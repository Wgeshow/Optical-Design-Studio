"""Display customization survives project files and leaves optical inputs intact."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary, read_json
from qt_core import ProjectStore
from qt_device_builder import DeviceBuilderPage


class DesignBControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.page=DeviceBuilderPage(self.store)
        self.page.resize(1460,900);self.page.show();self.app.processEvents()

    def tearDown(self):
        self.page.close();self.page.deleteLater();self.app.processEvents();self.temp.cleanup()

    def scientific_inputs(self):
        return {key:copy.deepcopy(self.store.project()[key]) for key in ('materials','layers','patterns','settings','performance')}

    def test_color_file_session_and_reset_preserve_scientific_inputs(self):
        before=self.scientific_inputs();name=self.page._selected
        with patch('qt_device_builder.QColorDialog.getColor',return_value=QColor('#dd2299')):
            self.page.layer_color_button.click()
        self.assertEqual(self.page.viewport.layer_colors[name],'#dd2299')
        item=self.page.layer_list.currentItem()
        self.assertEqual(item.data(Qt.ItemDataRole.UserRole+2),'#dd2299')
        path=Path(self.temp.name)/'colored.json';self.store.save_project(path)
        restored=ProjectStore(self.store.library,restore=False);restored.load_project(path)
        self.assertEqual(restored.appearance,self.store.appearance)
        self.assertEqual(read_json(self.store.session_path)['appearance'],self.store.appearance)
        self.assertEqual(before,self.scientific_inputs())
        self.page.reset_layer_color();self.assertNotIn(name,self.store.appearance['layer_colors'])

    def test_color_follows_rename_duplicate_and_reorder(self):
        self.page.set_layer_color('#123456')
        self.page.layer_name.setText('Colored device');self.page.layer_action('apply')
        self.assertEqual(self.store.appearance['layer_colors']['Colored device'],'#123456')
        self.page.layer_action('duplicate');duplicate=self.page._selected
        self.assertNotEqual(duplicate,'Colored device')
        self.assertEqual(self.store.appearance['layer_colors'][duplicate],'#123456')
        self.page.layer_action('up')
        self.assertEqual(self.page.viewport.layer_colors[duplicate],'#123456')

    def test_preview_options_visibility_and_summary_do_not_edit_design(self):
        before=self.scientific_inputs();item=self.page.layer_list.currentItem();name=self.page._selected
        self.page.display_controls['show_holes'].setChecked(False)
        self.assertEqual(self.page.viewport.regions(name),[])
        for key in ('use_colors','show_axes','show_edges'):
            self.page.display_controls[key].toggle()
        item.setCheckState(Qt.CheckState.Unchecked)
        self.assertIn(name,self.page.viewport.hidden_layers)
        for view in ('3D Stack','Unit cell','Cross-section'):
            self.page.set_geometry_view(view);self.app.processEvents()
            self.assertFalse(self.page.viewport.grab().isNull())
        self.assertEqual(before,self.scientific_inputs())
        item.setCheckState(Qt.CheckState.Checked);self.assertNotIn(name,self.page.viewport.hidden_layers)
        self.assertEqual(self.page.geometry_metrics['layers'].text(),str(len(self.store.layers)-2))

    def test_invalid_color_and_failed_save_leave_metadata_unchanged(self):
        before=copy.deepcopy(self.store.appearance)
        with self.assertRaises(ValueError):self.store.update_appearance({'layer_colors':{'Device':'not-a-color'}})
        self.assertEqual(self.store.appearance,before)
        with patch.object(self.store,'_autosave',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.page.set_layer_color('#123456')
        self.assertEqual(self.store.appearance,before)

    def test_old_project_resets_previous_colors(self):
        old=self.store.project();old.pop('appearance')
        self.page.set_layer_color('#123456');self.store.load_project(old)
        self.assertEqual(self.store.appearance,{'layer_colors':{},'material_opacities':{}})


if __name__=='__main__':unittest.main()
