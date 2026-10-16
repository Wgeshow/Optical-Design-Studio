"""Finite PC placement, editable geometry and grouped-mask regression checks."""
import copy
import json
import math
import unittest
from unittest.mock import patch

import numpy as np

from device_model import default_device, shape_mask, validate_device
from pc_array import (MAX_SHAPES, apply_pc_array, iter_shape_masks,
                      plan_pc_array, regular_group_mask, regular_member,
                      validate_pc_arrays)


def device(width=150., depth=150.):
    result = default_device()
    result.update(width_um=width, depth_um=depth)
    return result


def specification(**values):
    result = dict(id='pc_test', name='Independent PC region', layer_id='layer_1',
                  cx_um=20., cy_um=-15., width_um=100., depth_um=100.,
                  cell_width_um=.444, cell_depth_um=.444, radius_um=.15)
    result.update(values)
    return result


def small_array(**values):
    return apply_pc_array(device(12., 12.), specification(
        cx_um=1., cy_um=-.5, width_um=4., depth_um=3.,
        cell_width_um=1., cell_depth_um=.75, radius_um=.25, **values))


def apply_masks(document, x, y, grouped):
    """Independently evaluate shape precedence as the material resolver does."""
    result = np.zeros(np.broadcast_arrays(x, y)[0].shape, dtype=np.int64)
    labels = {'void': -1, 'air': 1, 'silicon': 2, 'gaas': 3}
    if grouped:
        masks = iter_shape_masks(document, x, y)
    else:
        masks = ((obj, shape_mask(obj, x, y), {})
                 for obj in document['shapes'] if obj.get('enabled', True))
    for obj, mask, _counts in masks:
        result[mask] = labels['void'] if obj['operation'] == 'void' else labels[obj['material_id']]
    return result


class PCPlacementTests(unittest.TestCase):
    def test_full_requested_count_and_independent_position(self):
        plan = plan_pc_array(device(), specification())
        self.assertEqual((plan['nx'], plan['ny'], plan['hole_count']), (225, 225, 50_625))
        self.assertTrue(plan['can_apply'])
        self.assertAlmostEqual(plan['unused_x_um'], .1)
        self.assertAlmostEqual(plan['margin_x_um'], .05)
        self.assertAlmostEqual(plan['first_x_um'], -29.728)
        self.assertAlmostEqual(plan['first_y_um'], -64.728)
        self.assertTrue(any('256 cells per axis' in note for note in plan['notes']))

    def test_decimal_floor_tolerance_keeps_complete_cells_only(self):
        for extent, pitch, expected in ((.3, .1, 3), (.299999999, .1, 2),
                                        (100., .444, 225), (1., .4, 2)):
            with self.subTest(extent=extent, pitch=pitch):
                plan = plan_pc_array(device(), specification(
                    width_um=extent, depth_um=extent, cell_width_um=pitch,
                    cell_depth_um=pitch, radius_um=pitch/4))
                self.assertEqual((plan['nx'], plan['ny']), (expected, expected))
                first, last = plan['first_x_um'], plan['first_x_um']+(expected-1)*pitch
                self.assertAlmostEqual((first+last)/2, plan['cx_um'])
                self.assertGreaterEqual(first-pitch/2+1e-12, plan['cx_um']-extent/2)
                self.assertLessEqual(last+pitch/2, plan['cx_um']+extent/2+1e-12)

    def test_region_and_holes_fit_device_and_unit_cells(self):
        # The PC region can touch the device edge, and a hole may touch its cell.
        edge = plan_pc_array(device(), specification(cx_um=25., cy_um=-25., radius_um=.222))
        self.assertTrue(edge['can_apply'])
        for overrides, error in ((dict(cx_um=25.001), 'finite device'),
                                  (dict(cy_um=-25.001), 'finite device'),
                                  (dict(radius_um=.223), 'unit-cell'),
                                  (dict(cell_depth_um=.2, radius_um=.101), 'unit-cell')):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, error):
                plan_pc_array(device(), specification(**overrides))

    def test_finite_positive_numbers_and_missing_layers_are_rejected(self):
        for key in ('cx_um', 'cy_um', 'width_um', 'depth_um', 'cell_width_um',
                    'cell_depth_um', 'radius_um'):
            for value in (True, float('nan'), float('inf'), 'invalid'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    plan_pc_array(device(), specification(**{key: value}))
        for key in ('width_um', 'depth_um', 'cell_width_um', 'cell_depth_um', 'radius_um'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                plan_pc_array(device(), specification(**{key: 0.}))
        with self.assertRaisesRegex(ValueError, 'enabled target layer'):
            plan_pc_array(device(), specification(layer_id='missing'))

    def test_schema_text_and_boolean_fields_are_strict(self):
        for key in ('id', 'name', 'layer_id'):
            for value in (None, False, 123, [], {}):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, key + ' must be text'):
                    plan_pc_array(device(), specification(**{key: value}))
        for value in (None, 0, 1, 'false', 'true', [], {}):
            with self.subTest(enabled=value), self.assertRaisesRegex(ValueError, 'enabled must be a boolean'):
                plan_pc_array(device(), specification(enabled=value))
        for value in ('', '  '):
            with self.subTest(layer_id=value), self.assertRaisesRegex(ValueError, 'non-empty target layer'):
                plan_pc_array(device(), specification(layer_id=value))
            with self.subTest(id=value), self.assertRaisesRegex(ValueError, 'id must be non-empty'):
                plan_pc_array(device(), specification(id=value))
        spec = specification(enabled=False)
        del spec['id']
        del spec['name']
        plan = plan_pc_array(device(), spec)
        self.assertTrue(plan['id'].startswith('pc_'))
        self.assertEqual(plan['name'], 'PC area')
        self.assertIs(plan['enabled'], False)
        del spec['layer_id']
        with self.assertRaisesRegex(ValueError, 'non-empty target layer'):
            plan_pc_array(device(), spec)

    def test_saved_schema_rejects_string_false_and_does_not_scan_each_region(self):
        result = small_array()
        result['pc_arrays'][0]['enabled'] = 'false'
        with self.assertRaisesRegex(ValueError, 'enabled must be a boolean'):
            validate_device(result)
        result['pc_arrays'][0]['enabled'] = False
        self.assertIs(validate_pc_arrays(result)[0]['enabled'], False)

        class CountedShapes(list):
            iterations = 0
            def __iter__(self):
                self.iterations += 1
                return super().__iter__()

        result['shapes'] = CountedShapes(result['shapes'])
        spec = result['pc_arrays'][0]
        result['pc_arrays'] = [dict(spec, id='independent_pc_' + str(index)) for index in range(20)]
        self.assertEqual(len(validate_pc_arrays(result)), 20)
        self.assertEqual(result['shapes'].iterations, 1)

    def test_budget_is_explicit_and_never_silently_truncates(self):
        oversized = specification(cx_um=0., cy_um=0., width_um=150., depth_um=150.)
        plan = plan_pc_array(device(), oversized)
        self.assertEqual(plan['hole_count'], 337*337)
        self.assertEqual(plan['shape_budget_remaining'], MAX_SHAPES)
        self.assertFalse(plan['can_apply'])
        self.assertTrue(any('No holes will be truncated' in note for note in plan['notes']))
        with self.assertRaisesRegex(ValueError, 'document budget'):
            apply_pc_array(device(), oversized)
        empty = specification(cell_width_um=101.)
        self.assertFalse(plan_pc_array(device(), empty)['can_apply'])
        with self.assertRaisesRegex(ValueError, 'No complete unit cells'):
            apply_pc_array(device(), empty)

    def test_full_50625_shapes_are_real_editable_and_round_trip(self):
        original = device()
        generated = apply_pc_array(original, specification())
        self.assertEqual(original['shapes'], [])
        self.assertEqual(len(generated['shapes']), 50_625)
        self.assertEqual(len({row['id'] for row in generated['shapes']}), 50_625)
        self.assertEqual(generated['pc_arrays'][0]['hole_count'], 50_625)
        self.assertEqual(len(generated['pc_arrays'][0]['shape_ids']), 50_625)
        last = generated['shapes'][-1]
        self.assertEqual(last['pc_cell'], [224, 224])
        self.assertEqual(last['pc_array_id'], 'pc_test')
        self.assertAlmostEqual(last['cx_um'], 69.728)
        self.assertAlmostEqual(last['cy_um'], 34.728)
        restored = validate_device(json.loads(json.dumps(generated)))
        self.assertEqual(restored, generated)
        restored['shapes'][123]['cx_um'] += .013
        restored['shapes'][456]['size_x_um'] = .23
        restored['shapes'][789]['enabled'] = False
        deleted_id = restored['shapes'].pop(12)['id']
        canonical = validate_device(restored)
        self.assertEqual(len(canonical['shapes']), 50_624)
        self.assertFalse(any(row['id'] == deleted_id for row in canonical['shapes']))
        self.assertEqual(canonical['shapes'][122]['cx_um'], restored['shapes'][122]['cx_um'])

    def test_reapply_replaces_only_same_area_and_updates_metadata(self):
        first = small_array()
        other = dict(first['shapes'][0], id='independent', pc_array_id='other_pc')
        first['shapes'].append(other)
        spec = dict(first['pc_arrays'][0], width_um=2., radius_um=.2)
        result = apply_pc_array(first, spec)
        self.assertEqual(len(result['shapes']), 9)
        self.assertEqual(result['shapes'][0], other)
        self.assertEqual(len(result['pc_arrays']), 1)
        self.assertEqual(result['pc_arrays'][0]['hole_count'], 8)
        self.assertEqual(plan_pc_array(first, spec)['shape_budget_remaining'], MAX_SHAPES-1)

    def test_metadata_validation_retains_deletions_and_disabled_layers(self):
        result = small_array()
        removed = result['shapes'].pop()['id']
        result['layers'][0]['enabled'] = False
        arrays = validate_pc_arrays(result)
        self.assertIn(removed, arrays[0]['shape_ids'])
        self.assertEqual(len(result['shapes']), 15)
        with self.assertRaisesRegex(ValueError, 'enabled target layer'):
            apply_pc_array(result, arrays[0])
        bad = copy.deepcopy(result)
        bad['pc_arrays'][0]['id'] = bad['layers'][0]['id']
        with self.assertRaisesRegex(ValueError, 'unique'):
            validate_pc_arrays(bad)
        bad = copy.deepcopy(result)
        bad['pc_arrays'].append(copy.deepcopy(bad['pc_arrays'][0]))
        with self.assertRaisesRegex(ValueError, 'unique'):
            validate_pc_arrays(bad)
        for shape_ids in (None, [123], 'a'):
            bad = copy.deepcopy(result)
            bad['pc_arrays'][0]['shape_ids'] = shape_ids
            with self.assertRaisesRegex(ValueError, 'shape IDs'):
                validate_pc_arrays(bad)


class PCMaskTests(unittest.TestCase):
    def test_group_masks_and_per_hole_counts_match_individual_exact_masks(self):
        result = small_array()
        spec = result['pc_arrays'][0]
        rng = np.random.default_rng(841)
        x, y = rng.uniform(-6., 6., (2, 1500))
        for obj in result['shapes']:
            x = np.append(x, [obj['cx_um']-.25, obj['cx_um']+.25, obj['cx_um']])
            y = np.append(y, [obj['cy_um'], obj['cy_um'], obj['cy_um']+.25])
        mask, counts = regular_group_mask(spec, result['shapes'], x, y)
        expected = np.zeros(x.shape, bool)
        for obj in result['shapes']:
            individual = shape_mask(obj, x, y)
            expected |= individual
            self.assertEqual(counts[obj['id']], int(individual.sum()))
        np.testing.assert_array_equal(mask, expected)

    def test_broadcast_tangent_boundaries_deleted_and_duplicate_cells(self):
        result = small_array()
        spec = dict(result['pc_arrays'][0], radius_um=.375)
        objects = []
        for row in result['shapes'][::2]:
            objects.append(dict(row, size_x_um=.75, size_y_um=.75))
        objects.append(dict(objects[0], id='duplicate_same_geometry'))
        x = np.linspace(-2., 4., 97)[:, None]
        y = np.linspace(-3., 2., 81)[None, :]
        mask, counts = regular_group_mask(spec, objects, x, y)
        expected = np.zeros((97, 81), bool)
        for obj in objects:
            individual = shape_mask(obj, x, y)
            expected |= individual
            self.assertEqual(counts[obj['id']], int(individual.sum()))
        np.testing.assert_array_equal(mask, expected)

    def test_any_real_geometry_material_or_enable_edit_falls_back(self):
        result = small_array()
        original, spec = result['shapes'][0], result['pc_arrays'][0]
        self.assertEqual(regular_member(original, spec), (0, 0))
        changes = [dict(cx_um=math.nextafter(original['cx_um'], math.inf)),
                   dict(cy_um=math.nextafter(original['cy_um'], math.inf)),
                   dict(size_x_um=math.nextafter(original['size_x_um'], math.inf)),
                   dict(size_y_um=.49), dict(angle_deg=1.), dict(material_id='silicon'),
                   dict(operation='material'), dict(shape='ellipse'), dict(enabled=False),
                   dict(pc_cell=[True, 0]), dict(pc_cell=[0., 0]), dict(pc_cell=[-1, 0]),
                   dict(layer_id='layer_2'), dict(pc_array_id='other')]
        for change in changes:
            obj = dict(original, **change)
            with self.subTest(change=change):
                self.assertIsNone(regular_member(obj, spec))
                with self.assertRaisesRegex(ValueError, 'edited or disabled'):
                    regular_group_mask(spec, [obj], np.array([0.]), np.array([0.]))

    def test_tiny_position_edit_is_not_erased_at_original_boundary(self):
        result = small_array()
        original = result['shapes'][0]
        original.update(cx_um=40.)
        # Build a matching independent region centered at this large coordinate.
        spec = dict(result['pc_arrays'][0], cx_um=42.5, width_um=6., nx=6)
        original['pc_cell'] = [0, 0]
        original['cx_um'] = spec['cx_um']-(spec['nx']-1)*spec['cell_width_um']/2
        original['cx_um'] += 2e-11
        result['shapes'] = [original]
        result['pc_arrays'] = [spec]
        x = np.array([40.-.25])
        y = np.array([original['cy_um']])
        grouped = list(iter_shape_masks(result, x, y))
        self.assertFalse(bool(grouped[0][1][0]))
        np.testing.assert_array_equal(grouped[0][1], shape_mask(original, x, y))

    def test_consecutive_groups_preserve_material_override_and_edited_hole_order(self):
        result = small_array()
        # A later material fill overlaps several holes, then a later void wins.
        fill = dict(result['shapes'][0], id='fill', shape='rectangle',
                    cx_um=0., cy_um=0., size_x_um=4., size_y_um=3.,
                    material_id='silicon', operation='material')
        moved = dict(result['shapes'][1], cx_um=.12, cy_um=.03, size_x_um=.44)
        disabled = dict(result['shapes'][2], enabled=False)
        result['shapes'] = result['shapes'][:4] + [fill, moved, disabled] + result['shapes'][5:]
        result['shapes'][-1]['material_id'] = 'gaas'
        result['shapes'][-1]['operation'] = 'material'
        x = np.linspace(-5., 5., 113)[:, None]
        y = np.linspace(-5., 5., 119)[None, :]
        np.testing.assert_array_equal(apply_masks(result, x, y, True), apply_masks(result, x, y, False))
        batches = list(iter_shape_masks(result, x, y))
        self.assertLess(len(batches), len(result['shapes']))
        self.assertEqual([row[0]['id'] for row in batches],
                         [result['shapes'][0]['id'], 'fill', moved['id'], result['shapes'][7]['id'], result['shapes'][-1]['id']])

    def test_large_array_evaluation_batches_50625_holes_once(self):
        result = apply_pc_array(device(), specification())
        # The grouped path must not call individual whole-mesh shape_mask at all.
        x = np.linspace(-75., 75., 256)[:, None]
        y = np.linspace(-75., 75., 256)[None, :]
        with patch('device_model.shape_mask', side_effect=AssertionError('individual mask evaluation')):
            groups = list(iter_shape_masks(result, x, y))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][1].shape, (256, 256))
        self.assertEqual(len(groups[0][2]), 50_625)
        self.assertEqual(sum(groups[0][2].values()), int(groups[0][1].sum()))

    def test_disabled_parent_layers_skip_group_and_individual_evaluation(self):
        result = small_array()
        result['layers'][0]['enabled'] = False
        result['shapes'].append(dict(result['shapes'][0], id='edited_in_disabled_layer',
                                     operation='material', material_id='silicon'))
        x, y = np.array([0.]), np.array([0.])
        with patch('device_model.shape_mask', side_effect=AssertionError('disabled individual mask')), \
             patch('pc_array.regular_group_mask', side_effect=AssertionError('disabled grouped mask')):
            self.assertEqual(list(iter_shape_masks(result, x, y)), [])
        # Geometry-only callers without layer metadata retain their old behavior.
        del result['layers']
        self.assertEqual(len(list(iter_shape_masks(result, x, y))), 2)

    def test_solver_retains_per_hole_counts_and_actual_void_footprints(self):
        from custom_electrical_solver import build_mesh
        from electrical_material_library import builtin_materials
        result = small_array()
        result['mesh'].update(nx=64, ny=64, nz_per_layer=2)
        mesh = build_mesh(result, builtin_materials())
        x, y = np.meshgrid(mesh['axes'][0]*1e6, mesh['axes'][1]*1e6, indexing='ij')
        expected = np.zeros(x.shape, bool)
        for obj in result['shapes']:
            individual = shape_mask(obj, x, y)
            expected |= individual
            self.assertEqual(mesh['feature_cells'][obj['id']], int(individual.sum())*2)
        np.testing.assert_array_equal(~mesh['solid'][:, :, 0], expected)
        np.testing.assert_array_equal(~mesh['solid'][:, :, 1], expected)
        self.assertTrue(np.all(mesh['solid'][:, :, 2:]))

    def test_solver_rejects_unresolved_full_array_without_truncating_geometry(self):
        from custom_electrical_solver import build_mesh
        from electrical_material_library import builtin_materials
        result = apply_pc_array(device(), specification())
        with self.assertRaisesRegex(ValueError, 'features do not intersect mesh cells.*not been truncated'):
            build_mesh(result, builtin_materials())
        self.assertEqual(len(result['shapes']), 50_625)


if __name__ == '__main__':
    unittest.main()
