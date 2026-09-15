import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

from update_install import EXE, stage_update, apply_staged


class InstallTests(unittest.TestCase):
    def fixture(self, root, extra=None):
        target = root / 'app'
        target.mkdir()
        (target / EXE).write_bytes(b'old-exe')
        (target / '_internal').mkdir()
        (target / '_internal' / 'runtime').write_bytes(b'old-runtime')
        (target / 'User Data').mkdir()
        (target / 'User Data' / 'saved-project').write_bytes(b'keep')
        (target / 'portable_settings.json').write_text('keep settings')
        files = {EXE: b'new-exe', '_internal/runtime': b'new-runtime'}
        files.update(extra or {})
        manifest = dict(version='1.0.6', files={n:dict(size=len(b), sha256=hashlib.sha256(b).hexdigest()) for n,b in files.items()})
        package = root / 'update.zip'
        with zipfile.ZipFile(package, 'w') as archive:
            for name, data in files.items():
                archive.writestr('Optical Design Studio/' + name, data)
            archive.writestr('Optical Design Studio/PAYLOAD-MANIFEST.json', json.dumps(manifest))
        release = SimpleNamespace(version='1.0.6', asset_size=package.stat().st_size, sha256=hashlib.sha256(package.read_bytes()).hexdigest())
        return target, package, release

    def test_staging_preserves_current_application_and_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            plan = stage_update(package, release, target, target/'User Data')
            self.assertEqual((target/EXE).read_bytes(), b'old-exe')
            self.assertEqual((target/'User Data'/'saved-project').read_bytes(), b'keep')
            self.assertEqual((target/'portable_settings.json').read_text(), 'keep settings')
            self.assertEqual((plan.parent/'stage'/EXE).read_bytes(), b'new-exe')
            self.assertEqual((plan.parent/'helper'/EXE).read_bytes(), b'old-exe')

    def test_rejects_user_data_and_path_traversal(self):
        for name in ('User Data/saved-project', '../escape', 'portable_settings.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                target, package, release = self.fixture(Path(tmp), {name:b'bad'})
                with self.assertRaises(ValueError):
                    stage_update(package, release, target, target/'User Data')
                self.assertEqual((target/EXE).read_bytes(), b'old-exe')

    def test_rejects_changed_download_and_data_overlapping_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            with self.assertRaises(ValueError):
                stage_update(package, release, target, target/'_internal'/'research')
            release.sha256 = '0'*64
            with self.assertRaises(ValueError):
                stage_update(package, release, target, target/'User Data')

    def test_install_replaces_runtime_and_preserves_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            plan = stage_update(package, release, target, target/'User Data')
            with patch('update_install.wait_for_exit') as wait, \
                    patch('update_install.os.startfile') as start, \
                    patch('update_install.subprocess.Popen') as fallback:
                apply_staged(plan)
                wait.assert_called_once()
                start.assert_called_once()
                fallback.assert_not_called()
            self.assertEqual((target/EXE).read_bytes(), b'new-exe')
            self.assertEqual((target/'_internal'/'runtime').read_bytes(), b'new-runtime')
            self.assertEqual((target/'User Data'/'saved-project').read_bytes(), b'keep')
            self.assertEqual((target/'portable_settings.json').read_text(), 'keep settings')
            self.assertEqual((plan.parent/'backup'/EXE).read_bytes(), b'old-exe')

    def test_locked_runtime_rolls_back_already_replaced_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            plan = stage_update(package, release, target, target/'User Data')
            rename = Path.rename
            def locked(path, dest):
                if path == (target/'_internal').resolve():
                    raise PermissionError('locked runtime')
                return rename(path, dest)
            with patch('update_install.wait_for_exit'), patch.object(Path, 'rename', locked), patch('update_install.subprocess.Popen') as start:
                with self.assertRaises(PermissionError):
                    apply_staged(plan)
                start.assert_not_called()
            self.assertEqual((target/EXE).read_bytes(), b'old-exe')
            self.assertEqual((target/'_internal'/'runtime').read_bytes(), b'old-runtime')
            self.assertEqual((target/'User Data'/'saved-project').read_bytes(), b'keep')
