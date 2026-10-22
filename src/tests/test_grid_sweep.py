"""Behavioral contract for exact, lossless user-selected parameter sweeps."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import numpy as np
from backend import Cancelled
from model import DEFAULT_PERFORMANCE
from peak_optimizer import parse_search, execute_search, analyze_grid_results
from test_backend import sample
from test_peak_optimizer import bound, rows_for


class ExactGridTests(unittest.TestCase):
    def test_exact_product_no_hidden_refinement_constraints_or_other_changes(self):
        base = sample(wl_start_nm=1500, wl_stop_nm=1503, wl_step_nm=1)
        original = copy.deepcopy(base)
        cfg = parse_search(base, [bound('radius', '1', .4, .6, .2), bound('thickness', 'Device', .2, .3, .1)],
                           dict(refinement_rounds=6, absorption_target=1., ratio_limit=.01, min_bridge_um=10.))
        calls = []
        def executor(model, *args):
            calls.append(copy.deepcopy(model))
            return rows_for([p[1] for p in model['points']], [.1, .5, .2, .1]), {}
        with tempfile.TemporaryDirectory() as d:
            result = execute_search(base, DEFAULT_PERFORMANCE, cfg, d, executor, lambda e: None, lambda: False)
            self.assertEqual(result['summary']['evaluated'], 4)
            self.assertEqual(result['summary']['spectral_points'], 16)
            self.assertEqual(len(calls), 4)
            for model in calls:
                self.assertEqual(model['points'], original['points'])
                self.assertEqual(model['ax'], original['ax'])
                self.assertEqual(model['materials'], original['materials'])
                self.assertEqual(model['basis'], original['basis'])
            with (Path(d)/'all_spectra.csv').open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 16)
            self.assertEqual(len((Path(d)/'design_models.jsonl').read_text().splitlines()), 4)
            self.assertFalse((Path(d)/'best_spectrum.csv').exists())
        self.assertEqual(base, original)

    def test_response_filters_read_all_channels_and_preserve_data(self):
        base = sample(wl_start_nm=1500, wl_stop_nm=1502, wl_step_nm=1)
        cfg = parse_search(base, [bound('thickness', 'Device', .2, .3, .1)], {})
        def executor(model, *args):
            r = model['layers'][1]['thickness']
            return [[i,w,t,r,.8-r,.2] for i,w,t in model['points']], {}
        with tempfile.TemporaryDirectory() as d:
            execute_search(base, DEFAULT_PERFORMANCE, cfg, d, executor, lambda e: None, lambda: False)
            before = (Path(d)/'all_spectra.csv').read_bytes()
            for name in ('Reflection', 'Transmission', 'Absorption'):
                for direction in ('High', 'Low'):
                    self.assertEqual(len(analyze_grid_results(d, name, direction)), 2)
            self.assertEqual(analyze_grid_results(d, 'Reflection', 'Low', .25)[0]['design_id'], '1')
            self.assertEqual(analyze_grid_results(d, 'Reflection', 'High', .25)[0]['design_id'], '2')
            self.assertEqual((Path(d)/'all_spectra.csv').read_bytes(), before)

    def test_resolved_peak_and_dip_q_and_no_invented_q_for_sparse_scan(self):
        for step, expected in ((.05, 2), (25, 0)):
            base = sample(wl_start_nm=1500, wl_stop_nm=1600, wl_step_nm=step)
            cfg = parse_search(base, [], {})
            def executor(model, *args):
                x = np.array([r[1] for r in model['points']])
                y = .1+.8/(1+((x-1550)/.5)**2)
                return [[i,float(w),0.,float(r),float(1-r),0.] for i,(w,r) in enumerate(zip(x,y))], {}
            with tempfile.TemporaryDirectory() as d:
                execute_search(base, DEFAULT_PERFORMANCE, cfg, d, executor, lambda e: None, lambda: False)
                matches = [*analyze_grid_results(d, 'Reflection', metric='Q factor'),
                           *analyze_grid_results(d, 'Transmission', metric='Q factor')]
                self.assertEqual(len(matches), expected)
                for match in matches:
                    self.assertAlmostEqual(match['Q_estimate'], 1550, delta=2)

    def test_failed_and_invalid_designs_do_not_stop_or_discard_grid(self):
        cfg = parse_search(sample(), [bound('thickness', 'Device', .1, .5, .1)], {})
        calls = []
        def executor(model, *args):
            calls.append(model)
            if len(calls) <= 3:
                raise ValueError('bad geometry')
            r = -.1 if len(calls) == 4 else .5
            return [[i,w,t,r,1-r,0.] for i,w,t in model['points']], {}
        with tempfile.TemporaryDirectory() as d:
            result = execute_search(sample(), DEFAULT_PERFORMANCE, cfg, d, executor, lambda e: None, lambda: False)
            self.assertEqual(len(calls), 5)
            self.assertEqual(result['summary']['failed'], 3)
            self.assertEqual(result['summary']['invalid'], 1)
            self.assertEqual(result['summary']['evaluated'], 1)
            self.assertIn('-0.1', (Path(d)/'design_4_spectrum.csv').read_text())
            self.assertEqual(len(analyze_grid_results(d)), 1)
            with zipfile.ZipFile(result['archive']) as archive:
                self.assertIn('design_4_spectrum.csv', archive.namelist())

    def test_budget_and_cancellation_account_for_remaining_models(self):
        cfg = parse_search(sample(), [bound('thickness', 'Device', .1, .3, .1)], dict(point_budget=7))
        def executor(model, *args):
            return [[i,w,t,.4,.6,0.] for i,w,t in model['points']], {}
        with tempfile.TemporaryDirectory() as d:
            result = execute_search(sample(), DEFAULT_PERFORMANCE, cfg, d, executor, lambda e: None, lambda: False)
            self.assertEqual(result['summary']['evaluated'], 1)
            self.assertEqual(result['summary']['not_run'], 2)
            self.assertEqual(len((Path(d)/'design_models.jsonl').read_text().splitlines()), 3)
        with tempfile.TemporaryDirectory() as d:
            result = execute_search(sample(), DEFAULT_PERFORMANCE, cfg, d, executor, lambda e: None, lambda: True)
            self.assertEqual(result['summary']['status'], 'cancelled')
            self.assertEqual(result['summary']['not_run'], 3)

    def test_angle_sweep_preserves_angle_samples_and_has_no_wavelength_q(self):
        base = sample(mode='Angle sweep', angle_start=0, angle_stop=20, angle_step=10)
        cfg = parse_search(base, [], {})
        def executor(model, *args):
            self.assertEqual(model['points'], base['points'])
            return [[i,w,t,.4,.6,0.] for i,w,t in model['points']], {}
        with tempfile.TemporaryDirectory() as d:
            execute_search(base, DEFAULT_PERFORMANCE, cfg, d, executor, lambda e: None, lambda: False)
            self.assertEqual(analyze_grid_results(d, metric='Q factor'), [])

    def test_unavailable_samples_are_retained_and_remaining_designs_run(self):
        base = sample()
        cfg = parse_search(base, [bound('thickness', 'Device', .1, .2, .1)], {})
        calls, events = [], []
        def executor(model, *args):
            calls.append(model)
            channels = [None, None, None] if len(calls) == 1 else [.4, .6, 0.]
            return [list(point)+channels for point in model['points']], {}
        with tempfile.TemporaryDirectory() as d:
            result = execute_search(base, DEFAULT_PERFORMANCE, cfg, d, executor, events.append, lambda: False)
            self.assertEqual(result['summary']['invalid'], 1)
            self.assertEqual(result['summary']['evaluated'], 1)
            self.assertEqual(result['summary']['spectral_points'], 2*len(base['points']))
            with (Path(d)/'design_1_spectrum.csv').open() as stream:
                unavailable = list(csv.DictReader(stream))
            self.assertEqual(len(unavailable), len(base['points']))
            self.assertTrue(all(row['R'] == row['T'] == row['A'] == '' for row in unavailable))
            self.assertEqual(len(analyze_grid_results(d)), 1)
            self.assertEqual(sum(e['kind'] == 'finalizing' for e in events), 1)
            self.assertTrue(Path(result['archive']).is_file())

    def test_cancelled_checkpoint_with_unavailable_samples_finishes_archive(self):
        base = sample()
        cfg = parse_search(base, [bound('thickness', 'Device', .1, .3, .1)], {})
        events, cancel = [], [False]
        with tempfile.TemporaryDirectory() as d:
            class CheckpointExecutor:
                directory = d
                index = 1
                def __call__(self, model, *args):
                    checkpoint = Path(d)/'evaluations'/'000001'/'batch_results.csv'
                    checkpoint.parent.mkdir(parents=True)
                    checkpoint.write_text('point_index,wavelength_nm,angle_deg,R,T,A\n0,1500,0,,,\n1,1501,0,.4,.6,0\n')
                    cancel[0] = True
                    raise Cancelled('User stopped sweep')
            def observe(event):
                if event['kind'] == 'finalizing':
                    self.assertFalse((Path(d)/'design_1_spectrum.csv').exists())
                events.append(event)
            result = execute_search(base, DEFAULT_PERFORMANCE, cfg, d, CheckpointExecutor(), observe, lambda: cancel[0])
            self.assertEqual(result['summary']['status'], 'cancelled')
            self.assertEqual(result['summary']['incomplete'], 1)
            self.assertEqual(result['summary']['not_run'], 2)
            self.assertEqual(result['summary']['spectral_points'], 2)
            self.assertEqual(sum(e['kind'] == 'finalizing' for e in events), 1)
            with (Path(d)/'all_spectra.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]['R'], '')
            with zipfile.ZipFile(result['archive']) as archive:
                self.assertIn('search_summary.json', archive.namelist())
                self.assertIn('evaluations/000001/batch_results.csv', archive.namelist())


if __name__ == '__main__':
    unittest.main()
