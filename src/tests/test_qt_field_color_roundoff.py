"""Display-only handling of constant nonzero fields; saved data stays exact."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtWidgets import QApplication
from qt_electrical_results import _FieldColors, ElectricalResultsPanel
from tests.test_qt_electrical_results import _volume

APP = QApplication.instance() or QApplication([])


class FieldColorRoundoffTests(unittest.TestCase):
    def test_uniform_megavolt_field_uses_readable_padded_limits_without_mutating_samples(self):
        values = np.array([1e6-1e-9, 1e6, 1e6+1e-9])
        before = values.copy()
        for logarithmic in (False, True):
            colors = _FieldColors(values, logarithmic)
            self.assertTrue(colors.padded)
            self.assertIn('saved Δ=', colors.range_text())
            self.assertIn('±1%', colors.range_text())
            ticks = np.linspace(colors.low, colors.high, 5)
            physical = 10**ticks if logarithmic else ticks
            self.assertEqual(len(set(colors.tick_text(v) for v in physical)), 5)
            self.assertEqual(len(set(colors.color(v).rgba() for v in values)), 1)
        np.testing.assert_array_equal(values, before)

    def test_small_physical_signals_and_resolved_relative_variations_keep_actual_range(self):
        for values in (np.array([-1e-20, 0., 1e-20]), np.array([1e-20, 2e-20]), np.array([1e6, 1e6+.001])):
            colors = _FieldColors(values)
            self.assertFalse(colors.padded)
            if values.min() >= 0:
                self.assertEqual(colors.low, values.min())
                self.assertEqual(colors.high, values.max())

    def test_signed_nonzero_constant_and_explicit_tiny_range_opt_in(self):
        values = np.array([-1e6-1e-9, -1e6+1e-9])
        self.assertTrue(_FieldColors(values).padded)
        colors = _FieldColors(values, resolve_tiny=True)
        self.assertFalse(colors.padded)
        self.assertEqual(colors.low, values.min())
        self.assertEqual(colors.high, values.max())
        self.assertNotEqual(colors.tick_text(colors.low), colors.tick_text(colors.high))
        self.assertNotEqual(colors.color(values[0]).rgba(), colors.color(values[1]).rgba())

    def test_recorded_native_dc_mesh8_16_32_ranges_all_get_readable_automatic_limits(self):
        # Extrema read independently from native UI-run custom_1V.npz fields.
        for low, high in [(999999.9999999909, 1000000.0000000047),
                          (999999.9999999696, 1000000.0000000264),
                          (999999.9999999324, 1000000.0000001029)]:
            values = np.array([low, high])
            self.assertTrue(_FieldColors(values).padded)
            self.assertTrue(_FieldColors(values, logarithmic=True).padded)
            self.assertFalse(_FieldColors(values, resolve_tiny=True).padded)

    def test_panel_opt_in_changes_only_display_not_saved_volume(self):
        panel = ElectricalResultsPanel()
        try:
            panel.volume = _volume()
            panel.volume['field_magnitude_V_m'] = np.full(panel.volume['potential'].shape, 1e6)
            panel.volume['field_magnitude_V_m'].flat[0] += 1e-9
            panel.cursor_indices = (0, 0, 0)
            panel.quantity.setCurrentIndex(panel.quantity.findData('field_magnitude_V_m'))
            saved = panel.volume['field_magnitude_V_m'].copy()
            panel.redraw()
            self.assertTrue(panel._colors.padded)
            panel.resolve_tiny_range.setChecked(True)
            self.assertFalse(panel._colors.padded)
            np.testing.assert_array_equal(panel.volume['field_magnitude_V_m'], saved)
        finally:
            panel.close(); panel.deleteLater(); APP.processEvents()
