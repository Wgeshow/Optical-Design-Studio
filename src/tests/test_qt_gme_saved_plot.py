"""Saved GME bands render as separate curves without changing raw artifacts."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtCore import QLocale
from PyQt6.QtWidgets import QApplication, QHeaderView
from qt_research_results import ResearchResultsPanel

APP = QApplication.instance() or QApplication([])


class GmeSavedPlotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gme-saved-plot-', dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = ResearchResultsPanel(engine='pcsel')
        (self.root / 'research_summary.json').write_text(json.dumps(dict(engine='pcsel', model='gme', status='complete')), encoding='utf-8')
        self.headers = ['k_index', 'kx', 'ky', 'band', 'frequency', 'frequency_imag', 'wavelength_nm', 'Q']
        self.rows = [[ki, .01 * ki, 0., band, .29945709173737717 + band * .01 + ki * .001,
                      .0001964478255249568, 985.1160922203638 + ki + band, 762.1797058255909 + band - ki]
                     for ki in range(3) for band in range(4)]
        with (self.root / 'gme_modes.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(self.headers)
            writer.writerows(self.rows)
        self.assertTrue(self.panel.load_directory(self.root))

    def tearDown(self):
        from PyQt6 import sip
        sip.delete(self.panel)
        APP.processEvents()

    def test_default_plot_connects_only_matching_band_indices(self):
        self.assertEqual(self.panel.x_axis.currentData(), 'k_index')
        self.assertEqual(self.panel.y_axis.currentData(), 'frequency')
        axis = self.panel.plot.figure.axes[0]
        self.assertEqual(len(axis.lines), 4)
        self.assertEqual(axis.get_xlabel(), 'Wavevector sample index')
        self.assertEqual(axis.get_ylabel(), 'Normalized frequency (a / wavelength)')
        for band, line in enumerate(axis.lines):
            np.testing.assert_array_equal(line.get_xdata(), [0., 1., 2.])
            np.testing.assert_array_equal(line.get_ydata(), [row[4] for row in self.rows if row[3] == band])
            self.assertIn('Band ' + str(band), line.get_label())
        self.assertIn('not overlap-tracked', self.panel.chart_note.text())

    def test_selectable_wavelength_and_q_keep_separate_bands_and_units(self):
        for key, units in [('wavelength_nm', 'Wavelength (nm)'), ('Q', 'Quality factor Q (dimensionless)')]:
            self.panel.y_axis.setCurrentIndex(self.panel.y_axis.findData(key))
            axis = self.panel.plot.figure.axes[0]
            self.assertEqual(len(axis.lines), 4)
            self.assertEqual(axis.get_ylabel(), units)
            column = self.headers.index(key)
            np.testing.assert_array_equal(axis.lines[0].get_ydata(), [row[column] for row in self.rows if row[3] == 0])

    def test_compact_numeric_display_preserves_raw_table_tooltip_and_export(self):
        raw = str(self.rows[0][4])
        item = self.panel.table.item(0, 4)
        self.assertEqual(item.text(), raw)
        self.assertEqual(item.toolTip(), raw)
        self.assertEqual(self.panel.table.itemDelegate().displayText(raw, QLocale()), format(float(raw), '.8g'))
        self.assertEqual(self.panel.table.horizontalHeader().sectionResizeMode(0), QHeaderView.ResizeMode.ResizeToContents)
        self.assertTrue(self.panel.table.horizontalHeader().stretchLastSection())
        target = self.root / 'exact-export.csv'
        with patch('qt_research_results.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            self.panel.export_csv()
        self.assertEqual(target.read_bytes(), (self.root / 'gme_modes.csv').read_bytes())
        self.assertEqual(self.panel.data['frequency'][0], self.rows[0][4])


if __name__ == '__main__':
    unittest.main()
