import csv
import math
import tempfile
import unittest
from pathlib import Path
from backend import execute
from model import DEFAULT_PERFORMANCE, sweep, MAX_SWEEP_POINTS
from peak_optimizer import parse_search, execute_search, analyze_grid_results
from test_backend import sample
from spectral_phase import write_phase_csv

class SpectralFeatures(unittest.TestCase):
    def test_more_than_two_million_points(self):
        values = sweep(1, 3.000001, .000001, 'Wavelength')
        self.assertEqual(len(values), 2000002)
        self.assertAlmostEqual(values[-1], 3.000001)
        self.assertEqual(parse_search(sample(), [], {'point_budget':MAX_SWEEP_POINTS})['point_budget'], MAX_SWEEP_POINTS)
        with self.assertRaises(ValueError): sweep(0, MAX_SWEEP_POINTS, 1, 'Wavelength')

    def test_reflection_search_keeps_physical_spectrum(self):
        base=sample(wl_start_nm=1500,wl_stop_nm=1502,wl_step_nm=1)
        cfg=parse_search(base, [], dict(response='Reflection', absorption_target=.5, refinement_rounds=0))
        def executor(model, *args):
            return [[i,w,t,r,1-r,0.] for (i,w,t),r in zip(model['points'], [.1,.8,.1])], {}
        with tempfile.TemporaryDirectory() as d:
            result=execute_search(base, DEFAULT_PERFORMANCE, cfg, d, executor, lambda e:None, lambda:False)
            self.assertEqual(result['summary']['search_mode'],'Exhaustive grid')
            self.assertAlmostEqual(analyze_grid_results(d, 'Reflection')[0]['response_value'],.8)
            rows=list(csv.DictReader((Path(d)/'design_1_spectrum.csv').read_text().splitlines()))
            self.assertEqual(float(rows[1]['A']),0.)
            self.assertEqual(float(rows[1]['R']),.8)

    def test_phase_native_uniform_propagation(self):
        for polarization in ['s','p','45° s+p']:
            model=sample(wl_start_nm=1000,wl_stop_nm=1200,wl_step_nm=100,polarization=polarization)
            model['patterns']=[]
            for layer in model['layers']: layer['material']='Air'
            model['measure_phase']=True
            rows,info=execute(model,dict(DEFAULT_PERFORMANCE,workers=1))
            for row in info['phase_rows']:
                self.assertIsNone(row[3])
                expected=(360*1000*.25/row[1]+180)%360-180
                self.assertAlmostEqual(row[4],expected,places=7)

    def test_native_interface_reflection_phase(self):
        for polarization in ['s','p']:
            model=sample(wl_start_nm=1000,wl_stop_nm=1000,polarization=polarization)
            model['patterns']=[]
            model['layers'][1]['material']='Glass'
            model['layers'][1]['thickness']=0
            model['measure_phase']=True
            _,info=execute(model,dict(DEFAULT_PERFORMANCE,workers=1))
            phase=info['phase_rows'][0]
            self.assertAlmostEqual(abs(phase[3]),180.,places=7)
            self.assertAlmostEqual(phase[4],0.,places=7)

    def test_ml_response_and_resume_identity(self):
        from ml_optimizer import execute_ml_search, fingerprint
        from test_ml_optimizer import config, fake_executor
        base=sample(wl_start_nm=1535,wl_stop_nm=1565,wl_step_nm=1)
        absorption=config(base, refinement_rounds=0, ml_trials=3, initial_designs=3)
        reflection=dict(absorption,response='Reflection')
        self.assertNotEqual(fingerprint(base,absorption),fingerprint(base,reflection))
        fake=fake_executor([])
        def executor(*args):
            rows,info=fake(*args)
            return [[i,w,t,a,r,0.] for i,w,t,r,_,a in rows],info
        with tempfile.TemporaryDirectory() as d:
            result=execute_ml_search(base,dict(DEFAULT_PERFORMANCE,timeout_seconds=120),reflection,d,executor,lambda e:None,lambda:False)
            self.assertEqual(result['summary']['response'],'Reflection')
            self.assertGreater(result['summary']['best_absorption'],.3)

    def test_unwrap_and_undefined_gap(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'phase.csv'
            write_phase_csv(path,[[0,1,0,170,0],[1,2,0,-170,None],[2,3,0,None,90],[3,4,0,-160,100]])
            rows=list(csv.DictReader(path.read_text().splitlines()))
            self.assertEqual(float(rows[1]['reflection_change_deg']),20.)
            self.assertEqual(rows[2]['reflection_change_deg'],'')
            self.assertEqual(float(rows[3]['reflection_change_deg']),0.)

if __name__=='__main__': unittest.main()
