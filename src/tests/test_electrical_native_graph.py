"""Exact topology checks against the independently assembled electrostatic FV."""
import unittest

import numpy as np
from scipy.sparse import coo_matrix

from custom_electrical_solver import build_mesh, _system
from electrical_native_graph import build_native_graph
from test_electrical_terminal_studies import resistor_device


class NativeGraphTests(unittest.TestCase):
    def graph_laplacian(self, graph):
        a, b = graph['edges'].T
        g = graph['edge_displacement_coefficient_F']
        size = len(graph['node_xyz_m'])
        return coo_matrix((np.r_[g, g, -g, -g], (np.r_[a, b, a, b], np.r_[a, b, b, a])), shape=(size, size)).tocsr()

    def assert_equivalent(self, device, library):
        mesh = build_mesh(device, library)
        expected = _system(mesh)
        graph = build_native_graph(mesh)
        matrix = self.graph_laplacian(graph)
        difference = matrix[:graph['cell_count'], :graph['cell_count']] - expected
        self.assertLess(max(abs(difference.data), default=0.), max(expected.data) * 1e-12)
        self.assertEqual(graph['cell_count'], np.prod(mesh['shape']))
        self.assertAlmostEqual(graph['node_volume_m3'].sum(), mesh['volume'].sum())
        self.assertTrue(np.all(graph['node_volume_m3'][graph['cell_count']:] == 0))
        return mesh, graph

    def test_uniform_three_dimensional_face_graph_matches_poisson(self):
        self.assert_equivalent(*resistor_device())

    def test_partial_top_contact_and_air_hole_use_actual_mesh(self):
        device, library = resistor_device()
        device['mesh'].update(nx=12, ny=10)
        layer = device['layers'][0]['id']
        device['shapes'] = [dict(id='hole', name='Actual off-center hole', layer_id=layer,
            material_id='air', operation='void', shape='circle', cx_um=.35, cy_um=.1,
            size_x_um=.35, size_y_um=.35, angle_deg=0., vertices=[], enabled=True)]
        top=next(contact for contact in device['contacts'] if contact['surface']=='top')
        top.update(shape='rectangle', size_x_um=.5, size_y_um=1.2, cx_um=-.6)
        mesh, graph = self.assert_equivalent(device, library)
        self.assertTrue(np.any(~mesh['solid']))
        mapped=next(contact for contact in mesh['contacts'] if contact['object']['id']==top['id'])
        self.assertEqual(len(graph['contacts'][top['id']]), len(mapped['ids']))

    def test_material_interface_uses_harmonic_distance_weighted_permittivity(self):
        device, library = resistor_device()
        other = dict(library[-1], id='second_dielectric', name='Second dielectric', properties=dict(epsilon_r=12., conductivity_S_m=1.))
        library.append(other)
        device['layers'].append(dict(device['layers'][0], id='second', name='Second', material_id=other['id'], thickness_um=.5))
        for contact in device['contacts']:
            contact['layer_id']='second' if contact['surface']=='bottom' else device['layers'][0]['id']
        _, graph = self.assert_equivalent(device, library)
        self.assertTrue(np.any((graph['edge_epsilon_r'] > 4) & (graph['edge_epsilon_r'] < 12)))


if __name__ == '__main__':
    unittest.main()
