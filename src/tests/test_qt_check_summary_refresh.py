"""Check inputs reflects the schedule committed by its own validation action."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QCoreApplication,QEvent
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from device_model import default_device
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace


class CheckSummaryRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='check-summary-')
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.store.activate_study('electrical.cv')
        self.store.set_device(default_device(self.store.electrical_materials))
        self.page=SimulationSetupWorkspace(self.store,mode='electrical',document_id='electrical.cv')
        self.guard=patch.object(self.store,'start_run',side_effect=AssertionError('No solver/job permitted'))
        self.guard.start()
        self.page.state.set('ui.electrical.sweep_mode','manual')
        self.page.state.parse_biases('0, -.01, .01')
        self.page.setup_flow.show_stage(1)
        self.manual=self.page.widgets_by_key['ui.electrical.bias_list_text'][0]
        self.run_spy=QSignalSpy(self.page.runRequested)

    def tearDown(self):
        self.page.close();self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.app.processEvents();self.guard.stop();self.temp.cleanup()

    def test_check_updates_visible_summary_from_three_to_five_manual_biases(self):
        self.manual.setPlainText('0, -.01, -.005, .005, .01')
        flow=self.page.setup_flow
        flow.show_stage(3)
        self.assertNotIn('-0.005',flow.check_summary.text())
        with patch.object(self.page.state,'validate',return_value=[]):
            flow.check_button.click()
        self.assertEqual(self.page.state.get('search.electrical.biases_V'),[0.,-.01,-.005,.005,.01])
        self.assertEqual(flow.check_summary.text(),self.page.summary.text())
        self.assertIn('-0.005',flow.check_summary.text())
        self.assertIn('0.005',flow.check_summary.text())
        self.assertIs(self.page.stack.currentWidget(),flow.outcome_pages[3])
        self.assertEqual(len(self.run_spy),0)

    def test_invalid_manual_draft_reports_issue_without_replacing_schedule(self):
        self.manual.setPlainText('0, unfinished')
        self.page.setup_flow.show_stage(3)
        before=self.page.setup_flow.check_summary.text()
        with patch.object(self.page.state,'validate',return_value=[]):
            self.page.setup_flow.check_button.click()
        self.assertEqual(self.page.state.get('search.electrical.biases_V'),[0.,-.01,.01])
        self.assertEqual(self.page.setup_flow.check_summary.text(),before)
        self.assertIn('blocking issue',self.page.status.text())
        self.assertEqual(self.manual.toPlainText(),'0, unfinished')
        self.assertEqual(len(self.run_spy),0)

    def test_domain_summary_refreshes_while_check_stage_is_open(self):
        self.page.setup_flow.show_stage(3)
        self.page.state.set('device.temperature_K',330.)
        self.assertIn('330',self.page.setup_flow.check_summary.text())
        self.assertEqual(self.page.setup_flow.check_summary.text(),self.page.summary.text())
        self.assertEqual(len(self.run_spy),0)


if __name__=='__main__':unittest.main()
