"""Read-only paper figure views; synthetic UI fixtures are not paper validation."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PyQt6.QtWidgets import QApplication
from qt_pcsel_paper import PcselPaperResults, saved_paper_figure
from qt_research_results import ResearchResultsPanel
APP=QApplication.instance() or QApplication([])

class PaperFigureTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='paper-ui-',dir=os.environ.get('ODS_TEST_TMPDIR'))
  self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
 def csv(self,name,headers,rows):
  with (self.root/name).open('w',newline='',encoding='utf-8') as f:
   writer=csv.writer(f);writer.writerow(headers);writer.writerows(rows)
 def test_invalid_heatmap_cells_remain_masked_and_csv_unchanged(self):
  self.csv('map.csv',['theta','base','g','status'],[[65,.7,2,'complete'],[70,.7,3,'complete'],[65,.8,4,'complete'],[70,.8,999,'invalid_geometry']])
  before=(self.root/'map.csv').read_bytes()
  fig=saved_paper_figure(self.root,dict(kind='heatmap',csv='map.csv',x='theta',y='base',value='g',x_label='Base angle (degrees)',y_label='Base length / a',value_label='Loss (cm^-1)'))
  values=fig.axes[0].collections[0].get_array()
  self.assertEqual(np.ma.count_masked(values),1)
  self.assertEqual(fig.axes[0].get_xlabel(),'Base angle (degrees)')
  self.assertEqual(before,(self.root/'map.csv').read_bytes())
 def test_line_groups_modes_and_failed_sample_breaks_curve(self):
  self.csv('modes.csv',['L','loss','band','status'],[[1,2,'A','complete'],[2,99,'A','failed'],[3,4,'A','complete'],[1,5,'B','complete'],[2,6,'B','complete']])
  fig=saved_paper_figure(self.root,dict(kind='line',csv='modes.csv',x='L',y='loss',series='band'))
  self.assertEqual(len(fig.axes[0].lines),2)
  self.assertTrue(np.isnan(fig.axes[0].lines[0].get_ydata()[1]))
  self.assertEqual(list(fig.axes[0].lines[1].get_ydata()),[5,6])
 def test_spectrum_does_not_connect_unrelated_modes(self):
  self.csv('modes.csv',['wavelength','loss'],[[1069,2],[1070,5]])
  fig=saved_paper_figure(self.root,dict(kind='line',csv='modes.csv',x='wavelength',y='loss',connect=False))
  self.assertEqual(fig.axes[0].lines[0].get_linestyle(),'None')
 def test_field_uses_saved_mode_and_physical_coordinates(self):
  values=np.arange(24.).reshape(2,3,4)
  np.savez(self.root/'fields.npz',mode_intensity=values,x_um=[0,1,2,3],y_um=[0,2,4])
  fig=saved_paper_figure(self.root,dict(kind='field_grid',npz='fields.npz',array='mode_intensity',x='x_um',y='y_um',mode_index=1))
  np.testing.assert_array_equal(fig.axes[0].collections[0].get_array().reshape(3,4),values[1])
 def test_external_data_path_and_duplicate_map_coordinates_rejected(self):
  with self.assertRaisesRegex(ValueError,'inside this saved run'):
   saved_paper_figure(self.root,dict(kind='line',csv='../outside.csv',x='x',y='y'))
  self.csv('map.csv',['x','y','z'],[[1,1,3],[1,1,4]])
  with self.assertRaisesRegex(ValueError,'Duplicate map coordinates'):
   saved_paper_figure(self.root,dict(kind='heatmap',csv='map.csv',x='x',y='y',value='z'))
 def test_integrated_saved_tab_clears_after_other_run(self):
  self.csv('values.csv',['x','y'],[[1,2],[2,3]])
  (self.root/'research_summary.json').write_text(json.dumps(dict(engine='pcsel',status='complete')))
  (self.root/'pcsel_paper_figures.json').write_text(json.dumps(dict(schema_version=1,status='complete',scope='Synthetic UI fixture only',plots=[dict(id='x',title='Synthetic saved output',kind='line',csv='values.csv',x='x',y='y')],reference_targets=[999999])))
  p=ResearchResultsPanel(engine='pcsel')
  try:
   self.assertTrue(p.load_directory(self.root))
   self.assertTrue(p.tabs.isTabVisible(p.paper_figures_index))
   self.assertEqual(p.tabs.currentWidget(),p.paper_figures)
   self.assertEqual(list(p.paper_figures.plot.figure.axes[0].lines[0].get_ydata()),[2,3])
   (self.root/'pcsel_paper_figures.json').unlink()
   self.assertTrue(p.load_directory(self.root))
   self.assertFalse(p.tabs.isTabVisible(p.paper_figures_index))
   self.assertEqual(p.paper_figures.choice.count(),0)
  finally:
   from PyQt6 import sip
   sip.delete(p)
 def test_export_copies_original_saved_data_exactly(self):
  self.csv('values.csv',['x','y'],[[1,2],[2,3]])
  (self.root/'pcsel_paper_figures.json').write_text(json.dumps(dict(schema_version=1,plots=[dict(kind='line',csv='values.csv',x='x',y='y')])))
  p=PcselPaperResults()
  try:
   self.assertTrue(p.load_directory(self.root))
   with patch('qt_pcsel_paper.QFileDialog.getSaveFileName',return_value=(str(self.root/'export.csv'),'')):
    p.export_source()
   self.assertEqual((self.root/'export.csv').read_bytes(),(self.root/'values.csv').read_bytes())
  finally:
   from PyQt6 import sip
   sip.delete(p)

 def test_raw_pcsel_summary_opens_and_derived_period_is_explicit(self):
  self.csv('values.csv',['x','y'],[[1,2],[2,3]])
  summary=dict(engine='pcsel',status='complete',derived_inputs=dict(vertical_formulation='reference_wavelength',requested_lattice_nm=320.,effective_lattice_nm=321.6789,reference_wavelength_nm=1070.))
  (self.root/'pcsel_summary.json').write_text(json.dumps(summary))
  p=ResearchResultsPanel(engine='pcsel')
  try:
   self.assertTrue(p.load_directory(self.root))
   self.assertEqual(p.summary['derived_inputs']['requested_lattice_nm'],320.)
   self.assertIn('requested period 320 nm',p.method_status.text())
   self.assertIn('calculated period used 321.6789 nm',p.method_status.text())
   self.assertIn('reference wavelength 1070 nm',p.method_status.text())
   self.assertEqual(p.files.count(),1)
   (self.root/'pcsel_summary.json').write_text(json.dumps(dict(engine='pcsel',status='complete')))
   self.assertTrue(p.load_directory(self.root));self.assertEqual(p.method_status.text(),'')
   self.assertTrue(p.method_status.isHidden())
  finally:
   from PyQt6 import sip
   sip.delete(p)


 def test_native_field_box_keeps_saved_limits_in_wide_host(self):
  coords=np.linspace(-1000,1000,17);values=np.arange(289.).reshape(17,17)
  np.savez(self.root/'fields.npz',mode_intensity=values,x_um=coords,y_um=coords)
  spec=dict(id='field',title='Cavity field',kind='field_grid',npz='fields.npz',array='mode_intensity',x='x_um',y='y_um')
  (self.root/'pcsel_paper_figures.json').write_text(json.dumps(dict(schema_version=1,plots=[spec])))
  p=PcselPaperResults();p.resize(1400,650);p.show()
  try:
   self.assertTrue(p.load_directory(self.root))
   for _ in range(8):APP.processEvents()
   axis=p.plot.figure.axes[0];view=p.plot.canvas.axis_views[axis]
   self.assertGreater(p.plot.canvas.width(),200)
   self.assertGreater(p.plot.canvas.height(),100)
   self.assertGreater(p.plot.canvas.view.viewport().width(),150)
   np.testing.assert_allclose(view.viewRange(),[axis.get_xlim(),axis.get_ylim()],rtol=1e-12)
   self.assertLess(abs(view.width()/view.height()-1),.01)
   self.assertLess(abs(axis.get_xlim()[1]),1200)
   p.plot.toolbar.home()
   np.testing.assert_allclose(view.viewRange(),[axis.get_xlim(),axis.get_ylim()],rtol=1e-12)
   p.plot.retheme()
   for _ in range(8):APP.processEvents()
   view=p.plot.canvas.axis_views[axis]
   np.testing.assert_allclose(view.viewRange(),[axis.get_xlim(),axis.get_ylim()],rtol=1e-12)
   self.assertLess(abs(view.width()/view.height()-1),.01)
   p.resize(900,500)
   for _ in range(8):APP.processEvents()
   self.assertGreater(p.plot.canvas.width(),200)
   np.testing.assert_allclose(view.viewRange(),[axis.get_xlim(),axis.get_ylim()],rtol=1e-12)
   self.assertLess(abs(view.width()/view.height()-1),.01)
   self.csv('line.csv',['x','y'],[[0,1],[1,2]])
   p.choice.addItem('Profile',dict(id='line',kind='line',csv='line.csv',x='x',y='y'))
   p.choice.setCurrentIndex(1)
   for _ in range(8):APP.processEvents()
   self.assertGreater(p.plot.canvas.width(),600)
   p.choice.setCurrentIndex(0)
   for _ in range(8):APP.processEvents()
   self.assertGreater(p.plot.canvas.width(),200)
   axis=p.plot.figure.axes[0];view=p.plot.canvas.axis_views[axis]
   np.testing.assert_allclose(view.viewRange(),[axis.get_xlim(),axis.get_ylim()],rtol=1e-12)
   self.assertLess(abs(view.width()/view.height()-1),.01)
  finally:p.close();p.deleteLater();APP.processEvents()

 def test_beam_detail_is_explicit_crop_with_exact_full_data(self):
  coords=np.linspace(-.04,.04,101);x,y=np.meshgrid(coords,coords)
  values=np.exp(-(x*x+y*y)/.000001)
  np.savez(self.root/'fields.npz',far_display=values,sin_theta_x=coords,sin_theta_y=coords)
  before=(self.root/'fields.npz').read_bytes()
  spec=dict(id='field',title='far_display mode 0',kind='field_grid',npz='fields.npz',array='far_display',x='sin_theta_x',y='sin_theta_y')
  (self.root/'pcsel_paper_figures.json').write_text(json.dumps(dict(schema_version=1,plots=[spec])))
  p=PcselPaperResults();p.resize(1400,650);p.show()
  try:
   self.assertTrue(p.load_directory(self.root));full=p.plot.figure.axes[0].get_xlim()
   self.assertEqual(p.choice.currentText(),'Far-field intensity mode 0')
   self.assertFalse(p.display_view.currentData())
   p.display_view.setCurrentIndex(1)
   for _ in range(8):APP.processEvents()
   axis=p.plot.figure.axes[0];view=p.plot.canvas.axis_views[axis]
   self.assertLess(axis.get_xlim()[1]-axis.get_xlim()[0],(full[1]-full[0])/2)
   np.testing.assert_allclose(view.viewRange(),[axis.get_xlim(),axis.get_ylim()],rtol=1e-12)
   np.testing.assert_equal(axis.collections[0].get_array().reshape(values.shape),values)
   self.assertIn('display-only crop',p.note.text())
   self.assertEqual(before,(self.root/'fields.npz').read_bytes())
   p.display_view.setCurrentIndex(0)
   np.testing.assert_equal(p.plot.figure.axes[0].get_xlim(),full)
  finally:p.close();p.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
