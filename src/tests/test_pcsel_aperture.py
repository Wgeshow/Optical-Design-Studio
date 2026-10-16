import copy
import unittest
import numpy as np
from pcsel_research import paper_example,prepare,InputValidationError
from pcsel_aperture import calibration_domain,ApertureDevice,load_value


def example():
    """Synthetic QA load and sourced-study rate coefficients, not a paper fit."""
    cfg=paper_example();cfg.update(model='aperture',grid_nm=2.,aperture_um=[200.,200.])
    cfg['aperture']=dict(grid_n=10,currents_A=[.0004],contacts=[dict(shape='ring',cx_um=0.,cy_um=0.,width_um=200.,height_um=200.,inner_width_um=160.,inner_height_um=160.)],
        sheet_ohm_square=5.,sheet_temperature_exponent=1.5,reference_temperature_K=300.,sink_K=300.,
        substrate_um=100.,substrate_k_W_mK=55.,thermal_k_exponent=1.2,interface_R_m2K_W=1e-7,epitaxial_R_m2K_W=1e-8,
        well_total_nm=24.,capture_ps=3.,escape_ps=700.,barrier_lifetime_ps=200.,escape_activation_eV=.15,
        A_s1=1e9,B_cm3_s=1e-10,C_cm6_s=1e-30,g0_cm1=3000.,Ntr_cm3=8e17,gain_temperature_K=150.,
        group_index=3.6,Gamma_QW=.04,alpha_rad_cm1=10.,alpha_edge_cm1=5.,alpha_internal_cm1=5.,
        port_fraction=.5,port_transmission=.7,wavelength_nm=980.,load_reference_V=1.1,max_temperature_K=500.,
        voltage_bracket_V=[.1,3.],load_source='Synthetic monotone QA load; not a measured or paper device.',
        load_anchors=[dict(voltage_V=1.,current_density_A_cm2=.5,accepted_solver_checks=True),dict(voltage_V=1.2,current_density_A_cm2=2.,accepted_solver_checks=True)],
        load_domain=calibration_domain(cfg),heated=True)
    return cfg


class ApertureTests(unittest.TestCase):
    def test_log_load_and_derivative_match_analytic(self):
        p=example()['aperture'];v=np.array([1.1]);T=np.array([300.]);j,dj,_=load_value(v,T,p)
        self.assertAlmostEqual(float(j[0]),1e4,7)
        self.assertAlmostEqual(float(dj[0]/j[0]),np.log(4)/.2,10)

    def test_reduced_solver_conserves_current_energy_and_accepts_edited_aperture(self):
        cfg=example();first=ApertureDevice(prepare({},cfg));row,fields=first.run(.0004)
        self.assertTrue(row['accepted_solver_checks'],row)
        self.assertGreater(row['temperature_max_K'],300.)
        self.assertLess(row['total_energy_error'],1e-5)
        self.assertAlmostEqual(float(fields['current_A_cm2'].sum()*1e4*first.area),.0004,10)
        changed=copy.deepcopy(cfg);changed['aperture_um']=[300.,200.]
        changed['aperture']['contacts'][0].update(width_um=300.,inner_width_um=240.)
        second=ApertureDevice(prepare({},changed));other,_=second.run(.0004)
        self.assertTrue(other['accepted_solver_checks'],other)
        self.assertGreater(abs(other['voltage_V']-row['voltage_V']),.01)

    def test_changed_pattern_invalidates_calibration(self):
        cfg=example();cfg['shapes'][0]['radius']*=.9
        with self.assertRaises(InputValidationError) as raised:prepare({},cfg)
        self.assertEqual(raised.exception.diagnostics[0]['field'],'aperture.load_domain')


if __name__=='__main__':unittest.main()
