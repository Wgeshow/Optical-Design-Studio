"""Editable King PCSEL starting setups and read-only saved figure views.

Paper targets never supply calculated arrays. Figures read only solver CSV/NPZ
artifacts within the explicitly opened run directory.
"""
from __future__ import annotations
from collections import OrderedDict
from copy import deepcopy
import csv
import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, QSignalBlocker, QEvent, QTimer
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from qt_common import PlotWidget
from qt_research_common import button, label

FIGURES = {
    'vertical': [('fig2', 'Figure 2 · Layer profile and vertical mode')],
    'cwt': [('fig3', 'Figure 3 · Triangle loss and discrimination map'),
            ('fig4', 'Figure 4 · Triangle coupling maps'),
            ('fig4d', 'Figure 4(d) · Focused direct-coupling map'),
            ('fig5', 'Figure 5 · DBR cladding-thickness sweep')],
    'finite': [('fig6', 'Figure 6 · Cavity loss and emission efficiency'),
               ('fig7', 'Figure 7 · Cavity mode discrimination'),
               ('fig8', 'Figure 8 · 2 mm mode spectrum and near fields'),
               ('fig9', 'Figure 9 · Original and weakened grating')],
    'beam': [('fig8', 'Figure 8 · 2 mm near and far fields'),
             ('fig9b', 'Figure 9 · 5 mm weakened-grating beam')],
}


class PcselPaperSetup:
    def __init__(self, workspace):
        self.workspace = workspace

    def install(self):
        w = self.workspace
        self.page, layout = w.add_section('King 2024 · paper setup', 'Paper setup')
        layout.addWidget(label('All-semiconductor PCSEL · King et al. 2024', 'setupHeading'))
        layout.addWidget(label('Choose the physical question for this simulation. The editable structure comes from Table 1 and the stated figure inputs. Published result values are comparison references, never solver inputs.'))
        form = QFormLayout()
        self.figure = QComboBox()
        self.figure.setAccessibleName('King 2024 paper figure setup')
        form.addRow('Study target', self.figure)
        self.formulation = QComboBox()
        self.formulation.setAccessibleName('Paper template vertical formulation')
        self.formulation.addItem('Fixed lattice period (paper approximation: 320 nm)', 'fixed_period')
        self.formulation.addItem('Reference wavelength (1070 nm); derive lattice period', 'reference_wavelength')
        form.addRow('Template method', self.formulation)
        layout.addLayout(form)
        layout.addWidget(label('The reference-wavelength method is an explicit alternative: it solves the vertical mode at the stated wavelength and derives a = wavelength / effective index. It does not fit any paper result. Requested and calculated periods are recorded separately.'))
        self.note = label('')
        layout.addWidget(self.note)
        self.figure.currentIndexChanged.connect(self._figure_note)
        self.load_button = button('Load editable paper setup', self.load_example)
        from qt_reference_style import reference_icon
        self.load_button.setIcon(reference_icon('layers', '#356ce8'))
        layout.addWidget(self.load_button)
        layout.addWidget(label('This action replaces only this simulation’s setup. Other simulation documents remain independent. Edit the stack, semiconductor indices, triangle, cavity and numerical settings afterward; keep advanced properties available.'))
        layout.addWidget(label('Paper scope: passive TE coupled-wave modes with no internal absorption, carrier dynamics or heating. Substrate efficiency is an optical power fraction, not wall-plug efficiency. Underlying author data are not publicly available; paper agreement and convergence are separate checks.'))
        layout.addStretch()
        self.refresh_model(w.fields['model'].currentData())

    def refresh_model(self, model):
        previous = self.figure.currentData()
        with QSignalBlocker(self.figure):
            self.figure.clear()
            for identity, title in FIGURES.get(model, []): self.figure.addItem(title, identity)
            index = self.figure.findData(previous)
            if index >= 0: self.figure.setCurrentIndex(index)
        self.load_button.setEnabled(bool(self.figure.count()))
        self._figure_note()

    def _figure_note(self, *_):
        identity = self.figure.currentData()
        notes = {'fig2': 'Results include the combined index/intensity profile and saved structure/unit-cell schematics.',
            'fig3': 'The radiation/discrimination maps use theta horizontally and b/a vertically. The unpublished no-DBR cladding thickness stays blank and blocks Run.',
            'fig4': 'Coupling maps use theta horizontally and b/a vertically. Select Figure 4(d) for the smaller direct-coupling domain. No-DBR cladding thickness is unpublished and blocks Run.',
            'fig4d': 'Focused domain: theta 68–75 degrees, b/a 0.65–0.775 (upper frame inferred). Sampling is editable; no-DBR cladding thickness stays blank and blocks Run.',
            'fig5': 'Four calculated bands and the difference between the two lowest loss bands. Optional published dashed baselines are labelled comparison references; they are never computed samples.',
            'fig6': 'Sparse editable cavity sides span 100–3000 µm. Results include loss, combined efficiencies and near-field views for saved accepted modes at each size.',
            'fig7': 'Sparse editable cavity sides span 100–3000 µm, including both sides of 700 µm. Saved second-mode near fields can be compared; band identity is not automatically tracked.',
            'fig8': 'Spectrum and three lowest accepted returned modes. The Beam simulation also calculates near/far fields, with far-field angles displayed in degrees.',
            'fig9': 'Two explicit editable variants share the remaining inputs and sweep 100–5000 µm. Edit the PC/spacer overrides in Sweep. Results overlay original and weakened structures; use Beam Figure 9 for the 5 mm fields.',
            'fig9b': 'The weakened 5 mm structure calculates accepted-mode near/far fields. Far-field degrees convert saved sine-angle coordinates without changing intensity.'}
        self.note.setText(notes.get(identity, 'Choose the matching independent simulation to load its paper setup.')+' Triangle theta is the equal base angle; b/a is dimensionless. All samples and accuracy settings remain editable.')

    def load_example(self):
        w = self.workspace
        figure = self.figure.currentData()
        if not figure: return False
        try:
            from pcsel_paper_studies import king2024_example
            model = w.fields['model'].currentData()
            settings = deepcopy(king2024_example(figure, model=model, formulation=self.formulation.currentData()))
            if settings.get('model') != model: raise ValueError('Choose the matching simulation type before loading this figure.')
            # Installation identity is local configuration, never a paper constant.
            runtime = w.structured.get('runtime')
            if runtime is not None:
                try:
                    current_runtime = runtime.value()
                    if current_runtime: settings['runtime'] = current_runtime
                except ValueError:
                    pass
            w.load_settings(settings)
            w._edited()
            w.save_draft()
            w.select_section('design' if model != 'beam' else 'mode_source')
            missing = any(layer.get('thickness_nm') is None or layer.get('index') is None for layer in settings.get('layers', []))
            w.status.setText(('Missing published input: no-DBR p-cladding thickness is unspecified. It remains blank; supply a documented value before running. ' if missing else '')+'King 2024 '+figure+' setup loaded into this independent simulation. No published output has been inserted as a calculation.')
            return True
        except (ImportError, ValueError, KeyError, TypeError) as exc:
            w.status.setText('Paper setup could not be loaded: '+str(exc))
            return False


def _artifact(root, relative):
    if not isinstance(relative, str) or not relative: raise ValueError('No saved data file is specified.')
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('The figure data file must exist inside this saved run.')
    return path


def _number(value):
    try: result = float(value)
    except (TypeError, ValueError): return np.nan
    return result if np.isfinite(result) else np.nan


def _rows(root, spec):
    path = _artifact(root, spec.get('csv'))
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    filters = spec.get('filter', {})
    return [row for row in rows if all(str(row.get(key, '')) == str(value) for key, value in filters.items())]


def _figure_title(spec):
    return str(spec.get('title', 'Saved calculated output')).replace('near_display', 'Near-field intensity').replace('far_display', 'Far-field intensity').replace('Vertical intensity_per_nm', 'Vertical normalized intensity')


class PaperPlotWidget(PlotWidget):
    """Keep saved field extents inside a physical-aspect native plotting box."""
    def __init__(self, parent=None):
        self._field_axes = None
        self._field_fitting = False
        super().__init__(parent)
        original_fit = self.canvas.fit_data
        def fit_saved_data():
            original_fit()
            self._fit_field_box()
        self.canvas.fit_data = fit_saved_data

    def retheme(self):
        super().retheme()
        if self._field_axes is not None:
            self._fit_field_box()
            QTimer.singleShot(0, self._fit_field_box)

    def draw_figure(self, figure=None):
        self._field_axes = next((ax for ax in (figure.axes if figure else []) if getattr(ax, '_ods_paper_field', False)), None)
        super().draw_figure(figure)
        if self._field_axes is None: self.canvas.view.ci.layout.setContentsMargins(9, 9, 9, 9)
        self.canvas_layout.setAlignment(self.canvas, Qt.AlignmentFlag.AlignHCenter if self._field_axes is not None else Qt.AlignmentFlag(0))
        if self._field_axes is not None:
            QTimer.singleShot(0, self._fit_field_box)

    def eventFilter(self, watched, event):
        if watched is getattr(self, 'canvas_host', None) and event.type() == QEvent.Type.Resize and self._field_axes is not None:
            QTimer.singleShot(0, self._fit_field_box)
        return super().eventFilter(watched, event)

    def _fit_field_box(self):
        axis = self._field_axes
        if self._field_fitting or axis is None or self.canvas is None: return
        view = self.canvas.axis_views.get(axis)
        plot = self.canvas.plots.get(axis)
        if view is None or plot is None: return
        self._field_fitting = True
        try:
            xlim, ylim = axis.get_xlim(), axis.get_ylim()
            ratio = abs((xlim[1]-xlim[0])/(ylim[1]-ylim[0]))
            # The complete name is already in the selector. A duplicate long
            # title otherwise forces Qt's field box wider than its data aspect.
            plot.setTitle('')
            self.canvas.view.ci.layout.setContentsMargins(10, 16, 24, 24)
            for record in self.canvas.colorbars:
                bar = record['native_item']
                bar.getAxis('right').setLabel(getattr(axis, '_ods_paper_short_quantity', 'Intensity'))
            # Reserve physical-axis text and full colorbar labels/ticks rather
            # than letting either extend beyond the native graphics viewport.
            available_h = max(60., self.canvas_host.height()-120.)
            available_w = max(60., self.canvas_host.width()-260.)
            height = min(available_h, available_w/ratio)
            width = height*ratio
            # The shared canvas has QSizePolicy.Ignored; a centred widget
            # therefore needs an explicit width, not only a maximum.
            self.canvas.setFixedWidth(int(width+260))
            plot.layout.setColumnFixedWidth(1, width)
            plot.layout.setRowFixedHeight(2, height)
            # QGraphicsWidget can retain its previous minimum-sized scene after
            # the parent shrinks. Reflow against the actual viewport now.
            scene_layout = self.canvas.view.ci.layout
            scene_layout.invalidate()
            self.canvas.view.ci.resize(self.canvas.view.viewport().width(), self.canvas.view.viewport().height())
            scene_layout.activate()
            # The box already has physical aspect. Native aspect locking would
            # instead expand ranges whenever the enclosing viewport is wide.
            view.setAspectLocked(False)
            view.setRange(xRange=sorted(xlim), yRange=sorted(ylim), padding=0)
        finally:
            self._field_fitting = False


def _series_name(row, series, default):
    if isinstance(series, list): return ' · '.join(str(row.get(key, '')) for key in series)
    return str(row.get(series, '')) if series else default


def _plot_saved_lines(axis, root, spec, invalid):
    rows = _rows(root, spec)
    if not rows: raise ValueError('No saved rows match this figure selection.')
    xkey, ykey = spec['x'], spec['y']
    if any(key not in rows[0] for key in (xkey, ykey)): raise ValueError('A required axis column is missing from the saved data.')
    groups = OrderedDict()
    default = str(spec.get('label', spec.get('value_label', ykey)))
    for row in rows:
        name = _series_name(row, spec.get('series'), default)
        if spec.get('series') and spec.get('label'): name = default+' · '+name
        groups.setdefault(name, []).append(row)
    count = 0
    for name, group in groups.items():
        pairs = [(_number(row.get(xkey))*spec.get('x_scale', 1)+spec.get('x_offset', 0),
                  np.nan if row.get('status') in invalid else _number(row.get(ykey))*spec.get('y_scale', 1)) for row in group]
        pairs.sort(key=lambda point: point[0])
        x, y = np.asarray(pairs, dtype=float).T
        count += int(np.count_nonzero(np.isfinite(x) & np.isfinite(y)))
        axis.plot(x, y, marker='.' if spec.get('markers', True) else None,
                  linestyle=spec.get('linestyle', '-' if spec.get('connect', True) else 'None'), color=spec.get('color'), label=name)
    return count


def _input_schematic(axis, root, spec):
    from matplotlib.patches import Circle, Polygon, Rectangle
    from pcsel_paper_studies import triangle_vertices
    cfg = json.loads(_artifact(root, spec.get('json')).read_text(encoding='utf-8'))
    if spec.get('view') == 'cell':
        axis.add_patch(Rectangle((-.5,-.5),1,1,facecolor='#344158',edgecolor='#819ab8'))
        for shape in cfg.get('shapes', []):
            vertices = triangle_vertices(shape) if shape.get('shape') == 'triangle' else shape.get('vertices')
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    if vertices is not None:
                        axis.add_patch(Polygon(np.asarray(vertices)+[dx,dy],facecolor='#4c6ca8',edgecolor='#182a46',clip_on=True))
                    elif shape.get('shape') == 'circle':
                        center=np.asarray(shape.get('center',[0,0]))+[dx,dy]
                        axis.add_patch(Circle(center,shape['radius'],facecolor='#4c6ca8',edgecolor='#182a46',clip_on=True))
        axis.set_xlim(-.5,.5);axis.set_ylim(-.5,.5);axis.set_aspect('equal',adjustable='box')
        axis._ods_paper_field=True
        axis.set_xlabel('x / a');axis.set_ylabel('y / a')
        triangle=next((shape for shape in cfg.get('shapes',[]) if shape.get('shape')=='triangle'),None)
        if triangle:
            axis.text(.02,.03,'b/a = '+str(triangle['base_length'])+'; base θ = '+str(triangle['base_angle_deg'])+'°',transform=axis.transAxes,fontsize=8,va='bottom')
        # The periodic schematic uses the current shapes, not a static paper image.
        axis.text(.02,.98,'Saved input geometry',ha='left',va='top',transform=axis.transAxes,fontsize=8)
    else:
        height=0.;groups=set()
        for layer in reversed(cfg.get('layers', [])):
            thickness=_number(layer.get('thickness_nm'))/1000
            if not np.isfinite(thickness) or thickness <= 0: raise ValueError('The saved stack has an unspecified layer thickness.')
            name=str(layer.get('name',layer.get('id','Layer')))
            group='Photonic crystal' if layer.get('patterned') else 'Quantum well' if layer.get('qw') else 'DBR' if name.startswith('dbr-') else 'Other semiconductor'
            color={'Photonic crystal':'#355b96','Quantum well':'#973454','DBR':'#534170','Other semiconductor':'#344158'}[group]
            axis.add_patch(Rectangle((0,height),1,thickness,facecolor=color,edgecolor='#819ab8',linewidth=.4))
            # The native renderer's vector patches are not legend sample items.
            if group not in groups:axis.plot([],[],color=color,linewidth=6,label=group)
            groups.add(group)
            if thickness >= .12: axis.text(.5,height+thickness/2,name,ha='center',va='center',fontsize=7)
            height += thickness
        axis.set_xlim(0,1);axis.set_ylim(0,height);axis.set_xticks([])
        axis.set_ylabel('Height from n-side (µm)');axis.legend(fontsize=7,loc='upper left',bbox_to_anchor=(1,1))
    axis._ods_input_schematic=True


def saved_paper_figure(root, spec, *, beam_detail=False, show_references=False):
    """Render saved output without interpolation, fitting or reference substitution."""
    figure = Figure(figsize=(7, 5), layout='constrained')
    axis = figure.add_subplot(111)
    kind = spec.get('kind')
    axis.set_title(_figure_title(spec))
    invalid = set(spec.get('invalid_statuses', ['invalid_geometry', 'failed']))
    if kind == 'device_schematic':
        _input_schematic(axis, root, spec)
        return figure
    if kind == 'multi_line':
        right = None;count = 0
        for curve in spec.get('curves', []):
            if curve.get('axis') == 'right' and right is None:
                right=axis.twinx();right.set_ylabel(spec.get('right_y_label',''))
            destination=right if curve.get('axis') == 'right' else axis
            count += _plot_saved_lines(destination,root,curve,invalid)
        if not count: raise ValueError('This figure has no finite calculated samples.')
        for destination in [axis]+([right] if right is not None else []):
            destination.legend(fontsize=8,loc='upper right' if destination is right else 'upper left')
        axis.grid(True,alpha=.25)
    elif kind in ('line', 'heatmap'):
        rows = _rows(root, spec)
        if not rows: raise ValueError('No saved rows match this figure selection.')
        xkey, ykey = spec['x'], spec['y']
        if any(key not in rows[0] for key in (xkey, ykey)):
            raise ValueError('A required axis column is missing from the saved data.')
        if kind == 'line':
            finite_points = _plot_saved_lines(axis,root,spec,invalid)
            if not finite_points: raise ValueError('This figure has no finite calculated samples.')
            if len(axis.lines) <= 12: axis.legend(fontsize=8)
            axis.grid(True, alpha=.25)
        else:
            value_key = spec['value']
            if value_key not in rows[0]: raise ValueError('The saved map quantity is missing.')
            xs = sorted({_number(row.get(xkey)) for row in rows if np.isfinite(_number(row.get(xkey)))})
            ys = sorted({_number(row.get(ykey)) for row in rows if np.isfinite(_number(row.get(ykey)))})
            if not xs or not ys: raise ValueError('The map has no finite axis coordinates.')
            values = np.full((len(ys), len(xs)), np.nan)
            visited = set()
            for row in rows:
                x, y = _number(row.get(xkey)), _number(row.get(ykey))
                if not np.isfinite(x+y): continue
                key = (ys.index(y), xs.index(x))
                if key in visited: raise ValueError('Duplicate map coordinates require an explicit series or filter.')
                visited.add(key)
                if row.get('status') not in invalid: values[key] = _number(row.get(value_key))
            if not np.isfinite(values).any(): raise ValueError('This map has no finite calculated samples.')
            cmap = __import__('matplotlib').colormaps['viridis'].copy()
            cmap.set_bad('#d8dce2')
            axis.set_facecolor('#d8dce2')
            mesh = axis.pcolormesh(xs, ys, np.ma.masked_invalid(values), shading='nearest', cmap=cmap)
            figure.colorbar(mesh, ax=axis, label=spec.get('value_label', value_key))
    elif kind == 'field_grid':
        path = _artifact(root, spec.get('npz'))
        with np.load(path, allow_pickle=False) as saved:
            values = np.asarray(saved[spec['array']])
            x, y = np.asarray(saved[spec['x']], dtype=float), np.asarray(saved[spec['y']], dtype=float)
            if values.ndim == 3:
                index = int(spec.get('mode_index', 0))
                if not 0 <= index < values.shape[0]: raise ValueError('Saved mode index is outside the field array.')
                values = values[index]
            if np.iscomplexobj(values): raise ValueError('Select a saved real intensity quantity for this field view.')
            if values.ndim != 2 or values.shape != (len(y), len(x)):
                raise ValueError('Saved field dimensions do not match its physical coordinate axes.')
            for dim, key in enumerate(('y_transform','x_transform')):
                transform=spec.get(key)
                if transform is None: continue
                if transform != 'arcsin_degrees': raise ValueError('Unsupported saved coordinate display transform.')
                coords=y if dim==0 else x
                selected=np.isfinite(coords)&(np.abs(coords)<=1)
                if selected.sum()<2: raise ValueError('Too few propagating angle samples to display.')
                values=values[selected,:] if dim==0 else values[:,selected]
                converted=np.rad2deg(np.arcsin(coords[selected]))
                if dim==0:y=converted
                else:x=converted
            if not np.isfinite(values).any(): raise ValueError('The saved field contains no finite samples.')
            mesh = axis.pcolormesh(x, y, np.ma.masked_invalid(values), shading='nearest', cmap='viridis')
            figure.colorbar(mesh, ax=axis, label=spec.get('value_label', spec['array']))
            axis.set_aspect('equal', adjustable='box')
            axis._ods_paper_field = True
            axis._ods_paper_short_quantity = 'Peak intensity ratio' if spec.get('array') in ('near_display', 'far_display', 'emitted_near_intensity') else 'Normalized intensity'
            if beam_detail and spec.get('array') == 'far_display':
                # A labelled view limit only: the mesh and exported NPZ retain
                # every saved value, including side lobes outside this view.
                selected = np.isfinite(values) & (values >= .01*np.nanmax(values))
                iy, ix = np.nonzero(selected)
                if len(ix):
                    def edges(coords):
                        return np.r_[coords[0]-(coords[1]-coords[0])/2, (coords[:-1]+coords[1:])/2, coords[-1]+(coords[-1]-coords[-2])/2]
                    xe, ye = edges(x), edges(y)
                    margin_x = max(2, int(np.ceil((ix.max()-ix.min()+1)*.15)))
                    margin_y = max(2, int(np.ceil((iy.max()-iy.min()+1)*.15)))
                    axis.set_xlim(xe[max(0, ix.min()-margin_x)], xe[min(len(x), ix.max()+margin_x+1)])
                    axis.set_ylim(ye[max(0, iy.min()-margin_y)], ye[min(len(y), iy.max()+margin_y+1)])
                    axis.set_title(_figure_title(spec)+' · beam detail')
    else:
        raise ValueError('This saved figure type is not supported.')
    if show_references:
        for reference in spec.get('reference_lines', []):
            if reference.get('role') != 'published_reference': raise ValueError('Unlabelled reference overlay is not permitted.')
            axis.axhline(float(reference['value']),color='#b96b26',linestyle='--',label='REFERENCE ONLY · '+reference['label'])
        if spec.get('reference_lines'):axis.legend(fontsize=7)
    axis.set_xlabel(spec.get('x_label', spec.get('x', '')))
    axis.set_ylabel(spec.get('y_label', spec.get('y', '')))
    return figure


class PcselPaperResults(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = None
        self.manifest = {}
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.choice = QComboBox(); self.choice.setAccessibleName('Saved PCSEL paper figure')
        self.choice.currentIndexChanged.connect(self._selected)
        row.addWidget(self.choice, 1)
        self.export_button = button('Export source data…', self.export_source)
        row.addWidget(self.export_button)
        layout.addLayout(row)
        self.display_view = QComboBox()
        self.display_view.setAccessibleName('Far-field display extent')
        self.display_view.addItem('Full saved angular extent', False)
        self.display_view.addItem('Beam detail · ≥1% of peak + margin (display only)', True)
        self.display_view.currentIndexChanged.connect(self.draw)
        layout.addWidget(self.display_view)
        self.references=QCheckBox('Show published comparison reference (not calculated)')
        self.references.setAccessibleName('Show published reference overlay')
        self.references.toggled.connect(self.draw)
        layout.addWidget(self.references)
        self.status = label('No saved paper figure data is loaded.')
        layout.addWidget(self.status)
        self.plot = PaperPlotWidget(); layout.addWidget(self.plot, 1)
        self.note = label('Calculated plots read saved solver data only. Published comparison targets are separate. Grey map cells are missing or invalid, never a zero result.')
        layout.addWidget(self.note)
        self.clear()

    def clear(self):
        self.root = None; self.manifest = {}
        self.display_view.hide()
        self.references.hide()
        with QSignalBlocker(self.references): self.references.setChecked(False)
        with QSignalBlocker(self.display_view): self.display_view.setCurrentIndex(0)
        with QSignalBlocker(self.choice): self.choice.clear()
        self.plot.clear(); self.export_button.setEnabled(False)
        self.status.setText('No saved paper figure data is loaded.')

    def load_directory(self, root):
        self.clear()
        root = Path(root).resolve()
        path = root/'pcsel_paper_figures.json'
        if not path.is_file(): return False
        try:
            if path.stat().st_size > 10_000_000: raise ValueError('Figure manifest is too large.')
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or not isinstance(manifest.get('plots'), list):
                raise ValueError('Unsupported saved figure manifest.')
            self.root, self.manifest = root, manifest
            with QSignalBlocker(self.choice):
                for spec in manifest['plots']:
                    if not isinstance(spec, dict): raise ValueError('Invalid saved figure entry.')
                    self.choice.addItem(_figure_title(spec), spec)
            self.draw()
            return bool(self.choice.count())
        except (ValueError, OSError, TypeError) as exc:
            self.clear(); self.status.setText('Could not open saved paper figures: '+str(exc))
            return False

    def _selected(self, *_):
        with QSignalBlocker(self.display_view): self.display_view.setCurrentIndex(0)
        with QSignalBlocker(self.references): self.references.setChecked(False)
        self.draw()

    def draw(self, *_):
        self.plot.clear(); self.export_button.setEnabled(False)
        spec = self.choice.currentData()
        if self.root is None or not spec: return
        try:
            self.display_view.setVisible(spec.get('kind') == 'field_grid' and spec.get('array') == 'far_display')
            self.references.setVisible(bool(spec.get('reference_lines')))
            detail = bool(self.display_view.currentData()) and spec.get('array') == 'far_display'
            figure = saved_paper_figure(self.root, spec, beam_detail=detail, show_references=self.references.isChecked())
            self.plot.draw_figure(figure)
            self.export_button.setEnabled(True)
            self.status.setText(('Saved input schematic · ' if spec.get('kind')=='device_schematic' else 'Saved calculated output · ')+str(self.manifest.get('status', 'status unreported'))+'\n'+str(self.manifest.get('scope', 'Comparison and numerical convergence have not been established by this plot.')))
            self.note.setText(('Published dashed lines are comparison-only: '+str(spec['reference_lines'][0]['origin'])+'. ' if self.references.isChecked() and spec.get('reference_lines') else '')+('Quantity: '+str(spec.get('value_label', spec.get('array', '')))+'. ' if spec.get('kind') == 'field_grid' else '')+('Beam detail is a display-only crop around samples ≥1% of peak plus margin. Full mesh and source export remain unchanged. ' if detail else '')+str(spec.get('note', ''))+'\nSaved calculated samples and labelled input geometry only. Missing or invalid map cells are grey. See Status & provenance and Paper comparison for independent validation evidence.')
        except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
            self.status.setText('Figure unavailable: '+str(exc))

    def export_source(self):
        spec = self.choice.currentData()
        if self.root is None or not spec: return
        try:
            names=list(dict.fromkeys([row['csv'] for row in spec.get('curves',[]) if row.get('csv')]+[spec[key] for key in ('csv','npz','json') if spec.get(key)]))
            sources=[_artifact(self.root,name) for name in names]
            if not sources: raise ValueError('No saved source file is specified.')
            if len(sources)>1:
                target,_=QFileDialog.getSaveFileName(self,'Export exact saved figure sources','paper-figure-sources.zip','Source bundle (*.zip)')
                if target:
                    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                        for name,source in zip(names,sources):archive.write(source,arcname=name)
                        archive.writestr('figure-specification.json',json.dumps(spec,indent=2))
                    self.status.setText('Exported exact source files and figure specification to '+str(target))
                return
            source=sources[0]
            target, _ = QFileDialog.getSaveFileName(self, 'Export exact saved figure data', source.name, 'Saved data (*'+source.suffix+')')
            if target and Path(target).resolve() != source:
                shutil.copyfile(source, target)
                self.status.setText('Exported exact saved source data to '+str(target))
        except (ValueError, OSError) as exc: self.status.setText('Could not export saved figure data: '+str(exc))
