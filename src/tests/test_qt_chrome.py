"""Caption interactions and compact layout, without importing solver workflows."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_import_library = tempfile.TemporaryDirectory(prefix='s4_chrome_import_')
os.environ.setdefault('S4_LIBRARY_ROOT', _import_library.name)

from PyQt6.QtCore import Qt, QEvent, QPoint, QCoreApplication, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout

from qt_chrome import WindowChrome
from qt_common import theme_manager


class ChromeHost(QMainWindow):
    """Real Qt window states, with OS move/resize calls recorded offscreen."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Optical Design Studio')
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumSize(1000, 720)
        self.resize(1000, 720)
        self.native_calls = SimpleNamespace(startSystemMove=Mock(return_value=True),
                                            startSystemResize=Mock(return_value=True))
        self.open_project = Mock()
        self.save_project = Mock()
        self.show_settings = Mock()
        self.close_attempts = 0
        self.allow_close = False
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.chrome = WindowChrome(self, self.open_project, self.save_project, self.show_settings)
        layout.addWidget(self.chrome)
        layout.addStretch()
        self.setCentralWidget(central)

    def windowHandle(self):
        return self.native_calls

    def closeEvent(self, event):
        self.close_attempts += 1
        if self.allow_close:
            event.accept()
        else:
            event.ignore()


class WindowChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.previous_quit_on_close = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls.previous_quit_on_close)

    def setUp(self):
        self.manager = theme_manager()
        self.old_theme = self.manager.mode
        self.old_preference = self.manager.settings.value('theme')
        self.manager.apply('dark', persist=False)
        self.window = ChromeHost()
        self.chrome = self.window.chrome
        self.window.show()
        self.window.activateWindow()
        self.settle()

    def tearDown(self):
        for menu in (self.chrome.file_menu, self.chrome.view_menu, self.chrome.system_menu):
            menu.hide()
        self.window.hide()
        self.window.deleteLater()
        self.settle()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if self.old_preference is None:
            self.manager.settings.remove('theme')
        else:
            self.manager.settings.setValue('theme', self.old_preference)
        self.manager.apply(self.old_theme, persist=False)

    def settle(self):
        for _ in range(3):
            self.app.processEvents()

    def click(self, widget):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        self.settle()

    def test_title_and_every_control_fit_at_minimum_width_in_both_themes(self):
        for mode in ('dark', 'light'):
            with self.subTest(mode=mode):
                self.manager.apply(mode, persist=False)
                self.settle()
                controls = [self.chrome.logo, self.chrome.title, self.chrome.file_button,
                            self.chrome.view_button,
                            self.chrome.minimize_button, self.chrome.maximize_button, self.chrome.close_button]
                self.assertEqual(self.chrome.width(), 1000)
                self.assertLessEqual(self.chrome.minimumSizeHint().width(), 1000)
                for widget in controls:
                    self.assertTrue(self.chrome.rect().contains(widget.geometry()), widget.objectName())
                    self.assertGreaterEqual(widget.width(), widget.minimumSizeHint().width())
                for left, right in zip(controls, controls[1:]):
                    self.assertLess(left.geometry().right(), right.geometry().left())
                self.assertGreaterEqual(self.chrome.title.width(),
                                        self.chrome.title.fontMetrics().horizontalAdvance(self.window.windowTitle()))
                self.assertFalse(self.chrome.grab().isNull())

    def test_actions_and_standard_shortcuts_work_with_menus_closed(self):
        self.assertFalse(hasattr(self.chrome, 'open_button'))
        self.assertFalse(hasattr(self.chrome, 'save_button'))
        self.assertIn(self.chrome.open_action, self.chrome.file_menu.actions())
        self.assertIn(self.chrome.save_action, self.chrome.file_menu.actions())
        self.chrome.open_action.trigger()
        self.chrome.save_action.trigger()
        self.window.open_project.assert_called_once()
        self.window.save_project.assert_called_once()
        QTest.keyClick(self.window, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(self.window, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        self.settle()
        self.assertEqual(self.window.open_project.call_count, 2)
        self.assertEqual(self.window.save_project.call_count, 2)
        self.chrome.view_menu.actions()[-1].trigger()
        self.window.show_settings.assert_called_once()

    def test_caption_controls_preserve_window_close_guard(self):
        self.click(self.chrome.close_button)
        self.assertEqual(self.window.close_attempts, 1)
        self.assertTrue(self.window.isVisible(), 'Rejected close must leave the application open')
        self.chrome.file_menu.actions()[-1].trigger()
        self.assertEqual(self.window.close_attempts, 2)
        self.assertTrue(self.window.isVisible())
        self.window.allow_close = True
        self.click(self.chrome.close_button)
        self.assertEqual(self.window.close_attempts, 3)
        self.assertFalse(self.window.isVisible())

    def test_maximize_restore_and_minimize_follow_real_qt_states(self):
        self.assertTrue(all(handle.isVisible() for handle in self.chrome.handles))
        self.click(self.chrome.maximize_button)
        self.assertTrue(self.window.isMaximized())
        self.assertEqual(self.chrome.maximize_button.symbol, 'restore')
        self.assertEqual(self.chrome.maximize_button.accessibleName(), 'Restore window')
        self.assertTrue(all(not handle.isVisible() for handle in self.chrome.handles))
        self.click(self.chrome.minimize_button)
        self.assertTrue(self.window.isMinimized())
        self.assertTrue(self.window.windowState() & Qt.WindowState.WindowMaximized)
        self.window.showMaximized()
        self.settle()
        self.click(self.chrome.maximize_button)
        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.chrome.maximize_button.symbol, 'maximize')
        self.assertTrue(all(handle.isVisible() for handle in self.chrome.handles))
        self.window.showFullScreen()
        self.settle()
        self.assertTrue(all(not handle.isVisible() for handle in self.chrome.handles))

    def test_title_background_drag_and_double_click_use_window_actions(self):
        gap = QPoint((self.chrome.view_button.geometry().right() +
                      self.chrome.minimize_button.geometry().left()) // 2, 22)
        QTest.mouseClick(self.chrome, Qt.MouseButton.LeftButton, pos=gap)
        self.window.native_calls.startSystemMove.assert_called_once_with()
        QTest.mouseDClick(self.chrome, Qt.MouseButton.LeftButton, pos=gap)
        self.settle()
        self.assertTrue(self.window.isMaximized())
        QTest.mouseDClick(self.chrome, Qt.MouseButton.LeftButton, pos=gap)
        self.settle()
        self.assertFalse(self.window.isMaximized())

    def test_clicking_interactive_controls_never_starts_a_window_drag(self):
        for widget in (self.chrome.maximize_button, self.chrome.close_button):
            self.click(widget)
        for button, menu in ((self.chrome.file_button, self.chrome.file_menu),
                             (self.chrome.view_button, self.chrome.view_menu)):
            QTimer.singleShot(0, menu.hide)
            self.click(button)
        self.window.native_calls.startSystemMove.assert_not_called()

    def test_each_edge_requests_os_resize_and_cannot_resize_maximized(self):
        for handle in self.chrome.handles:
            self.click(handle)
            self.window.native_calls.startSystemResize.assert_called_with(handle.edges)
        self.assertEqual(self.window.native_calls.startSystemResize.call_count, 8)
        self.window.showMaximized()
        self.settle()
        # Deliver directly to the now-hidden handle to check its defensive guard too.
        self.click(self.chrome.handles[0])
        self.assertEqual(self.window.native_calls.startSystemResize.call_count, 8)

    def test_theme_menu_and_external_theme_changes_stay_synchronized(self):
        self.chrome.theme_actions['light'].trigger()
        self.settle()
        self.assertEqual(self.manager.mode, 'light')
        self.assertEqual(self.manager.settings.value('theme'), 'light')
        self.assertTrue(self.chrome.theme_actions['light'].isChecked())
        self.assertFalse(self.chrome.theme_actions['dark'].isChecked())
        self.manager.apply('dark', persist=False)
        self.settle()
        self.assertTrue(self.chrome.theme_actions['dark'].isChecked())
        self.assertFalse(self.chrome.theme_actions['light'].isChecked())


if __name__ == '__main__':
    unittest.main()
