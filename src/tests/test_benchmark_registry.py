import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
import benchmark_registry as registry
from data_library import DataLibrary
from qt_core import ProjectStore, prepare_job

APP = QApplication.instance() or QApplication([])


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_all_bundled_cases_hash_and_prepare_through_normal_job_path(self):
        library = DataLibrary(self.root/'library')
        for meta in registry.list_benchmarks():
            with self.subTest(case=meta['id']):
                case = registry.editable_copy(meta['id'])
                _, job = prepare_job(case['kind'], case['project'], case['options'], library)
                self.assertFalse(job['benchmark']['input_edited'])
                self.assertEqual(job['benchmark']['id'], meta['id'])

    def test_editable_duplicate_does_not_mutate_reference_and_detects_physical_edit(self):
        case = registry.editable_copy('jamois_airholes_2003')
        case['options']['settings']['geometry'][0]['radius'] = .4
        request = registry.prepare_comparison_request(case['project'], case['kind'], case['options'])
        self.assertTrue(request['input_edited'])
        self.assertEqual(registry.load_benchmark('jamois_airholes_2003')['options']['settings']['geometry'][0]['radius'], .43)
        case = registry.editable_copy('jamois_airholes_2003')
        case['options']['settings']['runtime'] = dict(mode='wsl', distro='Runtime selected by user')
        self.assertFalse(registry.prepare_comparison_request(case['project'], case['kind'], case['options'])['input_edited'])
        case['project']['device'] = {'name': 'Unrelated finite device remains open'}
        self.assertFalse(registry.prepare_comparison_request(case['project'], case['kind'], case['options'])['input_edited'])
        case=registry.editable_copy('sesame_1d_heterojunction')
        for region in case['options']['settings']['regions']:
            region.setdefault('donors_cm3',0.)
            region.setdefault('acceptors_cm3',0.)
        self.assertFalse(registry.prepare_comparison_request(case['project'],case['kind'],case['options'])['input_edited'])

    def test_modified_bundled_reference_fails_checksum(self):
        shutil.copytree(registry.ROOT, self.root/'bundle')
        target = self.root/'bundle'/'fan_pc_r05'/'reference.csv'
        target.write_text(target.read_text()+'\n')
        with patch.object(registry, 'ROOT', self.root/'bundle'), self.assertRaisesRegex(ValueError, 'checksum'):
            registry.load_benchmark('fan_pc_r05')

    def test_scalar_residual_keeps_disagreement_visible_without_validation_claim(self):
        (self.root/'electrical_cv.csv').write_text('bias_V,capacitance_F\n0,4e-11\n')
        result = registry.compare_run('xiong_al2o3_12p10nm', self.root)
        metric = result['results'][0]
        self.assertEqual(metric['status'], 'compared')
        self.assertAlmostEqual(metric['residuals'][0], 40000-84416)
        self.assertFalse(result['reproduction_accepted'])
        self.assertEqual(result['convergence_status'], 'not_established')

    def test_missing_results_are_not_zero_residuals_or_passes(self):
        result = registry.compare_run('fan_pc_r05', self.root)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['results'][0]['status'], 'unavailable')
        self.assertNotIn('rmse', result['results'][0])

    def test_pcsel_slope_is_explicit_conditional_estimate_from_actual_losses(self):
        (self.root/'finite_modes.csv').write_text('mode,wavelength_nm,total_loss_cm1,radiation_loss_cm1,eigen_residual,balance_relative\n'
            '0,1000,95,50,1e-10,1e-8\n1,1000,-1,1,0,0\n')
        result = registry.compare_run('pcsel_2021_hole_rit_finite', self.root)
        row = result['results'][0]
        self.assertEqual(row['status'], 'compared')
        self.assertAlmostEqual(row['observed'][0], .31)
        self.assertEqual(row['selected_mode'], 0)
        self.assertEqual(row['assumptions']['upward_fraction'], .5)
        self.assertFalse(result['reproduction_accepted'])

    def test_reference_launch_preserves_current_device_and_uses_snapshot(self):
        store = ProjectStore(DataLibrary(self.root/'library'), restore=False)
        previous = copy.deepcopy(store.device)
        with patch('qt_core.BackendWorker.start'):
            store.start_benchmark('xiong_al2o3_12p10nm')
        self.assertEqual(store.device, previous)
        self.assertEqual(store._worker.options['device'], store._worker.project['device'])
        self.assertNotEqual(store._worker.options['device'], previous)
        store._finished()

    def test_full_reference_project_roundtrips_optional_identity_and_clears_on_ordinary_load(self):
        store=ProjectStore(DataLibrary(self.root/'library'),restore=False)
        ordinary=store.project()
        case=registry.editable_copy('winn_ten_film')
        store.load_project(case['project'])
        self.assertEqual(store.project()['benchmark_request'],case['project']['benchmark_request'])
        reopened=ProjectStore(store.library,restore=True)
        self.assertEqual(reopened.portable_project()['benchmark_request'],case['project']['benchmark_request'])
        store.load_project(ordinary)
        self.assertNotIn('benchmark_request',store.project())


if __name__ == '__main__':
    unittest.main()
