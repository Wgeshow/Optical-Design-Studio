"""Sourced transport configuration; physical inputs remain drafts until Apply."""
from copy import deepcopy

from PyQt6.QtCore import QSignalBlocker
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget)


MODE_LABELS = {
    'disabled': 'Static electrostatics / frozen Ohmic estimate',
    'dielectric_leakage': 'Dielectric leakage with explicit material laws',
    'semiconductor_dd': 'Semiconductor drift diffusion / continuity',
}
MECHANISM_LABELS = {
    'ohmic': 'Bulk Ohmic', 'poole_frenkel': 'Poole–Frenkel',
    'schottky': 'Schottky emission', 'fowler_nordheim': 'Fowler–Nordheim',
    'direct_tunneling': 'Direct tunneling',
}
LEAKAGE_FIELDS = {
    'ohmic': [('conductivity_S_m', 'Conductivity (S/m)')],
    'poole_frenkel': [('conductivity_prefactor_S_m', 'Conductivity prefactor (S/m)'),
        ('trap_depth_eV', 'Trap depth (eV)'), ('optical_epsilon_r', 'Optical relative permittivity')],
    'schottky': [('richardson_A_m2_K2', 'Richardson constant (A/m²/K²)'),
        ('barrier_eV', 'Injection barrier (eV)'), ('optical_epsilon_r', 'Optical relative permittivity')],
    'fowler_nordheim': [('barrier_eV', 'Barrier height (eV)'), ('tunnel_mass_ratio', 'Tunneling mass / free-electron mass')],
    'direct_tunneling': [('barrier_eV', 'Barrier height (eV)'), ('tunnel_mass_ratio', 'Tunneling mass / free-electron mass')],
}
SEMICONDUCTOR_GROUPS = {
    'srh': ('SRH generation / recombination', [
        ('tau_n_s', 'Electron lifetime (s)'), ('tau_p_s', 'Hole lifetime (s)'),
        ('trap_energy_eV', 'Trap energy relative to intrinsic level (eV)')]),
    'high_field_mobility': ('High-field mobility / velocity saturation', [
        ('electron_saturation_velocity_cm_s', 'Electron saturation velocity (cm/s)'),
        ('hole_saturation_velocity_cm_s', 'Hole saturation velocity (cm/s)'),
        ('electron_exponent', 'Electron exponent (≥ 1)'), ('hole_exponent', 'Hole exponent (≥ 1)')]),
    'avalanche': ('Local impact ionization', [
        ('electron_A_cm1', 'Electron A (cm⁻¹)'), ('electron_B_V_cm', 'Electron B (V/cm)'),
        ('electron_exponent', 'Electron field exponent'), ('hole_A_cm1', 'Hole A (cm⁻¹)'),
        ('hole_B_V_cm', 'Hole B (V/cm)'), ('hole_exponent', 'Hole field exponent'),
        ('temperature_K', 'Coefficient temperature (K)'), ('maximum_field_V_cm', 'Maximum calibrated field (V/cm, optional)')]),
}


def transport_path_hint(device, cfg):
    """Nonallocating layout hint; backend preflight remains authoritative."""
    if cfg.get('mode', 'disabled') != 'semiconductor_dd': return 'inactive'
    if cfg.get('statistics', 'boltzmann') == 'fermi_dirac' or cfg.get('heterojunction'): return 'graph'
    layers = [row for row in (device or {}).get('layers', []) if row.get('enabled', True)]
    ids = {row['id'] for row in layers}
    if not layers or len({row['material_id'] for row in layers}) != 1: return 'graph'
    if any(row.get('enabled', True) and row.get('layer_id') in ids for group in ('shapes', 'doping_regions', 'pc_arrays') for row in device.get(group, [])): return 'graph'
    contacts = [row for row in device.get('contacts', []) if row.get('enabled', True) and row.get('layer_id') in ids]
    if len(contacts) != 2: return 'graph'
    top = [row for row in contacts if row.get('surface') == 'top' and row.get('layer_id') == layers[0]['id']]
    bottom = [row for row in contacts if row.get('surface') == 'bottom' and row.get('layer_id') == layers[-1]['id']]
    if len(top) != 1 or len(bottom) != 1 or any(row.get('shape') != 'rectangle' for row in contacts): return 'graph'
    import numpy as np
    from device_model import shape_mask
    x = np.array([-1., -1., 1., 1.])*device['width_um']/2
    y = np.array([-1., 1., -1., 1.])*device['depth_um']/2
    return 'planar' if all(np.all(shape_mask(row, x, y)) for row in contacts) else 'graph'


def _label(text, name='setupMuted'):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def _scroll(content):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(content)
    return scroll


def _number_text(value):
    return '' if value is None else format(value, '.15g') if isinstance(value, (float, int)) else str(value)


def _reference_link(reference, explanation):
    from qt_common import theme_manager
    accent = theme_manager().resolve_colors()['accent']
    link = _label(f'<a href="{reference}" style="color:{accent}">Model equation reference</a> · {explanation}')
    link.setOpenExternalLinks(True)
    return link


class _ParameterGroup(QFrame):
    def __init__(self, key, title, fields, cfg=None, parent=None):
        super().__init__(parent)
        self.setObjectName('setupCard')
        self.key = key
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox('Include ' + title)
        self.enabled.setObjectName('transportEnable_' + key)
        self.enabled.setChecked(cfg is not None)
        layout.addWidget(self.enabled)
        self.content = QWidget()
        form = QFormLayout(self.content)
        self.controls = {}
        for field, title in fields:
            editor = QLineEdit(_number_text((cfg or {}).get(field)))
            editor.setObjectName('transport_' + key + '_' + field)
            editor.setAccessibleName(title)
            self.controls[field] = editor
            form.addRow(title, editor)
        self.source = QPlainTextEdit((cfg or {}).get('parameter_source', ''))
        self.source.setPlaceholderText('Publication / dataset and conditions, measurement, or explicitly identified assumption. Required when included.')
        self.source.setMaximumHeight(74)
        self.source.setObjectName('transport_' + key + '_parameter_source')
        form.addRow('Parameter source and conditions', self.source)
        from electrical_transport import REFERENCES
        reference = REFERENCES[{'srh':'srh', 'high_field_mobility':'velocity_saturation', 'avalanche':'avalanche_implementation'}[key]]
        link = _reference_link(reference, 'supply the parameter dataset and conditions above.')
        form.addRow(link)
        layout.addWidget(self.content)
        self.enabled.toggled.connect(self.content.setEnabled)
        self.content.setEnabled(self.enabled.isChecked())

    def value(self):
        if not self.enabled.isChecked():
            return None
        result = dict(parameter_source=self.source.toPlainText())
        for key, editor in self.controls.items():
            if key == 'maximum_field_V_cm' and not editor.text().strip():
                continue
            result[key] = editor.text().strip()
        return result


class TransportSetupDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        self.setObjectName('setupDialog')
        self.setWindowTitle('Physical transport & breakdown settings')
        self.resize(900, 840)
        current = workspace.state.get('search.electrical.transport', {}) or {}
        self.material_models = deepcopy(current.get('material_models', {}))
        self.breakdown_fields = deepcopy(current.get('breakdown_fields', {}))
        self._material_id = None
        self._mechanism = None
        self._mechanism_drafts = {}
        layout = QVBoxLayout(self)
        layout.addWidget(_label('Physical transport & breakdown', 'setupCardTitle'))
        layout.addWidget(_label('Choose the model, enter sourced parameters, then Apply physical settings. Changing a control does not change the applied simulation.'))
        layout.addWidget(_label('Every enabled group or material law must be complete, including retained fits for another mode. Disable incomplete unused fits before Apply.'))
        mode_form = QFormLayout()
        self.mode = QComboBox()
        self.mode.setObjectName('transportMode')
        for value, title in MODE_LABELS.items(): self.mode.addItem(title, value)
        self.mode.setCurrentIndex(self.mode.findData(current.get('mode', 'disabled')))
        mode_form.addRow('Physical model', self.mode)
        layout.addLayout(mode_form)
        self.scope = _label('')
        layout.addWidget(self.scope)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('transportTabs')
        layout.addWidget(self.tabs, 1)
        semiconductor = QWidget()
        sem_layout = QVBoxLayout(semiconductor)
        statistics_form = QFormLayout()
        self.statistics = QComboBox()
        self.statistics.setObjectName('transportStatistics')
        self.statistics.addItem('Boltzmann · nondegenerate', 'boltzmann')
        self.statistics.addItem('Fermi–Dirac · experimental bulk parabolic bands / 3D graph', 'fermi_dirac')
        self.statistics.setCurrentIndex(self.statistics.findData(current.get('statistics', 'boltzmann')))
        statistics_form.addRow('Carrier statistics', self.statistics)
        sem_layout.addLayout(statistics_form)
        self.heterojunction = QCheckBox('Use an explicit ideal quasi-Fermi interface model for a heterojunction')
        self.heterojunction.setObjectName('transportHeterojunction')
        self.heterojunction.setChecked(bool(current.get('heterojunction')))
        sem_layout.addWidget(self.heterojunction)
        self.interface_source = QPlainTextEdit((current.get('heterojunction') or {}).get('parameter_source', ''))
        self.interface_source.setMaximumHeight(76)
        self.interface_source.setObjectName('transportInterfaceSource')
        self.interface_source.setPlaceholderText('Reference / justification, or explicitly identified ideal-interface assumption. Required when selected.')
        self.interface_source.setEnabled(self.heterojunction.isChecked())
        self.heterojunction.toggled.connect(self.interface_source.setEnabled)
        sem_layout.addWidget(_label('Ideal-interface parameter source and conditions'))
        sem_layout.addWidget(self.interface_source)
        from electrical_transport import REFERENCES
        sem_layout.addWidget(_reference_link(REFERENCES['fermi_dirac_transport'], 'Fermi–Dirac transport formulation.'))
        sem_layout.addWidget(_reference_link(REFERENCES['heterojunction_interface_limits'], 'interface-model scope; supply an explicit ideal-interface justification above.'))
        self.statistics_scope = _label('')
        sem_layout.addWidget(self.statistics_scope)
        sem_layout.addWidget(_label('Lifetimes, trap energies and avalanche coefficients are optional explicit inputs. No values are inferred from a material name or filled to match a paper. Local avalanche requires sourced velocity-saturation parameters.'))
        self.groups = {}
        for key, (title, fields) in SEMICONDUCTOR_GROUPS.items():
            group = _ParameterGroup(key, title, fields, current.get(key))
            self.groups[key] = group
            sem_layout.addWidget(group)
        sem_layout.addStretch()
        self.tabs.addTab(_scroll(semiconductor), 'Semiconductor')
        self._make_material_page(current)
        self._make_numerical_page(current)
        self.status = _label('', 'setupError')
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText('Apply physical settings')
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.statistics.currentIndexChanged.connect(self._mode_changed)
        self.heterojunction.toggled.connect(self._mode_changed)
        self._mode_changed()

    def _make_material_page(self, current):
        content = QWidget()
        layout = QVBoxLayout(content)
        form = QFormLayout()
        self.material = QComboBox()
        self.material.setObjectName('transportMaterial')
        library = self.workspace.state.store.electrical_materials
        active_ids = {row['material_id'] for row in (self.workspace.state.store.device or {}).get('layers', []) if row.get('enabled', True)}
        for row in library:
            self.material.addItem(row['name'] + (' · used by device' if row['id'] in active_ids else ''), row['id'])
        form.addRow('Electrical material', self.material)
        layout.addLayout(form)
        self.leak_enabled = QCheckBox('Use an explicit leakage law for this material')
        self.leak_enabled.setObjectName('transportLeakageEnabled')
        layout.addWidget(self.leak_enabled)
        self.leak_content = QWidget()
        self.leak_form = QFormLayout(self.leak_content)
        self.mechanism = QComboBox()
        self.mechanism.setObjectName('transportMechanism')
        for value, title in MECHANISM_LABELS.items(): self.mechanism.addItem(title, value)
        self.leak_form.addRow('Leakage mechanism', self.mechanism)
        self.parameter_content = QWidget()
        self.parameter_form = QFormLayout(self.parameter_content)
        self.leak_form.addRow(self.parameter_content)
        self.material_controls = {}
        self.material_source = QPlainTextEdit()
        self.material_source.setMaximumHeight(90)
        self.material_source.setPlaceholderText('Source, specimen / electrode conditions, temperature, calibrated field or voltage range. Required.')
        self.material_source.setObjectName('transportMaterialSource')
        self.leak_form.addRow('Parameter source and conditions', self.material_source)
        layout.addWidget(self.leak_content)
        self.threshold_enabled = QCheckBox('Evaluate an explicit critical-field criterion for this material')
        self.threshold_enabled.setObjectName('transportBreakdownEnabled')
        layout.addWidget(self.threshold_enabled)
        self.threshold_content = QWidget()
        threshold_form = QFormLayout(self.threshold_content)
        self.critical_field = QLineEdit()
        self.critical_field.setObjectName('transportCriticalField')
        self.threshold_source = QPlainTextEdit()
        self.threshold_source.setMaximumHeight(90)
        self.threshold_source.setObjectName('transportBreakdownSource')
        threshold_form.addRow('Critical electric field (V/m)', self.critical_field)
        threshold_form.addRow('Criterion source and conditions', self.threshold_source)
        layout.addWidget(self.threshold_content)
        layout.addWidget(_label('Field-threshold crossing is a screening criterion. It does not predict a damaged conducting filament or post-breakdown current. An invalid emission/tunneling point is reported unavailable instead of being replaced with zero.'))
        layout.addStretch()
        self.tabs.addTab(_scroll(content), 'Materials and field criteria')
        self.leak_enabled.toggled.connect(self.leak_content.setEnabled)
        self.threshold_enabled.toggled.connect(self.threshold_content.setEnabled)
        self.material.currentIndexChanged.connect(self._change_material)
        self.mechanism.currentIndexChanged.connect(self._change_mechanism)
        first = min((self.material.findData(mid) for mid in active_ids if self.material.findData(mid) >= 0), default=0)
        self.material.setCurrentIndex(first)
        self._change_material()

    def _make_numerical_page(self, current):
        content = QWidget()
        layout = QVBoxLayout(content)
        device = self.workspace.state.store.device or {}
        mesh = device.get('mesh', {})
        layers = sum(row.get('enabled', True) for row in device.get('layers', []))
        layout.addWidget(_label(f"Structure finite mesh: {mesh.get('nx', 0)} × {mesh.get('ny', 0)} × {mesh.get('nz_per_layer', 0)*layers} cells. Patterned, partial-contact and Fermi–Dirac transport use this actual 3D mesh."))
        self.path_readout = _label('')
        layout.addWidget(self.path_readout)
        self.custom_nodes = QCheckBox('Specify semiconductor transport depth intervals per layer')
        self.custom_nodes.setChecked('nodes_per_layer' in current)
        self.custom_nodes.setObjectName('transportCustomNodes')
        layout.addWidget(self.custom_nodes)
        form = QFormLayout()
        self.nodes = QLineEdit(_number_text(current.get('nodes_per_layer', max(4, mesh.get('nz_per_layer', 4)))))
        self.nodes.setObjectName('transportNodesPerLayer')
        self.nodes.setEnabled(self.custom_nodes.isChecked())
        self.custom_nodes.toggled.connect(self.nodes.setEnabled)
        form.addRow('Target transport depth intervals / layer (≥ 4)', self.nodes)
        self.max_step = QLineEdit(_number_text(current.get('max_bias_step_V', .1)))
        self.max_step.setObjectName('transportContinuationStep')
        form.addRow('Maximum internal continuation step (V)', self.max_step)
        layout.addLayout(form)
        layout.addWidget(_label('Target depth intervals apply to uniform planar Boltzmann transport only. That stored setting is inactive for the actual 3D graph path. The continuation step controls intermediate numerical states between requested outputs; it does not replace or reduce the voltage sweep point count. Configure output voltages in Study & bias sweep, and 3D counts in Structure / Finite device mesh.'))
        check = QPushButton('Check current device against selected model')
        check.clicked.connect(self.check_geometry)
        layout.addWidget(check)
        layout.addStretch()
        self.tabs.addTab(content, 'Numerics & validity')

    def _stash_material(self):
        mid = self._material_id
        if mid is None: return
        parameters = {key: editor.text().strip() for key, editor in self.material_controls.items()}
        parameters['parameter_source'] = self.material_source.toPlainText()
        self._mechanism_drafts[(mid, self._mechanism)] = deepcopy(parameters)
        if self.leak_enabled.isChecked():
            self.material_models[mid] = dict(mechanism=self._mechanism, parameters=parameters)
        else:
            self.material_models.pop(mid, None)
        if self.threshold_enabled.isChecked():
            self.breakdown_fields[mid] = dict(critical_field_V_m=self.critical_field.text().strip(), parameter_source=self.threshold_source.toPlainText())
        else:
            self.breakdown_fields.pop(mid, None)

    def _change_material(self):
        self._stash_material()
        self._material_id = self.material.currentData()
        model = self.material_models.get(self._material_id, {})
        self.leak_enabled.setChecked(bool(model))
        blocker = QSignalBlocker(self.mechanism)
        self.mechanism.setCurrentIndex(self.mechanism.findData(model.get('mechanism', 'ohmic')))
        del blocker
        self._mechanism = self.mechanism.currentData()
        self._load_material_parameters(model.get('parameters', {}))
        threshold = self.breakdown_fields.get(self._material_id, {})
        self.threshold_enabled.setChecked(bool(threshold))
        self.critical_field.setText(_number_text(threshold.get('critical_field_V_m')))
        self.threshold_source.setPlainText(threshold.get('parameter_source', ''))
        self.leak_content.setEnabled(self.leak_enabled.isChecked())
        self.threshold_content.setEnabled(self.threshold_enabled.isChecked())

    def _change_mechanism(self):
        self._stash_material()
        self._mechanism = self.mechanism.currentData()
        self._load_material_parameters(self._mechanism_drafts.get((self._material_id, self._mechanism), {}))

    def _load_material_parameters(self, parameters):
        while self.parameter_form.rowCount(): self.parameter_form.removeRow(0)
        self.material_controls = {}
        for key, title in LEAKAGE_FIELDS[self._mechanism]:
            editor = QLineEdit(_number_text(parameters.get(key)))
            editor.setObjectName('transportMaterial_' + key)
            editor.setAccessibleName(title)
            self.material_controls[key] = editor
            self.parameter_form.addRow(title, editor)
        self.material_source.setPlainText(parameters.get('parameter_source', ''))
        from electrical_transport import REFERENCES
        reference = REFERENCES[{'ohmic':'drift_diffusion', 'poole_frenkel':'schottky_poole_frenkel', 'schottky':'schottky_poole_frenkel', 'fowler_nordheim':'field_emission', 'direct_tunneling':'direct_tunneling'}[self._mechanism]]
        link = _reference_link(reference, 'this does not supply the specimen’s fitted parameters.')
        self.parameter_form.addRow(link)

    def _mode_changed(self):
        mode = self.mode.currentData()
        if mode == 'semiconductor_dd':
            path = transport_path_hint(self.workspace.state.store.device, dict(mode=mode, statistics=self.statistics.currentData(), heterojunction=self.heterojunction.isChecked()))
            text = 'Semiconductor Poisson and electron/hole continuity use the actual 3D finite mesh for patterns, partial contacts, Fermi–Dirac statistics and explicit supported interfaces; uniform planar Boltzmann devices use the native depth grid. Backend preflight decides the valid path.'
            self.tabs.setCurrentIndex(0)
        elif mode == 'dielectric_leakage':
            text = 'Explicit pre-damage material laws require a validated contacted dielectric device. Geometry, mechanism and voltage validity are checked; missing material parameters block the calculation.'
            self.tabs.setCurrentIndex(1)
        else:
            text = 'Static Poisson / Laplace and optional frozen Ohmic estimate remain selected. Sourced transport fits can be retained for later use.'
        path = transport_path_hint(self.workspace.state.store.device, dict(mode=mode, statistics=self.statistics.currentData(), heterojunction=self.heterojunction.isChecked()))
        planar = path == 'planar'
        self.custom_nodes.setEnabled(planar)
        self.nodes.setEnabled(planar and self.custom_nodes.isChecked())
        self.path_readout.setText('Expected path: native planar depth grid. Validate the current device before running.' if planar else 'Expected path: actual Structure 3D mesh; planar depth interval settings are inactive.' if path == 'graph' else 'Semiconductor transport is inactive; native depth interval settings are retained.')
        self.statistics_scope.setText('Experimental bulk parabolic-band Fermi–Dirac transport uses the actual 3D graph. The Boltzmann SRH group must be unchecked. A sourced ideal interface has zero interface resistance; finite thermionic transfer, interface tunneling and post-damage conduction are omitted.' if self.statistics.currentData() == 'fermi_dirac' else 'Boltzmann statistics require nondegenerate carrier densities. An explicit ideal heterojunction interface requires Fermi–Dirac statistics. Conductor volumes are unsupported; use ideal boundary electrodes only when that approximation is intended.')
        self.scope.setText(text)

    def config(self):
        self._stash_material()
        cfg = dict(mode=self.mode.currentData(), max_bias_step_V=self.max_step.text().strip(),
            statistics=self.statistics.currentData(),
            heterojunction=dict(model='ideal_quasi_fermi', parameter_source=self.interface_source.toPlainText()) if self.heterojunction.isChecked() else None,
            material_models=deepcopy(self.material_models), breakdown_fields=deepcopy(self.breakdown_fields))
        for key, group in self.groups.items(): cfg[key] = group.value()
        if self.custom_nodes.isChecked(): cfg['nodes_per_layer'] = self.nodes.text().strip()
        return cfg

    def check_geometry(self):
        try:
            from electrical_transport import validate_transport
            from electrical_transport_adapter import validate_transport_device
            cfg = validate_transport(self.config())
            if cfg['mode'] == 'disabled':
                self.status.setText('Transport is disabled; use Validate setup for the static electrostatic device.')
                return
            options = self.workspace.state._electrical_options()
            options['transport'] = cfg
            options['charge_model'] = 'semiconductor' if cfg['mode'] == 'semiconductor_dd' else 'dielectric'
            dispatch = validate_transport_device(options, cfg)
            self.status.setText(dispatch['scope'] + ' · Geometry and parameters pass preflight. Numerical and physical validity still require completed-run checks.')
        except (ValueError, TypeError, KeyError) as exc:
            self.status.setText(str(exc))

    def apply(self):
        try:
            self.workspace.state.apply_transport(self.config())
            self.workspace.set_status('Physical settings applied. Validate the current device and voltage sweep before running.')
            self.accept()
        except (ValueError, TypeError, KeyError) as exc:
            self.status.setText(str(exc))
