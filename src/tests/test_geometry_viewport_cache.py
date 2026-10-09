"""Geometry caching retains real apertures, editing and mouse interaction."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

import qt_device_builder
from qt_device_builder import GeometryViewport
from tests.test_qt_structure import MemoryStore


class GeometryViewportCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = MemoryStore()
        self.view = GeometryViewport()
        self.view.resize(680, 640)
        self.view.set_model(self.store, 'PCS1', 3)
        self.view.show()
        self.app.processEvents()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    def test_orbit_and_appearance_reuse_model_geometry(self):
        original_layers = self.store.layers.copy(deep=True)
        original_patterns = self.store.patterns.copy(deep=True)
        with patch('qt_device_builder.region_polygon', wraps=qt_device_builder.region_polygon) as polygon:
            self.view.cells = 7
            self.view.grab()
            initial = polygon.call_count
            self.assertGreaterEqual(initial, 98)
            for angle in (-2.4, -.2, .7, 2.5):
                self.view.angle = angle
                self.view.grab()
            self.view.set_model(self.store, 'PCS2', 7)
            self.view.layer_colors = {'PCS1': '#00ff00'}
            self.view.show_edges = True
            self.view.hidden_layers = {'PCS2'}
            self.view.grab()
            self.assertEqual(polygon.call_count, initial)
            self.view.cells = 3
            self.view.grab()
            self.assertEqual(polygon.call_count, initial)
        self.assertTrue(self.store.layers.equals(original_layers))
        self.assertTrue(self.store.patterns.equals(original_patterns))

    def test_pattern_lattice_and_hole_toggles_invalidate_the_right_cache(self):
        original_surface = self.view._stack_geometry()[2][1][4]
        self.store.patterns.loc[0, 'SizeX_um'] = .15
        self.view.set_model(self.store, 'PCS1', 3)
        changed_surface = self.view._stack_geometry()[2][1][4]
        self.assertNotEqual(original_surface, changed_surface)
        self.store.settings['ax_um'] = .99
        self.view.set_model(self.store, 'PCS1', 3)
        lattice_surface = self.view._stack_geometry()[2][1][4]
        self.assertNotEqual(changed_surface, lattice_surface)
        self.view.show_holes = False
        self.view.grab()
        self.assertEqual(self.view.aperture_paths, [])
        self.assertTrue(self.view._stack_geometry()[2][1][4].contains(QPointF(0, 0)))
        self.view.show_holes = True
        self.view.grab()
        self.assertGreater(len(self.view.aperture_paths), 0)

    def test_projection_cache_reuses_repaints_and_changes_with_camera(self):
        self.view.grab()
        first = self.view._projection
        self.view.grab()
        self.assertIs(self.view._projection, first)
        self.view.angle += .2
        self.view.grab()
        self.assertIsNot(self.view._projection, first)
        rotated = self.view._projection
        self.view.resize(710, 610)
        self.view.grab()
        self.assertIsNot(self.view._projection, rotated)

    def test_overlapping_holes_form_one_transparent_union(self):
        self.view.cells = 1
        region = dict(self.view.patterns[0])
        region.update(cx=-.04, sx=.15, sy=.15)
        second = dict(region, cx=.04)
        self.view.patterns = [region, second]
        surface = self.view._stack_geometry()[2][1][4]
        self.assertFalse(surface.contains(QPointF(0, 0)))

    def test_circle_ellipse_and_rectangle_reveal_lower_layer_during_orbit(self):
        self.view.layers = [dict(Name='Air', Material='Air', Thickness_um=0),
            dict(Name='Patterned', Material='GaAs', Thickness_um=.08),
            dict(Name='Lower', Material='SiC', Thickness_um=0)]
        self.view.cells = 1
        self.view.ax = self.view.ay = .54
        self.view.hidden_layers = {'Air'}
        self.view.show_axes = False
        self.view.elevation = .7
        for shape, sx, sy, rotation in [('circle', .24, .24, 0),
                ('ellipse', .24, .20, 30), ('rectangle', .44, .42, 35)]:
            self.view.patterns = [dict(layer='Patterned', material='Air',
                shape=shape, cx=0, cy=0, sx=sx, sy=sy, angle=rotation)]
            for angle in (-.78, 0, 1.04, 3.14):
                self.view.angle = angle
                self.view.layer_colors = {'Lower': '#00ff00'}
                first = self.view.grab().toImage()
                apertures = [path for _, path in self.view.aperture_paths if not path.isEmpty()]
                self.assertTrue(apertures, (shape, angle))
                # Rotated rectangles can wrap into the neighboring unit cell.
                # Select the main opening rather than a clipped corner copy.
                aperture = max(apertures, key=lambda path:
                    path.boundingRect().width()*path.boundingRect().height())
                self.view.layer_colors = {'Lower': '#ff00ff'}
                second = self.view.grab().toImage()
                bounds = aperture.boundingRect()
                visible = sum(1 for y in range(int(bounds.top())+2, int(bounds.bottom())-2, 4)
                    for x in range(int(bounds.left())+2, int(bounds.right())-2, 4)
                    if aperture.contains(QPointF(x, y)) and first.pixel(x, y) != second.pixel(x, y))
                self.assertGreater(visible, 4, (shape, angle))

    def test_drag_remains_immediate_and_click_selects_the_layer(self):
        selected = []
        self.view.layer_selected.connect(selected.append)
        self.view.grab()
        label, name = self.view.hits[-1]
        position = label.center()
        def mouse(kind, point):
            event = QMouseEvent(kind, point, self.view.mapToGlobal(point),
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.view, event)
        mouse(QEvent.Type.MouseButtonPress, position)
        mouse(QEvent.Type.MouseButtonRelease, position)
        self.assertEqual(selected, [name])
        mouse(QEvent.Type.MouseButtonPress, position)
        initial = self.view.angle
        mouse(QEvent.Type.MouseMove, position+QPointF(15, 4))
        self.assertAlmostEqual(self.view.angle, initial+15*.009)
        self.assertTrue(self.view.dragged)
        mouse(QEvent.Type.MouseButtonRelease, position+QPointF(15, 4))
        self.assertEqual(selected, [name])

    def test_burst_of_drag_events_coalesces_without_delaying_camera_state(self):
        position = QPointF(250, 230)
        def mouse(kind, point):
            event = QMouseEvent(kind, point, self.view.mapToGlobal(point),
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.view, event)
        self.view.grab()
        initial = self.view.angle
        mouse(QEvent.Type.MouseButtonPress, position)
        with patch.object(self.view, 'paint_stack', wraps=self.view.paint_stack) as paint:
            for frame in range(20):
                mouse(QEvent.Type.MouseMove, position+QPointF((frame+1)*3, 0))
            self.assertAlmostEqual(self.view.angle, initial+60*.009)
            self.assertEqual(paint.call_count, 0)
            self.app.processEvents()
            self.assertGreater(paint.call_count, 0)
            self.assertLess(paint.call_count, 4)
        mouse(QEvent.Type.MouseButtonRelease, position+QPointF(60, 0))


if __name__ == '__main__':
    unittest.main()
