"""Native interactive inspection of Cartesian photonic-crystal primitives.

This is a geometry display, not a Boolean material mesh or a field solution.
Only camera interaction is reused from the field canvas; no layered-device
coordinates, fields, physical-depth convention or colorbar are inherited.
"""
from __future__ import annotations

import copy
import itertools
import math

import numpy as np
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF

from qt_common import COLORS, theme_manager
from qt_native_field_volume import NativeVolumeCanvas


def _vector(value, name):
    try:
        result = np.array(value, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(name+' needs three finite Cartesian values.') from exc
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(name+' needs three finite Cartesian values.')
    return result


def _positive(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(name+' must be positive and finite.') from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(name+' must be positive and finite.')
    return result


def _readonly(values):
    result = np.array(values, dtype=float, copy=True)
    result.setflags(write=False)
    return result


def _box(axes):
    signs = np.asarray(list(itertools.product((-1., 1.), repeat=3)))
    corners = signs @ axes / 2
    edges = [(i, j) for i in range(8) for j in range(i+1, 8) if np.count_nonzero(signs[i] != signs[j]) == 1]
    faces = []
    for direction in range(3):
        others = [i for i in range(3) if i != direction]
        for side in (-1, 1):
            ids = []
            for first, second in ((-1,-1),(1,-1),(1,1),(-1,1)):
                s = np.zeros(3); s[direction] = side; s[others] = [first, second]
                ids.append(int(np.flatnonzero(np.all(signs == s, axis=1))[0]))
            faces.extend([corners[ids[:3]], corners[[ids[0], ids[2], ids[3]]]])
    return corners, np.asarray(faces), corners[np.asarray(edges)]


def primitive_mesh(item, segments=24, rings=12):
    """Return real 3D triangles and exact/analytic-outline samples in units a."""
    center = _vector(item.get('center', [0.,0.,0.]), 'Object center')
    shape = item.get('shape')
    theta = np.linspace(0, 2*np.pi, segments, endpoint=False)
    loop = np.column_stack([np.cos(theta), np.sin(theta)])
    wires = []
    if shape == 'block':
        size = _vector(item.get('size'), 'Block size')
        if np.any(size <= 0):
            raise ValueError('Block size must be positive on all three axes.')
        axes = np.asarray([_vector(a, 'Block axis') for a in item.get('axes', np.eye(3))])
        if axes.shape != (3,3):
            raise ValueError('Block needs three independent axes.')
        norms = np.linalg.norm(axes, axis=1)
        if np.any(norms <= 0) or abs(np.linalg.det(axes/norms[:,None])) < 1e-10:
            raise ValueError('Block axes must be nonzero and independent.')
        _, faces, edges = _box(axes/norms[:,None]*size[:,None])
        wires = list(edges)
    elif shape == 'sphere':
        radius = _positive(item.get('radius'), 'Sphere radius')
        latitudes = np.linspace(0, np.pi, rings+1)
        layers = [np.column_stack([np.sin(phi)*loop, np.full(segments, np.cos(phi))])*radius for phi in latitudes]
        faces = []
        for j in range(rings):
            for i in range(segments):
                nxt = (i+1)%segments
                if j > 0:
                    faces.append([layers[j][i], layers[j+1][i], layers[j][nxt]])
                if j < rings-1:
                    faces.append([layers[j][nxt], layers[j+1][i], layers[j+1][nxt]])
        smooth = np.linspace(0, 2*np.pi, 97)
        for axis in range(3):
            points = np.zeros((len(smooth),3)); other = [i for i in range(3) if i != axis]
            points[:,other] = radius*np.column_stack([np.cos(smooth),np.sin(smooth)])
            wires.append(points)
    elif shape == 'cylinder':
        radius = _positive(item.get('radius'), 'Cylinder radius')
        height = _positive(item.get('height'), 'Cylinder height')
        direction = _vector(item.get('axis', [0.,0.,1.]), 'Cylinder axis')
        if np.linalg.norm(direction) <= 0:
            raise ValueError('Cylinder axis must be nonzero.')
        direction /= np.linalg.norm(direction)
        first = np.eye(3)[int(np.argmin(abs(direction)))]; first = np.cross(direction, first); first /= np.linalg.norm(first)
        second = np.cross(direction, first)
        rim = radius*(loop[:,0,None]*first+loop[:,1,None]*second)
        lower, upper = rim-direction*height/2, rim+direction*height/2
        faces = []
        for i in range(segments):
            nxt = (i+1)%segments
            faces.extend([[lower[i],lower[nxt],upper[nxt]],[lower[i],upper[nxt],upper[i]],
                          [-direction*height/2,lower[nxt],lower[i]],[direction*height/2,upper[i],upper[nxt]]])
        wires = [np.vstack([row,row[0]]) for row in (lower,upper)]
        wires += [np.asarray([lower[i],upper[i]]) for i in range(0,segments,max(1,segments//4))]
    else:
        raise ValueError('The 3D view supports sphere, finite cylinder and block primitives.')
    faces = np.asarray(faces, dtype=float)
    # Orient triangles consistently outward for material lighting.
    normals = np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
    inward = np.sum(normals*faces.mean(axis=1),axis=1) < 0
    faces[inward] = faces[inward][:,[0,2,1]]
    faces = faces+center
    if not np.isfinite(faces).all():
        raise ValueError('Primitive coordinates exceed the finite display range.')
    return _readonly(faces), tuple(_readonly(row+center) for row in wires)


def crystal_scene(cfg, repeat=1):
    """Build a bounded immutable display without consulting solver/runtime inputs."""
    if not isinstance(cfg, dict) or cfg.get('dimension', 3) != 3:
        raise ValueError('The 3D crystal view requires a three-dimensional crystal.')
    if repeat not in (1,2,3):
        raise ValueError('Display one, two or three cells along each lattice vector.')
    lattice = np.asarray([_vector(a, 'Lattice vector') for a in cfg.get('lattice_vectors', [])])
    if lattice.shape != (3,3):
        raise ValueError('Supply three independent real-space lattice vectors.')
    norms = np.linalg.norm(lattice, axis=1)
    if np.any(norms <= 0) or abs(np.linalg.det(lattice/norms[:,None])) < 1e-10:
        raise ValueError('Real-space lattice vectors must be nonzero and independent.')
    background = _positive(cfg.get('background_epsilon', 1.), 'Background permittivity')
    objects = cfg.get('geometry', [])
    if not isinstance(objects, list) or len(objects) > 500:
        raise ValueError('The interactive preview supports up to 500 editable primitives.')
    # Resolution changes only the display mesh, never the solver or saved inputs.
    if repeat == 1 and len(objects) <= 16:
        segments, rings = 64,32
    elif (repeat == 1 and len(objects) <= 55) or len(objects)*repeat**3 <= 8:
        segments, rings = 32,16
    else:
        segments, rings = 16,8
    indices = list(itertools.product(range(-(repeat//2),repeat-repeat//2), repeat=3))
    corners, _, cell_edges = _box(lattice)
    cells = []
    meshes = []
    ids = set()
    face_count = 0
    for number, item in enumerate(objects):
        if not isinstance(item, dict):
            raise ValueError('Every primitive must be an object.')
        identity = item.get('id', 'primitive-'+str(number+1))
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError('Primitive identities must be unique nonempty text.')
        ids.add(identity)
        epsilon = _positive(item.get('epsilon'), 'Object permittivity')
        faces, wires = primitive_mesh(item, segments, rings)
        interaction_faces = primitive_mesh(item, 8, 4)[0] if item.get('shape') != 'block' else faces
        face_count += len(faces)*repeat**3
        if face_count > 100000:
            raise ValueError('This repeated preview exceeds 100,000 display triangles. Show fewer cells or primitives.')
        for index in indices:
            translation = np.asarray(index)@lattice
            meshes.append(dict(id=identity,name=str(item.get('name') or identity),epsilon=epsilon,
                image=tuple(index),faces=_readonly(faces+translation),interaction_faces=_readonly(interaction_faces+translation),
                wires=tuple(_readonly(row+translation) for row in wires)))
    for index in indices:
        translation = np.asarray(index)@lattice
        cells.append(dict(image=tuple(index),edges=_readonly(cell_edges+translation)))
    all_points = [corners+np.asarray(index)@lattice for index in indices]
    all_points += [mesh['faces'].reshape(-1,3) for mesh in meshes]
    points = np.concatenate(all_points)
    return dict(lattice=_readonly(lattice),meshes=tuple(meshes),cells=tuple(cells),cell_edges=_readonly(cell_edges),
        bounds=_readonly([points.min(axis=0),points.max(axis=0)]),repeat=repeat,background_epsilon=background,
        primitive_count=len(objects),triangle_count=face_count,display_segments=segments)


class PhotonicCrystal3D(NativeVolumeCanvas):
    """Orbitable authored basis objects; clicking a face selects its stable ID.

    One-cell view shows the authored basis and a unit-cell outline. Repeated
    views translate that basis without clipping or Boolean material meshing.
    """
    objectSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('photonicCrystal3D')
        self.setAccessibleName('Interactive 3D periodic crystal. Drag to rotate, scroll to zoom, shift-drag to pan; click an object to edit it.')
        self.setToolTip('Drag to rotate · Scroll to zoom · Shift-drag to pan · Click an object to edit. '
            'Authored basis objects; periodic copies are shown only when requested. Overlaps are not Boolean material meshing.')
        self.setMinimumSize(240,260)
        self.scene = None; self._cfg = None; self.repeat = 1; self.selected_id = ''
        self._press_point = None; self._moved = False; self._render_key = None
        self._screen_triangles = np.empty((0,3,2)); self._triangle_ids = []; self._picture = None
        self.interaction_started.connect(lambda:self._interaction_detail(True))
        self.interaction_finished.connect(lambda:self._interaction_detail(False))

    def _interaction_detail(self, fast):
        self.fast = bool(fast); self._render_key = None; self.update()

    def clear(self):
        self.scene = None; self._cfg = None; self._picture = None; self._render_key = None
        super().clear()

    def set_crystal(self, cfg, selected_id=''):
        scene = crystal_scene(cfg, self.repeat)
        self._cfg = copy.deepcopy(cfg); self.scene = scene; self.selected_id = selected_id
        self.model = {}  # Enable the inherited camera interactions; never a field model.
        self.axis_ranges = tuple((float(a),float(b)) for a,b in zip(*scene['bounds']))
        self.scene_version += 1; self._camera_key = None; self._render_key = None; self.update()

    def set_repeat(self, count):
        if isinstance(count, bool) or count not in (1,2,3):
            raise ValueError('Repeat count must be 1, 2 or 3.')
        if self._cfg is not None:
            scene = crystal_scene(self._cfg, count)
            self.repeat = count; self.scene = scene
            self.axis_ranges = tuple((float(a),float(b)) for a,b in zip(*scene['bounds']))
            self.scene_version += 1; self._camera_key = None; self._render_key = None; self.update()
        else:
            self.repeat = count

    set_repeats = set_repeat

    def set_selected(self, identity):
        self.selected_id = str(identity or ''); self._render_key = None; self.update()

    def set_standard_view(self, view):
        choices = dict(isometric=(-55.,25.),top=(-90.,90.),front=(-90.,0.),right=(0.,0.))
        if view not in choices:
            raise ValueError('View must be isometric, top, front or right.')
        self.azimuth, self.elevation = choices[view]
        self.pan = QPointF(); self.zoom = 1.; self._camera_key = None
        self.update(); self.camera_changed.emit()

    def camera(self):
        key = (self.scene_version,self.width(),self.height(),self.azimuth,self.elevation,self.zoom,self.pan.x(),self.pan.y())
        if key == self._camera_key:
            return self._camera
        a,e = math.radians(self.azimuth),math.radians(self.elevation)
        basis = np.asarray([[-math.sin(a),math.cos(a),0.],
            [-math.sin(e)*math.cos(a),-math.sin(e)*math.sin(a),math.cos(e)],
            [math.cos(e)*math.cos(a),math.cos(e)*math.sin(a),math.sin(e)]])
        lower,upper = np.asarray([r[0] for r in self.axis_ranges]),np.asarray([r[1] for r in self.axis_ranges])
        center = (lower+upper)/2
        corners = np.asarray(list(itertools.product(*self.axis_ranges)))
        projected = (corners-center)@basis.T
        span = np.maximum(np.ptp(projected[:,:2],axis=0),1e-12)
        plot = QRectF(28,35,max(50,self.width()-56),max(50,self.height()-83))
        scale = min(plot.width()/span[0],plot.height()/span[1])*.87*self.zoom
        origin = np.asarray([plot.center().x()+self.pan.x(),plot.center().y()+self.pan.y()])
        self._camera_key = key; self._camera = (basis,center,scale,origin,plot)
        return self._camera

    def _render_geometry(self):
        from PyQt6.QtGui import QPicture
        self.camera()
        key = (self._camera_key,self.selected_id,self.fast,theme_manager().mode,theme_manager().style)
        if key == self._render_key:
            return
        picture = QPicture(); painter = QPainter(picture)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        colors = COLORS[theme_manager().mode]
        palette = ['#59a8db','#dc9869','#85bca0','#b49cde','#d7c76f','#7cbfc4']
        epsilons = sorted({mesh['epsilon'] for mesh in self.scene['meshes']})
        material_colors = {value:QColor(palette[i%len(palette)]) for i,value in enumerate(epsilons)}
        faces = []; face_colors = []; ids = []
        light = np.asarray([-.35,-.45,.82]); light /= np.linalg.norm(light)
        for mesh in self.scene['meshes']:
            triangles = mesh['interaction_faces'] if self.fast else mesh['faces']
            faces.extend(triangles); ids.extend([mesh['id']]*len(triangles))
            normals = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
            normals /= np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-20)
            strength = .52+.44*np.maximum(normals@light,0.)
            base = material_colors[mesh['epsilon']]
            for shade in strength:
                face_colors.append(QColor.fromRgbF(base.redF()*shade,base.greenF()*shade,base.blueF()*shade,1.))
        # Sort all faces together: object-level sorting hides nested/small objects.
        if faces:
            xy,depth = self.project(np.asarray(faces)); order = np.argsort(depth.mean(axis=1),kind='stable')
            self._screen_triangles = xy[order]; self._triangle_ids = [ids[i] for i in order]
            for index in order:
                # A matching subpixel edge closes antialias seams between the
                # display triangles without drawing a scientific mesh overlay.
                painter.setPen(QPen(face_colors[index],.6)); painter.setBrush(face_colors[index])
                painter.drawPolygon(QPolygonF([QPointF(float(x),float(y)) for x,y in xy[index]]))
        else:
            self._screen_triangles = np.empty((0,3,2)); self._triangle_ids = []
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Cell edges intentionally overlay primitives so periodic boundaries remain legible.
        for cell in self.scene['cells']:
            color = QColor(colors['muted']); color.setAlpha(175 if cell['image'] == (0,0,0) else 65)
            painter.setPen(QPen(color,1.35 if cell['image'] == (0,0,0) else .75))
            xy,_ = self.project(cell['edges'])
            for edge in xy:
                painter.drawLine(QPointF(*map(float,edge[0])),QPointF(*map(float,edge[1])))
        for mesh in self.scene['meshes']:
            if mesh['id'] != self.selected_id or mesh['image'] != (0,0,0):
                continue
            # Supported primitives are convex. Their projected hull provides a
            # clean selected-object silhouette, without latitude grids or
            # selection marks on every displayed periodic image.
            from scipy.spatial import ConvexHull, QhullError
            points,_ = self.project(mesh['faces'].reshape(-1,3))
            points = np.unique(points,axis=0)
            try:
                hull = ConvexHull(points)
            except QhullError:
                continue
            outline = points[hull.vertices]
            color = QColor(colors['accent']); painter.setPen(QPen(color,1.6))
            painter.drawPolygon(QPolygonF([QPointF(*map(float,point)) for point in outline]))
        painter.end(); self._picture = picture; self._render_key = key

    def _draw_gizmo(self, painter):
        basis = self.camera()[0]; origin = np.asarray([47.,self.height()-48.])
        painter.setFont(QFont(painter.font().family(),8))
        for direction,name,color in ((0,'x','#e68b8d'),(1,'y','#75bc96'),(2,'z','#78a7ec')):
            vector = basis[:2,direction]*np.asarray([1.,-1.])*27
            tip = origin+vector; painter.setPen(QPen(QColor(color),1.8))
            painter.drawLine(QPointF(*origin),QPointF(*tip))
            painter.drawText(QRectF(tip[0]-6,tip[1]-10,18,18),Qt.AlignmentFlag.AlignCenter,name)

    def paintEvent(self,event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        colors = COLORS[theme_manager().mode]
        painter.fillRect(self.rect(),QColor(colors['field']))
        if self.scene is None:
            painter.setPen(QColor(colors['muted'])); painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'Define a 3D cell and add a sphere, cylinder or block.'); painter.end(); return
        self._render_geometry(); painter.drawPicture(0,0,self._picture); self._draw_gizmo(painter)
        painter.setPen(QColor(colors['text']))
        text = '3D crystal · '+('basis objects and unit cell' if self.repeat == 1 else f'{self.repeat} × {self.repeat} × {self.repeat} basis copies')
        painter.drawText(QRectF(12,8,self.width()-24,22),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,text)
        painter.setPen(QColor(colors['muted']))
        painter.drawText(QRectF(84,self.height()-31,self.width()-96,20),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,'Drag to rotate · scroll to zoom')
        painter.end()

    def pick_object(self, point):
        """Return the frontmost drawn primitive ID at widget-space coordinates."""
        if self.scene is None:
            return ''
        self._render_geometry()
        p = np.asarray([point.x(),point.y()] if hasattr(point,'x') else point,dtype=float)
        xy = self._screen_triangles
        if not len(xy):
            return ''
        # Signed edge tests cover either winding; degenerate projected faces cannot win.
        edge = np.roll(xy,-1,axis=1)-xy; offset = p-xy
        cross = edge[:,:,0]*offset[:,:,1]-edge[:,:,1]*offset[:,:,0]
        area = abs(np.sum(xy[:,:,0]*np.roll(xy[:,:,1],-1,axis=1)-xy[:,:,1]*np.roll(xy[:,:,0],-1,axis=1),axis=1))
        mask = (np.all(cross >= -1e-8,axis=1)|np.all(cross <= 1e-8,axis=1)) & (area > 1e-8)
        hits = np.flatnonzero(mask)
        return self._triangle_ids[int(hits[-1])] if len(hits) else ''

    def mousePressEvent(self,event):
        self._press_point = event.position(); self._moved = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._press_point is not None and (event.position()-self._press_point).manhattanLength() > 4:
            self._moved = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        selected = event.button() == Qt.MouseButton.LeftButton and not self._moved and self._press_point is not None
        super().mouseReleaseEvent(event)
        self._press_point = None
        if selected:
            identity = self.pick_object(event.position())
            if identity:
                self.set_selected(identity); self.objectSelected.emit(identity)
