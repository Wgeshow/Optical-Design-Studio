import copy
import csv
import sys
import tempfile
import unittest
from pathlib import Path
from comsol_carriers import import_comsol_profiles
from carrier_index import carrier_shifted_model,state_changes,validate_configuration

class ComsolTests(unittest.TestCase):
    def test_duplicate_limits_and_negative_tolerance(self):
        with tempfile.TemporaryDirectory() as tmp:
            files=[Path(tmp)/str(i) for i in range(4)]
            for f in files:f.write_text('% arc um / concentration\n0 10\n0.05 10\n0.05 100\n0.2 100\n0.22 100\n0.42 100\n')
            files[2].write_text('0 -5\n0.05 -5\n0.05 1000\n0.2 1000\n0.22 1000\n0.42 1000\n')
            with self.assertRaises(ValueError):import_comsol_profiles(*files,'Top','Bottom')
            result=import_comsol_profiles(*files,'Top','Bottom',negative_tolerance_cm3=10)
            limits=[r for r in result['profiles'] if r['layer']=='Top' and r['z_um']==.05]
            self.assertEqual([r['electron_cm3'] for r in limits],[0,1000])
            self.assertEqual([r['side'] for r in limits],['left','right'])
            self.assertEqual(result['report']['clipped_count'],2)
            self.assertEqual(len(result['report']['source_files'][0]['sha256']),64)
            with self.assertRaises(ValueError):import_comsol_profiles(*files,'Top','Bottom',negative_tolerance_cm3=1e8)

    def test_weighted_index_and_undoped_reference(self):
        model=dict(materials=[dict(name='GaAs',model='constant_nk',a=3.4,b=0)],
                   layers=[dict(name='Top',thickness=.2,material='GaAs')],patterns=[],points=[[0,1550,0]])
        rows=[dict(layer='Top',z_um=z,side=side,reference_electron_cm3=1e18,reference_hole_cm3=0,electron_cm3=n,hole_cm3=0)
              for z,side,n in [(0,'right',0),(.05,'left',0),(.05,'right',1e18),(.2,'left',1e18)]]
        state=dict(label='9V',profiles=rows)
        cfg=validate_configuration(dict(silicon_confirmed=True,optical_reference='undoped',profile_sampling='knots',states=[state]))
        state=cfg['states'][0]
        changed=carrier_shifted_model(model,'GaAs',['Top'],state,cfg)
        self.assertEqual([l['thickness'] for l in changed['layers']],[.05,.15000000000000002])
        from carrier_index import evaluate_state
        depletion=evaluate_state(1550,3.4,1e18,0,0,0)['delta_n']
        self.assertAlmostEqual(state_changes(model,'GaAs',['Top'],state,cfg,1550)['Top']['delta_n'],depletion*.25)
        self.assertTrue(all(m['table'][0][2]>=0 for m in changed['materials'][1:]))
        with self.assertRaisesRegex(ValueError,'negative k'):
            carrier_shifted_model(model,'GaAs',['Top'],state,dict(cfg,optical_reference='reference'))

    def test_actual_supplied_files_native_s4(self):
        directory=Path.home()/'Downloads';files=[directory/n for n in ('0elec','0hole','9elc','9hole')]
        if not all(f.exists() for f in files):self.skipTest('User-supplied COMSOL files unavailable.')
        imported=import_comsol_profiles(*files,'TopGaAs','BottomGaAs',negative_tolerance_cm3=1e4)
        self.assertGreater(imported['report']['clipped_count'],0)
        self.assertEqual(len([p for p in imported['profiles'] if p['layer']=='TopGaAs' and p['z_um']==.05]),2)
        sys.path.insert(0,str(Path(__file__).parent))
        from test_backend import sample
        from index_shift import prepare_sweep,execute_sweep
        from backend import execute
        from model import DEFAULT_PERFORMANCE
        model=sample(NumG=5);model['points']=[[i,w,0] for i,w in enumerate([1530,1550,1570])]
        model['materials'].append(dict(name='AlGaAs',model='constant_nk',a=3.1,b=0))
        model['layers']=[dict(name='AirAbove',material='Air',thickness=0),dict(name='TopGaAs',material='Film',thickness=.2),
                         dict(name='AlGaAsSpacer',material='AlGaAs',thickness=.02),dict(name='BottomGaAs',material='Film',thickness=.2),dict(name='Below',material='Glass',thickness=0)]
        model['patterns']=[dict(model['patterns'][0],layer=n) for n in ('TopGaAs','BottomGaAs')]
        source=copy.deepcopy(model)
        carrier=dict(semiconductor='GaAs',material_confirmed=True,mass_e_m0=.067,mass_h_m0=.45,mobility_e_cm2_Vs=8000,mobility_h_cm2_Vs=400,
                     profile_sampling='knots',optical_reference='undoped',states=[dict(label='9V',bias_v=9,profiles=imported['profiles'])])
        options=dict(material='Film',layers=[dict(layer='TopGaAs'),dict(layer='BottomGaAs')],reference_nm=1550,tracking_window_nm=30,sweep_mode='carrier',carrier=carrier)
        cfg=prepare_sweep(model,options)
        biased=carrier_shifted_model(model,'Film',['TopGaAs','BottomGaAs'],cfg['carrier_states'][1],cfg['carrier'])
        self.assertEqual(model,source)
        self.assertIn(source['layers'][2],biased['layers'])
        self.assertAlmostEqual(sum(l['thickness'] for l in biased['layers']),.42)
        with tempfile.TemporaryDirectory() as tmp:
            result=execute_sweep(model,dict(DEFAULT_PERFORMANCE,workers=1,timeout_seconds=120),cfg,tmp,execute)
            with (Path(tmp)/'index_shift_spectra.csv').open() as f:records=list(csv.DictReader(f))
            self.assertEqual(len(records),6)
            self.assertTrue(all(float(r['dn:TopGaAs'])==0 and float(r['dn:BottomGaAs'])==0 for r in records[:3]))
            self.assertGreater(max(abs(float(a['R'])-float(b['R'])) for a,b in zip(records[:3],records[3:])),1e-8)
            self.assertTrue(result['summary']['depth_profiles'])

if __name__=='__main__':unittest.main()
