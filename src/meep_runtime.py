"""Explicitly configured, isolated Meep runtime; no startup downloads."""
from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import signal
import subprocess
import sys
import queue
import threading
import time

PROBE = "import meep as mp; import numpy; print('ODS_MEEP_VERSION='+str(mp.__version__)); assert hasattr(mp, 'Simulation')"


def configuration_path():
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.config')
    return base/'Optical Design Studio'/'meep-runtime.json'


def default_config():
    return dict(mode='wsl' if sys.platform == 'win32' else 'local', distro='Ubuntu',
        python='/home/USER/miniforge3/envs/ods-meep/bin/python' if sys.platform == 'win32' else 'python3',
        conda='/home/USER/miniforge3/bin/conda')


def load_config():
    try:
        return validate_config(json.loads(configuration_path().read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return default_config()


def validate_config(config):
    result = dict(default_config(), **config)
    if result['mode'] not in ('wsl', 'local'):
        raise ValueError('Choose WSL on Windows or a local Linux/macOS runtime.')
    if sys.platform == 'win32' and result['mode'] == 'local':
        raise ValueError('Meep does not support native Windows. Choose the WSL runtime.')
    for key in ('python', 'conda', 'distro'):
        if not isinstance(result[key], str) or not result[key].strip() or any(c in result[key] for c in '\r\n\0'):
            raise ValueError(f'Enter a valid {key} value.')
        result[key] = result[key].strip()
    if result['mode']=='wsl' and (not result['python'].startswith('/') or not result['conda'].startswith('/')):
        raise ValueError('Python and Conda must be absolute Linux paths inside the selected WSL distribution.')
    return result


def save_config(config):
    from data_library import write_json
    config = validate_config(config)
    write_json(configuration_path(), config)
    return config


def command(config, arguments, executable=None):
    config = validate_config(config)
    base = ['wsl.exe', '--distribution', config['distro'], '--exec'] if config['mode']=='wsl' else []
    return base+[executable or config['python']]+list(arguments)


def process_options():
    return dict(creationflags=subprocess.CREATE_NO_WINDOW) if sys.platform=='win32' else {}


def probe(config=None):
    config = config or load_config()
    try:
        result = subprocess.run(command(config, ['-c', PROBE]), capture_output=True,
            timeout=25, encoding='utf-8', errors='replace', **process_options())
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return dict(available=False, message=str(exc))
    version = next((line.split('=', 1)[1] for line in result.stdout.splitlines() if line.startswith('ODS_MEEP_VERSION=')), '')
    return dict(available=result.returncode==0 and bool(version), version=version,
        message=('Meep '+version+' is ready.') if version and result.returncode==0 else (result.stderr or result.stdout or 'Meep is not installed in the selected Python runtime.').replace('\0', '').strip())


def linux_path(path, config):
    path = str(Path(path).resolve())
    if config['mode'] != 'wsl':
        return path
    if config.get('managed'):
        # The managed image pins automount root=/mnt. Custom imported images
        # need not contain the optional wslpath helper executable.
        windows = PureWindowsPath(path)
        if len(windows.drive)!=2 or windows.drive[1]!=':' or not windows.drive[0].isalpha():
            raise RuntimeError('The managed FDTD engine needs the project library on a local Windows drive.')
        return '/mnt/'+windows.drive[0].lower()+'/'+ '/'.join(windows.parts[1:])
    result = subprocess.run(['wsl.exe', '--distribution', config['distro'], '--exec',
        'wslpath', '-a', '-u', path], capture_output=True, timeout=15,
        encoding='utf-8', errors='replace', **process_options())
    if result.returncode or not result.stdout.strip().startswith('/'):
        raise RuntimeError('WSL could not access the saved job directory: '+result.stderr.strip())
    return result.stdout.strip()


def install_command(config):
    config = validate_config(config)
    # Install into the explicitly selected interpreter prefix; Conda owns this
    # isolated environment. No shell interpolation and no OS/distro install.
    interpreter = config['python'].replace('\\', '/')
    if not interpreter.endswith('/bin/python'):
        raise ValueError('For installation, choose an isolated environment path ending in /bin/python (for example /home/alice/miniforge3/envs/ods-meep/bin/python).')
    prefix = interpreter[:-len('/bin/python')]
    if not prefix.endswith('/envs/ods-meep'):
        raise ValueError('The managed installation target must end in /envs/ods-meep to protect other Python environments.')
    return command(config, ['create', '--yes', '--prefix', prefix,
        '--override-channels', '--channel', 'conda-forge', 'pymeep', 'numpy'], executable=config['conda'])


def copy_runner(directory):
    directory = Path(directory)
    source = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))/'meep_runner.py'
    if not source.is_file():
        raise RuntimeError('The installed package is missing the Meep worker source. Repair or update Optical Design Studio.')
    destination = directory/'meep_runner.py'
    shutil.copyfile(source, destination)
    return destination


class ManagedProcess:
    """Stream a child without blocking cancellation; terminate its own group."""

    def __init__(self, config, argv):
        self.config = config
        self.linux_pid = None
        if config['mode']=='wsl':
            # Positional arguments avoid interpolating user paths into shell
            # source. setsid creates an isolated group for precise cancellation.
            argv = argv[:4]+['setsid', 'sh', '-c',
                'printf "ODS_MEEP_PID=%s\\n" "$$"; exec "$@"', 'ods-meep']+argv[4:]
        options = process_options()
        if config['mode']=='local':
            options['start_new_session'] = True
        self.process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1, **options)
        self.lines = queue.Queue()
        def reader():
            try:
                for line in self.process.stdout:
                    self.lines.put(line)
            finally:
                self.lines.put(None)
        threading.Thread(target=reader, daemon=True).start()

    def terminate(self, force=False):
        if self.process.poll() is not None:
            return
        try:
            if self.config['mode']=='wsl' and self.linux_pid:
                subprocess.run(['wsl.exe', '--distribution', self.config['distro'], '--exec',
                    'kill', '-KILL' if force else '-TERM', '--', '-'+str(self.linux_pid)],
                    timeout=5, capture_output=True, **process_options())
            elif self.config['mode']=='local':
                os.killpg(self.process.pid, signal.SIGKILL if force else signal.SIGTERM)
            else:
                # No Linux PID was emitted: the WSL launcher itself is stuck.
                self.process.kill() if force else self.process.terminate()
        except (OSError, subprocess.TimeoutExpired):
            if force:
                self.process.kill()

    def stream(self, cancelled, timeout=86400):
        started, requested = time.monotonic(), None
        while True:
            now = time.monotonic()
            if now-started > timeout:
                self.terminate(force=True)
                raise TimeoutError('The Meep operation exceeded its time limit.')
            if cancelled.is_set():
                if requested is None:
                    requested = now
                    if self.config['mode']!='wsl' or self.linux_pid or now-started > 3:
                        self.terminate()
                elif self.config['mode']=='wsl' and self.linux_pid and now-requested < 1:
                    self.terminate()
                elif now-requested > 5:
                    self.terminate(force=True)
            try:
                line = self.lines.get(timeout=.2)
            except queue.Empty:
                continue
            if line is None:
                break
            if line.startswith('ODS_MEEP_PID='):
                value = line.strip().split('=', 1)[1]
                if value.isdecimal() and int(value)>1:
                    self.linux_pid = int(value)
            else:
                yield line
        return self.process.wait(timeout=10)
