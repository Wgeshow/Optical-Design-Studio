"""Create audited experimental assets without inventing unfinished verification."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import package_release as pkg


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def frozen_modules(application):
    from PyInstaller.archive.readers import CArchiveReader
    result = {}
    for name in ('Optical Design Studio.exe', 'OpticalDesignBackend.exe'):
        archive = CArchiveReader(str(application/name))
        pyz = archive.open_embedded_archive(next(key for key in archive.toc if key.endswith('.pyz')))
        modules = pyz.toc
        missing = set(pkg.REQUIRED_FROZEN_MODULES)-set(modules)
        if missing:
            raise ValueError(f'{name}: missing frozen modules {sorted(missing)}')
        numpy_version = {}
        exec(pyz.extract('numpy.version'), {'__builtins__': {}}, numpy_version)
        if numpy_version.get('__version__') != '1.26.4':
            raise ValueError(f'{name}: frozen NumPy does not match the native runtime requirement.')
        result[name] = dict(sha256=pkg.digest(application/name), required_modules=len(pkg.REQUIRED_FROZEN_MODULES),
                            numpy_version=numpy_version['__version__'])
    return result


def verify_dependency_licenses(application):
    """Publish the license texts that match each bundled solver distribution."""
    required = []
    for path in (application/'_internal'/'devsim-2.11.0.dist-info'/'licenses').rglob('*'):
        if path.is_file():
            required.append((path, application/'THIRD_PARTY_LICENSES'/'DEVSIM-2.11.0'/path.name))
    gpu = application/'_internal'/'gpu_solver_runtime'
    for distribution in gpu.glob('*.dist-info'):
        paths = list((distribution/'licenses').rglob('*'))
        if (distribution/'LICENSE').is_file():paths.append(distribution/'LICENSE')
        for path in paths:
            if path.is_file():required.append((path, application/'THIRD_PARTY_LICENSES'/'GPU'/path.relative_to(gpu)))
    if len(required) != 14:
        raise ValueError('Unexpected bundled solver license inventory; review coverage before shipping.')
    for origin, published in required:
        if not published.is_file() or pkg.digest(origin) != pkg.digest(published):
            raise ValueError('Missing or mismatched dependency notice: '+str(published))
    return {path.relative_to(application).as_posix():pkg.digest(path) for _,path in required}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seven-zip', type=Path, required=True)
    parser.add_argument('--allow-partial', action='store_true')
    parser.add_argument('--validation-scope', required=True)
    parser.add_argument('--reuse-portable', type=Path,
                        help='Previously audited archive to copy and update for documentation-only amendments.')
    parser.add_argument('--reuse-portable-audit', type=Path)
    args = parser.parse_args()
    stage, tests = pkg.verify_stage()
    gates = read(pkg.ROOT/'release-audit'/'packaging-gates-report.json')
    if not gates['passed'] or gates['source_tree_sha256'] != stage['source_tree_sha256']:
        raise ValueError('Current packaging gates must pass for this staged source.')
    if pkg.OUT.exists() and any(pkg.OUT.iterdir()):
        raise FileExistsError('Preserve existing release assets: '+str(pkg.OUT))
    modules = frozen_modules(pkg.APP)
    license_files = verify_dependency_licenses(pkg.APP)
    native_manifest = read(pkg.SRC/'pcs_s4_runtime'/'build_manifest.json')
    native_binary = stage['files']['pcs_s4_runtime/S4.cp312-win_amd64.pyd']['sha256']
    if native_binary != native_manifest.get('binary_sha256') or not native_manifest.get('sources'):
        raise ValueError('The native binary lacks matching corresponding-source provenance.')
    if pkg.digest(pkg.APP/'_internal'/'pcs_s4_runtime'/'S4.cp312-win_amd64.pyd') != native_binary:
        raise ValueError('The frozen native binary differs from its corresponding-source provenance.')
    for name, expected in native_manifest['sources'].items():
        relative = pkg.safe_relative(name.replace('\\', '/'))
        if pkg.digest(pkg.ROOT/'native'/'S4-source'/relative) != expected:
            raise ValueError('Corresponding native source changed: '+name)
    report_path = pkg.BUILD/'verification'/'report.json'
    report = read(report_path) if report_path.is_file() else None
    if report is not None and (not report.get('frozen') or report.get('version') != pkg.VERSION or
                              Path(report['executable']).resolve() != (pkg.APP/'Optical Design Studio.exe').resolve()):
        raise ValueError('Compiled evidence belongs to a different application.')
    complete = False
    incomplete_reason = ''
    try:
        pkg.verify_frozen()
        complete = True
    except (OSError, ValueError, AssertionError, KeyError, TypeError, StopIteration) as exc:
        incomplete_reason = str(exc)
        if not args.allow_partial:
            raise ValueError('Full frozen verification is incomplete; explicit --allow-partial required.') from exc
    native_path = pkg.BUILD/'verification'/'native-startup-report.json'
    native_status = 'not_run'
    if native_path.is_file():
        from verify_release import validate_native_startup
        native = read(native_path)
        try:
            validate_native_startup(native, pkg.APP/'Optical Design Studio.exe')
            native_status = 'passed'
        except (AssertionError, ValueError, KeyError, TypeError):
            native_status = 'failed'
    checks = {name: entry.get('passed') for name, entry in (report or {}).get('checks', {}).items()}
    verified_files = None
    independent_path = pkg.BUILD/'verification'/'independent-verification.json'
    independent = read(independent_path) if independent_path.is_file() else None
    if report and report.get('validation_profile') == 'critical_release':
        if not (report.get('passed') is True and checks and all(value is True for value in checks.values())
                and independent and independent.get('status') == 'passed'
                and independent.get('validation_profile') == 'critical_release'
                and independent.get('source_tree_sha256') == stage['source_tree_sha256']
                and independent.get('native_startup_verified') is True and native_status == 'passed'
                and independent.get('native_startup_executable_sha256') == modules['Optical Design Studio.exe']['sha256']
                and independent.get('native_startup_report_sha256') == pkg.digest(native_path)):
            raise ValueError('The critical frozen profile and real Windows startup must pass for this exact executable.')
        payload_audit = read(pkg.BUILD/'verification'/'payload-audit.json')
        if (payload_audit.get('executable_sha256') != modules['Optical Design Studio.exe']['sha256']
                or payload_audit.get('manifest_sha256') != pkg.digest(pkg.APP/'PAYLOAD-MANIFEST.json')):
            raise ValueError('The independently verified payload changed before packaging.')
        verified_files = read(pkg.APP/'PAYLOAD-MANIFEST.json')['files']
        if pkg.public_files() != verified_files:
            raise ValueError('Payload content changed after independent verification.')
    elif not complete:
        raise ValueError('Experimental packaging requires the passing critical frozen profile and native Windows startup.')
    if verified_files is None:
        verified_files = read(pkg.APP/'PAYLOAD-MANIFEST.json')['files']
        if pkg.public_files() != verified_files:
            raise ValueError('Payload content changed after independent verification.')
    validation = pkg.prepare_payload(stage, tests)
    validation.update(
        release_channel='highly_experimental', validation_scope=args.validation_scope,
        frozen_verification='passed' if complete else 'partial' if report else 'not_run',
        native_startup_verification=native_status, packaged_self_tests_passed=complete,
        compiled_validation_profile=(report or {}).get('validation_profile'),
        critical_packaged_checks_passed=bool(report and report.get('validation_profile') == 'critical_release'
                                          and report.get('passed') and independent and independent.get('status') == 'passed'),
        omitted_packaged_checks=(report or {}).get('omitted_checks', []),
        packaged_checks=checks, package_gate_tests=gates['tests_run'],
        incomplete_verification_reason=None if complete else incomplete_reason,
        source_test_targets=tests.get('targets', []), source_test_scope=tests.get('validation_scope', 'See source-test-report.json'),
        executable_sha256=modules['Optical Design Studio.exe']['sha256'],
        backend_executable_sha256=modules['OpticalDesignBackend.exe']['sha256'],
        frozen_module_inventory=modules,
        dependency_license_files=len(license_files),
        documentation_amendments=[{key:amendment.get(key) for key in
            ('kind','added','changed','gui_rerun','prior_gui_and_native_results_reused','scope')}
            for amendment in (independent or {}).get('documentation_amendments',[])],
        limitations=['Highly Experimental prerelease.',
                     'Completed calculations do not establish convergence or agreement for arbitrary edited devices.',
                     'Finite-area PCSEL remains unconverged in the existing reference audit.'],
        archive_integrity='pending', published=False)
    pkg.write_json(pkg.APP/'BUILD_VERIFICATION.json', validation)
    files = pkg.public_files()
    if verified_files is not None and (set(files) != set(verified_files) or any(
            record != verified_files[name] for name, record in files.items()
            if name not in ('BUILD_VERIFICATION.json', 'RELEASE_NOTES.md'))):
        raise ValueError('Only final release notes and verification metadata may change after the payload audit.')
    pkg.write_json(pkg.APP/'PAYLOAD-MANIFEST.json', dict(
        version=pkg.VERSION, delivery_profile='public', release_channel='highly_experimental',
        source_tree_sha256=stage['source_tree_sha256'], packaged_self_tests_passed=complete,
        compiled_verification=validation['frozen_verification'], native_startup_verification=native_status, files=files))
    pkg.OUT.mkdir()
    portable = pkg.OUT/f'OpticalDesignStudio-Portable-{pkg.VERSION}-Windows-x64.7z'
    names = sorted(files)+['PAYLOAD-MANIFEST.json']
    listing = pkg.ROOT/'release-audit'/'portable-files.txt'
    listing.write_text(''.join('Optical Design Studio/'+name+'\n' for name in names), encoding='utf-8')
    print('Compressing exact public portable inventory.', flush=True)
    reused_changed = []
    mode = 'a'
    if args.reuse_portable:
        if not args.reuse_portable_audit:
            raise ValueError('Archive reuse requires its successful final audit.')
        previous = read(args.reuse_portable_audit)
        previous_asset = next(item for item in previous['assets'] if item['name']==args.reuse_portable.name)
        if not (previous.get('passed') is True and previous.get('version')==pkg.VERSION
                and previous.get('source_tree_sha256')==stage['source_tree_sha256']
                and args.reuse_portable.stat().st_size==previous_asset['bytes']
                and pkg.digest(args.reuse_portable)==previous_asset['sha256']):
            raise ValueError('The reusable archive does not match its verified source and audit.')
        prior_manifest=json.loads(subprocess.check_output([
            str(args.seven_zip),'x','-so',str(args.reuse_portable),'Optical Design Studio/PAYLOAD-MANIFEST.json']))
        prior_files=prior_manifest['files']
        removed=set(prior_files)-set(files)
        added=set(files)-set(prior_files)
        changed={name for name in set(files)&set(prior_files) if files[name]!=prior_files[name]}
        if removed or any(not name.startswith('THIRD_PARTY_LICENSES/') for name in added) or not changed <= {
                'BUILD_VERIFICATION.json','RELEASE_NOTES.md','THIRD_PARTY_NOTICES.md'}:
            raise ValueError('Archive reuse is limited to added licenses and release documentation changes.')
        reused_changed=sorted(added|changed)
        shutil.copy2(args.reuse_portable,portable)
        mode='u'
    with (pkg.ROOT/'release-audit'/'portable-compression.log').open('w', encoding='utf-8') as log:
        subprocess.run([str(args.seven_zip), mode, '-t7z', '-mx=5', '-mmt=4', '-md=64m', '-scsUTF-8',
                        str(portable), '@'+str(listing)], cwd=pkg.APP.parent, stdout=log, stderr=subprocess.STDOUT, check=True)
    if portable.stat().st_size >= 2*1024**3:
        raise ValueError('Portable archive exceeds the per-file release limit.')
    subprocess.run([str(args.seven_zip), 't', str(portable), '-bso0', '-bsp0'], check=True)
    output = subprocess.check_output([str(args.seven_zip), 'l', '-slt', '-sccUTF-8', str(portable)], encoding='utf-8')
    entries = []
    for block in output.split('----------\n', 1)[1].split('\n\n'):
        fields = dict(line.split(' = ', 1) for line in block.splitlines() if ' = ' in line)
        if fields.get('Path') and fields.get('Folder') != '+':entries.append(fields)
    prefix = 'Optical Design Studio/'
    archive_files = {entry['Path'].replace('\\', '/'): entry for entry in entries}
    if set(archive_files) != {prefix+name for name in names}:
        raise ValueError('Portable archive inventory differs from the payload manifest.')
    for name, expected in files.items():
        if int(archive_files[prefix+name]['Size']) != expected['size']:
            raise ValueError('Portable archive size mismatch: '+name)
    for name in ('Optical Design Studio.exe', 'OpticalDesignBackend.exe', 'PAYLOAD-MANIFEST.json', *reused_changed):
        data = subprocess.check_output([str(args.seven_zip), 'x', '-so', str(portable), prefix+name])
        if hashlib.sha256(data).hexdigest() != pkg.digest(pkg.APP/name):
            raise ValueError('Portable archive content mismatch: '+name)
    recipe = read(pkg.BUILD/'source-recipe-audit.json')
    if not recipe['passed'] or recipe['source_tree_sha256'] != stage['source_tree_sha256']:
        raise ValueError('Corresponding source recipe audit is missing or stale.')
    recipe_names = recipe['packaging_files']
    for name, expected in recipe['packaged_file_sha256'].items():
        if pkg.digest(pkg.BUILD/name) != expected:raise ValueError('Recipe changed after audit: '+name)
    readable = pkg.APP/'_internal'/'source'
    source = pkg.OUT/f'OpticalDesignStudio-Source-{pkg.VERSION}.zip'
    source_entries = [(readable/name, 'native/'+name if name.startswith('S4-source/') else 'src/'+name)
                      for name in pkg.inventory(readable)]
    source_entries += [(pkg.APP/'THIRD_PARTY_LICENSES'/name, 'THIRD_PARTY_LICENSES/'+name)
                       for name in pkg.inventory(pkg.APP/'THIRD_PARTY_LICENSES')]
    source_entries += [(pkg.BUILD/name, 'packaging/'+name) for name in recipe_names]
    source_entries += [(pkg.BUILD/name, name) for name in ('START_HERE.md', 'RELEASE_NOTES.md', 'THIRD_PARTY_NOTICES.md')]
    source_entries += [(pkg.BUILD/'SOURCE_README.md', 'README.md'), (pkg.APP/'BUILD_VERIFICATION.json', 'EXPERIMENTAL_VALIDATION.json')]
    source_prefix = f'OpticalDesignStudio-Source-{pkg.VERSION}/'
    pkg.create_zip(source, source_entries, source_prefix, 6)
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() is not None:raise ValueError('Source ZIP failed CRC validation.')
        actual = {info.filename for info in archive.infolist() if not info.is_dir()}
        if actual != {source_prefix+name for _, name in source_entries}:raise ValueError('Source ZIP inventory mismatch.')
        for path, name in source_entries:
            if hashlib.sha256(archive.read(source_prefix+name)).hexdigest() != pkg.digest(path):
                raise ValueError('Source ZIP content mismatch: '+name)
        for name, expected in stage['files'].items():
            if Path(name).suffix in ('.pyd', '.dll', '.exe'):continue
            if hashlib.sha256(archive.read(source_prefix+'src/'+name)).hexdigest() != expected['sha256']:
                raise ValueError('Source archive differs from frozen source: '+name)
        for name, expected in native_manifest['sources'].items():
            path = source_prefix+'native/S4-source/'+name.replace('\\', '/')
            if hashlib.sha256(archive.read(path)).hexdigest() != expected:
                raise ValueError('Source archive native provenance mismatch: '+name)
    if files != pkg.public_files():raise ValueError('Payload changed while archiving.')
    assets = [dict(name=path.name, bytes=path.stat().st_size, sha256=pkg.digest(path)) for path in (portable, source)]
    sums = []
    for asset in assets:
        line=asset['sha256']+'  '+asset['name'];sums.append(line)
        (pkg.OUT/(asset['name']+'.sha256')).write_text(line+'\n',encoding='ascii')
    (pkg.OUT/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n',encoding='ascii')
    validation.update(archive_integrity='passed',assets=assets)
    pkg.write_json(pkg.OUT/'VALIDATION.json',validation)
    (pkg.OUT/'RELEASE_NOTES.md').write_bytes((pkg.BUILD/'RELEASE_NOTES.md').read_bytes())
    audit=dict(passed=True,version=pkg.VERSION,source_tree_sha256=stage['source_tree_sha256'],
               release_channel='highly_experimental',archive_crc_verified=True,archive_sha256_verified=True,
               exact_payload_inventory=True,personal_data_excluded=True,
               corresponding_source_verified=True,packaged_recipe_verified=True,
               native_source_files_matched=len(native_manifest['sources']),native_binary_sha256=native_binary,
               dependency_license_files=len(license_files),documentation_update_verified=bool(args.reuse_portable),
               portable_files=len(names),source_files=len(source_entries),assets=assets,published=False)
    pkg.write_json(pkg.BUILD/'final-archive-audit.json',audit)
    print(json.dumps(audit,indent=2),flush=True)


if __name__ == '__main__':main()
