"""Missing-input navigation must preserve drafts and focus the actual editor."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from data_library import DataLibrary
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace
from qt_input_diagnostics import reveal_and_focus
from input_diagnostics import diagnostic

APP=QApplication.instance() or QApplication([])


class MissingInputNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ods_input_links_',dir=Path(__file__).resolve().parents[3])
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.page=SimulationSetupWorkspace(self.store)
        self.page.resize(1500,950)
        self.page.show()
        self.page.activateWindow()
        APP.processEvents()

    def tearDown(self):
        self.page.close();self.page.deleteLater();APP.processEvents();self.temp.cleanup()

    def invalid_basis(self):
        self.page.select_section('optical.accuracy')
        editor=next(w for w in self.page.widgets_by_key['settings.NumG'] if w.isVisible())
        editor.setFocus();editor.selectAll();QTest.keyClicks(editor,'not a number')
        QTest.keyClick(editor,Qt.Key.Key_Tab)
        return editor

    def test_keyboard_issue_link_focuses_field_keeps_draft_and_returns(self):
        previous=self.store.settings['NumG']
        editor=self.invalid_basis()
        self.page.select_section('optical.overview')
        with patch.object(self.page.state,'validate',return_value=[]):
            self.assertFalse(self.page.validate_current())
        self.page.validation_list.setCurrentRow(0)
        self.page.validation_list.setFocus()
        QTest.keyClick(self.page.validation_list,Qt.Key.Key_Return)
        APP.processEvents()
        self.assertEqual(self.page.current_section,'optical.accuracy')
        self.assertTrue(editor.hasFocus())
        self.assertEqual(editor.text(),'not a number')
        self.assertEqual(self.store.settings['NumG'],previous)
        self.assertIsNotNone(editor.findChild(QWidget,'diagnosticFieldHighlight'))
        QTest.keyClick(editor,Qt.Key.Key_Escape)
        self.assertEqual(self.page.current_section,'optical.overview')
        self.assertTrue(self.page.validation_list.hasFocus())

    def test_corrected_issue_is_rechecked_before_old_link_is_followed(self):
        editor=self.invalid_basis()
        with patch.object(self.page.state,'validate',return_value=[]):
            self.page.validate_current()
            old=self.page.validation_list.item(0).data(Qt.ItemDataRole.UserRole)
            editor.setText('96');QTest.keyClick(editor,Qt.Key.Key_Tab)
            self.page.select_section('optical.overview')
            self.assertFalse(self.page.open_diagnostic(old))
        self.assertEqual(self.page.validation_list.count(),0)
        self.assertEqual(self.page.current_section,'optical.overview')
        self.assertEqual(self.store.settings['NumG'],96)

    def test_typed_issue_without_revision_gets_current_input_revision(self):
        typed=diagnostic('Check basis',workspace='optical',section='optical.accuracy',field='settings.NumG')
        with patch.object(self.page.state,'validate',return_value=[typed]):self.page.validate_current()
        saved=self.page.validation_list.item(0).data(Qt.ItemDataRole.UserRole)
        self.assertEqual(saved['revision'],self.page.input_revision())
        self.page.state.set('settings.NumG',96)
        with patch.object(self.page.state,'validate',return_value=[]):self.assertFalse(self.page.open_diagnostic(saved))

    def test_deleted_object_never_selects_a_different_object(self):
        selected=getattr(self.page,'selected_object','')
        issue=diagnostic('Set contact voltage',workspace='electrical',section='electrical.study',
            object_id='deleted-contact',field='device.contacts')
        with patch.object(self.page.state,'validate',return_value=[]):
            self.assertFalse(self.page.open_diagnostic(issue))
        self.assertEqual(getattr(self.page,'selected_object',''),selected)
        self.assertIn('removed',self.page.status.text())

    def test_table_draft_survives_refresh_and_link_selects_its_exact_cell(self):
        self.page.set_mode('electrical')
        table=self.page.tables_by_key['device.layers'][0]
        section=next(tab['id'] for tab in self.page.section_meta.values()
                     for card in tab.get('cards',[]) for field in card.get('fields',[])
                     if field.get('key')=='device.layers')
        self.page.select_section(section)
        ident=table._rows[0]['id']
        previous=self.store.device['layers'][0].get('donor_cm3',0)
        table.item(0,4).setText('bad doping')
        self.page.state.set('device.mesh.nx',17)
        self.page.refresh()
        self.assertEqual(table.item(0,4).text(),'bad doping')
        self.assertEqual(self.store.device['layers'][0].get('donor_cm3',0),previous)
        self.page.select_section('electrical.overview')
        with patch.object(self.page.state,'validate',return_value=[]):self.page.validate_current()
        issue=next(self.page.validation_list.item(i).data(Qt.ItemDataRole.UserRole)
                   for i in range(self.page.validation_list.count())
                   if self.page.validation_list.item(i).data(Qt.ItemDataRole.UserRole).get('object_id')==ident)
        self.assertTrue(self.page.open_diagnostic(issue))
        self.assertEqual((table.currentRow(),table.currentColumn()),(0,4))
        self.assertTrue(table.hasFocus())
        table.item(0,4).setText('1000')
        with patch.object(self.page.state,'validate',return_value=[]):self.assertTrue(self.page.validate_current())
        self.assertEqual(self.store.device['layers'][0]['donor_cm3'],1000)

    def test_reveal_opens_nested_page_and_scrolls_without_enabling_model(self):
        host=QTabWidget();first=QWidget();body=QWidget();layout=QVBoxLayout(body)
        layout.addSpacing(1100);editor=QLineEdit();layout.addWidget(editor)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(body)
        host.addTab(first,'First');host.addTab(scroll,'Inputs');host.resize(600,350);host.show()
        APP.processEvents()
        self.assertTrue(reveal_and_focus(editor,message='Enter a value'))
        self.assertEqual(host.currentIndex(),1)
        self.assertGreater(scroll.verticalScrollBar().value(),0)
        editor.setEnabled(False)
        self.assertFalse(reveal_and_focus(editor))
        self.assertFalse(editor.isEnabled())
        host.close();host.deleteLater();APP.processEvents()


if __name__=='__main__':unittest.main()
