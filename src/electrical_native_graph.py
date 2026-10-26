"""Exact conservative 3D finite-volume topology for native carrier transport.

The graph embeds cell centers and ideal-electrode face nodes in xyz. Native
node/edge integration measures are replaced by actual cell volumes/face areas;
the 1D Gmsh edge encoding does not reduce the physical device to one dimension.
Physics and model-validity checks belong to electrical_graph_transport.
"""
from __future__ import annotations

import numpy as np
from scipy.constants import epsilon_0


def build_native_graph(mesh):
    shape, index = mesh['shape'], mesh['index']
    size = index.size
    widths = mesh['widths']
    xyz = np.column_stack([values.ravel() for values in np.meshgrid(*mesh['axes'], indexing='ij')])
    eps = mesh['epsilon_r'].ravel()
    removed = {(min(int(a), int(b)), max(int(a), int(b)))
               for contact in mesh['contacts'] for a, b in zip(contact['ids'], contact['others']) if b >= 0}
    edge_parts, area_parts, length_parts, coefficient_parts, axis_parts = [], [], [], [], []
    for axis in range(3):
        lo, hi = [slice(None)] * 3, [slice(None)] * 3
        lo[axis], hi[axis] = slice(0, -1), slice(1, None)
        a, b = index[tuple(lo)].ravel(), index[tuple(hi)].ravel()
        ca, cb = np.unravel_index(a, shape), np.unravel_index(b, shape)
        area = np.ones(len(a))
        for other in range(3):
            if other != axis:
                area *= widths[other][ca[other]]
        da, db = widths[axis][ca[axis]] / 2, widths[axis][cb[axis]] / 2
        coefficient = epsilon_0 * area / (da / eps[a] + db / eps[b])
        keep = np.fromiter(((min(int(i), int(j)), max(int(i), int(j))) not in removed for i, j in zip(a, b)), bool, len(a))
        edge_parts.append(np.column_stack((a[keep], b[keep])))
        area_parts.append(area[keep]); length_parts.append((da + db)[keep])
        coefficient_parts.append(coefficient[keep]); axis_parts.append(np.full(np.count_nonzero(keep), axis, int))
    ghosts, adjacent, ghost_material, ghost_donor, ghost_acceptor = [], [], [], [], []
    contacts = {}
    next_index = size
    for contact in mesh['contacts']:
        ids = np.asarray(contact['ids'], int)
        other_ids = np.asarray(contact['others'], int)
        ghost_ids = np.arange(next_index, next_index + len(ids))
        next_index += len(ids)
        positions = xyz[ids].copy()
        positions[:, contact['axis']] += contact['sign'] * contact['distance']
        ghosts.append(positions); adjacent.append(ids)
        ghost_material.append(mesh['material_index'].ravel()[ids])
        ghost_donor.append(mesh['donor_cm3'].ravel()[ids]); ghost_acceptor.append(mesh['acceptor_cm3'].ravel()[ids])
        contacts[contact['object']['id']] = ghost_ids
        area = np.asarray(contact['area'])
        distance = np.asarray(contact['distance'])
        edge_parts.append(np.column_stack((ids, ghost_ids)))
        area_parts.append(area); length_parts.append(distance)
        coefficient_parts.append(epsilon_0 * eps[ids] * area / distance)
        axis_parts.append(np.full(len(ids), contact['axis'], int))
        valid = other_ids >= 0
        if np.any(valid):
            others = other_ids[valid]
            coords = np.unravel_index(others, shape)
            distance_other = widths[contact['axis']][coords[contact['axis']]] / 2
            edge_parts.append(np.column_stack((others, ghost_ids[valid])))
            area_parts.append(area[valid]); length_parts.append(distance_other)
            coefficient_parts.append(epsilon_0 * eps[others] * area[valid] / distance_other)
            axis_parts.append(np.full(len(others), contact['axis'], int))
    node_xyz = np.vstack([xyz, *ghosts])
    edges = np.vstack(edge_parts)
    lengths, areas, coefficients = (np.concatenate(values) for values in (length_parts, area_parts, coefficient_parts))
    direction = (node_xyz[edges[:, 1]] - node_xyz[edges[:, 0]]) / lengths[:, None]
    if not np.allclose(np.linalg.norm(direction, axis=1), 1., rtol=1e-12, atol=1e-12):
        raise ValueError('Native graph edge geometry disagrees with its finite-volume face distance')
    return dict(cell_count=size, shape=shape, node_xyz_m=node_xyz, edges=edges,
                edge_area_m2=areas, edge_length_m=lengths, edge_direction=direction,
                edge_axis=np.concatenate(axis_parts),
                edge_displacement_coefficient_F=coefficients,
                edge_epsilon_r=coefficients * lengths / (epsilon_0 * areas),
                node_volume_m3=np.r_[mesh['volume'].ravel(), np.zeros(next_index - size)],
                node_material_index=np.r_[mesh['material_index'].ravel(), *ghost_material],
                donor_cm3=np.r_[mesh['donor_cm3'].ravel(), *ghost_donor],
                acceptor_cm3=np.r_[mesh['acceptor_cm3'].ravel(), *ghost_acceptor],
                ghost_adjacent_cell=np.concatenate(adjacent), contacts=contacts,
                ghost_graph_indices=np.arange(size, next_index),
                contact_objects={contact['object']['id']: contact['object'] for contact in mesh['contacts']})


def create_native_graph(ds, name, graph):
    """Create a native branched graph and report its reorder maps in cm units."""
    contacts = list(graph['contacts'])
    coordinates = graph['node_xyz_m'] * 100.
    elements = []
    for a, b in graph['edges']:
        elements.extend((1, 0, int(a), int(b)))
    for tag, contact in enumerate(contacts, start=1):
        for node in graph['contacts'][contact]:
            elements.extend((0, tag, int(node)))
    ds.create_gmsh_mesh(mesh=name, coordinates=coordinates.ravel().tolist(), elements=elements,
                        physical_names=['body', *contacts])
    ds.add_gmsh_region(mesh=name, gmsh_name='body', region='body', material='EditableDevice')
    for contact in contacts:
        ds.add_gmsh_contact(mesh=name, gmsh_name=contact, name=contact, region='body', material='IdealElectrode')
    ds.finalize_mesh(mesh=name)
    ds.create_device(mesh=name, device=name)
    actual = np.column_stack([ds.get_node_model_values(device=name, region='body', name=axis) for axis in ('x', 'y', 'z')])
    lookup = {tuple(row): i for i, row in enumerate(coordinates)}
    if len(lookup) != len(coordinates):
        raise ValueError('Native graph contains coincident node coordinates; transport topology is ambiguous')
    try:
        native_to_graph = np.array([lookup[tuple(row)] for row in actual], int)
    except KeyError:
        raise RuntimeError('Native graph altered a node coordinate; cannot align physical properties safely') from None
    if len(native_to_graph) != len(coordinates) or len(set(native_to_graph)) != len(coordinates):
        raise RuntimeError('Native graph merged or lost a finite-volume/ideal-contact node')
    graph_to_native = np.empty(len(native_to_graph), int)
    graph_to_native[native_to_graph] = np.arange(len(native_to_graph))
    ds.node_solution(device=name, region='body', name='GraphIndex')
    ds.set_node_values(device=name, region='body', name='GraphIndex', values=native_to_graph.astype(float).tolist())
    ds.edge_from_node_model(device=name, region='body', node_model='GraphIndex')
    a = np.asarray(ds.get_edge_model_values(device=name, region='body', name='GraphIndex@n0'), int)
    b = np.asarray(ds.get_edge_model_values(device=name, region='body', name='GraphIndex@n1'), int)
    edges = np.column_stack((a, b))
    edge_lookup = {(min(int(i), int(j)), max(int(i), int(j))): n for n, (i, j) in enumerate(graph['edges'])}
    native_edge_to_graph = np.array([edge_lookup[(min(int(i), int(j)), max(int(i), int(j)))] for i, j in edges], int)
    if len(native_edge_to_graph) != len(graph['edges']) or len(set(native_edge_to_graph)) != len(graph['edges']):
        raise RuntimeError('Native graph merged or lost a conservative face edge')
    edge_sign = np.where(a == graph['edges'][native_edge_to_graph, 0], 1., -1.)
    return dict(device=name, region='body', native_node_to_graph=native_to_graph,
                graph_node_to_native=graph_to_native, native_edge_to_graph=native_edge_to_graph,
                native_edge_graph_endpoints=edges, native_edge_direction_sign=edge_sign)
