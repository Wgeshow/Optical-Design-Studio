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

    def test_every_simulation_uses_its_own_canonical_stage_tabs(self):
        from simulation_documents import STUDY_IDS
        for target in (*STUDY_IDS, 'papers'):
            with self.subTest(target=target):
                self.window._open_simulation_choice(target)
                APP.processEvents()
                controller=self.window.study_navigation
                source=controller.source
                self.assertIsNotNone(source, target)
                self.assertEqual(controller.owner,target)
                self.assertEqual(self.window.optical_workflow.count(),len(source.stages))
                self.assertEqual([self.window.optical_workflow.tabText(i).replace('&&','&')
                    for i in range(self.window.optical_workflow.count())],
                    [stage['title'] for stage in source.stages])
                self.assertFalse(source.isVisible())
                for index in range(len(source.stages)):
                    self.window._navigate_header(index)
                    APP.processEvents()
                    self.assertEqual(source._current,index,(target,index))
                    self.assertEqual(controller.current,index,(target,index))
                    if target!='papers':self.assertEqual(self.store.active_study,target)
                self.assertFalse(source.isVisible())
                self.assertNotIn('Settings',[stage['title'] for stage in source.stages])

    def test_global_utilities_return_to_the_exact_simulation_stage(self):
        for target in ('electrical.cv','photonic_bands.legume','thermal','pcsel.cwt','fdtd','papers'):
            with self.subTest(target=target):
                self.window._open_simulation_choice(target)
                controller=self.window.study_navigation
                selected=min(4,len(controller.source.stages)-1)
                controller.request(selected)
                source=controller.source
                for route in (6,7):
                    self.window._navigate_route(route)
                    APP.processEvents()
                    self.assertEqual(controller.current,-1)
                    self.assertFalse(self.window.optical_workflow.isVisible())
                    self.assertTrue(controller.return_button.isVisible())
                    self.assertEqual(source._current,selected)
                    QTest.mouseClick(controller.return_button,Qt.MouseButton.LeftButton)
                    APP.processEvents()
                    self.assertIs(controller.source,source)
                    self.assertEqual(controller.current,selected)
                    if target!='papers':self.assertEqual(self.store.active_study,target)
        self.assertEqual(self.window.windowTitle(),'Optical Design Studio · Paper comparisons')
        self.assertFalse(self.window.transfer_inputs_button.isEnabled())

    def test_responsive_workflow_never_duplicates_or_clips_navigation(self):
        self.window._open_simulation_choice('electrical')
        controller=self.window.study_navigation
        for width in (1920,800):
            self.window.resize(width,950)
            self.window.adapt_interface()
            APP.processEvents()
            self.assertTrue(self.window.simulation_picker_button.isVisible())
            self.assertTrue(self.window.transfer_inputs_button.isVisible())
            self.assertTrue(self.window.active_simulation_label.isVisible())
            self.assertTrue(self.window.workflow_navigation.isVisible())
            self.assertFalse(controller.source.isVisible())
            self.assertTrue(all(not bar.isVisible() for bar in self.window.simulation_local_bars))
            self.assertEqual(controller.selector.isVisible(),width==800)
            self.assertEqual(controller.tabs.isVisible(),width==1920)
            if width==1920:
                QTest.mouseClick(controller.tabs,Qt.MouseButton.LeftButton,pos=controller.tabs.tabRect(1).center())
                APP.processEvents()
                self.assertEqual(controller.source._current,1)
        controller.selector.setCurrentIndex(2)
        controller.selector.activated.emit(2)
        APP.processEvents()
        self.assertEqual(controller.source._current,2)
        QTest.mouseClick(controller.next,Qt.MouseButton.LeftButton)
        APP.processEvents()
        self.assertEqual(controller.source._current,3)
        QTest.mouseClick(controller.previous,Qt.MouseButton.LeftButton)
        APP.processEvents()
        self.assertEqual(controller.source._current,2)

    def test_selected_stage_click_reopens_canonical_device_editor_once(self):
        self.window._open_simulation_choice('optical')
        self.window.resize(1920,950);self.window.adapt_interface();APP.processEvents()
        flow=self.window.optical_setup.setup_flow
        flow.show_device_settings();APP.processEvents()
        controller=self.window.study_navigation
        self.assertEqual(controller.current,0)
        requests=[];controller.source.stageRequested.connect(requests.append)
        QTest.mouseClick(controller.tabs,Qt.MouseButton.LeftButton,pos=controller.tabs.tabRect(0).center())
        APP.processEvents()
        self.assertEqual(requests,[0])
        self.assertIs(flow.views.currentWidget(),flow.device_editor)
        QTest.mouseClick(controller.tabs,Qt.MouseButton.LeftButton,pos=controller.tabs.tabRect(1).center())
        APP.processEvents()
        self.assertEqual(requests,[0,1])
        self.assertEqual(controller.source._current,1)

    def test_full_editors_are_owned_stage_subviews(self):
        for target in ('optical','electrical.iv','thermal'):
            with self.subTest(target=target):
                self.window._open_simulation_choice(target)
                controller=self.window.study_navigation
                for route in (0,1):
                    self.window._navigate_route(route)
                    APP.processEvents()
                    self.assertEqual(self.window.stack.currentIndex(),route)
                    self.assertEqual(controller.current,controller.editor_stage(route))
                    self.assertEqual(self.store.active_study,target)
                    editor=self.window.stack.currentWidget()
                    self.window._navigate_route(6)
                    controller.return_to_study()
                    self.assertIs(self.window.stack.currentWidget(),editor)
                    controller.request(controller.current)
                    self.assertEqual(self.window.stack.currentIndex(),self.window._study_location()[0])
        self.window._open_simulation_choice('photonic_bands.2d')
        self.window._navigate_route(1)
        self.assertEqual(self.window.stack.currentIndex(),10)
        self.assertEqual(self.store.active_study,'photonic_bands.2d')

    def test_results_are_the_actual_owned_flow_stage(self):
        for target in ('optical','electrical','electrical.cv','coupled','fdtd','photonic_bands',
                       'sesame_transport.2d','thermal','pcsel.finite','lumped_laser','tools.sweep'):
            with self.subTest(target=target):
                self.window._open_simulation_choice(target)
                page=self.window._active_setup_page()
                controller=self.window.study_navigation
                index=next(i for i,s in enumerate(controller.source.stages) if 'result' in s['title'].lower())
                self.window._open_active_results()
                APP.processEvents()
                self.assertEqual(self.window.stack.currentIndex(),self.window._study_location()[0])
                self.assertEqual(controller.current,index)
                self.assertEqual(controller.source._current,index)
                self.assertIs(self.window._active_setup_page(),page)
                controller.request(0)
                self.assertEqual(controller.source._current,0)
                self.assertEqual(self.store.active_study,target)

    def test_legacy_optical_links_use_native_meep_and_ai_inputs(self):
        from PyQt6.QtWidgets import QPushButton
        self.window._open_simulation_choice('fdtd')
        page=self.window.fdtd_page
        with patch.object(self.store,'start_run') as start:
            for suffix,stage in [('overview','structure'),('domain','structure'),('incident','parameters'),
                                 ('sweep','parameters'),('accuracy','structure'),('outputs','stopping'),('materials','structure')]:
                page.routeRequested.emit('optical.'+suffix);APP.processEvents()
                self.assertEqual(self.store.active_study,'fdtd')
                self.assertEqual(self.window.simulation_engines.currentIndex(),1)
                self.assertEqual(self.window.study_navigation.current,page.optical_journey.keys[stage])
                self.assertFalse(self.window.optical_setup.isVisible())
            page.controls['wavelength_min_nm'].setValue(1222.5)
            self.assertEqual(page.options()['wavelength_min_nm'],1222.5)
            start.assert_not_called()
        self.window._open_simulation_choice('tools.ai')
        page=self.window.pages['AI Search']
        button=next(b for b in page.findChildren(QPushButton)
                    if b.text()=='Edit shared optical setup')
        button.click();APP.processEvents()
        self.assertEqual(self.window.stack.currentIndex(),8)
        page.controls['wavelength_nm'].setValue(1444.5)
        self.assertEqual(page.options()['wavelength_nm'],1444.5)
        self.assertEqual(self.store.active_study,'tools.ai')

    def test_tool_parameter_links_edit_only_own_document_and_run_own_solver(self):
        from PyQt6.QtWidgets import QPushButton
        editors={}
        for number,(target,label,key) in enumerate((('tools.index_shift','Edit optical sampling','settings.wl_start_nm'),
                ('tools.fields','Edit optical excitation','settings.theta_deg'),
                ('tools.sweep','Edit optical sampling','settings.wl_start_nm'))):
            with self.subTest(target=target):
                self.window._open_simulation_choice(target)
                owner=self.window._active_setup_page()
                button=next(b for b in owner.findChildren(QPushButton) if b.text()==label)
                button.click();APP.processEvents()
                editor=self.window._optical_parameter_pages[target];editors[target]=editor
                self.assertIs(self.window.simulation_engines.currentWidget(),editor)
                self.assertEqual(editor._bound_study_id,target)
                self.assertTrue(editor._is_active_document())
                self.assertTrue(self.window.study_navigation.parameter_return.isVisible())
                self.assertFalse(editor.setup_flow.journey_bar.isVisible())
                field=next(f for f in editor.fields if f.key==key)
                field.editor.setText(str(11.5 if target=='tools.fields' else 1300.5+number))
                field.commit();APP.processEvents()
                self.assertEqual(self.store.settings[key.split('.')[-1]],11.5 if target=='tools.fields' else 1300.5+number)
                self.window._navigate_route(6)
                self.window.study_navigation.return_to_study();APP.processEvents()
                self.assertIs(self.window.simulation_engines.currentWidget(),editor)
                with patch.object(owner,'run_peaks' if target=='tools.sweep' else 'run') as run:
                    self.window.run_button.click();APP.processEvents()
                    run.assert_called_once_with()
                self.assertEqual(self.store.active_study,target)
                self.assertEqual(self.window.stack.currentIndex(),self.window._study_location()[0])
                if self.window.stack.currentIndex()==2:
                    self.assertEqual(self.window.simulation_engines.currentIndex(),self.window._study_location()[1])
        self.window._open_simulation_choice('tools.index_shift')
        self.window.index_shift_page.routeRequested.emit('optical.sweep');APP.processEvents()
        self.assertIs(self.window.simulation_engines.currentWidget(),editors['tools.index_shift'])
        self.assertEqual(self.store.settings['wl_start_nm'],1300.5)
        field=next(f for f in editors['tools.index_shift'].fields if f.key=='settings.wl_start_nm')
        field.editor.setText('1e-');field.commit()
        self.window._open_simulation_choice('tools.fields')
        self.window._open_simulation_choice('tools.index_shift')
        self.window.index_shift_page.routeRequested.emit('optical.sweep');APP.processEvents()
        self.assertEqual(field.editor.text(),'1e-')
        self.assertEqual(self.store.settings['wl_start_nm'],1300.5)
        self.window.study_navigation.request(0);APP.processEvents()
        self.assertEqual(self.window.simulation_engines.currentIndex(),2)
        self.window._open_simulation_choice('optical')
        self.assertNotEqual(self.store.settings['wl_start_nm'],1300.5)

    def test_optical_engine_actions_open_independent_studies_without_running(self):
        self.window._open_simulation_choice('optical')
        self.store.update_settings({'wl_start_nm':1234.5})
        with patch.object(self.store,'start_run') as start:
            self.window._dispatch_setup_action('engine.meep')
            self.assertEqual(self.store.active_study,'fdtd')
            self.window._dispatch_setup_action('engine.s4')
            self.assertEqual(self.store.active_study,'optical')
            self.assertEqual(self.store.settings['wl_start_nm'],1234.5)
            self.window.study_navigation.request(2)
            self.assertEqual(self.store.active_study,'optical')
            start.assert_not_called()
        with patch.object(self.window.setup_state,'get',return_value='meep'), \
             patch.object(self.window.setup_state,'validate') as validate, \
             patch.object(self.window.fdtd_page,'run') as run, \
             patch.object(self.window,'show_error') as error:
            self.window._run_setup_mode('optical')
            validate.assert_not_called();run.assert_not_called()
            error.assert_called_once_with('Open Meep · time-domain optics to run its separate setup.')

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
        self.window._open_active_results()
        dc_results=self.window.electrical_page.setup_flow
        self.window._open_simulation_choice('electrical.cv')
        self.window._open_active_results()
        self.assertIsNot(self.window.electrical_page.setup_flow,dc_results)
        self.assertEqual(self.window.electrical_page.setup_flow.journey_bar._current,5)
        self.window._open_simulation_choice('photonic_bands')
        self.window._open_active_results()
        self.assertEqual(self.window.stack.currentIndex(),10)
        self.assertIs(self.window.photonic_bands_page.tabs.currentWidget(),self.window.photonic_bands_page.results)


class InitialStudyNavigationTests(unittest.TestCase):
    def test_last_window_page_cannot_replace_loaded_project_study(self):
        from qt_common import preferences
        with tempfile.TemporaryDirectory(dir=Path.cwd(),prefix='study-start-') as root, \
             patch.dict(os.environ,S4_LIBRARY_ROOT=root):
            for previous_page,active in ((8,'optical'),(10,'electrical.iv')):
                with self.subTest(previous_page=previous_page,active=active):
                    prefs=preferences();prefs.setValue('page',previous_page);prefs.sync()
                    store=ProjectStore(DataLibrary(Path(root)/active),restore=False)
                    store.activate_study(active)
                    store.update_settings(dict(wl_start_nm=1432.5,ax_um=3.21))
                    before=store.study_project(active)
                    window=OpticalStudio(store);window.show();APP.processEvents()
                    try:
                        self.assertEqual(store.active_study,active)
                        self.assertEqual(store.settings['wl_start_nm'],1432.5)
                        self.assertEqual(store.device,before['device'])
                        window._open_active_setup();APP.processEvents()
                        self.assertEqual(window.stack.currentIndex(),2)
                        self.assertEqual(window.simulation_engines.currentIndex(),0 if active=='optical' else 5)
                    finally:
                        window.hide();window.deleteLater();APP.processEvents()
                        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


if __name__=='__main__':unittest.main()
