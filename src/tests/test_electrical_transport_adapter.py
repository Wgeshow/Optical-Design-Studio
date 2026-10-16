"""End-to-end native transport, physical result reconstruction and saved studies."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.constants import e, k

from custom_electrical_solver import solve
from electrical_terminal_studies import execute_studies
from tests.test_electrical_transport import planar_options


@unittest.skipUnless(importlib.util.find_spec('devsim') is not None,'optional native DEVSIM is not installed')
class TransportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd())
        self.directory=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_planar_physical_currents_and_affinity_gauge_match_saved_contract(self):
        options=planar_options(biases=(0.,.025,.05),count=12)
        for layer in options['device']['layers']:layer.update(donor_cm3=1e15,acceptor_cm3=0.)
        options.update(charge_model='semiconductor',transport=dict(mode='semiconductor_dd'))
        summary=solve(options,self.directory/'electrical')
        self.assertEqual(summary['transport_scope']['path'],'planar')
        self.assertTrue(summary['semiconductor_current_predicted'])
        for result in summary['results']:
            with np.load(result['volume_npz']) as data:
                self.assertEqual(data['current_density_A_m2'].shape,(2,2,24,3))
                self.assertTrue(np.isfinite(data['potential']).all())
                props=next(row['properties'] for row in summary['evaluated_materials'] if row['id']=='silicon')
                # A homogeneous Ohmic sample at its biased ideal top electrode
                # has F_n=-V_contact, independently setting the band reference.
                expected_shift=-props['affinity_eV']+(k/e*300)*np.log(props['intrinsic_cm3']/props['Nc_cm3'])
                self.assertAlmostEqual(summary['provenance']['potential_gauge_shift_V'],expected_shift)
        studies=execute_studies(summary,dict(iv_enabled=True,cv_enabled=True),self.directory)
        self.assertEqual(studies['studies']['iv']['model'],'Self-consistent semiconductor drift diffusion')
        self.assertNotIn('prescribed-reservoir', ' '.join(studies['studies']['cv']['warnings']))
        self.assertTrue((self.directory/'electrical_iv.csv').is_file())

    def test_patterned_graph_outputs_actual_voids_lateral_current_and_fields(self):
        options=planar_options(biases=(0.,.025,.05),count=8)
        options['device']['mesh'].update(nx=6,ny=6)
        for layer in options['device']['layers']:
            layer.update(donor_cm3=1e15,acceptor_cm3=0.)
            options['device']['shapes'].append(dict(id='hole_'+layer['id'],name='Through hole',layer_id=layer['id'],
                operation='void',material_id='air',shape='circle',cx_um=0.,cy_um=0.,size_x_um=.9,size_y_um=.9,
                angle_deg=0.,vertices=[],enabled=True))
        options['device']['contacts'][1].update(shape='square_ring',inner_size_x_um=1.,inner_size_y_um=1.)
        options.update(charge_model='semiconductor',transport=dict(mode='semiconductor_dd'))
        summary=solve(options,self.directory/'electrical')
        self.assertEqual(summary['transport_scope']['path'],'graph')
        self.assertEqual(summary['mesh']['native_dimensionality'],3)
        with np.load(summary['results'][-1]['volume_npz']) as data:
            self.assertEqual(data['potential'].shape,(6,6,16))
            self.assertTrue(np.any(~data['solid']))
            np.testing.assert_array_equal(data['electrons_cm3'][~data['solid']],0.)
            np.testing.assert_array_equal(data['holes_cm3'][~data['solid']],0.)
            self.assertGreater(np.max(np.abs(data['current_density_A_m2'][...,:2])),0.)
            edges=data['transport_graph_edges']
            current=data['edge_electron_current_A']+data['edge_hole_current_A']
            count=int(data['transport_graph_cell_count'])
            residual=(np.bincount(edges[:,0],weights=current,minlength=len(data['transport_graph_node_xyz_m']))
                      -np.bincount(edges[:,1],weights=current,minlength=len(data['transport_graph_node_xyz_m'])))[:count]
            scale=max(np.max(np.abs(current)),1e-30)
            self.assertLess(np.max(np.abs(residual)),1e-7*scale)
            np.testing.assert_array_equal(data['transport_graph_node_volume_m3'][count:],0.)
        self.assertLess(summary['results'][-1]['checks']['relative_current_balance'],1e-7)

    def test_fd_ideal_interface_saves_quasi_fermi_energy_and_face_current(self):
        from tests.test_electrical_graph_transport import fd_settings
        options=planar_options('gaas',doping=1e17,biases=(0.,.01),count=8)
        options['device']['layers'][0].update(material_id='algaas',donor_cm3=1e17,acceptor_cm3=0.)
        options['device']['layers'][1].update(donor_cm3=1e17,acceptor_cm3=0.)
        options.update(charge_model='semiconductor',transport=fd_settings())
        summary=solve(options,self.directory/'electrical')
        self.assertEqual(summary['transport_scope']['path'],'graph')
        with np.load(summary['results'][0]['volume_npz']) as data:
            np.testing.assert_array_equal(data['electron_quasi_fermi_eV'],0.)
            self.assertGreater(np.ptp(data['potential']),.05)
        with np.load(summary['results'][-1]['volume_npz']) as data:
            self.assertEqual(data['hole_quasi_fermi_eV'].shape,data['potential'].shape)
            self.assertTrue(np.isfinite(data['hole_quasi_fermi_eV']).all())
            self.assertGreater(np.ptp(data['electron_quasi_fermi_eV']),0.)
            self.assertEqual(len(data['edge_electron_current_A']),len(data['transport_graph_edges']))
            self.assertIn('saved_face_currents',summary['provenance'])

    def test_dielectric_leakage_is_run_even_without_requested_iv_export(self):
        options=planar_options(biases=(0.,.1,.2),count=8)
        options['material_library'].append(dict(id='oxide',name='Explicit test dielectric',kind='dielectric',model='constant',
            temperature_K=300.,properties=dict(epsilon_r=4.),sources=[]))
        for layer in options['device']['layers']:layer.update(material_id='oxide',donor_cm3=0.,acceptor_cm3=0.)
        for contact in options['device']['contacts']:contact['boundary']='potential'
        options.update(charge_model='dielectric',transport=dict(mode='dielectric_leakage',material_models={
            'oxide':dict(mechanism='ohmic',parameters=dict(conductivity_S_m=1e-8,parameter_source='Independent synthetic resistor QA, not a paper fit'))}))
        summary=solve(options,self.directory/'electrical')
        self.assertGreater(summary['dielectric_leakage']['rows'][-1]['current_A'],0.)
        self.assertIn('dielectric_transport',summary['results'][-1]['checks'])
        saved=json.loads(Path(summary['summary_json']).read_text())
        self.assertIn('dielectric_leakage',saved)


if __name__=='__main__':unittest.main()
