"""Native, shared-structure range editors for the desktop optimizer."""
from __future__ import annotations

import copy

from PyQt6.QtCore import Qt, QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from bounds_editor import (BOUND_COLS, CATEGORICAL, HOLE_COLS, PARAMETERS, bound_label,
    finite_layers, names, prune_bounds, range_key, rows, target_choices, upsert_bound)
from model import PAT_COLS
from structure_sync import initial_hole_sync, sync_hole_ranges
from qt_common import CompactDoubleSpinBox


def _number(value=0., minimum=-1e9, maximum=1e9, decimals=6):
    control = CompactDoubleSpinBox()
    control.setDecimals(decimals)
    control.setRange(minimum, maximum)
    control.setValue(value)
    control.setSingleStep(.01)
    control.setKeyboardTracking(False)
    return control


def _choices(control, values, current=None):
    control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    control.setMinimumContentsLength(12)
    with QSignalBlocker(control):
        control.clear()
        for label, value in values:
            control.addItem(str(label), value)
        selected = control.findData(current)
        control.setCurrentIndex(selected if selected >= 0 else (0 if values else -1))


def _table(headers):
    control = QTableWidget(0, len(headers))
    control.setHorizontalHeaderLabels(headers)
    control.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    control.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    control.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    control.setWordWrap(False)
    control.setTextElideMode(Qt.TextElideMode.ElideRight)
    control.verticalHeader().hide()
    control.verticalHeader().setDefaultSectionSize(max(32,control.fontMetrics().height()+12))
    control.horizontalHeader().setStretchLastSection(True)
    control.setMinimumHeight(160)
    return control


def _form(parent=None):
    layout=QFormLayout(parent)
    layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    layout.setHorizontalSpacing(12)
    layout.setVerticalSpacing(8)
    return layout


class BoundsEditor(QWidget):
    """Editable optimization bounds; targets always come from the current project."""
    changed = pyqtSignal()

    def __init__(self, store, allowed=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.allowed = allowed
        self._rows = []
        self._patterns = rows(store.patterns, PAT_COLS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = _form()
        self.parameter = QComboBox()
        _choices(self.parameter, [(label, key) for label, key in PARAMETERS if allowed is None or key in allowed])
        self.target = QComboBox()
        self.minimum, self.maximum, self.step = _number(.1), _number(.2), _number(.01, .000000001, decimals=9)
        self.numeric = QWidget()
        numeric_form = _form(self.numeric)
        numeric_form.setContentsMargins(0, 0, 0, 0)
        self.min_label, self.max_label, self.step_label = QLabel('Minimum (µm)'), QLabel('Maximum (µm)'), QLabel('Step (µm)')
        for label, control in ((self.min_label, self.minimum), (self.max_label, self.maximum), (self.step_label, self.step)):
            numeric_form.addRow(label, control)
        self.materials = QListWidget()
        self.materials.setMaximumHeight(150)
        self.materials_label = QLabel('Allowed materials')
        form.addRow('Parameter', self.parameter)
        form.addRow('Layer / region', self.target)
        form.addRow(self.numeric)
        form.addRow(self.materials_label, self.materials)
        layout.addLayout(form)
        self.hint = QLabel('Unlisted parameters keep their applied Structure values. Equal limits fix a parameter.')
        self.hint.setWordWrap(True)
        self.hint.setObjectName('muted')
        layout.addWidget(self.hint)
        actions = QHBoxLayout()
        self.add = QPushButton('Save range')
        self.remove = QPushButton('Remove range')
        self.remove.setEnabled(False)
        actions.addWidget(self.add)
        actions.addWidget(self.remove)
        layout.addLayout(actions)
        self.overview = _table(['Saved design ranges'])
        layout.addWidget(self.overview)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.parameter.currentIndexChanged.connect(self._refresh_controls)
        self.add.clicked.connect(self.add_range)
        self.remove.clicked.connect(self.remove_range)
        self.overview.itemSelectionChanged.connect(self.load_selected)
        store.changed.connect(self.refresh)
        self._refresh_controls()

    def records(self):
        return copy.deepcopy(self._rows)

    def validated_records(self, value):
        result = []
        for row in rows(value, BOUND_COLS):
            if self.allowed is not None and row['Parameter'] not in self.allowed:
                raise ValueError('This search does not accept the parameter ' + str(row['Parameter']))
            result = upsert_bound(result, row['Parameter'], row['Target'], row['Min'], row['Max'], row['Step'],
                self.store.materials, self.store.layers, self.store.patterns,
                [item for item in str(row.get('Choices') or '').split(';') if item]).to_dict('records')
        return result

    def set_records(self, value):
        self._rows = self.validated_records(value)
        self._draw()
        self.changed.emit()

    def _selected_key(self):
        row = self.overview.currentRow()
        item = self.overview.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _draw(self, selected=None):
        selected = selected if selected is not None else self._selected_key()
        with QSignalBlocker(self.overview):
            self.overview.setRowCount(len(self._rows))
            self.overview.clearSelection()
            self.overview.setCurrentCell(-1, -1)
            for index, row in enumerate(self._rows):
                item = QTableWidgetItem(bound_label(row, self.store.layers, self.store.patterns))
                item.setData(Qt.ItemDataRole.UserRole, range_key(row))
                self.overview.setItem(index, 0, item)
                if range_key(row) == selected:
                    self.overview.setCurrentCell(index, 0)
        self.remove.setEnabled(self._selected_key() is not None)

    def _refresh_controls(self, *_):
        parameter = self.parameter.currentData()
        _choices(self.target, target_choices(parameter, self.store.layers, self.store.patterns), self.target.currentData())
        categorical = parameter in CATEGORICAL
        self.numeric.setVisible(not categorical)
        self.materials.setVisible(categorical)
        self.materials_label.setVisible(categorical)
        selected = self.selected_materials()
        self.materials.clear()
        for name in names(self.store.materials):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in selected else Qt.CheckState.Unchecked)
            self.materials.addItem(item)
        unit = 'degrees' if parameter == 'rotation' else 'r/a' if parameter == 'r_over_a' else 'µm'
        self.min_label.setText(f'Minimum ({unit})')
        self.max_label.setText(f'Maximum ({unit})')
        self.step_label.setText(f'Step ({unit})')
        self.add.setEnabled(self.target.count() > 0)

    def selected_materials(self):
        return [self.materials.item(i).text() for i in range(self.materials.count())
                if self.materials.item(i).checkState() == Qt.CheckState.Checked]

    def add_range(self):
        try:
            self._rows = upsert_bound(self._rows, self.parameter.currentData(), self.target.currentData(),
                self.minimum.value(), self.maximum.value(), self.step.value(), self.store.materials,
                self.store.layers, self.store.patterns, self.selected_materials()).to_dict('records')
        except ValueError as exc:
            self.status.setText(str(exc))
            return False
        key = range_key({'Parameter': self.parameter.currentData(), 'Target': self.target.currentData()})
        self._draw(key)
        self.status.setText('Range saved. The next search uses these limits.')
        self.changed.emit()
        return True

    def load_selected(self):
        key = self._selected_key()
        self.remove.setEnabled(key is not None)
        row = next((r for r in self._rows if range_key(r) == key), None)
        if row is None:
            return
        self.parameter.setCurrentIndex(self.parameter.findData(row['Parameter']))
        self._refresh_controls()
        self.target.setCurrentIndex(self.target.findData(str(row.get('Target') or '')))
        if row['Parameter'] in CATEGORICAL:
            chosen = str(row['Choices']).split(';')
            for i in range(self.materials.count()):
                item = self.materials.item(i)
                item.setCheckState(Qt.CheckState.Checked if item.text() in chosen else Qt.CheckState.Unchecked)
        else:
            for widget, key in ((self.minimum, 'Min'), (self.maximum, 'Max'), (self.step, 'Step')):
                widget.setValue(float(row[key]))

    def remove_range(self):
        key = self._selected_key()
        if key is None:
            return
        self._rows = [r for r in self._rows if range_key(r) != key]
        self._draw()
        self.status.setText('Range removed.')
        self.changed.emit()

    def refresh(self, reason=None):
        patterns = rows(self.store.patterns, PAT_COLS)
        data, removed = prune_bounds(self._rows, self.store.materials, self.store.layers,
            self.store.patterns, patterns_changed=patterns != self._patterns)
        self._patterns = patterns
        self._rows = data.to_dict('records')
        self._refresh_controls()
        self._draw()
        if removed:
            self.status.setText(f'{removed} range(s) removed after a Structure edit. Select the current layer or region to set its limits.')
            if reason != 'project':
                self.changed.emit()

    def populate_current(self):
        values = []
        s = self.store.settings
        ax, ay = float(s['ax_um']), float(s['ay_um'])
        if ax == ay:
            values.append(['lattice_square', '', ax, ax, .01, ''])
        else:
            values.extend([['lattice_x', '', ax, ax, .01, ''], ['lattice_y', '', ay, ay, .01, '']])
        for row in self.store.layers.to_dict('records')[1:-1]:
            values.append(['thickness', row['Name'], row['Thickness_um'], row['Thickness_um'], .01, ''])
            values.append(['layer_material', row['Name'], None, None, None, row['Material']])
        for index, row in enumerate(self.store.patterns.to_dict('records'), 1):
            if row['Shape'] == 'circle':
                values.append(['radius', str(index), row['SizeX_um'], row['SizeX_um'], .005, ''])
            else:
                for key, field in [('size_x', 'SizeX_um'), ('size_y', 'SizeY_um')]:
                    values.append([key, str(index), row[field], row[field], .005, ''])
            values.append(['pattern_material', str(index), None, None, None, row['Material']])
        self.set_records([dict(zip(BOUND_COLS, row)) for row in values if self.allowed is None or row[0] in self.allowed])
        self.status.setText('Current sizes added as fixed limits. Select a row and widen its limits to vary it.')


class HoleEditor(QWidget):
    """One air-hole range per PCS layer, retaining explicitly entered limits."""
    changed = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        data, self._sync = initial_hole_sync(store.materials, store.layers, store.patterns)
        self._rows = data.to_dict('records')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = _form()
        self.layer, self.shape = QComboBox(), QComboBox()
        _choices(self.shape, [('Circle', 'circle'), ('Ellipse', 'ellipse'), ('Rectangle', 'rectangle')])
        self.min_x, self.max_x = _number(.08, .000001), _number(.15, .000001)
        self.min_y, self.max_y = _number(.08, .000001), _number(.15, .000001)
        self.min_x_label, self.max_x_label = QLabel(), QLabel()
        self.y_row = QWidget()
        yform = _form(self.y_row)
        yform.setContentsMargins(0, 0, 0, 0)
        self.min_y_label, self.max_y_label = QLabel(), QLabel()
        yform.addRow(self.min_y_label, self.min_y)
        yform.addRow(self.max_y_label, self.max_y)
        form.addRow('PCS layer', self.layer)
        form.addRow('Air-hole shape', self.shape)
        form.addRow(self.min_x_label, self.min_x)
        form.addRow(self.max_x_label, self.max_x)
        form.addRow(self.y_row)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.add = QPushButton('Save hole range')
        self.remove = QPushButton('Remove range')
        actions.addWidget(self.add)
        actions.addWidget(self.remove)
        layout.addLayout(actions)
        self.overview = _table(['Layer', 'Shape', 'X min (µm)', 'X max (µm)', 'Y min (µm)', 'Y max (µm)'])
        layout.addWidget(self.overview)
        self.status = QLabel('Single air holes follow Structure edits. Entered min/max limits are preserved.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.shape.currentIndexChanged.connect(self._dimensions)
        self.add.clicked.connect(self.add_range)
        self.remove.clicked.connect(self.remove_range)
        self.overview.itemSelectionChanged.connect(self.load_selected)
        store.changed.connect(self.refresh)
        self.refresh()
        self._dimensions()

    def _dimensions(self, *_):
        shape = self.shape.currentData()
        dimension = 'radius' if shape == 'circle' else 'X semi-axis' if shape == 'ellipse' else 'full width'
        self.min_x_label.setText(f'Minimum {dimension} (µm)')
        self.max_x_label.setText(f'Maximum {dimension} (µm)')
        dimension = 'Y semi-axis' if shape == 'ellipse' else 'full height'
        self.min_y_label.setText(f'Minimum {dimension} (µm)')
        self.max_y_label.setText(f'Maximum {dimension} (µm)')
        self.y_row.setVisible(shape != 'circle')

    def records(self):
        return copy.deepcopy(self._rows)

    def sync_state(self):
        return copy.deepcopy(self._sync)

    def validated_records(self, value):
        result = rows(value, HOLE_COLS)
        seen = set()
        for row in result:
            self._validate(row)
            if row['Layer'] in seen:
                raise ValueError('Each PCS layer can have one hole range.')
            seen.add(row['Layer'])
        return result

    def set_records(self, value, sync_state=None):
        self._rows = self.validated_records(value)
        seen = {row['Layer'] for row in self._rows}
        if isinstance(sync_state, dict):
            self._sync = copy.deepcopy(sync_state)
        else:
            self._sync['manual'] = sorted(seen)
            self._sync['excluded'] = sorted(set(finite_layers(self.store.layers)) - seen)
        self._draw()
        self.changed.emit()

    def _validate(self, row):
        if row['Layer'] not in finite_layers(self.store.layers):
            raise ValueError('Select a finite layer from Structure.')
        if row['Shape'] not in ('circle', 'ellipse', 'rectangle'):
            raise ValueError('Select a supported hole shape.')
        from math import isfinite
        for low, high in [('MinX_um', 'MaxX_um')] + ([] if row['Shape'] == 'circle' else [('MinY_um', 'MaxY_um')]):
            lo, hi = float(row[low]), float(row[high])
            if not isfinite(lo) or not isfinite(hi) or lo <= 0 or hi < lo:
                raise ValueError('Hole sizes must be positive and the maximum must be at least the minimum.')

    def _draw(self, selected=None):
        item = self.overview.item(self.overview.currentRow(), 0)
        selected = selected if selected is not None else item.text() if item else None
        with QSignalBlocker(self.overview):
            self.overview.setRowCount(len(self._rows))
            self.overview.clearSelection()
            self.overview.setCurrentCell(-1, -1)
            for i, row in enumerate(self._rows):
                for j, key in enumerate(HOLE_COLS):
                    value = row[key]
                    self.overview.setItem(i, j, QTableWidgetItem(f'{value:g}' if isinstance(value, (int, float)) else str(value)))
                if row['Layer'] == selected:
                    self.overview.setCurrentCell(i, 0)
        self.remove.setEnabled(self.overview.currentRow() >= 0)

    def add_range(self):
        row = dict(zip(HOLE_COLS, [self.layer.currentData(), self.shape.currentData(), self.min_x.value(),
            self.max_x.value(), self.min_y.value() if self.shape.currentData() != 'circle' else 0.,
            self.max_y.value() if self.shape.currentData() != 'circle' else 0.]))
        try:
            self._validate(row)
        except (ValueError, TypeError) as exc:
            self.status.setText(str(exc))
            return False
        position = next((i for i, r in enumerate(self._rows) if r['Layer'] == row['Layer']), len(self._rows))
        if position == len(self._rows):
            self._rows.append(row)
        else:
            self._rows[position] = row
        self._sync['manual'] = sorted(set(self._sync.get('manual', [])) | {row['Layer']})
        self._sync['excluded'] = [name for name in self._sync.get('excluded', []) if name != row['Layer']]
        self._draw(row['Layer'])
        self.status.setText('Hole limits saved. These limits are retained when Structure dimensions change.')
        self.changed.emit()
        return True

    def load_selected(self):
        index = self.overview.currentRow()
        self.remove.setEnabled(index >= 0)
        if not 0 <= index < len(self._rows):
            return
        row = self._rows[index]
        self.layer.setCurrentIndex(self.layer.findData(row['Layer']))
        self.shape.setCurrentIndex(self.shape.findData(row['Shape']))
        for widget, key in ((self.min_x, 'MinX_um'), (self.max_x, 'MaxX_um'), (self.min_y, 'MinY_um'), (self.max_y, 'MaxY_um')):
            widget.setValue(float(row[key]))
        self._dimensions()

    def remove_range(self):
        index = self.overview.currentRow()
        if not 0 <= index < len(self._rows):
            return
        row = self._rows.pop(index)
        self._sync['excluded'] = sorted(set(self._sync.get('excluded', [])) | {row['Layer']})
        self._draw()
        self.changed.emit()

    def refresh(self, reason=None):
        previous = self.records()
        data, self._sync = sync_hole_ranges(self._rows, self._sync, self.store.materials, self.store.layers, self.store.patterns)
        self._rows = data.to_dict('records')
        _choices(self.layer, [(name, name) for name in finite_layers(self.store.layers)], self.layer.currentData())
        self.add.setEnabled(self.layer.count() > 0)
        self._draw()
        if previous != self._rows and reason != 'project':
            self.changed.emit()
