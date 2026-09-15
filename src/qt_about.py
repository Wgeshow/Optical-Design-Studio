"""About and public software updates, independent of simulation workers."""
from datetime import datetime
from pathlib import Path
import threading
import sys

from PyQt6.QtCore import Qt, QPointF, QThread, QUrl, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QProgressBar, QPushButton, QVBoxLayout, QWidget, QMessageBox)

from app_version import installation_info
from desktop_runtime import resource_root, application_root
from update_install import stage_update, launch_update
from qt_common import COLORS, button, note, theme_manager
from update_client import GitHubUpdateClient, REPOSITORY_URL, UpdateCancelled, UpdateError


def label(text, name='', wrap=False):
    widget = QLabel(str(text))
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def plain_note(text):
    widget = note(str(text))
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def display_time(value):
    """Display a server timestamp locally; never fabricate an update/check date."""
    if not value:
        return 'Never'
    try:
        timestamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return timestamp.astimezone().strftime('%b %d, %Y at %I:%M %p %Z')
    except (TypeError, ValueError):
        return 'Not recorded'


class StatusMark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(46, 46)
        self.kind = 'not_checked'

    def paintEvent(self, event):
        c = COLORS[theme_manager().mode]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c['hover']))
        painter.drawEllipse(0, 0, 46, 46)
        painter.setPen(QPen(QColor(c['accent']), 2.3, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if self.kind in ('current', 'downloaded'):
            painter.drawLine(QPointF(14, 23), QPointF(20, 29))
            painter.drawLine(QPointF(20, 29), QPointF(33, 16))
        elif self.kind == 'available':
            painter.drawLine(QPointF(23, 31), QPointF(23, 15))
            painter.drawLine(QPointF(16, 22), QPointF(23, 15))
            painter.drawLine(QPointF(30, 22), QPointF(23, 15))
        else:
            painter.drawEllipse(14, 14, 18, 18)
            painter.drawLine(QPointF(23, 18), QPointF(23, 24))
            painter.drawLine(QPointF(23, 24), QPointF(27, 26))
        painter.end()


class UpdateWorker(QThread):
    progress = pyqtSignal(object, object)

    def __init__(self, client_factory, operation, args, parent=None):
        super().__init__(parent)
        self._factory = client_factory
        self.operation = operation
        self.args = args
        self.cancel_event = threading.Event()
        self.result = None
        self.error = None
        self.cancelled = False

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            client = self._factory()
            if self.operation == 'install':
                self.result = stage_update(*self.args)
            elif self.operation == 'download':
                self.result = client.download(*self.args,
                    progress=lambda done, total: self.progress.emit(done, total), cancel=self.cancel_event)
            else:
                self.result = client.check(*self.args, cancel=self.cancel_event)
        except UpdateCancelled:
            self.cancelled = True
        except UpdateError as exc:
            self.error = str(exc)
        except Exception:
            # Transport exceptions may contain request internals or signed URLs.
            self.error = 'The update request could not be completed. Please try again.'


class AboutPage(QWidget):
    idle = pyqtSignal()

    def __init__(self, store, client_factory=None):
        super().__init__()
        self.store = store
        self._client_factory = client_factory or GitHubUpdateClient
        self._worker = None
        self._release = None
        self._downloaded_path = None
        self._install_after_download = False
        self.info = installation_info()
        self._build()
        self._set_state('not_checked')
        theme_manager().changed.connect(self.retheme)
        self.retheme()

    @property
    def busy(self):
        # Keep the guard through queued finished handling, not only QThread.run().
        return self._worker is not None

    def _build(self):
        self.setObjectName('page')
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 28)
        root.setSpacing(22)
        titles = QVBoxLayout()
        titles.setSpacing(6)
        titles.addWidget(label('About', 'pageTitle'))
        titles.addWidget(plain_note('Your application version and software updates.'))
        root.addLayout(titles)
        identity = QFrame()
        identity.setObjectName('aboutCard')
        card = QVBoxLayout(identity)
        card.setContentsMargins(26, 26, 26, 24)
        card.setSpacing(22)
        brand = QHBoxLayout()
        brand.setSpacing(18)
        logo = QLabel()
        logo.setPixmap(QIcon(str(resource_root() / 'S4_Studio.ico')).pixmap(68, 68))
        logo.setFixedSize(72, 72)
        brand.addWidget(logo)
        branding = QVBoxLayout()
        branding.setSpacing(7)
        branding.addWidget(label('Optical Design Studio', 'aboutBrand', True))
        branding.addWidget(plain_note('Design, simulate and optimize optical structures.'))
        brand.addLayout(branding, 1)
        card.addLayout(brand)
        line = QFrame()
        line.setObjectName('aboutDivider')
        line.setFixedHeight(1)
        card.addWidget(line)
        metadata = QGridLayout()
        metadata.setHorizontalSpacing(30)
        metadata.setVerticalSpacing(7)
        self.metadata_labels = {}
        for column, (key, value) in enumerate((
            ('Installed version', self.info['version']),
            ('Last updated', self.info['last_updated']),
            ('Platform', self.info['platform']),
        )):
            metadata.setColumnStretch(column, 1)
            metadata.addWidget(plain_note(key), 0, column)
            value_label = label(value, 'aboutValue', True)
            self.metadata_labels[key] = value_label
            metadata.addWidget(value_label, 1, column)
        card.addLayout(metadata)
        root.addWidget(identity)
        self.update_card = QFrame()
        self.update_card.setObjectName('aboutCard')
        update = QVBoxLayout(self.update_card)
        update.setContentsMargins(26, 24, 26, 24)
        update.setSpacing(21)
        top = QHBoxLayout()
        top.addWidget(label('Software updates', 'sectionTitle'), 1)
        top.addWidget(label('PUBLIC UPDATES', 'publicBadge'))
        update.addLayout(top)
        status_box = QFrame()
        status_box.setObjectName('updateStatusBox')
        status = QHBoxLayout(status_box)
        status.setContentsMargins(18, 18, 18, 18)
        status.setSpacing(15)
        self.mark = StatusMark()
        status.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(7)
        self.status_title = label('', 'updateTitle', True)
        self.status_detail = plain_note('')
        words.addWidget(self.status_title)
        words.addWidget(self.status_detail)
        status.addLayout(words, 1)
        update.addWidget(status_box)
        self.last_checked = plain_note('Last checked: Never')
        update.addWidget(self.last_checked)
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.check_button = button('Check for updates', self.check_for_updates)
        self.check_button.setMinimumWidth(174)
        self.check_button.setMinimumHeight(30)
        self.download_button = button('Download update', self.download_update, primary=True)
        self.download_button.setMinimumWidth(174)
        self.download_button.setMinimumHeight(30)
        actions.addWidget(self.check_button)
        actions.addWidget(self.download_button)
        actions.addStretch(1)
        self.notes_button = QPushButton('Release notes')
        self.notes_button.setObjectName('aboutLink')
        self.notes_button.clicked.connect(self.show_release_notes)
        actions.addWidget(self.notes_button)
        update.addLayout(actions)
        self.progress_row = QWidget()
        progress_layout = QHBoxLayout(self.progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(22)
        progress_layout.addWidget(self.progress_bar, 1)
        self.cancel_button = button('Cancel', self.cancel_request)
        progress_layout.addWidget(self.cancel_button)
        update.addWidget(self.progress_row)
        self.download_note = plain_note('')
        update.addWidget(self.download_note)
        root.addWidget(self.update_card)
        root.addWidget(plain_note('Software updates are available without an account or sign-in.'))
        root.addStretch(1)

    def retheme(self, *args):
        c = COLORS[theme_manager().mode]
        self.setStyleSheet(f'''
            QFrame#aboutCard {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:12px; }}
            QFrame#aboutDivider {{ background:{c['border']}; border:0; }}
            QFrame#updateStatusBox {{ background:{c['bg']}; border:1px solid {c['border']}; border-radius:8px; }}
            QLabel#aboutBrand {{ font-size:23pt; font-weight:650; }}
            QLabel#aboutValue {{ font-size:13pt; font-weight:600; }}
            QLabel#updateTitle {{ font-size:16pt; font-weight:600; }}
            QLabel#publicBadge {{ color:{c['accent']}; background:{c['hover']}; border-radius:5px; padding:5px 9px; font-size:8pt; font-weight:650; }}
            QPushButton#aboutLink {{ border:0; background:transparent; color:{c['accent']}; padding:7px 0; }}
        ''')
        self.mark.update()

    def _set_state(self, state, detail=None):
        self.state = state
        states = {
            'not_checked': ('Updates have not been checked', 'Check for the latest stable release. No sign-in is needed.'),
            'checking': ('Checking for updates', 'Contacting the public software update service…'),
            'available': ('An update is available', 'A newer compatible release is ready to download.'),
            'current': ('You’re up to date', 'You have the latest compatible stable version of Optical Design Studio.'),
            'no_releases': ('No releases published yet', 'The update service is reachable. Check again after a release is published.'),
            'no_compatible': ('No compatible update is available', 'No published package matches this platform. This does not confirm that the application is up to date.'),
            'error': ('Could not check for updates', 'Please try again.'),
            'cancelled': ('Update request cancelled', 'Check again whenever you are ready.'),
            'downloading': ('Downloading update', 'The package will be checked before it is saved.'),
            'downloaded': ('Update downloaded', 'Open the download folder when you are ready to install the update.'),
            'installing': ('Preparing installation', 'Verifying and staging the update. The application will restart in its current folder.'),
        }
        title, default_detail = states[state]
        self.status_title.setText(title)
        self.status_detail.setText(detail or default_detail)
        self.mark.kind = state
        self.mark.update()
        can_download = state == 'available' and self._release is not None
        downloaded = state == 'downloaded' and self._downloaded_path is not None
        self.download_button.setVisible(can_download or downloaded)
        installable = getattr(sys, 'frozen', False) and sys.platform == 'win32'
        self.download_button.setText(('Install and restart' if installable else 'Open download folder') if downloaded else ('Download and install' if installable else 'Download update'))
        self.notes_button.setVisible((can_download or downloaded) and self._release is not None)
        self.progress_row.setVisible(state in ('checking', 'downloading', 'installing'))
        self.check_button.setEnabled(not self.busy)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(state != 'installing')
        self.download_note.setText('Download the update, then choose when to install it.' if can_download else
            ('Extract the ZIP, then run Optical Design Studio.exe from the extracted folder. Keep your User Data folder and portable_settings.json when updating.' if downloaded and self._downloaded_path.suffix.lower() == '.zip' else
             'The application will not run the installer automatically.' if downloaded else
             'Your projects, materials and saved results remain in your local library.'))
        if installable and (can_download or downloaded):
            self.download_note.setText('Updates replace this application in its current folder and restart it. Your data and settings are preserved.')

    def check_for_updates(self):
        if self.busy:
            return
        self._start('check', (self.info['version'], self.info['platform_id']))

    def download_update(self):
        if self.busy:
            return
        if self.state == 'downloaded' and self._downloaded_path is not None:
            if getattr(sys, 'frozen', False) and sys.platform == 'win32':
                self.install_update()
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._downloaded_path.parent)))
            return
        if self.state != 'available' or self._release is None:
            return
        self._install_after_download = getattr(sys, 'frozen', False) and sys.platform == 'win32'
        if self._install_after_download:
            if self.store.busy:
                self.status_detail.setText('Wait for the current calculation or library operation before updating.')
                return
            if self.install_confirmation().exec() != QDialog.DialogCode.Accepted:
                return
        directory = QFileDialog.getExistingDirectory(self, 'Save update in folder', str(Path.home() / 'Downloads'))
        if directory:
            self._start('download', (self._release, Path(directory)))

    def install_confirmation(self):
        # A Qt dialog deliberately inherits the app palette in both themes.
        dialog = QDialog(self)
        dialog.setWindowTitle('Download and install update')
        dialog.setMinimumWidth(440)
        layout = QVBoxLayout(dialog)
        layout.addWidget(plain_note(f'Update to version {self._release.version}'))
        layout.addWidget(plain_note('Download the verified update, replace the current application, and restart. Your projects, materials and settings will be preserved.'))
        layout.addWidget(plain_note('Save your work before continuing. The current application will close after the download is verified.'))
        buttons = QDialogButtonBox()
        cancel = buttons.addButton('Not now', QDialogButtonBox.ButtonRole.RejectRole)
        install = buttons.addButton('Download and install', QDialogButtonBox.ButtonRole.AcceptRole)
        install.setProperty('primary', True)
        cancel.setDefault(True)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog

    def install_update(self):
        if self.busy or self.store.busy:
            self.status_detail.setText('Wait for active work to finish, then choose Install and restart.')
            return
        if self._downloaded_path is None or self._release is None:
            return
        try:
            self.store._autosave()
            self._start('install', (self._downloaded_path, self._release, application_root(), self.store.library.root))
            self.store._set_busy(True)
        except Exception as exc:
            self.status_detail.setText('Could not prepare installation: ' + str(exc))

    def _start(self, operation, args):
        if self.busy:
            return
        if operation == 'check':
            self._release = None
        self._downloaded_path = None
        worker = UpdateWorker(self._client_factory, operation, args, self)
        self._worker = worker
        worker.progress.connect(self._update_progress)
        worker.finished.connect(self._finish)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat('Checking…' if operation == 'check' else 'Downloading…')
        self._set_state('checking' if operation == 'check' else 'installing' if operation == 'install' else 'downloading')
        worker.start()

    def _update_progress(self, done, total):
        if not self.busy or self._worker.operation != 'download':
            return
        if total and total > 0:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(min(1000, int(1000 * done / total)))
            self.progress_bar.setFormat(f'{done / 1048576:.1f} / {total / 1048576:.1f} MB')
        else:
            self.progress_bar.setRange(0, 0)

    def cancel_request(self):
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_detail.setText('Cancelling the request safely…')

    def _finish(self):
        worker = self._worker
        if worker is None:
            return
        self._worker = None
        if worker.operation == 'install':
            self.store._set_busy(False)
        try:
            if worker.cancelled:
                self._release = None
                self._set_state('cancelled')
            elif worker.error is not None:
                self._release = None
                self._set_state('error', worker.error)
                self.status_title.setText('Could not prepare installation' if worker.operation == 'install' else 'Could not download update' if worker.operation == 'download'
                    else 'Could not check for updates')
            elif worker.operation == 'download':
                self._downloaded_path = Path(worker.result)
                self._set_state('downloaded', f'Verified package saved as {self._downloaded_path.name}.')
                if self._install_after_download:
                    QTimer.singleShot(0, self.install_update)
            elif worker.operation == 'install':
                try:
                    launch_update(worker.result)
                    self.window().close()
                except Exception as exc:
                    self._set_state('error', 'Could not start installation: ' + str(exc))
            else:
                result = worker.result
                self._release = result.release if result.status == 'available' else None
                self.last_checked.setText('Last checked: ' + display_time(result.checked_at) + ' · Stable channel')
                self._set_state(result.status)
                if result.status == 'available' and self._release is not None:
                    self.status_detail.setText(f'Version {self._release.version} is ready to download for {self.info["platform"]}.')
        finally:
            worker.deleteLater()
            self.idle.emit()

    def show_release_notes(self):
        if self._release is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f'Release notes · {self._release.version}')
        dialog.resize(630, 460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(plain_note('Published: ' + display_time(self._release.published_at)))
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(self._release.notes or 'No release notes were provided.')
        layout.addWidget(text, 1)
        layout.addWidget(button('View update releases', lambda: QDesktopServices.openUrl(QUrl(REPOSITORY_URL + '/releases'))))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()
        dialog.deleteLater()

    def shutdown(self):
        """Host must defer destruction until idle; socket operations have a timeout."""
        if self.busy:
            self.cancel_request()
            return False
        return True
