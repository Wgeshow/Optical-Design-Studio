import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
from pathlib import Path
import unittest
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from field_volume import vectors, amplitude, load_volume, field_surface, visible_samples, interaction_surface
from test_field_tracking_ui import sample


class Store(QObject):
    library_changed = pyqtSignal()


class VolumeTests(unittest.TestCase):
    def test_continuous_surface_threshold_and_orientation(self):
        axis = np.linspace(-1,1,9)
        xyz = np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),axis=-1).reshape(-1,3)
        values = np.exp(-np.sum(xyz**2,axis=1)*3)
        visible, cutoff = visible_samples(values,50)
        self.assertEqual(cutoff,.5)
        self.assertLess(visible.sum(),len(values))
        faces = field_surface(xyz,values,cutoff)
        original = faces.copy()
        reduced = interaction_surface(faces,900)
        self.assertGreater(len(reduced),0)
        self.assertLessEqual(len(reduced),900)
        np.testing.assert_array_equal(original,faces)
        self.assertTrue(np.isfinite(reduced).all())
        self.assertGreater(len(faces),0)
        normals = np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
        self.assertTrue(np.all(np.sum(normals*faces.mean(axis=1),axis=1)>=-1e-12))
        high = field_surface(xyz,values,.8)
        self.assertLess(np.abs(high).max(),np.abs(faces).max())
        self.assertEqual(len(field_surface(xyz,np.zeros(len(values)),0)),0)
        self.assertEqual(len(field_surface(xyz,values,2)),0)
        with self.assertRaises(ValueError):
            field_surface(xyz[:-1],values[:-1],.5)

    def test_phase_and_poynting(self):
        fields = {'E': np.array([[1+0j, 1j, 0j]]), 'H': np.array([[0j, 1+0j, 0j]])}
        np.testing.assert_allclose(vectors(fields,'E',0), [[1,0,0]])
        np.testing.assert_allclose(vectors(fields,'E',90), [[0,1,0]], atol=1e-15)
        np.testing.assert_allclose(vectors(fields,'E',180), [[-1,0,0]], atol=1e-15)
        np.testing.assert_allclose(vectors(fields,'Energy flow',90), [[0,0,.5]])
        np.testing.assert_allclose(amplitude(fields,'E'), [2])

    def test_component_intensity_and_phase_vectors(self):
        fields = {'E': np.array([[1+0j, 2j, 3+0j]])}
        np.testing.assert_allclose(amplitude(fields,'Ey'), [4])
        np.testing.assert_allclose(vectors(fields,'Ey',90), [[0,2,0]],atol=1e-15)
        np.testing.assert_allclose(vectors(fields,'Ez',0), [[0,0,3]])
        np.testing.assert_allclose(amplitude(fields,'E'), [14])

    def test_saved_volume_and_native_playback(self):
        from qt_field_volume import FieldVolumeWidget
        import pandas as pd
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            store = Store()
            store.library = DataLibrary(Path(folder))
            directory = store.library.runs/'run'/'fields'
            sample(directory,maps=True)
            self.assertEqual(len(load_volume(directory)[1]),27)
            widget = FieldVolumeWidget(store)
            widget.resize(1100,800)
            widget.show()
            app.processEvents()
            widget.load()
            self.assertIsNotNone(widget.data,widget.status.text())
            self.assertGreater(widget.surface_faces,0)
            self.assertNotIn('Use Sample points',widget.status.text())
            widget.threshold.setValue(90)
            self.assertLess(len(widget.ids),27)
            widget.show_arrows.setChecked(True)
            self.assertIsNotNone(widget.arrow)
            from PyQt6.QtCore import Qt
            from PyQt6.QtTest import QTest
            from unittest.mock import patch
            widget.plot.canvas.draw()
            canvas = widget.plot.canvas
            position=canvas.rect().center()
            widget.play.setChecked(True)
            self.assertTrue(widget.timer.isActive())
            QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=position)
            self.assertTrue(widget.dragging)
            self.assertFalse(widget.timer.isActive())
            self.assertTrue(all(not full.get_visible() and fast.get_visible() for full,fast in widget.surfaces))
            QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=position)
            self.assertTrue(widget.restore_timer.isActive())
            widget.restore_timer.stop()
            widget.finish_interaction()
            self.assertFalse(widget.dragging)
            self.assertTrue(widget.timer.isActive())
            widget.play.setChecked(False)
            self.assertTrue(all(full.get_visible() and not fast.get_visible() for full,fast in widget.surfaces))
            widget.show_arrows.setChecked(False)
            with patch.object(canvas,'draw_idle') as draw:
                widget.phase.setValue(31)
                draw.assert_not_called()
            widget.show_arrows.setChecked(True)
            self.assertEqual(widget.mode.count(),1)  # Legacy electric-only data.
            frame = pd.read_csv(directory/'electric_fields.csv')
            for axis in 'xyz':
                frame['H'+axis+'_real'] = 1 if axis == 'y' else 0
                frame['H'+axis+'_imag'] = 0
            frame.to_csv(directory/'electric_fields.csv',index=False)
            widget.load()
            self.assertEqual(widget.mode.count(),3)
            widget.phase.setValue(90)
            widget.mode.setCurrentText('H')
            self.assertTrue(widget.play.isEnabled())
            widget.mode.setCurrentText('Energy flow')
            self.assertFalse(widget.play.isEnabled())
            widget.plot.canvas.draw()
            widget.close()
            app.processEvents()

    def test_depth_validation(self):
        from field_solver import execute_fields
        for value in (0,41,True,3.5):
            with self.assertRaises(ValueError):
                execute_fields({}, {}, dict(depth_samples=value), '.')

    def test_native_s4_volume(self):
        from test_backend import sample as model_sample
        from model import DEFAULT_PERFORMANCE
        from field_solver import execute_fields
        model = model_sample(wl_start_nm=1550,wl_stop_nm=1550)
        for material in model['materials']:
            material.update(a=1.,b=0.)
        with tempfile.TemporaryDirectory() as folder:
            execute_fields(model,dict(DEFAULT_PERFORMANCE,timeout_seconds=60),
                           dict(wavelength_nm=1550.,grid=3,depth_samples=5,maps=True),folder)
            _, frame, _, fields = load_volume(folder)
            self.assertEqual(len(frame),45)
            self.assertEqual(frame['z_um'].nunique(),5)
            np.testing.assert_allclose(amplitude(fields,'E'),1.,atol=1e-7)
            flux = vectors(fields,'Energy flow',0)
            self.assertTrue(np.all(flux[:,2]>0))


if __name__ == '__main__':
    unittest.main()
