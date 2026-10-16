"""Dense schedules retain published anchors, endpoints and reference identity."""
import unittest
from unittest.mock import patch

from electrical_sweep import generate_biases, resolve_biases, describe_sweep


class ElectricalSweepTests(unittest.TestCase):
    def test_alumina_published_domain_dense_grid(self):
        values = generate_biases(-3, 3, step=.005)
        self.assertEqual(len(values), 1201)
        self.assertEqual(values[0], 0.)
        self.assertIn(-3., values)
        self.assertIn(3., values)
        self.assertIn(-2.995, values)
        self.assertIn(.005, values)
        self.assertIn(2.995, values)

    def test_yu_500_volt_anchor_and_count(self):
        values = generate_biases(0, 500, count=2001)
        self.assertEqual(len(values), 2001)
        self.assertEqual(values[:3], [0., .25, .5])
        self.assertEqual(values[-1], 500.)

    def test_reference_insertion_does_not_replace_endpoint(self):
        values = generate_biases(1, 2, count=1001)
        self.assertEqual(len(values), 1002)
        self.assertEqual(values[:2], [0., 1.])
        self.assertEqual(values[-1], 2.)

    def test_nonddividing_step_keeps_short_last_interval(self):
        self.assertEqual(generate_biases(0, 1, step=.3), [0., .3, .6, .9, 1.])
        self.assertEqual(generate_biases(1, 0, step=.3), [0., 1., .7, .4, .1])

    def test_legacy_bounds_and_caps_are_explicit(self):
        self.assertEqual(resolve_biases(['0', '0', '-1'], max_states=2), [0., -1.])
        self.assertEqual(len(generate_biases(-4, 0, step=.2, max_states=21)), 21)
        with self.assertRaisesRegex(ValueError, 'between'):
            generate_biases(-5, 0, count=10, low=-4, high=0, max_states=21)
        with self.assertRaisesRegex(ValueError, '21 states'):
            generate_biases(-4, 0, count=22, low=-4, high=0, max_states=21)

    def test_nonfinite_and_invalid_counts_rejected(self):
        for values in ([float('inf')], [float('nan')], [True], ['wrong']):
            with self.assertRaises(ValueError):
                resolve_biases(values)
        for count in (0, -1, 2.5, True):
            with self.assertRaises(ValueError):
                generate_biases(0, 1, count=count)

    def test_preallocation_ram_failure_is_not_silent_coarsening(self):
        with patch('electrical_sweep.available_memory_bytes', return_value=1024):
            with self.assertRaisesRegex(ValueError, 'No points were removed'):
                generate_biases(0, 500, count=2001)

    def test_live_description_does_not_allocate_a_voltage_array(self):
        with patch('electrical_sweep.resolve_biases', side_effect=AssertionError('Must not allocate')):
            result = describe_sweep(-3, 3, step=.005)
        self.assertEqual(result['requested_count'], 1201)
        self.assertEqual(result['resolved_count'], 1201)
        self.assertFalse(result['zero_reference_added'])
        self.assertEqual(describe_sweep(0, 1, step=.3)['final_interval_V'], .1)
        self.assertEqual(describe_sweep(1, 2, count=1001)['resolved_count'], 1002)

    def test_indistinguishable_float_points_rejected(self):
        with self.assertRaisesRegex(ValueError, 'cannot be distinguished'):
            generate_biases(1e16, 1e16 + 2, count=100)


if __name__ == '__main__':
    unittest.main()
