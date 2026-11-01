"""Analytic prescribed-source and UI contracts; no scientific solver is run."""
import copy
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_sesame_setup import SesameSetupWorkspace
from qt_photonic_bands import _rows, _fill
import sesame_transport as transport
import research_physics_worker as worker

APP = QApplication.instance() or QApplication([])


def configuration(dimension=1):
    material = dict(Nc=2.8e19, Nv=1.04e19, Eg=1.12, epsilon=11.7, mu_e=100., mu_h=50.,
        tau_e=1e-6, tau_h=1e-6, affinity=4.05, Et=0.)
    contact = dict(kind='Ohmic', electron_velocity_cm_s=1e10, hole_velocity_cm_s=1e10)
    cfg = dict(dimension=dimension, x_nodes_um=[0., .5, 1.], materials={'bulk': material},
        regions=[dict(id='region', material='bulk', x_range_um=[0., 1.], generation_cm3_s=2.3e21)],
        contacts=dict(left=contact, right=copy.deepcopy(contact)), voltages_V=[0.], temperature_K=300.)
    if dimension == 2:
        cfg['y_nodes_um'] = [0., .5, 1.]
        cfg['regions'][0]['y_range_um'] = [0., 1.]
    return cfg


def add_profile(cfg, **values):
    cfg['regions'][0]['generation_profile'] = dict(kind='exponential_x', absorption_cm1=23000., origin_um=0., **values)
    return cfg


class GenerationInputTests(unittest.TestCase):
    def test_uniform_omits_profile_and_prepare_is_deterministic(self):
        cfg = transport.prepare({}, configuration())
        self.assertNotIn('generation_profile', cfg['regions'][0])
        self.assertEqual(json.dumps(cfg, sort_keys=True), json.dumps(transport.prepare({}, configuration()), sort_keys=True))

    def test_rejects_malformed_and_unknown_profiles(self):
        for bad in (None, 'exp(-x)', {}, {'kind': 'uniform'},
                dict(kind='exponential_x', absorption_cm1=1, origin_um=0, expression='x'),
                dict(kind='other', absorption_cm1=1, origin_um=0)):
            with self.subTest(profile=bad):
                cfg = configuration(); cfg['regions'][0]['generation_profile'] = bad
                with self.assertRaises(ValueError): transport.prepare({}, cfg)

    def test_nonfinite_negative_and_origin_errors_are_addressed(self):
        for key, values in [('absorption_cm1', [-1, float('nan'), float('inf'), True]),
                ('origin_um', [.01, float('nan'), float('-inf'), True])]:
            for value in values:
                with self.subTest(key=key, value=value):
                    cfg = add_profile(configuration()); cfg['regions'][0]['generation_profile'][key] = value
                    try: transport.prepare({}, cfg)
                    except ValueError as exc:
                        diagnostic = exc.diagnostics[0]
                        self.assertEqual(diagnostic['field'], 'regions.region.generation_profile.'+key)
                        self.assertEqual(diagnostic['object_id'], 'region')
                        self.assertEqual(diagnostic['units'], 'cm^-1' if key == 'absorption_cm1' else 'um')
                    else: self.fail('Expected field-addressed rejection')

    def test_analytic_units_nonzero_origin_and_zero_limits(self):
        region = transport.prepare({}, add_profile(configuration()))['regions'][0]
        np.testing.assert_allclose(worker.sampled_region_generation(region, [0, .5, 1]),
            2.3e21*np.exp([0, -1.15, -2.3]), rtol=2e-15)
        region['generation_profile']['origin_um'] = -.5
        np.testing.assert_allclose(worker.sampled_region_generation(region, [0, .5, 1]),
            2.3e21*np.exp([-1.15, -2.3, -3.45]), rtol=2e-15)
        region['generation_profile']['absorption_cm1'] = 0
        np.testing.assert_array_equal(worker.sampled_region_generation(region, [0, 1]), [2.3e21]*2)
        region['generation_profile']['absorption_cm1'] = 1e308
        region['generation_profile']['origin_um'] = 0
        np.testing.assert_array_equal(worker.sampled_region_generation(region, [0, 1]), [2.3e21, 0])
        region['generation_cm3_s'] = 0
        np.testing.assert_array_equal(worker.sampled_region_generation(region, [0, 1]), [0, 0])

    def test_two_dimensional_global_coordinates_and_interface_ownership(self):
        cfg = add_profile(configuration(2))
        first = cfg['regions'][0]; first['x_range_um'] = [0, .5]
        second = copy.deepcopy(first); second.update(id='right', x_range_um=[.5, 1], generation_cm3_s=4.6e21)
        cfg['regions'].append(second)
        cfg = transport.prepare({}, cfg)
        labels = transport.region_labels(cfg)
        np.testing.assert_array_equal(labels, [[0, 1, 1]]*3)
        x, _ = np.meshgrid(cfg['x_nodes_um'], cfg['y_nodes_um'])
        result = np.zeros(x.shape)
        for i, region in enumerate(cfg['regions']):
            mask = labels == i; result[mask] = worker.sampled_region_generation(region, x[mask])
        np.testing.assert_allclose(result, [np.array([2.3e21, 4.6e21*np.exp(-1.15), 4.6e21*np.exp(-2.3)])]*3)

    def test_worker_saved_source_and_uniform_scaling_with_fake_engine(self):
        # Fake observables/solver test production assignment and NPZ plumbing,
        # without importing Sesame or claiming a transport solution.
        class Builder:
            def __init__(self, x, y, **kwargs):
                self.nx, self.ny = len(x), len(y); count = self.nx*self.ny
                self.scaling = types.SimpleNamespace(generation=100., energy=1., current=1., density=1., length=1.)
                self.g = np.zeros(count); self.rho = np.zeros(count); self.ni = np.ones(count)
                self.Nc = np.ones(count)*10; self.Nv = np.ones(count)*10
                self.bl = np.zeros(count); self.Eg = np.ones(count)
                self.dx, self.dy = np.diff(x), np.diff(y)
            def add_material(self, *args): pass
            def add_donor(self, *args): pass
            def add_acceptor(self, *args): pass
            def contact_type(self, *args): pass
            def contact_S(self, *args): pass
        class Solver:
            def solve(self, system, **kwargs):
                self.equilibrium = np.zeros(system.nx*system.ny)
                return dict(v=self.equilibrium.copy(), efn=self.equilibrium.copy(), efp=self.equilibrium.copy())
        sesame = types.ModuleType('sesame'); sesame.Builder = Builder
        solvers = types.ModuleType('sesame.solvers'); solvers.Solver = Solver
        observables = types.ModuleType('sesame.observables')
        observables.get_n = observables.get_p = lambda system, *args: np.ones(system.nx*system.ny)
        observables.get_bulk_rr = lambda system, *args: np.zeros(system.nx*system.ny)
        observables.get_jn = observables.get_jp = lambda system, efn, v, a, b, dx: np.zeros(len(a))
        for dim in (1, 2):
            for exponential in (False, True):
                with self.subTest(dimension=dim, exponential=exponential):
                    cfg = configuration(dim)
                    if exponential: add_profile(cfg)
                    cfg = transport.prepare({}, cfg)
                    with tempfile.TemporaryDirectory(dir=os.environ.get('ODS_TEST_TMPDIR')) as folder:
                        with patch.dict('sys.modules', {'sesame': sesame, 'sesame.solvers': solvers, 'sesame.observables': observables}), patch.object(worker, 'event'):
                            result = worker.sesame_transport(cfg, Path(folder))
                        with np.load(Path(folder)/result['state_files'][0]) as arrays:
                            expected = 2.3e21*np.exp([0, -1.15, -2.3]) if exponential else np.full(3, 2.3e21)
                            np.testing.assert_allclose(arrays['generation_cm3_s'], np.tile(expected, (3 if dim == 2 else 1, 1)))


class GenerationUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.store.activate_study('sesame_transport')
        self.page = SesameSetupWorkspace(self.store, document_id='sesame_transport')

    def tearDown(self):
        from PyQt6 import sip
        self.page._save_timer.stop(); sip.delete(self.page); APP.processEvents()

    def test_legacy_uniform_settings_and_seven_column_draft_are_retained(self):
        cfg = configuration(); self.page.load_settings(cfg)
        settings = self.page.options()['settings']
        self.assertNotIn('generation_profile', settings['regions'][0])
        self.assertEqual(len(self.page.draft()['regions'][0]), 7)
        self.assertEqual(transport.prepare({}, cfg), transport.prepare({}, settings))

    def test_profile_roundtrip_and_uniform_switch_omit_optional_schema(self):
        cfg = add_profile(configuration()); self.page.load_settings(cfg)
        self.assertEqual(self.page.options()['settings']['regions'][0]['generation_profile'], cfg['regions'][0]['generation_profile'])
        state = self.page.draft(); self.page.restore_draft(state)
        self.assertEqual(self.page.options()['settings']['regions'][0]['generation_profile'], cfg['regions'][0]['generation_profile'])
        inspector = self.page.inspectors['regions']
        inspector.editors['generation_profile'].setCurrentIndex(0)
        self.assertNotIn('generation_profile', self.page.options()['settings']['regions'][0])
        self.assertIn('Absolute device x', inspector.note.text())

    def test_old_draft_clears_previous_profile_cells(self):
        self.page.load_settings(configuration()); old = self.page.draft()
        self.page.load_settings(add_profile(configuration()))
        self.page.restore_draft(old)
        self.assertNotIn('generation_profile', self.page.options()['settings']['regions'][0])
        self.assertEqual(self.page.draft()['regions'], old['regions'])

    def test_manual_inspector_entry_and_field_specific_validation(self):
        self.page.load_settings(configuration())
        inspector = self.page.inspectors['regions']
        inspector.editors['generation_profile'].setCurrentIndex(1)
        inspector.editors['absorption_cm1'].setText('23000')
        inspector.editors['origin_um'].setText('0')
        region = self.page.options()['settings']['regions'][0]
        self.assertEqual(region['generation_profile'], dict(kind='exponential_x', absorption_cm1=23000., origin_um=0.))
        inspector.editors['origin_um'].setText('.1')
        with self.assertRaises(ValueError) as caught:
            transport.prepare({}, self.page.options()['settings'])
        self.assertEqual(caught.exception.diagnostics[0]['field'], 'regions.region.generation_profile.origin_um')

    def test_loaded_uniform_replaces_profile_without_leaking_values(self):
        self.page.load_settings(add_profile(configuration()))
        self.page.load_settings(configuration())
        self.assertNotIn('generation_profile', self.page.options()['settings']['regions'][0])
        self.assertEqual(len(self.page.draft()['regions'][0]), 7)

    def test_region_selection_reorder_and_field_diagnostic(self):
        self.page.resize(1100, 820); self.page.show(); APP.processEvents()
        cfg = add_profile(configuration())
        cfg['regions'][0]['x_range_um'] = [0, .5]
        second = copy.deepcopy(cfg['regions'][0]); second.update(id='right', x_range_um=[.5, 1])
        del second['generation_profile']; cfg['regions'].append(second)
        self.page.load_settings(cfg)
        _fill(self.page.regions, list(reversed(_rows(self.page.regions))))
        inspector = self.page.inspectors['regions']; inspector.refresh()
        rows = self.page.options()['settings']['regions']
        self.assertNotIn('generation_profile', rows[0]); self.assertIn('generation_profile', rows[1])
        self.assertTrue(self.page.open_diagnostic(dict(field='regions.region.generation_profile.origin_um', object_id='region')))
        self.assertEqual(self.page.regions.currentRow(), 1)
        self.assertEqual(inspector.editors['origin_um'].text(), '0.0')


if __name__ == '__main__': unittest.main()
