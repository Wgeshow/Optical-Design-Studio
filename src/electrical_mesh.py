"""Mesh resource estimates and memory-scalable electrical linear solves.

The cell counts are exact user inputs. Resource checks never reduce resolution.
Large positive-definite finite-volume systems use CG to avoid sparse LU fill-in.
"""
from __future__ import annotations

import ctypes
import math
import os

MESH_AXIS_MAX = 2_147_483_647
DIRECT_SOLVE_CELLS = 50_000


def available_memory_bytes():
    """Read currently available physical RAM, without an optional dependency."""
    try:
        if os.name == 'nt':
            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                            *[(name, ctypes.c_ulonglong) for name in
                              ('total', 'available', 'page_total', 'page_available',
                               'virtual_total', 'virtual_available', 'extended')]]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.available)
        else:
            return int(os.sysconf('SC_AVPHYS_PAGES')) * int(os.sysconf('SC_PAGE_SIZE'))
    except (AttributeError, OSError, ValueError):
        pass
    return None


def mesh_resource_estimate(device):
    """Conservative planning estimate, including graph assembly and CG buffers.

    Sparse LU is used only on small systems. Its fill-in varies with geometry;
    this is a planning estimate, not an exact peak-memory prediction.
    """
    mesh = device.get('mesh', {})
    layers = sum(bool(row.get('enabled', True)) for row in device.get('layers', []))
    shape = (int(mesh.get('nx', 16)), int(mesh.get('ny', 16)),
             int(mesh.get('nz_per_layer', 8)) * layers)
    cells = math.prod(shape)
    iterative = cells > DIRECT_SOLVE_CELLS
    peak = cells * 1200 + (32 if iterative else 256) * 1024**2
    return dict(shape=list(shape), cells=cells, estimated_peak_bytes=peak,
                estimated_volume_bytes=cells * 192,
                linear_solver='Jacobi-scaled CG' if iterative else 'Sparse direct',
                cell_budget=int(mesh.get('max_nodes', 0)))


def check_mesh_resources(device, available_bytes=None):
    """Refuse an unsafe allocation before creating any three-dimensional arrays."""
    estimate = mesh_resource_estimate(device)
    available = available_memory_bytes() if available_bytes is None else available_bytes
    estimate['available_memory_bytes'] = available
    # Leave RAM for Qt, the operating system, and the user's other applications.
    estimate['automatic_budget_bytes'] = int(available * .6) if available else None
    if available and estimate['estimated_peak_bytes'] > estimate['automatic_budget_bytes']:
        raise ValueError(
            f'Mesh {" × ".join(map(str, estimate["shape"]))} needs '
            f'{estimate["cells"]:,} cells, with estimated peak RAM '
            f'{estimate["estimated_peak_bytes"] / 1024**3:.2f} GiB. '
            f'The current available-RAM budget is '
            f'{estimate["automatic_budget_bytes"] / 1024**3:.2f} GiB. '
            'Free RAM or adjust the mesh; resolution has not been reduced.')
    return estimate


def solve_linear_system(matrix, rhs, cancelled=lambda: False, progress=None,
                        force_iterative=False):
    """Solve an anchored symmetric positive-definite finite-volume system."""
    import numpy as np
    from scipy.sparse.linalg import LinearOperator, cg, spsolve
    if cancelled():
        raise InterruptedError('Electrical simulation cancelled')
    rhs = np.asarray(rhs, dtype=float)
    size = matrix.shape[0]
    if not force_iterative and size <= DIRECT_SOLVE_CELLS:
        values = spsolve(matrix, rhs)
        metadata = dict(method='Sparse direct', iterations=0)
    else:
        diagonal = np.asarray(matrix.diagonal(), dtype=float)
        if np.any(diagonal <= 0) or not np.isfinite(diagonal).all():
            raise RuntimeError('Electrical linear system has an unanchored or invalid diagonal')
        scale = 1. / np.sqrt(diagonal)
        operator = LinearOperator(matrix.shape,
                                  matvec=lambda values: scale * (matrix @ (scale * values)),
                                  dtype=float)
        scaled_rhs = scale * rhs
        iterations = 0

        def callback(_):
            nonlocal iterations
            iterations += 1
            if cancelled():
                raise InterruptedError('Electrical simulation cancelled')
            if progress is not None and iterations % 100 == 0:
                progress(iterations)

        values, status = cg(operator, scaled_rhs, rtol=1e-12, atol=0.,
                            maxiter=max(2000, min(100000, size)), callback=callback)
        if status:
            raise RuntimeError(
                f'Fine-mesh electrical CG solve did not converge after {iterations:,} '
                'iterations. Inspect material contrast/contact connectivity or mesh aspect ratios.')
        values *= scale
        metadata = dict(method='Jacobi-scaled CG', iterations=iterations, relative_tolerance=1e-12)
    if not np.isfinite(values).all():
        raise RuntimeError('Electrical linear solve produced nonfinite values')
    residual = matrix @ values - rhs
    metadata['max_absolute_residual'] = float(np.max(np.abs(residual))) if size else 0.
    return values, metadata
