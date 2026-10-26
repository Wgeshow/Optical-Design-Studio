"""Reference-composed native results workspace backed by saved simulation data.

The full workspace deliberately reuses ElectricalResultsPanel's loading/probing
and exports. Device-face shading interpolates saved grid samples for display;
probe values and exports remain the original grid data. Drawn holes, rings and
contacts come from the saved physical device, never a decorative bitmap.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib import colormaps
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QSignalBlocker, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform, QRadialGradient
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSplitter, QStackedWidget,
    QStyledItemDelegate, QStyle, QToolButton, QVBoxLayout, QWidget,
)

from qt_common import COLORS, PlotWidget, theme_manager
from qt_icons import navigation_icon
from qt_reference_style import reference_icon
from qt_device_lighting import mix_color, sheen_brush, studio_brush
from qt_electrical_results import (
    ElectricalResultsPanel, ElectricalSliceCanvas, _FieldColors, _QUANTITY_INFO,
    _axis_edges, saved_result_path, saved_result_model_labels,
)


def _text(value, default='Unavailable'):
    if value is None:
        return default
    if isinstance(value,(float,int)):
        return f'{value:.5g}' if math.isfinite(value) else default
    return str(value)


def _saved_optical_cell(directory):
    """Read the actual solved cell once, including implicit PC selections."""
    directory=Path(directory)
    for path in (directory/'model.json',directory/'evaluations'/'000001'/'model.json',
                 directory/'field_model.json',directory/'fields'/'field_model.json'):
        try:
            if not path.is_file() or path.stat().st_size>5*1024*1024:continue
            saved=json.loads(path.read_text(encoding='utf-8'))
            model=saved.get('model',saved)
            metadata=model.get('optical_unit_cell',{})
            selection=metadata.get('selection',{})
            if isinstance(selection,dict) and isinstance(selection.get('enabled'),bool):
                if selection['enabled'] and not all(isinstance(selection.get(key),(float,int)) and
                        math.isfinite(selection[key]) and selection[key]>0 for key in ('width_um','depth_um')):continue
                return dict(selection)
        except (OSError,ValueError,TypeError,AttributeError):
            continue
    return {}


def results_preview_shapes(device,layer_id=None,budget=256):
    """Display-only sample of real enabled shapes; no document fields are edited.

    Ordinary designs retain every shape. Large PC areas use evenly distributed
    actual records and retain ordinary non-array regions ahead of generated
    array members. Solver masks and export use the original
    complete document independently of this presentation selection.
    """
    objects=[obj for obj in device.get('shapes',[]) if obj.get('enabled',True) and (layer_id is None or obj.get('layer_id')==layer_id)]
    total=len(objects)
    if total<=budget:return objects,total
    ordinary=[obj for obj in objects if not obj.get('pc_array_id')]
    generated=[obj for obj in objects if obj.get('pc_array_id')]
    if len(ordinary)>=budget:
        indices=np.linspace(0,len(ordinary)-1,budget,dtype=int)
        chosen=[ordinary[index] for index in indices]
    else:
        remaining=budget-len(ordinary)
        indices=np.linspace(0,len(generated)-1,min(remaining,len(generated)),dtype=int) if generated else []
        chosen=[*ordinary,*[generated[index] for index in indices]]
    # Keep original override order, including actual edited material regions.
    selected={obj['id'] for obj in chosen}
    return [obj for obj in objects if obj['id'] in selected],total


def _pc_area_outline(painter,device,layer_id,project):
    for area in device.get('pc_arrays',[]):
        if not area.get('enabled',True) or area.get('layer_id')!=layer_id:continue
        x,y=area.get('cx_um',0.),area.get('cy_um',0.)
        width,depth=area['width_um'],area['depth_um']
        painter.setPen(QPen(QColor('#62c8f1'),.8,Qt.PenStyle.DashLine));painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(QPolygonF([project(x-width/2,y-depth/2),project(x+width/2,y-depth/2),project(x+width/2,y+depth/2),project(x-width/2,y+depth/2)]))


def _frame(parent=None):
    frame=QFrame(parent)
    frame.setObjectName('resultsCard')
    return frame


def _small_plot():
    plot=PlotWidget()
    plot.setMinimumHeight(0)
    plot.setMinimumWidth(0)
    plot.toolbar.hide()
    plot.figure_style.update(label_pt=8.,tick_pt=7.5,title_pt=9.,legend_pt=7.,line_pt=1.35)
    return plot


class _CurveLegend(QWidget):
    """Keep compact chart labels outside the scientific data rectangle."""
    def __init__(self,parent=None):
        super().__init__(parent);self.lines=[];self.setFixedWidth(101)

    def set_lines(self,figure):
        self.lines=[line for axis in figure.axes for line in axis.lines if line.get_label() and not line.get_label().startswith('_')]
        self.update()

    def paintEvent(self,_):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font=QFont(painter.font());font.setPointSizeF(7.5);painter.setFont(font)
        count=len(self.lines);spacing=min(19,max(14,(self.height()-12)/max(count,1)));top=max(7,(self.height()-count*spacing)/2)
        for index,line in enumerate(self.lines):
            y=top+index*spacing+7
            style=Qt.PenStyle.DashLine if line.get_linestyle()=='--' else Qt.PenStyle.DotLine if line.get_linestyle()==':' else Qt.PenStyle.SolidLine
            painter.setPen(QPen(QColor(line.get_color()),1.4,style));painter.drawLine(QPointF(1,y),QPointF(17,y))
            painter.setPen(QColor('#bdd7e9'));label=line.get_label().replace('Electrons','n').replace('Holes','p').replace('Potential','φ')
            painter.drawText(QPointF(21,y+3),QFontMetrics(font).elidedText(label,Qt.TextElideMode.ElideRight,78))


def _legend_column(plot):
    content=QWidget();row=QHBoxLayout(content);row.setContentsMargins(0,0,3,0);row.setSpacing(2)
    legend=_CurveLegend();row.addWidget(plot,1);row.addWidget(legend)
    return content,legend


def _hide_native_legend(plot):
    for item in set(plot.canvas.plots.values()):
        legend=getattr(item,'legend',None)
        if legend is not None:legend.hide()


def _card(title,content,action=None):
    frame=_frame()
    layout=QVBoxLayout(frame)
    layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
    header=QFrame();header.setObjectName('resultsCardHeader')
    row=QHBoxLayout(header);row.setContentsMargins(10,4,7,4)
    label=QLabel(title);label.setObjectName('resultsCardTitle')
    row.addWidget(label,1)
    menu=QToolButton();menu.setIcon(reference_icon('more'));menu.setIconSize(QSize(18,18));menu.setObjectName('resultsMore')
    menu.setToolTip('Export or inspect saved data from the result actions.')
    menu.setFixedSize(22,22)
    row.addWidget(menu)
    header.setFixedHeight(29)
    layout.addWidget(header);layout.addWidget(content,1)
    frame.title_label=label
    frame.more_button=menu
    if action is not None:menu.clicked.connect(action)
    else:menu.hide()
    return frame


def _metric_icon(key):
    color={'bias':'#40bcff','field':'#44bdff','electrons':'#319cef','holes':'#f26d91','shift':'#ad8bfa'}[key]
    pixmap=QPixmap(90,108);pixmap.setDevicePixelRatio(3);pixmap.fill(Qt.GlobalColor.transparent)
    p=QPainter(pixmap);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen);background=QColor(color);background.setAlpha(25);p.setBrush(background);p.drawRoundedRect(QRectF(0,0,30,36),4,4)
    p.setPen(QPen(QColor(color),2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    if key=='bias':
        p.setBrush(QColor(color));p.setPen(Qt.PenStyle.NoPen);p.drawPolygon(QPolygonF([QPointF(18,5),QPointF(7,20),QPointF(14,20),QPointF(11,31),QPointF(24,14),QPointF(16,14)]))
    elif key=='field':
        p.setBrush(QColor(color));p.setPen(Qt.PenStyle.NoPen)
        for x,y in ((6,20),(13,13),(20,7)):p.drawRoundedRect(QRectF(x,y,4,29-y),.6,.6)
    elif key in ('electrons','holes'):
        p.setBrush(QColor(color));p.setPen(Qt.PenStyle.NoPen);p.drawEllipse(QRectF(5,9,21,21));p.setPen(QPen(QColor('#eaf6ff'),1.9));p.drawLine(QPointF(10,19.5),QPointF(21,19.5))
        if key=='holes':p.drawLine(QPointF(15.5,14),QPointF(15.5,25))
    else:p.drawPolyline(QPolygonF([QPointF(x,18+7*math.sin((x-5)*math.pi/9)) for x in range(4,27)]))
    p.end();return pixmap


class _RunDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):
        return QSize(200,73)

    def paint(self,painter,option,index):
        record=index.data(Qt.ItemDataRole.UserRole) or {}
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=QRectF(option.rect).adjusted(2,2,-2,-2)
        selected=bool(option.state&QStyle.StateFlag.State_Selected)
        gradient=QLinearGradient(rect.topLeft(),rect.bottomRight())
        gradient.setColorAt(0,QColor('#10446b' if selected else '#132a3b'))
        gradient.setColorAt(1,QColor('#0d2e49' if selected else '#0e2131'))
        painter.setBrush(gradient);painter.setPen(QPen(QColor('#1eb1ff' if selected else '#2a475c'),1))
        painter.drawRoundedRect(rect,4,4)
        icon=navigation_icon('Structure','#a9ddff' if selected else '#86aabc')
        icon.paint(painter,int(rect.left()+10),int(rect.top()+13),26,26)
        font=QFont(option.font);font.setPointSizeF(9.);font.setBold(True);painter.setFont(font)
        painter.setPen(QColor('#e1effc'))
        title=record.get('title') or Path(str(record.get('directory','Saved run'))).name
        painter.drawText(QPointF(rect.left()+46,rect.top()+20),QFontMetrics(font).elidedText(title,Qt.TextElideMode.ElideRight,int(rect.width()-57)))
        font.setBold(False);font.setPointSizeF(8.);painter.setFont(font)
        painter.setPen(QColor('#9bbbd0'))
        created=str(record.get('created',''))
        try:
            created=datetime.fromisoformat(created.replace('Z','+00:00')).strftime('%b %d · %H:%M')
        except ValueError:
            created=record.get('kind','Saved simulation')
        painter.drawText(QPointF(rect.left()+46,rect.top()+39),str(created))
        status=str(record.get('status','saved')).capitalize()
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor('#4de093' if status.lower()=='complete' else '#efc86a'))
        painter.drawEllipse(QPointF(rect.left()+50,rect.top()+56),3,3)
        painter.setPen(QColor('#c1d9e9'));painter.drawText(QPointF(rect.left()+59,rect.top()+59),status)
        painter.restore()


def _colorbar(painter,colors,rect,label):
    painter.save()
    gradient=QLinearGradient(rect.bottomLeft(),rect.topLeft())
    for step in range(17):
        value=colors.low+colors.span*step/16
        physical=10**value if colors.logarithmic else value
        gradient.setColorAt(step/16,colors.color(physical))
    painter.fillRect(rect,gradient)
    painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor('#94b1c7'),.8));painter.drawRect(rect)
    painter.setPen(QColor('#c5e0f4'))
    font=QFont(painter.font());font.setPointSizeF(7.7);painter.setFont(font)
    painter.drawText(QRectF(rect.left()-15,rect.top()-26,80,22),Qt.AlignmentFlag.AlignLeft,label)
    for step in range(5):
        position=step/4
        value=colors.high-(colors.high-colors.low)*position
        physical=10**value if colors.logarithmic else value
        y=rect.top()+position*rect.height()
        painter.drawLine(QPointF(rect.right(),y),QPointF(rect.right()+4,y))
        painter.drawText(QPointF(rect.right()+7,y+3),f'{physical:.2g}')
    painter.restore()


class ResultsMapCanvas(ElectricalSliceCanvas):
    """Compact actual-grid slice with device outlines, cursor and colorbar."""
    def __init__(self,plane='xy',parent=None):
        super().__init__(plane,parent)
        self.setMinimumSize(150,100)
        self.device={}
        self.plane_coordinate=0.
        self.unit='V'
        self.show_title=False
        self.preview_shape_count=0;self.total_shape_count=0

    def _plot_bounds(self):
        width,height=max(1,self.width()-133),max(1,self.height()-48)
        if self.plane=='xy' and self.axes is not None:
            first,second=[_axis_edges(axis) for axis in self.axes]
            ratio=(first[-1]-first[0])/max(second[-1]-second[0],1e-30)
            fitted_width=min(width,height*ratio);fitted_height=fitted_width/max(ratio,1e-30)
            return QRectF(44+(width-fitted_width)/2,14+(height-fitted_height)/2,fitted_width,fitted_height)
        return QRectF(44,14,width,height)

    def paintEvent(self,_):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme=COLORS[theme_manager().mode]
        painter.fillRect(self.rect(),QColor('#0b1f2e' if theme_manager().mode=='dark' else theme['field']))
        if self.values is None:
            painter.setPen(QColor(theme['muted']));painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'No saved field data')
            return
        rect=self._plot_bounds();a,b=self.axes;ea,eb=_axis_edges(a),_axis_edges(b)
        def project(x,y):
            return QPointF(rect.left()+(x-ea[0])/(ea[-1]-ea[0])*rect.width(),rect.top()+(y-eb[0])/(eb[-1]-eb[0])*rect.height())
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(len(a)):
            for j in range(len(b)):
                first,last=project(ea[i],eb[j]),project(ea[i+1],eb[j+1])
                painter.fillRect(QRectF(first,last).adjusted(0,0,.3,.3),self.colors.color(float(self.values[i,j])))
        if self.plane=='xy' and self.device:
            from device_model import layer_bounds,geometry_vertices,geometry_inner_vertices
            layer=next((row for row in layer_bounds(self.device) if row['z_min_um']-1e-9<=self.plane_coordinate*1e6<=row['z_max_um']+1e-9),None)
            if layer:
                objects,total=results_preview_shapes(self.device,layer['id'])
                self.preview_shape_count=len(objects);self.total_shape_count=total
                for obj in objects:
                    path=QPainterPath();path.setFillRule(Qt.FillRule.OddEvenFill)
                    for points in (geometry_vertices(obj,segments=32),geometry_inner_vertices(obj,segments=32)):
                        if points:
                            path.addPolygon(QPolygonF([project(x*1e-6,y*1e-6) for x,y in points]));path.closeSubpath()
                    painter.setPen(QPen(QColor('#233949' if obj.get('operation')=='void' else '#d7ebff'),.7))
                    painter.setBrush(QColor('#0a1c2b') if obj.get('operation')=='void' else Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
                if total>len(objects):
                    _pc_area_outline(painter,self.device,layer['id'],lambda x,y:project(x*1e-6,y*1e-6))
        if self.plane=='xz' and self.device:
            from device_model import layer_bounds
            painter.setPen(QPen(QColor(220,240,255,140),.7))
            for layer in layer_bounds(self.device):
                y=project(a[0],layer['z_max_um']*1e-6).y()
                if rect.top()<=y<=rect.bottom():painter.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
        painter.setPen(QPen(QColor('#e7f5ff'),.8,Qt.PenStyle.DashLine))
        if self.crosshair is not None:
            point=project(*self.crosshair)
            painter.drawLine(QPointF(point.x(),rect.top()),QPointF(point.x(),rect.bottom()))
            painter.drawLine(QPointF(rect.left(),point.y()),QPointF(rect.right(),point.y()))
        painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor('#34576f'),.7));painter.drawRect(rect)
        font=QFont(painter.font());font.setPointSizeF(7.5);painter.setFont(font);painter.setPen(QColor('#b3cddd'))
        for step in range(3):
            value=a[0]+(a[-1]-a[0])*step/2
            point=project(value,b[0]);painter.drawText(QRectF(point.x()-30,rect.bottom()+4,60,17),Qt.AlignmentFlag.AlignCenter,f'{value*1e6:.3g}')
        painter.drawText(QRectF(rect.left(),self.height()-17,rect.width(),17),Qt.AlignmentFlag.AlignCenter,'x (µm)')
        painter.save();painter.translate(14,rect.center().y());painter.rotate(-90)
        painter.drawText(QRectF(-rect.height()/2,0,rect.height(),18),Qt.AlignmentFlag.AlignCenter,('y' if self.plane=='xy' else 'Depth z')+' (µm)');painter.restore()
        _colorbar(painter,self.colors,QRectF(self.width()-71,22,12,max(30,self.height()-55)),self.unit)
        if self.total_shape_count>self.preview_shape_count:
            painter.setPen(QColor('#a6c7dd'));painter.drawText(7,11,f'Display {self.preview_shape_count:,}/{self.total_shape_count:,} shapes · full geometry retained')


class ResultsDeviceFieldCanvas(QWidget):
    """Actual extruded device surfaces, colored by nearest saved grid values."""
    positionPicked=pyqtSignal(float,float,float)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumSize(300,180)
        self.device={};self.data=None;self.values=None;self.colors=None;self.cursor=None
        self.yaw=-.60;self.elevation=.48;self.zoom=1.;self.hits=[];self._drag_start=self._last=None
        self.render_quality='studio';self.show_shadows=True;self.show_reflections=True;self.show_ambient_occlusion=True
        self.depth_display_mode='film'
        self.unit='V/m';self.quantity_label='|E| field';self.vertical_scale=1.
        self.surface_sample_count=0
        self.preview_shape_count=0;self.total_shape_count=0
        self._texture_cache={};self._texture_signature=None
        self.setMouseTracking(True)

    def set_field(self,device,data,values,colors,cursor,label,unit):
        self.device=device or {};self.data=data;self.values=values;self.colors=colors
        self.cursor=cursor;self.quantity_label=label;self.unit=unit;self.update()
        signature=(id(data),id(values),colors.low,colors.high,colors.logarithmic,colors.cmap.name)
        if signature!=self._texture_signature:self._texture_cache={};self._texture_signature=signature

    def _texture(self,key,values,first,second,first_bounds,second_bounds):
        """Bilinear display texture on true axes; numerical arrays stay untouched."""
        if key in self._texture_cache:return self._texture_cache[key]
        a=np.linspace(*first_bounds,192);b=np.linspace(*second_bounds,96)
        intermediate=np.array([np.interp(b,second,row) for row in np.asarray(values)])
        sampled=np.array([np.interp(a,first,intermediate[:,column]) for column in range(len(b))]).T
        display=np.log10(np.maximum(sampled,10**self.colors.low)) if self.colors.logarithmic else sampled
        normalized=np.clip((display-self.colors.low)/self.colors.span,0,1)
        rgba=(self.colors.cmap(normalized.T)*255).astype(np.uint8)
        image=QImage(rgba.tobytes(),len(a),len(b),len(a)*4,QImage.Format.Format_RGBA8888).copy()
        self._texture_cache[key]=image;return image

    def clear(self,message='No saved electrical field data'):
        self.values=None;self.data=None;self.device={};self.quantity_label=message;self.hits=[];self.update()

    def fit(self):
        self.zoom=1.;self.yaw=-.60;self.elevation=.48;self.update()

    def set_render_quality(self,quality='studio',*,shadows=None,reflections=None,ambient_occlusion=None):
        if quality not in ('studio','flat'):raise ValueError('Preview quality must be studio or flat')
        self.render_quality=quality
        for key,value in (('show_shadows',shadows),('show_reflections',reflections),('show_ambient_occlusion',ambient_occlusion)):
            if value is not None:setattr(self,key,bool(value))
        self.update()

    def _studio_shadow(self,painter,path,offset=QPointF(4.,6.),strength=1.):
        if self.render_quality!='studio' or not self.show_shadows:return
        painter.save();painter.setPen(Qt.PenStyle.NoPen)
        shifted=path.translated(offset);painter.setBrush(QColor(0,5,10,round(27*strength)));painter.drawPath(shifted)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for span,alpha in ((18.,3),(13.,5),(8.,8),(4.,12)):
            painter.setPen(QPen(QColor(0,5,10,round(alpha*strength)),span,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));painter.drawPath(shifted)
        painter.restore()

    def _field_surface_finish(self,painter,path,normal=(0.,0.,-1.)):
        """Subtle neutral light over a saved-value texture; no recoloring data."""
        if self.render_quality!='studio' or path.isEmpty():return
        painter.save();painter.setClipPath(path)
        if self.show_reflections:
            painter.fillRect(path.boundingRect(),sheen_brush(path.boundingRect(),intensity=.25))
        nx,ny,_=normal
        shade=max(0.,nx*math.sin(self.yaw)+ny*math.cos(self.yaw))
        gradient=QLinearGradient(path.boundingRect().topLeft(),path.boundingRect().bottomRight())
        gradient.setColorAt(0.,QColor(255,255,255,8));gradient.setColorAt(1.,QColor(0,8,15,round(13*shade)))
        painter.fillRect(path.boundingRect(),gradient)
        painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor(215,241,255,75),.75));painter.drawPath(path)
        painter.restore()

    def _geometry(self):
        if self.device.get('layers'):
            from device_model import layer_bounds
            return self.device,layer_bounds(self.device)
        if self.data is None:return {},[]
        x,y,z=[self.data[key]*1e6 for key in ('x','y','z')]
        ex,ey,ez=[_axis_edges(axis) for axis in (x,y,z)]
        device=dict(width_um=ex[-1]-ex[0],depth_um=ey[-1]-ey[0],shapes=[],contacts=[])
        layers=[dict(id='saved_volume',name='Saved solver volume',material_id='unknown',z_min_um=ez[0],z_max_um=ez[-1],thickness_um=ez[-1]-ez[0])]
        return device,layers

    def _paint_geometry(self,painter,theme):
        from device_model import geometry_vertices,geometry_inner_vertices
        device,layers=self._geometry()
        if not layers:return
        width,depth=device['width_um'],device['depth_um'];total=layers[-1]['z_max_um']
        above=below=0.
        for contact in device.get('contacts',[]):
            if not contact.get('enabled',True):continue
            thickness=float(contact.get('optical_thickness_um',0.) or 0.)
            if contact.get('surface')=='top' and contact.get('layer_id')==layers[0]['id']:above=max(above,thickness)
            if contact.get('surface')=='bottom' and contact.get('layer_id')==layers[-1]['id']:below=max(below,thickness)
        z_min,z_max=-above,total+below;draw_depth=z_max-z_min
        self.vertical_scale=1. if self.depth_display_mode=='physical' else min(100.,max(.25,min(width,depth)/max(draw_depth*7.,1e-9)))
        c,s=math.cos(self.yaw),math.sin(self.yaw)
        legend_width=140 if self.width()>650 else 105
        usable=max(100,self.width()-legend_width-96)
        extent_x=abs(c)*width+abs(s)*depth
        extent_y=(abs(s)*width+abs(c)*depth)*self.elevation+draw_depth*self.vertical_scale
        scale=min(usable/max(extent_x,1e-9),(self.height()-75)/max(extent_y,1e-9))*self.zoom
        center_x=legend_width+usable/2-10
        def project(x,y,z):
            return QPointF(center_x+(x*c-y*s)*scale,self.height()/2+9+(x*s+y*c)*scale*self.elevation+(z-(z_min+z_max)/2)*scale*self.vertical_scale)
        corners=[(-width/2,-depth/2),(width/2,-depth/2),(width/2,depth/2),(-width/2,depth/2)]
        def path(points,z):
            shape=QPainterPath();shape.addPolygon(QPolygonF([project(x,y,z) for x,y in points]));shape.closeSubpath();return shape
        def shape_path(obj,z):
            result=QPainterPath();result.setFillRule(Qt.FillRule.OddEvenFill)
            for points in (geometry_vertices(obj,segments=32),geometry_inner_vertices(obj,segments=32)):
                if points:
                    result.addPolygon(QPolygonF([project(x,y,z) for x,y in points]));result.closeSubpath()
            return result
        floor_path=path(corners,z_max)
        if self.render_quality=='studio' and self.show_reflections:
            floor_reflection=QTransform(1.,0.,0.,-.22,0.,floor_path.boundingRect().bottom()*1.22+4.)
            reflection=QLinearGradient(0.,floor_path.boundingRect().bottom(),0.,self.height())
            reflection.setColorAt(0.,QColor(93,157,197,17));reflection.setColorAt(1.,QColor(20,53,77,0))
            painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(reflection);painter.drawPath(floor_reflection.map(floor_path))
        self._studio_shadow(painter,floor_path,strength=1.2)
        def value_at(x,y,z):
            indices=tuple(int(np.argmin(abs(self.data[key]*1e6-value))) for key,value in zip(('x','y','z'),(x,y,z)))
            return float(self.values[indices])
        def face(points,z,color=None):
            polygon=QPolygonF([project(x,y,zz) for x,y,zz in points])
            painter.setPen(Qt.PenStyle.NoPen)
            center=np.mean(points,axis=0)
            painter.setBrush(color or self.colors.color(value_at(*center)))
            painter.drawPolygon(polygon)
            hit=QPainterPath();hit.addPolygon(polygon);hit.closeSubpath();self.hits.append((hit,tuple(center*1e-6)))
            self.surface_sample_count+=1
        # Floor grid follows the same physical device axes.
        painter.setPen(QPen(QColor(69,123,160,16),.6))
        for position in np.linspace(-max(width,depth),max(width,depth),15):
            painter.drawLine(project(-width,position,z_max+.03*total),project(width,position,z_max+.03*total))
            painter.drawLine(project(position,-depth,z_max+.03*total),project(position,depth,z_max+.03*total))
        xs,ys,zs=[self.data[key]*1e6 for key in ('x','y','z')]
        xe,ye=_axis_edges(xs),_axis_edges(ys)
        self.hits=[];self.surface_sample_count=0
        self.preview_shape_count=0;self.total_shape_count=0
        def texture_face(image,first,last,second,clip=None):
            origin=project(*first);right=project(*last);lower=project(*second)
            transform=QTransform((right.x()-origin.x())/image.width(),(right.y()-origin.y())/image.width(),
                                 (lower.x()-origin.x())/image.height(),(lower.y()-origin.y())/image.height(),origin.x(),origin.y())
            painter.save()
            if clip is not None:painter.setClipPath(clip)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,True);painter.setTransform(transform,True);painter.drawImage(QPointF(0,0),image);painter.restore()
        def add_hit(footprint,first,right,lower):
            origin=project(*first);x_end=project(*right);y_end=project(*lower)
            transform=QTransform(x_end.x()-origin.x(),x_end.y()-origin.y(),y_end.x()-origin.x(),y_end.y()-origin.y(),origin.x(),origin.y())
            inverse,valid=transform.inverted()
            if not valid:return
            start=np.asarray(first);dx=np.asarray(right)-start;dy=np.asarray(lower)-start
            def picked(point):
                local=inverse.map(point)
                return (start+local.x()*dx+local.y()*dy)*1e-6
            self.hits.append((footprint,picked))
        for layer in reversed(layers):
            top,bottom=layer['z_min_um'],layer['z_max_um'];zi=int(np.argmin(abs(zs-(top+bottom)/2)))
            objects,total_objects=results_preview_shapes(device,layer['id'])
            z_edges=np.unique(np.r_[top,_axis_edges(zs)[(_axis_edges(zs)>top)&(_axis_edges(zs)<bottom)],bottom])
            # Draw only the two front-facing exterior walls, with real depth samples.
            xside=width/2 if s>=0 else -width/2
            yside=depth/2 if c>=0 else -depth/2
            for side,axis in [('x',ys),('y',xs)]:
                extent=depth if side=='x' else width
                nearest=int(np.argmin(abs(xs-xside))) if side=='x' else int(np.argmin(abs(ys-yside)))
                values=self.values[nearest,:,:] if side=='x' else self.values[:,nearest,:]
                image=self._texture((layer['id'],side),values,axis,zs,(-extent/2,extent/2),(top,bottom))
                points=[(xside,-depth/2,top),(xside,depth/2,top),(xside,-depth/2,bottom)] if side=='x' else [(-width/2,yside,top),(width/2,yside,top),(-width/2,yside,bottom)]
                polygon=QPainterPath();polygon.addPolygon(QPolygonF([project(*points[0]),project(*points[1]),project(*(np.asarray(points[1])+np.asarray(points[2])-np.asarray(points[0]))),project(*points[2])]))
                polygon.closeSubpath()
                from qt_custom_device import _shape_section_intervals
                side_voids=QPainterPath()
                for obj in objects:
                    region=QPainterPath()
                    cut=math.nextafter(xside if side=='x' else yside,0.)
                    for low,high in _shape_section_intervals(obj,cut,swap=side=='x'):
                        low,high=max(low,-extent/2),min(high,extent/2)
                        if high<=low:continue
                        coordinates=[(xside,low,top),(xside,high,top),(xside,high,bottom),(xside,low,bottom)] if side=='x' else [(low,yside,top),(high,yside,top),(high,yside,bottom),(low,yside,bottom)]
                        piece=QPainterPath();piece.addPolygon(QPolygonF([project(*point) for point in coordinates]));piece.closeSubpath();region=region.united(piece)
                    side_voids=side_voids.united(region) if obj.get('operation')=='void' else side_voids.subtracted(region)
                polygon=polygon.subtracted(side_voids)
                texture_face(image,*points,polygon)
                self._field_surface_finish(painter,polygon,(1. if xside>0 else -1.,0.,0.) if side=='x' else (0.,1. if yside>0 else -1.,0.))
                add_hit(polygon,*points)
                self.surface_sample_count+=len(axis)*max(1,len(z_edges)-1)
            base=path(corners,top);voids=QPainterPath()
            self.preview_shape_count+=len(objects);self.total_shape_count+=total_objects
            for obj in objects:
                region=shape_path(obj,top).intersected(base)
                voids=voids.united(region) if obj.get('operation')=='void' else voids.subtracted(region)
            deck=base.subtracted(voids)
            zindex=int(np.argmin(abs(zs-top)))
            image=self._texture((layer['id'],'top'),self.values[:,:,zindex],xs,ys,(-width/2,width/2),(-depth/2,depth/2))
            texture_face(image,(-width/2,-depth/2,top),(width/2,-depth/2,top),(-width/2,depth/2,top),deck)
            add_hit(deck,(-width/2,-depth/2,top),(width/2,-depth/2,top),(-width/2,depth/2,top))
            self.surface_sample_count+=len(xs)*len(ys)
            self._field_surface_finish(painter,deck)
            painter.setPen(QPen(QColor(106,209,247,170),.6));painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawPath(deck)
            if total_objects>len(objects):_pc_area_outline(painter,device,layer['id'],lambda x,y,z=top:project(x,y,z))
            # Interior hole walls remain extrusions of the saved footprints.
            for obj in objects:
                if obj.get('operation')!='void':continue
                points=geometry_vertices(obj,segments=48)
                if sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1]))<0.:points.reverse()
                opening=shape_path(obj,top).intersected(voids)
                painter.save();painter.setClipPath(opening)
                interior=QPainterPath()
                curved=self.render_quality=='studio' and obj.get('shape') in ('circle','ellipse')
                for a,b in zip(points,points[1:]+points[:1]):
                    if (a[0]<-width/2 and b[0]<-width/2) or (a[0]>width/2 and b[0]>width/2) or (a[1]<-depth/2 and b[1]<-depth/2) or (a[1]>depth/2 and b[1]>depth/2):continue
                    dx,dy=b[0]-a[0],b[1]-a[1]
                    if dy*s-dx*c>=0.:continue
                    wall=QPainterPath();wall.addPolygon(QPolygonF([project(a[0],a[1],top),project(b[0],b[1],top),project(b[0],b[1],bottom),project(a[0],a[1],bottom)]));wall.closeSubpath()
                    interior=interior.united(wall)
                    color=self.colors.color(value_at((a[0]+b[0])/2,(a[1]+b[1])/2,(top+bottom)/2)).darker(140)
                    painter.setBrush(color);painter.setPen(QPen(color,.55));painter.drawPath(wall)
                if curved:
                    # A continuous neutral highlight smooths the cavity, while
                    # its base hues still come from the saved boundary samples.
                    smooth=QLinearGradient(interior.boundingRect().left(),0.,interior.boundingRect().right(),0.)
                    smooth.setColorAt(0.,QColor(4,15,25,26));smooth.setColorAt(.25,QColor(218,241,255,18));smooth.setColorAt(1.,QColor(1,8,13,43))
                    painter.setBrush(smooth);painter.setPen(Qt.PenStyle.NoPen);painter.drawPath(interior)
                if self.render_quality=='studio' and self.show_ambient_occlusion:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    for span,alpha in ((6.,12),(3.,28),(1.3,42)):
                        painter.setPen(QPen(QColor(1,8,13,alpha),span));painter.drawPath(opening)
                painter.restore()
                if self.render_quality=='studio':
                    painter.save();painter.setClipPath(deck);painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(191,231,251,125),1.1));painter.drawPath(opening);painter.restore()
            for contact in device.get('contacts',[]):
                if not contact.get('enabled',True) or contact.get('layer_id')!=layer['id']:continue
                surface=contact.get('surface','top')
                if surface in ('top','bottom'):
                    thickness=float(contact.get('optical_thickness_um',0.) or 0.)
                    z=top-thickness if surface=='top' else bottom
                    if surface=='bottom':
                        # From an above-device camera the underside is hidden.
                        # Its actual optical metal thickness remains visible
                        # along the exterior side walls, rather than becoming
                        # a fictitious golden floor in front of the device.
                        points=geometry_vertices(contact,segments=32)
                        for a,b in zip(points,points[1:]+points[:1]):
                            midpoint=((a[0]+b[0])/2,(a[1]+b[1])/2)
                            visible=(abs(midpoint[0]-xside)<1e-8 or abs(midpoint[1]-yside)<1e-8)
                            if visible and thickness>0:
                                wall=QPainterPath();wall.addPolygon(QPolygonF([project(*a,bottom),project(*b,bottom),project(*b,bottom+thickness),project(*a,bottom+thickness)]));wall.closeSubpath()
                                dx,dy=b[0]-a[0],b[1]-a[1];length=max(math.hypot(dx,dy),1e-12)
                                painter.setPen(QPen(QColor('#ffe09a'),.65))
                                painter.setBrush(studio_brush(QColor('#e5bb4b'),wall.boundingRect(),(dy/length,-dx/length,0.),self.yaw,metal=True,
                                    reflections=self.show_reflections) if self.render_quality=='studio' else QColor('#d5ab3b'))
                                painter.drawPath(wall)
                        continue
                    footprint=shape_path(contact,z).intersected(path(corners,z))
                    if surface=='top':
                        pad_voids=QPainterPath()
                        for obj in objects:
                            region=shape_path(obj,z).intersected(path(corners,z))
                            pad_voids=pad_voids.united(region) if obj.get('operation')=='void' else pad_voids.subtracted(region)
                        footprint=footprint.subtracted(pad_voids)
                    if thickness>0:
                        painter.save();painter.setClipPath(deck)
                        self._studio_shadow(painter,shape_path(contact,top),QPointF(1.5,2.5),.7);painter.restore()
                    if thickness>0:
                        for inner,points in enumerate((geometry_vertices(contact,segments=32),geometry_inner_vertices(contact,segments=32))):
                            for a,b in zip(points,points[1:]+points[:1]) if points else []:
                                dx,dy=b[0]-a[0],b[1]-a[1];length=max(math.hypot(dx,dy),1e-12)
                                normal=(dy/length*(-1 if inner else 1),-dx/length*(-1 if inner else 1),0.)
                                if normal[0]*s+normal[1]*c<=0.:continue
                                wall=QPainterPath();wall.addPolygon(QPolygonF([project(*a,top),project(*b,top),project(*b,z),project(*a,z)]));wall.closeSubpath()
                                painter.setPen(QPen(QColor('#edc856'),.5));painter.setBrush(studio_brush(QColor('#e5bb4b'),wall.boundingRect(),normal,self.yaw,
                                    metal=True,reflections=self.show_reflections) if self.render_quality=='studio' else QColor('#c19a36'))
                                painter.drawPath(wall)
                    painter.setPen(QPen(QColor('#ffe796'),.8))
                    painter.setBrush(studio_brush(QColor('#e5bb4b'),footprint.boundingRect(),yaw=self.yaw,metal=True,top=True,
                        reflections=self.show_reflections) if thickness>0 and self.render_quality=='studio' else QColor('#e5bb4b') if thickness>0 else QColor(229,187,75,37))
                    painter.drawPath(footprint)
                    if thickness>0 and self.render_quality=='studio' and self.show_reflections:
                        painter.save();painter.setClipPath(footprint);painter.fillRect(footprint.boundingRect(),sheen_brush(footprint.boundingRect(),metal=True,intensity=.6));painter.restore()
                    add_hit(footprint,(-width/2,-depth/2,z),(width/2,-depth/2,z),(-width/2,depth/2,z))
        if self.cursor is not None:
            x,y,z=np.asarray(self.cursor)*1e6
            plane=QPolygonF([project(x,-depth/2,0),project(x,depth/2,0),project(x,depth/2,total),project(x,-depth/2,total)])
            painter.setPen(QPen(QColor('#44c8ff'),1));painter.setBrush(QColor(34,160,223,17));painter.drawPolygon(plane)
            point=project(x,y,z);painter.setPen(QPen(QColor('#e9f7ff'),1.3));painter.setBrush(QColor('#ffffff'));painter.drawEllipse(point,3,3)
            caption=f'Probe x = {x:.4g} µm';metrics=painter.fontMetrics();label_width=metrics.horizontalAdvance(caption)+12
            label_x=max(legend_width+8,min(self.width()-label_width-77,point.x()+22))
            label_y=min(self.height()-35,max(point.y()+20,floor_path.boundingRect().bottom()+15))
            label_rect=QRectF(label_x,label_y-12,label_width,20)
            painter.setPen(QPen(QColor('#9acfeb'),.8));painter.drawLine(point,QPointF(label_rect.left()-4,label_rect.center().y()))
            painter.setPen(QPen(QColor(84,142,173,140),.7));painter.setBrush(QColor(7,24,36,220));painter.drawRoundedRect(label_rect,3,3)
            painter.setPen(QColor('#dbefff'));painter.drawText(label_rect,Qt.AlignmentFlag.AlignCenter,caption)
        font=QFont(painter.font());font.setPointSizeF(8.);painter.setFont(font)
        painter.setPen(QColor('#bed8ed'));painter.drawText(14,23,self.quantity_label+(' (log scale)' if self.colors.logarithmic else ''))
        from qt_custom_device import _layer_color,_contact_color
        legend=[(row['name'],_layer_color(row)) for row in layers]
        legend=[(obj['name'],_contact_color(obj)) for obj in device.get('contacts',[]) if obj.get('enabled',True)]+legend
        for index,(name,color) in enumerate(legend[:9]):
            painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(color));painter.drawRoundedRect(QRectF(17,43+index*19,10,11),1,1)
            painter.setPen(QColor('#c2dcec'));painter.drawText(33,53+index*19,QFontMetrics(font).elidedText(name,Qt.TextElideMode.ElideRight,legend_width-39))
        _colorbar(painter,self.colors,QRectF(self.width()-69,66,15,max(70,self.height()-132)),self.unit)
        origin=QPointF(29,self.height()-35)
        for label,delta,color in [('X',(25,4),'#f97670'),('Y',(-13,-16),'#6beaaf'),('Z',(0,-33),'#3baaff')]:
            endpoint=origin+QPointF(*delta);painter.setPen(QPen(QColor(color),1.8));painter.drawLine(origin,endpoint);painter.drawText(endpoint+QPointF(3,-2),label)
        painter.setPen(QColor('#81a7c2'))
        caption=f'Display: saved-value colormap + neutral studio light · probe/export: saved samples · vertical ×{self.vertical_scale:.3g}' if self.render_quality=='studio' else f'Display: bilinear face shading · probe/export: saved samples · vertical ×{self.vertical_scale:.3g}'
        painter.drawText(QRectF(92,self.height()-24,self.width()-103,21),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(font).elidedText(caption,Qt.TextElideMode.ElideRight,max(1,self.width()-103)))
        if self.total_shape_count>self.preview_shape_count:
            painter.setPen(QColor('#d5e9f6'));painter.drawText(15,self.height()-30,f'Display LOD: {self.preview_shape_count:,} of {self.total_shape_count:,} actual shapes · full geometry retained')

    def paintEvent(self,_):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme=COLORS[theme_manager().mode]
        gradient=QLinearGradient(0,0,self.width(),self.height());gradient.setColorAt(0,QColor('#102b3b'));gradient.setColorAt(1,QColor('#0a1c2c'))
        painter.fillRect(self.rect(),gradient)
        if self.render_quality=='studio':
            glow=QRadialGradient(QPointF(self.width()*.48,self.height()*.45),max(self.width(),self.height())*.62)
            glow.setColorAt(0.,QColor(63,114,149,32));glow.setColorAt(1.,QColor(5,16,27,0));painter.fillRect(self.rect(),glow)
        if self.values is None or self.data is None:
            painter.setPen(QColor('#9bbcd3'));painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,self.quantity_label)
            return
        self._paint_geometry(painter,theme)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self._drag_start=self._last=event.position()

    def mouseMoveEvent(self,event):
        if self._last is not None and event.buttons()&Qt.MouseButton.LeftButton:
            delta=event.position()-self._last;self.yaw+=delta.x()*.008;self.elevation=max(.12,min(.7,self.elevation+delta.y()*.003))
            self._last=event.position();self.update()

    def mouseReleaseEvent(self,event):
        if self._drag_start is not None and (event.position()-self._drag_start).manhattanLength()<5:
            for path,point in reversed(self.hits):
                if path.contains(event.position()):
                    value=point(event.position()) if callable(point) else point
                    self.positionPicked.emit(*value);break
        self._drag_start=self._last=None

    def wheelEvent(self,event):
        self.zoom=max(.4,min(3.,self.zoom*1.12**(event.angleDelta().y()/120)));self.update();event.accept()


class ResultsWorkspace(ElectricalResultsPanel):
    """Full three-column results page matching the approved desktop composition."""
    openRunRequested=pyqtSignal()
    rerunRequested=pyqtSignal()
    resultLoaded=pyqtSignal(str)

    def __init__(self,store=None,parent=None):
        self._workspace_ready=False
        self.store=store
        self.saved_project={};self.optical_data=pd.DataFrame();self.profile_data=pd.DataFrame();self.feature_data=pd.DataFrame()
        self._saved_optical_cell={}
        self._reference_volume=None;self._saved_runs=[];self._active_category='Overview'
        self.optical_source_directory=None;self.has_optical_fields=False;self.has_specular_phase=False
        super().__init__(parent)
        self.setObjectName('resultsWorkspace')
        # Keep the existing panel as the numerical controller while replacing
        # its embedded tabs with the reference's full workspace composition.
        old_layout=self.layout()
        while old_layout.count():
            item=old_layout.takeAt(0)
            if item.widget():item.widget().hide()
            elif item.layout():
                inner=item.layout()
                while inner.count():
                    child=inner.takeAt(0)
                    if child.widget():child.widget().hide()
        old_layout.setContentsMargins(8,8,8,6);old_layout.setSpacing(6)
        self._body=QHBoxLayout();self._body.setSpacing(7)
        old_layout.addLayout(self._body,1)
        self._build_left();self._build_center();self._build_right();self._build_footer(old_layout)
        self.setMinimumSize(1180,650)
        self._apply_style()
        self._workspace_ready=True
        self.probeChanged.connect(self._probe_updated)
        self.biasChanged.connect(lambda _:self._refresh_workspace())
        theme_manager().changed.connect(self._apply_style)
        if store is not None:
            self.refresh_saved_runs()
            store.library_changed.connect(self.refresh_saved_runs)

    def _apply_style(self,*_):
        self.setStyleSheet('''
            #resultsWorkspace { background:#081a29; color:#d8eaf8; }
            #resultsWorkspace QLabel { color:#c8def0; background:transparent; }
            #resultsCard { background:#0d2232; border:1px solid #2a485e; border-radius:4px; }
            #resultsCardHeader { background:#10283a; border-bottom:1px solid #28465b; border-radius:0; }
            #resultsCardTitle { color:#e1effc; font-size:12px; font-weight:600; }
            #resultsMore { background:transparent; border:0; font-size:18px; color:#b3cadc; }
            #resultsWorkspace QComboBox,#resultsWorkspace QDoubleSpinBox { background:#091c2b; border:1px solid #36526a; border-radius:4px; padding:3px 6px; min-height:22px; font-size:11px; }
            #resultsWorkspace QPushButton { background:#102a3e; border:1px solid #335671; border-radius:4px; color:#d4e9f9; padding:5px 10px; font-size:11px; }
            #resultsWorkspace QPushButton:hover { background:#143952; border-color:#3d9ee5; }
            #resultsWorkspace QPushButton:checked { background:#10416c; border-color:#19a5f9; }
            #resultsWorkspace QListWidget { border:0; background:transparent; outline:0; }
            #resultsWorkspace QCheckBox { font-size:11px; color:#c4daee; spacing:6px; }
            #resultsWorkspace QSlider::groove:horizontal { height:4px; background:#2b4c63; border-radius:2px; }
            #resultsWorkspace QSlider::sub-page:horizontal { background:#28a8fa; border-radius:2px; }
            #resultsWorkspace QSlider::handle:horizontal { width:11px; margin:-4px 0; background:#48b5ff; border:1px solid #77ceff; border-radius:6px; }
            #resultsWorkspace QPlainTextEdit { background:#0a1d2c; color:#bbd5e9; border:1px solid #29465c; border-radius:3px; font-size:10px; }
            #resultsWorkspace QScrollArea { background:transparent; border:0; }
            #resultsNavigation { text-align:left; border:0; background:transparent; padding:9px 11px; font-size:11px; }
            #resultsNavigation:checked { background:#123e62; border:1px solid #278ccc; }
            #resultsMetric { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #112d40,stop:1 #0c2131); border:1px solid #2b4c64; border-radius:4px; }
            #metricTitle { color:#a7c6df; font-size:10px; }
            #metricValue { color:#e3f2ff; font-size:18px; font-weight:600; }
            #metricSymbol { background:#153a52; color:#45bbff; font-size:24px; border-radius:4px; }
            #resultsInfo { background:#0f3047; border:1px solid #226187; border-radius:4px; color:#9fcae7; padding:4px 8px; font-size:10px; }
            #resultsPrimary { background:#086bdd; border:1px solid #2598ff; color:white; }
            #resultsExpander { text-align:left; background:#10293b; font-size:11px; padding:6px 8px; }
            #resultsFooter { background:#102637; border-top:1px solid #31536b; }
        ''')

    def _build_left(self):
        self.left_rail=_frame();self.left_rail.setFixedWidth(244)
        layout=QVBoxLayout(self.left_rail);layout.setContentsMargins(8,10,8,9);layout.setSpacing(8)
        row=QHBoxLayout();title=QLabel('Saved runs');title.setObjectName('resultsCardTitle');row.addWidget(title,1)
        add=QToolButton();add.setText('+');add.setFixedSize(24,24);add.setToolTip('Open a saved run folder');add.clicked.connect(self._open_requested);row.addWidget(add)
        layout.addLayout(row)
        self.saved_run_list=QListWidget();self.saved_run_list.setItemDelegate(_RunDelegate(self.saved_run_list))
        self.saved_run_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.saved_run_list.setFixedHeight(78);self.saved_run_list.currentItemChanged.connect(self._saved_run_selected)
        self.saved_run_list.setToolTip('Scroll to select another saved run; the active run remains highlighted.')
        layout.addWidget(self.saved_run_list)
        def field(label,widget):
            row=QHBoxLayout();row.addWidget(QLabel(label),1);row.addWidget(widget,2);layout.addLayout(row);widget.show()
        field('Bias (V)',self.result_bias)
        self.compare_zero=QCheckBox('Compare with 0 V');self.compare_zero.setToolTip('Overlay the saved zero-offset reference in depth and optical charts.')
        self.compare_zero.toggled.connect(self._draw_charts);layout.addWidget(self.compare_zero)
        field('Visualize',self.quantity)
        self.scale_choice=QComboBox();self.scale_choice.addItems(['Linear','Log']);self.scale_choice.currentTextChanged.connect(lambda text:self.log_colors.setChecked(text=='Log'))
        field('Scale',self.scale_choice)
        label=QLabel('Slice position (µm)');label.setContentsMargins(0,7,0,0);layout.addWidget(label)
        self.cursor_sliders={}
        for key in ('x','y','z'):
            row=QHBoxLayout();name=QLabel(key.upper());name.setFixedWidth(12);row.addWidget(name)
            slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(0,0);slider.valueChanged.connect(lambda value,k=key:self._slide_cursor(k,value));row.addWidget(slider,1)
            self.cursor_sliders[key]=slider
            control=self.cursor_controls[key];control.setDecimals(4);control.setSuffix('');control.setFixedWidth(70);control.setMinimumWidth(0);control.show();row.addWidget(control)
            layout.addLayout(row)
        layout.addSpacing(8)
        self.nav_buttons={}
        categories=[('Overview','Structure'),('Potential & fields','Fields'),('Carriers & charge','Materials'),
                    ('Energy bands','Optimize'),('Optical response','appearance'),('I–V / C–V','performance'),
                    ('Mesh & convergence','addons'),('Inputs & materials','Materials'),('Raw data & exports','Saved work'),
                    ('Optical E/H','Fields'),('Specular phase','appearance')]
        category_content=QWidget();category_layout=QVBoxLayout(category_content);category_layout.setContentsMargins(0,0,0,0);category_layout.setSpacing(4)
        for name,icon_name in categories:
            button=QPushButton(name.replace('&','&&'));button.setObjectName('resultsNavigation');button.setCheckable(True)
            button.setIcon(navigation_icon(icon_name,'#b8ddf7'));button.setIconSize(QSize(20,20));button.setMinimumHeight(36)
            button.clicked.connect(lambda _,n=name:self.select_category(n));category_layout.addWidget(button)
            self.nav_buttons[name]=button
        self.nav_buttons['Overview'].setChecked(True)
        category_layout.addStretch(1)
        category_scroll=QScrollArea();category_scroll.setWidgetResizable(True);category_scroll.setFrameShape(QFrame.Shape.NoFrame);category_scroll.setWidget(category_content)
        self.category_scroll=category_scroll
        layout.addWidget(category_scroll,1)
        self._body.addWidget(self.left_rail)

    def _build_center(self):
        self.center=QWidget();layout=QVBoxLayout(self.center);layout.setContentsMargins(0,0,0,0);layout.setSpacing(6)
        metric_row=QHBoxLayout();metric_row.setSpacing(6)
        self.metric_values={};self.metric_cards=[]
        for key,title,symbol in [('bias','Applied bias','ϟ'),('field','Peak field','▥'),('electrons','Peak electrons','−'),('holes','Peak holes','+'),('shift','Optical peak shift','∿')]:
            frame=QFrame();frame.setObjectName('resultsMetric');frame.setFixedHeight(65)
            row=QHBoxLayout(frame);row.setContentsMargins(10,6,8,6);row.setSpacing(8)
            icon=QLabel();icon.setPixmap(_metric_icon(key));icon.setAlignment(Qt.AlignmentFlag.AlignCenter);icon.setFixedSize(34,39);row.addWidget(icon)
            text=QVBoxLayout();text.setSpacing(3);label=QLabel(title);label.setObjectName('metricTitle');value=QLabel('—');value.setObjectName('metricValue')
            text.addWidget(label);text.addWidget(value);row.addLayout(text,1);metric_row.addWidget(frame,1)
            self.metric_values[key]=value
            self.metric_cards.append(frame)
        layout.addLayout(metric_row)
        self.info_label=QLabel('ⓘ  Open a saved run to display its computed fields and optical spectra.');self.info_label.setObjectName('resultsInfo');self.info_label.setFixedHeight(24)
        layout.addWidget(self.info_label)
        self.center_stack=QStackedWidget();layout.addWidget(self.center_stack,1)
        overview=QWidget();overview_layout=QVBoxLayout(overview);overview_layout.setContentsMargins(0,0,0,0);overview_layout.setSpacing(6)
        main=_frame();main_layout=QVBoxLayout(main);main_layout.setContentsMargins(0,0,0,0);main_layout.setSpacing(0)
        self.mode_buttons={};bar=QFrame();bar.setObjectName('resultsCardHeader');bar.setFixedHeight(30);bar_row=QHBoxLayout(bar);bar_row.setContentsMargins(0,0,0,0);bar_row.setSpacing(0)
        for title in ('3D fields','Top view · XY','Cross section · XZ','Depth profiles','Optical spectra'):
            button=QPushButton(title);button.setCheckable(True);button.setChecked(title=='3D fields');button.setStyleSheet('border-radius:0;border:0;border-right:1px solid #29465b;padding:5px 10px;font-size:10px;')
            button.clicked.connect(lambda _,t=title:self.focus_view(t));bar_row.addWidget(button);self.mode_buttons[title]=button
        bar_row.addStretch(1);main_layout.addWidget(bar)
        self.scene_stack=QStackedWidget()
        self.field_scene=ResultsDeviceFieldCanvas();self.field_scene.positionPicked.connect(self.set_probe);self.scene_stack.addWidget(self.field_scene)
        from qt_custom_device import DeviceCanvas
        self.geometry_scene=DeviceCanvas('3d');self.scene_stack.addWidget(self.geometry_scene)
        self.geometry_scene.depth_display_mode='film'
        self.hero_stack=QStackedWidget();self.hero_stack.addWidget(self.scene_stack)
        self.hero_top=ResultsMapCanvas('xy');self.hero_cross=ResultsMapCanvas('xz')
        self.hero_top.positionPicked.connect(self._pick_xy);self.hero_cross.positionPicked.connect(self._pick_xz)
        self.hero_stack.addWidget(self.hero_top);self.hero_stack.addWidget(self.hero_cross)
        self.hero_depth=_small_plot();self.hero_optical=_small_plot();self.hero_stack.addWidget(self.hero_depth);self.hero_stack.addWidget(self.hero_optical)
        main_layout.addWidget(self.hero_stack,1)
        overview_layout.addWidget(main,37)
        maps=QWidget();map_row=QHBoxLayout(maps);map_row.setContentsMargins(0,0,0,0);map_row.setSpacing(6)
        self.top_view=ResultsMapCanvas('xy');self.cross_view=ResultsMapCanvas('xz')
        self.top_view.positionPicked.connect(self._pick_xy);self.cross_view.positionPicked.connect(self._pick_xz)
        self.top_card=_card('Potential · XY',self.top_view);self.cross_card=_card('|E| · XZ',self.cross_view)
        self.top_card.more_button.clicked.connect(lambda:self.export_dialog('figure'));self.cross_card.more_button.clicked.connect(lambda:self.export_dialog('figure'))
        self.top_card.more_button.show();self.cross_card.more_button.show()
        map_row.addWidget(self.top_card,1);map_row.addWidget(self.cross_card,1);overview_layout.addWidget(maps,22)
        charts=QWidget();chart_row=QHBoxLayout(charts);chart_row.setContentsMargins(0,0,0,0);chart_row.setSpacing(6)
        self.depth_plot=_small_plot();self.rta_plot=_small_plot()
        depth_content,self.depth_legend=_legend_column(self.depth_plot)
        optical_content,self.rta_legend=_legend_column(self.rta_plot)
        self.depth_card=_card('Carrier & potential depth profiles (at cursor XY)',depth_content)
        self.rta_card=_card('Optical R / T / A (periodic incidence)',optical_content)
        self.depth_card.more_button.clicked.connect(self.depth_plot.export_dialog);self.rta_card.more_button.clicked.connect(self.rta_plot.export_dialog)
        self.depth_card.more_button.show();self.rta_card.more_button.show()
        chart_row.addWidget(self.depth_card,1);chart_row.addWidget(self.rta_card,1);overview_layout.addWidget(charts,22)
        self.center_stack.addWidget(overview)
        self.energy_plot=_small_plot();self.center_stack.addWidget(_card('Saved affinity-rule band edges at the cursor',self.energy_plot,self.energy_plot.export_dialog))
        self.optical_plot=_small_plot();self.center_stack.addWidget(_card('Optical R / T / A · saved spectra',self.optical_plot,self.optical_plot.export_dialog))
        terminal=QWidget();terminal_layout=QVBoxLayout(terminal);terminal_layout.setContentsMargins(0,0,0,0)
        self.terminal_cards={}
        for kind,title,scope,plot in [('iv','I–V · No saved current study',self.iv_scope,self.iv_plot),('cv','C–V · No saved capacitance study',self.cv_scope,self.cv_plot)]:
            plot.setMinimumHeight(0);plot.toolbar.hide();scope.show();plot.show()
            content=QWidget();inner=QVBoxLayout(content);inner.addWidget(scope);inner.addWidget(plot,1)
            card=_card(title,content,plot.export_dialog);self.terminal_cards[kind]=card;terminal_layout.addWidget(card,1)
        self.center_stack.addWidget(terminal)
        self.checks_table.show();self.center_stack.addWidget(_card('Actual mesh and numerical checks',self.checks_table))
        metadata=QWidget();metadata_layout=QHBoxLayout(metadata);metadata_layout.setContentsMargins(0,0,0,0)
        self.sources.show();self.inputs.show();metadata_layout.addWidget(_card('Material models and sources',self.sources),1);metadata_layout.addWidget(_card('Saved inputs and structure',self.inputs),1)
        self.center_stack.addWidget(metadata)
        self.raw_files=QListWidget();self.raw_files.itemDoubleClicked.connect(self._open_saved_file)
        self.center_stack.addWidget(_card('Raw result files · double-click to open',self.raw_files))
        from qt_optical_results import OpticalFieldResultsPanel,SpecularPhaseResultsPanel
        self.optical_fields_panel=OpticalFieldResultsPanel(self.store)
        self.phase_panel=SpecularPhaseResultsPanel()
        self.center_stack.addWidget(_card('Saved optical E/H phasor fields',self.optical_fields_panel))
        self.center_stack.addWidget(_card('Saved specular reflection / transmission phase',self.phase_panel))
        self._body.addWidget(self.center,1)

    def _build_right(self):
        self.right_rail=_frame();self.right_rail.setFixedWidth(333)
        right_layout=QVBoxLayout(self.right_rail);right_layout.setContentsMargins(0,0,0,0)
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        content=QWidget();layout=QVBoxLayout(content);layout.setContentsMargins(12,10,12,10);layout.setSpacing(8)
        title=QLabel('Run summary');title.setObjectName('resultsCardTitle');layout.addWidget(title)
        self.run_value_labels={}
        for key,label in [('model','Model'),('biases','Bias states'),('mesh','Mesh cells'),('elapsed','Elapsed time')]:
            row=QHBoxLayout();caption=QLabel(label);caption.setFixedWidth(85);row.addWidget(caption)
            value=QLabel('—');value.setWordWrap(True);value.setStyleSheet('font-size:11px;');row.addWidget(value,1);layout.addLayout(row);self.run_value_labels[key]=value
        badge_row=QHBoxLayout();self.convergence_badge=QLabel('Convergence unavailable');self.balance_badge=QLabel('Charge balance unavailable')
        for badge in (self.convergence_badge,self.balance_badge):badge.setStyleSheet('background:#12283a;border:1px solid #31546b;border-radius:4px;padding:6px;font-size:10px;');badge_row.addWidget(badge)
        layout.addLayout(badge_row)
        heading=QLabel('Numerical checks');heading.setContentsMargins(0,7,0,0);heading.setObjectName('resultsCardTitle');layout.addWidget(heading)
        self.check_labels={}
        for key,label in [('residual','Poisson residual'),('gauss','Gauss balance'),('refinement','Mesh refinement')]:
            row=QHBoxLayout();row.addWidget(QLabel(label),1);value=QLabel('Unavailable');value.setStyleSheet('font-size:11px;');row.addWidget(value,1);layout.addLayout(row);self.check_labels[key]=value
        self.detail_expanders={}
        for key,title in [('boundary','Boundary conditions'),('sources','Material models & sources'),('assumptions','Assumptions')]:
            button=QPushButton('›  '+title.replace('&','&&'));button.setObjectName('resultsExpander');button.setCheckable(True)
            text=QPlainTextEdit();text.setReadOnly(True);text.setMinimumHeight(80);text.setMaximumHeight(190);text.hide()
            button.toggled.connect(lambda checked,w=text,b=button,t=title:(w.setVisible(checked),b.setText(('⌄  ' if checked else '›  ')+t.replace('&','&&'))))
            layout.addWidget(button);layout.addWidget(text);self.detail_expanders[key]=text
        self.current_scope=QLabel('Current / I–V: no saved study');self.current_scope.setWordWrap(True);self.current_scope.setStyleSheet('font-size:11px;');layout.addWidget(self.current_scope)
        self.optical_scope=QLabel('Optical model: unavailable');self.optical_scope.setWordWrap(True);self.optical_scope.setStyleSheet('font-size:11px;');layout.addWidget(self.optical_scope)
        probe_title=QLabel('Probe at cursor position');probe_title.setObjectName('resultsCardTitle');probe_title.setContentsMargins(0,8,0,0);layout.addWidget(probe_title)
        self.probe_values={};probe_grid=QGridLayout();probe_grid.setHorizontalSpacing(10);probe_grid.setVerticalSpacing(7)
        for row,(key,label) in enumerate([('x','X (µm)'),('y','Y (µm)'),('z','Z (µm)'),('potential','Potential (V)'),('Ex_V_m','Ex (V/m)'),('Ey_V_m','Ey (V/m)'),('Ez_V_m','Ez (V/m)'),('electrons_cm3','Electrons (cm⁻³)'),('holes_cm3','Holes (cm⁻³)'),('charge_density_C_m3','Charge (C/m³)')]):
            probe_grid.addWidget(QLabel(label),row,0);value=QLabel('—');value.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter);value.setStyleSheet('font-size:11px;');probe_grid.addWidget(value,row,1);self.probe_values[key]=value
        layout.addLayout(probe_grid)
        self.probe_identity=QLabel('Nearest saved grid sample');self.probe_identity.setWordWrap(True);self.probe_identity.setStyleSheet('font-size:10px;color:#86adc9;');layout.addWidget(self.probe_identity)
        layout.addStretch(1);scroll.setWidget(content);right_layout.addWidget(scroll)
        self._body.addWidget(self.right_rail)

    def _build_footer(self,layout):
        footer=QFrame();footer.setObjectName('resultsFooter');footer.setFixedHeight(62);self.footer_widget=footer
        footer.setStyleSheet('''QFrame#resultsFooter {background:#102637;border-top:1px solid #31536b;}
            QLabel {color:#a9cee8;background:transparent;} QPushButton {background:#102a3e;border:1px solid #335671;border-radius:4px;color:#d4e9f9;padding:7px 10px;font-size:11px;}
            QPushButton#resultsPrimary {background:#086bdd;border:1px solid #2598ff;color:white;}
            QPushButton:hover {background:#174061;border-color:#3d9ee5;}''')
        row=QHBoxLayout(footer);row.setContentsMargins(7,5,7,5);row.setSpacing(7)
        self.footer_label=QLabel('ⓘ  No saved run selected');self.footer_label.setWordWrap(True);self.footer_label.setStyleSheet('font-size:10px;color:#8cb6d4;');row.addWidget(self.footer_label,1)
        buttons=[('Open run folder',self.open_run_folder),('Export CSV / NPZ',self._export_data_menu),('Export VTK',lambda:self.export_dialog('vtk')),
                 ('Export figures',self.export_visible_figure),('Create report',self.export_report)]
        self.workspace_export_buttons={}
        for title,callback in buttons:
            button=QPushButton(title);button.setIcon(navigation_icon('Saved work','#b3d7f0'));button.setIconSize(QSize(16,16));button.clicked.connect(callback);row.addWidget(button);self.workspace_export_buttons[title]=button
        rerun=QPushButton('Rerun / refine mesh');rerun.setObjectName('resultsPrimary');rerun.setIcon(navigation_icon('Simulate','#ffffff'));rerun.clicked.connect(self.rerunRequested.emit);row.addWidget(rerun)
        self.rerun_button=rerun;layout.addWidget(footer)

    def _open_requested(self):
        self.openRunRequested.emit()

    def refresh_saved_runs(self):
        if self.store is None or not hasattr(self.store,'library'):return
        records=[]
        for record in self.store.library.entries():
            value=dict(record);value['directory']=str(self.store.library.runs/record['id']);records.append(value)
        self.set_saved_runs(records)

    def set_saved_runs(self,records):
        self._saved_runs=[dict(row) for row in records]
        with QSignalBlocker(self.saved_run_list):
            self.saved_run_list.clear()
            for record in self._saved_runs:
                item=QListWidgetItem(record.get('title','Saved run'));item.setData(Qt.ItemDataRole.UserRole,record);item.setToolTip(record.get('title','Saved run'))
                self.saved_run_list.addItem(item)
                if self.directory and Path(record.get('directory','')).resolve()==self.directory.resolve():self.saved_run_list.setCurrentItem(item)

    def _saved_run_selected(self,item,*_):
        if item is None:return
        record=item.data(Qt.ItemDataRole.UserRole) or {}
        if record.get('directory'):
            try:self.load_run(record['directory'])
            except (OSError,ValueError) as exc:self.info_label.setText('ⓘ  '+str(exc))

    def load_run(self,directory):
        directory=Path(directory)
        path=saved_result_path(directory,'electrical_summary.json')
        if path:
            summary=json.loads(path.read_text(encoding='utf-8'))
        else:
            record_path=directory/'library_record.json'
            record=json.loads(record_path.read_text(encoding='utf-8')) if record_path.is_file() else {}
            summary=dict(model='optical_only',results=[],optical=record.get('summary',{}),title=record.get('title',directory.name))
            has_fields=(directory/'fields'/'samples.json').is_file() or (directory/'fields'/'samples.sqlite').is_file()
            if not (directory/'results.csv').is_file() and not has_fields and not (directory/'phase.csv').is_file():raise ValueError('This folder has no saved electrical or optical result data.')
        self.set_result(directory,summary)
        self._restore_presentation()
        self.resultLoaded.emit(str(directory))

    def _restore_presentation(self):
        """Use the presentation choices frozen with the submitted project."""
        values=self.saved_project.get('desktop_search',{}).get('simulation_setup',{}).get('values',{})
        category={'overview':'Overview','fields':'Potential & fields','carriers':'Carriers & charge',
            'iv':'I–V / C–V','cv':'I–V / C–V','checks':'Mesh & convergence'}.get(
                values.get('ui.electrical.initial_result_tab','overview'),'Overview')
        self.select_category(category if self._result_rows else 'Optical E/H' if self.has_optical_fields else 'Specular phase' if self.has_specular_phase and self.optical_data.empty else 'Optical response')
        key={'potential':'potential','field_magnitude':'field_magnitude_V_m','Ex':'Ex_V_m','Ey':'Ey_V_m','Ez':'Ez_V_m',
            'electrons':'electrons_cm3','holes':'holes_cm3','charge_density':'charge_density_C_m3',
            'doping':'net_doping_cm3','epsilon_r':'epsilon_r'}.get(values.get('ui.electrical.initial_field','field_magnitude'))
        index=self.quantity.findData(key)
        if index>=0 and self.volume is not None and key in self.volume:self.quantity.setCurrentIndex(index)
        self.scale_choice.setCurrentText('Log' if values.get('ui.electrical.density_scale','log')=='log' else 'Linear')

    def set_result(self,directory,summary):
        self.saved_project={};path=Path(directory)/'project.json'
        self._saved_optical_cell=_saved_optical_cell(directory) if summary.get('model')=='optical_only' else {}
        if path.is_file():
            try:self.saved_project=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):self.saved_project={}
        super().set_result(directory,summary)
        if not self._workspace_ready:return
        self._read_extra_data();self._reference_volume=None
        self._load_optical_saved_panels()
        self.field_scene.device=summary.get('device') or summary.get('options',{}).get('device') or self.saved_project.get('device',{})
        index=self.quantity.findData('field_magnitude_V_m')
        if self.volume is not None and 'field_magnitude_V_m' in self.volume:self.quantity.setCurrentIndex(index)
        self.compare_zero.setEnabled(any(abs(float(row['bias_V']))<1e-12 for row in self._result_rows))
        if self.quantity.currentData()=='field_magnitude_V_m':self.scale_choice.setCurrentText('Log')
        self._refresh_workspace();self.redraw();self._draw_charts();self._draw_band_edges();self._populate_files()
        if self.volume is not None:
            self.set_probe(*self._initial_probe_coordinates())
        record=next((row for row in self._saved_runs if Path(row.get('directory','')).resolve()==self.directory.resolve()),None)
        if record:
            with QSignalBlocker(self.saved_run_list):
                for index in range(self.saved_run_list.count()):
                    item=self.saved_run_list.item(index)
                    if item.data(Qt.ItemDataRole.UserRole)==record:self.saved_run_list.setCurrentItem(item)

    def _initial_probe_coordinates(self):
        """Choose a real solid sample near the XY center, if a mask was saved."""
        x,y,z=[self.volume[key] for key in ('x','y','z')]
        ix,iy=len(x)//2,len(y)//2
        solid=self.volume.get('solid')
        if solid is not None and np.asarray(solid).shape==(len(x),len(y),len(z)):
            candidates=np.argwhere(np.asarray(solid)[:,:,0].astype(bool))
            if len(candidates):
                center_x,center_y=(x[0]+x[-1])/2,(y[0]+y[-1])/2
                distances=(x[candidates[:,0]]-center_x)**2+(y[candidates[:,1]]-center_y)**2
                ix,iy=map(int,candidates[int(np.argmin(distances))])
        return float(x[ix]),float(y[iy]),float(z[0])

    def _load_optical_saved_panels(self):
        """Bind field-only jobs and their real parent spectrum without inventing CSVs."""
        directory=self.directory
        self.has_optical_fields=bool(directory and ((directory/'fields'/'samples.json').is_file() or (directory/'fields'/'samples.sqlite').is_file()))
        self.optical_source_directory=directory
        if directory and not (directory/'results.csv').is_file():
            try:
                request=directory/'desktop_request.json'
                options=json.loads(request.read_text(encoding='utf-8')).get('options',{}) if request.is_file() else {}
                identifier=options.get('spectrum_id')
                if identifier and self.store is not None:self.optical_source_directory=self.store.library.directory(identifier)
                else:
                    job=directory/'job.json'
                    search=json.loads(job.read_text(encoding='utf-8')).get('search',{}) if job.is_file() else {}
                    parent=search.get('spectrum_directory')
                    if parent and Path(parent).is_dir():self.optical_source_directory=Path(parent)
            except (ValueError,TypeError,KeyError,OSError):self.optical_source_directory=directory
        parent=self.optical_source_directory
        if self.optical_data.empty and parent and parent!=directory and (parent/'results.csv').is_file():
            try:self.optical_data=pd.read_csv(parent/'results.csv')
            except (ValueError,OSError,pd.errors.EmptyDataError):pass
        phase=directory/'phase.csv' if directory else None
        if phase and not phase.is_file() and parent:phase=parent/'phase.csv'
        self.has_specular_phase=bool(phase and phase.is_file())
        self.optical_fields_panel.set_directory(directory if self.has_optical_fields else None)
        self.phase_panel.set_path(phase if self.has_specular_phase else None)
        self.nav_buttons['Optical E/H'].setEnabled(self.has_optical_fields)
        self.nav_buttons['Specular phase'].setEnabled(self.has_specular_phase)

    def _read_extra_data(self):
        def read(value,default):
            path=saved_result_path(self.directory,value or default)
            if path:
                try:return pd.read_csv(path)
                except (OSError,ValueError,pd.errors.EmptyDataError):pass
            return pd.DataFrame()
        optical=self.summary.get('optical',{})
        self.optical_data=read(optical.get('spectra_csv') or self.summary.get('spectra_csv'),'electrical_optical_spectra.csv')
        if self.optical_data.empty:self.optical_data=read(None,'results.csv')
        self.feature_data=read(optical.get('features_csv') or self.summary.get('features_csv'),'electrical_features.csv')
        profiles=[]
        for row in self._result_rows:
            data=read(row.get('profile_csv'),'')
            if not data.empty:data['bias_V']=row['bias_V'];profiles.append(data)
        self.profile_data=pd.concat(profiles,ignore_index=True) if profiles else pd.DataFrame()

    def _metadata(self):
        super()._metadata()
        if self.summary.get('model')!='optical_only' or not self.saved_project:return
        # Optical runs retain the physical project even when they have no
        # electrical summary. Keep its actual inputs visible without putting
        # tens of thousands of generated records into a text widget.
        device=self.saved_project.get('device',{})
        structure={key:value for key,value in device.items() if key not in ('shapes','pc_arrays')}
        structure['shape_count']=len(device.get('shapes',[]))
        structure['pc_arrays']=[{key:value for key,value in area.items() if key!='shape_ids'} for area in device.get('pc_arrays',[])]
        if structure['shape_count']<=256:structure['shapes']=device.get('shapes',[])
        else:structure['shape_records_note']='All actual shape records remain in the saved project.json; this text view summarizes the generated array.'
        self.inputs.setPlainText(json.dumps(dict(settings=self.saved_project.get('settings',{}),device=structure,
            complete_saved_project=str(self.directory/'project.json')),indent=2,ensure_ascii=False,default=str))
        self.sources.setPlainText(json.dumps(dict(saved_electrical_material_definitions=self.saved_project.get('electrical_materials',[]),
            saved_optical_materials=self.saved_project.get('materials',[]),
            scope='Saved material definitions. This optical-only result has no evaluated electrical material state.'),
            indent=2,ensure_ascii=False,default=str))

    def _bias_changed(self,*args):
        previous=tuple(self.cursor_controls[key].value()*1e-6 for key in ('x','y','z')) if self.volume is not None else None
        super()._bias_changed(*args)
        if self._workspace_ready:
            if previous is not None and self.volume is not None:self.set_probe(*previous)
            self._refresh_workspace();self._draw_charts();self._draw_band_edges()

    def redraw(self,*args):
        super().redraw(*args)
        if not self._workspace_ready:return
        if self.volume is None or self.quantity.currentData() not in self.volume:
            self.field_scene.clear('Optical-only result · no saved electrical fields')
            device=self.saved_project.get('device')
            if not device and self.saved_project.get('layers'):
                try:
                    from device_model import from_optical_project
                    device=from_optical_project(self.saved_project)
                except ValueError:device=None
            if device:self.geometry_scene.set_device(device);self.scene_stack.setCurrentIndex(1)
            else:self.scene_stack.setCurrentIndex(0)
            return
        self.scene_stack.setCurrentIndex(0)
        key=self.quantity.currentData();values=np.asarray(self.volume[key]);label,unit=_QUANTITY_INFO[key]
        ix,iy,iz=self.cursor_indices;x,y,z=[self.volume[axis] for axis in ('x','y','z')]
        self._colors.cmap=colormaps['turbo'] if not (self._colors.low<0<self._colors.high) else colormaps['coolwarm']
        palette=self._colors.cmap(np.linspace(0,1,256));self._colors.palette=[QColor(round(r*255),round(g*255),round(b*255)) for r,g,b,_ in palette]
        device=self.summary.get('device') or self.summary.get('options',{}).get('device') or self.saved_project.get('device',{})
        self.field_scene.set_field(device,self.volume,values,self._colors,(x[ix],y[iy],z[iz]),label,unit)
        top_key='potential' if self._active_category in ('Overview','Potential & fields') and 'potential' in self.volume else key
        top_values=self.volume[top_key];top_label,top_unit=_QUANTITY_INFO[top_key]
        top_colors=_FieldColors(top_values,False);self.top_view.device=device;self.top_view.plane_coordinate=z[iz];self.top_view.unit=top_unit
        self.top_view.set_field(x,y,top_values[:,:,iz],top_colors,(x[ix],y[iy]),top_label)
        self.hero_top.device=device;self.hero_top.plane_coordinate=z[iz];self.hero_top.unit=top_unit
        self.hero_top.set_field(x,y,top_values[:,:,iz],top_colors,(x[ix],y[iy]),top_label)
        self.top_card.title_label.setText(f'{top_label} · XY (z = {z[iz]*1e6:.3g} µm)')
        self.cross_view.device=device;self.cross_view.plane_coordinate=y[iy];self.cross_view.unit=unit
        self.hero_cross.device=device;self.hero_cross.plane_coordinate=y[iy];self.hero_cross.unit=unit
        self.hero_cross.set_field(x,z,values[:,iy,:],self._colors,(x[ix],z[iz]),label)
        self.cross_card.title_label.setText(f'{label} · XZ (y = {y[iy]*1e6:.3g} µm)')
        for axis in ('x','y','z'):
            slider=self.cursor_sliders[axis]
            with QSignalBlocker(slider):slider.setRange(0,len(self.volume[axis])-1);slider.setValue(self.cursor_indices[('x','y','z').index(axis)])
        self._draw_charts();self._draw_band_edges()

    def _clear_views(self,message):
        super()._clear_views(message)
        if self._workspace_ready:
            self.field_scene.clear(message);self.hero_top.clear(message);self.hero_cross.clear(message);self._refresh_workspace()

    def _slide_cursor(self,key,index):
        if self.volume is not None:self.cursor_controls[key].setValue(float(self.volume[key][index])*1e6)

    def _probe_updated(self,probe):
        if not self._workspace_ready:return
        for key,value in zip(('x','y','z'),probe.get('coordinates_m',[])):self.probe_values[key].setText(f'{value*1e6:.5g}')
        for key,label in self.probe_values.items():
            if key not in ('x','y','z'):label.setText(_text(probe.get('values',{}).get(key),'—'))
        self.probe_identity.setText('Nearest grid sample '+str(probe.get('indices',''))+'\n'+' · '.join(str(probe[key]) for key in ('layer_id','material_id','contact_id') if key in probe))

    def _refresh_workspace(self):
        if not self._workspace_ready:return
        bias=self.selected_bias();values=self.volume or {}
        self.metric_values['bias'].setText(f'{bias:g} V' if bias is not None else '—')
        for key,quantity,factor,suffix in [('field','field_magnitude_V_m',1e-6,' MV/m'),('electrons','electrons_cm3',1.,''),('holes','holes_cm3',1.,'')]:
            array=values.get(quantity)
            self.metric_values[key].setText(f'{float(np.max(array))*factor:.3g}{suffix}'+(' cm⁻³' if key in ('electrons','holes') else '') if array is not None else '—')
            self.metric_values[key].setToolTip('cm⁻³' if key in ('electrons','holes') else 'Peak magnitude from the actual saved field array.')
        shift=None
        if not self.feature_data.empty and {'bias_V','shift_nm'}<=set(self.feature_data):
            frame=self.feature_data[np.isclose(pd.to_numeric(self.feature_data['bias_V'],errors='coerce'),bias if bias is not None else 0.)]
            if not frame.empty:
                series=pd.to_numeric(frame['shift_nm'],errors='coerce').dropna();shift=float(series.iloc[0]) if not series.empty else None
        self.metric_values['shift'].setText(f'{shift:+.3g} nm' if shift is not None else '—')
        self.metric_values['shift'].setToolTip('Shift of the tracked sampled optical peak/dip; unavailable when no baseline feature was resolved.')
        self.result_bias.setEnabled(bool(self._result_rows))
        self.scale_choice.setEnabled(self.volume is not None)
        self.quantity.setEnabled(self.volume is not None)
        for control in [*self.cursor_controls.values(),*self.cursor_sliders.values()]:control.setEnabled(self.volume is not None)
        if self.volume is None:
            for label in self.probe_values.values():label.setText('—')
            self.probe_identity.setText('Electrical field probe unavailable')
        model=self.summary.get('model','electrical')
        labels=saved_result_model_labels(self.summary,self.study_info,self.iv_data,self.cv_data,has_optical_fields=self.has_optical_fields)
        self.run_value_labels['model'].setText(labels['run_model'])
        self.summary_label.setText(self._summary_text(labels['run_model']))
        for kind,title in (('iv','I–V'),('cv','C–V')):
            self.terminal_cards[kind].title_label.setText(title+' · '+labels[kind+'_scope'])
        self.run_value_labels['biases'].setText(', '.join(f'{float(row["bias_V"]):g}' for row in self._result_rows)+' V' if self._result_rows else 'No electrical bias states')
        cells=self.summary.get('mesh',{}).get('cells')
        if cells is None and self.volume is not None:cells=int(np.prod([len(self.volume[key]) for key in ('x','y','z')]))
        self.run_value_labels['mesh'].setText(f'{cells:,}' if isinstance(cells,int) else 'Unavailable')
        elapsed=self.summary.get('elapsed_s');self.run_value_labels['elapsed'].setText(f'{elapsed:.3g} s' if isinstance(elapsed,(int,float)) else 'Unavailable')
        row=next((row for row in self._result_rows if bias is not None and math.isclose(float(row['bias_V']),bias,abs_tol=1e-12)),{})
        checks=row.get('checks',{});residual=checks.get('max_normalized_Poisson_residual',checks.get('poisson_residual'))
        gauss=checks.get('relative_gauss_balance')
        self.check_labels['residual'].setText(_text(residual));self.check_labels['gauss'].setText(_text(gauss));self.check_labels['refinement'].setText('Not yet verified')
        converged=isinstance(residual,(int,float)) and residual<1e-7;balanced=isinstance(gauss,(int,float)) and gauss<1e-6
        self.convergence_badge.setText('✓  Converged' if converged else 'Convergence unavailable' if residual is None else 'Check residual')
        self.balance_badge.setText('✓  Charge balanced' if balanced else 'Balance unavailable' if gauss is None else 'Check balance')
        for badge,value,passed in ((self.convergence_badge,residual,converged),(self.balance_badge,gauss,balanced)):
            background,border=('#12372f','#216347') if passed else ('#12283a','#31546b') if value is None else ('#3e2a14','#856039')
            badge.setStyleSheet(f'background:{background};border:1px solid {border};border-radius:4px;padding:6px;font-size:10px;')
        geometry=self.summary.get('device') or self.summary.get('options',{}).get('device') or self.saved_project.get('device',{})
        self.detail_expanders['boundary'].setPlainText(json.dumps(dict(contacts=geometry.get('contacts',[]),
            contact_scope='Saved device ideal electrical contacts; optical metal inclusion is controlled by the saved contact optics.',
            terminal_voltages=checks.get('terminal_voltages_V',{})),indent=2))
        self.detail_expanders['sources'].setPlainText(self.sources.toPlainText());self.detail_expanders['assumptions'].setPlainText('\n'.join(self.summary.get('limitations',[])))
        self.current_scope.setText('Current / I–V: '+labels['iv_scope'])
        selection=self._saved_optical_cell or self.summary.get('optical_unit_cell',{}).get('selection') or self.saved_project.get('settings',{}).get('optical_unit_cell',{})
        if self.optical_data.empty:optical_scope='Electrical fields only'
        elif selection.get('enabled'):
            optical_scope=f"S4 · selected periodic cell {selection['width_um']:g} × {selection['depth_um']:g} µm"
        elif selection:optical_scope='S4 · device-footprint periodic supercell'
        else:optical_scope='S4 · periodic model (saved cell metadata unavailable)'
        self.optical_scope.setText('Optical model: '+optical_scope)
        device=self.summary.get('device',{});name=device.get('name') or self.summary.get('title') or (self.directory.name[:16] if self.directory else 'No saved run')
        self.footer_label.setText('ⓘ  '+name+' · saved result\nGeometry, materials and inputs are retained with this run.')
        self.info_label.setText('ⓘ  '+('Saved optical spectra · electrical field quantities unavailable.' if model=='optical_only' else 'Computed saved fields · nearest-grid probe · meshes and optical sampling require convergence checks.'))
        if self.has_optical_fields and model=='optical_only':self.info_label.setText('ⓘ  Saved optical E/H phasors · source-normalized amplitudes; static electrical fields unavailable.')
        shape_count=sum(bool(obj.get('enabled',True)) for obj in geometry.get('shapes',[]))
        if shape_count>256:
            self.info_label.setText(self.info_label.text()+f'  Geometry display LOD · all {shape_count:,} actual shapes retained.')
        for title,button in self.workspace_export_buttons.items():button.setEnabled(self.directory is not None and (self.volume is not None or title=='Export CSV / NPZ' and (self.has_optical_fields or self.has_specular_phase or not self.optical_data.empty or not self.iv_data.empty or not self.cv_data.empty) or title not in ('Export CSV / NPZ','Export VTK')))

    def select_category(self,name):
        self._active_category=name
        for key,button in self.nav_buttons.items():button.setChecked(key==name)
        for card in self.metric_cards:card.setVisible(name not in ('Optical E/H','Specular phase'))
        if name in self.nav_buttons and hasattr(self,'category_scroll'):self.category_scroll.ensureWidgetVisible(self.nav_buttons[name])
        pages={'Overview':0,'Potential & fields':0,'Carriers & charge':0,'Energy bands':1,'Optical response':2,'I–V / C–V':3,'Mesh & convergence':4,'Inputs & materials':5,'Raw data & exports':6,
            'Optical E/H':7,'Specular phase':8}
        self.center_stack.setCurrentIndex(pages.get(name,0))
        if name in ('Potential & fields','Carriers & charge'):
            key='potential' if name=='Potential & fields' else 'electrons_cm3'
            index=self.quantity.findData(key)
            if self.volume is not None and key in self.volume:self.quantity.setCurrentIndex(index)
        self.redraw()

    def focus_view(self,title):
        for key,button in self.mode_buttons.items():button.setChecked(key==title)
        modes={'3D fields':0,'Top view · XY':1,'Cross section · XZ':2,'Depth profiles':3,'Optical spectra':4}
        self.hero_stack.setCurrentIndex(modes.get(title,0));self.center_stack.setCurrentIndex(0)
        if title=='3D fields':self.field_scene.fit()

    def _draw_charts(self,*_):
        if not self._workspace_ready:return
        ix,iy,_=self.cursor_indices
        depth_signature=(id(self.volume),ix,iy,self.selected_bias(),self.compare_zero.isChecked())
        if depth_signature!=getattr(self,'_depth_signature',None):
            self._depth_signature=depth_signature
            figure=self.depth_figure();self.depth_plot.draw_figure(figure);self.hero_depth.draw_figure(figure)
            self.depth_legend.set_lines(figure);_hide_native_legend(self.depth_plot)
        optical_signature=(id(self.optical_data),self.selected_bias(),self.compare_zero.isChecked())
        if optical_signature!=getattr(self,'_optical_signature',None):
            self._optical_signature=optical_signature
            figure=self.optical_figure();self.rta_plot.draw_figure(figure);self.optical_plot.draw_figure(figure);self.hero_optical.draw_figure(figure)
            self.rta_legend.set_lines(figure);_hide_native_legend(self.rta_plot)

    def depth_figure(self):
        figure=Figure(figsize=(5,2.3));axis=figure.add_subplot(111);figure.subplots_adjust(left=.13,right=.85,bottom=.17,top=.96)
        if self.volume is None or not {'electrons_cm3','holes_cm3'}<=set(self.volume):
            axis.text(.5,.5,'No saved carrier volume',ha='center',va='center',transform=axis.transAxes);axis.set_axis_off();return figure
        ix,iy,_=self.cursor_indices;z=self.volume['z']*1e9
        for key,label,color in [('electrons_cm3','Electrons','#36bfff'),('holes_cm3','Holes','#f06887')]:
            values=self.volume[key][ix,iy,:];axis.plot(z,np.where(values>0,values,np.nan),color=color,label=label)
        axis.set_yscale('log');axis.set_ylabel('Carriers (cm⁻³)');axis.set_xlabel('Depth (nm)');axis.grid(alpha=.22)
        if 'potential' in self.volume:
            second=axis.twinx();second.plot(z,self.volume['potential'][ix,iy,:],color='#f2f5ff',linestyle=':',label='Potential');second.set_ylabel('Potential (V)')
        if self.compare_zero.isChecked():
            baseline=self._baseline()
            if baseline is not None:
                for key,color,label in [('electrons_cm3','#36bfff','Electrons (0 V)'),('holes_cm3','#f06887','Holes (0 V)')]:
                    if key in baseline:axis.plot(baseline['z']*1e9,np.where(baseline[key][ix,iy,:]>0,baseline[key][ix,iy,:],np.nan),'--',color=color,label=label)
                if 'potential' in baseline and 'potential' in self.volume:
                    second.plot(baseline['z']*1e9,baseline['potential'][ix,iy,:],color='#bacadb',linestyle='--',label='Potential (0 V)')
        axis.legend(loc='lower right',fontsize=6.,framealpha=.12,ncol=2)
        return figure

    def _baseline(self):
        if self._reference_volume is not None:return self._reference_volume
        row=next((row for row in self._result_rows if abs(float(row['bias_V']))<1e-12),None)
        path=saved_result_path(self.directory,row.get('volume_npz')) if row else None
        if path:
            from qt_electrical_results import load_electrical_volume
            candidate,_=load_electrical_volume(path)
            if self.volume is not None and all(np.array_equal(candidate[key],self.volume[key]) for key in ('x','y','z')):self._reference_volume=candidate
        return self._reference_volume

    def optical_figure(self):
        figure=Figure(figsize=(5,2.3));axis=figure.add_subplot(111);figure.subplots_adjust(left=.11,right=.96,bottom=.17,top=.96)
        frame=self.optical_data
        wave='wavelength_nm' if 'wavelength_nm' in frame else 'wavelength'
        if frame.empty or wave not in frame or not {'R','T','A'}<=set(frame):
            axis.text(.5,.5,'No saved optical spectra',ha='center',va='center',transform=axis.transAxes);axis.set_axis_off();return figure
        bias=self.selected_bias();groups=[(bias,frame)]
        if 'bias_V' in frame and bias is not None:
            groups=[(bias,frame[np.isclose(pd.to_numeric(frame['bias_V'],errors='coerce'),bias)])]
            if self.compare_zero.isChecked() and abs(bias)>1e-12:groups.append((0.,frame[np.isclose(pd.to_numeric(frame['bias_V'],errors='coerce'),0.)]))
        for state,values in groups:
            values=values.sort_values(wave)
            for key,color in [('R','#39baf9'),('T','#51dd8d'),('A','#f67d78')]:
                axis.plot(pd.to_numeric(values[wave],errors='coerce'),pd.to_numeric(values[key],errors='coerce'),'-' if state==bias else '--',color=color,label=key+(f' ({state:g} V)' if state is not None else ''))
        axis.set_xlabel('Wavelength (nm)');axis.set_ylabel('R / T / A');axis.set_ylim(0,1.03);axis.grid(alpha=.22);axis.legend(fontsize=6.5,loc='best',framealpha=.2)
        return figure

    def _draw_band_edges(self):
        if not self._workspace_ready:return
        ix,iy,_=self.cursor_indices
        signature=(id(self.volume),ix,iy,self.selected_bias())
        if signature==getattr(self,'_band_signature',None):return
        self._band_signature=signature
        figure=Figure(figsize=(7,4),layout='constrained');axis=figure.add_subplot(111)
        data=self.volume;materials={row['id']:row for row in self.summary.get('evaluated_materials',[])}
        if data is not None and {'material_index','material_ids','potential'}<=set(data) and materials:
            ix,iy,_=self.cursor_indices;indices=data['material_index'][ix,iy,:]
            affinity=np.array([materials.get(str(data['material_ids'][int(index)]),{}).get('properties',{}).get('affinity_eV',np.nan) for index in indices])
            gap=np.array([materials.get(str(data['material_ids'][int(index)]),{}).get('properties',{}).get('bandgap_eV',np.nan) for index in indices])
            ec=-affinity-data['potential'][ix,iy,:]
            axis.plot(data['z']*1e9,ec,label='Ec = −χ − φ');axis.plot(data['z']*1e9,ec-gap,label='Ev = Ec − Eg');axis.legend()
            axis.set_xlabel('Depth (nm)');axis.set_ylabel('Vacuum-reference band edge (eV)');axis.grid(alpha=.2)
        else:axis.text(.5,.5,'Saved band-alignment inputs are unavailable.',ha='center',va='center',transform=axis.transAxes);axis.set_axis_off()
        self.energy_plot.draw_figure(figure)

    def _populate_files(self):
        self.raw_files.clear()
        if self.directory:
            for path in sorted(self.directory.rglob('*')):
                if path.is_file():
                    item=QListWidgetItem(str(path.relative_to(self.directory)));item.setData(Qt.ItemDataRole.UserRole,str(path));self.raw_files.addItem(item)

    def _open_saved_file(self,item):
        QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole)))

    def open_run_folder(self):
        if self.directory:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory)))

    def _export_data_menu(self):
        page=self.center_stack.currentIndex()
        if page==8:self.phase_panel.export_csv();return
        menu=QMenu(self);actions={}
        if page==7:
            actions[menu.addAction('Complete selected optical E/H sample CSV')]=self.optical_fields_panel.export_csv
            actions[menu.addAction('Original selected optical E/H arrays NPZ')]=self.optical_fields_panel.export_npz
        else:
            if self.volume is not None:
                actions[menu.addAction('Complete saved electrical grid CSV')]=lambda:self.export_dialog('csv')
                actions[menu.addAction('Original saved electrical volume NPZ')]=lambda:self.export_dialog('npz')
            for label,name,frame in [('Optical spectra CSV','optical-spectra',self.optical_data),
                    ('I–V CSV','electrical-iv',self.iv_data),('C–V CSV','electrical-cv',self.cv_data)]:
                if not frame.empty:
                    actions[menu.addAction(label)]=lambda frame=frame,name=name:self._export_frame_csv(frame,name)
        picked=menu.exec(self.workspace_export_buttons['Export CSV / NPZ'].mapToGlobal(self.workspace_export_buttons['Export CSV / NPZ'].rect().bottomLeft()))
        if picked in actions:actions[picked]()

    def _export_frame_csv(self,frame,name):
        from PyQt6.QtWidgets import QFileDialog
        path,_=QFileDialog.getSaveFileName(self,'Export complete saved data',name+'.csv','CSV (*.csv)')
        if path:
            try:
                frame.to_csv(path,index=False);self.footer_label.setText('Saved complete data: '+path)
            except OSError as exc:self.footer_label.setText('Data export failed: '+str(exc))

    def export_visible_figure(self):
        page=self.center_stack.currentIndex()
        if page==1:self.energy_plot.export_dialog()
        elif page==2:self.optical_plot.export_dialog()
        elif page==3:self.iv_plot.export_dialog()
        elif page==7:
            panel=self.optical_fields_panel
            (panel.volume.plot if panel.tabs.currentIndex()==1 else panel.plot).export_dialog()
        elif page==8:self.phase_panel.plot.export_dialog()
        else:self.export_dialog('figure')

    def export_file(self,path,kind='npz'):
        if kind!='figure' or not self._workspace_ready:return super().export_file(path,kind)
        page=self.center_stack.currentIndex()
        if page==1:figure=self.energy_plot.figure
        elif page==2:figure=self.optical_plot.figure
        elif page==3:figure=self.iv_plot.figure
        elif page==7:
            panel=self.optical_fields_panel
            figure=panel.volume.publication_figure() if panel.tabs.currentIndex()==1 and panel.volume.data is not None else panel.plot.figure
        elif page==8:figure=self.phase_panel.plot.figure
        elif self.hero_stack.currentIndex()==3:figure=self.depth_plot.figure
        elif self.hero_stack.currentIndex()==4:figure=self.rta_plot.figure
        else:figure=self.field_figure()
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        figure.savefig(path,dpi=200,bbox_inches='tight');self.footer_label.setText('Saved figure: '+str(path));return Path(path)

    def export_dialog(self,kind):
        self.status.clear()
        super().export_dialog(kind)
        if self.status.text():self.footer_label.setText(self.status.text())

    def export_report(self):
        from PyQt6.QtWidgets import QFileDialog
        path,_=QFileDialog.getSaveFileName(self,'Export saved result report','simulation-report.txt','Text report (*.txt)')
        if path:
            report='Optical Design Studio — saved simulation result\n\n'+json.dumps(dict(directory=str(self.directory),summary=self.summary,
                selected_bias_V=self.selected_bias(),probe=self.probe),indent=2,ensure_ascii=False,default=str)
            try:
                Path(path).write_text(report+'\n',encoding='utf-8');self.footer_label.setText('Saved report: '+path)
            except OSError as exc:self.footer_label.setText('Report export failed: '+str(exc))
