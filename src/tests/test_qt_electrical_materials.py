"""Qt material validation, edit isolation, alloy updates and manager dispatch."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QDialog

from electrical_material_library import builtin_materials, export_materials, lookup_material
from qt_electrical_materials import ElectricalMaterialDialog, ElectricalMaterialManagerDialog

APP = QApplication.instance() or QApplication([])


class _Store:
    def __init__(self):
        self.electrical_materials = builtin_materials()
        self.writes = 0

    def set_electrical_materials(self, materials):
        self.electrical_materials = deepcopy(materials)
        self.writes += 1


class ElectricalMaterialDialogTests(unittest.TestCase):
    def tearDown(self):
        for widget in APP.topLevelWidgets():
            if isinstance(widget, (ElectricalMaterialDialog, ElectricalMaterialManagerDialog)):
                widget.close()
                widget.deleteLater()
        APP.processEvents()

    def test_edit_changes_are_detached_and_numeric_validation_keeps_dialog_open(self):
        original = lookup_material(builtin_materials(), 'gaas')
        before = deepcopy(original)
        dialog = ElectricalMaterialDialog(original)
        self.assertTrue(dialog.ident.isReadOnly())
        dialog.name.setText('Measured GaAs')
        dialog.controls['epsilon_r'].setText('15.0')
        dialog.controls['Nc_cm3'].setText('nan')
        dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIn('finite', dialog.status.text())
        dialog.controls['Nc_cm3'].setText('5e17')
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        edited = dialog.material()
        self.assertEqual(edited['name'], 'Measured GaAs')
        self.assertEqual(edited['properties']['epsilon_r'], 15.)
        self.assertEqual(edited['properties']['Nc_cm3'], 5e17)
        self.assertEqual(original, before)
        edited['properties']['epsilon_r'] = 999
        self.assertEqual(dialog.material()['properties']['epsilon_r'], 15.)

    def test_alloy_composition_updates_reference_and_preserves_manual_values(self):
        dialog = ElectricalMaterialDialog(lookup_material(builtin_materials(), 'algaas'))
        dialog.al_fraction.setValue(.3)
        dialog.controls['electron_mobility_cm2_Vs'].setText('1500')
        dialog.accept()
        result = dialog.material()
        self.assertEqual(result['al_fraction'], .3)
        self.assertEqual(result['band_type'], 'direct')
        self.assertAlmostEqual(result['properties']['bandgap_eV'], 1.7981)
        self.assertEqual(result['properties']['electron_mobility_cm2_Vs'], 1500.)

    def test_source_json_error_and_dielectric_custom_material(self):
        dialog = ElectricalMaterialDialog()
        dialog.sources.setPlainText('not json')
        dialog.accept()
        self.assertIn('JSON', dialog.status.text())
        dialog.sources.setPlainText('[]')
        dialog.kind.setCurrentIndex(dialog.kind.findData('dielectric'))
        dialog.model.setCurrentIndex(dialog.model.findData('constant'))
        for key, field in dialog.controls.items():
            field.setText('4' if key == 'epsilon_r' else '')
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.material()['properties'], {'epsilon_r':4.})

    def test_explicit_reset_restores_edited_reference_values(self):
        dialog = ElectricalMaterialDialog(lookup_material(builtin_materials(), 'silicon'))
        dialog.controls['epsilon_r'].setText('30')
        dialog.temperature.setValue(350.)
        dialog.reference_button.click()
        self.assertEqual(float(dialog.controls['epsilon_r'].text()), 11.7)
        dialog.accept()
        self.assertEqual(dialog.material()['temperature_K'], 350.)
        self.assertEqual(dialog.material()['properties']['epsilon_r'], 11.7)

    def test_manager_selects_and_import_is_validated_before_store_mutation(self):
        store = _Store()
        dialog = ElectricalMaterialManagerDialog(store)
        selected = []
        dialog.materialSelected.connect(selected.append)
        self.assertEqual(dialog.material_list.count(), 5)
        self.assertIn('Sources and assumptions', dialog.details.toPlainText())
        dialog.material_list.setCurrentRow(1)
        dialog.use_selected()
        self.assertEqual(selected, ['ito'])
        self.assertEqual(store.writes, 0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'custom.json'
            path.write_text('{"id":"broken"}', encoding='utf-8')
            with patch('qt_electrical_materials.QFileDialog.getOpenFileName', return_value=(str(path),'')):
                dialog.import_library()
            self.assertEqual(store.writes, 0)
            self.assertIn('Import failed', dialog.status.text())
            material = deepcopy(store.electrical_materials[0])
            material['name'] = 'Measured GaAs'
            export_materials(path, [material])
            with patch('qt_electrical_materials.QFileDialog.getOpenFileName', return_value=(str(path),'')):
                dialog.import_library()
            self.assertEqual(store.writes, 1)
            self.assertEqual(store.electrical_materials[0]['name'], 'Measured GaAs')
            self.assertEqual(dialog.selected_material_id(), 'gaas')
        dialog.add_missing_presets()
        self.assertEqual(store.electrical_materials[0]['name'], 'Measured GaAs')


if __name__ == '__main__':
    unittest.main()
