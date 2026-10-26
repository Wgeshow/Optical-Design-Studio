"""Select one periodic optical cell without resizing the finite electrical device.

S4 always repeats the prepared cell. Disabling selection uses the full device
footprint as a periodic supercell; it does not provide a finite optical solve.
Only boundary-crossing curved patterns are polygonized. Coupling averages are
taken from the actual finite-volume cells, with fractional XY overlap weights.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np

CURVE_SEGMENTS = 512


def _active_pc_arrays(device):
    layers={row['id'] for row in (device or {}).get('layers',[]) if row.get('enabled',True)}
    return [row for row in (device or {}).get('pc_arrays',[])
            if row.get('enabled',True) and row.get('layer_id') in layers]


def _pc_selection(device, pc_id=None):
    """Derive one PC-pitch cell around an actual enabled generated air hole.

    Even arrays have no hole at their geometric center. Use the nearest saved
    member so the default cell contains a whole hole rather than four corners.
    No geometry, member edits, or stored optical setting is changed.
    """
    arrays=_active_pc_arrays(device)
    if pc_id is not None:arrays=[row for row in arrays if row['id']==pc_id]
    for pc in reversed(arrays):
        holes=[row for row in device.get('shapes',[])
               if row.get('enabled',True) and row.get('pc_array_id')==pc['id']
               and row.get('layer_id')==pc['layer_id'] and row.get('material_id')=='air'
               and row.get('operation')=='void' and row.get('shape')=='circle']
        if not holes:continue
        hole=min(holes,key=lambda row:((row['cx_um']-pc['cx_um'])**2+
                                      (row['cy_um']-pc['cy_um'])**2,row['id']))
        return dict(enabled=True,width_um=pc['cell_width_um'],depth_um=pc['cell_depth_um'],
                    cx_um=hole['cx_um'],cy_um=hole['cy_um']),pc
    return None,None


def pc_unit_cell(device, pc_id=None):
    """Return the pitch cell selected from actual saved PC members, if any."""
    return _pc_selection(device,pc_id)[0]


def apply_original_pc_cell(model, project):
    """Crop Original tables and verify one whole Air circle in the PC layer."""
    device=project.get('device')
    cell,pc=_pc_selection(device)
    if cell is None:return False
    if len(model['patterns'])!=len(project.get('patterns',[])):
        raise ValueError('Remove blank optical pattern rows before PC simulation/search so original table indexes remain unambiguous.')
    apply_optical_unit_cell(model,cell,device)
    physical=next(row for row in device['layers'] if row['id']==pc['layer_id'])
    names={physical.get('name'),physical.get('optical_layer_name')}
    layers=[row['name'] for row in model['layers']
            if row.get('device_layer_id')==pc['layer_id'] or row['name'] in names]
    if len(layers)!=1:
        raise ValueError('Match the PC area to one Original optical table layer before running its one-hole cell.')
    air={row['name'] for row in model['materials']
         if row['model'] in ('constant_nk','constant_eps') and row['a']==1 and row['b']==0}
    holes=[row for row in model['patterns'] if row['layer']==layers[0] and row['material'] in air]
    if len(holes)!=1 or holes[0]['shape']!='circle' or holes[0].get('unit_cell_clipped'):
        raise ValueError('Original PC optics requires one whole circular Air hole in '+layers[0]+
            '. Review table radius, position and material; neighboring edited holes must not enter this pitch cell.')
    return True


def resolve_unit_cell(config=None, device=None, *, require_fit=True):
    """Use a PC-pitch default only when a saved selection is absent/empty."""
    if config is None or config=={}:
        config=pc_unit_cell(device) if device else None
        if config is None:
            config=dict(enabled=False,width_um=(device or {}).get('width_um',1.),
                        depth_um=(device or {}).get('depth_um',1.),cx_um=0.,cy_um=0.)
    return validate_unit_cell(config,device if require_fit else None)


def pc_unit_cell_issue(config, device):
    """Describe a multi-cell PC request in the single-hole native workflow.

    Custom periodic geometries without active PC metadata keep their existing
    domain choices. Explicit selections are reported, never overwritten.
    """
    arrays=_active_pc_arrays(device)
    if not arrays:return None
    cfg=resolve_unit_cell(config,device,require_fit=False)
    action='Enable the selected optical cell, then choose Use PC lattice size in Optical → Domain & solver.'
    if not cfg['enabled']:
        return 'PC-area optical runs require one selected PC-pitch cell with one air hole; the full finite device and PC array remain available for preview and electrical simulation. '+action
    x0,x1=cfg['cx_um']-cfg['width_um']/2,cfg['cx_um']+cfg['width_um']/2
    y0,y1=cfg['cy_um']-cfg['depth_um']/2,cfg['cy_um']+cfg['depth_um']/2
    for pc in arrays:
        if x1<=pc['cx_um']-pc['width_um']/2 or x0>=pc['cx_um']+pc['width_um']/2 or \
           y1<=pc['cy_um']-pc['depth_um']/2 or y0>=pc['cy_um']+pc['depth_um']/2:
            continue
        if cfg['width_um']>pc['cell_width_um']*(1+1e-9) or cfg['depth_um']>pc['cell_depth_um']*(1+1e-9):
            return (f"The selected optical domain spans multiple PC cells in {pc['name']}. "
                    f"Use its {pc['cell_width_um']:g} × {pc['cell_depth_um']:g} µm pitch cell with one air hole. "+action)
    return None


def validate_unit_cell(config=None, device=None):
    """Normalize a saved selection; optionally require it inside the device."""
    if config is None:
        config = {}
    if not isinstance(config, dict) or set(config)-{'enabled', 'width_um', 'depth_um', 'cx_um', 'cy_um'}:
        raise ValueError('Optical unit cell must contain enabled, width/depth and center coordinates only.')
    enabled = config.get('enabled', False)
    if not isinstance(enabled, bool):
        raise ValueError('Optical unit-cell selection must be true or false.')
    result = {'enabled': enabled}
    for key, default in (('width_um', (device or {}).get('width_um', 1.)),
                         ('depth_um', (device or {}).get('depth_um', 1.)),
                         ('cx_um', 0.), ('cy_um', 0.)):
        value = config.get(key, default)
        if isinstance(value, bool):
            raise ValueError('Optical unit-cell '+key+' must be a finite number.')
        try:
            value = float(value)
        except (ValueError, TypeError):
            value = float('nan')
        if not math.isfinite(value) or abs(value) > 1e6 or (key in ('width_um', 'depth_um') and value <= 0.):
            raise ValueError('Optical unit-cell dimensions must be positive and coordinates finite.')
        result[key] = value
    if enabled and device:
        for size, center, extent in (('width_um', 'cx_um', 'width_um'), ('depth_um', 'cy_um', 'depth_um')):
            if abs(result[center])+result[size]/2 > float(device[extent])/2+1e-10:
                raise ValueError('The selected optical unit cell must fit inside the finite device.')
    return result


def _vertices(pattern):
    if pattern['shape'] == 'polygon':
        return [list(pair) for pair in pattern['vertices']]
    angle = math.radians(pattern.get('angle', 0.))
    c, s = math.cos(angle), math.sin(angle)
    shape = pattern['shape']
    if shape in ('circle', 'ellipse'):
        a, b = pattern['sx'], pattern['sx'] if shape == 'circle' else pattern['sy']
        points = [(a*math.cos(2*math.pi*i/CURVE_SEGMENTS), b*math.sin(2*math.pi*i/CURVE_SEGMENTS))
                  for i in range(CURVE_SEGMENTS)]
    else:
        a, b = pattern['sx']/2, pattern['sy']/2
        points = [(-a, -b), (a, -b), (a, b), (-a, b)]
    return [[pattern['cx']+c*x-s*y, pattern['cy']+s*x+c*y] for x, y in points]


def _bounds(pattern):
    """Analytic curved bounds ensure tangent intersections are not missed."""
    if pattern['shape'] in ('circle', 'ellipse'):
        a, b = pattern['sx'], pattern['sx'] if pattern['shape'] == 'circle' else pattern['sy']
        angle = math.radians(pattern.get('angle', 0.))
        dx = math.hypot(a*math.cos(angle), b*math.sin(angle))
        dy = math.hypot(a*math.sin(angle), b*math.cos(angle))
        return pattern['cx']-dx, pattern['cy']-dy, pattern['cx']+dx, pattern['cy']+dy
    points = _vertices(pattern)
    return min(x for x, y in points), min(y for x, y in points), max(x for x, y in points), max(y for x, y in points)


def apply_optical_unit_cell(model, config=None, device=None):
    """Crop the prepared model in place and record its actual S4 periodic domain."""
    cfg = resolve_unit_cell(config, device)
    message=pc_unit_cell_issue(cfg,device)
    if message:raise ValueError(message)
    original = dict(width_um=float(model['ax']), depth_um=float(model['ay']))
    full_width = float(device['width_um']) if device else original['width_um']
    full_depth = float(device['depth_um']) if device else original['depth_um']
    metadata = dict(selection=copy.deepcopy(cfg), enabled=cfg['enabled'],
                    domain='selected periodic unit cell' if cfg['enabled'] else 'device-footprint periodic supercell',
                    finite_optical_device=False, source_width_um=full_width, source_depth_um=full_depth,
                    source_model_ax_um=original['width_um'], source_model_ay_um=original['depth_um'],
                    width_um=cfg['width_um'] if cfg['enabled'] else full_width,
                    depth_um=cfg['depth_um'] if cfg['enabled'] else full_depth,
                    cx_um=cfg['cx_um'] if cfg['enabled'] else 0., cy_um=cfg['cy_um'] if cfg['enabled'] else 0.,
                    original_patterns=len(model['patterns']), retained_patterns=len(model['patterns']),
                    outside_patterns=0, clipped_patterns=0, curve_segments=CURVE_SEGMENTS,
                    approximation_notes=[])
    if not cfg['enabled']:
        model['ax'], model['ay'] = full_width, full_depth
        model['optical_unit_cell'] = metadata
        model.setdefault('warnings', []).append(
            'S4 repeats the full device footprint as a periodic supercell; isolated finite-device optical diffraction is not computed.')
        return model
    cx, cy, width, depth = cfg['cx_um'], cfg['cy_um'], cfg['width_um'], cfg['depth_um']
    x0, x1, y0, y1 = cx-width/2, cx+width/2, cy-depth/2, cy+depth/2
    retained, clipped, outside, source_indices = [], 0, 0, []
    polygon_type = orient = window = None
    for source_index,pattern in enumerate(model['patterns'],1):
        xmin, ymin, xmax, ymax = _bounds(pattern)
        if xmax <= x0 or xmin >= x1 or ymax <= y0 or ymin >= y1:
            outside += 1
            continue
        row = copy.deepcopy(pattern)
        if xmin >= x0 and xmax <= x1 and ymin >= y0 and ymax <= y1:
            if row['shape'] == 'polygon':
                row['vertices'] = [[x-cx, y-cy] for x, y in row['vertices']]
                row['cx'] = row['cy'] = row['angle'] = 0.
            else:
                row['cx'] -= cx
                row['cy'] -= cy
            retained.append(row)
            source_indices.append(source_index)
            continue
        if polygon_type is None:
            from circle_geometry import geometry_tools
            _, polygon_type, _, _, orient = geometry_tools()
            window = polygon_type([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        physical = polygon_type(_vertices(pattern))
        if not physical.is_valid:
            raise ValueError('Cannot select a cell through an invalid optical polygon.')
        intersection = physical.intersection(window)
        pieces = [intersection] if intersection.geom_type == 'Polygon' else list(getattr(intersection, 'geoms', []))
        emitted = 0
        for piece in pieces:
            if piece.geom_type != 'Polygon' or piece.area <= width*depth*1e-14:
                continue
            if piece.interiors:
                raise ValueError('Cell clipping produced a polygon with an interior ring; split that optical shape first.')
            vertices = [[float(x-cx), float(y-cy)] for x, y in list(orient(piece, sign=1.).exterior.coords)[:-1]]
            retained.append(dict(row, shape='polygon', vertices=vertices, cx=0., cy=0., angle=0.,
                                 sx=width, sy=depth, unit_cell_clipped=True))
            source_indices.append(source_index)
            emitted += 1
        if emitted:
            clipped += 1
            if pattern['shape'] in ('circle', 'ellipse'):
                metadata['approximation_notes'].append(
                    f"Boundary-crossing {pattern['shape']} in {pattern['layer']} uses {CURVE_SEGMENTS} chords; "
                    'contained curves keep native analytic geometry.')
        else:
            outside += 1
    # A ring outside the selected center cell contributes no pad. Remove its
    # empty air layer so its arbitrary thickness cannot shift field coordinates.
    used_layers = {row['layer'] for row in retained}
    model['layers'] = [row for row in model['layers']
                       if not row.get('contact_optical_surface') or row['name'] in used_layers]
    model['patterns'], model['ax'], model['ay'] = retained, width, depth
    metadata.update(retained_patterns=len(retained), outside_patterns=outside, clipped_patterns=clipped,
                    pattern_source_indices=source_indices)
    model['optical_unit_cell'] = metadata
    model.setdefault('warnings', []).append(
        'S4 repeats the selected optical unit cell. The finite electrical device and terminal I–V/C–V retain their full footprint.')
    model['warnings'].extend(metadata['approximation_notes'])
    return model


def remap_cell_search_options(model, options):
    """Map full-table search targets to cropped patterns without guessing."""
    cell=model.get('optical_unit_cell',{})
    sources=cell.get('pattern_source_indices')
    if not cell.get('enabled') or sources is None:return copy.deepcopy(options)
    mapping={}
    for cropped,source in enumerate(sources,1):mapping.setdefault(source,[]).append(cropped)
    available=', '.join('#'+str(index) for index in sorted(mapping)) or 'none'
    def target(value):
        from model import integer
        original=integer(value,'Pattern target (1-based)',1)
        selected=mapping.get(original,[])
        if len(selected)!=1:
            reason='is outside the optical PC cell' if not selected else 'was split by cell clipping'
            raise ValueError(f'Original table pattern #{original} {reason}. Choose a retained whole-cell pattern: {available}.')
        return selected[0]
    result=copy.deepcopy(options)
    fields={'radius','r_over_a','size_x','size_y','center_x','center_y','rotation','pattern_material'}
    for row in result.get('bounds',[]):
        parameter=str(row.get('Parameter') or '').strip()
        if parameter not in fields:continue
        row['Parameter']=parameter
        row['Target']=str(target(row.get('Target')))
        if row.get('linked_targets'):row['linked_targets']=[target(value) for value in row['linked_targets']]
        if parameter in ('center_x','center_y'):
            offset=cell['cx_um' if parameter=='center_x' else 'cy_um']
            for key in ('Min','Max'):row[key]=float(row[key])-offset
    shared=result.get('shared_hole')
    if shared and shared.get('enabled'):shared['targets']=[target(value) for value in shared.get('targets',[])]
    return result


def _axis_faces(centers, lower, upper):
    centers = np.asarray(centers, float)
    if centers.ndim != 1 or not len(centers) or not np.isfinite(centers).all() or np.any(np.diff(centers) <= 0):
        raise ValueError('Selected-cell averaging requires finite ordered electrical mesh axes.')
    faces = np.r_[lower, (centers[:-1]+centers[1:])/2, upper]
    if np.any(np.diff(faces) <= 0):
        raise ValueError('Electrical mesh axes do not fit the saved finite device.')
    return faces


def selected_cell_profile(volume_path, device, config, material_library):
    """Return solid-only depth profiles using conservative fractional cell area.

    Electrical values are piecewise constant on the actual solved FV cells.
    Partial selected-cell intersections therefore receive their exact overlap
    area, rather than selecting by a cell-center test or resampling values.
    """
    cfg = validate_unit_cell(config, device)
    if not cfg['enabled']:
        raise ValueError('Selected-cell profile requires an enabled optical unit-cell selection.')
    from device_model import layer_bounds
    bounds = layer_bounds(device)
    with np.load(volume_path, allow_pickle=False) as saved:
        keys = ('x', 'y', 'z', 'electrons_cm3', 'holes_cm3', 'field_V_m', 'solid',
                'material_index', 'layer_index', 'material_ids', 'layer_ids')
        if any(key not in saved.files for key in keys):
            raise ValueError('Selected-cell coupling requires the actual electrical volume, materials and layer identities.')
        data = {key: np.array(saved[key], copy=True) for key in keys}
        bias = float(saved['bias_V']) if 'bias_V' in saved.files else 0.
    xfaces = _axis_faces(data['x'], -device['width_um']*.5e-6, device['width_um']*.5e-6)
    yfaces = _axis_faces(data['y'], -device['depth_um']*.5e-6, device['depth_um']*.5e-6)
    x0, x1 = (cfg['cx_um']-cfg['width_um']/2)*1e-6, (cfg['cx_um']+cfg['width_um']/2)*1e-6
    y0, y1 = (cfg['cy_um']-cfg['depth_um']/2)*1e-6, (cfg['cy_um']+cfg['depth_um']/2)*1e-6
    wx = np.maximum(0., np.minimum(xfaces[1:], x1)-np.maximum(xfaces[:-1], x0))
    wy = np.maximum(0., np.minimum(yfaces[1:], y1)-np.maximum(yfaces[:-1], y0))
    area = wx[:, None]*wy[None, :]
    shape = tuple(len(data[key]) for key in ('x', 'y', 'z'))
    for key in ('electrons_cm3', 'holes_cm3', 'solid', 'material_index', 'layer_index'):
        if data[key].shape != shape:
            raise ValueError('Electrical volume '+key+' dimensions do not match its axes.')
    if data['field_V_m'].shape != shape+(3,):
        raise ValueError('Electrical volume field dimensions do not match its axes.')
    if not math.isclose(float(area.sum()), cfg['width_um']*cfg['depth_um']*1e-12, rel_tol=1e-10, abs_tol=1e-30):
        raise ValueError('Electrical mesh does not cover the selected optical cell.')
    solid_weights = area[:, :, None]*data['solid']
    denominator = solid_weights.sum(axis=(0, 1))
    if np.any(denominator <= 0):
        raise ValueError('The selected cell has no solid electrical mesh cells at one or more depths; refine the mesh or move the cell.')
    def average(values):
        if not np.isfinite(values).all():
            raise ValueError('Selected-cell electrical values must be finite.')
        return (solid_weights*values).sum(axis=(0, 1))/denominator
    ids = data['layer_ids']
    material_ids = data['material_ids']
    if (np.any(data['layer_index'] < 0) or np.any(data['layer_index'] >= len(ids))
            or np.any(data['material_index'] < 0) or np.any(data['material_index'] >= len(material_ids))):
        raise ValueError('Electrical volume has invalid layer or material identities.')
    layer_ids, layer_names, materials = [], [], []
    by_id = {row['id']: row for row in bounds}
    for zi in range(shape[2]):
        mask = solid_weights[:, :, zi] > 0
        actual_layers = np.unique(ids[data['layer_index'][:, :, zi][mask]])
        if len(actual_layers) != 1 or actual_layers[0] not in by_id:
            raise ValueError('Selected-cell depth slab must retain one mapped electrical layer identity.')
        layer = by_id[str(actual_layers[0])]
        actual_materials = np.unique(material_ids[data['material_index'][:, :, zi][mask]])
        if len(actual_materials) != 1 or actual_materials[0] != layer['material_id']:
            raise ValueError(layer['name']+': selected-cell coupling needs one mapped solid material per layer.')
        layer_ids.append(layer['id']); layer_names.append(layer['name']); materials.append(layer['material_id'])
    ito_ids = {row['id'] for row in material_library if row['id'] == 'ito' or str(row.get('name', '')).casefold() == 'ito'}
    ito = np.isin(material_ids[data['material_index']], list(ito_ids))
    ez = data['field_V_m'][..., 2]
    profile = dict(z_nm=data['z']*1e9, electrons_cm3=average(data['electrons_cm3']*~ito),
                   holes_cm3=average(data['holes_cm3']*~ito), ito_electrons_cm3=average(data['electrons_cm3']*ito),
                   Ez_V_m=average(ez), Ez_squared_V2_m2=average(ez**2),
                   layer_id=np.asarray(layer_ids), layer_name=np.asarray(layer_names), material=np.asarray(materials),
                   bias_V=bias, temperature_K=float(device['temperature_K']),
                   solid_area_m2=denominator, optical_unit_cell_json=np.asarray(json.dumps(cfg, sort_keys=True)))
    audit = dict(selection=cfg, source_volume_npz=str(Path(volume_path)), bias_V=bias,
                 temperature_K=float(device['temperature_K']), selected_area_um2=float(area.sum()*1e12),
                 overlapping_xy_cells=int(np.count_nonzero(area)),
                 partially_overlapping_xy_cells=int(np.count_nonzero((area > 0)&(area < np.diff(xfaces)[:, None]*np.diff(yfaces)[None, :]*(1-1e-12)))),
                 solid_area_um2_by_depth=(denominator*1e12).tolist(),
                 averaging='Exact XY overlap area of solved finite-volume cells, solid-only; piecewise-constant cell values; no field resampling.',
                 electrical_device_width_um=device['width_um'], electrical_device_depth_um=device['depth_um'])
    return profile, audit
