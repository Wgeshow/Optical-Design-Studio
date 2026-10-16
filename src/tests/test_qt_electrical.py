"""Electrical-page persistence, dispatch and saved-result presentation contracts."""
import json
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pandas as pd
from PyQt6.QtWidgets import QApplication

from data_library import DataLibrary
from model import LAYER_COLS
from qt_core import ProjectStore
from qt_electrical import (DEVICE_LAYERS, ElectricalPage, electrical_profile_figure,
    electrical_spectrum_figure, parse_biases)

APP = QApplication.instance() or QApplication([])


class ElectricalPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods_qt_electrical_')
        self.store = ProjectStore(DataLibrary(self.temp.name), restore=False)
        self.page = None

    def tearDown(self):
        if self.page is not None:
            self.page.close()
            self.page.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def page_widget(self,workflow='electrical'):
        self.page = ElectricalPage(self.store,workflow=workflow)
        return self.page

    def test_navigation_does_not_mutate_structure_or_saved_settings(self):
        project = self.store.portable_project()
        page = self.page_widget()
        self.assertEqual(self.store.portable_project(), project)
        self.assertEqual(page.options()['biases_V'], [0., -2.])
        self.assertEqual(page.options()['model'], 'custom_device')
        self.assertEqual(next(row for row in page.options()['material_library'] if row['id']=='ito')['properties']['bulk_electron_cm3'], 8e20)
        self.assertFalse(page.options()['optical_enabled'])
        self.assertEqual(page.options()['reference_nm'], self.store.settings['fixed_wl_nm'])
        self.assertEqual(page.mapping.rowCount(), 6)
        self.assertFalse(page.scope_note.isHidden())
        self.assertIn('Poisson', page.scope_note.text())

    def test_edits_roundtrip_and_run_dispatches_an_electrical_job(self):
        page = self.page_widget()
        page.model.setCurrentIndex(page.model.findData('contacts_only_sheet'))
        page.biases.setText('0, -1, -2')
        page.biases.editingFinished.emit()
        self.assertEqual(self.store.search_state['electrical']['biases_V'], [0., -1., -2.])
        self.assertFalse(page.controls['ito_density_cm3'].isEnabled())
        self.assertTrue(page.controls['sheet_resistance_ohm_square'].isEnabled())
        with patch.object(self.store, 'start_run') as start:
            page.run()
        start.assert_called_once_with('electrical', page.options())
        self.store.load_project(self.store.portable_project())
        self.assertEqual(page.model.currentData(), 'contacts_only_sheet')
        self.assertEqual(page.biases.text(), '0, -1, -2')
        self.assertNotIn('measured_current', page.options())

    def test_electrical_and_coupled_workflows_keep_independent_studies_and_results(self):
        electrical=self.page_widget()
        coupled=ElectricalPage(self.store,workflow='coupled')
        try:
            electrical.biases.setText('0, -0.2');electrical.changed()
            coupled.biases.setText('0, -0.1, -0.2');coupled.changed()
            self.assertFalse(electrical.options()['optical_enabled'])
            self.assertTrue(coupled.options()['optical_enabled'])
            self.assertEqual(coupled.options()['optical_reference'],'undoped')
            self.assertEqual(self.store.search_state['electrical']['biases_V'],[0.,-.2])
            self.assertEqual(self.store.search_state['coupled']['biases_V'],[0.,-.1,-.2])
            with patch.object(electrical,'show_result') as electric_result,patch.object(coupled,'show_result') as coupled_result:
                self.store.run_finished.emit({'run_kind':'coupled','directory':self.temp.name})
            electric_result.assert_not_called();coupled_result.assert_called_once()
        finally:
            coupled.close();coupled.deleteLater();APP.processEvents()

    def test_bad_bias_or_density_stops_before_worker_and_keeps_previous_draft(self):
        page = self.page_widget()
        page.changed()
        previous = self.store.search_state['electrical'].copy()
        page.biases.setText('0, nan')
        with patch.object(self.store, 'start_run') as start:
            page.run()
        start.assert_not_called()
        self.assertIn('finite', page.status.text())
        self.assertEqual(self.store.search_state['electrical'], previous)
        page.biases.setText('0, -2')
        page.model.setCurrentIndex(page.model.findData('explicit_ito'))
        page.controls['ito_density_cm3'].setText('5 x 10^20')
        with patch.object(self.store, 'start_run') as start:
            page.run()
        start.assert_not_called()
        self.assertIn('density', page.status.text())

    def test_layer_mapping_tracks_material_and_does_not_reassign_deleted_layer(self):
        self.store.layers = pd.DataFrame([
            ['AirAbove', 0., 'Air'], ['p+ GaAs', .05, 'GaAs'],
            ['p GaAs', .15, 'GaAs'], ['Al0.5Ga0.5As', .02, 'SiO2'],
            ['n GaAs', .15, 'GaAs'], ['n+ GaAs', .05, 'GaAs'],
            ['ITO', .04, 'SiO2'], ['AirBelow', 0., 'Air']], columns=LAYER_COLS)
        page = self.page_widget('coupled')
        page.model.setCurrentIndex(page.model.findData('explicit_ito'))
        mapping = page.options()['optical_mapping']
        self.assertEqual(set(mapping), set(DEVICE_LAYERS))
        self.assertEqual(mapping['Al0.5Ga0.5As']['material'], 'SiO2')
        self.store.layers.loc[1, 'Name'] = 'Renamed'
        self.store.changed.emit('structure')
        self.assertEqual(page.options()['optical_mapping']['p+ GaAs']['layer'], 'p+ GaAs')
        self.assertIn('unavailable', page.mapping.cellWidget(0, 1).currentText())

    def test_device_preset_requires_explicit_button_action(self):
        with patch.object(self.store, 'load_electrical_preset', create=True) as load:
            page = self.page_widget()
            page.model.setCurrentIndex(page.model.findData('explicit_ito'))
            load.assert_not_called()
            page.preset_button.click()
        load.assert_called_once_with(model='explicit_ito', ito_thickness_nm=40., ito_density_cm3=8e20)

    def test_pc_lattice_button_uses_real_even_array_and_preserves_optical_toggle(self):
        from device_model import default_device
        from pc_array import apply_pc_array
        device=default_device(self.store.electrical_materials)
        device.update(width_um=150.,depth_um=150.)
        spec=dict(id='even_pc',name='Even 222-cell PC',layer_id=device['layers'][0]['id'],
            width_um=100.,depth_um=100.,cx_um=0.,cy_um=0.,
            cell_width_um=.45,cell_depth_um=.45,radius_um=.09,enabled=True)
        device=apply_pc_array(device,spec,material_library=self.store.electrical_materials)
        self.assertEqual(len(device['shapes']),222*222)
        self.store.set_device(device)
        page=self.page_widget('coupled')
        before=copy.deepcopy(self.store.device)
        extent=(self.store.settings['ax_um'],self.store.settings['ay_um'])
        self.assertFalse(page.optical_cell_enabled.isChecked())
        page.use_pc_cell_button.click()
        cell=self.store.settings['optical_unit_cell']
        self.assertFalse(cell['enabled'])
        self.assertEqual((cell['width_um'],cell['depth_um']),(.45,.45))
        self.assertAlmostEqual(cell['cx_um'],-.225,places=10)
        self.assertAlmostEqual(cell['cy_um'],-.225,places=10)
        self.assertTrue(any(abs(row['cx_um']-cell['cx_um'])<1e-10 and abs(row['cy_um']-cell['cy_um'])<1e-10 for row in self.store.device['shapes']))
        self.assertEqual(self.store.device,before)
        self.assertEqual((self.store.settings['ax_um'],self.store.settings['ay_um']),extent)
        page.optical_cell_enabled.setChecked(True)
        page.use_pc_cell_button.click()
        self.assertTrue(self.store.settings['optical_unit_cell']['enabled'])
        self.assertEqual(self.store.device,before)
        self.assertEqual((self.store.settings['ax_um'],self.store.settings['ay_um']),extent)

    def test_moved_saved_run_loads_profiles_and_filters_plot_and_tables(self):
        page = self.page_widget()
        directory = Path(self.temp.name) / 'moved_run'
        electrical = directory / 'electrical'
        electrical.mkdir(parents=True)
        results = []
        for bias in (0, -2):
            filename = f'profile_{bias}V.csv'
            pd.DataFrame({'z_nm': [0., 420.], 'electrons_cm3': [1e10, 1e19],
                'holes_cm3': [1e20, 1e8], 'Ez_V_m': [1e6, -2e6]}).to_csv(electrical / filename, index=False)
            results.append({'bias_V': bias, 'profile_csv': str(Path(self.temp.name) / 'old_run' / 'electrical' / filename), 'checks': {}})
        (directory / 'electrical_summary.json').write_text(json.dumps({'model': 'explicit_ito', 'results': results}), encoding='utf-8')
        pd.DataFrame([{'bias_V': bias, 'wavelength_nm': wave, 'z_start_nm': depth,
            'n': 3.4 + bias*.01, 'k': .001, 'n_plus': 3.4, 'k_plus': .001,
            'n_minus': 3.4, 'k_minus': .001} for bias in (0, -2) for wave in (1150., 1151.) for depth in (0., 50.)]).to_csv(directory / 'electrical_index_changes.csv', index=False)
        pd.DataFrame([{'bias_V': bias, 'wavelength_nm': wave, 'R': .2, 'T': .7, 'A': .1} for bias in (0, -2) for wave in (1150., 1151.)]).to_csv(directory / 'electrical_optical_spectra.csv', index=False)
        pd.DataFrame([{'bias_V': 0., 'feature_nm': 1150., 'shift_nm': 0.},
            {'bias_V': -2., 'feature_nm': 1150.1, 'shift_nm': .1}]).to_csv(directory / 'electrical_features.csv', index=False)
        (directory / 'search_summary.json').write_text(json.dumps({'baseline_nm': 1150., 'max_abs_shift_nm': .1}), encoding='utf-8')
        self.store.run_finished.emit({'run_kind': 'electrical', 'directory': str(directory)})
        self.assertEqual(len(page.saved_profiles), 4)
        self.assertEqual(page.profile_table.rowCount(), 4)
        self.assertEqual(len(page.index_plot.figure.axes[0].lines), 6)
        self.assertEqual(len(page.spectrum_plot.figure.axes[0].lines), 6)
        self.assertEqual(page.feature_table.rowCount(), 2)
        self.assertIn('1150 nm', page.tracking_label.text())
        page.result_bias.setCurrentIndex(page.result_bias.findData(-2))
        self.assertEqual(page.profile_table.rowCount(), 2)
        self.assertEqual(page.spectrum_table.rowCount(), 2)
        self.assertEqual(len(page.index_plot.figure.axes[0].lines), 3)
        self.assertEqual(page.feature_table.rowCount(), 1)
        page.profile_view.setCurrentIndex(1)
        self.assertEqual(list(page.profile_plot.figure.axes[0].lines[0].get_ydata()), [1., -2.])

    def test_measured_current_import_is_atomic_and_clear_restores_default(self):
        page = self.page_widget()
        page.model.setCurrentIndex(page.model.findData('contacts_only_sheet'))
        filename = Path(self.temp.name) / 'measured.csv'
        pd.DataFrame({'bias_V': [-2., 0.], 'current_A': [-1e-6, 0.]}).to_csv(filename, index=False)
        with patch('qt_electrical.QFileDialog.getOpenFileName', return_value=(str(filename), '')):
            page.import_current()
        self.assertEqual(len(page.options()['measured_current']), 2)
        self.assertEqual(len(self.store.search_state['electrical']['measured_current']), 2)
        before = list(page.measured_current)
        pd.DataFrame({'bias_V': [0.], 'current_A': [float('nan')]}).to_csv(filename, index=False)
        with patch('qt_electrical.QFileDialog.getOpenFileName', return_value=(str(filename), '')):
            page.import_current()
        self.assertEqual(page.measured_current, before)
        page.clear_current()
        self.assertNotIn('measured_current', page.options())

    def test_damaged_saved_run_reports_missing_profile(self):
        page = self.page_widget()
        directory = Path(self.temp.name) / 'damaged_run'
        directory.mkdir()
        (directory / 'electrical_summary.json').write_text(json.dumps({'results': [
            {'bias_V': 0., 'profile_csv': 'missing.csv'}]}), encoding='utf-8')
        self.store.run_finished.emit({'run_kind': 'electrical', 'directory': str(directory)})
        self.assertIn('Missing saved electrical profile', page.status.text())
        self.assertTrue(page.saved_profiles.empty)

    def test_figures_keep_solver_values_and_percent_axis(self):
        frame = pd.DataFrame({'bias_V': [0, 0], 'z_nm': [0., 420.], 'electrons_cm3': [0., 1e19], 'holes_cm3': [1e20, 0.]})
        before = frame.copy(deep=True)
        figure = electrical_profile_figure(frame)
        self.assertEqual(figure.axes[0].get_yscale(), 'log')
        pd.testing.assert_frame_equal(frame, before)
        spectra = pd.DataFrame({'bias_V': [0, 0], 'wavelength_nm': [1150., 1151.], 'R': [.1, .2], 'T': [.8, .7], 'A': [.1, .1]})
        axis = electrical_spectrum_figure(spectra).axes[0]
        self.assertEqual(axis.get_ylim(), (0., 1.))
        self.assertEqual(axis.yaxis.get_major_formatter()(.5), '50%')
        self.assertEqual(list(axis.lines[0].get_ydata()), [.1, .2])

    def test_bias_parser_rejects_nonfinite_duplicates_and_malformed_text(self):
        self.assertEqual(parse_biases('0; -2'), [0., -2.])
        for value in ('', '0, 0', '0, inf', '0, bad'):
            with self.assertRaises(ValueError):
                parse_biases(value)


if __name__ == '__main__':
    unittest.main()
