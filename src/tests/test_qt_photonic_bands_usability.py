"""Independent data-preservation and interaction checks for the bands editor.

These exercise user edits and the normal job boundary. Optional solvers are
tested separately in the compiled candidate; this suite does not fake physics.
"""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox, QLineEdit, QScrollArea, QPushButton

from data_library import DataLibrary
from photonic_bands import prepare
from qt_core import ProjectStore
from qt_photonic_bands import PhotonicBandsWorkspace

APP = QApplication.instance() or QApplication([])


def crystal():
    return dict(dimension=2, solver='mpb', lattice_vectors=[[1.2, .3], [-.25, .9]],
        background_epsilon=2.3, reference_length_um=.42, num_bands=5,
        resolution=24, polarizations=['tm'], k_vertices=[[.13, -.07], [.31, .19], [-.2, .4]],
        points_per_segment=7, geometry=[
            dict(id='circle-kept', name='Offset circle', shape='circle', center=[.08, -.12], radius=.17, epsilon=8.),
            dict(id='block-kept', name='Oblique block', shape='block', center=[-.2, .24], size=[.3, .21],
                 axes=[[1., .1], [.2, 1.]], epsilon=4.)],
        runtime=dict(mode='wsl', distro='Explicit user distribution', executable='/usr/bin/mpb', timeout_s=321.))


class PhotonicBandsUsabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods-bands-usability-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(DataLibrary(self.root/'library'), restore=False)
        self.pages = []

    def page(self, store=None):
        page = PhotonicBandsWorkspace(store or self.store)
        page.resize(1280, 860)
        page.show(); APP.processEvents()
        self.pages.append(page)
        return page

    def tearDown(self):
        for page in self.pages:
            page._save_timer.stop()
            page.close(); page.deleteLater()
        APP.processEvents()

    def test_custom_cell_and_off_symmetry_sampling_survive_mode_switches(self):
        page = self.page(); settings = crystal(); page.load_settings(settings)
        self.assertEqual(prepare({}, page.options()['settings']), prepare({}, settings))
        page.grid_counts.setText('5, 3'); page.grid_offset.setText('.17, -.23')
        page.sampling.setCurrentIndex(page.sampling.findData('grid'))
        current = page.options()['settings']
        self.assertEqual(current['k_grid'], dict(counts=[5, 3], offset=[.17, -.23]))
        self.assertNotIn('k_vertices', current)
        page.sampling.setCurrentIndex(page.sampling.findData('points'))
        self.assertEqual(page.options()['settings']['k_points'], settings['k_vertices'])
        page.sampling.setCurrentIndex(page.sampling.findData('path'))
        current = page.options()['settings']
        self.assertEqual(current['k_vertices'], settings['k_vertices'])
        self.assertEqual(current['lattice_vectors'], settings['lattice_vectors'])
        self.assertEqual(current['points_per_segment'], 7)
        self.assertEqual(page.grid_offset.text(), '.17, -.23')

    def test_legacy_raw_draft_retains_invalid_and_inactive_shape_values(self):
        page = self.page(); page.load_settings(crystal())
        draft = page.draft()
        draft['geometry'][0][3] = '1e-'
        draft['geometry'][0][6] = 'inactive cylinder axis text'
        draft['geometry'][1][3] = 'inactive block radius text'
        draft['geometry'][1][5] = 'inactive block height text'
        draft['epsilons']['block-kept'] = 'unfinished epsilon'
        page.restore_draft(copy.deepcopy(draft)); page.flush_draft()
        other = ProjectStore(DataLibrary(self.root/'restored'), restore=False)
        other.load_project(self.store.portable_project())
        restored = self.page(other)
        actual = restored.draft()
        self.assertEqual(actual['geometry'], draft['geometry'])
        self.assertEqual(actual['object_ids'], ['circle-kept', 'block-kept'])
        self.assertEqual(actual['epsilons'], draft['epsilons'])
        self.assertFalse(restored.validate_setup())

    def test_unknown_legacy_shape_is_retained_and_rejected_not_coerced(self):
        page = self.page(); page.load_settings(crystal())
        draft = page.draft(); draft['geometry'][0][1] = 'future_custom_shape'
        page.restore_draft(draft)
        page.flush_draft()
        self.assertEqual(page.draft()['geometry'][0][1], 'future_custom_shape')
        with patch.object(self.store, 'start_run') as start:
            page.run()
        start.assert_not_called()
        self.assertEqual(page.draft()['object_ids'][0], 'circle-kept')

    def test_solver_and_runtime_switches_do_not_replace_explicit_values(self):
        page = self.page(); page.load_settings(crystal())
        page.executable.setText('/opt/user-python/bin/python')
        page.distro.setText('A saved custom distribution')
        page.module_paths.setText('/opt/legume source; /opt/custom modules')
        page.resolution.setText('uncommitted MPB resolution')
        page.gmax.setText('4.75')
        expected = (page.executable.text(), page.distro.text(), page.module_paths.text())
        page.solver.setCurrentIndex(page.solver.findData('legume'))
        page.runtime_mode.setCurrentIndex(page.runtime_mode.findData('local'))
        page.runtime_mode.setCurrentIndex(page.runtime_mode.findData('wsl'))
        self.assertEqual((page.executable.text(), page.distro.text(), page.module_paths.text()), expected)
        self.assertEqual(page.options()['settings']['gmax'], 4.75)
        page.solver.setCurrentIndex(page.solver.findData('mpb'))
        self.assertEqual(page.resolution.text(), 'uncommitted MPB resolution')
        self.assertEqual((page.executable.text(), page.distro.text(), page.module_paths.text()), expected)

    def test_editable_reference_roundtrip_retains_identity_and_shared_device(self):
        from benchmark_registry import editable_copy, prepare_comparison_request
        page = self.page()
        before = copy.deepcopy(self.store.device)
        case = editable_copy('jamois_airholes_2003')
        page.load_settings(case['options']['settings']); page.attach_benchmark(case)
        page.flush_draft()
        other = ProjectStore(DataLibrary(self.root/'reference-reload'), restore=False)
        other.load_project(self.store.portable_project())
        restored = self.page(other)
        request = restored.options()
        snapshot = other.project(); snapshot['benchmark_request'] = restored._benchmark_request
        self.assertFalse(prepare_comparison_request(snapshot, 'research_simulation', request)['input_edited'])
        self.assertEqual(other.device, before)
        with patch.object(other, 'start_run') as start:
            restored.run()
        self.assertEqual(start.call_args.args[0], 'research_simulation')
        self.assertEqual(start.call_args.kwargs['project_snapshot']['benchmark_request']['id'], case['project']['benchmark_request']['id'])
        self.assertEqual(other.device, before)

    def test_shape_inspector_edits_preserve_inactive_text_and_stable_identity(self):
        page = self.page(); page.load_settings(crystal())
        page.geometry.setCurrentCell(0, 0); APP.processEvents()
        radius = page.primitive_fields['radius']
        self.assertTrue(radius.isVisible())
        self.assertFalse(page.primitive_fields['height'].isVisible())
        radius.setFocus(); radius.selectAll(); QTest.keyClicks(radius, '1e-')
        page.primitive_shape.setCurrentIndex(page.primitive_shape.findData('block'))
        APP.processEvents()
        self.assertTrue(page.primitive_fields['size'].isVisible())
        self.assertFalse(radius.isVisible())
        page.primitive_fields['size'].setText('.32, .24')
        self.assertEqual(page.options()['settings']['geometry'][0]['size'], [.32, .24])
        self.assertEqual(page.draft()['geometry'][0][3], '1e-')
        page.geometry.setCurrentCell(1, 0); APP.processEvents()
        page.primitive_fields['epsilon'].setText('7.125')
        page.geometry.setCurrentCell(0, 0); APP.processEvents()
        self.assertEqual(page.primitive_fields['size'].text(), '.32, .24')
        page.primitive_shape.setCurrentIndex(page.primitive_shape.findData('circle'))
        APP.processEvents()
        self.assertEqual(radius.text(), '1e-')
        self.assertFalse(page.validate_setup())
        self.assertEqual(page._object_ids, ['circle-kept', 'block-kept'])
        self.assertEqual(page.draft()['epsilons']['block-kept'], '7.125')

    def test_diagnostics_reveal_exact_visible_inspector_and_table_controls(self):
        page = self.page(); page.load_settings(crystal())
        for identity, field in [('circle-kept', 'radius'), ('block-kept', 'epsilon'), ('block-kept', 'axes')]:
            with self.subTest(field=field):
                page.select_section('Review & Run')
                self.assertTrue(page.open_diagnostic(dict(workspace='photonic_bands',object_id=identity,field=field)))
                APP.processEvents()
                widget = page.primitive_fields[field]
                self.assertTrue(widget.isVisible())
                self.assertIs(APP.focusWidget(), widget)
                self.assertEqual(page._object_ids[page.geometry.currentRow()], identity)
        page.select_section('Review & Run')
        self.assertTrue(page.open_diagnostic(dict(workspace='photonic_bands',field='lattice_vectors.1.0')))
        APP.processEvents()
        self.assertTrue(page.lattice.isVisible())
        self.assertEqual((page.lattice.currentRow(), page.lattice.currentColumn()), (1, 0))
        self.assertTrue(page.open_diagnostic(dict(workspace='photonic_bands',field='runtime.executable')))
        APP.processEvents()
        self.assertTrue(page.executable.isVisible())
        self.assertIs(APP.focusWidget(), page.executable)
        for field, widget in [('tolerance', page.tolerance), ('runtime.timeout_s', page.timeout)]:
            page.advanced_solver_toggle.setChecked(False)
            page.select_section('Review & Run')
            self.assertTrue(page.open_diagnostic(dict(workspace='photonic_bands', field=field)))
            APP.processEvents()
            self.assertTrue(widget.isVisible())
            self.assertIs(APP.focusWidget(), widget)

    def test_focused_inspector_text_is_saved_and_validated_before_run(self):
        page = self.page(); page.load_settings(crystal())
        page.geometry.setCurrentCell(0, 0); APP.processEvents()
        radius = page.primitive_fields['radius']
        radius.setFocus(); radius.selectAll(); QTest.keyClicks(radius, 'unfinished')
        page.flush_draft()
        self.assertEqual(self.store.search_state['research_workspaces']['bands']['geometry'][0][3], 'unfinished')
        with patch.object(self.store, 'start_run') as start:
            page.run()
        start.assert_not_called()
        radius.setFocus(); radius.selectAll(); QTest.keyClicks(radius, '.27')
        with patch.object(self.store, 'start_run') as start:
            page.run()
        self.assertEqual(start.call_args.args[1]['settings']['geometry'][0]['radius'], .27)
        self.assertEqual(start.call_args.args[1]['settings']['geometry'][0]['id'], 'circle-kept')

    def test_preview_works_with_unfinished_runtime_without_changing_draft(self):
        page = self.page(); page.load_settings(crystal())
        page.executable.setText(''); page.num_bands.setText('1e-')
        before = copy.deepcopy(page.draft())
        with patch('photonic_bands.execute', side_effect=AssertionError('Preview must not run a solver')):
            page.preview_geometry()
        self.assertGreaterEqual(len(page.preview.figure.axes[0].patches), 3)
        self.assertEqual(page.draft(), before)

    def test_imported_legume_library_folders_survive_edit_and_project_reload(self):
        settings = crystal(); settings.update(solver='legume', gmax=3.5)
        settings['runtime'] = dict(mode='local',executable='C:/explicit/python.exe',timeout_s=456.,
            module_paths=['C:/Legume source','C:/other module'], library_paths=['C:/explicit library folder'])
        page = self.page(); page.load_settings(settings)
        self.assertEqual(page.options()['settings']['runtime']['library_paths'], settings['runtime']['library_paths'])
        page.flush_draft()
        other = ProjectStore(DataLibrary(self.root/'runtime-reload'), restore=False)
        other.load_project(self.store.portable_project())
        restored = self.page(other)
        self.assertEqual(prepare({}, restored.options()['settings']), prepare({}, settings))

    def test_lattice_preset_requires_explicit_application_and_keeps_objects(self):
        page = self.page(); settings = crystal(); page.load_settings(settings)
        before = page.options()['settings']
        index = page.lattice_preset.findData('square')
        self.assertGreaterEqual(index, 0)
        page.lattice_preset.setCurrentIndex(index)
        self.assertEqual(page.options()['settings'], before)
        page.apply_lattice_preset()
        after = page.options()['settings']
        self.assertEqual(after['lattice_vectors'], [[1., 0.], [0., 1.]])
        self.assertNotEqual(after['k_vertices'], before['k_vertices'])
        self.assertEqual(after['geometry'], before['geometry'])

    def test_dimension_switch_preserves_full_3d_geometry_and_lattice_draft(self):
        settings = crystal()
        settings.update(dimension=3, lattice_vectors=[[1.1,0.,.2],[.1,1.3,0.],[0.,.2,1.2]],
            k_vertices=[[.03,.04,.05],[.2,.1,.3]],polarizations=['vector'],
            geometry=[dict(id='tilted-cylinder',name='Tilted cylinder',shape='cylinder',center=[.1,-.2,.3],
                radius=.12,height=.44,axis=[.3,.4,.5],epsilon=8.)])
        page = self.page(); page.load_settings(settings)
        before = page.draft()
        page.dimension.setCurrentIndex(page.dimension.findData(2))
        page.dimension.setCurrentIndex(page.dimension.findData(3))
        self.assertEqual(page.draft()['geometry'],before['geometry'])
        self.assertEqual(page.draft()['lattice'],before['lattice'])
        self.assertEqual(page.draft()['kpoints'],before['kpoints'])
        self.assertEqual(page._object_ids,['tilted-cylinder'])
        self.assertEqual(prepare({},page.options()['settings']),prepare({},settings))

    def test_legume_overlap_diagnostic_selects_the_affected_visible_object(self):
        page = self.page(); settings = crystal(); page.load_settings(settings)
        page.geometry.item(1, 1).setText('circle')
        page.geometry.item(1, 2).setText('.08, -.12')
        page.geometry.item(1, 3).setText('.1')
        page.solver.setCurrentIndex(page.solver.findData('legume'))
        page.executable.setText('/usr/bin/python3')
        self.assertFalse(page.validate_setup())
        issue = page.diagnostics.list.item(0).data(Qt.ItemDataRole.UserRole)
        self.assertEqual(issue['code'], 'unsupported_periodic_overlap')
        self.assertEqual(issue['object_id'], 'block-kept')
        self.assertIn('Use MPB or separate the objects', issue['message'])
        self.assertTrue(page.open_diagnostic(issue)); APP.processEvents()
        self.assertTrue(page.primitive_fields['center'].isVisible())
        self.assertIs(APP.focusWidget(),page.primitive_fields['center'].components[0])
        self.assertEqual(page._object_ids[page.geometry.currentRow()],'block-kept')

    def test_tilted_3d_block_scene_uses_full_axis_lengths_and_third_extent(self):
        settings = crystal()
        settings.update(dimension=3, lattice_vectors=[[1.,.1,.5],[.2,1.1,.1],[.3,.4,1.]],
            k_vertices=[[0.,0.,0.],[.2,.1,.3]], polarizations=['vector'],
            geometry=[dict(id='tilted-block', name='Tilted block', shape='block', center=[0.,0.,0.],
                size=[.2,.4,.6], axes=[[1.,0.,1.],[0.,1.,1.],[1.,1.,0.]], epsilon=8.)])
        page = self.page(); page.load_settings(settings); before = page.draft()
        page.preview_geometry()
        scene = page.crystal_3d.scene
        self.assertIs(page.scene_stack.currentWidget(),page.crystal_3d)
        xy = scene['meshes'][0]['faces'].reshape(-1,3)
        # Half-widths include the tilted third edge as well as the first two.
        self.assertAlmostEqual(max(xy[:,0]), .4/(2**.5))
        self.assertAlmostEqual(min(xy[:,0]), -.4/(2**.5))
        self.assertAlmostEqual(max(xy[:,1]), .5/(2**.5))
        self.assertAlmostEqual(min(xy[:,1]), -.5/(2**.5))
        self.assertAlmostEqual(max(scene['cell_edges'].reshape(-1,3)[:,0]), .75)
        self.assertAlmostEqual(max(scene['cell_edges'].reshape(-1,3)[:,1]), .8)
        self.assertEqual(page.draft(), before)

    def test_three_stage_template_scale_and_3d_scene_are_explicit_editable_inputs(self):
        page = self.page(); device = copy.deepcopy(self.store.device)
        self.assertEqual(page.dimension.currentData(),3)
        self.assertEqual(page.options()['settings']['polarizations'],['vector'])
        self.assertEqual(page._crystal_stage,'unit')
        before = page.options()['settings']
        page.crystal_template.setCurrentIndex(page.crystal_template.findData('diamond'))
        self.assertEqual(page.options()['settings'],before)
        page.apply_crystal_template(); page.preview_geometry(); APP.processEvents()
        self.assertEqual(page.repeat_cells.currentData(),3)
        self.assertEqual(page.crystal_3d.scene['primitive_count'],2)
        self.assertEqual(len(page.crystal_3d.scene['meshes']),54)
        self.assertEqual(page.options()['settings']['lattice_vectors'],[[0.,.5,.5],[.5,0.,.5],[.5,.5,0.]])
        geometry = copy.deepcopy(page.options()['settings']['geometry'])
        page.scale_nm.setText('600')
        self.assertAlmostEqual(page.options()['settings']['reference_length_um'],.6)
        self.assertEqual(page.options()['settings']['geometry'],geometry)
        self.assertEqual(self.store.device,device)
        for stage in ('build','calculate','unit'):
            page.show_stage(stage); APP.processEvents()
            self.assertTrue(page.stage_buttons[stage].isChecked())

    def test_3d_click_opens_exact_object_inspector_and_invalid_edit_keeps_last_scene(self):
        page = self.page(); page.preview_geometry(); APP.processEvents()
        viewer = page.crystal_3d
        center,_ = viewer.project([0.,0.,0.])
        QTest.mouseClick(viewer,Qt.MouseButton.LeftButton,pos=QPoint(round(center[0]),round(center[1])))
        APP.processEvents()
        self.assertEqual(page._crystal_stage,'build')
        self.assertEqual(page._object_ids[page.geometry.currentRow()],viewer.selected_id)
        self.assertTrue(page.primitive_fields['radius'].isVisible())
        page.primitive_fields['center'].components[2].setText('.11')
        page.preview_geometry()
        self.assertEqual(page.options()['settings']['geometry'][0]['center'],[0.,0.,.11])
        previous = viewer.scene
        page.primitive_fields['radius'].setText('unfinished')
        page.preview_geometry()
        self.assertIs(viewer.scene,previous)
        self.assertIn('out of date',page.preview_note.text())
        self.assertEqual(page.draft()['geometry'][0][3],'unfinished')

    def test_cartesian_diagnostic_focuses_exact_component_or_preserved_raw_draft(self):
        page = self.page(); identity = page._object_ids[0]
        page.show_stage('calculate')
        target = dict(workspace='photonic_bands',object_id=identity,field='geometry.0.center.2')
        self.assertTrue(page.open_diagnostic(target)); APP.processEvents()
        vector_edit = page.primitive_fields['center']
        self.assertIs(APP.focusWidget(),vector_edit.components[2])
        self.assertTrue(vector_edit.components[2].isVisible())
        vector_edit.setText('unfinished four component draft')
        page.show_stage('calculate')
        self.assertTrue(page.open_diagnostic(target)); APP.processEvents()
        self.assertIs(APP.focusWidget(),vector_edit.raw)
        self.assertEqual(vector_edit.raw.text(),'unfinished four component draft')

    def test_3d_calculation_dispatch_uses_active_cartesian_component_and_nm_scale(self):
        page = self.page(); page.show_stage('build')
        page.scale_nm.setText('625'); page.primitive_fields['radius'].setText('.29')
        component = page.primitive_fields['center'].components[0]
        component.setFocus(); component.selectAll(); QTest.keyClicks(component,'.07')
        page.num_bands.setText('4'); page.resolution.setText('12')
        page.runtime_mode.setCurrentIndex(page.runtime_mode.findData('wsl'))
        page.distro.setText('Explicit installed distribution'); page.executable.setText('mpb')
        with patch.object(self.store,'start_run',return_value='job') as run:
            page.run()
        self.assertEqual(run.call_args.args[0],'research_simulation')
        settings = run.call_args.args[1]['settings']
        self.assertEqual(settings['dimension'],3); self.assertEqual(settings['polarizations'],['vector'])
        self.assertEqual(settings['geometry'][0]['center'],[.07,0.,0.])
        self.assertEqual(settings['geometry'][0]['radius'],.29)
        self.assertAlmostEqual(settings['reference_length_um'],.625)

    def test_template_description_does_not_mislabel_imported_or_saved_custom_geometry(self):
        page=self.page()
        page.crystal_template.setCurrentIndex(page.crystal_template.findData('diamond'))
        page.apply_crystal_template()
        self.assertEqual(page.crystal_template.currentData(),'diamond')
        self.assertIn('diamond',page.template_note.text().lower())
        expected=prepare({},page.options()['settings']);page.flush_draft()
        other=ProjectStore(DataLibrary(self.root/'template-reload'),restore=False)
        other.load_project(self.store.portable_project());restored=self.page(other)
        self.assertEqual(prepare({},restored.options()['settings']),expected)
        self.assertEqual(restored.crystal_template.currentData(),'custom')
        self.assertNotIn('diamond network',restored.template_note.text().lower())
        page.load_settings(crystal())
        self.assertEqual(page.crystal_template.currentData(),'custom')
        self.assertNotIn('diamond network',page.template_note.text().lower())
        self.assertEqual(page.options()['settings']['lattice_vectors'],crystal()['lattice_vectors'])


class PhotonicBandsWindowRouteTests(unittest.TestCase):
    def test_dedicated_band_actions_preserve_other_routes_and_progress_messages(self):
        from qt_app import OpticalStudio
        from PyQt6.QtCore import QCoreApplication, QEvent
        with tempfile.TemporaryDirectory(prefix='ods-bands-route-',dir=Path.cwd()) as folder:
            store = ProjectStore(DataLibrary(Path(folder)/'library'),restore=False)
            window = OpticalStudio(store)
            try:
                window.resize(1366, 900); window.show(); APP.processEvents()
                window._navigate_route(10); APP.processEvents()
                self.assertEqual(window.run_button.text(), 'Calculate bands')
                self.assertEqual(window.footer_validate.text(), 'Check inputs')
                self.assertEqual(window._idle_workspace_description(), 'Photonic Bands · independent periodic crystal')
                with patch.object(window.photonic_bands_page, 'run') as run:
                    window.run_button.click()
                    run.assert_called_once_with()
                window.status.setText('Solver status that must remain visible')
                window._sync_run_actions()
                self.assertEqual(window.status.text(), 'Solver status that must remain visible')
                window._navigate_route(11)
                self.assertEqual(window.run_button.text(), 'Run simulation')
                self.assertEqual(window.footer_validate.text(), 'Check inputs')
                window._navigate_route(2, 0)
                self.assertEqual(window.run_button.text(), 'Run optical simulation')
                # Exercise the actual host-width constraint, not a standalone
                # page that has more room than an 800px application window.
                window._navigate_route(10); window.resize(800,760); window.adapt_interface(); QTest.qWait(200)
                page = window.photonic_bands_page
                def reachable(control):
                    ancestors=[]; current=control.parentWidget()
                    while current is not None:
                        if isinstance(current,QScrollArea):ancestors.append(current)
                        current=current.parentWidget()
                    for area in ancestors:
                        area.ensureWidgetVisible(control,0,8); QTest.qWait(30)
                    self.assertTrue(control.isVisible())
                    for area in ancestors:
                        viewport=area.viewport()
                        x=control.mapTo(viewport,QPoint()).x()
                        self.assertGreaterEqual(x,-1)
                        self.assertLessEqual(x+control.width(),viewport.width()+1)
                        self.assertEqual(area.horizontalScrollBar().maximum(),0)
                def caption(form,control):
                    label=form.labelForField(control)
                    self.assertIsNotNone(label)
                    self.assertTrue(label.isVisible())
                    self.assertGreaterEqual(label.width(),min(80,label.fontMetrics().horizontalAdvance(label.text())))
                    self.assertGreaterEqual(label.height(),label.fontMetrics().height())
                    reachable(label)
                def scene_toolbar():
                    controls=[page.view_direction,page.repeat_cells,
                        next(b for b in page.preview_body.findChildren(QPushButton) if b.text()=='Reset view')]
                    bounds=[]
                    for control in controls:
                        self.assertTrue(control.isVisible())
                        self.assertGreaterEqual(control.width(),50)
                        rect=control.rect().translated(control.mapTo(page.preview_body,QPoint()))
                        self.assertGreaterEqual(rect.left(),0)
                        self.assertLessEqual(rect.right(),page.preview_body.width())
                        self.assertFalse(any(rect.intersects(previous) for previous in bounds))
                        bounds.append(rect)
                page.show_stage('unit'); QTest.qWait(100); reachable(page.scale_nm)
                caption(page.unit_form,page.scale_nm);caption(page.unit_form,page.dimension);scene_toolbar()
                page.crystal_template.setCurrentIndex(page.crystal_template.findData('diamond'))
                page.apply_crystal_template(); page.show_stage('build'); APP.processEvents()
                radius=page.primitive_fields['radius']; reachable(radius)
                for field in ('name','center','radius','epsilon'):
                    caption(page.primitive_form,page.primitive_fields[field])
                scene_toolbar()
                self.assertEqual(radius.cursorPosition(),0)
                full_value=radius.text(); self.assertTrue(full_value.startswith('0.233'))
                radius.setFocus(); radius.selectAll(); self.assertEqual(radius.selectedText(),full_value)
                page.show_stage('calculate'); APP.processEvents(); reachable(page.num_bands)
                caption(page.solver_form,page.num_bands);caption(page.solver_form,page.resolution)
                page.runtime_setup_toggle.setChecked(True); APP.processEvents(); reachable(page.executable)
                caption(page.runtime_form,page.executable)
            finally:
                window.hide(); window.deleteLater(); APP.processEvents()
                QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
if __name__ == '__main__':
    unittest.main()
