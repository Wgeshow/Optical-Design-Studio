"""Guided setup must preserve exact inputs, raw drafts and field destinations."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox
from data_library import DataLibrary
from qt_core import ProjectStore
from research_catalog import list_capabilities
from qt_transport_research_setup import TransportResearchWorkspace, HighFieldOpticsWorkspace
from qt_research_common import label
from qt_study_library import StudyLibrary

APP = QApplication.instance() or QApplication([])


def optical_settings():
    return dict(wavelengths_nm=[800., 850., 900.],
        material=dict(electron_mass_ratio=.067, hole_mass_ratios=[.5, .087],
            absorption_prefactor_cm1_sqrt_eV=100000., reference_gap_eV=1.42, source='Explicit test inputs'),
        samples=[dict(id='test-state', bandgap_eV=1.42, field_V_m=1e7, temperature_K=300.,
            electron_reduced_fermi=-12., hole_reduced_fermi=-12.)], energy_order=128, energy_upper_eV=6.)


class StudyUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='study-ui-', dir=Path(os.environ.get('TEMP', '.')))
        self.root = Path(self.temp.name)
        self.store = ProjectStore(DataLibrary(self.root/'library'), restore=False)
        self.pages = []
        self.capabilities = {row['engine']: row for row in list_capabilities()}

    def tearDown(self):
        for page in self.pages:
            if hasattr(page, '_save_timer'):
                page._save_timer.stop()
            page.close(); page.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def page(self, engine):
        cls = HighFieldOpticsWorkspace if engine == 'high_field_optics' else TransportResearchWorkspace
        page = cls(self.store, self.capabilities[engine])
        page.resize(1200, 850); page.show(); APP.processEvents()
        self.pages.append(page)
        return page

    def test_high_field_exact_roundtrip_and_visible_missing_value(self):
        page = self.page('high_field_optics')
        settings = optical_settings()
        page.load_settings(settings)
        self.assertEqual(page.options()['settings'], settings)
        target = dict(field='samples.0.field_V_m', object_id='test-state', workspace='research_studies')
        self.assertTrue(page.open_diagnostic(target))
        control = page.input_forms['samples']._fields['field_V_m']
        self.assertTrue(control.isVisible())
        control.setFocus(); control.selectAll(); QTest.keyClicks(control, '1e-')
        page.flush_draft()
        with self.assertRaises(ValueError):
            page.options()
        saved = self.store.portable_project()
        other = ProjectStore(DataLibrary(self.root/'other'), restore=False)
        other.load_project(saved)
        restored = HighFieldOpticsWorkspace(other, self.capabilities['high_field_optics'])
        self.pages.append(restored)
        self.assertEqual(restored.structured['samples'].tree.topLevelItem(0).child(0).child(2).text(1), '1e-')

    def test_new_high_field_inputs_are_explicit_blanks_and_use_backend_names(self):
        page = self.page('high_field_optics')
        page.create_material_fields(); page.add_sample()
        draft = page.structured['samples'].draft()['children'][0]['children']
        values = {row['name']: row for row in draft}
        self.assertEqual(set(values), {'id', 'bandgap_eV', 'field_V_m', 'temperature_K', 'electron_reduced_fermi', 'hole_reduced_fermi'})
        self.assertTrue(all(row['value'] == '' for key, row in values.items() if key != 'id'))
        self.assertTrue(all(row['type'] == 'number' for key, row in values.items() if key != 'id'))

    def test_transport_form_edit_keeps_shared_device_and_raw_bias(self):
        before = copy.deepcopy(self.store.device)
        page = self.page('advanced_transport')
        form = page.input_forms['biases_V']
        page.study_flow.show_stage(0)
        page.select_section('Bias')
        form.input.setFocus(); QTest.keyClicks(form.input, '0, 0.1, 1e-')
        page.flush_draft()
        self.assertEqual(page.structured['biases_V'].draft()['children'][-1]['value'], '1e-')
        self.assertEqual(self.store.device, before)
        self.assertFalse(page.tabs.tabBar().isVisible())
        stage_titles=[title for title,_ in page.study_flow.stages]
        for name in ('Device','Contacts & materials','Optional physics','Accuracy & sources','Check inputs','Run & progress','Results'):
            self.assertIn(name,stage_titles)
        self.assertEqual(len(page.study_flow.menu.actions()), page.tabs.count()+2)

    def test_paper_search_and_family_keep_real_case_identity(self):
        from benchmark_registry import list_benchmarks
        combo = QComboBox()
        widget = StudyLibrary(combo, lambda: None, lambda: None, label(''))
        self.pages.append(widget)
        widget.set_cases(list_benchmarks())
        self.assertEqual(combo.count(), 24)
        widget.search.setText('grain')
        self.assertEqual(combo.count(), 1)
        self.assertEqual(combo.currentData(), 'sesame_2d_grain_boundary')
        widget.search.clear()
        widget.family.setCurrentIndex(widget.family.findData('Optical spectra'))
        self.assertEqual(combo.count(), 8)


if __name__ == '__main__':
    unittest.main()
