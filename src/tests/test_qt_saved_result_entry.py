"""After restart, finite study Results can inspect saved runs without solving."""
import copy,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace
APP=QApplication.instance() or QApplication([])

class SavedResultEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.root=Path(self.temp.name);self.store=ProjectStore(DataLibrary(self.root/'library'),restore=False)
        self.pages=[]
    def tearDown(self):
        from PyQt6 import sip
        for page in self.pages:
            if hasattr(page,'_save_timer'):page._save_timer.stop()
            sip.delete(page)
        APP.processEvents();self.temp.cleanup()
    def page(self,identity):
        self.store.study_navigation_enabled=True;self.store.activate_study(identity)
        mode='electrical' if identity.startswith('electrical') else identity
        page=SimulationSetupWorkspace(self.store,mode=mode,document_id=identity)
        self.pages.append(page);page.setup_flow.show_stage(5);return page
    def test_each_finite_study_can_browse_without_prior_completion_or_input_mutation(self):
        for identity in ('optical','electrical','electrical.iv','electrical.cv','coupled'):
            with self.subTest(identity=identity):
                page=self.page(identity);flow=page.setup_flow;received=[];page.resultsRequested.connect(received.append)
                before=copy.deepcopy(self.store.study_project(identity))
                self.assertIsNone(flow.completed_event)
                self.assertFalse(flow.open_result_button.isEnabled());self.assertTrue(flow.browse_result_button.isEnabled())
                with patch('qt_simulation_flow.QFileDialog.getExistingDirectory',return_value=str(self.root/'saved')) as dialog,patch.object(self.store,'start_run') as start:
                    flow.browse_result_button.click()
                self.assertEqual(received,[dict(directory=str(self.root/'saved'))])
                self.assertEqual(self.store.study_project(identity),before)
                self.assertEqual(self.store.active_study,identity);self.assertIsNone(flow.completed_event)
                start.assert_not_called();dialog.assert_called_once()
    def test_cancelled_folder_selection_does_not_emit_or_change_input(self):
        page=self.page('electrical.iv');received=[];page.resultsRequested.connect(received.append)
        before=copy.deepcopy(self.store.study_project('electrical.iv'))
        with patch('qt_simulation_flow.QFileDialog.getExistingDirectory',return_value=''):
            page.setup_flow.browse_result_button.click()
        self.assertEqual(received,[]);self.assertEqual(self.store.study_project('electrical.iv'),before)
    def test_existing_completed_run_stays_a_direct_action(self):
        page=self.page('electrical');received=[];page.resultsRequested.connect(received.append)
        event=dict(directory=str(self.root/'latest'),summary=dict(status='complete'))
        page.setup_flow.completed_event=event
        with patch('qt_simulation_flow.QFileDialog.getExistingDirectory') as dialog:
            page.setup_flow._open_result()
        self.assertEqual(received,[event]);dialog.assert_not_called()

if __name__=='__main__':unittest.main()
