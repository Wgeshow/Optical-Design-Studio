"""AI plan display follows saved inputs and separates capacity from history."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QPushButton
from data_library import DataLibrary
from qt_core import ProjectStore,prepare_job
from qt_ai_search import AISearchPage
from qt_optical_journey import install_optical_journey

APP=QApplication.instance() or QApplication([])

class AIPlanFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd())
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.page=AISearchPage(self.store)
        for key,value in (('initial','2'),('test_count','1'),('adaptive','0')):
            self.page.controls[key].setText(value)
        self.page.bounds.set_records([dict(Parameter='radius',Target='1',Min=.19,Max=.21,Step=.01,Choices='')])
        self.page.save()

    def tearDown(self):
        self.page.close();self.page.deleteLater();APP.processEvents();self.temp.cleanup()

    def test_structure_pruning_invalidates_three_design_preview_without_preparing(self):
        self.page.preview_collection();self.assertIn('Range grid: 3 combinations',self.page.plan_label.text())
        with patch('qt_ai_search.prepare_job',side_effect=AssertionError('No automatic preparation')):
            self.store.patterns.loc[0,'Angle_deg']=1
            self.store.changed.emit('structure')
        self.assertEqual(self.page.bounds.records(),[])
        text=self.page.plan_label.text();self.assertIn('Plan preview needs refresh',text)
        self.assertIn('1 grid candidate before validation',text);self.assertNotIn('Range grid: 3',text)
        self.page.preview_collection();text=self.page.plan_label.text()
        self.assertIn('nominal allocation 1 training + 0 held-out test',text)
        self.assertIn('cannot supply the requested training/test',text)
        self.assertIn('No held-out coverage',text)
        with patch.object(self.page,'_start') as run:
            self.page.run('collect')
        self.assertEqual(run.call_args.args[0],'ai_search')
        self.assertEqual(run.call_args.args[1]['operation'],'collect')
        self.assertEqual(run.call_args.args[1]['bounds'],[])

    def test_control_and_unsaved_range_edits_invalidate_without_new_save_or_prepare(self):
        self.page.preview();saved=self.page.bounds.records()
        with patch('qt_ai_search.prepare_job',side_effect=AssertionError('No automatic preparation')),patch.object(self.store,'save_search') as save:
            self.page.controls['initial'].setText('3')
            self.assertIn('Plan preview needs refresh',self.page.plan_label.text())
            self.page.bounds.maximum.setValue(.23)
            self.assertIn('Unsaved range edits',self.page.plan_label.text())
            save.assert_not_called()
        self.assertEqual(self.page.bounds.records(),saved)

    def test_uncommitted_numeric_keyboard_text_invalidates_without_save_or_prepare(self):
        self.page.preview();control=self.page.controls['grid'];self.assertEqual(control.value(),9)
        with patch('qt_ai_search.prepare_job',side_effect=AssertionError('No automatic preparation')),patch.object(self.store,'save_search') as save:
            line=control.lineEdit();line.selectAll();QTest.keyClicks(line,'11')
            self.assertEqual(control.value(),9)
            self.assertEqual(line.text(),'11')
            self.assertIn('Plan preview needs refresh',self.page.plan_label.text())
            save.assert_not_called()

    def test_same_input_restore_can_conservatively_require_preview_refresh(self):
        self.page.preview_collection();saved=self.page.options()
        self.store.changed.emit('study')
        self.assertIn('Plan preview needs refresh',self.page.plan_label.text())
        self.assertFalse(self.page.bounds.has_unsaved_changes())
        self.assertEqual(self.page.options(),saved)
        self.page.preview_collection();self.assertIn('nominal allocation 2 training + 1 held-out test',self.page.plan_label.text())

    def test_operation_specific_history_labels_do_not_claim_fresh_search_measurements(self):
        self.page.resume.setText('checkpoint.json')
        self.page.campaign=dict(summary=dict(new_simulations=1,elapsed_seconds=10))
        self.page.preview();text=self.page.plan_label.text()
        self.assertIn('Fresh search screening upper bound',text)
        self.assertIn('compatible checkpoint may continue its existing plan/history',text)
        self.assertIn('not a count of fresh simulations',text)
        for operation,phrase in (('fit','Fit uses compatible completed campaign'),('verify','Verification uses eligible leaders')):
            _,job=prepare_job('ai_search',self.store.portable_project(),self.page.options(operation),self.store.library)
            text=self.page.plan_feedback(job['search'])
            self.assertIn(phrase,text);self.assertNotIn('Fresh no-history collection upper capacity',text)

    def test_wrapped_check_inputs_reports_available_vs_requested_for_selected_operation(self):
        host=install_optical_journey(self.page,self.store,'tools.ai')
        self.page.resize(1100,800);self.page.show();host.select_stage('parameters');APP.processEvents()
        preview=next(b for b in self.page.findChildren(QPushButton) if b.text()=='Preview count and estimated time')
        self.assertTrue(preview.isVisible());preview.click()
        self.assertIn('Fresh no-history collection upper capacity',self.page.plan_label.text())
        self.assertIn('verification: ≤0',self.page.plan_label.text())
        host.select_stage('checks');APP.processEvents()
        self.page.journey_check_operation.setCurrentIndex(self.page.journey_check_operation.findData('collect'))
        with patch.object(self.store,'start_run',side_effect=AssertionError('No solver allowed')):
            self.page.check_journey_inputs()
            self.assertIn('Saved range-grid capacity before geometry checks: 3',self.page.journey_check_state.text())
            self.assertIn('nominal allocation 2 training + 1 held-out test',self.page.journey_check_state.text())
            self.page.bounds.set_records([]);self.page.check_journey_inputs()
            self.assertIn('nominal allocation 1 training + 0 held-out test',self.page.journey_check_state.text())
            self.assertIn('current design only',self.page.journey_ai_range_summary.text())
            self.page.resume.setText('checkpoint.json')
            self.page.journey_check_operation.setCurrentIndex(self.page.journey_check_operation.findData('fit'))
            self.page.check_journey_inputs()
            self.assertIn('Fit uses compatible completed campaign',self.page.journey_check_state.text())
            self.assertNotIn('Fresh no-history collection upper capacity',self.page.journey_check_state.text())

if __name__=='__main__':unittest.main()
