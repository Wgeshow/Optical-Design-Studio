"""Auxiliary transport contact choices track authored device IDs, not names."""
from copy import deepcopy
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from PyQt6.QtWidgets import QApplication,QPushButton
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_transport_research_setup import TransportResearchWorkspace
from research_catalog import list_capabilities

APP=QApplication.instance() or QApplication([])

class DeviceAssignmentContactTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd())
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.study='pcsel_unitcell_transport';self.store.activate_study(self.study)
        cap=next(c for c in list_capabilities() if c['engine']==self.study)
        self.page=TransportResearchWorkspace(self.store,cap,document_id=self.study)
        self.page.select_section('device_editor')
        self.page.device_editor.open_button.click()
        self.assertIsNotNone(self.page.device_editor.editor)
        self.editor=self.page.device_editor.editor

    def tearDown(self):
        self.page._save_timer.stop();self.page.close();self.page.deleteLater()
        APP.processEvents();self.temp.cleanup()

    def author(self,name,surface='top'):
        self.editor.add_contact();identity=self.editor.selected_id
        self.editor.name_edit.setText(name)
        control=self.editor.contact_controls['surface'];control.setCurrentIndex(control.findData(surface))
        self.editor.apply_button.click()
        contact=next(c for c in self.store.device['contacts'] if c['id']==identity)
        self.assertEqual(contact['name'],name);self.assertEqual(contact['surface'],surface)
        return identity

    def test_editor_apply_refreshes_both_pickers_and_explicit_use_copies_actual_id(self):
        self.assertEqual(self.page.device_contact_picker.count(),1)
        with patch.object(self.store,'start_run',side_effect=AssertionError('No solver allowed')):
            top=self.author('visible top');bottom=self.author('visible bottom','bottom')
        picker=self.page.device_contact_picker
        self.assertEqual(picker.count(),3)
        self.assertEqual(picker.currentData(),'')
        for identity in (top,bottom):
            self.assertGreaterEqual(picker.findData(identity),1)
            self.assertGreaterEqual(self.page.contact_picker.findData(identity),1)
            self.assertIn(identity,self.page.device_assignment_description.text())
        picker.setCurrentIndex(picker.findData(top))
        next(b for b in self.page.findChildren(QPushButton) if b.text()=='Use as swept contact').click()
        self.assertEqual(self.page.fields['swept_contact_id'].text(),top)

    def test_rename_disable_remove_preserve_ids_and_independent_unsaved_setting(self):
        top=self.author('top');bottom=self.author('bottom','bottom');picker=self.page.device_contact_picker
        picker.setCurrentIndex(picker.findData(top));changed=Mock();picker.currentIndexChanged.connect(changed)
        self.page.fields['swept_contact_id'].setText('unfinished-contact-draft');self.page._save_timer.stop()
        self.editor.select_object(top);self.editor.name_edit.setText('renamed top');self.editor.apply_button.click()
        self.assertEqual(picker.currentData(),top);self.assertEqual(picker.currentText(),'renamed top')
        changed.assert_not_called();self.assertEqual(self.page.fields['swept_contact_id'].text(),'unfinished-contact-draft')
        self.editor.enabled_edit.setChecked(False);self.editor.apply_button.click()
        self.assertEqual(picker.findData(top),-1);self.assertEqual(picker.currentData(),'')
        self.assertNotIn(top,self.page.device_assignment_description.text())
        self.assertEqual(self.page.fields['swept_contact_id'].text(),'unfinished-contact-draft')
        picker.setCurrentIndex(picker.findData(bottom));self.editor.select_object(bottom);self.editor.delete_selected()
        self.assertEqual(picker.count(),1);self.assertEqual(picker.currentData(),'')
        self.assertEqual(self.page.fields['swept_contact_id'].text(),'unfinished-contact-draft')

    def test_inactive_document_refresh_does_not_write_or_take_another_studys_contacts(self):
        identity=self.author('owned contact');picker=self.page.device_contact_picker
        picker.setCurrentIndex(picker.findData(identity));description=self.page.device_assignment_description.text()
        self.store.activate_study('advanced_transport')
        other_device=deepcopy(self.store.device)
        with patch.object(self.store,'save_search') as save:
            self.page.refresh_device_assignments('device')
            save.assert_not_called()
        self.assertEqual(self.page.device_assignment_description.text(),description)
        self.assertEqual(picker.currentData(),identity);self.assertEqual(self.store.device,other_device)
        self.store.activate_study(self.study)
        self.assertEqual(picker.currentData(),identity)
        self.assertIn(identity,self.page.device_assignment_description.text())

    def test_material_description_refreshes_without_changing_contact_or_setting(self):
        identity=self.author('owned contact');picker=self.page.device_contact_picker
        picker.setCurrentIndex(picker.findData(identity));before=self.page.fields['swept_contact_id'].text()
        materials=deepcopy(self.store.electrical_materials);materials[0]['name']='Renamed illustrative material'
        self.store.set_electrical_materials(materials)
        self.assertIn('Renamed illustrative material',self.page.device_assignment_description.text())
        self.assertEqual(picker.currentData(),identity);self.assertEqual(self.page.fields['swept_contact_id'].text(),before)

if __name__=='__main__':unittest.main()
