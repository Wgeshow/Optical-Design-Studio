import copy
import os
import tempfile
import unittest
from pathlib import Path
import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from test_backend import sample, MATERIALS, LAYERS, PATTERNS, SETTINGS
from circle_geometry import solver_regions, merged_geometry_error, component_polygon, circle_components
from optical_objective import response_rows
from target_optimizer import target_metrics, execute_target_search
from peak_optimizer import parse_search, geometry_error
from ml_optimizer import validate_ml
from model import DEFAULT_PERFORMANCE, prepare
from backend import execute
from test_target_fields import config


class GeometryTests(unittest.TestCase):
    def cell(self):
        m=sample(ax_um=1,ay_um=1)
        m['patterns']=[dict(m['patterns'][0],cx=-.08,sx=.15),dict(m['patterns'][0],cx=.08,sx=.15)]
        return m

    def test_circle_union_is_one_valid_polygon(self):
        m=self.cell()
        regions=solver_regions(m)
        self.assertEqual([p['shape'] for p in regions],['polygon'])
        self.assertEqual(merged_geometry_error(m,.02,.03),'')
        self.assertEqual(len(m['patterns']),2)

    def test_periodic_union_wrap_and_bridge(self):
        m=self.cell()
        m['patterns'][0]['cx']=.46
        m['patterns'][1]['cx']=-.46
        self.assertEqual(len(solver_regions(m)),1)
        self.assertEqual(merged_geometry_error(m,.02,.03),'')
        self.assertIn('bridge',merged_geometry_error(m,.9,0))

    def test_disconnected_holes_and_neck(self):
        m=self.cell()
        m['patterns'][0]['cx']=-.2
        m['patterns'][1]['cx']=.2
        self.assertEqual(len(solver_regions(m)),2)
        self.assertIn('bridge',merged_geometry_error(m,.11,0))
        m=self.cell()
        m['patterns'][1]['cx']=.219
        self.assertIn('neck',merged_geometry_error(m,0,.05))

    def test_nested_material_island(self):
        m=self.cell()
        template=m['patterns'][0]
        m['patterns']=[dict(template,cx=.22*np.cos(a),cy=.22*np.sin(a),sx=.1) for a in np.linspace(0,2*np.pi,8,endpoint=False)]
        regions=solver_regions(m)
        self.assertEqual([r['material'] for r in regions],['Air','Film'])

    def test_native_union_spectrum_is_finite_and_conserves_power(self):
        m=self.cell()
        m['points']=[[0,1550.,0.]]
        m['materials'][1]['b']=0.
        rows,_=execute(m,dict(DEFAULT_PERFORMANCE,workers=1,timeout_seconds=60))
        self.assertEqual(len(rows),1)
        self.assertAlmostEqual(rows[0][3]+rows[0][4],1.,places=6)
        self.assertAlmostEqual(rows[0][5],0.,places=6)


class ResponseTests(unittest.TestCase):
    def test_response_selects_correct_peak_and_retains_raw_spectrum(self):
        m=sample(wl_start_nm=1500,wl_stop_nm=1600,wl_step_nm=.05)
        cfg=config(m,minimum_q=10,absorption_target=.8)
        for name,col in [('Absorption',5),('Transmission',4),('Reflection',3)]:
            rows=[]
            for i,w,t in m['points']:
                v=.95/(1+((w-1550)/2)**2)
                power=[0.,0.,0.]
                power[col-3]=v
                power[(col-3+1)%3]=1-v
                rows.append([i,w,t,*power])
            original=copy.deepcopy(rows)
            metrics=target_metrics(rows,dict(cfg,response=name))
            self.assertAlmostEqual(metrics['response_at_target'],.95)
            self.assertGreater(metrics['feasible_q'],300)
            self.assertEqual(rows,original)

    def test_target_amplitude_does_not_require_peak(self):
        m=sample(wl_start_nm=1540,wl_stop_nm=1560,wl_step_nm=1)
        rows=[[i,w,t,.9,.1,0.] for i,w,t in m['points']]
        metrics=target_metrics(rows,dict(config(m),response='Reflection',objective='Response at target',absorption_target=.85))
        self.assertTrue(metrics['response_feasible'])
        self.assertIsNone(metrics['feasible_q'])

    def test_ai_search_and_verification_use_selected_response(self):
        m=sample(wl_start_nm=1540,wl_stop_nm=1560,wl_step_nm=5)
        cfg=config(m,use_fields=False,response='Transmission',objective='Response at target',absorption_target=.7,refinement_rounds=0)
        def solver(model,*args):
            value=.95-(model['layers'][1]['thickness']-.275)**2*10
            return [[i,w,t,1-value,value,0.] for i,w,t in model['points']],{}
        with tempfile.TemporaryDirectory() as path:
            event=execute_target_search(m,dict(DEFAULT_PERFORMANCE,timeout_seconds=60),cfg,path,solver,lambda e:None,lambda:False)
            self.assertEqual(event['summary']['status'],'complete')
            self.assertGreater(event['summary']['verified_response_at_target'],.9)
            self.assertEqual(event['summary']['response'],'Transmission')
            self.assertIn('response_at_target',(Path(path)/'target_results.csv').read_text())

    def test_initial_basis_plateau_cannot_pass_verification(self):
        from data_library import read_json
        m=sample(wl_start_nm=1540,wl_stop_nm=1560,wl_step_nm=5)
        cfg=config(m,use_fields=False,response='Transmission',objective='Response at target',absorption_target=.7,refinement_rounds=0,finalists=1)
        def solver(model,*args):
            value=.9 if model['basis'] <= 26 else .8
            return [[i,w,t,1-value,value,0.] for i,w,t in model['points']],{}
        with tempfile.TemporaryDirectory() as path:
            event=execute_target_search(m,dict(DEFAULT_PERFORMANCE,timeout_seconds=60),cfg,path,solver,lambda e:None,lambda:False)
            self.assertAlmostEqual(event['summary']['verified_response_at_target'],.8)
            result=read_json(Path(path)/'recommended_design.json')
            self.assertEqual([r['agreement'] for r in result['convergence_checks']],[True,False,True,True])

    def test_target_response_history_requires_exact_target_sample(self):
        from target_optimizer import compatible_record
        m=sample(wl_start_nm=1540,wl_stop_nm=1560,wl_step_nm=5)
        rows=[[i,w,t,.1,.9,0.] for i,w,t in m['points'] if w != 1550]
        cfg=config(m,response='Transmission',objective='Response at target')
        self.assertIsNone(compatible_record(m,rows,m,cfg,'saved'))


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_multi_hole_dialog_ranges_and_saved_objective(self):
        from data_library import DataLibrary
        from qt_core import ProjectStore,prepare_job
        from qt_compute import OptimizePage
        from qt_multi_hole import MultiHoleDialog
        with tempfile.TemporaryDirectory() as path:
            store=ProjectStore(DataLibrary(path),restore=False)
            dialog=MultiHoleDialog(store)
            dialog.double_lattice()
            dialog.apply()
            self.assertEqual(dialog.result(),1,dialog.status.text())
            self.assertEqual(len(dialog.bounds),6)
            page=OptimizePage(store)
            page.target_controls['use_structure_patterns'].setChecked(True)
            page.target_controls['response'].setCurrentText('Reflection')
            page.target_controls['objective'].setCurrentText('Response at target')
            page.target_controls['response_threshold'].setValue(.7)
            page.target_bounds.set_records(dialog.bounds)
            options=page.target_options()
            _,job=prepare_job('target',store.portable_project(),options,store.library)
            self.assertEqual(job['search']['response'],'Reflection')
            self.assertEqual(len(job['search']['dimensions']),6)
            self.assertEqual(len(job['model']['patterns']),2)
            store.save_search('target',options)
            restored=ProjectStore(store.library,restore=True)
            self.assertEqual(restored.search_state['target']['response'],'Reflection')
            page.close(); dialog.close()

    def test_library_table_material_survives_search_and_coverage_checked(self):
        from data_library import DataLibrary
        from qt_core import ProjectStore,prepare_job
        from qt_design_materials import DesignMaterialsDialog
        from PyQt6.QtCore import Qt
        with tempfile.TemporaryDirectory() as path:
            library=DataLibrary(path)
            asset=library.asset(b'wavelength,n,k\n1500,2,0.01\n1600,2.1,0.02\n')
            library.save_preset(dict(Name='MeasuredFilm',Model='table_nk',A=1.,B=0.,DataFile=asset.name,WavelengthUnit='nm'),'Measured film')
            store=ProjectStore(library,restore=False)
            dialog=DesignMaterialsDialog(store)
            for i in range(dialog.items.count()):
                if 'Measured film' in dialog.items.item(i).text():
                    dialog.items.item(i).setCheckState(Qt.CheckState.Checked)
            dialog.apply()
            self.assertEqual(dialog.result(),1,dialog.status.text())
            options=dict(use_structure_patterns=True,bounds=[dialog.bound],trials=3,initial=2,half_window=20,step=5)
            _,job=prepare_job('target',store.portable_project(),options,library)
            material=next(m for m in job['model']['materials'] if m['name']=='MeasuredFilm')
            self.assertEqual(material['model'],'table_nk')
            self.assertEqual(len(material['table']),2)
            with self.assertRaisesRegex(ValueError,'must cover'):
                prepare_job('target',store.portable_project(),dict(options,half_window=100),library)
            dialog.close()


if __name__=='__main__': unittest.main()
