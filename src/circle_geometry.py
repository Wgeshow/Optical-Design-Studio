"""Periodic unions of circle primitives, extruded without changing vertical walls.

Canonical projects retain editable circles. Only the S4 boundary representation
is polygonized. Connected openings may cross a cell edge but may not span the
period: a material bridge must remain to the opening's own periodic copies.
"""
import math
import sys
from pathlib import Path
from functools import lru_cache
import json


def geometry_tools():
    bundled = Path(__file__).resolve().parent / 'geometry_dependencies'
    if sys.platform == 'win32' and bundled.is_dir() and str(bundled) not in sys.path:
        sys.path.insert(0, str(bundled))
    try:
        from shapely.geometry import Point, Polygon
        from shapely.ops import unary_union
        from shapely.affinity import translate
        from shapely.geometry.polygon import orient
    except ImportError as exc:
        raise RuntimeError('Circle unions require Shapely. Install requirements-geometry.txt into this Python environment.') from exc
    return Point, Polygon, unary_union, translate, orient


def wrapped_delta(value, period):
    return (value + period / 2) % period - period / 2


def circle_components(patterns, ax, ay):
    """Unwrap connected components on the periodic plane, retaining exact circles."""
    circles = [p for p in patterns if p['shape'] == 'circle']
    pending = set(range(len(circles)))
    components = []
    while pending:
        seed = min(pending)
        root = circles[seed]
        positions = {seed: (wrapped_delta(root['cx'], ax), wrapped_delta(root['cy'], ay))}
        queue = [seed]
        pending.remove(seed)
        while queue:
            i = queue.pop()
            p = circles[i]
            for j, q in enumerate(circles):
                if i == j or p['layer'] != q['layer'] or p['material'] != q['material']:
                    continue
                dx, dy = wrapped_delta(q['cx'] - p['cx'], ax), wrapped_delta(q['cy'] - p['cy'], ay)
                distance = math.hypot(dx, dy)
                if distance > p['sx'] + q['sx'] + 1e-12:
                    continue
                if abs(distance - p['sx'] - q['sx']) <= 1e-12:
                    raise ValueError('Circular boundaries touch at a point; separate them or overlap them by a finite amount.')
                position = (positions[i][0] + dx, positions[i][1] + dy)
                if j in positions:
                    if math.dist(position, positions[j]) > 1e-8:
                        raise ValueError('Connected opening spans the periodic cell; retain a material bridge.')
                else:
                    positions[j] = position
                    pending.discard(j)
                    queue.append(j)
        components.append([dict(circles[i], cx=pos[0], cy=pos[1]) for i, pos in positions.items()])
    return components


def component_polygon(component, segments=64):
    Point, _, union, _, _ = geometry_tools()
    return union([Point(p['cx'], p['cy']).buffer(p['sx'], quad_segs=segments) for p in component])


@lru_cache(maxsize=128)
def _compiled(serialized):
    model = json.loads(serialized)
    patterns = model['patterns']
    result = [p for p in patterns if p['shape'] != 'circle']
    backgrounds = {layer['name']: layer['material'] for layer in model['layers']}
    for component in circle_components(patterns, model['ax'], model['ay']):
        if len(component) == 1:
            result.append(component[0])
            continue
        polygon = component_polygon(component, model.get('circle_segments', 64))
        if polygon.geom_type != 'Polygon' or not polygon.is_valid:
            raise ValueError('Merged circles must form a valid connected opening.')
        orient = geometry_tools()[4]
        polygon = orient(polygon, sign=1.)
        first = component[0]
        result.append(dict(shape='polygon', layer=first['layer'], material=first['material'],
            vertices=list(polygon.exterior.coords)[:-1], cx=0., cy=0., angle=0.))
        # A union may surround a material island. Restore each nested island.
        for ring in polygon.interiors:
            vertices = list(ring.coords)[:-1][::-1]
            result.append(dict(shape='polygon', layer=first['layer'], material=backgrounds[first['layer']],
                vertices=vertices, cx=0., cy=0., angle=0.))
    return result


def solver_regions(model):
    # Preserve legacy ordering when circles do not merge.
    components = circle_components(model['patterns'], model['ax'], model['ay'])
    if all(len(component) == 1 for component in components):
        return model['patterns']
    error = merged_geometry_error(model)
    if error:
        raise ValueError(error)
    payload = {k: model[k] for k in ('patterns', 'layers', 'ax', 'ay')}
    payload['circle_segments'] = model.get('circle_segments', 64)
    return _compiled(json.dumps(payload, sort_keys=True))


def merged_geometry_error(model, minimum_bridge=0., minimum_neck=0.):
    """Check disconnected holes, periodic images, and finite-width joined necks."""
    try:
        components = circle_components(model['patterns'], model['ax'], model['ay'])
        polygons = [component_polygon(c) for c in components]
        translate = geometry_tools()[3]
        for i, (component, polygon) in enumerate(zip(components, polygons)):
            if polygon.geom_type != 'Polygon' or not polygon.is_valid:
                return 'Circle union is not a valid connected opening'
            if minimum_neck > 0:
                core = polygon.buffer(-minimum_neck / 2)
                if core.is_empty or core.geom_type != 'Polygon':
                    return 'Merged opening violates minimum neck width'
            for j in range(i, len(components)):
                if components[j][0]['layer'] != component[0]['layer']:
                    continue
                for ix in (-1, 0, 1):
                    for iy in (-1, 0, 1):
                        if i == j and ix == iy == 0:
                            continue
                        other = translate(polygons[j], ix * model['ax'], iy * model['ay'])
                        if polygon.intersects(other) or polygon.distance(other) < minimum_bridge - 1e-10:
                            return 'Openings overlap or violate the material bridge, including periodic neighbors'
        # Merging is only defined for circular holes. Reject ambiguous mixed overlaps.
        noncircles = [p for p in model['patterns'] if p['shape'] != 'circle']
        if noncircles and any(len(c) > 1 for c in components):
            return 'Use circle-only patterned layers for merged-circle optimization'
        return ''
    except (ValueError, RuntimeError) as exc:
        return str(exc)
