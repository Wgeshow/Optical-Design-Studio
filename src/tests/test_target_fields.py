import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from data_library import write_json,read_json
from field_solver import execute_fields,contains
from model import DEFAULT_PERFORMANCE
from peak_optimizer import parse_search,geometry_error
from target_optimizer import target_metrics,compatible_record,execute_target_search,field_candidate
from target_ui import plot_fields,target_project,HOLE_COLS
from test_backend import sample,MATERIALS,LAYERS,PATTERNS,SETTINGS


def config(base,**values):
    cfg=parse_search(base,[dict(Parameter='thickness',Target='Device',Min=.2,Max=.3,Step=.025,Choices='')],
        dict(search_mode='ML assisted',initial_designs=2,ml_trials=3,candidate_pool=32,random_seed=42,
             design_budget=10,point_budget=100000,refinement_rounds=2,finalists=2))
    cfg.update(target_nm=1550.,tolerance_nm=5.,minimum_q=1000.,use_fields=True,field_grid=3,map_grid=3,
               history_limit=30,reuse_saved=False,all_shape_bridges=True)
    cfg.update(values)
    return cfg


def spectrum(model,perf,emit,cancelled):
    center=1550+40*(model['layers'][1]['thickness']-.25)
    return [[i,w,t,1-.9995/(1+((w-center)/.5)**2),0.,.9995/(1+((w-center)/.5)**2)] for i,w,t in model['points']],{}


def fields(model,perf,cfg,directory,cancelled):
    return dict(wavelength_nm=cfg['wavelength_nm'],grid=cfg['grid'],log_concentration=model['layers'][1]['thickness']*10)


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.base=sample(wl_start_nm=1535,wl_stop_nm=1565,wl_step_nm=.1)
        self.cfg=config(self.base)

    def test_off_target_or_low_q_peak_cannot_qualify(self):
        rows,_=spectrum(self.base,{},None,None)
        self.assertGreater(target_metrics(rows,self.cfg)['feasible_q'],1000)
        self.assertIsNone(target_metrics(rows,dict(self.cfg,target_nm=1560))['feasible_q'])
        self.assertIsNone(target_metrics(rows,dict(self.cfg,minimum_q=100000))['feasible_q'])
        self.assertIsNone(target_metrics([[i,w,t,r,tt,min(a,.99)] for i,w,t,r,tt,a in rows],self.cfg)['feasible_q'])

    def test_saved_data_must_match_physics_and_bounds(self):
        rows,_=spectrum(self.base,{},None,None)
        self.assertIsNotNone(compatible_record(self.base,rows,self.base,self.cfg,'prior'))
        other=copy.deepcopy(self.base)
        other['materials'][1]['b']+=.01
        self.assertIsNone(compatible_record(other,rows,self.base,self.cfg,'prior'))
        other=copy.deepcopy(self.base)
        other['basis']+=1
        self.assertIsNone(compatible_record(other,rows,self.base,self.cfg,'prior'))
        self.assertIsNone(compatible_record(self.base,rows[1:],self.base,self.cfg,'prior'))

    def test_targets_verify_and_history_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            one=Path(temp)/'one'; one.mkdir()
            event=execute_target_search(self.base,dict(DEFAULT_PERFORMANCE,timeout_seconds=60),self.cfg,one,spectrum,lambda e:None,lambda:False,fields)
            self.assertEqual(event['summary']['status'],'complete',event)
            self.assertGreater(event['summary']['maximum_verified_Q'],1000)
            self.assertTrue((one/'recommended_design.json').exists())
            two=Path(temp)/'two'; two.mkdir()
            cfg=dict(self.cfg,reuse_saved=True,ml_trials=1)
            event=execute_target_search(self.base,dict(DEFAULT_PERFORMANCE,timeout_seconds=60),cfg,two,spectrum,lambda e:None,lambda:False,fields)
            self.assertGreaterEqual(event['summary']['reused_training_records'],3,event)

    def test_field_observations_change_exploration_choice(self):
        observations=[]
        for x in (.2,.225,.25,.275):
            observations.append(dict(values=[x],status='evaluated',fields=dict(log_concentration=x*10)))
        with patch('target_optimizer.fit_predict',return_value=(np.array([1.,3.]),np.array([.1,.1]),[])) as fit:
            selected,prediction=field_candidate([[.21],[.29]],observations,self.cfg)
            self.assertEqual(selected,[.29])
            self.assertIn('field',prediction['selection_reason'])
            self.assertEqual(fit.call_args.args[1],[2.,2.25,2.5,2.75])

    def test_cancellation_preserves_checkpoint_without_recommendation(self):
        with tempfile.TemporaryDirectory() as temp:
            event=execute_target_search(self.base,dict(DEFAULT_PERFORMANCE,timeout_seconds=60),self.cfg,temp,spectrum,lambda e:None,lambda:True,fields)
            self.assertEqual(event['summary']['status'],'partial')
            self.assertIsNone(event['summary']['maximum_verified_Q'])
            self.assertTrue((Path(temp)/'target_history.json').exists())

    def test_rectangle_bridge_constraints(self):
        model=copy.deepcopy(self.base)
        model['patterns'][0].update(shape='rectangle',sx=.9,sy=.1)
        self.assertIn('bridge',geometry_error(model,self.cfg))

    def test_hole_shape_and_bounds_compile(self):
        project=dict(materials=MATERIALS,layers=LAYERS,patterns=PATTERNS,settings=SETTINGS)
        holes=[dict(zip(HOLE_COLS,['Device','ellipse',.1,.2,.05,.1]))]
        updated,bounds=target_project(project,holes,[],1550,5,1000,20,.1,11)
        self.assertEqual(updated['patterns'][0]['Shape'],'ellipse')
        self.assertEqual([r['Parameter'] for r in bounds],['size_x','size_y'])
        self.assertEqual(updated['settings']['wl_start_nm'],1530)


class NativeFieldTests(unittest.TestCase):
    def test_uniform_field_intensity_and_saved_maps(self):
        model=sample(wl_start_nm=1550,wl_stop_nm=1550)
        for material in model['materials']: material.update(a=1.,b=0.)
        with tempfile.TemporaryDirectory() as temp:
            cfg=dict(wavelength_nm=1550.,grid=3,maps=True,layer='Device')
            result=execute_fields(model,dict(DEFAULT_PERFORMANCE,timeout_seconds=60),cfg,temp)
            self.assertAlmostEqual(result['mean_pcs_E2'],1.,places=7)
            self.assertAlmostEqual(result['layers']['Device']['max_E2'],1.,places=7)
            fig=plot_fields(temp)
            self.assertTrue((Path(temp)/'electric_field_maps.png').exists())
            self.assertEqual(len(fig.axes),4)


if __name__=='__main__': unittest.main()
