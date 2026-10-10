"""Bounded checks of saved-data integrity and original routing contracts."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from reproduce import rq1, rq2, r7, r7_infer


class FrozenRecomputationTests(unittest.TestCase):
    def test_rq1_all_methods_match_from_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            result=rq1.run(Path(folder))
        self.assertEqual(result['status'],'PASS_AGGREGATE_START')
        self.assertLess(result['methods']['M64_seed_20260815']['mrr'],result['methods']['C0']['mrr'])

    def test_rq1_rejects_inconsistent_count_input(self):
        counts=json.loads((rq1.ROOT/'data/reproduction/rq1/counts.json').read_text())
        counts['methods']['C0']['rank_distribution']['1']+=1
        with self.assertRaises(AssertionError):rq1.calculate(counts)

    def test_rq2_full_populations_exact(self):
        with tempfile.TemporaryDirectory() as folder:result=rq2.run(Path(folder))
        self.assertEqual((result['case_count'],result['core_count'],result['method_count']),(36,32,11))

    def test_rq2_clarify_has_no_invented_capability_gold(self):
        rows,answer,methods=rq2.load_inputs()
        clarify=[row for row in rows if row['gold_dialogue_action']=='CLARIFY']
        self.assertEqual(len(clarify),4)
        self.assertTrue(all(row['gold_'+bit] is None for row in clarify for bit in rq2.BITS))
        with self.assertRaises(rq2.metrics.MetricError):
            rq2.metrics.family_metrics(answer[:-1],next(iter(methods.values())))

    def test_r7_all_frozen_objects_and_negative_changes(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            result=r7.run(Path(folder))
            summary=json.loads((Path(folder)/'CHANGE_SUMMARY.json').read_text())
        self.assertEqual(result['case_changes'],{'B2':6,'B3':4,'P1':0})
        self.assertEqual(summary['B2']['answer_case_error_count_outcomes']['WORSENED'],4)

    def test_serializer_ignores_top_level_gold(self):
        import numpy as np
        semantic={'current_query':'Explain this synthetic dashboard.','current_page':'Overview','dashboard_context':'Synthetic fixture: two completed activities.','visible_conversation_history':[]}
        compact,labelled=r7_infer.algorithm_namespace(np)
        plain=labelled['serialize_canonical_text']({'model_input':semantic})
        with_gold=labelled['serialize_canonical_text']({'model_input':semantic,'gold_label':'not a runtime feature'})
        self.assertEqual(plain,with_gold)
        self.assertNotEqual(plain,compact['serialize_semantic_input'](semantic))
        self.assertEqual(tuple(json.loads(compact['serialize_semantic_input'](semantic))),r7_infer.SEMANTIC_FIELDS)

    def test_encoder_requires_explicit_opt_in_before_model_import(self):
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as caught:r7_infer.main([])
        self.assertEqual(caught.exception.code,2)

if __name__=='__main__':unittest.main()
