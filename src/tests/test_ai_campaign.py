import copy,tempfile,unittest
from pathlib import Path
import numpy as np
from data_library import read_json,write_json
from ai_campaign import prepare_campaign,execute_campaign,training_observations,measurement_key
from airhole_field_objective import evaluate
from test_airhole_field_objective import KnownField,MODEL
from test_backend import sample

class CampaignTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.base=sample(wl_start_nm=1550,wl_stop_nm=1550)
  self.cfg=prepare_campaign(self.base,dict(initial=4,test_count=2,adaptive=1,finalists=1,new_budget=8,grid=3,verification_grid=5,half_window=1,rta_step=1,bounds=[dict(Parameter='thickness',Target='Device',Min=.20,Max=.30,Step=.01,Choices='')]),self.root)
  self.calls=0
 def tearDown(self):self.tmp.cleanup()
 def fields(self,model,perf,cfg,directory,cancelled):
  self.calls+=1;directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
  fields=evaluate(KnownField(),MODEL,dict(contrast_target=cfg['airhole_settings']['contrast_target']))
  fields['objective']=1+model['layers'][1]['thickness']
  features={'shape':model['layers'][1]['thickness']}
  desc=dict(wavelength_nm=1550.,grid=cfg['grid'],airhole_views=fields,contour_features=features)
  write_json(directory/'field_features.json',desc)
  return desc
 def spectrum(self,model,perf,emit,cancelled):return [[i,w,0,.8,.2,0.] for i,w,_ in model['points']],{}
 def run_campaign(self,name,**changes):
  cfg=dict(self.cfg,**changes);return execute_campaign(self.base,{},cfg,self.root/name,self.spectrum,field_executor=self.fields)
 def test_training_validation_and_test_isolation(self):
  result=self.run_campaign('a');saved=read_json(self.root/'a/campaign.json')
  self.assertEqual(result['summary']['new_simulations'],6)
  self.assertEqual(result['summary']['tests'],2)
  self.assertEqual(len(training_observations(saved['records'],self.cfg)),4)
  self.assertEqual(saved['summary']['validation']['test_designs'],2)
  self.assertEqual(len(saved['summary']['validation']['measurements']),5)
  train={str(r['values']) for r in saved['records'] if r['phase']=='train'};test={str(r['values']) for r in saved['records'] if r['phase']=='test'}
  self.assertFalse(train&test)
 def test_reuse_runs_no_new_solver_work(self):
  self.run_campaign('a');before=self.calls;result=self.run_campaign('b')
  self.assertEqual(self.calls,before);self.assertEqual(result['summary']['reused'],6);self.assertEqual(result['summary']['new_simulations'],0)
 def test_budget_limits_collect(self):
  result=self.run_campaign('a',new_budget=2);self.assertEqual(self.calls,2);self.assertEqual(result['summary']['status'],'budget reached')
 def test_fit_only_and_resume_do_not_simulate(self):
  self.run_campaign('a');before=self.calls
  result=self.run_campaign('b',resume_file=str(self.root/'a/campaign.json'),operation='fit')
  self.assertEqual(self.calls,before);self.assertEqual(result['summary']['new_simulations'],0)
 def test_search_uses_contours_and_excludes_test_candidates(self):
  result=self.run_campaign('a',operation='search');saved=read_json(self.root/'a/campaign.json')
  adaptive=[r for r in saved['records'] if r['phase']=='adaptive'];self.assertEqual(len(adaptive),1)
  self.assertGreater(adaptive[0]['prediction']['contour_features'],1)
  self.assertLessEqual(result['summary']['new_simulations'],8)
  self.assertEqual(len([r for r in saved['records'] if r['phase']=='verification']),1)
 def test_changed_wavelength_starts_new_collection(self):
  self.run_campaign('a')
  result=self.run_campaign('b',resume_file=str(self.root/'a/campaign.json'),wavelength_nm=1500)
  self.assertEqual(result['summary']['new_simulations'],6)
  with self.assertRaises(ValueError):self.run_campaign('c',resume_file=str(self.root/'a/campaign.json'),wavelength_nm=1500,operation='fit')
 def test_full_grid_never_silently_truncates(self):
  with self.assertRaises(ValueError):prepare_campaign(self.base,dict(self.cfg,mode='Full range scan',new_budget=1))
 def test_cancel_checkpoint_can_resume(self):
  event=execute_campaign(self.base,{},self.cfg,self.root/'a',self.spectrum,cancelled=lambda:self.calls>=2,field_executor=self.fields)
  self.assertEqual(event['summary']['status'],'paused');before=self.calls
  self.run_campaign('b',resume_file=str(self.root/'a/campaign.json'))
  self.assertEqual(self.calls-before,4)
 def test_numerical_accuracy_changes_cache_key(self):
  m=copy.deepcopy(self.base);m['basis']+=2
  self.assertNotEqual(measurement_key(m,self.cfg),measurement_key(self.base,self.cfg))

 def test_reference_matching_survives_higher_accuracy_verification(self):
  self.run_campaign('a')
  reference=str(self.root/'a/designs/000001/fields')
  result=self.run_campaign('b',operation='search',approach='reference',reference_directory=reference,reuse=False)
  saved=read_json(self.root/'b/campaign.json')
  self.assertEqual(result['summary']['failures'],0)
  self.assertTrue(all('reference_distance' in r for r in saved['records']))
  self.assertEqual(len([r for r in saved['records'] if r['phase']=='verification']),1)
 def test_full_grid_collects_every_combination_and_reserves_tests(self):
  result=self.run_campaign('a',mode='Full range scan',new_budget=11)
  self.assertEqual(result['summary']['completed'],11)
  self.assertEqual(result['summary']['tests'],2)
 def test_changed_target_does_not_reuse_old_measurements(self):
  self.run_campaign('a');before=self.calls
  self.run_campaign('b',contrast_target=4.)
  self.assertEqual(self.calls-before,6)

 def test_unlimited_collect_finishes_plan(self):
  result=self.run_campaign('a',new_budget=0)
  self.assertEqual(self.calls,6)
  self.assertEqual(result['summary']['status'],'complete')
 def test_unlimited_search_includes_adaptive_and_verification(self):
  result=self.run_campaign('a',new_budget=0,operation='search')
  self.assertEqual(self.calls,8)
  self.assertEqual(result['summary']['status'],'complete')
 def test_training_uses_all_saved_designs(self):
  self.run_campaign('a');saved=read_json(self.root/'a/campaign.json')
  rows=[r for r in saved['records'] if r['phase']=='train']*30
  self.assertEqual(len(training_observations(rows,self.cfg)),120)
 def test_full_grid_over_ten_thousand_is_exhaustive(self):
  from ai_campaign import candidates
  import itertools
  # The Cartesian product may exceed 10,000; each materialized dimension
  # must still respect the separate design-bound allocation safety limit.
  bounds=[dict(Parameter='thickness',Target='Device',Min=.20,Max=.30,Step=.0005,Choices=''),
          dict(Parameter='radius',Target='1',Min=.10,Max=.20,Step=.001,Choices='')]
  cfg=prepare_campaign(self.base,dict(self.cfg,mode='Full range scan',new_budget=0,bounds=bounds))
  self.assertEqual([len(d['values']) for d in cfg['dimensions']],[201,101])
  self.assertEqual(cfg['design_count'],20301)
  values=candidates(self.base,cfg,set(),cfg['design_count'],42)
  self.assertEqual(len(values),20301)
  self.assertEqual({tuple(v) for v in values},set(itertools.product(*(d['values'] for d in cfg['dimensions']))))

 def test_full_grid_retains_per_dimension_allocation_safety_limit(self):
  with self.assertRaisesRegex(ValueError,'20,001.*safety limit of 10,000'):
   prepare_campaign(self.base,dict(self.cfg,mode='Full range scan',new_budget=0,bounds=[dict(Parameter='thickness',Target='Device',Min=.20,Max=.30,Step=.000005,Choices='')]))

 def test_changed_contours_and_rta_start_new_campaign(self):
  self.run_campaign('a');events=[]
  cfg=dict(self.cfg,resume_file=str(self.root/'a/campaign.json'),contour_step=.001,half_window=2.,reuse=False)
  result=execute_campaign(self.base,{},cfg,self.root/'b',self.spectrum,emit=events.append,field_executor=self.fields)
  self.assertEqual(result['summary']['new_simulations'],6)
  self.assertTrue(any('Starting a new campaign' in e.get('text','') for e in events))
  self.assertTrue((self.root/'a/campaign.json').is_file())
  self.assertEqual(read_json(self.root/'b/campaign.json')['settings']['resume_file'],'')
 def test_switching_to_full_scan_does_not_keep_short_sample_plan(self):
  self.run_campaign('a')
  result=self.run_campaign('b',resume_file=str(self.root/'a/campaign.json'),mode='Full range scan',new_budget=0)
  self.assertEqual(result['summary']['completed'],11)
