"""Installer ownership, actual subprocess probes, and usable asynchronous UI."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import solver_environment as setup
from qt_solver_environment import SolverEnvironmentSetup

APP = QApplication.instance() or QApplication([])


class InstallerTests(unittest.TestCase):
    def test_discovery_never_installs_into_selected_interpreter(self):
        runtime = dict(mode='local', executable='C:/user/python.exe')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder, patch.object(setup, 'discover', return_value=runtime), patch.object(setup, '_python_install') as install:
            result = setup.setup('legume', runtime, root=Path(folder)/'managed')
            self.assertEqual(result, runtime)
            install.assert_not_called()
            self.assertFalse((Path(folder)/'managed').exists())

    def test_failure_never_publishes_runtime_or_changes_existing_receipt(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            receipt = root/'legume.json'
            receipt.write_text('old working receipt', encoding='utf-8')
            with patch.object(setup, 'discover', return_value={}), patch.object(setup, '_python_install', side_effect=RuntimeError('Download failed')):
                with self.assertRaisesRegex(RuntimeError, 'Download failed'):
                    setup.setup('legume', root=root)
            self.assertEqual(receipt.read_text(), 'old working receipt')

    def test_new_runtime_is_published_only_after_api_probe(self):
        runtime = dict(mode='local', executable='C:/managed/python.exe')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            with patch.object(setup, 'discover', return_value={}), patch.object(setup, '_python_install', return_value=runtime), patch.object(setup, 'probe', return_value=runtime) as probe:
                result = setup.setup('gmsh', root=folder)
            probe.assert_called_once()
            self.assertEqual(result, setup.saved_runtime('gmsh', folder))
            data = json.loads(Path(folder, 'gmsh.json').read_text())
            self.assertIn('gmsh==4.13.1', data['packages'])

    def test_cancellation_does_not_publish(self):
        cancelled = threading.Event(); cancelled.set()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            with self.assertRaises(InterruptedError):
                setup.setup('sesame', root=folder, cancel=cancelled)
            self.assertFalse(Path(folder, 'sesame.json').exists())

    def test_paths_cannot_escape_managed_root(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)/'managed'
            with self.assertRaisesRegex(ValueError, 'outside'):
                setup._owned_path(root, root/'..'/'unrelated')

    def test_environment_ignores_user_python_and_package_manager_overrides(self):
        with patch.dict(os.environ, PYTHONPATH='unrelated/modules', PYTHONHOME='bad', UV_INDEX_URL='https://example.invalid', PIP_INDEX_URL='https://example.invalid'):
            env = setup._environment(Path('C:/managed'))
        self.assertNotIn('PYTHONPATH', env)
        self.assertNotIn('PYTHONHOME', env)
        self.assertNotIn('UV_INDEX_URL', env)
        self.assertNotIn('PIP_INDEX_URL', env)
        self.assertEqual(env['UV_PYTHON_NO_REGISTRY'], '1')

    def test_actual_child_checks_required_api_not_just_package_name(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder)/'legume.py'
            path.write_text('__version__="unrelated package"\n', encoding='utf-8')
            runtime = dict(mode='local', executable=sys.executable, module_paths=[folder])
            with self.assertRaisesRegex(RuntimeError, 'ImportError'):
                setup.probe('legume', runtime)
            path.write_text('PhotCryst = PlaneWaveExp = GuidedModeExp = Circle = Poly = object\n', encoding='utf-8')
            self.assertEqual(setup.probe('legume', runtime)['executable'], sys.executable)

    def test_actual_process_cancel_is_prompt_and_retryable(self):
        cancelled = threading.Event()
        timer = threading.Timer(.25, cancelled.set); timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(InterruptedError):
                setup._run([sys.executable, '-c', 'import time; time.sleep(20)'], cancel=cancelled)
        finally:
            timer.cancel()
        self.assertLess(time.monotonic()-started, 5)


class SetupUiTests(unittest.TestCase):
    def widget(self):
        widget = SolverEnvironmentSetup(lambda: ('legume', {}))
        self.addCleanup(widget.deleteLater)
        return widget

    def wait(self, widget):
        for _ in range(300):
            QTest.qWait(10)
            if widget._task is None:
                return
        self.fail('The setup UI did not release its worker.')

    def test_click_setup_runs_off_ui_thread_and_returns_verified_runtime(self):
        widget = self.widget(); result = []; main_thread = threading.get_ident()
        runtime = dict(mode='local', executable='C:/owned/python.exe')
        def install(*args, **kwargs):
            self.assertNotEqual(threading.get_ident(), main_thread)
            kwargs['progress']('Creating isolated environment')
            return runtime
        widget.runtimeReady.connect(result.append)
        with patch('solver_environment.setup', side_effect=install):
            widget.install_button.click()
            self.assertFalse(widget.install_button.isEnabled())
            self.wait(widget)
        self.assertEqual(result, [runtime])
        self.assertIn('Creating isolated environment', widget.log.toPlainText())
        self.assertTrue(widget.install_button.isEnabled())

    def test_failed_setup_preserves_actionable_error_and_retry(self):
        widget = self.widget()
        with patch('solver_environment.setup', side_effect=RuntimeError('Network unavailable. Retry setup.')):
            widget.install_button.click(); self.wait(widget)
        self.assertIn('Network unavailable', widget.status.text())
        self.assertTrue(widget.find_button.isEnabled())
        self.assertTrue(widget.install_button.isEnabled())

    def test_solver_switch_never_applies_old_runtime(self):
        widget = self.widget(); values = []
        widget.runtimeReady.connect(values.append)
        def install(*args, **kwargs):
            time.sleep(.12)
            return dict(executable='old solver')
        with patch('solver_environment.setup', side_effect=install):
            widget.install_button.click()
            widget.invalidate()
            self.wait(widget)
        self.assertEqual(values, [])
        self.assertIn('selected solver changed', widget.status.text())


class MeepSetupTests(unittest.TestCase):
    def test_install_uses_managed_bootstrap_without_release_asset_gate(self):
        from qt_fdtd import _ManagedRuntimeTask
        runtime = dict(mode='wsl', distro=setup.DISTRO, executable='/opt/ods-solvers/meep-test/bin/python')
        configured = dict(mode='wsl', distro='User Research', python='/usr/bin/python3', conda='/user/conda')
        task = _ManagedRuntimeTask(install=True); values = []
        task.completed.connect(values.append)
        with patch('meep_runtime.load_config', return_value=configured), patch('solver_environment.setup', return_value=runtime) as install, \
                patch('meep_runtime.probe', return_value=dict(available=True, message='Meep ready', version='1.30.0')), patch('meep_runtime.save_config') as save:
            task.run()
        self.assertEqual(install.call_args.args[0], 'meep')
        self.assertEqual(save.call_args.args[0]['python'], runtime['executable'])
        self.assertTrue(save.call_args.args[0]['managed'])
        self.assertTrue(values[0]['available'])

    def test_failed_verification_does_not_replace_saved_meep_config(self):
        from qt_fdtd import _ManagedRuntimeTask
        task = _ManagedRuntimeTask(install=True)
        runtime = dict(mode='wsl', distro=setup.DISTRO, executable='/opt/ods-solvers/meep-test/bin/python')
        with patch('meep_runtime.load_config', return_value=dict(mode='wsl', distro='User', python='/usr/bin/python3')), \
                patch('solver_environment.setup', return_value=runtime), patch('meep_runtime.probe', return_value=dict(available=False, message='Missing native dependency')), \
                patch('meep_runtime.save_config') as save:
            task.run()
        save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
