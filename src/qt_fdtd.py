"""Native Meep setup and FDTD calculation panels."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import uuid

import numpy as np
import pandas as pd
from PyQt6.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
    QMessageBox, QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from data_library import write_json
from fdtd_model import DEFAULTS, build_job, validate_options
import meep_runtime
from qt_common import PlotWidget, number, integer, table, fill_table


class MeepWorker(QThread):
    event = pyqtSignal(dict)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, kind, project, options, library, parent=None):
        super().__init__(parent)
        self.kind, self.project, self.options, self.library = kind, project, options, library
        self.directory = None
        self._cancelled = threading.Event()
        self.process = None

    def cancel(self):
        self._cancelled.set()
        if self.directory:
            (self.directory/'cancel.flag').touch()

    def run(self):
        terminal = None
        managed = None
        try:
            config = meep_runtime.load_config()
            ready = meep_runtime.probe(config)
            if not ready['available']:
                raise RuntimeError('Set up the MEEP FDTD add-on in Settings. '+ready['message'])
            spec = build_job(self.project, self.library.files_for(self.project), self.options)
            if self._cancelled.is_set():
                self.completed.emit(dict(run_kind='fdtd', status='cancelled'))
                return
            self.directory = self.library.runs/('fdtd_'+uuid.uuid4().hex)
            self.directory.mkdir()
            write_json(self.directory/'project.json', self.project)
            write_json(self.directory/'fdtd_job.json', spec)
            self.library.record(self.directory, kind='simulation', title='Meep FDTD simulation', status='running', engine='Meep')
            runner = meep_runtime.copy_runner(self.directory)
            args = meep_runtime.command(config, [meep_runtime.linux_path(runner, config), '--job', meep_runtime.linux_path(self.directory/'fdtd_job.json', config)])
            if self._cancelled.is_set():
                self.cancel()
            with (self.directory/'meep.log').open('w', encoding='utf-8') as log:
                managed = meep_runtime.ManagedProcess(config, args)
                self.process = managed.process
                for line in managed.stream(self._cancelled):
                    log.write(line)
                    log.flush()
                    if line.startswith('ODS_MEEP '):
                        message = json.loads(line[len('ODS_MEEP '):])
                        if message['kind'] in ('complete', 'error', 'cancelled'):
                            terminal = message
                        else:
                            self.event.emit(dict(message, run_kind='fdtd', directory=str(self.directory)))
                code = self.process.wait(timeout=10)
            if self._cancelled.is_set():
                terminal = dict(kind='cancelled')
            if terminal is None or terminal['kind']=='error' or (code and terminal['kind']!='cancelled'):
                raise RuntimeError((terminal or {}).get('message') or f'Meep exited with code {code}. See {self.directory / "meep.log"}.')
            status = 'cancelled' if terminal['kind']=='cancelled' else 'complete'
            self.library.record(self.directory, status=status, summary=terminal.get('info', {}))
            self.completed.emit(dict(run_kind='fdtd', status=status, directory=str(self.directory),
                output=str(self.directory/'results.csv'), info=terminal.get('info', {})))
        except Exception as exc:
            if managed is not None:
                managed.terminate(force=True)
            if self.directory:
                self.library.record(self.directory, status='error')
            self.failed.emit(str(exc))


class _RuntimeTask(QThread):
    line = pyqtSignal(str)
    completed = pyqtSignal(dict)

    def __init__(self, config, install=False, parent=None):
        super().__init__(parent)
        self.config, self.install = config, install
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            if self.install:
                process = meep_runtime.ManagedProcess(self.config, meep_runtime.install_command(self.config))
                for line in process.stream(self.cancelled, timeout=7200):
                    self.line.emit(line.rstrip())
                if self.cancelled.is_set():
                    self.completed.emit(dict(available=False, message='Meep installation cancelled. Click Install Meep again to repair an incomplete environment.'))
                    return
                if process.process.wait(timeout=10):
                    raise RuntimeError('Conda could not install Meep. Review the installation log and the Linux/Conda paths.')
            result = meep_runtime.probe(self.config)
            if result['available'] and not self.cancelled.is_set():
                meep_runtime.save_config(self.config)
            self.completed.emit(result)
        except Exception as exc:
            self.completed.emit(dict(available=False, message=str(exc)))


class _ManagedRuntimeTask(QThread):
    line = pyqtSignal(str)
    progress = pyqtSignal(int)
    completed = pyqtSignal(dict)

    def __init__(self, install=False, parent=None):
        super().__init__(parent)
        self.install = install
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        import meep_managed
        from update_client import UpdateCancelled, _cancelled
        try:
            status = meep_managed.prerequisites(self.cancelled)
            if status['ready'] and meep_managed.receipt():
                ready = meep_managed.verify_installed(cancel=self.cancelled)
                if ready['available']:
                    self.completed.emit(dict(ready, managed=True, ready=True, needs_setup=False))
                    return
            client = meep_managed.ManagedMeepClient()
            self.line.emit('Checking the official GitHub release for compatible FDTD setup files…')
            release = client.check_pack(self.cancelled)
            if release is None:
                self.completed.emit(dict(status, available=False, message=
                    'No managed FDTD package is published for this application version yet. Nothing was downloaded or installed. '
                    + (status['message'] if not status['ready'] else 'Expert setup can use an existing Meep installation.')))
                return
            if not self.install or not status['ready']:
                self.completed.emit(dict(status, available=False, release=release, message=
                    ('FDTD setup available. Install downloads Linux and Meep dependencies from their official providers; an internet connection and additional disk space are required.'
                     if status['ready'] else status['message'])))
                return
            self.line.emit('Downloading verified FDTD setup files from the official GitHub release…')
            with tempfile.TemporaryDirectory(prefix='ods-meep-download-') as tmp:
                package = client.download(release, tmp,
                    lambda done, total: self.progress.emit(int(100*done/total)), self.cancelled)
                self.line.emit('Verifying FDTD setup files…')
                rootfs, manifest = meep_managed.unpack_pack(package, release, Path(tmp)/'verified', self.cancelled)
                _cancelled(self.cancelled)
                result = meep_managed.import_pack(rootfs, manifest, release, cancel=self.cancelled, progress=self.line.emit)
            self.completed.emit(dict(result, managed=True, ready=True, needs_setup=False))
        except UpdateCancelled:
            self.completed.emit(dict(available=False, message='FDTD setup cancelled. Any completed dedicated runtime import is preserved; click Check availability to verify it later.'))
        except Exception as exc:
            self.completed.emit(dict(available=False, message=str(exc)))


class MeepRuntimeSettings(QWidget):
    runtime_changed = pyqtSignal(dict)
    idle = pyqtSignal()

    def __init__(self, parent=None, *, before_operation=None, after_operation=None):
        super().__init__(parent)
        self._task = None
        self._before_operation = before_operation
        self._after_operation = after_operation
        self._reserved = False
        self._external_busy = False
        layout = QVBoxLayout(self)
        intro = QLabel('Install MEEP in its own Linux environment. Setup files come from the Optical Design Studio GitHub release; Linux and Meep dependencies download directly from their official providers. Downloads start only when you click Install FDTD engine. Existing Linux distributions are left unchanged.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        managed_row = QHBoxLayout()
        self.check_button = QPushButton('Check availability')
        self.install_button = QPushButton('Install FDTD engine')
        self.install_button.setProperty('primary', True)
        self.setup_button = QPushButton('Set up Windows support')
        self.check_button.clicked.connect(lambda: self.start_managed(False))
        self.install_button.clicked.connect(lambda: self.start_managed(True))
        self.setup_button.clicked.connect(self.setup_windows)
        for button in (self.check_button, self.install_button, self.setup_button):
            managed_row.addWidget(button)
        layout.addLayout(managed_row)
        if __import__('sys').platform!='win32':
            self.install_button.setEnabled(False)
            self.setup_button.hide()
        requirement = QLabel('First-time Windows setup may require administrator approval, virtualization support and a restart. Your existing Linux distributions and default distribution are left unchanged.')
        requirement.setWordWrap(True)
        requirement.setObjectName('muted')
        layout.addWidget(requirement)
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.status = QLabel('Not checked. No automatic downloads or Windows changes.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.cancel_button = QPushButton('Cancel FDTD setup')
        self.cancel_button.clicked.connect(self.shutdown)
        self.cancel_button.hide()
        layout.addWidget(self.cancel_button)
        expert_toggle = QPushButton('Expert setup · use an existing runtime')
        expert_toggle.setCheckable(True)
        layout.addWidget(expert_toggle)
        self.expert = QWidget()
        expert_layout = QVBoxLayout(self.expert)
        expert_layout.setContentsMargins(0, 0, 0, 0)
        self.expert.hide()
        expert_toggle.toggled.connect(self.expert.setVisible)
        layout.addWidget(self.expert)
        config = meep_runtime.load_config()
        self.mode = QComboBox()
        self.mode.addItem('WSL / Linux', 'wsl')
        if __import__('sys').platform != 'win32':
            self.mode.addItem('Local Linux / macOS', 'local')
        self.mode.setCurrentIndex(max(0, self.mode.findData(config['mode'])))
        self.distro, self.python, self.conda = (QLineEdit(config[k]) for k in ('distro', 'python', 'conda'))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for label, control in [('Runtime', self.mode), ('WSL distribution', self.distro),
                               ('Linux Python path', self.python), ('Linux Conda path', self.conda)]:
            form.addRow(label, control)
        expert_layout.addLayout(form)
        row = QHBoxLayout()
        self.expert_check, self.expert_install = QPushButton('Check & save runtime'), QPushButton('Install into existing Conda')
        self.expert_check.clicked.connect(lambda: self.start(False))
        self.expert_install.clicked.connect(lambda: self.start(True))
        docs = QPushButton('Setup guide')
        docs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://meep.readthedocs.io/en/latest/Installation/')))
        for button in (self.expert_check, self.expert_install, docs):
            row.addWidget(button)
        expert_layout.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(400)
        self.log.setMaximumHeight(160)
        layout.addWidget(self.log)

    def _set_busy(self, busy):
        for button in (self.check_button, self.install_button, self.setup_button, self.expert_check, self.expert_install):
            button.setEnabled(not busy and not self._external_busy)
        if __import__('sys').platform!='win32':
            self.install_button.setEnabled(False)
        self.cancel_button.setVisible(busy)
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)

    def set_external_busy(self, busy):
        self._external_busy = bool(busy)
        self._set_busy(self._task is not None)

    def _reserve(self):
        if self._external_busy:
            raise RuntimeError('Wait for the active calculation, library operation, update or add-on installation to finish.')
        if self._before_operation is not None:
            self._before_operation()
            self._reserved = True

    def _release(self):
        reserved, self._reserved = self._reserved, False
        if reserved and self._after_operation is not None:
            self._after_operation()

    def start_managed(self, install):
        if self._task:
            return
        try:
            self._reserve()
            self._task = _ManagedRuntimeTask(install, self)
            self._task.line.connect(self.log.appendPlainText)
            self._task.line.connect(self.status.setText)
            self._task.progress.connect(self._download_progress)
            self._task.completed.connect(self._done)
            self._task.finished.connect(self._cleanup)
            self._set_busy(True)
            self.status.setText('Checking Windows support and the official FDTD package…')
            self._task.start()
        except Exception as exc:
            self._release()
            self.status.setText(str(exc))

    def _download_progress(self, value):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)

    def setup_windows(self):
        if self._task:
            return
        if self._external_busy:
            self.status.setText('Wait for the active operation to finish before setting up Windows support.')
            return
        choice = QMessageBox.question(self, 'Set up Windows support for FDTD',
            'Enable Microsoft Windows Subsystem for Linux support?\n\n'
            'Windows will request administrator approval. Hardware virtualization must be enabled; Windows may require a restart. '
            'This step installs no Linux distribution and does not restart your computer automatically. '
            'After setup, return here and click Install FDTD engine.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            self._reserve()
            import meep_managed
            self.status.setText(meep_managed.setup_windows_support())
        except Exception as exc:
            self.status.setText(str(exc))
        finally:
            self._release()

    def start(self, install):
        if self._task:
            return
        try:
            config = meep_runtime.validate_config(dict(mode=self.mode.currentData(), distro=self.distro.text(),
                python=self.python.text(), conda=self.conda.text()))
            if install:
                meep_runtime.install_command(config)
            self._reserve()
            self._task = _RuntimeTask(config, install, self)
            self._task.line.connect(self.log.appendPlainText)
            self._task.completed.connect(self._done)
            self._task.finished.connect(self._cleanup)
            self._set_busy(True)
            self.status.setText('Installing Meep into the selected isolated environment…' if install else 'Checking the selected runtime…')
            self._task.start()
        except Exception as exc:
            self._release()
            self.status.setText(str(exc))

    def _done(self, result):
        self.status.setText(result['message'])
        if result.get('available'):
            config = meep_runtime.load_config()
            for key, control in [('distro', self.distro), ('python', self.python), ('conda', self.conda)]:
                control.setText(config[key])
        self.runtime_changed.emit(result)

    def _cleanup(self):
        self._task.deleteLater()
        self._task = None
        self._release()
        self._set_busy(False)
        self.idle.emit()

    def is_busy(self):
        return self._task is not None

    def shutdown(self):
        """Request cancellation. Caller must wait for idle before destruction."""
        if self._task is not None:
            self._task.cancel()
            self.status.setText('Stopping Meep setup; waiting for its process to exit…')
            return False
        return True


class FDTDPage(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store, self.directory, self._active = store, None, False
        self._runtime_available = None
        layout = QVBoxLayout(self)
        title = QLabel('MEEP · FDTD')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = QLabel('Broadband pulse simulation of the shared structure, with an incident-reference run for reflection and transmission. Lateral boundaries are periodic; incidence is normal.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.controls = dict(
            dimensions=QComboBox(), resolution=integer(30, 5, 1000),
            wavelength_min_nm=number(1200, .001), wavelength_max_nm=number(1800, .001),
            frequency_points=integer(101, 2, 2001), polarization=QComboBox(),
            pml_um=number(1., .001), padding_um=number(1., .001),
            run_after_sources=number(200., 1., 1e7), courant=number(.5, .001, .5),
            section_y_um=number(0.), decay_by=number(1e-7, 1e-12, .1, 12),
            fit_materials=QCheckBox('Fit tabulated n,k to passive dispersion'),
            save_fields=QCheckBox('Save centre-frequency XZ field map'))
        self.controls['dimensions'].addItem('2D · XZ section (extruded along Y)', 2)
        self.controls['dimensions'].addItem('3D · full periodic structure', 3)
        self.controls['polarization'].addItem('s · Ey', 's')
        self.controls['polarization'].addItem('p · Ex', 'p')
        self.controls['fit_materials'].setChecked(True)
        self.controls['save_fields'].setChecked(True)
        self.controls['dimensions'].currentIndexChanged.connect(lambda: self.controls['section_y_um'].setEnabled(self.controls['dimensions'].currentData()==2))
        left = QWidget()
        controls_layout = QVBoxLayout(left)
        for group_title, rows in [
            ('Domain & excitation', [('View', 'dimensions'), ('Resolution (cells/µm)', 'resolution'), ('Section Y (µm)', 'section_y_um'), ('Polarization', 'polarization')]),
            ('Spectrum', [('First wavelength (nm)', 'wavelength_min_nm'), ('Last wavelength (nm)', 'wavelength_max_nm'), ('Frequency samples', 'frequency_points')]),
            ('Boundaries & stopping', [('PML thickness (µm)', 'pml_um'), ('Air/medium padding (µm)', 'padding_um'), ('Maximum time after pulse (µm/c)', 'run_after_sources'), ('Courant factor', 'courant'), ('Field energy decay target', 'decay_by')])]:
            group = QGroupBox(group_title)
            form = QFormLayout(group)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            for label, key in rows:
                form.addRow(label, self.controls[key])
            controls_layout.addWidget(group)
        controls_layout.addWidget(self.controls['fit_materials'])
        fit_note = QLabel('Fits must stay within 5% relative permittivity error over the selected band. Complex constant materials need tabulated n,k data. Incident and exit media must be lossless constants.')
        fit_note.setWordWrap(True)
        controls_layout.addWidget(fit_note)
        controls_layout.addWidget(self.controls['save_fields'])
        controls_layout.addStretch()
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(left)
        action_panel = QWidget()
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.addWidget(area)
        actions = QHBoxLayout()
        self.start_button, self.stop_button = QPushButton('Run FDTD simulation'), QPushButton('Stop')
        self.start_button.setProperty('primary', True)
        self.start_button.clicked.connect(self.run)
        self.stop_button.clicked.connect(store.cancel)
        actions.addWidget(self.start_button, 1)
        actions.addWidget(self.stop_button)
        action_layout.addLayout(actions)
        self.plot, self.field_plot, self.samples = PlotWidget(), PlotWidget(), table([])
        self.result_frame = pd.DataFrame()
        self.peak_quantity = QComboBox()
        for label, key in [('Reflection', 'R'), ('Transmission', 'T'), ('Absorption', 'A')]:
            self.peak_quantity.addItem(label, key)
        self.peak_quantity.setCurrentIndex(2)
        self.peak_summary = QLabel('Run a simulation or load saved results to inspect the highest sample.')
        self.peak_summary.setWordWrap(True)
        peak_box = QGroupBox('Highest sampled point')
        peak_layout = QFormLayout(peak_box)
        peak_layout.addRow('Find maximum of', self.peak_quantity)
        peak_layout.addRow(self.peak_summary)
        hint = QLabel('Uses displayed simulation data. Change the selection at any time. Ties use the first sample.')
        hint.setWordWrap(True)
        peak_layout.addRow(hint)
        self.peak_quantity.currentIndexChanged.connect(self.update_peak)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(300)
        tabs = QTabWidget()
        for widget, label in [(self.plot, 'Spectrum'), (self.field_plot, 'XZ field map'), (self.samples, 'Samples'), (self.log, 'Run details')]:
            tabs.addTab(widget, label)
        from qt_compute import _ResponsiveSplitter
        splitter = _ResponsiveSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(action_panel)
        output = QWidget()
        output_layout = QVBoxLayout(output)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(peak_box)
        output_layout.addWidget(tabs, 1)
        splitter.addWidget(output)
        splitter.setSizes([370, 740])
        layout.addWidget(splitter, 1)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel('Configure MEEP in Settings → Add-ons before your first run. 2D represents an extruded cross section; use 3D for holes.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        open_button = QPushButton('Open saved result files')
        open_button.clicked.connect(self.open_results)
        layout.addWidget(open_button)
        load_button = QPushButton('Load saved simulation results')
        load_button.clicked.connect(self.load_results)
        layout.addWidget(load_button)
        store.busy_changed.connect(self._busy)
        store.progress.connect(self._progress)
        store.run_finished.connect(self._finished)
        store.run_failed.connect(self._failed)
        self._busy(store.busy)
        self._restore()

    def _restore(self):
        options = self.store.search_state.get('fdtd', {})
        for key, control in self.controls.items():
            value = options.get(key, DEFAULTS[key])
            if isinstance(control, QComboBox):
                control.setCurrentIndex(max(0, control.findData(value)))
            elif isinstance(control, QCheckBox):
                control.setChecked(bool(value))
            else:
                control.setValue(float(value) if not isinstance(value, int) else value)

    def options(self):
        return validate_options({key: control.currentData() if isinstance(control, QComboBox)
            else control.isChecked() if isinstance(control, QCheckBox) else control.value()
            for key, control in self.controls.items()})

    def run(self):
        try:
            self._active = True
            self.store.start_run('fdtd', self.options())
            self.progress.setRange(0, 0)
            self.progress.show()
            self.status.setText('Validating structure, materials and Meep runtime…')
        except Exception as exc:
            self._failed(str(exc))

    def _busy(self, busy):
        self.start_button.setEnabled(not busy and self._runtime_available is not False)
        self.stop_button.setEnabled(busy and self._active)

    def refresh_runtime(self, result):
        """Receive verified setup results without importing Meep in the GUI."""
        self._runtime_available = bool(result.get('available'))
        if not self._active:
            self.status.setText(result.get('message') or ('MEEP is ready.' if self._runtime_available else 'Install or configure the FDTD engine in Settings → Add-ons.'))
        self._busy(self.store.busy)

    def _progress(self, info):
        if info.get('run_kind') == 'fdtd':
            message = info.get('message', 'Running Meep…')
            self.status.setText(message)
            self.log.appendPlainText(message)

    def _failed(self, message):
        if self._active:
            self._active = False
            self.progress.hide()
            self.status.setText(message)
            self.log.appendPlainText(message)

    def _finished(self, event):
        if event.get('run_kind') != 'fdtd':
            return
        self._active = False
        self.progress.hide()
        if event.get('status') == 'cancelled':
            self.status.setText('FDTD calculation cancelled.')
            return
        self._display_result(event)

    def load_results(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load saved simulation results',
            str(self.directory or ''), 'Simulation results (results.csv);;CSV files (*.csv)')
        if path:
            self._display_result({'directory': str(Path(path).parent), 'output': path, 'loaded': True})

    def update_peak(self, *_):
        from qt_compute import highest_sample_index, spectrum_figure
        frame = self.result_frame
        key = self.peak_quantity.currentData()
        name = self.peak_quantity.currentText().lower()
        self.plot.draw_figure(spectrum_figure(frame, title='MEEP · normalized optical response', peak_key=key))
        self.samples.clearSelection()
        position = highest_sample_index(frame, key)
        if position is None:
            self.peak_summary.setText(f'No finite {name} samples are available in the displayed data.')
            return
        best = frame.iloc[position]
        wavelength = pd.to_numeric(best.get('wavelength_nm'), errors='coerce')
        location = f' at {wavelength:.8g} nm' if pd.notna(wavelength) and np.isfinite(wavelength) else ''
        self.peak_summary.setText(f'Highest sampled {name}: {100 * float(best[key]):.7g}%{location} (sample {position + 1}).')
        self.samples.selectRow(position)

    def _display_result(self, event):
        try:
            self.directory = Path(event['directory'])
            from qt_compute import _read_csv
            frame = _read_csv(Path(event.get('output') or self.directory/'results.csv'))
            self.result_frame = frame
            fill_table(self.samples, frame)
            self.update_peak()
            self.field_plot.clear()
            info = event.get('info', {})
            self.log.appendPlainText(json.dumps(info, indent=2))
            self.status.setText(('Saved simulation loaded. ' if event.get('loaded') else 'Completed. ') + ' '.join(info.get('warnings', [])))
            field_path = self.directory/'fdtd_fields.npz'
            if field_path.exists():
                from matplotlib.figure import Figure
                with np.load(field_path, allow_pickle=False) as data:
                    figure = Figure(layout='constrained')
                    axis = figure.add_subplot(111)
                    image = axis.pcolormesh(data['x_um'], data['depth_um'], abs(data['field']).T**2, shading='auto', cmap='turbo')
                    figure.colorbar(image, ax=axis, label='Raw |DFT E|² (not incident-normalized)')
                    axis.set(xlabel='x (µm)', ylabel='Depth from stack centre (µm)', title=f'XZ · {float(data["wavelength_nm"]):g} nm')
                    axis.invert_yaxis()
                    self.field_plot.draw_figure(figure)
        except Exception as exc:
            self.status.setText('Result saved; could not render it: '+str(exc))

    def open_results(self):
        if self.directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory)))
