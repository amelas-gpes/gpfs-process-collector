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
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

RELATIONSHIPS = frozenset(('provides_input_to', 'produces', 'consumes', 'hands_off_to',
                           'requires_approval_from', 'happens_after', 'uses_system',
                           'performed_by', 'variant_of'))
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
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

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
            for row in self.db.execute("SELECT id,owner_pid FROM jobs WHERE status='processing'").fetchall():
                alive=False
                if row['owner_pid']:
                    try:
                        os.kill(row['owner_pid'],0); alive=True
                    except ProcessLookupError: pass
                    except PermissionError: alive=True
                if not alive:
                    self.db.execute("UPDATE jobs SET status='pending',owner_pid=NULL,error='Interrupted before completion; retry available.' WHERE id=?",(row['id'],))
        self.analyzer = analyzer
        self.document_resolver = document_resolver
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='knowledge')
        self.closed = False

    def submit(self, payload, principal=None, document_scope=None):
        if not isinstance(payload, dict):
            raise ValueError('Submission must be an object.')
        try:
            payload = json.loads(dumps(payload))
        except (TypeError, ValueError):
            raise ValueError('Submission must contain JSON data.') from None
        for key in ('submitter', 'principal', 'authenticated_submitter'):
            payload.pop(key, None)
        docs=payload.get('documents')
        if isinstance(docs,dict): docs.pop('scope',None)
        if document_scope is not None:
            document_scope=text(document_scope,500)
            if not document_scope: raise ValueError('Invalid document scope.')
        if len(dumps(payload).encode('utf-8')) > 1_000_000:
            raise ValueError('Submission exceeds the local size limit.')
        context = payload.get('context', {})
        turns = payload.get('turns', [])
        draft = payload.get('draft') or {}
        if not isinstance(context, dict) or not isinstance(turns, list) or not isinstance(draft, dict):
            raise ValueError('Submission requires valid context, turns and draft.')
        if len(turns)>400 or not any(isinstance(t,dict) and t.get('role')=='user' and isinstance(t.get('text'),str) and t['text'].strip() for t in turns):
            raise ValueError('A submission requires at least one participant statement.')
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
        with self.lock, self.db:
            if key:
                prior=self.db.execute('SELECT * FROM submission_keys WHERE key=?',(key,)).fetchone()
                if prior:
                    if prior['digest']!=digest or prior['principal']!=(principal or None):
                        raise ValueError('Submission key was already used for different content.')
                    receipt=json.loads(prior['receipt'])
                    receipt['status_token']=self._status_token(receipt['submission_id'],receipt['revision'])
                    return receipt
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
            if key: self.db.execute('INSERT INTO submission_keys VALUES (?,?,?,?)',(key,digest,principal or None,dumps(receipt)))
        if self.analyzer:
            self.executor.submit(self._run,job_id)
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
        working=payload.get('workflow') or {}
        if not isinstance(working,dict): raise ValueError('Submitted workflow must be an object.')
        source='workflow' if (not submitted_draft or payload.get('draft_stale')) else 'draft'
        draft=working if source=='workflow' else submitted_draft
        steps=draft.get('steps',[]) if isinstance(draft.get('steps',[]),list) else []
        connections=draft.get('connections',[]) if isinstance(draft.get('connections',[]),list) else []
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
        valid_evidence={turn['id'] for turn in payload.get('turns',[]) if turn.get('role')=='user'} | {'context'}
        def validate_evidence(item):
            refs=item.get('evidence_turns',[])
            if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in valid_evidence for ref in refs):
                raise ValueError('Submitted workflow references unknown or non-participant evidence.')
        ids={}
        for step in steps:
            if not isinstance(step,dict): raise ValueError('Invalid submitted step.')
            validate_evidence(step)
            local=text(step.get('id',''),80)
            if not local or local in ids: raise ValueError('Submitted step IDs must be unique.')
            eid=new_id();ids[local]=eid
            label=text(step.get('title','') or 'Untitled step',1000)
            kind='decision' if step.get('type')=='decision' else 'step'
            self.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',(eid,sid,rev,kind,label,dumps({**step,'_materialized_from':source})))
            link(version_entity,eid,'contains',{'step_id':local})
            for field,entity_type,relation in (('actor','role','performed_by'),('system','system','uses_system'),('input','business_object','consumes'),('output','business_object','produces')):
                component(eid,entity_type,step.get(field,''),relation,{'step_id':local,'evidence_turns':step.get('evidence_turns',[])})
        for edge in connections:
            if not isinstance(edge,dict) or edge.get('from') not in ids or edge.get('to') not in ids:
                raise ValueError('Submitted workflow connection references a missing step.')
            validate_evidence(edge)
            self.db.execute('INSERT INTO edges VALUES (?,?,?,?,?,?,?,?)',(new_id(),ids[edge['to']],ids[edge['from']],'happens_after','reported',sid,rev,dumps({**edge,'_materialized_from':source})))

    def _revision(self,sid,revision):
        row=self.db.execute('SELECT * FROM revisions WHERE submission_id=? AND revision=?',(sid,revision)).fetchone()
        if not row: raise ValueError('Submission revision is unavailable.')
        data=json.loads(row['payload'])
        return {**data,'submission_id':sid,'process_id':row['process_id'],'revision':revision,'submitter':row['submitter'],'created_at':row['created_at']}

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
        if p.get('source_revision') != permitted[a]['revision'] or p.get('destination_revision') != permitted[b]['revision']:
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
            if sid not in (a,b) or not source or item.get('revision')!=source['revision']: raise ValueError('Invalid evidence revision.')
            quote=text(item.get('quote',''),6000)
            if not quote: raise ValueError('Evidence needs a nonempty exact quote.')
            kind=item.get('type') or 'employee_reported'
            if kind=='employee_reported':
                tid=text(item.get('turn_id',''),80)
                match=next((t for t in source.get('turns',[]) if t.get('id')==tid and t.get('role')=='user'),None)
                if not match or quote not in match['text']: raise ValueError('Evidence must quote an exact participant statement.')
                evidence={'submission_id':sid,'revision':source['revision'],'turn_id':tid,'quote':quote,'type':kind}
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

    def _proposal(self,row):
        item=json.loads(row['data']); item.update(id=row['id'],status=row['status'],review_version=row['review_version'],created_at=row['created_at'],stale_reason=row['stale_reason'])
        item['history']=[dict(x) for x in self.db.execute('SELECT action,reviewer,reason,side,created_at,review_version FROM review_history WHERE proposal_id=? ORDER BY rowid',(row['id'],))]
        return item

    def review(self,proposal_id,action,reviewer,reason,expected_revision,side=None):
        if action not in ACTIONS or side not in (None,'sender','receiver'): raise ValueError('Unsupported review action.')
        reviewer=text(reviewer,500);reason=text(reason,6000)
        if not reviewer or not reason: raise ValueError('Reviewer and review reason are required.')
        # Commit invalidation separately, so rejecting a stale review cannot roll it back.
        with self.lock,self.db:
            self._invalidate_changed_document_evidence()
        with self.lock,self.db:
            row=self.db.execute('SELECT * FROM proposals WHERE id=?',(proposal_id,)).fetchone()
            if not row: raise ValueError('Proposal not found.')
            if row['status'] in ('stale','superseded'): raise ValueError('Stale proposals require new evidence and review.')
            if type(expected_revision) is not int or expected_revision!=row['review_version']: raise ValueError('Proposal changed; refresh before reviewing.')
            version=row['review_version']+1
            changed=self.db.execute("UPDATE proposals SET status=?,review_version=? WHERE id=? AND review_version=? AND status NOT IN ('stale','superseded')",(ACTIONS[action],version,proposal_id,expected_revision))
            if changed.rowcount!=1: raise ValueError('Proposal changed; refresh before reviewing.')
            self.db.execute('INSERT INTO review_history VALUES (?,?,?,?,?,?,?,?)',(new_id(),proposal_id,action,reviewer,reason,side,now(),version))
            return self._proposal(self.db.execute('SELECT * FROM proposals WHERE id=?',(proposal_id,)).fetchone())

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
        with self.lock,self.db:
            row=self.db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row or row['status'] not in ('failed','pending'): raise ValueError('Job cannot be retried.')
            if not self.analyzer: raise ValueError('Background analysis is not configured.')
            updated=self.db.execute("UPDATE jobs SET status='pending',error='' WHERE id=? AND status IN ('failed','pending')",(job_id,))
            if updated.rowcount!=1: raise ValueError('Job is already processing.')
        self.executor.submit(self._run,job_id)
        return {'id':job_id,'status':'pending'}

    def _canonical(self, row):
        result=dict(row)
        result['members']=[r['entity_id'] for r in self.db.execute('SELECT entity_id FROM canonical_members WHERE canonical_id=? ORDER BY entity_id',(row['id'],))]
        result['aliases']=[r['alias'] for r in self.db.execute('SELECT alias FROM canonical_aliases WHERE canonical_id=? ORDER BY alias',(row['id'],))]
        result['history']=[dict(r) for r in self.db.execute('SELECT action,value,reviewer,reason,review_version,created_at FROM canonical_history WHERE canonical_id=? ORDER BY rowid',(row['id'],))]
        return result

    def canonical_create(self,label,entity_ids,reviewer,reason):
        label=text(label,500);reviewer=text(reviewer,500);reason=text(reason,6000)
        if not label or not reviewer or not reason or not isinstance(entity_ids,list) or not 1<=len(entity_ids)<=100 or any(not isinstance(x,str) or len(x)>100 for x in entity_ids) or len(set(entity_ids))!=len(entity_ids):
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
            return self._canonical(self.db.execute('SELECT * FROM canonical_groups WHERE id=?',(cid,)).fetchone())

    def canonical_update(self,canonical_id,action,value,reviewer,reason,expected_revision):
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
            return self._canonical(self.db.execute('SELECT * FROM canonical_groups WHERE id=?',(canonical_id,)).fetchone())

    def _invalidate_changed_document_evidence(self):
        if not self.document_resolver: return
        rows=self.db.execute("SELECT id,data,review_version FROM proposals WHERE status NOT IN ('stale','superseded')").fetchall()
        for row in rows:
            for evidence in json.loads(row['data']).get('evidence',[]):
                if evidence.get('type')!='document_supported': continue
                try:
                    source=self._document_source(evidence['submission_id'],evidence['revision'],evidence['document_id'],evidence['source_id'])
                    digest=hashlib.sha256(source['text'].encode('utf-8')).hexdigest()
                except Exception:
                    digest=None
                if digest!=evidence.get('source_hash'):
                    reason='Document source changed or became unavailable; evidence requires review.'
                    changed=self.db.execute("UPDATE proposals SET status='stale',stale_reason=?,review_version=review_version+1 WHERE id=? AND review_version=? AND status NOT IN ('stale','superseded')",(reason,row['id'],row['review_version']))
                    if changed.rowcount:
                        self.db.execute('INSERT INTO review_history VALUES (?,?,?,?,?,?,?,?)',(new_id(),row['id'],'stale','system',reason,None,now(),row['review_version']+1))
                    break

    def admin_snapshot(self):
        with self.lock,self.db:
            self._invalidate_changed_document_evidence()
            rows=self.db.execute('SELECT * FROM revisions ORDER BY created_at DESC').fetchall()
            submissions=[]
            for row in rows:
                sub=self._revision(row['submission_id'],row['revision'])
                job=self.db.execute('SELECT status FROM jobs WHERE submission_id=? AND revision=?',(row['submission_id'],row['revision'])).fetchone()
                sub['job_status']=job['status'] if job else 'unknown';submissions.append(sub)
            return {'submissions':submissions,
                    'proposals':[self._proposal(row) for row in self.db.execute('SELECT * FROM proposals ORDER BY created_at DESC')],
                    'entities':[{**dict(r),'data':json.loads(r['data'])} for r in self.db.execute('SELECT * FROM entities')],
                    'edges':[{**dict(r),'evidence':json.loads(r['evidence'])} for r in self.db.execute('SELECT * FROM edges')],
                    'jobs':[dict(r) for r in self.db.execute('SELECT * FROM jobs ORDER BY created_at DESC')], 'canonical_groups':[self._canonical(r) for r in self.db.execute('SELECT * FROM canonical_groups ORDER BY created_at')], 'analysis_limitations':'Analysis uses at most eight candidate submissions and bounded transcript excerpts; it is not exhaustive. Document analysis is limited to two source excerpts per submission; visual transcriptions remain unverified.'}

    def close(self):
        with self.lock: self.closed=True
        self.executor.shutdown(wait=True)
        with self.lock: self.db.close()
