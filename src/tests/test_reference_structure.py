"""Reference layout remains usable with real Structure controls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox
from qt_device_builder import DeviceBuilderPage, layer_color
from qt_common import theme_manager
from tests.test_qt_structure import MemoryStore

class ReferenceStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.page=DeviceBuilderPage(MemoryStore());self.page.resize(1488,780);self.page.show();self.app.processEvents()
    def tearDown(self):self.page.close();self.page.deleteLater();self.app.processEvents()
    def test_three_columns_and_inspector_appearance_controls(self):
        sizes=self.page.builder_splitter.sizes()
        self.assertLess(sizes[0],sizes[1]);self.assertLess(sizes[2],sizes[1])
        self.assertTrue(self.page.look_selector.isHidden())
        self.assertTrue(self.page.layer_color_button.isVisible())
        for key,button in self.page.look_buttons.items():
            self.assertTrue(button.isHidden())
            button.click();self.app.processEvents();self.assertEqual(theme_manager().look,key);self.assertTrue(button.isChecked())
        self.assertFalse(self.page.continue_button.isVisible())
        self.assertFalse(self.page.preview_note.isVisible())
    def test_pattern_preview_and_material_colors(self):
        self.assertFalse(self.page.pattern_view.grab().isNull())
        self.assertEqual(layer_color('Top GaAs',1,material='GaAs'),'#f48391')
        self.page.layer_selector.setCurrentIndex(0);self.assertEqual(self.page._selected,str(self.page.store.layers.iloc[0]['Name']))

    def test_named_layer_selection_tracks_edits_stack_and_geometry(self):
        selector=self.page.layer_selector
        self.assertIsInstance(selector,QComboBox)
        def check_selection(name):
            self.assertEqual(selector.currentText(),name)
            self.assertEqual(selector.currentData(),name)
            self.assertEqual(self.page.selected_layer,name)
            self.assertEqual(self.page.layer_list.currentItem().data(Qt.ItemDataRole.UserRole),name)
            self.assertEqual([selector.itemText(i) for i in range(selector.count())],list(self.page.store.layers.Name))
        selector.setCurrentIndex(selector.findData('PCS2'));check_selection('PCS2')
        self.page.layer_thickness.setValue(325);self.page.layer_action('apply')
        self.assertAlmostEqual(self.page.store.layers.loc[self.page.store.layers.Name=='PCS2','Thickness_um'].iloc[0],.325)
        self.assertAlmostEqual(self.page.store.layers.loc[self.page.store.layers.Name=='PCS1','Thickness_um'].iloc[0],.25)
        self.page.layer_name.setText('Silicon patterned layer');self.page.layer_action('apply');check_selection('Silicon patterned layer')
        self.assertEqual(selector.findData('PCS2'),-1)
        self.page.layer_action('up');check_selection('Silicon patterned layer')
        self.page.layer_action('duplicate');copy=self.page.selected_layer;check_selection(copy)
        self.page.layer_action('delete');check_selection(self.page.selected_layer)
        self.assertEqual(selector.findData(copy),-1)
        self.page.undo();self.assertGreaterEqual(selector.findData(copy),0)
        self.page.viewport.layer_selected.emit('Gold');check_selection('Gold')
        self.page.layer_list.setCurrentRow(0);check_selection('AirAbove')
        self.assertFalse(self.page.layer_thickness.isEnabled())

if __name__=='__main__':unittest.main()
