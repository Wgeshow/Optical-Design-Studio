"""Package a verified public portable/source release; never upload or install it."""
from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path
import shutil
import zipfile

from stage_release import digest, inventory, safe_relative, tree_digest, write_json

BUILD = Path(__file__).resolve().parent
ROOT = BUILD.parent
SRC = BUILD/'source'
APP = BUILD/'dist'/'Optical Design Studio'
OUT = ROOT/'GitHub-Release-1.3.2'
VERSION = '1.3.2'
REQUIRED_FROZEN_MODULES = ('field_volume', 'qt_field_volume', 'qt_native_field_volume',
    'qt_native_figure', 'qt_native_plot', 'qt_structure_3d', 'qt_lattice_diagram',
    'qt_windows_glass', 'qt_help', 'qt_materials', 'qt_core', 'data_library',
    'field_solver', 'field_tracking', 'update_install', 'pyqtgraph', 'colorama',
    'scan_storage', 'field_sampling', 'simulation_fields', 'contour_sweep')
FORBIDDEN_FILES = {'user data', 'data_library', 'runs', '.git', '.env',
    'portable_settings.json', 'desktop_preferences.ini', 'session.json', 'desktop_session.json'}


def verify_stage():
    stage = json.loads((BUILD/'stage-manifest.json').read_text(encoding='utf-8'))
    if stage['version'] != VERSION or stage['profile'] != 'public' or not stage['production_bytes_preserved']:
        raise ValueError('Only the approved public source snapshot can be packaged.')
    if any(stage[name] != 0 for name in ('seed_files', 'seed_runs', 'seed_presets')):
        raise ValueError('The public application seed must be empty.')
    current = inventory(SRC)
    if current != stage['files'] or tree_digest(current) != stage['source_tree_sha256']:
        raise ValueError('Source changed after staging; stage and verify a fresh snapshot.')
    tests = json.loads((BUILD/'source-test-report.json').read_text(encoding='utf-8'))
    if not (tests['passed'] is True and tests['tests_run'] > 0 and tests['failures'] == 0 and tests['errors'] == 0
            and tests['source_tree_sha256'] == stage['source_tree_sha256']):
        raise ValueError('Source tests must pass against this exact staged tree.')
    build = json.loads((BUILD/'build-report.json').read_text(encoding='utf-8'))
    if not (build['passed'] is True and build['exit_code'] == 0 and build['version'] == VERSION
            and build['source_tree_sha256'] == stage['source_tree_sha256']):
        raise ValueError('Both executable builds must pass against this exact staged tree.')
    return stage, tests


def verify_frozen():
    from PyInstaller.archive.readers import CArchiveReader
    verification = BUILD/'verification'
    report = json.loads((verification/'report.json').read_text(encoding='utf-8'))
    if not (report['passed'] is True and report['version'] == VERSION and report['frozen'] is True):
        raise ValueError('The actual frozen application must pass its self-test.')
    if Path(report['executable']).resolve() != (APP/'Optical Design Studio.exe').resolve():
        raise ValueError('Frozen verification belongs to another application path.')
    independent = json.loads((verification/'independent-verification.json').read_text(encoding='utf-8'))
    if not (independent['status'] == 'passed' and independent['version'] == VERSION
            and Path(independent['application']).resolve() == (APP/'Optical Design Studio.exe').resolve()
            and Path(independent['report']).resolve() == (verification/'report.json').resolve()
            and Path(independent['payload_audit']).resolve() == (verification/'payload-audit.json').resolve()
            and independent['source_python_used_by_application'] is False
            and independent['native_fields_verified'] is True
            and independent.get('native_startup_verified') is True):
        raise ValueError('Independent verification must finish successfully for this exact application.')
    audit = json.loads((verification/'payload-audit.json').read_text(encoding='utf-8'))
    if audit['executable_sha256'] != digest(APP/'Optical Design Studio.exe'):
        raise ValueError('The executable changed after independent verification.')
    if audit['manifest_sha256'] != digest(APP/'PAYLOAD-MANIFEST.json'):
        raise ValueError('The payload inventory changed after independent verification.')
    native_report_path=verification/'native-startup-report.json'
    if not (Path(independent.get('native_startup_report','')).resolve()==native_report_path.resolve()
            and independent.get('native_startup_report_sha256')==digest(native_report_path)
            and independent.get('native_startup_executable_sha256')==digest(APP/'Optical Design Studio.exe')):
        raise ValueError('The native startup report must match the independently verified executable.')
    from verify_release import validate_native_startup
    try:
        validate_native_startup(json.loads(native_report_path.read_text(encoding='utf-8')),APP/'Optical Design Studio.exe')
    except (AssertionError,TypeError,KeyError,ValueError) as error:
        raise ValueError('Real Windows native startup and restore/maximize checks must pass.') from error
    manifest = json.loads((APP/'PAYLOAD-MANIFEST.json').read_text(encoding='utf-8'))
    stage = json.loads((BUILD/'stage-manifest.json').read_text(encoding='utf-8'))
    if not (manifest['delivery_profile'] == audit['delivery_profile'] == 'public'
            and manifest['source_tree_sha256'] == stage['source_tree_sha256']
            and len(manifest['files']) == audit['payload_files_verified'] == independent['payload_files_verified']):
        raise ValueError('The independently verified payload must match this public source snapshot.')
    expected_readable = sum(Path(name).suffix not in ('.pyd', '.dll', '.exe') for name in stage['files'])
    if not (audit['source_tree_sha256'] == independent['source_tree_sha256'] == stage['source_tree_sha256']
            and audit['readable_source_files_verified'] == independent['readable_source_files_verified'] == expected_readable
            and audit['user_guide_sha256'] == stage['files']['USER_GUIDE.html']['sha256']):
        raise ValueError('Independent verification must include every readable source file and the corrected public guide.')
    for executable in ('Optical Design Studio.exe', 'OpticalDesignBackend.exe'):
        if manifest['files'][executable]['sha256'] != digest(APP/executable):
            raise ValueError('An executable changed after independent verification: '+executable)
    failed = [name for name, entry in report['checks'].items() if not entry['passed']]
    if failed:
        raise ValueError('Failed frozen checks: '+', '.join(failed))
    controls = report['checks']['native_reference_controls_and_graphs']['detail']
    fields = report['checks']['native_electric_field_maps_and_features']['detail']
    if not (controls['physical_model_unchanged'] and controls['shared_settings_preview'] and
            controls['native_2d_canvases'] and controls['native_3d_canvases'] and
            not controls['live_matplotlib_qt_widgets'] and fields['live_renderer'] == 'NativeVolumeCanvas' and
            fields['native_2d_field_maps'] and fields['native_orbit_and_zoom'] and
            fields['actual_phase_vectors_verified'] and fields['saved_xyz_and_complex_fields_preserved'] and
            not fields['live_publication_artists_created']):
        raise ValueError('The native redesign and scientific arrays must be verified inside the frozen app.')
    speed = report['checks']['simulation_speed_and_scan_storage']['detail']
    if not (all(speed.get(name) is True for name in (
            'shared_spectrum_solutions', 'validated_fourier_sampling',
            'exact_disk_backed_spectrum', 'compact_scan_roundtrip', 'contour_label_parity'))
            and speed.get('field_sample_count') == 3):
        raise ValueError('Simulation solve reuse, Fourier sampling and exact scan storage must pass inside the frozen app.')
    maximize = report['checks']['maximize_restore_painting']['detail']
    if not (maximize.get('maximized_opaque_workspace') is True
            and maximize.get('restored_glass_policy') is True
            and maximize.get('looks') == ['glass_dark', 'glass_light']):
        raise ValueError('Maximized workspace painting and restored glass policy must pass inside the frozen app.')
    for executable in ('Optical Design Studio.exe', 'OpticalDesignBackend.exe'):
        reader = CArchiveReader(str(APP/executable))
        modules = reader.open_embedded_archive(next(name for name in reader.toc if name.endswith('.pyz'))).toc
        missing = [name for name in REQUIRED_FROZEN_MODULES if name not in modules]
        if missing:
            raise ValueError(f'{executable} is missing native runtime modules: {missing}')
        forbidden = [name for name in modules if name.startswith(('matplotlib.backends.backend_qt', 'PySide', 'PyQt5'))]
        if forbidden:
            raise ValueError('Unexpected alternate live GUI backend: '+', '.join(forbidden))
    return report, manifest['files']


def copy_readable_source():
    destination = APP/'_internal'/'source'
    if destination.exists():
        expected = {name: record for name, record in inventory(SRC).items()
                    if Path(name).suffix not in ('.pyd', '.dll', '.exe')}
        current = inventory(destination)
        if any(current.get(name) != record for name, record in expected.items()):
            raise ValueError('Prepared readable source changed after verification.')
        if any(name not in expected and not name.startswith('S4-source/') for name in current):
            raise ValueError('Unexpected file in prepared readable source.')
        return destination
    for name in inventory(SRC):
        path = SRC.joinpath(*safe_relative(name).parts)
        # The native module is already present in the frozen runtime. Readable
        # source and the separate source ZIP contain its corresponding source.
        if path.suffix in ('.pyd', '.dll', '.exe'):
            continue
        target = destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    # Pair this UI patch's unchanged solver with its already verified source.
    native_source = ROOT/'release-1.3.1'/'dist'/'Optical Design Studio'/'_internal'/'source'/'S4-source'
    if not native_source.is_dir():
        native_source = ROOT/'optical-design-studio-public-source'/'src'/'S4-source'
    if not native_source.is_dir():
        native_source = ROOT/'native'/'S4-source'
    if not (native_source/'COPYING').is_file() or not (native_source/'S4'/'accelerator.cpp').is_file():
        raise FileNotFoundError('The corresponding S4 native source must accompany the runtime.')
    shutil.copytree(native_source, destination/'S4-source', ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
    return destination


def prepare_payload(stage, tests, report=None):
    previous_notices = ROOT/'release-1.3.0'/'dist'/'Optical Design Studio'/'THIRD_PARTY_LICENSES'
    if not previous_notices.is_dir():
        previous_notices = ROOT/'release-1.2.9'/'dist'/'Optical Design Studio'/'THIRD_PARTY_LICENSES'
    if not previous_notices.is_dir():
        previous_notices = ROOT/'release-1.2.8'/'dist'/'Optical Design Studio'/'THIRD_PARTY_LICENSES'
    if not previous_notices.is_dir():
        previous_notices = ROOT/'THIRD_PARTY_LICENSES'
    shutil.copytree(previous_notices, APP/'THIRD_PARTY_LICENSES', dirs_exist_ok=True)
    if (BUILD/'THIRD_PARTY_LICENSES').is_dir():
        shutil.copytree(BUILD/'THIRD_PARTY_LICENSES', APP/'THIRD_PARTY_LICENSES', dirs_exist_ok=True)
    for name in ('START_HERE.md', 'THIRD_PARTY_NOTICES.md', 'RELEASE_NOTES.md'):
        shutil.copy2(BUILD/name, APP/name)
    guides = []
    for path in SRC.glob('*.md'):
        if path.name.endswith('_GUIDE.md') or path.name in ('PUBLICATION_FIGURES.md', 'MEEP_FDTD.md', 'UPDATES.md'):
            shutil.copy2(path, APP/path.name)
            guides.append(path.name)
    shutil.copy2(SRC/'S4_Studio.ico', APP/'S4_Studio.ico')
    copy_readable_source()
    validation = {'version': VERSION, 'build_date': stage['build_date'], 'signed': False,
        'source_tests_run': tests['tests_run'], 'source_tests_skipped': tests.get('skipped', 0),
        'source_tests_passed': tests['tests_run']-tests.get('skipped', 0),
        'source_tree_sha256': stage['source_tree_sha256'],
        'frozen_verification': 'passed' if report else 'pending',
        'native_startup_verification': 'passed' if report else 'pending',
        'packaged_checks': {name: entry['passed'] for name, entry in report['checks'].items()} if report else {},
        'live_rendering': 'Native Qt/PyQtGraph 2D and typed Qt 3D; Agg publication exports',
        'public_help_example': {'spectrum_samples': 41, 'csv_bytes_preserved': stage['help']['scientific_csv_bytes_unchanged'],
                                'csv_files': stage['help']['scientific_csv_files'], 'metadata_paths_rebased': True},
        'python_installation_required': False,
        'public_payload': 'Application, dependency runtime, public Silicon tutorial, guides, licenses and corresponding source. Empty user library.',
        'archive_integrity': 'verified after ZIP creation in VALIDATION.json', 'published': False}
    write_json(APP/'BUILD_VERIFICATION.json', validation)
    return validation


def public_files():
    files = inventory(APP)
    files.pop('PAYLOAD-MANIFEST.json', None)
    for name in files:
        safe_relative(name)
        if FORBIDDEN_FILES & {part.casefold() for part in Path(name).parts}:
            raise ValueError('Personal data/configuration in payload: '+name)
    with zipfile.ZipFile(APP/'_internal'/'seed_library.zip') as archive:
        if archive.namelist() != ['s4-library-manifest.json'] or json.loads(archive.read(archive.namelist()[0])) != {'format': 's4-library', 'version': 1, 'files': {}}:
            raise ValueError('The public seed must be a manifest-only empty library.')
    for name in ('qt_native_figure.py', 'qt_native_field_volume.py', 'qt_windows_glass.py',
                 'scan_storage.py', 'field_sampling.py', 'simulation_fields.py', 'contour_sweep.py'):
        if '_internal/source/'+name not in files:
            raise ValueError('Missing readable source: '+name)
    for name in ('bundle.json', 'results.csv', 'electric_fields.csv', 'field-samples.json'):
        target = '_internal/help_assets/silicon-reference-run/'+name
        if target not in files:
            raise ValueError('Missing public Help data: '+target)
    return files


def create_zip(path, entries, prefix, compresslevel):
    temporary = path.with_suffix(path.suffix+'.part')
    if path.exists() or temporary.exists():
        raise FileExistsError(path)
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=compresslevel, allowZip64=True) as archive:
        for source, name in entries:
            archive.write(source, prefix+name)
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP integrity failure: '+str(temporary))
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-payload', action='store_true',
                        help='Copy reviewed source/notices and inventory before frozen verification; create no ZIP.')
    args = parser.parse_args()
    stage, tests = verify_stage()
    if args.prepare_payload:
        if not (APP/'Optical Design Studio.exe').is_file() or not (APP/'OpticalDesignBackend.exe').is_file():
            raise FileNotFoundError('Build both executables before preparing their verified inventory.')
        prepare_payload(stage, tests)
        write_json(APP/'PAYLOAD-MANIFEST.json', {'version': VERSION, 'delivery_profile': 'public',
            'source_tree_sha256': stage['source_tree_sha256'], 'packaged_self_tests_passed': False,
            'files': public_files()})
        print('Payload prepared for independent frozen verification; no archives created.', flush=True)
        return
    report, verified_files = verify_frozen()
    if any(OUT.glob('*.zip')) or any(OUT.glob('*.part')):
        raise FileExistsError('Keep previous candidate assets intact: '+str(OUT))
    validation = prepare_payload(stage, tests, report)
    files = public_files()
    # Only the pending validation record changes after the independent audit.
    # Source, executables, dependencies, tutorial, guides and notices retain
    # their verified bytes before they are placed in the release archives.
    if set(files) != set(verified_files) or any(record != verified_files[name]
            for name, record in files.items() if name != 'BUILD_VERIFICATION.json'):
        raise ValueError('Payload files changed after independent frozen verification.')
    write_json(APP/'PAYLOAD-MANIFEST.json', {'version': VERSION, 'delivery_profile': 'public',
        'source_tree_sha256': stage['source_tree_sha256'], 'packaged_self_tests_passed': True, 'files': files})
    OUT.mkdir(exist_ok=True)
    portable = OUT/f'OpticalDesignStudio-Portable-{VERSION}-Windows-x64.zip'
    entries = [(APP/name, name) for name in files]
    entries.append((APP/'PAYLOAD-MANIFEST.json', 'PAYLOAD-MANIFEST.json'))
    print('Creating verified portable ZIP', flush=True)
    create_zip(portable, entries, 'Optical Design Studio/', 1)
    source = OUT/f'OpticalDesignStudio-Source-{VERSION}.zip'
    readable = APP/'_internal'/'source'
    source_entries = [(readable/name, ('native/'+name if name.startswith('S4-source/') else 'src/'+name))
                      for name in inventory(readable)]
    source_entries += [(APP/'THIRD_PARTY_LICENSES'/name, 'THIRD_PARTY_LICENSES/'+name)
                       for name in inventory(APP/'THIRD_PARTY_LICENSES')]
    # Shipping the spec/stager preserves the exact recipe. Machine-local pinned
    # input locations are relative defaults, documented in the source guide.
    source_entries += [(BUILD/name, 'packaging/'+name) for name in
        ('OpticalDesignStudio.spec', 'desktop_entry.py', 'backend_entry.py', 'version_info.txt',
         'stage_release.py', 'build_release.py', 'test_release_source.py', 'verify_release.py',
         'package_release.py', 'test_release_package_gates.py', 'test_packaging.py',
         'verify_release_source_smoke.py', 'audit_source_recipe.py', 'audit_release_archives.py', 'seed_library.zip',
         'stage-manifest.json', 'source-stage-manifest.json',
         'START_HERE.md', 'RELEASE_NOTES.md', 'THIRD_PARTY_NOTICES.md', 'SOURCE_README.md', 'BUILDING.md')]
    source_entries += [(BUILD/name, name) for name in ('START_HERE.md', 'RELEASE_NOTES.md', 'THIRD_PARTY_NOTICES.md')]
    source_entries.append((BUILD/'SOURCE_README.md', 'README.md'))
    print('Creating corresponding source ZIP', flush=True)
    create_zip(source, source_entries, f'OpticalDesignStudio-Source-{VERSION}/', 6)
    sums = []
    for path in (portable, source):
        line = digest(path)+'  '+path.name
        sums.append(line)
        path.with_name(path.name+'.sha256').write_text(line+'\n', encoding='ascii')
    (OUT/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n', encoding='ascii')
    shutil.copy2(BUILD/'RELEASE_NOTES.md', OUT/'RELEASE_NOTES.md')
    validation['archive_integrity'] = 'passed'
    validation['assets'] = [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': digest(p)} for p in (portable, source)]
    write_json(OUT/'VALIDATION.json', validation)
    print(json.dumps({'release': str(OUT), 'assets': validation['assets']}), flush=True)


if __name__ == '__main__':
    main()
