"""Regress data semantics and layout behavior of the live native RCWA spectrum."""
import os
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt,QPoint,QPointF,QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QLineEdit,QDialogButtonBox,QScrollArea
from qt_native_plot import NativeSpectrumWidget


class NativeSpectrumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.plot=NativeSpectrumWidget()
        self.plot.resize(720,440)
        self.frame=pd.DataFrame(dict(wavelength_nm=[1515.,1535.,1555.],angle_deg=[0.,0.,0.],
            R=[.2,.8,.2],T=[.8,.2,.8],A=[-1e-15,0.,1e-15]))
        self.plot.set_spectrum(self.frame,peak_key='R')
        self.plot.show()
        for _ in range(5):self.app.processEvents()

    def tearDown(self):
        self.plot.close();self.plot.deleteLater();self.app.processEvents()

    def test_live_percent_data_keep_full_raw_and_do_not_build_mpl_canvas(self):
        self.assertIsNone(self.plot._paper)
        self.assertFalse(hasattr(self.plot,'canvas'))
        for key,curve in self.plot.curves.items():
            np.testing.assert_allclose(curve.getOriginalDataset()[1],self.frame[key]*100)
        self.assertEqual(self.plot.plot.getViewBox().viewRange()[1],[0.,100.])
        large=pd.concat([self.frame]*4000,ignore_index=True)
        self.plot.set_spectrum(large)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'raw.csv';self.plot.export_raw_csv(path)
            data=pd.read_csv(path)
            self.assertEqual(len(data),12000)
            np.testing.assert_allclose(data[['R','T','A']],large[['R','T','A']])
        pd.testing.assert_frame_equal(self.frame,self.plot.raw.iloc[:3].reset_index(drop=True))

    def test_angle_axis_peak_and_native_click_choose_original_row(self):
        angle=self.frame.copy();angle['angle_deg']=[0.,30.,60.]
        self.plot.set_spectrum(angle,peak_key='R')
        self.assertEqual(self.plot.variable,'angle_deg')
        self.assertEqual(float(self.plot.marker.points()[0].pos().x()),30.)
        got=[];self.plot.sampleSelected.connect(got.append)
        scene=self.plot.plot.getViewBox().mapViewToScene(QPointF(30.2,50.))
        QTest.mouseClick(self.plot.view.viewport(),Qt.MouseButton.LeftButton,
            pos=self.plot.view.mapFromScene(scene))
        self.app.processEvents()
        self.assertEqual(got[-1],1)
        self.assertEqual(self.plot.cursor.value(),30.)
        self.assertIsNone(self.plot._paper)

    def test_hover_readout_and_updates_reuse_graph_without_layout_growth(self):
        before=(self.plot.size(),self.plot.view.size(),self.plot.plot.getViewBox().size())
        ids=[id(x) for x in self.plot.curves.values()]
        for i in range(3):
            self.plot.select_sample(i)
            scene=self.plot.plot.getViewBox().mapViewToScene(QPointF(self.frame.wavelength_nm[i],50.))
            QTest.mouseMove(self.plot.view.viewport(),self.plot.view.mapFromScene(scene))
            self.app.processEvents()
            self.assertEqual((self.plot.size(),self.plot.view.size(),self.plot.plot.getViewBox().size()),before)
        self.plot.set_spectrum(self.frame.iloc[:2])
        self.assertEqual(ids,[id(x) for x in self.plot.curves.values()])
        self.plot.resize(360,300);self.app.processEvents()
        self.assertLessEqual(self.plot.width(),360)
        self.assertGreater(self.plot.view.height(),100)

    def test_compact_icon_controls_are_accessible_and_do_not_shift_on_hover(self):
        self.plot.resize(360,300);self.app.processEvents()
        sizes=(self.plot.size(),self.plot.view.size(),self.plot.toolbar.size())
        for name,button in self.plot.buttons.items():
            self.assertEqual(button.accessibleName(),name)
            self.assertEqual(button.toolTip(),name)
            self.assertTrue(button.text()=='')
            self.assertFalse(button.icon().isNull())
            self.assertEqual((button.width(),button.height()),(30,30))
            QTest.mouseMove(button,button.rect().center());self.app.processEvents()
            self.assertEqual((self.plot.size(),self.plot.view.size(),self.plot.toolbar.size()),sizes)
        QTest.mouseClick(self.plot.buttons['Zoom'],Qt.MouseButton.LeftButton)
        self.assertTrue(self.plot.buttons['Zoom'].isChecked())
        self.assertFalse(self.plot.buttons['Pan'].isChecked())
        QTest.mouseClick(self.plot.buttons['Pan'],Qt.MouseButton.LeftButton)
        self.assertTrue(self.plot.buttons['Pan'].isChecked())

    def test_simulation_stacks_and_scrolls_without_clipping_narrow_graph(self):
        from data_library import DataLibrary
        from qt_core import ProjectStore
        from qt_compute import SimulationPage
        with tempfile.TemporaryDirectory() as root:
            page=SimulationPage(ProjectStore(DataLibrary(root),restore=False))
            page.result_frame=self.frame;page.update_peak()
            page.resize(960,640);page.show()
            for _ in range(10):self.app.processEvents()
            splitter=page.workspace_splitter
            self.assertEqual(splitter.orientation(),Qt.Orientation.Vertical)
            self.assertLessEqual(splitter.width(),page.workspace_scroll.viewport().width())
            self.assertGreater(page.workspace_scroll.verticalScrollBar().maximum(),0)
            for i in range(2):
                self.assertLessEqual(splitter.widget(i).geometry().bottom(),splitter.widget(i+1).geometry().top())
            self.assertLessEqual(page.plot.geometry().bottom(),page.plot.parentWidget().rect().bottom())
            page.workspace_scroll.ensureWidgetVisible(page.controls['wl_start_nm'])
            self.app.processEvents()
            self.assertTrue(page.controls['wl_start_nm'].isVisible())
            def reveal(control):
                area=control.parentWidget()
                while area is not None and not isinstance(area,QScrollArea):area=area.parentWidget()
                self.assertIsNotNone(area)
                area.ensureWidgetVisible(control,0,8)
                page.workspace_scroll.ensureWidgetVisible(area,0,8)
                self.app.processEvents()
                center=control.mapTo(area.viewport(),control.rect().center())
                self.assertTrue(area.viewport().rect().contains(center))
            reveal(page.measure_phase)
            previous=page.measure_phase.isChecked()
            QTest.mouseClick(page.measure_phase,Qt.MouseButton.LeftButton,pos=QPoint(10,page.measure_phase.height()//2))
            self.assertNotEqual(page.measure_phase.isChecked(),previous)
            grid=page.field_controls['grid'];reveal(grid)
            previous=grid.value();grid.setFocus()
            QTest.keyClick(grid,Qt.Key.Key_Up)
            self.assertEqual(grid.value(),previous+1)
            page.resize(1280,850)
            for _ in range(10):self.app.processEvents()
            self.assertEqual(splitter.orientation(),Qt.Orientation.Horizontal)
            page.close();page.deleteLater();self.app.processEvents()

    def test_publication_settings_and_export_have_no_live_size_constraint(self):
        from PIL import Image
        self.plot.figure_style.update(width_mm=90,height_mm=60,dpi=150)
        before=(self.plot.size(),self.plot.view.size())
        def edit():
            dialog=self.app.activeModalWidget()
            for entry in dialog.findChildren(QLineEdit):
                if entry.text()=='Optical response':entry.setText('Edited native spectrum')
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(100,edit)
        self.plot.edit_figure_settings()
        self.assertEqual(self.plot.plot.titleLabel.text,'Edited native spectrum')
        self.assertEqual(self.plot.figure.axes[0].get_title(),'Edited native spectrum')
        self.assertEqual(self.plot.figure.canvas.__class__.__name__,'FigureCanvasBase')
        self.assertEqual((self.plot.size(),self.plot.view.size()),before)

        with tempfile.TemporaryDirectory() as root:
            for suffix in ('png','pdf','svg','tiff'):
                path=Path(root)/('spectrum.'+suffix)
                self.plot.export_figure(path)
                self.assertGreater(path.stat().st_size,1000)
            with Image.open(Path(root)/'spectrum.png') as image:
                self.assertLessEqual(abs(image.width-90/25.4*150),1)
                self.assertLessEqual(abs(image.height-60/25.4*150),1)
                self.assertEqual(image.convert('RGB').getpixel((0,0)),(255,255,255))
        self.assertEqual((self.plot.size(),self.plot.view.size()),before)

    def test_saved_solver_warning_remains_visible_after_completion(self):
        from data_library import DataLibrary
        from qt_core import ProjectStore
        from qt_compute import SimulationPage
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);directory=root/'result';directory.mkdir()
            self.frame.to_csv(directory/'results.csv',index=False)
            page=SimulationPage(ProjectStore(DataLibrary(root/'library'),restore=False))
            page.directory=directory
            page.show_result(dict(output=str(directory/'results.csv'),
                info=dict(warnings=['Energy balance residual exceeds tolerance.'])))
            self.assertIn('Warnings: Energy balance residual',page.status.text())
            self.assertFalse(page.status.isHidden())
            page.show_result(dict(output=str(directory/'results.csv'),info={}))
            self.assertTrue(page.status.isHidden())
            page.close();page.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()
