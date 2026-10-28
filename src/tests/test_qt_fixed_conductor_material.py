"""Offscreen conductor authoring only; no simulation or structure acceptance."""
from copy import deepcopy
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QDialog

from qt_electrical_materials import ElectricalMaterialDialog

APP = QApplication.instance() or QApplication([])


class FixedConductorMaterialDialogTests(unittest.TestCase):
    def test_explicit_clear_preserves_authored_constants_metadata_and_saves_sparse_record(self):
        dialog = ElectricalMaterialDialog()
        try:
            before = {key: control.text() for key, control in dialog.controls.items()}
            dialog.kind.setCurrentIndex(dialog.kind.findData('conductor'))
            self.assertEqual({key: control.text() for key, control in dialog.controls.items()}, before)
            dialog.name.setText('Authored fixed conductor')
            dialog.controls['epsilon_r'].setText('5')
            dialog.controls['conductivity_S_m'].setText('2')
            dialog.controls['optical_n'].setText('2')
            dialog.optical_material.setText('My optical reference')
            dialog.notes.setPlainText('Retain my source conditions')
            dialog.sources.setPlainText('[{"title":"My conductivity measurement","kind":"measurement"}]')
            dialog._material['property_overrides'] = ['Nc_cm3', 'epsilon_r']
            original = deepcopy(dialog._material)
            self.assertTrue(dialog.fixed_conductivity_button.isEnabled())
            dialog.fixed_conductivity_button.click()
            self.assertEqual(dialog.controls['epsilon_r'].text(), '5')
            self.assertEqual(dialog.controls['conductivity_S_m'].text(), '2')
            self.assertEqual(dialog.controls['optical_n'].text(), '2')
            self.assertEqual(dialog.optical_material.text(), 'My optical reference')
            self.assertEqual(dialog.notes.toPlainText(), 'Retain my source conditions')
            self.assertEqual(dialog._material, original)
            self.assertEqual(dialog.controls['Nc_cm3'].text(), '')
            self.assertIn('cleared', dialog.status.text())
            dialog.accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            saved = dialog.material()
            self.assertEqual(saved['properties'], dict(epsilon_r=5., conductivity_S_m=2., optical_n=2.))
            self.assertEqual(saved['sources'][0]['title'], 'My conductivity measurement')
            self.assertEqual(saved['property_overrides'], ['epsilon_r'])
        finally:
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_clear_action_is_not_available_for_semiconductor_or_reference_model(self):
        dialog = ElectricalMaterialDialog()
        try:
            self.assertFalse(dialog.fixed_conductivity_button.isEnabled())
            dialog.kind.setCurrentIndex(dialog.kind.findData('conductor'))
            self.assertTrue(dialog.fixed_conductivity_button.isEnabled())
            dialog.model.setCurrentIndex(dialog.model.findData('gaas_reference'))
            self.assertFalse(dialog.fixed_conductivity_button.isEnabled())
        finally:
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
