"""Scan-cache and complete-field adapter integration checks.

Optional native comparison:
  S4_EIGENFREE_TEST_RUNTIME=<directory containing S4.cp312-win_amd64.pyd>
  S4_DLL_DIRS=<MKL DLL directory>
The native comparison uses a small Fourier basis and the NumPy backend.
"""
import contextlib
import importlib.util
import math
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from eigenfree_scan import FieldView, execute


class ScanCacheTests(unittest.TestCase):
    def run_scan(self, points, dispersive=False,unavailable_wave=None):
        captured, exports, material_updates = [], [], []

        class Simulation:
            wave, theta, eps = points[0][1], 0., 2.

            def SetFrequency(self, frequency):
                self.wave = 1000./frequency

            def SetExcitationPlanewave(self, IncidenceAngles, **unused):
                self.theta = IncidenceAngles[0]

            def SetMaterial(self, Name, Epsilon):
                self.eps = Epsilon
                material_updates.append((Name, Epsilon))

            def GetEigenfreeOperators(self):
                exports.append((self.wave, self.theta, self.eps))
                return dict(omega=2*math.pi*1000/self.wave,
                            kx=[math.sin(math.radians(self.theta))/self.wave],
                            source_theta=self.theta, constitutive=self.eps)

        class Result:
            diagnostics = dict(backend='test')

            def __init__(self, payloads):
                self.payloads = payloads

            def rta(self):
                return np.tile([.2, .7, .1], (len(self.payloads), 1))

        def solve(payloads, **unused):
            if unavailable_wave is not None and any(abs(p['omega']-2*math.pi*1000/unavailable_wave)<1e-12 for p in payloads):
                raise ValueError('Exterior diffraction threshold needs native fallback')
            captured.extend(dict(p) for p in payloads)
            return Result(payloads)

        simulation = Simulation()
        material = dict(name='film', model='table_nk' if dispersive else 'constant_nk')
        epsilon = lambda spec, wave: 2.+(wave-points[0][1])*.001 if dispersive else 2.
        fake_cp = types.SimpleNamespace(__version__='test',cuda=types.SimpleNamespace(
            Device=lambda index: contextlib.nullcontext(),
            get_current_stream=lambda: types.SimpleNamespace(synchronize=lambda: None)))
        runtime = types.SimpleNamespace(New=lambda **kwargs: simulation)
        config = dict(chunk_size=2, gpu_device=0, timeout_seconds=60, threads=1)
        model = dict(points=points, materials=[material], phi=23., polarization='p',allow_unavailable_points=unavailable_wave is not None)
        with patch.dict(sys.modules, {'cupy': fake_cp}), \
             patch('backend.load_runtime', return_value=runtime), \
             patch('backend.build_simulation', return_value=simulation), \
             patch('model.performance', side_effect=lambda p, *args: dict(config, **p)), \
             patch('model.epsilon', side_effect=epsilon), \
             patch('s4_eigenfree_gpu.solve_batch', side_effect=solve):
            rows, info = execute(model, {}, lambda event: None, lambda: False)
        self.assertEqual(len(rows), len(points))
        self.assertEqual(info['points'], len(points))
        if unavailable_wave is not None:
            self.assertEqual(info['unavailable_points'],1)
            missing=next(row for row in rows if row[1]==unavailable_wave)
            self.assertEqual(missing[3:],[None]*3)
            self.assertEqual(info['gpu_solved_points'],len(points)-1)
        return captured, exports, material_updates

    def test_singular_gpu_batch_is_split_without_losing_its_valid_neighbors(self):
        points=[[0,900.,0.],[1,910.,0.],[2,920.,0.]]
        captured,exports,updates=self.run_scan(points,unavailable_wave=910.)
        self.assertEqual(len(captured),2)

    def test_normal_template_survives_interleaved_oblique_batches(self):
        points = [[0, 900., 0.], [1, 910., 12.], [2, 920., 0.],
                  [3, 930., -7.], [4, 940., 0.]]
        captured, exports, updates = self.run_scan(points)
        self.assertEqual(len(exports), 3)
        self.assertEqual(updates, [])
        for item, (_, wave, theta) in zip(captured, points):
            self.assertAlmostEqual(item['omega'], 2*math.pi*1000/wave, places=13)
            self.assertEqual(item['source_theta'], theta)
            self.assertAlmostEqual(item['kx'][0], math.sin(math.radians(theta))/wave, places=16)
            self.assertEqual(item['constitutive'], 2.)

    def test_dispersive_normal_points_refresh_exact_constitutives(self):
        points = [[i, wave, 0.] for i, wave in enumerate([900., 910., 910., 930.])]
        captured, exports, updates = self.run_scan(points, dispersive=True)
        self.assertEqual(len(exports), 4)
        self.assertEqual(len(updates), 2)
        for item, (_, wave, _) in zip(captured, points):
            self.assertEqual(item['constitutive'], 2.+(wave-900)*.001)


class AdapterDepthTests(unittest.TestCase):
    def test_upper_side_interfaces_and_exterior_depths(self):
        view = FieldView(None, 0, dict(layers=[dict(thickness=0.),
                        dict(thickness=.25), dict(thickness=.17), dict(thickness=0.)]))
        for z, expected in [(-.03,(0,-.03)), (0.,(0,0.)), (.1,(1,.1)),
                            (.25,(1,.25)), (.42,(2,.17)), (.45,(3,.03))]:
            layer, depth = view._layer(z)
            self.assertEqual(layer, expected[0])
            self.assertAlmostEqual(depth, expected[1], places=14)


@unittest.skipUnless(os.environ.get('S4_EIGENFREE_TEST_RUNTIME'), 'optional native S4 runtime not configured')
class NativeFieldAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dll_handles = []
        if os.name == 'nt':
            for directory in os.environ.get('S4_DLL_DIRS', '').split(os.pathsep):
                if directory:
                    cls.dll_handles.append(os.add_dll_directory(directory))
        root = Path(os.environ['S4_EIGENFREE_TEST_RUNTIME'])
        binary = next(root.glob('S4*.pyd'))
        spec = importlib.util.spec_from_file_location('S4', binary)
        cls.native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.native)

    def test_complete_fields_and_sampler_across_layers_and_angles(self):
        from field_sampling import FourierFieldSampler
        from s4_eigenfree_gpu import solve_batch
        for theta in (0., 13.):
            simulation = self.native.New(Lattice=((.77,0.),(0.,.77)), NumBasis=9)
            simulation.SetMaterial(Name='air', Epsilon=1.)
            simulation.SetMaterial(Name='film', Epsilon=(3.4+.015j)**2)
            simulation.SetMaterial(Name='glass', Epsilon=2.25)
            simulation.AddLayer(Name='top', Thickness=0., S4_Material='air')
            simulation.AddLayer(Name='film', Thickness=.25, S4_Material='film')
            simulation.SetRegionCircle(S4_Layer='film', S4_Material='air', Center=(0.,0.), Radius=.1)
            simulation.AddLayer(Name='bottom', Thickness=0., S4_Material='glass')
            simulation.SetFrequency(1000./1050.)
            simulation.SetExcitationPlanewave(IncidenceAngles=(theta,23.), sAmplitude=.3+.1j, pAmplitude=-1., Order=0)
            payload = simulation.GetEigenfreeOperators()
            solution = solve_batch([payload], backend='numpy', symmetry=True)
            view = FieldView(solution,0,payload)
            depths = [-.03,0.,.04,.249,.25,.29]
            expected = np.frombuffer(simulation.GetFieldCoefficientsMany(depths), np.complex128)
            actual = np.frombuffer(view.GetFieldCoefficientsMany(depths), np.complex128)
            np.testing.assert_allclose(actual,expected,atol=3e-10,rtol=3e-9)
            for z in depths:
                np.testing.assert_allclose(view.GetFields(.123,-.091,z),simulation.GetFields(.123,-.091,z),atol=3e-10,rtol=3e-9)
            model = dict(ax=.77,ay=.77,phi=23.,points=[[0,1050.,theta]],
                         materials=[dict(name='air',model='constant_eps',eps_real=1.,eps_imag=0.)],
                         layers=[dict(material='air')])
            # Use the same scalar ambient epsilon as the native simulation;
            # the sampler's geometry contract is independent of material UI keys.
            with patch('field_sampling.epsilon',return_value=1.):
                sampler = FourierFieldSampler(view,model,1050.,threads=1,gpu=False)
                sampler.prepare_planes(depths)
                self.assertTrue(sampler.native_enabled)
                self.assertEqual(sampler.stats['method'],'validated_native_coefficients')
                xy=np.array([[.13,.21],[-.31,.17],[.47,-.37]])
                e,h=sampler.GetFieldsMany(xy,.04)
                actual=np.concatenate((e,h),axis=1)
                expected=np.array([np.asarray(simulation.GetFields(x,y,.04)).ravel() for x,y in xy])
                np.testing.assert_allclose(actual,expected,atol=3e-10,rtol=3e-9)


if __name__ == '__main__':
    unittest.main()
