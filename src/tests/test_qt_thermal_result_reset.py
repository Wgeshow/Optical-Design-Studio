"""Synthetic saved-output regression; no thermal solver or native UI journey."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication
from qt_thermal_setup import ThermalResultsPanel

APP = QApplication.instance() or QApplication([])


class ThermalResultResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='thermal-result-reset-', dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.panel = ThermalResultsPanel(None)
        self.first = self.folder('first')
        self.arrays = dict(x=np.array([-.5, .5])*1e-6, y=np.array([-.5, .5])*1e-6,
            z=np.array([.25, .75])*1e-6, temperature_K=np.full((2, 2, 2), 310.),
            temperature_rise_K=np.full((2, 2, 2), 10.), heat_density_W_m3=np.ones((2, 2, 2)))
        np.savez(self.first/'thermal_volume.npz', **self.arrays)
        self.assertTrue(self.panel.load_directory(self.first))
        self.assertGreater(len(self.panel.volume_plot.figure.axes[0].collections), 0)
        self.panel.slice.setValue(1)

    def tearDown(self):
        sip.delete(self.panel)
        APP.processEvents()
        self.temp.cleanup()

    def folder(self, name):
        path = self.root/name
        path.mkdir()
        (path/'research_summary.json').write_text(json.dumps(dict(engine='thermal', status='complete', label=name)))
        return path

    def assert_volume_cleared(self):
        self.assertIsNone(self.panel.volume)
        self.assertTrue(all(not axis.collections for axis in self.panel.volume_plot.figure.axes))
        self.assertFalse(self.panel.slice.isEnabled())
        self.assertFalse(self.panel.quantity.isEnabled())
        self.assertEqual((self.panel.slice.minimum(), self.panel.slice.maximum()), (0, 0))
        with patch('qt_thermal_setup.QFileDialog.getSaveFileName') as dialog:
            self.panel.export_slice()
        dialog.assert_not_called()

    def test_failed_result_open_clears_previous_thermal_plot_and_controls(self):
        self.assertFalse(self.panel.load_directory(self.root/'missing'))
        self.assert_volume_cleared()
        self.assertIn('No saved thermal volume', self.panel.volume_note.text())

    def test_valid_summary_without_volume_does_not_retain_previous_map(self):
        self.assertTrue(self.panel.load_directory(self.folder('summary-only')))
        self.assert_volume_cleared()
        self.assertIn('No saved thermal volume', self.panel.volume_note.text())

    def test_malformed_volume_is_not_committed_or_left_as_old_result(self):
        invalid = self.folder('invalid')
        arrays = dict(self.arrays, temperature_K=np.zeros((2, 2)))
        np.savez(invalid/'thermal_volume.npz', **arrays)
        self.assertTrue(self.panel.load_directory(invalid))
        self.assert_volume_cleared()
        self.assertIn('Could not load', self.panel.volume_note.text())

    def test_wrong_shape_and_nonfinite_coordinates_are_handled_then_valid_reload_works(self):
        for name, overrides in [('wrong-shape', dict(heat_density_W_m3=np.zeros((3, 2, 2)))),
                                ('nonfinite', dict(x=np.array([0., np.nan]))),
                                ('missing-key', None)]:
            with self.subTest(case=name):
                invalid = self.folder(name)
                arrays = dict(self.arrays, **(overrides or {}))
                if overrides is None:
                    arrays.pop('z')
                np.savez(invalid/'thermal_volume.npz', **arrays)
                self.assertTrue(self.panel.load_directory(invalid))
                self.assert_volume_cleared()
                self.assertIn('Could not load', self.panel.volume_note.text())
                self.assertTrue(self.panel.load_directory(self.first))
                self.assertIsNotNone(self.panel.volume)
                self.assertTrue(self.panel.quantity.isEnabled())
                self.assertGreater(len(self.panel.volume_plot.figure.axes[0].collections), 0)


if __name__ == '__main__':
    unittest.main()
