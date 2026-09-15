"""User-initiated GitHub add-on downloads. Constructing this page is offline."""
from pathlib import Path
import tempfile
import threading

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
                             QPushButton, QProgressBar)

import addon_runtime as runtime
from qt_common import note
from update_client import UpdateCancelled


class AddonWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int)
    stage = pyqtSignal(str)

    def __init__(self, identifier, release=None, parent=None, *, install=True):
        super().__init__(parent)
        self.identifier, self.release = identifier, release
        self.install = install
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            client = runtime.AddonClient()
            self.stage.emit('Checking for a compatible package…')
            release = self.release or client.check_addon(self.identifier, self.cancel_event)
            if release is None or not self.install:
                self.completed.emit(release)
                return
            self.stage.emit('Downloading and verifying the add-on…')
            with tempfile.TemporaryDirectory(prefix='optical-addon-') as folder:
                package = client.download(release, folder,
                    lambda done, total: self.progress.emit(int(100 * done / total)), self.cancel_event)
                self.stage.emit('Installing the verified add-on; preparing application restart…')
                location = runtime.install_archive(self.identifier, package, release, cancel=self.cancel_event)
            self.completed.emit(location)
        except UpdateCancelled:
            self.failed.emit('Cancelled. No new add-on was activated.')
        except Exception as exc:
            self.failed.emit(str(exc))


class AddonsPage(QWidget):
    idle = pyqtSignal()
    changed = pyqtSignal()
    runtime_changed = pyqtSignal(dict)
    restart_requested = pyqtSignal()

    def __init__(self, parent=None, *, store=None, preflight=None):
        super().__init__(parent)
        self.store, self.preflight = store, preflight
        self._reservation = None
        self._restart_waiting = False
        self._closing = False
        self.worker = None
        self.cards = {}
        self.releases = {}
        self.pending_restart = set(runtime.pending_addons())
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        title = QLabel('Add-ons')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(note('Install optional components when you need them. Downloads start only when you click Install.'))
        self.card_row = QHBoxLayout()
        layout.addLayout(self.card_row)
        for identifier, (name, description) in runtime.ADDONS.items():
            card = QGroupBox(name)
            body = QVBoxLayout(card)
            body.addWidget(note(description))
            status = QLabel()
            status.setWordWrap(True)
            body.addWidget(status)
            row = QHBoxLayout()
            row.addStretch()
            action = QPushButton('Install')
            action.clicked.connect(lambda checked=False, key=identifier: self.action(key))
            row.addWidget(action)
            body.addLayout(row)
            self.card_row.addWidget(card, 1)
            self.cards[identifier] = (status, action)
        self.meep_container = QGroupBox('MEEP FDTD engine')
        self.meep_layout = QVBoxLayout(self.meep_container)
        self.meep_layout.addWidget(note('Install a preconfigured MEEP environment in its own WSL distribution. Existing Linux distributions are left unchanged.'))
        try:
            from qt_fdtd import MeepRuntimeSettings
            self.meep_settings = MeepRuntimeSettings(before_operation=self._reserve_runtime,
                after_operation=self._release_operation)
            self.meep_layout.addWidget(self.meep_settings)
            self.meep_settings.idle.connect(self._runtime_idle)
            self.meep_settings.runtime_changed.connect(self.runtime_changed)
            self.meep_settings.runtime_changed.connect(lambda result: self.changed.emit())
        except ImportError:
            self.meep_layout.addWidget(note('MEEP runtime setup is being integrated in this preview.'))
        layout.addWidget(self.meep_container)
        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.cancel_button)
        layout.addLayout(progress_row)
        self.status = note('Click Install to download a matching GitHub pack and install it automatically. Native components restart the app after installation; your session is saved first.')
        layout.addWidget(self.status)
        layout.addStretch()
        if self.store is not None:
            self.store.busy_changed.connect(self._global_busy)
            self._global_busy(self.store.busy)
        else:
            self.refresh()

    def _reserve_operation(self, cancel):
        if self.is_busy or self._reservation is not None:
            raise RuntimeError('Wait for the current add-on operation to finish.')
        if self.preflight is not None:
            self.preflight()
        if self.store is not None:
            if self.store.busy or self.store._worker is not None:
                raise RuntimeError('Wait for the active calculation, library operation or update to finish.')
            self.store._autosave()
            # ProjectStore.cancel delegates to this explicit operation owner.
            # The lock remains held across metadata, download and staging.
            from types import SimpleNamespace
            self._reservation = SimpleNamespace(cancel=cancel, operation='add-on installation')
            self.store._worker = self._reservation
            self.store._set_busy(True)

    def _reserve_runtime(self):
        self._reserve_operation(self.meep_settings.shutdown)

    def _release_operation(self):
        owner, self._reservation = self._reservation, None
        if self.store is not None and owner is not None and self.store._worker is owner:
            self.store._worker = None
            self.store._set_busy(False)

    def _global_busy(self, busy):
        settings = getattr(self, 'meep_settings', None)
        if settings is not None:
            settings.set_external_busy(busy)
        self.refresh()
        if not busy and self._restart_waiting:
            QTimer.singleShot(0, self._request_restart)

    @property
    def is_busy(self):
        settings = getattr(self, 'meep_settings', None)
        return self.worker is not None or (settings is not None and settings.is_busy())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        from PyQt6.QtWidgets import QBoxLayout
        self.card_row.setDirection(QBoxLayout.Direction.LeftToRight if self.width() >= 760 else QBoxLayout.Direction.TopToBottom)

    def _runtime_idle(self):
        self.refresh()
        if not self.is_busy:
            self.idle.emit()

    def _request_restart(self):
        if self._restart_waiting and not self._closing and not self.is_busy and not (self.store and self.store.busy):
            self._restart_waiting = False
            self.restart_requested.emit()

    def refresh(self):
        for identifier, (label, button) in self.cards.items():
            if identifier in self.pending_restart:
                label.setText('Installed · Startup verification pending')
                button.setText('Restart required')
                enabled = False
            elif runtime.bundled(identifier):
                label.setText('Included in this full installation · No download needed')
                button.setText('Included')
                enabled = False
            elif runtime.available(identifier):
                label.setText('Installed · Ready')
                button.setText('Installed')
                enabled = False
            elif identifier in self.releases:
                label.setText(f'Available · Download size: {self.releases[identifier].asset_size / 1024**2:.1f} MiB')
                button.setText('Install')
                enabled = True
            else:
                label.setText('Not installed · Downloads from the official GitHub release')
                button.setText('Install')
                enabled = True
            button.setEnabled(enabled and not self.is_busy and not (self.store and self.store.busy))

    def action(self, identifier):
        if self.is_busy:
            return
        release = self.releases.get(identifier)
        try:
            self._reserve_operation(self.cancel)
            self.worker = AddonWorker(identifier, release, self, install=True)
            self.worker.completed.connect(lambda result: self.completed(identifier, result))
            self.worker.failed.connect(self.status.setText)
            self.worker.progress.connect(self._progress)
            self.worker.stage.connect(self.status.setText)
            self.worker.finished.connect(self.finished)
            self.status.setText('Preparing '+runtime.ADDONS[identifier][0]+'…')
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            self.cancel_button.show()
            self.refresh()
            self.worker.start()
        except Exception as exc:
            if self.worker is not None and not self.worker.isRunning():
                self.worker.deleteLater()
                self.worker = None
            self._release_operation()
            self.progress_bar.hide()
            self.cancel_button.hide()
            self.status.setText(str(exc))
            self.refresh()

    def _progress(self, value):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)

    def completed(self, identifier, result):
        if isinstance(result, Path):
            self.pending_restart.add(identifier)
            self._restart_waiting = True
            self.status.setText('Add-on installed. Restarting to verify and enable it…')
        elif result is None:
            self.status.setText('No compatible pack is published for this application version yet. Nothing was downloaded.')
        else:
            self.releases[identifier] = result
            self.status.setText('Compatible pack found. Click Install to download it.')

    def finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.progress_bar.hide()
        self.cancel_button.hide()
        self._release_operation()
        self.refresh()
        self.changed.emit()
        self.idle.emit()
        QTimer.singleShot(0, self._request_restart)

    def cancel(self):
        if self.worker is not None:
            self.worker.cancel()
            self.status.setText('Cancelling…')

    def shutdown(self):
        self._closing = True
        self.cancel()
        settings = getattr(self, 'meep_settings', None)
        if settings is not None:
            settings.shutdown()
        return not self.is_busy
