"""A failed/empty research result cannot retain another run's data or exports."""
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


class ResearchResultResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='research-reset-', dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = ResearchResultsPanel(engine='sesame_transport')
        self.first = self.root/'first'
        self.first.mkdir()
        comparison = dict(status='compared', results=[dict(id='curve', status='compared',
            x=[0., 1.], observed=[1., 2.], reference=[1., 2.], rmse=0., units='A')])
        (self.first/'research_summary.json').write_text(json.dumps(dict(engine='sesame_transport', status='complete',
            benchmark_comparison=comparison, provenance='original run')), encoding='utf-8')
        (self.first/'curve.csv').write_text('voltage_V,current_A\n0,1\n1,2\n', encoding='utf-8')
        np.savez(self.first/'array.npz', samples=np.array([[1., 2.], [3., 4.]]))
        np.savez(self.first/'mesh.npz', points_um=np.array([[0.,0.,0.], [1.,0.,0.], [0.,1.,0.], [0.,0.,1.]]),
                 tetrahedra=np.array([[0,1,2,3]]), temperature_K=np.array([300.,301.,302.,303.]))
        self.assertTrue(self.panel.load_directory(self.first))
        self.assertTrue(self.panel.load_reference(self.first/'curve.csv'))
        self.assertIsNotNone(self.panel.arrays.displayed)
        self.assertIsNotNone(self.panel.unstructured.selected_points)
        self.assertEqual(len(self.panel.plot.figure.axes[0].lines), 2)
        self.assertTrue(self.panel.export_button.isEnabled())

    def tearDown(self):
        from PyQt6 import sip
        sip.delete(self.panel)
        APP.processEvents()

    def assert_cleared(self):
        p = self.panel
        self.assertIsNone(p.directory)
        self.assertEqual(p.summary, {})
        self.assertIsNone(p.data)
        self.assertIsNone(p.reference)
        self.assertEqual(p._data_summary, {})
        self.assertEqual(p.files.count(), 0)
        self.assertEqual(p.x_axis.count(), 0)
        self.assertEqual(p.y_axis.count(), 0)
        self.assertEqual(p.table.rowCount(), 0)
        self.assertEqual(p.table.columnCount(), 0)
        self.assertEqual(p.details.toPlainText(), '')
        self.assertFalse(p.export_button.isEnabled())
        self.assertEqual(len(p.plot.figure.axes[0].lines), 0)
        self.assertEqual(p.benchmark_comparison, {})
        self.assertEqual(p.benchmark_choice.count(), 0)
        self.assertEqual(len(p.benchmark_plot.figure.axes[0].lines), 0)
        self.assertIsNone(p.arrays.array)
        self.assertIsNone(p.arrays.displayed)
        self.assertEqual(p.arrays.files.count(), 0)
        self.assertEqual(p.arrays.coordinates, {})
        self.assertEqual(len(p.arrays.plot.figure.axes[0].collections), 0)
        self.assertIsNone(p.unstructured.selected_points)
        self.assertIsNone(p.unstructured.selected_values)
        self.assertIsNone(p.unstructured.points)
        self.assertIsNone(p.unstructured.values)
        self.assertEqual(p.unstructured.files.count(), 0)
        self.assertFalse(p.tabs.isTabEnabled(p.tabs.indexOf(p.unstructured)))
        self.assertEqual(len(p.unstructured.plot.figure.axes[0].collections), 0)
        self.assertIn('No reference', p.compare_status.text())
        with patch('qt_research_results.QFileDialog.getSaveFileName') as dialog:
            p.export_csv()
            p.arrays.export_slice()
            p.unstructured.export_samples()
        dialog.assert_not_called()

    def test_missing_summary_clears_every_view_and_export_buffer(self):
        self.assertFalse(self.panel.load_directory(self.root/'missing'))
        self.assert_cleared()
        self.assertIn('no research result summary', self.panel.status.text())

    def test_wrong_workspace_clears_old_data_and_reports_mismatch(self):
        folder = self.root/'other'; folder.mkdir()
        (folder/'research_summary.json').write_text(json.dumps(dict(engine='high_field_optics')), encoding='utf-8')
        self.assertFalse(self.panel.load_directory(folder))
        self.assert_cleared()
        self.assertIn('different study workspace', self.panel.status.text())

    def test_invalid_json_clears_old_data_without_exposing_previous_provenance(self):
        folder = self.root/'invalid'; folder.mkdir()
        (folder/'research_summary.json').write_text('{ unfinished', encoding='utf-8')
        self.assertFalse(self.panel.load_directory(folder))
        self.assert_cleared()
        self.assertIn('Could not read result', self.panel.status.text())

    def test_nonobject_library_summary_is_a_handled_load_failure(self):
        folder = self.root/'library'; folder.mkdir()
        (folder/'library_record.json').write_text(json.dumps(dict(summary=['invalid'], status='failed')), encoding='utf-8')
        self.assertFalse(self.panel.load_directory(folder))
        self.assert_cleared()
        self.assertIn('JSON object', self.panel.status.text())

    def test_empty_valid_run_has_only_its_new_summary_and_no_old_comparison(self):
        folder = self.root/'empty'; folder.mkdir()
        (folder/'research_summary.json').write_text(json.dumps(dict(engine='sesame_transport', status='partial', reason='No states solved')), encoding='utf-8')
        self.assertTrue(self.panel.load_directory(folder))
        self.assertEqual(self.panel.directory, folder.resolve())
        self.assertEqual(self.panel.files.count(), 0)
        self.assertIsNone(self.panel.reference)
        self.assertIsNone(self.panel.arrays.displayed)
        self.assertIsNone(self.panel.unstructured.selected_values)
        self.assertIn('No states solved', self.panel.details.toPlainText())
        self.assertNotIn('original run', self.panel.details.toPlainText())
        self.assertIn('No reference', self.panel.compare_status.text())
        self.assertEqual(self.panel.benchmark_choice.count(), 0)
        self.assertFalse(self.panel.export_button.isEnabled())

    def test_valid_results_can_be_opened_again_after_failure(self):
        self.assertFalse(self.panel.load_directory(self.root/'missing'))
        self.assertTrue(self.panel.load_directory(self.first))
        self.assertEqual(len(self.panel.plot.figure.axes[0].lines), 1)
        np.testing.assert_array_equal(self.panel.plot.figure.axes[0].lines[0].get_ydata(), [1.,2.])
        self.assertTrue(self.panel.export_button.isEnabled())
        self.assertIsNone(self.panel.reference)
        self.assertIsNotNone(self.panel.arrays.displayed)
        self.assertIsNotNone(self.panel.unstructured.selected_values)


if __name__ == '__main__':
    unittest.main()
