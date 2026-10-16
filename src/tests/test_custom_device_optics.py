import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from custom_device_optics import (build_custom_optical_model, execute_custom_electrical,
    material_drude, prepare_custom_coupling, validate_custom_options)
from device_model import validate_device
from electrical_material_library import builtin_materials
from electrical_optics import E, EPS0, M0, C
from model import epsilon


def device(material='silicon'):
    contact = dict(layer_id='active', shape='rectangle', cx_um=0., cy_um=0.,
                   size_x_um=.65, size_y_um=.48, angle_deg=0., vertices=[], enabled=True,
                   boundary='potential', voltage_V=0., bias_scale=0.)
    polygon = dict(id='hole', name='User polygon void', layer_id='active', operation='void',
                   material_id='air', shape='polygon', vertices=[[-.1, -.1], [.1, -.1], [.05, .1]],
                   size_x_um=.2, size_y_um=.2, cx_um=0., cy_um=0., angle_deg=0., enabled=True)
    return validate_device(dict(schema_version=1, name='Arbitrary editable device', width_um=.65, depth_um=.48,
        temperature_K=300., mesh=dict(nx=8, ny=8, nz_per_layer=6, max_nodes=32000),
        layers=[dict(id='active', name='Custom active slab', material_id=material, thickness_um=.17,
                     donor_cm3=0., acceptor_cm3=0., enabled=True)], shapes=[polygon], doping_regions=[],
        contacts=[dict(contact, id='bottom', name='Bottom terminal', surface='bottom'),
                  dict(contact, id='top', name='Top terminal', surface='top')]), builtin_materials())


def optical_model():
    return dict(materials=[dict(name='Void', model='constant_nk', a=1., b=0.),
                           dict(name='Chosen optical table', model='constant_nk', a=3.4, b=.02)],
        layers=[dict(name='Incident', material='Void', thickness=0.),
                dict(name='Custom active slab', material='Chosen optical table', thickness=.17),
                dict(name='Exit', material='Void', thickness=0.)],
        patterns=[dict(layer='Custom active slab', material='Void', shape='polygon',
                       vertices=[[-.1, -.1], [.1, -.1], [.05, .1]], cx=0., cy=0., sx=.2, sy=.2, angle=0.)],
        ax=.65, ay=.48, basis=9, mode='Wavelength sweep', polarization='s', phi=0.,
        points=[[i, wave, 0.] for i, wave in enumerate([1500., 1550., 1600.])], warnings=[])


def options(**changes):
    return dict(dict(model='custom_device', device=device(), material_library=builtin_materials(),
        biases_V=[0., -.1], swept_contact_id='top', charge_model='dielectric',
        optical_enabled=True, optical_reference='zero_bias', reference_nm=1550., tracking_window_nm=100.,
        optical_slices_per_layer=3), **changes)


def profile(biased=False, material='silicon'):
    z = np.array([10., 40., 80., 120., 160.])
    return dict(z_nm=z, electrons_cm3=np.full(len(z), 1.2e18 if biased else 1e18),
        holes_cm3=np.full(len(z), 1.5e17 if biased else 2e17),
        Ez_V_m=np.full(len(z), -2e6 if biased else -1e6),
        Ez_squared_V2_m2=np.full(len(z), 4e12 if biased else 1e12),
        ito_electrons_cm3=np.zeros(len(z)), layer_name=np.full(len(z), 'Custom active slab'),
        layer_id=np.full(len(z), 'active'), material=np.full(len(z), material))


class CustomDeviceOpticsTests(unittest.TestCase):
    def test_drafts_persist_without_contacts_but_run_requires_them(self):
        cfg = options(optical_enabled=False)
        cfg['device']['contacts'] = []
        canonical = validate_custom_options(cfg)
        self.assertEqual(canonical['device']['contacts'], [])
        with self.assertRaisesRegex(ValueError, 'contact'):
            prepare_custom_coupling(None, canonical)

    def test_arbitrary_names_polygons_and_thickness_survive_coupling(self):
        model = optical_model()
        original = copy.deepcopy(model)
        cfg = prepare_custom_coupling(model, options())
        self.assertEqual(cfg['optical_mapping']['active']['layer'], 'Custom active slab')
        changed, audits = build_custom_optical_model(model, cfg, profile(True), profile(),
            layer_records=[dict(layer_id='active', depth_start_nm=0., depth_end_nm=75.),
                           dict(layer_id='active', depth_start_nm=75., depth_end_nm=170.)])
        self.assertEqual(model, original)
        self.assertAlmostEqual(sum(row['thickness'] for row in changed['layers']), .17, places=15)
        self.assertTrue(all(row['shape'] == 'polygon' and row['vertices'] == model['patterns'][0]['vertices']
                            and row['material'] == 'Void' for row in changed['patterns']))
        self.assertTrue(any(row['z_end_nm'] == 75. for row in audits))
        self.assertLess(audits[0]['n'], 3.4)

    def test_drude_uses_edited_custom_masses_and_mobilities(self):
        material = next(row for row in builtin_materials() if row['id'] == 'silicon')
        material['properties'].update(electron_mass_ratio=.8, electron_mobility_cm2_Vs=120.)
        populations = dict(electrons_cm3=1e18, holes_cm3=0.)
        omega = 2*np.pi*C/(1550e-9)
        gamma = E/(.8*M0*120e-4)
        expected = -(1e24*E**2/(EPS0*.8*M0))/(omega**2+1j*gamma*omega)
        actual = material_drude([1550.], populations, material)[0]
        self.assertAlmostEqual(abs(actual-expected), 0., places=15)
        material['properties']['electron_mass_ratio'] = .2
        self.assertNotEqual(material_drude([1550.], populations, material)[0], actual)

    def test_zero_bias_and_dielectric_optical_materials_are_unchanged(self):
        cfg = prepare_custom_coupling(optical_model(), options())
        changed, _ = build_custom_optical_model(optical_model(), cfg, profile(), profile())
        for row in changed['materials'][2:]:
            self.assertAlmostEqual(abs(epsilon(row, 1550.)-complex(3.4, .02)**2), 0., places=13)
        cfg = prepare_custom_coupling(optical_model(), options(device=device('air')))
        changed, _ = build_custom_optical_model(optical_model(), cfg, profile(True, 'air'), profile(False, 'air'))
        for row in changed['materials'][2:]:
            self.assertAlmostEqual(abs(epsilon(row, 1550.)-complex(3.4, .02)**2), 0., places=13)

    def test_mixed_solid_materials_reject_only_optical_coupling(self):
        cfg = options()
        shape = dict(cfg['device']['shapes'][0], id='inclusion', name='GaAs inclusion', operation='material', material_id='gaas')
        cfg['device']['shapes'].append(shape)
        validate_custom_options(cfg)
        with self.assertRaisesRegex(ValueError, 'material-specific'):
            prepare_custom_coupling(optical_model(), cfg)
        cfg['optical_enabled'] = False
        self.assertEqual(prepare_custom_coupling(None, cfg)['model'], 'custom_device')

    def test_wrong_mapping_or_profile_cannot_silently_change_material(self):
        cfg = options(optical_mapping={'active': dict(layer='Custom active slab', material='Void')})
        with self.assertRaisesRegex(ValueError, 'background'):
            prepare_custom_coupling(optical_model(), cfg)
        cfg = prepare_custom_coupling(optical_model(), options())
        with self.assertRaisesRegex(ValueError, 'single solid material'):
            build_custom_optical_model(optical_model(), cfg, profile(True, 'gaas'), profile())
        with self.assertRaisesRegex(ValueError, 'GaAs'):
            prepare_custom_coupling(optical_model(), options(electro_optic=True))

    def test_gaas_tensor_is_explicit_and_forces_native(self):
        cfg = prepare_custom_coupling(optical_model(), options(device=device('gaas'), electro_optic=True))
        self.assertTrue(cfg['requires_native'])
        shifted, audits = build_custom_optical_model(optical_model(), cfg, profile(True, 'gaas'), profile(False, 'gaas'))
        self.assertIn('epsilon_tensor', shifted['materials'][2])
        self.assertNotEqual(audits[0]['n_plus'], audits[0]['n_minus'])

    def test_execute_saved_contract_and_fixed_wavelength_readout(self):
        model = optical_model()
        model['points'] = [[i, wave, 0.] for i, wave in enumerate([1500., 1525., 1550., 1575., 1600.])]
        calls = []
        def executor(model, perf, emit, cancelled):
            values = [.1, .2, .8, .3, .1] if not calls else [.1, .2, .3, .8, .1]
            calls.append(model)
            return [[i, wave, theta, 1-a, 0., a] for (i, wave, theta), a in zip(model['points'], values)], {}
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            outputs = []
            for bias, values in [(0., profile()), (-.1, profile(True))]:
                path = directory/f'profile_{bias:g}.npz'
                np.savez(path, **values)
                outputs.append(dict(bias_V=bias, profile_npz=str(path)))
            with patch('custom_electrical_solver.solve', return_value=dict(results=outputs, limitations=['electrical scope'])):
                event = execute_custom_electrical(model, {}, options(), directory/'run', executor)
            self.assertEqual(event['summary']['spectra'], 2)
            self.assertEqual(event['summary']['max_abs_shift_nm'], 25.)
            with (directory/'run'/'electrical_features.csv').open() as stream:
                features = list(csv.DictReader(stream))
            self.assertEqual(float(features[1]['fixed_A']), .3)
            self.assertAlmostEqual(float(features[1]['dA']), -.5)
            saved = json.loads((directory/'run'/'electrical_summary.json').read_text())
            self.assertEqual(saved['optical']['spectra_csv'], 'electrical_optical_spectra.csv')

    def test_actual_bounded_scipy_solve_and_optical_pipeline(self):
        calls = []
        def executor(model, perf, emit, cancelled):
            calls.append(model)
            return [[i, wave, theta, .2, .7, .1] for i, wave, theta in model['points']], {}
        with tempfile.TemporaryDirectory() as directory:
            event = execute_custom_electrical(optical_model(), {}, options(), directory, executor)
            self.assertEqual(event['kind'], 'search_complete')
            self.assertEqual(len(calls), 2)
            saved = json.loads((Path(directory)/'electrical_summary.json').read_text())
            self.assertEqual(saved['mesh']['cells'], 384)
            self.assertTrue(all(row['checks']['relative_gauss_balance'] < 1e-6 for row in saved['results']))

    def test_actual_electrical_only_needs_no_optical_model_or_native_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('backend.load_runtime', side_effect=AssertionError('Native optics must not be loaded')):
                event = execute_custom_electrical(None, {}, options(optical_enabled=False), directory,
                    lambda *args: self.fail('Optical executor must not be called for electrical-only mode'))
            self.assertFalse(event['summary']['optical_enabled'])
            self.assertFalse((Path(directory)/'electrical_optical_spectra.csv').exists())
            saved = json.loads((Path(directory)/'electrical_summary.json').read_text())
            self.assertEqual(len(saved['results']), 2)

    def test_actual_silicon_charge_changes_the_coupled_index(self):
        from scipy.constants import k
        from scipy.optimize import brentq
        from electrical_material_library import evaluate_material
        from electrical_physics.reference import fermi_half
        cfg = options(charge_model='semiconductor')
        cfg['device']['layers'][0]['donor_cm3'] = 1e16
        material = evaluate_material(next(row for row in cfg['material_library'] if row['id'] == 'silicon'))
        props, thermal = material['properties'], k*300/E
        ec = -props['affinity_eV']
        # Match the potential electrode to a neutral bulk semiconductor at 0 V.
        neutral = brentq(lambda phi: props['Nv_cm3']*float(fermi_half((ec-props['bandgap_eV']-phi)/thermal)[0])
                         -props['Nc_cm3']*float(fermi_half((phi-ec)/thermal)[0])+1e16, ec-1., ec+1.)
        cfg['device']['contacts'][0]['boundary'] = 'ohmic'
        cfg['device']['contacts'][1]['voltage_V'] = neutral
        with tempfile.TemporaryDirectory() as directory:
            execute_custom_electrical(optical_model(), {}, cfg, directory,
                lambda model, *args: ([[i, wave, theta, .2, .7, .1] for i, wave, theta in model['points']], {}))
            with (Path(directory)/'electrical_index_changes.csv').open() as stream:
                records = list(csv.DictReader(stream))
            biased = [row for row in records if float(row['bias_V']) != 0]
            self.assertTrue(any(abs(float(row['delta_n'])) > 1e-8 for row in biased))
            self.assertTrue(all(float(row['delta_n']) >= -1e-10 for row in biased))

    def test_cancellation_and_incomplete_optics_do_not_claim_complete(self):
        from backend import Cancelled
        with tempfile.TemporaryDirectory() as folder:
            with patch('custom_electrical_solver.solve', side_effect=InterruptedError('cancelled')):
                with self.assertRaises(Cancelled):
                    execute_custom_electrical(None, {}, options(optical_enabled=False), folder, lambda *args: ([], {}))
            path = Path(folder)/'profile.npz'
            np.savez(path, **profile())
            with patch('custom_electrical_solver.solve', return_value=dict(results=[dict(bias_V=0., profile_npz=str(path))])):
                with self.assertRaisesRegex(ValueError, 'invalid or incomplete'):
                    execute_custom_electrical(optical_model(), {}, options(), Path(folder)/'run', lambda *args: ([], {}))
                self.assertFalse((Path(folder)/'run'/'search_summary.json').exists())


if __name__ == '__main__':
    unittest.main()
