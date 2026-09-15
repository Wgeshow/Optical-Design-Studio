"""Compare persisted field snapshots without rerunning the native solver."""
import cmath
from contextlib import nullcontext
from datetime import datetime
import html
from pathlib import Path
import re
import shutil
import uuid

import gradio as gr
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np
import pandas as pd

from data_library import read_json, write_json
from model import epsilon


MODES = {'All saved fields': None, 'Fixed target wavelength': 'fixed_target',
         'Selected resonance': 'selected_resonance', 'Manual / legacy': 'manual'}


def natural_key(value):
    """Keep design 2 before design 10 without assuming zero-padded IDs."""
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r'(\d+)', str(value)))


def _snapshot_label(identifier, snapshot, record):
    model = snapshot['model']
    title = record.get('title') or identifier.split('/')[0]
    created = record.get('created', '')
    try:
        created = datetime.fromisoformat(created.replace('Z', '+00:00')).astimezone().strftime('%b %d, %H:%M')
    except (TypeError, ValueError):
        created = ''
    design = re.search(r'(?:^|/)(?:design|trial)[_ -]*(\d+)', identifier, re.IGNORECASE)
    parts = [title, created, f'Design {int(design[1])}' if design else 'Field sample',
             f"{float(snapshot['wavelength_nm']):.8g} nm"]
    stack = [str(layer['material']) for layer in model.get('layers', [])[1:-1]]
    if stack:
        parts.append(' → '.join(stack[:5]) + (' …' if len(stack) > 5 else ''))
    mode = snapshot.get('settings', {}).get('sampling_mode', 'manual')
    parts.append({'fixed_target': 'Target', 'selected_resonance': 'Resonance', 'manual': 'Manual'}.get(mode, mode))
    return ' · '.join(part for part in parts if part)


def _safe_directory(library, identifier):
    root = Path(library.runs).resolve()
    path = (root / str(identifier)).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Choose a field dataset from the saved library')
    if not (path / 'electric_fields.csv').is_file() or not (path / 'field_model.json').is_file():
        raise ValueError('The selected field dataset is no longer available')
    return path


def saved_datasets(library, mode='All saved fields', query='', wavelength_nm=0):
    """List only complete snapshots; identifiers retain run and design lineage."""
    result = []
    wanted = MODES.get(mode)
    metadata = {}
    for path in sorted(Path(library.runs).rglob('electric_fields.csv'), key=natural_key):
        try:
            directory = path.parent
            identifier = directory.relative_to(library.runs).as_posix()
            _safe_directory(library, identifier)
            snapshot = read_json(directory / 'field_model.json')
            if not (directory / 'field_features.json').exists():
                continue  # An interrupted sample is not a complete field dataset.
            model = snapshot['model']
            config = snapshot.get('settings', {})
            sample_mode = config.get('sampling_mode', 'manual')
            wavelength = float(snapshot['wavelength_nm'])
            if wanted and sample_mode != wanted:
                continue
            if wavelength_nm and abs(wavelength - float(wavelength_nm)) > 1e-6:
                continue
            run = identifier.split('/')[0]
            if run not in metadata:
                record_path = Path(library.runs) / run / 'library_record.json'
                metadata[run] = read_json(record_path) if record_path.exists() else {}
            label = _snapshot_label(identifier, snapshot, metadata[run])
            searchable = ' '.join((label, identifier, str(model.get('patterns', [])), str(model.get('layers', []))))
            if query.strip().lower() not in searchable.lower():
                continue
            result.append((label, identifier))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def common_layers(library, reference_id, current_id, selected=None):
    """Return named finite layers present in both snapshots, preserving selection."""
    if not reference_id or not current_id:
        return [], None
    try:
        models = [read_json(_safe_directory(library, identifier) / 'field_model.json')['model']
                  for identifier in (reference_id, current_id)]
        common = set(_layer_layout(models[0])) & set(_layer_layout(models[1]))
        choices = [(f"{row['name']} · {row['material']}", row['name'])
                   for row in models[0]['layers'][1:-1] if row['name'] in common]
        values = [value for _, value in choices]
        return choices, selected if selected in values else (values[0] if values else None)
    except (OSError, ValueError, KeyError, TypeError):
        return [], None


def dataset_selection(choices, reference=None, current=None):
    identifiers = [value for _, value in choices]
    reference = reference if reference in identifiers else (identifiers[0] if identifiers else None)
    current = current if current in identifiers else (identifiers[-1] if identifiers else None)
    position = identifiers.index(current) + 1 if current else 1
    return reference, current, identifiers, position


def _layer_layout(model):
    result, depth = {}, 0.
    for layer in model['layers'][1:-1]:
        if layer['thickness'] > 0:
            result[layer['name']] = (len(result), depth, float(layer['thickness']))
        depth += layer['thickness']
    return result


def _slice(data, model, plane, layer):
    """Prefer explicit maps; fall back to clearly labelled volume samples."""
    frame = data[data.plane == plane].copy()
    if plane == 'xy':
        frame = frame[frame.layer == layer]
    if not frame.empty:
        return frame, 'layer midplane' if plane == 'xy' else 'y = 0'
    frame = data[data.plane == 'volume_samples'].copy()
    if plane == 'xy':
        frame = frame[frame.layer == layer]
        if not frame.empty:
            _, start, thickness = _layer_layout(model)[layer]
            closest = min(frame.z_um.unique(), key=lambda z: abs(z - start - thickness / 2))
            frame = frame[np.isclose(frame.z_um, closest)]
        return frame, 'sampled midplane (training grid)'
    if frame.empty:
        return frame, 'no samples'
    closest = min(frame.y_um.unique(), key=lambda y: (abs(y), y))
    return frame[np.isclose(frame.y_um, closest)].copy(), f'nearest sampled y = {closest:.4g} µm; 3 depths/layer'


def _coordinates(frame, model, plane, alignment):
    frame = frame.copy()
    frame['horizontal'] = frame.x_um
    frame['vertical'] = frame.y_um if plane == 'xy' else frame.z_um
    if alignment == 'Layer-relative coordinates':
        frame['horizontal'] = frame.x_um / model['ax']
        if plane == 'xy':
            frame['vertical'] = frame.y_um / model['ay']
        else:
            for name, (index, start, thickness) in _layer_layout(model).items():
                selected = frame.layer == name
                frame.loc[selected, 'vertical'] = index + (frame.loc[selected, 'z_um'] - start) / thickness
    return frame


def _outlines(axis, model, layer, alignment):
    sx = model['ax'] if alignment == 'Layer-relative coordinates' else 1.
    sy = model['ay'] if alignment == 'Layer-relative coordinates' else 1.
    # Plot transformed vertices, preserving rotations when the lattice is rectangular.
    for region in model.get('patterns', []):
        if region['layer'] != layer:
            continue
        theta = np.linspace(0, 2 * np.pi, 121)
        if region['shape'] in ('circle', 'ellipse'):
            x = region['sx'] * np.cos(theta)
            y = (region['sx'] if region['shape'] == 'circle' else region['sy']) * np.sin(theta)
        else:
            x = np.array([-1, 1, 1, -1, -1]) * region['sx'] / 2
            y = np.array([-1, -1, 1, 1, -1]) * region['sy'] / 2
        angle = np.deg2rad(region['angle'])
        u, v = x * np.cos(angle) - y * np.sin(angle), x * np.sin(angle) + y * np.cos(angle)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                axis.plot((u + region['cx'] + i * model['ax']) / sx,
                          (v + region['cy'] + j * model['ay']) / sy, color='white', lw=.8)


def _flow_arrows(axis, frame, model, plane, alignment):
    columns = [component + '_' + part for component in ('Ex', 'Ey', 'Ez', 'Hx', 'Hy', 'Hz') for part in ('real', 'imag')]
    if not set(columns).issubset(frame.columns):
        axis.text(.02, .02, 'H not saved; energy-flow arrows unavailable', transform=axis.transAxes, fontsize=7, color='white')
        return
    subset = frame.iloc[::max(1, len(frame) // 110)]
    e = np.column_stack([subset[c + '_real'].to_numpy() + 1j * subset[c + '_imag'].to_numpy() for c in ('Ex', 'Ey', 'Ez')])
    h = np.column_stack([subset[c + '_real'].to_numpy() + 1j * subset[c + '_imag'].to_numpy() for c in ('Hx', 'Hy', 'Hz')])
    flow = .5 * np.real(np.cross(e, np.conjugate(h)))
    u, v = flow[:, 0], flow[:, 1 if plane == 'xy' else 2]
    if alignment == 'Layer-relative coordinates':
        u = u / model['ax']
        if plane == 'xy':
            v = v / model['ay']
        else:
            thickness = {name: value[2] for name, value in _layer_layout(model).items()}
            v = v / subset.layer.map(thickness).to_numpy()
    magnitude = np.hypot(u, v)
    maximum = float(magnitude.max(initial=0.))
    if maximum <= 1e-15:
        return
    visible = magnitude > maximum * 1e-8
    # Direction-only arrows avoid independent panel autoscaling implying equal flux.
    u = u[visible] / magnitude[visible]
    v = v[visible] / magnitude[visible]
    axis.quiver(subset.horizontal.to_numpy()[visible], subset.vertical.to_numpy()[visible], u, v,
                color='white', angles='xy', scale_units='inches', scale=10, width=.003)


def plot_comparison(reference, current, layer='', alignment='Physical coordinates', arrows=False):
    """Common intensity normalization, independent geometry, no resampling of fields."""
    paths = [Path(reference), Path(current)]
    models = [read_json(path / 'field_model.json')['model'] for path in paths]
    available = [set(_layer_layout(model)) for model in models]
    common = available[0] & available[1]
    if not common:
        raise ValueError('The selected designs have no common finite layer name')
    layer = layer.strip() or next(name for name in _layer_layout(models[0]) if name in common)
    if layer not in common:
        raise ValueError('Choose an XY layer name present in both field datasets')
    slices = []
    for path, model in zip(paths, models):
        data = pd.read_csv(path / 'electric_fields.csv')
        maps = [_slice(data, model, plane, layer) for plane in ('xy', 'xz')]
        slices.append([(_coordinates(frame, model, plane, alignment), title)
                       for (frame, title), plane in zip(maps, ('xy', 'xz'))])
    maxima = [float(frame.E2.max()) for maps in slices for frame, _ in maps if not frame.empty]
    maximum = max(maxima, default=1.)
    if not np.isfinite(maximum) or maximum < 0:
        raise ValueError('Field intensity data must be finite and nonnegative')
    norm = Normalize(vmin=0, vmax=maximum or 1.)
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    relative = alignment == 'Layer-relative coordinates'
    xbound = .5 if relative else max(model['ax'] for model in models) / 2
    ybound = .5 if relative else max(model['ay'] for model in models) / 2
    zbound = max(len(_layer_layout(model)) if relative else sum(l['thickness'] for l in model['layers'][1:-1]) for model in models)
    artist = None
    for row, (maps, model, label) in enumerate(zip(slices, models, ('Reference', 'Current'))):
        for column, ((frame, subtitle), plane) in enumerate(zip(maps, ('xy', 'xz'))):
            axis = axes[row, column]
            if frame.empty:
                axis.text(.5, .5, 'No map samples', transform=axis.transAxes, ha='center')
                continue
            values = frame.pivot_table(index='vertical', columns='horizontal', values='E2', aggfunc='mean').sort_index()
            artist = axis.pcolormesh(values.columns, values.index, values.values, shading='nearest', cmap='turbo', norm=norm)
            axis.set_xlim(-xbound, xbound)
            axis.set_ylim((-ybound, ybound) if plane == 'xy' else (0, zbound))
            axis.set(xlabel='x / ax' if relative else 'x (µm)',
                     ylabel=('y / ay' if plane == 'xy' else 'layer index + depth fraction') if relative else ('y (µm)' if plane == 'xy' else 'z (µm)'),
                     title=f'{label} {plane.upper()}: {layer if plane == "xy" else "stack"}\n{subtitle}')
            if plane == 'xy':
                _outlines(axis, model, layer, alignment)
                axis.set_aspect('equal', adjustable='box')
            else:
                for name, (index, start, thickness) in _layer_layout(model).items():
                    lo, hi = (index, index + 1) if relative else (start, start + thickness)
                    axis.axhline(lo, color='white', lw=.65)
                    axis.axhline(hi, color='white', lw=.65)
                    axis.text(xbound, (lo + hi) / 2, name, color='white', ha='right', fontsize=8)
            # Material boundaries here are sampled masks, so never imply an exact interface.
            if 'material' in frame and frame.material.nunique() > 1:
                categories = {name: index for index, name in enumerate(sorted(frame.material.unique()))}
                mask = frame.assign(mask=frame.material.map(categories)).pivot_table(index='vertical', columns='horizontal', values='mask', aggfunc='first').sort_index()
                if min(mask.shape) >= 2:
                    axis.contour(mask.columns, mask.index, mask.values, levels=np.arange(len(categories) - 1) + .5, colors='black', linewidths=.35, alpha=.5)
            if arrows:
                _flow_arrows(axis, frame, model, plane, alignment)
    if artist is not None:
        figure.colorbar(artist, ax=axes, label='|E|² / incident |E|² (same scale for all panels)', shrink=.85)
    figure.suptitle('Saved steady-state field comparison; white outlines = geometry, black = sampled material boundary'
                   + ('\nArrows: local time-averaged energy-flow direction (equal length; magnitude not encoded)' if arrows else ''))
    return figure


def _conditions(snapshot):
    model = snapshot['model']
    wavelength = float(snapshot['wavelength_nm'])
    conditions = {'wavelength_nm': wavelength, 'sampling_mode': snapshot.get('settings', {}).get('sampling_mode', 'manual')}
    for key in ('ax', 'ay', 'basis', 'polarization', 'phi'):
        conditions[key] = model.get(key)
    conditions['incidence_theta_deg'] = model.get('points', [[None, None, None]])[0][2]
    for layer in model['layers']:
        conditions[f"layer/{layer['name']}/thickness_um"] = layer['thickness']
        conditions[f"layer/{layer['name']}/material"] = layer['material']
    for index, pattern in enumerate(model.get('patterns', []), 1):
        for key, value in pattern.items():
            conditions[f'pattern/{index}/{key}'] = value
    for material in model['materials']:
        prefix = f"material/{material['name']}"
        conditions[prefix + '/model'] = material['model']
        nk = cmath.sqrt(epsilon(material, wavelength))
        conditions[prefix + '/n_at_sample_wavelength'] = nk.real
        conditions[prefix + '/k_at_sample_wavelength'] = nk.imag
        if material['model'] == 'table_nk':
            conditions[prefix + '/table_samples'] = len(material['table'])
    return conditions


def condition_table(reference, current):
    before, after = (_conditions(read_json(Path(path) / 'field_model.json')) for path in (reference, current))
    return pd.DataFrame([{'Condition': key, 'Reference': str(before.get(key, 'absent')),
                          'Current': str(after.get(key, 'absent')), 'Changed': before.get(key) != after.get(key)}
                         for key in dict.fromkeys([*before, *after])])


def _flatten(value, prefix=''):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten(item, (prefix + '/' if prefix else '') + str(key))
    elif isinstance(value, (int, float, str, bool)) or value is None:
        yield prefix, value


def metric_table(reference, current, comparison):
    before, after = dict(_flatten(reference)), dict(_flatten(current))
    rows = [{'Metric': key, 'Reference': str(before.get(key, 'unavailable')), 'Current': str(after.get(key, 'unavailable'))}
            for key in dict.fromkeys([*before, *after]) if key.startswith(('layers/', 'global_metrics/', 'materials/'))]
    rows.extend({'Metric': 'comparison/' + key, 'Reference': '', 'Current': str(value)} for key, value in _flatten(comparison))
    return pd.DataFrame(rows, columns=['Metric', 'Reference', 'Current'])


def comparison_summary(payload):
    """Readable measurements for the main view; full descriptors remain downloadable."""
    rows = []
    for name, value in payload.get('comparison', {}).get('layers', {}).items():
        displacement = value.get('centroid_displacement_um', {})
        fraction = value.get('E2_fraction_change')
        rows.append({'Layer': name, 'Field overlap (0–1)': value.get('field_overlap'),
                     'Confinement change (percentage points)': None if fraction is None else 100 * fraction,
                     'Centroid Δx (µm)': displacement.get('x'), 'Centroid Δy (µm)': displacement.get('y'),
                     'Centroid Δz (µm)': displacement.get('z'), 'Mean intensity ratio': value.get('mean_E2_ratio')})
    return pd.DataFrame(rows, columns=['Layer', 'Field overlap (0–1)', 'Confinement change (percentage points)',
                                      'Centroid Δx (µm)', 'Centroid Δy (µm)', 'Centroid Δz (µm)', 'Mean intensity ratio'])


def compare_saved(library, reference_id, current_id, layer='', alignment='Physical coordinates', arrows=False):
    from field_tracking import enrich_fields, compare_fields
    reference, current = (_safe_directory(library, identifier) for identifier in (reference_id, current_id))
    before, after = enrich_fields(reference), enrich_fields(current)
    comparison = compare_fields(after, before)
    figure = plot_comparison(reference, current, layer, alignment, arrows)
    conditions = condition_table(reference, current)
    metrics = metric_table(before, after, comparison)
    explanation = ('Phase-independent complex-field overlap is evaluated in matching layer-relative cells. '
                   'The plots use the selected coordinate view and a shared incident-normalized intensity scale. '
                   'Confinement is an integral of |E|², not dispersive stored energy. ')
    if comparison.get('compatible'):
        overlap = comparison.get('field_overlap')
        explanation += f"Field overlap: **{overlap:.5g}**. " if overlap is not None else 'Field overlap is undefined for the saved signature. '
    else:
        explanation += '**Overlap unavailable:** ' + html.escape(str(comparison.get('reason', 'incompatible sampling'))) + '. '
    if before.get('sampling_mode') != after.get('sampling_mode') or abs(before['wavelength_nm'] - after['wavelength_nm']) > 1e-6:
        explanation += 'These snapshots differ in sampling mode or wavelength; field changes include detuning. '
    explanation += 'Selected-resonance snapshots may switch branches; overlap is evidence of similarity and does not certify mode identity.'
    payload = dict(reference=reference_id, current=current_id, alignment=alignment, xy_layer=layer, energy_flow_arrows=bool(arrows),
                   reference_descriptor=before, current_descriptor=after, comparison=comparison, interpretation=explanation)
    return figure, conditions, metrics, explanation, payload


def save_comparison(library, reference_id, current_id, layer='', alignment='Physical coordinates', arrows=False):
    figure, conditions, metrics, explanation, payload = compare_saved(library, reference_id, current_id, layer, alignment, arrows)
    directory = library.runs / ('field_tracking_' + uuid.uuid4().hex)
    directory.mkdir()
    write_json(directory / 'field_comparison.json', payload)
    conditions.to_csv(directory / 'design_conditions.csv', index=False)
    metrics.to_csv(directory / 'field_comparison_metrics.csv', index=False)
    figure.savefig(directory / 'field_comparison.png', dpi=160)
    plt.close(figure)
    for label, identifier in (('reference', reference_id), ('current', current_id)):
        source = _safe_directory(library, identifier)
        shutil.copy2(source / 'electric_fields.csv', directory / (label + '_electric_fields.csv'))
        shutil.copy2(source / 'field_model.json', directory / (label + '_field_model.json'))
    library.record(directory, kind='field comparison', status='complete', title='Electric-field comparison',
                   notes=f'Reference {reference_id}; current {current_id}')
    return library.export(directory.name), 'Saved comparison, raw samples, descriptors, models, metrics and plot to Saved work. Your comparison ZIP is ready to download.'


def build_field_tracking_ui(app, wrap_tab=True):
    def refresh(mode, query, wavelength, previous_reference=None, previous_current=None):
        choices = saved_datasets(app.LIBRARY, mode, query, wavelength)
        before, after, identifiers, position = dataset_selection(choices, previous_reference, previous_current)
        status = (f'**{len(identifiers)} saved snapshots.** Choose a reference and a design to compare. '
                  'The slider follows saved run order and numeric design order; it is not a time axis.') if identifiers else (
                  '**No matching fields yet.** Calculate a field map or run optimization with field learning enabled, then refresh. '
                  'Clear filters to see all saved fields.')
        return (gr.update(choices=choices, value=before), gr.update(choices=choices, value=after),
                identifiers, gr.update(minimum=1, maximum=max(2, len(identifiers)), value=position,
                                       interactive=bool(identifiers)), status)

    def update_layers(reference, current, selected):
        choices, value = common_layers(app.LIBRARY, reference, current, selected)
        return gr.update(choices=choices, value=value, interactive=bool(choices))

    def select_step(step, identifiers):
        if not identifiers:
            return gr.skip()
        return identifiers[min(len(identifiers), max(1, int(step))) - 1]

    def preview_ui(reference, current, layer, alignment, arrows=False):
        if not reference or not current:
            return None, pd.DataFrame(columns=['Condition', 'Reference', 'Current', 'Changed']), pd.DataFrame(columns=['Metric', 'Reference', 'Current']), 'Choose two saved field snapshots to see their maps and field changes.', comparison_summary({})
        if not layer:
            _, layer = common_layers(app.LIBRARY, reference, current)
        try:
            figure, conditions, metrics, message, payload = compare_saved(app.LIBRARY, reference, current, layer, alignment, arrows)
            plt.close(figure)
            return figure, conditions, metrics, message, comparison_summary(payload)
        except Exception as exc:
            return None, pd.DataFrame(columns=['Condition', 'Reference', 'Current', 'Changed']), pd.DataFrame(columns=['Metric', 'Reference', 'Current']), '**Error:** ' + html.escape(str(exc)), comparison_summary({})

    def preview(reference, current, layer, alignment, arrows=False):
        return preview_ui(reference, current, layer, alignment, arrows)[:4]

    def save(reference, current, layer, alignment, arrows=False):
        try:
            return save_comparison(app.LIBRARY, reference, current, layer, alignment, arrows)
        except Exception as exc:
            return None, '**Error:** ' + html.escape(str(exc))

    initial = saved_datasets(app.LIBRARY)
    before, after, initial_ids, position = dataset_selection(initial)
    layer_choices, selected_layer = common_layers(app.LIBRARY, before, after)
    with gr.Tab('Compare saved fields') if wrap_tab else nullcontext():
        gr.Markdown('### Track field changes\nCompare two saved designs on a shared intensity scale. Choose the same sampling mode to follow changes at the target wavelength or along a resonance.')
        with gr.Group(elem_classes=['card']):
            with gr.Row():
                mode = gr.Dropdown(list(MODES), value='All saved fields', label='Which fields?', scale=2)
                query = gr.Textbox(label='Search saved designs', placeholder='Run title, layer, material or shape…', scale=3)
                refresh_button = gr.Button('Refresh saved fields', scale=1)
            with gr.Accordion('Filter by exact sample wavelength', open=False):
                wavelength = gr.Number(0, minimum=0, label='Sample wavelength (nm)', info='Use 0 to include all wavelengths. This filters saved samples; it does not run a simulation.')
            with gr.Row():
                reference = gr.Dropdown(initial, value=before, label='Reference design', info='The baseline held fixed while you browse.', filterable=True)
                current = gr.Dropdown(initial, value=after, label='Compare with', info='Move through this selection using the slider below.', filterable=True)
            identifiers = gr.State(initial_ids)
            step = gr.Slider(1, max(2, len(initial_ids)), value=position, step=1, interactive=bool(initial_ids), label='Browse comparison designs')
            dataset_status = gr.Markdown(f'{len(initial_ids)} complete snapshots available. Refresh after a new field calculation or optimization.')
        with gr.Row():
            layer = gr.Dropdown(layer_choices, value=selected_layer, label='Layer to view from above (XY)', info='Only finite layers shared by both designs appear.', scale=2)
            alignment = gr.Dropdown(['Physical coordinates', 'Layer-relative coordinates'], value='Physical coordinates', label='Align maps by', info='Layer-relative coordinates make different sizes and thicknesses easier to compare.', scale=2)
            compare = gr.Button('Compare fields', variant='primary', scale=1)
        arrows = gr.Checkbox(False, label='Show energy-flow direction arrows', info='Requires saved magnetic fields. All arrows have equal length; direction alone is shown.')
        plot = gr.Plot(label='Reference and current electric fields — shared intensity scale')
        message = gr.Markdown('Choose **Compare fields** to load the selected maps.')
        summary = gr.Dataframe(comparison_summary({}), interactive=False, label='What changed in each layer?', max_height=300)
        with gr.Accordion('Field measurements and full design conditions', open=False):
            gr.Markdown('Confinement measures the fraction of integrated |E|² in a region. Centroid and hotspot coordinates use µm; overlap ranges from 0 to 1. Undefined centroids can occur for spatially uniform periodic fields. Training grids provide coarse samples at three depths per layer.')
            metrics = gr.Dataframe(pd.DataFrame(columns=['Metric', 'Reference', 'Current']), interactive=False, label='Confinement, position, spread and overlap', max_height=420)
            conditions = gr.Dataframe(pd.DataFrame(columns=['Condition', 'Reference', 'Current', 'Changed']), interactive=False, label='All design conditions and sampled optical constants', max_height=360)
        with gr.Row():
            save_button = gr.Button('Save comparison & create download', variant='secondary')
            bundle = gr.File(label='Download comparison ZIP', interactive=False)
        gr.Markdown('The ZIP includes the plot, design conditions, measurements and original complex field samples. A copy is kept in **Saved work**.')
        inputs = [reference, current, layer, alignment, arrows]
        outputs = [plot, conditions, metrics, message]
        ui_outputs = [*outputs, summary]
        refresh_inputs = [mode, query, wavelength, reference, current]
        refresh_outputs = [reference, current, identifiers, step, dataset_status]
        for event in (refresh_button.click, mode.input, query.submit, wavelength.submit):
            event(refresh, refresh_inputs, refresh_outputs, api_visibility='private').then(
                update_layers, [reference, current, layer], layer, api_visibility='private')
        for dropdown in (reference, current):
            dropdown.input(update_layers, [reference, current, layer], layer, api_visibility='private').then(
                preview_ui, inputs, ui_outputs, api_visibility='private')
        step.release(select_step, [step, identifiers], current, api_name='select_field_tracking_step').then(
            update_layers, [reference, current, layer], layer, api_visibility='private').then(
            preview_ui, inputs, ui_outputs, api_visibility='private')
        for component in (layer, alignment, arrows):
            component.input(preview_ui, inputs, ui_outputs, api_visibility='private')
        compare.click(preview_ui, inputs, ui_outputs, api_visibility='private')
        save_button.click(save, inputs, [bundle, message], api_visibility='private')
        # Keep existing client endpoints and argument types while the GUI uses named selectors.
        legacy_layer = gr.Textbox(visible=False)
        legacy_list = gr.Button(visible=False)
        legacy_compare = gr.Button(visible=False)
        legacy_save = gr.Button(visible=False)
        legacy_list.click(lambda m, q, w: refresh(m, q, w), [mode, query, wavelength], refresh_outputs, api_name='list_field_tracking_datasets')
        legacy_compare.click(preview, [reference, current, legacy_layer, alignment, arrows], outputs, api_name='compare_saved_fields')
        legacy_save.click(save, [reference, current, legacy_layer, alignment, arrows], [bundle, message], api_name='save_field_comparison')
