"""Scoped local document persistence and complete, bounded corpus extraction.

Parsing is deliberately separate from add(): callers enqueue extract(scope, id) on
a worker. SQLite transactions publish a complete index atomically. No macros,
formulas, embedded PDF actions, external links or uploaded code are executed.
"""
from __future__ import annotations

import codecs
import csv
from contextlib import contextmanager, ExitStack
import hashlib
import importlib.util
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
import unicodedata
import zipfile
from xml.etree import ElementTree

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FILES_PER_SCOPE = 20
# Count limits. A file past one is indexed up to it and the rest is named in its coverage, the way
# unread pages and hidden sheets are: pages and sheets after the limit, a CSV's rows after the limit,
# a CSV row's columns after the limit, and every row after the one that would pass MAX_CELLS (stored
# cells of an XLSX, populated cells of a CSV) or no longer fits in the index (MAX_INDEX_BYTES and
# MAX_CHUNKS below). The safety limits that follow them still refuse the whole file.
MAX_PDF_PAGES = 500
MAX_SHEETS = 100
MAX_ROWS = 1_048_576
MAX_COLUMNS = 16_384
MAX_CELLS = 2_000_000
# Not a count limit. A longer cell is not something Excel writes (its own limit is 32,767
# characters); in a CSV it is most often a stray quote that swallowed the rows after it. Cutting the
# cell would index a mangled value as if it had been read, so this one still refuses the file.
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
MAX_CONTEXT_BYTES = 32 * 1024
# 5: a worksheet whose only VML drawing holds its cell comments' note boxes is no longer counted as
# containing a drawing (the comments themselves are indexed); 4: a PDF page whose only drawings are
# page furniture (rules, boxes, bullets) is no longer given a visual placeholder; 3: PDF annotations,
# delimited text, narrower spreadsheet ranges.
EXTRACTION_VERSION = 5
# The layouts of documents.sqlite3 this build opens: the oldest it upgrades in place, and the
# one it writes. SQLite keeps the number in the file (PRAGMA user_version; 0 in a store from
# before it was recorded). Raise the second number with any change an older build would
# misread. Keep this line a plain literal: desktop/manage.py reads it from an unpacked build
# without running it, so that the window never gives newer data to an older build.
STORE_FORMATS = (0, 3)
# Format 2: the full-text table indexes `scope`, so a search matches inside one interview
# instead of matching every interview's text and discarding most of it; and chunk_map, an
# ordinary table kept in step with it, finds sections by scope, file and section ID. FTS5
# can only look rows up by MATCH or rowid: a WHERE on its other columns reads every section
# ever stored. A build that knows only format 1 would leave chunk_map out of step.
CHUNKS_TABLE = ("CREATE VIRTUAL TABLE {name} USING fts5(id UNINDEXED, document_id UNINDEXED, scope, "
                "label, text, location UNINDEXED, tokenize='unicode61')")
# One section by its place in chunk_map; the join order is fixed so that FTS5 is only ever asked for a rowid.
CHUNK_JOIN = ' FROM chunk_map{index} CROSS JOIN chunks ON chunks.rowid=chunk_map.chunk_rowid WHERE '
CHUNK_ROWS = 'SELECT chunk_map.ordinal AS position,chunks.*' + CHUNK_JOIN.format(index='')
REINDEX_NOTICE = ('Process Collector was updated since this file was indexed, and its saved index predates the current completeness '
                  'checks. It does not count as a full review until the file has been re-indexed.')
# The sentence earlier builds wrote, which a later action may have saved with the record.
REINDEX_NOTICES = (REINDEX_NOTICE, 'Saved extraction predates the current completeness checks. Revisit this file to re-index it before claiming a full review.')
INITIAL_SUMMARY_NOTE = ('Written from the initial review selection. Later review may have changed coverage; '
                        'current review status and limitations are shown separately.')
SUPPORTED_TYPES = {'.pdf': 'application/pdf', '.png': 'image/png',
                   '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                   '.xlsm': 'application/vnd.ms-excel.sheet.macroEnabled.12',
                   '.csv': 'text/csv', '.xls': 'application/vnd.ms-excel'}


# The reader each kind of file is parsed with: (what the kind is called, module, package to install).
# CSV needs none. Readers are imported only when a file of their kind is read, so an interpreter
# without one starts normally; unavailable_readers() and extract() say which one is missing.
READERS = {'pdf': ('PDF', 'pypdf', 'pypdf'), 'png': ('PNG image', 'PIL', 'Pillow'),
           'xlsx': ('Excel workbook', 'openpyxl', 'openpyxl'), 'xlsm': ('Excel workbook', 'openpyxl', 'openpyxl')}


def missing_reader_message(kind, module=None):
    """Fixed wording for a file kind whose reader this interpreter lacks; never a parser's own text."""
    name, expected, package = READERS[kind]
    other = module and module != expected and re.fullmatch(r'[A-Za-z0-9_]{1,60}', module)
    return (f'This computer cannot read {name} files: the Python that runs Process Collector has no usable {package} package'
            + (f' (module {module} is missing)' if other else '') + '. Install the packages listed in requirements-documents.txt into '
            "that Python's own site-packages, then restart the app and retry. The app starts Python in isolated mode, "
            'which ignores packages installed for your user account only. The original is retained.')


def unavailable_readers():
    """The file kinds this interpreter cannot read, each with its message. Nothing is imported."""
    missing = {}
    for kind, (_, module, _) in READERS.items():
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing[kind] = missing_reader_message(kind)
    return missing


class DocumentError(ValueError):
    """A safe user-facing upload/extraction failure."""


class UnknownDocumentScope(PermissionError):
    """The saved interview has no matching document workspace in this store."""


class ExtractionError(DocumentError):
    pass


INDEX_FULL_MESSAGE = 'The text of this file does not fit in the 64 MiB, 50,000-section index; nothing of it was indexed.'


class _IndexFull(ExtractionError):
    """The index has no room for another section (MAX_INDEX_BYTES or MAX_CHUNKS).

    A reader catches it where one page or group of rows begins, takes that unit's sections back
    out (_Chunks.rollback) and stops there, so the index holds whole units only. Uncaught, it
    refuses the file with INDEX_FULL_MESSAGE.
    """
    def __init__(self):
        super().__init__(INDEX_FULL_MESSAGE)


# What earlier versions said when they refused a file over a count limit. This version reads such
# a file up to the limit, so a saved record refused with one of these can be retried (Retry review)
# instead of having to be added again. Every refusal this version still gives has other wording.
COUNT_LIMIT_REFUSALS = frozenset((
    'PDF page count exceeds the 500-page limit or is empty; no partial index was published.',
    'A sheet exceeds 1,048,576 rows; no partial index was published.',
    'A sheet exceeds two million populated cells; no partial index was published.',
    'A sheet exceeds 16,384 columns.',
    'Workbook exceeds two million stored cells; no partial index was published.',
    'Workbook exceeds two million populated cells; no partial index was published.',
    'Workbook exceeds 100 sheets; no partial index was published.',
    'Workbook exceeds two million stored cells.',
    'Workbook exceeds 100 sheets.',
))
COUNT_LIMIT_RETRY = 'An earlier version refused this file for its size. Retry review reads it up to the limits.'


class StoreFormatError(RuntimeError):
    """The saved store has a layout this build does not open. Nothing in it was changed."""


def store_format(db, formats, contents):
    """The format number a store holds, after refusing one outside what this build opens."""
    stored = db.execute('PRAGMA user_version').fetchone()[0]
    if not formats[0] <= stored <= formats[1]:
        raise StoreFormatError(
            f'The saved {contents} on this computer use store format {stored}, and this build of Process Collector '
            f'opens formats {formats[0]} to {formats[1]}. '
            + ('They were written by a newer build: open them with that build, or update this one.'
               if stored > formats[1] else 'They are too old for this build to upgrade.')
            + ' Nothing was changed.')
    return stored


LONG_PATH_THRESHOLD = 200


def _long_path(path):
    """Return the Windows extended-length form of a path that could exceed MAX_PATH.

    The store nests a 64-character scope digest, a document ID and a temporary
    upload name under the application directory. Without the system-wide
    long-path setting, Windows rejects paths over 260 characters once the
    checkout lives a few folders deep, and uploads then fail with
    FileNotFoundError. Only paths long enough to be at risk receive the
    ``\\\\?\\`` prefix, so ordinary paths the store returns stay plain and
    comparable. Callers apply this at the operating-system boundary only.
    """
    path = Path(path)
    if os.name != 'nt':
        return path
    raw = os.fspath(path)
    if raw.startswith(('\\\\?\\', '\\\\.\\')) or len(raw) < LONG_PATH_THRESHOLD:
        return path
    # The prefix disables normalization, so normalize first.
    raw = os.path.abspath(raw)
    if raw.startswith('\\\\'):
        return Path('\\\\?\\UNC\\' + raw[2:])
    return Path('\\\\?\\' + raw)


def _private_dir(path):
    path = Path(path)
    target = _long_path(path)
    if target.is_symlink():
        raise DocumentError('Document storage cannot use a symbolic-link directory.')
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target, 0o700)
    return path


def _atomic_write(path, data):
    target = _long_path(path)
    temporary = _long_path(path.with_name('.pending-' + secrets.token_hex(12)))
    try:
        with open(temporary, 'xb') as stream:
            os.chmod(temporary, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
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
    if context_bytes(clean) > MAX_CONTEXT_BYTES:
        raise DocumentError('Document context exceeds its 32 KiB allowance.')
    return clean


def context_bytes(context):
    """The size an upload context is held to: its JSON text in UTF-8.

    Not the ASCII-escaped form the record is written in, where every character
    outside ASCII costs six bytes or twelve: an interview in Russian, Greek or
    Chinese must not have a sixth of the allowance of one in English.
    """
    return len(json.dumps(context, ensure_ascii=False).encode('utf-8', 'surrogatepass'))


INVENTORY_LIMIT_MESSAGE = ('This file has more pages or sheets than its 50 KiB inventory can list, even without preview samples. '
                           'Split it into smaller files and add those. Nothing was indexed, and no unit or source content was silently omitted.')
TRANSCRIPTION_LIMIT_MESSAGE = ('The visual readings of this file no longer fit its 64 MiB text or 50,000-section index, so this reading was not stored. '
                               'Split the file into smaller files and add those; retrying the review will stop at the same place.')
SAMPLES_SHORTENED ='Preview samples were shortened to keep inventory under 50 KiB. All unit names/counts and full indexed content are retained.'
SAMPLES_OMITTED = 'Preview samples were left out to keep inventory under 50 KiB. All unit names/counts and full indexed content are retained.'


def _inventory_budget(inventory, strict=True):
    """Keep every unit/count; shorten preview samples only, with an explicit flag.

    A PDF of MAX_PDF_PAGES pages fits by construction: when samples shortened to
    nothing are not enough, the sample fields themselves are left out, and what
    remains for each page is its number, its character count and whether it
    needs visual reading. Room is kept for 'visual_transcribed_units' to name
    every page that awaits a visual reading, so recording those readings later
    cannot run out of space. With strict=False an inventory that still does
    not fit is returned as it is: a reading that was paid for is never refused
    over the size of this listing.
    """
    units = inventory.get('page_inventory', inventory.get('sheets', []))
    recorded = set(map(str, inventory.get('visual_transcribed_units', [])))
    awaited = [unit for unit in inventory.get('vision_pages', []) if str(unit) not in recorded]
    limit = MAX_INVENTORY_BYTES - 512 - (len(json.dumps(awaited)) + 32 if awaited else 0)

    def fits():
        return len(json.dumps(inventory, ensure_ascii=False).encode('utf-8', 'surrogatepass')) <= limit

    changed = False
    while not fits():
        reduced = False
        for unit in units:
            for key in ('sample', 'header_sample'):
                if unit.get(key):
                    unit[key] = unit[key][:len(unit[key]) // 2]
                    unit['sample_truncated'] = True
                    reduced = changed = True
        if not reduced:
            break
    if not fits():
        for unit in units:
            for key in ('sample', 'header_sample', 'sample_truncated', 'header_sample_truncated'):
                unit.pop(key, None)
        if strict and not fits():
            raise ExtractionError(INVENTORY_LIMIT_MESSAGE)
        # The notes below fit in the 512 bytes held back above.
        inventory.update(samples_omitted=True, summary_limitations=[SAMPLES_OMITTED])
    elif changed:
        inventory['summary_limitations'] = [SAMPLES_SHORTENED]
    return inventory


def _text_parts(text):
    start = 0
    while start < len(text):
        end = min(start + MAX_CHUNK_CHARS, len(text))
        if end < len(text):
            middle = start + MAX_CHUNK_CHARS // 2
            for separator in (' | ', '\n', ' '):
                boundary = text.rfind(separator, middle, end)
                if boundary >= middle:
                    end = boundary + len(separator)
                    break
        yield text[start:end]
        start = end


class _Chunks:
    def __init__(self, document):
        self.document = document
        self.items = []
        self.characters = 0

    def add(self, source, label, text, location):
        if not isinstance(text, str):
            raise ExtractionError('Extracted document text was invalid.')
        if not text.strip():
            return
        # Split all content rather than dropping the tail of a long page/row.
        for index, part in enumerate(_text_parts(text), 1):
            if not part.strip():
                continue
            self.characters += len(part.encode('utf-8'))
            if self.characters > MAX_INDEX_BYTES or len(self.items) >= MAX_CHUNKS:
                raise _IndexFull()
            chunk_id = f'{self.document["id"]}_{source}_c{index}'
            self.items.append({'id': chunk_id, 'label': label, 'text': part, 'location': location})

    def mark(self):
        """Where the index stands before a unit is added; rollback() returns to it."""
        return len(self.items), self.characters

    def rollback(self, mark):
        del self.items[mark[0]:]
        self.characters = mark[1]


def _transcribed_coverage(inventory, coverage):
    """Count every unit in inventory['visual_transcribed_units'] as read, once."""
    reviewed = inventory['visual_transcribed_units']
    # A mixed page has native text and a separate visual source, but is
    # still one unit. Visual transcription must not count it twice.
    coverage['indexed_units'] = inventory.get('text_only_pages', inventory.get('text_pages', 0)) + len(reviewed)
    coverage['visual_pending_units'] = len(set(inventory.get('vision_pages', ['image'] if inventory.get('images') else [])) - set(reviewed))
    coverage['limitations'] = [entry for entry in coverage['limitations'] if 'native visual review' not in entry]
    unresolved = [page for page in inventory.get('vision_pages', []) if page not in reviewed]
    if unresolved:
        coverage['limitations'].append(f'{len(unresolved)} pages still require native visual review.')
    coverage['limitations'].append('AI visual transcriptions are searchable but have not been independently verified.')
    coverage['limitations'] = list(dict.fromkeys(coverage['limitations']))


def _carry_transcriptions(saved, chunks, inventory, coverage):
    """Keep stored AI visual transcriptions where a re-index finds only a placeholder again.

    The parser cannot reproduce a transcription: it came from a paid review, and
    notes and confirmed company connections cite its exact text. Only
    record_extracted_text replaces one, when a new reading actually arrives.
    Returns each kept source ID with the placeholder sentence the parser wrote
    for it now, and the content digest of each kept unit. The review that asks
    for a new reading presents that sentence, not the stored transcription.
    """
    transcribed = {row['id']: row['text'] for row in saved
                   if json.loads(row['location']).get('origin') == 'ai_visual_transcription'}
    kept, digests, units, items = {}, {}, [], []
    for item in chunks.items:
        if not item['location'].get('requires_vision') or item['id'] not in transcribed:
            items.append(item)  # Text the parser now reads itself replaces an earlier transcription.
            continue
        parts = [transcribed[item['id']]]
        while f'{item["id"]}_v{len(parts) + 1}' in transcribed:
            parts.append(transcribed[f'{item["id"]}_v{len(parts) + 1}'])
        location = {**item['location'], 'requires_vision': False, 'origin': 'ai_visual_transcription', 'verified': False}
        chunks.characters += sum(len(part.encode('utf-8')) for part in parts) - len(item['text'].encode('utf-8'))
        items.append({**item, 'text': parts[0], 'location': location})
        items.extend({'id': f'{item["id"]}_v{index}', 'label': item['label'], 'text': part, 'location': location}
                     for index, part in enumerate(parts[1:], 2))
        unit = location.get('page', 'image')
        if unit not in units:
            units.append(unit)
        digests[str(unit)] = hashlib.sha256(''.join(parts).encode('utf-8')).hexdigest()
        kept[item['id']] = item['text']
    if kept:
        if chunks.characters > MAX_INDEX_BYTES or len(items) > MAX_CHUNKS:
            raise ExtractionError('Document exceeds the 64 MiB text or 50,000-chunk indexing limit; no partial index was published.')
        chunks.items = items
        inventory['visual_transcribed_units'] = units
        _transcribed_coverage(inventory, coverage)
    return kept, digests


def reread_placeholder(record, source_id):
    """The parser's sentence for a kept source that still awaits its new reading, else None.

    A scan repeats one sentence on every page, so the record holds each distinct
    sentence once (visual_reread_basis) and each pending source only its position.
    A record written before that holds the sentence itself.
    """
    value = (record.get('visual_reread_pending') or {}).get(source_id)
    if isinstance(value, str):
        return value
    sentences = (record.get('visual_reread_basis') or {}).get('placeholders') or []
    return sentences[value] if type(value) is int and 0 <= value < len(sentences) else None


def unread_view(record, unit):
    """Inventory and coverage as the request for a new reading of one kept unit shows them.

    The stored record counts a kept transcription as read: it is searchable and
    citable. The request that asks for its new reading supplies the parser's
    placeholder with the page or image, so the file-level figures in that same
    request describe the unit as not yet read, as the parser alone left it.
    Nothing is stored; the record is not changed.
    """
    inventory, coverage = (json.loads(json.dumps(record.get(key) or {})) for key in ('inventory', 'coverage'))
    reviewed = inventory.get('visual_transcribed_units')
    parsed = (record.get('visual_reread_basis') or {}).get('limitations')
    if not isinstance(reviewed, list) or unit not in reviewed or not isinstance(parsed, list):
        return inventory, coverage
    reviewed.remove(unit)
    coverage['limitations'] = list(parsed)
    if reviewed:
        _transcribed_coverage(inventory, coverage)
    else:
        del inventory['visual_transcribed_units']
        coverage['visual_pending_units'] = len(inventory.get('vision_pages', ['image'] if inventory.get('images') else []))
        coverage['indexed_units'] = inventory.get('text_only_pages', inventory.get('text_pages', 0))
    return inventory, coverage


def _chunk(row, record):
    location = json.loads(row['location'])
    return {'id': row['id'], 'source_id': row['id'], 'document_id': row['document_id'],
            'name': record['name'], 'label': row['label'], 'text': row['text'],
            'location': location, **location}


class _DocumentReader:
    """Read chunks using one authorized scope and its matching file records."""
    def __init__(self, db, digest, records, state=None):
        # state: a digest of every stored record of the scope as this snapshot read it. A file's
        # sections only ever change together with its record, so equal states read equal content.
        self.db, self.digest, self.records, self.state = db, digest, records, state
        # Where each chunk this reader returned sits in the index, for neighbours().
        self._positions = {}

    def _read(self, row, record):
        self._positions[row['id']] = row['position']
        return _chunk(row, record)

    def neighbours(self, document_id, source_id, span=1):
        """The chunks next to one chunk of a file: the following ones first, then the preceding ones.

        Only for a chunk this reader returned from search() or chunk_rows(); otherwise nothing.
        A matching passage is usually continued, or introduced, by the text beside it.
        """
        position, record = self._positions.get(source_id), self.records.get(document_id)
        if position is None or record is None:
            return []
        after = self.db.execute(CHUNK_ROWS + 'chunk_map.scope=? AND chunk_map.document_id=? '
                                'AND chunk_map.ordinal>? ORDER BY chunk_map.ordinal LIMIT ?', (self.digest, document_id, position, span)).fetchall()
        before = self.db.execute(CHUNK_ROWS + 'chunk_map.scope=? AND chunk_map.document_id=? '
                                 'AND chunk_map.ordinal<? ORDER BY chunk_map.ordinal DESC LIMIT ?', (self.digest, document_id, position, span)).fetchall()
        return [self._read(row, record) for row in (*after, *before)]

    def prior_sources(self, source_ids):
        if not isinstance(source_ids, (list, tuple, set)) or len(source_ids) > 500:
            raise DocumentError('Choose at most 500 prior document source IDs.')
        prefixes = tuple(identity + '_' for identity in self.records)
        requested = dict.fromkeys(source_id for source_id in source_ids if isinstance(source_id, str)
                                  and len(source_id) <= 200 and source_id.startswith(prefixes))
        if not requested:
            return []
        placeholders = ','.join('?' for _ in requested)
        rows = self.db.execute('SELECT chunk_map.ordinal AS position,chunks.*' + CHUNK_JOIN.format(index=' INDEXED BY chunk_map_id')
                               + f'chunk_map.scope=? AND chunk_map.id IN ({placeholders})', (self.digest, *requested))
        found = {row['id']: self._read(row, self.records[row['document_id']]) for row in rows
                 if row['document_id'] in self.records and row['id'].startswith(row['document_id'] + '_')}
        # The caller's citation order decides which excerpts survive the context budget.
        return [found[source_id] for source_id in requested if source_id in found]

    def chunk_rows(self, document_id, offset, limit):
        record = self.records[document_id]
        rows = self.db.execute(CHUNK_ROWS + 'chunk_map.scope=? AND chunk_map.document_id=? '
                               'ORDER BY chunk_map.ordinal LIMIT ? OFFSET ?', (self.digest, document_id, limit, offset))
        return [self._read(row, record) for row in rows]

    def chunks(self, document_id, offset=0, limit=100):
        total = self.db.execute('SELECT count(*) FROM chunk_map WHERE scope=? AND document_id=?',
                                (self.digest, document_id)).fetchone()[0]
        chunks = self.chunk_rows(document_id, offset, limit)
        end = offset + len(chunks)
        return {'chunks': chunks, 'total': total, 'offset': offset, 'next_offset': end if end < total else None}

    def search(self, query, ids, limit):
        if ids is not None:
            if not isinstance(ids, list) or len(ids) > MAX_FILES_PER_SCOPE or any(not isinstance(item, str) for item in ids):
                raise DocumentError('Choose at most 20 document IDs to search.')
            if any(identity not in self.records for identity in ids):
                raise PermissionError('Document is not available in this interview.')
        records = {key: record for key, record in self.records.items() if not record['archived']
                   and record['status'] in ('ready', 'partial') and (ids is None or key in ids)}
        if not records:
            return []
        parameters = [self.digest, *records]
        where = 'scope=? AND document_id IN (' + ','.join('?' for _ in records) + ')'
        normalized = unicodedata.normalize('NFKC', query).casefold()
        # Keep combining marks attached to the preceding letters (e.g. Devanagari), including in lookups of legacy rows.
        tokens = ''.join(ch if ch.isalnum() or unicodedata.category(ch).startswith('M') else ' ' for ch in normalized).split()[:40]
        if tokens:
            # The words of an ordinary answer match most sections of every interview. Matching
            # inside this interview's scope keeps the work to its own files; the words themselves
            # are looked for in label and text only, and only those two columns are ranked.
            expression = ('scope : "' + self.digest + '" AND text : ('
                          + ' OR '.join('"' + token[:100] + '"' for token in tokens) + ')')
            sql = ('SELECT (SELECT ordinal FROM chunk_map WHERE chunk_map.scope=chunks.scope AND chunk_map.document_id=chunks.document_id AND chunk_map.id=chunks.id) AS position,*,bm25(chunks, 0, 0, 0, 1, 1, 0) AS rank FROM chunks WHERE chunks MATCH ? AND '
                   + where + ' ORDER BY rank LIMIT ?')
            parameters = [expression, *parameters, limit]
        else:
            sql = (CHUNK_ROWS + 'chunk_map.scope=? AND chunk_map.document_id IN (' + ','.join('?' for _ in records)
                   + ') ORDER BY chunk_map.ordinal LIMIT ?')
            parameters.append(limit)
        hits = [self._read(row, records[row['document_id']]) for row in self.db.execute(sql, parameters)]
        if tokens and (not hits or not normalized.isascii()):
            words = tuple(dict.fromkeys(word[:100] for word in tokens))
            exact = {word:re.compile(r'(?<!\w)'+re.escape(word)+r'(?!\w)') for word in words if word.isascii()}
            def score(body):
                if body.isascii(): return 0  # Native FTS already handled this section's word boundaries.
                body = unicodedata.normalize('NFKC', body).casefold()
                return sum(bool(exact[word].search(body)) if word in exact else word in body for word in words)
            self.db.create_function('document_match',1,score,deterministic=True)
            sql = (CHUNK_ROWS + 'chunk_map.scope=? AND chunk_map.document_id IN (' + ','.join('?' for _ in records)
                   + ') AND document_match(chunks.text)>0 ORDER BY document_match(chunks.text) DESC, chunk_map.chunk_rowid LIMIT ?')
            matches = [self._read(row,records[row['document_id']]) for row in self.db.execute(sql,[self.digest,*records,limit])]
            unique = {}
            for chunk in [*hits,*matches]: unique.setdefault(chunk['id'],chunk)
            return list(unique.values())[:limit]
        return hits


class DocumentStore:
    trace = None
    @staticmethod
    def extraction_current(record):
        # A higher number was written by a newer build that shares this store. That index is
        # not out of date: do not call it older than this build's checks, hide its coverage,
        # or re-extract it with this build's older parser.
        version = record.get('extraction_version')
        return type(version) is int and version >= EXTRACTION_VERSION

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
        # authorize full coverage. check_extraction compares the saved index
        # with what the current parser reads, on this computer and at no cost;
        # only when they differ does Revisit have to re-index the original.
        if record.get('status') == 'error' and record.get('error') in COUNT_LIMIT_REFUSALS:
            # Refused whole by an earlier version for passing a count limit. Its original is kept,
            # and this version reads it up to the limit, so it is offered Retry review again.
            record.update(error=COUNT_LIMIT_RETRY, retryable=True)
        version = record.get('extraction_version')
        # Stated on every read, never trusted from a saved copy of this projection.
        record.pop('indexed_by_newer_build', None)
        if type(version) is int and version > EXTRACTION_VERSION:
            record['indexed_by_newer_build'] = True
        checked = record.pop('reindex_check', None)
        if record.get('status') in ('ready', 'partial', 'error') and not DocumentStore.extraction_current(record):
            record['extraction_needs_reindex'] = True
            if record['status'] != 'error':
                record['status'] = 'partial'
                # 'pending' until this build has compared the index; then why the comparison did not settle it.
                settled = (isinstance(checked, dict) and checked.get('extraction_version') == EXTRACTION_VERSION
                           and checked.get('outcome') in ('changed', 'failed'))
                record['reindex_check'] = checked if settled else {'outcome': 'pending'}
            coverage = record.get('coverage') or {}
            record['coverage'] = {**coverage, 'indexed_units': 0,
                                  'limitations': list(dict.fromkeys([*(entry for entry in coverage.get('limitations', [])
                                                                       if entry not in REINDEX_NOTICES), REINDEX_NOTICE]))}
            # Its own phase, not 'error': nothing failed, the application was updated. An error the
            # review itself recorded stays as it is and does not stand in for this explanation.
            analysis = record.get('analysis') or {}
            record['analysis'] = {**analysis, 'phase': 'reindex_required', 'review_complete': False,
                                  **({'error': None} if analysis.get('error') in REINDEX_NOTICES else {})}
        return record

    def __init__(self, root):
        self.root = _private_dir(root).resolve()
        self.db_path = self.root / 'documents.sqlite3'
        if self.db_path.is_symlink():
            raise DocumentError('Document database cannot be a symbolic link.')
        self._interaction = threading.local()
        self._locks_guard = threading.Lock()
        self._locks = {}
        self.diagnostic = None  # Set by the server to its bounded local event log.
        # Before any statement that creates or changes anything in the file.
        probe = sqlite3.connect(_long_path(self.db_path), timeout=30)
        try:
            stored = store_format(probe, STORE_FORMATS, 'documents')
        finally:
            probe.close()
        with self._db() as db:
            # One transaction: another build or window may open the same file at this moment, and
            # a store is either wholly at its earlier format or wholly at this one.
            db.execute('BEGIN IMMEDIATE')
            stored = store_format(db, STORE_FORMATS, 'documents')
            for statement in ('CREATE TABLE IF NOT EXISTS scopes (scope TEXT PRIMARY KEY, created REAL NOT NULL)',
                              'CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, scope TEXT NOT NULL, record TEXT NOT NULL)',
                              'CREATE INDEX IF NOT EXISTS document_scope ON documents(scope)'):
                db.execute(statement)
            earlier = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='chunks'").fetchone()) and stored < 2
            if earlier:
                # Formats 0 and 1 kept `scope` unindexed. Rebuild the full-text table once, row for
                # row and with the same rowids, then describe it in chunk_map.
                db.execute(CHUNKS_TABLE.format(name='chunks_scoped'))
                db.execute('INSERT INTO chunks_scoped(rowid,id,document_id,scope,label,text,location) '
                           'SELECT rowid,id,document_id,scope,label,text,location FROM chunks')
                db.execute('DROP TABLE chunks')
                db.execute('ALTER TABLE chunks_scoped RENAME TO chunks')
                db.execute('DROP TABLE IF EXISTS chunk_map')
            elif not db.execute("SELECT 1 FROM sqlite_master WHERE name='chunks'").fetchone():
                db.execute(CHUNKS_TABLE.format(name='chunks'))
            for statement in ('CREATE TABLE IF NOT EXISTS chunk_map (scope TEXT NOT NULL, document_id TEXT NOT NULL, id TEXT NOT NULL, '
                              'chunk_rowid INTEGER NOT NULL, PRIMARY KEY (scope, document_id, id)) WITHOUT ROWID',
                              'CREATE INDEX IF NOT EXISTS chunk_map_id ON chunk_map(scope, id)',
                              # The order of a file's sections, and so every paged read of them.
                              'CREATE INDEX IF NOT EXISTS chunk_map_order ON chunk_map(scope, document_id, chunk_rowid)'):
                db.execute(statement)
            if earlier:
                db.execute('INSERT OR IGNORE INTO chunk_map SELECT scope, document_id, id, rowid FROM chunks ORDER BY rowid')
            if 'ordinal' not in {row[1] for row in db.execute('PRAGMA table_info(chunk_map)')}:
                db.execute('ALTER TABLE chunk_map ADD COLUMN ordinal INTEGER')
                db.execute('UPDATE chunk_map SET ordinal=chunk_rowid*256')
                for row in db.execute("SELECT scope,document_id,id FROM chunk_map WHERE id GLOB '*_v[0-9]*'").fetchall():
                    parent, suffix = row['id'].rsplit('_v',1)
                    if suffix.isdecimal() and 1<int(suffix)<256:
                        db.execute('UPDATE chunk_map SET ordinal=COALESCE((SELECT ordinal+? FROM chunk_map WHERE scope=? AND document_id=? AND id=?),ordinal) WHERE scope=? AND document_id=? AND id=?',
                                   (int(suffix)-1,row['scope'],row['document_id'],parent,row['scope'],row['document_id'],row['id']))
            db.execute('CREATE INDEX IF NOT EXISTS chunk_map_ordinal ON chunk_map(scope,document_id,ordinal)')
            if stored != STORE_FORMATS[1]:
                db.execute('PRAGMA user_version=%d' % STORE_FORMATS[1])
        self._permissions()

        self._clean_orphaned_originals()

    def _clean_orphaned_originals(self):
        # add() holds this writer lock from before creating its folder through the INSERT.
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            for directory in self.root.iterdir():
                if not re.fullmatch(r'[0-9a-f]{64}',directory.name) or directory.is_symlink() or directory.is_junction() or not directory.is_dir(): continue
                for child in directory.iterdir():
                    if not re.fullmatch(r'doc_[0-9a-f]{24}',child.name) or child.is_symlink() or child.is_junction() or not child.is_dir(): continue
                    if db.execute('SELECT 1 FROM documents WHERE scope=? AND id=?',(directory.name,child.name)).fetchone(): continue
                    self._remove_original_files(child)

    @staticmethod
    def _remove_original_files(directory):
        for file in directory.iterdir():
            if (file.name in {'original'+suffix for suffix in SUPPORTED_TYPES} or re.fullmatch(r'\.pending-[0-9a-f]{24}',file.name)) and not file.is_symlink():
                file.unlink(missing_ok=True)
        if not any(directory.iterdir()): directory.rmdir()

    @contextmanager
    def review_lease(self, scope, document_id):
        # Scope authorization precedes any use of the ID in a filesystem path. The OS releases the lock on process exit.
        record = self.get(scope, document_id)
        lockfile = self.root / (record['id'] + '.review.lock')
        with open(_long_path(lockfile), 'a+b') as stream:
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, PermissionError):
                yield False
            else:
                yield True

    def _permissions(self):
        for path in _long_path(self.root).glob('documents.sqlite3*'):
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
    def interactive_write(self):
        self._interaction.active = True
        try:
            yield
        except sqlite3.OperationalError as error:
            if getattr(error,'sqlite_errorcode',0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise DocumentError('The document index is being saved. Retry the file action in a moment.') from None
            raise
        finally:
            self._interaction.active = False

    @contextmanager
    def _db(self):
        db = sqlite3.connect(_long_path(self.db_path), timeout=.3 if getattr(self._interaction,'active',False) else 30)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA secure_delete=ON')
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
        if isinstance(token,str) and getattr(type(token),'document_scope_digest',False) and re.fullmatch(r'sha256:[0-9a-f]{64}',token):
            return token[7:]
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', token):
            raise UnknownDocumentScope('Unknown document scope.')
        return hashlib.sha256(token.encode()).hexdigest()

    def _authorize(self, db, scope):
        digest = self._scope_hash(scope)
        if not db.execute('SELECT 1 FROM scopes WHERE scope=?', (digest,)).fetchone():
            raise UnknownDocumentScope('Unknown document scope.')
        return digest

    def revoke_scope(self, scope):
        with self._db() as db:
            digest = self._authorize(db, scope)
            db.execute('DELETE FROM scopes WHERE scope=?',(digest,))

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
        if suffix == '.png' and len(data) >= 24 and data.startswith(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'):
            if int.from_bytes(data[16:20], 'big') * int.from_bytes(data[20:24], 'big') > MAX_IMAGE_PIXELS:
                raise DocumentError('This image exceeds 40 million pixels. Resize the image before uploading it.')
        attachment_context = _context(context)
        if suffix == '.xls' and importlib.util.find_spec('xlrd') is None:
            raise DocumentError('Legacy XLS requires xlrd. Save a copy as XLSX or CSV and attach that copy.')
        now = time.time()
        document_id = 'doc_' + secrets.token_hex(12)
        record = {'id': document_id, 'name': filename, 'filename': filename, 'kind': suffix[1:],
                  'media_type': SUPPORTED_TYPES[suffix], 'size': len(data),
                  'sha256': hashlib.sha256(data).hexdigest(), 'status': 'pending', 'archived': False,
                  'created_at': now, 'updated_at': now, 'context': attachment_context,
                  'inventory': {}, 'coverage': {'indexed_units': 0, 'total_units': 0, 'limitations': []},
                  'chunk_count': 0, 'error': None, 'analysis': {}, 'revision': 0,
                  'extraction_version': EXTRACTION_VERSION, 'extraction_needs_reindex': False}
        original = None
        try:
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                digest = self._authorize(db, scope)
                found = db.execute("SELECT record FROM documents WHERE scope=? AND "
                                   "json_extract(record,'$.sha256')=? AND json_extract(record,'$.kind')=? "
                                   "ORDER BY json_extract(record,'$.archived') LIMIT 1",
                                   (digest, record['sha256'], record['kind'])).fetchone()
                if found:
                    existing = json.loads(found['record'])
                    restored = existing['archived']
                    if restored:
                        existing.update(archived=False, updated_at=now, revision=existing['revision'] + 1)
                        db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(existing), existing['id']))
                    return {**self._read_record(existing), 'duplicate_upload': True, 'restored_upload': restored}
                count = db.execute('SELECT count(*) FROM documents WHERE scope=?', (digest,)).fetchone()[0]
                if count >= MAX_FILES_PER_SCOPE:
                    raise DocumentError('This interview already has 20 documents, including archived originals.')
                directory = _private_dir(_private_dir(self.root / digest) / document_id)
                original = directory / ('original' + suffix)
                _atomic_write(original, data)
                db.execute('INSERT INTO documents VALUES (?,?,?)', (document_id, digest, json.dumps(record)))
        except BaseException:
            if original is not None:
                # The commit can fail after the original is written. Check before removing its only copy.
                with self._db() as check:
                    saved = check.execute('SELECT 1 FROM documents WHERE id=?', (document_id,)).fetchone()
                if not saved:
                    _long_path(original).unlink(missing_ok=True)
                    _long_path(original.parent).rmdir()
            raise
        return record

    def _records(self, db, digest):
        rows = db.execute('SELECT record FROM documents WHERE scope=? ORDER BY rowid', (digest,))
        return [self._read_record(json.loads(row[0])) for row in rows]

    def list(self, scope, include_archived=False):
        with self._db() as db:
            records = self._records(db, self._authorize(db, scope))
        return records if include_archived else [record for record in records if not record['archived']]

    @contextmanager
    def interview_reader(self, scope):
        """Bind file states, citations, search and excerpts to the same read snapshot."""
        with self._db() as db:
            db.execute('BEGIN')
            digest = self._authorize(db, scope)
            rows = db.execute('SELECT record FROM documents WHERE scope=? ORDER BY rowid', (digest,)).fetchall()
            records = {record['id']: record for record in (self._read_record(json.loads(row[0])) for row in rows)}
            state = hashlib.sha256('\n'.join([str(EXTRACTION_VERSION), *(row[0] for row in rows)]).encode('utf-8', 'surrogatepass')).hexdigest()
            yield _DocumentReader(db, digest, records, state)

    def get(self, scope, document_id):
        with self._db() as db:
            return self._record(db, scope, document_id)[1]

    def update(self, scope, document_id, changes):
        """Trusted orchestration metadata only; never pass an HTTP request dict here."""
        allowed = {'analysis', 'analysis_status', 'analysis_error', 'notes', 'status', 'error', 'error_code', 'retryable'}
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
        if self.trace:
            recorded_changes = dict(changes)
            analysis = recorded_changes.get("analysis")
            if isinstance(analysis, dict):
                review_fields = ("phase","version","cursor","intent_version","disposition","review_complete",
                                 "reviewed_chunks","total_chunks","retry_required","review_stopped","review_requests")
                recorded_changes["analysis"] = {k:analysis[k] for k in review_fields if k in analysis}
                if set(analysis) - set(review_fields):
                    recorded_changes["analysis"]["content_omitted"] = "document_review_content"
            self.trace.emit("document.metadata_written", {"document_id":document_id, "revision":record["revision"],
                                                         "changes":recorded_changes})
        return record

    def reserve_review_request(self,scope,document_id,generation):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            digest,record=self._record(db,scope,document_id)
            analysis=record.setdefault('analysis',{})
            if record['archived'] or analysis.get('intent_version',0)!=generation or analysis.get('review_stopped'): return False
            count=analysis.get('request_count',0)
            scope_count=db.execute("SELECT SUM(COALESCE(json_extract(record,'$.analysis.request_count'),0)) FROM documents WHERE scope=?",(digest,)).fetchone()[0] or 0
            allowed=count < analysis.get('request_limit',64) and (scope_count<256 or count < analysis.get('authorized_through',0))
            if allowed:
                analysis['request_count']=count+1
            else:
                analysis.update(phase='complete',review_stopped=True,review_complete=False,
                                acknowledgement='The background review reached its request limit. Select Continue review to authorize up to 64 more requests.')
            db.execute('UPDATE documents SET record=? WHERE scope=? AND id=?',(json.dumps(record),digest,document_id))
            return allowed

    def archive(self, scope, document_id, archived=True):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            _, record = self._record(db, scope, document_id)
            record.update(archived=bool(archived), updated_at=time.time(), revision=record['revision'] + 1)
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(record), document_id))
        if self.trace:
            self.trace.emit("document.archived_changed", {"document_id":document_id, "revision":record["revision"],
                                                         "archived":record["archived"]})
        return record

    def remove(self, scope, document_id):
        return self.archive(scope, document_id)

    def purge(self, scope, document_id, *, failed_only=False):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            digest, record = self._record(db,scope,document_id)
            if failed_only:
                if record['status'] != 'error' or record.get('chunk_count',0) or db.execute('SELECT 1 FROM chunk_map WHERE document_id=? LIMIT 1',(document_id,)).fetchone():
                    raise DocumentError('Only a failed upload without any indexed text can be discarded.')
            elif not record['archived']:
                raise DocumentError('Remove the file from the interview before deleting it permanently.')
            directory = self.root / digest / record['id']
            if directory.is_symlink() or directory.is_junction() or directory.parent.is_symlink() or directory.parent.is_junction():
                raise DocumentError('Document storage cannot use a linked directory.')
            self._delete_chunks(db,digest,document_id)
            db.execute('DELETE FROM documents WHERE id=? AND scope=?',(document_id,digest))
            db.commit()
            if directory.exists(): self._remove_original_files(directory)
        return {'id':document_id, 'purged':True}

    def pending(self, scope):
        return [record for record in self.list(scope) if record['status'] in ('pending', 'indexing')]

    def chunks(self, scope, document_id, offset=0, limit=100):
        if (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
                or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500):
            raise DocumentError('Chunk pagination requires a nonnegative offset and limit between 1 and 500.')
        with self._db() as db:
            db.execute('BEGIN')
            digest, record = self._record(db, scope, document_id)
            return _DocumentReader(db, digest, {document_id: record}).chunks(document_id, offset, limit)

    def text_size(self, scope, document_id):
        """Characters of indexed text in one file: what a full review of it has to send."""
        with self._db() as db:
            digest, _ = self._record(db, scope, document_id)
            return db.execute('SELECT coalesce(sum(length(chunks.text)),0)' + CHUNK_JOIN.format(index='')
                              + 'chunk_map.scope=? AND chunk_map.document_id=?',
                              (digest, document_id)).fetchone()[0]

    def source(self, scope, document_id, source_id):
        with self._db() as db:
            digest, record = self._record(db, scope, document_id)
            row = db.execute(CHUNK_ROWS + 'chunk_map.scope=? AND chunk_map.document_id=? AND chunk_map.id=?',
                             (digest, document_id, source_id)).fetchone()
            if not row:
                raise PermissionError('Document source is not available in this interview.')
            return _chunk(row, record)

    @staticmethod
    def _insert_chunk(db, digest, document_id, identity, label, text, location):
        """Add one section to the full-text table and to chunk_map, in the caller's transaction."""
        rowid = db.execute('INSERT INTO chunks(id,document_id,scope,label,text,location) VALUES (?,?,?,?,?,?)',
                           (identity, document_id, digest, label, text, json.dumps(location))).lastrowid
        ordinal = rowid * 256
        parent, separator, suffix = identity.rpartition('_v')
        if separator and suffix.isdecimal() and 1<int(suffix)<256:
            source = db.execute('SELECT ordinal FROM chunk_map WHERE scope=? AND document_id=? AND id=?',(digest,document_id,parent)).fetchone()
            if source: ordinal=source[0]+int(suffix)-1
        db.execute('INSERT INTO chunk_map(scope,document_id,id,chunk_rowid,ordinal) VALUES (?,?,?,?,?)', (digest, document_id, identity, rowid,ordinal))

    @staticmethod
    def _delete_chunks(db, digest, document_id, identity=None):
        """Remove one section of a file, or all of them, from both tables."""
        where, values = 'scope=? AND document_id=?', [digest, document_id]
        if identity is not None:
            where, values = where + ' AND id=?', [*values, identity]
        db.execute(f'DELETE FROM chunks WHERE rowid IN (SELECT chunk_rowid FROM chunk_map WHERE {where})', values)
        db.execute(f'DELETE FROM chunk_map WHERE {where}', values)

    def record_extracted_text(self, scope, document_id, source_id, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 100000:
            raise DocumentError('Visual transcription requires 1–100,000 characters; no text was truncated.')
        if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,200}', source_id):
            raise DocumentError('Choose an exact document source ID.')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            digest, record = self._record(db, scope, document_id)
            row = db.execute('SELECT chunk_map.chunk_rowid,chunks.*' + CHUNK_JOIN.format(index='')
                             + 'chunk_map.scope=? AND chunk_map.document_id=? AND chunk_map.id=?',
                             (digest, document_id, source_id)).fetchone()
            if not row:
                raise PermissionError('Document source is not available in this interview.')
            location = json.loads(row['location'])
            if not location.get('requires_vision') and location.get('origin') != 'ai_visual_transcription':
                raise DocumentError('Only an explicitly visual source may receive a visual transcription.')
            location.update(requires_vision=False, origin='ai_visual_transcription', verified=False)
            parts = list(_text_parts(text))
            old = db.execute('SELECT chunks.id,chunks.text' + CHUNK_JOIN.format(index='')
                             + 'chunk_map.scope=? AND chunk_map.document_id=?', (digest, document_id)).fetchall()
            replaced = {source_id} | {item['id'] for item in old if item['id'].startswith(source_id + '_v')}
            remaining_bytes = sum(len(item['text'].encode()) for item in old if item['id'] not in replaced)
            if remaining_bytes + len(text.encode()) > MAX_INDEX_BYTES or len(old) - len(replaced) + len(parts) > MAX_CHUNKS:
                raise ExtractionError(TRANSCRIPTION_LIMIT_MESSAGE)
            db.execute('UPDATE chunks SET text=?,location=? WHERE rowid=?', (parts[0], json.dumps(location), row['chunk_rowid']))
            for item in old:
                if item['id'] != source_id and item['id'] in replaced:
                    self._delete_chunks(db, digest, document_id, item['id'])
            for index, part in enumerate(parts[1:], 2):
                self._insert_chunk(db, digest, document_id, f'{source_id}_v{index}', row['label'], part, location)
            inventory = record['inventory']
            reviewed = inventory.setdefault('visual_transcribed_units', [])
            unit = location.get('page', 'image')
            if unit not in reviewed:
                reviewed.append(unit)
            # Unit presence detects the first visual read. Its content digest
            # also detects a later correction without using mutable review
            # progress/version counters as a source identity.
            record.setdefault('visual_transcription_hashes', {})[str(unit)] = hashlib.sha256(text.encode('utf-8')).hexdigest()
            # This reading has arrived, so the source no longer awaits one.
            pending = record.pop('visual_reread_pending', {})
            pending.pop(source_id, None)
            if pending:
                record['visual_reread_pending'] = pending
            else:
                record.pop('visual_reread_basis', None)
            _transcribed_coverage(inventory, record['coverage'])
            # Never refused here: extraction kept room for every reading, and an
            # inventory from before it did gives up its preview samples instead.
            record['inventory'] = _inventory_budget(inventory, strict=False)
            record.update(status='partial', chunk_count=len(old) - len(replaced) + len(parts),
                          updated_at=time.time(), revision=record['revision'] + 1)
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(record), document_id))
        return record

    def original_path(self, scope, document_id):
        with self._db() as db:
            digest, record = self._record(db, scope, document_id)
        path = self.root / digest / document_id / ('original.' + record['kind'])
        target = _long_path(path)
        if target.is_symlink() or target.parent.is_symlink() or not target.is_file():
            raise DocumentError('The original document is unavailable.')
        return path

    def original_bytes(self, scope, document_id):
        """Read the original through a path form that works at any depth."""
        return _long_path(self.original_path(scope, document_id)).read_bytes()

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
                path = _long_path(self.original_path(scope, document_id))
                extractor = {'pdf': _pdf, 'png': _png, 'xlsx': _workbook, 'xlsm': _workbook,
                             'csv': _csv, 'xls': _legacy_xls}[record['kind']]
                inventory, coverage = extractor(path, record, chunks)
                with self._db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    digest, current = self._record(db, scope, document_id)
                    # Read what a paid review wrote before this index is replaced.
                    saved = db.execute('SELECT chunks.id,chunks.text,chunks.location' + CHUNK_JOIN.format(index='')
                                       + "chunk_map.scope=? AND chunk_map.document_id=? AND chunks.location LIKE '%ai_visual_transcription%'",
                                       (digest, document_id)).fetchall()
                    parsed_limitations = list(coverage['limitations'])
                    kept, digests = _carry_transcriptions(saved, chunks, inventory, coverage)
                    inventory = _inventory_budget(inventory)
                    status = 'partial' if coverage['limitations'] else 'ready'
                    self._delete_chunks(db, digest, document_id)
                    for item in chunks.items:
                        self._insert_chunk(db, digest, document_id, item['id'], item['label'], item['text'], item['location'])
                    current.update(status=status, inventory=inventory, coverage=coverage,
                                   visual_transcription_hashes=digests,
                                   chunk_count=len(chunks.items), error=None, extraction_version=EXTRACTION_VERSION,
                                   extraction_needs_reindex=False, updated_at=time.time(), revision=current['revision'] + 1)
                    # The next review is offered each kept source as a visual
                    # source again, under the placeholder sentence saved here;
                    # until that reading arrives the source stays as stored.
                    # Each distinct sentence is saved once, with what the parser
                    # alone said about coverage; a pending source holds only its
                    # sentence's position, so a long scan stays a small record.
                    current.pop('visual_reread_pending', None)
                    current.pop('visual_reread_basis', None)
                    if kept:
                        sentences = list(dict.fromkeys(kept.values()))
                        current['visual_reread_pending'] = {source: sentences.index(text) for source, text in kept.items()}
                        current['visual_reread_basis'] = {'placeholders': sentences, 'limitations': parsed_limitations}
                    db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(current), document_id))
                return current
            except ImportError as error:
                # The selected Python lacks a reader. That is not a damaged file: name the package,
                # as _legacy_xls does for xlrd, and leave a diagnostic that names the module.
                module = (getattr(error, 'name', None) or '').split('.')[0] or None
                if record['kind'] not in READERS:
                    return self.update(scope, document_id, {'status': 'error', 'error': 'The document could not be safely decoded. Its original is retained.'})
                self._diagnose('dependency_missing', reason=module or READERS[record['kind']][1], stage=record['kind'], error_type='ImportError')
                return self.update(scope, document_id, {'status': 'error', 'error_code':'dependency_missing', 'retryable':False,
                                                      'error': missing_reader_message(record['kind'], module)})
            except (OSError, sqlite3.Error) as error:
                self._diagnose('document_storage_unavailable', stage='publish', error_type=type(error).__name__)
                return self.update(scope, document_id, {'status':'error', 'error_code':'storage_unavailable', 'retryable':True,
                    'error':'Local storage could not publish the index. Check free disk space and access, then select Retry review.'})
            except Exception as error:
                # Parser messages can contain source text; publish only controlled diagnostics.
                message = str(error) if isinstance(error, DocumentError) else 'The document could not be safely decoded. Its original is retained.'
                return self.update(scope, document_id, {'status': 'error', 'error_code':'invalid_file', 'retryable':False, 'error': message})

    def _diagnose(self, event, **fields):
        """Report an operational fact (never file content) to whoever started the store, if anyone listens."""
        if callable(self.diagnostic):
            try:
                self.diagnostic(event, **fields)
            except Exception:
                pass  # A diagnostic must never make a file operation fail.

    def check_extraction(self, scope, document_id):
        """Compare an index made by an earlier version with what this version reads. Local and free.

        The original is parsed again in memory. When that gives the very
        sections that are stored (the same IDs, labels, text and locations,
        with stored AI transcriptions kept in place), the saved index is
        current after all: the record takes the new inventory, coverage and
        version, and keeps its review. Whether that review is complete is
        decided again from the new coverage, because a newer version may count
        as unread what an older one counted as read. No section is rewritten
        and no provider request is made. When the sections differ, or the
        original cannot be read, index and review stay as they are and the
        record says so: only an explicit re-index and review brings it up to date.
        """
        self.get(scope, document_id)  # Authorize before retaining any worker lock.
        with self._locks_guard:
            lock = self._locks.setdefault(document_id, threading.Lock())
        with lock:
            before = self.get(scope, document_id)
            if (before['archived'] or not before.get('extraction_needs_reindex')
                    or (before.get('reindex_check') or {}).get('outcome') != 'pending'):
                return before
            chunks, outcome = _Chunks(before), 'changed'
            try:
                path = _long_path(self.original_path(scope, document_id))
                extractor = {'pdf': _pdf, 'png': _png, 'xlsx': _workbook, 'xlsm': _workbook,
                             'csv': _csv, 'xls': _legacy_xls}[before['kind']]
                inventory, coverage = extractor(path, before, chunks)
            except Exception:
                outcome = 'failed'
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                digest = self._authorize(db, scope)
                row = db.execute('SELECT record FROM documents WHERE id=? AND scope=?', (document_id, digest)).fetchone()
                current = json.loads(row['record']) if row else None
                # An action taken while the file was being read (Revisit, Remove) decides instead.
                if not current or current.get('revision') != before['revision'] or self._read_record(dict(current)).get('status') != before['status']:
                    return self.get(scope, document_id) if current else before
                same = False
                if outcome != 'failed':
                    saved = db.execute('SELECT chunks.id,chunks.label,chunks.text,chunks.location' + CHUNK_JOIN.format(index='')
                                       + 'chunk_map.scope=? AND chunk_map.document_id=?', (digest, document_id)).fetchall()
                    try:
                        _, digests = _carry_transcriptions(saved, chunks, inventory, coverage)
                        inventory = _inventory_budget(inventory)
                        same = ({row['id']: (row['label'], row['text'], json.loads(row['location'])) for row in saved}
                                == {item['id']: (item['label'], item['text'], item['location']) for item in chunks.items})
                    except DocumentError:
                        outcome = 'failed'
                if same:
                    analysis = current.get('analysis') or {}
                    if analysis:
                        total, cursor, units = len(saved), analysis.get('cursor', 0), coverage.get('total_units', 0)
                        if analysis.get('phase') == 'reindex_required' or analysis.get('error') in REINDEX_NOTICES:
                            # An earlier action saved the cautious projection with the record.
                            if analysis.get('error') in REINDEX_NOTICES:
                                analysis['error'] = None
                            analysis['phase'] = ('error' if analysis.get('error') or analysis.get('retry_required')
                                                 else 'complete' if total and cursor >= total
                                                 else 'deep' if analysis.get('summary') else 'quick')
                        analysis['limitations'] = [entry for entry in analysis.get('limitations', []) if entry not in REINDEX_NOTICES]
                        analysis.update(total_chunks=total, version=analysis.get('version', 0) + 1,
                                        review_complete=bool(analysis.get('phase') == 'complete' and total and cursor >= total
                                                             and analysis.get('reviewed_chunks', cursor) >= total
                                                             and not current.get('visual_reread_pending')
                                                             and not analysis.get('review_stopped')
                                                             and units > 0 and coverage.get('indexed_units', 0) >= units
                                                             and not analysis.get('limit_indicator', False)))
                    current.update(status='partial' if coverage['limitations'] else 'ready', inventory=inventory, coverage=coverage,
                                   visual_transcription_hashes=current.get('visual_transcription_hashes') or digests,
                                   chunk_count=len(saved), error=None, extraction_version=EXTRACTION_VERSION,
                                   extraction_needs_reindex=False, analysis=analysis)
                    current.pop('reindex_check', None)
                else:
                    current['reindex_check'] = {'extraction_version': EXTRACTION_VERSION, 'outcome': outcome}
                current.update(updated_at=time.time(), revision=current['revision'] + 1)
                db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(current), document_id))
            return self._read_record(current)

    def search(self, scope, query, ids=None, limit=12):
        if not isinstance(query, str) or len(query) > 2000 or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise DocumentError('Search requires text and a limit between 1 and 100.')
        with self.interview_reader(scope) as reader:
            return reader.search(query, ids, limit)

    def page_input(self, scope, document_id, page_number):
        """Internal-only native PDF page input; page_number is one-based."""
        from pypdf import PdfReader, PdfWriter
        record = self.get(scope, document_id)
        if record['kind'] != 'pdf' or not isinstance(page_number, int) or isinstance(page_number, bool):
            raise DocumentError('Choose a PDF page by its one-based number.')
        # Read through an open file: given a path, pypdf loads the whole file into memory for every page
        # (69 MiB for one page of a 63 MiB PDF, sixteen pages at a time in an in-depth wave). pypdf reads
        # objects lazily while writing, so the page is written before the file is closed.
        with open(_long_path(self.original_path(scope, document_id)), 'rb', buffering=1 << 20) as stream:
            reader = PdfReader(stream)
            _open_pdf(reader)
            if not 1 <= page_number <= min(len(reader.pages), MAX_PDF_PAGES):
                raise DocumentError('That PDF page is unavailable.')
            writer = PdfWriter()
            writer.add_page(reader.pages[page_number - 1])
            output = io.BytesIO()
            writer.write(output)
        if output.tell() > MAX_PDF_PAGE_BYTES:
            raise DocumentError('This single PDF page exceeds the 16 MiB review limit. Export the page separately and attach it.')
        return output.getvalue()


def _open_pdf(reader):
    if reader.is_encrypted:
        try:
            if reader.decrypt(''):
                return
        except Exception:
            pass
        raise ExtractionError('Encrypted PDF requires a password to open. Upload an unlocked copy.')


def _pdf_annotation_text(page):
    lines, unread = [], False
    for reference in page.get('/Annots', ()):
        try:
            annotation = reference.get_object()
            if annotation.get('/Subtype') == '/Widget':
                field = annotation
                if '/V' not in field and field.get('/Parent'):
                    field = field['/Parent'].get_object()
                if '/V' in field:
                    lines.append(f"Form field {field.get('/T', '')}: {field['/V']}")
                elif '/AP' in annotation:
                    unread = True
            elif annotation.get('/Contents'):
                lines.append('Annotation: ' + str(annotation['/Contents']))
        except (ValueError, KeyError, AttributeError, TypeError):
            unread = True
    return lines, unread


# What a drawing has to exceed, in points, before it can be more than a bullet, a tick box,
# the rounded corner of a box or an icon set in a line of text.
PDF_FURNITURE_SIZE = 14.0
# How far a ruled line may drift, in points, and still be horizontal or vertical.
PDF_RULE_DRIFT = 0.75
# Rules and boxes are furniture where they frame text. On a page with fewer readable
# characters than this, a painted shape can be the page's actual content (a chart, a
# diagram of boxes), so the page keeps the cautious answer.
PDF_SPARSE_TEXT = 200
# The drawing check never decides the fate of a file: beyond these bounds a page keeps the
# cautious answer (graphics are assumed and sent for visual review).
PDF_DRAWING_OPERATIONS = 400_000
PDF_DRAWING_SECONDS = 12.0
_PDF_PAINTS = frozenset((b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*'))


class _PdfDrawingBudget(Exception):
    pass


def _pdf_matrix(left, right):
    a, b, c, d, e, f = left
    g, h, i, j, k, m = right
    return (a * g + b * i, a * h + b * j, c * g + d * i, c * h + d * j, e * g + f * i + k, e * h + f * j + m)


def _pdf_point(matrix, x, y):
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def _pdf_path_is_drawing(path):
    """Whether one painted path is more than page furniture.

    Furniture is what a text page is ruled and decorated with: rectangles, horizontal and
    vertical lines (table grids, borders, underlines, shaded bars), boxes with small rounded
    corners, and marks no larger than a line of text (bullets, tick boxes). A slanted line, a
    straight-edged shape such as an arrowhead, or a curve larger than a corner is a drawing.
    path holds ('l', (start, end)) and ('c', (start, control..., end)) in page units.
    """
    xs = [point[0] for _, points in path for point in points]
    ys = [point[1] for _, points in path for point in points]
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    curved = any(kind == 'c' for kind, _ in path)
    for kind, points in path:
        if kind == 'l':
            (x0, y0), (x1, y1) = points
            dx, dy = abs(x1 - x0), abs(y1 - y0)
            if dx <= PDF_RULE_DRIFT or dy <= PDF_RULE_DRIFT:
                continue
            # A slanted edge: part of something larger than a text mark, or of a small shape
            # drawn only with straight edges (an arrowhead), which a round bullet is not.
            if extent > PDF_FURNITURE_SIZE or (not curved and (dx * dx + dy * dy) ** .5 > 3.0):
                return True
        else:
            cx, cy = [point[0] for point in points], [point[1] for point in points]
            if max(cx) - min(cx) > PDF_FURNITURE_SIZE or max(cy) - min(cy) > PDF_FURNITURE_SIZE:
                return True
    return False


def _pdf_content_draws(content, reader, matrix, resources, depth, state):
    """Whether a content stream (a page's, or a form's that the page shows) paints a drawing.

    A page can hold all of its text and rules inside one form object, so the form is read
    rather than counted as a graphic. Counts the furniture shapes it passes in state['shapes'].
    """
    from pypdf.generic import ContentStream
    if depth > 8:
        return True
    try:
        xobjects = (resources.get('/XObject') if resources is not None else None) or {}
        xobjects = xobjects.get_object() if hasattr(xobjects, 'get_object') else xobjects
    except Exception:
        return True
    stack, path, start, current = [], [], None, None
    for operands, operator in content.operations:
        state['operations'] += 1
        if state['operations'] > PDF_DRAWING_OPERATIONS or (state['operations'] % 256 == 0 and time.monotonic() > state['deadline']):
            raise _PdfDrawingBudget
        if operator == b'q':
            stack.append(matrix)
        elif operator == b'Q':
            if stack:
                matrix = stack.pop()
        elif operator == b'cm':
            matrix = _pdf_matrix(tuple(float(value) for value in operands), matrix)
        elif operator == b'm':
            start = current = _pdf_point(matrix, float(operands[0]), float(operands[1]))
        elif operator == b'l':
            point = _pdf_point(matrix, float(operands[0]), float(operands[1]))
            if current is not None:
                path.append(('l', (current, point)))
            current = point
        elif operator in (b'c', b'v', b'y'):
            values = [float(value) for value in operands]
            points = [_pdf_point(matrix, values[index], values[index + 1]) for index in range(0, len(values) - 1, 2)]
            if current is not None and points:
                path.append(('c', (current, *points)))
            if points:
                current = points[-1]
        elif operator == b'h':
            if current is not None and start is not None and current != start:
                path.append(('l', (current, start)))
            current = start
        elif operator == b're':
            x, y, width, height = (float(value) for value in operands)
            corners = [_pdf_point(matrix, x, y), _pdf_point(matrix, x + width, y),
                       _pdf_point(matrix, x + width, y + height), _pdf_point(matrix, x, y + height)]
            path.extend(('l', (corners[index], corners[(index + 1) % 4])) for index in range(4))
            start = current = corners[0]
        elif operator == b'n':
            path, start, current = [], None, None  # A clipping path: nothing is painted.
        elif operator in _PDF_PAINTS:
            if path:
                if _pdf_path_is_drawing(path):
                    return True
                state['shapes'] += 1
            path, start, current = [], None, None
        elif operator == b'sh':
            return True  # A shading fills its area with a gradient; what it shows is not known.
        elif operator in (b'Do', b'INLINE IMAGE'):
            if operator == b'Do':
                target = xobjects[operands[0]].get_object()
                subtype = target.get('/Subtype')
                if subtype == '/Form':
                    if id(target) in state['open']:
                        return True
                    inner = target.get('/Matrix')
                    inner = _pdf_matrix(tuple(float(value) for value in inner), matrix) if inner else matrix
                    state['open'].add(id(target))
                    try:
                        if _pdf_content_draws(ContentStream(target, reader), reader, inner,
                                              target.get('/Resources') or resources, depth + 1, state):
                            return True
                    finally:
                        state['open'].discard(id(target))
                    continue
                if subtype != '/Image':
                    return True
            # An image is drawn on the unit square. One no larger than a text mark is an icon or
            # a bullet, and one as thin as a rule is a rule; anything else has content that only
            # a visual reading can report, however few pixels it was stored with.
            origin, across, up = _pdf_point(matrix, 0, 0), _pdf_point(matrix, 1, 0), _pdf_point(matrix, 0, 1)
            sides = (((across[0] - origin[0]) ** 2 + (across[1] - origin[1]) ** 2) ** .5,
                     ((up[0] - origin[0]) ** 2 + (up[1] - origin[1]) ** 2) ** .5)
            if max(sides) > PDF_FURNITURE_SIZE and min(sides) > 3.0:
                return True
            state['shapes'] += 1
    return False


def _pdf_page_has_drawing(page, reader, contents, text_chars, deadline):
    """True when a page paints something a visual reading is needed for; False when what it
    paints is page furniture around its text. Anything this check cannot settle is True.

    This narrows a cautious answer and never widens it: it is asked only about a page that
    paints something, and only its confident "furniture only" on a page of text lets the page
    go without a visual placeholder. A drawing made solely of unrotated boxes and ruled lines
    (a bar chart, a box diagram without arrowheads) reads as furniture; a page with little
    text of its own is therefore still sent for visual review whenever it paints a shape.
    """
    state = {'operations': 0, 'deadline': deadline, 'open': set(), 'shapes': 0}
    try:
        if _pdf_content_draws(contents, reader, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), page.get('/Resources'), 0, state):
            return True
    except _PdfDrawingBudget:
        return True
    except Exception:
        return True  # An object this check cannot follow is not evidence of a plain page.
    return state['shapes'] > 0 and text_chars < PDF_SPARSE_TEXT


def _pdf(path, record, chunks):
    from pypdf import PdfReader
    from pypdf.errors import LimitReachedError
    reader = PdfReader(path)
    _open_pdf(reader)
    deadline = time.monotonic() + 45
    drawing_seconds = 0.0
    operations = 0
    exhausted = False
    def bound(*_):
        nonlocal operations, exhausted
        operations += 1
        if exhausted or operations > 2_000_000 or (operations % 128 == 0 and time.monotonic() > deadline):
            exhausted = True
            raise ExtractionError('PDF content expands beyond the extraction budget; no partial index was published.')
    count = len(reader.pages)
    if not count:
        raise ExtractionError('This PDF has no pages.')
    # Pages after MAX_PDF_PAGES are not opened. Their number is known from the page tree, so the
    # coverage can say exactly what was left out.
    read = min(count, MAX_PDF_PAGES)
    index_full = False
    missing, failures, mixed, content_bytes, indexed, page_inventory = [], [], [], 0, 0, []
    for number, page in enumerate(itertools.islice(reader.pages, read), 1):
        failed = False
        try:
            contents = page.get_contents()
            # ContentStream is a dictionary-like object and can be false even
            # when it contains decoded bytes. Test presence, not truthiness.
            length = len(contents.get_data()) if contents is not None else 0
            content_bytes += length
            if length > MAX_PDF_PAGE_BYTES or content_bytes > MAX_PDF_CONTENT_BYTES:
                raise ExtractionError('PDF decoded content exceeds 16 MiB per page or 128 MiB total; no partial index was published.')
            text = page.extract_text(visitor_operand_before=bound) or ''
            if exhausted or time.monotonic() > deadline:
                raise ExtractionError('PDF content expands beyond the extraction budget; no partial index was published.')
            annotations, unread_annotations = _pdf_annotation_text(page)
            text = '\n'.join([text, *annotations]) if annotations else text
            suspect = sum(char == '\ufffd' or unicodedata.category(char) in ('Cs', 'Co') or
                          (unicodedata.category(char) == 'Cc' and not char.isspace()) for char in text)
            if suspect and suspect * 20 >= max(1, len(text.strip())):
                raise ValueError('Unreliable PDF character mapping')
            if suspect:
                text = re.sub(r'[\ud800-\udfff]', '\ufffd', text)
            # Text extraction does not read image pixels, diagram geometry or
            # painted form contents. Detect paint operations without decoding
            # image pixels; decorative and meaningful graphics are both honest
            # review requirements until inspected.
            paints = {b'Do', b'INLINE IMAGE', b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*', b'sh'}
            operators = [op for _, op in contents.operations] if contents is not None else []
            painted = (b're' in operators and any(op in paints for op in operators)
                       or any(op in paints - {b'S', b's'} for op in operators)
                       or sum(op in (b'S', b's') for op in operators) > 1)
            if painted and not unread_annotations and text.strip():
                # Rules, table grids, shaded bars and bullets are painted too, and many
                # exports put a whole page (text and rules) inside one form object. Such a
                # page has no graphic to read, so it must neither be sent for a visual
                # reading nor be reported as holding unread graphics. The time this check
                # takes is its own: it cannot make the text extraction miss its deadline.
                checked = time.monotonic()
                painted = (drawing_seconds >= PDF_DRAWING_SECONDS or _pdf_page_has_drawing(
                    page, reader, contents, len(text.strip()), checked + PDF_DRAWING_SECONDS - drawing_seconds))
                spent = time.monotonic() - checked
                drawing_seconds += spent
                deadline += spent
            visual = bool(unread_annotations or painted)
        except LimitReachedError:
            raise ExtractionError('PDF decoded content exceeds 16 MiB per page or 128 MiB total; no partial index was published.') from None
        except DocumentError:
            raise
        except Exception:
            failed = True
        label = f'{record["name"]} · page {number}'
        mark = chunks.mark()
        try:
            if failed:
                chunks.add(f'p{number}', label,
                           'PDF page text decoding failed. Native visual review is required; page contents have not been read.',
                           {'page': number, 'requires_vision': True, 'origin': 'visual_placeholder', 'text_decode_failed': True})
            elif not text.strip():
                chunks.add(f'p{number}', label,
                           'PDF page contains no extractable text. Native visual review is required; page contents have not been read.',
                           {'page': number, 'requires_vision': True, 'origin': 'visual_placeholder'})
            else:
                chunks.add(f'p{number}', label, text, {'page': number})
                if visual:
                    chunks.add(f'p{number}_visual', f'{label} · visual content',
                               'This PDF page also contains visual graphics. Its native text is indexed separately; graphic contents and layout require native visual review and have not been read.',
                               {'page': number, 'requires_vision': True, 'origin': 'visual_placeholder', 'native_text_preserved': True})
        except _IndexFull:
            # No room for this page: it and the pages after it are left out, as pages past
            # MAX_PDF_PAGES are. The index keeps whole pages only.
            chunks.rollback(mark)
            read, index_full = number - 1, True
            break
        if failed:
            failures.append(number)
            page_inventory.append({'page': number, 'text_chars': 0, 'sample': '', 'requires_vision': True})
        elif not text.strip():
            missing.append(number)
            page_inventory.append({'page': number, 'text_chars': 0, 'sample': '', 'requires_vision': True})
        else:
            if visual:
                mixed.append(number)
            page_inventory.append({'page': number, 'text_chars': len(text), 'sample': re.sub(r'\s+', ' ', text).strip()[:180],
                                   'requires_vision': visual})
            indexed += 1
    if not read:
        raise ExtractionError(INDEX_FULL_MESSAGE)
    limitations = []
    # Stated first: it is the largest limit on what the index can answer.
    cut = (f'Pages 1 to {read:,} of {count:,} were read; the rest '
           + ('did not fit in the text index.' if index_full else 'was not.')) if read < count else ''
    if cut:
        limitations.append(cut)
    if missing:
        limitations.append(f'{len(missing)} pages contain no extractable text and require native visual review; they were not treated as read.')
    if failures:
        limitations.append(f'{len(failures)} pages could not be decoded and require review.')
    if mixed:
        limitations.append(f'{len(mixed)} pages contain native text plus graphics; text is preserved separately, but graphics and layout still require native visual review.')
    return ({'pages': count, **({'pages_read': read} if cut else {}), 'page_inventory': page_inventory, 'text_pages': indexed,
             'text_only_pages': indexed - len(mixed), 'mixed_visual_pages': mixed, 'vision_pages': sorted(missing + failures + mixed),
             'failed_pages': failures, 'requires_vision': bool(missing or failures or mixed)},
            {'indexed_units': indexed - len(mixed), 'total_units': count, 'text_indexed_units': indexed,
             'visual_pending_units': len(missing)+len(failures)+len(mixed), 'unit':'pages', 'limitations': limitations,
             **({'read_limit': cut} if cut else {})})


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
            {'indexed_units': 0, 'total_units': 1, 'visual_pending_units': 1, 'limitations': ['Image contents require native visual review; no OCR was performed.']})


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
                if not item.is_dir():
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


HIDDEN_SHEET_LABEL = ' · hidden sheet'


class _SheetLimit:
    """How far a spreadsheet is read, and what a count limit left out.

    One allowance of MAX_CELLS covers the whole file. Each reader's rows() takes a row's cells from
    it (take) before it yields the row; a row that does not fit stops the reading there. So does a
    CSV row past MAX_ROWS, and a group of rows that no longer fits in the index (_row_chunks). That
    row and every row after it, in this sheet and the sheets after it, are then only counted (skip):
    never rendered, chunked or indexed. Counting is cheap, but it gives up rather than fail the file
    (counted False) when the rest cannot be read or the parser's time runs out.
    """

    def __init__(self):
        self.left = MAX_CELLS
        self.reason = None    # 'cells', 'rows' or 'index' once reading has stopped
        self.read = 0         # cells taken before the stop
        self.unread = 0       # cells counted after it
        self.counted = True
        self.rows = 0         # the highest row number the current sheet has shown, read or counted
        self.place = ''       # where reading stopped, e.g. 'to row 250,000 of Data'
        self.wide = []        # (row number, last populated column) of each CSV row cut at MAX_COLUMNS

    def take(self, cells, number):
        """True when this row is read; False when it is past a limit and only counted."""
        if self.reason is None and cells > self.left:
            self.stop('cells')
        if self.reason is not None:
            self.skip(cells, number)
            return False
        self.rows = max(self.rows, number)
        self.left -= cells
        return True

    def skip(self, cells, number):
        self.rows = max(self.rows, number)
        self.unread += cells

    def stop(self, reason):
        if self.reason is None:
            self.reason, self.read = reason, MAX_CELLS - self.left

    def notes(self, rows=None):
        """The sentences that say what was left out; rows is a CSV's row count."""
        notes = []
        if self.wide:
            notes.append(f'Columns 1 to {MAX_COLUMNS:,} of {max(column for _, column in self.wide):,} were read; the rest was not.')
        if self.reason == 'cells':
            notes.append(f'The first {self.read:,} cells were read, {self.place}; '
                         + (f'{self.unread:,} more were not.' if self.counted else 'the rest was not.'))
        elif self.reason == 'rows':
            notes.append(f'Rows 1 to {MAX_ROWS:,}' + (f' of {rows:,}' if self.counted and rows else '') + ' were read; the rest was not.')
        elif self.reason == 'index':
            notes.append(f'Cells were read {self.place}; the rest did not fit in the text index.')
        return notes


NOTHING_READ_MESSAGE = 'The first row of this file is already past the reading limits, so nothing of it was indexed.'


def _row_chunks(record, chunks, sheet_index, sheet_name, rows, limit):
    def get_column_letter(number):
        result = ''
        while number:
            number, remainder = divmod(number - 1, 26)
            result = chr(65 + remainder) + result
        return result
    buffer, start, end, high_col = [], None, None, 0
    header_sample, header_truncated = '', False
    serial = 0
    buffer_chars = 0
    buffer_lengths = []
    # What the rows read so far hold, and the same for those whose sections are in the index. The
    # two differ only while rows wait in the buffer; when the index fills, the committed counts stand.
    totals = {'rows': 0, 'columns': 0, 'populated_cells': 0, 'formula_cells': 0, 'formulas_without_cached_values': 0}
    committed = dict(totals)

    def flush():
        nonlocal buffer, buffer_chars, start, end, high_col, serial
        if buffer:
            serial += 1
            area = f'A{start}:{get_column_letter(max(1, high_col))}{end}'
            mark = chunks.mark()
            try:
                chunks.add(f's{sheet_index}_r{start}_{end}_b{serial}', f'{record["name"]} · {sheet_name}!{area}',
                           '\n'.join(buffer), {'sheet': sheet_name, 'sheet_index': sheet_index, 'range': area,
                                                'row_start': start, 'row_end': end, 'header_sample': header_sample,
                                                'cell_lengths': list(buffer_lengths)})
            except _IndexFull:
                chunks.rollback(mark)
                raise
            buffer, buffer_chars, start, end, high_col = [], 0, None, None, 0
            buffer_lengths.clear()
        committed.update(totals)

    def add(row_number, row, formulas, uncached):
        totals.update(rows=max(totals['rows'], row_number), populated_cells=totals['populated_cells'] + len(row),
                      formula_cells=totals['formula_cells'] + formulas,
                      formulas_without_cached_values=totals['formulas_without_cached_values'] + uncached)
        if row:
            totals['columns'] = max(totals['columns'], max(item[0] for item in row))

    try:
        for row_number, row in rows:
            values, formulas, uncached = [], 0, 0
            for column, value, formula, cached in row:
                if formula:
                    formulas += 1
                    uncached += cached is None
                    rendered = f'FORMULA (not executed) {_formula_text(formula)}; cached value (not recalculated): {_cell_text(cached) if cached is not None else "UNAVAILABLE"}'
                else:
                    rendered = _cell_text(value)
                values.append(f'{get_column_letter(column)}{row_number}={rendered}')
            if not values:
                add(row_number, row, formulas, uncached)
                continue
            line = ' | '.join(values)
            if not header_sample:
                header_sample, header_truncated = line[:180], len(line) > 180
            if len(line) > MAX_CHUNK_CHARS:
                flush()
                mark = chunks.mark()
                group, group_length = [], 0
                def emit_cells():
                    nonlocal serial
                    if not group:
                        return
                    first, last = group[0][0], group[-1][0]
                    area = f'{first}:{last}' if first != last else first
                    serial += 1
                    source = f's{sheet_index}_wide_{first}_{last}_b{serial}'
                    body = ' | '.join(rendered for _, rendered in group)
                    caption = f'{record["name"]} · {sheet_name}!{area}'
                    location = {'sheet': sheet_name, 'sheet_index': sheet_index, 'range': area,
                                'row_start': row_number, 'row_end': row_number, 'header_sample': header_sample,
                                'cell_lengths': [len(rendered) for _, rendered in group]}
                    if len(group) == 1 and len(body) > MAX_CHUNK_CHARS:
                        # Keep the address on every continuation of a single oversized cell.
                        prefix = first + '='
                        value = body[len(prefix):]
                        width = MAX_CHUNK_CHARS - len(prefix)
                        for part, offset in enumerate(range(0, len(value), width), 1):
                            chunks.add(f'{source}_part{part}', f'{caption} · part {part}',
                                       prefix + value[offset:offset+width],
                                       {**location, 'cell_part': part, 'cell_lengths': [len(prefix) + len(value[offset:offset+width])]})
                    else:
                        chunks.add(source, caption, body, location)
                try:
                    for rendered in values:
                        address = rendered.split('=', 1)[0]
                        if group and group_length + 3 + len(rendered) > MAX_CHUNK_CHARS:
                            emit_cells()
                            group, group_length = [], 0
                        group_length += (3 if group else 0) + len(rendered)
                        group.append((address, rendered))
                    emit_cells()
                except _IndexFull:
                    chunks.rollback(mark)  # A row is indexed whole or not at all.
                    raise
                add(row_number, row, formulas, uncached)
                committed.update(totals)
                continue
            if buffer and (buffer_chars + 1 + len(line) > MAX_CHUNK_CHARS or row_number - start >= 50):
                flush()
            start = row_number if start is None else start
            end, high_col = row_number, max(high_col, max(item[0] for item in row))
            buffer_chars += len(line) + (1 if buffer else 0)
            buffer.append(line)
            buffer_lengths.extend(len(rendered) for rendered in values)
            add(row_number, row, formulas, uncached)
        flush()
    except _IndexFull:
        # The sections of the rows that did not fit were taken back out: the index ends with the
        # last committed rows. The rows after them, read or not, are left out.
        limit.stop('index')
        for _ in rows:
            pass
    return {'name': sheet_name, 'index': sheet_index, 'rows': committed['rows'], 'columns': committed['columns'],
            'header_sample': header_sample if committed['rows'] else '', 'header_sample_truncated': header_truncated and bool(committed['rows']),
            'populated_cells': committed['populated_cells'], 'formula_cells': committed['formula_cells'],
            'formulas_without_cached_values': committed['formulas_without_cached_values']}


def _vml_only_notes(archive, source_path, relations):
    """True when every VML drawing of this worksheet holds only comment note boxes (ObjectType Note)."""
    import posixpath
    found = False
    for relation in relations:
        if relation.get('Type', '').rsplit('/', 1)[-1] != 'vmlDrawing' or relation.get('TargetMode') == 'External':
            continue
        target = relation.get('Target', '')
        name = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(str(source_path.parent), target))
        if name.startswith('../') or name not in archive.namelist() or archive.getinfo(name).file_size > MAX_ZIP_MEMBER_BYTES:
            return False
        with archive.open(name) as stream:
            text = stream.read().decode('utf-8', 'replace')
        # Any namespace prefix: Excel writes v: and x:, other writers ns0: and the like.
        kinds = re.findall(r'<(?:[\w.-]+:)?ClientData\b[^>]*\bObjectType\s*=\s*"([^"]*)"', text)
        shapes = len(re.findall(r'<(?:[\w.-]+:)?shape\b', text))
        if (not kinds or any(kind != 'Note' for kind in kinds) or shapes != len(kinds)
                or re.search(r'<(?:[\w.-]+:)?imagedata\b', text)):
            return False
        found = True
    return found


class _CountCut(Exception):
    """The parser's time ran out while it was only counting what a limit left out."""


def _workbook(path, record, chunks):
    from openpyxl import load_workbook
    from openpyxl.worksheet._reader import WorkSheetParser, FORMULA_TAG
    from openpyxl.styles.numbers import BUILTIN_FORMATS, BUILTIN_FORMATS_MAX_SIZE
    _zip_check(path)
    with ExitStack() as cleanup:
        archive = cleanup.enter_context(zipfile.ZipFile(path))
        book = load_workbook(path, read_only=True, data_only=False, keep_links=False, keep_vba=False)
        cleanup.callback(book.close)
        # Stored cells count here, as each row's XML holds them, and before the row is parsed: an
        # empty but formatted cell costs the parser as much as a filled one.
        limit = _SheetLimit()
        deadline = time.monotonic() + 90

        class SparseParser(WorkSheetParser):
            def parse_row(self, element):
                if time.monotonic() > deadline:
                    if limit.reason is None:
                        raise ExtractionError('Workbook processing exceeded 90 seconds. Split the workbook and attach smaller copies.')
                    raise _CountCut()
                try:
                    number = int(element.get('r') or self.row_counter + 1)
                except ValueError:
                    number = self.row_counter + 1
                if not limit.take(len(element), number):
                    self.row_counter = number
                    return None  # Past a limit: counted, not parsed.
                return super().parse_row(element)

            def parse_cell(self, element):
                previous = self.col_counter
                cell = super().parse_cell(element)
                if element.find(FORMULA_TAG) is not None:
                    self.data_only = True
                    self.col_counter = previous
                    try: cell['cached'] = super().parse_cell(element)['value']
                    finally: self.data_only = False
                return cell
        if not book.sheetnames:
            raise ExtractionError('No worksheets could be read. Save a copy as Excel Workbook (.xlsx) and attach it.')
        names = book.sheetnames

        def rows(sheet):
            with sheet._get_source() as stream:
                parser = SparseParser(stream, sheet._shared_strings, False, book.epoch, book._date_formats, book._timedelta_formats)
                last_row = 0
                try:
                    for parsed in parser.parse():
                        if parsed is None:
                            continue
                        number, cells = parsed
                        if number <= last_row or not 1 <= number <= MAX_ROWS:
                            raise ExtractionError('Worksheet rows repeat or are out of order. Save a repaired copy and attach it.')
                        last_row = number
                        row, last_col = [], 0
                        for cell in cells:
                            col, raw = cell['column'], cell['value']
                            if cell['row'] != number or col <= last_col or col > MAX_COLUMNS:
                                raise ExtractionError('Worksheet cells repeat or are out of order. Save a repaired copy and attach it.')
                            last_col = col
                            if raw is None: continue
                            formula = raw if cell['data_type'] == 'f' else None
                            if not formula and cell['style_id'] and isinstance(raw,(int,float)) and not isinstance(raw,bool):
                                fmt_id = book._cell_styles[cell['style_id']].numFmtId
                                fmt = (BUILTIN_FORMATS.get(fmt_id) if fmt_id < BUILTIN_FORMATS_MAX_SIZE
                                       else book._number_formats[fmt_id-BUILTIN_FORMATS_MAX_SIZE])
                                if fmt and fmt != 'General': raw = f'{raw} [Excel format: {fmt[:100]}]'
                            row.append((col, raw, formula, cell.get('cached')))
                        yield number, row
                except _CountCut:
                    limit.counted = False

        def count(sheet):
            """Count the cells of a sheet after the one where reading stopped; nothing of it is read."""
            if limit.counted and limit.reason == 'cells' and hasattr(sheet, 'iter_rows'):
                for _ in rows(sheet):
                    pass

        inventory, previous = [], ''
        for index, name in enumerate(names[:MAX_SHEETS], 1):
            sheet = book[name]
            if limit.reason is not None:
                count(sheet)
                continue
            if not hasattr(sheet, 'iter_rows'):
                inventory.append({'name': name, 'index': index, 'kind': 'chart_sheet', 'rows': 0,
                                  'columns': 0, 'header_sample': '',
                                  'populated_cells': 0, 'formula_cells': 0, 'formulas_without_cached_values': 0,
                                  'requires_vision': True, 'visibility': sheet.sheet_state})
                continue
            first_chunk, limit.rows = len(chunks.items), 0
            item = _row_chunks(record, chunks, index, sheet.title, rows(sheet), limit)
            if limit.reason is not None:
                # Reading stopped in this sheet. Its rows after the stop were counted, not read.
                item.update(read_to_row=item['rows'], rows=max(item['rows'], limit.rows))
                limit.place = (f'to row {item["read_to_row"]:,} of {sheet.title}' if item['read_to_row'] or not previous
                               else f'to the end of {previous}')
            item['visibility'] = sheet.sheet_state
            for chunk in chunks.items[first_chunk:]:
                chunk['location']['visibility'] = sheet.sheet_state
                # A hidden sheet is read like any other, so every excerpt from one says so: a reader
                # of the notes or the draft would otherwise look for cells the workbook does not show.
                if sheet.sheet_state != 'visible': chunk['label'] += HIDDEN_SHEET_LABEL
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
                comments = 0
                try:
                    for relation in relations:
                        if relation.get('Type','').rsplit('/',1)[-1] != 'comments' or relation.get('TargetMode') == 'External': continue
                        import posixpath
                        target = relation.get('Target','')
                        path_name = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(str(source_path.parent),target))
                        if path_name.startswith('../') or path_name not in archive.namelist(): continue
                        with archive.open(path_name) as notes:
                            for _, note in ElementTree.iterparse(notes,events=('end',)):
                                if note.tag.rsplit('}',1)[-1]!='comment': continue
                                address = note.get('ref','')
                                if not re.fullmatch(r'[A-Z]{1,3}[1-9]\d{0,6}',address): continue
                                value = ''.join(part.text or '' for part in note.iter() if part.tag.rsplit('}',1)[-1]=='t')
                                if value.strip():
                                    mark = chunks.mark()
                                    try:
                                        chunks.add(f's{index}_comment{comments + 1}',f'{record["name"]} · {sheet.title}!{address} comment',value,
                                                   {'sheet':sheet.title,'sheet_index':index,'cell':address,'visibility':sheet.sheet_state,'origin':'cell_comment'})
                                    except _IndexFull:
                                        chunks.rollback(mark)
                                        raise
                                    comments += 1
                                note.clear()
                except _IndexFull:
                    # The cells of this sheet are indexed; its remaining comments and the sheets after it are not.
                    if limit.reason is None:
                        limit.stop('index')
                        limit.place = f'to the end of {sheet.title}'
                        item['read_to_row'] = item['rows']
                if comments: item['comment_count']=comments
                if 'vmlDrawing' in graphics and _vml_only_notes(archive, source_path, relations):
                    # Excel draws every cell comment's note box in a VML drawing. Those comments are
                    # indexed above; the drawing holds nothing else to read, so the tab is not unread.
                    graphics.remove('vmlDrawing')
                if graphics:
                    item.update(requires_vision=True, unread_visual_parts=graphics)
            inventory.append(item)
            previous = sheet.title
        if limit.reason is not None:
            for name in names[MAX_SHEETS:]:
                count(book[name])
        if not chunks.items and limit.reason is not None:
            raise ExtractionError(INDEX_FULL_MESSAGE if limit.reason == 'index' else NOTHING_READ_MESSAGE)
        limitations = limit.notes()
        if len(names) > MAX_SHEETS and limit.reason is None:
            limitations.append(f'Sheets 1 to {MAX_SHEETS:,} of {len(names):,} were read; the rest was not.')
        read_limit = ' '.join(limitations)
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
        # A sheet counts as indexed when all of it is: no chart-only tab, no unread graphics, no stop.
        indexed = sum(item.get('kind') != 'chart_sheet' and not item.get('unread_visual_parts') and 'read_to_row' not in item
                      for item in inventory)
        return ({'sheets': inventory, 'sheet_count': len(names), **({'sheets_read': len(inventory)} if len(inventory) < len(names) else {}),
                 'rows': sum(item['rows'] for item in inventory),
                 'formula_cells': sum(item['formula_cells'] for item in inventory), 'macros_executed': False,
                 'formula_policy': 'Formula text and saved cached values only; no recalculation.'},
                {'indexed_units': indexed, 'total_units': len(names), 'limitations': limitations,
                 **({'read_limit': read_limit} if read_limit else {})})


def _looks_utf16_or_32(head):
    """Null bytes the way UTF-16/32 without a byte-order mark has them: many, or nearly all on one byte
    parity (every ASCII character of UTF-16-LE text is followed by a null, also in Cyrillic or Arabic text)."""
    nulls = [index for index, byte in enumerate(head) if byte == 0]
    if not nulls:
        return False
    if len(nulls) * 4 >= len(head):
        return True
    odd = sum(index % 2 for index in nulls)
    return len(nulls) >= 8 and max(odd, len(nulls) - odd) >= 0.9 * len(nulls)


def _csv(path, record, chunks):
    error = ('CSV must be UTF-8 or BOM-marked UTF-16/32. In Excel, choose Save As > CSV UTF-8 '
             '(Comma delimited), or attach an XLSX copy.')
    with path.open('rb') as raw:
        head = raw.read(4096)
    if head.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = 'utf-32'
    elif head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = 'utf-16'
    elif _looks_utf16_or_32(head):
        # UTF-16/32 text saved without a byte-order mark. A stray null in an otherwise UTF-8
        # export is reported by its row below instead of as an encoding problem.
        raise ExtractionError(error)
    else:
        encoding = 'utf-8-sig'
    try:
        with path.open('r', encoding=encoding, newline='') as stream:
            sample = stream.read(16384)
            stream.seek(0)
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=',;\t').delimiter
            except csv.Error:
                delimiter = ','
            reader = csv.reader(stream, delimiter=delimiter, strict=True)
            limit = _SheetLimit()
            def rows():
                numbered = enumerate(reader, 1)
                while True:
                    try:
                        number, row = next(numbered)
                    except StopIteration:
                        return
                    except (csv.Error, UnicodeError):
                        if limit.reason is None:
                            raise
                        # Past a limit the rest is only counted. A fault in it ends the count, not the file.
                        limit.counted = False
                        return
                    if limit.reason is None and number > MAX_ROWS:
                        limit.stop('rows')
                    if limit.reason is not None:
                        limit.skip(sum(1 for value in row if value), number)
                        continue
                    if any('\x00' in value for value in row):
                        raise ExtractionError(f'Row {number:,} of this CSV contains a null character, which a CSV cell '
                                              'cannot hold. In Excel, choose Save As > CSV UTF-8 (Comma delimited), '
                                              'or attach an XLSX copy.')
                    cells = [(column, value, None, None) for column, value in enumerate(row, 1) if value]
                    kept = [cell for cell in cells if cell[0] <= MAX_COLUMNS]
                    if limit.take(len(kept), number):
                        if len(kept) < len(cells):
                            limit.wide.append((number, cells[-1][0]))
                        yield number, kept
                    else:
                        limit.unread += len(cells) - len(kept)
            item = _row_chunks(record, chunks, 1, 'CSV', rows(), limit)
    except UnicodeError:
        raise ExtractionError(error) from None
    except csv.Error:
        raise ExtractionError('CSV has an invalid or oversized field; no partial index was published.') from None
    if not item['populated_cells']:
        raise ExtractionError(INDEX_FULL_MESSAGE if limit.reason == 'index' else NOTHING_READ_MESSAGE if limit.reason
                              else 'CSV has no populated cells to index.')
    # Rows count as indexed when all of their cells are: a row cut at MAX_COLUMNS is not, nor is any row after a stop.
    read = item['rows']
    limit.wide = [entry for entry in limit.wide if entry[0] <= read]
    total = max(read, limit.rows) if limit.reason else read
    limit.place = f'to row {read:,}'
    notes = limit.notes(total)
    if limit.reason:
        item.update(read_to_row=read, rows=total)
    return ({'sheets': [item], 'sheet_count': 1, 'rows': total, 'delimiter': delimiter,
             'formula_policy': 'CSV cells are literal text; formulas are never executed.'},
            {'indexed_units': read - len(limit.wide), 'total_units': total, 'limitations': notes,
             **({'read_limit': ' '.join(notes)} if notes else {})})


def _legacy_xls(path, record, chunks):
    try:
        import xlrd
    except ImportError:
        raise ExtractionError('Legacy XLS requires xlrd, which is not installed. Save a copy as XLSX or CSV and upload that copy; the original is retained.') from None
    if not str(getattr(xlrd, '__version__', '')).startswith('2.'):
        raise ExtractionError('Legacy XLS requires xlrd 2.x. Save a copy as XLSX or CSV and attach it.')
    with path.open('rb') as source:
        if source.read(8) != bytes.fromhex('D0CF11E0A1B11AE1'):
            raise ExtractionError('Legacy XLS must be an OLE binary workbook. Save as XLSX or CSV and attach it.')
    book = xlrd.open_workbook(str(path), on_demand=True, ragged_rows=True)
    try:
        # As in _workbook: stored cells count, the first MAX_SHEETS sheets are read, and a stop
        # leaves the rows and sheets after it counted but unread.
        limit, sheets, previous = _SheetLimit(), [], ''
        def rows(sheet):
            for number in range(sheet.nrows):
                row = sheet.row_values(number)
                if limit.take(len(row), number + 1):
                    yield number + 1, [(col, value, None, None) for col,value in enumerate(row,1) if value != '']
        for index in range(min(book.nsheets, MAX_SHEETS)):
            sheet = book.sheet_by_index(index)
            if limit.reason is not None:
                if limit.reason == 'cells':
                    for _ in rows(sheet): pass
                continue
            first_chunk, limit.rows = len(chunks.items), 0
            item = _row_chunks(record, chunks, index + 1, sheet.name, rows(sheet), limit)
            if limit.reason is not None:
                item.update(read_to_row=item['rows'], rows=max(item['rows'], limit.rows))
                limit.place = (f'to row {item["read_to_row"]:,} of {sheet.name}' if item['read_to_row'] or not previous
                               else f'to the end of {previous}')
            item.update(visibility={0:'visible',1:'hidden',2:'veryHidden'}.get(sheet.visibility,'unknown'), formula_cells=None)
            if item['visibility'] in ('hidden', 'veryHidden'):
                for chunk in chunks.items[first_chunk:]: chunk['label'] += HIDDEN_SHEET_LABEL
            sheets.append(item)
            previous = sheet.name
        if limit.reason == 'cells':
            for index in range(MAX_SHEETS, book.nsheets):
                for _ in rows(book.sheet_by_index(index)): pass
        if not chunks.items and limit.reason is not None:
            raise ExtractionError(INDEX_FULL_MESSAGE if limit.reason == 'index' else NOTHING_READ_MESSAGE)
        notes = limit.notes()
        if book.nsheets > MAX_SHEETS and limit.reason is None:
            notes.append(f'Sheets 1 to {MAX_SHEETS:,} of {book.nsheets:,} were read; the rest was not.')
        return ({'sheets': sheets, 'sheet_count': book.nsheets, **({'sheets_read': len(sheets)} if len(sheets) < book.nsheets else {}),
                 'rows': sum(item['rows'] for item in sheets),
                 'formula_policy': 'Saved legacy cell results only; formula provenance may be unavailable.'},
                {'indexed_units': sum('read_to_row' not in item for item in sheets), 'total_units': book.nsheets,
                 'limitations': [*notes, 'Legacy XLS exposes saved cell results. Formula counts, chart and image contents, and macros are unavailable.'],
                 **({'read_limit': ' '.join(notes)} if notes else {})})
    finally:
        book.release_resources()
