"""Stage verified portable updates and replace an existing Windows application."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

from desktop_runtime import _safe_parts

EXE = 'Optical Design Studio.exe'
PROTECTED = {'user data', 'portable_settings.json', 'runs', 'data_library'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stage_update(package, release, target, data_directory):
    """Fully verify/extract before closing the GUI or touching installed files."""
    target = Path(target).resolve()
    if not (target / EXE).is_file() or not (target / '_internal').is_dir():
        raise ValueError('Run the packaged Windows application to install an update.')
    if Path(package).suffix.lower() != '.zip':
        raise ValueError('In-place updates require a portable Windows ZIP release.')
    if Path(package).stat().st_size != release.asset_size or digest(package) != release.sha256:
        raise ValueError('The update package changed after downloading. Download it again.')
    work = Path(tempfile.mkdtemp(prefix='.optical-update-', dir=target.parent))
    stage = work / 'stage'
    stage.mkdir()
    try:
        with zipfile.ZipFile(package) as archive:
            infos = archive.infolist()
            if len(infos) > 30000 or sum(i.file_size for i in infos) > 8 * 1024**3:
                raise ValueError('Update archive exceeds supported limits.')
            helper_bytes = sum(p.stat().st_size for p in (target / '_internal').rglob('*') if p.is_file())
            required = sum(i.file_size for i in infos) + helper_bytes + (target / EXE).stat().st_size + 256 * 1024**2
            if shutil.disk_usage(target.parent).free < required:
                raise ValueError(f'Not enough free space beside the application. Free at least {required / 1024**3:.1f} GB before retrying.')
            seen = set()
            for info in infos:
                parts = _safe_parts(info, seen)
                if parts[0] != 'Optical Design Studio' or len(parts) < 2:
                    raise ValueError('Unexpected update archive layout.')
                if parts[1].casefold() in PROTECTED:
                    raise ValueError('Update contains user data or settings.')
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
            for info in infos:
                if info.is_dir():
                    continue
                name = info.filename.split('/', 1)[1]
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, dest.open('wb') as out:
                    shutil.copyfileobj(src, out)
                if name in files and (dest.stat().st_size != files[name]['size'] or digest(dest) != files[name]['sha256']):
                    raise ValueError('Update file failed integrity verification: ' + name)
        # A separate copy keeps the helper's loaded DLLs out of the replacement target.
        helper = work / 'helper'
        helper.mkdir()
        shutil.copy2(target / EXE, helper / EXE)
        shutil.copytree(target / '_internal', helper / '_internal')
        names = sorted(p.name for p in stage.iterdir())
        data_directory = Path(data_directory).resolve()
        for name in names:
            existing = target / name
            if existing.is_symlink() or (hasattr(existing, 'is_junction') and existing.is_junction()):
                raise ValueError('Cannot update linked application files.')
            if data_directory == existing or data_directory.is_relative_to(existing):
                raise ValueError('The data folder overlaps application files. Choose a separate data folder first.')
        plan = dict(target=str(target), work=str(work), version=release.version,
                    names=names, parent_pid=os.getpid(), data_directory=str(data_directory))
        path = work / 'plan.json'
        path.write_text(json.dumps(plan), encoding='utf-8')
        return path
    except Exception:
        # Retain failed staging for diagnosis; installed files remain untouched.
        raise


def launch_update(plan):
    plan = Path(plan).resolve()
    helper = plan.parent / 'helper' / EXE
    return subprocess.Popen([str(helper), '--apply-update', str(plan)], cwd=plan.parent,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def wait_for_exit(pid):
    import ctypes
    from ctypes import wintypes
    ctypes.windll.kernel32.OpenProcess.restype = wintypes.HANDLE
    ctypes.windll.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    ctypes.windll.kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    ctypes.windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    process = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)
    if process:
        try:
            if ctypes.windll.kernel32.WaitForSingleObject(process, 120000) != 0:
                raise RuntimeError('Application did not close; update was not installed.')
        finally:
            ctypes.windll.kernel32.CloseHandle(process)


def apply_staged(plan):
    """Run only in the copied helper, after the parent has exited."""
    plan = Path(plan).resolve()
    job = json.loads(plan.read_text(encoding='utf-8'))
    work = plan.parent
    target = Path(job['target']).resolve()
    if Path(job['work']).resolve() != work or target.parent != work.parent or target == work:
        raise ValueError('Invalid update target.')
    if not (target / EXE).is_file():
        raise ValueError('Existing application was not found.')
    names = job['names']
    if any(Path(n).name != n or n in ('.', '..') or n.casefold() in PROTECTED for n in names):
        raise ValueError('Invalid replacement file.')
    wait_for_exit(job['parent_pid'])
    backup = work / 'backup'
    backup.mkdir()
    moved, installed = [], []
    try:
        for name in names:
            old = target / name
            if old.exists():
                old.rename(backup / name)
                moved.append(name)
            (work / 'stage' / name).rename(old)
            installed.append(name)
        # Retain the exact current data location, including older installed layouts.
        settings = target / 'portable_settings.json'
        if not settings.exists():
            settings.write_text(json.dumps({'version': 1, 'data_directory': job['data_directory']}), encoding='utf-8')
        (target / 'installation.json').write_text(json.dumps({'version': job['version'],
            'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}), encoding='utf-8')
    except Exception:
        for name in reversed(installed):
            (target / name).rename(work / 'stage' / name)
        for name in reversed(moved):
            (backup / name).rename(target / name)
        raise
    subprocess.Popen([str(target / EXE)], cwd=target)


def helper_main(plan):
    try:
        apply_staged(plan)
        return 0
    except Exception as exc:
        Path(plan).with_suffix('.error.txt').write_text(str(exc), encoding='utf-8')
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, 'Update could not finish. Your previous application files were retained or restored.\n' + str(exc), 'Optical Design Studio update', 0x10)
        return 1
