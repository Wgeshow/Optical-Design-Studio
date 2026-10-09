"""Logical hit testing used by the native Windows custom-frame bridge."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QPoint, QRect, Qt
from qt_chrome import WindowsCustomFrame


class WindowsFrameTests(unittest.TestCase):
    def setUp(self):
        self.frame = WindowsCustomFrame.__new__(WindowsCustomFrame)
        self.window = SimpleNamespace(width=lambda: 1000, height=lambda: 700,
            isMaximized=lambda: False, isFullScreen=lambda: False)
        self.window.chrome = SimpleNamespace(mapFrom=lambda window, point: point,
            maximize_button=SimpleNamespace(geometry=lambda: QRect(908, 0, 46, 44)))
        self.frame.window = self.window

    def test_maximize_hover_uses_windows_snap_hit_code(self):
        self.assertEqual(self.frame.hit_test(QPoint(930, 22)), 9)
        self.assertEqual(self.frame.hit_test(QPoint(300, 22)), 1)

    def test_native_resize_edges_and_corners(self):
        for point, code in [((1, 1), 13), ((999, 1), 14), ((1, 699), 16),
                            ((999, 699), 17), ((1, 300), 10), ((999, 300), 11),
                            ((500, 1), 12), ((500, 699), 15)]:
            self.assertEqual(self.frame.hit_test(QPoint(*point)), code)

    def test_maximized_window_does_not_offer_resize(self):
        self.window.isMaximized = lambda: True
        self.assertEqual(self.frame.hit_test(QPoint(1, 1)), 1)
        self.assertEqual(self.frame.hit_test(QPoint(930, 22)), 9)

    def _system_command(self, command, state=Qt.WindowState.WindowNoState):
        self.frame.enabled = True
        self.frame.ctypes = SimpleNamespace()
        self.frame.types = SimpleNamespace(MSG=SimpleNamespace(from_address=lambda address:
            SimpleNamespace(message=0x0112, wParam=command)))
        self.window.showMaximized = Mock()
        self.window.showNormal = Mock()
        self.window.isMinimized = lambda: False
        self.window.windowState = lambda: state
        return self.frame.event(1)

    def test_native_maximize_command_uses_qt_state_and_masks_reserved_bits(self):
        self.assertEqual(self._system_command(0xf03f), (True, 0))
        self.window.showMaximized.assert_called_once_with()
        self.window.showNormal.assert_not_called()

    def test_native_restore_command_uses_qt_state(self):
        self.assertEqual(self._system_command(0xf120, Qt.WindowState.WindowMaximized), (True, 0))
        self.window.showNormal.assert_called_once_with()
        self.window.showMaximized.assert_not_called()

    def test_restore_minimized_maximized_window_preserves_maximized_state(self):
        self._system_command(0xf120, Qt.WindowState.WindowMaximized)
        self.window.showMaximized.reset_mock()
        self.window.showNormal.reset_mock()
        self.window.isMinimized = lambda: True
        self.window.windowState = lambda: Qt.WindowState.WindowMinimized | Qt.WindowState.WindowMaximized
        self.assertEqual(self.frame.event(1), (True, 0))
        self.window.showMaximized.assert_called_once_with()
        self.window.showNormal.assert_not_called()

    def test_other_system_commands_are_forwarded_to_windows(self):
        self.assertIsNone(self._system_command(0xf020))
        self.window.showMaximized.assert_not_called()
        self.window.showNormal.assert_not_called()

    def test_normal_snapped_window_restore_is_forwarded_to_windows(self):
        self.assertIsNone(self._system_command(0xf120))
        self.window.showMaximized.assert_not_called()
        self.window.showNormal.assert_not_called()


if __name__ == '__main__':
    unittest.main()
