"""Saved binary fields remain usable throughout viewers and explicit CSV exports."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication

from data_library import DataLibrary
from field_storage import load_field_arrays, write_field_arrays
from field_tracking_ui import _safe_directory, saved_datasets, save_comparison
from field_volume import load_volume
from test_field_tracking_ui import sample


APP = QApplication.instance() or QApplication([])


def binary_sample(directory, **options):
    """Convert a known legacy fixture, keeping its independent CSV reference."""
    model = sample(directory, maps=True, **options)
    path = directory / 'electric_fields.csv'
    frame = pd.read_csv(path)
    for index, component in enumerate(('Ex', 'Ey', 'Ez', 'Hx', 'Hy', 'Hz')):
        frame[component + '_real'] = (index + 1) * (1 + frame.x_um ** 2 + .1 * frame.z_um)
        frame[component + '_imag'] = (index + 1) * .025
    frame['E2'] = sum(frame[c + '_real'] ** 2 + frame[c + '_imag'] ** 2 for c in ('Ex', 'Ey', 'Ez'))
    frame.to_csv(path, index=False)
    reference = pd.read_csv(path, float_precision='round_trip')
    write_field_arrays(directory, load_field_arrays(directory))
    path.unlink(missing_ok=True)
    return model, reference


class BinaryFieldConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = DataLibrary(self.root / 'library')
        self.directory = self.library.runs / 'run' / 'fields'
        self.model, self.reference = binary_sample(self.directory)
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        APP.processEvents()
        plt.close('all')
        self.temp.cleanup()

    def assert_original_stays_binary(self):
        self.assertTrue((self.directory / 'electric_fields.npz').is_file())
        self.assertFalse((self.directory / 'electric_fields.csv').exists())

    def test_discovery_accepts_binary_and_deduplicates_legacy_siblings(self):
        self.assertEqual([identifier for _, identifier in saved_datasets(self.library)], ['run/fields'])
        self.assertEqual(_safe_directory(self.library, 'run/fields'), self.directory.resolve())
        self.reference.to_csv(self.directory / 'electric_fields.csv', index=False)
        self.assertEqual(len(saved_datasets(self.library)), 1)

    def test_volume_preserves_all_electric_and_magnetic_phasors(self):
        metadata, frame, xyz, fields = load_volume(self.directory)
        expected = self.reference[self.reference.plane == 'volume_samples']
        self.assertEqual(metadata['model'], self.model)
        self.assertEqual(len(frame), 27)
        np.testing.assert_array_equal(xyz, expected[['x_um', 'y_um', 'z_um']].to_numpy())
        for prefix in ('E', 'H'):
            phasors = np.column_stack([expected[prefix + axis + '_real'] + 1j * expected[prefix + axis + '_imag'] for axis in 'xyz'])
            np.testing.assert_array_equal(fields[prefix], phasors)
        self.assert_original_stays_binary()

    def test_field_plots_render_without_materializing_csv(self):
        from qt_compute import field_figure
        from ai_campaign_plots import field_figure as campaign_figure
        from target_ui import plot_fields
        figures = [field_figure(self.directory), campaign_figure(dict(field_directory=str(self.directory))),
                   plot_fields(self.directory)]
        for figure in figures:
            self.assertTrue(figure.axes[0].collections or figure.axes[0].images)
            self.assertTrue(figure.axes[1].collections or figure.axes[1].images)
            plt.close(figure)
        self.assert_original_stays_binary()

    def test_comparison_export_contains_full_csv_and_keeps_binary_source(self):
        current = self.library.runs / 'run' / 'second_fields'
        binary_sample(current, thickness=2.)
        with patch.object(self.library, 'export', side_effect=lambda identifier: str(self.library.runs / identifier)):
            result, _ = save_comparison(self.library, 'run/fields', 'run/second_fields')
        exported = pd.read_csv(Path(result) / 'reference_electric_fields.csv')
        self.assertEqual(len(exported), len(self.reference))
        for column in ('Ex_real', 'Ex_imag', 'Hz_real', 'Hz_imag', 'z_um'):
            np.testing.assert_allclose(exported[column], self.reference[column], rtol=1e-15, atol=1e-15)
        self.assert_original_stays_binary()

    def test_native_fields_view_and_explicit_csv_export(self):
        from qt_core import ProjectStore
        from qt_compute import FieldsPage
        page = FieldsPage(ProjectStore(self.library, restore=False))
        self.widgets.append(page)
        page.field_directory = self.directory
        page.render_fields()
        self.assertEqual(page.sample_count.text(), str(len(self.reference)))
        exported = self.root / 'export.csv'
        with patch('qt_compute.QFileDialog.getSaveFileName', return_value=(str(exported), 'CSV data (*.csv)')):
            page.export_data()
        self.assertTrue(exported.is_file(), page.status.text())
        self.assertEqual(len(pd.read_csv(exported)), len(self.reference))
        self.assert_original_stays_binary()

    def test_native_library_preview_and_csv_export(self):
        from qt_core import ProjectStore
        from qt_library import LibraryPage
        self.library.record(self.directory.parent, kind='fields', status='complete', title='Binary field run')
        page = LibraryPage(ProjectStore(self.library, restore=False))
        self.widgets.append(page)
        self.assertEqual(page.result_path(), self.directory / 'electric_fields.npz')
        self.assertEqual(page.table.rowCount(), len(self.reference))
        exported = self.root / 'library-export.csv'
        with patch('qt_library.QFileDialog.getSaveFileName', return_value=(str(exported), 'CSV files (*.csv)')):
            page.save_csv()
        self.assertTrue(exported.is_file(), page.status.text())
        self.assertEqual(len(pd.read_csv(exported)), len(self.reference))
        self.assert_original_stays_binary()


if __name__ == '__main__':
    unittest.main()
