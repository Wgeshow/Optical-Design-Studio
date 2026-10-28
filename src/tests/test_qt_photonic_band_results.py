"""User-facing bands result defaults preserve the underlying saved data."""
import json
import os
from pathlib import Path
import tempfile
import unittest
import math
import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication
from qt_photonic_band_results import PhotonicBandResultsPanel, _path_vertex_ticks


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

    def test_saved_square_path_uses_registered_unequal_vertex_distances(self):
        folder = self.root/'square'
        folder.mkdir()
        points = [(0, 0), (.25, 0), (.5, 0), (.5, .25), (.5, .5), (.25, .25), (0, 0)]
        distances = [0, .25, .5, .75, 1, 1+math.sqrt(.5)/2, 1+math.sqrt(.5)]
        cfg = dict(dimension=2, lattice_vectors=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            k_vertices=[[0, 0, 0], [.5, 0, 0], [.5, .5, 0], [0, 0, 0]],
            sampling='k_vertices', points_per_segment=2)
        summary = dict(engine='mpb', status='complete', path_connectivity=True, options=cfg)
        (folder/'band_summary.json').write_text(json.dumps(summary), encoding='utf-8')
        rows = ['k_index,k1,k2,k3,path_distance_reciprocal_a,band_1_a_over_lambda']
        rows += [f'{i+1},{point[0]},{point[1]},0,{distance},{.1+i*.01}'
                 for i, (point, distance) in enumerate(zip(points, distances))]
        (folder/'bands_tm.csv').write_text('\n'.join(rows)+'\n', encoding='utf-8')
        self.assertTrue(self.panel.load_directory(folder))
        axis = self.panel.plot.figure.axes[0]
        self.assertEqual([item.get_text() for item in axis.get_xticklabels()], ['Γ', 'X', 'M', 'Γ'])
        np.testing.assert_allclose(axis.get_xticks(), [0, .5, 1, 1+math.sqrt(.5)])
        np.testing.assert_allclose(self.panel.data['path_distance_reciprocal_a'], distances)
        self.assertEqual(axis.get_legend_handles_labels()[1], ['Band 1'])

        # Editing the saved cell or path must never keep inappropriate labels.
        for change in ('lattice', 'vertices', 'sampling'):
            modified = json.loads(json.dumps(summary))
            if change == 'lattice': modified['options']['lattice_vectors'][1][0] = .2
            elif change == 'vertices': modified['options']['k_vertices'][1] = [.37, .12, 0]
            else: modified['options']['sampling'] = 'k_points'
            self.assertIsNone(_path_vertex_ticks(modified, self.panel.data))
        summary['options']['lattice_vectors'][1][0] = .2
        (folder/'band_summary.json').write_text(json.dumps(summary), encoding='utf-8')
        self.assertTrue(self.panel.load_directory(folder))
        self.assertNotIn('Γ', [item.get_text() for item in self.panel.plot.figure.axes[0].get_xticklabels()])

    def test_triangular_and_fcc_saved_paths_keep_their_own_coordinate_conventions(self):
        cases = [
            (2, [[1, 0, 0], [.5, math.sqrt(3)/2, 0], [0, 0, 1]],
             [[0, 0, 0], [.5, 0, 0], [2/3, 1/3, 0], [0, 0, 0]], ['Γ', 'M', 'K', 'Γ']),
            (3, [[0, .5, .5], [.5, 0, .5], [.5, .5, 0]],
             [[0, 0, 0], [.5, 0, .5], [.5, .25, .75], [.375, .375, .75],
              [.5, .5, .5], [.625, .25, .625]], ['Γ', 'X', 'W', 'K', 'L', 'U'])]
        for dimension, lattice, vertices, labels in cases:
            # The presentation must use the saved distances, never equally spaced ticks.
            distances = np.cumsum([0] + [.4 + .1*i for i in range(len(vertices)-1)])
            data = {f'k{i+1}': np.array(vertices)[:, i] for i in range(dimension)}
            data['path_distance_reciprocal_a'] = distances
            summary = dict(path_connectivity=True, options=dict(dimension=dimension,
                lattice_vectors=lattice, k_vertices=vertices, sampling='k_vertices', points_per_segment=1))
            actual_positions, actual_labels = _path_vertex_ticks(summary, data)
            np.testing.assert_array_equal(actual_positions, distances)
            self.assertEqual(actual_labels, labels)


if __name__ == '__main__':
    unittest.main()
