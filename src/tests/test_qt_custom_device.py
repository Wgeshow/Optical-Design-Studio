"""Canonical builder editing and linked-canvas interaction contracts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from device_model import default_device, find_object, validate_device
from electrical_material_library import builtin_materials, validate_materials
from qt_custom_device import CustomDevicePage, _section_intervals, _shape_section_intervals

APP = QApplication.instance() or QApplication([])


class _Store(QObject):
    changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.electrical_materials = builtin_materials()
        self.device = default_device(self.electrical_materials)

    def set_device(self, device):
        self.device = validate_device(device, self.electrical_materials)
        self.changed.emit('device')

    def set_electrical_materials(self, materials):
        self.electrical_materials = validate_materials(materials)
        self.changed.emit('electrical_materials')


class CustomDevicePageTests(unittest.TestCase):
    def setUp(self):
        self.store = _Store()
        self.page = CustomDevicePage(self.store, include_advanced=False)
        self.page.resize(1440, 900)
        self.page.show()
        APP.processEvents()

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        APP.processEvents()

    def test_large_pc_array_remains_selectable_and_editable_outside_tree_budget(self):
        from pc_array import apply_pc_array
        device=copy.deepcopy(self.store.device)
        device.update(width_um=150.,depth_um=150.)
        device=apply_pc_array(device,dict(id='large',name='Large PC',layer_id=device['layers'][0]['id'],
            cx_um=0.,cy_um=0.,width_um=100.,depth_um=100.,cell_width_um=.444,cell_depth_um=.444,radius_um=.09),material_library=self.store.electrical_materials)
        self.store.set_device(device);APP.processEvents()
        self.assertEqual(len(self.store.device['shapes']),50625)
        self.assertLess(self.page.tree_listed_count,650)
        self.assertIn('Coarse 3D',self.page.view_3d.lod_note)
        remote=self.store.device['shapes'][-1]
        point=self.page.top_view.screen_point(remote['cx_um'],remote['cy_um'])
        self.assertEqual(self.page.top_view._hit(point)[0],remote['id'])
        self.page.focus_object(remote['id']);APP.processEvents()
        point=self.page.top_view.screen_point(remote['cx_um'],remote['cy_um']).toPoint()
        QTest.mouseClick(self.page.top_view,Qt.MouseButton.LeftButton,pos=point)
        APP.processEvents()
        self.assertEqual(self.page.selected_id,remote['id'])
        self.assertEqual(self.page.object_tree.currentItem().data(0,Qt.ItemDataRole.UserRole),remote['id'])
        self.assertGreater(self.page.top_view.zoom,1.)
        self.assertTrue(any(obj['id']==remote['id'] for obj in self.page.top_view._render_shapes))
        old_x=remote['cx_um'];self.page.geometry_controls['cx_um'].setValue(old_x+.002)
        self.assertTrue(self.page.apply_inspector())
        self.assertAlmostEqual(find_object(self.store.device,remote['id'])['cx_um'],old_x+.002)
        self.assertEqual(len(self.store.device['shapes']),50625)

    def test_pc_dialog_return_commits_editor_without_filling_and_cell_import_is_independent(self):
        from PyQt6.QtWidgets import QDialogButtonBox
        self.store.settings={'ax_um':2.,'ay_um':2.,'optical_unit_cell':{'enabled':False,'width_um':.45,'depth_um':.45}}
        def edit_and_fill():
            controls=self.page.pc_area_controls
            controls['width_um'].setValue(1.35);controls['depth_um'].setValue(1.35)
            self.page.pc_area_import_cell.click()
            controls['width_um'].setFocus();QTest.keyClick(controls['width_um'],Qt.Key.Key_Return)
            self.assertTrue(self.page.pc_area_dialog.isVisible())
            self.assertEqual(len(self.store.device['shapes']),0)
            self.assertEqual(self.page.pc_area_plan['hole_count'],9)
            self.page.pc_area_button_box.button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(0,edit_and_fill)
        self.page.pc_area()
        self.assertEqual(len(self.store.device['shapes']),9)
        self.assertEqual(self.store.device['width_um'],2.)
        self.assertFalse(self.store.settings['optical_unit_cell']['enabled'])
        metadata=self.store.device['pc_arrays'][0]
        self.page.select_object(metadata['id'])
        self.assertTrue(self.page.edit_pc_area_button.isVisible())
        self.page.delete_selected()
        self.assertEqual(self.store.device['shapes'],[])
        self.assertEqual(self.store.device['pc_arrays'],[])

    def test_initialization_preserves_actual_device_and_links_selection(self):
        expected = default_device(self.store.electrical_materials)
        self.assertEqual(self.store.device, expected)
        selected = self.store.device['layers'][2]['id']
        self.page.select_object(selected)
        self.assertEqual(self.page.active_layer_id, selected)
        self.assertEqual([canvas.selected for canvas in (self.page.top_view, self.page.section_view, self.page.view_3d)], [selected]*3)
        self.assertTrue(self.page.top_view.hits)
        self.assertIsNotNone(self.page.export_button.menu())
        self.assertTrue(any('JSON' in action.text() for action in self.page.export_button.menu().actions()))

    def test_layer_inspector_updates_material_thickness_and_doping_atomically(self):
        selected = self.store.device['layers'][0]['id']
        self.page.select_object(selected)
        self.page.name_edit.setText('Custom silicon')
        self.page.material_edit.setCurrentIndex(self.page.material_edit.findData('silicon'))
        self.page.thickness_edit.setValue(.23)
        self.page.donor_edit.setText('8e17')
        self.page.acceptor_edit.setText('0')
        self.page.apply_inspector()
        layer = find_object(self.store.device, selected)
        self.assertEqual((layer['name'], layer['material_id'], layer['thickness_um'], layer['donor_cm3']), ('Custom silicon', 'silicon', .23, 8e17))
        before = copy.deepcopy(self.store.device)
        self.page.acceptor_edit.setText('nan')
        self.page.apply_inspector()
        self.assertEqual(self.store.device, before)

    def test_toolbar_shapes_have_real_ids_and_boolean_moves_and_extrusion_persist(self):
        self.page.add_shape('circle')
        object_id = self.page.selected_id
        obj = find_object(self.store.device, object_id)
        self.assertEqual(obj['shape'], 'circle')
        self.page.boolean.setCurrentIndex(self.page.boolean.findData('void'))
        self.assertEqual(find_object(self.store.device, object_id)['operation'], 'void')
        self.page.move_object(object_id, .2, -.1)
        obj = find_object(self.store.device, object_id)
        self.assertAlmostEqual(obj['cx_um'], .2)
        self.assertAlmostEqual(obj['cy_um'], -.1)
        target = self.store.device['layers'][1]['id']
        self.page.extrude_to_layers([obj['layer_id'], target])
        self.assertEqual(len(self.store.device['shapes']), 2)
        self.assertEqual(self.store.device['shapes'][1]['layer_id'], target)
        self.page.undo_device()
        self.assertEqual(len(self.store.device['shapes']), 1)

    def test_canvas_drag_draws_an_actual_shape_with_physical_dimensions(self):
        canvas = self.page.top_view
        self.page.set_tool('rectangle')
        start = canvas.screen_point(-.3, -.2).toPoint()
        stop = canvas.screen_point(.3, .2).toPoint()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, stop)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=stop)
        self.assertEqual(len(self.store.device['shapes']), 1)
        obj = self.store.device['shapes'][0]
        self.assertAlmostEqual(obj['size_x_um'], .6, delta=.02)
        self.assertAlmostEqual(obj['size_y_um'], .4, delta=.02)
        self.assertEqual(canvas.selected, obj['id'])

    def test_contact_surface_assignment_and_doping_regions_are_editable(self):
        self.page.add_contact()
        contact_id = self.page.selected_id
        bottom = self.store.device['layers'][-1]['id']
        self.page.assign_contact_surface(bottom, 'bottom')
        contact = find_object(self.store.device, contact_id)
        self.assertEqual((contact['layer_id'], contact['surface']), (bottom, 'bottom'))
        self.page.contact_controls['voltage_V'].setValue(-1.2)
        self.page.apply_inspector()
        self.assertEqual(find_object(self.store.device, contact_id)['voltage_V'], -1.2)
        self.page.add_doping()
        self.page.donor_edit.setText('3e18')
        self.page.apply_inspector()
        self.assertEqual(self.store.device['doping_regions'][0]['donor_cm3'], 3e18)

    def test_contact_base_voltage_above_old_limit_is_preserved(self):
        self.page.add_contact()
        contact_id = self.page.selected_id
        self.page.contact_controls['boundary'].setCurrentIndex(self.page.contact_controls['boundary'].findData('potential'))
        self.page.contact_controls['voltage_V'].setValue(500.)
        self.assertTrue(self.page.apply_inspector())
        self.assertEqual(find_object(self.store.device, contact_id)['voltage_V'], 500.)
        self.page.select_object(self.store.device['layers'][0]['id'])
        self.page.select_object(contact_id)
        self.assertEqual(self.page.contact_controls['voltage_V'].value(), 500.)

    def test_optical_contact_metal_persists_without_changing_electrical_boundary(self):
        self.store.materials = [{'Name': 'Air'}, {'Name': 'Au'}]
        contact_id = self.store.device['contacts'][-1]['id']
        self.page.select_object(contact_id)
        controls = self.page.optical_contact_controls
        self.assertEqual(controls['material'].currentData(), '')
        self.assertEqual(controls['thickness'].value(), 0.)
        before = copy.deepcopy(find_object(self.store.device, contact_id))
        controls['material'].setCurrentIndex(controls['material'].findData('Au'))
        controls['thickness'].setValue(.03)
        QTest.mouseClick(self.page.apply_button, Qt.MouseButton.LeftButton)
        contact = find_object(self.store.device, contact_id)
        self.assertEqual((contact['optical_material_name'], contact['optical_thickness_um']), ('Au', .03))
        for key in ('layer_id', 'surface', 'boundary', 'voltage_V', 'shape', 'size_x_um', 'size_y_um'):
            self.assertEqual(contact[key], before[key])
        self.page.select_object('device')
        self.page.select_object(contact_id)
        self.assertEqual(controls['material'].currentData(), 'Au')
        self.assertEqual(controls['thickness'].value(), .03)
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory)/'optical-contact.json'
            with patch('qt_custom_device.QFileDialog.getSaveFileName', return_value=(str(filename), '')):
                self.page.export_device()
            exported = json.loads(filename.read_text(encoding='utf-8'))
            self.assertEqual(find_object(exported, contact_id)['optical_thickness_um'], .03)
            controls['material'].setCurrentIndex(controls['material'].findData(''))
            controls['thickness'].setValue(0.)
            self.page.apply_inspector()
            self.assertTrue(self.page.import_geometry_file(filename))
            restored = find_object(self.store.device, contact_id)
            self.assertEqual((restored['optical_material_name'], restored['optical_thickness_um']), ('Au', .03))
        self.store.materials = [{'Name': 'Air'}]
        self.page.select_object(contact_id)
        self.assertEqual(controls['material'].currentData(), 'Au')
        self.assertIn('missing', controls['material'].currentText())

    def test_optical_contact_fields_validate_finite_thickness_and_text(self):
        for invalid in (-.03, float('nan'), float('inf')):
            device = copy.deepcopy(self.store.device)
            device['contacts'][0]['optical_thickness_um'] = invalid
            with self.assertRaisesRegex(ValueError, 'optical contact thickness'):
                validate_device(device, self.store.electrical_materials)
        device = copy.deepcopy(self.store.device)
        device['contacts'][0]['optical_material_name'] = 123
        with self.assertRaisesRegex(ValueError, 'optical material name must be text'):
            validate_device(device, self.store.electrical_materials)

    def test_reference_workspace_menu_and_optical_tab_are_functional(self):
        self.assertFalse(self.page.tabs.tabBar().isVisible())
        self.assertEqual(self.page.inspector_tabs.count(),3)
        self.assertTrue(self.page.tool_buttons['select'].isChecked())
        self.assertEqual(len(self.page.library_buttons),5)
        self.store.materials=[{'Name':'Air'},{'Name':'Au'}]
        layer_id=self.store.device['layers'][0]['id']
        self.page.select_object(layer_id)
        self.page.inspector_tabs.setCurrentIndex(2)
        APP.processEvents()
        self.assertTrue(self.page.optical_assignment.isVisible())
        self.page.optical_assignment.setCurrentIndex(self.page.optical_assignment.findData('Au'))
        QTest.mouseClick(self.page.apply_button,Qt.MouseButton.LeftButton)
        self.assertEqual(find_object(self.store.device,layer_id)['optical_material_name'],'Au')
        before=len(self.store.device['layers'])
        self.page.activateWindow();QTest.qWait(20)
        clicked=[]
        def duplicate_from_menu():
            clicked.append(self.page.action_buttons['duplicate'].isVisible())
            QTest.mouseClick(self.page.action_buttons['duplicate'],Qt.MouseButton.LeftButton)
            self.page.tree_actions.close()
        QTimer.singleShot(40,duplicate_from_menu)
        QTest.mouseClick(self.page.tree_menu_button,Qt.MouseButton.LeftButton)
        APP.processEvents()
        self.assertEqual(clicked,[True])
        self.assertEqual(len(self.store.device['layers']),before+1)
        self.page.material_search.setText('Silicon')
        APP.processEvents()
        self.assertEqual(len(self.page.library_buttons),2)
        self.assertEqual(self.page.library_buttons[0].material_id,'silicon')

    def test_contact_electrical_tab_edits_real_position_size_name_and_optical_height(self):
        self.store.materials=[{'Name':'Au'}]
        contact_id=self.store.device['contacts'][-1]['id']
        self.page.select_object(contact_id)
        self.page.inspector_tabs.setCurrentIndex(2)
        self.page.optical_contact_controls['material'].setCurrentIndex(self.page.optical_contact_controls['material'].findData('Au'))
        self.page.inspector_tabs.setCurrentIndex(1)
        self.page.contact_position_controls['cx_um'].setValue(.15)
        self.page.contact_position_controls['size_x_um'].setValue(1.5)
        self.page.contact_position_controls['size_y_um'].setValue(1.4)
        self.page.contact_height_edit.setValue(.03)
        self.page.activateWindow();QTest.qWait(20)
        QTest.mouseClick(self.page.contact_terminal_name,Qt.MouseButton.LeftButton)
        QTest.keyClick(self.page.contact_terminal_name,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(self.page.contact_terminal_name,'P metal')
        QTest.keyClick(self.page.contact_terminal_name,Qt.Key.Key_Tab)
        QTest.mouseClick(self.page.apply_button,Qt.MouseButton.LeftButton)
        obj=find_object(self.store.device,contact_id)
        self.assertEqual((obj['name'],obj['cx_um'],obj['size_x_um'],obj['size_y_um']),('P metal',.15,1.5,1.4))
        self.assertEqual((obj['optical_material_name'],obj['optical_thickness_um']),('Au',.03))
        self.assertTrue(self.page.contact_surface_z.isReadOnly())
        self.assertEqual(self.page.contact_surface_z.value(),0.)

    def test_delete_layer_removes_dependents_and_undo_restores_them(self):
        selected = self.page.active_layer_id
        self.page.add_shape()
        self.page.select_object(selected)
        before = copy.deepcopy(self.store.device)
        self.page.delete_selected()
        self.assertNotIn(selected, [layer['id'] for layer in self.store.device['layers']])
        self.assertFalse(any(obj['layer_id'] == selected for kind in ('shapes', 'contacts', 'doping_regions') for obj in self.store.device[kind]))
        self.page.undo_device()
        self.assertEqual(self.store.device, before)

    def test_mesh_edits_change_the_canonical_mesh_and_preview(self):
        self.page.select_object('mesh')
        self.page.mesh_controls['nx'].setValue(12)
        self.page.mesh_controls['ny'].setValue(14)
        self.page.apply_inspector()
        self.assertEqual(self.store.device['mesh']['nx'], 12)
        self.assertEqual(self.store.device['mesh']['ny'], 14)
        self.page.mesh_preview.setChecked(True)
        self.assertTrue(self.page.top_view.show_mesh)

    def test_fine_mesh_controls_keep_counts_and_automatic_budget(self):
        from electrical_mesh import MESH_AXIS_MAX
        self.page.select_object('mesh')
        for key in ('nx','ny','nz_per_layer'):
            self.assertEqual(self.page.mesh_controls[key].maximum(),MESH_AXIS_MAX)
        self.assertEqual(self.page.mesh_controls['max_nodes'].minimum(),0)
        self.assertEqual(self.page.mesh_controls['max_nodes'].specialValueText(),'Automatic (RAM budget)')
        with patch('custom_electrical_solver.build_mesh',side_effect=AssertionError('Inspector must not allocate a mesh')):
            self.page.mesh_controls['max_nodes'].setValue(0)
            self.page.mesh_controls['nx'].setValue(320)
            self.page.mesh_controls['ny'].setValue(320)
            self.page.mesh_controls['nz_per_layer'].setValue(12)
            self.assertTrue(self.page.apply_inspector())
        self.assertEqual(self.store.device['mesh']['nx'],320)
        self.assertEqual(self.store.device['mesh']['ny'],320)
        self.assertEqual(self.store.device['mesh']['max_nodes'],0)
        self.assertIn('Planning estimate',self.page.mesh_resource_note.text())
        self.assertIn('Jacobi-scaled CG',self.page.mesh_resource_note.text())

    def test_device_and_geometry_json_import_are_validated_before_committing(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / 'geometry.json'
            filename.write_text(json.dumps([{'name': 'Imported ellipse', 'shape': 'ellipse', 'size_x_um': .8, 'size_y_um': .4}]), encoding='utf-8')
            self.assertTrue(self.page.import_geometry_file(filename))
            self.assertEqual(self.store.device['shapes'][0]['name'], 'Imported ellipse')
            before = copy.deepcopy(self.store.device)
            filename.write_text(json.dumps({'layers': []}), encoding='utf-8')
            self.assertFalse(self.page.import_geometry_file(filename))
            self.assertEqual(self.store.device, before)

    def test_polygon_section_uses_actual_intersections(self):
        self.assertEqual(_section_intervals([[-1., -1.], [1., -1.], [1., 1.], [-1., 1.]], 0.), [(-1., 1.)])
        self.assertEqual(_section_intervals([[-1., -1.], [1., -1.], [1., 1.], [-1., 1.]], 2.), [])

    def test_polygon_move_updates_the_same_geometry_seen_by_the_solver(self):
        from device_model import geometry_vertices, shape_mask
        self.page.add_shape('polygon')
        object_id = self.page.selected_id
        before = geometry_vertices(find_object(self.store.device, object_id))
        self.page.move_object(object_id, .2, .1)
        moved = find_object(self.store.device, object_id)
        after = geometry_vertices(moved)
        self.assertAlmostEqual(after[0][0]-before[0][0], .2)
        self.assertAlmostEqual(after[0][1]-before[0][1], .1)
        self.assertTrue(shape_mask(moved, .2, .1))

    def test_side_contact_picker_snaps_to_the_actual_device_boundary(self):
        self.page.add_contact()
        object_id = self.page.selected_id
        self.page.assign_contact_surface(self.page.active_layer_id, 'side_x_min')
        contact = find_object(self.store.device, object_id)
        self.assertEqual(contact['surface'], 'side_x_min')
        self.assertEqual(contact['cx_um'], -self.store.device['width_um']/2)

    def test_run_validates_mesh_and_dispatches_current_canonical_device(self):
        self.store.start_run = Mock()
        self.page.run()
        self.store.start_run.assert_called_once_with('electrical', dict(model='custom_device', biases_V=[0.],
            optical_enabled=False, charge_model='semiconductor'))
        before = copy.deepcopy(self.store.device)
        self.page.donor_edit.setText('nan')
        self.page.run()
        self.assertEqual(self.store.start_run.call_count, 1)
        self.assertEqual(self.store.device, before)

    def test_square_ring_is_one_contact_with_a_true_open_center(self):
        from device_model import shape_mask
        self.page.add_contact()
        object_id = self.page.selected_id
        self.page.shape_edit.setCurrentIndex(self.page.shape_edit.findData('square_ring'))
        self.page.geometry_controls['size_x_um'].setValue(1.8)
        self.page.geometry_controls['size_y_um'].setValue(1.8)
        self.page.inner_controls['inner_size_x_um'].setValue(1.2)
        self.page.inner_controls['inner_size_y_um'].setValue(1.2)
        self.page.apply_button.click()
        contact = find_object(self.store.device, object_id)
        self.assertEqual(contact['shape'], 'square_ring')
        self.assertFalse(shape_mask(contact, 0., 0.))
        self.assertTrue(shape_mask(contact, .8, 0.))
        path = self.page.top_view._object_path(contact)
        self.assertFalse(path.contains(self.page.top_view.screen_point(0., 0.)))
        self.assertTrue(path.contains(self.page.top_view.screen_point(.8, 0.)))
        self.assertEqual(_shape_section_intervals(contact, 0.), [(-.9, -.6), (.6, .9)])

    def test_pattern_array_creates_editable_unique_physical_void_regions(self):
        self.page.operation = 'void'
        self.page.add_shape('circle', dict(cx_um=-.375, cy_um=-.375, size_x_um=.1, size_y_um=.1))
        self.assertTrue(self.page.create_pattern_array(nx=4, ny=4, pitch_x_um=.25, pitch_y_um=.25))
        shapes = self.store.device['shapes']
        self.assertEqual(len(shapes), 16)
        self.assertEqual(len({shape['id'] for shape in shapes}), 16)
        self.assertEqual({shape['operation'] for shape in shapes}, {'void'})
        self.assertEqual(sorted({shape['cx_um'] for shape in shapes}), [-.375, -.125, .125, .375])
        self.assertEqual(sorted({shape['cy_um'] for shape in shapes}), [-.375, -.125, .125, .375])
        before = copy.deepcopy(self.store.device)
        self.assertFalse(self.page.create_pattern_array(nx=3, ny=3, pitch_x_um=-1.))
        self.assertEqual(self.store.device, before)


if __name__ == '__main__':
    unittest.main()
