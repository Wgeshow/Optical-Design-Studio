import math
import unittest
from laser_model import LaserParameters, solve_laser


class LaserPerformanceTests(unittest.TestCase):
    def test_optical_relations_and_loss_breakdown(self):
        p = LaserParameters(quality_factor=10000, wavelength_nm=1000, internal_loss_cm=2)
        optical = solve_laser(p, [0])["optical"]
        self.assertAlmostEqual(optical["linewidth_nm"], .1)
        tau = p.quality_factor*p.wavelength_nm*1e-9/(2*math.pi*299792458)
        self.assertAlmostEqual(optical["photon_lifetime_ps"], tau*1e12)
        self.assertAlmostEqual(optical["total_loss_cm_1"], optical["q_loss_cm_1"]+2)

    def test_loss_and_low_confinement_raise_threshold(self):
        base = solve_laser(LaserParameters(), [0])
        overlap = solve_laser(LaserParameters(confinement=.1), [0])
        lossy = solve_laser(LaserParameters(internal_loss_cm=20), [0])
        self.assertGreater(overlap["threshold_density_cm-3"], base["threshold_density_cm-3"])
        self.assertGreater(lossy["threshold_current_ma"], base["threshold_current_ma"])

    def test_structured_sweep_and_carrier_clamping(self):
        result = solve_laser(LaserParameters(), [0, 100, 150])
        self.assertEqual(result["schema"], "optical-design-studio/laser-performance/v1")
        self.assertEqual(result["sweep"][0]["carrier_density_cm_3"], 0)
        self.assertAlmostEqual(result["sweep"][-1]["carrier_density_cm_3"],
                               result["sweep"][-2]["carrier_density_cm_3"])
        self.assertGreater(result["sweep"][-1]["photon_density_cm_3"], 0)

    def test_thermal_feedback_heats_red_shifts_and_reduces_power(self):
        cold = solve_laser(LaserParameters(), [100])
        hot = solve_laser(LaserParameters(thermal_resistance_k_w=100), [100])
        point = hot["sweep"][0]
        self.assertTrue(hot["thermal"]["enabled"])
        self.assertGreater(point["temperature_k"], 300)
        self.assertGreater(point["wavelength_nm"], 940)
        self.assertLess(hot["output_power_mw"][0], cold["output_power_mw"][0])

    def test_small_signal_response(self):
        modulation = solve_laser(LaserParameters(), [150], [0, 1, 5, 10, 50])["modulation"]
        self.assertEqual(modulation["magnitude_linear"][0], 1)
        self.assertLess(modulation["magnitude_linear"][-1], 1)
        self.assertIsNotNone(modulation["bandwidth_3db_ghz"])

    def test_invalid_extended_inputs(self):
        for p in (LaserParameters(internal_loss_cm=-1),
                  LaserParameters(spontaneous_emission_factor=1.1),
                  LaserParameters(thermal_resistance_k_w=-1)):
            with self.subTest(parameters=p), self.assertRaises(ValueError):
                solve_laser(p, [0])
        with self.assertRaises(ValueError):
            solve_laser(LaserParameters(), [10], [-1])


if __name__ == "__main__":
    unittest.main()
