"""Shared optical, electrical and coupled setup with saved-result compatibility."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter
from PyQt6.QtCore import Qt, QSignalBlocker, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QLinearGradient
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
    QLineEdit, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
    QGridLayout, QFrame, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
    QDialog, QDialogButtonBox, QScrollArea, QSizePolicy)

from qt_common import PlotWidget, fill_table, integer, number, table, theme_manager, COLORS
from qt_compute import (_ResponsiveSplitter, _RunPage, _button, _check, _combo,
    _group, _label, _on_edit, _scroll, _set_value, _value)
from qt_ranges import _choices
from qt_surfaces import WorkspacePanel
from qt_electrical_results import ElectricalResultsPanel


DEVICE_LAYERS = ('p+ GaAs', 'p GaAs', 'Al0.5Ga0.5As', 'n GaAs', 'n+ GaAs', 'ITO')


def _draw_workflow_icon(painter, kind, rect, color):
    """Crisp vector symbols at the same scale as the approved workspace."""
    import math
    painter.save()
    painter.setPen(QPen(QColor(color), 1.8))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = rect.center().x(), rect.center().y()
    scale = min(rect.width(), rect.height()) / 48
    if kind == 'optical':
        painter.drawEllipse(QPointF(cx, cy), 8*scale, 8*scale)
        for index in range(8):
            angle = index*math.pi/4
            painter.drawLine(QPointF(cx+13*scale*math.cos(angle), cy+13*scale*math.sin(angle)),
                QPointF(cx+20*scale*math.cos(angle), cy+20*scale*math.sin(angle)))
    elif kind == 'electrical':
        points = [(-22, 0), (-13, 0), (-8, -18), (0, 18), (6, -7), (11, 0), (22, 0)]
        for first, second in zip(points, points[1:]):
            painter.drawLine(QPointF(cx+first[0]*scale,cy+first[1]*scale),QPointF(cx+second[0]*scale,cy+second[1]*scale))
    elif kind == 'coupled':
        painter.drawEllipse(QPointF(cx-7*scale, cy-5*scale), 13*scale, 13*scale)
        painter.drawEllipse(QPointF(cx+7*scale, cy+5*scale), 13*scale, 13*scale)
    else:
        for offset in (-7, 0, 7):
            points=[(-14,offset), (0,offset-8), (14,offset), (0,offset+8), (-14,offset)]
            for first,second in zip(points,points[1:]):
                painter.drawLine(QPointF(cx+first[0]*scale,cy+first[1]*scale),QPointF(cx+second[0]*scale,cy+second[1]*scale))
    painter.restore()


class _WorkflowCard(QPushButton):
    """A real navigation button with the reference's large workflow-card face."""
    def __init__(self, kind, selected=False, parent=None):
        super().__init__(parent)
        self.kind=kind
        self.setObjectName('workflowCard')
        self.setCheckable(True)
        self.setChecked(selected)
        self.setMinimumHeight(116)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(kind.title()+' simulation workflow')
        theme_manager().changed.connect(self.update)

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors=COLORS[theme_manager().mode]
        dark=theme_manager().mode=='dark'
        gradient=QLinearGradient(0,0,self.width(),self.height())
        selected=self.isChecked()
        gradient.setColorAt(0,QColor('#123552' if selected and dark else colors['panel']))
        gradient.setColorAt(1,QColor('#0b2c4e' if selected and dark else colors['bg']))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(colors['accent'] if selected else colors['border']),1.5 if selected else 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.8,.8,-.8,-.8),4,4)
        accent=colors['accent'] if selected else colors['text']
        _draw_workflow_icon(painter,self.kind,QRectF(17,13,48,46),accent)
        title=QFont(self.font());title.setPointSizeF(11.5);title.setBold(False)
        painter.setFont(title);painter.setPen(QColor(accent))
        painter.drawText(QRectF(85,10,self.width()-94,24),Qt.AlignmentFlag.AlignVCenter,self.kind.title())
        small=QFont(self.font());small.setPointSizeF(9.1);painter.setFont(small)
        descriptions={'optical':'Light response only','electrical':'DC device physics only','coupled':'Electrical → Optical'}
        painter.setPen(QColor(colors['muted']))
        painter.drawText(QRectF(85,36,self.width()-94,24),Qt.AlignmentFlag.AlignVCenter,descriptions[self.kind])
        painter.setPen(QPen(QColor(colors['muted']),1.3));painter.drawLine(25,73,57,73)
        tiny=QFont(self.font());tiny.setPointSizeF(8.2);painter.setFont(tiny)
        painter.drawText(QRectF(67,62,self.width()-74,24),Qt.AlignmentFlag.AlignVCenter,'Uses shared device & materials')
        painter.setPen(QColor(accent));painter.drawEllipse(QPointF(33,96),6,6)
        painter.drawText(QRectF(29,88,9,15),Qt.AlignmentFlag.AlignCenter,'i')
        subtitles={'optical':'Does not run electrical simulation','electrical':'Requires no optical data','coupled':'Runs electrical first, then optical'}
        painter.setPen(QColor(colors['muted']))
        painter.drawText(QRectF(48,86,self.width()-55,22),Qt.AlignmentFlag.AlignVCenter,subtitles[self.kind])
        painter.end()


class _SequenceStep(QWidget):
    def __init__(self, number_, kind, title, detail, parent=None):
        super().__init__(parent)
        self.number=number_;self.kind=kind;self.state='ready'
        self.setMinimumHeight(94)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        row=QHBoxLayout(self);row.setContentsMargins(106,6,10,6);row.setSpacing(0)
        text=QVBoxLayout();text.setSpacing(3)
        self.title=QLabel(title);self.title.setObjectName('sequenceTitle')
        self.detail=QLabel(detail);self.detail.setObjectName('workspaceMuted');self.detail.setWordWrap(True)
        self.badge=QLabel('Ready to run');self.badge.setObjectName('sequenceBadge');self.badge.setMaximumHeight(22)
        text.addStretch();text.addWidget(self.title);text.addWidget(self.detail);text.addWidget(self.badge,0,Qt.AlignmentFlag.AlignLeft);text.addStretch()
        row.addLayout(text)
        theme_manager().changed.connect(self.update)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors=COLORS[theme_manager().mode]
        accent='#39d799' if self.state=='complete' else colors['accent'] if self.state in ('active','ready') else colors['muted']
        painter.setPen(QPen(QColor(colors['border']),1.1))
        if self.number>1:painter.drawLine(QPointF(16,0),QPointF(16,self.height()/2-16))
        if self.number<4:
            painter.drawLine(QPointF(16,self.height()/2+16),QPointF(16,self.height()))
            painter.setPen(QPen(QColor(colors['accent']),1.4))
            painter.drawLine(12,self.height()-9,16,self.height()-3);painter.drawLine(20,self.height()-9,16,self.height()-3)
        painter.setBrush(QColor(colors['panel']));painter.setPen(QPen(QColor(accent),1.2))
        painter.drawEllipse(QPointF(16,self.height()/2),14,14)
        painter.setPen(QColor(colors['text']));painter.drawText(QRectF(2,self.height()/2-14,28,28),Qt.AlignmentFlag.AlignCenter,str(self.number))
        painter.setPen(QPen(QColor(colors['border']),1.1));painter.drawRoundedRect(QRectF(44,self.height()/2-26,52,52),5,5)
        _draw_workflow_icon(painter,self.kind,QRectF(50,self.height()/2-22,40,44),colors['text'])
        painter.end()

    def set_state(self,state,text):
        self.state=state;self.badge.setText(text);self.update()


def _note(text):
    widget = _label(text, True)
    widget.show()
    return widget


def parse_biases(text):
    """Reject malformed input before starting a worker; keep the entered order."""
    try:
        values = [float(value) for value in text.replace(';', ',').split(',') if value.strip()]
    except ValueError as exc:
        raise ValueError('Enter biases as comma-separated voltages, for example 0, -2.') from exc
    if not values or not np.isfinite(values).all():
        raise ValueError('Bias voltages must be finite numbers.')
    if len(set(values)) != len(values):
        raise ValueError('Enter each bias voltage once.')
    return values


def _saved_path(directory, value):
    """Prefer the run-local copy so saved runs still open after being moved."""
    candidate = Path(value)
    local = directory / candidate.name
    if not candidate.is_absolute():
        local = directory / candidate
    if local.is_file():
        return local
    nested = directory / 'electrical' / candidate.name
    return nested if nested.is_file() else candidate


def electrical_profile_figure(frame, view='Carrier concentration', *, minimum_density=None):
    figure = Figure(figsize=(8, 5), layout='constrained')
    axis = figure.add_subplot(111)
    if frame.empty or 'z_nm' not in frame:
        axis.text(.5, .5, 'No saved electrical profile is available.', ha='center', va='center', transform=axis.transAxes)
        axis.set_axis_off()
        return figure
    groups = frame.groupby('bias_V', sort=False) if 'bias_V' in frame else [('Saved state', frame)]
    for bias, data in groups:
        data = data.sort_values('z_nm')
        label = f'{bias:g} V' if isinstance(bias, (float, int)) else str(bias)
        if view == 'Carrier concentration':
            for key, name, style in [('electrons_cm3', 'electrons', '-'), ('holes_cm3', 'holes', '--'), ('ito_electrons_cm3', 'ITO electrons', ':')]:
                if key in data:
                    y = pd.to_numeric(data[key], errors='coerce').to_numpy(dtype=float)
                    keep = np.isfinite(y) & (y > 0)
                    if minimum_density is not None:
                        keep &= y >= minimum_density
                    if keep.any():
                        axis.plot(data['z_nm'], np.where(keep, y, np.nan), style, label=f'{label} · {name}', linewidth=1.7)
            axis.set_yscale('log')
            if minimum_density is not None:
                axis.set_ylim(bottom=minimum_density)
            axis.set_ylabel('Carrier concentration (cm⁻³)')
        elif 'Ez_V_m' in data:
            axis.plot(data['z_nm'], data['Ez_V_m'] / 1e6, label=label, linewidth=1.7)
            axis.set_ylabel('Depth electric field (MV/m)')
    axis.set_xlabel('Depth from top of electrical device (nm)')
    axis.grid(alpha=.22)
    if axis.lines:
        axis.legend(fontsize=9)
    return figure


def electrical_index_figure(frame, view='Refractive index n'):
    figure = Figure(figsize=(8, 5), layout='constrained')
    axis = figure.add_subplot(111)
    component = 'k' if view == 'Extinction coefficient k' else 'n'
    depth = next((name for name in ('z_nm', 'depth_nm', 'z_start_nm', 'depth_start_nm') if name in frame), None)
    if frame.empty or depth is None:
        axis.text(.5, .5, 'Run with optical R/T/A enabled to save n and k profiles.', ha='center', va='center', transform=axis.transAxes)
        axis.set_axis_off()
        return figure
    series = [key for key in (component, component + '_plus', component + '_minus') if key in frame]
    grouping = [key for key in ('bias_V', 'wavelength_nm') if key in frame]
    groups = frame.groupby(grouping, sort=False) if grouping else [('Saved state', frame)]
    for group, data in groups:
        values = group if isinstance(group, tuple) else (group,)
        labels = [f'{value:g} {"V" if key == "bias_V" else "nm"}' for key, value in zip(grouping, values)]
        for key in series:
            label = ' · '.join(labels + ([key] if len(series) > 1 else [])) or 'Saved state'
            data = data.sort_values(depth)
            axis.plot(data[depth], data[key], label=label, linewidth=1.7)
    axis.set(xlabel='Depth from top of device (nm)', ylabel='Extinction coefficient k' if component == 'k' else 'Refractive index n')
    axis.grid(alpha=.22)
    if axis.lines:
        axis.legend(fontsize=9)
    return figure


def electrical_spectrum_figure(frame, response='R / T / A'):
    figure = Figure(figsize=(8, 5), layout='constrained')
    axis = figure.add_subplot(111)
    if frame.empty or 'wavelength_nm' not in frame:
        axis.text(.5, .5, 'No optical spectrum. Enable Calculate optical R/T/A for a coupled run.', ha='center', va='center', transform=axis.transAxes)
        axis.set_axis_off()
        return figure
    keys = {'Reflection': ['R'], 'Transmission': ['T'], 'Absorption': ['A']}.get(response, ['R', 'T', 'A'])
    groups = frame.groupby('bias_V', sort=False) if 'bias_V' in frame else [('Saved state', frame)]
    angle_sweep = 'angle_deg' in frame and frame['angle_deg'].nunique() > 1 and frame['wavelength_nm'].nunique() == 1
    variable = 'angle_deg' if angle_sweep else 'wavelength_nm'
    for bias, data in groups:
        label = f'{bias:g} V' if isinstance(bias, (float, int)) else str(bias)
        for key in keys:
            if key in data:
                axis.plot(data[variable], data[key], label=f'{label} · {key}', linewidth=1.7)
    axis.set(xlabel='Incidence angle (degrees)' if angle_sweep else 'Wavelength (nm)', ylabel='Incident power (%)', ylim=(0, 1))
    axis.yaxis.set_major_formatter(PercentFormatter(xmax=1))
    axis.grid(alpha=.22)
    if axis.lines:
        axis.legend(fontsize=9)
    return figure


class ElectricalPage(_RunPage):
    selectWorkflow=pyqtSignal(str)
    editDeviceRequested=pyqtSignal()
    resultsRequested=pyqtSignal(object,object)
    opticalRunRequested=pyqtSignal()

    def __init__(self, store, parent=None,workflow='electrical'):
        if workflow not in ('optical','electrical','coupled'):
            raise ValueError('Workflow must be optical, electrical or coupled.')
        self.workflow=workflow
        self.run_kind='simulation' if workflow=='optical' else 'coupled' if workflow=='coupled' else 'electrical'
        super().__init__(store, workflow.title(), 'Simulate the shared device with electrical, optical or coupled physics.', {self.run_kind}, parent)
        self.loading = False
        self.saved_summary = None
        self.saved_profiles = pd.DataFrame()
        self.saved_indices = pd.DataFrame()
        self.saved_spectra = pd.DataFrame()
        self.saved_features = pd.DataFrame()
        self.measured_current = []
        self.layout_.setContentsMargins(8, 10, 8, 10)

        left = QWidget()
        controls = QVBoxLayout(left)
        controls.setContentsMargins(10, 10, 10, 10)
        controls.addWidget(_label('Electrical setup'))
        self.model = _combo([('Editable device from Structure', 'custom_device'), ('Explicit ITO study · experimental', 'explicit_ito'), ('Contacts-only study · ITO sheet', 'contacts_only_sheet')])
        self.charge_model=_combo([('Semiconductor carriers','semiconductor'),('Fixed charge / dielectric','dielectric')])
        self.swept_contact=_combo([('Use last enabled contact','')])
        self.biases = QLineEdit('0, -2')
        self.biases.setToolTip('Bias offsets applied to the selected terminal, relative to its base voltage. A zero-offset reference is included.')
        self.controls = {
            'mesh_level': _combo([('L0 · coarse', 0), ('L1 · refined', 1)]),
            'ito_thickness_nm': number(40, 40, 40, 0),
            'ito_density_cm3': QLineEdit('8e20'),
            'sheet_resistance_ohm_square': number(45, 30, 60, 3),
            'temperature_K': number(300, 300, 300, 0),
            'current_offset': _combo([('Subtract zero-bias offset', 'subtract_zero'), ('Use measured values as plotted', 'as_plotted')]),
            'response': _combo(['Absorption', 'Reflection', 'Transmission']),
            'feature': _combo(['Peak', 'Dip']),
            'reference_nm': number(1157, .000001, 1e9, 6),
            'tracking_window_nm': number(1, .000001, 1e9, 6),
        }
        self.controls['ito_thickness_nm'].setToolTip('The saved electrical geometry currently supports 40 nm ITO.')
        self.controls['ito_density_cm3'].setToolTip('Electron density from 1e20 to 1e21 cm⁻³; nominal saved-device density is 8e20 cm⁻³.')
        device, form = _group('Device and bias', [('Model', self.model), ('Biases (V)', self.biases), ('Mesh', self.controls['mesh_level']), ('Temperature (K)', self.controls['temperature_K'])])
        self.device_form=form
        form.addRow('Charge model',self.charge_model)
        form.addRow('Swept terminal',self.swept_contact)
        self.preset_button = _button('Load device preset into optical project', self.load_preset)
        form.addRow(self.preset_button)
        self.preset_note=_note('')
        form.addRow(self.preset_note)
        controls.addWidget(device)
        self.iv_enabled=_check('Calculate I–V · Ohmic conductivity estimate',False)
        self.cv_enabled=_check('Calculate C–V · electrode charge derivative',False)
        self.measured_iv=QLineEdit();self.measured_cv=QLineEdit()
        studies,studies_form=_group('Terminal studies')
        studies_form.addRow(self.iv_enabled);studies_form.addRow(self.cv_enabled)
        studies_form.addRow(_note('I–V uses a frozen-conductivity estimate, not junction transport or leakage. C–V is the derivative of electrode displacement charge; junction reservoir charging needs a transport/AC model.'))
        studies_form.addRow('Measured I–V CSV',self.measured_iv)
        studies_form.addRow(_button('Choose measured I–V…',lambda:self.choose_terminal_data('iv')))
        studies_form.addRow('Measured C–V CSV',self.measured_cv)
        studies_form.addRow(_button('Choose measured C–V…',lambda:self.choose_terminal_data('cv')))
        controls.addWidget(studies);self.studies_group=studies
        ito, _ = _group('ITO', [('Thickness (nm)', self.controls['ito_thickness_nm']), ('Electron density (cm⁻³)', self.controls['ito_density_cm3']), ('Sheet resistance (Ω/□)', self.controls['sheet_resistance_ohm_square'])])
        controls.addWidget(ito)
        self.ito_group=ito
        self.model_note = _note('')
        controls.addWidget(self.model_note)

        measured, measured_form = _group('Measured current calibration (optional)')
        measured_actions = QHBoxLayout()
        self.import_current_button = _button('Import I–V CSV…', self.import_current)
        measured_actions.addWidget(self.import_current_button)
        measured_actions.addWidget(_button('Clear', self.clear_current))
        measured_form.addRow(measured_actions)
        measured_form.addRow('Current convention', self.controls['current_offset'])
        self.current_note = _note('No measured I–V data loaded. CSV columns: bias_V, current_A.')
        measured_form.addRow(self.current_note)
        controls.addWidget(measured)
        self.measured_group=measured

        self.optical_enabled = _check('Calculate optical R/T/A', False)
        self.optical_enabled.setChecked(workflow=='coupled')
        self.optical_reference = _combo([('Material table contains zero-bias carriers', 'zero_bias'), ('Material table is undoped', 'undoped')])
        self.electro_optic = _check('Include GaAs electro-optic field response', False)
        self.interband = _check('Include experimental GaAs interband response', False)
        self.interband_extrapolation = _check('Allow interband extrapolation at high doping', False)
        self.optical_slices = integer(8, 1, 100)
        optical, optical_form = _group('Carrier-to-optical coupling')
        optical_form.addRow(self.optical_enabled)
        optical_form.addRow('Material reference', self.optical_reference)
        optical_form.addRow(self.electro_optic)
        optical_form.addRow(self.interband)
        optical_form.addRow(self.interband_extrapolation)
        optical_form.addRow('Slices per device layer', self.optical_slices)
        self.s4_note = _note('')
        optical_form.addRow(self.s4_note)
        self.mapping_note=_note('')
        optical_form.addRow(self.mapping_note)
        controls.addWidget(optical)
        self.optical_group=optical
        if workflow!='coupled':optical.hide()
        self.optical_enabled.hide()
        self.mapping = QTableWidget(0, 3)
        self.mapping.setHorizontalHeaderLabels(['Device layer', 'Optical layer', 'Material'])
        self.mapping.verticalHeader().hide()
        self.mapping.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.mapping.setMinimumHeight(230)
        mapping_box = QGroupBox('Layer mapping')
        mapping_layout = QVBoxLayout(mapping_box)
        mapping_layout.addWidget(self.mapping)
        controls.addWidget(mapping_box)
        self.mapping_box=mapping_box
        tracking, _ = _group('Sampled resonance tracking', [('Response', self.controls['response']),
            ('Feature', self.controls['feature']), ('Reference λ (nm)', self.controls['reference_nm']),
            ('Search radius (nm)', self.controls['tracking_window_nm'])])
        controls.addWidget(tracking)
        tracking.setVisible(workflow=='coupled')
        self.tracking_note=_note('Tracks the nearest sampled peak or dip within the search radius and reports wavelength shifts from 0 V. Refine the S4 wavelength step to resolve small shifts.')
        self.tracking_note.setVisible(workflow=='coupled');controls.addWidget(self.tracking_note)
        self.scope_note = _note('Accuracy scope: static Poisson with carrier reservoirs; no drift-diffusion transport or time dynamics. Periodic optics uses a lateral average of the electrical solution. Explicit ITO interfaces remain experimental.')
        controls.addStretch()
        for selector in left.findChildren(QComboBox):
            selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            selector.setMinimumContentsLength(12)

        right = WorkspacePanel()
        output = QVBoxLayout(right)
        output.setContentsMargins(12, 12, 12, 12)
        output.addWidget(_label('Electrical and optical results' if workflow=='coupled' else 'Electrical results'))
        self.summary_label = _note('No electrical result loaded.')
        output.addWidget(self.summary_label)
        output.addWidget(self.scope_note)
        self.tracking_label = _note('')
        output.addWidget(self.tracking_label)
        selectors = QHBoxLayout()
        self.result_bias = _combo([('All biases', None)])
        selectors.addWidget(_label('Curve bias filter'))
        selectors.addWidget(self.result_bias, 1)
        self.curve_filters=QWidget()
        self.curve_filters.setLayout(selectors)
        output.addWidget(self.curve_filters)

        self.profile_view = _combo(['Carrier concentration', 'Electric field'])
        self.profile_full_range = _check('Show carrier concentrations below 10⁸ cm⁻³', False)
        self.index_view = _combo(['Refractive index n', 'Extinction coefficient k'])
        self.result_wavelength = _combo([])
        self.response_view = _combo(['R / T / A', 'Reflection', 'Transmission', 'Absorption'])
        self.profile_plot = PlotWidget()
        self.index_plot = PlotWidget()
        self.spectrum_plot = PlotWidget()
        self.profile_table = table([])
        self.spectrum_table = table([])
        self.feature_table = table([])
        self.checks_table = table([])
        self.result_tabs = QTabWidget()
        self.results_dashboard=ElectricalResultsPanel()
        self.result_tabs.addTab(self.results_dashboard,'Device results')
        for title, selector, plot in [('Carriers / field', self.profile_view, self.profile_plot), ('n / k profile', self.index_view, self.index_plot), ('Optical R/T/A', self.response_view, self.spectrum_plot)]:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 8, 0, 0)
            layout.addWidget(selector)
            if selector is self.profile_view:
                layout.addWidget(self.profile_full_range)
            if selector is self.index_view:
                row = QHBoxLayout()
                row.addWidget(_label('Wavelength'))
                row.addWidget(self.result_wavelength, 1)
                layout.addLayout(row)
            layout.addWidget(plot, 1)
            self.result_tabs.addTab(page, title)
        self.result_tabs.addTab(self.profile_table, 'Electrical data')
        self.result_tabs.addTab(self.spectrum_table, 'Optical data')
        self.result_tabs.addTab(self.feature_table, 'Resonance shifts')
        self.result_tabs.addTab(self.checks_table, 'Electrical checks')
        self.result_tabs.currentChanged.connect(lambda index:self.curve_filters.setVisible(index!=0))
        self.curve_filters.hide()
        for index in (2,3,5,6):self.result_tabs.setTabVisible(index,workflow=='coupled')
        output.addWidget(self.result_tabs, 1)
        self.result_note = _note('Depth profiles are averages over solid semiconductor; concentrations are in cm⁻³ and electric fields are in V/m. Full volumes and convergence checks are saved with each run.')
        output.addWidget(self.result_note)
        result_actions = QHBoxLayout()
        result_actions.addWidget(_button('Load saved electrical result', self.load_saved))
        result_actions.addWidget(_button('Open CSV / result files', self.open_results))
        output.addLayout(result_actions)

        # Saved studies and legacy controls remain available through real dialogs.
        # The default workspace follows the approved three-column composition.
        self._compose_workspace(left,right)
        # Enter commits numeric editors; it must never invoke the example
        # loader just because Qt picked a dialog default action.
        for dialog in (self._legacy_setup_dialog,self._legacy_results_dialog):
            for action in dialog.findChildren(QPushButton):
                action.setAutoDefault(False);action.setDefault(False)
        self.footer()

        for widget in [self.model, self.biases, self.optical_enabled, self.optical_reference, self.electro_optic, self.interband, self.interband_extrapolation, self.optical_slices, *self.controls.values()]:
            _on_edit(widget, self.changed)
        for widget in (self.result_bias, self.profile_view, self.index_view, self.result_wavelength, self.response_view):
            widget.currentIndexChanged.connect(self.redraw_result)
        self.profile_full_range.toggled.connect(self.redraw_result)
        store.changed.connect(self.refresh)
        _on_edit(self.charge_model,self.changed)
        _on_edit(self.swept_contact,self.changed)
        for field in (self.iv_enabled,self.measured_iv,self.measured_cv):_on_edit(field,self.changed)
        self.cv_enabled.toggled.connect(self.cv_changed)
        self.biases.textChanged.connect(self._sync_bias_preview)
        store.library_changed.connect(self.refresh_history)
        store.progress.connect(self.sequence_progress)
        store.run_failed.connect(self.sequence_failed)
        theme_manager().changed.connect(self._apply_workspace_theme)
        self.refresh()
        self.redraw_result()

    def _card(self,title,parent=None):
        card=QFrame(parent);card.setObjectName('simulationCard')
        layout=QVBoxLayout(card);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        heading=QLabel(title);heading.setObjectName('simulationCardHeading');heading.setFixedHeight(39)
        layout.addWidget(heading)
        return card,layout

    def _field_row(self,layout,label,field,*,unit=None):
        row=QHBoxLayout();row.setContentsMargins(0,0,0,0);row.setSpacing(8)
        name=QLabel(label);name.setObjectName('workspaceFieldLabel');name.setFixedWidth(112)
        row.addWidget(name)
        if isinstance(field,QWidget):row.addWidget(field,1)
        else:row.addLayout(field,1)
        if unit:
            suffix=QLabel(unit);suffix.setObjectName('workspaceMuted');suffix.setFixedWidth(22);row.addWidget(suffix)
        layout.addLayout(row)
        return row

    def _compose_workspace(self,legacy_setup,legacy_results):
        from qt_custom_device import DeviceCanvas
        self._legacy_setup_dialog=QDialog(self)
        self._legacy_setup_dialog.setWindowTitle('Advanced study and coupling options')
        self._legacy_setup_dialog.resize(610,720)
        legacy_layout=QVBoxLayout(self._legacy_setup_dialog)
        legacy_layout.addWidget(_scroll(legacy_setup),1)
        legacy_buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        legacy_buttons.rejected.connect(self._legacy_setup_dialog.hide)
        legacy_layout.addWidget(legacy_buttons)
        self._legacy_setup_dialog.hide()
        self._legacy_results_dialog=QDialog(self)
        self._legacy_results_dialog.setWindowTitle('Saved electrical and optical profiles')
        self._legacy_results_dialog.resize(1100,800)
        saved_layout=QVBoxLayout(self._legacy_results_dialog);saved_layout.setContentsMargins(0,0,0,0)
        saved_layout.addWidget(legacy_results)
        self._legacy_results_dialog.hide()

        self.workspace=QWidget();self.workspace.setObjectName('simulationWorkspace')
        grid=QGridLayout(self.workspace);grid.setContentsMargins(0,0,0,0);grid.setHorizontalSpacing(8);grid.setVerticalSpacing(8)
        grid.setColumnStretch(0,18);grid.setColumnStretch(1,57);grid.setColumnStretch(2,25)
        grid.setColumnMinimumWidth(0,230);grid.setColumnMinimumWidth(1,650);grid.setColumnMinimumWidth(2,295)
        grid.setRowStretch(0,0);grid.setRowStretch(1,7);grid.setRowStretch(2,5);grid.setRowStretch(3,0)
        self.layout_.setContentsMargins(10,10,10,8)

        shared,shared_layout=self._card('Shared device   ⌄')
        self.shared_preview=DeviceCanvas('3d');self.shared_preview.setMinimumSize(200,205);self.shared_preview.setMaximumHeight(255)
        self.shared_preview.compact_preview=True
        shared_layout.addWidget(self.shared_preview,3)
        self.edit_device_button=_button('✎  Edit shared device…',self.editDeviceRequested.emit)
        self.edit_device_button.setObjectName('workspaceLink');self.edit_device_button.setFixedHeight(30)
        shared_layout.addWidget(self.edit_device_button)
        summary_heading=QLabel('⌄  Device summary');summary_heading.setObjectName('simulationSectionHeading');summary_heading.setFixedHeight(35)
        shared_layout.addWidget(summary_heading)
        summary=QWidget();summary_rows=QVBoxLayout(summary);summary_rows.setContentsMargins(20,0,14,8);summary_rows.setSpacing(0)
        self.device_summary_labels={}
        for key in ('Geometry','Layers','Materials','Contacts'):
            line=QWidget();line.setObjectName('deviceSummaryRow');line_layout=QHBoxLayout(line);line_layout.setContentsMargins(0,5,0,5)
            title=QLabel(key);title.setObjectName('workspaceMuted');title.setFixedWidth(78)
            value=QLabel('—');value.setWordWrap(True);value.setObjectName('workspaceSmall')
            line_layout.addWidget(title);line_layout.addWidget(value,1)
            summary_rows.addWidget(line);self.device_summary_labels[key]=value
        shared_layout.addWidget(summary)
        self.scope_note.setObjectName('workspaceSmall');self.scope_note.setContentsMargins(12,0,12,7)
        shared_layout.addWidget(self.scope_note)
        left=QWidget();left_layout=QVBoxLayout(left);left_layout.setContentsMargins(0,0,0,0);left_layout.setSpacing(7)
        shared.setMaximumHeight(450)
        left_layout.addWidget(shared,1)
        history,history_layout=self._card('Run history   ⌃')
        self.run_history=QTreeWidget();self.run_history.setHeaderHidden(True);self.run_history.setColumnCount(2)
        self.run_history.setObjectName('simulationHistory');self.run_history.setRootIsDecorated(True);self.run_history.setIndentation(17)
        self.run_history.setMinimumHeight(155);self.run_history.setColumnWidth(0,128)
        self.run_history.itemDoubleClicked.connect(self._open_history_item)
        history_layout.addWidget(self.run_history,1)
        self.load_history_button=_button('Open saved run…',self.load_saved);self.load_history_button.setObjectName('workspaceLink')
        history_layout.addWidget(self.load_history_button)
        left_layout.addWidget(history,1)
        grid.addWidget(left,0,0,4,1)

        cards=QWidget();card_layout=QHBoxLayout(cards);card_layout.setContentsMargins(0,0,0,0);card_layout.setSpacing(8)
        self.workflow_cards={}
        for key in ('optical','electrical','coupled'):
            button=_WorkflowCard(key,key==self.workflow);button.clicked.connect(lambda checked=False,key=key:self.choose_workflow(key))
            self.workflow_cards[key]=button;card_layout.addWidget(button,1)
        grid.addWidget(cards,0,1)

        setups=QWidget();setup_grid=QHBoxLayout(setups);setup_grid.setContentsMargins(0,0,0,0);setup_grid.setSpacing(8)
        electrical,electrical_outer=self._card('ϟ  Electrical setup')
        electrical_inner=QWidget();electrical_form=QVBoxLayout(electrical_inner)
        electrical_form.setContentsMargins(16,10,16,10);electrical_form.setSpacing(7)
        self.study_selector=_combo([('Bias sweep','bias'),('I–V curve','iv'),('C–V curve','cv'),('I–V + C–V curves','both')])
        self.study_selector.currentIndexChanged.connect(self._study_selected)
        self._field_row(electrical_form,'Study',self.study_selector)
        bias_range=QHBoxLayout();bias_range.setSpacing(5)
        self.bias_start=number(0,-1e6,1e6,6);self.bias_stop=number(-2,-1e6,1e6,6)
        self.bias_start.setAccessibleName('First bias offset in volts');self.bias_stop.setAccessibleName('Last bias offset in volts')
        self.bias_start.valueChanged.connect(self._bias_range_changed);self.bias_stop.valueChanged.connect(self._bias_range_changed)
        bias_range.addWidget(self.bias_start,1);between=QLabel('to');between.setObjectName('workspaceMuted');bias_range.addWidget(between);bias_range.addWidget(self.bias_stop,1)
        self.bias_list_button=_button('…',self.edit_bias_list);self.bias_list_button.setObjectName('workspaceIconButton');self.bias_list_button.setFixedWidth(26);self.bias_list_button.setToolTip('Edit arbitrary bias voltages and number of sweep points')
        bias_range.addWidget(self.bias_list_button)
        self._field_row(electrical_form,'Bias sweep (V)',bias_range)
        self._field_row(electrical_form,'Swept terminal',self.swept_contact)
        self.shared_temperature=QLabel();self.shared_temperature.setObjectName('workspaceReadout')
        self._field_row(electrical_form,'Temperature',self.shared_temperature,unit='K')
        self._field_row(electrical_form,'Charge model',self.charge_model)
        self.iv_model_readout=QLabel('Ohmic conductivity estimate');self.iv_model_readout.setObjectName('workspaceReadout')
        self._field_row(electrical_form,'I–V model',self.iv_model_readout)
        self.cv_model_readout=QLabel('Electrode charge derivative');self.cv_model_readout.setObjectName('workspaceReadout')
        self._field_row(electrical_form,'C–V mode',self.cv_model_readout)
        self.mesh_readout=QLabel();self.mesh_readout.setObjectName('workspaceReadout')
        mesh_row=QHBoxLayout();mesh_row.setSpacing(5);mesh_row.addWidget(self.mesh_readout,1)
        self.advanced_button=_button('⚙',self._legacy_setup_dialog.show);self.advanced_button.setObjectName('workspaceIconButton');self.advanced_button.setFixedWidth(30)
        self.advanced_button.setToolTip('Advanced study, optical sampling and coupling options');mesh_row.addWidget(self.advanced_button)
        self._field_row(electrical_form,'Mesh settings',mesh_row)
        self.preview_mesh_button=_button('▦  Preview mesh',self.preview_mesh);self.preview_mesh_button.setObjectName('meshPreviewAction');self.preview_mesh_button.setMinimumHeight(32)
        electrical_form.addWidget(self.preview_mesh_button)
        electrical_form.addStretch()
        electrical_outer.addWidget(electrical_inner,1);self.electrical_setup_card=electrical
        setup_grid.addWidget(electrical,1)

        optical,optical_outer=self._card('☼  Optical setup')
        optical_inner=QWidget();optical_form=QVBoxLayout(optical_inner);optical_form.setContentsMargins(16,9,16,9);optical_form.setSpacing(6)
        wave=QHBoxLayout();wave.setSpacing(7)
        self.optical_settings={
            'wl_start_nm':number(1515,.000001,1e9,4),'wl_stop_nm':number(1555,.000001,1e9,4),
            'wl_step_nm':number(1,.000001,1e9,6),
            'polarization':_combo([('TE (in-plane)','s'),('TM (out-of-plane)','p'),('45° · TE + TM','45° s+p')]),
            'NumG':integer(32,1,4096)}
        wave.addWidget(self.optical_settings['wl_start_nm'],1);to=QLabel('to');to.setObjectName('workspaceMuted');wave.addWidget(to);wave.addWidget(self.optical_settings['wl_stop_nm'],1)
        self._field_row(optical_form,'Wavelength range',wave,unit='nm')
        sampling,sampling_form=_group('Optical sampling',[('Wavelength step (nm)',self.optical_settings['wl_step_nm'])])
        legacy_layout.insertWidget(1,sampling)
        self._field_row(optical_form,'Polarization',self.optical_settings['polarization'])
        basis=QHBoxLayout();solver=QLabel('S4 · RCWA');solver.setObjectName('workspaceReadout');basis.addWidget(solver,1);basis.addWidget(self.optical_settings['NumG'],1)
        self._field_row(optical_form,'Solver / basis',basis)
        self.optical_cell_controls={
            'width_um':number(2,.000001,1e6,6),'depth_um':number(2,.000001,1e6,6),
            'cx_um':number(0,-1e6,1e6,6),'cy_um':number(0,-1e6,1e6,6)}
        self.optical_cell_enabled=_check('Use selected optical cell',False)
        self.optical_cell_enabled.setAccessibleName('Use selected optical cell independently of the finite electrical device')
        self.optical_cell_enabled.setToolTip('S4 solves this one periodic unit cell. The electrical device keeps its own finite width and depth.')
        cell_size=QHBoxLayout();cell_size.setSpacing(6)
        cell_size.addWidget(self.optical_cell_controls['width_um'],1)
        multiply=QLabel('×');multiply.setObjectName('workspaceMuted');cell_size.addWidget(multiply)
        cell_size.addWidget(self.optical_cell_controls['depth_um'],1)
        self._field_row(optical_form,'Unit cell (µm)',cell_size)
        optical_form.addWidget(self.optical_cell_enabled)
        optical_cell,cell_form=_group('Optical unit-cell position',[
            ('Center x (µm)',self.optical_cell_controls['cx_um']),('Center y (µm)',self.optical_cell_controls['cy_um'])])
        self.use_pc_cell_button=_button('Use PC lattice size',self.use_pc_cell)
        self.use_pc_cell_button.setAutoDefault(False)
        self.use_pc_cell_button.setToolTip('Copy the most recently added enabled PC area cell dimensions and choose a hole near its center. The simulation checkbox keeps your choice.')
        cell_form.addRow(self.use_pc_cell_button)
        cell_form.addRow(_note('The selected rectangle is one periodic S4 cell inside the finite electrical device. Size and center do not change the electrical geometry.'))
        legacy_layout.insertWidget(2,optical_cell)
        self.optical_cell_enabled.toggled.connect(self.optical_cell_changed)
        for field in self.optical_cell_controls.values():_on_edit(field,self.optical_cell_changed)
        self._field_row(optical_form,'Reference state',self.optical_reference)
        slicing=QHBoxLayout();slicing.setSpacing(5);slicing.addWidget(self.optical_slices,1)
        self.optical_advanced_button=_button('⚙',self._legacy_setup_dialog.show);self.optical_advanced_button.setObjectName('workspaceIconButton');self.optical_advanced_button.setFixedWidth(30)
        self.optical_advanced_button.setToolTip('Optical sampling, feature tracking and experimental coupling options');slicing.addWidget(self.optical_advanced_button)
        self._field_row(optical_form,'Optical slices',slicing)
        self.carrier_response=_check('Carrier-induced n / k',self.workflow=='coupled');self.carrier_response.setEnabled(False)
        self.carrier_response.setToolTip('The coupled solver always transfers its calculated carrier response; choose Optical to use only the optical material data.')
        optical_form.addWidget(self.carrier_response)
        self.carrier_note=QLabel('Use calculated carriers to update optical materials.');self.carrier_note.setObjectName('workspaceMuted');self.carrier_note.setWordWrap(True);self.carrier_note.hide()
        self.electro_optic.setText('Electro-optic response · GaAs');optical_form.addWidget(self.electro_optic)
        self.electro_optic.setToolTip('Include the supported GaAs field-induced index change. This does not imply an electro-optic model for silicon or other materials.')
        optical_form.addStretch()
        note=QLabel('ⓘ  S4: one periodic unit cell.\n     Electrical: the finite device.');note.setObjectName('workspaceInfo');note.setWordWrap(True);optical_form.addWidget(note)
        optical_outer.addWidget(optical_inner,1);self.optical_setup_card=optical
        setup_grid.addWidget(optical,1);grid.addWidget(setups,1,1)
        for field in self.optical_settings.values():_on_edit(field,self.optical_settings_changed)

        previews=QWidget();preview_layout=QHBoxLayout(previews);preview_layout.setContentsMargins(0,0,0,0);preview_layout.setSpacing(8)
        class OpticalCellPreview(DeviceCanvas):
            def __init__(self):
                super().__init__('top');self.optical_cell=None

            def paintEvent(self,event):
                super().paintEvent(event)
                cell=self.optical_cell
                if not cell or not cell.get('enabled') or not self.device:return
                x,y=cell['cx_um'],cell['cy_um'];width,depth=cell['width_um'],cell['depth_um']
                rectangle=QRectF(self.screen_point(x-width/2,y+depth/2),self.screen_point(x+width/2,y-depth/2)).normalized()
                painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                fill=QColor('#28b8ff');fill.setAlpha(24);painter.setBrush(fill)
                painter.setPen(QPen(QColor('#48caff'),1.8,Qt.PenStyle.DashLine));painter.drawRect(rectangle)
                painter.setPen(QColor('#91dcff'));font=QFont(self.font());font.setPointSizeF(8);painter.setFont(font)
                painter.drawText(QRectF(12,6,self.width()-24,22),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,
                    f'Optical cell · {width:g} × {depth:g} µm')
                painter.end()

        self.top_preview=OpticalCellPreview();self.section_preview=DeviceCanvas('section')
        self.top_preview.compact_preview=True;self.section_preview.compact_preview=True
        self.top_preview.setMinimumSize(230,170);self.section_preview.setMinimumSize(230,170)
        self.top_preview.object_selected.connect(self._select_preview_object)
        self.section_preview.object_selected.connect(self._select_preview_object)
        self.shared_preview.object_selected.connect(self._select_preview_object)
        self.preview_selection=''
        for title,canvas in [('Top view · XY',self.top_preview),('Cross section · XZ (A–A)',self.section_preview)]:
            frame,body=self._card(title);body.addWidget(canvas,1);preview_layout.addWidget(frame,1)
        grid.addWidget(previews,2,1)

        sequence,sequence_layout=self._card('◇  Coupling sequence')
        sequence_body=QWidget();steps_layout=QVBoxLayout(sequence_body);steps_layout.setContentsMargins(13,5,9,8);steps_layout.setSpacing(0)
        definitions=[('layers','Shared device','Geometry + material properties\n+ contacts'),
            ('electrical','Electrical simulation','Potential, E-field, electrons and holes'),
            ('layers','Optical material update','n(z, V), k(z, V), permittivity'),
            ('optical','Optical simulation','R / T / A and resonance shifts')]
        self.sequence_steps=[]
        for index,(kind,title,detail) in enumerate(definitions,1):
            step=_SequenceStep(index,kind,title,detail);self.sequence_steps.append(step);steps_layout.addWidget(step,1)
        self.transferred_profiles_button=_button('▥  Inspect transferred profiles',self.inspect_transferred)
        self.transferred_profiles_button.setMinimumHeight(38);self.transferred_profiles_button.setEnabled(False)
        steps_layout.addWidget(self.transferred_profiles_button)
        self.transfer_note=QLabel('Run a coupled simulation to view transferred data.');self.transfer_note.setObjectName('workspaceMuted');self.transfer_note.setWordWrap(True);self.transfer_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        steps_layout.addWidget(self.transfer_note)
        sequence_layout.addWidget(sequence_body,1);grid.addWidget(sequence,0,2,2,1)

        results,results_layout=self._card('⌁  Results (show after run)   ⌃')
        choices=QWidget();choices_layout=QVBoxLayout(choices);choices_layout.setContentsMargins(18,5,14,8);choices_layout.setSpacing(0)
        self.fields_choice=_check('Electrical fields',True);self.fields_choice.setEnabled(False);self.fields_choice.setToolTip('The electrical solver always saves its fields and carrier concentrations.')
        self.iv_enabled.setText('I–V curves');self.cv_enabled.setText('C–V curves')
        self.optical_choice=_check('Optical spectra',self.workflow!='electrical');self.optical_choice.setEnabled(False)
        for checkbox,description in [(self.fields_choice,'Potential, E-field, carrier density'),(self.iv_enabled,'Ohmic current vs. voltage'),(self.cv_enabled,'Electrode charge derivative'),(self.optical_choice,'R / T / A vs. wavelength')]:
            line=QWidget();line.setObjectName('resultChoiceRow');row=QHBoxLayout(line);row.setContentsMargins(0,10,0,10);row.setSpacing(8)
            checkbox.setMinimumWidth(134);row.addWidget(checkbox)
            detail=QLabel(description);detail.setObjectName('workspaceMuted');detail.setWordWrap(True);row.addWidget(detail,1);choices_layout.addWidget(line)
        choices_layout.addStretch()
        self.view_results_button=_button('Open results',self.inspect_transferred);self.view_results_button.setEnabled(False);self.view_results_button.hide()
        results_layout.addWidget(choices,1);grid.addWidget(results,2,2)

        validation,validation_layout=self._card('Setup validation')
        validation.layout().itemAt(0).widget().setFixedHeight(27)
        checks=QWidget();checks_layout=QHBoxLayout(checks);checks_layout.setContentsMargins(15,0,12,8);checks_layout.setSpacing(9)
        self.validation_labels={}
        for key,text in [('contacts','Contacts assigned'),('electrical','Electrical materials ready'),('optical','Optical reference selected'),('mesh','Mesh preview available'),('convergence','Convergence checked\nafter running')]:
            label=QLabel('○   '+text);label.setObjectName('setupValidationBadge');label.setWordWrap(True);label.setMinimumHeight(40)
            checks_layout.addWidget(label,1);self.validation_labels[key]=label
        validation_layout.addWidget(checks);grid.addWidget(validation,3,1,1,2)
        self.validation_state={};self.mesh_preview_valid=False
        self.workspace_splitter=self.workspace
        self.layout_.addWidget(self.workspace,1)
        # Keep these run buttons for embedders without the application's footer.
        self.local_actions=self.actions('Run '+self.workflow+' simulation',self.run)
        self.local_actions.hide();self.layout_.addWidget(self.local_actions)
        self._apply_workspace_theme()
        self.refresh_history()

    def _apply_workspace_theme(self,*_):
        colors=COLORS[theme_manager().mode]
        self.workspace.setStyleSheet(f'''
            QWidget#simulationWorkspace {{ background: transparent; color: {colors['text']}; }}
            QFrame#simulationCard {{ border: 1px solid {colors['border']}; border-radius: 4px;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {colors['panel']},stop:1 {colors['bg']}); }}
            QLabel#simulationCardHeading {{ font-size: 14px; font-weight: 500; padding-left: 15px;
                border-bottom: 1px solid {colors['border']}; background: transparent; }}
            QLabel#simulationSectionHeading {{ padding-left: 14px; border-top: 1px solid {colors['border']}; }}
            QLabel#workspaceMuted {{ color: {colors['muted']}; font-size: 11px; background: transparent; }}
            QLabel#workspaceSmall {{ color: {colors['muted']}; font-size: 11px; background: transparent; }}
            QLabel#workspaceFieldLabel {{ color: {colors['text']}; font-size: 12px; }}
            QLabel#workspaceReadout {{ border: 1px solid {colors['border']}; border-radius: 3px;
                background: {colors['field']}; color: {colors['text']}; padding: 4px 7px; min-height: 17px; font-size: 11px; }}
            QLabel#workspaceInfo {{ color: {colors['muted']}; font-size: 11px; border-top: 1px solid {colors['border']}; padding-top: 12px; }}
            QLabel#sequenceTitle {{ font-size: 13px; color: {colors['text']}; }}
            QLabel#sequenceBadge {{ border: 1px solid {colors['border']}; border-radius: 4px; padding: 2px 8px;
                color: {colors['muted']}; font-size: 10px; background: {colors['field']}; }}
            QLabel#setupValidationBadge {{ border: 1px solid {colors['border']}; border-radius: 4px; padding: 4px 8px;
                color: {colors['muted']}; font-size: 10px; background: {colors['panel']}; }}
            QWidget#deviceSummaryRow, QWidget#resultChoiceRow {{ border-bottom: 1px solid {colors['border']}; }}
            QPushButton#workspaceLink {{ color: {colors['accent']}; background: transparent; border: 0;
                padding: 4px; font-size: 11px; }}
            QPushButton#workflowCard {{ min-height: 116px; max-height: 116px; padding: 0; border: 0; }}
            QPushButton#workspaceIconButton {{ padding: 0; font-size: 15px; min-height: 25px; }}
            QPushButton#meshPreviewAction {{ border: 1px solid {colors['accent']}; min-height: 32px;
                background: {colors['select']}; font-size: 12px; padding: 2px 8px; }}
            QTreeWidget#simulationHistory {{ border: 0; background: transparent; font-size: 11px; }}
            QTreeWidget#simulationHistory::item {{ min-height: 26px; border-bottom: 1px solid {colors['border']}; }}
            QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {{ min-height: 21px; font-size: 11px; padding: 2px 6px; border-radius: 3px; }}
            QCheckBox {{ font-size: 12px; spacing: 9px; }}
        ''')
        for card in self.workflow_cards.values():card.update()

    def _sync_bias_preview(self,*_):
        if not hasattr(self,'bias_start'):return
        try:values=parse_biases(self.biases.text())
        except ValueError:return
        for field,value in ((self.bias_start,values[0]),(self.bias_stop,values[-1])):
            with QSignalBlocker(field):field.setValue(value)

    def choose_workflow(self,key):
        for name,card in self.workflow_cards.items():
            with QSignalBlocker(card):card.setChecked(name==self.workflow)
        self.selectWorkflow.emit(key)

    def _bias_range_changed(self,*_):
        if self.loading:return
        try:count=max(2,len(parse_biases(self.biases.text())))
        except ValueError:count=2
        if self.cv_enabled.isChecked():count=max(3,count)
        values=np.linspace(self.bias_start.value(),self.bias_stop.value(),count)
        if values[0]==values[-1]:values=values[:1]
        self.biases.setText(', '.join(f'{value:g}' for value in values));self.changed()

    def edit_bias_list(self):
        dialog=QDialog(self);dialog.setWindowTitle('Bias sweep');dialog.resize(500,210)
        layout=QVBoxLayout(dialog)
        layout.addWidget(_note('Enter any unique finite bias offsets, in volts, separated by commas. C–V requires at least three distinct states.'))
        layout.addWidget(self.biases)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        dialog.finished.connect(lambda:self.biases.setParent(self._legacy_setup_dialog))
        dialog.finished.connect(self.changed)
        self.bias_dialog=dialog;dialog.show()

    def _study_selected(self,*_):
        if self.loading:return
        value=self.study_selector.currentData()
        with QSignalBlocker(self.iv_enabled):self.iv_enabled.setChecked(value in ('iv','both'))
        with QSignalBlocker(self.cv_enabled):self.cv_enabled.setChecked(value in ('cv','both'))
        self.cv_changed(self.cv_enabled.isChecked())

    def _sync_study_selector(self):
        with QSignalBlocker(self.study_selector):
            value='both' if self.iv_enabled.isChecked() and self.cv_enabled.isChecked() else 'iv' if self.iv_enabled.isChecked() else 'cv' if self.cv_enabled.isChecked() else 'bias'
            self.study_selector.setCurrentIndex(self.study_selector.findData(value))

    def optical_settings_changed(self,*_):
        if self.loading:return
        try:self.store.update_settings({key:_value(field) for key,field in self.optical_settings.items()})
        except Exception as exc:self.status.setText(str(exc))

    def optical_cell_changed(self,*_):
        if self.loading:return
        # Unit-cell dimensions are independent of the finite electrical device.
        # Never write ax_um/ay_um here: those still name the shared device extent.
        try:
            cell={key:field.value() for key,field in self.optical_cell_controls.items()}
            cell['enabled']=self.optical_cell_enabled.isChecked()
            self.store.update_settings({'optical_unit_cell':cell})
        except Exception as exc:self.status.setText(str(exc))

    def use_pc_cell(self):
        from pc_array import plan_pc_array
        try:
            area=next((row for row in reversed((self.store.device or {}).get('pc_arrays',[])) if row.get('enabled',True)),None)
            if area is None:raise ValueError('Create a photonic-crystal area in Structure first.')
            plan=plan_pc_array(self.store.device,area)
            if not plan['hole_count']:raise ValueError('No complete unit cells fit in this PC area.')
            cell=dict(enabled=self.optical_cell_enabled.isChecked(),
                width_um=plan['cell_width_um'],depth_um=plan['cell_depth_um'],
                cx_um=plan['first_x_um']+((plan['nx']-1)//2)*plan['cell_width_um'],
                cy_um=plan['first_y_um']+((plan['ny']-1)//2)*plan['cell_depth_um'])
            self.store.update_settings({'optical_unit_cell':cell})
        except Exception as exc:self.status.setText(str(exc))

    def _select_preview_object(self,ident):
        self.preview_selection=ident
        device=self.store.device or {}
        obj=next((row for kind in ('layers','shapes','contacts','doping_regions') for row in device.get(kind,[]) if row['id']==ident),{})
        selected_layer=obj.get('layer_id',ident if obj in device.get('layers',[]) else '')
        for view in (self.shared_preview,self.top_preview,self.section_preview):view.set_device(device,ident,selected_layer)

    def _refresh_shared_device(self):
        device=self.store.device or {}
        for view in (self.shared_preview,self.top_preview,self.section_preview):view.set_device(device,self.preview_selection)
        layers=[row for row in device.get('layers',[]) if row.get('enabled',True)]
        materials={row['id']:row for row in self.store.electrical_materials}
        height=sum(float(row.get('thickness_um',0)) for row in layers)
        self.device_summary_labels['Geometry'].setText(f"{device.get('width_um',0):g} × {device.get('depth_um',0):g} × {height:g} µm")
        self.device_summary_labels['Layers'].setText(f'{len(layers)} layers')
        names=list(dict.fromkeys(materials.get(row.get('material_id'),{}).get('name','Unassigned') for row in layers))
        self.device_summary_labels['Materials'].setText(', '.join(names) or 'No finite layers')
        contacts=[row for row in device.get('contacts',[]) if row.get('enabled',True)]
        self.device_summary_labels['Contacts'].setText(', '.join(row['name'] for row in contacts) or 'None assigned')
        self.shared_temperature.setText(f"{device.get('temperature_K',300):g}")
        mesh=device.get('mesh',{})
        self.mesh_readout.setText(f"{mesh.get('nx',0)} × {mesh.get('ny',0)} × {mesh.get('nz_per_layer',0)} / layer")
        for key,field in self.optical_settings.items():_set_value(field,self.store.settings.get(key,_value(field)))
        cell=self.store.settings.get('optical_unit_cell') or {}
        cell_defaults=dict(width_um=self.store.settings.get('ax_um',device.get('width_um',2)),
            depth_um=self.store.settings.get('ay_um',device.get('depth_um',2)),cx_um=0.,cy_um=0.)
        for key,field in self.optical_cell_controls.items():_set_value(field,cell.get(key,cell_defaults[key]))
        _set_value(self.optical_cell_enabled,cell.get('enabled',False))
        self.top_preview.optical_cell=dict(cell_defaults,**cell)
        self.top_preview.update()
        self._sync_bias_preview()
        self._sync_study_selector()
        electrical=self.workflow!='optical'
        for field in (self.study_selector,self.bias_start,self.bias_stop,self.bias_list_button,self.swept_contact,self.charge_model,self.preview_mesh_button,self.iv_enabled,self.cv_enabled,self.advanced_button):field.setEnabled(electrical)
        self.fields_choice.setChecked(electrical)
        self.optical_choice.setChecked(self.workflow!='electrical')
        for field in self.optical_settings.values():field.setEnabled(self.workflow!='electrical')
        self.optical_cell_enabled.setEnabled(self.workflow!='electrical')
        for field in self.optical_cell_controls.values():field.setEnabled(self.workflow!='electrical' and self.optical_cell_enabled.isChecked())
        self.optical_reference.setEnabled(self.workflow=='coupled');self.optical_slices.setEnabled(self.workflow=='coupled')
        self.electro_optic.setEnabled(self.workflow=='coupled')
        self.optical_advanced_button.setEnabled(self.workflow!='electrical')
        self.carrier_response.setChecked(self.workflow=='coupled')
        self.carrier_note.setText('Use calculated carriers to update optical materials.' if self.workflow=='coupled' else 'Optical uses the assigned material dispersion.' if self.workflow=='optical' else 'Select Optical or Coupled to configure light response.')
        self._refresh_validation()
        if not self.store.busy:self._sequence_ready()

    def _set_validation_badge(self,key,text,ready=False):
        label=self.validation_labels[key]
        label.setText(('✓   ' if ready else '○   ')+text)
        label.setStyleSheet('color: #46e39b;' if ready else '')

    def _refresh_validation(self):
        device=self.store.device or {};contacts=[row for row in device.get('contacts',[]) if row.get('enabled',True)]
        self._set_validation_badge('contacts','Contacts assigned' if len(contacts)>=2 else 'Assign device contacts',len(contacts)>=2)
        try:
            from device_model import validate_device
            validate_device(device,self.store.electrical_materials)
            assigned=bool(device.get('layers'))
        except (ValueError,KeyError,TypeError):assigned=False
        self._set_validation_badge('electrical','Electrical materials ready' if assigned else 'Assign electrical materials',assigned)
        if self.workflow=='electrical':self._set_validation_badge('optical','Optical data not required',True)
        else:self._set_validation_badge('optical','Optical setup validated' if self.validation_state.get('optical') else 'Optical reference selected',self.validation_state.get('optical',False))
        self._set_validation_badge('mesh','Mesh preview available' if self.mesh_preview_valid else 'Preview mesh to check',self.mesh_preview_valid)
        checks=[result.get('checks',{}) for result in (self.saved_summary or {}).get('results',[])]
        converged=bool(checks) and all(check.get('converged',False) or (
            float(check.get('max_normalized_Poisson_residual',np.inf))<1e-9 and
            float(check.get('relative_gauss_balance',np.inf))<=1e-6) for check in checks)
        self._set_validation_badge('convergence','Convergence checked\nafter running' if not converged else 'Saved solver convergence checked',converged)

    def preview_mesh(self):
        try:
            from custom_electrical_solver import build_mesh
            mesh=build_mesh(self.store.device,self.store.electrical_materials)
            self.mesh_preview_valid=True
            for view in (self.shared_preview,self.top_preview,self.section_preview):view.show_mesh=True;view.update()
            self.status.setText(f"Device mesh and contact placement checked: {np.prod(mesh['shape']):,} cells.")
            self._refresh_validation()
        except Exception as exc:
            self.mesh_preview_valid=False;self._refresh_validation();self.status.setText(str(exc))

    def validate_setup(self):
        try:
            from qt_core import prepare_job
            project=self.store.project() if self.workflow=='electrical' else self.store.portable_project()
            prepare_job(self.run_kind,project,self.options(),self.store.library)
            if self.workflow!='optical':
                from custom_electrical_solver import build_mesh
                if self.model.currentData()=='custom_device':build_mesh(self.store.device,self.store.electrical_materials)
            self.validation_state['optical']=self.workflow!='electrical'
            self.status.setText('Setup validated against the selected solver inputs. Convergence is checked after running.')
            self._refresh_validation();return True
        except Exception as exc:self.status.setText(str(exc));return False

    def _sequence_ready(self):
        self.sequence_steps[0].set_state('ready','Same shared geometry')
        self.sequence_steps[1].set_state('ready' if self.workflow!='optical' else 'skipped','Ready to run' if self.workflow!='optical' else 'Skipped · optical only')
        self.sequence_steps[2].set_state('ready' if self.workflow=='coupled' else 'skipped','Ready to transfer' if self.workflow=='coupled' else 'Assigned optical data' if self.workflow=='optical' else 'Skipped · electrical only')
        self.sequence_steps[3].set_state('ready' if self.workflow!='electrical' else 'skipped','Ready to run' if self.workflow!='electrical' else 'Skipped · electrical only')

    def sequence_progress(self,event):
        if event.get('run_kind') not in self.kinds:return
        text=str(event.get('text') or event.get('message') or '').lower()
        self.sequence_steps[0].set_state('complete','Inputs recorded')
        if self.workflow=='optical':self.sequence_steps[3].set_state('active','Running optical solver');return
        if 'optical' in text or 's4' in text or 'spectr' in text:
            self.sequence_steps[1].set_state('complete','Profiles saved');self.sequence_steps[2].set_state('complete','Carrier profiles transferred');self.sequence_steps[3].set_state('active','Running optical solver')
        else:self.sequence_steps[1].set_state('active','Solving electrical states')

    def sequence_failed(self,message):
        if not any(step.state=='active' for step in self.sequence_steps):return
        for step in self.sequence_steps:
            if step.state=='active':step.set_state('failed','Stopped · inspect status')

    def inspect_transferred(self):
        if self.directory is not None:
            self.resultsRequested.emit(self.directory,self.saved_summary or {})

    def refresh_history(self,*_):
        self.run_history.clear()
        entries=self.store.library.entries()
        groups={}
        for key,label in [('optical','Optical'),('electrical','Electrical'),('coupled','Coupled')]:
            group=QTreeWidgetItem([label,'']);self.run_history.addTopLevelItem(group);group.setExpanded(True);groups[key]=group
        counts=dict.fromkeys(groups,0)
        for record in entries[:100]:
            directory=self.store.library.runs/record['id']
            if (directory/'electrical_summary.json').exists():
                try:
                    summary=json.loads((directory/'electrical_summary.json').read_text(encoding='utf-8'))
                    key='coupled' if summary.get('spectra_csv') or summary.get('optical',{}).get('spectra_csv') else 'electrical'
                except (OSError,ValueError,TypeError):key='electrical'
            elif (directory/'results.csv').exists():key='optical'
            else:continue
            counts[key]+=1
            label=str(record.get('title') or record['id'])
            created=str(record.get('created','')).replace('T',' ')[:16]
            item=QTreeWidgetItem([label,created]);item.setData(0,Qt.ItemDataRole.UserRole,str(directory));item.setToolTip(0,label+'\n'+str(directory));groups[key].addChild(item)
        for key,group in groups.items():group.setText(0,f'{group.text(0)} ({counts[key]})')

    def _open_history_item(self,item,column):
        path=item.data(0,Qt.ItemDataRole.UserRole)
        if path:self.resultsRequested.emit(Path(path),{})

    def mapping_records(self):
        result = {}
        for row, source in enumerate(DEVICE_LAYERS):
            layer = self.mapping.cellWidget(row, 1).currentData()
            material = self.mapping.cellWidget(row, 2).currentData()
            if layer:
                result[source] = {'layer': layer, 'material': material or ''}
        return result

    def options(self):
        if self.workflow=='optical':
            return dict(self.store.search_state.get('simulation',{}))
        if self.model.currentData()=='custom_device':
            return dict(model='custom_device',device=self.store.device,material_library=self.store.electrical_materials,
                biases_V=parse_biases(self.biases.text()),charge_model=self.charge_model.currentData(),
                swept_contact_id=self.swept_contact.currentData(),optical_enabled=self.workflow=='coupled',
                optical_reference=self.optical_reference.currentData(),electro_optic=self.electro_optic.isChecked(),
                interband=self.interband.isChecked(),interband_extrapolation=self.interband_extrapolation.isChecked(),
                optical_slices_per_layer=self.optical_slices.value(),
                terminal_studies=dict(iv_enabled=self.iv_enabled.isChecked(),cv_enabled=self.cv_enabled.isChecked(),
                    measured_iv_path=self.measured_iv.text(),measured_cv_path=self.measured_cv.text()),
                **{key:_value(self.controls[key]) for key in ('response','feature','reference_nm','tracking_window_nm')})
        try:
            density = float(self.controls['ito_density_cm3'].text())
        except ValueError as exc:
            raise ValueError('ITO electron density must be a positive number in cm⁻³, for example 5e20.') from exc
        if not np.isfinite(density) or density <= 0:
            raise ValueError('ITO electron density must be a positive finite number in cm⁻³.')
        options = {key: _value(widget) for key, widget in self.controls.items() if key != 'ito_density_cm3'}
        options.update(model=self.model.currentData(), biases_V=parse_biases(self.biases.text()),
            ito_density_cm3=density, geometry='contacts_only_100um',
            optical_enabled=self.workflow=='coupled', optical_reference=self.optical_reference.currentData(),
            optical_mapping=self.mapping_records(), electro_optic=self.electro_optic.isChecked(), interband=self.interband.isChecked(),
            interband_extrapolation=self.interband_extrapolation.isChecked(), optical_slices_per_layer=self.optical_slices.value())
        if self.measured_current:
            options['measured_current'] = self.measured_current
        return options

    def refresh(self, *_):
        if self.loading:
            return
        self.loading = True
        try:
            saved = self.store.search_state.get(self.run_kind, {})
            _set_value(self.model, saved.get('model', 'custom_device'))
            _set_value(self.charge_model,saved.get('charge_model','semiconductor'))
            terminal=saved.get('terminal_studies',{})
            _set_value(self.iv_enabled,terminal.get('iv_enabled',False));_set_value(self.cv_enabled,terminal.get('cv_enabled',False))
            _set_value(self.measured_iv,terminal.get('measured_iv_path',''));_set_value(self.measured_cv,terminal.get('measured_cv_path',''))
            contacts=[row for row in (self.store.device or {}).get('contacts',[]) if row.get('enabled',True)]
            _choices(self.swept_contact,[('Use last enabled contact','')]+[(row['name'],row['id']) for row in contacts],saved.get('swept_contact_id',''))
            _set_value(self.biases, ', '.join(f'{value:g}' for value in saved.get('biases_V', [0, -2])))
            for key, widget in self.controls.items():
                if key in saved:
                    _set_value(widget, f'{saved[key]:g}' if key == 'ito_density_cm3' else saved[key])
            if self.model.currentData()=='custom_device' and 'reference_nm' not in saved:
                settings=self.store.settings
                low,high=sorted((settings.get('wl_start_nm',1515.),settings.get('wl_stop_nm',1555.)))
                _set_value(self.controls['reference_nm'],min(high,max(low,settings.get('fixed_wl_nm',1550.))))
            self.measured_current = saved.get('measured_current', [])
            _set_value(self.optical_enabled,self.workflow=='coupled')
            _set_value(self.optical_reference, saved.get('optical_reference', 'undoped' if self.model.currentData()=='custom_device' else 'zero_bias'))
            _set_value(self.electro_optic, saved.get('electro_optic', False))
            _set_value(self.interband, saved.get('interband', False))
            _set_value(self.interband_extrapolation, saved.get('interband_extrapolation', False))
            _set_value(self.optical_slices, saved.get('optical_slices_per_layer', 8))
            self.rebuild_mapping(saved.get('optical_mapping', {}))
            settings = self.store.settings
            self.s4_note.setText(f"Uses current S4 settings: {settings.get('wl_start_nm', 0):g}–{settings.get('wl_stop_nm', 0):g} nm, step {settings.get('wl_step_nm', 0):g} nm; polarization {settings.get('polarization', 'p')}, basis {settings.get('NumG', 0)}.")
            self.current_note.setText(f'{len(self.measured_current)} measured I–V points loaded.' if self.measured_current else 'No measured I–V data loaded. CSV columns: bias_V, current_A.')
            self.update_model()
            signature=json.dumps(self.store.device,sort_keys=True)
            if signature!=getattr(self,'_preview_signature',None):
                self.mesh_preview_valid=False;self.validation_state.clear();self._preview_signature=signature
            self._refresh_shared_device()
        finally:
            self.loading = False

    def rebuild_mapping(self, saved):
        layers = self.store.layers.to_dict('records')
        names = [row['Name'] for row in layers]
        materials = [str(name) for name in self.store.materials['Name'] if str(name).strip()]
        self.mapping.setRowCount(len(DEVICE_LAYERS))
        for row, source in enumerate(DEVICE_LAYERS):
            item = QTableWidgetItem(source)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.mapping.setItem(row, 0, item)
            record = saved.get(source, {})
            record = {'layer': record} if isinstance(record, str) else record
            selected = record.get('layer', source if source in names else '')
            choices = [('Select layer…', '')] + [(name, name) for name in names]
            if selected and selected not in names:
                choices.append((selected + ' · unavailable', selected))
            layer_combo = _combo(choices, selected)
            layer_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            layer_combo.setMinimumContentsLength(8)
            base = next((layer['Material'] for layer in layers if layer['Name'] == selected), '')
            material = record.get('material', base)
            material_choices = [('Select material…', '')] + [(name, name) for name in materials]
            if material and material not in materials:
                material_choices.append((material + ' · unavailable', material))
            material_combo = _combo(material_choices, material)
            material_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            material_combo.setMinimumContentsLength(8)
            self.mapping.setCellWidget(row, 1, layer_combo)
            self.mapping.setCellWidget(row, 2, material_combo)
            layer_combo.currentIndexChanged.connect(lambda _=None, row=row: self.mapping_layer_changed(row))
            material_combo.currentIndexChanged.connect(self.changed)

    def mapping_layer_changed(self, row):
        if self.loading:
            return
        layer = self.mapping.cellWidget(row, 1).currentData()
        material = next((item['Material'] for item in self.store.layers.to_dict('records') if item['Name'] == layer), '')
        _set_value(self.mapping.cellWidget(row, 2), material)
        self.changed()

    def update_model(self):
        custom=self.model.currentData()=='custom_device'
        explicit = self.model.currentData() == 'explicit_ito'
        self.ito_group.setVisible(not custom)
        self.measured_group.setVisible(not custom)
        self.mapping_box.setVisible(not custom)
        self.studies_group.setVisible(custom)
        self.charge_model.setVisible(custom);self.swept_contact.setVisible(custom)
        self.controls['mesh_level'].setEnabled(not custom)
        for key in ('mesh_level','temperature_K'):
            self.device_form.setRowVisible(self.controls[key],not custom)
        self.preset_button.setText('Load editable device example' if custom else 'Load study device preset')
        self.preset_note.setText('The example replaces the shared device. Its size, layers, material assignments, doping and contacts can all be edited in Structure.' if custom else '100 × 100 µm study square with the saved contact layout and doping. Loading the preset replaces the shared structure.')
        self.mapping_note.setText('Uses optical material links and the actual finite layers and patterns in Structure. Assign optical dispersion in Materials; electrical properties stay independent.' if custom else 'Map each study layer to an optical layer with matching thickness. Patterned regions retain their geometry.')
        self.controls['ito_thickness_nm'].setEnabled(explicit)
        self.controls['ito_density_cm3'].setEnabled(explicit)
        self.controls['sheet_resistance_ohm_square'].setEnabled(not explicit)
        self.model_note.setText('Explicit ITO: solves a finite-thickness electron reservoir. Interface accuracy and carrier redistribution are experimental.' if explicit else 'Contacts-only model: semiconductor Poisson profiles with ITO represented by a measured conductive sheet. No ITO depth profile is solved.')
        if custom:self.model_note.setText('Uses the actual layers, material properties, shapes, doping, contacts, temperature and mesh in Structure. Bias values are offsets at the selected terminal. Electrostatics does not predict current.')
        self.scope_note.setText(('Optical simulation uses assigned material dispersion.' if self.workflow=='optical' else 'Static Poisson; transport is not solved.'+
            ('\nOptics uses lateral-average profiles.' if self.workflow=='coupled' else '')) if custom else
            'Study Poisson model with prescribed carrier reservoirs; explicit ITO interfaces remain experimental. Electrical transport is not solved.')
        self.electro_optic.setEnabled(self.optical_enabled.isChecked())
        self.interband.setEnabled(self.optical_enabled.isChecked())
        self.interband_extrapolation.setEnabled(self.optical_enabled.isChecked() and self.interband.isChecked())
        self.optical_slices.setEnabled(self.optical_enabled.isChecked())
        self.optical_reference.setEnabled(self.optical_enabled.isChecked())
        for key in ('response', 'feature', 'reference_nm', 'tracking_window_nm'):
            self.controls[key].setEnabled(self.optical_enabled.isChecked())
        for row in range(self.mapping.rowCount()):
            enabled = self.optical_enabled.isChecked() and (row < 5 or explicit)
            for column in (1, 2):
                self.mapping.cellWidget(row, column).setEnabled(enabled)
        current_text = f'{len(self.measured_current)} measured I–V points loaded.' if self.measured_current else 'No measured I–V data loaded. CSV columns: bias_V, current_A.'
        self.current_note.setText(current_text + (' I–V loads apply to the contacts-only sheet model.' if explicit else ' Without measured data, the imposed sheet current is zero.'))
        self.controls['current_offset'].setEnabled(not explicit)
        self.import_current_button.setEnabled(not explicit)

    def changed(self, *_):
        if self.loading:
            return
        self.update_model()
        self._sync_study_selector()
        if self.workflow=='optical':return
        try:
            self.store.save_search(self.run_kind, self.options())
        except Exception as exc:
            self.status.setText(str(exc))

    def cv_changed(self,checked):
        if self.loading:return
        if checked:
            try:
                biases=parse_biases(self.biases.text())
                if len(biases)==2:self.biases.setText(', '.join(f'{value:g}' for value in (biases[0],(biases[0]+biases[1])/2,biases[1])))
            except ValueError:pass
        self.changed()

    def choose_terminal_data(self,kind):
        path,_=QFileDialog.getOpenFileName(self,'Choose measured '+kind.upper()+' curve','','CSV files (*.csv)')
        if path:
            try:
                from electrical_terminal_studies import read_measured_csv
                read_measured_csv(path,kind)
                (self.measured_iv if kind=='iv' else self.measured_cv).setText(path)
                self.changed()
            except Exception as exc:self.status.setText(str(exc))

    def run(self):
        if self.workflow=='optical':
            self.opticalRunRequested.emit()
            return
        try:
            options = self.options()
            self.store.save_search(self.run_kind, options)
            self._start(self.run_kind, options)
        except Exception as exc:
            self.status.setText(str(exc))

    def load_preset(self):
        try:
            if self.model.currentData()=='custom_device':
                from device_model import default_device
                self.store.set_device(default_device(self.store.electrical_materials))
                self.status.setText('Editable example loaded into Structure. Review contacts, material data and mesh before running.')
                return
            self.store.load_electrical_preset(model=self.model.currentData(),
                ito_thickness_nm=self.controls['ito_thickness_nm'].value(),
                ito_density_cm3=float(self.controls['ito_density_cm3'].text()))
            self.status.setText('Device preset loaded. Review the optical mapping and S4 wavelength range before running.')
        except Exception as exc:
            self.status.setText(str(exc))

    def import_current(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Import measured I–V data', '', 'CSV files (*.csv);;All files (*)')
        if not filename:
            return
        try:
            frame = pd.read_csv(filename)
            if not {'bias_V', 'current_A'} <= set(frame):
                raise ValueError('Measured-current CSV requires bias_V and current_A columns.')
            frame = frame[['bias_V', 'current_A']].apply(pd.to_numeric, errors='raise')
            if len(frame) < 2 or not np.isfinite(frame.to_numpy(dtype=float)).all():
                raise ValueError('Measured-current values must be finite and the CSV must contain at least two points.')
            from electrical_solver import validate_options
            validated = validate_options({'measured_current': frame.to_dict('records'), 'biases_V': parse_biases(self.biases.text())})
            self.measured_current = validated['measured_current']
            self.changed()
        except Exception as exc:
            self.status.setText(f'Could not import measured current: {exc}')

    def clear_current(self):
        self.measured_current = []
        self.changed()

    def load_saved(self):
        directory = QFileDialog.getExistingDirectory(self, 'Open a saved electrical run', str(self.store.library.runs))
        if directory:
            try:
                self.directory = Path(directory)
                self.show_result({})
            except Exception as exc:
                self.status.setText(f'Could not load electrical result: {exc}')

    def show_result(self, event):
        if self.directory is None:
            raise ValueError('The electrical run did not provide a result directory.')
        if self.workflow=='optical':
            self.saved_summary=event.get('summary',{})
            self.view_results_button.setEnabled(True)
            self.sequence_steps[0].set_state('complete','Inputs recorded')
            self.sequence_steps[3].set_state('complete','Optical results saved')
            self.resultsRequested.emit(self.directory,self.saved_summary)
            self.refresh_history()
            return
        summary_path = self.directory / 'electrical_summary.json'
        summary = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.is_file() else event.get('summary')
        if not isinstance(summary, dict) or not isinstance(summary.get('results'), list) or not summary['results']:
            raise ValueError('This folder does not contain a saved electrical_summary.json result.')
        profiles = []
        for result in summary['results']:
            path = _saved_path(self.directory, result.get('profile_csv', ''))
            if not path.is_file():
                raise ValueError(f'Missing saved electrical profile: {path}')
            frame = pd.read_csv(path)
            if frame.empty or 'z_nm' not in frame:
                raise ValueError(f'The electrical profile is empty or has no z_nm depth column: {path}')
            frame['bias_V'] = result['bias_V']
            profiles.append(frame)
        self.saved_summary = summary
        self.results_dashboard.set_result(self.directory,summary)
        self.saved_profiles = pd.concat(profiles, ignore_index=True) if profiles else pd.DataFrame()
        self.saved_indices = self._read_optional_result(summary, 'index_profiles_csv', ('electrical_index_changes.csv', 'electrical_index_profiles.csv', 'electrical_nk_profiles.csv'))
        self.saved_spectra = self._read_optional_result(summary, 'spectra_csv', ('electrical_spectra.csv', 'electrical_optical_spectra.csv'))
        self.saved_features = self._read_optional_result(summary, 'features_csv', ('electrical_features.csv',))
        for index in (2,3,5,6):self.result_tabs.setTabVisible(index,self.workflow=='coupled' or not self.saved_spectra.empty)
        checks = [{'bias_V': result['bias_V'], **result.get('checks', {})} for result in summary['results']]
        fill_table(self.checks_table, pd.DataFrame(checks))
        biases = [result['bias_V'] for result in summary['results']]
        with QSignalBlocker(self.result_bias):
            _choices(self.result_bias, [('All biases', None)] + [(f'{value:g} V', value) for value in biases], self.result_bias.currentData())
        waves = sorted(self.saved_indices['wavelength_nm'].dropna().unique()) if 'wavelength_nm' in self.saved_indices else []
        preferred = self.result_wavelength.currentData()
        if preferred not in waves and waves:
            preferred = min(waves, key=lambda value: abs(value - self.store.settings.get('fixed_wl_nm', 1550)))
        with QSignalBlocker(self.result_wavelength):
            _choices(self.result_wavelength, [(f'{value:g} nm', float(value)) for value in waves], preferred)
        self.result_wavelength.setEnabled(bool(waves))
        model = summary.get('model', summary.get('options', {}).get('model', 'electrical'))
        label = 'Explicit ITO · experimental' if model == 'explicit_ito' else 'Contacts only · ITO sheet' if model == 'contacts_only_sheet' else str(model)
        optical = f'{len(self.saved_spectra):,} optical samples' if not self.saved_spectra.empty else 'electrical profiles only'
        self.summary_label.setText(f'{label} · {len(biases)} bias states · {optical}')
        tracking_path = self.directory / 'search_summary.json'
        tracking = json.loads(tracking_path.read_text(encoding='utf-8')) if tracking_path.is_file() else event.get('summary', {})
        baseline = tracking.get('baseline_nm')
        shift = tracking.get('max_abs_shift_nm')
        if not self.saved_spectra.empty:
            text = f'Sampled 0 V feature: {baseline:g} nm' if baseline is not None else 'No baseline peak/dip resolved within the tracking window.'
            if shift is not None:
                text += f' · maximum sampled |Δλ|: {shift:g} nm'
            self.tracking_label.setText(text)
        else:
            self.tracking_label.setText('')
        self.status.setText(f'Loaded electrical result: {self.directory}')
        self.redraw_result()
        self.view_results_button.setEnabled(True)
        self.transferred_profiles_button.setEnabled(not self.saved_indices.empty)
        self.transfer_note.setText('Saved carrier and refractive-index profiles are available.' if not self.saved_indices.empty else 'Electrical results saved. Coupled runs also save transferred profiles.')
        self.sequence_steps[0].set_state('complete','Inputs recorded')
        self.sequence_steps[1].set_state('complete','Electrical profiles saved')
        if not self.saved_spectra.empty:
            self.sequence_steps[2].set_state('complete','Optical profiles saved');self.sequence_steps[3].set_state('complete','Optical results saved')
        self._refresh_validation()
        self.refresh_history()
        self.resultsRequested.emit(self.directory,summary)

    def _read_optional_result(self, summary, key, filenames):
        value = summary.get(key) or summary.get('optical', {}).get(key)
        paths = [_saved_path(self.directory, value)] if value else []
        paths += [self.directory / filename for filename in filenames]
        for path in paths:
            if path.is_file():
                try:
                    return pd.read_csv(path)
                except pd.errors.EmptyDataError:
                    return pd.DataFrame()
        return pd.DataFrame()

    def _selected_frame(self, frame):
        bias = self.result_bias.currentData()
        if bias is None or 'bias_V' not in frame:
            return frame
        return frame[np.isclose(pd.to_numeric(frame['bias_V'], errors='coerce'), bias)]

    def redraw_result(self, *_):
        self.results_dashboard.set_bias(self.result_bias.currentData())
        profiles = self._selected_frame(self.saved_profiles)
        indices = self._selected_frame(self.saved_indices)
        wavelength = self.result_wavelength.currentData()
        if wavelength is not None and 'wavelength_nm' in indices:
            indices = indices[np.isclose(indices['wavelength_nm'], wavelength)]
        spectra = self._selected_frame(self.saved_spectra)
        features = self._selected_frame(self.saved_features)
        self.profile_full_range.setEnabled(self.profile_view.currentData() == 'Carrier concentration')
        self.profile_plot.draw_figure(electrical_profile_figure(profiles, self.profile_view.currentData(),
            minimum_density=None if self.profile_full_range.isChecked() else 1e8))
        self.index_plot.draw_figure(electrical_index_figure(indices, self.index_view.currentData()))
        self.spectrum_plot.draw_figure(electrical_spectrum_figure(spectra, self.response_view.currentData()))
        fill_table(self.profile_table, profiles.head(10000))
        fill_table(self.spectrum_table, spectra.head(10000))
        fill_table(self.feature_table, features)
