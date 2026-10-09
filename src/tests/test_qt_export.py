import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from qt_export import ExportDialog
from qt_structure import StructurePage
from tests.test_qt_structure import MemoryStore


class ExportUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_units_and_rectangular_counts_pass_to_export(self):
        store = MemoryStore()
        page = StructurePage(store)
        dialog = ExportDialog(store.settings, False)
        dialog.nx.setValue(2)
        dialog.ny.setValue(5)
        dialog.unit.setCurrentIndex(dialog.unit.findData('nm'))
        self.assertIn('1540 × 3850 nm', dialog.size_label.text())
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)/'Device.java'
            with patch('qt_export.ExportDialog', return_value=dialog), patch.object(dialog, 'exec', return_value=1), patch('qt_structure.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
                page.export_comsol()
            self.assertTrue(destination.is_file())
            text = destination.read_text()
            self.assertIn('"cells_y", "5"', text)
            self.assertIn('lengthUnit("nm")', text)
        page.close()
        dialog.close()

    def test_cancel_does_not_open_save_dialog(self):
        page = StructurePage(MemoryStore())
        with patch.object(ExportDialog, 'exec', return_value=0), patch('qt_structure.QFileDialog.getSaveFileName') as save:
            page.export_cad()
            save.assert_not_called()
        page.close()
