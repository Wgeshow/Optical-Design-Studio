"""Reuse S4's complete Fourier field vector once per depth plane.

The native grid omits the Bloch phase/origin shift and some builds reverse Hz.
Recover every retained harmonic on a sufficiently large grid, validate against
GetFields, then evaluate the same finite Fourier sum at the requested points.
This changes neither the RCWA basis nor the sample coordinates.
"""
from collections import OrderedDict
import math
import numpy as np

from model import epsilon


class FourierFieldSampler:
    def __init__(self, simulation, model, wavelength, enabled=True):
        self.simulation = simulation
        self.ax, self.ay = model['ax'], model['ay']
        self.cache = OrderedDict()
        self.enabled = enabled and hasattr(simulation, 'GetFieldsOnGrid')
        self.validated = False
        self.sign_validated = False
        self.hz_sign = 1
        self.stats = dict(method='point', plane_calls=0, point_calls=0,
                          validation_relative_error=None, fallback_reason=None)
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

    def _plane(self, z):
        if not self.enabled:
            return None
        z = float(z)
        if z in self.cache:
            self.cache.move_to_end(z)
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

    def grid(self, xs, ys, z):
        coefficients = self._plane(z)
        if coefficients is None:
            values = np.array([np.asarray(self._direct(x, y, z)).ravel() for x in xs for y in ys]).reshape(len(xs), len(ys), 6)
        else:
            # Fold ALL orders onto the requested output grid, including when
            # the output grid is smaller than the basis. No orders are dropped.
            shape = (len(xs), len(ys), 6)
            spectrum = np.zeros(shape, dtype=complex)
            shift = np.exp(2j*np.pi*(self.g[:, 0]*xs[0]/self.ax + self.g[:, 1]*ys[0]/self.ay))
            np.add.at(spectrum, (self.g[:, 0] % len(xs), self.g[:, 1] % len(ys)), coefficients*shift[:, None])
            values = np.fft.ifftn(spectrum, axes=(0, 1), norm='forward')
            values *= np.exp(1j*(self.kx*np.asarray(xs)[:, None] + self.ky*np.asarray(ys)[None, :]))[:, :, None]
        return values[:, :, :3], values[:, :, 3:]
