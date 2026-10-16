"""Actual editable-device heat jobs through persistence, backend and export.

The fixture is an analytical QA geometry, not a calibrated material sample.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
import numpy as np

from data_library import DataLibrary, write_json
from qt_core import ProjectStore, prepare_job
from custom_device_optics import execute_custom_electrical
from tests.test_custom_device_optics import options


APP = QApplication.instance() or QApplication([])


def thermal_settings(**changes):
    return dict(dict(enabled=True, power_by_layer_W={'active': 1e-6},
        conductivity={'silicon': {'value_W_mK': 100., 'source': 'Analytical QA constant; not calibrated silicon'}},
        void_conductivity_W_mK=.026, ambient_temperature_K=300.,
        boundaries={'z_max': {'kind': 'fixed_temperature', 'temperature_K': 300.}},
        temperature_limit_K=310.), **changes)


class ThermalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods-thermal-job-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = DataLibrary(self.root/'library')
        self.store = ProjectStore(self.library, restore=False)
        self.cfg = options(optical_enabled=False, biases_V=[0.], thermal=thermal_settings())
        # No voids: exact heated slab provides an independently checkable bound.
        self.cfg['device']['shapes'] = []
        self.store.device = copy.deepcopy(self.cfg['device'])
        self.store.electrical_materials = copy.deepcopy(self.cfg['material_library'])

    def test_thermal_draft_roundtrip_and_preflight_validate_current_layer_ids(self):
        self.store.save_search('electrical', self.cfg)
        other = ProjectStore(DataLibrary(self.root/'other'), restore=False)
        other.load_project(self.store.portable_project())
        self.assertEqual(other.search_state['electrical']['thermal'], self.store.search_state['electrical']['thermal'])
        cfg = copy.deepcopy(self.cfg)
        cfg['thermal']['power_by_layer_W'] = {'not-a-layer': 1e-6}
        with self.assertRaises(ValueError):
            prepare_job('electrical', self.store.project(), cfg, self.library)

    def test_existing_setup_composer_keeps_thermal_for_electrical_and_coupled_runs(self):
        from simulation_setup_state import SimulationSetupState
        self.store.save_search('electrical', self.cfg)
        state = SimulationSetupState(self.store)
        for mode in ('electrical', 'coupled'):
            with self.subTest(mode=mode):
                cfg = state.job_options(mode)
                self.assertEqual(cfg['thermal'], self.store.search_state['electrical']['thermal'])
                self.assertEqual(cfg['optical_enabled'], mode == 'coupled')

    def test_backend_temperature_energy_and_portable_run_archive(self):
        project, job = prepare_job('electrical', self.store.project(), self.cfg, self.library)
        directory = self.library.runs/'thermal-editable-qa'
        directory.mkdir()
        write_json(directory/'project.json', project)
        write_json(directory/'job.json', job)
        process = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]/'backend.py'), '--job', str(directory/'job.json')],
            cwd=directory, capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(process.returncode, 0, process.stdout+'\n'+process.stderr)
        events = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
        event = next(row for row in events if row.get('kind') == 'search_complete')
        self.assertEqual(event['summary']['status'], 'complete')
        self.assertEqual(event['summary']['thermal']['volume_npz'], 'thermal/thermal_volume.npz')
        thermal_path = directory/event['summary']['thermal_summary_json']
        thermal = json.loads(thermal_path.read_text())
        self.assertEqual(thermal['model_scope'], 'prescribed_heat')
        volume_path = Path(thermal['volume_npz'])
        if not volume_path.is_absolute():
            volume_path = thermal_path.parent/volume_path
        with np.load(volume_path) as data:
            values = data['temperature_K']
            self.assertEqual(values.shape, (8, 8, 6))
            self.assertGreater(values.max(), 300.)
            self.assertLess(values.max(), 310.)
        self.library.record(directory, kind='simulation', title='Prescribed heat QA', status=event['summary']['status'], summary=event['summary'])
        bundle = self.library.export(directory.name)
        with zipfile.ZipFile(bundle) as archive:
            self.assertIn('runs/thermal-editable-qa/thermal/thermal_summary.json', archive.namelist())
            self.assertIn('runs/thermal-editable-qa/'+volume_path.relative_to(directory).as_posix(), archive.namelist())
        other = DataLibrary(self.root/'imported')
        imported = other.import_bundle(bundle)
        self.assertEqual(imported['runs'], 1)
        imported_run = other.runs/'thermal-editable-qa'
        saved = json.loads((imported_run/'search_summary.json').read_text())
        moved_thermal = imported_run/saved['thermal_summary_json']
        moved = json.loads(moved_thermal.read_text())
        self.assertFalse(Path(moved['volume_npz']).is_absolute())
        self.assertTrue((moved_thermal.parent/moved['volume_npz']).is_file())

    def test_validity_limit_is_preserved_in_whole_job_status(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['thermal']['temperature_limit_K'] = 300.0001
        event = execute_custom_electrical(None, {}, cfg, self.root/'limited',
            lambda *args: self.fail('Electrical heat QA must not invoke optical solver'))
        self.assertEqual(event['summary']['status'], 'validity_limit')
        self.assertEqual(event['summary']['thermal']['status'], 'validity_limit')
        self.assertIn('not evidence of thermal runaway', event['summary']['thermal']['status_reason'])


if __name__ == '__main__':
    unittest.main()
