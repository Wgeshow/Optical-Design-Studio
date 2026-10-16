import os,unittest
from concurrent.futures import Future
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

class IoffeUiTests(unittest.TestCase):
    def test_fill_and_hole_choice_and_saved_provenance(self):
        from PyQt6.QtWidgets import QApplication
        from qt_carrier_index import CarrierIndexDialog
        app=QApplication.instance() or QApplication([])
        dialog=CarrierIndexDialog(configuration=dict(semiconductor='GaAs',material_confirmed=True,states=[dict(label='on',electron_cm3=1e18,hole_cm3=1e18)]))
        future=Future();future.set_result(dict(values=dict(mass_e_m0=.063,heavy_hole_mass_m0=.51,light_hole_mass_m0=.082,mobility_e_cm2_Vs=8500,mobility_h_cm2_Vs=400,relative_permittivity=12.9,intrinsic_cm3=2.1e6),sources=['https://www.ioffe.ru/'],notes=['Hole conductivity mass not supplied.'],temperature_k=300,status='bundled-cache'))
        dialog.parameter_future=future;dialog.finish_parameters()
        self.assertEqual(dialog.fields['mass_e_m0'].text(),'0.063')
        self.assertEqual(dialog.fields['mass_h_m0'].text(),'')
        self.assertEqual(dialog.junction_fields['relative_permittivity'].text(),'12.9')
        dialog.hole_model.setCurrentText('Heavy-hole approximation')
        self.assertEqual(dialog.fields['mass_h_m0'].text(),'0.51')
        dialog.confirm.setChecked(True)
        cfg=dialog.configuration()
        self.assertEqual(cfg['parameter_record']['status'],'bundled-cache')
        self.assertEqual(cfg['hole_mass_model'],'Heavy-hole approximation')
        dialog.close()

    def test_material_selection_requests_data(self):
        from PyQt6.QtWidgets import QApplication
        from qt_carrier_index import CarrierIndexDialog
        app=QApplication.instance() or QApplication([])
        dialog=CarrierIndexDialog(configuration={'semiconductor':'Si'})
        with patch('qt_carrier_index._PARAMETER_POOL.submit',return_value=Future()) as submit:
            dialog.semiconductor.setCurrentText('AlGaAs')
            self.assertEqual(submit.call_args.args[1],'AlGaAs')
            self.assertEqual(submit.call_args.kwargs['x'],.3)
        dialog.parameter_timer.stop();dialog.close()

if __name__=='__main__':unittest.main()
