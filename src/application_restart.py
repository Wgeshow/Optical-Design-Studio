"""Restart this exact application after native add-on libraries unload."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time


def _identity():
    frozen = bool(getattr(sys, 'frozen', False))
    executable = Path(sys.executable).resolve()
    source = Path(__file__).resolve().parent
    return executable, executable.parent if frozen else source, frozen


def _write(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def prepare_restart(data_directory, *, store=None, busy_checks=()):
    """Save before preparing; never close an app while background work is active."""
    if (store is not None and store.busy) or any(check() for check in busy_checks):
        raise RuntimeError('Wait for active calculations, updates and add-on operations before restarting.')
    if store is not None:
        store._autosave()
    library = Path(data_directory).expanduser().resolve(strict=True)
    if not library.is_dir():
        raise ValueError('The current data directory is unavailable.')
    executable, application, frozen = _identity()
    nonce = secrets.token_hex(24)
    directory = library / '.application-restart' / nonce
    directory.mkdir(parents=True, exist_ok=False)
    plan = directory / 'plan.json'
    _write(plan, {'version': 1, 'nonce': nonce, 'parent_pid': os.getpid(),
        'created': time.time(), 'library': str(library), 'executable': str(executable),
        'application': str(application), 'frozen': frozen})
    return plan


def _read(plan):
    original = Path(plan)
    path = original.resolve(strict=True)
    if original.is_symlink() or path.name != 'plan.json' or path.stat().st_size > 8192:
        raise ValueError('Invalid restart plan.')
    data = json.loads(path.read_text(encoding='utf-8'))
    executable, application, frozen = _identity()
    library = Path(data['library']).resolve(strict=True)
    nonce = data.get('nonce', '')
    if (data.get('version') != 1 or len(nonce) != 48 or
        any(character not in '0123456789abcdef' for character in nonce) or
        path.parent != library / '.application-restart' / nonce or
        Path(data['executable']).resolve() != executable or
        Path(data['application']).resolve() != application or data['frozen'] != frozen or
        type(data.get('parent_pid')) is not int or data['parent_pid'] <= 0 or
        not 0 <= time.time()-data['created'] <= 600):
        raise ValueError('Restart plan does not belong to this application session.')
    return path, data


def _spawn(command, cwd, env=None):
    options = dict(cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options['start_new_session'] = True
    return subprocess.Popen(command, **options)


def launch_restart(plan):
    """Return only once the helper is ready; caller then closes normally."""
    path, data = _read(plan)
    if data['parent_pid'] != os.getpid():
        raise ValueError('Only the preparing application can request this restart.')
    command = [data['executable']]
    if not data['frozen']:
        command.append(str(Path(__file__).resolve()))
    command += ['--restart-app', str(path)]
    process = _spawn(command, data['application'])
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        ready = path.parent/'ready.json'
        if ready.is_file():
            receipt = json.loads(ready.read_text(encoding='utf-8'))
            if receipt.get('nonce') == data['nonce'] and receipt.get('pid') == process.pid:
                return process
        if process.poll() is not None:
            break
        time.sleep(.05)
    # Parent stays open on failure. Stop only our own helper, never another app.
    if process.poll() is None:
        process.terminate()
    raise RuntimeError('The restart helper did not become ready. The application is still open.')


def _wait_parent(pid):
    if os.name == 'nt':
        from update_install import wait_for_exit
        wait_for_exit(pid)
        return
    deadline = time.monotonic()+120
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(.1)
    raise RuntimeError('Application did not close; restart was cancelled.')


def restart_helper_main(plan):
    path, data = _read(plan)
    if data['parent_pid'] == os.getpid():
        raise ValueError('Restart helper cannot wait on itself.')
    status = path.parent/'status.json'
    try:
        _write(path.parent/'ready.json', {'nonce': data['nonce'], 'pid': os.getpid()})
        _wait_parent(data['parent_pid'])
        command = [data['executable']]
        if not data['frozen']:
            command.append(str(Path(data['application'])/'qt_app.py'))
        command += ['--library', data['library']]
        environment = dict(os.environ, S4_LIBRARY_ROOT=data['library'], ODS_RESTART_PLAN=str(path))
        process = _spawn(command, data['application'], environment)
        _write(status, {'state': 'launched', 'pid': process.pid})
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            if (path.parent/'started.json').is_file():
                receipt = json.loads((path.parent/'started.json').read_text(encoding='utf-8'))
                if receipt.get('nonce') == data['nonce'] and receipt.get('pid') == process.pid:
                    _write(status, {'state': 'started', 'pid': process.pid})
                    return 0
            if process.poll() is not None:
                raise RuntimeError('The restarted application exited before startup completed. Open the application manually to recover.')
            time.sleep(.1)
        raise RuntimeError('The application was launched but startup was not confirmed. Check the running application before retrying.')
    except Exception as error:
        _write(status, {'state': 'failed', 'error': str(error)})
        return 1


def acknowledge_restart():
    """Root calls this only after the window and add-on checks are ready."""
    raw = os.environ.pop('ODS_RESTART_PLAN', None)
    if not raw:
        return False
    try:
        path, data = _read(raw)
        _write(path.parent/'started.json', {'nonce': data['nonce'], 'pid': os.getpid()})
        return True
    except (OSError, ValueError, KeyError, TypeError):
        # A stale environment receipt must not take down a healthy GUI. The
        # waiting helper records unconfirmed startup independently.
        return False


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--restart-app':
        raise SystemExit('Restart helper requires a prepared plan.')
    raise SystemExit(restart_helper_main(sys.argv[2]))
