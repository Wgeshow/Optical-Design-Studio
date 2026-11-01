"""UI binding regression only; no Meep calculation or native acceptance."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel
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

    def test_journey_monitor_decay_label_and_tooltip_retain_options(self):
        before = copy.deepcopy(self.page.options())
        self.page.optical_journey.select_stage('stopping')
        labels = [label.text() for label in self.page.findChildren(QLabel)]
        self.assertIn('Monitor field decay target', labels)
        self.assertNotIn('Field energy decay target', labels)
        self.assertIn('20 µm/c', self.page.controls['decay_by'].toolTip())
        self.assertEqual(self.page.options(), before)

    def test_journey_live_grid_summary_is_read_only_and_uses_current_tables(self):
        before = copy.deepcopy(self.store.project())
        with patch('fdtd_model.build_job', side_effect=AssertionError('No job preparation')), \
             patch('fdtd_model.convert_material', side_effect=AssertionError('No material fit')), \
             patch.object(self.store, 'save_search', return_value=None), \
             patch.object(self.store.library, 'snapshot', side_effect=AssertionError('No file snapshot')), \
             patch('meep_runtime.probe', side_effect=AssertionError('No runtime probe')):
            self.store.settings.update(ax_um=2.94, ay_um=2.94)
            self.store.layers = self.store.layers.iloc[:3].copy()
            self.store.layers.loc[:, 'Thickness_um'] = [0., .2695, 0.]
            self.page.controls['dimensions'].setCurrentIndex(1)
            self.page.controls['resolution'].setValue(40)
            self.page.optical_journey.select_stage('checks')
            self.app.processEvents()
            label = self.page.journey_grid_summary
            self.assertTrue(label.isVisible())
            self.assertIn('117.6 cells → 118', label.text())
            self.assertIn('approximately 2.95 µm', label.text())
            self.assertIn('noninteger lateral cell sizes', label.text())
            self.assertIn('does not establish convergence', label.text())
            self.page.controls['resolution'].setValue(40.81632653)
            self.app.processEvents()
            self.assertNotIn('noninteger lateral cell sizes', label.text())
            self.assertIn('align with the grid', label.text())
            self.store.settings['ax_um'] = 3.01
            self.store.changed.emit('geometry')
            self.app.processEvents()
            self.assertIn('noninteger lateral cell sizes', label.text())
            self.assertEqual(self.store.settings['ax_um'], 3.01)
            self.assertEqual(self.page.controls['resolution'].value(), 40.81632653)
        after = self.store.project()
        for key in ('materials', 'patterns', 'device', 'electrical_materials'):
            self.assertEqual(after[key], before[key])


    def test_journey_fractional_resolution_entry_persistence_restore_and_job(self):
        before = copy.deepcopy(self.page.options())
        self.page.optical_journey.select_stage('structure')
        self.app.processEvents()
        control = self.page.controls['resolution']
        self.assertTrue(control.isVisible())
        self.assertEqual(control.decimals(), 8)
        value = '40.81632653'
        control.setFocus()
        control.selectAll()
        QTest.keyClicks(control, value)
        QTest.keyClick(control, Qt.Key.Key_Enter)
        self.app.processEvents()
        entered = float(value)
        self.assertEqual(control.value(), entered)
        self.assertAlmostEqual(.49*entered, 20, places=8)
        self.assertEqual(self.store.search_state['fdtd']['resolution'], entered)
        job = build_job(self.store.portable_project(), {}, self.page.options())
        self.assertEqual(job['options']['resolution'], entered)
        self.assertEqual(self.page.options(), dict(before, resolution=entered))
        self.page._restore()
        self.assertEqual(control.value(), entered)
        control.setValue(40)
        self.app.processEvents()
        self.assertIsInstance(self.page.options()['resolution'], int)
        self.assertEqual(self.page.options()['resolution'], 40)

    def test_journey_integrated_source_visible_click_saved_job_and_check_review(self):
        before = copy.deepcopy(self.page.options())
        self.page.optical_journey.select_stage('parameters')
        self.app.processEvents()
        control = self.page.controls['source_is_integrated']
        self.assertTrue(control.isVisible())
        self.assertTrue(control.isEnabled())
        self.assertTrue(self.page.optical_journey.stack.currentWidget().isAncestorOf(control))
        self.assertFalse(control.isChecked())
        previous_generation = self.page._estimate_generation
        QTest.mouseClick(control, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(control.isChecked())
        self.assertGreater(self.page._estimate_generation, previous_generation)
        self.assertTrue(self.store.search_state['fdtd']['source_is_integrated'])
        expected = dict(before, source_is_integrated=True)
        self.assertEqual(self.page.options(), expected)
        self.page.optical_journey.select_stage('checks')
        self.app.processEvents()
        self.assertTrue(self.page.journey_source_summary.isVisible())
        self.assertIn('integrated polarization (on)', self.page.journey_source_summary.text())
        self.page.check_journey_inputs()
        self.assertIn('Input preparation passed', self.page.journey_check_state.text())
        job = build_job(self.store.portable_project(), {}, self.page.options())
        self.assertTrue(job['options']['source_is_integrated'])
        self.page.optical_journey.select_stage('parameters')
        self.app.processEvents()
        QTest.mouseClick(control, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertFalse(self.store.search_state['fdtd']['source_is_integrated'])
        self.assertEqual(self.page.options(), before)
        self.assertIn('current (integration off)', self.page.journey_source_summary.text())
        self.assertIn('Inputs changed', self.page.journey_check_state.text())

    def test_runtime_estimate_controls_are_on_visible_run_stage(self):
        self.page.optical_journey.select_stage('run')
        self.app.processEvents()
        self.assertTrue(self.page.estimate_button.isVisible())
        self.assertTrue(self.page.timing_status.isVisible())
        self.page._active = True
        self.page._run_started = 100.
        with patch('qt_fdtd.time.monotonic', return_value=105.):
            self.page._update_timing()
        self.assertIn('elapsed 5s', self.page.timing_status.text())
        self.page._active = False

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
