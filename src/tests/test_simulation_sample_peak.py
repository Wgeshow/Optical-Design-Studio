"""Saved sample analysis must never launch a solver."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication, QListWidgetItem
from PyQt6.QtCore import Qt
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_compute import SimulationPage, highest_sample_index

APP = QApplication.instance() or QApplication([])


class SamplePeakTests(unittest.TestCase):
    def test_saved_results_change_quantity_and_load_without_running(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProjectStore(DataLibrary(folder), restore=False)
            page = SimulationPage(store)
            frame = pd.DataFrame(dict(wavelength_nm=[1500, 1501, 1502], angle_deg=[0, 0, 0],
                                      R=[.8, .1, .2], T=[.1, .7, .2], A=[.1, .2, .6]))
            frame.to_csv(Path(folder) / 'results.csv', index=False)
            page.directory = Path(folder)
            with patch.object(store, 'start_run') as start:
                page.show_result({})
                for key, row in [('R', 0), ('T', 1), ('A', 2)]:
                    page.peak_quantity.setCurrentIndex(page.peak_quantity.findData(key))
                    self.assertIn(str(1500 + row), page.peak_summary.text())
                    self.assertEqual(page.results.currentRow(), row)
                    self.assertEqual(float(page.plot.figure.axes[0].collections[0].get_offsets()[0, 0]), 1500 + row)
                frame.iloc[:1].to_csv(Path(folder) / 'results.csv', index=False)
                item = QListWidgetItem('Saved')
                item.setData(Qt.ItemDataRole.UserRole, 'saved-id')
                page.recent_runs.addItem(item)
                page.recent_runs.setCurrentItem(item)
                with patch.object(store.library, 'directory', return_value=Path(folder)):
                    page.load_recent()
                self.assertIn('1500', page.peak_summary.text())
                self.assertEqual(page.results.rowCount(), 1)
                page.result_frame = pd.DataFrame({'A': [np.nan, np.inf]})
                page.update_peak()
                self.assertIn('No finite', page.peak_summary.text())
                self.assertEqual(page.power_values['A'].text(), '—')
                start.assert_not_called()
            page.close()
            page.deleteLater()
            APP.processEvents()

    def test_finite_maxima_and_first_tie_ignore_index_labels(self):
        frame = pd.DataFrame({'R': [np.nan, np.inf, .7, .7, -.1]}, index=[9, 9, 8, 7, 6])
        self.assertEqual(highest_sample_index(frame, 'R'), 2)
        self.assertIsNone(highest_sample_index(frame, 'T'))
        self.assertIsNone(highest_sample_index(pd.DataFrame(), 'R'))
        self.assertIsNone(highest_sample_index(pd.DataFrame({'R': [np.nan, -np.inf]}), 'R'))


if __name__ == '__main__':
    unittest.main()
