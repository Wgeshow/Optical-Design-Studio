"""Each selectable research type owns its controls, diagnostics and results."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QCoreApplication,QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_research_studies import ResearchStudiesWorkspace

APP=QApplication.instance() or QApplication([])


class ResearchWorkspaceIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.store.study_navigation_enabled=True
        self.host=ResearchStudiesWorkspace(self.store)
        self.host.set_embedded(True)
        self.host.show()

    def tearDown(self):
        self.host.hide();self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        APP.processEvents();self.temp.cleanup()

    def open(self,identifier):
        self.host.flush_draft()
        self.store.activate_study(identifier)
        self.host.select_engine(identifier.split('.')[0])
        APP.processEvents()
        return self.host.stack.currentWidget()

    def test_every_pcsel_type_has_its_own_editor_and_result_workspace(self):
        pages=[]
        models=('vertical','cwt','finite','beam','aperture','gme','rcwa_poles')
        for index,model in enumerate(models):
            page=self.open('pcsel.'+model);pages.append(page)
            page.fields['lattice_nm'].setText(str(410+index))
            page.status.setText(model+' diagnostic')
            self.assertEqual(page.fields['model'].currentData(),model)
            self.assertTrue(page.fields['model'].isHidden())
            self.assertTrue(self.host.navigation_row.isHidden())
        self.assertEqual(len(set(pages)),len(models))
        self.assertEqual(len({page.results for page in pages}),len(models))
        for index,model in enumerate(models):
            page=self.open('pcsel.'+model)
            self.assertIs(page,pages[index])
            self.assertEqual(page.fields['lattice_nm'].text(),str(410+index))
            self.assertEqual(page.status.text(),model+' diagnostic')

    def test_inactive_editor_signals_and_timer_cannot_write_to_current_study(self):
        vertical=self.open('pcsel.vertical')
        vertical.fields['lattice_nm'].setText('431')
        cwt=self.open('pcsel.cwt')
        cwt.fields['lattice_nm'].setText('544');cwt.flush_draft()
        current=copy.deepcopy(self.store.search_state)
        vertical.fields['lattice_nm'].setText('999')
        vertical._save_timer.start();vertical.save_draft()
        QTest.qWait(220)
        self.assertEqual(self.store.search_state,current)
        self.assertFalse(vertical.validate_inputs())
        self.assertEqual(self.open('pcsel.vertical').fields['lattice_nm'].text(),'431')

    def test_transport_dimensions_have_distinct_controls_and_diagnostics(self):
        one=self.open('sesame_transport')
        one.x_nodes.setText('0, .5, 1');one.status.setText('1D diagnostic')
        two=self.open('sesame_transport.2d')
        two.x_nodes.setText('0, 1, 2');two.status.setText('2D diagnostic')
        self.assertIsNot(one,two)
        self.assertIsNot(one.results,two.results)
        self.assertEqual(two.dimension.currentData(),2)
        self.assertTrue(two.dimension.isHidden())
        self.assertIs(self.open('sesame_transport'),one)
        self.assertEqual(one.dimension.currentData(),1)
        self.assertEqual(one.x_nodes.text(),'0, .5, 1')
        self.assertEqual(one.status.text(),'1D diagnostic')
        self.assertIs(self.open('sesame_transport.2d'),two)
        self.assertEqual(two.x_nodes.text(),'0, 1, 2')
        self.assertEqual(two.status.text(),'2D diagnostic')
        with self.assertRaisesRegex(ValueError,'other transport dimension'):
            two.load_settings({'dimension':1})

    def test_partial_draft_defaults_and_model_identity_do_not_inherit_old_values(self):
        page=self.open('pcsel.cwt')
        default=page._default_draft['fields']['harmonics']
        page.fields['harmonics'].setText('8');page.flush_draft()
        project=self.store.project()
        saved=project['desktop_search']['research_workspaces'][page.state_key]
        saved['fields'].pop('harmonics');saved['fields']['model']='beam'
        self.store.replace_active_study(project)
        self.assertEqual(page.fields['harmonics'].text(),str(default))
        self.assertEqual(page.fields['model'].currentData(),'cwt')
        with self.assertRaisesRegex(ValueError,'different simulation type'):
            page.load_settings({'model':'beam'})

    def test_nonresearch_project_restore_does_not_create_research_drafts(self):
        self.open('pcsel.cwt')
        self.store.activate_study('optical')
        self.store.replace_active_study(self.store._study_seed)
        before=copy.deepcopy(self.store.search_state)
        self.host.refresh();QTest.qWait(220)
        self.assertEqual(self.store.search_state,before)


if __name__=='__main__':unittest.main()
