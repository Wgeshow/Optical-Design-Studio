import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import addon_runtime as ar
from update_client import ReleaseInfo, UpdateCancelled, UpdateError


class AddonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def pack(self, filename='cublas64_11.dll', content=b'test native payload', **overrides):
        archive = self.root / 'pack.zip'
        manifest = dict(schema=1, id='gpu', app_version=ar.APP_VERSION, platform='windows-x64',
            python=f'{sys.version_info.major}.{sys.version_info.minor}',
            files={filename: hashlib.sha256(content).hexdigest()})
        manifest.update(overrides)
        with zipfile.ZipFile(archive, 'w') as pack:
            pack.writestr('addon.json', json.dumps(manifest))
            pack.writestr(filename, content)
        raw = archive.read_bytes()
        info = ReleaseInfo(ar.APP_VERSION, 'v'+ar.APP_VERSION, '', '', '', 123,
            ar.asset_name('gpu'), len(raw), hashlib.sha256(raw).hexdigest())
        return archive, info

    def test_installs_only_after_explicit_call(self):
        archive, info = self.pack()
        managed = self.root / 'managed'
        self.assertFalse(managed.exists())
        target = ar.install_archive('gpu', archive, info, root=managed)
        self.assertIsNone(ar._read_receipt('gpu', managed))
        self.assertEqual(ar.pending_addons(managed), ['gpu'])
        self.assertEqual((target / 'cublas64_11.dll').read_bytes(), b'test native payload')
        self.assertFalse(list(managed.glob('.staging-*')))
        result = ar.validate_pending('gpu', lambda identifier, directory: True, root=managed)
        self.assertEqual(result['status'], 'activated')
        self.assertEqual(ar._read_receipt('gpu', managed), target)
        self.assertEqual(ar.pending_addons(managed), [])

    def test_failed_candidate_keeps_previous_receipt_and_payloads(self):
        managed = self.root/'managed'
        archive, info = self.pack(content=b'old runtime')
        previous = ar.install_archive('gpu', archive, info, root=managed)
        ar.validate_pending('gpu', lambda *_: True, root=managed)
        old_receipt = (managed/'gpu.json').read_bytes()
        archive, info = self.pack(content=b'new bad runtime')
        candidate = ar.install_archive('gpu', archive, info, root=managed)
        self.assertEqual((managed/'gpu.json').read_bytes(), old_receipt)
        result = ar.validate_pending('gpu', lambda *_: False, root=managed)
        self.assertEqual(result['status'], 'rolled-back')
        self.assertEqual((managed/'gpu.json').read_bytes(), old_receipt)
        self.assertTrue(previous.is_dir())
        self.assertTrue(candidate.is_dir())
        self.assertTrue((managed/'gpu.failed.json').is_file())

    def test_startup_rejects_tampered_payload_before_native_probe(self):
        managed = self.root/'managed'
        archive, info = self.pack()
        candidate = ar.install_archive('gpu', archive, info, root=managed)
        (candidate/'cublas64_11.dll').write_bytes(b'altered')
        with patch('addon_runtime.probe_native_payload') as probe:
            result = ar.validate_pending('gpu', probe, root=managed)
            self.assertEqual(result['status'], 'rolled-back')
            probe.assert_not_called()
        self.assertIsNone(ar._read_receipt('gpu', managed))
        self.assertTrue(candidate.exists())

    def test_damaged_pending_receipts_keep_active_addon_and_are_quarantined(self):
        managed = self.root/'managed'
        archive, info = self.pack(content=b'active runtime')
        active = ar.install_archive('gpu', archive, info, root=managed)
        ar.validate_pending('gpu', lambda *_: True, root=managed)
        old_receipt = (managed/'gpu.json').read_bytes()
        valid = dict(schema=1, id='gpu', version=ar.APP_VERSION,
                     sha256='a'*64, manifest_sha256='b'*64)
        damaged = [b'{broken', b'[]', b'null', b'\xff', b'{}', b' '*16385,
                   json.dumps(dict(valid, sha256=None)).encode(),
                   json.dumps(dict(valid, previous={'id':'gpu', 'version':ar.APP_VERSION, 'sha256':1})).encode()]
        for raw in damaged:
            with self.subTest(raw=raw[:80]):
                pending = managed/'gpu.pending.json'
                pending.write_bytes(raw)
                with patch('addon_runtime.probe_native_payload') as probe:
                    result = ar.validate_pending('gpu', probe, root=managed)
                    probe.assert_not_called()
                self.assertEqual(result['status'], 'rejected')
                self.assertEqual(Path(result['quarantined']).read_bytes(), raw)
                self.assertFalse(pending.exists())
                self.assertEqual((managed/'gpu.json').read_bytes(), old_receipt)
                self.assertEqual(ar._read_receipt('gpu', managed), active)
                self.assertEqual(ar.validate_pending('gpu', lambda *_: True, root=managed)['status'], 'not-pending')

    def test_failed_quarantine_does_not_prevent_startup(self):
        self.root.joinpath('gpu.pending.json').write_text('{broken')
        with patch.object(Path, 'rename', side_effect=PermissionError('receipt locked')):
            result = ar.validate_pending('gpu', lambda *_: self.fail('must not probe'), root=self.root)
        self.assertEqual(result['status'], 'rejected')
        self.assertIn('receipt locked', result['recovery_error'])
        self.assertTrue(self.root.joinpath('gpu.pending.json').exists())

    def test_desktop_startup_continues_after_damaged_receipt(self):
        import desktop_runtime
        self.root.joinpath('gpu.pending.json').write_text('{broken')
        with patch.object(ar, 'addon_root', return_value=self.root), patch.object(desktop_runtime, '_probe_addon_child') as probe:
            results = desktop_runtime.validate_startup_addons(self.root/'library')
        self.assertEqual(results[0]['status'], 'rejected')
        probe.assert_not_called()
        self.assertEqual(ar.pending_addons(self.root), [])
        desktop_runtime.startup_addon_results.clear()

    def test_failed_rollback_does_not_mask_candidate_error(self):
        archive, info = self.pack()
        managed = self.root/'managed'
        ar.install_archive('gpu', archive, info, root=managed)
        with patch.object(ar, 'rollback_pending', side_effect=OSError('disk unavailable')):
            result = ar.validate_pending('gpu', lambda *_: False, root=managed)
        self.assertEqual(result['status'], 'recovery-failed')
        self.assertIn('isolated native startup check', result['error'])
        self.assertIn('disk unavailable', result['recovery_error'])

    def test_path_traversal_and_windows_paths(self):
        for name in ('../evil.dll', '/evil.dll', 'C:/evil.dll', 'a\\evil.dll', 'a/../evil.dll',
                     'NUL.dll', 'aux/file.dll', 'bad./file.dll', 'a//file.dll'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                ar._relative(name)

    def test_hash_mismatch_never_commits(self):
        archive, info = self.pack()
        archive.write_bytes(b'x' * info.asset_size)
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            ar.install_archive('gpu', archive, info, root=self.root/'managed')
        self.assertFalse((self.root/'managed'/'gpu.json').exists())

    def test_version_and_python_must_match(self):
        for override in ({'app_version': '0.0.0'}, {'python': '2.7'}, {'platform': 'linux-x64'}):
            archive, info = self.pack(**override)
            with self.assertRaisesRegex(ValueError, 'incompatible'):
                ar.install_archive('gpu', archive, info, root=self.root/'managed')

    def test_cancel_cleans_staging_and_no_receipt(self):
        archive, info = self.pack()
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(UpdateCancelled):
            ar.install_archive('gpu', archive, info, root=self.root/'managed', cancel=cancel)
        self.assertFalse((self.root/'managed'/'gpu.json').exists())

    def test_unexpected_executable_rejected(self):
        archive, info = self.pack(filename='setup.exe')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            ar.install_archive('gpu', archive, info, root=self.root/'managed')

    def test_file_digest_checked(self):
        archive, info = self.pack(files={'cublas64_11.dll': '0'*64})
        with self.assertRaisesRegex(ValueError, 'integrity'):
            ar.install_archive('gpu', archive, info, root=self.root/'managed')

    def test_metadata_only_query_exact_app_version(self):
        _, info = self.pack()
        release = {'tag_name': info.tag, 'assets': [dict(name=info.asset_name, id=123,
            size=info.asset_size, state='uploaded', digest='sha256:'+info.sha256)]}
        client = ar.AddonClient()
        with patch.object(client, '_json', return_value=[release]) as metadata, patch.object(client, 'download') as download:
            result = client.check_addon('gpu')
            self.assertEqual(result.sha256, info.sha256)
            metadata.assert_called_once()
            download.assert_not_called()

    def test_missing_asset_is_not_available(self):
        with patch.object(ar.AddonClient, '_json', return_value=[]):
            self.assertIsNone(ar.AddonClient().check_addon('gpu'))

    def test_unknown_addon_rejected(self):
        with self.assertRaises(ValueError):
            ar.asset_name('../unexpected')


if __name__ == '__main__':
    unittest.main()
