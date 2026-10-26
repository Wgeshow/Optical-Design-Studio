"""Linked native electrical volume, terminal-curve and provenance results.

The views display saved solver samples. The probe snaps to the nearest stored
grid coordinate; missing legacy quantities remain unavailable. Three-dimensional
rendering is a bounded native QPainter point cloud and requires no OpenGL.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import shutil
import zipfile

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib import colormaps
from PyQt6.QtCore import QPointF, QRectF, Qt, QSignalBlocker, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from qt_common import COLORS, PlotWidget, fill_table, table, theme_manager

QUANTITIES = (
    ('potential', 'Potential', 'V'),
    ('field_magnitude_V_m', 'Electric field |E|', 'V/m'),
    ('Ex_V_m', 'Electric field Ex', 'V/m'),
    ('Ey_V_m', 'Electric field Ey', 'V/m'),
    ('Ez_V_m', 'Electric field Ez', 'V/m'),
    ('electrons_cm3', 'Electrons n', 'cm⁻³'),
    ('holes_cm3', 'Holes p', 'cm⁻³'),
    ('electron_quasi_fermi_eV', 'Electron quasi-Fermi energy', 'eV'),
    ('hole_quasi_fermi_eV', 'Hole quasi-Fermi energy', 'eV'),
    ('charge_density_C_m3', 'Charge density ρ', 'C/m³'),
    ('epsilon_r', 'Static permittivity εr', '1'),
    ('donor_cm3', 'Donor concentration', 'cm⁻³'),
    ('acceptor_cm3', 'Acceptor concentration', 'cm⁻³'),
    ('current_density_magnitude_A_m2', 'Total current density |J|', 'A/m²'),
    ('electron_current_density_magnitude_A_m2', 'Electron current density |Jn|', 'A/m²'),
    ('hole_current_density_magnitude_A_m2', 'Hole current density |Jp|', 'A/m²'),
    ('Jx_A_m2', 'Total current density Jx', 'A/m²'),
    ('Jy_A_m2', 'Total current density Jy', 'A/m²'),
    ('Jz_A_m2', 'Total current density Jz', 'A/m²'),
    ('srh_recombination_cm3_s', 'SRH recombination / generation', 'cm⁻³/s'),
    ('impact_generation_cm3_s', 'Impact-ionization generation', 'cm⁻³/s'),
)
_QUANTITY_INFO = {key: (label, unit) for key, label, unit in QUANTITIES}


def saved_result_path(directory, value):
    """Resolve portable run-local copies first, including nested electrical data."""
    directory = Path(directory)
    if not value:
        return None
    candidate = Path(str(value))
    possible = [directory/candidate.name, directory/'electrical'/candidate.name]
    if not candidate.is_absolute():
        possible.insert(0, directory/candidate)
    else:
        possible.append(candidate)
    return next((path for path in possible if path.is_file()), None)


def load_electrical_volume(path):
    """Read numeric NPZ arrays without pickle and validate the rectilinear axes."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 512*1024*1024:
            raise ValueError('Electrical volume exceeds the 512 MiB preview limit.')
    with np.load(path, allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
    for key in ('x','y','z'):
        if key not in data:
            raise ValueError(f'Electrical volume is missing its {key} coordinate axis.')
        axis = np.asarray(data[key], dtype=float)
        if axis.ndim != 1 or not len(axis) or not np.isfinite(axis).all() or np.any(np.diff(axis) <= 0):
            raise ValueError(f'Electrical {key} coordinates must be finite, increasing one-dimensional samples.')
        data[key] = axis
    shape = tuple(len(data[key]) for key in ('x','y','z'))
    notes = []
    for key, _, _ in QUANTITIES:
        if key in data and (np.asarray(data[key]).shape != shape or not np.isfinite(np.asarray(data[key], dtype=float)).all()):
            notes.append(f'{key} is unavailable: saved array does not match the finite coordinate grid.')
            del data[key]
    if 'field_V_m' in data:
        field = np.asarray(data['field_V_m'], dtype=float)
        if field.shape == shape+(3,) and np.isfinite(field).all():
            data['field_magnitude_V_m'] = np.linalg.norm(field, axis=-1)
            for component, key in enumerate(('Ex_V_m','Ey_V_m','Ez_V_m')):
                data[key] = field[..., component]
        else:
            notes.append('Electric field is unavailable: saved vector array does not match the coordinate grid.')
            del data['field_V_m']
    if 'current_density_A_m2' in data:
        current=np.asarray(data['current_density_A_m2'],float)
        if current.shape==shape+(3,) and np.isfinite(current).all():
            data['current_density_magnitude_A_m2']=np.linalg.norm(current,axis=-1)
            for component,key in enumerate(('Jx_A_m2','Jy_A_m2','Jz_A_m2')):
                data[key]=current[...,component]
        else:
            notes.append('Current density is unavailable: saved vector array does not match the coordinate grid.')
            del data['current_density_A_m2']
    return data, notes


def nearest_grid_probe(data, coordinates_m):
    """Report the nearest stored sample, with both requested and actual position."""
    request = np.asarray(coordinates_m, dtype=float)
    if request.shape != (3,) or not np.isfinite(request).all():
        raise ValueError('Probe position must contain three finite coordinates in metres.')
    indices = tuple(int(np.argmin(np.abs(data[key]-request[index]))) for index, key in enumerate(('x','y','z')))
    shape = tuple(len(data[key]) for key in ('x','y','z'))
    values = {key: float(np.asarray(data[key])[indices]) for key, _, _ in QUANTITIES
              if key in data and np.asarray(data[key]).shape == shape}
    result = dict(indices=indices, requested_m=request.tolist(),
                  coordinates_m=[float(data[key][indices[index]]) for index, key in enumerate(('x','y','z'))], values=values)
    for index_key, ids_key, label in [('material_index','material_ids','material_id'),
                                     ('layer_index','layer_ids','layer_id'),
                                     ('contact_index','contact_ids','contact_id')]:
        if index_key in data and np.asarray(data[index_key]).shape == shape:
            value = int(np.asarray(data[index_key])[indices])
            if ids_key in data and 0 <= value < len(data[ids_key]):
                result[label] = str(data[ids_key][value])
    if 'solid' in data and np.asarray(data['solid']).shape == shape:
        result['solid'] = bool(data['solid'][indices])
    if 'layer_index' in data and np.asarray(data['layer_index']).shape == shape and 'layer_names' in data:
        layer_index=int(np.asarray(data['layer_index'])[indices])
        if 0<=layer_index<len(data['layer_names']):result['layer_name']=str(data['layer_names'][layer_index])
    return result


def export_volume_csv(path, data):
    """Export every saved grid sample with SI coordinates and explicit units."""
    shape = tuple(len(data[key]) for key in ('x','y','z'))
    fields = [key for key, _, _ in QUANTITIES if key in data and np.asarray(data[key]).shape == shape]
    extra = [key for key in ('cell_volumes_m3','layer_index','material_index','contact_index','solid')
             if key in data and np.asarray(data[key]).shape == shape]
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['x_m','y_m','z_m',*fields,*extra])
        for indices in np.ndindex(shape):
            coordinates = [float(data[key][indices[index]]) for index, key in enumerate(('x','y','z'))]
            values = [float(np.asarray(data[key])[indices]) for key in [*fields,*extra]]
            writer.writerow([*coordinates,*values])


def export_rectilinear_vtk(path, data):
    """Write legacy VTK RECTILINEAR_GRID with actual nonuniform SI coordinates.

    Saved arrays are grid sample values, so they are POINT_DATA. The solver's
    actual control-volume measure is exported as cell_volumes_m3 point metadata;
    no uniform spacing or interpolated cell values are invented.
    """
    shape = tuple(len(data[key]) for key in ('x','y','z'))
    fields = [key for key, _, _ in QUANTITIES if key in data and np.asarray(data[key]).shape == shape]
    fields += [key for key in ('cell_volumes_m3','epsilon_r','layer_index','material_index','contact_index','solid')
               if key not in fields and key in data and np.asarray(data[key]).shape == shape]
    with Path(path).open('w', encoding='utf-8', newline='\n') as stream:
        stream.write('# vtk DataFile Version 3.0\nElectrical solver samples; coordinates in metres\nASCII\nDATASET RECTILINEAR_GRID\n')
        stream.write('DIMENSIONS '+' '.join(str(n) for n in shape)+'\n')
        for key in ('x','y','z'):
            stream.write(f'{key.upper()}_COORDINATES {len(data[key])} double\n')
            stream.write(' '.join(f'{float(value):.17g}' for value in data[key])+'\n')
        stream.write(f'POINT_DATA {int(np.prod(shape))}\n')
        for key in fields:
            values = np.asarray(data[key], dtype=float)
            if not np.isfinite(values).all():
                continue
            stream.write(f'SCALARS {key} double 1\nLOOKUP_TABLE default\n')
            flat_values = values.ravel(order='F')
            for start in range(0, values.size, 8):
                stream.write(' '.join(f'{value:.17g}' for value in flat_values[start:start+8])+'\n')
        if 'field_V_m' in data:
            field = np.asarray(data['field_V_m'], dtype=float)
            if field.shape == shape+(3,) and np.isfinite(field).all():
                stream.write('VECTORS electric_field_V_m double\n')
                flat = np.column_stack([field[..., component].ravel(order='F') for component in range(3)])
                for values in flat:
                    stream.write(' '.join(f'{value:.17g}' for value in values)+'\n')


def _recorded_curve_model(computed, metadata=None):
    """Use the saved study description, then the models recorded per CSV row."""
    model=(metadata or {}).get('model')
    if isinstance(model,str) and model.strip():return model.strip()
    if computed is not None and not computed.empty and 'model' in computed:
        values=[str(value).strip() for value in computed['model'].dropna().unique() if str(value).strip()]
        if values:return '; '.join(values)
    return ''


def saved_result_model_labels(summary,study_info=None,iv_data=None,cv_data=None,*,has_optical_fields=False):
    """Keep every results readout consistent with the saved calculation.

    Missing legacy model records remain unknown. A current CSV by itself is
    not evidence that its values came from the frozen-conductivity estimator.
    """
    study_info=study_info if isinstance(study_info,dict) else {}
    studies=study_info.get('studies',{})
    studies=studies if isinstance(studies,dict) else {}
    metadata={kind:studies.get(kind,{}) if isinstance(studies.get(kind,{}),dict) else {} for kind in ('iv','cv')}
    options=summary.get('options',{})
    options=options if isinstance(options,dict) else {}
    transport=metadata['iv'].get('transport') or options.get('transport',{})
    transport=transport if isinstance(transport,dict) else {}
    mode=transport.get('mode')
    semiconductor=bool(summary.get('semiconductor_current_predicted')) or mode=='semiconductor_dd'
    leakage=mode=='dielectric_leakage'
    current=_recorded_curve_model(iv_data,metadata['iv'])
    if not current:
        cached=summary.get('dielectric_leakage',{})
        if isinstance(cached,dict):current=_recorded_curve_model(None,cached.get('metadata',{}))
    if not current:
        current=('Self-consistent semiconductor drift diffusion' if semiconductor else
                 'Sourced dielectric leakage' if leakage else 'Saved current (model not recorded)')
    if semiconductor:
        details=[]
        statistics={'boltzmann':'Boltzmann','fermi_dirac':'Fermi–Dirac'}.get(transport.get('statistics'))
        if statistics and statistics not in current:details.append(statistics)
        interface=transport.get('heterojunction')
        if isinstance(interface,dict) and interface.get('model')=='ideal_quasi_fermi' and 'ideal quasi-Fermi interface' not in current:
            details.append('ideal quasi-Fermi interface')
        if details:current+=' · '+' · '.join(details)
    capacitance=_recorded_curve_model(cv_data,metadata['cv']) or (
        'Self-consistent DC electrode displacement-charge derivative' if semiconductor else 'Electrode displacement-charge derivative')
    has_current=iv_data is not None and not iv_data.empty
    has_capacitance=cv_data is not None and not cv_data.empty
    model=summary.get('model')
    if model=='optical_only':
        run_model='Saved S4 E/H phasor fields' if has_optical_fields else 'Periodic optical solve'
    elif semiconductor:
        run_model=current
    elif leakage:
        run_model='Electrostatic Poisson + '+current
    else:
        run_model={'custom_device':'Electrostatic Poisson','explicit_ito':'Explicit ITO electrostatics',
            'contacts_only_sheet':'Contact and ITO sheet electrostatics'}.get(model,model or 'Saved electrical result')
        if has_current:run_model+=' · '+current
    return dict(run_model=run_model,iv_model=current,cv_model=capacitance,
        iv_scope=current if has_current else 'No saved current study',
        cv_scope=capacitance if has_capacitance else 'No saved capacitance study')


def terminal_curve_figure(computed, measured, kind='iv', metadata=None):
    """Show recorded terminal values, keeping measured and model curves distinct."""
    figure = Figure(figsize=(7, 4), layout='constrained')
    axis = figure.add_subplot(111)
    column, label = ('current_A','Current (A)') if kind == 'iv' else ('capacitance_F','Capacitance (F)')
    metadata = metadata or {}
    computed_label = _recorded_curve_model(computed,metadata) or ('Saved current (model not recorded)' if kind == 'iv' else 'Electrode charge derivative')
    for frame, legend, style in [(computed, computed_label, '-o'), (measured, 'User supplied measured curve', '--s')]:
        if frame is None or frame.empty or column not in frame:
            continue
        xkey = 'terminal_voltage_V' if 'terminal_voltage_V' in frame else 'bias_V'
        if xkey not in frame:
            continue
        x = pd.to_numeric(frame[xkey], errors='coerce').to_numpy(float)
        y = pd.to_numeric(frame[column], errors='coerce').to_numpy(float)
        keep = np.isfinite(x)
        order = np.argsort(x[keep])
        if np.any(keep&np.isfinite(y)):
            # Invalid physical-domain samples remain NaN gaps. Dropping them
            # would draw a fabricated current through an unavailable regime.
            axis.plot(x[keep][order], y[keep][order], style, label=legend, markersize=4, linewidth=1.7)
    axis.set_xlabel('Swept terminal voltage (V)')
    axis.set_ylabel(label)
    axis.grid(alpha=.2)
    if axis.lines:
        axis.legend(fontsize=8)
    else:
        axis.text(.5,.5,'No saved '+('I–V' if kind=='iv' else 'C–V')+' samples are available.',
                  ha='center', va='center', transform=axis.transAxes)
    return figure


def _axis_edges(axis):
    axis = np.asarray(axis, dtype=float)
    if len(axis) == 1:
        span = max(abs(float(axis[0]))*.01, 1e-9)
        return np.array([axis[0]-span/2, axis[0]+span/2])
    mid = (axis[:-1]+axis[1:])/2
    return np.r_[axis[0]-(mid[0]-axis[0]), mid, axis[-1]+(axis[-1]-mid[-1])]


class _FieldColors:
    def __init__(self, values, logarithmic=False):
        self.logarithmic = logarithmic
        values = np.asarray(values, dtype=float)
        if logarithmic:
            positive = values[values > 0]
            self.low = float(np.log10(positive.min())) if positive.size else 0.
            self.high = float(np.log10(positive.max())) if positive.size else 1.
            self.cmap = colormaps['viridis']
        else:
            self.low = float(values.min())
            self.high = float(values.max())
            if self.low < 0 < self.high:
                bound = max(abs(self.low), abs(self.high))
                self.low, self.high = -bound, bound
                self.cmap = colormaps['coolwarm']
            else:
                self.cmap = colormaps['viridis']
        self.span = max(self.high-self.low, abs(self.high)*1e-15, 1e-300)
        palette = self.cmap(np.linspace(0,1,256))
        self.palette = [QColor(round(r*255),round(g*255),round(b*255)) for r,g,b,_ in palette]
        self.translucent_palette = [QColor(round(r*255),round(g*255),round(b*255),205) for r,g,b,_ in palette]

    def color(self, value, alpha=255):
        if self.logarithmic:
            if value <= 0:
                return QColor('#34424f')
            value = math.log10(value)
        index = max(0,min(255,int((value-self.low)/self.span*255)))
        return self.translucent_palette[index] if alpha == 205 else self.palette[index]

    def range_text(self):
        low, high = (10**self.low, 10**self.high) if self.logarithmic else (self.low,self.high)
        return f'{low:.4g} … {high:.4g}'+(' (log color)' if self.logarithmic else '')


class ElectricalSliceCanvas(QWidget):
    positionPicked = pyqtSignal(float, float)

    def __init__(self, plane='xy', parent=None):
        super().__init__(parent)
        self.plane = plane
        self.axes = None
        self.values = None
        self.colors = None
        self.crosshair = None
        self.title = 'Top XY view' if plane == 'xy' else 'Cross-section XZ view'
        self.setMinimumSize(240, 195)
        self.setMouseTracking(True)

    def set_field(self, first, second, values, colors, crosshair, title):
        self.axes = (np.asarray(first), np.asarray(second))
        self.values = np.asarray(values)
        self.colors = colors
        self.crosshair = crosshair
        self.title = title
        self.update()

    def clear(self, message='No saved volume is available.'):
        self.axes = self.values = self.colors = self.crosshair = None
        self.title = message
        self.update()

    def _plot_bounds(self):
        return QRectF(55,35,max(1,self.width()-77),max(1,self.height()-78))

    def paintEvent(self, _):
        painter = QPainter(self)
        colors = COLORS[theme_manager().mode]
        painter.fillRect(self.rect(), QColor(colors['field']))
        painter.setPen(QColor(colors['text']))
        painter.drawText(QRectF(10,5,self.width()-20,25), Qt.AlignmentFlag.AlignCenter, self.title)
        if self.values is None:
            painter.setPen(QColor(colors['muted']))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Unavailable')
            return
        rect = self._plot_bounds()
        a,b = self.axes
        ea,eb = _axis_edges(a),_axis_edges(b)
        sa,sb = ea[-1]-ea[0],eb[-1]-eb[0]
        # Cell colors represent saved samples on the real nonuniform axes.
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(len(a)):
            left = rect.left()+(ea[i]-ea[0])/sa*rect.width()
            width = (ea[i+1]-ea[i])/sa*rect.width()
            for j in range(len(b)):
                top = rect.top()+(eb[j]-eb[0])/sb*rect.height()
                height = (eb[j+1]-eb[j])/sb*rect.height()
                painter.fillRect(QRectF(left,top,width+.6,height+.6),self.colors.color(float(self.values[i,j])))
        painter.setPen(QPen(QColor('#ffffff'),1,Qt.PenStyle.DashLine))
        if self.crosshair is not None:
            x = rect.left()+(self.crosshair[0]-ea[0])/sa*rect.width()
            y = rect.top()+(self.crosshair[1]-eb[0])/sb*rect.height()
            painter.drawLine(QPointF(x,rect.top()),QPointF(x,rect.bottom()))
            painter.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
        painter.setPen(QColor(colors['muted']))
        painter.drawText(QRectF(rect.left(),rect.bottom()+5,rect.width(),20),Qt.AlignmentFlag.AlignCenter,
                         f'x: {a[0]*1e6:.4g} … {a[-1]*1e6:.4g} µm')
        painter.save()
        painter.translate(15,rect.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-rect.height()/2,0,rect.height(),22),Qt.AlignmentFlag.AlignCenter,
                         f'{"y" if self.plane=="xy" else "z"}: {b[0]*1e6:.4g} … {b[-1]*1e6:.4g} µm')
        painter.restore()
        painter.drawRect(rect)

    def mousePressEvent(self, event):
        if self.axes is not None and self._plot_bounds().contains(event.position()):
            rect = self._plot_bounds()
            ea,eb = [_axis_edges(axis) for axis in self.axes]
            first = ea[0]+(event.position().x()-rect.left())/rect.width()*(ea[-1]-ea[0])
            second = eb[0]+(event.position().y()-rect.top())/rect.height()*(eb[-1]-eb[0])
            self.positionPicked.emit(float(first),float(second))
        super().mousePressEvent(event)


class ElectricalField3DCanvas(QWidget):
    """Orbitable color samples; limit rendering cost while retaining real values."""
    positionPicked = pyqtSignal(float,float,float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(280,250)
        self.yaw = -35.
        self.pitch = 24.
        self.zoom = 1.
        self.points = np.empty((0,3))
        self.coordinates_m = np.empty((0,3))
        self.values = np.empty(0)
        self.projected = np.empty((0,2))
        self.colors = None
        self.cursor = None
        self.title = '3D saved field samples'
        self._drag_start = self._last_mouse = None
        self.total_samples = 0

    def set_field(self, data, values, colors, cursor, title):
        axes = [data[key] for key in ('x','y','z')]
        shape = values.shape
        total = values.size
        indices = np.linspace(0,total-1,min(total,10000),dtype=int)
        solid = np.asarray(data.get('solid',np.ones(shape,bool)))
        if solid.shape == shape:
            indices = indices[solid.ravel()[indices].astype(bool)]
        locations = np.column_stack(np.unravel_index(indices,shape))
        coordinates = np.column_stack([axes[axis][locations[:,axis]] for axis in range(3)])
        center = np.array([(axis[0]+axis[-1])/2 for axis in axes])
        span = np.array([max(float(axis[-1]-axis[0]),1e-12) for axis in axes])
        self.points = (coordinates-center)/span
        self.coordinates_m = coordinates
        self.projected = np.empty((0,2))
        self.values = np.asarray(values).ravel()[indices]
        self.colors = colors
        self.cursor = (np.asarray(cursor)-center)/span
        self.title = title
        self.total_samples = total
        self.update()

    def clear(self, message='No saved volume is available.'):
        self.points = np.empty((0,3)); self.values = np.empty(0)
        self.coordinates_m = np.empty((0,3)); self.projected = np.empty((0,2))
        self.total_samples = 0
        self.cursor = None; self.title = message
        self.update()

    def _project(self, points):
        y,p = np.deg2rad([self.yaw,self.pitch])
        yaw = np.array([[np.cos(y),-np.sin(y),0],[np.sin(y),np.cos(y),0],[0,0,1]])
        pitch = np.array([[1,0,0],[0,np.cos(p),-np.sin(p)],[0,np.sin(p),np.cos(p)]])
        rotated = np.asarray(points)@yaw.T@pitch.T
        scale = max(1,min(self.width()-70,self.height()-110))*.62*self.zoom
        screen = rotated[:,:2]*scale
        screen[:,0] += self.width()/2
        screen[:,1] += self.height()/2-10
        return screen,rotated[:,2]

    def paintEvent(self, _):
        painter = QPainter(self)
        theme = COLORS[theme_manager().mode]
        painter.fillRect(self.rect(),QColor(theme['field']))
        painter.setPen(QColor(theme['text']))
        painter.drawText(QRectF(8,5,self.width()-16,28),Qt.AlignmentFlag.AlignCenter,self.title)
        if not len(self.points):
            painter.setPen(QColor(theme['muted']))
            painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'Unavailable')
            return
        projected,depth = self._project(self.points)
        self.projected = projected
        painter.setPen(Qt.PenStyle.NoPen)
        radius = max(1.2,min(3.,120/math.sqrt(len(self.points))))
        for index in np.argsort(depth):
            painter.setBrush(self.colors.color(float(self.values[index]),205))
            painter.drawEllipse(QPointF(*projected[index]),radius,radius)
        corners = np.array([[x,y,z] for x in (-.5,.5) for y in (-.5,.5) for z in (-.5,.5)])
        corner_screen,_ = self._project(corners)
        painter.setPen(QPen(QColor(theme['border']),1))
        for i in range(8):
            for j in range(i+1,8):
                if np.count_nonzero(corners[i]!=corners[j]) == 1:
                    painter.drawLine(QPointF(*corner_screen[i]),QPointF(*corner_screen[j]))
        if self.cursor is not None:
            # The linked slice locations are coordinate planes through the
            # actual nearest grid sample, not fitted or interpolated surfaces.
            from PyQt6.QtGui import QPolygonF
            for plane in (np.array([[-.5,-.5,self.cursor[2]],[.5,-.5,self.cursor[2]],
                                    [.5,.5,self.cursor[2]],[-.5,.5,self.cursor[2]]]),
                          np.array([[-.5,self.cursor[1],-.5],[.5,self.cursor[1],-.5],
                                    [.5,self.cursor[1],.5],[-.5,self.cursor[1],.5]])):
                plane_screen,_ = self._project(plane)
                painter.setBrush(QColor(40,168,250,15))
                painter.setPen(QPen(QColor(theme['accent']),1,Qt.PenStyle.DashLine))
                painter.drawPolygon(QPolygonF([QPointF(*point) for point in plane_screen]))
            cursor,_ = self._project(self.cursor[None,:])
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor('#ffffff'),2))
            painter.drawEllipse(QPointF(*cursor[0]),7,7)
        axis_endpoints,_ = self._project(np.array([[-.5,-.5,-.5],[.5,-.5,-.5],[-.5,.5,-.5],[-.5,-.5,.5]]))
        for label,position in zip(('X','Y','Z'),axis_endpoints[1:]):
            painter.setPen(QColor(theme['text']))
            painter.drawText(QPointF(position[0]+5,position[1]-4),label)
        painter.setPen(QColor(theme['muted']))
        painter.drawText(QRectF(8,self.height()-39,self.width()-16,34),Qt.AlignmentFlag.AlignCenter,
                         f'{len(self.points):,} sampled points / {self.total_samples:,} grid samples\nDrag to orbit · wheel to zoom · click to probe · independent axis scale')

    def mousePressEvent(self, event):
        self._drag_start = self._last_mouse = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._last_mouse is not None and event.buttons()&Qt.MouseButton.LeftButton:
            delta = event.position()-self._last_mouse
            self.yaw += delta.x()*.6
            self.pitch = max(-85,min(85,self.pitch+delta.y()*.6))
            self._last_mouse = event.position()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_start is not None and (event.position()-self._drag_start).manhattanLength() < 5 and len(self.projected):
            distances = np.linalg.norm(self.projected-np.array([event.position().x(),event.position().y()]),axis=1)
            index = int(np.argmin(distances))
            if distances[index] < 16:
                self.positionPicked.emit(*[float(value) for value in self.coordinates_m[index]])
        self._last_mouse = self._drag_start = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self.zoom = max(.3,min(3.,self.zoom*1.15**(event.angleDelta().y()/120)))
        self.update()
        event.accept()


class ElectricalResultsPanel(QWidget):
    """Reusable saved-result dashboard; call set_result(directory, summary)."""
    probeChanged = pyqtSignal(dict)
    biasChanged = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.directory = None
        self.summary = {}
        self.volume = None
        self.volume_path = None
        self.cursor_indices = (0,0,0)
        self.probe = {}
        self._result_rows = []
        self._colors = None
        self.study_info = {}
        self.iv_data = self.cv_data = self.measured_iv_data = self.measured_cv_data = pd.DataFrame()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8)
        self.summary_label = QLabel('Run or open an electrical simulation to inspect its saved fields.')
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('Bias'))
        self.result_bias = QComboBox()
        self.result_bias.setMinimumWidth(105)
        controls.addWidget(self.result_bias)
        controls.addWidget(QLabel('Quantity'))
        self.quantity = QComboBox()
        for key,label,unit in QUANTITIES:
            self.quantity.addItem(f'{label} [{unit}]',key)
        controls.addWidget(self.quantity,1)
        self.log_colors = QCheckBox('Log color scale')
        controls.addWidget(self.log_colors)
        self.range_label = QLabel('')
        controls.addWidget(self.range_label)
        layout.addLayout(controls)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs,1)

        fields = QWidget(); field_layout = QVBoxLayout(fields)
        field_layout.setContentsMargins(0,4,0,0)
        linked = QSplitter()
        slices = QWidget(); slice_layout = QVBoxLayout(slices); slice_layout.setContentsMargins(0,0,0,0)
        self.top_view = ElectricalSliceCanvas('xy')
        self.cross_view = ElectricalSliceCanvas('xz')
        slice_layout.addWidget(self.top_view,1); slice_layout.addWidget(self.cross_view,1)
        linked.addWidget(slices)
        self.volume_view = ElectricalField3DCanvas()
        linked.addWidget(self.volume_view)
        linked.setSizes([480,600])
        field_layout.addWidget(linked,1)
        cursor = QHBoxLayout()
        cursor.addWidget(QLabel('Nearest sample probe'))
        self.cursor_controls = {}
        for key in ('x','y','z'):
            cursor.addWidget(QLabel(key))
            control = QDoubleSpinBox()
            control.setDecimals(8); control.setRange(-1e9,1e9); control.setSuffix(' µm')
            control.setKeyboardTracking(False)
            control.valueChanged.connect(self._cursor_changed)
            self.cursor_controls[key] = control
            cursor.addWidget(control)
        field_layout.addLayout(cursor)
        self.probe_label = QLabel('Probe unavailable')
        self.probe_label.setWordWrap(True)
        self.probe_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        field_layout.addWidget(self.probe_label)
        self.tabs.addTab(fields,'Linked fields')

        self.iv_plot = PlotWidget(); self.cv_plot = PlotWidget()
        self.iv_scope = QLabel(''); self.cv_scope = QLabel('')
        self.iv_scope.setWordWrap(True); self.cv_scope.setWordWrap(True)
        for label,plot,scope in [('I–V',self.iv_plot,self.iv_scope),('C–V',self.cv_plot,self.cv_scope)]:
            page = QWidget(); page_layout = QVBoxLayout(page)
            page_layout.addWidget(scope); page_layout.addWidget(plot,1)
            self.tabs.addTab(page,label)

        self.checks_table = table(['Bias (V)','Poisson residual','Relative Gauss balance','Iterations'])
        self.tabs.addTab(self.checks_table,'Mesh and checks')
        self.sources = QPlainTextEdit(); self.sources.setReadOnly(True)
        self.inputs = QPlainTextEdit(); self.inputs.setReadOnly(True)
        self.run_details = QPlainTextEdit(); self.run_details.setReadOnly(True)
        self.tabs.addTab(self.sources,'Material sources')
        self.tabs.addTab(self.inputs,'Saved inputs')
        self.tabs.addTab(self.run_details,'Run summary')

        exports = QHBoxLayout()
        self.export_npz_button = QPushButton('Export volume NPZ')
        self.export_csv_button = QPushButton('Export grid CSV')
        self.export_vtk_button = QPushButton('Export VTK')
        self.export_figure_button = QPushButton('Export figure')
        for button,kind in [(self.export_npz_button,'npz'),(self.export_csv_button,'csv'),
                            (self.export_vtk_button,'vtk'),(self.export_figure_button,'figure')]:
            button.clicked.connect(lambda _, k=kind:self.export_dialog(k))
            exports.addWidget(button)
        exports.addStretch(1)
        layout.addLayout(exports)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.result_bias.currentIndexChanged.connect(self._bias_changed)
        self.quantity.currentIndexChanged.connect(self.redraw)
        self.log_colors.toggled.connect(self.redraw)
        self.top_view.positionPicked.connect(self._pick_xy)
        self.cross_view.positionPicked.connect(self._pick_xz)
        self.volume_view.positionPicked.connect(self.set_probe)
        theme_manager().changed.connect(self.redraw)
        self._update_exports()

    def _update_exports(self):
        ready = self.volume is not None
        for button in (self.export_npz_button,self.export_csv_button,self.export_vtk_button):
            button.setEnabled(ready)
        self.export_figure_button.setEnabled(ready or not self.iv_data.empty or not self.cv_data.empty or not self.measured_iv_data.empty or not self.measured_cv_data.empty)

    def set_result(self, directory, summary):
        if not isinstance(summary,dict) or not isinstance(summary.get('results'),list):
            raise ValueError('Electrical results require a saved summary with a results list.')
        self.directory = Path(directory)
        self.summary = summary
        self._result_rows = summary['results']
        self.volume = self.volume_path = None
        with QSignalBlocker(self.result_bias):
            self.result_bias.clear()
            for index,row in enumerate(self._result_rows):
                bias = float(row['bias_V'])
                if not math.isfinite(bias):
                    raise ValueError('Saved bias values must be finite.')
                self.result_bias.addItem(f'{bias:g} V',index)
        self._load_studies()
        self.summary_label.setText(self._summary_text(self.result_model_labels['run_model']))
        self._metadata()
        self._bias_changed()

    def _summary_text(self,model):
        shape = self.summary.get('mesh',{}).get('shape')
        elapsed = self.summary.get('elapsed_s')
        text = f'{model} · {len(self._result_rows)} saved bias states'
        if shape:
            text += ' · mesh '+' × '.join(str(n) for n in shape)
        if isinstance(elapsed,(float,int)):
            text += f' · {elapsed:.3g} s'
        return text

    def _load_studies(self):
        self.study_info = self.summary.get('terminal_studies',{})
        if not isinstance(self.study_info,dict):
            self.study_info = {}
        path = saved_result_path(self.directory,self.summary.get('study_summary_json','electrical_study_summary.json'))
        if path:
            try:
                self.study_info = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(self.study_info,dict):
                    raise ValueError('Terminal study metadata must be an object.')
            except (OSError,ValueError) as exc:
                self.study_info = {}
                self.status.setText(f'Terminal study metadata could not be read: {exc}')
        def frame(value, default):
            path = saved_result_path(self.directory,value or default)
            if not path:
                return pd.DataFrame()
            try:
                return pd.read_csv(path)
            except (OSError,ValueError,pd.errors.EmptyDataError) as exc:
                self.status.setText(f'Saved terminal curve could not be read: {exc}')
                return pd.DataFrame()
        self.iv_data = frame(self.study_info.get('iv_csv') or self.summary.get('iv_csv'),'electrical_iv.csv')
        self.cv_data = frame(self.study_info.get('cv_csv') or self.summary.get('cv_csv'),'electrical_cv.csv')
        measured = self.study_info.get('measured',{})
        self.measured_iv_data = frame(measured.get('iv',{}).get('csv'),'measured_iv.csv')
        self.measured_cv_data = frame(measured.get('cv',{}).get('csv'),'measured_cv.csv')
        studies = self.study_info.get('studies',{})
        self.result_model_labels=saved_result_model_labels(self.summary,self.study_info,self.iv_data,self.cv_data)
        for kind,computed,actual,plot,label in [('iv',self.iv_data,self.measured_iv_data,self.iv_plot,self.iv_scope),
                                               ('cv',self.cv_data,self.measured_cv_data,self.cv_plot,self.cv_scope)]:
            metadata = dict(studies.get(kind,{}))
            metadata['model']=self.result_model_labels[kind+'_model']
            plot.draw_figure(terminal_curve_figure(computed,actual,kind,metadata))
            scope = self.result_model_labels[kind+'_scope']
            warnings = metadata.get('warnings',[])
            label.setText(scope+('\n'+'\n'.join(str(item) for item in warnings) if warnings else '')+
                          (f'\n{len(actual)} user supplied measured samples.' if not actual.empty else ''))

    def _metadata(self):
        records = []
        for row in self._result_rows:
            checks = row.get('checks',{})
            records.append(dict(bias_V=row['bias_V'], **{key:value for key,value in checks.items() if not isinstance(value,(list,dict))}))
        fill_table(self.checks_table,pd.DataFrame(records))
        material_list = self.summary.get('evaluated_materials',self.summary.get('material_library',[]))
        provenance = self.summary.get('provenance',{})
        self.sources.setPlainText(json.dumps(dict(materials=material_list,provenance=provenance),indent=2,ensure_ascii=False,default=str))
        self.inputs.setPlainText(json.dumps(dict(options=self.summary.get('options',{}),device=self.summary.get('device',{})),indent=2,ensure_ascii=False,default=str))
        self.run_details.setPlainText(json.dumps(dict(model=self.summary.get('model'),geometry=self.summary.get('geometry',{}),
            mesh=self.summary.get('mesh',{}),limitations=self.summary.get('limitations',[]),elapsed_s=self.summary.get('elapsed_s'),
            terminal_studies=self.study_info,checks=[row.get('checks',{}) for row in self._result_rows]),indent=2,ensure_ascii=False,default=str))

    def _bias_changed(self, *_):
        self.volume = self.volume_path = None
        index = self.result_bias.currentData()
        if index is None or not self._result_rows:
            self._clear_views('No saved volume is available.')
            return
        row = self._result_rows[index]
        self.biasChanged.emit(float(row['bias_V']))
        path = saved_result_path(self.directory,row.get('volume_npz'))
        if path is None:
            self._clear_views('This saved result has no available volume NPZ.')
            return
        try:
            self.volume,notes = load_electrical_volume(path)
            self.volume_path = path
            for key,control in self.cursor_controls.items():
                axis = self.volume[key]*1e6
                with QSignalBlocker(control):
                    control.setRange(float(axis[0]),float(axis[-1]))
                    control.setValue(float(axis[len(axis)//2]))
            for item,(key,label,unit) in enumerate(QUANTITIES):
                available = key in self.volume
                self.quantity.setItemText(item,f'{label} [{unit}]'+('' if available else ' · Unavailable'))
                self.quantity.model().item(item).setEnabled(available)
            if self.quantity.currentData() not in self.volume:
                first = next((item for item,(key,_,_) in enumerate(QUANTITIES) if key in self.volume),-1)
                with QSignalBlocker(self.quantity):
                    self.quantity.setCurrentIndex(first)
                if first < 0:
                    self._clear_views('Saved coordinates are available, but this volume contains no supported electrical field quantities.')
                    self._update_exports()
                    return
            self.status.setText('; '.join(notes) if notes else f'Loaded actual saved volume: {path.name}. Probe snaps to nearest stored sample.')
            self._cursor_changed()
        except (OSError,ValueError,KeyError,zipfile.BadZipFile) as exc:
            self.volume = self.volume_path = None
            self._clear_views(f'Could not load electrical volume: {exc}')
        self._update_exports()

    def set_bias(self, bias_V):
        """Synchronize an enclosing result selector by its actual saved voltage."""
        if bias_V is None:
            return False
        try:
            value = float(bias_V)
        except (TypeError,ValueError):
            raise ValueError('Result bias must be a finite voltage.') from None
        if not math.isfinite(value):
            raise ValueError('Result bias must be a finite voltage.')
        for index,row in enumerate(self._result_rows):
            if math.isclose(float(row['bias_V']),value,rel_tol=1e-12,abs_tol=1e-12):
                self.result_bias.setCurrentIndex(index)
                return True
        return False

    def selected_bias(self):
        index = self.result_bias.currentData()
        return float(self._result_rows[index]['bias_V']) if index is not None and self._result_rows else None

    def _clear_views(self, message):
        self.top_view.clear(message); self.cross_view.clear(message); self.volume_view.clear(message)
        self.probe = {}; self.probe_label.setText('Probe unavailable'); self.range_label.setText('')
        self.status.setText(message)
        self._update_exports()

    def _cursor_changed(self, *_):
        if self.volume is None:
            return
        self.probe = nearest_grid_probe(self.volume,[self.cursor_controls[key].value()*1e-6 for key in ('x','y','z')])
        self.cursor_indices = self.probe['indices']
        values = self.probe['values']
        position = ', '.join(f'{key}={coordinate*1e6:.6g} µm' for key,coordinate in zip(('x','y','z'),self.probe['coordinates_m']))
        selected = self.quantity.currentData()
        label,unit = _QUANTITY_INFO.get(selected,('Quantity',''))
        measured = f'{label}={values[selected]:.7g} {unit}' if selected in values else f'{label}: Unavailable'
        identities=self._probe_identities()
        others = ' · '.join(f'{_QUANTITY_INFO[key][0]}={values[key]:.5g} {_QUANTITY_INFO[key][1]}' for key in
                           ('potential','field_magnitude_V_m','electrons_cm3','holes_cm3','charge_density_C_m3') if key in values and key != selected)
        self.probe_label.setText(f'Nearest stored grid sample [{", ".join(map(str,self.cursor_indices))}]: {position}\n{measured}'+
                                 (' · '+identities if identities else '')+('\n'+others if others else ''))
        self.probeChanged.emit(self.probe)
        self.redraw()

    def _probe_identities(self):
        device=self.summary.get('device',self.summary.get('options',{}).get('device',{}))
        names={row['id']:row['name'] for group in ('layers','contacts') for row in device.get(group,[])}
        names.update({row['id']:row.get('name',row['id']) for row in self.summary.get('material_library',self.summary.get('evaluated_materials',[]))})
        return ' · '.join(self.probe.get('layer_name') if key=='layer_id' and self.probe.get('layer_name') else
            names.get(self.probe[key],str(self.probe[key])) for key in ('layer_id','material_id','contact_id') if key in self.probe)

    def set_probe(self, x_m, y_m, z_m):
        if self.volume is None:
            return
        for key,value in zip(('x','y','z'),(x_m,y_m,z_m)):
            with QSignalBlocker(self.cursor_controls[key]):
                self.cursor_controls[key].setValue(float(value)*1e6)
        self._cursor_changed()

    def _pick_xy(self, x_m, y_m):
        self.set_probe(x_m,y_m,self.cursor_controls['z'].value()*1e-6)

    def _pick_xz(self, x_m, z_m):
        self.set_probe(x_m,self.cursor_controls['y'].value()*1e-6,z_m)

    def redraw(self, *_):
        if self.volume is None or self.quantity.currentData() not in self.volume:
            return
        key = self.quantity.currentData()
        values = np.asarray(self.volume[key],dtype=float)
        if values.ndim != 3:
            return
        can_log = bool(np.all(values >= 0) and np.any(values > 0))
        self.log_colors.setEnabled(can_log)
        logarithmic = self.log_colors.isChecked() and can_log
        self._colors = _FieldColors(values,logarithmic)
        label,unit = _QUANTITY_INFO[key]
        self.range_label.setText(self._colors.range_text()+' '+unit)
        ix,iy,iz = self.cursor_indices
        x,y,z = [self.volume[axis] for axis in ('x','y','z')]
        self.top_view.set_field(x,y,values[:,:,iz],self._colors,(x[ix],y[iy]),f'Top XY · z={z[iz]*1e6:.5g} µm · {label}')
        self.cross_view.set_field(x,z,values[:,iy,:],self._colors,(x[ix],z[iz]),f'Cross-section XZ · y={y[iy]*1e6:.5g} µm · {label}')
        self.volume_view.set_field(self.volume,values,self._colors,(x[ix],y[iy],z[iz]),'3D · '+label)
        # A quantity change also updates the textual value at the linked probe.
        if self.probe and key in self.probe.get('values',{}):
            position = ', '.join(f'{axis}={coordinate*1e6:.6g} µm' for axis,coordinate in zip(('x','y','z'),self.probe['coordinates_m']))
            identities=self._probe_identities()
            other_values = ' · '.join(f'{_QUANTITY_INFO[item][0]}={value:.5g} {_QUANTITY_INFO[item][1]}' for item,value in self.probe['values'].items()
                                    if item in ('potential','field_magnitude_V_m','electrons_cm3','holes_cm3','charge_density_C_m3') and item != key)
            self.probe_label.setText(f'Nearest stored grid sample [{", ".join(map(str,self.cursor_indices))}]: {position}\n{label}={self.probe["values"][key]:.7g} {unit}'+
                                     (' · '+identities if identities else '')+('\n'+other_values if other_values else ''))

    def field_figure(self):
        if self.volume is None or self.quantity.currentData() not in self.volume:
            raise ValueError('No saved field is selected for figure export.')
        key = self.quantity.currentData(); values = self.volume[key]
        _,iy,iz = self.cursor_indices
        figure = Figure(figsize=(10,5),layout='constrained')
        label,unit = _QUANTITY_INFO[key]
        from matplotlib.colors import LogNorm, Normalize
        norm = LogNorm(vmin=10**self._colors.low,vmax=10**self._colors.high if self._colors.high > self._colors.low else 10**self._colors.low*1.01) if self._colors.logarithmic else Normalize(self._colors.low,self._colors.high if self._colors.high > self._colors.low else self._colors.low+1.)
        for item,(second,slice_values,title) in enumerate([('y',values[:,:,iz],f'Top XY at z={self.volume["z"][iz]*1e6:.5g} µm'),
                                                        ('z',values[:,iy,:],f'Cross-section XZ at y={self.volume["y"][iy]*1e6:.5g} µm')]):
            axis = figure.add_subplot(1,2,item+1)
            image = axis.pcolormesh(_axis_edges(self.volume['x'])*1e6,_axis_edges(self.volume[second])*1e6,slice_values.T,
                                    shading='flat',cmap=self._colors.cmap,norm=norm)
            axis.set_xlabel('x (µm)'); axis.set_ylabel(second+' (µm)'); axis.set_title(title)
            axis.invert_yaxis()
            figure.colorbar(image,ax=axis,label=f'{label} ({unit})')
        figure.suptitle(f'{label} · {self.result_bias.currentText()} · saved grid samples')
        return figure

    def export_file(self, path, kind='npz'):
        path = Path(path)
        if kind in ('npz','csv','vtk') and self.volume is None:
            raise ValueError('Select an available saved volume before exporting.')
        if kind == 'npz':
            if path.resolve() != self.volume_path.resolve():
                shutil.copy2(self.volume_path,path)
        elif kind == 'csv':
            export_volume_csv(path,self.volume)
        elif kind == 'vtk':
            export_rectilinear_vtk(path,self.volume)
        elif kind == 'figure':
            index = self.tabs.currentIndex()
            figure = self.iv_plot.figure if index == 1 else self.cv_plot.figure if index == 2 else self.field_figure()
            figure.savefig(path,dpi=200,bbox_inches='tight')
        else:
            raise ValueError(f'Unknown electrical export type: {kind}.')
        self.status.setText(f'Exported actual saved result: {path}')
        return path

    def export_dialog(self, kind):
        names = {'npz':('volume.npz','NumPy volume (*.npz)'), 'csv':('electrical-grid.csv','Grid samples (*.csv)'),
                 'vtk':('electrical-volume.vtk','VTK rectilinear grid (*.vtk)'), 'figure':('electrical-fields.png','PNG image (*.png);;PDF figure (*.pdf);;SVG figure (*.svg)')}
        name,filters = names[kind]
        path,_ = QFileDialog.getSaveFileName(self,'Export electrical result',name,filters)
        if path:
            try:
                self.export_file(path,kind)
            except (OSError,ValueError) as exc:
                self.status.setText(f'Export failed: {exc}')
