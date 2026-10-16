import unittest
import numpy as np
from electrical_temperature import apply_material_temperature,validate_feedback


class TemperatureLawTests(unittest.TestCase):
    def model(self):
        return dict(Nc_exponent=1.5,Nv_exponent=1.5,electron_mobility_exponent=-1.,hole_mobility_exponent=-2.,
            minimum_temperature_K=250.,maximum_temperature_K=500.,source='Synthetic temperature laws',
            varshni=dict(alpha_eV_K=.0005,beta_K=200.,conduction_partition=.4))

    def test_reference_exact_and_varshni_partition(self):
        properties=dict(Nc_cm3=1e18,Nv_cm3=2e18,affinity_eV=4.,bandgap_eV=1.5,electron_mobility_cm2_Vs=100.,hole_mobility_cm2_Vs=20.)
        result=apply_material_temperature(properties,np.array([300.,400.]),300.,self.model())
        for key,value in properties.items():self.assertEqual(result[key][0],value)
        self.assertAlmostEqual(result['electron_mobility_cm2_Vs'][1],75.)
        self.assertAlmostEqual(result['Nc_cm3'][1]/properties['Nc_cm3'],(4/3)**1.5)
        gap_shift=-.0005*(400**2/600-300**2/500)
        self.assertAlmostEqual(result['bandgap_eV'][1]-1.5,gap_shift)
        self.assertAlmostEqual(result['affinity_eV'][1]-4.,-.4*gap_shift)

    def test_missing_material_and_outside_range_reject(self):
        with self.assertRaises(ValueError):validate_feedback({'temperature_models':{}},['test'],300.)
        props=dict(Nc_cm3=1.,Nv_cm3=1.,affinity_eV=1.,bandgap_eV=1.,electron_mobility_cm2_Vs=1.,hole_mobility_cm2_Vs=1.)
        with self.assertRaises(ValueError):apply_material_temperature(props,[600.],300.,self.model())


if __name__=='__main__':unittest.main()
