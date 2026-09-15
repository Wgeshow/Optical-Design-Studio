"""3D material semantics and the 2D/3D shared-state boundary."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import numpy as np
from PyQt6.QtWidgets import QApplication
from qt_structure import StructurePage
from qt_structure_3d import geometry_figure_3d, material_grid
from structure_preview import normalize_region
from tests.test_qt_structure import MemoryStore


class Structure3DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_air_hole_and_later_material_overlay(self):
        layer = {'name': 'Device', 'material': 'GaAs'}
        hole = normalize_region(dict(Shape='circle', Layer='Device', Material='Air',
                                     SizeX_um=.2, CenterX_um=0, CenterY_um=0))
        _, _, grid = material_grid(layer, [hole], 1, 1, 1, 40)
        self.assertEqual(grid[20,20], 'Air')
        self.assertEqual(grid[0,0], 'GaAs')
        fill = dict(hole, material='Au', sx=.1)
        _, _, grid = material_grid(layer, [hole,fill], 1, 1, 1, 40)
        self.assertEqual(grid[20,20], 'Au')
        self.assertGreater(np.count_nonzero(grid == 'Air'), 0)

    def test_surface_budget_and_exact_layer_depths(self):
        store = MemoryStore()
        fig = geometry_figure_3d(store.layers, store.patterns, 'PCS1', .77, .77, 7)
        data = fig._s4_geometry
        self.assertLess(data['face_count'], 90000)
        self.assertAlmostEqual(data['total_um'], .7)
        self.assertAlmostEqual(data['stack'][1]['z1'], .25)
        self.assertIn('∞', ''.join(text.get_text() for text in data['three_d'].texts))

    def test_toggle_preserves_structure_and_restores_exact_section(self):
        store = MemoryStore()
        before = store.layers.copy(deep=True)
        page = StructurePage(store)
        page.view_mode.setCurrentIndex(1)
        self.assertIn('three_d', page.plot.figure._s4_geometry)
        axis = page.plot.figure._s4_geometry['three_d']
        axis.view_init(40, 60)
        page.draw_preview()
        self.assertEqual(page.plot.figure._s4_geometry['three_d'].elev, 40)
        page.draw_preview(reset=True)
        self.assertEqual(page.plot.figure._s4_geometry['three_d'].elev, 25)
        page.view_mode.setCurrentIndex(0)
        self.assertIn('section', page.plot.figure._s4_geometry)
        self.assertTrue(store.layers.equals(before))
        page.close()
        page.deleteLater()
        self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
