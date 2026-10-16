"""Material interpolation is a persisted scientific input, independent of display."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from model import (MAT_COLS, DEFAULT_PERFORMANCE, epsilon, interpolate_nk,
                   material_interpolations, prepare, sample_nk)
from fdtd_model import DEFAULTS, convert_material, evaluate_medium
from data_library import DataLibrary
from qt_core import ProjectStore, desktop_settings, prepare_job


def project():
    return dict(materials=[dict(zip(MAT_COLS, row)) for row in
        [('Air', 'constant_nk', 1., 0., '', 'nm'), ('Measured', 'table_nk', 1., 0., 'measured.csv', 'nm')]],
        layers=[dict(Name=name, Thickness_um=thickness, Material=material) for name,thickness,material in
                [('Above', 0., 'Air'), ('Film', .25, 'Measured'), ('Below', 0., 'Air')]], patterns=[],
        settings=dict(ax_um=1., ay_um=1., NumG=11, phi_deg=0., polarization='s', mode='Wavelength sweep',
                      theta_deg=0., wl_start_nm=1500., wl_stop_nm=1500., wl_step_nm=1.))


class MaterialInterpolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/'measured.csv'
        self.path.write_text('wavelength,n,k\n1000,2,.01\n2000,4,1\n')
        self.source = project()
        self.library = DataLibrary(self.root/'library')

    def tearDown(self):
        self.temp.cleanup()

    def model(self, policy=None):
        settings = copy.deepcopy(self.source['settings'])
        if policy is not None: settings['material_interpolations'] = {'Measured':policy}
        return prepare(self.source['materials'], self.source['layers'], [], [self.path], settings)

    def test_default_linear_is_unchanged_and_log_k_changes_only_between_samples(self):
        default = self.model()['materials'][1]
        linear = self.model('linear')['materials'][1]
        logged = self.model('log_k')['materials'][1]
        self.assertEqual(len(MAT_COLS), 6)
        self.assertNotIn('interpolation', default)
        self.assertEqual(epsilon(default, 1500.), epsilon(linear, 1500.))
        self.assertEqual(interpolate_nk(default, 1500.), (3., .505))
        np.testing.assert_allclose(interpolate_nk(logged, 1500.), (3., .1), rtol=0, atol=1e-15)
        self.assertAlmostEqual(epsilon(logged, 1500.), complex(3., .1)**2)
        queries = np.array([500., 1000., 1250., 1500., 1750., 2000., 2500.])
        n, k = sample_nk(logged, queries)
        np.testing.assert_allclose(n, [2, 2, 2.5, 3, 3.5, 4, 4], rtol=0, atol=0)
        np.testing.assert_allclose(k, [.01, .01, np.sqrt(.001), .1, np.sqrt(.1), 1, 1], rtol=1e-15)
        np.testing.assert_array_equal(k[[0, 1, 5, 6]], [.01, .01, 1, 1])
        for wavelength in (500., 1000., 2000., 2500.):
            self.assertEqual(epsilon(logged, wavelength), epsilon(default, wavelength))

    def test_log_k_requires_every_sample_positive_and_never_invents_a_floor(self):
        for k in (0., -1.):
            self.path.write_text(f'wavelength,n,k\n1000,2,.01\n2000,4,{k}\n')
            with self.assertRaisesRegex(ValueError, 'strictly positive'): self.model('log_k')
            raw = self.model()['materials'][1]
            self.assertEqual(interpolate_nk(raw, 2000.)[1], k)
            with self.assertRaisesRegex(ValueError, 'strictly positive'):
                sample_nk(dict(raw, interpolation='log_k'), [1000.])

    def test_map_validation_and_old_settings_shape(self):
        legacy = desktop_settings(self.source['settings'])
        self.assertNotIn('material_interpolations', legacy)
        self.assertEqual(desktop_settings(dict(legacy, material_interpolations={'Unused library entry':'log_k'}))['material_interpolations'],
                         {'Unused library entry':'log_k'})
        for bad in (None, [], {'': 'linear'}, {'Measured':'cubic'}, {'Measured':False}):
            with self.subTest(bad=bad), self.assertRaises(ValueError): material_interpolations(bad)
        settings = dict(self.source['settings'], material_interpolations={'Air':'log_k'})
        with self.assertRaisesRegex(ValueError, 'only to tabulated'):
            prepare(self.source['materials'], self.source['layers'], [], [self.path], settings)

    def test_project_session_preset_and_recovered_models_preserve_policy_and_raw_table(self):
        store = ProjectStore(self.library, restore=False)
        store.load_project(self.source)
        store.files = [self.path]
        store.update_settings({'material_interpolations':{'Measured':'log_k'}})
        portable = store.portable_project()
        before = self.path.read_bytes()
        reopened = ProjectStore(self.library, restore=True)
        self.assertEqual(reopened.settings['material_interpolations'], {'Measured':'log_k'})
        other = DataLibrary(self.root/'other-library')
        imported = ProjectStore(other, restore=False)
        imported.load_project(portable)
        for kind, options in (('simulation', {}), ('fields', dict(wavelength_nm=1500., layer='Film', grid=3))):
            _, job = prepare_job(kind, imported.portable_project(), options, other)
            measured = job['model']['materials'][1]
            self.assertEqual(measured['interpolation'], 'log_k')
            self.assertAlmostEqual(epsilon(measured, 1500.), complex(3, .1)**2)
        recovered = other.from_model(self.model('log_k'))
        self.assertEqual(recovered['settings']['material_interpolations'], {'Measured':'log_k'})
        key = self.library.save_preset(self.source['materials'][1], 'Measured', uploads=[self.path], interpolation='log_k')
        preset = self.library.presets()[key]['project']
        self.assertEqual(preset['settings']['material_interpolations'], {'Measured':'log_k'})
        self.assertEqual(set(preset['materials'][0]), set(MAT_COLS))
        self.assertEqual(self.path.read_bytes(), before)

    def test_actual_s4_slab_response_consumes_selected_between_sample_epsilon(self):
        from backend import execute
        settings = dict(DEFAULT_PERFORMANCE, workers=1, timeout_seconds=60)
        linear, _ = execute(self.model('linear'), settings)
        logged, _ = execute(self.model('log_k'), settings)
        self.assertEqual(linear[0][:3], logged[0][:3])
        self.assertGreater(abs(linear[0][5]-logged[0][5]), .05)
        self.assertAlmostEqual(sum(linear[0][3:6]), 1., delta=1e-12)
        self.assertAlmostEqual(sum(logged[0][3:6]), 1., delta=1e-12)

    def test_preset_source_provenance_and_interpolation_survive_library_bundle(self):
        row = self.source['materials'][1]
        with self.assertRaisesRegex(ValueError, 'source notes must be text'):
            self.library.save_preset(row, 'Measured', uploads=[self.path], source_notes=[])
        self.assertEqual(self.library.presets(), {})
        legacy = self.library.save_preset(row, 'Legacy', 'Original citation', uploads=[self.path])
        self.assertNotIn('source_notes', self.library.presets()[legacy])
        current = self.library.save_preset(row, 'Measured', 'My project notes', uploads=[self.path],
                                          interpolation='log_k', source_notes='Measured source citation')
        original = self.library.presets()[current]
        self.assertEqual(original['notes'], 'My project notes')
        self.assertEqual(original['source_notes'], 'Measured source citation')
        imported = DataLibrary(self.root/'bundle-import')
        result = imported.import_bundle(self.library.export())
        self.assertEqual(result['presets'], 2)
        restored = next(record for record in imported.presets().values() if record['label'] == 'Measured')
        self.assertEqual(restored, original)
        self.assertEqual(restored['project']['settings']['material_interpolations'], {'Measured':'log_k'})
        self.assertEqual(Path(imported.files_for(restored['project'])[0]).read_bytes(), self.path.read_bytes())

    def test_fdtd_fit_and_independent_error_check_use_selected_interpolation(self):
        wavelengths = np.linspace(900., 2300., 101)
        physical = dict(epsilon=2., poles=[dict(frequency=1.3, gamma=.1, strength=.8)])
        nk = np.sqrt(evaluate_medium(physical, 1000/wavelengths))
        material = dict(name='Measured', model='table_nk', interpolation='log_k',
                        table=np.column_stack((wavelengths, nk.real, nk.imag)).tolist())
        fitted = convert_material(material, 1000/1800, 1000/1200, DEFAULTS)
        self.assertEqual(fitted['interpolation'], 'log_k')
        frequencies = np.linspace(1000/1800, 1000/1200, 2001)
        n, k = sample_nk(material, 1000/frequencies)
        target = (n+1j*k)**2
        actual_error = np.max(abs(evaluate_medium(fitted, frequencies)-target)/np.maximum(abs(target), 1.))
        self.assertAlmostEqual(fitted['relative_error'], actual_error, delta=1e-15)
        self.assertLessEqual(actual_error, DEFAULTS['fit_tolerance'])


if __name__ == '__main__': unittest.main()
