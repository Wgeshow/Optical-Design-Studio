import copy,json,os,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from test_backend import sample,run,MATERIALS,LAYERS,PATTERNS,SETTINGS
from model import DEFAULT_PERFORMANCE,epsilon
from index_shift import prepare_sweep,shifted_model,shifted_material,execute_sweep,sampled_feature
from linked_hole_sweep import shared_radius_bounds
from peak_optimizer import parse_search,designs
from ml_optimizer import model_for

def multilayer():
    m=sample()
    m['layers'].insert(2,dict(name='Second',thickness=.2,material='Film'))
    m['patterns'].append(dict(m['patterns'][0],layer='Second'))
    return m

def options(**values):
    return dict(dict(material='Film',equal=True,start=0,stop=.02,samples=3,layers=[dict(layer='Device',start=0,stop=.02,samples=3),dict(layer='Second',start=0,stop=.04,samples=3)],reference_nm=1550,tracking_window_nm=100,response='Reflection',feature='Peak'),**values)

class IndexTests(unittest.TestCase):
    def test_selected_layer_is_cloned_not_shared_library_mutated(self):
        m=multilayer();original=copy.deepcopy(m)
        s=shifted_model(m,'Film',{'Device':.1})
        mats={v['name']:v for v in s['materials']}
        self.assertAlmostEqual(mats[s['layers'][1]['material']]['a'],3.5)
        self.assertEqual(s['layers'][2]['material'],'Film')
        self.assertEqual(m,original)
        s=shifted_model(m,'Air',{'Device':.03})
        self.assertEqual(s['layers'][0]['material'],'Air')
        self.assertNotEqual(s['patterns'][0]['material'],'Air')
        self.assertEqual(s['patterns'][1]['material'],'Air')

    def test_equal_and_independent_combinations(self):
        m=multilayer();cfg=prepare_sweep(m,options())
        self.assertEqual(len(cfg['assignments']),3)
        self.assertTrue(all(a['Device']==a['Second'] for a in cfg['assignments']))
        cfg=prepare_sweep(m,options(equal=False))
        self.assertEqual(len(cfg['assignments']),9)
        self.assertIn({'Device':.01,'Second':.04},cfg['assignments'])
        self.assertEqual(cfg['assignments'][0],{'Device':0.,'Second':0.})

    def test_dispersion_and_k_preserved(self):
        material=dict(name='table',model='table_nk',a=1,b=0,grid=[1500,1600],table=[[1500,1.4,.01],[1600,1.5,.02]])
        shifted=shifted_material(material,.03)
        self.assertAlmostEqual(epsilon(shifted,1550).real,(1.48**2-.015**2))
        self.assertEqual([r[2] for r in shifted['table']],[.01,.02])
        eps=shifted_material(dict(name='eps',model='constant_eps',a=4,b=0),.1)
        self.assertAlmostEqual(epsilon(eps,1550).real,2.1**2)

    def test_invalid_and_excessive_sweeps(self):
        m=multilayer()
        for cfg in [options(layers=[]),options(samples=1),options(start=-5),options(equal=False,layers=[dict(layer=n,start=0,stop=.1,samples=101) for n in ['Device','Second']])]:
            with self.assertRaises(ValueError):prepare_sweep(m,cfg)

    def test_tracking_rejects_edges_and_missing_feature(self):
        rows=[[i,1500+i,0,.1*i,1-.1*i,0] for i in range(5)]
        self.assertIsNone(sampled_feature(rows,'Reflection','Peak',1502,100))

    def test_native_sweep_and_saved_outputs(self):
        from backend import execute
        m=multilayer();m['points']=[[i,w,0] for i,w in enumerate([1450,1500,1550,1600])]
        cfg=prepare_sweep(m,options(samples=2))
        with tempfile.TemporaryDirectory() as directory:
            result=execute_sweep(m,dict(DEFAULT_PERFORMANCE,workers=1,timeout_seconds=60),cfg,directory,execute)
            self.assertEqual(result['summary']['spectra'],2)
            import pandas as pd
            data=pd.read_csv(Path(directory)/'index_shift_spectra.csv')
            self.assertEqual(len(data),8)
            self.assertTrue((data['dn:Device']==data['dn:Second']).all())
            self.assertGreater(abs(data[data['case']==0].R.to_numpy()-data[data['case']==1].R.to_numpy()).max(),1e-6)

class SharedHoleTests(unittest.TestCase):
    def test_shared_nm_radius_grid_and_ml(self):
        m=multilayer()
        cfg=dict(enabled=True,targets=[1,2],min_um=.0001,max_um=.0003,step_um=.0001)
        bounds=shared_radius_bounds(m,[dict(Parameter='radius',Target='2',Min=.1,Max=.2,Step=.1)],cfg)
        search=parse_search(m,bounds,dict(design_budget=10))
        self.assertEqual(search['design_count'],3)
        for design in designs(m,search):self.assertEqual(design['patterns'][0]['sx'],design['patterns'][1]['sx'])
        self.assertAlmostEqual(next(designs(m,search))['patterns'][1]['sx'],.0001)
        learned=model_for(m,search,[.0002])
        self.assertEqual([r['sx'] for r in learned['patterns']],[.0002,.0002])

    def test_invalid_targets_rejected(self):
        with self.assertRaises(ValueError):shared_radius_bounds(multilayer(),[],dict(enabled=True,targets=[3],min_um=.1,max_um=.2,step_um=.1))

class IndexUiTests(unittest.TestCase):
    def test_controls_persist_and_shared_unit_conversion(self):
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
        from data_library import DataLibrary
        from qt_core import ProjectStore,prepare_job
        from qt_index_shift import IndexShiftPage
        from linked_hole_sweep import make_widget
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(DataLibrary(directory),restore=False)
            project=dict(materials=MATERIALS,layers=LAYERS,patterns=PATTERNS,settings=SETTINGS,performance=DEFAULT_PERFORMANCE)
            store.load_project(project)
            page=IndexShiftPage(store)
            page.material.setCurrentIndex(page.material.findData('Film'))
            page.layers.cellWidget(0,0).setChecked(True)
            page.controls['reference_nm'].setValue(1500)
            page.changed()
            self.assertEqual(store.search_state['index_shift']['material'],'Film')
            _,job=prepare_job('index_shift',store.project(),page.options(),store.library)
            self.assertEqual(len(job['search']['assignments']),3)
            page.equal.setChecked(False)
            self.assertFalse(page.layers.isColumnHidden(2))
            restored=IndexShiftPage(store)
            self.assertFalse(restored.equal.isChecked())
            self.assertTrue(restored.layers.cellWidget(0,0).isChecked())
            linked=make_widget(store);linked.enabled.setChecked(True)
            linked.minimum.setValue(.1)
            self.assertAlmostEqual(linked.options()['min_um'],.0001)
            linked.unit.setCurrentIndex(1)
            self.assertAlmostEqual(linked.minimum.value(),.0001)
            page.close();restored.close();linked.close()

if __name__=='__main__':unittest.main()
