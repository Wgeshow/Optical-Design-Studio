"""Saved maximized windows must establish their normal backing store first."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
_library=tempfile.TemporaryDirectory(prefix='s4_window_restore_import_')
os.environ.setdefault('S4_LIBRARY_ROOT',_library.name)

from PyQt6.QtCore import QCoreApplication,QEvent,Qt,QRect
from PyQt6.QtWidgets import QApplication,QMainWindow,QLabel
from qt_app import OpticalStudio


class RestoreHost(OpticalStudio):
    """Exercise production state/paint methods without solver/page setup."""
    def __init__(self,state):
        QMainWindow.__init__(self)
        self.setGeometry(QRect(25,30,700,500))
        self.setWindowState(state)
        self._defer_saved_window_state()
        self.setCentralWidget(QLabel('Visible content after restoring window state'))


class WindowStateRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.previous_quit=cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls.previous_quit)

    def tearDown(self):
        if hasattr(self,'window'):
            self.window.hide()
            self.window.deleteLater()
            self.settle()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def settle(self):
        for _ in range(5):self.app.processEvents()

    def test_maximized_state_is_deferred_until_first_visible_paint(self):
        self.window=RestoreHost(Qt.WindowState.WindowMaximized)
        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.geometry(),QRect(25,30,700,500))
        self.assertEqual(self.window._startup_window_state,Qt.WindowState.WindowMaximized)
        # Rendering a hidden preview must not consume the pending startup state.
        self.assertFalse(self.window.grab().isNull())
        self.assertFalse(self.window.isVisible())
        self.assertEqual(self.window._startup_window_state,Qt.WindowState.WindowMaximized)
        self.window.show()
        self.settle()
        self.assertTrue(self.window.isMaximized())
        self.assertEqual(self.window._startup_window_state,Qt.WindowState.WindowNoState)
        self.window.showNormal()
        self.window.update()
        self.settle()
        self.assertFalse(self.window.isMaximized(),'Later repaint must not reapply the startup state')
        self.assertEqual(self.window.size().width(),700)
        self.assertEqual(self.window.size().height(),500)

    def test_fullscreen_state_is_restored_after_initial_normal_paint(self):
        self.window=RestoreHost(Qt.WindowState.WindowFullScreen)
        self.assertFalse(self.window.isFullScreen())
        self.window.show()
        self.settle()
        self.assertTrue(self.window.isFullScreen())
        self.window.showNormal()
        self.settle()
        self.assertFalse(self.window.isFullScreen())

    def test_normal_window_preserves_geometry_and_stays_normal(self):
        self.window=RestoreHost(Qt.WindowState.WindowNoState)
        self.assertEqual(self.window._startup_window_state,Qt.WindowState.WindowNoState)
        self.window.show()
        self.settle()
        self.assertFalse(self.window.isMaximized())
        self.assertFalse(self.window.isFullScreen())
        self.assertEqual(self.window.size().width(),700)
        self.assertEqual(self.window.size().height(),500)


if __name__=='__main__':unittest.main()
