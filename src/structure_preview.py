"""Geometry-only plan and section views of the current S4 layer tables.

The renderer never invokes S4 or changes the project. Coordinates are micrometres;
z increases from the incident medium down through the finite layers.
"""
import hashlib
import html
import math


LAYER_COLUMNS = ("Name", "Thickness_um", "Material")
PATTERN_COLUMNS = ("Shape", "Layer", "Material", "CenterX_um", "CenterY_um",
                   "SizeX_um", "SizeY_um", "Angle_deg")
MAX_LAYERS = 5000
MAX_REGIONS = 5000
MAX_COPIES = 2048
MAX_POLYGONS = 16000


def _records(value, columns):
    """Accept the table representations used by Gradio and project files."""
    if value is None:
        return []
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if hasattr(value, "to_dict"):
        return value.to_dict("records")
    if isinstance(value, dict):
        if "data" in value:
            headers = value.get("headers") or columns
            return [dict(zip(headers, row)) for row in value["data"]]
        return [value]
    return [dict(row) if isinstance(row, dict) else dict(zip(columns, row)) for row in value]


def _text(value, fallback=""):
    if value is None or str(value).strip().lower() in ("", "nan", "none"):
        return fallback
    return str(value).strip()


def _number(value, name, default=None, positive=False):
    if _text(value) == "" and default is not None:
        value = default
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be a number.") from None
    if not math.isfinite(value) or abs(value) > 1e12:
        raise ValueError(f"{name} must be a finite, practical dimension.")
    if positive and value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def normalize_region(row):
    """Return geometry using the same full-width/radius convention as S4."""
    shape = _text(row.get("Shape")).lower()
    if shape not in ("circle", "ellipse", "rectangle"):
        raise ValueError("Choose circle, ellipse, or rectangle for each region.")
    sx = _number(row.get("SizeX_um"), "Region X size", positive=True)
    sy = sx if shape == "circle" else _number(row.get("SizeY_um"), "Region Y size", positive=True)
    return dict(shape=shape, layer=_text(row.get("Layer")), material=_text(row.get("Material"), "Unassigned"),
                cx=_number(row.get("CenterX_um"), "Region centre X", 0),
                cy=_number(row.get("CenterY_um"), "Region centre Y", 0),
                sx=sx, sy=sy, angle=_number(row.get("Angle_deg"), "Region rotation", 0) % 360)


def region_extents(region):
    """Axis-aligned half extents of a rotated region."""
    sx, sy = region["sx"], region["sy"]
    if region["shape"] == "circle":
        return sx, sx
    c, s = math.cos(math.radians(region["angle"])), math.sin(math.radians(region["angle"]))
    if region["shape"] == "rectangle":
        return (abs(sx*c) + abs(sy*s))/2, (abs(sx*s) + abs(sy*c))/2
    return math.hypot(sx*c, sy*s), math.hypot(sx*s, sy*c)


def section_interval(region, cut_y, center=None):
    """Exact x interval where a horizontal line intersects a region, or None.

    Ellipse radii are SizeX/SizeY; rectangle sizes are full widths. Rotation is
    counterclockwise about the region centre, matching S4's in-plane convention.
    """
    cx, cy = center if center is not None else (region["cx"], region["cy"])
    dy = cut_y - cy
    sx, sy = region["sx"], region["sy"]
    if region["shape"] == "circle":
        if abs(dy) > sx:
            return None
        half = sx * math.sqrt(max(0., 1 - (dy/sx)**2))
        return cx-half, cx+half
    c, s = math.cos(math.radians(region["angle"])), math.sin(math.radians(region["angle"]))
    if region["shape"] == "ellipse":
        extent_y = math.hypot(sx*s, sy*c)
        if abs(dy) > extent_y:
            return None
        centre = c*s*(sx*sx - sy*sy)*dy/(extent_y*extent_y)
        half = sx*sy/extent_y * math.sqrt(max(0., 1 - (dy/extent_y)**2))
        return cx+centre-half, cx+centre+half
    lo, hi = -math.inf, math.inf
    for coefficient, offset, halfwidth in ((c, s*dy, sx/2), (-s, c*dy, sy/2)):
        if abs(coefficient) < 1e-14:
            if abs(offset) > halfwidth + 1e-12*max(sx, sy):
                return None
        else:
            a, b = (-halfwidth-offset)/coefficient, (halfwidth-offset)/coefficient
            lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
            if lo > hi + 1e-12*max(sx, sy):
                return None
    if lo > hi:
        lo = hi = (lo+hi)/2
    return cx+lo, cx+hi


def periodic_centers(region, lattice_x, lattice_y, window, limit=MAX_COPIES):
    """Replicas intersecting (xmin, xmax, ymin, ymax), including wrapped edges.

    Region centres are reduced modulo the lattice first, so an imported centre
    far outside the base cell does not require traversing irrelevant cells.
    """
    xmin, xmax, ymin, ymax = window
    ex, ey = region_extents(region)
    cx = (region["cx"] + lattice_x/2) % lattice_x - lattice_x/2
    cy = (region["cy"] + lattice_y/2) % lattice_y - lattice_y/2
    edges = ((xmin-cx-ex)/lattice_x, (xmax-cx+ex)/lattice_x,
             (ymin-cy-ey)/lattice_y, (ymax-cy+ey)/lattice_y)
    if not all(math.isfinite(value) for value in edges):
        raise ValueError("A region spans too many periods to preview. Reduce its size or increase the lattice spacing.")
    ix0, ix1, iy0, iy1 = math.ceil(edges[0]), math.floor(edges[1]), math.ceil(edges[2]), math.floor(edges[3])
    if (ix1-ix0+1)*(iy1-iy0+1) > limit:
        raise ValueError("A region spans too many periods to preview. Reduce its size or increase the lattice spacing.")
    return [(cx+i*lattice_x, cy+j*lattice_y)
            for i in range(ix0, ix1+1) for j in range(iy0, iy1+1)]


def region_polygon(region, center=None, points=80):
    cx, cy = center if center is not None else (region["cx"], region["cy"])
    sx, sy = region["sx"], region["sy"]
    if region["shape"] == "rectangle":
        local = [(-sx/2, -sy/2), (sx/2, -sy/2), (sx/2, sy/2), (-sx/2, sy/2)]
    else:
        local = [(sx*math.cos(2*math.pi*i/points), sy*math.sin(2*math.pi*i/points)) for i in range(points)]
    angle = 0 if region["shape"] == "circle" else region["angle"]
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [(cx+c*x-s*y, cy+s*x+c*y) for x, y in local]


def clip_polygon(vertices, window):
    """Sutherland-Hodgman clipping keeps oversized/crossing regions in view."""
    result = list(vertices)
    for axis, boundary, sign in ((0, window[0], 1), (0, window[1], -1),
                                 (1, window[2], 1), (1, window[3], -1)):
        previous_result, result = result, []
        if not previous_result:
            break
        previous = previous_result[-1]
        prev_inside = sign*(previous[axis]-boundary) >= -1e-14
        for current in previous_result:
            inside = sign*(current[axis]-boundary) >= -1e-14
            if inside != prev_inside:
                denominator = current[axis]-previous[axis]
                fraction = (boundary-previous[axis])/denominator
                intersection = tuple(previous[k]+fraction*(current[k]-previous[k]) for k in (0, 1))
                result.append(intersection)
            if inside:
                result.append(current)
            previous, prev_inside = current, inside
    return result


def layer_positions(value, lateral_scale=1.):
    """Thickness-positioned layers, with finite display pads for half-spaces."""
    rows = _records(value, LAYER_COLUMNS)
    if len(rows) < 3:
        raise ValueError("Add an incident medium, at least one device layer, and an exit medium to see the structure.")
    if len(rows) > MAX_LAYERS:
        raise ValueError(f"The interactive structure preview supports up to {MAX_LAYERS:,} layers.")
    total, stack, names = 0., [], set()
    for index, row in enumerate(rows):
        name = _text(row.get("Name"))
        if not name or name in names:
            raise ValueError("Give each layer a unique name to see the structure.")
        names.add(name)
        thickness = _number(row.get("Thickness_um"), f"{name} thickness", default=0)
        if thickness < 0:
            raise ValueError("Layer thickness cannot be negative.")
        outer = index in (0, len(rows)-1)
        if outer and thickness != 0:
            raise ValueError("Set the first and last layer thicknesses to zero for the semi-infinite media.")
        stack.append(dict(name=name, material=_text(row.get("Material"), "Unassigned"),
                          thickness=thickness, z0=total, z1=total+thickness,
                          halfspace="incident" if index == 0 else "exit" if index == len(rows)-1 else None))
        if not outer:
            total += thickness
    pad = max(total*.12, lateral_scale*.22, .001)
    stack[0].update(z0=-pad, z1=0.)
    stack[-1].update(z0=total, z1=total+pad)
    return stack, total, pad


def material_color(name):
    """Stable colours across geometry changes and interpreter sessions."""
    if _text(name).lower() in ("air", "vacuum", "air / vacuum", "air/vacuum"):
        return "#ffffff"
    digest = hashlib.sha256(_text(name).encode("utf-8")).digest()
    return f"hsl({int.from_bytes(digest[:2], 'big') % 360}, {48+digest[2] % 16}%, {70+digest[3] % 9}%)"


def _rectangle(x0, x1, y0, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _empty_figure(message):
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_annotation(text=html.escape(message), x=.5, y=.5, xref="paper", yref="paper", showarrow=False)
    fig.update_layout(height=480, template="plotly_white", margin=dict(l=20, r=20, t=30, b=20),
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      meta=dict(preview_kind="structure_geometry", error=message))
    return fig


def build_structure_figure(layers, patterns, selected, lattice_x, lattice_y, cells=3, cut_y=0.0):
    """Return an interactive, geometry-only XY plan / XZ section Plotly figure.

    All inputs use micrometres. ``cells`` is the number of periods per plan-view
    axis (1–7). The section repeats along x; an arbitrary cut_y is displayed at
    its equivalent position in the central periodic cell. Invalid transient
    table edits produce an explanatory annotation instead of an exception.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    try:
        ax = _number(lattice_x, "Lattice X", positive=True)
        ay = _number(lattice_y, "Lattice Y", positive=True)
        requested_cells = _number(cells, "Displayed periods", positive=True)
        if not requested_cells.is_integer():
            raise ValueError("Choose a whole number of displayed periods.")
        cells = max(1, min(7, int(requested_cells)))
        cut_y = _number(cut_y, "Section Y")
        cut_display = (cut_y+ay/2) % ay-ay/2
        stack, total, pad = layer_positions(layers, max(ax, ay))
        raw_regions = _records(patterns, PATTERN_COLUMNS)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return _empty_figure(str(exc))

    warnings = []
    if requested_cells != cells:
        warnings.append("Preview limited to seven periods per axis.")
    by_name = {layer["name"]: layer for layer in stack}
    selected = _text(selected)
    if selected not in by_name:
        selected = stack[1]["name"]
    selected_layer = by_name[selected]
    regions = []
    invalid = 0
    for row in raw_regions[:MAX_REGIONS]:
        if not any(_text(row.get(key)) for key in ("Shape", "Layer", "Material")):
            continue
        try:
            region = normalize_region(row)
            if region["layer"] not in by_name:
                raise ValueError("A region refers to an unknown layer.")
            regions.append(region)
        except (ValueError, TypeError):
            invalid += 1
    if invalid:
        warnings.append(f"{invalid} incomplete or invalid region(s) omitted; complete their geometry to display them.")
    if len(raw_regions) > MAX_REGIONS:
        warnings.append(f"Preview includes the first {MAX_REGIONS:,} regions.")

    x0, x1, y0, y1 = -cells*ax/2, cells*ax/2, -cells*ay/2, cells*ay/2
    window = (x0, x1, y0, y1)
    title_selected = html.escape(selected[:50])
    cut_label = f"y = {cut_y:g} µm"
    if not math.isclose(cut_y, cut_display, rel_tol=1e-12, abs_tol=1e-12*ay):
        cut_label += f" (≡ {cut_display:g} µm)"
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=.115,
                        subplot_titles=(f"Plan · {title_selected}", f"Section · {cut_label}"))
    seen_materials = set()
    polygon_count = 0
    vertex_count = 0
    limited = False

    def add_polygons(polygons, material, descriptions, column, name=None):
        nonlocal polygon_count, vertex_count, limited
        xs, ys, texts = [], [], []
        for vertices, description in zip(polygons, descriptions):
            if len(vertices) < 3:
                continue
            if polygon_count >= MAX_POLYGONS or vertex_count+len(vertices) > 250000:
                limited = True
                break
            polygon_count += 1
            vertex_count += len(vertices)
            closed = list(vertices) + [vertices[0]]
            xs.extend([v[0] for v in closed] + [None])
            ys.extend([v[1] for v in closed] + [None])
            texts.extend([description]*(len(closed)+1))
        if not xs:
            return
        label = html.escape(material)
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", fill="toself",
                                fillcolor=material_color(material), line=dict(color="#526477", width=.7),
                                name=name or label, legendgroup=material,
                                showlegend=material not in seen_materials,
                                text=texts, hovertemplate="%{text}<extra></extra>"), row=1, col=column)
        seen_materials.add(material)

    def layer_description(layer):
        label = f"<b>{html.escape(layer['name'])}</b><br>{html.escape(layer['material'])}"
        if layer["halfspace"]:
            return label + f"<br>{layer['halfspace'].capitalize()} medium · semi-infinite (display pad only)"
        return label + f"<br>Thickness: {layer['thickness']:g} µm<br>z: {layer['z0']:g} to {layer['z1']:g} µm"

    add_polygons([_rectangle(x0, x1, y0, y1)], selected_layer["material"],
                 [layer_description(selected_layer)], 1)
    # Non-overlapping layer bases can be batched by material, keeping very large
    # stacks responsive. Transparent centre markers retain per-layer hover data.
    base_groups = {}
    for layer in stack:
        group = base_groups.setdefault(layer["material"], ([], []))
        group[0].append(_rectangle(x0, x1, layer["z0"], layer["z1"]))
        group[1].append(layer_description(layer))
    for material, (polygons, descriptions) in base_groups.items():
        add_polygons(polygons, material, descriptions, 2)

    # Preserve region order within each layer (nested materials can overpaint
    # their enclosing regions); batch all periodic copies of one region.
    previewed_regions = 0
    for region in regions:
        if limited:
            break
        layer = by_name[region["layer"]]
        description = (f"<b>{html.escape(region['layer'])} · {region['shape']}</b>"
                       f"<br>{html.escape(region['material'])}"
                       f"<br>{'Radius' if region['shape'] == 'circle' else 'Radii' if region['shape'] == 'ellipse' else 'Full widths'}: "
                       f"{region['sx']:g}" + ("" if region["shape"] == "circle" else f" × {region['sy']:g}")
                       + f" µm<br>Rotation: {region['angle']:g}°")
        try:
            if region["layer"] == selected:
                top_polygons = [clip_polygon(region_polygon(region, center), window)
                                for center in periodic_centers(region, ax, ay, window)]
                add_polygons(top_polygons, region["material"], [description]*len(top_polygons), 1)
            side_polygons = []
            for center in periodic_centers(region, ax, ay, (x0, x1, cut_display, cut_display)):
                interval = section_interval(region, cut_display, center)
                if interval is None:
                    continue
                left, right = max(x0, interval[0]), min(x1, interval[1])
                if right > left and layer["z1"] > layer["z0"]:
                    side_polygons.append(_rectangle(left, right, layer["z0"], layer["z1"]))
            add_polygons(side_polygons, region["material"], [description]*len(side_polygons), 2)
            previewed_regions += 1
        except ValueError as exc:
            message = str(exc)
            if message not in warnings:
                warnings.append(message)

    # A centred, dashed cell outline and section line make periodic wrapping
    # explicit. These decorations never alter the underlying model geometry.
    fig.add_shape(type="rect", x0=-ax/2, x1=ax/2, y0=-ay/2, y1=ay/2,
                  line=dict(color="#334155", width=2, dash="dash"), row=1, col=1)
    fig.add_shape(type="line", x0=x0, x1=x1, y0=cut_display, y1=cut_display,
                  line=dict(color="#0f766e", width=2, dash="dot"), row=1, col=1)
    fig.add_shape(type="rect", x0=x0, x1=x1,
                  y0=selected_layer["z0"], y1=selected_layer["z1"],
                  line=dict(color="#0f766e", width=3), row=1, col=2)
    for boundary in (0, total):
        fig.add_shape(type="line", x0=x0, x1=x1, y0=boundary, y1=boundary,
                      line=dict(color="#334155", width=1.5, dash="dash"), row=1, col=2)
    fig.add_trace(go.Scatter(x=[x0+.07*(x1-x0)]*len(stack),
                            y=[(layer["z0"]+layer["z1"])/2 for layer in stack],
                            mode="markers", marker=dict(size=18, color="rgba(0,0,0,0)"),
                            text=[layer_description(layer) for layer in stack],
                            hovertemplate="%{text}<extra></extra>", name="Layer details",
                            showlegend=False), row=1, col=2)
    for layer in (stack[0], selected_layer, stack[-1]):
        if layer is selected_layer and layer["halfspace"]:
            continue
        label = html.escape(layer["name"][:32])
        if layer["halfspace"]:
            label += " · ∞"
        fig.add_annotation(x=x0+.025*(x1-x0), y=(layer["z0"]+layer["z1"])/2,
                           text=label, showarrow=False, xanchor="left", font=dict(size=10, color="#17283d"),
                           bgcolor="rgba(255,255,255,.8)", row=1, col=2)
    if limited:
        warnings.append("Preview detail limit reached; reduce displayed periods or regions to show all geometry.")
    notes = "Dashed box: one unit cell · Dotted line: section cut · ∞: display pads for semi-infinite media"
    notes += "<br>Geometry only; no electric field. Section axes scale independently; layer thicknesses retain their proportions."
    if warnings:
        notes += "<br><b>" + " ".join(html.escape(w) for w in warnings[:3]) + "</b>"
    fig.add_annotation(text=notes, x=0, y=-.23, xref="paper", yref="paper", xanchor="left",
                       yanchor="top", align="left", showarrow=False, font=dict(size=10, color="#475569"))
    fig.update_xaxes(title_text="x (µm)", range=[x0, x1], constrain="domain", zeroline=False, row=1, col=1)
    fig.update_yaxes(title_text="y (µm)", range=[y0, y1], scaleanchor="x", scaleratio=1,
                     constrain="domain", zeroline=False, row=1, col=1)
    fig.update_xaxes(title_text="x (µm)", range=[x0, x1], zeroline=False, row=1, col=2)
    fig.update_yaxes(title_text="Depth z (µm)", range=[total+pad, -pad], zeroline=False, row=1, col=2)
    fig.update_layout(height=480 if not warnings else 515, template="plotly_white",
                      paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", font=dict(family="Arial, sans-serif", color="#334155"),
                      margin=dict(l=55, r=24, t=50, b=135 if warnings else 115),
                      legend=dict(orientation="h", yanchor="bottom", y=1.11, x=0, font=dict(size=10)),
                      hovermode="closest", dragmode="zoom",
                      uirevision=f"{selected}:{total}:{ax}:{ay}:{cells}",
                      meta=dict(preview_kind="structure_geometry", selected_layer=selected,
                                total_thickness_um=total, cells=cells, cut_y_um=cut_y,
                                display_cut_y_um=cut_display, layer_count=len(stack),
                                region_count=len(regions), previewed_regions=previewed_regions,
                                halfspace_pad_um=pad, warnings=warnings))
    return fig
