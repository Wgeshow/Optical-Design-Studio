import unittest
import pandas as pd
from qt_compute import sweep_analysis_display


class SweepDisplayColumnsTests(unittest.TestCase):
    def test_ranked_value_is_visible_before_metadata_and_export_is_unchanged(self):
        original=pd.DataFrame([dict(design_id=4,lattice_x_um=1,basis=49,material='Si',status='evaluated',response='Transmission',response_value=.2,wavelength_nm=1200)])
        exported_before=original.to_csv(index=False)
        shown=sweep_analysis_display(original)
        self.assertEqual(list(shown.columns[:4]),['design_id','response','response_value','wavelength_nm'])
        self.assertEqual(set(shown.columns),set(original.columns))
        pd.testing.assert_frame_equal(shown.loc[:,original.columns],original)
        self.assertEqual(original.to_csv(index=False),exported_before)

    def test_q_feature_and_limitation_stay_ahead_of_geometric_metadata(self):
        original=pd.DataFrame([dict(design_id=5,lattice_x_um=1,material='Si',status='evaluated',response='Transmission',feature='dip',response_value=.8,wavelength_nm=1200,Q_estimate=7.8,fwhm_nm=153,linewidth_status='baseline-relative FWHM estimate; verify convergence')])
        shown=sweep_analysis_display(original)
        self.assertEqual(list(shown.columns[:4]),['design_id','response','feature','Q_estimate'])
        self.assertLess(shown.columns.get_loc('linewidth_status'),shown.columns.get_loc('material'))
        pd.testing.assert_frame_equal(shown.loc[:,original.columns],original)

if __name__=='__main__':unittest.main()
