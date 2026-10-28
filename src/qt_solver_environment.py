"""Common nonblocking automatic setup controls for optional solver panels."""
from __future__ import annotations

import os
import threading

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QGridLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


_tasks = set()  # Keep cancelled installers alive until their child processes exit.


def setup_in_progress():
    return any(task.isRunning() for task in _tasks)


def cancel_all_setups():
    """The window may defer closing until setup_in_progress() becomes false."""
    for task in tuple(_tasks):
        task.cancelled.set()


class _SetupTask(QThread):
    progress = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, engine, configured, install):
        super().__init__()
        self.engine, self.configured, self.install = engine, configured, install
        self.cancelled = threading.Event()

    def run(self):
        from solver_environment import setup
        try:
            value = setup(self.engine, self.configured, install=self.install,
                cancel=self.cancelled, progress=self.progress.emit)
            self.completed.emit(value)
        except Exception as exc:
            self.failed.emit(str(exc))


class SolverEnvironmentSetup(QWidget):
    runtimeReady = pyqtSignal(object)
    launcherChanged = pyqtSignal()

    def __init__(self, get_runtime, parent=None):
        super().__init__(parent)
        self.get_runtime = get_runtime
        self._task = None
        self._revision = 0
        self._started_revision = -1
        self._result = None
        self._error = ''
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.description = QLabel('Find an installed solver, or create its own environment automatically. Setup downloads dependencies only after you click Set up automatically.')
        self.description.setWordWrap(True); self.description.setObjectName('setupMuted')
        layout.addWidget(self.description)
        row = QGridLayout()
        self.find_button = QPushButton('Find installed solver')
        self.install_button = QPushButton('Set up automatically')
        self.install_button.setProperty('primary', True)
        self.cancel_button = QPushButton('Cancel setup'); self.cancel_button.hide()
        self.windows_button = QPushButton('Set up Windows support'); self.windows_button.hide()
        for index, button in enumerate((self.find_button, self.install_button, self.cancel_button, self.windows_button)):
            button.setMinimumHeight(32); row.addWidget(button, index//2, index%2)
        layout.addLayout(row)
        self.launcher_button = QPushButton('Choose Windows WSL launcher…', self)
        self.launcher_button.setToolTip('Remember an existing WSL executable for all WSL solvers. This does not change your Linux installations. Check or find the solver afterward.')
        self.launcher_button.setVisible(os.name == 'nt')
        self.launcher_button.clicked.connect(self.choose_wsl_launcher)
        layout.addWidget(self.launcher_button)
        self.status = QLabel(''); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(130)
        self.log.document().setMaximumBlockCount(160)
        self.log.setAccessibleName('Automatic solver setup progress and errors')
        self.log.hide(); layout.addWidget(self.log)
        self.find_button.clicked.connect(lambda: self.start(False))
        self.install_button.clicked.connect(lambda: self.start(True))
        self.cancel_button.clicked.connect(self.cancel)
        self.windows_button.clicked.connect(self.setup_windows)
        # A destroyed editor cancels its worker; the application-owned task set
        # keeps QThread alive until its process exits, preventing Qt destruction.
        self.destroyed.connect(self._cancel_on_destroy)

    def _cancel_on_destroy(self):
        if self._task is not None:
            self._task.cancelled.set()

    def invalidate(self):
        self._revision += 1
        if self._task is not None:
            self.cancel()

    def cancel(self):
        if self._task is not None:
            self._task.cancelled.set()
            self.cancel_button.setEnabled(False)
            self.status.setText('Cancelling setup; waiting for the active setup step to stop safely…')

    def choose_wsl_launcher(self):
        from meep_runtime import saved_wsl_launcher, save_wsl_launcher
        filename, _ = QFileDialog.getOpenFileName(self, 'Choose installed Windows WSL launcher',
            saved_wsl_launcher(), 'Windows executable (*.exe)')
        if not filename:
            return
        try:
            saved = save_wsl_launcher(filename)
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc)); return
        self.invalidate()
        self.launcherChanged.emit()
        self.status.setText('Windows WSL launcher saved. Find or check your solver again.')
        self.status.setToolTip(saved)

    def setup_windows(self):
        from meep_managed import setup_windows_support
        try:
            self.status.setText(setup_windows_support())
        except Exception as exc:
            self.status.setText(str(exc))

    def start(self, install):
        if self._task is not None:
            return
        try:
            engine, runtime = self.get_runtime()
            if not engine:
                self.status.setText('This calculation uses the program’s included engine; no separate environment is needed.')
                return
        except (TypeError, ValueError, KeyError) as exc:
            self.status.setText(str(exc)); return
        self._started_revision = self._revision
        self._result, self._error = None, ''
        self.find_button.setEnabled(False); self.install_button.setEnabled(False)
        self.cancel_button.show(); self.cancel_button.setEnabled(True)
        self.windows_button.setVisible(engine == 'mpb' and os.name == 'nt')
        self.status.setText('Preparing '+engine+'…' if install else 'Looking for '+engine+'…')
        self.log.clear(); self.log.show()
        task = self._task = _SetupTask(engine, runtime, install)
        self.destroyed.connect(task.cancelled.set)
        _tasks.add(task)
        task.progress.connect(self.log.appendPlainText)
        task.completed.connect(self._completed)
        task.failed.connect(self._failed)
        task.finished.connect(self._finished)
        task.finished.connect(lambda: (_tasks.discard(task), task.deleteLater()))
        task.start()

    def _completed(self, result):
        self._result = result

    def _failed(self, message):
        self._error = message

    def _finished(self):
        cancelled = self._task.cancelled.is_set()
        self._task = None
        self.find_button.setEnabled(True); self.install_button.setEnabled(True)
        self.cancel_button.hide()
        if self._started_revision != self._revision:
            self.status.setText('The selected solver changed. Run setup for the current solver.'); return
        if self._result is not None and not cancelled:
            self.runtimeReady.emit(self._result)
            self.status.setText('Solver is ready and selected. You can run the study.')
        else:
            message = self._error or 'Setup cancelled. Existing installations were preserved; you can retry.'
            self.status.setText(message)
            self.log.appendPlainText(message)
