"""Physics translation, runtime isolation and optional real Meep smoke checks."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from fdtd_model import DEFAULTS, build_job, convert_material, evaluate_medium, validate_options
import meep_runtime


def project():
    return dict(materials=[dict(Name='Air', Model='constant_nk', A=1, B=0),
                           dict(Name='Glass', Model='constant_nk', A=1.5, B=0)],
        layers=[dict(Name='Above', Thickness_um=0, Material='Air'),
                dict(Name='Film', Thickness_um=.5, Material='Glass'),
                dict(Name='Below', Thickness_um=0, Material='Air')], patterns=[],
        settings=dict(ax_um=1., ay_um=1., NumG=11, phi_deg=0., polarization='s',
            mode='Wavelength sweep', theta_deg=0., wl_start_nm=1200., wl_stop_nm=1800., wl_step_nm=100.))


class TranslationTests(unittest.TestCase):
    def test_exact_dielectric_slab(self):
        job = build_job(project(), [], {})
        self.assertEqual(job['materials']['Glass']['epsilon'], 2.25)
        self.assertEqual(job['geometry'], [dict(shape='layer', material='Glass', z=0., thickness=.5)])
        self.assertEqual(job['size_z'], 4.5)
        json.dumps(job, allow_nan=False)

    def test_unused_bad_material_does_not_block_run(self):
        source = project()
        source['materials'].append(dict(Name='Unused metal', Model='constant_eps', A=-10, B=1))
        self.assertNotIn('Unused metal', build_job(source, [], {})['materials'])

    def test_lossy_complex_constant_is_rejected(self):
        for mode, a, b in [('constant_eps', 2., .1), ('constant_eps', -2., 0.), ('constant_nk', 1.5, .1)]:
            with self.subTest(mode=mode, a=a), self.assertRaisesRegex(ValueError, 'causal broadband'):
                convert_material(dict(name='metal', model=mode, a=a, b=b), .5, 1., DEFAULTS)

    def test_lorentz_table_fit_is_passive_and_accurate(self):
        wavelengths = np.linspace(900., 2300., 501)
        original = dict(epsilon=2., poles=[dict(frequency=1.3, gamma=.1, strength=.8)])
        nk = np.sqrt(evaluate_medium(original, 1000/wavelengths))
        material = dict(name='Synthetic', model='table_nk', table=np.column_stack((wavelengths, nk.real, nk.imag)).tolist())
        fitted = convert_material(material, 1000/1800, 1000/1200, DEFAULTS)
        self.assertLessEqual(fitted['relative_error'], .05)
        self.assertTrue(all(p['strength'] >= 0 and p['gamma'] > 0 for p in fitted['poles']))
        dense = np.linspace(1000/1800, 1000/1200, 5001)
        self.assertLess(np.max(abs(evaluate_medium(fitted, dense)-evaluate_medium(original, dense))/abs(evaluate_medium(original, dense))), .05)

    def test_material_table_must_cover_band(self):
        with self.assertRaisesRegex(ValueError, 'cover the entire'):
            convert_material(dict(name='short', model='table_nk', table=[[1400, 1.5, 0], [1600, 1.6, 0]]), .5, 1., DEFAULTS)

    def test_dispersion_fit_requires_explicit_option(self):
        with self.assertRaisesRegex(ValueError, 'enable passive'):
            convert_material(dict(name='table', model='table_nk', table=[[900, 1.4, 0], [2100, 1.6, 0]]), .5, 1., dict(DEFAULTS, fit_materials=False))

    def test_circle_2d_slice_is_exact_and_3d_remains_cylinder(self):
        source = project()
        source['patterns'] = [dict(Shape='circle', Layer='Film', Material='Air', CenterX_um=0., CenterY_um=0., SizeX_um=.2, SizeY_um=0., Angle_deg=0.)]
        job = build_job(source, [], dict(section_y_um=.1))
        self.assertAlmostEqual(job['geometry'][1]['width'], 2*np.sqrt(.2**2-.1**2))
        self.assertEqual(job['geometry'][1]['shape'], 'slice')
        job3 = build_job(source, [], dict(dimensions=3))
        self.assertEqual(job3['geometry'][1]['shape'], 'circle')
        self.assertEqual(job3['estimated_cells'], job['estimated_cells']*30)

    def test_periodic_wrapped_geometry_is_preserved(self):
        source = project()
        source['patterns'] = [dict(Shape='circle', Layer='Film', Material='Air', CenterX_um=.49, CenterY_um=0., SizeX_um=.2, SizeY_um=0., Angle_deg=0.)]
        job = build_job(source, [], {})
        self.assertEqual(len(job['geometry']), 3)
        self.assertAlmostEqual(job['geometry'][1]['x'], -.51)

    def test_infinite_pattern_refused(self):
        source = project()
        source['patterns'] = [dict(Shape='circle', Layer='Above', Material='Glass', CenterX_um=0., CenterY_um=0., SizeX_um=.2, SizeY_um=0., Angle_deg=0.)]
        with self.assertRaisesRegex(ValueError, 'finite device layers'):
            build_job(source, [], {})

    def test_resolution_guard_and_invalid_numbers(self):
        with self.assertRaisesRegex(ValueError, 'Estimated grid'):
            build_job(project(), [], dict(dimensions=3, resolution=1000))
        for options in [dict(resolution=30.5), dict(courant=.6), dict(wavelength_min_nm=float('nan')),
                        dict(wavelength_min_nm=2000), dict(dimensions=1), dict(save_fields='yes')]:
            with self.subTest(options=options), self.assertRaises((ValueError, OverflowError)):
                validate_options(options)

    def test_build_does_not_mutate_project(self):
        source = project()
        original = copy.deepcopy(source)
        build_job(source, [], dict(polarization='p'))
        self.assertEqual(source, original)


class RuntimeTests(unittest.TestCase):
    def test_wsl_command_preserves_paths_without_shell(self):
        config = dict(mode='wsl', distro='Ubuntu', python='/home/alice/my env/bin/python', conda='/home/alice/miniforge3/bin/conda')
        self.assertEqual(meep_runtime.command(config, ['--job', '/mnt/c/A B/job.json']),
            ['wsl.exe', '--distribution', 'Ubuntu', '--exec', config['python'], '--job', '/mnt/c/A B/job.json'])

    def test_install_only_managed_environment(self):
        config = dict(mode='wsl', distro='Ubuntu', python='/home/alice/miniforge3/envs/ods-meep/bin/python', conda='/home/alice/miniforge3/bin/conda')
        args = meep_runtime.install_command(config)
        self.assertIn('pymeep', args)
        self.assertIn('--override-channels', args)
        with self.assertRaisesRegex(ValueError, 'protect other'):
            meep_runtime.install_command(dict(config, python='/usr/bin/python'))

    def test_probe_requires_actual_meep_version(self):
        result = type('Result', (), dict(returncode=0, stdout='some other package', stderr=''))()
        with patch('meep_runtime.subprocess.run', return_value=result):
            self.assertFalse(meep_runtime.probe()['available'])

    def test_worker_source_is_delivered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = meep_runtime.copy_runner(tmp)
            self.assertIn('load_minus_flux_data', path.read_text(encoding='utf-8'))


class RunnerContractTests(unittest.TestCase):
    def test_reference_subtraction_and_power_signs(self):
        """A controlled API double checks accounting, not solver correctness."""
        import meep_runner
        source = project()
        job = build_job(source, [], dict(frequency_points=3, save_fields=False))
        simulations = []
        class Sim:
            def __init__(self, **kwargs):
                self.arguments = kwargs
                self.phase = len(simulations)
                self.fields = SimpleNamespace(last_source_time=lambda: 20.)
                self.monitors = []
                simulations.append(self)
            def add_flux(self, fcen, df, count, region):
                flux = SimpleNamespace(phase=self.phase, index=len(self.monitors), fcen=fcen, df=df, count=count)
                self.monitors.append(flux)
                return flux
            def get_flux_data(self, flux):
                return 'saved-reference-fields'
            def load_minus_flux_data(self, flux, data):
                self.subtracted = data
            def meep_time(self):
                return 120.
            def run(self, tick, until_after_sources):
                tick(self)
                assert until_after_sources(self)
            def reset_meep(self):
                pass
        def values(flux):
            if flux.phase == 0:
                return [100., 100., 100.]
            return [-25., -25., -25.] if flux.index==0 else [60., 60., 60.]
        def record(*args, **kwargs):
            return SimpleNamespace(args=args, **kwargs)
        mp = SimpleNamespace(__version__='test-double', inf=float('inf'), Y='Y', Z='Z', Ez='Ez', Ey='Ey', Ex='Ex',
            Vector3=lambda x=0,y=0,z=0: (x,y,z), Medium=record, Block=record,
            LorentzianSusceptibility=record, DrudeSusceptibility=record,
            GaussianSource=record, Source=record, PML=record, FluxRegion=record,
            Simulation=Sim, at_every=lambda dt, tick: tick,
            stop_when_fields_decayed=lambda *args: lambda sim: True,
            get_fluxes=values, get_flux_freqs=lambda f: np.linspace(f.fcen-f.df/2, f.fcen+f.df/2, f.count))
        with tempfile.TemporaryDirectory() as tmp, patch('meep_runner.event'):
            meep_runner.run(job, tmp, mp)
            rows = np.genfromtxt(Path(tmp)/'results.csv', names=True, delimiter=',')
        self.assertEqual(simulations[0].arguments['geometry'], [])
        self.assertEqual(simulations[1].subtracted, 'saved-reference-fields')
        self.assertTrue(np.allclose(rows['R'], .25))
        self.assertTrue(np.allclose(rows['T'], .6))
        self.assertTrue(np.allclose(rows['A'], .15))
        self.assertTrue(np.all(np.diff(rows['wavelength_nm'])>0))
        self.assertEqual(simulations[1].arguments['geometry'][1].size[2], float('inf'))


@unittest.skipUnless(importlib.util.find_spec('meep'), 'Real Meep requires a configured Linux/WSL runtime')
class RealMeepTests(unittest.TestCase):
    def test_uniform_air_has_unit_transmission(self):
        from meep_runner import run
        source = project()
        source['layers'][1]['Material'] = 'Air'
        job = build_job(source, [], dict(resolution=20, frequency_points=11, run_after_sources=100., save_fields=False))
        with tempfile.TemporaryDirectory() as tmp:
            info = run(job, tmp)
            result = np.genfromtxt(Path(tmp)/'results.csv', names=True, delimiter=',')
            self.assertLess(np.max(abs(result['R'])), .01)
            self.assertLess(np.max(abs(result['T']-1)), .02)
            self.assertEqual(info['engine'], 'Meep')


if __name__ == '__main__':
    unittest.main()
