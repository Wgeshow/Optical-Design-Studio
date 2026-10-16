"""One periodic optical cell remains separate from the finite device solve."""
import copy
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from custom_device_optics import execute_custom_electrical, prepare_custom_coupling
from electrical_material_library import builtin_materials
from model import DEFAULT_PERFORMANCE
from optical_unit_cell import apply_optical_unit_cell, selected_cell_profile, validate_unit_cell
from test_contact_optics import device, prepared, project


def selection(**changes):
    return dict(dict(enabled=True, width_um=.45, depth_um=.45, cx_um=0., cy_um=0.), **changes)


def patterned_project():
    physical = device()
    physical['mesh'].update(nx=24, ny=24)
    physical['shapes'] = [dict(id=f'hole_{ix}_{iy}', name=f'Air hole {ix} {iy}', layer_id='p',
        material_id='air', operation='void', shape='circle', cx_um=x, cy_um=y,
        size_x_um=.18, size_y_um=.18, angle_deg=0., vertices=[], enabled=True)
        for ix, x in enumerate([-.45, 0., .45]) for iy, y in enumerate([-.45, 0., .45])]
    physical['contacts'][1].update(optical_material_name='Au', optical_thickness_um=.1)
    value = project(physical)
    value['settings']['optical_unit_cell'] = selection()
    return value


class OpticalCellGeometryTests(unittest.TestCase):
    def test_invalid_config_and_outside_finite_device_are_rejected(self):
        for cfg in [dict(enabled=1), dict(width_um=0), dict(width_um=True), dict(cx_um=float('nan')), dict(unknown=2)]:
            with self.assertRaises(ValueError): validate_unit_cell(cfg)
        with self.assertRaisesRegex(ValueError, 'fit inside'):
            validate_unit_cell(selection(cx_um=.9), device())
        self.assertFalse(validate_unit_cell(selection(enabled=False, width_um=4.), device())['enabled'])

    def test_single_hole_native_geometry_and_outside_p_ring_are_cropped(self):
        value = patterned_project()
        original = copy.deepcopy(value)
        result = prepared(value)
        self.assertEqual(value, original)
        self.assertEqual((result['ax'], result['ay']), (.45, .45))
        holes = [row for row in result['patterns'] if row['shape'] == 'circle']
        self.assertEqual(len(holes), 1)
        self.assertEqual((holes[0]['cx'], holes[0]['cy'], holes[0]['sx']), (0., 0., .09))
        self.assertFalse(any(row.get('contact_optical_surface') == 'top' for row in result['layers']))
        self.assertTrue(any(row.get('contact_optical_surface') == 'bottom' for row in result['layers']))
        bottom = next(row for row in result['patterns'] if row.get('contact_id') == 'N')
        self.assertEqual(bottom['shape'], 'polygon')
        self.assertTrue(all(abs(x) <= .225 and abs(y) <= .225 for x, y in bottom['vertices']))
        self.assertEqual(result['optical_unit_cell']['outside_patterns'], 12)
        self.assertFalse(result['optical_unit_cell']['finite_optical_device'])

    def test_disabled_selection_keeps_all_holes_and_full_periodic_supercell(self):
        value = patterned_project()
        value['settings']['optical_unit_cell']['enabled'] = False
        result = prepared(value)
        self.assertEqual((result['ax'], result['ay']), (2., 2.))
        self.assertEqual(len([row for row in result['patterns'] if row['shape'] == 'circle']), 9)
        self.assertEqual(result['optical_unit_cell']['domain'], 'device-footprint periodic supercell')
        self.assertEqual(len([row for row in result['layers'] if row.get('contact_optical_surface')]), 2)

    def test_offset_cell_recenters_analytic_shape(self):
        value = patterned_project()
        value['settings']['optical_unit_cell'] = selection(cx_um=.45, cy_um=-.45)
        result = prepared(value)
        hole = next(row for row in result['patterns'] if row['shape'] == 'circle')
        self.assertAlmostEqual(hole['cx'], 0.)
        self.assertAlmostEqual(hole['cy'], 0.)
        self.assertEqual(len([row for row in result['patterns'] if row['shape'] == 'circle']), 1)

    def test_partial_circle_clip_is_reported_and_preserves_only_intersection(self):
        value = patterned_project()
        value['settings']['optical_unit_cell'] = selection(cx_um=.18, width_um=.3)
        result = prepared(value)
        voids = [row for row in result['patterns'] if row['material'] == 'Air']
        self.assertEqual(len(voids), 1)
        self.assertEqual(voids[0]['shape'], 'polygon')
        self.assertTrue(all(-.15-1e-12 <= x <= .15+1e-12 and -.225-1e-12 <= y <= .225+1e-12
                            for x, y in voids[0]['vertices']))
        self.assertTrue(result['optical_unit_cell']['approximation_notes'])

    def test_concave_polygon_clip_can_have_multiple_exact_pieces(self):
        # The window cuts both separated arms of a U-shaped material region.
        model = dict(ax=4., ay=4., layers=[], patterns=[dict(shape='polygon', layer='film', material='Air',
            vertices=[[-1., -1.], [1., -1.], [1., 1.], [.5, 1.], [.5, -.5], [-.5, -.5], [-.5, 1.], [-1., 1.]],
            cx=0., cy=0., sx=2., sy=2., angle=0.)])
        apply_optical_unit_cell(model, selection(width_um=2.5, depth_um=.5, cy_um=.5))
        self.assertEqual(len(model['patterns']), 2)
        self.assertTrue(all(row['shape'] == 'polygon' for row in model['patterns']))
        area = sum(abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(row['vertices'], row['vertices'][1:]+row['vertices'][:1])))/2
                   for row in model['patterns'])
        self.assertAlmostEqual(area, .5)

    def test_large_pc_area_is_filtered_before_native_periodic_wrapping(self):
        model = prepared(project())
        model['ax'] = model['ay'] = 150.
        count = math.floor(100./.45)
        model['patterns'] = [dict(shape='circle', layer='p-Si PCS', material='Air',
            cx=(ix-(count-1)/2)*.45, cy=(iy-(count-1)/2)*.45, sx=.09, sy=0., angle=0.)
            for ix in range(count) for iy in range(count)]
        self.assertEqual(len(model['patterns']), 49284)
        apply_optical_unit_cell(model, selection(cx_um=.225, cy_um=.225))
        self.assertEqual(len(model['patterns']), 1)
        self.assertEqual(model['patterns'][0]['shape'], 'circle')
        self.assertAlmostEqual(model['patterns'][0]['cx'], 0.)
        self.assertAlmostEqual(model['patterns'][0]['cy'], 0.)
        self.assertEqual(model['optical_unit_cell']['outside_patterns'], 49283)


class SelectedCellAveragingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'volume.npz'
        self.physical = device()
        shape = (4, 2, 2)
        n = np.broadcast_to(np.array([1., 2., 5., 9.])[:, None, None]+np.array([0., 10.])[None, :, None], shape).copy()
        fields = np.zeros(shape+(3,)); fields[..., 2] = n
        solid = np.ones(shape, bool); solid[1, 0, 0] = False
        materials = np.zeros(shape, int); materials[1, 0, 0] = 1
        self.data = dict(x=np.array([-.75, -.25, .25, .75])*1e-6, y=np.array([-.5, .5])*1e-6,
            z=np.array([.1, .6])*1e-6, electrons_cm3=n, holes_cm3=n*.1, field_V_m=fields,
            solid=solid, material_index=materials, layer_index=np.broadcast_to(np.array([0, 1]), shape),
            material_ids=np.array(['silicon', '__void__']), layer_ids=np.array(['p', 'n']), bias_V=-.1)
        np.savez(self.path, **self.data)
        self.cfg = selection(width_um=.8, depth_um=.9, cx_um=.1, cy_um=.15)

    def test_fractional_xy_weights_exclude_voids_and_keep_field_second_moment(self):
        profile, audit = selected_cell_profile(self.path, self.physical, self.cfg, builtin_materials())
        # Overlaps are dx=.3,.5 and dy=.3,.6; void removes the .09 square-µm corner.
        self.assertAlmostEqual(profile['electrons_cm3'][0], (12*.18+5*.15+15*.3)/.63)
        self.assertAlmostEqual(profile['electrons_cm3'][1], (2*.09+12*.18+5*.15+15*.3)/.72)
        self.assertAlmostEqual(profile['Ez_squared_V2_m2'][0], (12**2*.18+5**2*.15+15**2*.3)/.63)
        self.assertNotEqual(profile['Ez_squared_V2_m2'][0], profile['Ez_V_m'][0]**2)
        np.testing.assert_array_equal(profile['layer_id'], ['p', 'n'])
        np.testing.assert_allclose(profile['solid_area_m2']*1e12, [.63, .72])
        self.assertEqual(audit['overlapping_xy_cells'], 4)
        self.assertEqual(audit['partially_overlapping_xy_cells'], 4)
        self.assertAlmostEqual(audit['selected_area_um2'], .72)

    def test_cell_all_void_at_a_depth_requires_refinement(self):
        self.data['solid'][:, :, 0] = False
        np.savez(self.path, **self.data)
        with self.assertRaisesRegex(ValueError, 'no solid'):
            selected_cell_profile(self.path, self.physical, self.cfg, builtin_materials())

    def test_mixed_material_cell_cannot_borrow_host_material_average(self):
        self.data['material_ids'] = np.array(['silicon', '__void__', 'gaas'])
        self.data['material_index'][2, 1, 0] = 2
        np.savez(self.path, **self.data)
        with self.assertRaisesRegex(ValueError, 'one mapped solid material'):
            selected_cell_profile(self.path, self.physical, self.cfg, builtin_materials())

    def test_ito_separate_population_does_not_double_count_on_loading(self):
        from custom_device_optics import _read_profile
        for layer in self.physical['layers']: layer['material_id'] = 'ito'
        self.data['material_ids'] = np.array(['ito', '__void__'])
        np.savez(self.path, **self.data)
        profile, _ = selected_cell_profile(self.path, self.physical, self.cfg, builtin_materials())
        self.assertTrue(np.all(profile['electrons_cm3'] == 0.))
        np.savez(Path(self.folder.name)/'selected.npz', **profile)
        loaded = _read_profile(Path(self.folder.name)/'selected.npz')
        np.testing.assert_array_equal(loaded['electrons_cm3'], profile['ito_electrons_cm3'])


class SelectedCellPipelineTests(unittest.TestCase):
    def options(self, value):
        return dict(model='custom_device', device=value['device'], material_library=value['electrical_materials'],
                    biases_V=[0., -.1], swept_contact_id='P', charge_model='dielectric', optical_enabled=True,
                    optical_reference='undoped', reference_nm=1550., optical_slices_per_layer=2)

    def test_actual_electrical_volume_retains_device_size_but_coupled_model_has_one_hole(self):
        value = patterned_project(); model = prepared(value)
        calls = []
        def executor(actual, performance, emit, cancelled):
            calls.append(actual)
            return [[i, wave, theta, .2, .7, .1] for i, wave, theta in actual['points']], {}
        with tempfile.TemporaryDirectory() as folder:
            event = execute_custom_electrical(model, {}, self.options(value), folder, executor)
            saved = json.loads((Path(folder)/'electrical_summary.json').read_text())
            self.assertEqual(saved['mesh']['cells'], 24*24*8)
            for state in saved['results']:
                with np.load(state['volume_npz']) as volume:
                    self.assertEqual(volume['potential'].shape, (24, 24, 8))
                    self.assertGreater(np.ptp(volume['x'])*1e6, 1.9)
            self.assertEqual(event['summary']['optical_unit_cell']['width_um'], .45)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(call['ax'] == .45 and call['ay'] == .45 for call in calls))
            self.assertTrue(all(len([row for row in call['patterns'] if row['shape'] == 'circle']) == 4 for call in calls))
            audit = json.loads((Path(folder)/'optical_cell_profiles'/'averaging.json').read_text())
            self.assertTrue(all(row['overlapping_xy_cells'] == 36 for row in audit))
            self.assertTrue(all(row['partially_overlapping_xy_cells'] > 0 for row in audit))
            self.assertTrue(all(row['checks']['relative_gauss_balance'] < 1e-6 for row in saved['results']))

    @unittest.skipUnless(os.environ.get('S4_TEST_CONTACT_OPTICS') == '1', 'Opt-in actual native S4 selected-cell test')
    def test_native_s4_single_cell_and_coupled_solve_produce_finite_conserved_spectra(self):
        from backend import execute
        value = patterned_project(); model = prepared(value)
        performance = dict(DEFAULT_PERFORMANCE, workers=1, threads=1, timeout_seconds=60)
        raw, _ = execute(model, performance)
        self.assertEqual(len(raw), 1)
        self.assertTrue(all(math.isfinite(number) for number in raw[0]))
        self.assertAlmostEqual(sum(raw[0][3:]), 1., places=10)
        with tempfile.TemporaryDirectory() as folder:
            event = execute_custom_electrical(model, performance, self.options(value), folder, execute)
            self.assertEqual(event['summary']['optical_samples'], 2)
            import csv
            with (Path(folder)/'electrical_optical_spectra.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(all(abs(sum(float(row[key]) for key in ('R', 'T', 'A'))-1.) < 1e-10 for row in rows))


if __name__ == '__main__':
    unittest.main()
