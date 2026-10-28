"""Inspect actual research-run artifacts without manufacturing result curves."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QSpinBox, QStyledItemDelegate, QHeaderView)

from qt_common import PlotWidget
from qt_research_common import button, label


class SavedArrayViewer(QWidget):
    """Inspect saved NPZ arrays using explicit component and slice selections."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.files, self.quantity, self.part = QComboBox(), QComboBox(), QComboBox()
        self.files.setAccessibleName('Saved array file'); self.quantity.setAccessibleName('Saved array quantity')
        self.part.addItems(['Real part', 'Imaginary part', 'Magnitude'])
        self.part.setAccessibleName('Complex-value display convention')
        self.component = QSpinBox(); self.component.setAccessibleName('Fourth array-axis index')
        self.slice = QSpinBox(); self.slice.setAccessibleName('Third array-axis index')
        for widget in (self.files, self.quantity, self.part):
            row.addWidget(widget, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.x_axis, self.y_axis = QComboBox(), QComboBox()
        self.x_axis.setAccessibleName('Saved array horizontal dimension')
        self.y_axis.setAccessibleName('Saved array vertical dimension')
        row.addWidget(label('Horizontal axis')); row.addWidget(self.x_axis, 1)
        row.addWidget(label('Vertical axis')); row.addWidget(self.y_axis, 1)
        self.slice_label, self.component_label = label('Fixed axis 2'), label('Fixed axis 3')
        row.addWidget(self.slice_label); row.addWidget(self.slice)
        row.addWidget(self.component_label); row.addWidget(self.component)
        row.addStretch(); row.addWidget(button('Export displayed slice…', self.export_slice))
        layout.addLayout(row)
        self.plot = PlotWidget(); layout.addWidget(self.plot, 1)
        self.note = label('Select a saved array. Raw array axes are sample indices unless explicit physical coordinates are available.')
        layout.addWidget(self.note)
        self.array = None
        self.displayed = None
        self.axis_metadata = []
        self.coordinates = {}
        self._fixed_axes = []
        self.quantity_unit = ''
        self.excluded_count = 0
        self.files.currentIndexChanged.connect(self.load_file)
        self.quantity.currentIndexChanged.connect(self.load_array)
        self.part.currentIndexChanged.connect(self.draw)
        self.slice.valueChanged.connect(self.draw)
        self.component.valueChanged.connect(self.draw)
        self.x_axis.currentIndexChanged.connect(self._axes_changed)
        self.y_axis.currentIndexChanged.connect(self._axes_changed)

    def load_directory(self, directory):
        directory = Path(directory)
        same_directory = directory.resolve() == getattr(self, '_directory', None)
        previous_file = self.files.currentData() if same_directory else None
        previous_quantity = self.quantity.currentText() if same_directory else ''
        self._directory = directory.resolve()
        self.files.blockSignals(True); self.files.clear()
        for path in sorted(directory.rglob('*.npz')):
            if path.resolve().is_relative_to(directory.resolve()):
                self.files.addItem(path.relative_to(directory).as_posix(), str(path))
        index = self.files.findData(previous_file)
        if index >= 0:
            self.files.setCurrentIndex(index)
        self.files.blockSignals(False)
        self.load_file(preferred_quantity=previous_quantity)

    @staticmethod
    def _default_quantity(archive):
        # Coordinate vectors and diagnostics remain selectable, but the initial
        # view should show a saved physical solution rather than array ordering.
        metadata = {}
        if 'array_axes' in archive:
            try:
                raw = archive['array_axes'].item()
                metadata = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else str(raw))
            except (ValueError, TypeError, AttributeError):
                pass
        if not isinstance(metadata, dict):
            metadata = {}
        coordinates = set()
        for entry in metadata.values():
            axes = entry if isinstance(entry, list) else entry.get('axes', []) if isinstance(entry, dict) else []
            coordinates.update(row['coordinate'] for row in axes
                               if isinstance(row, dict) and isinstance(row.get('coordinate'), str))
        coordinates.update({'x', 'y', 'z', 'x_um', 'y_um', 'z_um', 'x_m', 'y_m', 'z_m',
                            'x_nm', 'y_nm', 'z_nm', 'wavelength_nm', 'wavelengths_nm',
                            'frequency', 'frequencies', 'k_points', 'k_index', 'band_index'})
        candidates = []
        for key in archive.files:
            if key in coordinates or key.endswith(('_mask', '_index', '_indices', '_id')) or key in ('dof_map', 'array_axes'):
                continue
            try:
                value = archive[key]
                if value.size and value.ndim in (1, 2, 3, 4) and np.issubdtype(value.dtype, np.number):
                    candidates.append(key)
            except (ValueError, TypeError):
                continue
        return next((key for key in candidates if key in metadata), candidates[0] if candidates else '')

    def load_file(self, *args, preferred_quantity=None):
        previous_quantity = self.quantity.currentText() if preferred_quantity is None else preferred_quantity
        self.quantity.blockSignals(True); self.quantity.clear()
        path = self.files.currentData()
        if path:
            try:
                with np.load(path, allow_pickle=False) as archive:
                    for key in archive.files:
                        self.quantity.addItem(key)
                    selected = previous_quantity if previous_quantity in archive.files else self._default_quantity(archive)
                    self.quantity.setCurrentIndex(self.quantity.findText(selected))
            except (ValueError, OSError) as exc:
                self.note.setText('Cannot read saved arrays: '+str(exc))
        self.quantity.blockSignals(False)
        self.load_array()
        if path and not self.quantity.currentText():
            self.note.setText('No physical numeric array was identified. Coordinate and metadata entries remain available in the quantity selector.')

    def load_array(self, *args):
        self.array = None; self.displayed = None
        self.plot.clear()
        path, key = self.files.currentData(), self.quantity.currentText()
        if not path or not key:
            return
        try:
            with np.load(path, allow_pickle=False) as archive:
                array = archive[key]
                self.excluded_count = 0
                if key.startswith('high_field_') and key != 'high_field_evaluated_mask' and 'high_field_evaluated_mask' in archive:
                    evaluated = np.asarray(archive['high_field_evaluated_mask'], dtype=bool)
                    if array.shape[:evaluated.ndim] == evaluated.shape:
                        excluded = np.broadcast_to((~evaluated).reshape(evaluated.shape+(1,)*(array.ndim-evaluated.ndim)), array.shape)
                        self.excluded_count = int(excluded.sum())
                        array = np.ma.array(array, mask=excluded)
                metadata = {}
                if 'array_axes' in archive:
                    try:
                        raw = archive['array_axes'].item()
                        if isinstance(raw, bytes):
                            raw = raw.decode('utf-8')
                        metadata = json.loads(str(raw)).get(key, {})
                    except (ValueError, TypeError, AttributeError):
                        metadata = {}
                records = metadata if isinstance(metadata, list) else metadata.get('axes', []) if isinstance(metadata, dict) else []
                self.quantity_unit = metadata.get('unit', '') if isinstance(metadata, dict) else ''
                self.axis_metadata = [records[i] if i < len(records) and isinstance(records[i], dict) else {}
                                      for i in range(array.ndim)]
                self.coordinates = {}
                for i, record in enumerate(self.axis_metadata):
                    coordinate = record.get('coordinate')
                    if coordinate and coordinate in archive:
                        values = archive[coordinate]
                        if (values.ndim == 1 and len(values) == array.shape[i] and np.issubdtype(values.dtype, np.number)
                            and not np.iscomplexobj(values) and np.isfinite(values).all()
                            and (len(values) < 2 or np.all(np.diff(values) > 0) or np.all(np.diff(values) < 0))):
                            self.coordinates[i] = values.copy()
            if not array.size or not np.issubdtype(array.dtype, np.number) or array.ndim not in (1, 2, 3, 4):
                self.note.setText('This entry is metadata or a scalar. Choose a numeric array with one to four axes.'); return
            self.array = array
            self.x_axis.blockSignals(True); self.y_axis.blockSignals(True)
            self.x_axis.clear(); self.y_axis.clear()
            for i in range(array.ndim):
                title = self.axis_metadata[i].get('name', 'Axis '+str(i))+' ('+str(array.shape[i])+' samples)'
                self.x_axis.addItem(title, i); self.y_axis.addItem(title, i)
            names = [row.get('name', '').lower() for row in self.axis_metadata]
            self.x_axis.setCurrentIndex(names.index('x') if 'x' in names else 0)
            self.y_axis.setCurrentIndex(names.index('y') if 'y' in names else min(1, array.ndim-1))
            self.y_axis.setEnabled(array.ndim > 1)
            self.x_axis.blockSignals(False); self.y_axis.blockSignals(False)
            self.part.setEnabled(np.iscomplexobj(array))
            self._axes_changed()
        except (ValueError, OSError, KeyError) as exc:
            self.note.setText('Cannot load saved quantity: '+str(exc))

    def _axes_changed(self, *args):
        if self.array is None:
            return
        x, y = self.x_axis.currentData(), self.y_axis.currentData()
        if x is None or y is None:
            return
        if self.array.ndim > 1 and x == y:
            other = self.x_axis if self.sender() is self.y_axis else self.y_axis
            other.blockSignals(True); other.setCurrentIndex((x+1) % self.array.ndim); other.blockSignals(False)
        displayed = {self.x_axis.currentData()}
        if self.array.ndim > 1:
            displayed.add(self.y_axis.currentData())
        self._fixed_axes = [i for i in range(self.array.ndim) if i not in displayed]
        for position, (widget, title) in enumerate(((self.slice, self.slice_label), (self.component, self.component_label))):
            widget.blockSignals(True)
            enabled = position < len(self._fixed_axes)
            widget.setEnabled(enabled); title.setVisible(enabled); widget.setVisible(enabled)
            if enabled:
                dimension = self._fixed_axes[position]
                name = self.axis_metadata[dimension].get('name', 'Axis '+str(dimension))
                title.setText(name+' index'); widget.setAccessibleName(name+' fixed index')
                widget.setRange(0, self.array.shape[dimension]-1)
            widget.blockSignals(False)
        self.draw()

    def _axis_label(self, dimension):
        record = self.axis_metadata[dimension]
        name = record.get('name', 'Axis '+str(dimension))
        if dimension in self.coordinates:
            return name+(' ('+str(record['unit'])+')' if record.get('unit') else '')
        return name+' sample index'

    def draw(self, *args):
        if self.array is None:
            return
        indices = [slice(None)]*self.array.ndim
        fixed = {}
        for dimension, widget in zip(self._fixed_axes, (self.slice, self.component)):
            indices[dimension] = widget.value(); fixed[dimension] = widget.value()
        values = self.array[tuple(indices)]
        dimensions = [i for i in range(self.array.ndim) if i not in fixed]
        x_dimension = self.x_axis.currentData()
        y_dimension = self.y_axis.currentData() if values.ndim > 1 else None
        if values.ndim > 1:
            values = np.transpose(values, [dimensions.index(x_dimension), dimensions.index(y_dimension)])
        convention = self.part.currentText() if np.iscomplexobj(values) else 'Real values'
        values = np.abs(values) if convention == 'Magnitude' else values.imag if convention == 'Imaginary part' else values.real
        self.displayed = values
        self.display_dimensions = [x_dimension]+([y_dimension] if y_dimension is not None else [])
        self.display_fixed = fixed
        figure = Figure(figsize=(7, 4), layout='constrained'); axis = figure.add_subplot(111)
        x = self.coordinates.get(x_dimension, np.arange(values.shape[0]))
        quantity_title = self.quantity.currentText()+(' ('+self.quantity_unit+')' if self.quantity_unit else '')
        if values.ndim == 1:
            axis.plot(x, values); axis.set_xlabel(self._axis_label(x_dimension))
            axis.set_ylabel(quantity_title)
        else:
            y = self.coordinates.get(y_dimension, np.arange(values.shape[1]))
            artist = axis.pcolormesh(x, y, np.ma.masked_invalid(values.T), shading='nearest')
            figure.colorbar(artist, ax=axis, label=quantity_title)
            axis.set_xlabel(self._axis_label(x_dimension)); axis.set_ylabel(self._axis_label(y_dimension))
        self.plot.draw_figure(figure)
        self.note.setText(f'{self.quantity.currentText()} · saved shape {self.array.shape} · {convention}. '
            'Fixed indices: '+(', '.join(self.axis_metadata[d].get('name', 'Axis '+str(d))+' = '+str(v) for d, v in fixed.items()) or 'none')+'. '
            'Physical coordinates are used only where the saved array metadata supplies them; raw sample indices are not physical distance.'+
            (f' {self.excluded_count} unevaluated values are masked, not treated as zero.' if self.excluded_count else ''))

    def export_slice(self):
        if self.displayed is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export displayed saved-array slice', 'array-slice.csv', 'CSV (*.csv)')
        if path:
            try:
                with open(path, 'w', newline='', encoding='utf-8') as stream:
                    writer = csv.writer(stream)
                    dimensions = self.display_dimensions
                    fixed = self.display_fixed
                    writer.writerow([self._axis_label(d) for d in dimensions]+['axis_'+str(d)+'_index' for d in fixed]
                                    +[self.quantity.currentText()+'_'+(self.part.currentText() if np.iscomplexobj(self.array) else 'Real values')])
                    values = self.displayed[:, None] if self.displayed.ndim == 1 else self.displayed
                    for i, row in enumerate(values):
                        for j, value in enumerate(row):
                            coordinates = [self.coordinates.get(d, np.arange(self.array.shape[d]))[index]
                                           for d, index in zip(dimensions, (i, j))]
                            writer.writerow(coordinates+list(fixed.values())+['' if np.ma.is_masked(value) else value])
            except OSError as exc:
                self.note.setText('Export failed: '+str(exc))


class UnstructuredFieldViewer(QWidget):
    """Physical point/element projections from the saved tetrahedral mesh."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.files, self.quantity = QComboBox(), QComboBox()
        self.files.setAccessibleName('Saved conformal state'); self.quantity.setAccessibleName('Conformal mesh quantity')
        row.addWidget(self.files, 1); row.addWidget(self.quantity, 1); layout.addLayout(row)
        row = QHBoxLayout()
        self.projection, self.component = QComboBox(), QComboBox()
        for title, value in [('x–y', (0, 1, 2)), ('x–z', (0, 2, 1)), ('y–z', (1, 2, 0))]:
            self.projection.addItem(title, value)
        self.component.addItems(['Magnitude', 'x component', 'y component', 'z component'])
        self.minimum, self.maximum = QLineEdit(), QLineEdit()
        self.depth_label = label('z range (µm)')
        for widget in (self.projection, self.component, self.depth_label, self.minimum, self.maximum):
            row.addWidget(widget)
        row.addWidget(button('Update view', self.draw)); layout.addLayout(row)
        self.plot = PlotWidget(); layout.addWidget(self.plot, 1)
        self.note = label('Load a saved conformal mesh to view its actual points and tetrahedral elements.')
        layout.addWidget(self.note)
        layout.addWidget(button('Export selected physical samples…', self.export_samples))
        self.points = self.elements = self.locations = self.values = None
        self.selected_points = self.selected_values = None
        self.association = ''
        self.files.currentIndexChanged.connect(self.load_file)
        self.quantity.currentIndexChanged.connect(self.load_quantity)
        self.projection.currentIndexChanged.connect(self.reset_range)
        self.component.currentIndexChanged.connect(self.draw)
        self.minimum.returnPressed.connect(self.draw); self.maximum.returnPressed.connect(self.draw)

    def load_directory(self, directory, *, selection=None):
        root = Path(directory).resolve()
        if selection is None:
            current = self.files.currentData()
            selection = ((current, self.quantity.currentText())
                         if current and Path(current).resolve().is_relative_to(root) else ('', ''))
        self.files.blockSignals(True); self.files.clear()
        for path in sorted(root.rglob('*.npz')):
            if not path.resolve().is_relative_to(root):
                continue
            try:
                with np.load(path, allow_pickle=False) as archive:
                    if 'points_um' in archive and 'tetrahedra' in archive:
                        self.files.addItem(path.relative_to(root).as_posix(), str(path))
            except (ValueError, OSError):
                continue
        index = self.files.findData(selection[0])
        if index >= 0:
            self.files.setCurrentIndex(index)
        self.files.blockSignals(False)
        self.load_file(preferred_quantity=selection[1])
        return bool(self.files.count())

    def load_file(self, *args, preferred_quantity=None):
        previous_quantity = self.quantity.currentText() if preferred_quantity is None else preferred_quantity
        self.quantity.blockSignals(True); self.quantity.clear()
        self.points = self.elements = self.locations = self.values = None
        self.selected_points = self.selected_values = None
        self.plot.clear()
        path = self.files.currentData()
        if path:
            try:
                with np.load(path, allow_pickle=False) as archive:
                    points, elements = archive['points_um'], archive['tetrahedra']
                    if (points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all()
                        or elements.ndim != 2 or elements.shape[1] != 4
                        or not np.issubdtype(elements.dtype, np.integer) or not elements.size
                        or elements.min() < 0 or elements.max() >= len(points)):
                        raise ValueError('Saved points or tetrahedral connectivity are invalid.')
                    self.points, self.elements = points.copy(), elements.copy()
                    for key in archive.files:
                        if key in ('points_um', 'tetrahedra', 'array_axes'):
                            continue
                        values = archive[key]
                        if (np.issubdtype(values.dtype, np.number) and not np.iscomplexobj(values)
                            and values.ndim in (1, 2) and len(values) in (len(points), len(elements))
                            and (values.ndim == 1 or values.shape[1] in (3, 4))):
                            self.quantity.addItem(key)
            except (ValueError, OSError) as exc:
                self.note.setText('Cannot read conformal mesh: '+str(exc))
        # State changes retain the user's physical or diagnostic quantity.
        # A new run, or a state without that field, starts on saved potential.
        for key in (previous_quantity, 'potential_V', 'potential'):
            index = self.quantity.findText(key)
            if index >= 0:
                self.quantity.setCurrentIndex(index)
                break
        self.quantity.blockSignals(False); self.load_quantity()

    def load_quantity(self, *args):
        path, key = self.files.currentData(), self.quantity.currentText()
        self.locations = self.values = None
        self.selected_points = self.selected_values = None
        self.plot.clear()
        if not path or not key or self.points is None:
            return
        try:
            with np.load(path, allow_pickle=False) as archive:
                values = archive[key].copy()
            on_elements = 'element' in key or len(values) != len(self.points)
            if on_elements:
                self.locations = self.points[self.elements].mean(axis=1)
                self.association = 'tetrahedron centroid values'
                if values.ndim == 2 and values.shape[1] == 4:
                    values = values.mean(axis=1)
                    self.association = 'mean of four element-local vertex values, located at the tetrahedron centroid'
            else:
                self.locations = self.points
                self.association = 'mesh vertex values'
            if len(values) != len(self.locations):
                raise ValueError('The field does not match the selected mesh association.')
            self.values = values
            self.component.setEnabled(values.ndim == 2 and values.shape[1] == 3)
            self.reset_range()
        except (ValueError, OSError, KeyError) as exc:
            self.note.setText('Cannot read conformal quantity: '+str(exc))

    def reset_range(self, *args):
        if self.locations is None:
            return
        depth = self.projection.currentData()[2]
        self.depth_label.setText('xyz'[depth]+' range (µm)')
        self.minimum.setText(str(self.locations[:, depth].min()))
        self.maximum.setText(str(self.locations[:, depth].max()))
        self.draw()

    def draw(self, *args):
        if self.locations is None or self.values is None:
            return
        try:
            lower, upper = float(self.minimum.text()), float(self.maximum.text())
            if not np.isfinite([lower, upper]).all() or lower > upper:
                raise ValueError('Supply an increasing finite physical depth range.')
        except ValueError as exc:
            self.note.setText(str(exc)); return
        values = self.values
        if values.ndim == 2:
            values = np.linalg.norm(values, axis=1) if self.component.currentIndex() == 0 else values[:, self.component.currentIndex()-1]
        x, y, depth = self.projection.currentData()
        selected = (self.locations[:, depth] >= lower) & (self.locations[:, depth] <= upper) & np.isfinite(values)
        points, values = self.locations[selected], values[selected]
        self.selected_points, self.selected_values = points, values
        self.plot.clear()
        if not len(points):
            self.note.setText('No saved physical samples lie in this depth range.'); return
        # Keep every sample in exports; plotting may decimate very large meshes.
        stride = max(1, int(np.ceil(len(points)/100000)))
        figure = Figure(figsize=(7, 4), layout='constrained'); axis = figure.add_subplot(111)
        artist = axis.scatter(points[::stride, x], points[::stride, y], c=values[::stride], s=10, linewidths=0)
        figure.colorbar(artist, ax=axis, label=self.quantity.currentText())
        axis.set_xlabel('xyz'[x]+' (µm)'); axis.set_ylabel('xyz'[y]+' (µm)'); axis.set_aspect('equal')
        self.plot.draw_figure(figure)
        self.note.setText(str(len(points))+' physical samples · '+self.association+'. Projection over '+
            'xyz'[depth]+f' = [{lower:g}, {upper:g}] µm; no spatial interpolation. '+
            ('Display uses every '+str(stride)+'th point; exports retain all selected samples.' if stride > 1 else ''))

    def export_samples(self):
        if self.selected_points is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export selected conformal samples', 'conformal-samples.csv', 'CSV (*.csv)')
        if path:
            try:
                title = self.quantity.currentText()+(' '+self.component.currentText() if self.component.isEnabled() else '')
                with open(path, 'w', newline='', encoding='utf-8') as stream:
                    writer = csv.writer(stream); writer.writerow(['x_um', 'y_um', 'z_um', title, 'association'])
                    for point, value in zip(self.selected_points, self.selected_values):
                        writer.writerow([*point, value, self.association])
            except OSError as exc:
                self.note.setText('Export failed: '+str(exc))


def _saved_high_field_table(directory, summary):
    """Flatten saved state/wavelength arrays; do not recompute any optical values."""
    if summary.get('engine') != 'high_field_optics':
        return None
    path = directory/'high_field_optics.npz'
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as archive:
        waves = np.asarray(archive['wavelengths_nm'])
        ids = np.asarray(archive['sample_ids'])
        if waves.ndim != 1 or ids.ndim != 1:
            raise ValueError('High-field sample IDs and wavelengths must be one-dimensional.')
        shape = (len(ids), len(waves))
        arrays = {}
        required = {'absorption_cm1', 'reference_absorption_cm1', 'delta_n', 'delta_k', 'interband_k'}
        for key in archive.files:
            if key in ('sample_ids', 'wavelengths_nm'):
                continue
            values = np.asarray(archive[key])
            if key in required and values.shape != shape:
                raise ValueError('High-field '+key+' shape does not match the saved states and wavelengths.')
            if values.shape == shape and np.issubdtype(values.dtype, np.number):
                arrays[key] = values
        if not required <= arrays.keys():
            raise ValueError('Required high-field optical arrays are missing.')
        parameters = {str(row.get('id')): row for row in summary.get('options', {}).get('samples', [])}
        state_keys = ['field_V_m', 'bandgap_eV', 'temperature_K', 'electron_reduced_fermi', 'hole_reduced_fermi']
        headers = ['sample_id', 'wavelength_nm', *arrays, *state_keys]
        rows = []
        for i, ident in enumerate(ids):
            state = parameters.get(str(ident), {})
            for j, wave in enumerate(waves):
                rows.append([str(ident), str(wave), *[str(value[i, j]) for value in arrays.values()],
                             *[str(state[key]) if key in state else '' for key in state_keys]])
    return dict(source='saved_high_field_arrays', filename='high-field-optics.csv', headers=headers, rows=rows)


def _saved_terminal_table(summary):
    """Expose recorded transport checks as tabular data without rewriting the run."""
    if summary.get('engine') not in ('advanced_transport', 'pcsel_unitcell_transport'):
        return None
    states = summary.get('results', [])
    if not isinstance(states, list):
        return None
    swept = summary.get('options', {}).get('swept_contact_id')
    records = []
    for state in states:
        if not isinstance(state, dict) or not isinstance(state.get('checks'), dict):
            continue
        checks = state['checks']
        currents = checks.get('terminal_current_A', {})
        if not isinstance(currents, dict) or not currents:
            continue
        row = {'bias_V': state.get('bias_V')}
        for name, source in [('terminal_voltage_V', 'terminal_voltages_V'),
                             ('current_A', 'terminal_current_A'), ('terminal_charge_C', 'terminal_charge_C')]:
            if swept in checks.get(source, {}):
                row[name] = checks[source][swept]
        # Preserve every terminal and scalar conservation diagnostic, including units in its key.
        for key, value in checks.items():
            if key in ('terminal_current_A', 'terminal_charge_C', 'terminal_voltages_V') and isinstance(value, dict):
                row.update({key+'.'+str(contact): number for contact, number in value.items()})
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                row[key] = value
        records.append(row)
    if not records:
        return None
    headers = list(dict.fromkeys(key for row in records for key in row))
    rows = [[str(row[key]) if row.get(key) is not None else '' for key in headers] for row in records]
    return dict(source='saved_terminal_checks', headers=headers, rows=rows)


class _CompactResultNumberDelegate(QStyledItemDelegate):
    """Compact paint text only; item data and copied/exported values stay exact."""
    def displayText(self, value, locale):
        raw = str(value)
        if len(raw) > 12:
            try:
                numeric = float(raw)
                if np.isfinite(numeric):
                    return format(numeric, '.8g')
            except ValueError:
                pass
        return raw


class ResearchResultsPanel(QWidget):
    """A read-only view of a run directory, with explicit file/axis selection."""
    def __init__(self, store=None, engine=None, parent=None):
        super().__init__(parent)
        self.store, self.engine = store, engine
        self.directory = None
        self.data = None
        self.reference = None
        self.summary = {}
        self._data_summary = {}
        self._headers = []
        self._pole_acceptance = []
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        actions.addWidget(button('Open saved run…', self.choose_directory))
        self.files = QComboBox()
        self.files.setAccessibleName('Result data file')
        self.files.currentIndexChanged.connect(self._file_changed)
        actions.addWidget(self.files, 1)
        self.export_button = button('Export displayed CSV…', self.export_csv)
        self.export_button.setEnabled(False)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        self.status = label('No result loaded. Run a study or open one of its saved result folders.')
        layout.addWidget(self.status)
        self.method_status = label(''); self.method_status.setAccessibleName('Requested and calculated lattice period'); self.method_status.hide()
        layout.addWidget(self.method_status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        chart = QWidget()
        chart_layout = QVBoxLayout(chart)
        axes = QHBoxLayout()
        self.x_axis, self.y_axis = QComboBox(), QComboBox()
        self.x_axis.setAccessibleName('Horizontal data column')
        self.y_axis.setAccessibleName('Vertical data column')
        axes.addWidget(QLabel('Horizontal'))
        axes.addWidget(self.x_axis, 1)
        axes.addWidget(QLabel('Vertical'))
        axes.addWidget(self.y_axis, 1)
        chart_layout.addLayout(axes)
        self.plot = PlotWidget()
        chart_layout.addWidget(self.plot, 1)
        self.chart_note = label('Charts show only numeric columns from the selected saved file.')
        chart_layout.addWidget(self.chart_note)
        self.x_axis.currentIndexChanged.connect(self.draw)
        self.y_axis.currentIndexChanged.connect(self.draw)
        self.tabs.addTab(chart, 'Plot')
        self.table = QTableWidget()
        self.table.setAccessibleName('Saved numeric result data')
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setItemDelegate(_CompactResultNumberDelegate(self.table))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setMinimumSectionSize(96)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.table, 'Data')
        self.arrays = SavedArrayViewer(self)
        self.tabs.addTab(self.arrays, 'Saved field arrays')
        self.unstructured = UnstructuredFieldViewer(self)
        self.tabs.addTab(self.unstructured, 'Conformal field maps')
        self.tabs.setTabEnabled(self.tabs.indexOf(self.unstructured), False)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName('Run provenance, validity and limitations')
        self.tabs.addTab(self.details, 'Status & provenance')
        compare = QWidget()
        comparison = QVBoxLayout(compare)
        comparison.addWidget(label('Compare the selected x/y columns with an explicit two-column reference CSV. '
            'The reference must use exactly the same quantity, units and coordinate convention. '
            'Only matching x samples are compared; no interpolation or extrapolation is applied.'))
        buttons = QHBoxLayout()
        buttons.addWidget(button('Load reference CSV…', self.choose_reference))
        buttons.addWidget(button('Clear reference', self.clear_reference))
        buttons.addStretch()
        comparison.addLayout(buttons)
        self.compare_status = label('No reference is loaded. A matching curve is not by itself a validated paper reproduction.')
        comparison.addWidget(self.compare_status)
        comparison.addStretch()
        self.tabs.addTab(compare, 'Reference comparison')
        benchmark = QWidget()
        benchmark_layout = QVBoxLayout(benchmark)
        self.benchmark_choice = QComboBox()
        self.benchmark_choice.setAccessibleName('Saved paper comparison quantity')
        benchmark_layout.addWidget(self.benchmark_choice)
        self.benchmark_status = label('No saved benchmark comparison is loaded.')
        benchmark_layout.addWidget(self.benchmark_status)
        self.benchmark_plot = PlotWidget()
        benchmark_layout.addWidget(self.benchmark_plot, 1)
        self.benchmark_choice.currentIndexChanged.connect(self.draw_benchmark)
        self.tabs.addTab(benchmark, 'Paper comparison')
        self.benchmark_comparison = {}
        from qt_pcsel_paper import PcselPaperResults
        self.paper_figures = PcselPaperResults(self)
        self.paper_figures_index = self.tabs.addTab(self.paper_figures, 'Paper figures')
        self.tabs.setTabVisible(self.paper_figures_index, False)

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, 'Open saved research run')
        if path:
            self.load_directory(path)

    def _clear_result(self):
        """A new open attempt must not expose data or exports from another run."""
        self.directory = None
        self.summary = {}
        self.method_status.clear(); self.method_status.hide()
        self.data = None
        self.reference = None
        self._data_summary = {}
        self._headers = []
        self._pole_acceptance = []
        self.benchmark_comparison = {}
        for control in (self.files, self.x_axis, self.y_axis, self.benchmark_choice):
            with QSignalBlocker(control):
                control.clear()
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.details.clear()
        self.export_button.setEnabled(False)
        self.plot.clear()
        self.benchmark_plot.clear()
        self.paper_figures.clear()
        self.tabs.setTabVisible(self.paper_figures_index, False)
        self.chart_note.setText('No result data is loaded.')
        self.compare_status.setText('No reference is loaded.')
        self.benchmark_status.setText('No saved benchmark comparison is loaded.')
        # Use the child viewers' ordinary empty-selection paths so export
        # buffers and plotted arrays are reset along with their selectors.
        with QSignalBlocker(self.arrays.files):
            self.arrays.files.clear()
        self.arrays.load_file()
        self.arrays.axis_metadata = []
        self.arrays.coordinates = {}
        self.arrays._fixed_axes = []
        self.arrays.quantity_unit = ''
        self.arrays.excluded_count = 0
        for control in (self.arrays.x_axis, self.arrays.y_axis):
            with QSignalBlocker(control):
                control.clear()
        self.arrays.note.setText('No saved arrays are loaded.')
        with QSignalBlocker(self.unstructured.files):
            self.unstructured.files.clear()
        self.unstructured.load_file()
        self.unstructured.association = ''
        self.unstructured.minimum.clear()
        self.unstructured.maximum.clear()
        self.unstructured.note.setText('No saved conformal mesh is loaded.')
        self.tabs.setTabEnabled(self.tabs.indexOf(self.unstructured), False)

    def load_directory(self, path):
        directory = Path(path).resolve()
        conformal_selection = ((self.unstructured.files.currentData(), self.unstructured.quantity.currentText())
                               if self.directory == directory else None)
        self._clear_result()
        manifest = next((directory/name for name in ('research_summary.json', 'pcsel_summary.json', 'band_summary.json', 'search_summary.json', 'library_record.json') if (directory/name).is_file()), None)
        if manifest is None:
            self.status.setText('This folder has no research result summary. Failed or incomplete runs remain in their original folder.')
            return False
        try:
            summary = json.loads(manifest.read_text(encoding='utf-8'))
            if not isinstance(summary, dict):
                raise ValueError('Summary must be a JSON object.')
            if manifest.name == 'library_record.json':
                record = summary
                if not isinstance(record.get('summary', {}), dict):
                    raise ValueError('Library result summary must be a JSON object.')
                summary = dict(record.get('summary', {}), status=record.get('status', 'unreported'), library_record=record)
            allowed_engines = (None, self.engine, 'mpb', 'legume') if self.engine == 'photonic_bands' else (None, self.engine)
            if self.engine and summary.get('engine') not in allowed_engines:
                raise ValueError('This run belongs to a different study workspace.')
        except (ValueError, OSError) as exc:
            self.status.setText('Could not read result: '+str(exc))
            return False
        self.directory, self.summary = directory, summary
        self.reference = None
        self.files.blockSignals(True)
        self.files.clear()
        terminal_table = _saved_terminal_table(summary)
        if terminal_table:
            self.files.addItem('Saved terminal I–V · summary values', terminal_table)
        table_error = ''
        try:
            optical_table = _saved_high_field_table(directory, summary)
            if optical_table:
                self.files.addItem('Saved high-field states · all wavelengths and quantities', optical_table)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            table_error = '\nSaved optical table could not be read: '+str(exc)
        for file in sorted(directory.rglob('*.csv')):
            if file.is_file() and file.resolve().is_relative_to(directory):
                self.files.addItem(file.relative_to(directory).as_posix(), str(file))
        self.files.blockSignals(False)
        self.status.setText(str(summary.get('status', 'unreported')).upper()+' · '+str(directory)+table_error)
        derived = summary.get('derived_inputs', {})
        if isinstance(derived, dict) and derived.get('vertical_formulation') == 'reference_wavelength':
            def saved_value(key):
                value = derived.get(key)
                return format(value, '.10g') if isinstance(value, (int, float)) and np.isfinite(value) else 'not recorded'
            self.method_status.setText('Reference-wavelength method · requested period '+saved_value('requested_lattice_nm')+' nm · calculated period used '+saved_value('effective_lattice_nm')+' nm · reference wavelength '+saved_value('reference_wavelength_nm')+' nm. The saved input retains the requested period; calculated geometry and coupling use the derived period.')
            self.method_status.show()
        self.details.setPlainText(json.dumps(summary, indent=2, ensure_ascii=False))
        self.benchmark_comparison = summary.get('benchmark_comparison', {})
        if (directory/'benchmark_comparison.json').is_file():
            try:
                self.benchmark_comparison = json.loads((directory/'benchmark_comparison.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                self.benchmark_comparison = {}
        self.benchmark_choice.blockSignals(True)
        self.benchmark_choice.clear()
        for comparison in self.benchmark_comparison.get('results', []):
            self.benchmark_choice.addItem(comparison.get('label', comparison.get('id', 'Comparison')), comparison)
        self.benchmark_choice.blockSignals(False)
        self.draw_benchmark()
        self._file_changed()
        self.arrays.load_directory(directory)
        if terminal_table:
            # Start on an actual saved potential slice; all quantities/axes remain selectable.
            for state in reversed(summary.get('results', [])):
                name = Path(str(state.get('volume_npz', ''))).name
                index = next((i for i in range(self.arrays.files.count())
                              if Path(self.arrays.files.itemData(i)).name == name), -1)
                if index >= 0:
                    self.arrays.files.setCurrentIndex(index)
                    break
            for key in ('potential_V', 'potential'):
                index = self.arrays.quantity.findText(key)
                if index >= 0:
                    self.arrays.quantity.setCurrentIndex(index)
                    if self.arrays.array is not None and self.arrays.array.ndim >= 3:
                        self.arrays.y_axis.setCurrentIndex(self.arrays.y_axis.findData(2))
                    break
        self.tabs.setTabEnabled(self.tabs.indexOf(self.unstructured),
                                self.unstructured.load_directory(directory, selection=conformal_selection))
        if summary.get('engine') == 'pcsel' and (directory/'pcsel_paper_figures.json').is_file():
            self.tabs.setTabVisible(self.paper_figures_index, True)
            self.paper_figures.load_directory(directory)
            self.tabs.setCurrentIndex(self.paper_figures_index)
        return True

    def _file_changed(self, *args):
        path = self.files.currentData()
        self.data, self._headers = None, []
        self._pole_acceptance = []
        self.x_axis.blockSignals(True)
        self.y_axis.blockSignals(True)
        self.x_axis.clear()
        self.y_axis.clear()
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        if path:
            try:
                self._data_summary = self.summary
                if isinstance(path, dict):
                    headers, rows = path['headers'], path['rows']
                else:
                    manifest = Path(path).parent/'band_summary.json'
                    if manifest.is_file():
                        self._data_summary = json.loads(manifest.read_text(encoding='utf-8'))
                    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
                        reader = csv.reader(stream)
                        headers = next(reader)
                        rows = list(reader)
                if any(len(row) != len(headers) for row in rows):
                    raise ValueError('CSV rows have different column counts.')
                self._headers = headers
                self.table.setColumnCount(len(headers))
                self.table.setHorizontalHeaderLabels(headers)
                # All rows stay in the file; the table cap does not affect plots/exports.
                shown = rows[:10000]
                self.table.setRowCount(len(shown))
                for i, row in enumerate(shown):
                    for j, value in enumerate(row):
                        item = QTableWidgetItem(value)
                        item.setToolTip(value)
                        self.table.setItem(i, j, item)
                columns = {}
                for index, heading in enumerate(headers):
                    try:
                        values = np.asarray([float(row[index]) for row in rows], float)
                    except ValueError:
                        continue
                    if values.size and np.isfinite(values).all():
                        columns[heading] = values
                        self.x_axis.addItem(heading, heading)
                        self.y_axis.addItem(heading, heading)
                self.data = columns
                gme_modes = self._is_gme_modes()
                rcwa_poles = self._is_rcwa_poles()
                if rcwa_poles:
                    acceptance_column = headers.index('accepted') if 'accepted' in headers else None
                    self._pole_acceptance = [
                        'Accepted pole' if str(row[acceptance_column]).strip().lower() in ('true', '1')
                        else 'Unaccepted pole' if str(row[acceptance_column]).strip().lower() in ('false', '0')
                        else 'Acceptance not recorded'
                        for row in rows] if acceptance_column is not None else ['Acceptance not recorded'] * len(rows)
                preferred = ('wavelength_nm' if path.get('source') == 'saved_high_field_arrays' else 'terminal_voltage_V') if isinstance(path, dict) else 'path_distance_reciprocal_a'
                if gme_modes:
                    preferred = 'k_index'
                elif rcwa_poles:
                    preferred = 'frequency'
                if preferred in columns:
                    self.x_axis.setCurrentText(preferred)
                self.y_axis.addItem('All bands', '__bands__') if any(h.startswith('band_') for h in columns) else None
                if any(h.startswith('band_') for h in columns):
                    self.y_axis.setCurrentText('All bands')
                elif isinstance(path, dict) and path.get('source') == 'saved_high_field_arrays' and 'absorption_cm1' in columns:
                    self.y_axis.setCurrentText('absorption_cm1')
                elif isinstance(path, dict) and 'current_A' in columns:
                    self.y_axis.setCurrentText('current_A')
                elif gme_modes:
                    self.y_axis.setCurrentText('frequency')
                elif rcwa_poles:
                    self.y_axis.setCurrentText('imaginary')
                elif self.y_axis.count() > 1:
                    self.y_axis.setCurrentIndex(1)
                self.chart_note.setText(f'{len(rows):,} saved rows. '+('Table displays the first 10,000 rows. ' if len(rows) > 10000 else '')+
                    'Column names retain the solver units. '+('Recorded values from saved result artifacts; no new calculation.' if isinstance(path, dict) else 'Path gaps do not establish a complete Brillouin-zone gap.' if any(h.startswith('band_') for h in columns) else ''))
                if gme_modes:
                    self.chart_note.setText(self.chart_note.text() +
                        ' Each curve joins the same saved band index in input wavevector order; bands are not overlap-tracked. '
                        'Frequency is normalized as a / wavelength; Q is dimensionless. Select wavelength_nm or Q for other views.')
                elif rcwa_poles:
                    self.chart_note.setText(self.chart_note.text() +
                        ' Markers show solved complex frequencies, grouped by recorded root acceptance; unrelated poles are not connected. '
                        'Circle: accepted; cross: unaccepted; square: acceptance not recorded. Root acceptance does not establish convergence.')
            except (OSError, ValueError, StopIteration) as exc:
                self.chart_note.setText('Cannot display this data file: '+str(exc))
        else:
            self.chart_note.setText('This result has no CSV data. See its status and provenance for saved artifacts.')
        self.x_axis.blockSignals(False)
        self.y_axis.blockSignals(False)
        self.export_button.setEnabled(bool(path))
        self.draw()

    def _is_gme_modes(self):
        source = self.files.currentData()
        return (isinstance(source, str) and Path(source).name == 'gme_modes.csv'
                and self.data is not None and {'k_index', 'band', 'frequency'}.issubset(self.data))

    def _is_rcwa_poles(self):
        source = self.files.currentData()
        return (isinstance(source, str) and Path(source).name == 'rcwa_poles.csv'
                and self.data is not None and {'frequency', 'imaginary'}.issubset(self.data))

    def draw(self, *args):
        figure = Figure(figsize=(7, 4), layout='constrained')
        axis = figure.add_subplot(111)
        x_key, y_key = self.x_axis.currentData(), self.y_axis.currentData()
        if self.data and x_key in self.data:
            y_keys = [key for key in self.data if key.startswith('band_')] if y_key == '__bands__' else [y_key]
            source = self.files.currentData()
            gme_modes = self._is_gme_modes()
            rcwa_poles = self._is_rcwa_poles()
            groups = [(None, np.ones(len(self.data[x_key]), dtype=bool))]
            if gme_modes:
                bands = self.data['band']
                groups = [('Band '+format(band, 'g'), bands == band) for band in dict.fromkeys(bands)]
            if rcwa_poles:
                acceptance = np.asarray(self._pole_acceptance)
                groups = [(status, acceptance == status) for status in dict.fromkeys(acceptance)]
            if isinstance(source, dict) and source.get('source') == 'saved_high_field_arrays':
                state_column = source['headers'].index('sample_id')
                state_ids = np.asarray([row[state_column] for row in source['rows']])
                groups = [(ident, state_ids == ident) for ident in dict.fromkeys(state_ids)]
            for key in y_keys:
                if key in self.data:
                    connected = not rcwa_poles and self._data_summary.get('path_connectivity', True)
                    for ident, selected in groups:
                        marker = ({'Accepted pole': 'o', 'Unaccepted pole': 'x', 'Acceptance not recorded': 's'}.get(ident, 'o')
                                  if rcwa_poles else '.' if not connected or selected.sum() < 30 else None)
                        axis.plot(self.data[x_key][selected], self.data[key][selected], linestyle='-' if connected else 'None',
                            marker=marker, label=(str(ident)+' · ' if ident is not None else '')+key)
            labels = ({'k_index': 'Wavevector sample index', 'band': 'Band index',
                       'kx': 'kx (2 pi / a)', 'ky': 'ky (2 pi / a)',
                       'frequency': 'Normalized frequency (a / wavelength)',
                       'frequency_imag': 'Imaginary normalized frequency (omega a / 2 pi c)',
                       'wavelength_nm': 'Wavelength (nm)', 'Q': 'Quality factor Q (dimensionless)'}
                      if gme_modes else {})
            if rcwa_poles:
                labels.update(frequency='Real normalized frequency Re(omega a / 2 pi c)',
                              imaginary='Imaginary normalized frequency Im(omega a / 2 pi c)',
                              Q='Quality factor Q (dimensionless)',
                              seed_real='Seed real normalized frequency (omega a / 2 pi c)',
                              seed_imag='Seed imaginary normalized frequency (omega a / 2 pi c)',
                              residual='Pole-search residual', calls='Response evaluation count')
            axis.set_xlabel(labels.get(x_key, x_key))
            axis.set_ylabel('a / wavelength' if y_key == '__bands__' else labels.get(y_key, str(y_key)))
            axis.grid(True, alpha=.25)
            if self.reference is not None and y_key in self.data:
                values, source = self.reference
                axis.plot(values[:, 0], values[:, 1], 'o', fillstyle='none', label='Reference: '+source.name)
                pairs = []
                for x, y in values:
                    matching = np.flatnonzero(np.isclose(self.data[x_key], x, rtol=1e-9, atol=1e-12))
                    if len(matching) == 1:
                        pairs.append(self.data[y_key][matching[0]]-y)
                if pairs:
                    errors = np.asarray(pairs)
                    self.compare_status.setText(f'{len(pairs)} exact-coordinate samples compared. '
                        f'RMSE {np.sqrt(np.mean(errors**2)):.6g}; maximum absolute difference {np.max(np.abs(errors)):.6g}. '
                        'Difference units are the selected vertical-axis units. Confirm source conventions before interpreting agreement.')
                else:
                    self.compare_status.setText('No unique matching x samples. Select compatible columns; no interpolated agreement is claimed.')
            elif self.reference is not None:
                self.compare_status.setText('Select one vertical data column to compare with the reference.')
            if len(y_keys) <= 12 or self.reference is not None:
                axis.legend(fontsize=8)
        else:
            axis.text(.5, .5, 'No numeric result selected', transform=axis.transAxes, ha='center', va='center')
            axis.set_axis_off()
        self.plot.draw_figure(figure)

    def draw_benchmark(self, *args):
        comparison = self.benchmark_choice.currentData()
        figure = Figure(figsize=(7, 5), layout='constrained')
        if comparison and comparison.get('status') == 'compared':
            observed = np.asarray(comparison['observed'], float)
            reference = np.asarray(comparison['reference'], float)
            x = np.asarray(comparison.get('x', list(range(len(observed)))), float)
            axis, residual = figure.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [3, 1]})
            axis.plot(x, observed, '.-', label='Calculated')
            axis.plot(x, reference, 'o', fillstyle='none', label='Reference')
            axis.set_ylabel(comparison.get('units', ''))
            axis.legend(); axis.grid(True, alpha=.25)
            residual.plot(x, observed-reference, '.-', label='Calculated − reference')
            residual.axhline(0, color='gray', linewidth=.7)
            residual.set_ylabel('Residual')
            residual.set_xlabel('Reference coordinate' if 'x' in comparison else 'Observation index')
            tolerance = comparison.get('tolerance')
            if tolerance is not None:
                tolerance = np.broadcast_to(np.asarray(tolerance, float), observed.shape)
                residual.fill_between(x, -tolerance, tolerance, alpha=.18, label='Declared tolerance')
            self.benchmark_status.setText('Comparison '+str(self.benchmark_comparison.get('status', 'unreported'))+
                f' · RMSE {comparison["rmse"]:.6g} {comparison.get("units", "")} · '+
                ('Inputs edited. ' if self.benchmark_comparison.get('input_edited') else 'Reference input identity retained. ')+
                'Convergence: '+str(self.benchmark_comparison.get('convergence_status', 'not_established'))+'. '+
                str(comparison.get('interpolation', ''))+' '+str(comparison.get('tolerance_basis', ''))+
                ' Agreement and convergence remain separate claims; reproduction is not automatically accepted.')
        else:
            axis = figure.add_subplot(111)
            axis.set_axis_off()
            self.benchmark_status.setText(str(comparison.get('message', 'Comparison unavailable.')) if comparison else 'No saved benchmark comparison is loaded.')
        self.benchmark_plot.draw_figure(figure)

    def choose_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose reference CSV (x,y; same units)', '', 'CSV data (*.csv)')
        if path:
            self.load_reference(path)

    def load_reference(self, path):
        try:
            with Path(path).open(newline='', encoding='utf-8-sig') as stream:
                rows = list(csv.reader(stream))
            try:
                float(rows[0][0]); float(rows[0][1])
            except (ValueError, IndexError):
                rows = rows[1:]
            if not rows or any(len(row) != 2 for row in rows):
                raise ValueError('Use exactly two numeric columns, with an optional header.')
            data = np.asarray([[float(value) for value in row] for row in rows])
            if not np.isfinite(data).all():
                raise ValueError('Reference values must be finite.')
            self.reference = data, Path(path)
            self.draw()
            return True
        except (OSError, ValueError, IndexError) as exc:
            self.compare_status.setText('Could not load reference: '+str(exc))
            return False

    def clear_reference(self):
        self.reference = None
        self.compare_status.setText('No reference is loaded.')
        self.draw()

    def export_csv(self):
        source = self.files.currentData()
        if not source:
            return
        target, _ = QFileDialog.getSaveFileName(self, 'Export saved result CSV', source.get('filename', 'terminal-iv.csv') if isinstance(source, dict) else Path(source).name, 'CSV data (*.csv)')
        if target:
            try:
                if isinstance(source, dict):
                    with Path(target).open('w', newline='', encoding='utf-8') as stream:
                        writer = csv.writer(stream)
                        writer.writerow(source['headers']); writer.writerows(source['rows'])
                elif Path(source).resolve() != Path(target).resolve():
                    shutil.copyfile(source, target)
                self.status.setText('Exported saved solver data to '+target)
            except OSError as exc:
                self.status.setText('Export failed: '+str(exc))
