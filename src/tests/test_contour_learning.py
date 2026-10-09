import tempfile,unittest,json
from pathlib import Path
import numpy as np
from test_field_tracking import field_fixture
from field_tracking import feature_vector
from contour_sweep import sweep,shape_features
from airhole_field_objective import choose_candidate,evaluate
from test_airhole_field_objective import KnownField,MODEL

class ContourLearningTests(unittest.TestCase):
 def test_saved_maps_reach_training_features(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=field_fixture(tmp,grid=4)
   features=feature_vector(d)
   self.assertTrue(any(k.startswith('contour_v1.') for k in features))
   saved=json.loads((Path(tmp)/'field_contours.json').read_text())
   self.assertEqual(saved['step'],.1)
   self.assertEqual(len(saved['views']),6)
   self.assertTrue(all(np.isfinite(v) for v in features.values()))
 def test_equal_strength_different_shapes_are_distinguishable(self):
  a=np.zeros((8,8));a[:,0:2]=1
  b=np.zeros((8,8));b[0:2,:]=1
  fa=shape_features(sweep(a),a,'x.');fb=shape_features(sweep(b),b,'x.')
  self.assertEqual(fa['x.mean_amplitude'],fb['x.mean_amplitude'])
  self.assertNotEqual(fa['x.shape.8.x1.cos'],fb['x.shape.8.x1.cos'])
 def test_airhole_gp_predicts_contours_at_train_and_candidates(self):
  obs=[]
  for i in range(4):
   f=evaluate(KnownField(),MODEL);f['contour_features']={'shape':float(i)}
   obs.append(dict(x=[i/3],fields=f))
  calls=[]
  def fit(x,y,q,noise):
   calls.append((np.asarray(x).shape,np.asarray(q).shape))
   return np.linspace(0,1,len(q)),np.full(len(q),.1),[]
  _,p=choose_candidate(obs,[[.2],[.8]],fit,lambda z:np.ones_like(z)*.5,lambda *args:np.ones(2))
  self.assertEqual(p['contour_components'],1)
  self.assertEqual(calls[0],((4,1),(6,1)))
  self.assertTrue(all(x[0][1]==2 and x[1][1]==2 for x in calls[1:]))
