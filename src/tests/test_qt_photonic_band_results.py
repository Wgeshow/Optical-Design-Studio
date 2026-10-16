"""User-facing bands result defaults preserve the underlying saved data."""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication
from qt_photonic_band_results import PhotonicBandResultsPanel


class PhotonicBandResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.panel = PhotonicBandResultsPanel()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def write_run(self, name, connected=True):
        folder = self.root/name
        folder.mkdir()
        summary = dict(engine='mpb', status='complete', dimension=2, num_bands=2, k_points=2,
            path_connectivity=connected, spatial_convergence_established=False,
            sampled_path_gaps={'te': [dict(after_band=1, lower_a_over_lambda=.2,
                upper_a_over_lambda=.3, relative_percent=40.)]})
        (folder/'band_summary.json').write_text(json.dumps(summary), encoding='utf-8')
        (folder/'accuracy.csv').write_text('resolution,error\n16,0.1\n32,0.01\n', encoding='utf-8')
        (folder/'bands_te.csv').write_text('k_index,k1,k2,k3,path_distance_reciprocal_a,band_1_a_over_lambda,band_2_a_over_lambda\n0,0,0,0,0,0.1,0.3\n1,0.5,0,0,0.5,0.2,0.4\n', encoding='utf-8')
        return folder

    def test_opens_band_plot_not_bookkeeping_and_keeps_saved_gaps_explicit(self):
        folder = self.write_run('path')
        self.assertTrue(self.panel.load_directory(folder))
        self.assertEqual(Path(self.panel.files.currentData()).name, 'bands_te.csv')
        self.assertEqual(self.panel.files.currentText(), 'TE bands')
        self.assertEqual(self.panel.y_axis.currentData(), '__bands__')
        self.assertEqual(self.panel.x_axis.currentData(), 'path_distance_reciprocal_a')
        self.assertEqual(self.panel.plot.figure.axes[0].get_ylabel(), 'Normalized frequency a/λ')
        self.assertEqual(list(self.panel.data['band_1_a_over_lambda']), [.1, .2])
        self.assertEqual(self.panel.plot.figure.axes[0].get_legend_handles_labels()[1], ['Band 1', 'Band 2'])
        self.assertTrue(self.panel.x_axis.isHidden())
        self.panel.plot_controls.setChecked(True)
        self.assertFalse(self.panel.x_axis.isHidden())
        self.assertEqual(self.panel.gaps.item(0, 2).text(), '0.2')
        self.assertIn('do not establish a complete band gap', self.panel.gap_note.text())
        self.assertIn('not established', self.panel.status.text())
        # The advanced data is still accessible and file export uses its original path.
        self.assertTrue(any(Path(self.panel.files.itemData(i)).name == 'accuracy.csv'
            for i in range(self.panel.files.count())))
        self.assertEqual(self.panel.export_button.isEnabled(), True)
        self.assertFalse(self.panel.tabs.tabBar().isVisible())

    def test_grid_samples_are_not_connected_and_empty_run_clears_old_gaps(self):
        self.assertTrue(self.panel.load_directory(self.write_run('grid', connected=False)))
        self.assertEqual(self.panel.x_axis.currentData(), 'k_index')
        self.assertEqual(self.panel.plot.figure.axes[0].lines[0].get_linestyle(), 'None')
        folder = self.root/'empty'
        folder.mkdir()
        (folder/'research_summary.json').write_text(json.dumps(dict(engine='photonic_bands', status='partial')), encoding='utf-8')
        self.assertTrue(self.panel.load_directory(folder))
        self.assertEqual(self.panel.gaps.rowCount(), 0)
        self.assertIn('Partial', self.panel.status.text())
        self.assertEqual(self.panel.files.count(), 0)


if __name__ == '__main__':
    unittest.main()
