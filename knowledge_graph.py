"""Local, evidence-backed process graph. Authorization belongs at the API boundary.

SQLite stores immutable submission revisions, reported internal topology, proposals,
review decisions and durable jobs. No automatic connection is ever confirmed.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import secrets
import json
import os
import re
import sqlite3
import sys
import threading
import time
import unicodedata
import uuid

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path


def _sibling(name):
    """Load a fixed application-owned sibling when Python -I excludes the source directory."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[name] = module
    return sys.modules[name]


gpfs_interview = _sibling("gpfs_interview")
raw_trace = _sibling("raw_trace")
validate_generation_records = _sibling("provider_usage").validate_generation_records

RELATIONSHIPS = frozenset(('provides_input_to', 'produces', 'consumes', 'hands_off_to',
                           'requires_approval_from', 'happens_after', 'uses_system',
                           'performed_by', 'variant_of', 'subprocess_of', 'parallel_with', 'shares_calculation_with'))
# The layouts of knowledge.sqlite3 this build opens: the oldest it upgrades in place, and the
# one it writes. SQLite keeps the number in the file (PRAGMA user_version; 0 in a store from
# before it was recorded). Raise the second number with any change an older build would
# misread. Keep this line a plain literal: desktop/manage.py reads it from an unpacked build
# without running it, so that the window never gives newer data to an older build.
STORE_FORMATS = (0, 2)

class StoredScopeDigest(str):
    # Internal resolver credential. JSON request strings can never acquire this type.
    document_scope_digest = True


def scope_digest(scope):
    return 'sha256:' + hashlib.sha256(scope.encode('utf-8')).hexdigest()

class StoreFormatError(RuntimeError):
    """The saved store has a layout this build does not open. Nothing in it was changed."""

class RevisionConflict(ValueError):
    """A revision was submitted from a copy that is not based on the latest stored revision. Nothing was stored.

    The HTTP boundary answers 409 with latest_revision, so the submitter can open the latest copy or
    confirm, naming that revision, that the older copy should become the newest one.
    """
    def __init__(self, base_revision, latest_revision):
        self.base_revision, self.latest_revision = base_revision, latest_revision
        described = (f'This copy is based on revision {base_revision}' if base_revision
                     else 'This copy does not record which revision it is based on')
        super().__init__(
            (f'A newer revision ({latest_revision}) of this process exists. ' if latest_revision > base_revision
             else f'The latest stored revision of this process is {latest_revision}. ')
            + f'{described}. Open the latest copy, or confirm that this copy should become revision {latest_revision + 1}.')

def now():
    return datetime.now(timezone.utc).isoformat()

def new_id():
    return str(uuid.uuid4())

def text(value, limit=1000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Invalid text field.')
    return value.strip()

def named_text(value, limit, name):
    """text() for a field of a submission: the refusal says which field it is and the limit it exceeds."""
    if not isinstance(value, str):
        raise ValueError(f'{name} must be text.')
    if len(value) > limit:
        raise ValueError(f'{name} is longer than {limit:,} characters.')
    return value.strip()

def normalized(value):
    return unicodedata.normalize('NFKC', str(value or '')).casefold()


def claim_identity(proposal):
    identity={k:proposal[k] for k in ('source_submission_id','destination_submission_id','relationship_type')}
    identity.update(scope=normalized(proposal.get('scope','').strip()),evidence=sorted({
        (e['submission_id'],e['type'],e.get('turn_id',''),e.get('document_id',''),e.get('source_id','')) for e in proposal['evidence']}))
    return hashlib.sha256(dumps(identity).encode()).hexdigest()


def meaningful_quote(quote, source):
    return quote in source and (quote.strip() == source.strip() or len(quote.strip()) >= 20 or len(quote.split()) >= 4
                                or (re.fullmatch(r'[A-Z]{1,3}[1-9]\d*=[^|\n]{2,}',quote) and quote in re.split(r' \| |\n',source)))


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

class Candidates(list):
    """The other processes one matching job is compared with, as the analyzer receives them.

    omitted counts the compatible processes beyond the bound that were not loaded. The provider adapter
    reports it to the model as candidates_omitted, so a bounded sample is not read as the whole company.
    """
    omitted = 0


def validated_document_evidence(value, documents, scope):
    """Accept only a server-hydrated catalog, separate from the submitted JSON.

    The HTTP boundary authorizes and reads exact sources from its document store.
    Here we bind those sources to the canonical submission manifest and retain a
    bounded immutable copy for the submitted revision's documentary provenance.

    A saved excerpt from a file that was removed or saved for later is bound to
    the manifest's separate 'retained' list and keeps its flags. It is provenance
    for an existing capture: that file is not in the manifest of active files, so
    it is never resolved again for matching or proposals.

    Each stored entry says how its text was read: 'origin' is 'ai_visual_transcription'
    (with 'verified': False) for a model's reading of a page or image, else
    'source_extraction'. The pair is an allow-list taken from this server-hydrated
    catalog only, so a reviewer can tell a model's reading from the file's own text.
    """
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError('Invalid verified document evidence catalog.')
    if value and not scope:
        raise ValueError('Verified document evidence requires an authorized scope.')
    manifest = documents.get('documents', []) if isinstance(documents, dict) else []
    allowed = {(item.get('id'), source.get('source_id')) for item in manifest if isinstance(item, dict)
               for source in item.get('sources', []) if isinstance(source, dict)}
    kept = documents.get('retained') if isinstance(documents, dict) else None
    saved = {(item.get('id'), source.get('source_id')) for item in kept if isinstance(item, dict)
             for source in item.get('sources', []) if isinstance(source, dict)} if isinstance(kept, list) else set()
    seen, total, result = set(), 0, []
    for source in value:
        if not isinstance(source, dict):
            raise ValueError('Invalid verified document source.')
        identity, document_id = text(source.get('id'), 200), text(source.get('document_id'), 100)
        content = source.get('text')
        checked_text = text(content, 18000)
        retained = bool(source.get('retained_only') or source.get('archived') or source.get('disposition') == 'parked')
        if (not re.fullmatch(r'doc_[A-Za-z0-9_]+', identity) or not re.fullmatch(r'doc_[A-Za-z0-9_]+', document_id)
                or not identity.startswith(document_id + '_') or not checked_text or identity in seen
                or (document_id, identity) not in (saved if retained else allowed)):
            raise ValueError('Document source is unavailable or not authorized for this submission.')
        seen.add(identity)
        total += len(content)
        if total > 600000:
            raise ValueError('Verified document evidence exceeds the submission limit.')
        result.append({'id': identity, 'document_id': document_id, 'name': text(source.get('name', ''), 500),
                       'label': text(source.get('label', ''), 500), 'text': content,
                       'source_kind': 'document', 'participant_confirmed': False, 'owner_review_required': True})
        location = source.get('location') if isinstance(source.get('location'), dict) else {}
        if 'ai_visual_transcription' in (location.get('origin'), source.get('origin')):
            result[-1].update(origin='ai_visual_transcription', verified=False)
        else:
            result[-1]['origin'] = 'source_extraction'
        if retained:
            result[-1].update(retained_only=True, archived=bool(source.get('archived')),
                              disposition=text(source.get('disposition') or '', 80))
    return result

def _process_is_alive(pid):
    """Conservatively check a job owner without sending Windows console signals."""
    if type(pid) is not int or pid<=0:return False
    if os.name=='nt':
        # os.kill(pid, 0) means CTRL_C_EVENT on Windows, not a liveness probe.
        # A zero-time process-handle wait is read-only and avoids exit-code
        # ambiguities. Unknown/access-denied owners must not lose active jobs.
        if pid>0xffffffff:return True
        import ctypes
        from ctypes import wintypes
        try:
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
            kernel.OpenProcess.restype=wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD)
            kernel.WaitForSingleObject.restype=wintypes.DWORD
            kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
            kernel.CloseHandle.restype=wintypes.BOOL
            handle=kernel.OpenProcess(0x00100000,False,pid)  # SYNCHRONIZE only
            if not handle:return ctypes.get_last_error()!=87  # missing PID
            try:
                return kernel.WaitForSingleObject(handle,0)!=0  # signaled = exited
            finally:
                kernel.CloseHandle(handle)
        except OSError:
            return True
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError,OSError):
        return True

STEP_EDIT_FIELDS = frozenset(('title','type','actor','system','description','input','output','completion_criteria',
    'handoff','control_type','data_origin','entry_mode','rule_source_ref','entity_scope','parent_process','evidence_turns'))
MEMO_EDIT_FIELDS = frozenset(('answer','status','evidence_turns'))


def validate_reviewed_fields(rows, allowed):
    """An owner edit describes which displayed fields changed, independently of source evidence."""
    if not isinstance(rows, list):
        return
    for row in rows:
        if isinstance(row, dict) and 'reviewed_fields' in row:
            fields = row['reviewed_fields']
            if (not isinstance(fields, list) or len(fields) > len(allowed)
                    or any(not isinstance(field, str) or field not in allowed for field in fields)
                    or len(set(fields)) != len(fields)):
                raise ValueError('A reviewed field must name an editable field on that step or memo finding.')


def validate_capture_provenance(value):
    """Record a declared document simulation, never an employee attestation.

    Filenames and hashes identify the supplied sources; this declaration does
    not independently verify those documents or how the actual work operates.
    """
    fields={'method','source_documents','participant_confirmed','process_owner_approved'}
    if not isinstance(value,dict) or set(value)!=fields or value.get('method')!='document_simulation':
        raise ValueError('Invalid capture provenance.')
    if value['participant_confirmed'] is not False or value['process_owner_approved'] is not False:
        raise ValueError('A document simulation cannot claim participant confirmation or process-owner approval.')
    sources=value['source_documents']
    if not isinstance(sources,list) or not 1<=len(sources)<=20:
        raise ValueError('Document simulation requires 1–20 source documents.')
    clean=[];seen=set()
    for source in sources:
        if not isinstance(source,dict) or set(source)!={'filename','sha256'}:
            raise ValueError('Invalid simulation source document.')
        filename=text(source['filename'],500)
        digest=text(source['sha256'],64).lower()
        if (not filename or filename in ('.','..') or any(ord(c)<32 or c in '/\\:' for c in filename)
                or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('Simulation sources require a filename and SHA-256 hash.')
        identity=(filename,digest)
        if identity in seen:raise ValueError('Duplicate simulation source document.')
        seen.add(identity);clean.append({'filename':filename,'sha256':digest})
    return {'method':'document_simulation','source_documents':clean,
            'participant_confirmed':False,'process_owner_approved':False}

def validate_capture_state(value, turns):
    """Record how far the notes and the working map reached when the snapshot was taken.

    The browser reports it: the server cannot see whether a capture was still running, only
    that cited evidence exists. The marker is checked against the transcript and stored with
    answer counts to record when the notes or map stop before the last answer.

    notes_assumed / map_assumed (optional, only ever true): the interview was reopened from a file
    that recorded no capture position, so the turn named is where that file stood, not a recorded
    coverage. Only the answers after it are known to be missing; the count is an estimate.
    """
    fields={'in_progress','notes_current','map_current','notes_through_turn','map_through_turn'}
    if not isinstance(value,dict) or not fields<=set(value)<=fields|{'notes_assumed','map_assumed'} or not isinstance(value['in_progress'],bool):
        raise ValueError('Invalid capture state.')
    answers=[turn['id'] for turn in turns if turn.get('role')=='user' and not turn.get('document_event')]
    latest=answers[-1] if answers else None
    clean={'in_progress':value['in_progress'],'answers':len(answers)}
    for part in ('notes','map'):
        current=value[part+'_current'];through=value[part+'_through_turn']
        if current is not None and not isinstance(current,bool):
            raise ValueError('Invalid capture state.')
        if through is not None and (not isinstance(through,str) or through not in answers):
            raise ValueError('The capture state names an answer that is not in the transcript.')
        if current is True and through!=latest:
            raise ValueError('The capture state claims to be current but stops before the last answer.')
        clean[part+'_current']=current;clean[part+'_through_turn']=through
        clean[part+'_answers']=None if current is None and through is None else (answers.index(through)+1 if through is not None else 0)
        if part+'_assumed' in value:
            # An assumed position exists only for a part that is known to be behind a later answer.
            if value[part+'_assumed'] is not True or current is not False or through is None or through==latest:
                raise ValueError('Invalid capture state.')
            clean[part+'_assumed']=True
    return clean

class InterviewAlreadySubmitted(ValueError):
    """A new process was requested for an interview that company knowledge already holds.

    Nothing is stored. The submitter chooses: a revision of that process, or a separate process on purpose.
    The HTTP boundary recognises it by its code and answers 409.
    """
    code = 'interview_already_submitted'

    def __init__(self, process_id, revision):
        super().__init__(f'This interview was already submitted as revision {revision}.')
        self.process_id, self.revision = process_id, revision


class KnowledgeGraph:
    # How long a statement waits for another program's lock on the file before failing with
    # "database is locked". The file store waits as long; SQLite's own default is 5 seconds.
    busy_timeout = 30.0

    def __init__(self, path, analyzer=None, document_resolver=None, request_scope=None):
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink(): raise ValueError('Graph database path cannot be a symlink.')
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=self.busy_timeout)
        try:
            self._open(analyzer, document_resolver, request_scope)
        except BaseException:
            # A store that cannot be opened (damaged, locked, wrong format) is not left
            # held open: on Windows an open handle would stop its owner moving the file.
            self.db.close()
            raise

    def _open(self, analyzer, document_resolver, request_scope=None):
        self.db.row_factory = sqlite3.Row
        self.db.create_function('casefold',1,normalized,deterministic=True)
        # Before any statement that creates or changes anything in the file.
        stored = self.db.execute('PRAGMA user_version').fetchone()[0]
        if not STORE_FORMATS[0] <= stored <= STORE_FORMATS[1]:
            self.db.close()
            raise StoreFormatError(
                f'The saved company knowledge on this computer uses store format {stored}, and this build of '
                f'Process Collector opens formats {STORE_FORMATS[0]} to {STORE_FORMATS[1]}. '
                + ('It was written by a newer build: open it with that build, or update this one.'
                   if stored > STORE_FORMATS[1] else 'It is too old for this build to upgrade.')
                + ' Nothing was changed.')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS revisions(submission_id TEXT NOT NULL, process_id TEXT NOT NULL, revision INTEGER NOT NULL,
          payload TEXT NOT NULL, submitter TEXT, created_at TEXT NOT NULL, PRIMARY KEY(submission_id,revision), UNIQUE(process_id,revision));
        CREATE TABLE IF NOT EXISTS submission_keys(key TEXT PRIMARY KEY, digest TEXT NOT NULL, principal TEXT, receipt TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS private_meta(key TEXT PRIMARY KEY, value BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS status_capabilities(submission_id TEXT NOT NULL, revision INTEGER NOT NULL, token_hash TEXT NOT NULL, PRIMARY KEY(submission_id,revision));
        CREATE TABLE IF NOT EXISTS private_documents(submission_id TEXT NOT NULL, revision INTEGER NOT NULL, scope TEXT NOT NULL, PRIMARY KEY(submission_id,revision));
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, revision INTEGER NOT NULL,
          status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, owner_pid INTEGER,
          detail TEXT NOT NULL DEFAULT '',
          UNIQUE(submission_id,revision), FOREIGN KEY(submission_id,revision) REFERENCES revisions(submission_id,revision));
        CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, revision INTEGER NOT NULL,
          type TEXT NOT NULL, label TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS edges(id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL, type TEXT NOT NULL,
          status TEXT NOT NULL, submission_id TEXT NOT NULL, revision INTEGER NOT NULL, evidence TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, data TEXT NOT NULL,
          status TEXT NOT NULL, review_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, stale_reason TEXT NOT NULL DEFAULT '', claim_key TEXT);
        CREATE TABLE IF NOT EXISTS canonical_groups(id TEXT PRIMARY KEY,label TEXT NOT NULL,type TEXT NOT NULL,review_version INTEGER NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',stale_reason TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS canonical_members(canonical_id TEXT NOT NULL,entity_id TEXT NOT NULL UNIQUE,PRIMARY KEY(canonical_id,entity_id),FOREIGN KEY(canonical_id) REFERENCES canonical_groups(id),FOREIGN KEY(entity_id) REFERENCES entities(id));
        CREATE TABLE IF NOT EXISTS canonical_aliases(canonical_id TEXT NOT NULL,alias TEXT NOT NULL,PRIMARY KEY(canonical_id,alias),FOREIGN KEY(canonical_id) REFERENCES canonical_groups(id));
        CREATE TABLE IF NOT EXISTS canonical_history(id TEXT PRIMARY KEY,canonical_id TEXT NOT NULL,action TEXT NOT NULL,value TEXT NOT NULL,reviewer TEXT NOT NULL,reason TEXT NOT NULL,review_version INTEGER NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(canonical_id) REFERENCES canonical_groups(id));
        CREATE TABLE IF NOT EXISTS review_history(id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, action TEXT NOT NULL,
          reviewer TEXT NOT NULL, reason TEXT NOT NULL, side TEXT, created_at TEXT NOT NULL, review_version INTEGER NOT NULL,
          FOREIGN KEY(proposal_id) REFERENCES proposals(id));
        CREATE TABLE IF NOT EXISTS deletions(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, process_id TEXT NOT NULL,
          revisions INTEGER NOT NULL, proposals INTEGER NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO private_meta(key,value) VALUES ('status_secret',?)",(secrets.token_bytes(32),))
            self.status_secret=bytes(self.db.execute("SELECT value FROM private_meta WHERE key='status_secret'").fetchone()['value'])
            group_columns={row['name'] for row in self.db.execute('PRAGMA table_info(canonical_groups)')}
            if 'status' not in group_columns: self.db.execute("ALTER TABLE canonical_groups ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            if 'stale_reason' not in group_columns: self.db.execute("ALTER TABLE canonical_groups ADD COLUMN stale_reason TEXT NOT NULL DEFAULT ''")
            if 'claim_key' not in {row['name'] for row in self.db.execute('PRAGMA table_info(proposals)')}:
                self.db.execute('ALTER TABLE proposals ADD COLUMN claim_key TEXT')
            if 'owner_pid' not in {row['name'] for row in self.db.execute('PRAGMA table_info(jobs)')}:
                self.db.execute('ALTER TABLE jobs ADD COLUMN owner_pid INTEGER')
            # What the last run of a job compared and kept, as JSON (see _run); '' until a job has run.
            if 'detail' not in {row['name'] for row in self.db.execute('PRAGMA table_info(jobs)')}:
                self.db.execute("ALTER TABLE jobs ADD COLUMN detail TEXT NOT NULL DEFAULT ''")
            if 'intent_digest' not in {row['name'] for row in self.db.execute('PRAGMA table_info(submission_keys)')}:
                self.db.execute('ALTER TABLE submission_keys ADD COLUMN intent_digest TEXT')
            for row in self.db.execute('SELECT rowid,scope FROM private_documents').fetchall():
                if not re.fullmatch(r'sha256:[0-9a-f]{64}', row['scope']):
                    self.db.execute('UPDATE private_documents SET scope=? WHERE rowid=?',(scope_digest(row['scope']),row['rowid']))
            self.db.execute('CREATE INDEX IF NOT EXISTS review_history_proposal_idx ON review_history(proposal_id)')
            self.db.execute('CREATE INDEX IF NOT EXISTS canonical_history_group_idx ON canonical_history(canonical_id)')
            self.db.execute('CREATE INDEX IF NOT EXISTS proposals_claim_idx ON proposals(claim_key)')
            self.db.execute('CREATE INDEX IF NOT EXISTS entities_revision_type_idx ON entities(submission_id,revision,type)')
            self.db.execute('CREATE INDEX IF NOT EXISTS edges_endpoints_idx ON edges(source,target)')
            self.db.execute('CREATE INDEX IF NOT EXISTS edges_target_idx ON edges(target)')
            self.db.execute('CREATE INDEX IF NOT EXISTS revisions_order_idx ON revisions(created_at,submission_id,revision)')
            self.db.execute("CREATE INDEX IF NOT EXISTS revisions_interview_idx ON revisions(json_extract(payload,'$.interview_id'))")
            self.db.execute("CREATE INDEX IF NOT EXISTS proposals_source_idx ON proposals(json_extract(data,'$.source_submission_id'),json_extract(data,'$.source_revision'))")
            self.db.execute("CREATE INDEX IF NOT EXISTS proposals_destination_idx ON proposals(json_extract(data,'$.destination_submission_id'),json_extract(data,'$.destination_revision'))")
            if stored < 2:
                for old in self.db.execute('SELECT id,data FROM proposals').fetchall():
                    try: updated = claim_identity(json.loads(old['data']))
                    except (TypeError, KeyError, ValueError): continue
                    self.db.execute('UPDATE proposals SET claim_key=? WHERE id=?',(updated,old['id']))
            if stored != STORE_FORMATS[1]: self.db.execute('PRAGMA user_version=%d' % STORE_FORMATS[1])

            for row in self.db.execute("SELECT id,owner_pid,detail FROM jobs WHERE status='processing'").fetchall():
                alive=_process_is_alive(row['owner_pid'])
                try: claimed_at=json.loads(row['detail'] or '{}').get('claimed_at')
                except (TypeError,ValueError): claimed_at=None
                if not alive or (claimed_at is not None and not 0 <= time.time()-claimed_at < 900):
                    self.db.execute("UPDATE jobs SET status='pending',owner_pid=NULL,error='Interrupted before completion.' WHERE id=?",(row['id'],))
            self.db.execute(self._FAIL_EXHAUSTED_JOBS, (self.AUTO_RESUME_ATTEMPTS,))
        self.request_scope = request_scope or nullcontext
        self.analyzer = analyzer
        self.document_resolver = document_resolver
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='knowledge')
        self.closed = False
        self.scheduling = True
        self.queued_jobs = set()
        # A job left waiting (the app stopped before it ran, it was interrupted, or no provider was configured
        # when it was filed) runs now, oldest first. _run supersedes outdated revisions, and its conditional
        # claim keeps two instances on one store from analysing the same job. The cap stops a job that brings
        # the process down from doing so at every start.
        if self.analyzer:
            for row in self.db.execute("SELECT id FROM jobs WHERE status='pending' AND attempts<? ORDER BY created_at,rowid",(self.AUTO_RESUME_ATTEMPTS,)).fetchall():
                self._schedule(row['id'])

    # How many times a waiting job is started without anyone asking (at startup, or from its submitter's status check).
    AUTO_RESUME_ATTEMPTS = 3
    _FAIL_EXHAUSTED_JOBS = ("UPDATE jobs SET status='failed',owner_pid=NULL, "
                            "error='Matching was interrupted before completion and reached its attempt limit. Your process is saved.' "
                            "WHERE status='pending' AND attempts>=?")
    # How many other processes one matching job compares with: the most recent ones of a compatible scope.
    CANDIDATE_LIMIT = 8

    @contextmanager
    def _write(self):
        with self.lock:
            if self.closed: raise ValueError('Knowledge storage is closed.')
            with self.db:
                # Reserve the write transaction before reading an idempotency
                # key or latest revision. Separate local server processes use
                # distinct Python locks but must still serialize this decision.
                self.db.execute('BEGIN IMMEDIATE')
                yield

    @staticmethod
    def _intent_digest(value):
        if value is not None and (not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value)):
            raise ValueError('Invalid server submission intent.')
        return value

    def _key_receipt(self, row):
        receipt=json.loads(row['receipt'])
        receipt['status_token']=self._status_token(receipt['submission_id'],receipt['revision'])
        row = self.db.execute('SELECT status FROM jobs WHERE submission_id=? AND revision=?',(receipt['submission_id'],receipt['revision'])).fetchone()
        if row: receipt['status'] = row['status']
        return receipt

    def recover_submission(self, key, intent_digest, principal=None):
        """Recover an exact server-bound attempt before mutable file hydration.

        The endpoint supplies the digest as a trusted argument, never a browser
        field. Legacy keys have no raw-intent digest, so they still require the
        original canonical submit path before they can be upgraded safely.
        """
        intent_digest=self._intent_digest(intent_digest)
        if not key: return None
        try:key=str(uuid.UUID(key))
        except (ValueError,TypeError,AttributeError):raise ValueError('Invalid submission key.') from None
        with self.lock:
            if self.closed:raise ValueError('Knowledge storage is closed.')
            row=self.db.execute('SELECT * FROM submission_keys WHERE key=?',(key,)).fetchone()
            if not row:return None
            if row['principal']!=(principal or None):raise ValueError('Submission key was already used for different content.')
            if row['intent_digest'] is None:return None
            if intent_digest is None or not hmac.compare_digest(row['intent_digest'],intent_digest):raise ValueError('Submission key was already used for different content.')
            return self._key_receipt(row)

    def submission_unsaved(self, key):
        """True only when no submission was ever stored under this submission key.

        The HTTP boundary adds it to a refusal, so the browser can release an attempt it could not
        confirm earlier. An unusable key is not evidence either way.
        """
        try:key=str(uuid.UUID(key))
        except (ValueError,TypeError,AttributeError):return False
        with self.lock:
            if self.closed:return False
            return self.db.execute('SELECT 1 FROM submission_keys WHERE key=?',(key,)).fetchone() is None

    def submit(self, payload, principal=None, document_scope=None, intent_digest=None, document_evidence=None,
               base_revision=None, acknowledged_revision=None):
        """Store a new process, or a revision of payload['process_id'].

        base_revision: the revision the submitting copy was filed as (0 when it does not know). When it is
        given and is not the latest stored revision, the revision is refused with RevisionConflict unless
        acknowledged_revision names that latest revision: an older saved copy or a stale tab must not
        silently become the newest revision. Both are trusted arguments of the caller, like the other
        keyword arguments; they are not read from the payload and are not stored.
        """
        intent_digest=self._intent_digest(intent_digest)
        for value in (base_revision,acknowledged_revision):
            if value is not None and (type(value) is not int or not 0<=value<=9223372036854775807):
                raise ValueError('Invalid base revision.')
        if not isinstance(payload, dict):
            raise ValueError('Submission must be an object.')
        pending = [(payload, 0)]
        while pending:
            value, depth = pending.pop()
            if depth > 64:
                raise ValueError('Submission JSON nesting exceeds 64 levels.')
            children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
            pending.extend((child, depth + 1) for child in children)
        try:
            payload = json.loads(dumps(payload))
        except (TypeError, ValueError, RecursionError):
            raise ValueError('Submission must contain JSON data.') from None
        for key in ('submitter', 'principal', 'authenticated_submitter', 'document_evidence'):
            payload.pop(key, None)
        if 'capture_provenance' in payload:
            payload['capture_provenance']=validate_capture_provenance(payload['capture_provenance'])
            closure=payload.get('closure')
            if isinstance(closure,dict) and closure.get('confirmed',False) is not False:
                raise ValueError('A document simulation cannot claim participant confirmation.')
        docs=payload.get('documents')
        if isinstance(docs,dict): docs.pop('scope',None)
        if document_scope is not None:
            document_scope=text(document_scope,500)
            if not document_scope: raise ValueError('Invalid document scope.')
        catalog=validated_document_evidence(document_evidence, docs, document_scope)
        if len(dumps(payload).encode('utf-8')) > 1_000_000:
            raise ValueError('Submission exceeds the local size limit.')
        if catalog: payload['document_evidence']=catalog
        context = payload.get('context', {})
        turns = payload.get('turns', [])
        draft = payload.get('draft')
        if draft is None: draft = {}
        if not isinstance(context, dict) or not isinstance(turns, list) or not isinstance(draft, dict):
            raise ValueError('Submission requires valid context, turns and draft.')
        for artifact in (payload, draft, payload.get('workflow')):
            if isinstance(artifact, dict):
                if 'generated_by' in artifact:
                    validate_generation_records(artifact['generated_by'])
                for key in ('app_version', 'app_build'):
                    if key in artifact and (not isinstance(artifact[key], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,179}', artifact[key])):
                        raise ValueError('The application version or build identifier is invalid.')
        validate_reviewed_fields(draft.get('steps'), STEP_EDIT_FIELDS)
        validate_reviewed_fields(draft.get('memo_summary'), MEMO_EDIT_FIELDS)
        # A saved excerpt from a removed or parked file is provenance, not evidence that a file was read for this submission.
        retained={item['id'] for item in catalog if item.get('retained_only')}
        if len(turns)>400:
            raise ValueError(f'A submission holds at most 400 transcript turns; this interview has {len(turns)}.')
        if (len(catalog)==len(retained) and not any(isinstance(t,dict) and t.get('role')=='user' and not t.get('document_event') and isinstance(t.get('text'),str) and t['text'].strip() for t in turns)):
            raise ValueError('A submission requires a participant statement or verified document evidence.')
        seen=set()
        for turn in turns:
            if not isinstance(turn,dict) or turn.get('role') not in ('user','assistant'):
                raise ValueError('Invalid transcript turn.')
            tid=text(turn.get('id'),80)
            if not tid or tid in seen:
                raise ValueError('Transcript turn IDs must be unique.')
            seen.add(tid); named_text(turn.get('text'),6000,'Transcript turn '+tid)
        for artifact in (draft, payload.get('workflow')):
            if isinstance(artifact, dict) and isinstance(artifact.get('steps'), list):
                gpfs_interview.validate_operating_details(artifact['steps'], turns, catalog, context)
        if retained:
            # A saved excerpt may stay beside other evidence. A part may rest on saved excerpts alone only where
            # each one is provenance for an existing capture: a passage that an earlier revision of this same
            # process already holds. A new process has no earlier capture, and a revision cannot bring in a
            # removed or parked file's passage that way either. The HTTP boundary reports this rule first, by
            # file and by the step or note that cites it (check_document_citations).
            supported={'context'}|{item['id'] for item in catalog if not item.get('retained_only')}|{t['id'] for t in turns if t.get('role')=='user' and not t.get('document_event')}
            revised=payload.get('process_id')
            unfiled=retained-self.filed_document_sources(revised) if revised else retained
            pending=[payload] if unfiled else []
            while pending:
                value=pending.pop()
                if isinstance(value,list): pending.extend(value)
                elif isinstance(value,dict):
                    refs=[ref for ref in value['evidence_turns'] if isinstance(ref,str)] if isinstance(value.get('evidence_turns'),list) else []
                    if unfiled.intersection(refs) and not supported.intersection(refs):
                        raise ValueError('A revision cannot rest only on saved excerpts that no earlier revision of this process holds.' if revised
                                         else 'A new process cannot rest only on saved excerpts from a removed or parked file.')
                    pending.extend(value.values())
        if payload.get('capture') is None: payload.pop('capture',None)
        else: payload['capture']=validate_capture_state(payload['capture'],turns)
        # A revision that does not carry an attribution field keeps the one of the revision before it
        # (filled in below, once that revision is known). A field sent empty is cleared on purpose.
        unsent=[key for key in ('participant','team','department','scope') if key not in payload]
        for key,name in (('participant','Participant'),('team','Team'),('department','Department'),('scope','Business scope')):
            payload[key]=named_text(payload.get(key,'') or '',500,name)
        key=payload.get('submission_key')
        if key:
            try: key=str(uuid.UUID(key))
            except (ValueError, TypeError, AttributeError): raise ValueError('Invalid submission key.') from None
        # The interview's own identity, created when it started and kept in every saved copy. It lets the
        # store notice the same interview arriving again without a process ID (a second tab, or a copy
        # saved before the first submission). separate_process is the submitter's explicit choice to file
        # it as another process all the same; it is a request flag, not part of the stored interview.
        interview_id=payload.get('interview_id')
        if interview_id is None: payload.pop('interview_id',None)
        else:
            try: interview_id=payload['interview_id']=str(uuid.UUID(interview_id))
            except (ValueError, TypeError, AttributeError): raise ValueError('Invalid interview ID.') from None
        separate=payload.pop('separate_process',None)
        if separate is not None and not isinstance(separate,bool): raise ValueError('Invalid separate process choice.')
        digest_payload=dict(payload); digest_payload.pop('saved_at',None)
        # The recorded reading (origin, verified) is not part of the content digest: a key first used by a
        # build that did not record it must still recognise the same submission.
        if catalog: digest_payload['document_evidence']=[{k:v for k,v in item.items() if k not in ('origin','verified')} for item in catalog]
        digest=hashlib.sha256(dumps({'payload':digest_payload,'scope':document_scope}).encode()).hexdigest()
        process_id=payload.get('process_id') or new_id()
        try: process_id=str(uuid.UUID(process_id))
        except (ValueError,TypeError,AttributeError): raise ValueError('Invalid process ID.') from None
        with self._write():
            if key:
                prior=self.db.execute('SELECT * FROM submission_keys WHERE key=?',(key,)).fetchone()
                if prior:
                    if prior['principal']!=(principal or None):
                        raise ValueError('Submission key was already used for different content.')
                    if intent_digest is not None and prior['intent_digest'] is not None:
                        if not hmac.compare_digest(prior['intent_digest'],intent_digest):raise ValueError('Submission key was already used for different content.')
                    elif prior['digest']!=digest:
                        raise ValueError('Submission key was already used for different content.')
                    if intent_digest is not None and prior['intent_digest'] is None:
                        self.db.execute('UPDATE submission_keys SET intent_digest=? WHERE key=?',(intent_digest,key))
                    return self._key_receipt(prior)
            previous=self.db.execute('SELECT submission_id,revision FROM revisions WHERE process_id=? ORDER BY revision DESC LIMIT 1',(process_id,)).fetchone()
            if payload.get('process_id') and not previous:
                raise ValueError('Process does not exist.')
            # Decided under the write lock that also assigns the revision number, like expected_revision in review.
            if previous and base_revision is not None and previous['revision'] not in (base_revision,acknowledged_revision):
                raise RevisionConflict(base_revision,previous['revision'])
            if interview_id and not previous and separate is not True:
                twin=self.db.execute("SELECT process_id,MAX(revision) AS revision FROM revisions WHERE json_extract(payload,'$.interview_id')=? "
                                     "GROUP BY process_id ORDER BY MAX(created_at) DESC LIMIT 1",(interview_id,)).fetchone()
                if twin: raise InterviewAlreadySubmitted(twin['process_id'],twin['revision'])
            submission_id=previous['submission_id'] if previous else new_id()
            revision=previous['revision']+1 if previous else 1
            if previous and unsent:
                earlier=json.loads(self.db.execute('SELECT payload FROM revisions WHERE submission_id=? AND revision=?',(previous['submission_id'],previous['revision'])).fetchone()['payload'])
                for field in unsent:
                    kept=earlier.get(field)
                    payload[field]=kept.strip()[:500] if isinstance(kept,str) else ''
            self.db.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?)',(submission_id,process_id,revision,dumps(payload),text(principal,500) if principal else None,now()))
            if document_scope:
                self.db.execute('INSERT INTO private_documents VALUES (?,?,?)',(submission_id,revision,scope_digest(document_scope)))
            # Existing conclusions continue to exist, but previous approvals cannot transfer.
            if previous:
                for row in self.db.execute("SELECT id,data,review_version FROM proposals WHERE status NOT IN ('stale','superseded')").fetchall():
                    data=json.loads(row['data'])
                    if submission_id in (data['source_submission_id'],data['destination_submission_id']):
                        self.db.execute("UPDATE proposals SET status='stale', stale_reason=?, review_version=review_version+1 WHERE id=?",('Submission revised; evidence requires review.',row['id']))
                        self.db.execute('INSERT INTO review_history VALUES (?,?,?,?,?,?,?,?)',(new_id(),row['id'],'stale','system','Submission revised; evidence requires review.',None,now(),row['review_version']+1))
            if previous:
                groups=self.db.execute('SELECT DISTINCT g.id,g.review_version FROM canonical_groups g JOIN canonical_members m ON m.canonical_id=g.id JOIN entities e ON e.id=m.entity_id WHERE e.submission_id=? AND e.revision<?',(submission_id,revision)).fetchall()
                for group in groups:
                    reason='A member source was revised; replace outdated members and review the group.'
                    self.db.execute("UPDATE canonical_groups SET status='stale',stale_reason=?,review_version=review_version+1 WHERE id=?",(reason,group['id']))
                    self.db.execute('INSERT INTO canonical_history VALUES (?,?,?,?,?,?,?,?)',(new_id(),group['id'],'stale',submission_id,'system',reason,group['review_version']+1,now()))
            self._materialize(submission_id,process_id,revision,payload)
            job_id=new_id()
            self.db.execute('INSERT INTO jobs(id,submission_id,revision,status,created_at) VALUES (?,?,?,?,?)',(job_id,submission_id,revision,'pending',now()))
            receipt={'submission_id':submission_id,'process_id':process_id,'revision':revision,'job_id':job_id,'status':'pending'}
            status_token=self._status_token(submission_id,revision)
            self.db.execute('INSERT INTO status_capabilities VALUES (?,?,?)',(submission_id,revision,hashlib.sha256(status_token.encode()).hexdigest()))
            if key: self.db.execute('INSERT INTO submission_keys(key,digest,principal,receipt,intent_digest) VALUES (?,?,?,?,?)',(key,digest,principal or None,dumps(receipt),intent_digest))
        if self.analyzer:
            self._schedule(job_id)
        receipt['status_token']=status_token
        return receipt

    def _status_token(self,submission_id,revision):
        return hmac.new(self.status_secret,(submission_id+':'+str(revision)).encode('utf-8'),hashlib.sha256).hexdigest()

    def status(self,submission_id,revision,status_token):
        if not isinstance(submission_id,str) or type(revision) is not int or revision<1 or not isinstance(status_token,str) or len(status_token)>200:
            raise PermissionError('Submission status unavailable.')
        with self.lock:
            row=self.db.execute('SELECT c.token_hash,j.id,j.status,j.error,j.attempts FROM status_capabilities c JOIN jobs j ON j.submission_id=c.submission_id AND j.revision=c.revision WHERE c.submission_id=? AND c.revision=?',(submission_id,revision)).fetchone()
            candidate=hashlib.sha256(status_token.encode('utf-8')).hexdigest()
            expected=row['token_hash'] if row else '0'*64
            if not hmac.compare_digest(expected,candidate) or not row:
                # A deleted process keeps no capability row; its holder is recognised by the token itself and told.
                gone=None if row else self.db.execute('SELECT revisions FROM deletions WHERE submission_id=? ORDER BY rowid DESC LIMIT 1',(submission_id,)).fetchone()
                if gone and revision<=gone['revisions'] and hmac.compare_digest(self._status_token(submission_id,revision),status_token):
                    return {'submission_id':submission_id,'revision':revision,'job_id':None,'status':'deleted','error':'','attempts':0,'stalled':False,'latest_revision':None}
                raise PermissionError('Submission status unavailable.')
            # The caller's own waiting job is started here when nothing in this process is going to run it (a
            # provider configured since it was filed, or a lost worker entry), under the same cap as at startup.
            # 'stalled' tells the submitter that the job is waiting and no worker holds it.
            if row['status']=='pending' and row['attempts']>=self.AUTO_RESUME_ATTEMPTS:
                with self.db:
                    self.db.execute(self._FAIL_EXHAUSTED_JOBS+' AND id=?',(self.AUTO_RESUME_ATTEMPTS,row['id']))
                row=self.db.execute('SELECT id,status,error,attempts FROM jobs WHERE id=?',(row['id'],)).fetchone()
            stalled=False
            if row['status']=='pending' and not self.closed:
                if self.analyzer and row['attempts']<self.AUTO_RESUME_ATTEMPTS: self._schedule(row['id'])
                stalled=row['id'] not in self.queued_jobs
            return {'submission_id':submission_id,'revision':revision,'job_id':row['id'],'status':row['status'],'error':row['error'],'attempts':row['attempts'],'stalled':stalled,
                    # So a saved copy can say that it is older than the newest revision of its process.
                    'latest_revision':self._latest(submission_id)}

    def _materialize(self, sid, pid, rev, payload):
        submitted_draft=payload.get('draft') or {}
        working=payload.get('workflow')
        if working is None: working={}
        if not isinstance(working,dict): raise ValueError('Submitted workflow must be an object.')
        # The graph comes from the review draft. The working map replaces it only before a draft exists,
        # or when an unedited draft predates newer answers: a reviewer's corrections are never left out,
        # and a draft with steps is never replaced by a working map that has none.
        # web/knowledge-ui.js (graphSource) tells the submitter the same rule; keep the two together.
        draft_stale=bool(submitted_draft) and bool(payload.get('draft_stale'))
        draft_edited=payload.get('draft_edited') is True
        working_has_more=bool(working.get('steps')) or not submitted_draft.get('steps')
        source='workflow' if (not submitted_draft or (draft_stale and not draft_edited and working_has_more)) else 'draft'
        basis={'source':source,**({'draft_stale':draft_stale,'draft_edited':draft_edited} if submitted_draft else {})}
        draft=working if source=='workflow' else submitted_draft
        steps=draft.get('steps',[])
        connections=draft.get('connections',[])
        if not isinstance(steps,list) or not isinstance(connections,list): raise ValueError('Submitted steps and connections must be arrays.')
        if len(steps)>80 or len(connections)>150: raise ValueError('Submitted workflow exceeds graph limits.')
        process_entity=new_id()
        derived = payload.get('derived_process_title')
        title = (derived.strip() if payload.get('process_name_manual') is False
                 and isinstance(derived,str) and len(derived)<=180 else '')
        title = title or (payload.get('context') or {}).get('process_name') or draft.get('title') or 'Untitled process'
        title=named_text(title,1000,'Process name')
        self.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',(process_entity,sid,rev,'process',title,dumps(basis)))
        version_entity=new_id()
        self.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',(version_entity,sid,rev,'process_version',title+' (revision '+str(rev)+')',dumps(basis)))
        def link(source,target,kind,evidence):
            self.db.execute('INSERT INTO edges VALUES (?,?,?,?,?,?,?,?)',(new_id(),source,target,kind,'reported',sid,rev,dumps(evidence)))
        # One entity per role, system, team, scope or business object named in this revision, whatever the
        # number of steps that name it: each mention adds an edge that carries that step's evidence. The
        # first spelling is the label; mentions are matched on type and case-folded label.
        # A business object (a step's Input or Output, an Inputs or Outputs line) may be a sentence: the Review
        # editor accepts 6,000 characters there, and so does this. Lists and the graph get a label of at most
        # 1,000 characters; the whole text stays in the entity's data and is what mentions are matched on.
        # name says which field a value came from, for a refusal the submitter can find in Review.
        components={}
        def component(parent,kind,label,relationship,evidence,name):
            if not isinstance(label,str) or not label.strip() or label.strip().upper() in ('UNKNOWN','N/A','NOT KNOWN','UNKNOWN / TBD','TBD'):
                return
            label=named_text(label,6000 if kind=='business_object' else 1000,name); key=(kind,label.casefold()); eid=components.get(key)
            if eid is None:
                eid=components[key]=new_id()
                shown,data=(label,'{}') if len(label)<=1000 else (label[:999]+'…',dumps({'full_label':label}))
                self.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',(eid,sid,rev,kind,shown,data))
            link(parent,eid,relationship,evidence)
        link(process_entity,version_entity,'has_version',{})
        for field,kind,relation,name in (('team','team','performed_by','Team'),('department','team','performed_by','Department'),('scope','scope','applies_to','Business scope')):
            component(version_entity,kind,payload.get(field,''),relation,{'source':'submission_context','field':field},name)
        for field,kind,relation,name in (('inputs','business_object','consumes','Inputs'),('outputs','business_object','produces','Outputs')):
            values=draft.get(field,[])
            if isinstance(values,list):
                sidecar = draft.get('field_evidence') or []
                for line,value in enumerate(values[:100],1):
                    refs = []
                    for entry in sidecar if isinstance(sidecar,list) else []:
                        if isinstance(entry,dict) and entry.get('field')==field and type(entry.get('index')) is int and entry['index']==line-1 and entry.get('text')==value:
                            cited = entry.get('evidence_turns')
                            if not isinstance(cited,list) or any(not isinstance(ref,str) for ref in cited):
                                raise ValueError('Draft field sources must be a list of source identifiers.')
                            refs.extend(cited)
                    component(version_entity,kind,value,relation,{'source':source,'field':field,'evidence_turns':list(dict.fromkeys(refs))},f'{name}, line {line},')
        document_ids={item['id'] for item in payload.get('document_evidence',[])}
        participant_ids={turn['id'] for turn in payload.get('turns',[]) if turn.get('role')=='user' and not turn.get('document_event')}
        valid_evidence=participant_ids | {'context'} | document_ids
        def validate_evidence(item):
            refs=item.get('evidence_turns',[])
            if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in valid_evidence for ref in refs):
                raise ValueError('Submitted workflow references unknown or non-participant evidence.')
        pending = [payload.get(key) for key in ('draft','workflow','memo_findings','connections_out')]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                if 'evidence_turns' in item: validate_evidence(item)
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        def provenance(item):
            refs=set(item.get('evidence_turns',[]))
            cited_documents=sorted(refs & document_ids)
            if not cited_documents: return {}
            return {'source_kind':'mixed' if refs & participant_ids else 'document',
                    'document_source_ids':cited_documents, 'owner_review_required':True,
                    **({'participant_confirmed':False} if not refs & participant_ids else {})}
        ids={}
        for step in steps:
            if not isinstance(step,dict): raise ValueError('Invalid submitted step.')
            validate_evidence(step)
            local=named_text(step.get('id',''),80,'A step ID')
            if not local or local in ids: raise ValueError('Submitted step IDs must be unique.')
            eid=new_id();ids[local]=eid
            label=named_text(step.get('title','') or 'Untitled step',1000,f'Step {local}: Title')
            kind='decision' if step.get('type')=='decision' else 'step'
            content = {k:v for k,v in step.items() if k not in ('source_kind','document_source_ids','owner_review_required','participant_confirmed')}
            self.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',(eid,sid,rev,kind,label,dumps({**content,'_materialized_from':source,**provenance(step)})))
            link(version_entity,eid,'contains',{'step_id':local,**provenance(step)})
            # The names are the Review editor's field labels (web/app.js), so a refusal can be found there.
            for field,entity_type,relation,name in (('actor','role','performed_by','Owner / role'),('system','system','uses_system','System / tool'),('input','business_object','consumes','Input'),('output','business_object','produces','Output')):
                component(eid,entity_type,step.get(field,''),relation,{'step_id':local,'evidence_turns':step.get('evidence_turns',[]),**provenance(step)},f'Step {local}: {name}')
        for edge in connections:
            if (not isinstance(edge,dict) or not isinstance(edge.get('from'),str) or not isinstance(edge.get('to'),str)
                    or edge['from'] not in ids or edge['to'] not in ids):
                raise ValueError('Submitted workflow connection references a missing step.')
            validate_evidence(edge)
            content = {k:v for k,v in edge.items() if k not in ('source_kind','document_source_ids','owner_review_required','participant_confirmed')}
            state = 'reported' if edge.get('evidence_turns') else 'unevidenced'
            self.db.execute('INSERT INTO edges VALUES (?,?,?,?,?,?,?,?)',(new_id(),ids[edge['to']],ids[edge['from']],'happens_after',state,sid,rev,dumps({**content,'_materialized_from':source,**provenance(edge)})))

    def _revision(self,sid,revision):
        row=self.db.execute('SELECT * FROM revisions WHERE submission_id=? AND revision=?',(sid,revision)).fetchone()
        if not row: raise ValueError('Submission revision is unavailable.')
        return self._submission(row)

    def _submission(self,row):
        data=json.loads(row['payload'])
        return {**data,'submission_id':row['submission_id'],'process_id':row['process_id'],'revision':row['revision'],'submitter':row['submitter'],'created_at':row['created_at']}

    def _latest(self,sid):
        return self.db.execute('SELECT MAX(revision) AS revision FROM revisions WHERE submission_id=?',(sid,)).fetchone()['revision']

    def _document_source(self, submission_id, revision, document_id, source_id):
        if not self.document_resolver: raise ValueError('Document source resolution is unavailable.')
        with self.lock:
            data=self._revision(submission_id,revision)
        documents=data.get('documents') or {}
        docs=documents.get('documents',[]) if isinstance(documents,dict) else []
        doc=next((d for d in docs if isinstance(d,dict) and d.get('id')==document_id),None)
        if not doc or not any(isinstance(s,dict) and s.get('source_id')==source_id for s in doc.get('sources',[])):
            raise ValueError('Document source is not in this submission revision.')
        with self.lock:
            row=self.db.execute('SELECT scope FROM private_documents WHERE submission_id=? AND revision=?',(submission_id,revision)).fetchone()
        if not row: raise PermissionError('Document source unavailable.')
        return self._resolve_source(StoredScopeDigest(row['scope']),document_id,source_id)

    def _resolve_source(self, scope, document_id, source_id):
        try: result=self.document_resolver(scope,document_id,source_id)
        except PermissionError as error:
            if error.errno is not None: raise OSError('Document storage is temporarily inaccessible.') from None
            raise ValueError('Document source is unavailable.') from None
        except ValueError: raise ValueError('Document source is unavailable.') from None
        if not isinstance(result,dict) or not isinstance(result.get('text'),str):
            raise ValueError('Document source text is unavailable.')
        # A page or image that has not been read holds a placeholder sentence, not file content. It is never an
        # excerpt for matching or document-supported evidence, and evidence that rested on one goes back for review.
        location=result.get('location') if isinstance(result.get('location'),dict) else {}
        if any(part.get('requires_vision') or part.get('origin')=='visual_placeholder' for part in (result,location)):
            raise ValueError('Document source has not been read.')
        return result

    def _with_document_excerpts(self, record):
        excerpts=[]
        docs=record.get('documents') or {}
        if not isinstance(docs,dict) or not docs.get('documents'): return {**record,'document_excerpts':[]}
        with self.lock:
            row = self.db.execute('SELECT scope FROM private_documents WHERE submission_id=? AND revision=?',(record['submission_id'],record['revision'])).fetchone()
        if not row: return {**record,'document_excerpts':[]}
        credential = StoredScopeDigest(row['scope'])
        cited = {item['id'] for item in record.get('document_evidence',[]) if not item.get('retained_only')}
        documents = [doc for doc in docs['documents'] if isinstance(doc,dict)]
        sources = [(doc,item) for doc in documents for item in doc.get('sources',[]) if isinstance(item,dict)]
        sources.sort(key=lambda pair: pair[1].get('source_id') not in cited)
        for doc, item in sources[:24]:
            try:
                source=self._resolve_source(credential,doc.get('id',''),item.get('source_id',''))
            except (ValueError,PermissionError): continue
            if source['text'].strip():
                excerpts.append({'document_id':doc['id'],'source_id':item['source_id'],'label':source.get('label',''),
                                 'text':source['text'][:1200], 'origin':source.get('origin','source_extraction'),
                                 'verified':source.get('verified'),'cited':item['source_id'] in cited,'excerpt_truncated':len(source['text'])>1200})
            if len(excerpts)>=2: break
        return {**record,'document_excerpts':excerpts}

    def _validate_proposal(self,p, current, candidates):
        if not isinstance(p,dict): raise ValueError('Invalid proposal.')
        permitted={current['submission_id']:current,**{x['submission_id']:x for x in candidates}}
        a,b=p.get('source_submission_id'),p.get('destination_submission_id')
        if a==b or a not in permitted or b not in permitted or current['submission_id'] not in (a,b): raise ValueError('Invalid proposal endpoints.')
        if any(type(p.get(side+'_revision')) is not int or p.get(side+'_revision') != permitted[sid]['revision']
               for side,sid in (('source',a),('destination',b))):
            raise ValueError('Proposal references an unavailable revision.')
        kind=p.get('relationship_type')
        if kind not in RELATIONSHIPS: raise ValueError('Unsupported relationship type.')
        scope_a,scope_b=permitted[a].get('scope',''),permitted[b].get('scope','')
        if scope_a and scope_b and scope_a.casefold()!=scope_b.casefold(): raise ValueError('Proposal scopes do not match.')
        scope=text(p.get('scope',''),500)
        if scope and any(s and scope.casefold()!=s.casefold() for s in (scope_a,scope_b)):
            raise ValueError('Proposal scope does not match its sources.')
        ev=p.get('evidence')
        if not isinstance(ev,list) or not 2<=len(ev)<=20: raise ValueError('Proposal needs evidence from both processes.')
        sides=set();clean=[]
        for item in ev:
            if not isinstance(item,dict): raise ValueError('Invalid proposal evidence.')
            sid=item.get('submission_id'); source=permitted.get(sid)
            if sid not in (a,b) or not source or type(item.get('revision')) is not int or item.get('revision')!=source['revision']: raise ValueError('Invalid evidence revision.')
            quote=text(item.get('quote',''),6000)
            if not quote: raise ValueError('Evidence needs a nonempty exact quote.')
            kind=item.get('type') or 'employee_reported'
            if kind in ('employee_reported','simulated_document_account'):
                tid=text(item.get('turn_id',''),80)
                match=next((t for t in source.get('turns',[]) if t.get('id')==tid and t.get('role')=='user' and not t.get('document_event')),None)
                if not match or quote not in match['text']: raise ValueError('Evidence must quote an exact participant statement.')
                if not meaningful_quote(quote,match['text']): raise ValueError('Evidence must quote a meaningful participant statement.')
                provenance=source.get('capture_provenance')
                simulated=isinstance(provenance,dict) and provenance.get('method')=='document_simulation'
                if kind=='simulated_document_account' and not simulated:
                    raise ValueError('Simulation evidence requires declared document-simulation provenance.')
                # Attribution is derived from stored provenance, not a model's
                # proposed label. A simulated answer is never employee evidence.
                kind='simulated_document_account' if simulated else 'employee_reported'
                evidence={'submission_id':sid,'revision':source['revision'],'turn_id':tid,'quote':quote,'type':kind}
                if simulated:
                    evidence.update(label='Document-derived simulation — not an employee statement',
                                    capture_provenance=validate_capture_provenance(provenance))
            elif kind=='document_supported':
                did=text(item.get('document_id',''),100); source_id=text(item.get('source_id',''),200)
                resolved=self._document_source(sid,source['revision'],did,source_id)
                if not meaningful_quote(quote,resolved['text']): raise ValueError('Evidence must quote an exact document source of meaningful length.')
                evidence={'submission_id':sid,'revision':source['revision'],'document_id':did,'source_id':source_id,'quote':quote,'type':kind,
                          'label':resolved.get('label',''),'origin':resolved.get('origin','source_extraction'),
                          'verified':resolved.get('verified'), 'source_hash':hashlib.sha256(resolved['text'].encode('utf-8')).hexdigest()}
            else: raise ValueError('Unsupported evidence type.')
            sides.add(sid);clean.append(evidence)
        if sides!={a,b}: raise ValueError('Proposal needs participant evidence from both processes.')
        result={k:p[k] for k in ('source_submission_id','destination_submission_id','source_revision','destination_revision','relationship_type')}
        for k in ('scope','condition','explanation','inference'):
            result[k]=text(p.get(k,'') or '',6000)
        for k in ('missing_evidence','contradictions'):
            values=p.get(k,[]) or []
            if isinstance(values,str): values=[values] if values.strip() else []
            if not isinstance(values,list) or len(values)>20: raise ValueError('Invalid proposal uncertainties.')
            result[k]=[text(v,2000) for v in values]
        if not result['explanation'] or not result['inference']: raise ValueError('Proposal requires an explanation and inference.')
        result['evidence']=clean
        return result

    def _run(self,job_id):
        with self.lock,self.db:
            job=self.db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not job or job['status']!='pending' or not self.scheduling: return
            if self._latest(job['submission_id']) != job['revision']:
                self.db.execute("UPDATE jobs SET status='superseded',owner_pid=NULL WHERE id=?",(job_id,));return
            claimed=self.db.execute("UPDATE jobs SET status='processing',attempts=attempts+1,error='',owner_pid=? WHERE id=? AND status='pending'",(os.getpid(),job_id))
            if claimed.rowcount!=1: return
            current=self._revision(job['submission_id'],job['revision'])
            # Explicitly incompatible scopes can never support a proposal. The scope of each other process's
            # latest revision is compared in SQL before the bound is applied, so a compatible process is
            # found however many submissions of other scopes are newer. Only the eight most recent compatible
            # ones are loaded (the provider adapter's bound), so unneeded files are never read or sent; the
            # number left out is recorded on the job and given to the adapter.
            current_scope=normalized(current.get('scope','').strip())
            compatible=("FROM revisions r JOIN (SELECT submission_id,MAX(revision) AS revision FROM revisions WHERE submission_id!=? GROUP BY submission_id) l"
                        " ON l.submission_id=r.submission_id AND l.revision=r.revision"
                        " WHERE (?='' OR COALESCE(json_extract(r.payload,'$.scope'),'')='' OR casefold(trim(json_extract(r.payload,'$.scope')))=?)")
            scoped=(job['submission_id'],current_scope,current_scope)
            if current.get('interview_id'):
                # Copies of the same interview cannot supply evidence for either side of a handoff.
                compatible += " AND COALESCE(json_extract(r.payload,'$.interview_id'),'')!=?"
                scoped += (current['interview_id'],)
            total=self.db.execute('SELECT COUNT(*) '+compatible,scoped).fetchone()[0]
            rows=self.db.execute('SELECT r.submission_id,r.revision '+compatible+' ORDER BY r.rowid DESC LIMIT ?',scoped+(self.CANDIDATE_LIMIT,)).fetchall()
            candidates=[self._revision(row['submission_id'],row['revision']) for row in rows]
            token = secrets.token_hex(16)
            detail={'candidates':len(candidates),'candidates_omitted':total-len(candidates),'claimed_at':time.time(),'claim_token':token}
            self.db.execute('UPDATE jobs SET detail=? WHERE id=?',(dumps(detail),job_id))
        try:
            if self.document_resolver:
                current=self._with_document_excerpts(current)
                candidates=[self._with_document_excerpts(item) for item in candidates]
            candidates=Candidates(candidates);candidates.omitted=detail['candidates_omitted']
            with self.request_scope(current.get('interview_id')):
                proposed=self.analyzer(current,candidates) if candidates else []
            if not isinstance(proposed,list) or len(proposed)>100: raise ValueError('Invalid analyzer response.')
            # Each proposal stands or falls alone. One that fails a check (a quote that is not verbatim, evidence
            # from one side only, a wrong revision or scope) is dropped and never stored; the others are kept and
            # the job completes. The reasons are the validator's own sentences, counted on the job row.
            valid=[];dropped={}
            for p in proposed:
                try: valid.append(self._validate_proposal(p,current,candidates))
                except UnicodeError: reason='Proposal text is not valid Unicode.'
                except ValueError as error: reason=str(error)[:200]
                except PermissionError: reason='Document source is unavailable.'
                except (TypeError,KeyError,AttributeError): reason='Malformed proposal.'
                else: continue
                dropped[reason]=dropped.get(reason,0)+1
            unique={}
            for proposal in valid:
                a,b=proposal['source_submission_id'],proposal['destination_submission_id']
                key=(tuple(sorted((a,b))),proposal['relationship_type'],normalized(proposal['scope']))
                kept=unique.setdefault(key,proposal)
                if kept is proposal: continue
                if kept['source_submission_id']!=a:
                    kept['contradictions']=list(dict.fromkeys(kept['contradictions']+['The matching result also proposed this relationship in the reverse direction.']))
                else:
                    for entry in proposal['evidence']:
                        if entry not in kept['evidence'] and len(kept['evidence'])<20: kept['evidence'].append(entry)
            valid=list(unique.values())
            detail.update(proposals_returned=len(proposed),proposals_kept=len(valid),proposals_dropped=len(proposed)-len(valid),
                          **({'dropped_reasons':dropped} if dropped else {}))
            with self.lock,self.db:
                # A revision on another database connection must either be
                # visible to these checks or invalidate the newly saved claims.
                self.db.execute('BEGIN IMMEDIATE')
                owner=self.db.execute("SELECT json_extract(detail,'$.claim_token') FROM jobs WHERE id=? AND status='processing'",(job_id,)).fetchone()
                if not owner or owner[0]!=token: return
                if self._latest(job['submission_id'])!=job['revision']:
                    self.db.execute("UPDATE jobs SET status='superseded',owner_pid=NULL WHERE id=?",(job_id,));return
                for p in valid:
                    if any(self._latest(p[k+'_submission_id'])!=p[k+'_revision'] for k in ('source','destination')): continue
                    claim=claim_identity(p)
                    old = self.db.execute("SELECT 1 FROM proposals WHERE claim_key=? AND json_extract(data,'$.source_revision')=? AND json_extract(data,'$.destination_revision')=? LIMIT 1", (claim,p['source_revision'],p['destination_revision'])).fetchone()
                    if old: continue
                    last=self.db.execute("SELECT h.action FROM review_history h JOIN proposals p ON p.id=h.proposal_id WHERE p.claim_key=? AND h.action!='stale' ORDER BY h.rowid DESC LIMIT 1",(claim,)).fetchone()
                    if last and last['action']=='reject': continue
                    fingerprint=hashlib.sha256((claim+':'+str(p['source_revision'])+':'+str(p['destination_revision'])).encode()).hexdigest()
                    self.db.execute('INSERT OR IGNORE INTO proposals(id,fingerprint,claim_key,data,status,created_at) VALUES (?,?,?,?,?,?)',(new_id(),fingerprint,claim,dumps(p),'proposed',now()))
                self.db.execute("UPDATE jobs SET status='completed',error='',owner_pid=NULL,detail=? WHERE id=?",(dumps(detail),job_id))
        except Exception as error:
            # Keep the failure category and exception class in the job row and diagnostics.
            kind,message=self._failure(error)
            detail.update(error_kind=kind,error_class=type(error).__name__)
            with self.lock,self.db:
                self.db.execute("UPDATE jobs SET status='failed',owner_pid=NULL,error=?,detail=? WHERE id=? AND json_extract(detail,'$.claim_token')=?",(message,dumps(detail),job_id,token))
            if self.diagnostic:
                try: self.diagnostic('knowledge_job_failed',error_category=kind,error_type=type(error).__name__)
                except Exception: pass

    # Set by the server to its lifecycle log (record_event, whose field names these are). Receives an event
    # name, the kind of failure and the exception class: never a payload or an error's text.
    diagnostic = None

    @staticmethod
    def _failure(error):
        """(kind, sentence for jobs.error) for an analysis that raised.

        A provider error is recognised by its shape (server.APIError: the name, with an HTTP status), since
        this module does not import the server. Its text is the application's own wording by that class's
        contract and is shown; no other exception's text is, as it may quote what it failed on.
        """
        if type(error).__name__=='APIError' and isinstance(getattr(error,'status',None),int):
            category=getattr(error,'category',None)
            if category=='quota' or error.status==429:
                return 'provider','The provider rate limit or quota was reached. Check the project limits.'
            if category in ('authentication','permissions','model_access','invalid_configuration') or error.status in (401,403):
                return 'provider','The provider rejected the configured credentials, model or permissions. Check the provider settings.'
            return 'provider','The AI provider did not complete the analysis.'
        if isinstance(error,(OSError,TimeoutError)):
            return 'provider','The AI provider could not be reached.'
        if isinstance(error,ValueError):
            return 'result','The analysis returned a result this app could not use.'
        if isinstance(error,sqlite3.Error):
            return 'internal','The analysis could not be saved in the knowledge store ('+type(error).__name__+').'
        return 'internal','Analysis stopped on an internal error in this app ('+type(error).__name__+').'

    def filed_document_sources(self, process_id):
        """Source IDs of the file passages that the stored revisions of a process already hold.

        A saved excerpt from a removed or parked file may be the only evidence of a part only when it is
        one of these: provenance for a capture that exists, not a new way into company knowledge.
        """
        try: process_id=str(uuid.UUID(process_id))
        except (ValueError,TypeError,AttributeError): return set()
        with self.lock:
            rows=self.db.execute("SELECT DISTINCT json_extract(e.value,'$.id') AS id FROM revisions r, json_each(r.payload,'$.document_evidence') e WHERE r.process_id=?",(process_id,)).fetchall()
        return {row['id'] for row in rows if isinstance(row['id'],str)}

    def can_revise(self, process_id, principal):
        if not principal: return False
        with self.lock:
            # Each revision records its author. The original submitter owns the process.
            row=self.db.execute('SELECT submitter FROM revisions WHERE process_id=? AND revision=1',(process_id,)).fetchone()
            return bool(row and row['submitter'] and row['submitter']==principal)

    def _schedule(self, job_id):
        # Startup and participant status checks can both schedule a pending job.
        with self.lock:
            if not self.scheduling or job_id in self.queued_jobs: return False
            self.queued_jobs.add(job_id)
            try:
                raw_trace.emit("knowledge.job_queued", {"job_id":job_id})
                self.executor.submit(raw_trace.wrap(self._execute),job_id)
            except Exception:
                self.queued_jobs.discard(job_id)
                raise
            return True

    def _execute(self, job_id):
        completed = False
        try:
            raw_trace.emit("knowledge.job_started", {"job_id":job_id})
            self._run(job_id)
            completed = True
        except Exception:
            with self.lock,self.db:
                self.db.execute("UPDATE jobs SET status='failed',owner_pid=NULL,error='The knowledge job could not start. Check local storage.' WHERE id=? AND status IN ('processing','pending')",(job_id,))
        finally:
            with self.lock:
                self.queued_jobs.discard(job_id)
                raw_trace.emit("knowledge.job_returned", {"job_id":job_id, "returned":completed})
                if completed and self.scheduling:
                    row=self.db.execute('SELECT status FROM jobs WHERE id=?',(job_id,)).fetchone()
                    raw_trace.emit("knowledge.job_status_read", {"job_id":job_id, "status":row['status'] if row else None})

    def stop_scheduling(self):
        with self.lock:
            self.scheduling = False

    def close(self):
        self.stop_scheduling()
        self.executor.shutdown(wait=True)
        with self.lock:
            if not self.closed:
                self.closed = True
                self.db.close()
