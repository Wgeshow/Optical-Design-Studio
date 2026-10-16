import copy
import importlib.util
import tempfile
import unittest
from unittest.mock import patch
import json
from pathlib import Path
import numpy as np

from advanced_transport import prepare, execute
from tests.test_electrical_transport import planar_options


def conductor_inputs():
    options = planar_options('ito', 1e20, (0., .0001), count=6)
    for layer in options['device']['layers']:
        layer.update(donor_cm3=1e20, acceptor_cm3=0.)
    next(row for row in options['material_library'] if row['id'] == 'ito')['properties']['bulk_electron_cm3'] = 0.
    settings = dict(parameter_source='Synthetic finite-contact test', biases_V=[0., .0001], swept_contact_id='contact_p',
        unipolar_conductors={'ito': 'Electron-only conductor approximation'},
        contacts={key: dict(electron_resistivity_ohm_cm2=1e-5, hole_resistivity_ohm_cm2=0., source='Synthetic resistance')
                  for key in ('contact_n', 'contact_p')})
    return dict(device=options['device'], electrical_materials=options['material_library']), settings


class AdvancedPreflightTests(unittest.TestCase):
    def test_conductors_are_explicit_and_inputs_are_preserved(self):
        project, settings = conductor_inputs()
        original = copy.deepcopy(project)
        result = prepare(project, settings)
        self.assertEqual(result['advanced']['unipolar_conductors'], settings['unipolar_conductors'])
        self.assertEqual(original, project)
        del settings['unipolar_conductors']
        with self.assertRaisesRegex(ValueError, 'Explicitly enable'):
            prepare(project, settings)

    def test_wrong_contact_and_unrecognized_models_are_rejected(self):
        project, settings = conductor_inputs()
        settings['contacts']['missing'] = settings['contacts']['contact_p']
        with self.assertRaises(ValueError):
            prepare(project, settings)
        del settings['contacts']['missing']
        settings['thermal'] = {'source': 'automatic'}
        with self.assertRaises(ValueError):
            prepare(project, settings)

    def test_unused_or_blocked_interface_laws_are_rejected(self):
        project, settings = conductor_inputs()
        settings['interfaces'] = [dict(materials=['ito','silicon'],electron_resistivity_ohm_cm2=1e-5,hole_resistivity_ohm_cm2=0.,source='Explicit test')]
        with self.assertRaisesRegex(ValueError, 'occupied'):
            prepare(project, settings)
        material = copy.deepcopy(next(row for row in project['electrical_materials'] if row['id'] == 'ito'))
        for key in ('middle','last'):
            project['electrical_materials'].append(dict(material,id=key,name=key,aliases=[]))
            settings['unipolar_conductors'][key]='Synthetic material identity'
        project['device']['layers'][1]['material_id']='last'
        project['device']['layers'].insert(1,dict(project['device']['layers'][0],id='middle_layer',material_id='middle'))
        settings['interfaces'][0]['materials']=['ito','last']
        with self.assertRaisesRegex(ValueError, 'share no resolved mesh face'):
            prepare(project, settings)
        settings['interfaces'][0].update(materials=['ito','middle'],hole_resistivity_ohm_cm2=1e-5)
        with self.assertRaisesRegex(ValueError, 'no hole channel'):
            prepare(project, settings)

    def test_out_of_gap_trap_and_unoccupied_recombination_are_rejected(self):
        options=planar_options('silicon',count=4)
        project=dict(device=options['device'],electrical_materials=options['material_library'])
        settings=dict(parameter_source='Synthetic validation',biases_V=[0.],swept_contact_id='contact_p',
            recombination={'silicon':dict(model='fd_detailed_balance_proxy',tau_n_s=1e-7,tau_p_s=1e-7,trap_energy_eV=2.,source='Explicit test')})
        with self.assertRaisesRegex(ValueError, 'outside this material band gap'):
            prepare(project,settings)
        settings['recombination']['silicon']['trap_energy_eV']=0.
        settings['recombination']['gaas']=settings['recombination'].pop('silicon')
        with self.assertRaisesRegex(ValueError, 'occupied semiconductor'):
            prepare(project,settings)


@unittest.skipUnless(importlib.util.find_spec('devsim') is not None, 'optional DEVSIM is not installed')
class AdvancedNativeTests(unittest.TestCase):
    def test_failed_optional_optics_preserves_completed_electrical_state(self):
        options=planar_options('silicon',count=4)
        project=dict(device=options['device'],electrical_materials=options['material_library'])
        settings=dict(parameter_source='Synthetic checkpoint validation',biases_V=[0.],swept_contact_id='contact_p',
            high_field_optics=dict(wavelengths_nm=[1150.],materials={'silicon':dict(electron_mass_ratio=.2,hole_mass_ratios=[.5],
                absorption_prefactor_cm1_sqrt_eV=1000.,reference_gap_eV=1.12,source='Explicit numerical test; not silicon optical calibration')}))
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            with patch('high_field_optics.response',side_effect=RuntimeError('Synthetic optical-stage failure')):
                with self.assertRaisesRegex(RuntimeError,'Synthetic optical-stage failure'):
                    execute(prepare(project,settings),folder)
            saved=json.loads((Path(folder)/'advanced_transport_summary.json').read_text())
            self.assertEqual(saved['status'],'partial')
            self.assertEqual(saved['results'][0]['high_field_optics_status'],'failed')
            with np.load(Path(folder)/saved['results'][0]['volume_npz']) as data:
                self.assertTrue(np.isfinite(data['potential_V']).all())
                metadata=json.loads(data['array_axes'].item())
                self.assertEqual(metadata['potential_V']['unit'],'V')
                np.testing.assert_allclose(data['z_um'],data['z']*1e6)

    def test_explicit_material_interface_adds_physical_series_resistance(self):
        project, settings = conductor_inputs()
        material = copy.deepcopy(next(row for row in project['electrical_materials'] if row['id'] == 'ito'))
        material.update(id='second_conductor',name='Second conductor',aliases=[])
        project['electrical_materials'].append(material)
        project['device']['layers'][1]['material_id']='second_conductor'
        settings['unipolar_conductors']['second_conductor']='Identical material properties, separate interface identity'
        settings['interfaces']=[dict(materials=['ito','second_conductor'],electron_resistivity_ohm_cm2=1e-5,hole_resistivity_ohm_cm2=0.,source='Synthetic interface')]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            result=execute(prepare(project,settings),folder)
            expected=.0001/(2e-4/(1.602176634e-19*30*1e20)+3e-5)*4e-8
            actual=abs(result['results'][-1]['checks']['terminal_current_A']['contact_p'])
            self.assertAlmostEqual(actual/expected,1.,places=8)

    def test_unipolar_bulk_and_contact_resistances_and_heat_conserve(self):
        project, settings = conductor_inputs()
        settings['thermal'] = dict(source='electrochemical_dissipation',
            conductivity={'ito': dict(value_W_mK=4., source='Synthetic conductivity')},
            boundaries={'z_max': dict(kind='fixed_temperature', temperature_K=300.)})
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            result = execute(prepare(project, settings), folder)
            expected = .0001/(2e-4/(1.602176634e-19*30*1e20)+2e-5)*4e-8
            checks = result['results'][-1]['checks']
            actual = abs(checks['terminal_current_A']['contact_p'])
            self.assertAlmostEqual(actual/expected, 1., places=8)
            self.assertLess(checks['electrical_power_balance_relative'], 1e-8)
            thermal = result['results'][-1]['thermal_checks']
            self.assertLess(thermal['relative_power_balance'], 1e-8)
            self.assertAlmostEqual(thermal['input_power_W']/(actual*.0001), 1., places=8)
            with np.load(Path(folder)/'advanced_state_0001.npz') as data:
                self.assertTrue(np.all(data['holes_cm3'] == 0.))

    def test_recombination_is_zero_at_equilibrium_and_conserves_under_bias(self):
        options = planar_options('silicon', 1e16, (0., .1), count=12)
        settings = dict(parameter_source='Synthetic recombination test', biases_V=[0., .1], swept_contact_id='contact_p',
            recombination={'silicon': dict(model='fd_detailed_balance_proxy', tau_n_s=1e-7, tau_p_s=2e-7,
                B_cm3_s=1e-10, Cn_cm6_s=1e-30, Cp_cm6_s=1e-30, surface_velocity_cm_s=100., source='Synthetic rates')})
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            result = execute(prepare(dict(device=options['device'], electrical_materials=options['material_library']), settings), folder)
            with np.load(Path(folder)/'advanced_state_0000.npz') as data:
                self.assertEqual(np.max(np.abs(data['srh_recombination_cm3_s'])), 0.)
            checks = result['results'][-1]['checks']
            self.assertLess(checks['relative_current_balance'], 1e-5)
            self.assertLess(checks['electrical_power_balance_relative'], 1e-5)


if __name__ == '__main__':
    unittest.main()
