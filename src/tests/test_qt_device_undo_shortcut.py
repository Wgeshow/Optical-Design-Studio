"""Finite editors route Undo to their visible document, preserving text Undo."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton
from data_library import DataLibrary
from device_model import default_device
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace


class DeviceUndoShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='device-undo-')
        self.store = ProjectStore(DataLibrary(Path(self.temp.name) / 'library'), restore=False)
        self.store.activate_study('electrical')
        device = default_device(self.store.electrical_materials)
        device['layers'][0]['thickness_um'] = .0531
        self.store.set_device(device)
        self.store._undo.clear()
        self.guard = patch.object(self.store, 'start_run', side_effect=AssertionError('No solver/job permitted'))
        self.guard.start()
        self.page = SimulationSetupWorkspace(self.store, mode='electrical', document_id='electrical')
        self.page.resize(1350, 850); self.page.show(); self.page.activateWindow()
        self.app.processEvents()
        self.editor = self.page.setup_flow.device_editor.editor
        self.identity = self.store.device['layers'][0]['id']
        self.editor.select_object(self.identity)

    def tearDown(self):
        if hasattr(self.page, '_save_timer'): self.page._save_timer.stop()
        self.page.close(); self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.guard.stop(); self.temp.cleanup()

    def apply_thickness(self):
        self.editor.thickness_edit.setValue(.054)
        QTest.mouseClick(self.editor.apply_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.store.device['layers'][0]['thickness_um'], .054)
        self.assertEqual(len(self.store._undo), 1)
        self.editor.apply_button.setFocus(); self.app.processEvents()
        self.assertTrue(self.editor.apply_button.hasFocus())

    def test_ctrl_z_after_apply_restores_exact_thickness_in_electrical_document(self):
        before = copy.deepcopy(self.store.device)
        self.apply_thickness()
        QTest.keyClick(self.editor.apply_button, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertEqual(self.store.device, before)
        self.assertEqual(self.editor.thickness_edit.value(), .0531)
        self.assertEqual(len(self.store._undo), 0)

    def test_text_field_undo_keeps_applied_device_history(self):
        self.apply_thickness()
        name = self.editor.name_edit.text()
        self.editor.name_edit.setFocus()
        self.editor.name_edit.setCursorPosition(len(name))
        QTest.keyClicks(self.editor.name_edit, ' local draft')
        self.assertEqual(self.editor.name_edit.text(), name + ' local draft')
        QTest.keyClick(self.editor.name_edit, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.editor.name_edit.text(), name)
        self.assertEqual(self.store.device['layers'][0]['thickness_um'], .054)
        self.assertEqual(len(self.store._undo), 1)

    def test_numeric_field_undo_does_not_consume_applied_device_history(self):
        self.apply_thickness()
        control = self.editor.thickness_edit
        control.setFocus(); control.selectAll()
        QTest.keyClicks(control, '.055')
        QTest.keyClick(control, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.store.device['layers'][0]['thickness_um'], .054)
        self.assertEqual(len(self.store._undo), 1)

    def test_hidden_device_editor_does_not_undo_from_another_setup_stage(self):
        self.apply_thickness()
        self.page.setup_flow.show_stage(1)
        self.app.processEvents()
        self.assertFalse(self.editor.isVisible())
        control = next(widget for widget in self.page.findChildren(QPushButton) if widget.isVisible() and widget.isEnabled())
        control.setFocus(); self.app.processEvents()
        QTest.keyClick(control, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.store.device['layers'][0]['thickness_um'], .054)
        self.assertEqual(len(self.store._undo), 1)

    def test_menu_undo_and_shortcut_share_the_same_history(self):
        self.apply_thickness()
        self.editor.action_buttons['undo'].click()
        self.assertEqual(self.store.device['layers'][0]['thickness_um'], .0531)
        self.assertEqual(len(self.store._undo), 0)
        self.editor.apply_button.setFocus(); self.app.processEvents()
        QTest.keyClick(self.editor.apply_button, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.store.device['layers'][0]['thickness_um'], .0531)
        self.assertIn('no earlier', self.editor.status.text().lower())


if __name__ == '__main__':
    unittest.main()

