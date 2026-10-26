"""Units, alloy branches, editable reference values and portable-library contracts."""
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest

from electrical_material_library import (
    KB_EV_K, Q_C, builtin_materials, conductivity_S_m, evaluate_material,
    export_materials, import_materials, lookup_material, merge_materials,
    new_material, validate_materials,
)


class ElectricalMaterialLibraryTests(unittest.TestCase):
    def test_requested_presets_are_complete_and_independent(self):
        library = builtin_materials()
        self.assertEqual([material['id'] for material in library], ['gaas','ito','algaas','silicon','air'])
        library[0]['properties']['epsilon_r'] = 100
        library[0]['sources'][0]['title'] = 'changed'
        next_library = builtin_materials()
        self.assertEqual(next_library[0]['properties']['epsilon_r'], 12.9)
        self.assertIn('Ioffe', next_library[0]['sources'][0]['title'])
        self.assertEqual(lookup_material(next_library, 'Si')['id'], 'silicon')
        self.assertEqual(lookup_material(next_library, 'Air')['kind'], 'dielectric')
        for material in next_library:
            self.assertTrue(material['sources'])
            self.assertTrue(material['notes'])

    def test_invalid_records_reject_without_mutation(self):
        valid = builtin_materials()
        before = deepcopy(valid)
        invalid = deepcopy(valid)
        invalid[0]['properties']['epsilon_r'] = 0
        with self.assertRaisesRegex(ValueError, 'greater than zero'):
            validate_materials(invalid)
        self.assertEqual(valid, before)
        for key, value in [('Nc_cm3', -1), ('electron_mobility_cm2_Vs', 'nan'), ('bandgap_eV', True), ('bulk_electron_cm3', -1)]:
            invalid = deepcopy(valid)
            invalid[0]['properties'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_materials(invalid)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            validate_materials([valid[0],valid[0]])
        invalid = deepcopy(valid)
        del invalid[0]['properties']['affinity_eV']
        with self.assertRaisesRegex(ValueError, 'affinity_eV'):
            validate_materials(invalid)

    def test_alloy_uses_indirect_gap_and_distinct_dos_mass(self):
        original = lookup_material(builtin_materials(), 'algaas')
        props = evaluate_material(original)['properties']
        self.assertAlmostEqual(props['bandgap_eV'], 1.99825)
        self.assertEqual(props['electron_mass_ratio'], .26)
        self.assertAlmostEqual(props['electron_dos_mass_ratio'], .78)
        self.assertAlmostEqual(props['Nc_cm3']/2.5e19, .78**1.5)
        self.assertAlmostEqual(props['affinity_eV'], 3.57)
        low = evaluate_material(original, al_fraction=.3)
        self.assertEqual(low['band_type'], 'direct')
        self.assertAlmostEqual(low['properties']['bandgap_eV'], 1.424+1.247*.3)
        self.assertAlmostEqual(low['properties']['electron_mass_ratio'], .063+.083*.3)
        self.assertEqual(original['al_fraction'], .5)
        for x in (-.1, 1.1, 'nan'):
            with self.subTest(x=x), self.assertRaises(ValueError):
                evaluate_material(original, al_fraction=x)

    def test_temperature_scaling_and_custom_property_override_are_consistent(self):
        original = lookup_material(builtin_materials(), 'gaas')
        warmer = evaluate_material(original, 350.)
        self.assertAlmostEqual(warmer['properties']['Nc_cm3']/original['properties']['Nc_cm3'], (350/300)**1.5)
        self.assertLess(warmer['properties']['bandgap_eV'], original['properties']['bandgap_eV'])
        self.assertGreater(warmer['properties']['intrinsic_cm3'], original['properties']['intrinsic_cm3'])
        manual = deepcopy(original)
        manual['properties'].update(epsilon_r=15., bandgap_eV=1.5, Nc_cm3=1e18)
        edited = evaluate_material(manual, 350.)
        self.assertEqual(edited['properties']['epsilon_r'], 15.)
        self.assertEqual(edited['properties']['bandgap_eV'], 1.5)
        self.assertEqual(edited['properties']['Nc_cm3'], 1e18)
        expected = math.sqrt(edited['properties']['Nc_cm3']*edited['properties']['Nv_cm3'])*math.exp(-1.5/(2*KB_EV_K*350))
        self.assertAlmostEqual(edited['properties']['intrinsic_cm3']/expected, 1.)
        # Re-evaluation must be stable after the computed temperature is persisted.
        self.assertEqual(evaluate_material(edited), edited)

    def test_conductivity_conversion_and_ito_assumptions(self):
        ito = lookup_material(builtin_materials(), 'ito')
        self.assertAlmostEqual(conductivity_S_m(ito), Q_C*100*8e20*30)
        self.assertAlmostEqual(conductivity_S_m(ito), 384522.39216)
        assumed = [source for source in ito['sources'] if source['kind'] == 'assumption']
        self.assertTrue(assumed)
        for key in ('bulk_electron_cm3','electron_mobility_cm2_Vs','epsilon_r','affinity_eV','electron_mass_ratio'):
            self.assertIn(key, assumed[0]['properties'])
        manual = new_material(template=ito)
        manual['properties']['conductivity_S_m'] = 1234.
        self.assertEqual(conductivity_S_m(manual), 1234.)
        self.assertAlmostEqual(conductivity_S_m(manual, 1e18, 0), Q_C*100*1e18*30)
        self.assertEqual(conductivity_S_m(lookup_material(builtin_materials(), 'air')), 0.)

    def test_custom_json_roundtrip_and_merge_preserve_stable_ids(self):
        library = builtin_materials()
        custom = new_material('Measured sample', library[0])
        custom.update(notes='300 K measured film', optical_material_name='MeasuredSampleOptics',
                      sources=[{'title':'Sample record','url':'https://example.org/sample','kind':'measurement'}])
        custom['properties'].update(optical_n=3.1, optical_k=.05)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'library.json'
            export_materials(path, library+[custom])
            self.assertEqual(import_materials(path), validate_materials(library+[custom]))
            payload = json.loads(path.read_text(encoding='utf-8'))
            payload['schema_version'] = 999
            path.write_text(json.dumps(payload), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'schema version'):
                import_materials(path)
            path.write_text('{"id":"x","properties":{"epsilon_r":NaN}}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Non-finite'):
                import_materials(path)
        modified = deepcopy(library[0])
        modified['name'] = 'My GaAs'
        merged = merge_materials(library, [modified, custom])
        self.assertEqual(merged[0]['name'], 'My GaAs')
        self.assertEqual(merged[-1]['id'], custom['id'])
        self.assertEqual(library[0]['name'], 'GaAs')
        self.assertEqual(custom['model'], 'constant')


if __name__ == '__main__':
    unittest.main()
