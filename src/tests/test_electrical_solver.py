import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import electrical_solver as solver
from electrical_physics import reference,device


class ElectricalSolverTests(unittest.TestCase):
    def test_validation_preserves_geometry_and_rejects_unmodelled_inputs(self):
        cfg=solver.validate_options({'biases_V':[-2]})
        self.assertEqual(cfg['biases_V'],[0.,-2.])
        self.assertEqual(cfg['ito_density_cm3'],8e20)
        for options in ({'biases_V':[1]},{'mesh_level':True},{'ito_density_cm3':float('nan')},
                        {'ito_thickness_nm':50},{'temperature_K':310},
                        {'geometry_parameters':{'external_gap_nm':10}},
                        {'net_doping_cm3':[-1e20,-1e19,0,8e18,1e19]}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                solver.validate_options(options)

    def test_measured_load_requires_coverage_and_unique_biases(self):
        for rows in ([{'bias_V':-1,'current_A':0},{'bias_V':0,'current_A':0}],
                     [{'bias_V':0,'current_A':0},{'bias_V':0,'current_A':1e-9}]):
            with self.assertRaises(ValueError):solver.validate_options({'measured_current':rows})
        cfg=solver.validate_options({'measured_current':[{'bias_V':0,'current_A':1e-10},
            {'bias_V':-2,'current_A':-1e-9}]})
        self.assertEqual(cfg['measured_current'][0]['bias_V'],-2)

    def test_optional_dependency_and_cancellation(self):
        with patch.object(importlib.util,'find_spec',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'optional DEVSIM'):solver._load_core()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            with self.assertRaises(InterruptedError):solver.solve({},directory,cancelled=lambda:True)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_ito_sheet_resistance_constrains_mobility(self):
        from scipy.constants import e
        par=device.ito_parameters(5e20,45)
        rho=1/(e*5e26*par['mobility_cm2_Vs']*1e-4)
        self.assertAlmostEqual(rho/(40e-9),45,places=10)
        self.assertGreater(par['eta_bulk'],20)

    def test_planar_reference_conserves_charge_and_voltage(self):
        equilibrium=reference.solve(0,.2)
        biased=reference.solve(-2,.2,equilibrium)
        for data in (equilibrium,biased):
            self.assertLess(data['integrated_Gauss_error_C_m2'],1e-9)
            self.assertLess(data['integrated_voltage_error_V'],1e-10)
            self.assertLess(data['max_normalized_Poisson_residual'],1e-10)
        barrier=(biased['z_face_m']>=202e-9)&(biased['z_face_m']<=218e-9)
        self.assertGreater(abs(biased['field_V_m'][barrier]).max(),
                           abs(equilibrium['field_V_m'][barrier]).max())

    def test_independent_explicit_ito_seed(self):
        par=device.ito_parameters()
        zero=device.planar_ito(par)
        minus=device.planar_ito(par,-2,initial=zero)
        self.assertLess(minus['residual'],3e-9)
        self.assertLess(minus['gauss_C_m2'],1e-7)
        self.assertTrue(np.isfinite(minus['electrons_cm3']).all())

    def test_five_nanometre_gap_and_real_pad(self):
        x=np.array([50e-6,50.005e-6,60e-6,78e-6,390e-6])
        y=np.zeros(5);z=np.zeros(5)
        p,n=device.masks(x,y,z,True)
        self.assertEqual(p.tolist(),[False,True,True,False,False])
        self.assertFalse(n.any())
        _,pad=device.masks(x,y,np.full(5,420e-9),True)
        self.assertEqual(pad.tolist(),[False,False,False,True,True])

    def test_sheet_current_and_power_balance(self):
        data,checks=device.sheet(10.)
        self.assertLess(checks['current_balance_relative'],1e-8)
        self.assertLess(checks['power_balance_relative'],1e-8)
        self.assertTrue(np.all(data['transfer'][data['contact']]==0))

    def test_profile_preserves_solid_density_and_interface_identity(self):
        z=np.array([0,50,100,199,200,210,220,300,370,415,420,421,430,445,460])*1e-9
        shape=(3,3,len(z));sem=np.broadcast_to((z<=420e-9)[None,None,:],shape)
        ito=np.broadcast_to((z>420e-9)[None,None,:],shape)
        fraction=sem.astype(float)*.9
        data=dict(x=np.array([0,25,50])*1e-6,y=np.array([-50,0,50])*1e-6,z=z,
            ga_fraction=fraction,al_fraction=np.zeros(shape),
            electrons_cm3=fraction*1e18+ito*8e20,holes_cm3=fraction*1e16,
            ito_fraction=ito.astype(float),ito_electrons_cm3=np.full(shape,8e20),
            field_V_m=np.broadcast_to(np.array([0,0,1e7]),shape+(3,)).copy())
        profile,layers=solver._profile(data,device.ito_parameters(),True)
        self.assertEqual(profile['layer_name'][profile['z_nm']==420].tolist(),['n+ GaAs'])
        np.testing.assert_allclose(profile['ito_electrons_cm3'][profile['layer_name']=='ITO'],8e20,rtol=1e-12)
        np.testing.assert_allclose(profile['Ez_V_m'][profile['layer_name']=='ITO'],1e7,rtol=1e-12)
        np.testing.assert_allclose(profile['Ez_squared_V2_m2'][profile['layer_name']=='ITO'],1e14,rtol=1e-12)
        self.assertAlmostEqual(sum(r['thickness_nm'] for r in layers),460)
        for row in layers:
            if row['material']=='ITO':
                self.assertAlmostEqual(row['ito_electrons_cm3']/8e20,1)
                self.assertAlmostEqual(row['field_V_m']/1e7,1)
            else:self.assertAlmostEqual(row['electrons_cm3']/1e18,1)


if __name__=='__main__':unittest.main()
