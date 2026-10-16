"""Full phasor storage, legacy exports, and geometry-cache correctness."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from field_storage import (arrays_from_frame, copy_field_data, export_field_csv, field_data_exists,
                           field_frame, load_field_arrays, load_field_frame, write_field_arrays)
from field_solver import _sample_field_arrays, _sampling_layout, material_at
from tests.test_backend import sample


class AnalyticSampler:
    def prepare_planes(self, depths):
        self.batch_sizes = getattr(self, 'batch_sizes', []) + [len(depths)]

    def GetFieldsMany(self, xy, z):
        xy = np.asarray(xy)
        e = np.column_stack((xy[:, 0]+1j*z, xy[:, 1]-2j*z, np.ones(len(xy))*(1+3j)))
        return e, e*(.3+.7j)

    def grid(self, xs, ys, z):
        x, y = np.meshgrid(xs, ys, indexing='ij')
        e, h = self.GetFieldsMany(np.column_stack((x.ravel(), y.ravel())), z)
        return e.reshape(len(xs), len(ys), 3), h.reshape(len(xs), len(ys), 3)


class FieldArrayTests(unittest.TestCase):
    def arrays(self):
        self.model = sample()
        self.cfg = dict(grid=8, depth_samples=5, maps=True, track_contours=True)
        self.sampler = AnalyticSampler()
        return _sample_field_arrays(self.sampler, self.model, self.cfg)

    def test_full_volume_sections_complex_roundtrip_and_csv_export(self):
        arrays = self.arrays()
        self.assertEqual(np.sum(arrays['plane'] == 0), 8*8*5)
        self.assertEqual(np.sum(arrays['plane'] == 1), 8*8)
        self.assertEqual(np.sum(arrays['plane'] == 2), 8*8)
        self.assertLessEqual(max(self.sampler.batch_sizes), 8)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_field_arrays(root, arrays)
            self.assertTrue(field_data_exists(root))
            self.assertFalse((root/'electric_fields.csv').exists())
            loaded = load_field_arrays(root)
            for key in arrays:
                np.testing.assert_array_equal(arrays[key], loaded[key])
            copy_field_data(root, root/'copy')
            np.testing.assert_array_equal(load_field_arrays(root/'copy')['H'], arrays['H'])
            export_field_csv(root, root/'csv/electric_fields.csv')
            legacy = load_field_arrays(root/'csv')
            for key in ('xyz', 'E', 'H'):
                np.testing.assert_array_equal(legacy[key], arrays[key])
            frame = load_field_frame(root)
            np.testing.assert_allclose(frame['Sz'], .5*np.cross(arrays['E'], arrays['H'].conj()).real[:, 2])

    def test_geometry_labels_match_scalar_and_cache_excludes_wavelength(self):
        arrays = self.arrays()
        layer = self.model['layers'][1]
        for (x, y, _), material in zip(arrays['xyz'], arrays['material']):
            self.assertEqual(arrays['material_names'][material], material_at(self.model, layer, x, y))
        initial = _sampling_layout.cache_info().hits
        self.model['points'] = [[0, 1100., 23.]]
        self.model['materials'][1]['a'] = 2.1
        again = _sample_field_arrays(self.sampler, self.model, self.cfg)
        self.assertGreater(_sampling_layout.cache_info().hits, initial)
        self.assertIs(again['xyz'], arrays['xyz'])
        self.model['patterns'][0]['sx'] = .3
        changed = _sample_field_arrays(self.sampler, self.model, self.cfg)
        self.assertFalse(np.array_equal(changed['material'], arrays['material']))

    def test_rejects_corrupt_arrays_without_replacing_complete_result(self):
        arrays = self.arrays()
        with tempfile.TemporaryDirectory() as tmp:
            output = write_field_arrays(tmp, arrays)
            before = output.read_bytes()
            for key in ('xyz', 'E', 'H'):
                bad = dict(arrays)
                bad[key] = arrays[key].copy()
                bad[key][0, 0] = np.nan
                with self.assertRaisesRegex(ValueError, 'nonfinite'):
                    write_field_arrays(tmp, bad)
                self.assertEqual(output.read_bytes(), before)
            bad = dict(arrays, layer=np.full(len(arrays['layer']), -1))
            with self.assertRaises(ValueError):
                write_field_arrays(tmp, bad)

    def test_legacy_e_only_and_explicit_recalculation_format(self):
        arrays = self.arrays()
        frame = field_frame(dict(arrays, H=None))
        self.assertIsNone(arrays_from_frame(frame)['H'])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame.to_csv(root/'electric_fields.csv', index=False)
            self.assertIsNone(load_field_arrays(root)['H'])
            write_field_arrays(root, arrays)
            self.assertFalse((root/'electric_fields.csv').exists())
            self.assertIsNotNone(load_field_arrays(root)['H'])


if __name__ == '__main__':
    unittest.main()
