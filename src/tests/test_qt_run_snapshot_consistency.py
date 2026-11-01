"""Submitted project provenance; workers are never launched in these checks."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import BackendWorker, ProjectStore

APP = QApplication.instance() or QApplication([])


class RunSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='ods-snapshot-')
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.store.activate_study('advanced_transport')
        self.old = dict(engine='advanced_transport', study='finite_contact', settings={'contacts': {'fixture': {'rho': 0.}}})
        self.new = copy.deepcopy(self.old)
        self.new['settings']['contacts']['fixture']['rho'] = 1e-5
        self.store.save_search('research_simulation', self.old)
        self.store.save_search('research_workspaces', {'schema_version': 1, 'fixture': {'structured': {'contacts': 'authored draft'}}})

    def submit(self, kind='research_simulation', options=None, **kwargs):
        with patch.object(BackendWorker, 'start') as start:
            self.store.start_run(kind, self.new if options is None else options, **kwargs)
            start.assert_called_once()
        worker = self.store._worker
        self.addCleanup(self.store._finished)
        return worker

    def assert_bank_current(self, project, kind, expected):
        self.assertEqual(project['desktop_search'][kind], expected)
        bank = project['simulation_documents']
        nested = bank['documents'][bank['active']]
        self.assertEqual(nested['desktop_search'][kind], expected)
        self.assertEqual(nested, {k: v for k, v in project.items() if k != 'simulation_documents'})

    def test_new_run_updates_nested_options_preserving_drafts_geometry_and_other_studies(self):
        before = self.store.project()
        worker = self.submit()
        self.assertEqual(worker.options, self.new)
        self.assert_bank_current(worker.project, 'research_simulation', self.new)
        self.assertEqual(worker.project['device'], before['device'])
        self.assertEqual(worker.project['desktop_search']['research_workspaces'], before['desktop_search']['research_workspaces'])
        self.assertEqual(worker.project['simulation_documents']['documents']['optical'], before['simulation_documents']['documents']['optical'])
        self.assert_bank_current(self.store.project(), 'research_simulation', self.new)

    def test_explicit_snapshot_is_not_mutated_or_replaced_with_live_geometry(self):
        snapshot = self.store.project()
        snapshot['device']['width_um'] = 8.
        original = copy.deepcopy(snapshot)
        live = self.store.project()
        worker = self.submit(project_snapshot=snapshot)
        self.assert_bank_current(worker.project, 'research_simulation', self.new)
        self.assertEqual(worker.project['device']['width_um'], 8.)
        self.assertEqual(snapshot, original)
        self.assertEqual(self.store.project(), live)

    def test_legacy_snapshot_without_document_bank_stays_legacy(self):
        snapshot = self.store._project_payload()
        original = copy.deepcopy(snapshot)
        worker = self.submit(project_snapshot=snapshot)
        self.assertNotIn('simulation_documents', worker.project)
        self.assertEqual(worker.project['desktop_search']['research_simulation'], self.new)
        self.assertEqual(snapshot, original)

    def test_original_tables_spectrum_preserves_independent_saved_field_draft(self):
        self.store.optical_geometry_source = 'original_tables'
        self.store.save_search('simulation', {'field_grid': 49, 'phase': False})
        expected = copy.deepcopy(self.store.search_state['simulation'])
        expected.update(phase=True, optical_geometry_source='original_tables')
        worker = self.submit('simulation', {'phase': True})
        self.assertEqual(worker.options, {'phase': True, 'optical_geometry_source': 'original_tables'})
        self.assert_bank_current(worker.project, 'simulation', expected)

    def test_invalid_preparation_reports_attempt_without_launch_or_complete_result(self):
        worker = self.submit()
        failures, completed = [], []
        worker.failed.connect(failures.append)
        worker.completed.connect(completed.append)
        with patch('qt_core.prepare_job', side_effect=ValueError('fixture invalid inputs')), patch('qt_core.subprocess.Popen') as launch:
            worker.run()
        launch.assert_not_called()
        self.assertTrue(failures)
        self.assertIn('fixture invalid inputs', failures[0])
        self.assertFalse(completed)
        self.assertIsNone(worker.directory)
        self.assert_bank_current(worker.project, 'research_simulation', self.new)

    def test_cancel_before_launch_preserves_snapshot_without_claiming_completion(self):
        worker = self.submit()
        failures, completed = [], []
        worker.failed.connect(failures.append)
        worker.completed.connect(completed.append)
        worker.cancel()
        with patch('qt_core.prepare_job', return_value=(worker.project, {})), patch('qt_core.subprocess.Popen') as launch:
            worker.run()
        launch.assert_not_called()
        self.assertTrue(any('cancelled before launch' in message for message in failures))
        self.assertFalse(completed)
        self.assertIsNone(worker.directory)
        self.assert_bank_current(worker.project, 'research_simulation', self.new)


if __name__ == '__main__':
    unittest.main()
