import os
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from refractiveindex_online import search_catalog, inspect_dataset
from tests.test_refractiveindex_online import CATALOG, DATA


class MaterialDetailsTests(unittest.TestCase):
    def test_author_and_material_search(self):
        result = search_catalog('Silicon Green', fetch=lambda *_: CATALOG)
        self.assertEqual(len(result), 1)
        self.assertEqual(search_catalog('Silver Green', fetch=lambda *_: CATALOG), [])

    def test_preview_reports_source_and_actual_range_without_import(self):
        item = search_catalog('Green', fetch=lambda *_: CATALOG)[0]
        calls = []
        package = inspect_dataset(item, fetch=lambda url, _: calls.append(url) or DATA)
        self.assertEqual(len(calls), 1)
        for text in ['250–500 nm', 'Test reference', 'temperature: 300', '300 K sample', 'No material has been added']:
            self.assertIn(text, package['details'])

    def test_formula_preview_does_not_assume_missing_k(self):
        item = search_catalog('Green', fetch=lambda *_: CATALOG)[0]
        raw = b'DATA:\n  - type: formula 1\n    wavelength_range: 0.5 1.0\n    coefficients: 0 1 0.1\n'
        details = inspect_dataset(item, fetch=lambda *_: raw)['details']
        self.assertIn('formula 1', details)
        self.assertIn('Coefficients: 0 1 0.1', details)
        self.assertIn('Not supplied', details)

    def test_preview_rejects_bad_paths(self):
        with self.assertRaises(ValueError):
            inspect_dataset({'data_path': '../secret.yml'})

    def test_ui_details_and_candidate_notes(self):
        from PyQt6.QtWidgets import QApplication
        from data_library import DataLibrary
        from qt_core import ProjectStore
        from qt_materials import MaterialsPage
        from qt_design_materials import DesignMaterialsDialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as path:
            store = ProjectStore(DataLibrary(path), restore=False)
            page = MaterialsPage(store)
            item = search_catalog('Green', fetch=lambda *_: CATALOG)[0]
            page._online_task_finished('online-material-search', [item])
            page.online_selection_changed()
            self.assertIn('Chemical / catalog identifier: Si', page.online_details.toPlainText())
            page._online_task_finished('online-material-preview', inspect_dataset(item, fetch=lambda *_: DATA))
            self.assertIn('Test reference', page.online_details.toPlainText())
            page._online_task_finished('online-material-search', [])
            self.assertIn('No matching', page.online_details.toPlainText())
            dialog = DesignMaterialsDialog(store)
            dialog.items.setCurrentRow(0)
            self.assertIn('constant approximation', dialog.details.toPlainText())
            page.close(); dialog.close()


if __name__ == '__main__':
    unittest.main()
