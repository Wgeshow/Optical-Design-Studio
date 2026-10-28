"""Presentation integration tests: real editors and existing job boundaries."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_optical_journey import install_optical_journey

APP = QApplication.instance() or QApplication([])


class OpticalJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods-optical-journey-', dir=Path.cwd())
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page.close(); page.deleteLater()
        APP.processEvents(); self.temp.cleanup()

    def install(self, cls, route):
        page = cls(self.store); self.pages.append(page)
        host = install_optical_journey(page, self.store, route)
        page.resize(950, 700); page.show(); APP.processEvents()
        self.assertGreaterEqual(host.stack.count(), 5)
        self.assertIs(install_optical_journey(page, self.store, route), host)
        return page, host

    def test_fdtd_real_controls_and_domain_navigation(self):
        from qt_fdtd import FDTDPage
        page, host = self.install(FDTDPage, 'fdtd')
        control = page.controls['resolution']; control.setValue(47)
        host.select_stage('parameters'); host.select_stage('structure')
        self.assertEqual(control.value(), 47)
        self.assertTrue(host.stack.currentWidget().isAncestorOf(control))
        host.reveal(page.controls['wavelength_min_nm'])
        self.assertEqual(host.stack.currentIndex(), host.keys['parameters'])
        page.workbench.show_results()
        self.assertEqual(host.stack.currentIndex(), host.keys['results'])

    def test_index_shift_edits_use_existing_options(self):
        from qt_index_shift import IndexShiftPage
        page, host = self.install(IndexShiftPage, 'tools.index_shift')
        page.controls['start'].setValue(.004)
        self.assertEqual(page.options()['start'], .004)
        page.select_tool_tab('response')
        self.assertEqual(host.stack.currentIndex(), host.keys['results'])
        self.assertEqual(page.result_tabs.currentIndex(), 0)

    def test_field_sampling_identity_and_saved_tabs(self):
        from qt_compute import FieldsPage
        page, host = self.install(FieldsPage, 'tools.fields')
        page.grid.setValue(31)
        host.select_stage('run'); host.select_stage('parameters')
        self.assertEqual(page.grid.value(), 31)
        page.select_tool_tab('volume')
        self.assertEqual(page.tabs.currentIndex(), 2)
        self.assertEqual(host.stack.currentIndex(), host.keys['results'])

    def test_original_spectrum_and_real_run_boundary(self):
        from qt_compute import SimulationPage
        page, host = self.install(SimulationPage, 'optical')
        page.controls['wl_start_nm'].setValue(1531)
        page.save_settings()
        self.assertEqual(self.store.settings['wl_start_nm'], 1531)
        with patch.object(self.store, 'start_run') as run:
            host.select_stage('parameters'); host.select_stage('run')
            run.assert_not_called()

    def test_campaign_controls_and_results_preserved(self):
        from qt_ai_search import AISearchPage
        page, host = self.install(AISearchPage, 'tools.ai')
        page.controls['test_count'].setText('7')
        self.assertEqual(page.options()['test_count'], '7')
        page.select_tool_tab('validation')
        self.assertEqual(page.result_tabs.currentIndex(), 5)
        self.assertEqual(host.stack.currentIndex(), host.keys['results'])

    def test_grid_recipe_keeps_exhaustive_method(self):
        from qt_compute import OptimizePage
        page = OptimizePage(self.store); page.set_grid_workspace(True); self.pages.append(page)
        host = install_optical_journey(page, self.store, 'tools.sweep')
        self.assertEqual(page.search_controls['search_mode'].currentData(), 'Exhaustive grid')
        host.select_stage('results'); host.select_stage('parameters')
        self.assertEqual(page.search_controls['search_mode'].currentData(), 'Exhaustive grid')
        before=page.peak_options()
        self.assertTrue(page.select_tool_tab('explore.learning'))
        self.assertEqual(page.general_detail_tabs.currentIndex(),1)
        self.assertEqual(host.stack.currentIndex(),host.keys['sampling'])
        self.assertFalse(page.ml_settings.isEnabled())
        self.assertFalse(page.general_detail_tabs.isTabVisible(0))
        self.assertFalse(page.general_detail_tabs.isTabVisible(2))
        self.assertEqual(page.peak_options(),before)
        from PyQt6.QtWidgets import QPushButton
        requests=[];page.routeRequested.connect(requests.append)
        next(b for b in page.findChildren(QPushButton) if b.text()=='Open AI optical search').click()
        self.assertEqual(requests,['tools.ai'])
        self.assertEqual(page.peak_options(),before)

    def test_fdtd_check_uses_actual_validation_and_jumps_to_field(self):
        from qt_fdtd import FDTDPage
        page,host=self.install(FDTDPage,'fdtd')
        page.controls['wavelength_min_nm'].setValue(1800)
        page.controls['wavelength_max_nm'].setValue(1200)
        host.select_stage('checks')
        with patch.object(self.store,'start_run') as run:
            page.check_journey_inputs()
            run.assert_not_called()
        self.assertEqual(page.journey_diagnostics.list.count(),1)
        page.journey_diagnostics.go_to_first()
        self.assertEqual(host.stack.currentIndex(),host.keys['parameters'])
        page.controls['wavelength_max_nm'].setValue(2000)
        self.assertEqual(page.journey_diagnostics.list.count(),0)
        self.assertIn('Inputs changed',page.journey_check_state.text())

    def test_cancel_cannot_stop_another_study_and_failure_is_real(self):
        from qt_compute import FieldsPage
        page,host=self.install(FieldsPage,'tools.fields')
        self.store.active_study='electrical'
        self.store._set_busy(True)
        with patch.object(self.store,'cancel') as cancel:
            page.journey_cancel_button.click()
            for button in page.stops: button.click()
            cancel.assert_not_called()
        self.store._set_busy(False)
        self.store.active_study='tools.fields'
        page._active='fields'
        self.store._set_busy(True)
        self.store.progress.emit(dict(run_kind='fields',message='Sampling actual field request'))
        self.assertTrue(page.journey_cancel_button.isEnabled())
        self.store.run_failed.emit('Actual worker failure')
        self.assertEqual(page.journey_run_state.text(),'Actual worker failure')
        self.assertFalse(page.journey_cancel_button.isEnabled())
        self.store._set_busy(False)

    def test_band_navigation_uses_actual_sampling_and_preserves_request(self):
        from qt_photonic_bands import PhotonicBandsWorkspace
        page=PhotonicBandsWorkspace(self.store); self.pages.append(page)
        before=page.options()
        page._journey_requested(2)
        self.assertEqual(page.tabs.tabText(page.tabs.currentIndex()),'k-space path')
        page.points_per_segment.setText('17')
        self.assertEqual(page.options()['settings']['points_per_segment'],17)
        page._journey_requested(0); page._journey_requested(1)
        self.assertEqual(page.options()['settings']['geometry'],before['settings']['geometry'])
        page._save_timer.stop()
        self.assertEqual(len(page.journey_bar.stages),7)
        page._journey_requested(4)
        self.assertEqual(page.tabs.currentIndex(),page.sections['__journey_check'])
        page._journey_requested(5)
        self.assertEqual(page.tabs.currentIndex(),page.sections['__journey_run'])

    def test_campaign_check_requires_checkpoint_for_selected_operation(self):
        from qt_ai_search import AISearchPage
        page,host=self.install(AISearchPage,'tools.ai')
        page.resume.clear()
        page.journey_check_operation.setCurrentIndex(page.journey_check_operation.findData('verify'))
        with patch.object(self.store,'start_run') as run:
            page.check_journey_inputs(); run.assert_not_called()
        self.assertEqual(page.journey_diagnostics.list.count(),1)
        issue=page.journey_diagnostics.list.item(0).data(256)
        self.assertEqual(issue['field'],'resume')
        self.assertIn('checkpoint',issue['message'])
        page.resume.setText('editable-checkpoint-path')
        self.assertEqual(page.journey_diagnostics.list.count(),0)


if __name__ == '__main__': unittest.main()
