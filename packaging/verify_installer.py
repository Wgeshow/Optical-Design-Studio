"""Verify a Windows installer in an isolated folder, including upgrade/removal.

Run only after the frozen payload and installer have been built. Existing
Optical Design Studio installation registrations are never overwritten. The
test uses no shortcuts or visible GUI, and leaves its evidence and user-created
sentinels available for inspection after uninstalling the test application.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid

from verify_frozen import pe_machine
from build_version import release_info


ROOT = Path(__file__).resolve().parent
VERIFICATION_ROOT = ROOT / 'install_verification'
APP_ID = '{3103D40B-0D27-4DA2-8C2A-D87331C81AD2}'
UNINSTALL_KEY = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + APP_ID + '_is1'
REGISTRY_FIELDS = ('DisplayName', 'DisplayVersion', 'InstallLocation',
                   'UninstallString', 'QuietUninstallString', 'Inno Setup: App Path')


def contained(path):
    """Resolve the exact path before any install, uninstall, or evidence write."""
    root = VERIFICATION_ROOT.resolve()
    if not root.is_relative_to(ROOT) or root == ROOT:
        raise RuntimeError('The verification folder resolves outside desktop_installer.')
    path = Path(path).resolve()
    if path == root or not path.is_relative_to(root):
        raise RuntimeError(f'Refusing a target outside the isolated verification folder: {path}')
    return path


def registered_installations():
    import winreg
    records = []
    for view_name, view_flag in (('64-bit', winreg.KEY_WOW64_64KEY),
                                 ('32-bit', winreg.KEY_WOW64_32KEY)):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY,
                                 0, winreg.KEY_READ | view_flag)
        except FileNotFoundError:
            continue
        with key:
            values = {}
            for name in REGISTRY_FIELDS:
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    values[name] = None
            records.append(dict(view=view_name, values=values))
    return records


def owned_registration(application_directory):
    application_directory = contained(application_directory)
    records = registered_installations()
    if not records:
        raise RuntimeError('The test installation has no Windows uninstall registration.')
    for record in records:
        location = record['values'].get('InstallLocation') or record['values'].get('Inno Setup: App Path')
        if not location or Path(location).resolve() != application_directory:
            raise RuntimeError('An installation registration points outside the test target; it will not be changed.')
    return records


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def executable_version(path):
    """Read the PE's fixed file version without executing it or invoking a shell."""
    import ctypes
    from ctypes import wintypes
    import struct

    version = ctypes.WinDLL('version', use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR,
                                     ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.UINT)]
    version.VerQueryValueW.restype = wintypes.BOOL
    ignored = wintypes.DWORD()
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
    if not size:
        raise RuntimeError('The installed executable has no readable version resource: ' + str(path))
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, data):
        raise ctypes.WinError(ctypes.get_last_error())
    pointer, length = wintypes.LPVOID(), wintypes.UINT()
    if not version.VerQueryValueW(data, '\\', ctypes.byref(pointer), ctypes.byref(length)) or length.value < 52:
        raise RuntimeError('The installed executable has no fixed version information: ' + str(path))
    fields = struct.unpack('<13I', ctypes.string_at(pointer, 52))
    if fields[0] != 0xFEEF04BD:
        raise RuntimeError('Invalid executable version signature: ' + str(path))
    major_minor, patch_build = fields[2:4]
    return '.'.join(str(value) for value in (major_minor >> 16, major_minor & 0xffff,
                                           patch_build >> 16, patch_build & 0xffff))


def assert_new_release(previous, upgraded, expected_version):
    """Verify release identity independently of the installer's exit status."""
    if previous['payload_version'] == upgraded['payload_version']:
        raise AssertionError('The previous and upgraded payload versions are identical.')
    if upgraded['payload_version'] != expected_version:
        raise AssertionError('Unexpected upgraded payload manifest version: ' + str(upgraded['payload_version']))
    expected_file_version = '.'.join((expected_version.split('.') + ['0'] * 4)[:4])
    for name, version in upgraded['executable_versions'].items():
        if version != expected_file_version or version == previous['executable_versions'].get(name):
            raise AssertionError(f'The upgraded executable has an unexpected or unchanged file version: {name}: {version}')
        if upgraded['executables'][name] == previous['executables'].get(name):
            raise AssertionError('The version upgrade did not replace the executable: ' + name)
    for record in upgraded['registry']:
        if record['values'].get('DisplayVersion') != expected_version:
            raise AssertionError('The Windows uninstall registration does not identify the new release.')


def run_hidden(command, directory, env, log_prefix, timeout=300):
    directory, log_prefix = contained(directory), contained(log_prefix)
    stdout_path = contained(log_prefix.with_suffix('.stdout.log'))
    stderr_path = contained(log_prefix.with_suffix('.stderr.log'))
    started = time.monotonic()
    with stdout_path.open('w', encoding='utf-8') as stdout, stderr_path.open('w', encoding='utf-8') as stderr:
        process = subprocess.Popen(command, cwd=directory, env=env, stdout=stdout, stderr=stderr,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Terminate only the process tree started by this invocation. Inno's
            # loader can have a child process; killing just its parent is not enough.
            windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
            subprocess.run([str(windows / 'System32' / 'taskkill.exe'), '/PID', str(process.pid), '/T', '/F'],
                           stdout=stdout, stderr=stderr, timeout=15,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            process.wait(timeout=15)
            raise TimeoutError(f'The owned verification process exceeded {timeout} seconds: {command[0]}') from None
    result = dict(exit_code=code, elapsed_seconds=round(time.monotonic() - started, 3),
                  stdout=str(stdout_path), stderr=str(stderr_path))
    if code:
        raise RuntimeError(f'Command exited with {code}: {command[0]}. See {stderr_path} and the Inno log.')
    return result


def assert_sentinels(sentinels):
    checked = {}
    for path, content in sentinels.items():
        path = contained(path)
        if not path.is_file() or path.read_text(encoding='utf-8') != content:
            raise AssertionError(f'User-created data was changed or removed: {path}')
        checked[str(path)] = sha256(path)
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installer', type=Path)
    parser.add_argument('--previous-installer', type=Path,
                        help='Install an older package first, then verify a real version upgrade to installer.')
    parser.add_argument('--expected-version',
                        help='Expected new manifest, executable, and registry version in --previous-installer mode.')
    parser.add_argument('--cpu-only', action='store_true', help='Skip the GPU check on computers without NVIDIA hardware.')
    parser.add_argument('--minimum-saved', type=int,
                        help='Defaults to each installed package seed count, including an older release.')
    args = parser.parse_args()
    args.expected_version = args.expected_version or release_info()['version']
    if os.name != 'nt':
        parser.error('Installer verification requires Windows.')

    installer = args.installer.resolve(strict=True)
    previous_installer = args.previous_installer.resolve(strict=True) if args.previous_installer else None
    if previous_installer == installer:
        parser.error('--previous-installer must identify a different installer file.')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    output = contained(VERIFICATION_ROOT / ('attempt-' + run_id))
    application_directory = contained(VERIFICATION_ROOT / 'Custom install location' / 'Optical Design Studio')
    output.mkdir(parents=True, exist_ok=False)
    report_path = contained(output / 'installer-verification.json')
    summary_path = contained(VERIFICATION_ROOT / 'latest-verification.json')
    # Keep the test library comparable to LocalAppData in length. Adding an
    # attempt timestamp above its extraction stage can exceed Windows MAX_PATH
    # even though the application's normal per-user directory is short.
    frozen_output = contained(VERIFICATION_ROOT / ('runtime-' + uuid.uuid4().hex[:6]))
    frozen_output.mkdir()
    user_data = contained(frozen_output / 'User Data')
    application = contained(application_directory / 'Optical Design Studio.exe')
    backend = contained(application_directory / 'OpticalDesignBackend.exe')
    report = dict(started=datetime.now(timezone.utc).isoformat(), status='running', installer=str(installer),
                  application_directory=str(application_directory), user_data=str(user_data),
                  app_id=APP_ID, registry_key='HKCU\\' + UNINSTALL_KEY, checks={})
    if previous_installer:
        report.update(previous_installer=str(previous_installer), expected_version=args.expected_version)

    def save():
        text = json.dumps(report, indent=2, ensure_ascii=False)
        report_path.write_text(text, encoding='utf-8')
        summary_path.write_text(text, encoding='utf-8')

    def check(name, value):
        report['checks'][name] = dict(passed=True, detail=value)
        save()

    env = dict(os.environ)
    env['S4_LIBRARY_ROOT'] = str(user_data)
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    sentinels = {}
    saved_data_hashes = None
    installation_started = False
    code = 1
    save()
    try:
        machine = pe_machine(installer)
        if machine != 0x8664:
            raise AssertionError(f'Installer must be a native x64 PE, received {machine!r}.')
        check('installer_architecture', dict(machine=hex(machine), sha256=sha256(installer), size=installer.stat().st_size))
        if previous_installer:
            previous_machine = pe_machine(previous_installer)
            if previous_machine != 0x8664:
                raise AssertionError('The previous installer must also be a native x64 PE.')
            previous_digest = sha256(previous_installer)
            if previous_digest == report['checks']['installer_architecture']['detail']['sha256']:
                raise AssertionError('The previous and new installer packages have identical bytes.')
            check('previous_installer_architecture', dict(machine=hex(previous_machine),
                  sha256=previous_digest, size=previous_installer.stat().st_size))

        previous = registered_installations()
        report['registry_before'] = previous
        if previous:
            report.update(status='skipped', reason='An Optical Design Studio installation is already registered. '
                          'No install or uninstall was run; review the existing registration before proceeding.')
            save()
            print(json.dumps(dict(status='skipped', report=str(report_path), reason=report['reason']), indent=2))
            return 3
        # An unregistered install from a prior interrupted run also needs review.
        if application.exists() or backend.exists() or list(application_directory.glob('unins*.exe')):
            report.update(status='skipped', reason='The isolated target already contains application or uninstall executables. '
                          'No installation files were overwritten; review the previous test first.')
            save()
            print(json.dumps(dict(status='skipped', report=str(report_path), reason=report['reason']), indent=2))
            return 3
        check('no_existing_installation', dict(registry_entries=0, target=str(application_directory)))

        user_data.mkdir(parents=True)
        data_sentinel = contained(user_data / ('user-data-sentinel-' + run_id + '.txt'))
        sentinels[data_sentinel] = 'User-created research data must survive install, upgrade, and uninstall.\n' + run_id + '\n'
        data_sentinel.write_text(sentinels[data_sentinel], encoding='utf-8')

        def install(phase, package=installer):
            contained(application_directory)
            log = contained(output / (phase + '.inno.log'))
            command = [str(package), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
                       '/NOICONS', '/TASKS=!desktopicon', '/GROUP=Optical Design Studio Verification',
                       '/DIR=' + str(application_directory), '/LOG=' + str(log)]
            install_started = datetime.now().replace(microsecond=0)
            result = run_hidden(command, output, env, output / phase)
            install_finished = datetime.now()
            result.update(inno_log=str(log), registry=owned_registration(application_directory))
            if not application.is_file() or not backend.is_file():
                raise AssertionError('The selected folder does not contain both installed executables.')
            result['executables'] = {p.name: sha256(p) for p in (application, backend)}
            if package == installer:
                receipt = contained(application_directory / 'installation.json')
                content = json.loads(receipt.read_text(encoding='utf-8'))
                if content.get('version') != args.expected_version:
                    raise AssertionError('Installation receipt has the wrong version.')
                recorded_at = datetime.fromisoformat(content['updated_at'])
                if recorded_at.tzinfo is not None or not install_started <= recorded_at <= install_finished:
                    raise AssertionError('Installation receipt date was not recorded by this install.')
                result['installation_receipt'] = content
            if previous_installer:
                manifest = contained(application_directory / 'PAYLOAD-MANIFEST.json')
                result['payload_version'] = json.loads(manifest.read_text(encoding='utf-8')).get('version')
                result['executable_versions'] = {p.name: executable_version(p) for p in (application, backend)}
            result['preserved_data'] = assert_sentinels(sentinels)
            return result

        installation_started = True
        first = install('install', previous_installer or installer)
        check('custom_folder_install', first)
        for relative in ('S4_Studio.ico', '_internal/source/qt_app.py', '_internal/seed_library.zip'):
            if not contained(application_directory / relative).is_file():
                raise AssertionError('Missing installed application file: ' + relative)
        if not any(contained(application_directory / 'THIRD_PARTY_LICENSES').rglob('*')):
            raise AssertionError('Dependency licenses are missing from the installed application.')

        app_sentinel = contained(application_directory / ('user-created-file-' + run_id + '.txt'))
        sentinels[app_sentinel] = 'An arbitrary untracked file in the application folder.\n' + run_id + '\n'
        app_sentinel.write_text(sentinels[app_sentinel], encoding='utf-8')
        def verify_runtime(phase):
            # Reuse this exact output directory: verify_frozen always places its
            # isolated library at output/User Data, including across versions.
            command = [sys.executable, str(ROOT / 'verify_frozen.py'), str(application), str(frozen_output)]
            if args.minimum_saved is not None:
                command.extend(['--minimum-saved', str(args.minimum_saved)])
            if not args.cpu_only:
                command.append('--gpu')
            receipt = contained(application_directory / 'installation.json')
            receipt_before = receipt.read_bytes() if receipt.is_file() else None
            runtime = run_hidden(command, output, env, output / phase, timeout=330)
            if receipt_before is not None:
                if not receipt.is_file() or receipt.read_bytes() != receipt_before:
                    raise AssertionError('Launching the application changed its installation receipt.')
                runtime['installation_receipt_unchanged'] = True
            runtime_report = contained(frozen_output / 'report.json')
            if not runtime_report.is_file():
                raise AssertionError('The installed runtime did not write its verification report.')
            content = json.loads(runtime_report.read_text(encoding='utf-8'))
            if not content.get('checks') or any(not item.get('passed') for item in content['checks'].values()):
                raise AssertionError('The installed runtime has failed checks; see ' + str(runtime_report))
            evidence = contained(output / (phase + '.report.json'))
            evidence.write_text(json.dumps(content, indent=2), encoding='utf-8')
            runtime.update(report=str(evidence), checks=list(content['checks']), gpu_requested=not args.cpu_only,
                           user_data=str(user_data))
            return runtime

        first_runtime = verify_runtime('verify-previous' if previous_installer else 'verify-frozen')
        check('previous_runtime_without_developer_paths' if previous_installer else
              'installed_runtime_without_developer_paths', first_runtime)
        saved_data_hashes = {path.relative_to(user_data).as_posix(): sha256(path)
                             for path in user_data.rglob('*') if path.is_file()}
        contained(output/'saved-data-checksums.json').write_text(json.dumps(saved_data_hashes, indent=2), encoding='utf-8')

        upgrade = install('upgrade')
        if previous_installer:
            assert_new_release(first, upgrade, args.expected_version)
        elif upgrade['executables'] != first['executables']:
            raise AssertionError('Reinstalling the same package unexpectedly changed the application executable bytes.')
        after_upgrade = {path.relative_to(user_data).as_posix(): sha256(path)
                         for path in user_data.rglob('*') if path.is_file()}
        if after_upgrade != saved_data_hashes:
            raise AssertionError('The upgrade changed saved data.')
        upgrade['saved_data_files_unchanged'] = len(saved_data_hashes)
        check('upgrade_preserves_user_data_and_untracked_files', upgrade)
        if previous_installer:
            # Preserve evidence before launch: successful self-tests intentionally
            # add run files and autosave a session to this existing user library.
            # Refresh the removal baseline even on failure so cleanup only tests
            # the uninstaller, rather than counting legitimate runtime writes.
            try:
                runtime = verify_runtime('verify-upgraded')
                check('installed_runtime_without_developer_paths', runtime)
            finally:
                saved_data_hashes = {path.relative_to(user_data).as_posix(): sha256(path)
                                     for path in user_data.rglob('*') if path.is_file()}
                contained(output / 'saved-data-after-runtime-checksums.json').write_text(
                    json.dumps(saved_data_hashes, indent=2), encoding='utf-8')
        code = 0
    except Exception:
        report['failure'] = traceback.format_exc()
    finally:
        if installation_started:
            try:
                records = owned_registration(application_directory)
                value = records[0]['values']['UninstallString']
                if not isinstance(value, str):
                    raise RuntimeError('The test installation has no valid uninstall command.')
                # Inno stores its executable quoted. No shell parses this value.
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                uninstaller = contained(Path(value))
                if uninstaller.parent != contained(application_directory) or not uninstaller.name.lower().startswith('unins') or uninstaller.suffix.lower() != '.exe':
                    raise RuntimeError('Refusing an unexpected uninstall executable.')
                log = contained(output / 'uninstall.inno.log')
                result = run_hidden([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                                     '/LOG=' + str(log)], output, env, output / 'uninstall')
                if application.exists() or backend.exists():
                    raise AssertionError('The uninstaller left an installed application executable behind.')
                if contained(application_directory / 'installation.json').exists():
                    raise AssertionError('The uninstaller left the tracked installation receipt behind.')
                after = registered_installations()
                if after:
                    raise AssertionError('The test uninstall registration was not removed.')
                if saved_data_hashes is not None:
                    after_uninstall = {path.relative_to(user_data).as_posix(): sha256(path)
                                       for path in user_data.rglob('*') if path.is_file()}
                    if after_uninstall != saved_data_hashes:
                        raise AssertionError('Uninstall changed saved data.')
                    result['saved_data_files_unchanged'] = len(saved_data_hashes)
                result.update(inno_log=str(log), registry_after=after, application_executables_removed=True,
                              preserved_data=assert_sentinels(sentinels))
                check('uninstall_preserves_user_data_and_untracked_files', result)
            except Exception:
                report['cleanup_failure'] = traceback.format_exc()
                code = 1
        if report.get('status') != 'skipped':
            report.update(status='passed' if code == 0 else 'failed', finished=datetime.now(timezone.utc).isoformat())
        save()
    print(json.dumps(dict(status=report['status'], report=str(report_path), latest=str(summary_path)), indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
