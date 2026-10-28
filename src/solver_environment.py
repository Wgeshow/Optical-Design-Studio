"""User-initiated, isolated solver setup. Importing this module never installs.

The installer only writes its own versioned environments. A runtime is published
after its actual required API starts successfully; an import check is not a
scientific validation. Existing user interpreters/distributions are read-only
during discovery. MPB packages are installed inside an app-owned prefix.
"""
from __future__ import annotations

import hashlib
import json
from meep_runtime import wsl_executable
import os
from pathlib import Path
import platform
import queue
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from urllib.request import urlopen
import uuid
import zipfile


UV_VERSION = '0.11.19'
UV_ASSETS = {
    'win32': dict(url='https://files.pythonhosted.org/packages/d4/43/f374fad7ad94e4a8c47cf09f00d803c76c6cc7f225668c41f4e2fb5de000/uv-0.11.19-py3-none-win_amd64.whl',
        bytes=25143888, sha256='480fc34a8d0967af6a90b3f99a6e5687cd5c6e29528de96bec04d6e305a59363'),
    'linux': dict(url='https://files.pythonhosted.org/packages/5a/74/2bd8b51e1d76210fd424ae55ec3f34ded5a10eeff3dd38aeb03c816a0af2/uv-0.11.19-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl',
        bytes=24872664, sha256='731d9fab8db5d41590af64236d03f8069c8da665fd0f9493b85985f19c86cd90'),
}
MICROMAMBA = dict(url='https://conda.anaconda.org/conda-forge/linux-64/micromamba-2.3.3-0.tar.bz2',
    bytes=6515385, sha256='e7274528ceb9c20d048a428d6c22d7e02e268f8ffb762c4c365422347c8b8ba2')
SESAME_COMMIT = 'e2769a9d15c64415a87a5cfb566cbf2f3dac309f'
BASE_PACKAGES = ['numpy==1.26.4', 'scipy==1.16.3', 'matplotlib==3.8.4']
PACKAGES = {
    'legume': ['legume-gme==1.0.3'],
    'gmsh': ['gmsh==4.13.1'],
    # The unrelated package named "sesame" on PyPI is not this NIST solver.
    'sesame': ['https://github.com/usnistgov/sesame/archive/'+SESAME_COMMIT+'.zip'],
}
PROBES = {
    'legume': 'import legume; from legume import PhotCryst, PlaneWaveExp, GuidedModeExp, Circle, Poly',
    'sesame': 'import sesame; from sesame import Builder, solve, IVcurve, Analyzer',
    'gmsh': 'import gmsh; gmsh.initialize(); gmsh.finalize()',
    'meep': 'import meep; assert hasattr(meep, "Simulation")',
}
WSL_PACKAGES = {'mpb': ['mpb=1.11.1'], 'meep': ['pymeep=1.30.0=nompi_py311*', 'python=3.11',
    'numpy=1.26.4', 'scipy=1.16.3', 'matplotlib-base=3.8.4', 'mkl=2023.2.0', 'mpb=1.12.0']}
DISTRO = 'OpticalDesignStudio-Research-v1'
_locks = {}
_lock_guard = threading.Lock()


def root_directory():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.local/share')/'OpticalDesignStudio'/'SolverEnvironments'


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError('Solver setup cancelled. Existing installations were preserved; you can retry setup.')


def _owned_path(root, path):
    root, path = Path(os.path.abspath(root)), Path(os.path.abspath(path))
    if path != root and root not in path.parents:
        raise ValueError('Solver setup path is outside its managed directory.')
    if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in (path, *path.parents)):
        raise ValueError('Solver setup directories must not contain links or junctions.')
    return path


def _write_json(path, value):
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def _environment(root=None):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('UV_', 'PIP_')) or key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
            env.pop(key, None)
    env.update(PYTHONNOUSERSITE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', MPLBACKEND='Agg')
    if root is not None:
        env.update(UV_PYTHON_INSTALL_DIR=str(root/'python'), UV_CACHE_DIR=str(root/'cache'),
            UV_PYTHON_NO_REGISTRY='1', UV_NO_PROGRESS='1', UV_LINK_MODE='copy',
            TMP=str(root/'tmp'), TEMP=str(root/'tmp'), TMPDIR=str(root/'tmp'))
    return env


def _run(command, *, cancel=None, progress=lambda text: None, timeout=1200, env=None):
    """Stream diagnostics and kill the full child tree on cancellation on Windows."""
    _check_cancel(cancel)
    options = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else dict(start_new_session=True)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', env=env or _environment(), **options)
    messages = queue.Queue()
    def reader():
        try:
            for line in process.stdout:
                messages.put(line)
        finally:
            messages.put(None)
    threading.Thread(target=reader, daemon=True).start()
    started, tail = time.monotonic(), []
    try:
        while True:
            _check_cancel(cancel)
            if time.monotonic()-started > timeout:
                raise TimeoutError('Solver setup step timed out. Check the network and retry.\n'+'\n'.join(tail[-8:]))
            try:
                line = messages.get(timeout=.1)
            except queue.Empty:
                continue
            if line is None:
                break
            line = line.rstrip().replace('\0', '')
            tail.append(line)
            tail = tail[-160:]
            progress(line)
        code = process.wait(timeout=10)
        if code:
            raise RuntimeError('Solver setup command failed (exit '+str(code)+').\n'+'\n'.join(tail[-16:]))
        return '\n'.join(tail)
    finally:
        if process.poll() is None:
            if os.name == 'nt':
                try:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                        timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                if process.poll() is None:
                    process.kill()
            else:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=15)
        process.stdout.close()


def probe(engine, runtime, *, cancel=None):
    if engine not in {*PACKAGES, *WSL_PACKAGES}:
        raise ValueError('Unsupported solver environment: '+str(engine))
    executable = runtime.get('executable', '')
    if not executable:
        raise ValueError('No solver executable has been configured.')
    mode = runtime.get('mode', 'local')
    prefix = [wsl_executable(), '--distribution', runtime.get('distro', 'Ubuntu'), '--exec'] if mode == 'wsl' else []
    if engine == 'mpb':
        output = _run(prefix+[executable, '--version'], cancel=cancel, timeout=25)
        if 'mpb' not in output.lower():
            raise RuntimeError('The executable did not identify itself as MPB.')
    else:
        from research_physics_runtime import validate_runtime
        runtime = validate_runtime(runtime)
        code = ("import sys,json,os; r=json.loads(sys.argv[1]); sys.path[:0]=r.get('module_paths',[]); "
            "import numpy,scipy; "+PROBES[engine]+"; print('ODS_SOLVER_READY')")
        if mode == 'wsl' and runtime['library_paths']:
            prefix += ['env', 'LD_LIBRARY_PATH='+':'.join(runtime['library_paths'])]
        environment = _environment()
        if mode == 'local' and runtime['library_paths']:
            environment['PATH'] = os.pathsep.join(runtime['library_paths']+[environment.get('PATH', '')])
        output = _run(prefix+[executable, '-c', code, json.dumps(runtime)], cancel=cancel, timeout=30, env=environment)
        if 'ODS_SOLVER_READY' not in output.splitlines():
            raise RuntimeError('The required solver API did not pass its installation check.')
    return dict(runtime)


def saved_runtime(engine, root=None, *, discovery_candidate=False):
    root = Path(root) if root is not None else root_directory()
    try:
        file = _owned_path(root, root/(engine+'.json'))
        value = json.loads(file.read_text(encoding='utf-8'))
        saved_root = value.get('root')
        same_root = saved_root == str(root.resolve())
        # MSIX file virtualization can leave a receipt in the real user folder
        # with its old virtual root in metadata. Discovery may probe that
        # existing runtime, but must never treat it as installer-owned or
        # rewrite the receipt merely because its API works.
        relocated_candidate = (discovery_candidate and isinstance(saved_root,str)
                               and Path(saved_root).is_absolute())
        if (value.get('schema') == 1 and value.get('engine') == engine
                and (same_root or relocated_candidate) and isinstance(value.get('runtime'),dict)):
            return value['runtime']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {}


def discover(engine, configured=None, *, root=None, cancel=None, progress=lambda text: None):
    """Probe known locations; never install into an environment found here."""
    def candidates():
        # Find installed solver prefers the last verified installation. Checking
        # one specific selection remains the separate Check solver action.
        yield saved_runtime(engine, root, discovery_candidate=True)
        yield configured or {}
        # Enumerating or starting another WSL distribution can be slow. Delay
        # that work until both known locations have actually failed their probe.
        if engine in WSL_PACKAGES:
            if os.name == 'nt' and shutil.which(wsl_executable()):
                progress('Looking for installed WSL distributions…')
                try:
                    names = _run([wsl_executable(), '--list', '--quiet'], cancel=cancel, timeout=15).replace('\ufeff', '').splitlines()
                except (OSError, RuntimeError, TimeoutError):
                    names = []
                yield from (dict(mode='wsl', distro=name.strip(), executable='mpb' if engine == 'mpb' else '/usr/bin/python3', timeout_s=86400.) for name in names if name.strip())
                # Recover working app-owned environments even if Windows settings
                # were reset or a different portable copy created the installation.
                # This only probes discovered executables; it never modifies them.
                if DISTRO in [name.strip() for name in names]:
                    progress('Looking for installed '+engine+' environments in '+DISTRO+'…')
                    suffix = 'mpb' if engine == 'mpb' else 'python'
                    script = 'for p in /opt/ods-solvers/*/bin/'+suffix+'; do if [ -x "$p" ]; then printf "%s\\n" "$p"; fi; done'
                    try:
                        found = _run([wsl_executable(), '--distribution', DISTRO, '--exec', '/bin/sh', '-c', script], cancel=cancel, timeout=15)
                        yield from (dict(mode='wsl', distro=DISTRO, executable=path, timeout_s=86400.)
                            for path in found.splitlines() if path.startswith('/opt/ods-solvers/') and path.endswith('/bin/'+suffix))
                    except (OSError, RuntimeError, TimeoutError):
                        pass
            elif engine == 'mpb' and shutil.which('mpb'):
                yield dict(mode='local', executable=shutil.which('mpb'), timeout_s=86400.)
        elif not getattr(sys, 'frozen', False):
            yield dict(mode='local', executable=sys.executable, module_paths=[], library_paths=[], timeout_s=86400.)
    seen = set()
    for runtime in candidates():
        _check_cancel(cancel)
        if not isinstance(runtime, dict) or not runtime.get('executable'):
            continue
        if getattr(sys, 'frozen', False) and os.path.normcase(runtime['executable']) == os.path.normcase(sys.executable):
            continue
        identity = dict(mode='local',distro='Ubuntu',timeout_s=86400.,module_paths=[],library_paths=[])
        identity.update(runtime)
        if identity['mode']=='local':
            identity['distro']=''
            identity['executable']=os.path.normcase(identity['executable'])
        try:identity['timeout_s']=float(identity['timeout_s'])
        except (ValueError,TypeError):pass
        signature = json.dumps(identity, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        progress('Checking '+runtime['executable']+(' in '+runtime.get('distro', '') if runtime.get('mode') == 'wsl' else '')+'…')
        try:
            return probe(engine, runtime, cancel=cancel)
        except (OSError, RuntimeError, ValueError, TimeoutError):
            pass
    return {}


def _uv(root, cancel, progress):
    key = 'win32' if sys.platform == 'win32' else 'linux' if sys.platform.startswith('linux') else ''
    if key not in UV_ASSETS or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('Automatic Python setup supports Windows/Linux x64. Configure an existing Python 3.12 installation on this platform.')
    from meep_bootstrap import download
    cache = _owned_path(root, root/'downloads'); cache.mkdir(exist_ok=True)
    progress('Downloading the verified uv '+UV_VERSION+' environment manager…')
    archive = download(UV_ASSETS[key], cache/('uv-'+UV_VERSION+'-'+key+'.whl'), cancel)
    binary = _owned_path(root, root/('uv-'+UV_VERSION+('.exe' if key == 'win32' else '')))
    with zipfile.ZipFile(archive) as package:
        matches = [item for item in package.infolist() if item.filename.endswith('/scripts/'+('uv.exe' if key == 'win32' else 'uv'))]
        if len(matches) != 1 or matches[0].file_size > 150*1024**2:
            raise ValueError('Invalid verified uv archive layout.')
        binary.write_bytes(package.read(matches[0]))
    if key != 'win32':
        binary.chmod(0o700)
    return binary


def _python_install(engine, root, cancel, progress):
    for name in ('python', 'cache', 'tmp'):
        _owned_path(root, root/name).mkdir(exist_ok=True)
    uv = _uv(root, cancel, progress)
    environments = _owned_path(root, root/'environments'); environments.mkdir(exist_ok=True)
    # Fresh generations mean repair never alters the previously working runtime.
    prefix = _owned_path(root, environments/(engine+'-'+uuid.uuid4().hex))
    environment = _environment(root)
    progress('Creating an isolated Python 3.12 environment for '+engine+'…')
    _run([str(uv), '--no-config', 'venv', '--python', '3.12', '--managed-python', str(prefix)], cancel=cancel, progress=progress, env=environment)
    executable = prefix/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    progress('Installing '+engine+' and compatible numerical dependencies…')
    _run([str(uv), '--no-config', 'pip', 'install', '--python', str(executable), '--index-url', 'https://pypi.org/simple',
        *BASE_PACKAGES, *PACKAGES[engine]], cancel=cancel, progress=progress, env=environment)
    return dict(mode='local', executable=str(executable), module_paths=[], library_paths=[], timeout_s=86400.)


def _wsl_install(engine, root, cancel, progress):
    """Use only the dedicated ODS distribution, never apt-modify user distros."""
    if os.name != 'nt':
        raise RuntimeError('For '+engine+' on Linux/macOS, install the solver with your system package manager or Conda, then configure that runtime.')
    import meep_managed
    status = meep_managed.prerequisites(cancel)
    if not status['ready']:
        raise RuntimeError(status['message']+' Use Set up Windows support below, then retry.')
    from meep_bootstrap import download, run_owned
    distro_root = _owned_path(root, root/'research-wsl'); distro_root.mkdir(exist_ok=True)
    receipt = _owned_path(root, distro_root/'installation.json')
    location = _owned_path(root, distro_root/'distro')
    registered = _registration(DISTRO)
    if DISTRO in status.get('distributions', []) or registered:
        try:
            saved = json.loads(receipt.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
        if not registered or saved.get('location') != str(location.resolve()) or os.path.normcase(registered) != os.path.normcase(str(location.resolve())):
            raise RuntimeError('The research WSL name belongs to an unrecognized installation. Existing files were preserved.')
    else:
        if location.exists() and any(location.iterdir()):
            raise RuntimeError('Unregistered WSL files were preserved. Check Windows WSL support before retrying.')
        progress('Downloading Ubuntu for a separate research runtime. This requires several GB of free disk space…')
        if shutil.disk_usage(root).free < 8*1024**3:
            raise RuntimeError('Automatic research solver setup needs at least 8 GiB of free disk space.')
        base = 'https://cloud-images.ubuntu.com/wsl/releases/24.04/current/'
        filename = 'ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz'
        with urlopen(base+'SHA256SUMS', timeout=30) as stream:
            sums = stream.read(1024*1024).decode('utf-8')
        match = next((re.fullmatch(r'([0-9a-f]{64})\s+\*?'+re.escape(filename), line.strip()) for line in sums.splitlines() if filename in line), None)
        if match is None:
            raise RuntimeError('Ubuntu did not publish a SHA256 checksum for its WSL image.')
        with urlopen(base+filename, timeout=30) as stream:
            size = int(stream.headers.get('Content-Length', '0'))
        if not 0 < size <= 2*1024**3:
            raise RuntimeError('Ubuntu returned an invalid WSL image size.')
        archive = download(dict(url=base+filename, bytes=size, sha256=match[1]), distro_root/'ubuntu-rootfs.tar.gz', cancel)
        location.mkdir(exist_ok=True)
        _write_json(receipt, dict(schema=1, location=str(location.resolve()), sha256=match[1], state='importing'))
        progress('Importing the separate research WSL runtime. Import completes safely before cancellation takes effect…')
        code, output, error = meep_managed._wsl(['--import', DISTRO, str(location.resolve()), str(archive.resolve()), '--version', '2'], timeout=900)
        if code:
            raise RuntimeError('WSL import failed: '+(error or output))
    _check_cancel(cancel)
    progress('Installing '+engine+' into an isolated conda-forge environment…')
    archive = download(MICROMAMBA, distro_root/'micromamba.tar.bz2', cancel)
    binary = _owned_path(root, distro_root/'micromamba')
    with tarfile.open(archive, 'r:bz2') as package:
        item = package.getmember('bin/micromamba')
        if not item.isfile() or item.size > 100*1024**2:
            raise ValueError('Invalid micromamba archive.')
        with package.extractfile(item) as stream:
            binary.write_bytes(stream.read())
    from meep_runtime import linux_path
    config = dict(mode='wsl', distro=DISTRO, managed=True)
    # Constant application script, positional path data, no user shell text.
    script = 'set -eu; mkdir -p /opt/ods-solvers/bin; cp "$1" /opt/ods-solvers/bin/micromamba; chmod 700 /opt/ods-solvers/bin/micromamba; prefix="$2"; shift 2; /opt/ods-solvers/bin/micromamba create --yes --root-prefix /opt/ods-solvers/cache --prefix "$prefix" --override-channels --channel conda-forge --strict-channel-priority "$@"'
    prefix = '/opt/ods-solvers/'+engine+'-'+uuid.uuid4().hex
    run_owned(DISTRO, ['/bin/sh', '-c', script, 'ods-solver', linux_path(binary, config), prefix, *WSL_PACKAGES[engine]], cancel, progress)
    return dict(mode='wsl', distro=DISTRO, executable=prefix+('/bin/mpb' if engine == 'mpb' else '/bin/python'), timeout_s=86400.)


def _registration(name):
    if os.name != 'nt':
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Lxss') as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                with winreg.OpenKey(key, winreg.EnumKey(key, index)) as item:
                    if winreg.QueryValueEx(item, 'DistributionName')[0] == name:
                        path = winreg.QueryValueEx(item, 'BasePath')[0]
                        return str(Path(path.removeprefix('\\\\?\\')).resolve())
    except FileNotFoundError:
        pass
    return None


def setup(engine, configured=None, *, root=None, cancel=None, progress=lambda text: None, install=True):
    if engine not in {*PACKAGES, *WSL_PACKAGES}:
        raise ValueError('This calculation uses the included engine and needs no optional setup.')
    root = Path(root) if root is not None else root_directory()
    with _lock_guard:
        lock = _locks.setdefault(str(root.absolute()), threading.Lock())
    if not lock.acquire(blocking=False):
        raise RuntimeError('A solver installation is already running. Wait for it to finish.')
    try:
        found = discover(engine, configured, root=root, cancel=cancel, progress=progress)
        if found:
            return found
        if not install:
            raise RuntimeError('No working '+engine+' installation was found. Click Set up automatically to create one.')
        _owned_path(root, root).mkdir(parents=True, exist_ok=True)
        runtime = _wsl_install(engine, root, cancel, progress) if engine in WSL_PACKAGES else _python_install(engine, root, cancel, progress)
        progress('Verifying the installed '+engine+' API…')
        runtime = probe(engine, runtime, cancel=cancel)
        _write_json(_owned_path(root, root/(engine+'.json')), dict(schema=1, engine=engine, root=str(root.resolve()),
            runtime=runtime, installed_at=time.time(), packages=BASE_PACKAGES+PACKAGES[engine] if engine in PACKAGES else WSL_PACKAGES[engine]))
        progress('Solver ready. Its installation has been selected for this study.')
        return runtime
    finally:
        lock.release()
