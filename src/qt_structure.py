"""Native Qt multilayer construction, backed by the shared project store."""
from __future__ import annotations

import colorsys
import hashlib
import math
from pathlib import Path

from PyQt6.QtCore import Qt, QSignalBlocker, QSize, QRect
from PyQt6.QtGui import QColor, QIcon, QFont, QFontMetrics, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget, QFileDialog,
    QVBoxLayout, QWidget, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QMenu, QCheckBox,
)
from matplotlib.artist import Artist
from matplotlib.collections import PatchCollection
from matplotlib.figure import Figure
from matplotlib.patches import Polygon, Rectangle
from matplotlib.ticker import FuncFormatter

from model import LAYER_COLS, PAT_COLS
from structure_builder import material_catalog, mutate_region, mutate_structure, rows
from structure_preview import (
    clip_polygon, layer_positions, normalize_region, periodic_centers,
    region_polygon, section_interval,
)
from qt_common import PlotWidget, CompactDoubleSpinBox


class LayerItemDelegate(QStyledItemDelegate):
    """Three bounded lines per layer; row height follows the actual Qt font."""
    def sizeHint(self, option, index):
        font = QFont(option.font)
        font.setBold(True)
        line = QFontMetrics(font).height() + 3
        return QSize(0, 3 * line + 18)

    def paint(self, painter, option, index):
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        lines = str(index.data(Qt.ItemDataRole.DisplayRole) or '').split('\n')
        style_option.text = ''
        style_option.icon = QIcon()
        style = style_option.widget.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, style_option, painter, style_option.widget)
        painter.save()
        painter.setClipRect(option.rect)
        color = index.data(int(Qt.ItemDataRole.UserRole) + 1) or '#738496'
        painter.fillRect(QRect(option.rect.x()+9, option.rect.y()+10, 5, option.rect.height()-20), QColor(color))
        font = QFont(option.font)
        font.setBold(True)
        line_height = QFontMetrics(font).height() + 3
        text_role = (QPalette.ColorRole.HighlightedText if option.state & QStyle.StateFlag.State_Selected
                     else QPalette.ColorRole.Text)
        painter.setPen(option.palette.color(text_role))
        for row, line in enumerate(lines[:3]):
            font.setBold(row == 0)
            painter.setFont(font)
            bounds = QRect(option.rect.x()+23, option.rect.y()+9+row*line_height,
                           max(0, option.rect.width()-35), line_height)
            visible = QFontMetrics(font).elidedText(line, Qt.TextElideMode.ElideRight, bounds.width())
            painter.drawText(bounds, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, visible)
        painter.restore()


class LayerLabelLayout(Artist):
    """Choose readable section labels in display pixels on each render/resize."""
    def __init__(self, axes, labels, selected, plan, plan_title):
        super().__init__()
        self.axes = axes
        self.labels = labels
        self.selected = selected
        self.plan = plan
        self.plan_title = plan_title
        self.set_zorder(2.5)
        self.set_in_layout(False)

    @staticmethod
    def _fit(text, font, renderer, width):
        if renderer.get_text_width_height_descent(text, font, False)[0] <= width:
            return text
        while text and renderer.get_text_width_height_descent(text+'…', font, False)[0] > width:
            text = text[:-1]
        return text+'…' if text else ''

    def draw(self, renderer):
        occupied = []
        priority = sorted(self.labels, key=lambda pair: (
            pair[0]['name'] != self.selected, not pair[0]['halfspace'],
            -(pair[0]['z1']-pair[0]['z0'])))
        for layer, text in priority:
            full = layer['name'] + (' ∞' if layer['halfspace'] else '')
            text.set_text(self._fit(full, text.get_fontproperties(), renderer, self.axes.bbox.width * .94))
            text.set_visible(True)
            bounds = text.get_window_extent(renderer).expanded(1.02, 1.35)
            lower, upper = self.axes.transData.transform([(0, layer['z0']), (0, layer['z1'])])[:, 1]
            fits_layer = abs(upper-lower) >= bounds.height
            fits_plot = bounds.y0 >= self.axes.bbox.y0 and bounds.y1 <= self.axes.bbox.y1
            show = fits_plot and (fits_layer or layer['name'] == self.selected)
            show = show and not any(bounds.overlaps(other) for other in occupied)
            text.set_visible(show)
            if show:
                occupied.append(bounds)
        self.plan.title.set_text(self._fit(self.plan_title, self.plan.title.get_fontproperties(),
                                          renderer, self.plan.bbox.width))
        self.stale = False


def _number(value=0, minimum=-1e12, maximum=1e12, decimals=6):
    widget = CompactDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setMinimumWidth(105)
    return widget


def _choices(widget, choices, selected=None):
    """Refresh items without dispatching selection events back into the editor."""
    if selected is None:
        selected = widget.currentData()
    with QSignalBlocker(widget):
        widget.clear()
        for label, value in choices:
            widget.addItem(str(label), value)
        index = widget.findData(selected)
        widget.setCurrentIndex(index if index >= 0 else (0 if choices else -1))


def _color(material):
    if str(material).lower() in ('air', 'vacuum', 'air / vacuum'):
        return '#f8fafc'
    digest = hashlib.sha256(str(material).encode('utf8')).digest()
    r, g, b = colorsys.hls_to_rgb(int.from_bytes(digest[:2], 'big') % 360 / 360., .76, .50)
    return '#%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255))


def geometry_figure(layers, patterns, selected, lattice_x, lattice_y, cells=1, cut_y=0.):
    """Matplotlib plan and exact section; dimensions agree with S4 shape semantics."""
    ax, ay = float(lattice_x), float(lattice_y)
    if ax <= 0 or ay <= 0:
        raise ValueError('Lattice periods must be greater than zero.')
    cells = max(1, min(7, int(cells)))
    stack, total, pad = layer_positions(layers, max(ax, ay))
    by_name = {layer['name']: layer for layer in stack}
    selected_layer = by_name.get(selected, stack[1])
    selected = selected_layer['name']
    cut = (float(cut_y) + ay / 2) % ay - ay / 2
    xmin, xmax, ymin, ymax = -cells * ax / 2, cells * ax / 2, -cells * ay / 2, cells * ay / 2
    window = (xmin, xmax, ymin, ymax)
    fig = Figure(figsize=(8.4, 3.6), layout='constrained')
    plan, section = fig.subplots(1, 2, gridspec_kw={'width_ratios': [1, 1.35]})
    plan.add_patch(Rectangle((xmin, ymin), xmax-xmin, ymax-ymin,
                             facecolor=_color(selected_layer['material']), edgecolor='#738496', lw=.6))
    bases = [Rectangle((xmin, layer['z0']), xmax-xmin, layer['z1']-layer['z0']) for layer in stack]
    section.add_collection(PatchCollection(bases, facecolors=[_color(layer['material']) for layer in stack],
                                          edgecolors='#738496', linewidths=.55))
    warnings = []
    rendered = 0
    for raw in rows(patterns, PAT_COLS):
        if rendered > 15000:
            warnings.append('Preview detail limit reached. Display fewer cells for complete geometry.')
            break
        region = normalize_region(raw)
        layer = by_name.get(region['layer'])
        if layer is None:
            continue
        try:
            if region['layer'] == selected:
                polygons = [clip_polygon(region_polygon(region, center), window)
                            for center in periodic_centers(region, ax, ay, window)]
                patches = [Polygon(poly) for poly in polygons if len(poly) > 2]
                plan.add_collection(PatchCollection(patches, facecolors=_color(region['material']),
                                                    edgecolors='#738496', linewidths=.6))
                rendered += len(patches)
            patches = []
            for center in periodic_centers(region, ax, ay, (xmin, xmax, cut, cut)):
                interval = section_interval(region, cut, center)
                if interval is not None:
                    left, right = max(xmin, interval[0]), min(xmax, interval[1])
                    if right > left:
                        patches.append(Rectangle((left, layer['z0']), right-left, layer['z1']-layer['z0']))
            section.add_collection(PatchCollection(patches, facecolors=_color(region['material']),
                                                   edgecolors='#738496', linewidths=.6))
            rendered += len(patches)
        except ValueError as exc:
            if str(exc) not in warnings:
                warnings.append(str(exc))
    plan.add_patch(Rectangle((-ax/2, -ay/2), ax, ay, fill=False, edgecolor='#54738d',
                             linewidth=1.2, linestyle='--'))
    plan.axhline(cut, color='#21a79b', linestyle=':', linewidth=1.6)
    section.add_patch(Rectangle((xmin, selected_layer['z0']), xmax-xmin,
                                selected_layer['z1']-selected_layer['z0'], fill=False,
                                edgecolor='#21a79b', linewidth=2.0))
    for z in (0, total):
        section.axhline(z, color='#54738d', linewidth=.9, linestyle='--')
    # Physical thickness stays exact. Display-space labels never overlap, even
    # when a selected layer is thinner than the text or the canvas is resized.
    labels = []
    for layer in stack:
        label = layer['name'] + (' ∞' if layer['halfspace'] else '')
        text = section.text(xmin + .025*(xmax-xmin), (layer['z0']+layer['z1'])/2, label,
                     fontsize=8.5, color='#17283d', va='center', clip_on=True, in_layout=False,
                     bbox={'facecolor': '#ffffff', 'edgecolor': 'none', 'alpha': .84, 'pad': 1.5})
        labels.append((layer, text))
    plan.set(xlim=(xmin, xmax), ylim=(ymin, ymax), xlabel='x (µm)', ylabel='y (µm)',
             title=f'Plan · {selected[:28]}'+('…' if len(selected)>28 else ''))
    plan.set_aspect('equal', adjustable='box')
    section.set(xlim=(xmin, xmax), ylim=(total+pad, -pad), xlabel='x (µm)', ylabel='Depth z (µm)',
                title=f'Section · y = {cut:g} µm')
    for axis in (plan, section):
        axis.tick_params(labelsize=8)
        axis.title.set_fontsize(10)
        axis.xaxis.label.set_size(9)
        axis.yaxis.label.set_size(9)
    section.add_artist(LayerLabelLayout(section, labels, selected, plan, f'Plan · {selected}'))
    fig._s4_geometry = {'stack': stack, 'selected': selected, 'section': section,
                        'warnings': warnings, 'total_um': total, 'cut_y_um': cut, 'labels': labels}
    return fig


def apply_geometry_units(figure, unit):
    """Convert display formatting only; selection geometry stays in micrometres."""
    factor = 1000 if unit == 'nm' else 1
    text = lambda value: f'{value * factor:g}'
    for axis in figure.axes:
        axis.set_xlabel(f'x ({unit})')
        axis.set_ylabel(f'y ({unit})' if hasattr(axis, 'zaxis') or axis is figure.axes[0] else f'Depth z ({unit})')
        axis.xaxis.set_major_formatter(FuncFormatter(lambda value, position: text(value)))
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, position: text(value)))
        axis.format_xdata = text
        axis.format_ydata = text
        if hasattr(axis, 'zaxis'):
            axis.set_zlabel(f'Depth z ({unit})')
            axis.zaxis.set_major_formatter(FuncFormatter(lambda value, position: text(value)))
            axis.format_zdata = text
    metadata = getattr(figure, '_s4_geometry', {})
    metadata['display_unit'] = unit
    if metadata.get('section') is not None:
        metadata['section'].set_title(f"Section · y = {text(metadata['cut_y_um'])} {unit}")


class StructurePage(QWidget):
    """Synchronous selection and atomic edits eliminate stale browser callbacks."""
    def heightForWidth(self, width):
        # The editors already scroll, and the splitters resize the preview.
        # A wrapping label otherwise makes QScrollArea reserve the splitter's
        # preferred height, pushing Apply below the fold on a normal desktop.
        layout = self.layout()
        if layout is None:
            return super().heightForWidth(width)
        return max(self.minimumSizeHint().height(), layout.minimumHeightForWidth(width))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'workspace_splitter'):
            return
        wide = self.width() >= 1120
        orientation = Qt.Orientation.Horizontal if wide else Qt.Orientation.Vertical
        if self.workspace_splitter.orientation() != orientation:
            self.workspace_splitter.setOrientation(orientation)
            self.workspace_splitter.setSizes([650, 335] if wide else [430, 285])

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.setObjectName('structurePage')
        self.store = store
        self._selected = None
        self._region = None
        self._unit = 'nm'
        self._refreshing = False
        self._snapshot = None
        self._lattice_snapshot = None
        self._mutating = False
        self._actions = []
        self._build()
        store.changed.connect(self.refresh)
        store.library_changed.connect(self._refresh_materials)
        store.busy_changed.connect(self._busy)
        if hasattr(store, 'task_finished'):
            store.task_finished.connect(self._export_finished)
            store.task_failed.connect(self._export_failed)
        self.refresh()
        self._busy(store.busy)

    def _button(self, text, action, name, primary=False):
        result = QPushButton(text)
        result.setObjectName(name)
        if primary:
            result.setProperty('primary', True)
        result.clicked.connect(action)
        self._actions.append(result)
        return result

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        title = QLabel('Structure')
        title.setObjectName('pageTitle')
        heading = QHBoxLayout()
        heading.addWidget(title)
        heading.addStretch()
        self.export_button = self._button('Export ▾', lambda: None, 'structureExport')
        export_menu = QMenu(self.export_button)
        export_menu.addAction('COMSOL model…', self.export_comsol).setObjectName('exportComsol')
        export_menu.addAction('CAD / STEP…', self.export_cad).setObjectName('exportCad')
        self.export_button.setMenu(export_menu)
        heading.addWidget(self.export_button)
        root.addLayout(heading)
        subtitle = QLabel('Build your multilayer device once. Simulations, optimization and field maps use this structure.')
        subtitle.setObjectName('muted')
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)
        lattice = QGroupBox('Unit cell')
        layout = QHBoxLayout(lattice)
        self.lattice_x = _number(.77, 1e-9)
        self.lattice_x.setObjectName('latticeX')
        self.lattice_y = _number(.77, 1e-9)
        self.lattice_y.setObjectName('latticeY')
        self.lattice_x.setSuffix(' ' + self._unit)
        self.lattice_y.setSuffix(' ' + self._unit)
        self.lattice_x_label = QLabel('Period')
        self.lattice_y_label = QLabel('Period Y')
        self.square_lattice = QCheckBox('Square lattice')
        self.square_lattice.setObjectName('squareLattice')
        self.square_lattice.setToolTip('Link both side lengths. Uncheck to enter separate X and Y periods.')
        self.square_lattice.setChecked(True)
        self.square_lattice.toggled.connect(self._lattice_mode_changed)
        self.lattice_x.valueChanged.connect(self._link_lattice_period)
        layout.addWidget(self.square_lattice)
        layout.addWidget(self.lattice_x_label)
        layout.addWidget(self.lattice_x)
        layout.addWidget(self.lattice_y_label)
        layout.addWidget(self.lattice_y)
        self._lattice_mode_changed(True)
        layout.addWidget(self._button('Apply lattice', self.apply_lattice, 'applyLattice'))
        layout.addStretch()
        unit_card = QGroupBox('Editor units')
        unit_layout = QHBoxLayout(unit_card)
        unit_layout.addWidget(QLabel('Dimensions'))
        self.units = QComboBox()
        self.units.setObjectName('structureUnits')
        self.units.addItems(['nm', 'µm'])
        self.units.currentTextChanged.connect(self._change_units)
        unit_layout.addWidget(self.units)
        self.units.setToolTip('Display units for every length in this Structure workspace, including lattice, layers, regions and previews.')
        settings_row = QHBoxLayout()
        settings_row.addWidget(lattice, 1)
        settings_row.addWidget(unit_card)
        root.addLayout(settings_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setObjectName('structureSplitter')
        root.addWidget(splitter, 1)
        sidebar = QGroupBox('Layer stack')
        sidebar.setMinimumWidth(235)
        side = QVBoxLayout(sidebar)
        self.summary = QLabel()
        self.summary.setObjectName('structureSummary')
        self.summary.setWordWrap(True)
        side.addWidget(self.summary)
        self.layer_list = QListWidget()
        self.layer_list.setObjectName('layerList')
        self.layer_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.layer_list.setSpacing(3)
        self.layer_list.setWordWrap(False)
        self.layer_list.setUniformItemSizes(True)
        self.layer_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.layer_list.setItemDelegate(LayerItemDelegate(self.layer_list))
        self.layer_list.currentItemChanged.connect(self._select_item)
        side.addWidget(self.layer_list, 1)
        buttons = QGridLayout()
        for index, (text, action) in enumerate((('Add above', 'above'), ('Add below', 'below'),
                                               ('Duplicate', 'duplicate'), ('Delete', 'delete'),
                                               ('Move up', 'up'), ('Move down', 'down'))):
            widget = self._button(text, lambda checked=False, op=action: self.layer_action(op), 'layer_' + action)
            buttons.addWidget(widget, index//2, index % 2)
        side.addLayout(buttons)
        side.addWidget(self._button('Undo structure edit', self.undo, 'undoStructure'))
        hint = QLabel('Top → bottom. First and last media extend to infinity.')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        side.addWidget(hint)
        splitter.addWidget(sidebar)

        right = QSplitter(Qt.Orientation.Vertical)
        self.workspace_splitter = right
        right.setObjectName('structureWorkspaceSplitter')
        right.setChildrenCollapsible(False)
        self.preview_card = QGroupBox('Structure preview')
        preview = QVBoxLayout(self.preview_card)
        controls = QGridLayout()
        self.view_mode = QComboBox()
        self.view_mode.setObjectName('structureViewMode')
        self.view_mode.addItems(['2D · Plan & section', '3D · Structure'])
        self.view_mode.currentIndexChanged.connect(self.draw_preview)
        controls.addWidget(self.view_mode, 0, 0, 1, 2)
        self.cells = QComboBox()
        self.cells.setObjectName('previewCells')
        self.cells.addItems(['1 × 1 cell', '3 × 3 cells', '5 × 5 cells', '7 × 7 cells'])
        self.cells.currentIndexChanged.connect(self.draw_preview)
        self.cut_y = _number(0)
        self.cut_y.setSuffix(' ' + self._unit)
        self.cut_y.setObjectName('previewCutY')
        self.cut_y.valueChanged.connect(self.draw_preview)
        controls.addWidget(QLabel('Periodic cells'), 1, 0)
        controls.addWidget(self.cells, 1, 1)
        self.cut_label = QLabel('Section Y')
        controls.addWidget(self.cut_label, 1, 2)
        controls.addWidget(self.cut_y, 1, 3)
        self.reset_view = QPushButton('Reset view')
        self.reset_view.setObjectName('resetStructureView')
        self.reset_view.clicked.connect(lambda: self.draw_preview(reset=True))
        controls.addWidget(self.reset_view, 0, 3)
        controls.setColumnStretch(2, 1)
        preview.addLayout(controls)
        self.plot = PlotWidget()
        self.plot.setObjectName('structurePlot')
        self.plot.setMinimumHeight(280)
        preview.addWidget(self.plot, 1)
        self.preview_note = QLabel('Geometry view · click a layer in the section to select it · dashed box: unit cell')
        self.preview_note.setObjectName('muted')
        self.preview_note.setWordWrap(True)
        preview.addWidget(self.preview_note)
        right.addWidget(self.preview_card)

        self.tabs = QTabWidget()
        self.tabs.setObjectName('structureEditorTabs')
        self.tabs.setMinimumWidth(285)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.layer_editor = QWidget()
        layer_layout = QVBoxLayout(self.layer_editor)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.layer_name = QLineEdit()
        self.layer_name.setObjectName('layerName')
        self.layer_material = QComboBox()
        self.layer_material.setObjectName('layerMaterial')
        self.layer_material.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.layer_material.setMinimumContentsLength(14)
        self.layer_thickness = _number(250, 0)
        self.layer_thickness.setObjectName('layerThickness')
        form.addRow('Layer name', self.layer_name)
        form.addRow('Material', self.layer_material)
        form.addRow('Thickness', self.layer_thickness)
        layer_layout.addLayout(form)
        self.layer_hint = QLabel()
        self.layer_hint.setWordWrap(True)
        self.layer_hint.setObjectName('muted')
        layer_layout.addWidget(self.layer_hint)
        layer_layout.addWidget(self._button('Apply layer', lambda: self.layer_action('apply'), 'applyLayer', True))
        layer_layout.addStretch()
        self.tabs.addTab(self._scroll(self.layer_editor), 'Layer')

        self.region_editor = QWidget()
        region_layout = QVBoxLayout(self.region_editor)
        region_select = QHBoxLayout()
        self.region_choice = QComboBox()
        self.region_choice.setObjectName('regionChoice')
        self.region_choice.currentIndexChanged.connect(self._select_region)
        region_select.addWidget(QLabel('Region'))
        region_select.addWidget(self.region_choice, 1)
        region_layout.addLayout(region_select)
        grid = QFormLayout()
        grid.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.shape = QComboBox()
        self.shape.setObjectName('regionShape')
        for label, value in [('Circle', 'circle'), ('Ellipse', 'ellipse'), ('Rectangle', 'rectangle')]:
            self.shape.addItem(label, value)
        self.shape.currentIndexChanged.connect(self._shape_labels)
        self.region_material = QComboBox()
        self.region_material.setObjectName('regionMaterial')
        self.region_material.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.region_material.setMinimumContentsLength(14)
        self.region_x, self.region_y = _number(0), _number(0)
        self.region_sx, self.region_sy = _number(100, 1e-9), _number(100, 1e-9)
        self.region_angle = _number(0, -36000, 36000, 3)
        self.region_angle.setSuffix('°')
        for widget, name in ((self.region_x, 'regionX'), (self.region_y, 'regionY'),
                              (self.region_sx, 'regionSizeX'), (self.region_sy, 'regionSizeY'),
                              (self.region_angle, 'regionAngle')):
            widget.setObjectName(name)
        self.sx_label, self.sy_label = QLabel('Radius'), QLabel('Y radius')
        for label, widget in [(QLabel('Shape'), self.shape), (QLabel('Material'), self.region_material),
                              (QLabel('Centre X'), self.region_x), (QLabel('Centre Y'), self.region_y),
                              (self.sx_label, self.region_sx), (self.sy_label, self.region_sy),
                              (QLabel('Rotation'), self.region_angle)]:
            grid.addRow(label, widget)
        region_layout.addLayout(grid)
        region_buttons = QGridLayout()
        for index, (text, op) in enumerate([('Add region', 'add'), ('Apply region', 'apply'), ('Duplicate', 'copy'), ('Delete', 'delete')]):
            region_buttons.addWidget(self._button(text, lambda checked=False, action=op: self.region_action(action),
                                                   'region_' + op, op == 'apply'), index//2, index%2)
        region_layout.addLayout(region_buttons)
        self.region_hint = QLabel()
        self.region_hint.setWordWrap(True)
        self.region_hint.setObjectName('muted')
        region_layout.addWidget(self.region_hint)
        region_layout.addStretch()
        self.tabs.addTab(self._scroll(self.region_editor), 'Regions')

        repeat_page = QWidget()
        repeat = QVBoxLayout(repeat_page)
        instructions = QLabel('Repeat a contiguous block of finite layers. Every hole and material region is copied with its layer.')
        instructions.setWordWrap(True)
        repeat.addWidget(instructions)
        form = QFormLayout()
        self.repeat_start, self.repeat_end = QComboBox(), QComboBox()
        self.repeat_start.setObjectName('repeatStart')
        self.repeat_end.setObjectName('repeatEnd')
        self.repeat_count = QSpinBox()
        self.repeat_count.setObjectName('repeatCount')
        self.repeat_count.setRange(1, 100)
        form.addRow('First layer', self.repeat_start)
        form.addRow('Last layer', self.repeat_end)
        form.addRow('Additional copies', self.repeat_count)
        repeat.addLayout(form)
        repeat.addWidget(self._button('Repeat layer block', lambda: self.layer_action('repeat'), 'repeatBlock', True))
        repeat.addStretch()
        self.tabs.addTab(self._scroll(repeat_page), 'Repeat')
        right.addWidget(self.tabs)
        right.setStretchFactor(0, 7)
        right.setStretchFactor(1, 3)
        right.setSizes([430, 285])
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([270, 900])
        self.status = QLabel('Select a layer, edit its properties, then apply your changes.')
        self.status.setObjectName('structureStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    @staticmethod
    def _scroll(widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(widget)
        scroll.setMinimumHeight(190)
        return scroll

    def _message(self, text, error=False):
        self.status.setText(str(text))
        self.status.setProperty('error', error)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    @property
    def selected_layer(self):
        return self._selected

    def select_layer(self, name):
        for i in range(self.layer_list.count()):
            if self.layer_list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                self.layer_list.setCurrentRow(i)
                return True
        return False

    def _select_item(self, item, previous=None):
        if self._refreshing or item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if name == self._selected:
            return
        self._selected = name
        self._region = None
        self._load_layer()
        self.draw_preview()

    def _refresh_materials(self):
        try:
            catalog = material_catalog(self.store.context, self.store.materials)
            choices = [(label, key) for key, (label, _) in catalog.items()]
            _choices(self.layer_material, choices)
            _choices(self.region_material, choices)
        except (ValueError, KeyError, OSError) as exc:
            self._message(str(exc), True)

    def refresh(self, reason='structure'):
        """Keep the current selection across table, material and library updates."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            stack = rows(self.store.layers, LAYER_COLS)
            regions = rows(self.store.patterns, PAT_COLS)
            snapshot = (repr(stack), repr(regions))
            geometry_changed = snapshot != self._snapshot
            self._snapshot = snapshot
            if geometry_changed and not self._mutating:
                self._region = None
            self._refresh_materials()
            available = [layer['Name'] for layer in stack]
            if self._selected not in available:
                self._selected = available[1] if len(available) > 1 else (available[0] if available else None)
                self._region = None
            with QSignalBlocker(self.layer_list):
                self.layer_list.clear()
                counts = {}
                for region in regions:
                    counts[region['Layer']] = counts.get(region['Layer'], 0) + 1
                for index, layer in enumerate(stack):
                    count = counts.get(layer['Name'], 0)
                    thickness = ('Incident medium · ∞' if index == 0 else 'Exit medium · ∞' if index == len(stack)-1
                                 else self._length_text(float(layer['Thickness_um'])))
                    extra = f' · {count} region' + ('s' if count != 1 else '') if count else ''
                    item = QListWidgetItem(f"{index+1:03d}  {layer['Name']}\n{layer['Material']}\n{thickness}{extra}")
                    item.setData(Qt.ItemDataRole.UserRole, layer['Name'])
                    item.setData(int(Qt.ItemDataRole.UserRole) + 1, _color(layer['Material']))
                    item.setToolTip(f"{layer['Name']}\n{layer['Material']}\n{thickness}{extra}")
                    self.layer_list.addItem(item)
                    if layer['Name'] == self._selected:
                        self.layer_list.setCurrentItem(item)
            finite = [(layer['Name'], layer['Name']) for layer in stack[1:-1]]
            _choices(self.repeat_start, finite)
            _choices(self.repeat_end, finite)
            total = sum(float(layer['Thickness_um']) for layer in stack[1:-1])
            self.summary.setText(f'{max(0, len(stack)-2)} finite layers · {self._length_text(total)} total')
            saved_lattice = (float(self.store.settings.get('ax_um', .77)),
                             float(self.store.settings.get('ay_um', .77)))
            # Unrelated updates must not replace an un-applied lattice draft.
            if saved_lattice != self._lattice_snapshot or reason == 'project':
                self._lattice_snapshot = saved_lattice
                with QSignalBlocker(self.lattice_x), QSignalBlocker(self.lattice_y), QSignalBlocker(self.square_lattice):
                    self.lattice_x.setValue(saved_lattice[0] * self._display_factor())
                    self.lattice_y.setValue(saved_lattice[1] * self._display_factor())
                    self.square_lattice.setChecked(math.isclose(*saved_lattice, rel_tol=1e-10, abs_tol=1e-12))
                self._lattice_mode_changed(self.square_lattice.isChecked())
            if geometry_changed or self._mutating:
                self._load_layer()
            self.draw_preview()
        finally:
            self._refreshing = False

    def _load_layer(self):
        stack = rows(self.store.layers, LAYER_COLS)
        layer = next((row for row in stack if row['Name'] == self._selected), None)
        if layer is None:
            return
        halfspace = self._selected in (stack[0]['Name'], stack[-1]['Name'])
        self.layer_name.setText(str(layer['Name']))
        with QSignalBlocker(self.layer_material):
            self.layer_material.setCurrentIndex(self.layer_material.findData('current:' + str(layer['Material'])))
        factor = 1000 if self._unit == 'nm' else 1
        self.layer_thickness.setValue(float(layer['Thickness_um']) * factor)
        self.layer_thickness.setSuffix(' ' + self._unit)
        self.layer_thickness.setEnabled(not halfspace and not self.store.busy)
        self.layer_hint.setText('Semi-infinite medium: thickness stays zero.' if halfspace else
                               'Changes apply to this layer and appear in every other workspace.')
        choices = [('New region', 'new')]
        for index, region in enumerate(rows(self.store.patterns, PAT_COLS)):
            if region['Layer'] == self._selected:
                choices.append((f"{len(choices)} · {region['Shape']} · {region['Material']}", str(index)))
        if self._region is None:
            self._region = choices[1][1] if len(choices) > 1 else 'new'
        _choices(self.region_choice, choices, self._region)
        self._region = self.region_choice.currentData()
        self.region_editor.setEnabled(not halfspace and not self.store.busy)
        self._load_region()
        self._busy(self.store.busy)

    def _select_region(self, index=None):
        self._region = self.region_choice.currentData()
        self._load_region()

    def _load_region(self):
        data = rows(self.store.patterns, PAT_COLS)
        index = int(self._region) if str(self._region).isdigit() else -1
        existing = 0 <= index < len(data) and data[index]['Layer'] == self._selected
        region = data[index] if existing else dict(Shape='circle', Material='Air', CenterX_um=0.,
                                                  CenterY_um=0., SizeX_um=.1, SizeY_um=.1, Angle_deg=0.)
        with QSignalBlocker(self.shape), QSignalBlocker(self.region_material):
            self.shape.setCurrentIndex(max(0, self.shape.findData(region['Shape'])))
            material_index = self.region_material.findData('current:' + region['Material'])
            if material_index < 0:
                material_index = self.region_material.findData('builtin:Air / Vacuum')
            self.region_material.setCurrentIndex(max(0, material_index))
        factor = 1000 if self._unit == 'nm' else 1
        for widget, key in ((self.region_x, 'CenterX_um'), (self.region_y, 'CenterY_um'),
                            (self.region_sx, 'SizeX_um'), (self.region_sy, 'SizeY_um')):
            value = float(region[key])
            if key == 'SizeY_um' and region['Shape'] == 'circle':
                value = float(region['SizeX_um'])
            widget.setValue(value * factor)
            widget.setSuffix(' ' + self._unit)
        self.region_angle.setValue(float(region['Angle_deg']))
        self._shape_labels()
        self._busy(self.store.busy)

    def _shape_labels(self, index=None):
        shape = self.shape.currentData()
        self.sx_label.setText('Radius' if shape == 'circle' else 'X radius' if shape == 'ellipse' else 'Full width X')
        self.sy_label.setText('Y radius' if shape == 'ellipse' else 'Full width Y')
        self.sy_label.setVisible(shape != 'circle')
        self.region_sy.setVisible(shape != 'circle')
        self.region_angle.setEnabled(shape != 'circle' and not self.store.busy)
        self.region_hint.setText('Circles use radius; ellipses use X/Y radii; rectangles use full X/Y widths. '
                                 'Select Air for an air hole. Regions repeat with the unit cell.')

    def _change_units(self, unit):
        if unit == self._unit:
            return
        factor = .001 if unit == 'µm' else 1000.
        for widget in (self.lattice_x, self.lattice_y, self.cut_y, self.layer_thickness,
                       self.region_x, self.region_y, self.region_sx, self.region_sy):
            with QSignalBlocker(widget):
                widget.setValue(widget.value() * factor)
                widget.setSuffix(' ' + unit)
        self._unit = unit
        # Refreshes read-only stack labels without reloading unchanged draft fields.
        self.refresh('units')

    def _display_factor(self):
        return 1000 if self._unit == 'nm' else 1

    def _length_text(self, micrometres):
        return f'{micrometres * self._display_factor():g} {self._unit}'

    def _link_lattice_period(self, value):
        if self.square_lattice.isChecked():
            self.lattice_y.setValue(value)

    def _lattice_mode_changed(self, square):
        self.lattice_x_label.setText('Period' if square else 'Period X')
        self.lattice_y_label.setVisible(not square)
        self.lattice_y.setVisible(not square)
        if square:
            self.lattice_y.setValue(self.lattice_x.value())

    def apply_lattice(self):
        if self.store.busy:
            return
        try:
            y = self.lattice_x.value() if self.square_lattice.isChecked() else self.lattice_y.value()
            self.store.update_settings({'ax_um': self.lattice_x.value() / self._display_factor(),
                                        'ay_um': y / self._display_factor()})
            self._message('Unit cell updated across all workspaces.')
        except (ValueError, TypeError) as exc:
            self._message(exc, True)

    def layer_action(self, action):
        if self.store.busy:
            return
        try:
            result = mutate_structure(self.store.context, self.store.materials, self.store.layers,
                                      self.store.patterns, self._selected, action,
                                      name=self.layer_name.text(), material=self.layer_material.currentData(),
                                      thickness=self.layer_thickness.value(), unit=self._unit,
                                      start=self.repeat_start.currentData(), end=self.repeat_end.currentData(),
                                      count=self.repeat_count.value())
            old_selection = self._selected
            self._selected = result[3]
            self._region = None
            self._mutating = True
            try:
                self.store.set_structure(*result[:3], reason='structure')
            except Exception:
                self._selected = old_selection
                raise
            finally:
                self._mutating = False
            self._message(f'Structure updated. Selected layer: {self._selected}.')
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self._message(exc, True)

    def region_action(self, action):
        if self.store.busy:
            return
        try:
            result = mutate_region(self.store.context, self.store.materials, self.store.layers,
                                   self.store.patterns, self._selected, self._region, action,
                                   shape=self.shape.currentData(), material=self.region_material.currentData(),
                                   x=self.region_x.value(), y=self.region_y.value(),
                                   sx=self.region_sx.value(), sy=self.region_sy.value(),
                                   angle=self.region_angle.value(), unit=self._unit)
            self._region = result[3]
            self._mutating = True
            try:
                self.store.set_structure(*result[:3], reason='structure')
            finally:
                self._mutating = False
            self._message(f'Regions updated in {self._selected}.')
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self._message(exc, True)

    def undo(self):
        if self.store.busy:
            return
        try:
            self.store.undo()
            self._message('Previous structure restored.')
        except (ValueError, TypeError) as exc:
            self._message(exc, True)

    def export_comsol(self):
        self._export_structure(False)

    def export_cad(self):
        self._export_structure(True)

    def _export_structure(self, cad):
        if self.store.busy:
            return
        from qt_export import ExportDialog
        dialog = ExportDialog(self.store.settings, cad, self)
        if not dialog.exec():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export CAD' if cad else 'Export COMSOL model script',
            'OpticalStructure.step' if cad else 'S4UnitCell.java',
            'STEP CAD (*.step *.stp)' if cad else 'COMSOL Java model (*.java)')
        if not path:
            return
        try:
            import copy
            options, include_air = dialog.options(), dialog.air.isChecked()
            snapshot = copy.deepcopy((self.store.materials, self.store.layers, self.store.patterns, self.store.settings))
            def export():
                if cad:
                    from cad_export import export_cad_step
                    return str(export_cad_step(path, *snapshot, options, include_air))
                from comsol_export import export_comsol_java
                return str(export_comsol_java(path, *snapshot, options))
            self._message(f'Exporting {options.cells_x} × {options.cells_y} model in {options.unit}…')
            if hasattr(self.store, 'run_task'):
                self.store.run_task('structure-export', export)
            else:
                self._export_finished('structure-export', export())
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self._message('Structure export: ' + str(exc), True)

    def _export_finished(self, name, result):
        if name == 'structure-export':
            if str(result).lower().endswith('.java'):
                self._message('Java source exported: ' + str(result) + '. Compile with COMSOL, then open the resulting .class (not the .java). Instructions and a .build.ps1 helper were saved beside it.')
            else:
                self._message('Model exported: ' + str(result))

    def _export_failed(self, name, error):
        if name == 'structure-export':
            self._message('Structure export: ' + str(error), True)

    def _busy(self, busy):
        for widget in self._actions:
            widget.setEnabled(not busy)
        stack = rows(self.store.layers, LAYER_COLS)
        names = [layer['Name'] for layer in stack]
        index = names.index(self._selected) if self._selected in names else -1
        halfspace = index in (0, len(stack)-1) or index < 0
        self.layer_thickness.setEnabled(not busy and not halfspace)
        self.region_editor.setEnabled(not busy and not halfspace)
        for action in ('duplicate', 'delete', 'up', 'down'):
            widget = self.findChild(QPushButton, 'layer_' + action)
            valid = not halfspace
            if action == 'delete':
                valid = valid and len(stack) > 3
            if action == 'up':
                valid = valid and index > 1
            if action == 'down':
                valid = valid and index < len(stack)-2
            widget.setEnabled(not busy and valid)
        existing = self._region not in (None, '', 'new')
        for action in ('apply', 'copy', 'delete'):
            self.findChild(QPushButton, 'region_' + action).setEnabled(not busy and not halfspace and existing)

    def draw_preview(self, *args, reset=False):
        try:
            try:
                from addon_runtime import available
                self.export_button.setVisible(available('cad_comsol'))
            except ImportError:
                self.export_button.setVisible(True)
            three_d = self.view_mode.currentIndex() == 1
            self.cut_y.setVisible(not three_d)
            self.cut_label.setVisible(not three_d)
            self.reset_view.setVisible(three_d)
            inputs = (self.store.layers, self.store.patterns, self._selected,
                      self.store.settings.get('ax_um', .77), self.store.settings.get('ay_um', .77),
                      self.cells.currentIndex()*2 + 1)
            if three_d:
                from qt_structure_3d import geometry_figure_3d
                old_axis = getattr(self.plot.figure, '_s4_geometry', {}).get('three_d')
                view = (old_axis.elev, old_axis.azim) if old_axis is not None and not reset else None
                figure = geometry_figure_3d(*inputs, view=view)
            else:
                figure = geometry_figure(*inputs, self.cut_y.value() / self._display_factor())
            apply_geometry_units(figure, self._unit)
            self.plot.draw_figure(figure)
            self.plot.canvas.mpl_connect('button_press_event', self._plot_click)
            self.plot.canvas.mpl_connect('motion_notify_event', self._plot_hover)
            warnings = figure._s4_geometry['warnings']
            self.preview_note.setText(' '.join(warnings) if warnings else (
                'Drag: orbit · middle drag: pan · right drag: zoom · teal: selected layer · ∞: infinite media · sampled surface preview'
                if three_d else 'Hover for layer details · click a section layer to select it · dashed box: unit cell'))
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            self.preview_note.setText('Preview: ' + str(exc))

    def _plot_click(self, event):
        figure = self.plot.figure
        metadata = getattr(figure, '_s4_geometry', {})
        toolbar = getattr(self.plot.canvas, 'toolbar', None)
        if toolbar is not None and getattr(toolbar, 'mode', ''):
            return
        if event.button != 1 or event.inaxes is not metadata.get('section') or event.ydata is None:
            return
        for layer in metadata.get('stack', []):
            if layer['z0'] <= event.ydata < layer['z1']:
                self.select_layer(layer['name'])
                break

    def _plot_hover(self, event):
        metadata = getattr(self.plot.figure, '_s4_geometry', {})
        detail = ''
        if event.inaxes is metadata.get('section') and event.ydata is not None:
            layer = next((item for item in metadata.get('stack', [])
                          if item['z0'] <= event.ydata < item['z1']), None)
            if layer:
                thickness = 'Semi-infinite medium' if layer['halfspace'] else self._length_text(layer['z1']-layer['z0'])
                detail = f"{layer['name']}\n{layer['material']}\n{thickness}"
        elif event.inaxes is not None:
            detail = metadata.get('selected', '')
        if self.plot.canvas.toolTip() != detail:
            self.plot.canvas.setToolTip(detail)
