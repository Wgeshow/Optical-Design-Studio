"""Independent physical limits and native current-conservation regression tests."""
import copy
import importlib.util
import math
import unittest

import numpy as np
from scipy.constants import e, epsilon_0, k

from device_model import default_device
from electrical_material_library import builtin_materials
from electrical_transport import (ModelValidityError, avalanche_integral,
    barrier_lowering_eV, dielectric_leakage_iv, direct_tunnel_current_density,
    field_breakdown_screen, fowler_nordheim_current_density, ionization_coefficient,
    iter_semiconductor_states, neutral_carriers, poole_frenkel_current_density,
    srh_rate, validate_planar_device, validate_transport)


def planar_options(material='silicon', doping=1e16, biases=(0.,-.2,.2), count=60):
    device=default_device()
    device['layers']=[dict(id='p',name='P',material_id=material,thickness_um=1.,
                           donor_cm3=0.,acceptor_cm3=doping,enabled=True),
                      dict(id='n',name='N',material_id=material,thickness_um=1.,
                           donor_cm3=doping,acceptor_cm3=0.,enabled=True)]
    device['contacts'][0]['layer_id']='n'
    device['contacts'][1]['layer_id']='p'
    device['mesh'].update(nx=2,ny=2,nz_per_layer=count)
    return dict(device=device,material_library=builtin_materials(),biases_V=list(biases),swept_contact_id='contact_p')


def srh_settings(tau=1e-7):
    return dict(mode='semiconductor_dd',srh=dict(tau_n_s=tau,tau_p_s=tau,
        trap_energy_eV=0.,parameter_source='Explicit synthetic test lifetime, not a material default'))


def dielectric_options():
    options=planar_options()
    options['material_library'].append(dict(id='oxide',name='Test oxide',kind='dielectric',model='constant',
        temperature_K=300.,properties=dict(epsilon_r=4.),sources=[]))
    for layer in options['device']['layers']:
        layer.update(material_id='oxide',donor_cm3=0.,acceptor_cm3=0.,thickness_um=.1)
    for contact in options['device']['contacts']:contact['boundary']='potential'
    return options


class TransportKernelTests(unittest.TestCase):
    def test_neutral_carriers_resolve_gaas_minority_without_cancellation(self):
        n,p=neutral_carriers(np.array([-1e19,0.,1e19]),2e6)
        np.testing.assert_allclose(n*p,(2e6)**2,rtol=1e-15)
        np.testing.assert_allclose(n-p,[-1e19,0.,1e19],rtol=1e-15)
        self.assertGreater(float(n[0]),0.)

    def test_srh_equilibrium_zero_and_depletion_generation_limit(self):
        params=srh_settings(1e-6)['srh']
        ni=1e10
        self.assertEqual(float(srh_rate(ni,ni,ni,300.,params)),0.)
        self.assertAlmostEqual(float(srh_rate(0.,0.,ni,300.,params))/(-ni/2e-6),1.)
        self.assertGreater(float(srh_rate(1e14,1e14,ni,300.,params)),0.)

    def test_image_lowering_matches_coulomb_barrier_and_pf_factor_two(self):
        field=1e7;eps=3.
        expected=math.sqrt(e*field/(4*math.pi*epsilon_0*eps))
        self.assertAlmostEqual(float(barrier_lowering_eV(field,eps)),expected)
        self.assertAlmostEqual(float(barrier_lowering_eV(field,eps,poole_frenkel=True)),2*expected)

    def test_pf_arrhenius_dependence_and_odd_zero_current(self):
        p=dict(conductivity_prefactor_S_m=1.,trap_depth_eV=.6,optical_epsilon_r=4.)
        field=1e6
        j300=float(poole_frenkel_current_density(field,300,p));j400=float(poole_frenkel_current_density(field,400,p))
        activation=.6-float(barrier_lowering_eV(field,4.,poole_frenkel=True))
        self.assertAlmostEqual(math.log(j400/j300),activation/(k/e)*(1/300-1/400))
        self.assertEqual(float(poole_frenkel_current_density(0,300,p)),0.)
        self.assertEqual(float(poole_frenkel_current_density(-field,300,p)),-j300)
        with self.assertRaises(ModelValidityError):poole_frenkel_current_density(1e10,300,p)

    def test_fn_inverse_field_plot_is_linear_and_mass_suppresses_tunneling(self):
        fields=np.array([2e8,3e8,4e8])
        p=dict(barrier_eV=1.5,tunnel_mass_ratio=.3)
        current=fowler_nordheim_current_density(fields,p)
        slopes=np.diff(np.log(current/fields**2))/np.diff(1/fields)
        self.assertAlmostEqual(slopes[0]/slopes[1],1.,places=13)
        self.assertTrue(np.all(fowler_nordheim_current_density(fields,dict(p,tunnel_mass_ratio=.6))<current))
        self.assertEqual(float(fowler_nordheim_current_density(0.,p)),0.)

    def test_simmons_low_voltage_is_ohmic_odd_and_exponentially_width_sensitive(self):
        p=dict(barrier_eV=2.,tunnel_mass_ratio=.5)
        voltage=np.array([-1e-6,0.,1e-6,2e-6])
        current=direct_tunnel_current_density(voltage,2e-9,p)
        self.assertEqual(current[1],0.)
        self.assertAlmostEqual(current[0]/current[2],-1.)
        self.assertAlmostEqual(current[3]/current[2],2.,places=7)
        self.assertLess(float(direct_tunnel_current_density(1e-6,3e-9,p)),current[2]*.01)
        with self.assertRaises(ModelValidityError):direct_tunnel_current_density(2.,2e-9,p)

    def test_ionization_zero_field_and_constant_equal_coefficient_breakdown(self):
        self.assertEqual(float(ionization_coefficient(0.,1e6,1e6,1.)),0.)
        z=np.linspace(0.,1e-6,1001)
        for coefficient in (1e5,1e6,2e6):
            self.assertAlmostEqual(avalanche_integral(z,np.full(z.shape,coefficient),np.full(z.shape,coefficient)),coefficient*1e-6)
        # For beta=0 the exact integral is 1-exp(-alpha W), so a finite
        # multiplication region cannot reach self-sustaining breakdown.
        value=avalanche_integral(z,np.full(z.shape,2e6),np.zeros(z.shape))
        self.assertAlmostEqual(value,1-math.exp(-2),places=6)

    def test_missing_physical_sources_and_unsupported_geometry_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'parameter_source'):
            validate_transport(dict(mode='semiconductor_dd',srh=dict(tau_n_s=1e-6,tau_p_s=1e-6,trap_energy_eV=0.)))
        options=planar_options()
        options['device']['contacts'][1]['size_x_um']=1.
        with self.assertRaisesRegex(ValueError,'entire device face'):
            validate_planar_device(options,srh_settings())
        options=planar_options('gaas',1e20)
        with self.assertRaisesRegex(ModelValidityError,'nondegenerate'):
            validate_planar_device(options,srh_settings())
        options=planar_options();options['device']['layers'][0]['material_id']='gaas'
        with self.assertRaisesRegex(ValueError,'heterojunction'):
            validate_planar_device(options,srh_settings())

    def test_series_dielectric_current_is_conserved_with_correct_voltage_partition(self):
        options=dielectric_options()
        second=copy.deepcopy(options['material_library'][-1]);second['id']='oxide2'
        options['material_library'].append(second)
        options['device']['layers'][1]['material_id']='oxide2'
        cfg=dict(mode='dielectric_leakage',material_models={
            'oxide':dict(mechanism='ohmic',parameters=dict(conductivity_S_m=1e-8,parameter_source='Synthetic test')),
            'oxide2':dict(mechanism='ohmic',parameters=dict(conductivity_S_m=1e-12,parameter_source='Synthetic test'))})
        rows,meta=dielectric_leakage_iv(dict(options=options),cfg)
        conductance=4e-12/(1e-7/1e-8+1e-7/1e-12)
        for row,check in zip(rows,meta['checks']):
            self.assertAlmostEqual(row['current_A'],conductance*row['bias_V'],delta=max(1e-30,abs(row['current_A'])*1e-10))
            self.assertAlmostEqual(check['voltage_balance_V'],0.,places=12)
            self.assertEqual(sum(check['terminal_current_A'].values()),0.)

    def test_breakdown_criteria_do_not_return_post_damage_current(self):
        options=dielectric_options();options['biases_V']=[0.,.1,.4]
        cfg=dict(mode='dielectric_leakage',material_models={'oxide':dict(mechanism='ohmic',
            parameters=dict(conductivity_S_m=1e-8,parameter_source='Synthetic test'))},
            breakdown_fields={'oxide':dict(critical_field_V_m=1e6,parameter_source='Synthetic threshold, not a material default')})
        rows,meta=dielectric_leakage_iv(dict(options=options),cfg)
        self.assertIsNotNone(rows[1]['current_A'])
        self.assertIsNone(rows[2]['current_A'])
        self.assertTrue(meta['checks'][2]['breakdown']['criterion_reached'])
        self.assertIn('no damage',field_breakdown_screen({'unknown':[1e10]}, {})['model'])


@unittest.skipUnless(importlib.util.find_spec('devsim') is not None,'optional native DEVSIM is not installed')
class NativeTransportTests(unittest.TestCase):
    def test_silicon_diode_rectifies_and_conserves_current(self):
        states=list(iter_semiconductor_states(planar_options(),srh_settings()))
        zero,reverse,forward=states
        self.assertLess(abs(zero['terminal_current_A']['contact_p']),1e-15)
        self.assertLess(reverse['terminal_current_A']['contact_p'],0.)
        self.assertGreater(forward['terminal_current_A']['contact_p'],abs(reverse['terminal_current_A']['contact_p'])*10)
        for state in states:
            self.assertLess(state['checks']['relative_gauss_balance'],1e-6)
            self.assertLess(abs(sum(state['terminal_current_A'].values())),1e-14)

    def test_gaas_diode_continuity_runs_with_actual_material_parameters(self):
        states=list(iter_semiconductor_states(planar_options('gaas',1e15,(0.,-.2,.4)),srh_settings()))
        self.assertLess(states[1]['terminal_current_A']['contact_p'],0.)
        self.assertGreater(states[2]['terminal_current_A']['contact_p'],0.)
        self.assertTrue(all(np.isfinite(state['electrons_cm3']).all() for state in states))
        for state in states[1:]:
            scale=max(abs(value) for value in state['terminal_current_A'].values())
            self.assertLess(state['checks']['current_balance_A'],max(1e-28,1e-7*scale))

    def test_extended_precision_settings_are_restored_when_generator_closes(self):
        from electrical_solver import _load_core
        ds=_load_core().ds
        keys=('extended_model','extended_equation','extended_solver')
        original={}
        for key in keys:
            try:original[key]=ds.get_parameter(name=key)
            except ds.error:original[key]=False
        requested=dict(zip(keys,(False,True,False)))
        stream=None
        try:
            for key,value in requested.items():ds.set_parameter(name=key,value=value)
            stream=iter_semiconductor_states(planar_options(biases=(0.,.1)),srh_settings())
            next(stream)
            self.assertTrue(all(ds.get_parameter(name=key) for key in keys))
            stream.close()
            self.assertEqual({key:ds.get_parameter(name=key) for key in keys},requested)
        finally:
            if stream is not None:stream.close()
            for key,value in original.items():ds.set_parameter(name=key,value=value)

    def test_homogeneous_resistor_matches_analytic_drift_current(self):
        options=planar_options(biases=(0.,.05),count=30)
        for layer in options['device']['layers']:layer.update(donor_cm3=1e15,acceptor_cm3=0.)
        states=list(iter_semiconductor_states(options,dict(mode='semiconductor_dd')))
        properties=next(row for row in builtin_materials() if row['id']=='silicon')['properties']
        n,p=neutral_carriers(1e15,properties['intrinsic_cm3'])
        sigma=e*100*(n*properties['electron_mobility_cm2_Vs']+p*properties['hole_mobility_cm2_Vs'])
        expected=float(sigma)*4e-12/2e-6*.05
        self.assertAlmostEqual(states[-1]['terminal_current_A']['contact_p']/expected,1.,places=8)

    def test_srh_reverse_generation_and_mesh_refinement(self):
        options=planar_options(biases=(0.,-1.),count=60)
        first=list(iter_semiconductor_states(options,srh_settings(1e-7)))[-1]
        options['device']['mesh']['nz_per_layer']=120
        refined=list(iter_semiconductor_states(options,srh_settings(1e-7)))[-1]
        slower=list(iter_semiconductor_states(options,srh_settings(1e-6)))[-1]
        self.assertLess(abs(first['terminal_current_A']['contact_p']/refined['terminal_current_A']['contact_p']-1),.03)
        self.assertGreater(abs(refined['terminal_current_A']['contact_p']/slower['terminal_current_A']['contact_p']),5.)

    def test_impact_generation_increases_reverse_current_and_preserves_continuity(self):
        options=planar_options(biases=(0.,-2.),count=90)
        cfg=srh_settings()
        cfg['high_field_mobility']=dict(electron_saturation_velocity_cm_s=1e7,hole_saturation_velocity_cm_s=8e6,
            electron_exponent=2.,hole_exponent=1.,parameter_source='Explicit synthetic velocity saturation test')
        without=list(iter_semiconductor_states(options,cfg))[-1]
        cfg['avalanche']=dict(electron_A_cm1=2e4,electron_B_V_cm=2e5,electron_exponent=1.,
            hole_A_cm1=1e4,hole_B_V_cm=2e5,hole_exponent=1.,temperature_K=300.,
            parameter_source='Explicit synthetic coefficients to verify coupled impact generation, not a silicon parameter fit')
        with_impact=list(iter_semiconductor_states(options,cfg))[-1]
        self.assertGreater(with_impact['checks']['peak_impact_generation_cm3_s'],0.)
        self.assertGreater(abs(with_impact['terminal_current_A']['contact_p']),1.01*abs(without['terminal_current_A']['contact_p']))
        self.assertLess(abs(sum(with_impact['terminal_current_A'].values())),1e-15)


if __name__=='__main__':
    unittest.main()
