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
from PyQt6.QtCore import QThread, QTimer, Qt, QUrl, QSignalBlocker, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
    QMessageBox, QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget, QListWidget, QListWidgetItem, QApplication)

from data_library import write_json
from fdtd_model import DEFAULTS, build_job, validate_options
import meep_runtime
from fdtd_progress import SCHEMA as TIMING_SCHEMA, PhaseEstimate, cached_estimate, duration, timing_key
from qt_common import PlotWidget, number, integer, table, fill_table
from qt_surfaces import WorkspacePanel


class MeepWorker(QThread):
    progress_event = pyqtSignal(dict)
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
        started = time.monotonic()
        phase_estimate = PhaseEstimate()
        phase_budgets, phase_elapsed = {}, {}
        try:
            config = meep_runtime.load_config()
            self.progress_event.emit(dict(run_kind='fdtd', message='Preparing Meep runtime and inputs…', elapsed_seconds=0.))
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
                            elapsed = time.monotonic()-started
                            if message.get('phase'):
                                if message['kind'] == 'phase_complete':
                                    phase_budgets[message['phase']] = phase_estimate.budget_seconds()
                                    phase_elapsed[message['phase']] = message.get('phase_elapsed_seconds', 0.)
                                else:
                                    phase_estimate.update(message, time.monotonic())
                                if message.get('time') is not None:
                                    message['message'] += ' · elapsed '+duration(elapsed)+' · '+phase_estimate.text(time.monotonic())
                            message['elapsed_seconds'] = elapsed
                            self.progress_event.emit(dict(message, run_kind='fdtd', directory=str(self.directory)))
                code = self.process.wait(timeout=10)
            if self._cancelled.is_set():
                terminal = dict(kind='cancelled')
            if terminal is None or terminal['kind']=='error' or (code and terminal['kind']!='cancelled'):
                raise RuntimeError((terminal or {}).get('message') or f'Meep exited with code {code}. See {self.directory / "meep.log"}.')
            status = 'cancelled' if terminal['kind']=='cancelled' else 'complete'
            if status == 'complete':
                info = terminal.setdefault('info', {})
                info['elapsed_seconds'] = time.monotonic()-started
                if set(phase_budgets) == {'Reference', 'Device'} and all(value is not None for value in phase_budgets.values()):
                    overhead = max(0., info['elapsed_seconds']-sum(phase_elapsed.values()))
                    try:
                        write_json(self.directory/'runtime_timing.json', dict(schema=TIMING_SCHEMA,
                            input_key=timing_key(self.project, self.options, config),
                            estimated_budget_seconds=overhead+sum(phase_budgets.values()),
                            actual_elapsed_seconds=info['elapsed_seconds'],
                            convergence=info.get('convergence', {})))
                    except (OSError, ValueError, TypeError) as exc:
                        info.setdefault('warnings', []).append('Could not save runtime estimate data: '+str(exc))
            self.library.record(self.directory, status=status, summary=terminal.get('info', {}))
            self.completed.emit(dict(run_kind='fdtd', status=status, directory=str(self.directory),
                output=str(self.directory/'results.csv'), info=terminal.get('info', {})))
        except Exception as exc:
            errors = [str(exc)]
            if managed is not None:
                try:
                    managed.terminate(force=True)
                except Exception as cleanup_exc:
                    errors.append('Could not stop the Meep process: '+str(cleanup_exc))
            if self.directory:
                try:
                    self.library.record(self.directory, status='error')
                except Exception as record_exc:
                    errors.append('Could not save the failed run status: '+str(record_exc))
            self.failed.emit('\n'.join(errors))


class RuntimeEstimateWorker(QThread):
    """Cached timing lookup only; no probe, input builder or solver execution."""
    result = pyqtSignal(dict)

    def __init__(self, runs, project, options, generation):
        # Application ownership prevents destruction while a page is closed.
        super().__init__(QApplication.instance())
        self.runs, self.project, self.options, self.generation = runs, project, options, generation

    def run(self):
        try:
            key = timing_key(self.project, self.options, meep_runtime.load_config())
            if self.isInterruptionRequested():
                return
            estimate = cached_estimate(self.runs, key, cancelled=self.isInterruptionRequested)
            self.result.emit(dict(generation=self.generation, estimate=estimate))
        except Exception as exc:
            self.result.emit(dict(generation=self.generation, error=str(exc)))


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
        import solver_environment
        from update_client import UpdateCancelled
        try:
            configured = meep_runtime.load_config()
            candidate = dict(mode=configured['mode'], distro=configured['distro'],
                executable=configured['python'], timeout_s=86400.)
            if self.install:
                runtime = solver_environment.setup('meep', candidate, cancel=self.cancelled, progress=self.line.emit)
            else:
                runtime = solver_environment.discover('meep', candidate, cancel=self.cancelled, progress=self.line.emit)
                if not runtime:
                    status = meep_managed.prerequisites(self.cancelled)
                    self.completed.emit(dict(status, available=False, message=
                        'Click Install FDTD engine to create a separate Meep environment from the official Ubuntu and conda-forge providers.'
                        if status['ready'] else status['message']))
                    return
            config = dict(mode=runtime['mode'], distro=runtime.get('distro', 'Ubuntu'),
                python=runtime['executable'], conda=configured.get('conda', '/opt/ods-solvers/bin/micromamba'))
            if runtime.get('distro') == solver_environment.DISTRO:
                config['managed'] = True
                config['conda'] = '/opt/ods-solvers/bin/micromamba'
            result = meep_runtime.probe(config)
            if result['available']:
                meep_runtime.save_config(config)
            self.completed.emit(dict(result, managed=bool(config.get('managed')), ready=result['available'], needs_setup=False))
        except (UpdateCancelled, InterruptedError):
            self.completed.emit(dict(available=False, message='FDTD setup cancelled. Existing runtimes were preserved; click Install FDTD engine to retry.'))
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
        intro = QLabel('Install Meep in a separate environment automatically. Ubuntu and pinned conda-forge dependencies download from their official providers after you click Install FDTD engine. An existing working installation can also be discovered and reused.')
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
            self.status.setText('Checking Windows support and installed Meep environments…')
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
    routeRequested = pyqtSignal(str)
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store, self.directory, self._active = store, None, False
        self._runtime_available = None
        self._estimate_worker = None
        self._estimate_generation = 0
        self._run_started = None
        self._live_estimate = PhaseEstimate()
        self._timing_timer = QTimer(self)
        self._timing_timer.setInterval(1000)
        self._timing_timer.timeout.connect(self._update_timing)
        layout = QVBoxLayout(self)
        title = QLabel('MEEP · FDTD')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        title.hide()
        note = QLabel('Broadband pulse simulation of the simulation structure, with an incident-reference run for reflection and transmission. Lateral boundaries are periodic; incidence is normal.')
        note.setWordWrap(True)
        layout.addWidget(note)
        note.hide()
        self.controls = dict(
            dimensions=QComboBox(), resolution=number(30, 5, 1000, 8), max_cells=integer(30000000, 100, 100000000),
            wavelength_min_nm=number(1200, .001), wavelength_max_nm=number(1800, .001),
            frequency_points=integer(101, 2, 2001), polarization=QComboBox(),
            pml_um=number(1., .001), padding_um=number(1., .001),
            run_after_sources=number(200., 1., 1e7), courant=number(.5, .001, .5),
            section_y_um=number(0.), decay_by=number(1e-7, 1e-12, .1, 12),
            fit_materials=QCheckBox('Fit material dispersion'), fit_tolerance=number(.05, .000001, .1, 6),
            save_fields=QCheckBox('Save XZ field map'),
            source_is_integrated=QCheckBox('Integrated Gaussian source'))
        self.controls['source_is_integrated'].setToolTip(
            'Use Meep is_integrated=True: supply the integrated current (polarization), '
            'which vanishes when the source turns off. This can avoid residual static electric fields. '
            'Default is off for compatibility. Compare reference/device decay and spectra; '
            'this setting does not establish convergence. '
            'See https://meep.readthedocs.io/en/latest/FAQ/#how-is-the-source-current-defined')
        self.controls['save_fields'].setToolTip('Save the centre-frequency XZ field map.')
        self.controls['resolution'].setToolTip(
            'Grid cells per micrometre; fractional values are supported to eight decimal places. '
            'For a lattice pitch a in micrometres, enter desired cells per pitch divided by a. '
            'Meep rounds cell dimensions to grid pixels; check the actual cell in the saved run log.')
        self.controls['decay_by'].setToolTip(
            'Meep stop_when_fields_decayed checks the selected electric-field component’s squared amplitude '
            'at the transmission plane over a 20 µm/c decay window. '
            'The target is relative to the monitored peak; it is not domain-integrated energy.')
        self.controls['dimensions'].addItem('2D · XZ section (extruded along Y)', 2)
        self.controls['dimensions'].addItem('3D · full periodic structure', 3)
        self.controls['polarization'].addItem('s · Ey', 's')
        self.controls['polarization'].addItem('p · Ex', 'p')
        self.controls['fit_materials'].setChecked(True)
        self.controls['save_fields'].setChecked(True)
        self.controls['dimensions'].currentIndexChanged.connect(lambda: self.controls['section_y_um'].setEnabled(self.controls['dimensions'].currentData()==2))
        left = QWidget()
        controls_layout = QVBoxLayout(left)
        self.exterior_group = QGroupBox('Incident and exit media')
        exterior_form = QFormLayout(self.exterior_group)
        self.exterior_controls = {}
        for side, label in [('incident', 'Incident medium'), ('exit', 'Exit medium')]:
            control = QComboBox()
            control.setAccessibleName('Meep '+label.lower())
            control.currentIndexChanged.connect(lambda _, side=side: self._set_exterior(side))
            self.exterior_controls[side] = control
            exterior_form.addRow(label, control)
        controls_layout.addWidget(self.exterior_group)
        if hasattr(store, 'changed'):
            store.changed.connect(self._refresh_exterior)
        self._refresh_exterior()
        self.input_groups = []
        for group_title, rows in [
            ('Domain & excitation', [('View', 'dimensions'), ('Resolution (cells/µm)', 'resolution'), ('Section Y (µm)', 'section_y_um'), ('Polarization', 'polarization'), ('Pulse source', 'source_is_integrated')]),
            ('Spectrum', [('First wavelength (nm)', 'wavelength_min_nm'), ('Last wavelength (nm)', 'wavelength_max_nm'), ('Frequency samples', 'frequency_points')]),
            ('Boundaries & stopping', [('PML thickness (µm)', 'pml_um'), ('Air/medium padding (µm)', 'padding_um'), ('Maximum time after pulse (µm/c)', 'run_after_sources'), ('Courant factor', 'courant'), ('Monitor field decay target', 'decay_by')])]:
            group = QGroupBox(group_title)
            form = QFormLayout(group)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            for label, key in rows:
                form.addRow(label, self.controls[key])
            controls_layout.addWidget(group)
            self.input_groups.append(group)
        controls_layout.addWidget(self.controls['fit_materials'])
        fit_note = QLabel('Fits must satisfy the selected relative permittivity error tolerance over the selected band. Complex constant materials need tabulated n,k data. Incident and exit media must be lossless constants.')
        fit_note.setWordWrap(True)
        self.controls['fit_materials'].setToolTip(fit_note.text());fit_note.hide()
        controls_layout.addWidget(fit_note)
        controls_layout.addWidget(self.controls['save_fields'])
        controls_layout.addStretch()
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(left)
        action_panel = WorkspacePanel()
        action_layout = QVBoxLayout(action_panel)
        self.setup_layout=action_layout
        action_layout.setContentsMargins(10, 10, 10, 10)
        action_layout.addWidget(QLabel('Simulation Setup'))
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
        self.peak_summary = QLabel('')
        self.peak_summary.setWordWrap(True)
        peak_box = QGroupBox('Highest sampled point')
        peak_layout = QFormLayout(peak_box)
        peak_layout.addRow('Find maximum of', self.peak_quantity)
        peak_layout.addRow(self.peak_summary)
        hint = QLabel('Uses displayed simulation data. Change the selection at any time. Ties use the first sample.')
        hint.setWordWrap(True)
        peak_layout.addRow(hint)
        hint.hide();self.peak_quantity.setToolTip(hint.text())
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
        output = WorkspacePanel()
        output_layout = QVBoxLayout(output)
        output_layout.setContentsMargins(12, 12, 12, 12)
        output_layout.addWidget(QLabel('Simulation Results'))
        cards=QHBoxLayout();self.power_values={}
        for key,name in [('R','Reflectance (R)'),('T','Transmittance (T)'),('A','Absorptance (A)')]:
            card=QGroupBox(name);card_layout=QVBoxLayout(card)
            value=QLabel('—');value.setObjectName('responseValue');card_layout.addWidget(value)
            self.power_values[key]=value;cards.addWidget(card)
        output_layout.addLayout(cards)
        samples_page=QWidget();samples_layout=QVBoxLayout(samples_page)
        tabs.removeTab(2);samples_layout.addWidget(peak_box);samples_layout.addWidget(self.samples,1)
        tabs.insertTab(2,samples_page,'Samples')
        self.plot.toolbar.hide();self.field_plot.toolbar.hide()
        output_layout.addWidget(tabs, 1)
        splitter.addWidget(output)
        recent=WorkspacePanel();recent_layout=QVBoxLayout(recent)
        recent_layout.addWidget(QLabel('Recent Runs'))
        self.recent_runs=QListWidget();recent_layout.addWidget(self.recent_runs,1)
        recent_load=QPushButton('Load selected run');recent_load.clicked.connect(self.load_recent)
        recent_layout.addWidget(recent_load)
        restore_setup=QPushButton('Load setup');restore_setup.clicked.connect(self.restore_recent_setup)
        recent_layout.addWidget(restore_setup)
        splitter.addWidget(recent);splitter.reference_ratios=(.305,.435,.26)
        splitter.setSizes([450,640,380])
        layout.addWidget(splitter, 1)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        self.timing_status = QLabel('Runtime estimates use measured timing from matching saved runs.')
        self.timing_status.setWordWrap(True)
        layout.addWidget(self.timing_status)
        self.estimate_button = QPushButton('Estimate runtime')
        self.estimate_button.clicked.connect(self.estimate_runtime)
        layout.addWidget(self.estimate_button)
        from qt_common import ActionStatusLabel
        self.status = ActionStatusLabel()
        self.status.setToolTip('Configure MEEP in Settings → Add-ons before your first run. 2D represents an extruded cross section; use 3D for holes.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        open_button = QPushButton('Open saved result files')
        open_button.clicked.connect(self.open_results)
        recent_layout.addWidget(open_button)
        load_button = QPushButton('Load saved simulation results')
        load_button.clicked.connect(self.load_results)
        recent_layout.addWidget(load_button)
        from qt_result_export import export_frame
        self.export_button=QPushButton('Export spectrum CSV…')
        self.export_button.clicked.connect(lambda:export_frame(self,self.result_frame,self.status,'meep-spectrum.csv'))
        self.export_button.setEnabled(False)
        recent_layout.addWidget(self.export_button)
        store.library_changed.connect(self.refresh_recent)
        self.refresh_recent()
        store.busy_changed.connect(self._busy)
        store.progress.connect(self._progress)
        store.run_finished.connect(self._finished)
        store.run_failed.connect(self._failed)
        self._busy(store.busy)
        self._restore()
        for control in self.controls.values():
            for signal_name in ('valueChanged', 'currentIndexChanged', 'toggled'):
                signal = getattr(control, signal_name, None)
                if signal is not None:
                    signal.connect(self._invalidate_estimate)
                    break
        if hasattr(store, 'changed'):
            store.changed.connect(self._invalidate_estimate)

        if hasattr(store,'changed'):store.changed.connect(self._project_changed)
        for control in self.controls.values():
            signal=control.currentIndexChanged if isinstance(control,QComboBox) else control.toggled if isinstance(control,QCheckBox) else control.valueChanged
            signal.connect(self._save_options)
        from qt_legacy_study_workbench import StudyWorkbench
        # Retain the existing controls and result widgets; only their placement changes.
        action_layout.removeWidget(area)
        area.takeWidget()
        action_layout.insertWidget(1, left, 1)
        area.deleteLater()
        layout.removeWidget(splitter)
        self.workbench = StudyWorkbench(store, 'Time-domain optics',
            ['Domain', 'Pulse & sampling', 'Calculate'], action_panel, output,
            edit_geometry=lambda: self.routeRequested.emit('structure.original'),
            preview_note='This simulation’s optical unit cell. Lateral boundaries are periodic; PML and padding apply along the propagation direction. Normal incidence.')
        self.workbench.add_parameter_tab(recent, 'Saved runs')
        self.workbench.set_step_targets(self.input_groups)
        layout.insertWidget(0, self.workbench, 1)
        splitter.hide()
        self._clear_result()

    def _invalidate_estimate(self, *_):
        self._estimate_generation += 1
        if not self._active:
            self.timing_status.setText('Inputs changed. Estimate runtime again using matching measured data.')

    def estimate_runtime(self):
        if self._active:
            self._update_timing()
            return
        if self._estimate_worker is not None:
            return
        try:
            options = self.options()
            # Capture only the active payload, not every independent study bank.
            snapshot = getattr(self.store, '_project_payload', self.store.project)
            project = snapshot()
            self._estimate_generation += 1
            worker = RuntimeEstimateWorker(self.store.library.runs, project, options, self._estimate_generation)
            self._estimate_worker = worker
            worker.result.connect(self._estimated_runtime)
            worker.finished.connect(self._estimate_cleanup)
            worker.finished.connect(worker.deleteLater)
            self.estimate_button.setEnabled(False)
            self.timing_status.setText('Checking saved timing data…')
            worker.start()
        except Exception as exc:
            self.timing_status.setText('Could not estimate runtime: '+str(exc))

    def _estimated_runtime(self, result):
        if result.get('generation') != self._estimate_generation or self._active:
            return
        estimate = result.get('estimate')
        if result.get('error'):
            self.timing_status.setText('Could not read saved timing data: '+result['error'])
        elif estimate:
            self.timing_status.setText('Estimated configured runtime budget ~'+duration(estimate['seconds'])+
                ' from matching measured data. Decay may finish sooner; speed and setup overhead can vary.')
        else:
            self.timing_status.setText('No matching measured timing data yet. Run once to calibrate; live estimates appear after time stepping begins.')

    def _estimate_cleanup(self):
        self._estimate_worker = None
        self.estimate_button.setEnabled(True)

    def stop_runtime_estimate(self):
        """Nonblocking close guard; the caller retries after the thread exits."""
        if self._estimate_worker is not None and self._estimate_worker.isRunning():
            self._estimate_worker.requestInterruption()
            return False
        return True

    def _update_timing(self):
        if not self._active or self._run_started is None:
            return
        now = time.monotonic()
        estimate = self._live_estimate
        phase = estimate.phase
        label = (f'{phase} ({1 if phase == "Reference" else 2}/2)' if phase else 'Preparing / finalizing')
        self.timing_status.setText(label+' · elapsed '+duration(now-self._run_started)+' · '+estimate.text(now)+
            (' Device time will be estimated when it starts.' if phase == 'Reference' else ''))
        if estimate.fraction is not None and estimate.last_received is not None and now-estimate.last_received <= 10:
            self.progress.setRange(0, 100)
            self.progress.setValue(min(99, int(estimate.fraction*100)))
            self.progress.setFormat(label+' · %p% of phase time budget')
        else:
            self.progress.setRange(0, 0)

    def _stop_timing(self):
        self._timing_timer.stop()
        self._estimate_generation += 1
        if self._run_started is not None:
            self.timing_status.setText('Elapsed '+duration(time.monotonic()-self._run_started)+'. See result warnings for convergence status.')
        self._run_started = None

    def _restore(self):
        self._restoring=True
        options = self.store.search_state.get('fdtd', {})
        for key, control in self.controls.items():
            value = options.get(key, DEFAULTS[key])
            if isinstance(control, QComboBox):
                control.setCurrentIndex(max(0, control.findData(value)))
            elif isinstance(control, QCheckBox):
                control.setChecked(bool(value))
            else:
                control.setValue(float(value) if not isinstance(value, int) else value)
        self._restoring=False

    def _project_changed(self,reason):
        if reason in ('project','study'):self._restore()

    def _save_options(self,*_):
        if self._restoring:return
        if not hasattr(self.store,'save_search'):return
        if getattr(self.store,'study_navigation_enabled',False) and self.store.active_study!='fdtd':return
        try:self.store.save_search('fdtd',self.options())
        except ValueError:pass

    def apply_setup_preset(self, payload):
        """Import the selected solver's options without copying geometry or S4."""
        if self.store.busy or (getattr(self.store,'study_navigation_enabled',False) and self.store.active_study!='fdtd'):
            raise ValueError('Open the idle Meep study before importing its setup.')
        from optical_ui_scope import meep_preset_options
        options=meep_preset_options(payload)
        self.store.save_search('fdtd',options)
        self._restore()
        self.status.setText('Meep setup imported. This study’s geometry and other solver settings were retained.')
        return options

    def load_setup_preset(self):
        filename,_=QFileDialog.getOpenFileName(self,'Load Meep setup','','Simulation setup (*.json)')
        if not filename:return
        try:
            self.apply_setup_preset(json.loads(Path(filename).read_text(encoding='utf-8')))
        except (ValueError,TypeError,KeyError,OSError) as exc:
            self.status.setText('Could not load Meep setup: '+str(exc))

    def save_setup_preset(self):
        try:
            options=self.options()
            filename,_=QFileDialog.getSaveFileName(self,'Save Meep setup','meep-setup.json','Simulation setup (*.json)')
            if not filename:return
            payload=dict(schema_version=1,kind='ods_simulation_setup',scope='optical',fdtd=options,
                         values={'ui.optical.engine':'meep'})
            Path(filename).write_text(json.dumps(payload,indent=2),encoding='utf-8')
            self.status.setText('Saved Meep parameters. Save project to include device geometry and materials.')
        except (ValueError,TypeError,KeyError,OSError) as exc:
            self.status.setText('Could not save Meep setup: '+str(exc))

    def options(self):
        return validate_options({key: control.currentData() if isinstance(control, QComboBox)
            else control.isChecked() if isinstance(control, QCheckBox) else control.value()
            for key, control in self.controls.items()})

    def run(self):
        try:
            self._active = True
            self._estimate_generation += 1
            self._run_started = time.monotonic()
            self._live_estimate = PhaseEstimate()
            self._timing_timer.start()
            self._update_timing()
            self.store.start_run('fdtd', self.options())
            self.progress.setRange(0, 0)
            self.progress.show()
            self.status.setText('Validating structure, materials and Meep runtime…')
        except Exception as exc:
            self._failed(str(exc))

    def _busy(self, busy):
        self.start_button.setEnabled(not busy and self._runtime_available is not False)
        self.stop_button.setEnabled(busy and self._active)
        self._refresh_exterior()

    def _refresh_exterior(self, *_):
        if not hasattr(self.store, 'materials') or not hasattr(self.store, 'layers') or len(self.store.layers) < 2:
            self.exterior_group.setEnabled(False)
            return
        current = not getattr(self.store, 'study_navigation_enabled', False) or self.store.active_study == 'fdtd'
        self.exterior_group.setEnabled(current and not self.store.busy)
        if not current:
            return
        names = list(self.store.materials['Name'])
        for side, control in self.exterior_controls.items():
            with QSignalBlocker(control):
                selected = self.store.layers.iloc[0 if side == 'incident' else -1]['Material']
                control.clear()
                for name in names:
                    control.addItem(name, name)
                control.setCurrentIndex(control.findData(selected))

    def _set_exterior(self, side):
        if self.store.busy or (getattr(self.store, 'study_navigation_enabled', False) and self.store.active_study != 'fdtd'):
            return
        material = self.exterior_controls[side].currentData()
        if material is None:
            return
        try:
            self.store.set_optical_exterior_material(side, material)
        except Exception as exc:
            self.status.setText('Could not change Meep exterior medium: '+str(exc))
            self._refresh_exterior()

    def refresh_runtime(self, result):
        """Receive verified setup results without importing Meep in the GUI."""
        self._invalidate_estimate()
        self._runtime_available = bool(result.get('available'))
        if not self._active:
            self.status.setText(result.get('message') or ('MEEP is ready.' if self._runtime_available else 'Install or configure the FDTD engine in Settings → Add-ons.'))
        self._busy(self.store.busy)

    def _progress(self, info):
        if info.get('run_kind') == 'fdtd':
            if self._active:
                if info.get('phase') and info.get('kind') != 'phase_complete':
                    self._live_estimate.update(info, time.monotonic())
                else:
                    self._live_estimate = PhaseEstimate()
                self._update_timing()
            message = info.get('message', 'Running Meep…')
            self.status.setText(message)
            self.log.appendPlainText(message)

    def _failed(self, message):
        if self._active:
            self._stop_timing()
            self._active = False
            self.progress.hide()
            self.status.setText(message)
            self.log.appendPlainText(message)

    def _finished(self, event):
        if event.get('run_kind') != 'fdtd':
            return
        self._stop_timing()
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

    def refresh_recent(self):
        self.recent_runs.clear()
        for record in self.store.library.entries():
            if record.get('engine')!='Meep':continue
            item=QListWidgetItem(str(record.get('created',''))[:16]+' · '+str(record.get('status','saved')))
            item.setData(Qt.ItemDataRole.UserRole,record['id']);self.recent_runs.addItem(item)

    def load_recent(self):
        item=self.recent_runs.currentItem()
        if item is None:return
        try:
            directory=self.store.library.directory(item.data(Qt.ItemDataRole.UserRole))
            self._display_result(dict(directory=str(directory),output=str(directory/'results.csv'),loaded=True))
        except Exception as exc:self.status.setText(str(exc))

    def restore_recent_setup(self):
        if self.store.busy:return
        item=self.recent_runs.currentItem()
        if item is None:return
        try:
            project,search=self.store.library.project_for(item.data(Qt.ItemDataRole.UserRole),0)
            if search:project['search']=search
            self.store.replace_active_study(project);self._restore()
            self.status.setText('Setup loaded')
        except Exception as exc:self.status.setText('Could not load setup: '+str(exc))

    def update_peak(self, *_):
        from qt_compute import highest_sample_index, spectrum_figure
        frame = self.result_frame
        key = self.peak_quantity.currentData()
        name = self.peak_quantity.currentText().lower()
        self.plot.draw_figure(spectrum_figure(frame, title='MEEP · normalized optical response', peak_key=key))
        self.samples.clearSelection()
        position = highest_sample_index(frame, key)
        if position is None:
            for value in self.power_values.values():value.setText('—')
            self.peak_summary.setText(f'No finite {name} samples are available in the displayed data.')
            return
        best = frame.iloc[position]
        for metric,label in self.power_values.items():
            value=pd.to_numeric(best.get(metric),errors='coerce')
            label.setText(f'{value:.4f}' if pd.notna(value) and np.isfinite(value) else '—')
        wavelength = pd.to_numeric(best.get('wavelength_nm'), errors='coerce')
        location = f' at {wavelength:.8g} nm' if pd.notna(wavelength) and np.isfinite(wavelength) else ''
        self.peak_summary.setText(f'Highest sampled {name}: {100 * float(best[key]):.7g}%{location} (sample {position + 1}).')
        self.samples.selectRow(position)

    def _clear_result(self):
        self.directory = None
        self.result_frame = pd.DataFrame()
        self.samples.clear()
        self.samples.setRowCount(0)
        self.samples.setColumnCount(0)
        self.plot.clear()
        self.field_plot.clear()
        for value in self.power_values.values():
            value.setText('—')
        self.peak_summary.setText('No Meep result data is loaded.')
        self.peak_quantity.setEnabled(False)
        self.export_button.setEnabled(False)

    def _display_result(self, event):
        self._clear_result()
        self.workbench.show_results()
        try:
            directory = Path(event['directory'])
            frame = pd.read_csv(Path(event.get('output') or directory/'results.csv'))
            if frame.empty or 'wavelength_nm' not in frame or not {'R', 'T', 'A'}.intersection(frame.columns):
                raise ValueError('Expected wavelength_nm and at least one R, T or A column with saved samples.')
            info = event.get('info', {})
            figure = None
            field_path = directory/'fdtd_fields.npz'
            if field_path.exists():
                from matplotlib.figure import Figure
                with np.load(field_path, allow_pickle=False) as data:
                    figure = Figure(layout='constrained')
                    axis = figure.add_subplot(111)
                    image = axis.pcolormesh(data['x_um'], data['depth_um'], abs(data['field']).T**2, shading='auto', cmap='turbo')
                    axis.set_aspect('equal',adjustable='box')
                    figure.colorbar(image, ax=axis, label='Raw |DFT E|² (not incident-normalized)')
                    axis.set(xlabel='x (µm)', ylabel='Depth from stack centre (µm)', title=f'XZ · {float(data["wavelength_nm"]):g} nm')
                    axis.invert_yaxis()
            self.directory = directory
            self.result_frame = frame
            fill_table(self.samples, frame)
            self.update_peak()
            if figure is not None:
                self.field_plot.draw_figure(figure)
            self.peak_quantity.setEnabled(True)
            self.export_button.setEnabled(True)
            self.log.appendPlainText(json.dumps(info, indent=2))
            warnings=info.get('warnings', [])
            self.status.setText(('Saved simulation loaded. ' if event.get('loaded') else 'Completed. ') +
                                ('Warnings: ' + ' '.join(warnings) if warnings else ''))
            return True
        except Exception as exc:
            self._clear_result()
            self.status.setText(('Could not load saved Meep results: ' if event.get('loaded')
                                else 'Could not display Meep results: ')+str(exc))
            return False

    def open_results(self):
        if self.directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory)))
