"""Installed desktop paths and non-destructive library seeding."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import desktop_runtime as runtime
import bootstrap


class DesktopRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='optical_installer_test_')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.resources = self.root / 'application' / '_internal'
        self.resources.mkdir(parents=True)
        self.user = self.root / 'saved work'

    def archive(self, name, files, manifest=False):
        path = self.root / name
        records = {}
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for key, value in files.items():
                payload = value.encode() if isinstance(value, str) else value
                archive.writestr(key, payload)
                records[key] = dict(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            if manifest:
                archive.writestr('s4-library-manifest.json', json.dumps(dict(format='s4-library', version=1, files=records)))
        return path

    def test_source_and_frozen_backend_commands_do_not_relaunch_the_gui(self):
        job = self.user / 'runs' / 'example' / 'job.json'
        with patch.object(sys, 'frozen', False, create=True):
            command = runtime.backend_command(job)
            self.assertEqual(command[-3:], [str(runtime.resource_root() / 'backend.py'), '--job', str(job)])
            self.assertEqual(command[1], '-u')
        executable = self.resources.parent / 'Optical Design Studio.exe'
        backend = self.resources.parent / 'OpticalDesignBackend.exe'
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(executable)):
            with self.assertRaisesRegex(RuntimeError, 'backend is missing'):
                runtime.backend_command(job)
            backend.write_bytes(b'test executable placeholder')
            self.assertEqual(runtime.backend_command(job), [str(backend), '--job', str(job)])

    def test_library_argument_beats_environment_and_installed_default_is_writable_user_data(self):
        with patch.object(sys, 'frozen', True, create=True), patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'local')}, clear=True):
            self.assertEqual(runtime.library_root([]), runtime.default_data_directory())
            os.environ['S4_LIBRARY_ROOT'] = str(self.root / 'environment')
            self.assertEqual(runtime.library_root([]), (self.root / 'environment').resolve())
            self.assertEqual(runtime.initialize_desktop(['--library', str(self.user), '--theme', 'dark']), self.user.resolve())
            self.assertEqual(os.environ['S4_LIBRARY_ROOT'], str(self.user.resolve()))

    def test_first_launch_seeds_data_and_upgrades_preserve_existing_records(self):
        first = self.archive('first.zip', {
            'runs/a/project.json': 'original design',
            'runs/a/library_record.json': 'original record',
            'data_library/presets/p.json': 'original preset',
            'data_library/optical_constants/nk_a.csv': 'original optical constants',
            'data_library/desktop_session.json': 'original session',
        }, manifest=True)
        self.assertEqual(runtime.seed_library(first, self.user), dict(runs=1, files=3))
        (self.user / 'runs/a/project.json').write_text('user modified design')
        (self.user / 'data_library/presets/p.json').write_text('user modified preset')
        (self.user / 'data_library/desktop_session.json').write_text('user current session')
        second = self.archive('second.zip', {
            'runs/a/project.json': 'different seed design',
            'runs/a/new_result.csv': 'must not alter an existing run',
            'runs/b/project.json': 'new supplied design',
            'data_library/presets/p.json': 'different seed preset',
            'data_library/presets/q.json': 'new supplied preset',
            'data_library/desktop_session.json': 'different seed session',
        })
        self.assertEqual(runtime.seed_library(second, self.user), dict(runs=1, files=1))
        self.assertEqual((self.user / 'runs/a/project.json').read_text(), 'user modified design')
        self.assertFalse((self.user / 'runs/a/new_result.csv').exists())
        self.assertEqual((self.user / 'data_library/presets/p.json').read_text(), 'user modified preset')
        self.assertEqual((self.user / 'data_library/desktop_session.json').read_text(), 'user current session')
        shutil.rmtree(self.user / 'runs/b')
        self.assertEqual(runtime.seed_library(second, self.user), dict(runs=0, files=0))
        self.assertFalse((self.user / 'runs/b').exists(), 'A deleted sample must not return on every startup')

    def test_corrupt_or_unsafe_seed_is_rejected_before_any_saved_record_changes(self):
        for index, malicious in enumerate(('../outside.txt', '/absolute.txt', 'runs/a/../../escape.txt', 'data_library/presets/CON.json', 'runs//a/file.json')):
            archive = self.archive(f'bad{index}.zip', {'runs/a/project.json': 'safe', malicious: 'unsafe'})
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                runtime.seed_library(archive, self.user)
            self.assertFalse((self.user / 'runs').exists())
        path = self.archive('checksum.zip', {'runs/a/project.json': 'original'}, manifest=True)
        with zipfile.ZipFile(path) as source:
            manifest = json.loads(source.read('s4-library-manifest.json'))
        manifest['files']['runs/a/project.json']['sha256'] = '0' * 64
        broken = self.archive('broken.zip', {'runs/a/project.json': 'original', 's4-library-manifest.json': json.dumps(manifest)})
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            runtime.seed_library(broken, self.user)
        self.assertFalse((self.user / 'runs').exists())

    def test_frozen_resources_source_export_and_bundled_gpu_override(self):
        (self.resources / 'cublas64_11.dll').write_bytes(b'test')
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(self.resources), create=True), patch.dict(os.environ, {}, clear=True), patch.object(os, 'add_dll_directory', create=True) as add_directory:
            self.assertEqual(runtime.source_root(), self.resources / 'source')
            bootstrap.initialize(1)
            self.assertEqual(os.environ['S4_CUBLAS_LIBRARY'], str((self.resources / 'cublas64_11.dll').resolve()))
            self.assertIn(str(self.resources), os.environ['S4_DLL_DIRS'].split(os.pathsep))
            add_directory.assert_any_call(str(self.resources))
            os.environ['S4_CUBLAS_LIBRARY'] = 'explicit-user-runtime.dll'
            bootstrap.initialize(1)
            self.assertEqual(os.environ['S4_CUBLAS_LIBRARY'], 'explicit-user-runtime.dll')

    def test_portable_directory_selection_persists_and_reset_moves_with_application(self):
        app = self.resources.parent
        old = self.root / 'existing data'
        old.mkdir()
        (old/'result.csv').write_text('saved result')
        with patch.object(runtime, 'application_root', return_value=app), patch.dict(os.environ, {}, clear=True), patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(runtime.library_root([]), app/'User Data')
            runtime.save_data_directory(old)
            self.assertEqual(runtime.library_root([]), old)
            self.assertEqual((old/'result.csv').read_text(), 'saved result')
            runtime.save_data_directory()
            self.assertEqual(json.loads((app/'portable_settings.json').read_text())['data_directory'], 'User Data')
            self.assertEqual(runtime.library_root([]), app/'User Data')
            moved = self.root/'moved app'
            shutil.copytree(app, moved)
            with patch.object(runtime, 'application_root', return_value=moved):
                self.assertEqual(runtime.library_root([]), moved/'User Data')

    def test_failed_storage_selection_preserves_existing_configuration(self):
        with patch.object(runtime, 'application_root', return_value=self.resources.parent):
            runtime.save_data_directory(self.user)
            before = (self.resources.parent/'portable_settings.json').read_bytes()
            file = self.root/'not a folder'
            file.write_text('do not replace')
            with self.assertRaises(OSError):
                runtime.save_data_directory(file)
            self.assertEqual((self.resources.parent/'portable_settings.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
