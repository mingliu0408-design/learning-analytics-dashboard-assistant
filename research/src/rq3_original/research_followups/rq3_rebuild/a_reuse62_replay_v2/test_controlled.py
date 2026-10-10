"""Bounded regression checks. No retrieval, encoder, transport or human scoring."""
from replay_common import *
import unittest
from copy import deepcopy
import ast
from controlled_runtime import *
from interfaces import FINAL_SCHEMA,final_issues,freeze_answer
from preparation import assess

class ControlledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b=read(HERE/'runtime/BINDINGS.json');cls.tasks=lines(HERE/'runtime/TASKS_62.jsonl')
        cls.pages=read(checked(cls.b['pages']))['pages'];cls.cfg=read(HERE/'runtime/CONFIG_PROPOSED.json')
        cls.results=[]
        t=cls.tasks[19];s=source_for(t,cls.b)
        for mode in ('S2_EVIDENCE_RAG','S3_EVIDENCE_MEMORY','S4_EVIDENCE_PLANNING','S5_FULL'):
            cls.results.append(handle(dict(op='prepare',task=t,mode=mode,config=cls.cfg,bindings_path=str(HERE/'runtime/BINDINGS.json'),
                bindings_digest=sha(cls.b),primary_sha256=s['primary_sha256'],route=dict(rag_required=False,memory_required=False,
                    planning_required=False,provider_identity='OFFLINE_CONTRACT_NO_BITS_NOT_ACTUAL_P3'))))

    def test_original_queries_and_page_preserved(self):
        old=lines(OLD/'runtime/TASKS_62.jsonl')
        self.assertEqual([(x['task_id'],x['query'],x['page']) for x in old],[(x['task_id'],x['query'],x['page']) for x in self.tasks])

    def test_original_version_untouched(self):
        before=read(HERE/'audit/OLD_VERSION_BASELINE.json')
        self.assertTrue(all(file_id(OLD/n)==entry for n,entry in before.items()))

    def test_exact_nine_hidden_histories(self):
        old=lines(OLD/'runtime/TASKS_62.jsonl')
        self.assertEqual([t['task_id'] for a,t in zip(old,self.tasks) if a['history']!=t['history']],list(NINE))
        self.assertTrue(all(not t['history'] for t in self.tasks if t['task_id'] in NINE))

    def test_role_and_span_whitelist(self):
        for tid in NINE:
            r=read(HERE/f'runtime/memory_sources/{tid}.json')
            from utils.c4_rebuild.contracts import reject_sidecars
            reject_sidecars(r)
            self.assertFalse(r['relation_events'])
            for op in r['setup_operations']:
                t=next(t for t in r['source_turns'] if t['turn_id']==op['source_turn_id']);a,b=op['source_span_chars']
                self.assertEqual(t['content'][a:b],op['content'])
                if t['role']=='SYSTEM':self.assertEqual(op['memory_type'],'ACTIVE_PLAN')
            self.assertNotIn('expected',json.dumps(r).lower())

    def test_readonly_evidence_and_budget(self):
        r=read(HERE/'MEMORY_RESULTS.json')
        self.assertEqual((r['setup_writes'],r['mode_clones'],r['reads_started'],r['reads_completed'],r['read_retries']),(20,54,9,9,0))
        self.assertTrue(all(t['read']['readonly_unchanged'] for t in r['tasks'].values()))
        self.assertEqual(r['tasks']['U031']['stored_rows'],0)
        for mb in read(HERE/'runtime/MEMORY_BINDINGS.json').values():
            checked(mb['graph']);checked(mb['source_events'])
            for entry in mb['databases'].values():checked(entry)
            for c in mb['mode_copies'].values():
                for entry in c.values():checked(entry)

    def test_unknown_never_zero_or_current_week(self):
        p=self.pages['Reflection']
        self.assertIsNone(p['missing']['weekly_edit_events']);self.assertIsNone(p['writing_snapshot']['observation_window'])
        self.assertEqual(p['writing_snapshot']['Total_chars'],45093)
        for r in self.results:
            self.assertIsNone(r['prepared']['final_request']['runtime_input']['scope']['as_of'])

    def test_echo_content_week_is_not_observation_week(self):
        e=self.pages['Lecture']['playback_snapshot']
        self.assertIsNone(e['observation_window']);self.assertEqual(e['total_view_events'],11)
        self.assertNotIn('viewed_videos',e)
        self.assertTrue(any('No Lecture Video' in r['Class'] for r in e['rows']))
        self.assertFalse(any('recording_id' in r for r in e['rows']))

    def test_readiness_independent_of_retrieval(self):
        rows=assess(self.tasks,self.b,with_diagnostics=False)
        self.assertEqual(sum(r['source_sufficient_for_bounded_replay'] for r in rows),54)
        self.assertTrue(rows[19]['source_sufficient_for_bounded_replay'])
        self.assertEqual(rows[21]['important_missing'],['NUMBERED_PLAN_2_AND_3_ANTECEDENT_NOT_RECOVERED'])
        self.assertTrue(rows[25]['source_sufficient_for_bounded_replay'])

    def test_all_no_route_preserves_mode_gates(self):
        for r in self.results:
            self.assertEqual((r['rag_calls'],r['memory_calls']),(0,0));self.assertIsNone(r['prepared']['planner'])
            self.assertEqual(r['prepared']['trace']['generation_calls'],0)

    def test_s0_s1_saved_boundaries(self):
        r=read(HERE/'OFFLINE_ACCEPTANCE.json')
        self.assertEqual(r['compiler_preparations_completed'],6)
        self.assertEqual([x['additional_domains'] for x in r['evidence_pairs']],[['Lecture'],['Resources'],[]])
        self.assertTrue(all(x['current_identical'] for x in r['evidence_pairs']))

    def test_final_wire_reuses_correct_slot(self):
        self.assertEqual(set(FINAL_SCHEMA['properties']),{'answer','cited_evidence_ids'})
        self.assertTrue(final_issues(dict(answer='test',cited_evidence_ids=[],plan_fields=None),[]))
        plan={'test_marker':'APPLICATION_HELD'}
        v=freeze_answer(dict(answer='INTERFACE_TEST_ONLY',cited_evidence_ids=[]),[],plan)
        self.assertEqual(v['accepted_plan'],plan)
        # DurableRunner.perform returns result, whose accepted object is value.
        tree=ast.parse((HERE/'run_batch.py').read_text())
        assignments=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='accepted' for t in n.targets)]
        self.assertTrue(any("result['value']" in ast.unparse(n) for n in assignments))

    def test_executable_fails_before_provider(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('controlled_runner',HERE/'run_batch.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        with self.assertRaisesRegex(PermissionError,'NO_PROVIDER_AUTHORIZATION'):
            runner.main(['--execute'])

if __name__=='__main__':
    offline()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ControlledTests))
    write(HERE/'TEST_REPORT.json',dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),passed=result.wasSuccessful(),
        actual_test_compiler_preparations=4,route_mode='EXPLICIT_ALL_NO_CONTRACT_TEST_NOT_P3',new_native_reads=0,new_rag_queries=0,
        provider_calls=0,p3_llm_calls=0,candidate_calls=0,final_calls=0,judge_calls=0,human_fields_filled=0))
    raise SystemExit(0 if result.wasSuccessful() else 1)
