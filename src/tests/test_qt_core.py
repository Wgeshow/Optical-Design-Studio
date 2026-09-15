"""Desktop persistence and real Qt/native-backend lifecycle regressions."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_import_library = tempfile.TemporaryDirectory(prefix='s4_qt_core_import_')
os.environ.setdefault('S4_LIBRARY_ROOT', _import_library.name)

import pandas as pd
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from data_library import DataLibrary, read_json, write_json
from model import MAT_COLS, prepare, performance
from peak_optimizer import BOUND_COLS, parse_search
from qt_core import BackendWorker, ProjectStore, prepare_job


def bound(parameter='thickness', target='Device', low=.2, high=.3, step=.05):
    return dict(zip(BOUND_COLS, [parameter, target, low, high, step, '']))


class QtCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='s4_qt_core_')
        self.addCleanup(self.temporary.cleanup)
        self.library = DataLibrary(self.temporary.name)
        self.store = ProjectStore(self.library, restore=False)
        self.workers = []

    def tearDown(self):
        # Explicitly finish owned threads/processes even when an assertion fails.
        if self.store._worker is not None:
            self.store.cancel()
            deadline = time.monotonic() + 18
            while self.store._worker is not None and time.monotonic() < deadline:
                QTest.qWait(25)
            if self.store._worker is not None:
                self.store._worker._stop_process()
                self.store._worker.wait(5000)
                QTest.qWait(50)
        for worker in self.workers:
            if worker.isRunning():
                worker.cancel()
                worker.wait(18000)
            if worker.isRunning():
                worker._stop_process()
                worker.wait(5000)
            self.assertFalse(worker.isRunning(), 'An owned backend thread remained active.')
        self.app.processEvents()

    def until(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(predicate(), f'Qt task did not finish within {timeout} seconds.')

    def worker(self, kind='simulation', project=None, options=None, cancel=False):
        worker = BackendWorker(kind, project or self.small_project(), options or {}, self.library)
        self.workers.append(worker)
        completed, failed, events = [], [], []
        worker.completed.connect(completed.append)
        worker.failed.connect(failed.append)
        worker.event.connect(events.append)
        if cancel:
            worker.cancel()
        worker.start()
        self.until(lambda: not worker.isRunning(), 35)
        QTest.qWait(50)
        return worker, completed, failed, events

    def small_project(self):
        project = self.store.project()
        project['settings'].update(NumG=9, wl_start_nm=1549, wl_stop_nm=1551, wl_step_nm=1)
        project['performance'].update(mode='CPU only', workers=1, threads=1, chunk_size=1,
                                      timeout_seconds=30, require_gpu=False)
        return project

    def test_library_write_failure_cannot_escape_native_worker_cleanup(self):
        with patch.object(self.library,'record',side_effect=PermissionError('library is read-only')):
            worker,completed,failed,_=self.worker()
        self.assertEqual(completed,[])
        self.assertTrue(any('library is read-only' in error for error in failed))
        self.assertIsNone(worker.process)
        self.assertFalse(worker.isRunning())

    def test_autosave_restore_and_undo_preserve_one_shared_structure(self):
        changes = []
        self.store.changed.connect(changes.append)
        original = self.store.layers.copy()
        changed = self.store.layers.copy()
        changed.loc[1, 'Thickness_um'] = .365
        self.store.set_structure(self.store.materials, changed, self.store.patterns)
        changed.loc[1, 'Thickness_um'] = 99  # Mutating caller input must not mutate the project.
        self.assertAlmostEqual(self.store.layers.iloc[1].Thickness_um, .365)
        restored = ProjectStore(self.library)
        self.assertAlmostEqual(restored.layers.iloc[1].Thickness_um, .365)
        self.assertEqual(changes, ['structure'])
        self.store.undo()
        pd.testing.assert_frame_equal(self.store.layers, original)
        restored = ProjectStore(self.library)
        pd.testing.assert_frame_equal(restored.layers, original)
        self.assertEqual(changes, ['structure', 'structure'])

    def test_failed_structure_autosave_rolls_back_without_emitting_or_growing_undo(self):
        original = self.store.project()
        changed = self.store.layers.copy()
        changed.loc[1, 'Thickness_um'] = .44
        signals = []
        self.store.changed.connect(signals.append)
        with patch.object(self.store, '_autosave', side_effect=PermissionError('read-only test destination')):
            with self.assertRaises(PermissionError):
                self.store.set_structure(self.store.materials, changed, self.store.patterns)
        self.assertEqual(self.store.project(), original)
        self.assertEqual(signals, [])
        self.assertEqual(len(self.store._undo), 0)

    def test_failed_settings_save_preserves_previous_values(self):
        previous = copy.deepcopy(self.store.settings)
        with patch.object(self.store, '_autosave', side_effect=PermissionError('write failed')):
            with self.assertRaises(PermissionError):
                self.store.update_settings({'ax_um': 1.5})
        self.assertEqual(self.store.settings, previous)

    def test_invalid_project_settings_never_mutate_state_save_or_emit(self):
        self.store.update_settings({'ax_um': .81})
        original = self.store.project()
        checkpoint = self.store.session_path.read_bytes()
        changes, library_changes = [], []
        self.store.changed.connect(changes.append)
        self.store.library_changed.connect(lambda: library_changes.append(True))
        invalid = [
            {'settings': {'ax_um': 'bad'}}, {'settings': {'NumG': 3.2}},
            {'settings': {'NumG': True}}, {'settings': {'wl_start_nm': float('nan')}},
            {'settings': {'phi_deg': float('inf')}}, {'settings': {'wl_step_nm': []}},
            {'settings': {'mode': 'unknown'}}, {'settings': {'polarization': 'circular'}},
            {'settings': []}, {'performance': {'workers': 1.5}},
            {'performance': {'timeout_seconds': 2147483648}}, {'performance': {'gpu_block': 65}},
            {'performance': {'gpu_device': {}}}, {'performance': {'require_gpu': 'False'}},
            {'performance': {'mode': 'GPU'}}, {'performance': None},
            {'desktop_search': []}, {'desktop_search': {'target': 'invalid'}},
            {'search': []}, {'desktop_search': {'peaks': {'search_options': []}}},
            {'desktop_search': {'fields': {'grid': 'bad'}}},
            {'desktop_search': {'fields': {'wavelength_nm': float('nan')}}},
            {'desktop_search': {'fields': {'layer': 7}}},
        ]
        for updates in invalid:
            project = copy.deepcopy(original)
            project['layers'][1]['Name'] = 'Would change if partially applied'
            project.update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.store.load_project(project)
            self.assertEqual(self.store.project(), original)
            self.assertEqual(self.store.session_path.read_bytes(), checkpoint)
            self.assertEqual(changes, [])
            self.assertEqual(library_changes, [])

    def test_update_validation_preserves_state_and_normalizes_numeric_scalars(self):
        original = self.store.project()
        for change in ({'ax_um': 'bad'}, {'theta_deg': None}, {'angle_stop': float('inf')},
                       {'mode': 'unknown'}, {'NumG': 1.5}, {'NumG': 2**40}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.store.update_settings(change)
            self.assertEqual(self.store.project(), original)
        for change in ({'threads': True}, {'workers': float('nan')}, {'require_gpu': 1},
                       {'gpu_block': 'invalid'}, {'mode': 'unknown'}, {'timeout_seconds': 2**40}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.store.update_performance(change)
            self.assertEqual(self.store.project(), original)
        self.store.update_settings({'ax_um': '.82', 'NumG': '17'})
        self.store.update_performance({'workers': '1', 'threads': 2.0})
        self.assertEqual(self.store.settings['ax_um'], .82)
        self.assertIsInstance(self.store.settings['ax_um'], float)
        self.assertEqual(self.store.settings['NumG'], 17)
        self.assertIsInstance(self.store.settings['NumG'], int)
        self.assertIsInstance(self.store.performance['workers'], int)
        self.assertIsInstance(self.store.performance['threads'], int)

    def test_incomplete_drafts_load_without_running_material_or_sweep_validation(self):
        project = self.small_project()
        project['settings'].update(wl_start_nm=1600, wl_stop_nm=1500)
        project['performance'].update(workers=2, threads=os.cpu_count() or 1)
        project['layers'][1]['Thickness_um'] = 0
        project['materials'].append(dict(zip(MAT_COLS, ['Draft alloy', 'table_nk', None, None, 'missing.csv', 'nm'])))
        self.store.load_project(project)
        self.assertEqual(self.store.settings['wl_start_nm'], 1600)
        self.assertEqual(self.store.settings['wl_stop_nm'], 1500)
        self.assertEqual(self.store.layers.iloc[1].Thickness_um, 0)
        self.assertEqual(self.store.materials.iloc[-1].DataFile, 'missing.csv')
        self.assertTrue(self.store.session_path.exists())

    def test_corrupt_desktop_restore_keeps_safe_default_state(self):
        project = self.small_project()
        project['settings']['ax_um'] = 'bad'
        project['layers'][1]['Name'] = 'Must not partially load'
        write_json(self.store.session_path, project)
        restored = ProjectStore(self.library, restore=True)
        self.assertIn('ax_um', restored.restore_error)
        self.assertEqual(restored.settings['ax_um'], .77)
        self.assertEqual(restored.layers.iloc[1].Name, 'Device')
        self.assertEqual(restored.search_state, {})

    def test_saved_search_options_are_safe_for_native_control_restoration(self):
        self.store.save_search('fields', {'grid': '7', 'wavelength_nm': '1549.5', 'layer': 'Device'})
        self.assertEqual(self.store.search_state['fields']['grid'], 7)
        self.assertEqual(self.store.search_state['fields']['wavelength_nm'], 1549.5)
        before = copy.deepcopy(self.store.search_state)
        for kind, options in [('fields', {'grid': 'bad'}), ('fields', None),
                              ('target', {'trials': 2.5}), ('target', {'use_fields': 'yes'}),
                              ('peaks', {'search_options': {'search_mode': 'unknown'}})]:
            with self.subTest(kind=kind, options=options), self.assertRaises(ValueError):
                self.store.save_search(kind, options)
            self.assertEqual(self.store.search_state, before)

    def test_project_embeds_wavelength_material_data_and_opens_in_new_library(self):
        source = Path(self.temporary.name) / 'test_alloy.csv'
        source.write_text('wavelength,n,k\n1500,3.4,0.02\n1550,3.5,0.025\n1600,3.6,0.03\n', encoding='utf8')
        material = dict(zip(MAT_COLS, ['Alloy', 'table_nk', None, None, source.name, 'nm']))
        materials = pd.DataFrame([*self.store.materials.to_dict('records'), material], columns=MAT_COLS)
        layers = self.store.layers.copy()
        layers.loc[1, 'Material'] = 'Alloy'
        self.store.files = [str(source)]
        self.store.set_structure(materials, layers, self.store.patterns)
        destination = Path(self.temporary.name) / 'portable.json'
        self.store.save_project(destination)
        project = read_json(destination)
        self.assertEqual(len(project['optical_constants']), 1)
        source.unlink()
        other = DataLibrary(Path(self.temporary.name) / 'shared_copy')
        opened = ProjectStore(other, restore=False)
        opened.load_project(project)
        self.assertEqual(opened.layers.iloc[1].Material, 'Alloy')
        self.assertTrue(all(Path(file).is_file() for file in opened.files))
        _, spec = prepare_job('simulation', opened.portable_project(), {}, other)
        alloy = next(row for row in spec['model']['materials'] if row['name'] == 'Alloy')
        self.assertEqual(alloy['table'][1], [1550.0, 3.5, .025])
        self.assertTrue(any(row['kind'] == 'project' for row in self.library.entries()))

    def test_prepare_simulation_matches_existing_model_contract_and_freezes_snapshot(self):
        project = self.small_project()
        expected = prepare(project['materials'], project['layers'], project['patterns'], [], project['settings'])
        prepared, spec = prepare_job('simulation', project, {}, self.library)
        self.assertEqual(spec['model'], expected)
        self.assertEqual(spec['performance'], performance(project['performance'], 3, os.cpu_count() or 1))
        project['layers'][1]['Thickness_um'] = 9
        project['settings']['ax_um'] = 9
        self.assertEqual(prepared['layers'][1]['Thickness_um'], .25)
        self.assertEqual(spec['model']['layers'][1]['thickness'], .25)
        self.assertEqual(spec['model']['ax'], .77)

    def test_peak_request_preserves_endpoint_and_all_design_constraints(self):
        project = self.small_project()
        project['settings'].update(wl_start_nm=1549, wl_stop_nm=1552, wl_step_nm=1.2)
        options = {'bounds': [bound()], 'search_options': {'search_mode': 'Exhaustive grid',
                                                          'ratio_limit': .55, 'absorption_target': .999}}
        original = copy.deepcopy(options)
        _, spec = prepare_job('peaks', project, options, self.library)
        self.assertEqual(spec['model']['points'][-1][1], 1552)
        cfg = spec['search']
        self.assertEqual(cfg['ratio_limit'], .55)
        self.assertEqual(cfg['absorption_target'], .999)
        self.assertEqual(cfg['design_count'], 3)
        self.assertEqual(options, original)
        self.assertEqual(cfg['dimensions'], parse_search(spec['model'], options['bounds'], options['search_options'])['dimensions'])
        with self.assertRaisesRegex(ValueError, 'Unknown layer'):
            prepare_job('peaks', project, {'bounds': [bound(target='Removed layer')]}, self.library)
        with self.assertRaisesRegex(ValueError, 'Absorption target'):
            prepare_job('peaks', project, {'bounds': [bound()], 'search_options': {'absorption_target': .9}}, self.library)

    def target_options(self):
        return dict(holes=[dict(Layer='Device', Shape='ellipse', MinX_um=.08, MaxX_um=.12,
                                MinY_um=.04, MaxY_um=.09)], bounds=[], target_nm=1550,
                    tolerance_nm=5, min_q=2000, half_window=20, step=3,
                    grid_steps=5, trials=8, initial=2, finalists=1, use_fields=True)

    def test_target_request_uses_user_wavelength_hole_bounds_and_minimum_q(self):
        project = self.small_project()
        options = self.target_options()
        before_project, before_options = copy.deepcopy(project), copy.deepcopy(options)
        converted, spec = prepare_job('target', project, options, self.library)
        cfg = spec['search']
        self.assertEqual(cfg['target_nm'], 1550)
        self.assertEqual(cfg['tolerance_nm'], 5)
        self.assertEqual(cfg['minimum_q'], 2000)
        self.assertTrue(cfg['use_fields'])
        self.assertEqual(cfg['search_mode'], 'ML assisted')
        self.assertEqual([row['parameter'] for row in cfg['dimensions']], ['size_x', 'size_y'])
        self.assertEqual(converted['patterns'][0]['Shape'], 'ellipse')
        wavelengths = [row[1] for row in spec['model']['points']]
        self.assertTrue({1545, 1550, 1555, 1570}.issubset(wavelengths))
        self.assertEqual(project, before_project)
        self.assertEqual(options, before_options)
        for override in ({'tolerance_nm': 20}, {'min_q': 0}, {'field_grid': 31}, {'holes': []}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                prepare_job('target', project, dict(options, **override), self.library)

    def test_fields_validate_grid_and_use_current_snapshot_layer(self):
        project = self.small_project()
        _, spec = prepare_job('fields', project, {'wavelength_nm': 1567, 'layer': 'Device', 'grid': 7}, self.library)
        self.assertEqual(spec['model']['points'], [[0, 1567., 0.]])
        self.assertEqual(spec['search']['layer'], 'Device')
        self.assertEqual(spec['search']['grid'], 7)
        with self.assertRaises(ValueError):
            prepare_job('fields', project, {'grid': 81}, self.library)

    def test_worker_cancel_before_launch_never_creates_or_starts_native_job(self):
        started = time.monotonic()
        worker, completed, failed, _ = self.worker(cancel=True)
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(completed, [])
        self.assertEqual(len(failed), 1)
        self.assertIn('cancelled before launch', failed[0])
        self.assertIsNone(worker.process)
        self.assertIsNone(worker.directory)
        self.assertEqual(list(self.library.runs.iterdir()), [])

    def test_native_cpu_spectrum_completes_without_blocking_qt_and_saves_all_data(self):
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start(20)
        try:
            worker, completed, failed, events = self.worker()
        finally:
            timer.stop()
        self.assertEqual(failed, [])
        self.assertEqual(len(completed), 1)
        self.assertGreater(len(ticks), 2)
        result = completed[0]
        self.assertGreater(result['info']['cpu_gemm_calls'], 0)
        self.assertEqual(result['info']['gpu_gemm_calls'], 0)
        spectrum = pd.read_csv(result['output'])
        self.assertEqual(len(spectrum), 3)
        self.assertTrue(all(abs(spectrum['R'] + spectrum['T'] + spectrum['A'] - 1) < 1e-9))
        self.assertEqual(worker.process.poll(), 0)
        self.assertEqual(read_json(worker.directory / 'library_record.json')['status'], 'complete')
        for name in ('project.json', 'desktop_request.json', 'job.json', 'diagnostics.json', 'results.csv'):
            self.assertTrue((worker.directory / name).is_file(), name)
        self.assertTrue(any(event['kind'] == 'complete' for event in events))

    def test_gpu_diagnostic_reports_actual_native_offload_when_device_present(self):
        command = shutil.which('nvidia-smi')
        if command is None:
            self.skipTest('NVIDIA runtime not present')
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        probe = subprocess.run([command, '-L'], capture_output=True, text=True, timeout=10, creationflags=flags)
        if probe.returncode or 'GPU' not in probe.stdout:
            self.skipTest('No NVIDIA GPU available')
        project = self.small_project()
        project['performance'].update(mode='GPU-assisted (one worker)', gpu_min_n=1024)
        worker, completed, failed, _ = self.worker('diagnostic', project)
        self.assertEqual(failed, [])
        self.assertEqual(len(completed), 1)
        self.assertGreater(completed[0]['info']['gpu_gemm_calls'], 0)
        self.assertEqual(completed[0]['info']['gpu_failures'], 0)
        self.assertIn('GPU connection verified', completed[0]['message'])
        self.assertIn('run threshold remains 1024', completed[0]['message'])
        self.assertEqual(project['performance']['gpu_min_n'], 1024)
        self.assertEqual(worker.process.poll(), 0)

    def test_live_cancel_stops_owned_native_job_and_preserves_cancelled_record(self):
        project = self.small_project()
        project['settings'].update(NumG=101, wl_start_nm=1200, wl_stop_nm=1800, wl_step_nm=.2)
        worker = BackendWorker('simulation', project, {}, self.library)
        self.workers.append(worker)
        failed, completed = [], []
        worker.failed.connect(failed.append)
        worker.completed.connect(completed.append)
        worker.start()
        self.until(lambda: worker.process is not None, 8)
        started = time.monotonic()
        worker.cancel()
        self.until(lambda: not worker.isRunning(), 16)
        QTest.qWait(50)
        self.assertLess(time.monotonic() - started, 16)
        self.assertEqual(completed, [])
        self.assertEqual(len(failed), 1)
        self.assertIsNotNone(worker.process.poll())
        self.assertEqual(read_json(worker.directory / 'library_record.json')['status'], 'cancelled')

    def test_native_backend_error_closes_process_and_marks_saved_run_failed(self):
        project, spec = prepare_job('simulation', self.small_project(), {}, self.library)
        # Model validation normally catches this. Inject a native failure to test
        # the Qt supervisor after it has created a run and launched subprocesses.
        spec['model']['layers'][1]['material'] = 'No such material'
        with patch('qt_core.prepare_job', return_value=(project, spec)):
            worker, completed, failed, _ = self.worker()
        self.assertEqual(completed, [])
        self.assertEqual(len(failed), 1)
        self.assertTrue(failed[0])
        self.assertIsNotNone(worker.process.poll())
        self.assertEqual(read_json(worker.directory / 'library_record.json')['status'], 'error')

    def test_failed_undo_retains_edit_and_can_retry_successfully(self):
        changed = self.store.layers.copy()
        changed.loc[1, 'Thickness_um'] = .41
        self.store.set_structure(self.store.materials, changed, self.store.patterns)
        with patch.object(self.store, '_autosave', side_effect=PermissionError('write failed')):
            with self.assertRaises(PermissionError):
                self.store.undo()
        self.assertEqual(self.store.layers.iloc[1].Thickness_um, .41)
        self.assertEqual(len(self.store._undo), 1)
        self.store.undo()
        self.assertEqual(self.store.layers.iloc[1].Thickness_um, .25)

    def test_validation_failure_releases_store_busy_state_and_allows_next_task(self):
        states, failures, finished = [], [], []
        self.store.busy_changed.connect(states.append)
        self.store.run_failed.connect(failures.append)
        self.store.task_finished.connect(lambda name, result: finished.append((name, result)))
        self.store.start_run('target', {'holes': []})
        self.assertTrue(self.store.busy)
        self.until(lambda: not self.store.busy, 8)
        self.assertEqual(states, [True, False])
        self.assertEqual(len(failures), 1)
        self.assertIsNone(self.store._worker)
        self.store.run_task('follow-up', lambda: 42)
        self.until(lambda: not self.store.busy)
        self.assertEqual(finished, [('follow-up', 42)])

    def test_task_error_cleans_up_busy_state(self):
        failures = []
        self.store.task_failed.connect(lambda name, error: failures.append((name, error)))
        def fail():
            raise ValueError('Deliberate test error')
        self.store.run_task('test failure', fail)
        self.until(lambda: not self.store.busy)
        self.assertEqual(failures, [('test failure', 'Deliberate test error')])
        self.assertIsNone(self.store._worker)


if __name__ == '__main__':
    unittest.main()
