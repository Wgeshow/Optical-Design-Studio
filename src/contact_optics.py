"""Optional periodic optical pads for ideal electrical terminal footprints.

Pads are added to prepared optical models only. The finite electrostatic device
and its ideal terminal boundaries retain their original dimensions and layers.
Lengths are micrometres; circle/ellipse solver sizes are radii/semiaxes.
"""
from __future__ import annotations

import math

from device_model import geometry_vertices


def _unique_name(stem, names):
    name, suffix = stem, 2
    while name in names:
        name = f'{stem}_{suffix}'
        suffix += 1
    names.add(name)
    return name


def _ring_bars(contact):
    """Decompose an outer-minus-inner ring into four nonoverlapping bars."""
    sx, sy = contact['size_x_um'], contact['size_y_um']
    ix, iy = contact['inner_size_x_um'], contact['inner_size_y_um']
    angle = math.radians(contact['angle_deg'])
    cosine, sine = math.cos(angle), math.sin(angle)
    for x, y, width, depth in (
            (0., (sy+iy)/4, sx, (sy-iy)/2),
            (0., -(sy+iy)/4, sx, (sy-iy)/2),
            (-(sx+ix)/4, 0., (sx-ix)/2, iy),
            ((sx+ix)/4, 0., (sx-ix)/2, iy)):
        yield dict(contact, shape='rectangle',
                   cx_um=contact['cx_um']+cosine*x-sine*y,
                   cy_um=contact['cy_um']+sine*x+cosine*y,
                   size_x_um=width, size_y_um=depth)


def footprint_patterns(contact, layer_name, material_name):
    """Return native optical patterns with the exact editable footprint."""
    if contact['shape'] == 'polygon':
        return [dict(shape='polygon', layer=layer_name, material=material_name,
                     cx=0., cy=0., sx=contact['size_x_um'], sy=contact['size_y_um'],
                     angle=0., vertices=geometry_vertices(contact),
                     contact_id=contact['id'])]
    objects = _ring_bars(contact) if contact['shape'] == 'square_ring' else [contact]
    patterns = []
    for obj in objects:
        scale = .5 if obj['shape'] in ('circle', 'ellipse') else 1.
        patterns.append(dict(shape=obj['shape'], layer=layer_name, material=material_name,
                             cx=obj['cx_um'], cy=obj['cy_um'],
                             sx=obj['size_x_um']*scale,
                             sy=0. if obj['shape'] == 'circle' else obj['size_y_um']*scale,
                             angle=obj['angle_deg'], contact_id=contact['id']))
    return patterns


def _air_background(materials):
    for material in materials:
        if (material.get('model') in ('constant_nk', 'constant_eps')
                and material.get('a') == 1. and material.get('b') == 0.
                and 'epsilon_tensor' not in material):
            return material['name'], None
    name = _unique_name('Contact_air', {row['name'] for row in materials})
    return name, dict(name=name, model='constant_nk', a=1., b=0.)


def apply_contact_optics(model, device):
    """Validate then add optional top/bottom pads to a prepared optical model.

    Thickness zero disables optical geometry. Positive thickness requires an
    assigned existing optical material and an exterior top/bottom terminal.
    Contacts sharing a plane must have equal thickness. This keeps the electrical
    layer stack consecutive and avoids inventing optical geometry for buried or
    side contacts. Validation completes before this function mutates the model.
    """
    if any(row.get('contact_optical_surface') for row in model['layers']):
        raise ValueError('Contact optical geometry has already been added to this model.')
    active = [row for row in device['layers'] if row.get('enabled', True)]
    if not active:
        raise ValueError('Contact optical geometry needs an enabled device layer.')
    materials = {row['name'] for row in model['materials']}
    groups = {'top': [], 'bottom': []}
    active_ids = {row['id'] for row in active}
    for contact in device.get('contacts', []):
        if not contact.get('enabled', True) or contact['layer_id'] not in active_ids:
            continue
        value = contact.get('optical_thickness_um', 0.)
        if isinstance(value, bool):
            raise ValueError(contact['name']+': optical contact thickness must be finite and nonnegative.')
        try:
            thickness = float(value)
        except (ValueError, TypeError):
            thickness = float('nan')
        if not math.isfinite(thickness) or thickness < 0:
            raise ValueError(contact['name']+': optical contact thickness must be finite and nonnegative.')
        if thickness == 0:
            continue
        surface = contact['surface']
        exterior_id = active[0]['id'] if surface == 'top' else active[-1]['id']
        if surface not in groups or contact['layer_id'] != exterior_id:
            raise ValueError(contact['name']+': optical pads support only the top of the first enabled '
                             'device layer or the bottom of the last enabled device layer.')
        material = str(contact.get('optical_material_name') or '').strip()
        if not material or material not in materials:
            raise ValueError(contact['name']+': assign an existing optical material for the contact pad.')
        if groups[surface] and not math.isclose(thickness, groups[surface][0][1], rel_tol=0., abs_tol=1e-12):
            raise ValueError('Contacts on the '+surface+' optical plane must have the same optical thickness.')
        groups[surface].append((contact, thickness, material))
    if not any(groups.values()):
        return model
    by_device_id = {row.get('device_layer_id'): i for i, row in enumerate(model['layers'])
                    if row.get('device_layer_id')}
    for surface, index in (('top', 0), ('bottom', -1)):
        if not groups[surface]:
            continue
        device_id = active[index]['id']
        if device_id not in by_device_id:
            raise ValueError('Map the exterior electrical device layer before adding optical contact pads.')
        position = by_device_id[device_id]
        if (surface == 'top' and position != 1) or (surface == 'bottom' and position != len(model['layers'])-2):
            raise ValueError('Optical contact pads require exterior electrical layers adjacent to the optical half-spaces.')
    air_name, new_air = _air_background(model['materials'])
    names = {row['name'] for row in model['layers']}
    pads, patterns = {}, []
    for surface in ('top', 'bottom'):
        if not groups[surface]:
            continue
        name = _unique_name('Contact_'+surface, names)
        pads[surface] = dict(name=name, material=air_name,
                             thickness=groups[surface][0][1],
                             contact_optical_surface=surface,
                             contact_ids=[row[0]['id'] for row in groups[surface]])
        for contact, _, material in groups[surface]:
            patterns.extend(footprint_patterns(contact, name, material))
    if new_air:
        model['materials'].append(new_air)
    layers = model['layers']
    model['layers'] = [layers[0], *([pads['top']] if 'top' in pads else []),
                       *layers[1:-1], *([pads['bottom']] if 'bottom' in pads else []), layers[-1]]
    model['patterns'].extend(patterns)
    model.setdefault('warnings', []).append(
        'Optional contact footprints are finite periodic optical scattering pads; '
        'electrical terminals remain ideal boundary conditions without metal transport.')
    return model
