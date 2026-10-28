"""GUI-independent input validation. Geometry is um; wavelengths are nm."""
import bisect
import math
import re
from collections.abc import Mapping
from pathlib import Path

MAT_COLS = ["Name", "Model", "A", "B", "DataFile", "WavelengthUnit"]
LAYER_COLS = ["Name", "Thickness_um", "Material"]
PAT_COLS = ["Shape", "Layer", "Material", "CenterX_um", "CenterY_um", "SizeX_um", "SizeY_um", "Angle_deg"]
MODES = ("CPU only", "CPU + GPU", "GPU-assisted (one worker)")
SOLVER_BACKENDS = ('native', 'eigenfree-gpu')
DEFAULT_PERFORMANCE = dict(mode=MODES[0], workers=0, threads=1, gpu_device=0,
                           gpu_min_n=1024, gpu_block=256, chunk_size=8,
                           timeout_seconds=0, require_gpu=False,
                           solver_backend='native', mirror_symmetry=True,
                           eigenfree_symmetry=True, eigenfree_batch_size=32)
# Sweeps are evaluated in performance-sized chunks by the compute layer.  Keep
# a generous input guard only to catch accidental unit/step mistakes.
MAX_SWEEP_POINTS = 20_000_000
MATERIAL_INTERPOLATIONS = ('linear', 'log_k')


def material_interpolations(values):
    """Validate optional per-name policies without extending material rows."""
    if not isinstance(values, Mapping):
        raise ValueError('Material interpolations must be an object keyed by material name.')
    result = {}
    for name, mode in values.items():
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError('Material interpolation needs a nonempty material name without outer whitespace.')
        if mode not in MATERIAL_INTERPOLATIONS:
            raise ValueError(f'{name}: interpolation must be linear or log_k.')
        result[name] = mode
    return result


def _table_interpolation(material):
    mode = material.get('interpolation', 'linear')
    if mode not in MATERIAL_INTERPOLATIONS:
        raise ValueError(f'{material.get("name", "Material")}: interpolation must be linear or log_k.')
    if mode == 'log_k' and any(not math.isfinite(float(row[2])) or float(row[2]) <= 0 for row in material['table']):
        raise ValueError(f'{material.get("name", "Material")}: Linear (in log k) requires every k sample to be strictly positive.')
    return mode


def interpolate_nk(material, wavelength):
    """Evaluate one wavelength, clamping endpoints and keeping n linear."""
    if material['model'] != 'table_nk':
        return material['a'], material['b']
    mode = _table_interpolation(material)
    table = material['table']
    grid = material.get('grid') or [row[0] for row in table]
    index = bisect.bisect_left(grid, wavelength)
    if index == 0:
        return tuple(table[0][1:])
    if index == len(table):
        return tuple(table[-1][1:])
    lo, hi = table[index-1], table[index]
    fraction = (wavelength-lo[0])/(hi[0]-lo[0])
    n = lo[1]+fraction*(hi[1]-lo[1])
    # Preserve measured samples exactly, including endpoints of each interval.
    if mode == 'log_k' and wavelength == hi[0]:
        return hi[1], hi[2]
    k = (math.exp(math.log(lo[2])+fraction*(math.log(hi[2])-math.log(lo[2])))
         if mode == 'log_k' else lo[2]+fraction*(hi[2]-lo[2]))
    return n, k


def sample_nk(material, wavelengths):
    """Vector evaluator shared by Materials preview and causal FDTD fitting."""
    import numpy as np
    wavelengths = np.asarray(wavelengths, dtype=float)
    if material['model'] != 'table_nk':
        value = complex(material['a'], material['b'])
        if material['model'] == 'constant_eps':
            value = np.sqrt(value)
        return np.full(wavelengths.shape, value.real), np.full(wavelengths.shape, value.imag)
    mode = _table_interpolation(material)
    table = np.asarray(material['table'], dtype=float)
    n = np.interp(wavelengths, table[:, 0], table[:, 1])
    if mode == 'linear':
        k = np.interp(wavelengths, table[:, 0], table[:, 2])
    else:
        k = np.exp(np.interp(wavelengths, table[:, 0], np.log(table[:, 2])))
        # Log/exp roundoff must not alter original measured or clamped samples.
        indexes = np.searchsorted(table[:, 0], wavelengths).clip(0, len(table)-1)
        exact = (wavelengths == table[indexes, 0]) | (wavelengths <= table[0, 0]) | (wavelengths >= table[-1, 0])
        k = np.where(exact, table[indexes, 2], k)
    return n, k


def blank(value):
    return value is None or str(value).strip().lower() in ("", "nan", "none")


def number(value, name, default=None, minimum=None):
    if blank(value) and default is not None:
        value = default
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric") from None
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{name} must be finite" + (f" and >= {minimum}" if minimum is not None else ""))
    return result


def integer(value, name, minimum=0):
    result = number(value, name, minimum=minimum)
    if not result.is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(result)


def positive(value, name):
    result = number(value, name)
    if result <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return result


def sweep_range(start, stop, step, label, limit=MAX_SWEEP_POINTS):
    start, stop, step = number(start, label + " start"), number(stop, label + " stop"), positive(step, label + " step")
    if stop < start:
        raise ValueError(label + " stop must be >= start")
    count_float = (stop - start) / step
    if not math.isfinite(count_float) or count_float > limit:
        raise ValueError(f"{label} sweep exceeds the safety limit of {limit:,} points; increase the step or split the scan into batches")
    count = int(math.floor(count_float + 1e-9)) + 1
    if count > limit:
        raise ValueError(f"{label} sweep exceeds the safety limit of {limit:,} points; increase the step or split the scan into batches")
    return start, step, count


def sweep(start, stop, step, label, limit=MAX_SWEEP_POINTS):
    start, step, count = sweep_range(start, stop, step, label, limit)
    return [start + i * step for i in range(count)]


def numeric_rows(path, unit):
    from nk_import import parse_nk
    try:
        return parse_nk(Path(path).read_text(encoding="utf-8-sig"), unit)
    except ValueError as exc:
        raise ValueError(f"{Path(path).name}: {exc}") from exc


def epsilon(material, wavelength):
    if 'epsilon_tensor' in material:
        return tensor_epsilon(material, wavelength)
    if material["model"] == "constant_eps":
        return complex(material["a"], material["b"])
    n, k = interpolate_nk(material, wavelength)
    return complex(n * n - k * k, 2 * n * k)


def tensor_epsilon(material, wavelength):
    """Interpolate a coupled DC optical tensor accepted by native S4.

    S4 exposes the xy block and zz; off-plane coupling is unsupported by
    its Python binding and must never be silently discarded.
    """
    grid=material.get('grid', [])
    tensors=material['epsilon_tensor']
    if not grid or len(tensors)!=len(grid):
        raise ValueError('Optical tensor samples must match a wavelength grid.')
    if any(not math.isfinite(float(w)) for w in grid) or any(b<=a for a,b in zip(grid,grid[1:])):
        raise ValueError('Optical tensor wavelength grid must be finite and increasing.')
    index=bisect.bisect_left(grid,wavelength)
    lo=max(0,min(index-1,len(grid)-1));hi=min(index,len(grid)-1)
    fraction=0. if lo==hi else (wavelength-grid[lo])/(grid[hi]-grid[lo])
    result=[]
    for row in range(3):
        entries=[]
        for col in range(3):
            try:
                left=complex(*tensors[lo][row][col]);right=complex(*tensors[hi][row][col])
            except (TypeError,ValueError,IndexError):
                raise ValueError('Optical tensor must contain 3x3 complex [real, imaginary] samples.') from None
            if not all(math.isfinite(v) for v in (left.real,left.imag,right.real,right.imag)):
                raise ValueError('Optical tensor samples must be finite.')
            if (row,col) in ((0,2),(1,2),(2,0),(2,1)) and (abs(left)>0 or abs(right)>0):
                raise ValueError('Native S4 supports the xy tensor block and zz; off-plane terms must be zero.')
            entries.append(left+(right-left)*fraction)
        result.append(tuple(entries))
    return tuple(result)


def prepare(materials, layers, patterns, files, settings, compact_points=False):
    """Snapshot uploads and validate before any native worker starts."""
    interpolations = material_interpolations(settings.get('material_interpolations', {}))
    uploaded = {}
    for file in files or []:
        path = Path(file)
        if path.name in uploaded:
            raise ValueError(f"Duplicate uploaded filename: {path.name}")
        uploaded[path.name] = path
    mats, layer_list, regions, warnings = [], [], [], []
    names = set()
    for row in materials:
        if blank(row.get("Name")):
            continue
        name = str(row["Name"]).strip()
        if name in names:
            raise ValueError("Material names must be unique")
        names.add(name)
        mode = str(row.get("Model", "")).strip()
        if mode not in ("constant_nk", "constant_eps", "table_nk"):
            raise ValueError(f"{name}: invalid material model")
        if mode != 'table_nk' and interpolations.get(name) == 'log_k':
            raise ValueError(f'{name}: Log k interpolation applies only to tabulated n,k materials.')
        mat = dict(name=name, model=mode, a=1.0, b=0.0)
        if mode == "table_nk":
            filename = Path(str(row.get("DataFile", ""))).name
            if filename not in uploaded:
                raise ValueError(f"{name}: upload the n,k file '{filename}'")
            mat["table"] = numeric_rows(uploaded[filename], row.get("WavelengthUnit") or "nm")
            mat["grid"] = [r[0] for r in mat["table"]]
            if name in interpolations:
                mat['interpolation'] = interpolations[name]
            _table_interpolation(mat)
        else:
            mat["a"] = number(row.get("A"), name + " A")
            mat["b"] = number(row.get("B"), name + " B", default=0.0)
        mats.append(mat)
    if not mats:
        raise ValueError("Add at least one material")
    for row in layers:
        name = "" if blank(row.get("Name")) else str(row["Name"]).strip()
        material = str(row.get("Material", "")).strip()
        if not name or material not in names:
            raise ValueError(f"Layer '{name}' needs a name and a valid material")
        layer_list.append(dict(name=name, material=material,
                               thickness=number(row.get("Thickness_um"), name + " thickness", default=0, minimum=0)))
    layer_names = [row["name"] for row in layer_list]
    if len(layer_list) < 3 or len(set(layer_names)) != len(layer_names):
        raise ValueError("Use at least three uniquely named layers (incident, device, exit)")
    if layer_list[0]["thickness"] != 0 or layer_list[-1]["thickness"] != 0:
        raise ValueError("Incident and exit half-spaces must have thickness 0")
    for row in patterns:
        if all(blank(row.get(k)) for k in ("Shape", "Layer", "Material")):
            continue
        shape = str(row.get("Shape", "")).strip().lower()
        layer, material = str(row.get("Layer", "")).strip(), str(row.get("Material", "")).strip()
        if shape not in ("circle", "ellipse", "rectangle") or layer not in layer_names or material not in names:
            raise ValueError("Patterns require circle/ellipse/rectangle and valid layer/material names")
        regions.append(dict(shape=shape, layer=layer, material=material,
            cx=number(row.get("CenterX_um"), "Center X", default=0),
            cy=number(row.get("CenterY_um"), "Center Y", default=0),
            sx=positive(row.get("SizeX_um"), "Size X"),
            sy=number(row.get("SizeY_um"), "Size Y", default=0, minimum=0) if shape == "circle" else positive(row.get("SizeY_um"), "Size Y"),
            angle=number(row.get("Angle_deg"), "Pattern angle", default=0)))
    ax, ay = positive(settings["ax_um"], "Lattice X"), positive(settings["ay_um"], "Lattice Y")
    basis = integer(settings["NumG"], "Basis count", 1)
    if basis > 4096:
        raise ValueError("This GUI limits the basis count to 4096; high counts need substantial RAM")
    mode = settings["mode"]
    phi = number(settings["phi_deg"], "Azimuth")
    if settings["polarization"] not in ("s", "p", "45° s+p"):
        raise ValueError("Invalid polarization")
    if mode == "Wavelength sweep":
        theta = number(settings["theta_deg"], "Incidence theta")
        if compact_points:
            from scan_storage import ScanPoints
            start, step, count = sweep_range(settings["wl_start_nm"], settings["wl_stop_nm"], settings["wl_step_nm"], "Wavelength")
            points = ScanPoints(start, step, count, theta)
        else:
            wavelengths = sweep(settings["wl_start_nm"], settings["wl_stop_nm"], settings["wl_step_nm"], "Wavelength")
            points = [[i, wl, theta] for i, wl in enumerate(wavelengths)]
    elif mode == "Angle sweep":
        wl = positive(settings["fixed_wl_nm"], "Fixed wavelength")
        angles = sweep(settings["angle_start"], settings["angle_stop"], settings["angle_step"], "Angle", 361)
        points = [[i, wl, theta] for i, theta in enumerate(angles)]
    else:
        raise ValueError("Invalid sweep mode")
    checked_points = (points[0], points[-1]) if compact_points and mode == 'Wavelength sweep' else points
    if any(wl <= 0 or not -90 < theta < 90 for _, wl, theta in checked_points):
        raise ValueError("Wavelengths must be positive and incidence angles strictly between -90 and 90 degrees")
    lo, hi = min(p[1] for p in checked_points), max(p[1] for p in checked_points)
    for mat in mats:
        if mat["model"] == "table_nk" and (lo < mat["grid"][0] or hi > mat["grid"][-1]):
            warnings.append(f"{mat['name']} table spans {mat['grid'][0]:g}–{mat['grid'][-1]:g} nm. Endpoint clamping is used outside it, as in v1.1. Check WavelengthUnit.")
    return dict(materials=mats, layers=layer_list, patterns=regions, ax=ax, ay=ay,
                basis=basis, phi=phi, polarization=settings["polarization"], mode=mode,
                points=points, warnings=warnings)


def performance(values, point_count, cpu_count):
    p = dict(DEFAULT_PERFORMANCE, **values)
    p["timeout_seconds"] = 0  # Legacy saved limits no longer stop calculations.
    if p['solver_backend'] not in SOLVER_BACKENDS:
        raise ValueError('Invalid solver backend')
    for name in ('mirror_symmetry', 'eigenfree_symmetry'):
        if not isinstance(p[name], bool):
            raise ValueError(name.replace('_', ' ') + ' must be true or false')
    p['eigenfree_batch_size'] = integer(p['eigenfree_batch_size'], 'GPU wavelengths per batch', 1)
    if p['eigenfree_batch_size'] > 256:
        raise ValueError('GPU wavelengths per batch must be at most 256')
    if p['solver_backend'] == 'eigenfree-gpu':
        p.update(mode=MODES[2], workers=1)
    if point_count < 1 or cpu_count < 1:
        raise ValueError("Need at least one sweep point and one logical CPU")
    if not isinstance(p["require_gpu"], bool):
        raise ValueError("Require GPU work must be true or false")
    if p["mode"] not in MODES:
        raise ValueError("Invalid CPU/GPU mode")
    for name, minimum in (("workers", 0), ("threads", 1), ("gpu_device", 0), ("gpu_min_n", 1), ("gpu_block", 64), ("chunk_size", 1), ("timeout_seconds", 0)):
        p[name] = integer(p[name], name.replace("_", " "), minimum)
    if p["gpu_block"] not in (64, 128, 256, 512, 1024):
        raise ValueError("GPU tile size must be 64, 128, 256, 512 or 1024")
    if p["gpu_device"] > 1024 or p["gpu_min_n"] > 2147483647:
        raise ValueError("GPU device or threshold exceeds the native runtime's supported range")
    if p["chunk_size"] > 10000:
        raise ValueError("Chunk size must be at most 10000")
    if p["threads"] > cpu_count:
        raise ValueError("Threads per worker exceeds available logical CPUs")
    requested = p["workers"] or max(1, cpu_count // p["threads"])
    if p["mode"] == MODES[2]:
        requested = 1
    if requested * p["threads"] > cpu_count:
        raise ValueError(f"Workers × threads must not exceed {cpu_count} logical CPUs")
    p["effective_workers"] = min(requested, point_count)
    p["effective_chunk"] = min(p["chunk_size"], max(1, point_count // p["effective_workers"]))
    p["gpu_workers"] = int(p["mode"] != MODES[0])
    if p["require_gpu"] and not p["gpu_workers"]:
        raise ValueError("Require GPU work is incompatible with CPU-only mode")
    return p
