"""Per-user WSL recovery settings do not change the Windows installation."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import meep_runtime

class LauncherPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / 'wsl-launcher.json'
        self.preference = patch.object(meep_runtime, 'wsl_launcher_configuration_path', return_value=self.file)
        self.preference.start()
        self.environment = patch.dict(os.environ, ODS_WSL_EXECUTABLE='')
        self.environment.start()
    def tearDown(self):
        self.environment.stop(); self.preference.stop(); self.temp.cleanup()
    def executable(self, name):
        path = self.root / name; path.touch(); return path
    def test_saved_choice_is_used_by_normal_launch_without_environment_override(self):
        path = self.executable('Microsoft WSL.exe')
        meep_runtime.save_wsl_launcher(str(path))
        with patch.object(meep_runtime.shutil, 'which', return_value='broken-default.exe'):
            self.assertEqual(meep_runtime.wsl_executable(), str(path.resolve()))
        self.assertEqual(json.loads(self.file.read_text())['schema'], 1)
    def test_explicit_environment_override_takes_priority(self):
        saved = self.executable('saved.exe'); override = self.executable('override.exe')
        meep_runtime.save_wsl_launcher(str(saved))
        with patch.dict(os.environ, ODS_WSL_EXECUTABLE=str(override)):
            self.assertEqual(meep_runtime.wsl_executable(), str(override.resolve()))
    def test_stale_saved_path_reports_recovery_instead_of_silent_fallback(self):
        path = self.executable('removed.exe'); meep_runtime.save_wsl_launcher(str(path)); path.unlink()
        with self.assertRaisesRegex(ValueError, 'saved Windows WSL launcher'):
            meep_runtime.wsl_executable()
    def test_rejects_relative_missing_and_non_executable_paths(self):
        for value in ['relative.exe', str(self.root / 'missing.exe'), str(self.executable('not-executable.txt'))]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                meep_runtime.save_wsl_launcher(value)
        self.assertFalse(self.file.exists())
    def test_invalid_configuration_preserves_default_resolution(self):
        self.file.write_text('{invalid')
        path = self.root / 'system-wsl.exe'
        with patch.object(meep_runtime.shutil, 'which', return_value=str(path)):
            self.assertEqual(meep_runtime.wsl_executable(), str(path.resolve()))

if __name__ == '__main__': unittest.main()
