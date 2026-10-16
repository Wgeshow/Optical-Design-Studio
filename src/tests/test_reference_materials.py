"""Reference workspace visibility and material filtering regressions."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_materials import MaterialsPage
from qt_common import theme_manager

class ReferenceMaterialsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.old_look=theme_manager().look
        theme_manager().apply_look('glass_dark',persist=False)
    @classmethod
    def tearDownClass(cls):
        theme_manager().apply_look(cls.old_look,persist=False)
    def test_reference_workspace_is_visible_and_library_selects_actual_data(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProjectStore(DataLibrary(Path(folder)/'library'),restore=False)
            page=MaterialsPage(store)
            page.resize(1460,800);page.show();self.app.processEvents()
            self.assertTrue(page.inspect_splitter.isVisible())
            self.assertTrue(page.material_list.isVisible())
            self.assertTrue(page.plot.isVisible())
            self.assertEqual(page.values.horizontalScrollBar().maximum(),0)
            self.assertEqual(page.inspect_splitter.count(),3)
            self.assertEqual([page.tabs.tabText(i) for i in range(page.tabs.count())],['Inspect','Find online','Import CSV','Enter values'])
            bar=page.tabs.tabBar()
            self.assertLessEqual(bar.tabRect(3).right(),bar.width())
            for tab in range(4):self.assertTrue(bar.rect().contains(bar.tabRect(tab)))
            page.material_scope.setCurrentIndex(page.material_scope.findData('saved'))
            self.assertGreater(page.material_list.rowCount(),0)
            self.assertFalse(page.material_list.item(0,0).icon().isNull())
            self.assertGreaterEqual(page.material_list.rowHeight(0),56)
            card=page.material_list.item(0,0).data(Qt.ItemDataRole.UserRole)
            self.assertTrue(card['name']);self.assertTrue(card['subtitle'])
            self.assertTrue(page.material_list.isColumnHidden(1))
            self.assertLess(page.material_query.y(),page.scope_buttons.button(0).y())
            page.select_material_row(0)
            self.assertTrue(page.selection.currentData().startswith(('builtin:','saved:')))
            self.assertEqual(page.material_name.text(),page.selected_row()[0]['Name'])
            self.assertTrue(page.add_preset.isEnabled())
            page.use_preset()
            self.assertTrue(page.selection.currentData().startswith('project:'))
            page.import_shortcut.click();self.app.processEvents()
            self.assertEqual(page.tabs.tabText(page.tabs.currentIndex()),'Import CSV')
            self.assertTrue(page.import_button.isVisible())
            page.tabs.setCurrentIndex(0)
            if os.environ.get('CAPTURE_MATERIALS_REFERENCE'):
                theme_manager().apply_look('glass_dark',persist=False)
                self.app.processEvents()
                page.grab().save(os.environ['CAPTURE_MATERIALS_REFERENCE'])
            page.close();page.deleteLater();self.app.processEvents()

if __name__=='__main__':unittest.main()
