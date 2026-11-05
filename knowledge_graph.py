"""Local, evidence-backed process graph. Authorization belongs at the API boundary.

SQLite stores immutable submission revisions, reported internal topology, proposals,
review decisions and durable jobs. No automatic connection is ever confirmed.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import json
import os
import re
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

RELATIONSHIPS = frozenset(('provides_input_to', 'produces', 'consumes', 'hands_off_to',
                           'requires_approval_from', 'happens_after', 'uses_system',
                           'performed_by', 'variant_of', 'subprocess_of', 'parallel_with', 'shares_calculation_with'))
ACTIONS = {'confirm': 'confirmed', 'reject': 'rejected', 'dispute': 'disputed', 'clarify': 'awaiting_clarification'}

def now():
    return datetime.now(timezone.utc).isoformat()

def new_id():
    return str(uuid.uuid4())

def text(value, limit=1000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Invalid text field.')
    return value.strip()

def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def validated_document_evidence(value, documents, scope):
    """Accept only a server-hydrated catalog, separate from the submitted JSON.

    The HTTP boundary authorizes and reads exact sources from its document store.
    Here we bind those sources to the canonical submission manifest and retain a
    bounded immutable copy for the submitted revision's documentary provenance.
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
    seen, total, result = set(), 0, []
    for source in value:
        if not isinstance(source, dict):
            raise ValueError('Invalid verified document source.')
        identity, document_id = text(source.get('id'), 200), text(source.get('document_id'), 100)
        content = source.get('text')
        checked_text = text(content, 18000)
        if (not re.fullmatch(r'doc_[A-Za-z0-9_]+', identity) or not re.fullmatch(r'doc_[A-Za-z0-9_]+', document_id)
                or not identity.startswith(document_id + '_') or not checked_text or identity in seen or (document_id, identity) not in allowed
                or source.get('retained_only') or source.get('archived') or source.get('disposition') == 'parked'):
            raise ValueError('Document source is unavailable or not authorized for this submission.')
        seen.add(identity)
        total += len(content)
        if total > 600000:
            raise ValueError('Verified document evidence exceeds the submission limit.')
        result.append({'id': identity, 'document_id': document_id, 'name': text(source.get('name', ''), 500),
                       'label': text(source.get('label', ''), 500), 'text': content,
                       'source_kind': 'document', 'participant_confirmed': False, 'owner_review_required': True})
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

class KnowledgeGraph:
    def __init__(self, path, analyzer=None, document_resolver=None):
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink(): raise ValueError('Graph database path cannot be a symlink.')
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.create_function('casefold',1,lambda value: str(value or '').casefold(),deterministic=True)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS revisions(submission_id TEXT NOT NULL, process_id TEXT NOT NULL, revision INTEGER NOT NULL,
          payload TEXT NOT NULL, submitter TEXT, created_at TEXT NOT NULL, PRIMARY KEY(submission_id,revision), UNIQUE(process_id,revision));
        CREATE TABLE IF NOT EXISTS submission_keys(key TEXT PRIMARY KEY, digest TEXT NOT NULL, principal TEXT, receipt TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS private_meta(key TEXT PRIMARY KEY, value BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS status_capabilities(submission_id TEXT NOT NULL, revision INTEGER NOT NULL, token_hash TEXT NOT NULL, PRIMARY KEY(submission_id,revision));
        CREATE TABLE IF NOT EXISTS private_documents(submission_id TEXT NOT NULL, revision INTEGER NOT NULL, scope TEXT NOT NULL, PRIMARY KEY(submission_id,revision));
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, revision INTEGER NOT NULL,
          status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, owner_pid INTEGER,
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
            if 'intent_digest' not in {row['name'] for row in self.db.execute('PRAGMA table_info(submission_keys)')}:
                self.db.execute('ALTER TABLE submission_keys ADD COLUMN intent_digest TEXT')
            self.db.execute('CREATE INDEX IF NOT EXISTS review_history_proposal_idx ON review_history(proposal_id)')
            self.db.execute('CREATE INDEX IF NOT EXISTS canonical_history_group_idx ON canonical_history(canonical_id)')
            self.db.execute('CREATE INDEX IF NOT EXISTS proposals_claim_idx ON proposals(claim_key)')
            self.db.execute('CREATE INDEX IF NOT EXISTS entities_revision_type_idx ON entities(submission_id,revision,type)')
            self.db.execute('CREATE INDEX IF NOT EXISTS edges_endpoints_idx ON edges(source,target)')
            self.db.execute('CREATE INDEX IF NOT EXISTS revisions_order_idx ON revisions(created_at,submission_id,revision)')
            self.db.execute("CREATE INDEX IF NOT EXISTS proposals_source_idx ON proposals(json_extract(data,'$.source_submission_id'),json_extract(data,'$.source_revision'))")
            self.db.execute("CREATE INDEX IF NOT EXISTS proposals_destination_idx ON proposals(json_extract(data,'$.destination_submission_id'),json_extract(data,'$.destination_revision'))")

            for row in self.db.execute("SELECT id,owner_pid FROM jobs WHERE status='processing'").fetchall():
                alive=_process_is_alive(row['owner_pid'])
                if not alive:
                    self.db.execute("UPDATE jobs SET status='pending',owner_pid=NULL,error='Interrupted before completion; retry available.' WHERE id=?",(row['id'],))
        self.analyzer = analyzer
        self.document_resolver = document_resolver
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='knowledge')
        self.closed = False
        self.queued_jobs = set()

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

    def submit(self, payload, principal=None, document_scope=None, intent_digest=None, document_evidence=None):
        intent_digest=self._intent_digest(intent_digest)
        if not isinstance(payload, dict):
            raise ValueError('Submission must be an object.')
        try:
            payload = json.loads(dumps(payload))
        except (TypeError, ValueError):
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
        if catalog: payload['document_evidence']=catalog
        if len(dumps(payload).encode('utf-8')) > 1_000_000:
            raise ValueError('Submission exceeds the local size limit.')
        context = payload.get('context', {})
        turns = payload.get('turns', [])
        draft = payload.get('draft')
        if draft is None: draft = {}
        if not isinstance(context, dict) or not isinstance(turns, list) or not isinstance(draft, dict):
            raise ValueError('Submission requires valid context, turns and draft.')
        if len(turns)>400 or (not catalog and not any(isinstance(t,dict) and t.get('role')=='user' and not t.get('document_event') and isinstance(t.get('text'),str) and t['text'].strip() for t in turns)):
            raise ValueError('A submission requires a participant statement or verified document evidence.')
        seen=set()
        for turn in turns:
            if not isinstance(turn,dict) or turn.get('role') not in ('user','assistant'):
                raise ValueError('Invalid transcript turn.')
            tid=text(turn.get('id'),80)
            if not tid or tid in seen:
                raise ValueError('Transcript turn IDs must be unique.')
            seen.add(tid); text(turn.get('text'),6000)
        for key in ('participant','team','department','scope'):
            payload[key]=text(payload.get(key,'') or '',500)
        key=payload.get('submission_key')
        if key:
            try: key=str(uuid.UUID(key))
            except (ValueError, TypeError, AttributeError): raise ValueError('Invalid submission key.') from None
        digest_payload=dict(payload); digest_payload.pop('saved_at',None)
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
            submission_id=previous['submission_id'] if previous else new_id()
            revision=previous['revision']+1 if previous else 1
            self.db.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?)',(submission_id,process_id,revision,dumps(payload),text(principal,500) if principal else None,now()))
            if document_scope:
                self.db.execute('INSERT INTO private_documents VALUES (?,?,?)',(submission_id,revision,document_scope))
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
            if not hmac.compare_digest(expected,candidate) or not row: raise PermissionError('Submission status unavailable.')
            return {'submission_id':submission_id,'revision':revision,'job_id':row['id'],'status':row['status'],'error':row['error'],'attempts':row['attempts']}

    def _materialize(self, sid, pid, rev, payload):
        submitted_draft=payload.get('draft') or {}
        working=payload.get('workflow')
        if working is None: working={}
        if not isinstance(working,dict): raise ValueError('Submitted workflow must be an object.')
        source='workflow' if (not submitted_draft or payload.get('draft_stale')) else 'draft'
        draft=working if source=='workflow' else submitted_draft
        steps=draft.get('steps',[])
        connections=draft.get('connections',[])
        if not isinstance(steps,list) or not isinstance(connections,list): raise ValueError('Submitted steps and connections must be arrays.')
        if len(steps)>80 or len(connections)>150: raise ValueError('Submitted workflow exceeds graph limits.')
        process_entity=new_id()
        title=(payload.get('context') or {}).get('process_name') or draft.get('title') or 'Untitled process'
        title=text(title,1000)
        self.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',(process_entity,sid,rev,'process',title,dumps({'source':source})))
        version_entity=new_id()
        self.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',(version_entity,sid,rev,'process_version',title+' (revision '+str(rev)+')',dumps({'source':source})))
        def link(source,target,kind,evidence):
            self.db.execute('INSERT INTO edges VALUES (?,?,?,?,?,?,?,?)',(new_id(),source,target,kind,'reported',sid,rev,dumps(evidence)))
        def component(parent,kind,label,relationship,evidence):
            if not isinstance(label,str) or not label.strip() or label.strip().upper() in ('UNKNOWN','N/A','NOT KNOWN'):
                return
            label=text(label,1000); eid=new_id()
            self.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',(eid,sid,rev,kind,label,'{}'))
            link(parent,eid,relationship,evidence)
        link(process_entity,version_entity,'has_version',{})
        for field,kind,relation in (('team','team','performed_by'),('department','team','performed_by'),('scope','scope','applies_to')):
            component(version_entity,kind,payload.get(field,''),relation,{'source':'submission_context','field':field})
        for field,kind,relation in (('inputs','business_object','consumes'),('outputs','business_object','produces')):
            values=draft.get(field,[])
            if isinstance(values,list):
                for value in values[:100]: component(version_entity,kind,value,relation,{'source':source,'field':field})
        document_ids={item['id'] for item in payload.get('document_evidence',[])}
        participant_ids={turn['id'] for turn in payload.get('turns',[]) if turn.get('role')=='user' and not turn.get('document_event')}
        valid_evidence=participant_ids | {'context'} | document_ids
        def validate_evidence(item):
            refs=item.get('evidence_turns',[])
            if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in valid_evidence for ref in refs):
                raise ValueError('Submitted workflow references unknown or non-participant evidence.')
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
            local=text(step.get('id',''),80)
            if not local or local in ids: raise ValueError('Submitted step IDs must be unique.')
            eid=new_id();ids[local]=eid
            label=text(step.get('title','') or 'Untitled step',1000)
            kind='decision' if step.get('type')=='decision' else 'step'
            self.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',(eid,sid,rev,kind,label,dumps({**step,'_materialized_from':source,**provenance(step)})))
            link(version_entity,eid,'contains',{'step_id':local,**provenance(step)})
            for field,entity_type,relation in (('actor','role','performed_by'),('system','system','uses_system'),('input','business_object','consumes'),('output','business_object','produces')):
                component(eid,entity_type,step.get(field,''),relation,{'step_id':local,'evidence_turns':step.get('evidence_turns',[]),**provenance(step)})
        for edge in connections:
            if not isinstance(edge,dict) or edge.get('from') not in ids or edge.get('to') not in ids:
                raise ValueError('Submitted workflow connection references a missing step.')
            validate_evidence(edge)
            self.db.execute('INSERT INTO edges VALUES (?,?,?,?,?,?,?,?)',(new_id(),ids[edge['to']],ids[edge['from']],'happens_after','reported',sid,rev,dumps({**edge,'_materialized_from':source,**provenance(edge)})))

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
        scope=self.document_scope(submission_id,revision,document_id)
        try: result=self.document_resolver(scope,document_id,source_id)
        except (PermissionError, ValueError): raise ValueError('Document source is unavailable.') from None
        if not isinstance(result,dict) or not isinstance(result.get('text'),str):
            raise ValueError('Document source text is unavailable.')
        return result

    def _with_document_excerpts(self, record):
        excerpts=[]
        docs=record.get('documents') or {}
        for doc in (docs.get('documents',[]) if isinstance(docs,dict) else []):
            if not isinstance(doc,dict): continue
            for item in doc.get('sources',[]):
                if not isinstance(item,dict): continue
                try:
                    source=self._document_source(record['submission_id'],record['revision'],doc.get('id',''),item.get('source_id',''))
                except (ValueError,PermissionError): continue
                if source['text'].strip():
                    excerpts.append({'document_id':doc['id'],'source_id':item['source_id'],'label':source.get('label',''),
                                     'text':source['text'][:1200], 'origin':source.get('origin','source_extraction'),
                                     'verified':source.get('verified'),'excerpt_truncated':len(source['text'])>1200})
                if len(excerpts)>=2: break
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
                if quote not in resolved['text']: raise ValueError('Evidence must quote an exact document source.')
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
            if not job or job['status']!='pending' or self.closed: return
            if self._latest(job['submission_id']) != job['revision']:
                self.db.execute("UPDATE jobs SET status='superseded',owner_pid=NULL WHERE id=?",(job_id,));return
            claimed=self.db.execute("UPDATE jobs SET status='processing',attempts=attempts+1,error='',owner_pid=? WHERE id=? AND status='pending'",(os.getpid(),job_id))
            if claimed.rowcount!=1: return
            current=self._revision(job['submission_id'],job['revision'])
            rows=self.db.execute('SELECT submission_id,MAX(revision) AS revision FROM revisions WHERE submission_id!=? GROUP BY submission_id ORDER BY MAX(created_at) DESC LIMIT 30',(job['submission_id'],)).fetchall()
            candidates=[self._revision(row['submission_id'],row['revision']) for row in rows]
            # Explicitly incompatible scopes can never support a proposal. Filter
            # before source resolution and keep the same eight-account bound as
            # the provider adapter, so unneeded files are never read or sent.
            current_scope=current.get('scope','').strip().casefold()
            candidates=[item for item in candidates if not current_scope or not item.get('scope') or item['scope'].strip().casefold()==current_scope][:8]
        try:
            if self.document_resolver:
                current=self._with_document_excerpts(current)
                candidates=[self._with_document_excerpts(item) for item in candidates]
            proposed=self.analyzer(current,candidates) if candidates else []
            if not isinstance(proposed,list) or len(proposed)>100: raise ValueError('Invalid analyzer response.')
            valid=[self._validate_proposal(p,current,candidates) for p in proposed]
            with self.lock,self.db:
                if self._latest(job['submission_id'])!=job['revision']:
                    self.db.execute("UPDATE jobs SET status='superseded',owner_pid=NULL WHERE id=?",(job_id,));return
                for p in valid:
                    if any(self._latest(p[k+'_submission_id'])!=p[k+'_revision'] for k in ('source','destination')): continue
                    identity={k:p[k] for k in ('source_submission_id','destination_submission_id','relationship_type')}
                    identity.update(scope=p['scope'].strip().casefold(),condition=p['condition'].strip().casefold(),evidence=sorted((e['submission_id'],e['type'],e.get('turn_id',''),e.get('document_id',''),e.get('source_id',''),e['quote']) for e in p['evidence']))
                    claim=hashlib.sha256(dumps(identity).encode()).hexdigest()
                    last=self.db.execute("SELECT h.action FROM review_history h JOIN proposals p ON p.id=h.proposal_id WHERE p.claim_key=? AND h.action!='stale' ORDER BY h.rowid DESC LIMIT 1",(claim,)).fetchone()
                    if last and last['action']=='reject': continue
                    fingerprint=hashlib.sha256((claim+':'+str(p['source_revision'])+':'+str(p['destination_revision'])).encode()).hexdigest()
                    self.db.execute('INSERT OR IGNORE INTO proposals(id,fingerprint,claim_key,data,status,created_at) VALUES (?,?,?,?,?,?)',(new_id(),fingerprint,claim,dumps(p),'proposed',now()))
                self.db.execute("UPDATE jobs SET status='completed',error='',owner_pid=NULL WHERE id=?",(job_id,))
        except Exception:
            with self.lock,self.db:
                self.db.execute("UPDATE jobs SET status='failed',owner_pid=NULL,error='Analysis did not complete. Retry when the provider is available.' WHERE id=?",(job_id,))

    def _proposal(self,row,history=None):
        item=json.loads(row['data']); item.update(id=row['id'],status=row['status'],review_version=row['review_version'],created_at=row['created_at'],stale_reason=row['stale_reason'])
        item['history']=history if history is not None else [dict(x) for x in self.db.execute('SELECT action,reviewer,reason,side,created_at,review_version FROM review_history WHERE proposal_id=? ORDER BY rowid',(row['id'],))]
        return item

    def review(self,proposal_id,action,reviewer,reason,expected_revision,side=None,bounded_result=False):
        if action not in ACTIONS or side not in (None,'sender','receiver'): raise ValueError('Unsupported review action.')
        reviewer=text(reviewer,500);reason=text(reason,6000)
        if not reviewer or not reason: raise ValueError('Reviewer and review reason are required.')
        # Commit invalidation separately, so rejecting a stale review cannot roll it back.
        with self.lock,self.db:
            self._invalidate_changed_document_evidence([proposal_id])
        with self.lock,self.db:
            row=self.db.execute('SELECT * FROM proposals WHERE id=?',(proposal_id,)).fetchone()
            if not row: raise ValueError('Proposal not found.')
            if row['status'] in ('stale','superseded'): raise ValueError('Stale proposals require new evidence and review.')
            if type(expected_revision) is not int or expected_revision!=row['review_version']: raise ValueError('Proposal changed; refresh before reviewing.')
            version=row['review_version']+1
            changed=self.db.execute("UPDATE proposals SET status=?,review_version=? WHERE id=? AND review_version=? AND status NOT IN ('stale','superseded')",(ACTIONS[action],version,proposal_id,expected_revision))
            if changed.rowcount!=1: raise ValueError('Proposal changed; refresh before reviewing.')
            self.db.execute('INSERT INTO review_history VALUES (?,?,?,?,?,?,?,?)',(new_id(),proposal_id,action,reviewer,reason,side,now(),version))
            row=self.db.execute('SELECT * FROM proposals WHERE id=?',(proposal_id,)).fetchone()
            if bounded_result:
                return {'id':row['id'],'status':row['status'],'review_version':row['review_version']}
            return self._proposal(row)

    def document_scope(self, submission_id, revision, document_id):
        with self.lock:
            data=self._revision(submission_id,revision)
            docs=data.get('documents') or {}
            items=docs.get('documents',[]) if isinstance(docs,dict) else []
            if not isinstance(items,list) or not any(isinstance(item,dict) and item.get('id')==document_id for item in items):
                raise PermissionError('Document not in submission revision.')
            row=self.db.execute('SELECT scope FROM private_documents WHERE submission_id=? AND revision=?',(submission_id,revision)).fetchone()
            if not row: raise PermissionError('Document source unavailable.')
            return row['scope']

    def can_revise(self, process_id, principal):
        if not principal: return False
        with self.lock:
            row=self.db.execute('SELECT submitter FROM revisions WHERE process_id=? ORDER BY revision DESC LIMIT 1',(process_id,)).fetchone()
            return bool(row and row['submitter'] and row['submitter']==principal)

    def retry(self,job_id):
        with self._write():
            row=self.db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row or row['status'] not in ('failed','pending'): raise ValueError('Job cannot be retried.')
            if not self.analyzer: raise ValueError('Background analysis is not configured.')
            updated=self.db.execute("UPDATE jobs SET status='pending',error='' WHERE id=? AND status IN ('failed','pending')",(job_id,))
            if updated.rowcount!=1: raise ValueError('Job is already processing.')
        self._schedule(job_id)
        return {'id':job_id,'status':'pending'}

    def _schedule(self, job_id):
        # A durable pending job may be retried while it is still waiting behind
        # another analysis. Keep one executor entry per job, including when
        # repeated retry requests arrive before that job can claim its row.
        with self.lock:
            if self.closed or job_id in self.queued_jobs: return False
            self.queued_jobs.add(job_id)
            try: self.executor.submit(self._execute,job_id)
            except Exception:
                self.queued_jobs.discard(job_id)
                raise
            return True

    def _execute(self, job_id):
        try: self._run(job_id)
        finally:
            with self.lock:
                self.queued_jobs.discard(job_id)
                # A retry can arrive after _run records failure but before this
                # wrapper releases its queue slot. Preserve that retry rather
                # than leaving a durable pending job with no scheduled worker.
                if not self.closed:
                    row=self.db.execute('SELECT status FROM jobs WHERE id=?',(job_id,)).fetchone()
                    if row and row['status']=='pending': self._schedule(job_id)

    def _canonical(self, row, members=None, aliases=None, history=None):
        result=dict(row)
        result['members']=members if members is not None else [r['entity_id'] for r in self.db.execute('SELECT entity_id FROM canonical_members WHERE canonical_id=? ORDER BY entity_id',(row['id'],))]
        result['aliases']=aliases if aliases is not None else [r['alias'] for r in self.db.execute('SELECT alias FROM canonical_aliases WHERE canonical_id=? ORDER BY alias',(row['id'],))]
        result['history']=history if history is not None else [dict(r) for r in self.db.execute('SELECT action,value,reviewer,reason,review_version,created_at FROM canonical_history WHERE canonical_id=? ORDER BY rowid',(row['id'],))]
        return result

    def canonical_create(self,label,entity_ids,reviewer,reason,bounded_result=False):
        label=text(label,500);reviewer=text(reviewer,500);reason=text(reason,6000)
        if not label or not reviewer or not reason or not isinstance(entity_ids,list) or not 2<=len(entity_ids)<=100 or any(not isinstance(x,str) or len(x)>100 for x in entity_ids) or len(set(entity_ids))!=len(entity_ids):
            raise ValueError('A label, reviewer, reason and unique entity IDs are required.')
        with self.lock,self.db:
            entities=[]
            for entity_id in entity_ids:
                row=self.db.execute('SELECT id,type,submission_id,revision FROM entities WHERE id=?',(entity_id,)).fetchone()
                if not row: raise ValueError('Entity not found.')
                if self._latest(row['submission_id'])!=row['revision']: raise ValueError('Cannot group an outdated entity revision.')
                entities.append(row)
            kind=entities[0]['type']
            if any(e['type']!=kind for e in entities): raise ValueError('Only entities of the same type may be grouped.')
            cid=new_id();self.db.execute('INSERT INTO canonical_groups(id,label,type,review_version,created_at) VALUES (?,?,?,?,?)',(cid,label,kind,1,now()))
            try:
                for entity_id in entity_ids: self.db.execute('INSERT INTO canonical_members VALUES (?,?)',(cid,entity_id))
            except sqlite3.IntegrityError: raise ValueError('An entity already belongs to a canonical group.') from None
            self.db.execute('INSERT INTO canonical_history VALUES (?,?,?,?,?,?,?,?)',(new_id(),cid,'create',dumps(entity_ids),reviewer,reason,1,now()))
            row=self.db.execute('SELECT * FROM canonical_groups WHERE id=?',(cid,)).fetchone()
            return self._admin_group_meta(row) if bounded_result else self._canonical(row)

    def canonical_update(self,canonical_id,action,value,reviewer,reason,expected_revision,bounded_result=False):
        if action not in ('add_member','remove_member','add_alias','remove_alias','revalidate'): raise ValueError('Unsupported canonical action.')
        value=text(value,1000);reviewer=text(reviewer,500);reason=text(reason,6000)
        if not value or not reviewer or not reason: raise ValueError('Value, reviewer and reason are required.')
        with self.lock,self.db:
            group=self.db.execute('SELECT * FROM canonical_groups WHERE id=?',(canonical_id,)).fetchone()
            if not group: raise ValueError('Canonical group not found.')
            if type(expected_revision) is not int or expected_revision!=group['review_version']: raise ValueError('Canonical group changed; refresh before reviewing.')
            # Compare-and-swap under a SQLite write transaction also protects multiple local processes.
            changed=self.db.execute('UPDATE canonical_groups SET review_version=review_version+1 WHERE id=? AND review_version=?',(canonical_id,expected_revision))
            if changed.rowcount!=1: raise ValueError('Canonical group changed; refresh before reviewing.')
            if action=='add_member':
                entity=self.db.execute('SELECT type,submission_id,revision FROM entities WHERE id=?',(value,)).fetchone()
                if not entity or entity['type']!=group['type']: raise ValueError('Entity must exist and have the same type.')
                if self._latest(entity['submission_id'])!=entity['revision']: raise ValueError('Cannot group an outdated entity revision.')
                try:self.db.execute('INSERT INTO canonical_members VALUES (?,?)',(canonical_id,value))
                except sqlite3.IntegrityError: raise ValueError('Entity already belongs to a canonical group.') from None
            elif action=='remove_member':
                removed=self.db.execute('DELETE FROM canonical_members WHERE canonical_id=? AND entity_id=?',(canonical_id,value))
                if removed.rowcount!=1: raise ValueError('Entity is not in this group.')
            elif action=='add_alias':
                try:self.db.execute('INSERT INTO canonical_aliases VALUES (?,?)',(canonical_id,value))
                except sqlite3.IntegrityError: raise ValueError('Alias is already recorded.') from None
            elif action=='revalidate':
                members=self.db.execute('SELECT e.submission_id,e.revision FROM canonical_members m JOIN entities e ON e.id=m.entity_id WHERE m.canonical_id=?',(canonical_id,)).fetchall()
                if not members or any(self._latest(m['submission_id'])!=m['revision'] for m in members):
                    raise ValueError('Remove outdated members and add current source entities before revalidating.')
                self.db.execute("UPDATE canonical_groups SET status='active',stale_reason='' WHERE id=?",(canonical_id,))
            else:
                removed=self.db.execute('DELETE FROM canonical_aliases WHERE canonical_id=? AND alias=?',(canonical_id,value))
                if removed.rowcount!=1: raise ValueError('Alias is not in this group.')
            version=expected_revision+1
            self.db.execute('INSERT INTO canonical_history VALUES (?,?,?,?,?,?,?,?)',(new_id(),canonical_id,action,value,reviewer,reason,version,now()))
            row=self.db.execute('SELECT * FROM canonical_groups WHERE id=?',(canonical_id,)).fetchone()
            return self._admin_group_meta(row) if bounded_result else self._canonical(row)

    def _invalidate_changed_document_evidence(self,proposal_ids=None):
        if not self.document_resolver: return
        if proposal_ids is not None:
            if not proposal_ids:return
            placeholders=','.join('?'*len(proposal_ids))
            rows=self.db.execute("SELECT id,data,review_version FROM proposals WHERE status NOT IN ('stale','superseded') AND id IN ("+placeholders+")",list(proposal_ids)).fetchall()
        else:
            rows=self.db.execute("SELECT id,data,review_version FROM proposals WHERE status NOT IN ('stale','superseded')").fetchall()
        digests={}
        for row in rows:
            for evidence in json.loads(row['data']).get('evidence',[]):
                if evidence.get('type')!='document_supported': continue
                key=(evidence['submission_id'],evidence['revision'],evidence['document_id'],evidence['source_id'])
                if key not in digests:
                    try:
                        source=self._document_source(*key)
                        digests[key]=hashlib.sha256(source['text'].encode('utf-8')).hexdigest()
                    except Exception:
                        digests[key]=None
                digest=digests[key]
                if digest!=evidence.get('source_hash'):
                    reason='Document source changed or became unavailable; evidence requires review.'
                    changed=self.db.execute("UPDATE proposals SET status='stale',stale_reason=?,review_version=review_version+1 WHERE id=? AND review_version=? AND status NOT IN ('stale','superseded')",(reason,row['id'],row['review_version']))
                    if changed.rowcount:
                        self.db.execute('INSERT INTO review_history VALUES (?,?,?,?,?,?,?,?)',(new_id(),row['id'],'stale','system',reason,None,now(),row['review_version']+1))
                    break

    ADMIN_LIMITATIONS = ('Reported accounts are not operational measurements. Sources are checked when a connection is opened, '
                         'graphed or reviewed. Lists and histories are paged; Refresh restarts pages when records change. '
                         'AI matching uses at most eight compatible candidates and bounded excerpts; it is not exhaustive.')
    _ADMIN_STATES = frozenset(('all','reported','proposed','awaiting_clarification','confirmed','disputed','rejected',
                              'stale','superseded','active','pending','processing','completed','failed','unknown'))

    @staticmethod
    def _admin_uuid(value, name='record'):
        if not isinstance(value,str): raise ValueError('Choose a valid '+name+'.')
        try: return str(uuid.UUID(value))
        except (ValueError,TypeError,AttributeError): raise ValueError('Choose a valid '+name+'.') from None

    @staticmethod
    def _admin_page_args(offset,limit):
        if type(offset) is not int or not 0<=offset<=9223372036854775807 or type(limit) is not int or not 1<=limit<=50:
            raise ValueError('Choose a nonnegative page offset and a page size from 1 to 50.')
        return offset,limit

    @staticmethod
    def _admin_page(offset,limit,total):
        return {'offset':offset,'limit':limit,'total':total,'has_more':offset+limit<total}

    def _admin_filters(self,filters):
        if filters is None: filters={}
        if not isinstance(filters,dict): raise ValueError('Admin filters must be an object.')
        allowed={'team','system','scope','state','freshness','query','type','submission_id','revision','latest_only','exclude_group_id'}
        if set(filters)-allowed: raise ValueError('Unsupported Admin filter.')
        result={}
        for key in ('team','system','scope','query','type'):
            result[key]=text(filters.get(key,''),500)
        result['state']=filters.get('state','all')
        result['freshness']=filters.get('freshness','all')
        if not isinstance(result['state'],str) or result['state'] not in self._ADMIN_STATES:
            raise ValueError('Choose a valid review state.')
        if not isinstance(result['freshness'],str) or result['freshness'] not in ('all','recent','older'):
            raise ValueError('Choose a valid freshness filter.')
        result['latest_only']=filters.get('latest_only',False)
        if type(result['latest_only']) is not bool: raise ValueError('Latest revisions must be a boolean.')
        for key in ('submission_id','exclude_group_id'):
            raw=filters.get(key)
            result[key]=None if raw is None or raw=='' else self._admin_uuid(raw,key.replace('_',' '))
        result['revision']=filters.get('revision')
        if result['revision'] is not None and (type(result['revision']) is not int or not 1<=result['revision']<=9223372036854775807):
            raise ValueError('Choose a valid revision.')
        return result

    @contextmanager
    def _admin_read(self):
        with self.lock:
            if self.closed: raise ValueError('Knowledge storage is closed.')
            savepoint='admin_'+uuid.uuid4().hex
            self.db.execute('SAVEPOINT '+savepoint)
            try:
                yield
            except BaseException:
                self.db.execute('ROLLBACK TO '+savepoint)
                self.db.execute('RELEASE '+savepoint)
                raise
            else:
                self.db.execute('RELEASE '+savepoint)

    def _admin_matching(self,filters,latest=False):
        clauses=[];args=[]
        for key,expression in (('team',"COALESCE(json_extract(r.payload,'$.team'),'')||' '||COALESCE(json_extract(r.payload,'$.department'),'')"),
                               ('scope',"COALESCE(json_extract(r.payload,'$.scope'),'')")):
            if filters[key]:
                clauses.append('instr(casefold('+expression+'),?)>0');args.append(filters[key].casefold())
        if filters['system']:
            clauses.append("EXISTS(SELECT 1 FROM entities fs WHERE fs.submission_id=r.submission_id AND fs.revision=r.revision AND fs.type='system' AND instr(casefold(fs.label),?)>0)")
            args.append(filters['system'].casefold())
        if filters['submission_id']:
            clauses.append('r.submission_id=?');args.append(filters['submission_id'])
        if filters['revision'] is not None:
            clauses.append('r.revision=?');args.append(filters['revision'])
        if latest or filters['latest_only']:
            clauses.append('r.revision=(SELECT MAX(lr.revision) FROM revisions lr WHERE lr.submission_id=r.submission_id)')
        if filters['freshness']!='all':
            # ISO timestamps are emitted in UTC by this module. julianday also
            # supports valid imported offsets and treats unknown dates as older.
            recent="julianday(r.created_at)>=julianday('now','-30 days')"
            clauses.append(recent if filters['freshness']=='recent' else '('+recent+' IS NOT TRUE)')
        where=' AND '.join(clauses) or '1'
        return 'matching AS (SELECT r.submission_id,r.revision FROM revisions r WHERE '+where+')',args

    @staticmethod
    def _admin_submission_select(alias='r'):
        return (alias+".submission_id,"+alias+".process_id,"+alias+".revision,"+alias+".submitter,"+alias+".created_at,"
                "json_extract("+alias+".payload,'$.context.process_name') AS process_name,"
                "json_extract("+alias+".payload,'$.context.process_owner') AS process_owner,"
                "json_extract("+alias+".payload,'$.team') AS team,json_extract("+alias+".payload,'$.department') AS department,"
                "json_extract("+alias+".payload,'$.scope') AS scope")

    @staticmethod
    def _admin_submission_meta(row):
        return {'submission_id':row['submission_id'],'process_id':row['process_id'],'revision':row['revision'],
                'submitter':row['submitter'],'created_at':row['created_at'],
                'context':{'process_name':row['process_name'] or '', 'process_owner':row['process_owner'] or ''},
                'team':row['team'] or '', 'department':row['department'] or '', 'scope':row['scope'] or '',
                **({'job_status':row['job_status'] or 'unknown'} if 'job_status' in row.keys() else {})}

    @staticmethod
    def _admin_entity_select(alias='e'):
        return (alias+".id,"+alias+".submission_id,"+alias+".revision,"+alias+".type,"+alias+".label,"
                "("+alias+".revision=(SELECT MAX(lr.revision) FROM revisions lr WHERE lr.submission_id="+alias+".submission_id)) AS latest,"
                "(SELECT cm.canonical_id FROM canonical_members cm WHERE cm.entity_id="+alias+".id) AS canonical_id")

    @staticmethod
    def _admin_entity_meta(row):
        result=dict(row)
        result['latest']=bool(result.get('latest'))
        return result

    @staticmethod
    def _admin_proposal_meta_select():
        return ("p.id,p.status,p.review_version,p.created_at,p.stale_reason,"
                "json_extract(p.data,'$.source_submission_id') AS source_submission_id,"
                "json_extract(p.data,'$.source_revision') AS source_revision,"
                "json_extract(p.data,'$.destination_submission_id') AS destination_submission_id,"
                "json_extract(p.data,'$.destination_revision') AS destination_revision,"
                "json_extract(p.data,'$.relationship_type') AS relationship_type,"
                "json_extract(p.data,'$.explanation') AS explanation,json_extract(p.data,'$.condition') AS condition,"
                "json_extract(p.data,'$.scope') AS scope,"
                "json_extract(sr.payload,'$.context.process_name') AS source_name,"
                "json_extract(dr.payload,'$.context.process_name') AS destination_name")

    @staticmethod
    def _admin_proposal_joins():
        return (" JOIN revisions sr ON sr.submission_id=json_extract(p.data,'$.source_submission_id') AND sr.revision=json_extract(p.data,'$.source_revision')"
                " JOIN revisions dr ON dr.submission_id=json_extract(p.data,'$.destination_submission_id') AND dr.revision=json_extract(p.data,'$.destination_revision')"
                " JOIN matching sm ON sm.submission_id=sr.submission_id AND sm.revision=sr.revision"
                " JOIN matching dm ON dm.submission_id=dr.submission_id AND dm.revision=dr.revision")

    def _admin_query_parts(self,section,filters):
        cte,args=self._admin_matching(filters)
        clauses=[];extra=[]
        query=filters['query'];kind=filters['type'];state=filters['state']
        if section=='submissions':
            source="revisions r JOIN matching m USING(submission_id,revision) LEFT JOIN jobs j USING(submission_id,revision)"
            select=self._admin_submission_select()+',j.status AS job_status'
            order='r.created_at DESC,r.submission_id,r.revision DESC'
            if query:clauses.append("instr(casefold(COALESCE(json_extract(r.payload,'$.context.process_name'),'')),?)>0");extra.append(query.casefold())
        elif section=='connections':
            source='proposals p'+self._admin_proposal_joins();select=self._admin_proposal_meta_select();order='p.created_at DESC,p.id'
            if state!='all':clauses.append('p.status=?');extra.append(state)
            if query:
                clauses.append("instr(casefold(COALESCE(json_extract(p.data,'$.explanation'),'')||' '||COALESCE(json_extract(p.data,'$.relationship_type'),'')),?)>0");extra.append(query.casefold())
        elif section=='entities':
            source='entities e JOIN matching m USING(submission_id,revision)';select=self._admin_entity_select();order='e.label COLLATE NOCASE,e.id'
            if query:clauses.append('instr(casefold(e.label),?)>0');extra.append(query.casefold())
            if kind:clauses.append('e.type=?');extra.append(kind)
            if state not in ('all','reported'):clauses.append('0')
            if filters['exclude_group_id']:
                clauses.append('NOT EXISTS(SELECT 1 FROM canonical_members em WHERE em.entity_id=e.id AND em.canonical_id=?)');extra.append(filters['exclude_group_id'])
        elif section=='groups':
            source='canonical_groups g'
            select=("g.*,(SELECT COUNT(*) FROM canonical_members cm WHERE cm.canonical_id=g.id) AS member_count,"
                    "(SELECT COUNT(*) FROM canonical_aliases ca WHERE ca.canonical_id=g.id) AS alias_count,"
                    "(SELECT COUNT(*) FROM canonical_history ch WHERE ch.canonical_id=g.id) AS history_count")
            order='g.created_at DESC,g.id'
            constrained=any(filters[k] for k in ('team','system','scope','submission_id')) or filters['revision'] is not None or filters['latest_only'] or filters['freshness']!='all'
            if constrained:clauses.append('EXISTS(SELECT 1 FROM canonical_members cm JOIN entities e ON e.id=cm.entity_id JOIN matching m USING(submission_id,revision) WHERE cm.canonical_id=g.id)')
            if query:clauses.append('instr(casefold(g.label),?)>0');extra.append(query.casefold())
            if kind:clauses.append('g.type=?');extra.append(kind)
            if state!='all':clauses.append('g.status=?');extra.append(state)
        elif section=='jobs':
            source='jobs j JOIN matching m USING(submission_id,revision) JOIN revisions r USING(submission_id,revision)'
            select="j.id,j.submission_id,j.revision,j.status,j.attempts,j.error,j.created_at,json_extract(r.payload,'$.context.process_name') AS process_name"
            order='j.created_at DESC,j.id'
            if state!='all':clauses.append('j.status=?');extra.append(state)
            if query:clauses.append("instr(casefold(COALESCE(json_extract(r.payload,'$.context.process_name'),'')),?)>0");extra.append(query.casefold())
        else: raise ValueError('Choose a valid Admin section.')
        return cte,select,source,' AND '.join(clauses) or '1',order,args+extra

    def _admin_counts(self,filters):
        result={}
        for section,key in (('submissions','submissions'),('connections','connections'),('entities','entities'),('groups','groups'),('jobs','jobs')):
            cte,_,source,where,_,args=self._admin_query_parts(section,filters)
            result[key]=self.db.execute('WITH '+cte+' SELECT COUNT(*) FROM '+source+' WHERE '+where,args).fetchone()[0]
        for state,key in (('proposed','awaiting_review'),('confirmed','confirmed_connections')):
            active=dict(filters);active['state']=state
            cte,_,source,where,_,args=self._admin_query_parts('connections',active)
            result[key]=self.db.execute('WITH '+cte+' SELECT COUNT(*) FROM '+source+' WHERE '+where,args).fetchone()[0]
        active=dict(filters);active['state']='failed'
        cte,_,source,where,_,args=self._admin_query_parts('jobs',active)
        result['processing_failures']=self.db.execute('WITH '+cte+' SELECT COUNT(*) FROM '+source+' WHERE '+where,args).fetchone()[0]
        return result

    def admin_browse(self,section,filters=None,offset=0,limit=25):
        offset,limit=self._admin_page_args(offset,limit);filters=self._admin_filters(filters)
        if section not in ('overview','submissions','connections','entities','groups','jobs'):raise ValueError('Choose a valid Admin section.')
        with self._admin_read():
            if section=='overview':
                counts=self._admin_counts(filters)
                return {'section':section,'items':[],'page':self._admin_page(offset,limit,0),'counts':counts,'analysis_limitations':self.ADMIN_LIMITATIONS}
            cte,select,source,where,order,args=self._admin_query_parts(section,filters)
            # Browsing reports stored states. Resolving sources while filtering
            # by status can move rows between pages and trigger unbounded refill
            # scans; exact detail, graph and review validate selected sources.
            total=self.db.execute('WITH '+cte+' SELECT COUNT(*) FROM '+source+' WHERE '+where,args).fetchone()[0]
            rows=self.db.execute('WITH '+cte+' SELECT '+select+' FROM '+source+' WHERE '+where+' ORDER BY '+order+' LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
            if section=='submissions':items=[self._admin_submission_meta(row) for row in rows]
            elif section=='entities':items=[self._admin_entity_meta(row) for row in rows]
            else:items=[dict(row) for row in rows]
            return {'section':section,'items':items,'page':self._admin_page(offset,limit,total),'counts':self._admin_counts(filters),'analysis_limitations':self.ADMIN_LIMITATIONS}

    def _admin_group_meta(self,row):
        result=dict(row);cid=row['id']
        for key,table in (('member_count','canonical_members'),('alias_count','canonical_aliases'),('history_count','canonical_history')):
            result[key]=self.db.execute('SELECT COUNT(*) FROM '+table+' WHERE canonical_id=?',(cid,)).fetchone()[0]
        result.update(members=[],aliases=[],history=[])
        return result

    def _admin_sources(self,refs):
        result=[]
        for (sid,revision),ids in refs.items():
            row=self.db.execute('SELECT '+self._admin_submission_select()+' FROM revisions r WHERE r.submission_id=? AND r.revision=?',(sid,revision)).fetchone()
            if not row:continue
            item=self._admin_submission_meta(row)
            context=self.db.execute("SELECT json_extract(payload,'$.context') FROM revisions WHERE submission_id=? AND revision=?",(sid,revision)).fetchone()[0]
            context=json.loads(context) if isinstance(context,str) else {}
            item['context'].update({key:context.get(key,'') for key in ('objective','background') if isinstance(context.get(key,''),str)})
            item['turns']=[dict(turn) for turn in self.db.execute("SELECT json_extract(t.value,'$.id') AS id,json_extract(t.value,'$.role') AS role,json_extract(t.value,'$.text') AS text FROM revisions r,json_each(r.payload,'$.turns') t WHERE r.submission_id=? AND r.revision=? AND json_extract(t.value,'$.role')='user' AND NOT COALESCE(json_extract(t.value,'$.document_event'),0)",(sid,revision)) if turn['id'] in ids]
            catalog=self.db.execute("SELECT json_extract(payload,'$.document_evidence') FROM revisions WHERE submission_id=? AND revision=?",(sid,revision)).fetchone()[0]
            if isinstance(catalog,str):
                item['document_evidence']=[source for source in json.loads(catalog) if source.get('id') in ids]
            item['transcript_partial']=True
            result.append(item)
        return result

    def admin_detail(self,kind,id,revision=None):
        id=self._admin_uuid(id);refs={};entity_ids=set()
        if kind not in ('submission','entity','relationship','proposal','group'):raise ValueError('Choose a valid detail kind.')
        if revision is not None and (type(revision) is not int or not 1<=revision<=9223372036854775807):raise ValueError('Choose a submission revision.')
        if kind=='submission' and revision is None:raise ValueError('Choose a submission revision.')
        with self._admin_read():
            if kind=='submission':
                row=self.db.execute('SELECT r.*,j.status AS job_status FROM revisions r LEFT JOIN jobs j USING(submission_id,revision) WHERE r.submission_id=? AND r.revision=?',(id,revision)).fetchone()
                if not row:raise ValueError('Submission revision is unavailable.')
                item=self._submission(row);item['job_status']=row['job_status'] or 'unknown'
                return {'kind':kind,'item':item,'submissions':[item],'entities':[],'edges':[],'proposals':[]}
            elif kind=='entity':
                row=self.db.execute('SELECT * FROM entities WHERE id=?',(id,)).fetchone()
                if not row:raise ValueError('Entity is unavailable.')
                item={**dict(row),'data':json.loads(row['data'])}
                refs[(row['submission_id'],row['revision'])]=set(item['data'].get('evidence_turns',[]))
                entity_ids.add(id)
                item['neighbor_count']=self._admin_related_count('entity_neighbors',id)
            elif kind=='relationship':
                row=self.db.execute('SELECT * FROM edges WHERE id=?',(id,)).fetchone()
                if not row:raise ValueError('Relationship is unavailable.')
                item={**dict(row),'evidence':json.loads(row['evidence'])}
                ids=set(item['evidence'].get('evidence_turns',[]));entity_ids.update((row['source'],row['target']))
                if row['type']=='contains':
                    target=self.db.execute('SELECT data FROM entities WHERE id=?',(row['target'],)).fetchone()
                    if target:ids.update(json.loads(target['data']).get('evidence_turns',[]))
                    # The bounded label references omit step data. Carry the
                    # target's cited IDs on this detail so readers can select
                    # exact supplied excerpts without fetching every entity.
                    item['evidence']['evidence_turns']=sorted(ids)
                refs[(row['submission_id'],row['revision'])]=ids
            elif kind=='proposal':
                self._invalidate_changed_document_evidence([id])
                row=self.db.execute('SELECT * FROM proposals WHERE id=?',(id,)).fetchone()
                if not row:raise ValueError('Connection is unavailable.')
                item=self._proposal(row,[])
                for side in ('source','destination'):
                    refs.setdefault((item[side+'_submission_id'],item[side+'_revision']),set())
                item['history_count']=self.db.execute('SELECT COUNT(*) FROM review_history WHERE proposal_id=?',(id,)).fetchone()[0]
                for evidence in item.get('evidence',[]):
                    pair=(evidence['submission_id'],evidence['revision'])
                    refs.setdefault(pair,set()).add(evidence.get('turn_id',''))
            else:
                row=self.db.execute('SELECT * FROM canonical_groups WHERE id=?',(id,)).fetchone()
                if not row:raise ValueError('Reviewed group is unavailable.')
                item=self._admin_group_meta(row)
            entities=[]
            for eid in entity_ids:
                row=self.db.execute('SELECT '+self._admin_entity_select()+' FROM entities e WHERE e.id=?',(eid,)).fetchone()
                if row:entities.append(self._admin_entity_meta(row))
            return {'kind':kind,'item':item,'submissions':self._admin_sources(refs),'entities':entities,'edges':[],'proposals':[]}

    def _admin_direct_cte(self):
        # "happens_after" stores the inverse claim. Normalize it once for both
        # paged neighbors and the recursive reachability traversal.
        return ("""direct AS (
          SELECT x.id,CASE WHEN x.type='happens_after' THEN x.target ELSE x.source END AS source,
            CASE WHEN x.type='happens_after' THEN x.source ELSE x.target END AS target,
            CASE WHEN x.type='happens_after' THEN 'before' ELSE x.type END AS type,
            x.status,x.submission_id,x.revision,NULL AS proposal_id
          FROM edges x WHERE x.status='reported'
          UNION ALL
          SELECT p.id,CASE WHEN json_extract(p.data,'$.relationship_type')='happens_after' THEN de.id ELSE se.id END,
            CASE WHEN json_extract(p.data,'$.relationship_type')='happens_after' THEN se.id ELSE de.id END,
            CASE WHEN json_extract(p.data,'$.relationship_type')='happens_after' THEN 'before' ELSE json_extract(p.data,'$.relationship_type') END,p.status,
            json_extract(p.data,'$.source_submission_id'),json_extract(p.data,'$.source_revision'),p.id
          FROM proposals p JOIN entities se ON se.type='process_version' AND se.submission_id=json_extract(p.data,'$.source_submission_id') AND se.revision=json_extract(p.data,'$.source_revision')
          JOIN entities de ON de.type='process_version' AND de.submission_id=json_extract(p.data,'$.destination_submission_id') AND de.revision=json_extract(p.data,'$.destination_revision')
          WHERE p.status='confirmed')""")

    def _admin_related_parts(self,kind,id):
        if kind=='entity_neighbors':
            return self._admin_direct_cte(),'direct d JOIN entities se ON se.id=d.source JOIN entities de ON de.id=d.target','d.source=? OR d.target=?',[id,id]
        if kind=='downstream':
            cte=self._admin_direct_cte()+", reachable(node) AS (SELECT ? UNION SELECT d.target FROM direct d JOIN reachable r ON r.node=d.source WHERE d.type IN ('before','provides_input_to','hands_off_to'))"
            return cte,'direct d JOIN entities se ON se.id=d.source JOIN entities de ON de.id=d.target',"d.type IN ('before','provides_input_to','hands_off_to') AND d.source IN (SELECT node FROM reachable)",[id]
        raise ValueError('Choose a valid related view.')

    def _admin_related_count(self,kind,id):
        cte,source,where,args=self._admin_related_parts(kind,id)
        return self.db.execute('WITH RECURSIVE '+cte+' SELECT COUNT(*) FROM '+source+' WHERE '+where,args).fetchone()[0]

    def admin_history(self,kind,id,offset=0,limit=25):
        offset,limit=self._admin_page_args(offset,limit);id=self._admin_uuid(id)
        if kind not in ('proposal','group','group_members','group_aliases','entity_neighbors','downstream'):
            raise ValueError('Choose a valid history or related-record kind.')
        with self._admin_read():
            if kind=='proposal':
                if not self.db.execute('SELECT 1 FROM proposals WHERE id=?',(id,)).fetchone():raise ValueError('Connection is unavailable.')
                table='review_history';where='proposal_id=?';args=[id];select='action,reviewer,reason,side,created_at,review_version';order='rowid'
            elif kind in ('group','group_members','group_aliases'):
                if not self.db.execute('SELECT 1 FROM canonical_groups WHERE id=?',(id,)).fetchone():raise ValueError('Reviewed group is unavailable.')
                if kind=='group':
                    table='canonical_history';where='canonical_id=?';args=[id];select='action,value,reviewer,reason,review_version,created_at';order='rowid'
                elif kind=='group_aliases':
                    table='canonical_aliases';where='canonical_id=?';args=[id];select='alias';order='alias'
                else:
                    table='canonical_members cm JOIN entities e ON e.id=cm.entity_id';where='cm.canonical_id=?';args=[id];select=self._admin_entity_select();order='e.label COLLATE NOCASE,e.id'
            else:
                if not self.db.execute('SELECT 1 FROM entities WHERE id=?',(id,)).fetchone():raise ValueError('Entity is unavailable.')
                cte,source,where,args=self._admin_related_parts(kind,id)
                total=self.db.execute('WITH RECURSIVE '+cte+' SELECT COUNT(*) FROM '+source+' WHERE '+where,args).fetchone()[0]
                items=[dict(row) for row in self.db.execute('WITH RECURSIVE '+cte+' SELECT d.*,se.label AS source_label,de.label AS target_label FROM '+source+' WHERE '+where+' ORDER BY d.source,d.target,d.id LIMIT ? OFFSET ?',args+[limit,offset])]
                return {'kind':kind,'id':id,'items':items,'page':self._admin_page(offset,limit,total),
                        'source_verification':'stored_status',
                        'analysis_limitations':'Connection status reflects the last source check. Open a connection to revalidate its evidence before relying on it.'}
            total=self.db.execute('SELECT COUNT(*) FROM '+table+' WHERE '+where,args).fetchone()[0]
            rows=self.db.execute('SELECT '+select+' FROM '+table+' WHERE '+where+' ORDER BY '+order+' LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
            items=[self._admin_entity_meta(row) for row in rows] if kind=='group_members' else [dict(row) for row in rows]
            return {'kind':kind,'id':id,'items':items,'page':self._admin_page(offset,limit,total)}

    def admin_graph(self,filters=None,level='overview',submission_id=None):
        filters=self._admin_filters(filters)
        if level not in ('overview','steps','all'):raise ValueError('Choose a valid graph level.')
        if submission_id is not None:submission_id=self._admin_uuid(submission_id,'process')
        with self._admin_read():
            cte,args=self._admin_matching(filters,latest=True)
            clauses=[]
            if level=='overview':clauses.append("e.type='process_version'")
            elif level=='steps':clauses.append("e.type IN ('process_version','step','decision')")
            if filters['type']:clauses.append('e.type=?');args.append(filters['type'])
            if filters['query']:clauses.append('instr(casefold(e.label),?)>0');args.append(filters['query'].casefold())
            if submission_id:clauses.append('e.submission_id=?');args.append(submission_id)
            where=' AND '.join(clauses) or '1'
            base='SELECT e.id FROM entities e JOIN matching m USING(submission_id,revision) WHERE '+where
            # For an explicitly selected process, include immediate confirmed
            # process-version endpoints as context without importing their steps.
            neighbors=''
            if submission_id and filters['state'] in ('all','confirmed'):
                neighbors=(" UNION SELECT other.id FROM proposals p JOIN entities mine ON mine.type='process_version' AND mine.submission_id=?"
                           " AND mine.revision=(SELECT MAX(revision) FROM revisions WHERE submission_id=mine.submission_id)"
                           " JOIN entities other ON other.type='process_version' AND ((json_extract(p.data,'$.source_submission_id')=mine.submission_id AND json_extract(p.data,'$.source_revision')=mine.revision AND other.submission_id=json_extract(p.data,'$.destination_submission_id') AND other.revision=json_extract(p.data,'$.destination_revision')) OR (json_extract(p.data,'$.destination_submission_id')=mine.submission_id AND json_extract(p.data,'$.destination_revision')=mine.revision AND other.submission_id=json_extract(p.data,'$.source_submission_id') AND other.revision=json_extract(p.data,'$.source_revision')))"
                           " JOIN matching om ON om.submission_id=other.submission_id AND om.revision=other.revision WHERE p.status='confirmed' AND EXISTS(SELECT 1 FROM base_visible)")
                args.append(submission_id)
            ctes=cte+', base_visible AS ('+base+'), visible AS (SELECT id FROM base_visible'+neighbors+')'
            total=self.db.execute('WITH '+ctes+' SELECT COUNT(*) FROM visible',args).fetchone()[0]
            empty={'entities':[],'edges':[],'proposals':[],'submissions':[],'too_large':False,'counts':{'nodes':total,'connections':0},'message':'','analysis_limitations':self.ADMIN_LIMITATIONS}
            if total>80:
                # Count in SQL without materializing the large view. Zero here
                # would falsely say that an over-limit graph has no routes.
                edge_state=" AND 0" if filters['state'] not in ('all','reported') else ''
                edge_kind=" AND x.type IN ('contains','happens_after')" if level=='steps' else ''
                n_edges=self.db.execute("WITH "+ctes+" SELECT COUNT(*) FROM edges x JOIN visible sv ON sv.id=x.source JOIN visible tv ON tv.id=x.target WHERE x.status='reported'"+edge_state+edge_kind,args).fetchone()[0]
                proposal_state=" AND 0" if filters['state'] not in ('all','confirmed') else ''
                n_proposals=self.db.execute("WITH "+ctes+" SELECT COUNT(*) FROM proposals p JOIN entities se ON se.type='process_version' AND se.submission_id=json_extract(p.data,'$.source_submission_id') AND se.revision=json_extract(p.data,'$.source_revision') JOIN entities de ON de.type='process_version' AND de.submission_id=json_extract(p.data,'$.destination_submission_id') AND de.revision=json_extract(p.data,'$.destination_revision') JOIN visible sv ON sv.id=se.id JOIN visible tv ON tv.id=de.id WHERE p.status='confirmed'"+proposal_state,args).fetchone()[0]
                return {**empty,'too_large':True,'counts':{'nodes':total,'connections':n_edges+n_proposals},'message':'Select a process or refine filters to show a complete graph of at most 80 entities and 150 connections.'}
            ids=[row[0] for row in self.db.execute('WITH '+ctes+' SELECT id FROM visible ORDER BY id LIMIT 80',args)]
            if not ids:return {**empty,'message':'No graph entities match these filters.'}
            placeholders=','.join('?'*len(ids))
            edge_where='x.source IN ('+placeholders+') AND x.target IN ('+placeholders+") AND x.status='reported'"
            if level=='steps':edge_where+=" AND x.type IN ('contains','happens_after')"
            if filters['state'] not in ('all','reported'):edge_where+=' AND 0'
            edge_args=ids+ids
            direct_count=self.db.execute('SELECT COUNT(*) FROM edges x WHERE '+edge_where,edge_args).fetchone()[0]
            proposal_where="p.status='confirmed' AND se.id IN ("+placeholders+') AND de.id IN ('+placeholders+')'
            if filters['state'] not in ('all','confirmed'):proposal_where+=' AND 0'
            proposal_source=("proposals p JOIN entities se ON se.type='process_version' AND se.submission_id=json_extract(p.data,'$.source_submission_id') AND se.revision=json_extract(p.data,'$.source_revision')"
                             " JOIN entities de ON de.type='process_version' AND de.submission_id=json_extract(p.data,'$.destination_submission_id') AND de.revision=json_extract(p.data,'$.destination_revision')")
            proposal_ids=[row[0] for row in self.db.execute('SELECT p.id FROM '+proposal_source+' WHERE '+proposal_where+' LIMIT 151',ids+ids)]
            if direct_count+len(proposal_ids)>150:
                full_count=self.db.execute('SELECT COUNT(*) FROM '+proposal_source+' WHERE '+proposal_where,ids+ids).fetchone()[0]
                return {**empty,'too_large':True,'counts':{'nodes':total,'connections':direct_count+full_count},'message':'Select a process or refine filters to show a complete graph of at most 80 entities and 150 connections.'}
            self._invalidate_changed_document_evidence(proposal_ids)
            entities=[]
            for row in self.db.execute('SELECT e.id,e.submission_id,e.revision,e.type,e.label,json_extract(e.data,\'$.actor\') AS actor,json_extract(e.data,\'$.system\') AS system,json_extract(e.data,\'$.evidence_turns\') AS refs FROM entities e WHERE e.id IN ('+placeholders+') ORDER BY e.submission_id,e.revision,e.rowid',ids):
                entity={key:row[key] for key in ('id','submission_id','revision','type','label')}
                entity['data']={'actor':row['actor'] if isinstance(row['actor'],str) else '', 'system':row['system'] if isinstance(row['system'],str) else '',
                                'evidence_turns':json.loads(row['refs']) if isinstance(row['refs'],str) else []}
                entities.append(entity)
            edges=[{**{key:row[key] for key in ('id','source','target','type','status','submission_id','revision')},
                    'evidence':{'label':row['label'] or '', 'evidence_turns':json.loads(row['refs']) if isinstance(row['refs'],str) else []}}
                   for row in self.db.execute("SELECT x.id,x.source,x.target,x.type,x.status,x.submission_id,x.revision,json_extract(x.evidence,'$.label') AS label,json_extract(x.evidence,'$.evidence_turns') AS refs FROM edges x WHERE "+edge_where+' ORDER BY x.id LIMIT 150',edge_args)]
            # Metadata only: source quotes and history are loaded by detail.
            matching_all='matching AS (SELECT submission_id,revision FROM revisions)'
            proposals=[dict(row) for row in self.db.execute('WITH '+matching_all+' SELECT '+self._admin_proposal_meta_select()+' FROM proposals p'+self._admin_proposal_joins()+' WHERE p.id IN ('+','.join('?'*len(proposal_ids))+") AND p.status='confirmed' ORDER BY p.id",proposal_ids)] if proposal_ids else []
            pairs={(e['submission_id'],e['revision']) for e in entities}
            submissions=[]
            for sid,revision in sorted(pairs):
                row=self.db.execute('SELECT '+self._admin_submission_select()+' FROM revisions r WHERE r.submission_id=? AND r.revision=?',(sid,revision)).fetchone()
                if row:submissions.append(self._admin_submission_meta(row))
            return {**empty,'entities':entities,'edges':edges,'proposals':proposals,'submissions':submissions,'counts':{'nodes':len(entities),'connections':len(edges)+len(proposals)}}

    def admin_snapshot(self):
        with self.lock,self.db:
            self._invalidate_changed_document_evidence()
            rows=self.db.execute('SELECT r.*,j.status AS job_status FROM revisions r LEFT JOIN jobs j ON j.submission_id=r.submission_id AND j.revision=r.revision ORDER BY r.created_at DESC').fetchall()
            submissions=[]
            for row in rows:
                sub=self._submission(row)
                sub['job_status']=row['job_status'] or 'unknown';submissions.append(sub)
            proposal_history={}
            for row in self.db.execute('SELECT proposal_id,action,reviewer,reason,side,created_at,review_version FROM review_history ORDER BY rowid'):
                entry=dict(row);pid=entry.pop('proposal_id');proposal_history.setdefault(pid,[]).append(entry)
            members={};aliases={};canonical_history={}
            for row in self.db.execute('SELECT canonical_id,entity_id FROM canonical_members ORDER BY entity_id'):
                members.setdefault(row['canonical_id'],[]).append(row['entity_id'])
            for row in self.db.execute('SELECT canonical_id,alias FROM canonical_aliases ORDER BY alias'):
                aliases.setdefault(row['canonical_id'],[]).append(row['alias'])
            for row in self.db.execute('SELECT canonical_id,action,value,reviewer,reason,review_version,created_at FROM canonical_history ORDER BY rowid'):
                entry=dict(row);cid=entry.pop('canonical_id');canonical_history.setdefault(cid,[]).append(entry)
            return {'submissions':submissions,
                    'proposals':[self._proposal(row,proposal_history.get(row['id'],[])) for row in self.db.execute('SELECT * FROM proposals ORDER BY created_at DESC')],
                    'entities':[{**dict(r),'data':json.loads(r['data'])} for r in self.db.execute('SELECT * FROM entities')],
                    'edges':[{**dict(r),'evidence':json.loads(r['evidence'])} for r in self.db.execute('SELECT * FROM edges')],
                    'jobs':[dict(r) for r in self.db.execute('SELECT * FROM jobs ORDER BY created_at DESC')], 'canonical_groups':[self._canonical(r,members.get(r['id'],[]),aliases.get(r['id'],[]),canonical_history.get(r['id'],[])) for r in self.db.execute('SELECT * FROM canonical_groups ORDER BY created_at')], 'analysis_limitations':'Analysis uses at most eight compatible candidate submissions and bounded transcript excerpts; it is not exhaustive. Document analysis is limited to two source excerpts per submission; visual transcriptions remain unverified.'}

    def close(self):
        with self.lock: self.closed=True
        self.executor.shutdown(wait=True)
        with self.lock: self.db.close()
