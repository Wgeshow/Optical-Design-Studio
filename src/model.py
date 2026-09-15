"""GUI-independent input validation. Geometry is um; wavelengths are nm."""
import bisect
import math
import re
from pathlib import Path

MAT_COLS = ["Name", "Model", "A", "B", "DataFile", "WavelengthUnit"]
LAYER_COLS = ["Name", "Thickness_um", "Material"]
PAT_COLS = ["Shape", "Layer", "Material", "CenterX_um", "CenterY_um", "SizeX_um", "SizeY_um", "Angle_deg"]
MODES = ("CPU only", "CPU + GPU", "GPU-assisted (one worker)")
DEFAULT_PERFORMANCE = dict(mode=MODES[0], workers=0, threads=1, gpu_device=0,
                           gpu_min_n=1024, gpu_block=256, chunk_size=8,
                           timeout_seconds=3600, require_gpu=False)


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


def sweep(start, stop, step, label, limit=200000):
    start, stop, step = number(start, label + " start"), number(stop, label + " stop"), positive(step, label + " step")
    if stop < start:
        raise ValueError(label + " stop must be >= start")
    count_float = (stop - start) / step
    if not math.isfinite(count_float) or count_float > limit:
        raise ValueError(f"{label} sweep is limited to {limit:,} points")
    count = int(math.floor(count_float + 1e-9)) + 1
    if count > limit:
        raise ValueError(f"{label} sweep is limited to {limit:,} points")
    return [start + i * step for i in range(count)]


def numeric_rows(path, unit):
    from nk_import import parse_nk
    try:
        return parse_nk(Path(path).read_text(encoding="utf-8-sig"), unit)
    except ValueError as exc:
        raise ValueError(f"{Path(path).name}: {exc}") from exc


def epsilon(material, wavelength):
    if material["model"] == "constant_eps":
        return complex(material["a"], material["b"])
    n, k = material["a"], material["b"]
    if material["model"] == "table_nk":
        table = material["table"]
        grid = material["grid"]
        index = bisect.bisect_left(grid, wavelength)
        if index == 0:
            n, k = table[0][1:]
        elif index == len(table):
            n, k = table[-1][1:]
        else:
            lo, hi = table[index - 1], table[index]
            fraction = (wavelength - lo[0]) / (hi[0] - lo[0])
            n, k = [lo[i] + fraction * (hi[i] - lo[i]) for i in (1, 2)]
    return complex(n * n - k * k, 2 * n * k)


def prepare(materials, layers, patterns, files, settings):
    """Snapshot uploads and validate before any native worker starts."""
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
        mat = dict(name=name, model=mode, a=1.0, b=0.0)
        if mode == "table_nk":
            filename = Path(str(row.get("DataFile", ""))).name
            if filename not in uploaded:
                raise ValueError(f"{name}: upload the n,k file '{filename}'")
            mat["table"] = numeric_rows(uploaded[filename], row.get("WavelengthUnit") or "nm")
            mat["grid"] = [r[0] for r in mat["table"]]
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
        wavelengths = sweep(settings["wl_start_nm"], settings["wl_stop_nm"], settings["wl_step_nm"], "Wavelength")
        points = [[i, wl, theta] for i, wl in enumerate(wavelengths)]
    elif mode == "Angle sweep":
        wl = positive(settings["fixed_wl_nm"], "Fixed wavelength")
        angles = sweep(settings["angle_start"], settings["angle_stop"], settings["angle_step"], "Angle", 361)
        points = [[i, wl, theta] for i, theta in enumerate(angles)]
    else:
        raise ValueError("Invalid sweep mode")
    if any(wl <= 0 or not -90 < theta < 90 for _, wl, theta in points):
        raise ValueError("Wavelengths must be positive and incidence angles strictly between -90 and 90 degrees")
    lo, hi = min(p[1] for p in points), max(p[1] for p in points)
    for mat in mats:
        if mat["model"] == "table_nk" and (lo < mat["grid"][0] or hi > mat["grid"][-1]):
            warnings.append(f"{mat['name']} table spans {mat['grid'][0]:g}–{mat['grid'][-1]:g} nm. Endpoint clamping is used outside it, as in v1.1. Check WavelengthUnit.")
    return dict(materials=mats, layers=layer_list, patterns=regions, ax=ax, ay=ay,
                basis=basis, phi=phi, polarization=settings["polarization"], mode=mode,
                points=points, warnings=warnings)


def performance(values, point_count, cpu_count):
    p = dict(DEFAULT_PERFORMANCE, **values)
    if point_count < 1 or cpu_count < 1:
        raise ValueError("Need at least one sweep point and one logical CPU")
    if not isinstance(p["require_gpu"], bool):
        raise ValueError("Require GPU work must be true or false")
    if p["mode"] not in MODES:
        raise ValueError("Invalid CPU/GPU mode")
    for name, minimum in (("workers", 0), ("threads", 1), ("gpu_device", 0), ("gpu_min_n", 1), ("gpu_block", 64), ("chunk_size", 1), ("timeout_seconds", 1)):
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
