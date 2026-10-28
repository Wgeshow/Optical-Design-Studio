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
    'voltage_V': 'Voltage (V)', 'current_density_A_cm2': 'Current density (A/cm²)',
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
    def __init__(self, editor, parent=None, *, array_types=None, root_array_type=None, nullable_numbers=()):
        super().__init__(parent)
        self.editor = editor
        self._array_types = dict(array_types or {})
        self._root_array_type = root_array_type
        self._nullable_numbers = set(nullable_numbers)
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
            node = QTreeWidgetItem(parent, [self._node_title(source)])
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

    @staticmethod
    def _node_title(source):
        identifier = next((source.child(i).text(1) for i in range(source.childCount())
                           if source.child(i).text(0) in ('name', 'id')), '')
        return identifier or field_label(source.text(0))

    def _refresh_identity_label(self, path):
        # Rename in place after editing finishes. Rebuilding the form for each
        # keystroke would discard the active control, cursor and selection.
        pair = self._nodes.get(path)
        if pair is None:
            return
        node, source = pair
        title = self._node_title(source)
        node.setText(0, title)
        if self.navigator.currentItem() is node:
            self.title.setText(title)

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
                optional_number = item.text(0) in self._nullable_numbers
                control.setPlaceholderText('Not assigned; enter a number' if optional_number else 'Required value' if kind == 'number' else '')
                if kind == 'null' and not optional_number:
                    # A null has no inferred scalar type. Do not present a text
                    # editor whose apparent changes the typed model ignores.
                    control.setEnabled(False)
                    control.setPlaceholderText('Unassigned; choose a type in Advanced properties')
                control.textEdited.connect(lambda text, target=item: self._write(target, text))
                if item.text(0) in ('name', 'id'):
                    # Capture the path instead of a tree item that a later
                    # external refresh may destroy.
                    control.editingFinished.connect(lambda target=path: self._refresh_identity_label(target))
            control.setAccessibleName(field_label(item.text(0)))
            control.setToolTip(field_label(item.text(0)))
            self.form.addRow(field_label(item.text(0)), control)
            self._fields[item.text(0)] = control
        self.note.setText('Choose a group on the left to edit its values.' if not self._fields and source.childCount()
                          else 'No values assigned yet. Add the input fields for this model to begin.' if not source.childCount()
                          else '')
        scalar_array = self._array_element_kind(source) in ('number', 'text', 'boolean')
        self.add_value.setVisible(scalar_array)
        self.remove_value.setVisible(scalar_array and source.childCount() > 0)

    def _array_element_kind(self, source):
        if source.data(0, Qt.ItemDataRole.UserRole) != 'array':
            return None
        if source is self.editor.tree.topLevelItem(0) and self._root_array_type:
            return self._root_array_type
        if source.text(0) in self._array_types:
            return self._array_types[source.text(0)]
        kinds = {source.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(source.childCount())}
        # Existing scalar lists retain their actual type. Empty lists need the
        # owning study's hint when they contain IDs or structured objects.
        return next(iter(kinds)) if len(kinds) == 1 else 'number' if not kinds else None

    def _array_source(self):
        node = self.navigator.currentItem()
        return self._nodes[node.data(0, Qt.ItemDataRole.UserRole)][1] if node else None

    def _add_value(self):
        source = self._array_source()
        kind = self._array_element_kind(source) if source is not None else None
        if kind not in ('number', 'text', 'boolean'):
            return
        self._writing = True
        blocked = self.editor.tree.blockSignals(True)
        try:
            item = self.editor._append(source, source.childCount(),
                                       {'number': 0., 'text': '', 'boolean': False}[kind])
            if kind != 'boolean':
                item.setText(1, '')
        finally:
            self.editor.tree.blockSignals(blocked)
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
            if item.text(0) in self._nullable_numbers:
                blocked = self.editor.tree.blockSignals(True)
                try:
                    kind = 'number' if text.strip() else 'null'
                    item.setData(0, Qt.ItemDataRole.UserRole, kind)
                    item.setText(2, kind)
                    item.setText(1, text)
                finally:
                    self.editor.tree.blockSignals(blocked)
                self.editor.changed.emit()
            else:
                item.setText(1, text)
        finally:
            self._writing = False

    def open_field(self, path, object_id=''):
        # Resolve with the canonical stable-ID logic, then focus the visible
        # native field rather than the optional schema tree.
        self.refresh()
        # A missing stable ID must not reuse a previous object's selection.
        # The underlying editor can return false merely because its raw tree
        # is hidden, so resolve success through the newly selected item.
        self.editor.tree.setCurrentItem(None)
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


class FlatPropertyForm(QWidget):
    """Accessible nested editing without a visible expandable tree.

    The existing typed tree remains the sole draft model. This scoped view
    avoids the Windows Qt tree-collapse hang; it does not disable accessibility.
    """
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._path = ()
        self._writing = False
        self._fields = {}
        self._paths = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        navigation = QHBoxLayout()
        self.up = QPushButton('Up one group')
        self.up.clicked.connect(lambda: self.select_path(self._path[:-1]))
        navigation.addWidget(self.up)
        self.groups = QComboBox()
        self.groups.setAccessibleName('Aperture property group')
        self.groups.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.groups.setMinimumContentsLength(20)
        self.groups.setMinimumWidth(0)
        self.groups.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.groups.currentIndexChanged.connect(self._group_changed)
        navigation.addWidget(self.groups, 1)
        layout.addLayout(navigation)
        self.title = QLabel()
        self.title.setObjectName('setupHeading')
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)
        self.note = QLabel('Choose a group to edit its values. Changes update this study only; numbers retain their exact typed text.')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        actions = QHBoxLayout()
        self.add = QPushButton('Add property or item')
        self.add.clicked.connect(self.add_child)
        actions.addWidget(self.add)
        self.remove = QPushButton('Remove this group')
        self.remove.clicked.connect(lambda: self.remove_path(self._path))
        actions.addWidget(self.remove)
        actions.addStretch()
        layout.addLayout(actions)
        editor.changed.connect(self.refresh)
        self.refresh()

    def _resolve(self, path):
        item = self.editor.tree.topLevelItem(0)
        for index in path:
            if item is None or index >= item.childCount():
                return None
            item = item.child(index)
        return item

    def _item_path(self, item):
        path = []
        while item.parent() is not None:
            parent = item.parent()
            path.append(parent.indexOfChild(item))
            item = parent
        return tuple(reversed(path))

    def refresh(self):
        if self._writing:
            return
        self._paths = {}
        def visit(item, path, names):
            if item.data(0, Qt.ItemDataRole.UserRole) not in ('object', 'array'):
                return
            title = field_label(item.text(0))
            identifier = next((item.child(i).text(1) for i in range(item.childCount())
                               if item.child(i).text(0) in ('id', 'name')), '')
            if identifier:
                title += ' (' + identifier + ')'
            names = names + [title]
            self._paths[path] = ' / '.join(names)
            for index in range(item.childCount()):
                visit(item.child(index), path + (index,), names)
        visit(self.editor.tree.topLevelItem(0), (), [])
        while self._path not in self._paths and self._path:
            self._path = self._path[:-1]
        self.groups.blockSignals(True)
        self.groups.clear()
        for path, title in self._paths.items():
            self.groups.addItem(title, path)
            self.groups.setItemData(self.groups.count()-1, title, Qt.ItemDataRole.ToolTipRole)
        self.groups.setCurrentIndex(next((i for i in range(self.groups.count()) if self.groups.itemData(i) == self._path), -1))
        self.groups.blockSignals(False)
        self._render()

    def _group_changed(self, *_):
        path = self.groups.currentData()
        if path is not None:
            self._path = tuple(path)
            self._render()

    def select_path(self, path):
        path = tuple(path)
        index = next((i for i in range(self.groups.count()) if self.groups.itemData(i) == path), -1)
        if index >= 0:
            self._path = path
            if index == self.groups.currentIndex():
                self._render()
            else:
                self.groups.setCurrentIndex(index)
            return True
        return False

    def _render(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self._fields = {}
        node = self._resolve(self._path)
        if node is None:
            return
        self.title.setText(self._paths.get(self._path, 'Aperture properties'))
        self.groups.setToolTip(self.title.text())
        self.up.setEnabled(bool(self._path))
        self.remove.setEnabled(bool(self._path))
        self.editor.tree.setCurrentItem(node)
        for index in range(node.childCount()):
            item = node.child(index)
            path = self._path + (index,)
            kind = item.data(0, Qt.ItemDataRole.UserRole)
            host = QWidget()
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            title = field_label(item.text(0))
            if kind in ('object', 'array'):
                control = QPushButton('Open group (' + str(item.childCount()) + ' items)')
                control.clicked.connect(lambda checked=False, target=path: self.select_path(target))
            elif kind == 'boolean':
                control = QComboBox()
                control.setEditable(True)
                control.addItems(['false', 'true'])
                control.setCurrentText(item.text(1))
                control.currentTextChanged.connect(lambda value, target=path: self._write(target, value))
            else:
                control = QLineEdit(item.text(1))
                control.setEnabled(kind != 'null')
                control.setPlaceholderText('Not assigned' if kind == 'null' else 'Required value' if kind == 'number' else '')
                control.textEdited.connect(lambda value, target=path: self._write(target, value))
            control.setAccessibleName(title)
            control.setToolTip(item.text(0) + ' · ' + kind)
            row.addWidget(control, 1)
            self._fields[item.text(0)] = control
            row.addWidget(QLabel(kind))
            if node.data(0, Qt.ItemDataRole.UserRole) == 'object':
                rename = QPushButton('Rename')
                rename.setAccessibleName('Rename ' + title)
                rename.clicked.connect(lambda checked=False, target=path: self.rename_path(target))
                row.addWidget(rename)
            remove = QPushButton('Remove')
            remove.setAccessibleName('Remove ' + title)
            remove.clicked.connect(lambda checked=False, target=path: self.remove_path(target))
            row.addWidget(remove)
            self.form.addRow(title, host)

    def _write(self, path, value):
        item = self._resolve(path)
        if item is None:
            return
        self._writing = True
        try:
            item.setText(1, value)
        finally:
            self._writing = False

    def add_child(self):
        node = self._resolve(self._path)
        if node is not None:
            self.editor.tree.setCurrentItem(node)
            if not self.editor.add_child() and getattr(self.editor, '_property_add_error', ''):
                self.note.setText(self.editor._property_add_error)

    def remove_path(self, path):
        item = self._resolve(path)
        if item is None or item.parent() is None:
            return
        parent = item.parent()
        blocked = self.editor.tree.blockSignals(True)
        try:
            parent.takeChild(parent.indexOfChild(item))
            if parent.data(0, Qt.ItemDataRole.UserRole) == 'array':
                for index in range(parent.childCount()):
                    parent.child(index).setText(0, str(index))
        finally:
            self.editor.tree.blockSignals(blocked)
        if tuple(path) == self._path:
            self._path = self._path[:-1]
        self.editor.changed.emit()

    def rename_path(self, path, name=None):
        from PyQt6.QtWidgets import QInputDialog
        item = self._resolve(path)
        if item is None or item.parent() is None or item.parent().data(0, Qt.ItemDataRole.UserRole) != 'object':
            return False
        if name is None:
            name, accepted = QInputDialog.getText(self, 'Rename property', 'Property name', text=item.text(0))
            if not accepted:
                return False
        name = str(name).strip()
        parent = item.parent()
        if not name or any(parent.child(i) is not item and parent.child(i).text(0).strip() == name for i in range(parent.childCount())):
            self.note.setText('Property names must be nonempty and unique within this group.')
            return False
        item.setText(0, name)
        return True

    def open_item(self, item):
        container = item if item.data(0, Qt.ItemDataRole.UserRole) in ('object', 'array') else item.parent()
        if container is None:
            return False
        self.refresh()
        self.select_path(self._item_path(container))
        target = self._fields.get(item.text(0), self.groups) if item is not container else self.groups
        return reveal_and_focus(target)


def replace_structured_form(workspace, key, replacement):
    """Retain canonical tree and optional access without changing field maps."""
    editor = workspace.structured[key]
    for form in workspace.findChildren(QFormLayout):
        if form.indexOf(editor) >= 0:
            form.replaceWidget(editor, replacement)
            editor.hide()
            return True
    return False
