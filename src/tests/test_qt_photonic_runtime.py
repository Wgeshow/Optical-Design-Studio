"""Check runtime argument isolation and asynchronous readiness state."""
import os
import sys
import unittest
from meep_runtime import wsl_executable
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QProcess
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from qt_photonic_runtime import PhotonicRuntimeCheck, probe_command

APP = QApplication.instance() or QApplication([])


class RuntimeCheckTests(unittest.TestCase):
    def test_wsl_command_keeps_paths_as_arguments(self):
        command, _ = probe_command(dict(solver='mpb', runtime=dict(mode='wsl', distro='Ubuntu Test', executable='/opt/my solver/mpb')))
        self.assertEqual(command, [wsl_executable(), '--distribution', 'Ubuntu Test', '--exec', '/opt/my solver/mpb', '--version'])
        with self.assertRaises(ValueError):
            probe_command(dict(solver='mpb', runtime=dict(mode='wsl', executable='mpb\nother')))

    def test_legume_path_is_data_and_probe_checks_required_classes(self):
        folder = "C:/study's solver; files"
        command, _ = probe_command(dict(solver='legume', runtime=dict(mode='local', executable=sys.executable, module_paths=[folder])))
        compile(command[-1], '<probe>', 'exec')
        self.assertIn('from legume import PhotCryst, PlaneWaveExp', command[-1])
        self.assertEqual(command[:2], [sys.executable, '-c'])

    def test_actual_process_response_and_setting_change_invalidate_readiness(self):
        widget = PhotonicRuntimeCheck(lambda: dict(solver='mpb', runtime={}))
        with patch('qt_photonic_runtime.probe_command', return_value=([sys.executable, '-c', 'print("MPB 1.12.0")'], {})):
            widget.check()
            for _ in range(100):
                if not widget._running:
                    break
                QTest.qWait(20)
        self.assertIn('MPB is available', widget.status.text())
        widget.invalidate()
        self.assertIn('not checked', widget.status.text())
        widget.deleteLater()

    def test_exit_zero_without_solver_marker_is_not_ready(self):
        widget = PhotonicRuntimeCheck(lambda: {})
        widget._running = True
        widget._checked_revision = widget._revision
        widget._solver = 'mpb'
        widget._output = 'unrelated executable'
        widget._finished(0, QProcess.ExitStatus.NormalExit)
        self.assertIn('Could not verify', widget.status.text())
        widget.deleteLater()

    def test_changed_setup_cannot_accept_old_process_result(self):
        widget = PhotonicRuntimeCheck(lambda: {})
        widget._running = True
        widget._checked_revision = widget._revision
        widget._solver = 'mpb'
        widget._output = 'MPB 1.12.0'
        widget.invalidate()
        widget._finished(0, QProcess.ExitStatus.NormalExit)
        self.assertIn('changed', widget.status.text())
        self.assertNotIn('is available', widget.status.text())
        widget.deleteLater()

    def test_cancelled_process_cannot_be_reused_before_it_has_exited(self):
        widget = PhotonicRuntimeCheck(lambda: dict(solver='mpb', runtime={}))
        with patch('qt_photonic_runtime.probe_command', return_value=([sys.executable, '-c', 'import time; time.sleep(10); print("MPB old")'], {})) as command:
            widget.check()
            self.assertTrue(widget.process.waitForStarted(2000))
            widget.invalidate()
            widget.check()
            self.assertEqual(command.call_count, 1)
            self.assertFalse(widget.check_button.isEnabled())
            for _ in range(100):
                QTest.qWait(20)
                if widget.process.state() == QProcess.ProcessState.NotRunning:
                    break
        self.assertTrue(widget.check_button.isEnabled())
        with patch('qt_photonic_runtime.probe_command', return_value=([sys.executable, '-c', 'print("MPB new")'], {})):
            widget.check()
            for _ in range(100):
                QTest.qWait(20)
                if not widget._running:
                    break
        self.assertIn('MPB is available', widget.status.text())
        widget.deleteLater()


class RuntimeDiscoveryTests(unittest.TestCase):
    def test_discovery_uses_optional_hints_not_strict_run_validation(self):
        def strict():
            raise ValueError('Enter an explicit runtime executable.')
        widget = PhotonicRuntimeCheck(strict, get_discovery_settings=lambda: dict(
            solver='legume', runtime=dict(mode='local', executable='', distro='')))
        self.assertEqual(widget._setup_request(), ('legume', dict(mode='local', executable='', distro='')))
        with patch('qt_solver_environment._SetupTask') as task_class:
            widget.setup.start(False)
            task_class.assert_called_once_with('legume', dict(mode='local', executable='', distro=''), False)
            task_class.return_value.start.assert_called_once()
            from qt_solver_environment import _tasks
            _tasks.discard(task_class.return_value); widget.setup._task = None
        widget.check()
        self.assertIn('explicit runtime executable', widget.status.text())
        widget.deleteLater()

    def test_bands_discovery_accepts_missing_executable_and_timeout(self):
        from types import SimpleNamespace
        from qt_photonic_bands import PhotonicBandsWorkspace
        text = lambda value: SimpleNamespace(text=lambda: value)
        page = SimpleNamespace(runtime_mode=SimpleNamespace(currentData=lambda:'local'),
            solver=SimpleNamespace(currentData=lambda:'legume'), distro=text(''), executable=text(''),
            module_paths=text(''), library_paths=text(''), timeout=text('unfinished'))
        self.assertEqual(PhotonicBandsWorkspace.runtime_discovery_settings(page),
            dict(mode='local', distro='', executable='', module_paths=[], library_paths=[]))
        with self.assertRaisesRegex(ValueError, 'explicit runtime executable'):
            PhotonicBandsWorkspace.runtime_settings(page)

    def test_launcher_file_choice_persists_and_invalidates_readiness(self):
        widget = PhotonicRuntimeCheck(lambda: dict(solver='mpb', runtime={}))
        widget._solver = 'mpb'; widget._checked_revision = widget._revision
        selected = 'C:/User selected/WSL.exe'
        with patch('qt_solver_environment.QFileDialog.getOpenFileName', return_value=(selected,'')), \
             patch('meep_runtime.saved_wsl_launcher', return_value=''), \
             patch('meep_runtime.save_wsl_launcher', return_value=selected) as save:
            widget.setup.choose_wsl_launcher()
        save.assert_called_once_with(selected)
        self.assertNotEqual(widget._checked_revision, widget._revision)
        self.assertIn('saved', widget.setup.status.text())
        widget.deleteLater()


if __name__ == '__main__':
    unittest.main()
