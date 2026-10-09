"""Material preview opacity persists independently from all optical inputs."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary, read_json
from qt_core import ProjectStore
from qt_device_builder import DeviceBuilderPage
from qt_appearance import AppearancePage
from tests.test_qt_structure import MemoryStore

APP=QApplication.instance() or QApplication([])


class MaterialPreviewOpacityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        sample=MemoryStore()
        self.store.set_structure(sample.materials,sample.layers,sample.patterns)
        self.page=DeviceBuilderPage(self.store)
        self.page.resize(1460,950)
        self.page.show()
        self.settings_preview=AppearancePage(store=self.store)
        self.page.select_layer('PCS1')
        APP.processEvents()

    def tearDown(self):
        for widget in (self.settings_preview,self.page):
            widget.close()
            widget.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def optical_inputs(self):
        project=self.store.project()
        return {key:copy.deepcopy(project[key]) for key in ('materials','layers','patterns','settings','performance')}

    def test_material_opacity_roundtrips_and_survives_structure_undo(self):
        before=self.optical_inputs()
        undo_count=len(self.store._undo)
        self.assertFalse(self.page.material_opacity.hasTracking())
        self.page.material_opacity.setValue(37)
        self.assertEqual(self.store.appearance['material_opacities'],{'GaAs':37})
        self.assertEqual(self.page.material_opacity_value.text(),'37%')
        self.assertEqual(self.page.viewport.material_opacities['GaAs'],37)
        self.assertEqual(self.settings_preview.viewport.material_opacities['GaAs'],37)
        self.assertEqual(sum(layer['Material']=='GaAs' for layer in self.page.viewport.layers),2)
        self.assertEqual(self.optical_inputs(),before)
        self.assertEqual(len(self.store._undo),undo_count)
        path=Path(self.temp.name)/'opacity.json'
        self.store.save_project(path)
        restored=ProjectStore(self.store.library,restore=False)
        restored.load_project(path)
        self.assertEqual(restored.appearance,self.store.appearance)
        self.assertEqual(read_json(self.store.session_path)['appearance'],self.store.appearance)
        changed=self.store.layers.copy(deep=True)
        changed.loc[changed.Name=='PCS1','Thickness_um']=.4
        self.store.set_structure(self.store.materials,changed,self.store.patterns)
        self.store.undo()
        self.assertEqual(self.optical_inputs(),before)
        self.assertEqual(self.store.appearance['material_opacities'],{'GaAs':37})
        self.assertEqual(self.page.material_opacity.value(),37)

    def test_actual_material_selection_and_reset_leave_other_overrides_intact(self):
        self.store.update_appearance({'layer_colors':{'PCS1':'#abcdef'},'material_opacities':{'SiO2':21}})
        self.page.layer_material.setCurrentIndex(self.page.layer_material.findData('SiO2'))
        self.page.material_opacity.setValue(52)
        self.assertEqual(self.store.layers.loc[self.store.layers.Name=='PCS1','Material'].iloc[0],'GaAs')
        self.assertEqual(self.store.appearance['material_opacities'],{'SiO2':21,'GaAs':52})
        self.assertIn('GaAs',self.page.material_opacity.toolTip())
        self.page.select_layer('PCS2')
        self.assertEqual(self.page.material_opacity.value(),52)
        self.page.select_layer('Substrate')
        self.assertEqual(self.page.material_opacity.value(),21)
        self.page.select_layer('PCS1')
        self.page.material_opacity.setValue(0)
        self.assertEqual(self.store.appearance['material_opacities']['GaAs'],0)
        self.page.reset_material_opacity_button.click()
        self.assertEqual(self.store.appearance['material_opacities'],{'SiO2':21})
        self.assertEqual(self.store.appearance['layer_colors'],{'PCS1':'#abcdef'})
        self.assertEqual(self.page.material_opacity.value(),100)
        self.assertFalse(self.page.reset_material_opacity_button.isEnabled())

    def test_failed_opacity_save_restores_controls_and_metadata(self):
        before=copy.deepcopy(self.store.appearance)
        with patch.object(self.store,'_autosave',side_effect=OSError('disk full')):
            self.page.material_opacity.setValue(48)
        self.assertEqual(self.store.appearance,before)
        self.assertEqual(self.page.material_opacity.value(),100)
        self.assertIn('disk full',self.page.status.text())


if __name__=='__main__':unittest.main()
