"""Additive study chooser with lazily constructed model-specific workspaces."""
from __future__ import annotations

from copy import deepcopy
import json
import uuid

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLineEdit, QStackedWidget, QTreeWidget,
    QTreeWidgetItem, QStyledItemDelegate, QVBoxLayout, QWidget)

from qt_research_common import ResearchWorkspaceBase, FieldError, button, label, number


class _StructuredDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        kind = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole)
        if index.column() == 2 or (index.column() == 1 and kind in ('object', 'array', 'null')):
            return None
        if index.column() == 0 and (not index.parent().isValid() or index.parent().data(Qt.ItemDataRole.UserRole) == 'array'):
            return None
        return super().createEditor(parent, option, index)


class StructuredValueEditor(QWidget):
    """Typed nested objects/lists; JSON is only an optional interchange format."""
    changed = pyqtSignal()

    def __init__(self, value, field, parent=None):
        super().__init__(parent)
        self.field = field
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(['Property / item', 'Value', 'Type'])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setColumnWidth(0, 300)
        self.tree.setItemDelegate(_StructuredDelegate(self.tree))
        self.tree.setAccessibleName(field+' structured editor')
        self.tree.setMinimumHeight(190)
        self.tree.itemChanged.connect(lambda *args: self.changed.emit())
        layout.addWidget(self.tree)
        row = QHBoxLayout()
        row.addWidget(button('Add property or item', self.add_child))
        row.addWidget(button('Remove selected', self.remove_selected))
        row.addStretch()
        layout.addLayout(row)
        self.set_value(value)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.tree.setColumnWidth(0, max(140, min(300, round(self.tree.viewport().width()*.38))))

    def _append(self, parent, name, value):
        kind = ('object' if isinstance(value, dict) else 'array' if isinstance(value, list) else
                'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (int, float)) else 'null' if value is None else 'text')
        shown = '' if kind in ('object', 'array', 'null') else str(value).lower() if kind == 'boolean' else str(value)
        item = QTreeWidgetItem(parent, [str(name), shown, kind])
        item.setData(0, Qt.ItemDataRole.UserRole, kind)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setToolTip(1, 'Edit the value. Type remains '+kind+'. Remove and add a property to change its type.')
        if isinstance(value, dict):
            for key, child in value.items():
                self._append(item, key, child)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._append(item, index, child)
        return item

    def set_value(self, value):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._append(self.tree, self.field, value)
        self.tree.expandToDepth(1)
        self.tree.blockSignals(False)

    def set_template(self, value):
        """Display unspecified physical numbers as editable blanks, never zero defaults."""
        def seed(item):
            if isinstance(item, dict):
                return {key: seed(child) for key, child in item.items()}
            if isinstance(item, list):
                return [seed(child) for child in item]
            return 0. if item is None else item
        self.set_value(seed(value))
        def clear(item, original):
            if original is None:
                item.setText(1, '')
            elif isinstance(original, dict):
                for index, child in enumerate(original.values()):
                    clear(item.child(index), child)
            elif isinstance(original, list):
                for index, child in enumerate(original):
                    clear(item.child(index), child)
        clear(self.tree.topLevelItem(0), value)

    def _read(self, item, *, raw=False, path=None):
        path = path or self.field
        kind = item.data(0, Qt.ItemDataRole.UserRole)
        if raw:
            return dict(name=item.text(0), value=item.text(1), type=kind,
                children=[self._read(item.child(i), raw=True) for i in range(item.childCount())])
        if kind == 'object':
            result = {}
            for index in range(item.childCount()):
                child = item.child(index); name = child.text(0).strip()
                if not name or name in result:
                    raise FieldError(path, 'Property names must be nonempty and unique.')
                result[name] = self._read(child, path=path+'.'+name)
            return result
        if kind == 'array':
            return [self._read(item.child(i), path=path+'.'+str(i)) for i in range(item.childCount())]
        if kind == 'number':
            return number(item.text(1), path)
        if kind == 'boolean':
            if item.text(1).strip().lower() not in ('true', 'false'):
                raise FieldError(path, 'Boolean values must be true or false.')
            return item.text(1).strip().lower() == 'true'
        return None if kind == 'null' else item.text(1)

    def value(self):
        return self._read(self.tree.topLevelItem(0))

    def draft(self):
        return self._read(self.tree.topLevelItem(0), raw=True)

    def restore_draft(self, draft):
        self.tree.blockSignals(True)
        self.tree.clear()
        def append(parent, raw):
            item = QTreeWidgetItem(parent, [raw['name'], raw['value'], raw['type']])
            item.setData(0, Qt.ItemDataRole.UserRole, raw['type'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            for child in raw.get('children', []):
                append(item, child)
        append(self.tree, draft)
        self.tree.expandToDepth(1)
        self.tree.blockSignals(False)

    def add_child(self):
        parent = self.tree.currentItem() or self.tree.topLevelItem(0)
        if parent.data(0, Qt.ItemDataRole.UserRole) not in ('array', 'object'):
            parent = parent.parent() or parent
        if parent.data(0, Qt.ItemDataRole.UserRole) not in ('array', 'object'):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Add editable property or item')
        layout = QFormLayout(dialog)
        name, kind = QLineEdit(), QComboBox()
        kind.addItems(['number', 'text', 'boolean', 'object', 'array'])
        name.setText(str(parent.childCount()) if parent.data(0, Qt.ItemDataRole.UserRole) == 'array' else '')
        layout.addRow('Property name', name)
        layout.addRow('Value type', kind)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted and name.text().strip():
            self._append(parent, name.text().strip(), {'number': 0., 'text': '', 'boolean': False, 'object': {}, 'array': []}[kind.currentText()])
            parent.setExpanded(True); self.changed.emit()

    def remove_selected(self):
        selected = self.tree.currentItem()
        if selected and selected.parent():
            selected.parent().removeChild(selected); self.changed.emit()

    def append_template(self, value, missing_numbers=()):
        root = self.tree.topLevelItem(0)
        if root.data(0, Qt.ItemDataRole.UserRole) != 'array':
            return
        item = self._append(root, root.childCount(), value)
        for index in range(item.childCount()):
            child = item.child(index)
            if child.text(0) in missing_numbers:
                child.setText(1, '')
        root.setExpanded(True); item.setExpanded(True)
        self.tree.setCurrentItem(item); self.changed.emit()

    def open_field(self, path, object_id=''):
        from qt_input_diagnostics import reveal_and_focus
        item = self.tree.topLevelItem(0)
        parts = path.split('.')[1:]
        if object_id:
            found = next((item.child(i) for i in range(item.childCount()) if item.child(i).text(0) == object_id), None)
            pending = [item]
            while pending and found is None:
                parent = pending.pop()
                if any(parent.child(i).text(0) == 'id' and parent.child(i).text(1) == object_id for i in range(parent.childCount())):
                    found = parent; break
                pending.extend(parent.child(i) for i in range(parent.childCount()))
            if found is None:
                return False
            item = found
            if parts and (parts[0].isdigit() or parts[0] == object_id):
                parts = parts[1:]
        for part in parts:
            if item.data(0, Qt.ItemDataRole.UserRole) == 'array' and part.isdigit() and int(part) < item.childCount():
                item = item.child(int(part))
            else:
                child = next((item.child(i) for i in range(item.childCount()) if item.child(i).text(0) == part), None)
                if child is None:
                    # Missing properties retain a real destination: the owning object.
                    break
                item = child
        parent = item.parent()
        while parent:
            parent.setExpanded(True); parent = parent.parent()
        self.tree.setCurrentItem(item, 1)
        self.tree.scrollToItem(item)
        return reveal_and_focus(self.tree)


class PcselSweepEditor(QWidget):
    """Native explicit-value sweep rows targeting stable objects or scalar inputs."""
    changed = pyqtSignal()
    scalar_paths = ('lattice_nm', 'inclusion_index', 'top_index', 'bottom_index', 'grid_nm', 'pad_nm',
        'harmonics', 'collocation_order', 'beam_grid', 'beam_padding', 'gmax', 'num_modes', 'basis',
        'fill_fraction', 'center_scale')

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        from qt_photonic_bands import _table
        self.workspace = workspace
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label('Optional Cartesian sweep, at most 128 variants. Select a real input or stable layer/inclusion, '
            'add it, then enter explicit comma-separated values. All variants are checked before the first run.'))
        self.table = _table(['Quantity', 'Stable object ID', 'Object field', 'Explicit values'], 'PCSEL geometry and accuracy sweep')
        self.table.cellChanged.connect(lambda *args: self.changed.emit())
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.targets = QComboBox(); self.targets.setAccessibleName('PCSEL sweep target')
        row.addWidget(self.targets, 1)
        row.addWidget(button('Refresh targets', self.refresh_targets))
        row.addWidget(button('Add target', self.add_target))
        row.addWidget(button('Remove selected', self.remove_selected))
        layout.addLayout(row)
        self.refresh_targets()

    def refresh_targets(self):
        self.targets.clear()
        for key in self.scalar_paths:
            title = {'fill_fraction': 'Total inclusion area fraction (scales each shape about its center)',
                     'center_scale': 'Inclusion center-position scale (dimensionless)'}.get(key, key.replace('_', ' '))
            self.targets.addItem(title, dict(path=key))
        for field in ('width', 'height'):
            self.targets.addItem('Aperture '+field+' (µm)', dict(path='aperture_um', field=field))
        for group in ('layers', 'shapes'):
            editor = self.workspace.structured.get(group)
            if editor is None:
                continue
            try:
                objects = editor.value()
            except ValueError:
                continue
            for obj in objects:
                if not isinstance(obj, dict) or not obj.get('id'):
                    continue
                fields = ('thickness_nm', 'index') if group == 'layers' else ('radius', 'center_x', 'center_y') if obj.get('shape') == 'circle' else ()
                for field in fields:
                    title = field.replace('_', ' ')+(' / a' if field in ('radius', 'center_x', 'center_y') else '')
                    self.targets.addItem(str(obj.get('name', obj['id']))+' · '+title,
                        dict(path=group, object_id=obj['id'], field=field))

    def _rows(self):
        from qt_photonic_bands import _rows
        return _rows(self.table)

    def _fill(self, rows):
        from qt_photonic_bands import _fill
        _fill(self.table, rows)
        for row in range(self.table.rowCount()):
            for column in (0, 1, 2):
                self.table.item(row, column).setFlags(self.table.item(row, column).flags() & ~Qt.ItemFlag.ItemIsEditable)

    def add_target(self):
        target = self.targets.currentData()
        if not target:
            return
        rows = self._rows()
        rows.append([target['path'], target.get('object_id', ''), target.get('field', ''), ''])
        self._fill(rows); self.changed.emit()

    def remove_selected(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow()); self.changed.emit()

    def value(self):
        parameters = []
        for index, (path, identity, field, values) in enumerate(self._rows()):
            parts = values.replace(',', ' ').split()
            if not parts:
                raise FieldError('parameter_sweep.'+str(index)+'.values', 'Supply explicit values for this sweep target.')
            row = dict(path=path, values=[number(value, 'parameter_sweep.'+str(index)+'.values') for value in parts])
            if identity:
                row['object_id'] = identity
            if field:
                row['field'] = field
            parameters.append(row)
        return dict(parameters=parameters) if parameters else {}

    def set_value(self, value):
        self._fill([[row['path'], row.get('object_id', ''), row.get('field', ''), ', '.join(map(str, row['values']))]
                    for row in value.get('parameters', [])])
        self.refresh_targets()

    def draft(self):
        return {'rows': self._rows()}

    def restore_draft(self, draft):
        self._fill(draft.get('rows', []))

    def open_field(self, path, object_id=''):
        from qt_input_diagnostics import reveal_and_focus
        parts = path.split('.')
        row = next((i for i, values in enumerate(self._rows()) if object_id and values[1] == object_id), 0)
        if len(parts) > 1 and parts[1].isdigit():
            row = int(parts[1])
        if row < self.table.rowCount():
            self.table.setCurrentCell(row, 3)
        return reveal_and_focus(self.table)


class StructuredStudyWorkspace(ResearchWorkspaceBase):
    """Schema-driven typed controls for newly registered editable research models."""
    def __init__(self, store, capability, parent=None):
        self.engine, self.study = capability['engine'], capability['study']
        self.workspace_id = 'advanced_transport' if self.engine == 'advanced_transport' else 'research_studies'
        self.state_key = 'model_'+self.engine+'_'+self.study
        super().__init__(store, parent)
        self.heading.setText(capability['label'])
        self.description.setText(' '.join(capability.get('limitations', [])))
        self.structured = {}
        self.schema = []
        from research_catalog import field_schema
        self.schema = field_schema(self.engine, self.study)
        forms = {}
        for spec in self.schema:
            section = spec.get('section', 'Inputs')
            if section not in forms:
                title = {'physics': 'Aperture physics', 'sweep': 'Parameter sweep'}.get(section, section.replace('_', ' ').title())
                _, layout = self.add_section(title, section)
                forms[section] = (layout, QFormLayout())
                layout.addLayout(forms[section][1])
            layout, form = forms[section]
            key, title, kind = spec['path'], spec.get('label', spec['path']), spec.get('type', 'text')
            value = spec.get('default')
            if kind == 'choice':
                self.choice(form, title, key, spec.get('options', []), value)
            elif kind in ('number', 'integer', 'text', 'string'):
                self.line(form, title, key, '' if value is None else value, spec.get('unit', ''))
                if key == 'beam_saved_run':
                    form.addRow(button('Browse saved finite-mode run…', self.browse_beam_run))
            elif kind in ('boolean', 'bool'):
                self.choice(form, title, key, [('No', False), ('Yes', True)], bool(value))
            else:
                if value is None:
                    value = {} if kind == 'object' else []
                editor = PcselSweepEditor(self) if self.engine == 'pcsel' and key == 'parameter_sweep' else StructuredValueEditor(value, key)
                self.structured[key] = editor
                self.fields[key] = editor
                editor.changed.connect(self._edited)
                form.addRow(title+(' ('+spec['unit']+')' if spec.get('unit') else ''), editor)
                if self.engine in ('advanced_transport', 'pcsel_unitcell_transport') and key in (
                    'nonlocal_tunnelling', 'high_field_optics', 'temperature_feedback', 'recombination',
                    'bandgap_narrowing', 'thermal', 'contacts', 'interfaces', 'unipolar_conductors'):
                    form.addRow(button('Create missing input fields', lambda checked=False, name=key: self.create_model_fields(name)))
            if spec.get('description'):
                form.addRow(label(spec['description']))
        _, interchange = self.add_section('Review & files')
        interchange.addWidget(label('Nested properties are edited in typed lists above. Exported settings retain the exact physical values and units.'))
        row = QHBoxLayout()
        row.addWidget(button('Import editable settings…', self.import_settings))
        row.addWidget(button('Export settings…', self.export_settings))
        interchange.addLayout(row); interchange.addStretch()
        from qt_research_results import ResearchResultsPanel
        self.results = ResearchResultsPanel(store, self.engine, self)
        self.tabs.addTab(self.results, 'Results')
        if self.engine == 'pcsel':
            self._add_pcsel_controls()
        elif self.engine in ('advanced_transport', 'pcsel_unitcell_transport'):
            self._add_device_model_controls()
        elif self.engine == 'pcsel_transport':
            self._add_conformal_controls()
        self.finish_build()

    def browse_beam_run(self):
        directory = QFileDialog.getExistingDirectory(self, 'Choose a saved finite-mode run',
            self.fields['beam_saved_run'].text())
        if directory:
            self.fields['beam_saved_run'].setText(directory)

    def create_model_fields(self, key):
        from advanced_transport import input_template
        editor = self.structured[key]
        if not self.store.project().get('device'):
            self.status.setText('Create the shared finite device first so fields use its actual material and contact IDs.'); return
        try:
            current = editor.value()
            template = input_template(key, self.store.project())
        except ValueError as exc:
            self.status.setText('Existing entries were preserved. Finish their values before adding fields: '+str(exc)); return
        def merge(existing, proposed):
            if isinstance(existing, dict) and isinstance(proposed, dict):
                return {name: merge(existing[name], value) if name in existing else value for name, value in proposed.items()} | {
                    name: value for name, value in existing.items() if name not in proposed}
            return proposed if existing in ([], {}) else existing
        editor.set_template(merge(current, template))
        editor.tree.expandToDepth(2)
        self._edited()

    def _add_conformal_controls(self):
        _, layout = self.add_section('Editable starting structures')
        layout.addWidget(label('Homogeneous analytic example · illustrative material values for checking current against '
            'q μ n A/L. This is not a paper reproduction or a measured PCSEL device. Loading it replaces only this study draft.'))
        layout.addWidget(button('Load editable homogeneous example', self.load_conformal_example))
        row = QHBoxLayout()
        row.addWidget(button('Add editable layer', lambda: self.structured['layers'].append_template(
            dict(id='layer-'+uuid.uuid4().hex[:8], thickness_um=0., material='', donors_cm3=0., acceptors_cm3=0., patterned=False),
            ('thickness_um', 'donors_cm3', 'acceptors_cm3'))))
        row.addWidget(button('Add circular air inclusion', lambda: self.structured['inclusions'].append_template(
            dict(id='hole-'+uuid.uuid4().hex[:8], shape='circle', center_um=[0., 0.], radius_um=0.), ('radius_um',))))
        layout.addLayout(row)
        layout.addWidget(label('The independent periodic cell has full-face top and bottom contacts. '
            'Configure the Python runtime containing Gmsh, NumPy and SciPy, then refine the mesh and bias steps for the edited device.'))
        layout.addStretch()

    def load_conformal_example(self):
        from pcsel_transport_study import example_settings
        self.load_settings(example_settings())
        self.select_section('Geometry')

    def _add_pcsel_controls(self):
        _, layout = self.add_section('Editable starting structures')
        layout.addWidget(label('Recovered PCSEL example · an explicit starting structure, not a validated result. '
            'Loading an example replaces this study draft only. All dimensions, layers and inclusions remain editable.'))
        form = QFormLayout()
        self.example_kind = QComboBox(); self.example_kind.addItems(['hole', 'pillar'])
        self.example_shape = QComboBox(); self.example_shape.addItems(['CC', 'RIT'])
        self.example_fill = QLineEdit('0.16')
        form.addRow('Recovered stack', self.example_kind); form.addRow('Recovered shape family', self.example_shape)
        form.addRow('Inclusion area fraction', self.example_fill); layout.addLayout(form)
        layout.addWidget(button('Load recovered PCSEL example', self.load_pcsel_example))
        row = QHBoxLayout()
        row.addWidget(button('Add editable layer', lambda: self.structured['layers'].append_template(
            dict(id='layer-'+uuid.uuid4().hex[:8], name='New layer', thickness_nm=0., index=0., qw=False, patterned=False), ('thickness_nm', 'index'))))
        row.addWidget(button('Add circle inclusion', lambda: self.structured['shapes'].append_template(
            dict(id='circle-'+uuid.uuid4().hex[:8], shape='circle', center=[0., 0.], radius=0.), ('radius',))))
        row.addWidget(button('Add polygon inclusion', lambda: self.structured['shapes'].append_template(
            dict(id='polygon-'+uuid.uuid4().hex[:8], shape='polygon', vertices=[]))))
        layout.addLayout(row)
        layout.addWidget(button('Create explicit aperture input fields', self.create_aperture_fields))
        layout.addWidget(label('Aperture calculations require a source-bound calibration for this exact stack and pattern. '
            'The load-domain record is imported with the calibration; this editor never marks invented anchors as accepted. '
            'Use the physics section to supply the material, gain, recombination, thermal and contact inputs.'))
        layout.addStretch()

    def _add_device_model_controls(self):
        _, layout = self.add_section('Device assignments')
        device = getattr(self.store, 'device', None) or {}
        layout.addWidget(label('This model uses the current finite device and its mesh. '
            'Material/contact identifiers below are stable assignments from that device; editing this list does not change the geometry.'))
        layout.addWidget(button('Edit shared device and contacts', lambda: self.diagnosticRequested.emit(dict(
            workspace='structure', section='device', field='device', message='Edit the device used for this transport study.'))))
        descriptions = ['Contacts: '+', '.join(row.get('name', row['id'])+' ['+row['id']+']' for row in device.get('contacts', []) if row.get('enabled', True))]
        descriptions.append('Materials: '+', '.join(row.get('name', row['id'])+' ['+row['id']+']' for row in getattr(self.store, 'electrical_materials', [])))
        layout.addWidget(label('\n'.join(descriptions)))
        self.device_contact_picker = QComboBox()
        self.device_contact_picker.setAccessibleName('Device contact for carrier-resistance inputs')
        self.device_contact_picker.addItem('Choose a contact…', '')
        for row in device.get('contacts', []):
            if row.get('enabled', True):
                self.device_contact_picker.addItem(row.get('name', row['id']), row['id'])
        layout.addWidget(self.device_contact_picker)
        layout.addWidget(button('Use as swept contact', lambda: self.fields['swept_contact_id'].setText(self.device_contact_picker.currentData() or '')))
        layout.addWidget(button('Add explicit contact-resistance fields', self.add_contact_fields))
        layout.addWidget(label('Empty optional sections are off. Adding contact-resistance fields requires explicit values and a source; '
            'zero is the ideal-interface limit. Semiconductor recombination, conductor selection and electrochemical heating '
            'use the explicitly supplied properties in their respective sections.'))
        layout.addStretch()

    def add_contact_fields(self):
        identity = self.device_contact_picker.currentData()
        if not identity:
            self.status.setText('Choose an enabled device contact first.'); return
        editor = self.structured['contacts']
        try:
            values = editor.value()
        except ValueError:
            self.status.setText('Finish or remove the current incomplete resistance entry before adding another.'); return
        if identity in values:
            editor.open_field('contacts.'+identity); return
        values[identity] = dict(electron_resistivity_ohm_cm2=0., hole_resistivity_ohm_cm2=0., source='')
        editor.set_value(values)
        root = editor.tree.topLevelItem(0)
        item = next(root.child(i) for i in range(root.childCount()) if root.child(i).text(0) == identity)
        for i in range(item.childCount()):
            if item.child(i).data(0, Qt.ItemDataRole.UserRole) == 'number':
                item.child(i).setText(1, '')
        self.select_section('Contacts'); editor.open_field('contacts.'+identity); self._edited()

    def load_pcsel_example(self):
        try:
            from pcsel_research import paper_example
            fill = number(self.example_fill.text(), 'example_fill', positive=True)
            self.load_settings(paper_example(self.example_kind.currentText(), self.example_shape.currentText(), fill))
            self.select_section('geometry')
        except ValueError as exc:
            self.status.setText(str(exc))

    def create_aperture_fields(self):
        editor = self.structured['aperture']
        # Blank numeric fields are deliberate: do not invent sourced material inputs.
        required = ('sheet_ohm_square sheet_temperature_exponent reference_temperature_K sink_K substrate_um substrate_k_W_mK '
            'thermal_k_exponent interface_R_m2K_W epitaxial_R_m2K_W well_total_nm capture_ps escape_ps barrier_lifetime_ps '
            'escape_activation_eV A_s1 B_cm3_s C_cm6_s g0_cm1 Ntr_cm3 gain_temperature_K group_index Gamma_QW alpha_rad_cm1 '
            'alpha_edge_cm1 alpha_internal_cm1 port_fraction port_transmission wavelength_nm load_reference_V max_temperature_K').split()
        try:
            current = editor.value()
        except ValueError:
            self.status.setText('Resolve the current aperture draft before adding a missing-field template.'); return
        template = dict(current)
        added = []
        for key in required:
            if key not in template:
                template[key] = 0.; added.append(key)
        for key, value in dict(grid_n=20, maximum_iterations=120, temperature_tolerance_K=.002, heated=True,
            currents_A=[], voltage_bracket_V=[], load_anchors=[], load_source='', load_domain={}, contacts=[], mode_weight=[]).items():
            template.setdefault(key, value)
        editor.set_value(template)
        root = editor.tree.topLevelItem(0)
        for index in range(root.childCount()):
            item = root.child(index)
            if item.text(0) in added:
                item.setText(1, '')
        self.select_section('physics'); self._edited()

    def draft(self):
        state = super().draft()
        state['structured'] = {key: edit.draft() for key, edit in self.structured.items()}
        return state

    def restore_draft(self, state):
        super().restore_draft(state)
        for key, value in state.get('structured', {}).items():
            if key in self.structured:
                self.structured[key].restore_draft(value)

    def options(self):
        settings = {}
        for spec in self.schema:
            key, kind = spec['path'], spec.get('type', 'text')
            editor = self.fields[key]
            if key in self.structured:
                value = editor.value()
                if value in ({}, []) and not spec.get('required') and 'default' not in spec:
                    continue
            elif isinstance(editor, QComboBox):
                value = editor.currentData()
            elif kind in ('number', 'integer'):
                if not editor.text().strip() and not spec.get('required'):
                    continue
                value = number(editor.text(), key, integer=kind == 'integer', units=spec.get('unit', ''))
            else:
                value = editor.text()
            target = settings
            parts = key.split('.')
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
        return dict(engine=self.engine, study=self.study, settings=settings)

    def load_settings(self, settings):
        self._loading = True
        try:
            self.restore_draft(self._default_draft)
            for key, editor in self.fields.items():
                value = settings
                for part in key.split('.'):
                    value = value.get(part) if isinstance(value, dict) else None
                if value is None:
                    continue
                if key in self.structured:
                    editor.set_value(value)
                elif isinstance(editor, QComboBox):
                    editor.setCurrentIndex(editor.findData(value))
                else:
                    editor.setText(str(value))
        finally:
            self._loading = False
        self.save_draft()

    def open_diagnostic(self, target):
        field = target.get('field', '').removeprefix('settings.')
        if field == 'device':
            self.diagnosticRequested.emit(dict(target, workspace='structure'))
            return False
        root = field.split('.')[0]
        if root in self.structured:
            result = self.structured[root].open_field(field, target.get('object_id', ''))
            if not result:
                self.status.setText('This object was removed or changed. Recheck the current study draft.')
            return result
        return super().open_diagnostic(target)

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import editable study settings', '', 'JSON (*.json)')
        if path:
            try:
                with open(path, encoding='utf-8') as stream:
                    value = json.load(stream)
                self.load_settings(value.get('settings', value))
                self.validate_inputs()
            except (ValueError, OSError) as exc:
                self.status.setText('Import failed: '+str(exc))

    def export_settings(self):
        try:
            value = self.options()
        except ValueError as exc:
            self.diagnostics.set_diagnostics([self._issue(exc)])
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export editable study settings', self.engine+'.json', 'JSON (*.json)')
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as stream:
                    json.dump(value, stream, indent=2, allow_nan=False)
            except OSError as exc:
                self.status.setText('Export failed: '+str(exc))


class ResearchStudiesWorkspace(QWidget):
    diagnosticRequested = pyqtSignal(dict)
    projectReplacementRequested = pyqtSignal(dict)
    independentBenchmarkRequested = pyqtSignal(str, bool)
    selectionChanged = pyqtSignal()
    simulationRequested = pyqtSignal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._pages = {}
        self._capabilities = {}
        self._reference_running = False
        self._embedded = False
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(button('All studies', lambda: self.select_section('Overview')))
        self.selector = QComboBox()
        self.selector.setAccessibleName('Additional simulation study')
        row.addWidget(self.selector, 1)
        row.addWidget(button('Paper library', self.show_paper_library))
        layout.addLayout(row)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.overview_text = label('')
        self.overview_text.hide()
        self.benchmarks = QComboBox()
        self.benchmarks.setAccessibleName('Installed paper comparison benchmark')
        self.benchmark_note = label('')
        from qt_study_library import StudyLibrary
        self.library_page = StudyLibrary(self.benchmarks, self.duplicate_benchmark, self.run_benchmark, self.benchmark_note, self)
        self.library_page.engineRequested.connect(self.select_engine)
        self.library_page.simulationRequested.connect(self.simulationRequested)
        self.library_page.routeRequested.connect(self.diagnosticRequested)
        self.stack.addWidget(self.library_page)
        self.selector.currentIndexChanged.connect(self._selected)
        self.store.run_finished.connect(self._reference_finished)
        self.store.run_failed.connect(self._reference_failed)
        self.store.changed.connect(self._store_changed)
        self.refresh_capabilities()
        self.refresh_benchmarks()
        chosen = self.store.search_state.get('research_workspaces', {}).get('studies', {}).get('selected_engine', '')
        if chosen:
            self.select_engine(chosen)

    def refresh_capabilities(self):
        from research_catalog import list_capabilities
        from qt_study_library import STUDIES
        names={row[0]:row[1] for row in STUDIES}
        previous = self.selector.currentData()
        self.selector.blockSignals(True)
        self.selector.clear(); self.selector.addItem('Overview', '')
        self._capabilities = {row['engine']: row for row in list_capabilities() if row['engine'] != 'photonic_bands'}
        for engine, row in self._capabilities.items():
            self.selector.addItem(names.get(engine,row['label']), engine)
        self.selector.addItem('Lumped laser model', 'lumped_laser')
        if 'reference_result' in self._pages:
            self.selector.addItem('Saved reference result', 'reference_result')
        self.selector.setCurrentIndex(max(0, self.selector.findData(previous)))
        self.selector.blockSignals(False)
        self.overview_text.setText('\n\n'.join(row['label']+': '+' '.join(row.get('limitations', []))+
            (' Optional runtime must be configured.' if row.get('optional_runtime') else '') for row in self._capabilities.values()))

    def _selected(self, *args):
        engine = self.selector.currentData()
        namespace = deepcopy(self.store.search_state.get('research_workspaces', {}))
        namespace.setdefault('schema_version', 1)
        namespace.setdefault('studies', {})['selected_engine'] = engine or ''
        self.store.save_search('research_workspaces', namespace)
        if not engine:
            self.stack.setCurrentIndex(0); self.selectionChanged.emit(); return
        if engine not in self._pages:
            if engine == 'thermal':
                from qt_thermal_setup import ThermalSetupWorkspace
                page = ThermalSetupWorkspace(self.store, self)
            elif engine == 'sesame_transport':
                from qt_sesame_setup import SesameSetupWorkspace
                page = SesameSetupWorkspace(self.store, self)
            elif engine == 'lumped_laser':
                from qt_pcsel import PCSELPage
                page = PCSELPage(self.store)
            elif engine in ('pcsel', 'pcsel_transport'):
                from qt_pcsel_research_setup import PcselResearchWorkspace
                page = PcselResearchWorkspace(self.store, self._capabilities[engine], self)
            elif engine in ('advanced_transport', 'pcsel_unitcell_transport', 'high_field_optics'):
                from qt_transport_research_setup import TransportResearchWorkspace, HighFieldOpticsWorkspace
                cls = HighFieldOpticsWorkspace if engine == 'high_field_optics' else TransportResearchWorkspace
                page = cls(self.store, self._capabilities[engine], self)
            else:
                page = StructuredStudyWorkspace(self.store, self._capabilities[engine], self)
            if hasattr(page, 'diagnosticRequested'):
                page.diagnosticRequested.connect(self.diagnosticRequested)
            if hasattr(page, 'set_embedded'):
                page.set_embedded(self._embedded)
            self._pages[engine] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(self._pages[engine])
        if hasattr(self._pages[engine], 'refresh'):
            self._pages[engine].refresh()
        self.adapt_layout()
        self.selectionChanged.emit()

    def show_paper_library(self):
        self.select_section('Overview')
        self.library_page.tabs.setCurrentIndex(1)

    def adapt_layout(self):
        self.layout().setContentsMargins(12, 8, 12, 8)
        current = self.stack.currentWidget()
        if hasattr(current, 'adapt_layout'):
            current.adapt_layout()
        elif hasattr(current, 'study_flow'):
            current.study_flow.adapt_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adapt_layout()

    def select_engine(self, engine):
        index = self.selector.findData(engine)
        if index < 0:
            self.refresh_capabilities(); index = self.selector.findData(engine)
        if index < 0:
            return False
        self.selector.setCurrentIndex(index)
        self._selected()
        return True

    def select_section(self, section):
        if section.lower() in ('overview', 'research.overview'):
            self.selector.setCurrentIndex(0); return True
        page = self.stack.currentWidget()
        return bool(hasattr(page, 'select_section') and page.select_section(section))

    def refresh(self):
        selected = self.store.search_state.get('research_workspaces', {}).get('studies', {}).get('selected_engine', '')
        if selected != self.selector.currentData():
            index = self.selector.findData(selected)
            self.selector.setCurrentIndex(max(0, index))
        for page in self._pages.values():
            if hasattr(page, 'refresh'):
                page.refresh()

    def _store_changed(self, reason=''):
        if reason in ('project', 'load', 'reset', 'all'):
            self.refresh()

    def flush_draft(self):
        for page in self._pages.values():
            if hasattr(page, 'flush_draft'):
                page.flush_draft()

    def set_embedded(self, embedded=True):
        self._embedded = bool(embedded)
        for page in self._pages.values():
            if hasattr(page, 'set_embedded'):
                page.set_embedded(self._embedded)

    def run(self):
        page = self.stack.currentWidget()
        if hasattr(page, 'run'):
            page.run()
        elif hasattr(page, 'run_simulation'):
            page.run_simulation()

    def validate_setup(self):
        page = self.stack.currentWidget()
        return bool(hasattr(page, 'validate_setup') and page.validate_setup())

    def return_to_issues(self):
        page = self.stack.currentWidget()
        if hasattr(page, 'return_to_issues'):
            page.return_to_issues()

    def open_diagnostic(self, target):
        workspace = target.get('workspace', '')
        engine = workspace if workspace in self._capabilities else target.get('model_id')
        if engine and engine in self._capabilities:
            self.select_engine(engine)
        if workspace not in ('', 'research_studies', 'thermal') and workspace not in self._capabilities:
            self.diagnosticRequested.emit(target); return False
        page = self.stack.currentWidget()
        if engine in self._capabilities and hasattr(page, 'workspace_id'):
            target = dict(target, workspace=page.workspace_id, model_id=engine)
        return bool(hasattr(page, 'open_diagnostic') and page.open_diagnostic(target))

    def refresh_benchmarks(self):
        self.benchmarks.clear()
        try:
            from benchmark_registry import list_benchmarks
            self.library_page.set_cases(list_benchmarks())
        except (ImportError, OSError, ValueError) as exc:
            self.benchmark_note.setText('Benchmark registry unavailable: '+str(exc))

    def duplicate_benchmark(self):
        identity = self.benchmarks.currentData()
        if not identity:
            return
        try:
            from benchmark_registry import editable_copy
            case = editable_copy(identity)
            if case['kind'] == 'research_simulation':
                engine = case['options']['engine']
                if engine == 'photonic_bands':
                    self.independentBenchmarkRequested.emit(identity, False)
                elif self.select_engine(engine):
                    page = self._pages[engine]
                    settings = deepcopy(case['options']['settings'])
                    if hasattr(page, 'runtime_settings'):
                        try:
                            runtime = page.runtime_settings()
                            if runtime and 'runtime' not in settings:
                                settings['runtime'] = runtime
                        except ValueError:
                            pass
                    page.load_settings(settings)
                    page.attach_benchmark(case)
                    if hasattr(page, 'study_flow'):
                        page.study_flow.show_stage(0)
            else:
                self.benchmark_note.setText('Opening this reference through the project replacement flow so current edits can be saved first.')
                self.projectReplacementRequested.emit(case)
        except (ValueError, KeyError, OSError) as exc:
            self.benchmark_note.setText('Could not copy reference: '+str(exc))

    def run_benchmark(self):
        identity = self.benchmarks.currentData()
        if identity and not self.store.busy:
            try:
                self._reference_running = True
                from benchmark_registry import load_benchmark
                case = load_benchmark(identity)
                engine = case.get('options', {}).get('engine')
                if engine == 'photonic_bands':
                    self._reference_running = False
                    self.independentBenchmarkRequested.emit(identity, True)
                    return
                if engine and engine not in self._pages:
                    self.select_engine(engine)
                page = self._pages.get(engine)
                runtime = page.runtime_settings() if page is not None and hasattr(page, 'runtime_settings') else None
                self.store.start_benchmark(identity, runtime=runtime)
                self.benchmark_note.setText('Reference run started through the normal job pipeline. Its manifest retains comparison and convergence status.')
            except Exception as exc:
                self._reference_running = False
                self.benchmark_note.setText('Could not start reference: '+str(exc))

    def _reference_finished(self, event):
        if not self._reference_running:
            return
        self._reference_running = False
        if not event.get('directory'):
            return
        from qt_research_results import ResearchResultsPanel
        engine = 'reference_result'
        if engine not in self._pages:
            self._pages[engine] = ResearchResultsPanel(self.store, parent=self)
            self.stack.addWidget(self._pages[engine])
        if self.selector.findData(engine) < 0:
            self.selector.addItem('Saved reference result', engine)
        self._pages[engine].load_directory(event['directory'])
        self.selector.setCurrentIndex(self.selector.findData(engine))

    def _reference_failed(self, message):
        if self._reference_running:
            self._reference_running = False
            self.benchmark_note.setText('Reference run failed: '+str(message))
