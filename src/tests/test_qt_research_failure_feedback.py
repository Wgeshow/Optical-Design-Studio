"""Compact failure feedback preserves complete diagnostics without opening windows."""
import os
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog
from qt_research_common import ResearchWorkspaceBase, run_failure_summary
from qt_research_journey import ResearchExecutionPanels
APP=QApplication.instance() or QApplication([])

class Store(QObject):
    busy_changed=pyqtSignal(bool)
    changed=pyqtSignal(str)
    progress=pyqtSignal(dict)
    run_finished=pyqtSignal(dict)
    run_failed=pyqtSignal(str)
    busy=False
    def cancel(self):pass

TRACE='Traceback (most recent call last):\n  File "worker.py", line 1\n    fail()\nValueError: first cause\n\nDuring handling of the above exception, another exception occurred:\nTraceback (most recent call last):\n  File "runtime.py", line 2\n    raise RuntimeError()\nRuntimeError: WSL could not access the saved job directory:\nThe system cannot find the file specified.'

class ResearchFailureFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.store=Store();self.page=ResearchWorkspaceBase(self.store)
    def tearDown(self):
        self.page.close();self.page.deleteLater();APP.processEvents()
    def test_summary_uses_final_cause_and_bounds_unstructured_messages(self):
        text=run_failure_summary(TRACE)
        self.assertTrue(text.startswith('RuntimeError: WSL'))
        self.assertIn('system cannot find',text)
        self.assertNotIn('worker.py',text)
        self.assertNotIn('\n',text)
        self.assertEqual(len(run_failure_summary('x'*1000)),300)
    def test_failed_job_retains_full_report_and_does_not_open_dialog(self):
        before=set(APP.topLevelWidgets());self.page._owns_run=True
        self.page._failed(TRACE)
        self.assertFalse(self.page._owns_run)
        self.assertLess(len(self.page.status.text()),320)
        self.assertEqual(self.page.status.toolTip(),TRACE)
        self.assertEqual(self.page._last_run_error,TRACE)
        issue=self.page.diagnostics.list.item(0)
        self.assertEqual(issue.data(Qt.ItemDataRole.UserRole)['details'],TRACE)
        self.assertNotIn('worker.py',issue.text())
        self.assertFalse(self.page.error_details_button.isHidden())
        self.assertFalse(any(isinstance(w,QDialog) for w in set(APP.topLevelWidgets())-before))
        self.assertEqual(self.page.status.textFormat(),Qt.TextFormat.PlainText)
    def test_execution_status_and_log_keep_summary_and_raw_detail(self):
        panels=ResearchExecutionPanels(self.page)
        panels._observing_run=True;panels.failed(TRACE)
        self.assertLess(len(panels.run_status.text()),320)
        self.assertEqual(panels.run_status.toolTip(),TRACE)
        item=panels.log.topLevelItem(0)
        self.assertEqual(item.data(1,Qt.ItemDataRole.UserRole),TRACE)
        self.assertEqual(item.toolTip(1),TRACE)
        self.assertNotIn('worker.py',item.text(1))
    def test_run_button_refreshes_on_study_return_without_a_tab_change(self):
        # This minimal base page has no concrete draft restore implementation.
        self.store.changed.disconnect(self.page._store_changed)
        active = [False]
        with patch.object(self.page, '_is_active_document', side_effect=lambda:active[0]):
            panels=ResearchExecutionPanels(self.page)
            self.assertFalse(panels.start.isEnabled())
            tab=self.page.tabs.currentIndex()
            active[0]=True;self.store.changed.emit('study')
            self.assertEqual(self.page.tabs.currentIndex(),tab)
            self.assertTrue(panels.start.isEnabled())
            active[0]=False;self.store.changed.emit('study')
            self.assertFalse(panels.start.isEnabled())

    def test_progress_fallback_and_worker_text_remain_readable(self):
        panels=ResearchExecutionPanels(self.page)
        self.page._owns_run=True
        for event,expected in (({}, 'Running…'),
                ({'text':'Preparing current inputs'}, 'Preparing current inputs'),
                ({'message':'Computed 63 of 78 band samples','text':'legacy text'}, 'Computed 63 of 78 band samples')):
            panels.progress(event)
            self.assertEqual(panels.run_status.text(),expected)
            self.assertEqual(panels.log.topLevelItem(panels.log.topLevelItemCount()-1).text(1),expected)

    def test_review_context_uses_readable_separator(self):
        panels=ResearchExecutionPanels(self.page)
        self.assertIn(' · independent setup',panels.context.text())
        self.assertNotIn('Â',panels.context.text())

    def test_non_owner_does_not_receive_failure(self):
        self.page._failed(TRACE)
        self.assertEqual(self.page._last_run_error,'')
        self.assertTrue(self.page.error_details_button.isHidden())

if __name__=='__main__':unittest.main()
