"""Nonblocking readiness check for the explicitly selected band solver."""
from __future__ import annotations

import json
import os

from PyQt6.QtCore import QProcess, QProcessEnvironment, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


def probe_command(settings):
    """Return an argument-vector probe; never interpret configured text as a shell."""
    solver = settings.get('solver')
    runtime = settings.get('runtime', {})
    if solver not in ('mpb', 'legume'):
        raise ValueError('Choose MPB or Legume before checking the solver.')
    if solver == 'legume':
        from research_physics_runtime import validate_runtime
        runtime = validate_runtime(runtime)
    mode = runtime.get('mode', 'wsl' if os.name == 'nt' else 'local')
    if mode not in ('local', 'wsl'):
        raise ValueError('Choose where the solver is installed.')
    executable = runtime.get('executable', '')
    distro = runtime.get('distro', 'Ubuntu')
    for name, value in [('executable', executable), ('WSL distribution', distro)]:
        if not isinstance(value, str) or not value.strip() or value.startswith('-') or any(c in value for c in '\r\n\0'):
            raise ValueError('Enter a valid '+name+' in Solver setup.')
    if solver == 'mpb' and mode == 'local' and os.name == 'nt':
        raise ValueError('Select WSL for MPB on Windows.')
    if solver == 'mpb':
        command = [executable.strip(), '--version']
    else:
        # Paths are serialized as data. The executed code is fixed application code.
        script = ('import sys,json; sys.path[:0]=json.loads('+repr(json.dumps(runtime.get('module_paths', [])))+'); '
                  'import legume; from legume import PhotCryst, PlaneWaveExp; '
                  'print("ODS_LEGUME_READY "+str(getattr(legume,"__version__","version unavailable")))')
        command = [executable.strip(), '-c', script]
    if mode == 'wsl':
        if runtime.get('library_paths'):
            command = ['env', 'LD_LIBRARY_PATH='+':'.join(runtime['library_paths'])]+command
        command = ['wsl.exe', '--distribution', distro.strip(), '--exec']+command
    return command, runtime


class PhotonicRuntimeCheck(QWidget):
    """Readiness belongs to the checked configuration, not to the saved project."""

    def __init__(self, get_settings, parent=None):
        super().__init__(parent)
        self.get_settings = get_settings
        self._revision = 0
        self._checked_revision = -1
        self._running = False
        self._output = ''
        self._output_bytes = b''
        self._solver = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.status = QLabel('Solver not checked.')
        self.status.setToolTip('Check the selected installation before your first run. This does not change your crystal or start a band calculation.')
        self.status.setWordWrap(True)
        self.status.setObjectName('setupMuted')
        row.addWidget(self.status, 1)
        self.check_button = QPushButton('Check solver')
        self.check_button.setMinimumHeight(32)
        self.check_button.clicked.connect(self.check)
        row.addWidget(self.check_button)
        layout.addLayout(row)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self._timeout)

    def invalidate(self, *args):
        self._revision += 1
        if self._running:
            self._finish('Solver setup changed. Check the updated installation.')
            self.process.kill()
        else:
            self.status.setText('Solver not checked for these settings.')

    def check(self):
        if self._running or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        try:
            settings = self.get_settings()
            command, runtime = probe_command(settings)
        except (TypeError, ValueError, KeyError) as exc:
            self.status.setText(str(exc))
            return
        environment = QProcessEnvironment.systemEnvironment()
        for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
            environment.insert(key, '1')
        if runtime.get('mode') == 'local' and runtime.get('library_paths'):
            environment.insert('PATH', os.pathsep.join(runtime['library_paths']+[environment.value('PATH')]))
        self.process.setProcessEnvironment(environment)
        self._solver = settings['solver']
        self._checked_revision = self._revision
        self._output = ''
        self._output_bytes = b''
        self._running = True
        self.check_button.setEnabled(False)
        self.status.setText('Checking '+self._solver.upper()+'…')
        self.timer.start()
        self.process.start(command[0], command[1:])

    def _read(self):
        chunk = bytes(self.process.readAllStandardOutput())
        if not chunk:
            return
        self._output_bytes = (self._output_bytes+chunk)[-16384:]
        # WSL launcher diagnostics use UTF-16; the Linux child uses UTF-8.
        encoding = 'utf-16-le' if b'\x00' in self._output_bytes else 'utf-8'
        self._output = self._output_bytes.decode(encoding, 'replace')[-8192:]

    def _finish(self, text):
        self.timer.stop()
        self._running = False
        # A cancelled QProcess can still deliver finished after kill(). Never
        # let that process be reused for a newer configuration until it exits.
        self.check_button.setEnabled(self.process.state() == QProcess.ProcessState.NotRunning)
        self.status.setText(text)

    def _finished(self, exit_code, exit_status):
        self._read()
        if not self._running or self._checked_revision != self._revision:
            self.check_button.setEnabled(True)
            return
        marker = 'ODS_LEGUME_READY' if self._solver == 'legume' else 'mpb'
        valid = marker.lower() in self._output.lower()
        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit and valid:
            self._finish(self._solver.upper()+' is available.')
        else:
            self._finish('Could not verify '+self._solver.upper()+'. Open Solver setup and check the installation and executable.')
        self.status.setToolTip(self._output.strip() or self.process.errorString())

    def _error(self, error):
        if self._running and error == QProcess.ProcessError.FailedToStart:
            self._finish('Solver could not start. Open Solver setup and check its location.')
            self.status.setToolTip(self.process.errorString())

    def _timeout(self):
        if self._running:
            self._finish('Solver check timed out. Open Solver setup and check that the selected installation starts.')
            self.process.kill()
