"""Native simulation, inverse design, electric-field and runtime pages."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, QSignalBlocker, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget, QListWidget, QListWidgetItem)

from model import MODES
from peak_optimizer import SEARCH_KEYS, SEARCH_DEFAULTS
from ml_optimizer import ML_KEYS, ML_DEFAULTS, MODES as SEARCH_MODES
from qt_common import PlotWidget, number, integer, table, fill_table
from qt_ranges import BoundsEditor, HoleEditor, _choices


def _label(text, muted=False):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if muted:
        widget.setObjectName('muted')
    return widget


def _combo(values, current=None):
    widget = QComboBox()
    _choices(widget, [(v, v) if isinstance(v, str) else v for v in values], current)
    return widget


def _check(text, checked=True):
    widget = QCheckBox(text)
    widget.setChecked(checked)
    return widget


def _button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.setProperty('primary', primary)
    widget.clicked.connect(callback)
    return widget


def _value(widget):
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QComboBox):
        return widget.currentData()
    if isinstance(widget, QLineEdit):
        return widget.text()
    return widget.value()


def _set_value(widget, value):
    with QSignalBlocker(widget):
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QComboBox):
            index = widget.findData(value)
            if index >= 0:
                widget.setCurrentIndex(index)
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value or ''))
        else:
            widget.setValue(value)


def _on_edit(widget, callback):
    if isinstance(widget, QComboBox):
        widget.currentIndexChanged.connect(callback)
    elif isinstance(widget, QCheckBox):
        widget.toggled.connect(callback)
    else:
        widget.editingFinished.connect(callback)


def _group(title, pairs=()):
    box = QGroupBox(title)
    layout = QFormLayout(box)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    layout.setHorizontalSpacing(12)
    layout.setVerticalSpacing(8)
    for label, widget in pairs:
        layout.addRow(label, widget)
    return box, layout


def _scroll(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(widget)
    return area


class _ResponsiveSplitter(QSplitter):
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.count() not in (2, 3):
            return
        orientation=Qt.Orientation.Horizontal if self.width()>=980 else Qt.Orientation.Vertical
        if orientation!=self.orientation():
            self.setOrientation(orientation)
            vertical=orientation==Qt.Orientation.Vertical
            self.widget(0).setMinimumHeight(240 if vertical else 0)
            self.widget(1).setMinimumHeight(330 if vertical else 0)
            self.setSizes(([350,430] if vertical else [300,750]) if self.count() == 2 else
                          ([300,430,220] if vertical else [280,660,220]))


def _split(left, right, actions=None):
    splitter = _ResponsiveSplitter(Qt.Orientation.Horizontal)
    left.setMinimumWidth(260)
    if actions is None:
        splitter.addWidget(_scroll(left))
    else:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_scroll(left), 1)
        layout.addWidget(actions)
        splitter.addWidget(panel)
    splitter.addWidget(right)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)
    splitter.setSizes([300, 750])
    splitter.setChildrenCollapsible(False)
    return splitter


def _directory(event):
    if event.get('directory'):
        return Path(event['directory'])
    if event.get('output'):
        return Path(event['output']).parent
    return None


def _read_csv(path):
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def highest_sample_index(frame, key):
    """Return the first finite maximum's row position, independent of index labels."""
    if frame.empty or key not in frame:
        return None
    values = pd.to_numeric(frame[key], errors='coerce').to_numpy(dtype=float)
    valid = np.isfinite(values)
    if not valid.any():
        return None
    return int(np.argmax(np.where(valid, values, -np.inf)))


def spectrum_figure(frame, *, threshold=None, title='Optical response', peak_key='A'):
    figure = Figure(figsize=(8, 5), layout='constrained')
    axis = figure.add_subplot(111)
    if frame.empty:
        axis.text(.5, .5, 'No spectrum is available for this result.', ha='center', va='center', transform=axis.transAxes)
        axis.set_axis_off()
        return figure
    variable = 'angle_deg' if 'angle_deg' in frame and frame['angle_deg'].nunique() > 1 else 'wavelength_nm'
    if variable not in frame:
        axis.text(.5, .5, 'This result does not include a spectral axis.', ha='center', transform=axis.transAxes)
        return figure
    for key, name, color in [('A', 'Absorption', '#00b99f'), ('R', 'Reflection', '#5487ec'), ('T', 'Transmission', '#e3a650')]:
        if key in frame:
            axis.plot(frame[variable], frame[key], label=name, color=color, linewidth=1.8)
    position = highest_sample_index(frame, peak_key)
    if position is not None:
        best = frame.iloc[position]
        axis.scatter([best[variable]], [best[peak_key]], color='#e8748b', s=45, zorder=5, label=f'Highest sampled {peak_key}')
    if threshold is not None:
        axis.axhline(threshold, color='#929cab', linestyle='--', linewidth=1, label=f'Acceptance > {100 * threshold:g}%')
    axis.set(xlabel='Incidence angle (degrees)' if variable == 'angle_deg' else 'Wavelength (nm)',
             ylabel='Fraction of incident power', title=title)
    axis.grid(alpha=.22)
    axis.legend(loc='best')
    return figure


def field_figure(directory, component='E2', arrows=True, logarithmic=False):
    """Render saved native samples without a browser or a new solver calculation."""
    directory = Path(directory)
    frame = _read_csv(directory / 'electric_fields.csv')
    figure = Figure(figsize=(11, 5), layout='constrained')
    axes = figure.subplots(1, 2)
    model = {}
    snapshot = directory / 'field_model.json'
    wavelength = None
    if snapshot.is_file():
        saved = json.loads(snapshot.read_text(encoding='utf-8'))
        model = saved.get('model', {})
        wavelength = saved.get('wavelength_nm')
    if component != 'E2' and not frame.empty:
        frame = frame.copy()
        frame[component] = frame[component + '_real'] ** 2 + frame[component + '_imag'] ** 2
    for axis, plane, vertical, vector in ((axes[0], 'xy', 'y_um', ('Ex_real', 'Ey_real')),
                                          (axes[1], 'xz', 'z_um', ('Ex_real', 'Ez_real'))):
        data = frame[frame.plane == plane] if 'plane' in frame else pd.DataFrame()
        if data.empty:
            axis.text(.5, .5, 'No samples in this plane', ha='center', va='center', transform=axis.transAxes)
            axis.set_axis_off()
            continue
        grid = data.pivot(index=vertical, columns='x_um', values=component).sort_index()
        values = grid.to_numpy()
        if logarithmic:
            values = np.log10(np.maximum(values, 1e-16))
        image = axis.pcolormesh(grid.columns, grid.index, values, shading='nearest', cmap='turbo')
        label = '|E|² / incident |E|²' if component == 'E2' else f'|{component}|² / incident |E|²'
        figure.colorbar(image, ax=axis, label=('log₁₀ ' if logarithmic else '') + label)
        if arrows and all(key in data for key in vector):
            selected = data.iloc[::max(1, len(data) // 140)]
            axis.quiver(selected.x_um, selected[vertical], selected[vector[0]], selected[vector[1]], color='black', alpha=.65)
        axis.set(xlabel='x (µm)', ylabel=vertical.replace('_um', ' (µm)'),
                 title='XY · layer midplane' if plane == 'xy' else 'XZ · y = 0')
        if plane == 'xy':
            from matplotlib.patches import Circle, Ellipse, Rectangle
            for region in model.get('patterns', []):
                if region['layer'] not in set(data.layer):
                    continue
                center = (region['cx'], region['cy'])
                style = dict(fill=False, edgecolor='white', linewidth=1.3)
                if region['shape'] == 'circle':
                    outline = Circle(center, region['sx'], **style)
                elif region['shape'] == 'ellipse':
                    outline = Ellipse(center, 2 * region['sx'], 2 * region['sy'], angle=region['angle'], **style)
                else:
                    outline = Rectangle((center[0] - region['sx'] / 2, center[1] - region['sy'] / 2), region['sx'], region['sy'],
                        angle=region['angle'], rotation_point='center', **style)
                axis.add_patch(outline)
        else:
            depth = 0.
            for layer in model.get('layers', [])[1:-1]:
                axis.axhline(depth, color='white', alpha=.65, linewidth=.7)
                depth += layer['thickness']
            axis.axhline(depth, color='white', alpha=.65, linewidth=.7)
            axis.invert_yaxis()
    if wavelength is not None:
        layers = ', '.join(str(value) for value in frame.loc[frame.plane == 'xy', 'layer'].unique()) if 'plane' in frame and 'layer' in frame else ''
        figure.suptitle(f'Fields at {float(wavelength):g} nm' + (f' · top view in {layers}' if layers else ''))
    return figure


class _RunPage(QWidget):
    def __init__(self, store, title, subtitle, kinds, parent=None):
        super().__init__(parent)
        self.setObjectName('page')
        self.store, self.kinds = store, set(kinds)
        self.directory = None
        self._active = None
        self.layout_ = QVBoxLayout(self)
        heading = _label(title)
        heading.setObjectName('pageTitle')
        self.layout_.addWidget(heading)
        self.layout_.addWidget(_label(subtitle, True))
        self.status = _label('Ready. Calculations use the applied Structure and current solver settings.')
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.starts = []
        self.stops = []
        store.busy_changed.connect(self._busy)
        store.progress.connect(self._progress)
        store.run_finished.connect(self._finished)
        store.run_failed.connect(self._failed)

    def actions(self, text, callback):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        start = _button(text, callback, True)
        stop = _button('Stop', self._cancel)
        self.starts.append(start)
        self.stops.append(stop)
        layout.addWidget(start, 1)
        layout.addWidget(stop)
        self._busy(self.store.busy)
        return widget

    def _cancel(self):
        try:
            self.store.cancel()
            self.status.setText('Cancellation requested; waiting for native workers to stop.')
        except Exception as exc:
            self.status.setText(f'Could not request cancellation: {exc}')

    def footer(self):
        self.layout_.addWidget(self.progress_bar)
        self.layout_.addWidget(self.status)

    def _busy(self, busy):
        for widget in self.starts:
            widget.setEnabled(not busy)
        for widget in self.stops:
            widget.setEnabled(busy)

    def _start(self, kind, options):
        self._active = kind
        self.status.setText('Preparing calculation…')
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        try:
            self.store.start_run(kind, options)
        except Exception as exc:
            self._failed(str(exc))

    def _progress(self, event):
        if event.get('run_kind') not in self.kinds:
            return
        self._active = event.get('run_kind')
        self.progress_bar.show()
        text = event.get('text') or event.get('message') or 'Calculating…'
        if 'design' in event:
            text = f"Design {event['design']} / {event.get('total', '?')} · {text}"
        if 'points' in event:
            text += f" · {event['points']:,} spectral points"
        self.status.setText(str(text))
        total = event.get('total')
        done = event.get('completed', event.get('done', event.get('design')))
        if isinstance(total, (int, float)) and total > 0 and isinstance(done, (int, float)):
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(min(100, int(100 * done / total)))

    def _finished(self, event):
        if event.get('run_kind') not in self.kinds:
            return
        self._active = None
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self.directory = _directory(event)
        try:
            self.show_result(event)
        except Exception as exc:
            self.status.setText(f'Calculation finished; result display failed: {exc}. Saved files: {self.directory}')

    def _failed(self, message):
        if self._active is not None:
            self.status.setText(str(message))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.hide()
            self._active = None

    def open_results(self):
        if self.directory and self.directory.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory)))


class SimulationPage(_RunPage):
    def __init__(self, store, parent=None):
        super().__init__(store, 'Simulation', 'Sweep wavelength or incidence angle and inspect absorption, reflection and transmission.', {'simulation'}, parent)
        left, right = QWidget(), QWidget()
        controls, output = QVBoxLayout(left), QVBoxLayout(right)
        self.controls = {
            'mode': _combo(['Wavelength sweep', 'Angle sweep']),
            'wl_start_nm': number(1515, .000001), 'wl_stop_nm': number(1555, .000001),
            'wl_step_nm': number(.1, .000001), 'fixed_wl_nm': number(1550, .000001),
            'theta_deg': number(0, -89.999999, 89.999999), 'phi_deg': number(0, -360, 360),
            'angle_start': number(0, -89.999999, 89.999999), 'angle_stop': number(60, -89.999999, 89.999999),
            'angle_step': number(2, .000001, 179.999999), 'polarization': _combo([('p · TM', 'p'), ('s · TE', 's'), ('45° · s + p', '45° s+p')]),
        }
        sweep, form = _group('Sweep', [('Variable', self.controls['mode'])])
        self.wavelength_box, _ = _group('Wavelength range', [(label, self.controls[key]) for label, key in
            [('Start (nm)', 'wl_start_nm'), ('Stop (nm)', 'wl_stop_nm'), ('Step (nm)', 'wl_step_nm')]])
        self.angle_box, _ = _group('Angle range', [(label, self.controls[key]) for label, key in
            [('Wavelength (nm)', 'fixed_wl_nm'), ('Start (degrees)', 'angle_start'), ('Stop (degrees)', 'angle_stop'), ('Step (degrees)', 'angle_step')]])
        excitation, _ = _group('Incident light', [('Polarization', self.controls['polarization']),
            ('Fixed angle θ (degrees)', self.controls['theta_deg']), ('Azimuth φ (degrees)', self.controls['phi_deg'])])
        controls.addWidget(sweep)
        controls.addWidget(self.wavelength_box)
        controls.addWidget(self.angle_box)
        controls.addWidget(excitation)
        controls.addWidget(_label('The Fourier basis and CPU/GPU settings are shared through Settings. All completed samples are saved in the data library.', True))
        run_actions = self.actions('Run simulation', self.run)
        controls.addStretch()
        overview = QGroupBox('Results overview')
        overview_layout = QHBoxLayout(overview)
        self.power_values = {}
        for key, label in [('R', 'Reflectance'), ('T', 'Transmittance'), ('A', 'Absorptance')]:
            card, card_layout = _group(label)
            value = _label('—')
            value.setObjectName('pageTitle')
            card_layout.addRow(value)
            overview_layout.addWidget(card, 1)
            self.power_values[key] = value
        output.addWidget(overview)
        self.result_frame = pd.DataFrame()
        self.peak_quantity = _combo([('Reflection', 'R'), ('Transmission', 'T'), ('Absorption', 'A')], 'A')
        self.peak_summary = _label('Run a simulation or load a recent run to inspect its highest sample.')
        peak_box, peak_form = _group('Highest sampled point', [('Find maximum of', self.peak_quantity)])
        peak_form.addRow(self.peak_summary)
        peak_form.addRow(_label('Uses the displayed simulation data. Change this selection at any time. Ties use the first sample.', True))
        output.addWidget(peak_box)
        self.peak_quantity.currentIndexChanged.connect(self.update_peak)
        self.plot = PlotWidget()
        self.plot.setMinimumHeight(380)
        self.results = table([])
        tabs = QTabWidget()
        tabs.addTab(self.plot, 'Spectrum')
        tabs.addTab(self.results, 'All samples')
        output.addWidget(tabs, 1)
        self.metrics = _label('Run a simulation to see sample counts and GPU activity.')
        output.addWidget(self.metrics)
        output.addWidget(_button('Open saved result files', self.open_results))
        panels = _split(left, right, run_actions)
        recent = QGroupBox('Recent runs')
        recent_layout = QVBoxLayout(recent)
        self.recent_runs = QListWidget()
        self.recent_runs.setMinimumWidth(150)
        recent_layout.addWidget(self.recent_runs)
        recent_layout.addWidget(_button('Load selected run', self.load_recent))
        recent_layout.addWidget(_button('View saved files', self.open_recent))
        panels.addWidget(recent)
        panels.setSizes([280, 650, 190])
        self.layout_.addWidget(panels, 1)
        store.library_changed.connect(self.refresh_recent)
        self.refresh_recent()
        self.footer()
        for widget in self.controls.values():
            _on_edit(widget, self.save_settings)
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        for key, widget in self.controls.items():
            if key in self.store.settings:
                _set_value(widget, self.store.settings[key])
        self._mode()

    def _mode(self):
        wavelength = self.controls['mode'].currentData() == 'Wavelength sweep'
        self.wavelength_box.setVisible(wavelength)
        self.angle_box.setVisible(not wavelength)
        self.controls['theta_deg'].setEnabled(wavelength)

    def save_settings(self, *_):
        try:
            self.store.update_settings({key: _value(widget) for key, widget in self.controls.items()})
        except Exception as exc:
            self.status.setText(f'Could not apply simulation settings: {exc}')
            return False
        self._mode()
        return True

    def run(self):
        if self.save_settings():
            self._start('simulation', {})

    def refresh_recent(self):
        self.recent_runs.clear()
        for record in self.store.library.entries():
            if record.get('kind') != 'simulation':
                continue
            item = QListWidgetItem(str(record.get('title', 'Simulation')) + '\n' +
                str(record.get('created', ''))[:16] + ' · ' + str(record.get('status', 'saved')))
            item.setData(Qt.ItemDataRole.UserRole, record['id'])
            self.recent_runs.addItem(item)
            if self.recent_runs.count() >= 12:
                break
        if not self.recent_runs.count():
            item = QListWidgetItem('No saved simulations yet')
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent_runs.addItem(item)

    def open_recent(self):
        item = self.recent_runs.currentItem()
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return
        try:
            directory = self.store.library.directory(item.data(Qt.ItemDataRole.UserRole))
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def load_recent(self):
        item = self.recent_runs.currentItem()
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return
        try:
            directory = self.store.library.directory(item.data(Qt.ItemDataRole.UserRole))
            frame = _read_csv(Path(directory) / 'results.csv')
            self.directory = Path(directory)
            self.result_frame = frame
            fill_table(self.results, frame)
            self.update_peak()
            self.metrics.setText(f'{len(frame):,} saved samples loaded.')
            self.status.setText(f'Loaded saved simulation: {directory}')
        except (OSError, ValueError) as exc:
            self.status.setText(f'Could not load saved simulation: {exc}')

    def update_peak(self, *_):
        frame = self.result_frame
        key = self.peak_quantity.currentData()
        name = self.peak_quantity.currentText().lower()
        self.plot.draw_figure(spectrum_figure(frame, peak_key=key))
        self.results.clearSelection()
        for value in self.power_values.values():
            value.setText('—')
            value.setToolTip('')
        position = highest_sample_index(frame, key)
        if position is None:
            self.peak_summary.setText(f'No finite {name} samples are available in the displayed data.')
            return
        best = frame.iloc[position]
        coordinates = []
        for column, unit in [('wavelength_nm', 'nm'), ('angle_deg', '°')]:
            value = pd.to_numeric(best.get(column), errors='coerce')
            if pd.notna(value) and np.isfinite(value):
                coordinates.append(f'{value:.8g} {unit}')
        location = ' at ' + ', '.join(coordinates) if coordinates else ''
        self.peak_summary.setText(f'Highest sampled {name}: {100 * float(best[key]):.7g}%{location} (sample {position + 1}).')
        for quantity, label in self.power_values.items():
            value = pd.to_numeric(best.get(quantity), errors='coerce')
            label.setText(f'{value:.4f}' if pd.notna(value) and np.isfinite(value) else '—')
            label.setToolTip(f'Value at the highest sampled {name} point.')
        self.results.selectRow(position)

    def show_result(self, event):
        frame = _read_csv(Path(event.get('output') or self.directory / 'results.csv'))
        self.result_frame = frame
        fill_table(self.results, frame)
        self.update_peak()
        self.plot.figure.savefig(self.directory / 'spectrum.png', dpi=160)
        parts = [f'{len(frame):,} samples saved.']
        from gpu_status import acceleration_summary
        info = event.get('info', {})
        parts.append(acceleration_summary(info))
        self.metrics.setText(' '.join(parts))
        self.status.setText('Completed. ' + ' '.join(info.get('warnings', [])) + f' Saved to {self.directory}')


class OptimizePage(_RunPage):
    def __init__(self, store, parent=None):
        super().__init__(store, 'Optimize', 'Find the highest verified Q at your target, or explore all absorption peaks within a wavelength range.', {'target', 'peaks'}, parent)
        self.result_directories = {}
        self._restored = {}
        self._loading = True
        self.tabs = QTabWidget()
        self.target_page = self._target_page()
        self.general_page = self._general_page()
        self.tabs.addTab(self.target_page, 'Target wavelength')
        self.tabs.addTab(self.general_page, 'Explore designs')
        self.layout_.addWidget(self.tabs, 1)
        self.footer()
        self._target_defaults = {key: _value(widget) for key, widget in self.target_controls.items()}
        self._search_defaults = {key: _value(widget) for key, widget in self.search_controls.items()}
        for widget in self.target_controls.values():
            _on_edit(widget, lambda: self.persist_setup('target'))
        for widget in self.search_controls.values():
            _on_edit(widget, lambda: self.persist_setup('peaks'))
        self.resume_file.editingFinished.connect(lambda: self.persist_setup('peaks'))
        self.holes.changed.connect(lambda: self.persist_setup('target'))
        self.target_bounds.changed.connect(lambda: self.persist_setup('target'))
        self.bounds.changed.connect(lambda: self.persist_setup('peaks'))
        store.changed.connect(self.restore_saved)
        self.restore_saved()
        self._loading = False

    def _target_page(self):
        left, right = QWidget(), QWidget()
        controls, output = QVBoxLayout(left), QVBoxLayout(right)
        self.target_controls = {
            'target_nm': number(1550, .000001), 'tolerance_nm': number(5, .000001), 'min_q': number(1000, 1, 1e12, 2),
            'half_window': number(20, .000001), 'step': number(.2, .000001), 'grid_steps': integer(21, 2, 101),
            'trials': integer(40, 2, 10000), 'initial': integer(8, 2, 10000), 'finalists': integer(3, 1, 10),
            'reuse': _check('Learn from compatible saved spectra and fields'), 'history': integer(300, 1, 2000),
            'use_fields': _check('Use electric-field information during learning'),
            'field_grid': integer(6, 3, 30), 'map_grid': integer(25, 3, 80),
            'track_resonance': _check('Track fields at both the target and moving resonance'),
        }
        goal, _ = _group('Design goal', [(label, self.target_controls[key]) for label, key in
            [('Target wavelength (nm)', 'target_nm'), ('Tolerance ± (nm)', 'tolerance_nm'), ('Minimum Q factor', 'min_q')]])
        controls.addWidget(goal)
        controls.addWidget(_label('Acceptance requires absorption > 99%, a resolved peak within your tolerance, and agreement at two solver resolutions. Circle r/a must stay below 0.6; every hole must retain a bridge.', True))
        self.holes = HoleEditor(self.store)
        self.target_bounds = BoundsEditor(self.store, allowed={'lattice_square', 'lattice_x', 'lattice_y', 'thickness', 'layer_material'})
        range_tabs = QTabWidget()
        range_tabs.addTab(self.holes, 'PCS hole limits')
        range_tabs.addTab(self.target_bounds, 'Other parameters')
        controls.addWidget(range_tabs)
        learning, form = _group('Search budget', [('New designs', self.target_controls['trials'])])
        form.addRow(self.target_controls['reuse'])
        form.addRow(self.target_controls['use_fields'])
        controls.addWidget(learning)
        advanced = QTabWidget()
        sampling, _ = _group('Sampling and verification', [(label, self.target_controls[key]) for label, key in
            [('Window: target ± (nm)', 'half_window'), ('Initial wavelength step (nm)', 'step'), ('Sizes per range', 'grid_steps'),
             ('Initial designs', 'initial'), ('Finalists to verify', 'finalists')]])
        field_options, form = _group('Training data', [(label, self.target_controls[key]) for label, key in
            [('Saved observations to reuse', 'history'), ('Training grid per axis', 'field_grid'), ('Final map grid per axis', 'map_grid')]])
        form.addRow(self.target_controls['track_resonance'])
        advanced.addTab(sampling, 'Sampling')
        advanced.addTab(field_options, 'Learning detail')
        controls.addWidget(advanced)
        run_actions = self.actions('Find maximum-Q design', self.run_target)
        controls.addWidget(self._setup_actions('target'))
        controls.addStretch()
        self.target_summary = _label('The recommended design will appear here after verification.')
        output.addWidget(self.target_summary)
        self.target_plot = PlotWidget()
        self.target_plot.setMinimumHeight(400)
        self.target_results = table([])
        result_tabs = QTabWidget()
        result_tabs.addTab(self.target_plot, 'Recommended fields')
        result_tabs.addTab(self.target_results, 'Designs and conditions')
        output.addWidget(result_tabs, 1)
        self.apply_target = _button('Use verified design in Structure', self.use_target, True)
        self.apply_target.setEnabled(False)
        output.addWidget(self.apply_target)
        output.addWidget(_button('Open complete target-search files', lambda: self.open_kind('target')))
        output.addWidget(_label('Results report the best verified design found in this finite search. Full saved files contain every evaluation, spectrum, design condition and field sample.', True))
        self.target_controls['use_fields'].toggled.connect(self._target_enabling)
        self.target_controls['reuse'].toggled.connect(self._target_enabling)
        self._target_enabling()
        return _split(left, right, run_actions)

    def _target_enabling(self, *_):
        fields = self.target_controls['use_fields'].isChecked()
        for key in ('field_grid', 'map_grid', 'track_resonance'):
            self.target_controls[key].setEnabled(fields)
        self.target_controls['history'].setEnabled(self.target_controls['reuse'].isChecked())

    def _general_page(self):
        left, right = QWidget(), QWidget()
        controls, output = QVBoxLayout(left), QVBoxLayout(right)
        self.search_controls = {
            'search_mode': _combo(SEARCH_MODES, 'Hybrid verified'), 'design_budget': integer(500, 1, 10000),
            'ratio_limit': number(.6, .000001, .6), 'min_bridge_um': number(0, 0),
            'separate_circles': _check('Keep circular regions separate, including periodic neighbors'),
            'absorption_target': number(.99, .99, .999999999, 9), 'tie_tolerance': number(.0001, 0, 1, 8),
            'prominence': number(.00001, 0, 1, 8), 'refinement_rounds': integer(3, 0, 6),
            'point_budget': integer(200000, 3, 2000000), 'initial_designs': integer(24, 2, 10000),
            'ml_trials': integer(60, 2, 10000), 'candidate_pool': integer(1024, 32, 10000),
            'random_seed': integer(42, 0, 2147483647), 'finalists': integer(2, 1, 10),
            'verification_basis_factor': number(1.5, 1.01, 4), 'verification_step_divisor': integer(2, 2, 10),
            'absorption_agreement': number(.001, 0, 1), 'q_agreement': number(.05, 0, 1),
            'patience': integer(0, 0, 10000),
        }
        method, _ = _group('Search method', [('Method', self.search_controls['search_mode']), ('Maximum designs', self.search_controls['design_budget'])])
        controls.addWidget(method)
        controls.addWidget(_label('Uses the wavelength range and incident-light settings in Simulation. Empty bounds evaluate the current design only.', True))
        self.bounds = BoundsEditor(self.store)
        controls.addWidget(self.bounds)
        controls.addWidget(_button('Create fixed ranges from Structure', self.bounds.populate_current))
        details = QTabWidget()
        constraints, form = _group('Acceptance and fabrication', [(label, self.search_controls[key]) for label, key in
            [('Absorption threshold (fraction)', 'absorption_target'), ('Circle r/a upper limit', 'ratio_limit'),
             ('Minimum circle gap (µm)', 'min_bridge_um'), ('Best-match tolerance (fraction)', 'tie_tolerance')]])
        form.addRow(self.search_controls['separate_circles'])
        sampling, _ = _group('Peak detection', [(label, self.search_controls[key]) for label, key in
            [('Peak prominence (fraction)', 'prominence'), ('Finer sampling rounds', 'refinement_rounds'), ('Maximum spectral points', 'point_budget')]])
        self.ml_settings, _ = _group('Learning and verification', [(label, self.search_controls[key]) for label, key in
            [('Initial designs', 'initial_designs'), ('Learning trials', 'ml_trials'), ('Candidate pool', 'candidate_pool'),
             ('Random seed', 'random_seed'), ('Finalists', 'finalists'), ('Verification basis multiplier', 'verification_basis_factor'),
             ('Verification step divisor', 'verification_step_divisor'), ('Absorption agreement', 'absorption_agreement'),
             ('Relative Q agreement', 'q_agreement'), ('No-improvement trials (0 = off)', 'patience')]])
        details.addTab(constraints, 'Constraints')
        details.addTab(sampling, 'Detection')
        details.addTab(self.ml_settings, 'Learning')
        controls.addWidget(details)
        self.resume_file = QLineEdit()
        self.resume_file.setPlaceholderText('Optional optimization_history.json')
        resume, form = _group('Continue a previous search', [('History file', self.resume_file)])
        form.addRow(_button('Choose history JSON…', self.choose_resume))
        controls.addWidget(resume)
        run_actions = self.actions('Start design search', self.run_peaks)
        controls.addWidget(self._setup_actions('peaks'))
        controls.addStretch()
        self.peak_summary = _label('Find peak locations first, then compare all designs matching the best absorption and the highest qualifying Q.')
        output.addWidget(self.peak_summary)
        self.peak_plot = PlotWidget()
        self.peak_plot.setMinimumHeight(360)
        self.peak_results, self.peak_matches, self.peak_feasible = table([]), table([]), table([])
        tabs = QTabWidget()
        tabs.addTab(self.peak_plot, 'Best spectrum')
        tabs.addTab(self.peak_feasible, 'Highest Q')
        tabs.addTab(self.peak_matches, 'Best absorption matches')
        tabs.addTab(self.peak_results, 'All designs')
        output.addWidget(tabs, 1)
        self.design = QComboBox()
        self.design.setMinimumContentsLength(16)
        self.design.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.apply_peak = _button('Use design in Structure', self.use_peak, True)
        self.apply_peak.setEnabled(False)
        row = QHBoxLayout()
        row.addWidget(self.design, 1)
        row.addWidget(self.apply_peak)
        output.addLayout(row)
        output.addWidget(_button('Open complete design-search files', lambda: self.open_kind('peaks')))
        for widget in (self.peak_results, self.peak_matches, self.peak_feasible):
            widget.itemSelectionChanged.connect(lambda current=widget: self._select_result(current))
        self.search_controls['search_mode'].currentIndexChanged.connect(self._search_enabling)
        self._search_enabling()
        return _split(left, right, run_actions)

    def _search_enabling(self, *_):
        self.ml_settings.setEnabled(self.search_controls['search_mode'].currentData() != 'Exhaustive grid')

    def target_options(self):
        return dict(holes=self.holes.records(), hole_sync=self.holes.sync_state(), bounds=self.target_bounds.records(),
                    **{key: _value(widget) for key, widget in self.target_controls.items()})

    def peak_options(self):
        return dict(bounds=self.bounds.records(), search_options={key: _value(widget) for key, widget in self.search_controls.items()},
                    resume_history_file=self.resume_file.text().strip())

    def run_target(self):
        self._start('target', self.target_options())

    def run_peaks(self):
        self._start('peaks', self.peak_options())

    def choose_resume(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Continue an optimization history', '', 'JSON files (*.json)')
        if path:
            self.resume_file.setText(path)
            self.persist_setup('peaks')

    def _setup_actions(self, kind):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_button('Save search setup…', lambda: self.save_setup(kind)))
        layout.addWidget(_button('Load setup…', lambda: self.load_setup(kind)))
        return widget

    def save_setup(self, kind):
        path, _ = QFileDialog.getSaveFileName(self, 'Save search setup', f'{kind}_setup.json', 'JSON files (*.json)')
        if not path:
            return
        try:
            options = self.target_options() if kind == 'target' else self.peak_options()
            Path(path).write_text(json.dumps({'kind': kind, 'options': options}, indent=2, allow_nan=False), encoding='utf-8')
            self.store.save_search(kind, options)
            self.status.setText(f'Search setup saved to {path}')
        except Exception as exc:
            self.status.setText(str(exc))

    def load_setup(self, kind):
        path, _ = QFileDialog.getOpenFileName(self, 'Load search setup', '', 'JSON files (*.json)')
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if data.get('kind', kind) != kind:
                raise ValueError('This setup belongs to the other search tab.')
            options = data.get('options', data)
            # Accept the browser GUI's general-search setup format as well.
            if 'bounds' in data and 'search_options' not in options and kind == 'peaks':
                options = dict(bounds=data['bounds'], search_options=data.get('options', {}))
            self._loading = True
            try:
                self._restore(kind, options)
            finally:
                self._loading = False
            self.store.save_search(kind, options)
            self.status.setText('Search setup loaded. Layer and region targets were checked against Structure.')
        except Exception as exc:
            self.status.setText(f'Could not load this setup: {exc}')

    def _restore(self, kind, options):
        if kind == 'target':
            holes = self.holes.validated_records(options.get('holes', []))
            bounds = self.target_bounds.validated_records(options.get('bounds', []))
            self.holes.set_records(holes, options.get('hole_sync'))
            self.target_bounds.set_records(bounds)
            for key, widget in self.target_controls.items():
                if key in options:
                    _set_value(widget, options[key])
            self._target_enabling()
        else:
            self.bounds.set_records(options.get('bounds', []))
            for key, widget in self.search_controls.items():
                if key in options.get('search_options', {}):
                    _set_value(widget, options['search_options'][key])
            self.resume_file.setText(options.get('resume_history_file', ''))
            self._search_enabling()

    def persist_setup(self, kind):
        if self._loading:
            return
        try:
            self.store.save_search(kind, self.target_options() if kind == 'target' else self.peak_options())
        except Exception as exc:
            self.status.setText(f'Could not save the search setup: {exc}')

    def restore_saved(self, reason=None):
        if reason not in (None, 'project'):
            return
        previous = self._loading
        self._loading = True
        try:
            for kind in ('target', 'peaks'):
                options = getattr(self.store, 'search_state', {}).get(kind)
                if not options and reason == 'project':
                    if kind == 'target':
                        from structure_sync import initial_hole_sync
                        data, state = initial_hole_sync(self.store.materials, self.store.layers, self.store.patterns)
                        options = dict(self._target_defaults, holes=data.to_dict('records'), hole_sync=state, bounds=[])
                    else:
                        options = dict(bounds=[], search_options=self._search_defaults, resume_history_file='')
                if options:
                    try:
                        self._restore(kind, options)
                    except (ValueError, TypeError, KeyError) as exc:
                        self.status.setText(f'Saved {kind} setup needs current Structure targets: {exc}')
        finally:
            self._loading = previous

    def show_result(self, event):
        kind = event['run_kind']
        self.result_directories[kind] = self.directory
        summary = event.get('summary', {})
        if kind == 'target':
            frame = _read_csv(self.directory / 'target_results.csv')
            fill_table(self.target_results, frame)
            path = self.directory / 'recommended_fields'
            if (path / 'electric_fields.csv').is_file():
                self.target_plot.draw_figure(field_figure(path))
                self.target_plot.figure.savefig(path / 'electric_field_maps.png', dpi=160)
            else:
                self.target_plot.clear()
            self.apply_target.setEnabled((self.directory / 'recommended_design.json').is_file())
            q = summary.get('maximum_verified_Q')
            message = f'Highest verified Q found: {float(q):.7g}.' if q else 'No verified design meets all requested limits yet.'
            message += f" {summary.get('new_evaluations', 0)} new evaluations; {summary.get('reused_training_records', 0)} saved spectra and {summary.get('reused_field_records', 0)} field datasets reused."
            self.target_summary.setText(message)
        else:
            frame = _read_csv(self.directory / 'design_results.csv')
            fill_table(self.peak_results, frame)
            fill_table(self.peak_matches, _read_csv(self.directory / 'matching_best.csv'))
            fill_table(self.peak_feasible, _read_csv(self.directory / 'above_target_by_Q.csv'))
            spectrum = _read_csv(self.directory / 'best_spectrum.csv')
            threshold = self.search_controls['absorption_target'].value()
            request = self.directory / 'desktop_request.json'
            if request.is_file():
                saved = json.loads(request.read_text(encoding='utf-8'))
                threshold = saved.get('options', {}).get('search_options', {}).get('absorption_target', threshold)
            self.peak_plot.draw_figure(spectrum_figure(spectrum, threshold=threshold, title='Best absorption design found'))
            self.peak_plot.figure.savefig(self.directory / 'best_spectrum.png', dpi=160)
            choices = []
            for row in frame.to_dict('records'):
                if row.get('status', 'evaluated') != 'evaluated' or pd.isna(row.get('design_id')):
                    continue
                identifier = int(row['design_id'])
                label = f'Design {identifier}'
                if pd.notna(row.get('absorption')):
                    label += f" · {100 * float(row['absorption']):.6g}%"
                if pd.notna(row.get('wavelength_nm')):
                    label += f" · {float(row['wavelength_nm']):.7g} nm"
                choices.append((label, identifier))
            _choices(self.design, choices)
            self.apply_peak.setEnabled(bool(choices))
            best = summary.get('best_absorption')
            message = f'Best absorption found: {100 * float(best):.8g}%.' if best is not None else 'No evaluated absorption peak is available.'
            message += f" {summary.get('evaluated', 0)} designs evaluated; {summary.get('matching_designs', 0)} best matches; {summary.get('above_target_designs', 0)} above threshold."
            self.peak_summary.setText(message)
        self.status.setText(f"{str(summary.get('status', 'complete')).title()}. {summary.get('reason', '')} Saved to {self.directory}")

    def _select_result(self, widget):
        headers = [widget.horizontalHeaderItem(i).text() for i in range(widget.columnCount())]
        if 'design_id' not in headers or widget.currentRow() < 0:
            return
        item = widget.item(widget.currentRow(), headers.index('design_id'))
        if item:
            try:
                index = self.design.findData(int(float(item.text())))
                if index >= 0:
                    self.design.setCurrentIndex(index)
            except ValueError:
                pass

    def use_target(self):
        path = self.result_directories.get('target')
        if path:
            try:
                self.store.apply_design(path, recommended=True)
                self.status.setText('Verified design applied to Structure. Every page now uses this design.')
            except Exception as exc:
                self.status.setText(str(exc))

    def use_peak(self):
        path = self.result_directories.get('peaks')
        identifier = self.design.currentData()
        if path and identifier is not None:
            try:
                self.store.apply_design(path, design_id=int(identifier))
                self.status.setText(f'Design {identifier} applied to Structure. Every page now uses this design.')
            except Exception as exc:
                self.status.setText(str(exc))

    def open_kind(self, kind):
        path = self.result_directories.get(kind)
        if path and path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class FieldsPage(_RunPage):
    def __init__(self, store, parent=None):
        super().__init__(store, 'Electric fields', 'Inspect optical-field concentration in each layer and compare how it moves between saved designs.', {'fields'}, parent)
        self.field_directory = None
        self.tabs = QTabWidget()
        current = QWidget()
        body = QVBoxLayout(current)
        left, center, right = QWidget(), QWidget(), QWidget()
        settings_layout, plot_layout, export_layout = QVBoxLayout(left), QVBoxLayout(center), QVBoxLayout(right)
        inputs, form = _group('Calculate current Structure')
        self.wavelength = number(1550, .000001)
        self.layer = QComboBox()
        self.grid = integer(25, 3, 80)
        form.addRow('Wavelength (nm)', self.wavelength)
        form.addRow('Layer for top view', self.layer)
        form.addRow('Map samples per axis', self.grid)
        form.addRow(self.actions('Calculate field maps', self.run))
        settings_layout.addWidget(inputs)
        self.component = _combo([('Total intensity |E|²', 'E2'), ('X component |Ex|²', 'Ex'), ('Y component |Ey|²', 'Ey'), ('Z component |Ez|²', 'Ez')])
        self.arrows = _check('Show Re(E) arrows')
        self.logarithmic = _check('Log intensity scale', False)
        display, display_form = _group('Display')
        display_form.addRow('Field component', self.component)
        display_form.addRow(self.arrows)
        display_form.addRow(self.logarithmic)
        settings_layout.addWidget(display)
        settings_layout.addStretch()
        self.plot = PlotWidget()
        plot_layout.addWidget(self.plot, 1)
        self.plot.setMinimumHeight(420)
        plot_layout.addWidget(_label('XY: selected layer midplane · XZ: y = 0. Colors show intensity relative to the incident field.', True))
        exports, export_form = _group('Export')
        export_form.addRow(_button('Save image…', self.export_image))
        export_form.addRow(_button('Export data…', self.export_data))
        export_form.addRow(_button('Copy plot', self.copy_plot))
        export_form.addRow(_button('Open saved files', self.open_results))
        export_layout.addWidget(exports)
        export_layout.addWidget(_label('Saved data includes complex field samples and the Structure used for the calculation.', True))
        export_layout.addStretch()
        panels = _split(left, center)
        panels.addWidget(right)
        panels.setSizes([280, 650, 180])
        body.addWidget(panels, 1)
        self.tabs.addTab(current, 'Current Structure')
        from qt_field_compare import FieldComparisonWidget
        self.comparison = FieldComparisonWidget(store)
        self.tabs.addTab(_scroll(self.comparison), 'Compare saved designs')
        self.layout_.addWidget(self.tabs, 1)
        self.footer()
        for widget in (self.component, self.arrows, self.logarithmic):
            _on_edit(widget, self.render_fields)
        for widget in (self.wavelength, self.layer, self.grid):
            _on_edit(widget, self.persist_options)
        store.changed.connect(self.refresh)
        self.refresh()
        saved = getattr(store, 'search_state', {}).get('fields', {})
        for key, widget in [('wavelength_nm', self.wavelength), ('layer', self.layer), ('grid', self.grid)]:
            if key in saved:
                _set_value(widget, saved[key])

    def refresh(self, reason=None):
        choices = [('Automatic · first patterned layer', '')] + [(row['Name'], row['Name']) for row in self.store.layers.to_dict('records')[1:-1]]
        _choices(self.layer, choices, self.layer.currentData())
        if reason == 'project':
            saved = getattr(self.store, 'search_state', {}).get('fields', {})
            for key, widget, default in [('wavelength_nm', self.wavelength, 1550), ('layer', self.layer, ''), ('grid', self.grid, 25)]:
                _set_value(widget, saved.get(key, default))

    def persist_options(self, *_):
        try:
            self.store.save_search('fields', self.options())
        except Exception as exc:
            self.status.setText(f'Could not save the field settings: {exc}')

    def options(self):
        return dict(wavelength_nm=self.wavelength.value(), layer=self.layer.currentData() or '', grid=self.grid.value())

    def run(self):
        self._start('fields', self.options())

    def export_image(self):
        if self.field_directory is None:
            self.status.setText('Calculate or open a field result before exporting an image.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Save field image', 'electric-field.png', 'PNG image (*.png)')
        if path:
            try:
                self.plot.figure.savefig(path, dpi=180)
                self.status.setText('Field image saved.')
            except Exception as exc:
                self.status.setText('Could not save image: ' + str(exc))

    def export_data(self):
        if self.field_directory is None:
            self.status.setText('Calculate a field result before exporting data.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export field samples', 'electric-fields.csv', 'CSV data (*.csv)')
        if path:
            try:
                import shutil
                shutil.copyfile(self.field_directory / 'electric_fields.csv', path)
                self.status.setText('Complex field samples exported.')
            except Exception as exc:
                self.status.setText('Could not export samples: ' + str(exc))

    def copy_plot(self):
        if self.field_directory is None:
            self.status.setText('Calculate a field result before copying the plot.')
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setPixmap(self.plot.canvas.grab())
        self.status.setText('Field plot copied to clipboard.')

    def render_fields(self, *_):
        if self.field_directory is None:
            return
        try:
            self.plot.draw_figure(field_figure(self.field_directory, self.component.currentData(), self.arrows.isChecked(), self.logarithmic.isChecked()))
        except Exception as exc:
            self.status.setText(f'Field display failed: {exc}')

    def show_result(self, event):
        self.field_directory = self.directory / 'fields'
        self.render_fields()
        self.plot.figure.savefig(self.field_directory / 'electric_field_maps.png', dpi=160)
        from gpu_status import acceleration_summary
        info = event.get('summary', {}).get('field_features', {}).get('acceleration', {})
        self.status.setText('Field maps and complex samples saved. ' + acceleration_summary(info) + ' ' + ' '.join(info.get('warnings', [])) + f' Saved to {self.directory}')


class SettingsPage(_RunPage):
    def __init__(self, store, parent=None):
        super().__init__(store, 'Settings', 'Customize appearance, data storage, accuracy and parallel execution.', {'diagnostic'}, parent)
        left, right = QWidget(), QWidget()
        controls, details = QVBoxLayout(left), QVBoxLayout(right)
        from desktop_runtime import default_data_directory, saved_data_directory
        self.data_directory = QLineEdit(str(saved_data_directory() or default_data_directory()))
        self.data_directory.setAccessibleName('Data output folder')
        storage, storage_form = _group('Data output folder', [('Folder for saved data', self.data_directory)])
        storage_form.addRow(_label('Current folder: ' + str(store.library.root), True))
        storage_form.addRow(_button('Browse…', self.browse_data_directory))
        storage_form.addRow(_button('Use folder beside the program', self.default_data_directory))
        storage_form.addRow(_button('Save data folder', self.save_data_directory))
        self.storage_note = _label('Changes apply after restarting. Existing data stays in its current folder. Select that folder again to reopen it, or use Saved work to export/import a backup.', True)
        storage_form.addRow(self.storage_note)
        details.addWidget(storage)
        self.basis = integer(32, 1, 4096)
        accuracy, form = _group('Accuracy', [('Fourier basis count', self.basis)])
        form.addRow(_label('Larger basis counts can resolve finer features and cost more memory and time. Check convergence before accepting a final Q estimate.', True))
        controls.addWidget(accuracy)
        cpus = os.cpu_count() or 1
        self.controls = {
            'mode': _combo(MODES), 'workers': integer(0, 0, cpus), 'threads': integer(1, 1, cpus),
            'gpu_device': integer(0, 0, 1024), 'gpu_min_n': integer(1024, 1, 2147483647),
            'gpu_block': _combo([(str(value), value) for value in (64, 128, 256, 512, 1024)], 256),
            'chunk_size': integer(8, 1, 10000), 'timeout_seconds': integer(3600, 1, 2147483647),
            'require_gpu': _check('Require successful GPU work for each calculation', False),
        }
        runtime, form = _group('Compute resources', [(label, self.controls[key]) for label, key in
            [('Execution mode', 'mode'), ('CPU workers (0 = automatic)', 'workers'), ('Threads per worker', 'threads'),
             ('CUDA device index', 'gpu_device'), ('Minimum GPU matrix size', 'gpu_min_n'), ('GPU tile size', 'gpu_block'),
             ('Wavelengths per work chunk', 'chunk_size'), ('Run timeout (seconds)', 'timeout_seconds')]])
        form.addRow(self.controls['require_gpu'])
        controls.addWidget(runtime)
        controls.addWidget(_label(f'{cpus} logical CPUs available. Worker count × threads per worker cannot exceed this count.', True))
        controls.addWidget(_button('Use GPU for small matrices', self.small_matrices))
        controls.addWidget(self.actions('Check selected runtime', self.run))
        controls.addStretch()
        self.gpu_note = _label('')
        details.addWidget(self.gpu_note)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setPlaceholderText('Run the diagnostic to see actual S4 CPU/GPU matrix-product counts and native runtime status.')
        details.addWidget(self.diagnostics, 1)
        details.addWidget(_label('GPU acceleration covers supported matrix products. S4 also uses CPU solver steps, and the ML surrogate fitting uses the CPU. A connected GPU does not imply every operation runs on it.', True))
        from qt_appearance import AppearancePage
        self.settings_tabs = QTabWidget()
        self.settings_tabs.addTab(AppearancePage(), 'Appearance')
        storage_page = QWidget()
        QVBoxLayout(storage_page).addWidget(storage)
        self.settings_tabs.addTab(storage_page, 'Data storage')
        self.settings_tabs.addTab(_split(left,right), 'Performance')
        from qt_addons import AddonsPage
        self.addons_panel = AddonsPage(store=store)
        self.settings_tabs.addTab(_scroll(self.addons_panel), 'Add-ons')
        from qt_common import theme_manager
        self.refresh_tab_icons()
        theme_manager().changed.connect(self.refresh_tab_icons)
        self.layout_.addWidget(self.settings_tabs,1)
        self.footer()
        self.basis.editingFinished.connect(self.save_settings)
        for widget in self.controls.values():
            _on_edit(widget, self.save_settings)
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh_tab_icons(self, *_):
        from qt_icons import navigation_icon
        from qt_common import COLORS, theme_manager
        for index, name in enumerate(('appearance', 'storage', 'performance', 'addons')):
            self.settings_tabs.setTabIcon(index, navigation_icon(name, COLORS[theme_manager().mode]['accent']))

    def browse_data_directory(self):
        directory = QFileDialog.getExistingDirectory(self, 'Choose data output folder', self.data_directory.text())
        if directory:
            self.data_directory.setText(directory)

    def default_data_directory(self):
        from desktop_runtime import default_data_directory
        self.data_directory.setText(str(default_data_directory()))

    def save_data_directory(self):
        from desktop_runtime import save_data_directory
        try:
            if not self.data_directory.text().strip():
                raise ValueError('Choose a folder first.')
            target = save_data_directory(self.data_directory.text().strip())
            self.storage_note.setText(f'Saved. Restart the application to use {target}. Existing data has not been moved.')
        except Exception as exc:
            self.storage_note.setText('Could not save the data folder: ' + str(exc))

    def refresh(self, *_):
        _set_value(self.basis, self.store.settings.get('NumG', 32))
        for key, widget in self.controls.items():
            if key in self.store.performance:
                _set_value(widget, self.store.performance[key])
        mode = self.controls['mode'].currentData()
        gpu = mode != MODES[0]
        for key in ('gpu_device', 'gpu_min_n', 'gpu_block', 'require_gpu'):
            self.controls[key].setEnabled(gpu)
        self.controls['workers'].setEnabled(mode != MODES[2])
        threshold = self.controls['gpu_min_n'].value()
        self.gpu_note.setText(f'Fourier basis: {self.basis.value():,}. GPU offload threshold: {threshold:,}. '
            'All dimensions of a matrix product must meet the threshold. Small structures may otherwise stay on the CPU. '
            'The runtime diagnostic uses threshold 1 to verify actual GPU work; it does not change your run threshold.')

    def save_settings(self, *_):
        # Capture both groups before either update emits the shared refresh signal.
        perf = {key: _value(widget) for key, widget in self.controls.items()}
        if perf['mode'] == MODES[0]:
            perf['require_gpu'] = False
        basis = self.basis.value()
        try:
            self.store.update_performance(perf)
            self.store.update_settings({'NumG': basis})
        except Exception as exc:
            self.status.setText(f'Could not apply solver settings: {exc}')
            return False
        return True

    def small_matrices(self):
        _set_value(self.controls['gpu_min_n'], 1)
        if self.controls['mode'].currentData() == MODES[0]:
            _set_value(self.controls['mode'], MODES[2])
        if self.save_settings():
            self.status.setText('GPU matrix threshold set to 1. This can increase GPU activity; small problems may run faster on the CPU.')

    def run(self):
        if self.save_settings():
            self._start('diagnostic', {})

    def show_result(self, event):
        info = event.get('info', event.get('summary', {}))
        self.diagnostics.setPlainText(json.dumps(info, indent=2, default=str))
        from gpu_status import runtime_check_summary
        self.status.setText(runtime_check_summary(info, self.store.performance).replace('**', ''))
