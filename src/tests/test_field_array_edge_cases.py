"""Failure atomicity, format validation, fallback diagnostics, and full-volume layout."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from field_sampling import FourierFieldSampler
from field_solver import _sample_field_arrays, material_at
from field_storage import export_field_csv, load_field_arrays, validate_field_arrays, write_field_arrays
from test_backend import sample
from test_field_arrays import AnalyticSampler


class FieldArrayEdgeCases(unittest.TestCase):
    def arrays(self):
        return _sample_field_arrays(AnalyticSampler(), sample(), dict(grid=4, depth_samples=3))

    def test_complex_coordinates_are_rejected_without_discarding_information(self):
        arrays = self.arrays()
        arrays['xyz'] = arrays['xyz'].astype(complex)
        arrays['xyz'][0, 0] += 1j
        with self.assertRaises(ValueError):
            validate_field_arrays(arrays)

    def test_schema_version_requires_an_integer_scalar(self):
        arrays = self.arrays()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'electric_fields.npz'
            for version in (1.5, '1', True):
                with self.subTest(version=version):
                    np.savez(path, **arrays, schema_version=np.asarray(version))
                    with self.assertRaises(ValueError):
                        load_field_arrays(tmp)

    def test_csv_export_cannot_overwrite_its_binary_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = write_field_arrays(tmp, self.arrays())
            original = source.read_bytes()
            with self.assertRaises(ValueError):
                export_field_csv(tmp, source)
            self.assertEqual(source.read_bytes(), original)

    def test_failed_archive_write_preserves_previous_result_and_cleans_temporary_file(self):
        arrays = self.arrays()
        with tempfile.TemporaryDirectory() as tmp:
            source = write_field_arrays(tmp, arrays)
            original = source.read_bytes()

            def failed_write(writer, name, block):
                writer.stream.write(b'partial archive')
                raise OSError('Disk write failed')

            with patch('direct_npz.DirectNPZWriter.append', autospec=True, side_effect=failed_write):
                with self.assertRaisesRegex(OSError, 'Disk write failed'):
                    write_field_arrays(tmp, arrays)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list(Path(tmp).glob('.fields-*')), [])

    def test_failed_atomic_replace_preserves_previous_result(self):
        arrays = self.arrays()
        with tempfile.TemporaryDirectory() as tmp:
            source = write_field_arrays(tmp, arrays)
            original = source.read_bytes()
            with patch('direct_npz.os.replace', side_effect=PermissionError('Archive is locked')):
                with self.assertRaises(PermissionError):
                    write_field_arrays(tmp, arrays)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list(Path(tmp).glob('.fields-*')), [])

    def test_all_layers_and_depths_retained_after_geometry_changes(self):
        model = sample()
        first = model['layers'][1]
        model['layers'].insert(2, dict(first, name='Second film', thickness=.07))
        model['patterns'].append(dict(model['patterns'][0], layer='Second film', shape='ellipse',
                                      sx=.25, sy=.12, angle=31., cx=.08, cy=-.04))
        cfg = dict(grid=6, depth_samples=4, maps=True, track_contours=True, layer='Second film')
        before = _sample_field_arrays(AnalyticSampler(), model, cfg)
        # Reordering overlapping materials must invalidate masks, not just geometry coordinates.
        model['patterns'].append(dict(model['patterns'][-1], material=first['material'],
                                      shape='rectangle', sx=.11, sy=.2, angle=13.))
        after = _sample_field_arrays(AnalyticSampler(), model, cfg)
        self.assertEqual(np.sum(after['plane'] == 0), 2 * 6 * 6 * 4)
        self.assertEqual(np.sum(after['plane'] == 1), 6 * 6)
        self.assertEqual(np.sum(after['plane'] == 2), 2 * 6 * 6)
        self.assertFalse(np.array_equal(before['material'], after['material']))
        finite = {layer['name']: layer for layer in model['layers'][1:-1]}
        for (x, y, _), layer_id, material_id in zip(after['xyz'], after['layer'], after['material']):
            layer = finite[after['layer_names'][layer_id]]
            self.assertEqual(after['material_names'][material_id], material_at(model, layer, x, y))
        changed = copy.deepcopy(model)
        changed['layers'][1]['thickness'] *= 2
        shifted = _sample_field_arrays(AnalyticSampler(), changed, cfg)
        self.assertFalse(np.array_equal(after['xyz'], shifted['xyz']))
        self.assertFalse(after['xyz'].flags.writeable)


class NativeFallbackEdgeCases(unittest.TestCase):
    class Simulation:
        def __init__(self):
            self.native_calls = 0

        def GetBasisSet(self):
            return ((0, 0),)

        def GetFields(self, x, y, z):
            return ((1 + 0j, 0j, 0j), (0j, 1 + 0j, 0j))

        def GetFieldsOnGrid(self, z, shape, fmt):
            # Deliberately wrong legacy API forces scalar fallback after the native failure.
            return np.zeros((*shape, 3), complex), np.zeros((*shape, 3), complex)

        def GetFieldCoefficientsMany(self, depths):
            self.native_calls += 1
            if self.native_calls > 1:
                raise RuntimeError('Native batch unavailable')
            values = np.tile(np.asarray(self.GetFields(0, 0, 0)).ravel(), (len(depths), 1, 1))
            return values.astype(np.complex128).tobytes()

    def test_late_native_and_grid_failure_reports_scalar_fallback(self):
        simulation = self.Simulation()
        model = sample()
        sampler = FourierFieldSampler(simulation, model, 1500.)
        xy = np.array([[.1, -.2], [.2, .1]])
        sampler.GetFieldsMany(xy, .01)
        self.assertEqual(sampler.stats['method'], 'validated_native_coefficients')
        electric, magnetic = sampler.GetFieldsMany(xy, .02)
        for i, (x, y) in enumerate(xy):
            np.testing.assert_array_equal([electric[i], magnetic[i]], simulation.GetFields(x, y, .02))
        self.assertFalse(sampler.enabled)
        self.assertFalse(sampler.native_enabled)
        self.assertIsNotNone(sampler.stats['native_fallback_reason'])
        self.assertIsNotNone(sampler.stats['fallback_reason'])
        self.assertEqual(sampler.stats['method'], 'point')

    def test_point_backend_never_calls_native_batch_or_grid(self):
        simulation = self.Simulation()
        sampler = FourierFieldSampler(simulation, sample(), 1500., enabled=False)
        with patch.object(simulation, 'GetFieldCoefficientsMany', side_effect=AssertionError('Native call')):
            with patch.object(simulation, 'GetFieldsOnGrid', side_effect=AssertionError('Grid call')):
                sampler.prepare_planes([.01, .02])
                electric, magnetic = sampler.grid([-.1, .1], [-.2, .2], .01)
        self.assertEqual(electric.shape, (2, 2, 3))
        self.assertEqual(magnetic.shape, electric.shape)
        self.assertEqual(sampler.stats['method'], 'point')
        self.assertEqual(sampler.stats['point_calls'], 4)


if __name__ == '__main__':
    unittest.main()
