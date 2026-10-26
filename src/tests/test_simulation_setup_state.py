"""Setup bindings dispatch real shared project options and reject wrong physics."""
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_import_dir = tempfile.TemporaryDirectory(prefix='ods_setup_import_')
os.environ.setdefault('S4_LIBRARY_ROOT', _import_dir.name)

from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore, prepare_job
from simulation_setup_state import SimulationSetupState, load_plan
from test_contact_optics import device, project
from pc_array import apply_pc_array


class SimulationSetupStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='ods_setup_state_')
        self.addCleanup(self.directory.cleanup)
        self.store = ProjectStore(DataLibrary(self.directory.name), restore=False)
        value = project()
        value['settings'].update(wl_start_nm=1540., wl_stop_nm=1560., wl_step_nm=10.)
        self.store.load_project(value)
        self.state = SimulationSetupState(self.store)
        self.state.set('search.electrical.swept_contact_id', 'P')
        self.state.set('search.electrical.biases_V', [0., -.1, -.2])

    def test_packaged_plan_has_twenty_tabs_and_complete_unique_fields(self):
        catalog = load_plan()
        self.assertEqual([len(catalog['modes'][m]['tabs']) for m in ('optical','electrical','coupled')], [7,7,6])
        fields = [f for cfg in catalog['modes'].values() for tab in cfg['tabs'] for card in tab['cards'] for f in card.get('fields',[])]
        self.assertEqual(len({f['id'] for f in fields}),len(fields))
        self.assertEqual(len(catalog['dialogs']),44)
        # Every control is safe to read on a genuine non-mockup project.
        for field in fields:
            self.state.get(field['key'], field['default'])
        self.assertEqual(self.state.get('settings.NumG'),9)
        self.assertEqual(self.state.get('ui.optical.compiled_samples'),3)

    def test_cell_controls_never_resize_finite_device_and_real_model_is_cropped(self):
        self.state.set('settings.optical_unit_cell',dict(enabled=True,width_um=.45,depth_um=.45,cx_um=0.,cy_um=0.))
        self.assertEqual((self.store.device['width_um'],self.store.settings['ax_um']),(2.,2.))
        model = self.state._prepared_model()
        self.assertEqual((model['ax'],model['ay']),(.45,.45))
        self.state.set('settings.optical_unit_cell.enabled',False)
        self.assertEqual((self.state._prepared_model()['ax'],self.state._prepared_model()['ay']),(2.,2.))

    def test_workspace_source_is_fresh_without_changing_saved_or_pending_optical_jobs(self):
        from test_optical_unit_cell import patterned_project
        self.store.load_project(patterned_project())
        self.store.save_search('simulation',dict(optical_geometry_source='original_tables'))
        self.store.optical_geometry_source='original_tables'
        pending=self.state.job_options('optical')
        saved=copy.deepcopy(self.store.search_state)
        _,original=prepare_job('simulation',self.store.project(),pending,self.store.library)
        self.assertEqual((original['model']['ax'],original['model']['ay']),(2.,2.))
        self.assertEqual(len([p for p in original['model']['patterns'] if p['shape']=='circle']),9)
        self.assertFalse(any(p.get('contact_optical_surface') for p in original['model']['layers']))

        self.store.optical_geometry_source='device'
        fresh=self.state.job_options('optical')
        self.assertEqual(fresh['optical_geometry_source'],'device')
        self.assertEqual(pending['optical_geometry_source'],'original_tables')
        self.assertEqual(self.store.search_state,saved)
        _,canonical=prepare_job('simulation',self.store.project(),fresh,self.store.library)
        self.assertEqual((canonical['model']['ax'],canonical['model']['ay']),(.45,.45))
        self.assertEqual(len([p for p in canonical['model']['patterns'] if p['shape']=='circle']),1)
        self.assertTrue(any(p.get('contact_optical_surface')=='bottom' for p in canonical['model']['layers']))
        self.assertEqual(canonical['model']['geometry_source'],'device')
        self.assertEqual(self.state.validate('optical'),[])
        self.assertEqual(self.state._prepared_model()['ax'],.45)

        # A queued original job stays original even after the visible switch.
        _,queued=prepare_job('simulation',self.store.project(),pending,self.store.library)
        self.assertEqual(queued['model']['geometry_source'],'original_tables')
        self.assertEqual(queued['model']['ax'],2.)

    def test_pc_pitch_defaults_match_optical_and_coupled_jobs_without_resizing_electrical(self):
        from test_pc_optical_defaults import pc_project
        value=pc_project()
        value['settings'].update(wl_start_nm=1540.,wl_stop_nm=1560.,wl_step_nm=10.)
        self.store.load_project(value)
        self.state.set('search.electrical.swept_contact_id','P')
        self.state.set('search.electrical.biases_V',[0.,-.1,-.2])
        before=self.store.project()
        cell=self.state.get('settings.optical_unit_cell')
        self.assertTrue(cell['enabled'])
        self.assertEqual((cell['width_um'],cell['depth_um']),(.3,.3))
        self.assertNotIn('optical_unit_cell',self.store.settings)
        self.assertEqual(self.state.validate('optical'),[])
        optical=self.state._prepared_model()
        self.assertEqual(optical['optical_unit_cell']['selection'],cell)
        self.assertEqual(len([p for p in optical['patterns'] if p['shape']=='circle']),1)
        options=self.state.job_options('coupled')
        self.assertEqual(options['optical_unit_cell'],cell)
        self.assertEqual(self.state.validate('coupled'),[])
        _,coupled=prepare_job('coupled',self.store.project(),options,self.store.library)
        self.assertEqual(coupled['search']['optical_unit_cell'],cell)
        self.assertEqual(coupled['model']['optical_unit_cell']['selection'],cell)
        electrical=self.state.job_options('electrical')
        self.assertFalse(electrical['optical_unit_cell']['enabled'])
        self.assertEqual(electrical['device']['width_um'],2.)
        self.assertEqual(len(electrical['device']['shapes']),16)
        self.assertEqual(self.store.project(),before)

    def test_explicit_multi_cell_pc_choice_is_retained_but_routed_to_domain_before_run(self):
        from test_pc_optical_defaults import pc_project
        self.store.load_project(pc_project())
        self.state.set('search.electrical.swept_contact_id','P')
        self.state.set('settings.optical_unit_cell.enabled',False)
        before=self.store.project()
        self.assertFalse(self.state.get('settings.optical_unit_cell.enabled'))
        issues=self.state.validate('optical')
        self.assertTrue(any(row['tab']=='optical.domain' and 'one air hole' in row['message'] for row in issues))
        self.assertEqual(self.store.project(),before)
        self.assertEqual(self.state.validate('electrical'),[])
        self.state.set('settings.optical_unit_cell',dict(enabled=True,width_um=.6,depth_um=.3,cx_um=0.,cy_um=0.))
        self.assertTrue(any('multiple PC cells' in row['message'] for row in self.state.validate('coupled')))
        self.assertEqual(self.state.get('settings.optical_unit_cell.width_um'),.6)

    def test_original_optical_pc_tables_use_one_pitch_cell_without_device_contacts_or_saved_crop(self):
        from test_pc_optical_defaults import pc_project
        self.store.load_project(pc_project())
        self.store.optical_geometry_source='original_tables'
        self.state.set('settings.optical_unit_cell',dict(enabled=False,width_um=1.2,depth_um=1.2,cx_um=0.,cy_um=0.))
        before=self.store.project()
        self.assertEqual(self.state.validate('optical'),[])
        _,cfg=prepare_job('simulation',self.store.project(),self.state.job_options('optical'),self.store.library)
        self.assertEqual(cfg['model']['geometry_source'],'original_tables')
        self.assertEqual((cfg['model']['ax'],cfg['model']['ay']),(.3,.3))
        self.assertEqual(len([p for p in cfg['model']['patterns'] if p['shape']=='circle']),1)
        self.assertFalse(any(p.get('contact_optical_surface') for p in cfg['model']['layers']))
        self.assertEqual(self.store.project(),before)

    def test_regenerating_pc_pitch_refreshes_the_unconfigured_cell_without_saving_a_crop(self):
        from test_pc_optical_defaults import pc_project
        self.store.load_project(pc_project())
        first=self.state.get('settings.optical_unit_cell')
        spec=dict(self.store.device['pc_arrays'][0],cell_width_um=.2)
        generated=apply_pc_array(self.store.device,spec,material_library=self.store.electrical_materials)
        self.store.set_device(generated)
        current=self.state.get('settings.optical_unit_cell')
        self.assertEqual((first['width_um'],current['width_um']),(.3,.2))
        self.assertAlmostEqual(abs(current['cx_um']),.1)
        self.assertEqual(len(self.store.device['shapes']),24)
        self.assertNotIn('optical_unit_cell',self.store.settings)

    def test_electrical_only_ignores_incomplete_optical_band_and_outside_cell_draft(self):
        self.state.set('settings.wl_start_nm',1700.)
        self.state.set('settings.wl_stop_nm',1200.)
        self.state.set('settings.optical_unit_cell',dict(enabled=True,width_um=3.,depth_um=3.,cx_um=0.,cy_um=0.))
        self.assertEqual(self.state.get('settings.optical_unit_cell.width_um'),3.)
        self.assertEqual(self.state.validate('electrical'),[])
        self.assertTrue(self.state.validate('optical'))
        self.assertTrue(self.state.validate('coupled'))

    def test_real_modes_share_electrical_and_coupling_has_current_selection(self):
        self.state.set('search.electrical.terminal_studies.iv_enabled',True)
        self.state.set('search.electrical.terminal_studies.cv_enabled',True)
        self.state.set('search.coupled.optical_slices_per_layer',3)
        self.state.set('settings.optical_unit_cell',dict(enabled=True,width_um=.45,depth_um=.45,cx_um=0.,cy_um=0.))
        electrical=self.state.job_options('electrical')
        coupled=self.state.job_options('coupled')
        self.assertFalse(electrical['optical_enabled'])
        self.assertTrue(coupled['optical_enabled'])
        self.assertEqual(electrical['biases_V'],coupled['biases_V'])
        self.assertEqual(electrical['terminal_studies'],coupled['terminal_studies'])
        self.assertFalse(electrical['optical_unit_cell']['enabled'])
        self.assertTrue(coupled['optical_unit_cell']['enabled'])
        self.assertEqual(coupled['optical_slices_per_layer'],3)
        self.assertEqual(self.state.validate('electrical'),[])
        self.assertEqual(self.state.validate('coupled'),[])
        _,cfg=prepare_job('coupled',self.store.project(),coupled,self.store.library)
        self.assertEqual(cfg['search']['biases_V'],electrical['biases_V'])

    def test_cv_requires_three_distinct_biases(self):
        self.state.set('ui.electrical.study','cv')
        self.state.set('search.electrical.biases_V',[0.,-.1])
        issues=self.state.validate('electrical')
        self.assertTrue(any('three' in row['message'].lower() for row in issues))
        self.state.set('search.electrical.biases_V',[0.,-.1,-.2])
        self.assertEqual(self.state.validate('electrical'),[])

    def test_forward_bias_gate_and_dielectric_mode(self):
        self.state.set('search.electrical.biases_V',[0.,.2])
        self.assertTrue(any('Forward' in r['message'] for r in self.state.validate('electrical')))
        self.state.set('search.electrical.charge_model','dielectric')
        self.assertEqual(self.state.validate('electrical'),[])

    def test_invalid_mesh_edit_is_atomic_and_keeps_canonical_geometry(self):
        self.state.set('device.mesh.max_nodes',120000)
        previous=self.store.project()
        with self.assertRaisesRegex(ValueError,'cells|limit'):
            self.state.set('device.mesh.nx',256)
            self.state.set('device.mesh.ny',256)
        # First independent valid X edit remains; second is rejected atomically.
        self.assertEqual(self.store.device['mesh']['nx'],256)
        self.assertEqual(self.store.device['mesh']['ny'],previous['device']['mesh']['ny'])
        self.assertEqual(self.store.device['layers'],previous['device']['layers'])

    def test_fine_mesh_counts_and_resource_readouts_do_not_allocate(self):
        self.state.set('device.mesh.max_nodes',0)
        with patch('custom_electrical_solver.build_mesh',side_effect=AssertionError('Editing must not allocate a mesh')):
            for key,value in (('nx',320),('ny',320),('nz_per_layer',12)):
                self.state.set('device.mesh.'+key,value)
            self.assertEqual(self.store.device['mesh']['nx'],320)
            self.assertEqual(self.store.device['mesh']['ny'],320)
            self.assertIn('planning estimate',self.state.get('ui.electrical.mesh_peak_memory'))
            self.assertIn('/ bias',self.state.get('ui.electrical.mesh_volume_memory'))
            self.assertEqual(self.state.get('ui.electrical.mesh_linear_solver'),'Jacobi-scaled CG')
            self.assertIn('Automatic',self.state.get('ui.electrical.mesh_resource_budget'))

    def test_store_autosave_failure_restores_shared_control(self):
        before=self.store.project()
        with patch.object(self.store,'_autosave',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):
                self.state.set('search.electrical.terminal_studies.iv_enabled',True)
        self.assertEqual(self.store.project(),before)

    def test_study_switch_and_single_wavelength_remember_actual_sweep(self):
        self.state.set('ui.optical.study_type','single')
        self.state.set('ui.optical.single.wavelength_nm',1558.)
        self.assertEqual(self.store.settings['wl_start_nm'],1558.)
        self.assertEqual(self.store.settings['wl_stop_nm'],1558.)
        self.state.set('ui.optical.study_type','wavelength_sweep')
        self.assertEqual((self.store.settings['wl_start_nm'],self.store.settings['wl_stop_nm']),(1540.,1560.))
        self.state.set('ui.optical.study_type','angle_sweep')
        self.assertEqual(self.store.settings['mode'],'Angle sweep')
        self.state.set('ui.optical.study_type','single')
        self.assertEqual(self.state.get('ui.optical.single.wavelength_nm'),1558.)

    def test_voltage_generation_includes_real_stop_and_zero_without_duplicates(self):
        for key,value in [('bias_start_V',-.21),('bias_stop_V',-.01),('bias_step_V',.06)]:
            self.state.set('ui.electrical.'+key,value)
        values=self.state.generate_biases()
        self.assertEqual(values,[0.,-.21,-.15,-.09,-.03,-.01])
        self.assertEqual(self.state.parse_biases('-.2, -.2; -.1\n0'),[0.,-.2,-.1])
        with self.assertRaises(ValueError): self.state.parse_biases('NaN')
        with self.assertRaises(ValueError): self.state.parse_biases('1e309')

    def test_dense_point_count_includes_endpoints_and_extra_reference(self):
        self.state.set('search.electrical.charge_model', 'dielectric')
        for key, value in [('bias_start_V', 0.), ('bias_stop_V', 500.), ('range_sampling', 'count'), ('bias_point_count', 5001)]:
            self.state.set('ui.electrical.' + key, value)
        self.assertIn('5,001 range points', self.state.get('ui.electrical.range_summary'))
        self.assertIn('0.1 V spacing', self.state.get('ui.electrical.range_summary'))
        values = self.state.generate_biases()
        self.assertEqual(len(values), 5001)
        self.assertEqual((values[0], values[1], values[-1]), (0., .1, 500.))
        self.assertEqual(len(self.state.job_options('electrical')['biases_V']), 5001)
        self.state.set('ui.electrical.bias_start_V', 1.)
        self.state.set('ui.electrical.bias_stop_V', 2.)
        self.state.set('ui.electrical.bias_point_count', 1001)
        self.assertIn('1,001 range points', self.state.get('ui.electrical.range_summary'))
        self.assertIn('1,002 distinct solved', self.state.get('ui.electrical.range_summary'))
        self.assertEqual(len(self.state.generate_biases()), 1002)

    def test_live_range_count_does_not_generate_or_allocate_the_schedule(self):
        self.state.set('ui.electrical.range_sampling', 'count')
        self.state.set('ui.electrical.bias_start_V', 500.)
        self.state.set('ui.electrical.bias_stop_V', 0.)
        self.state.set('ui.electrical.bias_point_count', 5001)
        before = self.state.get('search.electrical.biases_V')
        with patch('electrical_sweep.generate_biases', side_effect=AssertionError('Live readout must not generate a schedule')):
            self.assertIn('5,001 range points', self.state.get('ui.electrical.range_summary'))
        self.assertEqual(self.state.get('search.electrical.biases_V'), before)
        values = self.state.generate_biases()
        self.assertEqual((len(values), values[0], values[1], values[-1]), (5001, 0., 500., .1))

    def test_dense_schedule_preview_is_bounded_and_full_state_is_retained(self):
        self.state.set('ui.electrical.range_sampling', 'count')
        self.state.set('ui.electrical.bias_start_V', -12.)
        self.state.set('ui.electrical.bias_stop_V', 0.)
        self.state.set('ui.electrical.bias_point_count', 2401)
        values = self.state.generate_biases()
        rows = self.state.get('ui.electrical.voltage_schedule')
        self.assertEqual(len(rows), 200)
        self.assertEqual(rows[0][0], 1)
        self.assertEqual(rows[-1][0], 2401)
        self.assertEqual(self.state.get('ui.electrical.voltage_schedule_count'), 2401)
        self.assertIn('2,401', self.state.get('ui.electrical.offset_summary'))
        self.assertLess(len(self.state.get('ui.electrical.offset_summary')), 100)
        self.assertEqual(self.state.get('search.electrical.biases_V'), values)
        self.assertIn('2,401 resolved states', self.state.get('ui.electrical.mesh_sweep_storage'))
        self.assertIn('uncompressed planning estimate', self.state.get('ui.electrical.mesh_sweep_storage'))

    def test_dense_range_invalid_count_is_atomic_and_step_reports_remainder(self):
        previous = self.state.get('search.electrical.biases_V')
        self.state.set('ui.electrical.range_sampling', 'count')
        self.state.set('ui.electrical.bias_start_V', 0.)
        self.state.set('ui.electrical.bias_stop_V', 12.)
        self.state.set('ui.electrical.bias_point_count', 1)
        with self.assertRaises(ValueError): self.state.generate_biases()
        self.assertEqual(self.state.get('search.electrical.biases_V'), previous)
        self.state.set('ui.electrical.range_sampling', 'step')
        self.state.set('ui.electrical.bias_stop_V', 1.)
        self.state.set('ui.electrical.bias_step_V', .3)
        self.assertIn('final interval 0.1 V', self.state.get('ui.electrical.range_summary'))
        self.assertEqual(self.state.generate_biases(), [0., .3, .6, .9, 1.])

    def test_fixed_legacy_model_retains_its_range_and_count_gate(self):
        self.state.set('search.electrical.model', 'explicit_ito')
        with self.assertRaises(ValueError): self.state.parse_biases('0, 500')
        self.state.set('ui.electrical.range_sampling', 'count')
        self.state.set('ui.electrical.bias_start_V', -4.)
        self.state.set('ui.electrical.bias_stop_V', 0.)
        self.state.set('ui.electrical.bias_point_count', 1001)
        with self.assertRaises(ValueError): self.state.generate_biases()

    def test_use_pc_lattice_chooses_existing_hole_in_even_array_and_preserves_enabled(self):
        physical=apply_pc_array(self.store.device,dict(id='pc',name='Nondefault PC',layer_id='p',
            width_um=1.2,depth_um=1.2,cell_width_um=.3,cell_depth_um=.3,radius_um=.05,cx_um=0.,cy_um=0.),
            material_library=self.store.electrical_materials)
        self.store.set_device(physical)
        self.state.set('settings.optical_unit_cell.enabled',False)
        selected=self.state.use_pc_lattice()
        self.assertFalse(selected['enabled'])
        self.assertEqual(selected['width_um'],.3)
        self.assertAlmostEqual(abs(selected['cx_um']),.15)
        self.assertAlmostEqual(abs(selected['cy_um']),.15)
        self.assertEqual(self.store.device['width_um'],2.)

    def test_coupled_output_policy_explicitly_gates_unsupported_requests(self):
        self.state.set('search.simulation.measure_phase',True)
        self.state.set('ui.optical.outputs.fields_enabled',True)
        self.state.set('ui.coupled.unsupported_output_policy','require_all')
        self.assertTrue(any('unavailable' in row['message'] for row in self.state.validate('coupled')))
        self.state.set('ui.coupled.unsupported_output_policy','supported_only')
        self.assertEqual(self.state.validate('coupled'),[])
        self.assertTrue(self.state.get('search.simulation.measure_phase'))
        self.assertTrue(self.state.get('ui.optical.outputs.fields_enabled'))
        self.state.set('ui.optical.engine','meep')
        self.assertTrue(any('requires S4' in row['message'] for row in self.state.validate('coupled')))

    def test_presets_do_not_resize_device_and_bad_contact_is_rejected_atomically(self):
        payload=self.state.export_preset('coupled')
        payload['settings']['ax_um']=150.
        payload['settings']['ay_um']=150.
        payload['settings']['NumG']=21
        self.state.import_preset(payload)
        self.assertEqual(self.store.device['width_um'],2.)
        self.assertEqual(self.store.settings['NumG'],21)
        payload['electrical']['swept_contact_id']='absent'
        before=self.store.project()
        self.assertTrue(self.state.preview_preset(payload)['errors'])
        with self.assertRaisesRegex(ValueError,'absent'):
            self.state.import_preset(payload)
        self.assertEqual(self.store.project(),before)

    def test_ui_state_persists_and_loaded_source_settings_override_mockup(self):
        self.state.set('ui.optical.engine','meep')
        self.state.set('ui.electrical.initial_field','Ez')
        self.state.set('search.electrical.terminal_studies.cv_enabled',True)
        saved=self.store.project()
        self.store.load_project(saved)
        state=SimulationSetupState(self.store)
        self.assertEqual(state.get('ui.optical.engine'),'meep')
        self.assertEqual(state.get('ui.electrical.initial_field'),'Ez')
        self.assertTrue(state.get('search.electrical.terminal_studies.cv_enabled'))
        self.assertEqual(state.get('settings.NumG'),9)
        self.assertEqual(state.get('device.name'),'Si-PCS usability device')

    def test_material_and_contact_edit_live_shared_canonical_rows(self):
        self.state.set('ui.electrical.selected_contact_id','P')
        self.state.set('device.contacts[{ui.electrical.selected_contact_id}].voltage_V',-.05)
        self.assertEqual(self.state.selected_contact()['voltage_V'],-.05)
        self.state.update_layer('p',dict(acceptor_cm3=2e17))
        self.assertEqual(self.state.get('device.layers')[0]['acceptor_cm3'],2e17)
        rows=self.state.get('ui.optical.assignment_rows')
        self.assertTrue(any(r['id']=='p' and r['kind']=='layer' for r in rows))
        self.state.update_optical_assignment('p','Si')
        self.assertEqual(self.store.device['layers'][0]['optical_material_name'],'Si')
        self.assertEqual(set(self.state.auto_map()),{'p','n'})


if __name__=='__main__':
    unittest.main()
