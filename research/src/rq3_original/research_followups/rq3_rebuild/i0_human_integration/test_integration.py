"""Adversarial synthetic acceptance through actual E1, R0, native M1 and P1."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fixtures import *
from utils.c4_dashboard_scoped.aggregate import aggregate
from utils.c4_dashboard_scoped.scope import ScopeError, digest
from utils.c4_rebuild.service import ResearchService, planner_base
from utils.c4_rebuild.contracts import LiveExecutionDisabled, reject_sidecars
from utils.c4_rebuild.language import numeric_constraint, intent, purpose
from utils.c4_rebuild.memory import MemoryBundle
from utils.c4_rebuild.planning import (source_bindings, bridge_from_m1, validate_bridge,
    validate_candidate, project, empty_envelope, p1p)
from utils.c4_rebuild.generation import check_final_fields, Telemetry, prepare_final_from_candidate
from utils.c4_rebuild.sources import source_template, check_source


def plan(bridge, minutes=10):
    return dict(plan_id='SYNTHETIC_CHECKER_PLAN', goal_id='current-request',
        goal=bridge['planner_input']['context']['query'],
        actions=[dict(step_id='step-1', task_id='synthetic-task-1', kind='TASK',
            action='Review the explicitly requested example.',
            estimated_duration=dict(value=minutes, unit='minutes', origin='MODEL_ESTIMATE',
                evidence_refs=[], uncertainty='Synthetic model estimate; actual duration unknown.'),
            resource_ids=[], dependencies=[], schedule=None, completion_check='Compare the worked steps.',
            evidence_refs=['current-request'], brief_rationale='Address the current explicit request.')],
        evidence_refs=['current-request'], continues_plan_id=None, brief_rationale='Synthetic mechanical diagnostic only.')


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.counter = 0

    def memory(self, index=0, **kw):
        self.counter += 1
        p = Path(self.tmp.name)/str(self.counter)
        p.mkdir()
        return memory_source(index, p, **kw)[0]

    def prepare(self, mode=Mode.S5_FULL, *, memory=None, router=None, **kw):
        s = ResearchService(enabled=True, snapshot=snapshot(), router=router or SyntheticRouter(),
                            retriever=rag_source(), memory=memory or self.memory())
        return s.prepare(request(mode, **kw))

    def test_six_modes_actual_e1_to_final_facts(self):
        q='Summarise my learning this week across resources, lecture, debate and reflection using the week 1 lecture worksheet.'
        outputs={m:self.prepare(m,query=q) for m in Mode}
        a=outputs[Mode.S0_PAGE_ONLY]['trace']['e1_fact_trace']
        b=outputs[Mode.S1_CROSS_PAGE_EVIDENCE]['trace']['e1_fact_trace']
        self.assertTrue(b);self.assertGreater(len(b),len(a))
        self.assertEqual({f['domain'] for f in a},{'Lecture'})
        self.assertIn('Resources',{f['domain'] for f in b})
        for p in outputs.values():
            self.assertTrue(all(x['final_value_verified'] for x in p['trace']['e1_fact_trace']))
            self.assertTrue(p['trace']['memory_retention_complete']);self.assertTrue(p['trace']['course_retention_complete'])
            self.assertEqual(p['trace']['generation_calls'],0)

    def test_legitimate_single_page_no_forced_difference(self):
        q='Summarise resource views for this week.'
        a=self.prepare(Mode.S0_PAGE_ONLY,query=q,page='Resources')
        b=self.prepare(Mode.S1_CROSS_PAGE_EVIDENCE,query=q,page='Resources')
        self.assertEqual(a['final_request']['runtime_input']['evidence'],b['final_request']['runtime_input']['evidence'])

    def test_overview_no_double_count(self):
        a=self.prepare(Mode.S0_PAGE_ONLY,page='Overview')
        b=self.prepare(Mode.S1_CROSS_PAGE_EVIDENCE,page='Overview')
        self.assertEqual(a['final_request']['runtime_input']['evidence'],b['final_request']['runtime_input']['evidence'])
        ids=[(x['domain'],x['metric']) for x in b['trace']['e1_fact_trace']]
        self.assertEqual(len(ids),len(set(ids)))

    def test_wrong_learner_course_window_fail_before_routing(self):
        router=SyntheticRouter()
        s=ResearchService(enabled=True,snapshot=snapshot(),router=router)
        r=request()
        for scope in (replace(r.scope,learner_id='unauthorised'),replace(r.scope,course_id='other'),
                      replace(r.scope,start=END,end='2026-09-14T00:00:00+02:00')):
            with self.subTest(scope=scope):
                with self.assertRaises((ScopeError,ValueError)):s.prepare(replace(r,scope=scope))
        self.assertEqual(router.inputs,[])

    def test_missing_versus_zero(self):
        snap=snapshot();tables={k:[dict(r) for r in rows] for k,rows in snap.tables.items()}
        tables['moodle']=[]
        zero=aggregate(snapshot(tables),request().scope)
        tables['moodle']=None
        missing=aggregate(snapshot(tables),request().scope)
        f=lambda b:next(x.value for x in b.facts if x.metric=='resource_views')
        self.assertEqual(f(zero),0);self.assertIsNone(f(missing))

    def test_rag_yes_reaches_actual_scorer_without_second_veto(self):
        r=rag_source();q=request(Mode.S2_EVIDENCE_RAG,query='Summarise the week 1 lecture worksheet.')
        from utils import course_material_retriever as legacy
        with patch.object(legacy,'should_use_course_retrieval',side_effect=AssertionError('SECOND_GATE')):
            p=ResearchService(enabled=True,snapshot=snapshot(),router=SyntheticRouter(),retriever=r).prepare(q)
        self.assertEqual(r.calls,1);self.assertTrue(p['trace']['course_returned_ids'])

    def test_rag_no_permission_and_off_mode_zero_search(self):
        for mode,route,access in [(Mode.S2_EVIDENCE_RAG,SyntheticRouter(False,True,True),Access(True,False,False,'SYN')),
            (Mode.S2_EVIDENCE_RAG,SyntheticRouter(),Access()), (Mode.S0_PAGE_ONLY,SyntheticRouter(),Access(True,True,True,'SYN'))]:
            r=rag_source()
            ResearchService(enabled=True,snapshot=snapshot(),router=route,retriever=r).prepare(request(mode,access=access))
            self.assertEqual(r.calls,0)

    def test_missing_invalid_route_never_yes(self):
        s=ResearchService(enabled=True,snapshot=snapshot(),retriever=rag_source())
        p=s.prepare(request());self.assertFalse(p['trace']['activation']['rag'])
        class Bad:
            def route(self,x):return {'rag_required':'yes'}
        s.router=Bad()
        with self.assertRaises(ValueError):s.prepare(request())

    def test_p3_timing_and_exact_four_field_input(self):
        router=SyntheticRouter(False,True,True)
        p=self.prepare(router=router,query='Remind me of my goal and suggest next steps without dates.')
        self.assertEqual(set(router.inputs[0]),{'current_query','current_page','dashboard_context','visible_conversation_history'})
        self.assertNotIn('quadratic formula',json.dumps(router.inputs[0]))
        e=p['trace']['ordered_events'];self.assertLess(e.index('P3_ON_ORIGINAL_FOUR_FIELDS'),e.index('M1_READ_ONLY_LINKED_RETRIEVAL'))

    def test_missing_course_evidence_is_typed_absence(self):
        r=rag_source(empty=True)
        p=ResearchService(enabled=True,snapshot=snapshot(),router=SyntheticRouter(),retriever=r).prepare(request(Mode.S2_EVIDENCE_RAG))
        self.assertEqual(r.calls,1)
        self.assertIn({'source_kind':'COURSE_RAG','status':'NO_RESULT'},p['final_request']['runtime_input']['evidence']['typed_absence'])

    def test_real_linked_read_cloned_reopened_unchanged(self):
        m=self.memory(12)
        from state_harness import ReadOnlyStore
        from utils.c4_rebuild.memory import clone_native_states
        cloned=clone_native_states(m.databases,Path(self.tmp.name)/'clones')
        m.databases=cloned
        q=request(query='Continue my plan and suggest next steps without dates.')
        b=m.read(q,'PLAN_CONTINUATION')
        self.assertGreaterEqual(len(b.envelope['facts']),3)
        self.assertTrue(b.trace['readonly_state_unchanged'])
        with ReadOnlyStore(cloned[COURSE],clock=lambda:NOW) as store:
            self.assertEqual(store.integrity_check()['integrity_check'],'ok')

    def test_native_open_ended_policy_and_raw_text_survive(self):
        p=self.prepare(query='Remind me of my goal and suggest next steps without dates.')
        b=p['planner']['bridge']
        self.assertEqual(set(x['kind'] for x in b['validity_mapping'].values()),{'NO_DECLARED_EXPIRY'})
        self.assertTrue(all(x['native']['timestamp_version']['valid_to'] is None for x in b['source_input']['selected_memory']))
        self.assertEqual(b['i0_diagnostics']['raw_state_checkability'],'NOT_CHECKABLE')
        self.assertIn('twenty minutes',json.dumps(p['final_request']))

    def test_actual_saved_m1_envelopes_without_authority_remain_unknown(self):
        source=json.loads((HERE.parent/'m1_memory_completeness/PLANNER_ENVELOPE_SYNTHETIC_FIXTURES.json').read_text())
        for row in source['envelopes']:
            env=row['envelope'];r=request(query='Continue my plan without dates.')
            empty=self.prepare(Mode.S1_CROSS_PAGE_EVIDENCE)
            # P1 base is explicit scaffolding; missing native authority is NOT filled.
            b=bridge_from_m1(MemoryBundle(env,{},{}),
                self.prepare(Mode.S4_EVIDENCE_PLANNING)['planner']['bridge']['source_input']['base_input'],
                intent('Summarise my learning this week.'),'RECONFIRM_FOR_SCHEDULE')
            self.assertEqual(len(b['source_input']['selected_memory']),len(env['facts']))
            self.assertTrue(all(x['kind']=='UNKNOWN' for x in b['validity_mapping'].values()))
            self.assertNotEqual(validate_bridge(b)['outcome'],'PASSED_ENCODED_CHECKS')

    def test_expired_revoked_missing_ambiguous_memory(self):
        for index in (8,20,21,24,11):
            with self.subTest(index=index):
                m=self.memory(index)
                q=request(query='Continue my plan and remind me of my goal without dates.',memory_purpose='PLAN_CONTINUATION',visible_controls='SYNTHETIC_UI_PURPOSE_SELECTION')
                b=m.read(q,'PLAN_CONTINUATION')
                self.assertTrue(b.trace['readonly_state_unchanged'])
                for f in b.envelope['facts']:
                    self.assertIn(f['consent_status'],('GRANTED','NOT_REQUIRED'))
                    self.assertEqual(f['learner_id'],LEARNER)
                if index==8:self.assertEqual(b.envelope['facts'],[])
                if index==11:self.assertEqual(b.envelope['status'],'AMBIGUOUS');self.assertIsNone(b.envelope['chosen_active_plan_id'])

    def test_unknown_purpose_not_resolved_from_fixture_or_plan_label(self):
        m=self.memory()
        p=self.prepare(memory=m,query='Suggest a useful study strategy.')
        self.assertEqual(m.calls,0);self.assertEqual(p['trace']['purpose_resolution']['value'],'UNKNOWN')
        self.assertEqual(purpose('SYN-M1-LINKED-01')['value'],'UNKNOWN')

    def test_ordinary_language_beyond_two_p1_phrases(self):
        for q in ('Suggest useful next steps.','Help me review my progress without dates.','请总结本周并给出建议。'):
            self.assertEqual(intent(q)['mode'],'ORDINARY_ACTION_ADVICE')
        self.assertEqual(intent('Please make me a timetable.')['mode'],'EXPLICIT_SCHEDULE')
        self.assertEqual(intent('Do not schedule my tasks.')['mode'],'UNKNOWN')

    def test_schedule_missing_timezone_clarifies(self):
        p=self.prepare(query='Please schedule my tasks.',schedule_horizon={'start':START,'end':END},allowed_windows=({'start':START,'end':END},))
        self.assertIn('MISSING_TIMEZONE',p['final_request']['clarification_required'])
        self.assertEqual(p['planner']['status'],'NEEDS_INFORMATION');self.assertIsNone(p['planner']['request'])

    def test_supported_natural_constraint_is_source_derived_and_enforced(self):
        m=self.memory(change=explicit_minutes_source)
        p=self.prepare(memory=m,query='Remind me of my goal and suggest next steps without dates.')
        b=p['planner']['bridge']
        self.assertEqual(b['planner_input']['hard_constraints']['budget']['minutes'],15)
        parsed=b['i0_diagnostics']['numeric_parses'][0]
        self.assertEqual(parsed['source_span']['text'],'I have 15 minutes.')
        self.assertEqual(validate_candidate(b,plan(b,10))['outcome'],'PASSED_ENCODED_CHECKS')
        self.assertIn('BUDGET_EXCEEDED',{x['code'] for x in validate_candidate(b,plan(b,20))['issues']})

    def test_superseded_completion_not_promoted(self):
        p=self.prepare(memory=self.memory(25),query='Continue my plan and suggest next steps without dates.')
        self.assertEqual(p['final_request']['runtime_input']['memory']['completed_action_ids'],[])
        self.assertEqual(p['planner']['bridge']['planner_input']['completed_tasks'],[])

    def test_two_future_policies_remain_explicit_alternatives(self):
        m=self.memory(change=explicit_minutes_source)
        for policy,should_pass in [('RECONFIRM_FOR_SCHEDULE',False),('WARN_SNAPSHOT_ONLY',True)]:
            p=self.prepare(memory=m,query='Please schedule my tasks for the quadratic formula goal using the 15 minutes I have.',future_policy=policy,
                memory_purpose='GOAL_RECALL',visible_controls='SYNTHETIC_EXPLICIT_PURPOSE',
                schedule_timezone='Europe/Oslo',
                schedule_horizon={'start':'2026-09-03T00:00:00+02:00','end':'2026-09-04T00:00:00+02:00'},
                allowed_windows=({'start':'2026-09-03T09:00:00+02:00','end':'2026-09-03T10:00:00+02:00'},))
            b=p['planner']['bridge'];c=plan(b)
            self.assertTrue(b['source_input']['selected_memory'])
            c['actions'][0]['schedule']={'start':'2026-09-03T09:00:00+02:00','end':'2026-09-03T09:10:00+02:00'}
            v=validate_candidate(b,c)
            self.assertEqual(v['outcome']=='PASSED_ENCODED_CHECKS',should_pass,v)
            self.assertIn('OPEN_ENDED_FUTURE_UNCONFIRMED',{x['code'] for x in v['issues']})

    def test_accepted_action_edge_is_not_plan_adoption(self):
        p=self.prepare(memory=self.memory(28),query='Continue my plan and suggest next steps without dates.')
        env=p['final_request']['runtime_input']['memory'];b=p['planner']['bridge']
        self.assertTrue(env['accepted_action_ids'])
        self.assertTrue(all(x['learner_adoption']=='NOT_ESTABLISHED' for x in b['memory_lineage']))
        self.assertIsNone(b['planner_input']['active_plan'])
        self.assertEqual({x['task_id'] for x in b['planner_input']['completed_tasks']},set(env['accepted_action_ids']))

    def test_no_planner_work_when_off_information_parity(self):
        m=self.memory();router=SyntheticRouter(False,True,True)
        s=ResearchService(enabled=True,snapshot=snapshot(),router=router,memory=m)
        q=request(Mode.S3_EVIDENCE_MEMORY,query='Remind me of my goal and suggest next steps without dates.')
        a=s.prepare(q);self.assertEqual(s.planner_work,0)
        b=s.prepare(replace(q,mode=Mode.S5_FULL));self.assertEqual(s.planner_work,1)
        self.assertEqual(a['final_request']['runtime_input'],b['final_request']['runtime_input'])
        self.assertIn('natural planning and steps',a['final_request']['instruction'])

    def test_unexpanded_and_linked_same_native_state(self):
        m=self.memory();q=request(query='Remind me of my goal and how much study time I said I had.')
        a=m.read(q,'GOAL_RECALL');m.expand=False;b=m.read(q,'GOAL_RECALL')
        self.assertEqual(a.trace['original_seed_ids'],b.trace['original_seed_ids'])
        self.assertGreaterEqual(len(a.envelope['facts']),len(b.envelope['facts']))

    def test_budget_does_not_reintroduce_omitted_memory(self):
        m=self.memory(29);q=request(query='Continue my plan and suggest next steps without dates.')
        for budget in (900,2200):
            p=ResearchService(enabled=True,snapshot=snapshot(),router=SyntheticRouter(False,True,True),memory=m,evidence_budget=budget).prepare(q)
            self.assertTrue(p['trace']['memory_retention_complete'])
            final=json.dumps(p['final_request']['runtime_input']['memory']['facts'])
            for omitted in p['trace']['budget_omitted_ids']:self.assertNotIn(omitted,final)
            if budget==900:
                self.assertTrue(set(p['trace']['memory_returned_ids'])&set(p['trace']['budget_omitted_ids']))

    def test_source_sidecar_nested_fields_rejected(self):
        for x in ({'evidence':{'expected_fact_ids':['x']}},{'gold':'x'},{'nested':[{'human_rating':5}]}):
            with self.assertRaises(ValueError):reject_sidecars(x)

    def test_cache_keys_scope_state_and_model_visible_request(self):
        s=ResearchService(enabled=True,snapshot=snapshot())
        r=request(Mode.S1_CROSS_PAGE_EVIDENCE)
        a=s.prepare(r)['trace']['request_cache_key']
        self.assertEqual(a,s.prepare(r)['trace']['request_cache_key'])
        for change in (dict(memory_state_version='NEXT'),dict(source_version='NEXT'),dict(query='Summarise resource views this week.')):
            self.assertNotEqual(a,s.prepare(replace(r,**change))['trace']['request_cache_key'])

    def test_unsupported_plus40_claim_is_still_not_checked(self):
        b=self.prepare(Mode.S4_EVIDENCE_PLANNING)['planner']['bridge']
        c=plan(b);c['actions'][0]['action']='This guarantees a 40 percent improvement in your final grade.'
        v=validate_candidate(b,c)
        self.assertEqual(v['outcome'],'PASSED_ENCODED_CHECKS');self.assertEqual(v['semantic_support'],'NOT_CHECKED')

    def test_final_generator_can_corrupt_valid_plan(self):
        b=self.prepare(Mode.S4_EVIDENCE_PLANNING)['planner']['bridge'];c=plan(b)
        o={'answer':'SYNTHETIC TEST FIELD','cited_evidence_ids':['current-request'],'plan_fields':c}
        v=check_final_fields(o,['current-request'],accepted_plan=c)
        self.assertEqual(v['mechanical_status'],'PASS');self.assertEqual(v['answer_plan_fidelity'],'NOT_CHECKED')
        o['plan_fields']=dict(c,goal='changed')
        self.assertEqual(check_final_fields(o,['current-request'],accepted_plan=c)['mechanical_status'],'FAIL')

    def test_disabled_transport_and_distinct_telemetry(self):
        s=ResearchService(enabled=True,snapshot=snapshot())
        with self.assertRaises(LiveExecutionDisabled):s.execute(request())
        t=Telemetry()
        for event in ('REQUEST_PREPARED','RAW_OUTPUT_RECEIVED','TRANSPORT_FAILURE','SEMANTIC_VALIDATOR_FAILURE','ACCEPTED_TERMINAL'):
            t.record(event,phase='FINAL',request_id='SYNTHETIC',payload=None)
        self.assertEqual(len({x['event'] for x in t.events}),5)

    def test_validated_plan_to_same_final_request_and_tamper_rejection(self):
        p=self.prepare(Mode.S4_EVIDENCE_PLANNING);c=plan(p['planner']['bridge'])
        final=prepare_final_from_candidate(p,c)
        self.assertEqual(final['runtime_input'],p['final_request']['runtime_input'])
        self.assertEqual(final['structured_plan'],c);self.assertFalse(final['execution_authorised'])
        p['final_request']['runtime_input']['context']['current_query']='tampered'
        with self.assertRaises(ValueError):prepare_final_from_candidate(p,c)

    def test_synthetic_route_cannot_be_mislabelled_as_real_source_execution(self):
        original=snapshot()
        live=Snapshot(original.version,{k:[dict(r) for r in rows] for k,rows in original.tables.items()},
            original.specs,original.roster,original.calendars,'LIVE')
        s=ResearchService(enabled=True,snapshot=live,router=SyntheticRouter())
        with self.assertRaisesRegex(ValueError,'SYNTHETIC_ROUTE_ON_REAL_SOURCE'):
            s.prepare(request())

    def test_original_p1_not_mutated_by_i0_projection(self):
        from p1bridge.projection import project as original
        code=original.__code__;globals_=dict(original.__globals__)
        self.prepare(query='Remind me of my goal and suggest next steps without dates.')
        self.assertIs(original.__code__,code);self.assertEqual(original.__globals__,globals_)


class NormalisationTests(unittest.TestCase):
    def test_supported_explicit_number_variants(self):
        for text,value in [('I have 15 minutes.',15),('I have only twenty minutes.',20),
                           ('I have a quarter of an hour.',15),('我只有30分钟。',30)]:
            p=numeric_constraint(text,'source');self.assertEqual(p['parsed_value'],value)
            self.assertEqual(p['unit'],'minutes');self.assertEqual(p['source_span']['text'],text)

    def test_counterexamples_remain_raw(self):
        for text in ['I do not have 15 minutes.','I have 15 hours.','I had 15 minutes yesterday.',
                     'I have twenty-one minutes.','I have about 15 minutes.',
                     'I have 15 minutes every weekday.','I have 15 minutes, unless I work late.',
                     'Next Friday at 3.','I have only twenty minutes for maths after work on weekdays.']:
            with self.subTest(text=text):
                p=numeric_constraint(text,'source');self.assertIsNone(p['parsed_value']);self.assertEqual(p['status'],'NOT_CHECKABLE')

    def test_unknown_source_manifests_fail_closed(self):
        m=source_template('echo');r=check_source(m,HERE)
        self.assertFalse(r['ready']);self.assertIn('PERMISSION_REF_UNKNOWN',r['gaps'])

    def test_pickle_and_material_week_never_become_weekly_events(self):
        m=source_template('gdocs');m.update(path='opaque.pkl',format='pickle',observation='content_week')
        r=check_source(m,HERE)
        self.assertIn('TRUSTED_REFLECTION_EXPORT_REQUIRED',r['gaps'])
        self.assertIn('WEEKLY_OBSERVATION_UNSUPPORTED',r['gaps'])


if __name__=='__main__':unittest.main(verbosity=2)
