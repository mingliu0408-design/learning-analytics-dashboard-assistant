"""Real CSV -> original worker checks; only the provider transport is mocked."""
import csv
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from public_runtime.core import PublicAssistant, CoreFailure, ROOT
from public_runtime.dashboard import build_context, learners, SOURCES, DATA
from tests.test_runtime import ExactMock

class DashboardRuntime(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='lad-dashboard-tests-')
        self.engine=PublicAssistant(uuid.uuid4().hex,storage_root=self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def source(self,learner='301101',first=1,last=1,page='Overview'):
        self.engine.bind_dashboard(learner,first,last)
        return self.engine.call('source',query='Summarize my learning activity',page=page)
    def raw(self,name):
        with (DATA/SOURCES[name]).open(newline='') as source:return list(csv.DictReader(source))
    def test_actual_selected_learner_week_and_raw_counts(self):
        source=self.source()
        scope=source['source']['scope']
        self.assertEqual(scope['learner_id'],'301101')
        self.assertEqual(scope['start'],'2025-09-29T00:00:00+00:00')
        self.assertEqual(scope['end'],'2025-10-06T00:00:00+00:00')
        expected=sum(r['ID']=='301101' and int(r['Week'])==1 and r['Event']=='Resources_views' for r in self.raw('moodle'))
        fact=source['primary']['dashboard_context']['activity']['Resources']['resource_views']
        self.assertEqual(fact['value'],expected)
        self.assertEqual(fact['status'],'OBSERVED_PARTIAL_COVERAGE')
        other=self.source('301102',2,2)
        expected_other=sum(r['ID']=='301102' and int(r['Week'])==2 and r['Event']=='Resources_views' for r in self.raw('moodle'))
        self.assertEqual(other['primary']['dashboard_context']['activity']['Resources']['resource_views']['value'],expected_other)
        self.assertNotEqual(source['primary_sha256'],other['primary_sha256'])
        self.assertNotIn('301101',json.dumps(other['primary']))
        self.assertNotIn('learner-001',json.dumps(other['primary']))
    def test_no_historical_seed_or_other_visitor_memory_and_correction(self):
        self.source()
        self.assertEqual(self.engine.memory_list(),[])
        saved=self.engine.memory_write('dashboard-301101','My learning goal is understanding analytics','GOAL',consent=True)
        self.assertTrue(saved['accepted'])
        updated=self.engine.memory_write('dashboard-301101','My learning goal is understanding course analytics','GOAL',consent=True,target_memory_id=saved['memory_id'])
        self.assertTrue(updated['accepted'])
        self.engine.bind_dashboard('301101',2,2)
        self.assertEqual(self.engine.memory_list()[0]['content'],'My learning goal is understanding course analytics')
        result=self.engine.components('What learning goal did I state?',page='Reflection',rag=False,memory=True)
        facts=result['prepared']['final_request']['runtime_input']['memory']['facts']
        self.assertEqual(len(facts),1)
        self.assertEqual(facts[0]['source_ref']['origin'],'USER')
        self.assertEqual(facts[0]['source_ref']['claim_basis'],'EXPLICIT_USER_STATEMENT')
        self.assertTrue(result['readonly_state_unchanged'])
        self.engine.bind_dashboard('301102',1,1)
        self.assertEqual(self.engine.memory_list(),[])
        other=PublicAssistant(uuid.uuid4().hex,storage_root=self.temp.name)
        other.bind_dashboard('301101',1,1)
        self.assertEqual(other.memory_list(),[])
    def test_visible_history_separates_learner_and_week_memory_stays_learner_local(self):
        self.engine.bind_dashboard('301101',1,1)
        self.engine.history.append({'role':'user','content':'This history belongs to the first week.'})
        self.engine.bind_dashboard('301101',2,2)
        self.assertEqual(self.engine.history,[])
        self.engine.bind_dashboard('301102',1,1)
        self.assertEqual(self.engine.history,[])
        self.engine.bind_dashboard('301101',1,1)
        self.assertEqual(len(self.engine.history),1)
        primary=self.engine.call('source',query='Explain my learning analytics')['primary']
        self.assertEqual(primary['visible_conversation_history'],self.engine.history)
    def test_absence_unknown_and_echo_not_watching_week(self):
        rows=self.raw('moodle')
        ids=[x['id'] for x in learners()]
        chosen=next((identifier,week) for identifier in ids for week in range(0,11)
                    if not any(r['ID']==identifier and int(r['Week'])==week and r['Event']=='Resources_views' for r in rows))
        source=self.source(chosen[0],chosen[1],chosen[1])
        activity=source['primary']['dashboard_context']['activity']
        self.assertIsNone(activity['Resources']['resource_views']['value'])
        self.assertEqual(activity['Resources']['resource_views']['status'],'NO_OBSERVATIONS_COVERAGE_UNKNOWN')
        self.assertIsNone(activity['Lecture']['video_views']['value'])
        self.assertEqual(activity['Lecture']['cumulative_video_views']['time_basis'],'cumulative_snapshot')
        self.assertIn('not watching time',source['source']['temporal_boundary'])
        self.assertEqual(activity['Reflection']['edited_characters']['definition'],'Sum of absolute edited-character counts; no inference about reflection content or quality.')
    def test_strict_context_gold_id_course_and_window_rejection(self):
        context=self.engine.bind_dashboard('301101',1,1)
        for field,value in [('gold',{'answer':'forbidden'}),('course_id','UNRELATED_COURSE'),('learner_id','999999'),('source_path','research/data/evaluation/rq1/final128_query_gold.csv')]:
            wrong=deepcopy(context);wrong[field]=value
            with self.assertRaises(ValueError):self.engine.call('source',context=wrong)
        with self.assertRaises(ValueError):build_context('301101',week_start=True,week_end=1)
        with self.assertRaises(ValueError):build_context('301101',week_start=2,week_end=1)
        with self.assertRaises(CoreFailure):self.engine.call('prepare',query='Explain',history=[{'role':'user','content':'hello','gold':'forbidden'}])
    def test_live_s0_s1_and_true_clarification_skip_provider_roles(self):
        for mode in ('S0_PAGE_ONLY','S1_CROSS_PAGE_EVIDENCE'):
            self.engine.bind_dashboard('301101',1,3)
            mock=ExactMock()
            result=self.engine.live('Explain learning analytics',transport=mock,mode=mode)
            self.assertEqual([x['role'] for x in result['provider_trace']],['FINAL'])
            self.assertEqual(len(mock.payloads),1)
            self.assertEqual(mock.payloads[0]['max_tokens'],2048)
            self.assertEqual(result['core']['rag_calls'],0)
            self.assertEqual(result['core']['memory_calls'],0)
            self.assertEqual(result['core']['prepared']['trace']['route_status'],'BYPASSED_S0_S1')
        fresh=PublicAssistant(uuid.uuid4().hex,storage_root=self.temp.name)
        fresh.bind_dashboard('301101',1,3)
        # Actual original frozen gate: multiple visible week targets and no item selected.
        self.assertTrue(fresh.call('source',query='Explain that.')['clarification'])
        mock=ExactMock()
        result=fresh.live('Explain that.',transport=mock)
        self.assertEqual(mock.payloads,[])
        self.assertEqual(result['generation'],'LOCAL_CLARIFICATION_NO_PROVIDER_CALL')
        self.assertIn('FROZEN_CLARIFICATION_GATE',result['clarification_required'])
        self.assertFalse(result['live_model_call'])
    def test_full_original_chain_uses_dashboard_scope_and_fixed_wire_limits(self):
        self.engine.bind_dashboard('301101',1,3)
        mock=ExactMock()
        result=self.engine.live('Give me an action plan without dates to study learning analytics',transport=mock,memory_backend='LEXICAL',controls={'task_intent':'ORDINARY_ACTION_ADVICE'})
        self.assertEqual([x['role'] for x in result['provider_trace']],['RAG','MEMORY','B4_PLANNING','CANDIDATE','FINAL'])
        self.assertEqual([p['max_tokens'] for p in mock.payloads],[32,32,64,2048,2048])
        self.assertEqual(result['core']['source']['scope']['learner_id'],'301101')
        self.assertTrue(result['core']['readonly_state_unchanged'])
        self.assertEqual(result['core']['rag_calls'],1)
        self.assertEqual(result['core']['memory_calls'],1)
        self.assertIsNotNone(result['accepted_plan'])
        self.assertEqual(mock.payloads[-1]['response_format']['json_schema']['name'],'reused62_final_v1')
        self.assertEqual(result['answer_plan_fidelity'],'NOT_CHECKED')
        for payload in mock.payloads:
            self.assertNotIn('301102',json.dumps(payload))
            self.assertNotIn('gold',json.dumps(json.loads(payload['messages'][-1]['content'])).lower())
    def test_request_cannot_claim_current_week_from_historical_archive(self):
        self.engine.bind_dashboard('301101',1,1)
        mock=ExactMock()
        with self.assertRaisesRegex(CoreFailure,'ClarificationRequired'):
            self.engine.live('How active am I this week?',transport=mock)
        self.assertEqual(mock.payloads,[])

if __name__=='__main__':unittest.main()
