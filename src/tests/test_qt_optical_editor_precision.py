"""Original optical layer edits must not round imported scientific geometry."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from qt_device_builder import DeviceBuilderPage
from qt_structure import StructurePage
from tests.test_qt_structure import MemoryStore


class OpticalEditorPrecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_editor(self, page_type):
        store = MemoryStore()
        # The Winn low-index layer is two thirds of a micrometre. Its binary
        # source value must survive more than the spinbox's decimal precision.
        store.layers.loc[store.layers.Name == 'PCS1', 'Thickness_um'] = 2 / 3
        page = page_type(store)
        page.select_layer('PCS1')
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close)
        return store, page

    @staticmethod
    def apply(page):
        page.findChild(QPushButton, 'applyLayer').click()

    @staticmethod
    def type_thickness(page, value):
        page.layer_thickness.lineEdit().selectAll()
        QTest.keyClicks(page.layer_thickness.lineEdit(), value)

    def test_apply_without_edit_preserves_imported_thickness_exactly(self):
        for page_type in (StructurePage, DeviceBuilderPage):
            with self.subTest(page=page_type.__name__):
                store, page = self.make_editor(page_type)
                original = store.layers.copy(deep=True)
                self.apply(page)
                self.assertTrue(store.layers.equals(original))
                self.assertEqual(store.layers.Thickness_um.sum(), original.Thickness_um.sum())

    def test_material_only_edit_preserves_exact_imported_thickness(self):
        for page_type in (StructurePage, DeviceBuilderPage):
            with self.subTest(page=page_type.__name__):
                store, page = self.make_editor(page_type)
                before = store.layers.Thickness_um.copy()
                page.layer_material.setCurrentIndex(page.layer_material.findData('current:SiO2'))
                self.apply(page)
                self.assertTrue(store.layers.Thickness_um.equals(before))
                self.assertEqual(store.layers.iloc[1].Material, 'SiO2')

    def test_explicit_typed_thickness_is_committed_without_display_rounding(self):
        for page_type in (StructurePage, DeviceBuilderPage):
            with self.subTest(page=page_type.__name__):
                store, page = self.make_editor(page_type)
                self.type_thickness(page, '667.1234567')
                self.apply(page)
                self.assertAlmostEqual(store.layers.iloc[1].Thickness_um, .6671234567, places=14)
                self.assertEqual(store.layers.iloc[2].Thickness_um, .25)

    def test_unit_changes_preserve_both_pristine_and_edited_thickness(self):
        for page_type in (StructurePage, DeviceBuilderPage):
            with self.subTest(page=page_type.__name__):
                store, page = self.make_editor(page_type)
                for _ in range(4):
                    page.units.setCurrentText('µm')
                    page.units.setCurrentText('nm')
                self.apply(page)
                self.assertEqual(store.layers.iloc[1].Thickness_um, 2 / 3)
                self.type_thickness(page, '667.1234567')
                # Unit switching also commits pending text in the old unit.
                page.units.setCurrentText('µm')
                for _ in range(4):
                    page.units.setCurrentText('nm')
                    page.units.setCurrentText('µm')
                self.apply(page)
                self.assertAlmostEqual(store.layers.iloc[1].Thickness_um, .6671234567, places=14)


if __name__ == '__main__':
    unittest.main()
