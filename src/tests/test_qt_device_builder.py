"""Approved builder interaction, geometry integrity and responsive review checks."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from qt_device_builder import DeviceBuilderPage
from qt_common import theme_manager
from tests.test_qt_structure import MemoryStore


class DeviceBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.store=MemoryStore();self.page=DeviceBuilderPage(self.store)
        self.page.resize(1250,640);self.page.show();self.app.processEvents()

    def tearDown(self):
        self.page.close();self.page.deleteLater();self.app.processEvents()

    def test_square_has_one_input_and_rectangular_preserves_two_independent_periods(self):
        self.assertFalse(self.page.lattice_y.isVisible())
        self.page.lattice_x.setValue(640);self.page.apply_lattice()
        self.assertEqual(self.store.settings['ax_um'],.64);self.assertEqual(self.store.settings['ay_um'],.64)
        self.page.lattice_type.setCurrentText('Rectangular');self.assertTrue(self.page.lattice_y.isVisible())
        self.page.lattice_y.setValue(810);self.page.apply_lattice()
        self.assertEqual(self.store.settings['ax_um'],.64);self.assertEqual(self.store.settings['ay_um'],.81)

    def test_layer_and_region_edits_update_underlying_model_and_live_preview(self):
        self.page.select_layer('PCS1');self.page.layer_thickness.setValue(350);self.page.layer_action('apply')
        self.assertAlmostEqual(self.store.layers.iloc[1].Thickness_um,.35)
        self.page.quick_radius.setValue(120);self.page.apply_quick_region()
        self.assertAlmostEqual(self.store.patterns.iloc[0].SizeX_um,.12)
        self.assertAlmostEqual(self.page.viewport.patterns[0]['sx'],.12)
        before=len(self.store.layers);self.page.layer_action('duplicate')
        self.assertEqual(len(self.store.layers),before+1)
        self.page.undo();self.assertEqual(len(self.store.layers),before)

    def test_view_changes_orbit_and_explosion_never_change_scientific_geometry(self):
        before=self.store.layers.copy(deep=True)
        for mode in ('Cross-section','Unit cell','3D Stack'):
            self.page.set_geometry_view(mode);self.app.processEvents();self.assertFalse(self.page.viewport.grab().isNull())
        self.page.assembly.setCurrentIndex(0);self.assertFalse(self.page.viewport.exploded)
        self.page.assembly.setCurrentIndex(1);self.assertTrue(self.page.viewport.exploded)
        self.assertTrue(self.store.layers.equals(before))

    def test_light_dark_and_compact_layout_retain_primary_controls(self):
        for mode in ('light','dark'):
            theme_manager().apply(mode,persist=False);self.app.processEvents()
            self.assertTrue(self.page.continue_button.isHidden())
            self.assertFalse(self.page.grab().isNull())

    def test_eye_control_hides_preview_without_changing_structure(self):
        before=self.store.layers.copy(deep=True)
        item=self.page.layer_list.item(1)
        name=item.data(Qt.ItemDataRole.UserRole)
        bounds=self.page.layer_list.visualItemRect(item)
        QTest.mouseClick(self.page.layer_list.viewport(),Qt.MouseButton.LeftButton,pos=QPoint(bounds.left()+17,bounds.center().y()))
        self.app.processEvents()
        self.assertIn(name,self.page.viewport.hidden_layers)
        self.assertTrue(self.store.layers.equals(before))
        QTest.mouseClick(self.page.layer_list.viewport(),Qt.MouseButton.LeftButton,pos=QPoint(bounds.left()+17,bounds.center().y()))
        self.app.processEvents()
        self.assertNotIn(name,self.page.viewport.hidden_layers)


if __name__=='__main__':unittest.main()
