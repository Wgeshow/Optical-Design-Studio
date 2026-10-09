"""COMSOL script export preserves the unit-cell model without needing COMSOL."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from comsol_export import comsol_java, export_comsol_java
from model import LAYER_COLS, MAT_COLS, PAT_COLS


class ComsolExportTests(unittest.TestCase):
    def setUp(self):
        self.materials = pd.DataFrame([
            ['Air', 'constant_nk', 1., 0., '', 'nm'],
            ['GaAs', 'constant_nk', 3.4, .1, '', 'nm'],
            ['Gold', 'constant_eps', -115.13, 11.259, '', 'nm'],
        ], columns=MAT_COLS)
        self.layers = pd.DataFrame([
            ['Top', 0., 'Air'], ['Slab', .25, 'GaAs'], ['Metal', .1, 'Gold'], ['Bottom', 0., 'Air'],
        ], columns=LAYER_COLS)
        self.patterns = pd.DataFrame([
            ['circle', 'Slab', 'Air', 0., 0., .1, 0., 0.],
            ['rectangle', 'Metal', 'Air', .02, -.01, .12, .08, 37.],
        ], columns=PAT_COLS)
        self.settings = {'ax_um': .77, 'ay_um': .8, 'fixed_wl_nm': 1550}

    def test_script_has_parametric_stack_patterns_selections_and_materials(self):
        script = comsol_java(self.materials, self.layers, self.patterns, self.settings)
        self.assertIn('model.param().set("ax", "0.77[um]"', script)
        self.assertIn('"incident_padding"', script)
        self.assertIn('"exit_padding"', script)
        self.assertIn('geom().create("geom1", 3)', script)
        self.assertIn('"Ellipse"', script)
        self.assertIn('"Rectangle"', script)
        self.assertIn('"Difference"', script)
        self.assertIn('"Intersection"', script)
        self.assertIn('"keepsubtract", true', script)
        self.assertIn('"sel_air", "CumulativeSelection"', script)
        self.assertIn('selection().named("geom1_sel_gaas_dom")', script)
        self.assertIn('11.55-0.68*i', script)
        self.assertIn('-115.13-11.259*i', script)
        self.assertIn('"quickz", "0[um]"', script)
        self.assertIn('"quickz", "0.25[um]"', script)
        # COMSOL cumulative geometry selections do not support show(true) in
        # all supported versions. Extrude must explicitly select its work plane.
        self.assertNotIn('.show(true)', script)
        self.assertIn('feature("ext_1_1").selection("input").set(new String[]{"wp_1_1"})', script)

    def test_file_export_adds_java_extension_and_validates_lattice(self):
        with tempfile.TemporaryDirectory() as folder:
            result = export_comsol_java(Path(folder) / 'OpticalDevice', self.materials, self.layers,
                                        self.patterns, self.settings)
            self.assertEqual(result.suffix, '.java')
            self.assertIn('public class OpticalDevice', result.read_text(encoding='utf8'))
            self.assertIn('Compiled Model File for Java', result.with_suffix('.README.txt').read_text(encoding='utf8'))
            self.assertIn('& $compiler "$modelName.java"', result.with_suffix('.build.ps1').read_text(encoding='utf8'))
            linux_helper = result.with_suffix('.build.sh').read_text(encoding='utf8')
            self.assertIn('"$comsol_command" compile -verbose "$model.java"', linux_helper)
            self.assertIn("'--build-mph'", linux_helper)
            self.assertNotIn('model.save(', result.read_text(encoding='utf8'))
        with self.assertRaisesRegex(ValueError, 'Lattice periods'):
            comsol_java(self.materials, self.layers, self.patterns, {'ax_um': 0, 'ay_um': 1})

    def test_boundary_crossing_region_is_wrapped_and_clipped_to_unit_cell(self):
        patterns = self.patterns.iloc[:1].copy()
        patterns.loc[patterns.index[0], 'CenterX_um'] = .36
        patterns.loc[patterns.index[0], 'SizeX_um'] = .1
        script = comsol_java(self.materials, self.layers, patterns, self.settings)
        self.assertIn('"wp_1_2", "WorkPlane"', script)
        self.assertEqual(script.count('"Intersection"'), 2)
        self.assertIn('"clip_1_1", "Block"', script)


if __name__ == '__main__':
    unittest.main()
