"""Offline SQLite graph tests; injected analyzer, no network or external provider."""
import importlib.util
import tempfile
import time
import unittest
import uuid
import threading
from pathlib import Path

spec=importlib.util.spec_from_file_location('knowledge_graph',Path(__file__).resolve().parents[1]/'knowledge_graph.py')
kg=importlib.util.module_from_spec(spec);spec.loader.exec_module(kg)

def payload(name,statement,scope='Fund A'):
    return {'context':{'process_name':name},'participant':'Participant','team':'Operations','scope':scope,
            'turns':[{'id':'u1','role':'user','text':statement}],
            'draft':{'title':name,'inputs':['Approved NAV'],'outputs':['Statements'],
                     'steps':[{'id':'s1','title':'Start','type':'activity','actor':'Analyst','system':'Ledger','evidence_turns':['u1']},
                              {'id':'s2','title':'Check','type':'decision','actor':'Reviewer','evidence_turns':['u1']}],
                     'connections':[{'from':'s1','to':'s2','evidence_turns':['u1']}]},
            'documents':{'files':[{'name':'example.pdf','id':'ref'}]},'memo_findings':[]}

def proposal(current,candidates):
    other=candidates[0]
    return [{'source_submission_id':other['submission_id'],'source_revision':other['revision'],
             'destination_submission_id':current['submission_id'],'destination_revision':current['revision'],
             'relationship_type':'provides_input_to','scope':'Fund A','condition':'approved',
             'explanation':'Both accounts describe an approved NAV.','inference':'Potential handoff requires review.',
             'missing_evidence':['Timing unclear'],'contradictions':[],
             'evidence':[{'submission_id':other['submission_id'],'revision':other['revision'],'turn_id':'u1','quote':other['turns'][0]['text']},
                         {'submission_id':current['submission_id'],'revision':current['revision'],'turn_id':'u1','quote':current['turns'][0]['text']}]}]

def wait(graph,job):
    for _ in range(300):
        row=next(x for x in graph.admin_snapshot()['jobs'] if x['id']==job)
        if row['status'] not in ('pending','processing'): return row
        time.sleep(.01)
    raise AssertionError('job timed out')

class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'graph.db';self.graph=kg.KnowledgeGraph(self.path,proposal)
    def tearDown(self): self.graph.close();self.temp.cleanup()
    def test_persists_revisions_and_trusted_attribution(self):
        p=payload('Publishing','We publish approved NAV.');p['submitter']='untrusted';first=self.graph.submit(p,principal='verified-user');wait(self.graph,first['job_id'])
        self.assertTrue(self.graph.can_revise(first['process_id'],'verified-user'));self.assertFalse(self.graph.can_revise(first['process_id'],None))
        p['process_id']=first['process_id'];p['turns'][0]['text']='Corrected account.';second=self.graph.submit(p,principal='verified-user');wait(self.graph,second['job_id'])
        self.graph.close();self.graph=kg.KnowledgeGraph(self.path,proposal)
        records=self.graph.admin_snapshot()['submissions'];self.assertEqual(len(records),2);self.assertEqual({r['revision'] for r in records},{1,2});self.assertTrue(all(r['submitter']=='verified-user' for r in records));self.assertTrue(any(r['turns'][0]['text']=='We publish approved NAV.' for r in records))
    def test_proposal_review_stale_and_exact_evidence(self):
        a=self.graph.submit(payload('Publishing','We publish approved NAV.'));wait(self.graph,a['job_id'])
        b=self.graph.submit(payload('Statements','We use approved NAV.'));self.assertEqual(wait(self.graph,b['job_id'])['status'],'completed')
        p=self.graph.admin_snapshot()['proposals'][0];self.assertEqual(p['status'],'proposed')
        p=self.graph.review(p['id'],'confirm','local-owner','Evidence reviewed',p['review_version'],side='sender')
        self.assertEqual(p['status'],'confirmed');self.assertEqual([x['side'] for x in p['history']],['sender'])
        changed=payload('Publishing','Corrected NAV.');changed['process_id']=a['process_id'];self.graph.submit(changed)
        stale=next(x for x in self.graph.admin_snapshot()['proposals'] if x['id']==p['id']);self.assertEqual(stale['status'],'stale')
        with self.assertRaises(ValueError): self.graph.review(p['id'],'confirm','owner','approve',stale['review_version'])
    def test_admin_approval_and_two_side_statements_are_separate_and_stale_on_revision(self):
        def claiming_confirmation(current,candidates):
            items=proposal(current,candidates)
            items[0].update(status='confirmed',history=[{'reviewer':'AI','side':'sender'}],sender_confirmed=True,receiver_confirmed=True)
            return items
        self.graph.analyzer=claiming_confirmation
        first=self.graph.submit(payload('Publishing','We publish approved NAV.'));wait(self.graph,first['job_id'])
        second=self.graph.submit(payload('Statements','We use approved NAV.'));self.assertEqual(wait(self.graph,second['job_id'])['status'],'completed')
        initial=self.graph.admin_snapshot()['proposals'][0]
        self.assertEqual(initial['status'],'proposed');self.assertEqual(initial['history'],[])
        self.assertNotIn('sender_confirmed',initial);self.assertNotIn('receiver_confirmed',initial)
        # Analyzer output is only a proposal; it cannot supply side confirmation.
        admin=self.graph.review(initial['id'],'confirm','admin','Administrator reviewed the evidence',initial['review_version'])
        self.assertEqual(admin['status'],'confirmed');self.assertEqual([(h['reviewer'],h['side']) for h in admin['history']],[('admin',None)])
        sender=self.graph.review(admin['id'],'confirm','admin','Sender Alice confirmed publication',admin['review_version'],side='sender')
        receiver=self.graph.review(sender['id'],'confirm','admin','Receiver Bob confirmed use',sender['review_version'],side='receiver')
        self.assertEqual([(h['reviewer'],h['side'],h['reason']) for h in receiver['history']],
                         [('admin',None,'Administrator reviewed the evidence'),('admin','sender','Sender Alice confirmed publication'),('admin','receiver','Receiver Bob confirmed use')])
        revised=payload('Publishing','Corrected publication account.');revised['process_id']=first['process_id'];new=self.graph.submit(revised);wait(self.graph,new['job_id'])
        old=next(p for p in self.graph.admin_snapshot()['proposals'] if p['id']==initial['id'])
        self.assertEqual(old['status'],'stale');self.assertEqual(old['history'][-1]['action'],'stale')
        with self.assertRaisesRegex(ValueError,'Stale proposals'):
            self.graph.review(old['id'],'confirm','admin','Reuse prior approval',old['review_version'])
    def test_duplicate_key_and_topology(self):
        p=payload('Publishing','We publish NAV.');p['submission_key']=str(uuid.uuid4());r=self.graph.submit(p);same=self.graph.submit(p);self.assertEqual(r,same)
        p['turns'][0]['text']='Changed';self.assertRaises(ValueError,self.graph.submit,p)
        data=self.graph.admin_snapshot();self.assertEqual(len(data['submissions']),1)
        self.assertTrue({'process','process_version','team','system','role','step','decision','business_object','scope'} <= {e['type'] for e in data['entities']})
        nodes={e['id']:e['label'] for e in data['entities']};edge=next(e for e in data['edges'] if e['type']=='happens_after');self.assertEqual((nodes[edge['source']],nodes[edge['target']]),('Check','Start'))
    def test_submissions_materialize_current_workflow_before_review_or_when_draft_stale(self):
        self.graph.analyzer=lambda current,candidates: []
        for has_stale_draft in (False,True):
            p=payload('A','We report two steps.')
            p['workflow']={'title':'Current map','steps':[{'id':'x','title':'Current step','type':'activity','evidence_turns':['u1']}, {'id':'y','title':'Current decision','type':'decision','evidence_turns':['u1']}], 'connections':[{'from':'x','to':'y','evidence_turns':['u1']}]}
            if has_stale_draft:p['draft_stale']=True
            else:p['draft']=None
            r=self.graph.submit(p);wait(self.graph,r['job_id']);snapshot=self.graph.admin_snapshot()
            entities=[e for e in snapshot['entities'] if e['submission_id']==r['submission_id']]
            self.assertEqual({e['label'] for e in entities if e['type'] in ('step','decision')},{'Current step','Current decision'})
            step=next(e for e in entities if e['type']=='step');self.assertEqual(step['data']['_materialized_from'],'workflow');self.assertEqual(step['data']['evidence_turns'],['u1'])
            edge=next(e for e in snapshot['edges'] if e['submission_id']==r['submission_id'] and e['type']=='happens_after');self.assertEqual(edge['evidence']['evidence_turns'],['u1']);self.assertEqual(edge['evidence']['_materialized_from'],'workflow')
    def test_workflow_cannot_cite_invented_or_interviewer_evidence(self):
        p=payload('A','We report two steps.');p['draft']=None
        p['turns'].insert(0,{'id':'a1','role':'assistant','text':'What happens?'})
        for forged in ('missing','a1'):
            p['workflow']={'steps':[{'id':'x','title':'Step','evidence_turns':[forged]}],'connections':[]}
            with self.subTest(forged=forged), self.assertRaisesRegex(ValueError,'non-participant evidence'):
                self.graph.submit(p)
        self.assertEqual(self.graph.admin_snapshot()['submissions'],[])
    def test_invalid_fabricated_evidence_fails_without_proposal(self):
        a=self.graph.submit(payload('A','We send data.'));wait(self.graph,a['job_id'])
        def fake(current,candidates):
            p=proposal(current,candidates);p[0]['evidence'][0]['quote']='Invented';return p
        self.graph.analyzer=fake;b=self.graph.submit(payload('B','We receive data.'));self.assertEqual(wait(self.graph,b['job_id'])['status'],'failed');self.assertEqual(self.graph.admin_snapshot()['proposals'],[])
    def test_different_scope_does_not_connect_similar_names(self):
        a=self.graph.submit(payload('A','We send data.','Fund A'));wait(self.graph,a['job_id'])
        calls=[]
        self.graph.analyzer=lambda current,candidates: calls.append(candidates) or []
        b=self.graph.submit(payload('B','We receive data.','Fund B'));self.assertEqual(wait(self.graph,b['job_id'])['status'],'completed')
        self.assertEqual(calls,[], 'An incompatible scope must not be sent to the analyzer.')
        self.assertEqual(self.graph.admin_snapshot()['proposals'],[])

    def test_nonfinite_json_and_malformed_workflow_cannot_poison_saved_graph(self):
        for invalid in (float('nan'),float('inf'),float('-inf')):
            p=payload('A','We send data.');p['extra']=invalid
            with self.subTest(invalid=invalid),self.assertRaisesRegex(ValueError,'JSON data'):
                self.graph.submit(p)
        for field,value in (('draft',[]),('workflow',[]),('steps',{}),('connections','broken')):
            p=payload('A','We send data.')
            if field in ('steps','connections'):p['draft'][field]=value
            else:p[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.graph.submit(p)
        self.assertEqual(self.graph.admin_snapshot()['submissions'],[])

    def test_file_event_is_not_participant_evidence(self):
        p=payload('A','File received.');p['turns'][0]['document_event']=True
        with self.assertRaisesRegex(ValueError,'participant statement'):self.graph.submit(p)
        p['turns'].append({'id':'u2','role':'user','text':'We send approved NAV.'})
        with self.assertRaisesRegex(ValueError,'non-participant evidence'):self.graph.submit(p)
        p['draft']['steps']=[];p['draft']['connections']=[]
        a=self.graph.submit(p);wait(self.graph,a['job_id'])
        b=self.graph.submit(payload('B','We receive NAV.'))
        self.assertEqual(wait(self.graph,b['job_id'])['status'],'failed')
        self.assertEqual(self.graph.admin_snapshot()['proposals'],[])

    def test_candidate_document_reads_are_scoped_and_bounded_before_analysis(self):
        self.graph.analyzer=None
        expected=set()
        for index in range(12):
            scope='Fund A' if index<8 else 'Fund B'
            p=payload(str(index),'We report an input and output.',scope)
            p['documents']={'documents':[{'id':f'doc{index}','sources':[{'source_id':'s1'}]}]}
            record=self.graph.submit(p,document_scope='private')
            if scope=='Fund A':expected.add(record['submission_id'])
        reads=[];received=[]
        self.graph.document_resolver=lambda scope,doc,source: reads.append(doc) or {'text':'Reference text.'}
        self.graph.analyzer=lambda current,candidates: received.extend(candidates) or []
        result=self.graph.submit(payload('Current','We receive approved data.','fund a'))
        self.assertEqual(wait(self.graph,result['job_id'])['status'],'completed')
        self.assertEqual({item['submission_id'] for item in received},expected)
        self.assertEqual(len(reads),8)
        self.assertFalse(any(doc in reads for doc in ('doc8','doc9','doc10','doc11')))

    def test_repeated_pending_retry_does_not_queue_duplicate_work(self):
        a=self.graph.submit(payload('A','We send NAV.'));wait(self.graph,a['job_id'])
        entered=threading.Event();release=threading.Event()
        def blocked(current,candidates):
            entered.set();release.wait(3);return []
        self.graph.analyzer=blocked
        b=self.graph.submit(payload('B','We receive NAV.'));self.assertTrue(entered.wait(1))
        scheduled=[];original=self.graph.executor.submit
        def count_scheduled(fn,*args):
            scheduled.append(args[0]);return original(fn,*args)
        self.graph.executor.submit=count_scheduled
        try:
            c=self.graph.submit(payload('C','We consume NAV.'))
            for _ in range(30):self.graph.retry(c['job_id'])
            self.assertEqual(scheduled,[c['job_id']])
        finally:release.set()
        self.assertEqual(wait(self.graph,c['job_id'])['attempts'],1)

    def test_shutdown_rejects_new_submissions_and_retries_clearly(self):
        result=self.graph.submit(payload('A','We send NAV.'));wait(self.graph,result['job_id'])
        self.graph.close()
        with self.assertRaisesRegex(ValueError,'closed'):self.graph.submit(payload('B','We receive NAV.'))
        with self.assertRaisesRegex(ValueError,'closed'):self.graph.retry(result['job_id'])

    def test_retry_during_failed_worker_cleanup_is_not_lost(self):
        first=self.graph.submit(payload('A','We send NAV.'));wait(self.graph,first['job_id'])
        self.graph.analyzer=lambda current,candidates: (_ for _ in ()).throw(ValueError('Synthetic failure'))
        failed=threading.Event();release=threading.Event();run=self.graph._run
        def hold_cleanup(job):
            run(job)
            failed.set();release.wait(3)
        self.graph._run=hold_cleanup
        second=self.graph.submit(payload('B','We receive NAV.'));self.assertTrue(failed.wait(1))
        self.assertEqual(wait(self.graph,second['job_id'])['status'],'failed')
        self.graph.analyzer=lambda current,candidates: []
        self.graph.retry(second['job_id']);release.set()
        self.assertEqual(wait(self.graph,second['job_id'])['status'],'completed')

    def test_boolean_revision_cannot_masquerade_as_integer_evidence(self):
        first=self.graph.submit(payload('A','We send NAV.'));wait(self.graph,first['job_id'])
        for field in ('source_revision','evidence_revision'):
            def invalid(current,candidates):
                result=proposal(current,candidates)
                if field=='source_revision':result[0]['source_revision']=True
                else:result[0]['evidence'][0]['revision']=True
                return result
            self.graph.analyzer=invalid
            second=self.graph.submit(payload('B','We receive NAV.'))
            self.assertEqual(wait(self.graph,second['job_id'])['status'],'failed')
        self.assertEqual(self.graph.admin_snapshot()['proposals'],[])

    def test_snapshot_batches_records_and_preserves_history_and_evidence(self):
        records=[]
        for index in range(3):
            record=self.graph.submit(payload(str(index),'We report approved NAV.'))
            wait(self.graph,record['job_id']);records.append(record)
        initial=self.graph.admin_snapshot()
        item=initial['proposals'][0]
        reviewed=self.graph.review(item['id'],'confirm','owner','Exact sources checked',item['review_version'],side='sender')
        systems=[entry for entry in initial['entities'] if entry['type']=='system']
        group=self.graph.canonical_create('Ledger',[systems[0]['id'],systems[1]['id']],'owner','Checked systems')
        group=self.graph.canonical_update(group['id'],'add_alias','GL','owner','Known alias',group['review_version'])
        roles=[entry for entry in initial['entities'] if entry['type']=='role']
        other=self.graph.canonical_create('Analyst',[roles[0]['id']],'owner','Checked role')
        def snapshot_queries():
            statements=[]
            self.graph.db.set_trace_callback(lambda sql:statements.append(sql) if sql.lstrip().upper().startswith('SELECT') else None)
            try:return self.graph.admin_snapshot(),len(statements)
            finally:self.graph.db.set_trace_callback(None)
        before,before_queries=snapshot_queries()
        self.graph.analyzer=None
        for index in range(20):self.graph.submit(payload('Additional '+str(index),'A complete additional account.'))
        after,after_queries=snapshot_queries()
        self.assertEqual(before_queries,10)
        self.assertEqual(after_queries,before_queries,'Snapshot reads must not grow per submission, proposal or canonical group.')
        self.assertEqual(len(after['submissions']),23,'Batching must not truncate saved revisions.')
        self.assertEqual(len(after['jobs']),23)
        self.assertEqual(next(p for p in after['proposals'] if p['id']==reviewed['id']),reviewed)
        self.assertEqual(next(g for g in after['canonical_groups'] if g['id']==group['id']),group)
        self.assertEqual(next(g for g in after['canonical_groups'] if g['id']==other['id']),other)
        self.assertTrue(all(e in after['entities'] for e in before['entities']))
        self.assertTrue(all(e in after['edges'] for e in before['edges']))

    def test_server_intent_recovery_binds_principal_and_handles_concurrent_hydration(self):
        self.graph.analyzer=None
        other=kg.KnowledgeGraph(self.path)
        p=payload('A','We send NAV.');p['submission_key']=str(uuid.uuid4())
        start=threading.Barrier(2);results=[];failures=[]
        def submit_variant(store,label):
            import copy
            variant=copy.deepcopy(p);variant['documents']={'documents':[{'id':'doc1','sources':[{'source_id':label}]}]}
            try:
                start.wait();results.append(store.submit(variant,principal='employee',document_scope='private',intent_digest='a'*64))
            except Exception as error:failures.append(error)
        workers=[threading.Thread(target=submit_variant,args=(store,label)) for store,label in ((self.graph,'before'),(other,'after'))]
        try:
            for worker in workers:worker.start()
            for worker in workers:worker.join(2)
        finally:other.close()
        self.assertEqual(failures,[]);self.assertEqual(len(results),2);self.assertEqual(results[0],results[1])
        self.assertEqual(len(self.graph.admin_snapshot()['submissions']),1)
        self.assertEqual(self.graph.recover_submission(p['submission_key'],'a'*64,principal='employee'),results[0])
        for digest,principal in (('b'*64,'employee'),('a'*64,'other')):
            with self.assertRaisesRegex(ValueError,'different content'):self.graph.recover_submission(p['submission_key'],digest,principal)
            with self.assertRaisesRegex(ValueError,'different content'):self.graph.submit(p,principal=principal,document_scope='private',intent_digest=digest)

    def test_legacy_key_requires_canonical_replay_before_raw_intent_upgrade(self):
        p=payload('A','We send NAV.');p['submission_key']=str(uuid.uuid4())
        original=self.graph.submit(p,principal='employee');wait(self.graph,original['job_id'])
        self.assertIsNone(self.graph.recover_submission(p['submission_key'],'a'*64,'employee'))
        changed=payload('A','Changed participant account.');changed['submission_key']=p['submission_key']
        with self.assertRaisesRegex(ValueError,'different content'):self.graph.submit(changed,principal='employee',intent_digest='a'*64)
        self.assertEqual(self.graph.submit(p,principal='employee',intent_digest='a'*64),original)
        self.assertEqual(self.graph.recover_submission(p['submission_key'],'a'*64,'employee'),original)
        self.assertEqual(self.graph.submit(p,principal='employee'),original,'Direct canonical replay remains supported.')
    def test_shared_system_does_not_create_cross_submission_dependency(self):
        self.graph.analyzer=lambda current,candidates: []
        a=self.graph.submit(payload('A','We send data.'));wait(self.graph,a['job_id'])
        b=self.graph.submit(payload('B','We receive data.'));wait(self.graph,b['job_id'])
        data=self.graph.admin_snapshot();systems=[x for x in data['entities'] if x['type']=='system' and x['label']=='Ledger']
        self.assertEqual(len(systems),2);self.assertNotEqual(systems[0]['id'],systems[1]['id'])
        self.assertEqual(data['proposals'],[])
    def test_parallel_paths_loop_and_variant_are_preserved_in_source_and_graph(self):
        self.graph.analyzer=lambda current,candidates: []
        p=payload('Portfolio approval','For Fund A, reviews run in parallel, then failed checks return to correction.')
        p['draft']['steps']=[
            {'id':'start','title':'Start','type':'activity','evidence_turns':['u1']},
            {'id':'legal','title':'Legal review','type':'activity','evidence_turns':['u1']},
            {'id':'ops','title':'Operations review','type':'activity','evidence_turns':['u1']},
            {'id':'decision','title':'Checks complete?','type':'decision','evidence_turns':['u1']},
            {'id':'correct','title':'Correct issue','type':'activity','evidence_turns':['u1']}]
        p['draft']['connections']=[{'from':a,'to':b,'label':label,'evidence_turns':['u1']} for a,b,label in [
            ('start','legal','Parallel'),('start','ops','Parallel'),('legal','decision','Legal complete'),
            ('ops','decision','Operations complete'),('decision','correct','Failed'),('correct','decision','Retry')]]
        p['draft']['variations']=[{'applies_to':'Fund A','difference':'Both reviews are required','evidence_turns':['u1']}]
        result=self.graph.submit(p);wait(self.graph,result['job_id']);snapshot=self.graph.admin_snapshot()
        stored=next(s for s in snapshot['submissions'] if s['submission_id']==result['submission_id'])
        self.assertEqual(stored['draft']['variations'],p['draft']['variations'])
        nodes={e['id']:e['label'] for e in snapshot['entities'] if e['submission_id']==result['submission_id']}
        reported={(nodes[e['target']],nodes[e['source']],e['evidence']['label']) for e in snapshot['edges'] if e['submission_id']==result['submission_id'] and e['type']=='happens_after'}
        self.assertEqual(reported,{('Start','Legal review','Parallel'),('Start','Operations review','Parallel'),('Legal review','Checks complete?','Legal complete'),('Operations review','Checks complete?','Operations complete'),('Checks complete?','Correct issue','Failed'),('Correct issue','Checks complete?','Retry')})

    def test_conflicting_accounts_remain_separate_through_clarification_and_dispute(self):
        def conflicting(current,candidates):
            result=proposal(current,candidates);result[0]['contradictions']=['Accounts disagree about whether approval precedes publication.'];return result
        self.graph.analyzer=conflicting
        first=self.graph.submit(payload('Publishing','We publish NAV before approval.'));wait(self.graph,first['job_id'])
        second=self.graph.submit(payload('Statements','We use NAV only after approval.'));self.assertEqual(wait(self.graph,second['job_id'])['status'],'completed')
        snapshot=self.graph.admin_snapshot();item=snapshot['proposals'][0]
        self.assertEqual(item['contradictions'],['Accounts disagree about whether approval precedes publication.'])
        self.assertEqual({e['quote'] for e in item['evidence']},{'We publish NAV before approval.','We use NAV only after approval.'})
        clarified=self.graph.review(item['id'],'clarify','owner','Ask each side about approval timing',item['review_version'])
        self.assertEqual(clarified['status'],'awaiting_clarification')
        disputed=self.graph.review(item['id'],'dispute','owner','The accounts still conflict',clarified['review_version'])
        self.assertEqual(disputed['status'],'disputed');self.assertEqual([h['action'] for h in disputed['history']],['clarify','dispute'])
        self.assertEqual({s['turns'][0]['text'] for s in snapshot['submissions']},{'We publish NAV before approval.','We use NAV only after approval.'})
    def test_retry_keeps_rejection_despite_changed_model_explanation(self):
        a=self.graph.submit(payload('A','We send NAV.'));wait(self.graph,a['job_id']);b=self.graph.submit(payload('B','We receive NAV.'));wait(self.graph,b['job_id'])
        p=self.graph.admin_snapshot()['proposals'][0];self.graph.review(p['id'],'reject','owner','Not related',p['review_version'])
        def reword(current,candidates):
            result=proposal(current,candidates);result[0]['explanation']='Different words, same claim';return result
        self.graph.analyzer=reword
        with self.graph.lock,self.graph.db:self.graph.db.execute("UPDATE jobs SET status='failed' WHERE id=?",(b['job_id'],))
        self.graph.retry(b['job_id']);wait(self.graph,b['job_id']);items=self.graph.admin_snapshot()['proposals'];self.assertEqual(len(items),1);self.assertEqual(items[0]['status'],'rejected')
        revised=payload('B','We receive NAV.');revised['process_id']=b['process_id'];again=self.graph.submit(revised);wait(self.graph,again['job_id'])
        items=self.graph.admin_snapshot()['proposals'];self.assertEqual(len(items),1);self.assertEqual(items[0]['status'],'stale')
        self.assertEqual([entry['action'] for entry in items[0]['history']],['reject','stale'])
    def test_document_scope_is_private_and_bounded_to_revision(self):
        p=payload('A','We send data.');p['documents']={'scope':'secret-token','documents':[{'id':'doc-1','name':'reference.pdf'}]}
        r=self.graph.submit(p,document_scope='secret-token');wait(self.graph,r['job_id'])
        self.assertNotIn('secret-token',kg.dumps(self.graph.admin_snapshot()))
        self.assertEqual(self.graph.document_scope(r['submission_id'],1,'doc-1'),'secret-token')
        with self.assertRaises(PermissionError): self.graph.document_scope(r['submission_id'],1,'doc-2')
    def test_document_citation_is_checked_against_exact_source_and_invalidated_on_change(self):
        source={'text':'Approved NAV is published for Fund A.','label':'Page 5','origin':'source_extraction'}
        def resolve(scope,document_id,source_id):
            if (scope,document_id,source_id)!=('private-capability','doc1','page5'):raise PermissionError('unknown')
            return source
        self.graph.document_resolver=resolve
        p=payload('A','We prepare NAV.');p['documents']={'scope':'private-capability','documents':[{'id':'doc1','sources':[{'source_id':'page5','label':'Page 5'}]}]}
        a=self.graph.submit(p,document_scope='private-capability');wait(self.graph,a['job_id'])
        def analyze(current,candidates):
            self.assertNotIn('private-capability',kg.dumps((current,candidates)))
            self.assertEqual(candidates[0]['document_excerpts'][0]['source_id'],'page5')
            result=proposal(current,candidates);result[0]['evidence'][0]={'type':'document_supported','submission_id':candidates[0]['submission_id'],'revision':candidates[0]['revision'],'document_id':'doc1','source_id':'page5','quote':'Approved NAV is published'}
            return result
        self.graph.analyzer=analyze;b=self.graph.submit(payload('B','We receive approved NAV.'));self.assertEqual(wait(self.graph,b['job_id'])['status'],'completed')
        item=self.graph.admin_snapshot()['proposals'][0];self.assertEqual(item['evidence'][0]['type'],'document_supported')
        source['text']='Revised source without the previous quote.'
        with self.assertRaisesRegex(ValueError,'Stale proposals'):
            self.graph.review(item['id'],'confirm','owner','Reviewed',item['review_version'])
        changed=self.graph.admin_snapshot()['proposals'][0];self.assertEqual(changed['status'],'stale');self.assertEqual(changed['history'][-1]['action'],'stale')
    def test_forged_document_quote_or_source_cannot_create_proposals(self):
        self.graph.document_resolver=lambda scope,doc,source:{'text':'Actual document text','label':'Page 5'}
        p=payload('A','We prepare NAV.');p['documents']={'documents':[{'id':'doc1','sources':[{'source_id':'page5'}]}]}
        a=self.graph.submit(p,document_scope='private');wait(self.graph,a['job_id'])
        for source_id,quote in (('missing','Actual document text'),('page5','Invented text')):
            def analyze(current,candidates):
                result=proposal(current,candidates);result[0]['evidence'][0]={'type':'document_supported','submission_id':candidates[0]['submission_id'],'revision':candidates[0]['revision'],'document_id':'doc1','source_id':source_id,'quote':quote};return result
            self.graph.analyzer=analyze;b=self.graph.submit(payload('B','We receive NAV.'));self.assertEqual(wait(self.graph,b['job_id'])['status'],'failed')
        self.assertEqual(self.graph.admin_snapshot()['proposals'],[])
    def test_archived_document_is_not_eligible_evidence(self):
        def archived(scope,document_id,source_id):raise PermissionError('Archived')
        self.graph.document_resolver=archived
        p=payload('A','We send NAV.');p['documents']={'documents':[{'id':'doc1','sources':[{'source_id':'page5'}]}]}
        a=self.graph.submit(p,document_scope='private');wait(self.graph,a['job_id'])
        def analyze(current,candidates):
            result=proposal(current,candidates);result[0]['evidence'][0]={'type':'document_supported','submission_id':candidates[0]['submission_id'],'revision':candidates[0]['revision'],'document_id':'doc1','source_id':'page5','quote':'NAV'};return result
        self.graph.analyzer=analyze;b=self.graph.submit(payload('B','We receive NAV.'));self.assertEqual(wait(self.graph,b['job_id'])['status'],'failed');self.assertEqual(self.graph.admin_snapshot()['proposals'],[])
    def test_second_instance_does_not_reset_a_live_job(self):
        a=self.graph.submit(payload('A','We send NAV.'));wait(self.graph,a['job_id'])
        started=threading.Event();release=threading.Event()
        def blocked(current,candidates):
            started.set();release.wait(2);return []
        self.graph.analyzer=blocked;b=self.graph.submit(payload('B','We receive NAV.'))
        self.assertTrue(started.wait(1))
        other=kg.KnowledgeGraph(self.path,blocked)
        try:
            job=next(j for j in other.admin_snapshot()['jobs'] if j['id']==b['job_id'])
            self.assertEqual(job['status'],'processing')
            with self.assertRaises(ValueError):other.retry(b['job_id'])
        finally:
            release.set();other.close()
        self.assertEqual(wait(self.graph,b['job_id'])['status'],'completed')
    def test_admin_canonical_alias_and_reversible_unmerge_preserve_sources(self):
        self.graph.analyzer=lambda current,candidates: []
        a=self.graph.submit(payload('A','We send NAV.'));wait(self.graph,a['job_id'])
        b=self.graph.submit(payload('B','We receive NAV.'));wait(self.graph,b['job_id'])
        systems=[e for e in self.graph.admin_snapshot()['entities'] if e['type']=='system' and e['label']=='Ledger']
        ids=[e['id'] for e in systems];group=self.graph.canonical_create('Shared ledger',ids,'local-owner','Reviewed both sources')
        group=self.graph.canonical_update(group['id'],'add_alias','GL','local-owner','Known alias',group['review_version'])
        self.assertEqual(group['aliases'],['GL'])
        stale_version=group['review_version'];group=self.graph.canonical_update(group['id'],'remove_member',ids[1],'local-owner','Incorrect match',stale_version)
        self.assertEqual(group['members'],[ids[0]])
        with self.assertRaises(ValueError): self.graph.canonical_update(group['id'],'add_member',ids[1],'local-owner','Stale edit',stale_version)
        self.assertEqual(len([e for e in self.graph.admin_snapshot()['entities'] if e['id'] in ids]),2)
        self.assertEqual([h['action'] for h in group['history']],['create','add_alias','remove_member'])
    def test_canonical_revision_stales_membership_until_explicit_revalidation(self):
        self.graph.analyzer=lambda current,candidates: []
        p=payload('A','We send NAV.');a=self.graph.submit(p);wait(self.graph,a['job_id'])
        first=next(e for e in self.graph.admin_snapshot()['entities'] if e['submission_id']==a['submission_id'] and e['type']=='system')
        group=self.graph.canonical_create('Ledger',[first['id']],'owner','Identified system')
        p['process_id']=a['process_id'];second=self.graph.submit(p);wait(self.graph,second['job_id'])
        data=self.graph.admin_snapshot();stale=data['canonical_groups'][0]
        self.assertEqual(stale['status'],'stale');self.assertEqual(stale['members'],[first['id']]);self.assertEqual(stale['history'][-1]['action'],'stale')
        with self.assertRaisesRegex(ValueError,'outdated members'):
            self.graph.canonical_update(stale['id'],'revalidate','reviewed','owner','Recheck',stale['review_version'])
        stale=self.graph.canonical_update(stale['id'],'remove_member',first['id'],'owner','Replaced old revision',stale['review_version'])
        current=next(e for e in data['entities'] if e['submission_id']==a['submission_id'] and e['revision']==2 and e['type']=='system')
        stale=self.graph.canonical_update(stale['id'],'add_member',current['id'],'owner','Checked revised source',stale['review_version'])
        current_group=self.graph.canonical_update(stale['id'],'revalidate','reviewed','owner','Confirmed mapping',stale['review_version'])
        self.assertEqual(current_group['status'],'active');self.assertEqual(current_group['members'],[current['id']])
    def test_status_capability_is_scoped_private_and_recoverable_by_idempotent_retry(self):
        p=payload('A','We send NAV.');p['submission_key']=str(uuid.uuid4());r=self.graph.submit(p);wait(self.graph,r['job_id'])
        self.assertEqual(self.graph.status(r['submission_id'],r['revision'],r['status_token'])['status'],'completed')
        with self.assertRaises(PermissionError):self.graph.status(r['submission_id'],r['revision'],'wrong')
        with self.assertRaises(PermissionError):self.graph.status(r['submission_id'],r['revision']+1,r['status_token'])
        self.assertNotIn(r['status_token'],kg.dumps(self.graph.admin_snapshot()))
        self.assertEqual(self.graph.submit(p)['status_token'],r['status_token'])
        self.graph.close();self.graph=kg.KnowledgeGraph(self.path,proposal)
        self.assertEqual(self.graph.submit(p)['status_token'],r['status_token'])
        self.assertEqual(self.graph.status(r['submission_id'],1,r['status_token'])['status'],'completed')

if __name__=='__main__':unittest.main()
