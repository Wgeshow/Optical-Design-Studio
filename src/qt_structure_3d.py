"""Bounded 3D inspection of shared geometry; simulation tables are never altered."""
from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure
from matplotlib.path import Path
from matplotlib.colors import to_rgb
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from model import PAT_COLS
from structure_builder import rows
from structure_preview import clip_polygon, layer_positions, normalize_region, periodic_centers, region_polygon


def material_grid(layer, patterns, ax, ay, cells, resolution):
    """Sample periodic regions in table order, matching the 2D material overlay."""
    xs = np.linspace(-cells*ax/2, cells*ax/2, resolution+1)
    ys = np.linspace(-cells*ay/2, cells*ay/2, resolution+1)
    xx, yy = np.meshgrid((xs[:-1]+xs[1:])/2, (ys[:-1]+ys[1:])/2)
    points = np.column_stack((xx.ravel(), yy.ravel()))
    grid = np.full((resolution, resolution), str(layer['material']), dtype=object)
    window = (xs[0], xs[-1], ys[0], ys[-1])
    for region in patterns:
        if region['layer'] != layer['name']:
            continue
        for center in periodic_centers(region, ax, ay, window):
            polygon = region_polygon(region, center)
            mask = Path(polygon).contains_points(points).reshape(grid.shape)
            grid[mask] = region['material']
    return xs, ys, grid


def geometry_figure_3d(layers, patterns, selected, lattice_x, lattice_y, cells=1,
                       view=None):
    """Draw open air holes and material interfaces with a bounded surface mesh.

    Top and bottom surfaces are sampled; vertical dimensions remain exact. Air
    regions are omitted so through-holes remain visible from any viewing angle.
    Semi-infinite media are contextual planes, never presented as finite slabs.
    """
    from qt_structure import _color
    ax, ay = float(lattice_x), float(lattice_y)
    if not np.isfinite([ax, ay]).all() or min(ax, ay) <= 0:
        raise ValueError('Lattice periods must be greater than zero.')
    cells = max(1, min(7, int(cells)))
    stack, total, pad = layer_positions(layers, max(ax, ay))
    finite = [layer for layer in stack if not layer['halfspace']]
    # At most approximately 90,000 quads, including material interfaces.
    resolution = max(2, min(56, int((15000/max(1, len(finite)))**.5)))
    regions = [normalize_region(raw) for raw in rows(patterns, PAT_COLS)]
    fig = Figure(figsize=(8.4, 4.8))
    fig.subplots_adjust(left=.02, right=.86, bottom=.14, top=.96)
    axis = fig.add_subplot(111, projection='3d')
    face_count = 0
    all_faces, all_colors = [], []
    for layer in finite:
        xs, ys, grid = material_grid(layer, regions, ax, ay, cells, resolution)
        z0, z1 = layer['z0'], layer['z1']
        faces, colors = [], []
        for j in range(resolution):
            for i in range(resolution):
                material = str(grid[j, i])
                if material.lower() in ('air', 'vacuum', 'air / vacuum'):
                    continue
                x0, x1, y0, y1 = xs[i], xs[i+1], ys[j], ys[j+1]
                cell_faces = [[(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0)],
                              [(x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]]
                if i == 0 or grid[j, i-1] != material:
                    cell_faces.append([(x0,y0,z0),(x0,y1,z0),(x0,y1,z1),(x0,y0,z1)])
                if i == resolution-1 or grid[j, i+1] != material:
                    cell_faces.append([(x1,y0,z0),(x1,y1,z0),(x1,y1,z1),(x1,y0,z1)])
                if j == 0 or grid[j-1, i] != material:
                    cell_faces.append([(x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1)])
                if j == resolution-1 or grid[j+1, i] != material:
                    cell_faces.append([(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)])
                faces.extend(cell_faces)
                base = to_rgb(_color(material))
                # Directional shading distinguishes the floor of an air hole
                # from its side walls without a new rendering dependency.
                colors.extend([base, tuple(c*.86 for c in base)] +
                              [tuple(c*.68 for c in base)]*(len(cell_faces)-2))
        if faces:
            all_faces.extend(faces)
            all_colors.extend(colors)
            face_count += len(faces)
        # Exact rims keep small regions visible even when the bounded surface
        # sampling cannot resolve them. Their contours use the same 2D polygons.
        outline_count = 0
        for region in regions:
            if region['layer'] != layer['name']:
                continue
            for center in periodic_centers(region, ax, ay, (xs[0],xs[-1],ys[0],ys[-1])):
                outline_count += 1
                if outline_count > 2000:
                    break
                polygon = clip_polygon(region_polygon(region, center), (xs[0],xs[-1],ys[0],ys[-1]))
                if len(polygon) < 3:
                    continue
                contour = np.asarray([*polygon, polygon[0]])
                axis.plot(contour[:,0], contour[:,1], [z0]*len(contour),
                          color='#54738d', linewidth=.9)
        if layer['name'] == selected:
            for z in (z0, z1):
                axis.plot([xs[0],xs[-1],xs[-1],xs[0],xs[0]],
                          [ys[0],ys[0],ys[-1],ys[-1],ys[0]], [z]*5,
                          color='#21a79b', linewidth=1.8)
    xmin, xmax, ymin, ymax = -cells*ax/2, cells*ax/2, -cells*ay/2, cells*ay/2
    # One collection sorts faces across all layers. Separate layer collections
    # can incorrectly paint an entire lower slab over holes in an upper slab.
    if all_faces:
        axis.add_collection3d(Poly3DCollection(all_faces, facecolors=all_colors,
                                              edgecolors='none', antialiased=False, alpha=1.0))
    # Infinite media are labels, not polygons that could cap an open air hole.
    axis.text2D(.02, .96, f"Above: {stack[0]['name']} · {stack[0]['material']} · ∞",
                transform=axis.transAxes, fontsize=8)
    axis.text2D(.02, .90, f"Below: {stack[-1]['name']} · {stack[-1]['material']} · ∞",
                transform=axis.transAxes, fontsize=8)
    axis.set(xlim=(xmin,xmax), ylim=(ymin,ymax), zlim=(total+pad*.25,-pad*.25),
             xlabel='x (µm)', ylabel='y (µm)', zlabel='Depth z (µm)',
             title='')
    axis.set_box_aspect((cells*ax,cells*ay,max(total, min(ax,ay)*.15)), zoom=1.08)
    for coordinate in (axis.xaxis, axis.yaxis, axis.zaxis):
        coordinate.labelpad = 1
    axis.view_init(*(view or (25, -55)))
    axis.mouse_init(rotate_btn=1, pan_btn=2, zoom_btn=3)
    axis.tick_params(labelsize=8)
    fig._s4_geometry = {'stack': stack, 'selected': selected, 'warnings': [],
                        'total_um': total, 'three_d': axis, 'face_count': face_count,
                        'resolution': resolution}
    return fig
