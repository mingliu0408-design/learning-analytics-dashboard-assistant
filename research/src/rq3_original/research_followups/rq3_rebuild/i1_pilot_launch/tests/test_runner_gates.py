from pathlib import Path
import copy
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME, load, sha, write_once
from utils.c4_rebuild.i1.policy import preflight,APPROVAL_VERSION,APPROVAL_SCHEMA
from research_followups.rq3_rebuild.i1_pilot_launch.run_pilot import main


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.c=self.root/'config.json';self.m=self.root/'manifest.json';self.s=self.root/'sources.json'
        self.c.write_bytes((HOME/'PILOT_CONFIGURATION_PROPOSED.json').read_bytes())
        self.m.write_bytes((HOME/'TASK_MANIFEST.json').read_bytes())
        p=ROOT/'utils/c4_rebuild/i1/policy.py'
        write_once(self.s,dict(schema_version='I1_SOURCE_MANIFEST_V1',files=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p.read_bytes()),bytes=p.stat().st_size)]))
        self.output=self.root/'new_run'
        self.a=self.root/'EXPLICITLY_ARTIFICIAL_APPROVAL.json'
        approval=dict(schema_version=APPROVAL_VERSION,status='AUTHORIZED',authorized_by='ARTIFICIAL TEST ONLY',
            authorized_at='2026-09-07T12:00:00+00:00',signature='ARTIFICIAL NOT A REAL AUTHOR SIGNATURE',
            scope='EXPOSED_SYNTHETIC_ENGINEERING_PILOT_ONLY',config_sha256=sha(self.c.read_bytes()),
            manifest_sha256=sha(self.m.read_bytes()),source_manifest_sha256=sha(self.s.read_bytes()),
            output_directory=str(self.output),resume_unknown_attempts=[],protocol_deviations=[])
        write_once(self.a,approval)
        self.args=['--config',str(self.c),'--manifest',str(self.m),'--source-manifest',str(self.s)]

    def test_default_prepare_does_not_construct_client(self):
        def forbidden(**kw):raise AssertionError('CLIENT MUST NOT BE CONSTRUCTED')
        result=main(self.args,transport_factory=forbidden)
        self.assertEqual(result['provider_calls'],0)

    def test_execute_without_external_approval_before_client(self):
        with self.assertRaises(PermissionError):main(self.args+['--execute','--output',str(self.output)],transport_factory=lambda **kw:self.fail('CLIENT'))

    def test_approval_schema_version_mismatch_before_client(self):
        a=load(self.a);a['schema_version']='WRONG_FILE_VERSION';self.a.write_text(json.dumps(a))
        with self.assertRaisesRegex(PermissionError,'APPROVAL_SCHEMA_VERSION'):
            main(self.args+['--execute','--output',str(self.output),'--approval',str(self.a)],transport_factory=lambda **kw:self.fail('CLIENT'))

    def test_config_schema_mismatch_before_client(self):
        c=load(self.c);c['role_contract_version']='WRONG';self.c.write_text(json.dumps(c))
        with self.assertRaisesRegex(ValueError,'CONFIG_SCHEMA'):
            main(self.args+['--execute','--output',str(self.output),'--approval',str(self.a)],transport_factory=lambda **kw:self.fail('CLIENT'))

    def test_modified_source_before_client(self):
        s=load(self.s);s['files'][0]['sha256']='0'*64;self.s.write_text(json.dumps(s))
        with self.assertRaisesRegex(ValueError,'SOURCE_HASH'):
            main(self.args+['--execute','--output',str(self.output),'--approval',str(self.a)],transport_factory=lambda **kw:self.fail('CLIENT'))

    def test_approval_hash_output_and_scope_bindings(self):
        original=load(self.a)
        for key,value in [('config_sha256','0'*64),('output_directory','/tmp/another'),('scope','REAL_STUDY'),('signature','')]:
            with self.subTest(key=key):
                a=copy.deepcopy(original);a[key]=value;self.a.write_text(json.dumps(a))
                with self.assertRaises(PermissionError):preflight(self.c,self.m,self.s,execute=True,approval_path=self.a,output=self.output)

    def test_execute_dispatch_mocked_after_same_shared_schema(self):
        called=[]
        class Mock:
            kind='MOCK'
            def close(self):called.append('closed')
        def factory(**kw):called.append(kw);return Mock()
        with patch('research_followups.rq3_rebuild.i1_pilot_launch.run_pilot.Orchestrator') as orchestrator:
            orchestrator.return_value.run.return_value=[]
            main(self.args+['--execute','--output',str(self.output),'--approval',str(self.a)],transport_factory=factory)
        self.assertEqual(called,[{'approved':True,'timeout':30},'closed'])
        self.assertEqual(len(list(self.output.glob('AUTHOR_APPROVAL_*.json'))),1)

    def test_nonempty_directory_not_overwritten(self):
        self.output.mkdir();(self.output/'keep').write_text('keep')
        with self.assertRaisesRegex(ValueError,'NEW_OUTPUT'):
            main(self.args+['--execute','--output',str(self.output),'--approval',str(self.a)],transport_factory=lambda **kw:self.fail('CLIENT'))
        self.assertEqual((self.output/'keep').read_text(),'keep')


if __name__=='__main__':unittest.main(verbosity=2)
