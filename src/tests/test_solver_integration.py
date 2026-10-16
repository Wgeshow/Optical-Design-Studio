"""Desktop persistence and normal field-workflow checks for optimized solvers."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from model import DEFAULT_PERFORMANCE, performance
from qt_core import ProjectStore, desktop_performance, prepare_job
from data_library import DataLibrary
from PyQt6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class SolverIntegrationTests(unittest.TestCase):
    def test_saved_older_projects_gain_native_symmetry_default(self):
        p = desktop_performance(dict(workers=2, mode='CPU only'))
        self.assertEqual(p['solver_backend'], 'native')
        self.assertTrue(p['mirror_symmetry'])
        self.assertEqual(p['eigenfree_batch_size'], 32)

    def test_gpu_settings_survive_project_roundtrip_and_job_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProjectStore(DataLibrary(folder), restore=False)
            store.update_performance(dict(solver_backend='eigenfree-gpu',
                mirror_symmetry=False,eigenfree_symmetry=False,eigenfree_batch_size=16))
            saved = store.project()
            store.load_project(copy.deepcopy(saved))
            self.assertEqual(store.performance, saved['performance'])
            _, job = prepare_job('simulation', store.project(), {}, store.library)
            self.assertEqual(job['performance']['solver_backend'], 'eigenfree-gpu')
            self.assertEqual(job['performance']['effective_workers'], 1)
            self.assertEqual(job['performance']['eigenfree_batch_size'], 16)
            self.assertFalse(job['performance']['mirror_symmetry'])
            self.assertFalse(job['performance']['eigenfree_symmetry'])

    def test_invalid_backend_batch_and_boolean_inputs_are_rejected(self):
        for values in (dict(solver_backend='invalid'), dict(mirror_symmetry='yes'),
                       dict(eigenfree_symmetry=1), dict(eigenfree_batch_size=0),
                       dict(eigenfree_batch_size=257)):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    performance(values, 100, 16)
                with self.assertRaises(ValueError):
                    desktop_performance(values)

    def test_settings_controls_select_solver_and_bound_batches(self):
        from qt_compute import SettingsPage
        with tempfile.TemporaryDirectory() as folder:
            store = ProjectStore(DataLibrary(folder), restore=False)
            page = SettingsPage(store)
            try:
                box = page.controls['solver_backend']
                box.setCurrentIndex(box.findData('eigenfree-gpu'))
                self.assertEqual(store.performance['solver_backend'],'native')
                page.save_settings()
                self.assertEqual(store.performance['solver_backend'], 'eigenfree-gpu')
                self.assertTrue(page.controls['eigenfree_batch_size'].isEnabled())
                self.assertFalse(page.controls['mode'].isEnabled())
                self.assertFalse(page.controls['gpu_min_n'].isEnabled())
                page.controls['mirror_symmetry'].setChecked(False)
                page.save_settings()
                self.assertFalse(store.performance['eigenfree_symmetry'])
                box.setCurrentIndex(box.findData('native'))
                page.save_settings()
                self.assertTrue(page.controls['mode'].isEnabled())
                self.assertEqual(store.performance['mode'],'CPU only')
                self.assertEqual(store.performance['workers'],0)
                self.assertFalse(page.controls['eigenfree_batch_size'].isEnabled())
            finally:
                page.close()
                page.deleteLater()
                APP.processEvents()


if __name__ == '__main__':
    unittest.main()
