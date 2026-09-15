"""Release checks exercise the real desktop composition, without running S4."""
import os
import sys
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_library = tempfile.TemporaryDirectory(prefix='optical_chrome_smoke_')
os.environ.setdefault('S4_LIBRARY_ROOT', _library.name)

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from installer_smoke import inspect_busy_close_guard, inspect_window_chrome
from qt_app import OpticalStudio
from qt_common import theme_manager
from qt_core import ProjectStore


class InstalledChromeSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.quit_on_close = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)
        cls.old_theme = theme_manager().mode
        cls.store = ProjectStore(DataLibrary(_library.name), restore=False)
        cls.window = OpticalStudio(cls.store)
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        cls.window.deleteLater()
        cls.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        cls.app.setQuitOnLastWindowClosed(cls.quit_on_close)
        theme_manager().apply(cls.old_theme, persist=False)

    def test_actual_application_chrome_fits_both_themes_and_window_sizes(self):
        for mode in ('dark', 'light'):
            theme_manager().apply(mode, persist=False)
            for width, height in ((1000, 720), (1460, 960)):
                with self.subTest(mode=mode, width=width):
                    self.window.resize(width, height)
                    self.app.processEvents()
                    detail = inspect_window_chrome(self.window)
                    self.assertEqual(detail['width'], width)
                    self.assertEqual(detail['visible_controls'], 4 if sys.platform == 'win32' else 7)
                    self.assertTrue(detail['project_commands_in_file_menu'])
                    self.assertFalse(hasattr(self.window, 'open_button'))
                    self.assertFalse(hasattr(self.window, 'save_button'))

    def test_actual_caption_close_preserves_busy_library_guard_and_state(self):
        worker = self.store._worker
        busy = self.store.busy
        status = self.window.status.text()
        detail = inspect_busy_close_guard(self.window, self.app)
        self.assertTrue(detail['active_library_operation_prevents_close'])
        self.assertIs(self.store._worker, worker)
        self.assertEqual(self.store.busy, busy)
        self.assertEqual(self.window.status.text(), status)
        self.assertTrue(self.window.isVisible())


if __name__ == '__main__':
    unittest.main()
