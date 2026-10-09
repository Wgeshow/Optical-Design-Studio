"""Replay saved S4 phasors; no solver or learned fields are used here."""
import json
from pathlib import Path

import numpy as np
import pandas as pd


def load_volume(directory):
    directory = Path(directory)
    metadata = json.loads((directory / 'field_model.json').read_text(encoding='utf-8'))
    frame = pd.read_csv(directory / 'electric_fields.csv')
    frame = frame.loc[frame['plane'] == 'volume_samples'].copy()
    if frame.empty:
        raise ValueError('This snapshot has no volume samples. Calculate field maps first.')
    xyz = frame[['x_um', 'y_um', 'z_um']].to_numpy(dtype=float)
    fields = {}
    for prefix in ('E', 'H'):
        columns = [prefix + axis + '_' + part for axis in 'xyz' for part in ('real', 'imag')]
        if not all(c in frame for c in columns):
            if prefix == 'E':
                raise ValueError('Complex electric-field components are missing.')
            continue
        values = frame[columns].to_numpy(dtype=float).reshape(-1, 3, 2)
        fields[prefix] = values[..., 0] + 1j * values[..., 1]
    if not np.isfinite(xyz).all() or any(not np.isfinite(f).all() for f in fields.values()):
        raise ValueError('The saved volume contains nonfinite field samples.')
    return metadata, frame, xyz, fields


def vectors(fields, mode, phase_degrees):
    """S4 exp(-i omega t) convention; Poynting is time averaged."""
    if mode == 'Energy flow':
        return .5 * np.cross(fields['E'], fields['H'].conjugate()).real
    field = fields['E'] if mode in ('Ex', 'Ey', 'Ez') else fields[mode]
    result = (field * np.exp(-1j * np.deg2rad(phase_degrees))).real
    if mode in ('Ex', 'Ey', 'Ez'):
        result = result.copy()
        result[:, [i for i in range(3) if i != 'xyz'.index(mode[1])]] = 0
    return result


def amplitude(fields, mode):
    if mode == 'Energy flow':
        return np.linalg.norm(vectors(fields, mode, 0), axis=1)
    if mode in ('Ex', 'Ey', 'Ez'):
        return np.abs(fields['E'][:, 'xyz'.index(mode[1])]) ** 2
    return np.sum(np.abs(fields[mode]) ** 2, axis=1)


def visible_samples(values, minimum_percent):
    """Keep one snapshot-wide reference so layer filtering does not rescale power."""
    peak = float(np.max(values))
    cutoff = peak * minimum_percent / 100.
    return (values >= cutoff) & (values > 0), cutoff


def interaction_surface(faces, target_faces=1800):
    """Vertex-cluster an existing surface for temporary interactive display.

    Use the full mesh's vertices rather than resampling the field, so small
    visible lobes are not missed by a second, coarser field grid. Full geometry
    is retained separately and is never modified by this display operation.
    """
    faces = np.asarray(faces)
    if len(faces) <= target_faces:
        return faces
    vertices = faces.reshape(-1,3)
    lower = vertices.min(axis=0)
    span = vertices.max(axis=0)-lower
    normalized = (vertices-lower)/np.where(span>0,span,1.)
    for divisions in (16,12,9,7,5,3,2,1):
        keys = np.floor(normalized*divisions+.5).astype(np.int64)
        _, inverse = np.unique(keys,axis=0,return_inverse=True)
        counts = np.bincount(inverse)
        centers = np.column_stack([np.bincount(inverse,weights=vertices[:,i])/counts for i in range(3)])
        indices = inverse.reshape(-1,3)
        valid = (indices[:,0]!=indices[:,1]) & (indices[:,1]!=indices[:,2]) & (indices[:,0]!=indices[:,2])
        indices = indices[valid]
        _, unique = np.unique(np.sort(indices,axis=1),axis=0,return_index=True)
        reduced = centers[indices[unique]]
        if len(reduced) <= target_faces:
            return reduced
    return reduced


def field_surface(xyz, values, cutoff, resolution=24):
    """Piecewise-linear isosurface, capped at the sampled domain, using NumPy.

    Input must be one complete rectilinear layer. Interpolation is for display
    only; it neither adds simulated detail nor crosses layer interfaces.
    """
    axes = [np.unique(xyz[:,i]) for i in range(3)]
    shape = tuple(len(a) for a in axes)
    if min(shape) < 2 or np.prod(shape) != len(xyz):
        raise ValueError('Continuous shape requires a complete 3D grid in each layer.')
    indices = tuple(np.searchsorted(axes[i],xyz[:,i]) for i in range(3))
    if len(np.unique(np.ravel_multi_index(indices,shape))) != len(xyz):
        raise ValueError('Continuous shape cannot use duplicate volume samples.')
    volume = np.empty(shape)
    volume[indices] = values
    if not np.any(values > 0) or cutoff > values.max():
        return np.empty((0,3,3))
    # Bounded separable interpolation preserves the saved physical coordinates.
    fine = [np.linspace(a[0],a[-1],resolution) for a in axes]
    for axis in range(3):
        volume = np.apply_along_axis(lambda v: np.interp(fine[axis],axes[axis],v),axis,volume)
    peak = max(float(values.max()),1e-30)
    signed = volume / peak - cutoff / peak
    signed = np.where(signed == 0, 1e-12, signed)
    # Ghost cells close the surface at the data boundary; clamp vertices below.
    signed = np.pad(signed,1,constant_values=-1.)
    coordinates = [np.r_[a[0]-(a[1]-a[0])*1e-6,a,a[-1]+(a[-1]-a[-2])*1e-6] for a in fine]
    points = np.stack(np.meshgrid(*coordinates,indexing='ij'),axis=-1)
    corners = [(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,0,1),(1,0,1),(1,1,1),(0,1,1)]
    positions, scalars = [], []
    for corner in corners:
        sl = tuple(slice(c,-1 if c==0 else None) for c in corner)
        positions.append(points[sl].reshape(-1,3))
        scalars.append(signed[sl].ravel())
    positions = np.stack(positions,axis=1)
    scalars = np.stack(scalars,axis=1)
    edges = [(0,1),(0,2),(0,3),(1,2),(1,3),(2,3)]
    triangles = []
    for tetra in [(0,1,2,6),(0,2,3,6),(0,3,7,6),(0,7,4,6),(0,4,5,6),(0,5,1,6)]:
        p, s = positions[:,tetra], scalars[:,tetra]
        cases = np.sum((s>=0)*np.array([1,2,4,8]),axis=1)
        for case in range(1,15):
            selected = cases == case
            if not selected.any():
                continue
            pp, ss = p[selected], s[selected]
            inside = [i for i in range(4) if case & (1<<i)]
            outside = [i for i in range(4) if not case & (1<<i)]
            outward = pp[:,outside].mean(axis=1)-pp[:,inside].mean(axis=1)
            cross = [(a,b) for a,b in edges if bool(case & (1<<a)) != bool(case & (1<<b))]
            vertices = np.stack([pp[:,a]+(ss[:,a]/(ss[:,a]-ss[:,b]))[:,None]*(pp[:,b]-pp[:,a]) for a,b in cross],axis=1)
            if len(cross)==3:
                pieces = [vertices]
            else:
                center = vertices.mean(axis=1,keepdims=True)
                relative = vertices-center
                u = relative[:,0]
                normal = np.cross(u,relative[:,1])
                v = np.cross(normal,u)
                u /= np.maximum(np.linalg.norm(u,axis=1,keepdims=True),1e-300)
                v /= np.maximum(np.linalg.norm(v,axis=1,keepdims=True),1e-300)
                order = np.argsort(np.arctan2(np.sum(relative*v[:,None],axis=2),np.sum(relative*u[:,None],axis=2)),axis=1)
                vertices = np.take_along_axis(vertices,order[:,:,None],axis=1)
                pieces = [vertices[:,[0,1,2]],vertices[:,[0,2,3]]]
            for piece in pieces:
                normal = np.cross(piece[:,1]-piece[:,0],piece[:,2]-piece[:,0])
                flip = np.sum(normal*outward,axis=1)<0
                piece[flip] = piece[flip][:,[0,2,1]]
                triangles.append(piece)
    if not triangles:
        return np.empty((0,3,3))
    result = np.concatenate(triangles)
    for axis in range(3):
        result[:,:,axis] = np.clip(result[:,:,axis],axes[axis][0],axes[axis][-1])
    return result


def draw_geometry(ax, model):
    from structure_preview import region_polygon, periodic_centers, clip_polygon
    x, y = model['ax'] / 2, model['ay'] / 2
    window = (-x, x, -y, y)
    z = 0.
    for layer in model['layers'][1:-1]:
        top = z
        z += layer['thickness']
        if z <= top:
            continue
        for height in (top, z):
            ax.plot([-x, x, x, -x, -x], [-y, -y, y, y, -y], [height]*5, color='#879aaa', alpha=.5, lw=.7)
        for xx, yy in ((-x,-y),(x,-y),(x,y),(-x,y)):
            ax.plot([xx,xx],[yy,yy],[top,z], color='#879aaa', alpha=.5, lw=.7)
        for region in model.get('patterns', []):
            if region['layer'] != layer['name']:
                continue
            region = dict(region, sy=region['sx'] if region['shape'] == 'circle' else region['sy'])
            for center in periodic_centers(region, model['ax'], model['ay'], window):
                polygon = clip_polygon(region_polygon(dict(region, angle=np.deg2rad(region['angle'])), center), window)
                if len(polygon) < 3:
                    continue
                polygon = np.asarray(list(polygon) + [polygon[0]])
                for height in (top, z):
                    ax.plot(polygon[:,0], polygon[:,1], np.full(len(polygon),height), color='#879aaa', alpha=.7, lw=.8)
    ax.set(xlim=(-x,x), ylim=(-y,y), zlim=(z,0), xlabel='x (µm)', ylabel='y (µm)', zlabel='z (µm)')
    ax.set_box_aspect((2*x,2*y,max(z,1e-9)))
