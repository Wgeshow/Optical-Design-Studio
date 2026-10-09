"""Native widgets and coordinated light/dark styling for Optical Studio."""
import weakref
import tempfile
import os
import re
import json
from pathlib import Path

import pandas as pd
from PyQt6 import sip
from PyQt6.QtCore import QObject, QSettings, Qt, pyqtSignal, QSignalBlocker, QPoint, QEvent
from PyQt6.QtGui import QColor, QPalette, QFontDatabase, QFont, QImage, QPainter, QPolygon, QPen
from PyQt6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QSpinBox, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QWidget, QVBoxLayout, QGroupBox,
    QLabel, QPushButton, QScrollArea, QFileDialog, QMessageBox, QSizePolicy, QLayout)
from matplotlib.figure import Figure

COLORS = {
    'light': dict(bg='#f4f6fa', panel='#ffffff', field='#f8fafc', text='#202c40', muted='#5d6d83',
                  border='#dce3ed', accent='#2563eb', hover='#eef3fd', select='#e4edff', header='#f0f3f8', grid='#e2e8f0'),
    'dark': dict(bg='#11191f', panel='#182229', field='#141e25', text='#e7eff5', muted='#9eafbc',
                 border='#34434d', accent='#4199e1', hover='#203540', select='#204d64', header='#1b2b34', grid='#2c3e49'),
}
BASE_COLORS = {key: dict(value) for key, value in COLORS.items()}
GLASS_COLORS = {
    'light': dict(bg='#dce8f4', panel='#eef5fc', field='#f8fbff', text='#142d45', muted='#4f6880', border='#b3cadc', accent='#087e9b', hover='#d8edf8', select='#c1e6f4', header='#e4f0fa', grid='#c5d5e5'),
    'dark': dict(bg='#081b24', panel='#112832', field='#102630', text='#ecf6fc', muted='#acc2d0', border='#3b5966', accent='#34d2df', hover='#24404b', select='#17576a', header='#18333e', grid='#304853'),
}
LOOKS = {'dark': ('B · Dark', 'b', 'dark'), 'light': ('B · Light', 'b', 'light'),
         'glass_dark': ('Glass · Dark', 'glass', 'dark'), 'glass_light': ('Glass · Light', 'glass', 'light')}
CUSTOM_COLOR_ROLES = {'accent':'Accent', 'bg':'Background', 'panel':'Panels', 'field':'Input fields',
                      'text':'Text', 'muted':'Secondary text', 'border':'Borders'}


def blend_color(first, second, amount):
    a,b=QColor(first),QColor(second)
    return QColor(*(round(a_component*(1-amount)+b_component*amount) for a_component,b_component in zip(a.getRgb()[:3],b.getRgb()[:3]))).name()


def color_foreground(background):
    """Choose black or white by relative luminance for primary actions."""
    rgb=QColor(background).getRgbF()[:3]
    linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    luminance=sum(v*w for v,w in zip(linear,(.2126,.7152,.0722)))
    return '#101820' if luminance>.179 else '#ffffff'

def clamp_alpha(value):
    """Keep calculated surface alpha inside QColor's supported byte range."""
    return max(0, min(255, round(value)))


_icon_directory = None


def preferences():
    """Keep desktop preferences beside the portable data, on either platform."""
    root=Path(os.environ.get('S4_LIBRARY_ROOT') or Path(__file__).resolve().parent)
    path=root/'data_library'/'desktop_preferences.ini'
    path.parent.mkdir(parents=True,exist_ok=True)
    return QSettings(str(path),QSettings.Format.IniFormat)


def arrow_icon(mode,direction):
    global _icon_directory
    if _icon_directory is None:
        _icon_directory=tempfile.TemporaryDirectory(prefix='s4_qt_icons_')
    path=Path(_icon_directory.name)/(mode+'_'+COLORS[mode]['text'].lstrip('#')+'_'+direction+'.png')
    if not path.exists():
        image=QImage(12,8,QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter=QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS[mode]['text']))
        points=[QPoint(1,1),QPoint(11,1),QPoint(6,7)] if direction=='down' else [QPoint(1,7),QPoint(11,7),QPoint(6,1)]
        painter.drawPolygon(QPolygon(points))
        painter.end()
        image.save(str(path))
    return path.as_posix()


def check_icon(color):
    global _icon_directory
    if _icon_directory is None:
        _icon_directory=tempfile.TemporaryDirectory(prefix='s4_qt_icons_')
    path=Path(_icon_directory.name)/('check_'+color.lstrip('#')+'.png')
    if not path.exists():
        image=QImage(18,18,QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter=QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color),2.2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline(QPolygon([QPoint(4,9),QPoint(7,12),QPoint(14,5)]))
        painter.end();image.save(str(path))
    return path.as_posix()


class ThemeManager(QObject):
    changed = pyqtSignal(str)
    appearance_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings = preferences()
        self.mode = str(self.settings.value('theme', 'dark'))
        if self.mode not in COLORS:
            self.mode = 'dark'
        self.style=str(self.settings.value('interface_style','b'))
        if self.style not in ('b','glass'):self.style='b'
        try:
            supplied=json.loads(str(self.settings.value('custom_ui_colors','{}')))
            self.custom_colors={look:{key:value for key,value in roles.items() if key in CUSTOM_COLOR_ROLES and isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value)} for look,roles in supplied.items() if look in LOOKS and isinstance(roles,dict)} if isinstance(supplied,dict) else {}
        except (ValueError,TypeError):self.custom_colors={}
        try:self.glass_opacity=max(0,min(100,int(self.settings.value('glass_opacity',76))))
        except (ValueError,TypeError):self.glass_opacity=76
        try:
            self.scale = max(70, min(140, int(self.settings.value('interface_scale', 100))))
        except (ValueError, TypeError):
            self.scale = 100
        self.adaptive = self.settings.value('adaptive_layout', True, type=bool)
        self.window_factor = 1.0
        self.resolve_colors()

    @property
    def look(self):
        return ('glass_' if self.style=='glass' else '')+self.mode

    def apply_look(self,look,persist=True):
        if look not in LOOKS:raise ValueError('Choose B light/dark or Glass light/dark.')
        _,self.style,mode=LOOKS[look]
        if persist:self.settings.setValue('interface_style',self.style)
        self.apply(mode,persist=persist)

    def resolve_colors(self):
        c=dict((GLASS_COLORS if self.style=='glass' else BASE_COLORS)[self.mode])
        overrides=self.custom_colors.get(self.look,{})
        c.update(overrides)
        c['hover']=blend_color(c['panel'],c['accent'],.10)
        c['select']=blend_color(c['panel'],c['accent'],.23)
        c['header']=blend_color(c['panel'],c['accent'],.045)
        c['grid']=c['border']
        COLORS[self.mode].clear();COLORS[self.mode].update(c)
        return c

    def set_ui_color(self,key,color):
        if key not in CUSTOM_COLOR_ROLES:raise ValueError('Unknown interface color.')
        if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('Use a six-digit hex color, for example #53d6dc.')
        self.custom_colors.setdefault(self.look,{})[key]=color.lower()
        self.settings.setValue('custom_ui_colors',json.dumps(self.custom_colors));self.settings.sync()
        self.apply(self.mode,persist=False)

    def reset_ui_colors(self):
        self.custom_colors.pop(self.look,None)
        self.settings.setValue('custom_ui_colors',json.dumps(self.custom_colors));self.settings.sync()
        self.apply(self.mode,persist=False)

    def set_glass_opacity(self,value):
        self.glass_opacity=max(0,min(100,int(value)))
        self.settings.setValue('glass_opacity',self.glass_opacity);self.settings.sync()
        self.apply(self.mode,persist=False)

    def set_appearance(self, scale=None, adaptive=None):
        if scale is not None:
            self.scale = max(70, min(140, int(scale)))
        if adaptive is not None:
            self.adaptive = bool(adaptive)
        self.settings.setValue('interface_scale', self.scale)
        self.settings.setValue('adaptive_layout', self.adaptive)
        self.settings.sync()
        self.apply(self.mode, persist=False)
        self.appearance_changed.emit()

    def set_window_width(self, width):
        # Width is already in Qt logical pixels, so Windows 125%/150% scaling
        # must not be applied again. Prefer tighter spacing before smaller text.
        factor = self.window_density(width) if self.adaptive else 1.0
        if factor != self.window_factor:
            self.window_factor = factor
            self.apply(self.mode, persist=False)

    @property
    def effective_scale(self):
        return max(0.60, min(1.40, self.scale / 100 * self.window_factor))

    @staticmethod
    def window_density(width):
        stops = ((640, .76), (800, .80), (1100, .86), (1460, .92), (1920, 1.0))
        if width <= stops[0][0]:
            return stops[0][1]
        for (left, low), (right, high) in zip(stops, stops[1:]):
            if width <= right:
                return round(low + (high-low)*(width-left)/(right-left), 3)
        return 1.0

    def scale_stylesheet(self, stylesheet):
        def size(match):
            value, unit = float(match[1]), match[2]
            scaled = max(9, round(value*self.effective_scale, 1)) if unit == 'pt' else max(0, round(value*self.effective_scale))
            return f'{scaled:g}{unit}'
        return re.sub(r'(\d+(?:\.\d+)?)(pt|px)', size, stylesheet)

    def apply(self, mode, persist=True):
        self.mode = mode if mode in COLORS else 'dark'
        if persist:
            self.settings.setValue('theme', self.mode)
            self.settings.sync()
        app = QApplication.instance()
        c = self.resolve_colors()
        primary=QColor(c['accent']).darker(150).name() if self.mode=='dark' else c['accent']
        primary_text=color_foreground(primary)
        palette = QPalette()
        for role, color in ((QPalette.ColorRole.Window,c['bg']), (QPalette.ColorRole.WindowText,c['text']),
                (QPalette.ColorRole.Base,c['field']), (QPalette.ColorRole.AlternateBase,c['panel']),
                (QPalette.ColorRole.Text,c['text']), (QPalette.ColorRole.Button,c['panel']),
                (QPalette.ColorRole.ButtonText,c['text']), (QPalette.ColorRole.Highlight,c['select']),
                (QPalette.ColorRole.HighlightedText,c['text']), (QPalette.ColorRole.ToolTipBase,c['panel']),
                (QPalette.ColorRole.ToolTipText,c['text'])):
            palette.setColor(role,QColor(color))
        palette.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.Text,QColor(c['muted']))
        palette.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.ButtonText,QColor(c['muted']))
        if app:
            if not getattr(app,'_s4_fonts_loaded',False):
                from pathlib import Path
                import matplotlib
                for name in ('DejaVuSans.ttf','DejaVuSans-Bold.ttf'):
                    QFontDatabase.addApplicationFont(str(Path(matplotlib.get_data_path())/'fonts'/'ttf'/name))
                app.setFont(QFont('DejaVu Sans',10))
                app._s4_fonts_loaded=True
            if app.style().objectName().lower()!='fusion':app.setStyle('Fusion')
            if app.palette()!=palette:app.setPalette(palette)
            stylesheet = f'''
                QWidget {{ color:{c['text']}; font-family:"Segoe UI"; font-size:11pt; }}
                QMainWindow,QDialog,QScrollArea,QStackedWidget {{ background:{c['bg']}; }}
                QScrollArea {{ border:0; }}
                QWidget#page {{ background:{c['bg']}; }}
                QLabel {{ background:transparent; }}
                QLabel#pageTitle {{ font-size:22pt; font-weight:650; padding:4px 0 10px; }}
                QLabel#sectionTitle {{ font-size:13pt; font-weight:600; }}
                QLabel#muted {{ color:{c['muted']}; }}
                QLabel[error="true"] {{ color:{'#ffaaa5' if self.mode=='dark' else '#b42318'}; }}
                QLabel#brand {{ font-size:20pt; font-weight:700; color:{c['accent']}; }}
                QFrame#sidebar {{ background:{c['panel']}; border-right:1px solid {c['border']}; }}
                QListWidget#navigation {{ background:{c['panel']}; border:0; outline:0; padding:4px 0; }}
                QListWidget#navigation::item {{ color:{c['muted']}; padding:9px 10px; margin:2px 0; border-radius:5px; font-size:9pt; }}
                QListWidget#navigation::item:hover {{ background:{c['hover']}; color:{c['text']}; }}
                QListWidget#navigation::item:selected {{ background:{c['select']}; color:{c['accent']}; border-left:3px solid {c['accent']}; font-weight:600; }}
                QFrame#projectHeader {{ background:{c['panel']}; border:1px solid {c['border']}; border-top:0; border-bottom:0; border-radius:12px; }}
                QFrame#builderPanel {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:7px; }}
                QFrame#builderSeparator {{ background:{c['border']}; border:0; }}
                QPushButton#structureContinue {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #087985,stop:1 #23999f);color:white;min-height:28px;border:1px solid {c['accent']}; }}
                QFrame#builderPanel QScrollArea,QFrame#builderPanel QScrollArea QWidget {{ background:{c['panel']}; }}
                QPushButton[viewTab="true"] {{ border:0; border-bottom:2px solid transparent; background:transparent; padding:8px 12px; }}
                QPushButton[viewTab="true"]:checked {{ border-bottom:2px solid {c['accent']}; color:{c['accent']}; }}
                QPushButton:checked {{ background:{c['select']}; border-color:{c['accent']}; color:{c['accent']}; }}
                QFrame#windowChrome {{ background:{c['panel']}; border:1px solid {c['border']}; border-bottom:0; border-top-left-radius:16px; border-top-right-radius:16px; }}
                QFrame#workspaceFooter {{ border:1px solid {c['border']}; border-radius:12px; }}
                QFrame#workspaceTabs {{ background:{c['bg']}; border-bottom:1px solid {c['border']}; }}
                QPushButton[workspaceTab="true"] {{ background:{c['field']}; border:1px solid {c['border']}; border-radius:6px; padding:8px 16px; color:{c['muted']}; font-size:10pt; font-weight:600; text-align:center; }}
                QPushButton[workspaceTab="true"]:hover {{ background:{c['hover']}; color:{c['text']}; border-color:{c['accent']}; }}
                QPushButton[workspaceTab="true"]:checked,QPushButton[workspaceTab="true"][active="true"] {{ background:{c['select']}; color:{c['accent']}; border:2px solid {c['accent']}; font-weight:700; }}
                QFrame#workspaceFooter {{ background:{c['panel']}; border-top:1px solid {c['border']}; }}
                QLabel#workspaceLabel {{ color:{c['muted']}; font-size:9pt; font-weight:600; }}
                QLabel#windowTitle {{ color:{c['text']}; font-size:12pt; font-weight:400; }}
                QToolButton#projectPicker {{ border:1px solid {c['border']}; border-radius:8px; padding:4px 10px; }}
                QToolButton#projectSave {{ border:none; border-radius:6px; padding:6px; }}
                QToolButton#projectSave:hover {{ background:{c['field']}; border:1px solid {c['accent']}; }}
                QFrame#captionDivider {{ background:{c['border']}; border:0; }}
                QToolButton#chromeAction {{ padding:4px 11px; border:0; border-radius:5px; }}
                QToolButton#chromeAction::menu-indicator {{ image:none; width:0; }}
                QMenu {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; padding:5px; }}
                QMenu::item {{ padding:7px 28px 7px 22px; border-radius:4px; }}
                QMenu::item:selected {{ background:{c['hover']}; }}
                QMenu::item:disabled {{ color:{c['muted']}; }}
                QMenu::separator {{ height:1px; background:{c['border']}; margin:4px 6px; }}
                QFrame#structureNotice {{ background:{c['panel']}; border:1px solid {c['accent']}; border-radius:9px; }}
                QLabel#noticeTitle {{ color:{c['accent']}; font-size:11pt; font-weight:600; }}
                QGroupBox {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:10px;
                    margin-top:16px; padding:16px 14px 14px; font-weight:600; }}
                QGroupBox::title {{ subcontrol-origin:margin; left:14px; padding:0 5px; }}
                QTabWidget::pane {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:7px; top:-1px; }}
                QTabBar::tab {{ background:{c['field']}; color:{c['muted']}; border:1px solid {c['border']}; padding:7px 16px; margin-right:2px; border-top-left-radius:5px; border-top-right-radius:5px; }}
                QTabBar::tab:selected {{ background:{c['select']}; color:{c['accent']}; border-color:{c['accent']}; font-weight:600; }}
                QTabBar::tab:hover {{ background:{c['hover']}; color:{c['text']}; }}
                QFrame#metricCard {{ background:{c['field']}; border:1px solid {c['border']}; border-radius:7px; padding:6px; }}
                QLabel#metricValue {{ color:{c['text']}; font-size:15pt; font-weight:700; }}
                QLabel#responseValue {{ color:{c['text']}; font-size:27pt; font-weight:700; }}
                QLabel#metricLabel {{ color:{c['muted']}; font-size:8pt; }}
                QProgressBar {{ background:{c['field']}; border:1px solid {c['border']}; border-radius:5px; text-align:center; color:{c['text']}; }}
                QProgressBar::chunk {{ background:{c['accent']}; border-radius:4px; }}
                QPushButton {{ background:{c['field']}; border:1px solid {c['border']}; border-radius:6px;
                    padding:6px 12px; min-height:20px; font-weight:500; }}
                QPushButton:hover {{ background:{c['hover']}; border-color:{c['accent']}; }}
                QPushButton:pressed {{ background:{c['select']}; }}
                QPushButton[primary="true"],QFrame#builderPanel QPushButton[primary="true"] {{ background:{primary}; color:{primary_text}; border:1px solid {c['accent']}; font-weight:600; }}
                QPushButton[primary="true"]:hover,QFrame#builderPanel QPushButton[primary="true"]:hover {{ background:{QColor(primary).lighter(115).name()}; color:{primary_text}; }}
                QFrame#builderPanel QPushButton#structureContinue {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {blend_color(c['accent'],'#087985',.75)},stop:1 {blend_color(c['accent'],'#23999f',.75)});color:white;min-height:28px; }}
                QPushButton:focus,QToolButton:focus {{ border:1px solid {c['accent']}; }}
                QPushButton:disabled {{ color:{c['muted']}; background:{c['panel']}; }}
                QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QPlainTextEdit,QTextEdit {{ background:{c['field']};
                    border:1px solid {c['border']}; border-radius:6px; padding:6px; selection-background-color:{c['select']}; }}
                QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus {{ border-color:{c['accent']}; }}
                QSpinBox,QDoubleSpinBox {{ padding-right:24px; }}
                QComboBox {{ min-height:18px; padding-right:22px; }}
                QComboBox::drop-down {{ border:0; width:22px; }}
                QComboBox::down-arrow {{ image:url("{arrow_icon(self.mode,'down')}"); width:12px; height:8px; }}
                QSpinBox::up-button,QDoubleSpinBox::up-button {{ width:19px; background:{c['header']}; border:0; }}
                QSpinBox::down-button,QDoubleSpinBox::down-button {{ width:19px; background:{c['header']}; border:0; }}
                QSpinBox::up-arrow,QDoubleSpinBox::up-arrow {{ image:url("{arrow_icon(self.mode,'up')}"); width:10px; height:6px; }}
                QSpinBox::down-arrow,QDoubleSpinBox::down-arrow {{ image:url("{arrow_icon(self.mode,'down')}"); width:10px; height:6px; }}
                QComboBox QAbstractItemView {{ background:{c['field']}; selection-background-color:{c['select']}; padding:4px; }}
                QTableWidget,QTableView,QListWidget {{ background:{c['panel']}; border:1px solid {c['border']};
                    border-radius:6px; gridline-color:{c['border']}; alternate-background-color:{c['bg']};
                    selection-background-color:{c['select']}; selection-color:{c['text']}; }}
                QHeaderView::section {{ background:{c['header']}; border:0; border-right:1px solid {c['border']};
                    border-bottom:1px solid {c['border']}; padding:8px; font-weight:600; }}
                QTableWidget::item {{ padding:4px; }}
                QListWidget::item {{ padding:10px 8px; border-radius:5px; }}
                QListWidget#navigation {{ background:transparent; border:0; font-size:11pt; }}
                QListWidget#navigation::item {{ padding:8px 10px; margin:2px 0; border-radius:7px; }}
                QListWidget#navigation::item:selected {{ background:{c['select']}; border-left:3px solid {c['accent']}; }}
                QListWidget#navigation::item:hover {{ background:{c['hover']}; }}
                QListWidget#layerList::item:selected {{ background:{c['select']}; border:1px solid {c['accent']}; }}
                QTabWidget::pane {{ border:1px solid {c['border']}; border-radius:7px; background:{c['panel']}; }}
                QTabBar::tab {{ background:{c['bg']}; padding:7px 12px; border-bottom:2px solid transparent; }}
                QTabBar::tab:selected {{ background:{c['panel']}; color:{c['accent']}; border-bottom:2px solid {c['accent']}; }}
                QTabBar#opticalWorkflowTabs {{ background:transparent; border:0; }}
                QTabBar#opticalWorkflowTabs::tab {{ background:transparent; border:0; border-bottom:3px solid transparent; border-radius:7px; padding:9px 18px; margin:0; font-weight:400; }}
                QTabBar#opticalWorkflowTabs::tab:selected {{ background:{c['hover']}; border-bottom:3px solid {c['accent']}; color:{c['accent']}; font-weight:600; }}
                QTabBar#opticalWorkflowTabs::tab:hover {{ background:{c['hover']}; }}
                QTabBar#simulationWorkspaceTabs::tab {{ padding:7px 7px; font-size:9pt; margin:0; }}
                QLabel#globalStatus {{ color:{c['muted']}; font-size:9pt; }}
                QLabel#projectSelector {{ color:{c['text']}; font-weight:400; }}
                QSplitter::handle {{ background:{c['border']}; }}
                QProgressBar {{ border:0; border-radius:4px; background:{c['header']}; min-height:7px; text-align:center; }}
                QProgressBar::chunk {{ background:{c['accent']}; border-radius:4px; }}
                QCheckBox {{ spacing:8px; padding:4px 0; }}
                QCheckBox::indicator {{ width:18px; height:18px; border:1px solid {c['muted']}; border-radius:4px; background:{c['field']}; }}
                QCheckBox::indicator:hover {{ border-color:{c['accent']}; }}
                QCheckBox::indicator:checked {{ background:{c['accent']}; border-color:{c['accent']}; image:url("{check_icon(color_foreground(c['accent']))}"); }}
                QCheckBox::indicator:disabled {{ border-color:{c['border']}; background:{c['panel']}; }}
                QSlider::groove:horizontal {{ height:5px; background:{c['border']}; border-radius:2px; }}
                QSlider::sub-page:horizontal {{ background:{c['accent']}; border-radius:2px; }}
                QSlider::handle:horizontal {{ background:{c['accent']}; width:16px; margin:-6px 0; border-radius:8px; }}
                QToolBar {{ background:{c['panel']}; border:0; spacing:4px; }}
                QToolButton {{ background:transparent; border:0; padding:5px; }}
                QToolButton:hover {{ background:{c['hover']}; border-radius:4px; }}
                QScrollBar:vertical {{ background:{c['bg']}; width:11px; margin:0; }}
                QScrollBar::handle:vertical {{ background:{c['border']}; border-radius:5px; min-height:28px; }}
                QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{ height:0; }}
                QStatusBar {{ background:{c['panel']}; color:{c['muted']}; }}
                QToolTip {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; padding:6px; }}
            '''
            if self.style=='glass':
                surface=QColor(c['panel']);surface.setAlpha(clamp_alpha(self.glass_opacity*2.55))
                lower=QColor(c['header']);lower.setAlpha(clamp_alpha((self.glass_opacity-12)*2.55))
                upper_css=f'rgba({surface.red()},{surface.green()},{surface.blue()},{surface.alpha()})'
                lower_css=f'rgba({lower.red()},{lower.green()},{lower.blue()},{lower.alpha()})'
                stylesheet+=f'''
                    QMainWindow#opticalStudioWindow {{ background:transparent; }}
                    QScrollArea,QStackedWidget,QScrollArea > QWidget > QWidget {{ background:transparent; }}
                    QWidget#page {{ background:transparent; }}
                    QGroupBox,QTabWidget::pane {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {upper_css},stop:1 {lower_css}); border:1px solid {c['border']}; }}
                    QFrame#builderPanel {{ background:transparent; border:0; border-radius:14px; }}
                    QFrame#builderPanel QScrollArea,QFrame#builderPanel QScrollArea QWidget {{ background:transparent; }}
                    QFrame#builderPanel QLineEdit,QFrame#builderPanel QComboBox,QFrame#builderPanel QSpinBox,QFrame#builderPanel QDoubleSpinBox,QFrame#builderPanel QScrollArea QLineEdit,QFrame#builderPanel QScrollArea QComboBox,QFrame#builderPanel QScrollArea QSpinBox,QFrame#builderPanel QScrollArea QDoubleSpinBox {{ background:{c['field']}; }}
                    QFrame#builderPanel QTabWidget::pane {{ background:transparent; border-color:{c['border']}; }}
                    QFrame#windowChrome,QFrame#workspaceFooter,QFrame#projectHeader {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {upper_css},stop:1 {lower_css}); }}
                    QFrame#windowChrome {{ background:transparent; border:0; border-radius:0; }}
                    QToolButton#captionControl,QToolButton#captionControl:hover {{ background:transparent; border:0; }}
                    QTabBar#opticalWorkflowTabs {{ background:transparent; border:0; }}
                    QTabBar#opticalWorkflowTabs::tab {{ background:transparent; }}
                    QTabBar#opticalWorkflowTabs::tab:selected {{ background:{c['select']}; border-radius:8px; border-bottom:2px solid {c['accent']}; }}
                    QFrame#metricCard {{ background:{c['header']}; border:1px solid {c['border']}; border-radius:12px; }}
                    QSplitter::handle {{ background:transparent; }}
                '''
                gloss_top=blend_color(c['field'],c['text'],.12)
                gloss_band=blend_color(c['field'],c['text'],.045)
                gloss_bottom=blend_color(c['field'],c['bg'],.45)
                gloss_primary=blend_color(c['panel'],c['accent'],.38)
                gloss_primary_bottom=blend_color(c['panel'],c['accent'],.14)
                gloss_text=color_foreground(gloss_primary_bottom)
                input_top=blend_color(c['field'],c['text'],.08)
                input_bottom=blend_color(c['field'],c['bg'],.18)
                stylesheet+=f'''
                    QPushButton {{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {gloss_top},stop:0.22 {gloss_band},stop:0.5 {c['field']},stop:1 {gloss_bottom}); border-top:1px solid {blend_color(c['border'],c['text'],.3)}; border-bottom:2px solid {c['bg']}; }}
                    QPushButton:hover {{ border-color:{c['accent']}; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {blend_color(gloss_top,c['accent'],.16)},stop:0.25 {gloss_band},stop:1 {gloss_bottom}); }}
                    QPushButton:pressed {{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {gloss_bottom},stop:1 {gloss_top}); }}
                    QPushButton[primary="true"],QFrame#builderPanel QPushButton[primary="true"],QFrame#builderPanel QPushButton#structureContinue {{ color:{gloss_text}; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {blend_color(gloss_primary,c['text'],.10)},stop:0.23 {gloss_primary},stop:1 {gloss_primary_bottom}); border:1px solid {c['accent']};border-top:1px solid {blend_color(c['accent'],c['text'],.38)};border-bottom:2px solid {c['bg']}; }}
                    QPushButton[primary="true"]:hover,QFrame#builderPanel QPushButton[primary="true"]:hover {{ color:{gloss_text}; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {blend_color(gloss_primary,c['text'],.18)},stop:0.23 {gloss_primary},stop:1 {gloss_primary_bottom}); }}
                    QPushButton[primary="true"]:pressed,QFrame#builderPanel QPushButton[primary="true"]:pressed {{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {gloss_primary_bottom},stop:1 {gloss_primary}); }}
                    QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QFrame#builderPanel QLineEdit,QFrame#builderPanel QComboBox,QFrame#builderPanel QSpinBox,QFrame#builderPanel QDoubleSpinBox {{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {input_top},stop:0.2 {c['field']},stop:1 {input_bottom});border-top:1px solid {blend_color(c['border'],c['text'],.22)}; }}
                    QTabBar::tab:selected,QTabBar#opticalWorkflowTabs::tab:selected {{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {blend_color(gloss_primary,c['text'],.12)},stop:0.23 {gloss_primary},stop:1 {gloss_primary_bottom}); color:{c['text']};border:1px solid {c['accent']};border-top:1px solid {blend_color(c['accent'],c['text'],.35)};border-bottom:2px solid {c['accent']};border-radius:7px; }}
                    QPushButton:disabled {{ color:{c['muted']};background:{c['panel']};border:1px solid {c['border']}; }}
                '''
            # Qt already accounts for monitor DPI; this is the independent user zoom.
            stylesheet = self.scale_stylesheet(stylesheet)
            if app.styleSheet()!=stylesheet:app.setStyleSheet(stylesheet)
        for widget in list(_plots):
            if sip.isdeleted(widget):
                _plots.discard(widget)
            else:
                widget.retheme()
        self.changed.emit(self.mode)


_theme = None
_plots = weakref.WeakSet()


def theme_manager():
    global _theme
    if _theme is None:
        _theme = ThemeManager()
    return _theme


def apply_plot_theme(figure):
    c = COLORS[theme_manager().mode]
    figure.set_facecolor(c['panel'])
    for ax in figure.axes:
        ax.set_facecolor(c['panel'])
        ax.tick_params(colors=c['muted'])
        ax.xaxis.label.set_color(c['text'])
        ax.yaxis.label.set_color(c['text'])
        ax.xaxis.get_offset_text().set_color(c['muted'])
        ax.yaxis.get_offset_text().set_color(c['muted'])
        if hasattr(ax, 'zaxis'):
            ax.zaxis.label.set_color(c['text'])
            for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
                axis.set_pane_color(QColor(c['panel']).getRgbF())
                axis.line.set_color(c['border'])
                # Matplotlib's 3D grid styling lives on each axis rather than
                # the ordinary 2D grid line artists.
                axis._axinfo['grid']['color'] = c['grid']
        ax.title.set_color(c['text'])
        for spine in ax.spines.values():
            spine.set_color(c['border'])
        for line in [*ax.get_xgridlines(),*ax.get_ygridlines()]:
            line.set_color(c['grid'])
        for text in ax.texts:
            text.set_color(c['text'])
            if text.get_bbox_patch() is not None:
                text.get_bbox_patch().set_facecolor(c['panel'])
                text.get_bbox_patch().set_edgecolor(c['border'])
        legend = ax.get_legend()
        if legend:
            legend.get_frame().set_facecolor(c['panel'])
            legend.get_frame().set_edgecolor(c['border'])
            for text in legend.get_texts():
                text.set_color(c['text'])
    for text in figure.texts:
        text.set_color(c['text'])


from PyQt6.QtWidgets import QToolBar
from PyQt6.QtCore import QSize


class PublicationToolbar(QToolBar):
    """Native icon controls; publication export keeps its own figure backend."""
    def __init__(self,canvas,owner):
        super().__init__(owner)
        self.owner=owner
        self.canvas=canvas
        self.mode=''
        self.setMovable(False)
        self.setFloatable(False)
        self.setIconSize(QSize(20,20))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        from qt_native_plot import plot_icon
        self.buttons={}
        for name,callback in [('Fit',self.home),('Pan',self.pan),('Zoom',self.zoom),
                              ('Copy',self.copy_figure),('Export',self.save_figure),
                              ('Figure settings',self.owner.edit_figure_settings)]:
            action=self.addAction(plot_icon(name,COLORS[theme_manager().mode]['text']),name,callback)
            action.setToolTip(name)
            if name in ('Pan','Zoom'):action.setCheckable(True)
            self.buttons[name]=action
        self.coordinate_label=QLabel()
        self.coordinate_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.coordinate_label.setMinimumWidth(0)
        self.coordinate_label.setMaximumWidth(220)
        self.addWidget(self.coordinate_label)
        self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        canvas.toolbar=self
        canvas.coordinateChanged.connect(self.set_message)

    def home(self,*_):
        self.canvas.fit_data()
        self.mode=''
        self.buttons['Pan'].setChecked(False)
        self.buttons['Zoom'].setChecked(False)
        self.canvas.set_mode(False)

    def pan(self,*_):
        active=self.mode!='pan/zoom'
        self.mode='pan/zoom' if active else ''
        self.buttons['Pan'].setChecked(active)
        self.buttons['Zoom'].setChecked(False)
        self.canvas.set_mode(False)

    def zoom(self,*_):
        active=self.mode!='zoom rect'
        self.mode='zoom rect' if active else ''
        self.buttons['Zoom'].setChecked(active)
        self.buttons['Pan'].setChecked(False)
        self.canvas.set_mode(active)

    def copy_figure(self,*_):
        QApplication.clipboard().setPixmap(self.canvas.view.grab())
        notify=getattr(self.owner.window(),'notify_action',None)
        if callable(notify):notify('Copied','Plot copied to clipboard.')
    def set_message(self,message):
        if hasattr(self,'coordinate_label'):
            label=self.coordinate_label
            label.setText(label.fontMetrics().elidedText(str(message),Qt.TextElideMode.ElideRight,max(1,label.width())))
            label.setToolTip(str(message))

    def save_figure(self,*_):
        self.owner.export_dialog()

class PlotWidget(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0,0,0,0)
        self.figure = None
        self.canvas = None
        self.toolbar = None
        from publication_plot import defaults
        self.figure_style=defaults()
        self.canvas_host=QWidget(self)
        self.canvas_host.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        self.canvas_host.installEventFilter(self)
        self.canvas_layout=QVBoxLayout(self.canvas_host)
        self.canvas_layout.setContentsMargins(0,0,0,0)
        self.canvas_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.layout_.addWidget(self.canvas_host,1)
        self.setMinimumHeight(260)
        _plots.add(self)
        from qt_native_figure import NativeFigureCanvas
        self.canvas=NativeFigureCanvas(parent=self.canvas_host,colors=COLORS[theme_manager().mode])
        self.canvas_layout.addWidget(self.canvas,1)
        self.toolbar=PublicationToolbar(self.canvas,self)
        self.layout_.insertWidget(0,self.toolbar)
        self.clear()

    def draw_figure(self,figure=None):
        figure = figure or self.figure
        self.figure = figure
        apply_plot_theme(figure)
        from publication_plot import apply_style
        apply_style(figure,self.figure_style)
        self.axes = figure.axes[0] if figure.axes else figure.add_subplot(111)
        self.canvas.set_figure(figure,colors=COLORS[theme_manager().mode])
        self.fit_canvas()

    def clear(self):
        figure = Figure(figsize=(7,4),layout='constrained')
        ax = figure.add_subplot(111)
        ax.text(.5,.5,'Results will appear here',ha='center',va='center',transform=ax.transAxes)
        ax.set_axis_off()
        self.draw_figure(figure)

    def retheme(self):
        if self.figure is not None:
            apply_plot_theme(self.figure)
            from publication_plot import apply_style
            apply_style(self.figure,self.figure_style)
            from qt_native_plot import plot_icon
            for name,action in self.toolbar.buttons.items():action.setIcon(plot_icon(name,COLORS[theme_manager().mode]['text']))
            self.canvas.set_figure(self.figure,colors=COLORS[theme_manager().mode],preserve_view=True)
            self.fit_canvas()

    def fit_canvas(self):
        if self.canvas is None:return
        # Live charts always fill their host. Physical paper dimensions are
        # applied only by publication_plot.export_figure.
        self.canvas.setMinimumSize(0,0)
        self.canvas.setMaximumSize(16777215,16777215)
        self.canvas.updateGeometry()

    def eventFilter(self,watched,event):
        if watched is self.canvas_host and event.type()==QEvent.Type.Resize:self.fit_canvas()
        return super().eventFilter(watched,event)

    def edit_figure_settings(self):
        from publication_plot import edit_settings
        edit_settings(self)

    def export_figure(self,path):
        from publication_plot import export_figure
        export_figure(self.figure,path,self.figure_style)

    def export_dialog(self):
        path,selected=QFileDialog.getSaveFileName(self,'Export publication figure','figure.pdf','PDF vector (*.pdf);;SVG vector (*.svg);;PNG image (*.png);;TIFF image (*.tiff)')
        if path:
            if not Path(path).suffix:path+='.'+{'PDF':'pdf','SVG':'svg','PNG':'png','TIFF':'tiff'}[selected.split()[0]]
            try:self.export_figure(path)
            except Exception as exc:QMessageBox.warning(self,'Figure export failed',str(exc))


class CompactDoubleSpinBox(QDoubleSpinBox):
    def textFromValue(self,value):
        text=super().textFromValue(value)
        decimal=self.locale().decimalPoint()
        return text.rstrip('0').rstrip(decimal) if decimal in text else text


def number(value=0,minimum=-1e12,maximum=1e12,decimals=6):
    widget=CompactDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(minimum,maximum)
    widget.setValue(float(value or 0))
    widget.setKeyboardTracking(False)
    widget.setMinimumWidth(100)
    return widget


def integer(value=0,min=0,max=1000000):
    widget=QSpinBox()
    widget.setRange(min,max)
    widget.setValue(int(value or 0))
    widget.setKeyboardTracking(False)
    return widget


def combo(items,current=None):
    widget=QComboBox()
    widget.setMinimumWidth(120)
    widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    widget.setMinimumContentsLength(12)
    set_choices(widget,items,current)
    return widget


def set_choices(widget,items,value=None):
    previous=widget.currentData() if value is None else value
    blocker=QSignalBlocker(widget)
    widget.clear()
    for item in items:
        label,data=item if isinstance(item,(list,tuple)) and len(item)==2 else (str(item),item)
        widget.addItem(str(label),data)
    index=widget.findData(previous)
    widget.setCurrentIndex(index if index>=0 else 0 if widget.count() else -1)
    del blocker


def table(headers):
    widget=QTableWidget(0,len(headers))
    widget.setHorizontalHeaderLabels(list(headers))
    widget.setAlternatingRowColors(True)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setWordWrap(False)
    widget.setTextElideMode(Qt.TextElideMode.ElideRight)
    widget.verticalHeader().setVisible(False)
    widget.verticalHeader().setDefaultSectionSize(max(32,widget.fontMetrics().height()+12))
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setMinimumHeight(150)
    return widget


def fill_table(widget,data):
    frame=data if isinstance(data,pd.DataFrame) else pd.DataFrame(data)
    blocker=QSignalBlocker(widget)
    widget.setSortingEnabled(False)
    if len(frame.columns):
        widget.setColumnCount(len(frame.columns))
        widget.setHorizontalHeaderLabels([str(x) for x in frame.columns])
    widget.setRowCount(len(frame))
    for row,values in enumerate(frame.itertuples(index=False,name=None)):
        for column,value in enumerate(values):
            item=QTableWidgetItem('' if value is None else str(value))
            item.setToolTip(item.text())
            widget.setItem(row,column,item)
    widget.resizeColumnsToContents()
    for column in range(widget.columnCount()):
        widget.setColumnWidth(column,min(260,max(85,widget.columnWidth(column))))
    del blocker


def card(title):
    return QGroupBox(title)


def note(text):
    widget=QLabel(text)
    widget.setWordWrap(True)
    widget.setObjectName('muted')
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def completion_notice(text):
    """Recognize successful feedback, preserving problems and ongoing work."""
    text=str(text or '').strip()
    if not text:return None
    if re.match(r'^(no\b|not\b|select\b|choose\b)',text,re.I):return None
    if re.search(r'\b(fail(?:ed|ure)?|error|unable|could not|needs?|warning(?:s)?|cancel(?:led|ling)?|missing|invalid|requires?|processing|preparing|running|checking|installing|waiting|searching|training|collecting|validating|downloading|reading|verifying|pending|comparing|saving|copying|exporting|importing|restarting|awaiting|resuming)\b',text,re.I):
        return None
    match=re.search(r'\b(completed?|finished|saved|loaded|opened|exported|copied|applied|updated|imported|added|removed|deleted|duplicated|restored|created|assigned|pasted|downloaded|found)\b',text,re.I)
    if not match:return None
    action=match.group(1).lower()
    title='Completed' if action in ('complete','completed','finished') else action.capitalize()
    summary=text.split('. ',1)[0].split('\n',1)[0]
    if len(summary)>145:summary=summary[:142].rstrip()+'…'
    return title,summary


class ActionStatusLabel(QLabel):
    """Successful actions become a toast; actionable feedback keeps its space."""
    def __init__(self,text='',parent=None):
        super().__init__(text,parent)
        self.setWordWrap(True)
        self.setVisible(bool(text) and not str(text).startswith('Ready'))

    def setText(self,text):
        text=str(text or '')
        super().setText(text)
        self.setToolTip(text)
        notice=completion_notice(text)
        self.setVisible(bool(text) and not text.startswith('Ready') and notice is None)
        notify=getattr(self.window(),'notify_action',None)
        if notice is not None and callable(notify):
            notify(*notice,detail=text)


def button(text,callback=None,primary=False):
    widget=QPushButton(text)
    widget.setProperty('primary',primary)
    if callback:
        widget.clicked.connect(callback)
    return widget


def scroll(widget):
    area=QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    return area
