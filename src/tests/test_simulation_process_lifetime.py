"""Mocked process lifetime contracts; never execute a scientific solver."""
import json
from importlib.util import find_spec
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, call, patch

import numpy as np
import meep_runtime


class ProcessLifetimeTests(unittest.TestCase):
    def process(self, mode='local'):
        process = meep_runtime.ManagedProcess.__new__(meep_runtime.ManagedProcess)
        process.config = dict(mode=mode, distro='Test')
        process.linux_pid = None
        process.lines = Mock()
        process.process = Mock()
        process.process.wait.return_value = 0
        process.terminate = Mock()
        return process

    def test_default_and_zero_survive_more_than_one_day(self):
        for timeout in (None, 0):
            process = self.process()
            process.lines.get.side_effect = ['retained output\n', None]
            with patch('meep_runtime.time.monotonic', side_effect=[0., 90000., 90001.]):
                self.assertEqual(list(process.stream(threading.Event(), timeout=timeout)), ['retained output\n'])
            process.terminate.assert_not_called()

    def test_explicit_installation_bound_terminates(self):
        process = self.process()
        with patch('meep_runtime.time.monotonic', side_effect=[0., 7201.]):
            with self.assertRaises(TimeoutError):
                list(process.stream(threading.Event(), timeout=7200))
        process.terminate.assert_called_once_with(force=True)

    def test_invalid_explicit_bounds_rejected(self):
        for value in (-1, float('nan'), float('inf'), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                list(self.process().stream(threading.Event(), timeout=value))

    def test_cancellation_retains_grace_then_forced_termination(self):
        process = self.process()
        process.lines.get.side_effect = [queue.Empty, None]
        event = threading.Event(); event.set()
        with patch('meep_runtime.time.monotonic', side_effect=[0., 1., 7.]):
            self.assertEqual(list(process.stream(event)), [])
        self.assertEqual(process.terminate.call_args_list, [call(), call(force=True)])

    def test_wsl_cancellation_waits_for_child_pid_then_terminates_group(self):
        process = self.process('wsl')
        process.lines.get.side_effect = ['ODS_MEEP_PID=44\n', queue.Empty, None]
        event = threading.Event(); event.set()
        with patch('meep_runtime.time.monotonic', side_effect=[0., 1., 1.5, 6.1]):
            self.assertEqual(list(process.stream(event)), [])
        self.assertEqual(process.linux_pid, 44)
        self.assertEqual(process.terminate.call_args_list, [call(), call(force=True)])

    def test_meep_installer_retains_explicit_bound(self):
        from qt_fdtd import _RuntimeTask
        process = Mock(); process.stream.return_value = []; process.process.wait.return_value = 0
        with patch('qt_fdtd.meep_runtime.ManagedProcess', return_value=process), \
             patch('qt_fdtd.meep_runtime.install_command', return_value=['mock installer']), \
             patch('qt_fdtd.meep_runtime.probe', return_value={'available': False}):
            task = _RuntimeTask(dict(mode='local'), install=True)
            task.run()
        process.stream.assert_called_once_with(task.cancelled, timeout=7200)

    def test_mpb_simulation_omits_legacy_timeout(self):
        import photonic_bands as bands
        process = Mock(); process.stream.return_value = []; process.process.poll.return_value = 0; process.process.returncode = 0
        prepared = dict(solver='mpb', runtime=dict(mode='local', executable='mock-mpb', timeout_s=1.), dimension=2, polarizations=['te'])
        with tempfile.TemporaryDirectory() as directory, \
             patch('meep_runtime.ManagedProcess', return_value=process), \
             patch.object(bands, 'control_file', return_value=''), \
             patch.object(bands, 'k_path', return_value=(np.zeros((1, 3)), np.zeros(1))), \
             patch.object(bands, 'parse_frequencies', return_value={}), \
             patch.object(bands, '_save_result', return_value={'status': 'mocked'}):
            self.assertEqual(bands.execute(prepared, directory)['status'], 'mocked')
        self.assertEqual(process.stream.call_args.kwargs, {})

    def research_fixture(self, directory, mode):
        (Path(directory)/'engine_result.json').write_text(json.dumps({'status': 'complete'}))
        return dict(runtime=dict(mode=mode, executable='/mock/python' if mode=='wsl' else 'mock-python', timeout_s=1.), worker_engine='sesame_transport')

    @patch('research_physics_runtime.__file__', find_spec('research_physics_worker').origin)
    def test_wsl_scientific_worker_omits_legacy_timeout(self):
        from research_physics_runtime import run_worker
        process = Mock(); process.stream.return_value = []; process.process.poll.return_value = 0; process.process.returncode = 0
        with tempfile.TemporaryDirectory() as directory, \
             patch('meep_runtime.ManagedProcess', return_value=process), \
             patch('meep_runtime.linux_path', side_effect=lambda path, cfg: '/mock/'+Path(path).name), \
             patch('meep_runtime.wsl_executable', return_value='mock-wsl'):
            result = run_worker(self.research_fixture(directory, 'wsl'), directory)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(process.stream.call_args.kwargs, {})

    @patch('research_physics_runtime.__file__', find_spec('research_physics_worker').origin)
    def test_local_scientific_worker_survives_legacy_limit(self):
        from research_physics_runtime import run_worker
        process = Mock(); process.stdout = iter([]); process.poll.return_value = 0; process.wait.return_value = 0
        with tempfile.TemporaryDirectory() as directory, \
             patch('research_physics_runtime.subprocess.Popen', return_value=process), \
             patch('research_physics_runtime.time.monotonic', side_effect=[0., 90000.]):
            result = run_worker(self.research_fixture(directory, 'local'), directory)
        self.assertEqual(result['status'], 'complete')
        process.terminate.assert_not_called()

    @patch('research_physics_runtime.__file__', find_spec('research_physics_worker').origin)
    def test_local_scientific_cancellation_still_terminates(self):
        from research_physics_runtime import run_worker
        process = Mock(); process.stdout = iter([]); process.poll.return_value = None; process.wait.return_value = 0
        with tempfile.TemporaryDirectory() as directory, \
             patch('research_physics_runtime.subprocess.Popen', return_value=process):
            with self.assertRaises(InterruptedError):
                run_worker(self.research_fixture(directory, 'local'), directory, cancelled=Mock(side_effect=[False, True]))
        process.terminate.assert_called_once()

    def test_saved_performance_limits_normalize_to_unlimited(self):
        from model import DEFAULT_PERFORMANCE, performance
        from qt_core import desktop_performance
        self.assertEqual(DEFAULT_PERFORMANCE['timeout_seconds'], 0)
        self.assertEqual(performance(dict(timeout_seconds=1), 1, 8)['timeout_seconds'], 0)
        self.assertEqual(desktop_performance(dict(timeout_seconds=3600))['timeout_seconds'], 0)


    def test_native_spectrum_supervisor_survives_legacy_limit_without_worker(self):
        import itertools
        import backend
        from model import DEFAULT_PERFORMANCE
        parent, child, process, context = Mock(), Mock(), Mock(), Mock()
        context.Pipe.return_value = (parent, child); context.Process.return_value = process
        process.pid = 7; process.is_alive.side_effect = [True, True, False, False, False]
        row = [0, 1550., 0., .1, .9, 0.]
        parent.recv.side_effect = [dict(kind='ready', pid=7, gpu=False, module='mock'),
            dict(kind='result', rows=[row], status='mock', **dict.fromkeys(backend.COUNTERS, 0))]
        with patch('backend.mp.get_context', return_value=context), \
             patch('backend.wait', side_effect=[[parent], [parent]]), \
             patch('backend.time.monotonic', side_effect=itertools.count(0, 90000).__next__):
            rows, info = backend.execute(dict(points=[[0,1550.,0.]]), dict(DEFAULT_PERFORMANCE, workers=1, timeout_seconds=1))
        self.assertEqual(rows, [row]); self.assertGreater(info['elapsed_seconds'], 86400)
        process.terminate.assert_not_called()

    def test_field_worker_and_reused_session_survive_legacy_limit(self):
        import itertools
        import field_solver
        context, parent, child, process = Mock(), Mock(), Mock(), Mock()
        context.Pipe.return_value = (parent, child); context.Process.return_value = process
        parent.poll.side_effect = [False, True]; parent.recv.return_value = {'result': {'mocked': True}}
        process.pid = 7; process.is_alive.side_effect = [True, False, False]
        cfg = dict(wavelength_nm=1550., grid=3, depth_samples=3)
        with patch('field_solver.mp.get_context', return_value=context), \
             patch('field_solver.time.monotonic', side_effect=itertools.count(0, 90000).__next__):
            self.assertEqual(field_solver.execute_fields({}, dict(timeout_seconds=1), cfg, '/mock'), {'mocked': True})
        parent.poll.side_effect = [False, True]; process.is_alive.side_effect = None; process.is_alive.return_value = True
        session = field_solver.FieldSession.__new__(field_solver.FieldSession)
        session.parent, session.process = parent, process
        with patch('field_solver.time.monotonic', side_effect=itertools.count(0, 90000).__next__):
            self.assertEqual(session(dict(points=[[0,1550.,0.]]), dict(timeout_seconds=1), cfg, '/mock'), {'mocked': True})

    def desktop_worker(self, kind, elapsed):
        import qt_core
        with tempfile.TemporaryDirectory() as directory:
            library = Mock(); library.runs = Path(directory)
            process = Mock(); process.stdout = Mock(); process.poll.return_value = 0; process.wait.return_value = 0; process.returncode = 0
            messages = Mock(); messages.get.side_effect = [dict(kind='complete', summary={'status': 'complete'}), None]
            worker = qt_core.BackendWorker(kind, {}, {}, library)
            done, errors = [], []; worker.completed.connect(done.append); worker.failed.connect(errors.append)
            with patch('qt_core.prepare_job', return_value=({'materials': []}, {'performance': {'timeout_seconds': 1}})), \
                 patch('qt_core.backend_command', return_value=['mock backend']), \
                 patch('qt_core.subprocess.Popen', return_value=process), \
                 patch('qt_core.threading.Thread'), patch('qt_core.queue.Queue', return_value=messages), \
                 patch('qt_core.time.monotonic', side_effect=elapsed):
                worker.run()
            return done, errors

    def test_desktop_simulation_fields_sweep_and_ai_ignore_elapsed_limit(self):
        for kind in ('simulation', 'fields', 'index_shift', 'peaks', 'ai_search'):
            with self.subTest(kind=kind):
                done, errors = self.desktop_worker(kind, [0., 90000., 90001.])
                self.assertEqual(errors, []); self.assertEqual(len(done), 1)

    def test_availability_diagnostic_retains_deliberate_bound(self):
        done, errors = self.desktop_worker('diagnostic', [0., 76.])
        self.assertFalse(done); self.assertEqual(errors, ['Runtime diagnostic exceeded its time limit.'])


    def test_explicit_sweep_keeps_work_budget_without_elapsed_budget(self):
        import itertools
        from test_backend import sample
        from peak_optimizer import parse_search, execute_search
        from model import DEFAULT_PERFORMANCE
        base = sample()
        cfg = parse_search(base, [], dict(refinement_rounds=0))
        def executor(model, perf, emit, cancelled):
            self.assertEqual(perf['timeout_seconds'], 0)
            return [[i, wl, theta, .5, .4, .1] for i, wl, theta in model['points']], {}
        with tempfile.TemporaryDirectory() as directory, \
             patch('peak_optimizer.time.monotonic', side_effect=itertools.count(0, 90000).__next__):
            result = execute_search(base, dict(DEFAULT_PERFORMANCE, timeout_seconds=1), cfg, directory, executor, lambda event: None, lambda: False)
        self.assertEqual(result['summary']['evaluated'], 1)

    def test_ai_search_continues_after_legacy_elapsed_budget(self):
        import itertools
        from test_ml_optimizer import MLTests, config
        fixture = MLTests(); fixture.setUp(); calls = []
        cfg = config(fixture.base, initial_designs=2, ml_trials=2, design_budget=2, refinement_rounds=0)
        with patch('ml_optimizer.time.monotonic', side_effect=itertools.count(0, 90000).__next__):
            summary, history, records = fixture.run_search(cfg, calls)
        self.assertEqual(len([row for row in history['observations'] if row['phase']=='exploration']), 2)
        self.assertGreaterEqual(len(calls), 2)


    def test_target_search_default_zero_runs_and_preserves_point_budget(self):
        import itertools
        from test_target_fields import TargetTests, spectrum, fields
        from target_optimizer import execute_target_search
        from model import DEFAULT_PERFORMANCE
        fixture = TargetTests(); fixture.setUp()
        cfg = dict(fixture.cfg, ml_trials=2, initial_designs=2, refinement_rounds=0, finalists=1)
        calls = []
        def executor(model, perf, emit, cancelled):
            self.assertEqual(perf['timeout_seconds'], 0); calls.append(model)
            return spectrum(model, perf, emit, cancelled)
        def field_executor(model, perf, options, directory, cancelled):
            self.assertEqual(perf['timeout_seconds'], 0)
            return fields(model, perf, options, directory, cancelled)
        with tempfile.TemporaryDirectory() as directory, \
             patch('target_optimizer.time.monotonic', side_effect=itertools.count(0, 90000).__next__):
            result = execute_target_search(fixture.base, dict(DEFAULT_PERFORMANCE), cfg, directory, executor, lambda event: None, lambda: False, field_executor)
        self.assertGreater(len(calls), 0)
        self.assertNotIn('time budget', str(result).lower())
        calls.clear()
        with tempfile.TemporaryDirectory() as directory:
            result = execute_target_search(fixture.base, dict(DEFAULT_PERFORMANCE), dict(cfg, point_budget=1), directory, executor, lambda event: None, lambda: False, field_executor)
        self.assertFalse(calls); self.assertEqual(result['summary']['status'], 'partial')


class UnlimitedRuntimeUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_runtime_forms_preserve_legacy_metadata_but_show_unlimited(self):
        from PyQt6 import sip
        from PyQt6.QtWidgets import QLabel
        from data_library import DataLibrary
        from qt_core import ProjectStore
        from qt_photonic_bands import PhotonicBandsWorkspace
        from qt_sesame_setup import SesameSetupWorkspace
        with tempfile.TemporaryDirectory() as directory:
            for number, workspace in enumerate((PhotonicBandsWorkspace, SesameSetupWorkspace)):
                store = ProjectStore(DataLibrary(Path(directory)/str(number)), restore=False)
                page = workspace(store)
                try:
                    page.timeout.setText('4321')
                    self.assertEqual(page.runtime_settings()['timeout_s'], 4321.)
                    form = page.advanced_solver_form if workspace is PhotonicBandsWorkspace else page.solver_advanced.layout()
                    self.assertFalse(form.isRowVisible(page.timeout))
                    self.assertTrue(any(w.text() == 'None. Use Stop to cancel.' for w in page.findChildren(QLabel)))
                finally:
                    page._save_timer.stop(); sip.delete(page)

    def test_pcsel_runtime_timeout_is_read_only_unlimited(self):
        from PyQt6 import sip
        from PyQt6.QtWidgets import QLabel
        from qt_research_studies import StructuredValueEditor
        from qt_pcsel_research_setup import TreeForm
        editor = StructuredValueEditor(dict(timeout_s=4321., executable='/mock/python'), 'runtime')
        form = TreeForm(editor)
        try:
            form.set_node(editor.tree.topLevelItem(0))
            self.assertIsInstance(form.controls['timeout_s'], QLabel)
            self.assertEqual(form.controls['timeout_s'].text(), 'None. Use Stop to cancel.')
            self.assertEqual(editor.value()['timeout_s'], 4321.)
        finally:
            sip.delete(form); sip.delete(editor)


    def test_live_optical_accuracy_shows_readonly_elapsed_policy(self):
        from PyQt6 import sip
        from PyQt6.QtWidgets import QLabel
        from data_library import DataLibrary
        from qt_core import ProjectStore
        from qt_simulation_setup import SimulationSetupWorkspace
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectStore(DataLibrary(directory), restore=False)
            store.study_navigation_enabled = True; store.activate_study('optical')
            import simulation_setup_state as setup_state
            setup_state._plan.cache_clear()
            with patch.object(setup_state, '__file__', str(Path(__file__).resolve().parents[1]/'simulation_setup_state.py')):
                page = SimulationSetupWorkspace(store, mode='optical', document_id='optical')
            try:
                key = 'ui.optical.elapsed_time_limit'
                editor = page.widgets_by_key[key][0]
                self.assertIsInstance(editor, QLabel)
                self.assertEqual(page.state.get(key), 'None. Use Stop to cancel.')
                self.assertNotIn('performance.timeout_seconds', page.widgets_by_key)
            finally:
                sip.delete(page)
                setup_state._plan.cache_clear()


if __name__ == '__main__':
    unittest.main()
