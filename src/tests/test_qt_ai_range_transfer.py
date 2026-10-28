"""Explicit AI range transfer respects independent simulation documents."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy,tempfile,unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_ai_search import AISearchPage
APP=QApplication.instance() or QApplication([])
RADIUS=dict(Parameter='radius',Target='1',Min=.08,Max=.12,Step=.02,Choices='')
LATTICE=dict(Parameter='lattice_square',Target='',Min=.7,Max=.8,Step=.05,Choices='')
class AiRangeTransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.getcwd());self.store=ProjectStore(DataLibrary(self.tmp.name),restore=False)
        self.store.study_navigation_enabled=True
        self.store.activate_study('tools.sweep');self.store.save_search('peaks',dict(bounds=[RADIUS]))
        self.source=copy.deepcopy(self.store.project())
        self.store.activate_study('tools.ai');self.page=AISearchPage(self.store)
        self.page.bounds.set_records([LATTICE]);self.page.save()
    def tearDown(self):
        self.page.close();self.page.deleteLater();APP.processEvents();self.tmp.cleanup()
    def test_copy_reads_source_document_and_preserves_geometry_and_other_options(self):
        geometry=self.store.patterns.copy(deep=True);basis=self.page.controls['basis'].value()
        source=self.store.study_project('tools.sweep')
        self.page.copy_ranges()
        self.assertEqual(self.page.bounds.records(),[RADIUS])
        self.assertEqual(self.store.study_project('tools.sweep'),source)
        self.assertEqual(self.store.active_study,'tools.ai')
        self.assertTrue(self.store.patterns.equals(geometry))
        self.assertEqual(self.page.controls['basis'].value(),basis)
        self.assertEqual(self.store.search_state['ai_search']['bounds'],[RADIUS])
    def test_empty_source_preserves_existing_ai_ranges_instead_of_using_local_legacy_data(self):
        self.store._study_documents['tools.sweep']['desktop_search']={}
        self.store.save_search('peaks',dict(bounds=[RADIUS]))
        self.page.copy_ranges()
        self.assertEqual(self.page.bounds.records(),[LATTICE])
        self.assertIn('No saved',self.page.status.text())
    def test_different_pattern_identity_is_not_silently_retargeted(self):
        source=self.store._study_documents['tools.sweep']
        source['patterns'][0]['CenterX_um']=.15
        self.page.copy_ranges()
        self.assertEqual(self.page.bounds.records(),[LATTICE])
        self.assertIn('Pattern targets differ',self.page.status.text())
    def test_restored_modes_refresh_conditional_editor_enablement(self):
        self.page.controls['mode'].setCurrentIndex(self.page.controls['mode'].findData('Full range scan'))
        self.assertFalse(self.page.controls['initial'].isEnabled())
        self.store.save_search('ai_search',dict(mode='Budgeted adaptive',approach='reference',reference_directory='reference-fields'))
        self.page.restore('study')
        self.assertTrue(self.page.controls['initial'].isEnabled())
        self.assertTrue(self.page.controls['adaptive'].isEnabled())
        self.assertTrue(self.page.reference.isEnabled())
        self.assertTrue(self.page.controls['reference_weight'].isEnabled())
        self.store.save_search('ai_search',dict(mode='Full range scan',approach='discover'))
        self.page.restore('study')
        self.assertFalse(self.page.controls['initial'].isEnabled())
        self.assertFalse(self.page.reference.isEnabled())

    def test_open_checkpoint_refreshes_conditional_editors(self):
        saved=dict(settings=dict(mode='Full range scan',approach='reference',reference_directory='reference-fields'),base={})
        with patch('qt_ai_search.QFileDialog.getOpenFileName',return_value=('campaign.json','')), patch('qt_ai_search.read_json',return_value=saved), patch.object(self.page,'load_campaign'):
            self.page.open_campaign()
        self.assertFalse(self.page.controls['initial'].isEnabled())
        self.assertTrue(self.page.reference.isEnabled())
        self.assertTrue(self.page.controls['reference_weight'].isEnabled())

    def test_open_relocated_checkpoint_passes_local_fields_without_starting_solver(self):
        import json
        from pathlib import Path
        root=Path(self.tmp.name)/'extracted';fields=root/'designs/000001/fields';fields.mkdir(parents=True)
        (fields/'field_features.json').write_text('{}')
        saved=dict(settings={},base={},records=[dict(measurement_key='one',field_directory='R:/removed/library/designs/000001/fields')])
        checkpoint=root/'campaign.json';checkpoint.write_text(json.dumps(saved));before=checkpoint.read_bytes()
        with patch('qt_ai_search.QFileDialog.getOpenFileName',return_value=(str(checkpoint),'')), patch.object(self.page,'load_campaign') as loaded, patch.object(self.store,'start_run') as run:
            self.page.open_campaign()
        run.assert_not_called();loaded.assert_called_once()
        self.assertEqual(Path(loaded.call_args.args[0]['records'][0]['field_directory']),fields.resolve())
        self.assertEqual(checkpoint.read_bytes(),before)
        self.assertEqual(self.store.active_study,'tools.ai')

    def test_shared_group_preserves_current_bounds_and_explains_scope(self):
        source=self.store._study_documents['tools.sweep']
        source['desktop_search']['peaks']['shared_hole']=dict(enabled=True,targets=[1],min_um=.08,max_um=.12,step_um=.02)
        self.page.copy_ranges()
        self.assertEqual(self.page.bounds.records(),[LATTICE])
        self.assertIn('Shared-radius',self.page.status.text())
if __name__=='__main__':unittest.main()
