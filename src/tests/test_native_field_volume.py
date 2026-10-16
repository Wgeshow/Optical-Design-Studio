"""Native 3D playback preserves phasors, physical coordinates and mesh caches."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import copy
import unittest
from unittest.mock import patch
import numpy as np
from PyQt6.QtCore import QObject,Qt,QPointF,QEvent,QTimer,pyqtSignal
from PyQt6.QtGui import QMouseEvent,QWheelEvent
from PyQt6.QtWidgets import QApplication,QFormLayout,QDialogButtonBox
from qt_common import theme_manager
from qt_field_volume import FieldVolumeWidget
from qt_native_field_volume import NativeVolumeCanvas,NativeSurfaceMesh,NativeFieldVolumePlot
from field_volume import vectors
from tests.test_field_tracking_ui import sample


class Store(QObject):library_changed=pyqtSignal()


class NativeFieldVolumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        theme_manager().apply_look('glass_dark',persist=False)
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'fields'
        sample(self.path,maps=True)
        self.widget=FieldVolumeWidget(Store(),campaign=True)
        self.widget.resize(1000,800);self.widget.show();self.app.processEvents()
        with patch('matplotlib.figure.Figure',side_effect=AssertionError('Live replay must not create export artists')):
            self.widget.load_directory(self.path)
        self.assertIsNotNone(self.widget.data,self.widget.status.text())
        self.canvas=self.widget.plot.canvas

    def tearDown(self):
        self.widget.close();self.widget.deleteLater();self.app.processEvents();self.temp.cleanup()

    def test_phase_changes_actual_vectors_only_and_reuses_surface_projection(self):
        self.assertIsInstance(self.widget.plot,NativeFieldVolumePlot)
        self.assertIsInstance(self.canvas,NativeVolumeCanvas)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        self.assertFalse(self.widget.findChildren(FigureCanvasQTAgg))
        xyz=self.widget.data[2].copy();fields={key:value.copy() for key,value in self.widget.data[3].items()}
        faces=[mesh.faces.copy() for mesh,_ in self.widget.surfaces]
        self.widget.show_arrows.setChecked(True);self.widget.phase.setValue(0)
        first=self.canvas.grab().toImage()
        picture=self.widget.surfaces[0][0]._picture
        arrow=self.widget.arrow
        self.widget.phase.setValue(90);second=self.canvas.grab().toImage()
        self.assertIs(self.widget.arrow,arrow)
        self.assertIs(self.widget.surfaces[0][0]._picture,picture)
        selected={key:value[self.widget.arrow_ids] for key,value in fields.items()}
        np.testing.assert_allclose(self.widget.arrow.vectors,vectors(selected,'E',90)*self.widget.scale)
        self.assertGreater(sum(first.pixel(x,y)!=second.pixel(x,y)
            for y in range(40,self.canvas.height()-30,3) for x in range(30,self.canvas.width()-80,3)),20)
        np.testing.assert_array_equal(self.widget.data[2],xyz)
        for key in fields:np.testing.assert_array_equal(self.widget.data[3][key],fields[key])
        for (mesh,_),original in zip(self.widget.surfaces,faces):np.testing.assert_array_equal(mesh.faces,original)

    def test_real_units_threshold_and_native_camera_preserve_saved_arrays(self):
        self.assertEqual(self.canvas.axis_ranges,((-.5,.5),(-.5,.5),(0.,1.)))
        self.assertAlmostEqual(self.canvas.peak,float(np.sum(np.abs(self.widget.data[3]['E'])**2,axis=1).max()))
        all_peak=self.canvas.peak
        self.widget.threshold.setValue(90)
        self.assertLess(len(self.widget.ids),27);self.assertEqual(self.canvas.peak,all_peak)
        xyz=self.widget.data[2].copy();old_camera=self.canvas.azimuth
        point=QPointF(self.canvas.width()/2,self.canvas.height()/2)
        def mouse(kind,position):
            event=QMouseEvent(kind,position,self.canvas.mapToGlobal(position),Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.canvas,event)
        mouse(QEvent.Type.MouseButtonPress,point)
        for index in range(20):mouse(QEvent.Type.MouseMove,point+QPointF((index+1)*2,0))
        self.assertAlmostEqual(self.canvas.azimuth,old_camera+20.)
        self.assertTrue(self.widget.dragging)
        self.assertTrue(all(not full.visible and fast.visible for full,fast in self.widget.surfaces))
        mouse(QEvent.Type.MouseButtonRelease,point+QPointF(40,0))
        self.widget.restore_timer.stop();self.widget.finish_interaction()
        before_zoom=self.canvas.zoom
        wheel=QWheelEvent(point,self.canvas.mapToGlobal(point),QPointF(0,0).toPoint(),QPointF(0,120).toPoint(),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        QApplication.sendEvent(self.canvas,wheel)
        self.assertGreater(self.canvas.zoom,before_zoom)
        np.testing.assert_array_equal(self.widget.data[2],xyz)
        # A physical micrometre along y and depth uses one uniform projection
        # scale even when the model's three axis spans are very different.
        self.canvas.azimuth=0.;self.canvas.elevation=0.;self.canvas.zoom=1.
        screen,_=self.canvas.project(np.array([[0,0,0],[0,1,0],[0,0,1]]))
        self.assertAlmostEqual(float(np.linalg.norm(screen[1]-screen[0])),float(np.linalg.norm(screen[2]-screen[0])))

    def test_publication_export_is_lazy_and_contains_saved_surface(self):
        self.canvas.grab()
        picture=self.widget.surfaces[0][0]._picture
        original=self.widget.data[2].copy()
        figure=self.widget.publication_figure()
        self.assertEqual(figure.axes[0].get_xlim(),(-.5,.5))
        self.assertEqual(figure.axes[0].get_ylim(),(-.5,.5))
        self.assertEqual(figure.axes[0].get_zlim(),(1.,0.))
        path=Path(self.temp.name)/'field.pdf';self.widget.plot.export_figure(path)
        self.assertGreater(path.stat().st_size,1000)
        self.assertIs(self.widget.surfaces[0][0]._picture,picture)
        np.testing.assert_array_equal(self.widget.data[2],original)

    def test_native_colorbar_retains_fixed_inferno_scale_with_arrows(self):
        self.widget.show_arrows.setChecked(True)
        image=self.canvas.grab().toImage()
        x=self.canvas.width()-82
        bright=image.pixelColor(x,91)
        dark=image.pixelColor(x,self.canvas.height()-140)
        self.assertGreater(bright.red(),220)
        self.assertGreater(bright.green(),210)
        self.assertLess(dark.red(),25)
        self.assertLess(dark.green(),25)
        for button in self.widget.plot.buttons.values():
            self.assertEqual(button.toolButtonStyle(),Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.assertFalse(button.icon().isNull())
            self.assertTrue(button.accessibleName());self.assertTrue(button.toolTip())
            icon=button.icon().pixmap(20,20).toImage()
            self.assertGreater(sum(icon.pixelColor(x,y).alpha()>0 for y in range(20) for x in range(20)),10)
        self.canvas.azimuth=13.;self.widget.plot.buttons['Fit'].click()
        self.assertEqual(self.canvas.azimuth,-55.)

    def test_layer_filter_keeps_complete_peak_and_physical_depth(self):
        import pandas as pd
        metadata,frame,xyz,fields=self.widget.data
        metadata=copy.deepcopy(metadata)
        metadata['model']['layers'].insert(-1,dict(name='Other',material='Film',thickness=1.))
        second=frame.copy();second['layer']='Other';second['z_um']+=1.
        deeper=xyz.copy();deeper[:,2]+=1.
        fields={key:np.concatenate([value,value*10]) for key,value in fields.items()}
        self.widget.data=(metadata,pd.concat([frame,second],ignore_index=True),np.concatenate([xyz,deeper]),fields)
        self.widget.layer.addItem('Other','Other')
        self.widget.style.setCurrentText('Sample points');self.widget.threshold.setValue(0)
        self.widget.layer.setCurrentText('PCS')
        peak=self.canvas.peak
        self.assertTrue(np.all(self.canvas.points[:,2]<1.))
        self.assertEqual(len(self.canvas.points),27)
        self.widget.layer.setCurrentText('Other')
        self.assertEqual(self.canvas.peak,peak)
        self.assertTrue(np.all(self.canvas.points[:,2]>1.))
        self.assertEqual(self.canvas.axis_ranges[2],(0.,2.))
        self.assertTrue(np.all(self.widget.ids>=27))

    def test_rotated_regions_keep_saved_degrees_and_physical_polygons(self):
        from structure_preview import region_polygon,periodic_centers,clip_polygon
        model=copy.deepcopy(self.widget.data[0]['model'])
        window=(-model['ax']/2,model['ax']/2,-model['ay']/2,model['ay']/2)
        for shape in ('rectangle','ellipse'):
            with self.subTest(shape=shape):
                region=dict(layer=model['layers'][1]['name'],material='Air',shape=shape,
                    cx=.44,cy=.12,sx=.4,sy=.12,angle=45.)
                model['patterns']=[region]
                self.canvas._build_geometry(model)
                expected=[]
                for center in periodic_centers(region,model['ax'],model['ay'],window):
                    polygon=clip_polygon(region_polygon(region,center),window)
                    if len(polygon)<3:continue
                    xy=np.asarray(list(polygon)+[polygon[0]])
                    for z in (0.,float(model['layers'][1]['thickness'])):
                        expected.append(np.column_stack([xy,np.full(len(xy),z)]))
                actual=self.canvas.layer_lines[6:]
                self.assertEqual(len(actual),len(expected))
                self.assertGreater(len(actual),2,'Rotated region must wrap across the periodic cell edge')
                for native,saved in zip(actual,expected):np.testing.assert_allclose(native,saved,atol=1e-14)
                self.assertEqual(model['patterns'][0]['angle'],45.)
        for combo in (self.widget.snapshot,self.widget.mode,self.widget.layer,self.widget.style):
            self.assertTrue(combo.accessibleName())
        self.assertIn('orbit',self.canvas.toolTip())

    def test_figure_settings_keep_local_style_labels_and_lazy_exports(self):
        plot=self.widget.plot
        self.assertIsNone(plot._publication_figure)
        original=self.widget.data[2].copy();camera=(self.canvas.azimuth,self.canvas.elevation,self.canvas.zoom)
        changed=[]
        def configure():
            dialog=QApplication.activeModalWidget()
            values={'Width (mm)':90.,'Height (mm)':65.,'Font family':'Arial',
                'Axis labels (pt)':12.,'Tick labels (pt)':8.,'Titles (pt)':13.,
                'Title':'Saved silicon fields','X label':'Position x (µm)'}
            for form in dialog.findChildren(QFormLayout):
                for row in range(form.rowCount()):
                    label=form.itemAt(row,QFormLayout.ItemRole.LabelRole)
                    field=form.itemAt(row,QFormLayout.ItemRole.FieldRole)
                    if not label or not field or not label.widget():continue
                    name=label.widget().text()
                    if name in values:
                        control=field.widget();value=values[name]
                        control.setText(value) if isinstance(value,str) else control.setValue(value)
                        changed.append(name)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(0,configure)
        plot.buttons['Settings'].click()
        self.assertEqual(len(changed),len(set(changed)))
        self.assertIn('Width (mm)',changed);self.assertIn('Title',changed)
        self.assertEqual(plot.figure_style['width_mm'],90.)
        self.assertEqual(plot.figure_style['height_mm'],65.)
        self.assertEqual(self.canvas.figure_style['font'],'Arial')
        self.assertEqual(self.canvas.title_override,'Saved silicon fields')
        self.assertEqual(self.canvas.axis_labels[0],'Position x (µm)')
        self.assertEqual(self.canvas.axis_labels[2],'Depth z (µm)')
        self.assertIsNone(plot._publication_figure)
        self.widget.phase.setValue(75)
        path=Path(self.temp.name)/'custom-field.svg';plot.export_figure(path)
        exported=path.read_text(encoding='utf-8')
        self.assertIn('Saved silicon fields',exported);self.assertIn('Position x',exported)
        self.assertIn('width="255.11811pt"',exported)
        self.assertIsNone(plot._publication_figure)
        self.assertEqual((self.canvas.azimuth,self.canvas.elevation,self.canvas.zoom),camera)
        np.testing.assert_array_equal(self.widget.data[2],original)


if __name__=='__main__':unittest.main()
