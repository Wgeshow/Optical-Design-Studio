"""Real field-only/staged S4 artifacts open in the native shared Results page."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('S4_DLL_DIRS','C:/codes/Optical Design Studio/_internal')
_import_root=tempfile.TemporaryDirectory(prefix='ods_optical_results_import_',dir=Path(__file__).resolve().parents[3])
os.environ.setdefault('S4_LIBRARY_ROOT',_import_root.name)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication,QEvent,Qt
from PyQt6.QtTest import QTest
from qt_common import theme_manager
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_app import OpticalStudio
from tests.test_contact_optics import device,project

APP=QApplication.instance() or QApplication([])


class NativeOpticalSavedResultsTests(unittest.TestCase):
    def setUp(self):
        theme_manager().apply('dark',persist=False)
        self.temp=tempfile.TemporaryDirectory(prefix='ods_real_optical_fields_',dir=Path(__file__).resolve().parents[3])
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        physical=device();physical['contacts'][1].update(optical_material_name='Au',optical_thickness_um=.1)
        value=project(physical);value['layers'][-1]['Material']='Air'
        value['settings'].update(NumG=9,wl_start_nm=1549.,wl_stop_nm=1551.,wl_step_nm=1.)
        value['performance']=dict(mode='CPU only',solver_backend='native',workers=1,threads=1,timeout_seconds=90)
        self.store.load_project(value)
        self.window=OpticalStudio(self.store);self.window.resize(1586,992);self.window.show()
        self.window._select_simulation_workflow('optical')
        self.state=self.window.setup_state
        self.state.set('search.simulation.electric_fields.grid',3)
        self.state.set('search.simulation.electric_fields.depth_samples',3)
        self.errors=[];self.events=[]
        self.store.run_failed.connect(self.errors.append);self.store.run_finished.connect(self.events.append)
        APP.processEvents()

    def tearDown(self):
        if self.store.busy:
            self.store.cancel()
            deadline=time.monotonic()+10
            while self.store.busy and time.monotonic()<deadline:QTest.qWait(20)
        self.window.hide();self.window.deleteLater();APP.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def wait_finished(self,count):
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            QTest.qWait(30)
            if self.errors:break
            if len(self.events)>=count and not self.store.busy:
                APP.processEvents();break
        self.assertEqual(self.errors,[])
        self.assertFalse(self.store.busy)
        self.assertEqual(len(self.events),count)
        APP.processEvents()

    def test_fields_only_opens_without_spectrum_csv_and_exports_exact_saved_data(self):
        self.state.set('ui.optical.outputs.execution_plan','fields_only')
        self.state.set('search.simulation.wavelength_source','manual')
        self.state.set('search.simulation.wavelength_nm',1550.)
        QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
        self.wait_finished(1)
        directory=Path(self.events[-1]['directory'])
        self.assertEqual(self.events[-1]['run_kind'],'simulation_fields')
        self.assertFalse((directory/'results.csv').exists())
        result=self.window.results_page
        self.assertEqual(result.directory,directory)
        self.assertTrue(result.has_optical_fields)
        self.assertEqual(result._active_category,'Optical E/H')
        self.assertEqual(result.center_stack.currentIndex(),7)
        panel=result.optical_fields_panel
        self.assertEqual(panel.sample_count,1)
        self.assertGreater(len(panel.frame),0)
        self.assertTrue({'Ex_real','Hx_real','Sx'}<=set(panel.frame.columns))
        for key in ('E2','H2','S2'):
            panel.quantity.setCurrentIndex(panel.quantity.findData(key));APP.processEvents()
            self.assertTrue(panel.plot.figure.axes)
        panel.tabs.setCurrentIndex(1);APP.processEvents()
        self.assertIsNotNone(panel.volume.data)
        image=Path(self.temp.name)/'optical-field-3d.png'
        result.export_file(image,'figure')
        self.assertTrue(image.is_file());self.assertGreater(image.stat().st_size,1000)
        with patch.object(panel.volume.plot,'export_dialog') as export:
            result.export_visible_figure()
            panel.export_figure()
        self.assertEqual(export.call_count,2)
        export.assert_called_with()
        csv=Path(self.temp.name)/'export.csv';npz=Path(self.temp.name)/'export.npz'
        with patch('qt_optical_results.QFileDialog.getSaveFileName',return_value=(str(csv),'CSV')):panel.export_csv()
        with patch('qt_optical_results.QFileDialog.getSaveFileName',return_value=(str(npz),'NPZ')):panel.export_npz()
        self.assertTrue(csv.is_file());self.assertTrue(npz.is_file())
        source=panel.sample_directory/'electric_fields.npz'
        self.assertEqual(npz.read_bytes(),source.read_bytes())
        self.assertTrue(result.workspace_export_buttons['Export CSV / NPZ'].isEnabled())

    def test_real_spectrum_then_fields_retains_original_inputs_and_saved_phase(self):
        self.state.set('ui.optical.outputs.execution_plan','spectrum_then_fields')
        self.state.set('search.simulation.measure_phase',True)
        self.state.set('search.simulation.wavelength_source','maxR')
        self.assertEqual(self.state.validate('optical'),[])
        QTest.mouseClick(self.window.run_button,Qt.MouseButton.LeftButton)
        self.assertTrue(self.store.busy)
        # User changes the visible setup while the original project is running.
        self.store.update_settings(dict(NumG=13))
        self.wait_finished(2)
        first,second=self.events
        self.assertEqual((first['run_kind'],second['run_kind']),('simulation','simulation_fields'))
        source=Path(first['directory']);fields=Path(second['directory'])
        snapshot=json.loads((fields/'project.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['settings']['NumG'],9)
        self.assertEqual(self.store.settings['NumG'],13)
        result=self.window.results_page
        self.assertEqual(result.directory,fields)
        self.assertEqual(result.optical_source_directory,source)
        self.assertTrue(result.has_optical_fields);self.assertTrue(result.has_specular_phase)
        self.assertFalse(result.optical_data.empty)
        result.select_category('Specular phase')
        self.assertEqual(result.center_stack.currentIndex(),8)
        self.assertEqual(result.phase_panel.path,source/'phase.csv')
        self.assertFalse(result.phase_panel.frame.empty)
        self.assertIn('reflection_phase_deg',result.phase_panel.frame)
        output=Path(self.temp.name)/'phase-export.csv'
        with patch('qt_optical_results.QFileDialog.getSaveFileName',return_value=(str(output),'CSV')):result.phase_panel.export_csv()
        self.assertEqual(output.read_bytes(),(source/'phase.csv').read_bytes())


if __name__=='__main__':unittest.main()
