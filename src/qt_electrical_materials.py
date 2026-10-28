"""Native editable electrical materials and portable JSON import/export."""
from copy import deepcopy
import json

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

from electrical_material_library import (
    CARRIER_PROPERTY_KEYS, PROPERTY_FIELDS, builtin_materials, conductivity_S_m, evaluate_material,
    export_materials, import_materials, lookup_material, merge_materials,
    new_material, reference_properties, validate_materials,
)


class ElectricalMaterialDialog(QDialog):
    """Edit a detached material; no shared project state is changed until accepted."""
    def __init__(self, material=None, parent=None):
        super().__init__(parent)
        self._material = validate_materials([material])[0] if material is not None else new_material()
        if material is None:
            # An uncommitted new draft has no material facts. Explicit edits
            # and duplicates still receive their detached source values.
            self._material.update(properties={}, optical_material_name='', color='#7faadd')
        self._accepted_material = None
        self.setWindowTitle('Electrical material properties')
        self.resize(790, 720)
        layout = QVBoxLayout(self)
        intro = QLabel('Electrical values feed the carrier and Poisson models. Optical dispersion uses the linked optical material; static permittivity does not determine optical n/k.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        general = QWidget()
        form = QFormLayout(general)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name = QLineEdit(self._material['name'])
        self.ident = QLineEdit(self._material['id'])
        self.ident.setReadOnly(material is not None)
        self.ident.setToolTip('Stable ID preserves device assignments when a material is renamed.')
        self.kind = QComboBox()
        for label, value in [('Semiconductor', 'semiconductor'), ('Conductor / degenerate semiconductor', 'conductor'), ('Dielectric / void', 'dielectric')]:
            self.kind.addItem(label, value)
        self.kind.setCurrentIndex(self.kind.findData(self._material['kind']))
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(.01, 10000.)
        self.temperature.setDecimals(2)
        self.temperature.setSuffix(' K')
        self.temperature.setValue(self._material['temperature_K'])
        self.al_fraction = QDoubleSpinBox()
        self.al_fraction.setRange(0., 1.)
        self.al_fraction.setDecimals(6)
        self.al_fraction.setSingleStep(.05)
        self.al_fraction.setValue(self._material.get('al_fraction', .5))
        self.model = QComboBox()
        for label, value in [('User values / constant', 'constant'), ('GaAs reference', 'gaas_reference'), ('Silicon reference', 'silicon_reference'), ('AlGaAs alloy reference', 'algaas_reference')]:
            self.model.addItem(label, value)
        self.model.setCurrentIndex(self.model.findData(self._material.get('model', 'constant')))
        self.optical_material = QLineEdit(self._material.get('optical_material_name', ''))
        self.optical_material.setPlaceholderText('Name of material in the optical material library')
        self.color = QLineEdit(self._material.get('color', '#7faadd'))
        for title, widget in [('Name', self.name), ('Stable ID', self.ident), ('Material kind', self.kind),
                              ('Reference temperature', self.temperature), ('Parameter model', self.model),
                              ('Al fraction x (AlₓGa₁₋ₓAs)', self.al_fraction),
                              ('Optical material link', self.optical_material), ('Preview color', self.color)]:
            form.addRow(title, widget)
        self.reference_button = QPushButton('Update values from reference model')
        self.reference_button.clicked.connect(self.reset_reference_values)
        form.addRow(self.reference_button)
        note = QLabel('Reference models update band gap, density of states and intrinsic concentration when temperature or alloy fraction changes. Edited properties remain overrides. Mobilities remain editable constants; ITO defaults are assumptions for the device study.')
        note.setWordWrap(True)
        form.addRow(note)
        self.tabs.addTab(general, 'Material')

        props_page = QWidget()
        props_form = QFormLayout(props_page)
        props_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.controls = {}
        for key, label, unit in PROPERTY_FIELDS:
            value = self._material['properties'].get(key)
            control = QLineEdit('' if value is None else f'{value:.12g}')
            control.setObjectName('electrical_property_'+key)
            control.setPlaceholderText('Not specified' if 'optional' in label else 'Required for carrier models')
            control.setToolTip(f'{key}: {unit}. Scientific notation such as 8e20 is accepted.')
            self.controls[key] = control
            props_form.addRow(f'{label} [{unit}]', control)
        self.fixed_conductivity_button = QPushButton('Clear carrier fields for fixed conductivity')
        self.fixed_conductivity_button.setToolTip('Clears band gap, affinity, density of states, masses, mobilities, intrinsic and bulk carrier densities. Keeps permittivity, fixed conductivity, optical values and source records.')
        self.fixed_conductivity_button.clicked.connect(self._clear_carrier_fields)
        props_form.addRow(self.fixed_conductivity_button)
        prop_note = QLabel('A constant conductor in dielectric charge mode needs static permittivity and explicit fixed conductivity; carrier fields may be blank. Semiconductor charge models still require carrier data. Leave fixed conductivity blank to derive σ=q(nμₙ+pμₚ) from carrier properties. Constant optical n/k is optional; use a linked dataset for wavelength-dependent optics.')
        prop_note.setWordWrap(True)
        props_form.addRow(prop_note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(props_page)
        self.tabs.addTab(scroll, 'Electrical values')

        sources_page = QWidget()
        sources_layout = QVBoxLayout(sources_page)
        sources_layout.addWidget(QLabel('Source records (JSON list; retain URLs, units, conditions and assumptions)'))
        self.sources = QPlainTextEdit(json.dumps(self._material.get('sources', []), indent=2, ensure_ascii=False))
        self.sources.setPlaceholderText('[{"title":"My measured sample", "url":"https://…", "note":"300 K; sample and uncertainty", "kind":"measurement"}]')
        sources_layout.addWidget(self.sources, 2)
        sources_layout.addWidget(QLabel('Material notes and model limits'))
        self.notes = QPlainTextEdit(self._material.get('notes', ''))
        sources_layout.addWidget(self.notes, 1)
        self.tabs.addTab(sources_page, 'Sources and assumptions')

        self.status = QLabel('New custom material: electrical values and optical link are blank. Enter sourced values before saving.' if material is None else '')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.model.currentIndexChanged.connect(self._model_changed)
        self.kind.currentIndexChanged.connect(self._model_changed)
        self._model_changed()

    def _model_changed(self):
        model = self.model.currentData()
        self.al_fraction.setEnabled(model == 'algaas_reference')
        self.reference_button.setEnabled(model != 'constant')
        self.fixed_conductivity_button.setEnabled(model == 'constant' and self.kind.currentData() == 'conductor')

    def _clear_carrier_fields(self):
        if self.model.currentData() != 'constant' or self.kind.currentData() != 'conductor':
            return
        for key in CARRIER_PROPERTY_KEYS:
            self.controls[key].clear()
        self.status.setText('Carrier fields cleared: band gap, affinity, density of states, masses, mobilities and carrier densities. Permittivity, fixed conductivity, optical values and source records are unchanged. Enter an explicit fixed conductivity and use dielectric charge mode for field/Ohmic calculations.')

    def reset_reference_values(self):
        try:
            values = reference_properties(self.model.currentData(), self.temperature.value(), self.al_fraction.value())
            for key, value in values.items():
                self.controls[key].setText(f'{value:.12g}')
            # Explicit reset establishes the new baseline, removing manual overrides
            # for the reference fields while retaining mobility and bulk densities.
            self._material.update(model=self.model.currentData(), temperature_K=self.temperature.value())
            if self.model.currentData() == 'algaas_reference':
                self._material['al_fraction'] = self.al_fraction.value()
            self._material['properties'].update(values)
            self._material['property_overrides'] = [key for key in self._material.get('property_overrides', []) if key not in values]
            self.status.setText('Reference values updated. Mobility and sample-specific values remain editable.')
        except (ValueError, OverflowError) as exc:
            self.status.setText(str(exc))

    def material(self):
        if self._accepted_material is not None:
            return deepcopy(self._accepted_material)
        result = deepcopy(self._material)
        result.update(id=self.ident.text().strip(), name=self.name.text().strip(), kind=self.kind.currentData(),
                      model=self.model.currentData(), optical_material_name=self.optical_material.text().strip(),
                      color=self.color.text().strip(), notes=self.notes.toPlainText())
        try:
            result['sources'] = json.loads(self.sources.toPlainText() or '[]')
        except json.JSONDecodeError as exc:
            raise ValueError(f'Source records must be a JSON list: {exc.msg}.') from exc
        properties = deepcopy(result['properties'])
        for key, control in self.controls.items():
            raw = control.text().strip()
            if not raw:
                properties.pop(key, None)
            else:
                try:
                    properties[key] = float(raw)
                except (ValueError, OverflowError):
                    raise ValueError(f'{key} must be a number, for example 8e20.') from None
        result['properties'] = properties
        result['property_overrides'] = [key for key in result.get('property_overrides', []) if key in properties]
        if result['model'] == 'algaas_reference' and 'al_fraction' not in result:
            result['al_fraction'] = self.al_fraction.value()
        result = evaluate_material(result, self.temperature.value(), self.al_fraction.value() if result['model'] == 'algaas_reference' else None)
        return validate_materials([result])[0]

    def accept(self):
        try:
            self._accepted_material = self.material()
        except (ValueError, OverflowError) as exc:
            self.status.setText(str(exc))
            return
        super().accept()


class ElectricalMaterialManagerDialog(QDialog):
    """Manage the project's electrical library while retaining device ID references."""
    materialSelected = pyqtSignal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle('Electrical material library')
        self.resize(970, 650)
        layout = QVBoxLayout(self)
        intro = QLabel('Select a preset or add your own semiconductor, conductor or dielectric. Changes are saved with the project; source records travel with imported and exported materials.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        split = QSplitter()
        self.material_list = QListWidget()
        self.material_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        split.addWidget(self.material_list)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        split.addWidget(self.details)
        split.setSizes([260, 650])
        layout.addWidget(split, 1)
        row = QHBoxLayout()
        self.add_button = QPushButton('Add custom')
        self.edit_button = QPushButton('Edit selected')
        self.clone_button = QPushButton('Duplicate')
        self.import_button = QPushButton('Import JSON')
        self.export_button = QPushButton('Export JSON')
        self.reset_button = QPushButton('Add missing presets')
        for button, handler in [(self.add_button, self.add_material), (self.edit_button, self.edit_material),
                                (self.clone_button, self.duplicate_material), (self.import_button, self.import_library),
                                (self.export_button, self.export_library), (self.reset_button, self.add_missing_presets)]:
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.use_button = QPushButton('Use selected material')
        self.use_button.clicked.connect(self.use_selected)
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        buttons.addWidget(self.use_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.material_list.currentItemChanged.connect(self._selection_changed)
        self.material_list.itemDoubleClicked.connect(lambda _: self.edit_material())
        self.refresh()

    def _library(self):
        value = self.store.electrical_materials
        return validate_materials(value() if callable(value) else value)

    def selected_material_id(self):
        item = self.material_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def refresh(self, selected=None):
        selected = selected or self.selected_material_id()
        self.material_list.clear()
        for material in self._library():
            item = QListWidgetItem(material['name'])
            item.setData(Qt.ItemDataRole.UserRole, material['id'])
            item.setToolTip(f"{material['kind']} · {material['id']}")
            self.material_list.addItem(item)
            if material['id'] == selected:
                self.material_list.setCurrentItem(item)
        if self.material_list.currentItem() is None and self.material_list.count():
            self.material_list.setCurrentRow(0)
        self._selection_changed()

    def _selection_changed(self, *_):
        ident = self.selected_material_id()
        for button in (self.edit_button, self.clone_button, self.use_button):
            button.setEnabled(bool(ident))
        if not ident:
            self.details.clear()
            return
        material = lookup_material(self._library(), ident)
        lines = [f"{material['name']} ({material['kind']})", f"Reference temperature: {material['temperature_K']:g} K"]
        if 'al_fraction' in material:
            lines.append(f"Al fraction x: {material['al_fraction']:g}")
        try:
            lines.append(f'Equilibrium / fixed conductivity: {conductivity_S_m(material):.6g} S/m')
        except ValueError as exc:
            lines.append(str(exc))
        lines.extend(['', material.get('notes', ''), '', 'Electrical properties'])
        for key, label, unit in PROPERTY_FIELDS:
            if key in material['properties']:
                lines.append(f"{label}: {material['properties'][key]:.8g} {unit}")
        lines.extend(['', 'Sources and assumptions'])
        for source in material.get('sources', []):
            lines.extend([source.get('title', ''), source.get('url', ''), source.get('note', ''), ''])
        self.details.setPlainText('\n'.join(lines))

    def _edit(self, material):
        dialog = ElectricalMaterialDialog(material, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            value = dialog.material()
            self.store.set_electrical_materials(merge_materials(self._library(), [value]))
            self.refresh(value['id'])
            self.status.setText(f"Saved {value['name']}.")

    def add_material(self):
        self._edit(None)

    def edit_material(self):
        ident = self.selected_material_id()
        if ident:
            self._edit(lookup_material(self._library(), ident))

    def duplicate_material(self):
        ident = self.selected_material_id()
        if ident:
            original = lookup_material(self._library(), ident)
            self._edit(new_material(original['name']+' copy', original))

    def import_library(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Import electrical materials', '', 'Electrical material library (*.json)')
        if not filename:
            return
        try:
            incoming = import_materials(filename)
            merged = merge_materials(self._library(), incoming)
            self.store.set_electrical_materials(merged)
            self.refresh(incoming[0]['id'] if incoming else None)
            self.status.setText(f'Imported {len(incoming)} electrical material definitions.')
        except (OSError, ValueError) as exc:
            self.status.setText(f'Import failed: {exc}')

    def export_library(self):
        filename, _ = QFileDialog.getSaveFileName(self, 'Export electrical materials', 'electrical-materials.json', 'Electrical material library (*.json)')
        if not filename:
            return
        try:
            export_materials(filename, self._library())
            self.status.setText(f'Exported electrical library to {filename}.')
        except (OSError, ValueError) as exc:
            self.status.setText(f'Export failed: {exc}')

    def add_missing_presets(self):
        current = self._library()
        ids = {material['id'] for material in current}
        missing = [material for material in builtin_materials() if material['id'] not in ids]
        self.store.set_electrical_materials(current+missing)
        self.refresh()
        self.status.setText(f'Added {len(missing)} missing presets. Existing edits are retained.')

    def use_selected(self):
        ident = self.selected_material_id()
        if ident:
            self.materialSelected.emit(ident)
            self.accept()
