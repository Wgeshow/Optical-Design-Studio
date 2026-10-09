"""Early dispatch and disposable native validation must precede GUI startup."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import desktop_runtime as runtime
import addon_runtime


class StartupHelperTests(unittest.TestCase):
    def test_restart_dispatch_does_not_initialize_application(self):
        with patch('application_restart.restart_helper_main', return_value=0) as helper, patch.object(runtime, 'library_root') as root:
            with self.assertRaises(SystemExit) as stopped:
                runtime.initialize_desktop(['--restart-app', 'plan.json'])
            self.assertEqual(stopped.exception.code, 0)
            root.assert_not_called()
            helper.assert_called_once_with('plan.json')

    def test_probe_accepts_only_receipted_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            candidate = root/('gpu-'+'a'*64)
            candidate.mkdir()
            with patch.object(addon_runtime, 'addon_root', return_value=root), patch.object(addon_runtime, '_pending', return_value={'sha256':'a'*64}), patch.object(addon_runtime, 'probe_native_payload', return_value=True) as probe:
                self.assertEqual(runtime.dispatch_startup_helper(['--addon-probe','gpu',str(candidate)]), 0)
                probe.assert_called_once_with('gpu', candidate)
                with self.assertRaises(ValueError):
                    runtime.dispatch_startup_helper(['--addon-probe','gpu',str(root)])

    def test_validation_runs_once_per_process_library(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(addon_runtime, 'pending_addons', return_value=['gpu']), patch.object(addon_runtime, 'validate_pending', return_value={'status':'activated'}) as validate:
                runtime.validate_startup_addons(folder)
                runtime.validate_startup_addons(folder)
                validate.assert_called_once_with('gpu', runtime._probe_addon_child)

    def test_probe_child_has_no_shell_and_exact_source_entry(self):
        with patch.object(runtime.sys, 'frozen', False, create=True), patch('subprocess.run', return_value=Mock(returncode=0)) as run:
            self.assertTrue(runtime._probe_addon_child('gpu', Path.cwd()))
            args, kwargs = run.call_args
            self.assertEqual(args[0][:3], [str(Path(sys.executable).resolve()), str(Path(runtime.__file__).resolve()), '--addon-probe'])
            self.assertNotIn('shell', kwargs)
            self.assertEqual(kwargs['timeout'], 120)

    def test_import_is_scientific_library_free(self):
        result = subprocess.run([sys.executable, '-c', "import sys; import desktop_runtime; assert not any(n in sys.modules for n in ('numpy','PyQt6','OCP','qt_app'))"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_disposable_child_rejects_unreceipted_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            environment = dict(os.environ, LOCALAPPDATA=folder)
            result = subprocess.run([sys.executable, str(Path(runtime.__file__).resolve()),
                '--addon-probe', 'gpu', folder], env=environment,
                capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertIn('not the staged add-on receipt', result.stderr)


if __name__ == '__main__':
    unittest.main()
