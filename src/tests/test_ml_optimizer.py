"""Scientific and workflow checks for the optional Bayesian search."""
import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from model import DEFAULT_PERFORMANCE
from peak_optimizer import parse_search
from ml_optimizer import (ML_DEFAULTS, ML_KEYS, acquisition, dependencies, encode, execute_ml_search,
                          fingerprint, load_history, local_grid, peak_targets, validate_ml)
from test_backend import sample
from test_peak_optimizer import bound, rows_for


def config(base, **overrides):
    options = dict(zip(ML_KEYS, ML_DEFAULTS))
    options.update(search_mode='ML assisted', initial_designs=3, ml_trials=8, candidate_pool=64,
                   refinement_rounds=2, design_budget=100, point_budget=100000)
    options.update(overrides)
    cfg = parse_search(base, [bound('thickness', 'Device', .2, .3, .005)], options)
    return validate_ml(cfg, base)


def fake_executor(calls, high_resolution_loss=False):
    def execute(model, perf, emit, cancelled):
        calls.append(copy.deepcopy(model))
        x = np.array([r[1] for r in model['points']])
        t = model['layers'][1]['thickness']
        amplitude = .4+.5998*math.exp(-((t-.25)/.025)**2)
        if high_resolution_loss and model['basis'] > 17:
            amplitude -= .1
        width = .5+(t-.2)*3
        y = amplitude/(1+((x-1550.017)/width)**2)
        return rows_for(x, y), dict(warnings=[], cpu_gemm_calls=1)
    return execute


class MLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dependencies()

    def setUp(self):
        self.base = sample(wl_start_nm=1535, wl_stop_nm=1565, wl_step_nm=1, NumG=17)

    def run_search(self, cfg, calls=None, lose=False, cancelled=lambda: False):
        calls = calls if calls is not None else []
        with tempfile.TemporaryDirectory() as directory:
            result = execute_ml_search(self.base, dict(DEFAULT_PERFORMANCE, timeout_seconds=120), cfg, directory,
                                       fake_executor(calls, lose), lambda e: None, cancelled)
            history = json.loads((Path(directory)/'optimization_history.json').read_text())
            records = (Path(directory)/'design_results.csv').read_text()
            self.assertTrue(Path(result['archive']).is_file())
            return result['summary'], history, records

    def test_categorical_encoding_has_no_ordinal_distance(self):
        dimensions = [dict(parameter='layer_material', values=['Si', 'GaAs', 'TiO2'])]
        encoded = np.array([encode([v], dimensions) for v in dimensions[0]['values']])
        for i in range(3):
            for j in range(i+1, 3):
                self.assertAlmostEqual(float(np.linalg.norm(encoded[i]-encoded[j])), math.sqrt(2))

    def test_q_constraint_uses_same_peak(self):
        peaks = [dict(absorption=.999, Q_estimate=100, wavelength_nm=1500),
                 dict(absorption=.8, Q_estimate=10000, wavelength_nm=1550)]
        result = peak_targets(peaks, .99)
        self.assertEqual(result['q_absorption'], .999)
        self.assertAlmostEqual(result['log_q'], math.log(100))
        self.assertEqual(result['feasible_q'], 100)
        self.assertIsNone(peak_targets([dict(absorption=.999, Q_estimate=None, wavelength_nm=1550)], .99)['log_q'])

    def test_ml_bypasses_grid_budget_but_enforces_trial_budget(self):
        cfg = config(self.base, design_budget=10)
        self.assertEqual(cfg['design_count'], 21)
        with self.assertRaises(ValueError):
            config(self.base, ml_trials=12, design_budget=10)
        with self.assertRaises(ValueError):
            config(self.base, search_mode='Exhaustive grid', design_budget=10)

    def test_ml_learns_and_records_uncertainty(self):
        summary, history, records = self.run_search(config(self.base, initial_designs=2))
        observations = history['observations']
        self.assertEqual(summary['status'], 'complete', summary)
        self.assertEqual(len(observations), 8)
        self.assertEqual(len({tuple(o['values']) for o in observations}), 8)
        self.assertTrue(all(.2 <= o['values'][0] <= .3 for o in observations))
        self.assertTrue(any('absorption_std' in o['prediction'] for o in observations))
        self.assertIn('predicted_absorption', records)
        initial_best = max(o['targets']['absorption'] for o in observations[:2])
        self.assertGreater(summary['best_absorption'], initial_best)
        # Eight trials are not guaranteed to find a very narrow feasible region.
        self.assertGreater(summary['best_absorption'], .8)

    def test_feasible_run_switches_to_constrained_q_acquisition(self):
        summary, history, _ = self.run_search(config(self.base, initial_designs=3))
        self.assertGreater(summary['best_absorption'], .99)
        selected = [o for o in history['observations'] if o.get('prediction', {}).get('paired_peak_probability') is not None]
        self.assertTrue(selected)
        self.assertTrue(all(0 <= o['prediction']['paired_peak_probability'] <= 1 for o in selected))
        self.assertIsNotNone(summary['highest_Q_estimate'])

    def test_large_history_keeps_constrained_q_search(self):
        from unittest.mock import patch
        cfg = config(self.base)
        observations = [dict(values=[.2 + (i % 21)*.005], targets=dict(absorption=.999,
                         log_q=math.log(100), q_absorption=.999, feasible_q=100)) for i in range(257)]
        prediction = (np.array([.999]), np.array([.01]), [])
        with patch('ml_optimizer.fit_predict', return_value=prediction):
            _, result = acquisition(observations, [[.25]], cfg)
        self.assertIn('Q improvement', result['selection_reason'])
        self.assertIsNotNone(result['paired_peak_probability'])

    def test_resume_reuses_observations_and_rejects_mismatch(self):
        cfg = config(self.base, ml_trials=5)
        _, history, _ = self.run_search(cfg)
        calls = []
        resumed_cfg = config(self.base, ml_trials=7, resume_history=history)
        summary, resumed, _ = self.run_search(resumed_cfg, calls)
        self.assertEqual(summary['resumed_observations'], 5)
        self.assertEqual(len(resumed['observations']), 7)
        self.assertEqual(len({m['layers'][1]['thickness'] for m in calls}), 2)
        altered = copy.deepcopy(self.base)
        altered['basis'] += 1
        with self.assertRaises(ValueError):
            load_history(history, altered, cfg)
        malformed = copy.deepcopy(history)
        malformed['observations'][0]['values'][0] = .8
        with self.assertRaises(ValueError):
            load_history(malformed, self.base, cfg)

    def test_hybrid_grid_and_higher_resolution_replace_coarse_results(self):
        cfg = config(self.base, search_mode='Hybrid verified', ml_trials=8, finalists=2)
        calls = []
        summary, history, records = self.run_search(cfg, calls, lose=True)
        self.assertEqual(summary['status'], 'complete', summary)
        self.assertTrue(summary['local_grid_complete'])
        self.assertTrue(summary['finalist_checks_complete'])
        checks = [o for o in history['observations'] if o['phase'] == 'verification']
        self.assertEqual(len(checks), 2)
        self.assertTrue(all(o['basis'] == 26 for o in checks))
        self.assertTrue(any(len(m['points']) == 61 and m['basis'] == 26 for m in calls))
        self.assertTrue(all(o['verification']['status'] == 'needs further convergence review' for o in checks))
        self.assertIn('verification_status', records)
        # Final rankings must not retain the earlier >99% claim for a checked geometry.
        checked_values = {tuple(o['values']) for o in checks}
        import csv
        rows = list(csv.DictReader(records.splitlines()))
        for row in rows:
            if (float(row['layer:Device:thickness_um']),) in checked_values:
                self.assertLess(float(row['absorption']), .99)
                self.assertEqual(row['phase'], 'verification')

    def test_local_grid_is_full_cartesian_and_bounded(self):
        cfg = config(self.base)
        cfg['dimensions'].append(dict(parameter='radius', values=[.05, .1, .15]))
        cfg['dimensions'].append(dict(parameter='layer_material', values=['Si', 'GaAs']))
        grid = local_grid([dict(values=[.2, .1, 'Si'])], cfg)
        self.assertEqual(len(grid), 6)
        self.assertTrue(all(v[0] >= .2 and v[2] == 'Si' for v in grid))

    def test_insufficient_local_budget_is_explicit_and_finalists_still_checked(self):
        summary, history, _ = self.run_search(config(self.base, search_mode='Hybrid verified', design_budget=8))
        self.assertEqual(summary['status'], 'partial')
        self.assertIn('not truncated', summary['reason'])
        self.assertFalse(summary['local_grid_complete'])
        self.assertTrue(summary['finalist_checks_complete'])
        self.assertFalse(any(o['phase'] == 'local grid' for o in history['observations']))

    def test_cancel_preserves_history_and_can_resume(self):
        calls = []
        summary, history, _ = self.run_search(config(self.base, refinement_rounds=0), calls,
                                             cancelled=lambda: len(calls) >= 1)
        self.assertEqual(summary['status'], 'cancelled')
        self.assertEqual(len(history['observations']), 1)
        summary2, history2, _ = self.run_search(config(self.base, refinement_rounds=0, resume_history=history))
        self.assertEqual(summary2['resumed_observations'], 1)
        self.assertEqual(len(history2['observations']), 8)

    def test_resume_finishes_saved_local_grid(self):
        calls = []
        summary, history, _ = self.run_search(config(self.base, search_mode='Hybrid verified', design_budget=8))
        self.assertFalse(summary['local_grid_complete'])
        saved_plan = history['local_plan']
        self.assertTrue(saved_plan)
        completed, resumed, _ = self.run_search(config(self.base, search_mode='Hybrid verified', design_budget=100, resume_history=history), calls)
        self.assertTrue(completed['local_grid_complete'])
        self.assertEqual(saved_plan, resumed['local_plan'])
        self.assertEqual(completed['resumed_observations'], len(history['observations']))

    def test_point_budget_stops_before_spending_and_exports(self):
        calls = []
        summary, history, _ = self.run_search(config(self.base, point_budget=3), calls)
        self.assertEqual(summary['status'], 'partial')
        self.assertEqual(len(calls), 0)
        self.assertIsNone(summary['best_absorption'])


if __name__ == '__main__':
    unittest.main()
