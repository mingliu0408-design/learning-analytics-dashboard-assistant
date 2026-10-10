"""Synthetic governance/algorithm tests plus immutable saved-artifact checks. No models."""
import copy
import fcntl
import inspect
import tempfile
import unittest
from unittest.mock import patch
from common import *
from policies import *
from audit_coverage import coverage_rows, summarize
import run_inference as runner

class CandidatePolicies(unittest.TestCase):
    def test_e_preserves_saved_order(self):
        a=['a'+str(i) for i in range(40)]
        self.assertEqual(candidate_pool('E_R0_SEEDED',a,['c']),a[:30])
    def test_e_keeps_empty_without_fallback(self):
        self.assertEqual(candidate_pool('E_R0_SEEDED',[],['c']),[])
    def test_e_short_is_not_padded(self):
        self.assertEqual(candidate_pool('E_R0_SEEDED',['z','a'],[]),['z','a'])
    def test_union_alternates_a_first(self):
        self.assertEqual(candidate_pool('F_FIXED_UNION',['a','b'],['c','d']),['a','c','b','d'])
    def test_union_exact_duplicate_skip(self):
        self.assertEqual(candidate_pool('F_FIXED_UNION',['a','b','c'],['b','a','d']),['a','b','c','d'])
    def test_union_exhausted_side_continues(self):
        self.assertEqual(candidate_pool('F_FIXED_UNION',[],['c','d']),['c','d'])
    def test_union_cap(self):
        result=candidate_pool('F_FIXED_UNION',[f'a{i}' for i in range(40)],[f'c{i}' for i in range(40)])
        self.assertEqual(result,[x for i in range(15) for x in (f'a{i}',f'c{i}')])
    def test_unknown_policy_stops(self):
        with self.assertRaises(ValueError):candidate_pool('G_SEARCH',[],[])
    def test_duplicate_saved_ranking_stops(self):
        with self.assertRaises(ValueError):candidate_pool('E_R0_SEEDED',['a','a'],[])
    def test_mapping_or_labels_rejected(self):
        with self.assertRaises(ValueError):candidate_pool('F_FIXED_UNION',{'gold':['a']},[])
    def test_constructor_has_no_labels_scores_or_query_arguments(self):
        self.assertEqual(list(inspect.signature(candidate_pool).parameters),['policy','a_ids','c_ids'])
        self.assertNotIn('open(',inspect.getsource(candidate_pool))
    def test_rank_ties_are_deterministic(self):
        self.assertEqual(rank_scores(['z','a'],{'z':1.0,'a':1.0}),['a','z'])
    def test_nonfinite_always_stops(self):
        for value in (float('nan'),float('inf'),float('-inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):rank_scores(['a'],{'a':value})
    def test_scores_cannot_expand_or_drop_pool(self):
        with self.assertRaises(ValueError):rank_scores(['a'],{'b':1.0})
    def test_pair_bound_and_reservation(self):
        self.assertEqual(admit_pairs(896,4),900)
        with self.assertRaises(ValueError):admit_pairs(899,2)

class InputIdentity(unittest.TestCase):
    def setUp(self):
        self.raw=[{'query_sha256':'q','passage_sha256':'p'}]
        self.data={'input_ids':[[101,1,102,2,102]],'attention_mask':[[1]*5],'token_type_ids':[[0,0,0,1,1]]}
    def test_exact_identity_is_reusable(self):
        self.assertEqual(batch_identity('m',self.raw,self.data),batch_identity('m',copy.deepcopy(self.raw),copy.deepcopy(self.data)))
    def test_model_config_change_invalidates_cache(self):
        self.assertNotEqual(batch_identity('m',self.raw,self.data),batch_identity('other',self.raw,self.data))
    def test_query_passage_bytes_invalidate_cache(self):
        for field in ('query_sha256','passage_sha256'):
            raw=copy.deepcopy(self.raw);raw[0][field]='changed'
            self.assertNotEqual(batch_identity('m',self.raw,self.data),batch_identity('m',raw,self.data))
    def test_each_token_tensor_field_invalidates_cache(self):
        for field in self.data:
            data=copy.deepcopy(self.data);data[field][0][-1]+=1
            self.assertNotEqual(batch_identity('m',self.raw,self.data),batch_identity('m',self.raw,data))
    def test_padding_or_batch_shape_invalidates_cache(self):
        data=copy.deepcopy(self.data)
        for field in data:data[field][0].append(0)
        self.assertNotEqual(batch_identity('m',self.raw,self.data),batch_identity('m',self.raw,data))
        self.assertNotEqual(batch_identity('m',self.raw,self.data),batch_identity('m',self.raw*2,{k:v*2 for k,v in self.data.items()}))

class MetricsAndResources(unittest.TestCase):
    def test_micro_macro_and_empty_reference_denominators(self):
        rows=coverage_rows([{'case_id':'x','ranked_ids':['a']},{'case_id':'y','ranked_ids':['a']},{'case_id':'z','ranked_ids':['a']}],{'x':['a'],'y':['a','b','c'],'z':[]})
        summary=summarize(rows)
        self.assertEqual(summary['top5_micro_recall'],.5)
        self.assertAlmostEqual(summary['top5_macro_query_recall'],2/3)
        self.assertIsNone(rows[2]['recall_at_5'])
        self.assertEqual(summary['reference_positive_queries'],2)
    def test_oracle_respects_top5_cap(self):
        ids=[str(i) for i in range(7)]
        row=coverage_rows([{'case_id':'x','ranked_ids':ids}],{'x':ids})[0]
        self.assertEqual(row['oracle_recall_at_5'],5/7)
    def test_process_classifier_defers_unknown_inference(self):
        fake=SimpleNamespace(stdout='python /some/i0/run_inference.py')
        with patch.object(runner.subprocess,'check_output',return_value='999999 python\n'),patch.object(runner.subprocess,'run',return_value=fake):
            self.assertTrue(runner.model_processes()[0]['blocks_inference'])
    def test_process_classifier_excludes_observed_harvester(self):
        fake=SimpleNamespace(stdout='python /Telegram Image Harvester/runtime/live_monitor.py')
        with patch.object(runner.subprocess,'check_output',return_value='999999 python\n'),patch.object(runner.subprocess,'run',return_value=fake):
            self.assertFalse(runner.model_processes()[0]['blocks_inference'])
    def test_competing_lock_defers_without_killing(self):
        with tempfile.TemporaryDirectory() as td:
            lock=Path(td)/'lock'
            with lock.open('a+') as f,patch.object(runner,'LOCK',lock):
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaisesRegex(RuntimeError,'LOCK_BUSY'):
                    with runner.compute_lease():pass
    def test_competing_process_defers(self):
        with tempfile.TemporaryDirectory() as td,patch.object(runner,'model_processes',return_value=[{'blocks_inference':True}]):
            with patch.object(runner,'LOCK',Path(td)/'lock'),patch.object(runner,'OUT',Path(td)):
                with self.assertRaisesRegex(RuntimeError,'DEFERRED_LOCAL_INFERENCE_RESOURCE'):
                    with runner.compute_lease():pass
    def test_firewall_blocks_reference_open(self):
        script="from run_inference import install_reference_firewall; install_reference_firewall(); open('historical_labels.json')"
        result=subprocess.run([sys.executable,'-B','-c',script],cwd=OUT,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('REFERENCE_OR_EVALUATION_OPEN_FORBIDDEN',result.stderr)

class FrozenArtifacts(unittest.TestCase):
    def test_policy_hashes_and_exact_saved_construction(self):
        for name,h in read_json(OUT/'POLICY_FREEZE.json')['files'].items():self.assertEqual(file_hash(OUT/name),h)
        saved=read_json(OUT/'SAVED_RANKING_INPUTS.json')
        a={r['case_id']:r['ranked_ids'] for r in saved if r['candidate']=='A_R0'}
        c={r['case_id']:r['ranked_ids'] for r in saved if r['candidate']=='C_HYBRID'}
        pools=read_json(OUT/'CANDIDATE_POOLS.json')
        self.assertEqual(len(pools),30)
        for p in pools:self.assertEqual(p['candidate_ids'],candidate_pool(p['policy'],a[p['case_id']],c[p['case_id']]))
        self.assertLessEqual(sum(p['candidate_count'] for p in pools),900)
    def test_saved_d_is_c_pool_permutation(self):
        c={r['case_id']:r for r in read_json(R1/'C_HYBRID_DIAGNOSTICS.json')}
        for r in read_json(R1/'D_CROSS_ENCODER_DIAGNOSTICS.json'):
            self.assertEqual(r['candidate_pool_ids'],c[r['case_id']]['ranked_ids'][:30])
            self.assertEqual(set(r['ranked_ids']),set(r['candidate_pool_ids']))

if __name__=='__main__':
    from types import SimpleNamespace
    import sys
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    write_json(OUT/'TEST_RESULTS.json',{'time_utc':now(),'tests_run':result.testsRun,'failures':len(result.failures),
        'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful(),
        'synthetic_tests_and_saved_artifact_invariants_only':True,'model_inference_pairs':0})
    sys.exit(not result.wasSuccessful())
