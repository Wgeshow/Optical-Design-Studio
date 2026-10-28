"""Raw high-field NPZ values must be accessible as tables and exact CSV exports."""
import os,csv,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PyQt6.QtWidgets import QApplication
from qt_research_results import ResearchResultsPanel
APP=QApplication.instance() or QApplication([])

class HighFieldSavedTableTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='highfield_table_');self.root=Path(self.temp.name)
  self.panel=ResearchResultsPanel(engine='high_field_optics')
  self.summary=dict(status='complete',engine='high_field_optics',options=dict(samples=[dict(id='field',field_V_m=1.3e8,bandgap_eV=1.39,temperature_K=300.,electron_reduced_fermi=-5.,hole_reduced_fermi=-5.),dict(id='zero',field_V_m=0.,bandgap_eV=1.424,temperature_K=300.,electron_reduced_fermi=-30.,hole_reduced_fermi=-30.)]))
  (self.root/'research_summary.json').write_text(json.dumps(self.summary),encoding='utf-8')
  self.values=dict(sample_ids=np.array(['field','zero']),wavelengths_nm=np.array([800.,900.,1150.]))
  for k in ['absorption_cm1','reference_absorption_cm1','delta_n','delta_k','interband_k','kk_quadrature_error_estimate']:self.values[k]=np.arange(6.).reshape(2,3)*.013245678901234567
  self.values['kk_quadrature_warning_count']=np.array([[1,0,1],[0,0,0]])
  np.savez(self.root/'high_field_optics.npz',**self.values)
 def tearDown(self):
  from PyQt6 import sip
  sip.delete(self.panel);APP.processEvents();self.temp.cleanup()
 def test_all_states_quantities_and_diagnostics_in_raw_table(self):
  before={p.name:p.read_bytes() for p in self.root.iterdir()}
  self.assertTrue(self.panel.load_directory(self.root))
  self.assertEqual(self.panel.table.rowCount(),6);self.assertTrue(self.panel.export_button.isEnabled())
  self.assertEqual(self.panel.x_axis.currentData(),'wavelength_nm')
  self.assertEqual(self.panel.y_axis.currentData(),'absorption_cm1')
  np.testing.assert_array_equal(self.panel.data['delta_n'],self.values['delta_n'].ravel())
  self.assertIn('kk_quadrature_warning_count',self.panel.data)
  self.assertEqual(len(self.panel.plot.figure.axes[0].lines),2)
  self.assertEqual(list(self.panel.plot.figure.axes[0].lines[0].get_xdata()),[800.,900.,1150.])
  self.assertEqual(list(self.panel.data['field_V_m']),[1.3e8]*3+[0.]*3)
  self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
 def test_native_export_retains_ids_and_float_values(self):
  self.panel.load_directory(self.root);target=self.root/'export.csv'
  with patch('qt_research_results.QFileDialog.getSaveFileName',return_value=(str(target),'')):self.panel.export_csv()
  with target.open() as stream:rows=list(csv.DictReader(stream))
  self.assertEqual([r['sample_id'] for r in rows],['field']*3+['zero']*3)
  np.testing.assert_array_equal([float(r['delta_k']) for r in rows],self.values['delta_k'].ravel())
 def test_bad_shape_does_not_fabricate_rows_or_keep_prior_table(self):
  self.panel.load_directory(self.root)
  self.values['delta_n']=np.ones((1,3));np.savez(self.root/'high_field_optics.npz',**self.values)
  self.assertTrue(self.panel.load_directory(self.root))
  self.assertFalse(self.panel.export_button.isEnabled());self.assertIsNone(self.panel.data)
  self.assertIn('shape',self.panel.status.text())

if __name__=='__main__':unittest.main()
