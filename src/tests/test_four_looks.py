"""Four skins share the B editor and persist independent user palettes."""
import os
import copy
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from qt_common import theme_manager,ThemeManager,COLORS,LOOKS
from qt_appearance import AppearancePage
from qt_device_builder import DeviceBuilderPage
from tests.test_qt_structure import MemoryStore


class FourLooksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.manager=theme_manager()
        self.old=(self.manager.settings,self.manager.look,copy.deepcopy(self.manager.custom_colors),self.manager.glass_opacity)
        self.manager.settings=QSettings(self.temp.name+'/appearance.ini',QSettings.Format.IniFormat)
        self.manager.custom_colors={};self.manager.apply_look('dark')
        self.store=MemoryStore();self.page=DeviceBuilderPage(self.store);self.page.resize(1460,1024);self.page.show()

    def tearDown(self):
        self.page.close();self.page.deleteLater();self.app.processEvents()
        self.manager.settings,self.manager.custom_colors,self.manager.glass_opacity=self.old[0],self.old[2],self.old[3]
        self.manager.apply_look(self.old[1],persist=False);self.temp.cleanup()

    def test_all_looks_preserve_controls_selection_geometry_and_model(self):
        before=(self.store.layers.copy(),self.store.patterns.copy(),copy.deepcopy(self.store.settings))
        self.page.select_layer('PCS2');controls=set(self.page.display_controls)
        for look in LOOKS:
            self.page.look_selector.setCurrentIndex(self.page.look_selector.findData(look));self.app.processEvents()
            self.assertEqual(self.manager.look,look)
            self.assertEqual(self.page._selected,'PCS2')
            self.assertEqual(set(self.page.display_controls),controls)
            self.assertTrue(self.page.continue_button.isHidden())
            self.assertTrue(self.page.layer_color_button.isVisible())
            self.assertFalse(self.page.grab().isNull())
            self.assertTrue(self.store.layers.equals(before[0]));self.assertTrue(self.store.patterns.equals(before[1]));self.assertEqual(self.store.settings,before[2])
        self.page.layer_selector.setCurrentIndex(self.page.layer_selector.findData('PCS1'));self.assertEqual(self.page._selected,'PCS1')

    def test_custom_colors_are_isolated_per_look_and_survive_restart(self):
        self.manager.apply_look('glass_light');self.manager.set_ui_color('accent','#882266');self.manager.set_ui_color('panel','#e3e7ee')
        self.manager.apply_look('dark');self.assertNotEqual(COLORS['dark']['accent'],'#882266')
        self.manager.set_ui_color('accent','#ffaa44')
        with patch('qt_common.preferences',return_value=self.manager.settings):restored=ThemeManager()
        self.assertEqual(restored.look,'dark');self.assertEqual(restored.custom_colors['glass_light']['accent'],'#882266')
        self.manager.apply_look('glass_light');self.assertEqual(COLORS['light']['accent'],'#882266')
        self.manager.reset_ui_colors();self.assertNotEqual(COLORS['light']['accent'],'#882266')
        self.manager.apply_look('dark');self.assertEqual(COLORS['dark']['accent'],'#ffaa44')

    def test_invalid_colors_leave_palette_and_preferences_intact(self):
        before=copy.deepcopy(self.manager.custom_colors);color=COLORS['dark']['accent']
        with self.assertRaises(ValueError):self.manager.set_ui_color('accent','invalid')
        with self.assertRaises(ValueError):self.manager.set_ui_color('unsupported','#123456')
        self.assertEqual(self.manager.custom_colors,before);self.assertEqual(COLORS['dark']['accent'],color)

    def test_quick_pattern_dimensions_rotation_and_units_in_each_look(self):
        self.page.select_layer('PCS1')
        for look in LOOKS:
            self.manager.apply_look(look)
            self.page.quick_shape.setCurrentText('Ellipse')
            self.assertEqual(self.page.quick_radius_label.text(),'X radius')
            self.page.quick_radius.setValue(110);self.page.quick_radius_y.setValue(65);self.page.quick_angle.setValue(25)
            self.page.apply_quick_region()
            row=self.store.patterns[self.store.patterns.Layer=='PCS1'].iloc[0]
            self.assertEqual(row.Shape,'ellipse');self.assertAlmostEqual(row.SizeX_um,.11);self.assertAlmostEqual(row.SizeY_um,.065);self.assertEqual(row.Angle_deg,25)
            self.page.quick_shape.setCurrentText('Rectangle')
            self.assertEqual(self.page.quick_radius_y_label.text(),'Full width Y')
            self.page.apply_quick_region();self.assertEqual(self.store.patterns.iloc[0].Shape,'rectangle')

    def test_appearance_controls_follow_editor_look_and_apply_hex(self):
        appearance=AppearancePage()
        try:
            self.page.look_selector.setCurrentIndex(self.page.look_selector.findData('glass_dark'))
            self.assertEqual(appearance.theme.currentData(),'glass_dark');self.assertTrue(appearance.glass_opacity.isEnabled())
            appearance.color_fields['accent'].setText('#aa88ee');appearance.color_fields['accent'].editingFinished.emit()
            self.assertEqual(COLORS['dark']['accent'],'#aa88ee')
            appearance.glass_opacity.setValue(70);self.assertEqual(self.manager.glass_opacity,70)
            appearance.theme.setCurrentIndex(appearance.theme.findData('light'))
            self.assertEqual(self.page.look_selector.currentData(),'light');self.assertFalse(appearance.glass_opacity.isEnabled())
        finally:appearance.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()
