"""Native live spectrum view. Matplotlib is used only to create export figures.

The caller retains saved scientific data. Display scaling, clipping, and optional
downsampling never change that data. Publication export is an explicit callback.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap, QPainter, QPen
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QToolButton, QButtonGroup, QSizePolicy, QApplication, QFileDialog, QMessageBox)
# Source distributions can carry this small pure-Python dependency locally.
_local=Path(__file__).resolve().parent/'plot_dependencies'
if (_local/'pyqtgraph').is_dir() and str(_local) not in sys.path:
    sys.path.insert(0,str(_local))
import pyqtgraph as pg
import pyqtgraph.exporters

DEFAULT_COLORS = dict(bg='#081b24', panel='#112832', field='#102630',
    text='#ecf6fc', muted='#acc2d0', border='#3b5966', accent='#34d2df')
SERIES = [('A', 'Absorption', '#00b99f'), ('R', 'Reflection', '#5487ec'),
          ('T', 'Transmission', '#e3a650')]


def plot_icon(name,color):
    """Small high-DPI vector marks using the same drawing style as qt_icons."""
    if name=='Figure settings':
        from qt_icons import navigation_icon
        return navigation_icon('Settings',color)
    pixmap=QPixmap(72,72);pixmap.setDevicePixelRatio(3)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color),1.7,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    def line(x1,y1,x2,y2):painter.drawLine(QPointF(x1,y1),QPointF(x2,y2))
    if name=='Fit':
        for x,y,sx,sy in ((3,3,1,1),(21,3,-1,1),(3,21,1,-1),(21,21,-1,-1)):
            line(x,y,x+5*sx,y);line(x,y,x,y+5*sy)
        painter.drawRect(QRectF(8,8,8,8))
    elif name=='Pan':
        line(3,12,21,12);line(12,3,12,21)
        for x,y,sx,sy in ((3,12,1,0),(21,12,-1,0),(12,3,0,1),(12,21,0,-1)):
            line(x,y,x+3*sx+3*sy,y+3*sy+3*sx)
            line(x,y,x+3*sx-3*sy,y+3*sy-3*sx)
    elif name=='Zoom':
        painter.drawEllipse(QRectF(3,3,13,13));line(14,14,21,21)
        line(6,9.5,13,9.5);line(9.5,6,9.5,13)
    elif name=='Copy':
        painter.drawRoundedRect(QRectF(8,8,13,13),1,1)
        line(3,16,3,3);line(3,3,16,3);line(16,3,16,6);line(3,16,6,16)
    elif name=='Export':
        line(12,3,12,15);line(8,11,12,15);line(12,15,16,11)
        line(4,16,4,21);line(4,21,20,21);line(20,21,20,16)
    painter.end();return QIcon(pixmap)


def theme_plot(plot, colors, percent=False):
    font = QFont('Segoe UI', 9)
    for side in ('left', 'bottom'):
        axis = plot.getAxis(side)
        axis.setPen(pg.mkPen(colors['border']))
        axis.setTextPen(pg.mkPen(colors['muted']))
        axis.setTickFont(font)
        axis.setStyle(autoExpandTextSpace=False, tickTextOffset=8,
                      hideOverlappingLabels=False, maxTickLevel=0, maxTextLevel=0)
        axis.enableAutoSIPrefix(False)
    plot.getAxis('left').setWidth(70 if percent else 56)
    plot.getAxis('bottom').setHeight(52)
    plot.getViewBox().setBorder(pg.mkPen(colors['border']))
    plot.getViewBox().setBackgroundColor(QColor(0, 0, 0, 0))
    plot.setMenuEnabled(False)
    plot.hideButtons()
    plot.showGrid(x=True, y=True, alpha=.15)
    plot.setTitle(plot.titleLabel.text, color=colors['text'], size='11pt')


class NativeAxis(pg.AxisItem):
    def boundingRect(self):
        bounds=super().boundingRect()
        # AxisItem's grid bounds otherwise discard labels at 0 and 100.
        if self.orientation in ('left','right'):return bounds.adjusted(0,-15,0,15)
        return bounds.adjusted(-15,0,15,0)


class PercentAxis(NativeAxis):
    def tickStrings(self, values, scale, spacing):
        return [f'{v:g}%' for v in values]


class _NativeBase(QWidget):
    def _base(self, colors):
        self.colors = dict(colors or DEFAULT_COLORS)
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(4)
        self.toolbar = QWidget()
        self.toolbar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self.toolbar)
        row.setContentsMargins(4, 4, 4, 0)
        row.setSpacing(4)
        self.buttons={}
        self.mode_buttons=QButtonGroup(self)
        self.mode_buttons.setExclusive(True)
        for name, callback in [('Fit', self.fit_data), ('Pan', lambda:self.set_mode(False)),
                               ('Zoom', lambda:self.set_mode(True)), ('Copy', self.copy_graph),
                               ('Export', self.export_dialog)]:
            button = self._tool_button(name,callback)
            if name in ('Pan','Zoom'):
                button.setCheckable(True);self.mode_buttons.addButton(button)
            row.addWidget(button)
        row.addStretch(1)
        self.layout_.addWidget(self.toolbar)
        self.paper_export_callback = None

    def _tool_button(self,name,callback):
        button=QToolButton(self.toolbar)
        button.setFixedSize(30,30);button.setIconSize(QSize(20,20))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAccessibleName(name);button.setToolTip(name)
        button.setIcon(plot_icon(name,self.colors['text']))
        button.clicked.connect(callback)
        self.buttons[name]=button
        return button

    def _configure_view(self, view):
        view.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        view.setMinimumSize(0, 0)
        view.setBackground(None)
        view.setStyleSheet('background:transparent; border:0;')
        view.viewport().setAutoFillBackground(False)
        view.setFrameShape(view.Shape.NoFrame)
        self.layout_.addWidget(view, 1)

    def copy_graph(self):
        QApplication.clipboard().setPixmap(self.view.grab())
        self._notify_action('Copied','Spectrum copied to clipboard.')

    def _notify_action(self,title,summary,detail=''):
        notify=getattr(self.window(),'notify_action',None)
        if callable(notify):notify(title,summary,detail=detail)

    def export_view(self, path, width=1600):
        path = Path(path)
        target = self.view.plotItem if isinstance(self.view, pg.PlotWidget) else self.view.scene()
        exporter = (pg.exporters.SVGExporter(target) if path.suffix.lower()=='.svg'
                    else pg.exporters.ImageExporter(target))
        if 'width' in exporter.parameters():
            exporter.parameters()['width'] = int(width)
        if 'background' in exporter.parameters():
            exporter.parameters()['background'] = QColor(self.colors['field'])
        exporter.export(str(path))

    def export_dialog(self):
        formats = 'PNG current view (*.png);;SVG current view (*.svg)'
        if self.paper_export_callback:
            formats += ';;PDF publication figure (*.pdf);;TIFF publication figure (*.tiff)'
        path, _ = QFileDialog.getSaveFileName(self, 'Export plot', 'spectrum.png', formats)
        if path:
            if Path(path).suffix.lower() in ('.pdf','.tiff') and self.paper_export_callback:
                self.paper_export_callback(path)
            else:
                self.export_view(path)


class NativeSpectrumWidget(_NativeBase):
    sampleSelected = pyqtSignal(int)

    def __init__(self, parent=None, colors=None, paper_factory=None):
        super().__init__(parent)
        self._base(colors)
        self.raw = pd.DataFrame()
        self._paper_factory=paper_factory
        self._paper=None
        self._cursor_position=None
        self.peak_key='A'
        from publication_plot import defaults
        self.figure_style=defaults()
        self.variable = 'wavelength_nm'
        self.view = pg.PlotWidget(axisItems={'left':PercentAxis('left'),'bottom':NativeAxis('bottom')})
        self._configure_view(self.view)
        self.plot = self.view.plotItem
        self.plot.setTitle('Optical response')
        theme_plot(self.plot, self.colors, percent=True)
        self.plot.setLabel('left','Incident power (%)',color=self.colors['text'],size='10pt')
        self.plot.setLabel('bottom','Wavelength (nm)',color=self.colors['text'],size='10pt')
        self.legend = self.plot.addLegend(offset=(14, -18), labelTextColor=self.colors['text'],
            labelTextSize='9pt', brush=pg.mkBrush(self.colors['panel']),
            pen=pg.mkPen(self.colors['border']))
        self.curves = {key:self.plot.plot([], [], name=name, pen=pg.mkPen(color,width=1.8),
            connect='finite', autoDownsample=True, downsampleMethod='peak', clipToView=True)
            for key,name,color in SERIES}
        self.cursor = pg.InfiniteLine(angle=90,movable=False,
            pen=pg.mkPen('#a1bbc9',width=1,style=Qt.PenStyle.DashLine))
        self.plot.addItem(self.cursor,ignoreBounds=True)
        self.marker = pg.ScatterPlotItem(size=8,brush='#e8748b',pen=None)
        self.plot.addItem(self.marker)
        self.readout = QLabel('Select a sample')
        self.readout.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.readout.setFixedHeight(25)
        self.readout.setMinimumWidth(0)
        self.layout_.addWidget(self.readout)
        self.full_readout = ''
        self.view.scene().sigMouseClicked.connect(self._clicked)
        self.view.scene().sigMouseMoved.connect(self._hovered)
        self._range_timer=QTimer(self);self._range_timer.setSingleShot(True)
        self._range_timer.timeout.connect(self._load_visible_samples)
        self.plot.getViewBox().sigXRangeChanged.connect(lambda *args:self._range_timer.start(120))
        self.plot.setYRange(0,100,padding=0)
        self.plot.setLimits(yMin=0,yMax=100)
        self.set_mode(False)
        from qt_common import theme_manager
        theme_manager().changed.connect(self.retheme)
        self.toolbar.layout().addWidget(self._settings_button())
        self.retheme()

    def _settings_button(self):
        return self._tool_button('Figure settings',self.edit_figure_settings)

    def set_spectrum(self, frame, peak_key='A', reset_view=True, sample_lookup=None):
        self.raw = frame.copy(deep=True)
        self.sample_lookup=sample_lookup
        self.peak_key=peak_key
        self._paper=None
        self._cursor_position=None
        self.cursor.hide()
        self.marker.clear()
        self.plot.setTitle('Optical response',color=self.colors['text'],size=f"{self.figure_style['title_pt']:g}pt")
        if frame.empty or not any(name in frame for name in ('wavelength_nm','angle_deg')):
            self.clear()
            return
        self.variable = 'angle_deg' if 'angle_deg' in frame and frame.angle_deg.nunique()>1 else 'wavelength_nm'
        if self.variable not in frame:self.variable='angle_deg'
        x = pd.to_numeric(frame[self.variable],errors='coerce').to_numpy(dtype=float)
        finite_x=x[np.isfinite(x)]
        self._full_xrange=(float(finite_x.min()),float(finite_x.max())) if len(finite_x) else None
        for key, curve in self.curves.items():
            y = pd.to_numeric(frame[key],errors='coerce').to_numpy(dtype=float) if key in frame else np.full(len(x),np.nan)
            curve.setData(x=x,y=y*100,connect='finite')
        self.plot.setLabel('bottom', 'Incidence angle (degrees)' if self.variable=='angle_deg' else 'Wavelength (nm)', color=self.colors['text'],size='10pt')
        if peak_key in frame:
            y = pd.to_numeric(frame[peak_key],errors='coerce').to_numpy(dtype=float)
            valid = np.isfinite(y)
            if valid.any():
                position = int(np.argmax(np.where(valid,y,-np.inf)))
                if np.isfinite(x[position]):self.marker.setData([x[position]],[y[position]*100])
        self.legend.clear()
        for key,name,_ in SERIES:self.legend.addItem(self.curves[key],name)
        if len(self.marker.points()):self.legend.addItem(self.marker,f'Highest sampled {peak_key}')
        self.apply_figure_style()
        if reset_view:self.fit_data()

    def fit_data(self):
        if getattr(self,'_full_xrange',None) is not None:
            self.plot.setXRange(*self._full_xrange,padding=.035)
        elif not self.raw.empty:
            x = pd.to_numeric(self.raw[self.variable],errors='coerce').to_numpy(dtype=float)
            finite = x[np.isfinite(x)]
            if len(finite):self.plot.setXRange(float(finite.min()),float(finite.max()),padding=.035)
        if hasattr(self,'plot'):self.plot.setYRange(0,100,padding=0)

    def set_mode(self, zoom):
        self.plot.getViewBox().setMouseMode(pg.ViewBox.RectMode if zoom else pg.ViewBox.PanMode)
        self.buttons['Zoom' if zoom else 'Pan'].setChecked(True)
        for name in ('Pan','Zoom'):
            button=self.buttons[name]
            button.setIcon(plot_icon(name,self.colors['accent'] if button.isChecked() else self.colors['text']))

    def nearest_sample(self, value):
        if self.raw.empty:return None
        lookup=getattr(self,'sample_lookup',None)
        if lookup is not None:return lookup.nearest_index(value,self.variable)
        x = pd.to_numeric(self.raw[self.variable],errors='coerce').to_numpy(dtype=float)
        distances = np.where(np.isfinite(x),np.abs(x-value),np.inf)
        return int(np.argmin(distances)) if np.isfinite(distances).any() else None

    def _load_visible_samples(self):
        lookup=getattr(self,'sample_lookup',None)
        if lookup is None or self.raw.empty or not lookup.path.is_file():return
        lo,hi=self.plot.getViewBox().viewRange()[0]
        frame=lookup.view_frame(lo,hi,self.variable)
        if frame.empty:return
        self.raw=frame
        self._paper=None
        x=frame[self.variable].to_numpy(dtype=float)
        for key,curve in self.curves.items():curve.setData(x=x,y=frame[key].to_numpy(dtype=float)*100,connect='finite')

    def select_sample(self, position, emit=True, move_cursor=True):
        if self.raw.empty:return
        lookup=getattr(self,'sample_lookup',None)
        position=max(0,min(int(position),len(lookup if lookup is not None else self.raw)-1))
        row=(pd.Series(lookup[position][1:],index=['wavelength_nm','angle_deg','R','T','A'])
             if lookup is not None else self.raw.iloc[position])
        x=pd.to_numeric(row[self.variable],errors='coerce')
        if move_cursor:
            self._cursor_position=float(x) if np.isfinite(x) else None
            self.cursor.setVisible(self._cursor_position is not None)
            if self._cursor_position is not None:self.cursor.setValue(self._cursor_position)
            self._paper=None
        values=[]
        for k in ('R','T','A'):
            value=pd.to_numeric(row.get(k),errors='coerce')
            if pd.notna(value) and np.isfinite(value):values.append(f'{k}: {value*100:.4f}%')
        self.full_readout=(f'{x:g} '+('°' if self.variable=='angle_deg' else 'nm')+' · ' if np.isfinite(x) else '')+' · '.join(values)
        self._elide_readout()
        if emit:self.sampleSelected.emit(position)

    def _elide_readout(self):
        self.readout.setText(self.readout.fontMetrics().elidedText(self.full_readout,Qt.TextElideMode.ElideRight,max(1,self.readout.width())))
        self.readout.setToolTip(self.full_readout)

    def _clicked(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return
        if self.plot.getViewBox().sceneBoundingRect().contains(event.scenePos()):
            point=self.plot.getViewBox().mapSceneToView(event.scenePos())
            position=self.nearest_sample(point.x())
            if position is not None:self.select_sample(position)

    def _hovered(self,point):
        if self.plot.getViewBox().sceneBoundingRect().contains(point):
            value=self.plot.getViewBox().mapSceneToView(point)
            self.view.setToolTip(f'{value.x():.8g} '+('°' if self.variable=='angle_deg' else 'nm')+f' · {value.y():.6g}%')

    def export_raw_csv(self,path):
        lookup=getattr(self,'sample_lookup',None)
        if lookup is not None:
            import shutil
            source=lookup.path.parent/'results.csv'
            if source.resolve()!=Path(path).resolve():shutil.copyfile(source,path)
        else:self.raw.to_csv(path,index=False)

    def clear(self):
        self.raw=pd.DataFrame()
        self.sample_lookup=None
        self._full_xrange=None
        self._paper=None
        self._cursor_position=None
        for curve in self.curves.values():curve.clear()
        self.marker.clear();self.cursor.hide()
        self.plot.setTitle('Results will appear here',color=self.colors['muted'],size='11pt')
        self.full_readout='';self.readout.clear()

    @property
    def figure(self):
        """Lazily create a paper figure; it is never embedded in the live widget."""
        if self._paper is None:
            if self._paper_factory is None:
                from qt_compute import spectrum_figure
                self._paper=spectrum_figure(self.raw,peak_key=self.peak_key)
            else:self._paper=self._paper_factory(self.raw,peak_key=self.peak_key)
            if self._cursor_position is not None and self._paper.axes:
                line=self._paper.axes[0].axvline(self._cursor_position,color='#a1bbc9',linestyle='--',linewidth=1)
                line.set_gid('sample-cursor')
            from qt_common import apply_plot_theme
            from publication_plot import apply_style
            apply_plot_theme(self._paper);apply_style(self._paper,self.figure_style)
        return self._paper

    def export_figure(self,path):
        from publication_plot import export_figure
        export_figure(self.figure,path,self.figure_style)

    def export_dialog(self):
        path,selected=QFileDialog.getSaveFileName(self,'Export publication figure','figure.pdf',
            'PDF vector (*.pdf);;SVG vector (*.svg);;PNG image (*.png);;TIFF image (*.tiff)')
        if path:
            if not Path(path).suffix:path+='.'+{'PDF':'pdf','SVG':'svg','PNG':'png','TIFF':'tiff'}[selected.split()[0]]
            try:
                self.export_figure(path)
                self._notify_action('Exported','Publication figure exported.',detail=str(path))
            except Exception as exc:QMessageBox.warning(self,'Figure export failed',str(exc))

    def apply_figure_style(self):
        style=self.figure_style
        for side in ('left','bottom'):
            font=QFont(style['font']);font.setPointSizeF(style['tick_pt'])
            self.plot.getAxis(side).setTickFont(font)
        # Physical paper dimensions apply to exports, never to the live layout.
        self.plot.titleLabel.setText(self.plot.titleLabel.text,size=f"{style['title_pt']:g}pt",color=self.colors['text'])
        for side in ('left','bottom'):
            axis=self.plot.getAxis(side)
            axis.setLabel(axis.labelText,color=self.colors['text'],size=f"{style['label_pt']:g}pt")
        self.legend.setLabelTextSize(f"{style['legend_pt']:g}pt")
        for curve in self.curves.values():
            pen=curve.opts['pen'];pen.setWidthF(style['line_pt']);curve.setPen(pen)

    def retheme(self,*_):
        from qt_common import theme_manager,COLORS
        self.colors=dict(COLORS[theme_manager().mode])
        theme_plot(self.plot,self.colors,percent=True)
        self.legend.setBrush(pg.mkBrush(self.colors['panel']))
        self.legend.setPen(pg.mkPen(self.colors['border']))
        self.legend.setLabelTextColor(self.colors['text'])
        for name,button in self.buttons.items():
            button.setIcon(plot_icon(name,self.colors['accent'] if button.isChecked() else self.colors['text']))
        self.toolbar.setStyleSheet(f'QToolButton {{background:transparent; border:1px solid transparent; padding:0; border-radius:5px;}} QToolButton:hover {{background:{self.colors["panel"]}; border-color:{self.colors["border"]};}} QToolButton:checked {{background:{self.colors["panel"]}; border-color:{self.colors["accent"]};}}')
        self.apply_figure_style()

    def _sync_paper_labels(self):
        axis=self.figure.axes[0]
        self.plot.setTitle(axis.get_title())
        self.plot.setLabel('left',axis.get_ylabel())
        self.plot.setLabel('bottom',axis.get_xlabel())
        self.legend.clear()
        for line,(key,name,color) in zip(axis.lines,SERIES):
            from matplotlib.colors import to_hex
            modes={'-':Qt.PenStyle.SolidLine,'--':Qt.PenStyle.DashLine,':':Qt.PenStyle.DotLine,'-.':Qt.PenStyle.DashDotLine}
            self.curves[key].setPen(pg.mkPen(to_hex(line.get_color()),width=line.get_linewidth(),style=modes.get(line.get_linestyle(),Qt.PenStyle.SolidLine)))
            self.legend.addItem(self.curves[key],line.get_label())
        if len(self.marker.points()):self.legend.addItem(self.marker,f'Highest sampled {self.peak_key}')
        self.apply_figure_style()

    def edit_figure_settings(self):
        # Reuse the established paper settings editor through an offscreen Figure
        # adapter, then explicitly apply its labels/fonts to the native view.
        from publication_plot import edit_settings
        owner=self
        class SettingsAdapter(QWidget):
            def __init__(self):
                super().__init__(owner)
                self.figure=owner.figure
                self.figure_style=dict(owner.figure_style)
                self.canvas=self
            def fit_canvas(self):
                owner.figure_style=dict(self.figure_style)
                owner._sync_paper_labels()
            def draw_idle(self):pass
        adapter=SettingsAdapter()
        try:edit_settings(adapter)
        finally:adapter.deleteLater()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'readout'):self._elide_readout()
