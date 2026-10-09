"""Focused release-input checks; no PyInstaller build or publication."""
import ast
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import stage_release as stage

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent/'s4_ui_redesign'


class PackagingInputsTests(unittest.TestCase):
    def test_native_dependency_pins_and_unchanged_solver(self):
        report = stage.validate_dependencies(SOURCE)
        self.assertEqual(report['pyqtgraph'], '0.14.0')
        self.assertEqual(report['colorama'], '0.4.6')
        old = ROOT.parent/'release-1.2.9'/'source'/'pcs_s4_runtime'/'S4.cp312-win_amd64.pyd'
        self.assertEqual(stage.digest(old), report['pinned_native_inputs'][old.name]['sha256'])

    def test_public_help_copy_preserves_every_csv_and_has_exact_checksums(self):
        original = stage.inventory(SOURCE/'help_assets')
        with tempfile.TemporaryDirectory(prefix='packaging-help-', dir=ROOT) as directory:
            target = Path(directory)/'help_assets'
            shutil.copytree(SOURCE/'help_assets', target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            report = stage.sanitize_help(target)
            self.assertTrue(report['scientific_csv_bytes_unchanged'])
            self.assertGreaterEqual(report['scientific_csv_files'], 44)
            self.assertEqual(len(json.loads((target/'silicon-reference-run'/'field-samples.json').read_text())['samples']), 41)
            for name, record in original.items():
                if name.endswith('.csv'):
                    self.assertEqual(stage.digest(target/name), record['sha256'], name)
            bundle = json.loads((target/'silicon-reference-run'/'bundle.json').read_text())
            for record in bundle['files']:
                path = target/'silicon-reference-run'/record['file']
                self.assertEqual(record['bytes'], path.stat().st_size)
                self.assertEqual(record['sha256'], stage.digest(path))
                self.assertEqual(record['source'], record['file'])
            for record in json.loads((target/'manifest.json').read_text()):
                self.assertEqual(record['sha256'], stage.digest(target/record['asset']))
            self.assertFalse(stage.has_personal_path((target/'silicon-reference-run'/'provenance.json').read_text()))
        self.assertEqual(stage.inventory(SOURCE/'help_assets'), original, 'Original Help audit was modified')

    def test_privacy_check_distinguishes_documented_wsl_accounts(self):
        for value in ('/home/USER/miniforge3', '/home/alice/my env', '/home/ods', '/home/'):
            self.assertFalse(stage.has_personal_path(value), value)
        for value in ('C:/Users/ZhouGroup/Documents', r'C:\Users\ZhouGroup\Documents', '/home/private/research', '/Users/Owner/Desktop'):
            self.assertTrue(stage.has_personal_path(value), value)
        for path in SOURCE.iterdir():
            if path.is_file() and path.suffix in stage.SOURCE_SUFFIXES and path.suffix != '.ico' and path.name not in stage.EXCLUDED_FILES and not path.name.startswith(stage.EXCLUDED_PREFIXES):
                self.assertFalse(stage.has_personal_path(path.read_text(encoding='utf-8')), path.name)

    def test_spec_declares_native_runtime_and_agg_only(self):
        tree = ast.parse((ROOT/'OpticalDesignStudio.spec').read_text(encoding='utf-8'))
        assignments = {node.targets[0].id: node.value for node in tree.body
                       if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
        hidden = ast.literal_eval(assignments['hidden'])
        self.assertIn('qt_native_figure', hidden)
        self.assertIn('qt_native_field_volume', hidden)
        self.assertIn('qt_windows_glass', hidden)
        for module in ('scan_storage', 'field_sampling', 'simulation_fields', 'contour_sweep'):
            self.assertIn(module, hidden)
            self.assertIn(module, stage.REQUIRED_MODULES)
        self.assertIn('matplotlib.backends.backend_agg', hidden)
        self.assertFalse(any('qtagg' in name for name in hidden))
        analysis = assignments['a']
        settings = {keyword.arg: keyword.value for keyword in analysis.keywords}
        self.assertEqual(ast.literal_eval(settings['hooksconfig']), {'matplotlib': {'backends': ['Agg']}})
        self.assertIn('matplotlib.backends.backend_qtagg', ast.literal_eval(settings['excludes']))
        text = (ROOT/'OpticalDesignStudio.spec').read_text()
        self.assertIn("'plot_dependencies'", text)
        self.assertIn("source/'help_assets'", text)
        self.assertIn("copy_metadata(package)", text)
        self.assertIn("'pyqtgraph', 'colorama'", text)
        self.assertNotIn('C:\\Users', text)

    def test_public_bundle_paths_cannot_escape(self):
        for value in ('../credentials', '/absolute', 'C:/private', 'a\\b'):
            with self.assertRaises(ValueError):
                stage.safe_relative(value)
        self.assertEqual(stage.safe_relative('all-wavelength-fields/sample-000041.csv').as_posix(),
                         'all-wavelength-fields/sample-000041.csv')

    def test_performance_modules_are_required_in_both_frozen_executables(self):
        import package_release
        import verify_release
        import test_release_source
        for module in ('scan_storage', 'field_sampling', 'simulation_fields', 'contour_sweep'):
            self.assertIn(module, package_release.REQUIRED_FROZEN_MODULES)
            self.assertIn(module, verify_release.GUI_MODULES)
            self.assertIn(module, verify_release.BACKEND_MODULES)
            self.assertTrue((SOURCE/(module+'.py')).is_file())
        self.assertTrue(set([
            'tests.test_compute_speed', 'tests.test_scan_scaling',
            'tests.test_scan_scaling_ui', 'tests.test_backend',
            'tests.test_simulation_fields', 'tests.test_contour_sweep',
            'tests.test_field_tracking',
            'tests.test_contour_learning', 'tests.test_airhole_field_objective',
            'tests.test_target_fields', 'tests.test_field_ml',
            'tests.test_field_target_integration',
        ]) <= set(test_release_source.GROUPS['simulation-performance']))
        self.assertIn('tests.test_field_volume', test_release_source.GROUPS['scientific-rendering'])
        for target in ('tests.test_qt_core', 'tests.test_qt_chrome', 'tests.test_windows_desktop_glass'):
            self.assertIn(target, test_release_source.GROUPS['desktop-interface'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
