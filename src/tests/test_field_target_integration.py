"""End-to-end field-guided search with synthetic spectra and complete field CSVs."""
import csv
import math
from pathlib import Path
import tempfile
import unittest

from data_library import read_json, write_json
from field_solver import material_at
from field_tracking import enrich_fields
from model import DEFAULT_PERFORMANCE
from peak_optimizer import parse_search
from target_optimizer import execute_target_search
from test_backend import sample


def full_fields(model, perf, cfg, directory, cancelled):
    """Analytic moving field profile; descriptors use the production CSV reader."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory/'field_model.json', dict(model=model, wavelength_nm=cfg['wavelength_nm'], settings=cfg))
    components = ('Ex', 'Ey', 'Ez', 'Hx', 'Hy', 'Hz')
    headers = ['plane', 'layer', 'x_um', 'y_um', 'z_um']
    headers += [component+'_'+part for component in components for part in ('real', 'imag')]
    headers += ['E2', 'material']
    with (directory/'electric_fields.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        start = 0.
        for layer in model['layers'][1:-1]:
            thickness = layer['thickness']
            center = (thickness-.25)*3.
            for fraction in (1/6, .5, 5/6):
                for i in range(cfg['grid']):
                    for j in range(cfg['grid']):
                        x = model['ax']*((i+.5)/cfg['grid']-.5)
                        y = model['ay']*((j+.5)/cfg['grid']-.5)
                        # Large intensity deliberately does not imply qualifying absorption/Q.
                        amplitude = 1000.*math.exp(-20.*(x/model['ax']-center)**2)
                        phase = .01*(cfg['wavelength_nm']-1550.)*fraction
                        electric = amplitude*complex(math.cos(phase), math.sin(phase))
                        values = (electric, .1*electric*center, 0j, 0j, electric/1.5, 0j)
                        row = ['volume_samples', layer['name'], x, y, start+thickness*fraction]
                        row += [part for value in values for part in (complex(value).real, complex(value).imag)]
                        row += [sum(abs(v)**2 for v in values[:3]), material_at(model, layer, x, y)]
                        writer.writerow(row)
            start += thickness
    return enrich_fields(directory)


def configuration(base, **updates):
    cfg = parse_search(base, [dict(Parameter='thickness', Target='Device', Min=.2, Max=.3, Step=.01, Choices='')],
                       dict(search_mode='ML assisted', initial_designs=2, ml_trials=5, candidate_pool=32,
                            random_seed=42, design_budget=12, point_budget=100000,
                            refinement_rounds=2, finalists=1))
    cfg.update(target_nm=1550., tolerance_nm=5., minimum_q=1000., use_fields=True, field_grid=3,
               map_grid=3, track_resonance=True, history_limit=50, reuse_saved=False, all_shape_bridges=True)
    cfg.update(updates)
    return cfg


def spectra(amplitude, halfwidth):
    def execute(model, perf, emit, cancelled):
        center = 1550.017+40.*(model['layers'][1]['thickness']-.25)
        rows = []
        for i, wavelength, angle in model['points']:
            absorption = amplitude/(1.+((wavelength-center)/halfwidth)**2)
            rows.append([i, wavelength, angle, 1.-absorption, 0., absorption])
        return rows, {}
    return execute


class FieldTargetIntegrationTests(unittest.TestCase):
    def run_search(self, folder, base, cfg, executor):
        folder.mkdir()
        result = execute_target_search(base, dict(DEFAULT_PERFORMANCE, timeout_seconds=120), cfg, folder,
                                       executor, lambda event: None, lambda: False, full_fields)
        self.assertEqual(result['summary']['status'], 'complete', result)
        history = read_json(folder/'target_history.json')['observations']
        return result['summary'], history

    def test_full_field_guidance_persists_reuses_and_cannot_bypass_absorption_or_q(self):
        base = sample(wl_start_nm=1535., wl_stop_nm=1565., wl_step_nm=.2)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for label, amplitude, width in [('absorption', .985, .5), ('q', .9995, 2.)]:
                with self.subTest(failing_constraint=label):
                    cfg = configuration(base)
                    family_root = root/(label+'_family')
                    family_root.mkdir()
                    output = family_root/label
                    summary, records = self.run_search(output, base, cfg, spectra(amplitude, width))
                    self.assertGreaterEqual(summary['field_informed_proposals'], 1, summary)
                    self.assertGreater(summary['field_comparisons'], 0)
                    self.assertGreater(summary['field_feature_records'], 8)
                    self.assertIsNone(summary['maximum_verified_Q'])
                    self.assertFalse((output/'recommended_design.json').exists())
                    self.assertTrue(all(o['targets']['feasible_q'] is None for o in records))
                    self.assertTrue(all('field_error' not in o for o in records))
                    for record in records:
                        self.assertEqual(record['fields']['sampling_mode'], 'fixed_target')
                        self.assertEqual(record['fields']['wavelength_nm'], 1550.)
                        self.assertEqual(record['resonance_fields']['sampling_mode'], 'selected_resonance')
                        self.assertAlmostEqual(record['resonance_fields']['wavelength_nm'], record['targets']['q_wavelength'])
                        folder = output/f'target_design_{record["id"]}'
                        self.assertTrue((folder/'fields'/'electric_fields.csv').exists())
                        self.assertTrue((folder/'field_tracking.json').exists())
                    with (output/'field_training.csv').open(newline='', encoding='utf-8') as stream:
                        training = list(csv.DictReader(stream))
                    self.assertEqual(len(training), summary['field_feature_records'])
                    self.assertEqual({row['mode'] for row in training}, {'fields', 'resonance_fields'})
                    with (output/'field_comparisons.csv').open(newline='', encoding='utf-8') as stream:
                        comparisons = list(csv.DictReader(stream))
                    self.assertEqual(len(comparisons), summary['field_comparisons'])
                    self.assertTrue(all(0. <= float(row['field_overlap']) <= 1. for row in comparisons))
            # Refit from completed, compatible JSON+CSV records with only one new trial.
            cfg = configuration(base, reuse_saved=True, ml_trials=1)
            summary, records = self.run_search(root/'absorption_family'/'reused', base, cfg, spectra(.985, .5))
            self.assertGreaterEqual(summary['reused_training_records'], 5)
            self.assertGreaterEqual(summary['reused_field_records'], 8)
            self.assertGreaterEqual(summary['field_informed_proposals'], 1)
            self.assertIsNone(summary['maximum_verified_Q'])
            fresh = [o for o in records if o['source'] == 'new' and o['phase'] == 'exploration']
            self.assertEqual(len(fresh), 1)
            self.assertIn('field_surrogates', fresh[0]['prediction'])


if __name__ == '__main__':
    unittest.main()
