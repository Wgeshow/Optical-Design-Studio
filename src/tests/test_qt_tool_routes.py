"""Every preserved optical tool section is reachable by its stable named route."""
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QSignalSpy
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_compute import OptimizePage,FieldsPage
from qt_ai_search import AISearchPage
from qt_index_shift import IndexShiftPage
from qt_library import LibraryPage

APP=QApplication.instance() or QApplication([])


class NamedToolRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ods_tool_routes_',dir=Path(__file__).resolve().parents[3])
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.widgets=[]

    def tearDown(self):
        for page in self.widgets:
            page.close();page.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def test_every_declared_tool_tab_preserves_saved_settings(self):
        for factory in (OptimizePage,FieldsPage,AISearchPage,IndexShiftPage,LibraryPage):
            page=factory(self.store);self.widgets.append(page)
            before=self.store.portable_project()
            for route,destinations in page.tool_tabs.items():
                self.assertTrue(page.select_tool_tab(route),(factory.__name__,route))
                for tabs,index in destinations:
                    self.assertEqual(tabs.currentIndex(),index)
            self.assertFalse(page.select_tool_tab('missing-section'))
            self.assertEqual(self.store.portable_project(),before)

    def test_restored_ai_results_and_library_notes_are_explicit_tabs(self):
        ai=AISearchPage(self.store);library=LibraryPage(self.store)
        self.widgets.extend((ai,library))
        self.assertEqual(ai.result_tabs.count(),8)
        self.assertEqual(ai.result_tabs.indexOf(ai.field_plot),0)
        self.assertEqual(ai.result_tabs.indexOf(ai.results),4)
        self.assertEqual(library.tabs.count(),3)
        self.assertEqual(library.tabs.tabText(1),'Details & notes')
        self.assertEqual(library.tabs.tabText(2),'Back up & share')

    def test_index_editor_routes_to_shared_optical_sampling(self):
        page=IndexShiftPage(self.store);self.widgets.append(page)
        spy=QSignalSpy(page.routeRequested)
        from PyQt6.QtWidgets import QPushButton
        button=next(button for button in page.findChildren(QPushButton) if button.text()=='Edit optical sampling')
        button.click()
        self.assertEqual(list(spy),[['optical.sweep']])


if __name__=='__main__':
    unittest.main()
