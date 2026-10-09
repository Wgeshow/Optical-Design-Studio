"""Typed native Qt rendering of saved, physical 3D field geometry.

QPainter draws scientific mesh triangles, sample points and vectors. The
complete saved data and isosurface construction live outside this display
adapter. Camera projection uses one physical scale for all three coordinates.
"""
import math
from pathlib import Path
import numpy as np
from PyQt6.QtCore import Qt, QPointF, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF, QPicture, QLinearGradient, QFont, QFontMetrics
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QFileDialog, QMessageBox, QApplication
from qt_common import COLORS, theme_manager
from structure_preview import region_polygon, periodic_centers, clip_polygon


_INFERNO = bytes.fromhex(
    '00000300000400000601000701010901010b02010e02021003021204031404031605041806041b07051d08061f090621'
    '0a07230b07260d08280e082a0f092d10092f120a32130a34140b36160b39170b3b190b3e1a0b401c0c431d0c451f0c47'
    '200c4a220b4c240b4e260b50270b52290b542b0a562d0a582e0a5a300a5c32095d34095f3509603709613909623b0964'
    '3c09653e0966400966410967430a68450a69460a69480b6a4a0b6a4b0c6b4d0c6b4f0d6c500d6c520e6c530e6d550f6d'
    '570f6d58106d5a116d5b116e5d126e5f126e60136e62146e63146e65156e66156e68166e6a176e6b176e6d186e6e186e'
    '70196e72196d731a6d751b6d761b6d781c6d7a1c6d7b1d6c7d1d6c7e1e6c801f6b811f6b83206b85206a86216a88216a'
    '8922698b22698d23698e24689024689125679325679526669626669827659928649b28649c29639e2963a02a62a12b61'
    'a32b61a42c60a62c5fa72d5fa92e5eab2e5dac2f5cae305baf315bb1315ab23259b43358b53357b73456b83556ba3655'
    'bb3754bd3753be3852bf3951c13a50c23b4fc43c4ec53d4dc73e4cc83e4bc93f4acb4049cc4148cd4247cf4446d04544'
    'd14643d24742d44841d54940d64a3fd74b3ed94d3dda4e3bdb4f3adc5039dd5238de5337df5436e05634e25733e35832'
    'e45a31e55b30e65c2ee65e2de75f2ce8612be9622aea6428eb6527ec6726ed6825ed6a23ee6c22ef6d21f06f1ff0701e'
    'f1721df2741cf2751af37719f37918f47a16f57c15f57e14f68012f68111f78310f7850ef8870df8880cf88a0bf98c09'
    'f98e08f99008fa9107fa9306fa9506fa9706fb9906fb9b06fb9d06fb9e07fba007fba208fba40afba60bfba80dfbaa0e'
    'fbac10fbae12fbb014fbb116fbb318fbb51afbb71cfbb91efabb21fabd23fabf25fac128f9c32af9c52cf9c72ff8c931'
    'f8cb34f8cd37f7cf3af7d13cf6d33ff6d542f5d745f5d948f4db4bf4dc4ff3de52f3e056f3e259f2e45df2e660f1e864'
    'f1e968f1eb6cf1ed70f1ee74f1f079f1f27df2f381f2f485f3f689f4f78df5f891f6fa95f7fb99f9fc9dfafda0fcfea4'
)


def intensity_color(fraction):
    # Frozen standard inferno lookup: the same fixed 0-to-peak map as export.
    index=min(255,int(min(1.,max(0.,float(fraction)))*256))*3
    return QColor(*_INFERNO[index:index+3])


class NativeSurfaceMesh:
    """An immutable scientific triangle mesh with native display visibility."""
    def __init__(self, faces, fraction, canvas=None, visible=True):
        self.faces=np.array(faces,dtype=float,copy=True).reshape(-1,3,3)
        self.faces.setflags(write=False)
        self.fraction=float(fraction);self.canvas=canvas;self.visible=bool(visible)
        self._picture_key=None;self._picture=None
        normals=np.cross(self.faces[:,1]-self.faces[:,0],self.faces[:,2]-self.faces[:,0])
        lengths=np.linalg.norm(normals,axis=1)
        self.normals=normals/np.maximum(lengths[:,None],1e-30)
        light=np.array([-.4,-.55,-.73]);light/=np.linalg.norm(light)
        diffuse=np.clip(self.normals@light,0,1)
        base=intensity_color(self.fraction)
        # Directional lighting varies brightness, while the colorbar retains
        # the complete snapshot normalization and the actual isovalue.
        self.colors=[QColor.fromRgbF(*[min(1.,max(0.,channel*(.50+.58*d)+.06*d))
            for channel in (base.redF(),base.greenF(),base.blueF())]) for d in diffuse]

    def set_visible(self, visible):
        if self.visible!=bool(visible):
            self.visible=bool(visible)
            if self.canvas is not None:self.canvas.draw_idle()

    def get_visible(self):return self.visible


class NativeVectorSet:
    """Actual instantaneous phasor vectors, separate from steady intensity."""
    def __init__(self, canvas, positions, vectors):
        self.canvas=canvas;self.visible=True
        self.set_vectors(positions,vectors)

    def set_vectors(self, positions, vectors):
        self.positions=np.array(positions,dtype=float,copy=True)
        self.vectors=np.array(vectors,dtype=float,copy=True)
        self.positions.setflags(write=False);self.vectors.setflags(write=False)
        self.canvas.draw_idle()

    def set_visible(self, visible):self.visible=bool(visible);self.canvas.draw_idle()
    def get_visible(self):return self.visible
    def remove(self):
        if self.canvas.arrows is self:self.canvas.arrows=None;self.canvas.draw_idle()


class NativeVolumeCanvas(QWidget):
    interaction_started=pyqtSignal()
    interaction_finished=pyqtSignal()
    camera_changed=pyqtSignal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName('nativeFieldVolumeCanvas')
        self.setMinimumSize(300,300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName('Scientific 3D field volume. Drag to orbit, scroll to zoom, shift-drag to pan.')
        self.setToolTip('Drag to orbit · Scroll to zoom · Shift-drag to pan')
        self.figure_style=None;self.axis_labels=['x (µm)','y (µm)','Depth z (µm)'];self.title_override=None;self.quantity_override=None
        self.azimuth=-55.;self.elevation=25.;self.zoom=1.;self.pan=QPointF()
        self.scene_version=0;self.model=None;self.meshes=[];self.arrows=None
        self.points=np.empty((0,3));self.values=np.empty(0);self.peak=1.
        self.title='';self.quantity='';self.fast=False;self._drag=None
        self._camera_key=None;self._camera=None;self._point_key=None;self._point_picture=None
        self.layer_lines=[];self.layer_labels=[]
        self.axis_ranges=((-1.,1.),(-1.,1.),(0.,1.))
        theme_manager().changed.connect(self.update)

    def draw_idle(self):self.update()
    def draw(self):self.repaint()

    def clear(self):
        self.model=None;self.meshes=[];self.arrows=None;self.points=np.empty((0,3));self.values=np.empty(0)
        self.scene_version+=1;self._camera_key=None;self.update()

    def set_scene(self, model, points, values, meshes, peak, title, quantity, samples_mode=False):
        points=np.asarray(points,dtype=float);values=np.asarray(values,dtype=float)
        if points.shape!=(len(values),3) or not np.isfinite(points).all() or not np.isfinite(values).all():
            raise ValueError('Native 3D field display requires finite physical sample coordinates and values.')
        self.model=model;self.points=np.array(points,copy=True);self.values=np.array(values,copy=True)
        self.points.setflags(write=False);self.values.setflags(write=False)
        self.meshes=list(meshes);self.samples_mode=bool(samples_mode)
        for mesh in self.meshes:mesh.canvas=self
        self.peak=max(float(peak),1e-30);self.title=str(title);self.quantity=str(quantity)
        x,y=float(model['ax'])/2,float(model['ay'])/2
        total=sum(max(0.,float(layer['thickness'])) for layer in model['layers'][1:-1])
        if total<=0:total=float(points[:,2].max()) if len(points) else 1.
        self.axis_ranges=((-x,x),(-y,y),(0.,max(total,1e-9)))
        self._build_geometry(model)
        self.scene_version+=1;self._camera_key=None;self._point_key=None;self.arrows=None;self.draw_idle()

    def _build_geometry(self,model):
        self.layer_lines=[];self.layer_labels=[]
        x,y=model['ax']/2,model['ay']/2;window=(-x,x,-y,y);z=0.
        for layer in model['layers'][1:-1]:
            top=z;z+=max(0.,float(layer['thickness']))
            if z<=top:continue
            for depth in (top,z):
                self.layer_lines.append(np.array([[-x,-y,depth],[x,-y,depth],[x,y,depth],[-x,y,depth],[-x,-y,depth]]))
            for xx,yy in ((-x,-y),(x,-y),(x,y),(-x,y)):
                self.layer_lines.append(np.array([[xx,yy,top],[xx,yy,z]]))
            self.layer_labels.append((str(layer['name']),np.array([-x,-y,(top+z)/2])))
            for region in model.get('patterns',[]):
                if region['layer']!=layer['name']:continue
                shape=dict(region,sy=region['sx'] if region['shape']=='circle' else region['sy'],angle=float(region.get('angle',0.)))
                for center in periodic_centers(shape,model['ax'],model['ay'],window):
                    polygon=clip_polygon(region_polygon(shape,center),window)
                    if len(polygon)<3:continue
                    xy=np.asarray(list(polygon)+[polygon[0]])
                    for depth in (top,z):self.layer_lines.append(np.column_stack([xy,np.full(len(xy),depth)]))

    def camera(self):
        key=(self.scene_version,self.width(),self.height(),self.azimuth,self.elevation,self.zoom,self.pan.x(),self.pan.y())
        if key==self._camera_key:return self._camera
        a,e=math.radians(self.azimuth),math.radians(self.elevation)
        # Saved z is physical depth, increasing downward, as in draw_geometry.
        basis=np.array([[-math.sin(a),math.cos(a),0.],
            [-math.sin(e)*math.cos(a),-math.sin(e)*math.sin(a),-math.cos(e)],
            [math.cos(e)*math.cos(a),math.cos(e)*math.sin(a),-math.sin(e)]])
        lower=np.array([r[0] for r in self.axis_ranges]);upper=np.array([r[1] for r in self.axis_ranges])
        center=(lower+upper)/2
        corners=np.array([[x,y,z] for x in self.axis_ranges[0] for y in self.axis_ranges[1] for z in self.axis_ranges[2]])
        rotated=(corners-center)@basis.T
        span=np.maximum(np.ptp(rotated[:,:2],axis=0),1e-12)
        plot=QRectF(62,54,max(40,self.width()-185),max(40,self.height()-134))
        scale=min(plot.width()/span[0],plot.height()/span[1])*.87*self.zoom
        origin=np.array([plot.center().x()+self.pan.x(),plot.center().y()+self.pan.y()])
        self._camera_key=key;self._camera=(basis,center,scale,origin,plot)
        return self._camera

    def project(self,xyz):
        basis,center,scale,origin,_=self.camera()
        projected=(np.asarray(xyz)-center)@basis.T
        screen=projected[...,:2]*np.array([scale,-scale])+origin
        return screen,projected[...,2]

    def set_vectors(self,positions,vectors):
        if self.arrows is None:self.arrows=NativeVectorSet(self,positions,vectors)
        else:self.arrows.set_vectors(positions,vectors)
        return self.arrows

    def reset_camera(self):
        self.azimuth=-55.;self.elevation=25.;self.zoom=1.;self.pan=QPointF()
        self.draw_idle();self.camera_changed.emit()

    def _mesh_picture(self,mesh):
        key=self._camera_key
        if mesh._picture_key==key:return mesh._picture
        xy,depth=self.project(mesh.faces)
        order=np.argsort(depth.mean(axis=1))
        picture=QPicture();painter=QPainter(picture);painter.setPen(Qt.PenStyle.NoPen)
        for index in order:
            painter.setBrush(mesh.colors[index]);painter.drawPolygon(QPolygonF([QPointF(float(x),float(y)) for x,y in xy[index]]))
        painter.end();mesh._picture_key=key;mesh._picture=picture
        return picture

    def _samples_picture(self):
        key=(self._camera_key,self.fast)
        if key==self._point_key:return self._point_picture
        ids=np.arange(len(self.points))
        if self.fast and len(ids)>600:ids=ids[np.linspace(0,len(ids)-1,600,dtype=int)]
        xy,depth=self.project(self.points[ids]);order=np.argsort(depth)
        picture=QPicture();painter=QPainter(picture);painter.setPen(Qt.PenStyle.NoPen)
        for index in order:
            color=intensity_color(self.values[ids[index]]/self.peak);color.setAlpha(210)
            painter.setBrush(color);painter.drawEllipse(QPointF(*map(float,xy[index])),2.6,2.6)
        painter.end();self._point_key=key;self._point_picture=picture
        return picture

    def _draw_vectors(self,p):
        if self.arrows is None or not self.arrows.visible:return
        start,_=self.project(self.arrows.positions);end,_=self.project(self.arrows.positions+self.arrows.vectors)
        color=QColor('#24b7df');p.setBrush(color)
        for a,b in zip(start,end):
            direction=b-a;length=float(np.linalg.norm(direction))
            if length<.25:continue
            unit=direction/length;normal=np.array([-unit[1],unit[0]])
            head=min(6.,length*.32)
            p.setPen(QPen(color,1.15));p.drawLine(QPointF(*map(float,a)),QPointF(*map(float,b-unit*head*.5)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygonF([QPointF(*map(float,point)) for point in (b,b-unit*head+normal*head*.42,b-unit*head-normal*head*.42)]))

    def _draw_axes(self,p,c):
        ranges=self.axis_ranges
        label_bounds=[]
        for axis,label,color in ((0,self.axis_labels[0],'#eb8791'),(1,self.axis_labels[1],'#69b68c'),(2,self.axis_labels[2],'#719de4')):
            base=np.array([ranges[0][0],ranges[1][0],ranges[2][1]])
            if axis==1:base[0]=ranges[0][1]
            first=base.copy();last=base.copy();first[axis]=ranges[axis][0];last[axis]=ranges[axis][1]
            ends,_=self.project(np.array([first,last]));delta=ends[1]-ends[0]
            normal=np.array([-delta[1],delta[0]])/max(float(np.linalg.norm(delta)),1e-12)
            if normal[1]<0:normal=-normal
            if axis==2 and normal[0]>0:normal=-normal
            tint=QColor(color);p.setPen(QPen(tint,1.1));p.drawLine(QPointF(*map(float,ends[0])),QPointF(*map(float,ends[1])))
            for tick in np.linspace(*ranges[axis],4):
                point=base.copy();point[axis]=tick;position,_=self.project(point)
                p.setPen(QPen(tint,.9));p.drawLine(QPointF(*map(float,position)),QPointF(*map(float,position+normal*4)))
                center=position+normal*15
                text=f'{tick:.3g}'
                width=QFontMetrics(p.font()).horizontalAdvance(text)+6
                rect=QRectF(center[0]-width/2,center[1]-8,width,16)
                # Two axes meet at a physical box corner. Keep both endpoint
                # values, moving the second label along its tick direction.
                for _ in range(4):
                    if not any(rect.intersects(previous.adjusted(-2,-2,2,2)) for previous in label_bounds):break
                    rect.translate(float(normal[0])*16,float(normal[1])*16)
                rect.moveLeft(min(max(2.,rect.left()),self.width()-rect.width()-2));rect.moveTop(min(max(2.,rect.top()),self.height()-rect.height()-2))
                label_bounds.append(rect)
                p.setPen(QColor(c['muted']));p.drawText(rect,Qt.AlignmentFlag.AlignCenter,text)
            center=(ends[0]+ends[1])/2+normal*38
            rect=QRectF(center[0]-53,center[1]-9,106,20)
            rect.moveLeft(min(max(2.,rect.left()),self.width()-rect.width()-2));rect.moveTop(min(max(2.,rect.top()),self.height()-rect.height()-2))
            p.setPen(tint)
            tick_font=QFont(p.font());label_font=QFont(tick_font)
            if self.figure_style:label_font.setPointSizeF(self.figure_style['label_pt'])
            p.setFont(label_font);p.drawText(rect,Qt.AlignmentFlag.AlignCenter,label);p.setFont(tick_font)
            label_bounds.append(rect)
        self._axis_label_bounds=label_bounds

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c=COLORS[theme_manager().mode]
        if theme_manager().style!='glass':p.fillRect(self.rect(),QColor(c['panel']))
        if self.model is None:
            p.setPen(QColor(c['muted']));p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'Load a saved 3D field snapshot');p.end();return
        self.camera()
        p.setPen(QPen(QColor(c['muted']),.8));p.setBrush(Qt.BrushStyle.NoBrush)
        for line in self.layer_lines:
            xy,_=self.project(line);p.drawPolyline(QPolygonF([QPointF(*map(float,point)) for point in xy]))
        active=[mesh for mesh in self.meshes if mesh.visible and len(mesh.faces)]
        if active:
            active.sort(key=lambda mesh:float(self.project(mesh.faces.mean(axis=(0,1)))[1]))
            # Mesh pictures cache the sorted scientific triangles. A phase
            # frame replays native primitives and projects only its vectors.
            p.setRenderHint(QPainter.RenderHint.Antialiasing,False)
            for mesh in active:p.drawPicture(0,0,self._mesh_picture(mesh))
            p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        elif self.samples_mode and len(self.points):p.drawPicture(0,0,self._samples_picture())
        self._draw_vectors(p)
        if self.figure_style:
            font=QFont(self.figure_style['font']);font.setPointSizeF(self.figure_style['tick_pt']);p.setFont(font)
        self._draw_axes(p,c)
        label_font=QFont(p.font());label_font.setPointSizeF(self.figure_style['legend_pt'] if self.figure_style else 8);p.setFont(label_font)
        last_bottom=45
        for index,(name,point) in enumerate(self.layer_labels):
            position,_=self.project(point)
            y=max(last_bottom,min(self.height()-50-(len(self.layer_labels)-index)*18,position[1]-9))
            bounds=QRectF(8,y,95,18)
            for step in (0,-22,22,-44,44,-66,66,-88,88,-110,110):
                candidate=QRectF(8,y+step,95,18)
                if candidate.top()<last_bottom or candidate.bottom()>self.height()-50:continue
                if not any(candidate.intersects(axis.adjusted(-2,-2,2,2)) for axis in self._axis_label_bounds):bounds=candidate;break
            last_bottom=bounds.bottom()+3
            leader=QColor(c['muted']);leader.setAlpha(125);p.setPen(QPen(leader,.65))
            p.drawLine(QPointF(bounds.right()+3,bounds.center().y()),QPointF(*map(float,position)))
            p.setPen(QColor(c['text']));p.drawText(bounds,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,QFontMetrics(label_font).elidedText(name,Qt.TextElideMode.ElideRight,95))
        font=QFont(p.font());font.setBold(True);font.setPointSizeF(self.figure_style['title_pt'] if self.figure_style else 10);p.setFont(font)
        p.setPen(QColor(c['text']));p.drawText(QRectF(18,10,self.width()-36,26),Qt.AlignmentFlag.AlignCenter,self.title if self.title_override is None else self.title_override)
        font.setBold(False);font.setPointSizeF(self.figure_style['tick_pt'] if self.figure_style else 8);p.setFont(font)
        bar=QRectF(self.width()-88,88,13,max(70,self.height()-225))
        gradient=QLinearGradient(bar.bottomLeft(),bar.topLeft())
        for index in range(10):gradient.setColorAt(index/9,intensity_color(index/9))
        p.fillRect(bar,gradient);p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(c['border']),.7));p.drawRect(bar)
        p.setPen(QColor(c['muted']))
        for fraction in (0.,.25,.5,.75,1.):
            y=bar.bottom()-fraction*bar.height()
            p.drawText(QRectF(bar.right()+5,y-8,64,17),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,f'{self.peak*fraction:.3g}')
        p.save();p.translate(bar.left()-13,bar.center().y());p.rotate(-90)
        p.drawText(QRectF(-bar.height()/2,-10,bar.height(),20),Qt.AlignmentFlag.AlignCenter,self.quantity if self.quantity_override is None else self.quantity_override);p.restore()
        p.end()

    def mousePressEvent(self,event):
        if self.model is not None and event.button() in (Qt.MouseButton.LeftButton,Qt.MouseButton.MiddleButton):
            self._drag=(event.position(),event.modifiers()&Qt.KeyboardModifier.ShiftModifier or event.button()==Qt.MouseButton.MiddleButton)
            self.interaction_started.emit();event.accept()

    def mouseMoveEvent(self,event):
        if self._drag is not None:
            previous,pan=self._drag;delta=event.position()-previous
            if pan:self.pan+=delta
            else:self.azimuth+=delta.x()*.5;self.elevation=max(-85.,min(85.,self.elevation+delta.y()*.4))
            self._drag=(event.position(),pan);self.draw_idle();self.camera_changed.emit();event.accept()

    def mouseReleaseEvent(self,event):
        if self._drag is not None:self._drag=None;self.interaction_finished.emit();event.accept()

    def wheelEvent(self,event):
        if self.model is not None:
            self.zoom=min(5.,max(.25,self.zoom*(1.12 if event.angleDelta().y()>0 else 1/1.12)))
            self.draw_idle();self.camera_changed.emit();event.accept()


class NativeFieldVolumePlot(QWidget):
    """Native 3D canvas with lazily generated publication export figures."""
    def __init__(self,parent=None,paper_factory=None):
        super().__init__(parent);self.paper_factory=paper_factory
        from publication_plot import defaults
        self.figure_style=defaults();self._publication_figure=None;self._publication_labels=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.toolbar=QWidget(self);actions=QHBoxLayout(self.toolbar);actions.setContentsMargins(4,4,4,0);actions.setSpacing(4);actions.addStretch()
        self.buttons={}
        for key,label,callback in [('Fit','Reset camera',lambda:self.canvas.reset_camera()),
                ('Copy','Copy view',lambda:QApplication.clipboard().setPixmap(self.canvas.grab())),
                ('Settings','Figure settings',self.edit_figure_settings),
                ('Export','Export figure',self.export_dialog)]:
            button=QToolButton(self.toolbar);button.setFixedSize(30,30);button.setIconSize(QSize(20,20))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setText(label);button.setAccessibleName(label);button.setToolTip(label)
            button.clicked.connect(callback);actions.addWidget(button);self.buttons[key]=button
        layout.addWidget(self.toolbar)
        self.canvas=NativeVolumeCanvas(self);layout.addWidget(self.canvas,1)
        theme_manager().changed.connect(self.retheme);self.retheme()

    def retheme(self):
        from qt_native_plot import plot_icon
        colors=COLORS[theme_manager().mode]
        for key,button in self.buttons.items():button.setIcon(plot_icon('Figure settings' if key=='Settings' else key,colors['text']))
        self.toolbar.setStyleSheet(f'QToolButton {{background:transparent; border:1px solid transparent; padding:0; border-radius:5px;}} QToolButton:hover {{background:{colors["panel"]}; border-color:{colors["border"]};}}')
        self.canvas.update()

    def clear(self):self.canvas.clear()
    def set_scene(self,*args,**kwargs):self.canvas.set_scene(*args,**kwargs)

    def _make_publication_figure(self):
        if self.paper_factory is None:raise ValueError('Load a field snapshot before exporting.')
        figure=self.paper_factory()
        for axis,values in zip(figure.axes,self._publication_labels):axis.set(**values)
        return figure

    @property
    def figure(self):
        if self._publication_figure is None:self._publication_figure=self._make_publication_figure()
        return self._publication_figure

    def fit_canvas(self):
        # The shared publication dialog applies its edits here. Store only
        # local labels and typography; live replay keeps its native canvas.
        self._publication_labels=[]
        for axis in self.figure.axes:
            labels=dict(title=axis.get_title(),xlabel=axis.get_xlabel(),ylabel=axis.get_ylabel())
            if hasattr(axis,'get_zlabel'):labels['zlabel']=axis.get_zlabel()
            self._publication_labels.append(labels)
        self.canvas.figure_style=dict(self.figure_style)
        if self._publication_labels:
            labels=self._publication_labels[0]
            self.canvas.title_override=labels['title'];self.canvas.axis_labels=[labels['xlabel'],labels['ylabel'],self.canvas.axis_labels[2]]
        if len(self._publication_labels)>1:self.canvas.quantity_override=self._publication_labels[1]['ylabel']
        self.canvas.update()

    def edit_figure_settings(self):
        from publication_plot import edit_settings,apply_style
        try:
            self._publication_figure=self._make_publication_figure()
            apply_style(self._publication_figure,self.figure_style)
            edit_settings(self)
        except Exception as exc:QMessageBox.warning(self,'Figure settings',str(exc))
        finally:self._publication_figure=None

    def export_figure(self,path):
        figure=self._make_publication_figure()
        from publication_plot import export_figure
        export_figure(figure,path,self.figure_style)

    def export_dialog(self):
        path,_=QFileDialog.getSaveFileName(self,'Export 3D field figure','field-volume.pdf','PDF vector (*.pdf);;SVG vector (*.svg);;PNG image (*.png)')
        if path:
            try:self.export_figure(Path(path) if Path(path).suffix else Path(path+'.pdf'))
            except Exception as exc:QMessageBox.warning(self,'Field figure export failed',str(exc))
