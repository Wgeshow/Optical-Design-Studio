"""Approved native device editor; editing uses the existing structure contracts.

The lightweight geometry viewport renders the actual layer/region tables. Its
exploded view compresses thickness for readability and never changes the model.
"""
import math
import numpy as np
from PyQt6.QtCore import Qt, QPointF, QRectF, QSignalBlocker, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QFont, QFontMetrics, QLinearGradient, QTransform, QBrush
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QComboBox, QSplitter, QGridLayout, QFormLayout, QStyledItemDelegate,
    QStyleOptionViewItem, QStyle, QAbstractItemView, QDoubleSpinBox, QCheckBox, QColorDialog, QDialog, QScrollArea)
from qt_structure import StructurePage
from qt_common import COLORS, theme_manager, LOOKS
from qt_surfaces import WorkspacePanel
from model import LAYER_COLS, PAT_COLS
from structure_builder import rows, validate_structure
from structure_preview import normalize_region, region_polygon, periodic_centers, clip_polygon, section_interval


def layer_color(name, index=0, overrides=None, material='', material_colors=None):
    if overrides and name in overrides and QColor(overrides[name]).isValid():
        return overrides[name]
    if material_colors and material in material_colors and QColor(material_colors[material]).isValid():
        return material_colors[material]
    material = material.lower()
    if material == 'gaas': return '#f48391'
    if 'algaas' in material: return '#929af5'
    if material == 'sic': return '#74d7ac'
    name = name.lower()
    if 'well' in name or 'active' in name: return '#f5ad36'
    if 'barrier' in name: return '#f58561'
    if 'clad' in name: return '#a17cdb'
    if 'photo' in name or 'pc' in name: return '#4baff2'
    if 'air' in name or 'substrate' in name: return '#9caabc'
    return ['#739bd5', '#a17cdb', '#55b8bb', '#dcab69'][index % 4]


class StackRowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(0, 49)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        lines = str(index.data() or '').split('\n')
        opt.text = ''
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        opt.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        c = COLORS[theme_manager().mode]
        painter.save()
        painter.setClipRect(option.rect)
        rect = option.rect
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(index.data(Qt.ItemDataRole.UserRole+2) or layer_color(index.data(Qt.ItemDataRole.UserRole) or '', index.row())))
        painter.drawRoundedRect(QRectF(rect.x()+55, rect.y()+13, 16, 16), 3, 3)
        painter.setPen(QPen(QColor(c['muted']), 1.2));painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(rect.x()+10,rect.y()+16,15,9))
        if index.data(Qt.ItemDataRole.CheckStateRole)==Qt.CheckState.Checked.value:
            painter.setBrush(QColor(c['muted']));painter.drawEllipse(QRectF(rect.x()+16,rect.y()+19,3,3))
        painter.drawText(QRectF(rect.x()+32,rect.y(),20,42),Qt.AlignmentFlag.AlignVCenter,str(index.row()+1))
        painter.setPen(QColor(c['text']))
        font = QFont(option.font); font.setBold(True); painter.setFont(font)
        width = max(10, rect.width()-150)
        painter.drawText(QRectF(rect.x()+82, rect.y(), width, 42), Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(font).elidedText(str(index.data(Qt.ItemDataRole.UserRole) or ''), Qt.TextElideMode.ElideRight, width))
        font.setBold(False); painter.setFont(font); painter.setPen(QColor(c['muted']))
        painter.drawText(QRectF(rect.right()-67, rect.y(), 62, 42), Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,
                         str(index.data(Qt.ItemDataRole.UserRole+3) or ''))
        painter.restore()

    def editorEvent(self,event,model,option,index):
        from PyQt6.QtCore import QEvent
        if event.type()==QEvent.Type.MouseButtonRelease and event.position().x()<option.rect.x()+29:
            checked=index.data(Qt.ItemDataRole.CheckStateRole)==Qt.CheckState.Checked.value
            return model.setData(index,Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,Qt.ItemDataRole.CheckStateRole)
        return False


class GeometryViewport(QWidget):
    layer_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('nativeGeometryViewport')
        self.setMinimumSize(260, 280)
        self.mode = '3D Stack'; self.exploded = True
        self.angle = -math.pi/4; self.elevation = .40; self.zoom = 1.
        self.layers = []; self.patterns = []; self.selected = ''; self.ax = self.ay = .474
        self.cells = 3; self.hits = []; self.drag = None; self.dragged = False
        self.layer_colors = {}; self.material_colors = {}; self.material_opacities = {}; self.hidden_layers = set()
        self.show_holes = True; self.use_colors = True; self.show_edges = False; self.show_axes = True
        self.compact=False
        self._geometry_signature = None
        self._material_clip_cache = {}
        self._regions_cache = {}
        self._stack_cache = {}
        self._projection_key = None
        self._projection = None
        self._frame_apertures = []
        self._aperture_paths = None
        self.setMouseTracking(True)
        self.setAccessibleName('Interactive device geometry. Drag to rotate; scroll to zoom; click a layer to select.')
        theme_manager().changed.connect(self.update)

    def set_model(self, store, selected, cells):
        self.layers = rows(store.layers, LAYER_COLS)
        self.patterns = [normalize_region(r) for r in rows(store.patterns, PAT_COLS)]
        self.selected = selected
        self.layer_colors = getattr(store, 'appearance', {}).get('layer_colors', {}).copy()
        self.material_colors = getattr(store, 'appearance', {}).get('material_colors', {}).copy()
        self.material_opacities = getattr(store, 'appearance', {}).get('material_opacities', {}).copy()
        self.ax = float(store.settings.get('ax_um', .474)); self.ay = float(store.settings.get('ay_um', self.ax))
        self.cells = min(7, max(1, int(cells)))
        self.update()

    def color(self, layer, index):
        return layer_color(layer['Name'], index, self.layer_colors, layer['Material'], self.material_colors) if self.use_colors else '#93a6b3'

    def region_color(self, region, fallback):
        color=self.material_colors.get(region['material']) if self.use_colors else None
        return color if color and QColor(color).isValid() else fallback

    def material_opacity(self, layer):
        return self.opacity_for_material(layer['Material'])

    def opacity_for_material(self, material):
        return min(1., max(0., float(self.material_opacities.get(material, 100))/100))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'display_panel'):
            self.display_panel.layout().invalidate();self.display_panel.adjustSize()
            self.display_panel.move(self.width()-self.display_panel.width()-12,self.height()-self.display_panel.height()-14)

    def regions(self, name, cells=1):
        self._ensure_geometry_cache()
        key = (name, cells, self.show_holes)
        if key in self._regions_cache:
            return self._regions_cache[key]
        window = (-cells*self.ax/2, cells*self.ax/2, -cells*self.ay/2, cells*self.ay/2)
        result = []
        for region in self.patterns:
            if region['layer'] != name: continue
            if not self.show_holes and region['material'].lower() in ('air','vacuum','air / vacuum'): continue
            for center in periodic_centers(region, self.ax, self.ay, window):
                polygon = clip_polygon(region_polygon(region, center), window)
                if len(polygon) >= 3: result.append((region, tuple(polygon)))
                if len(result) >= 600:
                    self._regions_cache[key] = result
                    return result
        self._regions_cache[key] = result
        return result

    def _ensure_geometry_cache(self):
        # Selection, appearance, visibility and camera changes do not alter the
        # model geometry. Also accept direct attribute updates used by previews.
        signature = (self.ax, self.ay,
            tuple((l['Name'], l['Material'], float(l['Thickness_um'])) for l in self.layers),
            tuple(tuple(sorted(r.items())) for r in self.patterns))
        if signature != self._geometry_signature:
            self._geometry_signature = signature
            self._regions_cache.clear()
            self._stack_cache.clear()
            self._material_clip_cache.clear()
            self._projection_key = None

    def _material_clip(self,key,paths):
        if key not in self._material_clip_cache:
            if len(self._material_clip_cache)>64:self._material_clip_cache.clear()
            cutouts=QPainterPath();cutouts.setFillRule(Qt.FillRule.WindingFill)
            for path in paths:cutouts.addPath(path)
            whole=QPainterPath();whole.addRect(QRectF(self.rect()))
            self._material_clip_cache[key]=whole.subtracted(cutouts)
        return self._material_clip_cache[key]

    @property
    def aperture_paths(self):
        # These diagnostic paths are only needed by geometry inspection. Paint
        # uses the equivalent clipped wall band without any frame-time boolean.
        if self._aperture_paths is None:
            self._aperture_paths = [(name, top.intersected(bottom))
                for name, top, bottom in self._frame_apertures]
        return self._aperture_paths

    def _stack_geometry(self):
        self._ensure_geometry_cache()
        key = (self.cells, self.show_holes, self.exploded)
        if key in self._stack_cache:
            return self._stack_cache[key]
        heights = [.035 if i == 0 else .23 if i == len(self.layers)-1
            else max(.08, min(.26, math.sqrt(max(0., float(l['Thickness_um'])))*.34))
            for i, l in enumerate(self.layers)]
        gap = .16 if self.exploded else .004
        total = sum(heights)+gap*max(0, len(self.layers)-1)
        vertices = QPolygonF([QPointF(-.6, -.6), QPointF(.6, -.6),
                             QPointF(.6, .6), QPointF(-.6, .6)])
        sheet = QPainterPath(); sheet.addPolygon(vertices); sheet.closeSubpath()
        factorx, factory = 1.2/(self.ax*self.cells), 1.2/(self.ay*self.cells)
        z = 0.; slabs = []
        for i, (layer, h) in enumerate(zip(self.layers, heights)):
            openings = []
            holes = QPainterPath(); holes.setFillRule(Qt.FillRule.WindingFill)
            for region, polygon in self.regions(layer['Name'], self.cells):
                opening = QPainterPath()
                opening.addPolygon(QPolygonF([QPointF(x*factorx, y*factory) for x, y in polygon]))
                opening.closeSubpath()
                air = region['material'].lower() in ('air', 'vacuum', 'air / vacuum')
                if air: holes.addPath(opening)
                openings.append((opening, air))
            # Compile the surface once in model space. Affine camera projection
            # preserves its real cutouts, including overlapping air regions.
            surface = sheet.subtracted(holes) if not holes.isEmpty() else sheet
            slabs.append((layer, h, z, i, surface, openings))
            z += h+gap
        result = (total, vertices, slabs)
        self._stack_cache[key] = result
        return result

    def _project_stack(self):
        total, vertices, slabs = self._stack_geometry()
        key = (self._geometry_signature, self.cells, self.show_holes, self.exploded,
               self.width(), self.height(), self.angle, self.elevation, self.zoom)
        if key == self._projection_key:
            return self._projection
        self._material_clip_cache.clear()
        scale = min(self.width()*.46, (self.height()-95)/(total+.64))*self.zoom
        cx, cy = self.width()*.54, self.height()*.49
        cosa, sina = math.cos(self.angle), math.sin(self.angle)
        projected = []
        for layer, h, z, i, surface, openings in slabs:
            transform = QTransform(scale*cosa, scale*sina*self.elevation,
                -scale*sina, scale*cosa*self.elevation, cx, cy+scale*(z-total/2))
            top = transform.map(vertices)
            depth = scale*h
            bottom = QPolygonF([p+QPointF(0, depth) for p in top])
            path = transform.map(surface)
            shadow = path.translated(0, depth+scale*.035)
            projected_openings = []
            for opening, air in openings:
                opening = transform.map(opening)
                bottom_opening = opening.translated(0, depth)
                # For these convex region polygons, the clipped odd-even band
                # is exactly the visible extrusion wall. The intersection of
                # both openings remains transparent to the lower stack.
                walls = QPainterPath(opening)
                walls.addPath(bottom_opening)
                walls.setFillRule(Qt.FillRule.OddEvenFill)
                projected_openings.append((opening, air, bottom_opening, walls))
            projected.append((layer, h, z, i, top, bottom, path, shadow,
                              projected_openings, transform.map(QPointF(-.6, -.6))+QPointF(0, depth/2)))
        self._projection_key = key
        self._projection = projected
        return projected

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = COLORS[theme_manager().mode]
        if theme_manager().style!='glass':
            gradient=QLinearGradient(0,0,self.width(),self.height());gradient.setColorAt(0,QColor(c['panel']).lighter(105));gradient.setColorAt(.5,QColor(c['panel']).darker(118));gradient.setColorAt(1,QColor(c['panel']))
            p.fillRect(self.rect(),gradient)
        self.hits = []
        if len(self.layers) < 3: p.end(); return
        if self.mode == 'Unit cell': self.paint_plan(p, c)
        elif self.mode == 'Cross-section': self.paint_section(p, c)
        else: self.paint_stack(p, c)
        if self.show_axes:
            self.paint_axes(p)
        p.end()

    @staticmethod
    def _lit_color(color, light=0., shade=1., alpha=None):
        """Tint lighting with the actual material color, including user overrides."""
        result = QColor.fromRgbF(*[min(1., max(0., value*shade*(1-light)+light))
            for value in (color.redF(), color.greenF(), color.blueF())], color.alphaF())
        if alpha is not None: result.setAlpha(alpha)
        return result

    def paint_axes(self, p):
        # The xy triad follows the same orbit as the scientific geometry.
        origin = QPointF(38, self.height()-48)
        cosine, sine = math.cos(self.angle), math.sin(self.angle)
        vectors = [('x', QPointF(36*cosine, 36*sine*self.elevation), '#ff626b'),
                   ('y', QPointF(-36*sine, 36*cosine*self.elevation), '#57e38c'),
                   ('z', QPointF(0, -43), '#498dff')]
        font = QFont(p.font()); font.setPointSize(10); font.setBold(True); p.setFont(font)
        for text, direction, color in vectors:
            tip = origin+direction
            length = math.hypot(direction.x(), direction.y())
            unit = direction/length
            normal = QPointF(-unit.y(), unit.x())
            tint = QColor(color)
            p.setPen(QPen(tint, 2.2)); p.drawLine(origin, tip-unit*5)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(tint)
            p.drawPolygon(QPolygonF([tip, tip-unit*8+normal*3.6, tip-unit*8-normal*3.6]))
            p.setPen(tint)
            label = tip+unit*10
            p.drawText(QRectF(label.x()-7, label.y()-9, 16, 18), Qt.AlignmentFlag.AlignCenter, text)

    def paint_plan(self, p, c):
        name = self.selected or self.layers[1]['Name']
        i = next((i for i, l in enumerate(self.layers) if l['Name'] == name), 1)
        if name in self.hidden_layers:
            p.setPen(QColor(c['muted'])); p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Selected layer hidden in preview'); return
        side = min(self.width()-(60 if self.compact else 90), self.height()-(70 if self.compact else 100))*self.zoom
        sx = side / max(self.ax, self.ay); w, h = self.ax*sx, self.ay*sx
        x, y = (self.width()-w)/2, (self.height()-h)/2
        regions=[];transparent=[]
        for r,poly in self.regions(name,3 if self.compact else 1):
            if self.compact:poly=[(px/3,py/3) for px,py in poly]
            polygon=QPolygonF([QPointF(x+w/2+px*sx,y+h/2-py*sx) for px,py in poly])
            air=r['material'].lower() in ('air','vacuum','air / vacuum')
            regions.append((r,polygon,air))
            if not air and self.opacity_for_material(r['material'])<1.:transparent.append(len(regions)-1)
        p.save();p.setOpacity(self.material_opacity(self.layers[i]))
        if transparent:
            paths=[]
            for j in transparent:
                path=QPainterPath();path.addPolygon(regions[j][1]);path.closeSubpath();paths.append(path)
            p.setClipPath(self._material_clip(('plan',self._geometry_signature,name,self.width(),self.height(),self.zoom,self.compact,tuple(transparent)),paths))
        p.setPen(QPen(QColor(c['border']), 1)); p.setBrush(Qt.BrushStyle.NoBrush if self.compact else QColor(self.color(self.layers[i], i)))
        p.drawRect(QRectF(x, y, w, h))
        for r,polygon,air in regions:
            fallback='#929af5' if self.compact else c['panel'] if air else '#a6c5df'
            p.setBrush(QColor(fallback if air else self.region_color(r,fallback)))
            if self.compact:p.setPen(QPen(QColor('#ced7ff'),.8))
            p.save()
            if not air:p.setClipping(False);p.setOpacity(self.opacity_for_material(r['material']))
            p.drawPolygon(polygon);p.restore()
        p.restore();p.setPen(QColor(c['muted']))
        if self.compact:
            p.setPen(QPen(QColor(c['muted']),1))
            yy=y+h+12;p.drawLine(QPointF(x,yy),QPointF(x+w/3,yy))
            for xx in (x,x+w/3):p.drawLine(QPointF(xx,yy-4),QPointF(xx,yy+4))
            p.drawText(QRectF(x,yy+2,w/3,18),Qt.AlignmentFlag.AlignCenter,'a')
            p.drawText(QRectF(x+w/2+5,y+h/2-18,30,18),'r')
        if not self.compact:
            p.drawText(QRectF(10,10,self.width()-20,26),Qt.AlignmentFlag.AlignCenter,f'{name} · top view')
        if not self.compact:
            p.drawText(QRectF(10,self.height()-42,self.width()-20,30),Qt.AlignmentFlag.AlignCenter,f'{self.ax*1000:g} × {self.ay*1000:g} nm · z normal to plane')

    def paint_section(self, p, c):
        n = len(self.layers); heights = [max(.055, min(.24, math.sqrt(max(0.,float(l['Thickness_um'])))*.16)) for l in self.layers]
        total = sum(heights); available = (self.height()-70)*self.zoom; y = 28+(self.height()-70-available)/2
        w = (self.width()-56)*self.zoom; x = (self.width()-w)/2
        for i, (layer, height) in enumerate(zip(self.layers, heights)):
            h = height/total*available
            if layer['Name'] in self.hidden_layers:
                y += h; continue
            sections=[];transparent=[]
            for region in self.patterns:
                if region['layer']!=layer['Name']:continue
                air=region['material'].lower() in ('air','vacuum','air / vacuum')
                if air and not self.show_holes:continue
                for center in periodic_centers(region,self.ax,self.ay,(-self.ax/2,self.ax/2,0,0)):
                    interval=section_interval(region,0,center)
                    if interval is None:continue
                    left,right=max(-self.ax/2,interval[0]),min(self.ax/2,interval[1])
                    if right<=left:continue
                    region_rect=QRectF(x+(left/self.ax+.5)*w,y,(right-left)/self.ax*w,h-2)
                    sections.append((region,region_rect,air))
                    if not air and self.opacity_for_material(region['material'])<1.:transparent.append(len(sections)-1)
            p.save();p.setOpacity(self.material_opacity(layer))
            if transparent:
                paths=[]
                for j in transparent:
                    path=QPainterPath();path.addRect(sections[j][1]);paths.append(path)
                p.setClipPath(self._material_clip(('section',self._geometry_signature,i,self.width(),self.height(),self.zoom,tuple(transparent)),paths))
            rect = QRectF(x, y, w, h-2)
            color = QColor(self.color(layer, i)); p.setBrush(color)
            p.setPen(QPen(QColor(c['accent'] if layer['Name']==self.selected else c['border']), 2 if layer['Name']==self.selected else .7))
            p.drawRect(rect); self.hits.append((rect, layer['Name']))
            for region,region_rect,air in sections:
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(c['bg'] if air else self.region_color(region,'#b6d9ee')))
                p.save()
                if not air:p.setClipping(False);p.setOpacity(self.opacity_for_material(region['material']))
                p.drawRect(region_rect);p.restore()
            p.restore()
            luminance = .2126*color.redF()+.7152*color.greenF()+.0722*color.blueF()
            backdrop=QColor(c['panel']);opacity=self.material_opacity(layer)
            luminance=opacity*luminance+(1-opacity)*(.2126*backdrop.redF()+.7152*backdrop.greenF()+.0722*backdrop.blueF())
            p.setPen(QColor('#102035' if luminance > .5 else '#ffffff'))
            half = i in (0,n-1)
            text = f"{layer['Name']}   ·   {layer['Material']}   ·   "+('∞' if half else f"{float(layer['Thickness_um'])*1000:g} nm")
            p.drawText(rect.adjusted(12, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(p.font()).elidedText(text, Qt.TextElideMode.ElideRight, int(w-20)))
            y += h

    def paint_stack(self, p, c):
        self._frame_apertures = []
        self._aperture_paths = None
        slabs = self._project_stack()
        width, height = self.width(), self.height()
        visible = [slab for slab in slabs if slab[0]['Name'] not in self.hidden_layers]
        # These quiet dashed guides connect the real corresponding corners.
        # Drawing behind the stack naturally hides them beneath solid material.
        if self.exploded and len(visible)>1:
            guide=QColor(c['text']);guide.setAlpha(82 if theme_manager().mode=='dark' else 64)
            pen=QPen(guide,.8,Qt.PenStyle.DashLine);pen.setDashPattern([4,5]);p.setPen(pen)
            for corner in sorted(range(4), key=lambda k: visible[0][4][k].x()):
                if corner==min(range(4),key=lambda k:visible[0][4][k].y()):continue
                p.drawLine(visible[0][5][corner],visible[-1][4][corner])
        # Lower slabs first; upper planes then occlude them in assembled mode.
        for layer,h,z,i,top,bottom,path,shadow,openings,anchor in reversed(slabs):
            if layer['Name'] in self.hidden_layers: continue
            opacity=self.material_opacity(layer)
            p.save();p.setOpacity(opacity)
            region_styles=[(self.region_color(region,'#b6d9ee'),self.opacity_for_material(region['material']))
                for region,_ in self.regions(layer['Name'],self.cells)] if any(not opening[1] for opening in openings) else None
            # A filled region replaces the host in its physical footprint. Its
            # own opacity must reveal geometry beneath rather than a host tint.
            transparent_regions=tuple(j for j,opening in enumerate(openings)
                if not opening[1] and region_styles[j][1]<1.)
            if transparent_regions:
                p.setClipPath(self._material_clip(('stack',i,transparent_regions),[openings[j][0] for j in transparent_regions]))
            color=QColor(self.color(layer,i))
            glass=i==0 and str(layer['Material']).lower() in ('air','vacuum','air / vacuum')
            if glass:color.setAlpha(50)
            # A short, soft cast shadow gives the volume a clear underside.
            # All shadow paths retain the actual holes compiled in model space.
            p.setPen(Qt.PenStyle.NoPen)
            for offset,shadow_alpha in ((1,30),):
                p.save();p.translate(0,offset);p.fillPath(shadow,QColor(0,0,0,shadow_alpha));p.restore()
            center=top.boundingRect().center()
            faces=[]
            for k in (1,2,3,0):
                j=(k+1)%4
                # The opposite exterior walls are covered by the top surface.
                # Keep only the two forward-facing edges of this extrusion.
                if abs(top[j].x()-top[k].x())<.001:continue
                if opacity>=1. and top[j].x() >= top[k].x(): continue
                face=QPolygonF([top[k],top[j],bottom[j],bottom[k]])
                faces.append((k,j))
                left=(top[k].x()+top[j].x())/2<center.x()
                edge=top[j]-top[k]
                normal=QPointF(-edge.y(),edge.x())
                if normal.y()<0:normal=-normal
                normal/=math.hypot(normal.x(),normal.y())
                # The gradient is perpendicular to the sloping top edge. A
                # screen-vertical gradient flattens most of an isometric face
                # to its first/last stops and loses the visible material depth.
                shade=QLinearGradient(top[k],top[k]+normal*((bottom[k]-top[k]).y()*normal.y()))
                shade.setColorAt(0,self._lit_color(color,.30,1.))
                shade.setColorAt(.09,self._lit_color(color,.05,.94 if left else .76))
                shade.setColorAt(.60,self._lit_color(color,0.,.76 if left else .57))
                shade.setColorAt(.88,self._lit_color(color,.03,.89 if left else .70))
                shade.setColorAt(1,self._lit_color(color,.29,.97))
                p.setPen(QPen(QColor(c['border']),1) if self.show_edges else Qt.PenStyle.NoPen);p.setBrush(shade);p.drawPolygon(face)
                # A broad low-opacity reflection stays clipped to this face.
                side_light=QLinearGradient(top[k],top[j]);side_light.setColorAt(0,QColor(255,255,255,0));side_light.setColorAt(.35,QColor(255,255,255,27 if left else 12));side_light.setColorAt(.56,QColor(255,255,255,5));side_light.setColorAt(1,QColor(255,255,255,0))
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(side_light);p.drawPolygon(face)
            bounds=top.boundingRect()
            gradient=QLinearGradient(bounds.topLeft(),bounds.bottomRight())
            gradient.setColorAt(0,self._lit_color(color,.34,.96,58 if glass else None))
            gradient.setColorAt(.20,self._lit_color(color,.07,.89,28 if glass else None))
            gradient.setColorAt(.58,self._lit_color(color,.06,.98,25 if glass else None))
            gradient.setColorAt(.82,self._lit_color(color,.16,1.,45 if glass else None))
            gradient.setColorAt(1,self._lit_color(color,.12,.86,40 if glass else None))
            p.setBrush(gradient);p.setPen(QPen(QColor(c['text']),.8) if self.show_edges else Qt.PenStyle.NoPen);p.drawPath(path)
            # A reflected light strip is material-only: neither it nor the face
            # shading ever fills an aperture with a simulated painted disk.
            sheen=QLinearGradient(bounds.topLeft(),bounds.bottomRight())
            sheen.setColorAt(0,QColor(255,255,255,0));sheen.setColorAt(.25,QColor(255,255,255,0));sheen.setColorAt(.46,QColor(255,255,255,26 if glass else 28));sheen.setColorAt(.58,QColor(255,255,255,7));sheen.setColorAt(.72,QColor(255,255,255,0));sheen.setColorAt(1,QColor(255,255,255,0))
            p.fillPath(path,sheen)
            wall_stops=[(position,self._lit_color(color,light,shade,245))
                for position,light,shade in [(0,0.,.24),(.18,0.,.34),(.54,.02,.54),(.84,.08,.48),(1,.16,.65)]]
            bevel_stops=[(0,self._lit_color(color,0.,.52,175)),(.40,self._lit_color(color,.24,.87,175)),(1,self._lit_color(color,.57,1.,225))]
            lip_stops=[(0,self._lit_color(color,.46,1.,175)),(.50,self._lit_color(color,.25,1.,175)),(1,self._lit_color(color,.70,1.,245))]
            for opening_index,(opening,air,bottom_aperture,walls) in enumerate(openings):
                p.save()
                if not air:p.setClipping(False);p.setOpacity(region_styles[opening_index][1])
                p.setClipPath(opening)
                if air:
                    self._frame_apertures.append((layer['Name'],opening,bottom_aperture))
                    bounds=opening.boundingRect();bottom_bounds=bottom_aperture.boundingRect()
                    shade=QLinearGradient(bounds.center().x(),bounds.top(),bounds.center().x(),bottom_bounds.bottom())
                    # Only opening-minus-bottom is an exposed inner wall. The
                    # overlap remains transparent, including ellipse/rectangle
                    # regions and rotated cameras. The shaded band is one path.
                    shade.setStops(wall_stops)
                    p.setPen(Qt.PenStyle.NoPen);p.setBrush(shade);p.drawPath(walls)
                else:p.fillPath(opening,QColor(region_styles[opening_index][0]))
                p.restore()
                # A narrow native rim describes the bevel at the exact region
                # boundary. No large surface clip or boolean runs per hole.
                bounds=opening.boundingRect()
                bevel=QLinearGradient(bounds.topLeft(),bounds.bottomLeft())
                bevel.setStops(bevel_stops)
                p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QBrush(bevel),2.1));p.drawPath(opening)
                lip=QLinearGradient(bounds.topLeft(),bounds.bottomLeft())
                lip.setStops(lip_stops)
                p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QBrush(lip),.8));p.drawPath(opening)
            # Crisp luminous top, bottom and vertical corner rims describe a
            # thick slab even with the optional diagnostic Edges turned off.
            rim=self._lit_color(color,.63,1.,185 if glass else 205)
            p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(rim,.9));p.drawPolygon(top)
            for k,j in faces:
                p.setPen(QPen(self._lit_color(color,.36,1.,140),.65));p.drawLine(bottom[k],bottom[j])
            near=max(range(4),key=lambda k:top[k].y())
            p.setPen(QPen(self._lit_color(color,.65,1.,205),.8));p.drawLine(top[near],bottom[near])
            if layer['Name']==self.selected:
                accent=QColor(c['accent']);accent.setAlpha(160)
                p.setPen(QPen(accent,1.25));p.drawPolygon(top)
            p.restore()
            self.hits.append((path,layer['Name']))
        p.setPen(QColor(c['muted']))
        # Label distribution uses screen height, not physical layer thickness.
        labelx=12;last_label_bottom=8;self.label_bounds=[]
        for j,(layer,h,z,i,top,bottom,path,shadow,openings,anchor) in enumerate(slabs):
            if layer['Name'] in self.hidden_layers: continue
            remaining=sum(1 for candidate in slabs[j:] if candidate[0]['Name'] not in self.hidden_layers)
            label_height=24
            labely=max(last_label_bottom,min(height-12-remaining*label_height,anchor.y()-14))
            leader=QColor(c['text']);leader.setAlpha(92 if theme_manager().mode=='dark' else 80)
            p.setPen(QPen(leader,.7));p.drawLine(anchor,QPointF(labelx+114,labely+12))
            p.setPen(QColor(c['text']));font=QFont(p.font());font.setPointSize(9);p.setFont(font)
            bounds=QRectF(labelx,labely,min(114,width-24),label_height)
            p.drawText(bounds,Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,QFontMetrics(font).elidedText(str(layer['Name']),Qt.TextElideMode.ElideRight,int(bounds.width())))
            self.label_bounds.append(bounds);last_label_bottom=bounds.bottom()
            self.hits.append((bounds,layer['Name']))
        p.setPen(QColor(c['muted']))

    def mousePressEvent(self, e):
        self.drag=e.position();self.dragged=False

    def mouseMoveEvent(self,e):
        if self.drag is not None and self.mode=='3D Stack':
            delta=e.position()-self.drag
            if abs(delta.x())+abs(delta.y())>2:self.dragged=True
            self.angle+=delta.x()*.009;self.elevation=max(.15,min(.85,self.elevation+delta.y()*.004))
            self.drag=e.position();self.update()

    def mouseReleaseEvent(self,e):
        if not self.dragged:
            for rect,name in reversed(self.hits):
                if rect.contains(e.position()):self.layer_selected.emit(name);break
        self.drag=None

    def wheelEvent(self,e):
        self.zoom=max(.55,min(1.5,self.zoom*(1.1 if e.angleDelta().y()>0 else 1/1.1)));self.update();e.accept()


class DeviceBuilderPage(StructurePage):
    continue_requested = pyqtSignal()

    def __init__(self,store,parent=None,laser=False):
        self.laser=laser
        super().__init__(store,parent)
        theme_manager().changed.connect(self.update)

    def paintEvent(self,event):
        super().paintEvent(event)

    def _build(self):
        super()._build()
        root=self.layout()
        # Reparent original controls, retaining all validated edit/undo/export operations.
        def detach(layout):
            while layout.count():
                item=layout.takeAt(0)
                if item.widget():item.widget().hide()
                elif item.layout():detach(item.layout())
        detach(root)
        root.setContentsMargins(0,0,0,0);root.setSpacing(10)
        self.look_selector=QComboBox(self);self.look_selector.setObjectName('structureLookSelector')
        for key,(label,style,mode) in LOOKS.items():self.look_selector.addItem(label,key)
        self.look_selector.setCurrentIndex(self.look_selector.findData(theme_manager().look))
        self.look_selector.currentIndexChanged.connect(lambda:theme_manager().apply_look(self.look_selector.currentData()))
        theme_manager().changed.connect(self._refresh_look)
        # The complete region and repeat tools remain available in a separate editor.
        self.advanced_editor=QDialog(self);self.advanced_editor.setWindowTitle('Structure · advanced editing');self.advanced_editor.resize(560,680)
        advanced_layout=QVBoxLayout(self.advanced_editor);advanced_layout.addWidget(self.tabs);self.tabs.show()
        rename_apply=QPushButton('Apply layer edits');rename_apply.clicked.connect(lambda:self.layer_action('apply'));self.layer_editor.layout().insertWidget(self.layer_editor.layout().count()-1,rename_apply)
        def advanced(tab):
            self.tabs.setCurrentIndex(tab);self.advanced_editor.show();self.advanced_editor.raise_()
        def title(text):
            label=QLabel(text);label.setObjectName('sectionTitle');return label
        def line(layout):
            separator=QFrame();separator.setObjectName('builderSeparator');separator.setFixedHeight(1);layout.addWidget(separator)
        splitter=QSplitter(Qt.Orientation.Horizontal);splitter.setObjectName('approvedBuilderSplitter');splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10);root.addWidget(splitter,1);self.builder_splitter=splitter
        rail=WorkspacePanel();layout=QVBoxLayout(rail);layout.setContentsMargins(12,16,12,12);layout.setSpacing(12)
        layout.addWidget(title('Layer Stack'));line(layout)
        toolbar=QHBoxLayout();toolbar.setSpacing(5)
        for op,text in [('below','+ Add'),('duplicate','Duplicate'),('delete','Delete')]:
            w=self.findChild(QPushButton,'layer_'+op);w.setText(text);toolbar.addWidget(w);w.show()
        layout.addLayout(toolbar)
        self.layer_list.setItemDelegate(StackRowDelegate(self.layer_list));self.layer_list.setMinimumWidth(270);self.layer_list.setSpacing(0)
        layout.addWidget(self.layer_list,1);self.layer_list.show();self.layer_list.itemChanged.connect(self._layer_visibility_changed)
        bottom=QHBoxLayout()
        for op,text in [('up','↑'),('down','↓')]:
            w=self.findChild(QPushButton,'layer_'+op);w.setText(text);w.setMaximumWidth(42);bottom.addWidget(w);w.show()
        repeat=QPushButton('Repeat…');repeat.clicked.connect(lambda:advanced(2));bottom.addWidget(repeat)
        undo=self.findChild(QPushButton,'undoStructure');undo.setText('Undo');bottom.addWidget(undo);undo.show();layout.addLayout(bottom)
        self.summary.setWordWrap(True);self.summary.hide();splitter.addWidget(rail)
        center=QWidget();cv=QVBoxLayout(center);cv.setContentsMargins(0,0,0,0);cv.setSpacing(10)
        preview=WorkspacePanel();pv=QVBoxLayout(preview);pv.setContentsMargins(12,16,12,10);pv.setSpacing(8)
        viewbar=QHBoxLayout();viewbar.addWidget(title('Geometry Viewer'));viewbar.addStretch();self.view_buttons={}
        for label in ('3D Stack','Cross-section','Unit cell'):
            w=QPushButton(label);w.setCheckable(True);w.setProperty('viewTab',True);w.clicked.connect(lambda checked=False,m=label:self.set_geometry_view(m));viewbar.addWidget(w);self.view_buttons[label]=w
        pv.addLayout(viewbar);line(pv)
        self.viewport=GeometryViewport();self.viewport.layer_selected.connect(self.select_layer);pv.addWidget(self.viewport,1)
        # Display toggles float over the lower right of the viewer, as in B.
        self.viewport.display_panel=WorkspacePanel(self.viewport);display=QVBoxLayout(self.viewport.display_panel);display.setContentsMargins(12,10,12,10);display.setSpacing(6)
        self.display_controls={}
        for key,text,value in [('show_holes','Show holes',True),('use_colors','Layer colors',True),('show_edges','Edges',False),('show_axes','Axes',True)]:
            control=QCheckBox(text);control.setObjectName('geometry_'+key);control.setChecked(value);control.toggled.connect(lambda checked,k=key:self.set_display_option(k,checked));display.addWidget(control);self.display_controls[key]=control
        self.viewport.display_panel.adjustSize()
        options=QHBoxLayout();options.addWidget(QLabel('Cells'));options.addWidget(self.cells);self.cells.show()
        self.assembly=QComboBox();self.assembly.setObjectName('stackAssembly');self.assembly.addItems(['Assembled','Exploded']);self.assembly.setCurrentIndex(1);self.assembly.currentIndexChanged.connect(self.draw_preview);options.addWidget(self.assembly)
        for text,factor in [('−',1/1.15),('+',1.15)]:
            zoom=QPushButton(text);zoom.setMaximumWidth(32);zoom.clicked.connect(lambda checked=False,f=factor:self.zoom_geometry(f));options.addWidget(zoom)
        reset=QPushButton('Reset view');reset.clicked.connect(lambda:self.draw_preview(reset=True));options.addWidget(reset);options.addStretch();pv.addLayout(options)
        self.preview_note.hide()
        cv.addWidget(preview,1)
        geometry_summary=WorkspacePanel();gs=QVBoxLayout(geometry_summary);gs.setContentsMargins(16,12,16,14);gs.addWidget(title('Geometry Summary'))
        metrics=QGridLayout();self.geometry_metrics={}
        for index,(key,text) in enumerate([('period','Lattice period'),('radius','Hole radius'),('thickness','Total thickness'),('layers','Finite layers'),('patterned','Patterned layers')]):
            metric=QLabel();metric.setObjectName('metricValue');caption=QLabel(text);caption.setObjectName('metricLabel');metric.setWordWrap(True)
            metrics.addWidget(caption,0,index);metrics.addWidget(metric,1,index);self.geometry_metrics[key]=metric
        gs.addLayout(metrics);cv.addWidget(geometry_summary);splitter.addWidget(center)
        inspector=WorkspacePanel();ins=QVBoxLayout(inspector);ins.setContentsMargins(14,16,14,14);ins.setSpacing(10);self.inspector_title=title('Layer Properties');ins.addWidget(self.inspector_title);line(ins)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);body=QWidget();form_layout=QVBoxLayout(body);form_layout.setContentsMargins(0,0,2,0);form_layout.setSpacing(10);scroll.setWidget(body);ins.addWidget(scroll,1)
        selection_row=QHBoxLayout();selection_row.addWidget(QLabel('Layer'))
        self.layer_selector=QComboBox();self.layer_selector.setObjectName('selectedLayerName');self.layer_selector.setAccessibleName('Selected layer')
        self.layer_selector.setMinimumContentsLength(8);self.layer_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.layer_selector.currentIndexChanged.connect(self._select_layer_choice);selection_row.addWidget(self.layer_selector,1);form_layout.addLayout(selection_row)
        properties=QFormLayout();properties.setSpacing(6)
        for label,widget in [('Material',self.layer_material),('Thickness',self.layer_thickness)]:properties.addRow(label,widget);widget.show()
        form_layout.addLayout(properties)
        color_row=QHBoxLayout();self.layer_color_button=QPushButton('Layer color…');self.layer_color_button.setObjectName('customizeLayerColor');self.layer_color_button.clicked.connect(self.choose_layer_color);color_row.addWidget(self.layer_color_button)
        reset_color=QPushButton('Reset');reset_color.setObjectName('resetLayerColor');reset_color.clicked.connect(self.reset_layer_color);color_row.addWidget(reset_color);form_layout.addLayout(color_row)
        from PyQt6.QtWidgets import QSlider
        opacity=QGridLayout();opacity.setHorizontalSpacing(10);opacity.setVerticalSpacing(4)
        self.material_opacity_label=QLabel('Preview opacity')
        self.material_opacity_value=QLabel('100%');self.material_opacity_value.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.material_opacity=QSlider(Qt.Orientation.Horizontal);self.material_opacity.setObjectName('materialPreviewOpacity')
        self.material_opacity.setRange(0,100);self.material_opacity.setTracking(False)
        self.material_opacity.setAccessibleName('Preview opacity for the selected material')
        self.material_opacity.valueChanged.connect(self._apply_material_opacity)
        self.reset_material_opacity_button=QPushButton('Reset');self.reset_material_opacity_button.setObjectName('resetMaterialPreviewOpacity')
        self.reset_material_opacity_button.clicked.connect(self.reset_material_opacity)
        opacity.addWidget(self.material_opacity_label,0,0);opacity.addWidget(self.material_opacity_value,0,1)
        opacity.addWidget(self.material_opacity,1,0,1,2);opacity.addWidget(self.reset_material_opacity_button,1,2)
        opacity.setColumnStretch(0,1);form_layout.addLayout(opacity);line(form_layout)
        self.quick_region=QFrame();qr=QVBoxLayout(self.quick_region);qr.setContentsMargins(0,0,0,0);qr.setSpacing(6);qr.addWidget(title('Pattern'))
        quick_form=QFormLayout();quick_form.setSpacing(6);self.quick_shape=QComboBox();self.quick_shape.addItems(['Circle','Ellipse','Rectangle'])
        self.quick_fill=QComboBox();self.quick_fill.setMinimumContentsLength(9);self.quick_fill.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.quick_radius=QDoubleSpinBox();self.quick_radius.setRange(.001,1e7);self.quick_radius.setDecimals(3);self.quick_radius_label=QLabel('Hole radius')
        quick_form.addRow(self.quick_radius_label,self.quick_radius)
        self.lattice_type=QComboBox();self.lattice_type.setObjectName('latticeType');self.lattice_type.addItems(['Square','Rectangular']);self.lattice_type.currentIndexChanged.connect(lambda i:self.square_lattice.setChecked(i==0));self.square_lattice.toggled.connect(lambda v:self.lattice_type.setCurrentIndex(0 if v else 1))
        quick_form.addRow('Lattice',self.lattice_type);quick_form.addRow(self.lattice_x_label,self.lattice_x);quick_form.addRow(self.lattice_y_label,self.lattice_y)
        for w in (self.lattice_x_label,self.lattice_x,self.lattice_y_label,self.lattice_y):w.show()
        quick_form.addRow('Pattern type',self.quick_shape);quick_form.addRow('Fill material',self.quick_fill)
        self.quick_radius_y=QDoubleSpinBox();self.quick_radius_y.setRange(.001,1e7);self.quick_radius_y.setDecimals(3);self.quick_radius_y_label=QLabel('Y radius');quick_form.addRow(self.quick_radius_y_label,self.quick_radius_y)
        self.quick_angle=QDoubleSpinBox();self.quick_angle.setRange(-360,360);self.quick_angle.setSuffix('°');self.quick_angle_label=QLabel('Rotation');quick_form.addRow(self.quick_angle_label,self.quick_angle)
        self.quick_shape.currentIndexChanged.connect(self._quick_shape_labels);qr.addLayout(quick_form);self._quick_shape_labels()
        # Fill editing remains in the complete advanced region editor. Keep the
        # reference inspector focused on radius, period, and shape.
        quick_form.labelForField(self.quick_fill).hide();self.quick_fill.hide()
        lattice_row=QHBoxLayout();apply=self.findChild(QPushButton,'applyLattice');apply.setText('Apply lattice');lattice_row.addWidget(apply);apply.show();lattice_row.addWidget(self.units);self.units.show();qr.addLayout(lattice_row)
        from qt_lattice_diagram import LatticeDiagram
        self.pattern_view=LatticeDiagram();qr.addWidget(self.pattern_view);form_layout.addWidget(self.quick_region)
        self.region_link=QPushButton('Advanced editing…');self.region_link.clicked.connect(lambda:advanced(1));layout.addWidget(self.region_link);form_layout.addStretch()
        actions=QHBoxLayout();apply_layer=self.findChild(QPushButton,'applyLayer');apply_layer.setText('Apply layer');actions.addWidget(apply_layer);apply_layer.show()
        quick_apply=QPushButton('Apply pattern');quick_apply.setObjectName('quickApplyPattern');quick_apply.setProperty('primary',True);quick_apply.clicked.connect(self.apply_quick_region);actions.addWidget(quick_apply);ins.addLayout(actions)
        validate=QPushButton('✓  Validate Structure',self);validate.setObjectName('validateDeviceStructure');validate.clicked.connect(self.validate_device);validate.hide()
        self.continue_button=QPushButton('Continue to Optical Modes →' if self.laser else 'Continue to Materials →',self);self.continue_button.setObjectName('structureContinue');self.continue_button.setProperty('primary',True);self.continue_button.clicked.connect(self.continue_requested);self.continue_button.hide()
        # Global appearance lives in Settings. Retain hidden adapters for saved
        # integrations and keep this inspector focused on the selected layer.
        self.look_buttons={}
        for key,(label,style,mode) in LOOKS.items():
            button=QPushButton(label,self);button.setCheckable(True);button.setProperty('viewTab',True);button.clicked.connect(lambda checked=False,k=key:theme_manager().apply_look(k));button.hide();self.look_buttons[key]=button
        self.look_selector.hide();splitter.addWidget(inspector);splitter.setSizes([350,720,370]);splitter.setStretchFactor(0,0);splitter.setStretchFactor(1,1);splitter.setStretchFactor(2,0)
        root.addWidget(self.status);self.status.hide();self._refresh_look()
        self.layer_material.setMinimumContentsLength(8)
        for field in (self.quick_radius,self.quick_radius_y):field.setDecimals(1)
        self.layer_color_button.setText('Layer color…')
        self.cells.setCurrentIndex(1);self.set_geometry_view('3D Stack');self._lattice_mode_changed(True)

    def _lattice_mode_changed(self,square):
        super()._lattice_mode_changed(square)
        self.lattice_x_label.setText('Lattice constant a' if square else 'Period X')
        if hasattr(self,'lattice_type'):
            with QSignalBlocker(self.lattice_type):self.lattice_type.setCurrentIndex(0 if square else 1)

    def _load_region(self):
        super()._load_region()
        if not hasattr(self,'quick_region'):return
        with QSignalBlocker(self.quick_shape),QSignalBlocker(self.quick_fill),QSignalBlocker(self.quick_radius):
            self.quick_shape.setCurrentIndex(self.shape.currentIndex());self.quick_fill.clear()
            for i in range(self.region_material.count()):self.quick_fill.addItem(self.region_material.itemText(i),self.region_material.itemData(i))
            self.quick_fill.setCurrentIndex(self.region_material.currentIndex());self.quick_radius.setValue(self.region_sx.value());self.quick_radius.setSuffix(' '+self._unit)
        self.quick_radius_label.setText(self.sx_label.text());self.quick_region.setEnabled(self.region_editor.isEnabled())
        if hasattr(self,'quick_radius_y'):
            self.quick_radius_y.setValue(self.region_sy.value());self.quick_radius_y.setSuffix(' '+self._unit)
            self.quick_angle.setValue(self.region_angle.value());self._quick_shape_labels()
        if self.laser:self.layer_hint.setText('Applies to this layer in the Laser / PCSEL workspace.')

    def apply_quick_region(self):
        self.shape.setCurrentIndex(self.quick_shape.currentIndex());self.region_material.setCurrentIndex(self.region_material.findData(self.quick_fill.currentData()))
        self.region_sx.setValue(self.quick_radius.value())
        self.region_sy.setValue(self.quick_radius_y.value());self.region_angle.setValue(self.quick_angle.value())
        self.region_action('add' if self._region in (None,'new','') else 'apply')

    def _quick_shape_labels(self,*args):
        shape=self.quick_shape.currentText();noncircle=shape!='Circle'
        self.quick_radius_label.setText('Radius' if shape=='Circle' else 'X radius' if shape=='Ellipse' else 'Full width X')
        self.quick_radius_y_label.setText('Y radius' if shape=='Ellipse' else 'Full width Y')
        for widget in (self.quick_radius_y,self.quick_radius_y_label,self.quick_angle,self.quick_angle_label):widget.setVisible(noncircle)

    def set_geometry_view(self,mode):
        if not hasattr(self,'viewport'):return
        self.viewport.mode=mode
        for label,w in self.view_buttons.items():w.setChecked(label==mode)
        self.assembly.setVisible(mode=='3D Stack')
        self.draw_preview()

    def _refresh_look(self,*args):
        with QSignalBlocker(self.look_selector):self.look_selector.setCurrentIndex(self.look_selector.findData(theme_manager().look))
        for key,button in getattr(self,'look_buttons',{}).items():button.setChecked(key==theme_manager().look)
        self.update()

    def _select_layer_choice(self,index):
        if index>=0:self.select_layer(self.layer_selector.itemData(index))

    def set_display_option(self,key,value):
        setattr(self.viewport,key,bool(value));self.viewport.update()

    def zoom_geometry(self,factor):
        self.viewport.zoom=max(.55,min(1.5,self.viewport.zoom*factor));self.viewport.update()

    def _layer_visibility_changed(self,item):
        if not hasattr(self,'viewport'):return
        name=item.data(Qt.ItemDataRole.UserRole)
        if item.checkState()==Qt.CheckState.Checked:self.viewport.hidden_layers.discard(name)
        else:self.viewport.hidden_layers.add(name)
        self.viewport.update()

    def set_layer_color(self,color):
        if not self._selected:return
        color=QColor(color)
        if not color.isValid():raise ValueError('Choose a valid layer color.')
        colors=dict(getattr(self.store,'appearance',{}).get('layer_colors',{}));colors[self._selected]=color.name()
        self.store.update_appearance({'layer_colors':colors})

    def choose_layer_color(self):
        selected=next((layer for layer in self.viewport.layers if layer['Name']==self._selected),None)
        if selected is None:return
        color=QColorDialog.getColor(QColor(self.viewport.color(selected,self.viewport.layers.index(selected))),self,'Color for '+self._selected)
        if color.isValid():
            try:self.set_layer_color(color)
            except (ValueError,OSError) as exc:self._message(exc,True)

    def reset_layer_color(self):
        colors=dict(getattr(self.store,'appearance',{}).get('layer_colors',{}));colors.pop(self._selected,None)
        try:self.store.update_appearance({'layer_colors':colors})
        except (ValueError,OSError) as exc:self._message(exc,True)

    def _preview_material(self):
        selected=next((layer for layer in rows(self.store.layers,LAYER_COLS) if layer['Name']==self._selected),None)
        return selected['Material'] if selected is not None else None

    def set_material_opacity(self,value):
        material=self._preview_material()
        if material is None:return
        opacities=dict(getattr(self.store,'appearance',{}).get('material_opacities',{}))
        opacities[material]=value
        self.store.update_appearance({'material_opacities':opacities})

    def _apply_material_opacity(self,value):
        try:self.set_material_opacity(value)
        except (ValueError,OSError) as exc:
            self._message(exc,True)
            self.draw_preview()

    def reset_material_opacity(self):
        material=self._preview_material()
        if material is None:return
        opacities=dict(getattr(self.store,'appearance',{}).get('material_opacities',{}))
        opacities.pop(material,None)
        try:self.store.update_appearance({'material_opacities':opacities})
        except (ValueError,OSError) as exc:self._message(exc,True)

    def layer_action(self,action):
        old=self._selected
        color=getattr(self.store,'appearance',{}).get('layer_colors',{}).get(old)
        super().layer_action(action)
        if color and old!=self._selected and action in ('apply','duplicate'):
            try:self.set_layer_color(color)
            except (ValueError,OSError) as exc:self._message(exc,True)

    def draw_preview(self,*args,reset=False):
        if not hasattr(self,'viewport'):return
        if reset:self.viewport.angle=-math.pi/4;self.viewport.elevation=.48;self.viewport.zoom=1.
        self.viewport.exploded=self.assembly.currentIndex()==1
        self.viewport.set_model(self.store,self._selected,self.cells.currentIndex()*2+1)
        layers=self.viewport.layers; names={layer['Name'] for layer in layers}
        if hasattr(self,'layer_selector'):
            with QSignalBlocker(self.layer_selector):
                ordered_names=[layer['Name'] for layer in layers]
                if ordered_names!=[self.layer_selector.itemData(i) for i in range(self.layer_selector.count())]:
                    self.layer_selector.clear()
                    for name in ordered_names:self.layer_selector.addItem(name,name)
                self.layer_selector.setCurrentIndex(self.layer_selector.findData(self._selected))
                self.layer_selector.setEnabled(bool(layers))
                self.layer_selector.setToolTip(self._selected or 'Select a layer')
        if hasattr(self,'pattern_view'):self.pattern_view.set_model(self.store,self._selected,1)
        self.viewport.hidden_layers.intersection_update(names)
        with QSignalBlocker(self.layer_list):
            for i,layer in enumerate(layers):
                item=self.layer_list.item(i)
                if item is None:continue
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked if layer['Name'] in self.viewport.hidden_layers else Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole+2,layer_color(layer['Name'],i,self.viewport.layer_colors,layer['Material'],self.viewport.material_colors))
                item.setData(Qt.ItemDataRole.UserRole+3,'∞' if i in (0,len(layers)-1) else f'{float(layer["Thickness_um"])*1000:g} nm')
                item.setToolTip('Checkbox controls preview visibility only. Select a layer and use Layer color to customize it.')
        self.layer_list.viewport().update()
        if hasattr(self,'layer_color_button'):
            custom=self.viewport.layer_colors.get(self._selected)
            self.layer_color_button.setText('Layer color…');self.layer_color_button.setToolTip(custom or 'Customize the selected layer color')
        if hasattr(self,'material_opacity'):
            material=self._preview_material()
            opacities=getattr(self.store,'appearance',{}).get('material_opacities',{})
            opacity=opacities.get(material,100)
            with QSignalBlocker(self.material_opacity):self.material_opacity.setValue(round(opacity))
            self.material_opacity_value.setText(f'{opacity:g}%')
            self.material_opacity.setEnabled(material is not None)
            self.reset_material_opacity_button.setEnabled(material in opacities)
            tooltip=f'Preview only: opacity for all layers using {material}. Optical n/k values are unchanged.' if material is not None else 'Select a layer to set its material preview opacity.'
            for control in (self.material_opacity_label,self.material_opacity,self.material_opacity_value,self.reset_material_opacity_button):control.setToolTip(tooltip)
        if hasattr(self,'geometry_metrics'):
            scale=self._display_factor();unit=self._unit
            self.geometry_metrics['period'].setText(f'{self.viewport.ax*scale:g} × {self.viewport.ay*scale:g} {unit}')
            circles=[r for r in self.viewport.patterns if r['layer']==self._selected and r['shape']=='circle' and r['material'].lower() in ('air','vacuum','air / vacuum')]
            self.geometry_metrics['radius'].setText(f'{circles[0]["sx"]*scale:g} {unit}' if len(circles)==1 else 'Multiple' if len(circles)>1 else '—')
            self.geometry_metrics['thickness'].setText(f'{sum(float(l["Thickness_um"]) for l in layers[1:-1])*scale:g} {unit}')
            self.geometry_metrics['layers'].setText(str(max(0,len(layers)-2)))
            self.geometry_metrics['patterned'].setText(str(len({r['layer'] for r in self.viewport.patterns})))
        if hasattr(self,'inspector_title'):self.inspector_title.setText('Layer properties')

    def validate_device(self):
        try:
            validate_structure(self.store.materials,self.store.layers,self.store.patterns)
            self.status.setText('Structure is valid · ready for the next step')
        except ValueError as exc:self.status.setText(str(exc))
        self.status.show()
