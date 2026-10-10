"""Bounded state-machine tests using independent synthetic mock responses only."""
from copy import deepcopy
from decimal import Decimal
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from i5_common import *
import run_i5 as run
from utils.c4_rebuild.i1.transport import TransportFailure


def plan(p):
    goal = p['planner']['bridge']['planner_input']['goals'][0]
    return dict(plan_id='I5_MOCK_ONLY_NEW_PLAN', goal_id=goal['goal_id'], goal=goal['text'],
        evidence_refs=['current-request'], continues_plan_id=None, brief_rationale='Independent mock control.',
        actions=[dict(step_id='MOCK_STEP',task_id='MOCK_TASK',kind='TASK',action='Restate the current request.',
            estimated_duration=dict(value=5,unit='minutes',origin='MODEL_ESTIMATE',evidence_refs=[],uncertainty='Mock estimate.'),
            resource_ids=[],dependencies=[],schedule=None,completion_check='Restate the request.',
            evidence_refs=['current-request'],brief_rationale='Mock only; never an actual I5 response.')])


def raw(value, model='gpt-4o-mini-2024-07-18', text=None):
    return dict(model=model, choices=[dict(finish_reason='stop',message=dict(content=canonical(value).decode() if text is None else text,refusal=None))],
        usage=dict(prompt_tokens=100,completion_tokens=100,total_tokens=200),id='MOCK_ONLY')


class Clock:
    def __init__(self): self.t = 0.; self.waits = []
    def __call__(self): return self.t
    def sleep(self, value): self.waits.append(value); self.t += value


class Mock:
    kind = 'MOCK_ONLY_NO_PROVIDER'
    def __init__(self, script=None): self.calls=[]; self.script=script
    def send(self, payload):
        self.calls.append(deepcopy(payload))
        if self.script: return self.script(payload, len(self.calls))
        body=json.loads(payload['messages'][1]['content'])
        if 'accepted_plan' in body:
            return raw(dict(answer='MOCK ONLY. No human assessment.',cited_evidence_ids=[],plan_fields=body['accepted_plan']))
        row = next(r for r in load_slots() if sha(run.REPAIR.candidate_payload(prepared(r), settings()['generation_roles']['CANDIDATE'])) == sha(payload))
        return raw(plan(prepared(row)))


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='i5_offline_mock_')
        self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name)/'exclusive'
        self.out.mkdir();self.clock=Clock();self.config=settings();self.row=load_slots()[0];self.p=prepared(self.row)

    def runner(self, mock=None, guard=lambda:None):
        self.mock=mock or Mock()
        return run.LimitedRunner(self.out,self.config,self.mock,guard,self.clock,self.clock.sleep)

    def execute(self,mock=None,guard=lambda:None):
        r=self.runner(mock,guard)
        with contextlib.redirect_stdout(io.StringIO()): result=r.execute()
        return r,result

    def candidate(self,r,phase='INITIAL',value=None):
        payload=run.REPAIR.candidate_payload(self.p,self.config['generation_roles']['CANDIDATE'])
        with contextlib.redirect_stdout(io.StringIO()):
            return r.call(self.row,phase,payload,lambda x:run.REPAIR.candidate_issues(self.p['planner']['bridge'],x))

    def test_exact_five_initial_hashes_and_full_snapshot(self):
        bs=load(HERE/'INPUT_BINDINGS.json')
        self.assertEqual([r['logical'] for r in bs],SLOTS)
        for b in bs:
            p=prepared(b);req=run.REPAIR.candidate_payload(p,self.config['generation_roles']['CANDIDATE'])
            self.assertEqual(sha(req),b['proposed_initial_request_sha256'])
            self.assertEqual(sha(p),b['prepared_sha256'])
            self.assertEqual(sha(p['planner']['bridge']),b['frozen_input_sha256'])

    def test_first_pass_zero_correction_five_changed_finals(self):
        r,s=self.execute()
        self.assertEqual(s['phase_counts'],dict(INITIAL=5,CORRECTION=0,FINAL=5))
        self.assertEqual(s['status'],'BOUNDED_EXECUTION_COMPLETE')
        self.assertTrue(all(x['final_eligible'] and x['final_status']=='ACCEPTED' for x in s['slots']))

    def test_approval_to_exclusive_mock_execution(self):
        b=run.binding();a=load(HERE/'DIRECT_APPROVAL.json')
        out=Path(self.tmp.name)/'approved_run'
        run.begin_output(out,dict(status='PASS',binding=b),a)
        self.assertTrue((out/'PREFLIGHT.json').exists())
        with contextlib.redirect_stdout(io.StringIO()):
            s=run.LimitedRunner(out,self.config,Mock(),clock=self.clock,sleep=self.clock.sleep).execute()
        self.assertEqual(s['total_physical_calls'],10)

    def test_old_i1_approval_schema_rejected(self):
        a=load(HERE/'DIRECT_APPROVAL.json');a['version']='I1_EXECUTION_APPROVAL_V1'
        with self.assertRaisesRegex(ValueError,'I5_APPROVAL_SCHEMA'):run.validate_approval(a,run.binding())

    def test_approval_wrong_binding_rejected(self):
        a=load(HERE/'DIRECT_APPROVAL.json');a['binding']['limits']['caps']['TOTAL']=16
        with self.assertRaisesRegex(ValueError,'I5_APPROVAL_BINDING'):run.validate_approval(a,run.binding())

    def test_no_implicit_resume(self):
        a=load(HERE/'DIRECT_APPROVAL.json');b=run.binding()
        with self.assertRaises(FileExistsError):run.begin_output(self.out,dict(status='PASS',binding=b),a)

    def test_no_client_on_failed_preflight(self):
        with patch.object(run,'validate_preflight',side_effect=ValueError('OFFLINE_GATE')),patch.object(run,'ExactOpenAITransport') as client:
            with self.assertRaises(ValueError):run.main()
            client.assert_not_called()

    def invalid_script(self,second_valid=False):
        def script(payload,n):
            body=json.loads(payload['messages'][1]['content'])
            if 'accepted_plan' in body:
                return raw(dict(answer='MOCK FINAL',cited_evidence_ids=[],plan_fields=body['accepted_plan']))
            goal=body['encoded_planning_fields']['goals'][0]
            p=plan(self.p);p.update(goal_id=goal['goal_id'],goal=goal['text'])
            if not second_valid or 'previous_candidate' not in body:p['evidence_refs']=[]
            return raw(p)
        return script

    def test_second_invalid_has_no_third_and_no_final(self):
        r,s=self.execute(Mock(self.invalid_script()))
        self.assertEqual(s['phase_counts'],dict(INITIAL=1,CORRECTION=1,FINAL=0))
        self.assertEqual(s['stop_reason'],'CANDIDATE_FAILED_AFTER_ALLOWED_ATTEMPTS')
        self.assertEqual(s['slots'][0]['final_status'],'NOT_CALLED_NO_ACCEPTED_PLAN')
        self.assertTrue(all(x['candidate_status']=='NOT_ATTEMPTED' for x in s['slots'][1:]))

    def test_maximum_fifteen_calls(self):
        r,s=self.execute(Mock(self.invalid_script(True)))
        self.assertEqual(s['phase_counts'],dict(INITIAL=5,CORRECTION=5,FINAL=5))
        self.assertEqual(len(r.starts),15)

    def test_new_output_and_exact_feedback_never_old_preview(self):
        r,s=self.execute(Mock(self.invalid_script(True)))
        starts=[x for x in r.starts if x['phase']=='CORRECTION']
        for start,row in zip(starts,load_slots()):
            body=json.loads(start['request']['messages'][1]['content'])
            prior=load(self.out/'attempts'/(start['correction_of']+'.outcome.json'))
            self.assertEqual(body['previous_candidate'],prior['value'])
            self.assertEqual(body['concrete_checker_issues'],prior['issues'])
            self.assertEqual(body['previous_candidate']['plan_id'],'I5_MOCK_ONLY_NEW_PLAN')
            old=load(I3/row['proposed_initial_request'].replace('.1.json','.2.json'))
            self.assertNotEqual(start['request_sha256'],sha(old))

    def test_raw_invalid_json_correction_retains_exact_failed_text(self):
        r,s=self.execute(Mock(lambda payload,n:raw(None,text='{"fresh_bad": INVALID_NEW_MOCK}')))
        self.assertEqual(s['phase_counts'],dict(INITIAL=1,CORRECTION=1,FINAL=0))
        b=json.loads(self.mock.calls[1]['messages'][1]['content'])
        self.assertEqual(b['raw_failed_response_text'],'{"fresh_bad": INVALID_NEW_MOCK}')
        self.assertNotIn('previous_candidate',b)
        self.assertEqual(b['checker_feedback_details'][0]['parse_error']['type'],'JSONDecodeError')
        self.assertIn('candidate_contract',b)

    def test_outer_schema_null_uses_raw_branch_no_invented_candidate(self):
        r,s=self.execute(Mock(lambda p,n:raw(None)))
        b=json.loads(self.mock.calls[1]['messages'][1]['content'])
        self.assertEqual(b['raw_failed_response_text'],'null');self.assertNotIn('previous_candidate',b)
        self.assertEqual(b['concrete_checker_issues'],['$:TYPE'])

    def test_parsable_schema_failure_uses_exact_i3_helper(self):
        r,s=self.execute(Mock(lambda p,n:raw({'new_field':'MOCK'})))
        b=json.loads(self.mock.calls[1]['messages'][1]['content'])
        self.assertEqual(b['previous_candidate'],{'new_field':'MOCK'})
        self.assertEqual(b['concrete_checker_issues'],['$:FIELD_SET'])

    def test_final_invalid_never_retried(self):
        default=Mock()
        def script(p,n):
            if 'accepted_plan' in json.loads(p['messages'][1]['content']):return raw(None,text='BAD_FINAL')
            return default.send(p)
        r,s=self.execute(Mock(script))
        self.assertEqual(s['phase_counts'],dict(INITIAL=1,CORRECTION=0,FINAL=1))
        self.assertEqual(s['stop_reason'],'FINAL_FAILED_NO_RETRY')
        self.assertEqual(s['slots'][0]['final_status'],'INVALID_JSON')

    def test_final_plan_must_be_identical_to_accepted(self):
        r=self.runner();c=self.candidate(r);wrong=deepcopy(c['value']);wrong['plan_id']='WRONG'
        p=run.final_payload(self.p,self.config['generation_roles']['FINAL'],wrong,False)
        with self.assertRaisesRegex(run.StopRun,'FINAL_NO_NEW_ACCEPTED_PLAN'):r.call(self.row,'FINAL',p,final_plan=wrong,validator=lambda v:[])
        self.assertEqual(len(self.mock.calls),1)

    def test_unchanged_fallback_not_eligible(self):
        r=self.runner();c=self.candidate(r)
        p=run.final_payload(self.p,self.config['generation_roles']['FINAL'],None,True)
        with self.assertRaisesRegex(run.StopRun,'FINAL_INPUT_UNCHANGED_OR_RENDERER_DRIFT'):r.call(self.row,'FINAL',p,final_plan=c['value'],validator=lambda v:[])
        self.assertEqual(len(self.mock.calls),1)

    def test_duplicate_initial_no_redispatch(self):
        r=self.runner();self.candidate(r)
        with self.assertRaisesRegex(run.StopRun,'SLOT_ATTEMPT_CEILING'):self.candidate(r)
        self.assertEqual(len(self.mock.calls),1)

    def test_final_duplicate_no_retry(self):
        r=self.runner();c=self.candidate(r);p=run.final_payload(self.p,self.config['generation_roles']['FINAL'],c['value'],False)
        with contextlib.redirect_stdout(io.StringIO()):r.call(self.row,'FINAL',p,validator=lambda v:[],final_plan=c['value'])
        with self.assertRaisesRegex(run.StopRun,'SLOT_ATTEMPT_CEILING'):r.call(self.row,'FINAL',p,validator=lambda v:[],final_plan=c['value'])
        self.assertEqual(len(self.mock.calls),2)

    def test_global_ceiling_prevents_transport(self):
        r=self.runner();r.starts=[dict(logical='PREEXISTING_MOCK',phase='INITIAL') for _ in range(15)]
        with self.assertRaisesRegex(run.StopRun,'TOTAL_PHYSICAL_CALL_CEILING'):self.candidate(r)
        self.assertEqual(len(self.mock.calls),0)

    def test_phase_ceiling_prevents_transport(self):
        r=self.runner();r.starts=[dict(logical='PREEXISTING_MOCK',phase='INITIAL') for _ in range(5)]
        with self.assertRaisesRegex(run.StopRun,'ROLE_CALL_CEILING'):self.candidate(r)
        self.assertEqual(len(self.mock.calls),0)

    def test_budget_reservation_is_frozen_convention(self):
        p=run.REPAIR.candidate_payload(self.p,self.config['generation_roles']['CANDIDATE'])
        units,amount=run.estimate(p,self.config)
        self.assertEqual(units,len(canonical(p))+256)
        self.assertEqual(amount,(Decimal(units)*Decimal('.15')+Decimal(2048)*Decimal('.6'))/Decimal(1000000))

    def test_exhausted_budget_no_transport(self):
        r=self.runner();r.starts=[dict(logical='PREEXISTING_MOCK',phase='FINAL',attempt_id='prior',reserved_estimate_usd='.2499')]
        with self.assertRaisesRegex(run.StopRun,'ESTIMATED_BUDGET_EXHAUSTED'):self.candidate(r)
        self.assertEqual(len(self.mock.calls),0)

    def test_unknown_usage_does_not_release_reservation(self):
        r=self.runner();r.starts=[dict(logical='PREEXISTING_MOCK',phase='FINAL',attempt_id='prior',reserved_estimate_usd='.2499')]
        r.outcomes=[dict(attempt_id='prior',usage=None)]
        with self.assertRaisesRegex(run.StopRun,'ESTIMATED_BUDGET_EXHAUSTED'):self.candidate(r)
        self.assertIsNone(run.usage_estimate(None,self.config))

    def test_returned_usage_exceeding_reservation_can_stop(self):
        def script(p,n):
            v=raw(plan(self.p));v['usage']['prompt_tokens']=2000000;return v
        r,s=self.execute(Mock(script))
        self.assertEqual(s['stop_reason'],'OBSERVED_USAGE_EXCEEDS_ESTIMATED_BUDGET')
        self.assertEqual(len(self.mock.calls),1)

    def test_actual_correction_input_byte_cap_before_send(self):
        r,s=self.execute(Mock(lambda p,n:raw(None,text='X'*40000)))
        self.assertEqual(s['stop_reason'],'REQUEST_INPUT_BOUND_EXCEEDED')
        self.assertEqual(len(self.mock.calls),1)

    def test_monotonic_pacing_includes_corrections(self):
        r,s=self.execute(Mock(self.invalid_script(True)))
        times=[o['monotonic_start'] for o in r.outcomes]
        self.assertTrue(all(b-a>=2 for a,b in zip(times,times[1:])))
        self.assertEqual(len(times),15)

    def test_source_drift_stops_before_first_send(self):
        def guard():raise ValueError('CHANGED_FILE')
        r,s=self.execute(guard=guard)
        self.assertEqual(s['stop_reason'],'SOURCE_OR_HARNESS_DRIFT');self.assertEqual(len(self.mock.calls),0)

    def test_source_drift_between_candidate_and_final(self):
        count=[0]
        def guard():
            count[0]+=1
            if count[0]>1:raise ValueError('CHANGED_FILE')
        r,s=self.execute(guard=guard)
        self.assertEqual(s['stop_reason'],'SOURCE_OR_HARNESS_DRIFT');self.assertEqual(len(self.mock.calls),1)

    def test_all_transport_failure_categories_stop_without_correction(self):
        for category in sorted(run.FATAL-{'RETURNED_MODEL_MISMATCH'}):
            with self.subTest(category=category):
                out=Path(self.tmp.name)/category;out.mkdir()
                def script(p,n):raise TransportFailure(category)
                m=Mock(script)
                with contextlib.redirect_stdout(io.StringIO()):s=run.LimitedRunner(out,self.config,m,clock=self.clock,sleep=self.clock.sleep).execute()
                self.assertEqual(s['stop_reason'],category);self.assertEqual(len(m.calls),1)

    def test_unknown_completion_keeps_raw_and_reservation(self):
        def script(p,n):raise TimeoutError('MOCK')
        r,s=self.execute(Mock(script))
        self.assertEqual(s['stop_reason'],'UNKNOWN_COMPLETION');self.assertEqual(len(self.mock.calls),1)
        self.assertEqual(r.outcomes[0]['completion'],'UNKNOWN');self.assertIsNone(r.outcomes[0]['usage'])
        self.assertTrue((self.out/'attempts/01_initial.start.json').exists())

    def test_model_mismatch_stops(self):
        r,s=self.execute(Mock(lambda p,n:raw(plan(self.p),model='UNAPPROVED_MODEL')))
        self.assertEqual(s['stop_reason'],'RETURNED_MODEL_MISMATCH');self.assertEqual(len(self.mock.calls),1)

    def test_wrong_scope_or_unapproved_slot_no_calls(self):
        r=self.runner();row=deepcopy(self.row);row['logical']='I0-SYN-09:S5_FULL'
        with self.assertRaisesRegex(run.StopRun,'ROLE_OR_SLOT_NOT_AUTHORIZED'):r.call(row,'INITIAL',{},lambda v:[])
        self.assertEqual(len(self.mock.calls),0)

    def test_mutated_source_binding_no_calls(self):
        r=self.runner();row=deepcopy(self.row);row['frozen_input_sha256']='X'
        with self.assertRaisesRegex(run.StopRun,'SLOT_SOURCE_BINDING_CHANGED'):r.call(row,'INITIAL',{},lambda v:[])

    def test_original_final_id_and_plan_checks(self):
        p=plan(self.p);value=dict(answer='mock',cited_evidence_ids=['fake'],plan_fields=p)
        self.assertIn('CITATION_ID_NOT_RETAINED',run.final_errors(value,[],p))
        value.update(cited_evidence_ids=[],plan_fields=None)
        self.assertIn('FINAL_ADMIN_PLAN_CHANGED',run.final_errors(value,[],p))

    def test_no_module_or_execution_entrypoint_imported(self):
        import sys
        self.assertNotIn('utils.c4_rebuild.i1.worker',sys.modules)
        self.assertNotIn('utils.c4_rebuild.i1.orchestrator',sys.modules)
        self.assertNotIn('openai',sys.modules)


if __name__=='__main__':unittest.main(verbosity=2)
