"""Runtime checks can end without a run_finished event; preserve specific feedback."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_LIBRARY = tempfile.TemporaryDirectory(prefix='busy_footer_')
os.environ.setdefault('S4_LIBRARY_ROOT', _LIBRARY.name)
from PyQt6.QtWidgets import QApplication, QLabel, QProgressBar, QWidget
from qt_app import OpticalStudio


class BusyFooterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent = QWidget()  # Never shown; no native window is created.
        self.window = SimpleNamespace(progress_bar=QProgressBar(self.parent),
            status=QLabel('Ready', self.parent), _sync_run_actions=Mock(),
            _closing=False, close=Mock())

    def tearDown(self):
        self.parent.deleteLater()
        self.app.processEvents()

    def test_runtime_check_without_run_finished_returns_generic_status_to_ready(self):
        OpticalStudio.busy_changed(self.window, True)
        self.assertEqual(self.window.status.text(), 'Running\u2026')
        self.assertFalse(self.window.progress_bar.isHidden())
        OpticalStudio.busy_changed(self.window, False)
        self.assertEqual(self.window.status.text(), 'Ready')
        self.assertTrue(self.window.progress_bar.isHidden())
        self.assertEqual(self.window._sync_run_actions.call_count, 2)

    def test_only_exact_generic_status_is_reset(self):
        for message in ('Check: runtime unavailable', 'Electrical simulation: failed',
                        'Runtime available', 'Exported 41 rows', 'Ready', '',
                        'Running...', 'Running\u2026 20 of 41 biases'):
            with self.subTest(message=message):
                self.window.status.setText(message)
                self.window.status.setToolTip('Detailed feedback')
                OpticalStudio.busy_changed(self.window, False)
                self.assertEqual(self.window.status.text(), message)
                self.assertEqual(self.window.status.toolTip(), 'Detailed feedback')

    def test_pending_close_still_schedules_after_worker_finishes(self):
        self.window._closing = True
        self.window.status.setText('Stopping safely before closing\u2026')
        with patch('qt_app.QTimer.singleShot') as schedule:
            OpticalStudio.busy_changed(self.window, False)
        schedule.assert_called_once_with(0, self.window.close)
        self.assertEqual(self.window.status.text(), 'Stopping safely before closing\u2026')


if __name__ == '__main__':
    unittest.main()
