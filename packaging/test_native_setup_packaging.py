"""Ship the native setup modules/catalog; never stage user session JSON."""
import ast
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import stage_release as stage
import package_release as package
import verify_release

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'source' if (ROOT/'source').is_dir() else ROOT.parent/'src'
NEW_MODULES=('qt_simulation_setup','simulation_setup_state','qt_device_lighting',
    'qt_tool_workspace','qt_electrical_material_catalog','qt_results_workspace','qt_optical_results','qt_workspace_start')


def hidden_modules():
    tree=ast.parse((ROOT/'OpticalDesignStudio.spec').read_text('utf-8'))
    modules=[]
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='hidden' for target in node.targets):
            if isinstance(node.value,(ast.List,ast.Tuple)): modules.extend(ast.literal_eval(node.value))
        elif isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id=='hidden':
            if isinstance(node.value,(ast.List,ast.Tuple)): modules.extend(ast.literal_eval(node.value))
    return set(modules)


class NativeSetupPackagingTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='ods-setup-package-')
        self.addCleanup(self.directory.cleanup)
        self.base=Path(self.directory.name)

    def test_native_modules_compile_and_are_required_in_stage_and_both_executables(self):
        hidden=hidden_modules()
        for module in NEW_MODULES:
            with self.subTest(module=module):
                text=(SOURCE/(module+'.py')).read_text('utf-8')
                compile(text,module+'.py','exec')
                self.assertIn(module,hidden)
                self.assertIn(module,stage.REQUIRED_MODULES)
                self.assertIn(module,package.REQUIRED_FROZEN_MODULES)
                self.assertIn(module,verify_release.GUI_MODULES)
                self.assertIn(module,verify_release.BACKEND_MODULES)

    def test_local_transitive_imports_are_available_and_compile(self):
        # Static imports inside functions are included, matching PyInstaller's
        # analysis of the dynamic UI/backend entrypoints without importing Qt.
        pending=list(NEW_MODULES)+['fdtd_model','meep_runtime','meep_managed','meep_bootstrap']
        seen=set()
        while pending:
            module=pending.pop()
            if module in seen: continue
            seen.add(module)
            path=SOURCE/(module+'.py')
            self.assertTrue(path.is_file(),module)
            text=path.read_text('utf-8')
            compile(text,str(path),'exec')
            for node in ast.walk(ast.parse(text)):
                roots=[]
                if isinstance(node,ast.Import): roots=[alias.name.split('.')[0] for alias in node.names]
                elif isinstance(node,ast.ImportFrom) and node.module: roots=[node.module.split('.')[0]]
                pending.extend(name for name in roots if (SOURCE/(name+'.py')).is_file() and name not in seen)
        self.assertIn('electrical_material_library',seen)
        self.assertIn('custom_device_optics',seen)
        self.assertIn('structure_preview',seen)

    def test_runtime_catalog_has_all_tabs_and_is_explicit_spec_data(self):
        records=stage.validate_runtime_resources(SOURCE)
        self.assertEqual(records['simulation_setup_plan.json']['setup_tabs'],20)
        self.assertEqual(records['simulation_setup_plan.json']['sha256'],stage.digest(SOURCE/'simulation_setup_plan.json'))
        text=(ROOT/'OpticalDesignStudio.spec').read_text('utf-8')
        self.assertIn("(str(source/'simulation_setup_plan.json'), '.')",text)
        self.assertNotIn('.json',stage.SOURCE_SUFFIXES,'Do not admit session/project JSON by extension.')

    def test_staged_verification_exercises_new_setup_lighting_and_electrical_contracts(self):
        import test_release_source
        self.assertIn('tests.test_qt_simulation_setup',test_release_source.GROUPS['desktop-interface'])
        self.assertIn('tests.test_qt_device_lighting',test_release_source.GROUPS['desktop-interface'])
        self.assertIn('tests.test_qt_optical_results',test_release_source.GROUPS['desktop-interface'])
        for target in ('tests.test_qt_original_optical_workspace','tests.test_qt_workspace_start','tests.test_device_studio_help','tests.test_qt_setup_dispatch','tests.test_qt_startup_transition'):
            self.assertIn(target,test_release_source.GROUPS['desktop-interface'])
            self.assertTrue((SOURCE/'tests'/(target.split('.')[-1]+'.py')).is_file(),target)
        targets=test_release_source.GROUPS['device-electrical-and-coupled']
        for target in ('tests.test_simulation_setup_state','tests.test_electrical_terminal_studies',
                'tests.test_custom_device_optics','tests.test_pc_array','tests.test_optical_unit_cell','tests.test_pc_optical_defaults','tests.test_pc_library_roundtrip'):
            self.assertIn(target,targets)
        for target in targets:
            self.assertTrue((SOURCE/'tests'/(target.split('.')[-1]+'.py')).is_file(),target)
        recipe=(ROOT/'package_release.py').read_text('utf-8')
        self.assertIn("'test_native_setup_packaging.py'",recipe)
        self.assertIn("'test_native_setup_packaging.py'",(ROOT/'audit_source_recipe.py').read_text('utf-8'))

    def test_only_catalog_is_copied_and_bytes_match_the_authoritative_source(self):
        source=self.base/'source';target=self.base/'staged'
        source.mkdir();target.mkdir()
        shutil.copy2(SOURCE/'simulation_setup_plan.json',source/'simulation_setup_plan.json')
        shutil.copytree(SOURCE/'benchmark_data',source/'benchmark_data')
        (source/'desktop_session.json').write_text('{"private":true}')
        (source/'personal_project.json').write_text('{"private":true}')
        records=stage.copy_runtime_resources(source,target)
        self.assertEqual(list(target.iterdir()),[target/'simulation_setup_plan.json'])
        self.assertEqual(stage.digest(target/'simulation_setup_plan.json'),records['simulation_setup_plan.json']['sha256'])
        self.assertEqual((target/'simulation_setup_plan.json').read_bytes(),(SOURCE/'simulation_setup_plan.json').read_bytes())

    def test_missing_malformed_and_incomplete_catalogs_fail_before_staging(self):
        source=self.base/'source';source.mkdir()
        with self.assertRaisesRegex(FileNotFoundError,'Missing native setup'):
            stage.validate_runtime_resources(source)
        path=source/'simulation_setup_plan.json'
        path.write_text('{bad json')
        with self.assertRaisesRegex(ValueError,'Invalid native setup'):
            stage.validate_runtime_resources(source)
        plan=json.loads((SOURCE/'simulation_setup_plan.json').read_text('utf-8'))
        plan['modes']['electrical']['tabs'].pop()
        path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError,'tabs are incomplete'):
            stage.validate_runtime_resources(source)

    def test_full_stage_includes_catalog_inventory_and_rejects_missing_module(self):
        source=self.base/'source';source.mkdir()
        (source/'app_version.py').write_text(f"APP_VERSION={stage.VERSION!r}\nBUILD_DATE={stage.BUILD_DATE!r}\n")
        for module in stage.REQUIRED_MODULES:
            (source/(module+'.py')).write_text('VALUE = 1\n')
        shutil.copy2(SOURCE/'simulation_setup_plan.json',source/'simulation_setup_plan.json')
        shutil.copytree(SOURCE/'benchmark_data',source/'benchmark_data')
        (source/'desktop_session.json').write_text('{"private":true}')
        (source/'tests').mkdir()
        for folder in ('pcs_s4_runtime','help_assets','electrical_physics','electrical_materials'):
            (source/folder).mkdir()
        metadata=self.base/'metadata';metadata.mkdir()
        with patch.object(stage,'ROOT',metadata),patch.object(stage,'validate_dependencies',return_value={}),patch.object(stage,'sanitize_help',return_value={'scientific_csv_files':0,'scientific_csv_bytes_unchanged':True}):
            report=stage.stage(source,self.base/'staged')
            self.assertIn('simulation_setup_plan.json',report['files'])
            self.assertEqual(report['runtime_resources']['simulation_setup_plan.json']['setup_tabs'],20)
            self.assertNotIn('desktop_session.json',report['files'])
            self.assertEqual(report['files']['simulation_setup_plan.json']['sha256'],stage.digest(SOURCE/'simulation_setup_plan.json'))
            (source/'qt_device_lighting.py').unlink()
            with self.assertRaisesRegex(FileNotFoundError,'qt_device_lighting'):
                stage.stage(source,self.base/'incomplete-staged')


if __name__=='__main__':
    unittest.main(verbosity=2)
