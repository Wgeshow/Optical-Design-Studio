import unittest
from laser_model import LaserParameters, solve_laser


class LaserModelTests(unittest.TestCase):
    def test_threshold_and_li_curve_are_physical(self):
        result = solve_laser(LaserParameters(), [0, 20, 50, 100])
        self.assertGreater(result['threshold_gain_cm-1'], 0)
        self.assertGreater(result['threshold_current_ma'], 0)
        self.assertEqual(result['output_power_mw'][0], 0)
        self.assertGreaterEqual(result['output_power_mw'][-1], result['output_power_mw'][-2])

    def test_invalid_confinement_is_rejected(self):
        with self.assertRaises(ValueError):
            solve_laser(LaserParameters(confinement=1.2), [0])

    def test_invalid_current_sweep_is_rejected(self):
        for currents in ([], [-1, 2], [float('nan')]):
            with self.subTest(currents=currents), self.assertRaises(ValueError):
                solve_laser(LaserParameters(), currents)

    def test_power_slope_matches_reported_efficiency(self):
        result = solve_laser(LaserParameters(), [100, 110])
        measured_w_per_a = (result['output_power_mw'][1] - result['output_power_mw'][0]) / 10
        self.assertAlmostEqual(measured_w_per_a, result['slope_efficiency_w_per_a'], places=10)


if __name__ == '__main__':
    unittest.main()
