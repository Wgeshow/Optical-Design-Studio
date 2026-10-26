"""Native Qt rendering of scientific 2D figure definitions.

Matplotlib artists are a data/export description only. No Matplotlib Qt canvas
or rendered figure bitmap is used. Every live primitive is a PyQtGraph item or
a Qt vector path, with the original numeric arrays retained for inspection.
"""
import copy
import html
import inspect
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import numpy as np
from PyQt6.QtCore import QEvent, QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainterPath, QPen, QBrush
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy, QGraphicsScene
from PyQt6 import sip
from matplotlib.cbook import CallbackRegistry
from matplotlib.colors import to_rgba
from matplotlib.path import Path as MplPath
from matplotlib.collections import (QuadMesh, PathCollection, LineCollection,
                                    PolyCollection, PatchCollection)
from matplotlib.contour import ContourSet
from matplotlib.quiver import Quiver
from matplotlib.ticker import ScalarFormatter, PercentFormatter, FixedLocator, MultipleLocator, FixedFormatter

_local = Path(__file__).resolve().parent/'plot_dependencies'
if (_local/'pyqtgraph').is_dir() and str(_local) not in sys.path:
    sys.path.insert(0, str(_local))
import pyqtgraph as pg


def plain_text(value):
    value = str(value or '')
    substitutions = {r'\mu':'µ', r'\lambda':'λ', r'\theta':'θ', r'\phi':'φ',
                     r'\Delta':'Δ', r'\pi':'π', r'\times':'×', r'\infty':'∞'}
    for source, target in substitutions.items():
        value = value.replace(source, target)
    # Mathtext wrappers can contain nested braces, as in a log tick
    # \mathdefault{10^{-3}}. Unwrap balanced groups before flattening braces.
    wrapper = re.compile(r'\\(?:mathdefault|mathregular|mathrm|mathbf|operatorname)\{')
    while match := wrapper.search(value):
        start, end, depth = match.end(), match.end(), 1
        while end < len(value) and depth:
            depth += (value[end] == '{')-(value[end] == '}')
            end += 1
        if depth:
            break
        value = value[:match.start()]+value[start:end-1]+value[end:]
    value = value.replace('$', '').replace(r'\;', ' ').replace(r'\,', ' ')
    return value.replace('{', '').replace('}', '')


def qcolor(color, alpha=None):
    rgba = to_rgba(color)
    result = QColor.fromRgbF(*rgba)
    if alpha is not None:
        result.setAlphaF(float(alpha))
    return result


def native_font(text):
    font = QFont()
    font.setFamilies(text.get_fontfamily())
    font.setPointSizeF(float(text.get_fontsize()))
    weight = text.get_fontweight()
    font.setBold(weight in ('bold', 'heavy', 'black', 'semibold', 'demibold') or
                 isinstance(weight, (int, float)) and weight >= 600)
    font.setItalic(text.get_fontstyle() in ('italic', 'oblique'))
    return font


def label_style(text):
    font = native_font(text)
    return dict(family=font.family(), size=f'{font.pointSizeF():g}pt',
                bold=font.bold(), italic=font.italic())


def axis_label_style(text):
    style = label_style(text)
    return {'font-family':style['family'], 'font-size':style['size'],
            'font-weight':'bold' if style['bold'] else 'normal',
            'font-style':'italic' if style['italic'] else 'normal'}


def pen(color, width=1, linestyle='-', alpha=None):
    result = QPen(qcolor(color, alpha))
    result.setWidthF(float(width))
    result.setCosmetic(True)
    styles = {'--':Qt.PenStyle.DashLine, ':':Qt.PenStyle.DotLine,
              '-.':Qt.PenStyle.DashDotLine, 'None':Qt.PenStyle.NoPen,
              'none':Qt.PenStyle.NoPen, '':Qt.PenStyle.NoPen, ' ':Qt.PenStyle.NoPen}
    if isinstance(linestyle, tuple):
        offset, pattern = linestyle
        if pattern:
            # Matplotlib collection dash lengths are already scaled points;
            # QPen expresses dash lengths in multiples of its line width.
            divisor = max(float(width), 1e-12)
            result.setDashPattern([float(value)/divisor for value in pattern])
            result.setDashOffset(float(offset)/divisor)
    else:
        result.setStyle(styles.get(linestyle, Qt.PenStyle.SolidLine))
    return result


def native_path(path):
    result = QPainterPath()
    vertices = np.asarray(path.vertices)
    codes = path.codes
    if codes is None:
        codes = np.full(len(vertices), MplPath.LINETO, np.uint8)
        if len(codes):
            codes[0] = MplPath.MOVETO
    index = 0
    while index < len(vertices):
        code = codes[index]
        x, y = vertices[index]
        if not np.isfinite([x, y]).all():
            index += 1
            continue
        if code == MplPath.MOVETO:
            result.moveTo(float(x), float(y))
        elif code == MplPath.LINETO:
            result.lineTo(float(x), float(y))
        elif code == MplPath.CURVE3 and index+1 < len(vertices):
            end = vertices[index+1]
            result.quadTo(float(x), float(y), float(end[0]), float(end[1]))
            index += 1
        elif code == MplPath.CURVE4 and index+2 < len(vertices):
            control, end = vertices[index+1:index+3]
            result.cubicTo(float(x), float(y), float(control[0]), float(control[1]), float(end[0]), float(end[1]))
            index += 2
        elif code == MplPath.CLOSEPOLY:
            result.closeSubpath()
        index += 1
    result.setFillRule(Qt.FillRule.WindingFill)
    return result


class VectorPathItem(pg.GraphicsObject):
    """A Qt vector path in plot coordinates; no figure rasterization."""
    def __init__(self, path, edge, face=None):
        super().__init__()
        self.path = native_path(path)
        self.edge = edge
        self.face = QBrush(Qt.BrushStyle.NoBrush) if face is None else QBrush(face)
        bounds = self.path.boundingRect()
        epsilon = max(1., bounds.width(), bounds.height())*1e-7
        self._bounds = bounds.adjusted(-epsilon, -epsilon, epsilon, epsilon)

    def boundingRect(self):
        return self._bounds

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setPen(self.edge)
        painter.setBrush(self.face)
        painter.drawPath(self.path)


class SourceAxis(pg.AxisItem):
    def __init__(self, orientation, source_axis=None, norm=None, **kwargs):
        super().__init__(orientation=orientation, **kwargs)
        self.source_axis = source_axis
        self.norm = norm
        self.enableAutoSIPrefix(False)

    def tickValues(self, minVal, maxVal, size):
        source = self.source_axis
        locator = source.get_major_locator() if source is not None else None
        # Explicit source ticks carry scientific meaning (phase cycles,
        # categorical coordinates, chosen reference values). Forward their
        # positions as well as their formatter, rather than relabeling an
        # unrelated set of automatically chosen native tick positions.
        if self.norm is None and isinstance(locator, (FixedLocator, MultipleLocator)):
            try:
                bounds = sorted((minVal, maxVal))
                actual = [10**value for value in bounds] if source.get_scale() == 'log' else bounds
                ticks = np.asarray(locator.tick_values(*actual), dtype=float)
                ticks = ticks[np.isfinite(ticks)]
                if source.get_scale() == 'log':
                    ticks = np.log10(ticks[ticks > 0])
                tolerance = max(abs(bounds[1]-bounds[0]), abs(bounds[0]), abs(bounds[1]))*1e-12
                ticks = ticks[(ticks >= bounds[0]-tolerance) & (ticks <= bounds[1]+tolerance)]
                spacing = float(np.min(np.diff(ticks))) if len(ticks) > 1 else max(abs(bounds[1]-bounds[0]), 1.)
                return [(spacing, ticks.tolist())]
            except (ValueError, TypeError, OverflowError):
                pass
        return super().tickValues(minVal, maxVal, size)

    def tickStrings(self, values, scale, spacing):
        if self.norm is not None:
            return [f'{float(self.norm.inverse(value)):.4g}' for value in values]
        source = self.source_axis
        if source is None:
            return [f'{value:.5g}' for value in values]
        actual = [10**value if source.get_scale() == 'log' else value for value in values]
        formatter = source.get_major_formatter()
        if isinstance(formatter, ScalarFormatter):
            return [f'{value:.5g}' for value in actual]
        formatter = copy.copy(formatter)
        try:
            formatter.set_locs(actual)
            if isinstance(formatter, FixedFormatter) and isinstance(source.get_major_locator(), FixedLocator):
                locations = source.get_major_locator().locs
                result = []
                for value in actual:
                    index = next((index for index, location in enumerate(locations)
                                  if math.isclose(value, location, rel_tol=1e-12, abs_tol=0.)), None)
                    result.append(plain_text(formatter(value, index)) if index is not None else '')
                return result
            return [plain_text(formatter(value, index)) for index, value in enumerate(actual)]
        except (ValueError, TypeError, OverflowError):
            return [f'{value:.5g}' for value in actual]


class NativeFigureCanvas(QWidget):
    """Native 2D scene and a narrow Qt-backed event bridge for old callers."""
    unsupportedChanged = pyqtSignal(list)
    coordinateChanged = pyqtSignal(str)

    def __init__(self, figure=None, parent=None, colors=None):
        super().__init__(parent)
        self.figure = figure
        self.toolbar = None
        self.colors = colors or {}
        self.plots = {}
        self.axis_views = {}
        self.data_records = []
        self.unsupported_artists = []
        self.callbacks = CallbackRegistry()
        self._callbacks_by_key = {}
        self._links = []
        self._extra_views = []
        self._pending_draw = False
        self._rendering = False
        self._zoom_mode = False
        self._device_pixel_ratio = self.devicePixelRatioF()
        self.mouse_grabber = None
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(0, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setObjectName('nativePlotWarning')
        self.warning.hide()
        layout.addWidget(self.warning)
        self.view = pg.GraphicsLayoutWidget()
        # Charts rebuild vector items and linked views while nested splitters
        # resize. Qt's BSP scene index can retain an invalid entry during those
        # transitions (a Windows paint crash with sample markers plus curves).
        # These scenes contain a small number of aggregate scientific items;
        # linear item lookup avoids that stale index without changing datasets.
        self.view.scene().setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.view.setMinimumSize(0, 0)
        self.view.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.view.setBackground(None)
        self.view.setStyleSheet('background:transparent; border:0;')
        self.view.viewport().setAutoFillBackground(False)
        self.view.setFrameShape(self.view.Shape.NoFrame)
        self.view.viewport().installEventFilter(self)
        self.view.scene().sigMouseMoved.connect(self._mouse_moved)
        self.view.scene().sigMouseClicked.connect(self._mouse_clicked)
        layout.addWidget(self.view, 1)
        if figure is not None:
            self.set_figure(figure)

    @property
    def device_pixel_ratio(self):
        return self._device_pixel_ratio

    def mpl_connect(self, event, callback):
        # Repeated redraws register the same bound callback once.
        key = (event, callback)
        if key not in self._callbacks_by_key:
            self._callbacks_by_key[key] = self.callbacks.connect(event, callback)
        return self._callbacks_by_key[key]

    def mpl_disconnect(self, identifier):
        self.callbacks.disconnect(identifier)
        self._callbacks_by_key = {key:value for key,value in self._callbacks_by_key.items() if value != identifier}

    def get_width_height(self, physical=False):
        ratio = self.devicePixelRatioF() if physical else 1
        return round(self.width()*ratio), round(self.height()*ratio)

    def _event_at(self, position, name, button=None, gui_event=None):
        source = None
        point = None
        # Reverse order gives an independently scaled twin view priority.
        for axis, view in reversed(list(getattr(self, 'axis_views', {}).items())):
            if sip.isdeleted(view):
                continue
            if view.sceneBoundingRect().contains(position):
                source = axis
                point = view.mapSceneToView(position)
                break
        x = point.x() if point is not None else None
        y = point.y() if point is not None else None
        if source is not None:
            if source.get_xscale() == 'log':
                x = 10**x
            if source.get_yscale() == 'log':
                y = 10**y
        return SimpleNamespace(name=name, canvas=self, inaxes=source, xdata=x, ydata=y,
                               x=position.x(), y=self.height()-position.y(), button=button,
                               guiEvent=gui_event, key=None, dblclick=False, step=0)

    def _mouse_moved(self, position):
        event = self._event_at(position, 'motion_notify_event')
        self.callbacks.process('motion_notify_event', event)
        if event.inaxes is not None:
            self.coordinateChanged.emit(f'x={event.xdata:.6g} · y={event.ydata:.6g}')

    def _mouse_clicked(self, event):
        buttons = {Qt.MouseButton.LeftButton:1, Qt.MouseButton.MiddleButton:2, Qt.MouseButton.RightButton:3}
        self.callbacks.process('button_press_event', self._event_at(event.scenePos(), 'button_press_event', buttons.get(event.button()), event))

    def eventFilter(self, watched, event):
        view = getattr(self, 'view', None)
        if view is not None and not sip.isdeleted(view) and watched is view.viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            position = view.mapToScene(event.position().toPoint())
            buttons = {Qt.MouseButton.LeftButton:1, Qt.MouseButton.MiddleButton:2, Qt.MouseButton.RightButton:3}
            self.callbacks.process('button_release_event', self._event_at(position, 'button_release_event', buttons.get(event.button()), event))
        return super().eventFilter(watched, event)

    def draw_idle(self):
        if not self._pending_draw:
            self._pending_draw = True
            QTimer.singleShot(0, self._draw_pending)

    def _draw_pending(self):
        self._pending_draw = False
        self.draw()

    def draw(self):
        if self.figure is not None and not self._rendering:
            self.set_figure(self.figure, preserve_view=True)

    def _display_points(self, axis, points):
        result = np.asarray(points, dtype=float).copy()
        with np.errstate(divide='ignore', invalid='ignore'):
            if axis.get_xscale() == 'log':
                result[..., 0] = np.log10(result[..., 0])
            if axis.get_yscale() == 'log':
                result[..., 1] = np.log10(result[..., 1])
        return result

    def _data_path(self, axis, artist, path, transform=None):
        transform = transform or artist.get_transform()
        data = axis.transData.inverted().transform(transform.transform(path.vertices))
        return MplPath(self._display_points(axis, data), path.codes), data

    def _add(self, axis, item, artist, kind, **data):
        self.axis_views[axis].addItem(item)
        if isinstance(item, pg.PlotDataItem):
            item.setClipToView(True)
            item.setDownsampling(auto=item.opts.get('symbol') is None, method='peak')
        item.setZValue(float(artist.get_zorder()))
        self.data_records.append(dict(kind=kind, source_axis=axis, source_artist=artist, native_item=item, **data))
        return item

    def _optimize_views(self, enabled):
        for record in getattr(self, 'data_records', []):
            for item in [record.get('native_item'), *record.get('native_items', [])]:
                if isinstance(item, pg.PlotDataItem) and not sip.isdeleted(item):
                    item.setClipToView(enabled)
                    item.setDownsampling(auto=enabled and item.opts.get('symbol') is None, method='peak')

    def showEvent(self, event):
        super().showEvent(event)
        self._optimize_views(True)

    def hideEvent(self, event):
        # Hiding a tab does not detach its ViewBox. Preserve bounded rendering;
        # set_figure disables it only during actual scene teardown.
        super().hideEvent(event)

    def _line(self, axis, artist):
        raw_x = np.asarray(artist.get_xdata(orig=False)).copy()
        raw_y = np.asarray(artist.get_ydata(orig=False)).copy()
        raw = np.column_stack((raw_x, raw_y))
        data = axis.transData.inverted().transform(artist.get_transform().transform(raw))
        display = self._display_points(axis, data)
        marker = artist.get_marker()
        symbols = {'o':'o', '.':'o', ',':'o', 's':'s', '^':'t', 'v':'t1', '>':'t2', '<':'t3',
                   'd':'d', 'D':'d', '+':'+', 'x':'x', '*':'star', '|':'|', '_':'_'}
        symbol = symbols.get(marker)
        # Custom markers are native Qt paths in device-independent pixels.
        if marker not in (None, 'None', 'none', '', ' ') and symbol is None:
            from matplotlib.markers import MarkerStyle
            style = MarkerStyle(marker)
            symbol = native_path(style.get_path().transformed(style.get_transform()))
        item = pg.PlotDataItem(display[:,0], display[:,1], connect='finite',
                pen=pen(artist.get_color(), artist.get_linewidth(), artist.get_linestyle(), artist.get_alpha()),
                symbol=symbol, symbolSize=artist.get_markersize(),
                symbolPen=pen(artist.get_markeredgecolor(), artist.get_markeredgewidth(), alpha=artist.get_alpha()) if symbol is not None else None,
                symbolBrush=qcolor(artist.get_markerfacecolor(), artist.get_alpha()) if symbol is not None else None,
                autoDownsample=False, downsampleMethod='peak', clipToView=False)
        return self._add(axis, item, artist, 'line', raw_x=raw_x, raw_y=raw_y,
                         data_x=data[:,0].copy(), data_y=data[:,1].copy(), label=artist.get_label())

    def _mesh(self, axis, artist, coordinates, values, kind):
        coordinates = np.asarray(coordinates, dtype=float).copy()
        values = np.ma.asarray(values).copy()
        if values.ndim == 1:
            values = values.reshape(coordinates.shape[0]-1, coordinates.shape[1]-1)
        normalized = np.ma.asarray(artist.norm(values))
        normalized = np.ma.filled(normalized, np.nan).astype(float)
        cmap = artist.get_cmap()
        samples = np.linspace(0, 1, 256)
        colors = (np.asarray(cmap(samples))*255).round().astype(np.uint8)
        color_map = pg.ColorMap(samples, colors)
        display = self._display_points(axis, coordinates)
        item = pg.PColorMeshItem(display[:,:,0], display[:,:,1], normalized,
                                colorMap=color_map, levels=(0, 1), enableAutoLevels=False)
        if artist.get_alpha() is not None:
            item.setOpacity(float(artist.get_alpha()))
        return self._add(axis, item, artist, kind, values=values, coordinates=coordinates,
                  normalized_values=normalized.copy(), norm=artist.norm, cmap=cmap,
                  color_limits=artist.get_clim())

    def _image(self, axis, artist):
        values = np.ma.asarray(artist.get_array()).copy()
        left, right, bottom, top = artist.get_extent()
        x = np.linspace(left, right, values.shape[1]+1)
        y = np.linspace(bottom, top, values.shape[0]+1) if artist.origin == 'lower' else np.linspace(top, bottom, values.shape[0]+1)
        xx, yy = np.meshgrid(x, y)
        if values.ndim != 2:
            raise ValueError('RGB image definitions need an explicit native image data view.')
        item = self._mesh(axis, artist, np.stack((xx, yy), axis=-1), values, 'image')
        self.data_records[-1].update(origin=artist.origin, extent=tuple(artist.get_extent()))
        return item

    def _quiver(self, axis, artist):
        # Matplotlib's numeric arrow geometry calculation does not paint a
        # canvas. Preserve its scale/angles/units rather than guessing arrows.
        artist._init()
        arguments = (artist.U, artist.V, artist.angles)
        if len(inspect.signature(artist._make_verts).parameters) == 4:
            arguments = (artist.XY, *arguments)
        polygons = artist._make_verts(*arguments)
        offsets = artist.get_offset_transform().transform(artist.get_offsets())
        artist.update_scalarmappable()
        faces = artist.get_facecolors()
        native_items = []
        vertices = []
        for index, polygon in enumerate(polygons):
            if np.ma.is_masked(polygon) and np.ma.getmaskarray(polygon).any():
                continue
            screen = artist.get_transform().transform(polygon)+offsets[index]
            data = axis.transData.inverted().transform(screen)
            path = MplPath(self._display_points(axis, data), closed=True)
            item = VectorPathItem(path, pen('none'), qcolor(faces[index % len(faces)] if len(faces) else 'black', artist.get_alpha()))
            self.axis_views[axis].addItem(item)
            item.setZValue(artist.get_zorder())
            native_items.append(item)
            vertices.append(data.copy())
        self.data_records.append(dict(kind='quiver', source_axis=axis, source_artist=artist,
                                      native_items=native_items, x=np.asarray(artist.X).copy(), y=np.asarray(artist.Y).copy(),
                                      u=np.asarray(artist.U).copy(), v=np.asarray(artist.V).copy(),
                                      angles=artist.angles, scale=artist.scale, scale_units=artist.scale_units,
                                      vertices=vertices))

    def _collection(self, axis, artist):
        if isinstance(artist, QuadMesh):
            if getattr(artist, '_shading', 'flat') != 'flat':
                raise ValueError('Gouraud mesh interpolation is not yet a native mesh primitive.')
            return self._mesh(axis, artist, artist.get_coordinates(), artist.get_array(), 'mesh')
        if isinstance(artist, Quiver):
            self._quiver(axis, artist)
            return
        artist.update_scalarmappable()
        faces, edges = artist.get_facecolors(), artist.get_edgecolors()
        widths = artist.get_linewidths()
        linestyles = artist.get_linestyles()
        if isinstance(artist, PathCollection):
            offsets = np.asarray(artist.get_offsets())
            data = axis.transData.inverted().transform(artist.get_offset_transform().transform(offsets))
            display = self._display_points(axis, data)
            sizes = np.asarray(artist.get_sizes())
            paths = artist.get_paths()
            spots = []
            for index, point in enumerate(display):
                if not np.isfinite(point).all():
                    continue
                spots.append(dict(pos=point, size=np.sqrt(sizes[index % len(sizes)]) if len(sizes) else 6,
                    brush=qcolor(faces[index % len(faces)], artist.get_alpha()) if len(faces) else None,
                    pen=pen(edges[index % len(edges)], widths[index % len(widths)] if len(widths) else 1, alpha=artist.get_alpha()) if len(edges) else None,
                    symbol=native_path(paths[index % len(paths)]) if paths else 'o'))
            item = pg.ScatterPlotItem(spots=spots)
            return self._add(axis, item, artist, 'scatter', offsets=offsets.copy(), sizes=sizes.copy(),
                      raw_x=offsets[:,0].copy(), raw_y=offsets[:,1].copy(), data_x=data[:,0].copy(), data_y=data[:,1].copy())
        if isinstance(artist, LineCollection):
            segments = artist.get_segments()
            native_items = []
            for index, segment in enumerate(segments):
                path, data = self._data_path(axis, artist, MplPath(segment))
                item = VectorPathItem(path, pen(edges[index % len(edges)] if len(edges) else 'black',
                    widths[index % len(widths)] if len(widths) else 1,
                    linestyles[index % len(linestyles)] if len(linestyles) else '-', alpha=artist.get_alpha()))
                self.axis_views[axis].addItem(item)
                item.setZValue(artist.get_zorder())
                native_items.append(item)
            self.data_records.append(dict(kind='line_collection', source_axis=axis, source_artist=artist,
                                          segments=[np.asarray(value).copy() for value in segments], native_items=native_items,
                                          linestyles=copy.deepcopy(linestyles)))
            return
        if isinstance(artist, (PolyCollection, PatchCollection, ContourSet)):
            paths = artist.get_paths()
            native_items = []
            recorded = []
            for index, path in enumerate(paths):
                converted, data = self._data_path(axis, artist, path)
                edge = edges[index % len(edges)] if len(edges) else 'none'
                face = faces[index % len(faces)] if len(faces) else None
                item = VectorPathItem(converted, pen(edge, widths[index % len(widths)] if len(widths) else 1,
                                      linestyles[index % len(linestyles)] if len(linestyles) else '-', alpha=artist.get_alpha()),
                                      None if face is None else qcolor(face, artist.get_alpha()))
                self.axis_views[axis].addItem(item)
                item.setZValue(artist.get_zorder())
                native_items.append(item)
                recorded.append(data.copy())
            self.data_records.append(dict(kind='contour' if isinstance(artist, ContourSet) else 'polygons',
                source_axis=axis, source_artist=artist, paths=recorded, native_items=native_items,
                levels=np.asarray(artist.levels).copy() if isinstance(artist, ContourSet) else None,
                linestyles=copy.deepcopy(linestyles)))
            return
        raise ValueError('Unsupported collection '+type(artist).__name__)

    def _patch(self, axis, artist):
        path, data = self._data_path(axis, artist, artist.get_path())
        item = VectorPathItem(path, pen(artist.get_edgecolor(), artist.get_linewidth(), artist.get_linestyle(), artist.get_alpha()),
                              qcolor(artist.get_facecolor(), artist.get_alpha()) if artist.get_fill() else None)
        return self._add(axis, item, artist, 'patch', vertices=data.copy())

    def _text(self, axis, artist):
        text = plain_text(artist.get_text())
        if not text:
            return
        data = axis.transData.inverted().transform(artist.get_transform().transform(artist.get_position()))
        position = self._display_points(axis, data)
        anchor = ({'left':0, 'center':.5, 'right':1}.get(artist.get_ha(), .5),
                  {'top':0, 'center':.5, 'bottom':1, 'baseline':1, 'center_baseline':.5}.get(artist.get_va(), .5))
        item = pg.TextItem(text, color=qcolor(artist.get_color()), anchor=anchor, angle=float(artist.get_rotation()))
        item.setFont(native_font(artist))
        item.setPos(float(position[0]), float(position[1]))
        self._add(axis, item, artist, 'text', text=text, position=np.asarray(data).copy())
        arrow = getattr(artist, 'arrow_patch', None)
        if arrow is not None:
            self._patch(axis, arrow)
        return item

    def _unsupported(self, axis, artist, error):
        self.unsupported_artists.append(dict(axis_title=axis.get_title(), artist=type(artist).__name__, reason=str(error)))

    def _range(self, axis, view):
        xlim, ylim = axis.get_xlim(), axis.get_ylim()
        with np.errstate(divide='ignore', invalid='ignore'):
            x = np.log10(xlim) if axis.get_xscale() == 'log' else xlim
            y = np.log10(ylim) if axis.get_yscale() == 'log' else ylim
        padding = getattr(axis, '_ods_native_y_padding', 0.)
        if padding and axis.get_yscale() == 'linear':
            margin = abs(y[1]-y[0])*padding
            y = (y[0]-margin, y[1]+margin) if y[0] < y[1] else (y[0]+margin, y[1]-margin)
        view.invertX(xlim[1] < xlim[0])
        view.invertY(ylim[1] < ylim[0])
        view.setRange(xRange=sorted(x), yRange=sorted(y), padding=0)
        aspect = axis.get_aspect()
        if aspect == 'equal' or isinstance(aspect, (int, float)):
            view.setAspectLocked(True, ratio=1 if aspect == 'equal' else float(aspect))

    def _theme_axis(self, item):
        for side in ('left', 'right', 'bottom', 'top'):
            axis = item.getAxis(side)
            source = getattr(axis, 'source_axis', None)
            labels = source.get_ticklabels() if source is not None else []
            font = native_font(labels[0]) if labels else QFont()
            width = next(iter(source.axes.spines.values())).get_linewidth() if source is not None else .8
            axis.setPen(pg.mkPen(self.colors.get('border', '#3b5966'), width=width))
            axis.setTextPen(pg.mkPen(self.colors.get('muted', '#acc2d0')))
            axis.setTickFont(font)
            axis.enableAutoSIPrefix(False)
        item.setMenuEnabled(False)
        item.hideButtons()
        item.getViewBox().setBorder(pg.mkPen(self.colors.get('border', '#3b5966')))

    def _figure_grid(self, primary, twins, colorbar_axes, row_offset):
        """Keep each source colorbar bound to its declared subplot parents."""
        specs = [axis.get_subplotspec() for axis in primary]
        top = [spec.get_topmost_subplotspec() if spec is not None else None for spec in specs]
        candidates = [(spec.rowspan.start, spec.colspan.start, len(spec.rowspan), len(spec.colspan))
                      for spec in top if spec is not None]
        shapes = {spec.get_gridspec().get_geometry() for spec in top if spec is not None}
        if len(candidates) == len(primary) and len(set(candidates)) == len(primary) and len(shapes) == 1:
            cells = dict(zip(primary, candidates))
            rows, columns = next(iter(shapes))
        else:
            xs = sorted(set(round(axis.get_position().x0+axis.get_position().width/2, 5) for axis in primary))
            ys = sorted(set(round(axis.get_position().y0+axis.get_position().height/2, 5) for axis in primary), reverse=True)
            cells = {axis:(ys.index(round(axis.get_position().y0+axis.get_position().height/2, 5)),
                          xs.index(round(axis.get_position().x0+axis.get_position().width/2, 5)), 1, 1)
                     for axis in primary}
            rows, columns = max(1, len(ys)), max(1, len(xs))
        lanes, bars, horizontal = {}, [], []
        for axis in colorbar_axes:
            colorbar = axis._colorbar
            declared = getattr(axis, '_colorbar_info', {}).get('parents')
            if declared is None:
                declared = [colorbar.mappable.axes]
            parents = tuple(dict.fromkeys(parent for parent in declared if twins.get(parent, parent) in cells))
            owning = [cells[twins.get(parent, parent)] for parent in parents]
            first_row = min((cell[0] for cell in owning), default=0)
            end_row = max((cell[0]+cell[2] for cell in owning), default=rows)
            first_col = min((cell[1] for cell in owning), default=0)
            end_col = max((cell[1]+cell[3] for cell in owning), default=columns)
            bar = dict(source_axis=axis, parents=parents, shared=len(parents)>1,
                       first_row=first_row, end_row=end_row, first_col=first_col, end_col=end_col,
                       horizontal=colorbar.orientation == 'horizontal')
            if bar['horizontal']:
                horizontal.append(bar)
            else:
                group = first_col if end_col-first_col == 1 else None
                occupied = lanes.setdefault(group, [])
                lane = next((index for index, intervals in enumerate(occupied)
                             if all(end_row <= start or first_row >= end for start, end in intervals)), len(occupied))
                if lane == len(occupied):
                    occupied.append([])
                occupied[lane].append((first_row, end_row))
                bar.update(group=group, lane=lane)
            bars.append(bar)
        native_columns, cursor = {}, 0
        for column in range(columns):
            native_columns[column] = cursor
            cursor += 1+len(lanes.get(column, []))
        plot_cells = {axis:(cell[0]+row_offset, native_columns[cell[1]], cell[2],
                           native_columns[cell[1]+cell[3]-1]-native_columns[cell[1]]+1)
                      for axis, cell in cells.items()}
        for bar in bars:
            if bar['horizontal']:
                row = row_offset+rows+horizontal.index(bar)
                col = native_columns[bar['first_col']]
                span = native_columns[bar['end_col']-1]-col+1
                bar['grid_position'] = (row, col, 1, span)
            else:
                group = bar['group']
                col = cursor+bar['lane'] if group is None else native_columns[group]+1+bar['lane']
                bar['grid_position'] = (row_offset+bar['first_row'], col, bar['end_row']-bar['first_row'], 1)
        return plot_cells, bars, cursor+len(lanes.get(None, []))

    def set_figure(self, figure, colors=None, preserve_view=False):
        if self._rendering:
            return
        self._rendering = True
        old_ranges = {axis:view.viewRange() for axis,view in self.axis_views.items()} if preserve_view else {}
        try:
            self.figure = figure
            if colors is not None:
                self.colors = dict(colors)
            for view, handler in self._links:
                try:
                    view.sigResized.disconnect(handler)
                except (TypeError, RuntimeError):
                    pass
            self._links = []
            # A PlotDataItem briefly loses its ViewBox while Qt removes a
            # parent item. Disable view-dependent optimizations before that
            # transition; its raw scientific arrays are never changed.
            for record in self.data_records:
                for item in [record.get('native_item'), *record.get('native_items', [])]:
                    if isinstance(item, pg.PlotDataItem):
                        item.setClipToView(False)
                        item.setDownsampling(auto=False)
            for view in self._extra_views:
                view.clear()
                self.view.scene().removeItem(view)
                view.deleteLater()
            self._extra_views = []
            self.view.clear()
            self.plots = {}
            self.axis_views = {}
            self.data_records = []
            self.unsupported_artists = []
            colorbar_axes = [axis for axis in figure.axes if hasattr(axis, '_colorbar')]
            axes = [axis for axis in figure.axes if axis not in colorbar_axes and axis.get_visible()]
            primary = []
            twins = {}
            for axis in axes:
                if getattr(axis, 'name', '') == '3d':
                    self._unsupported(axis, axis, '3D data requires the typed native 3D viewport; it is never flattened.')
                    continue
                match = next((other for other in primary if np.allclose(axis.get_position().bounds, other.get_position().bounds, atol=1e-6)
                              and axis.get_shared_x_axes().joined(axis, other)), None)
                if match is None:
                    primary.append(axis)
                else:
                    twins[axis] = match
            has_title = figure._suptitle is not None and bool(figure._suptitle.get_text())
            row_offset = int(has_title)
            plot_cells, bar_specs, total_columns = self._figure_grid(primary, twins, colorbar_axes, row_offset)
            if has_title:
                self.view.addLabel(html.escape(plain_text(figure._suptitle.get_text())).replace('\n', '<br>'),
                                   row=0, col=0, colspan=max(1, total_columns), color=self.colors.get('text', '#ecf6fc'),
                                   **label_style(figure._suptitle))
            for axis in primary:
                row, col, rowspan, colspan = plot_cells[axis]
                plot = self.view.addPlot(row=row, col=col, rowspan=rowspan, colspan=colspan, axisItems={
                    'bottom':SourceAxis('bottom', axis.xaxis), 'left':SourceAxis('left', axis.yaxis)})
                self.plots[axis] = plot
                self.axis_views[axis] = plot.getViewBox()
                self._theme_axis(plot)
                plot.setTitle(html.escape(plain_text(axis.get_title())).replace('\n', '<br>'), color=self.colors.get('text', '#ecf6fc'), **label_style(axis.title))
                plot.setLabel('bottom', plain_text(axis.get_xlabel()), color=self.colors.get('text', '#ecf6fc'), **axis_label_style(axis.xaxis.label))
                plot.setLabel('left', plain_text(axis.get_ylabel()), color=self.colors.get('text', '#ecf6fc'), **axis_label_style(axis.yaxis.label))
                plot.getAxis('bottom').setLogMode(axis.get_xscale() == 'log')
                plot.getAxis('left').setLogMode(axis.get_yscale() == 'log')
                plot.showGrid(x=any(line.get_visible() for line in axis.get_xgridlines()),
                              y=any(line.get_visible() for line in axis.get_ygridlines()), alpha=.15)
                if not axis.axison:
                    plot.hideAxis('left')
                    plot.hideAxis('bottom')
                    plot.getViewBox().setBorder(None)
                self._range(axis, self.axis_views[axis])
            for axis, base in twins.items():
                plot = self.plots[base]
                plot.showAxis('right')
                right = SourceAxis('right', axis.yaxis)
                plot.setAxisItems({'right':right})
                right.setLabel(plain_text(axis.get_ylabel()), color=self.colors.get('text', '#ecf6fc'), **axis_label_style(axis.yaxis.label))
                right.setLogMode(axis.get_yscale() == 'log')
                view = pg.ViewBox()
                self._extra_views.append(view)
                plot.scene().addItem(view)
                right.linkToView(view)
                view.setXLink(plot.getViewBox())
                self.axis_views[axis] = view
                self.plots[axis] = plot
                updating = [False]
                def update_views(*_, secondary=view, base_view=plot.getViewBox(), updating=updating):
                    # sigResized emits its source ViewBox. Ignore that argument
                    # so it cannot replace the captured secondary view.
                    if updating[0]:
                        return
                    updating[0] = True
                    try:
                        # sceneBoundingRect includes the cosmetic border. The
                        # linked data view must share the exact inner rectangle
                        # or re-linking can shift its x range by one pixel.
                        geometry = base_view.mapRectToScene(base_view.rect())
                        if secondary.geometry() != geometry:
                            secondary.setGeometry(geometry)
                        secondary.linkedViewChanged(base_view, secondary.XAxis)
                    finally:
                        updating[0] = False
                plot.getViewBox().sigResized.connect(update_views)
                self._links.append((plot.getViewBox(), update_views))
                update_views()
                self._range(axis, view)
                self._theme_axis(plot)
            legend_items = {}
            legend_plots = {self.plots[axis] for axis in axes if axis in self.plots and axis.get_legend() is not None}
            for axis in axes:
                if axis not in self.axis_views:
                    continue
                items = []
                artists = [*axis.lines, *axis.images, *axis.collections, *axis.patches, *axis.texts, *axis.artists]
                for artist in artists:
                    if not artist.get_visible():
                        continue
                    try:
                        if artist in axis.lines:
                            item = self._line(axis, artist)
                        elif artist in axis.images:
                            item = self._image(axis, artist)
                        elif artist in axis.collections:
                            item = self._collection(axis, artist)
                        elif artist in axis.patches:
                            item = self._patch(axis, artist)
                        elif artist in axis.texts:
                            item = self._text(axis, artist)
                        else:
                            raise ValueError('Unsupported scientific artist '+type(artist).__name__)
                        label = artist.get_label()
                        if item is not None and label and not label.startswith('_'):
                            items.append((item, plain_text(label)))
                    except (ValueError, TypeError, AttributeError, IndexError, RuntimeError) as error:
                        self._unsupported(axis, artist, error)
                if self.plots[axis] in legend_plots:
                    legend_items.setdefault(self.plots[axis], []).extend(items)
            for plot, items in legend_items.items():
                source_legend = next(axis.get_legend() for axis in axes if self.plots.get(axis) is plot and axis.get_legend() is not None)
                source_texts = source_legend.get_texts()
                style = label_style(source_texts[0]) if source_texts else {}
                legend = plot.addLegend(offset=(8, 8), labelTextColor=self.colors.get('text', '#ecf6fc'), labelTextSize=style.get('size', '9pt'),
                                        brush=pg.mkBrush(self.colors.get('panel', '#112832')), pen=pg.mkPen(self.colors.get('border', '#3b5966')))
                for item, label in items:
                    legend.addItem(item, label)
                    legend.items[-1][1].setText(label, **style)
            self.colorbars = []
            for specification in bar_specs:
                axis = specification['source_axis']
                colorbar = axis._colorbar
                mappable = colorbar.mappable
                cmap = pg.ColorMap(np.linspace(0, 1, 256), (mappable.get_cmap()(np.linspace(0, 1, 256))*255).round().astype(np.uint8))
                bar = pg.ColorBarItem(values=(0, 1), colorMap=cmap,
                                      interactive=False, colorMapMenu=False, width=16,
                                      orientation='horizontal' if specification['horizontal'] else 'vertical')
                # The bar's gradient coordinate is normalized; its labels use
                # the exact inverse Normalize/LogNorm shared by the source map.
                side = 'bottom' if specification['horizontal'] else 'right'
                source_axis = axis.xaxis if specification['horizontal'] else axis.yaxis
                bar.getAxis(side).tickStrings = SourceAxis(side, norm=mappable.norm).tickStrings
                bar.getAxis(side).source_axis = source_axis
                bar.getAxis(side).setLabel(plain_text(axis.get_xlabel() if specification['horizontal'] else axis.get_ylabel()),
                    color=self.colors.get('text', '#ecf6fc'), **axis_label_style(source_axis.label))
                row, col, rowspan, colspan = specification['grid_position']
                self.view.addItem(bar, row=row, col=col, rowspan=rowspan, colspan=colspan)
                self._theme_axis(bar)
                self.colorbars.append(dict(source_axis=axis, native_item=bar, norm=mappable.norm, mappable=mappable,
                    parents=specification['parents'], shared=specification['shared'], grid_position=specification['grid_position']))
            for axis, ranges in old_ranges.items():
                if axis in self.axis_views:
                    if axis in twins:
                        self.axis_views[axis].setRange(yRange=ranges[1], padding=0)
                    else:
                        self.axis_views[axis].setRange(xRange=ranges[0], yRange=ranges[1], padding=0)
            message = '\n'.join(f'{item["artist"]}: {item["reason"]}' for item in self.unsupported_artists)
            self.warning.setText('Plot content needs attention: '+message if message else '')
            self.warning.setVisible(bool(message))
            self.unsupportedChanged.emit(self.unsupported_artists)
            self.set_mode(self._zoom_mode)
            self.view.viewport().update()
        finally:
            self._rendering = False

    def fit_data(self):
        for axis, view in self.axis_views.items():
            self._range(axis, view)

    def set_mode(self, zoom=False):
        self._zoom_mode = bool(zoom)
        for view in self.axis_views.values():
            view.setMouseMode(pg.ViewBox.RectMode if zoom else pg.ViewBox.PanMode)

