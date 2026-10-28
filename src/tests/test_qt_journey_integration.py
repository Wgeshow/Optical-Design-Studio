"""Independent checks of shared journey ownership and real edit navigation."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel_research_setup import PcselResearchWorkspace
from research_catalog import list_capabilities

APP = QApplication.instance() or QApplication([])


class SharedJourneyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='journey-integration-', dir=Path.cwd())
        self.store = ProjectStore(DataLibrary(Path(self.temporary.name)/'library'), restore=False)
        self.cap = next(row for row in list_capabilities() if row['engine'] == 'pcsel')
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page.close(); page.deleteLater()
        APP.processEvents(); self.temporary.cleanup()

    def page(self):
        page = PcselResearchWorkspace(self.store, self.cap)
        page.resize(1200, 850); page.show(); APP.processEvents()
        self.pages.append(page)
        return page

    def test_only_job_owner_can_stop_and_receive_execution_events(self):
        owner, other = self.page(), self.page()
        owner.load_pcsel_example(); other.load_pcsel_example()
        with patch.object(owner, 'validate_inputs', return_value=True), \
             patch.object(self.store, 'start_run', side_effect=lambda *_a, **_k:self.store._set_busy(True)), \
             patch.object(self.store, 'cancel') as cancel:
            owner.journey_execution.start_run()
            self.assertTrue(owner._owns_run)
            self.assertTrue(owner.journey_execution.stop.isEnabled())
            self.assertFalse(other.journey_execution.stop.isEnabled())
            other.journey_execution.cancel_run(); cancel.assert_not_called()
            owner.journey_execution.cancel_run(); cancel.assert_called_once()
            self.store.progress.emit({'message':'Owned progress marker'})
            self.assertIn('Owned progress marker', owner.journey_execution.run_status.text())
            self.assertNotIn('Owned progress marker', other.journey_execution.run_status.text())
            self.store.run_failed.emit('Owned failure marker')
            self.store._set_busy(False)
            self.assertFalse(owner._owns_run)
            self.assertFalse(owner.journey_execution.stop.isEnabled())
            self.assertIn('Owned failure marker', owner.journey_execution.run_status.text())
            self.assertNotIn('Owned failure marker', other.journey_execution.run_status.text())

    def test_review_link_reveals_same_invalid_bound_field(self):
        page = self.page(); page.load_pcsel_example()
        field = page.fields['grid_nm']; field.setText('1e-')
        page.select_section('__journey_check'); APP.processEvents()
        review = page.journey_execution
        item = next(review.inputs.topLevelItem(i) for i in range(review.inputs.topLevelItemCount())
                    if review.inputs.topLevelItem(i).data(0,Qt.ItemDataRole.UserRole).get('field')=='grid_nm')
        review._open(item); APP.processEvents()
        self.assertIs(page.fields['grid_nm'],field)
        self.assertEqual(field.text(),'1e-')
        self.assertTrue(field.isVisible())
        self.assertEqual(page.tabs.currentIndex(),page.sections['accuracy'])

    def test_stage_navigation_never_opens_another_window_or_starts_a_run(self):
        page = self.page(); before=set(APP.topLevelWidgets())
        with patch.object(self.store,'start_run') as start:
            for stage in range(len(page.study_flow.stages)):
                page.study_flow.show_stage(stage);APP.processEvents()
            page.study_flow.show_results();APP.processEvents()
            start.assert_not_called()
        self.assertEqual(set(APP.topLevelWidgets()),before)

    def test_rejected_setup_submission_does_not_claim_later_unrelated_job(self):
        from qt_simulation_setup import SimulationSetupWorkspace
        self.store.activate_study('electrical')
        page=SimulationSetupWorkspace(self.store,mode='electrical',document_id='electrical')
        self.pages.append(page);page.show();APP.processEvents()
        flow=page.setup_flow
        # The shell received the request but rejected it before creating a
        # worker. No busy or failed signal belongs to this submission.
        flow._run_requested('electrical');APP.processEvents()
        self.store._set_busy(True)
        try:
            self.assertFalse(flow._owns_run)
            self.assertFalse(flow.stop_button.isEnabled())
            with patch.object(self.store,'cancel') as cancel:
                flow._cancel();cancel.assert_not_called()
        finally:self.store._set_busy(False)


class FullWindowLaserHeaderTests(unittest.TestCase):
    def test_header_results_returns_to_previous_scalar_setup_stage(self):
        from PyQt6.QtCore import QCoreApplication, QEvent
        from PyQt6.QtTest import QTest
        with tempfile.TemporaryDirectory(prefix='laser-header-', dir=Path.cwd()) as temporary, \
             patch.dict(os.environ, S4_LIBRARY_ROOT=temporary):
            from qt_app import OpticalStudio
            store = ProjectStore(DataLibrary(Path(temporary)/'library'), restore=False)
            window = OpticalStudio(store); window.resize(1440,950);window.show();APP.processEvents()
            try:
                window._open_simulation_choice('lumped_laser');APP.processEvents()
                page = window._active_setup_page()
                page._show_laser_stage(2);APP.processEvents()
                previous = page.current_points.value()
                header = window.optical_workflow
                with patch.object(store,'start_run') as start:
                    for label in ('Results','Drive & modulation'):
                        index=next(i for i in range(header.count()) if header.tabText(i).replace('&&','&')==label)
                        QTest.mouseClick(header,Qt.MouseButton.LeftButton,pos=header.tabRect(index).center())
                        APP.processEvents()
                        self.assertEqual(store.active_study,'lumped_laser')
                        self.assertEqual(header.tabText(header.currentIndex()).replace('&&','&'),label)
                        self.assertEqual(page.laser_stage,5 if label=='Results' else 2)
                        self.assertEqual(page.workbench.properties.isVisible(),label=='Drive & modulation')
                    start.assert_not_called()
                self.assertEqual(page.current_points.value(),previous)
            finally:
                window.hide();window.deleteLater();APP.processEvents()
                QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


class OpticalSourceContextReviewTests(unittest.TestCase):
    def test_reused_journey_editor_target_tracks_current_geometry_source(self):
        from PyQt6.QtWidgets import QPushButton
        from qt_index_shift import IndexShiftPage
        from qt_optical_journey import install_optical_journey
        with tempfile.TemporaryDirectory(prefix='source-context-', dir=Path.cwd()) as temporary:
            store=ProjectStore(DataLibrary(Path(temporary)/'library'),restore=False)
            page=IndexShiftPage(store);page.resize(1200,850);page.show()
            try:
                host=install_optical_journey(page,store,'tools.index_shift')
                requests=[];page.routeRequested.connect(requests.append)
                for source,target in [('device','structure.device'),('original_tables','structure.original'),('device','structure.device')]:
                    store.optical_geometry_source=source
                    self.assertIs(install_optical_journey(page,store,'tools.index_shift'),host)
                    host.select_stage('structure');APP.processEvents()
                    self.assertTrue(page.open_journey_device_editor())
                    editor=page.journey_device_editor
                    self.assertEqual(editor.editor.tabs.currentIndex(), 1 if source=='original_tables' else 0)
                    editor.back_button.click(); APP.processEvents()
                    link=next(button for button in page.findChildren(QPushButton)
                              if button.text()=='Open separate periodic structure editor')
                    self.assertEqual(link.isVisible(),source=='original_tables')
                    if source=='original_tables':
                        link.click()
                        self.assertEqual(requests[-1],target)
            finally:
                page.close();page.deleteLater();APP.processEvents()


if __name__=='__main__':
    unittest.main()
