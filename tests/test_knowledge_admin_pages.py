"""Offline coverage for bounded Admin reads; only temporary synthetic records."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('knowledge_graph',Path(__file__).resolve().parents[1]/'knowledge_graph.py')
kg=importlib.util.module_from_spec(spec);spec.loader.exec_module(kg)


def payload(name='Invoice approval',team='Operations',system='Ledger',scope='Fund A',turns=3):
    return {'context':{'process_name':name,'process_owner':'Controller','objective':'Pay approved invoices',
                       'background':'Invoices arrive from suppliers.'},'participant':'Synthetic participant',
            'team':team,'scope':scope,
            'turns':[{'id':'u'+str(i),'role':'user','text':'We approve the invoice. '+('Detailed statement. '*100)} for i in range(turns)]
                    +[{'id':'a1','role':'assistant','text':'Who approves?'},
                      {'id':'file1','role':'user','text':'File received.','document_event':True}],
            'draft':{'title':name,'inputs':['Supplier invoice'],'outputs':['Approved payment'],
                     'steps':[{'id':'s1','title':'Review invoice','actor':'Analyst','system':system,
                               'input':'Supplier invoice','output':'Validated invoice','completion':'Checks pass',
                               'handoff':'Reviewer receives the invoice','description':'Full retained step details',
                               'evidence_turns':['u0']},
                              {'id':'s2','title':'Approve invoice','type':'decision','actor':'Controller',
                               'evidence_turns':['u1']}],
                     'connections':[{'from':'s1','to':'s2','label':'Validated','evidence_turns':['u0','u1']}]}}


class AdminPagesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.graph=kg.KnowledgeGraph(Path(self.temp.name)/'graph.db')

    def tearDown(self):
        self.graph.close();self.temp.cleanup()

    def submit(self,value=None):
        return self.graph.submit(value or payload(),principal='synthetic-owner',document_scope='synthetic-documents')

    def proposal(self,a,b,status='confirmed',document=False):
        evidence=[{'submission_id':r['submission_id'],'revision':r['revision'],'turn_id':'u0',
                   'quote':'We approve the invoice.','type':'employee_reported'} for r in (a,b)]
        if document:
            evidence[0]={'submission_id':a['submission_id'],'revision':a['revision'],'type':'document_supported',
                         'document_id':'doc1','source_id':'page1','quote':'Original source',
                         'source_hash':hashlib.sha256(b'Original source').hexdigest()}
        data={'source_submission_id':a['submission_id'],'source_revision':a['revision'],
              'destination_submission_id':b['submission_id'],'destination_revision':b['revision'],
              'relationship_type':'provides_input_to','scope':'Fund A','condition':'Approved',
              'explanation':'The two accounts describe a handoff.','inference':'A reviewed handoff.',
              'evidence':evidence,'contradictions':[],'missing_evidence':[]}
        pid=str(uuid.uuid4())
        with self.graph.db:
            self.graph.db.execute('INSERT INTO proposals(id,fingerprint,data,status,created_at) VALUES (?,?,?,?,?)',
                                  (pid,pid,kg.dumps(data),status,kg.now()))
        return pid

    def entity(self,receipt,kind='process_version'):
        return self.graph.db.execute('SELECT id FROM entities WHERE submission_id=? AND revision=? AND type=?',
                                     (receipt['submission_id'],receipt['revision'],kind)).fetchone()[0]

    def pages(self,section,filters=None,limit=17):
        items=[];offset=0
        while True:
            page=self.graph.admin_browse(section,filters,offset,limit)
            self.assertLessEqual(len(page['items']),limit)
            items.extend(page['items'])
            if not page['page']['has_more']:return items,page
            offset+=limit

    def related_pages(self,kind,id,limit=17):
        items=[];offset=0
        while True:
            page=self.graph.admin_history(kind,id,offset,limit)
            self.assertLessEqual(len(page['items']),limit);items.extend(page['items'])
            if not page['page']['has_more']:return items,page
            offset+=limit

    def test_submission_pages_bound_metadata_and_retain_every_long_account(self):
        receipts=[self.submit(payload('Process '+str(i),turns=30)) for i in range(107)]
        traces=[];self.graph.db.set_trace_callback(traces.append)
        with patch.object(self.graph,'admin_snapshot',side_effect=AssertionError('Unbounded snapshot used')):
            first=self.graph.admin_browse('submissions',{},0,10)
            items,last=self.pages('submissions')
        self.graph.db.set_trace_callback(None)
        self.assertEqual(first['page'],{'offset':0,'limit':10,'total':107,'has_more':True})
        self.assertLess(len(kg.dumps(first)),15_000)
        self.assertEqual({x['submission_id'] for x in items},{x['submission_id'] for x in receipts})
        self.assertEqual(len(items),107);self.assertFalse(last['page']['has_more'])
        self.assertTrue(all('turns' not in x and 'draft' not in x for x in items))
        self.assertTrue(all(set(x['context'])=={'process_name','process_owner'} for x in items))
        self.assertTrue(any('LIMIT 10 OFFSET 0' in sql for sql in traces))
        self.assertFalse(any('SELECT r.*' in sql or 'SELECT payload' in sql for sql in traces))

    def test_full_submission_and_exact_source_excerpts_are_loaded_on_demand(self):
        receipt=self.submit(payload(turns=60));eid=self.entity(receipt,'step')
        detail=self.graph.admin_detail('entity',eid)
        self.assertEqual(detail['item']['data']['completion'],'Checks pass')
        self.assertEqual(detail['item']['data']['handoff'],'Reviewer receives the invoice')
        self.assertEqual([t['id'] for t in detail['submissions'][0]['turns']],['u0'])
        self.assertTrue(detail['submissions'][0]['transcript_partial'])
        self.assertEqual(detail['submissions'][0]['context']['background'],'Invoices arrive from suppliers.')
        self.assertNotIn('draft',detail['submissions'][0])
        complete=self.graph.admin_detail('submission',receipt['submission_id'],1)['item']
        self.assertEqual(len(complete['turns']),62)
        self.assertEqual(complete['draft']['steps'][0]['description'],'Full retained step details')
        self.assertEqual(complete['turns'][-1]['id'],'file1')
        self.assertNotIn('transcript_partial',complete)

    def test_filters_use_literal_unicode_substrings_and_match_system_at_same_revision(self):
        original=payload('Äquity %_ process','Straße %_ team','Système %_','Scope %_')
        a=self.submit(original)
        revised=payload('Updated','Other team','Other system','Other scope');revised['process_id']=a['process_id']
        self.submit(revised)
        self.submit(payload('Decoy','Strasse X team','Système X','Scope X'))
        filters={'team':'STRASSE %_','system':'SYSTÈME %_','scope':'SCOPE %_'}
        items,_=self.pages('submissions',filters,1)
        self.assertEqual([(x['submission_id'],x['revision']) for x in items],[(a['submission_id'],1)])
        self.assertEqual(self.graph.admin_browse('submissions',dict(filters,latest_only=True))['items'],[])
        self.assertEqual(self.graph.admin_browse('submissions',{'team':'Other team','system':'Système %_'})['items'],[])
        self.assertEqual(self.graph.admin_browse('submissions',{'query':'ÄQUITY %_'})['page']['total'],1)
        entity=self.graph.admin_browse('entities',dict(filters,type='system',query='%_'))['items'][0]
        self.assertFalse(entity['latest'])
        self.assertEqual(entity['label'],'Système %_')

    def test_freshness_submission_revision_and_job_filters_page_consistently(self):
        old=self.submit(payload('Old'));recent=self.submit(payload('Recent'))
        with self.graph.db:
            self.graph.db.execute("UPDATE revisions SET created_at='2020-01-01T00:00:00+00:00' WHERE submission_id=?",(old['submission_id'],))
            self.graph.db.execute("UPDATE jobs SET status='failed',error='Synthetic failure' WHERE id=?",(old['job_id'],))
        self.assertEqual(self.graph.admin_browse('submissions',{'freshness':'older'})['items'][0]['submission_id'],old['submission_id'])
        self.assertEqual(self.graph.admin_browse('submissions',{'freshness':'recent'})['items'][0]['submission_id'],recent['submission_id'])
        self.assertEqual(self.graph.admin_browse('jobs',{'state':'failed'})['page']['total'],1)
        self.assertEqual(self.graph.admin_browse('overview',{})['counts']['processing_failures'],1)
        self.assertEqual(self.graph.admin_browse('entities',{'submission_id':old['submission_id'],'revision':2})['page']['total'],0)

    def test_inferred_process_name_survives_admin_browsing_search_and_detail(self):
        record=payload()
        record['context']['process_name']=''
        record.update(derived_process_title='Quarterly invoice approval',process_name_manual=False)
        receipt=self.submit(record)
        sid=receipt['submission_id']
        for section in ('submissions','jobs'):
            row=self.graph.admin_browse(section,{'query':'QUARTERLY INVOICE'})['items'][0]
            self.assertEqual(row['submission_id'],sid)
            self.assertEqual(row.get('display_name') or row.get('process_name'),'Quarterly invoice approval')
        item=self.graph.admin_detail('submission',sid,1)['item']
        self.assertEqual(item['display_name'],'Quarterly invoice approval')
        self.assertEqual(item['context']['process_name'],'')
        source=self.graph.admin_detail('entity',self.entity(receipt,'step'))['submissions'][0]
        self.assertEqual(source['display_name'],item['display_name'])
        other=self.submit(payload('Manual title'))
        self.proposal(receipt,other)
        connection=self.graph.admin_browse('connections')['items'][0]
        self.assertEqual((connection['source_name'],connection['destination_name']),
                         ('Quarterly invoice approval','Manual title'))
        legacy=payload()
        legacy['context']['process_name']=''
        legacy['draft']['title']='Legacy map title'
        self.submit(legacy)
        self.assertEqual(self.graph.admin_browse('submissions',{'query':'Legacy map'})['items'][0]['display_name'],'Legacy map title')

    def test_connection_filter_applies_to_exact_endpoint_revisions(self):
        a=self.submit(payload('Sender','Match','Old system'));b=self.submit(payload('Receiver','Match','Old system'))
        pid=self.proposal(a,b)
        changed=payload('New sender','Different','New system');changed['process_id']=a['process_id'];self.submit(changed)
        page=self.graph.admin_browse('connections',{'team':'Match','system':'Old system','state':'stale'},0,1)
        self.assertEqual(page['page']['total'],1);self.assertEqual(page['items'][0]['id'],pid)
        self.assertNotIn('evidence',page['items'][0]);self.assertNotIn('history',page['items'][0])
        self.assertEqual(page['items'][0]['source_name'],'Sender')
        self.assertEqual(self.graph.admin_browse('connections',{'system':'New system'})['page']['total'],0)

    def test_canonical_members_aliases_and_histories_are_complete_bounded_pages(self):
        receipts=[self.submit(payload('Process '+str(i))) for i in range(104)]
        ids=[self.entity(r,'system') for r in receipts]
        group=self.graph.canonical_create('Shared ledger',ids[:100],'owner','Sources reviewed',bounded_result=True)
        self.assertEqual(group['member_count'],100);self.assertEqual(group['members'],[])
        for i in range(74):
            group=self.graph.canonical_update(group['id'],'add_alias','Alias '+str(i),'owner','Reviewed alias',group['review_version'],bounded_result=True)
        members,page=self.related_pages('group_members',group['id'])
        self.assertEqual({x['id'] for x in members},set(ids[:100]));self.assertEqual(page['page']['total'],100)
        aliases,_=self.related_pages('group_aliases',group['id']);self.assertEqual(len(aliases),74)
        history,_=self.related_pages('group',group['id']);self.assertEqual(len(history),75)
        detail=self.graph.admin_detail('group',group['id'])['item']
        self.assertEqual((detail['member_count'],detail['alias_count'],detail['history_count']),(100,74,75))
        self.assertEqual((detail['members'],detail['aliases'],detail['history']),([],[],[]))
        choices=self.graph.admin_browse('entities',{'type':'system','latest_only':True,'exclude_group_id':group['id']})
        self.assertEqual({x['id'] for x in choices['items']},set(ids[100:]))
        self.assertTrue(all(x['canonical_id']==group['id'] and x['latest'] for x in members))
        self.assertEqual(self.graph.admin_browse('groups',{'team':'Operations','system':'Ledger','scope':'Fund A'})['page']['total'],1)
        self.assertEqual(self.graph.admin_browse('groups',{'system':'Missing'})['page']['total'],0)

    def test_long_proposal_history_is_lazy_and_mutation_result_is_bounded(self):
        a=self.submit();b=self.submit(payload('Receiver'));pid=self.proposal(a,b,'proposed')
        with self.graph.db:
            self.graph.db.executemany('INSERT INTO review_history VALUES (?,?,?,?,?,?,?,?)',
                [(str(uuid.uuid4()),pid,'clarify','owner','Review detail '*300,None,kg.now(),i+1) for i in range(703)])
        with patch.object(self.graph,'admin_snapshot',side_effect=AssertionError('Unbounded snapshot used')):
            detail=self.graph.admin_detail('proposal',pid)
            result=self.graph.review(pid,'confirm','owner','Evidence reviewed',1,bounded_result=True)
            history,last=self.related_pages('proposal',pid,23)
        self.assertEqual(detail['item']['history'],[]);self.assertEqual(detail['item']['history_count'],703)
        self.assertEqual(set(result),{'id','status','review_version'})
        self.assertEqual(len(history),704);self.assertEqual(last['page']['total'],704)
        self.assertEqual(history[0]['action'],'confirm')
        self.assertEqual([x['turns'][0]['id'] for x in detail['submissions']],['u0','u0'])

    def test_internal_relationship_detail_keeps_route_condition_and_cited_answers(self):
        receipt=self.submit();graph=self.graph.admin_graph({},'steps',receipt['submission_id'])
        route=next(x for x in graph['edges'] if x['type']=='happens_after')
        detail=self.graph.admin_detail('relationship',route['id'])
        self.assertEqual(detail['item']['evidence']['label'],'Validated')
        self.assertEqual({x['id'] for x in detail['entities']},{route['source'],route['target']})
        self.assertEqual({x['id'] for x in detail['submissions'][0]['turns']},{'u0','u1'})
        containment=next(x for x in graph['edges'] if x['type']=='contains')
        detail=self.graph.admin_detail('relationship',containment['id'])
        self.assertEqual(len(detail['submissions'][0]['turns']),1)
        self.assertEqual(detail['item']['evidence']['evidence_turns'],[detail['submissions'][0]['turns'][0]['id']])

    def test_large_company_graph_is_explicitly_refused_and_selected_process_is_complete(self):
        receipts=[self.submit(payload('Process '+str(i))) for i in range(83)]
        graph=self.graph.admin_graph({},'overview')
        self.assertTrue(graph['too_large']);self.assertEqual(graph['counts']['nodes'],83)
        self.assertEqual(graph['entities'],[]);self.assertIn('Select a process',graph['message'])
        selected=self.graph.admin_graph({},'steps',receipts[0]['submission_id'])
        self.assertFalse(selected['too_large']);self.assertEqual(selected['counts'],{'nodes':3,'connections':3})
        self.assertEqual({x['type'] for x in selected['edges']},{'contains','happens_after'})
        self.assertTrue(all('draft' not in x and 'turns' not in x for x in selected['submissions']))
        self.assertTrue(all('description' not in x['data'] and 'input' not in x['data'] for x in selected['entities']))

    def test_graph_routes_are_never_silently_truncated_at_connection_limit(self):
        p=payload();p['draft']['steps']=[{'id':'s'+str(i),'title':'Step '+str(i),'evidence_turns':['u0']} for i in range(20)]
        p['draft']['connections']=[{'from':'s'+str(i//20),'to':'s'+str(i%20),'evidence_turns':['u0']} for i in range(150)]
        receipt=self.submit(p);graph=self.graph.admin_graph({},'steps',receipt['submission_id'])
        self.assertFalse(graph['too_large'])
        self.assertEqual(graph['counts'],{'nodes':20,'connections':150})
        self.assertTrue(all(x['type']=='happens_after' for x in graph['edges']))

    def test_selected_graph_preserves_confirmed_cross_process_context_without_importing_other_steps(self):
        a=self.submit(payload('Sender'));b=self.submit(payload('Receiver'));pid=self.proposal(a,b)
        graph=self.graph.admin_graph({},'steps',a['submission_id'])
        self.assertEqual(len(graph['entities']),4)
        self.assertEqual([x['id'] for x in graph['proposals']],[pid])
        self.assertEqual({x['submission_id'] for x in graph['submissions']},{a['submission_id'],b['submission_id']})
        self.assertEqual(len([x for x in graph['entities'] if x['submission_id']==b['submission_id']]),1)
        self.assertNotIn('evidence',graph['proposals'][0]);self.assertNotIn('history',graph['proposals'][0])
        self.assertEqual(self.graph.admin_graph({'team':'Missing'},'steps',a['submission_id'])['entities'],[])

    def test_selected_process_must_match_filters_before_neighbor_context_is_returned(self):
        a=self.submit(payload('Sender','Sender team'));b=self.submit(payload('Receiver','Receiver team'))
        self.proposal(a,b)
        self.assertEqual(self.graph.admin_graph({'team':'Receiver team'},'overview',a['submission_id'])['entities'],[])
        self.assertEqual(self.graph.admin_graph({'submission_id':b['submission_id']},'overview',a['submission_id'])['entities'],[])
        self.assertEqual(self.graph.admin_graph({'query':'Receiver'},'overview',a['submission_id'])['entities'],[])

    def test_new_groups_require_two_members_but_existing_corrections_can_leave_one(self):
        a=self.submit();b=self.submit();ids=[self.entity(a,'system'),self.entity(b,'system')]
        with self.assertRaises(ValueError):self.graph.canonical_create('Ledger',ids[:1],'owner','Reviewed')
        group=self.graph.canonical_create('Ledger',ids,'owner','Reviewed',bounded_result=True)
        group=self.graph.canonical_update(group['id'],'remove_member',ids[1],'owner','Corrected member',group['review_version'],bounded_result=True)
        self.assertEqual(group['member_count'],1)

    def test_downstream_traversal_handles_cycles_and_direction_with_bounded_results(self):
        receipts=[self.submit(payload('Process '+str(i))) for i in range(33)]
        pids=[self.proposal(receipts[i],receipts[(i+1)%len(receipts)]) for i in range(len(receipts))]
        start=self.entity(receipts[0]);routes,last=self.related_pages('downstream',start,7)
        self.assertEqual({x['proposal_id'] for x in routes},set(pids));self.assertEqual(len(routes),33)
        self.assertEqual(last['source_verification'],'stored_status');self.assertIn('revalidate',last['analysis_limitations'])
        neighbor=self.graph.admin_history('entity_neighbors',start,0,1)
        self.assertEqual(neighbor['page']['total'],9)  # process context, containment and both cross-process links
        self.assertEqual(len(neighbor['items']),1)
        first_step=self.entity(receipts[0],'step');sequence=self.graph.admin_history('downstream',first_step)
        self.assertEqual(len(sequence['items']),1);self.assertEqual(sequence['items'][0]['type'],'before')
        self.assertEqual(sequence['items'][0]['source'],first_step)

    def test_confirmed_temporal_routes_follow_the_same_direction_as_internal_sequence(self):
        earlier=self.submit(payload('Earlier'));later=self.submit(payload('Later'))
        pid=self.proposal(later,earlier)
        with self.graph.db:
            self.graph.db.execute("UPDATE proposals SET data=json_set(data,'$.relationship_type','happens_after') WHERE id=?",(pid,))
        start=self.entity(earlier);end=self.entity(later)
        route=self.graph.admin_history('downstream',start)['items'][0]
        self.assertEqual((route['source'],route['target'],route['type'],route['proposal_id']),(start,end,'before',pid))
        self.assertEqual(self.graph.admin_history('downstream',end)['items'],[])
        self.assertEqual(self.graph.admin_detail('proposal',pid)['item']['relationship_type'],'happens_after')

    def test_source_validation_targets_only_opened_graphed_or_reviewed_connections(self):
        p=payload('Source');p['documents']={'documents':[{'id':'doc1','sources':[{'source_id':'page1'}]}]}
        a=self.submit(p);b=self.submit(payload('Receiver'));c=self.submit(payload('Unrelated'))
        selected=self.proposal(a,b,'proposed',True);unrelated=self.proposal(a,c,'proposed',True)
        calls=[];self.graph.document_resolver=lambda *args:calls.append(args) or {'text':'Changed source'}
        self.graph.admin_browse('connections',{},0,1)
        self.graph.admin_browse('entities');self.graph.admin_history('entity_neighbors',self.entity(a))
        self.assertEqual(calls,[])
        detail=self.graph.admin_detail('proposal',selected)
        self.assertEqual(detail['item']['status'],'stale');self.assertEqual(len(calls),1)
        self.assertEqual(self.graph.db.execute('SELECT status FROM proposals WHERE id=?',(unrelated,)).fetchone()[0],'proposed')
        with self.assertRaisesRegex(ValueError,'Stale proposals'):
            self.graph.review(selected,'confirm','owner','Review',detail['item']['review_version'],bounded_result=True)
        self.assertEqual(len(calls),1)
        # Unrelated selected stored proposal is now reviewed, and only it is checked.
        with self.assertRaisesRegex(ValueError,'Stale proposals'):
            self.graph.review(unrelated,'confirm','owner','Review',1,bounded_result=True)
        self.assertEqual(len(calls),2)

    def test_graph_revalidates_only_its_bounded_visible_proposals(self):
        p=payload('Sender');p['documents']={'documents':[{'id':'doc1','sources':[{'source_id':'page1'}]}]}
        a=self.submit(p);b=self.submit(payload('Receiver'));c=self.submit(payload('Other sender'));d=self.submit(payload('Other receiver'))
        visible=self.proposal(a,b,document=True);unrelated=self.proposal(c,d,document=False)
        calls=[];self.graph.document_resolver=lambda *args:calls.append(args) or {'text':'Changed source'}
        graph=self.graph.admin_graph({},'overview',a['submission_id'])
        self.assertEqual(graph['proposals'],[]);self.assertEqual(len(calls),1)
        self.assertEqual(self.graph.db.execute('SELECT status FROM proposals WHERE id=?',(visible,)).fetchone()[0],'stale')
        self.assertEqual(self.graph.db.execute('SELECT status FROM proposals WHERE id=?',(unrelated,)).fetchone()[0],'confirmed')

    def test_invalid_admin_arguments_raise_validation_errors_instead_of_type_errors(self):
        receipt=self.submit();id=receipt['submission_id']
        for filters in ([],False,{'unexpected':True},{'state':[]},{'freshness':{}},{'team':False},
                        {'query':None},{'latest_only':1},{'revision':True},{'revision':2**64},
                        {'submission_id':False},{'exclude_group_id':0}):
            with self.subTest(filters=filters),self.assertRaises(ValueError):self.graph.admin_browse('submissions',filters)
        for offset,limit in ((True,25),(-1,25),(0,True),(0,0),(0,51),(2**64,25),('0',25)):
            with self.subTest(offset=offset,limit=limit),self.assertRaises(ValueError):self.graph.admin_browse('submissions',{},offset,limit)
        for rev in (None,True,0,-1,2**64,'1'):
            with self.subTest(revision=rev),self.assertRaises(ValueError):self.graph.admin_detail('submission',id,rev)
        for args in (('submission','not-a-uuid',1),('entity',id,True),('bogus',id,None)):
            with self.subTest(args=args),self.assertRaises(ValueError):self.graph.admin_detail(*args)
        with self.assertRaises(ValueError):self.graph.admin_history('downstream',id,False,25)
        with self.assertRaises(ValueError):self.graph.admin_graph({},'bogus')
        self.assertEqual(self.graph.admin_browse('submissions',{},2**63-1,1)['items'],[])


if __name__=='__main__':unittest.main()
