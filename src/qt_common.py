"""Native widgets and coordinated light/dark styling for Optical Studio."""
import weakref
import tempfile
import os
import re
from pathlib import Path

import pandas as pd
from PyQt6 import sip
from PyQt6.QtCore import QObject, QSettings, Qt, pyqtSignal, QSignalBlocker, QPoint
from PyQt6.QtGui import QColor, QPalette, QFontDatabase, QFont, QImage, QPainter, QPolygon
from PyQt6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QSpinBox, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QWidget, QVBoxLayout, QGroupBox,
    QLabel, QPushButton, QScrollArea)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

COLORS = {
    'light': dict(bg='#f2f5f8', panel='#ffffff', field='#ffffff', text='#172d3b', muted='#586d7d',
                  border='#d6e0e8', accent='#087f78', hover='#e4f2f0', select='#d0ebe7', header='#eaf0f5', grid='#d7e0e7'),
    'dark': dict(bg='#101821', panel='#18232f', field='#202e3c', text='#e5eef5', muted='#adbdcd',
                 border='#344555', accent='#4ed6c1', hover='#24443f', select='#28594f', header='#223343', grid='#3a4b59'),
}

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
    path=Path(_icon_directory.name)/(mode+'_'+direction+'.png')
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


class ThemeManager(QObject):
    changed = pyqtSignal(str)
    appearance_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings = preferences()
        self.mode = str(self.settings.value('theme', 'dark'))
        if self.mode not in COLORS:
            self.mode = 'dark'
        try:
            self.scale = max(80, min(140, int(self.settings.value('interface_scale', 100))))
        except (ValueError, TypeError):
            self.scale = 100
        self.adaptive = self.settings.value('adaptive_layout', True, type=bool)
        self.window_factor = 1.0

    def set_appearance(self, scale=None, adaptive=None):
        if scale is not None:
            self.scale = max(80, min(140, int(scale)))
        if adaptive is not None:
            self.adaptive = bool(adaptive)
        self.settings.setValue('interface_scale', self.scale)
        self.settings.setValue('adaptive_layout', self.adaptive)
        self.settings.sync()
        self.apply(self.mode, persist=False)
        self.appearance_changed.emit()

    def set_window_width(self, width):
        factor = (0.9 if width < 1000 else 1.0 if width < 1600 else 1.1) if self.adaptive else 1.0
        if factor != self.window_factor:
            self.window_factor = factor
            self.apply(self.mode, persist=False)

    @property
    def effective_scale(self):
        return max(0.8, min(1.54, self.scale / 100 * self.window_factor))

    def apply(self, mode, persist=True):
        self.mode = mode if mode in COLORS else 'dark'
        if persist:
            self.settings.setValue('theme', self.mode)
            self.settings.sync()
        app = QApplication.instance()
        c = COLORS[self.mode]
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
            app.setStyle('Fusion')
            app.setPalette(palette)
            stylesheet = f'''
                QWidget {{ color:{c['text']}; font-family:"Segoe UI","DejaVu Sans",sans-serif; font-size:10pt; }}
                QMainWindow,QDialog,QScrollArea,QStackedWidget {{ background:{c['bg']}; }}
                QScrollArea {{ border:0; }}
                QWidget#page {{ background:{c['bg']}; }}
                QLabel {{ background:transparent; }}
                QLabel#pageTitle {{ font-size:23pt; font-weight:650; }}
                QLabel#sectionTitle {{ font-size:15pt; font-weight:600; }}
                QLabel#muted {{ color:{c['muted']}; }}
                QLabel[error="true"] {{ color:{'#ffaaa5' if self.mode=='dark' else '#b42318'}; }}
                QLabel#brand {{ font-size:20pt; font-weight:700; color:{c['accent']}; }}
                QFrame#sidebar {{ background:{c['panel']}; border-right:1px solid {c['border']}; }}
                QFrame#projectHeader {{ background:{c['panel']}; border-bottom:1px solid {c['border']}; }}
                QFrame#windowChrome {{ background:{c['panel']}; border-bottom:1px solid {c['border']}; }}
                QLabel#windowTitle {{ color:{c['text']}; font-size:10pt; font-weight:600; }}
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
                QGroupBox {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:9px;
                    margin-top:15px; padding:17px 13px 13px; font-weight:600; }}
                QGroupBox::title {{ subcontrol-origin:margin; left:14px; padding:0 5px; }}
                QPushButton {{ background:{c['field']}; border:1px solid {c['border']}; border-radius:6px;
                    padding:8px 13px; min-height:18px; font-weight:500; }}
                QPushButton:hover {{ background:{c['hover']}; border-color:{c['accent']}; }}
                QPushButton:pressed {{ background:{c['select']}; }}
                QPushButton[primary="true"] {{ background:#087f78; color:#ffffff; border-color:#087f78; font-weight:600; }}
                QPushButton[primary="true"]:hover {{ background:#096b65; }}
                QPushButton:disabled {{ color:{c['muted']}; background:{c['panel']}; }}
                QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QPlainTextEdit,QTextEdit {{ background:{c['field']};
                    border:1px solid {c['border']}; border-radius:5px; padding:7px; selection-background-color:{c['select']}; }}
                QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus {{ border-color:{c['accent']}; }}
                QSpinBox,QDoubleSpinBox {{ padding-right:24px; }}
                QComboBox {{ min-height:20px; padding-right:22px; }}
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
                QListWidget#navigation::item {{ padding:14px 16px; margin:3px 0; }}
                QListWidget#navigation::item:selected {{ background:{c['select']}; border-left:3px solid {c['accent']}; }}
                QListWidget#navigation::item:hover {{ background:{c['hover']}; }}
                QListWidget#layerList::item:selected {{ background:{c['select']}; border:1px solid {c['accent']}; }}
                QTabWidget::pane {{ border:1px solid {c['border']}; border-radius:7px; background:{c['panel']}; }}
                QTabBar::tab {{ background:{c['bg']}; padding:10px 17px; border-bottom:2px solid transparent; }}
                QTabBar::tab:selected {{ background:{c['panel']}; color:{c['accent']}; border-bottom:2px solid {c['accent']}; }}
                QSplitter::handle {{ background:{c['border']}; }}
                QProgressBar {{ border:0; border-radius:4px; background:{c['header']}; min-height:7px; text-align:center; }}
                QProgressBar::chunk {{ background:#087f78; border-radius:4px; }}
                QToolBar {{ background:{c['panel']}; border:0; spacing:4px; }}
                QToolButton {{ background:transparent; border:0; padding:5px; }}
                QToolButton:hover {{ background:{c['hover']}; border-radius:4px; }}
                QScrollBar:vertical {{ background:{c['bg']}; width:11px; margin:0; }}
                QScrollBar::handle:vertical {{ background:{c['border']}; border-radius:5px; min-height:28px; }}
                QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{ height:0; }}
                QStatusBar {{ background:{c['panel']}; color:{c['muted']}; }}
                QToolTip {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; padding:6px; }}
            '''
            # Qt already accounts for monitor DPI; this is the independent user zoom.
            stylesheet = re.sub(r'(\d+(?:\.\d+)?)(pt|px)',
                lambda m: f'{max(1, round(float(m[1]) * self.effective_scale))}{m[2]}', stylesheet)
            app.setStyleSheet(stylesheet)
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


class PlotWidget(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0,0,0,0)
        self.figure = None
        self.canvas = None
        self.toolbar = None
        self.setMinimumHeight(260)
        _plots.add(self)
        self.clear()

    def draw_figure(self,figure=None):
        figure = figure or self.figure
        if figure is self.figure:
            self.retheme()
            return
        old = self.figure
        for widget in (self.toolbar,self.canvas):
            if widget is not None:
                self.layout_.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
        self.figure = figure
        apply_plot_theme(figure)
        self.canvas = FigureCanvasQTAgg(figure)
        self.toolbar = NavigationToolbar2QT(self.canvas,self)
        self.layout_.addWidget(self.toolbar)
        self.layout_.addWidget(self.canvas,1)
        self.axes = figure.axes[0] if figure.axes else figure.add_subplot(111)
        self.canvas.draw_idle()
        if old is not None:
            old.clear()

    def clear(self):
        figure = Figure(figsize=(7,4),layout='constrained')
        ax = figure.add_subplot(111)
        ax.text(.5,.5,'Results will appear here',ha='center',va='center',transform=ax.transAxes)
        ax.set_axis_off()
        self.draw_figure(figure)

    def retheme(self):
        if self.figure is not None:
            apply_plot_theme(self.figure)
            old=self.toolbar
            self.layout_.removeWidget(old)
            old.setParent(None)
            old.deleteLater()
            self.toolbar=NavigationToolbar2QT(self.canvas,self)
            self.layout_.insertWidget(0,self.toolbar)
            self.canvas.draw_idle()


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
