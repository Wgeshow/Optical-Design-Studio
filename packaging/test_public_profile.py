"""Public delivery rejects research data and uses only reviewed readable source."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import build_version
import prepare_payload
from public_profile import (SOURCE_REQUIRED, assert_empty_seed, public_build_info,
                            validate_public_source, write_empty_seed)


def make_reviewed_tree(root):
    root.mkdir(parents=True)
    for name in SOURCE_REQUIRED:
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# Source fixture\n', encoding='utf-8')
    (root/'app_version.py').write_text("APP_VERSION = '1.0.3'\nBUILD_DATE = '2026-09-13'\n", encoding='utf-8')


class PublicProfileTests(unittest.TestCase):
    def test_only_manifest_only_seed_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            seed = Path(folder)/'seed.zip'
            write_empty_seed(seed)
            assert_empty_seed(seed)
            with zipfile.ZipFile(seed, 'a') as archive:
                archive.writestr('runs/private/result.csv', 'private result')
            with self.assertRaises(ValueError):
                assert_empty_seed(seed)
            with zipfile.ZipFile(seed, 'w') as archive:
                archive.writestr('s4-library-manifest.json', json.dumps(
                    {'format': 's4-library', 'version': 1, 'files': {'private': {}}}))
            with self.assertRaises(ValueError):
                assert_empty_seed(seed)

    def test_reviewed_source_requires_native_notices_and_rejects_private_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'reviewed'
            make_reviewed_tree(root)
            original = validate_public_source(root)
            for name, content in [('runs/private.csv', 'data'), ('benchmark_results.json', '{}'),
                                  ('desktop_session.json', '{}'), ('private-library.zip', 'opaque archive'),
                                  ('README.md', 'C:' + chr(92) + 'Users' + chr(92) + 'PrivateUser' + chr(92) + 'project')]:
                with self.subTest(name=name):
                    path = root/name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        validate_public_source(root)
                    path.unlink()
                    if path.parent != root:
                        path.parent.rmdir()
            self.assertEqual(validate_public_source(root), original)
            (root/'S4-source/COPYING').unlink()
            with self.assertRaises(ValueError):
                validate_public_source(root)

    def test_public_manifest_omits_builder_locations_and_private_bundle_identifiers(self):
        build = {'version': '1.0.3', 'build_date': '2026-09-13', 'profile': 'public',
                 'seed_files': 0, 'seed_runs': 0, 'seed_presets': 0,
                 'public_source_tree_sha256': 'reviewed', 'source': 'private location',
                 'data_bundle': 'private archive', 'data_bundle_sha256': 'private identifier'}
        result = public_build_info(build)
        self.assertNotIn('source', result)
        self.assertNotIn('data_bundle', result)
        self.assertNotIn('data_bundle_sha256', result)
        build['seed_runs'] = 1
        with self.assertRaises(ValueError):
            public_build_info(build)

    def test_public_preparation_cannot_copy_research_seed_from_private_input_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            builder, source, reviewed = root/'builder', root/'application', root/'reviewed'
            builder.mkdir()
            make_reviewed_tree(source)
            make_reviewed_tree(reviewed)
            for name in ('qt_chrome.py', 'update_client.py', 'update_credentials.py', 'backend.py',
                         'installer_smoke.py', 'pcs_s4_runtime/S4.cp312-win_amd64.pyd',
                         'ml_dependencies/sklearn/__init__.py'):
                path = source/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('build fixture', encoding='utf-8')
            (builder/'assets').mkdir()
            (builder/'assets/S4_Studio.ico').write_bytes(b'icon fixture')
            (builder/'tools').mkdir()
            with zipfile.ZipFile(builder/'tools/nvidia_cublas_cu11-1.whl', 'w') as archive:
                for name in ('cublas64_11.dll', 'cublasLt64_11.dll', 'cudart64_110.dll'):
                    archive.writestr(name, b'build fixture')
            bundle = root/'private-library.zip'
            data = {'runs/private/results.csv': b'private result',
                    'data_library/presets/private.json': b'{}',
                    'data_library/optical_constants/private.csv': b'private nk'}
            manifest = {'format': 's4-library', 'version': 1, 'files': {
                name: {'size': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
                for name, value in data.items()}}
            with zipfile.ZipFile(bundle, 'w') as archive:
                for name, value in data.items():
                    archive.writestr(name, value)
                archive.writestr('s4-library-manifest.json', json.dumps(manifest))
            command = ['prepare_payload.py', '--source', str(source), '--bundle', str(bundle),
                       '--profile', 'public', '--public-source', str(reviewed)]
            with patch.object(prepare_payload, 'ROOT', builder), patch('sys.argv', command), \
                 patch.object(prepare_payload, 'write_build_metadata',
                              side_effect=lambda src: build_version.write_build_metadata(src, builder)), \
                 contextlib.redirect_stdout(io.StringIO()):
                prepare_payload.main()
            assert_empty_seed(builder/'build_input/seed_library.zip')
            info = json.loads((builder/'build_input/build_input.json').read_text())
            self.assertEqual((info['seed_files'], info['seed_runs'], info['seed_presets']), (0, 0, 0))
            self.assertEqual(validate_public_source(builder/'build_input/public_source'), validate_public_source(reviewed))
            self.assertFalse((builder/'build_input/public_source/runs').exists())
            self.assertTrue((builder/'build_input/source/pcs_s4_runtime/S4.cp312-win_amd64.pyd').is_file())


if __name__ == '__main__':
    unittest.main()
