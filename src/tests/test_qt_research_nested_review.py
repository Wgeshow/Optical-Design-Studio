"""Research review includes typed arrays/objects without parsing or dropping drafts."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QCoreApplication,QEvent,Qt
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from device_model import default_device
from qt_core import ProjectStore
from qt_research_studies import StructuredValueEditor
from qt_transport_research_setup import TransportResearchWorkspace,HighFieldOpticsWorkspace
from qt_research_journey import _structured_review_value


class ResearchNestedReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nested-review-')
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.guard=patch.object(self.store,'start_run',side_effect=AssertionError('No solver/job permitted'));self.guard.start()
        self.pages=[]

    def tearDown(self):
        for page in self.pages:
            timer=getattr(page,'_save_timer',None)
            if timer is not None:timer.stop()
            page.close();page.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.app.processEvents();self.guard.stop();self.temp.cleanup()

    def transport(self):
        self.store.activate_study('advanced_transport')
        self.store.set_device(default_device(self.store.electrical_materials))
        page=TransportResearchWorkspace(self.store,dict(engine='advanced_transport',study='finite_contact',label='Finite contacts',limitations=[]),document_id='advanced_transport')
        self.pages.append(page)
        page.structured['biases_V'].set_value([0.,-.01,-.02])
        page.structured['contacts'].set_value({'contact_p':dict(electron_resistivity_ohm_cm2=2e-7,hole_resistivity_ohm_cm2=3e-7)})
        page.fields['parameter_source'].setText('Synthetic UI test inputs')
        page.select_section('__journey_check');page.journey_execution.refresh()
        return page

    def rows(self,page):
        tree=page.journey_execution.inputs
        return {tree.topLevelItem(i).text(0):tree.topLevelItem(i) for i in range(tree.topLevelItemCount())}

    def test_transport_review_includes_biases_and_contact_arrays_with_editor_routes(self):
        page=self.transport();before=copy.deepcopy(page.draft())
        rows=self.rows(page)
        biases=rows['Bias sequence (V)'];contacts=rows['Contact carrier resistivities (ohm cm²)']
        self.assertIn('3 items',biases.text(1));self.assertIn('-0.02',biases.text(1))
        self.assertIn('2e-07',contacts.text(1));self.assertIn('3e-07',contacts.text(1))
        self.assertGreaterEqual(len(rows),len(page.fields))
        self.assertEqual(page.draft(),before)
        page.journey_execution._open(biases)
        self.assertEqual(page.tabs.currentIndex(),page.sections['Bias'])
        page.select_section('__journey_check');page.journey_execution._open(self.rows(page)['Contact carrier resistivities (ohm cm²)'])
        self.assertEqual(page.tabs.currentIndex(),page.sections['Contacts'])

    def test_incomplete_typed_number_is_reviewed_verbatim_and_invalidates_check(self):
        page=self.transport();panels=page.journey_execution
        panels.validation_status.setText('Inputs checked')
        root=page.structured['biases_V'].tree.topLevelItem(0)
        root.child(1).setText(1,'unfinished')
        self.assertIn('Inputs changed',panels.validation_status.text())
        panels.refresh()
        self.assertIn('unfinished',self.rows(page)['Bias sequence (V)'].text(1))
        self.assertEqual(root.child(1).text(1),'unfinished')
        with self.assertRaises(ValueError):page.structured['biases_V'].value()

    def test_large_nested_review_is_bounded_and_explicit_about_remaining_values(self):
        editor=StructuredValueEditor([dict(id=str(i),value=i,source='x'*500) for i in range(100)],'samples')
        self.pages.append(editor)
        before=copy.deepcopy(editor.draft())
        summary=_structured_review_value(editor)
        self.assertTrue(summary.startswith('100 items'))
        self.assertIn('Open editor for all values',summary)
        self.assertLess(len(summary),680)
        self.assertEqual(editor.draft(),before)

    def test_high_field_review_includes_wavelengths_material_and_samples(self):
        self.store.activate_study('high_field_optics')
        page=HighFieldOpticsWorkspace(self.store,dict(engine='high_field_optics',study='franz_keldysh',label='High-field optics',limitations=[]),document_id='high_field_optics')
        self.pages.append(page)
        page.structured['wavelengths_nm'].set_value([850.,900.])
        page.structured['material'].set_value(dict(electron_mass_ratio=.067,reference_gap_eV=1.42))
        page.structured['samples'].set_value([dict(id='state-1',field_V_m=1e7,temperature_K=300.)])
        page.select_section('__journey_check');page.journey_execution.refresh()
        values='\n'.join(item.text(0)+': '+item.text(1) for item in self.rows(page).values())
        for expected in ('Wavelength samples (nm)','850.0','900.0','electron_mass_ratio','0.067','state-1','10000000.0'):
            self.assertIn(expected,values)

    def test_specialized_pcsel_review_is_not_replaced(self):
        page=self.transport()
        expected=[('custom','Selected model only','unchanged')]
        with patch.object(page,'journey_review_fields',return_value=expected,create=True):
            self.assertEqual(page.journey_execution._review_rows(),expected)


if __name__=='__main__':unittest.main()

