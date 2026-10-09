"""Exercise About shutdown inside the real desktop composition."""
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_library = tempfile.TemporaryDirectory(prefix='optical_about_integration_')
os.environ.setdefault('S4_LIBRARY_ROOT', _library.name)

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication
from app_version import APP_VERSION
from data_library import DataLibrary
from qt_app import OpticalStudio
from qt_core import ProjectStore
from update_client import UpdateCancelled


class AboutIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_about_navigation_and_cancelled_request_defer_close_safely(self):
        store = ProjectStore(DataLibrary(_library.name), restore=False)
        window = OpticalStudio(store)
        window.show()
        window.navigation.setCurrentRow(7)
        self.app.processEvents()
        about = window.pages['About']
        self.assertEqual(window.navigation.currentItem().text(), 'About')
        self.assertEqual(about.info['version'], APP_VERSION)
        self.assertEqual(about.state, 'not_checked')
        self.assertTrue(about.check_button.isEnabled())
        self.assertFalse(hasattr(about, '_credentials'))
        self.assertFalse(hasattr(about, 'account_button'))
        self.assertFalse(hasattr(window.chrome, 'open_button'))
        self.assertFalse(hasattr(window.chrome, 'save_button'))
        entered, released = threading.Event(), threading.Event()

        class PendingClient:
            def check(self, *args, cancel=None):
                entered.set()
                while not cancel.wait(.01):
                    pass
                released.wait(2)
                raise UpdateCancelled()

        about._client_factory = lambda: PendingClient()
        store._autosave = Mock()
        about.check_for_updates()
        self.assertTrue(entered.wait(2))
        window.close()
        self.assertTrue(window.isVisible())
        self.assertTrue(about.busy)
        store._autosave.assert_not_called()
        released.set()
        deadline = time.monotonic() + 3
        while window.isVisible() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(about.busy)
        self.assertFalse(window.isVisible())
        store._autosave.assert_called_once_with()
        window.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
