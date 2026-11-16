"""Offline regressions for the local parser, privacy boundary and durable knowledge worker."""
import io
import json
import sqlite3
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from test_documents import documents, workbook_bytes
from test_knowledge_graph import kg, payload, proposal, wait


class DocumentAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=documents.DocumentStore(Path(self.tmp.name))
        self.scope=self.store.create_scope()

    def read(self,name,data):
        record=self.store.add(self.scope,name,data)
        return self.store.extract(self.scope,record['id'])

    def test_insert_abort_and_crash_orphan_cleanup(self):
        with self.store._db() as db:
            db.execute("CREATE TRIGGER refuse BEFORE INSERT ON documents BEGIN SELECT RAISE(ABORT,'test refusal'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.add(self.scope,'test.csv',b'field,value\nsample,one')
        self.assertEqual(list(Path(self.tmp.name).rglob('original.csv')),[])
        folder=Path(self.tmp.name)/self.store._scope_hash(self.scope)/('doc_'+'a'*24)
        folder.mkdir(parents=True)
        (folder/'original.csv').write_text('orphan')
        documents.DocumentStore(self.tmp.name)
        self.assertFalse(folder.exists())

    def test_duplicate_archive_restore_and_permanent_removal(self):
        data=b'field,value\nexample,unmistakableword'
        record=self.read('one.csv',data)
        self.assertTrue(self.store.add(self.scope,'duplicate.csv',data)['duplicate_upload'])
        with self.assertRaises(documents.DocumentError): self.store.purge(self.scope,record['id'])
        self.store.archive(self.scope,record['id'])
        restored=self.store.add(self.scope,'renamed.csv',data)
        self.assertEqual((restored['id'],restored['restored_upload']),(record['id'],True))
        self.store.archive(self.scope,record['id'])
        self.assertTrue(self.store.purge(self.scope,record['id'])['purged'])
        self.assertFalse(self.store.list(self.scope,include_archived=True))
        self.assertFalse(list(Path(self.tmp.name).rglob('original.csv')))
        self.assertFalse(self.store.search(self.scope,'unmistakableword'))

    def test_excel_csv_encodings_unicode_search_and_label_only_misses(self):
        content='field;value\nＦｕｎｄ;年度確認作業\nकर्म;कर्मचारी सत्यापन\ncafé;review\n'
        record=self.read('labelonly.csv',content.encode('utf-32'))
        self.assertEqual((record['status'],record['inventory']['delimiter']),('ready',';'))
        for query in ('Fund','確認','कर्मचारी','cafe\u0301'):
            self.assertTrue(self.store.search(self.scope,query),query)
        self.assertEqual(self.store.search(self.scope,'labelonly'),[])
        bad=self.read('invalid.csv',content.encode('utf-16-le'))
        self.assertEqual((bad['status'],bad['retryable']),('error',False))
        self.assertIn('UTF',bad['error'])

    def test_xlsx_all_zip_parts_checked_and_sparse_coordinates_validated(self):
        def modify(source,fn):
            output=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(source)) as inp,zipfile.ZipFile(output,'w') as out:
                for name in inp.namelist(): out.writestr(name,fn(name,inp.read(name)))
            return output.getvalue()
        body=workbook_bytes()
        out=io.BytesIO(body)
        with zipfile.ZipFile(out,'a') as archive: archive.writestr('xl/parts/unsafe.data','<!DOCTYPE unexpected>')
        self.assertIn('DTD',self.read('unsafe.xlsx',out.getvalue())['error'])
        body=modify(body,lambda name,text:text.replace(b'<row r="2"',b'<row r="1"') if name.endswith('sheet1.xml') else text)
        self.assertEqual(self.read('order.xlsx',body)['status'],'error')

    def test_legacy_xls_reader_is_versioned_bounded_and_closed(self):
        data=bytes.fromhex('D0CF11E0A1B11AE1')+b'FAKE TEST DATA'
        reader=Mock()
        reader.__version__='2.0.1'
        sheet=Mock(name='sheet');sheet.name='Hidden';sheet.visibility=1
        sheet.nrows=2;sheet.row_values.side_effect=lambda row: ['header'] if not row else ['value']
        book=reader.open_workbook.return_value;book.nsheets=1;book.sheet_by_index.return_value=sheet
        import sys
        with patch.dict(sys.modules,{'xlrd':reader}),patch.object(documents.importlib.util,'find_spec',return_value=True):
            saved=self.read('legacy.xls',data)
        self.assertEqual(saved['inventory']['sheets'][0]['visibility'],'hidden')
        self.assertIsNone(saved['inventory']['sheets'][0]['formula_cells'])
        book.release_resources.assert_called_once()
        with patch.dict(sys.modules,{'xlrd':reader}),patch.object(documents,'MAX_CELLS',1):
            with self.assertRaisesRegex(documents.ExtractionError,'million'):
                documents._legacy_xls(self.store.original_path(self.scope,saved['id']), saved,documents._Chunks(saved))

    def test_fictional_settlement_fixtures_include_pdf_forms_comments_hidden_sheets_and_legacy_csv(self):
        base=Path(__file__).parent/'fixtures'/'document-audit'
        pdf=self.read('sample.pdf',(base/'settlement-intake.pdf').read_bytes())
        self.assertEqual(pdf['inventory']['pages'],2)
        self.assertTrue(self.store.search(self.scope,'override',ids=[pdf['id']]))
        self.assertGreater(len(self.store.page_input(self.scope,pdf['id'],2)),50)
        book=self.read('sample.xlsx',(base/'settlement-checks.xlsx').read_bytes())
        self.assertEqual(book['inventory']['sheet_count'],3)
        comment=self.store.search(self.scope,'fictional amount',ids=[book['id']])
        self.assertTrue(any(c.get('origin')=='cell_comment' and c['cell']=='B2' for c in comment))
        self.assertEqual(book['inventory']['sheets'][1]['visibility'],'hidden')
        csv=self.read('sample.csv',(base/'settlement-log.csv').read_bytes())
        self.assertEqual(csv['status'],'error')
        self.assertIn('UTF',csv['error'])

    def test_index_boundaries_and_platform_review_lock(self):
        record=self.read('a.csv',b'alpha,beta')
        with self.store.review_lease(self.scope,record['id']) as first:
            with documents.DocumentStore(self.tmp.name).review_lease(self.scope,record['id']) as second:
                self.assertTrue(first); self.assertFalse(second)
        chunks=documents._Chunks(record)
        with patch.object(documents,'MAX_INDEX_BYTES',3):
            chunks.add('x','x','xyz',{})
            with self.assertRaises(documents.ExtractionError): chunks.add('z','z','z',{})
        with patch.object(documents,'MAX_CHUNKS',1):
            with self.assertRaises(documents.ExtractionError): chunks.add('z','z','z',{})


class KnowledgeAuditTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'graph.db'
        self.graph=kg.KnowledgeGraph(self.path)
        self.addCleanup(self.graph.close)

    def test_transient_job_claim_failure_has_one_failure_and_explicit_retry(self):
        item=self.graph.submit(payload('Fictional review','We check the document.'))
        self.graph.analyzer=lambda *_:[]
        with self.graph.db:
            self.graph.db.execute("CREATE TRIGGER fail_claim BEFORE UPDATE ON jobs WHEN new.status='processing' BEGIN SELECT RAISE(ABORT,'reproduction'); END")
        self.graph.retry(item['job_id'])
        self.assertEqual(wait(self.graph,item['job_id'])['status'],'failed')
        with self.graph.db: self.graph.db.execute('DROP TRIGGER fail_claim')
        self.graph.retry(item['job_id'])
        result=wait(self.graph,item['job_id'])
        self.assertEqual((result['status'],result['attempts']),('completed',1))

    def test_saved_document_scope_is_a_digest_and_replay_tracks_current_job(self):
        body=payload('Example','We check every statement.')
        body['documents']={'documents':[{'id':'doc-1','sources':[{'source_id':'p1'}]}]}
        secret='private-capability-for-a-synthetic-interview'
        result=self.graph.submit(body,document_scope=secret)
        token=self.graph.document_scope(result['submission_id'],1,'doc-1')
        self.assertEqual(token,kg.scope_digest(secret))
        self.assertTrue(token.document_scope_digest)
        self.assertFalse(getattr(str(token),'document_scope_digest',False))
        self.assertNotIn(secret.encode(),self.path.read_bytes())

    def test_transient_read_preserves_a_confirmation_and_revalidation_checks_the_original_quote(self):
        body=payload('Sender','We prepare the accepted invoice.')
        body['documents']={'documents':[{'id':'support','sources':[{'source_id':'page1'}]}]}
        source={'text':'The manager personally approves the invoice before settlement.'}
        self.graph.document_resolver=lambda *_:dict(source)
        a=self.graph.submit(body,document_scope='fictional-private-scope')
        def analyzer(current,candidates):
            item=proposal(current,candidates)[0]
            item['evidence'][0]={'type':'document_supported','submission_id':a['submission_id'],'revision':1,'document_id':'support','source_id':'page1','quote':'The manager personally approves the invoice'}
            return [item]
        self.graph.analyzer=analyzer
        b=self.graph.submit({**payload('Receiver','We then settle the approved amount.'),'team':'Receiving team'})
        self.assertEqual(wait(self.graph,b['job_id'])['status'],'completed')
        item=self.graph.admin_browse('connections')['items'][0]
        for team in ('Operations','Receiving team'):
            self.assertEqual(self.graph.admin_browse('connections',{'team':team})['page']['total'],1)
        self.graph.review(item['id'],'confirm','reviewer','Reviewed both accounts',1)
        with patch.object(self.graph,'document_resolver',side_effect=sqlite3.OperationalError('temporary lock')):
            detail=self.graph.admin_detail('proposal',item['id'])['item']
            self.assertEqual((detail['status'],detail['source_verification']),('confirmed','temporarily_unavailable'))
        source['text']+=' A reviewer corrected the footer.'
        stale=self.graph.admin_detail('proposal',item['id'])['item']
        self.assertEqual(stale['status'],'stale')
        restored=self.graph.review(item['id'],'revalidate','reviewer','Original quote verified',stale['review_version'])
        self.assertEqual(restored['status'],'proposed')

    def test_over_limit_company_count_with_confirmed_links(self):
        with self.graph.db:
            receipts=[]
            for n in range(400):
                sid,eid=kg.new_id(),kg.new_id()
                self.graph.db.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?)',(sid,sid,1,'{}','fixture',kg.now()))
                self.graph.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',(eid,sid,1,'process_version','Example','{}'))
                receipts.append(sid)
            for n in range(80):
                data={'source_submission_id':receipts[n],'source_revision':1,'destination_submission_id':receipts[n+1],'destination_revision':1,'relationship_type':'hands_off_to'}
                self.graph.db.execute('INSERT INTO proposals(id,fingerprint,data,status,created_at) VALUES (?,?,?,?,?)',(kg.new_id(),str(n),json.dumps(data),'confirmed',kg.now()))
        started=time.monotonic()
        result=self.graph.admin_graph({},'overview')
        self.assertEqual(result['counts'],{'nodes':400,'connections':80})
        self.assertTrue(result['too_large'])
        self.assertLess(time.monotonic()-started,10)

    def test_one_letter_quote_and_mixed_scope_filter(self):
        self.assertFalse(kg.meaningful_quote('a','An analyst approves a file.'))
        self.assertTrue(kg.meaningful_quote('B2=approved','A2=flag | B2=approved'))
        self.assertFalse(kg.meaningful_quote('B2=approve','A2=flag | B2=approved'))
