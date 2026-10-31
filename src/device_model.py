"""Portable finite-device geometry shared by the editor, previews and solver.

Lengths are micrometres. Layers are ordered from top to bottom and z is depth
from the top surface. Patterns and doping regions are extruded through one
layer; subsequent patterns override earlier patterns where they overlap.
"""
from __future__ import annotations

import copy
import json
import math
import uuid

from electrical_mesh import MESH_AXIS_MAX

SCHEMA_VERSION = 1
OBJECT_GROUPS = ('layers', 'shapes', 'contacts', 'doping_regions')
SHAPE_TYPES = ('rectangle', 'circle', 'ellipse', 'polygon', 'square_ring')
SURFACES = ('top', 'bottom', 'side_x_min', 'side_x_max', 'side_y_min', 'side_y_max')
MAX_SHAPES = 100_000


def new_id(prefix='object'):
    return prefix + '_' + uuid.uuid4().hex[:12]


def _number(value, name, low=0., high=1e12):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be a finite number')
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a finite number') from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f'{name} must be between {low:g} and {high:g}')
    return result


def default_device(material_library=None):
    """Editable, finite six-layer reference, independent of the legacy preset."""
    layers = []
    specifications = [('p+ GaAs', 'gaas', .05, 0., 1e20),
                      ('p GaAs', 'gaas', .15, 0., 3e19),
                      ('AlGaAs barrier', 'algaas', .02, 0., 0.),
                      ('n GaAs', 'gaas', .15, 8e18, 0.),
                      ('n+ GaAs', 'gaas', .05, 1e19, 0.),
                      ('ITO', 'ito', .04, 0., 0.)]
    for index, (name, material, thickness, donor, acceptor) in enumerate(specifications):
        layers.append(dict(id=f'layer_{index + 1}', name=name, material_id=material,
                           thickness_um=thickness, donor_cm3=donor,
                           acceptor_cm3=acceptor, enabled=True))
    def terminal(name, layer, surface, scale):
        return dict(id='contact_' + name.lower(), name=name, layer_id=layer,
                    surface=surface, boundary='ohmic', voltage_V=0., bias_scale=scale,
                    shape='rectangle', cx_um=0., cy_um=0., size_x_um=2.,
                    size_y_um=2., angle_deg=0., vertices=[], enabled=True)
    result = dict(schema_version=1, name='Editable GaAs / AlGaAs device',
                  width_um=2., depth_um=2., temperature_K=300.,
                  mesh=dict(nx=16, ny=16, nz_per_layer=8, max_nodes=0),
                  layers=layers, shapes=[], doping_regions=[],
                  contacts=[terminal('N', layers[-1]['id'], 'bottom', 0.),
                            terminal('P', layers[0]['id'], 'top', 1.)])
    return validate_device(result, material_library)


def validate_device(device, material_library=None, require_contacts=False):
    """Return a deep, JSON-safe canonical copy or a precise validation error."""
    if not isinstance(device, dict):
        raise ValueError('Device must be a dictionary')
    if device.get('schema_version', 1) != SCHEMA_VERSION:
        raise ValueError('Unsupported device schema version')
    result = copy.deepcopy(device)
    result['schema_version'] = SCHEMA_VERSION
    result['name'] = str(result.get('name', 'Custom device')).strip() or 'Custom device'
    for key in ('width_um', 'depth_um'):
        result[key] = _number(result.get(key, 2.), key, 1e-6, 1e6)
    result['temperature_K'] = _number(result.get('temperature_K', 300.), 'Temperature', 50., 1500.)
    mesh = result.setdefault('mesh', {})
    if not isinstance(mesh, dict):
        raise ValueError('Mesh settings must be a dictionary')
    for key, default, low, high in [('nx', 16, 2, MESH_AXIS_MAX), ('ny', 16, 2, MESH_AXIS_MAX),
                                   ('nz_per_layer', 8, 2, MESH_AXIS_MAX),
                                   ('max_nodes', 0, 0, MESH_AXIS_MAX)]:
        value = mesh.get(key, default)
        number = _number(value, 'Mesh ' + key, low, high)
        if number != int(number):
            raise ValueError('Mesh ' + key + ' must be an integer')
        mesh[key] = int(number)
    materials = None
    if material_library is not None:
        from electrical_material_library import validate_materials
        materials = {row['id'] for row in validate_materials(material_library)}
    seen = set()
    for group in OBJECT_GROUPS:
        objects = result.setdefault(group, [])
        if not isinstance(objects, list):
            raise ValueError(group + ' must be a list')
        limit=MAX_SHAPES if group=='shapes' else 1000
        if len(objects) > limit:
            raise ValueError(f'{group} may contain at most {limit:,} objects')
        parent_layers={layer['id']:layer['enabled'] for layer in result.get('layers',[])} if group!='layers' else {}
        for index, obj in enumerate(objects):
            if not isinstance(obj, dict):
                raise ValueError(group + ' objects must be dictionaries')
            obj['id'] = str(obj.get('id') or new_id(group[:-1]))
            if obj['id'] in seen:
                raise ValueError('Device object IDs must be unique: ' + obj['id'])
            seen.add(obj['id'])
            obj['name'] = str(obj.get('name') or f'{group[:-1]} {index + 1}')
            obj['enabled'] = bool(obj.get('enabled', True))
            if group == 'layers':
                obj['thickness_um'] = _number(obj.get('thickness_um', .1), obj['name'] + ' thickness', 1e-6, 1e6)
            else:
                _validate_geometry(obj)
            if group in ('layers', 'doping_regions'):
                for key in ('donor_cm3', 'acceptor_cm3'):
                    obj[key] = _number(obj.get(key, 0.), obj['name'] + ' ' + key, 0., 1e22)
            if group in ('layers', 'shapes'):
                obj['material_id'] = str(obj.get('material_id', 'gaas'))
                if group == 'shapes':
                    obj['operation'] = str(obj.get('operation', 'material'))
                    if obj['operation'] not in ('material', 'void'):
                        raise ValueError('Shape operation must be material or void')
                parent_enabled = group == 'layers' or parent_layers.get(obj.get('layer_id'),False)
                if obj['enabled'] and parent_enabled and materials is not None and obj['material_id'] not in materials and obj.get('operation') != 'void' and (obj['material_id'] or require_contacts):
                    raise ValueError(obj['name'] + ' references missing material ' + obj['material_id'])
            if group == 'contacts':
                obj['surface'] = str(obj.get('surface', 'top'))
                if obj['surface'] not in SURFACES:
                    raise ValueError('Unsupported contact surface: ' + obj['surface'])
                obj['boundary'] = str(obj.get('boundary', 'ohmic'))
                if obj['boundary'] not in ('ohmic', 'potential'):
                    raise ValueError('Contact boundary must be ohmic or potential')
                obj['voltage_V'] = _number(obj.get('voltage_V', 0.), obj['name'] + ' voltage', -1e300, 1e300)
                obj['bias_scale'] = _number(obj.get('bias_scale', 0.), obj['name'] + ' bias scale', -1., 1.)
                optical_material = obj.get('optical_material_name', '')
                if optical_material is None:
                    optical_material = ''
                if not isinstance(optical_material, str):
                    raise ValueError(obj['name'] + ' optical material name must be text')
                obj['optical_material_name'] = optical_material.strip()
                obj['optical_thickness_um'] = _number(obj.get('optical_thickness_um', 0.), obj['name'] + ' optical contact thickness', 0., 1e6)
    layer_ids = {obj['id'] for obj in result['layers']}
    active_ids = {obj['id'] for obj in result['layers'] if obj['enabled']}
    if not active_ids:
        raise ValueError('Device needs at least one enabled layer')
    for group in OBJECT_GROUPS[1:]:
        for obj in result[group]:
            obj['layer_id'] = str(obj.get('layer_id', ''))
            if obj['layer_id'] not in layer_ids:
                raise ValueError(obj['name'] + ' references a missing layer')
            # Disabled parent layers hide their objects in previews/solves while
            # retaining all editor settings so re-enabling is lossless.
    nodes = mesh['nx'] * mesh['ny'] * mesh['nz_per_layer'] * len(active_ids)
    if mesh['max_nodes'] and nodes > mesh['max_nodes']:
        raise ValueError(f'Mesh needs {nodes:,} cells; your cell budget is {mesh["max_nodes"]:,}. Raise the budget or set Maximum cells to 0 for automatic RAM checking. Resolution has not been reduced.')
    if require_contacts and not any(obj['enabled'] for obj in result['contacts']):
        raise ValueError('Add an enabled electrical contact before solving')
    if 'pc_arrays' in result:
        from pc_array import validate_pc_arrays
        result['pc_arrays']=validate_pc_arrays(result)
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Device must contain finite JSON-compatible values') from None
    return result


def _validate_geometry(obj):
    obj['shape'] = str(obj.get('shape', 'rectangle')).lower()
    if obj['shape'] not in SHAPE_TYPES:
        raise ValueError('Unsupported geometry shape: ' + obj['shape'])
    for key in ('cx_um', 'cy_um', 'angle_deg'):
        obj[key] = _number(obj.get(key, 0.), obj['name'] + ' ' + key, -1e6, 1e6)
    for key in ('size_x_um', 'size_y_um'):
        obj[key] = _number(obj.get(key, 1.), obj['name'] + ' ' + key, 1e-6, 1e6)
    if obj['shape'] == 'square_ring':
        for inner,outer in (('inner_size_x_um','size_x_um'),('inner_size_y_um','size_y_um')):
            obj[inner] = _number(obj.get(inner,obj[outer]/2),obj['name']+' '+inner,1e-6,1e6)
            if obj[inner] >= obj[outer]:
                raise ValueError('Ring inner dimensions must be smaller than its outer dimensions')
    vertices = obj.get('vertices', [])
    if not isinstance(vertices, (list, tuple)):
        raise ValueError('Polygon vertices must be a list of x/y pairs')
    obj['vertices'] = []
    for pair in vertices:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('Polygon vertices must be x/y pairs')
        obj['vertices'].append([_number(pair[0], 'Polygon x', -1e6, 1e6),
                                _number(pair[1], 'Polygon y', -1e6, 1e6)])
    if obj['shape'] == 'polygon':
        points = obj['vertices']
        if not 3 <= len(points) <= 512:
            raise ValueError('Polygon needs between three and 512 vertices')
        area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2
        if area < 1e-12:
            raise ValueError('Polygon must have nonzero area')
        # Intersections would make both the preview and electrical inside mask
        # ambiguous. Reject crossing edges instead of quietly changing geometry.
        def orient(a, b, c):
            return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        for i in range(len(points)):
            a, b = points[i], points[(i+1) % len(points)]
            for j in range(i+1, len(points)):
                if j == i+1 or (i == 0 and j == len(points)-1):
                    continue
                c, d = points[j], points[(j+1) % len(points)]
                if orient(a,b,c)*orient(a,b,d) < 0 and orient(c,d,a)*orient(c,d,b) < 0:
                    raise ValueError('Polygon edges may not cross')


def layer_bounds(device):
    depth = 0.
    result = []
    for layer in device.get('layers', []):
        if not layer.get('enabled', True):
            continue
        row = dict(layer, z_min_um=depth, z_max_um=depth + float(layer['thickness_um']))
        depth = row['z_max_um']
        result.append(row)
    return result


def geometry_vertices(obj, segments=48):
    """Actual vertices, including polygon centroid rotation and x/y offsets.

    Polygon vertex pairs start in device coordinates. ``cx_um``/``cy_um`` are
    translation offsets for polygons, while other shapes use their center.
    """
    shape = obj.get('shape', 'rectangle')
    if shape == 'polygon':
        points = obj.get('vertices', [])
        if not points:
            return []
        px = sum(pair[0] for pair in points)/len(points)
        py = sum(pair[1] for pair in points)/len(points)
        angle = math.radians(float(obj.get('angle_deg', 0.)))
        c, s = math.cos(angle), math.sin(angle)
        x, y = float(obj.get('cx_um', 0.)), float(obj.get('cy_um', 0.))
        return [[px+x+c*(a-px)-s*(b-py), py+y+s*(a-px)+c*(b-py)] for a,b in points]
    sx, sy = float(obj.get('size_x_um', 1.)), float(obj.get('size_y_um', 1.))
    if shape == 'circle':
        sy = sx
    if shape in ('circle', 'ellipse'):
        local = [(sx/2*math.cos(2*math.pi*i/segments), sy/2*math.sin(2*math.pi*i/segments)) for i in range(segments)]
    else:
        local = [(-sx/2,-sy/2), (sx/2,-sy/2), (sx/2,sy/2), (-sx/2,sy/2)]
    angle = math.radians(float(obj.get('angle_deg', 0.)))
    c, s = math.cos(angle), math.sin(angle)
    x, y = float(obj.get('cx_um', 0.)), float(obj.get('cy_um', 0.))
    return [[x+c*a-s*b, y+s*a+c*b] for a,b in local]


def shape_mask(obj, x_um, y_um):
    """Vectorized exact footprint mask, including rotated ellipses/rectangles."""
    import numpy as np
    x, y = np.broadcast_arrays(np.asarray(x_um, float), np.asarray(y_um, float))
    shape = obj.get('shape', 'rectangle')
    if shape == 'polygon':
        vertices = geometry_vertices(obj)
        inside = np.zeros(x.shape, dtype=bool)
        edge = np.zeros(x.shape, dtype=bool)
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            ax, ay = a; bx, by = b
            if ay != by:
                inside ^= ((ay > y) != (by > y)) & (x < (bx-ax)*(y-ay)/(by-ay)+ax)
            cross = (x-ax)*(by-ay)-(y-ay)*(bx-ax)
            edge |= (np.abs(cross) < 1e-12) & (x >= min(ax,bx)-1e-12) & (x <= max(ax,bx)+1e-12) & (y >= min(ay,by)-1e-12) & (y <= max(ay,by)+1e-12)
        return inside | edge
    angle = math.radians(float(obj.get('angle_deg', 0.)))
    dx, dy = x-float(obj.get('cx_um', 0.)), y-float(obj.get('cy_um', 0.))
    rx, ry = math.cos(angle)*dx+math.sin(angle)*dy, -math.sin(angle)*dx+math.cos(angle)*dy
    sx, sy = float(obj.get('size_x_um', 1.))/2, float(obj.get('size_y_um', 1.))/2
    if shape == 'circle':
        sy = sx
    if shape in ('circle', 'ellipse'):
        return (rx/sx)**2 + (ry/sy)**2 <= 1.+1e-12
    if shape == 'square_ring':
        outer = (np.abs(rx) <= sx+1e-12) & (np.abs(ry) <= sy+1e-12)
        inner = (np.abs(rx) < float(obj.get('inner_size_x_um',sx))/2-1e-12) & (np.abs(ry) < float(obj.get('inner_size_y_um',sy))/2-1e-12)
        return outer & ~inner
    return (np.abs(rx) <= sx+1e-12) & (np.abs(ry) <= sy+1e-12)


def geometry_inner_vertices(obj, segments=48):
    """Hole loop for a square ring, transformed exactly like the outer loop."""
    if obj.get('shape') != 'square_ring':
        return []
    inner=dict(obj,shape='rectangle',size_x_um=float(obj.get('inner_size_x_um',obj['size_x_um']/2)),
               size_y_um=float(obj.get('inner_size_y_um',obj['size_y_um']/2)))
    return geometry_vertices(inner,segments)


def find_object(device, object_id):
    return next((obj for group in (*OBJECT_GROUPS,'pc_arrays') for obj in device.get(group, []) if obj.get('id') == object_id), None)


def remove_object(device, object_id):
    """Remove an object and its layer's children, returning a separate document."""
    result = copy.deepcopy(device)
    for group in (*OBJECT_GROUPS,'pc_arrays'):
        if group in result:
            result[group] = [obj for obj in result.get(group, []) if obj.get('id') != object_id and obj.get('layer_id') != object_id and obj.get('pc_array_id')!=object_id]
    return result


def from_optical_project(project, material_library=None):
    """Convert finite optical layers/patterns without reversing depth order."""
    from electrical_material_library import builtin_materials
    library = material_library if material_library is not None else builtin_materials()
    names = {}
    for row in library:
        for name in [row['name'],row['id'],row.get('optical_material_name',''),*row.get('aliases',[])]:
            if name:
                names[str(name).strip().casefold()] = row['id']
    names.update({'si': 'silicon', 'algaas_50': 'algaas', 'al0.5ga0.5as': 'algaas'})
    settings = project.get('settings', {})
    result = dict(schema_version=1, name='Optical device',
                  width_um=max(1e-6, float(settings.get('ax_um', 2.))),
                  depth_um=max(1e-6, float(settings.get('ay_um', 2.))), temperature_K=300.,
                  mesh=dict(nx=16, ny=16, nz_per_layer=8, max_nodes=0),
                  layers=[], shapes=[], contacts=[], doping_regions=[])
    mapping = {}
    for layer in project.get('layers', []):
        thickness = float(layer.get('Thickness_um', 0.))
        if thickness < 0 or not math.isfinite(thickness):
            raise ValueError('Optical layer thickness must be finite and nonnegative')
        if thickness == 0:
            continue
        optical_material = str(layer.get('Material', ''))
        material_id = names.get(optical_material.casefold())
        row = dict(id=new_id('layer'), name=str(layer.get('Name', 'Layer')),
                   material_id=material_id or '', optical_material_name=optical_material, thickness_um=thickness,
                   donor_cm3=0., acceptor_cm3=0., enabled=True)
        result['layers'].append(row); mapping[row['name']] = row['id']
    for pattern in project.get('patterns', []):
        layer_id = mapping.get(str(pattern.get('Layer', '')))
        if layer_id is None:
            continue
        material = str(pattern.get('Material', ''))
        operation = 'void' if material.casefold() in ('air', 'vacuum') else 'material'
        material_id = names.get(material.casefold())
        shape = str(pattern.get('Shape', 'rectangle')).lower()
        if shape not in SHAPE_TYPES:
            raise ValueError('Optical pattern shape is unsupported: ' + shape)
        sx = float(pattern.get('SizeX_um', 1.)); sy = float(pattern.get('SizeY_um', sx))
        # Optical S4 circle/ellipse sizes are radii; editor sizes are diameters.
        if shape in ('circle', 'ellipse'):
            sx *= 2; sy = sx if shape == 'circle' else sy*2
        result['shapes'].append(dict(id=new_id('shape'), name=f'{shape.replace("_", " ").title()} {len(result["shapes"])+1}',
            layer_id=layer_id, material_id=material_id or '', optical_material_name=material, operation=operation,
            shape=shape, cx_um=float(pattern.get('CenterX_um', 0.)),
            cy_um=float(pattern.get('CenterY_um', 0.)), size_x_um=sx, size_y_um=max(sy,1e-6),
            angle_deg=float(pattern.get('Angle_deg', 0.)), vertices=pattern.get('Vertices', []), enabled=True))
    return validate_device(result, library)
