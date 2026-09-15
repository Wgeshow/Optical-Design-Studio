"""Explicit, version-locked native add-ons; never contacts the network on import.

The full distribution can continue shipping its native libraries. Optional packs
are SHA256-verified GitHub release assets, staged before an atomic receipt switch.
No installer scripts from a pack are executed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import time
import zipfile

from app_version import APP_VERSION
from desktop_runtime import resource_root
from update_client import (GitHubUpdateClient, ReleaseInfo, REPOSITORY_URL,
                           UpdateError, _cancelled, _version)

ADDONS = {
    'gpu': ('GPU acceleration', 'CUDA runtime for supported S4 matrix products.'),
    'cad_comsol': ('CAD & COMSOL export', 'STEP geometry and COMSOL model export tools.'),
}
MAX_UNPACKED = 4 * 1024**3
_handles = []


def _linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def _receipt_data(identifier, root):
    path = root/(_id(identifier)+'.json')
    if _linked(path) or not path.is_file() or path.stat().st_size>4096:
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if (value.get('version')!=APP_VERSION or value.get('id')!=identifier
            or not re.fullmatch('[0-9a-f]{64}', value.get('sha256', ''))):
        return None
    return value


def addon_root():
    # Stable across application replacement. This is not the research library.
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local' / 'share')
    return base / 'OpticalDesignStudio' / 'Addons' / APP_VERSION


def _id(identifier):
    if identifier not in ADDONS:
        raise ValueError('Unknown add-on.')
    return identifier


def _read_receipt(identifier, root=None):
    try:
        root = Path(root) if root is not None else addon_root()
        data = _receipt_data(identifier, root)
        if data is None:
            return None
        location = root / (identifier + '-' + data['sha256'])
        if _linked(root) or _linked(location) or not location.is_dir() or location.resolve().parent != root.resolve():
            return None
        return location
    except (OSError, ValueError, TypeError, RuntimeError):
        return None


def bundled(identifier):
    _id(identifier)
    if not getattr(sys, 'frozen', False) and os.environ.get('ODS_ADDON_TEST_MODE')=='1':
        # Source-only integration testing: hide bundled availability without
        # renaming/deleting the user's full libraries. Installed packs still
        # undergo real isolated probing and normal activation.
        return False
    root = resource_root()
    if identifier == 'cad_comsol':
        if (root / 'cad_runtime' / 'OCP').is_dir() or (root / 'OCP').is_dir():
            return True
        try:
            return importlib.util.find_spec('OCP') is not None
        except (ImportError, ValueError):
            return False
    candidates = [root, Path(sys.prefix) / 'Library' / 'bin']
    return any(any(p.glob('cublas64_*.dll')) for p in candidates)


def available(identifier):
    return bundled(identifier) or _read_receipt(identifier) is not None


def activate(identifier):
    """Make only a managed, installed pack visible before native imports."""
    directory = _read_receipt(identifier)
    if directory is None:
        return None
    if identifier == 'cad_comsol' and str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    if os.name == 'nt':
        for folder in [directory, *[p for p in directory.iterdir() if p.is_dir() and p.name.endswith('.libs')]]:
            _handles.append(os.add_dll_directory(str(folder)))
    if identifier == 'gpu':
        candidates = sorted(directory.glob('cublas64_*.dll'), reverse=True)
        if candidates:
            os.environ.setdefault('S4_CUBLAS_LIBRARY', str(candidates[0]))
        configured = [p for p in os.environ.get('S4_DLL_DIRS', '').split(os.pathsep) if p]
        if str(directory) not in configured:
            os.environ['S4_DLL_DIRS'] = os.pathsep.join([str(directory), *configured])
    return directory


def _pending(identifier, root):
    path = root/(_id(identifier)+'.pending.json')
    if _linked(path) or not path.is_file() or path.stat().st_size>16384:
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if (value.get('schema')!=1 or value.get('id')!=identifier or value.get('version')!=APP_VERSION
            or not re.fullmatch('[0-9a-f]{64}', value.get('sha256', ''))
            or not re.fullmatch('[0-9a-f]{64}', value.get('manifest_sha256', ''))):
        raise ValueError('Invalid pending add-on receipt.')
    previous = value.get('previous')
    if previous is not None and (not isinstance(previous, dict) or previous.get('id')!=identifier
            or previous.get('version')!=APP_VERSION or not re.fullmatch('[0-9a-f]{64}', previous.get('sha256', ''))):
        raise ValueError('Invalid previous add-on receipt.')
    return value


def pending_addons(root=None):
    """List staged candidates, without activating or loading native libraries."""
    try:
        root = Path(root) if root is not None else addon_root()
    except RuntimeError:
        return []
    return [key for key in ADDONS if (root/(key+'.pending.json')).is_file()]


def _verify_payload(identifier, directory):
    path = directory/'addon.json'
    if _linked(directory) or _linked(path) or not path.is_file() or path.stat().st_size>4*1024**2:
        raise ValueError('Staged add-on manifest is missing or unsafe.')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    hashes = manifest.get('files')
    if (manifest.get('schema')!=1 or manifest.get('id')!=identifier
            or manifest.get('app_version')!=APP_VERSION or manifest.get('platform')!='windows-x64'
            or manifest.get('python')!=f'{sys.version_info.major}.{sys.version_info.minor}'
            or not isinstance(hashes, dict) or not hashes):
        raise ValueError('Staged add-on manifest is incompatible.')
    actual = set()
    for file in directory.rglob('*'):
        if _linked(file):
            raise ValueError('Staged add-on contains a link or junction.')
        if file.is_file() and file.name!='addon.json':
            actual.add(file.relative_to(directory).as_posix())
    if actual!=set(hashes):
        raise ValueError('Staged add-on files differ from the verified manifest.')
    for name, expected in hashes.items():
        relative = _relative(name)
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Staged add-on has an invalid content digest.')
        digest = hashlib.sha256()
        with directory.joinpath(*relative.parts).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024**2), b''):
                digest.update(chunk)
        if digest.hexdigest()!=expected:
            raise ValueError('Staged add-on content failed verification.')
    return manifest


def rollback_pending(identifier, reason, *, root=None):
    """Keep previous activation and both payloads; archive failed candidate info."""
    from data_library import write_json
    root = Path(root) if root is not None else addon_root()
    candidate = _pending(identifier, root)
    if candidate is None:
        return dict(id=identifier, status='not-pending')
    current = _receipt_data(identifier, root)
    # Restore only if a candidate receipt had already been promoted; do not
    # overwrite an unrelated/newer receipt created by another application.
    if current and current['sha256']==candidate['sha256']:
        if candidate.get('previous'):
            write_json(root/(identifier+'.json'), candidate['previous'])
        else:
            (root/(identifier+'.json')).unlink()
    write_json(root/(identifier+'.failed.json'), dict(candidate, reason=str(reason), failed_at=time.time()))
    (root/(identifier+'.pending.json')).unlink()
    return dict(id=identifier, status='rolled-back', error=str(reason))


def validate_pending(identifier, probe, *, root=None):
    """Fresh-start transaction: verify + isolated native probe, then activate.

    probe(identifier, directory) must run native validation in a disposable
    child process and return True only on success. It must not import candidate
    DLLs into the currently running GUI process.
    """
    from data_library import write_json
    root = Path(root) if root is not None else addon_root()
    candidate = _pending(identifier, root)
    if candidate is None:
        return dict(id=identifier, status='not-pending')
    try:
        directory = root/(identifier+'-'+candidate['sha256'])
        if directory.resolve().parent != root.resolve():
            raise ValueError('Staged add-on is outside its owned directory.')
        if hashlib.sha256((directory/'addon.json').read_bytes()).hexdigest()!=candidate['manifest_sha256']:
            raise ValueError('Staged add-on manifest changed after verification.')
        _verify_payload(identifier, directory)
        if probe(identifier, directory) is not True:
            raise RuntimeError('The new add-on failed its isolated native startup check.')
        write_json(root/(identifier+'.json'), dict(id=identifier, version=APP_VERSION, sha256=candidate['sha256']))
        (root/(identifier+'.pending.json')).unlink()
        return dict(id=identifier, status='activated', directory=str(directory))
    except Exception as exc:
        return rollback_pending(identifier, str(exc), root=root)


def probe_native_payload(identifier, directory):
    """Run only in a disposable process before any Qt/scientific app imports."""
    _id(identifier)
    directory = Path(directory).resolve()
    _verify_payload(identifier, directory)
    handles = []
    if os.name!='nt':
        raise RuntimeError('Native GPU/CAD packs require Windows.')
    for folder in [directory, *[p for p in directory.iterdir() if p.is_dir() and p.name.endswith('.libs')]]:
        handles.append(os.add_dll_directory(str(folder)))
    if identifier=='gpu':
        import ctypes
        dlls = sorted(directory.glob('cublas64_*.dll'), reverse=True)
        if not dlls:
            raise RuntimeError('No cuBLAS runtime found.')
        library = ctypes.WinDLL(str(dlls[0]))
        for symbol in ('cublasCreate_v2', 'cublasDestroy_v2', 'cublasDgemm_v2'):
            getattr(library, symbol)
    else:
        sys.path.insert(0, str(directory))
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.BRepCheck import BRepCheck_Analyzer
        shape = BRepPrimAPI_MakeBox(1., 1., 1.).Shape()
        if not BRepCheck_Analyzer(shape).IsValid():
            raise RuntimeError('The CAD runtime could not construct a valid solid.')
    return True


def asset_name(identifier, version=APP_VERSION):
    return f'OpticalDesignStudio-Addon-{_id(identifier)}-{version}-Windows-x64.zip'


class AddonClient(GitHubUpdateClient):
    def check_addon(self, identifier, cancel=None):
        """User-invoked metadata query, exactly the running app's release."""
        name = asset_name(identifier)
        for page in range(1, 101):
            _cancelled(cancel)
            releases = self._json(f'/repos/Wgeshow/Optical-Design-Studio/releases?per_page=100&page={page}', cancel)
            if not isinstance(releases, list):
                raise UpdateError('invalid_response', 'Invalid GitHub release listing.')
            for release in releases:
                if not isinstance(release, dict) or release.get('draft'):
                    continue
                tag = release.get('tag_name')
                if tag != 'addons-v' + APP_VERSION and (tag != 'v' + APP_VERSION or release.get('prerelease')):
                    continue
                assets = release.get('assets', [])
                if not isinstance(assets, list):
                    raise UpdateError('invalid_asset', 'Invalid add-on release metadata.')
                matches = [a for a in assets if isinstance(a, dict) and a.get('name') == name]
                if not matches:
                    continue
                if len(matches) != 1 or matches[0].get('state') != 'uploaded':
                    raise UpdateError('invalid_asset', 'Ambiguous or incomplete add-on package.')
                asset = matches[0]
                digest = asset.get('digest', '')
                if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
                    raise UpdateError('integrity_metadata', 'This add-on has no published GitHub SHA256 digest.')
                info = ReleaseInfo(APP_VERSION, tag, str(release.get('published_at', '')), '',
                    REPOSITORY_URL + '/releases/tag/' + tag, asset.get('id'), name,
                    asset.get('size'), digest[7:].lower())
                self._validate_release(info)
                return info
            if len(releases) < 100:
                return None
        raise UpdateError('listing_limit', 'Too many releases to check reliably.')

    @staticmethod
    def _validate_release(release):
        if (not isinstance(release, ReleaseInfo) or _version(release.version) is None
                or release.version != APP_VERSION or release.tag not in {'v' + APP_VERSION, 'addons-v' + APP_VERSION}
                or release.asset_name not in {asset_name(key) for key in ADDONS}
                or type(release.asset_id) is not int or release.asset_id <= 0
                or type(release.asset_size) is not int or not 0 < release.asset_size <= MAX_UNPACKED
                or not isinstance(release.sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', release.sha256)):
            raise UpdateError('invalid_asset', 'The add-on does not match this application version or platform.')


def _relative(name):
    parts = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or parts.is_absolute()
            or any(p in ('', '.', '..') or p.rstrip(' .') != p for p in name.split('/'))
            or any(p.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1,10)], *[f'LPT{i}' for i in range(1,10)]} for p in parts.parts)):
        raise ValueError('Unsafe add-on archive path.')
    return parts


def install_archive(identifier, archive, release, *, root=None, cancel=None):
    """Stage a verified candidate; active receipts change only at fresh startup."""
    _id(identifier)
    AddonClient._validate_release(release)
    if release.asset_name != asset_name(identifier):
        raise ValueError('The selected pack belongs to another add-on.')
    archive = Path(archive)
    if archive.stat().st_size != release.asset_size:
        raise ValueError('Add-on package size mismatch.')
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            _cancelled(cancel)
            digest.update(chunk)
    if digest.hexdigest() != release.sha256:
        raise ValueError('Add-on package SHA256 mismatch.')
    root = Path(root) if root is not None else addon_root()
    root.mkdir(parents=True, exist_ok=True)
    if _linked(root):
        raise ValueError('Add-on installation directory must not be a link.')
    if identifier in pending_addons(root):
        raise ValueError('This add-on already has a pending installation. Restart the application to verify it.')
    staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=root))
    receipt_temp = None
    try:
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            if len(entries) > 30000 or sum(e.file_size for e in entries) > MAX_UNPACKED:
                raise ValueError('Add-on archive exceeds extraction limits.')
            manifest_entry = package.getinfo('addon.json')
            if manifest_entry.file_size > 4 * 1024**2:
                raise ValueError('Add-on manifest is too large.')
            manifest = json.loads(package.read(manifest_entry))
            if (manifest.get('schema') != 1 or manifest.get('id') != identifier
                    or manifest.get('app_version') != APP_VERSION or manifest.get('platform') != 'windows-x64'
                    or manifest.get('python') != f'{sys.version_info.major}.{sys.version_info.minor}'):
                raise ValueError('Add-on manifest is incompatible with this application.')
            hashes = manifest.get('files')
            if not isinstance(hashes, dict) or not hashes:
                raise ValueError('Add-on manifest has no files.')
            seen = set()
            extracted = set()
            for entry in entries:
                _cancelled(cancel)
                relative = _relative(entry.filename.rstrip('/') if entry.is_dir() else entry.filename)
                key = str(relative).casefold()
                if key in seen or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise ValueError('Duplicate, linked, or encrypted add-on member.')
                seen.add(key)
                if entry.is_dir() or str(relative) == 'addon.json':
                    continue
                expected = hashes.get(str(relative))
                if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
                    raise ValueError('Unlisted add-on file.')
                if identifier == 'gpu' and (len(relative.parts) != 1 or relative.suffix.lower() not in ('.dll', '.txt', '.md')):
                    raise ValueError('Unexpected GPU add-on content.')
                if identifier == 'cad_comsol' and relative.parts[0] not in ('OCP', 'cadquery_ocp.libs', 'vtk.libs', 'licenses'):
                    raise ValueError('Unexpected CAD add-on content.')
                destination = staging.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                file_hash = hashlib.sha256()
                with package.open(entry) as source, destination.open('xb') as target:
                    for chunk in iter(lambda: source.read(1024**2), b''):
                        _cancelled(cancel)
                        target.write(chunk)
                        file_hash.update(chunk)
                if file_hash.hexdigest() != expected:
                    raise ValueError('Add-on content failed its integrity check.')
                extracted.add(str(relative))
            if extracted != set(hashes):
                raise ValueError('Add-on manifest contains missing files.')
            if identifier == 'gpu' and not any(staging.glob('cublas64_*.dll')):
                raise ValueError('GPU runtime is missing from this pack.')
            if identifier == 'cad_comsol' and not (staging / 'OCP' / '__init__.py').is_file():
                raise ValueError('CAD runtime is missing from this pack.')
            (staging/'addon.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        _cancelled(cancel)
        destination = root / (identifier + '-' + release.sha256)
        if destination.exists():
            _verify_payload(identifier, destination)
            if (destination/'addon.json').read_bytes()!=(staging/'addon.json').read_bytes():
                raise ValueError('Existing add-on staging data differs from the verified package.')
        else:
            staging.rename(destination)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=root, prefix='.receipt-', delete=False) as stream:
            receipt_temp = Path(stream.name)
            json.dump({'schema': 1, 'id': identifier, 'version': APP_VERSION, 'sha256': release.sha256,
                       'manifest_sha256': hashlib.sha256((destination/'addon.json').read_bytes()).hexdigest(),
                       'previous': _receipt_data(identifier, root), 'staged_at': time.time()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(receipt_temp, root / (identifier + '.pending.json'))
        return destination
    finally:
        if staging.exists() and staging.resolve().parent == root.resolve() and staging.name.startswith('.staging-'):
            shutil.rmtree(staging)
        if receipt_temp is not None:
            receipt_temp.unlink(missing_ok=True)
