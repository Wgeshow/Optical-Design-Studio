"""Saved-field mesh colors use actual intensity, including domain caps."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import unittest
import numpy as np
import pandas as pd
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from field_volume import surface_values, field_surface
from qt_field_volume import FieldVolumeWidget
from qt_native_field_volume import NativeSurfaceMesh


class Store(QObject):
    library_changed = pyqtSignal()


class FieldSurfaceColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def grid(self):
        return np.stack(np.meshgrid([-.5, 0., .5], [-.5, 0., .5], [.1, .5, .9], indexing='ij'), axis=-1).reshape(-1, 3)

    def test_constant_boundary_caps_show_saved_value_not_cutoff(self):
        xyz = self.grid()
        for value in (1., .5):
            values = np.full(len(xyz), value)
            for cutoff in (0., value * .2, value * .9):
                faces = field_surface(xyz, values, cutoff)
                self.assertGreater(len(faces), 0)
                np.testing.assert_allclose(surface_values(xyz, values, faces), value)

    def test_surface_interpolation_preserves_nonuniform_physical_intensity(self):
        xyz = np.stack(np.meshgrid([-2., -.2, 1.], [-3., .5, 2.], [.1, .3, .9], indexing='ij'), axis=-1).reshape(-1, 3)
        def analytic(points):
            x, y, z = points.T
            return 20. + x + 2. * y + .5 * z + .1 * x * y * z
        centres = np.array([[-2., -1., .2], [.7, .8, .7], [0., 2., .9]])
        offsets = np.array([[0., .03, 0.], [.02, 0., 0.], [-.02, -.03, 0.]])
        faces = centres[:, None, :] + offsets
        order = np.random.default_rng(13).permutation(len(xyz))
        np.testing.assert_allclose(surface_values(xyz[order], analytic(xyz)[order], faces), analytic(centres), rtol=1e-14)

    def test_invalid_grid_rejected_and_empty_surface_safe(self):
        xyz = self.grid()
        with self.assertRaises(ValueError):
            surface_values(xyz[:-1], np.ones(len(xyz) - 1), np.ones((1, 3, 3)))
        duplicate = xyz.copy(); duplicate[-1] = duplicate[-2]
        with self.assertRaises(ValueError):
            surface_values(duplicate, np.ones(len(xyz)), np.ones((1, 3, 3)))
        self.assertEqual(len(surface_values(xyz, np.ones(len(xyz)), np.empty((0, 3, 3)))), 0)

    def test_native_mesh_retains_immutable_per_face_colors(self):
        faces = np.array([[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]], [[0., 0., 1.], [1., 0., 1.], [0., 1., 1.]]])
        mesh = NativeSurfaceMesh(faces, [.2, 1.])
        self.assertFalse(mesh.fractions.flags.writeable)
        self.assertGreater(mesh.colors[1].green(), mesh.colors[0].green())
        scalar = NativeSurfaceMesh(faces, .5)
        np.testing.assert_array_equal(scalar.fractions, [.5, .5])
        with self.assertRaises(ValueError):
            NativeSurfaceMesh(faces, [float('nan'), 1.])

    def widget(self):
        xyz = self.grid()
        model = dict(ax=1., ay=1., layers=[dict(name='Top', material='Air', thickness=0.), dict(name='Air cell', material='Air', thickness=1.), dict(name='Bottom', material='Air', thickness=0.)], patterns=[])
        frame = pd.DataFrame(dict(layer=['Air cell'] * len(xyz), z_um=xyz[:, 2]))
        fields = dict(E=np.tile([1.+0j, 0j, 0j], (len(xyz), 1)), H=np.tile([0j, 1.+0j, 0j], (len(xyz), 1)))
        widget = FieldVolumeWidget(Store(), campaign=True)
        widget.data = (dict(model=model, wavelength_nm=1550.), frame, xyz, fields)
        widget.mode.blockSignals(True); widget.mode.clear(); widget.mode.addItems(['E', 'H', 'Energy flow']); widget.mode.blockSignals(False)
        return widget

    def test_uniform_e_h_and_flow_agree_with_global_colorbar_and_export(self):
        widget = self.widget()
        try:
            original = {key: value.copy() for key, value in widget.data[3].items()}
            for mode, peak in [('E', 1.), ('H', 1.), ('Energy flow', .5)]:
                widget.mode.setCurrentText(mode)
                widget.threshold.setValue(20)
                widget.render()
                self.assertEqual(widget.plot.canvas.peak, peak)
                self.assertGreater(len(widget.surfaces), 0)
                for full, fast in widget.surfaces:
                    np.testing.assert_allclose(full.fractions, 1.)
                    np.testing.assert_allclose(fast.fractions, 1.)
                    self.assertTrue(all(color.green() > color.blue() for color in full.colors))
                figure = widget.publication_figure()
                colors = np.asarray(figure.axes[0].collections[0].get_facecolor())
                self.assertTrue(np.all(colors[:, 1] > colors[:, 2]))
                widget.phase.setValue(90)
                for key, value in original.items():
                    np.testing.assert_array_equal(widget.data[3][key], value)
        finally:
            widget.close(); widget.deleteLater(); self.app.processEvents()

    def test_layer_filter_preserves_complete_peak_for_surface_colors(self):
        widget = self.widget()
        try:
            metadata, frame, xyz, fields = widget.data
            metadata = copy.deepcopy(metadata)
            metadata['model']['layers'].insert(-1, dict(name='Strong cell', material='Air', thickness=1.))
            second = frame.copy(); second['layer'] = 'Strong cell'; second['z_um'] += 1.
            deeper = xyz.copy(); deeper[:, 2] += 1.
            fields = {key: np.concatenate([value, value * 2.]) for key, value in fields.items()}
            widget.data = (metadata, pd.concat([frame, second], ignore_index=True), np.concatenate([xyz, deeper]), fields)
            widget.layer.addItem('Air cell', 'Air cell'); widget.layer.addItem('Strong cell', 'Strong cell')
            widget.threshold.setValue(0)
            for layer, fraction in [('Air cell', .25), ('Strong cell', 1.)]:
                widget.layer.setCurrentText(layer); widget.render()
                self.assertEqual(widget.plot.canvas.peak, 4.)
                for full, fast in widget.surfaces:
                    np.testing.assert_allclose(full.fractions, fraction)
                    np.testing.assert_allclose(fast.fractions, fraction)
        finally:
            widget.close(); widget.deleteLater(); self.app.processEvents()


if __name__ == '__main__':
    unittest.main()

