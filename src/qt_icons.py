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
        for y in (5, 10, 15):
            p.drawPolyline(QPolygonF([QPointF(3, y+3), QPointF(12, y-1),
                                     QPointF(21, y+3), QPointF(12, y+7), QPointF(3, y+3)]))
    elif name == 'Materials':
        for x, y in ((7, 7), (17, 7), (12, 17)):
            p.drawEllipse(QPointF(x, y), 3, 3)
        line(10, 7, 14, 7)
        line(8.5, 10, 10.5, 14)
        line(15.5, 10, 13.5, 14)
    elif name == 'Simulate':
        p.drawPolygon(QPolygonF([QPointF(7, 4), QPointF(20, 12), QPointF(7, 20)]))
    elif name == 'Optimize':
        for x, y in ((5, 9), (12, 16), (19, 7)):
            line(x, 3, x, y-2)
            line(x, y+2, x, 21)
            p.drawEllipse(QPointF(x, y), 2, 2)
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
    elif name == 'About':
        p.drawEllipse(QRectF(3, 3, 18, 18))
        line(12, 11, 12, 17)
        line(12, 7, 12, 7.2)
    p.end()
    return QIcon(pixmap)
