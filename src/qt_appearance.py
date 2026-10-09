"""Persistent appearance controls with a native preview of the current project."""
from PyQt6.QtCore import Qt, QSignalBlocker, QSize, QRectF, QPointF, QTimer
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QComboBox, QSlider, QCheckBox,
    QLabel, QColorDialog, QLineEdit, QHBoxLayout, QGridLayout, QBoxLayout,
    QAbstractButton, QButtonGroup, QFrame, QSizePolicy)
from PyQt6.QtGui import QColor, QPainter, QPen, QLinearGradient, QPolygonF
from qt_common import (theme_manager, button, LOOKS, CUSTOM_COLOR_ROLES, COLORS,
    BASE_COLORS, GLASS_COLORS, blend_color, ActionStatusLabel)
from qt_surfaces import WorkspacePanel


def _title(text):
    label = QLabel(text)
    label.setObjectName('sectionTitle')
    return label


def _line(layout):
    line = QFrame()
    line.setObjectName('builderSeparator')
    line.setFixedHeight(1)
    layout.addWidget(line)


class ThemeCard(QAbstractButton):
    """An accessible native theme selector, with a vector workspace thumbnail."""
    def __init__(self, look, label, parent=None):
        super().__init__(parent)
        self.look, self.label = look, label
        self.setCheckable(True)
        self.setAccessibleName(label + ' theme')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setFixedHeight(138)

    def sizeHint(self):
        return QSize(132, 138)

    def minimumSizeHint(self):
        return QSize(64, 138)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        manager = theme_manager()
        current = COLORS[manager.mode]
        _, style, mode = LOOKS[self.look]
        colors = (GLASS_COLORS if style == 'glass' else BASE_COLORS)[mode]
        outer = QRectF(2, 2, self.width()-4, 106)
        painter.setBrush(QColor(colors['panel']))
        painter.setPen(QPen(QColor(current['accent'] if self.isChecked() else current['border']), 2 if self.isChecked() else 1))
        painter.drawRoundedRect(outer, 9, 9)
        inside = outer.adjusted(9, 9, -9, -9)
        gradient = QLinearGradient(inside.topLeft(), inside.bottomRight())
        gradient.setColorAt(0, QColor(colors['panel']))
        gradient.setColorAt(1, QColor(colors['bg']))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(colors['border']), .8))
        painter.drawRoundedRect(inside, 5, 5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors['header']))
        painter.drawRoundedRect(QRectF(inside.x()+1, inside.y()+1, inside.width()-2, 16), 4, 4)
        painter.setBrush(QColor(colors['accent']))
        painter.drawRoundedRect(QRectF(inside.x()+7, inside.y()+6, max(8, inside.width()*.17), 4), 1, 1)
        sidebar = QRectF(inside.x()+6, inside.y()+23, inside.width()*.32, inside.height()-29)
        painter.setBrush(QColor(colors['field']))
        painter.setPen(QPen(QColor(colors['border']), .6))
        painter.drawRoundedRect(sidebar, 3, 3)
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(3):
            painter.setBrush(QColor(colors['select'] if index == 0 else colors['header']))
            painter.drawRoundedRect(QRectF(sidebar.x()+4, sidebar.y()+5+index*13, max(4, sidebar.width()-8), 7), 1, 1)
        x, y = inside.x()+inside.width()*.71, inside.y()+inside.height()*.61
        radius = min(21, inside.width()*.2)
        top = QPolygonF([QPointF(x,y-radius), QPointF(x+radius,y-radius*.5), QPointF(x,y), QPointF(x-radius,y-radius*.5)])
        left = QPolygonF([QPointF(x-radius,y-radius*.5), QPointF(x,y), QPointF(x,y+radius), QPointF(x-radius,y+radius*.5)])
        right = QPolygonF([QPointF(x,y), QPointF(x+radius,y-radius*.5), QPointF(x+radius,y+radius*.5), QPointF(x,y+radius)])
        cube = blend_color(colors['accent'], colors['panel'], .45 if style=='glass' else .72)
        for polygon, shade in ((top,QColor(cube).lighter(130)), (left,QColor(cube)), (right,QColor(cube).darker(122))):
            painter.setBrush(shade)
            painter.setPen(QPen(QColor(colors['border']).lighter(118), .7))
            painter.drawPolygon(polygon)
        if style == 'glass':
            sheen = QLinearGradient(inside.topLeft(), inside.bottomRight())
            highlight = QColor('#ffffff'); highlight.setAlpha(65 if mode=='light' else 25)
            sheen.setColorAt(0, highlight); highlight.setAlpha(0); sheen.setColorAt(.65, highlight)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(sheen)
            painter.drawRoundedRect(inside, 5, 5)
        if self.isChecked():
            center = QPointF(outer.right()-15, outer.top()+15)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(current['accent']))
            painter.drawEllipse(center, 10, 10)
            painter.setPen(QPen(QColor(colors['bg']), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPolyline(QPolygonF([center+QPointF(-4,0), center+QPointF(-1,3), center+QPointF(4,-3)]))
        painter.setPen(QColor(current['text']))
        painter.drawText(QRectF(0,113,self.width(),23), Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignVCenter, self.label)
        if self.hasFocus():
            painter.setPen(QPen(QColor(current['accent']), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5), 8, 8)
        painter.end()


class ColorSwatch(QAbstractButton):
    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.color = '#000000'
        self.setFixedSize(30, 30)
        self.setAccessibleName('Choose ' + label.lower() + ' color')
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(self.color))
        painter.setPen(QPen(QColor(COLORS[theme_manager().mode]['border']), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1), 5, 5)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(COLORS[theme_manager().mode]['accent']), 2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1), 5, 5)
        painter.end()


class AppearancePage(QWidget):
    def __init__(self, parent=None, *, store=None):
        super().__init__(parent)
        self.manager, self.store = theme_manager(), store
        self.setMinimumWidth(0)
        self.content_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.content_layout.setContentsMargins(0,0,0,0)
        self.content_layout.setSpacing(10)
        self.editor_panel = WorkspacePanel()
        editor = QVBoxLayout(self.editor_panel)
        editor.setContentsMargins(18,18,18,18)
        editor.setSpacing(12)
        editor.addWidget(_title('Appearance'))
        _line(editor)
        editor.addWidget(QLabel('Look and theme'))
        self.theme = QComboBox(self)
        for key,(label,style,mode) in LOOKS.items():
            self.theme.addItem(label,key)
        self.theme.setAccessibleName('Color theme')
        self.theme.hide()
        self.theme_cards = {}
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.cards_grid = QGridLayout()
        self.cards_grid.setHorizontalSpacing(14)
        self.cards_grid.setVerticalSpacing(8)
        for index,(key,label) in enumerate((('light','B Light'),('dark','B Dark'),('glass_light','Glass Light'),('glass_dark','Glass Dark'))):
            card = ThemeCard(key,label)
            card.clicked.connect(lambda checked=False,k=key:self.manager.apply_look(k))
            self.theme_group.addButton(card)
            self.cards_grid.addWidget(card,0,index)
            self.theme_cards[key] = card
        editor.addLayout(self.cards_grid)
        _line(editor)
        editor.addWidget(QLabel('Color customization'))
        self.colors_grid = QGridLayout()
        self.colors_grid.setHorizontalSpacing(10)
        self.colors_grid.setVerticalSpacing(8)
        self.colors_grid.setColumnStretch(0,2)
        self.colors_grid.setColumnStretch(2,3)
        self.color_fields, self.color_swatches = {}, {}
        for index,(key,label) in enumerate(CUSTOM_COLOR_ROLES.items()):
            label = {'accent':'Accent color','text':'Text color'}.get(key,label)
            caption = QLabel(label)
            field = QLineEdit()
            field.setMaxLength(7)
            field.setMinimumWidth(0)
            field.setAccessibleName(label+' hex color')
            field.editingFinished.connect(lambda k=key:self.apply_color(k))
            swatch = ColorSwatch(label)
            swatch.clicked.connect(lambda checked=False,k=key:self.choose_color(k))
            choose = button('Choose…',lambda checked=False,k=key:self.choose_color(k))
            choose.setAccessibleName('Choose '+label.lower()+' color')
            choose.setMaximumWidth(114)
            self.colors_grid.addWidget(caption,index,0)
            self.colors_grid.addWidget(swatch,index,1)
            self.colors_grid.addWidget(field,index,2)
            self.colors_grid.addWidget(choose,index,3)
            self.color_fields[key], self.color_swatches[key] = field, swatch
        editor.addLayout(self.colors_grid)
        self.color_message = ActionStatusLabel('')
        editor.addWidget(self.color_message)
        reset_row = QHBoxLayout()
        reset_row.addStretch(2)
        self.reset_colors_button = button('↶  Reset colors',self.manager.reset_ui_colors)
        reset_row.addWidget(self.reset_colors_button)
        reset_row.addStretch(3)
        editor.addLayout(reset_row)
        _line(editor)
        editor.addWidget(QLabel('Interface'))
        interface = QGridLayout()
        interface.setHorizontalSpacing(12)
        interface.setVerticalSpacing(14)
        self.scale = QSlider(Qt.Orientation.Horizontal)
        self.scale.setRange(70,140)
        self.scale.setSingleStep(5)
        self.scale.setTracking(False)
        self.scale.setAccessibleName('Interface size percentage')
        self.value = QLabel()
        self.value.setMinimumWidth(42)
        interface.addWidget(QLabel('Interface scale'),0,0)
        interface.addWidget(self.value,0,1)
        interface.addWidget(self.scale,0,2)
        self.adaptive = QCheckBox('Use adaptive layout')
        self.adaptive.setAccessibleName('Adapt layout and control size to the window')
        interface.addWidget(self.adaptive,0,3)
        self.glass_opacity = QSlider(Qt.Orientation.Horizontal)
        self.glass_opacity.setRange(0,100)
        self.glass_opacity.setTracking(False)
        self.glass_opacity.setAccessibleName('Glass surface opacity percentage')
        self.glass_value = QLabel()
        interface.addWidget(QLabel('Glass opacity'),1,0)
        interface.addWidget(self.glass_value,1,1)
        interface.addWidget(self.glass_opacity,1,2,1,2)
        interface.setColumnStretch(2,1)
        editor.addLayout(interface)
        self.interface_grid = interface
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(button('Reset appearance',self.reset))
        editor.addLayout(bottom)
        editor.addStretch(1)
        self.content_layout.addWidget(self.editor_panel, 6)
        self.preview_panel = WorkspacePanel()
        preview = QVBoxLayout(self.preview_panel)
        preview.setContentsMargins(18,18,18,18)
        preview.setSpacing(14)
        preview.addWidget(_title('Live preview'))
        _line(preview)
        self.geometry_panel = WorkspacePanel()
        geometry = QVBoxLayout(self.geometry_panel)
        geometry.setContentsMargins(10,10,10,10)
        geometry.setSpacing(8)
        self.viewbar = QGridLayout()
        self.geometry_title = QLabel('Geometry Viewer')
        self.viewbar.addWidget(self.geometry_title,0,0)
        self.view_buttons = {}
        for index,label in enumerate(('3D Stack','Cross-section','Unit cell')):
            control = button(label,lambda checked=False,m=label:self.set_geometry_view(m))
            control.setCheckable(True)
            control.setProperty('viewTab',True)
            self.viewbar.addWidget(control,0,index+1)
            self.view_buttons[label] = control
        self.viewbar.setColumnStretch(0,1)
        geometry.addLayout(self.viewbar)
        from qt_device_builder import GeometryViewport
        self.viewport = GeometryViewport()
        self.viewport.setMinimumSize(0,340)
        geometry.addWidget(self.viewport,1)
        self.viewport.display_panel = WorkspacePanel(self.viewport)
        display = QVBoxLayout(self.viewport.display_panel)
        display.setContentsMargins(12,10,12,10)
        display.setSpacing(6)
        self.display_controls = {}
        for key,label,value in (('show_holes','Show holes',True),('use_colors','Layer colors',True),('show_edges','Edges',False),('show_axes','Axes',True)):
            control = QCheckBox(label)
            control.setChecked(value)
            control.toggled.connect(lambda checked,k=key:self.set_display_option(k,checked))
            display.addWidget(control)
            self.display_controls[key] = control
        self.viewport.display_panel.adjustSize()
        preview.addWidget(self.geometry_panel,1)
        self.content_layout.addWidget(self.preview_panel,5)
        self.theme.currentIndexChanged.connect(lambda:self.manager.apply_look(self.theme.currentData()))
        self.scale.valueChanged.connect(lambda value:self.manager.set_appearance(scale=value))
        self.adaptive.toggled.connect(lambda value:self.manager.set_appearance(adaptive=value))
        self.glass_opacity.valueChanged.connect(self.manager.set_glass_opacity)
        self.manager.changed.connect(self.refresh)
        if store is not None:
            store.changed.connect(self.refresh_model)
        self.set_geometry_view('3D Stack')
        self.refresh()
        self.refresh_model()

    def minimumSizeHint(self):
        return QSize(0,self.minimumHeight())

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._reflow_layout()

    def _reflow_layout(self):
        stacked = self.width()<1000
        direction = QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight
        if self.content_layout.direction()!=direction:
            self.content_layout.setDirection(direction)
        editor_width = self.width() if stacked else (self.width()-10)*6/11
        preview_width = self.width() if stacked else (self.width()-10)*5/11
        columns = 2 if editor_width<510 else 4
        if getattr(self,'_card_columns',None)!=columns:
            self._card_columns = columns
            for index,card in enumerate(self.theme_cards.values()):
                self.cards_grid.removeWidget(card)
                self.cards_grid.addWidget(card,index//columns,index%columns)
        compact = editor_width<510
        if compact!=getattr(self,'_compact_interface',None):
            self._compact_interface = compact
            self.interface_grid.removeWidget(self.adaptive)
            self.interface_grid.addWidget(self.adaptive,2 if compact else 0,0 if compact else 3,1,3 if compact else 1)
        narrow_preview = preview_width<470
        if narrow_preview!=getattr(self,'_narrow_preview',None):
            self._narrow_preview = narrow_preview
            for control in self.view_buttons.values():self.viewbar.removeWidget(control)
            self.viewbar.removeWidget(self.geometry_title)
            self.viewbar.addWidget(self.geometry_title,0,0,1,3 if narrow_preview else 1)
            for index,control in enumerate(self.view_buttons.values()):
                self.viewbar.addWidget(control,1 if narrow_preview else 0,index if narrow_preview else index+1)
        # Respect the native controls' actual font and layout minimums. An
        # arbitrary stacked height would squeeze the second card row into the
        # first when Windows scaling or adaptive density changes.
        self.editor_panel.layout().invalidate()
        self.editor_panel.setMinimumHeight(max(820 if columns==2 else 680,self.editor_panel.minimumSizeHint().height()))
        self.preview_panel.setMinimumHeight(590 if stacked else 680)
        self.setMinimumHeight((self.editor_panel.minimumHeight()+self.preview_panel.minimumHeight()+10) if stacked else max(self.editor_panel.minimumHeight(),680))

    def refresh_model(self,*_):
        if self.store is not None:
            self.viewport.set_model(self.store,'',3)

    def set_geometry_view(self,mode):
        self.viewport.mode = mode
        for label,control in self.view_buttons.items():control.setChecked(label==mode)
        self.viewport.update()

    def set_display_option(self,key,value):
        setattr(self.viewport,key,bool(value))
        self.viewport.update()

    def refresh(self,*_):
        for widget,value in ((self.theme,self.theme.findData(self.manager.look)),(self.scale,self.manager.scale),(self.adaptive,self.manager.adaptive)):
            with QSignalBlocker(widget):
                if widget is self.theme:widget.setCurrentIndex(value)
                elif widget is self.scale:widget.setValue(value)
                else:widget.setChecked(value)
        self.value.setText(f'{self.manager.scale}%')
        self.glass_value.setText(f'{self.manager.glass_opacity}%')
        for key,card in self.theme_cards.items():
            with QSignalBlocker(card):card.setChecked(key==self.manager.look)
            card.update()
        for key,field in self.color_fields.items():
            with QSignalBlocker(field):field.setText(COLORS[self.manager.mode][key])
            self.color_swatches[key].color = COLORS[self.manager.mode][key]
            self.color_swatches[key].update()
        with QSignalBlocker(self.glass_opacity):self.glass_opacity.setValue(self.manager.glass_opacity)
        self.glass_opacity.setEnabled(self.manager.style=='glass')
        density = self.manager.effective_scale
        self.setStyleSheet(f'QLineEdit {{ min-width:0; }} QPushButton[viewTab="true"] {{ font-size:{max(9,10*density):g}pt; padding:{round(6*density)}px {round(7*density)}px; }}')
        QTimer.singleShot(0,self._reflow_layout)
        self.update()

    def apply_color(self,key):
        try:
            self.manager.set_ui_color(key,self.color_fields[key].text())
            self.color_message.setText('')
        except ValueError as exc:
            self.color_message.setText(str(exc))

    def choose_color(self,key):
        color = QColorDialog.getColor(QColor(COLORS[self.manager.mode][key]),self,'Choose '+CUSTOM_COLOR_ROLES[key].lower())
        if color.isValid():
            self.manager.set_ui_color(key,color.name())
            self.color_message.setText('')

    def reset(self):
        self.manager.set_appearance(scale=100,adaptive=True)
        self.manager.apply_look('dark')
        self.manager.reset_ui_colors()
