"""Research transport results may be saved as JSON and NPZ without any CSV."""
import csv,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PyQt6.QtWidgets import QApplication
from qt_research_results import ResearchResultsPanel
APP=QApplication.instance() or QApplication([])

class SavedTransportTablesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='transport_view_')
        self.root=Path(self.temp.name);self.panel=ResearchResultsPanel(engine='advanced_transport')
        metadata={'potential_V':dict(unit='V',axes=[dict(name=k,unit='m',coordinate=k) for k in ('x','y','z')])}
        for i in range(2):
            np.savez(self.root/f'advanced_state_{i:04d}.npz',x=np.array([0.,1.])*1e-6,y=np.array([0.,1.])*1e-6,z=np.array([0.,1.,2.])*1e-6,
              potential_V=np.arange(12.).reshape(2,2,3)*i*.001,array_axes=json.dumps(metadata))
        self.summary=dict(engine='advanced_transport',status='complete',options=dict(swept_contact_id='P'),results=[
          dict(bias_V=v,volume_npz=f'advanced_state_{i:04d}.npz',checks=dict(terminal_voltages_V={'P':v,'N':0.},terminal_current_A={'P':current,'N':-current},terminal_charge_C={'P':v*1e-15,'N':-v*1e-15},relative_current_balance=0.))
          for i,(v,current) in enumerate([(0.,0.),(.0001,1.959237994265871e-7)])])
        self.path=self.root/'research_summary.json';self.path.write_text(json.dumps(self.summary),encoding='utf-8')
    def tearDown(self):
        from PyQt6 import sip
        sip.delete(self.panel);APP.processEvents();self.temp.cleanup()
    def test_current_plot_and_physical_field_selection_need_no_csv(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        self.assertTrue(self.panel.load_directory(self.root))
        self.assertTrue(self.panel.export_button.isEnabled())
        self.assertEqual(self.panel.x_axis.currentData(),'terminal_voltage_V')
        self.assertEqual(self.panel.y_axis.currentData(),'current_A')
        self.assertEqual(list(self.panel.data['current_A']),[0.,1.959237994265871e-7])
        self.assertEqual(len(self.panel.plot.figure.axes[0].lines),1)
        self.assertEqual(self.panel.arrays.quantity.currentText(),'potential_V')
        self.assertEqual(Path(self.panel.arrays.files.currentData()).name,'advanced_state_0001.npz')
        self.assertEqual(set(self.panel.arrays.coordinates),{0,1,2})
        self.assertIsNotNone(self.panel.arrays.displayed)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
    def test_export_is_exact_saved_terminal_values_and_preserves_all_contacts(self):
        self.panel.load_directory(self.root);target=self.root/'export.csv'
        with patch('qt_research_results.QFileDialog.getSaveFileName',return_value=(str(target),'')):
            self.panel.export_csv()
        with target.open() as stream:rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),2)
        self.assertEqual(float(rows[1]['current_A']),self.summary['results'][1]['checks']['terminal_current_A']['P'])
        self.assertEqual(float(rows[1]['terminal_current_A.N']),-1.959237994265871e-7)
        self.assertIn('relative_current_balance',rows[1])
    def test_invalid_next_run_does_not_keep_virtual_table_or_export(self):
        self.panel.load_directory(self.root)
        other=self.root/'missing';other.mkdir()
        self.assertFalse(self.panel.load_directory(other))
        self.assertIsNone(self.panel.data);self.assertFalse(self.panel.export_button.isEnabled())
        with patch('qt_research_results.QFileDialog.getSaveFileName') as dialog:self.panel.export_csv()
        dialog.assert_not_called()
    def test_representative_transport_and_generic_library_view_are_supported(self):
        from PyQt6 import sip
        self.summary['engine']='pcsel_unitcell_transport';self.path.write_text(json.dumps(self.summary),encoding='utf-8')
        for engine in ('pcsel_unitcell_transport',None):
            panel=ResearchResultsPanel(engine=engine)
            try:
                self.assertTrue(panel.load_directory(self.root));self.assertIn('current_A',panel.data)
            finally:sip.delete(panel)

if __name__=='__main__':unittest.main()
