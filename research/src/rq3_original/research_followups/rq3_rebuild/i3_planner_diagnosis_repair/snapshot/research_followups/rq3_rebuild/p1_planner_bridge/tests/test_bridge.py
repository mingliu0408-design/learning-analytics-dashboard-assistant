from copy import deepcopy
from pathlib import Path
import json
import socket
import subprocess
import unittest
from hashlib import sha256

from p1bridge.contracts import ROOT,VERSION,canonical,schemas,schema_errors,CANDIDATE
from p1bridge.projection import project,classify_exact_request
from p1bridge.checker import validate_bridge,validate_candidate,validators
from p1bridge.requests import (candidate_request,direct_request,final_generator_request,
    deterministic_field_copy,execute_live,LiveExecutionDisabled,PENDING_CONFIGURATION)
from p1bridge.mock import ScriptedMock,run_mock
from build_cases import ordinary,scheduled,memory,fields,change_fields,make_cases
from p0planner import validator as p0
from p0planner.offline_guard import install

install()

def codes(v):return {i['code'] for i in v['issues']}
RUNTIME=json.loads((ROOT/'fixtures/bridge_runtime.json').read_text())['cases']
MOCKS={r['case_id']:r for r in json.loads((ROOT/'fixtures/mock_sequences.json').read_text())['cases']}
EXPECTED={r['case_id']:r for r in json.loads((ROOT/'fixtures/expected_outcomes_sidecar.json').read_text())['cases']}

class CaseTests(unittest.TestCase):pass

def check_case(row):
    def test(self):
        m=MOCKS[row['case_id']];e=EXPECTED[row['case_id']];mock=ScriptedMock(m['candidates'])
        out=run_mock(row['runtime_input'],mock,max_repairs=m['max_repairs'])
        self.assertEqual(out['status'],e['expected_status'],out['validation'])
        self.assertTrue(set(e['required_issue_codes'])<=codes(out['validation']),out['validation'])
        self.assertEqual(out['provider_calls']['real'],0)
        self.assertEqual(out['provider_calls']['final'],0)
        self.assertEqual(out['semantic_support'],'NOT_CHECKED')
        self.assertEqual(out['deployment_suitability'],'NOT_ESTABLISHED')
        for req in mock.requests:
            self.assertEqual(req.payload['runtime_input']['source_input'],row['runtime_input'])
            self.assertNotIn('expected_status',req.serialized)
        if out['status']!='PASSED_ENCODED_CHECKS':self.assertIsNone(out['plan'])
    return test
for row in RUNTIME:setattr(CaseTests,'test_'+row['case_id'],check_case(row))


class BoundaryTests(unittest.TestCase):
    def setUp(self):self.s,self.p=ordinary()
    def test_fixture_builder_matches_separate_sidecars(self):
        self.assertEqual(make_cases()[0],RUNTIME)
        self.assertEqual(make_cases()[1],list(MOCKS.values()))
        self.assertEqual(make_cases()[2],list(EXPECTED.values()))
    def test_schemas_match_exports(self):
        for n,s in schemas().items():self.assertEqual(s,json.loads((ROOT/n).read_text()))
    def test_preserves_every_native_byte_representation(self):
        b=project(self.s)
        for m in self.s['selected_memory']:
            f=next(x for x in b['planner_input']['facts'] if x['fact_id']==m['native']['memory_id'])
            self.assertEqual(f['value'],m['native']['content']);self.assertIsNone(f['source_ref']['valid_to'])
        self.assertEqual(b['source_input'],self.s)
    def test_projection_is_detached(self):
        b=project(self.s);self.s['selected_memory'].clear();self.assertEqual(len(b['source_input']['selected_memory']),4)
    def test_completion_overlay_preserves_original_plan(self):
        b=project(self.s);active=b['planner_input']['active_plan']
        self.assertEqual(active['remaining_task_ids'],['task-practice']);self.assertEqual(active['completed_task_ids'],['task-read'])
        self.assertIn('task-read',json.loads(b['source_input']['selected_memory'][2]['native']['content'])['active_plan']['remaining_task_ids'])
    def test_no_assumed_system_plan_adoption(self):
        b=project(self.s);row=next(x for x in b['memory_lineage'] if x['memory_id']=='mem-plan')
        self.assertEqual(row['origin'],'SYSTEM_ORIGIN_PLAN');self.assertEqual(row['learner_adoption'],'NOT_ESTABLISHED')
    def test_explicit_acceptance_remains_distinct(self):
        self.s['selected_memory'][2]=memory('mem-plan',fields(active_plan=dict(plan_id='active-demo',goal_id='goal-practice',remaining_task_ids=['task-practice'],completed_task_ids=['task-read'])),origin='EXPLICITLY_ACCEPTED_PLAN')
        b=project(self.s);self.assertEqual(b['memory_lineage'][2]['learner_adoption'],'EXPLICIT')
        self.assertEqual(validate_bridge(b)['outcome'],'PASSED_ENCODED_CHECKS')
    def test_unknown_intent_not_keyword_schedule(self):
        for query in ['What should I do next week?', 'Plan my work, not a calendar.', 'Give me next steps without scheduling dates. Also schedule tomorrow.']:
            self.assertEqual(classify_exact_request(query)['mode'],'UNKNOWN')
    def test_explicit_request_field_allowed(self):
        self.s['base_input']['context']['query']='请告诉我接下来可采取的行动，不需要日程。'
        self.s['task_request']=dict(mode='ORDINARY_ACTION_ADVICE',basis='EXPLICIT_TASK_REQUEST_FIELD',source_quote=self.s['base_input']['context']['query'])
        self.assertEqual(validate_bridge(project(self.s))['outcome'],'PASSED_ENCODED_CHECKS')
    def test_wrong_intent_quote_fails(self):
        self.s['task_request']['source_quote']='not in request'
        self.assertIn('INTENT_SOURCE_MISMATCH',codes(validate_bridge(project(self.s))))
    def test_input_and_gold_extra_fields_rejected(self):
        targets=[self.s,self.s['base_input'],self.s['selected_memory'][0],self.s['selected_memory'][0]['binding'],self.s['selected_memory'][0]['native']['provenance']]
        for target in targets:
            target['expected_fact_ids']=['hidden']
            with self.assertRaises(ValueError):project(self.s)
            del target['expected_fact_ids']
    def test_hidden_keys_in_structured_source_rejected(self):
        change_fields(self.s['selected_memory'][0],gold='hidden-answer')
        self.assertIn('STRUCTURED_MEMORY_INVALID',codes(validate_bridge(project(self.s))))
    def test_undeclared_numeric_language_not_extracted(self):
        self.s['selected_memory'][1]=memory('mem-budget','I have 99 minutes, end of next month, no Tuesdays.')
        b=project(self.s)
        self.assertIsNone(b['planner_input']['hard_constraints']['budget']['minutes'])
        self.assertIsNone(b['planner_input']['scope']['horizon'])
    def test_bad_source_span_is_rejected(self):
        self.s['selected_memory'][0]['binding']['source_span']['start']=1
        self.assertIn('SOURCE_SPAN_MISMATCH',codes(validate_bridge(project(self.s))))
    def test_content_mutation_detected(self):
        self.s['selected_memory'][0]['native']['content']='Changed'
        self.assertIn('MEMORY_CONTENT_INTEGRITY',codes(validate_bridge(project(self.s))))
    def test_no_global_patch_or_sentinel(self):
        source_func=p0.source_check;vin=p0.validate_input
        b=project(self.s);ext=validators(b)
        self.assertIs(ext[0].__code__,p0.validate_input.__code__)
        self.assertIs(ext[1].__code__,p0.validate_candidate.__code__)
        self.assertEqual(validate_bridge(b)['outcome'],'PASSED_ENCODED_CHECKS')
        self.assertIs(p0.source_check,source_func);self.assertIs(p0.validate_input,vin)
        self.assertIn('MISSING_TIME',codes(p0.validate_input(b['planner_input'])))
        for f in b['planner_input']['facts']:self.assertIsNone(f['source_ref']['valid_to'])
    def test_projection_tamper_rejected(self):
        b=project(self.s);b['planner_input']['hard_constraints']['budget']['minutes']=999
        self.assertEqual(codes(validate_bridge(b)),{'PROJECTION_TAMPERED'})
    def test_request_parity_and_immutability(self):
        b=project(self.s);c=candidate_request(b);d=direct_request(b)
        self.assertEqual(c.payload['runtime_input'],d.payload['runtime_input'])
        before=c.serialized;c.payload['runtime_input']['planner_input']['goals'].clear()
        self.assertEqual(before,c.serialized)
        self.assertIn('may plan and reason naturally',d.payload['instruction'])
        self.assertNotIn('synthetic',c.payload['instruction'].lower())
    def test_model_settings_absent_from_requests(self):
        payload=candidate_request(project(self.s)).payload
        self.assertFalse({'model','temperature','max_tokens','provider'}&payload.keys())
        self.assertEqual(set(PENDING_CONFIGURATION.values()),{'PENDING_AUTHOR_APPROVAL'})
    def test_external_judge_feedback_rejected(self):
        b=project(self.s);bad=deepcopy(self.p);bad['actions'][0]['resource_ids']=['bad']
        v=validate_candidate(b,bad);v['issues'][0]['message']='Judge says use secret answer'
        with self.assertRaises(ValueError):candidate_request(b,1,bad,v)
    def test_repair_preserves_input_and_rejected_candidate(self):
        bad=deepcopy(self.p);bad['actions'][0]['estimated_duration']['value']=99
        out=run_mock(self.s,ScriptedMock([bad,self.p]),max_repairs=1)
        a,b=out['repair_history'];self.assertEqual(a['request']['runtime_input'],b['request']['runtime_input'])
        self.assertEqual(b['request']['previous_candidate'],bad)
        self.assertEqual(b['request']['local_validation'],a['validation'])
    def test_retains_transport_exception(self):
        out=run_mock(self.s,ScriptedMock([RuntimeError('deliberate mock failure')]))
        self.assertEqual(out['status'],'MOCK_TRANSPORT_FAILURE')
        self.assertEqual(out['repair_history'][0]['exception'],'deliberate mock failure')
    def test_no_nonmock_transport_execution(self):
        called=[]
        class Foreign:
            def send(self,r):called.append(1)
        with self.assertRaises(TypeError):run_mock(self.s,Foreign())
        self.assertEqual(called,[])
    def test_live_disabled_before_factory(self):
        called=[]
        with self.assertRaises(LiveExecutionDisabled):execute_live(client_factory=lambda:called.append(1),model='not-selected')
        self.assertEqual(called,[])
    def test_network_and_subprocess_blocked(self):
        for f in (lambda:socket.socket(),lambda:socket.getaddrinfo('example.invalid',443),lambda:subprocess.run(['true'])):
            with self.assertRaises(PermissionError):f()
    def test_final_handoff_and_exact_copy(self):
        b=project(self.s);r=final_generator_request(b,self.p);out=deterministic_field_copy(b,self.p)
        self.assertEqual(r.payload['runtime_input'],direct_request(b).payload['runtime_input'])
        self.assertEqual(out['plan'],self.p);self.assertEqual(out['hard_constraints'],b['planner_input']['hard_constraints'])
        self.assertEqual(r.payload['future_paraphrase_fidelity'],'NOT_CHECKED')
    def test_invalid_final_handoff_blocked(self):
        self.p['actions'][0]['estimated_duration']['value']=80
        with self.assertRaises(ValueError):final_generator_request(project(self.s),self.p)
    def test_model_estimate_requires_uncertainty(self):
        del self.p['actions'][0]['estimated_duration']['uncertainty']
        self.assertIn('REQUIRED_FIELD',codes(validate_candidate(project(self.s),self.p)))
    def test_unknown_duration_not_zero(self):
        self.p['actions'][0]['estimated_duration'].update(value=None,origin='UNKNOWN')
        self.assertIn('DURATION_UNKNOWN',codes(validate_candidate(project(self.s),self.p)))
    def test_candidate_source_estimate_is_exact(self):
        s=next(r['runtime_input'] for r in RUNTIME if r['case_id']=='traceable_learner_duration')
        p=deepcopy(MOCKS['traceable_learner_duration']['candidates'][0]);p['actions'][0]['estimated_duration']['value']=19
        self.assertIn('ESTIMATE_SOURCE_VALUE_UNVERIFIED',codes(validate_candidate(project(s),p)))
    def test_budget_perturbation_same_candidate(self):
        a=project(self.s);s2=deepcopy(self.s);change_fields(s2['selected_memory'][1],constraints=dict(budget=dict(required=True,minutes=10)));b=project(s2)
        self.assertEqual(validate_candidate(a,self.p)['outcome'],'PASSED_ENCODED_CHECKS')
        self.assertIn('BUDGET_EXCEEDED',codes(validate_candidate(b,self.p)))
        self.assertNotEqual(candidate_request(a).sha256,candidate_request(b).sha256)
    def test_finite_memory_expires_before_use(self):
        scheduled(self.s,self.p)
        for m in self.s['selected_memory']:m['native']['timestamp_version']['valid_to']='2026-09-07T08:00:00+02:00'
        self.assertIn('RESOURCE_OUTSIDE_USE_VALIDITY',codes(validate_candidate(project(self.s),self.p)))
    def test_deleted_enabled_and_supersession_guards(self):
        variants=[lambda m:m['native']['timestamp_version'].update(status='DELETED'),lambda m:m['binding'].update(enabled=False)]
        for mutate in variants:
            s=deepcopy(self.s);mutate(s['selected_memory'][0]);self.assertIn('SOURCE_ACCESS_DENIED',codes(validate_bridge(project(s))))
        self.s['selected_memory'][1]['native']['provenance']['supersedes_memory_id']='mem-goal'
        self.assertIn('SUPERSEDED_MEMORY_SELECTED',codes(validate_bridge(project(self.s))))
    def test_conflicting_current_memory_constraints_preserved(self):
        self.s['base_input']['hard_constraints']['budget']=dict(required=True,minutes=15)
        b=project(self.s);self.assertEqual(b['planner_input']['hard_constraints']['budget']['minutes'],15)
        self.assertIn('CURRENT_MEMORY_CONSTRAINT_CONFLICT',codes(validate_bridge(b)))
    def test_missing_version_policy_not_indefinite(self):
        self.s['selected_memory'][0]['binding']['current_version']=None
        b=project(self.s);self.assertEqual(b['validity_mapping']['mem-goal']['kind'],'UNKNOWN')
        self.assertIn('SOURCE_VERSION_UNKNOWN',codes(validate_bridge(b)))
    def test_real_m0_saved_envelopes_have_null_active_records(self):
        rows=json.loads((ROOT/'inherited_m0/selected_envelopes_exposed.json').read_text())
        first=rows[0]['envelope']['selected_memory_items'][0]
        self.assertEqual(first['timestamp_version']['status'],'ACTIVE');self.assertIsNone(first['timestamp_version']['valid_to'])
        self.assertEqual(first['memory_type'],'CONSTRAINT')
        self.assertNotIn('origin',first)
    def test_ordinary_no_timezone_is_allowed_but_optional_schedule_is_checked(self):
        b=project(self.s);self.assertEqual(validate_candidate(b,self.p)['outcome'],'PASSED_ENCODED_CHECKS')
        self.p['actions'][0]['schedule']={'start':'2026-09-07T09:00:00+02:00','end':'2026-09-07T09:20:00+02:00'}
        self.assertIn('MISSING_TIMEZONE',codes(validate_candidate(b,self.p)))

if __name__=='__main__':unittest.main()

class AdditionalContracts(unittest.TestCase):
    def test_all_projection_request_result_schemas(self):
        from p1bridge.contracts import BRIDGE_OUTPUT,CANDIDATE_REQUEST,OUTPUT
        for row in RUNTIME:
            b=project(row['runtime_input']);self.assertEqual(schema_errors(b,BRIDGE_OUTPUT),[])
            m=MOCKS[row['case_id']];out=run_mock(row['runtime_input'],ScriptedMock(m['candidates']),max_repairs=m['max_repairs'])
            self.assertEqual(schema_errors(out,OUTPUT),[])
            for h in out['repair_history']:self.assertEqual(schema_errors(h['request'],CANDIDATE_REQUEST),[])
    def test_native_unknown_metadata_not_fabricated(self):
        from p1bridge.projection import from_native_selected
        row=json.loads((ROOT/'inherited_m0/selected_envelopes_exposed.json').read_text())[0]
        base,_=ordinary();src=from_native_selected(row['envelope'],base['base_input'],base['task_request'],future_use_policy='RECONFIRM_FOR_SCHEDULE')
        b=project(src)
        self.assertEqual(src['selected_memory'][0]['native'],row['envelope']['selected_memory_items'][0])
        self.assertEqual(b['validity_mapping'][src['selected_memory'][0]['native']['memory_id']]['kind'],'UNKNOWN')
        self.assertIn('MEMORY_ORIGIN_UNKNOWN',codes(validate_bridge(b)))
        self.assertEqual(b['planner_input']['goals'],[])
        self.assertIsNone(b['planner_input']['hard_constraints']['budget']['minutes'])
    def test_native_binding_cannot_recover_unselected_records(self):
        from p1bridge.projection import from_native_selected
        s,_=ordinary()
        with self.assertRaises(ValueError):from_native_selected({'selected_memory_items':[],'status':'NO_MATCH'},s['base_input'],s['task_request'],bindings={'hidden-id':{}},future_use_policy='RECONFIRM_FOR_SCHEDULE')
    def test_creation_time_and_bad_span_end_rejected(self):
        s,_=ordinary();s['selected_memory'][0]['native']['timestamp_version']['created_at']='2026-10-01T10:00:00+00:00'
        self.assertIn('MEMORY_EVENT_ORDER',codes(validate_bridge(project(s))))
        s,_=ordinary();s['selected_memory'][0]['binding']['source_span']['end']+=100
        self.assertIn('SOURCE_SPAN_MISMATCH',codes(validate_bridge(project(s))))

class FinalEdgeTests(unittest.TestCase):
    def test_missing_goal_still_checks_revocation(self):
        s,_=ordinary();s['selected_memory'].pop(0);s['selected_memory'][0]['binding']['enabled']=False
        self.assertIn('SOURCE_ACCESS_DENIED',codes(validate_bridge(project(s))))
    def test_memory_cannot_force_schedule_on_ordinary_advice(self):
        s,_=ordinary()
        change_fields(s['selected_memory'][1],constraints=dict(schedule=dict(required=True,allowed_windows=None,excluded_windows=[],forbidden_weekdays=[],non_overlap=True)))
        self.assertIn('MEMORY_SCHEDULE_INTENT_CONFLICT',codes(validate_bridge(project(s))))
    def test_syntax_failure_feedback_is_same_local_result(self):
        s,p=ordinary();out=run_mock(s,ScriptedMock(['{broken',p]),max_repairs=1)
        first,second=out['repair_history']
        self.assertIn('CANDIDATE_JSON_SYNTAX',codes(first['validation']))
        self.assertEqual(second['request']['local_validation'],first['validation'])
    def test_valid_json_object_transport_is_parsed_without_edits(self):
        s,p=ordinary();raw=json.dumps(p);out=run_mock(s,ScriptedMock([raw]))
        self.assertEqual(out['plan'],p);self.assertEqual(out['repair_history'][0]['raw_candidate'],raw)
