import unittest
import numpy as np
from airhole_field_objective import evaluate,statistics,choose_candidate

MODEL=dict(ax=.535,ay=.535,patterns=[dict(shape='circle',layer='GaAs',material='Air',cx=0.,cy=0.,sx=.1)],layers=[dict(name='Air',thickness=0.),dict(name='GaAs',thickness=.2),dict(name='SiC',thickness=0.)])
class KnownField:
 def __init__(self,bad_xz=False):self.bad_xz=bad_xz
 def GetFields(self,x,y,z):
  outside=x*x+y*y>.1**2
  amp=4. if outside else 1.
  if self.bad_xz and abs(y)<1e-12 and outside:amp=.5
  return ([amp*1j,0j,0j],[0j]*3)
class Tests(unittest.TestCase):
 def test_complex_amplitude_and_zero_component(self):
  r=evaluate(KnownField(),MODEL)
  self.assertAlmostEqual(r['volume']['Ex']['mean_abs_contrast'],4.)
  self.assertAlmostEqual(r['xz']['total']['rms_contrast'],4.)
  self.assertIsNone(r['xz']['Ey']['rms_contrast'])
  self.assertTrue(r['feasible'])
  zero=evaluate(KnownField(),MODEL,dict(component='Ey'))
  self.assertFalse(zero['feasible'])
 def test_xz_changes_acceptance_even_with_good_volume(self):
  r=evaluate(KnownField(True),MODEL)
  self.assertGreater(r['volume']['total']['rms_contrast'],3.)
  self.assertLess(r['xz']['total']['rms_contrast'],1.)
  self.assertFalse(r['feasible']);self.assertEqual(r['xz_sidewall_coverage'],0.)
 def test_volume_weights(self):
  o=np.array([[[1j,0,0]],[[3j,0,0]]]);i=np.ones_like(o);r=statistics(o,i,[1,3])
  self.assertAlmostEqual(r['Ex']['outside_E2'],7.)
  self.assertAlmostEqual(r['Ex']['outside_mean_abs'],2.5)
 def test_xz_affects_bayesian_proposal(self):
  import math
  obs=[dict(x=[0.],fields=evaluate(KnownField(True),MODEL))]
  # Both candidates have good volume contrast and coverage, but only candidate 1 has good XZ contrast.
  responses=[[0.,0.],[2.,2.],[-1.,2.],[1.,1.],[1.,1.]]
  def fit(x,y,pool,noise):return np.array(responses.pop(0)),np.array([.1,.1]),[]
  ndtr=np.vectorize(lambda z:.5*(1+math.erf(z/2**.5)))
  idx,p=choose_candidate(obs,[[.2],[.8]],fit,ndtr,lambda *args:np.ones(2))
  self.assertEqual(idx,1)
 def test_invalid_geometry_rejected(self):
  import copy
  m=copy.deepcopy(MODEL);m['patterns'][0]['sx']=.26
  with self.assertRaises(ValueError):evaluate(KnownField(),m)
if __name__=='__main__':unittest.main()
