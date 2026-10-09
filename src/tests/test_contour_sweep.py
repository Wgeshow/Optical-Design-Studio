import unittest
import numpy as np
from contour_sweep import sweep,regions,feature_values
class Tests(unittest.TestCase):
 def test_birth_merge_and_monotone_area(self):
  r=sweep(np.array([[3.,1.,0.,1.,3.]]),1.)
  self.assertEqual([x['region_count'] for x in r['levels']],[2,2,2,1]);self.assertEqual(r['summary']['births'],2);self.assertEqual(r['summary']['merges'],1)
  self.assertTrue(all(a['area_fraction']<=b['area_fraction'] for a,b in zip(r['levels'],r['levels'][1:])))
 def test_fixed_grid_endpoints_and_shape_reconstruction(self):
  a=np.array([[.03,.22],[.3,.47]]);r=sweep(a,.1)
  self.assertAlmostEqual(r['levels'][0]['level'],.47);self.assertAlmostEqual(r['levels'][-1]['level'],.03)
  for level in r['levels']:
   mask=np.zeros(a.shape,bool)
   for region in level['regions']:
    for j,start,n in region['pixel_runs']:mask[j,start:start+n]=True
   np.testing.assert_array_equal(mask,a>=level['level'])
 def test_nonuniform_physical_area(self):
  r=sweep(np.array([[2.],[1.]]),1.,np.array([[1.],[3.]]))
  self.assertAlmostEqual(r['levels'][0]['area_fraction'],.25)
 def test_periodic_seam(self):
  a=np.array([[1.,0.,1.]])
  self.assertEqual(regions(a>0)[1],2);self.assertEqual(regions(a>0,True)[1],1)
 def test_negligible_and_finite_features(self):
  r=sweep(np.full((3,3),1e-12));self.assertTrue(r['negligible']);self.assertEqual(r['levels'],[]);self.assertTrue(all(np.isfinite(list(feature_values(r).values()))))
 def test_invalid_step(self):
  with self.assertRaises(ValueError):sweep(np.ones((2,2)),0)
if __name__=='__main__':unittest.main()
