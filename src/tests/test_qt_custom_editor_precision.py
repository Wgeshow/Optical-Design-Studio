"""Unchanged full-device Apply preserves exact imported numbers and object IDs."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from device_model import default_device, find_object
from qt_core import ProjectStore
from qt_custom_device import CustomDevicePage


class CustomEditorPrecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        assert cls.app.platformName() == 'offscreen'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='custom-precision-')
        self.store = ProjectStore(DataLibrary(Path(self.temp.name) / 'library'), restore=False)
        self.guard = patch.object(self.store, 'start_run', side_effect=AssertionError('No solver/job permitted'))
        self.guard.start()
        device = default_device(self.store.electrical_materials)
        device.update(width_um=2.123456789012345, depth_um=3.23456789012345, temperature_K=300.123456789)
        layer = device['layers'][0]
        layer.update(optical_material_name='', thickness_um=2 / 3, donor_cm3=1.234567890123456e17, acceptor_cm3=2.345678901234567e16)
        self.layer_id = layer['id']
        shape = dict(id='precise-ring', name='Precise ring', layer_id=layer['id'], enabled=True,
                     shape='square_ring', cx_um=.123456789012345, cy_um=-.23456789012345,
                     size_x_um=.923456789012345, size_y_um=.812345678901234,
                     inner_size_x_um=.456789012345678, inner_size_y_um=.345678901234567,
                     angle_deg=12.3456789012345, vertices=[], material_id='gaas', operation='material',
                     optical_material_name='')
        device['shapes'].append(shape)
        contact = device['contacts'][0]
        contact.update(cx_um=.123456789012345, cy_um=-.23456789012345,
                       size_x_um=1.23456789012345, size_y_um=1.34567890123456,
                       angle_deg=2.3456789012345, voltage_V=1.23456789012345,
                       optical_thickness_um=.0123456789012345)
        self.contact_id = contact['id']
        self.store.set_device(device)
        self.page = CustomDevicePage(self.store)

    def tearDown(self):
        sip.delete(self.page)
        self.guard.stop()
        self.temp.cleanup()

    def apply(self):
        self.assertTrue(self.page.apply_inspector(), self.page.status.text())

    def typed(self, control, text):
        # Exercise the real textEdited signal without a visible window or native input.
        edit = control.lineEdit() if hasattr(control, 'lineEdit') else control
        edit.setText(text)
        edit.textEdited.emit(text)
        if hasattr(control, 'interpretText'):
            control.interpretText()

    def test_unchanged_layer_apply_keeps_full_thickness_and_doping_precision(self):
        self.page.select_object(self.layer_id)
        before = copy.deepcopy(self.store.device)
        self.assertNotEqual(self.page.thickness_edit.value(), before['layers'][0]['thickness_um'])
        self.apply()
        self.assertEqual(self.store.device, before)

    def test_rename_preserves_untouched_numbers_and_stable_id(self):
        self.page.select_object(self.layer_id)
        before = copy.deepcopy(find_object(self.store.device, self.layer_id))
        self.page.name_edit.setText('Renamed layer')
        self.apply()
        after = copy.deepcopy(find_object(self.store.device, self.layer_id))
        self.assertEqual(after.pop('name'), 'Renamed layer')
        before.pop('name')
        self.assertEqual(after, before)

    def test_explicit_typed_values_commit_even_when_equal_to_rounded_display(self):
        self.page.select_object(self.layer_id)
        displayed = self.page.thickness_edit.text()
        self.typed(self.page.thickness_edit, displayed)
        self.typed(self.page.donor_edit, self.page.donor_edit.text())
        self.apply()
        layer = find_object(self.store.device, self.layer_id)
        self.assertEqual(layer['thickness_um'], float(displayed))
        self.assertEqual(layer['donor_cm3'], 1.23457e17)
        self.typed(self.page.thickness_edit, '0.734567')
        self.apply()
        self.assertEqual(find_object(self.store.device, self.layer_id)['thickness_um'], .734567)

    def test_device_shape_contact_and_mesh_unchanged_apply_remains_exact(self):
        for identity in ('device', 'precise-ring', self.contact_id, 'mesh'):
            with self.subTest(identity=identity):
                self.page.select_object(identity)
                before = copy.deepcopy(self.store.device)
                self.apply()
                self.assertEqual(self.store.device, before)

    def test_contact_duplicate_controls_preserve_precision_and_accept_intentional_edits(self):
        self.page.select_object(self.contact_id)
        control = self.page.contact_position_controls['cx_um']
        self.typed(control, control.text())
        height = self.page.contact_height_edit
        self.typed(height, height.text())
        self.apply()
        contact = find_object(self.store.device, self.contact_id)
        self.assertEqual(contact['cx_um'], .123457)
        self.assertEqual(contact['optical_thickness_um'], .012346)
        self.assertEqual(contact['voltage_V'], 1.23456789012345)

    def test_diagnostic_round_trip_preserves_explicit_same_display_edit(self):
        self.page.select_object(self.layer_id)
        self.typed(self.page.thickness_edit, self.page.thickness_edit.text())
        with patch('qt_input_diagnostics.reveal_and_focus', return_value=True):
            self.assertTrue(self.page.open_diagnostic({'object_id': 'mesh', 'field': 'device.mesh.nx'}))
        self.assertTrue(self.page.return_from_diagnostic())
        self.apply()
        self.assertEqual(find_object(self.store.device, self.layer_id)['thickness_um'], .666667)

    def test_programmatic_control_edit_and_untouched_diagnostic_draft_are_distinct(self):
        self.page.select_object(self.layer_id)
        with patch('qt_input_diagnostics.reveal_and_focus', return_value=True):
            self.assertTrue(self.page.open_diagnostic({'object_id': 'mesh', 'field': 'device.mesh.nx'}))
        self.assertTrue(self.page.return_from_diagnostic())
        self.apply()
        self.assertEqual(find_object(self.store.device, self.layer_id)['thickness_um'], 2 / 3)
        self.page.thickness_edit.setValue(.7)
        self.apply()
        self.assertEqual(find_object(self.store.device, self.layer_id)['thickness_um'], .7)

    def test_aperture_anchor_labels_keep_correct_voltage_and_current_density_units(self):
        from qt_study_fields import field_label
        self.assertEqual(field_label('voltage_V'), 'Voltage (V)')
        self.assertEqual(field_label('current_density_A_cm2'), 'Current density (A/cm²)')


if __name__ == '__main__':
    unittest.main()
