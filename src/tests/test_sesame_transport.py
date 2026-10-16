import copy
import unittest
from unittest.mock import patch
import numpy as np

import sesame_transport as transport
from research_physics_runtime import validate_runtime


def configuration():
    material = dict(Nc=2.8e19, Nv=1.04e19, Eg=1.12, epsilon=11.7, mu_e=100., mu_h=50.,
                    tau_e=1e-6, tau_h=1e-6, affinity=4.05, Et=0.)
    contact = dict(kind='Ohmic', electron_velocity_cm_s=1e10, hole_velocity_cm_s=1e10)
    return dict(dimension=1, x_nodes_um=np.linspace(0, 1, 21).tolist(), materials={'semiconductor': material},
        regions=[dict(id='bulk', material='semiconductor', x_range_um=[0, 1], donors_cm3=1e15)],
        contacts=dict(left=contact, right=copy.deepcopy(contact)), voltages_V=[0., .01], temperature_K=300.)


class SesameInputTests(unittest.TestCase):
    def test_portable_full_material_and_runtime(self):
        result = transport.prepare({}, configuration())
        self.assertEqual(result['materials']['semiconductor']['B'], 0.)
        self.assertEqual(result['worker_engine'], 'sesame_transport')
        self.assertEqual(result['regions'][0]['donors_cm3'], 1e15)

    def test_interfaces_have_deterministic_ownership(self):
        cfg = configuration()
        cfg['regions'] = [dict(id='left', material='semiconductor', x_range_um=[0, .5]),
                          dict(id='right', material='semiconductor', x_range_um=[.5, 1])]
        result = transport.prepare({}, cfg)
        self.assertEqual(transport.region_labels(result)[0, 10], 1)

    def test_reject_holes_overlap_and_unresolved_boundaries(self):
        for bounds in ([.55, 1], [.45, 1], [.501, 1]):
            cfg = configuration()
            cfg['regions'] = [dict(id='a', material='semiconductor', x_range_um=[0, .5]),
                              dict(id='b', material='semiconductor', x_range_um=bounds)]
            with self.assertRaises(ValueError):
                transport.prepare({}, cfg)

    def test_defects_reference_and_no_unrecognized_physics(self):
        cfg = configuration()
        cfg['defects'] = [dict(id='trap', location_um=.5, density_cm2=1e11, sigma_e_cm2=1e-15,
                              sigma_h_cm2=1e-15, energy_eV=.1, transition=[1, 0])]
        result = transport.prepare({}, cfg)
        self.assertEqual(result['defects'][0]['energy_eV'], .1)
        cfg['tunnelling'] = True
        with self.assertRaises(ValueError):
            transport.prepare({}, cfg)

    def test_materials_and_contacts_never_silently_default(self):
        cfg = configuration()
        del cfg['materials']['semiconductor']['affinity']
        with self.assertRaises(ValueError):
            transport.prepare({}, cfg)
        cfg = configuration()
        cfg['contacts']['left']['kind'] = 'Schottky'
        with self.assertRaises(ValueError):
            transport.prepare({}, cfg)

    def test_packaged_application_needs_real_python(self):
        with patch('research_physics_runtime.sys.frozen', True, create=True):
            with self.assertRaises(ValueError):
                validate_runtime()
            self.assertEqual(validate_runtime({'executable': 'python'})['executable'], 'python')


if __name__ == '__main__':
    unittest.main()
