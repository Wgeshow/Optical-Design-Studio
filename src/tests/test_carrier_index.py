import copy
import math
import os
import tempfile
import unittest
from pathlib import Path
from carrier_index import evaluate_state,validate_configuration,carrier_shifted_model,read_states_csv

class CarrierIndexTests(unittest.TestCase):
    def test_zero_injection_and_reverse(self):
        args=(1550,3.48,0,0,1e18,1e18)
        change=evaluate_state(*args)
        self.assertLess(change['delta_n'],0);self.assertGreater(change['delta_k'],0)
        inverse=evaluate_state(1550,3.48,1e18,1e18,0,0)
        for key in ('delta_n','delta_k','delta_alpha_cm1'):self.assertEqual(change[key],-inverse[key])
        zero=evaluate_state(1550,3.48,1e18,2e18,1e18,2e18)
        self.assertEqual(zero['delta_n'],0);self.assertEqual(zero['delta_k'],0)

    def test_units_and_equation_reference(self):
        v=evaluate_state(1550,3.48,0,0,1e18,0)
        # Independent plasma frequency expression, SI conversion cm^-3 -> m^-3.
        omega=2*math.pi*299792458/(1550e-9)
        omega_p2=1e24*(1.602176634e-19)**2/(8.8541878128e-12*.26*9.1093837139e-31)
        self.assertAlmostEqual(v['delta_n'],-omega_p2/(2*3.48*omega**2),places=15)
        self.assertAlmostEqual(v['delta_k'],v['delta_alpha_cm1']*1550e-7/(4*math.pi),places=15)
        doubled=evaluate_state(1550,3.48,0,0,2e18,0)
        self.assertAlmostEqual(doubled['delta_n'],2*v['delta_n'])
        slower=evaluate_state(1550,3.48,0,0,1e18,0,675,480)
        self.assertAlmostEqual(slower['delta_alpha_cm1'],2*v['delta_alpha_cm1'])

    def test_invalid_inputs(self):
        for w in (999,2001,float('nan')):
            with self.assertRaises(ValueError):evaluate_state(w,3.48,0,0,1e18,0)
        for n in (-1,float('inf'),1e21,True):
            with self.assertRaises(ValueError):evaluate_state(1550,3.48,0,0,n,0)
        with self.assertRaises(ValueError):evaluate_state(1550,3.48,0,0,1e18,0,0,480)
        with self.assertRaises(ValueError):validate_configuration(dict(states=[dict(electron_cm3=0,hole_cm3=0)]))

    def model(self):
        return dict(materials=[dict(name='Si',model='constant_nk',a=3.48,b=.001)],
                    layers=[dict(name='one',material='Si'),dict(name='two',material='Si')],
                    patterns=[dict(layer='one',material='Si')],points=[[0,1500,0],[1,1550,0],[2,1600,0]])

    def test_clone_and_wavelength_dependence(self):
        model=self.model();before=copy.deepcopy(model)
        state=dict(label='biased',electron_cm3=1e18,hole_cm3=1e18)
        changed=carrier_shifted_model(model,'Si',['one'],state,dict(silicon_confirmed=True))
        self.assertEqual(model,before)
        self.assertEqual(changed['layers'][1]['material'],'Si')
        self.assertEqual(changed['patterns'][0]['material'],changed['layers'][0]['material'])
        material=changed['materials'][-1]
        self.assertEqual(material['grid'],[1500,1550,1600])
        self.assertGreater(material['table'][0][1],material['table'][-1][1])
        self.assertLess(material['table'][0][2],material['table'][-1][2])

    def test_negative_loss_and_material_validation(self):
        model=self.model();model['materials'][0]['b']=0
        state=dict(label='depleted',electron_cm3=0,hole_cm3=0)
        with self.assertRaisesRegex(ValueError,'negative k'):
            carrier_shifted_model(model,'Si',['one'],state,dict(silicon_confirmed=True,reference_electron_cm3=1e18))
        with self.assertRaises(ValueError):carrier_shifted_model(model,'Si',['absent'],state,dict(silicon_confirmed=True))

    def test_csv_units_and_depletion_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'states.csv'
            path.write_text('label,electron_cm3,hole_cm3,bias_v\non,1e18,2e18,1\noff,0,0,-1\n')
            states=read_states_csv(path)
            self.assertEqual(states[0]['electron_cm3'],1e18)
            self.assertEqual(states[1]['bias_v'],-1)
            path.write_text('electron_m3,hole_m3\n1,1\n')
            with self.assertRaises(ValueError):read_states_csv(path)

    def test_dialog_roundtrip(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PyQt6.QtWidgets import QApplication
        from qt_carrier_index import CarrierIndexDialog
        app=QApplication.instance() or QApplication([])
        cfg=dict(silicon_confirmed=True,reference_electron_cm3=1e17,reference_hole_cm3=0,
                 states=[dict(label='biased',electron_cm3=1e18,hole_cm3=1e18,bias_v=2)])
        dialog=CarrierIndexDialog(configuration=cfg)
        self.assertEqual(dialog.configuration()['states'][0]['bias_v'],2)
        dialog.preview();self.assertIn('Δn',dialog.preview_label.text());dialog.close()

    def test_carrier_fixed_readout_tracks_baseline_wavelength(self):
        from index_shift import prepare_sweep,execute_sweep
        import csv,json
        model=self.model();model['mode']='Wavelength sweep'
        config=dict(material='Si',layers=[dict(layer='one'),dict(layer='two')],reference_nm=1550,
                    tracking_window_nm=100,sweep_mode='carrier',carrier=dict(silicon_confirmed=True,
                    states=[dict(label='on',electron_cm3=1e18,hole_cm3=1e18,bias_v=1)]))
        cfg=prepare_sweep(model,config)
        calls=[]
        def executor(m,*args):
            calls.append(m);powers=[.1,.9,.2] if len(calls)==1 else [.8,.3,.1]
            return [[i,w,0,r,1-r,0] for i,(w,r) in enumerate(zip([1500,1550,1600],powers))],{}
        with tempfile.TemporaryDirectory() as tmp:
            result=execute_sweep(model,{},cfg,tmp,executor)
            with (Path(tmp)/'index_shift_readout.csv').open() as stream:records=list(csv.DictReader(stream))
            self.assertEqual(float(records[1]['value']),.3)
            self.assertAlmostEqual(float(records[1]['delta_value']),-.6)
            self.assertEqual(float(records[1]['index_evaluation_nm']),1550)
            self.assertEqual(records[1]['dn:one'],records[1]['dn:two'])
            self.assertEqual(result['summary']['sweep_mode'],'carrier')
            self.assertEqual(records[1]['state_label'],'on')

    def test_native_carrier_sweep(self):
        import sys,csv
        sys.path.insert(0,str(Path(__file__).parent))
        from test_backend import sample
        from backend import execute
        from model import DEFAULT_PERFORMANCE
        from index_shift import prepare_sweep,execute_sweep
        model=sample();model['points']=[[i,w,0] for i,w in enumerate([1500,1550,1600])]
        cfg=prepare_sweep(model,dict(material='Film',layers=[dict(layer='Device')],reference_nm=1550,
             tracking_window_nm=100,sweep_mode='carrier',carrier=dict(silicon_confirmed=True,
             states=[dict(label='on',electron_cm3=1e19,hole_cm3=1e19)])))
        with tempfile.TemporaryDirectory() as tmp:
            execute_sweep(model,dict(DEFAULT_PERFORMANCE,workers=1,timeout_seconds=60),cfg,tmp,execute)
            with (Path(tmp)/'index_shift_spectra.csv').open() as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),6)
            self.assertGreater(max(abs(float(rows[i]['R'])-float(rows[i+3]['R'])) for i in range(3)),1e-6)
            self.assertTrue(all(float(r['dk:Device'])>0 for r in rows[3:]))

    def profile(self,layer='one',thickness=.2):
        return [dict(layer=layer,z_um=z,reference_electron_cm3=0,reference_hole_cm3=0,
                     electron_cm3=n,hole_cm3=0) for z,n in [(0,0),(thickness,1e19)]]

    def test_gaas_and_custom_mass_validation(self):
        cfg=dict(semiconductor='GaAs',material_confirmed=True,mobility_e_cm2_Vs=8000,mobility_h_cm2_Vs=400,
                 states=[dict(label='on',electron_cm3=1e18,hole_cm3=0)])
        normalized=validate_configuration(cfg)
        self.assertEqual(normalized['mass_e_m0'],.067)
        v=evaluate_state(1550,3.48,0,0,1e18,0,mass_e_m0=.067,mass_h_m0=.45)
        si=evaluate_state(1550,3.48,0,0,1e18,0)
        self.assertAlmostEqual(v['delta_n']/si['delta_n'],.26/.067)
        with self.assertRaises(ValueError):validate_configuration(dict(cfg,semiconductor='Custom'))
        invalid=dict(cfg);invalid.pop('mobility_e_cm2_Vs')
        with self.assertRaises(ValueError):validate_configuration(invalid)

    def test_profile_slicing_preserves_patterns_and_thickness(self):
        model=self.model();model['layers'][0]['thickness']=.2;model['layers'][1]['thickness']=.3
        before=copy.deepcopy(model)
        state=dict(label='depth',profiles=self.profile())
        cfg=dict(silicon_confirmed=True,profile_slices=4)
        changed=carrier_shifted_model(model,'Si',['one'],state,cfg)
        self.assertEqual(model,before)
        self.assertEqual(len(changed['layers']),5)
        self.assertAlmostEqual(sum(l['thickness'] for l in changed['layers'][:4]),.2)
        self.assertEqual(len(changed['patterns']),4)
        self.assertEqual(changed['layers'][-1],model['layers'][-1])
        self.assertEqual([p['layer'] for p in changed['patterns']],[l['name'] for l in changed['layers'][:4]])
        for sample,expected in zip(changed['carrier_profile_segments'],[1.25e18,3.75e18,6.25e18,8.75e18]):self.assertAlmostEqual(sample['electron_cm3']/expected,1.)

    def test_profile_validation_and_junction(self):
        from carrier_index import junction_estimate
        m=self.model();m['layers'][0]['thickness']=.2;m['layers'][1]['thickness']=.3
        for profile in [self.profile(thickness=.1),self.profile(layer='unknown'),self.profile()+[self.profile()[0]]]:
            with self.assertRaises(ValueError):carrier_shifted_model(m,'Si',['one'],dict(label='x',profiles=profile),dict(silicon_confirmed=True))
        j=junction_estimate(1e17,1e17,1e10,11.7,300,0)
        self.assertAlmostEqual(j['built_in_V'],.83337,places=4)
        self.assertAlmostEqual(j['p_width_um'],j['n_width_um'])
        j2=junction_estimate(1e17,1e17,1e10,11.7,300,j['built_in_V'])
        self.assertAlmostEqual(j2['width_um']/j['width_um'],math.sqrt(2))
        with self.assertRaises(ValueError):junction_estimate(1e17,1e17,1e10,11.7,300,-1)

    def test_native_depth_profile_converges_and_readout(self):
        import sys,csv
        sys.path.insert(0,str(Path(__file__).parent))
        from test_backend import sample
        from backend import execute
        from model import DEFAULT_PERFORMANCE
        from index_shift import prepare_sweep,execute_sweep
        model=sample();model['points']=[[i,w,0] for i,w in enumerate([1500,1550,1600])]
        layer=next(l for l in model['layers'] if l['name']=='Device')
        state=dict(label='depth',profiles=self.profile('Device',layer['thickness']))
        options=dict(material='Film',layers=[dict(layer='Device')],reference_nm=1550,tracking_window_nm=100,
                     sweep_mode='carrier',carrier=dict(silicon_confirmed=True,profile_slices=4,states=[state]))
        cfg=prepare_sweep(model,options)
        self.assertEqual(len(cfg['carrier_states'][0]['profiles']),2)
        perf=dict(DEFAULT_PERFORMANCE,workers=1,timeout_seconds=60)
        with tempfile.TemporaryDirectory() as tmp:
            execute_sweep(model,perf,cfg,tmp,execute)
            with (Path(tmp)/'index_shift_spectra.csv').open() as f:rows=list(csv.DictReader(f))
            self.assertIn('thickness average',rows[-1]['index_average'])
            self.assertLess(float(rows[-1]['dn:Device']),0)
        m4=carrier_shifted_model(model,'Film',['Device'],state,cfg['carrier'])
        m8=carrier_shifted_model(model,'Film',['Device'],state,dict(cfg['carrier'],profile_slices=8))
        r4,_=execute(m4,perf);r8,_=execute(m8,perf)
        self.assertLess(max(abs(a[3]-b[3]) for a,b in zip(r4,r8)),.001)

if __name__=='__main__':unittest.main()
