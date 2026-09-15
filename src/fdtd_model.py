"""Validated, JSON-only bridge from the shared optical structure to Meep.

Coordinates and Meep time units use one micrometre. The 2D calculation is an
XZ cross section extruded along Y; it is not equivalent to a 3D hole array.
"""
from __future__ import annotations

import copy
import math

DEFAULTS = dict(dimensions=2, resolution=30, wavelength_min_nm=1200.,
    wavelength_max_nm=1800., frequency_points=101, polarization='s',
    pml_um=1., padding_um=1., run_after_sources=200., courant=.5,
    section_y_um=0., decay_by=1e-7, fit_materials=True, fit_tolerance=.05,
    save_fields=True, max_cells=30000000)


def validate_options(options):
    result = dict(DEFAULTS, **options)
    for key in ('dimensions', 'resolution', 'frequency_points', 'max_cells'):
        value = float(result[key])
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f'{key} must be a finite whole number.')
        result[key] = int(value)
    if result['dimensions'] not in (2, 3):
        raise ValueError('Choose a 2D cross section or the full 3D structure.')
    for key, low, high in [('resolution', 5, 1000), ('frequency_points', 2, 2001),
                           ('max_cells', 100, 100000000)]:
        if not low <= result[key] <= high:
            raise ValueError(f'{key} must be between {low} and {high}.')
    for key in ('wavelength_min_nm', 'wavelength_max_nm', 'pml_um', 'padding_um',
                'run_after_sources', 'courant', 'decay_by', 'fit_tolerance', 'section_y_um'):
        value = float(result[key])
        if not math.isfinite(value) or (key != 'section_y_um' and value <= 0):
            raise ValueError(f'{key} must be finite and positive.')
        result[key] = value
    if result['wavelength_min_nm'] >= result['wavelength_max_nm']:
        raise ValueError('The final wavelength must exceed the initial wavelength.')
    if result['courant'] > .5 or result['decay_by'] >= 1 or result['fit_tolerance'] > .1:
        raise ValueError('Courant must be ≤ 0.5, decay < 1, and material-fit tolerance ≤ 10%.')
    if result['polarization'] not in ('s', 'p'):
        raise ValueError('FDTD supports s or p polarization at normal incidence.')
    for key in ('save_fields', 'fit_materials'):
        if not isinstance(result[key], bool):
            raise ValueError(f'{key} must be true or false.')
    return result


def evaluate_medium(medium, frequencies):
    import numpy as np
    f = np.asarray(frequencies, dtype=float)
    eps = np.full(f.shape, complex(medium['epsilon']), dtype=complex)
    for pole in medium.get('poles', []):
        eps += pole['strength'] / (pole['frequency']**2 - f*f - 1j*pole['gamma']*f)
    return eps


def _nonnegative_least_squares(matrix, rhs):
    """Small Lawson–Hanson active-set solve using only bundled NumPy."""
    import numpy as np
    norms = np.maximum(np.linalg.norm(matrix, axis=0), 1e-30)
    matrix = matrix / norms
    x = np.zeros(matrix.shape[1])
    active = np.zeros(len(x), dtype=bool)
    for _ in range(1500):
        gradient = matrix.T @ (rhs-matrix@x)
        gradient[active] = -np.inf
        if float(np.max(gradient)) <= 1e-9:
            return x/norms
        active[int(np.argmax(gradient))] = True
        for _ in range(1500):
            candidate = np.zeros_like(x)
            candidate[active] = np.linalg.lstsq(matrix[:, active], rhs, rcond=1e-10)[0]
            if np.all(candidate[active] > 0):
                x = candidate
                break
            negative = active & (candidate <= 0)
            alpha = np.min(x[negative] / (x[negative]-candidate[negative]+1e-30))
            x += alpha*(candidate-x)
            active[x <= 1e-12] = False
            x[~active] = 0
        else:
            break
    raise ValueError('The passive material fit did not converge. Narrow the wavelength band or use different n,k data.')


def convert_material(material, fmin, fmax, options):
    """Use exact lossless constants, or a checked passive causal Lorentz fit.

    A complex constant epsilon cannot represent a broadband time-domain
    material. Tabulated data are fitted only after the user enables fitting.
    No endpoint clamping, gain, or silent centre-frequency substitution.
    """
    import numpy as np
    name = material['name']
    if material['model'] != 'table_nk':
        a, b = material['a'], material['b']
        eps = complex(a, b) if material['model'] == 'constant_eps' else complex(a, b)**2
        if abs(eps.imag) > 1e-12 or eps.real <= 0:
            raise ValueError(f'{name}: FDTD requires a lossless positive constant or a tabulated n,k dispersion model. A complex constant is not a causal broadband model.')
        return dict(name=name, epsilon=eps.real, poles=[], relative_error=0.)
    table = np.asarray(material['table'], dtype=float)
    lo, hi = 1000/fmax, 1000/fmin
    if lo < table[0, 0] - 1e-8 or hi > table[-1, 0] + 1e-8:
        raise ValueError(f'{name}: n,k data must cover the entire {lo:g}–{hi:g} nm FDTD band.')
    frequencies = np.linspace(fmin, fmax, 241)
    n = np.interp(1000/frequencies, table[:, 0], table[:, 1])
    k = np.interp(1000/frequencies, table[:, 0], table[:, 2])
    if np.any(n <= 0) or np.any(k < 0):
        raise ValueError(f'{name}: passive FDTD fitting requires n > 0 and k ≥ 0.')
    target = (n + 1j*k)**2
    if np.max(abs(target - target[0])) < 1e-10 and abs(target[0].imag) < 1e-12:
        return dict(name=name, epsilon=float(target[0].real), poles=[], relative_error=0.)
    if not options['fit_materials']:
        raise ValueError(f'{name}: enable passive dispersion fitting to use tabulated material data in FDTD.')
    # Nonnegative oscillator strengths guarantee passive poles. Fixed resonance
    # locations avoid nonlinear-fit instability; insignificant poles are pruned.
    candidates = [(0., gamma) for gamma in (fmin*.05, fmin*.3, fmin, fmax*3)]
    candidates += [(float(f), float(g)) for f in np.geomspace(fmin*.15, fmax*6, 28)
                   for g in (f*.015, f*.12, f*.6)]
    bases = [np.ones_like(frequencies, dtype=complex)]
    bases += [1/(f*f - frequencies**2 - 1j*g*frequencies) for f, g in candidates]
    basis = np.asarray(bases).T
    scale = np.maximum(abs(target), 1.)
    matrix = np.vstack((basis.real/scale[:, None], basis.imag/scale[:, None]))
    rhs = np.concatenate(((target.real-1)/scale, target.imag/scale))
    weights = _nonnegative_least_squares(matrix, rhs)
    poles = [dict(frequency=f, gamma=g, strength=float(w))
             for (f, g), w in zip(candidates, weights[1:]) if w > 1e-10]
    medium = dict(name=name, epsilon=float(1+weights[0]), poles=poles)
    # Validate on a denser independent grid, so narrow fitted poles cannot hide
    # errors between the optimization samples.
    check_f = np.linspace(fmin, fmax, 2001)
    check_n = np.interp(1000/check_f, table[:, 0], table[:, 1])
    check_k = np.interp(1000/check_f, table[:, 0], table[:, 2])
    check_target = (check_n+1j*check_k)**2
    error = float(np.max(abs(evaluate_medium(medium, check_f)-check_target)/np.maximum(abs(check_target), 1.)))
    if error > options['fit_tolerance']:
        raise ValueError(f'{name}: passive dispersion fit error {100*error:.2f}% exceeds {100*options["fit_tolerance"]:g}%. Narrow the wavelength band or use better material data.')
    medium['relative_error'] = error
    return medium


def build_job(project, files, options):
    from model import prepare
    from structure_preview import periodic_centers, section_interval
    opts = validate_options(options)
    settings = copy.deepcopy(project['settings'])
    settings.update(mode='Wavelength sweep', theta_deg=0., phi_deg=0.,
        polarization=opts['polarization'], wl_start_nm=opts['wavelength_min_nm'],
        wl_stop_nm=opts['wavelength_max_nm'], wl_step_nm=opts['wavelength_max_nm']-opts['wavelength_min_nm'])
    model = prepare(project['materials'], project['layers'], project['patterns'], files, settings)
    used = {layer['material'] for layer in model['layers']} | {p['material'] for p in model['patterns']}
    fmin, fmax = 1000/opts['wavelength_max_nm'], 1000/opts['wavelength_min_nm']
    materials = {m['name']: convert_material(m, fmin, fmax, opts) for m in model['materials'] if m['name'] in used}
    for layer in (model['layers'][0], model['layers'][-1]):
        if materials[layer['material']]['poles']:
            raise ValueError('Incident and exit media must be lossless constants for normalized flux monitors and PML.')
    total = sum(layer['thickness'] for layer in model['layers'][1:-1])
    if total <= 0:
        raise ValueError('FDTD needs at least one positive-thickness device layer.')
    size_z = total + 2*(opts['padding_um']+opts['pml_um'])
    cells = math.ceil(model['ax']*opts['resolution'])*math.ceil(size_z*opts['resolution'])
    if opts['dimensions'] == 3:
        cells *= math.ceil(model['ay']*opts['resolution'])
    if cells > opts['max_cells']:
        raise ValueError(f'Estimated grid {cells:,} cells exceeds {opts["max_cells"]:,}. Reduce resolution or choose 2D.')
    largest_pole_count = max(len(m['poles']) for m in materials.values())
    estimated_memory_mib = cells*(16*12+largest_pole_count*8*6)/(1024**2)
    if estimated_memory_mib > 8192:
        raise ValueError(f'Estimated field/material memory is {estimated_memory_mib:,.0f} MiB, exceeding the 8 GiB safety limit. Reduce resolution or use 2D.')
    if min(opts['pml_um'], opts['padding_um']) * opts['resolution'] < 4:
        raise ValueError('PML and padding each need at least four grid cells.')
    epsilon_min = min(m['epsilon'] for m in materials.values())
    if opts['courant'] > math.sqrt(epsilon_min/opts['dimensions']):
        raise ValueError('The low-index material requires a lower Courant factor for grid stability.')
    # Fastest fitted oscillator bounds time step stability (Meep ω Δt < 2).
    max_frequency = max([p['frequency'] for m in materials.values() for p in m['poles']] or [0])
    if math.pi*max_frequency*opts['courant']/opts['resolution'] >= 1:
        raise ValueError('Material dispersion requires a higher grid resolution or lower Courant factor.')
    geometry, z = [], -total/2
    depths = {}
    for layer in model['layers'][1:-1]:
        depths[layer['name']] = (z+layer['thickness']/2, layer['thickness'])
        if layer['thickness']:
            geometry.append(dict(shape='layer', material=layer['material'], z=z+layer['thickness']/2, thickness=layer['thickness']))
        z += layer['thickness']
    cut = (opts['section_y_um']+model['ay']/2) % model['ay'] - model['ay']/2
    for region in model['patterns']:
        if region['layer'] not in depths:
            raise ValueError('FDTD patterns must lie in finite device layers, not the incident or exit medium.')
        center_z, thickness = depths[region['layer']]
        if thickness == 0:
            continue
        region = dict(region)
        if region['shape'] == 'circle':
            region['sy'] = region['sx']
        for cx, cy in periodic_centers(region, model['ax'], model['ay'], (-model['ax']/2, model['ax']/2, -model['ay']/2, model['ay']/2)):
            if opts['dimensions'] == 2:
                interval = section_interval(region, cut, (cx, cy))
                if interval:
                    geometry.append(dict(shape='slice', material=region['material'], z=center_z,
                        thickness=thickness, x=(interval[0]+interval[1])/2, width=interval[1]-interval[0]))
            else:
                geometry.append(dict(region, x=cx, y=cy, z=center_z, thickness=thickness))
    warnings = ['Normal incidence; periodic lateral boundaries; PML along the propagation direction.']
    if opts['dimensions'] == 2:
        warnings.append('2D uses the XZ section extruded along Y. Use 3D for the actual periodic hole array.')
    warnings += [f'{m["name"]}: passive dispersion fit max relative error {100*m["relative_error"]:.3g}%.' for m in materials.values() if m['poles']]
    return dict(schema=1, options=opts, ax=model['ax'], ay=model['ay'], total=total, size_z=size_z,
        materials=materials, incident=model['layers'][0]['material'], exit=model['layers'][-1]['material'],
        geometry=geometry, fmin=fmin, fmax=fmax, estimated_cells=cells,
        estimated_memory_mib=estimated_memory_mib, warnings=warnings)
