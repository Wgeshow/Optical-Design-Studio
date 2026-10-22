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


if __name__ == '__main__':
    unittest.main()
