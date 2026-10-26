"""Independent Maxwell-transfer references for the eigenfree scattering backend."""
import unittest
import numpy as np
from scipy.linalg import expm
from s4_eigenfree_gpu import solve_batch


def payload(epsilon=4, thickness=.125, n=1):
    kx = np.linspace(0, .8, n)
    ky = np.linspace(0, -.3, n)
    layers = []
    for e, d in ((1, 0), (epsilon, thickness), (1.5, 0)):
        layers.append(dict(epsilon=e, uniform=True, thickness=d,
                           epsilon_inv=np.eye(n)/e, epsilon2=np.eye(2*n)*e))
    a = np.zeros(2*n, complex)
    a[n] = 1
    return dict(n=n, omega=2*np.pi, kx=kx, ky=ky,
                excitation_h=a, backwards=False, layers=layers)


class EigenfreeTests(unittest.TestCase):
    def test_quarter_wave(self):
        p = payload()
        p['layers'][-1] = dict(p['layers'][0])
        s = solve_batch([p], backend='numpy')
        np.testing.assert_allclose(s.rta()[0], [.36, .64, 0], atol=2e-14)

    def test_general_coupled_operator_fields(self):
        rng = np.random.default_rng(174)
        p = payload(3+.2j, .035, n=3)
        middle = p['layers'][1]
        middle['uniform'] = False
        middle['epsilon2'] += .07*(rng.normal(size=(6, 6))+1j*rng.normal(size=(6, 6)))
        middle['epsilon_inv'] += .01*(rng.normal(size=(3, 3))+1j*rng.normal(size=(3, 3)))
        s = solve_batch([p], backend='numpy')
        slab = s.pieces[1]
        doubled = s._double_slab(slab)
        general = s.star(slab, slab)
        for name in ('r', 'u', 't', 'v'):
            np.testing.assert_allclose(getattr(doubled, name), getattr(general, name), atol=5e-14)
        P, Q = s.layers[1]['P'][0], s.layers[1]['Q'][0]
        Z = np.zeros_like(P)
        generator = 1j*np.block([[Z, Q], [P, Z]])
        T = expm(generator*middle['thickness'])
        I = np.eye(6)
        Fleft = np.block([[I, I], [s.Yleft[0], -s.Yleft[0]]])
        Fright = np.block([[I, I], [s.Yright[0], -s.Yright[0]]])
        incident = p['excitation_h']
        # Independent dense boundary equations, safe here because this slab is thin.
        M = np.concatenate((T@Fleft[:, 6:], -Fright[:, :6]), axis=1)
        reflected, transmitted = np.linalg.solve(M, -T@Fleft[:, :6]@incident).reshape(2, 6)
        np.testing.assert_allclose(s.reflected[0, :, 0], reflected, atol=5e-14)
        np.testing.assert_allclose(s.transmitted[0, :, 0], transmitted, atol=5e-14)
        for depth in (0, .012, middle['thickness']):
            h, e = (expm(generator*depth)@Fleft@np.r_[incident, reflected]).reshape(2, 6)
            c = s.coefficients(1, depth)[0]
            np.testing.assert_allclose(c[:, 3:5], h.reshape(2, 3).T, atol=8e-14)
            np.testing.assert_allclose(c[:, :2], np.stack((e[3:], -e[:3]), axis=-1), atol=8e-14)
            np.testing.assert_allclose(c[:, 2], middle['epsilon_inv']@(p['ky']*h[:3]-p['kx']*h[3:])/p['omega'], atol=8e-14)
            np.testing.assert_allclose(c[:, 5], (-p['kx']*e[:3]-p['ky']*e[3:])/p['omega'], atol=8e-14)

    def test_thick_absorber_and_batch(self):
        ps = [payload(4+1j, d) for d in (20., 40.)]
        ps[1]['layers'][1]['uniform'] = False  # Exercise PIM for both batch entries.
        s = solve_batch(ps, backend='numpy')
        q = np.sqrt(4+1j)
        expected = abs((q-1)/(q+1))**2
        np.testing.assert_allclose(s.rta()[:, 0], expected, atol=2e-12)
        np.testing.assert_allclose(s.rta()[:, 1], 0, atol=1e-20)
        self.assertTrue(np.isfinite(s.coefficients(1, 10.)).all())

    def test_grazing_incident_wave_cannot_supply_normal_power(self):
        p = payload()
        p['kx'] = [p['omega']]
        with self.assertRaisesRegex(ValueError, 'grazing|Positive incoming'):
            solve_batch([p], backend='numpy').rta()

    def test_exact_cutoff_matches_independent_maxwell_boundary_system(self):
        rng = np.random.default_rng(442)
        for backwards in (False, True):
            for direction in ((1., 0.), (.6, .8)):
                p = payload(3+.15j, .025, n=3)
                p['layers'][-1] = dict(p['layers'][0])
                p.update(backwards=backwards,
                    kx=np.array([0., p['omega'], 1.2*p['omega']])*direction[0],
                    ky=np.array([0., p['omega'], 1.2*p['omega']])*direction[1])
                middle = p['layers'][1]
                middle['uniform'] = False
                middle['epsilon2'] += .04*(rng.normal(size=(6, 6))+1j*rng.normal(size=(6, 6)))
                solution = solve_batch([p], backend='numpy')
                self.assertTrue(solution.regular_ports)
                self.assertEqual(solution.qleft[0, 1], 0)
                H1, E1 = solution.Hleft[0], solution.Eleft[0]
                H2, E2 = solution.Hright[0], solution.Eright[0]
                F1 = np.block([[H1, H1], [E1, -E1]])
                F2 = np.block([[H2, H2], [E2, -E2]])
                P, Q = solution.layers[1]['P'][0], solution.layers[1]['Q'][0]
                generator = 1j*np.block([[np.zeros_like(P), Q], [P, np.zeros_like(P)]])
                transfer = expm(generator*middle['thickness'])
                a1 = solution.incident_left[0, :, 0]
                b2 = solution.incident_right[0, :, 0]
                matrix = np.column_stack((transfer@F1[:, 6:], -F2[:, :6]))
                reflected, transmitted = np.linalg.solve(matrix,
                    F2[:, 6:]@b2-transfer@F1[:, :6]@a1).reshape(2, 6)
                np.testing.assert_allclose(solution.reflected[0, :, 0], reflected, atol=8e-14)
                np.testing.assert_allclose(solution.transmitted[0, :, 0], transmitted, atol=8e-14)
                for z in (0., .009, middle['thickness']):
                    h, e = (expm(generator*z)@F1@np.r_[a1, reflected]).reshape(2, 6)
                    fields = solution.coefficients(1, z)[0]
                    np.testing.assert_allclose(fields[:, 3:5], h.reshape(2, 3).T, atol=1e-13)
                    np.testing.assert_allclose(fields[:, :2], np.column_stack((e[3:], -e[:3])), atol=1e-13)
                for li, z in ((0, -.3), (1, .013), (2, .7)):
                    self.assertTrue(np.isfinite(solution.coefficients(li, z)).all())
                self.assertTrue(np.isfinite(solution.rta()).all())

    def test_roundoff_guard_preserves_real_material_absorption(self):
        p = payload(n=2)
        p['kx'] = [0., p['omega']]
        p['layers'][0]['epsilon'] = 1+1e-16j
        solution = solve_batch([p], backend='numpy')
        self.assertFalse(solution.regular_ports)
        self.assertNotEqual(solution.qleft[0,1],0)

    def test_guarded_symmetry_lifts_all_orders(self):
        p = payload(3+.1j, .2, n=9)
        g = [(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1)]
        p.update(G=g, kx=np.array([x*3. for x, y in g]),
                 ky=np.array([y*3. for x, y in g]), mirror_eligible=True)
        p['excitation_h'][:] = 0
        p['excitation_h'][9+4] = 1
        p['layers'][1]['uniform'] = False
        full = solve_batch([p], backend='numpy')
        reduced = solve_batch([p], backend='numpy', symmetry=True)
        self.assertEqual(reduced.diagnostics['solver_dimension'], 5)
        np.testing.assert_allclose(full.rta(), reduced.rta(), atol=5e-14)
        for li, z in ((0, -.01), (1, .07), (2, .02)):
            np.testing.assert_allclose(full.coefficients(li, z), reduced.coefficients(li, z), atol=1e-13)
        np.testing.assert_allclose(full.port_amplitudes(), reduced.port_amplitudes(), atol=1e-13)
        p['excitation_h'][4] = 1e-100
        self.assertEqual(solve_batch([p], backend='numpy', symmetry=True).m, 10)
        p['excitation_h'][4] = 0
        p['mirror_eligible'] = False
        self.assertEqual(solve_batch([p], backend='numpy', symmetry=True).m, 18)
        p['mirror_eligible'] = True
        p['layers'][1]['epsilon2'][0, 13] = .001
        self.assertEqual(solve_batch([p], backend='numpy', symmetry=True).m, 18)


if __name__ == '__main__':
    unittest.main()
