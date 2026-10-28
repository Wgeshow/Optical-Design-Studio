"""Offscreen halfspace assignment regression; no solver or acceptance run."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QComboBox
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace


class OpticalExteriorEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='optical-exterior-')
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.store.study_navigation_enabled = True
        self.store.activate_study('optical')
        # Explicit test materials; these are fixture setup, not UI acceptance.
        materials = self.store.materials.copy(deep=True)
        for name, n in [('Manual air test', 1.), ('Manual glass test', 1.7)]:
            materials.loc[len(materials)] = dict(Name=name, Model='constant_nk', A=n, B=0., DataFile='', WavelengthUnit='nm')
        self.store.set_structure(materials, self.store.layers, self.store.patterns)
        self.page = SimulationSetupWorkspace(self.store, mode='optical', document_id='optical')
        self.page.resize(1300, 850); self.page.show()
        self.page.select_section('optical.incident'); self.app.processEvents()
        self.guard = patch.object(self.store, 'start_run', side_effect=AssertionError('No solver permitted'))
        self.guard.start()

    def tearDown(self):
        sip.delete(self.page)
        self.guard.stop()
        self.temp.cleanup()

    def choose(self, side, material):
        key = 'ui.optical.'+side+'_material'
        editor = self.page.widgets_by_key[key][0]
        self.assertIsInstance(editor, QComboBox)
        self.assertTrue(editor.isVisible())
        index = editor.findData(material)
        self.assertGreaterEqual(index, 0)
        editor.setCurrentIndex(index); self.app.processEvents()
        return editor

    def test_visible_selectors_change_real_halfspaces_without_geometry_or_settings_changes(self):
        before = copy.deepcopy(self.store.study_project('optical'))
        history = len(self.store._undo)
        self.choose('incident', 'Manual air test')
        self.choose('exit', 'Manual glass test')
        after = self.store.study_project('optical')
        expected = copy.deepcopy(before)
        expected['layers'][0]['Material'] = 'Manual air test'
        expected['layers'][-1]['Material'] = 'Manual glass test'
        self.assertEqual(after, expected)
        self.assertEqual(len(self.store._undo), history+2)
        model = self.page.state._prepared_model()
        self.assertEqual(model['layers'][0]['material'], 'Manual air test')
        self.assertEqual(model['layers'][-1]['material'], 'Manual glass test')
        self.store.undo(); self.store.undo()
        self.assertEqual(self.store.study_project('optical'), before)
        self.assertEqual(len(self.store._undo), history)

    def test_noop_invalid_material_and_save_failure_preserve_state_and_history(self):
        before = copy.deepcopy(self.store.project())
        history = len(self.store._undo)
        self.store.set_optical_exterior_material('incident', before['layers'][0]['Material'])
        with self.assertRaises(ValueError):
            self.page.state.set('ui.optical.exit_material', 'Absent material')
        with self.assertRaises(ValueError):
            self.store.set_optical_exterior_material('finite', 'Manual air test')
        with patch.object(self.store, '_autosave', side_effect=OSError('synthetic save failure')):
            with self.assertRaises(OSError):
                self.store.set_optical_exterior_material('exit', 'Manual glass test')
        self.assertEqual(self.store.project(), before)
        self.assertEqual(len(self.store._undo), history)

    def test_material_choice_is_study_owned_and_old_page_cannot_edit_another_study(self):
        self.choose('exit', 'Manual air test')
        optical = copy.deepcopy(self.store.study_project('optical'))
        self.store.activate_study('thermal')
        thermal = copy.deepcopy(self.store.project())
        editor = self.page.widgets_by_key['ui.optical.exit_material'][0]
        editor.setCurrentIndex(editor.findData('Manual glass test')); self.app.processEvents()
        self.assertEqual(self.store.project(), thermal)
        self.store.activate_study('optical'); self.app.processEvents()
        restored = self.store.study_project('optical')
        for key in ('device', 'layers', 'patterns', 'materials', 'settings'):
            self.assertEqual(restored[key], optical[key], key)
        self.assertEqual(editor.currentData(), 'Manual air test')


if __name__ == '__main__':
    unittest.main()
