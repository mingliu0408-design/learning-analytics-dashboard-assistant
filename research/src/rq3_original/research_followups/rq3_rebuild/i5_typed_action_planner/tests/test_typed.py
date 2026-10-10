"""I5 copied-input regression and independently constructed synthetic controls."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from i5_common import *
import typed_v1 as typed
import run_i5 as run
from utils.c4_rebuild.i1.renderer import final_payload
from utils.c4_rebuild.i1.schemas import errors, CANDIDATE, strict_schema_check
from utils.c4_rebuild.i1.durable import parse_response
from utils.c4_rebuild.planning import project, validate_candidate
from test_harness import plan, raw, Mock, Clock


def codes(bridge, candidate):
    return {i['code'] if isinstance(i, dict) else i.rsplit(':', 1)[-1]
            for i in typed.candidate_issues(bridge, candidate)}


def calendar_fixture():
    p = prepared(load_slots()[0])
    source = deepcopy(p['planner']['bridge']['source_input'])
    query = 'Schedule these tasks in the stated time windows.'
    source['task_request'] = dict(mode=typed.SCHEDULE, basis='EXPLICIT_TASK_REQUEST_FIELD', source_quote=query)
    base = source['base_input']; base['context']['query'] = query
    base['goals'][0]['text'] = query
    next(f for f in base['facts'] if f['fact_id'] == 'current-request')['value'] = query
    window = dict(start='2026-09-02T13:00:00+02:00', end='2026-09-02T14:00:00+02:00')
    base['scope'].update(timezone='Europe/Oslo', horizon=window)
    base['hard_constraints']['schedule'].update(required=True, allowed_windows=[window])
    p['planner']['bridge'] = project(source)
    p['final_request']['runtime_input']['context']['current_query'] = query
    c = plan(p)
    c['actions'][0]['schedule'] = dict(start=window['start'], end='2026-09-02T13:05:00+02:00')
    return p, c


class TypedTests(unittest.TestCase):
    def setUp(self):
        self.p = prepared(load_slots()[2]); self.b = self.p['planner']['bridge']; self.c = plan(self.p)
        self.config = settings()['generation_roles']['CANDIDATE']

    def test_original_ten_exact_errors_and_values_unchanged(self):
        rows = []
        for index, row in enumerate(load_slots(), 1):
            p = prepared(row)
            for phase in ('initial', 'correction'):
                aid = f'{index:02}_{phase}'; prefix = HERE / 'historical_i4/live/attempts'
                start = load(prefix / (aid + '.start.json')); old = load(prefix / (aid + '.outcome.json'))
                rawvalue = load(prefix / (aid + '.raw.json'))
                status, value, issues = parse_response(rawvalue, start['request'],
                    lambda c: typed.ORIGINAL.candidate_issues(p['planner']['bridge'], c))
                self.assertEqual(status, old['status']); self.assertNotEqual(status, 'ACCEPTED')
                self.assertEqual(value, old['value'])
                self.assertEqual(sorted(canonical(i) for i in issues), sorted(canonical(i) for i in old['issues']))
                self.assertTrue(typed.candidate_issues(p['planner']['bridge'], value))
                rows.append(aid)
        self.assertEqual(len(rows), 10)

    def test_five_modes_source_traced(self):
        for row in load_slots():
            p = prepared(row); d = typed.plan_kind(p['planner']['bridge'])
            self.assertEqual(d['kind'], typed.ORDINARY)
            self.assertEqual(d['task_request']['source_quote'], d['legitimate_query'])
            self.assertFalse(d['schedule_required'])

    def test_nullable_advice_admitted_without_calendar(self):
        local, wire = typed.schemas(typed.ORDINARY)
        self.assertEqual(errors(self.c, local), []); self.assertEqual(errors(self.c, wire), [])
        self.assertEqual(typed.candidate_issues(self.b, self.c), [])
        self.assertEqual(validate_candidate(self.b, self.c)['outcome'], 'PASSED_ENCODED_CHECKS')

    def test_advice_dates_structurally_inexpressible(self):
        self.c['actions'][0]['schedule'] = dict(start='2026-09-02T12:00:00+02:00', end='2026-09-02T12:05:00+02:00')
        local, wire = typed.schemas(typed.ORDINARY)
        self.assertTrue(errors(self.c, local)); self.assertTrue(errors(self.c, wire))
        payload = typed.candidate_payload(self.p, self.config)
        self.assertEqual(parse_response(raw(self.c), payload, lambda c: [])[0], 'SCHEMA')

    def test_unknown_duration_cannot_establish_budget(self):
        self.c['actions'][0]['estimated_duration'].update(value=None, origin='UNKNOWN')
        self.assertFalse(errors(self.c, typed.schemas(typed.ORDINARY)[0]))
        self.assertIn('DURATION_UNKNOWN', codes(self.b, self.c))

    def test_advice_estimate_origin_cannot_claim_source_proof(self):
        for origin in ('SOURCE_ESTIMATE', 'LEARNER_ESTIMATE', 'SYNTHETIC_ESTIMATE'):
            self.c['actions'][0]['estimated_duration']['origin'] = origin
            self.assertTrue(errors(self.c,typed.schemas(typed.ORDINARY)[1]))

    def test_budget_not_removed_by_advice_branch(self):
        self.c['actions'][0]['estimated_duration']['value'] = 16
        self.assertIn('BUDGET_EXCEEDED', codes(self.b, self.c))

    def test_unknown_request_needs_information(self):
        s = deepcopy(self.b['source_input']); s['task_request'].update(mode='UNKNOWN', basis='UNKNOWN')
        self.assertEqual(typed.plan_kind(project(s))['kind'], typed.NEEDS)

    def test_explicit_missing_calendar_no_reclassification(self):
        p, c = calendar_fixture(); s = p['planner']['bridge']['source_input']
        s['base_input']['scope'].update(timezone=None, horizon=None)
        s['base_input']['hard_constraints']['schedule']['allowed_windows'] = None
        p['planner']['bridge'] = project(s); d = typed.plan_kind(p['planner']['bridge'])
        self.assertEqual(d['kind'], typed.NEEDS)
        self.assertTrue({'MISSING_TIMEZONE','MISSING_HORIZON','MISSING_ALLOWED_WINDOWS'} <= set(d['reasons']))
        with self.assertRaisesRegex(ValueError, 'NEEDS_TASK_INFORMATION'):
            typed.candidate_payload(p, self.config)
        self.assertTrue(typed.candidate_issues(p['planner']['bridge'], c))

    def test_supported_feasible_scheduled_fixture_passes(self):
        p, c = calendar_fixture(); b = p['planner']['bridge']
        self.assertEqual(typed.plan_kind(b)['kind'], typed.SCHEDULE)
        self.assertEqual(typed.candidate_issues(b, c), [])
        self.assertEqual(validate_candidate(b, c)['outcome'], 'PASSED_ENCODED_CHECKS')
        req = typed.candidate_payload(p, self.config)
        self.assertEqual(parse_response(raw(c), req, lambda v: typed.candidate_issues(b,v))[0], 'ACCEPTED')

    def test_explicit_calendar_null_never_success(self):
        p, c = calendar_fixture(); c['actions'][0]['schedule'] = None
        self.assertTrue(typed.candidate_issues(p['planner']['bridge'], c))

    def test_explicit_schedule_schema_unchanged_except_descriptions(self):
        from utils.c4_rebuild.i1.schemas import strict_subset
        old = CANDIDATE['properties']['actions']['items']['properties']['schedule']
        new = typed.schemas(typed.SCHEDULE)[1]['properties']['actions']['items']['properties']['schedule']
        self.assertEqual(old, strict_subset(new))

    def test_infeasible_schedule_still_rejected(self):
        p, c = calendar_fixture()
        c['actions'][0]['schedule']['end'] = '2026-09-02T15:00:00+02:00'
        self.assertTrue(typed.candidate_issues(p['planner']['bridge'], c))

    def test_revoked_expired_cross_learner_sources_rejected(self):
        for mutation, expected in (
            ('revoked', 'SOURCE_ACCESS_DENIED'), ('expired', 'SOURCE_OUTSIDE_VALIDITY'), ('learner', 'SOURCE_SCOPE_MISMATCH')):
            with self.subTest(mutation=mutation):
                s = deepcopy(self.b['source_input'])
                if mutation == 'revoked': s['selected_memory'][0]['native']['provenance']['consent_status'] = 'WITHDRAWN'
                elif mutation == 'expired': s['base_input']['facts'][0]['source_ref']['valid_to'] = '2026-09-01T00:00:00+02:00'
                else: s['base_input']['scope']['learner_id'] = 'OTHER_SYNTHETIC_LEARNER'
                self.assertIn(expected, codes(project(s), self.c))

    def test_fake_evidence_or_evidence_as_resource_rejected(self):
        self.c['actions'][0]['evidence_refs'] = ['fake-evidence']
        self.assertIn('EVIDENCE_ID_MISSING', codes(self.b, self.c))
        self.c = plan(self.p); self.c['actions'][0]['resource_ids'] = ['current-request']
        self.assertIn('RESOURCE_NOT_PERMITTED', codes(self.b, self.c))

    def test_local_dependency_identity_order_and_cycle_checks(self):
        second = deepcopy(self.c['actions'][0]); second.update(step_id='STEP_TWO', task_id='TASK_TWO')
        self.c['actions'].append(second)
        for deps, code in ((['MOCK_TASK'],'DEPENDENCY_ID_MISSING'), (['missing'],'DEPENDENCY_ID_MISSING'),
                           (['STEP_TWO'],'DEPENDENCY_CYCLE')):
            second['dependencies'] = deps
            self.assertIn(code, codes(self.b, self.c))
        second['dependencies'] = ['MOCK_STEP']; self.c['actions'][0]['dependencies'] = ['STEP_TWO']
        self.assertTrue({'DEPENDENCY_CYCLE','DEPENDENCY_ORDER'} <= codes(self.b, self.c))
        self.c['actions'][0]['dependencies'] = []; self.assertEqual(typed.candidate_issues(self.b, self.c), [])

    def test_duplicate_step_ids_and_namespace_collision_rejected(self):
        a = deepcopy(self.c['actions'][0]); a['task_id'] = 'TASK_TWO'; self.c['actions'].append(a)
        self.assertIn('DUPLICATE_ID', codes(self.b, self.c))
        self.c = plan(self.p); self.c['actions'][0]['step_id'] = self.c['actions'][0]['task_id']
        self.assertIn('STEP_NAMESPACE_COLLISION', codes(self.b, self.c))

    def test_actual_dependency_feedback_no_silent_rename(self):
        self.c['actions'][0]['dependencies'] = ['MOCK_TASK']
        before = canonical(self.c); issues = typed.candidate_issues(self.b, self.c)
        req = typed.candidate_payload(self.p, self.config, self.c, issues)
        body = json.loads(req['messages'][1]['content'])
        self.assertEqual(canonical(self.c), before)
        self.assertEqual(body['previous_candidate'], self.c)
        self.assertEqual(body['checker_feedback_details']['existing_step_ids'], ['MOCK_STEP'])
        self.assertEqual(body['checker_feedback_details']['invalid_dependencies'][0]['offending_values'], ['MOCK_TASK'])

    def test_completed_task_repeat_rejected(self):
        s = deepcopy(self.b['source_input'])
        s['base_input']['completed_tasks'] = [dict(task_id='MOCK_TASK', evidence_refs=['current-request'])]
        self.assertIn('COMPLETED_TASK_REPEATED', codes(project(s), self.c))

    def test_conditional_rules_cover_all_nullable_branches(self):
        ordinary = typed.local_rules(typed.schemas(typed.ORDINARY)[0])
        self.assertFalse(any('.schedule.' in x['path'] for x in ordinary))
        cont = next(x for x in ordinary if x['path'] == '$.continues_plan_id')
        self.assertEqual(cont['applies_when'][0]['type'], 'string')
        dur = next(x for x in ordinary if x['path'].endswith('estimated_duration.value'))
        self.assertEqual(dur['applies_when'][0]['type'], 'number')
        schedule = typed.local_rules(typed.schemas(typed.SCHEDULE)[0])
        for row in [x for x in schedule if '.schedule.' in x['path']]:
            self.assertEqual(row['applies_when'][0]['path'], '$.actions[*].schedule')
            self.assertEqual(row['applies_when'][0]['type'], 'object')

    def test_branch_invariant_to_administrative_ids(self):
        before = typed.plan_kind(self.b)
        p = deepcopy(self.p)
        p['scenario_id']='OTHER'; p['condition_id']='OTHER'; p['reviewer_id']='UNREAD_ADMIN_SENTINEL'
        self.assertEqual(typed.plan_kind(p['planner']['bridge']), before)
        self.assertEqual(typed.candidate_payload(p,self.config),typed.candidate_payload(self.p,self.config))

    def test_past_evidence_time_not_inferred_calendar(self):
        before = canonical(self.p); req = typed.candidate_payload(self.p, self.config)
        body = json.loads(req['messages'][1]['content'])
        original = json.loads(typed.ORIGINAL.candidate_payload(self.p,self.config)['messages'][1]['content'])
        self.assertEqual(body['time_context'], original['time_context'])
        self.assertEqual(body['source_facts'], original['source_facts'])
        self.assertEqual(body['encoded_planning_fields'], original['encoded_planning_fields'])
        self.assertEqual(before, canonical(self.p))
        self.assertEqual(req['response_format']['json_schema']['schema']['properties']['actions']['items']['properties']['schedule']['type'], 'null')

    def test_transport_uses_actual_selected_typed_schema(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            clock = Clock(); m = Mock(); r = run.LimitedRunner(d, settings(), m, clock=clock, sleep=clock.sleep)
            row = load_slots()[0]; p=prepared(row)
            r.call(row, 'INITIAL', typed.candidate_payload(p,self.config), lambda v:typed.candidate_issues(p['planner']['bridge'],v))
            self.assertEqual(m.calls[0]['response_format']['json_schema']['schema'], typed.schemas(typed.ORDINARY)[1])
            self.assertNotEqual(m.calls[0]['response_format']['json_schema']['schema'], CANDIDATE)

    def test_plus_40_percent_remains_semantic_support_not_checked(self):
        self.c['actions'][0]['action'] = 'This activity increases exam scores by +40%.'
        result = validate_candidate(self.b,self.c)
        self.assertEqual(result['outcome'],'PASSED_ENCODED_CHECKS')
        self.assertEqual(result['semantic_support'],'NOT_CHECKED')
        self.assertEqual(typed.candidate_issues(self.b,self.c), [])

    def test_no_final_prompt_or_fallback_changes(self):
        for row in load_slots():
            p=prepared(row)
            self.assertEqual(sha(final_payload(p,settings()['generation_roles']['FINAL'],None,True)),row['prior_final_request_sha256'])

    def test_no_live_constructor_without_receipt(self):
        with patch.object(run, 'OUTPUT', HERE / 'NONEXISTENT_OFFLINE_RECEIPT'):
            with self.assertRaises(FileNotFoundError): run.ExactOpenAITransport()


if __name__ == '__main__':
    unittest.main(verbosity=2)
