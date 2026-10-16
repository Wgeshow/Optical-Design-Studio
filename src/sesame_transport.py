"""Editable one/two-dimensional Sesame drift-diffusion studies.

The study has its own rectilinear semiconductor domain. No paper material,
geometry, defect energy, contact or illumination is selected implicitly.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np

from photonic_bands import _number, _integer
from research_physics_runtime import validate_runtime, run_worker
from input_diagnostics import diagnostic, InputValidationError

CAPABILITIES = dict(engine='sesame_transport', studies=[dict(id='drift_diffusion', label='Editable 1D/2D semiconductor transport')],
    dimensions=[1, 2], geometry=['rectilinear material regions', 'point defects in 1D', 'line defects in 2D'],
    outputs=['current versus bias', 'potential and carrier maps', 'quasi-Fermi levels', 'bulk recombination', 'section-current conservation'],
    limitations=['Nondegenerate Boltzmann carriers', 'Two contacts at x endpoints', 'Constant temperature; no tunnelling or self-heating'],
    optional_runtime='Explicit Python interpreter with Sesame, NumPy, SciPy and its dependencies')
FIELD_SCHEMA = [
    dict(path='dimension', label='Dimensions', type='integer', required=True, default=1, options=[1, 2], section='Device'),
    dict(path='x_nodes_um', label='Transport mesh nodes', type='numbers', required=True, unit='um', section='Device'),
    dict(path='y_nodes_um', label='Transverse mesh nodes', type='numbers', required=False, unit='um', section='Device'),
    dict(path='materials', label='Semiconductor properties', type='object', required=True, section='Materials'),
    dict(path='regions', label='Material, doping and generation regions', type='objects', required=True, section='Device'),
    dict(path='contacts', label='Left and right contacts', type='object', required=True, section='Contacts'),
    dict(path='defects', label='Point or line defect states', type='objects', required=False, default=[], section='Defects'),
    dict(path='voltages_V', label='Right-contact bias sequence', type='numbers', required=True, unit='V', section='Study'),
    dict(path='temperature_K', label='Fixed temperature', type='number', required=True, default=300., unit='K', section='Study'),
    dict(path='periodic_y', label='Periodic transverse boundary', type='boolean', required=False, default=False, section='Study'),
    dict(path='tolerance', label='Newton update tolerance', type='number', required=False, default=1e-9, section='Solver'),
    dict(path='max_iterations', label='Maximum Newton iterations', type='integer', required=False, default=300, section='Solver'),
    dict(path='runtime', label='Sesame Python runtime', type='object', required=False, section='Solver'),
]
LIMITATIONS = [
    'Sesame drift-diffusion uses Boltzmann carriers and fixed-temperature, scalar local material coefficients; high degeneracy is outside this model.',
    'Only a filled rectilinear one/two-dimensional semiconductor domain with contacts at both x ends is supported; no 3D contacts or conductor interiors.',
    'SRH lifetimes/trap level, radiative B, Auger Cn/Cp and defect capture parameters are user inputs, not inferred or calibrated from a paper.',
    'Defect energy is measured relative to the intrinsic level, not geometric band midgap. Defect lines are discretized on the supplied mesh.',
    'No avalanche, tunnelling, self-heating or optical feedback; convergence in mesh, bias step and material assumptions remains the user responsibility.',
    'Regions may share boundaries: the later region owns shared mesh nodes. Interior overlap and uncovered nodes are rejected.',
    'For periodic y, Sesame identifies the last row with the first across one additional interval equal to the first y spacing; the reported period includes that interval.',
]


def _invalid(message, field, section, object_id='', units=''):
    return InputValidationError([diagnostic(message, workspace='sesame_transport', section=section,
        field=field, object_id=object_id, units=units)])


def _nonnegative(value, label):
    value = _number(value, label)
    if value < 0:
        raise ValueError(label+' must be nonnegative')
    return value


def _nodes(value, label):
    if not isinstance(value, list) or len(value) < 3:
        raise _invalid(label+' needs at least three explicit nodes', label, 'Device', units='um')
    result = [_number(v, label) for v in value]
    if np.any(np.diff(result) <= 0):
        raise _invalid(label+' must be strictly increasing', label, 'Device', units='um')
    return result


def region_labels(cfg):
    """Assign node regions with documented interface ownership; used in preflight."""
    x = np.asarray(cfg['x_nodes_um'])
    y = np.asarray(cfg.get('y_nodes_um') or [0.])
    xx, yy = np.meshgrid(x, y)
    labels = np.full(xx.shape, -1, dtype=int)
    for index, region in enumerate(cfg['regions']):
        lo, hi = region['x_range_um']
        selected = (xx >= lo) & (xx <= hi)
        if cfg['dimension'] == 2:
            lo, hi = region['y_range_um']
            selected &= (yy >= lo) & (yy <= hi)
        labels[selected] = index
    return labels


def prepare(project, settings):
    if not isinstance(project, dict) or not isinstance(settings, dict):
        raise ValueError('Sesame project and settings must be objects')
    allowed = {'dimension', 'x_nodes_um', 'y_nodes_um', 'materials', 'regions', 'contacts', 'defects',
               'voltages_V', 'temperature_K', 'periodic_y', 'tolerance', 'max_iterations', 'runtime'}
    if set(settings)-allowed:
        raise ValueError('Unsupported Sesame settings: '+', '.join(sorted(set(settings)-allowed)))
    dimension = _integer(settings.get('dimension', 1), 'dimension')
    if dimension not in (1, 2):
        raise ValueError('Sesame supports dimension=1 or 2')
    cfg = dict(schema_version=1, worker_engine='sesame_transport', dimension=dimension,
        x_nodes_um=_nodes(settings.get('x_nodes_um'), 'x_nodes_um'),
        y_nodes_um=_nodes(settings.get('y_nodes_um'), 'y_nodes_um') if dimension == 2 else [],
        temperature_K=_number(settings.get('temperature_K', 300.), 'temperature_K', positive=True),
        tolerance=_number(settings.get('tolerance', 1e-9), 'tolerance', positive=True),
        max_iterations=_integer(settings.get('max_iterations', 300), 'max_iterations'),
        runtime=validate_runtime(settings.get('runtime')))
    if dimension == 1 and settings.get('y_nodes_um'):
        raise ValueError('One-dimensional Sesame does not accept y mesh nodes')
    periodic = settings.get('periodic_y', False)
    if not isinstance(periodic, bool) or (dimension == 1 and periodic):
        raise ValueError('periodic_y must be boolean and requires dimension=2 when enabled')
    cfg['periodic_y'] = periodic
    raw_materials = settings.get('materials')
    if not isinstance(raw_materials, dict) or not raw_materials:
        raise _invalid('Supply explicit semiconductor materials', 'materials', 'Materials')
    required = {'Nc', 'Nv', 'Eg', 'epsilon', 'mu_e', 'mu_h', 'tau_e', 'tau_h', 'affinity', 'Et'}
    extra = {'B', 'Cn', 'Cp', 'mass_e', 'mass_h'}
    cfg['materials'] = {}
    for key, raw in raw_materials.items():
        if not isinstance(key, str) or not key or not isinstance(raw, dict):
            raise ValueError('Materials need nonempty string IDs and property objects')
        if required-set(raw) or set(raw)-required-extra:
            missing = sorted(required-set(raw))
            field = 'materials.'+key+('.'+missing[0] if missing else '')
            raise _invalid('Material '+key+' requires '+', '.join(sorted(required))+'; optional B, Cn, Cp, mass_e, mass_h', field, 'Materials', key)
        mat = {field: _number(raw[field], 'materials.'+key+'.'+field, positive=field not in {'affinity', 'Et'}) for field in required}
        for field in extra:
            default = 1. if field in {'mass_e', 'mass_h'} else 0.
            mat[field] = _number(raw.get(field, default), 'materials.'+key+'.'+field, positive=field.startswith('mass'))
            if mat[field] < 0:
                raise ValueError('Recombination coefficients cannot be negative')
        cfg['materials'][key] = mat
    regions = settings.get('regions')
    if not isinstance(regions, list) or not regions:
        raise _invalid('Supply material regions covering the full mesh', 'regions', 'Device')
    cfg['regions'] = []
    ids = set()
    for raw in regions:
        if not isinstance(raw, dict) or set(raw)-{'id', 'material', 'x_range_um', 'y_range_um', 'donors_cm3', 'acceptors_cm3', 'generation_cm3_s'}:
            raise ValueError('Invalid material region fields')
        identity = raw.get('id')
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError('Each material region needs a unique nonempty id')
        ids.add(identity)
        material = raw.get('material')
        if material not in cfg['materials']:
            raise _invalid('Region '+identity+' references an unknown material', 'regions.'+identity+'.material', 'Device', identity)
        region = dict(id=identity, material=material)
        for axis in ('x', 'y')[:dimension]:
            key = axis+'_range_um'
            bounds = raw.get(key)
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError('Region '+identity+' needs '+key+'=[minimum,maximum]')
            bounds = [_number(v, key) for v in bounds]
            nodes = cfg[axis+'_nodes_um']
            if bounds[0] >= bounds[1] or bounds[0] < nodes[0] or bounds[1] > nodes[-1]:
                raise ValueError('Region '+identity+' bounds must lie within the mesh and have positive extent')
            for bound in bounds:
                if not np.any(np.isclose(nodes, bound, rtol=0., atol=max(1., abs(bound))*1e-12)):
                    raise _invalid('Region boundaries must coincide with supplied mesh nodes: '+identity+'.'+key, 'regions.'+identity+'.'+key, 'Device', identity, 'um')
            region[key] = [nodes[int(np.argmin(np.abs(np.asarray(nodes)-bound)))] for bound in bounds]
        for field in ('donors_cm3', 'acceptors_cm3', 'generation_cm3_s'):
            region[field] = _nonnegative(raw.get(field, 0.), 'regions.'+identity+'.'+field)
        for previous in cfg['regions']:
            overlaps = all(min(region[axis+'_range_um'][1], previous[axis+'_range_um'][1]) > max(region[axis+'_range_um'][0], previous[axis+'_range_um'][0]) for axis in ('x', 'y')[:dimension])
            if overlaps:
                raise _invalid('Region interiors overlap: '+identity+' and '+previous['id'], 'regions.'+identity, 'Device', identity)
        cfg['regions'].append(region)
    labels = region_labels(cfg)
    if np.any(labels < 0):
        raise _invalid('Material regions must cover every mesh node', 'regions', 'Device')
    if set(np.unique(labels)) != set(range(len(regions))):
        raise ValueError('Every material region must own at least one mesh node')
    # Nodes alone do not prove a filled domain when adjacent intervals omit an interior cell.
    domain_measure = np.prod([cfg[axis+'_nodes_um'][-1]-cfg[axis+'_nodes_um'][0] for axis in ('x', 'y')[:dimension]])
    region_measure = sum(np.prod([r[axis+'_range_um'][1]-r[axis+'_range_um'][0] for axis in ('x', 'y')[:dimension]]) for r in cfg['regions'])
    if not np.isclose(region_measure, domain_measure, rtol=1e-12, atol=0):
        raise _invalid('Material regions must fill the domain without interior holes', 'regions', 'Device')
    contacts = settings.get('contacts')
    if not isinstance(contacts, dict) or set(contacts) != {'left', 'right'}:
        raise _invalid('Supply left and right contact properties', 'contacts', 'Contacts')
    cfg['contacts'] = {}
    for side, raw in contacts.items():
        if not isinstance(raw, dict) or set(raw)-{'kind', 'electron_velocity_cm_s', 'hole_velocity_cm_s', 'work_function_eV'} or raw.get('kind') not in ('Ohmic', 'Schottky'):
            raise ValueError('Contacts support Ohmic or Schottky type and explicit carrier velocities')
        contact = dict(kind=raw['kind'], electron_velocity_cm_s=_nonnegative(raw.get('electron_velocity_cm_s'), side+' electron_velocity_cm_s'),
            hole_velocity_cm_s=_nonnegative(raw.get('hole_velocity_cm_s'), side+' hole_velocity_cm_s'))
        if raw['kind'] == 'Schottky':
            if 'work_function_eV' not in raw:
                raise _invalid('Schottky contacts require an explicit work function', 'contacts.'+side+'.work_function_eV', 'Contacts', side, 'eV')
            contact['work_function_eV'] = _number(raw.get('work_function_eV'), side+' work_function_eV', positive=True)
        elif 'work_function_eV' in raw:
            raise ValueError('Work function applies only to Schottky contacts')
        cfg['contacts'][side] = contact
    voltages = settings.get('voltages_V')
    if not isinstance(voltages, list) or not voltages:
        raise _invalid('Supply an explicit nonempty bias sequence voltages_V', 'voltages_V', 'Study', units='V')
    cfg['voltages_V'] = [_number(v, 'voltages_V') for v in voltages]
    cfg['defects'] = []
    defects = settings.get('defects', [])
    if not isinstance(defects, list):
        raise ValueError('Defects must be a list')
    ids = set()
    for raw in defects:
        allowed = {'id', 'location_um', 'density_cm2', 'sigma_e_cm2', 'sigma_h_cm2', 'energy_eV', 'transition'}
        if not isinstance(raw, dict) or set(raw) != allowed or not isinstance(raw.get('id'), str) or not raw['id'] or raw['id'] in ids:
            raise ValueError('Each defect needs a unique id and fields '+', '.join(sorted(allowed)))
        ids.add(raw['id'])
        defect = dict(id=raw['id'], energy_eV=_number(raw['energy_eV'], 'defect energy_eV'))
        for field in ('density_cm2', 'sigma_e_cm2', 'sigma_h_cm2'):
            defect[field] = _number(raw[field], 'defect '+field, positive=True)
        if dimension == 1:
            points = [[_number(raw['location_um'], 'defect location_um')]]
            defect['location_um'] = points[0][0]
        else:
            value = raw['location_um']
            if not isinstance(value, list) or len(value) != 2 or any(not isinstance(p, list) or len(p) != 2 for p in value):
                raise ValueError('Two-dimensional defects require two endpoints [[x,y],[x,y]] in um')
            points = [[_number(v, 'defect location_um') for v in point] for point in value]
            if points[0] == points[1]:
                raise ValueError('Defect line must have nonzero length')
            defect['location_um'] = points
        for point in points:
            for index, axis in enumerate(('x', 'y')[:dimension]):
                nodes = cfg[axis+'_nodes_um']
                if point[index] < nodes[0] or point[index] > nodes[-1]:
                    raise ValueError('Defects must lie within the semiconductor domain')
                if not np.any(np.isclose(nodes, point[index], rtol=0, atol=max(1., abs(point[index]))*1e-12)):
                    raise ValueError('Defect endpoints must coincide with mesh nodes')
        transition = raw['transition']
        if not isinstance(transition, list) or len(transition) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in transition) or transition[0] <= transition[1]:
            raise ValueError('Defect transition requires decreasing integer empty/occupied charge states')
        defect['transition'] = transition
        cfg['defects'].append(defect)
    return cfg


def execute(prepared, directory, emit=lambda event: None, cancelled=lambda: False):
    directory = Path(directory).resolve()
    result = run_worker(prepared, directory, emit, cancelled)
    result.update(engine='sesame_transport', options=prepared, limitations=LIMITATIONS,
        current_convention='Jx is conventional current density along +x; diode_current is minus its section mean.',
        temperature_model='fixed', defect_energy_reference='intrinsic_level',
        files=dict(iv_csv='transport_iv.csv', states=result.get('state_files', []), engine_log='engine.log', inputs='engine_inputs.json'))
    (directory/'transport_summary.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    return result
