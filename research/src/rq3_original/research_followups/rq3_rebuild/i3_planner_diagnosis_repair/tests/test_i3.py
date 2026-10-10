"""Synthetic controls and complete saved-record regressions; no execution script."""
from copy import deepcopy
import json
import unittest

from i3_common import HERE, ROOT, live_records, read, sha, canonical
from repair_v1 import candidate_payload, candidate_issues, local_rules, FINAL_ONLY_TEXT
from utils.c4_rebuild.i1.renderer import candidate_payload as original_payload, final_payload
from utils.c4_rebuild.i1.schemas import CANDIDATE, errors
from utils.c4_rebuild.i1.durable import parse_response
from utils.c4_rebuild.planning import project, validate_bridge, validate_candidate

LIVE, STAGES, ATTEMPTS = live_records()
CONFIG = read(ROOT/'research_followups/rq3_rebuild/i1_pilot_launch/PILOT_CONFIGURATION_PROPOSED.json')['generation_roles']


def prepared(logical='I0-SYN-06:S5_FULL'):
    return deepcopy(STAGES[logical,'C_MODULE_REBUILD'][1]['output']['prepared'])


def synthetic_plan(bridge):
    """Independent test fixture, never a repaired I2 raw candidate or response."""
    goal=bridge['planner_input']['goals'][0]
    return dict(plan_id='I3_SYNTHETIC_CONTROL',goal_id=goal['goal_id'],goal=goal['text'],
        evidence_refs=['current-request'],continues_plan_id=None,brief_rationale='Synthetic mechanical control only.',
        actions=[dict(step_id='I3_TEST_STEP',task_id='I3_TEST_TASK',kind='TASK',action='Review the current request.',
            estimated_duration=dict(value=5,unit='minutes',origin='MODEL_ESTIMATE',evidence_refs=[],uncertainty='Synthetic estimate; real duration unknown.'),
            resource_ids=[],dependencies=[],schedule=None,completion_check='Restate the request.',
            evidence_refs=['current-request'],brief_rationale='Synthetic test action, not study advice.')])


def codes(bridge, plan):
    return {i['code'] if isinstance(i,dict) else i.rsplit(':',1)[-1] for i in candidate_issues(bridge,plan)}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.p=prepared();self.b=self.p['planner']['bridge'];self.plan=synthetic_plan(self.b)

    def test_advice_without_calendar_passes_original_and_new(self):
        self.assertIsNone(self.b['planner_input']['scope']['timezone'])
        self.assertIsNone(self.b['planner_input']['scope']['horizon'])
        self.assertEqual(candidate_issues(self.b,self.plan),[])
        self.assertEqual(validate_candidate(self.b,self.plan)['outcome'],'PASSED_ENCODED_CHECKS')
        self.assertEqual(self.plan['actions'][0]['schedule'],None)

    def test_required_schedule_without_window_still_blocks(self):
        p=prepared('I0-SYN-09:S4_EVIDENCE_PLANNING')
        with self.assertRaises(ValueError):candidate_payload(p,CONFIG['CANDIDATE'])
        c=codes(p['planner']['bridge'],synthetic_plan(p['planner']['bridge']))
        self.assertTrue({'MISSING_TIMEZONE','MISSING_WINDOW','ALLOWED_WINDOWS_UNKNOWN'}<=c)

    def test_explicit_infeasible_time_not_accepted(self):
        s=deepcopy(self.b['source_input']);base=s['base_input']
        s['task_request']['mode']='EXPLICIT_SCHEDULE'
        base['hard_constraints']['schedule'].update(required=True,allowed_windows=[])
        base['scope'].update(timezone='Europe/Oslo',horizon=dict(start='2026-09-02T13:00:00+02:00',end='2026-09-02T14:00:00+02:00'))
        b=project(s)
        self.assertIn('NO_ALLOWED_TIME_EXPLICIT',codes(b,self.plan))

    def test_optional_schedule_cannot_invent_calendar(self):
        self.plan['actions'][0]['schedule']=dict(start='2026-09-02T13:00:00+02:00',end='2026-09-02T13:05:00+02:00')
        self.assertTrue({'MISSING_TIMEZONE','MISSING_WINDOW','ALLOWED_WINDOWS_UNKNOWN'}<=codes(self.b,self.plan))

    def test_budget_remains_enforced(self):
        self.plan['actions'][0]['estimated_duration']['value']=16
        self.assertIn('BUDGET_EXCEEDED',codes(self.b,self.plan))

    def test_wrong_learner_still_rejected(self):
        s=deepcopy(self.b['source_input']);s['base_input']['scope']['learner_id']='I3_OTHER_LEARNER'
        self.assertIn('SOURCE_SCOPE_MISMATCH',codes(project(s),self.plan))

    def test_wrong_course_still_rejected(self):
        s=deepcopy(self.b['source_input']);s['base_input']['scope']['course_id']='I3_OTHER_COURSE'
        self.assertIn('SOURCE_SCOPE_MISMATCH',codes(project(s),self.plan))

    def test_revoked_source_still_rejected(self):
        s=deepcopy(self.b['source_input']);s['selected_memory'][0]['native']['provenance']['consent_status']='WITHDRAWN'
        self.assertIn('SOURCE_ACCESS_DENIED',codes(project(s),self.plan))

    def test_expired_source_still_rejected(self):
        s=deepcopy(self.b['source_input']);s['base_input']['facts'][0]['source_ref']['valid_to']='2026-09-01T00:00:00+02:00'
        self.assertIn('SOURCE_OUTSIDE_VALIDITY',codes(project(s),self.plan))

    def test_ambiguous_plan_still_blocks(self):
        s=deepcopy(self.b['source_input']);s['i0_envelope']['status']='AMBIGUOUS'
        self.assertIn('AMBIGUOUS_ACTIVE_PLAN',codes(project(s),self.plan))

    def test_missing_source_identifier_still_blocks(self):
        self.plan['actions'][0]['evidence_refs']=['source:invented']
        self.assertIn('EVIDENCE_ID_MISSING',codes(self.b,self.plan))

    def test_empty_plan_reference_array_still_blocks(self):
        self.plan['evidence_refs']=[]
        self.assertIn('ARRAY_LENGTH',codes(self.b,self.plan))

    def test_empty_action_reference_array_still_blocks(self):
        self.plan['actions'][0]['evidence_refs']=[]
        self.assertIn('ARRAY_LENGTH',codes(self.b,self.plan))

    def test_completed_task_not_reintroduced(self):
        s=deepcopy(self.b['source_input']);s['base_input']['completed_tasks']=[dict(task_id='I3_TEST_TASK',evidence_refs=['current-request'])]
        self.assertIn('COMPLETED_TASK_REPEATED',codes(project(s),self.plan))

    def test_review_does_not_bypass_permission(self):
        s=deepcopy(self.b['source_input']);s['base_input']['completed_tasks']=[dict(task_id='I3_TEST_TASK',evidence_refs=['current-request'])]
        self.plan['actions'][0]['kind']='REVIEW'
        self.assertIn('REVIEW_NOT_AUTHORIZED',codes(project(s),self.plan))

    def test_explicit_review_permission_preserved(self):
        s=deepcopy(self.b['source_input']);s['base_input']['completed_tasks']=[dict(task_id='I3_TEST_TASK',evidence_refs=['current-request'])]
        s['base_input']['review_permissions']=[dict(task_id='I3_TEST_TASK',rationale='Explicit synthetic review permission.',evidence_refs=['current-request'])]
        self.plan['actions'][0]['kind']='REVIEW'
        self.assertEqual(codes(project(s),self.plan),set())

    def test_unknown_duration_not_zero(self):
        self.plan['actions'][0]['estimated_duration']['value']=None
        self.assertIn('DURATION_UNKNOWN',codes(self.b,self.plan))

    def test_goal_ID_and_text_not_substituted(self):
        self.plan['goal']='A replacement goal.'
        self.assertIn('GOAL_BINDING_MISMATCH',codes(self.b,self.plan))

    def test_plus_40_percent_semantic_counterexample_remains_visible(self):
        self.plan['actions'][0]['action']='This activity increases exam scores by +40%.'
        r=validate_candidate(self.b,self.plan)
        self.assertEqual(r['outcome'],'PASSED_ENCODED_CHECKS')
        self.assertEqual(r['semantic_support'],'NOT_CHECKED')
        self.assertEqual(candidate_issues(self.b,self.plan),[])

    def test_renderer_preserves_existing_material_and_settings(self):
        old=original_payload(self.p,CONFIG['CANDIDATE']);before=canonical(self.p)
        new=candidate_payload(self.p,CONFIG['CANDIDATE'])
        oldbody=json.loads(old['messages'][1]['content']);newbody=json.loads(new['messages'][1]['content'])
        self.assertEqual({k:newbody[k] for k in oldbody},oldbody)
        self.assertEqual(new['response_format']['json_schema']['schema'],CANDIDATE)
        for k in ('model','max_tokens','temperature','stream'):self.assertEqual(new[k],old[k])
        self.assertEqual(before,canonical(self.p))
        self.assertNotIn(FINAL_ONLY_TEXT,new['messages'][0]['content'])
        self.assertIn(FINAL_ONLY_TEXT,old['messages'][0]['content'])

    def test_existing_limits_explicit_in_request(self):
        body=json.loads(candidate_payload(self.p,CONFIG['CANDIDATE'])['messages'][1]['content'])
        limits={r['path']:r for r in body['candidate_contract']['local_constraints']}
        self.assertEqual(limits['$.evidence_refs']['minItems'],1)
        self.assertEqual(limits['$.actions[*].evidence_refs']['minItems'],1)
        ids={r['id'] for r in body['candidate_contract']['reference_catalog']}
        self.assertEqual(ids,{f['fact_id'] for f in self.b['planner_input']['facts']})

    def test_concrete_correction_preserves_candidate_and_exact_feedback(self):
        self.plan['evidence_refs']=[];issues=candidate_issues(self.b,self.plan)
        payload=candidate_payload(self.p,CONFIG['CANDIDATE'],self.plan,issues)
        b=json.loads(payload['messages'][1]['content'])
        self.assertEqual(b['previous_candidate'],self.plan);self.assertEqual(b['concrete_checker_issues'],issues)
        self.assertEqual(b['checker_feedback_details'][0]['observed_length'],0)
        self.assertEqual(b['checker_feedback_details'][0]['required_local_constraints']['minItems'],1)

    def test_external_or_missing_feedback_rejected(self):
        self.plan['evidence_refs']=[]
        for issues in ([],['made-up issue']):
            with self.assertRaises(ValueError):candidate_payload(self.p,CONFIG['CANDIDATE'],self.plan,issues)

    def test_projection_tampering_not_hidden(self):
        self.p['planner']['bridge']['planner_input']['hard_constraints']['budget']['minutes']=999
        with self.assertRaises(ValueError):candidate_payload(self.p,CONFIG['CANDIDATE'])

    def test_renderer_source_ID_and_content_mismatch_fail_closed(self):
        for field,value in (('evidence_id','fabricated'),('content','changed content')):
            p=deepcopy(self.p);p['final_request']['runtime_input']['evidence']['selected_evidence'][0][field]=value
            with self.assertRaises(ValueError):candidate_payload(p,CONFIG['CANDIDATE'])

    def test_common_final_renderer_has_no_patch(self):
        baseline=final_payload(self.p,CONFIG['FINAL'],None,True)
        candidate_payload(self.p,CONFIG['CANDIDATE'])
        self.assertEqual(final_payload(self.p,CONFIG['FINAL'],None,True),baseline)


class SavedEvidenceTests(unittest.TestCase):
    def test_all_technical_spans_reproduce_exact_answer_words(self):
        rows=[json.loads(line) for line in (HERE/'FINAL_FALLBACK_AND_INPUT_TRACE.jsonl').read_text().splitlines()]
        for row in rows:
            path=row['raw_answer_source'].split('#')[0]
            answer=json.loads(read(HERE/path)['choices'][0]['message']['content'])['answer']
            for note in row['technical_observations']:
                span=note['answer_span']
                self.assertEqual(answer[span['start_char']:span['end_char']],span['text'])
                self.assertTrue(span['manual_verification_required'])

    def test_all_preview_requests_fit_original_input_cap(self):
        config=read(ROOT/'research_followups/rq3_rebuild/i1_pilot_launch/PILOT_CONFIGURATION_PROPOSED.json')
        paths=list((HERE/'proposed_requests_not_authorized').glob('*.json'))
        self.assertEqual(len(paths),32)
        for path in paths:
            payload=read(path)
            self.assertLessEqual(len(canonical(payload))+256,config['max_request_input_byte_units'])
            self.assertEqual(payload['max_tokens'],config['generation_roles']['CANDIDATE']['max_output_tokens'])

    def test_all_32_old_new_remain_rejected_without_candidate_edits(self):
        n=0
        for a in ATTEMPTS:
            if a['role']!='CANDIDATE':continue
            p=prepared(a['logical'].removesuffix(':CANDIDATE'));b=p['planner']['bridge'];aid=a['attempt_id']
            o=read(LIVE/'attempts'/f'{aid}.outcome.json');raw=read(LIVE/'attempts'/f'{aid}.raw.json')
            body=json.loads(a['request']['messages'][1]['content']);before=sha(o['value'])
            v=lambda x:candidate_issues(b,x)
            old=parse_response(raw,a['request'],v)
            new_req=candidate_payload(p,CONFIG['CANDIDATE'],body.get('previous_candidate'),body.get('concrete_checker_issues',()))
            new=parse_response(raw,new_req,v)
            self.assertEqual(old[0],o['status']);self.assertEqual(new,old);self.assertEqual(sha(o['value']),before);n+=1
        self.assertEqual(n,32)

    def test_72_raw_answers_and_reading_ranges_exact(self):
        index=read(HERE/'ANSWER_READING_COPY_INDEX.json');b=(HERE/'DEVELOPMENT_READING_COPY_VERIFIED.md').read_bytes()
        self.assertEqual(len(index['entries']),72)
        for row in index['entries']:
            answer=json.loads(read(HERE/row['raw_record'])['choices'][0]['message']['content'])['answer'].encode()
            self.assertEqual(b[row['reading_start_byte']:row['reading_end_byte_exclusive']],answer)
            self.assertEqual(sha(answer),row['answer_sha256'])

    def test_every_saved_final_matches_unchanged_final_renderer(self):
        n=0
        for a in ATTEMPTS:
            if a['role']!='FINAL':continue
            logical=a['logical'].removesuffix(':FINAL');p=prepared(logical)
            d=STAGES[logical,'D_E_CANDIDATE_CHECK_REPAIR'][1]['output']
            self.assertEqual(final_payload(p,CONFIG['FINAL'],d['accepted_plan'],d['planning_failed']),a['request']);n+=1
        self.assertEqual(n,72)


if __name__=='__main__':unittest.main(verbosity=2)
