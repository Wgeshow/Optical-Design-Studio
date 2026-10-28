"""Journeys reveal the real bound controls without changing a solver request."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel_research_setup import PcselResearchWorkspace
from qt_pcsel import PCSELPage
from research_catalog import list_capabilities

APP = QApplication.instance() or QApplication([])


class PcselJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pcsel-journey-', dir=Path.cwd())
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page.close(); page.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def page(self, engine='pcsel'):
        cap = next(row for row in list_capabilities() if row['engine'] == engine)
        page = PcselResearchWorkspace(self.store, cap)
        page.resize(1250, 850); page.show(); APP.processEvents()
        self.pages.append(page)
        return page

    def test_distinct_model_routes_keep_hidden_inputs_and_bound_widget_identity(self):
        page = self.page(); page.load_pcsel_example()
        field = page.fields['beam_power_source']; field.setText('Measured calibration fixture')
        expected = copy.deepcopy(page.options()['settings'])
        starts = {}
        for model in ('vertical', 'cwt', 'finite', 'beam', 'aperture', 'gme', 'rcwa_poles'):
            page.fields['model'].setCurrentIndex(page.fields['model'].findData(model))
            page.study_flow.show_stage(0); APP.processEvents()
            starts[model] = page.study_flow.stages[0][0]
            self.assertIs(page.fields['beam_power_source'], field)
            actual = page.options()['settings']; actual['model'] = expected['model']
            self.assertEqual(actual, expected)
        self.assertEqual(starts['beam'], 'Source mode')
        self.assertEqual(starts['aperture'], 'Calibration')
        self.assertEqual(starts['vertical'], 'Layer stack')
        self.assertIn('__journey_check', page.sections)
        self.assertIn('__journey_run', page.sections)

    def test_aperture_diagnostic_reveals_split_thermal_field_without_replacing_draft(self):
        page = self.page(); page.select_model('aperture'); page._create_fields('aperture')
        form, _ = page.aperture_journey_forms['aperture_thermal']
        control = form.controls['sheet_ohm_square']; control.setText('1e-')
        before = copy.deepcopy(page.draft())
        page.study_flow.show_results()
        self.assertTrue(page.open_diagnostic(dict(field='aperture.sheet_ohm_square')))
        APP.processEvents()
        self.assertTrue(control.isVisible())
        self.assertEqual(control.text(), '1e-')
        self.assertEqual(page.draft()['structured'], before['structured'])

    def test_periodic_cell_has_distinct_material_bias_and_mesh_runtime_stages(self):
        page = self.page('pcsel_transport')
        self.assertEqual([row[0] for row in page.study_flow.stages[:3]],
                         ['Periodic cell', 'Materials & bias', 'Mesh & environment'])
        page.study_flow.show_stage(1); APP.processEvents()
        self.assertIn(page.tabs.currentIndex(), page.study_flow.stages[1][1])

    def test_review_includes_only_current_physics_and_keeps_invalid_tree_values(self):
        page = self.page(); page.load_pcsel_example()
        page.geometry_editor.form.controls['thickness_nm'].setText('1e-')
        rows = page.journey_review_fields(); keys = {row[0] for row in rows}
        self.assertIn('layers', keys); self.assertIn('grid_nm', keys)
        self.assertNotIn('gmax', keys); self.assertNotIn('beam_mode', keys)
        self.assertIn('1e-', next(row[2] for row in rows if row[0]=='layers'))
        page.select_model('gme')
        keys = {row[0] for row in page.journey_review_fields()}
        self.assertIn('gmax', keys); self.assertIn('runtime', keys)
        self.assertNotIn('grid_nm', keys); self.assertNotIn('green_model', keys)

    def test_section_menu_contract_keeps_only_current_model_and_its_advanced_inputs(self):
        page=self.page();page.load_pcsel_example()
        allowed=page.journey_allowed_sections()
        self.assertIn(page.sections['geometry'],allowed)
        self.assertNotIn(page.sections['calibration'],allowed)
        self.assertNotIn(page.sections['advanced_runtime'],allowed)
        self.assertNotIn(page.sections['advanced_pole_seeds'],allowed)
        page.select_model('gme');allowed=page.journey_allowed_sections()
        self.assertIn(page.sections['advanced_runtime'],allowed)
        self.assertIn(page.sections['advanced_kpoints'],allowed)
        self.assertIn(page.sections['advanced_guided_modes'],allowed)
        self.assertNotIn(page.sections['calibration'],allowed)
        page.select_model('rcwa_poles');allowed=page.journey_allowed_sections()
        self.assertIn(page.sections['advanced_pole_seeds'],allowed)
        self.assertIn(page.sections['advanced_pole_bounds'],allowed)
        self.assertIn(page.sections['advanced_pole_excitation'],allowed)
        self.assertNotIn(page.sections['advanced_runtime'],allowed)
        page.select_model('aperture');allowed=page.journey_allowed_sections()
        self.assertIn(page.sections['calibration'],allowed)
        self.assertIn(page.sections['advanced_aperture'],allowed)
        self.assertIn(page.sections['advanced_aperture_um'],allowed)
        self.assertTrue(page.journey_stage_description('Aperture & physics',[]))

    def test_scalar_laser_stages_keep_parameters_and_actual_calculation(self):
        page = PCSELPage(None); self.pages.append(page)
        page.resize(1250, 850); page.show(); APP.processEvents()
        control = page.quality_factor
        page.current_points.setValue(5)
        page.active_volume.setValue(240)
        expected = page.laser_parameters()
        for index in range(6):
            page._show_laser_stage(index); APP.processEvents()
            self.assertEqual(page.laser_parameters(), expected)
            self.assertIs(page.quality_factor, control)
        self.assertFalse(page.gain_model.isEnabled())
        page._show_laser_stage(2)
        page.show_results();self.assertEqual(page.laser_stage,5)
        page.show_setup();self.assertEqual(page.laser_stage,2)
        self.assertTrue(page.workbench.properties.isVisible())
        self.assertTrue(page._check_laser_inputs())
        result = page.run_simulation()
        self.assertEqual(len(result['currents_ma']), 5)
        self.assertEqual(page.laser_stage, 5)
        page.active_volume.setValue(241)
        self.assertIn('stale', page.laser_run_note.text())
        page._show_laser_context(); APP.processEvents()
        self.assertTrue(page.workbench.objects_panel.isVisible())


if __name__ == '__main__':
    unittest.main()
