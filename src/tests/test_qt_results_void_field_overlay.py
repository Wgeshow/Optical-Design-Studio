"""Saved electrostatic fields remain visible inside dielectric void geometry."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication
from qt_electrical_results import _FieldColors
from qt_results_workspace import ResultsMapCanvas


class ResultsVoidFieldOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def render(self, shape, logarithmic=False):
        canvas = ResultsMapCanvas('xy')
        canvas.resize(440, 340)
        axis = np.array([-3., -1., 1., 3.])*1e-6
        values = np.arange(1., 17.).reshape(4, 4)*.0005
        colors = _FieldColors(values, logarithmic)
        canvas.device = dict(width_um=8., depth_um=8., layers=[dict(id='ambient',
            thickness_um=.5, enabled=True)], shapes=[dict(id='void', name='Vacuum',
            layer_id='ambient', operation='void', shape=shape, enabled=True,
            cx_um=0., cy_um=0., size_x_um=8., size_y_um=8., angle_deg=0., vertices=[])])
        canvas.plane_coordinate = .03125e-6
        canvas.set_field(axis, axis, values, colors, None, 'Potential')
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        image.fill(0)
        canvas.render(image)  # Offscreen paint only; never launch/show a window.
        return canvas, image, values, colors

    def test_nonzero_saved_potential_is_visible_inside_void(self):
        for shape in ('rectangle', 'circle'):
            for logarithmic in (False, True):
                with self.subTest(shape=shape, logarithmic=logarithmic):
                    canvas, image, values, colors = self.render(shape, logarithmic)
                    rect = canvas._plot_bounds()
                    # Interior saved cells are physically in vacuum; they still have potential.
                    for i, j in ((1, 1), (1, 2), (2, 1), (2, 2)):
                        x = round(rect.left()+(i+.5)/4*rect.width())
                        y = round(rect.top()+(j+.5)/4*rect.height())
                        self.assertEqual(image.pixelColor(x, y).rgba(), colors.color(values[i, j]).rgba())
                    np.testing.assert_array_equal(canvas.values, values)
                    canvas.deleteLater()
        self.app.processEvents()

    def test_void_outline_remains_visible(self):
        canvas, with_outline, _, _ = self.render('circle')
        canvas.device = {}
        without = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        without.fill(0)
        canvas.render(without)
        rect = canvas._plot_bounds()
        different = sum(with_outline.pixelColor(x, y).rgba()!=without.pixelColor(x, y).rgba()
            for x in range(int(rect.left())+2, int(rect.right())-2)
            for y in range(int(rect.top())+2, int(rect.bottom())-2))
        self.assertGreater(different, 20)
        self.assertLess(different, rect.width()*rect.height()*.05)
        canvas.deleteLater()
        self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
