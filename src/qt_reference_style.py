"""Vector details and dimensions from the approved dark workspace references."""
import math
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from qt_icons import navigation_icon

REFERENCE_SIZE=(1586,992)
BUILDER_PROPORTIONS=(286,920,346)

def optical_logo(size=32):
    pixmap=QPixmap(size*3,size*3);pixmap.setDevicePixelRatio(3)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#00a4ff'),2.6))
    painter.drawEllipse(QRectF(2,2,size-4,size-4))
    painter.setPen(QPen(QColor('#00a4ff'),2.2));painter.drawEllipse(QRectF(8,8,size-16,size-16))
    painter.drawLine(QPointF(size-8,size/2),QPointF(size-1,size/2))
    painter.end();return pixmap

def reference_icon(name,color='#d4e7f7'):
    aliases={'settings':'Settings','search':'AI Search','simulation':'Simulate',
             'sweep':'Optimize','results':'Saved work','cube':'Structure'}
    if name in aliases:return navigation_icon(aliases[name],color)
    pixmap=QPixmap(72,72);pixmap.setDevicePixelRatio(3);pixmap.fill(Qt.GlobalColor.transparent)
    p=QPainter(pixmap);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(color),1.3,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    def line(a,b,c,d):p.drawLine(QPointF(a,b),QPointF(c,d))
    if name in ('structure','layers'):
        for y in (3,9,15):
            p.drawRoundedRect(QRectF(3,y,18,5),.6,.6)
            for x in (7,16):line(x,y,x,y+5)
    elif name=='materials':
        p.drawPolygon(QPolygonF([QPointF(12,2),QPointF(22,12),QPointF(12,22),QPointF(2,12)]))
        line(12,2,12,22);line(2,12,22,12)
    elif name=='help':
        p.drawEllipse(QRectF(3,3,18,18));p.drawArc(QRectF(8,6,8,7),0,180*16)
        line(16,9,12,13);line(12,13,12,15);line(12,18,12,18.2)
    elif name=='save':
        p.drawRoundedRect(QRectF(3,3,18,18),1,1);p.drawRect(QRectF(7,3,10,7));p.drawRect(QRectF(7,14,10,7));line(14,4,14,8)
    elif name=='check':line(4,12,9,17);line(9,17,20,5)
    elif name=='play':p.drawPolygon(QPolygonF([QPointF(7,4),QPointF(20,12),QPointF(7,20)]))
    elif name=='plus':line(4,12,20,12);line(12,4,12,20)
    elif name in ('delete','remove'):
        line(5,6,19,6);line(9,3,15,3);line(9,3,9,6);line(15,3,15,6)
        p.drawRoundedRect(QRectF(6,6,12,15),1.2,1.2)
        line(10,10,10,17);line(14,10,14,17)
    elif name in ('up','down'):
        y1,y2=(19,5) if name=='up' else (5,19)
        line(12,y1,12,y2);line(7,10 if name=='up' else 14,12,y2);line(17,10 if name=='up' else 14,12,y2)
    elif name in ('back','next'):
        tip,tail=(6,17) if name=='back' else (18,7)
        line(tail,12,tip,12);line(12,6,tip,12);line(12,18,tip,12)
    elif name=='reset':
        p.drawArc(QRectF(4,4,16,16),25*16,295*16)
        line(20,3,20,9);line(14,9,20,9)
    elif name in ('spectrum','field','bands'):
        line(3,20,22,20);line(3,20,3,3)
        for branch in range(3 if name=='bands' else 1):
            curve=QPainterPath()
            for i in range(80):
                x=i/79
                y=(6+branch*5+2*math.cos(x*math.pi*2)) if name=='bands' else 12-6*math.sin(x*math.pi*4)*math.exp(-((x-.5)*2)**2)
                point=QPointF(4+17*x,y)
                curve.moveTo(point) if i==0 else curve.lineTo(point)
            p.drawPath(curve)
    elif name=='thermal':
        p.drawEllipse(QRectF(9,15,6,6));p.drawRoundedRect(QRectF(10,3,4,14),2,2)
        line(12,9,12,18);line(17,6,21,6);line(17,10,20,10)
    elif name=='transport':
        line(3,12,7,12);line(17,12,21,12);line(7,5,7,19);line(17,5,17,19)
        line(10,12,15,12);line(12,9,15,12);line(12,15,15,12)
    elif name=='pattern':
        p.drawRect(QRectF(3,3,18,18))
        for x in (7,12,17):
            for y in (7,12,17):p.drawEllipse(QPointF(x,y),1.5,1.5)
    elif name=='paper':
        p.drawRoundedRect(QRectF(5,2,14,20),1,1)
        for y in (7,11,15,18):line(8,y,16,y)
    elif name=='mesh':
        p.drawRect(QRectF(3,3,18,18))
        for v in (7.5,12,16.5):line(v,3,v,21);line(3,v,21,v)
    elif name=='info':
        p.drawEllipse(QRectF(3,3,18,18));line(12,11,12,18);line(12,7,12,7.2)
    elif name=='export':
        line(4,14,4,21);line(4,21,20,21);line(20,21,20,14)
        line(12,2,12,16);line(8,7,12,2);line(12,2,16,7)
    elif name=='more':
        for x in (5,12,19):p.drawEllipse(QPointF(x,12),.8,.8)
    else:
        p.end();return navigation_icon(name,color)
    p.end();return QIcon(pixmap)
