"""Native material library, optical-constant import, and dispersion inspection."""
from pathlib import Path
import csv
import io
import textwrap
import numpy as np

import pandas as pd
from PyQt6.QtCore import Qt, QSize, QRectF, QTimer, QSignalBlocker, QEvent, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap, QPainter, QPen, QFont
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QLineEdit, QPushButton, QLabel, QCheckBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
    QTabWidget, QTabBar, QPlainTextEdit, QSizePolicy, QMessageBox, QSplitter, QButtonGroup,
    QStyledItemDelegate, QStyle, QColorDialog, QScrollArea,
)

from model import MAT_COLS
from material_import_ui import import_csvs, save_manual, merge_material
from material_viewer import material_data
from qt_common import PlotWidget, CompactDoubleSpinBox, ActionStatusLabel, COLORS, theme_manager
from qt_surfaces import WorkspacePanel
from refractiveindex_online import search_catalog, download_dataset, catalog_details, inspect_dataset


def choices(combo, values, selected=None):
    """Refresh semantic choices without firing selection callbacks mid-refresh."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(20)
    if selected is None:
        selected = combo.currentData()
    blocked = combo.blockSignals(True)
    combo.clear()
    for label, value in values:
        combo.addItem(str(label), value)
    index = combo.findData(selected)
    combo.setCurrentIndex(index if index >= 0 else (0 if values else -1))
    combo.blockSignals(blocked)


def make_table(headers=(), editable=False):
    view = QTableWidget(0, len(headers))
    view.setHorizontalHeaderLabels(list(headers))
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.verticalHeader().setVisible(False)
    # Keep columns readable; wide scientific result sets scroll horizontally.
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    view.horizontalHeader().setMinimumSectionSize(100)
    view.horizontalHeader().setStretchLastSection(True)
    view.verticalHeader().setDefaultSectionSize(34)
    view.setWordWrap(False)
    view.setMinimumHeight(160)
    if not editable:
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    return view


def show_frame(view, data):
    frame = pd.DataFrame(data)
    view.setColumnCount(len(frame.columns))
    view.setHorizontalHeaderLabels([str(v) for v in frame.columns])
    view.setRowCount(len(frame))
    for r, row in enumerate(frame.itertuples(index=False, name=None)):
        for c, value in enumerate(row):
            text = '' if pd.isna(value) else (f'{value:.8g}' if isinstance(value, float) else str(value))
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            view.setItem(r, c, item)
    view.resizeColumnsToContents()
    for column in range(view.columnCount()):
        view.setColumnWidth(column, min(320, max(120, view.columnWidth(column))))


def readable_form(parent=None):
    form = QFormLayout(parent)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(12)
    return form


def spin(value, minimum=0, maximum=1e9, decimals=6):
    widget = CompactDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    return widget


def group(title):
    widget = QGroupBox(title)
    layout = QVBoxLayout(widget)
    layout.setSpacing(12)
    return widget, layout


def material_display_color(name, appearance):
    custom=appearance.get('material_colors',{}).get(name)
    if custom:return custom
    key=str(name).casefold()
    for prefix,color in (('algaas','#8b80ff'),('gaas','#ff6884'),('sic','#50d689'),
                         ('air','#dce6ed'),('sio2','#ffda55'),('au','#ffda55')):
        if key.startswith(prefix):return color
    palette=['#ff6884','#8b80ff','#50d689','#dce6ed','#ffda55','#69c8ed']
    return palette[sum(map(ord,str(name))) % len(palette)]


class MaterialCardDelegate(QStyledItemDelegate):
    """Native material cards retain the table's real selection and source data."""
    def sizeHint(self, option, index):
        return QSize(180, 62)

    def paint(self, painter, option, index):
        details = index.data(Qt.ItemDataRole.UserRole) or {}
        if index.column() != 0 or not details:
            return super().paint(painter, option, index)
        colors = COLORS[theme_manager().mode]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(option.rect).adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setBrush(QColor(colors['select']) if selected else Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(colors['accent']), 1) if selected else Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bounds, 7, 7)
        swatch = QRectF(bounds.left() + 12, bounds.center().y() - 16, 32, 32)
        painter.setBrush(QColor(details['color']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(swatch, 4, 4)
        text_bounds = QRectF(swatch.right() + 12, bounds.top() + 9,
                             max(1, bounds.right() - swatch.right() - 24), 21)
        font = QFont(option.font)
        painter.setFont(font)
        painter.setPen(QColor(colors['text']))
        painter.drawText(text_bounds, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(details['name'], Qt.TextElideMode.ElideRight, int(text_bounds.width())))
        font.setPointSizeF(max(8., font.pointSizeF() - 1.))
        painter.setFont(font)
        painter.setPen(QColor(colors['muted']))
        text_bounds.translate(0, 21)
        painter.drawText(text_bounds, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(details['subtitle'], Qt.TextElideMode.ElideRight, int(text_bounds.width())))
        if not selected:
            painter.setPen(QPen(QColor(colors['border']), .7))
            painter.drawLine(bounds.bottomLeft(), bounds.bottomRight())
        painter.restore()


class MaterialNotesEditor(QPlainTextEdit):
    editingFinished = pyqtSignal()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()


class MaterialSourceView(QPlainTextEdit):
    def setText(self, text):
        self.setPlainText(str(text))

    def text(self):
        return self.toPlainText()


class MaterialInspectorTabBar(QTabBar):
    def tabSizeHint(self,index):
        hint=super().tabSizeHint(index)
        hint.setWidth(self.fontMetrics().horizontalAdvance(self.tabText(index))+8)
        return hint


class MaterialChartTitle(QLabel):
    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        text=self.fontMetrics().elidedText(self.text(),Qt.TextElideMode.ElideRight,self.contentsRect().width())
        painter.drawText(self.contentsRect(),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,text)


class MaterialsPage(QWidget):
    """Edits the same material collection used by all calculation pages."""
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.setObjectName('materialsWorkspace')
        self.store = store
        self._presets = {}
        self._notes_material = None
        self._notes_selection = None
        self._notes_pending = None
        self._plot_ranges={}
        self._range_material_key=None
        self._inspector_loading = False
        self.panel_layout_timer=QTimer(self)
        self.panel_layout_timer.setSingleShot(True)
        self.panel_layout_timer.timeout.connect(self.layout_panels)
        self.notes_timer = QTimer(self)
        self.notes_timer.setSingleShot(True)
        self.notes_timer.setInterval(500)
        self.notes_timer.timeout.connect(self.save_material_notes)
        if QApplication.instance() is not None:
            QApplication.instance().aboutToQuit.connect(self.save_material_notes)
        root = QVBoxLayout(self)
        title = QLabel('Materials')
        title.setObjectName('pageTitle')
        title.hide()
        lead = QLabel('Saved materials appear immediately in every layer and region material selector.')
        lead.setWordWrap(True)
        lead.setObjectName('muted')
        lead.hide()
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        inspect = QWidget()
        inspect_layout = QVBoxLayout(inspect)
        self.inspect_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.inspect_splitter.setChildrenCollapsible(False)
        inspect_layout.addWidget(self.inspect_splitter)
        details_panel = WorkspacePanel()
        body = QVBoxLayout(details_panel)
        library_title=QLabel('Material Library');library_title.setObjectName('sectionTitle');body.addWidget(library_title)
        self.inspect_splitter.addWidget(details_panel)
        chart_panel = WorkspacePanel()
        chart_layout = QVBoxLayout(chart_panel)
        constants_title=MaterialChartTitle('Optical Constants');constants_title.setObjectName('sectionTitle');chart_layout.addWidget(constants_title)
        self.inspect_splitter.addWidget(chart_panel)
        self.inspect_splitter.setStretchFactor(0, 0)
        self.inspect_splitter.setStretchFactor(1, 1)
        self.inspect_splitter.setSizes([330, 760])
        self.selection = QComboBox()
        self.selection.setMinimumWidth(220)
        self.selection.setAccessibleName('Material to inspect')
        body.addWidget(self.selection)
        self.selection.hide()
        self.material_query = QLineEdit()
        self.material_query.setPlaceholderText('Search project materials and saved presets…')
        self.material_query.setClearButtonEnabled(True)
        body.addWidget(self.material_query)
        self.material_list = make_table(['Material', 'Source'])
        self.material_list.setItemDelegate(MaterialCardDelegate(self.material_list))
        self.material_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        body.addWidget(self.material_list, 1)
        self.material_query.textChanged.connect(self.filter_materials)
        self.material_list.cellClicked.connect(self.select_material_row)
        top = QVBoxLayout()
        self.material_actions = top
        self.add_preset = QPushButton('Add to structure materials')
        self.remove = QPushButton('Remove from project')
        top.addWidget(self.add_preset)
        top.addWidget(self.remove)
        body.addLayout(top)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        chart_layout.addWidget(self.description)
        self.range_box = QWidget()
        form = readable_form(self.range_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.low, self.high = spin(800, .001), spin(2000, .001)
        limits = QHBoxLayout()
        limits.addWidget(self.low, 1)
        connector = QLabel('to')
        connector.setFixedWidth(24)
        connector.setAlignment(Qt.AlignmentFlag.AlignCenter)
        limits.addWidget(connector)
        limits.addWidget(self.high, 1)
        form.addRow('Plot range (nm)', limits)
        chart_layout.addWidget(self.range_box)
        self.plot = PlotWidget()
        self.plot.setMinimumHeight(280)
        chart_layout.addWidget(self.plot, 1)
        self.values = make_table(['wavelength_nm', 'n', 'k'])
        self.values.setMaximumHeight(210)
        chart_layout.addWidget(self.values)
        properties_panel=WorkspacePanel()
        properties_layout=QVBoxLayout(properties_panel)
        self.inspect_splitter.addWidget(properties_panel)
        properties_title=QLabel('Material properties');properties_title.setObjectName('sectionTitle')
        properties_layout.addWidget(properties_title)
        self.property_details=QLabel();self.property_details.setWordWrap(True)
        properties_layout.addWidget(self.property_details)
        self.assignment_layer=QComboBox()
        assignment_form=readable_form()
        assignment_form.addRow('Assign to layer',self.assignment_layer)
        properties_layout.addLayout(assignment_form)
        self.assign_material=QPushButton('Apply material to layer');self.assign_material.setProperty('primary',True)
        self.assign_material.clicked.connect(self.apply_to_layer)
        properties_layout.addWidget(self.assign_material)
        properties_layout.addStretch()
        save_box, save_layout = group('Save material preset')
        save_form = readable_form()
        self.preset_name = QLineEdit()
        self.preset_name.setPlaceholderText('Optional display name')
        self.preset_notes = QLineEdit()
        self.preset_notes.setPlaceholderText('Dataset source, temperature, sample conditions…')
        save_form.addRow('Preset name', self.preset_name)
        save_form.addRow('Source & notes', self.preset_notes)
        save_layout.addLayout(save_form)
        self.save_preset = QPushButton('Save selected material to library')
        self.save_preset.setProperty('primary', True)
        save_layout.addWidget(self.save_preset)
        properties_layout.addWidget(save_box)
        self.inspect_splitter.setSizes([300,700,320])
        self.tabs.addTab(inspect, 'Inspect & manage')
        self._build_online()
        self._build_import()
        self._build_manual()
        self._reference_layout(root,inspect,properties_panel,properties_layout,body,chart_layout,constants_title)
        # Optical inspector tabs remain available through ``tabs``. The outer
        # workspace switch gives the electrical catalog the whole page width.
        self.optical_workspace=inspect
        root.removeWidget(inspect)
        self.workspace_tabs=QTabWidget();self.workspace_tabs.setObjectName('materialWorkspaces')
        self.workspace_tabs.addTab(inspect,'Optical materials')
        from qt_electrical_material_catalog import ElectricalMaterialCatalog
        self.electrical_catalog=ElectricalMaterialCatalog(store)
        self.electrical_tab_index=self.workspace_tabs.addTab(self.electrical_catalog,'Electrical materials')
        self.workspace_tabs.setMinimumWidth(0)
        root.insertWidget(0,self.workspace_tabs,1)
        self.status = ActionStatusLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.selection.currentIndexChanged.connect(self.draw)
        self.low.valueChanged.connect(self.draw)
        self.high.valueChanged.connect(self.draw)
        self.add_preset.clicked.connect(self.use_preset)
        self.remove.clicked.connect(self.remove_material)
        self.save_preset.clicked.connect(self.save_selected)
        store.changed.connect(self.refresh)
        store.library_changed.connect(self.refresh)
        store.busy_changed.connect(self._busy)
        self.refresh()

    def _reference_layout(self,root,inspect,properties_panel,properties_layout,body,chart_layout,constants_title):
        """Reference composition: library / chart+data / tabbed inspector."""
        old_tabs=self.tabs
        inspector_tabs=QTabWidget();inspector_tabs.setObjectName('materialInspectorTabs')
        inspector_tabs.setTabBar(MaterialInspectorTabBar(inspector_tabs))
        inspector_tabs.addTab(properties_panel,'Inspect')
        while old_tabs.count()>1:
            widget=old_tabs.widget(1);text=old_tabs.tabText(1)
            old_tabs.removeTab(1);inspector_tabs.addTab(widget,text)
        old_tabs.removeTab(0);root.removeWidget(old_tabs);old_tabs.hide()
        inspector_surface=WorkspacePanel();inspector_root=QVBoxLayout(inspector_surface)
        title=QLabel('Material Inspector');title.setObjectName('sectionTitle');inspector_root.addWidget(title)
        inspector_root.addWidget(inspector_tabs,1)
        self.inspect_splitter.addWidget(inspector_surface)
        root.insertWidget(0,inspect,1);inspect.show();self.tabs=inspector_tabs
        root.setContentsMargins(0,0,0,0)
        inspect.layout().setContentsMargins(0,0,0,0)
        self.inspect_splitter.setHandleWidth(10)
        inspector_tabs.setUsesScrollButtons(True)
        inspector_tabs.tabBar().setExpanding(False)
        inspector_tabs.setMinimumWidth(0)
        inspector_surface.setMinimumWidth(320)
        properties_panel.setMinimumWidth(0)
        self.material_scope=QComboBox()
        for label,key in [('Project','project'),('Library','saved'),('All materials','all')]:self.material_scope.addItem(label,key)
        body.insertWidget(2,self.material_scope)
        self.material_scope.hide()
        self.scope_buttons=QButtonGroup(self)
        scope_row=QHBoxLayout();scope_row.setSpacing(0)
        for index,label in enumerate(('Project','Library','All')):
            button=QPushButton(label);button.setCheckable(True)
            self.scope_buttons.addButton(button,index);scope_row.addWidget(button)
        self.scope_buttons.button(0).setChecked(True)
        self.scope_buttons.idClicked.connect(self.material_scope.setCurrentIndex)
        self.material_scope.currentIndexChanged.connect(lambda index:self.scope_buttons.button(index).setChecked(True))
        body.insertLayout(4,scope_row)
        self.material_scope.currentIndexChanged.connect(self.filter_materials)
        self.material_list.horizontalHeader().hide()
        self.material_list.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.material_list.verticalHeader().setMinimumSectionSize(62)
        self.material_list.verticalHeader().setDefaultSectionSize(62)
        self.material_list.setAlternatingRowColors(False)
        self.material_list.setShowGrid(False)
        self.material_list.setIconSize(QSize(28,28))
        self.add_preset.setText('+  Add to project')
        self.remove.setText('Remove')
        self.material_actions.removeWidget(self.remove)
        shortcut_row = QHBoxLayout()
        shortcut_row.addWidget(self.remove)
        self.import_shortcut = QPushButton('Import CSV')
        self.import_shortcut.setToolTip('Open the optical-constant CSV importer')
        self.import_shortcut.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        shortcut_row.addWidget(self.import_shortcut)
        self.material_actions.addLayout(shortcut_row)
        self.property_details.hide()
        for label in properties_panel.findChildren(QLabel):
            if label.text()=='Material properties':label.hide()
        inspector_form=readable_form()
        self.material_name=QLineEdit();self.material_name.setReadOnly(True)
        self.material_model=QLineEdit();self.material_model.setReadOnly(True)
        self.material_dataset=QLineEdit();self.material_dataset.setReadOnly(True)
        self.material_coverage=QLabel();self.material_coverage.setWordWrap(True)
        self.material_source=MaterialSourceView();self.material_source.setReadOnly(True)
        self.material_source.setFixedHeight(76)
        self.material_source.setAccessibleName('Authentic material source and dataset conditions')
        inspector_form.addRow('Material name',self.material_name)
        inspector_form.addRow('Dataset name',self.material_dataset)
        inspector_form.addRow('Dataset model',self.material_model)
        inspector_form.addRow('Source',self.material_source)
        self.range_box.layout().itemAt(0).widget().hide()
        chart_layout.removeWidget(self.range_box)
        inspector_form.addRow('Wavelength range (nm)',self.range_box)
        inspector_form.addRow('Dataset coverage',self.material_coverage)
        self.interpolation=QComboBox()
        self.interpolation.addItem('Linear','linear')
        self.interpolation.addItem('Linear (in log k)','log_k')
        self.interpolation.setAccessibleName('Optical-constant interpolation')
        self.interpolation.setToolTip('n is linear. Logarithmic k requires every saved k sample to be positive; endpoints stay clamped.')
        self.interpolation.currentIndexChanged.connect(self.set_material_interpolation)
        inspector_form.addRow('Interpolation',self.interpolation)
        color_row=QWidget();color_layout=QHBoxLayout(color_row);color_layout.setContentsMargins(0,0,0,0)
        self.material_color=QPushButton();self.material_color.setAccessibleName('Choose material preview display color')
        self.material_color.setToolTip('Preview color for this material; explicit layer colors take priority. Optical n and k stay unchanged.')
        self.material_color.clicked.connect(self.choose_material_color)
        color_layout.addWidget(self.material_color,1)
        self.color_reset=QPushButton('Reset');self.color_reset.clicked.connect(self.reset_material_color)
        color_layout.addWidget(self.color_reset)
        inspector_form.addRow('Display color',color_row)
        self.material_notes=MaterialNotesEditor()
        self.material_notes.setPlaceholderText('Notes for this material')
        self.material_notes.setAccessibleName('Material notes saved with this project')
        self.material_notes.setFixedHeight(92)
        self.material_notes.textChanged.connect(self.queue_material_notes)
        self.material_notes.editingFinished.connect(self.save_material_notes)
        inspector_form.addRow('Notes',self.material_notes)
        self.preset_notes.hide()
        self.preset_notes.parentWidget().layout().itemAt(0).layout().labelForField(self.preset_notes).hide()
        self.preset_notes.textChanged.connect(self.legacy_notes_changed)
        inspector_form.setVerticalSpacing(7)
        properties_layout.setSpacing(6)
        properties_layout.setContentsMargins(4,4,4,4)
        properties_layout.insertLayout(0,inspector_form)
        self.save_preset.setText('Save to library')
        self.description.hide()
        self.plot_mode=QComboBox();self.plot_mode.addItems(['n & k','n only','k only'])
        self.plot_mode.currentIndexChanged.connect(self.draw)
        self.plot_mode.hide()
        self.plot_mode_buttons=QButtonGroup(self)
        plot_modes=QHBoxLayout();plot_modes.setSpacing(0)
        chart_layout.removeWidget(constants_title)
        constants_title.setMinimumWidth(0);constants_title.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        plot_modes.addWidget(constants_title,1)
        plot_modes.addSpacing(8)
        self.plot_legend=QLabel('<span style="color:#ff5978">━━</span> n&nbsp;&nbsp; <span style="color:#438deb">━━</span> k&nbsp;&nbsp;')
        self.plot_legend.setAccessibleName('n is red; k is blue')
        plot_modes.addWidget(self.plot_legend)
        for index,label in enumerate(('n && k','n only','k only')):
            button=QPushButton(label);button.setCheckable(True)
            self.plot_mode_buttons.addButton(button,index);plot_modes.addWidget(button)
        self.plot_mode_buttons.button(0).setChecked(True)
        self.plot_mode_buttons.idClicked.connect(self.plot_mode.setCurrentIndex)
        self.plot_mode.currentIndexChanged.connect(lambda index:self.plot_mode_buttons.button(index).setChecked(True))
        chart_layout.insertLayout(0,plot_modes)
        self.constants_title=constants_title
        self.plot.setToolTip('Curves use the selected interpolation; dots show the original saved wavelength samples.')
        data_panel=WorkspacePanel();data_layout=QVBoxLayout(data_panel)
        data_title=QLabel('Wavelength–n–k Data');data_title.setObjectName('sectionTitle');data_layout.addWidget(data_title)
        chart_layout.removeWidget(self.values);self.values.setMaximumHeight(300);data_layout.addWidget(self.values,1)
        self.export_material=QPushButton('Export CSV…');self.export_material.clicked.connect(self.export_constants)
        data_layout.addWidget(self.export_material,0,Qt.AlignmentFlag.AlignRight);chart_layout.addWidget(data_panel,2)
        chart_layout.setStretch(chart_layout.indexOf(self.plot),3)
        inspector_tabs.tabBar().setObjectName('materialInspectorTabBar')
        inspector_tabs.tabBar().setStyleSheet('QTabBar#materialInspectorTabBar::tab {font-size:9pt; padding:7px 4px; margin:0; min-width:0px;}')
        inspector_tabs.tabBar().setExpanding(True)
        self.inspect_splitter.widget(0).setMinimumWidth(250)
        inspector_surface.setMinimumWidth(360)
        self.inspect_splitter.setStretchFactor(0,1)
        self.inspect_splitter.setStretchFactor(1,1)
        self.inspect_splitter.setStretchFactor(2,1)
        self.inspect_splitter.setSizes([345,750,405])
        for label in self.findChildren(QLabel):
            if label.wordWrap() and label is not self.material_coverage:
                label.setToolTip(label.text());label.hide()

    def export_constants(self):
        from qt_result_export import export_frame
        try:
            row,notes=self.selected_row()
            data,_,_=material_data(self.store.library,(row,notes),self.store.materials,self.store.files,self.low.value(),self.high.value())
            export_frame(self,data,self.status,'optical-constants.csv')
        except Exception as exc:self.status.setText(str(exc))

    def open_electrical_material(self,material_id=None):
        self.workspace_tabs.setCurrentIndex(self.electrical_tab_index)
        if material_id:self.electrical_catalog.select_material(material_id)

    def open_optical_materials(self,inspector_index=0):
        self.workspace_tabs.setCurrentIndex(0)
        self.tabs.setCurrentIndex(inspector_index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self,'panel_layout_timer'):self.panel_layout_timer.start(0)

    def showEvent(self,event):
        super().showEvent(event)
        viewport=self.scroll_viewport()
        if viewport is not None:viewport.installEventFilter(self)
        self.panel_layout_timer.start(0)

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.Resize:self.panel_layout_timer.start(0)
        return super().eventFilter(watched,event)

    def scroll_viewport(self):
        parent=self.parentWidget()
        while parent is not None:
            if isinstance(parent,QScrollArea):return parent.viewport()
            parent=parent.parentWidget()
        return None

    def layout_panels(self):
        viewport=self.scroll_viewport()
        available=viewport.width() if viewport is not None else self.width()
        orientation = Qt.Orientation.Vertical if available < 1000 else Qt.Orientation.Horizontal
        if self.inspect_splitter.orientation() != orientation:
            self.inspect_splitter.setOrientation(orientation)
            if orientation == Qt.Orientation.Vertical:
                self.inspect_splitter.setSizes([340, 650, 540])
        if orientation == Qt.Orientation.Horizontal:
            width = max(1, self.inspect_splitter.width() - 2 * self.inspect_splitter.handleWidth())
            self.inspect_splitter.setSizes([round(width * factor) for factor in (.23, .50, .27)])
        if hasattr(self, 'online_splitter'):
            self.online_splitter.setOrientation(orientation)

    def closeEvent(self,event):
        self.save_material_notes()
        super().closeEvent(event)

    def _build_online(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        search_box, search_body = group('Search refractiveindex.info')
        row = QHBoxLayout()
        self.online_query = QLineEdit()
        self.online_query.setPlaceholderText('Material, formula, author or dataset — e.g. Silicon Green')
        self.online_search = QPushButton('Search')
        self.online_search.setToolTip('Search the refractiveindex.info catalog')
        self.online_search.setProperty('primary', True)
        row.addWidget(self.online_query, 1)
        row.addWidget(self.online_search)
        search_body.addLayout(row)
        notice = QLabel('Search reads the public catalog only. No material files are downloaded.')
        notice.setWordWrap(True)
        search_body.addWidget(notice)
        self.online_search.setToolTip(notice.text());notice.hide()
        layout.addWidget(search_box)
        results_box, results_body = group('Results')
        self.online_results = make_table(['Material', 'Dataset / author', 'Wavelength range', 'Collection'])
        self.online_results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        results_body.addWidget(self.online_results)
        detail_box, detail_body = group('Selected dataset')
        self.online_details = QPlainTextEdit()
        self.online_details.setToolTip('Reference, sample conditions and optical model for the selected dataset.')
        self.online_details.setReadOnly(True)
        self.online_details.setMinimumHeight(220)
        detail_body.addWidget(self.online_details, 1)
        self.online_preview = QPushButton('Load dataset details')
        self.online_preview.setToolTip('Read the selected dataset’s reference, sample conditions and optical model without adding a material.')
        detail_body.addWidget(self.online_preview)
        self.online_preview.clicked.connect(self.preview_online)
        actions = QVBoxLayout()
        self.online_open = QPushButton('Open source page')
        self.online_download = QPushButton('Download & review…')
        self.online_download.setProperty('primary', True)
        actions.addWidget(self.online_open)
        actions.addWidget(self.online_download)
        detail_body.addLayout(actions)
        reminder = QLabel('Loading details reads one public dataset. Only Download & review… adds its optical constants to your library.')
        reminder.setWordWrap(True)
        detail_body.addWidget(reminder)
        self.online_preview.setToolTip(reminder.text());reminder.hide()
        self.online_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.online_splitter.setChildrenCollapsible(False)
        self.online_splitter.addWidget(results_box)
        self.online_splitter.addWidget(detail_box)
        self.online_splitter.setSizes([650, 760])
        layout.addWidget(self.online_splitter, 1)
        self._online_items = []
        self.online_search.clicked.connect(self.search_online)
        self.online_query.returnPressed.connect(self.search_online)
        self.online_results.itemSelectionChanged.connect(self.online_selection_changed)
        self.online_open.clicked.connect(self.open_online_source)
        self.online_download.clicked.connect(self.confirm_online_download)
        self.store.task_finished.connect(self._online_task_finished)
        self.store.task_failed.connect(self._online_task_failed)
        self.tabs.addTab(page, 'Find online')

    def _build_import(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        box, body = group('Import wavelength-dependent n and k')
        description = QLabel('Choose CSV or TXT files containing wavelength,n,k columns, or the separate n / k sections exported by refractiveindex.info. Each file is saved permanently and added to the material dropdowns.')
        description.setWordWrap(True)
        body.addWidget(description)
        box.setToolTip(description.text());description.hide()
        form = readable_form()
        self.import_unit = QComboBox()
        self.import_unit.addItems(['nm', 'um'])
        self.import_name = QLineEdit()
        self.import_name.setPlaceholderText('Leave empty to use each filename')
        self.import_source = QLineEdit('https://refractiveindex.info/')
        self.missing_k = QCheckBox('Use k = 0 for missing values')
        self.missing_k.setToolTip('Explicitly use k = 0 when the file has no k data')
        form.addRow('Wavelength unit in files', self.import_unit)
        form.addRow('Material name (one file only)', self.import_name)
        form.addRow('Dataset page / reference', self.import_source)
        body.addLayout(form)
        body.addWidget(self.missing_k)
        self.import_button = QPushButton('Choose files & import materials')
        self.import_button.setProperty('primary', True)
        self.import_button.clicked.connect(self.choose_csvs)
        body.addWidget(self.import_button)
        layout.addWidget(box)
        layout.addStretch()
        self.tabs.addTab(page, 'Import CSV')

    def _build_manual(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        box, body = group('Add material values')
        form = readable_form()
        self.manual_name = QLineEdit()
        self.manual_mode = QComboBox()
        self.manual_mode.addItems(['Wavelength-dependent n,k', 'Constant n,k (explicit approximation)'])
        self.manual_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.manual_mode.setMinimumContentsLength(20)
        self.manual_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.manual_unit = QComboBox()
        self.manual_unit.addItems(['nm', 'um'])
        self.manual_source = QLineEdit('https://refractiveindex.info/')
        form.addRow('Material name', self.manual_name)
        form.addRow('Wavelength dependence', self.manual_mode)
        form.addRow('Wavelength unit', self.manual_unit)
        form.addRow('Dataset page / conditions', self.manual_source)
        body.addLayout(form)
        self.manual_rows = make_table(['Wavelength', 'n', 'k'], editable=True)
        self.manual_rows.setRowCount(3)
        self.manual_rows.setMinimumHeight(200)
        body.addWidget(self.manual_rows)
        self.row_actions = QWidget()
        actions = QHBoxLayout(self.row_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        add = QPushButton('Add row');add.setToolTip('Add a wavelength, n, k sample row')
        add.clicked.connect(lambda: self.manual_rows.insertRow(self.manual_rows.rowCount()))
        paste = QPushButton('Paste rows');paste.setToolTip('Paste wavelength, n, k rows')
        paste.clicked.connect(self.paste_rows)
        actions.addWidget(add)
        actions.addWidget(paste)
        actions.addStretch()
        body.addWidget(self.row_actions)
        self.constants = QWidget()
        values = readable_form(self.constants)
        self.n, self.k = spin(1.5, -1e6), spin(0, -1e6)
        values.addRow('Constant n (real)', self.n)
        values.addRow('Constant k (imag)', self.k)
        body.addWidget(self.constants)
        self.manual_save = QPushButton('Save material to project & library')
        self.manual_save.setProperty('primary', True)
        self.manual_save.clicked.connect(self.save_values)
        body.addWidget(self.manual_save)
        layout.addWidget(box)
        layout.addStretch()
        self.manual_mode.currentIndexChanged.connect(self._mode)
        self._mode()
        self.tabs.addTab(page, 'Enter values')

    def _mode(self, *_):
        dependent = self.manual_mode.currentIndex() == 0
        self.manual_rows.setVisible(dependent)
        self.manual_unit.setEnabled(dependent)
        self.row_actions.setVisible(dependent)
        self.constants.setVisible(not dependent)

    def _busy(self, busy):
        for widget in (self.import_button, self.manual_save, self.add_preset, self.remove, self.save_preset,
                       self.online_search, self.online_download):
            widget.setEnabled(not busy)
        row,_=self.selected_row()
        self.interpolation.setEnabled(not busy and bool(row) and row.get('Model')=='table_nk')
        if not busy:
            self._selection_actions()

    def search_online(self):
        query = self.online_query.text().strip()
        self.status.setText('Searching the public catalog only…')
        try:
            self.store.run_task('online-material-search', lambda: search_catalog(query))
        except Exception as exc:
            self.status.setText('Online search needs attention: ' + str(exc))

    def _online_task_failed(self, name, error):
        if name in ('online-material-search', 'online-material-download', 'online-material-preview'):
            self.status.setText(('Online search needs attention: ' if name.endswith('search') else 'Download needs attention: ') + error)

    def _online_task_finished(self, name, value):
        if name == 'online-material-search':
            self._online_items = list(value)
            self.online_results.setRowCount(len(self._online_items))
            for r, result in enumerate(self._online_items):
                for c, text in enumerate((result['material'], result['dataset'], result['wavelength_range'], result.get('shelf_name', result['shelf']))):
                    cell = QTableWidgetItem(str(text))
                    cell.setToolTip(str(text))
                    self.online_results.setItem(r, c, cell)
            self.online_results.resizeColumnsToContents()
            for c in range(4):
                self.online_results.setColumnWidth(c, min(330, max(120, self.online_results.columnWidth(c))))
            self.status.setText(f'Found {len(value)} matching datasets. No material files were downloaded.')
            if value:
                self.online_results.selectRow(0)
            else:
                self.online_details.setPlainText('No matching datasets. Try a material name, chemical formula or author.')
        elif name == 'online-material-preview':
            if self._selected_online() == value['result']:
                self.online_details.setPlainText(value['details'])
            self.status.setText('Dataset details loaded. No material was added to the library.')
        elif name == 'online-material-download':
            self._import_online(value)

    def _selected_online(self):
        row = self.online_results.currentRow()
        return self._online_items[row] if 0 <= row < len(self._online_items) else None

    def online_selection_changed(self):
        item = self._selected_online()
        if item:
            self.online_details.setPlainText(catalog_details(item))

    def preview_online(self):
        item = self._selected_online()
        if not item:
            self.status.setText('Select a dataset first.')
            return
        try:
            self.store.run_task('online-material-preview', lambda: inspect_dataset(item))
            self.status.setText('Reading publication, sample conditions and optical model…')
        except Exception as exc:
            self.status.setText(str(exc))

    def open_online_source(self):
        item = self._selected_online()
        if item:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(item['page_url']))

    def confirm_online_download(self):
        item = self._selected_online()
        if not item:
            self.status.setText('Select a dataset first.')
            return
        box = QMessageBox(self)
        box.setWindowTitle('Download material dataset?')
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"{item['material']}\n{item['dataset']}")
        box.setInformativeText('This explicit action downloads this one YAML dataset, validates it, and adds it to your project library. Searching did not download it.')
        download = box.addButton('Download and add to library', QMessageBox.ButtonRole.AcceptRole)
        box.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not download:
            return
        missing = QMessageBox.question(self, 'Missing extinction data',
            'If this dataset contains n but no k, explicitly treat missing k as 0 (lossless)?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        self.status.setText('Downloading the selected dataset…')
        try:
            self.store.run_task('online-material-download', lambda: download_dataset(item, missing))
        except Exception as exc:
            self.status.setText('Download needs attention: ' + str(exc))

    def _import_online(self, package):
        item, rows = package['result'], package['rows']
        name = f"{item['material_id']} — {item['page']}"
        conditions = ', '.join(f'{key}: {value}' for key, value in package['conditions'].items())
        notes = (f"Source: {item['page_url']}\nDataset: {item['dataset']}\nReference: {package['reference']}"
                 + (f"\nComments: {package['comments']}" if package['comments'] else '')
                 + (f"\nConditions: {conditions}" if conditions else '')
                 + '\nRefractiveindex.info database: CC0 1.0. Download initiated and confirmed by the user.')
        try:
            from material_import_ui import store_table
            row, _ = store_table(self.store.library, name, rows, notes)
            self._apply(merge_material(self.store.materials, row), name,
                        f'Downloaded, validated {len(rows):,} n,k samples, and added {name} to the project library.')
        except Exception as exc:
            self.status.setText('Downloaded data could not be imported: ' + str(exc))

    def refresh(self, *_):
        self._presets = self.store.library.presets()
        values = [('Project · ' + str(row['Name']), 'project:' + str(row['Name'])) for row in self.store.materials.to_dict('records') if row.get('Name')]
        values += [('Built-in · ' + name, 'builtin:' + name) for name in self.store.context.PRESETS]
        values += [('Saved · ' + name, 'saved:' + name) for name in self._presets]
        choices(self.selection, values)
        self.filter_materials()
        self.draw()

    def filter_materials(self, *_):
        query = self.material_query.text().strip().casefold()
        self._visible_materials = [i for i in range(self.selection.count())
            if query in self.selection.itemText(i).casefold() and
            (not hasattr(self,'material_scope') or self.material_scope.currentData()=='all' or
             str(self.selection.itemData(i)).startswith(self.material_scope.currentData()+':') or
             (self.material_scope.currentData()=='saved' and str(self.selection.itemData(i)).startswith('builtin:')))]
        rows = []
        for index in self._visible_materials:
            source, _, name = self.selection.itemText(index).partition(' · ')
            rows.append({'Material': name, 'Source': source})
        show_frame(self.material_list, pd.DataFrame(rows, columns=['Material', 'Source']))
        palette=['#ff6884','#8b80ff','#50d689','#dce6ed','#ffda55','#69c8ed']
        for row,index in enumerate(self._visible_materials):
            name=rows[row]['Material']
            kind = str(self.selection.itemData(index)).partition(':')[0]
            material_name = self._presets[name]['project']['materials'][0]['Name'] if kind == 'saved' else name
            color=material_display_color(material_name,self.store.appearance)
            swatch=QPixmap(28,28);swatch.fill(QColor(color))
            item=self.material_list.item(row,0)
            item.setIcon(QIcon(swatch))
            if kind == 'project':
                material = next((entry for entry in self.store.materials.to_dict('records') if entry['Name'] == name), {})
            elif kind == 'saved':
                material = self._presets.get(name, {}).get('project', {}).get('materials', [{}])[0]
            else:
                material = dict(zip(MAT_COLS, self.store.context.PRESETS.get(name, ())))
            if material.get('Model') == 'table_nk':
                subtitle = str(material.get('Name',name)).partition(' — ')[2] or 'Wavelength-dependent n,k'
            elif material.get('Model') == 'constant_nk':
                subtitle = f"n = {float(material.get('A', 1)):g} · k = {float(material.get('B', 0)):g}"
            else:
                subtitle = 'Constant permittivity' if material.get('Model') == 'constant_eps' else rows[row]['Source']
            item.setData(Qt.ItemDataRole.UserRole, dict(name=str(material.get('Name',name)), subtitle=subtitle, color=color))
            item.setToolTip(name+' · '+rows[row]['Source'])
        self.material_list.setColumnHidden(1,True)
        self.material_list.verticalHeader().setMinimumSectionSize(62)
        self.material_list.verticalHeader().setDefaultSectionSize(62)
        self.material_list.horizontalHeader().setStretchLastSection(False)
        self.material_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.material_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        if self.selection.currentIndex() in self._visible_materials:
            self.material_list.selectRow(self._visible_materials.index(self.selection.currentIndex()))

    def select_material_row(self, row, column=0):
        if 0 <= row < len(self._visible_materials):
            self.selection.setCurrentIndex(self._visible_materials[row])

    def selected_row(self):
        key = self.selection.currentData() or ''
        kind, _, name = key.partition(':')
        if kind == 'project':
            row = next((row for row in self.project_material_rows() if row['Name'] == name), None)
            entry=self.material_metadata(row) if row is not None else {}
            return row, entry.get('source_notes',entry.get('notes',''))
        if kind == 'builtin' and name in self.store.context.PRESETS:
            return dict(zip(MAT_COLS, self.store.context.PRESETS[name])), 'Built-in constant approximation; no measured dispersion table is attached.'
        if kind == 'saved' and name in self._presets:
            entry = self._presets[name]
            return entry['project']['materials'][0], entry.get('source_notes',entry.get('notes',''))
        return None, ''

    def project_material_rows(self):
        frame=self.store.materials.astype(object)
        return frame.where(pd.notna(frame),None).to_dict('records')

    def material_metadata(self,row):
        lookup=getattr(self.store.library,'material_metadata',None)
        if lookup is not None:return lookup(row)
        matches=[entry for entry in self._presets.values() if entry['project']['materials'][0]==row]
        return max(matches,key=lambda entry:('source_notes' in entry,entry.get('created',''),entry.get('id',''))) if matches else {}

    def material_user_notes(self,row,source):
        if row['Name'] in self.store.appearance.get('material_notes',{}):
            return self.store.appearance['material_notes'][row['Name']]
        key=str(self.selection.currentData() or '')
        if key.startswith('saved:'):
            entry=self._presets.get(key.partition(':')[2],{})
        else:
            entry=self.material_metadata(row)
        return entry.get('notes','') if 'source_notes' in entry else source

    def _in_use(self, name):
        return bool((self.store.layers['Material'] == name).any() or (self.store.patterns['Material'] == name).any())

    def _selection_actions(self):
        choices(self.assignment_layer,[(r['Name'],r['Name']) for r in self.store.layers.to_dict('records')])
        row, _ = self.selected_row()
        project = str(self.selection.currentData()).startswith('project:')
        busy = self.store.busy
        self.add_preset.setEnabled(bool(row) and not project and not busy)
        self.save_preset.setEnabled(bool(row) and project and not busy)
        used = bool(row) and self._in_use(row['Name'])
        self.remove.setEnabled(bool(row) and project and not used and not busy)
        self.remove.setToolTip('This material is used by a layer or region.' if used else 'Remove from this project; saved presets are retained.')
        self.assign_material.setEnabled(bool(row) and bool(self.assignment_layer.count()) and not busy)

    def apply_to_layer(self):
        """Resolve library presets before assigning; preserve all other geometry."""
        if self.store.busy:return
        try:
            from structure_builder import resolve_material
            key=self.selection.currentData()
            selected,source=self.selected_row();policy=self.interpolation_policy(selected)
            if not self.save_material_notes():return
            notes=self.material_user_notes(selected,source)
            layer=self.assignment_layer.currentData()
            if not key or not layer:raise ValueError('Choose a material and a layer.')
            if key.startswith('project:'):key='current:'+key.partition(':')[2]
            materials,name=resolve_material(self.store.context,self.store.materials,key)
            self.preserve_renamed_source(selected,name,source,notes,policy)
            materials=pd.DataFrame(materials,columns=MAT_COLS)
            layers=self.store.layers.copy()
            layers.loc[layers.Name==layer,'Material']=name
            self.store.set_structure(materials,layers,self.store.patterns,reason='materials')
            self.copy_material_metadata(selected['Name'],name)
            if policy!='linear':
                policies=dict(self.store.settings.get('material_interpolations',{}));policies[name]=policy
                self.store.update_settings({'material_interpolations':policies})
            self.status.setText(f'Assigned {name} to {layer}.')
        except Exception as exc:self.status.setText('Could not assign material: '+str(exc))

    def draw(self, *_):
        self._selection_actions()
        row, notes = self.selected_row()
        if self._notes_pending is not None and (row is None or self._notes_pending[0] != row['Name']):
            if not self.save_material_notes():
                previous=self.selection.findData(self._notes_selection)
                if previous>=0:
                    with QSignalBlocker(self.selection):self.selection.setCurrentIndex(previous)
                    self.filter_materials();self._selection_actions()
                return
        self.range_box.setVisible(bool(row))
        try:
            if row is not None:
                key=tuple(row.get(column) for column in MAT_COLS)
                if key!=self._range_material_key:
                    self._range_material_key=key
                    if row.get('Model')=='table_nk':
                        table,_,_=material_data(self.store.library,(row,notes),self.store.materials,self.store.files,self.low.value(),self.high.value())
                        limits=self._plot_ranges.get(key,(table.wavelength_nm.min(),table.wavelength_nm.max()))
                    else:limits=self._plot_ranges.get(key,(800.,2000.))
                    with QSignalBlocker(self.low),QSignalBlocker(self.high):
                        self.low.setValue(limits[0]);self.high.setValue(limits[1])
                if self.low.value()>=self.high.value():
                    self.status.setText('Plot range needs a start wavelength below the stop wavelength.')
                    return
                self._plot_ranges[key]=(self.low.value(),self.high.value())
            data, description, notes = material_data(self.store.library, (row, notes) if row else None, self.store.materials, self.store.files, self.low.value(), self.high.value())
            figure = self.plot.figure
            figure.clear()
            main=figure.add_subplot(111);secondary=main.twinx()
            mode=self.plot_mode.currentText() if hasattr(self,'plot_mode') else 'n & k'
            columns = [('n','#ff5978','Refractive index, n'),('k','#438deb','Extinction coefficient, k')]
            if mode=='n only':columns=columns[:1]
            elif mode=='k only':columns=columns[1:]
            self.plot_legend.setText('&nbsp;&nbsp; '.join(f'<span style="color:{color}">━━</span> {column}' for column,color,_ in columns))
            self.plot_legend.setAccessibleName('; '.join(f'{column} is {"red" if column=="n" else "blue"}' for column,_,_ in columns))
            secondary.set_visible(len(columns)==2)
            for axis, (column,color,label) in zip((main,secondary),columns):
                if row.get('Model') == 'table_nk':
                    axis.plot(data.wavelength_nm, data[column], color=color, linestyle='None', marker='.',label=column)
                    from model import sample_nk
                    measured=data.wavelength_nm.to_numpy()
                    points=np.unique(np.concatenate([measured,(measured[:-1]+measured[1:])/2,np.linspace(
                        data.wavelength_nm.min(),data.wavelength_nm.max(),min(12001,max(501,len(data)*4+1)))]))
                    policy=self.interpolation_policy(row)
                    material=dict(model='table_nk',table=data.to_numpy().tolist(),grid=data.wavelength_nm.to_numpy().tolist(),interpolation=policy)
                    sampled=sample_nk(material,points)[0 if column=='n' else 1]
                    axis.plot(points,sampled,color=color,linewidth=2,label='_evaluated_'+column)
                else:
                    axis.plot(data.wavelength_nm, data[column], color=color, linewidth=2,label=column)
                axis.set_ylabel(label)
                axis.grid(alpha=.2)
                axis.ticklabel_format(axis='y', useOffset=False)
                if column=='k' and (data.k>0).all():axis.set_yscale('log')
            main.set_xlabel('Wavelength (nm)')
            main.set_xlim(self.low.value(),self.high.value())
            figure.set_layout_engine('constrained')
            self.plot.draw_figure(figure)
            show_frame(self.values, data.head(5000))
            self.values.setHorizontalHeaderLabels(['Wavelength (nm)','n (real)','k (imag)'])
            self.values.horizontalHeader().setStretchLastSection(False)
            self.values.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self.description.setText(description + ('\n' + notes if notes else ''))
            if hasattr(self,'material_name'):
                self.constants_title.setText('Optical Constants: '+str(row['Name']))
                self.material_name.setText(str(row['Name']))
                self.material_name.setCursorPosition(0)
                self.material_model.setText({'table_nk':'Wavelength-dependent n,k','constant_nk':'Constant n,k','constant_eps':'Constant permittivity'}.get(row.get('Model'),str(row.get('Model',''))))
                self.material_model.setCursorPosition(0)
                self.material_model.setToolTip(str(row.get('Model','')))
                dataset = next((line.partition(':')[2].strip() for line in notes.splitlines() if line.startswith('Dataset:')), '')
                original=next((line.partition(':')[2].partition(';')[0].strip() for line in notes.splitlines() if line.startswith('Original CSV:')), '')
                self.material_dataset.setText(dataset or original or (str(row['Name']) if row.get('Model')=='table_nk' else 'Explicit constant approximation'))
                self.material_dataset.setCursorPosition(0)
                self.material_dataset.setToolTip(self.material_dataset.text()+'\n'+str(row.get('DataFile','')))
                self.constants_title.setToolTip(self.constants_title.text())
                self.material_source.setText(notes or 'Project data · source not recorded')
                self.material_coverage.setText(f'{data.wavelength_nm.min():g}–{data.wavelength_nm.max():g} nm · {len(data):,} samples')
                self.sync_material_inspector(row,notes,data)
            assigned=[r['Name'] for r in self.store.layers.to_dict('records') if r['Material']==row['Name']]
            self.property_details.setText(f"{row['Name']}\nModel: {row.get('Model','')}\nSamples: {len(data):,}\nWavelength: {data.wavelength_nm.min():g}–{data.wavelength_nm.max():g} nm\nn: {data.n.min():g}–{data.n.max():g}\nk: {data.k.min():g}–{data.k.max():g}\nUsed by: {', '.join(assigned) or 'No layers'}\n\n{notes or 'No source notes recorded.'}")
        except Exception as exc:
            self.plot.clear()
            show_frame(self.values, pd.DataFrame(columns=['wavelength_nm', 'n', 'k']))
            self.description.setText(str(exc))
            self.property_details.setText(str(exc))

    def _apply(self, frame, name, message):
        self.store.set_structure(frame, self.store.layers, self.store.patterns, reason='materials')
        self.store.notify_library()
        index = self.selection.findData('project:' + name)
        self.selection.setCurrentIndex(index)
        self.status.setText(message)

    def choose_csvs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Import optical constants', '', 'Optical constants (*.csv *.txt);;All files (*)')
        if paths:
            self.import_paths(paths)

    def import_paths(self, paths):
        if self.store.busy:
            return
        try:
            result, key, message = import_csvs(self.store.library, self.store.materials, paths, self.import_unit.currentText(), self.missing_k.isChecked(), self.import_source.text(), self.import_name.text())
            name = self.store.library.presets()[key]['project']['materials'][0]['Name']
            self._apply(result, name, message)
        except Exception as exc:
            self.status.setText('Import needs attention: ' + str(exc))

    def paste_rows(self):
        try:
            text = QApplication.clipboard().text().strip()
            delimiter = '\t' if '\t' in text else ','
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
            if rows and rows[0][0].strip().lower() in ('wavelength', 'wavelength_nm', 'wl'):
                rows = rows[1:]
            if not rows or any(len(row) != 3 for row in rows):
                raise ValueError('Paste three columns: wavelength, n, k (tab or comma separated).')
            values = [[float(value) for value in row] for row in rows]
            show_frame(self.manual_rows, pd.DataFrame(values, columns=['Wavelength', 'n', 'k']))
            self.status.setText(f'Pasted {len(values)} rows. Save the material when its source and units are correct.')
        except Exception as exc:
            self.status.setText(str(exc))

    def save_values(self):
        if self.store.busy:
            return
        try:
            rows = []
            for r in range(self.manual_rows.rowCount()):
                row = [self.manual_rows.item(r, c).text().strip() if self.manual_rows.item(r, c) else '' for c in range(3)]
                if any(row):
                    rows.append([value or None for value in row])
            result, _, message = save_manual(self.store.library, self.store.materials, self.manual_name.text(), self.manual_mode.currentText(), self.manual_unit.currentText(), rows, self.n.value(), self.k.value(), self.manual_source.text())
            self._apply(result, self.manual_name.text().strip(), message)
        except Exception as exc:
            self.status.setText('Material needs attention: ' + str(exc))

    def use_preset(self):
        if self.store.busy:
            return
        try:
            row, source = self.selected_row()
            if row is None:
                raise ValueError('Select a built-in or saved material first.')
            if not self.save_material_notes():return
            notes=self.material_user_notes(row,source)
            row = dict(row)
            source_name=row['Name'];policy=self.interpolation_policy(row)
            existing = self.project_material_rows()
            same = next((entry for entry in existing if entry['Name'] == row['Name']), None)
            if same is not None and any(str(same.get(k) or '') != str(row.get(k) or '') for k in MAT_COLS):
                names = {entry['Name'] for entry in existing}
                base, index = row['Name'], 2
                while row['Name'] in names:
                    row['Name'] = f'{base} {index}'
                    index += 1
            self.preserve_renamed_source(dict(row,Name=source_name),row['Name'],source,notes,policy)
            self._apply(merge_material(self.store.materials, row), row['Name'], f"Added {row['Name']} to project materials.")
            self.copy_material_metadata(source_name,row['Name'])
            if policy!='linear':
                policies=dict(self.store.settings.get('material_interpolations',{}));policies[row['Name']]=policy
                self.store.update_settings({'material_interpolations':policies})
        except Exception as exc:
            self.status.setText(str(exc))

    def remove_material(self):
        if self.store.busy:
            return
        row, _ = self.selected_row()
        if row is None or not str(self.selection.currentData()).startswith('project:'):
            return
        if self._in_use(row['Name']):
            self.status.setText('Change the layers or regions that use this material before removing it.')
            return
        frame = self.store.materials[self.store.materials['Name'] != row['Name']].reset_index(drop=True)
        self.store.set_structure(frame, self.store.layers, self.store.patterns, reason='materials')
        self.status.setText(f"Removed {row['Name']} from the project. Saved presets remain available.")

    def save_selected(self):
        if self.store.busy:
            return
        try:
            row, source = self.selected_row()
            if row is None:
                raise ValueError('Select a project material first.')
            if not self.save_material_notes():return
            notes=self.store.appearance.get('material_notes',{}).get(row['Name'],self.material_notes.toPlainText())
            self.store.library.save_preset(row, self.preset_name.text(), notes, self.store.files,
                interpolation=self.interpolation_policy(row),source_notes=source)
            self.store.notify_library()
            self.status.setText('Saved a permanent preset version with its optical-constant data.')
        except Exception as exc:
            self.status.setText('Unable to save preset: ' + str(exc))

    def sync_material_inspector(self,row,notes,data):
        self._inspector_loading=True
        try:
            name=row['Name'];self._notes_material=name;self._notes_selection=self.selection.currentData()
            pending=self._notes_pending
            if pending is None or pending[0] != name:
                with QSignalBlocker(self.material_notes):
                    self.material_notes.setPlainText(self.material_user_notes(row,notes))
            self.preset_notes.setText(self.material_notes.toPlainText())
            color=material_display_color(name,self.store.appearance)
            swatch=QPixmap(24,24);swatch.fill(QColor(color))
            self.material_color.setIcon(QIcon(swatch));self.material_color.setText(color)
            self.color_reset.setEnabled(name in self.store.appearance.get('material_colors',{}))
            table=row.get('Model')=='table_nk'
            self.interpolation.setEnabled(table and not self.store.busy)
            self.interpolation.model().item(1).setEnabled(table and bool((data.k>0).all()))
            with QSignalBlocker(self.interpolation):
                mode=self.interpolation_policy(row)
                self.interpolation.setCurrentIndex(self.interpolation.findData(mode))
        finally:self._inspector_loading=False

    def queue_material_notes(self):
        if not self._inspector_loading and self._notes_material is not None:
            self._notes_pending=(self._notes_material,self.material_notes.toPlainText())
            self.notes_timer.start()

    def legacy_notes_changed(self,text):
        if not self._inspector_loading and self.material_notes.toPlainText()!=text:
            self.material_notes.setPlainText(text)

    def interpolation_policy(self,row):
        name=row['Name']
        policies=self.store.settings.get('material_interpolations',{})
        if name in policies:return policies[name]
        key=str(self.selection.currentData() or '')
        if key.startswith('saved:'):
            return self._presets.get(key.partition(':')[2],{}).get('project',{}).get('settings',{}).get('material_interpolations',{}).get(name,'linear')
        return 'linear'

    def copy_material_metadata(self,source,target):
        if source==target:return
        updates={}
        for key in ('material_colors','material_notes'):
            values=dict(self.store.appearance.get(key,{}))
            if source in values:values[target]=values[source];updates[key]=values
        if updates:self.store.update_appearance(updates)

    def preserve_renamed_source(self,row,target,source,notes,policy):
        """Bind the original dataset citation to an unchanged, renamed optical row."""
        if row['Name']==target or not source:return
        renamed=dict(row,Name=target)
        entry=self.material_metadata(renamed)
        if entry.get('source_notes')==source and entry.get('notes')==notes:return
        self.store.library.save_preset(renamed,target,notes,self.store.files,
            interpolation=policy,source_notes=source)

    def save_material_notes(self):
        self.notes_timer.stop()
        if self._notes_pending is None:return True
        name,text=self._notes_pending
        self._notes_pending=None
        try:
            notes=dict(self.store.appearance.get('material_notes',{}));notes[name]=text
            self.store.update_appearance({'material_notes':notes})
            if self._notes_material==name:
                with QSignalBlocker(self.preset_notes):self.preset_notes.setText(text)
            return True
        except Exception as exc:
            self._notes_pending=(name,text)
            self.status.setText('Could not save material notes: '+str(exc))
            return False

    def set_material_color(self,color):
        row,_=self.selected_row()
        if row is None:return
        value=QColor(color)
        if not value.isValid():raise ValueError('Choose a valid material display color.')
        colors=dict(self.store.appearance.get('material_colors',{}));colors[row['Name']]=value.name()
        self.store.update_appearance({'material_colors':colors})

    def choose_material_color(self):
        color=QColorDialog.getColor(QColor(self.material_color.text()),self,'Material preview color')
        if color.isValid():
            try:self.set_material_color(color)
            except Exception as exc:self.status.setText('Could not save material color: '+str(exc))

    def reset_material_color(self):
        row,_=self.selected_row()
        if row is None:return
        colors=dict(self.store.appearance.get('material_colors',{}));colors.pop(row['Name'],None)
        try:self.store.update_appearance({'material_colors':colors})
        except Exception as exc:self.status.setText('Could not reset material color: '+str(exc))

    def set_material_interpolation(self):
        if self._inspector_loading:return
        if self.store.busy:
            self.draw()
            return
        row,_=self.selected_row()
        if row is None or row.get('Model')!='table_nk':return
        try:
            data,_,_=material_data(self.store.library,(row,''),self.store.materials,self.store.files,self.low.value(),self.high.value())
            mode=self.interpolation.currentData()
            if mode=='log_k' and not bool((data.k>0).all()):
                raise ValueError('Logarithmic k interpolation requires every saved k sample to be positive.')
            existing=next((entry for entry in self.project_material_rows() if entry['Name']==row['Name']),None)
            if not str(self.selection.currentData()).startswith('project:') and existing is not None and existing!=row:
                raise ValueError('Add this dataset to the project before changing interpolation; this name already uses a different optical model.')
            policies=dict(self.store.settings.get('material_interpolations',{}))
            policies[row['Name']]=mode
            self.store.update_settings({'material_interpolations':policies})
        except Exception as exc:
            self.status.setText('Interpolation needs attention: '+str(exc))
            self.draw()
