"""Couple saved DC carrier profiles to the current optical structure.

The electrical example is a fixed p+/p/AlGaAs/n/n+ device. Mapping its
area-averaged profiles onto a periodic optical cell preserves the user's
materials and geometry. This is a conditional model, not a finite-pad
electromagnetic or self-consistent optical/transport calculation.
"""
from __future__ import annotations

import copy
import csv
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

E = 1.602176634e-19
EPS0 = 8.8541878128e-12
M0 = 9.1093837139e-31
C = 299792458.0
LAYERS = ('p+ GaAs', 'p GaAs', 'Al0.5Ga0.5As', 'n GaAs', 'n+ GaAs')
EDGES_NM = (0.0, 50.0, 200.0, 220.0, 370.0, 420.0)
# Retain the prior electrical/optical junction and explicit-ITO boundary
# refinement. Uniform control slices add boundaries rather than removing it.
FINE_EDGES_NM = (0, 46, 48, 49, 50, 51, 52, 54, 58, 180, 190, 194, 196,
                 197, 198, 199, 200, 220, 221, 222, 224, 226, 228, 230, 233,
                 237, 244, 260, 350, 360, 366, 370, 374, 380, 390, 394, 398,
                 402, 406, 410, 412, 414, 416, 418, 419, 420, 420.25, 420.5,
                 420.75, 421, 421.5, 422, 423, 424, 426, 428, 430, 435, 440,
                 445, 455, 460)
OPTICAL_SOURCES = {
    'drude_mobility': 'https://doi.org/10.1063/1.372274',
    'interband': 'https://doi.org/10.1109/3.44924',
    'implementation': 'Prior GaAs/AlGaAs study: profiled_device.py, '
                      'gaas_interband.py and poisson_optical_device.py',
}
LIMITATIONS = [
    'Area-averaged solid carrier populations and vertical field moments are '
    'applied to a periodic optical cell; lateral fields and finite contact pads '
    'are absent from this optical calculation.',
    'Drude damping uses transport mobility; optical damping was not measured. '
    'The AlGaAs barrier has no carrier optical correction in this example.',
    'Electro-optic tensors assume (001) material and a field along z. GaAs '
    'coefficients measured near 1.15 micrometres are held constant; the AlGaAs '
    'r41 coefficient is illustrative. Franz-Keldysh absorption is omitted.',
    'Optional GaAs interband response uses parabolic bands at 300 K below '
    'both band edges. Its published density range is 1e16–1e19 cm^-3; '
    'the p+ and p layers require explicitly enabled extrapolation.',
    'Undoped reference applies to the semiconductor. The chosen ITO table '
    'represents the configured nominal bulk carrier density; only the '
    'local Drude difference from that bulk density is added to ITO.',
]


def _finite(value, label, *, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise ValueError(label + ' must be a finite number.')
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(label + ' must be a finite number.') from None
    if not math.isfinite(value) or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise ValueError(label + ' is outside its allowed range.')
    return value


def validate_options(options):
    """Validate persistable draft controls; layer mapping is checked at Run."""
    if isinstance(options,dict) and options.get('model')=='custom_device':
        from custom_device_optics import validate_custom_options
        return validate_custom_options(options)
    from electrical_solver import DEFAULT_OPTIONS, validate_options as validate_electrical
    if not isinstance(options, dict):
        raise ValueError('Electrical settings must be an object.')
    cfg = copy.deepcopy(options)
    electrical_keys = set(DEFAULT_OPTIONS) | {'measured_current', 'geometry_parameters', 'net_doping_cm3'}
    optical_keys = {'optical_enabled', 'electro_optic', 'interband', 'interband_extrapolation',
                    'optical_reference', 'optical_slices_per_layer', 'optical_mapping',
                    'r41_gaas_m_V', 'r41_algaas_m_V', 'requires_native', 'task',
                    'response', 'feature', 'reference_nm', 'tracking_window_nm'}
    if set(cfg) - electrical_keys - optical_keys:
        raise ValueError('Unsupported electrical optical settings: ' + ', '.join(sorted(set(cfg)-electrical_keys-optical_keys)))
    cfg.update(validate_electrical({key: value for key, value in options.items() if key in electrical_keys}))
    for key in ('optical_enabled', 'electro_optic', 'interband', 'interband_extrapolation'):
        value = cfg.get(key, False)
        if not isinstance(value, bool):
            raise ValueError(key + ' must be true or false.')
        cfg[key] = value
    if cfg.get('optical_reference', 'zero_bias') not in ('zero_bias', 'undoped'):
        raise ValueError('Optical reference must be zero_bias or undoped.')
    cfg['optical_reference'] = cfg.get('optical_reference', 'zero_bias')
    if cfg.get('response', 'Absorption') not in ('Reflection', 'Transmission', 'Absorption'):
        raise ValueError('Select reflection, transmission or absorption for resonance tracking.')
    if cfg.get('feature', 'Peak') not in ('Peak', 'Dip'):
        raise ValueError('Select Peak or Dip for resonance tracking.')
    cfg['response'] = cfg.get('response', 'Absorption')
    cfg['feature'] = cfg.get('feature', 'Peak')
    cfg['reference_nm'] = _finite(cfg.get('reference_nm', 1157.), 'Reference wavelength', minimum=1e-6)
    cfg['tracking_window_nm'] = _finite(cfg.get('tracking_window_nm', 1.), 'Tracking window', minimum=1e-6)
    count = _finite(cfg.get('optical_slices_per_layer', 8), 'Optical slices per layer', minimum=1, maximum=100)
    if count != int(count):
        raise ValueError('Optical slices per layer must be an integer.')
    cfg['optical_slices_per_layer'] = int(count)
    mapping = cfg.get('optical_mapping', {})
    if not isinstance(mapping, dict) or set(mapping) - set((*LAYERS, 'ITO')):
        raise ValueError('Optical mapping must use the five electrical layer names and optional ITO.')
    for source, entry in mapping.items():
        if isinstance(entry, str):
            entry = {'layer': entry}
        if not isinstance(entry, dict) or set(entry) - {'layer', 'material'}:
            raise ValueError(source + ': mapping needs an optical layer and material.')
        if any(not isinstance(value, str) for value in entry.values()):
            raise ValueError(source + ': mapping names must be text.')
        mapping[source] = {key: value.strip() for key, value in entry.items()}
    cfg['optical_mapping'] = mapping
    for key, default in (('r41_gaas_m_V', 1.68e-12), ('r41_algaas_m_V', 1.2e-12)):
        cfg[key] = _finite(cfg.get(key, default), key, minimum=-1e-9, maximum=1e-9)
    cfg['requires_native'] = bool(cfg['optical_enabled'] and cfg['electro_optic'])
    return cfg


def prepare_coupling(model, options):
    """Validate the physical mapping before either numerical solver starts."""
    if options.get('model')=='custom_device':
        from custom_device_optics import prepare_custom_coupling
        return prepare_custom_coupling(model,options)
    cfg = validate_options(options)
    cfg['task'] = 'electrical'
    if not cfg['optical_enabled']:
        return cfg
    if cfg['interband'] and not cfg['interband_extrapolation']:
        raise ValueError('The fixed p+ and p device layers exceed the GaAs interband paper range; '
                         'explicitly enable interband extrapolation before running this model.')
    if model.get('mode') != 'Wavelength sweep':
        raise ValueError('Electrical optical coupling requires a wavelength sweep.')
    waves = sorted({float(point[1]) for point in model['points']})
    if not waves or not all(math.isfinite(w) and w > 0 for w in waves):
        raise ValueError('Optical wavelengths must be positive and finite.')
    if not waves[0] <= cfg['reference_nm'] <= waves[-1]:
        raise ValueError('Resonance reference wavelength must lie inside the optical wavelength range.')
    names = {layer['name']: layer for layer in model['layers']}
    materials = {material['name']: material for material in model['materials']}
    if any(not math.isclose(float(model.get(axis, 0)), .444, rel_tol=0, abs_tol=1e-10) for axis in ('ax', 'ay')):
        raise ValueError('Electrical optical coupling requires the studied 444 nm square lattice.')
    sources = list(LAYERS) + (['ITO'] if cfg['model'] == 'explicit_ito' else [])
    positions = []
    for source in sources:
        entry = cfg['optical_mapping'].get(source, {})
        layer_name = entry.get('layer', '')
        if layer_name not in names:
            raise ValueError(source + ': explicitly map an existing optical layer before running optical coupling.')
        layer = names[layer_name]
        position = next(i for i, row in enumerate(model['layers']) if row['name'] == layer_name)
        if position in (0, len(model['layers']) - 1):
            raise ValueError(source + ': a finite optical layer is required.')
        positions.append(position)
        material_name = entry.get('material') or layer['material']
        if material_name not in materials or not (material_name == layer['material'] or any(
                row['layer'] == layer_name and row['material'] == material_name for row in model['patterns'])):
            raise ValueError(source + ': selected optical material is not used in its mapped layer.')
        if material_name != layer['material']:
            raise ValueError(source + ': electrical carriers must map to the optical background material.')
        patterns = [row for row in model['patterns'] if row['layer'] == layer_name]
        if source == 'ITO':
            if patterns:
                raise ValueError('ITO: the electrical example requires an unpatterned optical ITO layer.')
        else:
            if len(patterns) != 1:
                raise ValueError(source + ': use exactly one centered 46 nm air hole, as in the electrical template.')
            hole = patterns[0]
            if (hole.get('shape') != 'circle' or any(abs(float(hole.get(axis, 0))) > 1e-10 for axis in ('cx', 'cy'))
                    or not math.isclose(float(hole.get('sx', 0)), .046, rel_tol=0, abs_tol=1e-10)):
                raise ValueError(source + ': use one centered circular air hole with radius 46 nm.')
            hole_material = materials.get(hole['material'])
            from model import epsilon
            if hole_material is None or hole_material.get('epsilon_tensor') is not None or any(
                    abs(complex(epsilon(hole_material, wave))-1.) > 1e-10 for wave in (waves[0], waves[-1])):
                raise ValueError(source + ': the optical hole must contain air (epsilon = 1).')
        material = materials[material_name]
        if material.get('epsilon_tensor') is not None:
            raise ValueError(source + ': choose a scalar reference material for the electrical correction.')
        if material['model'] == 'table_nk' and (material['grid'][0] > waves[0] or material['grid'][-1] < waves[-1]):
            raise ValueError(material_name + ': the reference optical table must cover the complete wavelength range.')
        thickness = cfg['ito_thickness_nm'] if source == 'ITO' else EDGES_NM[LAYERS.index(source)+1] - EDGES_NM[LAYERS.index(source)]
        if not math.isclose(float(layer['thickness'])*1000.0, thickness, rel_tol=0, abs_tol=1e-6):
            raise ValueError(f'{source}: mapped optical layer must be {thickness:g} nm thick.')
        cfg['optical_mapping'][source] = {'layer': layer_name, 'material': material_name}
    if len(set(positions)) != len(positions) or positions != sorted(positions):
        raise ValueError('Map each electrical layer to a distinct optical layer in device stack order.')
    if any(b != a+1 for a, b in zip(positions, positions[1:])):
        raise ValueError('Mapped device layers must be consecutive in the optical stack.')
    slices = sum(len(_boundaries(cfg, source))-1 for source in sources)
    if len(waves)*slices*len(cfg['biases_V']) > 5_000_000:
        raise ValueError('Limit optical coupling to five million slice/wavelength/bias records; reduce samples or slices.')
    return cfg


def _boundaries(cfg, source):
    start = 420.0 if source == 'ITO' else EDGES_NM[LAYERS.index(source)]
    stop = start+cfg['ito_thickness_nm'] if source == 'ITO' else EDGES_NM[LAYERS.index(source)+1]
    fine = [value for value in FINE_EDGES_NM if start <= value <= stop]
    return np.unique(np.r_[np.linspace(start, stop, cfg['optical_slices_per_layer']+1), fine])


def profile_mobility(density_cm3, kind):
    """Sotoodeh et al. Eq.4/Table I at 300 K, in cm^2/(V s)."""
    if kind == 'electrons':
        maximum, minimum, reference, exponent = 9400., 500., 6e16, .394
    elif kind == 'holes':
        maximum, minimum, reference, exponent = 491.5, 20., 1.48e17, .38
    else:
        raise ValueError('Unknown carrier kind.')
    return minimum + (maximum-minimum)/(1+(density_cm3/reference)**exponent)


def drude_epsilon(wavelengths_nm, density_cm3, kind, *, mass_ratio=None, gamma_rad_s=None):
    """Full complex Drude correction; no infinite-frequency background added."""
    waves = np.asarray(wavelengths_nm, dtype=float)
    density = _finite(density_cm3, 'Carrier concentration', minimum=0, maximum=1e23)
    if not np.isfinite(waves).all() or np.any(waves <= 0):
        raise ValueError('Drude wavelengths must be positive and finite.')
    mass = (mass_ratio if mass_ratio is not None else (.067 if kind == 'electrons' else .5))*M0
    if mass <= 0:
        raise ValueError('Drude conductivity mass must be positive.')
    gamma = gamma_rad_s if gamma_rad_s is not None else E/(mass*profile_mobility(density, kind)*1e-4)
    if not math.isfinite(gamma) or gamma < 0:
        raise ValueError('Drude damping must be nonnegative and finite.')
    omega = 2*np.pi*C/(waves*1e-9)
    return -(density*1e6*E*E/(EPS0*mass))/(omega*omega+1j*gamma*omega)


@lru_cache(maxsize=256)
def _fermi_level(density, kind):
    from scipy.integrate import quad
    from scipy.optimize import brentq
    from scipy.special import expit
    if density == 0:
        return -np.inf
    target = density/(4.3e17 if kind == 'electrons' else 8.3e18)
    def half(eta):
        return 2/np.sqrt(np.pi)*quad(lambda t: np.sqrt(t)*expit(eta-t), 0,
                                   max(80., eta+60.), epsabs=1e-10, epsrel=1e-10)[0]
    return brentq(lambda eta: half(eta)-target, -100., 200., xtol=1e-11)


@lru_cache(maxsize=4)
def _interband_nodes(order):
    from scipy.special import roots_legendre
    a, weights = roots_legendre(order)
    x = (a+1)/2
    return x/(1-x), weights/2/(1-x)**2


def interband_response(wavelengths_nm, density_cm3, kind, *, allow_extrapolation=False, order=512):
    """Prior Bennett/Soref/del Alamo (1990) model, no Drude contribution.

    Band filling and band-gap narrowing use the narrowed parabolic bands.
    Above-edge photon energies require principal-value integration and fail
    explicitly. Densities outside the paper's range require explicit consent
    in the model controls; they are never physically clipped.
    """
    from scipy.constants import hbar, k
    from scipy.special import expit
    density = _finite(density_cm3, 'GaAs interband density', minimum=0, maximum=1e20)
    if kind not in ('electrons', 'holes'):
        raise ValueError('Unknown interband carrier kind.')
    if density and not 1e16 <= density <= 1e19 and not allow_extrapolation:
        raise ValueError('GaAs interband density outside 1e16–1e19 cm^-3; explicitly enable interband extrapolation.')
    waves = np.asarray(wavelengths_nm, dtype=float)
    if not np.isfinite(waves).all() or np.any(waves <= 0):
        raise ValueError('Interband wavelengths must be positive and finite.')
    mass = .066 if kind == 'electrons' else .47
    critical = 1.6e24*(mass/(1.4*13.1))**3
    shift = (.125 if kind == 'electrons' else .11)/13.1*np.cbrt(min(0., 1-density/critical))
    gap = 1.42+shift
    energies = 1239.8419843320026/waves
    if np.any(energies >= min(gap, 1.42)):
        raise ValueError('GaAs interband coupling requires photon energies below both band edges.')
    if density == 0:
        return np.zeros(waves.shape, complex)
    t, weights = _interband_nodes(order)
    delta = t*t
    u = gap+delta
    masses = np.array([.45, .084])
    reduced = 1/(1/.066+1/masses)
    c_total = 2.3e12*np.sqrt(hbar/E)
    c_bands = c_total*reduced**1.5/np.sum(reduced**1.5)
    kinetic = delta[:, None]*(masses/(.066+masses) if kind == 'electrons' else .066/(.066+masses))
    blocked = expit(_fermi_level(density, kind)-kinetic/(k*300/E))
    intrinsic_narrow = 2*c_total*delta/u
    filling = -2*delta/u*np.sum(c_bands*blocked, axis=1)
    unshifted = 2*c_total*delta/(1.42+delta)
    flat = energies.ravel()
    answer = np.empty_like(flat)
    coefficient = C*hbar/E*100/np.pi
    for start in range(0, len(flat), 256):
        energy = flat[start:start+256, None]
        narrowed = (intrinsic_narrow+filling)/(u*u-energy*energy)
        reference = unshifted/((1.42+delta)**2-energy*energy)
        answer[start:start+256] = coefficient*np.sum((narrowed-reference)*weights, axis=1)
    return answer.reshape(waves.shape).astype(complex)


def _read_profile(path):
    required = ('z_nm', 'electrons_cm3', 'holes_cm3', 'Ez_V_m',
                'Ez_squared_V2_m2', 'ito_electrons_cm3', 'layer_name')
    with np.load(path, allow_pickle=False) as record:
        if any(key not in record.files for key in required):
            raise ValueError('Electrical profile is missing its depth, carrier, field or layer identity arrays.')
        profile = {key: np.array(record[key], copy=True) for key in required}
    z = profile['z_nm']
    if z.ndim != 1 or len(z) < 2 or not np.isfinite(z).all() or np.any(np.diff(z) < 0):
        raise ValueError('Electrical profile depths must be finite and sorted.')
    for key in required[1:-1]:
        array = profile[key]
        if array.shape != z.shape or not np.isfinite(array).all():
            raise ValueError('Electrical profile ' + key + ' has invalid values or dimensions.')
        if key != 'Ez_V_m' and np.any(array < 0):
            raise ValueError('Electrical profile ' + key + ' must be nonnegative.')
    if profile['layer_name'].shape != z.shape:
        raise ValueError('Electrical profile layer identities have invalid dimensions.')
    return profile


def _interval_values(profile, source, start, stop):
    mask = profile['layer_name'] == source
    if not np.any(mask):
        raise ValueError(source + ': electrical profile has no samples for the mapped layer.')
    z = profile['z_nm'][mask]
    physical_start = 420.0 if source == 'ITO' else EDGES_NM[LAYERS.index(source)]
    physical_stop = 460.0 if source == 'ITO' else EDGES_NM[LAYERS.index(source)+1]
    if np.any(np.diff(z) <= 0) or z[0] < physical_start-1e-6 or z[-1] > physical_stop+1e-6:
        raise ValueError(source + ': electrical profile samples lie outside this device layer.')
    # The conservative electrical mesh has material-specific boundary nodes.
    # Continue the closest valid same-material value to a missing endpoint;
    # never interpolate an ITO boundary through semiconductor populations.
    nodes = np.unique(np.r_[start, z[(z > start) & (z < stop)], stop])
    result = {}
    for key in ('electrons_cm3', 'holes_cm3', 'Ez_V_m', 'Ez_squared_V2_m2', 'ito_electrons_cm3'):
        samples = np.interp(nodes, z, profile[key][mask])
        result[key] = float(np.sum((samples[:-1]+samples[1:])/2*np.diff(nodes))/(stop-start))
    # Only remove the same demonstrated neutral-contact roundoff as the source
    # study; concentrations appreciably over the model range still fail.
    if source != 'ITO':
        for key in ('electrons_cm3', 'holes_cm3'):
            if result[key] > 1e20*(1+1e-11):
                raise ValueError('GaAs/AlGaAs carrier concentration exceeds 1e20 cm^-3.')
            result[key] = min(result[key], 1e20)
    return result


def _scalar_reference(material, waves):
    from model import epsilon
    return np.array([complex(epsilon(material, wave)) for wave in waves])


def _carrier_epsilon(waves, source, values, cfg, ito_parameters):
    if source == 'ITO':
        return drude_epsilon(waves, values['ito_electrons_cm3'], 'electrons',
                             mass_ratio=ito_parameters['mass_ratio'], gamma_rad_s=ito_parameters['gamma_rad_s'])
    if source == 'Al0.5Ga0.5As':
        return np.zeros(len(waves), complex)
    return (drude_epsilon(waves, values['electrons_cm3'], 'electrons') +
            drude_epsilon(waves, values['holes_cm3'], 'holes'))


def _interband_change(waves, source, values, reference, cfg):
    if not cfg['interband'] or source in ('ITO', 'Al0.5Ga0.5As'):
        return np.zeros(len(waves), complex)
    kind = 'holes' if source.startswith('p') else 'electrons'
    key = 'holes_cm3' if kind == 'holes' else 'electrons_cm3'
    args = {'allow_extrapolation': cfg['interband_extrapolation']}
    response = interband_response(waves, values[key], kind, **args)
    if cfg['optical_reference'] == 'zero_bias':
        response -= interband_response(waves, reference[key], kind, **args)
    return response


def _tensor(epsilon, source, values, reference, cfg):
    """Invert the xy-block impermeability with prior linear/quadratic EO laws."""
    zero_reference = cfg['optical_reference'] == 'zero_bias'
    field = values['Ez_V_m'] - (reference['Ez_V_m'] if zero_reference else 0.)
    square = values['Ez_squared_V2_m2'] - (reference['Ez_squared_V2_m2'] if zero_reference else 0.)
    diagonal = 1/epsilon
    zz = diagonal.copy()
    if source != 'Al0.5Ga0.5As':
        diagonal -= 1.7e-20*square
        zz -= 2.0e-20*square
    cross = -(cfg['r41_algaas_m_V'] if source == 'Al0.5Ga0.5As' else cfg['r41_gaas_m_V'])*field
    denominator = diagonal*diagonal-cross*cross
    if np.any(abs(denominator) < 1e-20) or np.any(abs(zz) < 1e-20):
        raise ValueError('Electro-optic impermeability is singular for the selected profiles.')
    xx = diagonal/denominator
    xy = -cross/denominator
    return xx, xy, 1/zz


def _index(epsilon):
    index = np.sqrt(np.asarray(epsilon, dtype=complex))
    if not np.isfinite(index).all() or np.any(index.real < -1e-10) or np.any(index.imag < -1e-10):
        raise ValueError('Carrier correction produces negative loss or nonfinite index. '
                         'Check that the chosen optical data match the declared reference state.')
    return index.real + 1j*np.maximum(index.imag, 0)


def _ito_parameters(cfg, summary):
    # The selected electrical sheet resistance fixes a transport-derived
    # damping; the user's optical n,k remain the baseline background.
    supplied = summary.get('ito_parameters') or summary.get('material_parameters', {}).get('ITO', {})
    mass = _finite(supplied.get('mass_ratio', .35), 'ITO conductivity mass', minimum=1e-6)
    gamma = supplied.get('gamma_rad_s')
    if gamma is None:
        mobility = 1/(cfg['sheet_resistance_ohm_square']*cfg['ito_thickness_nm']*1e-9*
                      E*cfg['ito_density_cm3']*1e6)
        gamma = E/(mass*M0*mobility)
    return {'mass_ratio': mass, 'gamma_rad_s': _finite(gamma, 'ITO optical damping', minimum=0)}


def coupled_model(model, cfg, profile, reference, *, ito_parameters=None, cancelled=lambda: False):
    """Build one independent bias model plus an index audit without mutations."""
    from backend import Cancelled
    result = copy.deepcopy(model)
    result.pop('measure_phase', None)
    waves = sorted({float(point[1]) for point in model['points']})
    reference_materials = {row['name']: row for row in model['materials']}
    mappings = {entry['layer']: (source, entry['material']) for source, entry in cfg['optical_mapping'].items()
                if source in LAYERS or (source == 'ITO' and cfg['model'] == 'explicit_ito')}
    layers, patterns, audits = [], [], []
    used_layer_names = {row['name'] for row in model['layers']}
    used_material_names = {row['name'] for row in model['materials']}
    ito_parameters = ito_parameters or _ito_parameters(cfg, {})
    for layer in model['layers']:
        old_patterns = [row for row in model['patterns'] if row['layer'] == layer['name']]
        if layer['name'] not in mappings:
            layers.append(copy.deepcopy(layer))
            patterns.extend(copy.deepcopy(old_patterns))
            continue
        source, material_name = mappings[layer['name']]
        base = _scalar_reference(reference_materials[material_name], waves)
        boundaries = _boundaries(cfg, source)
        accumulated = 0.
        for index, (start, stop) in enumerate(zip(boundaries[:-1], boundaries[1:])):
            if cancelled():
                raise Cancelled('Electrical optical coupling cancelled.')
            values = _interval_values(profile, source, start, stop)
            ref = _interval_values(reference, source, start, stop)
            change = _carrier_epsilon(waves, source, values, cfg, ito_parameters)
            if cfg['optical_reference'] == 'zero_bias':
                change -= _carrier_epsilon(waves, source, ref, cfg, ito_parameters)
            elif source == 'ITO':
                # ITO optical data already include their bulk free carriers;
                # the semiconductor's undoped convention does not make ITO
                # an intrinsic dielectric with a second full Drude term.
                change -= drude_epsilon(waves, cfg['ito_density_cm3'], 'electrons',
                                        mass_ratio=ito_parameters['mass_ratio'],
                                        gamma_rad_s=ito_parameters['gamma_rad_s'])
            eps = (_index(base)+_interband_change(waves, source, values, ref, cfg))**2+change
            if cfg['electro_optic'] and source != 'ITO':
                xx, xy, zz = _tensor(eps, source, values, ref, cfg)
            else:
                xx, xy, zz = eps, np.zeros(len(waves), complex), eps
            scalar, plus, minus, z_index = map(_index, (xx, xx-xy, xx+xy, zz))
            suffix = f'__electrical_{index:03d}'
            layer_name, new_material = layer['name']+suffix, material_name+suffix+'_'+layer['name']
            while layer_name in used_layer_names:
                layer_name += '_'
            while new_material in used_material_names:
                new_material += '_'
            used_layer_names.add(layer_name)
            used_material_names.add(new_material)
            table = [[wave, float(n.real), float(n.imag)] for wave, n in zip(waves, scalar)]
            clone = {'name': new_material, 'model': 'table_nk', 'a': table[0][1], 'b': table[0][2],
                     'table': table, 'grid': waves, 'electrical_source_layer': source,
                     'electrical_optical_reference': cfg['optical_reference']}
            if cfg['electro_optic'] and source != 'ITO':
                clone['epsilon_tensor'] = [
                    [[[float(x.real), float(x.imag)], [float(y.real), float(y.imag)], [0., 0.]],
                     [[float(y.real), float(y.imag)], [float(x.real), float(x.imag)], [0., 0.]],
                     [[0., 0.], [0., 0.], [float(z.real), float(z.imag)]]]
                    for x, y, z in zip(xx, xy, zz)]
            result['materials'].append(clone)
            thickness = (float(layer['thickness'])-accumulated if index == len(boundaries)-2 else (stop-start)/1000)
            accumulated += thickness
            row = dict(copy.deepcopy(layer), name=layer_name, thickness=thickness)
            if row['material'] == material_name:
                row['material'] = new_material
            layers.append(row)
            for pattern in old_patterns:
                new_pattern = dict(copy.deepcopy(pattern), layer=layer_name)
                if new_pattern['material'] == material_name:
                    new_pattern['material'] = new_material
                patterns.append(new_pattern)
            for position, wave in enumerate(waves):
                audits.append(dict(electrical_layer=source, optical_layer=layer['name'],
                    z_start_nm=float(start), z_end_nm=float(stop), wavelength_nm=wave,
                    n=float(scalar[position].real), k=float(scalar[position].imag),
                    n_plus=float(plus[position].real), k_plus=float(plus[position].imag),
                    n_minus=float(minus[position].real), k_minus=float(minus[position].imag),
                    n_z=float(z_index[position].real), k_z=float(z_index[position].imag),
                    delta_n=0., delta_k=0.))
    result['layers'], result['patterns'] = layers, patterns
    result['electrical_coupling'] = {'reference': cfg['optical_reference'], 'electro_optic': cfg['electro_optic'],
                                    'interband': cfg['interband'], 'slices_per_layer': cfg['optical_slices_per_layer']}
    return result, audits


def _save_csv(path, records):
    if not records:
        return
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def execute_electrical(model, performance, cfg, directory, executor, emit=lambda event: None, cancelled=lambda: False):
    """Save the electrical solve, then optionally calculate each optical bias."""
    if cfg.get('model')=='custom_device':
        from custom_device_optics import execute_custom_electrical
        return execute_custom_electrical(model,performance,cfg,directory,executor,emit,cancelled)
    from backend import Cancelled
    from electrical_solver import DEFAULT_OPTIONS, solve
    from index_shift import sampled_feature
    from optical_objective import valid_spectrum
    cfg = prepare_coupling(model, cfg)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    electrical_keys = set(DEFAULT_OPTIONS) | {'measured_current', 'geometry_parameters', 'net_doping_cm3'}
    try:
        electrical = solve({key: value for key, value in cfg.items() if key in electrical_keys},
                           directory/'electrical', emit, cancelled)
    except InterruptedError as exc:
        raise Cancelled(str(exc)) from exc
    (directory/'electrical_summary.json').write_text(json.dumps(electrical, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    if cancelled():
        raise Cancelled('Electrical calculation cancelled.')
    summary = dict(status='complete', task='electrical', model=cfg['model'], optical_enabled=cfg['optical_enabled'],
                   biases_V=[row['bias_V'] for row in electrical['results']],
                   electrical_summary='electrical_summary.json', optical_reference=cfg['optical_reference'],
                   electro_optic=cfg['electro_optic'], interband=cfg['interband'],
                   interband_extrapolation=cfg['interband_extrapolation'],
                   limitations=list(electrical.get('limitations', []))+LIMITATIONS,
                   optical_sources=OPTICAL_SOURCES)
    if cfg['optical_enabled']:
        outputs = sorted(electrical['results'], key=lambda row: (abs(float(row['bias_V'])), float(row['bias_V'])))
        zero = next((row for row in outputs if float(row['bias_V']) == 0.), None)
        if zero is None:
            raise ValueError('Electrical optical coupling requires a solved 0 V reference.')
        reference = _read_profile(zero['profile_npz'])
        parameters = _ito_parameters(cfg, electrical)
        perf = copy.deepcopy(performance)
        if cfg['requires_native']:
            perf.update(solver_backend='native', mirror_symmetry=False)
        spectra, audits, features, baseline, baseline_indices, baseline_feature = [], [], [], None, None, None
        for case, output in enumerate(outputs):
            if cancelled():
                raise Cancelled('Electrical optical coupling cancelled.')
            bias = float(output['bias_V'])
            shifted, indices = coupled_model(model, cfg, _read_profile(output['profile_npz']), reference,
                                             ito_parameters=parameters, cancelled=cancelled)
            emit(dict(kind='log', text=f'Computing optical response at {bias:g} V…'))
            rows, diagnostics = executor(shifted, perf, lambda event: emit(dict(event, bias_V=bias)), cancelled)
            if len(rows) != len(model['points']) or not valid_spectrum(rows):
                raise ValueError('Electrical optical calculation returned an invalid or incomplete spectrum.')
            if baseline is None:
                baseline = rows
                baseline_indices = indices
                baseline_feature = sampled_feature(rows, cfg['response'], cfg['feature'],
                                                   cfg['reference_nm'], cfg['tracking_window_nm'])
            if any(tuple(row[1:3]) != tuple(base[1:3]) for row, base in zip(rows, baseline)):
                raise ValueError('Electrical optical spectra do not share the reference wavelength/angle grid.')
            for row, base in zip(rows, baseline):
                spectra.append(dict(bias_V=bias, wavelength_nm=row[1], angle_deg=row[2], R=row[3], T=row[4], A=row[5],
                                    dR=row[3]-base[3], dT=row[4]-base[4], dA=row[5]-base[5]))
            center = baseline_feature[1] if baseline_feature else cfg['reference_nm']
            found = sampled_feature(rows, cfg['response'], cfg['feature'], center, cfg['tracking_window_nm'])
            fixed = next((row for row in rows if baseline_feature and row[1:3] == baseline_feature[1:3]), None)
            shift = found[1]-baseline_feature[1] if found and baseline_feature else None
            features.append(dict(bias_V=bias, response=cfg['response'], feature=cfg['feature'],
                feature_nm=found[1] if found else None, shift_nm=shift,
                baseline_nm=baseline_feature[1] if baseline_feature else None,
                fixed_R=fixed[3] if fixed else None, fixed_T=fixed[4] if fixed else None,
                fixed_A=fixed[5] if fixed else None,
                dR=fixed[3]-baseline_feature[3] if fixed else None,
                dT=fixed[4]-baseline_feature[4] if fixed else None,
                dA=fixed[5]-baseline_feature[5] if fixed else None,
                status='sampled feature' if found and baseline_feature else 'no resolved baseline/feature'))
            for index, base in zip(indices, baseline_indices):
                audits.append(dict(bias_V=bias, **dict(index, delta_n=index['n']-base['n'], delta_k=index['k']-base['k'])))
            # JSON audit stores only sampled material tables and geometry, not
            # electrical solver objects. It can be inspected without S4.
            (directory/f'electrical_optical_model_{case:03d}.json').write_text(
                json.dumps(dict(bias_V=bias, model=shifted, diagnostics=diagnostics), indent=2, allow_nan=False)+'\n', encoding='utf-8')
            emit(dict(kind='progress', completed=case+1, total=len(outputs), text=f'Optical biases: {case+1}/{len(outputs)}'))
        _save_csv(directory/'electrical_optical_spectra.csv', spectra)
        _save_csv(directory/'electrical_index_changes.csv', audits)
        _save_csv(directory/'electrical_features.csv', features)
        _save_csv(directory/'results.csv', [dict(wavelength_nm=row[1], angle_deg=row[2], R=row[3], T=row[4], A=row[5]) for row in baseline])
        summary.update(spectra=len(outputs), optical_samples=len(spectra), optical_spectra='electrical_optical_spectra.csv',
                       optical_indices='electrical_index_changes.csv', ito_optical_parameters=parameters,
                       optical_solver_backend=perf.get('solver_backend', 'native'),
                       optical_features='electrical_features.csv',
                       baseline_nm=baseline_feature[1] if baseline_feature else None,
                       max_abs_shift_nm=max((abs(row['shift_nm']) for row in features if row['shift_nm'] is not None), default=None),
                       response=cfg['response'], feature=cfg['feature'],
                       tracking_note='Nearest sampled local peak/dip relative to 0 V. Mode identity and '
                                     'basis convergence are not verified; fixed R/T/A use the same 0 V feature wavelength.')
        summary.update(spectra_csv=summary['optical_spectra'], index_profiles_csv=summary['optical_indices'],
                       features_csv=summary['optical_features'])
    electrical['optical'] = summary
    electrical['coupling_options'] = cfg
    electrical['limitations'] = summary['limitations']
    (directory/'electrical_summary.json').write_text(json.dumps(electrical, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (directory/'search_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return dict(kind='search_complete', directory=str(directory), summary=summary)
