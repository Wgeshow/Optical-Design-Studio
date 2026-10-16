import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore, prepare_job
from research_catalog import field_schema, list_capabilities
from research_diagnostics import validate_request
from research_simulation import execute_research
from tests.test_thermal_integration import thermal_settings
from tests.test_custom_device_optics import options
from tests.test_research_simulation import inputs

APP = QApplication.instance() or QApplication([])


class ResearchCatalogTests(unittest.TestCase):
    def test_catalog_lists_only_callable_registered_models(self):
        from research_simulation import ADAPTERS
        actual = {(r['engine'], r['study']) for r in list_capabilities()}
        self.assertEqual(actual, set(ADAPTERS))
        self.assertTrue(field_schema('photonic_bands', 'band_structure'))
        with self.assertRaises(ValueError):
            field_schema('unknown', 'unknown')

    def test_numeric_diagnostic_targets_field_and_preserves_typed_adapter_error(self):
        cfg = inputs(); cfg['settings']['resolution'] = 'not finished'
        issues = validate_request({}, cfg)
        self.assertEqual(issues[0]['field'], 'resolution')
        self.assertEqual(issues[0]['workspace'], 'photonic_bands')
        self.assertTrue(issues[0]['id'])
        from input_diagnostics import InputValidationError, diagnostic
        exact = diagnostic('Missing radius', workspace='photonic_bands', field='geometry[0].radius', object_id='hole')
        with patch('research_simulation.prepare_research_job', side_effect=InputValidationError([exact])):
            self.assertEqual(validate_request({}, inputs())[0]['field'], 'geometry[0].radius')
        from pcsel_research import paper_example
        for engine, study, settings in [('photonic_bands', 'band_structure', inputs()['settings']),
                                        ('pcsel', 'research', paper_example())]:
            exact = diagnostic('Missing object property', workspace='research_studies', field='layers', object_id='layer-1')
            with patch('research_simulation.prepare_research_job', side_effect=InputValidationError([exact])):
                issue = validate_request({}, dict(engine=engine,study=study,settings=settings))[0]
            self.assertEqual(issue['model_id'], engine)
            self.assertEqual(issue['object_id'], 'layer-1')
            self.assertEqual(issue['field'], 'layers')

    def test_unfinished_workspace_roundtrip_keeps_strings_and_existing_settings(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            a = ProjectStore(DataLibrary(Path(folder)/'a'), restore=False)
            previous = copy.deepcopy(a.settings)
            draft = dict(schema_version=1, bands=dict(settings=dict(resolution='16e', radius=''), ui=dict(section='geometry')))
            a.save_search('research_workspaces', draft)
            b = ProjectStore(DataLibrary(Path(folder)/'b'), restore=False)
            b.load_project(a.portable_project())
            self.assertEqual(b.search_state['research_workspaces'], draft)
            self.assertEqual(a.settings, previous)

    def test_standalone_heat_uses_edited_project_without_electrical_solver(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store = ProjectStore(DataLibrary(Path(folder)/'library'), restore=False)
            cfg = options(); cfg['device']['shapes'] = []
            store.device = cfg['device']; store.electrical_materials = cfg['material_library']
            request = dict(engine='thermal', study='steady_state', settings=thermal_settings())
            _, job = prepare_job('research_simulation', store.project(), request, store.library)
            with patch('custom_electrical_solver.solve', side_effect=AssertionError('No electrical solve required')):
                event = execute_research(job['search'], Path(folder)/'run')
            summary = event['summary']
            self.assertEqual(summary['status'], 'complete')
            self.assertGreater(summary['checks']['maximum_temperature_K'], 300.)
            self.assertLess(summary['checks']['relative_power_balance'], 1e-7)
            self.assertFalse(Path(summary['volume_npz']).is_absolute())


if __name__ == '__main__':
    unittest.main()
