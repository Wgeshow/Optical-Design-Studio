"""Research job boundary, persistence and failure semantics (no physics mocks claimed)."""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication

from backend import Cancelled
from data_library import DataLibrary
from qt_core import ProjectStore, prepare_job
from research_simulation import execute_research, prepare_research_job, validate_research_options


APP = QApplication.instance() or QApplication([])


def inputs():
    return dict(engine='photonic_bands', study='band_structure', settings=dict(
        dimension=2, lattice_vectors=[[1., 0.], [0., 1.]], background_epsilon=1.,
        geometry=[dict(shape='circle', radius=.2, epsilon=12.)],
        k_vertices=[[0., 0.], [.5, 0.]], num_bands=3, resolution=16,
        polarizations=['te'], points_per_segment=4, solver='mpb'))


class ResearchBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods-research-contract-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_unknown_adapters_nonfinite_values_and_unexpected_fields_fail(self):
        for cfg in (dict(inputs(), engine='os'), dict(inputs(), study='unimplemented'),
                    dict(inputs(), module='arbitrary_module'), dict(inputs(), settings={'x': float('nan')})):
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                validate_research_options(cfg)

    def test_draft_portable_project_roundtrip_preserves_explicit_geometry(self):
        store = ProjectStore(DataLibrary(self.root/'first'), restore=False)
        store.save_search('research_simulation', inputs())
        saved = store.portable_project()
        other = ProjectStore(DataLibrary(self.root/'elsewhere'), restore=False)
        other.load_project(saved)
        self.assertEqual(other.search_state['research_simulation'], inputs())

    def test_preparation_routes_without_needing_s4_optical_tables(self):
        store = ProjectStore(DataLibrary(self.root/'library'), restore=False)
        project = store.project()
        project['materials'][1].update(Model='table_nk', DataFile='missing.csv')
        original = copy.deepcopy(project)
        def prepare(project, settings):
            project['materials'].clear()
            settings['num_bands'] = 99
            return dict(validated=True)
        with patch('research_simulation.importlib.import_module', return_value=SimpleNamespace(prepare=prepare)):
            saved, job = prepare_job('research_simulation', project, inputs(), store.library)
        self.assertEqual(project, original)
        self.assertEqual(saved, original)
        self.assertIsNone(job['model'])
        self.assertEqual(job['search']['task'], 'research_simulation')
        self.assertEqual(job['search']['settings']['num_bands'], 3)
        self.assertEqual(job['search']['prepared'], {'validated': True})

    def test_shared_run_starts_research_worker_without_unused_optical_assets(self):
        store = ProjectStore(DataLibrary(self.root/'library'), restore=False)
        store.materials.loc[1, ['Model', 'DataFile']] = ['table_nk', 'missing.csv']
        with patch('qt_core.BackendWorker.start') as start:
            store.start_run('research_simulation', inputs())
            start.assert_called_once()
        self.assertEqual(store._worker.kind, 'research_simulation')
        self.assertEqual(store.search_state['research_simulation'], inputs())
        store._finished()

    def test_backend_revalidates_inputs_and_preserves_nonconverged_status(self):
        calls = []
        def prepare(project, settings):
            calls.append(settings)
            return {'actual': 'validated input'}
        def execute(prepared, directory, emit, cancelled):
            self.assertEqual(prepared, {'actual': 'validated input'})
            return {'status': 'unconverged', 'limitations': ['Contract fixture; no physical result.']}
        spec = dict(inputs(), task='research_simulation', project={}, prepared={'actual': 'untrusted'})
        with patch('research_simulation.importlib.import_module', return_value=SimpleNamespace(prepare=prepare, execute=execute)):
            event = execute_research(spec, self.root/'run')
        self.assertEqual(len(calls), 1)
        self.assertEqual(event['summary']['status'], 'unconverged')
        self.assertEqual(json.loads((self.root/'run'/'search_summary.json').read_text())['status'], 'unconverged')

    def test_missing_runtime_and_cancelled_runs_do_not_create_complete_summary(self):
        adapter = SimpleNamespace(prepare=lambda project, settings: {},
            execute=lambda *args: (_ for _ in ()).throw(RuntimeError('Optional runtime is unavailable')))
        with patch('research_simulation.importlib.import_module', return_value=adapter):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                execute_research(dict(inputs(), project={}), self.root/'failed')
        self.assertFalse((self.root/'failed'/'search_summary.json').exists())
        with self.assertRaises(Cancelled):
            execute_research(inputs(), self.root/'cancelled', cancelled=lambda: True)
        self.assertFalse((self.root/'cancelled'/'search_summary.json').exists())


if __name__ == '__main__':
    unittest.main()
