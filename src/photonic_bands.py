"""Editable periodic band structures through an explicitly configured MPB.

Geometry and real-space lattice vectors use Cartesian coordinates in units of
the reference length a. K points use fractional reciprocal-lattice coordinates.
Only positive real scalar permittivity and nondispersive lossless media are
supported. No paper geometry or workstation runtime is selected implicitly.
"""
from __future__ import annotations

import csv
import copy
import itertools
import json
import math
from pathlib import Path
import re
import sys
import time

import numpy as np

REFERENCE = 'https://mpb.readthedocs.io/en/stable/Scheme_User_Interface/'
CAPABILITIES = dict(engine='photonic_bands', studies=[dict(id='band_structure', label='Periodic bands and accuracy convergence')],
    dimensions=[2, 3], geometry=['circle (2D)', 'block (2D/3D)', 'sphere (3D)', 'cylinder (3D)'],
    solvers=dict(mpb=[2, 3], legume=[2]), outputs=['band frequencies', 'sampled-point gaps', 'accuracy-level comparisons', 'editable geometry/material parameter atlases'],
    limitations=['Lossless positive scalar permittivity', 'No complete-BZ convergence claim from finite samples',
                 'Legume primitives must not overlap, including their periodic images; touching boundaries are allowed'],
    optional_runtime='MPB executable or a Python interpreter with Legume; configured explicitly')
FIELD_SCHEMA = [
    dict(path='dimension', label='Periodic dimensions', type='integer', required=True, unit='', default=2, options=[2, 3], section='Crystal structure'),
    dict(path='lattice_vectors', label='Lattice vectors', type='matrix', required=True, unit='Cartesian a', section='Crystal structure'),
    dict(path='geometry', label='Editable periodic primitives', type='objects', required=False, unit='Cartesian a', default=[], section='Crystal structure'),
    dict(path='background_epsilon', label='Background permittivity', type='number', required=True, unit='relative epsilon', default=1., section='Materials'),
    dict(path='k_vertices', label='Reciprocal path vertices', type='matrix', required=False, unit='fractional reciprocal', section='k-space path'),
    dict(path='k_points', label='Explicit reciprocal points', type='matrix', required=False, unit='fractional reciprocal', section='k-space path'),
    dict(path='k_grid', label='Primitive reciprocal-cell grid', type='object', required=False, unit='counts and offset', section='k-space path'),
    dict(path='solver', label='Band engine', type='choice', required=True, options=['mpb', 'legume'], default='mpb', section='Solver & accuracy'),
    dict(path='num_bands', label='Number of bands', type='integer', required=True, default=8, unit='count', section='Solver & accuracy'),
    dict(path='resolution', label='MPB spatial resolution', type='integer', required=False, default=32, unit='grid', section='Solver & accuracy'),
    dict(path='gmax', label='Legume reciprocal cutoff', type='number', required=False, default=5., unit='reciprocal a', section='Solver & accuracy'),
    dict(path='resolution_levels', label='MPB convergence levels', type='numbers', required=False, unit='grid', section='Convergence'),
    dict(path='gmax_levels', label='Legume convergence levels', type='numbers', required=False, unit='reciprocal a', section='Convergence'),
    dict(path='frequency_tolerance', label='Last-pair frequency tolerance', type='number', required=False, unit='a/lambda', section='Convergence'),
    dict(path='parameter_sweep', label='Editable parameter atlas', type='object', required=False, section='Convergence'),
    dict(path='runtime', label='Optional engine runtime', type='object', required=False, section='Solver & accuracy'),
]
LIMITATIONS = [
    'Lossless nondispersive positive scalar permittivity; no absorption, gain, carrier transport or finite-device boundary conditions.',
    'Two-dimensional TE/TM calculations assume exact invariance along Cartesian z. Three-dimensional calculations solve full vector modes.',
    'Reported gaps are extrema on the supplied k-point path, not proof of a complete Brillouin-zone band gap.',
    'One supplied spatial resolution is executed without silent coarsening. Independent resolution and k-sampling convergence remain required.',
    'Geometry is supplied explicitly in study settings; it is not inferred from a finite optical stack or electrical contacts.',
    'Legume sums primitive dielectric contrasts and therefore requires disjoint periodic primitives; positive-area overlap is rejected. MPB retains its later-object precedence rule.',
]


def _number(value, label, *, positive=False):
    if isinstance(value, bool):
        raise ValueError(label+' must be finite')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(label+' must be finite') from None
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(label+(' must be positive and finite' if positive else ' must be finite'))
    return result


def _integer(value, label, minimum=1):
    result = _number(value, label)
    if result != int(result) or result < minimum:
        raise ValueError(label+' must be an integer of at least '+str(minimum))
    return int(result)


def _vector(value, dimension, label, *, positive=False):
    if not isinstance(value, (list, tuple)) or len(value) not in ({2, 3} if dimension == 2 else {3}):
        raise ValueError(label+' must have '+str(dimension)+' Cartesian components')
    vector = [_number(v, label, positive=positive) for v in value]
    if dimension == 2:
        if len(vector) == 3 and vector[2] != 0 and not positive:
            raise ValueError(label+' must lie in the Cartesian xy plane for dimension=2')
        vector = vector[:2]+[0. if not positive else 1.]
    return vector


def _validate_legume_disjoint(lattice_rows, primitives):
    """Reject positive-area overlaps in the periodic 2D ShapesLayer model.

    Legume adds each shape's dielectric contrast in Fourier space; it does not
    implement MPB's last-object-wins rule. Reciprocal-coordinate bounds enumerate
    every potentially intersecting lattice image, including skew cells. Exact
    convex geometry tests retain tangencies (within relative roundoff tolerance).
    """
    from input_diagnostics import InputValidationError, diagnostic
    lattice = np.asarray(lattice_rows, float)[:2, :2]
    inverse = np.linalg.inv(lattice)
    reciprocal_lengths = np.linalg.norm(inverse, axis=0)
    shapes = []
    for index, obj in enumerate(primitives):
        center = np.asarray(obj['center'][:2], float)
        # Equivalent cell-centered representatives improve distance arithmetic.
        fractional = center@inverse
        fractional -= np.floor(fractional+.5)
        center = fractional@lattice
        if obj['shape'] == 'circle':
            offsets, radius = None, obj['radius']
        else:
            axes = np.asarray(obj['axes'],float)[:2,:2]
            axes /= np.linalg.norm(axes,axis=1)[:,None]
            offsets = (np.asarray([[-1,-1],[1,-1],[1,1],[-1,1]])*np.asarray(obj['size'][:2])/2)@axes
            radius = float(np.max(np.linalg.norm(offsets,axis=1)))
        shapes.append(dict(index=index, object=obj, center=center, offsets=offsets, radius=radius))

    def circle_polygon(center, radius, vertices, tolerance):
        ends = np.roll(vertices,-1,axis=0)
        edges = ends-vertices
        relative = center-vertices
        cross = edges[:,0]*relative[:,1]-edges[:,1]*relative[:,0]
        if np.all(cross >= 0.) or np.all(cross <= 0.):
            return True
        fractions = np.clip(np.sum(relative*edges,axis=1)/np.sum(edges*edges,axis=1),0.,1.)
        nearest = vertices+fractions[:,None]*edges
        return float(np.min(np.linalg.norm(nearest-center,axis=1))) < radius-tolerance

    def intersect(first, second, delta):
        tolerance = 1e-11*max(first['radius']+second['radius'], float(np.linalg.norm(delta)), np.finfo(float).tiny)
        if first['offsets'] is None and second['offsets'] is None:
            return np.linalg.norm(delta) < first['radius']+second['radius']-tolerance
        if first['offsets'] is None:
            return circle_polygon(np.zeros(2),first['radius'],second['offsets']+delta,tolerance)
        if second['offsets'] is None:
            return circle_polygon(delta,second['radius'],first['offsets'],tolerance)
        a, b = first['offsets'], second['offsets']+delta
        for vertices in (a,b):
            edges = np.roll(vertices,-1,axis=0)-vertices
            normals = np.column_stack([-edges[:,1],edges[:,0]])
            normals /= np.linalg.norm(normals,axis=1)[:,None]
            for normal in normals:
                left, right = a@normal, b@normal
                if min(left.max(),right.max())-max(left.min(),right.min()) <= tolerance:
                    return False
        return True

    checked = 0
    for i, first in enumerate(shapes):
        for second in shapes[i:]:
            delta = second['center']-first['center']
            fractional = delta@inverse
            bound = (first['radius']+second['radius'])*reciprocal_lengths
            lower = np.ceil(-fractional-bound-1e-11).astype(float)
            upper = np.floor(-fractional+bound+1e-11).astype(float)
            counts = np.maximum(upper-lower+1,0)
            if not np.isfinite(counts).all() or np.prod(counts)>250000-checked:
                raise InputValidationError([diagnostic(
                    'This Legume geometry needs too many periodic overlap checks. Use MPB, reduce object sizes, or use a less skewed equivalent cell.',
                    code='periodic_geometry_check_limit',workspace='photonic_bands',section='Crystal structure',field='lattice_vectors',units='a')])
            for n1 in range(int(lower[0]),int(upper[0])+1):
                for n2 in range(int(lower[1]),int(upper[1])+1):
                    if first is second and n1 == n2 == 0:
                        continue
                    checked += 1
                    displacement = delta+np.asarray([n1,n2])@lattice
                    if not intersect(first,second,displacement):
                        continue
                    obj = second['object']
                    label = obj.get('name') or obj.get('id') or 'primitive '+str(second['index']+1)
                    other = 'its periodic copy' if first is second else (first['object'].get('name') or first['object'].get('id') or 'primitive '+str(first['index']+1))
                    field = 'radius' if first is second and obj['shape']=='circle' else ('size' if first is second else 'center')
                    raise InputValidationError([diagnostic(
                        'Legume cannot represent the overlap between '+label+' and '+other+'. Use MPB or separate the objects; touching boundaries are allowed.',
                        code='unsupported_periodic_overlap',workspace='photonic_bands',section='Crystal structure',
                        object_id=obj.get('id',''),field='geometry.'+str(second['index'])+'.'+field,units='a',
                        related_object_ids=[row['object'].get('id','') for row in (first,second)])])


def prepare(project, settings):
    """Validate portable physical inputs without launching an optional engine."""
    if not isinstance(project, dict) or not isinstance(settings, dict):
        raise ValueError('Band structure inputs and project must be objects')
    allowed = {'dimension', 'lattice_vectors', 'background_epsilon', 'geometry', 'k_vertices', 'k_points', 'k_grid',
               'points_per_segment', 'num_bands', 'resolution', 'polarizations', 'solver',
               'runtime', 'tolerance', 'mesh_size', 'reference_length_um', 'gmax',
               'resolution_levels', 'gmax_levels', 'frequency_tolerance', 'parameter_sweep'}
    if set(settings)-allowed:
        raise ValueError('Unsupported band structure settings: '+', '.join(sorted(set(settings)-allowed)))
    dimension = _integer(settings.get('dimension', 2), 'dimension', 2)
    if dimension not in (2, 3):
        raise ValueError('Band structures support dimension 2 or 3')
    solver = settings.get('solver', 'mpb')
    if solver not in ('mpb', 'legume'):
        raise ValueError('Band solver must be mpb or legume')
    if solver == 'legume' and dimension != 2:
        raise ValueError('Legume plane-wave bands require dimension=2; slab GME is a separate model')
    lattice = settings.get('lattice_vectors')
    if not isinstance(lattice, list) or len(lattice) != dimension:
        raise ValueError('Supply one lattice vector per periodic dimension')
    lattice = [_vector(row, dimension, 'lattice_vectors') for row in lattice]
    if dimension == 2:
        lattice.append([0., 0., 1.])
    lattice_array = np.asarray(lattice)
    lengths = np.linalg.norm(lattice_array, axis=1)
    if np.any(lengths <= 0) or abs(np.linalg.det(lattice_array/lengths[:, None])) < 1e-10:
        raise ValueError('Real-space lattice vectors must be nonzero and linearly independent')
    samplings = [key for key in ('k_vertices', 'k_points', 'k_grid') if key in settings]
    if len(samplings) != 1:
        raise ValueError('Supply exactly one of k_vertices, explicit k_points or a primitive reciprocal k_grid')
    sampling = samplings[0]
    vertices, explicit = [], []
    if sampling == 'k_vertices':
        vertices = settings['k_vertices']
        if not isinstance(vertices, list) or len(vertices) < 2:
            raise ValueError('Supply at least two fractional reciprocal k_vertices')
        vertices = [_vector(row, dimension, 'k_vertices') for row in vertices]
        if any(np.array_equal(a, b) for a, b in zip(vertices[:-1], vertices[1:])):
            raise ValueError('Adjacent k-path vertices must be distinct')
    elif sampling == 'k_points':
        points = settings['k_points']
        if not isinstance(points, list) or not points:
            raise ValueError('Explicit reciprocal k_points must be a nonempty list')
        explicit = [_vector(row, dimension, 'k_points') for row in points]
    else:
        grid = settings['k_grid']
        if not isinstance(grid, dict) or set(grid)-{'counts', 'offset'}:
            raise ValueError('k_grid supports counts and fractional offset')
        counts = grid.get('counts')
        if not isinstance(counts, list) or len(counts) != dimension:
            raise ValueError('k_grid needs one count per periodic dimension')
        counts = [_integer(count, 'reciprocal-grid count') for count in counts]
        if math.prod(counts) > 1000000:
            raise ValueError('Reciprocal grid exceeds one million points; adjust the explicit sampling before launch')
        offset = _vector(grid.get('offset', [0.]*dimension), dimension, 'k_grid offset')
        coordinates = np.meshgrid(*[np.arange(count)/count+offset[index] for index, count in enumerate(counts)], indexing='ij')
        explicit = np.stack([axis.ravel() for axis in coordinates], axis=1).tolist()
        if dimension == 2:
            explicit = [row+[0.] for row in explicit]
    polarizations = settings.get('polarizations', ['te', 'tm'] if dimension == 2 else ['vector'])
    choices = {'te', 'tm'} if dimension == 2 else {'vector'}
    if not isinstance(polarizations, list) or not polarizations or any(value not in choices for value in polarizations):
        raise ValueError('Use te/tm for 2D or vector for 3D band structures')
    if len(set(polarizations)) != len(polarizations):
        raise ValueError('Band polarizations must not repeat')
    geometry = settings.get('geometry', [])
    if not isinstance(geometry, list):
        raise ValueError('Band geometry must be a list of editable primitives')
    primitives = []
    primitive_ids = set()
    for item in geometry:
        if not isinstance(item, dict):
            raise ValueError('Each band primitive must be an object')
        shape = item.get('shape')
        fields = {'shape', 'center', 'epsilon', 'name', 'id'}
        fields |= {'circle': {'radius'}, 'sphere': {'radius'}, 'cylinder': {'radius', 'height', 'axis'},
                   'block': {'size', 'axes'}}.get(shape, set())
        if shape not in ('circle', 'sphere', 'cylinder', 'block') or set(item)-fields:
            raise ValueError('Unsupported primitive or primitive field')
        if (shape == 'circle' and dimension != 2) or (shape in ('sphere', 'cylinder') and dimension != 3):
            raise ValueError('Circle is a 2D primitive; sphere and finite cylinder require 3D')
        row = dict(shape=shape, center=_vector(item.get('center', [0.]*dimension), dimension, 'primitive center'),
                   epsilon=_number(item.get('epsilon'), 'primitive epsilon', positive=True))
        if 'name' in item:
            if not isinstance(item['name'], str):
                raise ValueError('Primitive name must be text')
            row['name'] = item['name']
        if 'id' in item:
            if not isinstance(item['id'], str) or not item['id'].strip() or item['id'] in primitive_ids:
                raise ValueError('Primitive id must be unique nonempty text')
            row['id'] = item['id']
            primitive_ids.add(item['id'])
        if shape in ('circle', 'sphere', 'cylinder'):
            row['radius'] = _number(item.get('radius'), 'primitive radius', positive=True)
        if shape == 'cylinder':
            row['height'] = _number(item.get('height'), 'cylinder height', positive=True)
            row['axis'] = _vector(item.get('axis', [0., 0., 1.]), 3, 'cylinder axis')
            if np.linalg.norm(row['axis']) == 0:
                raise ValueError('Cylinder axis must be nonzero')
        if shape == 'block':
            row['size'] = _vector(item.get('size'), dimension, 'block size', positive=True)
            axes = item.get('axes', np.eye(dimension).tolist())
            if not isinstance(axes, list) or len(axes) != dimension:
                raise ValueError('Block axes must contain one Cartesian direction per dimension')
            axes = [_vector(axis, dimension, 'block axis') for axis in axes]
            if dimension == 2:
                axes.append([0., 0., 1.])
            norms = np.linalg.norm(axes, axis=1)
            if np.any(norms == 0) or abs(np.linalg.det(np.asarray(axes)/norms[:, None])) < 1e-10:
                raise ValueError('Block axes must be nonzero and independent')
            row['axes'] = axes
        primitives.append(row)
    if solver == 'legume':
        _validate_legume_disjoint(lattice, primitives)
    runtime = settings.get('runtime', {})
    if solver == 'legume':
        from research_physics_runtime import validate_runtime
        runtime = validate_runtime(runtime)
    elif not isinstance(runtime, dict) or set(runtime)-{'mode', 'distro', 'executable', 'timeout_s'}:
        raise ValueError('Band runtime supports mode, distro, executable and timeout_s')
    if solver == 'mpb':
        runtime = dict(dict(mode='wsl' if sys.platform == 'win32' else 'local', distro='Ubuntu', executable='mpb', timeout_s=86400.), **runtime)
    if runtime['mode'] not in ('wsl', 'local'):
        raise ValueError('Band runtime mode must be wsl or local')
    if solver == 'mpb' and sys.platform == 'win32' and runtime['mode'] == 'local':
        raise ValueError('The MPB executable adapter on Windows requires WSL')
    for field in ('distro', 'executable'):
        if not isinstance(runtime[field], str) or not runtime[field].strip() or any(char in runtime[field] for char in '\r\n\0') or runtime[field].startswith('-'):
            raise ValueError('Invalid band runtime '+field)
        runtime[field] = runtime[field].strip()
    runtime['timeout_s'] = _number(runtime['timeout_s'], 'runtime timeout', positive=True)
    result = dict(schema_version=2, dimension=dimension, solver=solver, lattice_vectors=lattice,
        background_epsilon=_number(settings.get('background_epsilon', 1.), 'background epsilon', positive=True),
        geometry=primitives, k_vertices=vertices, sampling=sampling, k_points=explicit,
        points_per_segment=_integer(settings.get('points_per_segment', 10), 'points_per_segment'),
        num_bands=_integer(settings.get('num_bands', 8), 'num_bands'), resolution=_integer(settings.get('resolution', 32), 'resolution', 2),
        polarizations=list(polarizations), tolerance=_number(settings.get('tolerance', 1e-8), 'tolerance', positive=True),
        mesh_size=_integer(settings.get('mesh_size', 5), 'mesh_size'), runtime=runtime)
    if solver == 'legume':
        result['gmax'] = _number(settings.get('gmax', 5.), 'gmax', positive=True)
    for key, active_solver in (('resolution_levels', 'mpb'), ('gmax_levels', 'legume')):
        if key in settings:
            if solver != active_solver:
                raise ValueError(key+' is specific to '+active_solver)
            values = settings[key]
            if not isinstance(values, list) or len(values) < 2:
                raise ValueError(key+' needs at least two increasing accuracy levels')
            values = [_integer(value, key, 2) if solver == 'mpb' else _number(value, key, positive=True) for value in values]
            if any(b <= a for a, b in zip(values[:-1], values[1:])):
                raise ValueError(key+' must be strictly increasing')
            result[key] = values
    if 'frequency_tolerance' in settings:
        if not any(key in result for key in ('resolution_levels', 'gmax_levels')):
            raise ValueError('frequency_tolerance requires a convergence-level sweep')
        result['frequency_tolerance'] = _number(settings['frequency_tolerance'], 'frequency_tolerance', positive=True)
    if 'reference_length_um' in settings:
        result['reference_length_um'] = _number(settings['reference_length_um'], 'reference_length_um', positive=True)
    if 'parameter_sweep' in settings:
        result['parameter_sweep'] = _prepare_parameter_sweep(project, settings)
    return result


def _parameter_target(settings, target):
    """Resolve only supported physical scalar targets, never arbitrary JSON/code."""
    if not isinstance(target, dict) or set(target)-{'object_id', 'field'}:
        raise ValueError('Atlas parameter targets support object_id and field')
    field = target.get('field')
    if not isinstance(field, str):
        raise ValueError('Atlas target field must be explicit text')
    if 'object_id' in target:
        matches = [row for row in settings.get('geometry', []) if row.get('id') == target['object_id']]
        if len(matches) != 1:
            raise ValueError('Atlas target requires a unique existing primitive id: '+str(target['object_id']))
        owner = matches[0]
        if not re.fullmatch(r'(radius|height|epsilon|center\.[012]|size\.[012]|axis\.[012]|axes\.[012]\.[012])', field):
            raise ValueError('Unsupported primitive atlas field: '+field)
    else:
        owner = settings
        if not re.fullmatch(r'(background_epsilon|lattice_vectors\.[012]\.[012])', field):
            raise ValueError('Global atlas targets support background_epsilon or lattice_vectors.row.component')
    parts = field.split('.')
    for part in parts[:-1]:
        key = int(part) if isinstance(owner, list) and part.isdigit() else part
        try:
            owner = owner[key]
        except (KeyError, IndexError, TypeError):
            raise ValueError('Atlas target must already exist explicitly: '+field) from None
    key = int(parts[-1]) if isinstance(owner, list) and parts[-1].isdigit() else parts[-1]
    try:
        _number(owner[key], 'atlas target '+field)
    except (KeyError, IndexError, TypeError):
        raise ValueError('Atlas target must already exist explicitly: '+field) from None
    return owner, key


def _prepare_parameter_sweep(project, settings):
    sweep = settings['parameter_sweep']
    if not isinstance(sweep, dict) or set(sweep) != {'parameters'} or not isinstance(sweep['parameters'], list) or not sweep['parameters']:
        raise ValueError('parameter_sweep requires a nonempty parameters list')
    parameters, ids, used_targets = [], set(), set()
    for raw in sweep['parameters']:
        if not isinstance(raw, dict) or set(raw)-{'id', 'label', 'targets', 'values'}:
            raise ValueError('Each atlas parameter supports id, label, targets and values')
        identity = raw.get('id')
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError('Atlas parameters need unique nonempty ids')
        ids.add(identity)
        targets, values = raw.get('targets'), raw.get('values')
        if not isinstance(targets, list) or not targets or not isinstance(values, list) or not values:
            raise ValueError('Atlas parameters need nonempty target and numeric value lists')
        values = [_number(value, 'atlas '+identity) for value in values]
        for target in targets:
            _parameter_target(settings, target)
            key = (target.get('object_id'), target['field'])
            if key in used_targets:
                raise ValueError('An atlas target may be changed by only one parameter')
            used_targets.add(key)
        label = raw.get('label', identity)
        if not isinstance(label, str):
            raise ValueError('Atlas parameter label must be text')
        parameters.append(dict(id=identity, label=label, targets=copy.deepcopy(targets), values=values))
    if math.prod(len(row['values']) for row in parameters) > 1000:
        raise ValueError('Atlas exceeds 1000 explicit parameter combinations; split the study before launch')
    variants = []
    base = {key: copy.deepcopy(value) for key, value in settings.items() if key != 'parameter_sweep'}
    for values in itertools.product(*(row['values'] for row in parameters)):
        cfg = copy.deepcopy(base)
        for parameter, value in zip(parameters, values):
            for target in parameter['targets']:
                owner, key = _parameter_target(cfg, target)
                owner[key] = value
        variants.append(dict(values=dict(zip((row['id'] for row in parameters), values)), prepared=prepare(project, cfg)))
    return dict(parameters=parameters, variants=variants)


def k_path(prepared):
    """Use N intervals per segment, with each shared vertex included once."""
    if prepared.get('sampling', 'k_vertices') != 'k_vertices':
        fractions = np.asarray(prepared['k_points'])
    else:
        vertices = np.asarray(prepared['k_vertices'])
        count = prepared['points_per_segment']
        fractions = np.concatenate([a[None, :]+np.arange(count)[:, None]/count*(b-a)[None, :]
                                    for a, b in zip(vertices[:-1], vertices[1:])]+[vertices[-1:]])
    cartesian = fractions@np.linalg.inv(np.asarray(prepared['lattice_vectors'])).T
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(cartesian, axis=0), axis=1))]
    return fractions, distance


def control_file(prepared, output_prefix):
    """Generate Scheme from validated numbers; Cartesian shapes stay Cartesian."""
    def vector(values):
        return '(vector3 '+' '.join(format(float(value), '.17g') for value in values)+')'
    def cartesian(values):
        return '(cartesian->lattice '+vector(values)+')'
    lattice = np.asarray(prepared['lattice_vectors'])
    lines = ['; Generated by Optical Design Studio; geometry lengths are in units a.',
        '(set! geometry-lattice (make lattice (size 1 1 '+('no-size' if prepared['dimension'] == 2 else '1')+')',
        '  (basis-size '+ ' '.join(format(value, '.17g') for value in np.linalg.norm(lattice, axis=1))+')']
    lines.extend('  (basis'+str(index+1)+' '+vector(row)+')' for index, row in enumerate(lattice))
    lines[-1] += '))'
    lines.extend(['(set! default-material (make dielectric (epsilon '+format(prepared['background_epsilon'], '.17g')+')))',
                  '(set! geometry (list'])
    for obj in prepared['geometry']:
        shape = 'cylinder' if obj['shape'] == 'circle' else obj['shape']
        parts = ['(make '+shape, '(center '+cartesian(obj['center'])+')',
                 '(material (make dielectric (epsilon '+format(obj['epsilon'], '.17g')+')))']
        if 'radius' in obj:
            parts.append('(radius '+format(obj['radius'], '.17g')+')')
        if obj['shape'] == 'circle':
            parts.extend(['(height infinity)', '(axis '+cartesian([0, 0, 1])+')'])
        if obj['shape'] == 'cylinder':
            parts.extend(['(height '+format(obj['height'], '.17g')+')', '(axis '+cartesian(obj['axis'])+')'])
        if obj['shape'] == 'block':
            sizes = [format(value, '.17g') for value in obj['size']]
            if prepared['dimension'] == 2:
                sizes[-1] = 'infinity'
            parts.append('(size '+' '.join(sizes)+')')
            parts.extend('(e'+str(index+1)+' '+cartesian(axis)+')' for index, axis in enumerate(obj['axes']))
        lines.append('  '+' '.join(parts)+')')
    lines.extend(['))', '(set! resolution '+str(prepared['resolution'])+')',
        '(set! num-bands '+str(prepared['num_bands'])+')', '(set! mesh-size '+str(prepared['mesh_size'])+')',
        '(set! tolerance '+format(prepared['tolerance'], '.17g')+')',
        '(set! filename-prefix '+json.dumps(str(output_prefix), ensure_ascii=False)+')',
        '(set! k-points (list '+' '.join(vector(point) for point in k_path(prepared)[0])+'))'])
    lines.extend('(run'+('' if pol == 'vector' else '-'+pol)+')' for pol in prepared['polarizations'])
    return '\n'.join(lines)+'\n'


def parse_frequencies(lines, prepared):
    """Require every requested k point and every band from every polarization."""
    prefixes = {'tefreqs:': 'te', 'tmfreqs:': 'tm', 'freqs:': 'vector'}
    tables = {pol: [] for pol in prepared['polarizations']}
    for line in lines:
        fields = [item.strip() for item in line.split(',')]
        if not fields or fields[0] not in prefixes or len(fields) < 2 or not fields[1].isdigit():
            continue
        pol = prefixes[fields[0]]
        if pol not in tables:
            continue
        if len(fields) != prepared['num_bands']+6:
            raise RuntimeError('MPB emitted an incomplete band row')
        row = np.asarray([float(value) for value in fields[1:]])
        if not np.isfinite(row).all() or np.any(row[5:] < -1e-9):
            raise RuntimeError('MPB emitted a nonfinite or negative band frequency')
        tables[pol].append(row)
    points, _ = k_path(prepared)
    result = {}
    for pol, rows in tables.items():
        table = np.asarray(rows)
        if table.shape != (len(points), prepared['num_bands']+5):
            raise RuntimeError('MPB did not complete all requested '+pol+' band points')
        if not np.array_equal(table[:, 0], np.arange(1, len(points)+1)):
            raise RuntimeError('MPB k-point sequence is incomplete or repeated')
        if not np.allclose(table[:, 1:4], points, atol=6e-6, rtol=6e-6):
            raise RuntimeError('MPB output k points differ from the requested reciprocal path')
        result[pol] = table[:, 5:]
    return result


def execute(prepared, directory, emit=lambda event: None, cancelled=lambda: False):
    """Run MPB in a separate cancellable process and save portable band data."""
    from meep_runtime import ManagedProcess, linux_path
    if cancelled():
        raise InterruptedError('Band structure cancelled')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if 'parameter_sweep' in prepared:
        return _execute_parameter_sweep(prepared, directory, emit, cancelled)
    if 'resolution_levels' in prepared or 'gmax_levels' in prepared:
        return _execute_convergence(prepared, directory, emit, cancelled)
    if prepared['solver'] == 'legume':
        from research_physics_runtime import run_worker
        started = time.monotonic()
        worker_input = dict(prepared, worker_engine='legume_pwe', k_points=k_path(prepared)[0].tolist())
        engine = run_worker(worker_input, directory, emit, cancelled)
        with np.load(directory/engine['output_npz'], allow_pickle=False) as data:
            tables = {pol: data['frequencies_'+pol].copy() for pol in prepared['polarizations']}
        return _save_result(prepared, directory, tables, started, emit,
                            engine_metadata=engine, extra_files=['engine.log', 'engine_inputs.json', 'engine_result.json'])
    runtime = prepared['runtime']
    path = directory/'bands.ctl'
    runtime_directory = linux_path(directory, runtime)
    source = control_file(prepared, runtime_directory+'/mpb-')
    path.write_text(source, encoding='utf-8')
    (directory/'band_inputs.json').write_text(json.dumps(prepared, indent=2, allow_nan=False), encoding='utf-8')
    command = (['wsl.exe', '--distribution', runtime['distro'], '--exec'] if runtime['mode'] == 'wsl' else [])
    command += ['env', 'OMP_NUM_THREADS=1', 'OPENBLAS_NUM_THREADS=1', runtime['executable'], runtime_directory+'/bands.ctl']
    emit(dict(phase='photonic_bands', progress=0., message='Running editable '+str(prepared['dimension'])+'D MPB band structure'))
    class Cancellation:
        def is_set(self):
            return bool(cancelled())
    started = time.monotonic()
    lines = []
    try:
        process = ManagedProcess(runtime, command)
    except OSError as exc:
        raise RuntimeError('The selected MPB runtime is unavailable: '+str(exc)) from exc
    expected = len(k_path(prepared)[0])*len(prepared['polarizations'])
    completed = 0
    try:
        with (directory/'mpb.log').open('w', encoding='utf-8') as log:
            for line in process.stream(Cancellation(), timeout=runtime['timeout_s']):
                log.write(line)
                lines.append(line)
                if re.match(r'^(?:te|tm)?freqs:,\s*\d+,', line):
                    completed += 1
                    emit(dict(phase='photonic_bands', progress=min(.99, completed/max(1, expected)),
                              message=f'Computed {completed} of {expected} band samples'))
    finally:
        if process.process.poll() is None:
            process.terminate(force=True)
    if cancelled():
        raise InterruptedError('Band structure cancelled')
    if process.process.returncode:
        raise RuntimeError('MPB failed in the selected runtime; see mpb.log. '+''.join(lines[-8:]).strip())
    tables = parse_frequencies(lines, prepared)
    return _save_result(prepared, directory, tables, started, emit,
                        extra_files=['mpb.log', 'bands.ctl', 'band_inputs.json'])


def _save_result(prepared, directory, tables, started, emit, engine_metadata=None, extra_files=()):
    points, distances = k_path(prepared)
    gaps = {}
    files = []
    arrays = dict(k_fractional=points, k_distance_reciprocal_a=distances)
    for pol, frequencies in tables.items():
        filename = 'bands_'+pol+'.csv'
        with (directory/filename).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['k_index', 'k1', 'k2', 'k3', 'path_distance_reciprocal_a']+
                            ['band_'+str(index+1)+'_a_over_lambda' for index in range(prepared['num_bands'])])
            for index, row in enumerate(frequencies):
                writer.writerow([index+1, *points[index], distances[index], *row])
        files.append(filename)
        arrays['frequencies_'+pol] = frequencies
        gaps[pol] = []
        for index in range(prepared['num_bands']-1):
            low, high = float(frequencies[:, index].max()), float(frequencies[:, index+1].min())
            if high > low:
                gaps[pol].append(dict(after_band=index+1, lower_a_over_lambda=low, upper_a_over_lambda=high,
                    relative_percent=200*(high-low)/(high+low), scope='sampled_path_only' if prepared.get('sampling', 'k_vertices') == 'k_vertices' else 'sampled_points_only'))
    np.savez_compressed(directory/'bands.npz', **arrays)
    summary = dict(status='complete', engine=prepared['solver'], model_scope='periodic_lossless_band_structure',
        dimension=prepared['dimension'], polarizations=prepared['polarizations'], k_points=len(points),
        num_bands=prepared['num_bands'], resolution=prepared['resolution'], spatial_convergence_established=False,
        frequency_units='omega*a/(2*pi*c) = a/lambda', geometry_units='Cartesian units of reference length a',
        k_units='Fractional reciprocal-lattice coordinates; path distance omits 2*pi',
        sampled_path_gaps=gaps, k_sampling=prepared.get('sampling', 'k_vertices'),
        path_connectivity=prepared.get('sampling', 'k_vertices') == 'k_vertices',
        files=['bands.npz', *files, *extra_files],
        elapsed_s=time.monotonic()-started, limitations=LIMITATIONS, reference=REFERENCE,
        options=prepared)
    if prepared['solver'] == 'legume':
        summary['gmax'] = prepared['gmax']
    if engine_metadata:
        summary['engine_metadata'] = engine_metadata
    (directory/'band_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    emit(dict(phase='photonic_bands', progress=1., message='Band frequencies and sampled-path gaps saved'))
    return summary


def _execute_parameter_sweep(prepared, directory, emit, cancelled):
    sweep = prepared['parameter_sweep']
    results = []
    summary = dict(status='partial', engine=prepared['solver'], model_scope='editable_band_parameter_atlas',
        parameters=sweep['parameters'], results=results, requested_variants=len(sweep['variants']),
        spatial_convergence_established=False, limitations=LIMITATIONS+[
            'Each parameter combination uses the exact supplied primitive geometry and reciprocal samples; no crystal symmetry or complete gap is assumed.'])
    for index, variant in enumerate(sweep['variants']):
        if cancelled():
            raise InterruptedError('Band parameter atlas cancelled')
        folder = directory/f'variant_{index+1:04d}'
        def stage_event(event):
            emit(dict(event, progress=(index+float(event.get('progress', 0.)))/len(sweep['variants'])))
        result = execute(variant['prepared'], folder, stage_event, cancelled)
        results.append(dict(values=variant['values'], directory=folder.name, summary=result))
        (directory/'band_parameter_sweep.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    summary.update(status='complete', files=['band_parameter_sweep.json']+[row['directory']+'/band_summary.json' for row in results])
    (directory/'band_parameter_sweep.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    (directory/'band_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    return summary


def _execute_convergence(prepared, directory, emit, cancelled):
    key = 'resolution_levels' if prepared['solver'] == 'mpb' else 'gmax_levels'
    setting = 'resolution' if prepared['solver'] == 'mpb' else 'gmax'
    levels = prepared[key]
    results, comparisons = [], []
    previous = None
    for index, value in enumerate(levels):
        if cancelled():
            raise InterruptedError('Band convergence study cancelled')
        cfg = {k: v for k, v in prepared.items() if k not in (key, 'frequency_tolerance')}
        cfg[setting] = value
        folder = directory/f'level_{index+1}'
        def stage_event(event):
            emit(dict(event, progress=(index+float(event.get('progress', 0.)))/len(levels)))
        result = execute(cfg, folder, stage_event, cancelled)
        results.append(dict(level=value, directory=folder.name, summary=result))
        with np.load(folder/'bands.npz', allow_pickle=False) as data:
            current = {pol: data['frequencies_'+pol].copy() for pol in prepared['polarizations']}
        if previous is not None:
            comparisons.append(dict(previous_level=levels[index-1], level=value,
                max_sorted_frequency_change={pol: float(np.max(np.abs(current[pol]-previous[pol]))) for pol in current}))
        previous = current
    tolerance = prepared.get('frequency_tolerance')
    passed = tolerance is not None and max(comparisons[-1]['max_sorted_frequency_change'].values()) <= tolerance
    summary = dict(status='complete', engine=prepared['solver'], model_scope='band_accuracy_sweep',
        options=prepared, results=results, comparisons=comparisons,
        specified_frequency_tolerance=tolerance, last_pair_tolerance_passed=passed,
        spatial_convergence_established=False,
        limitations=LIMITATIONS+['The last two accuracy levels test only the supplied sorted eigenfrequencies and k samples; passing does not prove full Brillouin-zone or mode-character convergence.'],
        files=['band_convergence.json']+[row['directory']+'/band_summary.json' for row in results])
    (directory/'band_convergence.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    (directory/'band_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    return summary
