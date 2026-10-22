"""Native, draft-preserving setup for editable PCSEL optical and conformal studies.

The existing typed trees remain the canonical drafts. Friendly controls edit those
same items, so incomplete text and properties outside these forms are not lost.
"""
from __future__ import annotations

import math
import uuid
from copy import deepcopy

from PyQt6.QtCore import Qt, QPointF, QRectF, QSize, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QAbstractButton, QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from qt_research_common import button, label
from qt_research_studies import StructuredStudyWorkspace
from qt_input_diagnostics import reveal_and_focus


MODEL_LABELS = {
    'vertical': ('Vertical confinement', 'Solve the vertical TE mode of the editable layer stack.'),
    'cwt': ('Unit-cell coupling · CWT', 'Calculate four-wave TE coupling and radiative loss for the patterned cell.'),
    'gme': ('Slab modes · GME', 'Find guided-mode-expansion resonances at editable in-plane wavevectors.'),
    'rcwa_poles': ('Resonance poles · RCWA', 'Search complex-frequency resonances from explicit seeds and inspect pole fields.'),
    'finite': ('Finite-aperture modes', 'Find outgoing four-wave modes in the specified rectangular laser aperture.'),
    'beam': ('Far-field beam', 'Calculate a Fraunhofer beam from a compatible finite mode. Passive modes do not predict output power.'),
    'aperture': ('Aperture carriers & heating', 'Use explicit calibrated load data, carrier, optical and thermal parameters for the reduced aperture model.'),
}
MODEL_TITLES = dict(vertical='PCSEL vertical modes', cwt='PCSEL coupled-wave modes',
    finite='PCSEL finite-area modes', beam='PCSEL far-field beam', aperture='PCSEL aperture response',
    gme='PCSEL guided-mode expansion', rcwa_poles='PCSEL RCWA resonances')


def _child(item, name):
    return next((item.child(i) for i in range(item.childCount()) if item.child(i).text(0) == str(name)), None)


def _text(item, name, default=''):
    value = _child(item, name)
    return value.text(1) if value is not None else default


def _kind(item):
    return item.data(0, Qt.ItemDataRole.UserRole)


def _clear(layout):
    while layout.count():
        entry = layout.takeAt(0)
        if entry.widget():
            entry.widget().hide()
            entry.widget().deleteLater()
        elif entry.layout():
            _clear(entry.layout())


TITLES = {
    'name': 'Name', 'thickness_nm': 'Thickness (nm)', 'thickness_um': 'Thickness (µm)',
    'index': 'Refractive index n', 'material': 'Material ID', 'qw': 'Quantum well',
    'patterned': 'Apply cell pattern', 'radius': 'Radius / a', 'radius_um': 'Radius (µm)',
    'center': 'Center (x/a, y/a)', 'center_um': 'Center (x, y) in µm',
    'vertices': 'Vertices (x/a, y/a)', 'vertices_um': 'Vertices (x, y) in µm',
    'donors_cm3': 'Donors (cm⁻³)', 'acceptors_cm3': 'Acceptors (cm⁻³)',
    'epsilon_r': 'Relative permittivity', 'Nc_cm3': 'Conduction density Nc (cm⁻³)',
    'Nv_cm3': 'Valence density Nv (cm⁻³)', 'bandgap_eV': 'Band gap (eV)',
    'affinity_eV': 'Electron affinity (eV)', 'electron_mobility_cm2_Vs': 'Electron mobility (cm²/V·s)',
    'hole_mobility_cm2_Vs': 'Hole mobility (cm²/V·s)', 'B_cm3_s': 'Radiative B (cm³/s)',
    'C_cm6_s': 'Auger C (cm⁶/s)', 'tau_s': 'Lifetime (s)', 'source': 'Source / assumption',
    'executable': 'Python interpreter', 'distro': 'WSL distribution', 'mode': 'Run on',
    'timeout_s': 'Time limit (s)', 'module_paths': 'Python module folders',
    'library_paths': 'Shared-library folders', 'edge_segments': 'Segments per cell edge',
    'circle_segments': 'Segments per circle', 'xy_size_um': 'In-plane mesh size (µm)',
    'z_max_step_um': 'Largest vertical step (µm)', 'maximum_tetrahedra': 'Tetrahedron limit',
    'grid_n': 'Aperture cells per axis', 'maximum_iterations': 'Iteration limit',
    'temperature_tolerance_K': 'Temperature tolerance (K)', 'heated': 'Include self-heating',
    'currents_A': 'Requested currents (A)', 'voltage_bracket_V': 'Voltage bracket (V)',
    'load_anchors': 'Source-bound load anchors', 'load_source': 'Load-calibration source',
    'load_domain': 'Accepted calibration domain', 'contacts': 'Aperture contacts',
    'mode_weight': 'Optical-mode weights', 'sink_K': 'Heat-sink temperature (K)',
    'reference_temperature_K': 'Reference temperature (K)', 'max_temperature_K': 'Temperature limit (K)',
    'substrate_um': 'Substrate thickness (µm)', 'substrate_k_W_mK': 'Substrate conductivity (W/m·K)',
    'sheet_ohm_square': 'Sheet resistance (Ω/□)', 'sheet_temperature_exponent': 'Sheet temperature exponent',
    'thermal_k_exponent': 'Conductivity temperature exponent', 'interface_R_m2K_W': 'Interface resistance (m²·K/W)',
    'epitaxial_R_m2K_W': 'Epitaxial resistance (m²·K/W)', 'well_total_nm': 'Total well thickness (nm)',
    'capture_ps': 'Carrier capture time (ps)', 'escape_ps': 'Carrier escape time (ps)',
    'barrier_lifetime_ps': 'Barrier lifetime (ps)', 'escape_activation_eV': 'Escape activation energy (eV)',
    'A_s1': 'SRH rate A (s⁻¹)', 'g0_cm1': 'Gain coefficient g₀ (cm⁻¹)', 'Ntr_cm3': 'Transparency density (cm⁻³)',
    'gain_temperature_K': 'Gain temperature scale (K)', 'group_index': 'Group index', 'Gamma_QW': 'Well confinement Γ',
    'alpha_rad_cm1': 'Radiative loss (cm⁻¹)', 'alpha_edge_cm1': 'Edge loss (cm⁻¹)',
    'alpha_internal_cm1': 'Internal loss (cm⁻¹)', 'port_fraction': 'Output port fraction',
    'port_transmission': 'Output port transmission', 'wavelength_nm': 'Wavelength (nm)',
    'load_reference_V': 'Load reference voltage (V)',
}


class TreeForm(QWidget):
    """A form over existing typed items, with real tables for numeric arrays."""
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.form = QFormLayout(self)
        self.form.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setVerticalSpacing(13)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.controls = {}
        self.node = None
        self._syncing = False

    def set_node(self, node, skip=('id', 'shape'), keys=None):
        _clear(self.form)
        self.controls = {}
        self.node = node
        self._skip, self._keys = skip, keys
        if node is None:
            self.form.addRow(label('Select an object to edit its properties.'))
            return
        nodes = [node.child(i) for i in range(node.childCount())] if _kind(node) == 'object' else [node]
        for item in nodes:
            key = item.text(0)
            if key in skip or keys is not None and key not in keys:
                continue
            title = TITLES.get(key, key.replace('_', ' ').capitalize())
            if _kind(item) in ('number', 'text', 'boolean'):
                control = self._scalar(item, title)
            elif _kind(item) == 'array' and self._table_shape(item) is not None:
                control = self._array(item, title)
            else:
                control = button('Edit '+title.lower()+'…', lambda checked=False, entry=item: self._open_nested(entry))
            self.controls[key] = control
            if item is node and _kind(node) == 'array': self.form.addRow(control)
            else: self.form.addRow(title, control)
            control.show()
            caption = self.form.labelForField(control)
            if caption is not None: caption.show()

    def _open_nested(self, item):
        self.editor.tree.setCurrentItem(item, 1)
        item.setExpanded(True)
        reveal_and_focus(self.editor.tree)

    def diagnostic_control(self, parts):
        """Resolve a property and its array indices without changing its draft."""
        if not parts:
            return None
        control = self.controls.get(parts[0])
        if control is None:
            return None
        indices = parts[1:]
        components = getattr(control, 'components', None)
        if components is not None:
            if indices and (len(indices) != 1 or not indices[0].isdigit()):
                return None
            index = int(indices[0]) if indices else 0
            return components[index] if 0 <= index < len(components) else None
        table = getattr(control, 'table', None)
        if table is not None:
            if any(not index.isdigit() for index in indices) or len(indices) > 2:
                return None
            row = int(indices[0]) if indices else 0
            column = int(indices[1]) if len(indices) > 1 else 0
            if not (0 <= row < table.rowCount() and 0 <= column < table.columnCount()):
                return None
            table.setCurrentCell(row, column)
            if table.item(row, column) is not None:
                table.scrollToItem(table.item(row, column))
            return table
        return control if not indices else None

    def _scalar(self, item, title):
        if _kind(item) == 'boolean':
            control = QComboBox()
            control.addItem('No', 'false'); control.addItem('Yes', 'true')
            control.setCurrentIndex(max(0, control.findData(item.text(1))))
            control.currentIndexChanged.connect(lambda: item.setText(1, control.currentData()))
        elif item.text(0) == 'mode' and item.text(1) in ('local', 'wsl'):
            control = QComboBox(); control.addItem('This computer', 'local'); control.addItem('WSL', 'wsl')
            control.setCurrentIndex(control.findData(item.text(1)))
            control.currentIndexChanged.connect(lambda: item.setText(1, control.currentData()))
        else:
            control = QLineEdit(item.text(1))
            control.setPlaceholderText('Required value' if _kind(item) == 'number' else '')
            control.textChanged.connect(lambda text: item.setText(1, text))
        control.setAccessibleName(title)
        control.setMinimumWidth(0)
        return control

    def _table_shape(self, item):
        children = [item.child(i) for i in range(item.childCount())]
        if not children:
            return 2 if item.text(0) in ('vertices', 'vertices_um', 'pole_seeds', 'kpoints') else 1
        if all(_kind(child) in ('number', 'text') for child in children):
            return 1
        if all(_kind(child) == 'array' and child.childCount() == children[0].childCount()
               and all(_kind(child.child(i)) in ('number', 'text') for i in range(child.childCount())) for child in children):
            return children[0].childCount() or 1
        return None

    def _array(self, item, title):
        dimensions = {'period_um': ('Width', 'Depth'), 'aperture_um': ('Width', 'Height'),
            'center': ('X / a', 'Y / a'), 'center_um': ('X (µm)', 'Y (µm)'), 'probe': ('X / a', 'Y / a', 'Z (nm)')}
        names = dimensions.get(item.text(0))
        if names and item.childCount() in (0, len(names)):
            host = QWidget(); row = QHBoxLayout(host); row.setContentsMargins(0, 0, 0, 0); host.components = []
            for index, name in enumerate(names):
                column = QVBoxLayout(); caption = QLabel(name); edit = QLineEdit(item.child(index).text(1) if item.childCount() else '')
                edit.setMinimumWidth(0); edit.setAccessibleName(title+' '+name)
                edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                column.addWidget(caption); column.addWidget(edit); row.addLayout(column, 1); host.components.append(edit)
                def changed(text, component=index):
                    if item.childCount() == 0:
                        self.editor.tree.blockSignals(True)
                        for n in range(len(names)):
                            added = self.editor._append(item, n, 0.); added.setText(1, '')
                        self.editor.tree.blockSignals(False)
                    item.child(component).setText(1, text)
                edit.textChanged.connect(changed)
            return host
        host = QWidget(); layout = QVBoxLayout(host); layout.setContentsMargins(0, 0, 0, 0)
        columns = self._table_shape(item)
        table = QTableWidget(item.childCount(), columns)
        table.setAccessibleName(title)
        headings = ['Value'] if columns == 1 else ['X', 'Y'] if columns == 2 else [str(i+1) for i in range(columns)]
        if item.text(0) in ('pole_seeds', 'pole_excitation'):
            headings = ['Real', 'Imaginary']
        table.setHorizontalHeaderLabels(headings)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumWidth(0); table.setMaximumHeight(175)
        for row in range(item.childCount()):
            node = item.child(row)
            for col in range(columns):
                entry = node.child(col) if _kind(node) == 'array' else node
                table.setItem(row, col, QTableWidgetItem(entry.text(1)))
        def changed(row, col):
            node = item.child(row)
            target = node.child(col) if _kind(node) == 'array' else node
            target.setText(1, table.item(row, col).text())
        table.cellChanged.connect(changed)
        layout.addWidget(table)
        actions = QHBoxLayout()
        def add():
            node = self.editor._append(item, item.childCount(), [0.]*columns if columns > 1 else '' if item.text(0).endswith('paths') else 0.)
            if _kind(node) == 'array':
                for i in range(node.childCount()): node.child(i).setText(1, '')
            else: node.setText(1, '')
            self.editor.changed.emit()
            self.set_node(self.node, self._skip, self._keys)
        def remove():
            row = table.currentRow()
            if row >= 0:
                item.takeChild(row)
                self.editor.changed.emit()
                self.set_node(self.node, self._skip, self._keys)
        actions.addWidget(button('Add row', add)); actions.addWidget(button('Remove row', remove)); actions.addStretch()
        layout.addLayout(actions)
        host.table = table
        return host


class PcselSummaryPreview(QWidget):
    """Exact authored top-cell geometry and a thickness-scaled stack section."""
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace
        self.setMinimumSize(180, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName('Editable PCSEL cell and layer stack preview')
        self.selected_id = ''
        self.last_geometry = None
        self.message = ''

    def refresh(self):
        ws = self.workspace
        try:
            layers = ws.structured['layers'].value()
            shapes = ws.structured[ws.shape_key].value()
            period = [float(ws.fields['lattice_nm'].text())]*2 if ws.engine == 'pcsel' else ws.structured['period_um'].value()
            key = 'thickness_nm' if ws.engine == 'pcsel' else 'thickness_um'
            if len(period) != 2 or any(float(v) <= 0 or not math.isfinite(float(v)) for v in period):
                raise ValueError('Enter the cell dimensions to preview it.')
            if not layers or any(float(row.get(key, 0)) <= 0 for row in layers):
                raise ValueError('Add layers with positive thicknesses to preview the stack.')
            self.last_geometry = (layers, shapes, period)
            self.message = ''
        except (ValueError, TypeError, KeyError) as exc:
            self.message = 'Finish the highlighted dimensions to update the preview.' if self.last_geometry else 'Add a layer and enter the cell dimensions to see your structure.'
        self.update()

    def paintEvent(self, event):
        from qt_common import COLORS, theme_manager
        colors = COLORS[theme_manager().mode]
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(colors['field']))
        p.setPen(QColor(colors['muted']))
        if self.last_geometry is None:
            p.drawText(self.rect().adjusted(18, 18, -18, -18), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
            return
        layers, shapes, period = self.last_geometry
        w, h = self.width(), self.height()
        p.drawText(20, 28, 'TOP VIEW · UNIT CELL')
        side = min(w-64, h*.46)
        rect = QRectF((w-side)/2, 48, side, side*float(period[1])/float(period[0]))
        if rect.height() > h*.46:
            rect.setHeight(h*.46); rect.setWidth(rect.height()*float(period[0])/float(period[1])); rect.moveLeft((w-rect.width())/2)
        p.setBrush(QColor(colors['select'])); p.setPen(QPen(QColor(colors['border']), 1.3)); p.drawRect(rect)
        normalized = self.workspace.engine == 'pcsel'
        def point(x, y):
            return QPointF(rect.center().x()+float(x)*rect.width()/(1 if normalized else period[0]), rect.center().y()-float(y)*rect.height()/(1 if normalized else period[1]))
        p.save(); p.setClipRect(rect)
        for shape in shapes:
            color = QColor(colors['accent'] if shape.get('id') == self.selected_id else colors['panel'])
            p.setBrush(color); p.setPen(QPen(QColor(colors['accent']), 1.4))
            try:
                if shape.get('shape') == 'circle':
                    center = shape.get('center' if normalized else 'center_um', [0, 0])
                    radius = float(shape['radius' if normalized else 'radius_um'])
                    r = radius*rect.width()/(1 if normalized else period[0])
                    if math.isfinite(r) and r > 0: p.drawEllipse(point(*center), r, r)
                elif shape.get('shape') == 'polygon':
                    vertices = shape.get('vertices' if normalized else 'vertices_um', [])
                    p.drawPolygon(QPolygonF([point(*xy) for xy in vertices]))
            except (TypeError, ValueError, KeyError):
                continue
        p.restore()
        p.setPen(QColor(colors['muted']))
        unit = 'nm' if normalized else 'µm'
        p.drawText(QRectF(12, rect.bottom()+9, w-24, 23), Qt.AlignmentFlag.AlignCenter, f'{period[0]:g} × {period[1]:g} {unit} · +y upward')
        sy = max(h*.58, rect.bottom()+48)
        p.drawText(20, round(sy), 'LAYER STACK · TOP TO BOTTOM')
        key = 'thickness_nm' if normalized else 'thickness_um'
        total = sum(float(row[key]) for row in layers)
        height = max(10, h-sy-66)
        stack = QRectF(w*.25, sy+17, w*.5, height)
        y = stack.top()
        for i, row in enumerate(layers):
            dy = height*float(row[key])/total
            selected = row.get('id') == self.selected_id
            color = QColor(colors['accent'] if selected else '#829fd2' if row.get('patterned') else '#8eabbd' if row.get('qw') else colors['select'])
            p.setBrush(color); p.setPen(QPen(QColor(colors['border']), .7)); p.drawRect(QRectF(stack.left(), y, stack.width(), dy))
            y += dy
        p.setPen(QColor(colors['muted']))
        p.drawText(QRectF(8, h-34, w-16, 24), Qt.AlignmentFlag.AlignCenter, f'{len(layers)} layers · {total:g} {unit} total')
        if self.message:
            p.drawText(QRectF(10, h-60, w-20, 20), Qt.AlignmentFlag.AlignCenter, 'Showing the last complete geometry')


def pcsel_preview_device(layers, shapes, period, engine='pcsel', repeat=1, layer_id=''):
    """Convert authored independent-cell geometry into a read-only µm preview.

    No device defaults, electrical properties or solver geometry are imported.
    Repeated display instances map back to their original stable object IDs.
    """
    optical = engine == 'pcsel'
    scale = .001 if optical else 1.
    width, depth = [float(value)*scale for value in period]
    if repeat not in (1, 3) or not all(math.isfinite(v) and v > 0 for v in (width, depth)):
        raise ValueError('Enter positive finite cell dimensions.')
    snapshot = dict(schema_version=1, name='Authored PCSEL cell', width_um=width*repeat,
        depth_um=depth*repeat, layers=[], shapes=[], contacts=[], doping_regions=[])
    sources = {}
    for i, layer in enumerate(layers):
        identity = str(layer.get('id') or 'layer-'+str(i))
        if layer_id and identity != layer_id: continue
        thickness = float(layer['thickness_nm' if optical else 'thickness_um'])*scale
        if not math.isfinite(thickness) or thickness <= 0: raise ValueError('Complete the layer thicknesses.')
        name = str(layer.get('name') or 'Layer '+str(i+1))
        material = 'n='+str(layer.get('index', '?')) if optical else str(layer.get('material', 'Unassigned'))
        snapshot['layers'].append(dict(id=identity, name=name, material_id=material, thickness_um=thickness,
            enabled=True, donor_cm3=0., acceptor_cm3=0.))
        sources[identity] = ('layers', identity)
        if not layer.get('patterned', False): continue
        for shape in shapes:
            for ix in range(-(repeat//2), repeat//2+1):
                for iy in range(-(repeat//2), repeat//2+1):
                    source_id = str(shape['id'])
                    display_id = source_id+'@'+identity+':'+str(ix)+':'+str(iy)
                    obj = dict(id=display_id, name=source_id, layer_id=identity, enabled=True,
                        shape=shape['shape'], material_id='PCSEL inclusion', operation='void', angle_deg=0.,
                        cx_um=ix*width, cy_um=iy*depth, size_x_um=width, size_y_um=depth, vertices=[])
                    if shape['shape'] == 'circle':
                        center = shape.get('center' if optical else 'center_um', [0., 0.])
                        xy_scale = width if optical else 1.
                        radius = float(shape['radius' if optical else 'radius_um'])*xy_scale
                        x, y = [float(v)*xy_scale for v in center]
                        if not all(math.isfinite(v) for v in (x, y, radius)) or radius <= 0:
                            raise ValueError('Complete the circle center and radius.')
                        obj.update(cx_um=x+ix*width, cy_um=y+iy*depth, size_x_um=2*radius, size_y_um=2*radius)
                    elif shape['shape'] == 'polygon':
                        vertices = shape.get('vertices' if optical else 'vertices_um', [])
                        xy_scale = width if optical else 1.
                        if len(vertices) < 3: raise ValueError('Add at least three polygon vertices.')
                        obj['vertices'] = [[float(x)*xy_scale, float(y)*xy_scale] for x, y in vertices]
                        if not all(math.isfinite(v) for pair in obj['vertices'] for v in pair):
                            raise ValueError('Complete the polygon vertices.')
                    else: raise ValueError('The preview supports circles and polygons.')
                    snapshot['shapes'].append(obj)
                    sources[display_id] = ('shapes' if optical else 'inclusions', source_id)
    if not snapshot['layers']: raise ValueError('Add a layer to see the structure.')
    return snapshot, sources


class PcselGeometryPreview(QWidget):
    """Linked 3D, top and cross-section views of the independent authored cell."""
    def __init__(self, workspace):
        super().__init__()
        from qt_custom_device import DeviceCanvas
        from qt_reference_style import reference_icon
        from qt_common import COLORS, theme_manager
        self.workspace = workspace
        self.last_geometry = None
        self._selected_id = ''
        self._sources = {}
        self.message = ''
        self.setMinimumWidth(170)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
        toolbar = QHBoxLayout()
        self.view_choice = QComboBox()
        for caption, value in (('3D structure', '3d'), ('Top view', 'top'), ('Section', 'section')):
            self.view_choice.addItem(reference_icon('cube' if value == '3d' else 'layers' if value == 'section' else 'mesh', COLORS[theme_manager().mode]['accent']), caption, value)
        self.view_choice.setAccessibleName('PCSEL structure view')
        self.view_choice.setMinimumWidth(0)
        self.view_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.view_choice.setMinimumContentsLength(8)
        self.scope_choice = QComboBox(); self.scope_choice.addItem('Whole stack', 'all'); self.scope_choice.addItem('Selected layer', 'selected')
        self.scope_choice.setAccessibleName('Preview layer scope'); self.scope_choice.setMinimumWidth(0)
        self.scope_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.scope_choice.setMinimumContentsLength(8)
        self.reset_button = button('', self.reset_view)
        self.reset_button.setIcon(reference_icon('reset', COLORS[theme_manager().mode]['muted']))
        self.reset_button.setAccessibleName('Reset structure view'); self.reset_button.setToolTip('Reset camera'); self.reset_button.setFixedWidth(34)
        toolbar.addWidget(self.view_choice, 1); toolbar.addWidget(self.scope_choice, 1); toolbar.addWidget(self.reset_button)
        layout.addLayout(toolbar)
        tools = QHBoxLayout()
        self.repeat_choice = QComboBox(); self.repeat_choice.addItem('1 cell', 1); self.repeat_choice.addItem('3 × 3 cells', 3)
        self.repeat_choice.setAccessibleName('Preview cell repetitions')
        self.cut_label = QLabel('Cut y (µm)'); self.cut_y = QLineEdit('0'); self.cut_y.setMaximumWidth(90)
        self.cut_y.setAccessibleName('Cross-section y coordinate in micrometres')
        tools.addWidget(self.repeat_choice); tools.addStretch(); tools.addWidget(self.cut_label); tools.addWidget(self.cut_y)
        layout.addLayout(tools)
        self.canvas = DeviceCanvas('3d'); self.canvas.setMinimumSize(160, 240)
        self.canvas.depth_display_mode = 'physical'; self.canvas.compact_preview = True
        self.canvas.show_doping = False
        self.canvas.set_render_quality('studio', reflections=False, ambient_occlusion=True)
        self.canvas.setAccessibleName('Authored PCSEL geometry: orbit, zoom and select objects')
        self.canvas.object_selected.connect(self._picked)
        layout.addWidget(self.canvas, 1)
        self.note = label('Add a layer and enter cell dimensions to see your structure.'); layout.addWidget(self.note)
        self.view_choice.currentIndexChanged.connect(self._view_changed)
        self.scope_choice.currentIndexChanged.connect(self._render)
        self.repeat_choice.currentIndexChanged.connect(self._render)
        self.cut_y.editingFinished.connect(self._cut_changed)
        theme_manager().changed.connect(self._icons)
        theme_manager().appearance_changed.connect(self._icons)
        self._view_changed()

    def _icons(self, *args):
        from qt_reference_style import reference_icon
        from qt_common import COLORS, theme_manager
        colors = COLORS[theme_manager().mode]
        for i, name in enumerate(('cube', 'mesh', 'layers')): self.view_choice.setItemIcon(i, reference_icon(name, colors['accent']))
        self.reset_button.setIcon(reference_icon('reset', colors['muted']))

    @property
    def selected_id(self): return self._selected_id

    @selected_id.setter
    def selected_id(self, value):
        self._selected_id = value
        self._render()

    def reset_view(self):
        self.canvas.zoom = 1.; self.canvas.pan = QPointF(0, 0); self.canvas.yaw = -.6; self.canvas.elevation = .48
        self.canvas.update()

    def _view_changed(self):
        self.canvas.mode = self.view_choice.currentData()
        self.cut_label.setVisible(self.canvas.mode == 'section'); self.cut_y.setVisible(self.canvas.mode == 'section')
        self._render()

    def _cut_changed(self):
        try:
            value = float(self.cut_y.text())
            if not math.isfinite(value): raise ValueError()
            self.canvas.cut_y = value; self.canvas.update()
        except ValueError: self.note.setText('Enter a finite cross-section position in µm. The previous cut is retained.')

    def _picked(self, display_id):
        source = self._sources.get(display_id)
        if source and hasattr(self.workspace, 'geometry_editor'):
            self.workspace.geometry_editor.select_object(*source)

    def refresh(self):
        ws = self.workspace
        try:
            layers = ws.structured['layers'].value(); shapes = ws.structured[ws.shape_key].value()
            period = [float(ws.fields['lattice_nm'].text())]*2 if ws.engine == 'pcsel' else ws.structured['period_um'].value()
            pcsel_preview_device(layers, shapes, period, ws.engine)
            self.last_geometry = (deepcopy(layers), deepcopy(shapes), list(period)); self.message = ''
        except (ValueError, TypeError, KeyError, OverflowError):
            self.message = 'Incomplete geometry · showing the last valid preview.' if self.last_geometry else 'Add layers and complete their geometry to see the structure.'
        self._render()

    def _render(self, *args):
        if not self.last_geometry:
            if hasattr(self, 'note'): self.note.setText(self.message or 'Add layers and cell dimensions to see the structure.')
            return
        layers, shapes, period = self.last_geometry
        selected_layer = next((row['id'] for row in layers if row['id'] == self._selected_id), '')
        if not selected_layer: selected_layer = next((row['id'] for row in layers if row.get('patterned')), layers[0]['id'])
        try:
            snapshot, sources = pcsel_preview_device(layers, shapes, period, self.workspace.engine,
                self.repeat_choice.currentData(), selected_layer if self.scope_choice.currentData() == 'selected' else '')
            # Optical inclusions are air voids only when explicitly assigned n=1.
            if self.workspace.engine == 'pcsel':
                try: inclusion_n = float(self.workspace.fields['inclusion_index'].text())
                except ValueError: inclusion_n = None
                if inclusion_n != 1.:
                    for row in snapshot['shapes']:
                        row.update(operation='material', material_id='n='+str(inclusion_n) if inclusion_n is not None else 'Unassigned inclusion')
            chosen = next((key for key, source in sources.items() if source[1] == self._selected_id and ':0:0' in key), self._selected_id)
            self._sources = sources
            self.canvas.set_device(snapshot, chosen, selected_layer)
            n = self.repeat_choice.currentData()
            mode = self.view_choice.currentData()
            instruction = 'Drag to rotate · wheel to zoom' if mode == '3d' else 'Select a layer or pattern · wheel to zoom'
            scale_note = 'depth scaled to fit' if mode == 'section' else 'physical proportions'
            self.note.setText(self.message or instruction+'\n'+('One authored cell' if n == 1 else '3 × 3 display copies')+' · '+scale_note+' · geometry only')
        except (ValueError, KeyError, TypeError, OverflowError):
            self.note.setText('Finish the geometry to update this view. The last valid preview is retained.')


class PcselGeometryEditor(QWidget):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace
        self.current_group = 'layers'
        self.current_id = ''
        self._populating = False
        self.layout_row = QHBoxLayout(self); self.layout_row.setContentsMargins(0, 0, 0, 0); self.layout_row.setSpacing(18)
        self.sidebar = QWidget(); left = QVBoxLayout(self.sidebar); left.setContentsMargins(0, 0, 0, 0)
        self.group = QComboBox(); self.group.addItem('Layer stack', 'layers'); self.group.addItem('Cell pattern', workspace.shape_key)
        self.group.currentIndexChanged.connect(self._change_group)
        left.addWidget(self.group)
        self.objects = QListWidget(); self.objects.setAccessibleName('PCSEL layers and inclusions')
        self.objects.currentRowChanged.connect(self._select_row); left.addWidget(self.objects, 1)
        self.add_kind = QComboBox(); self.add_kind.addItems(['Layer', 'Circle', 'Polygon']); left.addWidget(self.add_kind)
        self.add_button = button('Add object', self.add_object); left.addWidget(self.add_button)
        actions = QHBoxLayout()
        self.up_button = button('Up', lambda: self.move(-1)); self.down_button = button('Down', lambda: self.move(1))
        for control, caption in ((self.up_button, 'Move object up'), (self.down_button, 'Move object down')):
            control.setText(''); control.setToolTip(caption); control.setAccessibleName(caption)
        actions.addWidget(self.up_button); actions.addWidget(self.down_button)
        left.addLayout(actions)
        self.remove_button = button('Remove', self.remove); left.addWidget(self.remove_button)
        self.preview = PcselGeometryPreview(workspace)
        self.inspector = QWidget(); right = QVBoxLayout(self.inspector); right.setContentsMargins(0, 0, 0, 0)
        self.title = label('Object properties', 'setupTitle'); right.addWidget(self.title)
        self.identity = label(''); self.identity.setToolTip('Stable identifier used by saved projects, sweeps and diagnostics.'); right.addWidget(self.identity)
        self.form = TreeForm(workspace.structured['layers']); right.addWidget(self.form); right.addStretch()
        right.addWidget(button('All object properties…', self.open_advanced))
        self.layout_row.addWidget(self.sidebar, 0); self.layout_row.addWidget(self.preview, 1); self.layout_row.addWidget(self.inspector, 0)
        self.sidebar.setFixedWidth(175); self.inspector.setFixedWidth(275)
        for key in ('layers', workspace.shape_key):
            workspace.structured[key].changed.connect(self._changed)
        from qt_common import theme_manager
        theme_manager().appearance_changed.connect(self._icons)
        theme_manager().changed.connect(self._icons)
        self._icons()
        self.refresh()

    def _icons(self, *args):
        from qt_reference_style import reference_icon
        from qt_common import COLORS, theme_manager
        color = COLORS[theme_manager().mode]['accent']
        self.add_button.setIcon(reference_icon('plus', color))
        self.remove_button.setIcon(reference_icon('delete', color))
        self.up_button.setIcon(reference_icon('up', color))
        self.down_button.setIcon(reference_icon('down', color))
        for widget in (self.add_button, self.remove_button, self.up_button, self.down_button): widget.setIconSize(QSize(17, 17))
        self.group.setItemIcon(0, reference_icon('layers', color)); self.group.setItemIcon(1, reference_icon('mesh', color))
        for i in range(self.add_kind.count()): self.add_kind.setItemIcon(i, reference_icon('layers' if i == 0 else 'mesh', color))
        for i in range(self.objects.count()): self.objects.item(i).setIcon(reference_icon('layers' if self.current_group == 'layers' else 'mesh', color))

    def root(self):
        return self.workspace.structured[self.current_group].tree.topLevelItem(0)

    def _change_group(self):
        self.current_group = self.group.currentData()
        self.current_id = ''
        self.refresh()

    def refresh(self):
        self._populating = True
        root = self.root()
        self.objects.clear()
        selected = -1
        for i in range(root.childCount()):
            item = root.child(i); identity = _text(item, 'id')
            title = _text(item, 'name') or ('Circle' if _text(item, 'shape') == 'circle' else 'Polygon' if self.current_group != 'layers' else 'Layer '+str(i+1))
            if self.current_group == 'layers':
                value = _text(item, 'thickness_nm' if self.workspace.engine == 'pcsel' else 'thickness_um')
                title += '\n'+(value or 'Set thickness')+(' nm' if self.workspace.engine == 'pcsel' else ' µm')
            entry = QListWidgetItem(title); entry.setData(Qt.ItemDataRole.UserRole, identity); self.objects.addItem(entry)
            from qt_reference_style import reference_icon
            from qt_common import COLORS, theme_manager
            entry.setIcon(reference_icon('layers' if self.current_group == 'layers' else 'mesh', COLORS[theme_manager().mode]['accent']))
            if identity == self.current_id: selected = i
        self._populating = False
        self.objects.setCurrentRow(selected if selected >= 0 else 0 if root.childCount() else -1)
        self._select_row(self.objects.currentRow())
        self.preview.refresh()

    def _changed(self):
        # Keep the active line editor and its cursor while its canonical item changes.
        root = self.root()
        if root.childCount() != self.objects.count():
            self.refresh(); return
        self.preview.refresh()
        for i in range(root.childCount()):
            node = root.child(i)
            if self.current_group == 'layers':
                title = _text(node, 'name') or 'Layer '+str(i+1)
                value = _text(node, 'thickness_nm' if self.workspace.engine == 'pcsel' else 'thickness_um')
                self.objects.item(i).setText(title+'\n'+(value or 'Set thickness')+(' nm' if self.workspace.engine == 'pcsel' else ' µm'))

    def _select_row(self, row):
        if self._populating: return
        item = self.root().child(row) if 0 <= row < self.root().childCount() else None
        self.current_id = _text(item, 'id') if item is not None else ''
        self.form.editor = self.workspace.structured[self.current_group]
        self.form.set_node(item)
        self.title.setText(_text(item, 'name') or ('Layer' if self.current_group == 'layers' else 'Inclusion') if item is not None else 'Object properties')
        self.identity.setText(self.current_id)
        self.preview.selected_id = self.current_id; self.preview.update()

    def select_object(self, group, identity='', index=None):
        self.group.setCurrentIndex(self.group.findData(group))
        root = self.root()
        row = next((i for i in range(root.childCount()) if identity and _text(root.child(i), 'id') == identity), -1)
        if not identity and index is not None and 0 <= index < root.childCount(): row = index
        if row < 0: return False
        self.objects.setCurrentRow(row); self._select_row(row)
        return True

    def add_object(self):
        kind = self.add_kind.currentText()
        optical = self.workspace.engine == 'pcsel'
        group = 'layers' if kind == 'Layer' else self.workspace.shape_key
        self.group.setCurrentIndex(self.group.findData(group))
        identity = ('layer-' if kind == 'Layer' else 'inclusion-')+uuid.uuid4().hex[:8]
        if kind == 'Layer':
            value = dict(id=identity, name='New layer', thickness_nm=0., index=0., qw=False, patterned=False) if optical else dict(id=identity, name='New layer', thickness_um=0., material='', donors_cm3=0., acceptors_cm3=0., patterned=False)
            missing = ('thickness_nm', 'index') if optical else ('thickness_um', 'donors_cm3', 'acceptors_cm3')
        elif kind == 'Circle':
            value = dict(id=identity, shape='circle', **({'center': [0., 0.], 'radius': 0.} if optical else {'center_um': [0., 0.], 'radius_um': 0.}))
            missing = ('radius' if optical else 'radius_um',)
        else:
            value = dict(id=identity, shape='polygon', **{'vertices' if optical else 'vertices_um': []}); missing = ()
        self.workspace.structured[group].append_template(value, missing)
        self.current_id = identity; self.refresh()

    def remove(self):
        row = self.objects.currentRow()
        if row >= 0:
            self.root().takeChild(row)
            self.workspace.structured[self.current_group].changed.emit(); self.refresh()

    def move(self, offset):
        row = self.objects.currentRow(); root = self.root(); target = row+offset
        if row >= 0 and 0 <= target < root.childCount():
            root.insertChild(target, root.takeChild(row))
            self.workspace.structured[self.current_group].changed.emit(); self.refresh()

    def open_advanced(self):
        self.workspace.structured[self.current_group].open_field(self.current_group, self.current_id)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 850
        self.sidebar.setFixedWidth(145 if compact else 175)
        self.inspector.setFixedWidth(225 if compact else 275)


class PcselResearchWorkspace(StructuredStudyWorkspace):
    """Curated setup retaining canonical study schema, runtime and result routes."""
    def __init__(self, store, capability, parent=None, *, document_id=None):
        self._friendly_ready = False
        self.shape_key = 'shapes' if capability['engine'] == 'pcsel' else 'inclusions'
        super().__init__(store, capability, parent, document_id=document_id)
        restored = store.search_state.get('research_workspaces', {}).get(self.state_key)
        restored_section = restored.get('section') if isinstance(restored, dict) else None
        self.heading.setText('PCSEL optics' if self.engine == 'pcsel' else 'PCSEL periodic transport')
        self.description.setText('Build your layer stack and cell pattern, choose the physics, then calculate.' if self.engine == 'pcsel' else 'Edit the periodic cell, assign explicit materials and sweep its full-face terminals.')
        self.description.setToolTip('\n'.join(capability.get('limitations', [])))
        self._make_geometry()
        self._make_friendly_parameters()
        self._friendly_ready = True
        self._refresh_friendly()
        from qt_study_flow import install_study_flow
        stages = [('Structure', ['design', 'Editable starting structures']),
                  ('Physics', ['materials' if self.engine == 'pcsel' else 'Materials', 'physics' if self.engine == 'pcsel' else 'Bias', 'Model']),
                  ('Calculate', ['accuracy' if self.engine == 'pcsel' else 'Accuracy', 'solver', 'outputs', 'runtime' if self.engine == 'pcsel' else 'Runtime', 'sweep', 'Review & files'])]
        self.study_flow = install_study_flow(self, stages=stages, subtitle=self.description.text(), details='\n'.join(capability.get('limitations', [])))
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self._model_changed()
        # Original tab indices remain stable for old drafts, but moved controls
        # must never leave an empty destination in imports, restores or More.
        self.tabs.currentChanged.connect(self._route_visible_section)
        if isinstance(restored_section, int) and 0 <= restored_section < self.tabs.count():
            self.tabs.setCurrentIndex(restored_section)
        else:
            self.select_section('design')
        self._route_visible_section()

    def _move_scalar(self, key, form, title=None):
        widget = self.fields[key]
        old = widget.parentWidget().layout()
        if isinstance(old, QFormLayout):
            taken = old.takeRow(widget)
            if taken.labelItem and taken.labelItem.widget():
                taken.labelItem.widget().hide(); taken.labelItem.widget().deleteLater()
        else:
            # A section's QFormLayout is nested under its vertical layout.
            parent = widget.parentWidget()
            forms = parent.findChildren(QFormLayout)
            for layout in forms:
                if layout.indexOf(widget) >= 0:
                    taken = layout.takeRow(widget)
                    if taken.labelItem and taken.labelItem.widget():
                        taken.labelItem.widget().hide(); taken.labelItem.widget().deleteLater()
                    break
        form.addRow(title or key, widget)

    def _make_geometry(self):
        _, layout = self.add_section('Build device', 'design')
        self.design_view_choice = QComboBox()
        self.design_view_choice.addItems(['Cell & calculation', 'Structure editor'])
        self.design_view_choice.setCurrentIndex(1 if self.engine == 'pcsel' else 0)
        self.design_view_choice.setAccessibleName('Compact PCSEL setup view')
        self.design_view_choice.currentIndexChanged.connect(self.adapt_layout)
        self.design_view_choice.hide()
        layout.addWidget(self.design_view_choice)
        self.design_settings = QWidget()
        settings_layout = QVBoxLayout(self.design_settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout(); form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.design_form = form
        if self.engine == 'pcsel':
            model = self.fields['model']
            for i in range(model.count()): model.setItemText(i, MODEL_LABELS[model.itemData(i)][0])
            self._move_scalar('model', form, 'What would you like to calculate?')
            self._move_scalar('lattice_nm', form, 'Square lattice period a (nm)')
            self.model_note = label(''); settings_layout.addWidget(self.model_note)
            model.currentIndexChanged.connect(self._model_changed)
        else:
            self.period_form = TreeForm(self.structured['period_um'])
            self.period_form.set_node(self.structured['period_um'].tree.topLevelItem(0), skip=())
            form.addRow('Cell width and depth (µm)', self.period_form)
        settings_layout.addLayout(form)
        layout.addWidget(self.design_settings)
        self.geometry_editor = PcselGeometryEditor(self); layout.addWidget(self.geometry_editor, 1)
        layout.addWidget(label('3D, top view and cross-section show the authored geometry. Isolate a selected layer to inspect a buried pattern.'))
        if self.engine == 'pcsel':
            self.fields['lattice_nm'].textChanged.connect(self.geometry_editor.preview.refresh)
            self.fields['inclusion_index'].textChanged.connect(self.geometry_editor.preview.refresh)
        else:
            self.structured['period_um'].changed.connect(self.geometry_editor.preview.refresh)

    def _make_friendly_parameters(self):
        self.friendly_forms = {}
        self.friendly_hosts = {}
        for key, editor in self.structured.items():
            if key in ('layers', self.shape_key, 'period_um', 'parameter_sweep'):
                continue
            form = TreeForm(editor)
            form.set_node(editor.tree.topLevelItem(0), skip=())
            parent = editor.parentWidget(); old = parent.layout()
            forms = parent.findChildren(QFormLayout)
            host_form = next((candidate for candidate in forms if candidate.indexOf(editor) >= 0), None)
            if isinstance(old, QFormLayout) and old.indexOf(editor) >= 0: host_form = old
            if host_form is None: continue
            row, role = host_form.getWidgetPosition(editor)
            taken = host_form.takeRow(editor)
            title = taken.labelItem.widget().text() if taken.labelItem and taken.labelItem.widget() else key
            if taken.labelItem and taken.labelItem.widget():
                taken.labelItem.widget().hide(); taken.labelItem.widget().deleteLater()
            holder = QWidget(); holder_layout = QVBoxLayout(holder); holder_layout.setContentsMargins(0, 0, 0, 0)
            if key == 'materials':
                self.material_picker = QComboBox()
                self.material_picker.setAccessibleName('Semiconductor material')
                self.material_picker.currentIndexChanged.connect(self._material_selected)
                holder_layout.addWidget(self.material_picker)
            holder_layout.addWidget(form)
            host_form.insertRow(row, title, holder)
            _, advanced = self.add_section('All '+key.replace('_', ' ')+' properties', 'advanced_'+key)
            advanced.addWidget(editor)
            self.friendly_forms[key] = form
            self.friendly_hosts[key] = holder
        if 'aperture_um' in self.friendly_hosts:
            holder = self.friendly_hosts['aperture_um']
            for layout in holder.parentWidget().findChildren(QFormLayout):
                if layout.indexOf(holder) >= 0:
                    taken = layout.takeRow(holder)
                    if taken.labelItem and taken.labelItem.widget():
                        taken.labelItem.widget().hide(); taken.labelItem.widget().deleteLater()
                    break
            self.design_form.addRow('Finite aperture width and height (µm)', holder)
        # Only create runtime/mesh/material records on an explicit user action.
        for key in ('runtime', 'mesh', 'materials', 'aperture'):
            if key not in self.friendly_forms: continue
            form = self.friendly_forms[key]
            self.friendly_hosts[key].layout().addWidget(button({'runtime': 'Set up Python runtime', 'mesh': 'Add mesh controls', 'materials': 'Add semiconductor material', 'aperture': 'Create required aperture inputs'}[key], lambda checked=False, name=key: self._create_fields(name)))
        from qt_research_runtime import ResearchRuntimeCheck
        self.runtime_check = ResearchRuntimeCheck(self._runtime_request, self)
        self.runtime_check.runtimeReady.connect(self._apply_automatic_runtime)
        self.friendly_hosts['runtime'].layout().addWidget(self.runtime_check)
        actions = QHBoxLayout()
        actions.addWidget(button('Remember this installation', self._remember_runtime))
        actions.addWidget(button('Use saved installation', self._use_saved_runtime))
        self.friendly_hosts['runtime'].layout().addLayout(actions)
        self.structured['runtime'].changed.connect(self.runtime_check.invalidate)

    def _runtime_request(self):
        return dict(engine=self.engine, settings=dict(model=self.fields['model'].currentData() if self.engine == 'pcsel' else '', runtime=self.structured['runtime'].value()))

    def _apply_automatic_runtime(self, runtime):
        self.structured['runtime'].set_value(runtime)
        self._refresh_friendly()
        self._edited()
        self._remember_runtime()
        self.runtime_check.check()

    def _remember_runtime(self):
        from qt_research_runtime import remember_runtime
        try:
            remember_runtime(self.engine, self.structured['runtime'].value(), model=self.fields['model'].currentData() if self.engine == 'pcsel' else None)
            self.status.setText('Installation saved. Use Check solver to verify it.')
        except ValueError as exc: self.status.setText(str(exc))

    def _use_saved_runtime(self):
        from qt_research_runtime import load_saved_runtime
        saved = load_saved_runtime(self.engine, model=self.fields['model'].currentData() if self.engine == 'pcsel' else None)
        if saved:
            self.structured['runtime'].set_value(saved); self._refresh_friendly(); self.runtime_check.invalidate(); self._edited()
        else: self.status.setText('No installation has been saved for this solver yet.')

    def _create_fields(self, key):
        editor = self.structured[key]
        if key == 'aperture':
            self.create_aperture_fields(); self._refresh_friendly(); return
        try: current = editor.value()
        except ValueError:
            self.status.setText('Finish the existing values before adding another set of inputs.'); return
        if key == 'runtime':
            proposed = dict(mode='local', executable='', distro='Ubuntu', timeout_s=86400., module_paths=[], library_paths=[])
            proposed.update(current); editor.set_value(proposed)
        elif key == 'mesh':
            proposed = dict(edge_segments=None, circle_segments=None, xy_size_um=None, z_max_step_um=None, maximum_tetrahedra=None)
            proposed.update(current); editor.set_template(proposed)
        else:
            identity = 'material-'+uuid.uuid4().hex[:8]
            current[identity] = dict(epsilon_r=None, Nc_cm3=None, Nv_cm3=None, bandgap_eV=None, affinity_eV=None,
                electron_mobility_cm2_Vs=None, hole_mobility_cm2_Vs=None, source='')
            editor.set_template(current)
        self._refresh_friendly(); self._edited()

    def _material_selected(self):
        if not hasattr(self, 'material_picker'): return
        root = self.structured['materials'].tree.topLevelItem(0)
        node = _child(root, self.material_picker.currentData())
        self.friendly_forms['materials'].set_node(node, skip=())

    def _refresh_friendly(self):
        if not self._friendly_ready: return
        self.geometry_editor.refresh()
        if hasattr(self, 'period_form'): self.period_form.set_node(self.structured['period_um'].tree.topLevelItem(0), skip=())
        for key, form in self.friendly_forms.items(): form.set_node(self.structured[key].tree.topLevelItem(0), skip=())
        if hasattr(self, 'material_picker'):
            self.material_picker.blockSignals(True); self.material_picker.clear()
            root = self.structured['materials'].tree.topLevelItem(0)
            for i in range(root.childCount()): self.material_picker.addItem(root.child(i).text(0), root.child(i).text(0))
            self.material_picker.blockSignals(False); self._material_selected()
        self._model_changed()

    def _model_changed(self):
        if self.engine != 'pcsel' or not hasattr(self, 'model_note'): return
        control=self.fields['model']
        previous=getattr(self.store,'active_study','pcsel.vertical').split('.')[-1]
        if self.switch_study_variant('pcsel.'+str(control.currentData()),control,previous):return
        model = self.fields['model'].currentData()
        self.heading.setText(MODEL_TITLES.get(model, 'PCSEL optics'))
        self.model_note.setText(MODEL_LABELS.get(model, ('', 'Choose a physical model.'))[1])
        if hasattr(self, 'runtime_check'): self.runtime_check.invalidate()
        # Conditional presentation changes no values or model semantics.
        groups = {'gme': {'gmax', 'guided_modes', 'num_modes', 'kpoints', 'runtime'},
            'rcwa_poles': {'basis', 'pole_seeds', 'pole_bounds', 'pole_excitation', 'probe', 'pole_field_grid', 'pole_field_z_nm', 'pole_detuning'},
            'beam': {'beam_grid', 'beam_padding', 'beam_mode', 'beam_normalization', 'beam_power_W', 'beam_power_source', 'beam_saved_run'},
            'aperture': {'aperture'}}
        for family, keys in groups.items():
            for key in keys:
                widget = self.friendly_hosts.get(key, self.fields.get(key))
                if widget is None: continue
                parent = widget.parentWidget()
                if parent:
                    for form in parent.findChildren(QFormLayout):
                        if form.indexOf(widget) >= 0:
                            form.setRowVisible(widget, model == family)
                            break
        common_visibility = {
            'grid_nm': model in ('vertical', 'cwt', 'finite', 'beam'),
            'pad_nm': model in ('vertical', 'cwt', 'finite', 'beam'),
            'harmonics': model in ('cwt', 'finite', 'beam'),
            'green_model': model in ('cwt', 'finite', 'beam'),
            'collocation_order': model in ('finite', 'beam'),
            'aperture_um': model in ('finite', 'beam', 'aperture'),
        }
        for key, visible in common_visibility.items():
            widget = self.friendly_hosts.get(key, self.fields.get(key))
            if widget is None: continue
            for form in widget.parentWidget().findChildren(QFormLayout):
                if form.indexOf(widget) >= 0:
                    form.setRowVisible(widget, visible); break
        if hasattr(self, 'study_flow'):
            second, keys = {
                'vertical': ('Waveguide', ['materials']), 'cwt': ('Coupling', ['materials', 'solver']),
                'gme': ('Modes', ['materials', 'solver']), 'rcwa_poles': ('Resonances', ['materials', 'solver', 'outputs']),
                'finite': ('Cavity', ['materials', 'solver']), 'beam': ('Source mode', ['outputs', 'materials', 'solver']),
                'aperture': ('Operating point', ['physics', 'materials']),
            }.get(model, ('Physics', ['materials']))
            final = ['Review & files'] if model == 'aperture' else ['accuracy']
            final += ['runtime'] if model == 'gme' else []
            final += ['sweep', 'Review & files'] if model != 'aperture' else ['sweep']
            self.study_flow.stages[1] = (second, [self.sections[key] for key in keys if key in self.sections])
            self.study_flow.stages[2] = ('Calculate', [self.sections[key] for key in final if key in self.sections])
            self.study_flow.buttons[1].setText('2  '+second)
            self.study_flow.buttons[1].setAccessibleName('Step 2: '+second)
            for index in (1, 2):
                if self.study_flow._last_sections.get(index) not in self.study_flow.stages[index][1]:
                    self.study_flow._last_sections[index] = self.study_flow.stages[index][1][0]
            self.study_flow.refresh()

    def select_model(self, model):
        """Navigate from the start chooser without loading or replacing a deck."""
        if self.engine != 'pcsel': return False
        index = self.fields['model'].findData(model)
        if index < 0: return False
        self.fields['model'].setCurrentIndex(index)
        self.select_section('design')
        return True

    def options(self):
        result = super().options()
        if self.engine == 'pcsel':
            # Guided modes are indices even while another optical model is
            # selected. Preserve their canonical integer representation so an
            # unchanged paper does not acquire an edited-input fingerprint.
            # Noninteger drafts remain unchanged for validation to reject.
            values = result['settings'].get('guided_modes', [])
            result['settings']['guided_modes'] = [int(value) if isinstance(value, (int, float))
                and float(value).is_integer() else value for value in values]
        return result

    def load_settings(self, settings):
        super().load_settings(settings)
        self._refresh_friendly()
        if self._friendly_ready:
            # Import is a new editable setup. The base import resets to legacy
            # section zero, which is a raw Geometry page for conformal cells.
            # Explicit restore_draft navigation still retains that advanced page.
            self.select_section('design')
            self.save_draft()
        self._route_visible_section()
        if hasattr(self, 'runtime_check'): self.runtime_check.invalidate()

    def restore_draft(self, state):
        super().restore_draft(state)
        self._refresh_friendly()
        self._route_visible_section()

    def _route_visible_section(self, *args):
        if not self._friendly_ready or 'design' not in self.sections:
            return
        index = self.tabs.currentIndex()
        page = self.tabs.widget(index)
        controls = (QAbstractButton, QAbstractItemView, QComboBox, QLineEdit)
        usable = page is not None and any(isinstance(child, controls) and child.isVisibleTo(page)
                                         for child in page.findChildren(QWidget))
        if index == self.sections.get('study') or not usable:
            self.select_section('design')
        if hasattr(self, 'study_flow'):
            self.study_flow.refresh()

    def load_pcsel_example(self):
        super().load_pcsel_example(); self.select_section('design')

    def load_conformal_example(self):
        super().load_conformal_example(); self.select_section('design')

    def open_diagnostic(self, target):
        field = target.get('field', '').removeprefix('settings.')
        parts = field.split('.'); root = parts[0]
        if not self._friendly_ready: return super().open_diagnostic(target)
        if root in ('layers', self.shape_key):
            self.design_view_choice.setCurrentIndex(1)
            self.adapt_layout()
            identity = target.get('object_id', '')
            index = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            if not identity and len(parts) > 1 and index is None:
                identity = parts[1] if len(parts) > 2 else ''
            # Keep the exact canonical tree selection for advanced inspection.
            self.structured[root].open_field(field, target.get('object_id', ''))
            if self.geometry_editor.select_object(root, identity, index):
                control = self.geometry_editor.form.diagnostic_control(parts[2:])
                if control is not None:
                    return reveal_and_focus(control, message=target.get('message', ''))
            return super().open_diagnostic(target)
        if root in self.friendly_forms:
            if root == 'aperture_um':
                self.design_view_choice.setCurrentIndex(0)
                self.adapt_layout()
            # Select the same canonical item for advanced inspection and older
            # diagnostic integrations, then reveal its friendly control.
            self.structured[root].open_field(field, target.get('object_id', ''))
            form = self.friendly_forms[root]
            if root == 'materials' and len(parts) > 1 and hasattr(self, 'material_picker'):
                self.material_picker.setCurrentIndex(self.material_picker.findData(parts[1])); self._material_selected()
                path = parts[2:]
            else:
                path = parts if root in form.controls else parts[1:]
            control = form.diagnostic_control(path)
            if control is not None and reveal_and_focus(control, message=target.get('message', '')):
                return True
        if root in ('model', 'lattice_nm', 'period_um'):
            self.design_view_choice.setCurrentIndex(0)
            self.adapt_layout()
            if root == 'period_um' and hasattr(self, 'period_form'):
                control = self.period_form.diagnostic_control(parts)
                if control is not None:
                    return reveal_and_focus(control, message=target.get('message', ''))
        return super().open_diagnostic(target)

    def adapt_layout(self):
        if hasattr(self, 'study_flow'): self.study_flow.adapt_layout()
        if hasattr(self, 'design_settings') and hasattr(self, 'geometry_editor'):
            compact = self.width() < 1000
            structure = self.design_view_choice.currentIndex() == 1
            self.design_view_choice.setVisible(compact)
            self.design_settings.setVisible(not compact or not structure)
            self.geometry_editor.setVisible(not compact or structure)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adapt_layout()
