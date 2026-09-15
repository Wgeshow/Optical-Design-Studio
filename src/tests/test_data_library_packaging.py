"""Source exports retain rebuild assets while imports remain data-only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from data_library import DataLibrary


class PackagingExportTests(unittest.TestCase):
    def test_source_export_preserves_icon_build_scripts_and_assets_without_build_outputs(self):
        with tempfile.TemporaryDirectory(prefix='s4_source_export_') as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            marker = root / 'must-not-execute.txt'
            script = f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n'
            expected = {
                'qt_app.py': script.encode(),
                'S4_Studio.ico': b'original application icon',
                'packaging/build_windows.ps1': b'throw "must never execute during import"',
                'packaging/prepare_payload.py': script.encode(),
                'packaging/OpticalDesignStudio.spec': b'# PyInstaller build recipe',
                'packaging/OpticalDesignStudio.iss': b'; Inno Setup recipe',
                'packaging/BUILDING.md': b'Rebuild instructions',
                'packaging/assets/application.ico': b'installer icon',
                'packaging/assets/wizard.png': b'installer artwork',
                'packaging/assets/NOTICE': b'artwork notice',
                'packaging/scripts/verify.py': script.encode(),
            }
            omitted = {
                'packaging/tools/compiler.exe', 'packaging/work/analysis.json',
                'packaging/work_backend/cache.py', 'packaging/dist/app.exe',
                'packaging/build_input/source/qt_app.py', 'packaging/build/source/qt_app.py',
                'packaging/downloads/dependency.whl', 'packaging/release/Setup.exe',
                'packaging/payload/qt_app.py', 'packaging/scripts/__pycache__/cached.py',
                'packaging/.git/config.json', 'packaging/.venv/site.py',
                'packaging/venv/site.py', 'packaging/node_modules/build.js',
                'packaging/unrelated.exe', 'packaging/build.log',
            }
            for name, payload in expected.items():
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            for name in omitted:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'must not be bundled')
            original = DataLibrary(root / 'original')
            bundle = original.export(source_root=source)
            with zipfile.ZipFile(bundle) as archive:
                actual = set(archive.namelist()) - {'s4-library-manifest.json'}
                self.assertEqual(actual, set(expected))
                manifest = json.loads(archive.read('s4-library-manifest.json'))
                self.assertEqual(set(manifest['files']), set(expected))
                for name, payload in expected.items():
                    self.assertEqual(archive.read(name), payload)
            destination = DataLibrary(root / 'destination')
            installed = destination.root / 'qt_app.py'
            installed.write_text('existing installed program')
            with patch('subprocess.Popen') as popen, patch('subprocess.run') as run, patch('os.system') as system:
                result = destination.import_bundle(bundle)
            self.assertEqual(result, dict(runs=0, presets=0, assets=0))
            self.assertEqual(installed.read_text(), 'existing installed program')
            self.assertFalse((destination.root / 'packaging').exists())
            self.assertFalse((destination.root / 'S4_Studio.ico').exists())
            self.assertFalse(marker.exists())
            popen.assert_not_called()
            run.assert_not_called()
            system.assert_not_called()


if __name__ == '__main__':
    unittest.main()
