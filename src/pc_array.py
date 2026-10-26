"""Independent finite PC areas, complete-cell hole placement and fast masks.

The document retains every generated hole as an editable canonical shape.
Regular consecutive runs are only an evaluation optimization; moved, resized,
disabled, removed or material-edited holes use their actual individual shapes.
"""
from __future__ import annotations

import copy
import math
import uuid

MAX_SHAPES = 100_000


def _finite(value, name, minimum=None):
    if isinstance(value, bool):
        raise ValueError(name + ' must be a finite number')
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(name + ' must be a finite number') from None
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(name + (' must be positive and finite' if minimum else ' must be finite'))
    return result


def _complete_cells(extent, pitch):
    ratio = extent / pitch
    return max(0, math.floor(ratio + 64 * math.ulp(max(1., ratio))))


def plan_pc_array(device, spec, *, allow_disabled_layer=False):
    """Return full uncapped counts, exact placement and visible capacity notes."""
    if not isinstance(spec, dict):
        raise ValueError('PC area settings must be a dictionary')
    for key in ('id', 'name', 'layer_id'):
        if key in spec and not isinstance(spec[key], str):
            raise ValueError('PC area ' + key + ' must be text')
    if 'id' in spec and not spec['id'].strip():
        raise ValueError('PC area id must be non-empty text')
    if not spec.get('layer_id', '').strip():
        raise ValueError('Choose a non-empty target layer ID for the PC area')
    if 'enabled' in spec and not isinstance(spec['enabled'], bool):
        raise ValueError('PC area enabled must be a boolean')
    result = dict(id=spec.get('id', 'pc_' + uuid.uuid4().hex[:12]),
                  name=spec.get('name', 'PC area').strip() or 'PC area',
                  layer_id=spec['layer_id'],
                  enabled=spec.get('enabled', True))
    layer = next((row for row in device.get('layers', []) if row['id'] == result['layer_id']), None)
    if layer is None or (not layer.get('enabled', True) and not allow_disabled_layer):
        raise ValueError('Choose an enabled target layer for the PC area')
    for key in ('cx_um', 'cy_um'):
        result[key] = _finite(spec.get(key, 0.), 'PC ' + key)
    for key in ('width_um', 'depth_um', 'cell_width_um', 'cell_depth_um'):
        result[key] = _finite(spec.get(key), 'PC ' + key, 1e-6)
    result['radius_um'] = _finite(spec.get('radius_um'), 'Hole radius', 5e-7)
    tolerance = 1e-12 * max(1., device['width_um'], device['depth_um'])
    if abs(result['cx_um']) + result['width_um']/2 > device['width_um']/2 + tolerance or \
       abs(result['cy_um']) + result['depth_um']/2 > device['depth_um']/2 + tolerance:
        raise ValueError('The PC area must fit entirely inside the finite device footprint')
    if result['radius_um'] > min(result['cell_width_um'], result['cell_depth_um'])/2 + 1e-12:
        raise ValueError('Hole radius must fit inside both unit-cell dimensions')
    nx = _complete_cells(result['width_um'], result['cell_width_um'])
    ny = _complete_cells(result['depth_um'], result['cell_depth_um'])
    result.update(nx=nx, ny=ny, hole_count=nx*ny,
                  unused_x_um=max(0., result['width_um']-nx*result['cell_width_um']),
                  unused_y_um=max(0., result['depth_um']-ny*result['cell_depth_um']))
    result['margin_x_um'] = result['unused_x_um']/2
    result['margin_y_um'] = result['unused_y_um']/2
    result['first_x_um'] = result['cx_um']-(nx-1)*result['cell_width_um']/2
    result['first_y_um'] = result['cy_um']-(ny-1)*result['cell_depth_um']/2
    others = sum(row.get('pc_array_id') != result['id'] for row in device.get('shapes', []))
    result['shape_budget_remaining'] = MAX_SHAPES-others
    result['can_apply'] = 0 < nx*ny <= result['shape_budget_remaining']
    notes = []
    if not nx or not ny:
        notes.append('No complete unit cells fit. Reduce the cell size or enlarge the PC area.')
    if nx*ny > result['shape_budget_remaining']:
        notes.append(f'{nx*ny:,} holes exceed the remaining {result["shape_budget_remaining"]:,}-shape document budget. No holes will be truncated.')
    mesh = device.get('mesh', {})
    dx = device['width_um']/max(1, mesh.get('nx', 16))
    dy = device['depth_um']/max(1, mesh.get('ny', 16))
    recommended_x = math.ceil(device['width_um']/(2*result['radius_um']/3))
    recommended_y = math.ceil(device['depth_um']/(2*result['radius_um']/3))
    result.update(mesh_dx_um=dx, mesh_dy_um=dy,
                  recommended_nx=recommended_x, recommended_ny=recommended_y)
    if min(2*result['radius_um']/dx, 2*result['radius_um']/dy) < 3:
        notes.append(f'Current electrical XY cells are {dx:g} × {dy:g} µm. About {recommended_x:,} × {recommended_y:,} cells give three cells across the hole diameter. Geometry can be saved; mesh validation may reject unresolved holes.')
    if recommended_x > 256 or recommended_y > 256:
        notes.append('That feature-resolution estimate exceeds the current electrical solver’s 256 cells per axis. Use a smaller electrical domain or a solver with a finer mesh; the full PC geometry is retained.')
    result['notes'] = notes
    return result


def apply_pc_array(device, spec, *, material_library=None):
    """Fill complete centered cells without clipping or silently capping count."""
    plan = plan_pc_array(device, spec)
    if not plan['can_apply']:
        raise ValueError(' '.join(plan['notes'][:1]) or 'No complete unit cells fit in this PC area')
    result = copy.deepcopy(device)
    result['shapes'] = [row for row in result.get('shapes', []) if row.get('pc_array_id') != plan['id']]
    shape_ids = []
    diameter = 2*plan['radius_um']
    for iy in range(plan['ny']):
        for ix in range(plan['nx']):
            object_id = f'{plan["id"]}_h_{ix}_{iy}'
            shape_ids.append(object_id)
            result['shapes'].append(dict(id=object_id, name=f'{plan["name"]} [{ix+1},{iy+1}]',
                layer_id=plan['layer_id'], shape='circle', material_id='air', operation='void',
                cx_um=plan['first_x_um']+ix*plan['cell_width_um'],
                cy_um=plan['first_y_um']+iy*plan['cell_depth_um'],
                size_x_um=diameter, size_y_um=diameter, angle_deg=0., vertices=[],
                enabled=plan['enabled'], pc_array_id=plan['id'], pc_cell=[ix,iy]))
    metadata = {key: plan[key] for key in ('id','name','layer_id','enabled','cx_um','cy_um','width_um','depth_um',
        'cell_width_um','cell_depth_um','radius_um','nx','ny','hole_count','unused_x_um','unused_y_um','margin_x_um','margin_y_um')}
    metadata['shape_ids'] = shape_ids
    result['pc_arrays'] = [row for row in result.get('pc_arrays', []) if row['id'] != plan['id']] + [metadata]
    from device_model import validate_device
    return validate_device(result, material_library)


def validate_pc_arrays(device):
    """Normalize saved design metadata without restoring edited/deleted holes."""
    arrays = device.get('pc_arrays', [])
    if not isinstance(arrays, list) or len(arrays) > 1000:
        raise ValueError('PC areas must be a list of at most 1000 regions')
    seen = {row['id'] for group in ('layers','shapes','contacts','doping_regions') for row in device.get(group, [])}
    # Saved metadata needs geometry validation, not an apply-capacity estimate.
    # Scan object IDs once above rather than scanning every hole for each area.
    metadata_device = dict(device, shapes=[])
    normalized = []
    for spec in arrays:
        plan = plan_pc_array(metadata_device, spec, allow_disabled_layer=True)
        if plan['id'] in seen:
            raise ValueError('Device object IDs must be unique: ' + plan['id'])
        seen.add(plan['id'])
        if not 0 < plan['hole_count'] <= MAX_SHAPES:
            raise ValueError('Saved PC area must contain 1 to 100,000 complete cells')
        shape_ids = spec.get('shape_ids', [])
        if not isinstance(shape_ids,list) or len(shape_ids)>MAX_SHAPES or not all(isinstance(value,str) for value in shape_ids):
            raise ValueError('PC area shape IDs must be a list of at most 100,000 text IDs')
        row = {key: plan[key] for key in ('id','name','layer_id','enabled','cx_um','cy_um','width_um','depth_um',
            'cell_width_um','cell_depth_um','radius_um','nx','ny','hole_count','unused_x_um','unused_y_um','margin_x_um','margin_y_um')}
        row['shape_ids'] = list(shape_ids)
        normalized.append(row)
    return normalized


def regular_member(obj, spec):
    """Return its original cell only when the current shape still matches it."""
    cell=obj.get('pc_cell')
    if obj.get('pc_array_id') != spec['id'] or obj.get('shape')!='circle' or obj.get('operation')!='void' or \
       obj.get('material_id')!='air' or obj.get('layer_id')!=spec['layer_id'] or not obj.get('enabled',True) or \
       not isinstance(cell,(list,tuple)) or len(cell)!=2:
        return None
    ix,iy=cell
    if isinstance(ix,bool) or isinstance(iy,bool) or not isinstance(ix,int) or not isinstance(iy,int) or not 0<=ix<spec['nx'] or not 0<=iy<spec['ny']:
        return None
    x=spec['cx_um']-(spec['nx']-1)*spec['cell_width_um']/2+ix*spec['cell_width_um']
    y=spec['cy_um']-(spec['ny']-1)*spec['cell_depth_um']/2+iy*spec['cell_depth_um']
    # Generated coordinates survive JSON serialization exactly. Approximate
    # equality can wrongly erase a real edit at a sampled hole boundary.
    if not all(obj.get(key)==value for key,value in
               [('cx_um',x),('cy_um',y),('size_x_um',2*spec['radius_um']),
                ('size_y_um',2*spec['radius_um']),('angle_deg',0.)]):
        return None
    return ix,iy


def regular_group_mask(spec, objects, x_um, y_um):
    """O(mesh points + holes) exact union and per-hole sample counts."""
    import numpy as np
    x,y=np.broadcast_arrays(np.asarray(x_um,float),np.asarray(y_um,float))
    nx,ny=spec['nx'],spec['ny']
    active=np.zeros(nx*ny,bool)
    cells=[]
    for obj in objects:
        cell=regular_member(obj,spec)
        if cell is None:raise ValueError('Grouped PC mask received an edited or disabled shape')
        flat=cell[1]*nx+cell[0];active[flat]=True;cells.append(flat)
    first_x=spec['cx_um']-(nx-1)*spec['cell_width_um']/2
    first_y=spec['cy_um']-(ny-1)*spec['cell_depth_um']/2
    ix0=np.floor((x-first_x)/spec['cell_width_um']).astype(np.int64)
    iy0=np.floor((y-first_y)/spec['cell_depth_um']).astype(np.int64)
    mask=np.zeros(x.shape,bool);counts=np.zeros(nx*ny,np.int64)
    for ox,oy in ((0,0),(1,0),(0,1),(1,1)):
        ix,iy=ix0+ox,iy0+oy
        valid=(ix>=0)&(ix<nx)&(iy>=0)&(iy<ny)
        flat=np.clip(iy*nx+ix,0,nx*ny-1)
        dx=x-(first_x+ix*spec['cell_width_um']);dy=y-(first_y+iy*spec['cell_depth_um'])
        hits=valid&active[flat]&((dx/spec['radius_um'])**2+(dy/spec['radius_um'])**2<=1.+1e-12)
        mask|=hits
        counts+=np.bincount(flat[hits].ravel(),minlength=nx*ny)
    return mask,{obj['id']:int(counts[cell]) for obj,cell in zip(objects,cells)}


def iter_shape_masks(device,x_um,y_um):
    """Preserve override order while batching only consecutive regular holes."""
    from device_model import shape_mask
    specs={row['id']:row for row in device.get('pc_arrays',[])}
    active_layers = ({row['id'] for row in device['layers'] if row.get('enabled', True)}
                     if 'layers' in device else None)
    pending=[];pending_spec=None
    def grouped():
        mask,counts=regular_group_mask(pending_spec,pending,x_um,y_um)
        return pending[0],mask,counts
    for obj in device.get('shapes',[]):
        if not obj.get('enabled',True) or (active_layers is not None and obj.get('layer_id') not in active_layers):continue
        spec=specs.get(obj.get('pc_array_id'))
        regular=spec is not None and regular_member(obj,spec) is not None
        if pending and (not regular or spec['id']!=pending_spec['id']):
            yield grouped();pending=[];pending_spec=None
        if regular:
            pending.append(obj);pending_spec=spec
        else:
            mask=shape_mask(obj,x_um,y_um)
            yield obj,mask,{obj['id']:int(mask.sum())}
    if pending:yield grouped()
