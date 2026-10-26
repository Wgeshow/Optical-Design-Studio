"""Vector details and dimensions from the approved dark workspace references."""
import math
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
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
