"""Finish editing an object ID/name without rebuilding its property controls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PyQt6.QtCore import QCoreApplication,QEvent,Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from qt_research_studies import StructuredValueEditor
from qt_study_fields import NamedPropertyForm


class StudyFieldIdentityLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor=StructuredValueEditor([dict(id='state-fad90c3d',field_V_m=0.),dict(id='other-state',field_V_m=1e7)],'samples')
        self.form=NamedPropertyForm(self.editor,root_array_type='object')
        self.form.resize(850,450);self.form.show();self.form.activateWindow()
        self.form.navigator.setCurrentItem(self.form._nodes[('0',)][0]);self.app.processEvents()

    def tearDown(self):
        self.form.close();self.form.deleteLater();self.editor.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);self.app.processEvents()

    def test_finished_id_edit_updates_tree_and_heading_without_rebuilding_or_losing_focus(self):
        node=self.form.navigator.currentItem();control=self.form._fields['id'];other=self.form._fields['field_V_m']
        control.setFocus();control.selectAll();QTest.keyClicks(control,'zero-field')
        self.assertEqual(self.editor.value()[0]['id'],'zero-field')
        self.assertIs(self.form._fields['id'],control)
        QTest.keyClick(control,Qt.Key.Key_Return);self.app.processEvents()
        self.assertEqual(node.text(0),'zero-field');self.assertEqual(self.form.title.text(),'zero-field')
        self.assertIs(self.form.navigator.currentItem(),node)
        self.assertIs(self.form._fields['id'],control);self.assertIs(self.form._fields['field_V_m'],other)
        self.assertEqual(control.cursorPosition(),len('zero-field'));self.assertTrue(control.hasFocus())

    def test_name_edit_uses_same_label_priority_as_refresh_and_survives_tab_style_selection(self):
        self.editor.set_value([dict(name='Original name',id='stable-id',field_V_m=0.),dict(id='other-state',field_V_m=1e7)])
        self.form.refresh()
        node=self.form._nodes[('0',)][0];self.form.navigator.setCurrentItem(node)
        control=self.form._fields['name'];control.setText('Renamed state');control.textEdited.emit('Renamed state');control.editingFinished.emit()
        self.assertEqual(node.text(0),'Renamed state');self.assertEqual(self.form.title.text(),'Renamed state')
        self.form.navigator.setCurrentItem(self.form._nodes[('1',)][0]);self.form.navigator.setCurrentItem(node)
        self.assertEqual(self.form.title.text(),'Renamed state')
        self.assertEqual(self.editor.value()[0]['id'],'stable-id')

    def test_finished_blank_id_uses_current_fallback_and_keeps_invalid_draft(self):
        node=self.form.navigator.currentItem();control=self.form._fields['id']
        control.setText('');control.textEdited.emit('');control.editingFinished.emit()
        self.assertEqual(node.text(0),'Value 1');self.assertEqual(self.form.title.text(),'Value 1')
        self.assertEqual(self.editor.value()[0]['id'],'')
        self.assertIs(self.form._fields['id'],control)


if __name__=='__main__':unittest.main()
