import unittest
import numpy as np
from scipy.constants import hbar,e,epsilon_0,k
from high_field_optics import validate_material,absorption_spectrum,response
from nonlocal_tunnelling import validate_tunnelling,source


class HighFieldOpticalTests(unittest.TestCase):
    def test_screening_shift_recovers_nondegenerate_debye_limit(self):
        from bandgap_narrowing import screening_shift_eV
        density=1e14;nc=4.7e17;nv=7e18;temperature=300.;eps=12.9
        actual=float(screening_shift_eV(density,nc,nv,4.07,1.424,eps,temperature))
        exact=e/(4*np.pi*eps*epsilon_0)*np.sqrt(e*density*1e6/(eps*epsilon_0*(k*temperature/e)))
        self.assertLess(abs(actual/exact-1),5e-5)
        self.assertEqual(float(screening_shift_eV(density,nc,nv,4.07,1.424,eps,temperature,scale=0.)),0.)

    def test_zero_field_reference_and_index_change(self):
        material=validate_material(dict(electron_mass_ratio=.066,hole_mass_ratios=[.45,.084],
            absorption_prefactor_cm1_sqrt_eV=2.3e12*np.sqrt(hbar/e),reference_gap_eV=1.424,source='Recovered GaAs sensitivity assumption'))
        energies=np.linspace(1.5,2.,51)
        exact=material['absorption_prefactor_cm1_sqrt_eV']*np.sqrt(energies-1.424)/energies
        actual=absorption_spectrum(energies,1.424,0.,-100.,-100.,300.,material)
        np.testing.assert_allclose(actual,exact,rtol=2e-14)
        result=response([1140.,1150.,1160.],1.424,0.,-100.,-100.,300.,material,energy_order=1024)
        np.testing.assert_allclose(result['delta_n'],0.,atol=1e-12)
        np.testing.assert_array_equal(result['delta_k'],0.)

    def test_finite_field_sensitivity_has_stable_kk_refinement(self):
        material=validate_material(dict(electron_mass_ratio=.066,hole_mass_ratios=[.45,.084],
            absorption_prefactor_cm1_sqrt_eV=2.3e12*np.sqrt(hbar/e),reference_gap_eV=1.424,source='Recovered sensitivity coefficients'))
        first=response([1150.],1.39,1.3e8,-5.,-5.,300.,material,energy_order=4096)
        second=response([1150.],1.39,1.3e8,-5.,-5.,300.,material,energy_order=8192)
        self.assertLess(abs(first['delta_n'][0]-second['delta_n'][0]),2e-4)
        self.assertGreater(first['absorption_cm1'][0],0.)


class NonlocalKernelTests(unittest.TestCase):
    def calculate(self,length,fn=-1.,fp=0.):
        faces=[np.array([0.,1e-6]),np.array([0.,1e-6]),np.linspace(0.,length,61)]
        axes=[(a[1:]+a[:-1])/2 for a in faces]
        z=axes[2];shape=(1,1,len(z));volume=np.broadcast_to(1e-12*np.diff(faces[2]),shape)
        conduction=(.75-1.5*z/length).reshape(shape);valence=conduction-1.
        cfg=validate_tunnelling(dict(axis='z',path_min_um=0.,path_max_um=length*1e6,hole_reservoir_um=z[0]*1e6,electron_reservoir_um=z[-1]*1e6,
            transverse_mass_ratio=.06,energy_order=20,transverse_order=10,materials={'test':dict(electron_gamma_mass_ratio=.067,hole_mass_ratio=.5)},source='Synthetic WKB barrier'))
        return source(axes,faces,volume,np.ones(shape,bool),conduction,valence,.067,.5,fn,fp,300.,cfg)

    def test_equilibrium_exact_zero_and_nonlocal_pair_conservation(self):
        equilibrium=self.calculate(20e-9,fn=0.,fp=0.)
        self.assertEqual(equilibrium['checks']['integrated_pairs_s'],0.)
        biased=self.calculate(20e-9)
        self.assertGreater(biased['checks']['integrated_pairs_s'],0.)
        self.assertLess(abs(biased['checks']['pair_balance_error_s'])/biased['checks']['integrated_pairs_s'],1e-12)
        self.assertTrue(biased['transfers'])

    def test_wider_barrier_suppresses_transmission(self):
        thin=self.calculate(20e-9)['checks']['integrated_pairs_s']
        thick=self.calculate(40e-9)['checks']['integrated_pairs_s']
        self.assertLess(thick,thin*.1)


if __name__=='__main__':unittest.main()
