"""Logical hit testing used by the native Windows custom-frame bridge."""
import os
import unittest
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QPoint, QRect
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


if __name__ == '__main__':
    unittest.main()
