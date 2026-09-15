"""Small, theme-aware vector navigation icons, rendered at high DPI."""
import math
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPolygonF


def navigation_icon(name, color):
    pixmap = QPixmap(72, 72)
    pixmap.setDevicePixelRatio(3)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    if name == 'Structure':
        p.drawPolygon(QPolygonF([QPointF(12, 2), QPointF(21, 7), QPointF(21, 17),
                                QPointF(12, 22), QPointF(3, 17), QPointF(3, 7)]))
        line(3, 7, 12, 12)
        line(21, 7, 12, 12)
        line(12, 12, 12, 22)
    elif name == 'Materials':
        p.drawEllipse(QRectF(3, 2, 18, 6))
        line(3, 5, 3, 18)
        line(21, 5, 21, 18)
        p.drawArc(QRectF(3, 9, 18, 6), 180*16, 180*16)
        p.drawArc(QRectF(3, 15, 18, 6), 180*16, 180*16)
    elif name == 'Simulate':
        p.drawPolygon(QPolygonF([QPointF(7, 4), QPointF(20, 12), QPointF(7, 20)]))
    elif name == 'Optimize':
        for x, y in ((3, 13), (10, 8), (17, 3)):
            p.drawRoundedRect(QRectF(x, y, 4, 21-y), .7, .7)
    elif name == 'Fields':
        for baseline in (7, 12, 17):
            p.drawPolyline(QPolygonF([QPointF(x, baseline + 2*math.sin((x-3)*math.pi/9))
                                      for x in range(3, 22)]))
    elif name == 'Saved work':
        p.drawPolygon(QPolygonF([QPointF(3, 6), QPointF(9, 6), QPointF(11, 9),
                                 QPointF(21, 9), QPointF(21, 20), QPointF(3, 20)]))
    elif name == 'Settings':
        p.drawEllipse(QPointF(12, 12), 6, 6)
        p.drawEllipse(QPointF(12, 12), 2, 2)
        for i in range(8):
            angle = i*math.pi/4
            line(12+6*math.cos(angle), 12+6*math.sin(angle),
                 12+9*math.cos(angle), 12+9*math.sin(angle))
    elif name == 'appearance':
        p.drawRoundedRect(QRectF(3, 4, 18, 13), 2, 2)
        line(12, 17, 12, 21)
        line(8, 21, 16, 21)
    elif name == 'storage':
        p.drawEllipse(QRectF(4, 3, 16, 6))
        line(4, 6, 4, 18)
        line(20, 6, 20, 18)
        p.drawArc(QRectF(4, 9, 16, 6), 180*16, 180*16)
        p.drawArc(QRectF(4, 15, 16, 6), 180*16, 180*16)
    elif name == 'performance':
        p.drawArc(QRectF(3, 4, 18, 18), 0, 180*16)
        line(3, 13, 3, 17)
        line(21, 13, 21, 17)
        line(12, 15, 17, 8)
        p.drawEllipse(QPointF(12, 15), 2, 2)
    elif name == 'addons':
        p.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
        for coordinate in (8, 12, 16):
            line(coordinate, 3, coordinate, 6)
            line(coordinate, 18, coordinate, 21)
            line(3, coordinate, 6, coordinate)
            line(18, coordinate, 21, coordinate)
    elif name == 'About':
        p.drawEllipse(QRectF(3, 3, 18, 18))
        line(12, 11, 12, 17)
        line(12, 7, 12, 7.2)
    p.end()
    return QIcon(pixmap)
