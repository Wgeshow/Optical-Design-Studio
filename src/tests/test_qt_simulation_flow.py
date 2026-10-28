"""The scene-centered presentation retains canonical controls and drafts."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest, QSignalSpy
from PyQt6.QtWidgets import QApplication, QScrollArea
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace
from qt_simulation_flow import STAGES

APP = QApplication.instance() or QApplication([])


class SimulationFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods_flow_', dir=Path(__file__).resolve().parents[3])
        self.store = ProjectStore(DataLibrary(self.temp.name), restore=False)
        self.page = SimulationSetupWorkspace(self.store)
        self.page.resize(1500, 900); self.page.show(); QTest.qWait(30)

    def tearDown(self):
        self.page.close(); self.page.deleteLater(); APP.processEvents(); self.temp.cleanup()

    def test_all_original_sections_have_a_stage_and_keep_same_fields(self):
        before = self.store.portable_project()
        controls = {key: tuple(widgets) for key, widgets in self.page.widgets_by_key.items()}
        for mode in STAGES:
            self.page.set_mode(mode)
            stage_sections = {mode+'.'+suffix for _, suffixes in STAGES[mode] for suffix in suffixes}
            self.assertEqual(stage_sections, {tab['id'] for tab in self.page._modes[mode]['tabs']})
            for section in stage_sections:
                if section == mode+'.overview':
                    # Device opens its full editor first. The visible Back
                    # action reveals its original overview/settings controls.
                    flow=self.page.setup_flow
                    flow.show_stage(0); APP.processEvents()
                    self.assertIs(flow.views.currentWidget(),flow.device_editor)
                    self.assertTrue(flow.device_editor.isVisible())
                    flow.device_editor.back_button.click(); APP.processEvents()
                self.page.select_section(section); APP.processEvents()
                self.assertTrue(self.page.stack.currentWidget().isVisible())
                self.assertEqual(sum(b.isChecked() for b in self.page.setup_flow.step_buttons), 1)
        self.assertEqual(before, self.store.portable_project())
        self.assertEqual(controls, {key:tuple(widgets) for key,widgets in self.page.widgets_by_key.items()})

    def test_wide_scene_is_largest_column_and_compact_has_readable_views(self):
        flow = self.page.setup_flow
        self.assertIs(flow.views.currentWidget(),flow.device_editor)
        self.assertTrue(flow.device_editor.isVisible())
        self.assertGreater(flow.device_editor.height(),400)
        flow.device_editor.back_button.click(); QTest.qWait(30)
        self.assertTrue(flow.view_choice.isVisible())
        self.assertGreater(flow.scene.width(), self.page.center.width())
        self.assertGreater(self.page.shared_preview.height(), 400)
        self.page.resize(776, 570); QTest.qWait(50)
        for view, panel in [('settings',self.page.center),('device',flow.scene),('objects',self.page.nav_panel)]:
            flow.show_compact(view); APP.processEvents()
            self.assertTrue(panel.isVisible()); self.assertGreater(panel.width(), 680)
            self.assertLessEqual(panel.geometry().right(), self.page.width())
        flow.show_compact('settings')
        self.assertTrue(flow.section_picker.isVisible())

    def test_missing_input_switches_compact_view_and_focuses_existing_raw_draft(self):
        self.page.resize(776,570); self.page.select_section('optical.accuracy')
        editor=self.page.widgets_by_key['settings.NumG'][0]
        editor.setText('unfinished'); editor.editingFinished.emit()
        self.page.setup_flow.show_compact('device')
        result=self.page.open_diagnostic(dict(workspace='optical',section='optical.accuracy',field='settings.NumG',message='Enter a finite Fourier basis.'))
        QTest.qWait(40)
        self.assertTrue(result); self.assertEqual(self.page.setup_flow.compact_view,'settings')
        self.assertTrue(editor.isVisible()); self.assertTrue(editor.hasFocus()); self.assertEqual(editor.text(),'unfinished')

    def test_object_selection_edit_route_preserves_setup_and_device(self):
        before=self.store.portable_project()
        self.page.select_section('optical.accuracy')
        editor=self.page.widgets_by_key['settings.NumG'][0]; editor.setText('invalid')
        ident=self.store.device['layers'][0]['id']
        self.page.shared_preview.object_selected.emit(ident)
        self.assertEqual(self.page.setup_flow.object_tree.currentItem().data(0,Qt.ItemDataRole.UserRole),ident)
        spy=QSignalSpy(self.page.diagnosticRequested); self.page.setup_flow.edit_selected()
        self.assertEqual(len(spy),0)
        self.assertEqual(self.page.setup_flow.device_editor.editor.selected_id,ident)
        self.assertIs(self.page.setup_flow.views.currentWidget(),self.page.setup_flow.device_editor)
        self.assertEqual(before,self.store.portable_project()); self.assertEqual(editor.text(),'invalid')

    def test_view_changes_and_domain_details_do_not_change_inputs(self):
        before=self.store.portable_project(); flow=self.page.setup_flow
        self.assertIs(flow.views.currentWidget(),flow.device_editor)
        flow.device_editor.back_button.click(); APP.processEvents()
        self.page.resize(776,570)
        for index in range(3):
            flow.view_choice.setCurrentIndex(index); flow.show_compact('device')
            self.assertEqual(flow.views.currentIndex(),index)
        flow.show_compact('settings'); self.page.set_mode('coupled')
        flow.summary_toggle.setChecked(True); APP.processEvents()
        self.assertLessEqual(flow.details_area.height(),180)
        self.assertTrue(self.page.summary.isVisible()); self.assertTrue(self.page.sequence.isVisible())
        self.assertEqual(before,self.store.portable_project())

    def test_iv_cv_dc_study_selector_remains_original_and_dispatches_electrical(self):
        self.page.set_mode('electrical'); self.page.select_section('electrical.study')
        # Discover the actual canonical selector rather than inventing a study
        # enum. All original values remain reachable through its native widget.
        field=next(f for f in self.page.fields if f.key=='ui.electrical.study' and f.editor.isVisible())
        editor=field.editor
        options=[editor.itemData(i) for i in range(editor.count())]
        self.assertGreaterEqual(len(options),3)
        for value in options:
            editor.setCurrentIndex(editor.findData(value)); APP.processEvents()
            self.assertEqual(self.page.state.get(field.key),value)
        spy=QSignalSpy(self.page.runRequested)
        with patch.object(self.page.state,'validate',return_value=[]): self.page.run()
        self.assertEqual(list(spy),[['electrical']])


if __name__=='__main__': unittest.main()
