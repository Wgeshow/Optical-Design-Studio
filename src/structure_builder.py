"""Form-based multilayer editing; canonical project tables remain unchanged."""
import copy
import html
import json
import math

from gradio_compat import gr
import pandas as pd

from model import MAT_COLS, LAYER_COLS, PAT_COLS


def table(value, columns):
    if value is None:
        return pd.DataFrame(columns=columns)
    if hasattr(value,'model_dump'):
        value=value.model_dump()
    if isinstance(value,dict) and 'data' in value:
        data=pd.DataFrame(value['data'],columns=value.get('headers') or columns)
    else:
        data = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value, columns=columns)
    return data.reindex(columns=columns).dropna(how='all').reset_index(drop=True)


def rows(value, columns):
    result = table(value, columns).astype(object)
    return result.where(pd.notna(result), None).to_dict('records')


def finite(value, label, positive=False):
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(label + ' must be a number.') from None
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(label + (' must be greater than zero.' if positive else ' must be finite.'))
    return result


def identifier(value, label):
    result = str(value or '').strip()
    if not result or result.lower() in ('nan','none') or any(ord(c) < 32 for c in result):
        raise ValueError(label + ' needs a nonempty name without line breaks.')
    return result


def scale(unit):
    if unit not in ('nm', 'µm'):
        raise ValueError('Choose nm or µm for dimensions.')
    return .001 if unit == 'nm' else 1.


def unique_name(base, names):
    if base not in names:
        return base
    i = 2
    while f'{base}_{i}' in names:
        i += 1
    return f'{base}_{i}'


def validate_structure(materials, layers, patterns):
    mats, stack, regions = rows(materials, MAT_COLS), rows(layers, LAYER_COLS), rows(patterns, PAT_COLS)
    names = [identifier(m['Name'], 'Material') for m in mats]
    if len(set(names)) != len(names):
        raise ValueError('Material names must be unique. Resolve duplicates in Materials first.')
    layer_names = [identifier(row['Name'], 'Layer') for row in stack]
    if len(stack) < 3 or len(set(layer_names)) != len(layer_names):
        raise ValueError('Use at least three uniquely named layers: incident medium, device, and exit medium.')
    if len(stack) > 5000:
        raise ValueError('The structure builder supports up to 5,000 layers.')
    for i, row in enumerate(stack):
        row['Name'] = layer_names[i]
        if row['Material'] not in names:
            raise ValueError(f"Layer {row['Name']}: choose an existing material.")
        t = finite(row['Thickness_um'], 'Thickness')
        if i in (0, len(stack) - 1):
            if t != 0:
                raise ValueError('The first and last media must have thickness 0 (semi-infinite).')
        elif t < 0:
            raise ValueError('Layer thickness cannot be negative.')
    for region in regions:
        if region['Layer'] not in layer_names or region['Material'] not in names:
            raise ValueError('Every region needs an existing layer and material.')
        if region['Shape'] not in ('circle', 'ellipse', 'rectangle'):
            raise ValueError('Choose circle, ellipse, or rectangle.')
        finite(region['SizeX_um'], 'Region X size', positive=True)
        if region['Shape'] != 'circle':
            finite(region['SizeY_um'], 'Region Y size', positive=True)
        else:
            if finite(region['SizeY_um'], 'Region Y size') < 0:
                raise ValueError('Region Y size cannot be negative.')
        for key in ('CenterX_um', 'CenterY_um', 'Angle_deg'):
            finite(region[key], key)
    return mats, stack, regions


def material_catalog(app, materials):
    """Current rows and saved versions are distinct; choosing never overwrites a row."""
    catalog = {}
    for row in rows(materials, MAT_COLS):
        name = str(row['Name'] or '').strip()
        if name:
            catalog['current:' + name] = (name + ' · in this structure', row)
    for label, value in app.PRESETS.items():
        catalog['builtin:' + label] = (label + ' · built-in', dict(zip(MAT_COLS, value)))
    for key, record in app.LIBRARY.presets().items():
        catalog['saved:' + key] = (key, copy.deepcopy(record['project']['materials'][0]))
    return catalog


def resolve_material(app, materials, choice):
    data = rows(materials, MAT_COLS)
    catalog = material_catalog(app, materials)
    if choice not in catalog:
        raise ValueError('Choose a material from the dropdown. Refresh if its preset was removed.')
    row = copy.deepcopy(catalog[choice][1])
    if choice.startswith('current:'):
        return data, row['Name']
    name = identifier(row['Name'], 'Material')
    existing = {str(m['Name']): m for m in data}
    if name in existing and existing[name] == row:
        return data, name
    row['Name'] = unique_name(name, set(existing))
    data.append(row)
    return data, row['Name']


def mutate_structure(app, materials, layers, patterns, selected, action, **values):
    """Atomic edit: work on copies, validate everything, then return the new tables."""
    mats, stack, regions = rows(materials, MAT_COLS), rows(layers, LAYER_COLS), rows(patterns, PAT_COLS)
    before = dict(layers=copy.deepcopy(stack), patterns=copy.deepcopy(regions))
    names = [r['Name'] for r in stack]
    if selected not in names:
        raise ValueError('Select a layer first.')
    index = names.index(selected)
    halfspace = index in (0, len(stack)-1)
    if action == 'apply':
        name = identifier(values.get('name'), 'Layer')
        if name != selected and name in names:
            raise ValueError('That layer name is already used. Choose a unique name.')
        mats, material = resolve_material(app, mats, values.get('material'))
        thickness = 0. if halfspace else finite(values.get('thickness'), 'Layer thickness', True) * scale(values.get('unit'))
        stack[index] = dict(Name=name, Material=material, Thickness_um=thickness)
        for region in regions:
            if region['Layer'] == selected:
                region['Layer'] = name
        selected = name
    elif action in ('above', 'below'):
        mats, material = resolve_material(app, mats, values.get('material'))
        requested = identifier(values.get('name') or 'Layer', 'Layer')
        selected = unique_name(requested, set(names))
        raw_thickness = finite(values.get('thickness'), 'New layer thickness')
        thickness = .1 if halfspace and raw_thickness == 0 else finite(raw_thickness, 'New layer thickness', True) * scale(values.get('unit'))
        position = min(max(index + int(action == 'below'), 1), len(stack)-1)
        stack.insert(position, dict(Name=selected, Thickness_um=thickness, Material=material))
    elif action == 'duplicate':
        if halfspace:
            raise ValueError('Only finite layers can be duplicated. Add a new layer beside this medium.')
        selected = unique_name(str(selected) + '_copy', set(names))
        duplicate = dict(stack[index], Name=selected)
        stack.insert(index+1, duplicate)
        regions.extend(dict(r, Layer=selected) for r in list(regions) if r['Layer'] == names[index])
    elif action == 'delete':
        if halfspace or len(stack) <= 3:
            raise ValueError('Keep both outer media and at least one finite layer.')
        stack.pop(index)
        regions = [r for r in regions if r['Layer'] != selected]
        selected = stack[min(index, len(stack)-2)]['Name']
    elif action in ('up', 'down'):
        other = index + (-1 if action == 'up' else 1)
        if halfspace or other <= 0 or other >= len(stack)-1:
            raise ValueError('Finite layers must stay between the incident and exit media.')
        stack[index], stack[other] = stack[other], stack[index]
    elif action == 'repeat':
        start, end = values.get('start'), values.get('end')
        if start not in names[1:-1] or end not in names[1:-1]:
            raise ValueError('Choose the first and last finite layer of the repeated block.')
        lo, hi = names.index(start), names.index(end)
        if hi < lo:
            raise ValueError('The block end must be at or below its start.')
        count = finite(values.get('count'), 'Additional copies')
        if not count.is_integer() or count < 1 or count > 100:
            raise ValueError('Additional copies must be a whole number from 1 to 100.')
        block = copy.deepcopy(stack[lo:hi+1])
        if len(stack) + len(block)*int(count) > 5000:
            raise ValueError('This repeat would exceed 5,000 layers.')
        block_regions = [r for r in regions if r['Layer'] in names[lo:hi+1]]
        additions, used = [], set(names)
        for _ in range(int(count)):
            mapping = {}
            for layer in block:
                name = unique_name(str(layer['Name']) + '_copy', used)
                used.add(name)
                mapping[layer['Name']] = name
                additions.append(dict(layer, Name=name))
            regions.extend(dict(r, Layer=mapping[r['Layer']]) for r in block_regions)
        stack[hi+1:hi+1] = additions
        selected = additions[0]['Name']
    else:
        raise ValueError('Unknown structure action.')
    validate_structure(mats, stack, regions)
    before.update(after_layers=copy.deepcopy(stack), after_patterns=copy.deepcopy(regions))
    return table(mats, MAT_COLS), table(stack, LAYER_COLS), table(regions, PAT_COLS), selected, before


def mutate_region(app, materials, layers, patterns, layer, region_id, action, **values):
    mats, stack, regions = rows(materials, MAT_COLS), rows(layers, LAYER_COLS), rows(patterns, PAT_COLS)
    before = dict(layers=copy.deepcopy(stack), patterns=copy.deepcopy(regions))
    finite_names = [r['Name'] for r in stack[1:-1]]
    if layer not in finite_names:
        raise ValueError('Choose a finite layer for holes and material regions.')
    index = None
    if region_id not in (None, '', 'new'):
        try:
            index = int(region_id)
        except (ValueError, TypeError):
            raise ValueError('Choose a region first.') from None
        if index < 0 or index >= len(regions) or regions[index]['Layer'] != layer:
            raise ValueError('That region no longer belongs to the selected layer. Select it again.')
    if action in ('apply', 'add'):
        if action == 'apply' and index is None:
            raise ValueError('Choose an existing region, or use Add region.')
        shape = values.get('shape')
        if shape not in ('circle', 'ellipse', 'rectangle'):
            raise ValueError('Choose circle, ellipse, or rectangle.')
        mats, material = resolve_material(app, mats, values.get('material'))
        factor = scale(values.get('unit'))
        region = dict(Shape=shape, Layer=layer, Material=material,
                      CenterX_um=finite(values.get('x'), 'Center X')*factor,
                      CenterY_um=finite(values.get('y'), 'Center Y')*factor,
                      SizeX_um=finite(values.get('sx'), 'X size', True)*factor,
                      SizeY_um=0. if shape == 'circle' else finite(values.get('sy'), 'Y size', True)*factor,
                      Angle_deg=finite(values.get('angle'), 'Rotation'))
        if action == 'add':
            regions.append(region)
            index = len(regions)-1
        else:
            regions[index] = region
    elif action == 'copy':
        if index is None:
            raise ValueError('Choose a region to duplicate.')
        regions.append(dict(regions[index]))
        index = len(regions)-1
    elif action == 'delete':
        if index is None:
            raise ValueError('Choose a region to delete.')
        regions.pop(index)
        index = next((i for i,r in enumerate(regions) if r['Layer'] == layer), None)
    else:
        raise ValueError('Unknown region action.')
    validate_structure(mats, stack, regions)
    before.update(after_layers=copy.deepcopy(stack), after_patterns=copy.deepcopy(regions))
    return table(mats, MAT_COLS), table(stack, LAYER_COLS), table(regions, PAT_COLS), str(index) if index is not None else 'new', before


def restore_structure(materials, layers, patterns, snapshot):
    if not snapshot:
        raise ValueError('There is no structure edit to undo.')
    if rows(layers,LAYER_COLS) != snapshot['after_layers'] or rows(patterns,PAT_COLS) != snapshot['after_patterns']:
        raise ValueError('The structure has changed outside this editor. Make a new edit before using undo.')
    old_l, old_p = table(snapshot['layers'],LAYER_COLS), table(snapshot['patterns'],PAT_COLS)
    validate_structure(materials,old_l,old_p)
    return old_l,old_p


def layer_choices(layers, finite_only=False):
    stack = rows(layers, LAYER_COLS)
    return [(f"{i+1:03d} · {r['Name']} · {r['Material']}" +
             (' · incident medium' if i == 0 else ' · exit medium' if i == len(stack)-1 else ''), r['Name'])
            for i,r in enumerate(stack) if not finite_only or 0 < i < len(stack)-1]


def region_choices(patterns, layer):
    return [('New region', 'new')] + [(f"{j+1} · {r['Shape']} · {r['Material']} · ({float(r['CenterX_um']):g}, {float(r['CenterY_um']):g}) µm", str(i))
         for j,(i,r) in enumerate((i,r) for i,r in enumerate(rows(patterns, PAT_COLS)) if r['Layer'] == layer)]


def editor_revision_scripts(key, output_count):
    """Issue browser-local revisions and reject late editor responses.

    Revision checks run when applying a response, rather than only when its
    server callback starts. That distinction matters when a user selects another
    layer while a previous response is in flight.
    """
    slot = json.dumps('s4_structure_editor_' + str(key))
    issue = f'''(...args) => {{
        const key = {slot};
        const revision = (window[key] || 0) + 1;
        window[key] = revision;
        return [...args.slice(0, -1), revision];
    }}'''
    apply = f'''(patch) => {{
        if (!patch || patch.revision !== window[{slot}]) {{
            return Array.from({{length: {output_count}}}, () => ({{__type__: "update"}}));
        }}
        return patch.updates;
    }}'''
    invalidate = f'''() => {{ window[{slot}] = (window[{slot}] || 0) + 1; }}'''
    return issue,apply,invalidate


def stack_view(layers, patterns, selected, ax, ay):
    from structure_preview import material_color
    stack, regions = rows(layers, LAYER_COLS), rows(patterns, PAT_COLS)
    total = sum(float(r['Thickness_um'] or 0) for r in stack[1:-1])
    content = []
    for i,r in enumerate(stack):
        name, material = str(r['Name']), str(r['Material'])
        color = material_color(material)
        description = 'Semi-infinite incident medium' if i == 0 else 'Semi-infinite exit medium' if i == len(stack)-1 else f"{float(r['Thickness_um'])*1000:g} nm"
        count = sum(p['Layer'] == r['Name'] for p in regions)
        active = 'outline:2px solid #2563eb;outline-offset:-2px;' if name == selected else ''
        content.append(f'<div style="display:flex;gap:12px;padding:9px 12px;border-bottom:1px solid #d4d8df;{active}"><span style="min-width:35px;color:#606875">{i+1:03d}</span><span style="width:20px;background:{color};border-radius:3px"></span><span style="flex:1"><b>{html.escape(name)}</b><br><span>{html.escape(material)}</span></span><span style="text-align:right">{description}<br><small>{count} region' + ('s' if count != 1 else '') + '</small></span></div>')
    return (f'<div class="stack-summary"><p><b>{max(0,len(stack)-2)} finite layers · {total*1000:g} nm total thickness</b><br>Top → bottom · lattice {html.escape(str(ax))} × {html.escape(str(ay))} µm</p>'
            '<div style="max-height:530px;overflow-y:auto;border:1px solid #d4d8df;border-radius:8px">' + ''.join(content) +
            '</div><small>Layer bands are schematic, not to scale. Blue outline marks the selected layer.</small></div>')


def build_structure_builder(app, materials, layers, patterns, ax, ay):
    initial_m, initial_l, initial_p = app.DEFAULT_MATERIALS, app.DEFAULT_LAYERS, app.DEFAULT_PATTERNS
    initial_name = str(initial_l.iloc[1]['Name'])
    initial_layer_material = 'current:' + str(initial_l.iloc[1]['Material'])
    initial_region_id = next((str(i) for i,r in initial_p.iterrows() if r['Layer'] == initial_name),'new')
    initial_region_material = 'current:' + (str(initial_p.loc[int(initial_region_id),'Material']) if initial_region_id != 'new' else str(initial_m.iloc[0]['Name']))
    initial_catalog = material_catalog(app, initial_m)
    material_options = [(label, key) for key,(label,_) in initial_catalog.items()]
    undo = gr.State(None)
    previous_unit = gr.State('nm')
    form_layer = gr.Textbox(initial_name,visible=False)
    form_region = gr.Textbox(initial_region_id,visible=False)
    gr.Markdown('Select a layer, choose its material, and apply your edits. Duplicate layers or repeat a block to build large structures.')
    selected_layer = gr.Dropdown(choices=layer_choices(initial_l), value=initial_name, label='Layer to edit', filterable=True, allow_custom_value=False)
    from structure_preview_ui import build_structure_preview
    preview = build_structure_preview(layers,patterns,selected_layer,ax,ay,initial_l,initial_p,initial_name)
    with gr.Row():
        with gr.Column(scale=4):
            stack = gr.HTML(stack_view(initial_l, initial_p, initial_name, .77, .77))
        with gr.Column(scale=7):
            with gr.Row():
                layer_name = gr.Textbox(value=initial_name, label='Layer name', scale=2)
                unit = gr.Dropdown(['nm', 'µm'], value='nm', label='Dimension unit', scale=1)
            with gr.Row():
                layer_material = gr.Dropdown(material_options, value=initial_layer_material, label='Layer material', filterable=True, scale=3)
                thickness = gr.Number(value=float(initial_l.iloc[1]['Thickness_um'])*1000, minimum=0, label='Thickness (nm)', scale=1)
            gr.Markdown('Edits become part of the structure when you click **Apply layer**. The first and last media are semi-infinite; their thickness stays zero.')
            apply_layer = gr.Button('Apply layer', variant='primary')
            with gr.Row():
                above = gr.Button('Add above')
                below = gr.Button('Add below')
                duplicate = gr.Button('Duplicate layer')
            with gr.Row():
                up = gr.Button('Move up ↑')
                down = gr.Button('Move down ↓')
                delete = gr.Button('Delete layer', variant='stop')
            gr.Markdown('**Add above/below** uses this material and thickness; beside an outer medium, the new layer starts at 100 nm. A unique name is assigned if needed. Deleting a layer also removes its regions.')
            with gr.Accordion('Repeat a layer block', open=False):
                gr.Markdown('Copies are inserted immediately after the block. Each copied layer keeps its material and all its holes/regions.')
                with gr.Row():
                    block_start = gr.Dropdown(layer_choices(initial_l, True), value=initial_name, label='First layer in block', filterable=True)
                    block_end = gr.Dropdown(layer_choices(initial_l, True), value=initial_name, label='Last layer in block', filterable=True)
                    copies = gr.Number(value=1, minimum=1, maximum=100, precision=0, label='Additional copies')
                repeat = gr.Button('Repeat block')
            undo_button = gr.Button('Undo last structure edit', interactive=False)
    status = gr.Markdown('Ready. Choose a layer to begin.')
    with gr.Accordion('Holes and material regions in the selected layer', open=True):
        gr.Markdown('Choose **Air** to make a hole, or any other material to make an inclusion. Multiple regions can be added to each finite layer. Use Apply region to commit edits.')
        with gr.Row():
            selected_region = gr.Dropdown(region_choices(initial_p, initial_name), value=initial_region_id, label='Region to edit', filterable=True)
            shape = gr.Dropdown(['circle', 'ellipse', 'rectangle'], value='circle', label='Shape')
            region_material = gr.Dropdown(material_options, value=initial_region_material, label='Fill material', filterable=True)
        with gr.Row():
            sx = gr.Number(value=100, label='Radius (nm)', minimum=0)
            sy = gr.Number(value=100, label='Y radius (nm)', minimum=0, visible=False)
        with gr.Accordion('Position and rotation', open=False):
            with gr.Row():
                cx = gr.Number(value=0, label='Center X (nm)')
                cy = gr.Number(value=0, label='Center Y (nm)')
                angle = gr.Number(value=0, label='Rotation (degrees)')
        with gr.Row():
            apply_region = gr.Button('Apply region', variant='primary')
            add_region = gr.Button('Add region')
            copy_region = gr.Button('Duplicate region')
            delete_region = gr.Button('Delete region', variant='stop')

    def refresh_materials(m, selected_m, selected_r):
        catalog = material_catalog(app, m)
        options = [(label, key) for key,(label,_) in catalog.items()]
        fallback = next(iter(catalog), None)
        # A preset-list refresh must not restore a past material choice after
        # the user has started editing another layer.
        return tuple(gr.update(choices=options) if selected in catalog else
                     gr.update(choices=options,value=fallback) for selected in (selected_m,selected_r))

    def dimension_labels(form_shape, dim_unit):
        if form_shape == 'rectangle':
            labels = 'Full width X', 'Full width Y'
        elif form_shape == 'ellipse':
            labels = 'X radius', 'Y radius'
        else:
            labels = 'Radius', 'Y radius'
        return gr.update(label=f'{labels[0]} ({dim_unit})'), gr.update(label=f'{labels[1]} ({dim_unit})', visible=form_shape != 'circle')

    def refresh(m, l, p, selected, current_region, dim_unit, start, end, lattice_x, lattice_y):
        stack_rows = rows(l, LAYER_COLS)
        choices = layer_choices(l)
        names = [r['Name'] for r in stack_rows]
        if not names:
            return [gr.skip()]*18
        selected = selected if selected in names else names[min(1,len(names)-1)]
        index = names.index(selected)
        row = stack_rows[index]
        factor = scale(dim_unit)
        options = [(label, key) for key,(label,_) in material_catalog(app,m).items()]
        rchoices = region_choices(p,selected)
        region_values = [value for _,value in rchoices]
        current_region = current_region if current_region in region_values else region_values[1] if len(region_values)>1 else 'new'
        finite_choices = layer_choices(l,True)
        finite_names = [value for _,value in finite_choices]
        return (gr.update(choices=choices,value=selected), row['Name'],
                gr.update(choices=options,value='current:'+str(row['Material'])),
                gr.update(value=float(row['Thickness_um'])/factor, label=f'Thickness ({dim_unit})', interactive=index not in (0,len(names)-1)),
                stack_view(l,p,selected,lattice_x,lattice_y),
                gr.update(choices=finite_choices,value=start if start in finite_names else (finite_names[0] if finite_names else None)),
                gr.update(choices=finite_choices,value=end if end in finite_names else (finite_names[-1] if finite_names else None)),
                gr.update(choices=rchoices,value=current_region),
                *region_form(m,p,selected,current_region,dim_unit))

    def refresh_editor(m, l, p, selected, *args):
        """Refresh form data without taking ownership of a user's selection.

        A queued request carries the selection at submission time. Sending that
        value back can reverse a newer dropdown choice, which starts another
        preview and makes switching layers appear to oscillate. Keep a valid
        current choice client-owned; only replace a layer that was removed.
        """
        result = list(refresh(m,l,p,selected,*args))
        if selected in {row['Name'] for row in rows(l,LAYER_COLS)}:
            result[0].pop('value',None)
        return result

    def region_form(m,p,selected,region_id,dim_unit):
        options = [(label,key) for key,(label,_) in material_catalog(app,m).items()]
        data = rows(p,PAT_COLS)
        factor = scale(dim_unit)
        try:
            row = data[int(region_id)]
            if row['Layer'] != selected:
                raise ValueError()
        except (ValueError,TypeError,IndexError):
            available = [str(r['Name']) for r in rows(m,MAT_COLS)]
            row = dict(Shape='circle',Material='Air' if 'Air' in available else available[0] if available else '',SizeX_um=.1,SizeY_um=.1,CenterX_um=0,CenterY_um=0,Angle_deg=0)
        dx,dy = dimension_labels(row['Shape'],dim_unit)
        dx['value'],dy['value'] = float(row['SizeX_um'])/factor, float(row['SizeY_um'] or .1)/factor
        return (row['Shape'],gr.update(choices=options,value='current:'+str(row['Material'])),dx,dy,
                gr.update(value=float(row['CenterX_um'])/factor,label=f'Center X ({dim_unit})'),
                gr.update(value=float(row['CenterY_um'])/factor,label=f'Center Y ({dim_unit})'),row['Angle_deg'],
                gr.update(interactive=region_id not in (None,'','new')),
                gr.update(interactive=region_id not in (None,'','new')),
                gr.update(interactive=region_id not in (None,'','new')))

    # Canonical table changes (including project loads/imports) refresh the editor.
    refresh_inputs = [materials,layers,patterns,selected_layer,selected_region,unit,block_start,block_end,ax,ay]
    refresh_outputs = [selected_layer,layer_name,layer_material,thickness,stack,block_start,block_end,selected_region,
                       shape,region_material,sx,sy,cx,cy,angle,apply_region,copy_region,delete_region]
    # Gradio can dispatch one change event for each output of a mutation. Separate
    # unqueued handlers then render intermediate tables out of order. Coalesce
    # those triggers and serialize every writer to the editor's visible values.
    # A queued selection may have disappeared after undo/project load. Bypass
    # component-choice validation so callbacks can validate the canonical tables
    # and replace stale selections. Gradio still resolves State and data schemas.
    editor_events = dict(queue=True,preprocess=False,concurrency_id='structure_builder_editor',concurrency_limit=1,
                         trigger_mode='always_last',show_progress='hidden')
    revision = gr.Number(0,visible=False)
    editor_patch = gr.JSON(visible=False)
    patch_outputs = [*refresh_outputs,form_layer,form_region,unit]
    issue_revision,apply_revision,invalidate_revision = editor_revision_scripts(selected_layer._id,len(patch_outputs))
    def guarded_refresh(*args):
        updates=list(refresh_editor(*args[:-1]))
        loaded_layer,loaded_region=updates[1],updates[7].get('value',args[4])
        for index in (1,2,7,8,9,10,11,12,13,14):
            value=updates[index]
            updates[index]=dict(value,interactive=True) if isinstance(value,dict) else gr.update(value=value,interactive=True)
        return dict(revision=args[-1],updates=[*updates,loaded_layer,loaded_region,gr.update(interactive=True)])
    def guarded_layer_selection(*args):
        values=list(args[:-2])
        if values[3] != args[-2]:
            # "New region" belongs to the current layer's form. When changing
            # layers, load that layer's first existing region instead of carrying
            # an empty region draft over from an unpatterned layer.
            values[4]=None
        return guarded_refresh(*values,args[-1])
    editor_patch.change(None,editor_patch,patch_outputs,js=apply_revision,
                        queue=False,api_visibility='private',show_progress='hidden')
    gr.on([materials.change,layers.change,patterns.change,ax.change,ay.change],guarded_refresh,
          [*refresh_inputs,revision],editor_patch,js=issue_revision,api_visibility='private',**editor_events)
    selected_layer.input(guarded_layer_selection,[*refresh_inputs,form_layer,revision],editor_patch,js=issue_revision,
                         api_visibility='private',**editor_events)
    # Preserve the explicit snapshot API: API callers ask for a complete view,
    # whereas automatic browser refreshes must not restore a past selection.
    sync_api = gr.Button(visible=False)
    sync_api.click(refresh,refresh_inputs,refresh_outputs,api_name='builder_select_layer',**editor_events)
    def convert_dimensions(old_unit,new_unit,t,dx,dy,x,y,form_shape):
        factor = scale(old_unit)/scale(new_unit)
        def converted(value):
            return None if value is None else float(value)*factor
        x_update,y_update = dimension_labels(form_shape,new_unit)
        x_update['value'],y_update['value'] = converted(dx),converted(dy)
        return (new_unit,gr.update(value=converted(t),label=f'Thickness ({new_unit})'),x_update,y_update,
                gr.update(value=converted(x),label=f'Center X ({new_unit})'),
                gr.update(value=converted(y),label=f'Center Y ({new_unit})'))
    unit.input(convert_dimensions,[previous_unit,unit,thickness,sx,sy,cx,cy,shape],
               [previous_unit,thickness,sx,sy,cx,cy],api_name='builder_dimension_unit',**editor_events)
    region_inputs = [materials,patterns,selected_layer,selected_region,unit]
    region_outputs = [shape,region_material,sx,sy,cx,cy,angle,apply_region,copy_region,delete_region]
    def guarded_region(*args):
        updates=list(region_form(*args[:-1]))
        for index in range(7):
            value=updates[index]
            updates[index]=dict(value,interactive=True) if isinstance(value,dict) else gr.update(value=value,interactive=True)
        return dict(revision=args[-1],updates=[*[gr.skip()]*8,*updates,gr.skip(),args[3],gr.skip()])
    selected_region.input(guarded_region,[*region_inputs,revision],editor_patch,js=issue_revision,
                          api_visibility='private',**editor_events)
    region_api = gr.Button(visible=False)
    region_api.click(region_form,region_inputs,region_outputs,api_name='builder_select_region',**editor_events)
    shape.input(dimension_labels,[shape,unit],[sx,sy],api_visibility='private',**editor_events)
    # Typing into a loaded form is also a newer user intent. A pending table
    # refresh must not erase an unsaved name, material, thickness, or region size.
    gr.on([component.input for component in (layer_name,layer_material,thickness,unit,shape,region_material,sx,sy,cx,cy,angle)],
          None,None,None,js=invalidate_revision,queue=False,api_visibility='private',show_progress='hidden')

    def final_refresh(event):
        # This event runs after the mutation's material, layer, pattern, and
        # selection outputs have all reached the browser, giving the last render
        # a complete committed project even if earlier change triggers coalesced.
        event.then(guarded_refresh,[*refresh_inputs,revision],editor_patch,js=issue_revision,
                   api_visibility='private',**editor_events)

    def layer_action(m,l,p,selected,name,mat,t,u,start,end,count, action):
        try:
            mm,ll,pp,ss,snapshot = mutate_structure(app,m,l,p,selected,action,name=name,material=mat,thickness=t,unit=u,start=start,end=end,count=count)
            if action == 'apply':
                row = ll.loc[ll.Name == ss].iloc[0]
                message = f"Saved {ss}: {row.Material}, {float(row.Thickness_um)*1000:g} nm."
            elif action == 'repeat':
                message = f'Applied repeat: added {int(count)} copies of {start} through {end}, including their regions.'
            elif action == 'delete':
                message = f'Deleted {selected} and its regions. Selected {ss}.'
            else:
                message = f'Applied {action}: {ss}.'
            return mm,ll,pp,gr.update(choices=layer_choices(ll),value=ss),snapshot,gr.update(interactive=True),message
        except (ValueError,TypeError,KeyError) as exc:
            return *[gr.skip()]*6,'**No changes applied:** '+html.escape(str(exc))

    layer_inputs = [materials,layers,patterns,selected_layer,layer_name,layer_material,thickness,unit,block_start,block_end,copies]
    layer_outputs = [materials,layers,patterns,selected_layer,undo,undo_button,status]
    for button,action in ((apply_layer,'apply'),(above,'above'),(below,'below'),(duplicate,'duplicate'),(up,'up'),(down,'down'),(delete,'delete'),(repeat,'repeat')):
        def invoke(*args, _action=action):
            return layer_action(*args,action=_action)
        def invoke_loaded(*args,_action=action):
            if args[3] != args[-1]:
                return *[gr.skip()]*6,'**Layer is still loading:** wait until the form shows the selected layer, then apply your edit.'
            return layer_action(*args[:-1],action=_action)
        event = button.click(invoke_loaded,[*layer_inputs,form_layer],layer_outputs,api_visibility='private',
                             queue=True,preprocess=False,concurrency_id='structure_builder_editor',concurrency_limit=1)
        final_refresh(event)
        api_button=gr.Button(visible=False)
        api_event=api_button.click(invoke,layer_inputs,layer_outputs,api_name='builder_layer_'+action,
                                 queue=True,preprocess=False,concurrency_id='structure_builder_editor',concurrency_limit=1)
        final_refresh(api_event)

    def region_action(m,l,p,selected,region_id,form_shape,mat,dx,dy,x,y,rotation,u,action):
        try:
            mm,ll,pp,rr,snapshot = mutate_region(app,m,l,p,selected,region_id,action,shape=form_shape,material=mat,sx=dx,sy=dy,x=x,y=y,angle=rotation,unit=u)
            return mm,ll,pp,gr.update(choices=region_choices(pp,selected),value=rr),snapshot,gr.update(interactive=True),'Region '+action+' applied. Use a distinct position when duplicating a region.' if action=='copy' else 'Region '+action+' applied.'
        except (ValueError,TypeError,KeyError) as exc:
            return *[gr.skip()]*6,'**No changes applied:** '+html.escape(str(exc))

    for button,action in ((apply_region,'apply'),(add_region,'add'),(copy_region,'copy'),(delete_region,'delete')):
        def invoke_region(*args,_action=action):
            return region_action(*args,action=_action)
        def invoke_loaded_region(*args,_action=action):
            if args[3] != args[-2] or args[4] != args[-1]:
                return *[gr.skip()]*6,'**Region is still loading:** wait until the form shows the selected layer and region, then apply your edit.'
            return region_action(*args[:-2],action=_action)
        action_inputs=[materials,layers,patterns,selected_layer,selected_region,shape,region_material,sx,sy,cx,cy,angle,unit]
        action_outputs=[materials,layers,patterns,selected_region,undo,undo_button,status]
        event = button.click(invoke_loaded_region,[*action_inputs,form_layer,form_region],action_outputs,api_visibility='private',
                     queue=True,preprocess=False,concurrency_id='structure_builder_editor',concurrency_limit=1)
        final_refresh(event)
        api_button=gr.Button(visible=False)
        api_event=api_button.click(invoke_region,action_inputs,action_outputs,api_name='builder_region_'+action,
                      queue=True,preprocess=False,concurrency_id='structure_builder_editor',concurrency_limit=1)
        final_refresh(api_event)

    def undo_edit(m,l,p,snapshot,selected):
        try:
            old_l,old_p = restore_structure(m,l,p,snapshot)
            names = list(old_l.Name)
            selected = selected if selected in names else names[1]
            return old_l,old_p,gr.update(choices=layer_choices(old_l),value=selected),None,gr.update(interactive=False),'Restored the previous structure. Material library additions are retained.'
        except (ValueError,TypeError,KeyError) as exc:
            return *[gr.skip()]*5,'**Undo unavailable:** '+html.escape(str(exc))
    event = undo_button.click(undo_edit,[materials,layers,patterns,undo,selected_layer],[layers,patterns,selected_layer,undo,undo_button,status],
                              api_name='builder_undo',queue=True,preprocess=False,concurrency_id='structure_builder_editor',concurrency_limit=1)
    final_refresh(event)
    return dict(selected_layer=selected_layer,layer_material=layer_material,region_material=region_material,stack=stack,
                refresh_materials=refresh_materials,refresh=refresh,refresh_inputs=refresh_inputs,refresh_outputs=refresh_outputs,
                refresh_editor=refresh_editor,sync_options=editor_events,preview=preview)
