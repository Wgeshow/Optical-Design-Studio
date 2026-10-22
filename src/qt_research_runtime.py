"""Nonblocking checks for explicitly configured optional research engines.

Readiness belongs to one installation configuration. It is never stored as a
scientific validation result, and remembering a path does not verify it.
"""
from __future__ import annotations

import json
from meep_runtime import wsl_executable
import os
import sys

from PyQt6.QtCore import QProcess, QProcessEnvironment, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


_OPTIONAL = {'sesame_transport': ('sesame', 'Sesame'),
             'pcsel_transport': ('gmsh', 'Gmsh'),
             'sesame': ('sesame', 'Sesame'), 'legume': ('legume', 'Legume'), 'gmsh': ('gmsh', 'Gmsh')}
_NATIVE = {'thermal': 'Heat flow', 'high_field_optics': 'High-field optics',
           'advanced_transport': 'DEVSIM transport', 'pcsel_unitcell_transport': 'DEVSIM transport',
           'lumped_laser': 'Lumped laser'}
_PCSEL_MODELS = {'vertical', 'cwt', 'finite', 'beam', 'aperture', 'rcwa_poles', 'gme'}


def runtime_key(engine, model=None):
    """Stable installation key; PCSEL GME shares one Legume installation."""
    if engine == 'pcsel':
        if model not in _PCSEL_MODELS:
            raise ValueError('Select a PCSEL calculation before checking the solver.')
        return 'legume' if model == 'gme' else ''
    if engine in _OPTIONAL:
        return _OPTIONAL[engine][0]
    if engine in _NATIVE:
        return ''
    raise ValueError('Select a supported research calculation before checking the solver.')


def _explicit_runtime(value):
    from research_physics_runtime import validate_runtime
    if not isinstance(value, dict) or not isinstance(value.get('executable'), str) or not value['executable'].strip():
        raise ValueError('Choose the Python executable in Solver setup, then check the solver.')
    runtime = validate_runtime(value)
    if runtime['mode'] == 'local' and getattr(sys, 'frozen', False):
        if os.path.normcase(os.path.abspath(runtime['executable'])) == os.path.normcase(os.path.abspath(sys.executable)):
            raise ValueError('Choose a Python installation in Solver setup. The simulation program is not a Python interpreter.')
    return runtime


def remember_runtime(engine, runtime, model=None):
    """Remember explicit installation inputs only; the caller opts in to saving."""
    key = runtime_key(engine, model)
    if not key:
        raise ValueError('This calculation does not need an external Python installation.')
    value = _explicit_runtime(runtime)
    from qt_common import preferences
    settings = preferences()
    settings.setValue('research_runtime/'+key, json.dumps(value, allow_nan=False))
    settings.sync()
    return value


def load_saved_runtime(engine, model=None):
    """Return remembered inputs or an empty dict, never an installation claim."""
    key = runtime_key(engine, model)
    if not key:
        return {}
    from qt_common import preferences
    raw = preferences().value('research_runtime/'+key, '')
    try:
        return _explicit_runtime(json.loads(raw)) if raw else {}
    except (TypeError, ValueError):
        return {}


def _request(value):
    if not isinstance(value, dict):
        raise ValueError('Choose a research calculation before checking the solver.')
    settings = value.get('settings', value)
    if not isinstance(settings, dict):
        raise ValueError('Solver settings must be an object.')
    engine = value.get('engine', '')
    model = settings.get('model', value.get('model'))
    key = runtime_key(engine, model)
    label = {'sesame': 'Sesame', 'legume': 'Legume', 'gmsh': 'Gmsh'}.get(key)
    if label is None:
        label = ('S4 resonance' if model == 'rcwa_poles' else 'PCSEL') if engine == 'pcsel' else _NATIVE[engine]
    return engine, model, key, label, settings.get('runtime', value.get('runtime', {}))


_PROBE_PREFIX = '''import json, os, sys
runtime = json.loads(sys.argv[1])
sys.path[:0] = runtime.get('module_paths', [])
os.environ['MPLBACKEND'] = 'Agg'
import numpy
import scipy
'''
_PROBES = {
    'sesame': "import sesame\nfrom sesame import Builder, solve, IVcurve, Analyzer\nversion = getattr(sesame, '__version__', 'unreported')\n",
    'legume': "import legume\nfrom legume import PhotCryst, GuidedModeExp, Circle, Poly\nversion = getattr(legume, '__version__', 'unreported')\n",
    'gmsh': "import gmsh\ngmsh.initialize()\ntry:\n    gmsh.option.setNumber('General.Terminal', 0)\n    version = getattr(gmsh, '__version__', 'unreported')\nfinally:\n    gmsh.finalize()\n",
}


def probe_command(request):
    """Return (argument vector, validated runtime, label, marker); no shell."""
    _, _, key, label, value = _request(request)
    if not key:
        return [], {}, label, ''
    runtime = _explicit_runtime(value)
    marker = 'ODS_RESEARCH_READY_'+key.upper()
    script = _PROBE_PREFIX+_PROBES[key]+"print("+repr(marker+' ')+"+str(version), flush=True)\n"
    # User paths remain JSON data in their own argument, never Python source.
    command = [runtime['executable'], '-c', script, json.dumps(runtime, allow_nan=False)]
    if runtime['mode'] == 'wsl':
        if runtime['library_paths']:
            command = ['env', 'LD_LIBRARY_PATH='+':'.join(runtime['library_paths'])]+command
        command = [wsl_executable(), '--distribution', runtime['distro'], '--exec']+command
    return command, runtime, label, marker


class ResearchRuntimeCheck(QWidget):
    """Check without blocking editing. Call invalidate when runtime/model changes."""
    readinessChanged = pyqtSignal(bool)
    runtimeReady = pyqtSignal(object)

    def __init__(self, get_settings, parent=None):
        super().__init__(parent)
        self.get_settings = get_settings
        self.ready = False
        self._revision = 0
        self._checked_revision = -1
        self._running = False
        self._output_bytes = b''
        self._output = ''
        self._label = ''
        self._marker = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.status = QLabel('Solver not checked.')
        self.status.setObjectName('setupMuted')
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.check_button = QPushButton('Check solver')
        self.check_button.setMinimumHeight(32)
        self.check_button.clicked.connect(self.check)
        row.addWidget(self.check_button)
        self.details_button = QPushButton('Details')
        self.details_button.setCheckable(True)
        self.details_button.setMinimumHeight(32)
        row.addWidget(self.details_button)
        layout.addLayout(row)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        self.details.setAccessibleName('Solver installation check details')
        self.details.hide()
        self.details_button.toggled.connect(self.details.setVisible)
        layout.addWidget(self.details)
        from qt_solver_environment import SolverEnvironmentSetup
        self.setup = SolverEnvironmentSetup(self._setup_request, self)
        self.setup.runtimeReady.connect(self.runtimeReady)
        layout.addWidget(self.setup)
        self._refresh_setup_visibility()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self._timeout)

    def _setup_request(self):
        _, _, key, _, runtime = _request(self.get_settings())
        return key, runtime

    def _refresh_setup_visibility(self):
        try:
            key, _ = self._setup_request()
            self.setup.setVisible(bool(key))
        except (TypeError, ValueError, KeyError):
            pass

    def _set_ready(self, value):
        if self.ready != value:
            self.ready = value
            self.readinessChanged.emit(value)

    def invalidate(self, *args):
        self._revision += 1
        self.setup.invalidate()
        self._refresh_setup_visibility()
        self._set_ready(False)
        if self._running:
            self._finish('Solver setup changed. Check the updated installation.')
            self.process.kill()
        else:
            self.status.setText('Solver not checked for these settings.')

    def cancel(self):
        self.setup.cancel()
        if self._running:
            self._revision += 1
            self._set_ready(False)
            self._finish('Solver check cancelled.')
            self.process.kill()

    def check(self):
        if self._running or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self._set_ready(False)
        try:
            command, runtime, self._label, self._marker = probe_command(self.get_settings())
        except (TypeError, ValueError, KeyError) as exc:
            self.status.setText(str(exc))
            self.details.setPlainText(str(exc))
            return
        if not command:
            self.status.setText(self._label+' uses the program’s included engine.')
            self.details.setPlainText('No external Python setup is needed for this calculation. '
                'This identifies the program engine; Check inputs and an actual run verify device and solver readiness.')
            return
        environment = QProcessEnvironment.systemEnvironment()
        for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
            environment.insert(key, '1')
        environment.insert('MPLBACKEND', 'Agg')
        environment.insert('PYTHONNOUSERSITE', '1')
        if runtime['mode'] == 'local' and runtime.get('library_paths'):
            environment.insert('PATH', os.pathsep.join(runtime['library_paths']+[environment.value('PATH')]))
        self.process.setProcessEnvironment(environment)
        self._checked_revision = self._revision
        self._output_bytes = b''
        self._output = ''
        self._running = True
        self.check_button.setEnabled(False)
        self.details.setPlainText('Checking '+self._label+' in '+runtime['executable'])
        self.status.setText('Checking '+self._label+'…')
        self.timer.start()
        self.process.start(command[0], command[1:])

    def _read(self):
        chunk = bytes(self.process.readAllStandardOutput())
        if chunk:
            self._output_bytes = (self._output_bytes+chunk)[-16384:]
            encoding = 'utf-16-le' if b'\x00' in self._output_bytes else 'utf-8'
            self._output = self._output_bytes.decode(encoding, 'replace')[-8192:]

    def _finish(self, message):
        self.timer.stop()
        self._running = False
        self.check_button.setEnabled(self.process.state() == QProcess.ProcessState.NotRunning)
        self.status.setText(message)

    def _finished(self, exit_code, exit_status):
        self._read()
        if not self._running or self._checked_revision != self._revision:
            self.check_button.setEnabled(True)
            return
        valid = bool(self._marker) and any(line.startswith(self._marker+' ') for line in self._output.splitlines())
        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit and valid:
            self._set_ready(True)
            self._finish(self._label+' is available.')
        else:
            self._finish('Could not verify '+self._label+'. Open Solver setup and check the installation.')
        self.details.setPlainText(self._output.strip() or self.process.errorString())
        self.status.setToolTip(self.details.toPlainText())

    def _error(self, error):
        if self._running and error == QProcess.ProcessError.FailedToStart:
            self._finish('Solver could not start. Open Solver setup and check its location.')
            self.details.setPlainText(self.process.errorString())

    def _timeout(self):
        if self._running:
            self._finish('Solver check timed out. Check its installation in Solver setup.')
            self.details.setPlainText(self._output.strip() or 'The installation check did not finish within 15 seconds.')
            self.process.kill()
