"""Verified, cancellable in-place updates with a recoverable Windows handoff."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile

from desktop_runtime import _safe_parts
from update_client import UpdateCancelled

EXE = 'Optical Design Studio.exe'
PROTECTED = {'user data', 'portable_settings.json', 'runs', 'data_library', 'addons', 'add-ons'}
_RESERVE = 256 * 1024**2


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise UpdateCancelled()


def digest(path, cancel=None):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024**2):
            _cancel(cancel)
            result.update(chunk)
    return result.hexdigest()


def _linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def update_cache_root():
    """Per-user download/helper location; never requires the install's parent."""
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local' / 'share')
    root = base / 'Optical Design Studio' / 'Updates'
    root.mkdir(parents=True, exist_ok=True)
    if _linked(root):
        raise ValueError('The update cache must not be a linked directory.')
    return root.resolve()


def _check_space(directory, required):
    if shutil.disk_usage(directory).free < required:
        raise ValueError(f'Not enough free disk space for the update. Free at least {required / 1024**3:.1f} GB on the drive containing {directory}.')


def preflight_update(target, package_bytes=0):
    """Check actual install/cache access before download. No elevation is used."""
    raw = Path(target)
    if _linked(raw):
        raise ValueError('Cannot update a linked application directory.')
    target = raw.resolve()
    if not (target / EXE).is_file() or not (target / '_internal').is_dir():
        raise ValueError('Run the packaged Windows application to install an update.')
    if _linked(target / EXE) or _linked(target / '_internal'):
        raise ValueError('Cannot update linked application files.')
    cache = update_cache_root()
    try:
        for location in (cache, target):
            with tempfile.TemporaryFile(dir=location) as probe:
                probe.write(b'Optical Design Studio update write check')
                probe.flush()
    except OSError as exc:
        raise PermissionError('This application folder is not writable by your Windows account. The update has not started. Use a per-user installation or ask an administrator to update this installation.') from exc
    _check_space(cache, max(0, int(package_bytes)) + _RESERVE)
    _check_space(target, _RESERVE)
    return cache


def _copy_stream(src, out, cancel=None):
    while chunk := src.read(1024**2):
        _cancel(cancel)
        out.write(chunk)


def _copy_file(source, destination, cancel=None):
    _cancel(cancel)
    if _linked(source):
        raise ValueError('Cannot copy linked application files.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as src, destination.open('wb') as out:
        _copy_stream(src, out, cancel)
    shutil.copystat(source, destination)


def _copy_tree(source, destination, cancel=None):
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        _cancel(cancel)
        if _linked(child):
            raise ValueError('Cannot copy linked application files.')
        if child.is_dir():
            _copy_tree(child, destination / child.name, cancel)
        else:
            _copy_file(child, destination / child.name, cancel)


def _json_write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def stage_update(package, release, target, data_directory, cancel=None, progress=None):
    """Prepare before quitting. progress(done,total) reports preparation units.

    The cache holds the detached helper. A unique transaction inside target
    makes commit/rollback renames work when cache and app are on different drives.
    """
    _cancel(cancel)
    cache = preflight_update(target)
    target, package = Path(target).resolve(), Path(package).resolve()
    if package.suffix.lower() != '.zip':
        raise ValueError('In-place updates require a portable Windows ZIP release.')
    if package.stat().st_size != release.asset_size or digest(package, cancel) != release.sha256:
        raise ValueError('The update package changed after downloading. Download it again.')
    token = uuid.uuid4().hex
    work = Path(tempfile.mkdtemp(prefix='.optical-update-', dir=cache))
    transaction = target / ('.ods-update-' + token)
    stage = work / 'stage'
    stage.mkdir()
    try:
        with zipfile.ZipFile(package) as archive:
            infos = archive.infolist()
            expanded = sum(i.file_size for i in infos)
            if len(infos) > 30000 or expanded > 8 * 1024**3:
                raise ValueError('Update archive exceeds supported limits.')
            _check_space(cache, 3 * expanded + _RESERVE)
            _check_space(target, expanded + _RESERVE)
            seen = set()
            for info in infos:
                _cancel(cancel)
                parts = _safe_parts(info, seen)
                if parts[0] != 'Optical Design Studio' or len(parts) < 2:
                    raise ValueError('Unexpected update archive layout.')
                if parts[1].casefold() in PROTECTED or parts[1].startswith('.ods-update-'):
                    raise ValueError('Update contains user data, settings or add-ons.')
            manifest_name = 'Optical Design Studio/PAYLOAD-MANIFEST.json'
            if archive.getinfo(manifest_name).file_size > 16 * 1024**2:
                raise ValueError('Update manifest is too large.')
            manifest = json.loads(archive.read(manifest_name))
            files = manifest['files']
            actual = {i.filename.split('/', 1)[1] for i in infos if not i.is_dir()}
            if manifest['version'] != release.version or actual != set(files) | {'PAYLOAD-MANIFEST.json'}:
                raise ValueError('Update version or file inventory does not match.')
            if EXE not in files or not any(n.startswith('_internal/') for n in files):
                raise ValueError('Update is missing the application runtime.')
            completed, total = 0, len(actual) * 2 + 2
            if progress:
                progress(0, total)
            for info in infos:
                _cancel(cancel)
                if info.is_dir():
                    continue
                name = info.filename.split('/', 1)[1]
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, dest.open('wb') as out:
                    _copy_stream(src, out, cancel)
                if name in files and (dest.stat().st_size != files[name]['size'] or digest(dest, cancel) != files[name]['sha256']):
                    raise ValueError('Update file failed integrity verification: ' + name)
                completed += 1
                if progress:
                    progress(completed, total)
        names = sorted(p.name for p in stage.iterdir())
        data_directory = Path(data_directory).resolve()
        for name in [*names, 'installation.json']:
            existing = target / name
            if _linked(existing):
                raise ValueError('Cannot update linked application files.')
            if data_directory == existing or data_directory.is_relative_to(existing):
                raise ValueError('The data folder overlaps application files. Choose a separate data folder first.')
        _json_write(stage / 'installation.json', {'version': release.version,
                    'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        if not (target / 'portable_settings.json').exists():
            _json_write(stage / 'portable_settings.json', {'version': 1, 'data_directory': str(data_directory)})
        names = sorted(p.name for p in stage.iterdir())
        transaction.mkdir()
        replacement = transaction / 'new'
        replacement.mkdir()
        for name in names:
            source, dest = stage / name, replacement / name
            if source.is_dir():
                _copy_tree(source, dest, cancel)
            else:
                _copy_file(source, dest, cancel)
        if progress:
            progress(len(actual)*2, total)
        helper = work / 'helper'
        helper.mkdir()
        # Use the newly verified updater implementation, including when the
        # installed version predates this handoff/acknowledgement protocol.
        _copy_file(stage / EXE, helper / EXE, cancel)
        _copy_tree(stage / '_internal', helper / '_internal', cancel)
        if progress:
            progress(total-1, total)
        prepared = {p.relative_to(replacement).as_posix(): {'size': p.stat().st_size, 'sha256': digest(p, cancel)}
                    for p in replacement.rglob('*') if p.is_file()}
        plan = dict(protocol=2, target=str(target), work=str(work), transaction=str(transaction),
                    token=token, version=release.version, names=names, prepared=prepared,
                    parent_pid=os.getpid(), data_directory=str(data_directory),
                    package=str(package) if package.is_relative_to(cache) else None)
        path = work / 'plan.json'
        _json_write(path, plan)
        _cancel(cancel)
        if progress:
            progress(total, total)
        return path
    except Exception:
        if transaction.parent == target and transaction.name == '.ods-update-' + token and transaction.exists():
            shutil.rmtree(transaction)
        if work.parent == cache and work.name.startswith('.optical-update-'):
            shutil.rmtree(work)
        raise


def _read_plan(plan):
    plan = Path(plan).resolve()
    if plan.stat().st_size > 16 * 1024**2:
        raise ValueError('Invalid update plan.')
    job = json.loads(plan.read_text(encoding='utf-8'))
    work = plan.parent
    target = Path(job['target']).resolve()
    transaction = Path(job['transaction']).resolve()
    token = job.get('token', '')
    if (job.get('protocol') != 2 or len(token) != 32 or any(c not in '0123456789abcdef' for c in token)
            or Path(job['work']).resolve() != work or work.parent != update_cache_root()
            or not work.name.startswith('.optical-update-') or transaction.parent != target
            or transaction.name != '.ods-update-' + token or _linked(transaction) or _linked(target)):
        raise ValueError('Invalid update target.')
    names = job['names']
    if not names or len(names) != len(set(names)) or any(not isinstance(n, str) or Path(n).name != n
            or n in ('.', '..') or (n.casefold() in PROTECTED and n != 'portable_settings.json') for n in names):
        raise ValueError('Invalid replacement file.')
    return job, work, target, transaction


def launch_update(plan):
    _, work, _, _ = _read_plan(plan)
    helper = work / 'helper' / EXE
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    process = subprocess.Popen([str(helper), '--apply-update', str(Path(plan).resolve())],
                               cwd=work, creationflags=flags, close_fds=True)
    # The original GUI quits only after the independent helper is waiting for it.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            ready = json.loads((work / 'helper.json').read_text(encoding='utf-8'))
            if ready.get('pid') == process.pid:
                return process
        except (OSError, ValueError):
            pass
        if process.poll() is not None:
            raise RuntimeError('The update helper could not start. The application remains open and unchanged.')
        time.sleep(.05)
    process.terminate()
    raise RuntimeError('The update helper did not become ready. The application remains open and unchanged; retry the update.')


def discard_staged(plan):
    """Cancel a completed preparation before helper launch; keep verified ZIP."""
    _, work, _, transaction = _read_plan(plan)
    if any((work/name).exists() for name in ('helper.json', 'installed.json', 'success.json')) or (transaction/'backup').exists():
        raise ValueError('Installation has started; staged files cannot be discarded.')
    if transaction.exists():
        shutil.rmtree(transaction)
    shutil.rmtree(work)


def wait_for_exit(pid):
    import ctypes
    from ctypes import wintypes
    ctypes.windll.kernel32.OpenProcess.restype = wintypes.HANDLE
    ctypes.windll.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    ctypes.windll.kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    ctypes.windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    process = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)
    if not process and ctypes.windll.kernel32.GetLastError() != 87:
        raise RuntimeError('Could not confirm that the application exited. Existing files have not been replaced.')
    if process:
        try:
            if ctypes.windll.kernel32.WaitForSingleObject(process, 120000) != 0:
                raise RuntimeError('Application did not close; update was not installed.')
        finally:
            ctypes.windll.kernel32.CloseHandle(process)


def _relaunch(target, plan=None):
    args = ['--update-ack', str(plan)] if plan is not None else []
    try:
        os.startfile(str(target / EXE), 'open', arguments=subprocess.list2cmdline(args), cwd=str(target))
    except (AttributeError, OSError):
        flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        subprocess.Popen([str(target / EXE), *args], cwd=target, creationflags=flags, close_fds=True)


def wait_for_ack(work, token, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = json.loads((work / 'startup-ack.json').read_text(encoding='utf-8'))
            if data.get('token') == token:
                return True
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    return False


def apply_staged(plan):
    """Copied helper: verify preparation, commit with rollback, launch, await GUI."""
    job, work, target, transaction = _read_plan(plan)
    if not (target / EXE).is_file():
        raise ValueError('Existing application was not found.')
    _json_write(work / 'helper.json', {'pid': os.getpid()})
    wait_for_exit(job['parent_pid'])
    replacement = transaction / 'new'
    actual = {p.relative_to(replacement).as_posix() for p in replacement.rglob('*') if p.is_file()}
    if actual != set(job['prepared']):
        raise ValueError('Prepared update inventory changed. The existing application is unchanged.')
    for name, info in job['prepared'].items():
        path = replacement / name
        if not path.resolve().is_relative_to(replacement.resolve()) or _linked(path) or path.stat().st_size != info['size'] or digest(path) != info['sha256']:
            raise ValueError('Prepared update failed verification. The existing application is unchanged.')
    backup = transaction / 'backup'
    backup.mkdir()
    moved, installed = [], []
    try:
        for name in job['names']:
            old = target / name
            if _linked(old):
                raise ValueError('Application files changed to links; update cancelled.')
            if name == 'portable_settings.json' and old.exists():
                raise ValueError('Portable settings changed while preparing the update; retry.')
            if old.exists():
                old.rename(backup / name)
                moved.append(name)
            (replacement / name).rename(old)
            installed.append(name)
    except Exception as exc:
        failures = []
        for name in reversed(installed):
            try:
                (target / name).rename(replacement / name)
            except OSError as error:
                failures.append(str(error))
        for name in reversed(moved):
            try:
                (backup / name).rename(target / name)
            except OSError as error:
                failures.append(str(error))
        if failures:
            raise RuntimeError(f'Update failed and automatic recovery was incomplete. Backups remain in {backup}. ' + '; '.join(failures)) from exc
        try:
            _relaunch(target)
        except OSError:
            pass
        raise RuntimeError('Update was not installed. Previous application files were restored. ' + str(exc)) from exc
    _json_write(work / 'installed.json', {'version': job['version'], 'token': job['token']})
    try:
        _relaunch(target, Path(plan).resolve())
    except OSError as exc:
        raise RuntimeError(f'Update installed, but the application could not restart. Open {target / EXE}. Recovery files are retained in {transaction}. {exc}') from exc
    if not wait_for_ack(work, job['token']):
        raise RuntimeError(f'Update installed, but successful startup was not confirmed. Open {target / EXE}. Recovery files are retained in {transaction}.')
    _json_write(work / 'success.json', {'version': job['version'], 'token': job['token']})


def _cleanup_after_helper(plan):
    """New GUI thread: helper DLLs must unload before deleting its cache."""
    try:
        job, work, _, transaction = _read_plan(plan)
        helper = json.loads((work / 'helper.json').read_text(encoding='utf-8'))
        wait_for_exit(helper['pid'])
        success = json.loads((work / 'success.json').read_text(encoding='utf-8'))
        if success.get('token') != job['token']:
            return
        if transaction.exists():
            shutil.rmtree(transaction)
        package = Path(job['package']).resolve() if job.get('package') else None
        if package is not None and package.is_relative_to(update_cache_root()) and package.is_file():
            package.unlink()
        shutil.rmtree(work)
    except (OSError, ValueError, KeyError, RuntimeError):
        return


def acknowledge_startup(plan):
    """Call after the updated GUI/store are ready, for --update-ack PLAN."""
    try:
        job, work, target, _ = _read_plan(plan)
        from app_version import APP_VERSION
        if not getattr(sys, 'frozen', False) or Path(sys.executable).resolve() != target / EXE or APP_VERSION != job['version']:
            return False
        installed = json.loads((work / 'installed.json').read_text(encoding='utf-8'))
        if installed.get('token') != job['token']:
            return False
        _json_write(work / 'startup-ack.json', {'token': job['token'], 'version': APP_VERSION})
        threading.Thread(target=_cleanup_after_helper, args=(plan,), daemon=True, name='update-cleanup').start()
        return True
    except (OSError, ValueError, KeyError):
        return False


def helper_main(plan):
    try:
        apply_staged(plan)
        return 0
    except Exception as exc:
        try:
            Path(plan).with_suffix('.error.txt').write_text(str(exc), encoding='utf-8')
        except OSError:
            pass
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(exc), 'Optical Design Studio update', 0x10)
        return 1
