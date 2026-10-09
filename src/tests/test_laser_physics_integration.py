"""Physics invariants and cross-layer integration tests for Laser & PCSEL.

These tests intentionally avoid duplicating the implementation equations.  They
exercise qualitative relationships that any compatible solver should preserve.
"""
import math
import unittest

from laser_model import LaserParameters, solve_laser
from pcsel_design import PCSELDesign


class LaserPhysicsInvariantTests(unittest.TestCase):
    def test_li_curve_is_zero_below_threshold_and_linear_above_it(self):
        baseline = solve_laser(LaserParameters(), [0])
        threshold = baseline["threshold_current_ma"]
        currents = [0, threshold * 0.5, threshold, threshold + 10, threshold + 20]
        result = solve_laser(LaserParameters(), currents)

        self.assertEqual(result["output_power_mw"][:3], [0.0, 0.0, 0.0])
        first_increment = result["output_power_mw"][3] - result["output_power_mw"][2]
        second_increment = result["output_power_mw"][4] - result["output_power_mw"][3]
        self.assertGreater(first_increment, 0)
        self.assertAlmostEqual(first_increment, second_increment, places=10)

    def test_higher_q_lowers_threshold_gain_and_increases_photon_lifetime(self):
        low_q = solve_laser(LaserParameters(quality_factor=2.0e4), [0])
        high_q = solve_laser(LaserParameters(quality_factor=4.0e4), [0])

        self.assertAlmostEqual(
            high_q["photon_lifetime_ps"] / low_q["photon_lifetime_ps"], 2.0
        )
        self.assertAlmostEqual(
            low_q["threshold_gain_cm-1"] / high_q["threshold_gain_cm-1"], 2.0
        )
        self.assertLess(high_q["threshold_current_ma"], low_q["threshold_current_ma"])

    def test_better_confinement_reduces_required_gain_and_threshold_current(self):
        weak = solve_laser(LaserParameters(confinement=0.10), [0])
        strong = solve_laser(LaserParameters(confinement=0.40), [0])

        self.assertGreater(weak["threshold_gain_cm-1"], strong["threshold_gain_cm-1"])
        self.assertGreater(weak["threshold_density_cm-3"], strong["threshold_density_cm-3"])
        self.assertGreater(weak["threshold_current_ma"], strong["threshold_current_ma"])

    def test_active_volume_scales_threshold_current_but_not_gain(self):
        small = solve_laser(LaserParameters(active_volume_um3=50), [0])
        large = solve_laser(LaserParameters(active_volume_um3=150), [0])

        self.assertEqual(small["threshold_gain_cm-1"], large["threshold_gain_cm-1"])
        self.assertEqual(small["threshold_density_cm-3"], large["threshold_density_cm-3"])
        self.assertAlmostEqual(
            large["threshold_current_ma"] / small["threshold_current_ma"], 3.0
        )

    def test_default_outputs_are_finite_nonnegative_and_aligned(self):
        result = solve_laser(LaserParameters(), range(0, 201, 5))
        self.assertEqual(len(result["currents_ma"]), len(result["output_power_mw"]))
        for key in ("threshold_gain_cm-1", "threshold_density_cm-3",
                    "threshold_current_ma", "photon_lifetime_ps",
                    "slope_efficiency_w_per_a"):
            self.assertTrue(math.isfinite(result[key]), key)
            self.assertGreater(result[key], 0, key)
        self.assertTrue(all(math.isfinite(p) and p >= 0
                            for p in result["output_power_mw"]))

    def test_modulation_is_calculated_at_the_requested_bias_point(self):
        frequencies = [0, 5, 10, 20]
        low = solve_laser(LaserParameters(), [40], frequencies)["modulation"]
        high = solve_laser(LaserParameters(), [100], frequencies)["modulation"]

        self.assertEqual(low["bias_current_ma"], 40)
        self.assertEqual(high["bias_current_ma"], 100)
        self.assertGreater(high["relaxation_frequency_ghz"],
                           low["relaxation_frequency_ghz"])
        self.assertEqual(low["frequencies_ghz"], frequencies)

    def test_thermal_controls_change_temperature_and_wavelength(self):
        cold = solve_laser(
            LaserParameters(thermal_resistance_k_w=0), [100]
        )["sweep"][0]
        hot = solve_laser(
            LaserParameters(thermal_resistance_k_w=30,
                            drive_voltage_v=2,
                            wavelength_shift_nm_k=0.1), [100]
        )["sweep"][0]

        self.assertEqual(cold["temperature_k"], 300)
        self.assertGreater(hot["temperature_k"], cold["temperature_k"])
        self.assertAlmostEqual(
            hot["wavelength_nm"] - 940,
            0.1 * (hot["temperature_k"] - 300), places=8,
        )


class PCSELGeometryInvariantTests(unittest.TestCase):
    def test_separate_pc_layer_controls_etch_limit(self):
        PCSELDesign(etch_depth_um=.43, gain_thickness_um=.007,
                    patterned_layer_thickness_um=.43).validate()
        with self.assertRaises(ValueError):
            PCSELDesign(etch_depth_um=.44, gain_thickness_um=.007,
                        patterned_layer_thickness_um=.43).validate()

    def test_fill_factor_matches_area_fraction_and_stays_below_close_packing(self):
        design = PCSELDesign(period_um=0.8, hole_radius_um=0.2).validate()
        self.assertAlmostEqual(design.fill_factor, math.pi * 0.25**2)
        self.assertGreater(design.fill_factor, 0)
        self.assertLess(design.fill_factor, math.pi / 4)

    def test_geometry_rejects_nonphysical_boundaries(self):
        cases = (
            PCSELDesign(period_um=0.8, hole_radius_um=0.4),
            PCSELDesign(etch_depth_um=0.3, gain_thickness_um=0.25),
            PCSELDesign(wavelength_nm=float("inf")),
        )
        for design in cases:
            with self.subTest(design=design), self.assertRaises(ValueError):
                design.validate()


if __name__ == "__main__":
    unittest.main()
