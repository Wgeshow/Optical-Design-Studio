"""Maximizing must preserve Qt painting while the native backdrop is retired."""
import ctypes
from ctypes import wintypes
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_library = tempfile.TemporaryDirectory(prefix='s4_glass_import_')
os.environ.setdefault('S4_LIBRARY_ROOT', _library.name)

from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QLabel
from qt_common import COLORS, theme_manager
from qt_surfaces import WorkspaceBackground
from qt_windows_glass import WindowsDesktopGlass, _Margins


class DesktopGlassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager = theme_manager()
        self.previous_look = self.manager.look
        self.manager.apply_look('glass_dark', persist=False)
        self.window = QMainWindow()
        self.window.resize(480, 320)
        self.root = WorkspaceBackground(desktop_root=True)
        layout = QVBoxLayout(self.root)
        layout.addWidget(QLabel('Visible optical design workspace'))
        layout.addStretch()
        self.window.setCentralWidget(self.root)
        self.adapter = WindowsDesktopGlass(self.window)
        self.window._desktop_glass = self.adapter
        # Exercise real Qt state/paint events with recorded Win32 calls on every
        # host. Native desktop capture is a separate optional release check.
        self.adapter.supported = True
        self.adapter.enabled = True
        self.adapter._install_native_notifications = Mock()
        self.adapter.user = SimpleNamespace(
            GetWindowLongW=Mock(return_value=0x00080000),
            SetWindowLongW=Mock())
        self.requests = []
        self.margins = []

        def composition(pointer):
            ctypes.cast(pointer, ctypes.POINTER(wintypes.BOOL)).contents.value = True
            return 0

        def attribute(hwnd, key, pointer, size):
            self.requests.append((key, ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int)).contents.value))
            return 0

        def extend(hwnd, pointer):
            margin = ctypes.cast(pointer, ctypes.POINTER(_Margins)).contents
            self.margins.append((margin.left, margin.right, margin.top, margin.bottom))
            return 0

        self.adapter.dwm = SimpleNamespace(DwmIsCompositionEnabled=composition,
            DwmSetWindowAttribute=attribute, DwmExtendFrameIntoClientArea=extend)
        self.window.show()
        self.settle()
        self.assertTrue(self.adapter.active)

    def tearDown(self):
        self.adapter._timer.stop()
        self.window.close()
        self.window.deleteLater()
        self.settle()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.manager.apply_look(self.previous_look, persist=False)

    def settle(self):
        for _ in range(3):
            self.app.processEvents()

    def assert_opaque_workspace(self):
        image = self.root.grab().toImage()
        color = image.pixelColor(image.width() // 2, image.height() - 30)
        self.assertEqual(color.alpha(), 255)
        self.assertEqual(color.name(), COLORS[self.manager.mode]['bg'])

    def test_maximize_retires_backdrop_before_paint_and_does_not_clear_layered_flag(self):
        self.adapter.user.SetWindowLongW.reset_mock()
        self.window.showMaximized()
        # The synchronous state event changes paint behavior before the timer
        # retires native Acrylic, so no enlarged transparent frame is required.
        self.assertFalse(self.adapter.active)
        self.assertTrue(self.window.property('desktopGlassSuspended'))
        self.assert_opaque_workspace()
        self.settle()
        self.adapter.user.SetWindowLongW.assert_not_called()
        self.assertEqual([value for key, value in self.requests if key == 38][-1], 1)
        self.assertEqual(self.margins[-1], (0, 0, 0, 0))
        self.assertTrue(self.window.property('desktopGlassSuspended'))
        self.assertTrue(self.window.isMaximized())

    def test_restore_reenables_acrylic_and_translucent_workspace(self):
        self.window.showMaximized()
        self.settle()
        self.window.showNormal()
        self.settle()
        self.assertTrue(self.adapter.active)
        self.assertFalse(self.window.property('desktopGlassSuspended'))
        self.assertEqual([value for key, value in self.requests if key == 38][-1], 3)
        self.assertEqual(self.margins[-1], (-1, -1, -1, -1))
        self.adapter.user.SetWindowLongW.assert_called_with(int(self.window.winId()), -20, 0)
        color = self.root.grab().toImage().pixelColor(self.root.width() // 2, self.root.height() - 30)
        self.assertLess(color.alpha(), 255)

    def test_fullscreen_also_uses_opaque_workspace_through_resize(self):
        self.window.showFullScreen()
        self.settle()
        self.adapter.user.SetWindowLongW.reset_mock()
        self.adapter.eventFilter(self.window, QEvent(QEvent.Type.Resize))
        self.assertFalse(self.adapter.active)
        self.settle()
        self.adapter.user.SetWindowLongW.assert_not_called()
        self.assert_opaque_workspace()

    def test_repeated_maximize_restore_and_look_changes_remain_paintable(self):
        for look in ('glass_dark', 'glass_light', 'glass_dark'):
            self.manager.apply_look(look, persist=False)
            self.adapter.apply(True, self.manager.mode)
            self.window.showMaximized()
            self.settle()
            self.assert_opaque_workspace()
            self.assertFalse(self.adapter.active)
            self.window.showNormal()
            self.settle()
            self.assertTrue(self.adapter.active)

    def test_suspension_diagnostic_survives_composition_loss_and_native_failure(self):
        self.window.showMaximized()
        self.assertTrue(self.window.property('desktopGlassSuspended'))
        self.adapter.dwm.DwmIsCompositionEnabled = Mock(return_value=-1)
        self.adapter._apply_native()
        self.assertTrue(self.window.property('desktopGlassSuspended'))
        self.assertFalse(self.adapter.active)
        self.assert_opaque_workspace()
        self.adapter.dwm.DwmIsCompositionEnabled = Mock(side_effect=OSError('DWM unavailable'))
        self.adapter._apply_native()
        self.assertTrue(self.window.property('desktopGlassSuspended'))
        self.window.showNormal()
        self.assertFalse(self.window.property('desktopGlassSuspended'))

    def test_unsupported_platform_also_reports_requested_maximize_state(self):
        self.adapter.supported = False
        self.adapter._set_active(False)
        self.window.showMaximized()
        self.assertTrue(self.window.property('desktopGlassSuspended'))
        self.assert_opaque_workspace()
        self.window.showNormal()
        self.assertFalse(self.window.property('desktopGlassSuspended'))


if __name__ == '__main__':
    unittest.main()
