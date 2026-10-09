"""Specular co-polarized tangential electric-field phase at stack boundaries."""
import cmath
import csv
import math
from model import epsilon


def validate_phase_model(model):
    if len(model['layers']) < 3:
        raise ValueError('Phase measurement requires an internal layer; use a zero-thickness exit-material layer for a single interface.')
    boundaries = {model['layers'][0]['name'], model['layers'][-1]['name']}
    if any(p['layer'] in boundaries for p in model['patterns']):
        raise ValueError('Phase measurement requires uniform incident and exit half-spaces.')


def measure_phase(simulation, model, wavelength, theta):
    validate_phase_model(model)
    mats = {m['name']: m for m in model['materials']}
    eps_in = epsilon(mats[model['layers'][0]['material']], wavelength)
    eps_out = epsilon(mats[model['layers'][-1]['material']], wavelength)
    n = cmath.sqrt(eps_in)
    angle, phi = math.radians(theta), math.radians(model['phi'])
    kx, ky = n * math.sin(angle) * math.cos(phi), n * math.sin(angle) * math.sin(phi)

    def electric(amplitudes, eps, direction):
        kz = cmath.sqrt(eps-kx*kx-ky*ky)
        if kz.imag < 0 or (abs(kz.imag) < 1e-14 and kz.real < 0):
            kz = -kz
        kz *= direction
        if abs(kz) < 1e-14 or abs(eps) < 1e-14:
            return None
        hx, hy = amplitudes[0], amplitudes[len(amplitudes)//2]
        hz = -(kx*hx+ky*hy)/kz
        return ((hy*kz-hz*ky)/eps, (hz*kx-hx*kz)/eps)

    incident, reflected = simulation.GetAmplitudes(model['layers'][0]['name'], 0.)
    transmitted, _ = simulation.GetAmplitudes(model['layers'][-1]['name'], 0.)
    reference = electric(incident, eps_in, 1)
    if reference is None:
        return [None, None]
    norm = sum(abs(v)**2 for v in reference)
    if norm < 1e-24:
        return [None, None]
    phases = []
    for amps, eps, direction in [(reflected, eps_in, -1), (transmitted, eps_out, 1)]:
        field = electric(amps, eps, direction)
        coefficient = None if field is None else sum(v*r.conjugate() for v, r in zip(field, reference))/norm
        phases.append(math.degrees(cmath.phase(coefficient)) if coefficient is not None and abs(coefficient) > 1e-10 and math.isfinite(abs(coefficient)) else None)
    return phases


def write_phase_csv(path, rows):
    # Unwrap only within contiguous valid segments; never bridge undefined phase.
    previous = [None, None]
    unwrapped = [None, None]
    reference = [None, None]
    with open(path, 'w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['wavelength_nm', 'angle_deg', 'reflection_phase_deg', 'transmission_phase_deg',
                         'reflection_change_deg', 'transmission_change_deg'])
        for _, wave, theta, *phases in rows:
            changes = []
            for j, phase in enumerate(phases):
                if phase is None:
                    previous[j] = unwrapped[j] = reference[j] = None
                    changes.append(None)
                    continue
                if previous[j] is None:
                    unwrapped[j] = reference[j] = phase
                else:
                    unwrapped[j] += (phase-previous[j]+180) % 360-180
                changes.append(unwrapped[j]-reference[j])
                previous[j] = phase
            writer.writerow([wave, theta, *phases, *changes])


def phase_figure(frame):
    import numpy as np
    from matplotlib.figure import Figure
    figure = Figure(figsize=(8, 6), layout='constrained')
    axes = figure.subplots(2, 1)
    if frame.empty:
        for axis in axes:
            axis.set_axis_off()
        axes[0].text(.5, .5, 'Enable phase measurement and run a simulation.\nOlder runs do not contain phase data.', ha='center', transform=axes[0].transAxes)
        return figure
    variable = 'angle_deg' if frame['angle_deg'].nunique() > 1 else 'wavelength_nm'
    frame = frame.iloc[np.unique(np.linspace(0, len(frame)-1, min(len(frame), 20000), dtype=int))]
    for axis, suffix, title in zip(axes, ['phase', 'change'], ['Wrapped phase', 'Unwrapped change from first valid sample in each segment']):
        for response in ['reflection', 'transmission']:
            axis.plot(frame[variable], frame[f'{response}_{suffix}_deg'], label=response.title())
        axis.set(ylabel='Degrees', title=title)
        axis.grid(alpha=.2)
        axis.legend()
    axes[-1].set_xlabel('Incidence angle (degrees)' if variable == 'angle_deg' else 'Wavelength (nm)')
    return figure
