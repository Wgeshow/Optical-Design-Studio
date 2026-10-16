"""Independent analytical limits for the editable-device heat solver."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from device_model import default_device
from electrical_material_library import builtin_materials
from electrical_thermal import execute_thermal, solve_steady_heat, validate_thermal


class HeatEquationTests(unittest.TestCase):
    def test_uniform_slab_converges_to_quadratic_temperature(self):
        length, conductivity, density = 3e-6, 46., 2e14
        errors = []
        for count in (8, 16, 32):
            z = np.linspace(0., length, count+1)
            result = solve_steady_heat(([0., 2e-6], [0., 4e-6], z), conductivity, density,
                {'z_min': dict(kind='fixed_temperature', temperature_K=300.),
                 'z_max': dict(kind='fixed_temperature', temperature_K=300.)})
            centers = (z[:-1]+z[1:])/2
            exact = 300.+density*centers*(length-centers)/(2*conductivity)
            errors.append(float(np.max(np.abs(result['temperature_K'].ravel()-exact))))
            self.assertLess(result['checks']['relative_power_balance'], 1e-10)
            self.assertAlmostEqual(result['checks']['input_power_W'], density*length*8e-12)
        # Cell-center boundary closure converges at second order.
        self.assertAlmostEqual(errors[0]/errors[1], 4., places=5)
        self.assertAlmostEqual(errors[1]/errors[2], 4., places=5)

    def test_nonuniform_two_material_resistance_and_convection_are_exact(self):
        z = np.array([0., .1, .4, .6, 1.])*1e-6
        k = np.array([2., 2., 20., 20.])[None, None, :]
        coefficient = 2e7
        result = solve_steady_heat(([0., 3e-6], [0., 2e-6], z), k, 0.,
            {'z_min': dict(kind='fixed_temperature', temperature_K=320.),
             'z_max': dict(kind='convection', temperature_K=300., coefficient_W_m2K=coefficient)})
        flux = 20./(.4e-6/2.+.6e-6/20.+1/coefficient)
        resistance = np.cumsum(np.diff(z)/k.ravel())-np.diff(z)/(2*k.ravel())
        np.testing.assert_allclose(result['temperature_K'].ravel(), 320.-flux*resistance, atol=2e-12)
        self.assertAlmostEqual(result['checks']['boundary_outward_power_W']['z_max'], flux*6e-12, places=14)
        self.assertAlmostEqual(result['checks']['boundary_outward_power_W']['z_min'], -flux*6e-12, places=14)
        self.assertLess(result['checks']['relative_power_balance'], 1e-12)

    def test_all_six_faces_remove_heat_by_their_physical_resistance(self):
        # One cell provides an independent six-resistor network check.
        widths = np.array([2., 3., 5.])*1e-6
        faces = [[0., width] for width in widths]
        boundaries = {axis+'_'+side: dict(kind='fixed_temperature', temperature_K=300.)
                      for axis in 'xyz' for side in ('min', 'max')}
        result = solve_steady_heat(faces, 10., 1e16, boundaries)
        volume = np.prod(widths)
        conductances = 2*10*volume/widths**2
        expected = 300.+1e16*volume/(2*conductances.sum())
        self.assertAlmostEqual(float(result['temperature_K'].item()), expected, places=10)
        for axis, conductance in zip('xyz', conductances):
            self.assertAlmostEqual(result['checks']['boundary_outward_power_W'][axis+'_max'], conductance*(expected-300), places=13)

    def test_tiny_temperature_rise_keeps_power_balance_precision(self):
        result = solve_steady_heat(([0., 1e-6],)*3, 10., 1e-9,
            {'z_max': dict(kind='fixed_temperature', temperature_K=300.)})
        self.assertGreater(result['temperature_rise_K'].item(), 0.)
        self.assertLess(result['checks']['relative_power_balance'], 1e-14)

    def test_unanchored_or_invalid_physics_is_rejected(self):
        faces = ([0., 1e-6],)*3
        for conductivity, power, boundary in ((1., 0., {}), (0., 1., {'z_max': dict(kind='fixed_temperature')}),
                (1., -1., {'z_max': dict(kind='fixed_temperature')})):
            with self.assertRaises(ValueError):
                solve_steady_heat(faces, conductivity, power, boundary)
        with self.assertRaises(InterruptedError):
            solve_steady_heat(faces, 1., 0., {}, cancelled=lambda: True)


class EditableHeatTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.directory.cleanup)
        self.library = builtin_materials()
        self.device = default_device()
        self.device['layers'] = [dict(id='film', name='Editable film', material_id='silicon',
            thickness_um=1., donor_cm3=0., acceptor_cm3=0., enabled=True)]
        self.device['mesh'].update(nx=4, ny=4, nz_per_layer=8)
        for contact in self.device['contacts']:
            contact.update(layer_id='film', boundary='potential')
        self.config = dict(enabled=True, power_by_layer_W={'film': .001},
            conductivity={'silicon': dict(value_W_mK=100., source='Analytical verification value')},
            boundaries={'z_max': dict(kind='fixed_temperature', temperature_K=300.)},
            temperature_limit_K=301.)

    def test_editable_geometry_saved_units_and_power_conservation(self):
        summary = dict(options=dict(device=self.device, material_library=self.library))
        result = execute_thermal(summary, self.directory.name, self.config)
        self.assertEqual(result['model_scope'], 'prescribed_heat')
        self.assertEqual(result['status'], 'validity_limit')
        self.assertIn('not evidence of thermal runaway', result['status_reason'])
        self.assertAlmostEqual(result['checks']['input_power_W'], .001, places=14)
        self.assertLess(result['checks']['relative_power_balance'], 1e-10)
        saved = json.loads(Path(result['summary_json']).read_text())
        self.assertEqual(saved['volume_npz'], 'thermal_volume.npz')
        with np.load(result['volume_npz'], allow_pickle=False) as data:
            self.assertEqual(data['temperature_K'].shape, (4, 4, 8))
            self.assertEqual(data['layer_ids'].tolist(), ['film'])
            self.assertAlmostEqual(float(np.sum(data['heat_density_W_m3']*data['cell_volumes_m3'])), .001)
            self.assertLess(data['z'].max(), 1e-6)

    def test_heat_does_not_require_electrical_contacts(self):
        from custom_electrical_solver import build_mesh
        self.device['contacts'] = []
        validate_thermal(self.config, self.library, self.device)
        result = execute_thermal(dict(options=dict(device=self.device, material_library=self.library)),
                                 self.directory.name, self.config)
        self.assertAlmostEqual(result['checks']['input_power_W'], .001)
        with self.assertRaises(ValueError):
            build_mesh(self.device, self.library)

    def test_preflight_checks_actual_materials_layers_and_voids(self):
        validate_thermal(self.config, self.library, self.device)
        invalid = copy.deepcopy(self.config)
        invalid['power_by_layer_W'] = {'missing': .001}
        with self.assertRaisesRegex(ValueError, 'missing or disabled'):
            validate_thermal(invalid, self.library, self.device)
        invalid = copy.deepcopy(self.config)
        invalid['conductivity'] = {'gaas': dict(value_W_mK=46., source='test')}
        with self.assertRaisesRegex(ValueError, 'occupied material silicon'):
            validate_thermal(invalid, self.library, self.device)
        self.device['shapes'] = [dict(id='hole', name='Hole', layer_id='film', shape='circle',
            cx_um=0., cy_um=0., size_x_um=1., size_y_um=1., angle_deg=0., vertices=[],
            operation='void', material_id='air', enabled=True)]
        with self.assertRaisesRegex(ValueError, 'void_conductivity'):
            validate_thermal(self.config, self.library, self.device)
        self.config['void_conductivity_W_mK'] = .026
        result = execute_thermal(dict(options=dict(device=self.device, material_library=self.library)),
                                 self.directory.name, self.config)
        with np.load(result['volume_npz'], allow_pickle=False) as data:
            self.assertTrue(np.all(data['heat_density_W_m3'][~data['solid']] == 0.))
            self.assertAlmostEqual(float(np.sum(data['heat_density_W_m3']*data['cell_volumes_m3'])), .001)

    def test_defaults_disabled_and_input_is_not_mutated(self):
        self.assertFalse(validate_thermal()['enabled'])
        before = copy.deepcopy(self.config)
        validate_thermal(self.config)
        self.assertEqual(before, self.config)
        self.config['conductivity']['silicon']['source'] = ''
        with self.assertRaisesRegex(ValueError, 'explicit source'):
            validate_thermal(self.config)


if __name__ == '__main__':
    unittest.main()
