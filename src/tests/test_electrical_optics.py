import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from electrical_optics import (E, EPS0, M0, C, LAYERS, EDGES_NM,
    coupled_model, drude_epsilon, execute_electrical, interband_response,
    prepare_coupling, validate_options)
from model import epsilon


def optical_model():
    layers = [dict(name='Incident', material='Air', thickness=0.)]
    for index, source in enumerate(LAYERS):
        layers.append(dict(name=source, material='AlGaAs' if index == 2 else 'GaAs',
                           thickness=(EDGES_NM[index+1]-EDGES_NM[index])/1000))
    layers.extend([dict(name='ITO', material='ITO', thickness=.04),
                   dict(name='Unmapped', material='GaAs', thickness=.005),
                   dict(name='Exit', material='Air', thickness=0.)])
    return dict(materials=[dict(name=name, model='constant_nk', a=n, b=k) for name, n, k in
                           [('Air', 1., 0.), ('GaAs', 3.5, .01), ('AlGaAs', 3.2, .001), ('ITO', 1.9, .05)]],
                layers=layers, patterns=[dict(layer=source, material='Air', shape='circle',
                    cx=0., cy=0., sx=.046, sy=0., angle=0.) for source in LAYERS],
                ax=.444, ay=.444, basis=9, mode='Wavelength sweep', phi=0., polarization='s',
                points=[[i, w, 0.] for i, w in enumerate([1100., 1150., 1200.])], warnings=[])


def coupling_options(**changes):
    model = optical_model()
    mapping = {row['name']: {'layer': row['name'], 'material': row['material']}
               for row in model['layers'][1:7]}
    return dict(dict(optical_enabled=True, optical_reference='zero_bias', optical_mapping=mapping,
                     optical_slices_per_layer=3, model='explicit_ito', biases_V=[0., -2.]), **changes)


def profile(biased=False):
    records = {key: [] for key in ('z_nm', 'electrons_cm3', 'holes_cm3', 'Ez_V_m',
                                  'Ez_squared_V2_m2', 'ito_electrons_cm3', 'layer_name')}
    for index, source in enumerate((*LAYERS, 'ITO')):
        start = EDGES_NM[index] if index < 5 else 420.
        stop = EDGES_NM[index+1] if index < 5 else 460.
        n = 1e18*(1+index) if index in (3, 4) else 0.
        p = 1e18*(1+index) if index < 2 else 0.
        if biased:
            n *= .8
            p *= .8
        field = -1e6*(2 if biased else 1)
        for z in np.linspace(start, stop, 5):
            for key, value in [('z_nm', z), ('electrons_cm3', n), ('holes_cm3', p),
                               ('Ez_V_m', field), ('Ez_squared_V2_m2', field*field),
                               ('ito_electrons_cm3', (5.5e20 if biased else 5e20) if source == 'ITO' else 0.),
                               ('layer_name', source)]:
                records[key].append(value)
    return {key: np.asarray(value) for key, value in records.items()}


class ElectricalOpticsTests(unittest.TestCase):
    def test_draft_validation_and_mapping_preflight(self):
        draft = validate_options(dict(optical_enabled=True))
        self.assertEqual(draft['biases_V'], [0., -2.])
        self.assertEqual(draft['optical_mapping'], {})
        with self.assertRaisesRegex(ValueError, 'explicitly map'):
            prepare_coupling(optical_model(), draft)
        self.assertFalse(prepare_coupling({}, {})['optical_enabled'])
        for change in [dict(optical_enabled='true'), dict(optical_slices_per_layer=2.5),
                       dict(optical_reference='unknown'), dict(unmodelled=True)]:
            with self.assertRaises(ValueError):
                validate_options(change)

    def test_mapping_rejects_wrong_thickness_order_and_material(self):
        model = optical_model()
        model['layers'][1]['thickness'] = .2
        with self.assertRaisesRegex(ValueError, '50 nm'):
            prepare_coupling(model, coupling_options())
        options = coupling_options()
        options['optical_mapping'][LAYERS[0]]['material'] = 'ITO'
        with self.assertRaisesRegex(ValueError, 'not used'):
            prepare_coupling(optical_model(), options)
        model = optical_model()
        model['layers'][1], model['layers'][5] = model['layers'][5], model['layers'][1]
        with self.assertRaisesRegex(ValueError, 'stack order'):
            prepare_coupling(model, coupling_options())

    def test_changed_optical_hole_geometry_is_rejected_before_solving(self):
        changed = optical_model()
        changed['ax'] = .5
        with self.assertRaisesRegex(ValueError, '444 nm'):
            prepare_coupling(changed, coupling_options())
        changed = optical_model()
        changed['patterns'][0]['sx'] = .06
        with self.assertRaisesRegex(ValueError, 'radius 46 nm'):
            prepare_coupling(changed, coupling_options())
        changed = optical_model()
        changed['patterns'][0]['material'] = 'GaAs'
        with self.assertRaisesRegex(ValueError, 'contain air'):
            prepare_coupling(changed, coupling_options())
        changed = optical_model()
        changed['patterns'].append(dict(changed['patterns'][0]))
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            prepare_coupling(changed, coupling_options())

    def test_exact_reference_and_geometry_are_preserved(self):
        model = optical_model()
        original = copy.deepcopy(model)
        cfg = prepare_coupling(model, coupling_options())
        ref = profile()
        changed, indices = coupled_model(model, cfg, ref, ref)
        self.assertEqual(model, original)
        self.assertEqual(len(indices), (len(changed['layers'])-3)*3)
        self.assertAlmostEqual(sum(row['thickness'] for row in changed['layers']),
                               sum(row['thickness'] for row in model['layers']), places=15)
        self.assertEqual(next(row for row in changed['layers'] if row['name'] == 'Unmapped')['material'], 'GaAs')
        holes = [row for row in changed['patterns'] if row['shape'] == 'circle']
        self.assertGreaterEqual(len(holes), 15)
        self.assertTrue(all(row['material'] == 'Air' and row['sx'] == .046 for row in holes))
        materials = {row['name']: row for row in changed['materials']}
        for row in changed['layers'][1:-2]:
            reference_name = 'ITO' if row['name'].startswith('ITO') else 'AlGaAs' if row['name'].startswith('Al0.') else 'GaAs'
            self.assertAlmostEqual(abs(epsilon(materials[row['material']], 1150)-epsilon(
                next(material for material in model['materials'] if material['name'] == reference_name), 1150)), 0, places=13)

    def test_undoped_semiconductor_convention_does_not_double_count_bulk_ito(self):
        cfg = prepare_coupling(optical_model(), coupling_options(optical_reference='undoped', ito_density_cm3=5e20))
        shifted, records = coupled_model(optical_model(), cfg, profile(), profile())
        ito = [row for row in records if row['electrical_layer'] == 'ITO']
        self.assertTrue(all(abs(row['n']-1.9) < 1e-13 and abs(row['k']-.05) < 1e-13 for row in ito))
        self.assertLess(next(row for row in records if row['electrical_layer'] == 'n GaAs')['n'], 3.5)
        # Refinement retains the semiconductor junction and sub-nm ITO nodes.
        boundaries = {row['z_end_nm'] for row in records if row['electrical_layer'] == 'ITO'}
        self.assertTrue({420.25, 420.5, 420.75, 421.0}.issubset(boundaries))

    def test_density_changes_have_expected_sign_and_ito_damping_units(self):
        cfg = prepare_coupling(optical_model(), coupling_options())
        changed, records = coupled_model(optical_model(), cfg, profile(True), profile())
        gaas = next(row for row in records if row['electrical_layer'] == 'n GaAs' and row['wavelength_nm'] == 1150)
        ito = next(row for row in records if row['electrical_layer'] == 'ITO' and row['wavelength_nm'] == 1150)
        self.assertGreater(gaas['n'], 3.5)  # Depletion reduces negative Drude epsilon.
        self.assertLess(gaas['k'], .01)
        self.assertLess(ito['n'], 1.9)
        self.assertGreater(ito['k'], .05)
        omega = 2*np.pi*C/(1150e-9)
        actual = drude_epsilon([1150], 1e18, 'electrons', mass_ratio=.067, gamma_rad_s=1e13)[0]
        expected = -(1e24*E**2/(EPS0*.067*M0))/(omega**2+1j*1e13*omega)
        self.assertAlmostEqual(abs(actual-expected), 0, places=15)

    def test_material_boundaries_do_not_mix_carrier_densities(self):
        cfg = prepare_coupling(optical_model(), coupling_options(optical_slices_per_layer=1))
        sampled = profile(True)
        sampled['holes_cm3'][sampled['layer_name'] == 'p+ GaAs'] = 1e19
        sampled['holes_cm3'][sampled['layer_name'] == 'p GaAs'] = 1e17
        _, records = coupled_model(optical_model(), cfg, sampled, profile())
        plus = next(row for row in records if row['electrical_layer'] == 'p+ GaAs')
        p = next(row for row in records if row['electrical_layer'] == 'p GaAs')
        self.assertLess(plus['n'], 3.5)
        self.assertGreater(p['n'], 3.5)

    def test_tensor_reference_and_electro_optic_eigenindices(self):
        cfg = prepare_coupling(optical_model(), coupling_options(electro_optic=True))
        self.assertTrue(cfg['requires_native'])
        shifted, records = coupled_model(optical_model(), cfg, profile(True), profile())
        ref_shifted, _ = coupled_model(optical_model(), cfg, profile(), profile())
        reference_material = ref_shifted['materials'][4]
        tensor = reference_material['epsilon_tensor'][1]
        self.assertEqual(tensor[0][1], [0., 0.])
        self.assertEqual(tensor[0][2], [0., 0.])
        self.assertEqual(tensor[2][1], [0., 0.])
        row = next(row for row in records if row['electrical_layer'] == 'p GaAs')
        self.assertNotEqual(row['n_plus'], row['n_minus'])
        self.assertNotEqual(row['n'], row['n_z'])
        # The baseline tensor equals the chosen scalar reference exactly.
        self.assertAlmostEqual(complex(*tensor[0][0]), complex(3.5, .01)**2)

    def test_interband_matches_independent_adaptive_quadrature(self):
        from scipy.constants import hbar, k
        from scipy.integrate import quad
        from scipy.optimize import brentq
        from scipy.special import expit
        density, kind, wave = 8e18, 'electrons', 1150.
        # Independent adaptive integration instead of the production fixed nodes.
        target = density/4.3e17
        half = lambda eta: 2/np.sqrt(np.pi)*quad(lambda t: np.sqrt(t)*expit(eta-t), 0, max(80, eta+60))[0]
        eta = brentq(lambda v: half(v)-target, -100, 200)
        critical = 1.6e24*(.066/(1.4*13.1))**3
        gap = 1.42+.125/13.1*np.cbrt(min(0., 1-density/critical))
        masses = np.array([.45, .084])
        reduced = 1/(1/.066+1/masses)
        total = 2.3e12*np.sqrt(hbar/E)
        band_weights = total*reduced**1.5/np.sum(reduced**1.5)
        energy = 1239.8419843320026/wave
        def integrand(t):
            delta, u = t*t, gap+t*t
            blocked = expit(eta-delta*masses/(.066+masses)/(k*300/E))
            shifted = 2*delta/u*(total-np.sum(band_weights*blocked))/(u*u-energy*energy)
            reference = 2*total*delta/(1.42+delta)/((1.42+delta)**2-energy*energy)
            return shifted-reference
        expected = C*hbar/E*100/np.pi*quad(integrand, 0, np.inf, epsabs=1e-5, epsrel=1e-10, limit=300)[0]
        actual = interband_response([wave], density, kind)[0]
        self.assertAlmostEqual(actual.real, expected, places=8)
        self.assertEqual(actual.imag, 0.)
        with self.assertRaisesRegex(ValueError, 'extrapolation'):
            interband_response([wave], 1e20, 'holes')
        with self.assertRaisesRegex(ValueError, 'band edges'):
            interband_response([500], 1e18, kind)

    def test_execute_saves_reference_comparisons_and_forces_native_tensor_solver(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            results = []
            for bias, values in [(0., profile()), (-2., profile(True))]:
                path = directory/f'profile_{bias:g}.npz'
                np.savez(path, **values)
                results.append(dict(bias_V=bias, profile_npz=str(path)))
            seen, calls = [], []
            def solve(cfg, output, emit, cancelled):
                self.assertNotIn('optical_mapping', cfg)
                return dict(results=results, limitations=['electrical assumption'])
            def executor(model, perf, emit, cancelled):
                calls.append((model, perf))
                reflection = .4 if len(calls) == 1 else .45
                return [[i, wave, angle, reflection, .5, 1-reflection-.5]
                        for i, wave, angle in model['points']], {'solver': 'test'}
            with patch('electrical_solver.solve', solve):
                event = execute_electrical(optical_model(), {'solver_backend': 'eigenfree-gpu'},
                    coupling_options(electro_optic=True), directory/'run', executor, seen.append)
            self.assertEqual(event['kind'], 'search_complete')
            self.assertEqual(event['summary']['spectra'], 2)
            self.assertTrue(all(perf['solver_backend'] == 'native' for _, perf in calls))
            with (directory/'run'/'electrical_optical_spectra.csv').open() as stream:
                records = list(csv.DictReader(stream))
            self.assertEqual(len(records), 6)
            self.assertAlmostEqual(float(records[3]['dR']), .05)
            with (directory/'run'/'electrical_index_changes.csv').open() as stream:
                indices = list(csv.DictReader(stream))
            self.assertTrue(all(float(row['delta_n']) == 0 for row in indices if float(row['bias_V']) == 0))
            self.assertTrue(any(abs(float(row['delta_n'])) > 0 for row in indices if float(row['bias_V']) == -2))
            self.assertEqual(json.loads((directory/'run'/'search_summary.json').read_text())['optical_reference'], 'zero_bias')

    def test_failures_do_not_claim_complete(self):
        from backend import Cancelled
        cfg = prepare_coupling(optical_model(), coupling_options())
        with self.assertRaises(Cancelled):
            coupled_model(optical_model(), cfg, profile(), profile(), cancelled=lambda: True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'profile.npz'
            np.savez(path, **profile())
            with patch('electrical_solver.solve', return_value=dict(results=[dict(bias_V=0., profile_npz=str(path))])):
                with self.assertRaisesRegex(ValueError, 'invalid or incomplete'):
                    execute_electrical(optical_model(), {}, cfg, Path(folder)/'run', lambda *args: ([], {}))
                self.assertFalse((Path(folder)/'run'/'search_summary.json').exists())
            with patch('electrical_solver.solve', side_effect=InterruptedError('Cancellation requested')):
                with self.assertRaises(Cancelled):
                    execute_electrical(None, {}, {}, Path(folder)/'cancelled', lambda *args: ([], {}))

    def test_missing_ito_interface_sample_continues_same_material_density(self):
        cfg = prepare_coupling(optical_model(), coupling_options(optical_reference='undoped', ito_density_cm3=5e20))
        sampled = profile()
        keep = ~((sampled['layer_name'] == 'ITO') & (sampled['z_nm'] == 420.))
        sampled = {key: value[keep] for key, value in sampled.items()}
        _, records = coupled_model(optical_model(), cfg, sampled, sampled)
        first = next(row for row in records if row['electrical_layer'] == 'ITO')
        self.assertAlmostEqual(first['n'], 1.9, places=13)
        self.assertAlmostEqual(first['k'], .05, places=13)

    def test_resonance_shift_and_fixed_wavelength_readout(self):
        model = optical_model()
        model['points'] = [[i, w, 0.] for i, w in enumerate([1156., 1156.5, 1157., 1157.5, 1158.])]
        options = coupling_options(response='Absorption', feature='Peak', reference_nm=1157., tracking_window_nm=1.)
        calls = []
        def executor(model, perf, emit, cancelled):
            values = [.1, .2, .8, .3, .1] if not calls else [.1, .2, .3, .8, .1]
            calls.append(model)
            return [[i, wave, theta, 1-absorption, 0., absorption]
                    for (i, wave, theta), absorption in zip(model['points'], values)], {}
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            rows = []
            for bias, values in [(0., profile()), (-2., profile(True))]:
                path = directory/f'{bias:g}.npz'
                np.savez(path, **values)
                rows.append(dict(bias_V=bias, profile_npz=str(path)))
            with patch('electrical_solver.solve', return_value=dict(results=rows)):
                event = execute_electrical(model, {}, options, directory/'run', executor)
            self.assertEqual(event['summary']['baseline_nm'], 1157.)
            self.assertEqual(event['summary']['max_abs_shift_nm'], .5)
            with (directory/'run'/'electrical_features.csv').open() as stream:
                features = list(csv.DictReader(stream))
            self.assertEqual(float(features[1]['feature_nm']), 1157.5)
            self.assertEqual(float(features[1]['shift_nm']), .5)
            self.assertEqual(float(features[1]['fixed_A']), .3)
            self.assertAlmostEqual(float(features[1]['dA']), -.5)


if __name__ == '__main__':
    unittest.main()
