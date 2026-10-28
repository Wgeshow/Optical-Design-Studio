"""Editable prescribed-heat controls on the existing finite device."""
from __future__ import annotations

from copy import deepcopy
import csv
from pathlib import Path
from html import escape
from zipfile import BadZipFile

import numpy as np
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, QSignalBlocker, QTimer
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QSpinBox,
    QTableWidgetItem, QWidget, QVBoxLayout, QCheckBox, QSplitter, QTextBrowser, QScrollArea, QGridLayout)

from qt_common import PlotWidget
from qt_input_diagnostics import reveal_and_focus
from qt_photonic_bands import _table, _fill, _rows
from qt_research_common import ResearchWorkspaceBase, FieldError, button, label, number
from qt_research_results import ResearchResultsPanel
from qt_sesame_setup import TableRowInspector, replace_section, native_form, restyle_inspectors, install_result_picker


class ThermalResultsPanel(ResearchResultsPanel):
    def __init__(self, store, parent=None):
        super().__init__(store, 'thermal', parent)
        from PyQt6.QtWidgets import QWidget, QVBoxLayout
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        self.quantity = QComboBox()
        self.quantity.addItem('Temperature (K)', 'temperature_K')
        self.quantity.addItem('Temperature rise (K)', 'temperature_rise_K')
        self.quantity.addItem('Prescribed heat density (W/m³)', 'heat_density_W_m3')
        self.quantity.setAccessibleName('Thermal volume quantity')
        self.slice = QSpinBox()
        self.slice.setAccessibleName('Depth slice index')
        controls.addWidget(self.quantity, 1)
        controls.addWidget(label('Depth slice'))
        controls.addWidget(self.slice)
        self.slice_export = button('Export slice CSV…', self.export_slice)
        controls.addWidget(self.slice_export)
        layout.addLayout(controls)
        self.volume_plot = PlotWidget()
        layout.addWidget(self.volume_plot, 1)
        self.volume_note = label('No thermal volume loaded.')
        layout.addWidget(self.volume_note)
        self.volume = None
        self.quantity.currentIndexChanged.connect(self.draw_volume)
        self.slice.valueChanged.connect(self.draw_volume)
        self.tabs.insertTab(0, page, 'Temperature map')
        install_result_picker(self, {})
        self._clear_volume()

    def _clear_volume(self):
        self.volume = None
        self.volume_plot.clear()
        self.volume_note.setText('No saved thermal volume is available for this run.')
        with QSignalBlocker(self.slice):
            self.slice.setRange(0, 0)
        for control in (self.quantity, self.slice, self.slice_export):
            control.setEnabled(False)

    def load_directory(self, path):
        self._clear_volume()
        loaded = super().load_directory(path)
        file = Path(path)/'thermal_volume.npz'
        if loaded and file.is_file():
            try:
                with np.load(file, allow_pickle=False) as data:
                    volume = {key: data[key].copy() for key in ('temperature_K', 'temperature_rise_K', 'heat_density_W_m3', 'x', 'y', 'z')}
                for key in ('x', 'y', 'z'):
                    values = volume[key]
                    if (not np.issubdtype(values.dtype, np.number) or not np.isrealobj(values)
                            or values.ndim != 1 or not len(values) or not np.isfinite(values).all()
                            or np.any(np.diff(values) <= 0)):
                        raise ValueError(key+' coordinates must be finite, increasing, one-dimensional values.')
                shape = tuple(len(volume[key]) for key in ('x', 'y', 'z'))
                for key in ('temperature_K', 'temperature_rise_K', 'heat_density_W_m3'):
                    values = volume[key]
                    if (values.shape != shape or not np.issubdtype(values.dtype, np.number)
                            or not np.isrealobj(values) or not np.isfinite(values).all()):
                        raise ValueError(key+' must contain finite real values matching the saved coordinates.')
                self.volume = volume
                with QSignalBlocker(self.slice):
                    self.slice.setRange(0, shape[2]-1)
                self.quantity.setEnabled(True)
                self.slice.setEnabled(shape[2] > 1)
                self.slice_export.setEnabled(True)
                self.tabs.setCurrentIndex(0)
                self.draw_volume()
            except (OSError, ValueError, KeyError, EOFError, BadZipFile) as exc:
                self._clear_volume()
                self.volume_note.setText('Could not load the saved thermal volume: '+str(exc))
        return loaded

    def draw_volume(self, *args):
        if self.volume is None:
            return
        quantity = self.quantity.currentData()
        z = self.slice.value()
        values = self.volume[quantity][:, :, z]
        fig = Figure(figsize=(7, 4), layout='constrained')
        axis = fig.add_subplot(111)
        image = axis.pcolormesh(self.volume['x']*1e6, self.volume['y']*1e6, values.T, shading='nearest')
        fig.colorbar(image, ax=axis, label=self.quantity.currentText())
        axis.set_xlabel('x (µm)'); axis.set_ylabel('y (µm)')
        axis.set_aspect('equal')
        self.volume_plot.draw_figure(fig)
        self.volume_note.setText(f'z = {self.volume["z"][z]*1e6:.6g} µm. Saved prescribed-heat solution; no current or temperature feedback is inferred.')

    def export_slice(self):
        if self.volume is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export thermal slice', 'thermal-slice.csv', 'CSV (*.csv)')
        if not path:
            return
        quantity, k = self.quantity.currentData(), self.slice.value()
        try:
            with open(path, 'w', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream)
                writer.writerow(['x_um', 'y_um', 'z_um', quantity])
                for i, x in enumerate(self.volume['x']):
                    for j, y in enumerate(self.volume['y']):
                        writer.writerow([x*1e6, y*1e6, self.volume['z'][k]*1e6, self.volume[quantity][i, j, k]])
        except OSError as exc:
            self.volume_note.setText('Export failed: '+str(exc))


class ThermalSetupWorkspace(ResearchWorkspaceBase):
    workspace_id = 'thermal'
    state_key = 'thermal'

    def __init__(self, store, parent=None, *, document_id=None):
        super().__init__(store, parent, document_id=document_id)
        self._layer_ids, self._material_ids = [], []
        self._power_drafts, self._conductivity_drafts = {}, {}
        self.heading.setText('Steady heat flow')
        self.description.setText('Prescribed layer power on the current editable device and mesh. '
            'This computes heat conduction with fixed material properties; it does not infer electrical heating or electrothermal feedback.')
        _, domain = self.add_section('Device & heat sources', 'heat_sources')
        self.device_note = label('')
        domain.addWidget(self.device_note)
        domain.addWidget(button('Edit device geometry and mesh', lambda: self.diagnosticRequested.emit(dict(
            workspace='structure', section='device', field='device', message='Edit the device and mesh used for heat conduction.'))))
        domain.addWidget(button('Refresh layer and material list', self.sync_device))
        domain.addWidget(label('Enter total prescribed watts per layer. Power is distributed uniformly over that layer’s solid volume.'))
        self.powers = _table(['Layer', 'Prescribed power (W)'], 'Layer heat sources')
        domain.addWidget(self.powers)
        self.fields['power_by_layer_W'] = self.powers
        _, materials = self.add_section('Conductivity', 'materials')
        materials.addWidget(label('Supply a positive conductivity and a source for every material present in the mesh. '
            'No library thermal property is assumed. Units: W/(m K).'))
        self.conductivities = _table(['Material', 'Conductivity (W/m K)', 'Source / reference'], 'Thermal material properties with sources')
        materials.addWidget(self.conductivities)
        self.fields['conductivity'] = self.conductivities
        mform = QFormLayout()
        self.void_k = self.line(mform, 'Void conductivity (if mesh contains void)', 'void_conductivity_W_mK', '', 'W/(m K)')
        materials.addLayout(mform)
        _, boundaries = self.add_section('Boundary conditions', 'boundaries')
        form = QFormLayout()
        self.ambient = self.line(form, 'Reference temperature', 'ambient_temperature_K', '300', 'K')
        self.limit = self.line(form, 'Material validity limit (optional)', 'temperature_limit_K', '', 'K')
        boundaries.addLayout(form)
        boundaries.addWidget(label('Every face is explicit. At least one face must exchange heat. '
            'Fixed temperature and convection use a reservoir temperature; convection also needs a positive heat-transfer coefficient.'))
        self.boundaries = _table(['Face', 'Kind', 'Reservoir temperature (K)', 'Convection coefficient (W/m² K)'], 'Thermal boundary faces')
        _fill(self.boundaries, [[face, 'fixed_temperature' if face == 'z_max' else 'insulated', '300', '']
            for face in ('x_min', 'x_max', 'y_min', 'y_max', 'z_min', 'z_max')])
        for row in range(6):
            self.boundaries.item(row, 0).setFlags(self.boundaries.item(row, 0).flags() & ~Qt.ItemFlag.ItemIsEditable)
            choices = QComboBox()
            choices.addItems(['insulated', 'fixed_temperature', 'convection'])
            choices.setCurrentText('fixed_temperature' if row == 5 else 'insulated')
            choices.setAccessibleName(_rows(self.boundaries)[row][0]+' heat boundary')
            choices.currentIndexChanged.connect(self._edited)
            self.boundaries.setCellWidget(row, 1, choices)
        self.fields['boundaries'] = self.boundaries
        boundaries.addWidget(self.boundaries)
        self.results = ThermalResultsPanel(store, self)
        self.tabs.addTab(self.results, 'Results')
        self.powers.cellChanged.connect(self._edited)
        self.conductivities.cellChanged.connect(self._edited)
        self.boundaries.cellChanged.connect(self._edited)
        self.sync_device()
        self._build_guided_setup()
        from qt_study_device_editor import StudyDeviceEditor
        _, editor_layout = self.add_section('Edit thermal domain', 'device_editor')
        self.device_editor = StudyDeviceEditor(self)
        self.device_editor.continue_requested.connect(lambda: self.study_flow.show_stage(1))
        editor_layout.addWidget(self.device_editor, 1)
        self.finish_build()
        from qt_study_flow import install_study_flow
        self.study_flow = install_study_flow(self, [('Device & power', [0, 'device_editor']), ('Conductivity', [1]), ('Cooling faces', [2]), ('Numerics & validity', [4])],
            subtitle='Use the current device, prescribe its heat, then define how that heat leaves the device.',
            details='Steady heat conduction with constant material properties. Electrical heating and temperature feedback are separate Advanced Transport models.')
        for table in (self.powers, self.conductivities, self.boundaries):
            table.cellChanged.connect(self.journey_execution.invalidate)
        for row in range(self.boundaries.rowCount()):
            self.boundaries.cellWidget(row, 1).currentIndexChanged.connect(self.journey_execution.invalidate)
        self._refresh_clean_ui()

    def journey_review_fields(self):
        """Review raw thermal drafts without parsing them or changing the device."""
        device = getattr(self.store, 'device', None) or {}
        layers = [row for row in device.get('layers', []) if row.get('enabled', True)]
        shapes = [row for row in device.get('shapes', []) if row.get('enabled', True)]
        mesh = device.get('mesh', {})
        materials = {row['id']: row.get('name', row['id']) for row in getattr(self.store, 'electrical_materials', [])}
        rows = [('', 'Input state', 'Draft values are shown as entered; Check inputs validates them. Geometry and mesh below are the applied device values.'),
            ('device', 'Applied device geometry',
             str(device.get('width_um', 'Not supplied'))+' × '+str(device.get('depth_um', 'Not supplied'))+
             ' µm in x × y; '+str(len(layers))+' active layers; '+str(len(shapes))+' active patterns', 'device_editor'),
            ('device.mesh', 'Applied mesh', ', '.join(str(key)+' = '+str(mesh[key])
             for key in ('nx', 'ny', 'nz_per_layer', 'max_nodes') if key in mesh) or 'Not supplied', 'device_editor')]
        for layer in layers:
            rows.append(('device', 'Applied layer · '+str(layer.get('name', layer['id'])),
                str(layer.get('thickness_um', 'Not supplied'))+' µm; material '+
                str(materials.get(layer.get('material_id'), layer.get('material_id', 'Not supplied'))), 'device_editor'))
        for row in _rows(self.powers):
            rows.append(('power_by_layer_W', 'Layer power · '+row[0], (row[1] or 'Not supplied')+' W', 'heat_sources'))
        for row in _rows(self.conductivities):
            rows.append(('conductivity', 'Conductivity · '+row[0], (row[1] or 'Not supplied')+
                ' W/(m K); source: '+(row[2] or 'Not supplied'), 'materials'))
        for index, row in enumerate(_rows(self.boundaries)):
            kind = self.boundaries.cellWidget(index, 1).currentText()
            text = 'Insulated · no heat flux' if kind == 'insulated' else (
                'Fixed temperature' if kind == 'fixed_temperature' else 'Convection')+'; reservoir '+(row[2] or 'Not supplied')+' K'
            if kind == 'convection':
                text += '; heat-transfer coefficient '+(row[3] or 'Not supplied')+' W/(m² K)'
            rows.append(('boundaries.'+row[0]+'.kind', 'Cooling · '+self.face_names.get(row[0], row[0]), text, 'boundaries'))
        rows.extend([
            ('ambient_temperature_K', 'Reference temperature', (self.ambient.text() or 'Not supplied')+' K', 'review'),
            ('temperature_limit_K', 'Material validity limit', self.limit.text()+' K' if self.limit.text() else 'Not supplied', 'review'),
            ('void_conductivity_W_mK', 'Void conductivity', self.void_k.text()+' W/(m K)' if self.void_k.text() else 'Not supplied', 'materials')])
        return rows

    def _build_guided_setup(self):
        self.heading.setText('Steady heat flow'); self.heading.setObjectName('studyPageTitle')
        self.ambient.setParent(self); self.limit.setParent(self)
        self.power_inspector = TableRowInspector(self.powers,
            [('layer', 'Layer', None), ('power', 'Total prescribed power (W)', None)], 'Selected heated layer')
        self.power_inspector.note.setText('This is total power in watts, distributed uniformly over the solid volume of the selected layer. Zero means no prescribed heat in that layer.')
        self.material_inspector = TableRowInspector(self.conductivities,
            [('material', 'Material', None), ('conductivity', 'Thermal conductivity (W / m K)', None),
             ('source', 'Source / reference', None)], 'Selected thermal material')
        self.material_inspector.note.setText('A positive conductivity and its source are required for every material in the mesh. No thermal conductivity is inferred from the optical index.')
        conductivity_label=self.material_inspector.form.labelForField(self.material_inspector.editors['conductivity'])
        conductivity_label.setWordWrap(False)
        conductivity_label.setMinimumWidth(conductivity_label.fontMetrics().horizontalAdvance(conductivity_label.text())+10)
        self.boundary_inspector = TableRowInspector(self.boundaries,
            [('face', 'Device face', None), ('kind', 'Heat boundary', [('Insulated · no heat flux', 'insulated'),
              ('Fixed temperature', 'fixed_temperature'), ('Convection to a reservoir', 'convection')]),
             ('temperature_K', 'Reservoir temperature (K)', None),
             ('coefficient_W_m2K', 'Heat-transfer coefficient (W / m² K)', None)], 'Selected cooling face')
        self.boundary_inspector.note.setText('z is depth measured downwards: z_min is the top and z_max is the bottom. At least one face must exchange heat.')
        self.face_names={'x_min':'Left · x_min','x_max':'Right · x_max','y_min':'Front · y_min','y_max':'Back · y_max',
                         'z_min':'Top · z_min','z_max':'Bottom · z_max'}
        self.boundary_inspector.selector_display=lambda value,row:self.face_names.get(value,value)
        self.boundary_inspector.set_field_visible('face',False)
        self.power_inspector.set_field_visible('layer',False)
        self.material_inspector.set_field_visible('material',False)
        body=QWidget(); box=QVBoxLayout(body)
        box.addWidget(self.device_note)
        actions=QHBoxLayout()
        actions.addWidget(button('Edit device and mesh…', self.edit_device))
        actions.addWidget(button('Refresh from device', self.sync_device)); actions.addStretch(); box.addLayout(actions)
        self.device_splitter=QSplitter(Qt.Orientation.Horizontal)
        context=QWidget(); left=QVBoxLayout(context); left.setContentsMargins(0,0,0,0)
        self.layer_preview=PlotWidget(); self.layer_preview.setMinimumSize(260,300); self.layer_preview.toolbar.hide()
        self.layer_preview.canvas.mpl_connect('button_press_event', self._select_heated_layer)
        left.addWidget(self.layer_preview,1)
        self.layer_preview_note=label('Layer-stack schematic; patterned shapes are included in the saved device, not drawn in this section view.')
        left.addWidget(self.layer_preview_note)
        self.power_scroll=QScrollArea(); self.power_scroll.setWidgetResizable(True)
        self.power_scroll.setWidget(self.power_inspector); self.power_scroll.setMinimumWidth(280)
        self.device_splitter.addWidget(context); self.device_splitter.addWidget(self.power_scroll)
        self.device_splitter.setStretchFactor(0,3); self.device_splitter.setStretchFactor(1,2)
        box.addWidget(self.device_splitter,1); replace_section(self,0,body)
        body=QWidget(); box=QVBoxLayout(body)
        from qt_custom_device import DeviceCanvas
        self.material_splitter = QSplitter(Qt.Orientation.Horizontal)
        context = QWidget(); context_layout = QVBoxLayout(context)
        context_layout.addWidget(label('Thermal material assignments', 'setupHeading'))
        self.material_canvas = DeviceCanvas('3d'); self.material_canvas.setMinimumSize(220, 280)
        self.material_canvas.object_selected.connect(self._select_thermal_material)
        context_layout.addWidget(self.material_canvas, 1)
        self.material_context = label('Select a device layer to edit its thermal conductivity and source.')
        context_layout.addWidget(self.material_context)
        self.material_splitter.addWidget(context)
        self.material_scroll = QScrollArea(); self.material_scroll.setWidgetResizable(True)
        self.material_scroll.setWidget(self.material_inspector); self.material_scroll.setMinimumWidth(290)
        self.material_scroll.setMaximumWidth(480)
        self.material_splitter.addWidget(self.material_scroll)
        self.material_splitter.setStretchFactor(0, 3); self.material_splitter.setStretchFactor(1, 2)
        box.addWidget(self.material_splitter, 1)
        self.void_toggle=QCheckBox('Void / ambient material conductivity'); box.addWidget(self.void_toggle)
        self.void_body=QWidget(); form=native_form(self.void_body)
        form.addRow('Void conductivity (W / m K)',self.void_k)
        box.addWidget(self.void_body); self.void_body.hide(); self.void_toggle.toggled.connect(self.void_body.setVisible)
        box.addWidget(button('Edit material assignments in Structure…', self.edit_device))
        replace_section(self,1,body)
        body=QWidget(); box=QVBoxLayout(body)
        self.boundary_summary=label(''); box.addWidget(self.boundary_summary)
        from qt_custom_device import DeviceCanvas
        self.cooling_splitter = QSplitter(Qt.Orientation.Horizontal)
        face_body = QWidget(); face_layout = QVBoxLayout(face_body)
        self.cooling_canvas = DeviceCanvas('3d')
        self.cooling_canvas.setMinimumSize(220, 260)
        self.cooling_canvas.pick_surface = True
        self.cooling_canvas.surface_picked.connect(self._pick_cooling_surface)
        face_layout.addWidget(self.cooling_canvas, 1)
        self.cooling_note = label('Select an exterior face in the actual device, or use the six face buttons. Top is z_min; bottom is z_max.')
        face_layout.addWidget(self.cooling_note)
        buttons = QGridLayout(); self.cooling_face_buttons = {}
        for i, (face, caption) in enumerate(self.face_names.items()):
            action = button(caption, lambda checked=False, value=face: self.select_cooling_face(value))
            action.setAccessibleName('Edit cooling boundary '+caption)
            buttons.addWidget(action, i//2, i%2); self.cooling_face_buttons[face] = action
        face_layout.addLayout(buttons)
        self.cooling_splitter.addWidget(face_body)
        self.cooling_splitter.addWidget(self.boundary_inspector)
        self.cooling_splitter.setStretchFactor(0, 3); self.cooling_splitter.setStretchFactor(1, 2)
        box.addWidget(self.cooling_splitter, 1)
        replace_section(self,2,body)
        # Keep original Results index 3; append the new review page at index 4.
        _, box=self.add_section('Review & calculate', 'review')
        form=native_form(); form.addRow('Reference temperature (K)',self.ambient)
        form.addRow('Maximum valid material temperature (K, optional)',self.limit); box.addLayout(form)
        self.thermal_review=QTextBrowser(); self.thermal_review.setMinimumHeight(240)
        box.addWidget(self.thermal_review,1)
        box.addWidget(label('This solver is included with the program. No external installation is needed.'))
        self._preview_timer=QTimer(self); self._preview_timer.setSingleShot(True); self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self.preview_device)
        for table in (self.powers,self.conductivities,self.boundaries):
            table.cellChanged.connect(self._queue_clean_refresh)
            table.currentCellChanged.connect(self._queue_clean_refresh)
        for i in range(6): self.boundaries.cellWidget(i,1).currentIndexChanged.connect(self._refresh_clean_ui)
        for edit in (self.ambient,self.limit): edit.textChanged.connect(self._refresh_clean_ui)
        from qt_common import theme_manager
        theme_manager().changed.connect(self._restyle_inspectors)
        restyle_inspectors(self)
        self._queue_clean_refresh()

    def _restyle_inspectors(self, *args):
        """A QObject-bound receiver disconnects when this page is deleted."""
        restyle_inspectors(self)

    def edit_device(self):
        if not self._is_active_document():
            return False
        self.select_section('device_editor')
        return self.device_editor.open_editor('device')

    def select_cooling_face(self, face):
        if not self._is_active_document() or face not in self.face_names:
            return False
        return self.open_diagnostic(dict(field='boundaries.'+face+'.kind'))

    def _pick_cooling_surface(self, identity, surface):
        device = self.store.device or {}
        layers = [row for row in device.get('layers', []) if row.get('enabled', True)]
        if not layers:
            return
        attached = next((row.get('layer_id', row['id']) for group in ('layers','shapes') for row in device.get(group, []) if row['id'] == identity), '')
        if surface == 'top' and attached != layers[0]['id'] or surface == 'bottom' and attached != layers[-1]['id']:
            self.cooling_note.setText('That is an internal layer surface. Select an exterior domain face or use its face button.')
            return
        face = {'top':'z_min','bottom':'z_max','side_x_min':'x_min','side_x_max':'x_max','side_y_min':'y_min','side_y_max':'y_max'}.get(surface)
        if face:
            self.select_cooling_face(face)

    def _select_heated_layer(self, event):
        if event.ydata is None or not self._is_active_document():
            return
        from device_model import layer_bounds
        for layer in layer_bounds(self.store.device or {}):
            if layer['z_min_um'] <= event.ydata <= layer['z_max_um'] and layer['id'] in self._layer_ids:
                self.open_diagnostic(dict(field='power_by_layer_W', object_id=layer['id']))
                return

    def _select_thermal_material(self, identity):
        row = next((row for group in ('layers','shapes') for row in (self.store.device or {}).get(group,[]) if row['id']==identity), None)
        if row and row.get('material_id') in self._material_ids:
            self.material_canvas.set_device(self.store.device, identity)
            self.open_diagnostic(dict(field='conductivity', object_id=row['material_id']))

    def _queue_clean_refresh(self,*args):
        if hasattr(self,'_preview_timer'): self._preview_timer.start()
        self._refresh_clean_ui()

    def _refresh_clean_ui(self,*args):
        if not hasattr(self,'power_inspector'): return
        if hasattr(self, 'cooling_canvas'):
            self.cooling_canvas.set_device(self.store.device or {})
        if hasattr(self, 'material_canvas'):
            device=self.store.device or {}
            self.material_canvas.set_device(device, self.material_canvas.selected)
            index=self.conductivities.currentRow()
            material=self._material_ids[index] if 0<=index<len(self._material_ids) else ''
            used=[row['name'] for row in device.get('layers',[]) if row.get('material_id')==material and row.get('enabled',True)]
            self.material_context.setText('Selected material: '+material+'\nUsed by layers: '+(', '.join(used) or 'patterned material / void')+'\nSupply positive constant isotropic conductivity and its source. No electrical heat is inferred.')
        for inspector in (self.power_inspector,self.material_inspector,self.boundary_inspector): inspector.refresh()
        row=self.boundaries.currentRow()
        kind=self.boundaries.cellWidget(row,1).currentText() if row>=0 else 'insulated'
        self.boundary_inspector.set_field_visible('temperature_K',kind!='insulated')
        self.boundary_inspector.set_field_visible('coefficient_W_m2K',kind=='convection')
        descriptions=self.face_names
        with QSignalBlocker(self.boundary_inspector.selector):
            for i,values in enumerate(_rows(self.boundaries)):
                self.boundary_inspector.selector.setItemText(i,descriptions.get(values[0],values[0]))
        sinks=[descriptions[_rows(self.boundaries)[i][0]] for i in range(6) if self.boundaries.cellWidget(i,1).currentText()!='insulated']
        self.boundary_summary.setText('Heat leaves through: '+(', '.join(sinks) if sinks else 'none — choose a fixed temperature or convection face.'))
        if not hasattr(self,'thermal_review'): return
        powers=_rows(self.powers); missing=[row[0] for row in _rows(self.conductivities) if not row[1].strip() or not row[2].strip()]
        self.thermal_review.setHtml('<h3>What will be calculated</h3><p>Steady temperature and heat-flow balance for the current finite device.</p>'+
            '<p><b>Prescribed layer powers:</b> '+('; '.join(escape(row[0])+': '+escape(row[1])+' W' for row in powers) or 'No active layers')+'</p>'+
            '<p><b>Material assignments:</b> '+(escape(', '.join(missing))+' need conductivity and source.' if missing else 'Each listed material has a conductivity and source.')+'</p>'+
            '<p><b>Cooling:</b> '+escape(', '.join(sinks) or 'No heat-exchange face selected')+'</p>'+
            '<p>Temperature rise is relative to '+escape(self.ambient.text())+' K. '+
            ('The material-validity guard is '+escape(self.limit.text())+' K. ' if self.limit.text().strip() else '')+
            'The guard does not establish thermal runaway. Electrical power and temperature feedback are not inferred.</p>')

    def preview_device(self):
        from device_model import layer_bounds
        from matplotlib.patches import Rectangle
        device=getattr(self.store,'device',None) or {}
        try:
            layers=layer_bounds(device)
            fig=Figure(figsize=(6,4),layout='constrained'); ax=fig.add_subplot(111)
            palette=['#569CD6','#7CB8A0','#D6A66A','#A89BD1','#D17E8C']
            for i,layer in enumerate(layers):
                top,bottom=layer['z_min_um'],layer['z_max_um']
                selected=i==self.powers.currentRow()
                ax.add_patch(Rectangle((0,top),1,bottom-top,facecolor=palette[i%len(palette)],alpha=.65,
                    edgecolor='#2563EB' if selected else '#52657A',linewidth=2.5 if selected else 1))
                ax.text(.5,(top+bottom)/2,layer.get('name',layer['id']),ha='center',va='center',fontsize=9,clip_on=True)
            if layers:
                ax.set_xlim(0,1); ax.set_ylim(layers[-1]['z_max_um'],0)
                ax.set_ylabel('Depth z (µm) · top to bottom'); ax.set_xticks([])
                ax.set_title('Current device layer stack',fontsize=11)
            else:
                ax.text(.5,.5,'Create a device in Structure',ha='center',va='center'); ax.set_axis_off()
            self.layer_preview.draw_figure(fig)
        except (ValueError,KeyError,TypeError) as exc:
            self.layer_preview_note.setText('Device preview needs attention: '+str(exc)+'. Last valid view retained.')

    def adapt_layout(self):
        if hasattr(self,'study_flow'): self.study_flow.adapt_layout()
        if hasattr(self,'device_splitter'):
            self.device_splitter.setMinimumHeight(330)
            self.device_splitter.setMaximumHeight(390 if self.width()<1000 else 550)
            self.device_splitter.setSizes([max(280,self.width()-370),320])
        if hasattr(self, 'cooling_splitter'):
            self.cooling_splitter.setOrientation(Qt.Orientation.Vertical if self.width()<900 else Qt.Orientation.Horizontal)
        if hasattr(self, 'material_splitter'):
            self.material_splitter.setOrientation(Qt.Orientation.Vertical if self.width()<900 else Qt.Orientation.Horizontal)
            self.material_scroll.setMaximumWidth(16777215 if self.width()<900 else 480)

    def _store_changed(self, reason=''):
        super()._store_changed(reason)
        if not self._is_active_document():
            return
        if hasattr(self,'power_inspector') and reason in ('device','structure','electrical_materials','project','study','load','reset','all'):
            # Reconcile by stable IDs so returning from Structure never shows an old device.
            self.sync_device()

    def _capture_assignments(self):
        # Keep raw, unfinished values for disabled objects and geometry undo.
        # Only active rows are parsed by options(); the cache is document-local.
        self._power_drafts.update({identity: row[1] for identity, row in zip(self._layer_ids, _rows(self.powers))})
        self._conductivity_drafts.update({identity: row[1:] for identity, row in zip(self._material_ids, _rows(self.conductivities))})

    def sync_device(self):
        if not self._is_active_document():
            return
        device = getattr(self.store, 'device', None) or {}
        mesh=device.get('mesh',{})
        self.device_note.setText(str(device.get('name', 'No editable device. Create one in Structure.'))+
            ' · '+str(len([row for row in device.get('layers',[]) if row.get('enabled',True)]))+' active layers'+
            ' · mesh '+', '.join(str(key)+' '+str(value) for key,value in mesh.items() if key in ('nx','ny','nz','nz_per_layer')))
        self._capture_assignments()
        layers = [row for row in device.get('layers', []) if row.get('enabled', True)]
        materials = list(getattr(self.store, 'electrical_materials', []))
        used = {row.get('material_id') for row in layers}
        used.update(row.get('material_id') for row in device.get('shapes', []) if row.get('enabled', True) and row.get('operation') != 'void')
        names = {row['id']: row.get('name', row['id']) for row in materials}
        self._layer_ids = [row['id'] for row in layers]
        self._material_ids = sorted(used-{None, ''})
        _fill(self.powers, [[row['name'], self._power_drafts.get(row['id'], '0')] for row in layers])
        _fill(self.conductivities, [[names.get(identity, identity)]+self._conductivity_drafts.get(identity, ['', '']) for identity in self._material_ids])
        for table in (self.powers, self.conductivities):
            for row in range(table.rowCount()):
                table.item(row, 0).setFlags(table.item(row, 0).flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._edited()
        self._queue_clean_refresh()

    def draft(self):
        self._capture_assignments()
        state = super().draft()
        state.update(power_drafts=deepcopy(self._power_drafts), conductivity_drafts=deepcopy(self._conductivity_drafts),
            layer_ids=list(self._layer_ids), material_ids=list(self._material_ids), powers=_rows(self.powers),
            conductivities=_rows(self.conductivities), boundaries=_rows(self.boundaries),
            boundary_kinds=[self.boundaries.cellWidget(i, 1).currentText() for i in range(6)])
        return state

    def restore_draft(self, state):
        super().restore_draft(state)
        # Reset on document replacement; older drafts are seeded from their rows.
        self._power_drafts = deepcopy(state.get('power_drafts', {}))
        self._conductivity_drafts = deepcopy(state.get('conductivity_drafts', {}))
        self._layer_ids = list(state.get('layer_ids', self._layer_ids))
        self._material_ids = list(state.get('material_ids', self._material_ids))
        for key, table in [('powers', self.powers), ('conductivities', self.conductivities)]:
            if key in state:
                _fill(table, state[key])
        if 'boundaries' in state:
            for i, row in enumerate(state['boundaries'][:6]):
                for j in (2, 3):
                    self.boundaries.item(i, j).setText(row[j])
        for i, kind in enumerate(state.get('boundary_kinds', [])):
            self.boundaries.cellWidget(i, 1).setCurrentText(kind)
        for table in (self.powers,self.conductivities):
            for row in range(table.rowCount()):
                table.item(row,0).setFlags(table.item(row,0).flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._capture_assignments()
        self._queue_clean_refresh()

    def options(self):
        device = getattr(self.store, 'device', None)
        if not device:
            raise FieldError('device', 'Create an editable device in Structure before running heat flow.')
        valid_layers = {row['id'] for row in device['layers'] if row.get('enabled', True)}
        powers, conductivities, boundaries = {}, {}, {}
        for identity, row in zip(self._layer_ids, _rows(self.powers)):
            if identity not in valid_layers:
                raise FieldError('power_by_layer_W', 'This layer was removed or disabled. Refresh the device list.', identity)
            powers[identity] = number(row[1], 'power_by_layer_W', minimum=0, units='W', object_id=identity)
        if set(self._layer_ids) != valid_layers:
            raise FieldError('power_by_layer_W', 'The device has new layers. Refresh the device list.')
        for identity, row in zip(self._material_ids, _rows(self.conductivities)):
            conductivities[identity] = dict(value_W_mK=number(row[1], 'conductivity', positive=True, units='W/(m K)', object_id=identity), source=row[2].strip())
            if not row[2].strip():
                raise FieldError('conductivity.source', 'Enter a source for this thermal conductivity.', identity)
        for i, row in enumerate(_rows(self.boundaries)):
            face, _, temp, coeff = row
            kind = self.boundaries.cellWidget(i, 1).currentText()
            boundary = {'kind': kind}
            if kind != 'insulated':
                boundary['temperature_K'] = number(temp, 'boundaries.'+face+'.temperature_K', positive=True, units='K')
            if kind == 'convection':
                boundary['coefficient_W_m2K'] = number(coeff, 'boundaries.'+face+'.coefficient_W_m2K', positive=True, units='W/(m² K)')
            boundaries[face] = boundary
        if not any(row['kind'] != 'insulated' for row in boundaries.values()):
            raise FieldError('boundaries', 'Select at least one fixed-temperature or convection boundary.')
        cfg = dict(power_by_layer_W=powers, conductivity=conductivities, boundaries=boundaries,
            ambient_temperature_K=number(self.ambient.text(), 'ambient_temperature_K', positive=True, units='K'))
        for key, edit in [('void_conductivity_W_mK', self.void_k), ('temperature_limit_K', self.limit)]:
            if edit.text().strip():
                cfg[key] = number(edit.text(), key, positive=True)
        return dict(engine='thermal', study='steady_state', settings=cfg)

    def open_diagnostic(self, target):
        if target.get('field') == 'device':
            return self.edit_device()
        identity, field = target.get('object_id'), target.get('field', '').removeprefix('settings.')
        if identity and (field.startswith('power') or field.startswith('conductivity')):
            ids, table = (self._layer_ids, self.powers) if field.startswith('power') else (self._material_ids, self.conductivities)
            if identity not in ids:
                self.status.setText('That object is no longer in this editor. Refresh the device list and recheck inputs.')
                return False
            column = 2 if field.endswith('.source') else 1
            table.setCurrentCell(ids.index(identity), column)
            is_power=field.startswith('power')
            self.tabs.setCurrentIndex(0 if is_power else 1)
            inspector=self.power_inspector if is_power else self.material_inspector
            return inspector.reveal(ids.index(identity),'power' if is_power else 'source' if column==2 else 'conductivity',target.get('message',''))
        if field.startswith('boundaries.'):
            parts = field.split('.')
            faces = [row[0] for row in _rows(self.boundaries)]
            if parts[1] in faces:
                row = faces.index(parts[1])
                column = 1 if field.endswith('.kind') else 3 if field.endswith('coefficient_W_m2K') else 2
                self.boundaries.setCurrentCell(row, column)
                self.tabs.setCurrentIndex(2)
                return self.boundary_inspector.reveal(row,{1:'kind',2:'temperature_K',3:'coefficient_W_m2K'}[column],target.get('message',''))
        if field=='boundaries':
            self.tabs.setCurrentIndex(2)
            return self.boundary_inspector.reveal(max(0,self.boundaries.currentRow()),'kind',target.get('message',''))
        if field=='conductivity':
            self.tabs.setCurrentIndex(1)
            return self.material_inspector.reveal(max(0,self.conductivities.currentRow()),'conductivity',target.get('message',''))
        if field=='void_conductivity_W_mK': self.void_toggle.setChecked(True)
        return super().open_diagnostic(target)
