import csv
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from peak_optimizer import (BOUND_COLS, parse_search, designs, geometry_error, grid_values,
                            spectrum_peaks, execute_search)
from test_backend import sample
from model import DEFAULT_PERFORMANCE


def bound(p, target='', lo=0, hi=0, step=1, choices=''):
    return dict(zip(BOUND_COLS, [p, target, lo, hi, step, choices]))


def rows_for(x, y):
    return [[i, float(w), 0., float(1-a), 0., float(a)] for i, (w, a) in enumerate(zip(x, y))]


class PeakSearchTests(unittest.TestCase):
    def test_bounds_endpoints_and_conflicts(self):
        self.assertEqual(grid_values(0, 1, .4), [0., .4, .8, 1.])
        self.assertEqual(grid_values(.2, .2, 0), [.2])
        for bounds in ([bound('lattice_square', lo=.7, hi=.8, step=.1), bound('lattice_x', lo=.7, hi=.8, step=.1)],
                       [bound('radius', '1', .1, .2, .1), bound('r_over_a', '1', .1, .2, .1)],
                       [bound('thickness', 'Top', 0, .1, .1)],
                       [bound('layer_material', 'Device', choices='Missing')]):
            with self.assertRaises(ValueError):
                parse_search(sample(), bounds, {})
        with self.assertRaises(ValueError):
            parse_search(sample(), [bound('radius', '1', .01, .2, .001)], dict(design_budget=2))
        for options in (dict(absorption_target=.98), dict(absorption_target=1), dict(ratio_limit=.7)):
            with self.assertRaises(ValueError):
                parse_search(sample(), [], options)

    def test_ratio_lattice_material_product(self):
        base = sample()
        cfg = parse_search(base, [bound('r_over_a', '1', .1, .2, .1), bound('lattice_square', lo=.7, hi=.8, step=.1),
                                  bound('layer_material', 'Device', choices='Film;Glass')], {})
        models = list(designs(base, cfg))
        self.assertEqual(len(models), 8)
        self.assertAlmostEqual(models[-1]['patterns'][0]['sx'], .16)
        self.assertEqual(models[-1]['layers'][1]['material'], 'Glass')
        self.assertEqual(base['patterns'][0]['sx'], .1)

    def test_geometry_strict_ratio_and_periodic_bridges(self):
        m = sample(ax_um=1, ay_um=1)
        cfg = parse_search(m, [], dict(separate_circles=False))
        m['patterns'][0]['sx'] = .6
        self.assertIn('r/a', geometry_error(m, cfg))
        m['patterns'][0]['sx'] = .55
        self.assertEqual(geometry_error(m, cfg), '')
        cfg['separate_circles'] = True
        self.assertIn('separation', geometry_error(m, cfg))
        m['patterns'][0].update(sx=.1, cx=.45)
        m['patterns'].append(dict(m['patterns'][0], cx=-.45))
        self.assertIn('overlap', geometry_error(m, cfg))

    def test_weak_peak_and_lorentzian_q(self):
        x = np.linspace(1500, 1600, 10001)
        y = .02+.05/(1+((x-1550)/.5)**2)
        peaks, _ = spectrum_peaks(rows_for(x, y), .00001)
        self.assertAlmostEqual(peaks[0]['wavelength_nm'], 1550)
        self.assertAlmostEqual(peaks[0]['absorption'], .07)
        self.assertAlmostEqual(peaks[0]['Q_estimate'], 1550, delta=1)

    def test_edges_flat_and_unresolved_not_infinite_q(self):
        for y in ([0, .5, 1], [.9, .9, .9], [.1, .999, .1]):
            peaks, _ = spectrum_peaks(rows_for([1500, 1550, 1600], y), 0)
            self.assertIsNone(peaks[0]['Q_estimate'])
            self.assertAlmostEqual(peaks[0]['absorption'], max(y))

    def test_all_peaks_and_q_ranking(self):
        base = sample(wl_start_nm=1500, wl_stop_nm=1600, wl_step_nm=.5)
        cfg = parse_search(base, [bound('thickness', 'Device', .2, .3, .1)], dict(refinement_rounds=3))
        def executor(m, perf, emit, cancelled):
            x = np.array([r[1] for r in m['points']])
            # The narrower resonance has lower height but must lead Q ranking.
            y = np.maximum(.9995/(1+((x-1530.123)/.8)**2), .997/(1+((x-1570.037)/.15)**2))
            return rows_for(x, y), dict(test=True)
        with tempfile.TemporaryDirectory() as directory:
            event = execute_search(base, dict(DEFAULT_PERFORMANCE), cfg, directory, executor, lambda e: None, lambda: False)
            summary = event['summary']
            self.assertEqual(summary['status'], 'complete')
            self.assertEqual(summary['evaluated'], 2)
            self.assertEqual(summary['matching_designs'], 2)
            self.assertGreater(summary['best_absorption'], .9994)
            with (Path(directory)/'above_target_by_Q.csv').open() as f:
                results = list(csv.DictReader(f))
            self.assertEqual(len(results), 4)
            self.assertAlmostEqual(float(results[0]['wavelength_nm']), 1570.037, delta=.01)
            self.assertIn('layer:Device:material', results[0])
            self.assertTrue(Path(event['archive']).is_file())
            self.assertEqual(len((Path(directory)/'design_models.jsonl').read_text().splitlines()), 2)

    def test_budget_cancel_and_nonphysical_results(self):
        base = sample()
        def executor(m, perf, emit, cancelled):
            return [[i, wl, theta, .5, .4, .1] for i, wl, theta in m['points']], {}
        with tempfile.TemporaryDirectory() as directory:
            cfg = parse_search(base, [], dict(point_budget=3))
            event = execute_search(base, dict(DEFAULT_PERFORMANCE), cfg, directory, executor, lambda e: None, lambda: False)
            self.assertEqual(event['summary']['status'], 'partial')
            self.assertIsNone(event['summary']['best_absorption'])
        with tempfile.TemporaryDirectory() as directory:
            event = execute_search(base, dict(DEFAULT_PERFORMANCE), cfg, directory, executor, lambda e: None, lambda: True)
            self.assertEqual(event['summary']['status'], 'cancelled')
        def invalid(m, perf, emit, cancelled):
            return [[i, wl, theta, -.1, 0, 1.1] for i, wl, theta in m['points']], {}
        with tempfile.TemporaryDirectory() as directory:
            cfg = parse_search(base, [], dict(refinement_rounds=0))
            event = execute_search(base, dict(DEFAULT_PERFORMANCE), cfg, directory, invalid, lambda e: None, lambda: False)
            self.assertEqual(event['summary']['failed'], 1)
            self.assertEqual(event['summary']['status'], 'partial')
            self.assertIsNone(event['summary']['best_absorption'])


if __name__ == '__main__':
    unittest.main()
