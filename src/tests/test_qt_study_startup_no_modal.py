"""Restoring an active study must not execute an explicit editor action."""
import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QCoreApplication,QEvent
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_app import OpticalStudio
from qt_pcsel import PCSELPage

APP=QApplication.instance() or QApplication([])

class StudyStartupTests(unittest.TestCase):
    def test_restored_laser_opens_owning_setup_without_editor_modal(self):
        self.assertEqual(APP.platformName(),'offscreen')
        with tempfile.TemporaryDirectory(dir=os.environ.get('ODS_TEST_TMPDIR')) as temp:
            with patch.dict(os.environ,S4_LIBRARY_ROOT=temp),patch.object(PCSELPage,'_edit_laser_structure') as editor:
                store=ProjectStore(DataLibrary(Path(temp)/'library'),restore=False)
                store.study_navigation_enabled=True;store.activate_study('lumped_laser')
                window=OpticalStudio(store)
                try:
                    editor.assert_not_called()
                    self.assertEqual(store.active_study,'lumped_laser')
                    self.assertEqual(window.navigation.currentRow(),11)
                    self.assertIs(window.research_studies_page.stack.currentWidget(),window.research_studies_page._pages['lumped_laser'])
                    window._navigate_route(0)
                    editor.assert_called_once_with()
                finally:
                    window.hide();window.deleteLater();APP.processEvents()
                    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

if __name__=='__main__':unittest.main()
