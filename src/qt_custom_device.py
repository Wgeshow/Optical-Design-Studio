"""Editable finite-device canvas sharing one canonical optical/electrical model."""
from __future__ import annotations

import copy
import json
import math
from functools import lru_cache
from pathlib import Path
import uuid

from PyQt6.QtCore import Qt, QPointF, QRect, QRectF, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QKeySequence, QShortcut, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient, QTransform
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHeaderView, QLayout,
    QAbstractSpinBox, QDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QMenu, QScrollArea, QSizePolicy, QSplitter, QTabWidget, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget, QWidgetAction)

from qt_common import COLORS, integer, number, theme_manager
from qt_compute import _button, _combo, _group, _label, _scroll, _set_value
from qt_ranges import _choices
from qt_surfaces import WorkspacePanel
from qt_device_lighting import mix_color, sheen_brush, studio_brush


def _model_api():
    import device_model
    return device_model


def _color(material_id):
    return {'gaas': '#ec839d', 'ito': '#45b8ed', 'algaas': '#9691df',
            'silicon': '#929ca9', 'air': '#263545'}.get(material_id, '#64b7ac')


def _layer_color(layer):
    if layer.get('material_id') == 'silicon':
        donors = layer.get('donor_cm3', 0)
        acceptors = layer.get('acceptor_cm3', 0)
        if acceptors > donors:
            return '#d3a1af'
        if donors > acceptors:
            return '#74afd7'
    if layer.get('material_id') == 'gaas' and layer.get('donor_cm3', 0) > layer.get('acceptor_cm3', 0):
        return '#69a9dd'
    return _color(layer.get('material_id'))


def _contact_color(contact):
    name=(contact.get('optical_material_name','')+' '+contact.get('name','')).casefold()
    return '#f2c263' if 'au' in name or 'gold' in name or not contact.get('name','').casefold().startswith('n') else '#2bafff'


@lru_cache(maxsize=128)
def _device_icon(kind, color='#cfdeeb'):
    """Small native vector icons, including actual material color swatches."""
    pixmap = QPixmap(72, 72)
    pixmap.setDevicePixelRatio(3)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.4, Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    def line(x1,y1,x2,y2):
        painter.drawLine(QPointF(x1,y1),QPointF(x2,y2))
    if kind == 'select':
        painter.drawPolygon(QPolygonF([QPointF(5,3),QPointF(18,13),QPointF(12,14),QPointF(10,21)]))
    elif kind == 'move':
        line(12,2,12,22);line(2,12,22,12)
        for points in [[(8,6),(12,2),(16,6)],[(8,18),(12,22),(16,18)],[(6,8),(2,12),(6,16)],[(18,8),(22,12),(18,16)]]:
            painter.drawPolyline(QPolygonF([QPointF(*point) for point in points]))
    elif kind in ('rectangle','square_ring'):
        painter.drawRoundedRect(QRectF(4,4,16,16),.7,.7)
        if kind=='square_ring':painter.drawRect(QRectF(8,8,8,8))
    elif kind in ('circle','ellipse'):
        painter.drawEllipse(QRectF(4,6 if kind=='ellipse' else 4,16,12 if kind=='ellipse' else 16))
    elif kind == 'polygon':
        painter.drawPolygon(QPolygonF([QPointF(3,9),QPointF(11,3),QPointF(21,8),QPointF(17,21),QPointF(5,18)]))
    elif kind=='layer':
        for offset in (0,5,10):
            painter.drawPolygon(QPolygonF([QPointF(3,6+offset),QPointF(12,2+offset),QPointF(21,6+offset),QPointF(12,10+offset)]))
    elif kind in ('extrude','device'):
        from qt_icons import navigation_icon
        painter.end()
        return navigation_icon('Structure',color)
    elif kind == 'boolean':
        painter.drawRoundedRect(QRectF(3,3,12,12),2,2)
        painter.drawRoundedRect(QRectF(9,9,12,12),2,2)
    elif kind == 'contact':
        painter.drawEllipse(QRectF(9,2,6,6));line(12,8,12,16);line(5,16,19,16)
        painter.drawEllipse(QRectF(3,16,4,4));painter.drawEllipse(QRectF(17,16,4,4))
    elif kind == 'import':
        painter.drawRect(QRectF(4,4,16,16));line(12,2,12,14);line(8,10,12,14);line(16,10,12,14)
    elif kind in ('mesh','doping'):
        for x in (4,10,16):
            for y in (4,10,16):
                painter.drawRect(QRectF(x,y,4,4)) if kind=='mesh' else painter.drawEllipse(QPointF(x+2,y+2),1.5,1.5)
    elif kind=='eye':
        painter.drawEllipse(QRectF(2,7,20,10));painter.drawEllipse(QPointF(12,12),3,3)
    elif kind in ('zoom','zoom_out','fit'):
        if kind in ('zoom','zoom_out'):
            painter.drawEllipse(QRectF(3,3,12,12));line(14,14,21,21);line(6,9,12,9)
            if kind=='zoom':line(9,6,9,12)
        else:
            for x,y,sx,sy in [(3,3,1,1),(21,3,-1,1),(3,21,1,-1),(21,21,-1,-1)]:
                line(x,y,x+sx*6,y);line(x,y,x,y+sy*6)
    elif kind == 'more':
        for x in (5,12,19):painter.drawEllipse(QPointF(x,12),1,1)
    elif kind=='search':
        painter.drawEllipse(QRectF(3,3,13,13));line(15,15,21,21)
    elif kind=='orbit':
        painter.drawEllipse(QRectF(5,5,14,14));line(12,1,12,8);line(12,16,12,23);line(1,12,8,12);line(16,12,23,12)
    elif kind=='plus':
        line(12,3,12,21);line(3,12,21,12)
    elif kind=='cube':
        painter.setPen(QPen(QColor(color).lighter(130),.7))
        for points,shade in [([(3,7),(12,2),(21,7),(12,12)],125), ([(3,7),(12,12),(12,22),(3,17)],95), ([(12,12),(21,7),(21,17),(12,22)],75)]:
            painter.setBrush(QColor(color).lighter(shade))
            painter.drawPolygon(QPolygonF([QPointF(*point) for point in points]))
    painter.end()
    return QIcon(pixmap)


class _BuilderStatus(QLabel):
    text_changed = pyqtSignal(str)

    def setText(self, text):
        super().setText(text)
        self.text_changed.emit(text)


class _EditorConfirmDialog(QDialog):
    """Enter commits an editor; only an explicit button submits the dialog."""
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
            focus=self.focusWidget()
            if isinstance(focus,(QLineEdit,QAbstractSpinBox,QComboBox)):
                event.accept();return
            if isinstance(focus,QPushButton) and focus.isEnabled():
                focus.click();event.accept();return
        super().keyPressEvent(event)


class _MaterialCard(QFrame):
    selected = pyqtSignal(str)
    edit_requested = pyqtSignal(str)

    def __init__(self, material, parent=None):
        super().__init__(parent)
        self.material_id = material['id']
        self.setObjectName('deviceMaterialCard')
        self.setMinimumWidth(125)
        self.setMaximumWidth(210)
        self.setFixedHeight(135)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9,10,9,8)
        layout.setSpacing(6)
        row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(_device_icon('cube',_color(material['id'])).pixmap(38,38))
        icon.setFixedSize(38,38)
        row.addWidget(icon)
        names = QVBoxLayout()
        names.setSpacing(3)
        title = _label(material['name'])
        title.setObjectName('materialCardTitle')
        names.addWidget(title)
        note = _label('Built-in · editable' if material.get('builtin',material['id'] in ('gaas','ito','algaas','silicon','air')) else 'Custom · editable')
        self.note=note;self.full_note=note.text()
        note.setObjectName('materialCardNote')
        names.addWidget(note)
        row.addLayout(names,1)
        layout.addLayout(row)
        if material['id']=='algaas':
            note = _label(f"Alloy fraction x = {material.get('al_fraction',.5):g}")
            self.alloy_note=note;self.alloy_fraction=material.get('al_fraction',.5)
            note.setObjectName('materialCardNote')
            layout.addWidget(note)
        layout.addStretch()
        self.edit_button = _button('Edit…',lambda:self.edit_requested.emit(self.material_id))
        self.edit_button.setObjectName('materialCardEdit')
        layout.addWidget(self.edit_button)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.selected.emit(self.material_id)
        super().mousePressEvent(event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.note.setText(self.full_note.split(' · ')[0] if self.width()<150 else self.full_note)
        if hasattr(self,'alloy_note'):
            self.alloy_note.setText(f'x = {self.alloy_fraction:g}' if self.width()<150 else f'Alloy fraction x = {self.alloy_fraction:g}')


def _polygon(obj):
    points=list(_model_api().geometry_vertices(obj))
    # Canonical polygon vertices can use either winding. Normalize only the
    # display loop so face lighting/culling has a consistent outward normal.
    if sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1]))<0.:
        points.reverse()
    return points


def _section_intervals(points, cut):
    intersections = []
    for first, second in zip(points, points[1:] + points[:1]):
        if (first[1] <= cut < second[1]) or (second[1] <= cut < first[1]):
            intersections.append(first[0] + (cut-first[1]) * (second[0]-first[0]) / (second[1]-first[1]))
    intersections.sort()
    return list(zip(intersections[::2], intersections[1::2]))


def _shape_section_intervals(obj, cut, swap=False):
    if obj.get('shape') in ('circle','ellipse'):
        x,y=obj.get('cx_um',0.),obj.get('cy_um',0.)
        angle=math.radians(obj.get('angle_deg',0.))
        if swap:x,y=y,x;angle=math.pi/2-angle
        a=obj['size_x_um']/2;b=a if obj['shape']=='circle' else obj['size_y_um']/2
        c,s=math.cos(angle),math.sin(angle);dy=cut-y
        aa=c*c/(a*a)+s*s/(b*b)
        bb=2*c*s*dy*(1/(a*a)-1/(b*b))
        cc=dy*dy*(s*s/(a*a)+c*c/(b*b))-1
        discriminant=bb*bb-4*aa*cc
        if discriminant<0:return []
        root=math.sqrt(max(0.,discriminant))
        return [(x+(-bb-root)/(2*aa),x+(-bb+root)/(2*aa))]
    outer = _polygon(obj)
    inner = list(_model_api().geometry_inner_vertices(obj))
    if swap:
        outer = [[y, x] for x, y in outer]
        inner = [[y, x] for x, y in inner]
    intervals = _section_intervals(outer, cut)
    for low, high in _section_intervals(inner, cut) if inner else []:
        remainder = []
        for first, last in intervals:
            if high <= first or low >= last:
                remainder.append((first, last))
            else:
                if first < low:
                    remainder.append((first, low))
                if high < last:
                    remainder.append((high, last))
        intervals = remainder
    return intervals


class _FlowLayout(QLayout):
    """Keep drawing/library actions accessible as the workspace narrows."""
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size+QSize(left+right, top+bottom)

    def _layout(self, rect, measure):
        left, top, right, bottom = self.getContentsMargins()
        area = rect.adjusted(left, top, -right, -bottom)
        x, y, row_height = area.x(), area.y(), 0
        for item in self.items:
            hint = item.sizeHint()
            width = min(hint.width(), max(1, area.width()))
            if x > area.x() and x+width > area.right()+1:
                x = area.x()
                y += row_height+self.spacing()
                row_height = 0
            if not measure:
                item.setGeometry(QRect(x, y, width, hint.height()))
            x += width+self.spacing()
            row_height = max(row_height, hint.height())
        return y+row_height-rect.y()+bottom


class _DeviceTabs(QTabWidget):
    def minimumSizeHint(self):
        current = self.currentWidget()
        hint = current.minimumSizeHint() if current is not None else QSize()
        return QSize(min(hint.width(),700), hint.height()+(self.tabBar().sizeHint().height() if self.tabBar().isVisible() else 0))


class DeviceCanvas(QWidget):
    """A shared selection/drawing view; every displayed entity has a model ID."""
    object_selected = pyqtSignal(str)
    geometry_created = pyqtSignal(dict)
    object_moved = pyqtSignal(str, float, float)
    surface_picked = pyqtSignal(str, str)
    interaction_cancelled = pyqtSignal()

    def __init__(self, mode='top', parent=None):
        super().__init__(parent)
        self.mode = mode
        self.device = {}
        self.selected = ''
        self.selected_layer = ''
        self.tool = 'select'
        self.cut_y = 0.
        self.show_mesh = False
        self.show_doping = True
        self.wireframe=False
        self.render_quality = 'studio'
        self.show_shadows = True
        self.show_reflections = True
        self.show_ambient_occlusion = True
        self.optical_unit_cell = None
        self.headered=False
        self.compact_preview=False
        self.plan_layer_mode='selected'
        self.depth_display_mode='auto'
        self.perspective=True
        self.navigation_mode='rotate'
        self.pan=QPointF(0,0)
        self.hits = []
        self.zoom = 1.
        self.yaw = -.6
        self.elevation = .48
        self.drag_start = None
        self.drag_end = None
        self.polygon_points = []
        self.pick_surface = False
        self.setMinimumSize(240, 170)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName({'top': 'Editable top view of the finite device',
            'section': 'Linked device cross-section', '3d': 'Rotatable linked 3D device preview'}[mode])
        theme_manager().changed.connect(self.update)

    def set_device(self, device, selected='', selected_layer=''):
        # ProjectStore replaces canonical dictionaries atomically; views only
        # read them. Sharing the snapshot avoids three full 100k-hole copies.
        self.device = device
        self._shape_lookup={row['id']:row for row in device.get('shapes',[])}
        self.selected = selected
        self.selected_layer = selected_layer
        self.update()

    def set_tool(self, tool):
        self.tool = tool
        self.polygon_points = []
        self.drag_start = self.drag_end = None
        self.setCursor(Qt.CursorShape.CrossCursor if tool in ('rectangle', 'circle', 'ellipse', 'polygon', 'square_ring', 'contact', 'doping') else Qt.CursorShape.ArrowCursor)
        self.update()

    def set_render_quality(self, quality='studio', *, shadows=None,
                           reflections=None, ambient_occlusion=None):
        """Change live presentation without touching the current simulation device model."""
        if quality not in ('studio', 'flat'):
            raise ValueError('Preview quality must be studio or flat')
        self.render_quality = quality
        for name, value in (('show_shadows', shadows), ('show_reflections', reflections),
                            ('show_ambient_occlusion', ambient_occlusion)):
            if value is not None:
                setattr(self, name, bool(value))
        self.update()

    def _plan_transform(self):
        width = float(self.device.get('width_um', 2))
        depth = float(self.device.get('depth_um', 2))
        scale = min((self.width()-60)/width, (self.height()-60)/depth) * self.zoom
        return scale, self.width()/2+self.pan.x(), self.height()/2+5+self.pan.y()

    def world_point(self, point):
        scale, cx, cy = self._plan_transform()
        return ((point.x()-cx)/scale, (cy-point.y())/scale)

    def screen_point(self, x, y):
        scale, cx, cy = self._plan_transform()
        return QPointF(cx+x*scale, cy-y*scale)

    def _path(self, points, projection=None):
        path = QPainterPath()
        polygon = QPolygonF([projection(*point) if projection else self.screen_point(*point) for point in points])
        path.addPolygon(polygon)
        path.closeSubpath()
        return path

    def _object_path(self, obj, projection=None):
        path = self._path(_polygon(obj), projection)
        inner = list(_model_api().geometry_inner_vertices(obj))
        if inner:
            path.addPath(self._path(inner, projection))
            path.setFillRule(Qt.FillRule.OddEvenFill)
        return path

    def _layers(self):
        return [layer for layer in _model_api().layer_bounds(self.device) if layer.get('enabled', True)]

    def _optical_depth_bounds(self,layers):
        total=max(layer['z_max_um'] for layer in layers)
        above=below=0.
        for contact in self.device.get('contacts',[]):
            if not contact.get('enabled',True):continue
            thickness=contact.get('optical_thickness_um',0.)
            if contact.get('surface')=='top' and contact['layer_id']==layers[0]['id']:above=max(above,thickness)
            if contact.get('surface')=='bottom' and contact['layer_id']==layers[-1]['id']:below=max(below,thickness)
        return -above,total+below

    def _geometry_objects(self, layer_id=None):
        for kind in ('shapes', 'doping_regions', 'contacts'):
            if kind == 'doping_regions' and not self.show_doping:
                continue
            for obj in (getattr(self,'_render_shapes',self.device.get('shapes',[])) if kind=='shapes' else self.device.get(kind, [])):
                if obj.get('enabled', True) and (layer_id is None or obj['layer_id'] == layer_id):
                    yield kind, obj

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = COLORS[theme_manager().mode]
        background = QLinearGradient(0, 0, self.width(), self.height())
        dark = theme_manager().mode == 'dark'
        background.setColorAt(0, QColor('#122639' if dark else '#e5edf5'))
        background.setColorAt(1, QColor('#091622' if dark else '#cbd8e5'))
        painter.fillRect(self.rect(), background)
        if self.mode == '3d' and self.render_quality == 'studio' and not self.wireframe:
            backdrop = QRadialGradient(QPointF(self.width()*.46, self.height()*.42), max(self.width(),self.height())*.68)
            backdrop.setColorAt(0, QColor(43, 81, 107, 77 if dark else 25))
            backdrop.setColorAt(1, QColor(5, 14, 22, 0))
            painter.fillRect(self.rect(), backdrop)
        else:
            grid = QColor('#74a3c7' if dark else '#547a99')
            grid.setAlpha(22)
            painter.setPen(QPen(grid, .65))
            for x in range(0, self.width(), 24):
                painter.drawLine(x, 28, x, self.height()-25)
            for y in range(28, self.height()-25, 24):
                painter.drawLine(0, y, self.width(), y)
        self.hits = []
        self._prepare_shape_render()
        if not self.device or not self.device.get('layers'):
            painter.setPen(QColor(colors['muted']))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Add a layer to begin')
            return
        try:
            if self.mode == 'top':
                self._paint_top(painter, colors)
            elif self.mode == 'section':
                self._paint_section(painter, colors)
            else:
                self._paint_3d(painter, colors)
            self._paint_axes(painter)
            if self.lod_note:
                painter.save();painter.setPen(QColor('#f3cf78'));font=QFont(painter.font());font.setPointSizeF(8);painter.setFont(font)
                painter.drawText(10,22 if self.headered or self.compact_preview else 40,self.lod_note);painter.restore()
        except (ValueError, KeyError, TypeError) as exc:
            painter.setPen(QColor(colors['muted']))
            painter.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.TextFlag.TextWordWrap, str(exc))

    def _draw_object(self, painter, path, kind, obj, normal=(0.,0.,-1.)):
        if kind == 'contacts':
            color = QColor(_contact_color(obj))
            color.setAlpha(220 if obj.get('optical_thickness_um', 0) > 0 else 115)
        elif kind == 'doping_regions':
            color = QColor('#63dba0')
            color.setAlpha(55)
        elif obj.get('operation') == 'void':
            color = QColor(COLORS[theme_manager().mode]['panel']).darker(112)
        else:
            color = QColor(_color(obj.get('material_id')))
        studio = self.mode == '3d' and self.render_quality == 'studio'
        if studio and kind != 'doping_regions' and not self.wireframe:
            painter.setBrush(studio_brush(color, path.boundingRect(), normal, self.yaw,
                metal=kind=='contacts', top=normal[2]<-.5, reflections=self.show_reflections))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush if self.wireframe else self._surface_brush(color, path.boundingRect(), light=116, shade=85)
                if kind == 'contacts' and obj.get('optical_thickness_um', 0) > 0 else color)
        selected = obj['id'] == self.selected
        pen = QPen(QColor('#63d5ff' if selected else '#ffe59b' if studio and kind=='contacts' else '#617489'), 2.5 if selected else .65 if studio else 1)
        if kind == 'doping_regions':
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawPath(path)
        if studio and not self.wireframe and kind != 'doping_regions':
            self._paint_surface_finish(painter,path,color,metal=kind=='contacts',normal=normal)
        if selected:
            self._selection_glow(painter, path)
        self.hits.append((path, obj['id'], obj.get('surface', 'top')))

    def _paint_surface_finish(self, painter, path, color, metal=False, normal=(0.,0.,-1.)):
        """Clipped softbox reflection and subpixel bevel; never alter geometry."""
        if self.wireframe or self.render_quality != 'studio' or path.isEmpty():
            return
        painter.save()
        painter.setClipPath(path)
        if self.show_reflections:
            painter.fillRect(path.boundingRect(),sheen_brush(path.boundingRect(),metal=metal,
                intensity=1. if normal[2]<-.5 else .55))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        edge = mix_color(color,'#fff2b3' if metal else '#d2f1ff',.64 if metal else .45)
        edge.setAlpha(185 if metal else 130)
        painter.setPen(QPen(edge,1.6 if metal else 1.1))
        painter.drawPath(path)
        painter.restore()

    def _paint_soft_shadow(self, painter, path, offset=QPointF(0.,4.), strength=1.):
        if self.wireframe or not self.show_shadows or self.render_quality != 'studio':
            return
        painter.save();painter.setPen(Qt.PenStyle.NoPen)
        # Nested translucent strokes are an inexpensive, stable soft blur that
        # works identically with native raster widgets and offscreen exports.
        shifted=path.translated(offset)
        painter.setBrush(QColor(0,4,8,round(24*strength)))
        painter.drawPath(shifted)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for span,alpha in ((18.,3),(13.,5),(9.,7),(5.,10),(2.,14)):
            painter.setPen(QPen(QColor(0,5,9,round(alpha*strength)),span,
                Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(shifted)
        painter.restore()

    @staticmethod
    def _selection_glow(painter, path):
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((9., 18), (6., 30), (3., 180)):
            color = QColor('#57d7ff')
            color.setAlpha(alpha)
            painter.setPen(QPen(color, width))
            painter.drawPath(path)
        painter.restore()

    def _paint_axes(self, painter):
        painter.save()
        if self.compact_preview and self.mode=='section':
            font=QFont(painter.font());font.setPointSizeF(7.);painter.setFont(font)
            painter.setPen(QColor(COLORS[theme_manager().mode]['muted']))
            painter.drawText(QPointF(10,self.height()-9),'Depth z ↓')
            painter.restore();return
        origin = QPointF(16, self.height()-23) if self.compact_preview and self.mode=='top' else QPointF(28, self.height()-54)
        length=18 if self.compact_preview and self.mode=='top' else 28
        for vector, color, label in [(QPointF(length, 0), '#f37584', 'X'), (QPointF(0, -length), '#68dca0', 'Z' if self.mode == 'section' else 'Y')]:
            painter.setPen(QPen(QColor(color), 1.8))
            painter.drawLine(origin, origin+vector)
            painter.drawText(origin+vector+QPointF(3, -2), label)
        if self.mode == '3d':
            painter.setPen(QPen(QColor('#5ac4ff'), 1.8))
            painter.drawLine(origin, origin+QPointF(-13, -21))
            painter.drawText(origin+QPointF(-19, -25), 'Z')
        painter.restore()

    def _surface_brush(self,color, bounds, light=116, shade=91):
        if self.wireframe:return Qt.BrushStyle.NoBrush
        gradient = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        gradient.setColorAt(0, color.lighter(light))
        gradient.setColorAt(1, color.darker(int(10000/shade)))
        return gradient

    def _void_path(self, layer_id, projection=None):
        result = QPainterPath()
        for obj in getattr(self,'_render_shapes',self.device.get('shapes',[])):
            if obj.get('enabled', True) and obj['layer_id'] == layer_id:
                path = self._object_path(obj, projection)
                result = result.united(path) if obj.get('operation') == 'void' else result.subtracted(path)
        return result

    def _prepare_shape_render(self):
        shapes=self.device.get('shapes',[]);self.lod_note='';self._lod_regions=[]
        if len(shapes)<=2000:
            self._render_shapes=shapes;return
        if self.mode=='3d':
            stride=max(1,math.ceil(len(shapes)/240));sample=shapes[::stride]
            selected=self._shape_lookup.get(self.selected)
            if selected is not None and selected not in sample:sample.append(selected)
            self._render_shapes=sample
            self.lod_note=f'Coarse 3D preview · {len(sample):,} of {len(shapes):,} shapes; document retains all'
            return
        if self.mode=='section':
            self._render_shapes=[obj for obj in shapes if obj.get('shape') not in ('circle','ellipse') or abs(self.cut_y-obj.get('cy_um',0))<=max(obj['size_x_um'],obj['size_y_um'])/2]
            return
        scale=self._plan_transform()[0]
        first=self.world_point(QPointF(0,self.height()));last=self.world_point(QPointF(self.width(),0))
        xmin,xmax=sorted((first[0],last[0]));ymin,ymax=sorted((first[1],last[1]))
        specs={row['id']:row for row in self.device.get('pc_arrays',[])}
        tiny={key for key,spec in specs.items() if spec['radius_um']*scale<2.}
        result=[]
        for obj in shapes:
            if obj['id']==self.selected:result.append(obj);continue
            if obj.get('pc_array_id') in tiny:continue
            extent=max(obj.get('size_x_um',0),obj.get('size_y_um',0))
            if obj.get('shape')=='polygon' or xmin-extent<=obj.get('cx_um',0)<=xmax+extent and ymin-extent<=obj.get('cy_um',0)<=ymax+extent:
                result.append(obj)
        self._render_shapes=result
        if len(result)>1500:
            result=result[::math.ceil(len(result)/1500)]
            selected=self._shape_lookup.get(self.selected)
            if selected is not None and selected not in result:result.append(selected)
            self._render_shapes=result
            self.lod_note=f'Coarse XY preview · {len(result):,} visible shapes; zoom or Find object'
        if tiny:
            self._lod_regions=[specs[key] for key in tiny]
            self.lod_note=f'{len(shapes):,} shapes · subpixel holes shown as PC area; zoom or Find object'

    def _paint_pc_regions(self,painter,layer_id):
        for spec in self.device.get('pc_arrays',[]):
            if spec['layer_id']!=layer_id or not spec.get('enabled',True):continue
            rect=QRectF(self.screen_point(spec['cx_um']-spec['width_um']/2,spec['cy_um']+spec['depth_um']/2),
                       self.screen_point(spec['cx_um']+spec['width_um']/2,spec['cy_um']-spec['depth_um']/2)).normalized()
            painter.save();painter.setPen(QPen(QColor('#709ca9'),1.,Qt.PenStyle.DashLine))
            painter.setBrush(QColor(35,119,146,55) if spec in self._lod_regions else Qt.BrushStyle.NoBrush)
            painter.drawRect(rect);painter.restore()

    def _paint_optical_domain(self,painter,projection=None,pc_layer_id=None):
        """An optical study guide, separate from the finite physical device."""
        cell=self.optical_unit_cell
        if not isinstance(cell,dict):return
        painter.save();painter.setBrush(Qt.BrushStyle.NoBrush)
        if projection is not None and pc_layer_id is not None:
            for area in self.device.get('pc_arrays',[]):
                if not area.get('enabled',True) or area.get('layer_id')!=pc_layer_id:continue
                cx,cy=area['cx_um'],area['cy_um'];hx,hy=area['width_um']/2,area['depth_um']/2
                path=self._path([(cx-hx,cy-hy),(cx+hx,cy-hy),(cx+hx,cy+hy),(cx-hx,cy+hy)],projection)
                painter.setPen(QPen(QColor('#709ca9'),1.,Qt.PenStyle.DashLine));painter.drawPath(path)
        if cell.get('enabled',False):
            try:
                width=float(cell['width_um']);depth=float(cell['depth_um'])
                cx=float(cell.get('cx_um',0.));cy=float(cell.get('cy_um',0.))
                if width<=0 or depth<=0 or not all(math.isfinite(value) for value in (width,depth,cx,cy)):
                    painter.restore();return
            except (KeyError,TypeError,ValueError):
                painter.restore();return
            corners=[(cx-width/2,cy-depth/2),(cx+width/2,cy-depth/2),
                (cx+width/2,cy+depth/2),(cx-width/2,cy+depth/2)]
            path=self._path(corners,projection)
            painter.setBrush(QColor(40,168,250,10));painter.setPen(QPen(QColor('#28b8ff'),1.8))
            painter.drawPath(path)
            if not self.compact_preview:
                font=QFont(painter.font());font.setPointSizeF(8);painter.setFont(font)
                label=f'Optical cell · {width:g} × {depth:g} µm'
                bounds=path.boundingRect()
                painter.drawText(QPointF(max(8.,min(bounds.left(),self.width()-200.)),max(38.,bounds.top()-6.)),label)
        painter.restore()

    def _paint_top(self, painter, colors):
        layers = self._layers()
        layer = layers[0] if self.plan_layer_mode=='top' else next((item for item in layers if item['id'] == self.selected_layer), layers[0])
        width, depth = self.device['width_um'], self.device['depth_um']
        outline = self._path([(-width/2, -depth/2), (width/2, -depth/2), (width/2, depth/2), (-width/2, depth/2)])
        painter.setPen(QPen(QColor('#63d5ff' if self.selected == layer['id'] else '#718396'), 2))
        painter.setBrush(self._surface_brush(QColor(_layer_color(layer)), outline.boundingRect()))
        painter.drawPath(outline)
        self.hits.append((outline, layer['id'], 'top'))
        void_path = self._void_path(layer['id'])
        painter.save()
        painter.setClipPath(outline)
        for kind, obj in self._geometry_objects():
            if obj['layer_id'] != layer['id']:
                continue
            path = self._object_path(obj)
            if kind == 'contacts':
                path = path.subtracted(void_path)
            self._draw_object(painter, path, kind, obj)
        if self.show_mesh:
            mesh = self.device['mesh']
            painter.setPen(QPen(QColor('#e5f4ff'), .6, Qt.PenStyle.DotLine))
            for index in range(0, mesh['nx']+1, max(1, math.ceil(mesh['nx']/80))):
                x = -width/2+width*index/mesh['nx']
                painter.drawLine(self.screen_point(x, -depth/2), self.screen_point(x, depth/2))
            for index in range(0, mesh['ny']+1, max(1, math.ceil(mesh['ny']/80))):
                y = -depth/2+depth*index/mesh['ny']
                painter.drawLine(self.screen_point(-width/2, y), self.screen_point(width/2, y))
        painter.restore()
        self._paint_pc_regions(painter,layer['id'])
        self._paint_optical_domain(painter)
        for kind, obj in self._geometry_objects(layer['id']):
            if obj['id'] == self.selected:
                self._selection_glow(painter, self._object_path(obj).intersected(outline))
        painter.setPen(QPen(QColor('#5bedd2'), 1.3, Qt.PenStyle.DashLine))
        painter.drawLine(self.screen_point(-width/2, self.cut_y), self.screen_point(width/2, self.cut_y))
        painter.setPen(QColor(colors['text']))
        if not self.headered and not self.compact_preview:painter.drawText(12, 22, f"XY · {layer['name']}")
        painter.setPen(QColor(colors['muted']))
        if not self.compact_preview and not self.headered:painter.drawText(12, self.height()-10, f'{width:g} × {depth:g} µm · cut y = {self.cut_y:g} µm')
        else:self._paint_scale_bar(painter,width,self._plan_transform()[0])
        if self.drag_start is not None and self.drag_end is not None and self.tool not in ('select', 'move'):
            painter.setPen(QPen(QColor('#63d5ff'), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(self.drag_start, self.drag_end).normalized()
            if self.tool == 'circle':
                center = rect.center()
                rect = QRectF(center.x()-rect.width()/2, center.y()-rect.width()/2, rect.width(), rect.width())
            painter.drawEllipse(rect) if self.tool in ('circle', 'ellipse') else painter.drawRect(rect)
            if self.tool == 'square_ring':
                painter.drawRect(rect.adjusted(rect.width()/4, rect.height()/4, -rect.width()/4, -rect.height()/4))
        if self.polygon_points:
            painter.setPen(QPen(QColor('#63d5ff'), 2))
            painter.drawPolyline(QPolygonF([self.screen_point(*point) for point in self.polygon_points]))

    def _section_transform(self):
        layers = self._layers()
        total = max(layer['z_max_um'] for layer in layers)
        width = self.device['width_um']
        side_margin=24 if self.compact_preview else 150
        top_margin=14 if self.compact_preview else 32
        bottom_margin=29 if self.compact_preview else 33
        sx = max(1.,self.width()-side_margin)/width*self.zoom
        z_min,z_max=self._optical_depth_bounds(layers)
        sz = (self.height()-top_margin-bottom_margin)/max(z_max-z_min, 1e-9)*self.zoom
        return sx, sz, self.width()/2 if self.compact_preview else 90+max(1.,self.width()-150)/2, top_margin-z_min*sz, total

    def _paint_section(self, painter, colors):
        sx, sz, cx, top, total = self._section_transform()
        width = self.device['width_um']
        for layer in self._layers():
            rect = QRectF(cx-width*sx/2, top+layer['z_min_um']*sz, width*sx, layer['thickness_um']*sz)
            path = QPainterPath()
            path.addRect(rect)
            painter.setBrush(self._surface_brush(QColor(_layer_color(layer)), rect, light=112, shade=96))
            painter.setPen(QPen(QColor('#63d5ff' if layer['id'] == self.selected else '#526578'), 2 if layer['id'] == self.selected else .8))
            painter.drawPath(path)
            self.hits.append((path, layer['id'], 'top'))
            for kind, obj in self._geometry_objects(layer['id']):
                for left, right in _shape_section_intervals(obj, self.cut_y):
                    left, right = max(left, -width/2), min(right, width/2)
                    if right <= left:
                        continue
                    if kind == 'contacts':
                        surface = obj.get('surface', 'top')
                        if surface.startswith('side_x'):
                            edge = -width/2 if surface == 'side_x_min' else width/2
                            if not _model_api().shape_mask(obj, edge, self.cut_y):
                                continue
                            part = QRectF(cx+edge*sx-3, rect.y(), 6, rect.height())
                        elif surface.startswith('side_y'):
                            edge = (-1 if surface == 'side_y_min' else 1)*self.device['depth_um']/2
                            if not math.isclose(self.cut_y, edge, abs_tol=1e-9):
                                continue
                            part = QRectF(cx+left*sx, rect.y(), (right-left)*sx, rect.height())
                        else:
                            z = layer['z_max_um'] if surface == 'bottom' else layer['z_min_um']
                            thickness=obj.get('optical_thickness_um',0.)
                            exterior=(surface=='top' and layer['id']==self._layers()[0]['id']) or (surface=='bottom' and layer['id']==self._layers()[-1]['id'])
                            part = QRectF(cx+left*sx,top+(z-thickness if surface=='top' else z)*sz,(right-left)*sx,thickness*sz) if thickness>0 and exterior else QRectF(cx+left*sx, top+z*sz-4, (right-left)*sx, 8)
                    else:
                        part = QRectF(cx+left*sx, rect.y(), (right-left)*sx, rect.height())
                    shape_path = QPainterPath()
                    shape_path.addRect(part)
                    self._draw_object(painter, shape_path, kind, obj)
            if rect.height() > 16:
                painter.setPen(QColor(colors['text']))
                font=QFont(painter.font());font.setPointSizeF(8);painter.save();painter.setFont(font)
                thickness_text=f"{layer['thickness_um']*1000:g} nm"
                thickness_width=min(rect.width()*.48,QFontMetrics(font).horizontalAdvance(thickness_text)+6)
                name_width=min(80.,max(6.,rect.width()-thickness_width-18)) if self.compact_preview else 80.
                name=QFontMetrics(font).elidedText(layer['name'],Qt.TextElideMode.ElideRight,int(name_width))
                if self.compact_preview:
                    # Both labels stay inside their own physical layer, with
                    # a subtle backing that keeps thin films readable.
                    name_rect=QRectF(rect.left()+5,rect.y(),name_width,rect.height())
                    thickness_rect=QRectF(rect.right()-5-thickness_width,rect.y(),thickness_width,rect.height())
                    painter.setBrush(QColor(5,17,27,110));painter.setPen(Qt.PenStyle.NoPen)
                    for label_rect in (name_rect,thickness_rect):
                        painter.drawRoundedRect(QRectF(label_rect.left()-2,label_rect.center().y()-7,label_rect.width()+4,14),2,2)
                    painter.setPen(QColor('#e6f2ff'))
                    painter.drawText(name_rect,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,name)
                    painter.drawText(thickness_rect,Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,thickness_text)
                else:
                    painter.drawText(QRectF(3,rect.y(),80,rect.height()),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,name)
                    painter.drawText(QRectF(rect.right()+7,rect.y(),55,rect.height()),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,f"{layer['thickness_um']*1000:g} nm")
                painter.restore()
            if self.show_mesh:
                count = self.device['mesh']['nz_per_layer']
                painter.setPen(QPen(QColor('#e5f4ff'), .6, Qt.PenStyle.DotLine))
                for index in range(1, count, max(1, math.ceil(count/80))):
                    z = layer['z_min_um']+layer['thickness_um']*index/count
                    painter.drawLine(QPointF(cx-width*sx/2, top+z*sz), QPointF(cx+width*sx/2, top+z*sz))
        painter.setPen(QColor(colors['text']))
        if not self.headered and not self.compact_preview:painter.drawText(12, 22, f'XZ · y = {self.cut_y:g} µm')
        painter.setPen(QColor(colors['muted']))
        if not self.compact_preview:
            caption=f'Depth display ×{sz/sx:.2g}' if self.headered else f'Depth 0–{total:g} µm · vertical display scale ×{sz/sx:.2g}'
            painter.drawText(12,self.height()-10,caption)
        if self.compact_preview or self.headered:self._paint_scale_bar(painter,width,sx)

    def _paint_scale_bar(self,painter,width,scale):
        length=width/4
        span=length*scale
        if span<=0:return
        painter.save();painter.setPen(QPen(QColor(COLORS[theme_manager().mode]['text']),1))
        end=self.width()-16;start=end-span;y=self.height()-21
        painter.drawLine(QPointF(start,y),QPointF(end,y))
        painter.drawLine(QPointF(start,y-3),QPointF(start,y+3));painter.drawLine(QPointF(end,y-3),QPointF(end,y+3))
        font=QFont(painter.font());font.setPointSizeF(8);painter.setFont(font)
        caption=f'{length:g} µm';label_width=max(span,QFontMetrics(font).horizontalAdvance(caption)+8)
        label_left=max(4.,min(self.width()-label_width-4,(start+end-label_width)/2))
        painter.drawText(QRectF(label_left,y+3,label_width,17),Qt.AlignmentFlag.AlignHCenter,caption);painter.restore()

    def _paint_3d(self, painter, colors):
        studio=self.render_quality=='studio' and not self.wireframe
        layers = self._layers()
        width, depth = self.device['width_um'], self.device['depth_um']
        total = max(layer['z_max_um'] for layer in layers)
        z_min,z_max=self._optical_depth_bounds(layers);draw_depth=z_max-z_min
        if self.depth_display_mode=='physical':exaggeration=1.
        elif self.depth_display_mode=='film':exaggeration=min(100.,max(.25,min(width,depth)/max(draw_depth*7,1e-9)))
        else:exaggeration=min(100.,max(1.,min(width,depth)/max(draw_depth*6,1e-9)))
        cosine, sine = math.cos(self.yaw), math.sin(self.yaw)
        x_extent = abs(cosine)*width+abs(sine)*depth
        y_extent = (abs(sine)*width+abs(cosine)*depth)*self.elevation+draw_depth*exaggeration
        legend = self.width() > 540 and not self.compact_preview
        usable_width = self.width()-(245 if legend else 60)
        center_x = (self.width()-(190 if legend else 0))/2
        scale = min(usable_width/max(x_extent, 1e-9), (self.height()-65)/max(y_extent, 1e-9))*self.zoom
        def project(x, y, z):
            rotated_x=x*cosine-y*sine;rotated_y=x*sine+y*cosine
            camera_distance=max(width,depth,draw_depth*exaggeration)*3;depth_center=(z_min+z_max)/2
            perspective=camera_distance/(camera_distance-rotated_y*.65+(z-depth_center)*exaggeration*.15) if self.perspective else 1.
            return QPointF(center_x+rotated_x*scale*perspective+self.pan.x(),
                self.height()/2+(rotated_y*self.elevation+(z-depth_center)*exaggeration)*scale*perspective+self.pan.y())
        points = [(-width/2, -depth/2), (width/2, -depth/2), (width/2, depth/2), (-width/2, depth/2)]
        shadow = self._path(points, lambda x, y: project(x, y, z_max))
        if studio:
            if self.show_reflections:
                # A faint floor reflection beneath the actual projected base;
                # the real device faces are painted above it, preserving depth.
                reflection=QTransform(1.,0.,0.,-.32,0.,shadow.boundingRect().bottom()*1.32+5.)
                painter.save();painter.setPen(Qt.PenStyle.NoPen)
                floor=QLinearGradient(0,shadow.boundingRect().bottom(),0,self.height())
                floor.setColorAt(0,QColor(100,164,201,22));floor.setColorAt(1,QColor(30,65,90,0))
                painter.setBrush(floor);painter.drawPath(reflection.map(shadow));painter.restore()
            self._paint_soft_shadow(painter,shadow,QPointF(5.,7.),1.25)
        elif self.show_shadows and not self.wireframe:
            painter.save();painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0,0,0,28));painter.drawPath(shadow.translated(0,4));painter.restore()
        visible_sides={face for normal,face in (((0,-1),'side_y_min'),((1,0),'side_x_max'),((0,1),'side_y_max'),((-1,0),'side_x_min')) if normal[0]*sine+normal[1]*cosine>1e-8}
        # Exterior bottom metal is behind the semiconductor from this camera.
        # Only its facing edge band is visible; painting a full horizontal
        # bottom plane afterwards would incorrectly cover the device walls.
        bottom=layers[-1]
        for obj in self.device.get('contacts',[]):
            if not obj.get('enabled',True) or obj['layer_id']!=bottom['id'] or obj.get('surface')!='bottom':continue
            thickness=obj.get('optical_thickness_um',0)
            vertices=_polygon(obj);z=bottom['z_max_um']
            for first,last in zip(vertices,vertices[1:]+vertices[:1]):
                dx,dy=last[0]-first[0],last[1]-first[1]
                if dy*sine-dx*cosine<=1e-8:continue
                wall=QPainterPath();wall.addPolygon(QPolygonF([project(*first,z),project(*last,z),project(*last,z+thickness),project(*first,z+thickness)]));wall.closeSubpath()
                magnitude=max(math.hypot(dx,dy),1e-12)
                if thickness>0:self._draw_object(painter,wall,'contacts',obj,(dy/magnitude,-dx/magnitude,0.))
                else:
                    painter.setPen(QPen(QColor(_contact_color(obj)),2));painter.drawLine(project(*first,z),project(*last,z))
        for layer in reversed(layers):
            objects = list(self._geometry_objects(layer['id']))
            upper = [project(x, y, layer['z_min_um']) for x, y in points]
            lower = [project(x, y, layer['z_max_um']) for x, y in points]
            color = QColor(_layer_color(layer))
            if layer.get('material_id')=='ito':color.setAlpha(205)
            painter.setPen(QPen(QColor('#63d5ff' if self.selected == layer['id'] else '#516477'), 2 if self.selected == layer['id'] else .8))
            for i, face in ((0, 'side_y_min'), (1, 'side_x_max'), (2, 'side_y_max'), (3, 'side_x_min')):
                if face not in visible_sides:continue
                wall = QPainterPath()
                wall.addPolygon(QPolygonF([upper[i], upper[(i+1)%4], lower[(i+1)%4], lower[i]]))
                wall.closeSubpath()
                edge_void=QPainterPath()
                material_faces=[]
                for kind,obj in objects:
                    if kind!='shapes':continue
                    edge_region=QPainterPath()
                    for region in self._side_contact_paths(dict(obj,surface=face),layer,project):
                        edge_region=edge_region.united(region)
                    if obj.get('operation')=='void':edge_void=edge_void.united(edge_region)
                    else:
                        edge_void=edge_void.subtracted(edge_region)
                        material_faces.append((obj,edge_region))
                wall=wall.subtracted(edge_void)
                normal=((0.,-1.,0.),(1.,0.,0.),(0.,1.,0.),(-1.,0.,0.))[i]
                painter.setBrush(studio_brush(color,wall.boundingRect(),normal,self.yaw,
                    reflections=self.show_reflections) if studio else self._surface_brush(color, wall.boundingRect(), light=88 if i % 2 else 98, shade=66 if i % 2 else 77))
                painter.drawPath(wall)
                if studio:self._paint_surface_finish(painter,wall,color,normal=normal)
                self.hits.append((wall, layer['id'], face))
                for obj,region in material_faces:
                    region=region.subtracted(edge_void).intersected(wall)
                    if not region.isEmpty():self._draw_object(painter,region,'shapes',obj,normal)
            base_top = QPainterPath()
            base_top.addPolygon(QPolygonF(upper))
            base_top.closeSubpath()
            void_path = QPainterPath()
            for kind, obj in objects:
                if kind == 'shapes':
                    region = self._object_path(obj, lambda x, y: project(x, y, layer['z_min_um'])).intersected(base_top)
                    void_path = void_path.united(region) if obj.get('operation') == 'void' else void_path.subtracted(region)
            top_path = base_top.subtracted(void_path)
            surface_color=mix_color(color,'#349ede',.62) if studio and self.show_reflections and layer.get('material_id')=='silicon' else color
            painter.setBrush(studio_brush(surface_color,top_path.boundingRect(),yaw=self.yaw,top=True,
                reflections=self.show_reflections) if studio else self._surface_brush(color, top_path.boundingRect(), light=124, shade=96))
            painter.drawPath(top_path)
            if studio:
                self._paint_surface_finish(painter,top_path,surface_color)
            elif not self.wireframe:
                painter.save();painter.setClipPath(top_path)
                sheen=QLinearGradient(top_path.boundingRect().topLeft(),top_path.boundingRect().bottomRight())
                sheen.setColorAt(0,QColor(225,246,255,45));sheen.setColorAt(.5,QColor(225,246,255,8));sheen.setColorAt(1,QColor(225,246,255,0))
                painter.fillRect(top_path.boundingRect(),sheen);painter.restore()
                painter.save();painter.setBrush(Qt.BrushStyle.NoBrush)
                highlight=color.lighter(145);highlight.setAlpha(120);painter.setPen(QPen(highlight,.8));painter.drawPath(top_path);painter.restore()
            # Void walls use the same extruded footprints and layer bounds as
            # the solver, rather than drawing decorative holes in the surface.
            if not void_path.isEmpty():
                painter.save();painter.setClipPath(void_path)
                if studio and self.show_ambient_occlusion:
                    # Deep apertures darken the visible floor. The shading is
                    # clipped to the true union of the current layer's voids.
                    ambient=QLinearGradient(void_path.boundingRect().topLeft(),void_path.boundingRect().bottomRight())
                    ambient.setColorAt(0,QColor(3,12,22,85));ambient.setColorAt(1,QColor(3,12,22,24))
                    painter.fillRect(void_path.boundingRect(),ambient)
                for kind,obj in objects:
                    if kind!='shapes' or obj.get('operation')!='void':continue
                    vertices=_polygon(obj)
                    wall_path=QPainterPath()
                    cavity_bounds=self._object_path(obj,lambda x,y:project(x,y,layer['z_min_um'])).united(
                        self._object_path(obj,lambda x,y:project(x,y,layer['z_max_um']))).boundingRect()
                    smooth_cavity=studio and obj.get('shape') in ('circle','ellipse')
                    for first,last in zip(vertices,vertices[1:]+vertices[:1]):
                        dx,dy=last[0]-first[0],last[1]-first[1]
                        if dy*sine-dx*cosine>=0:continue
                        wall=QPainterPath();wall.addPolygon(QPolygonF([
                            project(*first,layer['z_min_um']),project(*last,layer['z_min_um']),
                            project(*last,layer['z_max_um']),project(*first,layer['z_max_um'])]));wall.closeSubpath()
                        wall_path=wall_path.united(wall)
                        if studio and not smooth_cavity:
                            length=max(math.hypot(dx,dy),1e-12)
                            normal=(-dy/length,dx/length,0.)
                            wall_brush=studio_brush(color,cavity_bounds,normal,self.yaw,cavity=True,
                                reflections=self.show_reflections)
                            painter.setBrush(wall_brush)
                            # Matching half-pixel edges cover raster seams
                            # between adjacent smooth cylindrical facets.
                            painter.setPen(QPen(wall_brush,.55));painter.drawPath(wall)
                    if smooth_cavity:
                        # One continuous reflection for cylindrical walls
                        # avoids visible seams between the geometry facets.
                        curvature=QLinearGradient(cavity_bounds.left(),0.,cavity_bounds.right(),0.)
                        for position,value in ((0.,'#142c3c'),(.23,'#385567'),(.57,'#172e40'),(1.,'#263e50')):
                            curvature.setColorAt(position,QColor(value))
                        painter.setBrush(curvature);painter.setPen(Qt.PenStyle.NoPen);painter.drawPath(wall_path)
                        depth_shade=QLinearGradient(0.,cavity_bounds.top(),0.,cavity_bounds.bottom())
                        depth_shade.setColorAt(0.,QColor(1,8,14,0));depth_shade.setColorAt(1.,QColor(1,8,14,90))
                        painter.setBrush(depth_shade);painter.drawPath(wall_path)
                    elif not studio:
                        painter.setBrush(self._surface_brush(color.darker(215),wall_path.boundingRect(),light=115,shade=72))
                        painter.setPen(Qt.PenStyle.NoPen);painter.drawPath(wall_path)
                    opening=self._object_path(obj,lambda x,y:project(x,y,layer['z_min_um'])).intersected(base_top)
                    if studio and self.show_ambient_occlusion:
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        for span,alpha in ((7.,13),(4.,28),(2.,49)):
                            painter.setPen(QPen(QColor(2,10,16,alpha),span));painter.drawPath(opening)
                    self.hits.append((opening,obj['id'],'top'))
                painter.restore()
                if studio:
                    # Fine reflected rim, clipped to the surrounding solid.
                    painter.save();painter.setClipPath(top_path);painter.setBrush(Qt.BrushStyle.NoBrush)
                    rim=mix_color(surface_color,'#b9e6ff',.62);rim.setAlpha(145)
                    painter.setPen(QPen(rim,1.3));painter.drawPath(void_path);painter.restore()
                for kind,obj in objects:
                    if kind=='shapes' and obj.get('operation')=='void' and obj['id']==self.selected:
                        opening=self._object_path(obj,lambda x,y:project(x,y,layer['z_min_um'])).intersected(base_top)
                        self._selection_glow(painter,opening)
            if self.selected == layer['id']:
                self._selection_glow(painter, top_path)
            self.hits.append((top_path, layer['id'], 'top'))
            if studio:
                painter.save();painter.setClipPath(top_path)
                for kind,obj in objects:
                    if kind=='contacts' and obj.get('surface')=='top' and obj.get('optical_thickness_um',0)>0:
                        footprint=self._object_path(obj,lambda x,y:project(x,y,layer['z_min_um']))
                        self._paint_soft_shadow(painter,footprint,QPointF(2.,3.),.8)
                painter.restore()
            for kind, obj in objects:
                if kind == 'shapes' and obj.get('operation') == 'void':
                    continue
                if kind == 'contacts' and obj.get('surface', '').startswith('side_'):
                    if obj['surface'] not in visible_sides:continue
                    normal={'side_x_min':(-1.,0.,0.),'side_x_max':(1.,0.,0.),
                        'side_y_min':(0.,-1.,0.),'side_y_max':(0.,1.,0.)}[obj['surface']]
                    for path in self._side_contact_paths(obj, layer, project):
                        self._draw_object(painter, path, kind, obj,normal)
                    continue
                z = layer['z_max_um'] if kind == 'contacts' and obj.get('surface') == 'bottom' else layer['z_min_um']
                if kind=='contacts' and obj.get('surface')=='bottom' and layer['id']==layers[-1]['id']:continue
                thickness=obj.get('optical_thickness_um',0) if kind=='contacts' else 0
                if thickness>0 and ((obj.get('surface')=='top' and layer['id']==layers[0]['id']) or (obj.get('surface')=='bottom' and layer['id']==layers[-1]['id'])):
                    pad_z=z-thickness if obj.get('surface')=='top' else z+thickness
                    footprint=self._object_path(obj,lambda x,y:QPointF(x,y))
                    domain=QPainterPath();domain.addRect(QRectF(-width/2,-depth/2,width,depth))
                    loops=[[(point.x(),point.y()) for point in polygon] for polygon in footprint.intersected(domain).toSubpathPolygons()]
                    for loop in loops:
                        for first,last in zip(loop,loop[1:]+loop[:1]):
                            wall=QPainterPath();wall.addPolygon(QPolygonF([project(*first,z),project(*last,z),project(*last,pad_z),project(*first,pad_z)]));wall.closeSubpath()
                            dx,dy=last[0]-first[0],last[1]-first[1];length=max(math.hypot(dx,dy),1e-12)
                            normal=(dy/length,-dx/length,0.)
                            painter.setPen(QPen(mix_color(_contact_color(obj),'#ffedac',.40),.65))
                            painter.setBrush(studio_brush(QColor(_contact_color(obj)),wall.boundingRect(),normal,self.yaw,
                                metal=True,reflections=self.show_reflections) if studio else self._surface_brush(QColor(_contact_color(obj)),wall.boundingRect(),light=102,shade=73))
                            painter.drawPath(wall)
                            if studio:self._paint_surface_finish(painter,wall,QColor(_contact_color(obj)),metal=True,normal=normal)
                    z=pad_z
                path = self._object_path(obj, lambda x, y, z=z: project(x, y, z))
                base = self._path(points, lambda x, y, z=z: project(x, y, z))
                path = path.intersected(base)
                if kind == 'shapes':
                    path = path.subtracted(self._void_path(layer['id'],lambda x,y,z=z:project(x,y,z)))
                elif kind == 'contacts' and obj.get('surface') == 'top':
                    path = path.subtracted(self._void_path(layer['id'],lambda x,y,z=z:project(x,y,z)))
                self._draw_object(painter, path, kind, obj)
        self._paint_optical_domain(painter,lambda x,y:project(x,y,layers[0]['z_min_um']),layers[0]['id'])
        painter.setPen(QColor(colors['text']))
        if not self.headered and not self.compact_preview:painter.drawText(12, 22, '3D preview · drag to rotate, wheel to zoom')
        painter.setPen(QColor(colors['muted']))
        if not self.compact_preview:painter.drawText(12, self.height()-10, f'Vertical display scale ×{exaggeration:.2g}')
        if legend:
            x = self.width()-174
            y = 44
            font = QFont(painter.font())
            font.setPointSizeF(max(8., font.pointSizeF()-1))
            painter.setFont(font)
            entries = [(layer['name'], _layer_color(layer)) for layer in layers]
            layer_ids = {layer['id'] for layer in layers}
            entries += [(contact['name'], _contact_color(contact)) for contact in self.device.get('contacts', [])
                if contact.get('enabled', True) and contact['layer_id'] in layer_ids]
            count = max(1, min(12, (self.height()-50)//18))
            for name, color in entries[:count]:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(color))
                painter.drawRoundedRect(QRectF(x, y-9, 11, 11), 2, 2)
                painter.setPen(QColor(colors['text']))
                text = QFontMetrics(font).elidedText(name, Qt.TextElideMode.ElideRight, 148)
                painter.drawText(x+18, y, text)
                y += 18
            if len(entries) > count:
                painter.drawText(x+18, y, f'+ {len(entries)-count} objects')

    def _side_contact_paths(self, obj, layer, project):
        surface = obj['surface']
        polygon = _polygon(obj)
        if surface.startswith('side_x'):
            edge = (-1 if surface == 'side_x_min' else 1)*self.device['width_um']/2
            intervals = _shape_section_intervals(obj, math.nextafter(edge, 0.), swap=True)
            limit = self.device['depth_um']/2
            vertex = lambda value, z: project(edge, value, z)
        else:
            edge = (-1 if surface == 'side_y_min' else 1)*self.device['depth_um']/2
            intervals = _shape_section_intervals(obj, math.nextafter(edge, 0.))
            limit = self.device['width_um']/2
            vertex = lambda value, z: project(value, edge, z)
        paths = []
        for low, high in intervals:
            low, high = max(low, -limit), min(high, limit)
            if high > low:
                path = QPainterPath()
                path.addPolygon(QPolygonF([vertex(low, layer['z_min_um']), vertex(high, layer['z_min_um']),
                    vertex(high, layer['z_max_um']), vertex(low, layer['z_max_um'])]))
                path.closeSubpath()
                paths.append(path)
        return paths

    def _hit(self, point):
        if self.tool == 'move':
            for path, object_id, face in reversed(self.hits):
                if object_id == self.selected and path.contains(point):
                    return object_id, face
        if self.mode=='top' and not self.pick_surface:
            foreground={obj['id'] for group in ('contacts','doping_regions') for obj in self.device.get(group,[])}
            for path,object_id,face in reversed(self.hits):
                obj=self._shape_lookup.get(object_id)
                if (object_id in foreground or obj and not obj.get('pc_array_id')) and path.contains(point):return object_id,face
            hit=self._pc_hit(point)
            if hit:return hit,'top'
        for path, object_id, face in reversed(self.hits):
            if path.contains(point):
                return object_id, face
        return None

    def _pc_hit(self,point):
        x,y=self.world_point(point)
        layers=self._layers();layer_id=layers[0]['id'] if self.plan_layer_mode=='top' else self.selected_layer
        for spec in reversed(self.device.get('pc_arrays',[])):
            if spec['layer_id']!=layer_id:continue
            first_x=spec['cx_um']-(spec['nx']-1)*spec['cell_width_um']/2
            first_y=spec['cy_um']-(spec['ny']-1)*spec['cell_depth_um']/2
            ix0=math.floor((x-first_x)/spec['cell_width_um']);iy0=math.floor((y-first_y)/spec['cell_depth_um'])
            for ix,iy in ((ix0,iy0),(ix0+1,iy0),(ix0,iy0+1),(ix0+1,iy0+1)):
                if not 0<=ix<spec['nx'] or not 0<=iy<spec['ny']:continue
                index=iy*spec['nx']+ix
                object_id=spec['shape_ids'][index] if index<len(spec.get('shape_ids',[])) else f'{spec["id"]}_h_{ix}_{iy}'
                obj=self._shape_lookup.get(object_id)
                if obj and obj.get('enabled',True) and bool(_model_api().shape_mask(obj,x,y)):return object_id
        return None

    def mousePressEvent(self, event):
        self.setFocus()
        if self.mode=='top' and event.button()==Qt.MouseButton.MiddleButton:
            self._pan_start=event.position();return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        if self.mode == 'top' and self.tool == 'polygon':
            self.polygon_points.append(self.world_point(point))
            self.update()
            return
        self.drag_start = self.drag_end = point
        if self.tool in ('select', 'move') or self.mode != 'top' or self.pick_surface:
            hit = self._hit(point)
            if hit:
                if self.pick_surface:
                    self.surface_picked.emit(*hit)
                else:
                    self.object_selected.emit(hit[0])

    def mouseMoveEvent(self, event):
        if self.mode=='top' and event.buttons()&Qt.MouseButton.MiddleButton and getattr(self,'_pan_start',None) is not None:
            self.pan+=event.position()-self._pan_start;self._pan_start=event.position();self.update();return
        if self.drag_start is None:
            return
        current = event.position()
        if self.mode == '3d' and event.buttons() & Qt.MouseButton.LeftButton:
            delta = current-self.drag_end
            if self.navigation_mode=='pan':self.pan+=delta
            else:
                self.yaw += delta.x()*.008
                self.elevation = min(.9, max(.1, self.elevation+delta.y()*.004))
        self.drag_end = current
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button()==Qt.MouseButton.MiddleButton:
            self._pan_start=None;return
        if event.button() != Qt.MouseButton.LeftButton or self.drag_start is None:
            return
        start, end = self.drag_start, event.position()
        if self.mode == 'top' and self.tool == 'move' and (end-start).manhattanLength() > 3:
            x0, y0 = self.world_point(start)
            x1, y1 = self.world_point(end)
            self.object_moved.emit(self.selected, x1-x0, y1-y0)
        elif self.mode == 'top' and self.tool not in ('select', 'move', 'polygon') and (end-start).manhattanLength() > 4:
            x0, y0 = self.world_point(start)
            x1, y1 = self.world_point(end)
            self.geometry_created.emit(dict(shape='rectangle' if self.tool in ('contact', 'doping') else self.tool,
                cx_um=(x0+x1)/2, cy_um=(y0+y1)/2, size_x_um=abs(x1-x0), size_y_um=abs(y1-y0), vertices=[]))
        self.drag_start = self.drag_end = None
        self.update()

    def finish_polygon(self):
        if len(self.polygon_points) >= 3:
            points = list(self.polygon_points)
            self.geometry_created.emit(dict(shape='polygon', cx_um=0., cy_um=0.,
                size_x_um=max(x for x, y in points)-min(x for x, y in points),
                size_y_um=max(y for x, y in points)-min(y for x, y in points), vertices=points))
        self.polygon_points = []
        self.update()

    def mouseDoubleClickEvent(self, event):
        if self.mode == 'top' and self.tool == 'polygon':
            self.finish_polygon()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_polygon()
        elif event.key() == Qt.Key.Key_Escape:
            self.set_tool('select')
            self.interaction_cancelled.emit()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        anchor=self.world_point(event.position()) if self.mode=='top' else None
        self.zoom = min(512., max(.2, self.zoom*1.15**(event.angleDelta().y()/120)))
        if anchor is not None:self.pan+=event.position()-self.screen_point(*anchor)
        self.update()


class CustomDevicePage(QWidget):
    """Canonical device builder with an advanced periodic optical editor."""
    continue_requested = pyqtSignal()
    status_changed = pyqtSignal(str)

    def __getattr__(self, name):
        legacy = self.__dict__.get('_legacy')
        if legacy is not None and hasattr(legacy, name):
            return getattr(legacy, name)
        raise AttributeError(name)

    def __init__(self, store, parent=None, *, include_advanced=True):
        super().__init__(parent)
        self.store = store
        self.loading = False
        self.selected_id = ''
        self.active_layer_id = ''
        self.tool = 'select'
        self.operation = 'material'
        self._history = []
        self._run_active = False
        self._legacy = None
        self._diagnostic_drafts = {}
        self._diagnostic_origin = None
        self.setProperty('deviceBuilder',True)
        self.setObjectName('customDevicePage')
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0,0,0,0)
        self.tabs = _DeviceTabs()
        self.tabs.tabBar().hide()
        self.tabs.setDocumentMode(True)
        self.layout_.addWidget(self.tabs, 1)
        self.builder = QWidget()
        self.tabs.addTab(self.builder, 'Device canvas')
        layout = QVBoxLayout(self.builder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.builder_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.builder_splitter.setChildrenCollapsible(False)
        self.builder_splitter.setHandleWidth(8)
        layout.addWidget(self.builder_splitter, 1)

        left = WorkspacePanel()
        self.tree_panel = left
        left.setObjectName('devicePanel')
        left.setMinimumWidth(200)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10,10,10,9)
        left_layout.setSpacing(7)
        header=QHBoxLayout()
        heading=_label('Device structure');heading.setObjectName('devicePanelTitle')
        header.addWidget(heading,1)
        self.tree_menu_button=QToolButton();self.tree_menu_button.setIcon(_device_icon('more'))
        self.tree_menu_button.setToolTip('Device actions')
        self.tree_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        header.addWidget(self.tree_menu_button)
        left_layout.addLayout(header)
        self.object_tree = QTreeWidget()
        self.object_tree.setHeaderHidden(True)
        self.object_tree.setColumnCount(4)
        self.object_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.object_tree.header().setMinimumSectionSize(12)
        self.object_tree.header().setStretchLastSection(False)
        self.object_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.object_tree.setColumnWidth(1, 78)
        for column,width in [(2,22),(3,18)]:
            self.object_tree.header().setSectionResizeMode(column,QHeaderView.ResizeMode.Fixed)
            self.object_tree.setColumnWidth(column,width)
        self.object_tree.setIndentation(20)
        self.object_tree.setIconSize(QSize(20,20))
        self.object_tree.setMinimumHeight(220)
        self.object_tree.setObjectName('deviceObjectTree')
        self.object_tree.currentItemChanged.connect(self.tree_selected)
        self.object_tree.itemClicked.connect(self._tree_action)
        self.object_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.object_tree.customContextMenuRequested.connect(lambda pos:self.tree_actions.exec(self.object_tree.viewport().mapToGlobal(pos)))
        left_layout.addWidget(self.object_tree, 1)
        row = QHBoxLayout();row.setSpacing(6)
        self.action_buttons={}
        for text,key,callback in [('Layer','add_layer',self.add_layer),('Shape','add_shape',lambda:self.add_shape('rectangle')),('Contact','add_contact',self.add_contact)]:
            button=_button(text,callback);button.setIcon(_device_icon('plus'));button.setObjectName('device_'+key)
            button.setMinimumWidth(0);button.setFixedHeight(40);self.action_buttons[key]=button;row.addWidget(button,1)
        left_layout.addLayout(row)
        self.tree_actions=QMenu(self.tree_menu_button)
        self.tree_menu_button.setMenu(self.tree_actions)
        self.tree_actions.addAction('Find object…',self.find_device_object)
        self.undo_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        self.undo_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.undo_shortcut.activated.connect(self.undo_device)
        for text,key,callback in [('Add doping region','add_doping',self.add_doping),('Duplicate','duplicate',self.duplicate_selected),('Delete','delete',self.delete_selected),('Move layer up','up',lambda:self.reorder_layer(-1)),('Move layer down','down',lambda:self.reorder_layer(1)),('Undo device edit','undo',self.undo_device),('Load reference device','load_reference',self.load_reference_device)]:
            button=_button(text,lambda checked=False,callback=callback:(self.tree_actions.close(),callback()))
            button.setObjectName('device_'+key);self.action_buttons[key]=button
            action=QWidgetAction(self.tree_actions);action.setDefaultWidget(button);self.tree_actions.addAction(action)
        self.action_buttons['undo'].setToolTip('Undo the last applied device edit (' + self.undo_shortcut.key().toString(QKeySequence.SequenceFormat.NativeText) + '). Text fields keep their own Undo history.')
        self.mesh_preview = QToolButton()
        self.mesh_preview.setCheckable(True)
        self.mesh_preview.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.mesh_preview.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.mesh_preview.setText('Mesh preview')
        self.mesh_preview.setIcon(_device_icon('mesh'))
        self.mesh_preview.setObjectName('deviceMeshPreview')
        self.mesh_preview.setFixedHeight(37)
        self.mesh_preview.toggled.connect(self.update_views)
        left_layout.addWidget(self.mesh_preview)
        self.builder_splitter.addWidget(left)

        center = QWidget()
        self.canvas_panel=center
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0,0,0,0)
        center_layout.setSpacing(7)
        toolbar_panel=WorkspacePanel();toolbar_panel.setObjectName('deviceToolbar')
        self.toolbar_panel=toolbar_panel
        toolbar = QHBoxLayout(toolbar_panel);toolbar.setContentsMargins(7,5,7,5);toolbar.setSpacing(3)
        self.tool_buttons = {}
        for label, tool in [('Select', 'select'), ('Move', 'move'), ('Rectangle', 'rectangle'), ('Circle', 'circle')]:
            button = self._tool_card(label,tool,lambda checked=False,tool=tool:self.set_tool(tool),True)
            self.tool_buttons[tool] = button
            toolbar.addWidget(button)
        self.tool_buttons['extrude']=self._tool_card('Extrude','extrude',self.extrude_selected)
        toolbar.addWidget(self.tool_buttons['extrude'])
        self.boolean = _combo([('Material override', 'material'), ('Void / subtract', 'void')])
        self.boolean.currentIndexChanged.connect(self.boolean_changed)
        self.boolean.hide()
        boolean_tool=self._tool_card('Boolean','boolean',lambda:None)
        boolean_menu=QMenu(boolean_tool)
        for title,value in [('Material override','material'),('Void / subtract','void')]:
            boolean_menu.addAction(title,lambda checked=False,value=value:self.boolean.setCurrentIndex(self.boolean.findData(value)))
        boolean_tool.setMenu(boolean_menu);boolean_tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar.addWidget(boolean_tool)
        contact_tool=self._tool_card('Contact','contact',lambda:self.set_tool('contact'),True)
        self.tool_buttons['contact']=contact_tool;toolbar.addWidget(contact_tool)
        self.tool_buttons['import']=self._tool_card('Import geometry','import',self.import_geometry)
        toolbar.addWidget(self.tool_buttons['import'])
        toolbar.addStretch(1)
        self.camera_choice=_combo([('Perspective','perspective'),('Orthographic','orthographic')]);self.camera_choice.setObjectName('deviceViewChoice')
        self.camera_choice.currentIndexChanged.connect(self._update_camera)
        self.camera_choice.setMinimumContentsLength(8);self.camera_choice.setMaximumWidth(122)
        toolbar.addWidget(self.camera_choice)
        self.shading_choice=_combo([('Shaded',False),('Wireframe',True)]);self.shading_choice.setObjectName('deviceViewChoice')
        self.shading_choice.setMaximumWidth(92);self.shading_choice.currentIndexChanged.connect(self._update_shading)
        toolbar.addWidget(self.shading_choice)
        self.toolbar_more=QToolButton();self.toolbar_more.setIcon(_device_icon('more'));self.toolbar_more.setToolTip('More drawing and workspace actions')
        self.toolbar_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar_menu=QMenu(self.toolbar_more);self.toolbar_more.setMenu(self.toolbar_menu)
        for label,tool in [('Ellipse','ellipse'),('Polygon','polygon'),('Square ring','square_ring')]:
            button=self._tool_card(label,tool,lambda checked=False,tool=tool:(self.toolbar_menu.close(),self.set_tool(tool)),True)
            self.tool_buttons[tool]=button
            action=QWidgetAction(self.toolbar_menu);action.setDefaultWidget(button);self.toolbar_menu.addAction(action)
        self.array_button = _button('Pattern array…', self.pattern_array)
        self.array_button.setObjectName('patternArray')
        array_action=QWidgetAction(self.toolbar_menu);array_action.setDefaultWidget(self.array_button);self.toolbar_menu.addAction(array_action)
        self.pc_area_button=_button('Fill PC area…',self.pc_area)
        self.pc_area_button.setObjectName('pcAreaFill')
        pc_action=QWidgetAction(self.toolbar_menu);pc_action.setDefaultWidget(self.pc_area_button);self.toolbar_menu.addAction(pc_action)
        self.export_button = QPushButton('Export device…')
        self.export_menu = QMenu(self.export_button)
        self.export_menu.addAction('Editable device JSON…', self.export_device)
        self.export_menu.addAction('Top-view PNG…', lambda: self.export_view('top'))
        self.export_menu.addAction('Cross-section PNG…', lambda: self.export_view('section'))
        self.export_menu.addAction('3D preview PNG…', lambda: self.export_view('3d'))
        self.export_button.setMenu(self.export_menu)
        self.export_button.hide()
        self.toolbar_menu.addMenu(self.export_menu).setText('Export device')
        self.toolbar_menu.addAction('Show device canvas',lambda:self.tabs.setCurrentIndex(0))
        self.advanced_action=self.toolbar_menu.addAction('Show advanced optical editor',lambda:self.tabs.setCurrentIndex(1))
        self.advanced_action.setEnabled(include_advanced)
        toolbar.addWidget(self.toolbar_more)
        center_layout.addWidget(toolbar_panel)
        self.views = QSplitter(Qt.Orientation.Vertical);self.views.setHandleWidth(7)
        self.upper_views = QSplitter(Qt.Orientation.Horizontal);self.upper_views.setHandleWidth(7)
        self.top_view = DeviceCanvas('top')
        self.top_view.plan_layer_mode='top'
        self.section_view = DeviceCanvas('section')
        self.view_3d = DeviceCanvas('3d')
        self.view_3d.depth_display_mode='film'
        self.cut_y = number(0., -1e6, 1e6, 6)
        self.cut_y.valueChanged.connect(self.update_views)
        self.upper_views.addWidget(self._canvas_card(self.top_view,'Top view · XY'))
        self.upper_views.addWidget(self._canvas_card(self.section_view,'Cross section · XZ (A–A)'))
        self.upper_views.setChildrenCollapsible(False)
        self.views.addWidget(self.upper_views)
        self.views.addWidget(self._canvas_card(self.view_3d,'3D preview'))
        self.views.setSizes([282,265]);self.views.setChildrenCollapsible(False)
        center_layout.addWidget(self.views,1)
        self.pick_face_button = _button('Pick contact surface', self.pick_contact_surface)
        self.pick_face_button.setIcon(_device_icon('select'))
        self.library_panel=WorkspacePanel();self.library_panel.setObjectName('deviceLibrary')
        library_layout=QVBoxLayout(self.library_panel);library_layout.setContentsMargins(10,8,10,9);library_layout.setSpacing(8)
        library_header=QHBoxLayout();library_header.setSpacing(8)
        library_title=_label('Material library');library_title.setObjectName('devicePanelTitle');library_header.addWidget(library_title)
        self.material_search=QLineEdit();self.material_search.setPlaceholderText('Search materials…');self.material_search.textChanged.connect(self.rebuild_library)
        self.material_search.addAction(_device_icon('search'),QLineEdit.ActionPosition.LeadingPosition)
        library_header.addWidget(self.material_search,1)
        self.library_edit_button=_button('Edit properties…',self.edit_selected_material)
        self.library_import_button=_button('Import material',self.manage_materials)
        library_header.addWidget(self.library_edit_button);library_header.addWidget(self.library_import_button)
        self.library_more=QToolButton();self.library_more.setIcon(_device_icon('more'));self.library_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        library_menu=QMenu(self.library_more);library_menu.addAction('Edit material properties…',self.edit_selected_material);library_menu.addAction('Import / manage materials…',self.manage_materials)
        self.library_more.setMenu(library_menu);library_header.addWidget(self.library_more);self.library_more.hide()
        library_layout.addLayout(library_header)
        self.library_scroll=QScrollArea();self.library_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.library_scroll.setWidgetResizable(True);self.library_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.library_host=QWidget();self.library_host.setMinimumWidth(680)
        self.library_layout=QHBoxLayout(self.library_host);self.library_layout.setContentsMargins(0,0,0,0);self.library_layout.setSpacing(10)
        self.library_scroll.setWidget(self.library_host);library_layout.addWidget(self.library_scroll,1)
        self.library_buttons = []
        self.library_panel.setFixedHeight(193)
        center_layout.addWidget(self.library_panel)
        self.builder_splitter.addWidget(center)

        right = WorkspacePanel()
        right.setObjectName('devicePanel')
        right.setMinimumWidth(280)
        self.inspector_panel=right
        inspector = QVBoxLayout(right)
        inspector.setContentsMargins(12,12,12,10);inspector.setSpacing(9)
        selected_header=QHBoxLayout();selected_header.setSpacing(10)
        self.selection_swatch=QLabel();self.selection_swatch.setFixedSize(28,28)
        selected_header.addWidget(self.selection_swatch)
        self.selection_label = _label('Device outline')
        self.selection_label.setObjectName('devicePanelTitle')
        selected_header.addWidget(self.selection_label,1)
        inspector.addLayout(selected_header)
        self.inspector_tabs = QTabWidget()
        inspector.addWidget(self.inspector_tabs, 1)
        geometry = QWidget()
        electrical = QWidget()
        optical=QWidget()
        for content in (geometry,electrical,optical):content.setObjectName('deviceInspectorContent')
        geometry_layout = QVBoxLayout(geometry)
        electrical_layout = QVBoxLayout(electrical)
        optical_layout=QVBoxLayout(optical)
        for panel_layout in (geometry_layout,electrical_layout,optical_layout):
            panel_layout.setContentsMargins(0,4,0,4);panel_layout.setSpacing(13)
        self.inspector_tabs.addTab(_scroll(geometry), 'Geometry')
        self.inspector_tabs.addTab(_scroll(electrical), 'Electrical')
        self.inspector_tabs.addTab(_scroll(optical),'Optical')
        self.name_edit = QLineEdit()
        self.enabled_edit = QCheckBox('Enabled')
        self.material_edit = _combo([])
        self.layer_edit = _combo([])
        common, common_form = _group('Selected object', [('Name', self.name_edit), ('Material', self.material_edit), ('Layer', self.layer_edit)])
        self.common_form = common_form
        common_form.addRow(self.enabled_edit)
        geometry_layout.addWidget(common)
        self.common_group = common
        self.edit_pc_area_button=_button('Edit PC area / refill holes…',lambda:self.pc_area(self.selected_id))
        self.common_form.addRow(self.edit_pc_area_button)
        self.device_controls = {'width_um': number(2, 1e-6, 1e6), 'depth_um': number(2, 1e-6, 1e6), 'temperature_K': number(300, 50, 1500, 3)}
        self.device_group, _ = _group('Finite device', [('Width x (µm)', self.device_controls['width_um']), ('Depth y (µm)', self.device_controls['depth_um']), ('Temperature (K)', self.device_controls['temperature_K'])])
        geometry_layout.addWidget(self.device_group)
        self.thickness_edit = number(.1, 1e-6, 1e6, 6)
        self.layer_group, _ = _group('Layer', [('Thickness (µm)', self.thickness_edit)])
        geometry_layout.addWidget(self.layer_group)
        self.shape_edit = _combo([('Rectangle', 'rectangle'), ('Circle', 'circle'), ('Ellipse', 'ellipse'),
            ('Polygon', 'polygon'), ('Square ring', 'square_ring')])
        self.geometry_controls = {key: number(value, 1e-6 if key.startswith('size') else -1e6, 1e6, 6) for key, value in
            [('cx_um', 0.), ('cy_um', 0.), ('size_x_um', .5), ('size_y_um', .5), ('angle_deg', 0.)]}
        self.shape_group, form = _group('Geometry (placement)', [('Shape', self.shape_edit)] + [(label, self.geometry_controls[key]) for label, key in
            [('Center x (µm)', 'cx_um'), ('Center y (µm)', 'cy_um'), ('Full width / diameter (µm)', 'size_x_um'), ('Full depth (µm)', 'size_y_um'), ('Rotation (degrees)', 'angle_deg')]])
        self.shape_form = form
        self.geometry_controls['size_x_um'].valueChanged.connect(self.update_shape_fields)
        self.inner_controls = {'inner_size_x_um': number(.25, 1e-6, 1e6, 6), 'inner_size_y_um': number(.25, 1e-6, 1e6, 6)}
        for key, label in [('inner_size_x_um', 'Inner width (µm)'), ('inner_size_y_um', 'Inner depth (µm)')]:
            form.addRow(label, self.inner_controls[key])
        self.operation_edit = _combo([('Material override', 'material'), ('Void / subtract', 'void')])
        form.addRow('Operation', self.operation_edit)
        self.vertices_edit = QPlainTextEdit()
        self.vertices_edit.setPlaceholderText('Polygon vertices as [[x,y], [x,y], …] in µm')
        self.vertices_edit.setMaximumHeight(115)
        form.addRow('Polygon vertices', self.vertices_edit)
        geometry_layout.addWidget(self.shape_group)
        self.contact_position_controls={key:number(0. if key.startswith('c') else .5,-1e6 if key.startswith('c') else 1e-6,1e6,6)
            for key in ('cx_um','cy_um','size_x_um','size_y_um')}
        self.contact_surface_z=number(0.,-1e6,1e6,6);self.contact_surface_z.setReadOnly(True)
        self.contact_surface_z.setButtonSymbols(self.contact_surface_z.ButtonSymbols.NoButtons)
        self.contact_surface_z.setToolTip('Depth of the assigned electrical boundary; change the assigned surface to move it.')
        self.contact_position_group,_=_group('Geometry (placement)',[(label,self.contact_position_controls[key]) for label,key in
            [('Position X (µm)','cx_um'),('Position Y (µm)','cy_um')]]+[('Position Z (µm)',self.contact_surface_z)])
        self.contact_height_edit=number(0.,0.,1e6,6)
        self.contact_height_edit.setToolTip('Optional optical metal thickness. The electrical terminal remains an ideal surface boundary.')
        self.contact_dimensions_group,_=_group('Dimensions (µm)',[
            ('Width Y',self.contact_position_controls['size_y_um']),('Length X',self.contact_position_controls['size_x_um']),('Metal height Z',self.contact_height_edit)])
        for key,control in self.contact_position_controls.items():
            control.valueChanged.connect(self.geometry_controls[key].setValue)
            self.geometry_controls[key].valueChanged.connect(control.setValue)
        electrical_layout.addWidget(self.contact_position_group)
        electrical_layout.addWidget(self.contact_dimensions_group)
        self.contact_controls = {'surface': _combo([('Top surface', 'top'), ('Bottom surface', 'bottom'),
            ('X− side', 'side_x_min'), ('X+ side', 'side_x_max'), ('Y− side', 'side_y_min'), ('Y+ side', 'side_y_max')]),
            'boundary': _combo([('Ohmic reservoir', 'ohmic'), ('Fixed potential', 'potential')]), 'voltage_V': number(0, -1e300, 1e300, 6)}
        self.contact_group, contact_form = _group('Contact properties', [(label, self.contact_controls[key]) for label, key in
            [('Boundary type', 'boundary'), ('Applied voltage (V)', 'voltage_V'),('Assign surface', 'surface')]])
        self.contact_terminal_name=QLineEdit()
        self.contact_terminal_name.textEdited.connect(self.name_edit.setText)
        self.name_edit.textEdited.connect(self.contact_terminal_name.setText)
        contact_form.insertRow(1,'Terminal name',self.contact_terminal_name)
        contact_form.addRow(self.pick_face_button)
        contact_form.addRow(_label('Choose the swept terminal and bias range on the Electrical simulation page.'))
        electrical_layout.addWidget(self.contact_group)
        self.optical_contact_controls = {
            'material': _combo([('None', '')]),
            'thickness': number(0., 0., 1e6, 6),
        }
        self.contact_height_edit.valueChanged.connect(self.optical_contact_controls['thickness'].setValue)
        self.optical_contact_controls['thickness'].valueChanged.connect(self.contact_height_edit.setValue)
        self.optical_contact_group, optical_contact_form = _group('Optical contact metal', [
            ('Optical material', self.optical_contact_controls['material']),
            ('Metal thickness (µm)', self.optical_contact_controls['thickness']),
        ])
        self.optical_contact_group.setToolTip('Optical contact metal (optional)')
        optical_contact_form.addRow(_label('Optional: a positive thickness adds an optical scattering pad on the exposed top or bottom face. The electrical terminal remains an ideal boundary.'))
        optical_layout.addWidget(self.optical_contact_group)
        self.optical_assignment=_combo([('Automatic from electrical material','')])
        self.optical_assignment_group,optical_assignment_form=_group('Optical material assignment',[('Background material',self.optical_assignment)])
        optical_layout.addWidget(self.optical_assignment_group)
        optical_assignment_form.addRow(_label("Layers and material regions can override optical n/k. Changing their electrical material clears that override. Set Optical material link in the electrical material record to keep the pair associated; Automatic uses that link. Void regions remain air."))
        advanced_button=_button('Open periodic optical editor',lambda:self.tabs.setCurrentIndex(1))
        advanced_button.setEnabled(include_advanced)
        optical_layout.addWidget(advanced_button)
        self.donor_edit = QLineEdit('0')
        self.acceptor_edit = QLineEdit('0')
        self.doping_group, _ = _group('Uniform doping', [('Donors (cm⁻³)', self.donor_edit), ('Acceptors (cm⁻³)', self.acceptor_edit)])
        electrical_layout.addWidget(self.doping_group)
        from electrical_mesh import MESH_AXIS_MAX
        self.mesh_controls = {'nx': integer(16, 2, MESH_AXIS_MAX), 'ny': integer(16, 2, MESH_AXIS_MAX),
            'nz_per_layer': integer(8, 2, MESH_AXIS_MAX), 'max_nodes': integer(0, 0, MESH_AXIS_MAX)}
        self.mesh_controls['max_nodes'].setSpecialValueText('Automatic (RAM budget)')
        self.mesh_controls['max_nodes'].setToolTip('0 uses the automatic available-RAM budget. A positive value preserves an explicit cell limit; RAM is still checked before allocation.')
        self.mesh_group, mesh_form = _group('Structured mesh', [('X cells', self.mesh_controls['nx']), ('Y cells', self.mesh_controls['ny']),
            ('Depth cells / layer', self.mesh_controls['nz_per_layer']), ('Cell budget', self.mesh_controls['max_nodes'])])
        self.mesh_resource_note=_label('');self.mesh_resource_note.setWordWrap(True)
        mesh_form.addRow(self.mesh_resource_note)
        for widget in self.mesh_controls.values():widget.valueChanged.connect(self.update_mesh_resources)
        electrical_layout.addWidget(self.mesh_group)
        self.material_note = _label('')
        self.material_properties_group=QGroupBox('Material properties')
        properties_layout=QVBoxLayout(self.material_properties_group);properties_layout.setContentsMargins(8,13,8,8)
        properties_layout.addWidget(self.material_note)
        self.electrical_model_note = _label('Set material properties, contacts and doping here. For electrical studies, choose the electrostatic or current-transport model in Bias & physics. Doping is uniform within each layer or shaped region.')
        electrical_layout.addWidget(self.electrical_model_note)
        geometry_layout.addStretch()
        electrical_layout.addStretch()
        optical_layout.addStretch()
        self.apply_button = _button('Apply selected object', self.apply_inspector, True)
        inspector.addWidget(self.apply_button)
        self.edit_material_button = _button('Edit electrical material…', self.edit_selected_material)
        properties_layout.addWidget(self.edit_material_button)
        inspector.addWidget(self.material_properties_group)
        doping_button=_button('Edit doping regions…',self.edit_doping_regions);doping_button.setIcon(_device_icon('doping','#75e679'))
        inspector.addWidget(doping_button)
        self.toolbar_menu.addAction('Validate device',self.validate_current)
        self.toolbar_menu.addAction('Continue to simulation',lambda:self.continue_requested.emit())
        self.toolbar_menu.addAction('Extrude selected shape…',self.extrude_selected)
        self.toolbar_menu.addAction('Import geometry / device…',self.import_geometry)
        self.builder_splitter.addWidget(right)
        self.builder_splitter.setStretchFactor(1, 1)
        self.builder_splitter.setSizes([286,920,346])
        self.status = _BuilderStatus('Select an object, edit its properties, or draw in the top view.')
        self.status.text_changed.connect(self.status_changed)
        self.status.hide()

        if include_advanced:
            from qt_device_builder import DeviceBuilderPage
            self._legacy = DeviceBuilderPage(store)
            self._legacy.continue_requested.connect(self.continue_requested)
            self.tabs.addTab(self._legacy, 'Advanced periodic optical editor')
            legacy_menu = self._legacy.export_button.menu()
            if legacy_menu is not None:
                optical_export = self.export_menu.addMenu('Periodic optical model')
                for action in legacy_menu.actions():
                    optical_export.addAction(action)
        self.advanced_return=_button('← Simulation device canvas',lambda:self.tabs.setCurrentIndex(0))
        self.advanced_return.hide();self.layout_.insertWidget(0,self.advanced_return)
        self.tabs.currentChanged.connect(lambda index:self.advanced_return.setVisible(index>0))
        for canvas in (self.top_view, self.section_view, self.view_3d):
            canvas.object_selected.connect(self.select_object)
            canvas.surface_picked.connect(self.assign_contact_surface)
            canvas.interaction_cancelled.connect(lambda: self.set_tool('select'))
        self.top_view.geometry_created.connect(self.geometry_created)
        self.top_view.object_moved.connect(self.move_object)
        self.shape_edit.currentIndexChanged.connect(self.update_shape_fields)
        self.store.changed.connect(self.refresh)
        if hasattr(store, 'progress'):
            store.progress.connect(self._run_progress)
        if hasattr(store, 'run_finished'):
            store.run_finished.connect(self._run_finished)
        if hasattr(store, 'run_failed'):
            store.run_failed.connect(self._run_failed)
        self.refresh()
        self.set_tool('select')
        theme_manager().changed.connect(self._apply_reference_style)
        self._apply_reference_style()
        for selector in self.builder.findChildren(QComboBox):
            selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            selector.setMinimumContentsLength(7)

    def _tool_card(self,text,icon,callback,checkable=False):
        button=QToolButton()
        button.setText(text);button.setIcon(_device_icon(icon))
        button.setIconSize(QSize(22,22));button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setCheckable(checkable);button.setObjectName('deviceToolCard')
        button.setFixedHeight(54);button.setMinimumWidth(54)
        button.clicked.connect(callback)
        return button

    def _canvas_card(self,canvas,title):
        card=WorkspacePanel();card.setObjectName('deviceCanvasCard')
        layout=QVBoxLayout(card);layout.setContentsMargins(1,1,1,1);layout.setSpacing(0)
        header=QWidget();header.setObjectName('deviceCanvasHeader');header.setFixedHeight(35)
        row=QHBoxLayout(header);row.setContentsMargins(12,0,7,0);row.setSpacing(7)
        heading=_label(title);heading.setObjectName('deviceCanvasTitle');row.addWidget(heading,1)
        if canvas.mode=='3d':
            for icon,tip,mode in [('orbit','Rotate view','rotate'),('move','Pan view','pan')]:
                button=QToolButton();button.setIcon(_device_icon(icon));button.setToolTip(tip)
                button.clicked.connect(lambda checked=False,mode=mode:self._navigate_canvas(canvas,mode));row.addWidget(button)
        for icon,tip,callback in [('zoom','Zoom in',lambda: self._zoom_canvas(canvas,1.2)),('zoom_out','Zoom out',lambda:self._zoom_canvas(canvas,1/1.2)),('fit','Fit view',lambda:self._fit_canvas(canvas))]:
            button=QToolButton();button.setIcon(_device_icon(icon));button.setToolTip(tip);button.clicked.connect(callback);row.addWidget(button)
        more=QToolButton();more.setIcon(_device_icon('more'));more.setToolTip('View options')
        menu=QMenu(more);more.setMenu(menu);more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu.addAction('Export view PNG…',lambda:self.export_view(canvas.mode))
        if canvas.mode=='section':
            item=QWidgetAction(menu);host=QWidget();fields=QHBoxLayout(host)
            fields.addWidget(_label('Section y (µm)'));fields.addWidget(self.cut_y);item.setDefaultWidget(host);menu.addAction(item)
        if canvas.mode=='top':
            menu.addAction('Show top surface',lambda:self._set_plan_layer('top'))
            menu.addAction('Show selected layer',lambda:self._set_plan_layer('selected'))
        if canvas.mode=='3d':
            menu.addAction('Reset rotation',self._reset_camera)
            menu.addAction('Enlarge 3D preview',self._enlarge_preview)
            menu.addAction('Fit thin-film display proportions',lambda:self._set_depth_display('film'))
            menu.addAction('Use equal physical axis scales',lambda:self._set_depth_display('physical'))
            menu.addSeparator()
            studio=menu.addAction('Studio lighting')
            studio.setCheckable(True);studio.setChecked(canvas.render_quality=='studio')
            studio.toggled.connect(lambda enabled:canvas.set_render_quality('studio' if enabled else 'flat'))
            for label,attribute,option in [('Soft shadows','show_shadows','shadows'),
                    ('Surface reflections','show_reflections','reflections'),
                    ('Hole and edge shading','show_ambient_occlusion','ambient_occlusion')]:
                action=menu.addAction(label);action.setCheckable(True);action.setChecked(getattr(canvas,attribute))
                action.toggled.connect(lambda enabled,option=option:canvas.set_render_quality(canvas.render_quality,**{option:enabled}))
        row.addWidget(more);layout.addWidget(header)
        canvas.headered=True;layout.addWidget(canvas,1)
        return card

    def _zoom_canvas(self,canvas,factor):
        canvas.zoom=min(512.,max(.2,canvas.zoom*factor));canvas.update()

    def _set_plan_layer(self,mode):
        self.top_view.plan_layer_mode=mode;self.top_view.update()

    def _set_depth_display(self,mode):
        self.view_3d.depth_display_mode=mode;self.view_3d.update()

    def _fit_canvas(self,canvas):
        canvas.zoom=1.;canvas.pan=QPointF(0,0);canvas.update()

    def _navigate_canvas(self,canvas,mode):
        canvas.navigation_mode=mode
        canvas.setCursor(Qt.CursorShape.OpenHandCursor if mode=='pan' else Qt.CursorShape.ArrowCursor)

    def _reset_camera(self):
        self.view_3d.yaw=-.6;self.view_3d.elevation=.48;self._fit_canvas(self.view_3d)

    def _enlarge_preview(self):
        enlarged=self.upper_views.isVisible()
        self.upper_views.setVisible(not enlarged);self.library_panel.setVisible(not enlarged)

    def _update_shading(self,*_):
        if hasattr(self,'view_3d'):
            self.view_3d.wireframe=bool(self.shading_choice.currentData());self.view_3d.update()

    def _update_camera(self,*_):
        if hasattr(self,'view_3d'):
            self.view_3d.perspective=self.camera_choice.currentData()=='perspective';self.view_3d.update()

    def _tree_action(self,item,column):
        object_id=item.data(0,Qt.ItemDataRole.UserRole)
        if not object_id:return
        if column==2 and object_id not in ('device','mesh'):
            device=self._current_device();obj=_model_api().find_object(device,object_id)
            if obj:
                obj['enabled']=not obj.get('enabled',True)
                if self._kind(object_id)=='pc_arrays':
                    for shape in device['shapes']:
                        if shape.get('pc_array_id')==object_id:shape['enabled']=obj['enabled']
                self._commit(device,object_id)
        elif column==3:
            self.select_object(object_id);self.tree_actions.popup(self.object_tree.viewport().mapToGlobal(self.object_tree.visualItemRect(item).topRight()))

    def edit_doping_regions(self):
        candidates=[obj for obj in self._current_device()['doping_regions'] if obj['layer_id']==self.active_layer_id]
        if candidates:
            self.select_object(candidates[0]['id']);self.inspector_tabs.setCurrentIndex(1)
        else:self.add_doping()

    def _apply_reference_style(self,*_):
        c=COLORS[theme_manager().mode];dark=theme_manager().mode=='dark'
        panel='#132330' if dark else c['panel'];field='#0d1d29' if dark else c['field']
        edge='#29465b' if dark else c['border'];text='#dbe8f5' if dark else c['text']
        muted='#aac0d4' if dark else c['muted'];accent='#20a8ff' if dark else c['accent']
        stylesheet=f'''
            QWidget#customDevicePage {{ font-size:13px; color:{text}; }}
            QWidget#customDevicePage QTabWidget::pane {{ border:0; background:transparent; }}
            QWidget#customDevicePage QSplitter::handle {{ background:transparent; }}
            QWidget#customDevicePage QFrame#devicePanel, QWidget#customDevicePage QFrame#deviceToolbar,
            QWidget#customDevicePage QFrame#deviceCanvasCard, QWidget#customDevicePage QFrame#deviceLibrary {{
                border:1px solid {edge}; border-radius:5px; background:transparent; }}
            QWidget#customDevicePage QLabel#devicePanelTitle {{ font-size:14px; font-weight:600; }}
            QWidget#customDevicePage QLabel#deviceCanvasTitle {{ font-size:13px; font-weight:600; }}
            QWidget#customDevicePage QWidget#deviceCanvasHeader {{ background:{panel}; border-bottom:1px solid {edge}; }}
            QWidget#customDevicePage QToolButton {{ background:transparent; border:1px solid transparent; padding:3px; color:{text}; }}
            QWidget#customDevicePage QToolButton:hover {{ border-color:{edge}; background:{field}; }}
            QWidget#customDevicePage QToolButton#deviceToolCard {{ font-size:11px; padding:3px 5px; border-radius:3px; }}
            QWidget#customDevicePage QToolButton#deviceToolCard:checked {{ border:1px solid {accent}; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #173e60,stop:1 #102b47); }}
            QWidget#customDevicePage QPushButton {{ min-height:24px; padding:4px 9px; font-size:12px; border:1px solid {edge}; border-radius:4px; background:{panel}; color:{text}; }}
            QWidget#customDevicePage QPushButton:hover {{ background:{field}; border-color:{accent}; }}
            QWidget#customDevicePage QPushButton[primary="true"] {{ background:#125da4; border-color:{accent}; }}
            QWidget#customDevicePage QTreeWidget {{ border:0; background:transparent; font-size:13px; outline:0; }}
            QWidget#customDevicePage QTreeWidget::item {{ height:30px; border:0; padding:0 2px; }}
            QWidget#customDevicePage QTreeWidget::item:selected {{ background:#154571; border-radius:4px; }}
            QWidget#customDevicePage QToolButton#deviceMeshPreview {{ min-height:30px; padding:3px 8px; border:1px solid {edge}; border-radius:4px; }}
            QWidget#customDevicePage QToolButton#deviceMeshPreview:checked {{ border-color:{accent}; background:#153958; }}
            QWidget#customDevicePage QGroupBox {{ background:transparent; border:0; border-top:1px solid {edge}; border-radius:0; margin-top:20px; padding:7px 0 0; font-weight:600; }}
            QWidget#customDevicePage QGroupBox::title {{ subcontrol-origin:margin; subcontrol-position:top left; padding:0 0 2px; }}
            QWidget#customDevicePage QGroupBox QLabel {{ font-weight:400; color:{muted}; }}
            QWidget#customDevicePage QScrollArea {{ border:0; background:transparent; }}
            QWidget#customDevicePage QWidget#qt_scrollarea_viewport,
            QWidget#customDevicePage QWidget#deviceInspectorContent {{ background:{panel}; }}
            QWidget#customDevicePage QLineEdit, QWidget#customDevicePage QSpinBox,
            QWidget#customDevicePage QDoubleSpinBox, QWidget#customDevicePage QComboBox {{ min-height:24px; padding:2px 7px; background:{field}; border:1px solid {edge}; border-radius:3px; font-size:12px; }}
            QWidget#customDevicePage QTabBar::tab {{ min-width:67px; padding:8px 10px; margin:0 2px 0 0; border:1px solid {edge}; border-radius:3px; background:{panel}; font-size:12px; }}
            QWidget#customDevicePage QTabBar::tab:selected {{ border-color:{accent}; background:#153958; }}
            QWidget#customDevicePage QFrame#deviceMaterialCard {{ border:1px solid {edge}; border-radius:5px; background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #22384b,stop:1 #132431); }}
            QWidget#customDevicePage QLabel#materialCardTitle {{ font-size:13px; color:{text}; font-weight:500; }}
            QWidget#customDevicePage QLabel#materialCardNote {{ font-size:11px; color:{muted}; }}
            QWidget#customDevicePage QPushButton#materialCardEdit {{ font-size:12px; background:transparent; }}
            QWidget#customDevicePage QToolButton#deviceCustomMaterial {{ border:1px dashed #507b99; border-radius:5px; color:{accent}; font-size:12px; }}
        '''
        self.setStyleSheet(stylesheet.replace('QWidget#customDevicePage','QWidget[deviceBuilder="true"]'))
        self._configure_reference_forms()

    def _configure_reference_forms(self):
        for form in self.builder.findChildren(QFormLayout):
            form.setContentsMargins(0,10,0,0)
            form.setVerticalSpacing(4);form.setHorizontalSpacing(8)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'builder') and not getattr(self,'_reference_forms_pending',False):
            self._reference_forms_pending=True
            QTimer.singleShot(0,self._settle_reference_forms)

    def _settle_reference_forms(self):
        self._reference_forms_pending=False
        self._configure_reference_forms()
        narrow=self.canvas_panel.width()<680
        self.camera_choice.setVisible(not narrow);self.shading_choice.setVisible(not narrow)
        for name in ('extrude','import'):
            if name in self.tool_buttons:self.tool_buttons[name].setVisible(not narrow)
        self.library_edit_button.setVisible(not narrow);self.library_import_button.setVisible(not narrow);self.library_more.setVisible(narrow)
        self.object_tree.setColumnWidth(1,0 if self.tree_panel.width()<240 else 78)
        self.inspector_tabs.tabBar().setStyleSheet('QTabBar::tab { min-width:58px; padding:8px 6px; }' if self.inspector_panel.width()<310 else '')
        height=max(105,min(135,self.library_scroll.viewport().height()))
        for card in self.library_buttons:card.setFixedHeight(height)

    def _device_ref(self):
        device = getattr(self.store, 'device', None)
        return device if isinstance(device, dict) else _model_api().default_device(getattr(self.store, 'electrical_materials', None))

    def _current_device(self):
        return copy.deepcopy(self._device_ref())

    def _kind(self, object_id=None):
        object_id = self.selected_id if object_id is None else object_id
        if object_id in ('device', 'mesh'):
            return object_id
        if object_id in getattr(self,'_object_kinds',{}):return self._object_kinds[object_id]
        for kind in ('layers', 'shapes', 'contacts', 'doping_regions','pc_arrays'):
            if any(obj['id'] == object_id for obj in self._device_ref().get(kind, [])):
                return kind
        return 'device'

    def selected_object(self):
        return copy.deepcopy(_model_api().find_object(self._device_ref(), self.selected_id))

    def _commit(self, device, selected=None, message='Device updated.'):
        busy=len(device.get('shapes',[]))>5000
        if busy:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtGui import QCursor
            self.status.setText(f'Updating {len(device["shapes"]):,} editable shapes and the shared optical project…')
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor));QApplication.processEvents()
        try:
            previous = self._device_ref()
            validated = _model_api().validate_device(device, self.store.electrical_materials)
            self.selected_id = selected if selected is not None else self.selected_id
            if validated != previous:
                self.store.set_device(validated)
                if not callable(getattr(self.store,'undo',None)):
                    self._history.append(previous)
                    self._history = self._history[-40:]
            self.refresh()
            self.status.setText(message)
            return True
        except Exception as exc:
            self.status.setText(str(exc))
            return False
        finally:
            if busy:QApplication.restoreOverrideCursor()

    def refresh(self, *_):
        if self.loading:
            return
        if _ and _[0] == 'project':
            self._diagnostic_drafts.clear()
            self._diagnostic_origin = None
        self.loading = True
        try:
            device = self._device_ref()
            self._object_kinds={obj['id']:kind for kind in ('layers','shapes','contacts','doping_regions','pc_arrays') for obj in device.get(kind,[])}
            valid_ids = {'device', 'mesh'} | self._object_kinds.keys()
            if self.selected_id not in valid_ids:
                self.selected_id = device['layers'][0]['id'] if device['layers'] else 'device'
            selected = _model_api().find_object(device, self.selected_id)
            if selected:
                self.active_layer_id = selected['id'] if self._kind() == 'layers' else selected.get('layer_id', self.active_layer_id)
            if self.active_layer_id not in {layer['id'] for layer in device['layers']}:
                self.active_layer_id = device['layers'][0]['id'] if device['layers'] else ''
            self.object_tree.clear()
            root = QTreeWidgetItem([device.get('name', 'Device outline')])
            root.setText(0,'Device outline')
            root.setIcon(0,_device_icon('device'))
            root.setData(0, Qt.ItemDataRole.UserRole, 'device')
            self.object_tree.addTopLevelItem(root)
            root.setFirstColumnSpanned(True)
            chosen = root if self.selected_id == 'device' else None
            groups=[('layers', 'Layers'), ('shapes', 'Shapes'), ('contacts', 'Contacts'), ('doping_regions', 'Doping regions')]
            if device.get('pc_arrays'):groups.insert(2,('pc_arrays','PC areas'))
            self.tree_listed_count=0
            for kind, title in groups:
                objects=device.get(kind,[])
                group = QTreeWidgetItem([title+ (f' · {len(objects):,}' if len(objects)>600 else '')])
                group.setIcon(0,_device_icon('layer' if kind=='layers' else 'doping' if kind=='doping_regions' else 'contact' if kind=='contacts' else 'boolean', '#72df6a' if kind=='doping_regions' else '#cfdeeb'))
                self.object_tree.addTopLevelItem(group)
                group.setFirstColumnSpanned(True)
                listed=objects[:600]
                selected_row=selected if self._kind()==kind else None
                if selected_row and selected_row not in listed:listed=listed+[selected_row]
                for obj in listed:
                    text = obj['name'] + (' · disabled' if not obj.get('enabled', True) else '')
                    detail = f"{obj['thickness_um']*1000:g} nm" if kind == 'layers' else ''
                    if kind == 'contacts' and obj.get('optical_thickness_um', 0) > 0:
                        detail = f"{obj.get('optical_material_name') or 'No optical material'} · {obj['optical_thickness_um']*1000:g} nm"
                    if kind=='pc_arrays':detail=f"{obj['nx']} × {obj['ny']}"
                    item = QTreeWidgetItem([text, detail])
                    swatch=_layer_color(obj) if kind=='layers' else _contact_color(obj) if kind=='contacts' else '#65db9f' if kind=='doping_regions' else _color(obj.get('material_id'))
                    item.setIcon(0,_device_icon('cube',swatch))
                    item.setIcon(2,_device_icon('eye','#cfdeeb' if obj.get('enabled',True) else '#536978'))
                    item.setIcon(3,_device_icon('more'))
                    item.setToolTip(1,detail)
                    item.setData(0, Qt.ItemDataRole.UserRole, obj['id'])
                    item.setToolTip(0, text)
                    group.addChild(item)
                    self.tree_listed_count+=1
                    if obj['id'] == self.selected_id:
                        chosen = item
                if len(objects)>len(listed):
                    more=QTreeWidgetItem([f'{len(objects)-len(listed):,} more · Find object…'])
                    more.setData(0,Qt.ItemDataRole.UserRole,'__find__');group.addChild(more)
                    more.setFirstColumnSpanned(True)
                group.setExpanded(True)
            mesh = QTreeWidgetItem(['Mesh'])
            mesh.setIcon(0,_device_icon('mesh'))
            mesh.setData(0, Qt.ItemDataRole.UserRole, 'mesh')
            self.object_tree.addTopLevelItem(mesh)
            mesh.setFirstColumnSpanned(True)
            if self.selected_id == 'mesh':
                chosen = mesh
            self.object_tree.setCurrentItem(chosen)
            self._load_inspector(device, selected)
            self.rebuild_library()
            self.update_views()
        finally:
            self.loading = False

    def _load_inspector(self, device, selected):
        kind = self._kind()
        obj = device if kind == 'device' else device['mesh'] if kind == 'mesh' else selected or {}
        self.selection_label.setText('Selected object · '+('Mesh' if kind == 'mesh' else obj.get('name', 'Device outline')))
        swatch=_layer_color(obj) if kind=='layers' else _contact_color(obj) if kind=='contacts' else '#41bfff'
        self.selection_swatch.setPixmap(_device_icon('cube',swatch).pixmap(28,28))
        _set_value(self.name_edit, obj.get('name', device.get('name', 'Device')))
        self.name_edit.setEnabled(kind != 'mesh')
        _set_value(self.enabled_edit, obj.get('enabled', True))
        self.enabled_edit.setEnabled(kind not in ('device', 'mesh'))
        materials = [(entry['name'], entry['id']) for entry in self.store.electrical_materials]
        material_id=obj.get('material_id','')
        if kind in ('layers','shapes') and material_id not in {value for _,value in materials}:
            # Optical imports can intentionally have no electrical material.
            # Display that exact assignment instead of silently selecting the
            # first library material, which would erase the optical override on Apply.
            caption=(str(material_id)+' (missing electrical material)') if material_id else 'No electrical material assigned'
            materials.insert(0,(caption,material_id))
        _choices(self.material_edit, materials, material_id)
        _choices(self.layer_edit, [(layer['name'], layer['id']) for layer in device['layers']], obj.get('layer_id', self.active_layer_id))
        self.material_edit.setEnabled(kind in ('layers', 'shapes'))
        self.layer_edit.setEnabled(kind in ('shapes', 'contacts', 'doping_regions','pc_arrays'))
        self.material_edit.setVisible(kind in ('layers', 'shapes'))
        self.common_form.labelForField(self.material_edit).setVisible(kind in ('layers', 'shapes'))
        self.layer_edit.setVisible(kind in ('shapes', 'contacts', 'doping_regions','pc_arrays'))
        self.common_form.labelForField(self.layer_edit).setVisible(kind in ('shapes', 'contacts', 'doping_regions','pc_arrays'))
        self.edit_pc_area_button.setVisible(kind=='pc_arrays')
        self.common_group.setVisible(kind != 'mesh')
        self.edit_material_button.setEnabled(kind in ('layers', 'shapes','contacts'))
        self.device_group.setVisible(kind == 'device')
        self.layer_group.setVisible(kind == 'layers')
        self.shape_group.setVisible(kind in ('shapes', 'contacts', 'doping_regions'))
        self.contact_group.setVisible(kind == 'contacts')
        self.contact_position_group.setVisible(kind=='contacts')
        self.contact_dimensions_group.setVisible(kind=='contacts')
        self.optical_contact_group.setVisible(kind == 'contacts')
        self.optical_assignment_group.setVisible(kind in ('layers','shapes'))
        self.doping_group.setVisible(kind in ('layers', 'doping_regions'))
        self.mesh_group.setVisible(kind == 'mesh')
        for key, widget in self.device_controls.items():
            _set_value(widget, device[key])
        _set_value(self.thickness_edit, obj.get('thickness_um', .1))
        _set_value(self.shape_edit, obj.get('shape', 'rectangle'))
        for key, widget in self.geometry_controls.items():
            _set_value(widget, obj.get(key, 0 if key in ('cx_um', 'cy_um', 'angle_deg') else .5))
        for key,widget in self.contact_position_controls.items():
            _set_value(widget,self.geometry_controls[key].value())
        _set_value(self.contact_terminal_name,obj.get('name',''))
        bounds=next((layer for layer in _model_api().layer_bounds(device) if layer['id']==obj.get('layer_id')),None)
        surface=obj.get('surface','top')
        boundary_z=(bounds['z_max_um'] if surface=='bottom' else (bounds['z_min_um']+bounds['z_max_um'])/2 if surface.startswith('side_') else bounds['z_min_um']) if bounds else 0.
        _set_value(self.contact_surface_z,boundary_z)
        for key, widget in self.inner_controls.items():
            _set_value(widget, obj.get(key, obj.get('size_x_um' if 'x' in key else 'size_y_um', .5)/2))
        _set_value(self.operation_edit, obj.get('operation', 'material'))
        if kind == 'shapes':
            self.operation = obj.get('operation', 'material')
            _set_value(self.boolean, self.operation)
        self.operation_edit.setEnabled(kind == 'shapes')
        self.vertices_edit.setPlainText(json.dumps(obj.get('vertices', [])))
        for key, widget in self.contact_controls.items():
            _set_value(widget, obj.get(key, 'top' if key == 'surface' else 'ohmic' if key == 'boundary' else 0))
        optical_material = obj.get('optical_material_name') or ''
        optical_names = self._optical_material_names()
        optical_choices = [('None', '')] + [(name, name) for name in optical_names]
        if optical_material and optical_material not in optical_names:
            optical_choices.append((optical_material + ' (missing optical material)', optical_material))
        _choices(self.optical_contact_controls['material'], optical_choices, optical_material)
        assignment=obj.get('optical_material_name') or ''
        assignment_choices=[('Automatic from electrical material','')]+[(name,name) for name in optical_names]
        if assignment and assignment not in optical_names:assignment_choices.append((assignment+' (missing optical material)',assignment))
        _choices(self.optical_assignment,assignment_choices,assignment)
        _set_value(self.optical_contact_controls['thickness'], obj.get('optical_thickness_um', 0.))
        _set_value(self.contact_height_edit,self.optical_contact_controls['thickness'].value())
        self.donor_edit.setText(f"{obj.get('donor_cm3', 0):g}")
        self.acceptor_edit.setText(f"{obj.get('acceptor_cm3', 0):g}")
        for key, widget in self.mesh_controls.items():
            _set_value(widget, device['mesh'][key])
        self.update_mesh_resources()
        self.pick_face_button.setEnabled(kind == 'contacts')
        self.array_button.setEnabled(kind == 'shapes')
        self.update_shape_fields()
        material = next((entry for entry in self.store.electrical_materials if entry['id'] == obj.get('material_id')), None)
        if kind=='contacts':
            layer=next((row for row in device['layers'] if row['id']==obj.get('layer_id')), {})
            material=next((entry for entry in self.store.electrical_materials if entry['id']==layer.get('material_id')),None)
            if material:_set_value(self.material_edit,material['id'])
        self.material_note.setText(f"{material['name']} · {'Built-in' if material['id'] in ('gaas','ito','algaas','silicon','air') else 'Custom'}" if material else
            'No electrical material assigned · optical material '+obj['optical_material_name'] if kind in ('layers','shapes') and not material_id and obj.get('optical_material_name') else
            'Missing electrical material: '+str(material_id) if kind in ('layers','shapes') and material_id else 'Shared electrical material library')
        self._remember_inspector_precision()

    def _remember_inspector_precision(self):
        """A compact display must not round the source when Apply is unchanged."""
        self._inspector_numeric_baseline = {}
        self._inspector_numeric_edited = set()
        for widget in self._diagnostic_widgets().values():
            if not isinstance(widget, QAbstractSpinBox) and widget not in (self.donor_edit, self.acceptor_edit):
                continue
            edit = widget.lineEdit() if isinstance(widget, QAbstractSpinBox) else widget
            value = widget.value() if isinstance(widget, QAbstractSpinBox) else edit.text()
            self._inspector_numeric_baseline[widget] = (value, edit.text())
            if not getattr(widget, '_inspector_precision_connected', False):
                edit.textEdited.connect(lambda _text, control=widget: self._mark_inspector_numeric_edit(control))
                widget._inspector_precision_connected = True

    def _mark_inspector_numeric_edit(self, widget):
        if self.loading:
            return
        self._inspector_numeric_edited.add(widget)
        # These duplicate controls edit one physical quantity. Explicitly typing
        # its displayed rounded value is still an edit, even without valueChanged.
        for key, control in self.contact_position_controls.items():
            if widget in (control, self.geometry_controls[key]):
                self._inspector_numeric_edited.update((control, self.geometry_controls[key]))
        if widget in (self.contact_height_edit, self.optical_contact_controls['thickness']):
            self._inspector_numeric_edited.update((self.contact_height_edit, self.optical_contact_controls['thickness']))
        if widget is self.geometry_controls['size_x_um'] and self.shape_edit.currentData() == 'circle':
            self._inspector_numeric_edited.add(self.geometry_controls['size_y_um'])

    def _inspector_number(self, widget, original):
        spin = isinstance(widget, QAbstractSpinBox)
        edit = widget.lineEdit() if spin else widget
        value = widget.value() if spin else edit.text()
        baseline = getattr(self, '_inspector_numeric_baseline', {}).get(widget)
        if (original is not None and widget not in getattr(self, '_inspector_numeric_edited', set())
                and baseline == (value, edit.text())):
            return original
        return value if spin else float(value)

    def update_mesh_resources(self,*_):
        """Preview requested counts and planning RAM without allocating a mesh."""
        from electrical_mesh import mesh_resource_estimate,available_memory_bytes
        try:
            device=self._current_device()
            device['mesh'].update({key:widget.value() for key,widget in self.mesh_controls.items()})
            estimate=mesh_resource_estimate(device);available=available_memory_bytes()
            budget=(f"{estimate['cell_budget']:,} cells" if estimate['cell_budget'] else
                f"Automatic · {available*.6/1024**2:,.0f} MiB RAM" if available else 'Automatic · available RAM unknown')
            self.mesh_resource_note.setText(
                f"{' × '.join(map(str,estimate['shape']))} · {estimate['cells']:,} cells\n"
                f"Planning estimate: peak {estimate['estimated_peak_bytes']/1024**2:,.1f} MiB · "
                f"one bias volume {estimate['estimated_volume_bytes']/1024**2:,.1f} MiB\n"
                f"{estimate['linear_solver']} · {budget}\nResolution is retained; Run checks available RAM before allocation.")
        except (ValueError,TypeError,KeyError,OverflowError):
            self.mesh_resource_note.setText('Set the device layers and mesh counts to estimate RAM.')

    def _optical_material_names(self):
        materials = getattr(self.store, 'materials', None)
        if hasattr(materials, 'columns') and 'Name' in materials.columns:
            values = materials['Name'].tolist()
        elif isinstance(materials, list):
            values = [entry.get('Name', entry.get('name', '')) for entry in materials if isinstance(entry, dict)]
        else:
            values = []
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))

    def update_shape_fields(self, *_):
        polygon = self.shape_edit.currentData() == 'polygon'
        self.vertices_edit.setEnabled(polygon)
        self.vertices_edit.setVisible(polygon)
        self.shape_form.labelForField(self.vertices_edit).setVisible(polygon)
        self.geometry_controls['size_y_um'].setEnabled(self.shape_edit.currentData() != 'circle' and not polygon)
        if self.shape_edit.currentData() == 'circle':
            self.geometry_controls['size_y_um'].setValue(self.geometry_controls['size_x_um'].value())
        self.geometry_controls['size_x_um'].setEnabled(not polygon)
        self.shape_form.labelForField(self.geometry_controls['cx_um']).setText('X translation (µm)' if polygon else 'Center x (µm)')
        self.shape_form.labelForField(self.geometry_controls['cy_um']).setText('Y translation (µm)' if polygon else 'Center y (µm)')
        ring = self.shape_edit.currentData() == 'square_ring'
        for widget in self.inner_controls.values():
            widget.setVisible(ring)
            self.shape_form.labelForField(widget).setVisible(ring)

    def tree_selected(self, item, previous=None):
        if self.loading or item is None:
            return
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if value=='__find__':self.find_device_object();return
        if value:
            self.select_object(value)

    def select_object(self, object_id):
        self.selected_id = object_id
        self.refresh()
        if self._kind() == 'mesh':
            self.inspector_tabs.setCurrentIndex(1)

    def _diagnostic_widgets(self):
        """Only inspector controls; selection/camera/library state is not a model edit."""
        result = {name: getattr(self, name) for name in ('name_edit', 'enabled_edit', 'material_edit',
            'layer_edit', 'thickness_edit', 'shape_edit', 'operation_edit', 'vertices_edit',
            'donor_edit', 'acceptor_edit', 'optical_assignment', 'contact_terminal_name', 'contact_height_edit')}
        for group in ('device_controls', 'geometry_controls', 'inner_controls', 'contact_controls',
                      'contact_position_controls', 'optical_contact_controls', 'mesh_controls'):
            result.update({group+'.'+key: widget for key, widget in getattr(self, group).items()})
        return result

    def _diagnostic_object_snapshot(self, identity):
        device = self._device_ref()
        value = device if identity == 'device' else device.get('mesh') if identity == 'mesh' else _model_api().find_object(device, identity)
        return copy.deepcopy(value)

    def _capture_diagnostic_draft(self):
        values = {}
        for key, widget in self._diagnostic_widgets().items():
            if isinstance(widget, QComboBox):
                values[key] = ('choice', widget.currentData(), widget.currentText())
            elif isinstance(widget, QCheckBox):
                values[key] = ('check', widget.isChecked())
            elif isinstance(widget, QAbstractSpinBox):
                values[key] = ('spin', widget.value(), widget.lineEdit().text())
            elif isinstance(widget, QPlainTextEdit):
                values[key] = ('plain', widget.toPlainText())
            else:
                values[key] = ('text', widget.text())
        numeric_edited = [key for key, widget in self._diagnostic_widgets().items()
                          if widget in getattr(self, '_inspector_numeric_edited', set())]
        return dict(values=values, numeric_edited=numeric_edited, snapshot=self._diagnostic_object_snapshot(self.selected_id),
                    inspector_tab=self.inspector_tabs.currentIndex(), page=self.tabs.currentIndex())

    def _restore_diagnostic_draft(self, draft):
        """Restoring widgets must not trigger linked controls or commit a model."""
        from PyQt6.QtCore import QSignalBlocker
        widgets = self._diagnostic_widgets()
        blockers = [QSignalBlocker(widget) for widget in widgets.values()]
        previous = self.loading
        self.loading = True
        try:
            for key, value in draft['values'].items():
                widget = widgets[key]
                if value[0] == 'choice':
                    index = widget.findData(value[1])
                    if index < 0:
                        widget.addItem(value[2]+' (draft; missing assignment)', value[1])
                        index = widget.count()-1
                    widget.setCurrentIndex(index)
                elif value[0] == 'check':
                    widget.setChecked(value[1])
                elif value[0] == 'spin':
                    widget.setValue(value[1]); widget.lineEdit().setText(value[2])
                elif value[0] == 'plain':
                    widget.setPlainText(value[1])
                else:
                    widget.setText(value[1])
            self.update_shape_fields()
            # update_shape_fields can synchronize circle dimensions; preserve the
            # exact text last, including an intermediate numeric draft.
            for key, value in draft['values'].items():
                if value[0] == 'spin':
                    widgets[key].lineEdit().setText(value[2])
            self._inspector_numeric_edited = {widgets[key] for key in draft.get('numeric_edited', ()) if key in widgets}
            self.inspector_tabs.setCurrentIndex(draft['inspector_tab'])
            self.tabs.setCurrentIndex(draft['page'])
        finally:
            self.loading = previous
            del blockers

    def open_diagnostic(self, target):
        """Reveal a stable input without implicitly applying the current inspector."""
        from qt_input_diagnostics import reveal_and_focus
        field = str(target.get('field') or '').removeprefix('device.')
        identity = str(target.get('object_id') or '')
        if not identity:
            identity = 'mesh' if field.startswith('mesh.') or field in self.mesh_controls else 'device'
        if self._diagnostic_object_snapshot(identity) is None:
            self.status.setText('This object was removed. Recheck missing inputs; the current inspector draft is unchanged.')
            return False
        cached = self._diagnostic_drafts.get(identity)
        if cached and cached['snapshot'] != self._diagnostic_object_snapshot(identity):
            self.status.setText('This object changed while its draft was held. Return to that draft before resolving the new issue.')
            return False
        if self._diagnostic_origin is None:
            self._diagnostic_origin = self.selected_id
        self._diagnostic_drafts[self.selected_id] = self._capture_diagnostic_draft()
        if identity != self.selected_id:
            self.select_object(identity)
            if cached:
                self._restore_diagnostic_draft(cached)
        self.tabs.setCurrentIndex(0)
        kind = self._kind()
        short = field.split('.')[-1]
        mapping = dict(name=self.name_edit, enabled=self.enabled_edit, material_id=self.material_edit,
            layer_id=self.layer_edit, thickness_um=self.thickness_edit, shape=self.shape_edit,
            operation=self.operation_edit, vertices=self.vertices_edit, donor_cm3=self.donor_edit,
            acceptor_cm3=self.acceptor_edit, optical_material_name=(self.optical_contact_controls['material']
                if kind == 'contacts' else self.optical_assignment), optical_thickness_um=self.optical_contact_controls['thickness'])
        mapping.update(self.device_controls if kind == 'device' else self.mesh_controls if kind == 'mesh' else self.geometry_controls)
        mapping.update(self.inner_controls)
        if kind == 'contacts':
            mapping.update(self.contact_controls)
            mapping.update(self.contact_position_controls)
        widget = mapping.get(short)
        if widget is None:
            self.status.setText(target.get('message') or 'The owning object is selected. Choose its input in the inspector.')
            return reveal_and_focus(self.inspector_tabs, message=target.get('message', ''))
        return reveal_and_focus(widget, message=target.get('message', ''))

    def return_from_diagnostic(self):
        """Return to the originating inspector and its exact uncommitted draft."""
        identity = self._diagnostic_origin
        if not identity:
            return True
        self._diagnostic_drafts[self.selected_id] = self._capture_diagnostic_draft()
        cached = self._diagnostic_drafts.get(identity)
        if cached is None or cached['snapshot'] != self._diagnostic_object_snapshot(identity):
            self.status.setText('The original object changed or was removed. Its held draft has not been applied or discarded.')
            return False
        self.select_object(identity)
        self._restore_diagnostic_draft(cached)
        self._diagnostic_origin = None
        return True

    def find_device_object(self):
        """Search all canonical objects, including leaves outside the tree budget."""
        self.tree_actions.close()
        from PyQt6.QtWidgets import QDialogButtonBox
        dialog=_EditorConfirmDialog(self);dialog.setWindowTitle('Find a device object');dialog.resize(570,540)
        self.find_object_dialog=dialog
        layout=QVBoxLayout(dialog)
        self.find_object_search=QLineEdit();self.find_object_search.setPlaceholderText('Search every name or object ID…')
        layout.addWidget(self.find_object_search)
        self.find_object_results=QTreeWidget();self.find_object_results.setHeaderLabels(['Object','Type'])
        layout.addWidget(self.find_object_results,1)
        self.find_object_count=_label('');layout.addWidget(self.find_object_count)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Select and focus')
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        document=self._device_ref()
        def update_results():
            query=self.find_object_search.text().strip().casefold();self.find_object_results.clear();total=0
            for kind in ('layers','shapes','contacts','doping_regions','pc_arrays'):
                for obj in document.get(kind,[]):
                    if query and query not in (obj['name']+' '+obj['id']).casefold():continue
                    total+=1
                    if total<=500:
                        item=QTreeWidgetItem([obj['name'],kind.replace('_',' ')])
                        item.setData(0,Qt.ItemDataRole.UserRole,obj['id']);item.setToolTip(0,obj['id'])
                        self.find_object_results.addTopLevelItem(item)
            self.find_object_count.setText(f'{total:,} matches'+(' · first 500 shown; refine your search' if total>500 else ''))
            if self.find_object_results.topLevelItemCount():self.find_object_results.setCurrentItem(self.find_object_results.topLevelItem(0))
            buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(total>0)
        self.find_object_search.textChanged.connect(update_results)
        self.find_object_results.itemDoubleClicked.connect(lambda *_:dialog.accept())
        update_results();self.find_object_search.setFocus()
        if dialog.exec()==QDialog.DialogCode.Accepted:
            item=self.find_object_results.currentItem()
            if item:self.focus_object(item.data(0,Qt.ItemDataRole.UserRole))

    def focus_object(self,object_id):
        self.select_object(object_id)
        obj=_model_api().find_object(self._device_ref(),object_id)
        if not obj or self._kind(object_id) not in ('shapes','contacts','doping_regions'):return
        canvas=self.top_view;canvas.plan_layer_mode='selected';canvas.pan=QPointF(0,0);canvas.zoom=1.
        vertices=_polygon(obj)
        x=(min(point[0] for point in vertices)+max(point[0] for point in vertices))/2
        y=(min(point[1] for point in vertices)+max(point[1] for point in vertices))/2
        extent=max(max(point[0] for point in vertices)-min(point[0] for point in vertices),max(point[1] for point in vertices)-min(point[1] for point in vertices),1e-9)
        canvas.zoom=min(512.,max(1.,min(canvas.width(),canvas.height())/(extent*8*canvas._plan_transform()[0])))
        canvas.pan=QPointF(canvas.width()/2,canvas.height()/2)-canvas.screen_point(x,y)
        self.cut_y.setValue(y);canvas.update()

    def update_views(self, *_):
        device = self._device_ref()
        for canvas in (self.top_view, self.section_view, self.view_3d):
            canvas.cut_y = self.cut_y.value()
            canvas.show_mesh = self.mesh_preview.isChecked()
            canvas.set_device(device, self.selected_id, self.active_layer_id)

    def set_tool(self, tool):
        self.tool = tool
        if tool not in ('select','move'):
            self.top_view.plan_layer_mode='selected'
        for canvas in (self.top_view, self.section_view, self.view_3d):
            canvas.pick_surface = False
        for name, button in self.tool_buttons.items():
            button.setChecked(name == tool)
        self.top_view.set_tool(tool)
        self.status.setText('Click polygon vertices; press Enter or double-click to finish.' if tool == 'polygon' else
            'Drag in the top view to draw a contact footprint.' if tool == 'contact' else
            'Drag a selected shape in the top view.' if tool == 'move' else
            'Drag in the top view to draw; the shape belongs to the selected layer.' if tool not in ('select',) else
            'Click an object in any preview or select it in the tree.')

    def _new_geometry(self, shape_kind='rectangle', **values):
        shape = values.pop('shape', shape_kind)
        device = self._current_device()
        side = min(device['width_um'], device['depth_um'])/3
        result = dict(id=uuid.uuid4().hex, name=shape.title(), shape=shape,
            layer_id=self.active_layer_id or device['layers'][0]['id'], material_id=self.material_edit.currentData() or 'gaas',
            cx_um=0., cy_um=0., size_x_um=side, size_y_um=side, angle_deg=0., vertices=[], enabled=True)
        if shape == 'polygon':
            result['vertices'] = [[-side/2, -side/2], [side/2, -side/2], [0., side/2]]
        result.update(values)
        return result

    def add_layer(self):
        device = self._current_device()
        layer = dict(id=uuid.uuid4().hex, name=f"Layer {len(device['layers'])+1}", material_id=self.material_edit.currentData() or 'gaas',
            thickness_um=.1, donor_cm3=0., acceptor_cm3=0., enabled=True)
        position = next((i+1 for i, item in enumerate(device['layers']) if item['id'] == self.active_layer_id), len(device['layers']))
        device['layers'].insert(position, layer)
        self._commit(device, layer['id'], 'Layer added. Edit its material, thickness and doping in the inspector.')

    def add_shape(self, shape='rectangle', geometry=None):
        device = self._current_device()
        obj = self._new_geometry(shape, **(geometry or {}))
        if obj['name'] == shape.title():
            obj['name'] += f" {len(device['shapes'])+1}"
        obj['operation'] = self.operation
        device['shapes'].append(obj)
        self._commit(device, obj['id'], 'Shape added to the selected layer.')

    def add_contact(self, geometry=None):
        device = self._current_device()
        obj = self._new_geometry('rectangle', **(geometry or {}))
        obj.update(name=f"Contact {len(device['contacts'])+1}", surface='top', boundary='ohmic', voltage_V=0., bias_scale=1 if device['contacts'] else 0)
        device['contacts'].append(obj)
        if self._commit(device, obj['id'], 'Contact added. Choose its actual layer surface and boundary voltage.'):
            self.inspector_tabs.setCurrentIndex(1)

    def add_doping(self, geometry=None):
        device = self._current_device()
        obj = self._new_geometry('rectangle', **(geometry or {}))
        obj.update(name=f"Doping {len(device['doping_regions'])+1}", donor_cm3=1e17, acceptor_cm3=0.)
        device['doping_regions'].append(obj)
        if self._commit(device, obj['id'], 'Doping region added. Enter donors and acceptors in cm⁻³.'):
            self.inspector_tabs.setCurrentIndex(1)

    def geometry_created(self, geometry):
        if self.tool == 'contact':
            self.add_contact(geometry)
        elif self.tool == 'doping':
            self.add_doping(geometry)
        else:
            self.add_shape(geometry['shape'], geometry)

    def apply_inspector(self):
        device = self._current_device()
        kind = self._kind()
        obj = device if kind == 'device' else device['mesh'] if kind == 'mesh' else _model_api().find_object(device, self.selected_id)
        if obj is None:
            return False
        try:
            if kind == 'mesh':
                obj.update({key: self._inspector_number(widget, obj.get(key)) for key, widget in self.mesh_controls.items()})
            else:
                obj['name'] = self.name_edit.text().strip()
                if kind == 'device':
                    obj.update({key: self._inspector_number(widget, obj.get(key)) for key, widget in self.device_controls.items()})
                else:
                    obj['enabled'] = self.enabled_edit.isChecked()
                if kind in ('layers', 'shapes'):
                    obj['material_id'] = self.material_edit.currentData()
                    obj['optical_material_name'] = self.optical_assignment.currentData() or ''
                if kind == 'layers':
                    obj['thickness_um'] = self._inspector_number(self.thickness_edit, obj.get('thickness_um'))
                if kind in ('shapes', 'contacts', 'doping_regions'):
                    obj.update({key: self._inspector_number(widget, obj.get(key)) for key, widget in self.geometry_controls.items()})
                    obj['shape'] = self.shape_edit.currentData()
                    obj['layer_id'] = self.layer_edit.currentData()
                    obj['vertices'] = json.loads(self.vertices_edit.toPlainText()) if obj['shape'] == 'polygon' else []
                    if obj['shape'] == 'square_ring':
                        obj.update({key: self._inspector_number(widget, obj.get(key)) for key, widget in self.inner_controls.items()})
                if kind=='pc_arrays':
                    obj['layer_id']=self.layer_edit.currentData()
                    for shape in device['shapes']:
                        if shape.get('pc_array_id')==obj['id']:
                            shape['layer_id']=obj['layer_id'];shape['enabled']=obj['enabled']
                if kind == 'shapes':
                    obj['operation'] = self.operation_edit.currentData()
                if kind == 'contacts':
                    obj.update({key: widget.currentData() if isinstance(widget, QComboBox) else self._inspector_number(widget, obj.get(key)) for key, widget in self.contact_controls.items()})
                    obj['optical_material_name'] = self.optical_contact_controls['material'].currentData() or ''
                    obj['optical_thickness_um'] = self._inspector_number(self.optical_contact_controls['thickness'], obj.get('optical_thickness_um'))
                if kind in ('layers', 'doping_regions'):
                    obj['donor_cm3'] = self._inspector_number(self.donor_edit, obj.get('donor_cm3'))
                    obj['acceptor_cm3'] = self._inspector_number(self.acceptor_edit, obj.get('acceptor_cm3'))
            applied = self._commit(device)
            if applied:
                self._diagnostic_drafts.pop(self.selected_id, None)
            return applied
        except Exception as exc:
            self.status.setText(f'Could not apply properties: {exc}')
            return False

    def move_object(self, object_id, dx, dy):
        device = self._current_device()
        obj = _model_api().find_object(device, object_id)
        if obj and self._kind(object_id) in ('shapes', 'contacts', 'doping_regions'):
            obj['cx_um'] += dx
            obj['cy_um'] += dy
            self._commit(device, object_id, 'Object moved.')
        else:
            self.status.setText('Select a shape, contact or doping region to move.')

    def boolean_changed(self, *_):
        self.operation = self.boolean.currentData()
        if self.loading or self._kind() != 'shapes':
            return
        device = self._current_device()
        obj = _model_api().find_object(device, self.selected_id)
        obj['operation'] = self.operation
        self._commit(device, message='Shape operation updated.')

    def duplicate_selected(self):
        kind = self._kind()
        if kind=='pc_arrays':
            from pc_array import apply_pc_array
            spec=self.selected_object();spec.update(id='pc_'+uuid.uuid4().hex[:12],name=spec['name']+' copy')
            try:self._commit(apply_pc_array(self._device_ref(),spec,material_library=self.store.electrical_materials),spec['id'],'PC area and all editable holes duplicated.')
            except Exception as exc:self.status.setText(str(exc))
            return
        if kind in ('device', 'mesh'):
            self.status.setText('Select a layer, shape, contact or doping region to duplicate.')
            return
        device = self._current_device()
        obj = copy.deepcopy(_model_api().find_object(device, self.selected_id))
        obj['id'] = uuid.uuid4().hex
        obj['name'] += ' copy'
        device[kind].append(obj)
        self._commit(device, obj['id'], 'Object duplicated.')

    def delete_selected(self):
        kind = self._kind()
        if kind in ('device', 'mesh'):
            self.status.setText('The device outline and mesh cannot be deleted.')
            return
        device = self._current_device()
        object_id = self.selected_id
        if kind == 'layers' and len(device['layers']) <= 1:
            self.status.setText('Keep at least one finite device layer.')
            return
        device[kind] = [obj for obj in device[kind] if obj['id'] != object_id]
        if kind=='pc_arrays':device['shapes']=[obj for obj in device['shapes'] if obj.get('pc_array_id')!=object_id]
        if kind == 'layers':
            for group in ('shapes', 'contacts', 'doping_regions'):
                device[group] = [obj for obj in device[group] if obj['layer_id'] != object_id]
            device['pc_arrays']=[obj for obj in device.get('pc_arrays',[]) if obj['layer_id']!=object_id]
        self._commit(device, 'device', 'Object deleted; dependent layer objects were removed together.')

    def reorder_layer(self, offset):
        device = self._current_device()
        index = next((i for i, layer in enumerate(device['layers']) if layer['id'] == self.active_layer_id), None)
        if index is None or not 0 <= index+offset < len(device['layers']):
            return
        device['layers'][index], device['layers'][index+offset] = device['layers'][index+offset], device['layers'][index]
        self._commit(device, self.active_layer_id, 'Layer order updated; depth increases from top to bottom.')

    def extrude_selected(self):
        if self._kind() != 'shapes':
            self.status.setText('Select a shape to extrude through additional layers.')
            return
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        device = self._current_device()
        obj = _model_api().find_object(device, self.selected_id)
        dialog = QDialog(self)
        dialog.setWindowTitle('Extrude the selected shape through layers')
        layout = QVBoxLayout(dialog)
        layout.addWidget(_label('Creates the same physical cross-section in each checked layer.'))
        checks = []
        for layer in device['layers']:
            check = QCheckBox(layer['name'])
            check.setChecked(layer['id'] == obj['layer_id'])
            layout.addWidget(check)
            checks.append((layer['id'], check))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.extrude_to_layers([layer_id for layer_id, check in checks if check.isChecked()])

    def extrude_to_layers(self, layer_ids):
        if self._kind() != 'shapes':
            return False
        device = self._current_device()
        original = _model_api().find_object(device, self.selected_id)
        for layer_id in layer_ids:
            if layer_id != original['layer_id']:
                obj = copy.deepcopy(original)
                obj.update(id=uuid.uuid4().hex, layer_id=layer_id, name=original['name']+' extrusion')
                device['shapes'].append(obj)
        return self._commit(device, message='Shape extruded as matching regions in selected physical layers.')

    def pattern_array(self):
        self.toolbar_menu.close()
        if self._kind() != 'shapes':
            self.status.setText('Select a material or void shape to create a pattern array.')
            return
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        obj = self.selected_object()
        dialog = QDialog(self)
        dialog.setObjectName('patternArrayDialog')
        dialog.setWindowTitle('Array the selected physical pattern')
        layout = QVBoxLayout(dialog)
        controls = {'nx': integer(3, 1, 31), 'ny': integer(3, 1, 31),
            'pitch_x_um': number(obj['size_x_um']*2, 1e-6, 1e6, 6),
            'pitch_y_um': number(obj['size_y_um']*2, 1e-6, 1e6, 6)}
        for key, widget in controls.items():
            widget.setObjectName('array_'+key)
        form, form_layout = _group('Rectangular array', [('Count X', controls['nx']), ('Count Y', controls['ny']),
            ('Pitch X (µm)', controls['pitch_x_um']), ('Pitch Y (µm)', controls['pitch_y_um'])])
        centered = QCheckBox('Center the array on the selected shape')
        centered.setObjectName('array_centered')
        form_layout.addRow(centered)
        layout.addWidget(form)
        layout.addWidget(_label('Each copy is an editable physical region in the selected layer. The original anchors the first cell unless centered. Geometry outside the finite device is clipped by the model.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        self.array_dialog = dialog
        self.array_controls = dict(controls, centered=centered)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.create_pattern_array(**{key: widget.value() for key, widget in controls.items()}, centered=centered.isChecked())

    def pc_area(self,array_id=None):
        """Preview an independent PC area before creating all editable holes."""
        self.toolbar_menu.close()
        from PyQt6.QtWidgets import QApplication,QDialog,QDialogButtonBox
        from PyQt6.QtGui import QCursor
        from pc_array import plan_pc_array,apply_pc_array
        device=self._current_device();self._pc_area_device=device
        arrays=device.get('pc_arrays',[])
        existing=next((row for row in arrays if row['id']==array_id),None)
        dialog=_EditorConfirmDialog(self);dialog.setWindowTitle('Fill an independent PC area');dialog.resize(620,680)
        self.pc_area_dialog=dialog
        layout=QVBoxLayout(dialog);layout.setSpacing(10)
        layout.addWidget(_label(f"Finite device footprint: {device['width_um']:g} × {device['depth_um']:g} µm"))
        self.pc_area_selector=_combo([('New PC area','')]+[(row['name'],row['id']) for row in arrays],existing['id'] if existing else '')
        layout.addWidget(self.pc_area_selector)
        controls={'name':QLineEdit(), 'layer_id':_combo([(row['name']+(' (disabled)' if not row['enabled'] else ''),row['id']) for row in device['layers']])}
        for key in ('width_um','depth_um','cell_width_um','cell_depth_um'):
            controls[key]=number(.45,1e-6,1e6,8)
        for key in ('cx_um','cy_um'):controls[key]=number(0.,-1e6,1e6,8)
        controls['radius_um']=number(.09,5e-7,1e6,8)
        self.pc_area_controls=controls
        area,_=_group('PC area, independent of the finite device',[(label,controls[key]) for label,key in
            [('Name','name'),('Target layer','layer_id'),('PC width X (µm)','width_um'),('PC depth Y (µm)','depth_um'),('PC center X (µm)','cx_um'),('PC center Y (µm)','cy_um')]])
        layout.addWidget(area)
        cell,_=_group('Complete unit cells and circular air holes',[(label,controls[key]) for label,key in
            [('Cell width / pitch X (µm)','cell_width_um'),('Cell depth / pitch Y (µm)','cell_depth_um'),('Hole radius (µm)','radius_um')]])
        layout.addWidget(cell)
        self.pc_area_import_cell=_button('Use current optical unit-cell dimensions',self._pc_import_optical_cell)
        layout.addWidget(self.pc_area_import_cell)
        self.pc_area_preview=_label('');self.pc_area_preview.setObjectName('devicePanelTitle');layout.addWidget(self.pc_area_preview)
        self.pc_area_notes=_label('');layout.addWidget(self.pc_area_notes)
        self.pc_area_edit_note=_label('Every generated hole remains individually editable. Only complete cells are filled; unused margins are centered.');layout.addWidget(self.pc_area_edit_note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.pc_area_button_box=buttons
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Fill PC area')
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        self._pc_area_id='';self._pc_area_enabled=True
        def load_region(region_id):
            self._pc_area_id=region_id or 'pc_'+uuid.uuid4().hex[:12]
            region=next((row for row in arrays if row['id']==region_id),None)
            self._pc_area_enabled=region.get('enabled',True) if region else True
            values=region or dict(name=f'PC area {len(arrays)+1}',layer_id=self.active_layer_id or device['layers'][0]['id'],
                width_um=device['width_um']*.8,depth_um=device['depth_um']*.8,cx_um=0.,cy_um=0.,
                cell_width_um=.45,cell_depth_um=.45,radius_um=.09)
            for key,control in controls.items():_set_value(control,values[key])
            self.pc_area_edit_note.setText('Refilling this PC area replaces its associated holes and resets their individual edits.' if region else 'Every generated hole remains individually editable. Only complete cells are filled; unused margins are centered.')
            self._update_pc_area_preview()
        self.pc_area_selector.currentIndexChanged.connect(lambda _:load_region(self.pc_area_selector.currentData()))
        for control in controls.values():
            if isinstance(control,QLineEdit):control.textChanged.connect(self._update_pc_area_preview)
            elif isinstance(control,QComboBox):control.currentIndexChanged.connect(self._update_pc_area_preview)
            else:control.valueChanged.connect(self._update_pc_area_preview)
        load_region(existing['id'] if existing else '')
        for button in dialog.findChildren(QPushButton):
            button.setAutoDefault(False);button.setDefault(False)
        if not dialog.exec():return False
        spec=self._pc_area_spec()
        try:
            plan=plan_pc_array(device,spec)
            self.status.setText(f"Generating {plan['hole_count']:,} editable air holes in the PC area…")
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor));QApplication.processEvents()
            result=apply_pc_array(device,spec,material_library=self.store.electrical_materials)
            first=result['pc_arrays'][-1]['shape_ids'][0]
            return self._commit(result,first,f"PC area filled: {plan['nx']:,} × {plan['ny']:,} = {plan['hole_count']:,} actual holes. X/Y edge margins {plan['margin_x_um']:g}/{plan['margin_y_um']:g} µm per side. "+('Electrical mesh resolution needs review.' if plan['notes'] else ''))
        except Exception as exc:
            self.status.setText(f'Could not fill PC area: {exc}');return False
        finally:QApplication.restoreOverrideCursor()

    def _pc_area_spec(self):
        spec={'id':self._pc_area_id,'enabled':self._pc_area_enabled}
        for key,control in self.pc_area_controls.items():
            spec[key]=control.text().strip() if isinstance(control,QLineEdit) else control.currentData() if isinstance(control,QComboBox) else control.value()
        return spec

    def _update_pc_area_preview(self,*_):
        from pc_array import plan_pc_array
        from PyQt6.QtWidgets import QDialogButtonBox
        try:
            plan=plan_pc_array(self._pc_area_device,self._pc_area_spec());self.pc_area_plan=plan
            self.pc_area_preview.setText(f"{plan['nx']:,} × {plan['ny']:,} complete cells · {plan['hole_count']:,} air holes\nUnused X/Y: {plan['unused_x_um']:g}/{plan['unused_y_um']:g} µm total · {plan['margin_x_um']:g}/{plan['margin_y_um']:g} µm per edge")
            self.pc_area_notes.setText('\n'.join(plan['notes']))
            self.pc_area_button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(plan['can_apply'])
        except Exception as exc:
            self.pc_area_plan=None;self.pc_area_preview.setText(str(exc));self.pc_area_notes.setText('')
            self.pc_area_button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def _pc_import_optical_cell(self):
        settings=getattr(self.store,'settings',{})
        optical_cell=settings.get('optical_unit_cell')
        if isinstance(optical_cell,dict):
            for key,source in [('cell_width_um','width_um'),('cell_depth_um','depth_um')]:
                if source in optical_cell:self.pc_area_controls[key].setValue(optical_cell[source])
        else:
            for key,source in [('cell_width_um','ax_um'),('cell_depth_um','ay_um')]:
                if source in settings:self.pc_area_controls[key].setValue(settings[source])
        self._update_pc_area_preview()

    def create_pattern_array(self, nx=3, ny=3, pitch_x_um=.2, pitch_y_um=.2, centered=False):
        if self._kind() != 'shapes':
            self.status.setText('Select a material or void shape first.')
            return False
        try:
            if isinstance(nx, bool) or isinstance(ny, bool) or int(nx) != nx or int(ny) != ny or not 1 <= nx <= 31 or not 1 <= ny <= 31:
                raise ValueError('Array counts must be integers from 1 to 31.')
            pitch_x_um, pitch_y_um = float(pitch_x_um), float(pitch_y_um)
            if not math.isfinite(pitch_x_um+pitch_y_um) or min(pitch_x_um, pitch_y_um) <= 0:
                raise ValueError('Array pitches must be positive finite dimensions in µm.')
            device = self._current_device()
            if len(device['shapes'])+nx*ny-1 > 100000:
                raise ValueError('This array would exceed the 100,000-shape document budget.')
            original = _model_api().find_object(device, self.selected_id)
            source = copy.deepcopy(original)
            offset_x = -(nx-1)/2 if centered else 0
            offset_y = -(ny-1)/2 if centered else 0
            for iy in range(ny):
                for ix in range(nx):
                    obj = original if ix == 0 and iy == 0 else copy.deepcopy(source)
                    obj['cx_um'] = source['cx_um']+(ix+offset_x)*pitch_x_um
                    obj['cy_um'] = source['cy_um']+(iy+offset_y)*pitch_y_um
                    if ix or iy:
                        obj['id'] = uuid.uuid4().hex
                        obj['name'] = f"{source['name']} [{ix+1},{iy+1}]"
                        device['shapes'].append(obj)
            return self._commit(device, message=f'{nx} × {ny} physical pattern array created. Refine the mesh to resolve its smallest features.')
        except Exception as exc:
            self.status.setText(str(exc))
            return False

    def undo_device(self):
        if hasattr(self.store, 'undo'):
            try:
                self.store.undo()
                self.refresh()
                self.status.setText('Simulation device / optical structure edit undone.')
            except Exception as exc:
                self.status.setText(str(exc))
            return
        if not self._history:
            self.status.setText('No device edits to undo.')
            return
        previous = self._history[-1]
        try:
            self.store.set_device(previous)
            self._history.pop()
            self.refresh()
            self.status.setText('Device edit undone.')
        except Exception as exc:
            self.status.setText(str(exc))

    def pick_contact_surface(self):
        if self._kind() != 'contacts':
            self.status.setText('Select a contact first.')
            return
        for canvas in (self.top_view, self.section_view, self.view_3d):
            canvas.pick_surface = True
        self.status.setText('Click the layer surface in a preview. The 3D side walls identify side surfaces.')

    def assign_contact_surface(self, object_id, face):
        device = self._current_device()
        target = _model_api().find_object(device, object_id)
        contact = _model_api().find_object(device, self.selected_id)
        if not target or not contact or self._kind() != 'contacts':
            return
        layer_id = target['id'] if self._kind(object_id) == 'layers' else target.get('layer_id')
        contact.update(layer_id=layer_id, surface=face)
        if face.startswith('side_x'):
            contact['cx_um'] = (-1 if face == 'side_x_min' else 1)*device['width_um']/2
        elif face.startswith('side_y'):
            contact['cy_um'] = (-1 if face == 'side_y_min' else 1)*device['depth_um']/2
        if self._commit(device, message=f'Contact assigned to {face}.'):
            for canvas in (self.top_view, self.section_view, self.view_3d):
                canvas.pick_surface = False

    def fit_views(self):
        for canvas in (self.top_view, self.section_view, self.view_3d):
            canvas.zoom = 1.
            canvas.update()

    def import_geometry(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Import device or geometry JSON', '', 'Device / geometry JSON (*.json)')
        if filename:
            self.import_geometry_file(filename)

    def import_geometry_file(self, filename):
        try:
            payload = json.loads(Path(filename).read_text(encoding='utf-8'))
            if isinstance(payload, dict) and 'device' in payload:
                payload = payload['device']
            if isinstance(payload, dict) and 'layers' in payload:
                device = payload
            else:
                shapes = payload if isinstance(payload, list) else payload.get('shapes', [])
                if not shapes:
                    raise ValueError('Import a complete canonical device or a nonempty list of shape records.')
                device = self._current_device()
                for raw in shapes:
                    obj = self._new_geometry(raw.get('shape', 'rectangle'), **raw)
                    obj['id'] = uuid.uuid4().hex
                    obj.setdefault('operation', self.operation)
                    device['shapes'].append(obj)
            return self._commit(device, 'device', 'Geometry imported and validated against the shared material library.')
        except Exception as exc:
            self.status.setText(f'Could not import geometry: {exc}')
            return False

    def export_device(self):
        filename, _ = QFileDialog.getSaveFileName(self, 'Export editable device JSON', 'device.json', 'Device JSON (*.json)')
        if filename:
            try:
                Path(filename).write_text(json.dumps(self._current_device(), indent=2, allow_nan=False)+'\n', encoding='utf-8')
                self.status.setText(f'Editable device saved: {filename}')
            except Exception as exc:
                self.status.setText(f'Could not export device: {exc}')

    def export_view(self, mode='3d'):
        canvas = {'top': self.top_view, 'section': self.section_view, '3d': self.view_3d}[mode]
        filename, _ = QFileDialog.getSaveFileName(self, 'Export the current device preview', f'device-{mode}.png', 'PNG image (*.png)')
        if filename:
            try:
                if not Path(filename).suffix:
                    filename += '.png'
                if not canvas.grab().save(filename, 'PNG'):
                    raise ValueError('The preview image could not be written.')
                self.status.setText(f'Actual device preview saved: {filename}')
            except Exception as exc:
                self.status.setText(f'Could not export preview: {exc}')

    def validate_current(self):
        try:
            if not self.apply_inspector():
                return False
            from custom_electrical_solver import build_mesh
            mesh = build_mesh(self._current_device(), self.store.electrical_materials)
            self.status.setText(f'Device validated: {math.prod(mesh["shape"]):,} cells; shapes, doping and contact surfaces intersect the actual mesh.')
            return True
        except Exception as exc:
            self.status.setText(str(exc))
            return False

    def run(self):
        if not self.validate_current():
            return
        try:
            self._run_active = True
            self.status.setText('Preparing the current device electrical simulation…')
            self.store.start_run('electrical', dict(model='custom_device', biases_V=[0.],
                optical_enabled=False, charge_model='semiconductor'))
        except Exception as exc:
            self._run_active = False
            self.status.setText(str(exc))

    def _run_progress(self, event):
        if self._run_active and event.get('run_kind') == 'electrical':
            self.status.setText(event.get('text') or event.get('message') or 'Solving the current device…')

    def _run_finished(self, event):
        if self._run_active and event.get('run_kind') == 'electrical':
            self._run_active = False
            self.status.setText(f"Electrical calculation complete. Results: {event.get('directory', event.get('output', 'Electrical results page'))}")

    def _run_failed(self, message):
        if self._run_active:
            self._run_active = False
            self.status.setText(str(message))

    def load_reference_device(self):
        self._commit(_model_api().default_device(self.store.electrical_materials), 'device',
            'Editable GaAs / AlGaAs / ITO reference loaded; all dimensions, objects, materials and contacts can be changed.')

    def rebuild_library(self,*_):
        for button in self.library_buttons:
            self.library_layout.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.library_buttons = []
        query=self.material_search.text().strip().casefold()
        entries=self.store.electrical_materials
        if query:
            entries=[entry for entry in entries if query in entry['name'].casefold() or query in entry['id'].casefold()]
        else:
            entries=[entry for key in ('gaas','ito','algaas','silicon') for entry in entries if entry['id']==key]
        for material in entries[:4]:
            card=_MaterialCard(material)
            card.selected.connect(self.select_library_material)
            card.edit_requested.connect(self.edit_library_material)
            card.setToolTip(material['name']+': select to assign, or edit its actual electrical properties.')
            self.library_layout.addWidget(card,1);self.library_buttons.append(card)
        custom=QToolButton();custom.setObjectName('deviceCustomMaterial')
        custom.setIcon(_device_icon('plus','#20baff'));custom.setIconSize(QSize(30,30))
        custom.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        custom.setText('Custom material\nAdd a new material\nto your library')
        custom.clicked.connect(self.add_custom_material);custom.setMinimumWidth(130);custom.setMaximumWidth(210);custom.setFixedHeight(135)
        self.library_layout.addWidget(custom,1);self.library_buttons.append(custom)

    def edit_library_material(self,material_id):
        previous=self.material_edit.currentData()
        _set_value(self.material_edit,material_id)
        self.edit_selected_material()
        _set_value(self.material_edit,previous)

    def select_library_material(self, material_id):
        _set_value(self.material_edit, material_id)
        if self._kind() in ('layers', 'shapes'):
            self.status.setText('Material selected. Apply selected object to commit the assignment.')
        else:
            self.status.setText('Material selected for the next layer or material region.')

    def add_custom_material(self):
        from qt_electrical_materials import ElectricalMaterialDialog
        dialog = ElectricalMaterialDialog(parent=self)
        if dialog.exec():
            try:
                self.store.set_electrical_materials([*self.store.electrical_materials, dialog.material()])
                self.refresh()
            except Exception as exc:
                self.status.setText(f'Could not add material: {exc}')

    def edit_selected_material(self):
        from qt_electrical_materials import ElectricalMaterialDialog
        material_id = self.material_edit.currentData()
        material = next((entry for entry in self.store.electrical_materials if entry['id'] == material_id), None)
        if material is None:
            return
        dialog = ElectricalMaterialDialog(material=material, parent=self)
        if dialog.exec():
            try:
                replacement = dialog.material()
                self.store.set_electrical_materials([replacement if entry['id'] == material_id else entry for entry in self.store.electrical_materials])
                self.refresh()
            except Exception as exc:
                self.status.setText(f'Could not edit material: {exc}')

    def manage_materials(self):
        from qt_electrical_materials import ElectricalMaterialManagerDialog
        dialog = ElectricalMaterialManagerDialog(self.store, parent=self)
        dialog.materialSelected.connect(self.select_library_material)
        dialog.exec()
        self.refresh()
