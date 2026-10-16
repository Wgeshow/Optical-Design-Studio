"""Editable periodic planar mesh extruded with a conforming three-tet split.

Gmsh is needed only in the selected optional Python runtime. Coordinates are
micrometres at this boundary and centimetres in the transport weak form.
"""
import math
import numpy as np


def build(cfg):
    import gmsh
    width, depth = cfg['period_um']
    options = cfg['mesh']
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.model.add('editable_periodic_transport')
        geo = gmsh.model.geo
        corners = [geo.addPoint(x, y, 0, options['xy_size_um']) for x, y in
                   [(-width/2, -depth/2), (width/2, -depth/2), (width/2, depth/2), (-width/2, depth/2)]]
        edges = [geo.addLine(corners[i], corners[(i+1)%4]) for i in range(4)]
        for edge in edges:
            geo.mesh.setTransfiniteCurve(edge, options['edge_segments']+1)
        outer = geo.addCurveLoop(edges)
        loops = []
        for shape in cfg['inclusions']:
            if shape['shape'] == 'circle':
                cx, cy = shape['center_um']; radius = shape['radius_um']
                center = geo.addPoint(cx, cy, 0, options['xy_size_um'])
                points = [geo.addPoint(cx+radius*math.cos(t), cy+radius*math.sin(t), 0, options['xy_size_um'])
                          for t in np.arange(4)*math.pi/2]
                lines = [geo.addCircleArc(points[i], center, points[(i+1)%4]) for i in range(4)]
                for line in lines:
                    geo.mesh.setTransfiniteCurve(line, options['circle_segments']//4+1)
            else:
                points = [geo.addPoint(x, y, 0, options['xy_size_um']) for x, y in shape['vertices_um']]
                lines = [geo.addLine(points[i], points[(i+1)%len(points)]) for i in range(len(points))]
            loops.append(geo.addCurveLoop(lines))
        surfaces = [geo.addPlaneSurface([outer]+loops)]+[geo.addPlaneSurface([loop]) for loop in loops]
        geo.synchronize()
        tx = [1,0,0,width, 0,1,0,0, 0,0,1,0, 0,0,0,1]
        ty = [1,0,0,0, 0,1,0,depth, 0,0,1,0, 0,0,0,1]
        gmsh.model.mesh.setPeriodic(1, [edges[1]], [edges[3]], tx)
        gmsh.model.mesh.setPeriodic(1, [edges[2]], [edges[0]], ty)
        gmsh.model.mesh.generate(2)
        tags, coordinates, _ = gmsh.model.mesh.getNodes()
        coordinates = np.asarray(coordinates).reshape(-1, 3)
        lookup = {int(tag): i for i, tag in enumerate(tags)}
        triangles, regions = [], []
        for part, surface in enumerate(surfaces):
            types, _, connections = gmsh.model.mesh.getElements(2, surface)
            for element, connection in zip(types, connections):
                if element != 2:
                    raise ValueError('The planar mesh must contain only first-order triangles.')
                rows = np.asarray([lookup[int(tag)] for tag in connection]).reshape(-1, 3)
                triangles.append(rows); regions.extend([part]*len(rows))
        triangles = np.concatenate(triangles)
        used = np.unique(triangles); inverse = np.full(len(coordinates), -1)
        inverse[used] = np.arange(len(used))
        base, xy = inverse[triangles], coordinates[used, :2]
    finally:
        gmsh.finalize()
    # Canonical ordering makes prism diagonals agree on both periodic faces.
    canonical = xy.copy()
    tolerance = min(width, depth)*1e-8
    for axis, length in enumerate((width, depth)):
        canonical[np.isclose(canonical[:, axis], length/2, rtol=0, atol=tolerance), axis] = -length/2
    _, rank = np.unique(np.round(canonical/tolerance).astype(np.int64), axis=0, return_inverse=True)
    base = np.take_along_axis(base, np.argsort(rank[base], axis=1), axis=1)
    planar = xy[base]
    areas = abs((planar[:,1,0]-planar[:,0,0])*(planar[:,2,1]-planar[:,0,1])
                -(planar[:,2,0]-planar[:,0,0])*(planar[:,1,1]-planar[:,0,1]))/2
    inclusion_checks = []
    for index,shape in enumerate(cfg['inclusions'],1):
        measured=float(areas[np.asarray(regions)==index].sum())
        if shape['shape']=='circle':expected_area=math.pi*shape['radius_um']**2
        else:
            vertices=np.asarray(shape['vertices_um']);following=np.roll(vertices,-1,axis=0)
            expected_area=abs(np.sum(vertices[:,0]*following[:,1]-following[:,0]*vertices[:,1]))/2
        inclusion_checks.append(dict(id=shape['id'],faceted_area_um2=measured,
            exact_area_um2=expected_area,relative_area_error=abs(measured/expected_area-1)))
    z, layer_for_step = [0.], []
    for index, layer in enumerate(cfg['layers']):
        count = max(1, math.ceil(layer['thickness_um']/options['z_max_step_um']))
        z.extend(np.linspace(z[-1], z[-1]+layer['thickness_um'], count+1)[1:])
        layer_for_step.extend([index]*count)
    estimated = len(base)*len(layer_for_step)*3
    if estimated > options['maximum_tetrahedra']:
        raise ValueError('The requested mesh exceeds maximum_tetrahedra; coarsen it or explicitly raise the budget.')
    points = np.concatenate([np.column_stack([xy, np.full(len(xy), zz)]) for zz in z])
    tets, layers, void = [], [], []
    for iz, index in enumerate(layer_for_step):
        lower = base+iz*len(xy); upper = lower+len(xy)
        blocks = [np.column_stack([lower[:,0], lower[:,1], lower[:,2], upper[:,2]]),
                  np.column_stack([lower[:,0], lower[:,1], upper[:,1], upper[:,2]]),
                  np.column_stack([lower[:,0], upper[:,0], upper[:,1], upper[:,2]])]
        tets.extend(blocks); layers.extend([index]*len(base)*3)
        void.extend(np.tile((np.asarray(regions)>0) & cfg['layers'][index]['patterned'], 3))
    tets = np.concatenate(tets)
    p = points[tets]
    determinant = np.linalg.det(np.stack([p[:,1]-p[:,0], p[:,2]-p[:,0], p[:,3]-p[:,0]], axis=2))
    if np.any(abs(determinant) <= 1e-25):
        raise ValueError('The mesh contains degenerate tetrahedra.')
    negative = determinant < 0
    tets[negative,0], tets[negative,1] = tets[negative,1].copy(), tets[negative,0].copy()
    faces = np.concatenate([tets[:, choice] for choice in ([0,1,2],[0,1,3],[0,2,3],[1,2,3])])
    unique, counts = np.unique(np.sort(faces, axis=1), axis=0, return_counts=True)
    if counts.max() > 2:
        raise ValueError('The mesh is not a conforming tetrahedral volume.')
    boundary = unique[counts == 1]; checks = []
    for axis, length in enumerate((width, depth)):
        other = [j for j in range(3) if j != axis]
        left = boundary[np.all(np.isclose(points[boundary,axis], -length/2, rtol=0, atol=tolerance), axis=1)]
        right = boundary[np.all(np.isclose(points[boundary,axis], length/2, rtol=0, atol=tolerance), axis=1)]
        def identity(rows):
            return {tuple(sorted(map(tuple, np.round(points[face][:,other]/tolerance).astype(np.int64)))) for face in rows}
        if identity(left) != identity(right):
            raise ValueError('Opposite periodic faces do not have matching triangle connectivity.')
        checks.append(dict(axis=axis, matching_triangles=len(left)))
    volume = float(abs(determinant).sum()/6)
    expected = width*depth*z[-1]
    if abs(volume/expected-1) > 1e-10:
        raise ValueError('Tetrahedral volume does not match the supplied cell.')
    return dict(points_um=points, tetrahedra=tets, layer_index=np.asarray(layers), void=np.asarray(void),
        checks=dict(nodes=len(points), tetrahedra=len(tets), volume_um3=volume,
                    expected_volume_um3=expected, periodic_faces=checks, inclusions=inclusion_checks))
