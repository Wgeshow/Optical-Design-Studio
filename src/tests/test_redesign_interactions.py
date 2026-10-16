"""Regression coverage for B controls that change real data or inspect results."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd
from PyQt6.QtWidgets import QApplication
from qt_core import ProjectStore
from data_library import DataLibrary
from qt_compute import SimulationPage
from qt_materials import MaterialsPage
from qt_help import HelpGuide

APP=QApplication.instance() or QApplication([])

class RedesignInteractions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.widgets=[]
    def tearDown(self):
        for widget in self.widgets:widget.deleteLater()
        APP.processEvents();self.temp.cleanup()
    def page(self,cls):
        widget=cls(self.store);self.widgets.append(widget);return widget
    def test_assign_project_material_preserves_geometry(self):
        page=self.page(MaterialsPage)
        layer=self.store.layers.iloc[1].Name
        material=self.store.materials.iloc[0].Name
        page.selection.setCurrentIndex(page.selection.findData('project:'+material))
        page.assignment_layer.setCurrentIndex(page.assignment_layer.findData(layer))
        before=self.store.patterns.copy();thickness=self.store.layers.Thickness_um.copy()
        page.apply_to_layer()
        self.assertEqual(self.store.layers.loc[self.store.layers.Name==layer,'Material'].iloc[0],material)
        pd.testing.assert_frame_equal(before,self.store.patterns)
        pd.testing.assert_series_equal(thickness,self.store.layers.Thickness_um)
        self.assertIn('Assigned',page.status.text())
    def test_cursor_and_export_use_actual_samples(self):
        page=self.page(SimulationPage)
        page.result_frame=pd.DataFrame({'wavelength_nm':[1515.,1520.,1530.],'R':[.1,.2,.3],'T':[.7,.6,.5],'A':[.2,.2,.2]})
        page.update_peak()
        page.inspect_plot_sample(SimpleNamespace(inaxes=page.plot.figure.axes[0],xdata=1528.))
        self.assertEqual(page.sample_position.value(),3)
        self.assertEqual(page.power_values['R'].text(),'0.3000')
        path=os.path.join(self.temp.name,'export.csv')
        with patch('qt_compute.QFileDialog.getSaveFileName',return_value=(path,'CSV')):page.export_spectrum()
        pd.testing.assert_frame_equal(pd.read_csv(path),page.result_frame)
        self.assertEqual(sum(line.get_gid()=='sample-cursor' for line in page.plot.figure.axes[0].lines),1)
    def test_phase_selection_restores_with_project(self):
        page=self.page(SimulationPage)
        self.store.save_search('simulation',{'measure_phase':True})
        page.refresh('project')
        self.assertTrue(page.measure_phase.isChecked())
    def test_help_search_matches_control_text(self):
        page=HelpGuide();self.widgets.append(page)
        page.query.setText('CSV')
        self.assertGreater(page.topics.count(),0)
        page.query.setText('zzzz-no-guide')
        self.assertEqual(page.topics.count(),0)
        self.assertIn('No matching',page.reader.toPlainText())

if __name__=='__main__':unittest.main()
