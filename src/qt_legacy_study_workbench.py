"""Native study shell over existing controls, geometry and calculated results."""
from PyQt6.QtCore import Qt, QSize, QSignalBlocker
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QScrollArea, QFrame, QSplitter,
    QComboBox, QSizePolicy, QGroupBox, QFormLayout, QLineEdit, QAbstractSpinBox)
from qt_common import COLORS, theme_manager
from qt_reference_style import reference_icon


def scroll_content(widget):
    parent = widget.parentWidget()
    old_scroll = parent.parentWidget() if parent is not None else None
    if isinstance(old_scroll, QScrollArea) and old_scroll.widget() is widget:
        old_scroll.takeWidget()
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(widget)
    widget.setMinimumWidth(0)
    return area


class StudyWorkbench(QWidget):
    """Reuse authoritative widgets; view changes never rewrite physical inputs."""
    def __init__(self, store, title, steps, inputs, results, *, edit_geometry=None,
                 preview_note='Optical layer and pattern geometry. The preview is not a calculated field.',
                 parent=None):
        super().__init__(parent)
        self.store = store
        self.setObjectName('legacyStudyWorkbench')
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)
        self.heading = QLabel(title)
        self.heading.setObjectName('studyTitle')
        root.addWidget(self.heading)
        self.step_targets = []
        self.step_buttons = []
        strip = QHBoxLayout()
        strip.setSpacing(8)
        for index, label in enumerate(steps):
            action = QPushButton(str(index+1)+'  '+label.replace('&', '&&'))
            action.setCheckable(True)
            action.setAccessibleName(label)
            action.clicked.connect(lambda checked=False, i=index: self.select_step(i))
            strip.addWidget(action, 1)
            self.step_buttons.append(action)
        root.addLayout(strip)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        self.objects_panel = QFrame()
        self.objects_panel.setObjectName('studyCard')
        objects = QVBoxLayout(self.objects_panel)
        objects.setContentsMargins(10, 12, 10, 10)
        objects.addWidget(QLabel('Structure'))
        self.objects = QTreeWidget()
        self.objects.setHeaderHidden(True)
        self.objects.setRootIsDecorated(True)
        self.objects.setIndentation(14)
        self.objects.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.objects.setAccessibleName(title+' structure objects')
        self.objects.currentItemChanged.connect(self._select_object)
        objects.addWidget(self.objects, 1)
        self.edit_geometry = QPushButton('Edit structure')
        self.edit_geometry.setAccessibleName(title+' edit structure and materials')
        if edit_geometry is not None:
            self.edit_geometry.clicked.connect(edit_geometry)
        else:
            self.edit_geometry.setEnabled(False)
        objects.addWidget(self.edit_geometry)
        self.splitter.addWidget(self.objects_panel)

        self.views = QTabWidget()
        self.views.setDocumentMode(True)
        self.views.setUsesScrollButtons(True)
        model = QWidget()
        model_layout = QVBoxLayout(model)
        model_layout.setContentsMargins(12, 12, 12, 12)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('Structure preview'), 1)
        self.projection = QComboBox()
        self.projection.addItems(['3D stack', 'Top view', 'Cross section'])
        self.projection.setAccessibleName(title+' preview orientation')
        toolbar.addWidget(self.projection)
        model_layout.addLayout(toolbar)
        from qt_device_builder import GeometryViewport
        self.preview = GeometryViewport()
        self.preview.setMinimumSize(120, 180)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.preview.layer_selected.connect(self._preview_selected)
        self.projection.currentIndexChanged.connect(self._projection_changed)
        model_layout.addWidget(self.preview, 1)
        self.preview_note = QLabel(preview_note)
        self.preview_note.setWordWrap(True)
        self.preview_note.setObjectName('studyHint')
        model_layout.addWidget(self.preview_note)
        self.views.addTab(model, 'Structure')
        self.views.addTab(results, 'Results')
        results.setMinimumWidth(0)
        self.splitter.addWidget(self.views)

        self.properties = QFrame()
        self.properties.setObjectName('studyCard')
        properties = QVBoxLayout(self.properties)
        properties.setContentsMargins(0, 0, 0, 0)
        self.input_tabs = QTabWidget()
        self.input_tabs.setDocumentMode(True)
        self.input_tabs.setUsesScrollButtons(True)
        self.input_scroll = scroll_content(inputs)
        self.input_tabs.addTab(self.input_scroll, 'Parameters')
        properties.addWidget(self.input_tabs)
        self.splitter.addWidget(self.properties)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([180, 620, 350])
        for pane in (self.objects_panel, self.views, self.properties):
            pane.setMinimumWidth(0)
            pane.setMinimumHeight(0)
            pane.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        for heading in inputs.findChildren(QLabel):
            if heading.text() in ('Simulation Setup', 'Field Maps'):
                heading.hide()
        for group in inputs.findChildren(QGroupBox):
            group.setMinimumWidth(0)
            group.setTitle(group.title().replace('&&','&').replace('&','&&'))
        self._prepare_inputs(inputs)
        if hasattr(store, 'changed'):
            store.changed.connect(self.refresh_geometry)
        theme_manager().changed.connect(self.apply_theme)
        self.refresh_geometry()
        self.select_step(0)
        self.apply_theme()

    def set_step_targets(self, targets):
        self.step_targets = list(targets)

    def select_step(self, index):
        for i, button in enumerate(self.step_buttons):
            button.setChecked(i == index)
        self.input_tabs.setCurrentIndex(0)
        if index < len(self.step_targets):
            target = self.step_targets[index]
            if callable(target):
                target()
            elif target is not None:
                self.input_scroll.ensureWidgetVisible(target, 8, 12)
                target.setFocus(Qt.FocusReason.OtherFocusReason)
        if index == 0:
            self.views.setCurrentIndex(0)

    def add_parameter_tab(self, widget, title):
        self._prepare_inputs(widget)
        index=self.input_tabs.addTab(scroll_content(widget), title.replace('&','&&'))
        self.input_tabs.setTabIcon(index,reference_icon('settings',COLORS[theme_manager().mode]['muted']))
        return index

    def _prepare_inputs(self, widget):
        for field in widget.findChildren(QWidget):
            if not isinstance(field,(QComboBox,QLineEdit,QAbstractSpinBox)):
                continue
            field.setMinimumWidth(0)
            field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            if isinstance(field,QComboBox):
                field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                field.setMinimumContentsLength(8)
                field.setToolTip(field.toolTip() or field.currentText())
        for label in widget.findChildren(QLabel):
            label.setWordWrap(True)
        for form in widget.findChildren(QFormLayout):
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        available=max(300,self.splitter.width()-8)
        left=170 if self.width()>=1050 else 140
        right=350 if self.width()>=1050 else 300
        self.splitter.setSizes([left,max(150,available-left-right),right])
        self.edit_geometry.setText('Edit structure' if left>=170 else 'Edit')

    def add_result_tab(self, widget, title):
        widget.setMinimumWidth(0)
        return self.views.addTab(widget, title)

    def show_results(self):
        self.views.setCurrentIndex(1)

    def _projection_changed(self, index):
        self.preview.mode = ('3D Stack', 'Unit cell', 'Cross-section')[index]
        self.preview.update()

    def refresh_geometry(self, *_):
        if not all(hasattr(self.store, key) for key in ('layers', 'patterns', 'settings')):
            self.preview_note.setText('Open a device to preview its optical layers and patterns.')
            return
        previous = self.objects.currentItem()
        selected = previous.data(0, Qt.ItemDataRole.UserRole) if previous else ''
        try:
            self.preview.set_model(self.store, selected or '', 3)
        except (ValueError, KeyError, TypeError):
            self.preview_note.setText('Finish the structure inputs to update the preview.')
            return
        with QSignalBlocker(self.objects):
            self.objects.clear()
            for layer in self.preview.layers:
                name = str(layer['Name'])
                row = QTreeWidgetItem(self.objects, [name])
                row.setData(0, Qt.ItemDataRole.UserRole, name)
                row.setToolTip(0, str(layer['Material'])+' · '+str(layer['Thickness_um'])+' µm')
                row.setIcon(0, reference_icon('layers', COLORS[theme_manager().mode]['muted']))
                for shape in self.preview.patterns:
                    if shape['layer'] == name:
                        child = QTreeWidgetItem(row, [shape['shape'].replace('_', ' ').title()])
                        child.setData(0, Qt.ItemDataRole.UserRole, name)
                        child.setIcon(0, reference_icon('cube', COLORS[theme_manager().mode]['muted']))
                if name == selected:
                    self.objects.setCurrentItem(row)
            self.objects.expandAll()

    def _select_object(self, item, _previous=None):
        if item is not None:
            self.preview.selected = item.data(0, Qt.ItemDataRole.UserRole) or ''
            self.preview.update()
            self.views.setCurrentIndex(0)

    def _preview_selected(self, name):
        for index in range(self.objects.topLevelItemCount()):
            item = self.objects.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == name:
                self.objects.setCurrentItem(item)
                break

    def apply_theme(self, *_):
        c = COLORS[theme_manager().mode]
        self.setStyleSheet(f'''
        QWidget#legacyStudyWorkbench {{background:{c['bg']}; color:{c['text']};}}
        QLabel#studyTitle {{font-size:23px; font-weight:650; padding:2px 0 8px;}}
        QLabel#studyHint {{color:{c['muted']}; font-size:11px;}}
        QFrame#studyCard {{background:{c['panel']}; border:1px solid {c['border']}; border-radius:7px;}}
        QTreeWidget {{background:transparent; border:0; font-size:12px;}}
        QTreeWidget::item {{padding:7px 2px;}}
        QTreeWidget::item:selected {{background:{c['select']}; color:{c['text']}; border-radius:4px;}}
        QGroupBox {{background:{c['panel']}; border:1px solid {c['border']}; border-radius:6px; margin-top:10px; padding:12px 9px 9px; font-weight:600;}}
        QGroupBox::title {{subcontrol-origin:margin; left:9px; padding:0 4px;}}
        QTabWidget::pane {{border:1px solid {c['border']}; border-radius:6px; background:{c['panel']};}}
        QTabBar::tab {{padding:8px 9px;}}
        QPushButton:checked {{color:{c['accent']}; background:{c['select']}; border:1px solid {c['accent']};}}
        ''')
        for index, button in enumerate(self.step_buttons):
            button.setIcon(reference_icon(('cube', 'settings', 'check')[min(index, 2)], c['accent']))
            button.setIconSize(QSize(17, 17))
        self.edit_geometry.setIcon(reference_icon('structure', c['accent']))
        self.input_tabs.setTabIcon(0,reference_icon('settings',c['muted']))
        for index, icon in enumerate(('cube', 'results')):
            self.views.setTabIcon(index, reference_icon(icon, c['muted']))

