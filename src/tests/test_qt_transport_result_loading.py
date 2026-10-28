"""Saved-result safety with synthetic archives, never simulation execution."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtWidgets import QApplication
from qt_sesame_setup import TransportResultsPanel
from qt_high_field_results import HighFieldResultsPanel
from qt_research_results import ResearchResultsPanel

APP = QApplication.instance() or QApplication([])


class TransportResultLoadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='transport-result-', dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panels = []

    def tearDown(self):
        from PyQt6 import sip
        for panel in self.panels: sip.delete(panel)
        APP.processEvents()

    def panel(self, cls):
        panel = cls(None)
        self.panels.append(panel)
        return panel

    def directory(self, name, engine):
        result = self.root/name
        result.mkdir()
        (result/'research_summary.json').write_text(json.dumps(dict(engine=engine, status='complete')), encoding='utf-8')
        return result

    @staticmethod
    def fields(ny=1):
        x = np.array([0., .01, .04, .2])
        y = np.arange(ny)*.1
        field = x[None, :]+y[:, None]
        return dict(x_um=x, y_um=y, voltage_V=np.array(.125), potential_V=field,
                    conduction_band_eV=field+1, valence_band_eV=field-1,
                    electron_quasi_fermi_eV=field+.2, hole_quasi_fermi_eV=field-.2)

    def test_missing_states_clear_prior_run_plot_and_bias_note(self):
        first = self.directory('first', 'sesame_transport')
        second = self.directory('second', 'sesame_transport')
        np.savez(first/'transport_state_0000.npz', **self.fields())
        panel = self.panel(TransportResultsPanel)
        self.assertTrue(panel.load_directory(first))
        self.assertEqual(len(panel.state_plot.figure.axes[0].lines), 4)
        self.assertTrue(panel.load_directory(second))
        self.assertIsNone(panel.state)
        self.assertEqual(len(panel.state_plot.figure.axes[0].lines), 0)
        self.assertNotIn('0.125', panel.state_note.text())
        self.assertIn('no saved', panel.state_note.text())
        self.assertFalse(panel.section.isEnabled())

    def test_corrupt_and_mismatched_state_cannot_leave_partial_or_previous_results(self):
        panel = self.panel(TransportResultsPanel)
        folder = self.directory('states', 'sesame_transport')
        valid = folder/'transport_state_0000.npz'
        np.savez(valid, **self.fields())
        self.assertTrue(panel.load_directory(folder))
        for data, expected in [(dict(self.fields(), potential_V=np.zeros((1, 3))), 'does not match'),
                               (dict(self.fields(), x_um=np.array([0, .04, .01, .2])), 'increasing')]:
            np.savez(valid, **data)
            panel.load_state()
            self.assertIsNone(panel.state)
            self.assertIn(expected, panel.state_note.text())
            self.assertEqual(len(panel.state_plot.figure.axes[0].lines), 0)
        valid.write_bytes(b'not a saved npz archive')
        panel.load_state()
        self.assertIsNone(panel.state)
        self.assertIn('Cannot load', panel.state_note.text())

    def test_partial_state_uses_only_saved_quantities(self):
        folder = self.directory('partial', 'sesame_transport')
        data = self.fields()
        for name in list(data):
            if name.endswith('_eV'): del data[name]
        np.savez(folder/'transport_state_0000.npz', **data)
        panel = self.panel(TransportResultsPanel)
        self.assertTrue(panel.load_directory(folder))
        self.assertEqual(panel.quantity.currentData(), 'potential_V')
        self.assertFalse(panel.quantity.model().item(0).isEnabled())
        np.testing.assert_array_equal(panel.state_plot.figure.axes[0].lines[0].get_ydata(), data['potential_V'][0])
        # Programmatic selection of an unavailable item also remains safe.
        panel.quantity.setCurrentIndex(panel.quantity.findData('electrons_cm3'))
        self.assertEqual(len(panel.state_plot.figure.axes[0].lines), 0)
        self.assertIn('not saved', panel.state_note.text())

    def test_switch_from_2d_last_slice_to_1d_does_not_draw_an_out_of_range_slice(self):
        folder = self.directory('slices', 'sesame_transport')
        np.savez(folder/'transport_state_0000.npz', **self.fields(3))
        np.savez(folder/'transport_state_0001.npz', **self.fields())
        panel = self.panel(TransportResultsPanel)
        self.assertTrue(panel.load_directory(folder))
        panel.section.setValue(2)
        np.testing.assert_array_equal(panel.state_plot.figure.axes[0].lines[0].get_ydata(), self.fields(3)['conduction_band_eV'][2])
        panel.states.setCurrentIndex(1)
        self.assertEqual(panel.section.value(), 0)
        self.assertFalse(panel.section.isEnabled())
        np.testing.assert_array_equal(panel.state_plot.figure.axes[0].lines[0].get_ydata(), self.fields()['conduction_band_eV'][0])

    def highfield(self, folder, **overrides):
        values = dict(wavelengths_nm=np.array([1000., 1100., 1200.]), sample_ids=np.array(['state']),
                      absorption_cm1=np.array([[1., 2., 3.]]), delta_n=np.array([[.01, .02, .03]]))
        values.update(overrides)
        np.savez(folder/'high_field_optics.npz', **values)

    def test_failed_highfield_open_clears_previous_specialized_plot(self):
        folder = self.directory('highfield', 'high_field_optics')
        self.highfield(folder)
        panel = self.panel(HighFieldResultsPanel)
        self.assertTrue(panel.load_directory(folder))
        self.assertEqual(len(panel.response_plot.figure.axes[0].lines), 1)
        self.assertFalse(panel.load_directory(self.root/'absent'))
        self.assertEqual(panel.response_data, {})
        self.assertEqual(panel.state.count(), 0)
        self.assertEqual(len(panel.response_plot.figure.axes[0].lines), 0)

    def test_invalid_highfield_array_does_not_commit_partial_data(self):
        folder = self.directory('bad-highfield', 'high_field_optics')
        self.highfield(folder, delta_n=np.array([[.01]]))
        panel = self.panel(HighFieldResultsPanel)
        self.assertFalse(panel.load_directory(folder))
        self.assertEqual(panel.response_data, {})
        self.assertEqual(panel.state.count(), 0)
        self.assertIn('does not match', panel.response_note.text())

    def test_unrecorded_highfield_quantities_are_unavailable_without_old_labels(self):
        folder = self.directory('available-highfield', 'high_field_optics')
        self.highfield(folder)
        panel = self.panel(HighFieldResultsPanel)
        self.assertTrue(panel.load_directory(folder))
        index = panel.quantity.findData('delta_k')
        self.assertFalse(panel.quantity.model().item(index).isEnabled())
        panel.quantity.setCurrentIndex(index)
        self.assertEqual(len(panel.response_plot.figure.axes[0].lines), 0)
        self.assertIn('not saved', panel.response_note.text())


if __name__ == '__main__':
    unittest.main()
