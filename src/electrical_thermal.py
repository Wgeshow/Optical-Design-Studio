"""Conservative steady lattice heat on the editable finite device.

Power is an explicit input in watts per layer. This is a prescribed-heat study,
not self-consistent electrothermal transport: electrical current, recombination
energy, contact dissipation and temperature feedback are not inferred.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.sparse import coo_matrix

from electrical_mesh import solve_linear_system
from input_diagnostics import diagnostic, InputValidationError

FACES = ('x_min', 'x_max', 'y_min', 'y_max', 'z_min', 'z_max')
LIMITATIONS = [
    'Prescribed steady heat with isotropic, temperature-independent thermal conductivity; no electrical or optical temperature feedback.',
    'Supplied layer power is distributed uniformly per solid volume in that layer. It is not calculated from terminal current, carrier transport or optical absorption.',
    'Thermal boundaries apply to the outer rectangular mesh faces. Missing faces are insulated; internal material interfaces have perfect thermal contact.',
    'No automatic glass support, heat sink, interface resistance, radiation, transient heat capacity or hot-carrier temperature is added.',
    'The electrical geometry and its rasterized features are reused exactly. Thermal mesh convergence and material calibration remain user responsibilities.',
]


def _invalid(message, field, section, object_id='', units=''):
    return InputValidationError([diagnostic(message, workspace='thermal', field=field, section=section, object_id=object_id, units=units)])


def _number(value, label, *, positive=False, field='', section='', object_id='', units=''):
    def invalid(message):
        return _invalid(message, field, section, object_id, units) if field else ValueError(message)
    if isinstance(value, bool):
        raise invalid(label+' must be a finite number')
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise invalid(label+' must be a finite number') from None
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise invalid(label+(' must be positive and finite' if positive else ' must be nonnegative and finite'))
    return result


def _boundaries(values, ambient):
    if not isinstance(values, dict) or set(values)-set(FACES):
        raise _invalid('Thermal boundaries must use x_min/x_max/y_min/y_max/z_min/z_max', 'boundaries', 'boundaries')
    result = {}
    for face, row in values.items():
        if not isinstance(row, dict):
            raise _invalid('Thermal boundary '+face+' must be an object', 'boundaries.'+face, 'boundaries', face)
        kind = row.get('kind')
        fields = {'kind'} if kind == 'insulated' else {'kind', 'temperature_K'}
        if kind == 'convection':
            fields.add('coefficient_W_m2K')
        if kind not in ('fixed_temperature', 'convection', 'insulated') or set(row)-fields:
            raise _invalid('Unsupported thermal boundary on '+face, 'boundaries.'+face+'.kind', 'boundaries', face)
        boundary = dict(kind=kind)
        if kind != 'insulated':
            boundary['temperature_K'] = _number(row.get('temperature_K', ambient), face+' temperature', positive=True, field='boundaries.'+face+'.temperature_K', section='boundaries', object_id=face, units='K')
        if kind == 'convection':
            boundary['coefficient_W_m2K'] = _number(row.get('coefficient_W_m2K'), face+' convection coefficient', positive=True, field='boundaries.'+face+'.coefficient_W_m2K', section='boundaries', object_id=face, units='W/(m² K)')
        result[face] = boundary
    return result


def validate_thermal(config=None, material_library=None, device=None):
    """Normalize portable settings without choosing unsupplied material laws."""
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError('Thermal options must be an object')
    result = dict(enabled=False, power_by_layer_W={}, conductivity={},
                  void_conductivity_W_mK=None, ambient_temperature_K=300.,
                  boundaries={}, temperature_limit_K=None)
    unknown = set(config)-set(result)
    if unknown:
        raise ValueError('Unsupported thermal options: '+', '.join(sorted(unknown)))
    result.update(config)
    if not isinstance(result['enabled'], bool):
        raise ValueError('Thermal enabled must be true or false')
    result['ambient_temperature_K'] = _number(result['ambient_temperature_K'], 'Ambient temperature', positive=True, field='ambient_temperature_K', section='boundaries', units='K')
    result['boundaries'] = _boundaries(result['boundaries'], result['ambient_temperature_K'])
    for field in ('void_conductivity_W_mK', 'temperature_limit_K'):
        if result[field] is not None:
            result[field] = _number(result[field], field, positive=True, field=field, section='materials' if field.startswith('void') else 'validity')
    powers = result['power_by_layer_W']
    if not isinstance(powers, dict) or any(not isinstance(key, str) or not key.strip() for key in powers):
        raise _invalid('Thermal layer powers must map layer IDs to watts', 'power_by_layer_W', 'heat_sources')
    result['power_by_layer_W'] = {key: _number(value, 'Layer power '+key, field='power_by_layer_W.'+key, section='heat_sources', object_id=key, units='W') for key, value in powers.items()}
    values = result['conductivity']
    if not isinstance(values, dict):
        raise _invalid('Thermal conductivity must map material IDs to sourced values', 'conductivity', 'materials')
    material_ids = {row['id'] for row in material_library} if material_library is not None else None
    result['conductivity'] = {}
    for ident, row in values.items():
        if not isinstance(ident, str) or not ident.strip() or (material_ids is not None and ident not in material_ids):
            raise _invalid('Unknown thermal material ID: '+str(ident), 'conductivity', 'materials', str(ident))
        if not isinstance(row, dict) or set(row) != {'value_W_mK', 'source'}:
            raise _invalid('Each thermal conductivity needs value_W_mK and source', 'conductivity.'+ident, 'materials', ident)
        if not isinstance(row['source'], str) or not row['source'].strip():
            raise _invalid('Thermal conductivity needs an explicit source or measurement note', 'conductivity.'+ident+'.source', 'materials', ident)
        result['conductivity'][ident] = dict(value_W_mK=_number(row['value_W_mK'], 'Conductivity '+ident, positive=True, field='conductivity.'+ident+'.value_W_mK', section='materials', object_id=ident, units='W/(m K)'),
                                           source=row['source'].strip())
    if result['enabled']:
        if not any(row['kind'] != 'insulated' for row in result['boundaries'].values()):
            raise _invalid('Steady heat requires at least one fixed-temperature or convection boundary', 'boundaries', 'boundaries')
        if not result['conductivity']:
            raise _invalid('Thermal conductivity must be supplied explicitly for occupied materials', 'conductivity', 'materials')
        if device is not None:
            from custom_electrical_solver import build_mesh
            from electrical_material_library import builtin_materials
            _mesh_inputs(build_mesh(device, material_library if material_library is not None else builtin_materials(), require_contacts=False), result)
    return result


def _mesh_inputs(mesh, cfg):
    """Resolve sources and material laws on occupied cells, also for preflight."""
    layer_ids = {row['id'] for row in mesh['bounds']}
    if set(cfg['power_by_layer_W'])-layer_ids:
        raise _invalid('Heat source references missing or disabled device layers', 'power_by_layer_W', 'heat_sources')
    conductivity = np.empty(mesh['shape'])
    for index in np.unique(mesh['material_index']):
        material = mesh['materials'][int(index)]['id']
        if material == '__void__':
            value = cfg['void_conductivity_W_mK']
            if value is None:
                raise _invalid('Thermal mesh contains voids: supply void_conductivity_W_mK explicitly', 'void_conductivity_W_mK', 'materials', '__void__', 'W/(m K)')
        elif material in cfg['conductivity']:
            value = cfg['conductivity'][material]['value_W_mK']
        else:
            raise _invalid('Missing thermal conductivity for occupied material '+material, 'conductivity.'+material, 'materials', material, 'W/(m K)')
        conductivity[mesh['material_index'] == index] = value
    heat = np.zeros(mesh['shape'])
    for index, layer in enumerate(mesh['bounds']):
        power = cfg['power_by_layer_W'].get(layer['id'], 0.)
        selected = (mesh['layer_index'] == index) & mesh['solid']
        volume = float(mesh['volume'][selected].sum())
        if power > 0 and volume <= 0:
            raise ValueError('Positive heat power has no solid volume in layer '+layer['id'])
        if power:
            heat[selected] = power/volume
    return conductivity, heat


def solve_steady_heat(faces_m, conductivity_W_mK, heat_density_W_m3, boundaries,
                      *, reference_temperature_K=300., cancelled=lambda: False):
    """Solve -div(k grad T)=q on nonuniform cell volumes in SI units.

    Face conductance is area divided by both half-cell resistances. Boundary
    conductance includes the half-cell resistance and, for convection, 1/h.
    The solve uses a temperature rise to preserve small-signal precision.
    """
    if cancelled():
        raise InterruptedError('Thermal study cancelled')
    reference = _number(reference_temperature_K, 'Reference temperature', positive=True)
    boundaries = _boundaries(boundaries, reference)
    if not any(row['kind'] != 'insulated' for row in boundaries.values()):
        raise ValueError('Steady heat requires an anchored thermal boundary')
    if len(faces_m) != 3:
        raise ValueError('Thermal mesh needs three face-coordinate arrays')
    faces = [np.asarray(axis, float) for axis in faces_m]
    if any(axis.ndim != 1 or len(axis) < 2 or not np.isfinite(axis).all() or np.any(np.diff(axis) <= 0) for axis in faces):
        raise ValueError('Thermal mesh faces must be finite and strictly increasing')
    widths = [np.diff(axis) for axis in faces]
    shape = tuple(len(axis) for axis in widths)
    conductivity = np.broadcast_to(np.asarray(conductivity_W_mK, float), shape)
    density = np.broadcast_to(np.asarray(heat_density_W_m3, float), shape)
    if not np.isfinite(conductivity).all() or np.any(conductivity <= 0):
        raise ValueError('Thermal conductivity must be positive and finite in every cell')
    if not np.isfinite(density).all() or np.any(density < 0):
        raise ValueError('Prescribed heat density must be finite and nonnegative')
    size = math.prod(shape)
    ids = np.arange(size).reshape(shape)
    volume = widths[0][:, None, None]*widths[1][None, :, None]*widths[2][None, None, :]
    power = (density*volume).ravel()
    diagonal = np.zeros(size)
    rows, columns, entries = [], [], []
    face_areas = []
    half_resistance = []
    for axis in range(3):
        dimension = [1]*3
        dimension[axis] = shape[axis]
        distance = widths[axis].reshape(dimension)/2
        resistance = np.broadcast_to(distance, shape)/conductivity
        half_resistance.append(resistance)
        area = volume/(2*distance)
        face_areas.append(area)
        first = [slice(None)]*3
        second = first.copy()
        first[axis], second[axis] = slice(None, -1), slice(1, None)
        first, second = tuple(first), tuple(second)
        a, b = ids[first].ravel(), ids[second].ravel()
        conductance = (area[first]/(resistance[first]+resistance[second])).ravel()
        np.add.at(diagonal, a, conductance)
        np.add.at(diagonal, b, conductance)
        rows.extend((a, b)); columns.extend((b, a)); entries.extend((-conductance, -conductance))
    rhs = power.copy()
    boundary_terms = {}
    for face, row in boundaries.items():
        if row['kind'] == 'insulated':
            continue
        axis = 'xyz'.index(face[0])
        selected = [slice(None)]*3
        selected[axis] = 0 if face.endswith('min') else -1
        selected = tuple(selected)
        boundary_ids = ids[selected].ravel()
        resistance = half_resistance[axis][selected]
        if row['kind'] == 'convection':
            resistance = resistance+1/row['coefficient_W_m2K']
        conductance = (face_areas[axis][selected]/resistance).ravel()
        diagonal[boundary_ids] += conductance
        rhs[boundary_ids] += conductance*(row['temperature_K']-reference)
        boundary_terms[face] = (boundary_ids, conductance, row['temperature_K'])
    nodes = np.arange(size)
    rows.append(nodes); columns.append(nodes); entries.append(diagonal)
    matrix = coo_matrix((np.concatenate(entries), (np.concatenate(rows), np.concatenate(columns))), shape=(size, size)).tocsr()
    rise, solver = solve_linear_system(matrix, rhs, cancelled=cancelled)
    temperature = rise.reshape(shape)+reference
    if not np.isfinite(temperature).all() or np.any(temperature <= 0):
        raise RuntimeError('Thermal solve produced invalid absolute temperatures')
    outward = {face: float(np.dot(g, rise[index]-(temp-reference)))
               for face, (index, g, temp) in boundary_terms.items()}
    for face in FACES:
        outward.setdefault(face, 0.)
    total = float(power.sum())
    net_outward = sum(outward.values())
    residual = matrix@rise-rhs
    scale = max(total, sum(abs(value) for value in outward.values()), 1e-30)
    balance = abs(net_outward-total)
    relative = balance/scale
    # A relative-only threshold is inappropriate for an exactly isothermal,
    # zero-source state; it is already exact because the rise solve is zero.
    if balance > 1e-14+1e-6*scale:
        raise RuntimeError('Steady heat failed the independent boundary power balance')
    return dict(temperature_K=temperature, temperature_rise_K=rise.reshape(shape),
                reference_temperature_K=reference, heat_density_W_m3=density.copy(),
                conductivity_W_mK=conductivity.copy(), cell_volumes_m3=volume,
                checks=dict(input_power_W=total, outward_power_W=net_outward,
                            boundary_outward_power_W=outward, power_balance_error_W=balance,
                            relative_power_balance=relative, max_cell_residual_W=float(np.max(np.abs(residual))),
                            minimum_temperature_K=float(temperature.min()), maximum_temperature_K=float(temperature.max()),
                            linear_solver=solver))


def execute_thermal(summary, directory, config, emit=lambda event: None, cancelled=lambda: False):
    """Save one prescribed-power study on the exact editable device geometry.

    This is a geometry study independent of electrical bias. The same imposed
    power is not relabeled as multiple predicted bias-dependent temperatures.
    """
    from custom_electrical_solver import build_mesh
    from electrical_material_library import builtin_materials
    options = summary.get('options', {})
    library = options.get('material_library', builtin_materials())
    cfg = validate_thermal(config, library)
    if not cfg['enabled']:
        return dict(enabled=False, model_scope='prescribed_heat')
    if not isinstance(options.get('device'), dict):
        raise ValueError('Thermal studies require an explicit editable device')
    if cancelled():
        raise InterruptedError('Thermal study cancelled')
    started = time.monotonic()
    emit(dict(phase='thermal', progress=0., message='Preparing heat flow on the editable device mesh'))
    mesh = build_mesh(options['device'], library, require_contacts=False)
    conductivity, heat = _mesh_inputs(mesh, cfg)
    result = solve_steady_heat(mesh['faces'], conductivity, heat, cfg['boundaries'],
                               reference_temperature_K=cfg['ambient_temperature_K'], cancelled=cancelled)
    if cancelled():
        raise InterruptedError('Thermal study cancelled')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    volume_path = directory/'thermal_volume.npz'
    summary_path = directory/'thermal_summary.json'
    maximum = result['checks']['maximum_temperature_K']
    limit = cfg['temperature_limit_K']
    status = 'validity_limit' if limit is not None and maximum > limit else 'complete'
    axes = [dict(name=axis, coordinate=axis+'_um', unit='µm') for axis in ('x','y','z')]
    axis_metadata = {key:dict(axes=axes,unit=unit) for key,unit in
        [('temperature_K','K'),('temperature_rise_K','K'),('heat_density_W_m3','W/m³'),('conductivity_W_mK','W/(m K)'),('layer_index','index'),('material_index','index')]}
    np.savez_compressed(volume_path, **{key: value for key, value in result.items() if key != 'checks'},
                        x=mesh['axes'][0], y=mesh['axes'][1], z=mesh['axes'][2],
                        x_um=mesh['axes'][0]*1e6,y_um=mesh['axes'][1]*1e6,z_um=mesh['axes'][2]*1e6,
                        array_axes=np.array(json.dumps(axis_metadata,ensure_ascii=False)),
                        x_faces_m=mesh['faces'][0], y_faces_m=mesh['faces'][1], z_faces_m=mesh['faces'][2],
                        layer_index=mesh['layer_index'], material_index=mesh['material_index'], solid=mesh['solid'],
                        material_ids=np.array([row['id'] for row in mesh['materials']]),
                        layer_ids=np.array([row['id'] for row in mesh['bounds']]))
    output = dict(schema_version=1, enabled=True, model_scope='prescribed_heat', status=status,
                  options=cfg, checks=result['checks'], limitations=LIMITATIONS,
                  geometry=dict(device=mesh['device'], mesh_shape=list(mesh['shape'])),
                  volume_npz=str(volume_path), summary_json=str(summary_path),
                  elapsed_s=time.monotonic()-started,
                  provenance=dict(method='Conservative cell-centered 3D finite-volume Fourier heat conduction',
                      equation='-div(k grad T) = prescribed heat density',
                      boundary_flux_sign='Positive watts leave the device',
                      source_model='Explicit total watts per layer distributed uniformly over its solid volume',
                      bias_dependence='No predicted bias dependence; prescribed power is independent of electrical bias',
                      geometry_source='Current editable device; no experiment-specific dimensions or support added',
                      prior_method='2026-10-12 semiconductor 3D study: thermal_solver.py conservative heat-flow method',
                      thermal_conductivity_sources={key: row['source'] for key, row in cfg['conductivity'].items()}))
    if status == 'validity_limit':
        output['status_reason'] = 'Calculated temperature exceeds the explicit temperature_limit_K; not evidence of thermal runaway.'
    portable = dict(output, volume_npz=volume_path.name, summary_json=summary_path.name)
    summary_path.write_text(json.dumps(portable, indent=2, allow_nan=False), encoding='utf-8')
    emit(dict(phase='thermal', progress=1., message='Prescribed-heat temperature and power-balance results saved'))
    return output
