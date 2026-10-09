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
    """B uses a solid surface; glass uses translucent gradients and edge light."""
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
        upper=QColor(blend_color(c['panel'],c['text'],.015));upper.setAlpha(clamp_alpha(manager.glass_opacity*1.84) if glass else 255)
        lower=QColor(c['panel']);lower.setAlpha(clamp_alpha((manager.glass_opacity-18)*1.75) if glass else 255)
        gradient.setColorAt(0,upper);gradient.setColorAt(1,lower)
        painter.setBrush(gradient);painter.setPen(QPen(QColor(c['border']),1))
        painter.drawRoundedRect(rectangle,10,10)
        if glass:
            # The compositor blurs windows behind the app. This subtle grain
            # stays beneath child controls so text and input fields stay crisp.
            from PyQt6.QtGui import QPainterPath
            clip=QPainterPath();clip.addRoundedRect(rectangle,10,10)
            painter.save();painter.setClipPath(clip)
            sheen=QLinearGradient(rectangle.topLeft(),rectangle.bottomLeft())
            detail_scale=min(1,manager.glass_opacity/65)
            white=QColor(c['text']);white.setAlpha(clamp_alpha((13 if manager.mode=='dark' else 42)*detail_scale))
            sheen.setColorAt(0,white);white.setAlpha(0);sheen.setColorAt(.55,white)
            painter.fillRect(rectangle,sheen)
            grain_alpha=clamp_alpha((3 if manager.mode=='dark' else 6)*detail_scale)
            if grain_alpha:
                painter.fillRect(rectangle,QBrush(frost_texture(manager.mode,c['text'],grain_alpha)))
            painter.restore()
        highlight=QColor(c['text']);highlight.setAlpha((42 if manager.mode=='dark' else 80) if glass else 12)
        painter.setBrush(QColor(0,0,0,0));painter.setPen(QPen(highlight,.7))
        painter.drawRoundedRect(rectangle.adjusted(1,1,-1,-1),9,9)
        painter.end()


class WorkspaceBackground(QWidget):
    """One root tint; nested glass workspaces remain completely transparent."""
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
                if adapter is not None and adapter.active:
                    # A previous opaque B/fallback frame can remain in Qt's
                    # raster buffer. Replace its alpha instead of tinting over
                    # old pixels when switching into desktop glass.
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    painter.fillRect(self.rect(),Qt.GlobalColor.transparent)
                    manager=theme_manager()
                    tint=QColor(COLORS[manager.mode]['bg'])
                    # Panel opacity also adjusts the main desktop tint, without
                    # fading labels or controls through whole-window opacity.
                    opacity=manager.glass_opacity
                    # Preserve the existing tint above 65%, then fade smoothly
                    # to a genuinely clear workspace at the new zero endpoint.
                    tint.setAlpha(clamp_alpha(20*opacity/65 if opacity<65 else 20+(opacity-65)*1.4))
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(tint)
                    painter.drawRoundedRect(QRectF(self.rect()),16,16)
                else:
                    # Offscreen captures and unsupported desktops cannot show
                    # a compositor backdrop. Keep their preview readable.
                    paint_workspace_glass(painter,self.rect())
        else:
            painter.fillRect(self.rect(),QColor(COLORS[theme_manager().mode]['bg']))
        painter.end()
