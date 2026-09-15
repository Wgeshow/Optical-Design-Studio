"""Keep analysis controls attached to the applied, shared Structure records."""
import html
import math

from gradio_compat import gr
import pandas as pd

from model import LAYER_COLS, MAT_COLS, PAT_COLS

HOLE_COLS = ['Layer', 'Shape', 'MinX_um', 'MaxX_um', 'MinY_um', 'MaxY_um']


def records(value, columns):
    if value is None:
        return []
    if isinstance(value, pd.DataFrame):
        value = value.to_dict('records')
    elif isinstance(value, dict):
        value = value.get('data', [])
    result = []
    for row in value:
        row = row if isinstance(row, dict) else dict(zip(columns, row))
        cleaned = {key: None if isinstance(row.get(key), float) and math.isnan(row[key]) else row.get(key)
                   for key in columns}
        if any(item is not None and str(item).strip() for item in cleaned.values()):
            result.append(cleaned)
    return result


def air_materials(materials):
    """Match the explicit vacuum model required by the target optimizer."""
    result = set()
    for row in records(materials, MAT_COLS):
        try:
            if row['Model'] == 'constant_nk' and float(row['A']) == 1 and float(row['B']) == 0:
                result.add(str(row['Name']))
        except (TypeError, ValueError):
            pass
    return result


def structure_hole_ranges(materials, layers, patterns):
    """Seed one unambiguous existing air hole per finite layer at its current size."""
    finite = [row['Name'] for row in records(layers, LAYER_COLS)[1:-1]]
    air = air_materials(materials) if materials is not None else {'Air', 'air', 'Vacuum', 'vacuum'}
    grouped = {}
    for region in records(patterns, PAT_COLS):
        if region['Layer'] in finite and region['Material'] in air:
            grouped.setdefault(region['Layer'], []).append(region)
    result = []
    for layer in finite:
        candidates = grouped.get(layer, [])
        if len(candidates) != 1:
            continue
        region = candidates[0]
        shape = str(region['Shape']).lower()
        if shape not in ('circle', 'ellipse', 'rectangle'):
            continue
        try:
            x = float(region['SizeX_um'])
            y = 0. if shape == 'circle' else float(region['SizeY_um'])
            if not math.isfinite(x) or not math.isfinite(y) or x <= 0 or shape != 'circle' and y <= 0:
                continue
        except (TypeError, ValueError):
            continue
        result.append(dict(zip(HOLE_COLS, [layer, shape, x, x, y, y])))
    return result


def initial_hole_sync(materials, layers, patterns):
    source = structure_hole_ranges(materials, layers, patterns)
    return pd.DataFrame(source, columns=HOLE_COLS), dict(source=source, manual=[], excluded=[])


def sync_hole_ranges(value, previous, materials, layers, patterns):
    """Follow changed source holes while preserving manual limits and removals."""
    previous = previous or {}
    source = structure_hole_ranges(materials, layers, patterns)
    old = {row['Layer']: row for row in previous.get('source', [])}
    new = {row['Layer']: row for row in source}
    finite = {row['Name'] for row in records(layers, LAYER_COLS)[1:-1]}
    current = records(value, HOLE_COLS)
    present = {row['Layer'] for row in current}
    excluded = (set(previous.get('excluded', [])) | (set(old) - present)) & finite
    manual = set(previous.get('manual', [])) & finite
    result = []
    for row in current:
        layer = row['Layer']
        if layer not in finite:
            continue
        if layer not in manual and old.get(layer) == row:
            if layer in new:
                result.append(new[layer])
        else:
            result.append(row)
    present = {row['Layer'] for row in result}
    result.extend(row for row in source if row['Layer'] not in present | excluded)
    state = dict(source=source, manual=sorted(manual), excluded=sorted(excluded))
    return pd.DataFrame(result, columns=HOLE_COLS), state


def structure_summary(materials, layers, patterns, ax, ay):
    stack = records(layers, LAYER_COLS)
    finite = stack[1:-1]
    order = ' → '.join(html.escape(str(row['Name'])) for row in stack)
    return ('<div class="studio-hint"><strong>Shared Structure</strong> · '
            f'{len(finite)} finite layers · {len(records(patterns, PAT_COLS))} regions · '
            f'{len(records(materials, MAT_COLS))} materials · '
            f'lattice {html.escape(str(ax))} × {html.escape(str(ay))} µm<br>'
            f'{order}<br>Applied Structure edits are used by every new simulation, optimization, field map, '
            'and project save. Saved results keep the design that produced them.</div>')


def build_structure_summary(materials, layers, patterns, ax, ay):
    inputs = [materials, layers, patterns, ax, ay]
    view = gr.HTML(structure_summary(*(component.value for component in inputs)))
    gr.on([component.change for component in inputs], structure_summary, inputs, view,
          trigger_mode='always_last', concurrency_limit=1, preprocess=False,
          api_visibility='private', show_progress='hidden')
    return view
