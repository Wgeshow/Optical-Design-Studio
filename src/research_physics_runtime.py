"""Isolated Python execution for explicitly selected optional physics engines."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time


def validate_runtime(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value)-{'mode', 'distro', 'executable', 'timeout_s', 'module_paths', 'library_paths'}:
        raise ValueError('Python physics runtime supports mode, distro, executable, timeout_s, module_paths and library_paths')
    if getattr(sys, 'frozen', False) and not value.get('executable'):
        raise ValueError('Select an explicit Python interpreter for this optional engine; the packaged application is not a Python interpreter')
    result = dict(mode='local', distro='Ubuntu', executable=sys.executable, timeout_s=86400., module_paths=[], library_paths=[])
    result.update(value)
    if result['mode'] not in ('local', 'wsl'):
        raise ValueError('Python physics runtime mode must be local or wsl')
    for key in ('distro', 'executable'):
        if not isinstance(result[key], str) or not result[key].strip() or result[key].startswith('-') or any(c in result[key] for c in '\r\n\0'):
            raise ValueError('Invalid Python physics runtime '+key)
        result[key] = result[key].strip()
    if not isinstance(result['module_paths'], list) or any(not isinstance(p, str) or not p or any(c in p for c in '\r\n\0') for p in result['module_paths']):
        raise ValueError('module_paths must contain explicit optional-engine installation paths')
    result['module_paths'] = list(result['module_paths'])
    if not isinstance(result['library_paths'], list) or any(not isinstance(p,str) or not p or any(c in p for c in '\r\n\0') for p in result['library_paths']):
        raise ValueError('library_paths must contain explicit optional-engine shared-library directories')
    result['library_paths'] = list(result['library_paths'])
    if isinstance(result['timeout_s'], bool):
        raise ValueError('Physics runtime timeout must be positive and finite')
    try:
        result['timeout_s'] = float(result['timeout_s'])
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Physics runtime timeout must be positive and finite') from None
    if not math.isfinite(result['timeout_s']) or result['timeout_s'] <= 0:
        raise ValueError('Physics runtime timeout must be positive and finite')
    if result['mode'] == 'wsl' and not result['executable'].startswith('/'):
        raise ValueError('WSL Python executable must be an explicit absolute Linux path')
    if result['mode'] == 'wsl' and any(not p.startswith('/') or ':' in p for p in result['library_paths']):
        raise ValueError('WSL shared-library directories must be absolute Linux paths without colons')
    return result


def run_worker(prepared, directory, emit=lambda event: None, cancelled=lambda: False, *, worker_name='research_physics_worker.py'):
    """Run the fixed application worker; never evaluate user-supplied code."""
    from meep_runtime import ManagedProcess, linux_path, wsl_executable
    if worker_name not in {'research_physics_worker.py', 'pcsel_physics_worker.py', 'pcsel_transport_worker.py'}:
        raise ValueError('Unknown fixed application physics worker')
    if cancelled():
        raise InterruptedError('Physics simulation cancelled')
    runtime = validate_runtime(prepared.get('runtime'))
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    worker = directory/worker_name
    source = Path(__file__).with_name(worker_name)
    if not source.is_file():
        source = Path(getattr(sys, '_MEIPASS', ''))/worker_name
    if not source.is_file():
        raise RuntimeError('The installed application is missing its physics worker; repair the installation')
    shutil.copyfile(source, worker)
    if worker_name == 'pcsel_transport_worker.py':
        # Fixed application dependencies only, never paths from the job.
        for name in ('pcsel_conformal_mesh.py','pcsel_conformal_solver.py','electrical_fermi_transport.py'):
            dependency=Path(__file__).with_name(name)
            if not dependency.is_file():dependency=Path(getattr(sys,'_MEIPASS',''))/'source'/name
            if not dependency.is_file():raise RuntimeError('The installed application is missing '+name)
            shutil.copyfile(dependency,directory/name)
    inputs = directory/'engine_inputs.json'
    inputs.write_text(json.dumps(prepared, indent=2, allow_nan=False), encoding='utf-8')
    command = [runtime['executable'], linux_path(worker, runtime), linux_path(inputs, runtime)]
    lines = []
    def accept(line, log):
        log.write(line)
        log.flush()
        lines.append(line)
        if line.startswith('ODS_EVENT '):
            try:
                event = json.loads(line[len('ODS_EVENT '):])
                if isinstance(event, dict):
                    emit(event)
            except (ValueError, TypeError):
                pass
    with (directory/'engine.log').open('w', encoding='utf-8') as log:
        if runtime['mode'] == 'wsl':
            if runtime['library_paths']:
                command=['env','LD_LIBRARY_PATH='+':'.join(runtime['library_paths'])]+command
            command = [wsl_executable(), '--distribution', runtime['distro'], '--exec']+command
            class Cancellation:
                def is_set(self):
                    return bool(cancelled())
            try:
                process = ManagedProcess(runtime, command)
            except OSError as exc:
                raise RuntimeError('Optional physics runtime could not start: '+str(exc)) from exc
            try:
                for line in process.stream(Cancellation(), timeout=runtime['timeout_s']):
                    accept(line, log)
            finally:
                if process.process.poll() is None:
                    process.terminate(force=True)
            returncode = process.process.returncode
        else:
            environment = os.environ.copy()
            environment.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', MPLBACKEND='Agg')
            if runtime['library_paths']:
                environment['PATH']=os.pathsep.join(runtime['library_paths']+[environment.get('PATH','')])
            options = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else dict(start_new_session=True)
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', bufsize=1, env=environment, **options)
            except OSError as exc:
                raise RuntimeError('Optional physics runtime could not start: '+str(exc)) from exc
            pending = queue.Queue()
            def read_lines():
                try:
                    for line in process.stdout:
                        pending.put(line)
                finally:
                    pending.put(None)
            threading.Thread(target=read_lines, daemon=True).start()
            started = time.monotonic()
            try:
                while True:
                    if cancelled():
                        raise InterruptedError('Physics simulation cancelled')
                    if time.monotonic()-started > runtime['timeout_s']:
                        raise TimeoutError('The physics simulation exceeded its configured time limit')
                    try:
                        line = pending.get(timeout=.1)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    accept(line, log)
                returncode = process.wait(timeout=10)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
    if cancelled():
        raise InterruptedError('Physics simulation cancelled')
    if returncode:
        raise RuntimeError('The selected optional engine failed; inspect engine.log. '+''.join(lines[-12:]).strip())
    path = directory/'engine_result.json'
    if not path.is_file():
        raise RuntimeError('Optional engine exited without a result manifest')
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, dict) or result.get('status') not in ('complete', 'partial', 'unconverged', 'validity_limit'):
        raise RuntimeError('Optional engine returned an invalid completion status')
    return result
