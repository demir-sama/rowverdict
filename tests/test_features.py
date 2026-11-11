import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from html import escape
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import Engine, Refusal, canonical, digest, validate_contract, read_table
import formats


def workbook(rows, formula=None, extra=None, sheets=1, styles=None, cell_types=None):
    main = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    sheet_tags = ''.join(f'<sheet name="Sheet{i}" sheetId="{i}" r:id="rId{i}"/>' for i in range(1, sheets + 1))
    links = ''.join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, sheets + 1))
    xml_rows = []
    for row_no, row in enumerate(rows, 1):
        cells = []
        for index, value in enumerate(row):
            coordinate = chr(65 + index) + str(row_no)
            if formula and coordinate in formula:
                body = '<f>' + escape(formula[coordinate]) + '</f><v>999</v>'
                cells.append(f'<c r="{coordinate}">{body}</c>')
            elif cell_types and coordinate in cell_types:
                kind, style = cell_types[coordinate]
                cells.append(f'<c r="{coordinate}" t="{kind}" s="{style}"><v>{escape(value)}</v></c>')
            else:
                cells.append(f'<c r="{coordinate}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        xml_rows.append(f'<row r="{row_no}">' + ''.join(cells) + '</row>')
    content = f'<worksheet xmlns="{main}"><sheetData>' + ''.join(xml_rows) + '</sheetData></worksheet>'
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>{sheet_tags}</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{links}</Relationships>')
        for i in range(1, sheets + 1):
            z.writestr(f'xl/worksheets/sheet{i}.xml', content)
        if styles:
            z.writestr('xl/styles.xml', styles)
        for name, body in (extra or {}).items():
            z.writestr(name, body)
    return output.getvalue()


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        self.app = Engine(self.root / 'state', [str(self.inputs)])
        self.file = self.inputs / 'orders.csv'
        self.file.write_text('id,amount\n0001,1.25\n0002,bad\n0003,3.50\n')
        self.contract = {'columns':[{'name':'id','type':'string'},{'name':'amount','type':'decimal','min':'0'}], 'unique_key':['id']}

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self):
        return self.app.plan(str(self.file), self.contract)

    def test_draft_is_labeled_and_not_auto_applied(self):
        draft = self.app.draft(str(self.file))
        self.assertEqual(draft['status'], 'DRAFT')
        self.assertTrue(draft['requires_human_review'])
        self.assertEqual(self.app.history(), [])
        self.assertFalse((self.app.data_dir / 'exports').exists())
        with self.assertRaises(Refusal):
            validate_contract(draft)

    def test_extracting_draft_cannot_bypass_review(self):
        draft = self.app.draft(str(self.file))
        with self.assertRaisesRegex(Refusal, 'DRAFT_REVIEW'):
            self.app.plan(str(self.file), draft['suggested_contract'])
        with self.assertRaisesRegex(Refusal, 'DRAFT_REVIEW'):
            self.app.plan(str(self.file), self.contract)
        with self.assertRaisesRegex(Refusal, 'DRAFT_REVIEW'):
            self.app.plan(str(self.file), draft_id=draft['draft_id'])

    def test_review_allows_exact_source_policy_and_is_immutable(self):
        draft = self.app.draft(str(self.file))
        reviewed = self.app.review_draft(draft['draft_id'], self.contract)
        run = self.app.plan(str(self.file), draft_id=draft['draft_id'])
        self.assertEqual(run['summary']['clean_rows'], 2)
        self.assertEqual(run['summary']['draft_review']['policy_sha256'], reviewed['reviewed_policy_sha256'])
        self.assertEqual(reviewed, self.app.review_draft(draft['draft_id'], self.contract))
        edited = json.loads(json.dumps(self.contract)); edited['unique_key'] = []
        with self.assertRaisesRegex(Refusal, 'immutable'):
            self.app.review_draft(draft['draft_id'], edited)

    def test_draft_review_refuses_source_changes(self):
        draft = self.app.draft(str(self.file))
        self.file.write_text('id,amount\nx,9\n')
        with self.assertRaisesRegex(Refusal, 'STALE'):
            self.app.review_draft(draft['draft_id'])

    def test_draft_preserves_ids_and_leading_zeroes(self):
        self.file.write_text('order_id,postal,number\n0001,00102,001\n0002,00103,002\n')
        draft = self.app.draft(str(self.file))
        self.assertEqual([c['type'] for c in draft['suggested_contract']['columns']], ['string'] * 3)
        self.assertEqual(draft['suggested_contract']['unique_key'], ['order_id'])

    def test_draft_numeric_and_unambiguous_dates(self):
        self.file.write_text('count,amount,date\n1,1.25,2026-11-11\n2,-2.50,2026-11-12\n')
        cols = self.app.draft(str(self.file))['suggested_contract']['columns']
        self.assertEqual([c['type'] for c in cols], ['integer','decimal','date'])
        self.assertEqual(cols[2]['date_format'], '%Y-%m-%d')

    def test_draft_ambiguous_dates_stay_string(self):
        self.file.write_text('date\n01/02/2026\n03/04/2026\n')
        draft = self.app.draft(str(self.file))
        self.assertEqual(draft['suggested_contract']['columns'][0]['type'], 'string')
        self.assertIn('AMBIGUOUS', draft['notes'][0]['reason'])

    def test_draft_explicit_day_first(self):
        self.file.write_text('date\n13/02/2026\n14/04/2026\n')
        col = self.app.draft(str(self.file))['suggested_contract']['columns'][0]
        self.assertEqual(col['date_format'], '%d/%m/%Y')

    def test_draft_small_category_enum_not_personal_values(self):
        self.file.write_text('status,email\npaid,a@example.test\nheld,b@example.test\npaid,a@example.test\nheld,b@example.test\n')
        cols = self.app.draft(str(self.file))['suggested_contract']['columns']
        self.assertEqual(cols[0]['enum'], ['held','paid'])
        self.assertNotIn('enum', cols[1])

    def test_sample_is_bounded_and_full_plan_checks_tail(self):
        self.file.write_text('count\n1\n2\nbad\n')
        draft = self.app.draft(str(self.file), sample_rows=2)
        self.assertEqual(draft['sample_rows'], 2)
        self.app.review_draft(draft['draft_id'])
        run = self.app.plan(str(self.file), draft_id=draft['draft_id'])
        self.assertEqual(run['summary']['quarantined_rows'], 1)
        for invalid in (0,1001,True):
            with self.assertRaises(Refusal):
                self.app.draft(str(self.file), sample_rows=invalid)

    def test_json_exact_numeric_tokens_missing_fields_and_union_schema(self):
        file = self.inputs / 'data.json'
        file.write_text('[{"id":"0001","amount":12345678901234567890.125},{"id":"0002"}]')
        run = self.app.plan(str(file), self.contract)
        self.assertEqual(run['summary']['clean_decimal_totals']['amount'], '12345678901234567890.125')
        self.assertEqual(run['summary']['issue_counts'], {'REQUIRED':1})
        file.write_text('[{"id":"a"},{"id":"b","new":"value"}]')
        self.assertEqual(self.app.inspect(str(file))['columns'], ['id','new'])

    def test_jsonl_blank_lines_and_formula_cells(self):
        file = self.inputs / 'data.jsonl'
        file.write_text('\n{"id":"0001","amount":"1.25"}\n\n{"id":"=HYPERLINK(1)","amount":"2"}\n')
        run = self.app.plan(str(file), self.contract)
        self.assertEqual(run['summary']['input_rows'], 2)
        self.assertEqual(run['summary']['blank_lines_skipped'], 2)
        self.assertEqual(run['summary']['issue_counts'], {'FORMULA':1})
        self.assertEqual(run['summary']['input_format'], 'jsonl')

    def test_json_nested_duplicate_and_nonfinite_refused(self):
        file = self.inputs / 'data.json'
        for raw in ('[{"id":"a","id":"b"}]','[{"id": {"nested":1}}]','[{"id":NaN}]','[{"id":Infinity}]','[[]]','[]'):
            file.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(Refusal):
                self.app.inspect(str(file))

    def test_json_scalar_boolean_and_null(self):
        file = self.inputs / 'data.json'
        file.write_text('{"id":true,"amount":null}')
        self.assertEqual(read_table(file.read_bytes(), '.json')[1], [['true','']])

    def test_json_limits(self):
        file = self.inputs / 'data.json'; file.write_text('[{"id":"a"},{"id":"b"}]')
        with patch.object(formats, 'MAX_ROWS', 1), self.assertRaisesRegex(Refusal,'LIMIT'):
            self.app.inspect(str(file))
        with patch.object(formats, 'MAX_CELLS', 2), self.assertRaisesRegex(Refusal,'LIMIT'):
            self.app.inspect(str(file))

    def test_jsonl_malformed_tail_fails_whole_input(self):
        file = self.inputs / 'data.jsonl'; file.write_text('{"id":"a"}\nnot-json\n')
        with self.assertRaisesRegex(Refusal,'JSON'):
            self.app.inspect(str(file))
        self.assertFalse(self.app.data_dir.exists())

    def test_xlsx_text_ids_and_stored_formulas_quarantined(self):
        file=self.inputs/'data.xlsx'
        file.write_bytes(workbook([['id','amount'],['0001','1.25'],['0002','2']],formula={'B3':'1+1'}))
        run=self.app.plan(str(file),self.contract)
        self.assertEqual(run['summary']['clean_rows'],1)
        self.assertEqual(run['summary']['issue_counts'],{'EXCEL_FORMULA':1,'FORMULA':1,'TYPE':1})
        receipt=self.app.export(run['id'])
        self.assertIn('0001,1.25', (Path(receipt['output_dir'])/'clean.csv').read_text())
        self.assertIn('=1+1', (Path(receipt['output_dir'])/'quarantine.json').read_text())

    def test_xlsx_multisheet_requires_explicit_selection(self):
        file=self.inputs/'data.xlsx';file.write_bytes(workbook([['id','amount'],['0001','1']],sheets=2))
        with self.assertRaisesRegex(Refusal,'multiple worksheets'):
            self.app.inspect(str(file))
        self.assertEqual(self.app.inspect(str(file),sheet='Sheet2')['worksheet'],'Sheet2')
        contract={**self.contract,'sheet':'Sheet2'}
        self.assertEqual(self.app.plan(str(file),contract)['summary']['worksheet'],'Sheet2')

    def test_xlsx_empty_trailing_cells_and_error_cells(self):
        file=self.inputs/'data.xlsx';file.write_bytes(workbook([['id','amount'],['0001']],cell_types=None))
        self.assertEqual(self.app.plan(str(file),self.contract)['summary']['issue_counts'],{'REQUIRED':1})
        file.write_bytes(workbook([['id','amount'],['#DIV/0!','2']],cell_types={'A2':('e',0)}))
        self.assertIn('EXCEL_ERROR',self.app.plan(str(file),self.contract)['summary']['issue_counts'])

    def test_xlsx_date_storage_and_fictitious_leap_day(self):
        file=self.inputs/'data.xlsx'
        styles='<styleSheet xmlns="'+formats.NS['s']+'"><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>'
        file.write_bytes(workbook([['date'],['61'],['60'],['61.5']],styles=styles,cell_types={'A2':('n',1),'A3':('n',1),'A4':('n',1)}))
        c={'columns':[{'name':'date','type':'date','date_format':'%Y-%m-%d'}]}
        run=self.app.plan(str(file),c)
        self.assertEqual(run['summary']['clean_rows'],1)
        self.assertEqual(run['summary']['issue_counts']['EXCEL_DATE'],2)
        self.assertEqual(self.app.quarantine(run['id'])['total'],2)

    def test_xlsx_zip_traversal_macros_and_bombs_refused(self):
        for extra in ({'../escape.xml':'x'},{'xl/vbaProject.bin':'x'},{'bomb.xml':'x'*2_000_000}):
            file=self.inputs/'data.xlsx';file.write_bytes(workbook([['id']],extra=extra))
            with self.subTest(extra=list(extra)),self.assertRaises(Refusal):
                self.app.inspect(str(file))

    def test_xlsx_dtd_entities_refused(self):
        payload='<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><x>&secret;</x>'
        file=self.inputs/'data.xlsx';file.write_bytes(workbook([['id']],extra={'xl/sharedStrings.xml':payload}))
        with self.assertRaisesRegex(Refusal,'unsafe or malformed XML'):
            self.app.inspect(str(file))

    def test_xlsx_duplicate_zip_entries_refused(self):
        output=io.BytesIO(workbook([['id']]))
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(output,'a') as z:z.writestr('xl/workbook.xml','x')
        file=self.inputs/'data.xlsx';file.write_bytes(output.getvalue())
        with self.assertRaisesRegex(Refusal,'duplicate'):
            self.app.inspect(str(file))

    def test_replay_creates_new_plan_same_policy_and_parent_unchanged(self):
        parent=self.plan()
        child=self.app.replay(parent['id'],patch=[{'row':3,'set':{'amount':'2.50'}}])
        self.assertNotEqual(parent['id'],child['id'])
        self.assertEqual(parent['policy_sha256'],child['policy_sha256'])
        self.assertEqual(child['summary']['clean_rows'],3)
        self.assertEqual(self.app.get(parent['id'])['summary']['clean_rows'],2)
        self.assertEqual(self.app.get(parent['id'])['state'],'PLANNED')
        self.assertEqual(child['state'],'PLANNED')
        self.assertFalse((self.app.data_dir/'exports').exists())
        receipt=self.app.export(child['id'])
        self.assertEqual(receipt['summary']['replay']['parent_plan_id'],parent['id'])
        self.assertEqual(self.file.read_text(),'id,amount\n0001,1.25\n0002,bad\n0003,3.50\n')

    def test_replay_corrections_can_remain_bad(self):
        child=self.app.replay(self.plan()['id'],patch=[{'row':3,'set':{'amount':'=1+1'}}])
        self.assertEqual(child['summary']['quarantined_rows'],1)
        self.assertIn('FORMULA',child['summary']['issue_counts'])

    def test_replay_rechecks_duplicates_against_clean_rows(self):
        child=self.app.replay(self.plan()['id'],patch=[{'row':3,'set':{'id':'0001','amount':'2'}}])
        self.assertEqual(child['summary']['clean_rows'],1)
        self.assertEqual(child['summary']['issue_counts'],{'DUPLICATE_KEY':2})

    def test_replay_rejects_clean_unknown_duplicate_or_invalid_updates(self):
        parent=self.plan()
        invalids=[[{'row':2,'set':{'amount':'2'}}],[{'row':999,'set':{'amount':'2'}}],[{'row':3,'set':{'new':'2'}}],[{'row':True,'set':{'amount':'2'}}],[{'row':3,'set':{'amount':2}}],[{'row':3,'set':{'amount':'2'}},{'row':3,'set':{'amount':'3'}}],[]]
        for changes in invalids:
            with self.subTest(changes=changes),self.assertRaises(Refusal):
                self.app.replay(parent['id'],patch=changes)

    def test_replay_wrong_width_requires_full_replacement(self):
        self.file.write_text('id,amount\n0001,1,extra\n')
        parent=self.plan()
        with self.assertRaisesRegex(Refusal,'complete cells'):
            self.app.replay(parent['id'],patch=[{'row':2,'set':{'amount':'1'}}])
        child=self.app.replay(parent['id'],patch=[{'row':2,'cells':['0001','1']}])
        self.assertEqual(child['summary']['clean_rows'],1)

    def test_patch_file_hash_stales_child(self):
        file=self.inputs/'patch.json';file.write_text('[{"row":3,"set":{"amount":"2"}}]')
        child=self.app.replay(self.plan()['id'],patch_file=str(file))
        file.write_text('[{"row":3,"set":{"amount":"9"}}]')
        with self.assertRaisesRegex(Refusal,'STALE'):
            self.app.export(child['id'])
        self.assertEqual(self.app.get(child['id'])['state'],'STALE')
        self.assertFalse((self.app.data_dir/'exports').exists())

    def test_replay_refuses_original_changes_even_exported_parent(self):
        parent=self.plan();self.app.export(parent['id'])
        self.file.write_text('id,amount\nnew,3\n')
        with self.assertRaisesRegex(Refusal,'STALE'):
            self.app.replay(parent['id'],patch=[{'row':3,'set':{'amount':'2'}}])
        self.assertEqual(self.app.get(parent['id'])['state'],'EXPORTED')

    def test_replay_child_source_change_stays_stale(self):
        parent=self.plan();child=self.app.replay(parent['id'],patch=[{'row':3,'set':{'amount':'2'}}])
        original=self.file.read_bytes();self.file.write_text('id,amount\nx,1\n')
        with self.assertRaisesRegex(Refusal,'STALE'):self.app.check(child['id'])
        self.file.write_bytes(original)
        with self.assertRaisesRegex(Refusal,'STALE'):self.app.check(child['id'])

    def test_replay_preview_persists_nothing(self):
        parent=self.plan();before=len(self.app.history())
        preview=self.app.replay(parent['id'],patch=[{'row':3,'set':{'amount':'2'}}],preview=True)
        self.assertFalse(preview['persisted'])
        self.assertTrue(preview['requires_export_approval'])
        self.assertEqual(len(self.app.history()),before)

    def test_chained_replay_preserves_previous_fixes(self):
        self.file.write_text('id,amount\na,bad\nb,bad\n')
        first=self.app.replay(self.plan()['id'],patch=[{'row':2,'set':{'amount':'1'}}])
        second=self.app.replay(first['id'],patch=[{'row':3,'set':{'amount':'2'}}])
        self.assertEqual(second['summary']['clean_rows'],2)
        self.assertEqual(self.app.export(second['id'])['summary']['clean_decimal_totals']['amount'],'3')

    def test_excel_formula_can_be_manually_replaced(self):
        file=self.inputs/'data.xlsx';file.write_bytes(workbook([['id','amount'],['0001','1']],formula={'B2':'1+1'}))
        parent=self.app.plan(str(file),self.contract)
        child=self.app.replay(parent['id'],patch=[{'row':2,'set':{'amount':'2'}}])
        self.assertEqual(child['summary']['quarantined_rows'],0)
        self.assertEqual(self.app.export(child['id'])['summary']['clean_rows'],1)

    def test_quarantine_pagination_search_and_reason_filter(self):
        self.file.write_text('id,amount\na,bad\nb,=SUM(1)\nc,bad\n')
        run=self.plan()
        self.assertEqual(self.app.quarantine(run['id'],limit=1,offset=1)['records'][0]['row'],3)
        self.assertEqual(self.app.quarantine(run['id'],query='SUM')['total'],1)
        self.assertEqual(self.app.quarantine(run['id'],code='FORMULA')['total'],1)
        with self.assertRaises(Refusal):self.app.quarantine(run['id'],limit=101)

    def test_report_preview_no_artifacts_or_raw_values(self):
        self.file.write_text('id,amount\nSECRET_UNIQUE_RECORD,bad\n')
        run=self.plan();report=self.app.report(run['id'])
        self.assertIn('PREVIEW',report)
        self.assertNotIn('SECRET_UNIQUE_RECORD',report)
        self.assertNotIn('<script',report)
        self.assertNotIn('src=',report)
        self.assertFalse((self.app.data_dir/'exports').exists())

    def test_report_escaped_untrusted_schema_and_bound_to_receipt(self):
        self.file.write_text('id,<img src=x onerror=alert(1)>\na,bad\n')
        c={'columns':[{'name':'id'},{'name':'<img src=x onerror=alert(1)>','type':'decimal'}]}
        run=self.app.plan(str(self.file),c);receipt=self.app.export(run['id'])
        report=self.app.report(run['id'])
        self.assertNotIn('<img',report);self.assertIn('&lt;img',report)
        path=Path(receipt['output_dir'])/'audit.html'
        self.assertEqual(digest(path.read_bytes()),receipt['artifacts']['audit.html']['sha256'])
        self.assertIn(receipt['receipt_core_sha256'],report)
        self.assertEqual(self.app.export(run['id']),receipt)

    def test_report_tamper_or_symlink_refuses_idempotent_export(self):
        run=self.plan();receipt=self.app.export(run['id'])
        file=Path(receipt['output_dir'])/'audit.html';file.write_text('tampered')
        with self.assertRaisesRegex(Refusal,'RECEIPT'):self.app.export(run['id'])
        file.unlink();file.symlink_to(self.file)
        with self.assertRaises(Refusal):self.app.report(run['id'])

    def test_report_contains_counts_policy_reasons_drift_and_hashes(self):
        self.plan();run=self.plan();receipt=self.app.export(run['id'])
        report=self.app.report(run['id'])
        for needle in ('input records','quarantined','Policies','TYPE','Drift',run['policy_sha256'],run['source_sha256'],receipt['artifacts']['clean.csv']['sha256']):
            self.assertIn(needle,report)


# Native registration / command coverage without a Hermes or live model dependency.
SPEC=importlib.util.spec_from_file_location('_rowverdict_test_plugin',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
PLUGIN=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=PLUGIN;SPEC.loader.exec_module(PLUGIN)


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.file=self.root/'data.csv';self.file.write_text('id,amount\na,bad\n')
        self.app=PLUGIN.core.Engine(self.root/'state',[str(self.root)])
        self.contract={'columns':[{'name':'id'},{'name':'amount','type':'decimal'}]}
        self.replace=patch.object(PLUGIN,'engine',return_value=self.app);self.replace.start()
        class Context:
            def __init__(self):self.tools={};self.hooks={};self.commands={};self.calls=[]
            def register_tool(self,**kw):self.tools[kw['name']]=kw
            def register_hook(self,name,fn):self.hooks[name]=fn
            def register_command(self,name,fn,**kw):self.commands[name]=fn
            def dispatch_tool(self,name,args):self.calls.append((name,args));return self.tools[name]['handler'](args)
        self.ctx=Context();PLUGIN.register(self.ctx)

    def tearDown(self):self.replace.stop();self.temp.cleanup()

    def test_seven_tools_match_manifest_and_strict_schemas(self):
        self.assertEqual(len(self.ctx.tools),7)
        for name,data in self.ctx.tools.items():
            self.assertFalse(data['schema']['parameters']['additionalProperties'])
            self.assertIn(name,(ROOT/'plugin.yaml').read_text())

    def test_versions_are_consistent(self):
        import tomllib
        version=PLUGIN.core.VERSION
        self.assertEqual(json.loads((ROOT/'dashboard/manifest.json').read_text())['version'],version)
        self.assertEqual(tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version'],version)
        self.assertIn('version: "'+version+'"',(ROOT/'plugin.yaml').read_text())

    def test_native_dispatch_plain_english_summary_and_unknown_tool_refusal(self):
        result=json.loads(PLUGIN.dispatch('rowverdict_plan',{'source':str(self.file),'contract':self.contract}))
        self.assertTrue(result['ok']);self.assertIn('0 clean + 1 quarantined = 1',result['summary'])
        self.assertFalse(json.loads(PLUGIN.dispatch('unknown',{}))['ok'])

    def test_native_draft_review_requires_host_approval(self):
        draft=self.app.draft(str(self.file))
        directive=PLUGIN.before_export('rowverdict_review',{'draft_id':draft['draft_id']})
        self.assertEqual(directive['action'],'approve')
        self.assertIn('policy SHA256',directive['message'])
        self.assertEqual(self.app.get_draft(draft['draft_id'])['status'],'DRAFT')

    def test_replay_export_approval_card_binds_patch(self):
        parent=self.app.plan(str(self.file),self.contract)
        child=self.app.replay(parent['id'],patch=[{'row':2,'set':{'amount':'1'}}])
        directive=PLUGIN.before_export('rowverdict_export',{'plan_id':child['id']})
        self.assertEqual(directive['action'],'approve')
        self.assertIn(child['summary']['replay']['patch_sha256'],directive['message'])
        self.assertIn('audit.html',directive['message'])
        self.assertFalse((self.app.data_dir/'exports').exists())

    def test_stale_export_hook_blocks(self):
        run=self.app.plan(str(self.file),self.contract);self.file.write_text('id,amount\nb,1\n')
        self.assertEqual(PLUGIN.before_export('rowverdict_export',{'plan_id':run['id']})['action'],'block')
        self.assertIsNone(PLUGIN.before_export('unrelated',{}))

    def test_slash_inspect_and_plan_work_with_real_handlers(self):
        command=self.ctx.commands['rowverdict']
        self.assertIn('Inspected 1 records',command('inspect '+str(self.file)))
        output=command('plan '+json.dumps({'source':str(self.file),'contract':self.contract}))
        self.assertIn('0 clean + 1 quarantined',output)
        self.assertIn('persisted',command('status'))

    def test_slash_export_and_review_never_call_ungated_dispatch(self):
        for action in ('export','review'):
            output=self.ctx.commands['rowverdict'](action+' '+'a'*32)
            self.assertIn('Approval handoff prepared',output)
            self.assertIn('No files written',output)
        self.assertEqual(self.ctx.calls,[])
        self.assertFalse((self.app.data_dir/'exports').exists())

    def test_slash_draft_replay_invalid_json_and_legacy_status(self):
        command=self.ctx.commands['rowverdict']
        self.assertIn('DRAFT',command('draft '+str(self.file)))
        # Independent source for the explicit-contract path.
        other=self.root/'other.csv';other.write_text('id,amount\na,bad\n')
        run=self.app.plan(str(other),self.contract)
        output=command('replay '+json.dumps({'plan_id':run['id'],'patch':[{'row':2,'set':{'amount':'1'}}]}))
        self.assertIn('1 clean + 0 quarantined',output)
        self.assertIn(run['id'],command(run['id']))
        self.assertIn('Invalid arguments',command('plan {'))
