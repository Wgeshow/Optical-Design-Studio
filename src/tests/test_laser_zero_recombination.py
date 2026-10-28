"""Regression of the existing A-only steady-state limit, not a paper reproduction."""
from dataclasses import replace
import math
import unittest

from laser_model import LaserParameters, solve_laser


class LaserZeroRecombinationTests(unittest.TestCase):
    def test_a_only_limit_matches_analytic_carrier_balance_and_threshold(self):
        # Deliberately simple independent SI balance: g0 is a gain RATE slope.
        # These are regression inputs, not a native UI acceptance structure.
        charge = 1.602176634e-19
        light_speed = 299792458.0
        lifetime_s = 2e-9
        photon_lifetime_s = 1e-12
        gain_rate_m3_s = 2e-12
        transparency_m3 = 1e24
        volume_m3 = 1e-16
        confinement = 0.5
        injection = 0.8
        wavelength_m = 1e-6
        group_velocity_m_s = light_speed / 4.0
        threshold_m3 = transparency_m3 + 1 / (
            confinement * gain_rate_m3_s * photon_lifetime_s)
        threshold_a = charge * volume_m3 * threshold_m3 / (lifetime_s * injection)
        parameters = LaserParameters(
            wavelength_nm=wavelength_m * 1e9, group_index=4.0,
            confinement=confinement,
            quality_factor=2 * math.pi * light_speed / wavelength_m * photon_lifetime_s,
            transparency_density_cm3=transparency_m3 / 1e6,
            differential_gain_cm2=gain_rate_m3_s / group_velocity_m_s * 1e4,
            active_volume_um3=volume_m3 / 1e-18,
            recombination_a_s=1 / lifetime_s,
            recombination_b_cm3_s=0.0, recombination_c_cm6_s=0.0,
            injection_efficiency=injection, spontaneous_emission_factor=0.0,
        )
        result = solve_laser(parameters, [0.0, threshold_a * 500, threshold_a * 1500])
        self.assertAlmostEqual(result['threshold_density_cm-3'] / (threshold_m3 / 1e6), 1.0, places=12)
        self.assertAlmostEqual(result['threshold_current_ma'] / (threshold_a * 1e3), 1.0, places=12)
        zero, below, above = result['sweep']
        self.assertEqual(zero['carrier_density_cm_3'], 0)
        self.assertAlmostEqual(below['carrier_density_cm_3'] / (threshold_m3 / 2e6), 1.0, places=12)
        self.assertEqual(below['output_power_mw'], 0)
        self.assertEqual(below['photon_density_cm_3'], 0)
        self.assertAlmostEqual(above['carrier_density_cm_3'] / (threshold_m3 / 1e6), 1.0, places=12)
        self.assertGreater(above['output_power_mw'], 0)
        self.assertTrue(all(math.isfinite(value) for point in result['sweep'] for value in point.values()))

    def test_zero_b_or_c_is_allowed_independently(self):
        for field in ('recombination_b_cm3_s', 'recombination_c_cm6_s'):
            with self.subTest(field=field):
                parameters = replace(LaserParameters(), **{field: 0.0})
                self.assertIs(parameters.validate(), parameters)

    def test_negative_and_nonfinite_b_or_c_are_rejected(self):
        for field in ('recombination_b_cm3_s', 'recombination_c_cm6_s'):
            for value in (-1e-30, float('nan'), float('inf'), -float('inf')):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    replace(LaserParameters(), **{field: value}).validate()

    def test_required_positive_parameters_remain_positive(self):
        fields = ('wavelength_nm', 'group_index', 'confinement', 'quality_factor',
                  'transparency_density_cm3', 'differential_gain_cm2', 'active_volume_um3',
                  'recombination_a_s', 'injection_efficiency', 'differential_efficiency',
                  'ambient_temperature_k', 'drive_voltage_v')
        for field in fields:
            for value in (0.0, -1.0, float('nan'), float('inf')):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    replace(LaserParameters(), **{field: value}).validate()


if __name__ == '__main__':
    unittest.main()
