"""Exact Rayleigh-threshold solves using bounded Maxwell radiation columns.

The normal native modal path remains fast away from a threshold. At a grazing
exterior order its H-only normalization is singular; the same Fourier operators
are instead solved with finite H/E port coordinates, at the unchanged frequency.
"""
import cmath
import math
import sys
from model import epsilon


def cutoff_candidate(model, wavelength, theta, orders):
    """Cheap scalar guard; no dense operators or numerical imports per point."""
    materials = {m['name']: m for m in model['materials']}
    first, last = model['layers'][0], model['layers'][-1]
    if any(region['layer'] in (first['name'], last['name']) for region in model['patterns']):
        return False
    omega = 2*math.pi*1000/wavelength
    incident_eps = epsilon(materials[first['material']], wavelength)
    transverse = omega*cmath.sqrt(incident_eps).real*math.sin(math.radians(theta))
    bx = transverse*math.cos(math.radians(model['phi']))
    by = transverse*math.sin(math.radians(model['phi']))
    for layer in (first, last):
        eps = epsilon(materials[layer['material']], wavelength)
        if complex(eps).imag != 0 or complex(eps).real <= 0:
            continue
        term = eps*omega*omega
        for gx, gy in orders:
            lateral = (bx+2*math.pi*gx/model['ax'])**2+(by+2*math.pi*gy/model['ay'])**2
            if abs(term-lateral) <= 8*sys.float_info.epsilon*(abs(term)+lateral):
                return True
    return False


def solve_cutoff(simulation, perf):
    """Return a complete field-capable exact solution, with residual checks."""
    import numpy as np
    from s4_eigenfree_gpu import solve_batch
    from eigenfree_scan import FieldView
    payload = simulation.GetEigenfreeOperators()
    solution = solve_batch([payload], backend='numpy', symmetry=bool(perf.get('mirror_symmetry', True)))
    if not solution.regular_ports:
        raise ValueError('Cutoff guard and exact Fourier wavevectors disagree')
    rta = solution.rta()[0]
    if not np.isfinite(rta).all():
        raise FloatingPointError('Nonfinite exact cutoff power')
    # Compare tangential E/H on both sides of both interfaces. This catches
    # mistakes in radiation normalization, propagation and amplitude recovery.
    residual = 0.
    for exterior, inside, exterior_z, inside_z in (
            (0, 1, 0., 0.),
            (len(payload['layers'])-1, len(payload['layers'])-2,
             0., payload['layers'][-2]['thickness'])):
        outside = solution.coefficients(exterior, exterior_z)[0][:, [0, 1, 3, 4]]
        interior = solution.coefficients(inside, inside_z)[0][:, [0, 1, 3, 4]]
        scale = max(float(np.max(abs(outside))), float(np.max(abs(interior))), np.finfo(float).tiny)
        residual = max(residual, float(np.max(abs(outside-interior)))/scale)
    if residual > 2e-10:
        raise ArithmeticError(f'Exact cutoff interface residual {residual:g} exceeds tolerance')
    solution.diagnostics['interface_residual'] = residual
    return FieldView(solution, 0, payload), tuple(map(float, rta)), dict(solution.diagnostics)
