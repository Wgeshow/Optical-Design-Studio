"""Reachability checks for the reference-driven search and help workspace."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_ai_search import AISearchPage
from qt_library import LibraryPage
from qt_help import HelpGuide

class ReferenceWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.widgets=[]

    def tearDown(self):
        for widget in self.widgets:widget.close();widget.deleteLater()
        self.app.processEvents();self.temp.cleanup()

    def test_search_action_reachable_from_all_setup_pages(self):
        page=AISearchPage(self.store);self.widgets.append(page)
        page.resize(1460,850);page.show();self.app.processEvents()
        with patch.object(page,'run') as run:
            for index in range(page.setup_tabs.count()):
                page.setup_tabs.setCurrentIndex(index);self.app.processEvents()
                self.assertTrue(page.campaign_actions.isVisible())
                QTest.mouseClick(page.starts[-1],Qt.MouseButton.LeftButton)
                run.assert_called_with('search')
        self.assertTrue(page.field_plot.isVisible())
        self.assertTrue(page.select_tool_tab('designs'))
        self.app.processEvents()
        self.assertTrue(page.results.isVisible())
        self.assertTrue(page.select_tool_tab('fields'))
        self.app.processEvents()
        self.assertTrue(page.field_plot.isVisible())

    def test_quick_help_restores_filtered_topic(self):
        page=HelpGuide();self.widgets.append(page)
        page.query.setText('phase');self.assertGreater(page.topics.count(),0)
        page.open_topic('Appearance and colors')
        self.assertEqual(page.query.text(),'')
        self.assertTrue(page.reader.toPlainText().startswith('Appearance and colors'))

    def test_compact_bounds_editor_keeps_saved_ranges(self):
        page=AISearchPage(self.store);self.widgets.append(page)
        page.default_ranges();before=page.bounds.records()
        page.edit_bounds.setChecked(True)
        self.assertFalse(page.bounds_editor.isHidden())
        page.edit_bounds.setChecked(False)
        self.assertEqual(page.bounds.records(),before)
        page.save()
        self.assertEqual(self.store.project()['desktop_search']['ai_search']['bounds'],before)

    def test_library_restoration_controls_reachable_with_result_view(self):
        page=LibraryPage(self.store);self.widgets.append(page)
        page.resize(1460,850);page.show();self.app.processEvents()
        self.assertTrue(page.plot.isVisible())
        self.assertTrue(page.select_tool_tab('notes'))
        self.app.processEvents()
        self.assertTrue(page.title_edit.isVisible())
        self.assertTrue(page.restore.isVisible())
        self.assertFalse(page.restore.isEnabled())

if __name__=='__main__':
    unittest.main()
