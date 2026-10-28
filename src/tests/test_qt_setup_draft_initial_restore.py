"""First-created setup pages must restore drafts already loaded in the study bank."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace

APP = QApplication.instance() or QApplication([])


class InitialSetupDraftRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='initial-setup-draft-', dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.root = Path(self.temp.name)
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page.deleteLater()
        APP.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def store(self, name):
        return ProjectStore(DataLibrary(self.root/name), restore=False)

    def page(self, store, identity='electrical.iv', mode='electrical'):
        page = SimulationSetupWorkspace(store, mode=mode, document_id=identity)
        self.pages.append(page)
        return page  # Never shown and never run.

    def pending_project(self, identity='electrical.iv', mode='electrical'):
        store = self.store('writer-'+identity)
        store.activate_study(identity)
        page = self.page(store, identity, mode)
        page.widgets_by_key['device.mesh.nx'][0].setText('1e')
        page.widgets_by_key['ui.electrical.bias_list_text'][0].setPlainText('0, unfinished')
        table = page.tables_by_key['device.layers'][0]
        table.item(0, 4).setText('unfinished doping')
        page.flush_draft()
        expected = copy.deepcopy(store.search_state['research_workspaces']['setup_pending'][mode])
        return store.project(), expected

    def test_first_page_restores_saved_text_table_errors_without_committing(self):
        project, expected = self.pending_project()
        restored = self.store('restored')
        restored.load_project(project)
        committed = copy.deepcopy(restored.device)
        page = self.page(restored)
        self.assertEqual(page.drafts, expected['drafts'])
        self.assertEqual(page.draft_errors, expected['errors'])
        self.assertEqual(page.widgets_by_key['device.mesh.nx'][0].text(), '1e')
        self.assertEqual(page.widgets_by_key['ui.electrical.bias_list_text'][0].toPlainText(), '0, unfinished')
        self.assertEqual(page.tables_by_key['device.layers'][0].item(0, 4).text(), 'unfinished doping')
        self.assertEqual(restored.device, committed)
        page.flush_draft()
        self.assertEqual(restored.search_state['research_workspaces']['setup_pending']['electrical'], expected)

    def test_lazy_first_visit_restores_inactive_banked_document(self):
        project, expected = self.pending_project('electrical.cv')
        restored = self.store('bank')
        restored.load_project(project)
        restored.activate_study('electrical.iv')
        other = self.page(restored, 'electrical.iv')
        other.widgets_by_key['device.mesh.nx'][0].setText('77')
        other.widgets_by_key['device.mesh.nx'][0].editingFinished.emit()
        restored.activate_study('electrical.cv')  # Host constructs the lazy page after this event.
        page = self.page(restored, 'electrical.cv')
        self.assertEqual(page.drafts, expected['drafts'])
        self.assertEqual(page.widgets_by_key['device.mesh.nx'][0].text(), '1e')
        self.assertNotEqual(restored.device['mesh']['nx'], 77)

    def test_inactive_constructor_does_not_copy_or_flush_active_drafts(self):
        project, expected = self.pending_project()
        restored = self.store('inactive')
        restored.load_project(project)
        before = copy.deepcopy(restored.project())
        page = self.page(restored, 'electrical.cv')
        self.assertEqual(page.drafts, {})
        page.flush_draft()
        self.assertEqual(restored.project(), before)
        self.assertEqual(restored.search_state['research_workspaces']['setup_pending']['electrical'], expected)

    def test_coupled_first_page_restores_its_own_nested_electrical_drafts(self):
        project, expected = self.pending_project('coupled', 'coupled')
        restored = self.store('coupled-restored')
        restored.load_project(project)
        page = self.page(restored, 'coupled', 'coupled')
        self.assertEqual(page.drafts, expected['drafts'])
        self.assertEqual(page.widgets_by_key['device.mesh.nx'][0].text(), '1e')
        self.assertEqual(page.table_errors, {tuple(k): v for k,v in expected['table_errors']})


if __name__ == '__main__':
    unittest.main()
