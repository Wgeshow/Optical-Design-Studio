"""Check that local archives cannot bypass independent frozen verification."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import package_release as package


class ReleaseVerificationGates(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='release-gate-')
        self.addCleanup(self.directory.cleanup)
        self.build = Path(self.directory.name)
        self.app = self.build/'dist'/'Optical Design Studio'
        self.verification = self.build/'verification'
        self.app.mkdir(parents=True)
        self.verification.mkdir()
        for name in ('Optical Design Studio.exe', 'OpticalDesignBackend.exe'):
            (self.app/name).write_bytes(name.encode())
        guide = self.app/'_internal'/'source'/'USER_GUIDE.html'
        guide.parent.mkdir(parents=True)
        guide.write_text('Public guide 1.3.2', encoding='utf-8')
        self.files = package.inventory(self.app)
        package.write_json(self.build/'stage-manifest.json', {
            'source_tree_sha256': 'approved-source',
            'files': {'USER_GUIDE.html': self.files['_internal/source/USER_GUIDE.html']}})
        package.write_json(self.app/'PAYLOAD-MANIFEST.json', {
            'version': '1.3.2', 'delivery_profile': 'public',
            'source_tree_sha256': 'approved-source', 'files': self.files})
        controls = dict(physical_model_unchanged=True, shared_settings_preview=True,
                        native_2d_canvases=True, native_3d_canvases=True,
                        live_matplotlib_qt_widgets=[])
        fields = dict(live_renderer='NativeVolumeCanvas', native_2d_field_maps=True,
                      native_orbit_and_zoom=True, actual_phase_vectors_verified=True,
                      saved_xyz_and_complex_fields_preserved=True,
                      live_publication_artists_created=False)
        self.report = dict(passed=True, version='1.3.2', frozen=True,
            executable=str(self.app/'Optical Design Studio.exe'), checks={
                'native_reference_controls_and_graphs': dict(passed=True, detail=controls),
                'native_electric_field_maps_and_features': dict(passed=True, detail=fields),
                'simulation_speed_and_scan_storage': dict(passed=True, detail=dict(
                    shared_spectrum_solutions=True, validated_fourier_sampling=True,
                    exact_disk_backed_spectrum=True, compact_scan_roundtrip=True, contour_label_parity=True,
                    field_sample_count=3)),
                'maximize_restore_painting': dict(passed=True, detail=dict(
                    maximized_opaque_workspace=True, restored_glass_policy=True,
                    looks=['glass_dark', 'glass_light'], native_compositor_supported=False))})
        package.write_json(self.verification/'report.json', self.report)
        self.audit = dict(executable_sha256=package.digest(self.app/'Optical Design Studio.exe'),
            manifest_sha256=package.digest(self.app/'PAYLOAD-MANIFEST.json'),
            delivery_profile='public', payload_files_verified=len(self.files),
            source_tree_sha256='approved-source', readable_source_files_verified=1,
            user_guide_sha256=package.digest(guide))
        package.write_json(self.verification/'payload-audit.json', self.audit)
        self.native_report=dict(passed=True,version='1.3.2',frozen=True,platform='windows',
            executable=str(self.app/'Optical Design Studio.exe'),checks={
                name:dict(passed=True,detail={}) for name in (
                    'initial_maximized_native_surface','restore_state','remaximize_native_surface',
                    'system_restore_state','system_maximize_native_surface')})
        native_report_path=self.verification/'native-startup-report.json'
        package.write_json(native_report_path,self.native_report)
        self.independent = dict(status='passed', version='1.3.2',
            application=str(self.app/'Optical Design Studio.exe'),
            report=str(self.verification/'report.json'),
            payload_audit=str(self.verification/'payload-audit.json'),
            source_python_used_by_application=False, native_fields_verified=True,
            payload_files_verified=len(self.files), source_tree_sha256='approved-source',
            readable_source_files_verified=1,native_startup_verified=True,
            native_startup_report=str(native_report_path),
            native_startup_report_sha256=package.digest(native_report_path),
            native_startup_executable_sha256=package.digest(self.app/'Optical Design Studio.exe'))
        package.write_json(self.verification/'independent-verification.json', self.independent)
        for name, value in (('BUILD', self.build), ('APP', self.app)):
            self.enterContext(patch.object(package, name, value))
        reader = SimpleNamespace(toc={'PYZ.pyz': None}, open_embedded_archive=lambda name:
            SimpleNamespace(toc=dict.fromkeys(package.REQUIRED_FROZEN_MODULES)))
        self.enterContext(patch('PyInstaller.archive.readers.CArchiveReader', return_value=reader))

    def test_verified_exact_executables_and_manifest_are_accepted(self):
        report, files = package.verify_frozen()
        self.assertEqual(report, self.report)
        self.assertEqual(files, self.files)

    def test_missing_simulation_module_in_either_executable_is_rejected(self):
        for executable in ('Optical Design Studio.exe', 'OpticalDesignBackend.exe'):
            for module in ('scan_storage', 'field_sampling', 'simulation_fields', 'contour_sweep'):
                with self.subTest(executable=executable, module=module):
                    def reader(path):
                        modules = set(package.REQUIRED_FROZEN_MODULES)
                        if Path(path).name == executable:
                            modules.remove(module)
                        return SimpleNamespace(toc={'PYZ.pyz': None}, open_embedded_archive=lambda name:
                            SimpleNamespace(toc=dict.fromkeys(modules)))
                    with patch('PyInstaller.archive.readers.CArchiveReader', side_effect=reader):
                        with self.assertRaisesRegex(ValueError, 'missing native runtime modules'):
                            package.verify_frozen()

    def test_incomplete_frozen_simulation_validation_is_rejected(self):
        check = self.report['checks']['simulation_speed_and_scan_storage']
        for field in ('shared_spectrum_solutions', 'validated_fourier_sampling',
                      'exact_disk_backed_spectrum', 'compact_scan_roundtrip',
                      'contour_label_parity', 'field_sample_count'):
            with self.subTest(field=field):
                changed = {**self.report, 'checks': {**self.report['checks'],
                    'simulation_speed_and_scan_storage': {**check, 'detail': {**check['detail'], field: False}}}}
                package.write_json(self.verification/'report.json', changed)
                with self.assertRaisesRegex(ValueError, 'Simulation solve reuse'):
                    package.verify_frozen()

    def test_incomplete_maximize_restore_validation_is_rejected(self):
        check = self.report['checks']['maximize_restore_painting']
        for field, value in (('maximized_opaque_workspace', False),
                             ('restored_glass_policy', False), ('looks', ['glass_dark'])):
            with self.subTest(field=field):
                changed = {**self.report, 'checks': {**self.report['checks'],
                    'maximize_restore_painting': {**check, 'detail': {**check['detail'], field: value}}}}
                package.write_json(self.verification/'report.json', changed)
                with self.assertRaisesRegex(ValueError, 'Maximized workspace painting'):
                    package.verify_frozen()

    def test_self_test_report_does_not_replace_independent_completion(self):
        (self.verification/'independent-verification.json').unlink()
        with self.assertRaises(FileNotFoundError):
            package.verify_frozen()

    def test_incomplete_or_other_application_verification_is_rejected(self):
        for change in ({'status': 'failed'}, {'source_python_used_by_application': True},
                       {'application': str(self.build/'old.exe')}, {'native_fields_verified': False},
                       {'native_startup_verified': False}):
            package.write_json(self.verification/'independent-verification.json',
                               {**self.independent, **change})
            with self.assertRaisesRegex(ValueError, 'Independent verification'):
                package.verify_frozen()

    def test_offscreen_checks_without_native_startup_report_are_rejected(self):
        (self.verification/'native-startup-report.json').unlink()
        with self.assertRaises(FileNotFoundError):
            package.verify_frozen()

    def test_changed_or_other_native_startup_report_is_rejected(self):
        for change in ({'native_startup_report_sha256':'stale-report'},
                       {'native_startup_executable_sha256':'stale-executable'},
                       {'native_startup_report':str(self.build/'other.json')}):
            with self.subTest(change=change):
                package.write_json(self.verification/'independent-verification.json',{**self.independent,**change})
                with self.assertRaisesRegex(ValueError,'native startup report'):
                    package.verify_frozen()

    def test_failed_or_non_native_startup_report_cannot_be_packaged(self):
        def write_native(report):
            path=self.verification/'native-startup-report.json'
            package.write_json(path,report)
            package.write_json(self.verification/'independent-verification.json',{
                **self.independent,'native_startup_report_sha256':package.digest(path)})
        for name in self.native_report['checks']:
            with self.subTest(check=name):
                write_native({**self.native_report,'checks':{
                    **self.native_report['checks'],name:dict(passed=False,detail={})}})
                with self.assertRaisesRegex(ValueError,'Real Windows native startup'):
                    package.verify_frozen()
        for change in ({'platform':'offscreen'},{'passed':False},{'frozen':False},
                       {'version':'1.3.1'},{'executable':str(self.build/'old.exe')}):
            with self.subTest(change=change):
                write_native({**self.native_report,**change})
                with self.assertRaisesRegex(ValueError,'Real Windows native startup'):
                    package.verify_frozen()

    def test_gui_executable_changed_after_audit_is_rejected(self):
        (self.app/'Optical Design Studio.exe').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'executable changed'):
            package.verify_frozen()

    def test_backend_changed_after_audit_is_rejected(self):
        (self.app/'OpticalDesignBackend.exe').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'An executable changed'):
            package.verify_frozen()

    def test_payload_manifest_changed_after_audit_is_rejected(self):
        with (self.app/'PAYLOAD-MANIFEST.json').open('a', encoding='utf-8') as stream:
            stream.write(' ')
        with self.assertRaisesRegex(ValueError, 'payload inventory changed'):
            package.verify_frozen()

    def test_scientific_native_feature_failure_is_rejected(self):
        self.report['checks']['native_electric_field_maps_and_features']['detail']['saved_xyz_and_complex_fields_preserved'] = False
        package.write_json(self.verification/'report.json', self.report)
        with self.assertRaisesRegex(ValueError, 'scientific arrays'):
            package.verify_frozen()

    def test_other_source_snapshot_or_incomplete_readable_source_is_rejected(self):
        for change in ({'source_tree_sha256': 'superseded-source'},
                       {'readable_source_files_verified': 0}, {'user_guide_sha256': 'superseded-guide'}):
            package.write_json(self.verification/'payload-audit.json', {**self.audit, **change})
            with self.assertRaisesRegex(ValueError, 'every readable source'):
                package.verify_frozen()


if __name__ == '__main__':
    unittest.main(verbosity=2)
