"""Explicit geometry imports refresh inspectors; ordinary navigation retains drafts."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QWidget
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_study_device_editor import StudyDeviceEditor


class OwnedEditorReplacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        assert cls.app.platformName() == 'offscreen'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='owned-editor-')
        self.store = ProjectStore(DataLibrary(Path(self.temp.name) / 'library'), restore=False)
        self.store.study_navigation_enabled = True
        self.store.activate_study('electrical')
        self.guard = patch.object(self.store, 'start_run', side_effect=AssertionError('No solver/job permitted'))
        self.guard.start()
        self.owner = QWidget()
        self.owner.store = self.store
        self.owner._bound_study_id = 'electrical'
        self.host = StudyDeviceEditor(self.owner, include_advanced=True)
        self.host.open_editor()
        self.editor = self.host.editor
        self.identity = self.store.device['layers'][0]['id']
        self.editor.select_object(self.identity)

    def tearDown(self):
        sip.delete(self.owner)
        self.guard.stop()
        self.temp.cleanup()

    def replacement(self):
        project = copy.deepcopy(self.store.study_project('electrical'))
        project['device']['layers'][0].update(name='Imported replacement', material_id='silicon', thickness_um=2 / 3)
        return project

    def assert_replacement_is_shown(self):
        self.assertEqual(self.editor.selected_id, self.identity)
        self.assertEqual(self.editor.name_edit.text(), 'Imported replacement')
        self.assertEqual(self.editor.material_edit.currentData(), 'silicon')
        self.assertAlmostEqual(self.editor.thickness_edit.value(), 2 / 3, places=6)
        before = copy.deepcopy(self.store.device)
        self.assertTrue(self.editor.apply_inspector())
        self.assertEqual(self.store.device, before)

    def test_same_document_import_updates_selected_inspector_before_apply(self):
        self.store.replace_active_study(self.replacement())
        self.assert_replacement_is_shown()

    def test_explicit_transfer_updates_selected_inspector_and_preserves_source(self):
        project = self.replacement()
        self.store.activate_study('thermal')
        self.store.replace_active_study(project)
        self.store.activate_study('electrical')
        source = copy.deepcopy(self.store.study_project('thermal'))
        self.store.transfer_study_inputs('thermal')
        self.assert_replacement_is_shown()
        self.assertEqual(self.store.study_project('thermal'), source)

    def test_normal_switch_away_and_return_retains_unfinished_draft_and_selection(self):
        self.editor.donor_edit.setText('2.5e-')
        before = copy.deepcopy(self.store.device)
        self.store.activate_study('electrical.cv')
        other = copy.deepcopy(self.store.device)
        other['layers'][0]['name'] = 'Different CV layer'
        self.store.set_device(other)
        self.assertEqual(self.editor.donor_edit.text(), '2.5e-')
        self.store.activate_study('electrical')
        self.assertEqual(self.editor.selected_id, self.identity)
        self.assertEqual(self.editor.donor_edit.text(), '2.5e-')
        self.assertEqual(self.store.device, before)

    def test_periodic_editor_refreshes_after_replacement_but_not_unchanged_return(self):
        legacy = self.editor._legacy
        with patch.object(legacy, 'refresh', wraps=legacy.refresh) as refresh:
            self.store.replace_active_study(self.replacement())
            refresh.assert_called_once_with('project')
            refresh.reset_mock()
            self.store.activate_study('thermal')
            self.store.activate_study('electrical')
            refresh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
