"""Lattice, geometry and frequency-contract tests independent of optional MPB."""
import copy
import unittest

import numpy as np

from photonic_bands import control_file, k_path, parse_frequencies, prepare


def settings():
    return dict(dimension=2, lattice_vectors=[[2., 0.], [.5, 1.5]], background_epsilon=4.,
        geometry=[dict(shape='circle', center=[.2, -.1], radius=.15, epsilon=1.)],
        k_vertices=[[0., 0.], [.5, 0.], [.5, .5]], points_per_segment=2,
        num_bands=2, resolution=12, polarizations=['te', 'tm'], solver='mpb')


class PhotonicBandTests(unittest.TestCase):
    def test_basis_lengths_and_cartesian_geometry_are_preserved(self):
        prepared = prepare({}, settings())
        text = control_file(prepared, '/tmp/bands-')
        self.assertIn('(basis-size 2 1.5811388300841898 1)', text)
        self.assertIn('(basis1 (vector3 2 0 0))', text)
        self.assertIn('(center (cartesian->lattice (vector3 0.20000000000000001 -0.10000000000000001 0)))', text)
        self.assertIn('(size 1 1 no-size)', text)
        self.assertIn('(run-te)', text)
        self.assertIn('(run-tm)', text)

    def test_k_path_uses_fractional_reciprocal_and_interval_count(self):
        prepared = prepare({}, settings())
        points, distances = k_path(prepared)
        self.assertEqual(points.shape, (5, 3))
        np.testing.assert_array_equal(points[[0, 2, 4]], prepared['k_vertices'])
        lattice = np.asarray(prepared['lattice_vectors'])
        reciprocal = np.linalg.inv(lattice).T
        np.testing.assert_allclose(lattice@reciprocal.T, np.eye(3), atol=1e-15)
        self.assertAlmostEqual(distances[2], np.linalg.norm(reciprocal[0])*.5)
        self.assertAlmostEqual(distances[-1]-distances[2], np.linalg.norm(reciprocal[1])*.5)

    def test_3d_spheres_cylinders_blocks_keep_axes_and_finite_extents(self):
        cfg = settings()
        cfg.update(dimension=3, lattice_vectors=[[0., .5, .5], [.5, 0., .5], [.5, .5, 0.]],
            k_vertices=[[0., 0., 0.], [.5, 0., .5]], polarizations=['vector'], geometry=[
                dict(shape='sphere', center=[.1, .2, .3], radius=.2, epsilon=12.),
                dict(shape='cylinder', radius=.1, height=.4, axis=[1., 1., 0.], epsilon=4.),
                dict(shape='block', size=[.2, .3, .4], axes=[[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]], epsilon=2.)])
        text = control_file(prepare({}, cfg), '/tmp/3d-')
        self.assertIn('(run)', text)
        self.assertIn('(axis (cartesian->lattice (vector3 1 1 0)))', text)
        self.assertIn('(e1 (cartesian->lattice (vector3 1 0 0)))', text)
        self.assertNotIn('infinity', text)

    def test_parser_requires_complete_exact_path_and_band_count(self):
        prepared = prepare({}, settings())
        lines = []
        for polarization in prepared['polarizations']:
            lines.append(polarization+'freqs:, k index, k1, k2, k3, kmag/2pi, band 1, band 2')
            for index, point in enumerate(k_path(prepared)[0]):
                lines.append(polarization+'freqs:, '+', '.join(map(str, [index+1, *point, 0., .1, .2])))
        parsed = parse_frequencies(lines, prepared)
        self.assertEqual(parsed['te'].shape, (5, 2))
        with self.assertRaisesRegex(RuntimeError, 'complete all'):
            parse_frequencies(lines[:-1], prepared)
        broken = list(lines)
        broken[-1] += ', .3'
        with self.assertRaisesRegex(RuntimeError, 'incomplete band row'):
            parse_frequencies(broken, prepared)

    def test_no_silent_engine_or_geometry_changes(self):
        original = settings()
        prepare({}, original)
        self.assertEqual(original, settings())
        for changes in (dict(solver='unknown'), dict(lattice_vectors=[[1., 0.], [2., 0.]]),
                        dict(polarizations=['vector']), dict(resolution=1),
                        dict(geometry=[dict(shape='sphere', radius=.2, epsilon=2.)]),
                        dict(runtime={'executable': 'mpb\nother'})):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                prepare({}, dict(settings(), **changes))

    def test_explicit_grid_and_legume_inputs_preserve_physical_sampling(self):
        cfg = settings()
        cfg.pop('k_vertices')
        cfg.update(solver='legume', gmax=4., k_grid=dict(counts=[2, 3], offset=[0., 0.]),
                   gmax_levels=[3., 4., 6.], frequency_tolerance=.001)
        prepared = prepare({}, cfg)
        self.assertEqual(prepared['runtime']['mode'], 'local')
        self.assertEqual(k_path(prepared)[0].shape, (6, 3))
        self.assertEqual(prepared['gmax_levels'], [3., 4., 6.])
        self.assertEqual(prepared['sampling'], 'k_grid')
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            prepare({}, dict(cfg, k_points=[[0., 0.]]))

    def test_parameter_atlas_validates_all_variants_without_mutation(self):
        cfg = settings()
        cfg['geometry'][0]['id'] = 'hole'
        cfg['parameter_sweep'] = dict(parameters=[
            dict(id='radius', targets=[dict(object_id='hole', field='radius')], values=[.1, .2]),
            dict(id='background', targets=[dict(field='background_epsilon')], values=[4., 9.])])
        original = copy.deepcopy(cfg)
        prepared = prepare({}, cfg)
        variants = prepared['parameter_sweep']['variants']
        self.assertEqual(len(variants), 4)
        self.assertEqual(variants[3]['prepared']['geometry'][0]['radius'], .2)
        self.assertEqual(variants[3]['prepared']['background_epsilon'], 9.)
        self.assertEqual(cfg, original)
        cfg['parameter_sweep']['parameters'][0]['values'] = [.1, -1.]
        with self.assertRaises(ValueError):
            prepare({}, cfg)

    def test_atlas_rejects_nonphysical_target_and_duplicate_ids(self):
        cfg = settings()
        cfg['geometry'][0]['id'] = 'hole'
        cfg['parameter_sweep'] = dict(parameters=[dict(id='bad', targets=[dict(field='runtime.timeout_s')], values=[1.])])
        with self.assertRaises(ValueError):
            prepare({}, cfg)
        cfg.pop('parameter_sweep')
        cfg['geometry'].append(copy.deepcopy(cfg['geometry'][0]))
        with self.assertRaises(ValueError):
            prepare({}, cfg)


if __name__ == '__main__':
    unittest.main()
