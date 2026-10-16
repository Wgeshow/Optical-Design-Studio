"""Full-order synthesis, irregular grids, batched GPU lifetime and fallback."""
import math
import os
import unittest
from unittest.mock import patch

import numpy as np

from field_reconstruction import harmonic_plan, synthesize_cpu
from field_sampling import FourierFieldSampler
from model import epsilon
from tests.test_backend import sample


class Harmonics:
    def __init__(self, model, wavelength):
        self.g = np.asarray([(0, 0), (-7, 3), (9, -11), (2, 4), (-3, -5)])
        incident = next(m for m in model['materials'] if m['name'] == model['layers'][0]['material'])
        k = (2*math.pi*1000/wavelength * complex(epsilon(incident, wavelength))**.5).real
        k *= math.sin(math.radians(model['points'][0][2]))
        phi = math.radians(model['phi'])
        self.wv = self.g * [2*np.pi/model['ax'], 2*np.pi/model['ay']] + [k*math.cos(phi), k*math.sin(phi)]

    def coefficients(self, z):
        values = np.arange(30).reshape(5, 6)*.01 + 1j*np.arange(30, 60).reshape(5, 6)*.002
        return values*np.exp((.1+.7j)*z)

    def GetBasisSet(self):
        return self.g

    def GetFieldsOnGrid(self, *args):
        raise AssertionError('Native coefficient path should avoid a grid FFT')

    def GetFieldCoefficientsMany(self, depths):
        return np.asarray([self.coefficients(z) for z in depths], np.complex128).tobytes()

    def GetFields(self, x, y, z):
        value = (np.exp(1j*(self.wv @ [x, y]))[:, None]*self.coefficients(z)).sum(axis=0)
        return value[:3], value[3:]


class ReconstructionTests(unittest.TestCase):
    def sampler(self, **kwargs):
        model = sample(theta_deg=23, phi_deg=37, ay_um=.57)
        sim = Harmonics(model, 1050.)
        return FourierFieldSampler(sim, model, 1050., **kwargs), sim

    def check_grid(self, sampler, sim, xs, ys, z):
        e, h = sampler.grid(xs, ys, z)
        expected = np.asarray([[sim.GetFields(x, y, z) for y in ys] for x in xs])
        np.testing.assert_allclose(e, expected[:, :, 0], rtol=2e-10, atol=2e-12)
        np.testing.assert_allclose(h, expected[:, :, 1], rtol=2e-10, atol=2e-12)
        return e.copy(), h.copy()

    def test_irregular_rectangular_small_grid_keeps_high_orders_and_bloch_phase(self):
        sampler, sim = self.sampler(threads=2)
        for z in (.0005, .12, .2495):
            self.check_grid(sampler, sim, [-.29, -.031, .247], [-.2, -.123, .003, .049, .14], z)
        self.assertEqual(sampler.stats['cpu_grid_calls'], 3)
        self.assertEqual(len(sampler.plans), 1)

    def test_duplicate_harmonics_accumulate_and_distinct_depths_remain_distinct(self):
        g = np.asarray([(0, 0), (-8, 4), (-8, 4), (2, -9)])
        xs, ys = np.asarray([-.2, .01, .23]), np.asarray([-.13, .029])
        plan = harmonic_plan(g, xs, ys, .77, .57, .7, -.4)
        coefficients = np.arange(72).reshape(3, 4, 6).astype(np.complex128)*(1+.3j)
        result = synthesize_cpu(plan, coefficients, threads=2)
        wv = g*[2*np.pi/.77, 2*np.pi/.57] + [.7, -.4]
        for b in range(3):
            for i, x in enumerate(xs):
                for j, y in enumerate(ys):
                    expected = (np.exp(1j*(wv @ [x, y]))[:, None]*coefficients[b]).sum(axis=0)
                    np.testing.assert_allclose(result[b, i, j], expected, rtol=2e-12, atol=2e-12)

    def test_gpu_failure_is_visible_and_returns_correct_cpu_fields(self):
        sampler, sim = self.sampler(gpu=True)
        xs, ys = np.linspace(-.3, .3, 130), np.linspace(-.2, .2, 130)
        with patch('field_sampling.CudaSynthesis', side_effect=RuntimeError('device unavailable')):
            sampler.prepare_grid(xs, ys, [.01, .12])
        self.check_grid(sampler, sim, xs, ys, .12)
        self.assertEqual(sampler.stats['gpu_failures'], 1)
        self.assertEqual(sampler.stats['gpu_grid_batches'], 0)
        self.assertIn('device unavailable', sampler.stats['gpu_fallback_reason'])
        self.assertFalse(sampler.gpu_requested)

    @unittest.skipUnless(os.environ.get('S4_FIELD_TEST_GPU') == '1', 'Requires explicitly selected CUDA test device')
    def test_real_cuda_batches_preserve_all_components_and_returned_array_lifetime(self):
        sampler, sim = self.sampler(gpu=True, threads=2)
        xs, ys = np.linspace(-.3, .3, 130), np.linspace(-.2, .2, 131)
        sampler.prepare_grid(xs, ys, [.01, .12, .24])
        self.assertEqual(sampler.stats['gpu_grid_planes'], 3)
        e, h = sampler.grid(xs, ys, .01)
        self.assertTrue(e.flags.c_contiguous and h.flags.c_contiguous)
        before_e, before_h = e.copy(), h.copy()
        for z in (.01, .12, .24):self.check_grid(sampler, sim, xs, ys, z)
        # Coordinate changes replace resident phase/workspace without changing
        # views returned by a previous batch, even after explicit resource cleanup.
        sampler.prepare_grid(xs[:129], ys, [.02, .13])
        self.assertEqual(sampler.stats['gpu_grid_batches'], 2)
        self.assertEqual(sampler.stats['gpu_failures'], 0)
        sampler.close()
        np.testing.assert_array_equal(e, before_e)
        np.testing.assert_array_equal(h, before_h)


if __name__ == '__main__':
    unittest.main()
