"""Authored layer repetition only; no native acceptance or physics solves."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QSpinBox
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel_research_setup import PcselResearchWorkspace
from research_catalog import list_capabilities

APP = QApplication.instance() or QApplication([])


class RepeatLayersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='repeat-layers-', dir=Path.cwd())
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        cap = next(row for row in list_capabilities() if row['engine'] == 'pcsel')
        self.page = PcselResearchWorkspace(self.store, cap)
        self.editor = self.page.geometry_editor
        layers = [dict(id=name, name=name, thickness_nm=thickness, index=3.,
                       qw=name == 'A', patterned=name == 'B')
                  for name, thickness in [('cap', 220.), ('A', 79.), ('B', 90.), ('base', 350.)]]
        self.page.structured['layers'].set_value(layers)
        self.page.structured['layers'].changed.emit()
        self.editor.select_object('layers', 'A')
        self.editor.history.reset()

    def tearDown(self):
        self.page._save_timer.stop()
        self.page.close(); self.page.deleteLater(); APP.processEvents()
        self.temp.cleanup()

    def draft(self):
        return deepcopy(self.page.structured['layers'].draft())

    def test_pair_expansion_order_fresh_ids_original_selection_and_one_undo(self):
        before = self.draft()
        self.assertTrue(self.editor.repeat_layer_block(2, 13))
        after = self.draft()
        layers = self.page.structured['layers'].value()
        self.assertEqual(len(layers), 30)  # 2 originals + 26 copies + cap/base
        self.assertEqual([row['thickness_nm'] for row in layers], [220.] + [79., 90.]*14 + [350.])
        self.assertEqual(len({row['id'] for row in layers}), 30)
        self.assertEqual(layers[0]['id'], 'cap'); self.assertEqual(layers[-1]['id'], 'base')
        self.assertTrue(all(row['qw'] and not row['patterned'] for row in layers[1:-1:2]))
        self.assertTrue(all(row['patterned'] and not row['qw'] for row in layers[2:-1:2]))
        self.assertEqual(self.editor.current_id, 'A')
        self.assertTrue(self.editor.history.undo())
        self.assertEqual(self.draft(), before)
        self.assertFalse(self.editor.history.can_undo)
        self.assertTrue(self.editor.history.redo())
        self.assertEqual(self.draft(), after)

    def test_incomplete_numbers_and_extra_properties_are_preserved_losslessly(self):
        root = self.page.structured['layers'].tree.topLevelItem(0)
        row = root.child(1)
        for i in range(row.childCount()):
            if row.child(i).text(0) == 'thickness_nm': row.child(i).setText(1, '7e-')
        self.page.structured['layers']._append(row, 'source_note', {'condition': 'Keep this draft'})
        before = self.draft()
        self.assertTrue(self.editor.repeat_layer_block(2, 1))
        added = self.draft()['children'][3:5]
        for original, clone in zip(before['children'][1:3], added):
            expected = [item for item in original['children'] if item['name'] not in ('id', 'name')]
            actual = [item for item in clone['children'] if item['name'] not in ('id', 'name')]
            self.assertEqual(actual, expected)

    def test_invalid_bounds_and_wrong_group_do_not_mutate_or_record_history(self):
        before = self.draft()
        for count, copies in ((0, 1), (5, 1), (1, 0), (2, 1001), (2, True), (1.5, 1)):
            self.assertFalse(self.editor.repeat_layer_block(count, copies))
            self.assertEqual(self.draft(), before)
        self.editor.group.setCurrentIndex(self.editor.group.findData('shapes'))
        self.assertTrue(self.editor.repeat_layers_button.isHidden())
        self.assertFalse(self.editor.repeat_layer_block(1, 1))
        self.assertEqual(self.draft(), before)
        self.assertFalse(self.editor.history.can_undo)

    def test_dialog_previews_additional_copies_and_cancel_is_noop(self):
        before = self.draft(); observed = []
        def cancel():
            dialog = APP.activeModalWidget()
            observed.append(isinstance(dialog, QDialog))
            controls = {widget.accessibleName(): widget for widget in dialog.findChildren(QSpinBox)}
            observed.append(controls['Layers in block'].value() == 1 and controls['Additional copies'].value() == 1)
            controls['Layers in block'].setValue(2)
            controls['Additional copies'].setValue(13)
            text = '\n'.join(widget.text() for widget in dialog.findChildren(QLabel))
            observed.append('2 layers × 13 additional copies = 26 added layers.' in text)
            observed.append('A → B' in text)
            observed.append('Expanded block: 28 layers including the original block.' in text)
            dialog.reject()
        QTimer.singleShot(0, cancel)
        self.editor.repeat_layer_dialog()
        self.assertEqual(observed, [True, True, True, True, True])
        self.assertEqual(self.draft(), before)
        self.assertFalse(self.editor.history.can_undo)

    def test_dialog_apply_uses_actual_controls(self):
        def apply():
            dialog = APP.activeModalWidget()
            controls = {widget.accessibleName(): widget for widget in dialog.findChildren(QSpinBox)}
            controls['Layers in block'].setValue(2)
            controls['Additional copies'].setValue(2)
            dialog.accept()
        QTimer.singleShot(0, apply)
        self.editor.repeat_layer_dialog()
        self.assertEqual(len(self.page.structured['layers'].value()), 8)
        self.assertTrue(self.editor.history.undo())
        self.assertEqual(len(self.page.structured['layers'].value()), 4)


if __name__ == '__main__':
    unittest.main()
