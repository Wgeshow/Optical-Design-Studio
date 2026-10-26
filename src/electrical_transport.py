"""Explicit, sourced electrical transport models for planar devices.

This module deliberately does not turn a 3D electrostatic carrier reservoir into
a current source. Semiconductor transport solves Poisson and both continuity
equations in DEVSIM, on an independently validated planar homojunction geometry.
Dielectric current laws are pre-damage models; a field threshold is a screening
criterion, never a prediction of a conducting breakdown filament.

Public configuration is JSON-safe. Every fitted physical parameter group needs
``parameter_source``; there are no implicit lifetimes, trap barriers, ionization
coefficients or dielectric breakdown strengths. SI at public boundaries except
the explicitly named cm-based semiconductor parameters and carrier densities.
"""
from __future__ import annotations

from copy import deepcopy
import math
import threading
import uuid

import numpy as np
from scipy.constants import e, epsilon_0, h, hbar, k, m_e
from scipy.integrate import cumulative_trapezoid, trapezoid
from scipy.optimize import brentq


REFERENCES = {
    'drift_diffusion': 'https://devsim.net/examples_short.html#diode',
    'scharfetter_gummel': 'https://doi.org/10.1109/T-ED.1969.16566',
    'srh': 'https://doi.org/10.1103/PhysRev.87.835',
    'field_emission': 'https://doi.org/10.1098/rspa.1928.0091',
    'direct_tunneling': 'https://doi.org/10.1063/1.1702682',
    'schottky_poole_frenkel': 'https://doi.org/10.1103/PhysRev.155.657',
    'avalanche_implementation': 'https://devsim.com/avalanche-modeling/',
    'gaas_local_model_limits': 'https://doi.org/10.1109/TED.2003.816918',
    'velocity_saturation': 'https://doi.org/10.1109/PROC.1967.6123',
    'fermi_dirac_transport': 'https://arxiv.org/abs/1911.00377',
    'heterojunction_interface_limits': 'https://doi.org/10.1109/16.52447',
}
_NATIVE_LOCK = threading.RLock()
MODES = ('disabled', 'dielectric_leakage', 'semiconductor_dd')
DIELECTRIC_MECHANISMS = ('ohmic', 'poole_frenkel', 'schottky',
                        'fowler_nordheim', 'direct_tunneling')
SEMICONDUCTOR_LIMITATIONS = [
    'One-dimensional planar homojunction transport, uniformly extruded across the full contacted area; lateral shapes, partial contacts and heterojunctions are rejected.',
    'Boltzmann carrier statistics, complete ionization and the Einstein relation are used. Carrier densities above 0.1 of the relevant band density of states are rejected.',
    'SRH generation/recombination and local impact ionization are included only when their parameters are explicitly supplied. Band-to-band tunneling, surface leakage, radiative/Auger recombination, traps with dynamic occupation and self-heating are omitted.',
    'Local avalanche coefficients omit carrier energy history and dead space. Their applicability to thin multiplication layers must be established independently.',
    'Voltage-controlled stationary solutions do not predict post-damage conduction or Geiger-mode transients. Solver failure is not a measured or predicted breakdown voltage.',
]


class ModelValidityError(ValueError):
    """A requested state lies outside a stated physical model's domain."""


def _number(value, label, *, positive=False, nonnegative=False):
    if isinstance(value, bool):
        raise ValueError(label + ' must be a finite number')
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(label + ' must be a finite number') from None
    if not math.isfinite(result):
        raise ValueError(label + ' must be a finite number')
    if positive and result <= 0:
        raise ValueError(label + ' must be greater than zero')
    if nonnegative and result < 0:
        raise ValueError(label + ' must be nonnegative')
    return result


def _check_boltzmann_band_consistency(properties, temperature):
    """Ensure the density reference can be mapped to the plotted band gauge."""
    vt=k*temperature/e
    mismatch=properties['bandgap_eV']+vt*(2*math.log(properties['intrinsic_cm3'])-
        math.log(properties['Nc_cm3'])-math.log(properties['Nv_cm3']))
    if abs(mismatch)>1e-5:
        raise ModelValidityError('Boltzmann intrinsic_cm3 must agree with Nc_cm3, Nv_cm3 and bandgap_eV; the supplied values imply inconsistent carrier and band-energy references')


def _group(value, fields, label, nonnegative=(), optional=()):
    if not isinstance(value, dict):
        raise ValueError(label + ' must be an object')
    unknown = set(value) - set(fields) - set(optional) - {'parameter_source'}
    if unknown:
        raise ValueError(label + ' has unsupported fields: ' + ', '.join(sorted(unknown)))
    source = value.get('parameter_source')
    if not isinstance(source, str) or not source.strip():
        raise ValueError(label + ' requires parameter_source describing the measurement, reference or explicit assumption')
    result = {'parameter_source': source.strip()}
    for field in fields:
        if field not in value:
            raise ValueError(label + ' requires ' + field)
        result[field] = _number(value[field], label + '.' + field,
                                positive=field not in nonnegative,
                                nonnegative=field in nonnegative)
    for field in optional:
        if field in value:
            result[field] = _number(value[field], label + '.' + field, positive=True)
    return result


def validate_transport(cfg=None):
    """Normalize optional transport settings without importing native DEVSIM.

    ``semiconductor_dd`` accepts optional ``srh``, ``avalanche`` and
    ``high_field_mobility`` groups, plus numerical ``nodes_per_layer`` (>= 4)
    and ``max_bias_step_V``. ``dielectric_leakage`` requires
    ``material_models``: {material_id: {mechanism, parameters}}. Parameters carry
    their source. Only bulk Ohmic/PF laws may be placed in a multilayer stack.
    ``breakdown_fields`` optionally maps material IDs to a sourced
    ``critical_field_V_m``; it works in either enabled mode.
    """
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise ValueError('Transport settings must be an object')
    allowed = {'mode', 'statistics', 'heterojunction', 'srh', 'avalanche', 'high_field_mobility', 'nodes_per_layer',
               'max_bias_step_V', 'material_models', 'breakdown_fields'}
    if set(cfg) - allowed:
        raise ValueError('Unsupported transport settings: ' + ', '.join(sorted(set(cfg)-allowed)))
    mode = cfg.get('mode', 'disabled')
    if mode not in MODES:
        raise ValueError('Transport mode must be ' + ', '.join(MODES))
    result = {'mode': mode}
    result['statistics'] = cfg.get('statistics', 'boltzmann')
    if result['statistics'] not in ('boltzmann', 'fermi_dirac'):
        raise ValueError('statistics must be boltzmann or fermi_dirac')
    result['heterojunction'] = None
    if cfg.get('heterojunction') is not None:
        interface = cfg['heterojunction']
        if not isinstance(interface, dict) or set(interface)-{'model','parameter_source'}:
            raise ValueError('heterojunction needs model and parameter_source')
        if interface.get('model') != 'ideal_quasi_fermi':
            raise ValueError('The supported heterojunction model is ideal_quasi_fermi; finite thermionic interface resistance and tunneling are not modeled')
        group = _group({key:value for key,value in interface.items() if key!='model'}, (), 'heterojunction')
        result['heterojunction'] = dict(model='ideal_quasi_fermi', **group)
        if result['statistics'] != 'fermi_dirac':
            raise ValueError('ideal_quasi_fermi heterojunction transport requires fermi_dirac statistics')
    # Keep unselected settings so changing the UI mode does not discard a fit.
    if 'nodes_per_layer' in cfg:
        count = _number(cfg['nodes_per_layer'], 'nodes_per_layer', positive=True)
        if count != int(count) or count < 4:
            raise ValueError('nodes_per_layer must be an integer of at least 4')
        result['nodes_per_layer'] = int(count)
    result['max_bias_step_V'] = _number(cfg.get('max_bias_step_V', .1),
                                      'max_bias_step_V', positive=True)
    result['srh'] = None
    if cfg.get('srh') is not None:
        source = dict(cfg['srh']) if isinstance(cfg['srh'], dict) else cfg['srh']
        if not isinstance(source, dict) or 'trap_energy_eV' not in source:
            raise ValueError('srh requires trap_energy_eV measured relative to the intrinsic level')
        trap = _number(source.pop('trap_energy_eV'), 'srh.trap_energy_eV')
        result['srh'] = _group(source, ('tau_n_s', 'tau_p_s'), 'srh')
        result['srh']['trap_energy_eV'] = trap
        if mode == 'semiconductor_dd' and result['statistics'] == 'fermi_dirac':
            raise ValueError('The Boltzmann SRH np-ni^2 law is invalid for degenerate Fermi-Dirac equilibrium; omit SRH until a sourced FD trap-capture law is available')
    result['high_field_mobility'] = None
    if cfg.get('high_field_mobility') is not None:
        result['high_field_mobility'] = _group(cfg['high_field_mobility'],
            ('electron_saturation_velocity_cm_s', 'hole_saturation_velocity_cm_s',
             'electron_exponent', 'hole_exponent'), 'high_field_mobility')
        if min(result['high_field_mobility'][c+'_exponent'] for c in ('electron','hole')) < 1:
            raise ValueError('Velocity saturation exponents must be at least 1')
    result['avalanche'] = None
    if cfg.get('avalanche') is not None:
        result['avalanche'] = _group(cfg['avalanche'],
            ('electron_A_cm1', 'electron_B_V_cm', 'electron_exponent',
             'hole_A_cm1', 'hole_B_V_cm', 'hole_exponent', 'temperature_K'),
            'avalanche', optional=('maximum_field_V_cm',))
        if result['high_field_mobility'] is None:
            raise ValueError('Avalanche transport requires sourced high_field_mobility parameters')
    models = cfg.get('material_models', {})
    if not isinstance(models, dict):
        raise ValueError('material_models must map material IDs to leakage models')
    result['material_models'] = {}
    for material_id, model in models.items():
        if not isinstance(material_id, str) or not isinstance(model, dict):
            raise ValueError('Each dielectric material model needs a material ID and an object')
        if set(model) - {'mechanism', 'parameters'}:
            raise ValueError(material_id + ': unsupported dielectric model setting')
        mechanism = model.get('mechanism')
        fields = {
            'ohmic': ('conductivity_S_m',),
            'poole_frenkel': ('conductivity_prefactor_S_m', 'trap_depth_eV', 'optical_epsilon_r'),
            'schottky': ('richardson_A_m2_K2', 'barrier_eV', 'optical_epsilon_r'),
            'fowler_nordheim': ('barrier_eV', 'tunnel_mass_ratio'),
            'direct_tunneling': ('barrier_eV', 'tunnel_mass_ratio'),
        }
        if mechanism not in fields:
            raise ValueError('Dielectric leakage mechanism must be ' + ', '.join(DIELECTRIC_MECHANISMS))
        parameters = _group(model.get('parameters'), fields[mechanism], material_id,
                            nonnegative=('conductivity_S_m',))
        result['material_models'][material_id] = dict(mechanism=mechanism, parameters=parameters)
    if mode == 'dielectric_leakage' and not result['material_models']:
        raise ValueError('Dielectric leakage requires explicit material_models and sourced parameters')
    fields = cfg.get('breakdown_fields', {})
    if not isinstance(fields, dict):
        raise ValueError('breakdown_fields must map material IDs to sourced field criteria')
    result['breakdown_fields'] = {str(mid): _group(group, ('critical_field_V_m',), 'breakdown_fields.'+str(mid))
                                  for mid, group in fields.items()}
    return result


def validate_planar_device(options, cfg=None):
    """Reject geometries whose lateral physics cannot be represented in 1D."""
    from device_model import layer_bounds, shape_mask, validate_device
    from electrical_material_library import builtin_materials, evaluate_material, validate_materials
    cfg = validate_transport(cfg if cfg is not None else options.get('transport'))
    library = validate_materials(options.get('material_library', builtin_materials()))
    device = validate_device(options.get('device'), library, require_contacts=True)
    layers = layer_bounds(device)
    layer_ids = {layer['id'] for layer in layers}
    for group in ('shapes', 'doping_regions', 'pc_arrays'):
        if any(obj.get('enabled', True) and obj.get('layer_id') in layer_ids for obj in device.get(group, [])):
            raise ValueError('Planar transport cannot represent lateral '+group+'; use a validated multidimensional transport solver')
    contacts = [obj for obj in device['contacts'] if obj['enabled'] and obj['layer_id'] in layer_ids]
    if len(contacts) != 2:
        raise ValueError('Planar transport requires exactly two full-face top/bottom contacts')
    top = [obj for obj in contacts if obj['surface']=='top' and obj['layer_id']==layers[0]['id']]
    bottom = [obj for obj in contacts if obj['surface']=='bottom' and obj['layer_id']==layers[-1]['id']]
    if len(top) != 1 or len(bottom) != 1:
        raise ValueError('Planar transport requires contacts on the outermost top and bottom faces')
    corners_x = np.array([-1., -1., 1., 1.])*device['width_um']/2
    corners_y = np.array([-1., 1., -1., 1.])*device['depth_um']/2
    for contact in contacts:
        if contact['shape'] != 'rectangle' or not np.all(shape_mask(contact, corners_x, corners_y)):
            raise ValueError('Planar transport requires rectangular contacts covering the entire device face; partial contacts are not projected to 1D')
    evaluated = {row['id']: evaluate_material(row, temperature_K=device['temperature_K']) for row in library}
    active = [evaluated[layer['material_id']] for layer in layers]
    if cfg['mode'] == 'semiconductor_dd':
        if cfg['statistics'] != 'boltzmann':
            raise ValueError('Fermi-Dirac transport uses the full conservative device graph, including uniform planar devices')
        if any(contact['boundary'] != 'ohmic' for contact in contacts):
            raise ValueError('Semiconductor drift diffusion currently requires two ideal ohmic carrier contacts')
        if len({layer['material_id'] for layer in layers}) != 1 or any(row['kind']!='semiconductor' for row in active):
            raise ValueError('Semiconductor drift diffusion supports one homogeneous Si/GaAs material with layer doping; heterojunctions, insulators and conductors require additional transport boundary models')
        props = active[0]['properties']
        for name in ('intrinsic_cm3','Nc_cm3','Nv_cm3','electron_mobility_cm2_Vs','hole_mobility_cm2_Vs'):
            _number(props.get(name), name, positive=True)
        _check_boltzmann_band_consistency(props,device['temperature_K'])
        for layer in layers:
            doping = layer['donor_cm3']-layer['acceptor_cm3'] + props.get('bulk_electron_cm3',0.)-props.get('bulk_hole_cm3',0.)
            n0, p0 = neutral_carriers(doping, props['intrinsic_cm3'])
            if n0/props['Nc_cm3'] > .1 or p0/props['Nv_cm3'] > .1:
                raise ModelValidityError('Boltzmann drift diffusion requires nondegenerate doping: equilibrium n/Nc and p/Nv must not exceed 0.1; use Fermi-Dirac transport for this layer')
        if cfg['srh'] is not None:
            vt = k*device['temperature_K']/e
            # E_i differs from the band midgap when the DOS values differ.
            intrinsic_above_valence = props['bandgap_eV']/2 + vt/2*math.log(props['Nv_cm3']/props['Nc_cm3'])
            trap_above_valence = intrinsic_above_valence + cfg['srh']['trap_energy_eV']
            if not 0 < trap_above_valence < props['bandgap_eV']:
                raise ModelValidityError('The specified SRH trap is outside the semiconductor band gap')
        if cfg['avalanche'] and not math.isclose(device['temperature_K'], cfg['avalanche']['temperature_K'], rel_tol=1e-6):
            raise ModelValidityError('Avalanche coefficients apply only at their supplied temperature_K; no undocumented temperature scaling is applied')
    elif cfg['mode'] == 'dielectric_leakage':
        if any(row['kind']!='dielectric' for row in active):
            raise ValueError('Dielectric leakage requires a stack containing dielectric layers only, with electrodes represented by boundary contacts')
        for layer in layers:
            if layer['donor_cm3'] or layer['acceptor_cm3']:
                raise ValueError('Dielectric leakage does not support doped space-charge layers')
            if layer['material_id'] not in cfg['material_models']:
                raise ValueError('Missing leakage model for '+layer['material_id'])
        if len(layers) > 1 and any(cfg['material_models'][layer['material_id']]['mechanism'] not in ('ohmic','poole_frenkel') for layer in layers):
            raise ValueError('Multilayer steady leakage supports bulk Ohmic/Poole-Frenkel series transport only; electrode emission and tunneling require a single uniform barrier')
    swept = str(options.get('swept_contact_id') or contacts[-1]['id'])
    if swept not in {contact['id'] for contact in contacts}:
        raise ValueError('Swept contact must identify one of the planar device electrodes')
    return dict(device=device, material_library=library, evaluated_materials=evaluated,
                layers=layers, top=top[0], bottom=bottom[0], contacts=contacts,
                swept_contact_id=swept, area_m2=device['width_um']*device['depth_um']*1e-12,
                transport=cfg)


def neutral_carriers(net_doping_cm3, intrinsic_cm3):
    """Charge neutrality and mass action, without subtractive cancellation."""
    doping = np.asarray(net_doping_cm3, dtype=float)
    ni = _number(intrinsic_cm3, 'intrinsic_cm3', positive=True)
    majority = .5*np.abs(doping) + np.hypot(.5*doping, ni)
    minority = ni*(ni/majority)
    return np.where(doping>=0, majority, minority), np.where(doping>=0, minority, majority)


def srh_rate(n_cm3, p_cm3, intrinsic_cm3, temperature_K, parameters):
    """Net SRH recombination cm^-3 s^-1 (negative means generation)."""
    n, p = np.broadcast_arrays(np.asarray(n_cm3,float), np.asarray(p_cm3,float))
    ni = _number(intrinsic_cm3, 'intrinsic_cm3', positive=True)
    vt = k*_number(temperature_K, 'temperature_K', positive=True)/e
    n1 = ni*np.exp(parameters['trap_energy_eV']/vt)
    p1 = ni*np.exp(-parameters['trap_energy_eV']/vt)
    return (n*p-ni**2)/(parameters['tau_p_s']*(n+n1)+parameters['tau_n_s']*(p+p1))


def ionization_coefficient(field_V_m, prefactor_cm1, critical_V_cm, exponent):
    """Generalized Chynoweth alpha=A exp[-(B/|E|)^b], result m^-1."""
    field = np.abs(np.asarray(field_V_m,float)) / 100.
    a = _number(prefactor_cm1, 'ionization A', positive=True)*100.
    b = _number(critical_V_cm, 'ionization B', positive=True)
    power = _number(exponent, 'ionization exponent', positive=True)
    with np.errstate(divide='ignore', over='ignore', under='ignore'):
        return np.where(field>0, a*np.exp(-np.power(b/field,power)), 0.)


def avalanche_integral(z_m, alpha_n_m1, alpha_p_m1):
    """Local electron-injection multiplication criterion for a one-way field.

    z runs in the electron drift direction. The McIntyre/local condition is
    integral(alpha_n * exp(-integral(alpha_n-alpha_p) dz) dz) = 1.
    Only evaluates a supplied field profile; it does not replace coupled DD or
    calculate irreversible damage. Constant equal alpha gives alpha*length.
    """
    z, an, ap = [np.asarray(value,float) for value in (z_m,alpha_n_m1,alpha_p_m1)]
    if z.ndim != 1 or len(z)<2 or an.shape!=z.shape or ap.shape!=z.shape or np.any(np.diff(z)<=0):
        raise ValueError('Avalanche integral needs matching, increasing 1D coordinates and coefficient arrays')
    if not all(np.isfinite(v).all() for v in (z,an,ap)) or np.any(an<0) or np.any(ap<0):
        raise ValueError('Avalanche coordinates and nonnegative coefficients must be finite')
    exponent = -cumulative_trapezoid(an-ap,z,initial=0.)
    if float(np.max(exponent)) > 700:
        return math.inf
    return float(trapezoid(an*np.exp(exponent),z))


def barrier_lowering_eV(field_V_m, optical_epsilon_r, *, poole_frenkel=False):
    """Image-force lowering; PF is twice the Schottky energy lowering."""
    permittivity = epsilon_0*_number(optical_epsilon_r, 'optical_epsilon_r', positive=True)
    return np.sqrt(e*np.abs(np.asarray(field_V_m,float))/(math.pi*permittivity*(1. if poole_frenkel else 4.)))


def poole_frenkel_current_density(field_V_m, temperature_K, parameters):
    """Bulk trap emission law, A/m^2; optical epsilon is explicitly supplied."""
    field = np.asarray(field_V_m,float)
    lower = barrier_lowering_eV(field, parameters['optical_epsilon_r'], poole_frenkel=True)
    if np.any(lower >= parameters['trap_depth_eV']):
        raise ModelValidityError('Poole-Frenkel barrier is suppressed; the activated trap-emission model is outside its validity range')
    vt = k*_number(temperature_K,'temperature_K',positive=True)/e
    return parameters['conductivity_prefactor_S_m']*field*np.exp(-(parameters['trap_depth_eV']-lower)/vt)


def schottky_emission_density(field_V_m, temperature_K, parameters):
    """One-way injecting-electrode emission A/m^2, not zero-bias net current."""
    lower = barrier_lowering_eV(field_V_m, parameters['optical_epsilon_r'])
    if np.any(lower >= parameters['barrier_eV']):
        raise ModelValidityError('Schottky barrier is suppressed; thermionic emission is outside its validity range')
    temperature = _number(temperature_K,'temperature_K',positive=True)
    return parameters['richardson_A_m2_K2']*temperature**2*np.exp(-(parameters['barrier_eV']-lower)/(k*temperature/e))


def fowler_nordheim_current_density(field_V_m, parameters):
    """Zero-temperature triangular barrier WKB, A/m^2 (no image correction)."""
    field = np.asarray(field_V_m,float)
    barrier = parameters['barrier_eV']*e
    mass = parameters['tunnel_mass_ratio']*m_e
    prefactor = e**3/(8*math.pi*h*barrier)
    slope = 8*math.pi*math.sqrt(2*mass)*barrier**1.5/(3*e*h)
    with np.errstate(divide='ignore', under='ignore'):
        return np.sign(field)*prefactor*field**2*np.exp(-slope/np.abs(field))


def direct_tunnel_current_density(voltage_V, thickness_m, parameters):
    """Simmons symmetric rectangular barrier approximation, no image forces.

    Low/intermediate voltage |V| < phi/e; beta=1 mean-barrier approximation.
    The WKB action must exceed 4. These restrictions prevent negative currents
    from using the asymptotic expression on an almost transparent barrier.
    """
    voltage = np.asarray(voltage_V,float)
    d = _number(thickness_m,'thickness_m',positive=True)
    phi = parameters['barrier_eV']*e
    if np.any(np.abs(voltage) >= parameters['barrier_eV']):
        raise ModelValidityError('Direct tunneling requires |V| below the barrier height in eV; the barrier becomes triangular at larger voltage')
    lower = phi-e*np.abs(voltage)/2
    upper = phi+e*np.abs(voltage)/2
    action = 2*d*math.sqrt(2*m_e*parameters['tunnel_mass_ratio'])/hbar
    if np.any(action*np.sqrt(lower) < 4):
        raise ModelValidityError('Simmons approximation requires an opaque barrier (WKB action >= 4)')
    log_difference = np.log1p(e*np.abs(voltage)/lower)-action*(np.sqrt(upper)-np.sqrt(lower))
    difference = lower*np.exp(-action*np.sqrt(lower))*(-np.expm1(log_difference))
    return np.sign(voltage)*e/(2*math.pi*h*d**2)*difference


def field_breakdown_screen(field_by_material, breakdown_fields):
    """Compare fields with sourced criteria, preserving unknown materials."""
    result = []
    for mid, field in field_by_material.items():
        maximum = float(np.max(np.abs(field)))
        if not math.isfinite(maximum):
            raise ValueError('Breakdown screening fields must be finite')
        record = dict(material_id=mid, maximum_field_V_m=maximum, status='no_criterion')
        if mid in breakdown_fields:
            criteria = breakdown_fields[mid]
            critical = _number(criteria['critical_field_V_m'],'critical_field_V_m',positive=True)
            record.update(critical_field_V_m=critical, field_ratio=maximum/critical,
                          parameter_source=criteria['parameter_source'],
                          status='criterion_reached' if maximum>=critical else 'below_criterion')
        result.append(record)
    return dict(model='Field threshold screening; no damage or post-breakdown conduction model', materials=result,
                criterion_reached=any(row['status']=='criterion_reached' for row in result))


def _terminal_voltages(geometry, bias):
    # Match editable-device semantics: bias is an increment on swept contact.
    return {c['id']: c['voltage_V'] + (float(bias) if c['id']==geometry['swept_contact_id'] else 0.)
            for c in geometry['contacts']}


def _bulk_stack_fields(voltage, thickness, models, temperature):
    """Enforce a common current and sum(E_i*d_i)=V across bulk layers."""
    if voltage == 0:
        return 0., np.zeros(len(thickness))
    sign = math.copysign(1.,voltage)
    maximum = abs(voltage)/np.asarray(thickness)
    def current(field, model):
        params = model['parameters']
        if model['mechanism']=='ohmic':
            return params['conductivity_S_m']*field
        return float(poole_frenkel_current_density(field,temperature,params))
    for model in models:
        if model['mechanism']=='ohmic' and model['parameters']['conductivity_S_m']==0:
            raise ModelValidityError('Steady current is zero through a perfect insulating layer, but DC voltage partition is not unique without stored interface charge; use electrostatic fields')
    # A PF barrier can limit its invertible field below the entire applied bias.
    for index, model in enumerate(models):
        if model['mechanism']=='poole_frenkel':
            p = model['parameters']
            limit = p['trap_depth_eV']**2*math.pi*epsilon_0*p['optical_epsilon_r']/e
            maximum[index] = min(maximum[index],limit*(1-1e-12))
    ceiling = min(current(f,model) for f,model in zip(maximum,models))
    if ceiling <= 0:
        raise ModelValidityError('Leakage current underflows floating-point range; no resolved terminal current')
    def fields_for(j):
        if j==0:
            return np.zeros(len(models))
        fields = []
        for limit, model in zip(maximum,models):
            if model['mechanism']=='ohmic':
                fields.append(j/model['parameters']['conductivity_S_m'])
            else:
                # Solve in a normalized field variable; absolute units should
                # never establish an artificial current or field tolerance.
                fields.append(limit*brentq(lambda f: current(f*limit,model)/j-1,0.,1.,xtol=1e-14))
        return np.array(fields)
    def voltage_ratio(fraction):
        return float(np.dot(fields_for(fraction*ceiling),thickness))/abs(voltage)-1
    if voltage_ratio(1.) < -1e-10:
        raise ModelValidityError('A dielectric trap barrier is suppressed before this stack bias can be supported')
    fraction = brentq(voltage_ratio,0.,1.,xtol=1e-14)
    fields = fields_for(fraction*ceiling)
    return sign*fraction*ceiling, sign*fields


def dielectric_leakage_iv(summary, cfg, cancelled=lambda:False):
    """Return terminal I-V rows and provenance for a planar dielectric stack.

    Bulk multilayers use a steady-current partition, allowing interface charge;
    this field can differ from the initial electrostatic capacitive division.
    Single-barrier Schottky is an injection-limited high-bias approximation and
    requires |V| >= 5 kT/q. FN requires a triangular barrier (|V| >= phi/e).
    Invalid points have current_A=None and an explicit status, never zero.
    """
    cfg = validate_transport(cfg)
    if cfg['mode'] != 'dielectric_leakage':
        raise ValueError('dielectric_leakage_iv requires dielectric_leakage mode')
    geometry = validate_planar_device(summary['options'],cfg)
    layers = geometry['layers']
    thickness = np.array([row['thickness_um']*1e-6 for row in layers])
    models = [cfg['material_models'][row['material_id']] for row in layers]
    temperature = geometry['device']['temperature_K']
    rows, checks = [], []
    biases = [row['bias_V'] for row in summary.get('results',[])] or summary['options']['biases_V']
    for bias in biases:
        if cancelled():
            raise InterruptedError('Dielectric leakage study cancelled')
        voltages = _terminal_voltages(geometry,bias)
        voltage = voltages[geometry['top']['id']]-voltages[geometry['bottom']['id']]
        row = dict(bias_V=float(bias),terminal_voltage_V=voltages[geometry['swept_contact_id']],
                   voltage_difference_V=voltage,current_A=None,status='valid')
        check = dict(bias_V=float(bias))
        try:
            if all(model['mechanism'] in ('ohmic','poole_frenkel') for model in models):
                if len(models)==1 and models[0]['mechanism']=='ohmic' and models[0]['parameters']['conductivity_S_m']==0:
                    j, fields = 0., np.array([voltage/thickness[0]])
                else:
                    j, fields = _bulk_stack_fields(voltage,thickness,models,temperature)
            else:
                fields = np.array([voltage/thickness[0]])
                mechanism, p = models[0]['mechanism'], models[0]['parameters']
                if voltage==0:
                    j=0.
                elif mechanism=='schottky':
                    if abs(voltage)<5*k*temperature/e:
                        raise ModelValidityError('Schottky injection-limited approximation requires |V| >= 5 kT/q; low-bias back injection is not modeled')
                    j=math.copysign(float(schottky_emission_density(fields[0],temperature,p)),voltage)
                elif mechanism=='fowler_nordheim':
                    if abs(voltage)<p['barrier_eV']:
                        raise ModelValidityError('Fowler-Nordheim triangular-barrier approximation requires |V| >= barrier_eV')
                    j=float(fowler_nordheim_current_density(fields[0],p))
                else:
                    j=float(direct_tunnel_current_density(voltage,thickness[0],p))
            by_material = {}
            for layer, field in zip(layers,fields):
                by_material.setdefault(layer['material_id'],[]).append(float(field))
            screen = field_breakdown_screen(by_material,cfg['breakdown_fields'])
            check.update(layer_field_V_m={layer['id']:float(field) for layer,field in zip(layers,fields)},
                         voltage_balance_V=float(np.dot(fields,thickness)-voltage),
                         breakdown=screen)
            if screen['criterion_reached']:
                raise ModelValidityError('Supplied breakdown field criterion reached; pre-damage leakage is not extrapolated into a damaged state')
            current = j*geometry['area_m2']
            row['current_A'] = current if geometry['swept_contact_id']==geometry['top']['id'] else -current
            row['current_density_A_m2'] = j
            check.update(terminal_current_A={geometry['top']['id']:current,geometry['bottom']['id']:-current},
                         current_balance_A=0., power_W=current*voltage)
        except ModelValidityError as exc:
            row.update(status='outside_model_validity',reason=str(exc),current_density_A_m2=None)
        if row['current_A'] is not None and not math.isfinite(row['current_A']):
            raise RuntimeError('Dielectric current is not finite')
        rows.append(row)
        checks.append(check)
    return rows,dict(model='Planar dielectric leakage; sourced pre-damage constitutive models',
        transport=cfg,checks=checks,references=REFERENCES,
        warnings=['Steady-current field partition permits interfacial free charge and can differ from the electrostatic capacitive partition.',
                  'Mechanisms are alternatives, not automatically summed. Barrier parameters refer to the injecting electrode; symmetric electrodes are assumed for single-barrier polarity reversal.',
                  'Field threshold screening does not model time-to-breakdown, Weibull distributions, thermal runaway, filaments or post-damage conduction.',
                  'Invalid model-domain points have no predicted current. Parameters must be calibrated for the actual fabrication process; these laws do not reproduce a paper by themselves.'])


def _native_models(ds, device, region, geometry, coordinates_cm):
    """Construct coupled finite-volume equations; DEVSIM owns the Jacobian."""
    layers = geometry['layers']
    cfg = geometry['transport']
    material = geometry['evaluated_materials'][layers[0]['material_id']]
    props = material['properties']
    temperature = geometry['device']['temperature_K']
    vt = k*temperature/e
    ni = props['intrinsic_cm3']
    x = np.asarray(coordinates_cm,float)
    faces = np.r_[x[0],(x[:-1]+x[1:])/2,x[-1]]
    donor = np.zeros(len(x)); acceptor = np.zeros(len(x))
    for layer in layers:
        overlap = np.maximum(0.,np.minimum(faces[1:],layer['z_max_um']*1e-4)-np.maximum(faces[:-1],layer['z_min_um']*1e-4))
        fraction = overlap/np.diff(faces)
        donor += fraction*layer['donor_cm3']
        acceptor += fraction*layer['acceptor_cm3']
    donor += props.get('bulk_electron_cm3',0.)
    acceptor += props.get('bulk_hole_cm3',0.)
    doping = donor-acceptor
    n0,p0 = neutral_carriers(doping,ni)
    def solution(name,values):
        ds.node_solution(device=device,region=region,name=name)
        ds.set_node_values(device=device,region=region,name=name,values=np.asarray(values,float).tolist())
        ds.edge_from_node_model(device=device,region=region,node_model=name)
    def nm(name,equation,variables=()):
        ds.node_model(device=device,region=region,name=name,equation=equation)
        for variable in variables:
            ds.node_model(device=device,region=region,name=name+':'+variable,equation=f'simplify(diff({equation}, {variable}))')
    def em(name,equation,variables=()):
        ds.edge_model(device=device,region=region,name=name,equation=equation)
        for variable in variables:
            for node in ('n0','n1'):
                ds.edge_model(device=device,region=region,name=f'{name}:{variable}@{node}',
                              equation=f'simplify(diff({equation}, {variable}@{node}))')
    for name,value in dict(ElectronCharge=e,Permittivity=props['epsilon_r']*epsilon_0/100.,
                           V_t=vt,n_i=ni,mu_n=props['electron_mobility_cm2_Vs'],
                           mu_p=props['hole_mobility_cm2_Vs'],AvalancheScale=0.).items():
        ds.set_parameter(device=device,region=region,name=name,value=value)
    solution('NetDoping',doping)
    solution('Potential',vt*np.log(n0/ni))
    nm('EqElectrons','n_i*exp(Potential/V_t)',('Potential',))
    nm('EqHoles','n_i*exp(-Potential/V_t)',('Potential',))
    nm('EqCharge','-ElectronCharge*kahan3(EqHoles,-EqElectrons,NetDoping)',('Potential',))
    em('ElectricField','(Potential@n0-Potential@n1)*EdgeInverseLength',('Potential',))
    em('Displacement','Permittivity*ElectricField',('Potential',))
    ds.equation(device=device,region=region,name='Poisson',variable_name='Potential',
                node_model='EqCharge',edge_model='Displacement',variable_update='log_damp')
    for contact,index in (('top',0),('bottom',-1)):
        ds.set_parameter(device=device,name=contact+'_bias',value=0.)
        bc = f'Potential-({vt*math.log(float(n0[index])/ni):.17e})-{contact}_bias'
        ds.contact_node_model(device=device,contact=contact,name=contact+'_potential',equation=bc)
        ds.contact_node_model(device=device,contact=contact,name=contact+'_potential:Potential',equation='1')
        ds.contact_equation(device=device,contact=contact,name='Poisson',node_model=contact+'_potential',edge_charge_model='Displacement')
    return dict(donor=donor,acceptor=acceptor,n0=n0,p0=p0,nm=nm,em=em,solution=solution,
                temperature=temperature,vt=vt,ni=ni,props=props,faces_cm=faces)


def _native_continuity(ds,device,region,geometry,model):
    cfg = geometry['transport']; nm,em,solution = (model[name] for name in ('nm','em','solution'))
    variables = ('Potential','Electrons','Holes')
    for name,equilibrium in (('Electrons','EqElectrons'),('Holes','EqHoles')):
        solution(name,ds.get_node_model_values(device=device,region=region,name=equilibrium))
    nm('Charge','-ElectronCharge*kahan3(Holes,-Electrons,NetDoping)',variables)
    ds.equation(device=device,region=region,name='Poisson',variable_name='Potential',
                node_model='Charge',edge_model='Displacement',variable_update='log_damp')
    em('vdiff','(Potential@n0-Potential@n1)/V_t',('Potential',))
    em('Bern01','B(vdiff)',('Potential',))
    for carrier,base in (('electron','mu_n'),('hole','mu_p')):
        if cfg['high_field_mobility']:
            hp=cfg['high_field_mobility']; speed=hp[carrier+'_saturation_velocity_cm_s']; power=hp[carrier+'_exponent']
            # sqrt(E^2 + tiny^2) only regularizes the derivative at E=0,
            # far below any representable physical drift-field accuracy.
            mobility=f'{base}/(1+({base}*(ElectricField^2+1e-40)^0.5/({speed:.17e}))^({power:.17e}))^(1/({power:.17e}))'
        else:
            mobility=base
        em(carrier+'_mobility',mobility,('Potential',))
    # The Bernoulli identity B(-x)=B(x)+x avoids catastrophic overflow. kahan3
    # reduces cancellation when drift balances diffusion at equilibrium.
    em('ElectronCurrent','ElectronCharge*electron_mobility*EdgeInverseLength*V_t*kahan3(Electrons@n1*Bern01,Electrons@n1*vdiff,-Electrons@n0*Bern01)',variables)
    em('HoleCurrent','-ElectronCharge*hole_mobility*EdgeInverseLength*V_t*kahan3(Holes@n1*Bern01,-Holes@n0*Bern01,-Holes@n0*vdiff)',variables)
    if cfg['srh']:
        srh=cfg['srh']; ni=model['ni']; vt=model['vt']
        n1=ni*math.exp(srh['trap_energy_eV']/vt);p1=ni*math.exp(-srh['trap_energy_eV']/vt)
        expression=f'(Electrons*Holes-n_i^2)/(({srh["tau_p_s"]:.17e})*(Electrons+({n1:.17e}))+({srh["tau_n_s"]:.17e})*(Holes+({p1:.17e})))'
    else:
        expression='0'
    nm('SRH',expression,variables)
    nm('ElectronSource','-ElectronCharge*SRH',variables)
    nm('HoleSource','ElectronCharge*SRH',variables)
    if cfg['avalanche']:
        params=cfg['avalanche']
        for carrier in ('electron','hole'):
            a,b,power=(params[carrier+suffix] for suffix in ('_A_cm1','_B_V_cm','_exponent'))
            # max only excludes a mathematically singular E=0 evaluation;
            # alpha is exponentially zero at this negligible numerical field.
            expression=f'({a:.17e})*exp(-(({b:.17e})/max(abs(ElectricField),1e-30))^({power:.17e}))'
            em('alpha_'+carrier,expression,('Potential',))
        em('ImpactRate','AvalancheScale*(alpha_electron*abs(ElectronCurrent)+alpha_hole*abs(HoleCurrent))/ElectronCharge',variables)
        em('ElectronImpact','ElectronCharge*ImpactRate',variables)
        em('HoleImpact','-ElectronCharge*ImpactRate',variables)
    else:
        em('ImpactRate','0',variables)
    for name,carrier,source,impact in (('ElectronContinuity','Electrons','ElectronSource','ElectronImpact'),
                                     ('HoleContinuity','Holes','HoleSource','HoleImpact')):
        args=dict(device=device,region=region,name=name,variable_name=carrier,node_model=source,
                  edge_model='ElectronCurrent' if carrier=='Electrons' else 'HoleCurrent',variable_update='positive')
        if cfg['avalanche']:
            args['edge_volume_model']=impact
        ds.equation(**args)
        for contact,index in (('top',0),('bottom',-1)):
            density=model['n0' if carrier=='Electrons' else 'p0'][index]
            bc=contact+'_'+carrier
            # Always emit a floating-point token: DEVSIM's integer parser
            # saturates long decimal integer literals at signed 32-bit range.
            ds.contact_node_model(device=device,contact=contact,name=bc,equation=f'{carrier}-({density:.17e})')
            ds.contact_node_model(device=device,contact=contact,name=bc+':'+carrier,equation='1')
            ds.contact_equation(device=device,contact=contact,name=name,node_model=bc,edge_current_model=args['edge_model'])


def iter_semiconductor_states(options, transport_cfg=None, emit=lambda event:None, cancelled=lambda:False):
    """Yield native planar Poisson/continuity states, retaining every bias.

    Arrays use native nodes, not cells; edge current arrays have N-1 entries.
    Ideal ohmic contacts fix neutral n/p and electrostatic potential + applied
    voltage. Bias continuation solves intermediate points only when required;
    it never replaces requested samples. All native devices are cleaned up even
    when the generator is closed, cancelled or fails its conservation checks.
    """
    import contextlib
    import io
    from electrical_solver import _load_core
    geometry=validate_planar_device(options,transport_cfg)
    cfg=geometry['transport']
    if cfg['mode']!='semiconductor_dd':
        raise ValueError('iter_semiconductor_states requires semiconductor_dd mode')
    biases=[_number(value,'bias_V') for value in options.get('biases_V',[0.])]
    if not biases:
        raise ValueError('Transport needs at least one requested bias')
    count=cfg.get('nodes_per_layer',max(4,geometry['device']['mesh']['nz_per_layer']))
    if count*len(geometry['layers'])>500000:
        raise ValueError('Native planar transport mesh exceeds 500000 intervals; reduce nodes_per_layer or the number of layers')
    requested=np.r_[0.,np.concatenate([np.linspace(layer['z_min_um'],layer['z_max_um'],count+1)[1:] for layer in geometry['layers']])]*1e-4
    if cancelled():
        raise InterruptedError('Semiconductor transport cancelled')
    with _NATIVE_LOCK:
        ds=_load_core().ds
        name='transport_'+uuid.uuid4().hex
        region='semiconductor'
        # Leakage is the difference of much larger drift/diffusion terms.
        # Evaluate and assemble in the same extended precision as the 3D
        # backend, preserving the caller's process-wide DEVSIM settings.
        precision={}
        for key in ('extended_model','extended_equation','extended_solver'):
            try:precision[key]=ds.get_parameter(name=key)
            except ds.error:precision[key]=False
        for key in precision:ds.set_parameter(name=key,value=True)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ds.create_1d_mesh(mesh=name)
                spacings=np.diff(requested)
                for index,pos in enumerate(requested):
                    spacing=spacings[min(index,len(spacings)-1)]
                    if index:spacing=min(spacing,spacings[index-1])
                    args=dict(mesh=name,pos=float(pos),ps=float(spacing))
                    if index in (0,len(requested)-1):args['tag']='top' if index==0 else 'bottom'
                    ds.add_1d_mesh_line(**args)
                for contact in ('top','bottom'):
                    ds.add_1d_contact(mesh=name,name=contact,tag=contact,material='ideal_ohmic')
                ds.add_1d_region(mesh=name,material=geometry['layers'][0]['material_id'],region=region,tag1='top',tag2='bottom')
                ds.finalize_mesh(mesh=name);ds.create_device(mesh=name,device=name)
                x=np.asarray(ds.get_node_model_values(device=name,region=region,name='x'),float)
                model=_native_models(ds,name,region,geometry,x)
            solve_count=0
            def native_solve():
                nonlocal solve_count
                if cancelled():
                    raise InterruptedError('Semiconductor transport cancelled')
                log=io.StringIO()
                with contextlib.redirect_stdout(log):
                    try:
                        # DEVSIM requires both update tolerances. An absolute
                        # carrier update below 1 cm^-3 is below double precision
                        # at ordinary doping, while potential near zero makes
                        # a relative-only criterion ill conditioned. Independent
                        # current/Gauss checks below decide physical acceptance.
                        ds.solve(type='dc',absolute_error=1e4,relative_error=1e-7,maximum_iterations=100)
                    except ds.error as exc:
                        raise RuntimeError('Native Poisson/continuity Newton solve failed: '+str(exc)+'\n'+log.getvalue()[-1800:]) from exc
                solve_count+=1
            native_solve()
            with contextlib.redirect_stdout(io.StringIO()):
                _native_continuity(ds,name,region,geometry,model)
            native_solve()
            if cfg['avalanche']:
                ds.set_parameter(device=name,region=region,name='AvalancheScale',value=1.)
                native_solve()
            current_voltage=np.zeros(2)
            node_names=('Potential','Electrons','Holes')
            for bias_index,bias in enumerate(biases):
                voltages=_terminal_voltages(geometry,bias)
                target=np.array([voltages[geometry['top']['id']],voltages[geometry['bottom']['id']]])
                emit(dict(phase='transport',progress=bias_index/max(1,len(biases)),
                          message=f'Solving planar coupled Poisson and continuity at {bias:g} V'))
                step_limit=cfg['max_bias_step_V']
                while np.max(np.abs(target-current_voltage))>1e-13*max(1.,float(np.max(np.abs(target)))):
                    difference=target-current_voltage
                    fraction=min(1.,step_limit/float(np.max(np.abs(difference))))
                    next_voltage=current_voltage+fraction*difference
                    saved={key:list(ds.get_node_model_values(device=name,region=region,name=key)) for key in node_names}
                    for contact,value in zip(('top','bottom'),next_voltage):
                        ds.set_parameter(device=name,name=contact+'_bias',value=float(value))
                    try:
                        native_solve()
                    except RuntimeError:
                        for key,values in saved.items():
                            ds.set_node_values(device=name,region=region,name=key,values=values)
                        for contact,value in zip(('top','bottom'),current_voltage):
                            ds.set_parameter(device=name,name=contact+'_bias',value=float(value))
                        step_limit*=.5
                        if step_limit<1e-7:
                            raise RuntimeError(f'Coupled transport failed near {current_voltage[0]-current_voltage[1]:g} V before requested {bias:g} V. This is numerical nonconvergence, not evidence of breakdown.') from None
                        continue
                    current_voltage=next_voltage
                    step_limit=min(cfg['max_bias_step_V'],step_limit*1.5)
                nodes={key:np.asarray(ds.get_node_model_values(device=name,region=region,name=key),float) for key in node_names}
                edges={key:np.asarray(ds.get_edge_model_values(device=name,region=region,name=key),float) for key in ('ElectricField','ElectronCurrent','HoleCurrent','ImpactRate')}
                if not all(np.isfinite(value).all() for value in [*nodes.values(),*edges.values()]):
                    raise RuntimeError('Native transport state contains nonfinite values')
                if np.any(nodes['Electrons']<=0) or np.any(nodes['Holes']<=0):
                    raise RuntimeError('Native transport state contains nonpositive carrier density')
                props=model['props']
                if float(np.max(nodes['Electrons']))>.1*props['Nc_cm3'] or float(np.max(nodes['Holes']))>.1*props['Nv_cm3']:
                    raise ModelValidityError(f'Bias {bias:g} V enters degenerate injection; Boltzmann drift diffusion is outside its validity range')
                area_cm2=geometry['area_m2']*1e4
                currents={}; charges={}
                for native,contact in (('top',geometry['top']),('bottom',geometry['bottom'])):
                    currents[contact['id']]=area_cm2*sum(ds.get_contact_current(device=name,contact=native,equation=equation) for equation in ('ElectronContinuity','HoleContinuity'))
                    charges[contact['id']]=area_cm2*ds.get_contact_charge(device=name,contact=native,equation='Poisson')
                total=edges['ElectronCurrent']+edges['HoleCurrent']
                balance=abs(sum(currents.values()))
                # A roundoff floor is derived from the individual drift/diffusion
                # scale, not an artificial leakage conductivity or current.
                vt=model['vt']; mu=max(props['electron_mobility_cm2_Vs'],props['hole_mobility_cm2_Vs'])
                roundoff_density=128*np.finfo(float).eps*e*mu*vt*max(float(np.max(nodes['Electrons'])),float(np.max(nodes['Holes'])))/float(np.min(np.diff(x)))
                current_scale=max(max(abs(value) for value in currents.values()),roundoff_density*area_cm2)
                edge_spread=float(np.ptp(total))*area_cm2
                if balance>max(1e-5*current_scale,roundoff_density*area_cm2) or edge_spread>max(1e-4*current_scale,4*roundoff_density*area_cm2):
                    raise RuntimeError('Independent terminal/edge current conservation check failed')
                rho=e*(nodes['Holes']-nodes['Electrons']+model['donor']-model['acceptor'])
                charge=float(np.dot(rho,np.diff(model['faces_cm'])))*area_cm2
                gauss=abs(sum(charges.values())+charge)
                charge_scale=max(sum(abs(value) for value in charges.values()),abs(charge),e*model['ni']*(x[-1]-x[0])*area_cm2)
                if gauss>1e-5*charge_scale:
                    raise RuntimeError('Independent transport Gauss balance check failed')
                widths=np.diff(x); volumes=np.diff(model['faces_cm'])
                displacement=props['epsilon_r']*epsilon_0/100.*edges['ElectricField']
                poisson_residual=np.diff(displacement)-rho[1:-1]*volumes[1:-1]
                poisson_scale=max(float(np.max(np.abs(rho)*volumes)),
                    props['epsilon_r']*epsilon_0/100.*model['vt']/float(np.min(widths)))
                poisson_error=float(np.max(np.abs(poisson_residual)))/poisson_scale
                if poisson_error>1e-6:
                    raise RuntimeError('Independent local transport Poisson residual check failed')
                srh=np.asarray(ds.get_node_model_values(device=name,region=region,name='SRH'),float)
                impact_integrated=.5*(edges['ImpactRate'][1:]*widths[1:]+edges['ImpactRate'][:-1]*widths[:-1])
                recombination_charge=e*(srh[1:-1]*volumes[1:-1]-impact_integrated)
                electron_residual=np.diff(edges['ElectronCurrent'])-recombination_charge
                hole_residual=np.diff(edges['HoleCurrent'])+recombination_charge
                continuity_error=max(float(np.max(np.abs(electron_residual))),float(np.max(np.abs(hole_residual))))*area_cm2
                if continuity_error>max(1e-4*current_scale,4*roundoff_density*area_cm2):
                    raise RuntimeError('Independent local electron/hole continuity residual check failed')
                edge_field=edges['ElectricField']*100.
                field=np.interp(x,(x[:-1]+x[1:])/2,edge_field)
                screen=field_breakdown_screen({geometry['layers'][0]['material_id']:edge_field},cfg['breakdown_fields'])
                diagnostics=dict(current_balance_A=balance,relative_current_balance=balance/current_scale,
                    edge_current_spread_A=edge_spread,current_roundoff_floor_A=roundoff_density*area_cm2,
                    integrated_Gauss_error_C=gauss,relative_gauss_balance=gauss/charge_scale,
                    max_normalized_Poisson_residual=poisson_error,max_continuity_residual_A=continuity_error,
                    total_charge_C=charge,native_solve_count=solve_count,
                    terminal_current_A=currents,terminal_charge_C=charges,terminal_voltages_V=voltages,
                    semiconductor_current_predicted=True,breakdown=screen,
                    peak_impact_generation_cm3_s=float(np.max(edges['ImpactRate'])))
                if cfg['avalanche']:
                    params=cfg['avalanche']; peak=float(np.max(np.abs(edge_field)))/100.
                    if 'maximum_field_V_cm' in params and peak>params['maximum_field_V_cm']:
                        raise ModelValidityError('Avalanche field exceeds supplied coefficient maximum_field_V_cm; coefficients were not extrapolated')
                    # Integral is reported only for a unidirectional field.
                    significant=edge_field[np.abs(edge_field)>max(1e-9,float(np.max(np.abs(edge_field)))*1e-6)]
                    if significant.size and (np.all(significant>=0) or np.all(significant<=0)):
                        an=ionization_coefficient(field,params['electron_A_cm1'],params['electron_B_V_cm'],params['electron_exponent'])
                        ap=ionization_coefficient(field,params['hole_A_cm1'],params['hole_B_V_cm'],params['hole_exponent'])
                        # Electrons travel opposite the field.
                        if np.mean(significant)>0:an,ap=an[::-1],ap[::-1]
                        integral=avalanche_integral(x*.01,an,ap)
                        diagnostics['local_ionization_integral']=integral if math.isfinite(integral) else None
                        diagnostics['local_avalanche_criterion_reached']=integral>=1.
                if screen['criterion_reached']:
                    diagnostics['warning']='Supplied field criterion reached; this stationary transport state is not a post-damage model'
                yield dict(bias_V=float(bias),z_m=x*.01,potential_V=nodes['Potential'],
                    electrons_cm3=nodes['Electrons'],holes_cm3=nodes['Holes'],field_V_m=field,
                    edge_field_V_m=edge_field,donor_cm3=model['donor'],acceptor_cm3=model['acceptor'],
                    epsilon_r=np.full(len(x),props['epsilon_r']),charge_density_C_m3=rho*1e6,
                    electron_current_density_A_m2=edges['ElectronCurrent']*1e4,
                    hole_current_density_A_m2=edges['HoleCurrent']*1e4,
                    impact_generation_cm3_s=edges['ImpactRate'],
                    srh_recombination_cm3_s=srh,
                    terminal_voltages_V=voltages,terminal_current_A=currents,terminal_charge_C=charges,checks=diagnostics,
                    method='DEVSIM conservative 1D Poisson + Scharfetter-Gummel electron/hole continuity',
                    limitations=SEMICONDUCTOR_LIMITATIONS,references=REFERENCES)
        finally:
            if name in ds.get_device_list():ds.delete_device(device=name)
            if name in ds.get_mesh_list():ds.delete_mesh(mesh=name)
            for key,value in precision.items():ds.set_parameter(name=key,value=value)

