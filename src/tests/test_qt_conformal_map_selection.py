"""Saved conformal-map selection behavior; no solver execution."""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtWidgets import QApplication
from qt_research_results import ResearchResultsPanel

APP = QApplication.instance() or QApplication([])


class ConformalMapSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='conformal-selection-', dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = ResearchResultsPanel(engine='pcsel_transport')
        self.first = self.make_run('first')
        self.second = self.make_run('second')

    def tearDown(self):
        from PyQt6 import sip
        sip.delete(self.panel)
        APP.processEvents()

    def make_run(self, name):
        folder = self.root / name
        folder.mkdir()
        (folder / 'research_summary.json').write_text(json.dumps(dict(engine='pcsel_transport', status='complete')), encoding='utf-8')
        for index in range(3):
            values = dict(points_um=np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]),
                          tetrahedra=np.array([[0, 1, 2, 3]]), dof_map=np.arange(4),
                          potential_V=np.array([0., 0., 0., .1 * index]))
            if index != 2:
                values['current_density_A_cm2'] = np.full((4, 3), index + 1.)
            np.savez(folder / f'conformal_state_{index:04d}.npz', **values)
        return folder

    def viewer(self):
        self.assertTrue(self.panel.load_directory(self.first))
        return self.panel.unstructured

    def test_initial_map_prefers_potential_while_diagnostics_remain_selectable(self):
        viewer = self.viewer()
        self.assertEqual(viewer.quantity.currentText(), 'potential_V')
        self.assertGreaterEqual(viewer.quantity.findText('dof_map'), 0)
        self.assertEqual(Path(viewer.files.currentData()).name, 'conformal_state_0000.npz')
        np.testing.assert_array_equal(viewer.values, [0., 0., 0., 0.])

    def test_quantity_survives_state_change_and_falls_back_to_potential_if_unavailable(self):
        viewer = self.viewer()
        viewer.quantity.setCurrentIndex(viewer.quantity.findText('current_density_A_cm2'))
        viewer.files.setCurrentIndex(1)
        self.assertEqual(viewer.quantity.currentText(), 'current_density_A_cm2')
        np.testing.assert_array_equal(viewer.values, np.full((4, 3), 2.))
        viewer.files.setCurrentIndex(2)
        self.assertEqual(viewer.quantity.currentText(), 'potential_V')
        np.testing.assert_array_equal(viewer.values, [0., 0., 0., .2])

    def test_same_run_refresh_preserves_state_and_explicit_diagnostic_quantity(self):
        viewer = self.viewer()
        viewer.files.setCurrentIndex(2)
        viewer.quantity.setCurrentIndex(viewer.quantity.findText('dof_map'))
        self.assertTrue(self.panel.load_directory(self.first))
        self.assertEqual(Path(viewer.files.currentData()).name, 'conformal_state_0002.npz')
        self.assertEqual(viewer.quantity.currentText(), 'dof_map')
        np.testing.assert_array_equal(viewer.values, np.arange(4))

    def test_different_run_starts_with_its_own_default_selection(self):
        viewer = self.viewer()
        viewer.files.setCurrentIndex(2)
        viewer.quantity.setCurrentIndex(viewer.quantity.findText('dof_map'))
        self.assertTrue(self.panel.load_directory(self.second))
        self.assertEqual(Path(viewer.files.currentData()).parent, self.second)
        self.assertEqual(Path(viewer.files.currentData()).name, 'conformal_state_0000.npz')
        self.assertEqual(viewer.quantity.currentText(), 'potential_V')

    def test_direct_viewer_refresh_preserves_state_and_quantity(self):
        viewer = self.viewer()
        viewer.files.setCurrentIndex(1)
        viewer.quantity.setCurrentIndex(viewer.quantity.findText('current_density_A_cm2'))
        self.assertTrue(viewer.load_directory(self.first))
        self.assertEqual(Path(viewer.files.currentData()).name, 'conformal_state_0001.npz')
        self.assertEqual(viewer.quantity.currentText(), 'current_density_A_cm2')


if __name__ == '__main__':
    unittest.main()
