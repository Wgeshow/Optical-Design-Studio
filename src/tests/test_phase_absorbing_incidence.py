"""Native phase must use the real transverse wavevector of S4's source."""
import cmath
import math
import unittest

import numpy as np

from backend import build_simulation, load_runtime
from model import DEFAULT_PERFORMANCE
from spectral_phase import measure_phase


class AbsorbingIncidentPhaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime(DEFAULT_PERFORMANCE)

    @staticmethod
    def model(indices, thickness=.22):
        return dict(materials=[dict(name=f'M{i}', model='constant_nk', a=n.real, b=n.imag)
                               for i, n in enumerate(map(complex, indices))],
                    layers=[dict(name='Incident', material='M0', thickness=0.),
                            dict(name='Film', material='M1', thickness=thickness),
                            dict(name='Exit', material='M2', thickness=0.)],
                    patterns=[], ax=.3, ay=.3, basis=9, phi=29.)

    def simulation(self, model, polarization, theta):
        simulation = build_simulation(self.module, model, 1300.)
        simulation.SetFrequency(1000./1300.)
        s, p = {'s': (1., 0.), 'p': (0., -1.), 'mixed': (2**-.5, -2**-.5)}[polarization]
        simulation.SetExcitationPlanewave(IncidenceAngles=(theta, model['phi']),
                                         sAmplitude=complex(s), pAmplitude=complex(p), Order=0)
        return simulation

    @staticmethod
    def analytic(indices, thickness, theta, phi, incident):
        # S4's angle source has real k_parallel even when n_incident is complex.
        transverse = complex(indices[0]).real*math.sin(math.radians(theta))
        q = [cmath.sqrt(n*n-transverse*transverse) for n in indices]
        q = [-v if v.imag < 0 else v for v in q]
        propagation = cmath.exp(1j*2*math.pi*1000/1300*q[1]*thickness)
        coefficients = []
        for y in (q, [n*n/v for n, v in zip(indices, q)]):
            r01, r12 = (y[0]-y[1])/(y[0]+y[1]), (y[1]-y[2])/(y[1]+y[2])
            denominator = 1+r01*r12*propagation**2
            coefficients.append(((r01+r12*propagation**2)/denominator,
                                 2*y[0]/(y[0]+y[1])*2*y[1]/(y[1]+y[2])*propagation/denominator))
        azimuth = math.radians(phi)
        s = np.array([-math.sin(azimuth), math.cos(azimuth)])
        p = np.array([math.cos(azimuth), math.sin(azimuth)])
        weights = [abs(incident@s)**2, abs(incident@p)**2]
        return [sum(w*c[i] for w, c in zip(weights, coefficients))/sum(weights) for i in (0, 1)]

    def verify_polarization(self, polarization):
        indices = [1.5+.25j, 2.2+.15j, 1.1+0j]
        model = self.model(indices)
        reference = self.model([indices[0]]*3, thickness=0.)
        for theta in (17., 37.):
            with self.subTest(polarization=polarization, theta=theta):
                simulation = self.simulation(model, polarization, theta)
                empty = self.simulation(reference, polarization, theta)
                # Independent native total E, without interpreting modal H arrays.
                incident = np.asarray(empty.GetFields(0., 0., 0.)[0][:2])
                reflected = np.asarray(simulation.GetFields(0., 0., 0.)[0][:2])-incident
                offset = 1e-6
                transmitted = np.asarray(simulation.GetFields(0., 0., .22+offset)[0][:2])
                qout = cmath.sqrt(indices[-1]**2-(indices[0].real*math.sin(math.radians(theta)))**2)
                transmitted *= cmath.exp(-1j*2*math.pi*1000/1300*qout*offset)
                norm = np.vdot(incident, incident)
                fields = [np.vdot(incident, value)/norm for value in (reflected, transmitted)]
                analytic = self.analytic(indices, .22, theta, model['phi'], incident)
                np.testing.assert_allclose(fields, analytic, atol=2e-13, rtol=2e-13)
                observed = measure_phase(simulation, model, 1300., theta)
                for phase, coefficient in zip(observed, analytic):
                    self.assertIsNotNone(phase)
                    error = cmath.phase(cmath.exp(1j*math.radians(phase))/coefficient)
                    self.assertLess(abs(error), 2e-12)

    def test_s_phase_matches_fields_and_fresnel(self):
        self.verify_polarization('s')

    def test_p_phase_matches_fields_and_fresnel(self):
        self.verify_polarization('p')

    def test_mixed_phase_matches_fields_and_fresnel(self):
        self.verify_polarization('mixed')


if __name__ == '__main__':
    unittest.main()
