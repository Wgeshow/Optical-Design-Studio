"""Rendered aperture pixels reveal lower geometry during orbit and zoom."""
import os,math,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication
from qt_device_builder import GeometryViewport

class GeometryApertureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.view=GeometryViewport();self.view.resize(680,640);self.view.show();self.view.cells=1;self.view.ax=self.view.ay=.54
        self.view.layers=[dict(Name='Air',Material='Air',Thickness_um=0),dict(Name='Patterned semiconductor',Material='GaAs',Thickness_um=.08),dict(Name='Lower layer',Material='SiC',Thickness_um=0)]
        self.view.patterns=[dict(layer='Patterned semiconductor',material='Air',shape='circle',cx=0,cy=0,sx=.24,sy=.24,angle=0)]
        self.view.hidden_layers={'Air'};self.view.show_axes=False
    def tearDown(self):self.view.close();self.view.deleteLater();self.app.processEvents()
    def test_lower_layer_color_is_visible_through_opening_at_multiple_angles(self):
        for angle in (-math.pi/4,0,math.pi/3,math.pi):
            self.view.angle=angle;self.view.elevation=.7;self.view.layer_colors={'Lower layer':'#00ff00'};first=self.view.grab().toImage()
            aperture=self.view.aperture_paths[0][1];self.assertFalse(aperture.isEmpty())
            self.view.layer_colors={'Lower layer':'#ff00ff'};second=self.view.grab().toImage()
            bounds=aperture.boundingRect();changed=0
            for y in range(int(bounds.top())+2,int(bounds.bottom())-2,2):
                for x in range(int(bounds.left())+2,int(bounds.right())-2,2):
                    if aperture.contains(QPointF(x,y)) and first.pixel(x,y)!=second.pixel(x,y):changed+=1
            self.assertGreater(changed,4,f'Lower geometry hidden at angle {angle}')
    def test_labels_remain_inside_view_at_extreme_zoom_and_orbit(self):
        for angle in (-2,0,2):
            for zoom in (.55,1.5):
                self.view.angle=angle;self.view.zoom=zoom;self.view.elevation=.85;self.view.grab()
                for bounds in self.view.label_bounds:self.assertTrue(self.view.rect().contains(bounds.toAlignedRect()))
                for first,second in zip(self.view.label_bounds,self.view.label_bounds[1:]):self.assertLessEqual(first.bottom(),second.top())

if __name__=='__main__':unittest.main()
