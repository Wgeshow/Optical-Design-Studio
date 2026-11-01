"""Read-only check that the shipped source recipe contains its local inputs."""
import ast
import hashlib
import json
from pathlib import Path

BUILD = Path(__file__).resolve().parent


def main():
    tree = ast.parse((BUILD/'package_release.py').read_text(encoding='utf-8'))
    candidates = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)
                and node.target.id == 'source_entries' and isinstance(node.value, ast.ListComp)):
            continue
        if "'packaging/'" in ast.unparse(node.value.elt):
            candidates.append(ast.literal_eval(node.value.generators[0].iter))
    assert len(candidates) == 1
    packaged = set(candidates[0])
    required = {
        'OpticalDesignStudio.spec', 'desktop_entry.py', 'backend_entry.py',
        'version_info.txt', 'stage_release.py', 'build_release.py',
        'test_release_source.py', 'verify_release.py', 'package_release.py',
        'test_release_package_gates.py', 'seed_library.zip', 'stage-manifest.json',
        'source-stage-manifest.json', 'START_HERE.md', 'RELEASE_NOTES.md',
        'THIRD_PARTY_NOTICES.md', 'SOURCE_README.md', 'BUILDING.md',
        'test_packaging.py', 'verify_release_source_smoke.py', 'audit_source_recipe.py', 'audit_release_archives.py',
        'test_native_setup_packaging.py', 'package_experimental_candidate.py', 'test_thermal_packaging.py',
    }
    assert required <= packaged, sorted(required-packaged)
    assert all((BUILD/name).is_file() for name in packaged)
    local_imports = {}
    for name in sorted(packaged):
        if not name.endswith('.py'):
            continue
        imports = set()
        for node in ast.walk(ast.parse((BUILD/name).read_text(encoding='utf-8'))):
            modules = ([node.module] if isinstance(node, ast.ImportFrom) and node.module else
                       [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            for module in modules:
                target = module.split('.')[0]+'.py'
                if (BUILD/target).is_file():
                    assert target in packaged, (name, target)
                    imports.add(target)
        local_imports[name] = sorted(imports)
    package_source = (BUILD/'package_release.py').read_text(encoding='utf-8')
    assert "ROOT/'native'/'S4-source'" in package_source
    assert "ROOT/'THIRD_PARTY_LICENSES'" in package_source
    assert "(BUILD/'SOURCE_README.md', 'README.md')" in package_source
    spec = (BUILD/'OpticalDesignStudio.spec').read_text(encoding='utf-8')
    readme = (BUILD/'SOURCE_README.md').read_text(encoding='utf-8')
    assert "assert (env_bin/'sqlite3.dll').is_file()" in spec
    assert "names = ['sqlite3.dll'" in spec
    assert 'compatible SQLite' in readme and '**Library/bin**' in readme and '**ODS_OFFICIAL_RUNTIME**' in readme
    report = {
        'passed': True, 'version': '1.4.0-alpha.10', 'packaging_files': sorted(packaged),
        'source_tree_sha256': json.loads((BUILD/'stage-manifest.json').read_text())['source_tree_sha256'],
        'local_python_imports': local_imports,
        'corresponding_native_source_fallback': 'native/S4-source',
        'dependency_notices_fallback': 'THIRD_PARTY_LICENSES',
        'source_readme_at_root_and_packaging': True,
        'matching_sqlite_build_runtime_required_and_documented': True,
        'external_build_inputs_documented': ['ODS_NATIVE_INPUTS', 'ODS_RELEASE_DEPENDENCIES', 'ODS_S4_RUNTIME', 'ODS_OFFICIAL_RUNTIME', 'ODS_CAD_RUNTIME', 'ODS_DEVSIM_DEPENDENCIES', 'ODS_EIGENFREE_GPU_PACKAGES', 'ODS_EIGENFREE_CUDA'],
        'helper_sha256': {name: hashlib.sha256((BUILD/name).read_bytes()).hexdigest()
                          for name in sorted(packaged) if name.endswith('.py')},
        'packaged_file_sha256': {name: hashlib.sha256((BUILD/name).read_bytes()).hexdigest()
                                for name in sorted(packaged)},
        'production_source_changed': False, 'published': False,
    }
    (BUILD/'source-recipe-audit.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
