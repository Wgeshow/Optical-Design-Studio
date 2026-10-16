"""Real global workspace flows for electrical materials and settings drafts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from electrical_material_library import lookup_material
from qt_compute import SettingsPage
from qt_core import ProjectStore
from qt_electrical_material_catalog import ElectricalMaterialCatalog
from qt_electrical_materials import ElectricalMaterialDialog
from qt_materials import MaterialsPage

APP=QApplication.instance() or QApplication([])


class GlobalWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=ProjectStore(DataLibrary(self.root/'library'),restore=False)
        self.widgets=[]
        self.settings=QSettings(str(self.root/'execution.ini'),QSettings.Format.IniFormat)
        self.preferences=patch('qt_common.preferences',return_value=self.settings);self.preferences.start()

    def tearDown(self):
        for widget in self.widgets:widget.close();widget.deleteLater()
        APP.processEvents();self.preferences.stop();self.temp.cleanup()

    def page(self,kind):
        page=kind(self.store);page.resize(1440,900);page.show();APP.processEvents();self.widgets.append(page)
        return page

    def edit_modal(self,name,*,reject=False,epsilon=None):
        def edit():
            dialog=APP.activeModalWidget()
            self.assertIsInstance(dialog,ElectricalMaterialDialog)
            dialog.name.setText(name)
            if epsilon is not None:dialog.controls['epsilon_r'].setText(str(epsilon))
            dialog.reject() if reject else dialog.accept()
        QTimer.singleShot(0,edit)

    def test_material_workspace_switch_retains_existing_optical_inspector_tools(self):
        page=self.page(MaterialsPage)
        original=[page.tabs.tabText(index) for index in range(page.tabs.count())]
        page.open_electrical_material('silicon')
        self.assertEqual(page.workspace_tabs.currentIndex(),1)
        self.assertEqual(page.electrical_catalog.selected_material_id(),'silicon')
        page.open_optical_materials(2)
        self.assertEqual(page.workspace_tabs.currentIndex(),0)
        self.assertEqual(page.tabs.currentIndex(),2)
        self.assertEqual([page.tabs.tabText(index) for index in range(page.tabs.count())],original)
        self.assertIn('Import CSV',original)

    def test_custom_add_edit_duplicate_and_cancel_keep_stable_ids(self):
        page=self.page(ElectricalMaterialCatalog)
        count=len(self.store.electrical_materials)
        self.edit_modal('Measured film',epsilon=13.2);page.add_button.click()
        ident=page.selected_material_id()
        self.assertEqual(len(self.store.electrical_materials),count+1)
        self.assertEqual(lookup_material(self.store.electrical_materials,ident)['properties']['epsilon_r'],13.2)
        self.edit_modal('Renamed film',epsilon=14.1);page.edit_button.click()
        self.assertEqual(page.selected_material_id(),ident)
        self.assertEqual(lookup_material(self.store.electrical_materials,ident)['name'],'Renamed film')
        self.edit_modal('Film duplicate');page.clone_button.click()
        duplicate=page.selected_material_id()
        self.assertNotEqual(duplicate,ident)
        self.assertEqual(lookup_material(self.store.electrical_materials,duplicate)['properties']['epsilon_r'],14.1)
        before=deepcopy(self.store.electrical_materials)
        self.edit_modal('Cancelled edit',reject=True,epsilon=80);page.edit_button.click()
        self.assertEqual(self.store.electrical_materials,before)

    def test_evaluated_temperature_preview_and_search_do_not_modify_materials(self):
        page=self.page(ElectricalMaterialCatalog);page.select_material('silicon')
        before=deepcopy(self.store.project());page.temperature.setValue(500.)
        gap=next(row for row in range(page.property_table.rowCount()) if page.property_table.item(row,0).text()=='Band gap')
        self.assertNotEqual(page.property_table.item(gap,1).text(),page.property_table.item(gap,2).text())
        self.assertEqual(self.store.project(),before)
        page.query.setText('Silicon')
        self.assertEqual(sum(not page.material_list.item(index).isHidden() for index in range(page.material_list.count())),1)
        self.assertIn('Sources and assumptions',page.sources.toPlainText())

    def test_link_and_assignment_use_actual_library_and_device_ids(self):
        page=self.page(ElectricalMaterialCatalog);page.select_material('silicon')
        page.optical_link.setCurrentIndex(page.optical_link.findData('GaAs'));page.link_button.click()
        self.assertEqual(lookup_material(self.store.electrical_materials,'silicon')['optical_material_name'],'GaAs')
        layer_id=page.assignment.currentData();page.assign_button.click()
        self.assertEqual(next(row for row in self.store.device['layers'] if row['id']==layer_id)['material_id'],'silicon')
        page.remove_button.click()
        self.assertIn('Reassign',page.status.text())
        self.assertTrue(any(row['id']=='silicon' for row in self.store.electrical_materials))

    def test_material_export_and_invalid_import_preserve_usable_project(self):
        page=self.page(ElectricalMaterialCatalog);target=self.root/'electrical.json'
        with patch('qt_electrical_material_catalog.QFileDialog.getSaveFileName',return_value=(str(target),'')):page.export_button.click()
        self.assertTrue(target.is_file())
        self.assertEqual(len(json.loads(target.read_text())['materials']),5)
        before=deepcopy(self.store.electrical_materials);target.write_text('{"id":"broken"}')
        with patch('qt_electrical_material_catalog.QFileDialog.getOpenFileName',return_value=(str(target),'')):page.import_button.click()
        self.assertEqual(self.store.electrical_materials,before)
        self.assertIn('Import failed',page.status.text())

    def test_execution_drafts_save_defaults_and_explicit_apply_are_separate(self):
        page=self.page(SettingsPage);before=deepcopy(self.store.project())
        page.basis.setValue(96);page.controls['threads'].setValue(2)
        self.assertEqual(self.store.project(),before)
        page.save_defaults_button.click()
        saved=SettingsPage.saved_execution_defaults()
        self.assertEqual(saved['settings']['NumG'],96);self.assertEqual(saved['performance']['threads'],2)
        self.assertEqual(self.store.project(),before)
        page.apply_resources_button.click()
        self.assertEqual(self.store.settings['NumG'],96);self.assertEqual(self.store.performance['threads'],2)
        page.basis.setValue(120);page.load_resources_button.click();self.assertEqual(page.basis.value(),96)

    def test_all_settings_menu_routes_and_runtime_controls_remain_accessible(self):
        page=self.page(SettingsPage)
        for route,index in (('settings.appearance',0),('settings.performance',1),('settings.data-storage',2),
                ('settings.add-ons.meep',3),('settings.add-ons.gpu',4)):
            self.assertTrue(page.select_section(route));APP.processEvents();self.assertEqual(page.settings_tabs.currentIndex(),index)
        self.assertTrue(hasattr(page.addons_panel,'meep_settings'))
        self.assertFalse(page.select_section('unknown'))

    def test_storage_updates_are_blocked_during_active_simulation(self):
        page=self.page(SettingsPage);self.store._set_busy(True)
        self.assertFalse(page.save_folder_button.isEnabled())
        with patch('desktop_runtime.save_data_directory') as save:page.save_data_directory();save.assert_not_called()
        self.assertFalse(page.save_settings());self.store._set_busy(False)

    def test_compact_runtime_keeps_complete_action_captions(self):
        page=self.page(SettingsPage);page.resize(640,760);page.select_section('settings.add-ons.meep')
        for _ in range(10):APP.processEvents()
        runtime=page.addons_panel.meep_settings
        for button in (runtime.check_button,runtime.install_button,runtime.setup_button):
            required=button.fontMetrics().horizontalAdvance(button.text().replace('&&','&'))+8
            self.assertGreaterEqual(button.width(),required)
        self.assertEqual(page.settings_scroll.horizontalScrollBar().maximum(),0)

    def test_whole_library_backup_uses_actual_background_export(self):
        page=self.page(SettingsPage);target=self.root/'backup.zip'
        with patch('qt_compute.QFileDialog.getSaveFileName',return_value=(str(target),'')):page.export_library_button.click()
        end=time.monotonic()+10.
        while self.store.busy and time.monotonic()<end:APP.processEvents();QTest.qWait(10)
        APP.processEvents();self.assertFalse(self.store.busy)
        self.assertTrue(target.is_file())
        with zipfile.ZipFile(target) as archive:self.assertIn('s4-library-manifest.json',archive.namelist())
        self.assertIn('Library backup saved',page.status.text())


if __name__=='__main__':unittest.main()
