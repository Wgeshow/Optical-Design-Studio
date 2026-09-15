"""Regression checks for dependency closure and safe x64 augmentation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import augment_native_runtime as native


class NativeAugmentationTests(unittest.TestCase):
    def test_missing_dependencies_are_recursive_and_existing_files_are_not_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload, environment = root / 'payload', root / 'environment'
            internal, libraries = payload / '_internal', environment / 'Library' / 'bin'
            internal.mkdir(parents=True)
            libraries.mkdir(parents=True)
            def binary(path, imports=(), machine=native.AMD64, extra=None):
                path.write_text(json.dumps(dict(imports=list(imports), machine=machine, extra=extra)))
            def imports(path):
                data = json.loads(path.read_text())
                return data['machine'], data['imports']
            binary(payload / 'Optical Design Studio.exe', ['codec.dll', 'existing.dll', 'KERNEL32.dll'])
            binary(internal / 'existing.dll', extra='keep original')
            original = (internal / 'existing.dll').read_bytes()
            binary(libraries / 'existing.dll', extra='must never replace existing')
            binary(libraries / 'codec.dll', ['transitive.dll'])
            binary(libraries / 'transitive.dll', ['api-ms-win-crt-runtime-l1-1-0.dll'])
            with patch.object(native, 'pe_imports', side_effect=imports):
                dry_run = native.augment(payload, environment, audit_only=True)
                self.assertTrue(dry_run['passed'])
                self.assertEqual({entry['dependency'] for entry in dry_run['would_copy']}, {'codec.dll', 'transitive.dll'})
                self.assertFalse((internal / 'codec.dll').exists())
                applied = native.augment(payload, environment)
                self.assertTrue(applied['passed'])
                self.assertEqual({entry['dependency'] for entry in applied['copied']}, {'codec.dll', 'transitive.dll'})
                self.assertEqual((internal / 'existing.dll').read_bytes(), original)
                again = native.augment(payload, environment)
                self.assertTrue(again['passed'])
                self.assertEqual(again['copied'], [])

    def test_32_bit_dependency_is_rejected_and_optional_mkl_missing_import_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload, environment = root / 'payload', root / 'environment'
            internal, libraries = payload / '_internal', environment / 'Library' / 'bin'
            internal.mkdir(parents=True)
            libraries.mkdir(parents=True)
            (payload / 'Optical Design Studio.exe').write_bytes(b'exe')
            (internal / 'mkl_pgi_thread.2.dll').write_bytes(b'optional MKL variant')
            (libraries / 'wrong.dll').write_bytes(b'32 bit dependency')
            def imports(path):
                if path.name == 'Optical Design Studio.exe':
                    return native.AMD64, ['wrong.dll']
                if path.name == 'mkl_pgi_thread.2.dll':
                    return native.AMD64, ['pgf90.dll']
                return 0x14c, []
            with patch.object(native, 'pe_imports', side_effect=imports):
                report = native.augment(payload, environment)
            self.assertFalse(report['passed'])
            self.assertFalse((internal / 'wrong.dll').exists())
            self.assertEqual(report['unresolved'][0]['dependency'], 'wrong.dll')
            self.assertEqual(report['unresolved'][0]['rejected_candidates'][0]['machine'], '0x14c')
            self.assertEqual(report['optional_unresolved'][0]['dependency'], 'pgf90.dll')

    def test_vtk_wheel_dlls_are_copied_to_ocp_search_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload, environment = root/'payload', root/'environment'
            internal = payload/'_internal'
            vtk = root/'vtk.libs'
            internal.mkdir(parents=True)
            (environment/'Library'/'bin').mkdir(parents=True)
            vtk.mkdir()
            (payload/'Optical Design Studio.exe').write_text('exe')
            (vtk/'vtkCommonCore.dll').write_text('vtk')

            def imports(path):
                return (native.AMD64, ['vtkCommonCore.dll']) if path.name.endswith('.exe') else (native.AMD64, [])

            with patch.object(native, 'pe_imports', side_effect=imports):
                report = native.augment(payload, environment, extra=[vtk])
            self.assertTrue(report['passed'])
            self.assertTrue((internal/'cad_runtime'/'vtk.libs'/'vtkCommonCore.dll').is_file())

    def test_ocp_wheel_dlls_are_copied_to_ocp_search_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload, environment = root/'payload', root/'environment'
            internal = payload/'_internal'
            ocp = root/'cadquery_ocp.libs'
            internal.mkdir(parents=True)
            (environment/'Library'/'bin').mkdir(parents=True)
            ocp.mkdir()
            (payload/'Optical Design Studio.exe').write_text('exe')
            (ocp/'TKernel-hash.dll').write_text('ocp')

            def imports(path):
                return (native.AMD64, ['TKernel-hash.dll']) if path.name.endswith('.exe') else (native.AMD64, [])

            with patch.object(native, 'pe_imports', side_effect=imports):
                report = native.augment(payload, environment, extra=[ocp])
            self.assertTrue(report['passed'])
            self.assertTrue((internal/'cad_runtime'/'cadquery_ocp.libs'/'TKernel-hash.dll').is_file())


if __name__ == '__main__':
    unittest.main()
