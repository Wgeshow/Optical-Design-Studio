"""Sparse fixed-conductor contracts; no PDE solve or native acceptance run."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np

from custom_electrical_solver import validate_options
from device_model import default_device
from electrical_material_library import builtin_materials, conductivity_S_m, evaluate_material, validate_materials
from electrical_terminal_studies import _conductivity


def fixed_material():
    return dict(id='fixed_sample', name='Measured fixed conductor', kind='conductor',
                model='constant', properties=dict(epsilon_r=5., conductivity_S_m=2.),
                sources=[dict(title='Explicit test assumption', kind='assumption')])


def options(material_id='fixed_sample', charge_model='dielectric'):
    device = default_device()
    device['layers'] = [dict(id='film', name='Test film', material_id=material_id,
                             thickness_um=1., donor_cm3=0., acceptor_cm3=0., enabled=True)]
    device['shapes'] = []
    device['doping_regions'] = []
    device['contacts'] = [dict(id=surface, name=surface, layer_id='film',
        shape='rectangle', cx_um=0., cy_um=0., size_x_um=2., size_y_um=2., angle_deg=0.,
        vertices=[], enabled=True, surface=surface, boundary='potential', voltage_V=0., bias_scale=0.)
        for surface in ('top', 'bottom')]
    return dict(device=device, material_library=builtin_materials()+[fixed_material()],
                charge_model=charge_model, biases_V=[0., 1.], swept_contact_id='bottom')


class FixedConductorMaterialTests(unittest.TestCase):
    def test_only_permittivity_and_explicit_sigma_are_kept_without_placeholders(self):
        for sigma in (0., 2.):
            material = fixed_material()
            material['properties']['conductivity_S_m'] = sigma
            before = deepcopy(material)
            evaluated = evaluate_material(material, temperature_K=350.)
            self.assertEqual(evaluated['properties'], material['properties'])
            self.assertEqual(evaluated['sources'], material['sources'])
            self.assertEqual(conductivity_S_m(material), sigma)
            self.assertEqual(material, before)

    def test_semiconductor_reference_and_unfixed_conductor_still_require_carrier_fields(self):
        for change in ('semiconductor', 'reference', 'missing_sigma'):
            material = fixed_material()
            if change == 'semiconductor': material['kind'] = 'semiconductor'
            elif change == 'reference': material['model'] = 'gaas_reference'
            else: del material['properties']['conductivity_S_m']
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'missing electrical properties'):
                validate_materials([material])

    def test_invalid_permittivity_and_sigma_are_rejected(self):
        for key, values in (('epsilon_r', (0., -1., float('nan'), float('inf'), True)),
                            ('conductivity_S_m', (-1., float('nan'), float('inf'), True))):
            for value in values:
                material = fixed_material()
                material['properties'][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_materials([material])

    def test_dielectric_preflight_needs_no_carrier_data_or_mesh(self):
        supplied = options()
        before = deepcopy(supplied)
        with patch('custom_electrical_solver.build_mesh', side_effect=AssertionError('No mesh or solve.')):
            result = validate_options(supplied)
        self.assertEqual(result['charge_model'], 'dielectric')
        self.assertEqual(result['material_library'][-1]['properties'], fixed_material()['properties'])
        self.assertEqual(supplied, before)

    def test_semiconductor_charge_rejects_occupied_sparse_conductor_before_mesh(self):
        supplied = options(charge_model='semiconductor')
        with patch('custom_electrical_solver.build_mesh', side_effect=AssertionError('No mesh or solve.')):
            with self.assertRaisesRegex(ValueError, 'Measured fixed conductor.*semiconductor charge.*Nc_cm3'):
                validate_options(supplied)

    def test_carrier_transport_rejects_sparse_conductor_before_dispatch(self):
        supplied = options(charge_model='semiconductor')
        supplied['transport'] = dict(mode='semiconductor_dd')
        with patch('electrical_transport_adapter.validate_transport_device',
                   side_effect=AssertionError('Carrier data must be checked before dispatch.')):
            with self.assertRaisesRegex(ValueError, 'semiconductor charge.*missing electrical properties'):
                validate_options(supplied)

    def test_active_material_shape_rejected_but_unused_disabled_and_void_ignored(self):
        supplied = options('gaas', 'semiconductor')
        shape = dict(id='region', name='Region', layer_id='film', material_id='fixed_sample',
            shape='rectangle', cx_um=0., cy_um=0., size_x_um=.5, size_y_um=.5,
            angle_deg=0., vertices=[], enabled=True, operation='material')
        # Merely retaining a sparse conductor in the project library is safe.
        validate_options(supplied)
        supplied['device']['shapes'] = [shape]
        with self.assertRaisesRegex(ValueError, 'semiconductor charge'):
            validate_options(supplied)
        shape['enabled'] = False
        validate_options(supplied)
        shape.update(enabled=True, operation='void')
        validate_options(supplied)

    def test_carrier_conductivity_request_does_not_silently_use_zero_mobility(self):
        with self.assertRaisesRegex(ValueError, 'Carrier-derived conductivity.*missing'):
            conductivity_S_m(fixed_material(), electrons_cm3=1e18, holes_cm3=0.)

    def test_ohmic_field_uses_explicit_sigma_including_zero_without_carrier_properties(self):
        materials = validate_materials([fixed_material()])
        mesh = dict(materials=materials, shape=(2,), material_index=np.array([0, 0]),
                    solid=np.array([True, True]))
        data = dict(electrons_cm3=np.array([0., 1e18]), holes_cm3=np.array([0., 2e18]))
        np.testing.assert_array_equal(_conductivity(mesh, data), np.array([2., 2.]))
        materials[0]['properties']['conductivity_S_m'] = 0.
        np.testing.assert_array_equal(_conductivity(mesh, data), np.zeros(2))


if __name__ == '__main__':
    unittest.main()
