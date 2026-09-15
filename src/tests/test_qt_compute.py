"""Offscreen regression coverage for native computation-page contracts."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pandas as pd
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from data_library import DataLibrary
from model import MAT_COLS, LAYER_COLS, PAT_COLS, MODES
from qt_core import ProjectStore, prepare_job
from qt_compute import SimulationPage, OptimizePage, FieldsPage, SettingsPage, field_figure
from qt_ranges import BoundsEditor, HoleEditor
from peak_optimizer import SEARCH_KEYS
from ml_optimizer import ML_KEYS


APP = QApplication.instance() or QApplication([])


class NativeComputationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ProjectStore(DataLibrary(self.temp.name), restore=False)
        self.store.layers = pd.DataFrame([
            ['AirAbove', 0, 'Air'], ['PCS1', .25, 'GaAs'], ['PCS2', .25, 'GaAs'],
            ['Substrate', .1, 'SiO2'], ['AirBelow', 0, 'Air']], columns=LAYER_COLS)
        self.store.patterns = pd.DataFrame([
            ['circle', 'PCS1', 'Air', 0, 0, .1, 0, 0],
            ['ellipse', 'PCS2', 'Air', 0, 0, .05, .08, 15]], columns=PAT_COLS)
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def widget(self, cls):
        result = cls(self.store)
        self.widgets.append(result)
        return result

    def test_range_selection_is_semantic_and_safe_when_empty(self):
        editor = self.widget(BoundsEditor)
        self.assertFalse(editor.remove.isEnabled())
        editor.load_selected()
        self.assertEqual(editor.minimum.value(), .1)
        editor.parameter.setCurrentIndex(editor.parameter.findData('thickness'))
        editor.target.setCurrentIndex(editor.target.findData('PCS1'))
        editor.minimum.setValue(.2)
        editor.maximum.setValue(.3)
        self.assertTrue(editor.add_range())
        editor.target.setCurrentIndex(editor.target.findData('PCS2'))
        editor.minimum.setValue(.4)
        editor.maximum.setValue(.5)
        self.assertTrue(editor.add_range())
        editor.overview.setCurrentCell(0, 0)
        editor.remove_range()
        self.assertIsNone(editor._selected_key())
        editor.overview.setCurrentCell(0, 0)
        self.assertEqual(editor.target.currentData(), 'PCS2')
        self.assertEqual(editor.minimum.value(), .4)
        self.assertEqual(editor.records()[0]['Target'], 'PCS2')

    def test_material_choices_are_current_and_invalid_ranges_are_atomic(self):
        editor = self.widget(BoundsEditor)
        editor.parameter.setCurrentIndex(editor.parameter.findData('layer_material'))
        editor.target.setCurrentIndex(editor.target.findData('PCS1'))
        for index in range(editor.materials.count()):
            item = editor.materials.item(index)
            if item.text() in ('GaAs', 'SiO2'):
                item.setCheckState(Qt.CheckState.Checked)
        self.assertTrue(editor.add_range())
        self.assertEqual(editor.records()[0]['Choices'], 'GaAs;SiO2')
        before = editor.records()
        with self.assertRaisesRegex(ValueError, 'current layer'):
            editor.set_records([dict(Parameter='thickness', Target='Deleted', Min=.1, Max=.2, Step=.01, Choices='')])
        self.assertEqual(editor.records(), before)

    def test_pattern_ranges_clear_on_structure_change_and_layers_refresh(self):
        editor = self.widget(BoundsEditor)
        editor.parameter.setCurrentIndex(editor.parameter.findData('radius'))
        self.assertEqual(editor.target.count(), 1)
        self.assertTrue(editor.add_range())
        self.store.patterns = self.store.patterns.iloc[::-1].reset_index(drop=True)
        self.store.changed.emit('structure')
        self.assertEqual(editor.records(), [])
        self.assertEqual(editor.target.currentData(), '2')
        self.assertIn('removed', editor.status.text())

    def test_holes_follow_structure_but_keep_manual_limits_and_removals(self):
        editor = self.widget(HoleEditor)
        self.assertEqual(len(editor.records()), 2)
        editor.overview.setCurrentCell(0, 0)
        editor.min_x.setValue(.07)
        editor.max_x.setValue(.12)
        self.assertTrue(editor.add_range())
        self.store.patterns.loc[0, 'SizeX_um'] = .15
        self.store.patterns.loc[1, 'SizeX_um'] = .09
        self.store.changed.emit('structure')
        self.assertEqual(editor.records()[0]['MinX_um'], .07)
        self.assertEqual(editor.records()[0]['MaxX_um'], .12)
        self.assertEqual(editor.records()[1]['MinX_um'], .09)
        editor.overview.setCurrentCell(1, 0)
        editor.remove_range()
        self.store.changed.emit('settings')
        self.assertEqual([row['Layer'] for row in editor.records()], ['PCS1'])

    def test_simulation_options_edit_shared_settings_and_show_results(self):
        page = self.widget(SimulationPage)
        page.controls['wl_start_nm'].setValue(1500)
        page.controls['wl_stop_nm'].setValue(1502)
        page.controls['wl_step_nm'].setValue(1)
        with patch.object(self.store, 'start_run') as start:
            page.run()
        start.assert_called_once_with('simulation', {})
        self.assertEqual(self.store.settings['wl_start_nm'], 1500)
        path = Path(self.temp.name) / 'results.csv'
        pd.DataFrame([[1500, 0, .1, .2, .7], [1501, 0, .001, .001, .998]],
                     columns=['wavelength_nm', 'angle_deg', 'R', 'T', 'A']).to_csv(path, index=False)
        self.store.run_finished.emit(dict(run_kind='simulation', output=str(path), info={'gpu_gemm_calls': 8}))
        self.assertEqual(page.results.rowCount(), 2)
        self.assertIn('99.8%', page.metrics.text())
        self.assertIn('GPU matrix products: 8', page.metrics.text())
        self.assertEqual(len(page.plot.figure.axes[0].lines), 3)

    def test_target_contract_has_tolerance_hole_shapes_and_field_learning(self):
        page = self.widget(OptimizePage)
        options = page.target_options()
        self.assertEqual(options['tolerance_nm'], 5)
        self.assertTrue(options['use_fields'])
        self.assertTrue(options['track_resonance'])
        self.assertTrue(options['reuse'])
        self.assertEqual(options['holes'][1]['Shape'], 'ellipse')
        with patch.object(self.store, 'start_run') as start:
            page.run_target()
        self.assertEqual(start.call_args.args[0], 'target')
        self.assertEqual(start.call_args.args[1], options)
        self.store.layers.loc[2, 'Name'] = 'Renamed PCS'
        self.store.patterns.loc[1, 'Layer'] = 'Renamed PCS'
        self.store.changed.emit('structure')
        self.assertNotEqual(page.holes.layer.findData('Renamed PCS'), -1)
        self.assertEqual(page.holes.layer.findData('PCS2'), -1)

    def test_general_search_exposes_all_options_and_applies_selected_result(self):
        page = self.widget(OptimizePage)
        self.assertEqual(set(page.peak_options()['search_options']), set(SEARCH_KEYS + ML_KEYS))
        folder = Path(self.temp.name)
        pd.DataFrame([dict(design_id=7, status='evaluated', absorption=.9995, wavelength_nm=1550)]).to_csv(folder / 'design_results.csv', index=False)
        pd.DataFrame([dict(wavelength_nm=1550, A=.9995)]).to_csv(folder / 'best_spectrum.csv', index=False)
        self.store.run_finished.emit(dict(run_kind='peaks', directory=str(folder), summary={'best_absorption': .9995, 'evaluated': 1}))
        self.assertEqual(page.design.currentData(), 7)
        self.assertTrue(page.apply_peak.isEnabled())
        with patch.object(self.store, 'apply_design') as apply:
            page.use_peak()
        apply.assert_called_once_with(folder, design_id=7)

    def test_target_recommendation_requires_saved_verified_record(self):
        page = self.widget(OptimizePage)
        folder = Path(self.temp.name)
        self.store.run_finished.emit(dict(run_kind='target', directory=str(folder), summary={'maximum_verified_Q': None}))
        self.assertFalse(page.apply_target.isEnabled())
        (folder / 'recommended_design.json').write_text('{}', encoding='utf-8')
        self.store.run_finished.emit(dict(run_kind='target', directory=str(folder), summary={'maximum_verified_Q': 3210.3}))
        self.assertTrue(page.apply_target.isEnabled())
        self.assertIn('3210.3', page.target_summary.text())
        with patch.object(self.store, 'apply_design') as apply:
            page.use_target()
        apply.assert_called_once_with(folder, recommended=True)

    def test_search_edits_are_saved_before_run_and_settings_cannot_restore_old_bounds(self):
        page = self.widget(OptimizePage)
        page.target_controls['target_nm'].setValue(1600)
        page.target_controls['target_nm'].editingFinished.emit()
        self.assertEqual(self.store.search_state['target']['target_nm'], 1600)
        page.holes.overview.setCurrentCell(0, 0)
        page.holes.min_x.setValue(.06)
        page.holes.max_x.setValue(.14)
        page.holes.add_range()
        self.assertEqual(self.store.project()['desktop_search']['target']['holes'][0]['MinX_um'], .06)
        self.store.update_settings({'NumG': 64})
        self.assertEqual(page.holes.records()[0]['MinX_um'], .06)
        self.assertEqual(page.target_controls['target_nm'].value(), 1600)
        saved = json.loads(self.store.session_path.read_text(encoding='utf-8'))
        self.assertEqual(saved['desktop_search']['target']['holes'][0]['MaxX_um'], .14)

    def test_loading_another_project_clears_old_search_limits_and_keeps_imported_ones(self):
        page = self.widget(OptimizePage)
        page.bounds.populate_current()
        self.assertGreater(len(page.bounds.records()), 0)
        project = self.store.project()
        project['desktop_search'] = {}
        self.store.load_project(project)
        self.assertEqual(page.bounds.records(), [])
        self.assertEqual(page.target_controls['target_nm'].value(), 1550)
        project['desktop_search'] = dict(target=dict(page.target_options(), target_nm=1620))
        project['patterns'][0]['SizeX_um'] = .13
        self.store.load_project(project)
        self.assertEqual(page.target_controls['target_nm'].value(), 1620)
        self.assertEqual(self.store.search_state['target']['target_nm'], 1620)

    def test_automatic_hole_sync_survives_saved_search_roundtrip(self):
        page = self.widget(OptimizePage)
        page.persist_setup('target')
        project = self.store.project()
        self.store.load_project(project)
        self.store.patterns.loc[0, 'SizeX_um'] = .16
        self.store.changed.emit('structure')
        self.assertEqual(page.holes.records()[0]['MinX_um'], .16)
        self.assertEqual(self.store.search_state['target']['holes'][0]['MinX_um'], .16)

    def test_fields_share_layer_selection_and_build_component_maps(self):
        page = self.widget(FieldsPage)
        page.layer.setCurrentIndex(page.layer.findData('PCS2'))
        page.wavelength.setValue(1540)
        page.grid.setValue(9)
        with patch.object(self.store, 'start_run') as start:
            page.run()
        start.assert_called_once_with('fields', dict(wavelength_nm=1540., layer='PCS2', grid=9))
        data = []
        for plane in ('xy', 'xz'):
            for x in (-.1, .1):
                for y in (-.1, .1):
                    data.append(dict(plane=plane, layer='PCS1', x_um=x, y_um=y, z_um=y,
                                     Ex_real=1., Ex_imag=1., Ey_real=0., Ey_imag=0., Ez_real=0., Ez_imag=0., E2=2.))
        folder = Path(self.temp.name) / 'fields'
        folder.mkdir()
        pd.DataFrame(data).to_csv(folder / 'electric_fields.csv', index=False)
        self.store.run_finished.emit(dict(run_kind='fields', directory=self.temp.name, summary={}))
        self.assertEqual(len(page.plot.figure.axes), 4)
        page.component.setCurrentIndex(page.component.findData('Ex'))
        page.logarithmic.setChecked(True)
        self.assertEqual(len(page.plot.figure.axes), 4)
        self.store.layers = self.store.layers[self.store.layers.Name != 'PCS2'].reset_index(drop=True)
        self.store.changed.emit('structure')
        self.assertEqual(page.layer.currentData(), '')

    def test_settings_capture_accuracy_and_gpu_changes_before_shared_refresh(self):
        page = self.widget(SettingsPage)
        page.basis.setValue(64)
        page.controls['threads'].setValue(2)
        page.save_settings()
        self.assertEqual(self.store.settings['NumG'], 64)
        self.assertEqual(self.store.performance['threads'], 2)
        page.small_matrices()
        self.assertEqual(self.store.performance['gpu_min_n'], 1)
        self.assertEqual(self.store.performance['mode'], MODES[2])
        with patch.object(self.store, 'start_run') as start:
            page.run()
        start.assert_called_once_with('diagnostic', {})
        self.store.run_finished.emit(dict(run_kind='diagnostic', info={'gpu_gemm_calls': 15, 'gpu_failures': 0}))
        self.assertIn('GPU connection verified', page.status.text())

    def test_controls_disable_runs_when_backend_busy_and_handle_errors_inline(self):
        page = self.widget(SimulationPage)
        self.store.busy_changed.emit(True)
        self.assertFalse(page.starts[0].isEnabled())
        self.assertTrue(page.stops[0].isEnabled())
        with patch.object(self.store, 'start_run', side_effect=ValueError('Invalid sweep')):
            page.run()
        self.assertIn('Invalid sweep', page.status.text())
        self.assertEqual(page.progress_bar.maximum(), 100)
        self.assertTrue(page.progress_bar.isHidden())

    def test_optimizer_run_actions_are_outside_the_scrolling_inputs(self):
        from PyQt6.QtWidgets import QScrollArea
        page = self.widget(OptimizePage)
        for button in page.starts:
            parent = button.parentWidget()
            while parent is not None and parent is not page:
                self.assertNotIsInstance(parent, QScrollArea)
                parent = parent.parentWidget()
        self.assertTrue(page.progress_bar.isHidden())

    def test_failed_settings_save_never_starts_a_run_with_stale_values(self):
        page = self.widget(SimulationPage)
        with patch.object(self.store, 'update_settings', side_effect=PermissionError('Read-only library')):
            with patch.object(self.store, 'start_run') as start:
                page.run()
                start.assert_not_called()
        self.assertIn('Read-only library', page.status.text())
        settings = self.widget(SettingsPage)
        with patch.object(self.store, 'update_performance', side_effect=ValueError('Too many threads')):
            with patch.object(self.store, 'start_run') as start:
                settings.run()
                start.assert_not_called()
        self.assertIn('Too many threads', settings.status.text())
        with patch.object(self.store, 'cancel', side_effect=PermissionError('Cannot create cancel flag')):
            page.stops[0].click()
            page._cancel()
        self.assertIn('Cannot create cancel flag', page.status.text())


if __name__ == '__main__':
    unittest.main()
