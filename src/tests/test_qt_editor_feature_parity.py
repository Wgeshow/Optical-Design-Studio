"""Full native editor access, scoped drafts, and solver-specific stage ownership."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from device_model import default_device
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace
from qt_optical_journey import install_optical_journey

APP = QApplication.instance() or QApplication([])


class EditorFeatureParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods-editor-parity-', dir=Path.cwd())
        self.store = ProjectStore(DataLibrary(Path(self.temp.name) / 'library'), restore=False)
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            if hasattr(page, '_save_timer'):
                page._save_timer.stop()
            page.close(); page.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def finite(self, identity='electrical'):
        self.store.activate_study(identity)
        self.store.set_device(default_device(self.store.electrical_materials))
        page = SimulationSetupWorkspace(self.store, mode='electrical', document_id=identity)
        self.pages.append(page)
        page.resize(1350, 850); page.show(); APP.processEvents()
        return page

    def optical(self, route):
        if route == 'fdtd':
            from qt_fdtd import FDTDPage
            cls = FDTDPage
        else:
            from qt_index_shift import IndexShiftPage
            cls = IndexShiftPage
        self.store.activate_study(route)
        self.store.set_device(default_device(self.store.electrical_materials))
        page = cls(self.store); self.pages.append(page)
        host = install_optical_journey(page, self.store, route)
        page.resize(860, 800); page.show(); APP.processEvents()
        return page, host

    def test_device_stage_opens_complete_native_editor_and_reuses_action_menus(self):
        page = self.finite(); flow = page.setup_flow
        editor = flow.device_editor.editor
        self.assertIs(flow.views.currentWidget(), flow.device_editor)
        self.assertEqual(flow.journey_bar._current, 0)
        self.assertIs(flow.device_editor.menu_buttons['objects'].menu(), editor.tree_actions)
        self.assertIs(flow.device_editor.menu_buttons['drawing'].menu(), editor.toolbar_menu)
        self.assertIs(flow.device_editor.menu_buttons['export'].menu(), editor.export_menu)
        self.assertIn('undo', editor.action_buttons)
        self.assertIn('polygon', editor.tool_buttons)
        self.assertIsNotNone(editor.array_button)
        self.assertIsNotNone(editor.pc_area_button)
        self.assertIsNotNone(editor.library_import_button)
        self.assertIsNone(editor._legacy)
        flow.device_editor.back_button.click(); APP.processEvents()
        self.assertIsNot(flow.views.currentWidget(), flow.device_editor)
        self.assertEqual(flow.journey_bar._current, 0)
        self.assertTrue(page.center.isVisible())
        flow.show_stage(0)
        self.assertIs(flow.views.currentWidget(), flow.device_editor)
        page.select_section('electrical.overview')
        self.assertIs(flow.views.currentWidget(), flow.device_editor)

    def test_navigation_preserves_exact_unapplied_draft_and_runs_nothing(self):
        page = self.finite(); flow = page.setup_flow
        identity = self.store.device['layers'][0]['id']
        flow.open_device_editor(identity)
        editor = flow.device_editor.editor
        editor.donor_edit.setText('1e-')
        previous = copy.deepcopy(self.store.device)
        with patch.object(self.store, 'start_run') as run:
            flow.show_stage(1); flow.show_stage(0)
            self.assertEqual(editor.selected_id, identity)
            self.assertEqual(editor.donor_edit.text(), '1e-')
            self.assertEqual(self.store.device, previous)
            run.assert_not_called()

    def test_top_object_actions_add_once_and_apply_to_owned_study(self):
        page = self.finite(); host = page.setup_flow.device_editor; editor = host.editor
        before = len(self.store.device['layers'])
        with patch.object(self.store, 'start_run') as run:
            host.add_object_actions['add_layer'].trigger(); APP.processEvents()
            self.assertEqual(len(self.store.device['layers']), before + 1)
            identity = editor.selected_id
            editor.name_edit.setText('Manually added through Objects')
            editor.thickness_edit.setValue(1.25)
            self.assertIs(editor.apply_button.parentWidget(), host.actions)
            for width in (860, 1350):
                page.resize(width, 850); APP.processEvents()
                self.assertTrue(editor.apply_button.isVisible())
                self.assertLess(editor.apply_button.mapTo(host, editor.apply_button.rect().topLeft()).y(), 100)
            editor.apply_button.click(); APP.processEvents()
            layer = next(row for row in self.store.device['layers'] if row['id'] == identity)
            self.assertEqual(layer['name'], 'Manually added through Objects')
            self.assertEqual(layer['thickness_um'], 1.25)
            editor.apply_button.setFocus()
            QTest.keyClick(editor.apply_button, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            APP.processEvents()
            layer = next(row for row in self.store.device['layers'] if row['id'] == identity)
            self.assertNotEqual(layer['name'], 'Manually added through Objects')
            run.assert_not_called()

    def test_other_study_changes_do_not_replace_owned_inspector(self):
        page = self.finite(); flow = page.setup_flow
        identity = self.store.device['layers'][0]['id']
        flow.open_device_editor(identity)
        editor = flow.device_editor.editor
        editor.donor_edit.setText('2.5e-')
        self.store.activate_study('electrical.cv')
        self.store.set_device(default_device(self.store.electrical_materials))
        self.assertFalse(flow.device_editor.isEnabled())
        self.assertEqual(editor.donor_edit.text(), '2.5e-')
        self.store.activate_study('electrical'); APP.processEvents()
        self.assertTrue(flow.device_editor.isEnabled())
        self.assertEqual(editor.selected_id, identity)
        self.assertEqual(editor.donor_edit.text(), '2.5e-')

    def test_compact_panes_reuse_drafts_and_give_geometry_and_properties_the_space(self):
        page = self.finite(); page.resize(860, 720); APP.processEvents()
        host = page.setup_flow.device_editor; editor = host.editor
        host.pane_tabs.setCurrentIndex(1); APP.processEvents()
        self.assertTrue(host._compact_editor)
        self.assertTrue(editor.canvas_panel.isVisible())
        self.assertFalse(editor.tree_panel.isVisible())
        self.assertFalse(editor.inspector_panel.isVisible())
        self.assertGreater(editor.view_3d.height(), 180)
        editor.tool_buttons['rectangle'].click(); APP.processEvents()
        self.assertEqual(host.canvas_choice.currentIndex(), 1)
        self.assertTrue(editor.top_view.isVisible())
        host.pane_tabs.setCurrentIndex(2); APP.processEvents()
        editor.donor_edit.setText('8e-')
        before = copy.deepcopy(self.store.device)
        for pane in (0, 1, 3, 2):
            host.pane_tabs.setCurrentIndex(pane); APP.processEvents()
        self.assertTrue(editor.inspector_panel.isVisible())
        self.assertGreater(editor.inspector_panel.width(), 700)
        self.assertEqual(editor.donor_edit.text(), '8e-')
        self.assertEqual(self.store.device, before)
        page.resize(1350, 850); APP.processEvents()
        self.assertFalse(host._compact_editor)
        for panel in (editor.tree_panel, editor.canvas_panel, editor.inspector_panel, editor.top_view, editor.section_view, editor.view_3d, editor.library_panel):
            self.assertTrue(panel.isVisible())
        self.assertEqual(editor.donor_edit.text(), '8e-')

    def test_meep_inputs_have_separate_domain_pulse_and_stopping_owners(self):
        page, host = self.optical('fdtd')
        for key in ('dimensions', 'resolution', 'section_y_um', 'pml_um', 'padding_um'):
            self.assertTrue(host.stack.widget(host.keys['structure']).isAncestorOf(page.controls[key]), key)
        for key in ('polarization', 'wavelength_min_nm', 'wavelength_max_nm', 'frequency_points'):
            self.assertTrue(host.stack.widget(host.keys['parameters']).isAncestorOf(page.controls[key]), key)
        for key in ('run_after_sources', 'courant', 'decay_by', 'fit_materials', 'save_fields'):
            self.assertTrue(host.stack.widget(host.keys['stopping']).isAncestorOf(page.controls[key]), key)

    def test_meep_full_editor_uses_entire_stage_and_excludes_s4_periodic_model(self):
        page, host = self.optical('fdtd')
        original = page.controls['resolution']; original.setValue(43)
        with patch.object(self.store, 'start_run') as run:
            self.assertTrue(page.open_journey_device_editor()); APP.processEvents()
            editor = page.journey_device_editor
            self.assertIs(page.journey_structure_stack.currentWidget(), editor)
            self.assertIsNone(editor.editor._legacy)
            self.assertFalse(editor.editor.advanced_action.isEnabled())
            requests = []; page.routeRequested.connect(requests.append)
            editor.optical_material_action.trigger()
            self.assertEqual(requests, ['materials.optical'])
            self.assertGreater(editor.width(), page.width() * .85)
            editor.back_button.click(); APP.processEvents()
            self.assertEqual(page.journey_structure_stack.currentIndex(), 0)
            self.assertEqual(original.value(), 43)
            self.assertTrue(host.stack.currentWidget().isAncestorOf(original))
            run.assert_not_called()

    def test_s4_original_model_keeps_original_editor_and_returns_to_own_setup(self):
        page, host = self.optical('tools.index_shift')
        self.store.optical_geometry_source = 'original_tables'
        with patch.object(self.store, 'start_run') as run:
            self.assertTrue(page.open_journey_device_editor())
            editor = page.journey_device_editor
            self.assertIsNotNone(editor.editor._legacy)
            self.assertEqual(editor.editor.tabs.currentIndex(), 1)
            self.assertTrue(editor.editor.apply_button.isHidden())
            self.assertIs(editor.menu_buttons['export'].menu(), editor.editor._legacy.export_button.menu())
            editor.continue_button.click(); APP.processEvents()
            self.assertEqual(host.stack.currentIndex(), host.keys['parameters'])
            host.select_stage('structure')
            editor.back_button.click()
            self.assertEqual(page.journey_structure_stack.currentIndex(), 0)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
