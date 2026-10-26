"""Conservation and geometry checks for actual three-dimensional transport."""
import importlib.util
import copy
import contextlib
import io
import uuid
import unittest

import numpy as np
from scipy.constants import e
from scipy.integrate import quad
from scipy.special import expit

from electrical_graph_transport import iter_graph_states,_electric_field_at_nodes
from electrical_fermi_transport import fermi_half_transport
from electrical_transport import iter_semiconductor_states,validate_transport
from tests.test_electrical_transport import planar_options, srh_settings


def fd_settings():
    return dict(mode='semiconductor_dd',statistics='fermi_dirac',
        heterojunction=dict(model='ideal_quasi_fermi',parameter_source='Explicit ideal-interface test assumption, not a calibrated GaAs/AlGaAs interface'))


def field_settings(cfg):
    cfg=copy.deepcopy(cfg)
    cfg['high_field_mobility']=dict(electron_saturation_velocity_cm_s=1e7,hole_saturation_velocity_cm_s=8e6,
        electron_exponent=2.,hole_exponent=1.,parameter_source='Explicit synthetic velocity test')
    cfg['avalanche']=dict(electron_A_cm1=2e4,electron_B_V_cm=2e5,electron_exponent=1.,
        hole_A_cm1=1e4,hole_B_V_cm=2e5,hole_exponent=1.,temperature_K=300.,
        parameter_source='Explicit synthetic ionization test, not a semiconductor fit')
    return cfg


class FermiIntegralTests(unittest.TestCase):
    def test_local_field_reconstruction_obeys_dielectric_displacement_continuity(self):
        # Two unit-width cells, with the two electrode-face ghosts. For
        # epsilon=(4,12) and total voltage 4, the exact local fields are (3,1).
        edges=np.array([[2,0],[0,1],[1,3]])
        direction=np.tile([1.,0.,0.],(3,1));area=np.full(3,2.)
        face_weight=np.array([[4.,4.,4.],[4.,4.,4.],[0.,0.,0.],[0.,0.,0.]])
        fields=_electric_field_at_nodes(np.array([3.,2.,1.]),np.array([4.,6.,12.]),
            np.array([4.,12.,4.,12.]),edges,direction,area,face_weight)
        np.testing.assert_allclose(fields[:2,0],[3.,1.],rtol=1e-14)
        self.assertAlmostEqual(fields[0,0]/fields[1,0],12/4)
        uniform=_electric_field_at_nodes(np.full(3,2.),np.full(3,7.),np.full(4,7.),
            edges,direction,area,face_weight)
        np.testing.assert_allclose(uniform[:2,0],2.,rtol=1e-14)

    def test_fd_requires_explicit_interface_and_rejects_boltzmann_srh(self):
        from custom_electrical_solver import build_mesh
        from electrical_graph_transport import _validate_graph_materials
        options=planar_options('gaas')
        options['device']['layers'][0]['material_id']='algaas'
        mesh=build_mesh(options['device'],options['material_library'])
        with self.assertRaisesRegex(ValueError,'explicitly sourced'):
            _validate_graph_materials(mesh,validate_transport(dict(mode='semiconductor_dd',statistics='fermi_dirac')))
        with self.assertRaisesRegex(ValueError,'Boltzmann SRH'):
            validate_transport(dict(srh_settings(),statistics='fermi_dirac'))
        options['device']['layers'][0]['material_id']='ito'
        mesh=build_mesh(options['device'],options['material_library'])
        # Guard even when a future mesher classifies a conductor as nonmobile.
        mesh['mobile'][mesh['material_index']==next(i for i,v in enumerate(mesh['materials']) if v['id']=='ito')]=False
        with self.assertRaisesRegex(ValueError,'Conductor interiors'):
            _validate_graph_materials(mesh,validate_transport(fd_settings()))

    def test_population_and_derivative_against_independent_adaptive_quadrature(self):
        eta=np.array([-40.,-16.,-12.,-8.,0.,1.,9.,24.,40.,63.99,64.,80.,200.])
        values,derivatives=fermi_half_transport(eta)
        exact=[];exact_derivative=[]
        for value in eta:
            stop=max(40.,value+50.)
            exact.append(2/np.sqrt(np.pi)*quad(lambda energy:energy**.5*expit(value-energy),0,stop,epsabs=1e-30,epsrel=2e-11)[0])
            exact_derivative.append(2/np.sqrt(np.pi)*quad(lambda energy:energy**.5*expit(value-energy)*expit(energy-value),0,stop,epsabs=1e-30,epsrel=2e-11)[0])
        np.testing.assert_allclose(values,exact,rtol=2e-9)
        np.testing.assert_allclose(derivatives,exact_derivative,rtol=2e-8)
        self.assertTrue(np.all(derivatives>0))
        sample=np.linspace(-15.9,63.9,101)+.003
        numerical=(fermi_half_transport(sample+1e-5)[0]-fermi_half_transport(sample-1e-5)[0])/2e-5
        np.testing.assert_allclose(numerical,fermi_half_transport(sample)[1],rtol=2e-8)


@unittest.skipUnless(importlib.util.find_spec('devsim') is not None,'optional native DEVSIM is not installed')
class GraphTransportTests(unittest.TestCase):
    def test_native_fd_newton_derivatives_match_value_perturbations(self):
        from electrical_solver import _load_core
        from electrical_fermi_transport import install_fermi_density
        ds=_load_core().ds;device='fermi_derivative_'+uuid.uuid4().hex;region='body'
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ds.create_1d_mesh(mesh=device)
                ds.add_1d_mesh_line(mesh=device,pos=0.,ps=1.,tag='left')
                ds.add_1d_mesh_line(mesh=device,pos=1.,ps=1.,tag='right')
                ds.add_1d_region(mesh=device,material='test',region=region,tag1='left',tag2='right')
                ds.add_1d_contact(mesh=device,name='left',tag='left',material='metal')
                ds.add_1d_contact(mesh=device,name='right',tag='right',material='metal')
                ds.finalize_mesh(mesh=device);ds.create_device(mesh=device,device=device)
                for key,values in (('Potential',[-25.,9.]),('Mobile',[1.,1.])):
                    ds.node_solution(device=device,region=region,name=key)
                    ds.set_node_values(device=device,region=region,name=key,values=values)
                    ds.edge_from_node_model(device=device,region=region,node_model=key)
                install_fermi_density(ds,device,region,'Density','Potential','Mobile',{'Potential':'1'})
            actual=np.asarray(ds.get_node_model_values(device=device,region=region,name='Density:Potential'))
            plus=[]
            for perturbation in (1e-5,-1e-5):
                ds.set_node_values(device=device,region=region,name='Potential',values=(np.array([-25.,9.])+perturbation).tolist())
                plus.append(np.asarray(ds.get_node_model_values(device=device,region=region,name='Density')))
            np.testing.assert_allclose((plus[0]-plus[1])/2e-5,actual,rtol=2e-8)
            self.assertTrue(np.all(actual>0))
        finally:
            if device in ds.get_device_list():ds.delete_device(device=device)
            if device in ds.get_mesh_list():ds.delete_mesh(mesh=device)

    def test_full_vector_avalanche_increases_silicon_reverse_current(self):
        options=planar_options(biases=(0.,-2.),count=40)
        cfg=field_settings(srh_settings())
        without_cfg=copy.deepcopy(cfg);without_cfg.pop('avalanche')
        without=list(iter_graph_states(options,without_cfg))[-1]
        state=list(iter_graph_states(options,cfg))[-1]
        self.assertGreater(state['checks']['peak_impact_generation_cm3_s'],0.)
        self.assertGreater(abs(state['terminal_current_A']['contact_p']),1.01*abs(without['terminal_current_A']['contact_p']))
        self.assertLess(state['checks']['relative_current_balance'],1e-4)

    def test_fermi_dirac_field_mobility_and_impact_generation_are_conservative(self):
        options=planar_options('gaas',doping=1e19,biases=(0.,.1),count=8)
        for layer in options['device']['layers']:layer.update(donor_cm3=1e19,acceptor_cm3=0.,thickness_um=.1)
        cfg=field_settings(fd_settings())
        state=list(iter_graph_states(options,cfg))[-1]
        self.assertGreater(state['checks']['peak_impact_generation_cm3_s'],0.)
        self.assertLess(state['checks']['relative_current_balance'],1e-7)

    def test_fermi_dirac_uniform_resistor_matches_analytic_current(self):
        options=planar_options('gaas',doping=1e19,biases=(0.,.02),count=8)
        options['device']['mesh'].update(nx=2,ny=2)
        for layer in options['device']['layers']:layer.update(donor_cm3=1e19,acceptor_cm3=0.)
        equilibrium,biased=list(iter_graph_states(options,fd_settings()))
        self.assertEqual(equilibrium['terminal_current_A']['contact_p'],0.)
        props=biased['mesh']['materials'][0]['properties']
        n=np.mean(biased['electrons_cm3']);p=np.mean(biased['holes_cm3'])
        sigma=e*100*(props['electron_mobility_cm2_Vs']*n+props['hole_mobility_cm2_Vs']*p)
        expected=sigma*4e-12*.02/2e-6
        self.assertAlmostEqual(biased['terminal_current_A']['contact_p']/expected,1.,places=8)
        self.assertLess(biased['checks']['relative_current_balance'],1e-8)
        self.assertEqual(biased['potential_gauge'],'vacuum')

    def test_degenerate_gaas_pn_transport_rectifies_without_spurious_equilibrium_current(self):
        options=planar_options('gaas',doping=1e19,biases=(0.,-.1,.1),count=30)
        equilibrium,reverse,forward=list(iter_graph_states(options,fd_settings()))
        self.assertEqual(equilibrium['terminal_current_A']['contact_p'],0.)
        self.assertLess(reverse['terminal_current_A']['contact_p'],0.)
        self.assertGreater(forward['terminal_current_A']['contact_p'],abs(reverse['terminal_current_A']['contact_p'])*5.)
        self.assertLess(forward['checks']['relative_current_balance'],1e-7)

    def test_ideal_heterojunction_equilibrium_and_biased_interface_continuity(self):
        options=planar_options('gaas',doping=1e17,biases=(0.,.01),count=16)
        options['device']['layers'][0].update(material_id='algaas',donor_cm3=1e17,acceptor_cm3=0.)
        options['device']['layers'][1].update(donor_cm3=1e17,acceptor_cm3=0.)
        equilibrium,biased=list(iter_graph_states(options,fd_settings()))
        self.assertEqual(equilibrium['terminal_current_A']['contact_p'],0.)
        np.testing.assert_array_equal(equilibrium['electron_quasi_fermi_eV'],0.)
        self.assertGreater(np.ptp(equilibrium['potential_V']),.05)
        self.assertGreater(biased['terminal_current_A']['contact_p'],0.)
        self.assertLess(biased['checks']['relative_current_balance'],1e-7)
        graph=biased['graph'];a,b=graph['edges'].T
        interface=graph['node_material_index'][a]!=graph['node_material_index'][b]
        total_face=biased['edge_electron_current_A']+biased['edge_hole_current_A']
        self.assertAlmostEqual(abs(np.sum(total_face[interface]))/abs(biased['terminal_current_A']['contact_p']),1.,places=7)

    def test_uniform_graph_resistor_matches_planar_analytic_current(self):
        options=planar_options(biases=(0.,.05),count=12)
        options['device']['mesh'].update(nx=3,ny=3)
        for layer in options['device']['layers']:layer.update(donor_cm3=1e15,acceptor_cm3=0.)
        planar=list(iter_semiconductor_states(options,dict(mode='semiconductor_dd')))[-1]
        graph=list(iter_graph_states(options,dict(mode='semiconductor_dd')))[-1]
        self.assertAlmostEqual(graph['terminal_current_A']['contact_p']/planar['terminal_current_A']['contact_p'],1.,places=8)
        self.assertLess(graph['checks']['relative_current_balance'],1e-8)

    def test_patterned_semiconductor_and_ring_contact_use_actual_3d_geometry(self):
        options=planar_options(biases=(0.,.05),count=8)
        options['device']['mesh'].update(nx=6,ny=6)
        for layer in options['device']['layers']:
            layer.update(donor_cm3=1e15,acceptor_cm3=0.)
            options['device']['shapes'].append(dict(id='hole_'+layer['id'],name='Through hole',layer_id=layer['id'],
                operation='void',material_id='air',shape='circle',cx_um=0.,cy_um=0.,size_x_um=.9,size_y_um=.9,
                angle_deg=0.,vertices=[],enabled=True))
        options['device']['contacts'][1].update(shape='square_ring',inner_size_x_um=1.,inner_size_y_um=1.)
        state=list(iter_graph_states(options,dict(mode='semiconductor_dd')))[-1]
        self.assertGreater(state['terminal_current_A']['contact_p'],0.)
        self.assertLess(state['checks']['relative_current_balance'],1e-7)
        passive=~state['mesh']['mobile'].ravel()
        np.testing.assert_array_equal(state['electrons_cm3'][passive],0.)
        np.testing.assert_array_equal(state['holes_cm3'][passive],0.)
        self.assertGreater(np.max(np.abs(state['electron_current_density_A_m2'][:,:2])),0.)

    def test_3d_pn_srh_reverse_current_is_conserved(self):
        options=planar_options(biases=(0.,-.2),count=30)
        options['device']['mesh'].update(nx=3,ny=3)
        state=list(iter_graph_states(options,srh_settings()))[-1]
        self.assertLess(state['terminal_current_A']['contact_p'],0.)
        self.assertLess(state['checks']['relative_current_balance'],1e-4)
        self.assertLess(state['checks']['relative_gauss_balance'],1e-6)


if __name__=='__main__':unittest.main()
