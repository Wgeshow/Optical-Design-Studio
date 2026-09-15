"""Density compacts logical-pixel layouts without making text illegible."""
import os
import re
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from qt_common import ThemeManager


class DensityTests(unittest.TestCase):
    def test_window_widths_are_monotonic_and_do_not_enlarge_desktop(self):
        values = [ThemeManager.window_density(width) for width in (640, 800, 1100, 1460)]
        self.assertEqual(values, [.76, .80, .86, .92])
        self.assertEqual(values, sorted(values))
        self.assertEqual(ThemeManager.window_density(3000), 1.0)

    def test_windows_dpi_uses_logical_width_once(self):
        # A 1000px-wide physical snap region at 125% and 1200px at 150%
        # both supply the same logical 800px Qt resize width.
        self.assertEqual(ThemeManager.window_density(1000/1.25), .80)
        self.assertEqual(ThemeManager.window_density(1200/1.5), .80)

    def test_readable_font_floor_preserves_zero_margins(self):
        manager = ThemeManager()
        manager.scale, manager.window_factor = 70, .76
        result = manager.scale_stylesheet('font-size:10pt; padding:7px; margin:0px; border:1px;')
        self.assertIn('font-size:9pt', result)
        self.assertIn('margin:0px', result)
        self.assertIn('border:1px', result)


if __name__ == '__main__':
    unittest.main()
