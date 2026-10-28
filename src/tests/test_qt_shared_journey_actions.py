"""Review navigation must preserve selection and defer model mutations."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication,QComboBox,QLabel
from qt_input_diagnostics import DiagnosticPanel
from qt_study_library import StudyLibrary
from qt_study_transfer import StudyTransferDialog
from qt_core import ProjectStore
from data_library import DataLibrary
from benchmark_registry import list_benchmarks

APP=QApplication.instance() or QApplication([])


class SharedJourneyActionTests(unittest.TestCase):
    def test_research_check_is_invalidated_by_unfinished_input_before_save(self):
        from qt_pcsel_research_setup import PcselResearchWorkspace
        from research_catalog import list_capabilities
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3],prefix='journey-check-') as root:
            store=ProjectStore(DataLibrary(root),restore=False)
            capability=next(row for row in list_capabilities() if row['engine']=='pcsel')
            page=PcselResearchWorkspace(store,capability)
            review=page.journey_execution
            review.validation_status.setText('Inputs checked successfully')
            page.fields['grid_nm'].setText('1e-')
            self.assertIn('Inputs changed',review.validation_status.text())
            self.assertEqual(page.fields['grid_nm'].text(),'1e-')
            page.close();page.deleteLater();APP.processEvents()

    def test_issue_filter_goes_to_first_visible_exact_input(self):
        panel=DiagnosticPanel();received=[]
        panel.activated.connect(received.append)
        panel.set_diagnostics([
            dict(message='First',section='Contacts',object_id='P',field='voltage_V'),
            dict(message='Second',section='Mesh',object_id='cell',field='nx')])
        panel.group_filter.setCurrentIndex(panel.group_filter.findData('Mesh / cell'))
        panel.go_to_first()
        self.assertEqual(received[0]['field'],'nx')
        self.assertEqual(received[0]['object_id'],'cell')
        panel.close();panel.deleteLater();APP.processEvents()

    def test_transfer_preview_uses_real_conversion_without_changing_documents(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3],prefix='journey-transfer-') as root:
            store=ProjectStore(DataLibrary(root),restore=False)
            device=copy.deepcopy(store.device);device['width_um']=3.0
            store.set_device(device)
            store.activate_study('electrical')
            before=copy.deepcopy(store.project())
            dialog=StudyTransferDialog(store)
            dialog.source.setCurrentIndex(dialog.source.findData('optical'))
            self.assertGreater(dialog.preview.topLevelItemCount(),0)
            self.assertEqual(store.project(),before)
            self.assertIn('Contacts and doping',dialog.summary.text())
            dialog.close();dialog.deleteLater();APP.processEvents()

    def test_paper_journey_keeps_selection_and_opens_only_on_explicit_action(self):
        choices=QComboBox();open_editable=Mock();run_reference=Mock()
        page=StudyLibrary(choices,open_editable,run_reference,QLabel())
        page.set_cases(list_benchmarks())
        identity=choices.currentData()
        for stage in (1,2,0,2):page._show_paper_stage(stage)
        self.assertEqual(choices.currentData(),identity)
        open_editable.assert_not_called();run_reference.assert_not_called()
        page.edit_button.click();open_editable.assert_called_once()
        run_reference.assert_not_called()
        page.close();page.deleteLater();APP.processEvents()


if __name__=='__main__':unittest.main()
