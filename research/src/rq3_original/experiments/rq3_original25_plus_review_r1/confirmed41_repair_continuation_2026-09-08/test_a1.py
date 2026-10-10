"""Offline six-input replay and independent negative engineering controls."""
from a1_common import *
from copy import deepcopy
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import interface_a1 as repair
from parent_ledger import ParentLedger,ContinuationRunner
from utils.c4_rebuild.i1.durable import StopRun
from utils.c4_rebuild.i1.transport import TransportFailure

base.offline()

class Clock:
    def __init__(self):self.t=0.
    def __call__(self):return self.t
    def sleep(self,n):self.t+=n

class Mock:
    kind='INDEPENDENT_ENGINEERING_MOCK_NO_PROVIDER'
    def __init__(self,behavior='valid'):self.calls=[];self.behavior=behavior
    def send(self,p):
        self.calls.append(deepcopy(p))
        if self.behavior=='unknown':raise TransportFailure('UNKNOWN_COMPLETION',{'type':'MOCK_ONLY'})
        value={'answer':'ENGINEERING MOCK ONLY','cited_evidence_ids':[]}
        text=json.dumps(value) if self.behavior=='valid' or (self.behavior=='repair' and len(self.calls)==2) else 'not JSON'
        return dict(model=p['model'],choices=[dict(finish_reason='stop',message=dict(content=text))],usage=dict(prompt_tokens=10,completion_tokens=10),id='MOCK_ONLY')

def codes(report):return {i['code'] if isinstance(i,dict) else i.rsplit(':',1)[-1] for i in report}

def mock_plan(p):
    g=p['planner']['bridge']['planner_input']['goals'][0]
    return dict(plan_id='A1_ENGINEERING_ONLY',goal_id=g['goal_id'],goal=g['text'],evidence_refs=['current-request'],continues_plan_id=None,
        brief_rationale='Independent engineering fixture, never a research response.',actions=[dict(step_id='STEP_ONE',task_id='TASK_ONE',kind='TASK',
        action='Restate the current request.',estimated_duration=dict(value=5,unit='minutes',origin='MODEL_ESTIMATE',evidence_refs=[],uncertainty='Mock estimate.'),
        resource_ids=[],dependencies=[],schedule=None,completion_check='Restate the request.',evidence_refs=['current-request'],brief_rationale='Mock only.')])

class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved=load(HERE/'audit/REPLAYED_INPUTS.json');cls.tasks={t['task_id']:t for t in rows(DATA/'runtime_tasks.jsonl')};cls.binding=load(DATA/'BINDINGS.json')
    def fixture(self,slot='task-c0aa4f8d44d5:S5_FULL'):
        p=deepcopy(self.saved[slot]['prepared']);t=self.tasks[slot.split(':')[0]]
        api=repair.planner_for(base.snapshot_for(t,self.binding),p['final_request']['runtime_input']['evidence']['selected_evidence'])
        return p,api
    def test_general_intent_positive_and_negative(self):
        for q in ('What could I do next?','How can I best manage my reading?','What can I try first?','How should I organize this work?'):
            self.assertEqual(repair.resolve_intent(q)['mode'],'ORDINARY_ACTION_ADVICE')
        for q in ('What is this?','Tell me the assessment result.','What could I do next Monday at 10am?','What could I do in these calendar time slots?'):
            self.assertNotEqual(repair.resolve_intent(q)['mode'],'ORDINARY_ACTION_ADVICE')
        explicit='EXPLICIT_SCHEDULE'
        self.assertEqual(repair.resolve_intent('What could I do next?',explicit),base.interfaces.resolve_intent('What could I do next?',explicit))
    def test_all_six_ready_and_source_fields_unchanged(self):
        for slot in policy()['replacement_slots']:
            with self.subTest(slot=slot):
                p,api=self.fixture(slot);before=deepcopy(p['planner']['bridge']['source_input'])
                self.assertEqual(api.plan_kind(p['planner']['bridge'])['kind'],'ORDINARY_ACTION_ADVICE')
                self.assertEqual(before,p['planner']['bridge']['source_input'])
    def test_metadata_ids_do_not_change_payload(self):
        p,api=self.fixture();cfg=load(DATA/'CONFIG_PROPOSED.json')['generation_roles']['CANDIDATE'];old=api.candidate_payload(p,cfg)
        p.update(task_id='UNREAD_ENGINEERING_SENTINEL',family_id='UNREAD',expected_capabilities=['FORBIDDEN_GOLD_SENTINEL'])
        self.assertEqual(old,api.candidate_payload(p,cfg));self.assertNotIn('SENTINEL',str(old))
    def test_advice_budget_roles_completion_and_evidence_still_checked(self):
        p,api=self.fixture();b=p['planner']['bridge'];c=mock_plan(p)
        self.assertEqual(api.candidate_issues(b,c),[])
        s=deepcopy(b['source_input']);s['base_input']['hard_constraints']['budget'].update(required=True,minutes=4)
        self.assertIn('BUDGET_EXCEEDED',codes(api.candidate_issues(repair.api.project(s),c)))
        x=deepcopy(c);x['actions'][0]['resource_ids']=['current-request']
        self.assertIn('RESOURCE_NOT_PERMITTED',codes(api.candidate_issues(b,x)))
        x=deepcopy(c);x['actions'][0]['evidence_refs']=['FABRICATED']
        self.assertIn('EVIDENCE_ID_MISSING',codes(api.candidate_issues(b,x)))
        s=deepcopy(b['source_input']);s['base_input']['completed_tasks']=[dict(task_id='TASK_ONE',evidence_refs=['current-request'])]
        self.assertIn('COMPLETED_TASK_REPEATED',codes(api.candidate_issues(repair.api.project(s),c)))
        x=deepcopy(c);x['actions'][0]['estimated_duration'].update(value=None,origin='UNKNOWN')
        self.assertIn('DURATION_UNKNOWN',codes(api.candidate_issues(b,x)))
    def test_declared_temporal_exception_is_not_generic(self):
        p,api=self.fixture();bridge=p['planner']['bridge'];src=bridge['source_input']
        for mutation,expected in [('value','MISSING_TIME'),('fact_type','MISSING_TIME'),('version','MISSING_TIME'),('scope','SOURCE_SCOPE_MISMATCH'),('future','SOURCE_FROM_FUTURE')]:
            with self.subTest(mutation=mutation):
                s=deepcopy(src);f=next(f for f in s['base_input']['facts'] if f['kind']=='COURSE_RAG')
                if mutation=='value':f['value']='Unbound course body'
                elif mutation=='fact_type':f['fact_type']='CURRENT_YEAR_POLICY'
                elif mutation=='version':f['source_ref']['version']='WRONG_VERSION'
                elif mutation=='scope':f['source_ref']['course_id']='OTHER_COURSE'
                elif mutation=='future':f['source_ref']['observed_at']='2099-01-01T00:00:00Z'
                result=api.validate_bridge(repair.api.project(s));self.assertNotEqual(result['outcome'],'PASSED_ENCODED_CHECKS')
                self.assertIn(expected,codes(result['issues']))
    def test_withdrawn_and_scheduled_use_not_exempted(self):
        p,api=self.fixture();s=deepcopy(p['planner']['bridge']['source_input'])
        s['task_request']={'mode':'EXPLICIT_SCHEDULE','basis':'EXPLICIT_TASK_REQUEST_FIELD','source_quote':s['base_input']['context']['query']}
        self.assertNotEqual(api.validate_bridge(repair.api.project(s))['outcome'],'PASSED_ENCODED_CHECKS')
        p,api=self.fixture();b=p['planner']['bridge'];f=next(f for f in b['planner_input']['facts'] if f['kind']=='COURSE_RAG')
        report=repair.api.p1v.p0.Report()
        api.source_check(b)(f['source_ref'],'$.course',b['planner_input'],report,at='2099-01-01T00:00:00Z')
        self.assertIn('MISSING_TIME',codes(report.issues))
        s=deepcopy(b['source_input']);f=next(f for f in s['base_input']['facts'] if f['kind']=='COURSE_RAG');f['source_ref']['access']='DENIED'
        self.assertIn('SOURCE_ACCESS_DENIED',codes(api.validate_bridge(repair.api.project(s))['issues']))

class ContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.parent=ParentLedger()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name)/'fresh';self.clock=Clock();self.mock=Mock()
        self.config=load(DATA/'CONFIG_PROPOSED.json');self.config.update(initial_slot_ceilings=policy()['new_initial_slot_ceilings'],aggregate_attempt_ceiling=282,proposed_money_ceiling_usd=10.,uncached_usd_per_million=policy()['uncached_usd_per_million'])
        self.logical='original-01:S0_PAGE_ONLY:FINAL';self.payload=deepcopy(self.parent.starts[self.logical][0]['request'])
    def runner(self):
        r=ContinuationRunner(self.out,self.config,dict(test='INDEPENDENT_ENGINEERING_ONLY'),self.mock,self.parent,clock=self.clock,sleep=self.clock.sleep)
        self.addCleanup(r.close);return r
    def test_accepted_is_reused_with_exact_receipts_no_call(self):
        r=self.runner();out=r.perform(self.logical,'FINAL',self.payload)
        self.assertEqual(out['status'],'ACCEPTED');self.assertEqual(self.mock.calls,[])
        self.assertEqual(list((self.out/'attempts').glob('*')),[])
        self.assertEqual(len(rows(self.out/'PARENT_REUSE_RECEIPTS.jsonl')),1)
    def test_any_changed_accepted_outside_six_stops(self):
        self.payload['messages'][0]['content']+=' ENGINEERING DIFFERENCE'
        with self.assertRaisesRegex(StopRun,'ACCEPTED_PARENT_RESEND_FORBIDDEN'):self.runner().perform(self.logical,'FINAL',self.payload)
        self.assertEqual(self.mock.calls,[])
    def test_parent_payload_and_receipt_tampering_rejected(self):
        self.payload['max_tokens']=100
        with self.assertRaises(AssertionError):self.parent.accepted(self.logical,'FINAL',self.payload)
    def test_six_replacements_only_one_final_no_structural_retry(self):
        logical=policy()['replacement_slots'][0]+':FINAL';payload=deepcopy(self.parent.starts[logical][0]['request']);payload['messages'][0]['content']+=' ENGINEERING DIFFERENCE'
        self.mock=Mock('invalid');r=self.runner();res=r.perform(logical,'FINAL',payload)
        self.assertEqual(res['status'],'INVALID_JSON');self.assertEqual(len(self.mock.calls),1)
        self.assertEqual(r.perform(logical,'FINAL',payload),res);self.assertEqual(len(self.mock.calls),1)
    def test_unique_parent_unknown_exact_payload_one_new_attempt(self):
        logical=policy()['parent_unknown_authorizations'][0]['logical'];payload=self.parent.starts[logical][0]['request'];r=self.runner()
        res=r.perform(logical,'FINAL',payload);self.assertEqual(res['status'],'ACCEPTED');self.assertEqual(len(self.mock.calls),1)
        self.assertEqual(r.perform(logical,'FINAL',payload),res);self.assertEqual(len(self.mock.calls),1)
        self.assertEqual(self.parent.unknown_permission(logical,payload)['cumulative_slot_attempt'],2)
    def test_changed_unknown_payload_rejected(self):
        logical=policy()['parent_unknown_authorizations'][0]['logical'];payload=deepcopy(self.parent.starts[logical][0]['request']);payload['max_tokens']=100
        with self.assertRaisesRegex(StopRun,'IDENTITY_MISMATCH'):self.runner().perform(logical,'FINAL',payload)
        self.assertEqual(self.mock.calls,[])
    def test_new_unknown_on_same_attempt_name_stops_and_never_retries(self):
        logical=policy()['parent_unknown_authorizations'][0]['logical'];payload=self.parent.starts[logical][0]['request'];self.mock=Mock('unknown');r=self.runner()
        for _ in range(2):
            with self.assertRaisesRegex(StopRun,'UNKNOWN_COMPLETION_REQUIRES_EXPLICIT_HANDLING'):r.perform(logical,'FINAL',payload)
        self.assertEqual(len(self.mock.calls),1);self.assertEqual(r.unknown_authorizations,set())
    def test_ordinary_unexecuted_slot_max_two_and_serial_interval(self):
        self.mock=Mock('repair');r=self.runner();res=r.perform('ENGINEERING_NEW:FINAL','FINAL',self.payload)
        self.assertEqual(res['status'],'ACCEPTED');self.assertEqual(len(self.mock.calls),2)
        starts=sorted((load(p) for p in (self.out/'attempts').glob('*.start.json')),key=lambda s:s['attempt'])
        self.assertGreaterEqual(starts[1]['monotonic_start']-starts[0]['monotonic_start'],2)
    def test_cumulative_budget_blocks_before_transport(self):
        r=self.runner()
        with patch.object(self.parent,'budget_debit',10.):
            with self.assertRaisesRegex(StopRun,'CUMULATIVE_MONEY_CEILING'):r.perform('ENGINEERING_NEW:FINAL','FINAL',self.payload)
        self.assertEqual(self.mock.calls,[])
    def test_cumulative_physical_and_role_caps_block(self):
        r=self.runner();r.policy=dict(r.policy,cumulative_physical_ceiling=256)
        with self.assertRaisesRegex(StopRun,'CUMULATIVE_PHYSICAL_CEILING'):r.perform('ENGINEERING_NEW:FINAL','FINAL',self.payload)
        r.policy=policy();r.config['initial_slot_ceilings']['FINAL']=0
        with self.assertRaisesRegex(StopRun,'ROLE_LOGICAL_SLOT_CEILING'):r.perform('ENGINEERING_NEW:FINAL','FINAL',self.payload)
        self.assertEqual(self.mock.calls,[])
    def test_existing_approval_loader_accepts_exact_new_binding_rejects_old(self):
        a=load(PARENT/'EXECUTION_APPROVAL.json');old=deepcopy(a['binding']);ident=dict(old,interface_version=repair.VERSION,parent_ledger_sha256=self.parent.identity)
        a['binding']=ident;a['output_directory']=str(self.out)
        ids,c=legacy.approve(a,ident,load(DATA/'RUN_MANIFEST.json'),self.config,self.out)
        self.assertEqual(len(ids),41);self.assertEqual(c['proposed_money_ceiling_usd'],10)
        a['binding']=old
        with self.assertRaises(PermissionError):legacy.approve(a,ident,load(DATA/'RUN_MANIFEST.json'),self.config,self.out)
    def test_stop_before_new_final_preserves_168_and_all_246_statuses(self):
        from export_continuation import merged_slots
        self.runner();rs,summary,_,_=merged_slots(self.parent,self.out)
        self.assertEqual(len(rs),246);self.assertEqual(sum(r['answer'] is not None for r in rs),168)
        self.assertEqual(sum(r['status']=='UNKNOWN_COMPLETION' for r in rs),1)
        self.assertEqual(summary['physical_calls'],0)
        eligible=[r for r in rs if r['declared_slot_key'] in policy()['replacement_slots']]
        self.assertTrue(all(r['status']=='NOT_EXECUTED' and r['parent_status']=='ACCEPTED' and r['parent_answer_sha256'] for r in eligible))
    def test_accepted_resend_does_not_erase_parent_unknown_in_export(self):
        from export_continuation import merged_slots
        logical=policy()['parent_unknown_authorizations'][0]['logical'];r=self.runner()
        r.perform(logical,'FINAL',self.parent.starts[logical][0]['request'])
        rs,summary,_,_=merged_slots(self.parent,self.out)
        item=next(x for x in rs if x['declared_slot_key']+':FINAL'==logical)
        self.assertEqual(item['status'],'ACCEPTED');self.assertEqual(item['parent_status'],'UNKNOWN_COMPLETION')
        self.assertEqual(item['answer'],'ENGINEERING MOCK ONLY');self.assertEqual(summary['physical_calls'],1)
    def test_parent_all_bytes_preserved_after_mock_work(self):
        r=self.runner();r.perform(self.logical,'FINAL',self.payload)
        self.assertEqual(ParentLedger().identity,self.parent.identity)

if __name__=='__main__':unittest.main(verbosity=2)
