"""Native shared simulation workspace with a scene-centered guided setup.

The packaged plan declares presentation; SimulationSetupState owns every value.
Optical and electrical editors embedded in Coupled bind to those same values.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

from PyQt6.QtCore import Qt, QSignalBlocker, pyqtSignal, QTimer, QEvent
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTabBar, QVBoxLayout, QWidget)

from qt_common import COLORS, theme_manager
from qt_custom_device import DeviceCanvas
from simulation_setup_state import SimulationSetupState, load_plan
from input_diagnostics import normalize_diagnostic
from qt_input_diagnostics import DiagnosticPanel, reveal_and_focus


def _text(value):
    if value is None:
        return '—'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, float):
        return f'{value:.10g}'
    if isinstance(value, dict):
        return ' · '.join(f'{key}: {_text(item)}' for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return ', '.join(_text(item) for item in value)
    return str(value)


def _button(label, handler, name='setupAction'):
    result = QPushButton(label.replace('&','&&'))
    result.setObjectName(name)
    result.setMinimumHeight(34)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.clicked.connect(handler)
    return result


def _label(text='', name='setupMuted'):
    result = QLabel(text)
    result.setObjectName(name)
    result.setWordWrap(True)
    result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return result


def _scroll(widget):
    result = QScrollArea()
    result.setObjectName('setupScroll')
    result.setWidgetResizable(True)
    result.setFrameShape(QFrame.Shape.NoFrame)
    result.setWidget(widget)
    return result


class _FieldRow(QWidget):
    """Keep a numeric draft intact until it passes syntax and domain checks."""
    def __init__(self, workspace, field, parent=None):
        super().__init__(parent)
        self.workspace, self.field = workspace, field
        self.key = field.get('key', '')
        self.setObjectName('setupFieldRow')
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(5)
        self.grid=layout
        self.caption = _label(field.get('label', ''), 'setupFieldLabel')
        layout.addWidget(self.caption,0,0)
        kind = field.get('widget', 'readonly')
        if kind == 'select':
            self.editor = QComboBox()
            self.editor.currentIndexChanged.connect(self._choice_changed)
        elif kind == 'checkbox':
            self.editor = QCheckBox(field.get('label', ''))
            self.caption.hide()
            self.editor.toggled.connect(self._choice_changed)
        elif kind == 'textarea':
            self.editor = QPlainTextEdit()
            self.editor.setMinimumHeight(70)
            self.editor.setMaximumHeight(110)
            self.editor.textChanged.connect(self._text_changed)
        elif kind in ('number', 'text'):
            self.editor = QLineEdit()
            self.editor.textChanged.connect(self._text_changed)
            self.editor.editingFinished.connect(self.commit)
            if kind == 'number':
                self.editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            self.editor = _label('', 'setupReadout')
        self.editor.setObjectName('setupField_' + field.get('id', self.key).replace('.', '_'))
        self.editor.setProperty('setupKey', self.key)
        self.editor.setAccessibleName(field.get('label', self.key))
        if kind != 'readonly':
            self.editor.setMinimumHeight(34)
        self.value_widget=QWidget()
        value_row = QHBoxLayout(self.value_widget)
        value_row.setContentsMargins(0,0,0,0)
        value_row.setSpacing(8)
        value_row.addWidget(self.editor, 1)
        unit = field.get('unit')
        if unit:
            unit_label = _label(str(unit), 'setupUnit')
            unit_label.setMinimumWidth(30)
            value_row.addWidget(unit_label)
        layout.addWidget(self.value_widget,1,0)
        self.error = _label('', 'setupError')
        self.error.hide()
        layout.addWidget(self.error,2,0)
        limits = []
        if field.get('min') is not None:
            limits.append('minimum ' + _text(field['min']))
        if field.get('max') is not None:
            limits.append('maximum ' + _text(field['max']))
        self.editor.setToolTip('; '.join(limits))
        workspace.fields.append(self)
        workspace.widgets_by_key.setdefault(self.key, []).append(self.editor)
        self.refresh()

    def set_horizontal(self,horizontal):
        if getattr(self,'horizontal',None)==horizontal:
            return
        self.horizontal=horizontal
        for widget in (self.caption,self.value_widget,self.error):
            self.grid.removeWidget(widget)
        if self.field.get('widget')=='checkbox':
            self.grid.addWidget(self.value_widget,0,0,1,2)
            self.grid.addWidget(self.error,1,0,1,2)
        elif horizontal:
            self.caption.setMinimumWidth(115)
            self.caption.setMaximumWidth(140)
            self.grid.addWidget(self.caption,0,0)
            self.grid.addWidget(self.value_widget,0,1)
            self.grid.addWidget(self.error,1,1)
        else:
            self.caption.setMinimumWidth(0)
            self.caption.setMaximumWidth(16777215)
            self.grid.addWidget(self.caption,0,0,1,2)
            self.grid.addWidget(self.value_widget,1,0,1,2)
            self.grid.addWidget(self.error,2,0,1,2)
        self.grid.setColumnStretch(1,1)

    def _text_changed(self, *_):
        if self.workspace.refreshing or not self.workspace._is_active_document():
            return
        raw = self.editor.toPlainText() if isinstance(self.editor, QPlainTextEdit) else self.editor.text()
        self.workspace.drafts[self.key] = raw
        if self.field.get('widget') == 'textarea':
            # Manual voltage lists remain editable drafts until Apply offsets.
            if self.key != 'ui.electrical.bias_list_text':
                self.commit()

    def _choice_changed(self, *_):
        if self.workspace.refreshing or not self.workspace._is_active_document():
            return
        value = self.editor.currentData() if isinstance(self.editor, QComboBox) else self.editor.isChecked()
        store=self.workspace.store
        if self.key=='ui.electrical.study' and getattr(store,'study_navigation_enabled',False) and store.active_study.startswith('electrical'):
            target={'bias':'electrical','iv':'electrical.iv','cv':'electrical.cv'}.get(value)
            if target and target!=store.active_study:
                store.study_requested.emit(target)
                return
        try:
            self.workspace.state.set(self.key, value)
            self.workspace.draft_errors.pop(self.key, None)
            self.error.hide()
            self.workspace.refresh()
        except (ValueError, TypeError, KeyError) as exc:
            self.error.setText(str(exc))
            self.error.show()
            self.workspace.draft_errors[self.key] = str(exc)

    def commit(self):
        if not self.workspace._is_active_document():return False
        if not isinstance(self.editor, (QLineEdit, QPlainTextEdit)):
            return True
        if self.key not in self.workspace.drafts:
            return True
        raw = self.workspace.drafts[self.key]
        try:
            value = raw
            if self.field.get('widget') == 'number':
                value = float(raw)
                if not math.isfinite(value):
                    raise ValueError('Enter a finite number.')
                minimum, maximum = self.field.get('min'), self.field.get('max')
                if minimum is not None and value < minimum:
                    raise ValueError(f'Enter {_text(minimum)} or greater.')
                if maximum is not None and value > maximum:
                    raise ValueError(f'Enter {_text(maximum)} or less.')
                old = self.workspace.state.get(self.key, self.field.get('default'))
                if self.field.get('precision') == 0 or isinstance(old, int) and not isinstance(old, bool):
                    if value != round(value):
                        raise ValueError('Enter a whole number.')
                    value = int(value)
            self.workspace.state.set(self.key, value)
            self.workspace.drafts.pop(self.key, None)
            self.workspace.draft_errors.pop(self.key, None)
            self.error.hide()
            self.workspace.refresh()
            return True
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            self.workspace.drafts[self.key] = raw
            self.workspace.draft_errors[self.key] = str(exc)
            self.error.setText(str(exc))
            self.error.show()
            return False

    def refresh(self):
        field, state = self.field, self.workspace.state
        self.setVisible(self.workspace.condition(field.get('visible_when')))
        enabled = self.workspace.condition(field.get('enabled_when'))
        self.editor.setEnabled(enabled)
        value = state.get(self.key, None)
        blocker = QSignalBlocker(self.editor)
        if isinstance(self.editor, QComboBox):
            options = state.options(field) or field.get('options', [])
            normalized = [(str(item.get('label', item.get('value', ''))), item.get('value'))
                if isinstance(item, dict) else (str(item), item) for item in options]
            old = [(self.editor.itemText(i), self.editor.itemData(i)) for i in range(self.editor.count())]
            if old != normalized:
                self.editor.clear()
                for title, item in normalized:
                    self.editor.addItem(title, item)
            index = self.editor.findData(value)
            if index < 0 and value is not None:
                self.editor.addItem('Unresolved: ' + _text(value), value)
                index = self.editor.count()-1
            self.editor.setCurrentIndex(index)
        elif isinstance(self.editor, QCheckBox):
            self.editor.setChecked(bool(value))
        elif isinstance(self.editor, (QLineEdit, QPlainTextEdit)):
            if self.key in self.workspace.drafts:
                raw = self.workspace.drafts[self.key]
            else:
                raw = '' if value is None else _text(value)
            if isinstance(self.editor, QPlainTextEdit):
                if self.editor.toPlainText() != raw:
                    self.editor.setPlainText(raw)
            elif self.editor.text() != raw:
                self.editor.setText(raw)
        else:
            self.editor.setText(self.workspace.display_value(self.key,value))
        del blocker
        context = self.workspace._simulation_context or ''
        identity_field = (self.key == 'ui.optical.engine' and bool(context) or
            self.key == 'ui.electrical.study' and context.startswith('electrical'))
        if identity_field and not hasattr(self, 'identity_value'):
            self.identity_value = _label('', 'setupReadout')
            self.value_widget.layout().addWidget(self.identity_value, 1)
        self.editor.setVisible(not identity_field)
        if hasattr(self, 'identity_value'):
            self.identity_value.setText(self.editor.currentText() if isinstance(self.editor,QComboBox) else self.workspace.display_value(self.key,value))
            self.identity_value.setVisible(identity_field)
        message = self.workspace.draft_errors.get(self.key, '')
        self.error.setText(message)
        self.error.setVisible(bool(message))


class _PlanTable(QTableWidget):
    """Editable canonical rows keep stable IDs; no label-based reassignment."""
    def __init__(self, workspace, field, parent=None):
        super().__init__(parent)
        self.workspace, self.field = workspace, field
        self.key = field['key']
        self.setObjectName('setupTable_' + field.get('id', self.key).replace('.', '_'))
        self.setProperty('setupKey', self.key)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setMinimumHeight(132)
        self.verticalHeader().hide()
        self.horizontalHeader().setMinimumSectionSize(65)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.currentCellChanged.connect(self._select)
        self.cellChanged.connect(self._edit)
        self._rows = []
        self._updating = False
        workspace.tables_by_key.setdefault(self.key, []).append(self)
        self.refresh()

    def _select(self, row, *_):
        if self._updating or not self.workspace._is_active_document() or row < 0 or row >= len(self._rows):
            return
        value = self._rows[row]
        if isinstance(value, dict):
            ident = value.get('id', value.get('source_id', ''))
            self.workspace.selected_objects[self.key] = ident
            if self.key == 'device.contacts':
                self.workspace.state.set('ui.electrical.selected_contact_id', ident)
            elif self.key == 'device.layers':
                self.workspace.state.set('ui.electrical.selected_material_id', value.get('material_id', ''))
            self.workspace.select_object(ident)

    def _edit(self, row, column):
        if self._updating or not self.workspace._is_active_document() or row < 0 or row >= len(self._rows):
            return
        key = self.key
        if key == 'search.electrical.biases_V' and not self.field.get('editable', True):
            return
        value = self._rows[row]
        item = self.item(row, column)
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEditable:
            return
        ident=value.get('id',value.get('source_id','')) if isinstance(value,dict) else str(row)
        draft_key=(key,ident,column)
        self.workspace.table_drafts[draft_key]=item.text()
        try:
            if key == 'device.layers':
                attribute = {4:'donor_cm3', 5:'acceptor_cm3'}.get(column)
                if attribute:
                    number = float(item.text())
                    if not math.isfinite(number) or not 0 <= number <= 1e22:
                        raise ValueError('Doping must be a finite number between 0 and 1e22 cm⁻³.')
                    self.workspace.state.update_layer(value['id'], {attribute:number})
            elif key == 'device.contacts' and column == 5:
                number = float(item.text())
                if not math.isfinite(number):
                    raise ValueError('Base voltage must be finite.')
                self.workspace.state.update_contact(value['id'], {'voltage_V':number})
            elif key == 'device.doping_regions' and column in (4, 5):
                rows = deepcopy(self.workspace.state.store.device['doping_regions'])
                number = float(item.text())
                if not math.isfinite(number) or not 0 <= number <= 1e22:
                    raise ValueError('Doping must be between 0 and 1e22 cm⁻³.')
                next(obj for obj in rows if obj['id'] == value['id'])['donor_cm3' if column == 4 else 'acceptor_cm3'] = number
                self.workspace.state.set(key, rows)
            elif key == 'search.electrical.biases_V':
                rows = [float(self.item(i, 0).text()) for i in range(self.rowCount())]
                self.workspace.state.set(key, rows)
            elif key == 'search.electrical.measured_current':
                rows = [dict(bias_V=float(self.item(i, 0).text()), current_A=float(self.item(i, 1).text()))
                    for i in range(self.rowCount())]
                self.workspace.state.set(key, rows)
            self.workspace.table_drafts.pop(draft_key,None)
            self.workspace.table_errors.pop(draft_key,None)
            remaining=next((message for address,message in self.workspace.table_errors.items() if address[0]==key),None)
            if remaining:self.workspace.draft_errors[key]=remaining
            else:self.workspace.draft_errors.pop(key, None)
        except (ValueError, KeyError, TypeError) as exc:
            self.workspace.draft_errors[key] = str(exc)
            self.workspace.table_errors[draft_key]=str(exc)
            self.workspace.set_status(str(exc), error=True)
            item.setToolTip(str(exc))

    def _choice(self, ident, attribute, value):
        if self._updating or not self.workspace._is_active_document():return
        try:
            if self.key == 'device.layers':
                self.workspace.state.update_layer(ident, {attribute:value})
            elif self.key == 'device.contacts':
                if attribute == 'swept':
                    self.workspace.state.set('search.electrical.swept_contact_id', ident)
                else:
                    self.workspace.state.update_contact(ident, {attribute:value})
            elif self.key == 'device.doping_regions':
                rows = deepcopy(self.workspace.state.store.device['doping_regions'])
                next(obj for obj in rows if obj['id'] == ident)[attribute] = value
                self.workspace.state.set(self.key, rows)
        except (ValueError, TypeError, KeyError) as exc:
            self.workspace.set_status(str(exc), error=True)
            self.refresh()

    def _check(self, row, column, ident, attribute, value):
        widget = QCheckBox()
        widget.setChecked(bool(value))
        widget.setAccessibleName(attribute + ' ' + ident)
        widget.toggled.connect(lambda checked: self._choice(ident, attribute, checked))
        self.setCellWidget(row, column, widget)

    def _combo(self, row, column, ident, attribute, value, choices):
        widget = QComboBox()
        for label, option in choices:
            widget.addItem(label, option)
        widget.setCurrentIndex(widget.findData(value))
        widget.currentIndexChanged.connect(lambda _: self._choice(ident, attribute, widget.currentData()))
        self.setCellWidget(row, column, widget)

    def refresh(self):
        self.setVisible(self.workspace.condition(self.field.get('visible_when')))
        self.setEnabled(self.workspace.condition(self.field.get('enabled_when')))
        device = getattr(self.workspace.state.store, 'device', None) or {}
        if self.key.startswith('device.') and self.key.split('.')[-1] in ('contacts','layers','doping_regions'):
            rows = device.get(self.key.split('.')[-1], [])
        else:
            rows = self.workspace.state.get(self.key, []) or []
        if not isinstance(rows, list):
            rows = []
        if self.key == 'search.coupled.optical_mapping' and isinstance(self.workspace.state.get(self.key),dict):
            mapping=self.workspace.state.get(self.key)
            rows=[dict(source_id=layer['id'],source=layer['name'],thickness=layer['thickness_um'],
                electrical_material=layer['material_id'],target=mapping.get(layer['id'],{}).get('layer',layer.get('optical_layer_name',layer['name'])),
                optical_material=mapping.get(layer['id'],{}).get('material',layer.get('optical_material_name','')),
                status='Linked' if layer['id'] in mapping else 'Automatic structure link')
                for layer in device.get('layers',[]) if layer.get('enabled',True)]
        self.total_rows=len(rows)
        sweep_preview = self.key in ('ui.electrical.voltage_schedule', 'search.electrical.biases_V')
        if self.key == 'ui.electrical.voltage_schedule':
            self.total_rows = self.workspace.state.get('ui.electrical.voltage_schedule_count', len(rows))
        elif sweep_preview and len(rows) > 200:
            rows = rows[:100] + rows[-100:]
        elif not sweep_preview and len(rows)>600:
            rows=rows[:600]
        clipped = self.total_rows > len(rows)
        notice = (f'Preview: first and last 100 of {self.total_rows:,} voltage states. The complete schedule is submitted; edit it with the range or manual controls.' if sweep_preview else
            f'Preview: first 600 of {self.total_rows:,} rows. All objects remain editable in Structure.') if clipped else ''
        self.setToolTip(notice)
        if getattr(self,'count_label',None):
            self.count_label.setText(notice)
            self.count_label.setVisible(clipped)
        contact_labels = [obj['name'] for obj in self.workspace.state._contacts()] if self.key == 'ui.electrical.voltage_schedule' else []
        drafts=[(list(address),text) for address,text in self.workspace.table_drafts.items() if address[0]==self.key]
        signature = json.dumps([rows,self.workspace.state.get('search.electrical.swept_contact_id'),contact_labels,drafts], sort_keys=True, default=str)
        if signature == getattr(self, '_signature', None):
            return
        self._signature = signature
        self._updating = True
        self._rows = rows
        columns = self.field.get('columns', [])
        if isinstance(columns, str):
            columns = [columns]
        columns = columns or ['Value']
        labels = [col.get('label', col.get('id', '')) if isinstance(col, dict) else str(col) for col in columns]
        if self.key == 'ui.electrical.voltage_schedule':
            labels = ['Solve order', 'Offset (V)', *[name + ' (V)' for name in contact_labels], 'Reason']
        selected = self.workspace.selected_objects.get(self.key)
        self.clear()
        self.setColumnCount(len(labels))
        self.setHorizontalHeaderLabels(labels)
        self.setRowCount(len(rows))
        layer_names = {obj['id']:obj['name'] for obj in device.get('layers', [])}
        for index, row in enumerate(rows):
            if self.key == 'device.layers':
                values = [row.get('enabled'), row.get('name'), row.get('material_id'),
                    float(row.get('thickness_um',0))*1000, row.get('donor_cm3',0), row.get('acceptor_cm3',0),
                    'n' if row.get('donor_cm3',0) > row.get('acceptor_cm3',0) else 'p' if row.get('acceptor_cm3',0) > row.get('donor_cm3',0) else 'Intrinsic']
            elif self.key == 'device.contacts':
                values = [row.get('enabled'),row.get('name'),layer_names.get(row.get('layer_id'),row.get('layer_id')),
                    row.get('surface'),row.get('boundary'),row.get('voltage_V'),
                    row['id'] == self.workspace.state.get('search.electrical.swept_contact_id')]
            elif self.key == 'device.doping_regions':
                values = [row.get('enabled'),row.get('name'),layer_names.get(row.get('layer_id')),row.get('shape'),
                    row.get('donor_cm3',0),row.get('acceptor_cm3',0),index+1]
            elif isinstance(row, dict):
                column_keys=['region','electrical_material','optical_material','model','coverage','status'] if self.key=='ui.optical.assignment_rows' else None
                values = [row.get(column_keys[column], '—') if column_keys else row.get(col.get('id', col.get('key', col.get('label',''))), '—')
                    if isinstance(col, dict) else row.get(col, '—') for column,col in enumerate(columns)]
                if all(value == '—' for value in values):
                    values = list(row.values())
            elif isinstance(row, (list, tuple)):
                values = list(row)
            else:
                values = [row]
            for column in range(len(labels)):
                value = values[column] if column < len(values) else ''
                item = QTableWidgetItem(_text(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if (self.key == 'device.layers' and column in (4,5) or
                    self.key == 'device.contacts' and column == 5 or
                    self.key == 'device.doping_regions' and column in (4,5) or
                    self.key == 'search.electrical.measured_current' or
                    self.key == 'search.electrical.biases_V' and self.field.get('editable', True)):
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                ident=row.get('id',row.get('source_id','')) if isinstance(row,dict) else str(index)
                draft_key=(self.key,ident,column)
                if draft_key in self.workspace.table_drafts:
                    item.setText(self.workspace.table_drafts[draft_key])
                    item.setToolTip(self.workspace.table_errors.get(draft_key,''))
                self.setItem(index, column, item)
            if self.key in ('device.layers','device.contacts','device.doping_regions'):
                self._check(index,0,row['id'],'enabled',row.get('enabled',True))
            if self.key == 'device.layers':
                choices = [(obj['name'],obj['id']) for obj in self.workspace.state.store.electrical_materials]
                self._combo(index,2,row['id'],'material_id',row.get('material_id'),choices)
            elif self.key == 'device.contacts':
                self._combo(index,4,row['id'],'boundary',row.get('boundary'),[('Ohmic reservoir','ohmic'),('Fixed potential','potential')])
                self._check(index,6,row['id'],'swept',values[6])
            elif self.key == 'ui.optical.assignment_rows':
                editor=QComboBox()
                for name in self.workspace.state.store.materials['Name']:
                    editor.addItem(str(name),str(name))
                editor.setCurrentIndex(editor.findData(row.get('optical_material')))
                editor.currentIndexChanged.connect(lambda _,ident=row['id'],control=editor:self._assign_optical(ident,control.currentData()))
                self.setCellWidget(index,2,editor)
            elif self.key == 'search.coupled.optical_mapping':
                editor=QComboBox()
                finite=self.workspace.state.store.layers.iloc[1:-1]
                for _,layer in finite.iterrows():
                    editor.addItem(str(layer['Name']),str(layer['Name']))
                editor.setCurrentIndex(editor.findData(row.get('target')))
                editor.currentIndexChanged.connect(lambda _,ident=row['source_id'],control=editor:self._map_layer(ident,control.currentData()))
                self.setCellWidget(index,4,editor)
            if selected and isinstance(row, dict) and row.get('id') == selected:
                self.selectRow(index)
        self.setMaximumHeight(min(310, max(140, 34*len(rows)+40)))
        self._updating = False

    def _assign_optical(self,ident,material):
        try:
            self.workspace.state.update_optical_assignment(ident,material)
        except (ValueError,KeyError,TypeError) as exc:
            self.workspace.set_status(str(exc),error=True)

    def _map_layer(self,ident,target):
        try:
            rows=deepcopy(self.workspace.state.get('search.coupled.optical_mapping',{}))
            rows=rows if isinstance(rows,dict) else {}
            layer=next((row for row in self.workspace.state.store.layers.to_dict('records') if row['Name']==target),None)
            if not layer:
                raise ValueError('Choose an existing finite optical layer.')
            rows[ident]=dict(layer=target,material=layer['Material'])
            self.workspace.state.set_optical_mapping(rows)
        except (ValueError,KeyError,TypeError) as exc:
            self.workspace.set_status(str(exc),error=True)


class _ObjectDialog(QDialog):
    """Detached contact/doping footprint editor; Apply is one project transaction."""
    def __init__(self, workspace, group, original=None):
        super().__init__(workspace)
        from device_model import new_id
        self.workspace, self.group = workspace, group
        device = workspace.state.store.device or {}
        layers = device.get('layers', [])
        self.original = deepcopy(original or dict(id=new_id('contact' if group=='contacts' else 'doping'),
            name='New contact' if group=='contacts' else 'New doping region', enabled=True,
            layer_id=layers[0]['id'] if layers else '', shape='rectangle',cx_um=0.,cy_um=0.,
            size_x_um=min(1.,device.get('width_um',1.)),size_y_um=min(1.,device.get('depth_um',1.)),
            angle_deg=0.,vertices=[],surface='top',boundary='ohmic',voltage_V=0.,bias_scale=0.,
            donor_cm3=0.,acceptor_cm3=0.))
        self.setObjectName('setupDialog')
        self.setWindowTitle(('Edit ' if original else 'Add ') + ('electrical contact' if group=='contacts' else 'doping region'))
        self.resize(590,700)
        layout = QVBoxLayout(self)
        layout.addWidget(_label('Geometry, boundary values and optical metal are shared with the device editor. Apply updates all linked views.'))
        content = QWidget()
        form = QFormLayout(content)
        self.controls = {}
        choices = {'layer_id':[(obj['name'],obj['id']) for obj in layers],
            'shape':[(label,label) for label in ('rectangle','circle','ellipse','square_ring','polygon')],
            'surface':[(label.replace('_',' '),label) for label in ('top','bottom','side_x_min','side_x_max','side_y_min','side_y_max')],
            'boundary':[('Ohmic reservoir','ohmic'),('Fixed potential','potential')]}
        fields = [('name','Name'),('layer_id','Layer'),('shape','Footprint shape'),('cx_um','Center X (µm)'),
            ('cy_um','Center Y (µm)'),('size_x_um','Outer width (µm)'),('size_y_um','Outer depth (µm)'),
            ('angle_deg','Rotation (degrees)'),('inner_size_x_um','Ring inner width (µm)'),
            ('inner_size_y_um','Ring inner depth (µm)'),('vertices','Polygon vertices (x,y; µm)')]
        if group=='contacts':
            fields += [('surface','Attached surface'),('boundary','Electrical boundary'),('voltage_V','Base voltage (V)'),
                ('optical_material_name','Optical metal material'),('optical_thickness_um','Optical thickness (µm)')]
        else:
            fields += [('donor_cm3','Donors (cm⁻³)'),('acceptor_cm3','Acceptors (cm⁻³)')]
        for key, title in fields:
            value = self.original.get(key, '' if key=='optical_material_name' else [] if key=='vertices' else .5 if key.startswith('inner') else 0.)
            if key in choices:
                editor = QComboBox()
                for label, option in choices[key]:
                    editor.addItem(label, option)
                editor.setCurrentIndex(editor.findData(value))
            elif key=='vertices':
                editor = QPlainTextEdit(json.dumps(value))
                editor.setMaximumHeight(82)
            elif key=='optical_material_name':
                editor = QComboBox()
                editor.addItem('No optical metal slab','')
                for name in workspace.state.store.materials['Name']:
                    editor.addItem(str(name),str(name))
                editor.setCurrentIndex(editor.findData(value))
            else:
                editor = QLineEdit(_text(value))
            editor.setObjectName('setupObject_'+key)
            self.controls[key] = editor
            form.addRow(title,editor)
        self._form = form
        self.controls['shape'].currentIndexChanged.connect(self._shape_changed)
        self._shape_changed()
        layout.addWidget(_scroll(content),1)
        self.status = _label('', 'setupError')
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _shape_changed(self):
        shape = self.controls['shape'].currentData()
        for key in ('inner_size_x_um','inner_size_y_um','vertices'):
            editor = self.controls[key]
            visible = shape=='polygon' if key=='vertices' else shape=='square_ring'
            editor.setVisible(visible)
            self._form.labelForField(editor).setVisible(visible)

    def apply(self):
        try:
            value = deepcopy(self.original)
            for key, editor in self.controls.items():
                if isinstance(editor,QComboBox):
                    raw = editor.currentData()
                elif isinstance(editor,QPlainTextEdit):
                    raw = json.loads(editor.toPlainText())
                else:
                    raw = editor.text().strip()
                    if key!='name':
                        raw = float(raw)
                        if not math.isfinite(raw):
                            raise ValueError(key+' must be finite.')
                value[key]=raw
            rows = deepcopy(self.workspace.state.store.device[self.group])
            existing = next((i for i,obj in enumerate(rows) if obj['id']==value['id']),None)
            if existing is None:
                rows.append(value)
            else:
                rows[existing]=value
            self.workspace.state.set('device.'+self.group,rows)
            self.accept()
        except (ValueError,TypeError,KeyError) as exc:
            self.status.setText(str(exc))


class SimulationSetupWorkspace(QWidget):
    routeRequested = pyqtSignal(str)
    runRequested = pyqtSignal(str)
    selectWorkflow = pyqtSignal(str)
    editDeviceRequested = pyqtSignal()
    resultsRequested = pyqtSignal(dict)
    opticalRunRequested = pyqtSignal()
    statusChanged = pyqtSignal(str)
    diagnosticRequested = pyqtSignal(dict)

    def __init__(self, store=None, parent=None, *, mode='optical', state=None, workflow=None, document_id=None):
        super().__init__(parent)
        self._bound_study_id = document_id
        self._simulation_context = document_id
        self.state = state or SimulationSetupState(store,self)
        self.store = self.state.store
        from optical_ui_scope import s4_setup_plan
        self.plan = s4_setup_plan(load_plan())
        self._modes = self.plan.get('modes',self.plan)
        self._mode = workflow or mode
        self.workflow = self._mode
        self.refreshing = False
        self.fields, self.tables_by_key, self.widgets_by_key = [], {}, {}
        self.cards=[]
        self.table_rows=[]
        self.page_grids=[]
        self.drafts, self.draft_errors, self.selected_objects = {}, {}, {}
        self.table_drafts,self.table_errors={},{}
        self.pages, self.section_meta, self.active_sections = {}, {}, {}
        self.nested_sections = {'optical':'optical.overview','electrical':'electrical.overview'}
        self.starts, self.stops = [], []
        self.setObjectName('simulationSetupWorkspace')
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(8,0,8,8)
        self.layout_.setSpacing(8)
        mode_bar = self.mode_bar = QFrame()
        mode_bar.setObjectName('setupModeBar')
        row = QHBoxLayout(mode_bar)
        row.setContentsMargins(4,4,4,4)
        row.setSpacing(6)
        self.mode_buttons = {}
        for key, name in [('optical','Optical'),('electrical','Electrical'),('coupled','Coupled')]:
            button = _button(name,lambda checked=False,value=key:self._choose_mode(value),'setupMode')
            button.setCheckable(True)
            button.setMinimumWidth(116)
            self.mode_buttons[key]=button
            row.addWidget(button)
        row.addStretch()
        self.more_studies_button = _button('More studies…', lambda:self.routeRequested.emit('research.overview'))
        row.addWidget(self.more_studies_button)
        mode_note=_label('Independent device · this simulation','setupModeNote')
        mode_note.setWordWrap(False)
        row.addWidget(mode_note)
        self.layout_.addWidget(mode_bar)
        self.engine_recovery = _button('Restore S4 workflow for this study — keep stored inputs', self.restore_s4_workflow)
        self.engine_recovery.setToolTip('An older document selected Meep in this S4 workspace. Restore its S4 identity without deleting either solver’s stored parameters. Meep runs in its separate workspace.')
        self.engine_recovery.hide()
        self.layout_.addWidget(self.engine_recovery)
        self.body = QHBoxLayout()
        self.body.setSpacing(8)
        self.layout_.addLayout(self.body,1)
        self.nav_panel = QFrame()
        self.nav_panel.setObjectName('setupNavigation')
        self.nav_panel.setFixedWidth(232)
        nav = QVBoxLayout(self.nav_panel)
        nav.setContentsMargins(0,10,0,8)
        nav.setSpacing(8)
        self.nav_title = _label('OPTICAL SETUP','setupNavTitle')
        nav.addWidget(self.nav_title)
        self.navigation = QListWidget()
        self.navigation.setObjectName('setupSections')
        self.navigation.currentItemChanged.connect(self._section_changed)
        nav.addWidget(self.navigation,1)
        nav.addWidget(_button('Load preset…',self.load_preset))
        nav.addWidget(_button('Save preset…',self.save_setup))
        self.body.addWidget(self.nav_panel)
        self.center = QWidget()
        center = QVBoxLayout(self.center)
        center.setContentsMargins(0,0,0,0)
        center.setSpacing(8)
        self.return_button = _button('‹ Return to Coupled transfer & mapping',lambda:self.select_section('coupled.transfer'))
        self.return_button.hide()
        center.addWidget(self.return_button)
        self.title = _label('Optical simulation setup','setupTitle')
        self.purpose = _label('', 'setupPurpose')
        center.addWidget(self.title)
        center.addWidget(self.purpose)
        self.nested_tabs = QTabBar()
        self.nested_tabs.setObjectName('setupNestedTabs')
        self.nested_tabs.setExpanding(False)
        self.nested_tabs.setUsesScrollButtons(True)
        self.nested_tabs.currentChanged.connect(self._nested_changed)
        self.nested_tabs.hide()
        center.addWidget(self.nested_tabs)
        self.diagnostics = DiagnosticPanel(self)
        self.validation_list = self.diagnostics.list
        self.diagnostics.activated.connect(self.open_diagnostic)
        self.diagnostics.recheckRequested.connect(self.validate_current)
        self.diagnostics.returnRequested.connect(self.return_to_issues)
        self._issue_return = None
        center.addWidget(self.diagnostics)
        self.stack = QStackedWidget()
        center.addWidget(self.stack,1)
        self.status = _label('Changed since last validation','setupStatus')
        center.addWidget(self.status)
        self.body.addWidget(self.center,1)
        self.rail = self._make_rail()
        self.rail_scroll = _scroll(self.rail)
        self.rail_scroll.setFixedWidth(420)
        self.body.addWidget(self.rail_scroll)
        for mode_name in ('optical','electrical','coupled'):
            for tab in self._modes[mode_name]['tabs']:
                self.section_meta[tab['id']]=tab
                self.pages[tab['id']]=self._make_page(tab)
        self.state.changed.connect(self.refresh)
        self.store.changed.connect(self._reset_project_drafts)
        theme_manager().changed.connect(self._apply_style)
        self._apply_style()
        self.set_mode(self._mode)
        self.refresh()
        from qt_simulation_flow import SimulationSetupFlow
        self.setup_flow = SimulationSetupFlow(self)
        self.set_simulation_context(document_id)
        # Restored projects and lazy bank pages loaded before this widget
        # connected to store.changed. Recover their unfinished controls now.
        self._reset_project_drafts('project')

    def restore_s4_workflow(self):
        if not self._is_active_document() or self.store.busy:
            return
        self.state.set('ui.optical.engine','s4')
        self.set_status('S4 workflow restored. Stored S4 and Meep parameter values were retained.')
        self.refresh()

    def _is_active_document(self):
        return not self._bound_study_id or self.store.active_study == self._bound_study_id

    def set_simulation_context(self, identifier):
        """Show one study's identity; switching simulations belongs to the host."""
        self._simulation_context = identifier
        self.mode_bar.setVisible(not bool(identifier))
        self._update_context_title()
        self.refresh()

    def _update_context_title(self):
        identity = self._simulation_context
        if not identity:return
        from qt_simulation_picker import SIMULATIONS
        title = next((row[1] for row in SIMULATIONS if row[0] == identity), identity)
        section = getattr(self, 'current_section', self._mode+'.overview')
        nested = section.split('.')[0] if self._mode == 'coupled' and not section.startswith('coupled.') else ''
        self.title.setText(title + (' · '+nested.title()+' setup' if nested else ''))
        self.nav_title.setText({'electrical.iv':'I–V SETUP','electrical.cv':'C–V SETUP',
            'electrical':'DC SETUP'}.get(identity,self._mode.upper()+' SETUP'))

    def _mode_allowed(self, mode):
        if not self._simulation_context:return True
        expected = ('electrical' if self._simulation_context.startswith('electrical') else
                    'coupled' if self._simulation_context == 'coupled' else 'optical')
        return mode == expected

    @property
    def current_mode(self):
        return self._mode

    def display_value(self,key,value):
        if key=='ui.optical.engine':
            return 'S4 · periodic RCWA' if value=='s4' else 'Incompatible Meep setup — open its separate workspace'
        if key=='device.mesh' and isinstance(value,dict):
            return f'{value.get("nx",0)} × {value.get("ny",0)} cells · {value.get("nz_per_layer",0)} depth cells / layer'
        if key=='settings.optical_unit_cell' and isinstance(value,dict):
            return f'{_text(value.get("width_um"))} × {_text(value.get("depth_um"))} µm periodic cell' if value.get('enabled') else 'Full footprint · periodically repeated supercell'
        for field in self.fields:
            if field.key==key and field.field.get('widget')=='select':
                options=self.state.options(field.field)
                choice=next((row.get('label') for row in options if isinstance(row,dict) and row.get('value')==value),None)
                if choice:
                    return choice
        if key=='search.electrical.swept_contact_id':
            row=next((row for row in (self.store.device or {}).get('contacts',[]) if row['id']==value),None)
            return row['name'] if row else 'Unresolved terminal' if value else 'Last enabled contact'
        return _text(value)

    def condition(self, condition):
        if isinstance(condition,bool):
            return condition
        if not condition:
            return True
        if isinstance(condition,list):
            return all(self.condition(item) for item in condition)
        if not isinstance(condition,dict):
            return True
        if 'all' in condition:
            return all(self.condition(item) for item in condition['all'])
        if 'any' in condition:
            return any(self.condition(item) for item in condition['any'])
        if 'not' in condition:
            return not self.condition(condition['not'])
        value = self.state.get(condition.get('key',''))
        if 'equals' in condition:
            return value == condition['equals']
        if 'in' in condition:
            return value in condition['in']
        if 'not_equals' in condition:
            return value != condition['not_equals']
        if 'truthy' in condition:
            return bool(value) == bool(condition['truthy'])
        return bool(value)

    def _make_page(self, tab):
        if tab['id'] == 'electrical.study':
            # Presentation only: commit/check the draft before browsing its
            # applied previews or the longer model-scope explanations.
            tab = deepcopy(tab)
            by_id = {card['id']: card for card in tab['cards']}
            offsets = by_id['electrical.study.range']
            schedule = by_id['electrical.study.schedule']
            check = next(action for action in schedule['actions'] if action['target'] == 'electrical.validate_biases')
            offsets['actions'].append(check)
            offsets['actions_after_key'] = 'ui.electrical.bias_list_text'
            schedule['actions'].remove(check)
            for field in offsets['fields']:
                if field['key'] == 'ui.electrical.bias_list_text':
                    field['label'] = 'Manual offsets · draft until Apply'
                elif field['key'] == 'search.electrical.biases_V':
                    field['label'] = 'Submitted offsets · applied values'
            tab['cards'].remove(schedule)
            tab['cards'].insert(tab['cards'].index(offsets)+1, schedule)
        content = QWidget()
        content.setObjectName('setupCards')
        grid = QGridLayout(content)
        grid.setContentsMargins(0,0,0,0)
        grid.setSpacing(8)
        grid.setColumnStretch(0,1)
        grid.setColumnStretch(1,1)
        cards=[(self._make_card(card,parent=content),card) for card in tab.get('cards',[]) if not card.get('embedded_editor')]
        self.page_grids.append((grid,cards))
        self._reflow_grid(grid,cards)
        scroll = _scroll(content)
        scroll.setProperty('setupSection',tab['id'])
        self.stack.addWidget(scroll)
        return scroll

    def _reflow_grid(self,grid,cards):
        for index in range(grid.rowCount()):
            grid.setRowStretch(index,0)
        for frame,_ in cards:
            grid.removeWidget(frame)
        row,occupied=0,set()
        narrow=hasattr(self,'setup_flow') or self.center.width()<640
        for frame,card in cards:
            if not self.condition(card.get('visible_when')):
                continue
            column=card.get('column',1)
            if narrow or column=='full':
                if occupied:
                    row+=1
                    occupied=set()
                grid.addWidget(frame,row,0,1,2,Qt.AlignmentFlag.AlignTop)
                row+=1
            else:
                col=0 if column==1 else 1
                if col in occupied:
                    row+=1
                    occupied=set()
                grid.addWidget(frame,row,col,Qt.AlignmentFlag.AlignTop)
                occupied.add(col)
                if len(occupied)==2:
                    row+=1
                    occupied=set()
        if occupied:
            row+=1
        grid.setRowStretch(row,1)

    def _make_card(self, card, parent=None):
        frame = QFrame(parent)
        frame.setObjectName('setupCard')
        frame.setProperty('setupCardId',card.get('id',''))
        self.cards.append((frame,card))
        frame.setMinimumWidth(100)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14,12,14,14)
        layout.setSpacing(10)
        heading = _label(card.get('title',''),'setupCardTitle')
        heading.setMinimumHeight(22)
        layout.addWidget(heading)
        rule = QFrame()
        rule.setObjectName('setupRule')
        rule.setFixedHeight(1)
        layout.addWidget(rule)
        action_index = None
        for field in card.get('fields',[]):
            if field.get('widget')=='table':
                row=QWidget(frame)
                row_layout=QVBoxLayout(row)
                row_layout.setContentsMargins(0,0,0,0)
                row_layout.setSpacing(5)
                row_layout.addWidget(_label(field.get('label',''),'setupFieldLabel'))
                table=_PlanTable(self,field,parent=row)
                if field['key'] in ('search.electrical.biases_V', 'ui.electrical.voltage_schedule'):
                    table.setMaximumHeight(170)
                row_layout.addWidget(table)
                notice=_label('','setupMuted')
                notice.hide()
                table.count_label=notice
                row_layout.addWidget(notice)
                self.table_rows.append((row,field))
                layout.addWidget(row)
            else:
                layout.addWidget(_FieldRow(self,field,parent=frame))
            if field.get('key') == card.get('actions_after_key'):
                action_index = layout.count()
        actions = card.get('actions',[])
        for index, action in enumerate(actions):
            button = _button(action['label'],lambda checked=False,value=action:self.perform_action(value))
            button.setProperty('setupActionId',action.get('id'))
            if action_index is not None:
                layout.insertWidget(action_index + index, button)
            elif card.get('actions_position') == 'top':
                layout.insertWidget(2 + index, button)
            else:
                layout.addWidget(button)
        return frame

    def _make_rail(self):
        rail = QWidget()
        rail.setObjectName('setupRail')
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(8)
        frame = QFrame()
        frame.setObjectName('setupCard')
        preview = QVBoxLayout(frame)
        preview.setContentsMargins(12,12,12,12)
        preview.setSpacing(8)
        preview.addWidget(_label('This simulation’s device','setupCardTitle'))
        self.shared_preview = DeviceCanvas('3d')
        self.shared_preview.compact_preview=True
        self.shared_preview.depth_display_mode='film'
        self.shared_preview.setMinimumHeight(220)
        self.shared_preview.setMaximumHeight(280)
        self.shared_preview.setMinimumWidth(100)
        self.shared_preview.object_selected.connect(self.select_object)
        preview.addWidget(self.shared_preview)
        minis = QHBoxLayout()
        self.top_preview = DeviceCanvas('top')
        self.section_preview = DeviceCanvas('section')
        for title, view in [('Top · XY',self.top_preview),('Cross-section · XZ',self.section_preview)]:
            container = QWidget()
            column = QVBoxLayout(container)
            column.setContentsMargins(0,0,0,0)
            column.setSpacing(4)
            column.addWidget(_label(title,'setupFieldLabel'))
            view.compact_preview=True
            view.setMinimumSize(100,135)
            view.setMaximumHeight(180)
            view.object_selected.connect(self.select_object)
            column.addWidget(view)
            minis.addWidget(container,1)
        preview.addLayout(minis)
        preview.addWidget(_label('Cyan: optical cell · dashed: PC area · solid: finite device','setupPreviewLegend'))
        preview.addWidget(_button('Edit simulation structure',lambda:self.routeRequested.emit('global.structure')))
        layout.addWidget(frame)
        summary = QFrame()
        summary.setObjectName('setupCard')
        self.summary_layout = QVBoxLayout(summary)
        self.summary_layout.setContentsMargins(14,12,14,14)
        self.summary_layout.setSpacing(10)
        self.summary_title = _label('Optical domain','setupCardTitle')
        self.summary_layout.addWidget(self.summary_title)
        self.summary = _label('', 'setupReadout')
        self.summary_layout.addWidget(self.summary)
        layout.addWidget(summary)
        self.sequence = QFrame()
        self.sequence.setObjectName('setupCard')
        sequence = QVBoxLayout(self.sequence)
        sequence.setContentsMargins(14,12,14,14)
        sequence.addWidget(_label('Coupled run sequence','setupCardTitle'))
        for number, label in enumerate(('Finite electrical bias states','Solid-only profile transfer','Depth-resolved optical material update','Periodic optical response'),1):
            sequence.addWidget(_label(f'{number:02d}  {label}','setupSequenceStep'))
        layout.addWidget(self.sequence)
        layout.addStretch()
        return rail

    def _apply_style(self, *_):
        c = COLORS[theme_manager().mode]
        self.setStyleSheet(f'''
        QWidget#simulationSetupWorkspace {{ background:{c['bg']}; color:{c['text']}; font-family:'Segoe UI'; font-size:13px; }}
        QWidget#simulationSetupWorkspace QLabel {{ background:transparent; color:{c['text']}; }}
        QFrame#setupCard,QFrame#setupNavigation {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:5px; }}
        QFrame#setupModeBar {{ background:{c['panel']}; border-bottom:1px solid {c['border']}; }}
        QLabel#setupTitle {{font-size:20px; font-weight:600;}}
        QLabel#setupCardTitle {{font-size:14px; font-weight:600;}}
        QLabel#setupNavTitle {{padding:4px 12px; font-size:12px; font-weight:600; color:{c['muted']};}}
        QLabel#setupFieldLabel,QLabel#setupPurpose,QLabel#setupMuted,QLabel#setupUnit,QLabel#setupModeNote,QLabel#setupPreviewLegend {{color:{c['muted']};}}
        QLabel#setupPreviewLegend {{font-size:11px;}}
        QLabel#setupError {{color:#ffb4b4; font-size:12px;}}
        QFrame#setupRule {{background:{c['border']}; border:0;}}
        QLineEdit,QPlainTextEdit,QComboBox {{background:{c['field']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:4px; padding:5px 8px; min-height:22px;}}
        QLineEdit:focus,QComboBox:focus,QPlainTextEdit:focus {{border:1px solid {c['accent']};}}
        QCheckBox {{color:{c['text']}; spacing:8px;}}
        QCheckBox::indicator {{width:15px; height:15px;}}
        QPushButton#setupAction {{background:{c['field']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:4px; padding:5px 10px;}}
        QPushButton#setupAction:hover {{background:{c['hover']}; border-color:{c['accent']};}}
        QPushButton#setupMode {{background:transparent; color:{c['muted']}; border:1px solid transparent; border-radius:4px; padding:6px 14px;}}
        QPushButton#setupMode:checked {{background:{c['select']}; color:{c['accent']}; border:1px solid {c['accent']};}}
        QListWidget#setupSections {{background:transparent; border:0; outline:0;}}
        QListWidget#setupSections::item {{padding:11px 10px; min-height:22px; color:{c['muted']}; border-left:3px solid transparent;}}
        QListWidget#setupSections::item:selected {{background:{c['select']}; color:{c['text']}; border-left:3px solid {c['accent']};}}
        QScrollArea#setupScroll,QWidget#setupCards,QWidget#setupRail {{background:{c['bg']}; border:0;}}
        QTableWidget {{background:{c['field']}; alternate-background-color:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; gridline-color:{c['border']}; selection-background-color:{c['select']};}}
        QHeaderView::section {{background:{c['panel']}; color:{c['muted']}; border:0; border-bottom:1px solid {c['border']}; padding:8px 4px;}}
        QTabBar#setupNestedTabs::tab {{background:{c['field']}; color:{c['muted']}; padding:8px 12px; border-bottom:2px solid transparent;}}
        QTabBar#setupNestedTabs::tab:selected {{color:{c['accent']}; border-bottom:2px solid {c['accent']};}}
        ''')
        if hasattr(self,'setup_flow'):
            self.setup_flow.apply_style()

    def _choose_mode(self, mode):
        if not self._mode_allowed(mode):return
        self.set_mode(mode)
        self.selectWorkflow.emit(mode)

    def set_mode(self, mode):
        if mode not in self._modes:
            raise ValueError('Choose Optical, Electrical or Coupled.')
        if not self._mode_allowed(mode):return
        self._mode = self.workflow = mode
        self.nav_title.setText(mode.upper()+' SETUP')
        for key, button in self.mode_buttons.items():
            button.setChecked(key==mode)
        blocker = QSignalBlocker(self.navigation)
        self.navigation.clear()
        current = self.active_sections.get(mode, mode+'.overview')
        for tab in self._modes[mode]['tabs']:
            item = QListWidgetItem(tab['title'])
            item.setData(Qt.ItemDataRole.UserRole,tab['id'])
            self.navigation.addItem(item)
            if tab['id']==current:
                self.navigation.setCurrentItem(item)
        del blocker
        self.select_section(current)
        self.sequence.setVisible(mode=='coupled')
        self.refresh()

    def _section_changed(self, current, previous):
        if current is not None:
            self.select_section(current.data(Qt.ItemDataRole.UserRole))

    def select_section(self, section):
        if '/' in section:
            outer, nested = section.split('/',1)
            self.select_section(outer)
            self.select_section(nested)
            return
        if section not in self.pages:
            self.routeRequested.emit(section)
            return
        source_mode = section.split('.')[0]
        embedded = self._mode=='coupled' and source_mode in ('optical','electrical')
        if not embedded and not self._mode_allowed(source_mode):
            self.set_status('Use Choose simulation to open a different simulation workspace.')
            return False
        if source_mode!=self._mode and not embedded:
            self.set_mode(source_mode)
        self.current_section = section
        if embedded:
            self.nested_sections[source_mode]=section
            self.return_button.show()
            self._show_nested(source_mode,section)
        else:
            self.active_sections[self._mode]=section
            for i in range(self.navigation.count()):
                if self.navigation.item(i).data(Qt.ItemDataRole.UserRole)==section:
                    blocker=QSignalBlocker(self.navigation)
                    self.navigation.setCurrentRow(i)
                    del blocker
                    break
            if section in ('coupled.optical-setup','coupled.electrical-setup'):
                nested_mode = 'optical' if section=='coupled.optical-setup' else 'electrical'
                self.select_section(self.nested_sections[nested_mode])
                return
            self.return_button.hide()
            self.nested_tabs.hide()
        tab=self.section_meta[section]
        self.title.setText(('Coupled · ' if embedded else '')+source_mode.title()+' simulation setup')
        self._update_context_title()
        self.purpose.setText(tab['title']+'  ·  '+tab.get('purpose',''))
        self.stack.setCurrentWidget(self.pages[section])
        if hasattr(self,'setup_flow'):
            self.setup_flow.sync_section()
        self.refresh()

    def _show_nested(self, mode, current):
        blocker=QSignalBlocker(self.nested_tabs)
        while self.nested_tabs.count():
            self.nested_tabs.removeTab(0)
        for tab in self._modes[mode]['tabs']:
            index=self.nested_tabs.addTab(tab['title'])
            self.nested_tabs.setTabData(index,tab['id'])
            if tab['id']==current:
                self.nested_tabs.setCurrentIndex(index)
        del blocker
        self.nested_tabs.show()

    def _nested_changed(self,index):
        if index>=0:
            self.select_section(self.nested_tabs.tabData(index))

    def select_object(self, ident):
        self.selected_object = ident
        device=self.store.device or {}
        for view in (self.shared_preview,self.top_preview,self.section_preview):
            view.set_device(device,ident)
        if hasattr(self,'setup_flow'):
            self.setup_flow.select_object(ident)

    def refresh(self,*_):
        if self.refreshing or not self._is_active_document():
            return
        self.refreshing=True
        try:
            self.engine_recovery.setVisible(self._mode in ('optical','coupled') and self.state.get('ui.optical.engine') != 's4')
            self.engine_recovery.setEnabled(not self.store.busy)
            for field in self.fields:
                field.refresh()
                field.set_horizontal(not hasattr(self,'setup_flow') and self.width()>=1400)
            for frame,card in self.cards:
                frame.setVisible(self.condition(card.get('visible_when')))
                frame.setEnabled(self.condition(card.get('enabled_when')))
            for row,field in self.table_rows:
                row.setVisible(self.condition(field.get('visible_when')))
            for grid,cards in self.page_grids:
                self._reflow_grid(grid,cards)
            for tables in self.tables_by_key.values():
                for table in tables:
                    table.refresh()
            device=self.store.device or {}
            selected=getattr(self,'selected_object','')
            section_y=self.state.get('ui.electrical.section_y_um',0.) or 0.
            optical_cell=self.state.get('settings.optical_unit_cell')
            for view in (self.shared_preview,self.top_preview,self.section_preview):
                view.cut_y=float(section_y)
                view.optical_unit_cell=optical_cell
                view.show_mesh=bool(self.state.get('ui.electrical.mesh_grid',False)) and getattr(self,'current_section','')=='electrical.mesh'
                view.set_device(device,selected)
            self.summary_title.setText({'optical':'Optical domain','electrical':'Finite electrical domain','coupled':'Shared simulation domains'}[self._mode])
            width,depth=device.get('width_um',0),device.get('depth_um',0)
            enabled_layers={obj['id'] for obj in device.get('layers',[]) if obj.get('enabled',True)}
            layer_count=len(enabled_layers)
            regions=[obj for obj in device.get('shapes',[]) if obj.get('enabled',True) and obj.get('layer_id') in enabled_layers]
            array_ids={obj['id'] for obj in device.get('pc_arrays',[])}
            array_regions=sum(obj.get('pc_array_id') in array_ids for obj in regions)
            lines=[f'Finite device  {_text(width)} × {_text(depth)} µm',
                   f'Finite geometry: {layer_count} enabled layer{"s" if layer_count!=1 else ""} · {len(regions):,} enabled region{"s" if len(regions)!=1 else ""}']
            if array_ids:
                lines.append(f'PC-array regions: {array_regions:,} · Other regions: {len(regions)-array_regions:,}')
            if self._mode!='electrical':
                from optical_unit_cell import pc_unit_cell,pc_unit_cell_issue
                pc_cell=pc_unit_cell(device)
                if pc_cell is not None:
                    selected_pitch=optical_cell.get('enabled') and all(math.isclose(optical_cell[key],pc_cell[key],rel_tol=1e-9)
                        for key in ('width_um','depth_um'))
                    complete_holes=sum(1 for shape in device.get('shapes',[])
                        if shape.get('enabled',True) and shape.get('material_id')=='air' and shape.get('operation')=='void'
                        and shape.get('shape')=='circle' and
                        abs(shape['cx_um']-optical_cell['cx_um'])+shape['size_x_um']/2<=optical_cell['width_um']/2+1e-10 and
                        abs(shape['cy_um']-optical_cell['cy_um'])+shape['size_y_um']/2<=optical_cell['depth_um']/2+1e-10)
                    valid_pc=selected_pitch and complete_holes==1 and pc_unit_cell_issue(optical_cell,device) is None
                    lines.append('Optical PC cell: 1 air hole' if valid_pc else 'Optical PC cell: configure a one-hole pitch cell')
                    lines.append('Full array shown in preview; S4 solves the optical cell.')
                if optical_cell.get('enabled'):
                    lines.append(f'Periodic cell  {_text(optical_cell.get("width_um"))} × {_text(optical_cell.get("depth_um"))} µm')
                else:
                    lines.append('Optical: periodically repeated full-footprint supercell')
                lines.append('S4 repeats the chosen domain in X and Y.')
            if self._mode!='optical':
                mesh=device.get('mesh',{})
                total=mesh.get('nx',0)*mesh.get('ny',0)*mesh.get('nz_per_layer',0)*layer_count
                lines.append(f'Finite mesh  {mesh.get("nx",0)} × {mesh.get("ny",0)} × {mesh.get("nz_per_layer",0)*layer_count} · {total:,} cells')
                lines.append(f'Temperature  {_text(device.get("temperature_K"))} K')
                lines.append('Voltage sweep  ' + self.state.get('ui.electrical.offset_summary'))
            self.summary.setText('\n\n'.join(lines))
            self.summary.setAccessibleName('Simulation domain summary')
            self.summary.setAccessibleDescription(self.summary.text())
            if hasattr(self,'setup_flow'):
                self.setup_flow.refresh()
        finally:
            self.refreshing=False

    def set_status(self,text,error=False):
        self.status.setText(text)
        self.status.setObjectName('setupError' if error else 'setupStatus')
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.statusChanged.emit(text)

    def commit_drafts(self):
        if not self._is_active_document():return
        committed=set()
        for field in self.fields:
            if field.key in self.drafts and field.key not in committed:
                if field.key=='ui.electrical.bias_list_text':
                    continue
                field.commit()
                committed.add(field.key)

    def _reset_project_drafts(self,reason):
        if not self._is_active_document():return
        if reason not in ('project','study'):return
        self.drafts.clear();self.draft_errors.clear();self.table_drafts.clear();self.table_errors.clear()
        saved=self.store.search_state.get('research_workspaces',{}).get('setup_pending',{}).get(self._mode,{})
        self.drafts.update(saved.get('drafts',{}));self.draft_errors.update(saved.get('errors',{}))
        self.table_drafts.update({tuple(row[0]):row[1] for row in saved.get('tables',[])})
        self.table_errors.update({tuple(row[0]):row[1] for row in saved.get('table_errors',[])})
        self._issue_return=None
        self.diagnostics.set_diagnostics([])
        self.refresh()

    def flush_draft(self):
        """Persist unfinished controls, including invalid text, per document."""
        if not self._is_active_document():return
        import copy
        namespace=copy.deepcopy(self.store.search_state.get('research_workspaces',{}))
        namespace.setdefault('schema_version',1)
        namespace.setdefault('setup_pending',{})[self._mode]=dict(drafts=copy.deepcopy(self.drafts),
            errors=copy.deepcopy(self.draft_errors),tables=[[list(key),value] for key,value in self.table_drafts.items()],
            table_errors=[[list(key),value] for key,value in self.table_errors.items()])
        self.store.save_search('research_workspaces',namespace)

    def validate_current(self):
        if not self._is_active_document():return False
        self.commit_drafts()
        schedule_issues=[]
        if self._mode in ('electrical','coupled'):
            try:
                # Run submits the visible voltage inputs, including edits made
                # since the last explicit list preview.
                target='electrical.generate_biases' if self.state.get('ui.electrical.sweep_mode')=='range' else 'electrical.parse_biases'
                if not any(key.startswith('ui.electrical.bias_') for key in self.draft_errors):self._bias_action(target)
            except (ValueError,TypeError,KeyError) as exc:
                schedule_issues.append(dict(key='ui.electrical.bias_list_text',message=str(exc),tab='electrical.study'))
        issues=list(self.state.validate(self._mode))
        issues[:0]=schedule_issues
        table_keys={address[0] for address in self.table_errors}
        for (key,ident,column),message in self.table_errors.items():
            if self._mode=='optical' and key.startswith('device.'):continue
            tab=next((tab['id'] for tab in self.section_meta.values() for card in tab.get('cards',[]) for field in card.get('fields',[]) if field.get('key')==key),'')
            issues.insert(0,dict(key=key,message=message,tab=tab,object_id=ident if key.startswith('device.') else '',column=column))
        for key,message in self.draft_errors.items():
            if key in table_keys:continue
            optical_key=key.startswith(('settings.','performance.','ui.optical.','search.simulation.','search.fdtd.'))
            electrical_key=key.startswith(('device.','ui.electrical.','search.electrical.'))
            if self._mode=='optical' and not optical_key or self._mode=='electrical' and not electrical_key:
                continue
            tab=next((tab['id'] for tab in self.section_meta.values() for card in tab.get('cards',[]) for field in card.get('fields',[]) if field.get('key')==key),'')
            issues.insert(0,dict(key=key,message=message,tab=tab))
        revision=self.input_revision()
        self.diagnostics.set_diagnostics(issues,workspace=self._mode,revision=revision)
        self.set_status(f'{len(issues)} blocking issue(s); select an issue to fix it.' if issues else 'Setup validated. Numerical convergence is checked after running.',error=bool(issues))
        return not issues

    validate_setup=validate_current

    def _open_issue(self,item):
        return self.open_diagnostic(item.data(Qt.ItemDataRole.UserRole))

    def input_revision(self):
        import hashlib
        payload=dict(project=self.store.project(),drafts=self.drafts,
            table_drafts=[(list(address),text) for address,text in self.table_drafts.items()])
        return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()[:16]

    def open_diagnostic(self,issue):
        issue=normalize_diagnostic(issue,workspace=self._mode)
        if issue.get('revision') and issue['revision']!=self.input_revision():
            self.validate_current()
            match=next((self.validation_list.item(i).data(Qt.ItemDataRole.UserRole)
                        for i in range(self.validation_list.count())
                        if self.validation_list.item(i).data(Qt.ItemDataRole.UserRole)['id']==issue['id']),None)
            if match is None:
                self.set_status('Inputs rechecked. That issue is resolved; choose a remaining issue if needed.')
                return False
            issue=match
        if self._issue_return is None:
            self._issue_return=dict(section=getattr(self,'current_section',''),
                row=self.validation_list.currentRow(),scroll=self.validation_list.verticalScrollBar().value())
        workspace=issue.get('workspace')
        if workspace not in ('',self._mode,'optical','electrical','coupled'):
            self.diagnosticRequested.emit(issue)
            return True
        section=issue.get('section','')
        if section and section not in self.pages:
            self.diagnosticRequested.emit(issue)
            return True
        if section:self.select_section(section)
        ident=issue.get('object_id')
        if ident:
            device=self.store.device or {}
            if not any(row.get('id')==ident for group in ('layers','shapes','contacts','doping_regions') for row in device.get(group,[])):
                self.validate_current()
                self.set_status('The referenced object was removed. Inputs have been rechecked.',error=True)
                return False
            self.select_object(ident)
        field=issue.get('field','')
        widgets=self.widgets_by_key.get(field,[]) or self.tables_by_key.get(field,[])
        widget=next((editor for editor in widgets if editor.isVisible()),widgets[0] if widgets else None)
        if isinstance(widget,QTableWidget) and ident:
            row=next((i for i,value in enumerate(getattr(widget,'_rows',[])) if isinstance(value,dict) and value.get('id')==ident),-1)
            if row>=0:
                column=int(issue.get('column',0))
                if 0<=column<widget.columnCount():
                    widget.setCurrentCell(row,column)
                    item=widget.item(row,column)
                    if item is not None:widget.scrollToItem(item)
                    widget=widget.cellWidget(row,column) or widget
        if widget is not None and reveal_and_focus(widget,message=issue['message']):
            widget.installEventFilter(self)
            self.set_status('Highlighted input: '+widget.accessibleName()+'. Press Escape to return to issues.')
            return True
        self.set_status('Opened the owning section. '+issue['message']+
            (' The field is unavailable for the current model; review its enabling choice.' if field and widget is not None else ''),error=True)
        return bool(section)

    def return_to_issues(self):
        token=self._issue_return
        self._issue_return=None
        if token and token['section'] in self.pages:
            self.select_section(token['section'])
        if self.validation_list.count():
            if token:
                self.validation_list.setCurrentRow(min(max(0,token['row']),self.validation_list.count()-1))
                self.validation_list.verticalScrollBar().setValue(token['scroll'])
            self.validation_list.setFocus()

    def eventFilter(self,watched,event):
        if self._issue_return is not None and event.type()==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_Escape:
            self.return_to_issues()
            return True
        return super().eventFilter(watched,event)

    def run(self):
        if self.validate_current():
            self.runRequested.emit(self._mode)

    def options(self):
        return self.state.job_options(self._mode)

    def perform_action(self,action):
        if not self._is_active_document():return
        target=action.get('target','')
        ident=action.get('id','')
        try:
            if ident=='coupled.output-standalone':
                # The host opens the independent optical document. Moving inputs
                # remains the explicit Transfer inputs action in that workspace.
                self.routeRequested.emit('optical.outputs')
            elif target in self.pages or '/' in target and target.split('/')[0] in self.pages:
                self.select_section(target)
            elif target.startswith(('global.','structure.','materials.','results.','engine.')) or target.startswith('settings.') and target not in ('settings.optical_unit_cell','settings.theta_deg'):
                self.routeRequested.emit(target)
            elif target in ('dialog.save-preset','dialog.export-setup'):
                self.save_setup()
            elif target=='dialog.load-preset':
                self.load_preset()
            elif target in ('electrical.validate_all','electrical.validate_biases','coupled.validate-all','optical.run-review','electrical.run_review'):
                self.validate_current()
                if 'review' in target:
                    self._review_setup()
            elif target=='ui.coupled.first_blocker.target':
                self.validate_current()
                if self.validation_list.count():
                    self._open_issue(self.validation_list.item(0))
            elif target in ('electrical.generate_biases','electrical.parse_biases'):
                self._bias_action(target)
            elif target=='electrical.add_bias_samples':
                self._additional_bias_dialog()
            elif target == 'electrical.transport_settings':
                from qt_transport_setup import TransportSetupDialog
                TransportSetupDialog(self).exec()
            elif target in ('electrical.contact_editor','electrical.doping_editor'):
                self._object_editor('contacts' if 'contact' in target else 'doping_regions','add' in ident)
            elif target in ('electrical.remove_contact','electrical.remove_region','electrical.region_up','electrical.region_down'):
                self._change_object(target)
            elif target=='electrical.material_editor':
                self._material_editor('custom' in ident)
            elif target in ('electrical.measured_import','electrical.legacy_current_import'):
                self._import_measured('cv' if 'cv' in ident else 'iv',legacy='legacy' in target)
            elif target in ('electrical.clear_iv','electrical.clear_cv'):
                self.state.set('search.electrical.terminal_studies.measured_'+('cv' if target.endswith('cv') else 'iv')+'_path','')
            elif target=='electrical.clear_sheet_current':
                self.state.set('search.electrical.measured_current',[])
            elif target=='electrical.set300':
                self.state.set('device.temperature_K',300.)
            elif target=='electrical.build_mesh':
                self.preview_mesh()
            elif target=='electrical.mesh_fit':
                self.fit_preview()
            elif target in ('ui.optical.runtime_status','ui.optical.meep_runtime_status','electrical.check_runtime'):
                self._runtime_check()
            elif target=='settings.optical_unit_cell':
                self._use_pc_cell(center='center-cell' in ident)
            elif target=='dialog.choose-pc-cell':
                self._pc_cell_dialog()
            elif target=='settings.theta_deg':
                self.state.set('settings.theta_deg',0.)
                self.state.set('settings.phi_deg',0.)
            elif target=='search.simulation.measure_phase':
                self.state.set(target,False)
            elif target=='performance.gpu_min_n':
                self.state.set(target,1)
            elif target=='ui.optical.outputs.execution_plan':
                self.state.set(target,'fields_only')
                self.select_section('optical.outputs')
                self.run()
            elif target=='ui.optical.sample_preview' or target=='ui.optical.material_validation':
                self.validate_current()
            elif target=='coupled.reference.midpoint':
                self.state.set('search.coupled.reference_nm',(float(self.state.get('settings.wl_start_nm'))+float(self.state.get('settings.wl_stop_nm')))/2)
            elif target=='coupled.outputs.set-policy':
                self.state.set('ui.coupled.unsupported_output_policy','supported_only')
            elif target=='coupled.mapping.auto-link':
                if hasattr(self.state,'auto_map'):
                    self.state.auto_map()
                else:
                    self.state.set('search.coupled.optical_mapping',[])
            elif target=='optical.sample-list':
                self._table_dialog('Actual optical samples','ui.optical.sample_preview')
            elif target in ('dialog.transfer-region-preview','dialog.slice-layout','optical.domain-inspector','dialog.transfer-profile-inspection'):
                self._domain_inspector(target)
            elif target in ('optical.choose-material','optical.edit-material','optical.import-nk'):
                self.routeRequested.emit('materials.optical')
            elif target in ('optical.choose-spectrum','dialog.choose-reference-feature'):
                self._choose_saved_spectrum(reference='reference' in target)
            elif target=='optical.basis-comparison':
                self._basis_dialog()
            elif target=='electrical.load_example':
                self.routeRequested.emit('structure.examples')
            else:
                raise ValueError('This action has no registered destination: '+target)
        except (ValueError,TypeError,KeyError,OSError,ImportError) as exc:
            self.set_status(str(exc),error=True)

    def _bias_action(self,target):
        self.commit_drafts()
        errors = [message for key, message in self.draft_errors.items() if key.startswith('ui.electrical.bias_')]
        if errors:
            raise ValueError(errors[0])
        if target=='electrical.parse_biases':
            raw=self.drafts.get('ui.electrical.bias_list_text',self.state.get('ui.electrical.bias_list_text',''))
            values=self.state.parse_biases(str(raw))
        elif target=='electrical.generate_biases':
            values=self.state.generate_biases()
        else:
            raise ValueError('Choose range generation or manual voltage offsets.')
        self.drafts.pop('ui.electrical.bias_list_text',None)
        self.draft_errors.pop('search.electrical.biases_V',None)
        self.set_status(f'Applied {len(values):,} distinct voltage states, including the zero-offset reference. Every state will be solved.')
        self.refresh()

    def _object_editor(self,group,add=False):
        rows=(self.store.device or {}).get(group,[])
        ident=self.selected_objects.get('device.'+group)
        if not ident and group=='contacts':
            ident=self.state.get('ui.electrical.selected_contact_id')
        original=next((row for row in rows if row['id']==ident),None)
        if not add and original is None:
            raise ValueError('Select a '+('contact' if group=='contacts' else 'doping region')+' to edit.')
        _ObjectDialog(self,group,None if add else original).exec()

    def _additional_bias_dialog(self):
        dialog=QDialog(self)
        dialog.setObjectName('setupAdditionalBiasDialog')
        dialog.setWindowTitle('Add intermediate bias samples')
        dialog.resize(540,300)
        layout=QVBoxLayout(dialog)
        layout.addWidget(_label('Enter additional voltage offsets. Apply merges them with the current schedule, removes duplicates and retains the zero-offset reference.'))
        editor=QPlainTextEdit()
        editor.setObjectName('setupAdditionalBiases')
        editor.setPlaceholderText('For example: -0.15, -0.05')
        layout.addWidget(editor,1)
        status=_label('','setupError')
        layout.addWidget(status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)
        def apply():
            try:
                current=self.state.get('search.electrical.biases_V',[]) or []
                raw=', '.join(_text(value) for value in current)+', '+editor.toPlainText()
                values=self.state.parse_biases(raw)
                manual=', '.join(_text(value) for value in values)
                self.state.set('ui.electrical.bias_list_text',manual)
                self.state.set('ui.electrical.sweep_mode','manual')
                self.drafts.pop('ui.electrical.bias_list_text',None)
                self.set_status(f'Applied {len(values)} unique bias states, including zero.')
                dialog.accept()
            except (ValueError,TypeError,KeyError) as exc:
                status.setText(str(exc))
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(apply)
        layout.addWidget(buttons)
        dialog.exec()

    def _change_object(self,target):
        group='contacts' if 'contact' in target else 'doping_regions'
        rows=deepcopy((self.store.device or {}).get(group,[]))
        ident=self.selected_objects.get('device.'+group)
        if not ident:
            raise ValueError('Select the row to change.')
        index=next(i for i,row in enumerate(rows) if row['id']==ident)
        if 'remove' in target:
            dialog=QDialog(self)
            dialog.setWindowTitle('Remove '+rows[index]['name'])
            layout=QVBoxLayout(dialog)
            layout.addWidget(_label('Remove this object from the current simulation device? Its ID will no longer resolve in saved setup references.'))
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Remove')
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec()!=QDialog.DialogCode.Accepted:
                return
            rows.pop(index)
        else:
            other=index+(-1 if target.endswith('up') else 1)
            if 0<=other<len(rows):
                rows[index],rows[other]=rows[other],rows[index]
        self.state.set('device.'+group,rows)

    def _material_editor(self,new=False):
        from electrical_material_library import merge_materials
        from qt_electrical_materials import ElectricalMaterialDialog
        ident=self.state.get('ui.electrical.selected_material_id')
        original=next((row for row in self.store.electrical_materials if row['id']==ident),None)
        dialog=ElectricalMaterialDialog(None if new else original,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            value=dialog.material()
            self.store.set_electrical_materials(merge_materials(self.store.electrical_materials,[value]))
            self.state.set('ui.electrical.selected_material_id',value['id'])

    def _import_measured(self,kind,legacy=False):
        filename,_=QFileDialog.getOpenFileName(self,'Import '+kind.upper()+' measurements','','CSV files (*.csv)')
        if not filename:
            return
        from electrical_terminal_studies import read_measured_csv
        frame=read_measured_csv(filename,kind)
        if legacy:
            self.state.set('search.electrical.measured_current',frame.to_dict('records') if hasattr(frame,'to_dict') else frame)
        else:
            self.state.set('search.electrical.terminal_studies.measured_'+kind+'_path',filename)
        self.set_status('Validated '+kind.upper()+' measurement columns and units. Measured data do not replace computed results.')

    def preview_mesh(self):
        try:
            mesh=self.state.build_mesh()
            cells=math.prod(mesh['shape'])
            self.state.set('ui.electrical.mesh_grid',True)
            self.select_section('electrical.mesh' if self._mode!='optical' else 'optical.domain')
            self.set_status(f'Actual finite mesh validated: {cells:,} cells. Numerical convergence is checked after solving.')
            return True
        except (ValueError,TypeError,KeyError) as exc:
            self.set_status(str(exc),error=True)
            return False

    def fit_preview(self):
        from PyQt6.QtCore import QPointF
        for view in (self.shared_preview,self.top_preview,self.section_preview):
            view.zoom=1.
            view.pan=QPointF(0.,0.)
            if view.mode=='3d':
                view.yaw=-.6
                view.elevation=.23
            view.update()
        self.set_status('Linked views fitted to the current simulation device.')

    def _runtime_check(self):
        engine='electrical' if self._mode=='electrical' else self.state.get('ui.optical.engine','s4')
        result=self.state.check_runtime(engine)
        self.set_status(result.get('message','Runtime check complete.'),error=not result.get('available',False))

    def _use_pc_cell(self,center=False,pc_id=None):
        device=self.store.device or {}
        areas=device.get('pc_arrays',device.get('pc_areas',[]))
        if not areas:
            area=device.get('pc_array',{})
            areas=[area] if area else []
        if not center and pc_id is None and hasattr(self.state,'use_pc_lattice'):
            self.state.use_pc_lattice()
            return
        if not areas:
            raise ValueError('Define a PC array in Structure before copying its lattice pitch.')
        area=next((row for row in areas if row.get('id')==pc_id),None) if pc_id else next((row for row in reversed(areas) if row.get('enabled',True)),None)
        if area is None:
            raise ValueError('Select an enabled PC area.')
        cell=dict(self.state.get('settings.optical_unit_cell'))
        cell.update(cx_um=area.get('cx_um',0.),cy_um=area.get('cy_um',0.))
        if not center:
            holes=[row for row in device.get('shapes',[]) if row.get('pc_array_id')==area['id'] and row.get('enabled',True)]
            nearest=min(holes,key=lambda row:(row['cx_um']-cell['cx_um'])**2+(row['cy_um']-cell['cy_um'])**2) if holes else area
            cell.update(width_um=area.get('cell_width_um',area.get('pitch_x_um',area.get('pitch_um'))),
                depth_um=area.get('cell_depth_um',area.get('pitch_y_um',area.get('pitch_um'))),
                cx_um=nearest['cx_um'],cy_um=nearest['cy_um'],enabled=True)
        self.state.set('settings.optical_unit_cell',cell)

    def _pc_cell_dialog(self):
        areas=[row for row in (self.store.device or {}).get('pc_arrays',[]) if row.get('enabled',True)]
        dialog=QDialog(self)
        dialog.setWindowTitle('Choose PC lattice for optical cell')
        dialog.resize(520,260)
        layout=QVBoxLayout(dialog)
        layout.addWidget(_label('Choose the patterned PC area. Its lattice dimensions and nearest central hole define the periodic optical cell; finite device dimensions stay unchanged.'))
        choice=QComboBox()
        for row in areas:
            choice.addItem(row.get('name',row['id']),row['id'])
        layout.addWidget(choice)
        status=_label('' if areas else 'Create an enabled PC area in Structure first.','setupError')
        layout.addWidget(status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).setEnabled(bool(areas))
        buttons.rejected.connect(dialog.reject)
        def apply():
            try:
                self._use_pc_cell(pc_id=choice.currentData())
                dialog.accept()
            except (ValueError,TypeError,KeyError) as exc:
                status.setText(str(exc))
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(apply)
        layout.addWidget(buttons)
        dialog.exec()

    def setup_review_rows(self):
        """Read applied values and unfinished text without committing or solving."""
        rows=[]
        if self._mode in ('optical','coupled'):
            device=self.store.device or {}
            source=getattr(self.store,'optical_geometry_source','device')
            rows.append(('Applied geometry source','Device editor' if source=='device' else 'Original optical tables'))
            if source=='device':
                rows.append(('Applied finite footprint',f"{_text(device.get('width_um'))} × {_text(device.get('depth_um'))} µm"))
                layers=[row for row in device.get('layers',[]) if row.get('enabled',True)]
                active={row['id']:row for row in layers}
                assignments={row['id']:row.get('optical_material') or 'Not assigned'
                    for row in self.state.get('ui.optical.assignment_rows',[])}
                for layer in layers[:100]:
                    rows.append(('Applied layer: '+layer['name'],
                        f"{_text(layer['thickness_um'])} µm · {assignments.get(layer['id'],'Not resolved')}"))
                regions=[row for row in device.get('shapes',[]) if row.get('enabled',True) and row.get('layer_id') in active]
                for region in regions[:100]:
                    shape=region.get('shape','region')
                    size=(f"diameter {_text(region.get('size_x_um'))} µm" if shape=='circle' else
                        f"full size {_text(region.get('size_x_um'))} × {_text(region.get('size_y_um'))} µm")
                    rows.append(('Applied region: '+region['name'],f"{shape} · {size} · "
                        f"center ({_text(region.get('cx_um'))}, {_text(region.get('cy_um'))}) µm · "
                        f"{active[region['layer_id']]['name']} · {assignments.get(region['id'],'Not resolved')}"))
                if len(layers)>100 or len(regions)>100:
                    rows.append(('Geometry review extent',f'{len(layers)} enabled layers and {len(regions)} enabled regions; first100 of each shown. Inspect the remaining objects in Device.'))
            else:
                assignments={}
                for layer in self.store.layers.to_dict('records')[1:-1]:
                    rows.append(('Applied layer: '+str(layer.get('Name','')),f"{_text(layer.get('Thickness_um'))} µm · {layer.get('Material','Not assigned')}"))
            incident=self.state.get('ui.optical.incident_material')
            exit_material=self.state.get('ui.optical.exit_material')
            rows.extend([('Applied incident medium',str(incident)),('Applied exit medium',str(exit_material))])
            used={incident,exit_material,*assignments.values()}
            if source!='device':
                used.update(self.store.layers['Material'].tolist())
                used.update(self.store.patterns['Material'].tolist())
            for material in self.store.materials.to_dict('records'):
                if material.get('Name') not in used:continue
                model=material.get('Model')
                if model=='constant_nk':value=f"n = {_text(material.get('A'))} · k = {_text(material.get('B'))} (constant)"
                elif model=='constant_eps':value=f"ε real = {_text(material.get('A'))} · ε imaginary = {_text(material.get('B'))} (constant)"
                else:value='Tabulated n,k · '+Path(str(material.get('DataFile',''))).name
                rows.append(('Applied material: '+material['Name'],value))
            for label,key in [('Applied optical domain','ui.optical.compiled_domain_extent'),
                ('Applied boundary rule','ui.optical.periodic_boundary_text'),
                ('Applied sample count','ui.optical.compiled_samples'),
                ('Applied first sample','ui.optical.first_sample'),
                ('Applied last sample','ui.optical.actual_last_sample')]:
                rows.append((label,self.display_value(key,self.state.get(key))))
        keys=set()
        modes=('optical','electrical','coupled') if self._mode=='coupled' else (self._mode,)
        for mode in modes:
            for tab in self._modes[mode]['tabs']:
                for card in tab.get('cards',[]):
                    if not self.condition(card.get('visible_when')):continue
                    for field in card.get('fields',[]):
                        key=field['key']
                        if key in keys or field['widget'] in ('readonly','table') or not self.condition(field.get('visible_when')):
                            continue
                        keys.add(key)
                        applied=self.display_value(key,self.state.get(key))
                        unit=' '+str(field['unit']) if field.get('unit') else ''
                        value=applied+unit
                        if key in self.drafts:
                            value=f'Draft (not applied): {self.drafts[key]}{unit} · Applied: {value}'
                        if key in self.draft_errors:value+=' · Invalid: '+self.draft_errors[key]
                        rows.append((field['label'],value))
        # Table edits also remain drafts until their existing Apply action.
        for (key,ident,column),raw in self.table_drafts.items():
            if not any(key==field.get('key') for mode in modes for tab in self._modes[mode]['tabs']
                for card in tab.get('cards',[]) for field in card.get('fields',[])):continue
            name=next((obj.get('name') for group in ('layers','shapes','contacts','doping_regions')
                for obj in (self.store.device or {}).get(group,[]) if obj.get('id')==ident),'table row')
            rows.append(('Draft table edit: '+str(name),f'{column}: {raw} (not applied)'))
        return rows

    def _review_setup(self):
        dialog=QDialog(self)
        dialog.setWindowTitle(self._mode.title()+' setup review')
        dialog.resize(900,720)
        layout=QVBoxLayout(dialog)
        layout.addWidget(_label('Read-only review. Geometry and values marked Applied are committed inputs. Draft text is shown separately and is not applied by opening this review. This is not validation or a solver result.'))
        table=QTableWidget()
        table.setAccessibleName('Current simulation inputs review')
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(['Setting','Current value'])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().hide()
        rows=self.setup_review_rows()
        table.setRowCount(len(rows))
        for row,values in enumerate(rows):
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row,column,item)
        layout.addWidget(table)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _table_dialog(self,title,key):
        dialog=QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(850,620)
        layout=QVBoxLayout(dialog)
        original=next((table.field for table in self.tables_by_key.get(key,[])),None)
        if original:
            table=_PlanTable(self,original,parent=dialog)
            table.setMaximumHeight(10000)
            layout.addWidget(table,1)
        else:
            layout.addWidget(_label(_text(self.state.get(key))))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        if original:
            self.tables_by_key[key].remove(table)

    def _domain_inspector(self,target):
        if target=='dialog.transfer-profile-inspection':
            self.routeRequested.emit('results.profiles')
            return
        dialog=QDialog(self)
        dialog.setWindowTitle('Optical domain and depth slices')
        dialog.resize(700,560)
        layout=QVBoxLayout(dialog)
        view=DeviceCanvas('section' if target=='dialog.slice-layout' else 'top')
        view.set_device(self.store.device or {})
        view.optical_unit_cell=self.state.get('settings.optical_unit_cell')
        layout.addWidget(view,1)
        layout.addWidget(_label('Geometry preview only. The optical domain repeats periodically. Electrical fields are averaged over solid material inside this domain.'))
        layout.addWidget(_label('Slices per layer: '+_text(self.state.get('search.coupled.optical_slices_per_layer'))))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _choose_saved_spectrum(self,reference=False):
        entries=self.saved_spectrum_choices(reference=reference)
        dialog=QDialog(self)
        dialog.setObjectName('setupSavedSpectrumDialog')
        dialog.setWindowTitle('Choose sampled '+str(self.state.get('search.coupled.feature','Peak')).lower() if reference else 'Choose saved spectrum')
        dialog.resize(820,620)
        layout=QVBoxLayout(dialog)
        listing=QListWidget()
        listing.setObjectName('setupSavedSpectrumList')
        listing.setMaximumHeight(190)
        for entry in entries:
            item=QListWidgetItem(str(entry.get('title',entry.get('id','Saved run'))))
            item.setData(Qt.ItemDataRole.UserRole,entry)
            listing.addItem(item)
        layout.addWidget(listing,1)
        samples=QTableWidget()
        samples.setObjectName('setupSavedSpectrumSamples')
        samples.setColumnCount(6)
        samples.setHorizontalHeaderLabels(['Wavelength (nm)','Angle (°)','Bias (V)','R','T','A'])
        samples.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        samples.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        samples.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        samples.verticalHeader().hide()
        layout.addWidget(samples,2)
        status=_label('Select a saved spectrum, then choose an actual sampled feature.' if reference else 'Choose a completed compatible spectrum.' if entries else 'No completed optical spectrum is saved. Run an optical spectrum first.')
        layout.addWidget(status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
        apply=buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply.setEnabled(False)
        selected_rows=[]
        def load_samples(current,previous):
            selected_rows.clear()
            samples.setRowCount(0)
            apply.setEnabled(False)
            if current is None:
                return
            try:
                frame,limited=self.saved_spectrum_frame(current.data(Qt.ItemDataRole.UserRole),reference=reference)
                records=frame.to_dict('records')
                if reference:
                    records=self.sampled_reference_candidates(records)
                selected_rows.extend(records[:1000] if reference else records[:300])
                samples.setRowCount(len(selected_rows))
                for row,record in enumerate(selected_rows):
                    for col,key in enumerate(('wavelength_nm','angle_deg','bias_V','R','T','A')):
                        item=QTableWidgetItem(_text(record.get(key)))
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        samples.setItem(row,col,item)
                if reference:
                    status.setText(f'{len(records):,} sampled '+str(self.state.get('search.coupled.feature','Peak')).lower()+' candidate(s). Choose a row to set the tracking reference.' if records else 'No resolved sampled feature in this spectrum. Choose another run or enter the reference wavelength in Response tracking.')
                else:
                    status.setText(f'{len(frame):,} saved samples; the table previews the first 300. Apply uses this run as the field spectrum source.')
                    apply.setEnabled(bool(records))
                if limited:
                    status.setText(status.text()+' Inspection reads the first 100,000 actual samples; full saved data remain unchanged.')
            except (ValueError,TypeError,KeyError,OSError) as exc:
                status.setText(str(exc))
        listing.currentItemChanged.connect(load_samples)
        samples.currentCellChanged.connect(lambda row,*_:apply.setEnabled(row>=0 and row<len(selected_rows)) if reference else None)
        buttons.rejected.connect(dialog.reject)
        def accept():
            entry=listing.currentItem().data(Qt.ItemDataRole.UserRole)
            if reference:
                row=samples.currentRow()
                if row<0 or row>=len(selected_rows):
                    return
                wavelength=float(selected_rows[row]['wavelength_nm'])
                self.state.set('search.coupled.reference_nm',wavelength)
                self.set_status(f'Tracking reference set to the actual saved sample at {wavelength:g} nm.')
            else:
                self.state.set('ui.optical.outputs.selected_spectrum_id',entry.get('id',''))
                self.state.set('ui.optical.outputs.field_spectrum_source','saved')
                self.set_status('Field spectrum source selected: '+str(entry.get('title',entry['id'])))
            dialog.accept()
        apply.clicked.connect(accept)
        layout.addWidget(buttons)
        dialog.exec()

    def saved_spectrum_choices(self,reference=False):
        choices=[]
        for entry in self.store.library.entries():
            if entry.get('status') in ('error','failed','running','cancelled','cancelling'):
                continue
            try:
                directory=self.store.library.directory(entry['id'])
            except (ValueError,OSError):
                continue
            if (directory/'results.csv').is_file() or reference and (directory/'electrical_optical_spectra.csv').is_file():
                if reference or entry.get('kind') in ('simulation','optical','coupled'):
                    choices.append(entry)
        return choices

    def saved_spectrum_frame(self,entry,reference=False):
        import pandas as pd
        directory=self.store.library.directory(entry['id'])
        if reference and (directory/'electrical_optical_spectra.csv').is_file():
            frame=pd.read_csv(directory/'electrical_optical_spectra.csv',nrows=100001)
        elif (directory/'spectrum.sqlite').is_file():
            from scan_storage import SpectrumResults
            frame=SpectrumResults(directory/'spectrum.sqlite').frame(limit=100001)
        else:
            frame=pd.read_csv(directory/'results.csv',nrows=100001)
        if not {'wavelength_nm','R','T','A'} <= set(frame.columns):
            raise ValueError('This saved file does not contain wavelength-resolved R, T and A.')
        limited=len(frame)>100000
        return frame.iloc[:100000],limited

    def sampled_reference_candidates(self,records):
        # Use the backend's exact strict-left/non-strict-right feature rule.
        column={'Reflection':'R','Transmission':'T','Absorption':'A'}[self.state.get('search.coupled.response','Absorption')]
        sign=1 if self.state.get('search.coupled.feature','Peak')=='Peak' else -1
        groups={}
        for row in records:
            wavelength=float(row['wavelength_nm'])
            value=float(row[column])
            if math.isfinite(wavelength) and math.isfinite(value):
                groups.setdefault((row.get('bias_V'),row.get('angle_deg')),[]).append(row)
        found=[]
        for rows in groups.values():
            rows.sort(key=lambda row:float(row['wavelength_nm']))
            for index in range(1,len(rows)-1):
                left,middle,right=rows[index-1:index+2]
                if sign*float(middle[column])>sign*float(left[column]) and sign*float(middle[column])>=sign*float(right[column]):
                    found.append(middle)
        return sorted(found,key=lambda row:float(row['wavelength_nm']))

    def _basis_dialog(self):
        dialog=QDialog(self)
        dialog.setWindowTitle('Compare Fourier basis settings')
        form=QVBoxLayout(dialog)
        form.addWidget(_label('Run two independent optical simulations with different Fourier basis counts, then compare their saved spectra in Results. No convergence claim is made before both runs finish.'))
        editor=QLineEdit(_text(self.state.get('settings.NumG')))
        form.addWidget(editor)
        status=_label('','setupError')
        form.addWidget(status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
        def apply():
            try:
                value=int(editor.text())
                if not 1<=value<=4096:
                    raise ValueError('Fourier basis count must be between 1 and 4096.')
                self.state.set('settings.NumG',value)
                dialog.accept()
            except ValueError as exc:
                status.setText(str(exc))
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(apply)
        buttons.rejected.connect(dialog.reject)
        form.addWidget(buttons)
        dialog.exec()

    def save_setup(self):
        self.commit_drafts()
        dialog=QDialog(self)
        dialog.setWindowTitle('Save simulation setup preset')
        dialog.resize(540,250)
        layout=QVBoxLayout(dialog)
        form=QFormLayout()
        name=QLineEdit(self._mode.title()+' setup')
        scope=QComboBox()
        for value in ('optical','electrical','coupled'):
            scope.addItem(value.title(),value)
        scope.setCurrentIndex(scope.findData(self._mode))
        form.addRow('Preset name',name)
        form.addRow('Setup scope',scope)
        layout.addLayout(form)
        layout.addWidget(_label('Stores this simulation’s solver settings and device references. Coupled includes its electrical and optical setups and transfer controls.'))
        status=_label('','setupError')
        layout.addWidget(status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)
        def save():
            if not name.text().strip():
                status.setText('Enter a preset name.')
                return
            filename,_=QFileDialog.getSaveFileName(dialog,'Save setup preset',name.text().strip()+'.json','Simulation setup (*.json)')
            if not filename:
                return
            try:
                if not hasattr(self.state,'export_preset'):
                    raise ValueError('Preset persistence is unavailable.')
                payload=self.state.export_preset(scope.currentData())
                payload['name']=name.text().strip()
                payload['drafts']=deepcopy(self.drafts)
                payload['draft_errors']=deepcopy(self.draft_errors)
                Path(filename).write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')
                self.set_status('Saved setup preset: '+name.text().strip())
                dialog.accept()
            except (ValueError,OSError) as exc:
                status.setText(str(exc))
        buttons.accepted.connect(save)
        layout.addWidget(buttons)
        dialog.exec()

    def load_preset(self):
        filename,_=QFileDialog.getOpenFileName(self,'Load simulation setup preset','','Simulation setup (*.json)')
        if not filename:
            return
        try:
            payload=json.loads(Path(filename).read_text(encoding='utf-8'))
            from optical_ui_scope import require_s4_preset
            require_s4_preset(payload)
            if not hasattr(self.state,'import_preset'):
                raise ValueError('Preset persistence is unavailable.')
            dialog=QDialog(self)
            dialog.setWindowTitle('Review setup preset')
            dialog.resize(700,550)
            layout=QVBoxLayout(dialog)
            layout.addWidget(_label('Review the setup changes before applying. Simulation device geometry will be retained.'))
            review=QTableWidget()
            review.setColumnCount(3)
            review.setHorizontalHeaderLabels(['Setting','Current','Preset'])
            review.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            review.verticalHeader().hide()
            layout.addWidget(review,1)
            remap_form=QFormLayout()
            layout.addLayout(remap_form)
            status=_label('','setupError')
            layout.addWidget(status)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
            buttons.rejected.connect(dialog.reject)
            apply_button=buttons.button(QDialogButtonBox.StandardButton.Apply)
            def refresh_review():
                preview=self.state.preview_preset(payload)
                changes=preview.get('changes',[])
                review.setRowCount(len(changes))
                for row,change in enumerate(changes):
                    key=change['key']
                    label=next((field.field.get('label',key) for field in self.fields if field.key==key),key.split('.')[-1].replace('_',' ').title())
                    for col,value in enumerate((label,_text(change['before']),_text(change['after']))):
                        item=QTableWidgetItem(value)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        review.setItem(row,col,item)
                errors=preview.get('errors',[])
                status.setText('\n'.join(errors))
                apply_button.setEnabled(not errors)
            device=self.store.device or {}
            contacts=device.get('contacts',[])
            layers=device.get('layers',[])
            swept=payload.get('electrical',{}).get('swept_contact_id')
            if swept and swept not in {row['id'] for row in contacts}:
                contact=QComboBox()
                contact.addItem('Choose current device terminal…','')
                for row in contacts:
                    contact.addItem(row['name'],row['id'])
                remap_form.addRow('Map preset swept terminal',contact)
                def remap_contact(_):
                    value=contact.currentData()
                    if value:
                        payload['electrical']['swept_contact_id']=value
                        payload.setdefault('values',{})['ui.electrical.selected_contact_id']=value
                    refresh_review()
                contact.currentIndexChanged.connect(remap_contact)
            mapping=payload.get('coupled',{}).get('optical_mapping',{})
            for source in list(mapping):
                if source in {row['id'] for row in layers}:
                    continue
                editor=QComboBox()
                editor.addItem('Choose current device layer…','')
                for row in layers:
                    editor.addItem(row['name'],row['id'])
                remap_form.addRow('Map preset layer '+source,editor)
                old=[source]
                def remap_layer(_,control=editor,previous=old):
                    value=control.currentData()
                    if value:
                        if value in mapping and value!=previous[0]:
                            status.setText('Each preset layer must map to a different device layer.')
                            apply_button.setEnabled(False)
                            return
                        mapping[value]=mapping.pop(previous[0])
                        previous[0]=value
                    refresh_review()
                editor.currentIndexChanged.connect(remap_layer)
            refresh_review()
            def apply():
                try:
                    self.state.import_preset(payload)
                    self.drafts=deepcopy(payload.get('drafts',{}))
                    self.draft_errors=deepcopy(payload.get('draft_errors',{}))
                    self.refresh()
                    self.set_status('Loaded setup preset: '+payload.get('name',Path(filename).stem))
                    dialog.accept()
                except (ValueError,TypeError,KeyError) as exc:
                    status.setText(str(exc))
            apply_button.clicked.connect(apply)
            layout.addWidget(buttons)
            dialog.exec()
        except (ValueError,OSError) as exc:
            self.set_status(str(exc),error=True)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'setup_flow'):
            self.setup_flow.adapt_layout()
            return
        narrow=self.width()<1300
        self.nav_panel.setFixedWidth(195 if narrow else 232)
        self.rail_scroll.setFixedWidth(285 if narrow else 420)
        for grid,cards in self.page_grids:
            self._reflow_grid(grid,cards)
        for field in self.fields:
            field.set_horizontal(self.width()>=1400)

    def adapt_layout(self):
        if hasattr(self,'setup_flow'):
            self.setup_flow.adapt_layout()

