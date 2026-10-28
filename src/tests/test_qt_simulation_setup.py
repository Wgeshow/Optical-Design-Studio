"""User-facing native setup edits, shared configuration and dispatch contracts."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest, QSignalSpy
from PyQt6.QtWidgets import QApplication, QLineEdit, QComboBox, QDialog, QDialogButtonBox, QPlainTextEdit, QListWidget, QTableWidget, QPushButton

from data_library import DataLibrary
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace, _ObjectDialog
from simulation_setup_state import SimulationSetupState

APP=QApplication.instance() or QApplication([])


class SimulationSetupWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ods_native_setup_',dir=Path(__file__).resolve().parents[3])
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.state=SimulationSetupState(self.store)
        self.page=SimulationSetupWorkspace(state=self.state)
        self.page.resize(1586,940)
        self.page.show()
        APP.processEvents()

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def editor(self,key):
        editors=self.page.widgets_by_key[key]
        return next((item for item in editors if item.isVisible()),editors[0])

    def enter(self,key,value):
        editor=self.editor(key)
        self.assertIsInstance(editor,QLineEdit)
        editor.setFocus()
        editor.selectAll()
        QTest.keyClicks(editor,str(value))
        QTest.keyClick(editor,Qt.Key.Key_Tab)
        APP.processEvents()
        return editor

    def test_fine_mesh_setup_fields_accept_counts_and_show_memory_plan(self):
        self.page.set_mode('electrical');self.page.select_section('electrical.mesh')
        with patch('custom_electrical_solver.build_mesh',side_effect=AssertionError('Typing must not allocate a mesh')):
            self.enter('device.mesh.max_nodes',0)
            self.enter('device.mesh.nx',320)
            self.enter('device.mesh.ny',320)
            self.enter('device.mesh.nz_per_layer',12)
        self.assertEqual(self.store.device['mesh']['nx'],320)
        self.assertEqual(self.store.device['mesh']['ny'],320)
        self.assertEqual(self.store.device['mesh']['max_nodes'],0)
        self.assertIn('planning estimate',self.editor('ui.electrical.mesh_peak_memory').text())
        self.assertIn('/ bias',self.editor('ui.electrical.mesh_volume_memory').text())
        self.assertEqual(self.editor('ui.electrical.mesh_linear_solver').text(),'Jacobi-scaled CG')
        self.assertIn('Automatic',self.editor('ui.electrical.mesh_resource_budget').text())

    def test_all_twenty_sections_are_native_and_navigation_keeps_project(self):
        before=self.store.portable_project()
        expected={'optical':7,'electrical':7,'coupled':6}
        self.assertEqual(len(self.page.pages),20)
        for mode,count in expected.items():
            self.page.set_mode(mode)
            self.assertEqual(self.page.navigation.count(),count)
            for index in range(count):
                self.page.navigation.setCurrentRow(index)
                APP.processEvents()
                self.assertEqual(self.page.current_mode,mode)
                self.assertIsNotNone(self.page.stack.currentWidget())
        self.assertEqual(before,self.store.portable_project())

    def test_cell_dimensions_do_not_resize_finite_device(self):
        self.page.select_section('optical.domain')
        self.state.set('settings.optical_unit_cell.enabled',True)
        width=self.store.device['width_um']
        depth=self.store.device['depth_um']
        self.enter('settings.optical_unit_cell.width_um','.55')
        self.enter('settings.optical_unit_cell.depth_um','.65')
        self.assertAlmostEqual(self.store.settings['optical_unit_cell']['width_um'],.55)
        self.assertAlmostEqual(self.store.settings['optical_unit_cell']['depth_um'],.65)
        self.assertEqual((self.store.device['width_um'],self.store.device['depth_um']),(width,depth))

    def test_normal_incidence_button_updates_source_instead_of_opening_settings(self):
        self.state.set('settings.theta_deg',23.)
        self.state.set('settings.phi_deg',45.)
        routes=QSignalSpy(self.page.routeRequested)
        self.page.perform_action(dict(id='normal',target='settings.theta_deg'))
        self.assertEqual(self.store.settings['theta_deg'],0.)
        self.assertEqual(self.store.settings['phi_deg'],0.)
        self.assertEqual(len(routes),0)

    def test_invalid_number_survives_tab_and_mode_change_without_mutation(self):
        self.page.select_section('optical.accuracy')
        previous=self.store.settings['NumG']
        self.enter('settings.NumG','not a number')
        self.assertEqual(self.store.settings['NumG'],previous)
        self.assertIn('settings.NumG',self.page.draft_errors)
        self.page.set_mode('electrical')
        self.page.set_mode('optical')
        self.page.select_section('optical.accuracy')
        self.assertEqual(self.editor('settings.NumG').text(),'not a number')
        with patch.object(self.state,'validate',return_value=[]):
            self.assertFalse(self.page.validate_current())
        self.enter('settings.NumG','96')
        self.assertEqual(self.store.settings['NumG'],96)
        self.assertNotIn('settings.NumG',self.page.draft_errors)

    def test_other_solver_invalid_draft_does_not_block_optical_only(self):
        self.page.set_mode('electrical')
        self.page.select_section('electrical.mesh')
        self.enter('device.mesh.nx','bad')
        self.page.set_mode('optical')
        with patch.object(self.state,'validate',return_value=[]):
            self.assertTrue(self.page.validate_current())
        self.page.set_mode('coupled')
        with patch.object(self.state,'validate',return_value=[]):
            self.assertFalse(self.page.validate_current())

    def test_study_options_reveal_correct_sampling_controls(self):
        self.page.select_section('optical.sweep')
        editor=self.editor('ui.optical.study_type')
        editor.setCurrentIndex(editor.findData('angle_sweep'))
        APP.processEvents()
        self.assertTrue(self.editor('settings.angle_start').isVisible())
        self.assertFalse(any(item.isVisible() for item in self.page.widgets_by_key['settings.wl_start_nm']))
        editor.setCurrentIndex(editor.findData('single'))
        APP.processEvents()
        self.assertTrue(self.editor('ui.optical.single.wavelength_nm').isVisible())
        self.assertFalse(any(item.isVisible() for item in self.page.widgets_by_key['settings.angle_start']))

    def test_coupled_proxy_edits_shared_optical_state_and_keeps_run_mode(self):
        self.page.set_mode('coupled')
        self.page.select_section('coupled.optical-setup/optical.accuracy')
        self.enter('settings.NumG','72')
        self.assertEqual(self.store.settings['NumG'],72)
        self.assertEqual(self.page.current_mode,'coupled')
        spy=QSignalSpy(self.page.runRequested)
        with patch.object(self.state,'validate',return_value=[]):
            self.page.run()
        self.assertEqual(list(spy),[['coupled']])
        self.page.select_section('coupled.transfer')
        self.assertFalse(self.page.nested_tabs.isVisible())
        self.page.set_mode('optical')
        self.page.select_section('optical.accuracy')
        self.assertEqual(self.editor('settings.NumG').text(),'72')

    def test_run_submits_current_range_without_a_separate_preview_click(self):
        self.page.set_mode('electrical')
        self.page.select_section('electrical.study')
        self.state.set('ui.electrical.sweep_mode','range')
        self.enter('ui.electrical.bias_start_V','-.1')
        self.enter('ui.electrical.bias_stop_V','.1')
        self.enter('ui.electrical.bias_step_V','.1')
        with patch.object(self.state,'validate',return_value=[]):self.page.run()
        self.assertEqual(self.state.get('search.electrical.biases_V'),[0.,-.1,.1])

    def test_dense_count_controls_submit_exact_schedule_and_bounded_readonly_tables(self):
        self.page.set_mode('electrical')
        self.page.select_section('electrical.study')
        self.state.set('search.electrical.charge_model', 'dielectric')
        self.state.set('ui.electrical.sweep_mode', 'range')
        sampling = self.editor('ui.electrical.range_sampling')
        sampling.setCurrentIndex(sampling.findData('count'))
        APP.processEvents()
        self.assertTrue(self.editor('ui.electrical.bias_point_count').isVisible())
        self.assertFalse(any(item.isVisible() for item in self.page.widgets_by_key['ui.electrical.bias_step_V']))
        self.enter('ui.electrical.bias_start_V', 0)
        self.enter('ui.electrical.bias_stop_V', 500)
        self.enter('ui.electrical.bias_point_count', 5001)
        self.assertIn('5,001 range points', self.editor('ui.electrical.range_summary').text())
        with patch.object(self.state, 'validate', return_value=[]): self.page.run()
        values = self.state.get('search.electrical.biases_V')
        self.assertEqual((len(values), values[1], values[-1]), (5001, .1, 500.))
        for table in [table for tables in self.page.tables_by_key.values() for table in tables]:
            if table.key in ('search.electrical.biases_V', 'ui.electrical.voltage_schedule'):
                self.assertEqual(table.rowCount(), 200)
                self.assertEqual(table.total_rows, 5001)
                self.assertIn('5,001', table.toolTip())
                self.assertFalse(table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertIn('5,001', self.page.summary.text())
        self.page.select_section('electrical.mesh')
        self.assertIn('5,001 resolved states', self.editor('ui.electrical.mesh_sweep_storage').text())
        self.assertIn('uncompressed planning estimate', self.editor('ui.electrical.mesh_sweep_storage').text())

    def test_invalid_dense_point_count_survives_navigation_and_blocks_run(self):
        self.page.set_mode('electrical')
        self.page.select_section('electrical.study')
        self.state.set('ui.electrical.sweep_mode', 'range')
        self.state.set('ui.electrical.range_sampling', 'count')
        previous = self.state.get('search.electrical.biases_V')
        self.enter('ui.electrical.bias_point_count', '1.5')
        self.assertIn('ui.electrical.bias_point_count', self.page.draft_errors)
        self.page.select_section('electrical.mesh')
        self.page.select_section('electrical.study')
        self.assertEqual(self.editor('ui.electrical.bias_point_count').text(), '1.5')
        with patch.object(self.state, 'validate', return_value=[]):
            self.assertFalse(self.page.validate_current())
        self.assertEqual(self.state.get('search.electrical.biases_V'), previous)

    def test_iv_cv_controls_are_shared_with_coupled(self):
        self.page.set_mode('electrical')
        self.page.select_section('electrical.outputs')
        iv=self.editor('search.electrical.terminal_studies.iv_enabled')
        cv=self.editor('search.electrical.terminal_studies.cv_enabled')
        iv.setChecked(True)
        cv.setChecked(True)
        self.assertTrue(self.state.job_options('electrical')['terminal_studies']['iv_enabled'])
        self.assertTrue(self.state.job_options('electrical')['terminal_studies']['cv_enabled'])
        self.page.set_mode('coupled')
        self.page.select_section('coupled.outputs')
        self.assertTrue(self.editor('search.electrical.terminal_studies.iv_enabled').isChecked())
        self.assertTrue(self.editor('search.electrical.terminal_studies.cv_enabled').isChecked())

    def test_table_doping_edits_use_stable_layer_ids(self):
        self.page.set_mode('electrical')
        self.page.select_section('electrical.materials')
        table=self.page.tables_by_key['device.layers'][0]
        ident=self.store.device['layers'][0]['id']
        table.item(0,4).setText('2.5e17')
        APP.processEvents()
        layer=next(row for row in self.store.device['layers'] if row['id']==ident)
        self.assertEqual(layer['donor_cm3'],2.5e17)

    def test_contact_dialog_cancel_is_transactional_and_apply_updates_preview(self):
        before=copy.deepcopy(self.store.device)
        original=before['contacts'][0] if before['contacts'] else None
        dialog=_ObjectDialog(self.page,'contacts',original)
        dialog.controls['name'].setText('Cancelled name')
        dialog.reject()
        self.assertEqual(self.store.device,before)
        dialog=_ObjectDialog(self.page,'contacts',original)
        ident=dialog.original['id']
        dialog.controls['name'].setText('Edited N contact')
        dialog.controls['voltage_V'].setText('-.025')
        dialog.apply()
        self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
        obj=next(row for row in self.store.device['contacts'] if row['id']==ident)
        self.assertEqual(obj['name'],'Edited N contact')
        self.assertEqual(obj['voltage_V'],-.025)
        self.assertEqual(self.page.top_preview.device,self.store.device)

    def test_manual_bias_list_accepts_newlines_and_includes_reference(self):
        self.page.set_mode('electrical')
        self.page.select_section('electrical.study')
        self.page.drafts['ui.electrical.bias_list_text']='-.2\n-.1\n0'
        self.page.perform_action(dict(id='manual',target='electrical.parse_biases'))
        self.assertEqual(self.state.get('search.electrical.biases_V'),[0.,-.2,-.1])

    def test_bias_apply_and_check_are_adjacent_to_draft_before_applied_preview(self):
        self.page.set_mode('electrical'); self.page.select_section('electrical.study')
        mode = self.editor('ui.electrical.sweep_mode')
        mode.setCurrentIndex(mode.findData('manual')); APP.processEvents()
        manual = self.editor('ui.electrical.bias_list_text')
        row = manual.parentWidget().parentWidget()
        card = row.parentWidget(); layout = card.layout()
        apply = next(button for button in card.findChildren(QPushButton)
            if button.property('setupActionId') == 'electrical.study.apply_manual')
        check = next(button for button in card.findChildren(QPushButton)
            if button.property('setupActionId') == 'electrical.study.validate')
        # Actions live directly after editable controls, before preview rows.
        self.assertEqual(layout.indexOf(apply), layout.indexOf(row)+2)
        self.assertEqual(layout.indexOf(check), layout.indexOf(apply)+1)
        self.assertIn('draft until Apply', row.caption.text())
        before = copy.deepcopy(self.state.get('search.electrical.biases_V'))
        manual.setPlainText('0, -.12, -.24')
        self.assertEqual(self.state.get('search.electrical.biases_V'), before)
        apply.click(); APP.processEvents()
        self.assertEqual(self.state.get('search.electrical.biases_V'), [0., -.12, -.24])
        manual.setPlainText('0, unfinished')
        apply.click(); APP.processEvents()
        self.assertEqual(self.state.get('search.electrical.biases_V'), [0., -.12, -.24])
        with patch.object(self.page, 'validate_current') as validate:
            check.click()
            validate.assert_called_once_with()
        grid, cards = next((grid, cards) for grid, cards in self.page.page_grids
            if any(card['id'] == 'electrical.study.range' for _, card in cards))
        ids = [card['id'] for _, card in cards]
        self.assertEqual(ids.index('electrical.study.schedule'), ids.index('electrical.study.range')+1)

    def test_validation_issue_opens_correct_tab_and_run_has_no_confirmation(self):
        spy=QSignalSpy(self.page.runRequested)
        with patch.object(self.state,'validate',return_value=[dict(key='settings.NumG',message='Invalid basis',tab='optical.accuracy')]):
            self.page.run()
        self.assertEqual(len(spy),0)
        item=self.page.validation_list.item(0)
        self.page._open_issue(item)
        self.assertEqual(self.page.current_section,'optical.accuracy')
        with patch.object(self.state,'validate',return_value=[]):
            self.page.run()
        self.assertEqual(list(spy),[['optical']])

    def test_fit_view_is_cosmetic_and_does_not_build_a_mesh(self):
        before=self.store.portable_project()
        for view in (self.page.shared_preview,self.page.top_preview,self.page.section_preview):
            view.zoom=2.
        with patch.object(self.state,'build_mesh') as mesh:
            self.page.perform_action(dict(id='fit',target='electrical.mesh_fit'))
        mesh.assert_not_called()
        self.assertEqual(self.store.portable_project(),before)
        self.assertTrue(all(view.zoom==1. for view in (self.page.shared_preview,self.page.top_preview,self.page.section_preview)))

    def test_additional_bias_samples_apply_and_cancel(self):
        before=self.state.get('search.electrical.biases_V')
        def cancel():
            dialog=APP.activeModalWidget()
            dialog.findChild(QPlainTextEdit,'setupAdditionalBiases').setPlainText('-.15')
            dialog.reject()
        QTimer.singleShot(0,cancel)
        self.page.perform_action(dict(id='extra',target='electrical.add_bias_samples'))
        self.assertEqual(self.state.get('search.electrical.biases_V'),before)
        def apply():
            dialog=APP.activeModalWidget()
            dialog.findChild(QPlainTextEdit,'setupAdditionalBiases').setPlainText('-.15, -.05')
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Apply).click()
        QTimer.singleShot(0,apply)
        self.page.perform_action(dict(id='extra',target='electrical.add_bias_samples'))
        self.assertIn(-.15,self.state.get('search.electrical.biases_V'))
        self.assertIn(-.05,self.state.get('search.electrical.biases_V'))
        self.assertEqual(self.state.get('ui.electrical.sweep_mode'),'manual')

    def test_choose_reference_uses_real_saved_sample_and_cancel_keeps_value(self):
        directory=self.store.library.runs/'sampled_peak'
        directory.mkdir()
        (directory/'results.csv').write_text('wavelength_nm,angle_deg,R,T,A\n1500,0,.8,.1,.1\n1501,0,0,.1,.9\n1502,0,.8,.1,.1\n',encoding='utf-8')
        self.store.library.record(directory,kind='simulation',status='complete',title='Saved sampled peak')
        before=self.state.get('search.coupled.reference_nm')
        self.assertEqual(len(self.page.saved_spectrum_choices(reference=True)),1)
        def cancel():
            dialog=APP.activeModalWidget()
            dialog.findChild(QListWidget,'setupSavedSpectrumList').setCurrentRow(0)
            dialog.reject()
        QTimer.singleShot(0,cancel)
        self.page.perform_action(dict(id='reference',target='dialog.choose-reference-feature'))
        self.assertEqual(self.state.get('search.coupled.reference_nm'),before)
        def apply():
            dialog=APP.activeModalWidget()
            dialog.findChild(QListWidget,'setupSavedSpectrumList').setCurrentRow(0)
            dialog.findChild(QTableWidget,'setupSavedSpectrumSamples').selectRow(0)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Apply).click()
        QTimer.singleShot(0,apply)
        self.page.perform_action(dict(id='reference',target='dialog.choose-reference-feature'))
        self.assertEqual(self.state.get('search.coupled.reference_nm'),1501.)

    def test_run_requested_fields_dispatches_without_an_inert_intermediate_step(self):
        spy=QSignalSpy(self.page.runRequested)
        with patch.object(self.state,'validate',return_value=[]):
            self.page.perform_action(dict(id='fields',target='ui.optical.outputs.execution_plan'))
        self.assertEqual(self.state.get('ui.optical.outputs.execution_plan'),'fields_only')
        self.assertEqual(list(spy),[['optical']])

    def test_pc_cell_dialog_is_transactional_and_center_uses_pc_area_position(self):
        from pc_array import apply_pc_array
        device=copy.deepcopy(self.store.device)
        width,depth=device['width_um'],device['depth_um']
        spec=dict(name='Offset PC area',layer_id=device['layers'][0]['id'],
            width_um=width*.4,depth_um=depth*.4,cell_width_um=width*.2,
            cell_depth_um=depth*.2,radius_um=min(width,depth)*.02,cx_um=width*.1,cy_um=-depth*.1)
        device=apply_pc_array(device,spec,material_library=self.store.electrical_materials)
        self.store.set_device(device)
        before=copy.deepcopy(self.store.settings)
        QTimer.singleShot(0,lambda:APP.activeModalWidget().reject())
        self.page.perform_action(dict(id='pc',target='dialog.choose-pc-cell'))
        self.assertEqual(self.store.settings,before)
        def apply():
            APP.activeModalWidget().findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Apply).click()
        QTimer.singleShot(0,apply)
        self.page.perform_action(dict(id='pc',target='dialog.choose-pc-cell'))
        cell=self.store.settings['optical_unit_cell']
        self.assertTrue(cell['enabled'])
        self.assertAlmostEqual(cell['width_um'],width*.2)
        self.assertEqual((self.store.device['width_um'],self.store.device['depth_um']),(width,depth))
        self.page.perform_action(dict(id='optical.domain.center-cell',target='settings.optical_unit_cell'))
        cell=self.store.settings['optical_unit_cell']
        self.assertAlmostEqual(cell['cx_um'],width*.1)
        self.assertAlmostEqual(cell['cy_um'],-depth*.1)

    def test_automatic_pc_cell_matches_rail_and_expanded_domain_without_saving_defaults(self):
        from test_pc_optical_defaults import pc_project
        from qt_custom_device import DeviceCanvas
        self.store.load_project(pc_project())
        before=self.store.project()
        self.page.refresh()
        cell=self.state.get('settings.optical_unit_cell')
        self.assertTrue(cell['enabled'])
        self.assertEqual((cell['width_um'],cell['depth_um']),(.3,.3))
        self.assertNotIn('optical_unit_cell',self.store.settings)
        for view in (self.page.shared_preview,self.page.top_preview,self.page.section_preview):
            self.assertEqual(view.optical_unit_cell,cell)
        observed=[]
        def inspect():
            dialog=APP.activeModalWidget()
            observed.append(copy.deepcopy(dialog.findChild(DeviceCanvas).optical_unit_cell))
            dialog.reject()
        QTimer.singleShot(0,inspect)
        self.page._domain_inspector('dialog.domain-preview')
        self.assertEqual(observed,[cell])
        self.assertEqual(self.store.project(),before)

    def test_domain_summary_separates_finite_array_from_the_single_optical_hole(self):
        from test_pc_optical_defaults import pc_project
        self.store.load_project(pc_project())
        physical=copy.deepcopy(self.store.device)
        self.page.refresh()
        summary=self.page.summary.accessibleDescription()
        self.assertIn('16 enabled regions',summary)
        self.assertIn('PC-array regions: 16 · Other regions: 0',summary)
        self.assertIn('Optical PC cell: 1 air hole',summary)
        self.assertIn('Full array shown in preview; S4 solves the optical cell.',summary)
        self.assertEqual(self.store.device,physical)
        self.assertEqual(len(self.store.device['shapes']),16)
        self.page.set_mode('electrical')
        self.assertIn('PC-array regions: 16 · Other regions: 0',self.page.summary.accessibleDescription())
        self.assertNotIn('Optical PC cell',self.page.summary.accessibleDescription())
        self.page.set_mode('optical')
        cell=dict(self.state.get('settings.optical_unit_cell'),width_um=.6)
        self.state.set('settings.optical_unit_cell',cell)
        self.assertIn('Optical PC cell: configure a one-hole pitch cell',self.page.summary.accessibleDescription())
        self.assertNotIn('Optical PC cell: 1 air hole',self.page.summary.accessibleDescription())
        self.assertEqual(self.store.device,physical)

    def test_domain_summary_counts_explicit_optical_regions_without_inferring_holes(self):
        from device_model import default_device
        device=default_device(self.store.electrical_materials)
        device['shapes']=[dict(id='custom-circle',name='Optical air circle',layer_id=device['layers'][0]['id'],
            shape='circle',cx_um=0.,cy_um=0.,size_x_um=.4,size_y_um=.4,angle_deg=0.,vertices=[],
            enabled=True,material_id='gaas',operation='material',optical_material_name='Air')]
        self.store.set_device(device)
        physical=copy.deepcopy(self.store.device)
        self.page.refresh()
        summary=self.page.summary.accessibleDescription()
        self.assertIn('1 enabled region',summary)
        self.assertNotIn('air holes',summary)
        self.assertNotIn('PC-array regions',summary)
        self.assertEqual(self.store.device,physical)
        device=copy.deepcopy(physical);device['shapes'][0]['enabled']=False
        self.store.set_device(device)
        self.assertIn('0 enabled regions',self.page.summary.accessibleDescription())


if __name__=='__main__':
    unittest.main()
