"""Laser charts and device dashboard use native views of actual data."""
import copy
import os
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel import PCSELPage
from qt_device_builder import GeometryViewport

APP=QApplication.instance() or QApplication([])


class NativePCSELPlotsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.page=PCSELPage(self.store)
        self.page.resize(1460,950)
        self.page.show()
        self.page.run_simulation()
        APP.processEvents()

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def line_record(self,plot,line):
        records=[record for record in plot.canvas.data_records if record.get('source_artist') is line]
        self.assertEqual(len(records),1)
        return records[0]

    def test_all_laser_charts_are_native_and_keep_backend_samples_and_units(self):
        for name in ('field_canvas','dashboard_li','dashboard_mod','dashboard_rolloff','dashboard_shift',
                     'mode_canvas','laser_canvas','modulation_canvas','thermal_canvas','optimization_canvas'):
            canvas=getattr(self.page,name).canvas
            self.assertEqual(type(canvas).__name__,'NativeFigureCanvas',name)
            self.assertEqual(canvas.unsupported_artists,[],name)
        result=self.page.last_result
        for plot,x,y,xlabel,ylabel in (
            (self.page.laser_canvas,result['currents_ma'],result['output_power_mw'],'Current (mA)','Power (mW)'),
            (self.page.modulation_canvas,result['modulation']['frequencies_ghz'],result['modulation']['magnitude_db'],'Frequency (GHz)','Response (dB)')):
            axis=plot.figure.axes[0]
            record=self.line_record(plot,axis.lines[0])
            np.testing.assert_array_equal(record['raw_x'],x)
            np.testing.assert_array_equal(record['raw_y'],y)
            self.assertEqual(plot.canvas.plots[axis].getAxis('bottom').labelText,xlabel)
            self.assertEqual(plot.canvas.plots[axis].getAxis('left').labelText,ylabel)
        dashboard_axis=self.page.dashboard_mod.figure.axes[0]
        self.assertEqual(dashboard_axis.get_xscale(),'log')
        np.testing.assert_array_equal(self.line_record(self.page.dashboard_mod,dashboard_axis.lines[0])['raw_x'],result['modulation']['frequencies_ghz'])

    def test_native_dashboard_tracks_actual_applied_laser_device_and_preserves_parent(self):
        viewport=self.page.structure_canvas
        self.assertIsInstance(viewport,GeometryViewport)
        before=copy.deepcopy(self.store.project())
        device=self.page.device_store
        layers=device.layers.copy(deep=True)
        layers.loc[layers.Name=='Photonic crystal','Thickness_um']=.5
        patterns=device.patterns.copy(deep=True)
        patterns.loc[patterns.Layer=='Photonic crystal','SizeX_um']=.035
        device.set_structure(device.materials,layers,patterns)
        device.update_appearance({'material_opacities':{'InP':60}})
        rendered=next(layer for layer in viewport.layers if layer['Name']=='Photonic crystal')
        self.assertEqual(rendered['Thickness_um'],.5)
        region=next(region for region in viewport.patterns if region['layer']=='Photonic crystal')
        self.assertEqual(region['sx'],.035)
        self.assertEqual(viewport.material_opacities['InP'],60)
        self.assertEqual(viewport.ax,device.settings['ax_um'])
        self.assertEqual(self.store.project(),before)
        self.assertEqual(self.page.device_builder.viewport.layers,viewport.layers)
        self.assertFalse(viewport.grab().isNull())


if __name__=='__main__':unittest.main()
