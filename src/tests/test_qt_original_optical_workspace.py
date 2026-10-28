"""The original optical UI remains an independent, usable native workspace.

Dispatch tests use real controls and shared project state; the final test runs
real S4 spectrum/phase and manual fields through the original user interface.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('S4_DLL_DIRS','C:/codes/Optical Design Studio/_internal')
_import_library=tempfile.TemporaryDirectory(prefix='ods_original_import_',dir=Path(__file__).resolve().parents[3])
os.environ.setdefault('S4_LIBRARY_ROOT',_import_library.name)

from PyQt6.QtCore import Qt,QCoreApplication,QEvent,QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore,prepare_job
from qt_compute import SimulationPage
from qt_device_builder import DeviceBuilderPage
from qt_app import OpticalStudio
from qt_common import theme_manager
from tests.test_contact_optics import device,project

APP=QApplication.instance() or QApplication([])


class NativeOriginalOpticalWorkspaceTests(unittest.TestCase):
    def setUp(self):
        theme_manager().apply('dark',persist=False)
        self.temp=tempfile.TemporaryDirectory(prefix='ods_original_workspace_',dir=Path(__file__).resolve().parents[3])
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        physical=device();physical['contacts'][1].update(optical_material_name='Au',optical_thickness_um=.1)
        value=project(physical);value['layers'][-1]['Material']='Air'
        value['settings'].update(NumG=9,wl_start_nm=1549.,wl_stop_nm=1551.,wl_step_nm=1.)
        value['performance']=dict(mode='CPU only',solver_backend='native',workers=1,threads=1,timeout_seconds=90)
        self.store.load_project(value)
        self.window=OpticalStudio(self.store);self.window.resize(1586,992);self.window.show()
        self.window.set_workspace_profile('original_optical')
        self.window._navigate_route(2)
        self.page=self.window.pages['Simulate']
        self.events=[];self.errors=[]
        self.store.run_finished.connect(self.events.append);self.store.run_failed.connect(self.errors.append)
        APP.processEvents()

    def tearDown(self):
        if self.store.busy:
            self.store.cancel();deadline=time.monotonic()+10
            while self.store.busy and time.monotonic()<deadline:QTest.qWait(20)
        self.window.hide();self.window.deleteLater();APP.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def enter_number(self,widget,value):
        widget.setFocus();widget.selectAll();QTest.keyClicks(widget,str(value))
        QTest.keyClick(widget,Qt.Key.Key_Tab);APP.processEvents()

    def wait_finished(self,count):
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            QTest.qWait(30)
            if self.errors:break
            if len(self.events)==count and not self.store.busy:
                APP.processEvents();break
        self.assertEqual(self.errors,[]);self.assertFalse(self.store.busy)
        self.assertEqual(len(self.events),count)

    def test_original_profile_restores_exact_pages_and_original_result_tabs(self):
        self.assertEqual(self.window.workspace_profile,'original')
        self.assertIsInstance(self.page,SimulationPage)
        self.assertEqual(self.window.simulation_engines.currentIndex(),7)
        self.assertIs(self.window.simulation_engines.widget(7),self.page)
        self.assertTrue(self.page.isVisible());self.assertFalse(self.window.optical_setup.isVisible())
        self.assertEqual([self.page.result_tabs.tabText(i) for i in range(self.page.result_tabs.count())],
            ['Spectrum','Samples','Phase','Electric fields','3D fields'])
        self.window._navigate_route(0);APP.processEvents()
        structure=self.window.pages['Structure']
        self.assertEqual(structure.tabs.currentIndex(),1)
        self.assertIsInstance(structure._legacy,DeviceBuilderPage)
        self.assertTrue(structure._legacy.isVisible())

    def test_original_spectrum_footer_submits_live_wavelength_and_angle_controls(self):
        for key,value in [('wl_start_nm',1460.),('wl_stop_nm',1464.),('wl_step_nm',2.)]:
            self.enter_number(self.page.controls[key],value)
        QTest.mouseClick(self.page.measure_phase,Qt.MouseButton.LeftButton,pos=QPoint(10,self.page.measure_phase.height()//2))
        self.assertTrue(self.page.measure_phase.isChecked())
        with patch.object(self.store,'start_run') as start:
            QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
        start.assert_called_once_with('simulation',{'measure_phase':True})
        self.assertEqual((self.store.settings['wl_start_nm'],self.store.settings['wl_stop_nm'],self.store.settings['wl_step_nm']),
            (1460.,1464.,2.))
        self.page.controls['mode'].setCurrentIndex(self.page.controls['mode'].findData('Angle sweep'))
        for key,value in [('fixed_wl_nm',1482.),('angle_start',7.),('angle_stop',19.),('angle_step',6.)]:
            self.enter_number(self.page.controls[key],value)
        with patch.object(self.store,'start_run') as start:
            QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
        start.assert_called_once_with('simulation',{'measure_phase':True})
        self.assertEqual(self.store.settings['mode'],'Angle sweep')
        self.assertEqual((self.store.settings['fixed_wl_nm'],self.store.settings['angle_start'],
            self.store.settings['angle_stop'],self.store.settings['angle_step']),(1482.,7.,19.,6.))

    def test_original_manual_fields_button_submits_its_own_nondefault_controls(self):
        self.page.optical_journey.select_stage('outputs');APP.processEvents()
        self.assertTrue(self.page.field_run.isVisible());self.assertTrue(self.page.field_run.isEnabled())
        self.enter_number(self.page.field_wavelength,1567.5)
        self.enter_number(self.page.field_controls['grid'],4)
        self.enter_number(self.page.field_controls['depth_samples'],5)
        with patch.object(self.store,'start_run') as start:
            QTest.mouseClick(self.page.field_run,Qt.MouseButton.LeftButton)
        self.assertEqual(start.call_count,1)
        kind,options=start.call_args.args
        self.assertEqual(kind,'simulation_fields')
        self.assertEqual(options['wavelength_source'],'manual');self.assertTrue(options['single_wavelength'])
        self.assertEqual(options['wavelength_nm'],1567.5)
        self.assertEqual(options['electric_fields']['grid'],4)
        self.assertEqual(options['electric_fields']['depth_samples'],5)
        self.assertNotIn('optical_enabled',options)

    def test_original_structure_footer_does_not_apply_canonical_inspector(self):
        self.window._navigate_route(0);APP.processEvents()
        structure=self.window.pages['Structure']
        with patch.object(structure,'apply_inspector',return_value=False) as canonical_apply:
            with patch.object(self.store,'start_run') as start:
                QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
        canonical_apply.assert_not_called()
        self.assertEqual(start.call_count,1)
        self.assertEqual(start.call_args.args[0],'simulation')
        self.assertEqual(self.window.simulation_engines.currentIndex(),7)

    def test_original_narrow_results_preserve_metric_text_and_3d_viewer_height(self):
        self.page.optical_journey.show_results();APP.processEvents()
        self.page.result_tabs.setCurrentWidget(self.page.generated_volume)
        for width in (1024,640):
            self.window.resize(width,760);APP.processEvents();QTest.qWait(100)
            panels=self.page.journey_results_layout
            self.assertEqual(panels.orientation(),Qt.Orientation.Vertical)
            self.assertGreaterEqual(panels.widget(0).height(),700)
            self.assertGreaterEqual(self.page.generated_volume.plot.height(),300)
            tabs=self.window.optical_workflow
            self.assertIn('results',tabs.tabText(tabs.currentIndex()).lower())
            self.assertEqual(self.window.study_navigation.current,self.page.optical_journey.bar._current)
            for label in self.page.power_values.values():
                self.assertGreaterEqual(label.width(),label.fontMetrics().horizontalAdvance('0.7140'))
            self.assertLessEqual(self.window.chrome.file_button.geometry().right(),self.window.chrome.width())

    def test_switching_workspaces_preserves_structure_simulation_values_and_drafts(self):
        self.enter_number(self.page.controls['wl_start_nm'],1421.25)
        self.enter_number(self.page.field_wavelength,1433.5)
        self.window.setup_state.set('ui.electrical.bias_list_text','0, -.17, -.31')
        before=copy.deepcopy(self.store.project())
        for profile in ('multiphysics','original_optical','multiphysics','original_optical'):
            self.window.set_workspace_profile(profile);APP.processEvents()
            current=self.store.project()
            for key in ('device','materials','layers','patterns','settings','performance','electrical_materials'):
                self.assertEqual(current[key],before[key],key)
            self.assertEqual(self.window.setup_state.get('ui.electrical.bias_list_text'),'0, -.17, -.31')
        self.window._navigate_route(2);APP.processEvents()
        self.assertEqual(self.window.simulation_engines.currentIndex(),7)
        self.assertEqual(self.page.controls['wl_start_nm'].value(),1421.25)
        self.assertEqual(self.page.field_wavelength.value(),1433.5)

    def test_original_geometry_compiles_optical_tables_and_device_profile_compiles_selected_cell(self):
        cell=copy.deepcopy(self.window.setup_state.get('settings.optical_unit_cell'))
        cell.update(enabled=True,width_um=.45,depth_um=.45,cx_um=0.,cy_um=0.)
        self.store.update_settings(dict(optical_unit_cell=cell))
        original,spec=prepare_job('simulation',self.store.portable_project(),
            dict(optical_geometry_source='original_tables',measure_phase=False),self.store.library)
        self.assertEqual(spec['model']['ax'],self.store.settings['ax_um'])
        self.assertEqual(spec['model']['ay'],self.store.settings['ay_um'])
        self.assertEqual(spec['model']['ax'],2.)
        self.assertEqual(len(spec['model']['layers']),len(original['layers']))
        self.window.set_workspace_profile('device')
        prepared,cropped=prepare_job('simulation',self.store.portable_project(),
            dict(measure_phase=False),self.store.library)
        self.assertEqual(cropped['model']['ax'],.45)
        self.assertEqual(cropped['model']['ay'],.45)
        self.assertGreater(len(cropped['model']['layers']),len(prepared['layers']))

    def test_original_pc_uses_one_table_hole_without_contact_slabs_and_freezes_source(self):
        from tests.test_pc_optical_defaults import pc_project
        value=pc_project()
        value['device']['contacts'][1].update(optical_material_name='Au',optical_thickness_um=.1)
        value['layers'][-1]['Material']='Air'
        self.store.load_project(value)
        snapshot=copy.deepcopy(self.store.portable_project())
        options=dict(optical_geometry_source='original_tables',measure_phase=True)
        saved_options=copy.deepcopy(options)
        original,spectrum=prepare_job('simulation',snapshot,options,self.store.library)
        model=spectrum['model']
        self.assertIn('one air hole',self.window.original_geometry_label.text())
        self.assertIn('0.3 × 0.3 µm',self.window.original_geometry_label.text())
        self.assertEqual(model['geometry_source'],'original_tables')
        self.assertEqual((model['ax'],model['ay']),(.3,.3))
        holes=[row for row in model['patterns'] if row['shape']=='circle' and row['material']=='Air']
        self.assertEqual(len(holes),1)
        self.assertEqual((holes[0]['cx'],holes[0]['cy']),(0.,0.))
        self.assertEqual(holes[0]['sx'],.05)
        self.assertEqual(len(model['layers']),len(original['layers']))
        self.assertFalse(any(row.get('contact_optical_surface') for row in model['layers']))
        self.assertEqual(len(original['device']['shapes']),16)
        self.assertEqual(original['device']['width_um'],2.)
        self.assertEqual(snapshot,self.store.portable_project())
        self.assertEqual(options,saved_options)
        # A pending Original field request continues to use its saved table
        # data after the user chooses Device Studio and edits the new setup.
        self.window.set_workspace_profile('device')
        self.store.update_settings(dict(NumG=13))
        field_options=dict(saved_options,wavelength_source='manual',single_wavelength=True,
            wavelength_nm=1549.25,electric_fields=dict(grid=3,depth_samples=3))
        _,fields=prepare_job('simulation_fields',snapshot,field_options,self.store.library)
        self.assertEqual(fields['model']['geometry_source'],'original_tables')
        self.assertEqual((fields['model']['ax'],fields['model']['ay']),(.3,.3))
        self.assertEqual(fields['model']['basis'],9)
        self.assertEqual(len([row for row in fields['model']['patterns'] if row['shape']=='circle']),1)
        self.assertEqual(snapshot['settings']['NumG'],9)
        self.assertEqual(options,saved_options)

    def test_real_original_spectrum_phase_and_manual_fields_stay_in_original_workspace(self):
        self.enter_number(self.page.field_controls['grid'],3)
        self.enter_number(self.page.field_controls['depth_samples'],3)
        self.enter_number(self.page.field_wavelength,1549.25)
        QTest.mouseClick(self.page.measure_phase,Qt.MouseButton.LeftButton,pos=QPoint(10,self.page.measure_phase.height()//2))
        QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
        self.wait_finished(1)
        self.assertEqual(self.events[0]['run_kind'],'simulation')
        request=json.loads((Path(self.events[0]['directory'])/'desktop_request.json').read_text(encoding='utf-8'))
        self.assertEqual(request['options']['optical_geometry_source'],'original_tables')
        self.assertEqual(self.window.navigation.currentRow(),2)
        self.assertEqual(self.window.simulation_engines.currentIndex(),7)
        self.assertEqual(len(self.page.result_frame),3)
        self.assertFalse(self.page.phase_frame.empty)
        self.assertTrue((Path(self.events[0]['directory'])/'phase.csv').is_file())
        self.assertIs(self.page.result_tabs.currentWidget(),self.page.plot)
        self.assertEqual(self.page.field_controls['grid'].value(),3)
        self.assertEqual(self.page.field_controls['depth_samples'].value(),3)
        self.assertEqual(self.page.field_wavelength.value(),1549.25)
        self.enter_number(self.page.field_wavelength,1550.)
        QTest.mouseClick(self.page.field_run,Qt.MouseButton.LeftButton)
        self.wait_finished(2)
        self.assertEqual(self.events[1]['run_kind'],'simulation_fields')
        request=json.loads((Path(self.events[1]['directory'])/'desktop_request.json').read_text(encoding='utf-8'))
        self.assertEqual(request['options']['optical_geometry_source'],'original_tables')
        self.assertEqual(self.window.navigation.currentRow(),2)
        self.assertEqual(self.window.simulation_engines.currentIndex(),7)
        self.assertIs(self.page.result_tabs.currentWidget(),self.page.generated_fields)
        self.assertEqual(self.page.field_sample.count(),1)
        self.page.result_tabs.setCurrentWidget(self.page.generated_volume);APP.processEvents();QTest.qWait(50)
        self.assertIsNotNone(self.page.generated_volume.data)
        # A saved original run must not leak its geometry source into a fresh
        # Device Studio calculation after switching back to that workspace.
        self.window.set_workspace_profile('device')
        cell=copy.deepcopy(self.window.setup_state.get('settings.optical_unit_cell'))
        cell.update(enabled=True,width_um=.45,depth_um=.45,cx_um=0.,cy_um=0.)
        self.store.update_settings(dict(optical_unit_cell=cell))
        options=self.window.setup_state.job_options('optical')
        self.assertEqual(options['optical_geometry_source'],'device')
        _,prepared=prepare_job('simulation',self.store.portable_project(),options,self.store.library)
        self.assertEqual((prepared['model']['ax'],prepared['model']['ay']),(.45,.45))
        frozen=json.loads((Path(self.events[1]['directory'])/'desktop_request.json').read_text(encoding='utf-8'))
        self.assertEqual(frozen['options']['optical_geometry_source'],'original_tables')
        self.window._open_simulation_result(self.events[1]['directory']);APP.processEvents()
        self.assertEqual(self.window.navigation.currentRow(),9)
        QTest.mouseClick(self.window.results_page.rerun_button,Qt.MouseButton.LeftButton);APP.processEvents()
        self.assertEqual(self.window.workspace_profile,'original')
        self.assertEqual(self.window.navigation.currentRow(),2)
        self.assertEqual(self.window.simulation_engines.currentIndex(),7)
        self.assertEqual(self.page.field_wavelength.value(),1550.)
        self.assertEqual(self.page.field_controls['grid'].value(),3)
        self.assertFalse(self.store.busy)


if __name__=='__main__':unittest.main()
