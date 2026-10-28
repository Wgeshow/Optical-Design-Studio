"""Synthetic saved-output regression only; no Meep run or model construction."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QPushButton
from qt_fdtd import FDTDPage
from tests.test_qt_fdtd import Store

APP = QApplication.instance() or QApplication([])


class FDTDResultResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fdtd-result-reset-', dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.store = Store()
        self.page = FDTDPage(self.store)
        self.first = self.root/'first'
        self.first.mkdir()
        (self.first/'results.csv').write_text('wavelength_nm,R,T,A\n1500,0.2,0.7,0.1\n1501,0.3,0.5,0.2\n')
        np.savez(self.first/'fdtd_fields.npz', x_um=[-.5, .5], depth_um=[0., 1.],
            field=np.ones((2, 2), dtype=complex), wavelength_nm=1500.)
        self.display(self.first)
        self.assertEqual(self.page.samples.rowCount(), 2)
        self.assertTrue(self.page.field_plot.figure.axes[0].collections)
        self.export = next(item for item in self.page.findChildren(QPushButton) if item.text() == 'Export spectrum CSV…')

    def tearDown(self):
        sip.delete(self.page)
        APP.processEvents()
        self.temp.cleanup()

    def display(self, folder):
        with patch.object(self.store, 'start_run') as start:
            self.page._display_result(dict(directory=str(folder), loaded=True))
        start.assert_not_called()

    def assert_cleared(self):
        self.assertTrue(self.page.result_frame.empty)
        self.assertIsNone(self.page.directory)
        self.assertEqual(self.page.samples.rowCount(), 0)
        for plot in (self.page.plot, self.page.field_plot):
            self.assertTrue(all(not axis.collections and not axis.lines for axis in plot.figure.axes))
        self.assertEqual([item.text() for item in self.page.power_values.values()], ['—']*3)
        self.assertNotIn('1501', self.page.peak_summary.text())
        self.assertFalse(self.export.isEnabled())
        with patch('qt_result_export.QFileDialog.getSaveFileName') as dialog:
            self.export.click()
        dialog.assert_not_called()

    def test_missing_csv_clears_old_result_and_reports_missing_path(self):
        folder = self.root/'missing'
        folder.mkdir()
        self.display(folder)
        self.assert_cleared()
        self.assertIn('Could not load saved Meep results', self.page.status.text())
        self.assertIn('results.csv', self.page.status.text())
        self.assertNotIn('Result saved', self.page.status.text())

    def test_malformed_csv_clears_every_view_and_recovers_on_valid_reload(self):
        folder = self.root/'malformed'
        folder.mkdir()
        (folder/'results.csv').write_text('wavelength_nm,R\n1500,"unterminated\n')
        self.display(folder)
        self.assert_cleared()
        self.assertIn('Could not load saved Meep results', self.page.status.text())
        self.assertIn('EOF inside string', self.page.status.text())
        self.display(self.first)
        self.assertEqual(self.page.directory, self.first)
        self.assertEqual(self.page.samples.rowCount(), 2)
        self.assertTrue(self.export.isEnabled())
        self.assertEqual(self.page.power_values['A'].text(), '0.2000')

    def test_empty_or_unrelated_csv_is_not_reported_as_loaded(self):
        for name, text in [('empty', ''), ('unrelated', 'name,value\nother,3\n')]:
            with self.subTest(case=name):
                folder = self.root/name
                folder.mkdir()
                (folder/'results.csv').write_text(text)
                self.display(folder)
                self.assert_cleared()
                self.assertIn('Could not load saved Meep results', self.page.status.text())
                self.display(self.first)

    def test_malformed_optional_field_does_not_commit_partial_or_old_data(self):
        folder = self.root/'bad-field'
        folder.mkdir()
        (folder/'results.csv').write_text('wavelength_nm,A\n1600,0.8\n')
        np.savez(folder/'fdtd_fields.npz', x_um=[0., 1.])
        self.display(folder)
        self.assert_cleared()
        self.assertIn('depth_um', self.page.status.text())

    def test_new_spectrum_without_fields_clears_old_field_and_updates_export(self):
        folder = self.root/'spectrum-only'
        folder.mkdir()
        (folder/'results.csv').write_text('wavelength_nm,A\n1600,0.8\n')
        self.display(folder)
        self.assertEqual(self.page.result_frame['wavelength_nm'].tolist(), [1600])
        self.assertTrue(all(not axis.collections for axis in self.page.field_plot.figure.axes))
        self.assertEqual(self.page.power_values['A'].text(), '0.8000')
        self.assertTrue(self.export.isEnabled())


if __name__ == '__main__':
    unittest.main()
