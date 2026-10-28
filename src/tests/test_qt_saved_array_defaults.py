"""Saved physical fields remain default and closely spaced colorbar values readable."""
import json, os, tempfile, unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from matplotlib.colors import Normalize, LogNorm
from PyQt6.QtWidgets import QApplication
from qt_research_results import SavedArrayViewer
from qt_native_figure import SourceAxis

APP=QApplication.instance() or QApplication([])

class SavedArrayDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.root=Path(self.temp.name)
        axes=[dict(name='y',coordinate='y_um',unit='um'),dict(name='x',coordinate='x_um',unit='um')]
        self.metadata={key:dict(axes=axes,unit=unit) for key,unit in [('current_A_cm2','A/cm2'),('temperature_K','K')]}
        self.temperature=300.0195614368399+np.arange(6.).reshape(2,3)*1.4571372162208718e-6/5
        for i in range(2):
            np.savez(self.root/f'fields_{i}.npz',x_um=[0.,1.,2.],y_um=[0.,1.],
                     evaluated_mask=np.ones((2,3),dtype=bool),current_A_cm2=np.ones((2,3)),
                     temperature_K=self.temperature+i*1e-7,array_axes=json.dumps(self.metadata))
        self.viewer=SavedArrayViewer()
    def tearDown(self):
        from PyQt6 import sip
        sip.delete(self.viewer);APP.processEvents();self.temp.cleanup()
    def test_initial_view_is_physical_array_not_first_coordinate_or_mask(self):
        self.viewer.load_directory(self.root)
        self.assertEqual(self.viewer.quantity.currentText(),'current_A_cm2')
        self.assertEqual(set(self.viewer.coordinates),{0,1})
        self.assertEqual(self.viewer.displayed.shape,(3,2))
        self.assertGreaterEqual(self.viewer.quantity.findText('x_um'),0)
    def test_quantity_and_same_directory_file_survive_selection_and_refresh(self):
        self.viewer.load_directory(self.root)
        self.viewer.quantity.setCurrentText('temperature_K')
        self.viewer.files.setCurrentIndex(1)
        self.assertEqual(self.viewer.quantity.currentText(),'temperature_K')
        np.testing.assert_array_equal(self.viewer.displayed,(self.temperature+1e-7).T)
        self.viewer.load_directory(self.root)
        self.assertEqual(Path(self.viewer.files.currentData()).name,'fields_1.npz')
        self.assertEqual(self.viewer.quantity.currentText(),'temperature_K')
    def test_explicit_coordinate_selection_is_preserved_between_files(self):
        self.viewer.load_directory(self.root);self.viewer.quantity.setCurrentText('x_um')
        self.viewer.files.setCurrentIndex(1)
        self.assertEqual(self.viewer.quantity.currentText(),'x_um')
        np.testing.assert_array_equal(self.viewer.displayed,[0.,1.,2.])
    def test_no_physical_arrays_has_no_misleading_default(self):
        other=self.root/'coordinates';other.mkdir()
        np.savez(other/'coords.npz',x_um=[0.,1.],array_axes='{}')
        self.viewer.load_directory(other)
        self.assertEqual(self.viewer.quantity.currentIndex(),-1)
        self.assertIsNone(self.viewer.array)
        self.assertIn('No physical numeric array',self.viewer.note.text())
    def test_native_colorbar_preserves_small_temperature_variation(self):
        self.viewer.load_directory(self.root);self.viewer.quantity.setCurrentText('temperature_K')
        bar=self.viewer.plot.canvas.colorbars[0]
        norm=bar['norm'];ticks=np.linspace(0.,1.,5)
        labels=bar['native_item'].getAxis('right').tickStrings(ticks,1,.25)
        self.assertEqual(len(set(labels)),5)
        actual=np.asarray([float(text) for text in labels])
        np.testing.assert_allclose(actual,norm.inverse(ticks),rtol=0,atol=np.ptp(self.temperature)/100)
        np.testing.assert_array_equal(self.viewer.displayed,self.temperature.T)
        self.assertEqual(norm.vmin,float(self.temperature.min()))
        self.assertEqual(norm.vmax,float(self.temperature.max()))
    def test_precise_colorbar_labels_fit_and_are_actually_drawn(self):
        from PyQt6.QtGui import QImage,QPainter
        self.viewer.resize(1586,900);self.viewer.show()
        self.viewer.load_directory(self.root);self.viewer.quantity.setCurrentText('temperature_K')
        for width in (1586,860):
            self.viewer.resize(width,900)
            for _ in range(3):
                APP.processEvents();self.viewer.plot.canvas.view.viewport().grab()
            bar=self.viewer.plot.canvas.colorbars[0]['native_item']
            axis=bar.getAxis('right')
            image=QImage(1600,1000,QImage.Format.Format_ARGB32);image.fill(0)
            painter=QPainter(image);painter.setFont(axis.style['tickFont'])
            try:spec=axis.generateDrawSpecs(painter)
            finally:painter.end()
            self.assertIsNotNone(spec)
            labels=spec[2]
            self.assertGreaterEqual(len(labels),3,(width,axis.width(),labels))
            self.assertGreaterEqual(len({text for rect,flags,text in labels}),3)
            self.assertTrue(all(rect.right()<=axis.boundingRect().right()+1e-6 for rect,flags,text in labels))

    def test_wide_and_log_colorbar_ticks_remain_absolute(self):
        for norm in (Normalize(-2,4),LogNorm(1e-6,1e2)):
            axis=SourceAxis('right',norm=norm)
            ticks=np.array([0.,.5,1.])
            np.testing.assert_allclose([float(x) for x in axis.tickStrings(ticks,1,.5)],norm.inverse(ticks),rtol=.001,atol=1e-12)

if __name__=='__main__':unittest.main()
