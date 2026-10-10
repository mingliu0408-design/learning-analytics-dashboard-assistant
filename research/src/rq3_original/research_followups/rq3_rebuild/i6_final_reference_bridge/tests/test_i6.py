"""Actual-byte regression plus explicitly synthetic negative/mock controls."""
from copy import deepcopy
import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from i6_common import *
import run_i6 as run
import final_reference_v1 as final
from utils.c4_rebuild.i1.renderer import final_payload as old_final
from utils.c4_rebuild.i1.schemas import errors, final_errors, strict_schema_check
from utils.c4_rebuild.i1.durable import parse_response
from utils.c4_rebuild.i1.transport import TransportFailure
from test_harness import plan, raw, Mock, Clock

class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.p=prepared(load_slots()[0]);self.c=run.reused_candidate()['candidate']
        self.cfg=settings()['generation_roles']['FINAL'];self.ids=self.p['trace']['retained_evidence_ids']
    def value(self,ids=None):
        return dict(answer='SYNTHETIC CONTROL ONLY: conditional general advice.',cited_evidence_ids=[] if ids is None else ids,plan_fields=deepcopy(self.c))
    def test_actual_i5_failure_still_rejected_bytes_unchanged(self):
        prefix=HERE/'historical_i5/live/attempts';before=(prefix/'01_final.raw.json').read_bytes()
        status,value,issues=parse_response(load(prefix/'01_final.raw.json'),load(prefix/'01_final.start.json')['request'],
            lambda v:final_errors(v,self.ids,self.c))
        self.assertEqual((status,issues),('ENCODED_CHECK',['CITATION_ID_NOT_RETAINED']))
        self.assertEqual(value['cited_evidence_ids'],['current-request'])
        self.assertEqual(before,(I5/'live/attempts/01_final.raw.json').read_bytes())
        self.assertEqual(sha(before),load(HERE/'OLD_FAILURE_REPLAY.json')['raw_file_sha256'])
    def test_current_request_unknown_another_mode_nonretained_rejected(self):
        other=prepared(load_slots()[1])['trace']['retained_evidence_ids'][-1]
        self.assertNotIn(other,self.ids)
        wire=final.final_payload(self.p,self.cfg,self.c)['response_format']['json_schema']['schema']
        for cited in ('current-request','SYNTHETIC_UNKNOWN_ID',other,'page:SYNTHETIC_NONRETAINED'):
            with self.subTest(cited=cited):
                self.assertIn('CITATION_ID_NOT_RETAINED',final_errors(self.value([cited]),self.ids,self.c))
                self.assertTrue(errors(self.value([cited]),wire))
    def test_genuine_retained_id_permitted(self):
        self.assertEqual(final_errors(self.value(self.ids),self.ids,self.c),[])
        wire=final.final_payload(self.p,self.cfg,self.c)['response_format']['json_schema']['schema']
        self.assertEqual(errors(self.value(self.ids),wire),[])
    def test_empty_valid_without_sham_citation(self):
        self.assertEqual(final_errors(self.value(),self.ids,self.c),[])
    def test_empty_source_branch_no_dummy_or_empty_enum(self):
        p=deepcopy(self.p);p['trace']['retained_evidence_ids']=[]
        p['final_request']['runtime_input']['evidence']['selected_evidence']=[]
        p['final_request']['runtime_input']['normalisations']=[]
        req=final.final_payload(p,self.cfg,self.c);wire=req['response_format']['json_schema']['schema']
        strict_schema_check(wire)
        self.assertNotIn('enum',wire['properties']['cited_evidence_ids']['items'])
        self.assertEqual(final_errors(self.value(),[],self.c),[])
        self.assertTrue(final_errors(self.value(self.ids),[],self.c))
        self.assertEqual(json.loads(req['messages'][1]['content'])['final_citation_contract']['allowed_source_evidence_ids'],[])
    def test_duplicate_citations_rejected(self):
        self.assertIn('CITATION_ID_NOT_RETAINED',final_errors(self.value(self.ids*2),self.ids,self.c))
    def test_answer_must_be_nonempty(self):
        v=self.value();v['answer']=' '
        self.assertIn('ANSWER_EMPTY',final_errors(v,self.ids,self.c))
    def test_altered_plan_fields_rejected(self):
        v=self.value();v['plan_fields']['brief_rationale']='SYNTHETIC MUTATION'
        self.assertIn('FINAL_ADMIN_PLAN_CHANGED',final_errors(v,self.ids,self.c))
    def test_nested_current_request_is_preserved(self):
        req=final.final_payload(self.p,self.cfg,self.c);body=json.loads(req['messages'][1]['content'])
        self.assertIn('current-request',body['accepted_plan']['evidence_refs'])
        self.assertNotIn('current-request',body['final_citation_contract']['allowed_source_evidence_ids'])
        self.assertEqual(canonical(body['accepted_plan']),canonical(self.c))
    def test_five_initial_payloads_and_catalogues_unchanged(self):
        for i,row in enumerate(load_slots(),1):
            req=REPAIR.candidate_payload(prepared(row),settings()['generation_roles']['CANDIDATE'])
            saved=HERE/'requests'/f'{i:02}_initial.json'
            self.assertEqual(saved.read_bytes(),(I5/'requests'/saved.name).read_bytes())
            self.assertEqual(req,load(saved));self.assertEqual(sha(req),row['proposed_initial_request_sha256'])
            self.assertEqual(json.loads(req['messages'][1]['content']),json.loads(load(saved)['messages'][1]['content']))
    def test_all_final_input_fields_bytes_preserved(self):
        for row in load_slots():
            p=prepared(row)
            receipt=final.preservation_receipt(p,self.cfg,self.c)
            self.assertTrue(receipt['only_added_field'])
            self.assertTrue(all(x['canonical_bytes_unchanged'] for x in receipt['fields'].values()))
    def test_source_trace_mismatch_stops(self):
        p=deepcopy(self.p);p['trace']['retained_evidence_ids'].append('current-request')
        with self.assertRaisesRegex(ValueError,'SOURCE_TRACE_MISMATCH'):final.final_payload(p,self.cfg,self.c)
    def test_current_request_cannot_be_promoted_to_source(self):
        p=deepcopy(self.p);p['trace']['retained_evidence_ids']=['current-request']
        p['final_request']['runtime_input']['evidence']['selected_evidence'][0]['evidence_id']='current-request'
        with self.assertRaisesRegex(ValueError,'REFERENCE_BOUNDARY'):final.final_payload(p,self.cfg,self.c)
    def test_duplicate_source_ids_stops(self):
        p=deepcopy(self.p);p['trace']['retained_evidence_ids']*=2
        p['final_request']['runtime_input']['evidence']['selected_evidence']*=2
        with self.assertRaisesRegex(ValueError,'REFERENCE_BOUNDARY'):final.final_payload(p,self.cfg,self.c)
    def test_same_general_policy_plan_and_no_plan(self):
        yes=final.final_payload(self.p,self.cfg,self.c);no=final.final_payload(self.p,self.cfg)
        self.assertEqual(yes['messages'][0],no['messages'][0])
        self.assertIn(final.POLICY,yes['messages'][0]['content'])
        for needle in ('uncertain estimates','Observation dates are not calendar availability','Ordinary advice does not require','has not been read','Preserve plan_fields exactly','encoded checks only'):
            self.assertIn(needle,final.POLICY)
    def test_no_new_calendar_budget_or_timezone_fields(self):
        yes=json.loads(final.final_payload(self.p,self.cfg,self.c)['messages'][1]['content'])
        old=json.loads(old_final(self.p,self.cfg,self.c)['messages'][1]['content'])
        self.assertEqual(yes['time_context'],old['time_context'])
        self.assertEqual(yes['information_needed'],old['information_needed'])
        self.assertNotIn('calendar',yes['final_citation_contract'])
    def test_original_candidate_failure_fallback_unchanged(self):
        self.assertEqual(final.final_payload(self.p,self.cfg,None,True),old_final(self.p,self.cfg,None,True))
    def test_prompt_excludes_admin_and_human_side_material(self):
        for row in load_slots():
            p=prepared(row);p['SYNTHETIC_ADMIN_SENTINEL']='SYNTHETIC_GOLD_HUMAN_JUDGMENT_SENTINEL'
            req=final.final_payload(p,self.cfg,self.c)
            prompt=canonical(req['messages']).decode()
            for needle in ('/Users/','I0-SYN-','SYNTHETIC_GOLD_HUMAN_JUDGMENT_SENTINEL','H3_REVIEW','expected_outcome','rating_anchor'):
                self.assertNotIn(needle,prompt)
    def test_actual_schema_matches_saved(self):
        for i,row in enumerate(load_slots(),1):
            req=final.final_payload(prepared(row),self.cfg,self.c if i==1 else None)
            self.assertEqual(req['response_format']['json_schema']['schema'],load(HERE/'schemas'/f'{i:02}_final.wire.json'))
            strict_schema_check(req['response_format']['json_schema']['schema'])
    def test_original_final_checker_identity(self):
        self.assertEqual(sha((ROOT/'utils/c4_rebuild/i1/schemas.py').read_bytes()),load(HERE/'OLD_FAILURE_REPLAY.json')['checker_sha256'])
    def test_reuse_receipt_exact_source_binding(self):
        r=run.reused_candidate();self.assertEqual(r,load(HERE/'CANDIDATE_REUSE_RECEIPT.json'))
        self.assertEqual(r['prepared_sha256'],sha(self.p));self.assertEqual(r['new_candidate_calls'],0)
    def test_reuse_invalid_source_plan_stops(self):
        with patch.object(REPAIR,'candidate_issues',return_value=['SYNTHETIC_SOURCE_CONFLICT']):
            with self.assertRaisesRegex(ValueError,'REUSE_ORIGINAL_VALIDATION'):run.reused_candidate()

class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='i6_synthetic_controls_');self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name)/'exclusive';self.out.mkdir();self.clock=Clock();self.cfg=settings()
    def runner(self,mock=None,guard=lambda:None):
        self.mock=mock or Mock();return run.LimitedRunner(self.out,self.cfg,self.mock,guard,self.clock,self.clock.sleep)
    def execute(self,mock=None,guard=lambda:None):
        runner=self.runner(mock,guard)
        with contextlib.redirect_stdout(io.StringIO()):s=runner.execute()
        return runner,s
    def first_final(self,r):
        row=load_slots()[0];r.reused=run.reused_candidate();p=prepared(row);c=r.reused['candidate']
        return r.call(row,'FINAL',final.final_payload(p,self.cfg['generation_roles']['FINAL'],c),lambda v:final_errors(v,p['trace']['retained_evidence_ids'],c),final_plan=c)
    def correction_script(self,valid_correction=True):
        def script(payload,n):
            body=json.loads(payload['messages'][1]['content'])
            if 'accepted_plan' in body:return raw(dict(answer='SYNTHETIC MOCK ONLY',cited_evidence_ids=[],plan_fields=body['accepted_plan']))
            c=plan(prepared(load_slots()[0]));g=body['encoded_planning_fields']['goals'][0];c.update(goal=g['text'],goal_id=g['goal_id'])
            if 'previous_candidate' not in body or not valid_correction:c['evidence_refs']=[]
            return raw(c)
        return script
    def test_success_reuses_one_adds_four_and_five_finals(self):
        r,s=self.execute();self.assertEqual(s['phase_counts'],dict(INITIAL=4,CORRECTION=0,FINAL=5))
        self.assertEqual(s['reused_accepted_candidates'],1);self.assertEqual(s['new_accepted_candidates'],4)
        self.assertEqual(s['status'],'BOUNDED_EXECUTION_COMPLETE')
    def test_all_corrections_exact_maximum_thirteen(self):
        r,s=self.execute(Mock(self.correction_script()))
        self.assertEqual(s['phase_counts'],dict(INITIAL=4,CORRECTION=4,FINAL=5));self.assertEqual(s['total_physical_calls'],13)
        for x in r.starts:
            if x['phase']=='CORRECTION':
                body=json.loads(x['request']['messages'][1]['content'])
                prior=load(self.out/'attempts'/(x['correction_of']+'.outcome.json'))
                self.assertEqual(body['previous_candidate'],prior['value'])
                self.assertEqual(body['concrete_checker_issues'],prior['issues'])
    def test_exhausted_candidate_stops_all_later_slots(self):
        r,s=self.execute(Mock(self.correction_script(False)))
        self.assertEqual(s['phase_counts'],dict(INITIAL=1,CORRECTION=1,FINAL=1))
        self.assertEqual(s['stop_reason'],'CANDIDATE_FAILED_AFTER_ALLOWED_ATTEMPTS')
        self.assertTrue(all(x['final_status']=='NOT_ATTEMPTED' for x in s['slots'][2:]))
    def test_failed_final_no_retry_or_later_slot(self):
        r,s=self.execute(Mock(lambda p,n:raw(dict(answer='SYNTHETIC',cited_evidence_ids=['current-request'],plan_fields=json.loads(p['messages'][1]['content'])['accepted_plan']))))
        self.assertEqual(s['phase_counts'],dict(INITIAL=0,CORRECTION=0,FINAL=1))
        self.assertEqual(s['stop_reason'],'FINAL_FAILED_NO_RETRY')
        self.assertTrue(all(x['candidate_status']=='NOT_ATTEMPTED' for x in s['slots'][1:]))
    def test_unknown_completion_preserves_reservation_stops(self):
        def fail(p,n):raise TransportFailure('UNKNOWN_COMPLETION')
        r,s=self.execute(Mock(fail))
        self.assertEqual(s['stop_reason'],'UNKNOWN_COMPLETION');self.assertEqual(len(self.mock.calls),1)
        self.assertEqual(r.outcomes[0]['completion'],'UNKNOWN');self.assertGreater(float(r.starts[0]['reserved_estimate_usd']),0)
        self.assertIsNone(r.outcomes[0]['usage'])
    def test_nonretryable_errors_stop(self):
        for category in ('AUTH','CONFIG','MODEL','RATE_LIMIT','BILLING','PERMISSION','REFUSAL','TRUNCATED'):
            with self.subTest(category=category),tempfile.TemporaryDirectory(prefix='i6_mock_') as d:
                def fail(p,n):raise TransportFailure(category)
                r=run.LimitedRunner(Path(d),self.cfg,Mock(fail),clock=self.clock,sleep=self.clock.sleep)
                with contextlib.redirect_stdout(io.StringIO()):s=r.execute()
                self.assertEqual(s['total_physical_calls'],1);self.assertEqual(s['stop_reason'],category)
    def test_model_mismatch_stops(self):
        r,s=self.execute(Mock(lambda p,n:raw({},model='SYNTHETIC_WRONG_MODEL')))
        self.assertEqual(s['stop_reason'],'RETURNED_MODEL_MISMATCH')
    def test_source_identity_conflict_before_client_send(self):
        def fail():raise ValueError('SYNTHETIC_SOURCE_DRIFT')
        r,s=self.execute(guard=fail);self.assertEqual(len(self.mock.calls),0);self.assertTrue(s['stop_reason'])
    def test_serial_monotonic_two_second_starts(self):
        r,s=self.execute();starts=[x['monotonic_start'] for x in r.outcomes]
        self.assertTrue(all(b-a>=2 for a,b in zip(starts,starts[1:])))
        self.assertTrue(all(x['monotonic_end']<=y['monotonic_start'] for x,y in zip(r.outcomes,r.outcomes[1:])))
    def test_reused_slot_new_candidate_forbidden(self):
        r=self.runner();row=load_slots()[0]
        with self.assertRaisesRegex(run.StopRun,'REUSED_SLOT_CANDIDATE_FORBIDDEN'):
            r.call(row,'INITIAL',load(HERE/'requests/01_initial.json'),lambda v:[])
        self.assertEqual(self.mock.calls,[])
    def test_serial_slot_order_cannot_skip(self):
        r=self.runner()
        with self.assertRaisesRegex(run.StopRun,'SERIAL_SLOT_ORDER'):
            r.call(load_slots()[1],'INITIAL',load(HERE/'requests/02_initial.json'),lambda v:[])
    def test_no_final_with_mismatched_reuse(self):
        r=self.runner();row=load_slots()[0];p=prepared(row);c=plan(p)
        with self.assertRaisesRegex(run.StopRun,'REUSE_IDENTITY_CONFLICT'):
            r.call(row,'FINAL',final.final_payload(p,self.cfg['generation_roles']['FINAL'],c),lambda v:[],final_plan=c)
    def test_total_cap_enforced(self):
        r=self.runner();r.starts=[dict(logical='SYNTHETIC_PRIOR',phase='INITIAL') for _ in range(13)]
        with self.assertRaisesRegex(run.StopRun,'TOTAL_PHYSICAL_CALL_CEILING'):self.first_final(r)
        self.assertEqual(self.mock.calls,[])
    def test_final_role_cap_enforced(self):
        r=self.runner();r.starts=[dict(logical='SYNTHETIC_PRIOR',phase='FINAL') for _ in range(5)]
        with self.assertRaisesRegex(run.StopRun,'ROLE_CALL_CEILING'):self.first_final(r)
    def test_budget_reserved_before_dispatch(self):
        r=self.runner()
        with patch.object(run,'estimate',return_value=(100,run.Decimal('0.2500001'))):
            with self.assertRaisesRegex(run.StopRun,'ESTIMATED_BUDGET_EXHAUSTED'):self.first_final(r)
        self.assertEqual(self.mock.calls,[])
    def test_usage_overrun_stops(self):
        def script(p,n):
            r=raw(dict(answer='SYNTHETIC',cited_evidence_ids=[],plan_fields=json.loads(p['messages'][1]['content'])['accepted_plan']))
            r['usage']['prompt_tokens']=10000000;return r
        r,s=self.execute(Mock(script));self.assertEqual(s['stop_reason'],'OBSERVED_USAGE_EXCEEDS_ESTIMATED_BUDGET')
    def test_reservation_unknown_usage_not_zero(self):
        self.assertIsNone(run.usage_estimate(None,self.cfg))
        units,amount=run.estimate(load(HERE/'requests/01_i6_final.json'),self.cfg)
        self.assertEqual(units,len(canonical(load(HERE/'requests/01_i6_final.json')))+256);self.assertGreater(amount,0)
    def test_original_frozen_runtime_except_caps_version(self):
        c=settings();old=load(I5/'CONFIG.json');c['version']=old['version'];c['caps']=old['caps']
        self.assertEqual(c,old);self.assertEqual(settings()['caps'],dict(INITIAL=4,CORRECTION=4,FINAL=5,TOTAL=13))
    def test_authorization_exact_version_is_accepted(self):
        run.validate_approval(load(HERE/'DIRECT_APPROVAL.json'),run.binding())
    def test_unapproved_or_mismatched_authorization_rejected(self):
        for key,value in [('version','I5_DIRECT_APPROVAL_V1'),('status','UNAPPROVED'),('authority','ATTACHMENT_ONLY'),('binding_sha256','WRONG')]:
            a=load(HERE/'DIRECT_APPROVAL.json');a[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):run.validate_approval(a,run.binding())
        a=load(HERE/'DIRECT_APPROVAL.json');a['binding']['limits']['caps']['TOTAL']=14
        with self.assertRaises(ValueError):run.validate_approval(a,run.binding())
    def test_unapproved_begin_output_creates_no_directory(self):
        a=load(HERE/'DIRECT_APPROVAL.json');a['status']='UNAPPROVED';target=self.out/'never'
        with self.assertRaises(ValueError):run.begin_output(target,dict(status='PASS',binding=run.binding()),a)
        self.assertFalse(target.exists())
    def test_bad_preflight_never_constructs_client(self):
        with patch.object(run,'validate_preflight',side_effect=ValueError('SYNTHETIC_GATE')),patch.object(run,'ExactOpenAITransport') as client:
            with self.assertRaises(ValueError):run.main()
            client.assert_not_called()
    def test_no_implicit_resume(self):
        with self.assertRaises(FileExistsError):run.begin_output(self.out,dict(status='PASS',binding=run.binding()),load(HERE/'DIRECT_APPROVAL.json'))
    def test_stopped_runner_cannot_send_again(self):
        r=self.runner();r.stopped=True
        with self.assertRaisesRegex(run.StopRun,'STOPPED_NO_RESUME'):self.first_final(r)
        self.assertEqual(self.mock.calls,[])
    def test_live_constructor_requires_approval_before_sdk(self):
        with patch.object(run,'load',side_effect=ValueError('SYNTHETIC_NO_RECEIPT')):
            with self.assertRaisesRegex(ValueError,'SYNTHETIC_NO_RECEIPT'):run.ExactOpenAITransport()
    def test_exception_text_and_headers_never_persisted(self):
        def fail(p,n):raise ValueError('SYNTHETIC_SECRET_SENTINEL Authorization: Bearer SYNTHETIC')
        r,s=self.execute(Mock(fail))
        self.assertEqual(s['stop_reason'],'UNKNOWN_COMPLETION')
        for path in self.out.rglob('*'):
            if path.is_file():self.assertNotIn('SYNTHETIC_SECRET_SENTINEL',path.read_text())
    def test_raw_invalid_json_correction_is_fresh(self):
        p=prepared(load_slots()[1]);req=load(HERE/'requests/02_initial.json')
        r=raw(None,text='{SYNTHETIC_INVALID_JSON');status,value,issues=parse_response(r,req,lambda v:[])
        corrected,branch=run.correction_payload(p,dict(status=status,value=value,issues=issues),r,self.cfg)
        self.assertEqual(branch,'RAW_PARSE_OR_OUTER_SCHEMA_FEEDBACK')
        body=json.loads(corrected['messages'][1]['content'])
        self.assertEqual(body['raw_failed_response_text'],'{SYNTHETIC_INVALID_JSON')
        self.assertNotIn('previous_candidate',body)

if __name__=='__main__':unittest.main()
