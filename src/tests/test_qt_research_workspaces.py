"""Native research editor interactions, portable drafts and real data viewers."""
import copy
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from data_library import DataLibrary
from qt_core import ProjectStore
from qt_photonic_bands import PhotonicBandsWorkspace
from qt_research_studies import ResearchStudiesWorkspace, StructuredValueEditor
from qt_research_results import ResearchResultsPanel
from qt_thermal_setup import ThermalSetupWorkspace
from qt_sesame_setup import SesameSetupWorkspace

APP = QApplication.instance() or QApplication([])


class ResearchEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods-ui-research-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(DataLibrary(self.root/'library'), restore=False)
        self.pages = []

    def page(self, cls, *args):
        page = cls(self.store, *args)
        page.resize(1250, 800)
        page.show(); APP.processEvents()
        self.pages.append(page)
        return page

    def tearDown(self):
        for page in self.pages:
            page.close(); page.deleteLater()
        APP.processEvents()

    def test_invalid_primitive_draft_roundtrip_and_exact_missing_input_navigation(self):
        page = self.page(PhotonicBandsWorkspace)
        self.assertIs(page.layout(), page.body_layout)
        identity = page._object_ids[0]
        page.geometry.item(0, 3).setText('1e-')
        page.save_draft()
        self.assertFalse(page.validate_setup())
        target = page.diagnostics.list.item(0).data(Qt.ItemDataRole.UserRole)
        self.assertEqual(target['object_id'], identity)
        self.assertEqual(target['field'], 'radius')
        page.select_section('Overview')
        self.assertTrue(page.open_diagnostic(target))
        self.assertEqual(page.geometry.currentColumn(), 3)
        self.assertEqual(page.geometry.item(0, 3).text(), '1e-')
        saved = self.store.portable_project()
        other = ProjectStore(DataLibrary(self.root/'other'), restore=False)
        other.load_project(saved)
        restored = PhotonicBandsWorkspace(other)
        self.pages.append(restored)
        self.assertEqual(restored.geometry.item(0, 3).text(), '1e-')
        self.assertEqual(restored._object_ids[0], identity)
        page.geometry.item(0, 3).setText('0.31')
        self.assertTrue(page.validate_setup())
        self.assertEqual(page.diagnostics.list.count(), 0)

    def test_deleted_object_diagnostic_never_selects_another_primitive(self):
        page = self.page(PhotonicBandsWorkspace)
        identity = page._object_ids[0]
        page.add_primitive()
        page.geometry.setCurrentCell(0, 0); page.remove_primitive()
        self.assertFalse(page.open_diagnostic(dict(workspace='photonic_bands', object_id=identity, field='radius')))
        self.assertIn('removed', page.status.text())

    def test_actual_research_worker_receives_editable_geometry_and_runtime(self):
        page = self.page(PhotonicBandsWorkspace)
        before = copy.deepcopy(self.store.device)
        page.geometry.item(0, 3).setText('.33')
        page.distro.setText('UserLinux')
        with patch('qt_core.BackendWorker.start') as started:
            page.run()
            started.assert_called_once()
        request = self.store.search_state['research_simulation']
        self.assertEqual(request['settings']['geometry'][0]['radius'], .33)
        self.assertEqual(request['settings']['runtime']['distro'], 'UserLinux')
        self.assertEqual(self.store._worker.kind, 'research_simulation')
        self.assertEqual(self.store.device, before)
        self.store._finished()

    def test_sampling_convergence_and_linked_sweep_are_canonical(self):
        page = self.page(PhotonicBandsWorkspace)
        page.sampling.setCurrentIndex(page.sampling.findData('grid'))
        page.grid_counts.setText('3, 4, 5')
        page.levels.setText('8, 12')
        page.sweep_target.setCurrentIndex(1); page.add_sweep()
        page.sweeps.item(0, 3).setText('.1, .2')
        options = page.options()
        self.assertNotIn('k_vertices', options['settings'])
        self.assertEqual(options['settings']['k_grid']['counts'], [3, 4, 5])
        self.assertEqual(options['settings']['resolution_levels'], [8, 12])
        self.assertEqual(options['settings']['parameter_sweep']['parameters'][0]['targets'][0]['object_id'], page._object_ids[0])
        self.assertTrue(page.validate_setup())

    def test_more_studies_is_lazy_and_thermal_requires_sourced_properties(self):
        chooser = self.page(ResearchStudiesWorkspace)
        self.assertEqual(chooser._pages, {})
        self.assertTrue(chooser.select_engine('thermal'))
        thermal = chooser.stack.currentWidget()
        self.assertFalse(thermal.validate_setup())
        self.assertEqual(thermal.diagnostics.list.item(0).data(Qt.ItemDataRole.UserRole)['field'], 'conductivity')
        for row in range(thermal.conductivities.rowCount()):
            thermal.conductivities.item(row, 1).setText('45')
            thermal.conductivities.item(row, 2).setText('Explicit test material, not a literature validation')
        thermal.void_k.setText('0.025')
        self.assertTrue(thermal.validate_setup())
        self.assertEqual(thermal.options()['engine'], 'thermal')
        self.assertNotIn('sesame_transport', chooser._pages)

    def test_sesame_import_retains_materials_region_and_contact_units(self):
        from benchmark_registry import list_benchmarks, load_benchmark
        reference = next(row for row in list_benchmarks() if row.get('engine') == 'sesame_transport')
        settings = load_benchmark(reference['id'])['options']['settings']
        page = self.page(SesameSetupWorkspace)
        page.load_settings(settings)
        self.assertTrue(page.validate_setup())
        actual = page.options()['settings']
        self.assertEqual(actual['x_nodes_um'], settings['x_nodes_um'])
        expected_regions = [dict({'donors_cm3': 0., 'acceptors_cm3': 0., 'generation_cm3_s': 0.}, **region) for region in settings['regions']]
        self.assertEqual(actual['regions'], expected_regions)
        self.assertEqual(actual['contacts'], settings['contacts'])
        self.assertEqual(actual['materials'], settings['materials'])

    def test_results_retain_partial_status_and_compare_only_matching_coordinates(self):
        folder = self.root/'result'; folder.mkdir()
        (folder/'research_summary.json').write_text(json.dumps(dict(engine='photonic_bands', status='partial', limitations=['Test data fixture'])))
        with (folder/'bands_te.csv').open('w', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(['path_distance_reciprocal_a', 'band_1_a_over_lambda'])
            writer.writerows([[0, .1], [1, .2], [2, .3]])
        ref = self.root/'reference.csv'; ref.write_text('x,y\n0,0.11\n2,0.29\n3,0.5\n')
        viewer = ResearchResultsPanel(self.store, 'photonic_bands')
        self.pages.append(viewer)
        self.assertTrue(viewer.load_directory(folder))
        self.assertIn('PARTIAL', viewer.status.text())
        viewer.y_axis.setCurrentText('band_1_a_over_lambda')
        self.assertTrue(viewer.load_reference(ref))
        self.assertIn('2 exact-coordinate samples', viewer.compare_status.text())
        self.assertIn('0.01', viewer.compare_status.text())

    def test_structured_editor_preserves_invalid_number_draft_without_changing_type(self):
        editor = StructuredValueEditor([dict(id='layer', thickness_nm=100.)], 'layers')
        self.pages.append(editor)
        item = editor.tree.topLevelItem(0).child(0).child(1)
        item.setText(1, '1e-')
        draft = editor.draft()
        editor.restore_draft(draft)
        with self.assertRaisesRegex(ValueError, 'finite'):
            editor.value()
        self.assertEqual(editor.tree.topLevelItem(0).child(0).child(1).text(1), '1e-')

    def test_existing_device_diagnostic_preserves_unapplied_invalid_drafts(self):
        from device_model import default_device
        from qt_custom_device import CustomDevicePage
        self.store.set_device(default_device(self.store.electrical_materials))
        page = CustomDevicePage(self.store, include_advanced=False)
        self.pages.append(page)
        page.resize(1450, 900); page.show(); APP.processEvents()
        first, second = [layer['id'] for layer in self.store.device['layers'][:2]]
        page.select_object(first)
        page.donor_edit.setText('1e-')
        before = copy.deepcopy(self.store.device)
        self.assertTrue(page.open_diagnostic(dict(object_id=second, field='donor_cm3', message='Enter donors')))
        self.assertEqual(page.selected_id, second)
        self.assertEqual(self.store.device, before)
        page.acceptor_edit.setText('uncommitted target draft')
        self.assertTrue(page.return_from_diagnostic())
        self.assertEqual(page.selected_id, first)
        self.assertEqual(page.donor_edit.text(), '1e-')
        self.assertEqual(self.store.device, before)
        self.assertTrue(page.open_diagnostic(dict(object_id=second, field='acceptor_cm3')))
        self.assertEqual(page.acceptor_edit.text(), 'uncommitted target draft')
        self.store.load_project(self.store.project())
        self.assertEqual(page._diagnostic_drafts, {})
        self.assertIsNone(page._diagnostic_origin)

    def test_pcsel_example_and_nested_missing_input_remain_editable(self):
        chooser = self.page(ResearchStudiesWorkspace)
        self.assertTrue(chooser.select_engine('pcsel'))
        page = chooser.stack.currentWidget()
        page.load_pcsel_example()
        self.assertTrue(page.validate_setup())
        editor = page.structured['layers']
        row = editor.tree.topLevelItem(0).child(0)
        thickness = next(row.child(i) for i in range(row.childCount()) if row.child(i).text(0) == 'thickness_nm')
        identity = next(row.child(i).text(1) for i in range(row.childCount()) if row.child(i).text(0) == 'id')
        thickness.setText(1, 'unfinished')
        self.assertFalse(page.validate_setup())
        self.assertTrue(page.open_diagnostic(dict(workspace='research_studies', field='layers.thickness_nm', object_id=identity)))
        self.assertIs(editor.tree.currentItem(), thickness)
        self.assertEqual(thickness.text(1), 'unfinished')

    def test_save_flush_captures_active_table_editor_before_focus_changes(self):
        from PyQt6.QtWidgets import QLineEdit
        page = self.page(PhotonicBandsWorkspace)
        page.show_stage('unit')
        page.unit_custom_toggle.setChecked(True)
        page.custom_vectors_toggle.setChecked(True)
        page.lattice.setCurrentCell(0, 0)
        page.lattice.editItem(page.lattice.item(0, 0))
        APP.processEvents()
        editor = page.lattice.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.setFocus(); editor.setText('unfinished vector')
        page.flush_draft()
        self.assertEqual(self.store.search_state['research_workspaces']['bands']['lattice'][0][0], 'unfinished vector')

    def test_real_prescribed_heat_job_loads_actual_volume_view(self):
        from device_model import default_device
        from research_simulation import prepare_research_job, execute_research
        device = default_device(self.store.electrical_materials)
        device.update(layers=device['layers'][:1], contacts=[], shapes=[], doping_regions=[], width_um=1., depth_um=1.,
                      mesh=dict(nx=3, ny=3, nz_per_layer=3, max_nodes=0))
        self.store.set_device(device)
        page = self.page(ThermalSetupWorkspace)
        page.powers.item(0, 1).setText('0.0001')
        page.conductivities.item(0, 1).setText('45')
        page.conductivities.item(0, 2).setText('Explicit homogeneous regression coefficient')
        self.assertTrue(page.validate_setup())
        folder = self.root/'thermal-result'
        event = execute_research(prepare_research_job(self.store.project(), page.options()), folder)
        self.assertEqual(event['summary']['status'], 'complete')
        self.assertTrue(page.results.load_directory(folder))
        self.assertGreater(page.results.volume['temperature_K'].max(), 300.)
        self.assertEqual(page.results.volume['temperature_K'].shape, (3, 3, 3))
        self.assertIn('prescribed-heat', page.results.volume_note.text())

    def test_advanced_optional_heat_stays_off_and_nested_map_route_selects_exact_property(self):
        chooser = self.page(ResearchStudiesWorkspace)
        self.assertTrue(chooser.select_engine('advanced_transport'))
        page = chooser.stack.currentWidget()
        page.fields['swept_contact_id'].setText('explicit-contact')
        page.fields['parameter_source'].setText('Explicit test assumptions')
        self.assertNotIn('thermal', page.options()['settings'])
        page.structured['contacts'].set_value({'stable-contact': {'electron_resistivity_ohm_cm2': 1e-6, 'hole_resistivity_ohm_cm2': 0., 'source': 'fixture'}})
        self.assertTrue(chooser.open_diagnostic(dict(workspace='advanced_transport', field='contacts.stable-contact.source', object_id='stable-contact')))
        self.assertEqual(page.structured['contacts'].tree.currentItem().text(0), 'source')

    def test_pcsel_native_sweep_targets_stable_edited_geometry_and_preserves_invalid_values(self):
        chooser = self.page(ResearchStudiesWorkspace)
        chooser.select_engine('pcsel')
        page = chooser.stack.currentWidget()
        page.load_pcsel_example()
        sweep = page.structured['parameter_sweep']
        sweep.refresh_targets()
        index = next(index for index in range(sweep.targets.count())
                     if sweep.targets.itemData(index).get('path') == 'shapes')
        target = sweep.targets.itemData(index)
        sweep.targets.setCurrentIndex(index); sweep.add_target()
        sweep.table.item(0, 3).setText('0.15, 0.18')
        self.assertEqual(page.options()['settings']['parameter_sweep']['parameters'],
                         [dict(target, values=[0.15, 0.18])])
        self.assertTrue(page.validate_setup())
        sweep.table.item(0, 3).setText('0.15, unfinished')
        draft = page.draft()
        page.restore_draft(draft)
        self.assertEqual(sweep.table.item(0, 3).text(), '0.15, unfinished')
        self.assertFalse(page.validate_setup())
        self.assertTrue(page.open_diagnostic(dict(workspace='research_studies', field='parameter_sweep.0.values')))
        self.assertEqual(sweep.table.currentColumn(), 3)

    def test_saved_array_viewer_uses_actual_selected_slice_and_complex_convention(self):
        import numpy as np
        from qt_research_results import SavedArrayViewer
        values = np.arange(2*3*4*2).reshape(2, 3, 4, 2)+2j
        np.savez(self.root/'state.npz', current=values, metadata='not a field')
        viewer = SavedArrayViewer(); self.pages.append(viewer)
        viewer.load_directory(self.root)
        viewer.quantity.setCurrentText('current')
        viewer.slice.setValue(2); viewer.component.setValue(1)
        viewer.part.setCurrentText('Magnitude')
        np.testing.assert_allclose(viewer.displayed, np.abs(values[:, :, 2, 1]))
        self.assertIn('not physical distance', viewer.note.text())
        viewer.quantity.setCurrentText('metadata')
        self.assertIsNone(viewer.displayed)

    def test_legacy_benchmark_duplicate_requests_safe_project_replacement(self):
        chooser = self.page(ResearchStudiesWorkspace)
        before = copy.deepcopy(self.store.project())
        requests = []
        chooser.projectReplacementRequested.connect(requests.append)
        case = dict(kind='spectrum', options=dict(wavelength_min=123.), project=dict(before, name='Reference'))
        with patch('benchmark_registry.editable_copy', return_value=case):
            chooser.duplicate_benchmark()
        self.assertEqual(requests, [case])
        self.assertEqual(self.store.project(), before)
        chooser._reference_running = True
        self.store.run_failed.emit('runtime unavailable')
        self.assertFalse(chooser._reference_running)

    def test_edited_benchmark_retains_reference_identity_in_saved_draft_and_run_snapshot(self):
        page = self.page(PhotonicBandsWorkspace)
        page.geometry.item(0, 3).setText('unfinished before explicit replacement')
        page.duplicate_benchmark()
        identity = page._benchmark_request
        self.assertIsNotNone(identity)
        self.assertEqual(self.store.search_state['research_workspaces']['bands']['benchmark_request'], identity)
        self.assertNotIn('benchmark_request', self.store.project())
        page.geometry.item(0, 3).setText('0.22')
        with patch.object(self.store, 'start_run') as start:
            page.run()
        snapshot = start.call_args.kwargs['project_snapshot']
        self.assertEqual(snapshot['benchmark_request'], identity)
        from benchmark_registry import prepare_comparison_request
        self.assertTrue(prepare_comparison_request(snapshot, 'research_simulation', page.options())['input_edited'])
        page.load_settings(page.options()['settings'])
        self.assertIsNone(page._benchmark_request)

    def test_pcsel_saved_modes_choose_spatial_axes_and_saved_physical_coordinates(self):
        import numpy as np
        from qt_research_results import SavedArrayViewer
        values = np.arange(2*4*3*5).reshape(2, 4, 3, 5)+3j
        axes = {'fields': dict(axes=[dict(name='Mode'), dict(name='Basic wave'),
            dict(name='y', coordinate='y_um', unit='µm'), dict(name='x', coordinate='x_um', unit='µm')], unit='amplitude')}
        np.savez(self.root/'modes.npz', fields=values, x_um=np.linspace(-2, 2, 5), y_um=np.linspace(-1, 1, 3), array_axes=json.dumps(axes))
        viewer = SavedArrayViewer(); self.pages.append(viewer); viewer.load_directory(self.root)
        viewer.quantity.setCurrentText('fields')
        self.assertEqual(viewer.display_dimensions, [3, 2])
        viewer.slice.setValue(1); viewer.component.setValue(2)
        np.testing.assert_array_equal(viewer.displayed, values[1, 2].real.T)
        self.assertEqual(viewer.plot.axes.get_xlabel(), 'x (µm)')
        self.assertEqual(viewer.plot.axes.get_ylabel(), 'y (µm)')
        viewer.x_axis.setCurrentIndex(1); viewer.y_axis.setCurrentIndex(0)
        self.assertEqual(viewer.display_dimensions, [1, 0])
        self.assertEqual(viewer.displayed.shape, (4, 2))

    def test_optional_physics_template_creates_blank_numeric_fields_without_invented_coefficients(self):
        from device_model import default_device
        self.store.set_device(default_device(self.store.electrical_materials))
        chooser = self.page(ResearchStudiesWorkspace); chooser.select_engine('advanced_transport')
        page = chooser.stack.currentWidget()
        page.create_model_fields('nonlocal_tunnelling')
        editor = page.structured['nonlocal_tunnelling']
        self.assertTrue(editor.open_field('nonlocal_tunnelling.transverse_mass_ratio'))
        item = editor.tree.currentItem()
        self.assertEqual(item.text(1), '')
        self.assertEqual(item.data(0, Qt.ItemDataRole.UserRole), 'number')
        with self.assertRaises(ValueError):
            editor.value()

    def test_conformal_example_is_independent_and_materials_remain_editable(self):
        chooser = self.page(ResearchStudiesWorkspace)
        before = copy.deepcopy(self.store.device)
        self.assertTrue(chooser.select_engine('pcsel_transport'))
        page = chooser.stack.currentWidget(); page.load_conformal_example()
        self.assertTrue(page.validate_setup())
        self.assertEqual(page.options()['settings']['period_um'], [.3, .4])
        self.assertEqual(self.store.device, before)
        self.assertTrue(chooser.open_diagnostic(dict(workspace='research_studies', model_id='pcsel_transport',
            object_id='demo', field='materials.demo.electron_mobility_cm2_Vs')))
        page.structured['materials'].tree.currentItem().setText(1, '125')
        self.assertEqual(page.options()['settings']['materials']['demo']['electron_mobility_cm2_Vs'], 125.)

    def test_engine_alias_diagnostic_is_local_and_project_load_restores_selected_study(self):
        chooser = self.page(ResearchStudiesWorkspace)
        outward = []
        chooser.diagnosticRequested.connect(outward.append)
        self.assertTrue(chooser.open_diagnostic(dict(workspace='pcsel_transport', field='temperature_K')))
        self.assertEqual(outward, [])
        self.assertEqual(chooser.selector.currentData(), 'pcsel_transport')
        self.assertTrue(chooser.open_diagnostic(dict(workspace='pcsel_unitcell_transport', field='parameter_source')))
        self.assertEqual(outward, [])
        project = self.store.project()
        project['desktop_search']['research_workspaces']['studies']['selected_engine'] = 'sesame_transport'
        self.store.load_project(project)
        self.assertEqual(chooser.selector.currentData(), 'sesame_transport')
        self.assertIs(chooser.stack.currentWidget(), chooser._pages['sesame_transport'])

    def test_conformal_maps_use_real_tetrahedron_centroids_and_explicit_local_vertex_average(self):
        import numpy as np
        from qt_research_results import UnstructuredFieldViewer
        points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1]], float)
        cells = np.array([[0, 1, 2, 3], [1, 2, 3, 4]])
        values = np.array([[1, 2, 3, 4], [5, 6, 7, 8]], float)
        np.savez(self.root/'conformal.npz', points_um=points, tetrahedra=cells,
                 electrons_element_cm3=values, potential_V=np.arange(5.))
        viewer = UnstructuredFieldViewer(); self.pages.append(viewer); self.assertTrue(viewer.load_directory(self.root))
        viewer.quantity.setCurrentText('electrons_element_cm3')
        np.testing.assert_allclose(viewer.selected_points, points[cells].mean(axis=1))
        np.testing.assert_allclose(viewer.selected_values, [2.5, 6.5])
        self.assertIn('mean of four element-local vertex values', viewer.note.text())
        viewer.maximum.setText('0.3'); viewer.draw()
        np.testing.assert_allclose(viewer.selected_values, [2.5])
        viewer.quantity.setCurrentText('potential_V')
        np.testing.assert_allclose(viewer.selected_points, points)

    def test_high_field_unevaluated_cells_are_masked_in_saved_array_viewer(self):
        import numpy as np
        from qt_research_results import SavedArrayViewer
        mask = np.array([[[True], [False]], [[True], [True]]])
        values = np.ones((2, 2, 1, 2)); values[0, 1] = 0.
        np.savez(self.root/'highfield.npz', high_field_delta_n=values, high_field_evaluated_mask=mask)
        viewer = SavedArrayViewer(); self.pages.append(viewer); viewer.load_directory(self.root)
        viewer.quantity.setCurrentText('high_field_delta_n')
        self.assertTrue(np.ma.getmaskarray(viewer.displayed)[0, 1])
        self.assertIn('unevaluated values are masked', viewer.note.text())

    def test_embedded_actions_are_hidden_for_existing_and_lazy_study_pages(self):
        bands = self.page(PhotonicBandsWorkspace)
        bands.set_embedded(True)
        self.assertTrue(bands.run_button.isHidden())
        self.assertFalse(bands.status.isHidden())
        bands.set_embedded(False)
        self.assertFalse(bands.run_button.isHidden())
        chooser = self.page(ResearchStudiesWorkspace)
        chooser.set_embedded(True); chooser.select_engine('pcsel')
        self.assertTrue(chooser.stack.currentWidget().run_button.isHidden())
        chooser.select_engine('thermal')
        self.assertTrue(chooser.stack.currentWidget().validate_button.isHidden())

    def test_run_captures_focused_object_inspector_before_validating_or_dispatching(self):
        from PyQt6.QtWidgets import QLineEdit
        page = self.page(PhotonicBandsWorkspace)
        page.select_section('Crystal structure')
        editor = page.primitive_fields['radius']
        editor.setFocus(); editor.setText('unfinished radius')
        with patch.object(self.store, 'start_run') as start:
            page.run()
            start.assert_not_called()
        self.assertEqual(page.geometry.item(0, 3).text(), 'unfinished radius')
        self.assertEqual(self.store.search_state['research_workspaces']['bands']['geometry'][0][3], 'unfinished radius')
        editor.setText('0.27')
        with patch.object(self.store, 'start_run') as start:
            page.run()
        self.assertEqual(start.call_args.args[1]['settings']['geometry'][0]['radius'], .27)


if __name__ == '__main__':
    unittest.main()
