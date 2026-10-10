#!/usr/bin/env python3
"""Small hand-calculable fixtures, independent of the study's observed effects."""
import json
import unittest
from fractions import Fraction as F
from pathlib import Path
import numpy as np
from reproduce.s7 import avg, family_aggregate, sign_flip, holm, paired_bootstrap, leave_one_new

class HandFixtures(unittest.TestCase):
    def test_01_hierarchy_does_not_pool_criterion_counts(self):
        # A: means 1 and 3 -> 2; B: means 5 and 3 -> 4; family -> 3.
        # Pooling all scores instead gives 20/6, detecting wrong denominators.
        conditions=[[[1],[3]], [[5,5],[3,3]]]
        self.assertEqual(family_aggregate(conditions),F(3))
        self.assertNotEqual(family_aggregate(conditions),F(20,6))

    def test_02_paired_index_carries_every_mode(self):
        matrix=[[[1,11],[2,12],[3,13]], [[4,14],[5,15],[6,16]]]
        sums,den,idx=paired_bootstrap(matrix,20,20260908)
        self.assertTrue(np.all(sums[:,1]-sums[:,0] == 10*den))
        for b in range(20):
            expected=sum(matrix[g][idx[b,g,k]][0] for g in range(2) for k in range(3))
            self.assertEqual(int(sums[b,0]),expected)

    def test_03_zeros_and_equal_extremes(self):
        self.assertEqual(sign_flip([0,0,0,0])[:3],(F(1),16,16))
        self.assertEqual(sign_flip([1,1,0,0])[:3],(F(1,2),8,16))
        self.assertEqual(sign_flip([1,-1,0,0])[:3],(F(1),16,16))

    def test_04_direction_symmetry_and_all_configurations(self):
        self.assertEqual(sign_flip([F(1,3),F(-1,7),0])[0],sign_flip([F(-1,3),F(1,7),0])[0])
        self.assertEqual(sign_flip([1]*12)[:3],(F(1,2048),2,4096))
        self.assertEqual(sign_flip([F(1,3)]*3)[:3],(F(1,4),2,8))

    def test_05_holm_unsorted_monotone_and_clamped(self):
        p=[F(1,100),F(4,100),F(3,100)]
        self.assertEqual(holm(p),[F(3,100),F(6,100),F(6,100)])
        self.assertEqual(holm([F(9,10),F(4,5),F(1,10)]),[F(1),F(1),F(3,10)])
        adj=holm(p); order=sorted(range(3),key=lambda i:p[i])
        self.assertEqual([adj[i] for i in order],sorted(adj))
        self.assertTrue(all(p[i]<=adj[i]<=1 for i in range(3)))

    def test_06_seed_reproduces_indices_and_values(self):
        matrix=[[[1,2],[3,4],[5,6]],[[7,8],[9,10],[11,12]]]
        a=paired_bootstrap(matrix,50,20260908);b=paired_bootstrap(matrix,50,20260908)
        self.assertEqual(a[1],b[1]);np.testing.assert_array_equal(a[0],b[0]);np.testing.assert_array_equal(a[2],b[2])

    def test_07_stratified_delete_keeps_focus_weight(self):
        groups={g:[g+str(i) for i in range(1,4)] for g in 'ERMP'}
        d={u:F(0) for fs in groups.values() for u in fs};d.update(E1=F(1),E2=F(2),E3=F(3))
        self.assertEqual(avg(d.values()),F(1,2))
        self.assertEqual(leave_one_new(d,groups)['E1'],F(5,8))
        self.assertNotEqual(leave_one_new(d,groups)['E1'],F(5,11))

    def test_08_negative_and_zero_units_are_retained(self):
        d={'E1':F(-1),'E2':F(0),'E3':F(2)}
        self.assertEqual(avg(d.values()),F(1,3))
        self.assertEqual(len(leave_one_new(d,{'E':list(d)})),3)
        self.assertEqual(leave_one_new(d,{'E':list(d)})['E3'],F(-1,2))

    def test_09_linear_quantile_hand_fixture(self):
        np.testing.assert_allclose(np.quantile([0.,1.,2.,3.],[.025,.975],method='linear'),[.075,2.925],rtol=0,atol=1e-15)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(HandFixtures)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
