import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
import threading
from unittest.mock import patch

from update_install import (EXE, stage_update, apply_staged, preflight_update,
                            acknowledge_startup, _cleanup_after_helper, wait_for_ack, launch_update, discard_staged)
from update_client import UpdateCancelled


class InstallTests(unittest.TestCase):
    def fixture(self, root, extra=None):
        cache = root / 'cache'
        cache.mkdir()
        self.enterContext(patch('update_install.update_cache_root', return_value=cache.resolve()))
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
            self.assertEqual((plan.parent/'helper'/EXE).read_bytes(), b'new-exe')
            self.assertEqual((plan.parent/'helper'/'_internal'/'runtime').read_bytes(), b'new-runtime')

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
                    patch('update_install.wait_for_ack', return_value=True), \
                    patch('update_install.subprocess.Popen') as fallback:
                apply_staged(plan)
                wait.assert_called_once()
                start.assert_called_once()
                fallback.assert_not_called()
            self.assertEqual((target/EXE).read_bytes(), b'new-exe')
            self.assertEqual((target/'_internal'/'runtime').read_bytes(), b'new-runtime')
            self.assertEqual((target/'User Data'/'saved-project').read_bytes(), b'keep')
            self.assertEqual((target/'portable_settings.json').read_text(), 'keep settings')
            job = json.loads(plan.read_text())
            self.assertEqual((Path(job['transaction'])/'backup'/EXE).read_bytes(), b'old-exe')
            self.assertTrue((plan.parent/'success.json').exists())

    def test_locked_runtime_rolls_back_already_replaced_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            plan = stage_update(package, release, target, target/'User Data')
            rename = Path.rename
            def locked(path, dest):
                if path == (target/'_internal').resolve():
                    raise PermissionError('locked runtime')
                return rename(path, dest)
            with patch('update_install.wait_for_exit'), patch.object(Path, 'rename', locked), patch('update_install._relaunch') as start:
                with self.assertRaisesRegex(RuntimeError, 'restored'):
                    apply_staged(plan)
                start.assert_called_once_with(target.resolve())
            self.assertEqual((target/EXE).read_bytes(), b'old-exe')
            self.assertEqual((target/'_internal'/'runtime').read_bytes(), b'old-runtime')
            self.assertEqual((target/'User Data'/'saved-project').read_bytes(), b'keep')

    def test_cache_is_separate_and_transaction_stays_on_target_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            plan = stage_update(package, release, target, target/'User Data')
            job = json.loads(plan.read_text())
            self.assertEqual(plan.parent.parent, (Path(tmp)/'cache').resolve())
            self.assertEqual(Path(job['transaction']).parent, target.resolve())

    def test_cancel_during_extraction_removes_staging_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            cancel = threading.Event()
            def progress(done, total):
                if done:
                    cancel.set()
            with self.assertRaises(UpdateCancelled):
                stage_update(package, release, target, target/'User Data', cancel=cancel, progress=progress)
            self.assertEqual((target/EXE).read_bytes(), b'old-exe')
            self.assertEqual(list((Path(tmp)/'cache').iterdir()), [])
            self.assertEqual(list(target.glob('.ods-update-*')), [])
            self.assertTrue(package.exists())

    def test_disk_and_write_preflight_preserve_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            with patch('update_install.shutil.disk_usage', return_value=SimpleNamespace(free=1)):
                with self.assertRaisesRegex(ValueError, 'disk space'):
                    preflight_update(target, release.asset_size)
            with patch('update_install.tempfile.TemporaryFile', side_effect=PermissionError('denied')):
                with self.assertRaisesRegex(PermissionError, 'not writable'):
                    preflight_update(target)
            self.assertEqual((target/EXE).read_bytes(), b'old-exe')

    def test_tampered_prepared_file_does_not_replace_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            plan = stage_update(package, release, target, target/'User Data')
            job = json.loads(plan.read_text())
            (Path(job['transaction'])/'new'/EXE).write_bytes(b'tampered')
            with patch('update_install.wait_for_exit'), patch('update_install._relaunch') as launch:
                with self.assertRaisesRegex(ValueError, 'verification'):
                    apply_staged(plan)
                launch.assert_not_called()
            self.assertEqual((target/EXE).read_bytes(), b'old-exe')

    def test_no_startup_ack_preserves_recovery_and_reports_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            plan = stage_update(package, release, target, target/'User Data')
            with patch('update_install.wait_for_exit'), patch('update_install._relaunch'), patch('update_install.wait_for_ack', return_value=False):
                with self.assertRaisesRegex(RuntimeError, 'installed, but successful startup'):
                    apply_staged(plan)
            self.assertEqual((target/EXE).read_bytes(), b'new-exe')
            self.assertFalse((plan.parent/'success.json').exists())
            self.assertTrue(Path(json.loads(plan.read_text())['transaction']).exists())

    def test_receipt_and_generated_settings_roll_back_with_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp), {'zzz-final.txt':b'new'})
            (target/'portable_settings.json').unlink()
            (target/'installation.json').write_text('old receipt')
            plan = stage_update(package, release, target, target/'User Data')
            rename = Path.rename
            def fail_final(path, dest):
                if path.name == 'zzz-final.txt':
                    raise PermissionError('locked final file')
                return rename(path, dest)
            with patch('update_install.wait_for_exit'), patch('update_install._relaunch'), patch.object(Path, 'rename', fail_final):
                with self.assertRaisesRegex(RuntimeError, 'restored'):
                    apply_staged(plan)
            self.assertEqual((target/'installation.json').read_text(), 'old receipt')
            self.assertFalse((target/'portable_settings.json').exists())
            self.assertEqual((target/EXE).read_bytes(), b'old-exe')

    def test_ack_is_bound_to_version_and_executable_then_cleans_owned_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            cached = Path(tmp)/'cache'/'update.zip'
            cached.write_bytes(package.read_bytes())
            plan = stage_update(cached, release, target, target/'User Data')
            job = json.loads(plan.read_text())
            with patch('update_install.wait_for_exit'), patch('update_install._relaunch'), patch('update_install.wait_for_ack', return_value=True):
                apply_staged(plan)
            self.assertFalse(acknowledge_startup(plan))
            with patch('update_install.sys.frozen', True, create=True), patch('update_install.sys.executable', str(target/EXE)), patch('app_version.APP_VERSION', release.version), patch('update_install.threading.Thread'):
                self.assertTrue(acknowledge_startup(plan))
            self.assertTrue(wait_for_ack(plan.parent, job['token'], timeout=.1))
            with patch('update_install.wait_for_exit'):
                _cleanup_after_helper(plan)
            self.assertFalse(plan.parent.exists())
            self.assertFalse(Path(job['transaction']).exists())
            self.assertFalse(cached.exists())
            self.assertTrue(package.exists())
            self.assertEqual((target/'User Data'/'saved-project').read_bytes(), b'keep')

    def test_helper_handoff_requires_matching_ready_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            plan = stage_update(package, release, target, target/'User Data')
            process = SimpleNamespace(pid=123, poll=lambda: None)
            (plan.parent/'helper.json').write_text(json.dumps({'pid':123}))
            with patch('update_install.subprocess.Popen', return_value=process):
                self.assertIs(launch_update(plan), process)
            (plan.parent/'helper.json').unlink()
            failed = SimpleNamespace(pid=456, poll=lambda: 1)
            with patch('update_install.subprocess.Popen', return_value=failed):
                with self.assertRaisesRegex(RuntimeError, 'could not start'):
                    launch_update(plan)
            self.assertEqual((target/EXE).read_bytes(), b'old-exe')

    def test_copy_failure_discards_owned_staging_and_leaves_install_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            with patch('update_install._copy_file', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    stage_update(package, release, target, target/'User Data')
            self.assertEqual(list(target.glob('.ods-update-*')), [])
            self.assertEqual(list((Path(tmp)/'cache').iterdir()), [])
            self.assertEqual((target/EXE).read_bytes(), b'old-exe')

    def test_cancel_completed_stage_keeps_download_and_never_discards_live_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package, release = self.fixture(Path(tmp))
            plan = stage_update(package, release, target, target/'User Data')
            transaction = Path(json.loads(plan.read_text())['transaction'])
            (plan.parent/'helper.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'started'):
                discard_staged(plan)
            (plan.parent/'helper.json').unlink()
            discard_staged(plan)
            self.assertFalse(plan.parent.exists())
            self.assertFalse(transaction.exists())
            self.assertTrue(package.exists())
            self.assertEqual((target/EXE).read_bytes(), b'old-exe')
