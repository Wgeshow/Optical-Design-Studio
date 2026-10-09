import tempfile,unittest
from pathlib import Path
from data_library import read_json
from simulation_fields import execute_simulation_fields,validate_settings

class SimulationFieldsTests(unittest.TestCase):
 def test_every_point_keeps_its_wavelength_and_angle(self):
  calls=[]
  def fields(model,perf,cfg,path,cancelled):
   calls.append((model,cfg,path));Path(path).mkdir(parents=True,exist_ok=True);return {}
  model=dict(points=[[0,1550,0]],polarization='p')
  rows=[[0,1549,0,.1,.9,0],[1,1550,10,.2,.8,0],[2,1551,20,.3,.7,0]]
  with tempfile.TemporaryDirectory() as d:
   info=execute_simulation_fields(model,{},rows,dict(grid=3,depth_samples=5,contour_step=.2),d,field_executor=fields)
   self.assertEqual(info['samples'],3)
   saved=read_json(Path(d)/'fields/samples.json');self.assertEqual(saved['status'],'complete')
   self.assertEqual(len(saved['samples']),3)
  self.assertEqual([c[0]['points'][0][2] for c in calls],[0,10,20])
  self.assertEqual([c[1]['wavelength_nm'] for c in calls],[1549,1550,1551])
  self.assertTrue(all(c[1]['maps'] and c[1]['track_contours'] for c in calls))
  self.assertEqual(model['points'],[[0,1550,0]])
 def test_invalid_sampling_rejected(self):
  for opts in (dict(grid=2),dict(depth_samples=2),dict(contour_step=0)):
   with self.assertRaises(ValueError):validate_settings(opts)
