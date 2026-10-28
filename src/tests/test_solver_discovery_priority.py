"""Reuse verified runtime locations before slow distribution-wide discovery."""
import unittest
from unittest.mock import patch

import solver_environment as setup


class DiscoveryPriorityTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(mode='wsl', distro='Existing Research', executable='mpb')
        self.hint = dict(mode='wsl', distro='Ubuntu', executable='mpb')

    def test_verified_receipt_precedes_default_hint_and_distribution_scan(self):
        with patch.object(setup, 'saved_runtime', return_value=self.saved), \
                patch.object(setup, 'probe', return_value=self.saved) as probe, \
                patch.object(setup, '_run') as scan:
            self.assertEqual(setup.discover('mpb', self.hint), self.saved)
        probe.assert_called_once_with('mpb', self.saved, cancel=None)
        scan.assert_not_called()

    def test_stale_receipt_falls_back_to_configured_runtime_before_scanning(self):
        with patch.object(setup, 'saved_runtime', return_value=self.saved), \
                patch.object(setup, 'probe', side_effect=[RuntimeError('Removed'), self.hint]) as probe, \
                patch.object(setup, '_run') as scan:
            self.assertEqual(setup.discover('mpb', self.hint), self.hint)
        self.assertEqual([call.args[1] for call in probe.call_args_list], [self.saved, self.hint])
        scan.assert_not_called()

    def test_working_configured_runtime_needs_no_receipt_or_distribution_scan(self):
        with patch.object(setup, 'saved_runtime', return_value={}), \
                patch.object(setup, 'probe', return_value=self.hint) as probe, \
                patch.object(setup, '_run') as scan:
            self.assertEqual(setup.discover('mpb', self.hint), self.hint)
        probe.assert_called_once_with('mpb', self.hint, cancel=None)
        scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
