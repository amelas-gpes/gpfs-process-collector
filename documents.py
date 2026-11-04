"""Scoped local document persistence and complete, bounded corpus extraction.

Parsing is deliberately separate from add(): callers enqueue extract(scope, id) on
a worker. SQLite transactions publish a complete index atomically. No macros,
formulas, embedded PDF actions, external links or uploaded code are executed.
"""
from __future__ import annotations

import csv
from contextlib import contextmanager, ExitStack
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import secrets
import sqlite3
import sys
import threading
import time
import warnings
import zipfile
from xml.etree import ElementTree

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FILES_PER_SCOPE = 20
MAX_PDF_PAGES = 500
MAX_SHEETS = 100
MAX_ROWS = 1_048_576
MAX_CELLS = 2_000_000
MAX_CELL_CHARS = 100_000
MAX_INDEX_BYTES = 64 * 1024 * 1024
MAX_CHUNKS = 50_000
MAX_CHUNK_CHARS = 6000
MAX_ZIP_INFLATED_BYTES = 512 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ZIP_RATIO = 500
MAX_PDF_PAGE_BYTES = 16 * 1024 * 1024
MAX_PDF_CONTENT_BYTES = 128 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_INVENTORY_BYTES = 50 * 1024
EXTRACTION_VERSION = 2  # Includes mixed visual coverage and decoded PDF bounds.
INITIAL_SUMMARY_NOTE = ('Written from the initial review selection. Later review may have changed coverage; '
                        'current review status and limitations are shown separately.')
SUPPORTED_TYPES = {'.pdf': 'application/pdf', '.png': 'image/png',
                   '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                   '.xlsm': 'application/vnd.ms-excel.sheet.macroEnabled.12',
                   '.csv': 'text/csv', '.xls': 'application/vnd.ms-excel'}


class DocumentError(ValueError):
    """A safe user-facing upload/extraction failure."""


class ExtractionError(DocumentError):
    pass


def _private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise DocumentError('Document storage cannot use a symbolic-link directory.')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def _atomic_write(path, data):
    temporary = path.with_name('.pending-' + secrets.token_hex(12))
    try:
        with open(temporary, 'xb') as stream:
            os.chmod(temporary, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _context(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DocumentError('Document context must be an object.')
    # An upload keeps a small immutable account of where it was supplied. Do not
    # accidentally persist credentials or an unrestricted application snapshot.
    clean = {}
    for name in ('process_name', 'objective', 'latest_question', 'role', 'turn_id'):
        if name in value:
            text = value[name]
            if not isinstance(text, str) or len(text) > 6000:
                raise DocumentError('Document context contains an invalid text field.')
            clean[name] = text
    turns = value.get('turns', [])
    if not isinstance(turns, list) or len(turns) > 12:
        raise DocumentError('Document context accepts at most 12 recent turns.')
    if turns:
        clean['turns'] = []
        for turn in turns:
            if (not isinstance(turn, dict) or turn.get('role') not in ('user', 'assistant')
                    or not isinstance(turn.get('text'), str) or len(turn['text']) > 6000):
                raise DocumentError('Document context contains an invalid turn.')
            if 'id' in turn and (not isinstance(turn['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', turn['id'])):
                raise DocumentError('Document context contains an invalid turn ID.')
            clean['turns'].append({key: turn[key] for key in ('id', 'role', 'text') if key in turn})
    if len(json.dumps(clean).encode()) > 32 * 1024:
        raise DocumentError('Document context exceeds its 32 KiB allowance.')
    return clean


def _inventory_budget(inventory):
    """Keep every unit/count; shorten preview samples only, with an explicit flag."""
    units = inventory.get('page_inventory', inventory.get('sheets', []))
    changed = False
    while len(json.dumps(inventory, ensure_ascii=False).encode()) > MAX_INVENTORY_BYTES - 512:
        reduced = False
        for unit in units:
            for key in ('sample', 'header_sample'):
                if unit.get(key):
                    unit[key] = unit[key][:len(unit[key]) // 2]
                    unit['sample_truncated'] = True
                    reduced = changed = True
        if not reduced:
            raise ExtractionError('Full document inventory exceeds 50 KiB; no units or source content were silently omitted.')
    if changed:
        inventory['summary_limitations'] = ['Preview samples were shortened to keep inventory under 50 KiB. All unit names/counts and full indexed content are retained.']
    return inventory


class _Chunks:
    def __init__(self, document):
        self.document = document
        self.items = []
        self.characters = 0

    def add(self, source, label, text, location):
        if not isinstance(text, str):
            raise ExtractionError('Extracted document text was invalid.')
        # Split all content rather than dropping the tail of a long page/row.
        for index in range(0, max(1, len(text)), MAX_CHUNK_CHARS):
            part = text[index:index + MAX_CHUNK_CHARS]
            self.characters += len(part.encode('utf-8'))
            if self.characters > MAX_INDEX_BYTES or len(self.items) >= MAX_CHUNKS:
                raise ExtractionError('Document exceeds the 64 MiB text or 50,000-chunk indexing limit; no partial index was published.')
            chunk_id = f'{self.document["id"]}_{source}_c{index // MAX_CHUNK_CHARS + 1}'
            self.items.append({'id': chunk_id, 'label': label, 'text': part, 'location': location})


class DocumentStore:
    @staticmethod
    def extraction_current(record):
        return record.get('extraction_version') == EXTRACTION_VERSION

    @staticmethod
    def _read_record(record):
        analysis = record.get('analysis') or {}
        if analysis.get('summary') and not analysis.get('summary_basis'):
            # Existing overviews were also retained from the initial selection.
            # Its exact creation version was not saved; do not invent one or
            # write a migration merely to explain the historical scope.
            record['analysis'] = {**analysis, 'summary_basis': 'initial_review',
                                  'summary_basis_note': INITIAL_SUMMARY_NOTE,
                                  'summary_at_review_version': None}
        # Conservative read projection, not a bulk migration. Old exact chunks
        # remain available as provenance, but old parser capabilities cannot
        # authorize full coverage. Revisit explicitly reindexes the original.
        if record.get('status') in ('ready', 'partial', 'error') and not DocumentStore.extraction_current(record):
            notice = 'Saved extraction predates the current completeness checks. Revisit this file to re-index it before claiming a full review.'
            record['extraction_needs_reindex'] = True
            if record['status'] != 'error':
                record['status'] = 'partial'
            coverage = record.get('coverage') or {}
            record['coverage'] = {**coverage, 'indexed_units': 0,
                                  'limitations': list(dict.fromkeys([*coverage.get('limitations', []), notice]))}
            analysis = record.get('analysis') or {}
            record['analysis'] = {**analysis, 'phase': 'error', 'review_complete': False,
                                  'error': analysis.get('error') or notice}
        return record

    def __init__(self, root):
        self.root = _private_dir(root).resolve()
        self.db_path = self.root / 'documents.sqlite3'
        if self.db_path.is_symlink():
            raise DocumentError('Document database cannot be a symbolic link.')
        self._locks_guard = threading.Lock()
        self._locks = {}
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS scopes (scope TEXT PRIMARY KEY, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, record TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS document_scope ON documents(scope);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                    id UNINDEXED, document_id UNINDEXED, scope UNINDEXED,
                    label, text, location UNINDEXED, tokenize='unicode61');
            ''')
        self._permissions()

    def _permissions(self):
        for path in self.root.glob('documents.sqlite3*'):
            for attempt in range(6):
                try:
                    if path.is_file() and not path.is_symlink():
                        os.chmod(path, 0o600)
                    break
                except FileNotFoundError:
                    break  # A concurrent last connection may remove SQLite's WAL/SHM.
                except PermissionError:
                    # Windows may briefly deny metadata changes while SQLite
                    # opens/closes a sidecar. Retry only those transient targets;
                    # a persistent denial must still fail permission enforcement.
                    if (sys.platform != 'win32' or attempt == 5
                            or path.name not in ('documents.sqlite3-wal', 'documents.sqlite3-shm')):
                        raise
                    time.sleep(0.02)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            # SQLite WAL/SHM contain private document text too.
            self._permissions()
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
            self._permissions()

    @staticmethod
    def _scope_hash(token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', token):
            raise PermissionError('Unknown document scope.')
        return hashlib.sha256(token.encode()).hexdigest()

    def _authorize(self, db, scope):
        digest = self._scope_hash(scope)
        if not db.execute('SELECT 1 FROM scopes WHERE scope=?', (digest,)).fetchone():
            raise PermissionError('Unknown document scope.')
        return digest

    def create_scope(self):
        token = secrets.token_urlsafe(32)
        digest = self._scope_hash(token)
        with self._db() as db:
            db.execute('INSERT INTO scopes VALUES (?,?)', (digest, time.time()))
        _private_dir(self.root / digest)
        return token

    def _record(self, db, scope, document_id):
        digest = self._authorize(db, scope)
        row = db.execute('SELECT record FROM documents WHERE id=? AND scope=?', (document_id, digest)).fetchone()
        if not row:
            raise PermissionError('Document is not available in this interview.')
        return digest, self._read_record(json.loads(row['record']))

    def add(self, scope, filename, data, context=None):
        if not isinstance(filename, str) or not filename.strip() or len(filename) > 250:
            raise DocumentError('Choose a file with a valid name of at most 250 characters.')
        filename = filename.replace('\\', '/').rsplit('/', 1)[-1]
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_TYPES:
            raise DocumentError('Supported files are PDF, PNG, XLSX, XLSM, CSV and legacy XLS when xlrd is installed.')
        if not isinstance(data, bytes) or not data or len(data) > MAX_FILE_BYTES:
            raise DocumentError('Each document must contain 1 byte to 64 MiB.')
        attachment_context = _context(context)
        now = time.time()
        document_id = 'doc_' + secrets.token_hex(12)
        record = {'id': document_id, 'name': filename, 'filename': filename, 'kind': suffix[1:],
                  'media_type': SUPPORTED_TYPES[suffix], 'size': len(data),
                  'sha256': hashlib.sha256(data).hexdigest(), 'status': 'pending', 'archived': False,
                  'created_at': now, 'updated_at': now, 'context': attachment_context,
                  'inventory': {}, 'coverage': {'indexed_units': 0, 'total_units': 0, 'limitations': []},
                  'chunk_count': 0, 'error': None, 'analysis': {}, 'revision': 0,
                  'extraction_version': EXTRACTION_VERSION, 'extraction_needs_reindex': False}
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            digest = self._authorize(db, scope)
            count = db.execute('SELECT count(*) FROM documents WHERE scope=?', (digest,)).fetchone()[0]
            if count >= MAX_FILES_PER_SCOPE:
                raise DocumentError('This interview already has 20 documents, including archived originals.')
            directory = _private_dir(_private_dir(self.root / digest) / document_id)
            _atomic_write(directory / ('original' + suffix), data)
            db.execute('INSERT INTO documents VALUES (?,?,?)', (document_id, digest, json.dumps(record)))
        return record

    def list(self, scope, include_archived=False):
        with self._db() as db:
            digest = self._authorize(db, scope)
            records = [self._read_record(json.loads(row[0])) for row in db.execute('SELECT record FROM documents WHERE scope=? ORDER BY rowid', (digest,))]
        return records if include_archived else [record for record in records if not record['archived']]

    def get(self, scope, document_id):
        with self._db() as db:
            return self._record(db, scope, document_id)[1]

    def update(self, scope, document_id, changes):
        """Trusted orchestration metadata only; never pass an HTTP request dict here."""
        allowed = {'analysis', 'analysis_status', 'analysis_error', 'notes', 'status', 'error'}
        if not isinstance(changes, dict) or not set(changes) <= allowed:
            raise DocumentError('Unsupported document metadata update.')
        try:
            encoded = json.dumps(changes, allow_nan=False)
        except (TypeError, ValueError):
            raise DocumentError('Document metadata must contain JSON values.') from None
        if len(encoded.encode()) > 256 * 1024:
            raise DocumentError('Document analysis metadata exceeds 256 KiB.')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            _, record = self._record(db, scope, document_id)
            record.update(json.loads(encoded), updated_at=time.time(), revision=record['revision'] + 1)
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(record), document_id))
        return record

    def archive(self, scope, document_id, archived=True):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            _, record = self._record(db, scope, document_id)
            record.update(archived=bool(archived), updated_at=time.time(), revision=record['revision'] + 1)
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(record), document_id))
        return record

    def remove(self, scope, document_id):
        return self.archive(scope, document_id)

    def pending(self, scope):
        return [record for record in self.list(scope) if record['status'] in ('pending', 'indexing')]

    @staticmethod
    def _chunk(row, record):
        location = json.loads(row['location'])
        return {'id': row['id'], 'source_id': row['id'], 'document_id': row['document_id'],
                'name': record['name'], 'label': row['label'], 'text': row['text'],
                'location': location, **location}

    def chunks(self, scope, document_id, offset=0, limit=100):
        if (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
                or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500):
            raise DocumentError('Chunk pagination requires a nonnegative offset and limit between 1 and 500.')
        with self._db() as db:
            digest, record = self._record(db, scope, document_id)
            total = db.execute('SELECT count(*) FROM chunks WHERE scope=? AND document_id=?', (digest, document_id)).fetchone()[0]
            rows = db.execute('SELECT * FROM chunks WHERE scope=? AND document_id=? ORDER BY rowid LIMIT ? OFFSET ?',
                              (digest, document_id, limit, offset)).fetchall()
            return {'chunks': [self._chunk(row, record) for row in rows], 'total': total, 'offset': offset,
                    'next_offset': offset + len(rows) if offset + len(rows) < total else None}

    def source(self, scope, document_id, source_id):
        with self._db() as db:
            digest, record = self._record(db, scope, document_id)
            row = db.execute('SELECT * FROM chunks WHERE scope=? AND document_id=? AND id=?',
                             (digest, document_id, source_id)).fetchone()
            if not row:
                raise PermissionError('Document source is not available in this interview.')
            return self._chunk(row, record)

    def record_extracted_text(self, scope, document_id, source_id, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 100000:
            raise DocumentError('Visual transcription requires 1–100,000 characters; no text was truncated.')
        if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,200}', source_id):
            raise DocumentError('Choose an exact document source ID.')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            digest, record = self._record(db, scope, document_id)
            row = db.execute('SELECT * FROM chunks WHERE scope=? AND document_id=? AND id=?',
                             (digest, document_id, source_id)).fetchone()
            if not row:
                raise PermissionError('Document source is not available in this interview.')
            location = json.loads(row['location'])
            if not location.get('requires_vision') and location.get('origin') != 'ai_visual_transcription':
                raise DocumentError('Only an explicitly visual source may receive a visual transcription.')
            location.update(requires_vision=False, origin='ai_visual_transcription', verified=False)
            parts = [text[index:index + MAX_CHUNK_CHARS] for index in range(0, len(text), MAX_CHUNK_CHARS)]
            old = db.execute('SELECT id,text FROM chunks WHERE scope=? AND document_id=?', (digest, document_id)).fetchall()
            replaced = {source_id} | {item['id'] for item in old if item['id'].startswith(source_id + '_v')}
            remaining_bytes = sum(len(item['text'].encode()) for item in old if item['id'] not in replaced)
            if remaining_bytes + len(text.encode()) > MAX_INDEX_BYTES or len(old) - len(replaced) + len(parts) > MAX_CHUNKS:
                raise DocumentError('Visual transcription exceeds the document indexing limits.')
            db.execute('UPDATE chunks SET text=?,location=? WHERE scope=? AND document_id=? AND id=?',
                       (parts[0], json.dumps(location), digest, document_id, source_id))
            for item in old:
                if item['id'] != source_id and item['id'] in replaced:
                    db.execute('DELETE FROM chunks WHERE scope=? AND document_id=? AND id=?', (digest, document_id, item['id']))
            for index, part in enumerate(parts[1:], 2):
                db.execute('INSERT INTO chunks VALUES (?,?,?,?,?,?)',
                           (f'{source_id}_v{index}', document_id, digest, row['label'], part, json.dumps(location)))
            inventory = record['inventory']
            reviewed = inventory.setdefault('visual_transcribed_units', [])
            unit = location.get('page', 'image')
            if unit not in reviewed:
                reviewed.append(unit)
            # Unit presence detects the first visual read. Its content digest
            # also detects a later correction without using mutable review
            # progress/version counters as a source identity.
            record.setdefault('visual_transcription_hashes', {})[str(unit)] = hashlib.sha256(text.encode('utf-8')).hexdigest()
            coverage = record['coverage']
            # A mixed page has native text and a separate visual source, but is
            # still one unit. Visual transcription must not count it twice.
            coverage['indexed_units'] = inventory.get('text_only_pages', inventory.get('text_pages', 0)) + len(reviewed)
            coverage['limitations'] = [entry for entry in coverage['limitations'] if 'native visual review' not in entry]
            unresolved = [page for page in inventory.get('vision_pages', []) if page not in reviewed]
            if unresolved:
                coverage['limitations'].append(f'{len(unresolved)} pages still require native visual review.')
            coverage['limitations'].append('AI visual transcriptions are searchable but have not been independently verified.')
            coverage['limitations'] = list(dict.fromkeys(coverage['limitations']))
            record['inventory'] = _inventory_budget(inventory)
            record.update(status='partial', chunk_count=len(old) - len(replaced) + len(parts),
                          updated_at=time.time(), revision=record['revision'] + 1)
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(record), document_id))
        return record

    def original_path(self, scope, document_id):
        with self._db() as db:
            digest, record = self._record(db, scope, document_id)
        path = self.root / digest / document_id / ('original.' + record['kind'])
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise DocumentError('The original document is unavailable.')
        return path

    def extract(self, scope, document_id):
        self.get(scope, document_id)  # Authorize before retaining any worker lock.
        with self._locks_guard:
            lock = self._locks.setdefault(document_id, threading.Lock())
        with lock:
            record = self.get(scope, document_id)
            if record['archived'] or (record['status'] in ('ready', 'partial') and self.extraction_current(record)):
                return record
            self.update(scope, document_id, {'status': 'indexing', 'error': None})
            chunks = _Chunks(record)
            try:
                path = self.original_path(scope, document_id)
                extractor = {'pdf': _pdf, 'png': _png, 'xlsx': _workbook, 'xlsm': _workbook,
                             'csv': _csv, 'xls': _legacy_xls}[record['kind']]
                inventory, coverage = extractor(path, record, chunks)
                inventory = _inventory_budget(inventory)
                status = 'partial' if coverage['limitations'] else 'ready'
                with self._db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    digest, current = self._record(db, scope, document_id)
                    db.execute('DELETE FROM chunks WHERE document_id=? AND scope=?', (document_id, digest))
                    db.executemany('INSERT INTO chunks VALUES (?,?,?,?,?,?)',
                                   [(item['id'], document_id, digest, item['label'], item['text'], json.dumps(item['location'])) for item in chunks.items])
                    current.update(status=status, inventory=inventory, coverage=coverage,
                                   visual_transcription_hashes={},
                                   chunk_count=len(chunks.items), error=None, extraction_version=EXTRACTION_VERSION,
                                   extraction_needs_reindex=False, updated_at=time.time(), revision=current['revision'] + 1)
                    db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(current), document_id))
                return current
            except Exception as error:
                # Parser messages can contain source text; publish only controlled diagnostics.
                message = str(error) if isinstance(error, DocumentError) else 'The document could not be safely decoded. Its original is retained.'
                return self.update(scope, document_id, {'status': 'error', 'error': message})

    def search(self, scope, query, ids=None, limit=12):
        if not isinstance(query, str) or len(query) > 2000 or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise DocumentError('Search requires text and a limit between 1 and 100.')
        with self._db() as db:
            digest = self._authorize(db, scope)
            records = {record['id']: record for record in self.list(scope) if record['status'] in ('ready', 'partial')}
            if ids is not None:
                if not isinstance(ids, list) or len(ids) > MAX_FILES_PER_SCOPE or any(not isinstance(item, str) for item in ids):
                    raise DocumentError('Choose at most 20 document IDs to search.')
                for document_id in ids:
                    self._record(db, scope, document_id)
                records = {key: value for key, value in records.items() if key in ids}
            if not records:
                return []
            parameters = [digest, *records]
            where = 'scope=? AND document_id IN (' + ','.join('?' for _ in records) + ')'
            tokens = re.findall(r'\w+', query, re.UNICODE)[:40]
            if tokens:
                expression = ' OR '.join('"' + token[:100] + '"' for token in tokens)
                sql = 'SELECT *,bm25(chunks) AS rank FROM chunks WHERE chunks MATCH ? AND ' + where + ' ORDER BY rank LIMIT ?'
                parameters = [expression, *parameters, limit]
            else:
                sql = 'SELECT * FROM chunks WHERE ' + where + ' ORDER BY rowid LIMIT ?'
                parameters.append(limit)
            result = []
            for row in db.execute(sql, parameters):
                result.append(self._chunk(row, records[row['document_id']]))
            return result

    def page_input(self, scope, document_id, page_number):
        """Internal-only native PDF page input; page_number is one-based."""
        from pypdf import PdfReader, PdfWriter
        record = self.get(scope, document_id)
        if record['kind'] != 'pdf' or not isinstance(page_number, int) or isinstance(page_number, bool):
            raise DocumentError('Choose a PDF page by its one-based number.')
        reader = PdfReader(self.original_path(scope, document_id))
        if reader.is_encrypted:
            raise DocumentError('Encrypted PDFs must be unlocked before upload.')
        if not 1 <= page_number <= min(len(reader.pages), MAX_PDF_PAGES):
            raise DocumentError('That PDF page is unavailable.')
        writer = PdfWriter()
        writer.add_page(reader.pages[page_number - 1])
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()


def _pdf(path, record, chunks):
    from pypdf import PdfReader
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ExtractionError('Encrypted PDFs must be unlocked before upload; no pages were indexed.')
    count = len(reader.pages)
    if not 1 <= count <= MAX_PDF_PAGES:
        raise ExtractionError('PDF page count exceeds the 500-page limit or is empty; no partial index was published.')
    missing, failures, mixed, content_bytes, indexed, page_inventory = [], [], [], 0, 0, []
    for number, page in enumerate(reader.pages, 1):
        try:
            contents = page.get_contents()
            # ContentStream is a dictionary-like object and can be false even
            # when it contains decoded bytes. Test presence, not truthiness.
            length = len(contents.get_data()) if contents is not None else 0
            content_bytes += length
            if length > MAX_PDF_PAGE_BYTES or content_bytes > MAX_PDF_CONTENT_BYTES:
                raise ExtractionError('PDF decoded content exceeds 16 MiB per page or 128 MiB total; no partial index was published.')
            text = page.extract_text() or ''
            # Text extraction does not read image pixels, diagram geometry or
            # painted form contents. Detect paint operations without decoding
            # image pixels; decorative and meaningful graphics are both honest
            # review requirements until inspected.
            paints = {b'Do', b'INLINE IMAGE', b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*', b'sh'}
            visual = bool(contents is not None and any(operator in paints for _, operator in contents.operations))
        except DocumentError:
            raise
        except Exception:
            failures.append(number)
            page_inventory.append({'page': number, 'text_chars': 0, 'sample': '', 'requires_vision': True})
            chunks.add(f'p{number}', f'{record["name"]} · page {number}',
                       'PDF page text decoding failed. Native visual review is required; page contents have not been read.',
                       {'page': number, 'requires_vision': True, 'origin': 'visual_placeholder', 'text_decode_failed': True})
            continue
        if not text.strip():
            missing.append(number)
            page_inventory.append({'page': number, 'text_chars': 0, 'sample': '', 'requires_vision': True})
            chunks.add(f'p{number}', f'{record["name"]} · page {number}',
                       'PDF page contains no extractable text. Native visual review is required; page contents have not been read.',
                       {'page': number, 'requires_vision': True, 'origin': 'visual_placeholder'})
            continue
        chunks.add(f'p{number}', f'{record["name"]} · page {number}', text, {'page': number})
        if visual:
            mixed.append(number)
            chunks.add(f'p{number}_visual', f'{record["name"]} · page {number} · visual content',
                       'This PDF page also contains visual graphics. Its native text is indexed separately; graphic contents and layout require native visual review and have not been read.',
                       {'page': number, 'requires_vision': True, 'origin': 'visual_placeholder', 'native_text_preserved': True})
        page_inventory.append({'page': number, 'text_chars': len(text), 'sample': re.sub(r'\s+', ' ', text).strip()[:180],
                               'requires_vision': visual})
        indexed += 1
    limitations = []
    if missing:
        limitations.append(f'{len(missing)} pages contain no extractable text and require native visual review; they were not treated as read.')
    if failures:
        limitations.append(f'{len(failures)} pages could not be decoded and require review.')
    if mixed:
        limitations.append(f'{len(mixed)} pages contain native text plus graphics; text is preserved separately, but graphics and layout still require native visual review.')
    return ({'pages': count, 'page_inventory': page_inventory, 'text_pages': indexed, 'text_only_pages': indexed - len(mixed),
             'mixed_visual_pages': mixed, 'vision_pages': sorted(missing + failures + mixed), 'failed_pages': failures,
             'requires_vision': bool(missing or failures or mixed)}, {'indexed_units': indexed - len(mixed), 'total_units': count, 'limitations': limitations})


def _png(path, record, chunks):
    from PIL import Image
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as image:
            if image.format != 'PNG' or image.width * image.height > MAX_IMAGE_PIXELS:
                raise ExtractionError('The image is not PNG or exceeds 40 million pixels.')
            width, height = image.size
            image.verify()
        with Image.open(path) as image:
            image.load()
    chunks.add('image', f'{record["name"]} · image',
               f'PNG image {width} by {height} pixels. Image contents require native visual review; no OCR was performed.',
               {'image': True, 'requires_vision': True, 'origin': 'visual_placeholder'})
    return ({'images': 1, 'width': width, 'height': height, 'requires_vision': True},
            {'indexed_units': 0, 'total_units': 1, 'limitations': ['Image contents require native visual review; no OCR was performed.']})


def _zip_check(path):
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or len({item.filename for item in entries}) != len(entries):
                raise ExtractionError('Workbook ZIP has too many or duplicate entries.')
            total = 0
            for item in entries:
                total += item.file_size
                if (item.flag_bits & 1 or item.file_size > MAX_ZIP_MEMBER_BYTES or total > MAX_ZIP_INFLATED_BYTES
                        or (item.file_size > 1024 * 1024 and item.file_size / max(item.compress_size, 1) > MAX_ZIP_RATIO)):
                    raise ExtractionError('Workbook ZIP exceeds encryption, compression-ratio or inflated-size safety limits.')
                if item.filename.startswith('/') or '..' in Path(item.filename).parts:
                    raise ExtractionError('Workbook ZIP contains an unsafe member name.')
                if item.filename.lower().endswith(('.xml', '.rels')):
                    tail = b''
                    with archive.open(item) as stream:
                        while block := stream.read(65536):
                            # OOXML may be UTF-16/32; do not let NUL-separated
                            # declarations bypass the XML entity/DTD guard.
                            text = (tail + block).replace(b'\x00', b'').upper()
                            if b'<!DOCTYPE' in text or b'<!ENTITY' in text:
                                raise ExtractionError('Workbook XML declarations with external entities or DTDs are not supported.')
                            tail = text[-20:]
    except zipfile.BadZipFile:
        raise ExtractionError('Workbook is not a valid XLSX/XLSM ZIP file.') from None


def _cell_text(value):
    if value is None:
        return ''
    text = value.isoformat() if hasattr(value, 'isoformat') else str(value)
    if len(text) > MAX_CELL_CHARS:
        raise ExtractionError('A spreadsheet cell exceeds 100,000 characters; no partial index was published.')
    return text


def _formula_text(value):
    if isinstance(value, str):
        return _cell_text(value)
    # Recent OOXML readers expose array and data-table formulas as objects.
    # Their default repr contains a memory address, not the source formula.
    # Retain the serialized formula/range/input metadata without evaluating it.
    kind = getattr(value, 't', None)
    if kind not in ('array', 'dataTable'):
        raise ExtractionError('An unsupported spreadsheet formula type could not be preserved; no partial index was published.')
    attributes = dict(value)
    if kind == 'array':
        formula = getattr(value, 'text', None)
        if not isinstance(formula, str):
            raise ExtractionError('An array formula has no readable formula text; no partial index was published.')
        attributes['formula'] = formula
    return _cell_text(json.dumps(attributes, ensure_ascii=False, sort_keys=True))


def _row_chunks(record, chunks, sheet_index, sheet_name, rows):
    def get_column_letter(number):
        result = ''
        while number:
            number, remainder = divmod(number - 1, 26)
            result = chr(65 + remainder) + result
        return result
    buffer, start, end, high_col, count, cells, formulas, uncached = [], None, None, 0, 0, 0, 0, 0
    columns, header_sample, header_truncated = 0, '', False
    serial = 0

    def flush():
        nonlocal buffer, start, end, high_col, serial
        if buffer:
            serial += 1
            area = f'A{start}:{get_column_letter(max(1, high_col))}{end}'
            chunks.add(f's{sheet_index}_r{start}_{end}_b{serial}', f'{record["name"]} · {sheet_name}!{area}',
                       '\n'.join(buffer), {'sheet': sheet_name, 'sheet_index': sheet_index, 'range': area,
                                            'row_start': start, 'row_end': end})
            buffer, start, end, high_col = [], None, None, 0

    for row_number, row in rows:
        if row_number > MAX_ROWS:
            raise ExtractionError('A sheet exceeds 1,048,576 rows; no partial index was published.')
        count = max(count, row_number)
        values = []
        for column, value, formula, cached in row:
            cells += 1
            if cells > MAX_CELLS:
                raise ExtractionError('A sheet exceeds two million populated cells; no partial index was published.')
            if column > 16384:
                raise ExtractionError('A sheet exceeds 16,384 columns.')
            if formula:
                formulas += 1
                uncached += cached is None
                rendered = f'FORMULA (not executed) {_formula_text(formula)}; cached value (not recalculated): {_cell_text(cached) if cached is not None else "UNAVAILABLE"}'
            else:
                rendered = _cell_text(value)
            values.append(f'{get_column_letter(column)}{row_number}={rendered}')
        if not values:
            continue
        line = ' | '.join(values)
        columns = max(columns, max(item[0] for item in row))
        if not header_sample:
            header_sample, header_truncated = line[:180], len(line) > 180
        if buffer and (len('\n'.join(buffer)) + len(line) > MAX_CHUNK_CHARS or row_number - start >= 200):
            flush()
        start = row_number if start is None else start
        end, high_col = row_number, max(high_col, max(item[0] for item in row))
        buffer.append(line)
        if len(line) > MAX_CHUNK_CHARS:
            flush()
    flush()
    return {'name': sheet_name, 'index': sheet_index, 'rows': count, 'columns': columns,
            'header_sample': header_sample, 'header_sample_truncated': header_truncated, 'populated_cells': cells,
            'formula_cells': formulas, 'formulas_without_cached_values': uncached}


def _workbook(path, record, chunks):
    from openpyxl import load_workbook
    _zip_check(path)
    with ExitStack() as cleanup:
        archive = cleanup.enter_context(zipfile.ZipFile(path))
        book = load_workbook(path, read_only=True, data_only=False, keep_links=False, keep_vba=False)
        cleanup.callback(book.close)
        cached = load_workbook(path, read_only=True, data_only=True, keep_links=False, keep_vba=False)
        cleanup.callback(cached.close)
        if len(book.sheetnames) > MAX_SHEETS:
            raise ExtractionError('Workbook exceeds 100 sheets; no partial index was published.')
        inventory = []
        for index, name in enumerate(book.sheetnames, 1):
            sheet = book[name]
            if not hasattr(sheet, 'iter_rows'):
                inventory.append({'name': name, 'index': index, 'kind': 'chart_sheet', 'rows': 0,
                                  'columns': 0, 'header_sample': '',
                                  'populated_cells': 0, 'formula_cells': 0, 'formulas_without_cached_values': 0,
                                  'requires_vision': True, 'visibility': sheet.sheet_state})
                continue
            cache_sheet = cached[sheet.title]
            sheet.reset_dimensions()
            cache_sheet.reset_dimensions()

            def rows():
                for number, pair in enumerate(itertools.zip_longest(sheet.iter_rows(), cache_sheet.iter_rows()), 1):
                    raw, values = pair
                    if raw is None or values is None:
                        raise ExtractionError('Formula and cached-value row inventories do not agree.')
                    row = []
                    for column, cell in enumerate(raw, 1):
                        if cell.value is None:
                            continue
                        formula = cell.value if cell.data_type == 'f' else None
                        row.append((column, cell.value, formula, values[column - 1].value if column <= len(values) else None))
                    yield number, row
            item = _row_chunks(record, chunks, index, sheet.title, rows())
            item['visibility'] = sheet.sheet_state
            # openpyxl's read-only cell stream intentionally omits worksheet
            # drawings. Preserve their presence rather than claiming the tab
            # was fully read just because its cells were indexed.
            source_path = getattr(sheet, '_worksheet_path', None)
            if not isinstance(source_path, str):
                raise ExtractionError('Worksheet source location is unavailable; visual completeness could not be established.')
            source_path = PurePosixPath(source_path.lstrip('/'))
            relations_path = str(source_path.parent / '_rels' / (source_path.name + '.rels'))
            if relations_path in archive.namelist():
                with archive.open(relations_path) as stream:
                    relations = ElementTree.parse(stream).getroot()
                graphics = sorted({relation.get('Type', '').rsplit('/', 1)[-1] for relation in relations
                                   if relation.get('Type', '').rsplit('/', 1)[-1] in
                                   {'drawing', 'vmlDrawing', 'image', 'chart', 'oleObject', 'control', 'ctrlProp', 'diagramData', 'diagramLayout'}})
                if graphics:
                    item.update(requires_vision=True, unread_visual_parts=graphics)
            inventory.append(item)
            if sum(item['populated_cells'] for item in inventory) > MAX_CELLS:
                raise ExtractionError('Workbook exceeds two million populated cells; no partial index was published.')
        limitations = []
        missing = sum(item['formulas_without_cached_values'] for item in inventory)
        if missing:
            limitations.append(f'{missing} formula cells have no cached result. Formulas were indexed as text, never executed.')
        chart_sheets = sum(item.get('kind') == 'chart_sheet' for item in inventory)
        if chart_sheets:
            limitations.append(f'{chart_sheets} chart-only tabs have inventory entries but require visual review; no chart contents were inferred.')
        mixed_sheets = sum(bool(item.get('unread_visual_parts')) for item in inventory)
        if mixed_sheets:
            limitations.append(f'{mixed_sheets} worksheets contain drawings, charts, images or embedded objects that cell extraction does not read. Cell text is indexed; export the visual content as PDF or PNG for review. No graphic content was inferred.')
        if record['kind'] == 'xlsm':
            limitations.append('Macros are preserved in the original only and were never executed or interpreted.')
        return ({'sheets': inventory, 'sheet_count': len(inventory), 'rows': sum(item['rows'] for item in inventory),
                 'formula_cells': sum(item['formula_cells'] for item in inventory), 'macros_executed': False,
                 'formula_policy': 'Formula text and saved cached values only; no recalculation.'},
                {'indexed_units': len(inventory) - chart_sheets - mixed_sheets, 'total_units': len(inventory), 'limitations': limitations})


def _csv(path, record, chunks):
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig')
    except UnicodeError:
        raise ExtractionError('CSV must be UTF-8 or BOM-marked UTF-16; no lossy decoding was performed.') from None
    # Reject malformed quoting rather than silently merging cells/rows and
    # publishing the resulting interpretation as a complete index.
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    def rows():
        try:
            for number, row in enumerate(reader, 1):
                yield number, [(column, value, None, None) for column, value in enumerate(row, 1) if value]
        except csv.Error:
            raise ExtractionError('CSV has an invalid or oversized field; no partial index was published.') from None
    item = _row_chunks(record, chunks, 1, 'CSV', rows())
    return ({'sheets': [item], 'sheet_count': 1, 'rows': item['rows'], 'formula_policy': 'CSV cells are literal text; formulas are never executed.'},
            {'indexed_units': item['rows'], 'total_units': item['rows'], 'limitations': []})


def _legacy_xls(path, record, chunks):
    try:
        import xlrd
    except ImportError:
        raise ExtractionError('Legacy XLS requires xlrd, which is not installed. Save a copy as XLSX or CSV and upload that copy; the original is retained.') from None
    book = xlrd.open_workbook(path, on_demand=True)
    try:
        if book.nsheets > MAX_SHEETS:
            raise ExtractionError('Workbook exceeds 100 sheets.')
        sheets = []
        for index in range(book.nsheets):
            sheet = book.sheet_by_index(index)
            rows = ((number + 1, [(column + 1, sheet.cell_value(number, column), None, None)
                                  for column in range(sheet.ncols) if sheet.cell_value(number, column) != ''])
                    for number in range(sheet.nrows))
            sheets.append(_row_chunks(record, chunks, index + 1, sheet.name, rows))
        return ({'sheets': sheets, 'sheet_count': len(sheets), 'rows': sum(item['rows'] for item in sheets),
                 'formula_policy': 'Saved legacy cell results only; formula provenance may be unavailable.'},
                {'indexed_units': len(sheets), 'total_units': len(sheets),
                 'limitations': ['Legacy XLS exposes saved cell results; formulas/macros were not executed.']})
    finally:
        book.release_resources()
