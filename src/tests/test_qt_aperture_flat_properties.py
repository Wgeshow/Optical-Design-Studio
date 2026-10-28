"""Scoped aperture workaround preserves the canonical typed draft without tree collapse."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit
from qt_research_studies import StructuredValueEditor

APP = QApplication.instance() or QApplication([])


class ApertureFlatPropertiesTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(APP.platformName(), 'offscreen')
        self.value = dict(load_anchors=[dict(id='source-a', voltage_V=1.2345678901234567,
                                           checks=dict(accepted=True, labels=['first', 'second'], optional=None)),
                                       dict(id='source-b', voltage_V=2.)],
                          load_domain=dict(width_um=200., layers=[dict(id='contact', thickness_nm=100.)]),
                          contacts=[dict(shape='ring', width_um=200., inner_width_um=160.)])
        self.editor = StructuredValueEditor(copy.deepcopy(self.value), 'aperture')
        self.form = self.editor.enable_flat_navigation()

    def tearDown(self):
        from PyQt6 import sip
        sip.delete(self.editor)
        APP.processEvents()

    def item(self, *names):
        item = self.editor.tree.topLevelItem(0)
        for name in names:
            item = item.child(name) if isinstance(name, int) else next(item.child(i) for i in range(item.childCount()) if item.child(i).text(0) == name)
        return item

    def open(self, *names):
        self.editor.open_item(self.item(*names))

    def test_every_nested_group_has_flat_navigation_and_exact_original_serialization(self):
        self.assertTrue(self.editor.tree.isHidden())
        self.assertFalse(self.editor.tree.itemsExpandable())
        self.assertGreater(self.form.groups.count(), 6)
        for path in list(self.form._paths):
            self.form.select_path(path)
            self.assertTrue(self.editor.tree.isHidden())
            self.assertEqual(self.editor.value(), self.value)
        self.open('load_anchors', 0, 'checks')
        self.assertIn('accepted', self.form._fields)
        self.assertFalse(self.form._fields['optional'].isEnabled())
        self.assertEqual(self.editor.value(), self.value)

    def test_numeric_draft_edits_survive_group_navigation_without_rebuilding_on_typing(self):
        self.open('load_anchors', 0)
        control = self.form._fields['voltage_V']
        control.setText('1e-')
        control.textEdited.emit('1e-')
        self.assertIs(self.form._fields['voltage_V'], control)
        with self.assertRaises(ValueError):
            self.editor.value()
        self.open('load_domain')
        self.open('load_anchors', 0)
        self.assertEqual(self.form._fields['voltage_V'].text(), '1e-')
        control = self.form._fields['voltage_V']
        control.setText('1.2345678901234567')
        control.textEdited.emit('1.2345678901234567')
        self.assertEqual(self.editor.value(), self.value)

    def test_add_each_supported_type_rename_remove_and_array_renumber(self):
        self.open('load_domain')
        for kind, expected in [('number', 0.), ('text', ''), ('boolean', False), ('object', {}), ('array', [])]:
            name = 'new_' + kind
            def accept(dialog, name=name, kind=kind):
                dialog.findChild(QLineEdit).setText(name)
                dialog.findChild(QComboBox).setCurrentText(kind)
                return QDialog.DialogCode.Accepted
            with patch('qt_research_studies.QDialog.exec', new=accept):
                self.form.add_child()
            self.assertEqual(self.editor.value()['load_domain'][name], expected)
            self.assertEqual(self.item('load_domain', name).data(0, Qt.ItemDataRole.UserRole), kind)
        path = self.form._item_path(self.item('load_domain', 'new_text'))
        self.assertTrue(self.form.rename_path(path, 'notes'))
        self.assertFalse(self.form.rename_path(path, 'width_um'))
        self.assertIn('notes', self.editor.value()['load_domain'])
        self.form.remove_path(self.form._item_path(self.item('load_anchors', 0)))
        self.assertEqual(self.editor.value()['load_anchors'], [self.value['load_anchors'][1]])
        self.assertEqual(self.item('load_anchors', 0).text(0), '0')

    def test_add_rejects_duplicate_and_blank_names_without_mutating_existing_draft(self):
        from PyQt6.QtWidgets import QDialogButtonBox
        self.open('load_domain')
        before = copy.deepcopy(self.editor.draft())
        for name in ('width_um', '  width_um  ', '   '):
            with self.subTest(name=name):
                def accept(dialog):
                    dialog.findChild(QLineEdit).setText(name)
                    self.assertFalse(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).isEnabled())
                    return QDialog.DialogCode.Accepted
                with patch('qt_research_studies.QDialog.exec', new=accept):
                    self.form.add_child()
                self.assertEqual(self.editor.draft(), before)
                self.assertTrue(self.form.note.text())
        path = self.form._item_path(self.item('load_domain', 'layers'))
        self.assertFalse(self.form.rename_path(path, ' width_um '))
        self.assertEqual(self.editor.draft(), before)

    def test_duplicate_warning_reserves_full_wrapped_height_in_small_dialog(self):
        from PyQt6.QtWidgets import QDialogButtonBox, QLabel
        self.open('load_domain')
        before = copy.deepcopy(self.editor.draft())
        def cancel(dialog):
            dialog.ensurePolished()
            dialog.resize(dialog.minimumWidth(), 100)
            dialog.findChild(QLineEdit).setText('width_um')
            dialog.layout().activate()
            warning = next(row for row in dialog.findChildren(QLabel) if 'already exists' in row.text())
            buttons = dialog.findChild(QDialogButtonBox)
            self.assertTrue(warning.wordWrap())
            self.assertGreaterEqual(dialog.width(), 440)
            self.assertGreaterEqual(warning.height(), warning.heightForWidth(warning.width()))
            self.assertGreater(buttons.geometry().top(), warning.geometry().bottom())
            self.assertFalse(buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
            return QDialog.DialogCode.Rejected
        with patch('qt_research_studies.QDialog.exec', new=cancel):
            self.form.add_child()
        self.assertEqual(self.editor.draft(), before)

    def test_import_restore_and_diagnostics_keep_flat_route_and_other_editors_unchanged(self):
        self.open('contacts', 0)
        draft = self.editor.draft()
        self.editor.set_value({'load_domain': {'width_um': 123.45678901234567}})
        self.assertEqual(self.editor.value()['load_domain']['width_um'], 123.45678901234567)
        self.editor.restore_draft(draft)
        self.editor.open_field('aperture.load_anchors.0.checks.accepted')
        self.assertIn('accepted', self.form._fields)
        self.assertTrue(self.editor.tree.isHidden())
        self.assertEqual(self.editor.value(), self.value)
        other = StructuredValueEditor({'ordinary': [1., 2.]}, 'other')
        try:
            self.assertFalse(hasattr(other, 'flat_form'))
            self.assertTrue(other.tree.itemsExpandable())
        finally:
            from PyQt6 import sip
            sip.delete(other)

    def test_workspace_nested_edit_button_routes_to_flat_form_without_changing_model(self):
        from data_library import DataLibrary
        from qt_core import ProjectStore
        from qt_pcsel_research_setup import PcselResearchWorkspace
        from research_catalog import list_capabilities
        with tempfile.TemporaryDirectory(prefix='aperture-flat-') as directory:
            store = ProjectStore(DataLibrary(Path(directory) / 'library'), restore=False)
            store.study_navigation_enabled = True
            store.activate_study('pcsel.aperture')
            capability = next(row for row in list_capabilities() if row['engine'] == 'pcsel')
            page = PcselResearchWorkspace(store, capability, document_id='pcsel.aperture')
            try:
                editor = page.structured['aperture']
                editor.set_value(copy.deepcopy(self.value))
                page._refresh_friendly()
                before = copy.deepcopy(page.draft())
                form, _ = page.aperture_journey_forms['calibration']
                form.controls['load_anchors'].click()
                self.assertTrue(editor.tree.isHidden())
                self.assertFalse(editor.tree.itemsExpandable())
                self.assertEqual(editor.flat_form.title.text(), 'Aperture / Load anchors')
                self.assertEqual(editor.value(), self.value)
                self.assertEqual(page.fields['model'].currentData(), 'aperture')
                self.assertEqual(page.draft()['structured'], before['structured'])
                section = page.sections['aperture_accuracy']
                page.tabs.setCurrentIndex(section)
                page._create_fields('aperture')
                self.assertEqual(page.tabs.currentIndex(), section)
                self.assertEqual(float(next(editor.tree.topLevelItem(0).child(i).text(1) for i in range(editor.tree.topLevelItem(0).childCount()) if editor.tree.topLevelItem(0).child(i).text(0) == 'temperature_tolerance_K')), .002)
                self.assertEqual(float(next(editor.tree.topLevelItem(0).child(i).text(1) for i in range(editor.tree.topLevelItem(0).childCount()) if editor.tree.topLevelItem(0).child(i).text(0) == 'maximum_iterations')), 120)
            finally:
                page._save_timer.stop()
                from PyQt6 import sip
                sip.delete(page)


if __name__ == '__main__':
    unittest.main()
