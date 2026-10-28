"""UI binding regression only; no Meep calculation or native acceptance."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from fdtd_model import build_job
from qt_core import ProjectStore
from qt_fdtd import FDTDPage
from qt_optical_journey import install_optical_journey


class FDTDExteriorEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fdtd-exterior-')
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.store.study_navigation_enabled = True
        self.store.activate_study('fdtd')
        materials = self.store.materials.copy(deep=True)
        for name, n in [('FDTD test air', 1.), ('FDTD test glass', 1.7)]:
            materials.loc[len(materials)] = dict(Name=name, Model='constant_nk', A=n, B=0., DataFile='', WavelengthUnit='nm')
        self.store.set_structure(materials, self.store.layers, self.store.patterns)
        self.page = FDTDPage(self.store)
        install_optical_journey(self.page, self.store, 'fdtd')
        self.page.resize(1300, 850)
        self.page.show()
        self.app.processEvents()
        self.guard = patch.object(self.store, 'start_run', side_effect=AssertionError('No solver permitted'))
        self.guard.start()

    def tearDown(self):
        sip.delete(self.page)
        self.guard.stop()
        self.temp.cleanup()

    def choose(self, side, name):
        control = self.page.exterior_controls[side]
        self.assertTrue(control.isVisible())
        index = control.findData(name)
        self.assertGreaterEqual(index, 0)
        control.setCurrentIndex(index)
        self.app.processEvents()

    def test_visible_selectors_reach_real_job_and_undo_without_other_changes(self):
        before = copy.deepcopy(self.store.study_project('fdtd'))
        self.choose('incident', 'FDTD test air')
        self.choose('exit', 'FDTD test glass')
        expected = copy.deepcopy(before)
        expected['layers'][0]['Material'] = 'FDTD test air'
        expected['layers'][-1]['Material'] = 'FDTD test glass'
        self.assertEqual(self.store.study_project('fdtd'), expected)
        job = build_job(self.store.portable_project(), {}, self.page.options())
        self.assertEqual(job['incident'], 'FDTD test air')
        self.assertEqual(job['exit'], 'FDTD test glass')
        self.store.undo()
        self.store.undo()
        self.assertEqual(self.store.study_project('fdtd'), before)
        self.assertEqual(self.page.exterior_controls['exit'].currentData(), before['layers'][-1]['Material'])

    def test_inactive_study_and_busy_controls_cannot_mutate_other_work(self):
        self.choose('exit', 'FDTD test air')
        fdtd = copy.deepcopy(self.store.study_project('fdtd'))
        self.store.activate_study('thermal')
        thermal = copy.deepcopy(self.store.project())
        control = self.page.exterior_controls['exit']
        control.setCurrentIndex(control.findData('FDTD test glass'))
        self.assertEqual(self.store.project(), thermal)
        self.store.activate_study('fdtd')
        for key in ('device', 'layers', 'patterns', 'materials', 'settings'):
            self.assertEqual(self.store.study_project('fdtd')[key], fdtd[key])
        self.assertEqual(control.currentData(), 'FDTD test air')
        with patch.object(self.store, 'busy', True):
            self.page._busy(True)
            self.assertFalse(self.page.exterior_group.isEnabled())
            control.setCurrentIndex(control.findData('FDTD test glass'))
            self.assertEqual(self.store.layers.iloc[-1]['Material'], 'FDTD test air')

    def test_failed_save_reverts_selection_and_state(self):
        before = copy.deepcopy(self.store.project())
        previous = self.page.exterior_controls['exit'].currentData()
        with patch.object(self.store, '_autosave', side_effect=OSError('synthetic save failure')):
            self.choose('exit', 'FDTD test glass')
        self.assertEqual(self.store.project(), before)
        self.assertEqual(self.page.exterior_controls['exit'].currentData(), previous)
        self.assertIn('synthetic save failure', self.page.status.text())


if __name__ == '__main__':
    unittest.main()
