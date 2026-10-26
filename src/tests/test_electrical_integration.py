"""Electrical project persistence and native job routing contracts."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from model import epsilon
from qt_core import ProjectStore, prepare_job


class ElectricalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_preset_roundtrip_embeds_optics_and_keeps_shared_performance(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProjectStore(DataLibrary(folder),restore=False)
            store.update_performance(dict(workers=2,threads=1))
            perf=copy.deepcopy(store.performance)
            store.load_electrical_preset()
            self.assertEqual(store.performance,perf)
            saved=store.portable_project()
            self.assertEqual(saved['desktop_search']['electrical']['ito_thickness_nm'],40.)
            self.assertEqual(len(saved['optical_constants']),6)
            with tempfile.TemporaryDirectory() as elsewhere:
                restored=ProjectStore(DataLibrary(elsewhere),restore=False)
                restored.load_project(saved)
                self.assertEqual(restored.search_state,store.search_state)
                self.assertTrue(all(Path(file).is_file() for file in restored.files))
                cfg=copy.deepcopy(restored.search_state['electrical'])
                cfg['optical_enabled']=True
                _,job=prepare_job('electrical',restored.project(),cfg,restored.library)
                self.assertEqual(job['search']['task'],'electrical')
                self.assertEqual(job['performance']['solver_backend'],'native')

    def test_dc_only_can_run_with_an_incomplete_optical_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProjectStore(DataLibrary(folder),restore=False)
            project=store.project()
            project['materials'][1].update(Model='table_nk',DataFile='missing.csv')
            _,job=prepare_job('electrical',project,dict(optical_enabled=False),store.library)
            self.assertIsNone(job['model'])
            self.assertEqual(job['search']['task'],'electrical')

    def test_electrical_tab_uses_the_shared_run_and_preserves_saved_tab_index(self):
        from qt_app import OpticalStudio
        with tempfile.TemporaryDirectory() as folder:
            store=ProjectStore(DataLibrary(folder),restore=False)
            window=OpticalStudio(store)
            try:
                self.assertEqual(window.simulation_engines.tabText(4),'Saved results')
                self.assertEqual(window.simulation_engines.tabText(5),'Electrical')
                window._navigate_route(2,5)
                self.app.processEvents()
                self.assertTrue(window.run_button.isEnabled())
                with patch.object(window.electrical_page,'run') as run:
                    window.run_button.click()
                    run.assert_called_once_with()
                window._navigate_route(2,4)
                self.assertFalse(window.run_button.isEnabled())
            finally:
                window.close()
                self.app.processEvents()


class OpticalTensorTests(unittest.TestCase):
    def material(self):
        matrix=lambda value:[[[value,0.],[.1,0.],[0.,0.]],[[.1,0.],[value,0.],[0.,0.]],[[0.,0.],[0.,0.],[value+1,0.]]]
        return dict(model='table_nk',grid=[1100.,1200.],epsilon_tensor=[matrix(10.),matrix(12.)])

    def test_tensor_interpolation_and_endpoint_clamping(self):
        material=self.material()
        self.assertEqual(epsilon(material,1150.)[0][0],11+0j)
        self.assertEqual(epsilon(material,1000.)[2][2],11+0j)
        self.assertEqual(epsilon(material,1300.)[2][2],13+0j)
        self.assertEqual(epsilon(material,1150.)[0][1],.1+0j)

    def test_unsupported_off_plane_terms_are_rejected_before_native_solve(self):
        material=self.material();material['epsilon_tensor'][0][0][2]=[.01,0.]
        with self.assertRaisesRegex(ValueError,'off-plane'):
            epsilon(material,1150.)


if __name__=='__main__':
    unittest.main()
