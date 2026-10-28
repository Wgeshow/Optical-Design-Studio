"""Completed feedback must not consume space or hide problems and progress."""
import os
import tempfile
import unittest
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
_library=tempfile.TemporaryDirectory(prefix='action_notifications_')
os.environ.setdefault('S4_LIBRARY_ROOT',_library.name)
from PyQt6.QtWidgets import QApplication,QWidget,QVBoxLayout
from qt_common import ActionStatusLabel,completion_notice


class ActionNotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_problems_and_progress_never_classified_as_success(self):
        for text in ('Result saved; could not render it.', 'Saved setup needs current targets.',
                     'Completed. Warning: unconverged spectrum.', 'No matching saved work',
                     '5 fields saved; processing next batch', 'Verifying the saved library bundle…',
                     'Comparing saved field maps…', 'Results saved. Restarting the application…'):
            self.assertIsNone(completion_notice(text),text)

    def test_long_completion_uses_one_unicode_ellipsis(self):
        boundary='Exported '+('x'*136)
        self.assertEqual(len(boundary),145)
        self.assertEqual(completion_notice(boundary),('Exported',boundary))
        title,summary=completion_notice(boundary+'x')
        self.assertEqual(title,'Exported')
        self.assertEqual(summary,boundary[:142]+'\u2026')
        self.assertEqual(summary.encode('utf-8')[-3:],b'\xe2\x80\xa6')

    def test_success_hides_label_and_notifies_without_losing_feedback(self):
        host=QWidget();host.notify_action=Mock()
        layout=QVBoxLayout(host);label=ActionStatusLabel();layout.addWidget(label)
        host.show();self.app.processEvents()
        label.setText('Material assigned to Device.')
        self.assertTrue(label.isHidden())
        self.assertEqual(label.text(),'Material assigned to Device.')
        host.notify_action.assert_called_once_with('Assigned','Material assigned to Device.',detail='Material assigned to Device.')
        label.setText('Unable to save material: disk full')
        self.assertFalse(label.isHidden())
        self.assertIn('disk full',label.text())
        host.close();host.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()
