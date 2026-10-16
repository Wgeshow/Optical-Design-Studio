"""Optional contact pads preserve ideal DC boundaries and real optical holes."""
import copy
import math
import os
import unittest

import numpy as np

from contact_optics import apply_contact_optics, footprint_patterns
from device_model import geometry_vertices, shape_mask, validate_device
from device_project_bridge import apply_polygons, optical_structure, validate_optical_assignment
from electrical_material_library import builtin_materials
from model import DEFAULT_PERFORMANCE, prepare


def device():
    common = dict(shape='rectangle', cx_um=0., cy_um=0., size_x_um=2., size_y_um=2.,
                  angle_deg=0., vertices=[], enabled=True, boundary='ohmic',
                  voltage_V=0., bias_scale=0.)
    return validate_device(dict(schema_version=1, name='Si-PCS usability device',
        width_um=2., depth_um=2., temperature_K=300.,
        mesh=dict(nx=8, ny=8, nz_per_layer=4, max_nodes=32000),
        layers=[dict(id='p', name='p-Si PCS', material_id='silicon', thickness_um=.2,
                     donor_cm3=0., acceptor_cm3=1e17, enabled=True),
                dict(id='n', name='n-Si film', material_id='silicon', thickness_um=.8,
                     donor_cm3=1e16, acceptor_cm3=0., enabled=True)],
        shapes=[], doping_regions=[], contacts=[
            dict(common, id='P', name='P square ring', layer_id='p', surface='top',
                 shape='square_ring', size_x_um=1.8, size_y_um=1.8,
                 inner_size_x_um=1.3, inner_size_y_um=1.3, optical_material_name='Au',
                 optical_thickness_um=.03),
            dict(common, id='N', name='N gold reflector', layer_id='n', surface='bottom')]), builtin_materials())


def project(physical=None):
    physical = physical or device()
    value = dict(device=physical, electrical_materials=builtin_materials(),
        materials=[dict(Name=name, Model='constant_nk', A=n, B=k, DataFile='', WavelengthUnit='nm')
                   for name, n, k in [('Air', 1., 0.), ('Si', 3.48, .001), ('Au', .3, 7.)]],
        layers=[dict(Name='Incident', Thickness_um=0., Material='Air'),
                dict(Name='p-Si PCS', Thickness_um=.2, Material='Si'),
                dict(Name='n-Si film', Thickness_um=.8, Material='Si'),
                dict(Name='Reflector', Thickness_um=0., Material='Au')], patterns=[], files=[],
        settings=dict(ax_um=2., ay_um=2., NumG=9, mode='Wavelength sweep',
                      wl_start_nm=1550., wl_stop_nm=1550., wl_step_nm=10.,
                      theta_deg=0., phi_deg=0., polarization='s'))
    mats, layers, patterns, _ = optical_structure(physical, value['electrical_materials'], value)
    value.update(materials=mats, layers=layers, patterns=patterns)
    return value


def prepared(value=None):
    value = value or project()
    result = prepare(value['materials'], value['layers'], value['patterns'], [], value['settings'])
    return apply_polygons(result, value)


class ContactOpticsTests(unittest.TestCase):
    def test_top_ring_does_not_change_canonical_or_legacy_device_layers(self):
        value = project()
        original = copy.deepcopy(value)
        result = prepared(value)
        self.assertEqual(value, original)
        self.assertEqual([row.get('device_layer_id') for row in result['layers']], [None, None, 'p', 'n', None])
        pad = result['layers'][1]
        self.assertEqual((pad['material'], pad['thickness'], pad['contact_optical_surface']), ('Air', .03, 'top'))
        self.assertEqual(len(result['patterns']), 4)
        self.assertTrue(all(row['material'] == 'Au' and row['layer'] == pad['name'] for row in result['patterns']))
        self.assertAlmostEqual(sum(row['sx']*row['sy'] for row in result['patterns']), 1.8**2-1.3**2)
        validate_optical_assignment(result)

    def test_disabled_optical_geometry_adds_no_pad(self):
        value = project()
        value['device']['contacts'][0]['optical_thickness_um'] = 0.
        result = prepared(value)
        self.assertEqual(len(result['layers']), 4)
        self.assertEqual(result['patterns'], [])
        value['device']['contacts'][0].update(optical_thickness_um=.03, enabled=False)
        self.assertEqual(len(prepared(value)['layers']), 4)

    def test_ring_rotation_and_open_center_are_preserved(self):
        contact = dict(device()['contacts'][0], cx_um=.12, cy_um=-.15, angle_deg=37.)
        patterns = footprint_patterns(contact, 'pad', 'Au')
        rng = np.random.default_rng(81)
        x, y = rng.uniform(-1.4, 1.4, (2, 5000))
        masks = [shape_mask(dict(row, shape='rectangle', cx_um=row['cx'], cy_um=row['cy'],
                                 size_x_um=row['sx'], size_y_um=row['sy'], angle_deg=row['angle']), x, y)
                 for row in patterns]
        np.testing.assert_array_equal(np.logical_or.reduce(masks), shape_mask(contact, x, y))
        self.assertFalse(any(shape_mask(dict(row, shape='rectangle', cx_um=row['cx'], cy_um=row['cy'],
                                            size_x_um=row['sx'], size_y_um=row['sy'], angle_deg=row['angle']),
                                       contact['cx_um'], contact['cy_um']) for row in patterns))

    def test_circle_ellipse_and_polygon_use_optical_size_conventions(self):
        contact = device()['contacts'][1]
        for shape, sx, sy in [('circle', .8, .8), ('ellipse', .8, .5), ('rectangle', .8, .5)]:
            obj = dict(contact, shape=shape, size_x_um=sx, size_y_um=sy)
            row = footprint_patterns(obj, 'pad', 'Au')[0]
            self.assertEqual(row['sx'], sx*(.5 if shape != 'rectangle' else 1.))
            self.assertEqual(row['sy'], 0. if shape == 'circle' else sy*(.5 if shape == 'ellipse' else 1.))
        obj = dict(contact, shape='polygon', vertices=[[-.1, -.1], [.2, -.1], [0., .3]],
                   cx_um=.1, cy_um=-.1, angle_deg=25.)
        row = footprint_patterns(obj, 'pad', 'Au')[0]
        self.assertEqual(row['vertices'], geometry_vertices(obj))
        self.assertEqual((row['cx'], row['cy'], row['angle']), (0., 0., 0.))

    def test_both_exterior_pads_keep_physical_device_layers_consecutive(self):
        value = project()
        value['device']['contacts'][1].update(optical_material_name='Au', optical_thickness_um=.1)
        result = prepared(value)
        self.assertEqual([row.get('contact_optical_surface') for row in result['layers']],
                         [None, 'top', None, None, 'bottom', None])
        self.assertEqual([row['device_layer_id'] for row in result['layers'] if row.get('device_layer_id')], ['p', 'n'])
        from custom_device_optics import prepare_custom_coupling
        cfg = prepare_custom_coupling(result, dict(model='custom_device', device=value['device'],
              material_library=builtin_materials(), biases_V=[0., -.1], swept_contact_id='P',
              charge_model='semiconductor', optical_enabled=True, reference_nm=1550.))
        self.assertEqual(cfg['optical_mapping']['p']['layer'], 'p-Si PCS')
        self.assertEqual(cfg['optical_mapping']['n']['layer'], 'n-Si film')

    def test_same_plane_contacts_group_and_conflicting_thickness_rejects_atomically(self):
        physical = device()
        physical['contacts'].append(dict(physical['contacts'][0], id='P2', name='P2'))
        value = project(physical)
        self.assertEqual(len(prepared(value)['patterns']), 8)
        physical['contacts'][-1]['optical_thickness_um'] = .04
        value = project(physical)
        model = prepare(value['materials'], value['layers'], [], [], value['settings'])
        model['layers'][1]['device_layer_id'] = 'p'
        model['layers'][2]['device_layer_id'] = 'n'
        before = copy.deepcopy(model)
        with self.assertRaisesRegex(ValueError, 'same optical thickness'):
            apply_contact_optics(model, physical)
        self.assertEqual(model, before)

    def test_missing_material_side_and_buried_contacts_reject_at_optical_preflight(self):
        for changes, error in [(dict(optical_material_name='Unknown'), 'existing optical material'),
                               (dict(surface='side_x_min'), 'only the top'),
                               (dict(layer_id='n'), 'only the top')]:
            value = project()
            value['device']['contacts'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, error):
                prepared(value)

    def test_invalid_thickness_cannot_enter_prepared_optics(self):
        value = project()
        model = prepare(value['materials'], value['layers'], [], [], value['settings'])
        for thickness in (-.1, math.inf, math.nan, 'bad', True):
            physical = device()
            physical['contacts'][0]['optical_thickness_um'] = thickness
            with self.subTest(thickness=thickness), self.assertRaisesRegex(ValueError, 'finite and nonnegative'):
                apply_contact_optics(copy.deepcopy(model), physical)

    def test_air_background_is_physical_even_if_existing_air_name_is_repurposed(self):
        value = project()
        value['materials'][0]['A'] = 1.4
        result = prepared(value)
        pad = result['layers'][1]
        material = next(row for row in result['materials'] if row['name'] == pad['material'])
        self.assertEqual((material['a'], material['b']), (1., 0.))
        self.assertNotEqual(pad['material'], 'Air')

    def test_contact_assignment_is_included_in_optical_unassigned_validation(self):
        value = project()
        name = '__optical_unassigned_contact'
        value['materials'].append(dict(Name=name, Model='constant_nk', A=1., B=0.))
        value['device']['contacts'][0]['optical_material_name'] = name
        result = prepared(value)
        with self.assertRaisesRegex(ValueError, 'Assign optical n/k'):
            validate_optical_assignment(result)

    @unittest.skipUnless(os.environ.get('S4_TEST_CONTACT_OPTICS') == '1', 'Opt-in native S4 geometry test')
    def test_actual_native_s4_ring_changes_scattering_and_keeps_finite_results(self):
        from backend import execute
        value = project()
        with_ring = prepared(value)
        value['device']['contacts'][0]['optical_thickness_um'] = 0.
        without_ring = prepared(value)
        results = []
        for model in (without_ring, with_ring):
            rows, _ = execute(model, dict(DEFAULT_PERFORMANCE, workers=1, threads=1, timeout_seconds=60))
            self.assertEqual(len(rows), 1)
            self.assertTrue(all(math.isfinite(number) for number in rows[0]))
            self.assertAlmostEqual(sum(rows[0][3:]), 1., places=12)
            results.append(rows[0][3:])
        self.assertGreater(max(abs(a-b) for a,b in zip(*results)), 1e-5)


if __name__ == '__main__':
    unittest.main()
