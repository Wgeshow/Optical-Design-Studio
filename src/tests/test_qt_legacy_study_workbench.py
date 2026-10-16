"""The clean legacy shell preserves editable inputs and actual result views."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_fdtd import FDTDPage
from qt_index_shift import IndexShiftPage
from qt_compute import FieldsPage
from qt_pcsel import PCSELPage
from qt_common import theme_manager

APP=QApplication.instance() or QApplication([])


class LegacyStudyWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.environment=patch.dict(os.environ,S4_LIBRARY_ROOT=str(self.root/'preferences'))
        self.environment.start()
        theme_manager().apply_look('light',persist=False)
        self.store=ProjectStore(DataLibrary(self.root/'library'),restore=False)
        self.pages=[]

    def page(self,cls):
        page=cls(self.store);self.pages.append(page)
        page.resize(800,760);page.show();APP.processEvents()
        return page

    def tearDown(self):
        for page in self.pages:page.hide();page.deleteLater()
        APP.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.environment.stop();self.temporary.cleanup()

    def test_native_geometry_steps_and_parameter_tabs_fit_compact_window_without_changing_inputs(self):
        for cls in (FDTDPage,IndexShiftPage,FieldsPage):
            with self.subTest(page=cls.__name__):
                page=self.page(cls);work=page.workbench
                before=copy.deepcopy(page.options());device=copy.deepcopy(self.store.device)
                self.assertEqual((page.width(),page.height()),(800,760))
                self.assertEqual(work.splitter.count(),3)
                self.assertEqual(work.input_scroll.horizontalScrollBar().maximum(),0)
                self.assertTrue(work.preview.isVisible())
                self.assertTrue(all(not button.icon().isNull() for button in work.step_buttons))
                for index in range(3):work.step_buttons[index].click();APP.processEvents()
                for index in range(work.input_tabs.count()):
                    work.input_tabs.setCurrentIndex(index);APP.processEvents()
                    self.assertEqual(work.input_tabs.currentWidget().horizontalScrollBar().maximum(),0)
                work.projection.setCurrentIndex(1);work.objects.setCurrentItem(work.objects.topLevelItem(1))
                self.assertEqual(page.options(),before)
                self.assertEqual(self.store.device,device)
                route=QSignalSpy(page.routeRequested);work.edit_geometry.click()
                self.assertEqual(route[0][0],'structure.original')

    def test_existing_result_routes_reveal_results_and_every_field_control_remains_live(self):
        fields=self.page(FieldsPage)
        fields.wavelength.setValue(977.5);fields.grid.setValue(31);fields.depth.setValue(7)
        self.assertEqual(fields.options()['wavelength_nm'],977.5)
        self.assertEqual(fields.options()['grid'],31)
        self.assertEqual(fields.options()['depth_samples'],7)
        self.assertTrue(fields.select_tool_tab('volume'))
        self.assertEqual(fields.workbench.views.currentIndex(),1)
        self.assertEqual(fields.tabs.currentIndex(),2)
        fields.select_tool_tab('')
        self.assertEqual(fields.workbench.views.currentIndex(),0)
        index=self.page(IndexShiftPage)
        self.assertTrue(index.select_tool_tab('response'))
        self.assertEqual(index.workbench.views.currentIndex(),1)
        index.select_tool_tab('')
        self.assertEqual(index.workbench.views.currentIndex(),0)
        fdtd=self.page(FDTDPage)
        fdtd.controls['dimensions'].setCurrentIndex(1)
        fdtd.controls['resolution'].setValue(42)
        self.assertEqual(fdtd.options()['dimensions'],3)
        self.assertEqual(fdtd.options()['resolution'],42)
        self.assertFalse(fdtd.controls['section_y_um'].isEnabled())

    def test_lumped_laser_inputs_are_complete_and_geometry_stays_independent(self):
        device=copy.deepcopy(self.store.device)
        page=self.page(PCSELPage)
        self.assertIsNone(page.last_result)
        self.assertEqual(page.workbench.views.currentIndex(),0)
        self.assertEqual(page.model_views.currentIndex(),0)
        page.transparency_temperature.setValue(.0031)
        page.gain_temperature.setValue(.0019)
        page.thermal_resistance.setValue(0.)
        parameters=page.laser_parameters()
        self.assertEqual(parameters.transparency_temperature_coefficient_k,.0031)
        self.assertEqual(parameters.differential_gain_temperature_coefficient_k,.0019)
        self.assertEqual(parameters.thermal_resistance_k_w,0.)
        self.assertEqual(self.store.device,device)
        for index in range(page.workbench.input_tabs.count()):
            page.workbench.input_tabs.setCurrentIndex(index);APP.processEvents()
            self.assertEqual(page.workbench.input_tabs.currentWidget().horizontalScrollBar().maximum(),0)
        result=page.run_simulation()
        self.assertIsNotNone(result)
        self.assertEqual(page.workbench.views.currentIndex(),1)
        self.assertFalse(result['thermal']['enabled'])


if __name__=='__main__':unittest.main()
