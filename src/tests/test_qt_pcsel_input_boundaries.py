"""PCSEL document import and scalar input checks; numerical solvers are mocked."""
import copy
import os
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel import PCSELPage
from qt_pcsel_research_setup import PcselResearchWorkspace
from qt_research_studies import ResearchStudiesWorkspace
from research_catalog import list_capabilities


class PcselInputBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pcsel-input-boundaries-')
        self.store = ProjectStore(DataLibrary(Path(self.temp.name) / 'library'), restore=False)
        self.store.study_navigation_enabled = True
        self.pages = []
        self.solver_guard = patch('qt_pcsel.solve_laser', side_effect=AssertionError('No numerical solve allowed in these UI boundary tests.'))
        self.solve = self.solver_guard.start()

    def tearDown(self):
        for page in self.pages:
            if hasattr(page, '_save_timer'):
                page._save_timer.stop()
            page.close()
            page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.solver_guard.stop()
        self.temp.cleanup()

    def laser(self):
        self.store.activate_study('lumped_laser')
        page = PCSELPage(self.store)
        self.pages.append(page)
        return page

    def pcsel(self, model):
        target = 'pcsel.' + model
        self.store.activate_study(target)
        cap = next(row for row in list_capabilities() if row['engine'] == 'pcsel')
        page = PcselResearchWorkspace(self.store, cap, document_id=target)
        page.bind_study_document(target)
        self.pages.append(page)
        return page

    def test_scalar_checks_accept_missing_and_invalid_optional_geometry(self):
        page = self.laser()
        page.pc_layer.clear()
        with self.assertRaisesRegex(ValueError, 'patterned device layer'):
            page.design()
        self.assertTrue(page._check_laser_inputs())
        self.assertIsNone(page._optional_design_context())
        self.solve.assert_not_called()

    def test_scalar_run_and_report_accept_missing_geometry_with_mocked_solver(self):
        page = self.laser()
        page.pc_layer.clear()
        # Deliberately synthetic UI fixture, never a numerical/reference result.
        result = dict(currents_ma=[0, 150], output_power_mw=[0, 1],
                      threshold_current_ma=1, photon_lifetime_ps=1,
                      threshold_gain_cm_1=1, slope_efficiency_w_per_a=1,
                      modulation={})
        result['threshold_gain_cm-1'] = result.pop('threshold_gain_cm_1')
        result['threshold_density_cm-3'] = 1
        self.solve.side_effect = [result, {'modulation': {}}]
        with ExitStack() as stack:
            for name in ('plot_dashboard', 'plot_mode', 'plot_laser', 'plot_modulation', 'plot_thermal', 'plot_sensitivity', 'retheme'):
                stack.enter_context(patch.object(page, name))
            self.assertIs(page.run_simulation(), result)
            self.assertEqual(self.solve.call_count, 2)
            self.assertIn('unavailable or incomplete', page.report.toPlainText())
            self.assertIn('not used by this scalar calculation', page.report.toPlainText())
            self.assertIn('Threshold current', page.quick.text())
            self.assertEqual(page.mode_table.item(0, 0).text(), 'User-supplied mode')
            # Imported overlays use the same optional geometry reporting path.
            result['comsol'] = dict(provenance={'model_name': 'Synthetic UI fixture', 'study': 'test'},
                                   current_ma=[0, 1], manifest_path='fixture.json')
            page._render_comsol()
            self.assertIn('COMSOL IMPORT', page.report.toPlainText())

    def test_required_laser_parameters_and_current_range_still_block_run(self):
        page = self.laser()
        page.pc_layer.clear()
        invalid = replace(page.laser_parameters(), confinement=0)
        with patch.object(page, 'laser_parameters', return_value=invalid):
            self.assertFalse(page._check_laser_inputs())
            self.assertIsNone(page.run_simulation())
        page.current_start.setValue(page.current_max.value())
        self.assertFalse(page._check_laser_inputs())
        self.assertIsNone(page.run_simulation())
        self.solve.assert_not_called()

    def test_recovered_geometry_keeps_every_bound_model_and_nongeometry_draft(self):
        from pcsel_research import paper_example
        expected = paper_example('hole', 'CC', .16)
        for model in ('vertical', 'cwt', 'finite', 'beam', 'aperture', 'gme', 'rcwa_poles'):
            with self.subTest(model=model):
                page = self.pcsel(model)
                page.fields['harmonics'].setText('17')
                page.fields['gmax'].setText('1e-')
                page.fields['beam_saved_run'].setText('existing-source-folder')
                page.structured['aperture'].set_value(dict(load_source='Existing independent calibration', load_anchors=[]))
                before = copy.deepcopy(page.draft())
                device_before = copy.deepcopy(self.store.device)
                page.load_pcsel_example()
                after = page.draft()
                self.assertEqual(self.store.active_study, 'pcsel.' + model)
                self.assertEqual(page.fields['model'].currentData(), model)
                self.assertEqual(self.store.device, device_before)
                geometry = {'lattice_nm', 'layers', 'shapes', 'top_index', 'bottom_index', 'inclusion_index'}
                for key, value in before['fields'].items():
                    if key not in geometry:
                        self.assertEqual(after['fields'][key], value, key)
                for key, value in before['structured'].items():
                    if key not in geometry:
                        self.assertEqual(after['structured'][key], value, key)
                self.assertEqual(page.structured['layers'].value(), expected['layers'])
                self.assertEqual(page.structured['shapes'].value(), expected['shapes'])
                self.assertEqual(len(page.geometry_editor.preview.last_geometry[0]), len(expected['layers']))
                self.assertIn('geometry loaded', page.status.text())
        self.solve.assert_not_called()

    def test_full_import_rejects_other_model_without_changing_current_draft(self):
        from pcsel_research import paper_example
        page = self.pcsel('cwt')
        page.fields['harmonics'].setText('23')
        before = copy.deepcopy(page.draft())
        with self.assertRaisesRegex(ValueError, 'different simulation type'):
            page.load_settings(paper_example())
        self.assertEqual(page.draft(), before)
        self.assertEqual(self.store.active_study, 'pcsel.cwt')

    def test_paper_copy_routes_to_its_model_and_preserves_other_study(self):
        from benchmark_registry import editable_copy
        self.store.activate_study('pcsel.cwt')
        chooser = ResearchStudiesWorkspace(self.store)
        self.pages.append(chooser)
        chooser.select_engine('pcsel')
        cwt = chooser._pages['pcsel']
        cwt.fields['harmonics'].setText('23')
        def activate(target):
            chooser.flush_draft()
            self.store.activate_study(target)
        chooser.simulationRequested.connect(activate)
        for identity in ('pcsel_2021_hole_cc_finite', 'pcsel_2021_hole_vertical', 'pcsel_2021_hole_vertical'):
            index = chooser.benchmarks.findData(identity)
            self.assertGreaterEqual(index, 0, chooser.benchmark_note.text())
            chooser.benchmarks.setCurrentIndex(index)
            chooser.duplicate_benchmark()
            case = editable_copy(identity)
            target = 'pcsel.' + case['options']['settings']['model']
            self.assertEqual(self.store.active_study, target, chooser.benchmark_note.text())
            page = chooser._pages['pcsel']
            for key, value in case['options']['settings'].items():
                self.assertEqual(page.options()['settings'][key], value, key)
            self.assertEqual(page._benchmark_request['id'], identity)
        self.store.activate_study('pcsel.cwt')
        chooser.select_engine('pcsel')
        self.assertEqual(chooser._pages['pcsel'].fields['harmonics'].text(), '23')
        self.solve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
