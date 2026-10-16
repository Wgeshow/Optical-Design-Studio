"""Compact native lattice diagram of the selected, applied layer geometry."""
import math
from PyQt6.QtCore import Qt,QPointF,QRectF,QSize
from PyQt6.QtGui import QColor,QFont,QPainter,QPainterPath,QPen,QPolygonF,QLinearGradient,QTransform
from PyQt6.QtWidgets import QWidget,QSizePolicy
from model import PAT_COLS
from structure_builder import rows
from structure_preview import normalize_region,region_extents
from qt_common import COLORS,theme_manager


def region_path(region,center):
    """Use S4 radii for circles/ellipses and full widths for rectangles."""
    sx,sy=region['sx'],region['sy']
    path=QPainterPath()
    if region['shape']=='rectangle':path.addRect(QRectF(-sx/2,-sy/2,sx,sy))
    else:path.addEllipse(QRectF(-sx,-sy,2*sx,2*sy))
    transform=QTransform();transform.translate(*center)
    if region['shape']!='circle':transform.rotate(region['angle'])
    return transform.map(path)


class LatticeDiagram(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName('patternGeometryPreview')
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(180);self.setFixedHeight(178)
        self.selected='';self.patterns=[];self.copies=[];self.dimensions=[]
        self.ax=self.ay=None;self.error='';self.bounds=None
        self.setAccessibleName('Applied lattice pattern diagram')
        theme_manager().changed.connect(self.update)

    def sizeHint(self):return QSize(244,178)

    def set_model(self,store,selected,cells=1):
        # The inspector always shows three periods in each direction. The cells
        # argument remains compatible with the former unit-cell preview hook.
        self.selected=str(selected or '')
        self.patterns=[];self.copies=[];self.dimensions=[];self.bounds=None;self.error=''
        try:
            self.ax=float(store.settings['ax_um']);self.ay=float(store.settings['ay_um'])
            if not all(math.isfinite(v) and v>0 for v in (self.ax,self.ay)):
                raise ValueError('Apply valid lattice periods.')
            self.patterns=[normalize_region(r) for r in rows(store.patterns,PAT_COLS)
                if str(r.get('Layer',''))==self.selected]
            for region in self.patterns:
                cx=(region['cx']+self.ax/2)%self.ax-self.ax/2
                cy=(region['cy']+self.ay/2)%self.ay-self.ay/2
                for j in (-1,0,1):
                    for i in (-1,0,1):
                        self.copies.append((region,(cx+i*self.ax,cy+j*self.ay)))
            if self.copies:
                extents=[(center,region_extents(region)) for region,center in self.copies]
                self.bounds=(min(c[0]-e[0] for c,e in extents),max(c[0]+e[0] for c,e in extents),
                    min(c[1]-e[1] for c,e in extents),max(c[1]+e[1] for c,e in extents))
                region=self.patterns[0]
                width=region['sx'] if region['shape']=='rectangle' else 2*region['sx']
                label={'circle':'2r','ellipse':'2rₓ','rectangle':'wₓ'}[region['shape']]
                rectangular=not math.isclose(self.ax,self.ay,rel_tol=1e-9)
                self.dimensions=[dict(label=label,value_um=width),
                    dict(label='2aₓ' if rectangular else '2a',value_um=2*self.ax)]
                if rectangular:self.dimensions.append(dict(label='aᵧ',value_um=self.ay))
        except (ValueError,KeyError,TypeError) as exc:
            self.error=str(exc);self.patterns=[];self.copies=[];self.dimensions=[]
        description=(f'{self.selected}: lattice {self.ax:g} × {self.ay:g} µm' if self.ax and self.ay else self.selected)
        if self.dimensions:description+='; '+', '.join(f"{d['label']} = {d['value_um']:g} µm" for d in self.dimensions)
        else:description+='; '+(self.error or 'No applied pattern')
        self.setToolTip(description);self.setAccessibleDescription(description);self.update()

    def _mapping(self):
        rectangular=self.ax and self.ay and not math.isclose(self.ax,self.ay,rel_tol=1e-9)
        plot=QRectF(39 if rectangular else 20,33,self.width()-(61 if rectangular else 40),self.height()-65)
        xmin,xmax,ymin,ymax=self.bounds
        scale=min(plot.width()/(xmax-xmin),plot.height()/(ymax-ymin))
        tx=plot.center().x()-scale*(xmin+xmax)/2
        ty=plot.center().y()+scale*(ymin+ymax)/2
        return QTransform(scale,0,0,-scale,tx,ty),scale

    @staticmethod
    def _arrow(painter,start,end,label,color,label_offset=QPointF(0,-10)):
        delta=end-start;length=math.hypot(delta.x(),delta.y())
        if length<1:return
        direction=delta/length;normal=QPointF(-direction.y(),direction.x())
        painter.setPen(QPen(color,1.15));painter.setBrush(color);painter.drawLine(start,end)
        for tip,inward in ((start,direction),(end,-direction)):
            painter.drawPolygon(QPolygonF([tip,tip+inward*4+normal*2.3,tip+inward*4-normal*2.3]))
        middle=(start+end)/2+label_offset
        painter.drawText(QRectF(middle.x()-26,middle.y()-7,52,15),Qt.AlignmentFlag.AlignCenter,label)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors=COLORS[theme_manager().mode];dark=theme_manager().mode=='dark'
        frame=QRectF(1.5,1.5,self.width()-3,self.height()-3)
        background=QColor(colors['field']);background.setAlpha(160 if theme_manager().style=='glass' else 255)
        painter.setPen(QPen(QColor(colors['border']),1));painter.setBrush(background)
        painter.drawRoundedRect(frame,7,7)
        if not self.copies:
            painter.setPen(QColor(colors['muted']));painter.setFont(QFont('Segoe UI',9))
            painter.drawText(frame,Qt.AlignmentFlag.AlignCenter,'Apply lattice' if self.error else 'No pattern')
            return
        clip=QPainterPath();clip.addRoundedRect(frame.adjusted(2,2,-2,-2),5,5);painter.setClipPath(clip)
        transform,scale=self._mapping()
        first=self.patterns[0]
        cx=(first['cx']+self.ax/2)%self.ax-self.ax/2
        cy=(first['cy']+self.ay/2)%self.ay-self.ay/2
        links=QColor(colors['muted']);links.setAlpha(165)
        painter.setPen(QPen(links,.9,Qt.PenStyle.DashLine))
        for index in (-1,0,1):
            painter.drawLine(transform.map(QPointF(cx-self.ax,cy+index*self.ay)),transform.map(QPointF(cx+self.ax,cy+index*self.ay)))
            painter.drawLine(transform.map(QPointF(cx+index*self.ax,cy-self.ay)),transform.map(QPointF(cx+index*self.ax,cy+self.ay)))
        gradient=QLinearGradient(frame.topLeft(),frame.bottomRight())
        gradient.setColorAt(0,QColor('#8598ed' if dark else '#8ea1ef'))
        gradient.setColorAt(1,QColor('#5369bd' if dark else '#6079d1'))
        painter.setBrush(gradient);painter.setPen(QPen(QColor('#bdcbff' if dark else '#4b63af'),.9))
        for region,center in self.copies:painter.drawPath(transform.map(region_path(region,center)))
        painter.setFont(QFont('Segoe UI',10));ink=QColor(colors['text'])
        # Diameter/full-width dimension uses the real local x direction, including
        # rotation. Extension lines originate at the two actual diameter endpoints.
        center=transform.map(QPointF(cx,cy+self.ay))
        angle=0 if first['shape']=='circle' else math.radians(first['angle'])
        direction=QPointF(math.cos(angle),-math.sin(angle));normal=QPointF(-math.sin(angle),-math.cos(angle))
        half_x=(first['sx']/2 if first['shape']=='rectangle' else first['sx'])*scale
        half_y=(first['sy']/2 if first['shape']=='rectangle' else first['sy'])*scale
        offset=normal*(half_y+10)
        ends=[center-direction*half_x,center+direction*half_x]
        painter.setPen(QPen(ink,.8))
        for end in ends:painter.drawLine(end,end+offset+normal*3)
        self._arrow(painter,ends[0]+offset,ends[1]+offset,self.dimensions[0]['label'],ink)
        # The reference spans the two lower outer centers: this is 2a, not a.
        lower=[transform.map(QPointF(cx-self.ax,cy-self.ay)),transform.map(QPointF(cx+self.ax,cy-self.ay))]
        y=max(transform.map(QPointF(0,self.bounds[2])).y()+10,lower[0].y()+9)
        bottom=[QPointF(point.x(),y) for point in lower]
        painter.setPen(QPen(ink,.8))
        for point,end in zip(lower,bottom):painter.drawLine(point,end+QPointF(0,3))
        self._arrow(painter,*bottom,self.dimensions[1]['label'],ink,QPointF(0,11))
        if len(self.dimensions)==3:
            side=[transform.map(QPointF(cx-self.ax,cy)),transform.map(QPointF(cx-self.ax,cy+self.ay))]
            x=transform.map(QPointF(self.bounds[0],0)).x()-12
            ends=[QPointF(x,point.y()) for point in side]
            painter.setPen(QPen(ink,.8))
            for point,end in zip(side,ends):painter.drawLine(point,end+QPointF(-3,0))
            self._arrow(painter,*ends,'aᵧ',ink,QPointF(-17,0))
