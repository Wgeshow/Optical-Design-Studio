"""Checks that field guidance enriches proposals without replacing spectral evidence."""
import copy
import json
import math
import unittest
from unittest.mock import patch

import numpy as np

import field_ml
from ml_optimizer import acquisition as spectral_acquisition


def config(**updates):
    result = dict(dimensions=[dict(parameter='thickness', values=[0., 1.])],
                  field_grid=3, target_nm=1550., tolerance_nm=5.,
                  initial_designs=3, absorption_target=.99, track_resonance=True)
    result.update(updates)
    return result


def descriptor(x, mode='fixed_target', **updates):
    result = dict(schema_version=2, wavelength_nm=1550., grid=3,
                  sampling_mode=mode, sampling_method='test-volume-quadrature',
                  fixture={'confinement': x*x, 'hotspot_x': math.sin(math.pi*x)})
    result.update(updates)
    return result


def observations(count=5):
    records = []
    for i, x in enumerate(np.linspace(0., 1., count)):
        records.append(dict(values=[float(x)], status='evaluated', phase='exploration',
                            targets=dict(absorption=.999, log_q=math.log(100.+i*100.),
                                         q_absorption=.999 if i == 0 else .8,
                                         feasible_q=100. if i == 0 else None)))
    return records


def field_records(count=4):
    return [dict(values=[float(x)], status='evaluated', phase='exploration',
                 fields=descriptor(float(x))) for x in np.linspace(0., 1., count)]


def simple_field_prediction(x, y, queries, noise):
    queries = np.asarray(queries)
    return .25+.5*queries[:, 0], np.full(len(queries), .2), []


class FieldMLTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config()
        self.pool = [[.1], [.4], [.8]]
        # Descriptor arithmetic is tested in test_field_tracking; these fixtures
        # isolate the learned-field/spectral-model boundary.
        self.vector = patch('field_ml.feature_vector', side_effect=lambda d: d['fixture'])
        self.vector.start()
        self.addCleanup(self.vector.stop)

    def test_sparse_duplicate_constant_and_nonfinite_fields_fall_back(self):
        observed = observations()
        sparse = field_records(3)
        self.assertIsNone(field_ml.field_augmented_candidate(self.pool, observed, sparse, self.cfg))
        repeated = [copy.deepcopy(sparse[0]) for _ in range(10)]
        self.assertIsNone(field_ml.field_augmented_candidate(self.pool, observed, repeated, self.cfg))
        constant = field_records()
        for row in constant:
            row['fields']['fixture'] = {'confinement': 1.}
        self.assertIsNone(field_ml.field_augmented_candidate(self.pool, observed, constant, self.cfg))
        invalid = field_records()
        invalid[-1]['fields']['fixture']['confinement'] = float('nan')
        self.assertIsNone(field_ml.field_augmented_candidate(self.pool, observed, invalid, self.cfg))

    def test_wavelength_grid_schema_and_verification_are_not_mixed(self):
        good = field_records()
        invalid = []
        for index, updates in enumerate(({'wavelength_nm': 1551.}, {'grid': 5},
                                        {'schema_version': 1}, {'sampling_mode': 'selected_resonance'},
                                        {'schema_version': '2'}, {'schema_version': None})):
            row = dict(values=[.11+index*.01], status='evaluated', phase='exploration',
                       fields=descriptor(.1, **updates))
            invalid.append(row)
        invalid.append(dict(values=[.17], status='evaluated', phase='verification', fields=descriptor(.17)))
        invalid.append(dict(values=[.18], status='failed', phase='exploration', fields=descriptor(.18)))
        with patch('field_ml.fit_predict', side_effect=simple_field_prediction), \
                patch('field_ml.acquisition', return_value=(0, {'selection_reason': 'test'})):
            _, prediction = field_ml.field_augmented_candidate(self.pool, observations(), good+invalid, self.cfg)
        self.assertEqual(prediction['field_surrogates'][0]['observations'], 4)
        self.assertEqual(prediction['field_surrogates'][0]['mode'], 'fixed_target')

    def test_overlap_covariates_compare_every_design_with_one_common_reference(self):
        records = field_records()
        compared = []

        def compare(current, reference):
            compared.append((current, reference))
            overlap = 1.-abs(current['fixture']['confinement']-reference['fixture']['confinement'])
            return dict(compatible=True, field_overlap=overlap,
                        layers={'Device': {'field_overlap': overlap}})

        with patch('field_ml.compare_fields', side_effect=compare):
            rows, names = field_ml._field_rows(records, self.cfg, 'fields')
        self.assertEqual(len(compared), len(records))
        self.assertTrue(all(reference is records[0]['fields'] for _, reference in compared))
        index = names.index('reference_overlap')
        np.testing.assert_allclose([row[1][index] for row in rows], [1., 8/9, 5/9, 0.])

    def test_missing_overlap_signature_keeps_original_features_for_all_records(self):
        records = field_records()

        def compare(current, reference):
            if current is records[-1]['fields']:
                return dict(compatible=False, reason='missing signature')
            return dict(compatible=True, field_overlap=1., layers={'Device': {'field_overlap': 1.}})

        with patch('field_ml.compare_fields', side_effect=compare):
            rows, names = field_ml._field_rows(records, self.cfg, 'fields')
        self.assertEqual(names, ['confinement', 'hotspot_x'])
        self.assertEqual(len(rows), 4)
        for row, record in zip(rows, records):
            self.assertEqual(row[1], [record['fields']['fixture'][key] for key in names])

    def test_training_and_candidates_both_use_predicted_field_covariates(self):
        observed = observations()
        before = copy.deepcopy(observed)
        records = field_records()
        captured = {}

        def capture(obs, candidates, cfg):
            captured.update(obs=obs, candidates=candidates, cfg=cfg)
            return 1, {'selection_reason': 'test'}

        with patch('field_ml.fit_predict', side_effect=simple_field_prediction) as fitted, \
                patch('field_ml.acquisition', side_effect=capture):
            chosen, _ = field_ml.field_augmented_candidate(self.pool, observed, records, self.cfg)
        self.assertEqual(chosen, self.pool[1])
        self.assertEqual(observed, before, 'Field proposals must not alter measured spectral targets')
        self.assertEqual([o['targets'] for o in captured['obs']], [o['targets'] for o in observed])
        queries = np.asarray(fitted.call_args.args[2])
        self.assertEqual(len(queries), len(observed)+len(self.pool))
        expected = .35*np.tanh(.25+.5*queries[:, 0])
        actual = np.asarray([o['values'] for o in captured['obs']]+captured['candidates'])
        np.testing.assert_allclose(actual[:, 0], queries[:, 0])
        np.testing.assert_allclose(actual[:, 1], expected)
        self.assertTrue(np.all(np.abs(actual[:, 1]) < .35))

    def test_resonance_and_fixed_target_fit_separate_models(self):
        records = field_records()
        for i, row in enumerate(records):
            x = row['values'][0]
            row['resonance_fields'] = descriptor(x, 'selected_resonance', wavelength_nm=1546.+i*2.)
        # This is inside neither the fixed-target condition nor resonance tolerance.
        records.append(dict(values=[.2], status='evaluated', phase='exploration',
                            resonance_fields=descriptor(.2, 'selected_resonance', wavelength_nm=1560.)))
        with patch('field_ml.fit_predict', side_effect=simple_field_prediction) as fit, \
                patch('field_ml.acquisition', return_value=(0, {'selection_reason': 'test'})):
            _, prediction = field_ml.field_augmented_candidate(self.pool, observations(), records, self.cfg)
        self.assertEqual(fit.call_count, 2)
        self.assertEqual([item['mode'] for item in prediction['field_surrogates']],
                         ['fixed_target', 'selected_resonance'])
        self.assertEqual([item['observations'] for item in prediction['field_surrogates']], [4, 4])
        with patch('field_ml.fit_predict', side_effect=simple_field_prediction) as fit, \
                patch('field_ml.acquisition', return_value=(0, {'selection_reason': 'test'})):
            _, prediction = field_ml.field_augmented_candidate(self.pool, observations(), records,
                                                               config(track_resonance=False))
        self.assertEqual(fit.call_count, 1)
        self.assertEqual(len(prediction['field_surrogates']), 1)

    def test_augmented_q_acquisition_retains_paired_peak_absorption(self):
        observed = observations()
        targets_seen = []

        def spectral_prediction(x, y, candidates, noise):
            targets_seen.append(list(y))
            return np.full(len(candidates), float(np.mean(y))), np.full(len(candidates), .1), []

        with patch('field_ml.fit_predict', side_effect=simple_field_prediction), \
                patch('ml_optimizer.fit_predict', side_effect=spectral_prediction), \
                patch('field_ml.acquisition', side_effect=spectral_acquisition):
            _, prediction = field_ml.field_augmented_candidate(self.pool, observed, field_records(), self.cfg)
        self.assertIn('Q improvement', prediction['selection_reason'])
        self.assertEqual(targets_seen[0], [o['targets']['absorption'] for o in observed])
        self.assertEqual(targets_seen[1], [o['targets']['log_q'] for o in observed])
        self.assertEqual(targets_seen[2], [.999, .8, .8, .8, .8])
        self.assertIsNotNone(prediction['paired_peak_probability'])

    def test_large_history_retains_q_schedule_after_fit_limit(self):
        def spectral_prediction(x,y,candidates,noise):
            return np.full(len(candidates),float(np.mean(y))),np.full(len(candidates),.1),[]
        with patch('field_ml.fit_predict',side_effect=simple_field_prediction), \
                patch('ml_optimizer.fit_predict',side_effect=spectral_prediction), \
                patch('field_ml.acquisition',side_effect=spectral_acquisition):
            _,prediction=field_ml.field_augmented_candidate(self.pool,observations(269),field_records(),self.cfg)
        self.assertIn('Q improvement',prediction['selection_reason'])

    def test_exploration_diagnostics_describe_selected_uncertain_candidate(self):
        queried_candidates = []

        def field_prediction(x, y, queries, noise):
            mean, _, alerts = simple_field_prediction(x, y, queries, noise)
            std = np.full(len(queries), .1)
            std[-1] = 2.
            return mean, std, alerts

        def spectral_prediction(obs, candidates, cfg):
            queried_candidates.append(copy.deepcopy(candidates))
            return 0, {'selection_reason': 'test', 'predicted_absorption': candidates[0][0]}

        with patch('field_ml.fit_predict', side_effect=field_prediction), \
                patch('field_ml.acquisition', side_effect=spectral_prediction):
            chosen, prediction = field_ml.field_augmented_candidate(self.pool, observations(), field_records(),
                                                                    self.cfg, explore=True)
        self.assertEqual(chosen, [.8])
        self.assertEqual(prediction['predicted_absorption'], .8)
        self.assertEqual(prediction['field_uncertainty'], 2.)
        self.assertEqual(len(queried_candidates[-1]), 1)

    def test_real_surrogate_refits_identically_after_json_history_roundtrip(self):
        observed, fields = observations(6), field_records(8)
        result = field_ml.field_augmented_candidate(self.pool, observed, fields, self.cfg)
        recovered = json.loads(json.dumps({'observations': observed, 'fields': fields}, allow_nan=False))
        restored = field_ml.field_augmented_candidate(self.pool, recovered['observations'], recovered['fields'], self.cfg)
        self.assertEqual(result[0], restored[0])
        self.assertAlmostEqual(result[1]['predicted_absorption'], restored[1]['predicted_absorption'], places=12)
        self.assertAlmostEqual(result[1]['field_uncertainty'], restored[1]['field_uncertainty'], places=12)
        self.assertIn(result[0], self.pool)
        json.dumps(result[1], allow_nan=False)


if __name__ == '__main__':
    unittest.main()
