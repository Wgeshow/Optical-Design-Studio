"""FDTD Qt controls and setup lifecycle, without downloading any runtime."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication, QLabel
from qt_fdtd import FDTDPage, MeepRuntimeSettings, MeepWorker


class Store(QObject):
    library_changed = pyqtSignal()
    library = SimpleNamespace(entries=lambda: [])
    busy_changed = pyqtSignal(bool)
    progress = pyqtSignal(dict)
    run_finished = pyqtSignal(dict)
    run_failed = pyqtSignal(str)
    busy = False
    search_state = {}
    def cancel(self):
        self.cancelled = True
    def start_run(self, kind, options):
        self.started = kind, options
        self.busy_changed.emit(True)


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_monitor_decay_label_tooltip_and_numeric_default(self):
        page = FDTDPage(Store())
        self.assertIn('Monitor field decay target', [label.text() for label in page.findChildren(QLabel)])
        self.assertNotIn('Field energy decay target', [label.text() for label in page.findChildren(QLabel)])
        tooltip = page.controls['decay_by'].toolTip()
        for text in ('squared amplitude', 'transmission plane', '20 µm/c', 'not domain-integrated energy'):
            self.assertIn(text, tooltip)
        self.assertEqual(page.options()['decay_by'], 1e-7)
        page.deleteLater()

    def test_dimension_changes_section_control(self):
        page = FDTDPage(Store())
        page.controls['dimensions'].setCurrentIndex(1)
        self.assertFalse(page.controls['section_y_um'].isEnabled())
        self.assertEqual(page.options()['dimensions'], 3)
        page.controls['dimensions'].setCurrentIndex(0)
        self.assertTrue(page.controls['section_y_um'].isEnabled())
        page.deleteLater()

    def test_live_timing_phase_reset_stop_and_terminal_lifecycle(self):
        store = Store()
        page = FDTDPage(store)
        with patch('qt_fdtd.time.monotonic', return_value=100):
            page.run()
        self.assertTrue(page._timing_timer.isActive())
        with patch('qt_fdtd.time.monotonic', return_value=105):
            page._update_timing()
        self.assertIn('elapsed 5s', page.timing_status.text())
        for i in range(3):
            with patch('qt_fdtd.time.monotonic', return_value=106+i):
                page._progress(dict(run_kind='fdtd', phase='Reference', time=10+10*i,
                    phase_budget_time=100, phase_elapsed_seconds=1+i, message='Reference'))
        self.assertIn('~7s', page.timing_status.text())
        self.assertEqual(page.progress.value(), 30)
        with patch('qt_fdtd.time.monotonic', return_value=110):
            page._progress(dict(run_kind='fdtd', phase='Device', message='Initializing Device'))
        self.assertIn('Device (2/2)', page.timing_status.text())
        self.assertNotIn('~7s', page.timing_status.text())
        page.stop_button.click()
        self.assertTrue(store.cancelled)
        page._finished(dict(run_kind='fdtd', status='cancelled'))
        self.assertFalse(page._timing_timer.isActive())
        self.assertFalse(page._active)
        page.run()
        page._failed('Expected failure')
        self.assertFalse(page._timing_timer.isActive())
        self.assertIsNone(page._run_started)
        page.deleteLater()

    def test_estimate_lookup_is_asynchronous_and_discards_changed_input_result(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        def lookup(*args, **kwargs):
            entered.set()
            release.wait(3)
            return dict(seconds=120, run='fdtd_cached')
        store = Store()
        store.project = lambda: dict(materials=[], layers=[], patterns=[], settings={})
        store.library = SimpleNamespace(entries=lambda: [], runs=Path('unused'))
        page = FDTDPage(store)
        with patch('qt_fdtd.cached_estimate', side_effect=lookup), \
             patch('qt_fdtd.meep_runtime.load_config', return_value={}), \
             patch('qt_fdtd.meep_runtime.probe') as probe, patch('qt_fdtd.build_job') as build:
            page.estimate_button.click()
            worker = page._estimate_worker
            self.assertIsNotNone(worker)
            self.assertTrue(entered.wait(1))
            responsive = []
            QTimer.singleShot(0, lambda: responsive.append(True))
            self.app.processEvents()
            self.assertEqual(responsive, [True])
            self.assertIn('Checking saved', page.timing_status.text())
            generation = page._estimate_generation
            page.controls['resolution'].setValue(41)
            self.assertGreater(page._estimate_generation, generation)
            release.set()
            self.assertTrue(worker.wait(2000))
            self.app.processEvents()
            self.assertNotIn('~2m', page.timing_status.text())
            self.assertTrue(page.estimate_button.isEnabled())
            probe.assert_not_called(); build.assert_not_called()
        page._estimated_runtime(dict(generation=page._estimate_generation, estimate=None))
        self.assertIn('Run once to calibrate', page.timing_status.text())
        page._estimated_runtime(dict(generation=page._estimate_generation, estimate={'seconds':120}))
        self.assertIn('~2m', page.timing_status.text())
        self.assertIn('speed and setup overhead can vary', page.timing_status.text())
        page.deleteLater()

    def test_saved_peak_selection_uses_cached_samples_without_solver(self):
        import tempfile
        from pathlib import Path
        import pandas as pd
        import numpy as np
        store = Store()
        page = FDTDPage(store)
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'start_run') as start:
            path = Path(folder) / 'results.csv'
            pd.DataFrame(dict(wavelength_nm=[1500, 1501, 1502], R=[.8, .1, .2],
                T=[.1, .7, .2], A=[.1, .2, .6])).to_csv(path, index=False)
            page._finished(dict(run_kind='fdtd', directory=folder))
            for key, row in [('R', 0), ('T', 1), ('A', 2)]:
                page.peak_quantity.setCurrentIndex(page.peak_quantity.findData(key))
                self.assertIn(str(1500 + row), page.peak_summary.text())
                self.assertEqual(page.samples.currentRow(), row)
                self.assertEqual(float(page.plot.figure.axes[0].collections[0].get_offsets()[0, 0]), 1500 + row)
            pd.DataFrame(dict(wavelength_nm=[1600], A=[.9])).to_csv(path, index=False)
            with patch('qt_fdtd.QFileDialog.getOpenFileName', return_value=(str(path), '')):
                page.load_results()
            self.assertIn('1600', page.peak_summary.text())
            self.assertEqual(page.samples.rowCount(), 1)
            page.peak_quantity.setCurrentIndex(0)
            self.assertIn('No finite', page.peak_summary.text())
            page.result_frame = pd.DataFrame(dict(wavelength_nm=[1600, 1601], R=[np.nan, np.inf]))
            page.update_peak()
            self.assertIn('No finite', page.peak_summary.text())
            start.assert_not_called()
        page.deleteLater()

    def test_run_dispatch_and_error_restores_panel(self):
        store = Store()
        page = FDTDPage(store)
        page.run()
        self.assertEqual(store.started[0], 'fdtd')
        self.assertTrue(page.stop_button.isEnabled())
        store.run_failed.emit('A useful solver error')
        self.assertEqual(page.status.text(), 'A useful solver error')
        self.assertFalse(page._active)
        page.deleteLater()

    def test_runtime_change_invalidates_finished_and_pending_estimates(self):
        page = FDTDPage(Store())
        generation = page._estimate_generation
        page._estimated_runtime(dict(generation=generation, estimate={'seconds':120}))
        self.assertIn('~2m', page.timing_status.text())
        page.refresh_runtime(dict(available=True, message='Different runtime ready'))
        self.assertGreater(page._estimate_generation, generation)
        self.assertIn('Estimate runtime again', page.timing_status.text())
        pending_generation = page._estimate_generation
        page.timing_status.setText('Checking saved timing data…')
        page.refresh_runtime(dict(available=True, message='Another runtime ready'))
        page._estimated_runtime(dict(generation=pending_generation, estimate={'seconds':600}))
        self.assertIn('Estimate runtime again', page.timing_status.text())
        self.assertNotIn('~10m', page.timing_status.text())
        page.deleteLater()

    def test_worker_reports_original_failure_when_cleanup_and_recording_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            library = Mock(runs=Path(folder))
            library.files_for.return_value = []
            library.record.side_effect = [None, OSError('library disk full')]
            managed = Mock()
            managed.stream.side_effect = RuntimeError('solver connection lost')
            managed.terminate.side_effect = OSError('process cleanup denied')
            worker = MeepWorker('fdtd', {}, {}, library)
            failed = QSignalSpy(worker.failed)
            completed = QSignalSpy(worker.completed)
            with patch('qt_fdtd.meep_runtime.load_config', return_value={}), \
                 patch('qt_fdtd.meep_runtime.probe', return_value={'available': True}), \
                 patch('qt_fdtd.build_job', return_value={}), \
                 patch('qt_fdtd.meep_runtime.copy_runner', return_value=Path(folder)/'runner.py'), \
                 patch('qt_fdtd.meep_runtime.linux_path', side_effect=lambda path, config: str(path)), \
                 patch('qt_fdtd.meep_runtime.command', return_value=[]), \
                 patch('qt_fdtd.meep_runtime.ManagedProcess', return_value=managed):
                worker.start()
                self.assertTrue(worker.wait(5000), 'Meep worker did not finish')
                self.app.processEvents()
            self.assertEqual(len(failed), 1)
            self.assertEqual(len(completed), 0)
            error = failed[0][0]
            self.assertTrue(error.startswith('solver connection lost'))
            self.assertIn('process cleanup denied', error)
            self.assertIn('library disk full', error)
            managed.terminate.assert_called_once_with(force=True)
            self.assertEqual(library.record.call_count, 2)

    def test_measured_budget_receipt_keeps_complete_distinct_from_convergence(self):
        import json
        from fdtd_progress import cached_estimate, timing_key
        messages = []
        for phase in ('Reference', 'Device'):
            for i in range(3):
                messages.append(dict(kind='progress', phase=phase, time=10*(i+1),
                    phase_budget_time=100, phase_elapsed_seconds=i+1, message=phase))
            messages.append(dict(kind='phase_complete', phase=phase, phase_elapsed_seconds=4,
                decay_reached=False, message='time limit'))
        warning = 'Device: maximum post-source runtime reached before the field-decay target.'
        messages.append(dict(kind='complete', info=dict(convergence={'Reference':False,'Device':False}, warnings=[warning])))
        with tempfile.TemporaryDirectory() as folder:
            library = Mock(runs=Path(folder))
            library.files_for.return_value = []
            managed = Mock()
            managed.stream.return_value = ['ODS_MEEP '+json.dumps(item)+'\n' for item in messages]
            managed.process.wait.return_value = 0
            worker = MeepWorker('fdtd', {}, {}, library)
            completed, failed = QSignalSpy(worker.completed), QSignalSpy(worker.failed)
            with patch('qt_fdtd.meep_runtime.load_config', return_value={}), \
                 patch('qt_fdtd.meep_runtime.probe', return_value={'available': True}), \
                 patch('qt_fdtd.build_job', return_value={}), \
                 patch('qt_fdtd.meep_runtime.copy_runner', return_value=Path(folder)/'runner.py'), \
                 patch('qt_fdtd.meep_runtime.linux_path', side_effect=lambda path, config: str(path)), \
                 patch('qt_fdtd.meep_runtime.command', return_value=[]), \
                 patch('qt_fdtd.meep_runtime.ManagedProcess', return_value=managed):
                worker.run()
            self.assertEqual(len(failed), 0)
            self.assertEqual(completed[0][0]['status'], 'complete')
            self.assertEqual(completed[0][0]['info']['convergence'], {'Reference':False,'Device':False})
            self.assertIn(warning, completed[0][0]['info']['warnings'])
            estimate = cached_estimate(folder, timing_key({}, {}, {}))
            self.assertIsNotNone(estimate)
            self.assertGreaterEqual(estimate['seconds'], 20)

    def test_estimate_worker_survives_page_deletion(self):
        import threading
        from PyQt6 import sip
        entered, release = threading.Event(), threading.Event()
        def lookup(*args, **kwargs):
            entered.set(); release.wait(3)
            return None
        store = Store()
        store.project = lambda: {}
        store.library = SimpleNamespace(entries=lambda: [], runs=Path('unused'))
        page = FDTDPage(store)
        with patch('qt_fdtd.cached_estimate', side_effect=lookup), \
             patch('qt_fdtd.meep_runtime.load_config', return_value={}):
            page.estimate_runtime()
            worker = page._estimate_worker
            self.assertTrue(entered.wait(1))
            self.assertIs(worker.parent(), self.app)
            self.assertFalse(page.stop_runtime_estimate())
            self.assertTrue(worker.isInterruptionRequested())
            sip.delete(page)
            release.set()
            self.assertTrue(worker.wait(2000))
            self.app.processEvents()

    def test_window_close_defers_without_blocking_for_cached_lookup(self):
        from qt_app import OpticalStudio
        window = SimpleNamespace(fdtd_page=SimpleNamespace(stop_runtime_estimate=lambda:False),
            status=QLabel(), close=Mock())
        event = Mock()
        with patch('qt_app.QTimer.singleShot') as retry:
            OpticalStudio.closeEvent(window, event)
        event.ignore.assert_called_once()
        retry.assert_called_once_with(200, window.close)
        self.assertIn('cached runtime lookup', window.status.text())

    def test_settings_does_not_probe_or_install_on_open(self):
        with patch('meep_runtime.probe') as probe, patch('meep_runtime.install_command') as install:
            panel = MeepRuntimeSettings()
            probe.assert_not_called()
            install.assert_not_called()
            self.assertFalse(panel.is_busy())
            self.assertTrue(panel.shutdown())
            self.assertTrue(panel.expert.isHidden())
            self.assertEqual(panel.install_button.text(), 'Install FDTD engine')
            panel.deleteLater()

    def test_windows_setup_requires_explicit_confirmation(self):
        from PyQt6.QtWidgets import QMessageBox
        with patch('qt_fdtd.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel), \
             patch('meep_managed.setup_windows_support') as setup:
            panel = MeepRuntimeSettings()
            panel.setup_windows()
            setup.assert_not_called()
            panel.deleteLater()


if __name__ == '__main__':
    unittest.main()
