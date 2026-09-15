"""FDTD Qt controls and setup lifecycle, without downloading any runtime."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from unittest.mock import patch
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from qt_fdtd import FDTDPage, MeepRuntimeSettings


class Store(QObject):
    busy_changed = pyqtSignal(bool)
    progress = pyqtSignal(dict)
    run_finished = pyqtSignal(dict)
    run_failed = pyqtSignal(str)
    busy = False
    search_state = {}
    def cancel(self):
        self.cancelled = True
    def start_run(self, kind, options):
        self.started = kind, options
        self.busy_changed.emit(True)


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dimension_changes_section_control(self):
        page = FDTDPage(Store())
        page.controls['dimensions'].setCurrentIndex(1)
        self.assertFalse(page.controls['section_y_um'].isEnabled())
        self.assertEqual(page.options()['dimensions'], 3)
        page.controls['dimensions'].setCurrentIndex(0)
        self.assertTrue(page.controls['section_y_um'].isEnabled())
        page.deleteLater()

    def test_saved_peak_selection_uses_cached_samples_without_solver(self):
        import tempfile
        from pathlib import Path
        import pandas as pd
        import numpy as np
        store = Store()
        page = FDTDPage(store)
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'start_run') as start:
            path = Path(folder) / 'results.csv'
            pd.DataFrame(dict(wavelength_nm=[1500, 1501, 1502], R=[.8, .1, .2],
                T=[.1, .7, .2], A=[.1, .2, .6])).to_csv(path, index=False)
            page._finished(dict(run_kind='fdtd', directory=folder))
            for key, row in [('R', 0), ('T', 1), ('A', 2)]:
                page.peak_quantity.setCurrentIndex(page.peak_quantity.findData(key))
                self.assertIn(str(1500 + row), page.peak_summary.text())
                self.assertEqual(page.samples.currentRow(), row)
                self.assertEqual(float(page.plot.figure.axes[0].collections[0].get_offsets()[0, 0]), 1500 + row)
            pd.DataFrame(dict(wavelength_nm=[1600], A=[.9])).to_csv(path, index=False)
            with patch('qt_fdtd.QFileDialog.getOpenFileName', return_value=(str(path), '')):
                page.load_results()
            self.assertIn('1600', page.peak_summary.text())
            self.assertEqual(page.samples.rowCount(), 1)
            page.peak_quantity.setCurrentIndex(0)
            self.assertIn('No finite', page.peak_summary.text())
            page.result_frame = pd.DataFrame(dict(wavelength_nm=[1600, 1601], R=[np.nan, np.inf]))
            page.update_peak()
            self.assertIn('No finite', page.peak_summary.text())
            start.assert_not_called()
        page.deleteLater()

    def test_run_dispatch_and_error_restores_panel(self):
        store = Store()
        page = FDTDPage(store)
        page.run()
        self.assertEqual(store.started[0], 'fdtd')
        self.assertTrue(page.stop_button.isEnabled())
        store.run_failed.emit('A useful solver error')
        self.assertEqual(page.status.text(), 'A useful solver error')
        self.assertFalse(page._active)
        page.deleteLater()

    def test_settings_does_not_probe_or_install_on_open(self):
        with patch('meep_runtime.probe') as probe, patch('meep_runtime.install_command') as install:
            panel = MeepRuntimeSettings()
            probe.assert_not_called()
            install.assert_not_called()
            self.assertFalse(panel.is_busy())
            self.assertTrue(panel.shutdown())
            self.assertTrue(panel.expert.isHidden())
            self.assertEqual(panel.install_button.text(), 'Install FDTD engine')
            panel.deleteLater()

    def test_windows_setup_requires_explicit_confirmation(self):
        from PyQt6.QtWidgets import QMessageBox
        with patch('qt_fdtd.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel), \
             patch('meep_managed.setup_windows_support') as setup:
            panel = MeepRuntimeSettings()
            panel.setup_windows()
            setup.assert_not_called()
            panel.deleteLater()


if __name__ == '__main__':
    unittest.main()
