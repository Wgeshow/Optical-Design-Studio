"""Native simulation, inverse design, electric-field and runtime pages."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from PyQt6.QtCore import pyqtSignal
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter
from PyQt6.QtCore import Qt, QSignalBlocker, QUrl, QSize, QAbstractListModel, QTimer
from PyQt6.QtGui import QDesktopServices, QStandardItemModel
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget, QListWidget, QListWidgetItem)

from model import MODES, MAX_SWEEP_POINTS
from field_storage import field_data_exists, load_field_frame, export_field_csv
from peak_optimizer import SEARCH_KEYS, SEARCH_DEFAULTS
from ml_optimizer import ML_KEYS, ML_DEFAULTS, MODES as SEARCH_MODES
from qt_common import PlotWidget, ActionStatusLabel, number, integer, table, fill_table
from qt_native_plot import NativeSpectrumWidget
from qt_surfaces import WorkspacePanel
from qt_ranges import BoundsEditor, HoleEditor, _choices


class FieldSamplesModel(QAbstractListModel):
    """A virtual selector: no widget or Python record for each saved sample."""
    def __init__(self,root,parent=None):
        super().__init__(parent)
        from scan_storage import FieldSampleIndex
        from functools import lru_cache
        self.index=FieldSampleIndex(root)
        self.offset=0;self.page_size=200
        self.sample=lru_cache(maxsize=256)(self.index.sample)
        self.destroyed.connect(lambda:self.index.close())

    def rowCount(self,parent=None):
        return 0 if parent is not None and parent.isValid() else min(self.page_size,len(self.index)-self.offset)

    def set_page(self,ordinal):
        offset=(ordinal//self.page_size)*self.page_size
        if offset!=self.offset:
            self.beginResetModel();self.offset=offset;self.endResetModel()

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0<=index.row()<self.rowCount():return None
        if role not in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.UserRole):return None
        sample=self.sample(self.offset+index.row())
        if role==Qt.ItemDataRole.UserRole:return sample['directory']
        return f"{sample['wavelength_nm']:g} nm · {sample['angle_deg']:g}°"


def phase_preview(path,count=None,limit=20000,reference_path=None):
    """Unwrap every saved sample before selecting the bounded display rows."""
    from spectral_phase import read_phase_preview
    return read_phase_preview(path,count,limit,reference_path)


def _label(text, muted=False):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if muted:
        widget.setObjectName('muted')
        widget.setToolTip(text)
        widget.hide()
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
    def minimumSizeHint(self):
        if getattr(self,'vertical_minimum_sizes',None):
            # The scroll viewport chooses width before orientation. A summed
            # horizontal hint would prevent the splitter ever reaching its
            # vertical threshold when the window becomes narrow.
            return QSize(0,0)
        return super().minimumSizeHint()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.count() not in (2, 3):
            return
        orientation=Qt.Orientation.Horizontal if self.width()>=getattr(self,'responsive_breakpoint',980) else Qt.Orientation.Vertical
        if orientation!=self.orientation():
            self.setOrientation(orientation)
            vertical=orientation==Qt.Orientation.Vertical
            self.widget(0).setMinimumHeight(240 if vertical else 0)
            self.widget(1).setMinimumHeight(330 if vertical else 0)
            self.setSizes(([350,430] if vertical else [300,750]) if self.count() == 2 else
                          ([300,430,220] if vertical else [280,660,220]))
        minimums=getattr(self,'vertical_minimum_sizes',None)
        if minimums:
            vertical=orientation==Qt.Orientation.Vertical
            for index,minimum in enumerate(minimums):
                self.widget(index).setMinimumHeight(minimum if vertical else 0)
            self.setMinimumHeight(sum(minimums)+(self.count()-1)*self.handleWidth() if vertical else 0)
            if vertical and not getattr(self,'_vertical_sizes_applied',False):
                self._vertical_sizes_applied=True;self.setSizes(minimums)
            elif not vertical:self._vertical_sizes_applied=False
        if orientation==Qt.Orientation.Horizontal and abs(self.width()-getattr(self,'_last_layout_width',0))>20:
            self._last_layout_width=self.width()
            self.setSizes([round(self.width()*ratio) for ratio in getattr(self,'reference_ratios',((.27,.46,.27) if self.count()==3 else (.3,.7)))])


def _split(left, right, actions=None):
    splitter = _ResponsiveSplitter(Qt.Orientation.Horizontal)
    left.setMinimumWidth(260)
    if actions is None:
        splitter.addWidget(_scroll(left))
    else:
        panel = WorkspacePanel()
        panel.setMinimumWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_scroll(left), 1)
        layout.addWidget(actions)
        splitter.addWidget(panel)
    if isinstance(right,WorkspacePanel):
        splitter.addWidget(right)
    else:
        surface=WorkspacePanel();surface_layout=QVBoxLayout(surface)
        surface_layout.setContentsMargins(12,12,12,12);surface_layout.addWidget(right)
        splitter.addWidget(surface)
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
             ylabel='Incident power (%)', title=title,ylim=(0,1))
    axis.yaxis.set_major_formatter(PercentFormatter(xmax=1))
    axis.grid(alpha=.22)
    axis.legend(loc='best')
    return figure


def field_figure(directory, component='E2', arrows=True, logarithmic=False, amplitude=False):
    """Render saved native samples without a browser or a new solver calculation."""
    directory = Path(directory)
    frame = load_field_frame(directory) if field_data_exists(directory) else pd.DataFrame()
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
        if amplitude:values=np.sqrt(np.maximum(values,0.))
        if logarithmic:
            values = np.log10(np.maximum(values, 1e-16))
        image = axis.pcolormesh(grid.columns, grid.index, values, shading='nearest', cmap='turbo')
        label = '|E|² / incident |E|²' if component == 'E2' else f'|{component}|² / incident |E|²'
        if amplitude:label='|E| / incident |E|' if component=='E2' else f'|{component}| / incident |E|'
        figure.colorbar(image, ax=axis, label=('log₁₀ ' if logarithmic else '') + label)
        if arrows and all(key in data for key in vector):
            selected = data.iloc[::max(1, len(data) // 140)]
            axis.quiver(selected.x_um, selected[vertical], selected[vector[0]], selected[vector[1]], color='black', alpha=.65)
        axis.set(xlabel='x (µm)', ylabel=vertical.replace('_um', ' (µm)'),
                 title='XY · layer midplane' if plane == 'xy' else 'XZ · y = 0')
        axis.set_aspect('equal',adjustable='box')
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


class _StatusLabel(ActionStatusLabel):
    """Use notifications for completed actions and preserve actionable feedback."""


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
        # Navigation names the workspace; dedicate the page height to controls.
        heading.hide()
        self.layout_.addWidget(heading)
        description=_label(subtitle,True);description.hide()
        self.layout_.addWidget(description)
        self.status = _StatusLabel()
        self.status.setWordWrap(True)
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
        super().__init__(store, 'Simulation', 'Sweep wavelength or incidence angle and inspect absorption, reflection and transmission.', {'simulation','simulation_fields'}, parent)
        self.spectrum_directory=None;self.field_directory=None;self._spectrum_project=None
        self._field_display_key=None;self._fields_dirty=True
        for index in (0,1):self.layout_.itemAt(index).widget().hide()
        left, right = WorkspacePanel(), WorkspacePanel()
        controls, output = QVBoxLayout(left), QVBoxLayout(right)
        setup_title=_label('Simulation Setup');setup_title.setObjectName('sectionTitle');controls.addWidget(setup_title)
        results_title=_label('Simulation Results');results_title.setObjectName('sectionTitle');output.addWidget(results_title)
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
        self.measure_phase = _check('Measure specular reflection / transmission phase', False)
        controls.addWidget(self.measure_phase)
        controls.addWidget(_label('Phase uses the co-polarized tangential electric field at the top and bottom stack boundaries. Phase change is relative to the first valid sample; zero signals are undefined.', True))
        self.field_controls={'grid':integer(25,3,2147483647),'depth_samples':integer(3,3,2147483647),'contour_step':number(.1,.001,100,3)}
        field_box,_=_group('Electric fields with every simulation',[(label,self.field_controls[key]) for label,key in [('Field grid per axis','grid'),('Depth samples per layer','depth_samples'),('Contour amplitude step','contour_step')]])
        controls.addWidget(field_box)
        controls.addWidget(_label('Fields are calculated and saved at every wavelength / angle sample, with XY and full-stack XZ views. Finer sampling increases run time and saved data.',True))
        for widget in self.field_controls.values():_on_edit(widget,self.save_field_settings)
        # Rebuild setup as compact reference rows, rather than several stacked
        # legacy cards and explanatory paragraphs that push sampling offscreen.
        for index in range(1,controls.count()):
            widget=controls.itemAt(index).widget()
            if widget:widget.hide()
        while controls.count()>1:controls.takeAt(1)
        sweep_bar=QWidget();sweep_layout=QHBoxLayout(sweep_bar);sweep_layout.setContentsMargins(0,0,0,0)
        sweep_layout.addWidget(QLabel('Sweep'));sweep_layout.addWidget(self.controls['mode'],1)
        controls.addWidget(sweep_bar);self.controls['mode'].show()
        self.wavelength_box.setTitle('Wavelength / Angle sweep')
        controls.addWidget(self.wavelength_box);controls.addWidget(self.angle_box)
        incident_rows=QWidget();incident_form=QFormLayout(incident_rows)
        incident_form.setContentsMargins(8,0,8,0)
        for label,key in [('Polarization','polarization'),('Theta θ (degrees)','theta_deg'),('Phi φ (degrees)','phi_deg')]:
            widget=self.controls[key];incident_form.addRow(label,widget);widget.show()
        self.measure_phase.setText('Measure phase')
        incident_form.addRow(self.measure_phase);self.measure_phase.show()
        controls.addWidget(incident_rows)
        field_box.setTitle('Electric fields');field_box.show();controls.addWidget(field_box)
        field_form=field_box.layout()
        self.field_single=_check('Single wavelength',True)
        self.field_source=_combo([('Enter wavelength manually','manual'),('Maximum reflection (R)','maxR'),('Minimum reflection (R)','minR'),('Maximum transmission (T)','maxT'),('Minimum transmission (T)','minT'),('Maximum absorption (A)','maxA'),('Minimum absorption (A)','minA')])
        self.field_wavelength=number(1550,.000001);self.field_wavelength.setSuffix(' nm')
        self.field_selection=_label('Manual entry can run without a spectrum.')
        field_form.insertRow(0,self.field_single)
        field_form.insertRow(1,'Choose wavelength from',self.field_source)
        field_form.insertRow(2,'Wavelength',self.field_wavelength)
        field_form.insertRow(3,self.field_selection)
        field_form.addRow(_label('Save full 3D E/H fields across all finite layers.'))
        self.field_run=_button('Run electric fields',self.run_fields,True)
        field_form.insertRow(4,self.field_run)
        field_form.insertRow(5,_button('View saved electric fields',self.view_generated_fields))
        self.field_wavelength.valueChanged.connect(self.update_field_selection)
        for widget in (self.field_single,self.field_source,self.field_wavelength,self.measure_phase):_on_edit(widget,self.save_field_settings)
        store.busy_changed.connect(self.update_field_selection)
        run_actions = self.actions('Run spectrum', self.run)
        controls.addStretch()
        overview = QWidget()
        overview_layout = QHBoxLayout(overview)
        self.power_values = {}
        for key, label in [('R', 'Reflectance'), ('T', 'Transmittance'), ('A', 'Absorptance')]:
            card, card_layout = _group(label)
            value = _label('—')
            value.setWordWrap(False)
            value.setMinimumHeight(52)
            card.setMinimumHeight(100)
            value.setObjectName('metricValue')
            card_layout.addRow(value)
            overview_layout.addWidget(card, 1)
            self.power_values[key] = value
        output.addWidget(overview)
        self.result_frame = pd.DataFrame()
        self.spectrum_results=None
        self.phase_frame=pd.DataFrame()
        self.peak_quantity = _combo([('Reflection', 'R'), ('Transmission', 'T'), ('Absorption', 'A')], 'A')
        self.peak_summary = _label('Run a simulation or load a recent run to inspect its highest sample.')
        peak_box, peak_form = _group('Highest sampled point', [('Find maximum of', self.peak_quantity)])
        peak_form.addRow(self.peak_summary)
        self.peak_quantity.setToolTip('Find the highest calculated sample; ties use the first sample.')
        output.addWidget(peak_box)
        self.peak_quantity.currentIndexChanged.connect(self.update_peak)
        peak_box.hide()
        self.plot = NativeSpectrumWidget(paper_factory=spectrum_figure)
        self.plot.setMinimumHeight(180)
        self.results = table([])
        tabs = QTabWidget();self.result_tabs=tabs
        tabs.addTab(self.plot, 'Spectrum')
        tabs.addTab(self.results, 'Samples')
        self.results.setToolTip('First 10,000 rows shown; CSV export includes all calculated samples.')
        self.phase_page=QWidget();phase_layout=QVBoxLayout(self.phase_page)
        from spectral_phase import PHASE_MODES,PHASE_UNITS
        display_options=self.store.search_state.get('phase_display',{})
        self.phase_mode=_combo(PHASE_MODES,display_options.get('mode','positive'))
        self.phase_unit=_combo(PHASE_UNITS,display_options.get('unit','radians'))
        self.phase_reference_path=Path(display_options['reference_csv']) if display_options.get('reference_csv') else None
        self.phase_reference=_combo([('Absolute · stack boundary planes','boundary'),('Relative · physical reference CSV','csv')],display_options.get('reference_mode','boundary'))
        self.phase_mode.setAccessibleName('Phase wrapping mode');self.phase_unit.setAccessibleName('Phase display units')
        self.phase_reference.setAccessibleName('Phase reference convention')
        phase_controls=QHBoxLayout();phase_controls.addWidget(QLabel('Display'));phase_controls.addWidget(self.phase_mode)
        phase_controls.addWidget(QLabel('Units'));phase_controls.addWidget(self.phase_unit);phase_controls.addStretch()
        phase_layout.addLayout(phase_controls)
        references=QHBoxLayout();references.addWidget(QLabel('Reference'));references.addWidget(self.phase_reference)
        references.addWidget(_button('Choose reference CSV…',self.choose_phase_reference_csv));references.addStretch();phase_layout.addLayout(references)
        self.phase_reference_label=QLabel('Absolute boundary phase includes propagation between the stack planes. A reference CSV must use matching polarization and physical boundary planes.')
        self.phase_reference_label.setWordWrap(True);phase_layout.addWidget(self.phase_reference_label)
        phase_note=QLabel('2π rad = 2 in Phase / π = 360°. The lower plot accumulates full cycles from each valid segment. Undefined signals / independent branches reset unwrapping; adjacent changes must be resolved below π.')
        phase_note.setWordWrap(True);phase_layout.addWidget(phase_note)
        self.phase_plot = PlotWidget();phase_layout.addWidget(self.phase_plot,1)
        phase_exports=QHBoxLayout()
        phase_exports.addWidget(_button('Export complete phase CSV…',self.export_phase_csv))
        phase_exports.addWidget(_button('Export display CSV…',self.export_phase_display_csv))
        phase_exports.addWidget(_button('Export phase figure…',self.phase_plot.export_dialog))
        phase_layout.addLayout(phase_exports)
        tabs.addTab(self.phase_page, 'Phase')
        self.phase_mode.currentIndexChanged.connect(self.phase_display_changed)
        self.phase_unit.currentIndexChanged.connect(self.phase_display_changed)
        self.phase_reference.currentIndexChanged.connect(self.phase_reference_changed)
        self.generated_fields=QWidget();field_layout=QVBoxLayout(self.generated_fields)
        field_bar=QHBoxLayout();self.field_sample=QComboBox();self.field_sample.setMinimumContentsLength(18)
        self.field_sample.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.field_sample.view().setUniformItemSizes(True)
        self.field_position=integer(1,1,1)
        self.field_position.setToolTip('Open any saved field sample by its number.')
        self.field_component=_combo([('|E|','E2'),('|Ex|','Ex'),('|Ey|','Ey'),('|Ez|','Ez')])
        field_bar.addWidget(QLabel('Sample'));field_bar.addWidget(self.field_position)
        field_bar.addWidget(QLabel('Wavelength / angle'));field_bar.addWidget(self.field_sample,1);field_bar.addWidget(self.field_component)
        field_layout.addLayout(field_bar);self.generated_field_plot=PlotWidget();field_layout.addWidget(self.generated_field_plot,1)
        self.field_status=_label('');field_layout.addWidget(self.field_status)
        tabs.addTab(self.generated_fields,'Electric fields')
        from qt_field_volume import FieldVolumeWidget
        self.generated_volume=FieldVolumeWidget(store,campaign=True)
        self._volume_display_key=None
        tabs.addTab(self.generated_volume,'3D fields')
        tabs.currentChanged.connect(lambda *_:QTimer.singleShot(0,self.draw_generated_fields))
        self.field_sample.currentIndexChanged.connect(self.draw_generated_fields);self.field_component.currentIndexChanged.connect(self.draw_generated_fields)
        self.field_position.valueChanged.connect(self.select_field_sample)

        output.addWidget(tabs, 1)
        cursor_box,cursor_form=_group('Sample readout')
        self.sample_position=integer(1,1,1)
        self.sample_readout=_label('')
        self.sample_readout.setToolTip('Select a sample or click the spectrum to inspect R / T / A.')
        cursor_form.addRow('Sample',self.sample_position)
        cursor_form.addRow(self.sample_readout)
        output.addWidget(cursor_box)
        cursor_box.setTitle('')
        cursor_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.results_overview=overview
        overview_layout.setContentsMargins(8,12,8,8)
        peak_form.setContentsMargins(8,12,8,8)
        cursor_form.setContentsMargins(8,12,8,8)
        self.sample_position.valueChanged.connect(lambda value:self.inspect_sample(value-1))
        self.results.cellClicked.connect(lambda row,column:self.inspect_sample(row))
        self.plot.sampleSelected.connect(lambda position:self.inspect_sample(position))
        output.addWidget(_button('Export spectrum CSV…',self.export_spectrum))
        self.metrics = _label('Run a simulation to see sample counts and GPU activity.')
        output.addWidget(self.metrics)
        output.addWidget(_button('Open saved result files', self.open_results))
        panels = _split(left, right, run_actions)
        self.workspace_splitter=panels
        recent = QGroupBox('Recent runs')
        recent_layout = QVBoxLayout(recent)
        self.recent_runs = QListWidget()
        self.recent_runs.setMinimumWidth(150)
        recent_layout.addWidget(self.recent_runs)
        recent_layout.addWidget(_button('Load selected run', self.load_recent))
        recent_layout.addWidget(_button('Load setup', self.restore_recent_setup))
        recent_layout.addWidget(_button('View saved files', self.open_recent))
        self.recent_details=_label('Select a run to inspect its saved setup.',True)
        recent_layout.addWidget(self.recent_details)
        self.recent_runs.currentItemChanged.connect(self.describe_recent)
        panels.addWidget(recent)
        # The reference gives the plot the full central column, with actions
        # next to the saved-run inspector instead of underneath the spectrum.
        for index in reversed(range(output.count())):
            widget=output.itemAt(index).widget()
            if isinstance(widget,QPushButton):
                output.removeWidget(widget);recent_layout.addWidget(widget)
        self.metrics.hide()
        for value in self.power_values.values():value.setObjectName('responseValue')
        for plot in (self.phase_plot,self.generated_field_plot):plot.toolbar.hide()
        samples_page=QWidget();samples_layout=QVBoxLayout(samples_page)
        tabs.removeTab(1);samples_layout.addWidget(self.peak_quantity);samples_layout.addWidget(self.results,1)
        tabs.insertTab(1,samples_page,'Samples')
        overview.setMaximumHeight(140)
        self.plot.setMinimumHeight(180)
        left.setMinimumWidth(0)
        recent.setMinimumWidth(240)
        panels.reference_ratios=(.305,.435,.26)
        # A complete three-column optical setup needs room for all six digits
        # of R/T/A and the field viewer controls. Only this workspace stacks
        # earlier; the other compute tools retain their existing breakpoint.
        panels.responsive_breakpoint=1120
        panels.setSizes([450,640,380])
        # Preserve full result and action panels when the three columns stack.
        # The surrounding scroll host absorbs their height instead of allowing
        # children to paint outside undersized splitter cells.
        panels.vertical_minimum_sizes=(520,850,440)
        self.workspace_scroll=_scroll(panels)
        self.layout_.addWidget(self.workspace_scroll, 1)
        store.library_changed.connect(self.refresh_recent)
        self.refresh_recent()
        self.footer()
        for widget in self.controls.values():
            _on_edit(widget, self.save_settings)
        store.changed.connect(self.refresh)
        store.changed.connect(self.update_field_selection)
        self.refresh()

    def refresh(self, reason=None):
        if reason not in (None,'project','settings','undo'):return
        for key, widget in self.controls.items():
            if key in self.store.settings:
                _set_value(widget, self.store.settings[key])
        saved=self.store.search_state.get('simulation',{}).get('electric_fields',{})
        with QSignalBlocker(self.measure_phase):
            self.measure_phase.setChecked(bool(self.store.search_state.get('simulation',{}).get('measure_phase',False)))
        for key,widget in self.field_controls.items():_set_value(widget,saved.get(key,{'grid':25,'depth_samples':3,'contour_step':.1}[key]))
        options=self.store.search_state.get('simulation',{})
        _set_value(self.field_single,options.get('single_wavelength',True))
        _set_value(self.field_source,options.get('wavelength_source','manual'))
        _set_value(self.field_wavelength,options.get('wavelength_nm',1550))
        phase_options=self.store.search_state.get('phase_display',{})
        previous_phase_display=(self.phase_mode.currentData(),self.phase_unit.currentData())
        _set_value(self.phase_mode,phase_options.get('mode','positive'))
        _set_value(self.phase_unit,phase_options.get('unit','radians'))
        if previous_phase_display!=(self.phase_mode.currentData(),self.phase_unit.currentData()):self.draw_phase()
        previous_reference=(self.phase_reference.currentData(),str(self.phase_reference_path or ''))
        self.phase_reference_path=Path(phase_options['reference_csv']) if phase_options.get('reference_csv') else None
        _set_value(self.phase_reference,phase_options.get('reference_mode','boundary'))
        if previous_reference!=(self.phase_reference.currentData(),str(self.phase_reference_path or '')):
            self.load_phase();self.draw_phase()
        self.update_field_selection()
        self._mode()

    def field_options(self):
        return {key:_value(widget) for key,widget in self.field_controls.items()}

    def inspect_sample(self,position,draw_cursor=True):
        if self.result_frame.empty:return
        count=len(self.spectrum_results) if self.spectrum_results is not None else len(self.result_frame)
        position=max(0,min(int(position),count-1))
        row=(pd.Series(self.spectrum_results[position][1:],index=['wavelength_nm','angle_deg','R','T','A'])
             if self.spectrum_results is not None else self.result_frame.iloc[position])
        with QSignalBlocker(self.sample_position):
            self.sample_position.setRange(1,count)
            self.sample_position.setValue(position+1)
        coordinates=[f'{row[key]:.8g} {unit}' for key,unit in [('wavelength_nm','nm'),('angle_deg','°')] if key in row and pd.notna(row[key])]
        values=[]
        for key,label in self.power_values.items():
            value=pd.to_numeric(row.get(key),errors='coerce')
            label.setText(f'{value:.4f}' if pd.notna(value) and np.isfinite(value) else '—')
            label.setToolTip('Value at the selected sample.')
            if pd.notna(value):values.append(f'{key}: {value:.6g}')
        self.sample_readout.setText(' · '.join(coordinates+values))
        if position<self.results.rowCount():self.results.selectRow(position)
        self.plot.select_sample(position,emit=False,move_cursor=draw_cursor)

    def inspect_plot_sample(self,event):
        if event.inaxes is None or event.xdata is None or self.result_frame.empty:return
        key='angle_deg' if 'angle_deg' in self.result_frame and self.result_frame.angle_deg.nunique()>1 else 'wavelength_nm'
        if key not in self.result_frame:return
        values=pd.to_numeric(self.result_frame[key],errors='coerce').to_numpy(dtype=float)
        distances=np.where(np.isfinite(values),np.abs(values-event.xdata),np.inf)
        if np.isfinite(distances).any():
            position=int(np.argmin(distances))
            self.inspect_sample(int(self.result_frame.iloc[position]['point_index']) if self.spectrum_results is not None else position)

    def export_spectrum(self):
        if self.result_frame.empty:
            self.status.setText('Load or calculate a spectrum before exporting.');return
        path,_=QFileDialog.getSaveFileName(self,'Export spectrum','spectrum.csv','CSV (*.csv)')
        if path:
            try:
                if self.spectrum_results is not None:
                    import shutil
                    source=self.spectrum_directory/'results.csv'
                    if source.resolve()!=Path(path).resolve():shutil.copyfile(source,path)
                    count=len(self.spectrum_results)
                else:
                    self.result_frame.to_csv(path,index=False);count=len(self.result_frame)
                self.status.setText(f'Exported all {count:,} samples to {path}.')
            except OSError as exc:self.status.setText(str(exc))

    def describe_recent(self,*_):
        item=self.recent_runs.currentItem()
        identifier=item.data(Qt.ItemDataRole.UserRole) if item else None
        record=next((r for r in self.store.library.entries() if r.get('id')==identifier),None)
        self.recent_details.setText('\n'.join(str(record.get(k,'')) for k in ('title','created','status')) if record else 'Select a saved run.')

    def restore_recent_setup(self):
        if self.store.busy:return
        item=self.recent_runs.currentItem()
        identifier=item.data(Qt.ItemDataRole.UserRole) if item else None
        if not identifier:return
        try:
            project,search=self.store.library.project_for(identifier,0)
            if search:project['search']=search
            self.store.load_project(project)
            self.status.setText('Loaded the selected run’s structure, materials and simulation settings.')
        except Exception as exc:self.status.setText('Could not load setup: '+str(exc))

    def save_field_settings(self,*_):
        try:self.store.save_search('simulation',dict(measure_phase=self.measure_phase.isChecked(),electric_fields=self.field_options(),single_wavelength=self.field_single.isChecked(),wavelength_source=self.field_source.currentData(),wavelength_nm=self.field_wavelength.value()))
        except Exception as exc:self.status.setText(str(exc))
        self.update_field_selection()

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
        options = {'measure_phase': self.measure_phase.isChecked()}
        if self.save_settings():
            self.save_field_settings()
            self._start('simulation', options)

    def update_field_selection(self,*_):
        from spectrum_field_job import compatible_project
        single=self.field_single.isChecked();source=self.field_source.currentData()
        manual=single and source=='manual'
        self.field_source.setEnabled(single)
        self.field_wavelength.setEnabled(manual)
        valid=manual
        self._selected_field_row=None
        if manual:
            text=f'Selected: {self.field_wavelength.value():g} nm. Manual entry can run without a spectrum.'
        elif self.spectrum_directory is None or self.spectrum_results is None:
            text='Run or load a matching completed spectrum first.'
        elif not self._spectrum_project or not compatible_project(self.store.project(),self._spectrum_project):
            text='Setup changed. Run a new spectrum or restore the saved setup.'
        else:
            try:
                record=json.loads((self.spectrum_directory/'library_record.json').read_text(encoding='utf-8'))
                if record.get('status')!='complete':raise ValueError('Use a completed spectrum for field selection.')
                if single:
                    row=self.spectrum_results.extremum(source[-1],maximum=source.startswith('max'))
                    if row is None:raise ValueError('No finite samples for this extremum.')
                    self._selected_field_row=row
                    with QSignalBlocker(self.field_wavelength):self.field_wavelength.setValue(row[1])
                    value=row['RTA'.index(source[-1])+3]
                    text=f'{self.field_source.currentText()}: {value:.6g} at {row[1]:.8g} nm, {row[2]:g}°.'
                else:text=f'{len(self.spectrum_results):,} saved samples. Each will get full 3D fields in a separate run.'
                valid=True
            except (OSError,ValueError,KeyError) as exc:text=str(exc)
        self.field_selection.setText(text)
        self.field_run.setText('Run electric fields' if single else 'Run fields for entire spectrum')
        self.field_run.setEnabled(valid and not self.store.busy)

    def run_fields(self):
        if not self.save_settings():return
        self.save_field_settings()
        if not self.field_run.isEnabled():return
        options=dict(electric_fields=self.field_options(),single_wavelength=self.field_single.isChecked(),
            wavelength_source=self.field_source.currentData(),wavelength_nm=self.field_wavelength.value())
        if self.spectrum_directory is not None:options['spectrum_id']=self.spectrum_directory.name
        self._start('simulation_fields',options)

    def refresh_recent(self):
        self.recent_runs.clear()
        for record in self.store.library.entries():
            if record.get('kind') != 'simulation' and record.get('summary',{}).get('task')!='simulation_fields':
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

    def load_spectrum(self,path=None):
        from scan_storage import SpectrumResults,legacy_spectrum_index
        path=Path(path or self.directory/'results.csv')
        self.spectrum_directory=path.parent
        try:self._spectrum_project=json.loads((path.parent/'project.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):self._spectrum_project=None
        index=path.parent/'spectrum.sqlite'
        self.spectrum_results=SpectrumResults(index) if index.is_file() else legacy_spectrum_index(path)
        self.result_frame=(self.spectrum_results.frame(preview=True) if self.spectrum_results is not None else _read_csv(path))
        shown=(self.spectrum_results.frame(limit=10000) if self.spectrum_results is not None else self.result_frame.iloc[:10000])
        fill_table(self.results,shown.drop(columns=['point_index'],errors='ignore'))
        count=len(self.spectrum_results) if self.spectrum_results is not None else len(self.result_frame)
        self.load_phase(count)
        self.update_field_selection()

    def load_recent(self):
        item = self.recent_runs.currentItem()
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return
        try:
            directory = self.store.library.directory(item.data(Qt.ItemDataRole.UserRole))
            self.directory = Path(directory)
            self.field_directory=self.directory
            if (self.directory/'results.csv').is_file():
                self.load_spectrum();self.update_peak()
            else:
                self.load_generated_fields()
                self.result_tabs.setCurrentWidget(self.generated_fields)
                QTimer.singleShot(0,self.draw_generated_fields)
                self.status.setText(f'Loaded saved electric fields: {directory}')
                return
            self.load_generated_fields()
            count=len(self.spectrum_results) if self.spectrum_results is not None else len(self.result_frame)
            self.metrics.setText(f'{count:,} saved samples loaded.')
            self.status.setText(f'Loaded saved simulation: {directory}')
        except (OSError, ValueError) as exc:
            self.status.setText(f'Could not load saved simulation: {exc}')

    def load_generated_fields(self):
        import json
        with QSignalBlocker(self.field_sample):
            old_model=self.field_sample.model()
            self.field_sample.setModel(QStandardItemModel(self.field_sample))
            if isinstance(old_model,FieldSamplesModel):old_model.deleteLater()
            root=self.field_directory or self.directory
            manifest=root/'fields'/'samples.json' if root else None
            if manifest and (manifest.parent/'samples.sqlite').is_file():
                self.field_sample.setModel(FieldSamplesModel(manifest.parent,self.field_sample))
            elif manifest and manifest.is_file():
                saved=json.loads(manifest.read_text(encoding='utf-8'))
                for sample in saved.get('samples',[]):
                    self.field_sample.addItem(f"{sample['wavelength_nm']:g} nm · {sample['angle_deg']:g}°",sample['directory'])
        with QSignalBlocker(self.field_position):
            model=self.field_sample.model()
            count=len(model.index) if isinstance(model,FieldSamplesModel) else self.field_sample.count()
            self.field_position.setRange(1,max(1,count));self.field_position.setValue(1)
        self._fields_dirty=True
        self.draw_generated_fields()

    def select_field_sample(self,value):
        model=self.field_sample.model()
        if isinstance(model,FieldSamplesModel):
            with QSignalBlocker(self.field_sample):
                model.set_page(value-1);self.field_sample.setCurrentIndex(value-1-model.offset)
            self.draw_generated_fields()
        else:self.field_sample.setCurrentIndex(value-1)

    def draw_generated_fields(self,*_):
        current=self.result_tabs.currentWidget()
        if current not in (self.generated_fields,self.generated_volume) or not self.isVisible():return
        if current is self.generated_volume:
            path=self.field_sample.currentData()
            if path and path!=self._volume_display_key:
                self.generated_volume.load_directory(path);self._volume_display_key=path
            elif not path:self.generated_volume.invalidate();self._volume_display_key=None
            return
        model=self.field_sample.model()
        offset=model.offset if isinstance(model,FieldSamplesModel) else 0
        with QSignalBlocker(self.field_position):self.field_position.setValue(max(1,offset+self.field_sample.currentIndex()+1))
        path=self.field_sample.currentData()
        key=(path,self.field_component.currentData())
        if key==self._field_display_key and not self._fields_dirty:return
        self._field_display_key=key;self._fields_dirty=False
        if not path:
            self.generated_field_plot.clear();self.field_status.setText('No saved electric fields');return
        try:
            self.generated_field_plot.draw_figure(field_figure(path,self.field_component.currentData(),arrows=False,amplitude=True))
            self.field_status.setText('')
            self.generated_field_plot.setToolTip('XY at the layer midplane · XZ through the full finite stack. Amplitudes are relative to incident |E|.')
        except Exception as exc:self.field_status.setText('Could not display saved fields: '+str(exc))

    def view_generated_fields(self):
        if not self.field_sample.count():
            self.status.setText('Calculate electric fields separately or load a saved field run first.');return
        self.result_tabs.setCurrentWidget(self.generated_volume)
        QTimer.singleShot(0,self.draw_generated_fields)

    def update_peak(self, *_):
        frame = self.result_frame
        self.draw_phase()
        key = self.peak_quantity.currentData()
        name = self.peak_quantity.currentText().lower()
        self.plot.set_spectrum(frame,peak_key=key,sample_lookup=self.spectrum_results)
        self.results.clearSelection()
        for value in self.power_values.values():
            value.setText('—')
            value.setToolTip('')
        peak=self.spectrum_results.peak(key) if self.spectrum_results is not None else None
        position = self.spectrum_results.position_for_id(peak[0]) if peak is not None else highest_sample_index(frame, key)
        if position is None:
            self.peak_summary.setText(f'No finite {name} samples are available in the displayed data.')
            return
        best = pd.Series(peak[1:],index=['wavelength_nm','angle_deg','R','T','A']) if peak is not None else frame.iloc[position]
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
        if position < self.results.rowCount():
            self.results.selectRow(position)
        self.inspect_sample(position,draw_cursor=False)

    def draw_phase(self):
        from spectral_phase import phase_figure
        self.phase_plot.draw_figure(phase_figure(self.phase_frame,self.phase_mode.currentData(),self.phase_unit.currentData()))
        if self.phase_frame.attrs.get('phase_reference_mode')=='reference_csv':
            label='/'.join(self.phase_reference_path.parts[-3:])
            self.phase_reference_label.setText(f'Reference-relative: {label}. Exact matching grid; arg(response / reference). Assumes matching polarization and boundary planes; undefined sample or reference signals remain gaps.')
            self.phase_reference_label.setToolTip(str(self.phase_reference_path.resolve()))
        else:
            self.phase_reference_label.setText('Absolute boundary phase includes propagation between the top and bottom stack planes. A physical reference must use matching polarization and boundary planes.')
            self.phase_reference_label.setToolTip('')

    def phase_display_changed(self,*_):
        self.store.save_search('phase_display',dict(mode=self.phase_mode.currentData(),unit=self.phase_unit.currentData(),
            reference_mode=self.phase_reference.currentData(),reference_csv=str(self.phase_reference_path) if self.phase_reference_path else ''))
        self.draw_phase()

    def load_phase(self,count=None):
        path=self._phase_path()
        reference=self.phase_reference_path if self.phase_reference.currentData()=='csv' else None
        try:self.phase_frame=phase_preview(path,count,reference_path=reference) if path else pd.DataFrame()
        except (OSError,ValueError) as exc:
            with QSignalBlocker(self.phase_reference):self.phase_reference.setCurrentIndex(0)
            self.phase_frame=phase_preview(path,count) if path else pd.DataFrame()
            self.status.setText(str(exc)+' Showing absolute boundary phase.')

    def phase_reference_changed(self,*_):
        if self.phase_reference.currentData()=='csv' and self.phase_reference_path is None:
            with QSignalBlocker(self.phase_reference):self.phase_reference.setCurrentIndex(0)
            self.status.setText('Choose a complete matching reference phase CSV first.');return
        self.load_phase();self.phase_display_changed()

    def set_phase_reference_path(self,path):
        from spectral_phase import read_phase_preview
        source=self._phase_path()
        if source is None:self.status.setText('Load a saved phase result before selecting a physical reference.');return False
        try:frame=read_phase_preview(source,reference_path=path)
        except (OSError,ValueError) as exc:self.status.setText(str(exc));return False
        self.phase_reference_path=Path(path);self.phase_frame=frame
        with QSignalBlocker(self.phase_reference):self.phase_reference.setCurrentIndex(self.phase_reference.findData('csv'))
        self.phase_display_changed();return True

    def choose_phase_reference_csv(self):
        source=self._phase_path()
        if source is None:return
        filename,_=QFileDialog.getOpenFileName(self,'Choose complete physical reference phase CSV',str(source.parent),'CSV (*.csv)')
        if filename:self.set_phase_reference_path(filename)

    def _phase_path(self):
        directory=getattr(self,'spectrum_directory',None)
        path=Path(directory)/'phase.csv' if directory else None
        return path if path and path.is_file() else None

    def export_phase_csv(self):
        path=self._phase_path()
        if not path:return
        import shutil
        filename,_=QFileDialog.getSaveFileName(self,'Export complete specular phase','specular-phase.csv','CSV (*.csv)')
        if filename:shutil.copyfile(path,filename)

    def export_phase_display_csv(self):
        path=self._phase_path()
        if not path:return
        from spectral_phase import export_phase_display_csv
        filename,_=QFileDialog.getSaveFileName(self,'Export complete phase with display units','specular-phase-display.csv','CSV (*.csv)')
        if filename:
            try:export_phase_display_csv(path,filename,self.phase_mode.currentData(),self.phase_unit.currentData(),self.phase_reference_path if self.phase_reference.currentData()=='csv' else None)
            except (OSError,ValueError) as exc:self.status.setText(str(exc))

    def show_result(self, event):
        if event.get('run_kind')=='simulation_fields':
            self.field_directory=self.directory
            self.load_generated_fields()
            self.result_tabs.setCurrentWidget(self.generated_fields)
            QTimer.singleShot(0,self.draw_generated_fields)
            samples=event.get('summary',{}).get('electric_fields',{}).get('samples',0)
            self.status.setText(f'Completed {samples:,} full 3D field samples. Saved to {self.directory}')
            return
        self.field_directory=self.directory
        self.load_spectrum(Path(event.get('output') or self.directory / 'results.csv'))
        self.update_peak()
        self.load_generated_fields()
        self.result_tabs.setCurrentWidget(self.plot)
        self.plot.export_figure(self.directory / 'spectrum.png')
        if (self.directory / 'phase.csv').exists():
            self.phase_plot.export_figure(self.directory / 'phase.png')
        count=len(self.spectrum_results) if self.spectrum_results is not None else len(self.result_frame)
        parts = [f'{count:,} samples saved.']
        from gpu_status import acceleration_summary
        info = event.get('info', {})
        parts.append(acceleration_summary(info))
        self.metrics.setText(' '.join(parts))
        warnings=info.get('warnings', [])
        self.status.setText('Completed. ' + ('Warnings: '+' '.join(warnings)+' ' if warnings else '') + f' Saved to {self.directory}')


class OptimizePage(_RunPage):
    routeRequested=pyqtSignal(str)
    def __init__(self, store, parent=None):
        super().__init__(store, 'Simulation Sweep', 'Design for absorption, transmission or reflection at your wavelength, with optional field-guided learning.', {'target', 'peaks'}, parent)
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
        self.tool_tabs={
            'target':[(self.tabs,0)],'explore':[(self.tabs,1)],
            'target.holes':[(self.tabs,0),(self.target_range_tabs,0)],
            'target.parameters':[(self.tabs,0),(self.target_range_tabs,1)],
            'target.sampling':[(self.tabs,0),(self.target_advanced_tabs,0)],
            'target.learning':[(self.tabs,0),(self.target_advanced_tabs,1)],
            'target.fields':[(self.tabs,0),(self.target_result_tabs,0)],
            'target.designs':[(self.tabs,0),(self.target_result_tabs,1)],
            'explore.constraints':[(self.tabs,1),(self.general_detail_tabs,0)],
            'explore.detection':[(self.tabs,1),(self.general_detail_tabs,1)],
            'explore.learning':[(self.tabs,1),(self.general_detail_tabs,2)],
            'explore.spectrum':[(self.tabs,1),(self.general_result_tabs,0)],
            'explore.q':[(self.tabs,1),(self.general_result_tabs,1)],
            'explore.matches':[(self.tabs,1),(self.general_result_tabs,2)],
            'explore.designs':[(self.tabs,1),(self.general_result_tabs,3)]}
        from qt_tool_workspace import polish_tool_workspace
        polish_tool_workspace(self)

    def select_tool_tab(self,route):
        from qt_tool_workspace import select_tool_tab
        return select_tool_tab(self,route)

    def _target_page(self):
        left, right = QWidget(), QWidget()
        controls, output = QVBoxLayout(left), QVBoxLayout(right)
        self.target_controls = {
            'response': _combo(['Absorption','Transmission','Reflection'], 'Absorption'),
            'objective': _combo(['Response at target','Maximum Q'], 'Maximum Q'),
            'response_threshold': number(.99, 0, .999999, 6),
            'response_agreement': number(.001, 0, 1, 6),
            'use_structure_patterns': _check('Use all Structure regions', False),
            'merge_circles': _check('Merge overlapping circles', False),
            'min_bridge_um': number(.01, 0, 1e6, 6),
            'min_neck_um': number(.01, 0, 1e6, 6),
            'target_nm': number(1550, .000001), 'tolerance_nm': number(5, .000001), 'min_q': number(1000, 1, 1e12, 2),
            'half_window': number(20, .000001), 'step': number(.2, .000001), 'grid_steps': integer(21, 2, 101),
            'trials': integer(40, 2, 10000), 'initial': integer(8, 2, 10000), 'finalists': integer(3, 1, 10),
            'reuse': _check('Learn from compatible saved spectra and fields'), 'history': integer(300, 1, 2000),
            'use_fields': _check('Use electric-field information during learning'),
            'field_grid': integer(6, 3, 30), 'map_grid': integer(25, 3, 80),
            'track_resonance': _check('Track fields at both the target and moving resonance'),
        }
        goal, _ = _group('Design goal', [(label, self.target_controls[key]) for label, key in
            [('Optical response', 'response'), ('Optimize', 'objective'), ('Minimum response (0–1)', 'response_threshold'),
             ('Target wavelength (nm)', 'target_nm'), ('Tolerance ± (nm)', 'tolerance_nm'), ('Minimum Q factor', 'min_q')]])
        self.target_controls['use_structure_patterns'].setToolTip('Optimize multiple holes or circle-built outlines using saved ranges under Other parameters.')
        self.target_controls['merge_circles'].setToolTip('Overlapping circles of the same material become one opening with a valid merged S4 boundary.')
        controls.addWidget(goal)
        controls.addWidget(_label('Response at target maximizes the selected power fraction at exactly your wavelength; it does not require a spectral peak. Maximum Q requires a resolved peak within tolerance. Both require response above your threshold and successive agreement across at least three Fourier bases.', True))
        controls.addWidget(self.target_controls['use_structure_patterns'])
        controls.addWidget(_button('Create multi-hole / double-lattice cell', self.create_multi_hole))
        controls.addWidget(_button('Choose candidate materials from library', self.choose_design_materials))
        controls.addWidget(self.target_controls['merge_circles'])
        fabrication, _ = _group('Etched geometry', [('Minimum material bridge (µm)', self.target_controls['min_bridge_um']),
            ('Minimum merged neck (µm)', self.target_controls['min_neck_um'])])
        controls.addWidget(fabrication)
        self.holes = HoleEditor(self.store)
        self.target_bounds = BoundsEditor(self.store)
        range_tabs = QTabWidget()
        self.target_range_tabs=range_tabs
        range_tabs.addTab(self.holes, 'PCS hole limits')
        range_tabs.addTab(self.target_bounds, 'Other parameters')
        controls.addWidget(range_tabs)
        learning, form = _group('Search budget', [('New designs', self.target_controls['trials'])])
        form.addRow(self.target_controls['reuse'])
        form.addRow(self.target_controls['use_fields'])
        controls.addWidget(learning)
        advanced = QTabWidget()
        self.target_advanced_tabs=advanced
        sampling, _ = _group('Sampling and verification', [(label, self.target_controls[key]) for label, key in
            [('Window: target ± (nm)', 'half_window'), ('Initial wavelength step (nm)', 'step'), ('Sizes per range', 'grid_steps'),
             ('Initial designs', 'initial'), ('Finalists to verify', 'finalists'), ('Response agreement (absolute)', 'response_agreement')]])
        field_options, form = _group('Training data', [(label, self.target_controls[key]) for label, key in
            [('Saved observations to reuse', 'history'), ('Training grid per axis', 'field_grid'), ('Final map grid per axis', 'map_grid')]])
        form.addRow(self.target_controls['track_resonance'])
        advanced.addTab(sampling, 'Sampling')
        advanced.addTab(field_options, 'Learning detail')
        controls.addWidget(advanced)
        run_actions = self.actions('Run AI design search', self.run_target)
        controls.addWidget(self._setup_actions('target'))
        controls.addStretch()
        self.target_summary = _label('The recommended design will appear here after verification.')
        output.addWidget(self.target_summary)
        self.target_plot = PlotWidget()
        self.target_plot.setMinimumHeight(400)
        self.target_results = table([])
        result_tabs = QTabWidget()
        self.target_result_tabs=result_tabs
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
        self.target_controls['use_structure_patterns'].toggled.connect(self._target_enabling)
        self.target_controls['merge_circles'].toggled.connect(self._target_enabling)
        self.target_controls['objective'].currentIndexChanged.connect(self._target_enabling)
        self._target_enabling()
        inspector=WorkspacePanel();inspector_layout=QVBoxLayout(inspector)
        caption=_label('Parameter bounds and search budget');caption.setObjectName('sectionTitle');inspector_layout.addWidget(caption)
        for widget in (range_tabs,learning,advanced):
            controls.removeWidget(widget);inspector_layout.addWidget(widget)
        inspector_layout.addStretch()
        splitter=_split(left,right,run_actions)
        inspector_scroll=_scroll(inspector);inspector_scroll.setMinimumWidth(360)
        splitter.addWidget(inspector_scroll);splitter.setSizes([350,650,400])
        self.target_workspace_splitter=splitter
        return splitter

    def _target_enabling(self, *_):
        fields = self.target_controls['use_fields'].isChecked()
        for key in ('field_grid', 'map_grid', 'track_resonance'):
            self.target_controls[key].setEnabled(fields)
        self.target_controls['history'].setEnabled(self.target_controls['reuse'].isChecked())
        all_regions = self.target_controls['use_structure_patterns'].isChecked()
        self.holes.setEnabled(not all_regions)
        self.target_controls['min_neck_um'].setEnabled(self.target_controls['merge_circles'].isChecked())
        self.target_controls['min_q'].setEnabled(self.target_controls['objective'].currentData() == 'Maximum Q')

    def create_multi_hole(self):
        from qt_multi_hole import MultiHoleDialog
        dialog = MultiHoleDialog(self.store, self)
        if dialog.exec():
            self.holes.linked.setChecked(False)
            self.target_controls['use_structure_patterns'].setChecked(True)
            self.target_controls['merge_circles'].setChecked(dialog.merge.isChecked())
            self.target_bounds.set_records(dialog.bounds)
            self.persist_setup('target')
            self.status.setText('Multi-hole cell applied. Review each circle radius/position range under Other parameters, then run the AI search.')

    def choose_design_materials(self):
        from qt_design_materials import DesignMaterialsDialog
        dialog = DesignMaterialsDialog(self.store, self)
        if dialog.exec():
            rows = [r for r in self.target_bounds.records() if not
                (r['Parameter']=='layer_material' and r['Target']==dialog.bound['Target'])]
            self.target_bounds.set_records(rows+[dialog.bound])
            self.persist_setup('target')
            self.status.setText('Library material choices added to Other parameters. The AI will compare these materials using their stored optical constants.')

    def _general_page(self):
        left, right = QWidget(), QWidget()
        controls, output = QVBoxLayout(left), QVBoxLayout(right)
        self.search_controls = {
            'search_mode': _combo(SEARCH_MODES, 'Hybrid verified'), 'design_budget': integer(500, 1, 10000),
            'ratio_limit': number(.6, .000001, .6), 'min_bridge_um': number(0, 0),
            'separate_circles': _check('Keep circular regions separate, including periodic neighbors'),
            'response': _combo(['Absorption', 'Reflection', 'Transmission']),
            'absorption_target': number(.99, 0, .999999999, 9), 'tie_tolerance': number(.0001, 0, 1, 8),
            'prominence': number(.00001, 0, 1, 8), 'refinement_rounds': integer(3, 0, 6),
            'point_budget': integer(200000, 3, MAX_SWEEP_POINTS), 'initial_designs': integer(24, 2, 10000),
            'ml_trials': integer(60, 2, 10000), 'candidate_pool': integer(1024, 32, 10000),
            'random_seed': integer(42, 0, 2147483647), 'finalists': integer(2, 1, 10),
            'verification_basis_factor': number(1.5, 1.01, 4), 'verification_step_divisor': integer(2, 2, 10),
            'absorption_agreement': number(.001, 0, 1), 'q_agreement': number(.05, 0, 1),
            'patience': integer(0, 0, 10000),
        }
        method, _ = _group('Search method', [('Method', self.search_controls['search_mode']), ('Maximum designs', self.search_controls['design_budget'])])
        controls.addWidget(method)
        controls.addWidget(_label('Uses the wavelength range and incident-light settings in Simulation. Empty bounds evaluate the current design only.', True))
        controls.addWidget(_button('Edit shared optical sampling',lambda:self.routeRequested.emit('optical.sweep')))
        self.bounds = BoundsEditor(self.store)
        from linked_hole_sweep import make_widget
        self.shared_hole = make_widget(self.store)
        controls.addWidget(self.shared_hole)
        self.shared_hole.changed.connect(lambda:self.persist_setup('peaks'))
        controls.addWidget(self.bounds)
        controls.addWidget(_button('Create fixed ranges from Structure', self.bounds.populate_current))
        details = QTabWidget()
        self.general_detail_tabs=details
        constraints, form = _group('Acceptance and fabrication', [(label, self.search_controls[key]) for label, key in
            [('Response', 'response'), ('Response threshold (fraction)', 'absorption_target'), ('Circle r/a upper limit', 'ratio_limit'),
             ('Minimum circle gap (µm)', 'min_bridge_um'), ('Best-match tolerance (fraction)', 'tie_tolerance')]])
        form.addRow(self.search_controls['separate_circles'])
        sampling, _ = _group('Peak detection', [(label, self.search_controls[key]) for label, key in
            [('Peak prominence (fraction)', 'prominence'), ('Finer sampling rounds', 'refinement_rounds'), ('Maximum spectral points', 'point_budget')]])
        self.ml_settings, _ = _group('Learning and verification', [(label, self.search_controls[key]) for label, key in
            [('Initial designs', 'initial_designs'), ('Learning trials', 'ml_trials'), ('Candidate pool', 'candidate_pool'),
             ('Random seed', 'random_seed'), ('Finalists', 'finalists'), ('Verification basis multiplier', 'verification_basis_factor'),
             ('Verification step divisor', 'verification_step_divisor'), ('Response agreement', 'absorption_agreement'),
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
        self.peak_summary = _label('Find peak locations first, then compare all designs matching the best selected response and the highest qualifying Q.')
        output.addWidget(self.peak_summary)
        self.peak_plot = PlotWidget()
        self.peak_plot.setMinimumHeight(360)
        self.peak_results, self.peak_matches, self.peak_feasible = table([]), table([]), table([])
        tabs = QTabWidget()
        self.general_result_tabs=tabs
        tabs.addTab(self.peak_plot, 'Best spectrum')
        tabs.addTab(self.peak_feasible, 'Highest Q')
        tabs.addTab(self.peak_matches, 'Best response matches')
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
        return dict(holes=self.holes.records(), hole_sync=self.holes.sync_state(), linked_hole=self.holes.linked.isChecked() and not self.target_controls['use_structure_patterns'].isChecked(), bounds=self.target_bounds.records(),
                    **{key: _value(widget) for key, widget in self.target_controls.items()})

    def peak_options(self):
        return dict(bounds=self.bounds.records(), shared_hole=self.shared_hole.options(), search_options={key: _value(widget) for key, widget in self.search_controls.items()},
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
            self.holes.linked.setChecked(bool(options.get('linked_hole', False)))
            self.holes.set_records(holes, options.get('hole_sync'))
            self.target_bounds.set_records(bounds)
            for key, widget in self.target_controls.items():
                if key in options:
                    _set_value(widget, options[key])
            self._target_enabling()
        else:
            self.bounds.set_records(options.get('bounds', []))
            self.shared_hole.restore(options.get('shared_hole',{}))
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
            if field_data_exists(path):
                self.target_plot.draw_figure(field_figure(path))
                self.target_plot.export_figure(path / 'electric_field_maps.png')
            else:
                self.target_plot.clear()
            self.apply_target.setEnabled((self.directory / 'recommended_design.json').is_file())
            q = summary.get('maximum_verified_Q')
            message = f'Highest verified Q found: {float(q):.7g}.' if q else 'No verified design meets all requested limits yet.'
            if summary.get('objective') == 'Response at target':
                value = summary.get('verified_response_at_target')
                message = f"Verified {summary.get('response','response').lower()} at target: {100*value:.6g}%." if value is not None else 'No verified design meets the response threshold yet.'
            elif q:
                message += f" Response: {summary.get('response', 'Absorption')}."
            message += f" {summary.get('new_evaluations', 0)} new evaluations; {summary.get('reused_training_records', 0)} saved spectra and {summary.get('reused_field_records', 0)} field datasets reused."
            self.target_summary.setText(message)
        else:
            frame = _read_csv(self.directory / 'design_results.csv')
            fill_table(self.peak_results, frame.rename(columns={'absorption': 'response_value'}))
            fill_table(self.peak_matches, _read_csv(self.directory / 'matching_best.csv').rename(columns={'absorption':'response_value'}))
            fill_table(self.peak_feasible, _read_csv(self.directory / 'above_target_by_Q.csv').rename(columns={'absorption':'response_value'}))
            spectrum = _read_csv(self.directory / 'best_spectrum.csv')
            threshold = self.search_controls['absorption_target'].value()
            request = self.directory / 'desktop_request.json'
            if request.is_file():
                saved = json.loads(request.read_text(encoding='utf-8'))
                threshold = saved.get('options', {}).get('search_options', {}).get('absorption_target', threshold)
            response = summary.get('response', 'Absorption')
            self.peak_plot.draw_figure(spectrum_figure(spectrum, threshold=threshold, title=f'Best {response.lower()} design found', peak_key={'Absorption':'A','Reflection':'R','Transmission':'T'}[response]))
            self.peak_plot.export_figure(self.directory / 'best_spectrum.png')
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
            message = f'Best {response.lower()} found: {100 * float(best):.8g}%.' if best is not None else 'No evaluated response peak is available.'
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
    routeRequested=pyqtSignal(str)
    def __init__(self, store, parent=None):
        super().__init__(store, 'Optical field tools', '', {'fields'}, parent)
        from PyQt6.QtWidgets import QSlider, QButtonGroup
        self.field_directory = None
        self.layout_.setContentsMargins(0, 0, 0, 0)
        left, center, right = WorkspacePanel(), WorkspacePanel(), QWidget()
        self.setup_panel = left
        self.setup_layout = QVBoxLayout(left)
        self.setup_layout.setContentsMargins(12, 12, 12, 12)
        self.setup_layout.addWidget(_label('Simulation Setup'))
        maps_layout, export_layout = QVBoxLayout(center), QVBoxLayout(right)
        maps_layout.setContentsMargins(10, 12, 10, 12)
        export_layout.setContentsMargins(0, 0, 0, 0)
        inputs, form = _group('Field calculation')
        self.wavelength = number(1550, .000001)
        self.wavelength.setSuffix(' nm')
        self.layer = QComboBox()
        self.grid = integer(25, 3, 2147483647)
        self.depth = integer(3, 3, 2147483647)
        self.component = _combo([('|E|', 'E2'), ('Ex', 'Ex'), ('Ey', 'Ey'), ('Ez', 'Ez')])
        self.component.setAccessibleName('Field component')
        self.arrows = _check('Show Re(E) arrows', False)
        self.logarithmic = _check('Log intensity scale', True)
        self.shared_scale = _check('Use shared intensity scale', True)
        form.addRow('Wavelength', self.wavelength)
        form.addRow('Layer', self.layer)
        form.addRow('Grid samples / axis', self.grid)
        form.addRow('Depth samples (XZ)', self.depth)
        component_row = QWidget()
        component_layout = QHBoxLayout(component_row)
        component_layout.setContentsMargins(0, 0, 0, 0)
        component_layout.setSpacing(4)
        self.component_buttons = QButtonGroup(self)
        for index, title in enumerate(('|E|', 'Ex', 'Ey', 'Ez')):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.component_buttons.addButton(button, index)
            component_layout.addWidget(button)
        self.component_buttons.idClicked.connect(self.component.setCurrentIndex)
        self.component.currentIndexChanged.connect(lambda index: self.component_buttons.button(index).setChecked(True) if self.component_buttons.button(index) else None)
        self.component.hide()
        form.addRow('Field component', component_row)
        form.addRow(self.logarithmic)
        form.addRow(self.shared_scale)
        form.addRow(self.arrows)
        form.addRow(self.actions('Calculate field maps', self.run))
        self.setup_layout.addWidget(inputs)
        self.setup_layout.addWidget(_button('Edit shared optical excitation',lambda:self.routeRequested.emit('optical.incident')))
        status_box = QGroupBox('Run status')
        status_body = QVBoxLayout(status_box)
        self.run_log = QPlainTextEdit()
        self.run_log.setReadOnly(True)
        self.run_log.setPlaceholderText('Ready')
        self.run_log.setMinimumHeight(100)
        self.run_log.setMaximumHeight(180)
        status_body.addWidget(self.run_log)
        status_body.addWidget(self.progress_bar)
        status_body.addWidget(self.status)
        self.setup_layout.addWidget(status_box, 1)
        maps_layout.addWidget(_label('Field Maps'))
        self.tabs = QTabWidget()
        current = QWidget()
        plot_layout = QVBoxLayout(current)
        plot_layout.setContentsMargins(0, 8, 0, 0)
        class FieldPlot(PlotWidget):
            def fit_canvas(self):
                if self.canvas is not None:
                    self.canvas.setFixedSize(max(1, self.canvas_host.width()), max(1, self.canvas_host.height()))
            def draw_figure(self, figure=None):
                super().draw_figure(figure)
                self.toolbar.hide()
            def retheme(self):
                super().retheme()
                self.toolbar.hide()
        self.plot = FieldPlot()
        self.plot.setMinimumHeight(340)
        empty = Figure(figsize=(8, 8), layout='constrained')
        for axis, title in zip(empty.subplots(1, 2), ('XY plane · selected layer', 'XZ plane · full stack')):
            axis.set_title(title)
            axis.text(.5, .5, 'No field samples', ha='center', va='center', transform=axis.transAxes)
            axis.set_axis_off()
        self.plot.draw_figure(empty)
        plot_layout.addWidget(self.plot, 1)
        controls = QGroupBox('Map overlays')
        control_form = QFormLayout(controls)
        self.contour = QSlider(Qt.Orientation.Horizontal)
        self.contour.setRange(-60, 0)
        self.contour.setValue(-20)
        self.contour.setAccessibleName('Intensity contour threshold in decibels')
        self.contour_enabled = _check('Contour level', False)
        self.contour_value = QLabel('-20 dB')
        row = QWidget(); row_layout = QHBoxLayout(row); row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.contour, 1); row_layout.addWidget(self.contour_value)
        control_form.addRow(self.contour_enabled, row)
        plot_layout.addWidget(controls)
        self.tabs.addTab(current, 'Current structure')
        from qt_field_compare import FieldComparisonWidget
        self.comparison = FieldComparisonWidget(store)
        self.tabs.addTab(_scroll(self.comparison), 'Compare saved fields')
        from qt_field_volume import FieldVolumeWidget
        self.volume = FieldVolumeWidget(store)
        self.tabs.addTab(self.volume, '3D field playback')
        maps_layout.addWidget(self.tabs, 1)
        exports, export_form = _group('Export and Save')
        export_form.addRow(_button('Export PNG…', self.export_image))
        export_form.addRow(_button('Export CSV…', self.export_data))
        export_form.addRow(_button('Copy field maps', self.copy_plot))
        export_form.addRow(_button('Open saved result', self.open_results))
        export_layout.addWidget(exports)
        comparison_box, comparison_form = _group('Field comparison')
        comparison_form.addRow('Reference field', self.comparison.reference)
        comparison_form.addRow('Candidate field', self.comparison.current)
        comparison_form.addRow('Coordinate system', self.comparison.alignment)
        comparison_form.addRow('Layer reference', self.comparison.layer)
        comparison_form.addRow(self.comparison.compare)
        self.comparison.compare.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        export_layout.addWidget(comparison_box)
        # Move dataset selectors into the reference's persistent right column.
        compare_root = self.comparison.layout()
        compare_root.itemAt(0).widget().hide()
        compare_root.itemAt(1).widget().hide()
        self.comparison.plot.setMinimumHeight(340)
        self.comparison.plot.toolbar.hide()
        measurements, measurement_form = _group('Field measurements')
        self.maximum = QLabel('—')
        self.sample_count = QLabel('—')
        self.saved_wavelength = QLabel('—')
        measurement_form.addRow('Max |E|', self.maximum)
        measurement_form.addRow('Field samples', self.sample_count)
        measurement_form.addRow('Wavelength', self.saved_wavelength)
        export_layout.addWidget(measurements)
        export_layout.addStretch()
        self.panels = _ResponsiveSplitter(Qt.Orientation.Horizontal)
        self.panels.reference_ratios = (.30, .50, .20)
        left.setMinimumWidth(320); center.setMinimumWidth(420); right.setMinimumWidth(235)
        self.panels.addWidget(left); self.panels.addWidget(center); self.panels.addWidget(_scroll(right))
        self.panels.setSizes([400, 680, 280])
        self.layout_.addWidget(self.panels, 1)
        for widget in (self.component, self.arrows, self.logarithmic, self.shared_scale, self.contour_enabled):
            _on_edit(widget, self.render_fields)
        self.contour.valueChanged.connect(self.render_fields)
        for widget in (self.wavelength, self.layer, self.grid, self.depth):
            _on_edit(widget, self.persist_options)
        store.changed.connect(self.refresh)
        store.progress.connect(self.record_progress)
        self.refresh()
        saved = getattr(store, 'search_state', {}).get('fields', {})
        for key, widget in [('wavelength_nm', self.wavelength), ('layer', self.layer), ('grid', self.grid), ('depth_samples', self.depth)]:
            if key in saved:
                _set_value(widget, saved[key])
        self.tool_tabs={'current':[(self.tabs,0)],'compare':[(self.tabs,1)],
            'compare.conditions':[(self.tabs,1),(self.comparison.tabs,0)],
            'compare.measurements':[(self.tabs,1),(self.comparison.tabs,1)],
            'volume':[(self.tabs,2)]}
        from qt_tool_workspace import polish_tool_workspace
        polish_tool_workspace(self)

    def select_tool_tab(self,route):
        from qt_tool_workspace import select_tool_tab
        return select_tool_tab(self,route)

    def record_progress(self, event):
        if event.get('run_kind') in self.kinds:
            self.run_log.appendPlainText(str(event.get('text') or event.get('message') or 'Calculating…'))

    def refresh(self, reason=None):
        choices = [('Automatic · first patterned layer', '')] + [(row['Name'], row['Name']) for row in self.store.layers.to_dict('records')[1:-1]]
        _choices(self.layer, choices, self.layer.currentData())
        if reason == 'project':
            saved = getattr(self.store, 'search_state', {}).get('fields', {})
            for key, widget, default in [('wavelength_nm', self.wavelength, 1550), ('layer', self.layer, ''), ('grid', self.grid, 25), ('depth_samples', self.depth, 3)]:
                _set_value(widget, saved.get(key, default))

    def persist_options(self, *_):
        try:
            self.store.save_search('fields', self.options())
        except Exception as exc:
            self.status.setText(f'Could not save the field settings: {exc}')

    def options(self):
        return dict(wavelength_nm=self.wavelength.value(), layer=self.layer.currentData() or '', grid=self.grid.value(), depth_samples=self.depth.value())

    def run(self):
        self._start('fields', self.options())

    def export_image(self):
        if self.field_directory is None:
            self.status.setText('Calculate or open a field result before exporting an image.')
            return
        self.plot.export_dialog()

    def export_data(self):
        if self.field_directory is None:
            self.status.setText('Calculate a field result before exporting data.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export field samples', 'electric-fields.csv', 'CSV data (*.csv)')
        if path:
            try:
                export_field_csv(self.field_directory, path)
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
        self.contour_value.setText(f'{self.contour.value()} dB')
        if self.field_directory is None:
            return
        try:
            figure = field_figure(self.field_directory, self.component.currentData(), self.arrows.isChecked(), self.logarithmic.isChecked(), amplitude=True)
            figure.set_size_inches(8, 8)
            # XZ spans the full saved stack; retain its physical ticks while
            # allowing a deep substrate to remain visible in the map panel.
            figure.axes[1].set_aspect('auto')
            frame = load_field_frame(self.field_directory)
            component = self.component.currentData()
            if component != 'E2':
                frame[component] = frame[component + '_real'] ** 2 + frame[component + '_imag'] ** 2
            maximum = float(frame[component].max()) if not frame.empty else 0.
            if self.shared_scale.isChecked():
                from matplotlib.colors import Normalize
                values = np.sqrt(np.maximum(frame[component].to_numpy(), 0))
                if self.logarithmic.isChecked():
                    values = np.log10(np.maximum(values, 1e-16))
                norm = Normalize(float(np.min(values)), float(np.max(values)) or 1.)
                for axis in figure.axes[:2]:
                    if axis.collections:
                        axis.collections[0].set_norm(norm)
            if self.contour_enabled.isChecked() and maximum > 0:
                threshold = maximum * 10 ** (self.contour.value() / 10.)
                for axis, plane, vertical in ((figure.axes[0], 'xy', 'y_um'), (figure.axes[1], 'xz', 'z_um')):
                    data = frame[frame.plane == plane]
                    if data.empty:
                        continue
                    grid = data.pivot(index=vertical, columns='x_um', values=component).sort_index()
                    if min(grid.shape) >= 2 and float(grid.min().min()) < threshold < float(grid.max().max()):
                        axis.contour(grid.columns, grid.index, grid.to_numpy(), levels=[threshold], colors='white', linestyles='dashed', linewidths=1.2)
            self.plot.draw_figure(figure)
            self.maximum.setText(f'{np.sqrt(maximum):.5g}')
            self.sample_count.setText(f'{len(frame):,}')
            snapshot = self.field_directory / 'field_model.json'
            saved = json.loads(snapshot.read_text(encoding='utf-8')) if snapshot.is_file() else {}
            value = saved.get('wavelength_nm')
            self.saved_wavelength.setText(f'{float(value):g} nm' if value is not None else '—')
        except Exception as exc:
            self.status.setText(f'Field display failed: {exc}')

    def show_result(self, event):
        self.field_directory = self.directory / 'fields'
        self.render_fields()
        self.plot.export_figure(self.field_directory / 'electric_field_maps.png')
        from gpu_status import acceleration_summary
        info = event.get('summary', {}).get('field_features', {}).get('acceleration', {})
        warnings=info.get('warnings', [])
        self.status.setText('Field maps and complex samples saved. ' + acceleration_summary(info) + ' ' + ('Warnings: '+' '.join(warnings)+' ' if warnings else '') + f' Saved to {self.directory}')


class SettingsPage(_RunPage):
    @staticmethod
    def _note(text):
        label=QLabel(text);label.setWordWrap(True);label.setObjectName('muted')
        return label

    @staticmethod
    def _card(title,pairs=()):
        from PyQt6.QtWidgets import QFrame
        panel=WorkspacePanel();layout=QVBoxLayout(panel);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        heading=QLabel(title);heading.setObjectName('sectionTitle');heading.setContentsMargins(14,10,14,10)
        layout.addWidget(heading)
        line=QFrame();line.setObjectName('builderSeparator');line.setFixedHeight(1);layout.addWidget(line)
        body=QWidget();form=QFormLayout(body);form.setContentsMargins(14,12,14,14)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows);form.setHorizontalSpacing(12);form.setVerticalSpacing(10)
        for label,widget in pairs:form.addRow(label,widget)
        layout.addWidget(body)
        return panel,form

    class _SettingsTabs(QTabWidget):
        def minimumSizeHint(self):
            current = self.currentWidget()
            return QSize(0, current.minimumSizeHint().height() if current is not None else 0)

        def sizeHint(self):
            return QSize(1000, max(680, self.minimumSizeHint().height()))

    def __init__(self, store, parent=None):
        super().__init__(store, 'Settings', 'Customize appearance, data storage, accuracy and parallel execution.', {'diagnostic'}, parent)
        self.setObjectName('settingsWorkspace')
        self._execution_initialized=False
        self._execution_draft=False
        self._pending_storage=None
        left, right = QWidget(), QWidget()
        controls, details = QVBoxLayout(left), QVBoxLayout(right)
        controls.setContentsMargins(0,0,0,0);details.setContentsMargins(0,0,0,0)
        from desktop_runtime import default_data_directory, saved_data_directory
        self.data_directory = QLineEdit(str(saved_data_directory() or default_data_directory()))
        self.data_directory.setAccessibleName('Data output folder')
        storage, storage_form = self._card('Data output folder', [('Folder for saved data', self.data_directory)])
        storage_form.addRow(self._note('Current active library: ' + str(store.library.root)))
        storage_form.addRow(_button('Browse…', self.browse_data_directory))
        storage_form.addRow(_button('Use folder beside the program', self.default_data_directory))
        save_folder=_button('Save data folder', self.save_data_directory)
        save_folder.setToolTip('Changes apply after restarting. Existing data stays in its current folder. Select that folder again to reopen it, or use Saved work to export/import a backup.')
        storage_form.addRow(save_folder)
        self.storage_note = ActionStatusLabel('')
        storage_form.addRow(self.storage_note)
        self.save_folder_button=save_folder
        self.basis = integer(32, 1, 4096)
        accuracy, form = self._card('Optical accuracy', [('Fourier basis count', self.basis)])
        form.addRow(self._note('Larger basis counts can resolve finer features and cost more memory and time. Check convergence before accepting a final Q estimate.'))
        controls.addWidget(accuracy)
        cpus = os.cpu_count() or 1
        self.controls = {
            'solver_backend': _combo([('S4 native (recommended)', 'native'),
                                      ('GPU scattering (eigenfree)', 'eigenfree-gpu')], 'native'),
            'mirror_symmetry': _check('Use exact mirror symmetry', True),
            'eigenfree_batch_size': integer(32, 1, 256),
            'mode': _combo(MODES), 'workers': integer(0, 0, cpus), 'threads': integer(1, 1, cpus),
            'gpu_device': integer(0, 0, 1024), 'gpu_min_n': integer(1024, 1, 2147483647),
            'gpu_block': _combo([(str(value), value) for value in (64, 128, 256, 512, 1024)], 256),
            'chunk_size': integer(8, 1, 10000), 'timeout_seconds': integer(3600, 1, 2147483647),
            'require_gpu': _check('Require successful GPU work', False),
        }
        runtime, form = self._card('CPU resources', [(label, self.controls[key]) for label, key in
            [('Execution mode', 'mode'), ('CPU workers (0 = automatic)', 'workers'), ('Threads per worker', 'threads'),
             ('Wavelengths per work chunk', 'chunk_size'),('Run timeout (seconds)', 'timeout_seconds')]])
        controls.addWidget(runtime)
        controls.addWidget(self._note(f'{cpus} logical CPUs available. Worker count × threads per worker cannot exceed this count.'))
        self.execution_note=self._note('Changes remain a draft until you apply them to the current setup or save defaults for new projects.')
        controls.addWidget(self.execution_note)
        draft_actions=QWidget();draft_layout=QVBoxLayout(draft_actions);draft_layout.setContentsMargins(0,0,0,0)
        self.apply_resources_button=_button('Apply to current setup',self.save_settings,True)
        self.save_defaults_button=_button('Save defaults for new projects',self.save_execution_defaults)
        self.load_resources_button=_button('Load current setup',self.load_current_settings)
        for button in (self.apply_resources_button,self.save_defaults_button,self.load_resources_button):draft_layout.addWidget(button)
        controls.addWidget(draft_actions)
        controls.addStretch()
        gpu_resources,gpu_form=self._card('GPU resources',[(label,self.controls[key]) for label,key in
            [('CUDA device index','gpu_device'),('Minimum GPU matrix size','gpu_min_n'),('GPU tile size','gpu_block'),
             ('GPU wavelengths per batch','eigenfree_batch_size')]])
        gpu_form.addRow(self.controls['require_gpu'])
        gpu_form.addRow(_button('Apply GPU small-matrix preset',self.small_matrices))
        details.addWidget(gpu_resources)
        self.gpu_note = _label('')
        details.addWidget(self.gpu_note)
        details.addStretch()
        engine_left,engine_right=QWidget(),QWidget()
        engines,diagnostic_layout=QVBoxLayout(engine_left),QVBoxLayout(engine_right)
        engines.setContentsMargins(0,0,0,0);diagnostic_layout.setContentsMargins(0,0,0,0)
        native,native_form=self._card('S4 · periodic optical solver',[('S4 backend',self.controls['solver_backend'])])
        native_form.addRow(self.controls['mirror_symmetry'])
        native_form.addRow(self._note('S4 simulates one periodic cell or a periodic supercell. The device-footprint option repeats that footprint in X and Y. Phase requires the native backend.'))
        native_form.addRow(self.actions('Apply && check selected runtime',self.run));engines.addWidget(native)
        electrical,electrical_form=self._card('Electrical · finite device electrostatics')
        electrical_form.addRow(self._note('The finite volume electrical solver runs locally with SciPy. Semiconductor Poisson and fixed-charge models share the canonical device. I–V is a frozen-conductivity estimate; C–V is a terminal-charge derivative.'))
        engines.addWidget(electrical)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setPlaceholderText('Run the diagnostic to verify the selected solver and its actual CPU/GPU work.')
        diagnostic_panel=WorkspacePanel();diagnostic_body=QVBoxLayout(diagnostic_panel)
        diagnostic_title=_label('Actual runtime diagnostic');diagnostic_title.setObjectName('sectionTitle');diagnostic_body.addWidget(diagnostic_title)
        diagnostic_body.addWidget(self.diagnostics,1);diagnostic_layout.addWidget(diagnostic_panel,1)
        diagnostic_layout.addWidget(self._note('Availability is verified by an actual solve when you press Check. Native-library files alone do not confirm a working CUDA device. GPU scattering needs compatible NVIDIA drivers and lossless uniform exterior layers.'))
        from qt_appearance import AppearancePage
        from PyQt6.QtWidgets import QSizePolicy, QFrame, QButtonGroup
        self.settings_tabs = self._SettingsTabs()
        self.settings_tabs.setObjectName('settingsStack')
        self.settings_tabs.tabBar().hide()
        self.settings_tabs.setMinimumWidth(0)
        self.settings_tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.settings_tabs.setStyleSheet('QTabWidget#settingsStack::pane { border:0; background:transparent; }')
        self.appearance_page = AppearancePage(store=store)
        self.settings_tabs.addTab(self.appearance_page, 'Appearance')
        resources_split=_split(left,right);resources_split.reference_ratios=(.5,.5)
        self.settings_tabs.addTab(resources_split, 'Execution defaults')
        storage_page = QWidget()
        storage_layout=QVBoxLayout(storage_page);storage_layout.setContentsMargins(0,0,0,0);storage_layout.addWidget(storage)
        export_box,export_form=self._card('Backups & saved outputs')
        export_form.addRow(self._note('Backups include saved simulations, material presets, and optical datasets. Import merges verified data. Per-run CSV, NPZ, VTK and figure exports are available from Results.'))
        self.include_source=_check('Include application source in whole-library backup',False);export_form.addRow(self.include_source)
        self.export_library_button=_button('Export whole library…',self.export_storage)
        self.import_library_button=_button('Import library backup…',self.import_storage)
        export_form.addRow(self.export_library_button);export_form.addRow(self.import_library_button)
        export_form.addRow(_button('Open active library folder',self.open_storage_folder))
        storage_layout.addWidget(export_box);storage_layout.addStretch()
        self.settings_tabs.addTab(storage_page, 'Storage & exports')
        from qt_addons import AddonsPage
        self.addons_panel = AddonsPage(store=store)
        # Keep the existing add-on controller and runtime signals. The complete
        # Meep controls belong beside other solvers, rather than below downloads.
        self.addons_panel.layout().removeWidget(self.addons_panel.meep_container)
        self.addons_panel.meep_container.layout().itemAt(0).widget().hide()
        meep_card,meep_form=self._card('Meep · FDTD engine')
        self.addons_panel.meep_container.setTitle('')
        self.addons_panel.meep_container.setStyleSheet('QGroupBox {border:0; margin:0; padding:0;}')
        meep_form.addRow(self.addons_panel.meep_container);engines.addWidget(meep_card)
        engines.addStretch()
        engine_split=_split(engine_left,engine_right);engine_split.reference_ratios=(.62,.38)
        self.settings_tabs.addTab(engine_split,'Solver runtimes')
        self._runtime_button_rows=[]
        if hasattr(self.addons_panel,'meep_settings'):
            meep=self.addons_panel.meep_settings;meep.installEventFilter(self)
            for row in meep.findChildren(QHBoxLayout):
                if row.count() and all(isinstance(row.itemAt(index).widget(),QPushButton) for index in range(row.count())):
                    self._runtime_button_rows.append(row)
        self.settings_tabs.addTab(_scroll(self.addons_panel), 'Add-ons')
        self.section_indexes={'appearance':0,'resources':1,'execution_defaults':1,'storage':2,'exports':2,'runtimes':3,'engines':3,'addons':4}
        self.settings_navigation_panel = WorkspacePanel()
        navigation = QVBoxLayout(self.settings_navigation_panel)
        navigation.setContentsMargins(12,18,12,12)
        navigation.setSpacing(8)
        title = QLabel('Settings')
        title.setObjectName('sectionTitle')
        navigation.addWidget(title)
        self.settings_navigation = []
        self.settings_navigation_group = QButtonGroup(self)
        self.settings_navigation_group.setExclusive(True)
        for index,label in enumerate(('Appearance','Execution defaults','Storage & exports','Solver runtimes','Add-ons')):
            control = _button(label.replace('&','&&'),lambda checked=False,i=index:self.settings_tabs.setCurrentIndex(i))
            control.setProperty('settingsNav',True)
            control.setCheckable(True)
            self.settings_navigation_group.addButton(control)
            control.setIconSize(QSize(23,23))
            control.setAccessibleName(label+' settings')
            navigation.addWidget(control)
            self.settings_navigation.append(control)
            line = QFrame()
            line.setObjectName('builderSeparator')
            line.setFixedHeight(1)
            navigation.addWidget(line)
        navigation.addStretch(1)
        self.settings_host = QWidget()
        self.settings_columns = QHBoxLayout(self.settings_host)
        self.settings_columns.setContentsMargins(0,0,0,0)
        self.settings_columns.setSpacing(10)
        self.settings_columns.addWidget(self.settings_navigation_panel)
        self.settings_columns.addWidget(self.settings_tabs,1)
        self.settings_scroll = _scroll(self.settings_host)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_tabs.currentChanged.connect(self._sync_settings_navigation)
        from qt_common import theme_manager
        self.refresh_tab_icons()
        theme_manager().changed.connect(self.refresh_tab_icons)
        self.layout_.addWidget(self.settings_scroll,1)
        self.layout_.setContentsMargins(8,8,8,8)
        self._sync_settings_navigation(0)
        self.footer()
        self.basis.valueChanged.connect(self.edit_resources)
        for widget in self.controls.values():
            if isinstance(widget,QComboBox):widget.currentIndexChanged.connect(self.edit_resources)
            elif isinstance(widget,QCheckBox):widget.toggled.connect(self.edit_resources)
            else:widget.valueChanged.connect(self.edit_resources)
        store.changed.connect(self.refresh)
        store.task_finished.connect(self.storage_task_finished)
        store.task_failed.connect(self.storage_task_failed)
        self.refresh()

    def refresh_tab_icons(self, *_):
        from qt_icons import navigation_icon
        from qt_common import COLORS, theme_manager
        for index, name in enumerate(('appearance', 'performance', 'storage', 'Simulate', 'addons')):
            icon = navigation_icon('Settings' if index==0 else name, COLORS[theme_manager().mode]['accent'])
            self.settings_tabs.setTabIcon(index, icon)
            self.settings_navigation[index].setIcon(icon)
        c = COLORS[theme_manager().mode]
        density = theme_manager().effective_scale
        self.settings_navigation_panel.setStyleSheet(f'''
            QPushButton[settingsNav="true"] {{ background:transparent; border:1px solid transparent;
                border-radius:7px; text-align:left; padding:{round(12*density)}px {round(9*density)}px;
                min-height:{round(25*density)}px; font-weight:400; }}
            QPushButton[settingsNav="true"]:hover {{ background:{c['hover']}; }}
            QPushButton[settingsNav="true"]:checked {{ background:{c['select']}; border:1px solid {c['accent']};
                color:{c['text']}; font-weight:500; }}
        ''')

    def _sync_settings_navigation(self,index):
        for row,control in enumerate(self.settings_navigation):
            with QSignalBlocker(control):control.setChecked(row==index)
        QTimer.singleShot(0,self._layout_runtime_buttons)

    def _layout_runtime_buttons(self):
        from PyQt6.QtWidgets import QBoxLayout
        meep=getattr(getattr(self,'addons_panel',None),'meep_settings',None)
        if meep is None:return
        direction=QBoxLayout.Direction.TopToBottom if meep.width()<620 else QBoxLayout.Direction.LeftToRight
        for row in getattr(self,'_runtime_button_rows',[]):
            if row.direction()!=direction:row.setDirection(direction)

    def eventFilter(self,watched,event):
        from PyQt6.QtCore import QEvent
        if event.type()==QEvent.Type.Resize and watched is getattr(getattr(self,'addons_panel',None),'meep_settings',None):
            QTimer.singleShot(0,self._layout_runtime_buttons)
        return super().eventFilter(watched,event)

    def select_section(self,section):
        """Stable menu/context routes, including older settings aliases."""
        text=str(section).casefold().replace('_','-')
        focus=None
        if 'meep' in text or 'runtime' in text or 'engine' in text:
            index=3
            if 'meep' in text:focus=getattr(getattr(self.addons_panel,'meep_settings',None),'check_button',None)
        elif 'add-on' in text or 'addons' in text:
            index=4
            for name,(_,button) in self.addons_panel.cards.items():
                if name.replace('_','-') in text:focus=button;break
        elif 'storage' in text or 'export' in text:index=2
        elif 'performance' in text or 'resource' in text or 'execution' in text:index=1
        elif 'appearance' in text or text=='settings':index=0
        else:return False
        self.settings_tabs.setCurrentIndex(index)
        if focus is not None:
            QTimer.singleShot(0,lambda:(self.settings_scroll.ensureWidgetVisible(focus),focus.setFocus()))
        return True

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'settings_navigation_panel'):
            self.settings_navigation_panel.setFixedWidth(250 if self.width()>=1280 else 190 if self.width()>=850 else 154)
            compact = self.width()<850
            self.settings_navigation_panel.layout().setContentsMargins(8 if compact else 12,18,8 if compact else 12,12)
            for control in self.settings_navigation:
                control.setIconSize(QSize(19,19) if compact else QSize(23,23))

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
            if self.store.busy:
                raise ValueError('Wait for the active operation to finish before changing storage.')
            if not self.data_directory.text().strip():
                raise ValueError('Choose a folder first.')
            target = save_data_directory(self.data_directory.text().strip())
            self.storage_note.setText(f'Saved. Restart the application to use {target}. Existing data has not been moved.')
        except Exception as exc:
            self.storage_note.setText('Could not save the data folder: ' + str(exc))

    def refresh(self, *_):
        if not self._execution_initialized:
            self._execution_initialized=True
            saved=self.saved_execution_defaults()
            settings=saved.get('settings',self.store.settings)
            perf=saved.get('performance',self.store.performance)
            _set_value(self.basis,settings.get('NumG',32))
            for key,widget in self.controls.items():
                if key in perf:_set_value(widget,perf[key])
            self._last_resource_backend=self.controls['solver_backend'].currentData()
        self._refresh_resource_availability()

    def _refresh_resource_availability(self):
        mode = self.controls['mode'].currentData()
        eigenfree = self.controls['solver_backend'].currentData() == 'eigenfree-gpu'
        gpu = eigenfree or mode != MODES[0]
        for key in ('gpu_device', 'gpu_min_n', 'gpu_block', 'require_gpu'):
            self.controls[key].setEnabled(gpu and (not eigenfree or key in ('gpu_device','require_gpu')))
        self.controls['mode'].setEnabled(not eigenfree)
        self.controls['workers'].setEnabled(not eigenfree and mode != MODES[2])
        self.controls['chunk_size'].setEnabled(not eigenfree)
        self.controls['eigenfree_batch_size'].setEnabled(eigenfree)
        threshold = self.controls['gpu_min_n'].value()
        if eigenfree:
            self.gpu_note.setText(f'Fourier basis: {self.basis.value():,}. GPU scattering batch: '
                f"{self.controls['eigenfree_batch_size'].value():,} wavelengths. Exact symmetry is applied when eligible. "
                'Each wavelength is calculated directly. Full 3D fields are retained; field jobs use smaller batches to bound memory. '
                'Check selected runtime verifies an actual GPU solve.')
            return
        self.gpu_note.setText(f'Fourier basis: {self.basis.value():,}. GPU offload threshold: {threshold:,}. '
            'All dimensions of a matrix product must meet the threshold. Small structures may otherwise stay on the CPU. '
            'The runtime diagnostic uses threshold 1 to verify actual GPU work; it does not change your run threshold.')

    @staticmethod
    def saved_execution_defaults():
        """Validated app preferences for explicitly creating a fresh project."""
        from qt_common import preferences
        from qt_core import desktop_performance
        try:
            value=json.loads(str(preferences().value('execution_defaults_v1','{}')))
            if not isinstance(value,dict) or not value:return {}
            basis=value['settings']['NumG']
            if isinstance(basis,bool) or int(basis)!=basis or not 1<=basis<=4096:raise ValueError('Invalid basis')
            return {'settings':{'NumG':int(basis)},'performance':desktop_performance(value['performance'])}
        except (ValueError,TypeError,KeyError,OverflowError):return {}

    def edit_resources(self,*_):
        backend=self.controls['solver_backend'].currentData()
        previous=getattr(self,'_last_resource_backend',backend)
        if backend!=previous:
            if backend=='eigenfree-gpu':
                self._native_resources=(self.controls['mode'].currentData(),self.controls['workers'].value())
                _set_value(self.controls['mode'],MODES[2]);_set_value(self.controls['workers'],1)
            else:
                mode,workers=getattr(self,'_native_resources',(MODES[0],0))
                _set_value(self.controls['mode'],mode);_set_value(self.controls['workers'],workers)
        self._last_resource_backend=backend;self._execution_draft=True
        self.execution_note.setText('Unsaved execution draft. Apply to current setup changes this project. Save defaults is used when creating new projects.')
        self._refresh_resource_availability()

    def load_current_settings(self):
        for key,widget in self.controls.items():
            if key in self.store.performance:_set_value(widget,self.store.performance[key])
        _set_value(self.basis,self.store.settings.get('NumG',32))
        self._last_resource_backend=self.controls['solver_backend'].currentData();self._execution_draft=False
        self.execution_note.setText('Loaded the current project. Edits remain a draft until explicitly applied or saved as defaults.')
        self._refresh_resource_availability()

    def save_execution_defaults(self):
        from qt_common import preferences
        from qt_core import desktop_performance
        try:
            perf={key:_value(widget) for key,widget in self.controls.items()}
            perf['eigenfree_symmetry']=perf['mirror_symmetry']
            if perf['solver_backend']=='eigenfree-gpu':perf.update(mode=MODES[2],workers=1)
            if perf['mode']==MODES[0]:perf['require_gpu']=False
            value={'settings':{'NumG':self.basis.value()},'performance':desktop_performance(perf)}
            settings=preferences();settings.setValue('execution_defaults_v1',json.dumps(value,allow_nan=False));settings.sync()
            from PyQt6.QtCore import QSettings
            if settings.status()!=QSettings.Status.NoError:raise OSError('Desktop preferences could not be written')
            self._execution_draft=False;self.execution_note.setText('Defaults saved for new projects. The current project keeps its applied execution settings.')
            self.status.setText('Saved execution defaults for new projects.')
            return True
        except Exception as exc:
            self.status.setText('Could not save execution defaults: '+str(exc));return False

    def _busy(self,busy):
        super()._busy(busy)
        for name in ('apply_resources_button','save_folder_button','export_library_button','import_library_button','load_resources_button'):
            widget=getattr(self,name,None)
            if widget is not None:widget.setEnabled(not busy)

    def open_storage_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.library.root)))

    def export_storage(self):
        if self.store.busy:return
        filename,_=QFileDialog.getSaveFileName(self,'Export library backup','optical-design-studio-library.zip','ZIP archives (*.zip)')
        if not filename:return
        try:self.store.save_project()
        except Exception as exc:self.status.setText('Could not save the project for backup: '+str(exc));return
        from desktop_runtime import source_root
        source=source_root() if self.include_source.isChecked() else None
        library=self.store.library
        def export():
            import shutil
            produced=Path(library.export(None,source))
            if produced.resolve()!=Path(filename).resolve():shutil.copy2(produced,filename)
            return {'path':filename}
        self._pending_storage='settings-library-export';self.status.setText('Exporting a verified whole-library backup…')
        self.store.run_task(self._pending_storage,export)

    def import_storage(self):
        if self.store.busy:return
        filename,_=QFileDialog.getOpenFileName(self,'Import library backup','','ZIP archives (*.zip)')
        if not filename:return
        library=self.store.library;self._pending_storage='settings-library-import'
        self.status.setText('Verifying and merging the library backup…')
        self.store.run_task(self._pending_storage,lambda:library.import_bundle(filename))

    def storage_task_finished(self,name,result):
        if name!=self._pending_storage:return
        self._pending_storage=None
        if name=='settings-library-import':
            self.store.notify_library();self.status.setText(f"Imported {result['runs']} saved runs, {result['presets']} material presets and {result['assets']} datasets.")
        else:self.status.setText('Library backup saved: '+result['path'])

    def storage_task_failed(self,name,error):
        if name==self._pending_storage:
            self._pending_storage=None;self.status.setText('Library backup needs attention: '+str(error))

    def save_settings(self, *_):
        # Capture both groups before either update emits the shared refresh signal.
        if self.store.busy:
            self.status.setText('Wait for the active operation to finish before applying execution settings.')
            return False
        perf = {key: _value(widget) for key, widget in self.controls.items()}
        # Backend transitions already update the detached controls in
        # edit_resources. Preserve their restored native CPU values here.
        perf['eigenfree_symmetry'] = perf['mirror_symmetry']
        if perf['solver_backend'] == 'eigenfree-gpu':
            perf.update(mode=MODES[2],workers=1)
        if perf['mode'] == MODES[0]:
            perf['require_gpu'] = False
        basis = self.basis.value()
        try:
            self.store.update_performance(perf)
            self.store.update_settings({'NumG': basis})
        except Exception as exc:
            self.status.setText(f'Could not apply solver settings: {exc}')
            return False
        self._execution_draft=False
        self._last_resource_backend=self.controls['solver_backend'].currentData()
        self.execution_note.setText('Execution settings applied to the current project. Saved defaults for new projects are unchanged.')
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
