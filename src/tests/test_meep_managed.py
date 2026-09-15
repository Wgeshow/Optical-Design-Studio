"""Managed FDTD package checks; no downloads, OS setup or WSL imports occur."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from app_version import APP_VERSION
from update_client import ReleaseInfo, UpdateCancelled
import meep_managed as managed


def make_pack(folder, changes=None, extras=None):
    rootfs = b'Test rootfs blob; WSL import is mocked.'
    manifest = dict(schema=1, id='meep-wsl2', app_version=APP_VERSION, platform='wsl2-linux-x64',
        python=managed.LINUX_PYTHON, default_user='ods', rootfs_file='rootfs.tar.gz',
        rootfs_sha256=hashlib.sha256(rootfs).hexdigest(), rootfs_bytes=len(rootfs),
        unpacked_bytes=4096, meep_version='1.30.0', licenses=['GPL-2.0-or-later'])
    manifest.update(changes or {})
    path = Path(folder)/managed.asset_name()
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('addon.json', json.dumps(manifest))
        archive.writestr('rootfs.tar.gz', rootfs)
        for name, data in (extras or {}).items():
            archive.writestr(name, data)
    release = ReleaseInfo(APP_VERSION, 'v'+APP_VERSION, '', '', '', 44,
        managed.asset_name(), path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
    return path, release, manifest


class PackTests(unittest.TestCase):
    def test_only_verified_blob_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, release, manifest = make_pack(tmp)
            rootfs, result = managed.unpack_pack(path, release, Path(tmp)/'stage')
            self.assertEqual(result, manifest)
            self.assertEqual(hashlib.sha256(rootfs.read_bytes()).hexdigest(), manifest['rootfs_sha256'])
            self.assertEqual([p.name for p in rootfs.parent.iterdir()], ['rootfs.tar.gz'])

    def test_wrong_manifest_platform_version_user_and_hash_rejected(self):
        for changes in [dict(app_version='0.0.0'), dict(platform='windows-x64'), dict(default_user='root'),
                        dict(rootfs_sha256='0'*64), dict(python='/usr/bin/python')]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                path, release, _ = make_pack(tmp, changes)
                with self.assertRaises(ValueError):
                    managed.unpack_pack(path, release, Path(tmp)/'stage')

    def test_extra_and_traversal_entries_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, release, _ = make_pack(tmp, extras={'../bad.exe': b'bad'})
            with self.assertRaisesRegex(ValueError, 'Unexpected'):
                managed.unpack_pack(path, release, Path(tmp)/'stage')

    def test_outer_digest_is_mandatory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, release, _ = make_pack(tmp)
            bad = ReleaseInfo(release.version, release.tag, '', '', '', release.asset_id,
                release.asset_name, release.asset_size, '0'*64)
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                managed.unpack_pack(path, bad, Path(tmp)/'stage')

    def test_cancel_does_not_start_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, release, _ = make_pack(tmp)
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(UpdateCancelled):
                managed.unpack_pack(path, release, Path(tmp)/'stage', cancel)
            self.assertFalse((Path(tmp)/'stage').exists())

    def test_release_lookup_absent_pack_is_not_an_install(self):
        client = managed.ManagedMeepClient()
        with patch.object(client, '_json', return_value=[dict(tag_name='v'+APP_VERSION, assets=[])]):
            self.assertIsNone(client.check_pack())


class ImportTests(unittest.TestCase):
    def test_reserved_name_collision_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, release, manifest = make_pack(tmp)
            status = dict(ready=True, distributions=[managed.distro_name()])
            with patch.object(managed, 'prerequisites', return_value=status), patch.object(managed, 'registration', return_value=None), patch.object(managed.subprocess, 'Popen') as process:
                with self.assertRaisesRegex(RuntimeError, 'left unchanged'):
                    managed.import_pack(path, manifest, release, root=Path(tmp)/'owned')
                process.assert_not_called()

    def test_import_targets_only_new_owned_versioned_distribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, release, manifest = make_pack(tmp)
            root = Path(tmp)/'owned'
            process = SimpleNamespace(returncode=0, communicate=lambda timeout:(b'imported', None))
            with patch.object(managed, 'prerequisites', return_value=dict(ready=True, distributions=[])), \
                 patch.object(managed, 'registration', return_value=None), \
                 patch.object(managed.shutil, 'disk_usage', return_value=SimpleNamespace(free=20*1024**3)), \
                 patch.object(managed.subprocess, 'Popen', return_value=process) as spawn, \
                 patch.object(managed, 'verify_installed', return_value=dict(available=True, version='1.30.0', message='Ready')):
                result = managed.import_pack(path, manifest, release, root=root)
            argv = spawn.call_args.args[0]
            self.assertEqual(argv, ['wsl.exe', '--import', managed.distro_name(), str((root/'distro').resolve()), str(path.resolve()), '--version', '2'])
            self.assertTrue(result['available'])
            self.assertEqual(managed.receipt(root)['state'], 'imported')
            self.assertTrue((root/'addon.json').exists())

    def test_existing_unowned_directory_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, release, manifest = make_pack(tmp)
            root = Path(tmp)/'owned'
            (root/'distro').mkdir(parents=True)
            (root/'distro'/'valuable.txt').write_text('preserve')
            with patch.object(managed, 'prerequisites', return_value=dict(ready=True, distributions=[])), patch.object(managed, 'registration', return_value=None), patch.object(managed.subprocess, 'Popen') as process:
                with self.assertRaisesRegex(RuntimeError, 'preserved'):
                    managed.import_pack(path, manifest, release, root=root)
                process.assert_not_called()
            self.assertEqual((root/'distro'/'valuable.txt').read_text(), 'preserve')

    def test_ready_requires_actual_meep_probe_and_owned_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = dict(schema=1, app_version=APP_VERSION, distro=managed.distro_name(),
                location=str((root/'distro').resolve()), sha256='a'*64, meep_version='1.30.0', state='imported')
            (root/'installation.json').write_text(json.dumps(saved))
            with patch.object(managed, 'registration', return_value=dict(location=saved['location'], version=2)), \
                 patch.object(managed.meep_runtime, 'probe', return_value=dict(available=False, message='Meep missing')) as probe, \
                 patch.object(managed.meep_runtime, 'save_config') as save:
                self.assertFalse(managed.verify_installed(root)['available'])
                probe.assert_called_once()
                save.assert_not_called()
            with patch.object(managed, 'registration', return_value=dict(location=str(root/'other'), version=2)), \
                 patch.object(managed.meep_runtime, 'probe') as probe:
                with self.assertRaisesRegex(RuntimeError, 'left unchanged'):
                    managed.verify_installed(root)
                probe.assert_not_called()

    def test_prerequisites_only_read_commands(self):
        with patch.object(managed.sys, 'platform', 'win32'), patch.object(managed.platform, 'machine', return_value='AMD64'), \
             patch.object(managed.shutil, 'which', return_value=r'C:\Windows\System32\wsl.exe'), \
             patch.object(managed, '_wsl', side_effect=[(0, 'WSL 2.6', ''), (0, 'Default version 2', ''), (0, 'Ubuntu\nDebian', '')]) as run:
            result = managed.prerequisites()
        self.assertTrue(result['ready'])
        self.assertEqual([call.args[0] for call in run.call_args_list], [['--version'], ['--status'], ['--list', '--quiet']])


if __name__=='__main__':
    unittest.main()
