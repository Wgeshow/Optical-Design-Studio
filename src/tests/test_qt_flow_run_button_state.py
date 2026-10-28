"""A completed job must not leave another study's Run button disabled."""
import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace
APP=QApplication.instance() or QApplication([])

class FlowRunButtonStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='run_button_')
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.store.activate_study('coupled')
        self.page=SimulationSetupWorkspace(self.store,mode='coupled',document_id='coupled')
        self.flow=self.page.setup_flow
    def tearDown(self):
        self.page.deleteLater();self.store.deleteLater();APP.processEvents();self.temp.cleanup()
    def test_inactive_during_previous_job_reenables_on_activation(self):
        self.store.activate_study('electrical.cv')
        self.store._set_busy(True);self.store._set_busy(False)
        self.assertFalse(self.flow.run_button.isEnabled())
        with patch.object(self.store,'start_run') as start:
            self.store.activate_study('coupled')
            self.assertTrue(self.flow.run_button.isEnabled())
            self.assertFalse(self.flow.stop_button.isEnabled())
            self.assertFalse(self.flow._owns_run)
            start.assert_not_called()
    def test_switching_away_disables_without_busy_transition(self):
        self.assertTrue(self.flow.run_button.isEnabled())
        self.store.activate_study('electrical')
        self.assertFalse(self.flow.run_button.isEnabled())
        self.store.activate_study('coupled')
        self.assertTrue(self.flow.run_button.isEnabled())
    def test_activation_during_foreign_job_cannot_run_or_stop_it(self):
        self.store.activate_study('electrical');self.store._set_busy(True)
        self.store.activate_study('coupled')
        self.assertFalse(self.flow.run_button.isEnabled())
        self.assertFalse(self.flow.stop_button.isEnabled())
        self.assertFalse(self.flow._owns_run)
        self.store._set_busy(False)
        self.assertTrue(self.flow.run_button.isEnabled())

if __name__=='__main__':unittest.main()
