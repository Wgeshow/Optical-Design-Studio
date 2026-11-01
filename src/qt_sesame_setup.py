"""Native editable 1D/2D Sesame domain, material and grain-boundary controls."""
from __future__ import annotations

import json
import zipfile
from copy import deepcopy
import sys
import uuid
from pathlib import Path
from html import escape

import numpy as np
from matplotlib.figure import Figure

from PyQt6.QtCore import Qt, QSignalBlocker, QTimer
from PyQt6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QFileDialog, QComboBox,
    QSpinBox, QWidget, QVBoxLayout, QLineEdit, QGroupBox, QSplitter, QSizePolicy,
    QTextBrowser, QTableWidgetItem, QScrollArea)

from qt_input_diagnostics import reveal_and_focus
from qt_photonic_bands import _table, _fill, _rows
from qt_research_common import ResearchWorkspaceBase, FieldError, button, label, number, vector
from qt_research_results import ResearchResultsPanel
from qt_common import PlotWidget


class TableRowInspector(QWidget):
    """Native selected-object editing backed by the original lossless table draft."""
    def __init__(self, table, specifications, title, parent=None, advanced=()):
        super().__init__(parent)
        self.table, self.specifications = table, specifications
        self.editors, self.columns, self.forms = {}, {}, {}
        self._updating = False
        self.selector_display = lambda value, row: value
        self.setObjectName('studyInspector')
        self.setMinimumWidth(255)
        outer = QVBoxLayout(self); outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(label(title, 'setupHeading'))
        self.selector = QComboBox(); self.selector.setAccessibleName(title)
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.selector.setMinimumContentsLength(10)
        outer.addWidget(self.selector)
        self.actions = QHBoxLayout(); outer.addLayout(self.actions)
        self.form = QFormLayout(); self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.form.setProperty('studyAlwaysStacked', True)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        outer.addLayout(self.form)
        self.advanced_toggle = QCheckBox('Additional material properties')
        outer.addWidget(self.advanced_toggle)
        self.advanced_body = QWidget(); extra = QFormLayout(self.advanced_body)
        extra.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        extra.setProperty('studyAlwaysStacked', True)
        extra.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        outer.addWidget(self.advanced_body); self.advanced_body.hide()
        self.advanced_toggle.toggled.connect(self.advanced_body.setVisible)
        self.advanced_toggle.setVisible(bool(advanced))
        self.advanced_keys = set(advanced)
        for column, (key, caption, choices) in enumerate(specifications):
            if choices:
                edit = QComboBox()
                edit.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                edit.setMinimumContentsLength(8)
                for name, value in choices: edit.addItem(name, value)
                edit.currentIndexChanged.connect(lambda _, k=key: self._write(k))
            else:
                edit = QLineEdit(); edit.textChanged.connect(lambda _, k=key: self._write(k))
            edit.setAccessibleName(title+' '+caption)
            edit.setMinimumWidth(80)
            form = extra if key in self.advanced_keys else self.form
            form.addRow(caption, edit)
            caption_widget = form.labelForField(edit)
            caption_widget.setWordWrap(True)
            caption_widget.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
            caption_widget.setMinimumWidth(min(240,max(80,caption_widget.fontMetrics().horizontalAdvance(caption)+8)))
            self.editors[key], self.columns[key], self.forms[key] = edit, column, form
        self.note = label(''); outer.addWidget(self.note)
        outer.addStretch()
        table.setParent(self); table.hide()
        self.selector.currentIndexChanged.connect(self._select)
        table.currentCellChanged.connect(lambda *args: self.refresh())
        table.cellChanged.connect(lambda *args: self.refresh())
        self.refresh()

    def refresh(self):
        if self._updating: return
        self._updating = True
        try:
            row = self.table.currentRow()
            if row < 0 and self.table.rowCount():
                row = 0; self.table.setCurrentCell(0, 0)
            with QSignalBlocker(self.selector):
                self.selector.clear()
                for i in range(self.table.rowCount()):
                    item = self.table.item(i, 0)
                    caption = item.text() if item and item.text() else 'Unnamed object '+str(i+1)
                    self.selector.addItem(self.selector_display(caption,i), i)
                self.selector.setCurrentIndex(row)
            for key, edit in self.editors.items():
                column = self.columns[key]
                cell = self.table.item(row, column) if row >= 0 else None
                underlying = self.table.cellWidget(row, column) if row >= 0 else None
                value = underlying.currentText() if isinstance(underlying, QComboBox) else cell.text() if cell else ''
                with QSignalBlocker(edit):
                    if isinstance(edit, QComboBox):
                        index = edit.findData(value)
                        if index < 0:
                            edit.addItem(value or 'Choose…', value); index = edit.count()-1
                        edit.setCurrentIndex(index)
                    else:
                        edit.setText(value); edit.setCursorPosition(0)
                    edit.setEnabled(row >= 0)
                    if isinstance(edit, QLineEdit) and cell:
                        edit.setReadOnly(not bool(cell.flags() & Qt.ItemFlag.ItemIsEditable))
        finally:
            self._updating = False

    def _select(self, row):
        if self._updating or row < 0: return
        self.table.setCurrentCell(row, max(0, self.table.currentColumn()))
        self.refresh()

    def _write(self, key):
        if self._updating: return
        row, column = self.table.currentRow(), self.columns[key]
        if row < 0: return
        edit = self.editors[key]
        value = edit.currentData() if isinstance(edit, QComboBox) else edit.text()
        self._updating = True
        try:
            underlying = self.table.cellWidget(row, column)
            if isinstance(underlying, QComboBox): underlying.setCurrentText(str(value))
            cell = self.table.item(row, column)
            if cell is None: self.table.setItem(row, column, QTableWidgetItem(str(value)))
            else: cell.setText(str(value))
            if column == 0:
                with QSignalBlocker(self.selector): self.selector.setItemText(row, str(value))
        finally:
            self._updating = False

    def set_field_visible(self, key, visible):
        self.forms[key].setRowVisible(self.editors[key], visible)

    def reveal(self, row, key, message=''):
        if row < 0 or row >= self.table.rowCount(): return False
        key = key if key in self.editors else next(iter(self.editors))
        self.table.setCurrentCell(row, self.columns[key]); self.refresh()
        if key in self.advanced_keys: self.advanced_toggle.setChecked(True)
        self.set_field_visible(key, True)
        return reveal_and_focus(self.editors[key], message=message)


def replace_section(workspace, index, body):
    """Replace only presentation; moved canonical controls keep signals and state."""
    workspace.tabs.widget(index).setWidget(body)


def native_form(parent=None):
    form = QFormLayout(parent)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return form


def restyle_inspectors(workspace):
    from qt_common import COLORS, theme_manager
    colors = COLORS[theme_manager().mode]
    workspace.setStyleSheet(f'''
        QWidget#studyInspector {{ background: {colors['panel']}; border-radius: 8px; }}
        QWidget#studyInspector QLabel {{ background: transparent; }}
        QLabel#studyPageTitle {{ font-size: 23px; font-weight: 600; }}
    ''')


def install_result_picker(panel, preferred):
    """Keep every artifact view reachable without an overflowing tab strip."""
    panel.tabs.tabBar().hide()
    chooser = QComboBox(); chooser.setAccessibleName('Result view')
    for i in range(panel.tabs.count()):
        chooser.addItem(preferred.get(panel.tabs.tabText(i), panel.tabs.tabText(i)), i)
    chooser.currentIndexChanged.connect(panel.tabs.setCurrentIndex)
    panel.tabs.currentChanged.connect(chooser.setCurrentIndex)
    panel.layout().insertWidget(0, chooser)
    panel.view_selector = chooser
    panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)


class TransportResultsPanel(ResearchResultsPanel):
    def __init__(self, store, parent=None):
        super().__init__(store, 'sesame_transport', parent)
        page = QWidget(); layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.states = QComboBox(); self.states.setAccessibleName('Saved bias state')
        self.quantity = QComboBox(); self.quantity.setAccessibleName('Transport field or band diagram')
        self.quantity.addItem('Band diagram (eV)', '__bands__')
        for caption, key in [('Potential (V)', 'potential_V'), ('Electrons (cm⁻³)', 'electrons_cm3'),
                ('Holes (cm⁻³)', 'holes_cm3'), ('Bulk recombination (cm⁻³ s⁻¹)', 'bulk_recombination_cm3_s'),
                ('Generation (cm⁻³ s⁻¹)', 'generation_cm3_s'), ('Electron quasi-Fermi level (eV)', 'electron_quasi_fermi_eV'),
                ('Hole quasi-Fermi level (eV)', 'hole_quasi_fermi_eV'), ('Conduction band (eV)', 'conduction_band_eV'),
                ('Valence band (eV)', 'valence_band_eV')]:
            self.quantity.addItem(caption, key)
        self.section = QSpinBox(); self.section.setAccessibleName('Transverse slice index')
        row.addWidget(self.states, 1); row.addWidget(self.quantity, 1)
        row.addWidget(label('y slice')); row.addWidget(self.section)
        layout.addLayout(row)
        self.state_plot = PlotWidget(); layout.addWidget(self.state_plot, 1)
        self.state_note = label('Select a saved bias state.'); layout.addWidget(self.state_note)
        self.tabs.insertTab(1, page, 'Fields & bands')
        self.state = None
        self.states.currentIndexChanged.connect(self.load_state)
        self.quantity.currentIndexChanged.connect(self.draw_state)
        self.section.valueChanged.connect(self.draw_state)
        install_result_picker(self, {'Plot': 'Current–voltage and saved curves', 'Fields & bands': 'Carrier maps and energy bands'})

    def load_directory(self, path):
        loaded = super().load_directory(path)
        self.states.blockSignals(True); self.states.clear()
        if loaded:
            for file in sorted(Path(path).glob('transport_state_*.npz')):
                self.states.addItem(file.name, str(file))
        self.states.blockSignals(False)
        self.load_state()
        return loaded

    def load_state(self, *args):
        self.state = None
        self.state_plot.clear()
        self.state_note.setText('This run has no saved transport field or band states.')
        with QSignalBlocker(self.section):
            self.section.setRange(0, 0)
        self.section.setEnabled(False)
        for index in range(self.quantity.count()):
            self.quantity.model().item(index).setEnabled(False)
        path = self.states.currentData()
        if not path:
            return
        try:
            with np.load(path, allow_pickle=False) as data:
                state = {key: data[key].copy() for key in data.files}
            for key in ('x_um', 'y_um'):
                values = np.asarray(state[key], dtype=float)
                if (values.ndim != 1 or not len(values) or not np.isfinite(values).all()
                        or np.any(np.diff(values) <= 0)):
                    raise ValueError(key+' must contain finite increasing coordinates.')
                state[key] = values
            voltage = np.asarray(state['voltage_V'], dtype=float)
            if voltage.ndim != 0 or not np.isfinite(voltage):
                raise ValueError('Saved bias must be one finite voltage.')
            shape = (len(state['y_um']), len(state['x_um']))
            for index in range(1, self.quantity.count()):
                key = self.quantity.itemData(index)
                if key in state:
                    values = np.asarray(state[key], dtype=float)
                    if values.shape != shape:
                        raise ValueError('Saved '+key+' does not match the x/y coordinates.')
                    state[key] = values
            # Commit only a complete, shape-checked state. A failed load must
            # never leave a prior run's field or a partially loaded archive.
            self.state = state
            available = []
            for index in range(self.quantity.count()):
                key = self.quantity.itemData(index)
                exists = (all(name in state for name in ('conduction_band_eV', 'valence_band_eV',
                    'electron_quasi_fermi_eV', 'hole_quasi_fermi_eV')) if key == '__bands__' else key in state)
                self.quantity.model().item(index).setEnabled(exists)
                if exists: available.append(index)
            with QSignalBlocker(self.quantity):
                if self.quantity.currentIndex() not in available:
                    self.quantity.setCurrentIndex(available[0] if available else -1)
            with QSignalBlocker(self.section):
                self.section.setRange(0, shape[0]-1)
            self.section.setEnabled(shape[0] > 1)
            self.draw_state()
        except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile) as exc:
            self.state = None
            self.state_plot.clear()
            self.state_note.setText('Cannot load saved state: '+str(exc))

    def draw_state(self, *args):
        if self.state is None:
            return
        state, key, section = self.state, self.quantity.currentData(), self.section.value()
        self.state_plot.clear()
        if key is None or (key != '__bands__' and key not in state):
            self.state_note.setText('The selected quantity was not saved in this bias state.')
            return
        if key == '__bands__' and not all(name in state for name in ('conduction_band_eV', 'valence_band_eV',
                'electron_quasi_fermi_eV', 'hole_quasi_fermi_eV')):
            self.state_note.setText('A complete band diagram was not saved in this bias state.')
            return
        figure = Figure(figsize=(7, 4), layout='constrained')
        if key == '__bands__':
            axis = figure.add_subplot(111)
            for field, caption in [('conduction_band_eV', 'Conduction band'), ('valence_band_eV', 'Valence band'),
                                    ('electron_quasi_fermi_eV', 'Electron quasi-Fermi'), ('hole_quasi_fermi_eV', 'Hole quasi-Fermi')]:
                axis.plot(state['x_um'], state[field][section], label=caption)
            axis.set_ylabel('Energy (eV)'); axis.legend(fontsize=8)
        elif len(state['y_um']) > 1:
            axis, line = figure.subplots(1, 2)
            image = axis.pcolormesh(state['x_um'], state['y_um'], state[key], shading='nearest')
            figure.colorbar(image, ax=axis, label=self.quantity.currentText())
            axis.set_ylabel('y (µm)'); axis.set_xlabel('x (µm)')
            line.plot(state['x_um'], state[key][section])
            line.set_ylabel(self.quantity.currentText()); axis = line
        else:
            axis = figure.add_subplot(111)
            axis.plot(state['x_um'], state[key][section]); axis.set_ylabel(self.quantity.currentText())
        axis.set_xlabel('x (µm)'); axis.grid(True, alpha=.25)
        self.state_plot.draw_figure(figure)
        self.state_note.setText(f'Bias {float(state["voltage_V"]):.6g} V · y = {state["y_um"][section]:.6g} µm. '
            'Saved engine quantities; defect energy uses the intrinsic-level reference.')


class SesameSetupWorkspace(ResearchWorkspaceBase):
    workspace_id = 'research_studies'
    state_key = 'sesame'
    material_keys = ('id', 'Nc', 'Nv', 'Eg', 'epsilon', 'mu_e', 'mu_h', 'tau_e', 'tau_h', 'affinity', 'Et', 'B', 'Cn', 'Cp', 'mass_e', 'mass_h')
    region_keys = ('id', 'material', 'x_range_um', 'y_range_um', 'donors_cm3', 'acceptors_cm3', 'generation_cm3_s')
    defect_keys = ('id', 'location_um', 'density_cm2', 'sigma_e_cm2', 'sigma_h_cm2', 'energy_eV', 'transition')

    def __init__(self, store, parent=None, *, document_id=None):
        super().__init__(store, parent, document_id=document_id)
        self.heading.setText('Semiconductor transport · Sesame')
        self.description.setText('An editable 1D or 2D rectilinear semiconductor domain with two end contacts. '
            'Boltzmann carriers and fixed temperature; no 3D contacts, tunnelling or self-heating.')
        _, device = self.add_section('Device')
        form = QFormLayout()
        self.dimension = self.choice(form, 'Domain dimensions', 'dimension', [('1D transport', 1), ('2D transport', 2)])
        self.x_nodes = self.line(form, 'Explicit transport mesh nodes', 'x_nodes_um', '0, 0.25, 0.5, 0.75, 1', 'µm')
        self.y_nodes = self.line(form, 'Explicit transverse mesh nodes (2D)', 'y_nodes_um', '0, 0.25, 0.5, 0.75, 1', 'µm')
        device.addLayout(form)
        device.addWidget(label('Nodes must increase strictly. Regions must fill the domain without overlapping interiors; '
            'region and defect endpoints must coincide with mesh nodes. Later regions own shared interface nodes.'))
        self.regions = _table(['Stable ID', 'Material ID', 'x min, max (µm)', 'y min, max (µm)', 'Donors (cm⁻³)', 'Acceptors (cm⁻³)', 'Generation (cm⁻³ s⁻¹)'], 'Semiconductor material and doping regions')
        _fill(self.regions, [['region_1', 'material_1', '0, 1', '0, 1', '0', '0', '0']])
        device.addWidget(self.regions)
        self.fields['regions'] = self.regions
        row = QHBoxLayout()
        row.addWidget(button('Add region', lambda: self.add_row(self.regions, ['region_'+uuid.uuid4().hex[:8], 'material_1', '', '', '0', '0', '0'])))
        row.addWidget(button('Remove selected region', lambda: self.remove_row(self.regions)))
        row.addStretch(); device.addLayout(row)
        _, materials = self.add_section('Materials')
        materials.addWidget(label('Fill every required property. Nc/Nv: cm⁻³; Eg/affinity/Et: eV; εr: dimensionless; '
            'mobilities: cm²/(V s); lifetimes: s; B: cm³/s; Cn/Cp: cm⁶/s; masses: relative electron mass. '
            'Et is relative to the intrinsic level. Blank optional recombination coefficients use zero; blank masses use 1.'))
        self.materials = _table(list(self.material_keys), 'Editable semiconductor material properties')
        from PyQt6.QtWidgets import QHeaderView
        self.materials.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.materials.horizontalHeader().setDefaultSectionSize(110)
        _fill(self.materials, [['material_1']+['']*(len(self.material_keys)-1)])
        materials.addWidget(self.materials)
        self.fields['materials'] = self.materials
        row = QHBoxLayout()
        row.addWidget(button('Add material', lambda: self.add_row(self.materials, ['material_'+uuid.uuid4().hex[:8]]+['']*(len(self.material_keys)-1))))
        row.addWidget(button('Remove selected material', lambda: self.remove_row(self.materials)))
        row.addStretch(); materials.addLayout(row)
        _, contacts = self.add_section('Contacts')
        contacts.addWidget(label('The left contact is the reference. The bias sequence is applied to the right contact. '
            'Ohmic or Schottky contacts need explicit electron/hole velocities; Schottky contacts also need work function.'))
        self.contacts = _table(['Side', 'Kind', 'Electron velocity (cm/s)', 'Hole velocity (cm/s)', 'Work function (eV)'], 'End contact conditions')
        _fill(self.contacts, [['left', 'Ohmic', '', '', ''], ['right', 'Ohmic', '', '', '']])
        self.fields['contacts'] = self.contacts
        contacts.addWidget(self.contacts)
        _, defects = self.add_section('Defects')
        defects.addWidget(label('Optional grain-boundary states. 1D location is x; 2D line endpoints use x,y; x,y (µm). '
            'Density is cm⁻², capture cross sections cm², energy eV relative to the intrinsic level. '
            'Transition lists empty, occupied charge states (for example 1,0).'))
        self.defects = _table(['Stable ID', 'Location (µm)', 'Density (cm⁻²)', 'Electron capture (cm²)', 'Hole capture (cm²)', 'Energy (eV)', 'Charge transition'], 'Point or line defect states')
        defects.addWidget(self.defects)
        self.fields['defects'] = self.defects
        row = QHBoxLayout()
        row.addWidget(button('Add defect', lambda: self.add_row(self.defects, ['defect_'+uuid.uuid4().hex[:8], '', '', '', '', '', '1, 0'])))
        row.addWidget(button('Remove selected defect', lambda: self.remove_row(self.defects)))
        row.addStretch(); defects.addLayout(row)
        _, study = self.add_section('Study')
        form = QFormLayout()
        self.voltages = self.line(form, 'Right-contact bias sequence', 'voltages_V', '0, 0.05, 0.1', 'V')
        self.temperature = self.line(form, 'Fixed temperature', 'temperature_K', '300', 'K')
        self.periodic = QCheckBox('Periodic transverse boundary (2D)')
        self.periodic.setToolTip('Sesame uses period = last y node − first y node + first y spacing. The endpoint is not a duplicated periodic node.')
        form.addRow(self.periodic)
        self.fields['periodic_y'] = self.periodic
        study.addLayout(form)
        study.addWidget(label('Outputs include current versus bias, potential/carrier maps, quasi-Fermi levels, recombination '
            'and section-current conservation. A nonlinear solve that fails remains failed; a partial bias sequence is never presented as complete.'))
        study.addStretch()
        _, solver = self.add_section('Solver')
        form = QFormLayout()
        self.tolerance = self.line(form, 'Newton update tolerance', 'tolerance', '1e-9')
        self.max_iterations = self.line(form, 'Maximum Newton iterations', 'max_iterations', '300')
        self.runtime_mode = self.choice(form, 'Runtime location', 'runtime.mode', [('Local', 'local'), ('WSL', 'wsl')])
        self.executable = self.line(form, 'Python executable', 'runtime.executable', sys.executable)
        self.distro = self.line(form, 'WSL distribution', 'runtime.distro', 'Ubuntu')
        self.module_paths = self.line(form, 'Python package folders', 'runtime.module_paths', '', '', 'Explicit paths separated by semicolons')
        self.library_paths = self.line(form, 'Shared-library folders', 'runtime.library_paths', '', '', 'Explicit native-library paths separated by semicolons')
        self.timeout = self.line(form, 'Saved runtime value', 'runtime.timeout_s', '86400', 's')
        form.setRowVisible(self.timeout, False)
        form.addRow('Elapsed-time limit', label('None. Use Stop to cancel.'))
        solver.addLayout(form)
        solver.addWidget(label('Select a Python installation containing Sesame and its dependencies. '
            'WSL requires an absolute Linux Python path. Runtime availability is checked when starting the worker.'))
        actions = QHBoxLayout()
        actions.addWidget(button('Import editable settings…', self.import_settings))
        actions.addWidget(button('Export settings…', self.export_settings))
        solver.addLayout(actions)
        solver.addStretch()
        self.results = TransportResultsPanel(store, self)
        self.tabs.addTab(self.results, 'Results')
        for table in (self.regions, self.materials, self.contacts, self.defects):
            table.cellChanged.connect(self._edited)
        self.periodic.toggled.connect(self._edited)
        self.dimension.currentIndexChanged.connect(self._dimension_changed)
        self._dimension_changed()
        self._build_guided_setup()
        self.finish_build()
        from qt_study_flow import install_study_flow
        self.study_flow = install_study_flow(self, [('Domain', [0]), ('Materials', [1]), ('Contacts & defects', [2, 3]), ('Bias & accuracy', [4, 5])],
            subtitle='Build the transport domain, assign its physical properties, then apply a bias sequence.',
            details='Independent 1D / 2D rectilinear domain. Fixed temperature and Boltzmann carriers; no tunnelling or self-heating.')
        self._queue_clean_refresh()

    def _build_guided_setup(self):
        self.heading.setText('Semiconductor transport'); self.heading.setObjectName('studyPageTitle')
        self._preview_timer = QTimer(self); self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120); self._preview_timer.timeout.connect(self.preview_domain)
        self.inspectors = {}
        descriptors = {
            'regions': [('id', 'Region name / ID', None), ('material', 'Material', [('material_1','material_1')]),
                ('x_range_um', 'x start, end (µm)', None), ('y_range_um', 'y start, end (µm)', None),
                ('donors_cm3', 'Donor density (cm⁻³)', None), ('acceptors_cm3', 'Acceptor density (cm⁻³)', None),
                ('generation_cm3_s', 'Carrier generation (cm⁻³ s⁻¹)', None)],
            'materials': list(zip(self.material_keys, ['Material name / ID', 'Conduction density of states Nc (cm⁻³)',
                'Valence density of states Nv (cm⁻³)', 'Band gap Eg (eV)', 'Relative permittivity εr',
                'Electron mobility (cm² / V s)', 'Hole mobility (cm² / V s)', 'Electron lifetime (s)', 'Hole lifetime (s)',
                'Electron affinity (eV)', 'Trap energy relative to intrinsic level (eV)', 'Radiative coefficient B (cm³ / s)',
                'Electron Auger coefficient Cn (cm⁶ / s)', 'Hole Auger coefficient Cp (cm⁶ / s)',
                'Electron effective mass / m₀', 'Hole effective mass / m₀'], [None]*len(self.material_keys))),
            'contacts': [('side', 'Contact side', None), ('kind', 'Contact type', [('Ohmic', 'Ohmic'), ('Schottky', 'Schottky')]),
                ('electron_velocity_cm_s', 'Electron surface velocity (cm / s)', None),
                ('hole_velocity_cm_s', 'Hole surface velocity (cm / s)', None), ('work_function_eV', 'Work function (eV)', None)],
            'defects': [('id', 'Grain-boundary name / ID', None), ('location_um', 'Position / line endpoints (µm)', None),
                ('density_cm2', 'Defect density (cm⁻²)', None), ('sigma_e_cm2', 'Electron capture cross section (cm²)', None),
                ('sigma_h_cm2', 'Hole capture cross section (cm²)', None), ('energy_eV', 'Energy relative to intrinsic level (eV)', None),
                ('transition', 'Charge states: empty, occupied', None)]}
        for key, title in [('regions', 'Selected region'), ('materials', 'Selected material'),
                           ('contacts', 'Selected contact'), ('defects', 'Selected grain boundary')]:
            self.inspectors[key] = TableRowInspector(getattr(self, key), descriptors[key], title,
                advanced=('B', 'Cn', 'Cp', 'mass_e', 'mass_h') if key == 'materials' else ())
        for group, noun, default in [('regions', 'region', ['region_', 'material_1', '', '', '0', '0', '0']),
                ('materials', 'material', ['material_']+['']*15),
                ('defects', 'boundary', ['defect_', '', '', '', '', '', '1, 0'])]:
            editor = self.inspectors[group]
            editor.actions.addWidget(button('Add '+noun, lambda _, g=group, values=default: self.add_row(getattr(self, g), [values[0]+uuid.uuid4().hex[:8]]+values[1:])))
            editor.actions.addWidget(button('Remove', lambda _, g=group: self.remove_row(getattr(self, g))))
        # A compact domain editor with a true-coordinate preview, independent of material/runtime readiness.
        body = QWidget(); layout = QVBoxLayout(body)
        top = QHBoxLayout(); top.addWidget(label('Transport domain', 'setupHeading')); top.addStretch(); top.addWidget(self.dimension)
        layout.addLayout(top)
        self.domain_summary = label(''); layout.addWidget(self.domain_summary)
        self.domain_splitter = QSplitter(Qt.Orientation.Horizontal)
        context = QWidget(); left = QVBoxLayout(context); left.setContentsMargins(0, 0, 0, 0)
        self.domain_preview = PlotWidget(); self.domain_preview.setMinimumSize(260, 290)
        self.domain_preview.canvas.mpl_connect('button_press_event', self._select_domain_geometry)
        self.domain_preview.toolbar.hide(); left.addWidget(self.domain_preview, 1)
        self.preview_note = label(''); self.preview_note.setToolTip('The sketch uses region and grain-boundary geometry only. Material and runtime settings are validated separately.')
        left.addWidget(self.preview_note)
        self.mesh_toggle = QCheckBox('Edit mesh nodes'); left.addWidget(self.mesh_toggle)
        self.mesh_body = QWidget(); mesh = native_form(self.mesh_body)
        mesh.addRow('x nodes (µm)', self.x_nodes); mesh.addRow('y nodes (µm)', self.y_nodes)
        self.x_nodes.setMinimumWidth(100); self.y_nodes.setMinimumWidth(100)
        left.addWidget(self.mesh_body); self.mesh_body.hide(); self.mesh_toggle.toggled.connect(self.mesh_body.setVisible)
        self.mesh_form = mesh
        left.addWidget(label('Region edges and grain-boundary endpoints must lie on mesh nodes. Region order is preserved at shared interfaces.'))
        self.region_scroll=QScrollArea(); self.region_scroll.setWidgetResizable(True)
        self.region_scroll.setWidget(self.inspectors['regions']); self.region_scroll.setMinimumWidth(280)
        self.domain_splitter.addWidget(context); self.domain_splitter.addWidget(self.region_scroll)
        self.domain_splitter.setStretchFactor(0, 3); self.domain_splitter.setStretchFactor(1, 2)
        layout.addWidget(self.domain_splitter, 1); replace_section(self, 0, body)
        # Materials and contacts retain independent sections and exact targets.
        self.assignment_previews = {}
        for index, group, caption, explanation in [
            (1, 'materials', 'Material properties', 'Choose a material and enter its electrical properties. Required values are never filled from an unrelated example.'),
            (2, 'contacts', 'Two end contacts', 'The left end is the reference. The bias sequence raises the right-contact potential. Both carrier surface velocities are explicit.'),
            (3, 'defects', 'Grain boundaries · optional', 'In 1D enter one x coordinate. In 2D enter two endpoints as x, y; x, y. Leave this list empty when no grain boundary is intended.')]:
            body = QWidget(); box = QVBoxLayout(body)
            box.addWidget(label(caption, 'setupHeading')); box.addWidget(label(explanation))
            split = QSplitter(Qt.Orientation.Horizontal)
            preview = PlotWidget(); preview.setMinimumSize(230, 280); preview.toolbar.hide()
            preview.canvas.mpl_connect('button_press_event', self._select_domain_material if group=='materials' else self._select_domain_geometry)
            split.addWidget(preview)
            scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(self.inspectors[group])
            scroll.setMinimumWidth(290); scroll.setMaximumWidth(500)
            split.addWidget(scroll); split.setStretchFactor(0,3); split.setStretchFactor(1,2)
            box.addWidget(split,1); replace_section(self, index, body)
            self.assignment_previews[group]=(preview,split,scroll)
        self.inspectors['materials'].note.setText('Additional coefficients default to zero when blank; blank effective masses retain the solver default of 1. All required material values remain explicit.')
        self.inspectors['defects'].note.setText('Defect energy is referenced to the intrinsic level. The two charge states describe empty and occupied defects.')
        # Bias and temperature are the ordinary Calculate controls; installation/numerics are separate.
        body = QWidget(); box = QVBoxLayout(body); form = native_form()
        form.addRow('Right-contact biases (V)', self.voltages); form.addRow('Fixed temperature (K)', self.temperature)
        form.addRow(self.periodic); box.addLayout(form)
        self.periodic_note = label(''); box.addWidget(self.periodic_note)
        self.transport_review = QTextBrowser(); self.transport_review.setMinimumHeight(200)
        box.addWidget(self.transport_review, 1)
        box.addWidget(button('Solver installation and advanced accuracy…', lambda: self.select_section('Solver')))
        replace_section(self, 4, body)
        self.study_layout = box
        from qt_research_runtime import ResearchRuntimeCheck
        self.runtime_check = ResearchRuntimeCheck(lambda: dict(engine='sesame_transport',runtime=self.runtime_settings()), self)
        self.runtime_check.runtimeReady.connect(self._apply_automatic_runtime)
        self.study_layout.insertWidget(3,self.runtime_check)
        body = QWidget(); box = QVBoxLayout(body); form = native_form()
        form.addRow('Run on', self.runtime_mode); form.addRow('Python executable', self.executable)
        form.addRow('WSL distribution', self.distro); box.addLayout(form); self.runtime_form = form
        box.addWidget(label('Choose the Python environment containing Sesame. Checking an installation does not change this physical domain.'))
        box.addWidget(button('Use saved solver setup', self.use_saved_runtime))
        box.addWidget(button('Remember this solver setup', self.remember_runtime))
        self.solver_advanced_toggle = QCheckBox('Advanced solver and package settings'); box.addWidget(self.solver_advanced_toggle)
        self.solver_advanced = QWidget(); form = native_form(self.solver_advanced)
        for title, edit in [('Newton update tolerance', self.tolerance), ('Maximum Newton iterations', self.max_iterations),
                            ('Python package folders (semicolon separated)', self.module_paths),
                            ('Shared-library folders (semicolon separated)', self.library_paths), ('Saved runtime value', self.timeout)]:
            form.addRow(title, edit)
        form.setRowVisible(self.timeout, False)
        form.addRow('Elapsed-time limit', label('None. Use Stop to cancel.'))
        box.addWidget(self.solver_advanced); self.solver_advanced.hide()
        self.solver_advanced_toggle.toggled.connect(self.solver_advanced.setVisible)
        row = QHBoxLayout(); row.addWidget(button('Import settings…', self.import_settings)); row.addWidget(button('Export settings…', self.export_settings))
        box.addLayout(row); box.addStretch(); replace_section(self, 5, body)
        self.solver_layout = box
        for table in (self.regions, self.materials, self.contacts, self.defects):
            table.cellChanged.connect(self._queue_clean_refresh)
            table.currentCellChanged.connect(self._queue_clean_refresh)
        for edit in (self.x_nodes, self.y_nodes, self.voltages, self.temperature): edit.textChanged.connect(self._queue_clean_refresh)
        self.runtime_mode.currentIndexChanged.connect(self._refresh_clean_ui)
        self.runtime_mode.currentIndexChanged.connect(self.runtime_check.invalidate)
        for edit in (self.executable,self.distro,self.module_paths,self.library_paths,self.timeout): edit.textChanged.connect(self.runtime_check.invalidate)
        self.periodic.toggled.connect(self._refresh_clean_ui)
        from qt_common import theme_manager
        theme_manager().changed.connect(self._restyle_inspectors)
        restyle_inspectors(self)

    def _restyle_inspectors(self, *args):
        """A QObject-bound receiver disconnects when this page is deleted."""
        restyle_inspectors(self)

    def runtime_settings(self):
        runtime = super().runtime_settings()
        if runtime is not None:
            runtime['library_paths'] = [path.strip() for path in self.library_paths.text().split(';') if path.strip()]
        return runtime

    def _apply_automatic_runtime(self, runtime):
        for key, value in runtime.items():
            control = self.fields.get('runtime.'+key)
            if isinstance(control, QComboBox): control.setCurrentIndex(max(0, control.findData(value)))
            elif isinstance(control, QLineEdit): control.setText('; '.join(value) if isinstance(value, list) else str(value))
        self.remember_runtime()
        self.runtime_check.check()

    def remember_runtime(self):
        from qt_research_runtime import remember_runtime
        try:
            remember_runtime('sesame_transport',self.runtime_settings())
            self.status.setText('Saved solver setup on this computer. Physical inputs are unchanged.')
        except ValueError as exc: self.status.setText(str(exc))

    def use_saved_runtime(self):
        from qt_research_runtime import load_saved_runtime
        runtime=load_saved_runtime('sesame_transport')
        if not runtime:
            self.status.setText('No saved Sesame setup on this computer. Enter the installation below.')
            return
        for key,value in runtime.items():
            edit=self.fields.get('runtime.'+key)
            if isinstance(edit,QComboBox): edit.setCurrentIndex(edit.findData(value))
            elif isinstance(edit,QLineEdit): edit.setText('; '.join(value) if isinstance(value,list) else str(value))
        self.runtime_check.invalidate()
        self.status.setText('Loaded the saved solver setup. Check installation before running.')

    def _queue_clean_refresh(self, *args):
        if hasattr(self, '_preview_timer'): self._preview_timer.start()
        self._refresh_clean_ui()

    def _refresh_clean_ui(self, *args):
        if not hasattr(self, 'inspectors'): return
        material_choice=self.inspectors['regions'].editors['material']
        if not self.inspectors['regions']._updating:
            with QSignalBlocker(material_choice):
                material_choice.clear()
                for row in _rows(self.materials): material_choice.addItem(row[0],row[0])
        for inspector in self.inspectors.values(): inspector.refresh()
        two = self.dimension.currentData() == 2
        self.inspectors['regions'].set_field_visible('y_range_um', two)
        contact = self.contacts.currentRow()
        kind = self.contacts.item(contact, 1).text() if contact >= 0 else ''
        self.inspectors['contacts'].set_field_visible('work_function_eV', kind == 'Schottky')
        self.mesh_form.setRowVisible(self.y_nodes, two)
        self.runtime_form.setRowVisible(self.distro, self.runtime_mode.currentData() == 'wsl')
        self.periodic.setVisible(two)
        try:
            x = self._sequence(self.x_nodes.text(), 'x_nodes_um')
            y = self._sequence(self.y_nodes.text(), 'y_nodes_um') if two else [0]
            self.domain_summary.setText(f'{2 if two else 1}D domain · x {x[0]:g} to {x[-1]:g} µm · {len(x)} x nodes'+
                (f' × {len(y)} y nodes' if two else '')+f' · {self.regions.rowCount()} regions')
            period = y[-1]-y[0]+y[1]-y[0] if two and len(y)>1 else 0
            self.periodic_note.setText(f'Transverse periodic length: {period:g} µm (node span + first interval).' if two and self.periodic.isChecked() else '')
        except (ValueError, IndexError): self.domain_summary.setText('Finish the mesh coordinates to update the domain summary.')
        self.transport_review.setHtml('<h3>What will be calculated</h3><p>Apply the right-contact bias sequence <b>'+escape(self.voltages.text())+
            ' V</b> at <b>'+escape(self.temperature.text())+' K</b>.</p><p>Save current versus bias, carrier and potential maps, energy bands, '+
            'recombination and current-conservation checks.</p><p><b>Model boundary:</b> 1D / 2D drift–diffusion, Boltzmann carriers, fixed temperature. '+
            'No tunnelling or self-heating. Partial or failed bias sequences retain their solver status.</p>')

    def preview_domain(self):
        from matplotlib.patches import Rectangle
        try:
            two = self.dimension.currentData() == 2
            x = self._sequence(self.x_nodes.text(), 'x_nodes_um')
            y = self._sequence(self.y_nodes.text(), 'y_nodes_um') if two else [0, 1]
            if len(x)<2 or len(y)<2 or any(a>=b for a,b in zip(x,x[1:])) or any(a>=b for a,b in zip(y,y[1:])):
                raise ValueError('mesh nodes must increase')
            parsed=[]
            for row in _rows(self.regions):
                xr=vector(row[2],2,'regions.x_range_um'); yr=vector(row[3],2,'regions.y_range_um') if two else [0,1]
                if xr[0]>=xr[1] or yr[0]>=yr[1]: raise ValueError('region bounds must increase')
                parsed.append((row,xr,yr))
            figure=Figure(figsize=(6,4),layout='constrained'); ax=figure.add_subplot(111)
            palette=['#569CD6','#7CB8A0','#D6A66A','#A89BD1','#D17E8C']
            mats=list(dict.fromkeys(row[0][1] for row in parsed))
            for i,(row,xr,yr) in enumerate(parsed):
                selected=i==self.regions.currentRow()
                ax.add_patch(Rectangle((xr[0],yr[0]),xr[1]-xr[0],yr[1]-yr[0],facecolor=palette[mats.index(row[1])%len(palette)],
                    alpha=.55,edgecolor='#2563EB' if selected else '#52657A',linewidth=2.5 if selected else 1))
                ax.text(sum(xr)/2,sum(yr)/2,row[0]+'\n'+row[1],ha='center',va='center',fontsize=9,clip_on=True)
            for row in _rows(self.defects):
                if not row[1].strip(): continue
                if two:
                    points=[vector(p,2,'defects.location_um') for p in row[1].split(';')]
                    if len(points)!=2: raise ValueError('grain-boundary line needs two endpoints')
                    ax.plot([p[0] for p in points],[p[1] for p in points],color='#B45309',linewidth=2)
                else: ax.axvline(number(row[1],'defects.location_um'),color='#B45309',linewidth=2)
            for node in x:
                ax.axvline(node, color='#66788a', alpha=.16, linewidth=.6)
            if two:
                for node in y:
                    ax.axhline(node, color='#66788a', alpha=.16, linewidth=.6)
            ax.axvline(x[0], color='#334155', linewidth=3)
            ax.axvline(x[-1], color='#2563eb', linewidth=3)
            ax.set_xlim(x[0],x[-1]); ax.set_ylim(y[0],y[-1]); ax.set_xlabel('x · transport direction (µm)')
            if two: ax.set_ylabel('y (µm)'); ax.set_aspect('equal',adjustable='box')
            else: ax.set_yticks([]); ax.set_ylabel('1D region schematic')
            ax.set_title('Reference contact  →  Biased contact',fontsize=9)
            self.domain_preview.draw_figure(figure)
            for preview, _, _ in self.assignment_previews.values():
                preview.draw_figure(figure)
            self.preview_note.setText('Region and grain-boundary geometry preview.')
        except (ValueError, IndexError, TypeError) as exc:
            self.preview_note.setText('Preview needs geometry input: '+str(exc)+'. The last valid view is retained.')

    def _select_domain_geometry(self, event):
        """Native plot hits select the existing authoritative table inspector."""
        if event.xdata is None or not self._is_active_document():
            return
        try:
            nodes = self._sequence(self.x_nodes.text(), 'x_nodes_um')
            tolerance = (nodes[-1] - nodes[0]) * .02
            if abs(event.xdata-nodes[0]) <= tolerance or abs(event.xdata-nodes[-1]) <= tolerance:
                side = 'left' if abs(event.xdata-nodes[0]) <= tolerance else 'right'
                self.open_diagnostic(dict(field='contacts.kind', object_id=side))
                return
            two = self.dimension.currentData() == 2
            for row in _rows(self.defects):
                if not row[1].strip():
                    continue
                if two and event.ydata is not None:
                    a,b=[np.asarray(vector(v,2,'defects.location_um')) for v in row[1].split(';')]
                    delta=b-a; position=np.array([event.xdata,event.ydata])
                    fraction=np.clip(np.dot(position-a,delta)/max(np.dot(delta,delta),1e-30),0,1)
                    hit=np.linalg.norm(position-(a+fraction*delta))<=tolerance
                else:
                    hit=abs(event.xdata-number(row[1],'defects.location_um'))<=tolerance
                if hit:
                    self.open_diagnostic(dict(field='defects.energy_eV',object_id=row[0]))
                    return
            for row in reversed(_rows(self.regions)):
                xr = vector(row[2], 2, 'regions.x_range_um')
                yr = vector(row[3], 2, 'regions.y_range_um') if two else [0, 1]
                if xr[0] <= event.xdata <= xr[1] and (not two or event.ydata is not None and yr[0] <= event.ydata <= yr[1]):
                    self.open_diagnostic(dict(field='regions.material', object_id=row[0]))
                    return
        except (ValueError, IndexError, TypeError):
            self.preview_note.setText('Finish the region bounds before selecting its geometry. Your draft is retained.')

    def _select_domain_material(self, event):
        if event.xdata is None or not self._is_active_document():
            return
        try:
            two=self.dimension.currentData()==2
            for row in reversed(_rows(self.regions)):
                xr=vector(row[2],2,'regions.x_range_um')
                yr=vector(row[3],2,'regions.y_range_um') if two else [0,1]
                if xr[0]<=event.xdata<=xr[1] and (not two or event.ydata is not None and yr[0]<=event.ydata<=yr[1]):
                    self.open_diagnostic(dict(field='materials.Nc',object_id=row[1]))
                    return
        except (ValueError,IndexError,TypeError):
            return

    def adapt_layout(self):
        if hasattr(self,'study_flow'): self.study_flow.adapt_layout()
        if hasattr(self,'domain_splitter'):
            self.domain_splitter.setMinimumHeight(330)
            self.domain_splitter.setMaximumHeight(390 if self.width()<1000 else 550)
            self.domain_splitter.setSizes([max(280,self.width()-370),320])
        for _, split, scroll in getattr(self,'assignment_previews',{}).values():
            split.setOrientation(Qt.Orientation.Vertical if self.width()<900 else Qt.Orientation.Horizontal)
            scroll.setMaximumWidth(16777215 if self.width()<900 else 500)

    def _dimension_changed(self, *args):
        active=getattr(self.store,'active_study','sesame_transport')
        target='sesame_transport.2d' if self.dimension.currentData()==2 else 'sesame_transport'
        if self.switch_study_variant(target,self.dimension,2 if active.endswith('.2d') else 1):return
        two = self.dimension.currentData() == 2
        self.y_nodes.setEnabled(two)
        self.periodic.setEnabled(two)
        self.regions.setColumnHidden(3, not two)
        self._queue_clean_refresh()

    def add_row(self, table, row):
        rows = _rows(table); rows.append(row); _fill(table, rows)
        table.setCurrentCell(table.rowCount()-1, 0)
        self._edited(); self._queue_clean_refresh()

    def remove_row(self, table):
        if table.currentRow() >= 0:
            table.removeRow(table.currentRow()); self._edited(); self._queue_clean_refresh()

    def draft(self):
        state = super().draft()
        state.update({key: _rows(getattr(self, key)) for key in ('regions', 'materials', 'contacts', 'defects')})
        state['periodic_y'] = self.periodic.isChecked()
        return state

    def restore_draft(self, state):
        super().restore_draft(state)
        for key in ('regions', 'materials', 'contacts', 'defects'):
            if key in state:
                _fill(getattr(self, key), state[key])
        self.periodic.setChecked(state.get('periodic_y', False))
        self._dimension_changed()
        self._queue_clean_refresh()

    def _sequence(self, text, field, **kwargs):
        values = text.replace(',', ' ').split()
        if not values:
            raise FieldError(field, 'Enter at least one value.')
        return [number(value, field, **kwargs) for value in values]

    def options(self):
        dim = self.dimension.currentData()
        cfg = dict(dimension=dim, x_nodes_um=self._sequence(self.x_nodes.text(), 'x_nodes_um'),
            temperature_K=number(self.temperature.text(), 'temperature_K', positive=True),
            voltages_V=self._sequence(self.voltages.text(), 'voltages_V'), periodic_y=self.periodic.isChecked() if dim == 2 else False,
            tolerance=number(self.tolerance.text(), 'tolerance', positive=True),
            max_iterations=number(self.max_iterations.text(), 'max_iterations', integer=True, minimum=1),
            runtime=dict(mode=self.runtime_mode.currentData(), executable=self.executable.text(), distro=self.distro.text(),
                timeout_s=number(self.timeout.text(), 'runtime.timeout_s', positive=True),
                module_paths=[path.strip() for path in self.module_paths.text().split(';') if path.strip()],
                library_paths=[path.strip() for path in self.library_paths.text().split(';') if path.strip()]), materials={}, regions=[], contacts={}, defects=[])
        if dim == 2:
            cfg['y_nodes_um'] = self._sequence(self.y_nodes.text(), 'y_nodes_um')
        for axis in ('x', 'y')[:dim]:
            values = cfg[axis+'_nodes_um']
            if len(values) < 3 or any(a >= b for a, b in zip(values, values[1:])):
                raise FieldError(axis+'_nodes_um', 'Supply at least three strictly increasing mesh nodes.', units='µm')
        for values in _rows(self.materials):
            row = dict(zip(self.material_keys, values)); identity = row.pop('id').strip()
            if not identity or identity in cfg['materials']:
                raise FieldError('materials.id', 'Material IDs must be nonempty and unique.', identity)
            material = {}
            for key, value in row.items():
                if key in ('B', 'Cn', 'Cp', 'mass_e', 'mass_h') and not value.strip():
                    continue
                material[key] = number(value, 'materials.'+key, positive=key not in ('affinity', 'Et', 'B', 'Cn', 'Cp'),
                    minimum=0 if key in ('B', 'Cn', 'Cp') else None, object_id=identity)
            cfg['materials'][identity] = material
        for values in _rows(self.regions):
            row = dict(zip(self.region_keys, values)); identity = row['id'].strip()
            region = dict(id=identity, material=row['material'].strip(),
                x_range_um=vector(row['x_range_um'], 2, 'regions.x_range_um', object_id=identity))
            if dim == 2:
                region['y_range_um'] = vector(row['y_range_um'], 2, 'regions.y_range_um', object_id=identity)
            for key in ('donors_cm3', 'acceptors_cm3', 'generation_cm3_s'):
                region[key] = number(row[key], 'regions.'+key, minimum=0, object_id=identity)
            cfg['regions'].append(region)
        for values in _rows(self.contacts):
            side, kind, electron, hole, work = values
            if side not in ('left', 'right') or side in cfg['contacts']:
                raise FieldError('contacts', 'Contact sides must be exactly left and right.')
            if kind not in ('Ohmic', 'Schottky'):
                raise FieldError('contacts.kind', 'Choose Ohmic or Schottky.', side)
            row = dict(kind=kind, electron_velocity_cm_s=number(electron, 'contacts.electron_velocity_cm_s', minimum=0, object_id=side),
                hole_velocity_cm_s=number(hole, 'contacts.hole_velocity_cm_s', minimum=0, object_id=side))
            if kind == 'Schottky':
                row['work_function_eV'] = number(work, 'contacts.work_function_eV', positive=True, object_id=side)
            cfg['contacts'][side] = row
        for values in _rows(self.defects):
            row = dict(zip(self.defect_keys, values)); identity = row['id']
            location = (number(row['location_um'], 'defects.location_um', object_id=identity) if dim == 1 else
                [vector(value.strip(), 2, 'defects.location_um', object_id=identity) for value in row['location_um'].split(';')])
            defect = dict(id=identity, location_um=location, energy_eV=number(row['energy_eV'], 'defects.energy_eV', object_id=identity),
                transition=self._sequence(row['transition'], 'defects.transition', integer=True, object_id=identity))
            for key in ('density_cm2', 'sigma_e_cm2', 'sigma_h_cm2'):
                defect[key] = number(row[key], 'defects.'+key, positive=True, object_id=identity)
            cfg['defects'].append(defect)
        return dict(engine='sesame_transport', study='drift_diffusion', settings=cfg)

    def open_diagnostic(self, target):
        field, identity = target.get('field', '').removeprefix('settings.'), target.get('object_id')
        keys = {'materials': self.material_keys, 'regions': self.region_keys, 'defects': self.defect_keys,
                'contacts': ('side', 'kind', 'electron_velocity_cm_s', 'hole_velocity_cm_s', 'work_function_eV')}
        group = field.split('.')[0]
        if group in keys:
            table = getattr(self, group)
            rows = _rows(table)
            match = next((i for i, row in enumerate(rows) if row[0] == identity), None) if identity else (max(0,table.currentRow()) if rows else None)
            if match is None:
                self.status.setText('That object no longer exists. Recheck the current draft.')
                return False
            key = field.rsplit('.', 1)[-1]
            column = keys[group].index(key) if key in keys[group] else 0
            table.setCurrentCell(match, column)
            self.tabs.setCurrentIndex({'regions': 0, 'materials': 1, 'contacts': 2, 'defects': 3}[group])
            return self.inspectors[group].reveal(match, keys[group][column], target.get('message', ''))
        if field in ('x_nodes_um', 'y_nodes_um'):
            self.mesh_toggle.setChecked(True)
        if field in ('tolerance', 'max_iterations', 'runtime.module_paths', 'runtime.library_paths', 'runtime.timeout_s'):
            self.solver_advanced_toggle.setChecked(True)
        return super().open_diagnostic(target)

    def load_settings(self, cfg):
        if not isinstance(cfg, dict):
            raise ValueError('Semiconductor settings must be a JSON object.')
        if 'dimension' in getattr(self,'_document_fields',{}) and cfg.get('dimension',1)!=self._document_fields['dimension']:
            raise ValueError('These settings belong to the other transport dimension. Choose that simulation before importing them.')
        from sesame_transport import prepare
        runtime_draft = {key: control.currentData() if isinstance(control, QComboBox) else control.text()
            for key, control in self.fields.items() if key.startswith('runtime.')} if 'runtime' not in cfg else {}
        validation_cfg = deepcopy(cfg)
        # A physical-only file has no runtime to import or validate. Preserve the
        # current raw installation draft, including unfinished input, for Check.
        validation_cfg.setdefault('runtime', {'mode': 'local', 'executable': sys.executable})
        prepare({}, validation_cfg)
        self._loading = True
        try:
            self.restore_draft(self._default_draft)
            self.dimension.setCurrentIndex(self.dimension.findData(cfg.get('dimension', 1)))
            for key in ('x_nodes_um', 'y_nodes_um', 'voltages_V'):
                if key in cfg:
                    self.fields[key].setText(', '.join(map(str, cfg[key])))
            for key in ('temperature_K', 'tolerance', 'max_iterations'):
                if key in cfg:
                    self.fields[key].setText(str(cfg[key]))
            self.periodic.setChecked(cfg.get('periodic_y', False))
            _fill(self.materials, [[identity]+[str(value.get(key, '')) for key in self.material_keys[1:]] for identity, value in cfg['materials'].items()])
            def display(value):
                if isinstance(value, list):
                    return '; '.join(', '.join(map(str, row)) for row in value) if value and isinstance(value[0], list) else ', '.join(map(str, value))
                return str(value)
            for group, keys in [('regions', self.region_keys), ('defects', self.defect_keys)]:
                _fill(getattr(self, group), [[display(row.get(key, 0 if key in ('donors_cm3', 'acceptors_cm3', 'generation_cm3_s') else '')) for key in keys] for row in cfg.get(group, [])])
            _fill(self.contacts, [[side, row['kind'], row['electron_velocity_cm_s'], row['hole_velocity_cm_s'], row.get('work_function_eV', '')] for side, row in cfg['contacts'].items()])
            runtime = cfg.get('runtime') or {}
            for key in ('executable', 'distro', 'timeout_s'):
                if key in runtime:
                    self.fields['runtime.'+key].setText(str(runtime[key]))
            if 'mode' in runtime:
                self.runtime_mode.setCurrentIndex(self.runtime_mode.findData(runtime['mode']))
            self.module_paths.setText('; '.join(runtime.get('module_paths', [])))
            self.library_paths.setText('; '.join(runtime.get('library_paths', [])))
            for key, value in runtime_draft.items():
                control = self.fields[key]
                if isinstance(control, QComboBox):
                    control.setCurrentIndex(control.findData(value))
                else:
                    control.setText(value)
            self._dimension_changed()
        finally:
            self._loading = False
        self._queue_clean_refresh()
        self.save_draft()

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import editable semiconductor settings', '', 'JSON (*.json)')
        if path:
            try:
                with open(path, encoding='utf-8') as stream:
                    value = json.load(stream)
                if not isinstance(value, dict):
                    raise ValueError('Semiconductor settings must be a JSON object.')
                self.load_settings(value.get('settings', value))
            except (OSError, ValueError, KeyError) as exc:
                self.status.setText('Import failed: '+str(exc))

    def export_settings(self):
        try:
            value = self.options()
        except ValueError as exc:
            self.diagnostics.set_diagnostics([self._issue(exc)], workspace=self.workspace_id)
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export editable semiconductor settings', 'semiconductor-transport.json', 'JSON (*.json)')
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as stream:
                    json.dump(value, stream, indent=2, allow_nan=False)
            except OSError as exc:
                self.status.setText('Export failed: '+str(exc))
