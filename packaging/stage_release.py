"""Stage the approved public desktop source; never build, install or publish it."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = '1.4.0-alpha.1'
BUILD_DATE = '2026-10-15'
PINNED_INPUTS = Path(os.environ.get('ODS_NATIVE_INPUTS', ROOT.parent/'local-windows-review-1.2.5-ui-review2'/'build_input'))
SOURCE_SUFFIXES = {'.py', '.md', '.txt', '.yml', '.yaml', '.cmd', '.sh', '.ps1', '.ico', '.html'}
EXCLUDED_PREFIXES = ('_', 'preview_', 'check_', 'profile_', 'debug_', 'capture_', 'illustrate_', 'replace_ui_')
EXCLUDED_FILES = {'start_ui_preview.py', 'build_native_addons.py', 'bundle_silicon_help.py',
                  'TEST_REPORT.md', 'UI_TEST_REPORT.md', 'DESKTOP_TEST_REPORT.md', 'RELEASE_NOTES_1.2.6.md'}
PERSONAL_PATH = re.compile(r'''(?i)(?:[a-z]:[\\/]+Users[\\/]+[^\\/\s"'<>]+|/(?:Users|home)/[^/\s"'<>]+)''')
REQUIRED_MODULES = ('qt_native_plot', 'qt_native_figure', 'qt_native_field_volume',
                    'qt_field_volume', 'qt_structure_3d', 'qt_lattice_diagram',
                    'qt_windows_glass', 'qt_help', 'qt_appearance', 'qt_surfaces',
                    'model', 'fdtd_model', 'data_library', 'installer_smoke',
                    'scan_storage', 'field_sampling', 'field_reconstruction', 'field_storage', 'direct_npz', 'simulation_fields', 'contour_sweep',
                    'eigenfree_scan', 's4_eigenfree_gpu', 'gpu_solver_runtime',
                    'qt_electrical', 'electrical_solver', 'electrical_optics', 'electrical_preset',
                    'qt_custom_device','device_model','device_project_bridge','custom_electrical_solver',
                    'custom_device_optics','electrical_material_library','qt_electrical_materials',
                    'electrical_terminal_studies','electrical_thermal','research_simulation','photonic_bands','electrical_mesh','electrical_sweep',
                    'research_catalog','research_diagnostics','thermal_study','benchmark_registry',
                    'research_physics_runtime','research_physics_worker','sesame_transport',
                    'input_diagnostics','qt_input_diagnostics','qt_photonic_bands','qt_photonic_band_results','qt_photonic_crystal_3d','qt_photonic_runtime','qt_research_studies','qt_research_results','qt_thermal_setup',
                    'qt_study_flow','qt_simulation_flow','qt_legacy_study_workbench','qt_study_fields','qt_study_library', 'qt_simulation_picker','qt_transport_research_setup','qt_high_field_results','qt_pcsel_research_setup','qt_research_runtime',
                    'qt_research_common','qt_sesame_setup','pcsel_research','pcsel_aperture','pcsel_optional','pcsel_physics_worker',
                    'advanced_transport','advanced_transport_graph','electrical_temperature','nonlocal_tunnelling','high_field_optics','bandgap_narrowing',
                    'pcsel_transport_study','pcsel_conformal_mesh','pcsel_conformal_solver','pcsel_transport_worker','pcsel_unitcell_transport',
                    'electrical_transport','electrical_graph_transport','electrical_fermi_transport',
                    'electrical_native_graph','electrical_transport_adapter','qt_transport_setup',
                    'qt_electrical_results','contact_optics',
                    'qt_reference_style','qt_results_workspace','optical_unit_cell','pc_array',
                    'qt_simulation_setup','simulation_setup_state','qt_device_lighting',
                    'qt_tool_workspace','qt_electrical_material_catalog','qt_optical_results','qt_workspace_start','meep_runner',
                    'meep_runtime','meep_managed','meep_bootstrap','structure_preview')
REQUIRED_RESOURCES = ('simulation_setup_plan.json',)


def validate_benchmark_resources(source):
    """Require immutable case/reference checksums in the distributable bundle."""
    root = (Path(source)/'benchmark_data').resolve()
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or not manifest.get('cases'):
        raise ValueError('The benchmark reference catalog is missing or invalid.')
    identifiers = set()
    for case in manifest['cases']:
        if case['id'] in identifiers:
            raise ValueError('Duplicate benchmark reference identity.')
        identifiers.add(case['id'])
        if case['case_file'] not in case['files']:
            raise ValueError('Benchmark case inputs are missing their checksum.')
        for name, expected in case['files'].items():
            path = (root/name).resolve()
            if not path.is_relative_to(root) or not path.is_file() or digest(path) != expected:
                raise ValueError('Benchmark reference checksum/path mismatch: '+name)
            if path.suffix in ('.json', '.csv') and has_personal_path(path.read_text(encoding='utf-8').replace('\\\\', '\\')):
                raise ValueError('Personal path in benchmark reference: '+name)
    return dict(cases=len(identifiers), manifest_sha256=digest(root/'manifest.json'))


def validate_runtime_resources(source):
    """Gate required UI catalogs without admitting arbitrary session JSON."""
    source=Path(source)
    records={}
    for name in REQUIRED_RESOURCES:
        path=source/name
        if not path.is_file(): raise FileNotFoundError('Missing native setup runtime resource: '+name)
        text=path.read_text(encoding='utf-8')
        if has_personal_path(text.replace('\\\\','\\')):
            raise ValueError('Personal path in native setup runtime resource: '+name)
        try:
            plan=json.loads(text)
            modes=plan['modes']
            if set(modes)!={'optical','electrical','coupled'}: raise ValueError('Expected all three solver modes')
            ids=[]
            for mode,count in (('optical',7),('electrical',7),('coupled',6)):
                tabs=modes[mode]['tabs']
                if len(tabs)!=count: raise ValueError(mode+' setup tabs are incomplete')
                for tab in tabs:
                    if not tab['id'].startswith(mode+'.') or not tab.get('title'): raise ValueError('Invalid setup tab identity')
                    ids.append(tab['id'])
                    for card in tab.get('cards',[]):
                        for field in card.get('fields',[]):
                            if not {'id','label','widget','key','default'}<=set(field): raise ValueError('Incomplete setup control')
                            ids.append(field['id'])
            if len(ids)!=len(set(ids)): raise ValueError('Duplicate setup tab/control IDs')
            if not isinstance(plan.get('dialogs'),list) or not plan['dialogs']: raise ValueError('Setup dialogs are absent')
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError('Invalid native setup runtime resource '+name+': '+str(exc)) from exc
        records[name]={'size':path.stat().st_size,'sha256':digest(path),'setup_tabs':sum(len(mode['tabs']) for mode in modes.values())}
    return records


def copy_runtime_resources(source,destination):
    """Copy only explicitly required catalogs, preserving their exact bytes."""
    records=validate_runtime_resources(source)
    for name in REQUIRED_RESOURCES:
        shutil.copy2(Path(source)/name,Path(destination)/name)
        if digest(Path(destination)/name)!=records[name]['sha256']:
            raise ValueError('Native setup runtime resource bytes changed: '+name)
    return records


def has_personal_path(text):
    # These are documented WSL placeholders or the managed runtime's service
    # account. Preserve executable commands/examples; permit no other accounts.
    for match in PERSONAL_PATH.finditer(text):
        path = match[0].replace('\\', '/')
        if path in ('/home/alice', '/home/USER', '/home/ods'):
            continue
        return True
    return False


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def inventory(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): {'size': p.stat().st_size, 'sha256': digest(p)}
            for p in sorted(root.rglob('*')) if p.is_file() and
            '__pycache__' not in p.parts and p.suffix != '.pyc'}


def tree_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def release_info(source):
    values = {}
    for node in ast.parse((Path(source)/'app_version.py').read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('APP_VERSION', 'BUILD_DATE'):
                    values[target.id] = ast.literal_eval(node.value)
    if values != {'APP_VERSION': VERSION, 'BUILD_DATE': BUILD_DATE}:
        raise ValueError(f'Expected approved {VERSION}/{BUILD_DATE}, received {values}.')
    return {'version': VERSION, 'build_date': BUILD_DATE}


def safe_relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '\\' in value or ':' in value:
        raise ValueError(f'Unsafe public bundle file: {value}')
    return path


def public_capture_path(value):
    """Rebase original capture metadata without changing scientific values."""
    if not isinstance(value, str) or not has_personal_path(value):
        return value
    path = value.replace('\\', '/')
    lower = path.casefold()
    if lower.endswith('/python.exe') or lower.endswith('/pythonw.exe'):
        return 'Python 3.12 build interpreter; the portable application includes its own runtime'
    if '/pcs_s4_runtime/' in lower:
        return 'pcs_s4_runtime/'+path.split('/pcs_s4_runtime/', 1)[1]
    if '/help_assets/' in lower:
        return 'help_assets/'+path.split('/help_assets/', 1)[1]
    if '/s4_ui_redesign/' in lower:
        return path.split('/s4_ui_redesign/', 1)[1]
    match = re.search(r'/convergence-basis-(\d+)-verified(?:/(.*))?$', path)
    if match:
        return 'basis-'+match[1]+('/'+match[2] if match[2] else '')
    match = re.search(r'/isolated_library/runs/[^/]+(?:/(.*))?$', path)
    if match:
        relative = match[1] or '.'
        if relative == 'fields/samples.json':
            return 'field-samples.json'
        sample = re.fullmatch(r'fields/samples/(\d+)(?:/(.*))?', relative)
        if sample:
            # Point indices differ from ordinal saved-file names. The original
            # directory identifier is retained rather than inventing a binding.
            return 'original-capture/fields/samples/'+sample[1]+('/'+sample[2] if sample[2] else '')
        if relative.startswith('fields/'):
            return relative.split('/', 1)[1]
        return relative
    if '/silicon-help-simulation/' in lower:
        return path.split('/silicon-help-simulation/', 1)[1]
    return 'original-capture/'+path.rsplit('/', 1)[-1]


def rebase_metadata(value):
    if isinstance(value, dict):
        return {public_capture_path(key): rebase_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rebase_metadata(item) for item in value]
    return public_capture_path(value)


def sanitize_help(root):
    root = Path(root)
    before = inventory(root)
    csv_before = {name: record for name, record in before.items() if name.endswith('.csv')}
    changed = {}
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.suffix not in ('.json', '.jsonl'):
            continue
        if path.name == 'bundle.json':
            continue
        original = path.read_text(encoding='utf-8')
        if not has_personal_path(original.replace('\\\\', '\\')):
            continue
        if path.suffix == '.jsonl':
            records = [rebase_metadata(json.loads(line)) for line in original.splitlines() if line.strip()]
            path.write_text(''.join(json.dumps(item, ensure_ascii=False)+'\n' for item in records), encoding='utf-8')
        else:
            write_json(path, rebase_metadata(json.loads(original)))
        changed[path.relative_to(root).as_posix()] = before[path.relative_to(root).as_posix()]['sha256']
    run = root/'silicon-reference-run'
    provenance_path = run/'provenance.json'
    provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
    provenance['source_project'] = 'help_assets/air-hole-example.json'
    provenance['fields']['displayed_directory'] = '.'
    provenance['actual_run_directory'] = '.'
    provenance['scientific_validation'] = 'scientific-validation.json'
    provenance['helper'] = 'run_and_capture.py'
    provenance['helper_sha256'] = digest(run/'run_and_capture.py')
    provenance['public_release_copy'] = {
        'metadata_paths_rebased': True, 'scientific_csv_bytes_unchanged': True,
        'original_provenance_sha256': before['silicon-reference-run/provenance.json']['sha256'],
        'original_capture_hashes': 'source_code_sha256 and capture_refresh retain the original capture evidence',
        'original_metadata_sha256': changed,
    }
    write_json(provenance_path, provenance)
    bundle_path = run/'bundle.json'
    bundle = rebase_metadata(json.loads(bundle_path.read_text(encoding='utf-8')))
    for record in bundle['files']:
        path = run.joinpath(*safe_relative(record['file']).parts)
        if not path.is_file():
            raise FileNotFoundError(path)
        record['source'] = record['file']
        record['bytes'], record['sha256'] = path.stat().st_size, digest(path)
    bundle['public_release_copy'] = {'metadata_paths_rebased': True, 'scientific_csv_bytes_unchanged': True}
    write_json(bundle_path, bundle)
    manifest_path = root/'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for record in manifest:
        path = root.joinpath(*safe_relative(record['asset']).parts)
        if not path.is_file():
            raise FileNotFoundError(path)
        record['sha256'] = digest(path)
        if has_personal_path(str(record.get('source', ''))):
            record['source'] = 'original-capture/'+Path(record['source'].replace('\\', '/')).name
    write_json(manifest_path, manifest)
    after = inventory(root)
    if csv_before != {name: record for name, record in after.items() if name.endswith('.csv')}:
        raise ValueError('The public Help copy changed scientific CSV data.')
    for path in root.rglob('*'):
        if path.is_file() and path.suffix in ('.json', '.jsonl', '.py', '.txt'):
            if has_personal_path(path.read_text(encoding='utf-8').replace('\\\\', '\\')):
                raise ValueError(f'Personal capture path remains: {path.relative_to(root)}')
    return {'scientific_csv_files': len(csv_before), 'scientific_csv_bytes_unchanged': True,
            'metadata_rebased': sorted(changed), 'files': after}


def selected_s4_runtime(source):
    """Choose an explicit reviewed runtime without modifying production files."""
    return Path(os.environ.get('ODS_S4_RUNTIME') or Path(source)/'pcs_s4_runtime').resolve()


def validate_dependencies(source):
    import importlib.metadata
    import importlib.util
    official = Path(os.environ['ODS_OFFICIAL_RUNTIME'])
    pins = {'pyqtgraph': '0.14.0', 'colorama': '0.4.6'}
    versions = {}
    for package in ('pyqtgraph', 'colorama', 'scikit-learn', 'scipy', 'shapely'):
        versions[package] = importlib.metadata.version(package)
        if package in pins and versions[package] != pins[package]:
            raise ValueError('Unexpected dependency version: ' + package)
    for module in ('pyqtgraph', 'colorama', 'sklearn', 'scipy', 'shapely'):
        if importlib.util.find_spec(module) is None:
            raise ImportError(module)
    required = [selected_s4_runtime(source)/'S4.cp312-win_amd64.pyd',
                official/'cad_runtime'/'OCP'/'__init__.py']
    required += [PINNED_INPUTS/'gpu'/name for name in
                 ('cublas64_11.dll', 'cublasLt64_11.dll', 'cudart64_110.dll')]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    return dict(installed_versions=versions, s4_runtime_override_used=True,
                official_runtime_reused=True,
                pinned_native_inputs={path.name: {'size': path.stat().st_size, 'sha256': digest(path)}
                                      for path in required if path.suffix in ('.pyd', '.dll')})


def stage(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    release = release_info(source)
    dependencies = validate_dependencies(source)
    runtime_resources=validate_runtime_resources(source)
    validate_benchmark_resources(source)
    if destination.exists():
        raise FileExistsError('Use fresh staging; no previous release is overwritten: '+str(destination))
    if destination == source or destination.is_relative_to(source):
        raise ValueError('Stage outside the production source.')
    destination.mkdir(parents=True)
    copied = {}
    for path in source.iterdir():
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES and path.name not in EXCLUDED_FILES and not path.name.startswith(EXCLUDED_PREFIXES):
            if has_personal_path(path.read_text(encoding='utf-8', errors='ignore')) and path.suffix != '.ico':
                raise ValueError('Developer path in distributable production file: '+path.name)
            shutil.copy2(path, destination/path.name)
            copied[path.name] = digest(path)
    copy_runtime_resources(source,destination)
    copied.update({name:record['sha256'] for name,record in runtime_resources.items()})
    for folder,origin in (('pcs_s4_runtime',selected_s4_runtime(source)),('help_assets',source/'help_assets'),
                          ('electrical_physics',source/'electrical_physics'),
                          ('electrical_materials',source/'electrical_materials'),
                          ('benchmark_data',source/'benchmark_data')):
        shutil.copytree(origin, destination/folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (destination/'tests').mkdir()
    for path in (source/'tests').glob('test_*.py'):
        if has_personal_path(path.read_text(encoding='utf-8')):
            raise ValueError('Developer path in distributable test: '+path.name)
        shutil.copy2(path, destination/'tests'/path.name)
    test_init = source/'tests'/'__init__.py'
    if test_init.is_file():
        shutil.copy2(test_init, destination/'tests'/'__init__.py')
    else:
        (destination/'tests'/'__init__.py').write_text('', encoding='utf-8')
    help_check = sanitize_help(destination/'help_assets')
    for module in REQUIRED_MODULES:
        if not (destination/(module+'.py')).is_file():
            raise FileNotFoundError(module)
        compile((destination/(module+'.py')).read_text(encoding='utf-8'),module+'.py','exec')
    for name, sha in copied.items():
        if digest(destination/name) != sha:
            raise ValueError('Production bytes changed: '+name)
    files = inventory(destination)
    summary = {**release, 'profile': 'public', 'production_bytes_preserved': True,
               'seed_files': 0, 'seed_runs': 0, 'seed_presets': 0,
               'dependencies': dependencies, 'help': help_check,
               'runtime_resources':runtime_resources,
               'files': files, 'source_tree_sha256': tree_digest(files)}
    write_json(ROOT/'stage-manifest.json', summary)
    write_json(ROOT/'source-stage-manifest.json', {'version': VERSION, 'build_date': BUILD_DATE,
               'tree_sha256': summary['source_tree_sha256'], 'files': files})
    with zipfile.ZipFile(ROOT/'seed_library.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('s4-library-manifest.json', json.dumps({'format': 's4-library', 'version': 1, 'files': {}}))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parent/'s4_ui_redesign')
    parser.add_argument('--destination', type=Path, default=ROOT/'source')
    args = parser.parse_args()
    report = stage(args.source, args.destination)
    print(json.dumps({key: report[key] for key in ('version', 'build_date', 'profile', 'production_bytes_preserved', 'source_tree_sha256')}))


if __name__ == '__main__':
    main()
