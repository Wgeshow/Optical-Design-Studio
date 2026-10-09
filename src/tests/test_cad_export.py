import math
import tempfile
from pathlib import Path
from tests.test_comsol_export import ComsolExportTests
from export_geometry import ExportOptions, array_centers
from cad_export import cad_library, cad_parts, export_cad_step, shape_metrics, read_step_metrics
from comsol_export import comsol_java


class CadExportTests(ComsolExportTests):
    def test_array_geometry_volume_and_step_roundtrip_units(self):
        patterns = self.patterns.iloc[:1].copy()
        options = ExportOptions(2, 3, 'mm', False)
        parts = cad_parts(self.materials, self.layers, patterns, self.settings, options)
        bounds = shape_metrics([part[2] for part in parts])
        self.assertAlmostEqual(bounds['x_um'], 1.54, places=6)
        self.assertAlmostEqual(bounds['y_um'], 2.4, places=6)
        self.assertAlmostEqual(bounds['z_um'], .35, places=6)
        expected = 1.54*2.4*.35 - 6*math.pi*.1**2*.25
        self.assertAlmostEqual(bounds['volume_um3'], expected, places=6)
        for unit in ('nm', 'um', 'mm', 'm'):
            with self.subTest(unit=unit), tempfile.TemporaryDirectory() as folder:
                path = export_cad_step(Path(folder)/'device.step', self.materials, self.layers,
                    patterns, self.settings, ExportOptions(2, 3, unit, False))
                imported = read_step_metrics(path)
                self.assertAlmostEqual(imported['x_um'], 1.54, places=6)
                self.assertAlmostEqual(imported['y_um'], 2.4, places=6)
                self.assertAlmostEqual(imported['volume_um3'], expected, places=6)

    def test_even_array_centers_and_comsol_units(self):
        region = self.patterns.iloc[0].to_dict()
        options = ExportOptions(2, 3, 'nm', False)
        centers = array_centers(region, .77, .8, options)
        self.assertEqual(len(centers), 6)
        self.assertEqual(sorted(set(round(x, 6) for x,y in centers)), [-.385, .385])
        script = comsol_java(self.materials, self.layers, self.patterns, self.settings, options=options)
        self.assertIn('lengthUnit("nm")', script)
        self.assertIn('"cells_x", "2"', script)
        self.assertIn('"cells_y", "3"', script)
        self.assertIn('"quickz", "0.25[um]"', script)
        self.assertNotIn('"blk_top", "Block"', script)

    def test_reject_invalid_counts(self):
        for count in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                ExportOptions(count, 1).validate()

    def test_one_by_one_is_exactly_one_unit_cell(self):
        options = ExportOptions(1, 1, 'um', False)
        patterns = self.patterns.iloc[:1].copy()
        patterns.loc[patterns.index[0], 'Shape'] = 'ellipse'
        patterns.loc[patterns.index[0], 'SizeY_um'] = .05
        patterns.loc[patterns.index[0], 'Angle_deg'] = 31
        parts = cad_parts(self.materials, self.layers, patterns, self.settings, options)
        shape = shape_metrics([p[2] for p in parts])
        self.assertAlmostEqual(shape['x_um'], .77, places=6)
        self.assertAlmostEqual(shape['y_um'], .8, places=6)
        self.assertAlmostEqual(shape['volume_um3'], .77*.8*.35-math.pi*.1*.05*.25, places=6)
        self.assertEqual(len(array_centers(patterns.iloc[0].to_dict(), .77, .8, options)), 1)
