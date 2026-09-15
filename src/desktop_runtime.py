"""Paths and first-run data for the installed Optical Design Studio desktop.

This module intentionally imports no GUI or scientific libraries: the writable
library location must be selected before importing the shared application code.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import sys
import tempfile
import time
import zipfile


def resource_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)).resolve()


def application_root():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else resource_root()


def source_root():
    """The readable source included with the installer, for sharing exports."""
    return resource_root() / 'source' if getattr(sys, 'frozen', False) else resource_root()


def backend_command(job):
    if getattr(sys, 'frozen', False):
        backend = application_root() / 'OpticalDesignBackend.exe'
        if not backend.is_file():
            raise RuntimeError('The installed calculation backend is missing. Run the Optical Design Studio installer again to repair the application.')
        return [str(backend), '--job', str(job)]
    executable = Path(sys.executable)
    # A pythonw-launched source GUI still needs a console interpreter with pipes
    # for the backend's JSON progress stream (its window is hidden by Popen).
    if executable.name.lower() == 'pythonw.exe' and executable.with_name('python.exe').is_file():
        executable = executable.with_name('python.exe')
    return [str(executable), '-u', str(resource_root() / 'backend.py'), '--job', str(job)]


def library_root(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--library', type=Path)
    args, _ = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    if args.library is not None:
        return args.library.expanduser().resolve()
    configured = os.environ.get('S4_LIBRARY_ROOT')
    if configured:
        return Path(configured).expanduser().resolve()
    saved = saved_data_directory()
    if saved is not None:
        return saved
    if not getattr(sys, 'frozen', False):
        return resource_root()
    return default_data_directory()


def default_data_directory():
    return (application_root() / 'User Data').resolve()


def saved_data_directory():
    path = application_root() / 'portable_settings.json'
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 8192:
            raise ValueError('Settings file is too large.')
        data = json.loads(path.read_text(encoding='utf-8'))
        value = data['data_directory']
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Invalid data directory.')
        directory = Path(value).expanduser()
        return (directory if directory.is_absolute() else application_root()/directory).resolve()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('Cannot read portable_settings.json beside the application: ' + str(exc)) from exc


def save_data_directory(directory=None):
    """Persist the next-launch directory without moving or replacing saved work."""
    directory = default_data_directory() if directory is None else Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=directory) as probe:
        probe.write(b'Optical Design Studio write check')
        probe.flush()
    # Relative default lets the whole portable folder move between computers.
    value = 'User Data' if directory == default_data_directory() else str(directory)
    target = application_root()/'portable_settings.json'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix='.storage-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'version': 1, 'data_directory': value}, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return directory


@contextmanager
def _seed_lock(root):
    """Serialize seeding across simultaneous application launches."""
    path = root / '.seed-library.lock'
    stream = path.open('a+b')
    if stream.tell() == 0:
        stream.write(b'0')
        stream.flush()
    deadline = time.monotonic() + 60
    locked = False
    try:
        while not locked:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Another Optical Design Studio window is still preparing the saved library. Try opening the application again shortly.') from None
                time.sleep(.1)
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _safe_parts(info, seen):
    name = info.filename
    path = PurePosixPath(name)
    if (not path.parts or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
            or '/'.join(path.parts) != name.rstrip('/')
            or name.casefold() in seen or any(p.rstrip(' .') != p or PureWindowsPath(p).is_reserved() for p in path.parts)
            or any(ord(c) < 32 or c in '<>"|?*' for c in name)
            or stat.S_ISLNK(info.external_attr >> 16)):
        raise ValueError('The bundled library contains an unsafe or duplicate path.')
    seen.add(name.casefold())
    return path.parts


def seed_library(archive_path, root):
    """Verify the entire seed before adding missing records, never replacing data.

Seed versions are identified by their file content. A successful version is
merged once so that removing a supplied run later is respected on next launch.
"""
    archive_path, root = Path(archive_path), Path(root).resolve()
    if not archive_path.is_file():
        return dict(runs=0, files=0)
    digest = hashlib.sha256()
    with archive_path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    version = digest.hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ('seed-library-' + version + '.complete')
    with _seed_lock(root):
        if marker.is_file():
            return dict(runs=0, files=0)
        counts = dict(runs=0, files=0)
        with tempfile.TemporaryDirectory(prefix='.seed-stage-', dir=root) as temporary:
            stage = Path(temporary)
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                if len(infos) > 100000 or sum(i.file_size for i in infos) > 20 * 1024**3:
                    raise ValueError('The bundled library exceeds its supported size.')
                seen, parts_by_name = set(), {}
                for info in infos:
                    parts_by_name[info.filename] = _safe_parts(info, seen)
                manifest = None
                if 's4-library-manifest.json' in parts_by_name:
                    if archive.getinfo('s4-library-manifest.json').file_size > 32 * 1024**2:
                        raise ValueError('The bundled library manifest is too large.')
                    manifest = json.loads(archive.read('s4-library-manifest.json'))
                    if manifest.get('format') != 's4-library' or manifest.get('version') != 1:
                        raise ValueError('The bundled library manifest is unsupported.')
                    actual = {i.filename for i in infos if not i.is_dir() and i.filename != 's4-library-manifest.json'}
                    if actual != set(manifest['files']):
                        raise ValueError('The bundled library inventory does not match its manifest.')
                for info in infos:
                    parts = parts_by_name[info.filename]
                    if info.is_dir() or info.filename == 's4-library-manifest.json':
                        continue
                    keep = ((len(parts) >= 3 and parts[0] == 'runs') or
                            (len(parts) == 3 and parts[:2] in (('data_library', 'presets'), ('data_library', 'optical_constants'))) or
                            parts == ('data_library', 'desktop_session.json'))
                    if not keep and manifest is None:
                        raise ValueError('The bundled library contains an unexpected file.')
                    target = stage.joinpath(*parts)
                    if keep:
                        target.parent.mkdir(parents=True, exist_ok=True)
                    file_digest, size = hashlib.sha256(), 0
                    with archive.open(info) as src:
                        dst = target.open('wb') if keep else None
                        try:
                            for chunk in iter(lambda: src.read(1024 * 1024), b''):
                                size += len(chunk)
                                file_digest.update(chunk)
                                if dst:
                                    dst.write(chunk)
                        finally:
                            if dst:
                                dst.close()
                    if manifest is not None:
                        expected = manifest['files'][info.filename]
                        if size != expected['size'] or file_digest.hexdigest() != expected['sha256']:
                            raise ValueError('The bundled library has a checksum mismatch: ' + info.filename)
            for path in (stage / 'runs').glob('*'):
                destination = root / 'runs' / path.name
                if not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    path.rename(destination)
                    counts['runs'] += 1
            for path in (stage / 'data_library').rglob('*'):
                if not path.is_file():
                    continue
                destination = root / path.relative_to(stage)
                if not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    path.rename(destination)
                    counts['files'] += 1
        marker.write_text('Bundled library merged without replacing existing user data.\n', encoding='utf-8')
        return counts


def initialize_desktop(argv=None):
    root = library_root(argv)
    os.environ['S4_LIBRARY_ROOT'] = str(root)
    if getattr(sys, 'frozen', False):
        seed_library(resource_root() / 'seed_library.zip', root)
    return root


def set_windows_app_id():
    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('OpticalDesignStudio.Desktop')
