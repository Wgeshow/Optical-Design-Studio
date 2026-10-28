"""Unshown offscreen views of saved RCWA poles; no keyboard or solver calls."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtWidgets import QApplication
from qt_research_results import ResearchResultsPanel

APP = QApplication.instance() or QApplication([])


class RcwaSavedPlotTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(APP.platformName(), 'offscreen')
        self.temp = tempfile.TemporaryDirectory(prefix='rcwa-saved-plot-', dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = ResearchResultsPanel(engine='pcsel')
        (self.root / 'research_summary.json').write_text(json.dumps(dict(engine='pcsel', model='rcwa_poles', status='partial')), encoding='utf-8')
        self.headers = ['seed_real', 'seed_imag', 'frequency', 'imaginary', 'Q', 'residual', 'accepted', 'calls']
        self.rows = [[.2945, -3e-5, .29710651037182106, -.00010785562546227022, 1377.3343258565317, 2.3233400658723452e-14, True, 12],
                     [.3, -3e-5, .298760471450201, -9.91839870098006e-5, 1506.0922657841927, 1.8875430005713714e-13, True, 11],
                     [.31, -3e-5, .32, -.003, 53.333333333333336, .1, False, 20],
                     [.32, -3e-5, .33, -.002, 82.5, .01, '', 9]]
        with (self.root / 'rcwa_poles.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(self.headers)
            writer.writerows(self.rows)
        self.assertTrue(self.panel.load_directory(self.root))

    def tearDown(self):
        from PyQt6 import sip
        sip.delete(self.panel)
        APP.processEvents()

    def test_default_uses_solved_complex_frequency_without_connecting_poles(self):
        self.assertFalse(self.panel.isVisible())
        self.assertEqual(self.panel.x_axis.currentData(), 'frequency')
        self.assertEqual(self.panel.y_axis.currentData(), 'imaginary')
        axis = self.panel.plot.figure.axes[0]
        self.assertEqual(axis.get_xlabel(), 'Real normalized frequency Re(omega a / 2 pi c)')
        self.assertEqual(axis.get_ylabel(), 'Imaginary normalized frequency Im(omega a / 2 pi c)')
        self.assertEqual(len(axis.lines), 3)
        for line in axis.lines:
            self.assertEqual(line.get_linestyle(), 'None')
        accepted, unaccepted, unreported = axis.lines
        self.assertEqual(accepted.get_marker(), 'o')
        self.assertIn('Accepted pole', accepted.get_label())
        np.testing.assert_array_equal(accepted.get_xdata(), [row[2] for row in self.rows[:2]])
        np.testing.assert_array_equal(accepted.get_ydata(), [row[3] for row in self.rows[:2]])
        self.assertEqual(unaccepted.get_marker(), 'x')
        self.assertIn('Unaccepted pole', unaccepted.get_label())
        self.assertEqual(unreported.get_marker(), 's')
        self.assertIn('Acceptance not recorded', unreported.get_label())
        self.assertIn('does not establish convergence', self.panel.chart_note.text())

    def test_q_and_seed_columns_remain_selectable_as_unconnected_saved_points(self):
        self.panel.y_axis.setCurrentIndex(self.panel.y_axis.findData('Q'))
        axis = self.panel.plot.figure.axes[0]
        self.assertEqual(axis.get_ylabel(), 'Quality factor Q (dimensionless)')
        np.testing.assert_array_equal(axis.lines[0].get_ydata(), [row[4] for row in self.rows[:2]])
        self.panel.x_axis.setCurrentIndex(self.panel.x_axis.findData('seed_real'))
        self.panel.y_axis.setCurrentIndex(self.panel.y_axis.findData('seed_imag'))
        axis = self.panel.plot.figure.axes[0]
        self.assertIn('Seed', axis.get_xlabel())
        self.assertTrue(all(line.get_linestyle() == 'None' for line in axis.lines))

    def test_export_and_raw_acceptance_values_are_unchanged(self):
        self.assertEqual(self.panel.table.item(0, 6).text(), 'True')
        self.assertEqual(self.panel.table.item(2, 6).text(), 'False')
        self.assertEqual(self.panel.table.item(3, 6).text(), '')
        target = self.root / 'raw-export.csv'
        with patch('qt_research_results.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            self.panel.export_csv()
        self.assertEqual(target.read_bytes(), (self.root / 'rcwa_poles.csv').read_bytes())


if __name__ == '__main__':
    unittest.main()
