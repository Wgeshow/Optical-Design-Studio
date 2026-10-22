"""Complete-window paper routing, portable inputs and actual saved-data plots."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QMessageBox

from benchmark_registry import editable_copy, input_fingerprint, list_benchmarks
from data_library import DataLibrary
from qt_app import OpticalStudio
from qt_common import preferences
from qt_core import ProjectStore, desktop_search

APP = QApplication.instance() or QApplication([])
SAVED_HIGH_FIELD = Path(os.environ.get('ODS_HIGH_FIELD_RESULT_FIXTURE',
    r'C:\codes\ods-feature-validation\candidate-20261014-features-r2\frozen-research\high_field_optics'))


class StudyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='study-window-', dir=Path(os.environ.get('TEMP', '.')))
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, S4_LIBRARY_ROOT=str(self.root/'preferences'))
        self.environment.start()
        self.store = ProjectStore(DataLibrary(self.root/'library'), restore=False)
        self.windows = []
        self.window = self.new_window(self.store)

    def new_window(self, store):
        window = OpticalStudio(store)
        self.windows.append(window)
        window.resize(1280, 900)
        window.show()
        APP.processEvents()
        return window

    def tearDown(self):
        for window in self.windows:
            for page in window.findChildren(type(window.photonic_bands_page)):
                page._save_timer.stop()
            window.hide()
            window.deleteLater()
        APP.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.environment.stop()
        self.temp.cleanup()

    def test_all_24_paper_setups_open_with_exact_physical_inputs_and_portable_drafts(self):
        chooser = self.window.research_studies_page
        cases = list_benchmarks()
        self.assertEqual(len(cases), 24)
        for metadata in cases:
            identity = metadata['id']
            with self.subTest(case=identity):
                case = editable_copy(identity)
                self.window._navigate_route(11)
                chooser.show_paper_library()
                chooser.benchmarks.setCurrentIndex(chooser.benchmarks.findData(identity))
                self.assertEqual(chooser.benchmarks.currentData(), identity)
                before_device = copy.deepcopy(self.store.device)
                before_study = self.store.active_study
                with patch.object(self.window, '_confirm_project_replace', return_value=True):
                    chooser.library_page.edit_button.click()
                APP.processEvents()
                if case['kind'] == 'research_simulation':
                    engine = case['options']['engine']
                    page = self.window.photonic_bands_page if engine == 'photonic_bands' else chooser.stack.currentWidget()
                    self.assertEqual(self.window.stack.currentIndex(), 10 if engine == 'photonic_bands' else 11)
                    if engine != 'photonic_bands':
                        self.assertEqual(chooser.selector.currentData(), engine)
                    request = page.options()
                    self.assertEqual(input_fingerprint(case['project'], case['kind'], request),
                        input_fingerprint(case['project'], case['kind'], case['options']))
                    self.assertEqual(self.store.study_project(before_study)['device'], before_device)
                    self.assertEqual(page._benchmark_request['id'], identity)
                    page.flush_draft()
                    state = copy.deepcopy(self.store.search_state['research_workspaces'][page.state_key])
                    restored = ProjectStore(DataLibrary(self.root/('restore-'+identity)), restore=False)
                    restored.load_project(self.store.portable_project(), autosave=False)
                    self.assertEqual(restored.search_state['research_workspaces'][page.state_key], state)
                else:
                    expected = ProjectStore(DataLibrary(self.root/('reference-'+identity)), restore=False)
                    expected.load_project(case['project'], autosave=False)
                    for key in ('materials', 'layers', 'patterns', 'settings', 'device', 'electrical_materials'):
                        self.assertEqual(self.store.project()[key], expected.project()[key], key)
                    normalized_options = desktop_search({case['kind']: case['options']})[case['kind']]
                    self.assertEqual(self.store.search_state[case['kind']], normalized_options)
                    self.assertEqual(self.window.stack.currentIndex(), 2)
                    self.assertEqual(self.window.simulation_engines.currentIndex(), 5 if case['kind'] == 'electrical' else 7)
                    self.assertEqual(self.store.benchmark_request['id'], identity)
                    restored = ProjectStore(DataLibrary(self.root/('restore-'+identity)), restore=False)
                    restored.load_project(self.store.portable_project(), autosave=False)
                    self.assertEqual(restored.benchmark_request, self.store.benchmark_request)
                    self.assertEqual(restored.search_state[case['kind']], normalized_options)

    @unittest.skipUnless((SAVED_HIGH_FIELD/'high_field_optics.npz').is_file(), 'Actual saved compiled high-field fixture is not present')
    def test_actual_high_field_result_opens_physical_wavelength_curves(self):
        self.window._route_setup_action('high_field_optics')
        page = self.window.research_studies_page.stack.currentWidget()
        summary = json.loads((SAVED_HIGH_FIELD/'research_summary.json').read_text(encoding='utf-8'))
        page._owns_run = True
        self.store.run_finished.emit(dict(directory=str(SAVED_HIGH_FIELD), summary=summary, run_kind='research_simulation'))
        APP.processEvents()
        self.assertIs(page.tabs.currentWidget(), page.results)
        self.assertTrue(page.results.isVisible())
        self.assertEqual(page.results.summary['status'], summary['status'])
        viewer = page.results
        count = 0
        with np.load(SAVED_HIGH_FIELD/'high_field_optics.npz', allow_pickle=False) as archive:
            self.assertEqual(viewer.state.count(), len(archive['sample_ids']))
            for row in range(viewer.state.count()):
                viewer.state.setCurrentIndex(row)
                for _, key, _ in viewer.quantities:
                    if key not in archive:
                        continue
                    viewer.quantity.setCurrentIndex(viewer.quantity.findData(key))
                    APP.processEvents()
                    axis = viewer.response_plot.figure.axes[0]
                    self.assertEqual(axis.get_xlabel(), 'Wavelength (nm)')
                    np.testing.assert_array_equal(axis.lines[0].get_xdata(), archive['wavelengths_nm'])
                    np.testing.assert_array_equal(axis.lines[0].get_ydata(), archive[key][row])
                    count += 1
        self.assertGreaterEqual(count, 4)
        if summary.get('kk_quadrature_warning_count'):
            self.assertIn(str(summary['kk_quadrature_warning_count'])+' integration warnings', viewer.response_note.text())
        else:
            self.assertIn('convergence', viewer.response_note.text())

    def test_saved_new_workspace_routes_restore_without_falling_into_legacy_pages(self):
        self.window._route_setup_action('pcsel')
        page = self.window.research_studies_page.stack.currentWidget()
        page.load_pcsel_example()
        page.fields['lattice_nm'].setText('297.125')
        page.flush_draft()
        saved = self.store.portable_project()
        settings = preferences()
        settings.setValue('page', 11)
        settings.sync()
        restored = ProjectStore(DataLibrary(self.root/'restart'), restore=False)
        restored.load_project(saved, autosave=False)
        restarted = self.new_window(restored)
        self.assertEqual(restarted.stack.currentIndex(), 11)
        self.assertEqual(restarted.research_studies_page.selector.currentData(), 'pcsel')
        self.assertEqual(restarted.research_studies_page.stack.currentWidget().options()['settings']['lattice_nm'], 297.125)
        settings.setValue('page', 10)
        settings.sync()
        third = self.new_window(ProjectStore(DataLibrary(self.root/'restart-bands'), restore=False))
        self.assertEqual(third.stack.currentIndex(), 10)
        self.assertIs(third.stack.currentWidget(), third.photonic_bands_page)

    def test_new_studies_preserve_existing_routes_and_fixed_run_dispatch(self):
        self.window._route_setup_action('pcsel')
        research_page = self.window.research_studies_page.stack.currentWidget()
        with patch.object(research_page, 'run') as run:
            self.window.run_button.click()
            run.assert_called_once_with()
        for route, expected in (('optical', self.window.optical_setup), ('electrical', self.window.electrical_page),
                                ('coupled', self.window.coupled_page)):
            with self.subTest(route=route):
                self.window._route_setup_action(route)
                self.assertEqual(self.window.stack.currentIndex(), 2)
                with patch.object(expected, 'run') as run:
                    self.window.run_button.click()
                    run.assert_called_once_with()
        self.window._route_setup_action('photonic_bands')
        with patch.object(self.window.photonic_bands_page, 'run') as run:
            self.window.run_button.click()
            run.assert_called_once_with()
        for route, index, engine in (('tools.sweep', 3, None), ('tools.ai', 8, None),
                                     ('tools.index_shift', 2, 2), ('tools.fields', 2, 3), ('tools.library', 2, 4)):
            self.window._route_setup_action(route)
            self.assertEqual(self.window.navigation.currentRow(), index)
            if engine is not None:
                self.assertEqual(self.window.simulation_engines.currentIndex(), engine)

    def test_result_refinement_preserves_unsaved_geometry_and_incomplete_research_inputs(self):
        from data_library import write_json, read_json
        result_directory = self.root/'saved-result'
        result_directory.mkdir()
        original = copy.deepcopy(self.store.project())
        write_json(result_directory/'project.json', original)
        self.window.results_page.directory = result_directory
        self.window._route_setup_action('pcsel')
        page = self.window.research_studies_page.stack.currentWidget()
        page.fields['lattice_nm'].setText('1e-')
        self.store.device['width_um'] += 1.25
        edited_device = copy.deepcopy(self.store.device)
        with patch.object(self.store, 'load_project', wraps=self.store.load_project) as restore:
            self.store.busy = True
            try:
                with patch('qt_app.QMessageBox.question') as prompt:
                    self.window._rerun_simulation_result()
                    prompt.assert_not_called()
                restore.assert_not_called()
            finally:
                self.store.busy = False
            with patch('qt_app.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel) as prompt:
                self.window._rerun_simulation_result()
                prompt.assert_called_once()
            restore.assert_not_called()
            self.assertEqual(self.store.device, edited_device)
            self.assertEqual(page.fields['lattice_nm'].text(), '1e-')
            with patch('qt_app.QMessageBox.question', return_value=QMessageBox.StandardButton.Save), \
                    patch.object(self.window, 'save_project', return_value=False):
                self.window._rerun_simulation_result()
            restore.assert_not_called()
            self.assertEqual(self.store.device, edited_device)
            self.window._flush_research_drafts()
            draft = copy.deepcopy(self.store.search_state['research_workspaces'][page.state_key])
            saved_path = self.root/'my-edited-device.json'
            with patch('qt_app.QMessageBox.question', return_value=QMessageBox.StandardButton.Save), \
                    patch('qt_app.QFileDialog.getSaveFileName', return_value=(str(saved_path), 'JSON')):
                self.window._rerun_simulation_result()
            restore.assert_called_once_with(result_directory/'project.json')
        saved = read_json(saved_path)
        self.assertEqual(saved['device'], edited_device)
        self.assertEqual(saved['desktop_search']['research_workspaces'][page.state_key], draft)
        self.assertEqual(self.store.device, original['device'])
        self.assertFalse(self.store.busy)


if __name__ == '__main__':
    unittest.main()
