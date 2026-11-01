"""Saved sweep recipes and unsaved editor drafts remain explicitly distinct."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_ranges import BoundsEditor

APP=QApplication.instance() or QApplication([])

class RangeDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd())
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.store.settings.update(wl_start_nm=1550,wl_stop_nm=1550)
        self.widgets=[]

    def tearDown(self):
        for w in self.widgets:w.close();w.deleteLater()
        APP.processEvents();self.temp.cleanup()

    def editor(self):
        w=BoundsEditor(self.store);self.widgets.append(w);return w

    def saved(self,w,minimum=.19,maximum=.21):
        w.minimum.setValue(minimum);w.maximum.setValue(maximum);w.step.setValue(.01)
        w.add.click();self.assertFalse(w.has_unsaved_changes())

    def page(self):
        from qt_compute import OptimizePage
        from qt_optical_journey import install_optical_journey
        page=OptimizePage(self.store);page.set_grid_workspace(True);self.widgets.append(page)
        host=install_optical_journey(page,self.store,'tools.sweep')
        page.resize(1100,800);page.show();APP.processEvents();return page,host

    def test_edits_after_save_do_not_change_saved_ranges_or_emit_applied_change(self):
        w=self.editor();self.saved(w);saved=w.records();applied=Mock();w.changed.connect(applied)
        w.maximum.setValue(.23)
        self.assertTrue(w.has_unsaved_changes());self.assertEqual(w.records(),saved);applied.assert_not_called()
        self.assertIn('Unsaved range edits: click Save range to include them',w.status.text())
        self.assertNotIn('Range saved',w.status.text())
        w.maximum.setValue(.21);self.assertFalse(w.has_unsaved_changes())
        self.assertNotIn('Unsaved',w.status.text())

    def test_uncommitted_keyboard_text_is_draft_only(self):
        w=self.editor();self.saved(w);saved=w.records();line=w.maximum.lineEdit()
        line.selectAll();QTest.keyClicks(line,'0.23')
        self.assertTrue(w.has_unsaved_changes());self.assertEqual(w.records(),saved)
        self.assertIn('Unsaved',w.status.text())

    def test_restore_selection_and_refresh_are_clean_but_preserve_a_real_draft(self):
        w=self.editor();self.saved(w);saved=w.records();w.set_records(saved)
        self.assertFalse(w.has_unsaved_changes())
        w.overview.setCurrentCell(0,0);self.assertEqual(w.maximum.value(),.21)
        self.assertFalse(w.has_unsaved_changes())
        self.store.changed.emit('study');self.assertFalse(w.has_unsaved_changes())
        w.maximum.setValue(.23);self.store.changed.emit('structure')
        self.assertTrue(w.has_unsaved_changes());self.assertEqual(w.records(),saved)
        w.load_selected();self.assertFalse(w.has_unsaved_changes());self.assertEqual(w.maximum.value(),.21)
        w.set_records([]);self.assertFalse(w.has_unsaved_changes());self.assertEqual(w.records(),[])

    def test_material_drafts_and_saved_row_reload(self):
        w=self.editor();w.parameter.setCurrentIndex(w.parameter.findData('layer_material'))
        first=w.materials.item(0);first.setCheckState(Qt.CheckState.Checked);w.add.click()
        self.assertTrue(w.records());self.assertFalse(w.has_unsaved_changes())
        w.materials.item(1).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(w.has_unsaved_changes());w.load_selected();self.assertFalse(w.has_unsaved_changes())

    def test_journey_empty_draft_saved_and_fixed_counts_are_planning_only(self):
        page,host=self.page();w=page.bounds
        self.assertIn('No saved ranges: current design only',page.journey_range_summary.text())
        with patch.object(self.store,'start_run',side_effect=AssertionError('No solver allowed')):
            page.check_journey_inputs();self.assertIn('Prepared sweep: 1 design(s)',page.journey_check_state.text())
            w.minimum.setValue(.19);w.maximum.setValue(.21);w.step.setValue(.01)
            host.select_stage('run');host.select_stage('parameters');host.select_stage('checks')
            self.assertTrue(w.has_unsaved_changes());self.assertEqual(w.records(),[])
            self.assertIn('Unsaved range edits',page.journey_range_summary.text())
            page.check_journey_inputs();self.assertIn('Prepared sweep: 1 design(s)',page.journey_check_state.text())
            self.assertIn('Unsaved range edits',page.journey_check_state.text())
            w.add.click();page.check_journey_inputs()
            self.assertIn('Prepared sweep: 3 design(s) × 1 optical sample(s) = 3 planned points',page.journey_check_state.text())
            self.assertNotIn('Unsaved range edits',page.journey_range_summary.text())
            saved=page.peak_options();page._restore('peaks',saved)
            self.assertEqual(page.peak_options(),saved);self.assertFalse(w.has_unsaved_changes())
            w.overview.setCurrentCell(0,0);w.maximum.setValue(.19);w.add.click();page.check_journey_inputs()
            self.assertIn('equal limits give fixed values',page.journey_check_state.text())
            self.assertIn('Prepared sweep: 1 design(s)',page.journey_check_state.text())
            self.assertIn('No execution has started',page.journey_check_state.text())

    def test_shared_radius_is_not_misreported_as_current_design_only(self):
        page,host=self.page();page.shared_hole.enabled.setChecked(True)
        self.assertNotIn('current design only',page.journey_range_summary.text())
        self.assertIn('shared radius controls enabled',page.journey_range_summary.text())
        with patch.object(self.store,'start_run',side_effect=AssertionError('No solver allowed')):
            page.check_journey_inputs()
            self.assertIn('Prepared sweep: 5 design(s)',page.journey_check_state.text())
            self.saved(page.bounds);page.check_journey_inputs()
            self.assertIn('Prepared sweep: 15 design(s)',page.journey_check_state.text())
        page.bounds.set_records([])
        page.shared_hole.enabled.setChecked(False)
        self.assertIn('No saved ranges: current design only',page.journey_range_summary.text())

    def test_planned_points_and_budgets_are_reported_without_rewriting_recipe(self):
        page,host=self.page();self.saved(page.bounds);saved=page.bounds.records()
        page.search_controls['point_budget'].setValue(2)
        with patch.object(self.store,'start_run',side_effect=AssertionError('No solver allowed')):
            page.check_journey_inputs()
            text=page.journey_check_state.text()
            self.assertIn('3 planned points',text);self.assertIn('point budget: 2',text)
            self.assertIn('Planned points exceed the point budget',text)
            self.assertEqual(page.bounds.records(),saved)
            page.search_controls['design_budget'].setValue(2);page.check_journey_inputs()
            self.assertIn('Resolve the input below',page.journey_check_state.text())
            self.assertEqual(page.bounds.records(),saved)

if __name__=='__main__':unittest.main()
