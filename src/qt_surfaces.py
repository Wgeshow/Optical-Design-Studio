"""Translucent native panels above the Windows desktop glass backdrop."""
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QLinearGradient, QImage, QBrush
from PyQt6.QtWidgets import QFrame, QWidget
from functools import lru_cache
from qt_common import theme_manager, COLORS, blend_color, clamp_alpha


def paint_workspace_glass(painter, rectangle):
    """Solid unsupported/offscreen fallback; no simulated wallpaper is painted."""
    c=COLORS[theme_manager().mode]
    painter.fillRect(rectangle,QColor(c['bg']))


@lru_cache(maxsize=8)
def frost_texture(mode, text_color, alpha):
    """Small stationary grain tile: one texture fill instead of thousands of calls."""
    tile=QImage(35,35,QImage.Format.Format_ARGB32_Premultiplied)
    tile.fill(Qt.GlobalColor.transparent)
    painter=QPainter(tile)
    grain=QColor(text_color);grain.setAlpha(clamp_alpha(alpha))
    painter.setPen(QPen(grain,.6))
    for y in range(3,35,5):
        for x in range(3,35,5):
            offset=((x*73+y*37)%7)/3
            painter.drawPoint(QPointF(x+offset,y-offset))
    painter.end()
    return tile


class WorkspacePanel(QFrame):
    """One translucent neutral surface, with crisp controls painted above it."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName('builderPanel')
        theme_manager().changed.connect(self.update)

    def paintEvent(self,event):
        super().paintEvent(event)
        manager=theme_manager()
        c=COLORS[manager.mode]
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rectangle=QRectF(self.rect()).adjusted(.7,.7,-.7,-.7)
        gradient=QLinearGradient(rectangle.topLeft(),rectangle.bottomRight())
        glass=manager.style=='glass'
        upper=QColor(c['panel'] if glass else blend_color(c['panel'],c['text'],.015));upper.setAlpha(clamp_alpha(manager.glass_opacity*2.55) if glass else 255)
        lower=QColor(c['panel']);lower.setAlpha(upper.alpha())
        gradient.setColorAt(0,upper);gradient.setColorAt(1,lower)
        edge=QColor(c['border']);edge.setAlpha(55 if glass else 255)
        painter.setBrush(gradient);painter.setPen(QPen(edge,1))
        radius=10 if glass else 4
        painter.drawRoundedRect(rectangle,radius,radius)
        if glass:
            # Edge light gives the clear surface depth without a second tint
            # layer or grain obscuring the underlying desktop.
            from PyQt6.QtGui import QPainterPath
            clip=QPainterPath();clip.addRoundedRect(rectangle,10,10)
            painter.save();painter.setClipPath(clip)
            sheen=QLinearGradient(rectangle.topLeft(),rectangle.bottomLeft())
            detail_scale=min(1,manager.glass_opacity/65)
            white=QColor('#ffffff');white.setAlpha(clamp_alpha(8*detail_scale))
            sheen.setColorAt(0,white);white.setAlpha(0);sheen.setColorAt(.55,white)
            painter.fillRect(rectangle,sheen)
            painter.restore()
        highlight=QColor('#ffffff' if glass else c['text']);highlight.setAlpha(40 if glass else 12)
        painter.setBrush(QColor(0,0,0,0));painter.setPen(QPen(highlight,.7))
        painter.drawRoundedRect(rectangle.adjusted(1,1,-1,-1),max(2,radius-1),max(2,radius-1))
        painter.end()


class WorkspaceBackground(QWidget):
    """Clear native root; nested glass workspaces remain transparent."""
    def __init__(self,parent=None, *, desktop_root=False):
        super().__init__(parent)
        self.desktop_root=desktop_root
        self.setAutoFillBackground(False)
        theme_manager().changed.connect(self.update)

    def paintEvent(self,event):
        painter=QPainter(self)
        if theme_manager().style=='glass':
            if self.desktop_root:
                adapter=getattr(self.window(),'_desktop_glass',None)
                if adapter is not None and (adapter.active or getattr(adapter, 'alpha_active', False)):
                    # A previous opaque B/fallback frame can remain in Qt's
                    # raster buffer. Replace its alpha instead of tinting over
                    # old pixels when switching into desktop glass.
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    tint=QColor(COLORS[theme_manager().mode]['bg'])
                    tint.setAlpha(96 if theme_manager().mode=='dark' else 112)
                    painter.fillRect(self.rect(),tint)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                    painter.fillRect(self.rect(),QBrush(frost_texture(theme_manager().mode,COLORS[theme_manager().mode]['text'],5)))
                else:
                    # Offscreen captures and unsupported desktops cannot show
                    # a compositor backdrop. Keep their preview readable.
                    paint_workspace_glass(painter,self.rect())
        else:
            painter.fillRect(self.rect(),QColor(COLORS[theme_manager().mode]['bg']))
        painter.end()
