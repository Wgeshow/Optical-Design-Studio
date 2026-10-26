"""Native field and cache regression checks; run with built S4 on PYTHONPATH.

On Windows set S4_TEST_DLL_DIR to the directory containing MKL runtime DLLs.
"""
import os
import unittest
import numpy as np

_dll_handle = os.add_dll_directory(os.environ["S4_TEST_DLL_DIR"]) if os.name == "nt" and os.getenv("S4_TEST_DLL_DIR") else None
import S4


def simulation(basis=32, skew=True, loss=True, tensor=False, pattern=True):
    sim = S4.New(Lattice=((1.0, 0.0), (0.17, 0.93)) if skew else ((1., 0.), (0., 1.)), NumBasis=basis)
    sim.SetMaterial(Name="air", Epsilon=1.)
    eps = 7.2 + (0.11j if loss else 0j)
    if tensor:
        eps = ((eps, .03j, 0), (-.02j, eps+.2, 0), (0, 0, eps-.1))
    sim.SetMaterial(Name="film", Epsilon=eps)
    sim.SetMaterial(Name="substrate", Epsilon=2.25)
    sim.AddLayer(Name="top", Thickness=0., S4_Material="air")
    sim.AddLayer(Name="film", Thickness=.22, S4_Material="film")
    if pattern:
        sim.SetRegionCircle(S4_Layer="film", S4_Material="air", Center=(.07, -.04), Radius=.19)
    sim.AddLayerCopy(Name="copy", Thickness=.13, S4_Layer="film")
    sim.AddLayer(Name="bottom", Thickness=0., S4_Material="substrate")
    sim.SetExcitationPlanewave(IncidenceAngles=(17., 23.), sAmplitude=.4+.1j, pAmplitude=1.)
    sim.SetFrequency(.91)
    return sim


def coefficients(sim, depths):
    return np.frombuffer(sim.GetFieldCoefficientsMany(depths), dtype=np.complex128).reshape(len(depths), -1, 6)


def reconstructed(sim, depths, xy, frequency=.91, angles=(17., 23.)):
    coeff = coefficients(sim, depths)
    g = np.asarray(sim.GetBasisSet())
    reciprocal = np.asarray(sim.GetReciprocalLattice())
    polar, azimuth = np.deg2rad(angles)
    kxy = g @ reciprocal + frequency*np.sin(polar)*np.array([np.cos(azimuth), np.sin(azimuth)])
    phase = np.exp(2j*np.pi*(np.asarray(xy) @ kxy.T))
    return np.einsum("pg,zgc->zpc", phase, coeff)


class FieldCoefficientsTests(unittest.TestCase):
    def test_scalar_equivalence(self):
        depths = [-.12, 0., .001, .12, .219, .22, .221, .31, .35, .351, .49]
        xy = [(-.41, .29), (0., 0.), (.13, -.21), (.99, .37)]
        for basis in (32, 64, 128):
            for kwargs in ({}, {"tensor": True}, {"pattern": False}, {"skew": False, "loss": False}):
                with self.subTest(basis=basis, **kwargs):
                    sim = simulation(basis, **kwargs)
                    actual = reconstructed(sim, depths, xy)
                    reference = np.array([[np.concatenate(sim.GetFields(x, y, z)) for x, y in xy] for z in depths])
                    np.testing.assert_allclose(actual, reference, rtol=2e-11, atol=2e-12)

    def test_unsorted_repeated_and_invalid_depths(self):
        sim = simulation()
        depths = [.4, -.1, .15, .15, 0., .31]
        actual = coefficients(sim, depths)
        for index, depth in enumerate(depths):
            np.testing.assert_array_equal(actual[index], coefficients(sim, [depth])[0])
        self.assertEqual(sim.GetFieldCoefficientsMany([]), b"")
        for invalid in ([np.nan], [np.inf], ["bad"], 2):
            with self.assertRaises((TypeError, ValueError)):
                sim.GetFieldCoefficientsMany(invalid)

    def test_cache_frequency_and_invalidation(self):
        sim = simulation()
        depths = [.11, .27, .41]
        coefficients(sim, depths)
        first = sim.GetEpsilonCacheStats()
        self.assertGreater(first["bytes"], 0)
        sim.SetFrequency(.92)
        actual = coefficients(sim, depths)
        self.assertGreater(sim.GetEpsilonCacheStats()["hits"], first["hits"])
        np.testing.assert_array_equal(actual, coefficients(sim.Clone(), depths))
        mutations = [
            lambda s: s.SetMaterial(Name="film", Epsilon=6.8+.23j),
            lambda s: s.SetRegionCircle(S4_Layer="film", S4_Material="air", Center=(-.3, .28), Radius=.04),
            lambda s: s.SetOptions(PolarizationDecomposition=True, PolarizationBasis="Normal"),
            lambda s: s.SetOptions(DiscretizedEpsilon=True, DiscretizationResolution=8),
            lambda s: s.SetOptions(ConserveMemory=True),
            lambda s: s.SetLayerThickness(S4_Layer="film", Thickness=.26),
            lambda s: s.SetExcitationPlanewave(IncidenceAngles=(31., 51.), sAmplitude=.2j, pAmplitude=.7),
        ]
        for mutation in mutations:
            mutation(sim)
            actual = coefficients(sim, depths)
            np.testing.assert_allclose(actual, coefficients(sim.Clone(), depths), rtol=2e-12, atol=2e-12)
        self.assertEqual(sim.GetEpsilonCacheStats()["bytes"], 0)

    def test_partial_option_error_invalidates(self):
        sim = simulation()
        coefficients(sim, [.1])
        with self.assertRaises(ValueError):
            sim.SetOptions(DiscretizedEpsilon=True, DiscretizationResolution=1)
        np.testing.assert_allclose(coefficients(sim, [.1]), coefficients(sim.Clone(), [.1]), rtol=2e-12, atol=2e-12)

    def test_dispersive_material_updates(self):
        sim = simulation()
        for index, frequency in enumerate(np.linspace(.84, 1.04, 7)):
            sim.SetFrequency(float(frequency))
            sim.SetMaterial(Name="film", Epsilon=6.8+.3*index + (0.02+.01*index)*1j)
            np.testing.assert_allclose(coefficients(sim, [.13, .27]), coefficients(sim.Clone(), [.13, .27]), rtol=2e-12, atol=2e-12)


if __name__ == "__main__":
    unittest.main()
