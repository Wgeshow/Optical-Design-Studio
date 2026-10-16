import json,os,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from index_shift import fixed_wavelength_readout,execute_sweep,prepare_sweep
from test_index_shift import multilayer,options
from model import DEFAULT_PERFORMANCE

class FixedReadoutTests(unittest.TestCase):
    def simulate(self,directory):
        model=multilayer();model['points']=[[i,w,0] for i,w in enumerate([1540,1545,1550,1555,1560])]
        cfg=prepare_sweep(model,options(samples=2,tracking_window_nm=5))
        powers=[[.1,.3,.9,.2,.1],[.95,.6,.25,.1,.05]]
        calls=[]
        def executor(m,p,emit,cancel):
            values=powers[len(calls)];calls.append(m)
            return [[i,w,theta,values[i],1-values[i],0] for i,w,theta in m['points']],{}
        return execute_sweep(model,DEFAULT_PERFORMANCE,cfg,directory,executor)

    def test_shifted_peak_is_not_used_and_exact_baseline_response_saved(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as directory:
            result=self.simulate(directory)
            self.assertEqual(result['summary']['baseline_nm'],1550)
            data=pd.read_csv(Path(directory)/'index_shift_readout.csv')
            self.assertEqual(list(data.wavelength_nm),[1550,1550])
            self.assertEqual(list(data.value),[.9,.25])
            self.assertAlmostEqual(data.delta_value.iloc[1],-.65)
            self.assertEqual(data.delta_value.iloc[0],0)
            self.assertAlmostEqual(data.delta_T.iloc[1],.65)

    def test_missing_baseline_stays_unavailable(self):
        rows=[dict(case=0,wavelength_nm=1500,R=.1,T=.9,A=0,**{'dn:Film':0})]
        data=fixed_wavelength_readout(rows,dict(response='Transmission',baseline_nm=None))
        self.assertIsNone(data[0]['value']);self.assertIsNone(data[0]['delta_value'])

    def test_missing_exact_sample_is_not_silently_interpolated(self):
        with self.assertRaises(ValueError):
            fixed_wavelength_readout([dict(case=0,wavelength_nm=1500,R=.1,T=.9,A=0)],dict(response='Absorption',baseline_nm=1550))

    def test_ui_defaults_to_dn_vs_value_and_supports_difference(self):
        from PyQt6.QtWidgets import QApplication
        from qt_index_shift import IndexShiftPage
        from qt_core import ProjectStore
        from data_library import DataLibrary
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'run';self.simulate(run)
            page=IndexShiftPage(ProjectStore(DataLibrary(Path(directory)/'library'),restore=False))
            page.directory=run;page.show_result({})
            axis=page.plot.figure.axes[0]
            self.assertIn('Δn',axis.get_xlabel())
            self.assertEqual(list(axis.lines[0].get_ydata()),[.9,.25])
            self.assertIn('1550',page.locked_label.text())
            page.readout_view.setCurrentText('Change from baseline')
            self.assertAlmostEqual(page.plot.figure.axes[0].lines[0].get_ydata()[1],-.65)
            page.readout_view.setCurrentText('Overlaid spectra')
            self.assertIn('Wavelength',page.plot.figure.axes[0].get_xlabel())
            page.hide()

    def test_carrier_mode_settings_roundtrip(self):
        from PyQt6.QtWidgets import QApplication
        from qt_index_shift import IndexShiftPage
        from qt_core import ProjectStore
        from data_library import DataLibrary
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(DataLibrary(Path(directory)/'library'),restore=False)
            page=IndexShiftPage(store)
            page.sweep_mode.setCurrentIndex(1)
            page.carrier_configuration=dict(silicon_confirmed=True,states=[dict(label='Injection',electron_cm3=1e18,hole_cm3=2e18)])
            page.changed()
            self.assertEqual(store.search_state['index_shift']['sweep_mode'],'carrier')
            self.assertTrue(page.options()['equal'])
            page.refresh()
            self.assertEqual(page.carrier_configuration['states'][0]['hole_cm3'],2e18)
            self.assertTrue(page.layers.isColumnHidden(2))
            self.assertTrue(page.shared.isHidden())
            page.hide()

    def test_material_and_junction_calculator_ui(self):
        from PyQt6.QtWidgets import QApplication
        from qt_carrier_index import CarrierIndexDialog
        app=QApplication.instance() or QApplication([])
        dialog=CarrierIndexDialog()
        dialog.semiconductor.setCurrentText('GaAs')
        self.assertEqual(dialog.fields['mass_e_m0'].text(),'0.067')
        self.assertEqual(dialog.fields['mobility_e_cm2_Vs'].text(),'')
        for key,value in dict(acceptor_cm3='1e17',donor_cm3='1e17',intrinsic_cm3='2.1e6',relative_permittivity='12.9',temperature_k='300',reverse_bias_v='9').items():dialog.junction_fields[key].setText(value)
        dialog.calculate_junction()
        self.assertIn('built_in_V: 1.271',dialog.junction_result.text())
        self.assertIn('width_um: 0.541',dialog.junction_result.text())
        dialog.close()

if __name__=='__main__':unittest.main()
