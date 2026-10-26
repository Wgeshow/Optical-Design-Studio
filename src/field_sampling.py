"""Reuse S4's complete Fourier field vector once per depth plane.

The native grid omits the Bloch phase/origin shift and some builds reverse Hz.
Recover every retained harmonic on a sufficiently large grid, validate against
GetFields, then evaluate the same finite Fourier sum at the requested points.
This changes neither the RCWA basis nor the sample coordinates.
"""
from collections import OrderedDict
import math
import numpy as np
from field_reconstruction import harmonic_plan, synthesize_cpu, contract_y, CudaSynthesis
from threadpoolctl import threadpool_limits

from model import epsilon


class FourierFieldSampler:
    def __init__(self, simulation, model, wavelength, enabled=True, threads=1,
                 gpu=False, gpu_device=0, batch_planes=8):
        self.simulation = simulation
        self.ax, self.ay = model['ax'], model['ay']
        self.cache = OrderedDict()
        self.enabled = enabled and hasattr(simulation, 'GetFieldsOnGrid')
        self.native_enabled = self.enabled and hasattr(simulation, 'GetFieldCoefficientsMany')
        self.validated = False
        self.sign_validated = False
        self.hz_sign = 1
        self.threads = max(1, int(threads))
        self.gpu_requested = bool(gpu)
        self.gpu_device = int(gpu_device)
        self.batch_planes = max(1, min(8, int(batch_planes)))
        self.plans = OrderedDict()
        self.grid_cache = {}
        self.cuda = None
        self.cuda_plan_key = None
        self.stats = dict(method='point', plane_calls=0, point_calls=0,
                          validation_relative_error=None, fallback_reason=None,
                          native_batch_calls=0, native_fallback_reason=None,
                          reconstruction='separable_complex128', cpu_grid_calls=0,
                          gpu_grid_batches=0, gpu_grid_planes=0, gpu_failures=0,
                          gpu_fallback_reason=None, gpu_peak_device_bytes=0,
                          gpu_transfer_bytes=0, reconstruction_threads=self.threads)
        if not self.enabled:
            return
        self.g = np.asarray(simulation.GetBasisSet(), dtype=int)
        # Odd dimensions preserve both positive and negative extreme orders.
        self.shape = tuple(map(int, 2*np.max(np.abs(self.g), axis=0)+1))
        incident = next(m for m in model['materials'] if m['name'] == model['layers'][0]['material'])
        theta, phi = math.radians(model['points'][0][2]), math.radians(model['phi'])
        k = 2*math.pi*1000/wavelength * complex(epsilon(incident, wavelength))**.5
        k = k.real*math.sin(theta)  # same real sqrt(epsilon) convention as S4
        self.kx, self.ky = k*math.cos(phi), k*math.sin(phi)
        self.wavevectors = self.g * np.array([2*math.pi/self.ax, 2*math.pi/self.ay])
        self.wavevectors += np.array([self.kx, self.ky])

    def _direct(self, x, y, z):
        self.stats['point_calls'] += 1
        return self.simulation.GetFields(float(x), float(y), float(z))

    def _evaluate(self, xy, coefficients):
        return np.exp(1j*(np.asarray(xy, dtype=float) @ self.wavevectors.T)) @ coefficients

    def prepare_planes(self, depths):
        """Fetch at most eight native coefficient planes without any FFT roundtrip."""
        if not self.native_enabled or not self.enabled:
            return
        pending = list(dict.fromkeys(float(z) for z in depths if float(z) not in self.cache))
        # Cache and workspace bounds stay independent of the scan length.
        for start in range(0, len(pending), 8):
            batch = pending[start:start+8]
            try:
                packed = self.simulation.GetFieldCoefficientsMany(batch)
                self.stats['native_batch_calls'] += 1
                coefficients = np.frombuffer(packed, dtype=np.complex128).reshape(len(batch), len(self.g), 6)
                if not np.isfinite(coefficients).all():
                    raise ValueError('Nonfinite native field coefficients')
                if not self.validated:
                    xy = np.array([[.123*self.ax, .217*self.ay], [-.31*self.ax, .17*self.ay], [.47*self.ax, -.37*self.ay]])
                    expected = np.array([np.asarray(self._direct(x, y, batch[0])).ravel() for x, y in xy])
                    actual = self._evaluate(xy, coefficients[0])
                    if not np.allclose(actual, expected, rtol=2e-9, atol=2e-11):
                        raise ValueError('Native coefficients do not match scalar E/H')
                    self.stats['validation_relative_error'] = float(np.max(np.abs(actual-expected))/max(np.max(np.abs(expected)), 1e-30))
                    self.validated = self.sign_validated = True
                for z, values in zip(batch, coefficients):
                    self.cache[z] = values.copy()
                    self.stats['plane_calls'] += 1
                    if len(self.cache) > 8:
                        self.cache.popitem(last=False)
                self.stats['method'] = 'validated_native_coefficients'
            except (ValueError, TypeError, RuntimeError, AttributeError) as exc:
                # Older runtimes and a mismatching new API retain the established
                # validated grid path; no field values are silently substituted.
                self.native_enabled = False
                self.validated = self.sign_validated = False
                self.hz_sign = 1
                self.cache.clear()
                self.grid_cache.clear()
                self.stats['native_fallback_reason'] = str(exc)
                self.stats['method'] = 'point'
                return

    def _plane(self, z):
        if not self.enabled:
            return None
        z = float(z)
        if z in self.cache:
            self.cache.move_to_end(z)
            return self.cache[z]
        if self.native_enabled:
            self.prepare_planes([z])
            if z in self.cache:
                return self.cache[z]
        self.stats['plane_calls'] += 1
        e, h = self.simulation.GetFieldsOnGrid(z, self.shape, 'Array')
        raw = np.concatenate((np.asarray(e, dtype=complex), np.asarray(h, dtype=complex)), axis=2)
        spectrum = np.fft.fftn(raw, axes=(0, 1))/(self.shape[0]*self.shape[1])
        coefficients = spectrum[self.g[:, 0] % self.shape[0], self.g[:, 1] % self.shape[1]].copy()
        if not self.validated or not self.sign_validated:
            xy = np.array([[.123*self.ax, .217*self.ay], [-.31*self.ax, .17*self.ay], [.47*self.ax, -.37*self.ay]])
            expected = np.array([np.asarray(self._direct(x, y, z)).ravel() for x, y in xy])
            matches = []
            for sign in (-1, 1):
                trial = coefficients.copy()
                trial[:, 5] *= sign
                actual = self._evaluate(xy, trial)
                if np.isfinite(actual).all() and np.allclose(actual, expected, rtol=2e-9, atol=2e-11):
                    matches.append((sign, float(np.max(np.abs(actual-expected))/max(np.max(np.abs(expected)), 1e-30))))
            if not matches:
                self.enabled = False
                self.stats['method'] = 'point'
                self.stats['fallback_reason'] = 'Native Fourier grid did not match scalar E and H; using GetFields.'
                return None
            sign,error = matches[0]
            if sign != self.hz_sign:
                self.cache.clear()
            self.hz_sign = sign
            # A uniform first layer can have Hz=0 at every check point. Keep
            # calibrating subsequent planes until the two signs differ.
            self.sign_validated = len(matches) == 1
            self.stats['validation_relative_error'] = max(self.stats['validation_relative_error'] or 0.,error)
            self.stats['method'] = 'validated_fourier_planes'
            self.validated = True
        coefficients[:, 5] *= self.hz_sign
        self.cache[z] = coefficients
        if len(self.cache) > 8:
            self.cache.popitem(last=False)
        return coefficients

    def GetFields(self, x, y, z):
        # Isolated depth-profile points do not need a whole plane extraction.
        if not self.enabled or float(z) not in self.cache:
            return self._direct(x, y, z)
        values = self._evaluate([[x, y]], self._plane(z))[0]
        return values[:3], values[3:]

    def GetFieldsMany(self, xy, z):
        coefficients = self._plane(z)
        if coefficients is None:
            values = np.array([np.asarray(self._direct(x, y, z)).ravel() for x, y in xy])
        else:
            values = self._evaluate(xy, coefficients)
        return values[:, :3], values[:, 3:]

    def _plan(self, xs, ys):
        xs, ys = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
        key = (xs.tobytes(), ys.tobytes())
        if key not in self.plans:
            self.plans[key] = harmonic_plan(self.g, xs, ys, self.ax, self.ay, self.kx, self.ky)
            if len(self.plans) > 2:
                self.plans.popitem(last=False)
        self.plans.move_to_end(key)
        return key, self.plans[key]

    def prepare_grid(self, xs, ys, depths):
        """Prefetch a bounded GPU batch; scalar/native calls stay on the owner thread."""
        self.prepare_planes(depths)
        self.grid_cache.clear()
        if not self.enabled or not self.gpu_requested or len(xs)*len(ys) < 16384:
            return
        depths = list(dict.fromkeys(map(float, depths)))[:self.batch_planes]
        if not depths or any(z not in self.cache for z in depths):
            return
        key, plan = self._plan(xs, ys)
        try:
            if self.cuda is None or self.cuda_plan_key != key:
                if self.cuda is not None:
                    self.cuda.close()
                self.cuda = CudaSynthesis(plan[0], self.gpu_device)
                self.cuda_plan_key = key
            with threadpool_limits(limits=self.threads, user_api='blas'):
                middle = contract_y(plan, np.asarray([self.cache[z] for z in depths]), separate=True)
            values = self.cuda.multiply(middle).reshape(len(depths), 2, len(xs), len(ys), 3)
            # Check the new arithmetic on each plane before trusting the GPU.
            for plane, z in zip(values, depths):
                for i, j in ((0, 0), (len(xs)//2, len(ys)//2), (len(xs)-1, len(ys)-1)):
                    expected = self._evaluate([[xs[i], ys[j]]], self.cache[z])[0]
                    actual = np.asarray([plane[0, i, j], plane[1, i, j]]).ravel()
                    if not np.allclose(actual, expected, rtol=2e-9, atol=2e-11):
                        raise ValueError('GPU Fourier synthesis did not match complex128 coefficients')
            self.grid_cache = {(key, z): (plane[0], plane[1]) for z, plane in zip(depths, values)}
            self.stats['reconstruction'] = 'separable_complex128_cpu_cuda'
            self.stats['gpu_grid_batches'] += 1
            self.stats['gpu_grid_planes'] += len(depths)
            self.stats['gpu_peak_device_bytes'] = max(self.stats['gpu_peak_device_bytes'], self.cuda.peak_device_bytes)
            self.stats['gpu_transfer_bytes'] += middle.nbytes + values.nbytes
        except (RuntimeError, ValueError, OSError, AttributeError) as exc:
            self.stats['gpu_failures'] += 1
            self.stats['gpu_fallback_reason'] = str(exc)
            self.gpu_requested = False
            self.grid_cache.clear()
            if self.cuda is not None:
                self.cuda.close()
                self.cuda = None

    def close(self):
        self.grid_cache.clear()
        if self.cuda is not None:
            self.cuda.close()
            self.cuda = None

    def grid(self, xs, ys, z):
        coefficients = self._plane(z)
        if coefficients is None:
            values = np.array([np.asarray(self._direct(x, y, z)).ravel() for x in xs for y in ys]).reshape(len(xs), len(ys), 6)
        else:
            key, plan = self._plan(xs, ys)
            cached = self.grid_cache.get((key, float(z)))
            if cached is not None:
                return cached
            elif self.gpu_requested and len(xs)*len(ys) >= 16384:
                self.prepare_grid(xs, ys, [z])
                values = self.grid_cache.get((key, float(z)))
                if values is not None:
                    return values
                if values is None:
                    values = synthesize_cpu(plan, coefficients[None], self.threads)[0]
                    self.stats['cpu_grid_calls'] += 1
            else:
                values = synthesize_cpu(plan, coefficients[None], self.threads)[0]
                self.stats['cpu_grid_calls'] += 1
        return values[:, :, :3], values[:, :, 3:]
