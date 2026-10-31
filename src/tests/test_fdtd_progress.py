"""Timing mathematics and conservative cached receipts; no solver execution."""
import json
from pathlib import Path
import tempfile
import unittest
from fdtd_progress import PhaseEstimate, cached_estimate, timing_key


class TimingTests(unittest.TestCase):
    def sample(self, estimate, t, wall, phase='Reference', now=None):
        estimate.update(dict(phase=phase, time=t, phase_budget_time=100.,
                             phase_elapsed_seconds=wall), wall if now is None else now)

    def test_rate_excludes_initialization_and_estimates_limit(self):
        estimate = PhaseEstimate()
        self.sample(estimate, 10, 101)
        self.sample(estimate, 20, 102)
        self.assertIsNone(estimate.remaining)
        self.sample(estimate, 30, 103)
        self.assertEqual(estimate.rate, 10)
        self.assertEqual(estimate.remaining, 7)
        self.assertEqual(estimate.budget_seconds(), 110)
        self.assertIn('decay may finish sooner', estimate.text(103))

    def test_phase_reset_and_stale_or_invalid_data(self):
        estimate = PhaseEstimate()
        for t, wall in [(10, 1), (20, 2), (30, 3)]:
            self.sample(estimate, t, wall)
        self.assertIn('Waiting for solver', estimate.text(14))
        self.sample(estimate, 1, 1, 'Device')
        self.assertIsNone(estimate.remaining)
        self.assertEqual(estimate.phase, 'Device')
        estimate.update(dict(phase='Device', time=float('nan'), phase_budget_time=100,
                             phase_elapsed_seconds=2), 2)
        self.assertIsNone(estimate.fraction)
        self.assertIsNone(estimate.remaining)

    def test_time_rollback_does_not_reuse_rate(self):
        estimate = PhaseEstimate()
        for t, wall in [(10, 1), (20, 2), (30, 3), (2, 4)]:
            self.sample(estimate, t, wall)
        self.assertIsNone(estimate.remaining)

    def test_exact_physical_input_options_and_runtime_match(self):
        original = timing_key(dict(materials=[{'A': 1}], layers=[], patterns=[], settings={}), {'resolution': 40}, {'python': 'a'})
        self.assertNotEqual(original, timing_key(dict(materials=[{'A': 2}], layers=[], patterns=[], settings={}), {'resolution': 40}, {'python': 'a'}))
        self.assertNotEqual(original, timing_key(dict(materials=[{'A': 1}], layers=[], patterns=[], settings={}), {'resolution': 80}, {'python': 'a'}))
        self.assertNotEqual(original, timing_key(dict(materials=[{'A': 1}], layers=[], patterns=[], settings={}), {'resolution': 40}, {'python': 'b'}))

    def test_cached_receipts_require_valid_exact_match(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)/'fdtd_test'; run.mkdir()
            receipt = run/'runtime_timing.json'
            for payload in [{'schema': 1, 'input_key': 'other', 'estimated_budget_seconds': 50},
                            {'schema': 1, 'input_key': 'wanted', 'estimated_budget_seconds': float('nan')},
                            {'schema': 99, 'input_key': 'wanted', 'estimated_budget_seconds': 50}]:
                receipt.write_text(json.dumps(payload))
                self.assertIsNone(cached_estimate(folder, 'wanted'))
            receipt.write_text(json.dumps(dict(schema=1, input_key='wanted', estimated_budget_seconds=50)))
            self.assertEqual(cached_estimate(folder, 'wanted')['seconds'], 50)
