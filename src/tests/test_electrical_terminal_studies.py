"""Analytical electrode-charge and resistor checks for terminal studies."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.constants import epsilon_0

from custom_electrical_solver import build_mesh,solve
from device_model import default_device
from electrical_material_library import builtin_materials
from electrical_terminal_studies import (execute_studies, ohmic_iv,
                                         _conductivity,
                                         read_measured_csv, terminal_cv,
                                         validate_studies)


def resistor_device():
    library=builtin_materials()
    material=dict(id='user_conductor',name='User fixed conductor',kind='dielectric',model='constant',temperature_K=300.,
        properties=dict(epsilon_r=4.,conductivity_S_m=2.),sources=[])
    library.append(material)
    device=default_device()
    device['layers']=[dict(id='slab',name='User slab',material_id='user_conductor',
        thickness_um=.3,donor_cm3=0.,acceptor_cm3=0.,enabled=True)]
    device['mesh'].update(nx=4,ny=4,nz_per_layer=12)
    for contact in device['contacts']:
        contact.update(layer_id='slab',boundary='potential')
    # Default contact P is top swept; default N is bottom fixed.
    return device,library


class TerminalStudyTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.directory.cleanup)

    def solved(self,device=None,library=None,biases=None):
        if device is None:
            device,library=resistor_device()
        return solve(dict(device=device,material_library=library,
                          charge_model='dielectric',biases_V=biases or [0.,-.4,-1.7]),self.directory.name)

    def test_cv_nonuniform_voltage_steps_reproduce_analytic_plate_capacitance(self):
        summary=self.solved(); rows,metadata=terminal_cv(summary)
        expected=4.*epsilon_0*4e-12/.3e-6
        np.testing.assert_allclose([row['capacitance_F'] for row in rows],expected,rtol=1e-11)
        self.assertEqual([row['terminal_voltage_V'] for row in rows],[-1.7,-.4,0.])
        self.assertIn('dQ_swept_electrode',metadata['sign_convention'])

    def test_ohmic_current_matches_resistor_and_conserves_current_and_power(self):
        summary=self.solved(); rows,metadata=ohmic_iv(summary)
        conductance=2.*4e-12/.3e-6
        for row in rows:
            self.assertAlmostEqual(row['current_A'],conductance*row['terminal_voltage_V'],places=14)
        for check in metadata['checks']:
            self.assertLess(check['current_balance_A'],1e-14)
            if check['bias_V']:
                self.assertLess(check['relative_current_balance'],1e-10)
            self.assertAlmostEqual(check['power_W'],conductance*check['bias_V']**2,places=14)
        self.assertIn('not junction transport/leakage',metadata['model'])

    def test_ideal_insulator_is_open_circuit_without_conductivity_floor(self):
        device,library=resistor_device()
        library[-1]['properties']['conductivity_S_m']=0.
        summary=self.solved(device,library)
        rows,metadata=ohmic_iv(summary)
        self.assertEqual([row['current_A'] for row in rows],[0.,0.,0.])
        self.assertEqual(metadata['connected_conducting_cells'],0)
        self.assertEqual(metadata['zero_conductivity_cells'],4*4*12)

    def test_explicit_conductivity_overrides_nonzero_carriers_including_zero(self):
        device,library=resistor_device()
        silicon=copy.deepcopy(next(row for row in library if row['id']=='silicon'))
        silicon.update(id='user_semiconductor',name='Measured conductivity semiconductor',model='constant')
        device['layers'][0]['material_id']=silicon['id']
        library.append(silicon)
        carrier_data=dict(electrons_cm3=np.full((4,4,12),1e18),holes_cm3=np.full((4,4,12),2e17))
        derived=_conductivity(build_mesh(device,library),carrier_data)
        self.assertTrue(np.all(derived>1000.))
        silicon['properties']['conductivity_S_m']=2.
        fixed=_conductivity(build_mesh(device,library),carrier_data)
        np.testing.assert_array_equal(fixed,np.full((4,4,12),2.))
        silicon['properties']['conductivity_S_m']=0.
        opened=_conductivity(build_mesh(device,library),carrier_data)
        np.testing.assert_array_equal(opened,np.zeros((4,4,12)))

    def test_insulating_middle_layer_disconnects_electrodes(self):
        device,library=resistor_device()
        original=device['layers'][0]
        device['layers']=[dict(original,id='top',thickness_um=.1),
                          dict(original,id='gap',material_id='air',thickness_um=.1),
                          dict(original,id='bottom',thickness_um=.1)]
        device['contacts'][0]['layer_id']='bottom';device['contacts'][1]['layer_id']='top'
        summary=self.solved(device,library)
        rows,metadata=ohmic_iv(summary)
        np.testing.assert_allclose([row['current_A'] for row in rows],0.,atol=1e-16)
        self.assertEqual(metadata['zero_conductivity_cells'],4*4*12)

    def test_extreme_conductivity_contrast_preserves_tiny_series_current(self):
        device,library=resistor_device()
        library[-1]['properties']['conductivity_S_m']=1e6
        library.append(dict(library[-1],id='low',name='Low conductor',properties=dict(epsilon_r=4.,conductivity_S_m=1e-12)))
        original=device['layers'][0]
        device['layers']=[dict(original,id='top',thickness_um=.15),
                          dict(original,id='bottom',material_id='low',thickness_um=.15)]
        device['contacts'][0]['layer_id']='bottom';device['contacts'][1]['layer_id']='top'
        summary=self.solved(device,library)
        rows,metadata=ohmic_iv(summary)
        conductance=4e-12/(.15e-6/1e6+.15e-6/1e-12)
        for row in rows:
            self.assertAlmostEqual(row['current_A']/conductance,row['terminal_voltage_V'],places=8)
        self.assertTrue(all(check['relative_current_balance']<1e-10 for check in metadata['checks']))

    def test_real_silicon_reference_without_override_uses_unchanged_carrier_mobility(self):
        device=default_device()
        device['layers']=[dict(id='p',name='P silicon',material_id='silicon',thickness_um=.15,
            donor_cm3=0.,acceptor_cm3=1e17,enabled=True),
            dict(id='n',name='N silicon',material_id='silicon',thickness_um=.15,
                 donor_cm3=1e17,acceptor_cm3=0.,enabled=True)]
        device['mesh'].update(nx=4,ny=4,nz_per_layer=8)
        device['contacts'][0]['layer_id']='n';device['contacts'][1]['layer_id']='p'
        library=builtin_materials()
        summary=solve(dict(device=device,material_library=library,biases_V=[0.,-.3,-.6]),self.directory.name)
        mesh=build_mesh(device,library)
        material=next(row for row in library if row['id']=='silicon')
        self.assertNotIn('conductivity_S_m',material['properties'])
        props=material['properties']
        with np.load(summary['results'][0]['volume_npz'],allow_pickle=False) as data:
            sigma=_conductivity(mesh,data)
            expected=1.602176634e-19*100.*(data['electrons_cm3']*props['electron_mobility_cm2_Vs']
                +data['holes_cm3']*props['hole_mobility_cm2_Vs'])
            np.testing.assert_allclose(sigma,expected,rtol=1e-14)
        # The independently reconstructed series resistance uses the actual
        # nonuniform semiconductor reference conductivity in every z cell.
        conductance=4e-12/np.sum(mesh['widths'][2]/sigma[0,0,:])
        rows,metadata=ohmic_iv(summary)
        for row in rows:
            self.assertAlmostEqual(row['current_A']/conductance,row['terminal_voltage_V'],places=9)
        self.assertEqual(metadata['zero_conductivity_cells'],0)

    def test_unanchored_conductor_is_counted_and_not_given_fake_current(self):
        device,library=resistor_device()
        original=device['layers'][0]
        device['layers']=[dict(original,id='top',thickness_um=.1),
                          dict(original,id='gap',material_id='air',thickness_um=.1),
                          dict(original,id='floating',thickness_um=.1)]
        # Both contacts touch the top layer's sides; the bottom conductor floats.
        for contact,surface in zip(device['contacts'],('side_x_min','side_x_max')):
            contact.update(layer_id='top',surface=surface)
        summary=self.solved(device,library)
        rows,metadata=ohmic_iv(summary)
        self.assertEqual(metadata['unanchored_conducting_cells'],4*4*12)
        self.assertTrue(all(np.isfinite(row['current_A']) for row in rows))

    def test_study_outputs_portable_metadata_and_csv(self):
        summary=self.solved()
        info=execute_studies(summary,dict(iv_enabled=True,cv_enabled=True),self.directory.name)
        self.assertTrue(Path(info['iv_csv']).is_file())
        self.assertTrue(Path(info['cv_csv']).is_file())
        saved=json.loads(Path(info['summary_json']).read_text())
        self.assertIn('Ohmic conductivity estimate',saved['studies']['iv']['model'])
        self.assertIn('warnings',saved['studies']['cv'])

    def test_cv_requires_three_unique_actual_terminal_voltages(self):
        summary=self.solved(biases=[0.,-1.])
        with self.assertRaisesRegex(ValueError,'at least three'):terminal_cv(summary)
        summary['results'].append(copy.deepcopy(summary['results'][0]))
        with self.assertRaisesRegex(ValueError,'distinct'):terminal_cv(summary)

    def test_measured_csv_is_validated_and_preserved(self):
        path=Path(self.directory.name)/'measured.csv'
        path.write_text('bias_V,current_A\n0,0\n-1,-0.0001\n',encoding='utf-8')
        rows=read_measured_csv(path,'iv')
        self.assertEqual(rows[0],dict(bias_V=-1.,current_A=-.0001))
        summary=self.solved()
        info=execute_studies(summary,dict(measured_iv_path=str(path)),self.directory.name)
        self.assertEqual(info['measured']['iv']['samples'],2)
        path.write_text('bias_V,current_A\n0,nan\n-1,1\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'finite'):read_measured_csv(path,'iv')
        path.write_text('bias_V,capacitance_F\n0,1e-12\n0,2e-12\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'unique'):read_measured_csv(path,'cv')

    def test_validation_and_cancellation(self):
        self.assertFalse(validate_studies()['iv_enabled'])
        with self.assertRaises(ValueError):validate_studies(dict(iv_enabled='true'))
        with self.assertRaises(InterruptedError):
            execute_studies(self.solved(),dict(iv_enabled=True),self.directory.name,cancelled=lambda:True)


if __name__=='__main__':unittest.main()
