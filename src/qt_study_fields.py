"""Named, native forms backed by the existing lossless research draft tree."""
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget)
from qt_input_diagnostics import reveal_and_focus


NAMES = {
    'id': 'Name / stable ID', 'source': 'Parameter source or assumption',
    'electron_mass_ratio': 'Electron effective mass / m₀', 'hole_mass_ratios': 'Hole effective masses / m₀',
    'absorption_prefactor_cm1_sqrt_eV': 'Absorption coefficient (cm⁻¹ √eV)',
    'reference_gap_eV': 'Reference band gap (eV)', 'gap_eV': 'Band gap (eV)',
    'bandgap_eV': 'Band gap (eV)', 'electron_reduced_fermi': 'Electron reduced Fermi level',
    'hole_reduced_fermi': 'Hole reduced Fermi level',
    'field_V_m': 'Electric field (V/m)', 'eta_n': 'Electron reduced Fermi level',
    'eta_p': 'Hole reduced Fermi level', 'temperature_K': 'Temperature (K)',
    'electron_resistivity_ohm_cm2': 'Electron contact resistivity (Ω cm²)',
    'hole_resistivity_ohm_cm2': 'Hole contact resistivity (Ω cm²)',
    'tau_n_s': 'Electron lifetime (s)', 'tau_p_s': 'Hole lifetime (s)',
    'B_cm3_s': 'Radiative coefficient B (cm³/s)', 'Cn_cm6_s': 'Electron Auger coefficient (cm⁶/s)',
    'Cp_cm6_s': 'Hole Auger coefficient (cm⁶/s)', 'value_W_mK': 'Thermal conductivity (W/m/K)',
    'surface_velocity_cm_s': 'Surface recombination velocity (cm/s)',
    'Nc_exponent': 'Conduction density-of-states exponent', 'Nv_exponent': 'Valence density-of-states exponent',
    'path_min_um': 'Path start (µm)', 'path_max_um': 'Path end (µm)',
    'hole_reservoir_um': 'Hole reservoir position (µm)', 'electron_reservoir_um': 'Electron reservoir position (µm)',
    'transverse_mass_ratio': 'Transverse effective mass / m₀',
    'electron_gamma_mass_ratio': 'Γ-valley electron mass / m₀', 'hole_mass_ratio': 'Hole effective mass / m₀',
    'energy_order': 'Energy integration samples', 'transverse_order': 'Transverse integration samples',
    'maximum_iterations': 'Maximum iterations', 'temperature_tolerance_K': 'Temperature tolerance (K)',
    'minimum_temperature_K': 'Minimum valid temperature (K)', 'maximum_temperature_K': 'Maximum valid temperature (K)',
    'temperature_limit_K': 'Temperature validity limit (K)', 'ambient_temperature_K': 'Ambient temperature (K)',
    'electron_mobility_exponent': 'Electron mobility temperature exponent',
    'hole_mobility_exponent': 'Hole mobility temperature exponent',
    'conduction_partition': 'Conduction-band share (0–1)', 'trap_energy_eV': 'Trap energy (eV)',
    'void_conductivity_W_mK': 'Void thermal conductivity (W/m/K)',
    'power_by_layer_W': 'Power by layer (W)', 'conductivity_exponents': 'Conductivity temperature exponents',
    'model': 'Model', 'source_notes': 'Source / assumptions', 'materials': 'Materials',
}


def field_label(key):
    if key in NAMES:
        return NAMES[key]
    if str(key).isdigit():
        return 'Value '+str(int(key)+1)
    return str(key).replace('_', ' ').replace(' cm2', ' (cm²)').replace(' cm3', ' (cm³)').capitalize()


class SequenceField(QWidget):
    """One visible sequence field; incomplete numbers stay incomplete in drafts."""
    def __init__(self, editor, placeholder='', parent=None):
        super().__init__(parent)
        self.editor = editor
        self._writing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder or 'Comma-separated values')
        self.input.setAccessibleName(editor.field)
        layout.addWidget(self.input)
        self.input.textEdited.connect(self._write)
        editor.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        if self._writing:
            return
        root = self.editor.tree.topLevelItem(0)
        self.input.setText(', '.join(root.child(i).text(1) for i in range(root.childCount())))

    def _write(self, text):
        self._writing = True
        try:
            # Preserve an unfinished token (including a trailing comma).
            values = text.split(',') if ',' in text else text.split()
            self.editor.tree.blockSignals(True)
            root = self.editor.tree.topLevelItem(0)
            root.takeChildren()
            for index, token in enumerate(values):
                item = self.editor._append(root, index, 0.)
                item.setText(1, token.strip())
            self.editor.tree.blockSignals(False)
            self.editor.changed.emit()
        finally:
            self._writing = False

    def open_field(self, path='', object_id=''):
        return reveal_and_focus(self.input)


class NamedPropertyForm(QWidget):
    """Object selection and labeled fields; schema remains an optional detail."""
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._writing = False
        self._nodes = {}
        self._fields = {}
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter()
        self.navigator = QTreeWidget()
        self.navigator.setHeaderHidden(True)
        self.navigator.setAccessibleName(field_label(editor.field)+' objects')
        self.navigator.setMinimumWidth(130)
        self.navigator.setMaximumWidth(250)
        self.navigator.currentItemChanged.connect(self._select)
        self.splitter.addWidget(self.navigator)
        self.panel = QWidget()
        self.panel.setObjectName('studyFieldPanel')
        self.panel_layout = QVBoxLayout(self.panel)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setObjectName('setupHeading')
        self.panel_layout.addWidget(self.title)
        self.form_body = QWidget()
        self.form = QFormLayout(self.form_body)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.panel_layout.addWidget(self.form_body)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.panel_layout.addWidget(self.note)
        actions = QHBoxLayout()
        self.add_value = QPushButton('Add value')
        self.add_value.clicked.connect(self._add_value)
        actions.addWidget(self.add_value)
        self.remove_value = QPushButton('Remove last value')
        self.remove_value.clicked.connect(self._remove_value)
        actions.addWidget(self.remove_value)
        actions.addStretch()
        self.panel_layout.addLayout(actions)
        self.panel_layout.addStretch()
        self.splitter.addWidget(self.panel)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([190, 650])
        layout.addWidget(self.splitter)
        self.setMinimumHeight(210)
        editor.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        if self._writing:
            return
        selected = self.navigator.currentItem()
        path = selected.data(0, Qt.ItemDataRole.UserRole) if selected else ()
        self.navigator.blockSignals(True)
        self.navigator.clear()
        self._nodes = {}
        def append(source, parent, current):
            identifier = next((source.child(i).text(1) for i in range(source.childCount())
                               if source.child(i).text(0) in ('name', 'id')), '')
            title = identifier or field_label(source.text(0))
            node = QTreeWidgetItem(parent, [title])
            node.setData(0, Qt.ItemDataRole.UserRole, current)
            self._nodes[current] = (node, source)
            for i in range(source.childCount()):
                child = source.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) in ('object', 'array'):
                    append(child, node, current+(child.text(0),))
        append(self.editor.tree.topLevelItem(0), self.navigator, ())
        self.navigator.expandToDepth(1)
        self.navigator.blockSignals(False)
        chosen = self._nodes.get(path, self._nodes[()])[0]
        self.navigator.setCurrentItem(chosen)
        self.navigator.setVisible(len(self._nodes) > 1)
        self._select(chosen)

    def _select(self, node, previous=None):
        if node is None:
            return
        while self.form.rowCount():
            self.form.removeRow(0)
        self._fields = {}
        path = node.data(0, Qt.ItemDataRole.UserRole)
        source = self._nodes[path][1]
        self.title.setText(node.text(0))
        for index in range(source.childCount()):
            item = source.child(index)
            kind = item.data(0, Qt.ItemDataRole.UserRole)
            if kind in ('object', 'array'):
                continue
            if kind == 'boolean':
                control = QComboBox()
                control.addItems(['false', 'true'])
                control.setCurrentIndex(1 if item.text(1) == 'true' else 0)
                control.currentTextChanged.connect(lambda text, target=item: self._write(target, text))
            else:
                control = QLineEdit(item.text(1))
                control.setPlaceholderText('Required value' if kind == 'number' else '')
                control.textEdited.connect(lambda text, target=item: self._write(target, text))
            control.setAccessibleName(field_label(item.text(0)))
            control.setToolTip(field_label(item.text(0)))
            self.form.addRow(field_label(item.text(0)), control)
            self._fields[item.text(0)] = control
        self.note.setText('Choose a group on the left to edit its values.' if not self._fields and source.childCount()
                          else 'No values assigned yet. Add the input fields for this model to begin.' if not source.childCount()
                          else '')
        scalar_array = source.data(0, Qt.ItemDataRole.UserRole) == 'array' and all(
            source.child(i).data(0, Qt.ItemDataRole.UserRole) not in ('array', 'object') for i in range(source.childCount()))
        self.add_value.setVisible(scalar_array)
        self.remove_value.setVisible(scalar_array and source.childCount() > 0)

    def _array_source(self):
        node = self.navigator.currentItem()
        return self._nodes[node.data(0, Qt.ItemDataRole.UserRole)][1] if node else None

    def _add_value(self):
        source = self._array_source()
        if source is not None:
            self._writing = True
            item = self.editor._append(source, source.childCount(), 0.)
            item.setText(1, '')
            self._writing = False
            self.editor.changed.emit()

    def _remove_value(self):
        source = self._array_source()
        if source is not None and source.childCount():
            source.takeChild(source.childCount()-1)
            self.editor.changed.emit()

    def _write(self, item, text):
        self._writing = True
        try:
            item.setText(1, text)
        finally:
            self._writing = False

    def open_field(self, path, object_id=''):
        # Resolve with the canonical stable-ID logic, then focus the visible
        # native field rather than the optional schema tree.
        self.refresh()
        self.editor.open_field(path, object_id)
        target = self.editor.tree.currentItem()
        if target is None:
            return False
        parent = target if target.data(0, Qt.ItemDataRole.UserRole) in ('object', 'array') else target.parent()
        found = next((node for node, source in self._nodes.values() if source is parent), None)
        if found is None:
            return False
        self.navigator.setCurrentItem(found)
        control = self._fields.get(target.text(0), self.navigator if self.navigator.isVisible() else self.panel)
        return reveal_and_focus(control)


def replace_structured_form(workspace, key, replacement):
    """Retain canonical tree and optional access without changing field maps."""
    editor = workspace.structured[key]
    for form in workspace.findChildren(QFormLayout):
        if form.indexOf(editor) >= 0:
            form.replaceWidget(editor, replacement)
            editor.hide()
            return True
    return False
