"""Guided, validated editors for the existing canonical optimizer tables."""
import json
import math

import gradio as gr
import pandas as pd

from model import MAT_COLS, LAYER_COLS, PAT_COLS, number
from peak_optimizer import BOUND_COLS, grid_values
from structure_sync import initial_hole_sync, sync_hole_ranges


PARAMETERS = [
    ('Square lattice spacing (µm)', 'lattice_square'),
    ('Lattice spacing X (µm)', 'lattice_x'),
    ('Lattice spacing Y (µm)', 'lattice_y'),
    ('Layer thickness (µm)', 'thickness'),
    ('Layer material', 'layer_material'),
    ('Circle radius (µm)', 'radius'),
    ('Circle radius / lattice spacing', 'r_over_a'),
    ('Pattern size X (µm)', 'size_x'),
    ('Pattern size Y (µm)', 'size_y'),
    ('Pattern center X (µm)', 'center_x'),
    ('Pattern center Y (µm)', 'center_y'),
    ('Pattern rotation (degrees)', 'rotation'),
    ('Pattern material', 'pattern_material'),
]
PARAMETER_LABELS = {value: label for label, value in PARAMETERS}
PATTERN_PARAMETERS = {'radius', 'r_over_a', 'size_x', 'size_y', 'center_x', 'center_y', 'rotation', 'pattern_material'}
CATEGORICAL = {'layer_material', 'pattern_material'}
HOLE_COLS = ['Layer', 'Shape', 'MinX_um', 'MaxX_um', 'MinY_um', 'MaxY_um']


def rows(value, columns):
    if value is None:
        return []
    if isinstance(value, pd.DataFrame):
        value = value.to_dict('records')
    elif isinstance(value, dict) and 'data' in value:
        value = value['data']
    result = []
    for row in value:
        row = row if isinstance(row, dict) else dict(zip(columns, row))
        cleaned = {key: (None if item is None or isinstance(item, float) and math.isnan(item) else item)
                   for key, item in ((key, row.get(key)) for key in columns)}
        if any(item is not None and str(item).strip() for item in cleaned.values()):
            result.append(cleaned)
    return result


def names(value, columns=MAT_COLS):
    return list(dict.fromkeys(str(row['Name']).strip() for row in rows(value, columns) if row.get('Name')))


def finite_layers(value):
    return [str(row['Name']) for row in rows(value, LAYER_COLS)[1:-1] if row.get('Name')]


def target_choices(parameter, layers, patterns):
    if parameter.startswith('lattice_'):
        return [('Whole unit cell', '')]
    if parameter in ('thickness', 'layer_material'):
        candidates = rows(layers, LAYER_COLS)
        if parameter == 'thickness':
            candidates = candidates[1:-1]
        return [(f"{row['Name']} · {row['Material']}", str(row['Name'])) for row in candidates]
    candidates = []
    for index, row in enumerate(rows(patterns, PAT_COLS), 1):
        shape = str(row['Shape']).lower()
        if parameter in ('radius', 'r_over_a') and shape != 'circle':
            continue
        candidates.append((f"{row['Layer']} · {shape} {index} · {row['Material']}", str(index)))
    return candidates


def bound_label(row, layers, patterns):
    label = PARAMETER_LABELS.get(row['Parameter'], str(row['Parameter']))
    choices = dict((value, label) for label, value in target_choices(row['Parameter'], layers, patterns))
    target = choices.get(str(row.get('Target') or ''), str(row.get('Target') or 'Whole unit cell'))
    value = str(row.get('Choices') or '').replace(';', ', ') if row['Parameter'] in CATEGORICAL else f"{row.get('Min')} → {row.get('Max')}"
    return f'{label} · {target} · {value}'


def bound_keys(parameter, target):
    if parameter == 'lattice_square':
        return {'lattice_x', 'lattice_y'}
    if parameter.startswith('lattice_'):
        return {parameter}
    field = 'size_x' if parameter in ('radius', 'r_over_a') else parameter
    return {(field, str(target))}


def range_key(row):
    """Identify a bound by its meaning, so removing another row cannot retarget it."""
    return 'range:' + json.dumps([row['Parameter'], str(row.get('Target') or '')],
                                ensure_ascii=False, separators=(',', ':'))


def upsert_bound(value, parameter, target, minimum, maximum, step, materials, layers, patterns, selected_materials):
    if parameter not in PARAMETER_LABELS:
        raise ValueError('Choose a parameter to vary.')
    target = '' if parameter.startswith('lattice_') else str(target or '')
    valid_targets = {value for _, value in target_choices(parameter, layers, patterns)}
    if target not in valid_targets:
        raise ValueError('Choose a current layer or pattern for this parameter.')
    if parameter in CATEGORICAL:
        chosen = list(dict.fromkeys(selected_materials or []))
        if not chosen or any(material not in names(materials) for material in chosen):
            raise ValueError('Select at least one material from the project material library.')
        if any(';' in material for material in chosen):
            raise ValueError('Material names used in optimization must not contain semicolons.')
        row = dict(zip(BOUND_COLS, [parameter, target, None, None, None, ';'.join(chosen)]))
    else:
        low, high, delta = number(minimum, 'Minimum'), number(maximum, 'Maximum'), number(step, 'Step')
        if delta <= 0:
            raise ValueError('Step must be greater than zero, including for a fixed value.')
        grid_values(low, high, delta)
        if parameter == 'thickness' and low < 0:
            raise ValueError('Layer thickness cannot be negative.')
        if parameter not in ('thickness', 'center_x', 'center_y', 'rotation') and low <= 0:
            raise ValueError('Spacing, radius, and pattern sizes must be greater than zero.')
        if parameter == 'r_over_a' and high >= .6:
            raise ValueError('Every radius / lattice ratio must be below 0.6. Use a maximum such as 0.59.')
        row = dict(zip(BOUND_COLS, [parameter, target, low, high, delta, '']))
    result = rows(value, BOUND_COLS)
    existing = next((i for i, old in enumerate(result) if old['Parameter'] == parameter and str(old.get('Target') or '') == target), None)
    for i, old in enumerate(result):
        if i != existing and bound_keys(parameter, target) & bound_keys(str(old['Parameter']), old.get('Target')):
            raise ValueError('This range overlaps an existing bound. Remove the conflicting range first (for example square spacing versus X/Y, or radius versus radius / lattice).')
    if existing is None:
        result.append(row)
    else:
        result[existing] = row
    return pd.DataFrame(result, columns=BOUND_COLS)


def prune_bounds(value, materials, layers, patterns, patterns_changed=False):
    """Do not silently retarget a saved numeric pattern index after a structure edit."""
    result, removed = [], 0
    material_names = set(names(materials))
    for row in rows(value, BOUND_COLS):
        parameter = str(row['Parameter'])
        valid = parameter in PARAMETER_LABELS
        valid = valid and str(row.get('Target') or '') in {v for _, v in target_choices(parameter, layers, patterns)}
        valid = valid and not (patterns_changed and parameter in PATTERN_PARAMETERS)
        if parameter in CATEGORICAL:
            values = [item.strip() for item in str(row.get('Choices') or '').split(';') if item.strip()]
            # Preserve the requested set exactly; changing it could alter the meaning of a saved search.
            valid = valid and bool(values) and all(item in material_names for item in values)
        if valid:
            result.append(row)
        else:
            removed += 1
    return pd.DataFrame(result, columns=BOUND_COLS), removed


def build_bounds_editor(materials, layers, patterns, *, label='Design ranges', allowed=None):
    available = [(label, value) for label, value in PARAMETERS if allowed is None or value in allowed]
    initial_materials = materials.value
    initial_layers = layers.value
    initial_patterns = patterns.value
    parameter_value = available[0][1]
    with gr.Row():
        parameter = gr.Dropdown(available, value=parameter_value, label='What can change?')
        target = gr.Dropdown(target_choices(parameter_value, initial_layers, initial_patterns), value='', label='Where?', allow_custom_value=False)
    with gr.Row() as numeric_row:
        minimum = gr.Number(.1, label='Minimum (µm)')
        maximum = gr.Number(.2, label='Maximum (µm)')
        step = gr.Number(.01, minimum=0, label='Step (µm)', info='Both endpoints are included; equal limits keep a value fixed.')
    chosen_materials = gr.Dropdown(names(initial_materials), value=[], multiselect=True, label='Allowed materials', visible=False, allow_custom_value=False)
    hint = gr.Markdown('Choose one range at a time. Parameters without a range keep their current Structure values.')
    add = gr.Button('Add / update range', variant='secondary')
    overview = gr.Dataframe(value=[], headers=BOUND_COLS, column_count=(6, 'fixed'), row_count=(0, 'dynamic'),
                            datatype=['str', 'str', 'number', 'number', 'number', 'str'], interactive=False, label=label)
    with gr.Row():
        selected = gr.Dropdown([], value=None, label='Existing range', allow_custom_value=False, scale=3, interactive=False)
        edit = gr.Button('Load range into editor', scale=1, interactive=False)
        remove = gr.Button('Remove range', scale=1, interactive=False)
    status = gr.Markdown()
    pattern_snapshot = gr.State(rows(initial_patterns, PAT_COLS))

    def display(p, lay, pat, current_target, current_materials, mat):
        choices = target_choices(p, lay, pat)
        values = [value for _, value in choices]
        chosen = current_target if current_target in values else (values[0] if values else None)
        categorical = p in CATEGORICAL
        unit = 'degrees' if p == 'rotation' else 'ratio' if p == 'r_over_a' else 'µm'
        help_text = 'Select the materials the optimizer may use.' if categorical else 'Equal minimum and maximum keeps this parameter fixed.'
        if p in ('size_x', 'size_y'):
            help_text += ' Ellipse sizes are radii; rectangle sizes are full widths. Circle X is its radius.'
        if p == 'r_over_a':
            help_text += ' The ratio uses the smaller lattice spacing and must stay below 0.6.'
        return (gr.Dropdown(choices=choices, value=chosen), gr.Row(visible=not categorical),
                gr.Number(label=f'Minimum ({unit})'), gr.Number(label=f'Maximum ({unit})'), gr.Number(label=f'Step ({unit})'),
                gr.Dropdown(choices=names(mat), value=[x for x in (current_materials or []) if x in names(mat)], visible=categorical), help_text)

    display_inputs = [parameter, layers, patterns, target, chosen_materials, materials]
    display_outputs = [target, numeric_row, minimum, maximum, step, chosen_materials, hint]
    event_group = f'bounds-editor-{overview._id}'
    parameter.input(display, display_inputs, display_outputs, queue=True, trigger_mode='always_last',
                    concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')

    def add_range(value, p, dest, low, high, delta, mat, lay, pat, choices):
        try:
            updated = upsert_bound(value, p, dest, low, high, delta, mat, lay, pat, choices)
            return updated, 'Range saved. Add another parameter or start the search.'
        except ValueError as exc:
            return gr.skip(), '**Check this range:** ' + str(exc)

    add.click(add_range, [overview, parameter, target, minimum, maximum, step, materials, layers, patterns, chosen_materials],
              [overview, status], concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')

    def range_actions(value, selection):
        valid = any(range_key(row) == selection for row in rows(value, BOUND_COLS))
        return gr.Button(interactive=valid), gr.Button(interactive=valid)

    def list_ranges(value, lay, pat, selection):
        choices = [(bound_label(row, lay, pat), range_key(row)) for row in rows(value, BOUND_COLS)]
        selected_value = selection if selection in {key for _, key in choices} else None
        return (gr.Dropdown(choices=choices, value=selected_value, interactive=bool(choices)),
                *range_actions(value, selected_value))

    overview.change(list_ranges, [overview, layers, patterns, selected], [selected, edit, remove], trigger_mode='always_last',
                    concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')
    selected.input(range_actions, [overview, selected], [edit, remove], trigger_mode='always_last',
                   concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')

    def load_range(value, selection, lay, pat, mat):
        row = next((row for row in rows(value, BOUND_COLS) if range_key(row) == selection), None)
        if row is None:
            return (*[gr.skip() for _ in range(8)], 'Select a saved range from Existing range, then load it. Your editor values are unchanged.')
        _, invalid = prune_bounds([row], mat, lay, pat)
        if invalid:
            return (*[gr.skip() for _ in range(8)], 'This range refers to a material, layer, or pattern that changed. Select a current range or add it again. Your editor values are unchanged.')
        p = row['Parameter']
        chosen = [item.strip() for item in str(row.get('Choices') or '').split(';') if item.strip()]
        updates = display(p, lay, pat, row.get('Target') or '', chosen, mat)
        unit = 'degrees' if p == 'rotation' else 'ratio' if p == 'r_over_a' else 'µm'
        return (p, updates[0], updates[1], gr.Number(value=row.get('Min'), label=f'Minimum ({unit})'),
                gr.Number(value=row.get('Max'), label=f'Maximum ({unit})'), gr.Number(value=row.get('Step'), label=f'Step ({unit})'), updates[5], updates[6],
                'Range loaded. Change its values and use Add / update range to save.')

    edit.click(load_range, [overview, selected, layers, patterns, materials], [parameter, *display_outputs, status],
               concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')

    def remove_range(value, selection):
        data = rows(value, BOUND_COLS)
        index = next((i for i, row in enumerate(data) if range_key(row) == selection), None)
        if index is None:
            return gr.skip(), 'Select a saved range from Existing range before removing it. No ranges were changed.'
        data.pop(index)
        return pd.DataFrame(data, columns=BOUND_COLS), 'Range removed.'

    remove.click(remove_range, [overview, selected], [overview, status],
                 concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')

    def refresh(mat, lay, pat, p, destination, choices, value, previous_patterns):
        current_patterns = rows(pat, PAT_COLS)
        changed = current_patterns != (previous_patterns or [])
        updated, count = prune_bounds(value, mat, lay, pat, changed)
        note = f'Removed {count} range(s) whose material, layer, or pattern changed. Add those ranges again for the updated structure.' if count else gr.skip()
        return (*display(p, lay, pat, destination, choices, mat), updated if count else gr.skip(), note, current_patterns)

    gr.on(triggers=[materials.change, layers.change, patterns.change], fn=refresh,
          inputs=[materials, layers, patterns, parameter, target, chosen_materials, overview, pattern_snapshot],
          outputs=[*display_outputs, overview, status, pattern_snapshot], trigger_mode='always_last',
          concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')
    return overview


def upsert_hole(value, layer, shape, min_x, max_x, min_y, max_y, layers):
    if layer not in finite_layers(layers):
        raise ValueError('Choose a finite layer from the current structure.')
    if shape not in ('circle', 'ellipse', 'rectangle'):
        raise ValueError('Choose circle, ellipse, or rectangle.')
    low, high = number(min_x, 'Minimum X'), number(max_x, 'Maximum X')
    ly, hy = (0., 0.) if shape == 'circle' else (number(min_y, 'Minimum Y'), number(max_y, 'Maximum Y'))
    if low <= 0 or high < low or shape != 'circle' and (ly <= 0 or hy < ly):
        raise ValueError('Every size must be positive, with maximum at least the minimum.')
    result = rows(value, HOLE_COLS)
    row = dict(zip(HOLE_COLS, [layer, shape, low, high, ly, hy]))
    index = next((i for i, previous in enumerate(result) if previous['Layer'] == layer), None)
    if index is None:
        result.append(row)
    else:
        result[index] = row
    return pd.DataFrame(result, columns=HOLE_COLS)


def build_hole_editor(layers, patterns, materials=None):
    options = finite_layers(layers.value)
    initial_holes, initial_sync = initial_hole_sync(materials.value if materials is not None else None,
                                                   layers.value, patterns.value)
    sync_state = gr.State(initial_sync)
    material_source = materials if materials is not None else gr.State(None)
    with gr.Row():
        layer = gr.Dropdown(options, value=options[0] if options else None, label='PCS layer', allow_custom_value=False,
                            info='Choose a current Structure layer. Existing single air holes keep their position and rotation.')
        shape = gr.Dropdown([('Circle', 'circle'), ('Ellipse', 'ellipse'), ('Rectangle', 'rectangle')], value='circle', label='Air-hole shape', allow_custom_value=False)
    with gr.Row():
        min_x = gr.Number(.1, minimum=0, label='Minimum radius (µm)')
        max_x = gr.Number(.2, minimum=0, label='Maximum radius (µm)')
    with gr.Row(visible=False) as y_row:
        min_y = gr.Number(.1, minimum=0, label='Minimum Y radius (µm)')
        max_y = gr.Number(.2, minimum=0, label='Maximum Y radius (µm)')
    with gr.Row():
        add = gr.Button('Add / update layer hole')
        populate = gr.Button('Reset hole ranges to current structure sizes')
    overview = gr.Dataframe(value=initial_holes, headers=HOLE_COLS, column_count=(6, 'fixed'), row_count=(0, 'dynamic'), interactive=False,
                            label='Hole ranges by layer (µm)')
    with gr.Row():
        selected = gr.Dropdown([(f"{row['Layer']} · {row['Shape']}", row['Layer']) for row in initial_sync['source']],
                               value=None, label='Saved hole range', allow_custom_value=False, scale=3, interactive=not initial_holes.empty)
        edit = gr.Button('Load hole into editor', interactive=False)
        remove = gr.Button('Remove hole range', interactive=False)
    status = gr.Markdown('Single air holes follow Structure automatically at their current sizes. Set wider limits to optimize; your saved limits and removed-range choices are kept for existing layers. Add limits again after renaming a manually bounded layer. Layers with multiple air holes can be varied by pattern in Explore designs.')

    def dimensions(value):
        word = 'radius' if value == 'circle' else 'X radius' if value == 'ellipse' else 'full X width'
        y_word = 'Y radius' if value == 'ellipse' else 'full Y width'
        return gr.Number(label=f'Minimum {word} (µm)'), gr.Number(label=f'Maximum {word} (µm)'), gr.Row(visible=value != 'circle'), gr.Number(label=f'Minimum {y_word} (µm)'), gr.Number(label=f'Maximum {y_word} (µm)')

    event_group = f'hole-editor-{overview._id}'
    shape.input(dimensions, shape, [min_x, max_x, y_row, min_y, max_y], trigger_mode='always_last',
                concurrency_id=event_group, concurrency_limit=1, api_visibility='private')

    def add_hole(value, destination, kind, lx, hx, ly, hy, lay, previous):
        try:
            updated = upsert_hole(value, destination, kind, lx, hx, ly, hy, lay)
            state = dict(previous or {})
            state['manual'] = sorted(set(state.get('manual', [])) | {destination})
            state['excluded'] = sorted(set(state.get('excluded', [])) - {destination})
            return updated, 'Hole range saved.', state
        except ValueError as exc:
            return gr.skip(), '**Check this hole:** ' + str(exc), gr.skip()

    add.click(add_hole, [overview, layer, shape, min_x, max_x, min_y, max_y, layers, sync_state], [overview, status, sync_state],
              concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')

    def current_holes(lay, pat):
        result = []
        seen = set()
        for row in rows(pat, PAT_COLS):
            if row['Layer'] not in finite_layers(lay) or row['Layer'] in seen:
                continue
            seen.add(row['Layer'])
            result.append([row['Layer'], row['Shape'], row['SizeX_um'], row['SizeX_um'], row['SizeY_um'], row['SizeY_um']])
        return pd.DataFrame(result, columns=HOLE_COLS)

    def reset_holes(mat, lay, pat):
        value, state = initial_hole_sync(mat, lay, pat)
        return value, state, 'Hole ranges reset to the current single-air-hole sizes from Structure.'

    populate.click(reset_holes, [material_source, layers, patterns], [overview, sync_state, status],
                   concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')
    legacy_populate = gr.Button(visible=False)
    legacy_populate.click(current_holes, [layers, patterns], overview,
                          concurrency_id=event_group, concurrency_limit=1, api_name='populate_target_holes')

    def hole_actions(value, selection):
        valid = any(row['Layer'] == selection for row in rows(value, HOLE_COLS))
        return gr.Button(interactive=valid), gr.Button(interactive=valid)

    def selection_choices(value, selection):
        choices = [(f"{row['Layer']} · {row['Shape']}", str(row['Layer'])) for row in rows(value, HOLE_COLS)]
        selected_value = selection if selection in {key for _, key in choices} else None
        return (gr.Dropdown(choices=choices, value=selected_value, interactive=bool(choices)),
                *hole_actions(value, selected_value))

    overview.change(selection_choices, [overview, selected], [selected, edit, remove], trigger_mode='always_last',
                    concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')
    selected.input(hole_actions, [overview, selected], [edit, remove], trigger_mode='always_last',
                   concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')

    def load_hole(value, selection):
        row = next((row for row in rows(value, HOLE_COLS) if row['Layer'] == selection), None)
        if row is None:
            return (*[gr.skip() for _ in range(7)], 'Select a saved range from Saved hole range, then load it. Your editor values are unchanged.')
        kind = row['Shape']
        word = 'radius' if kind == 'circle' else 'X radius' if kind == 'ellipse' else 'full X width'
        y_word = 'Y radius' if kind == 'ellipse' else 'full Y width'
        return (row['Layer'], kind, gr.Number(value=row['MinX_um'], label=f'Minimum {word} (µm)'),
                gr.Number(value=row['MaxX_um'], label=f'Maximum {word} (µm)'), gr.Row(visible=kind != 'circle'),
                gr.Number(value=row['MinY_um'], label=f'Minimum {y_word} (µm)'),
                gr.Number(value=row['MaxY_um'], label=f'Maximum {y_word} (µm)'),
                'Hole range loaded. Change its sizes and use Add / update layer hole to save.')

    edit.click(load_hole, [overview, selected], [layer, shape, min_x, max_x, y_row, min_y, max_y, status],
               concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')

    def remove_hole(value, selection, previous=None):
        data = rows(value, HOLE_COLS)
        if not any(row['Layer'] == selection for row in data):
            return gr.skip(), 'Select a saved range from Saved hole range before removing it. No ranges were changed.', gr.skip()
        state = dict(previous or {})
        state['excluded'] = sorted(set(state.get('excluded', [])) | {selection})
        state['manual'] = sorted(set(state.get('manual', [])) - {selection})
        return pd.DataFrame([row for row in data if row['Layer'] != selection], columns=HOLE_COLS), 'Hole range removed.', state

    remove.click(remove_hole, [overview, selected, sync_state], [overview, status, sync_state],
                 concurrency_id=event_group, concurrency_limit=1, preprocess=False, api_visibility='private')

    def refresh(lay, value, destination, pat, mat, previous):
        options = finite_layers(lay)
        updated, state = sync_hole_ranges(value, previous, mat, lay, pat)
        changed = rows(value, HOLE_COLS) != rows(updated, HOLE_COLS)
        return (gr.Dropdown(choices=options, value=destination if destination in options else options[0] if options else None),
                updated if changed else gr.skip(),
                'Hole ranges synchronized with Structure. Manual limits and removed-range choices were kept for existing layers; add limits again for renamed layers.' if changed else gr.skip(), state)

    gr.on([layers.change, patterns.change, *([materials.change] if materials is not None else [])], refresh,
          [layers, overview, layer, patterns, material_source, sync_state], [layer, overview, status, sync_state],
          trigger_mode='always_last', concurrency_id=event_group, concurrency_limit=1,
          preprocess=False, api_visibility='private')
    return overview
