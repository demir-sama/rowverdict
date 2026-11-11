import base64
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

AVAILABLE=importlib.util.find_spec('fastapi') is not None and importlib.util.find_spec('httpx') is not None
ROOT=Path(__file__).resolve().parents[1]
if AVAILABLE:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    spec=importlib.util.spec_from_file_location('_rowverdict_test_api',ROOT/'dashboard/plugin_api.py')
    API=importlib.util.module_from_spec(spec);sys.modules[spec.name]=API;spec.loader.exec_module(API)


@unittest.skipUnless(AVAILABLE,'Dashboard integration requires the Hermes-provided FastAPI/httpx runtime')
class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.inputs=self.root/'input';self.inputs.mkdir()
        self.file=self.inputs/'data.csv';self.file.write_text('id,amount\na,1\nb,bad\n')
        # Realistic profile directory: uploads must work under .hermes without
        # accidentally making neighboring .hermes configuration readable.
        self.state=self.root/'.hermes/plugin-data/rowverdict'
        self.app=API.core.Engine(self.state,[str(self.inputs),str(self.state/'uploads')])
        self.mock=patch.object(API,'app_engine',return_value=self.app);self.mock.start()
        fast=FastAPI();fast.include_router(API.router,prefix='/api/plugins/rowverdict');self.client=TestClient(fast)
        self.base='/api/plugins/rowverdict'
        self.contract={'columns':[{'name':'id'},{'name':'amount','type':'decimal'}]}

    def tearDown(self):self.client.close();self.mock.stop();self.tmp.cleanup()
    def post(self,path,body):return self.client.post(self.base+path,json=body)
    def get(self,path):return self.client.get(self.base+path)
    def plan(self):
        response=self.post('/plans',{'source':str(self.file),'contract':self.contract})
        self.assertEqual(response.status_code,200,response.text);return response.json()

    def test_distinct_profile_source_roots_do_not_share_cached_core(self):
        import shutil
        other=self.root/'other-profile-plugin'
        (other/'dashboard').mkdir(parents=True)
        for name in ('__init__.py','core.py','formats.py','drafting.py','audit.py'):
            shutil.copyfile(ROOT/name,other/name)
        shutil.copyfile(ROOT/'dashboard/plugin_api.py',other/'dashboard/plugin_api.py')
        spec=importlib.util.spec_from_file_location('_rowverdict_other_profile_api',other/'dashboard/plugin_api.py')
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        self.assertIsNot(module.core,API.core)
        self.assertEqual(Path(module.core.__file__).resolve(),(other/'core.py').resolve())
        self.assertNotEqual(module._package_name,API._package_name)

    def test_real_inspect_plan_history_and_detail(self):
        self.assertEqual(self.post('/inspect',{'source':str(self.file)}).json()['input_rows'],2)
        run=self.plan();history=self.get('/runs').json()
        self.assertTrue(history['export_via_host_only']);self.assertTrue(history['uploads_enabled'])
        self.assertEqual(history['runs'][0]['id'],run['id'])
        self.assertEqual(self.get('/runs/'+run['id']).status_code,200)

    def test_draft_cannot_be_used_before_explicit_ui_review(self):
        draft=self.post('/drafts',{'source':str(self.file)}).json()
        body={'source':str(self.file),'draft_id':draft['draft_id']}
        self.assertEqual(self.post('/plans',body).status_code,409)
        review={'contract':self.contract,'expected_source_sha256':draft['source_sha256'],'acknowledgement':'I reviewed this exact contract'}
        self.assertEqual(self.post('/drafts/'+draft['draft_id']+'/review',review).status_code,200)
        self.assertEqual(self.post('/plans',body).json()['summary']['clean_rows'],1)

    def test_ui_review_requires_acknowledgement_and_hash(self):
        draft=self.post('/drafts',{'source':str(self.file)}).json();url='/drafts/'+draft['draft_id']+'/review'
        body={'contract':self.contract,'expected_source_sha256':draft['source_sha256'],'acknowledgement':'yes'}
        self.assertEqual(self.post(url,body).status_code,409)
        body.update(acknowledgement='I reviewed this exact contract',expected_source_sha256='0'*64)
        self.assertEqual(self.post(url,body).status_code,409)

    def test_ui_replay_previews_then_creates_review_plan_without_export(self):
        parent=self.plan();url='/runs/'+parent['id']+'/replays'
        body={'patch':[{'row':3,'set':{'amount':'2'}}],'preview':True}
        self.assertFalse(self.post(url,body).json()['persisted'])
        self.assertEqual(len(self.app.history()),1)
        body['preview']=False;child=self.post(url,body).json()
        self.assertEqual(child['state'],'PLANNED');self.assertEqual(child['summary']['clean_rows'],2)
        self.assertFalse((self.state/'exports').exists())

    def test_no_export_or_arbitrary_artifact_routes(self):
        run=self.plan()
        for endpoint in ('/export','/runs/'+run['id']+'/export','/runs/'+run['id']+'/artifacts/../../config.yaml'):
            self.assertIn(self.post(endpoint,{'plan_id':run['id']}).status_code,(404,405))
        self.assertFalse((self.state/'exports').exists())

    def test_quarantine_and_report_use_real_engine(self):
        run=self.plan()
        q=self.get('/runs/'+run['id']+'/quarantine?query=bad&code=TYPE&limit=1').json()
        self.assertEqual(q['total'],1);self.assertEqual(q['records'][0]['cells'],['b','bad'])
        report=self.get('/runs/'+run['id']+'/report').json()
        self.assertIn('PREVIEW',report['html']);self.assertTrue(report['filename'].endswith('.html'))

    def test_stale_source_returns_refusal_and_history_state(self):
        run=self.plan();self.file.write_text('id,amount\nx,2\n')
        self.assertEqual(self.post('/runs/'+run['id']+'/check',{}).status_code,409)
        self.assertEqual(self.get('/runs').json()['runs'][0]['state'],'STALE')

    def test_upload_is_private_and_parsable_under_hermes_directory(self):
        body={'filename':'orders.csv','content_base64':base64.b64encode(b'id,amount\n0001,1\n').decode()}
        response=self.post('/inputs',body);self.assertEqual(response.status_code,200,response.text)
        source=response.json()['source'];self.assertEqual(Path(source).stat().st_mode & 0o777,0o600)
        self.assertEqual(self.post('/inspect',{'source':source}).json()['input_rows'],1)
        forbidden=self.root/'.hermes/config.json';forbidden.write_text('{"id":"no"}')
        self.assertEqual(self.post('/inspect',{'source':str(forbidden)}).status_code,409)

    def test_uploads_default_disabled(self):
        self.app.allowed_roots=[self.inputs]
        self.assertEqual(self.post('/inputs',{'filename':'orders.csv','content_base64':'YQ=='}).status_code,409)

    def test_upload_rejects_traversal_credentials_invalid_base64_and_unsupported_type(self):
        for filename in ('../data.csv','credentials.json','.env.json','data.exe','a\\data.csv'):
            with self.subTest(filename=filename):
                self.assertEqual(self.post('/inputs',{'filename':filename,'content_base64':'YQ=='}).status_code,409)
        self.assertEqual(self.post('/inputs',{'filename':'data.csv','content_base64':'not-base64'}).status_code,409)

    def test_extra_fields_and_invalid_limits_fail_closed(self):
        self.assertEqual(self.post('/plans',{'source':str(self.file),'contract':self.contract,'approved':True}).status_code,422)
        run=self.plan()
        self.assertEqual(self.get('/runs/'+run['id']+'/quarantine?limit=10000').status_code,409)
        self.assertEqual(self.get('/runs/not-a-plan-id').status_code,409)

    def test_approved_report_is_receipt_verified_not_regenerated(self):
        run=self.plan()
        # Explicit development/library invocation, NOT a simulated host approval.
        receipt=self.app.export(run['id'])
        report=self.get('/runs/'+run['id']+'/report').json()['html']
        self.assertEqual(report,(Path(receipt['output_dir'])/'audit.html').read_text())
        (Path(receipt['output_dir'])/'audit.html').write_text('changed')
        self.assertEqual(self.get('/runs/'+run['id']+'/report').status_code,409)
