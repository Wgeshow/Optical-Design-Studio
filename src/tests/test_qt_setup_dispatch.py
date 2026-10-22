"""Complete native window dispatch, named destinations and staged-run contracts.

Job launch is mocked; all inputs use real project/state/solver preflight. This
keeps GUI dispatch failures distinguishable from numerical-runtime failures.
"""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
_import_library=tempfile.TemporaryDirectory(prefix='ods_dispatch_import_',dir=Path(__file__).resolve().parents[3])
os.environ.setdefault('S4_LIBRARY_ROOT',_import_library.name)

from PyQt6.QtCore import Qt, QCoreApplication, QEvent, QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit

from data_library import DataLibrary
from qt_core import ProjectStore
from qt_app import OpticalStudio
from tests.test_contact_optics import device as fixture_device, project as fixture_project

APP=QApplication.instance() or QApplication([])


class NativeSetupDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ods_setup_dispatch_',dir=Path(__file__).resolve().parents[3])
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        physical=fixture_device()
        physical['contacts'][1].update(optical_material_name='Au',optical_thickness_um=.1)
        project=fixture_project(physical)
        project['layers'][-1]['Material']='Air'
        project['settings'].update(wl_start_nm=1540.,wl_stop_nm=1560.,wl_step_nm=10.,NumG=9)
        project['performance']=dict(mode='CPU only',solver_backend='native',workers=1,threads=1,timeout_seconds=90)
        self.store.load_project(project)
        self.window=OpticalStudio(self.store)
        self.window.resize(1586,992)
        self.window.show()
        self.state=self.window.setup_state
        self.state.set('search.electrical.swept_contact_id','P')
        self.state.set('search.electrical.biases_V',[0.,-.1,-.2])
        for key,value in (('bias_start_V',-.2),('bias_stop_V',0.),('bias_step_V',.1)):
            self.state.set('ui.electrical.'+key,value)
        # This dispatch fixture intentionally supplies the same physical case
        # to three independent documents; navigation itself never copies it.
        configured=self.store.project()
        seed=configured['simulation_documents']['documents']['optical']
        for identifier in ('electrical','coupled'):
            configured['simulation_documents']['documents'][identifier]=copy.deepcopy(seed)
        self.store.load_project(configured)
        APP.processEvents()

    def tearDown(self):
        self.window.hide()
        self.window.deleteLater()
        APP.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def open_mode(self,mode,section=None):
        self.window._select_simulation_workflow(mode)
        page={'optical':self.window.optical_setup,'electrical':self.window.electrical_page,'coupled':self.window.coupled_page}[mode]
        if section:
            page.select_section(section)
        APP.processEvents()
        return page

    def editor(self,page,key):
        return next(widget for widget in page.widgets_by_key[key] if widget.isVisible())

    def enter(self,page,key,value):
        widget=self.editor(page,key)
        self.assertIsInstance(widget,QLineEdit)
        widget.setFocus();widget.selectAll()
        QTest.keyClicks(widget,str(value))
        QTest.keyClick(widget,Qt.Key.Key_Tab)
        APP.processEvents()

    def test_footer_runs_exactly_the_selected_mode_with_real_preflight(self):
        for mode,kind in (('optical','simulation'),('electrical','electrical'),('coupled','coupled')):
            with self.subTest(mode=mode):
                self.open_mode(mode)
                self.assertEqual(self.state.validate(mode),[])
                self.assertIn('Run '+mode+' simulation',self.window.run_button.text())
                with patch.object(self.store,'start_run') as start:
                    QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
                self.assertEqual(start.call_count,1)
                self.assertEqual(start.call_args.args[0],kind)
                if mode!='optical':
                    self.assertEqual(start.call_args.args[1]['optical_enabled'],mode=='coupled')

    def test_user_mode_buttons_roundtrip_and_run_dispatch_stay_aligned(self):
        self.open_mode('optical')
        current=self.window.optical_setup
        for mode,index in (('electrical',5),('coupled',6),('optical',0)):
            QTest.mouseClick(current.mode_buttons[mode],Qt.MouseButton.LeftButton)
            APP.processEvents()
            current={0:self.window.optical_setup,5:self.window.electrical_page,6:self.window.coupled_page}[index]
            self.assertEqual(self.window.simulation_engines.currentIndex(),index)
            self.assertEqual(current.current_mode,mode)
            with patch.object(self.store,'start_run') as start:
                QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
            self.assertEqual(start.call_count,1)
            self.assertEqual(start.call_args.args[0],'simulation' if mode=='optical' else mode)

    def test_current_manual_biases_and_iv_cv_checkboxes_stay_with_electrical_document(self):
        page=self.open_mode('electrical','electrical.study')
        mode=self.editor(page,'ui.electrical.sweep_mode')
        mode.setCurrentIndex(mode.findData('manual'))
        manual=self.editor(page,'ui.electrical.bias_list_text')
        self.assertIsInstance(manual,QPlainTextEdit)
        manual.setPlainText('0, -.05, -.15')
        page.select_section('electrical.outputs');APP.processEvents()
        for key in ('iv_enabled','cv_enabled'):
            widget=self.editor(page,'search.electrical.terminal_studies.'+key)
            if not widget.isChecked():QTest.mouseClick(widget,Qt.MouseButton.LeftButton,pos=QPoint(10,widget.height()//2))
        for mode,kind in (('electrical','electrical'),('coupled','coupled'),('electrical','electrical')):
            self.open_mode(mode)
            with patch.object(self.store,'start_run') as start:
                QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
            self.assertEqual(start.call_count,1)
            self.assertEqual(start.call_args.args[0],kind)
            options=start.call_args.args[1]
            if mode=='electrical':
                self.assertEqual(options['biases_V'],[0.,-.05,-.15])
                self.assertTrue(options['terminal_studies']['iv_enabled'])
                self.assertTrue(options['terminal_studies']['cv_enabled'])
            else:
                self.assertNotEqual(options['biases_V'],[0.,-.05,-.15])
                self.assertFalse(options['terminal_studies']['iv_enabled'])
                self.assertFalse(options['terminal_studies']['cv_enabled'])

    def test_current_range_is_submitted_without_apply_range_click(self):
        page=self.open_mode('electrical','electrical.study')
        selector=self.editor(page,'ui.electrical.sweep_mode')
        selector.setCurrentIndex(selector.findData('range'))
        APP.processEvents()
        self.enter(page,'ui.electrical.bias_start_V','-.18')
        self.enter(page,'ui.electrical.bias_stop_V','0')
        self.enter(page,'ui.electrical.bias_step_V','.06')
        with patch.object(self.store,'start_run') as start:
            QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
        self.assertEqual(start.call_count,1)
        actual=start.call_args.args[1]['biases_V']
        self.assertEqual(len(actual),4)
        for found,expected in zip(actual,[0.,-.18,-.12,-.06]):
            self.assertAlmostEqual(found,expected)

    def test_coupled_nested_optical_editor_keeps_coupled_dispatch(self):
        page=self.open_mode('coupled','coupled.optical-setup/optical.accuracy')
        self.enter(page,'settings.NumG','11')
        self.assertEqual(page.current_mode,'coupled')
        self.assertIn('coupled',self.window.run_button.text())
        with patch.object(self.store,'start_run') as start:
            QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
        self.assertEqual(start.call_args.args[0],'coupled')
        self.assertEqual(self.store.settings['NumG'],11)

    def test_phase_and_field_controls_have_real_separate_job_labels(self):
        page=self.open_mode('optical','optical.outputs')
        phase=self.editor(page,'search.simulation.measure_phase')
        fields=self.editor(page,'ui.optical.outputs.fields_enabled')
        self.assertIn('specular',phase.text().casefold())
        self.assertIn('E/H',fields.text())
        QTest.mouseClick(phase,Qt.MouseButton.LeftButton,pos=QPoint(10,phase.height()//2))
        self.assertTrue(self.state.job_options('optical')['measure_phase'])
        self.assertEqual(self.state.validate('optical'),[])
        with patch.object(self.store,'start_run') as start:
            QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
        self.assertEqual(start.call_args.args[0],'simulation')
        self.assertTrue(start.call_args.args[1]['measure_phase'])
        self.state.set('search.simulation.measure_phase',False)
        QTest.mouseClick(fields,Qt.MouseButton.LeftButton,pos=QPoint(10,fields.height()//2))
        self.assertEqual(self.state.get('ui.optical.outputs.execution_plan'),'spectrum_then_fields')

    def test_spectrum_field_sequence_preserves_immutable_project_and_loads_once(self):
        self.open_mode('optical')
        self.state.set('ui.optical.outputs.execution_plan','spectrum_then_fields')
        original=self.store.portable_project()
        directory=self.store.library.runs/'stage_spectrum'
        directory.mkdir()
        with patch.object(self.store,'start_run') as start,patch.object(self.window.results_page,'load_run') as load:
            self.window._run_setup_mode('optical')
            self.assertEqual(start.call_args.args[0],'simulation')
            self.store.update_settings(dict(NumG=13,wl_stop_nm=1580.))
            self.window._setup_run_finished(dict(run_kind='simulation',directory=str(directory),summary=dict(status='complete')))
            load.assert_not_called()
            self.window._setup_busy_changed(False)
            APP.processEvents()
            self.assertEqual(start.call_count,2)
            self.assertEqual(start.call_args.args[0],'simulation_fields')
            self.assertEqual(start.call_args.kwargs['project_snapshot'],original)
            self.assertEqual(start.call_args.args[1]['spectrum_id'],'stage_spectrum')
            self.window._setup_run_finished(dict(run_kind='simulation_fields',directory=str(directory),summary=dict(status='complete')))
            APP.processEvents()
            load.assert_called_once_with(str(directory))

    def test_cancelled_or_failed_spectrum_never_dispatches_field_stage(self):
        self.open_mode('optical')
        self.state.set('ui.optical.outputs.execution_plan','spectrum_then_fields')
        directory=self.store.library.runs/'cancelled_spectrum'
        directory.mkdir()
        with patch.object(self.store,'start_run') as start,patch.object(self.window.results_page,'load_run'):
            self.window._run_setup_mode('optical')
            self.window._setup_run_finished(dict(run_kind='simulation',directory=str(directory),summary=dict(status='cancelled')))
            self.window._setup_busy_changed(False)
            APP.processEvents()
            self.assertEqual(start.call_count,1)
            self.assertIsNone(self.window._pending_setup_fields)
            self.assertIsNone(self.window._queued_setup_fields)
            self.window._run_setup_mode('optical')
            self.window._setup_run_failed('Solver cancelled')
            self.window._setup_busy_changed(False)
            APP.processEvents()
            self.assertEqual(start.call_count,2)

    def test_finished_signal_opens_results_once(self):
        directory=self.store.library.runs/'electrical_complete'
        directory.mkdir()
        with patch.object(self.window.results_page,'load_run') as load:
            self.store.run_finished.emit(dict(run_kind='electrical',directory=str(directory),summary=dict(status='complete')))
            APP.processEvents()
            load.assert_called_once_with(str(directory))

    def test_named_tool_routes_select_exact_nested_tabs(self):
        expected=[
            ('tools.sweep.target.sampling','Optimize','target_advanced_tabs',0),
            ('tools.sweep.explore.learning','Optimize','general_detail_tabs',2),
            ('tools.sweep.explore.matches','Optimize','general_result_tabs',2),
            ('tools.ai.training','AI Search','setup_tabs',1),
            ('tools.ai.rta','AI Search','result_tabs',2),
            ('tools.ai.contours','AI Search','result_tabs',7),
            ('tools.fields.compare.measurements','Fields','comparison.tabs',1),
            ('tools.fields.playback','Fields','tabs',2),
            ('tools.library.details','Saved work','tabs',1),
            ('tools.library.sharing','Saved work','tabs',2)]
        for route,name,attribute,index in expected:
            with self.subTest(route=route):
                self.window._route_setup_action(route);APP.processEvents()
                page=self.window.pages[name]
                widget=page
                for part in attribute.split('.'):
                    widget=getattr(widget,part)
                self.assertEqual(widget.currentIndex(),index)
                self.assertTrue(page.isVisible())
        self.window._route_setup_action('tools.index_shift.shifts');APP.processEvents()
        self.assertEqual(self.window.index_shift_page.result_tabs.currentIndex(),2)
        self.assertTrue(self.window.index_shift_page.isVisible())

    def test_named_material_and_settings_aliases_select_exact_workspace(self):
        materials=self.window.pages['Materials']
        self.window._route_setup_action('materials.electrical');APP.processEvents()
        self.assertEqual(materials.workspace_tabs.currentIndex(),materials.electrical_tab_index)
        self.window._route_setup_action('materials.optical');APP.processEvents()
        self.assertEqual(materials.workspace_tabs.currentIndex(),0)
        settings=self.window.pages['Settings']
        for route,label in (('settings.appearance','Appearance'),('settings.performance','Execution defaults'),
            ('settings.storage','Storage & exports'),('settings.add-ons.meep','Solver runtimes'),('settings.add-ons','Add-ons')):
            self.window._route_setup_action(route);APP.processEvents()
            self.assertEqual(settings.settings_tabs.tabText(settings.settings_tabs.currentIndex()),label)


if __name__=='__main__':
    unittest.main()
