"""Visible navigation must stay inside the selected simulation document."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_app import OpticalStudio
from qt_core import ProjectStore

APP=QApplication.instance() or QApplication([])


class ContextNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd())
        self.environment=patch.dict(os.environ,S4_LIBRARY_ROOT=self.temp.name)
        self.environment.start()
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.window=OpticalStudio(self.store)
        self.window.resize(1440,950)
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.hide()
        self.window.deleteLater()
        APP.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.environment.stop()
        self.temp.cleanup()

    def header(self,label):
        tabs=self.window.optical_workflow
        index=next(i for i in range(tabs.count()) if tabs.tabText(i)==label)
        self.window._navigate_header(index)
        APP.processEvents()

    def test_header_returns_to_owned_simulation_and_material_editor(self):
        for target in ('thermal','pcsel.cwt','sesame_transport.2d','photonic_bands.legume','tools.fields','fdtd','electrical.cv'):
            with self.subTest(target=target):
                self.window._open_simulation_choice(target)
                self.assertEqual(self.window.windowTitle(),'Optical Design Studio · '+self.window._study_title())
                expected_route,expected_engine=self.window._study_location()
                self.header('Settings')
                self.header('Simulation')
                self.assertEqual(self.store.active_study,target)
                self.assertEqual(self.window.stack.currentIndex(),expected_route)
                if expected_route==2:self.assertEqual(self.window.simulation_engines.currentIndex(),expected_engine)
                self.assertNotIn('Photonic Bands',[self.window.optical_workflow.tabText(i) for i in range(self.window.optical_workflow.count())])
        self.window._open_simulation_choice('photonic_bands.2d')
        self.window._navigate_route(1)
        self.assertEqual(self.window.stack.currentIndex(),10)
        self.assertEqual(self.store.active_study,'photonic_bands.2d')
        self.window._open_simulation_choice('papers')
        self.assertEqual(self.window.windowTitle(),'Optical Design Studio · Paper comparisons')
        self.assertEqual(self.window.active_simulation_label.text(),'Paper comparisons')
        self.assertFalse(self.window.transfer_inputs_button.isEnabled())

    def test_context_controls_visible_and_cross_family_strips_hidden(self):
        self.window._open_simulation_choice('fdtd')
        for width in (1440,800):
            self.window.resize(width,950)
            self.window.adapt_interface()
            APP.processEvents()
            self.assertTrue(self.window.simulation_picker_button.isVisible())
            self.assertTrue(self.window.transfer_inputs_button.isVisible())
            self.assertTrue(self.window.active_simulation_label.isVisible())
            self.assertIn('Time-domain optics',self.window.active_simulation_label.toolTip())
            self.assertTrue(all(not bar.isVisible() for bar in self.window.simulation_local_bars))

    def test_actual_results_header_click_returns_to_prior_setup(self):
        for target in ('fdtd','photonic_bands','sesame_transport.2d','thermal','pcsel.finite','lumped_laser','tools.sweep'):
            with self.subTest(target=target):
                self.window._open_simulation_choice(target)
                APP.processEvents()
                page=self.window._active_setup_page()
                navigation=self.window._embedded_result_navigation(page)
                previous=navigation[0].currentWidget() if navigation is not None else None
                header=self.window.optical_workflow
                for label in ('Results','Simulation','Settings','Simulation'):
                    index=next(i for i in range(header.count()) if header.tabText(i)==label)
                    QTest.mouseClick(header,Qt.MouseButton.LeftButton,pos=header.tabRect(index).center())
                    APP.processEvents()
                    self.assertEqual(header.tabText(header.currentIndex()),label)
                    self.assertEqual(self.store.active_study,target)
                    if label=='Simulation' and navigation is not None:
                        self.assertIs(navigation[0].currentWidget(),previous)
        self.window._open_simulation_choice('pcsel.finite')
        page=self.window._active_setup_page()
        self.header('Results')
        self.window._open_simulation_choice('pcsel.finite')
        self.assertIs(page.tabs.currentWidget(),page.results)
        self.assertEqual(header.tabText(header.currentIndex()),'Results')
        self.header('Simulation')
        self.assertIsNot(page.tabs.currentWidget(),page.results)

    def test_electrical_and_band_variants_keep_distinct_views(self):
        self.window._open_simulation_choice('electrical.iv')
        iv=self.window.electrical_page
        self.window._open_simulation_choice('electrical.cv')
        cv=self.window.electrical_page
        self.assertIsNot(iv,cv)
        self.window._open_simulation_choice('electrical.iv')
        self.assertIs(self.window.electrical_page,iv)
        self.assertIs(self.window.electrical_stack.currentWidget(),iv)
        self.window._open_simulation_choice('photonic_bands')
        three=self.window.photonic_bands_page
        three.show_stage('calculate')
        self.window._open_simulation_choice('photonic_bands.2d')
        two=self.window.photonic_bands_page
        self.assertIsNot(three,two)
        self.window._open_simulation_choice('photonic_bands')
        self.assertIs(self.window.photonic_bands_page,three)
        self.assertEqual(three._crystal_stage,'calculate')

    def test_builder_run_uses_document_instead_of_hidden_engine_and_results_are_scoped(self):
        self.window._open_simulation_choice('thermal')
        page=self.window.research_studies_page.stack.currentWidget()
        self.window._navigate_route(0)
        with patch.object(self.window.pages['Structure'],'apply_inspector',return_value=True),patch.object(page,'run') as run:
            self.window._run_active_workspace()
            run.assert_called_once_with()
        self.assertEqual(self.store.active_study,'thermal')
        self.assertEqual(self.window.stack.currentIndex(),11)
        self.window._open_simulation_choice('electrical')
        self.header('Results')
        dc_results=self.window.results_page
        self.window._open_simulation_choice('electrical.cv')
        self.header('Results')
        self.assertIsNot(self.window.results_page,dc_results)
        self.assertIsNone(self.window.results_page.directory)
        self.window._open_simulation_choice('photonic_bands')
        self.header('Results')
        self.assertEqual(self.window.stack.currentIndex(),10)
        self.assertIs(self.window.photonic_bands_page.tabs.currentWidget(),self.window.photonic_bands_page.results)


if __name__=='__main__':unittest.main()
