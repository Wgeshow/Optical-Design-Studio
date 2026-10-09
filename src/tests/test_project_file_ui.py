"""Portable-project file controls and replacement safety."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
_imports=tempfile.TemporaryDirectory(prefix='s4_file_import_')
os.environ.setdefault('S4_LIBRARY_ROOT',_imports.name)

from PyQt6.QtWidgets import QApplication, QMessageBox, QToolButton
from qt_app import OpticalStudio
from qt_core import ProjectStore
from data_library import DataLibrary, read_json


class ProjectFileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.window=OpticalStudio(self.store)
        self.old_directory=self.window.preferences.value('project_directory')

    def tearDown(self):
        self.window.file_state_timer.stop()
        if self.old_directory is None:
            self.window.preferences.remove('project_directory')
        else:
            self.window.preferences.setValue('project_directory',self.old_directory)
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_save_reuses_file_save_as_changes_identity_and_open_restores_settings(self):
        first=Path(self.temp.name).resolve()/'device.json'
        second=Path(self.temp.name).resolve()/'device copy.json'
        self.store.update_settings({'wl_start_nm':1400})
        with patch('qt_app.QFileDialog.getSaveFileName',return_value=(str(first),'JSON')) as dialog:
            self.assertTrue(self.window.save_project())
            dialog.assert_called_once()
        self.store.update_settings({'wl_start_nm':1450})
        self.window._refresh_project_file()
        self.assertIn('*',self.window.project_select.text())
        with patch('qt_app.QFileDialog.getSaveFileName') as dialog:
            self.assertTrue(self.window.save_project())
            dialog.assert_not_called()
        self.assertEqual(read_json(first)['settings']['wl_start_nm'],1450)
        with patch('qt_app.QFileDialog.getSaveFileName',return_value=(str(second.with_suffix('')),'JSON')):
            self.assertTrue(self.window.save_project_as())
        self.assertEqual(self.window.project_path,second)
        self.store.update_settings({'wl_start_nm':1500})
        with patch('qt_app.QFileDialog.getOpenFileName',return_value=(str(first),'JSON')), patch('qt_app.QMessageBox.question',return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.window.open_project())
        self.assertEqual(self.store.settings['wl_start_nm'],1450)
        self.assertEqual(self.window.project_path,first)
        self.assertNotIn('*',self.window.project_select.text())
        self.assertIn(str(first),self.window.project_select.toolTip())
        self.store.load_project(self.store.project())
        self.assertIsNone(self.window.project_path,'A library/preset replacement must not overwrite the previous file')

    def test_cancel_or_failed_save_does_not_replace_project(self):
        self.store.update_settings({'wl_start_nm':1411})
        with patch('qt_app.QMessageBox.question',return_value=QMessageBox.StandardButton.Cancel):
            self.window._start_new_design()
        self.assertEqual(self.store.settings['wl_start_nm'],1411)
        with patch('qt_app.QMessageBox.question',return_value=QMessageBox.StandardButton.Save), patch('qt_app.QFileDialog.getSaveFileName',return_value=('','')):
            self.window._start_new_design()
        self.assertEqual(self.store.settings['wl_start_nm'],1411)
        with patch.object(self.store,'save_project',side_effect=OSError('Access denied')):
            self.assertFalse(self.window._save_project_to(Path(self.temp.name)/'blocked.json'))
        self.assertIsNone(self.window.project_path)
        self.assertIn('Save as',self.window.status.text())

    def test_new_project_and_wide_narrow_actions(self):
        self.store.update_settings({'wl_start_nm':1411})
        with patch('qt_app.QMessageBox.question',return_value=QMessageBox.StandardButton.Discard):
            self.window._start_new_design()
        self.assertNotEqual(self.store.settings['wl_start_nm'],1411)
        self.assertIsNone(self.window.project_path)
        self.window.resize(1460,900)
        self.window.show()
        self.window.adapt_interface()
        self.assertTrue(self.window.chrome.file_button.isVisible())
        self.assertTrue(self.window.project_header.isVisible())
        self.assertIsNone(self.window.findChild(QToolButton,'headerOpenProject'))
        self.assertFalse(self.window.chrome.view_button.isVisible())
        labels={action.text() for action in self.window.chrome.file_menu.actions()}
        self.assertTrue({'New project','Open project…','Save project','Save project as…','Export geometry…','Appearance','Settings','Help'}.issubset(labels))
        self.window.resize(640,600)
        self.window.adapt_interface()
        self.assertTrue(self.window.chrome.file_button.isVisible())
        self.assertTrue(self.window.project_header.isVisible())
        self.assertFalse(self.window.chrome.view_button.isVisible())
        self.assertIn(self.window.save_as_action,self.window.chrome.file_menu.actions())


if __name__=='__main__':
    unittest.main()
