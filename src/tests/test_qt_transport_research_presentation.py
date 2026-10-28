"""Preview selection must preserve authored geometry and unfinished requests."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_transport_research_setup import TransportResearchWorkspace, HighFieldOpticsWorkspace
from research_catalog import list_capabilities
from test_qt_study_ui import optical_settings

APP = QApplication.instance() or QApplication([])


class TransportPresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='transport-layout-', dir=os.environ.get('TEMP', '.'))
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page._save_timer.stop(); page.close(); page.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def page(self, engine='advanced_transport'):
        cap = next(row for row in list_capabilities() if row['engine'] == engine)
        cls = HighFieldOpticsWorkspace if engine == 'high_field_optics' else TransportResearchWorkspace
        page = cls(self.store, cap)
        self.pages.append(page)
        page.resize(1400, 900); page.show(); APP.processEvents()
        return page

    def test_three_views_keep_actual_device_and_route_selected_identity(self):
        before = copy.deepcopy(self.store.device)
        for engine in ('advanced_transport', 'pcsel_unitcell_transport'):
            page = self.page(engine); panel = page.device_panel
            identity = before['layers'][0]['id']
            self.assertTrue(panel.select_object(identity))
            destinations = []; page.diagnosticRequested.connect(destinations.append)
            panel.edit_selected()
            self.assertEqual(destinations, [])
            self.assertEqual(page.device_editor.editor.selected_id, identity)
            self.assertEqual(page.tabs.currentIndex(), page.sections['device_editor'])
            for mode in ('3d', 'top', 'section'):
                panel.view_choice.setCurrentIndex(panel.view_choice.findData(mode))
                APP.processEvents()
                self.assertEqual(panel.canvas.mode, mode)
                self.assertEqual(panel.canvas.device, before)
            self.assertEqual(self.store.device, before)
            self.assertFalse(panel.select_object('removed-object'))

    def test_compact_preview_and_raw_bias_roundtrip(self):
        page = self.page(); page.resize(800, 760); APP.processEvents()
        panel = page.device_panel
        self.assertEqual(page.width(), 800)
        self.assertTrue(panel.compact_choice.isVisible())
        control = panel.bias.input
        control.setFocus(); QTest.keyClicks(control, '0, 0.1, 1e-')
        draft = copy.deepcopy(page.draft())
        panel.compact_choice.setCurrentIndex(1); APP.processEvents()
        self.assertTrue(panel.canvas.isVisible())
        self.assertFalse(panel.right.isVisible())
        page.restore_draft(draft)
        self.assertEqual(page.structured['biases_V'].draft()['children'][-1]['value'], '1e-')
        self.assertTrue(page.open_diagnostic(dict(field='biases_V', workspace='advanced_transport')))
        self.assertTrue(page.input_forms['biases_V'].input.isVisible())
        self.assertEqual(page.input_forms['biases_V'].input.text(), '0, 0.1, 1e-')

    def test_high_field_illustration_preserves_inputs_and_diagnostic_reveals_hidden_form(self):
        page = self.page('high_field_optics'); settings = optical_settings()
        self.assertTrue(page.create_material_button.isVisible())
        page.load_settings(settings); page.study_flow.show_stage(1)
        form = page.input_forms['samples']; APP.processEvents()
        self.assertTrue(form.band_preview.isVisible())
        self.assertIn('not calculated results', form.band_preview.accessibleName())
        self.assertEqual(page.options()['settings'], settings)
        page.resize(800, 760); APP.processEvents()
        form.preview_choice.setCurrentIndex(1); APP.processEvents()
        self.assertFalse(form.panel.isVisible())
        self.assertTrue(form.band_preview.isVisible())
        self.assertTrue(page.open_diagnostic(dict(field='samples.0.field_V_m', object_id='test-state')))
        control = form._fields['field_V_m']
        self.assertTrue(control.isVisible())
        control.setFocus(); control.selectAll(); QTest.keyClicks(control, '1e-')
        draft = copy.deepcopy(page.draft())
        page.restore_draft(draft)
        self.assertTrue(page.open_diagnostic(dict(field='samples.0.field_V_m', object_id='test-state')))
        self.assertEqual(form._fields['field_V_m'].text(), '1e-')
        self.assertEqual(page.width(), 800)


if __name__ == '__main__': unittest.main()
