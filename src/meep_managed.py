"""User-initiated installation of the application's own Meep WSL2 runtime.

Small setup assets pin official Ubuntu/Miniforge downloads and conda packages.
Legacy root filesystem assets remain readable. Microsoft WSL imports only into
the dedicated owned distribution; unrelated distributions are untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import zipfile

from app_version import APP_VERSION
from data_library import write_json
import meep_runtime
from update_client import (GitHubUpdateClient, ReleaseInfo, REPOSITORY_URL,
    UpdateError, UpdateCancelled, _cancelled)

MAX_PACK_BYTES = 8*1024**3
MAX_ROOTFS_BYTES = 12*1024**3
LINUX_PYTHON = '/opt/ods-meep/bin/python'


def distro_name():
    return 'OpticalDesignStudio-FDTD-'+APP_VERSION


def asset_name():
    return 'OpticalDesignStudio-Addon-meep-setup-'+APP_VERSION+'-WSL2-x64.zip'


def legacy_asset_name():
    return 'OpticalDesignStudio-Addon-meep-'+APP_VERSION+'-WSL2-x64.zip'


def runtime_root():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.local/share')/'OpticalDesignStudio'/'FDTD'/APP_VERSION


def managed_config():
    return dict(mode='wsl', distro=distro_name(), python=LINUX_PYTHON,
        conda='/opt/conda/bin/conda', managed=True, app_version=APP_VERSION)


def _decode(value):
    if isinstance(value, str):
        return value.replace('\0', '').strip()
    if value[:2] in (b'\xff\xfe', b'\xfe\xff') or b'\0' in value[:200]:
        return value.decode('utf-16', errors='replace').lstrip('\ufeff').strip()
    return value.decode('utf-8', errors='replace').strip()


def _wsl(args, timeout=20):
    process = subprocess.run(['wsl.exe', *args], capture_output=True,
        timeout=timeout, **meep_runtime.process_options())
    return process.returncode, _decode(process.stdout), _decode(process.stderr)


def prerequisites(cancel=None):
    """Read-only checks. VM startup is verified when the imported engine probes."""
    _cancelled(cancel)
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        return dict(ready=False, available=False, needs_setup=False,
            message='The managed package supports Windows x64 with WSL2. Use Expert setup for a local Linux/macOS runtime.')
    if shutil.which('wsl.exe') is None:
        return dict(ready=False, available=False, needs_setup=True,
            message='Windows Subsystem for Linux is not installed. Click Set up Windows support; administrator approval and a restart may be required.')
    try:
        version_code, version, version_error = _wsl(['--version'])
        _cancelled(cancel)
        status_code, status, status_error = _wsl(['--status'])
        _cancelled(cancel)
        list_code, names, list_error = _wsl(['--list', '--quiet'])
        ready = version_code == 0 and status_code == 0 and list_code == 0
        return dict(ready=ready, available=False, needs_setup=not ready,
            distributions=[line.strip() for line in names.splitlines() if line.strip()] if list_code==0 else [],
            wsl_version=version, status=status,
            message='WSL is installed. The engine will use WSL2; successful engine startup verifies virtualization.' if ready
                else 'WSL2 is not ready. Complete Windows support setup, restart if requested, then check again. '+(status_error or status or version_error or list_error))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(ready=False, available=False, needs_setup=True, message='Could not check WSL: '+str(exc))


def setup_windows_support():
    """Called only from the explicit UI button after its OS-change explanation.

    This requests Microsoft's WSL prerequisite setup under UAC. It does not
    install Ubuntu, change defaults, launch an imported distro, or reboot.
    """
    if sys.platform != 'win32':
        raise RuntimeError('Windows support setup is available only on Windows.')
    import ctypes
    wsl = str(Path(os.environ.get('WINDIR', r'C:\Windows'))/'System32'/'wsl.exe')
    result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', wsl,
        '--install --no-distribution --no-launch', None, 0)
    if result <= 32:
        raise RuntimeError('Windows setup was not started. Administrator approval may have been cancelled.')
    return 'Windows support setup started. If Windows requests a restart, save your work and restart manually, then click Check availability. No restart is triggered by this application.'


class ManagedMeepClient(GitHubUpdateClient):
    def check_pack(self, cancel=None):
        for page in range(1, 101):
            _cancelled(cancel)
            releases = self._json(f'/repos/Wgeshow/Optical-Design-Studio/releases?per_page=100&page={page}', cancel)
            if not isinstance(releases, list):
                raise UpdateError('invalid_response', 'Invalid GitHub release listing.')
            for release in releases:
                if not isinstance(release, dict) or release.get('draft'):
                    continue
                tag = release.get('tag_name')
                if tag != 'addons-v'+APP_VERSION and (tag != 'v'+APP_VERSION or release.get('prerelease')):
                    continue
                assets = release.get('assets', [])
                if not isinstance(assets, list):
                    raise UpdateError('invalid_asset', 'Invalid FDTD package metadata.')
                matches = [asset for asset in assets if isinstance(asset, dict) and asset.get('name')==asset_name()]
                if not matches:
                    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get('name')==legacy_asset_name()]
                if not matches:
                    continue
                if len(matches)!=1 or matches[0].get('state')!='uploaded':
                    raise UpdateError('invalid_asset', 'The FDTD package is incomplete or ambiguous.')
                asset = matches[0]
                digest = asset.get('digest', '')
                if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
                    raise UpdateError('integrity_metadata', 'The FDTD pack has no published GitHub SHA256 digest.')
                result = ReleaseInfo(APP_VERSION, tag, str(release.get('published_at', '')), '',
                    REPOSITORY_URL+'/releases/tag/'+tag, asset.get('id'), asset['name'], asset.get('size'), digest[7:].lower())
                self._validate_release(result)
                return result
            if len(releases)<100:
                return None
        raise UpdateError('listing_limit', 'Too many releases to check reliably.')

    @staticmethod
    def _validate_release(release):
        if (not isinstance(release, ReleaseInfo) or release.version!=APP_VERSION
                or release.tag not in {'v'+APP_VERSION, 'addons-v'+APP_VERSION} or release.asset_name not in {asset_name(),legacy_asset_name()}
                or type(release.asset_id) is not int or release.asset_id<=0
                or type(release.asset_size) is not int or not 0<release.asset_size<=MAX_PACK_BYTES
                or not isinstance(release.sha256, str) or not re.fullmatch('[0-9a-f]{64}', release.sha256)):
            raise UpdateError('invalid_asset', 'The FDTD pack does not match this application version or WSL2 x64 platform.')


def _linked(path):
    return path.is_symlink() or (getattr(path, 'is_junction', lambda: False)())


def receipt(root=None):
    root = Path(root) if root is not None else runtime_root()
    try:
        file = root/'installation.json'
        if _linked(root) or _linked(file) or file.stat().st_size > 32768:
            return None
        value = json.loads(file.read_text(encoding='utf-8'))
        if (value.get('schema')!=1 or value.get('app_version')!=APP_VERSION
                or value.get('distro')!=distro_name() or value.get('location')!=str((root/'distro').resolve())
                or not re.fullmatch('[0-9a-f]{64}', value.get('sha256', ''))):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def registration():
    """Resolve only the exact app-owned distro; never return unrelated paths."""
    if sys.platform!='win32':
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Lxss') as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                with winreg.OpenKey(key, winreg.EnumKey(key, index)) as entry:
                    if winreg.QueryValueEx(entry, 'DistributionName')[0] == distro_name():
                        path = winreg.QueryValueEx(entry, 'BasePath')[0]
                        if path.startswith('\\\\?\\'):
                            path = path[4:]
                        return dict(location=str(Path(path).resolve()), version=winreg.QueryValueEx(entry, 'Version')[0])
    except FileNotFoundError:
        return None
    return None


def verify_installed(root=None, cancel=None):
    _cancelled(cancel)
    root = Path(root) if root is not None else runtime_root()
    saved, registered = receipt(root), registration()
    if not saved or not registered:
        return dict(available=False, message='The managed FDTD engine is not installed.')
    if os.path.normcase(registered['location']) != os.path.normcase(saved['location']) or registered['version']!=2:
        raise RuntimeError('The matching WSL distribution is not the owned WSL2 runtime. It was left unchanged.')
    result = meep_runtime.probe(managed_config())
    _cancelled(cancel)
    if result['available']:
        # Actual import and version check is mandatory before marking ready.
        expected = saved.get('meep_version')
        if expected and result['version']!=expected:
            raise RuntimeError('The installed Meep version differs from the verified package manifest.')
        meep_runtime.save_config(managed_config())
        write_json(root/'installation.json', dict(saved, state='ready', verified_at=time.time()))
    return result


def unpack_pack(archive, release, destination, cancel=None):
    """Extract only the verified rootfs blob; never unpack Linux paths on Windows."""
    ManagedMeepClient._validate_release(release)
    archive, destination = Path(archive), Path(destination)
    if archive.stat().st_size != release.asset_size:
        raise ValueError('FDTD package size mismatch.')
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            _cancelled(cancel)
            digest.update(chunk)
    if digest.hexdigest()!=release.sha256:
        raise ValueError('FDTD package SHA256 mismatch.')
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        names = {entry.filename for entry in entries}
        if len(entries)==2 and names=={'addon.json','linux-64.explicit.txt'}:
            if any(e.file_size>1024**2 or e.flag_bits&1 for e in entries):
                raise ValueError('FDTD setup metadata exceeds size limits or is encrypted.')
            import meep_bootstrap
            manifest = json.loads(package.read('addon.json'))
            lock = package.read('linux-64.explicit.txt')
            meep_bootstrap.validate_manifest(manifest,lock)
            if release.asset_name!=asset_name():
                raise ValueError('Direct setup requires the separate setup asset name.')
            if _linked(destination) or (destination.exists() and any(destination.iterdir())):
                raise ValueError('FDTD staging path already exists or is linked.')
            destination.mkdir(parents=True,exist_ok=True)
            _cancelled(cancel)
            (destination/'linux-64.explicit.txt').write_bytes(lock)
            write_json(destination/'addon.json',manifest)
            return destination/'addon.json',manifest
        if len(entries)!=2 or {entry.filename for entry in entries}!={'addon.json', 'rootfs.tar.gz'}:
            raise ValueError('Unexpected files in the FDTD package.')
        metadata = package.getinfo('addon.json')
        rootfs = package.getinfo('rootfs.tar.gz')
        if metadata.file_size>1024**2 or rootfs.file_size>MAX_PACK_BYTES or any(e.flag_bits&1 for e in entries):
            raise ValueError('FDTD package exceeds size limits or is encrypted.')
        manifest = json.loads(package.read(metadata))
        if (manifest.get('schema')!=1 or manifest.get('id')!='meep-wsl2'
                or manifest.get('app_version')!=APP_VERSION or manifest.get('platform')!='wsl2-linux-x64'
                or manifest.get('python')!=LINUX_PYTHON or manifest.get('default_user')!='ods'
                or manifest.get('rootfs_file')!='rootfs.tar.gz'
                or manifest.get('rootfs_bytes')!=rootfs.file_size
                or type(manifest.get('unpacked_bytes')) is not int
                or not 0<manifest['unpacked_bytes']<=MAX_ROOTFS_BYTES
                or not isinstance(manifest.get('meep_version'), str) or not manifest['meep_version']
                or not isinstance(manifest.get('licenses'), list) or not manifest['licenses']
                or not re.fullmatch('[0-9a-f]{64}', manifest.get('rootfs_sha256', ''))):
            raise ValueError('The FDTD manifest is incompatible or lacks provenance/license metadata.')
        target = destination/'rootfs.tar.gz'
        if target.exists() or _linked(destination):
            raise ValueError('FDTD staging path already exists or is linked.')
        destination.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with package.open(rootfs) as source, target.open('xb') as out:
            for chunk in iter(lambda: source.read(1024**2), b''):
                _cancelled(cancel)
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest()!=manifest['rootfs_sha256']:
            raise ValueError('FDTD Linux filesystem checksum mismatch.')
        return target, manifest


def import_pack(rootfs, manifest, release, *, root=None, cancel=None, progress=None):
    """Import once into a newly owned directory; never unregister or overwrite."""
    _cancelled(cancel)
    if manifest.get('schema')==2:
        import meep_bootstrap
        return meep_bootstrap.install(rootfs,manifest,release,root=root,cancel=cancel,progress=progress)
    ManagedMeepClient._validate_release(release)
    root = Path(root) if root is not None else runtime_root()
    status = prerequisites(cancel)
    if not status['ready']:
        raise RuntimeError(status['message'])
    existing = registration()
    if existing or distro_name() in status.get('distributions', []):
        if not receipt(root):
            raise RuntimeError('A distribution already uses the reserved FDTD name but has no matching installation receipt. It was left unchanged.')
        result = verify_installed(root, cancel)
        if not result['available']:
            raise RuntimeError('An existing managed installation needs repair. It was preserved; inspect its runtime log. '+result['message'])
        return result
    root.mkdir(parents=True, exist_ok=True)
    # Check all app-owned ancestors, including junctions, before creating VHDs.
    for parent in (root, root.parent, root.parent.parent):
        if _linked(parent):
            raise ValueError('The FDTD installation directory must not use symbolic links or junctions.')
    destination = root/'distro'
    previous = receipt(root)
    reusable_empty = (destination.is_dir() and not _linked(destination) and not any(destination.iterdir())
        and previous is not None and previous['sha256']==release.sha256)
    if destination.exists() and not reusable_empty:
        raise RuntimeError('The FDTD runtime directory already exists. It was preserved; use Expert setup or inspect the incomplete installation.')
    required = manifest['unpacked_bytes'] + 2*1024**3
    if shutil.disk_usage(root).free < required:
        raise RuntimeError(f'FDTD installation needs at least {required/1024**3:.1f} GiB free disk space.')
    _cancelled(cancel)
    destination.mkdir(exist_ok=reusable_empty)
    saved = dict(schema=1, app_version=APP_VERSION, distro=distro_name(), location=str(destination.resolve()),
        sha256=release.sha256, meep_version=manifest['meep_version'], state='importing')
    write_json(root/'installation.json', saved)
    write_json(root/'addon.json', manifest)
    argv = ['wsl.exe', '--import', distro_name(), str(destination.resolve()), str(Path(rootfs).resolve()), '--version', '2']
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **meep_runtime.process_options())
    # Import is a Windows service operation. Cancelling its launcher mid-import
    # can leave a registered partial VHD. Once import begins, wait for completion
    # (bounded) and preserve its receipt; honour cancellation before activation.
    try:
        if progress:
            progress('Importing the dedicated Linux runtime. Cancellation will finish this import safely before stopping.')
        output, _ = process.communicate(timeout=900)
        if process.returncode:
            raise RuntimeError('WSL could not import the FDTD engine: '+_decode(output))
        write_json(root/'installation.json', dict(saved, state='imported'))
        _cancelled(cancel)
        result = verify_installed(root, cancel)
        if not result['available']:
            raise RuntimeError('The runtime was imported but Meep could not start: '+result['message'])
        return result
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=10)
        write_json(root/'installation.json', dict(saved, state='import-timeout'))
        raise RuntimeError('WSL import timed out. The owned runtime directory was preserved for inspection; no distributions were removed.') from None
    except Exception:
        # Never unregister or recursively remove a potentially useful VHD.
        current = receipt(root) or saved
        write_json(root/'installation.json', dict(current, state='needs-check'))
        raise
