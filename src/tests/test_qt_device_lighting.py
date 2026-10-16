"""Live preview lighting must preserve the editable physical device."""
import copy
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from device_model import default_device, validate_device
from qt_custom_device import DeviceCanvas

APP=QApplication.instance() or QApplication([])


def silicon_fixture():
    device=default_device()
    device['layers']=[dict(id='p',name='p-Si PCS',material_id='silicon',thickness_um=.2,
        donor_cm3=0.,acceptor_cm3=1e17,enabled=True),
        dict(id='n',name='n-Si film',material_id='silicon',thickness_um=.8,
        donor_cm3=1e16,acceptor_cm3=0.,enabled=True)]
    geometry=dict(cx_um=0.,cy_um=0.,size_x_um=1.8,size_y_um=1.8,angle_deg=0.,vertices=[],enabled=True)
    device['contacts']=[dict(geometry,id='P',name='P Au ring',layer_id='p',shape='square_ring',
        inner_size_x_um=1.3,inner_size_y_um=1.3,surface='top',boundary='ohmic',
        voltage_V=0.,bias_scale=1.,optical_material_name='Au',optical_thickness_um=.03),
        dict(geometry,id='N',name='N Au reflector',layer_id='n',shape='rectangle',
        size_x_um=2.,size_y_um=2.,surface='bottom',boundary='ohmic',voltage_V=0.,bias_scale=0.,
        optical_material_name='Au',optical_thickness_um=.1)]
    device['shapes']=[dict(geometry,id=f'h{ix}{iy}',name='Hole',layer_id='p',shape='circle',
        material_id='air',operation='void',cx_um=ix*.45,cy_um=iy*.45,size_x_um=.18,size_y_um=.18)
        for iy in (-1,0,1) for ix in (-1,0,1)]
    return validate_device(device)


class DeviceLightingTests(unittest.TestCase):
    def setUp(self):
        self.device=silicon_fixture()
        self.canvas=DeviceCanvas('3d')
        self.canvas.resize(620,430)
        self.canvas.set_device(self.device)
        self.canvas.show();APP.processEvents()

    def tearDown(self):
        self.canvas.close();self.canvas.deleteLater();APP.processEvents()

    def pixels(self):
        APP.processEvents()
        image=self.canvas.grab().toImage()
        return image.constBits().asstring(image.sizeInBytes())

    def test_lighting_changes_real_render_without_changing_physical_geometry(self):
        before=copy.deepcopy(self.device)
        studio=self.pixels()
        self.canvas.set_render_quality('studio',shadows=False,reflections=False,ambient_occlusion=False)
        unlit=self.pixels()
        self.canvas.set_render_quality('flat')
        flat=self.pixels()
        self.assertNotEqual(studio,unlit)
        self.assertNotEqual(studio,flat)
        self.assertEqual(self.device,before)
        self.assertEqual(len(self.canvas._render_shapes),9)

    def test_rotating_live_canvas_preserves_all_holes_and_contact_ring(self):
        before=self.pixels()
        original_yaw=self.canvas.yaw
        QTest.mousePress(self.canvas,Qt.MouseButton.LeftButton,pos=QPointF(180,130).toPoint())
        QTest.mouseMove(self.canvas,QPointF(225,150).toPoint())
        QTest.mouseRelease(self.canvas,Qt.MouseButton.LeftButton,pos=QPointF(225,150).toPoint())
        self.assertNotEqual(self.canvas.yaw,original_yaw)
        self.assertNotEqual(self.pixels(),before)
        self.assertEqual({obj['id'] for obj in self.canvas._render_shapes},{obj['id'] for obj in self.device['shapes']})
        self.assertTrue(any(object_id=='P' for _,object_id,_ in self.canvas.hits))

    def test_hole_aperture_is_pickable_and_does_not_become_the_gold_ring(self):
        self.pixels()
        aperture=next(path for path,object_id,_ in self.canvas.hits if object_id=='h00')
        hit=self.canvas._hit(aperture.boundingRect().center())
        self.assertEqual(hit,('h00','top'))

    def test_optical_cell_guide_changes_preview_without_changing_device_or_picking(self):
        before=copy.deepcopy(self.device)
        plain=self.pixels()
        count=len(self.canvas.hits)
        self.canvas.optical_unit_cell=dict(enabled=True,width_um=.45,depth_um=.45,cx_um=0.,cy_um=0.)
        self.assertNotEqual(plain,self.pixels())
        self.assertEqual(len(self.canvas.hits),count)
        self.assertEqual(self.device,before)
        aperture=next(path for path,object_id,_ in self.canvas.hits if object_id=='h00')
        self.assertEqual(self.canvas._hit(aperture.boundingRect().center()),('h00','top'))

    def test_polygon_and_edge_cut_holes_are_not_rendered_as_solid_outer_walls(self):
        self.canvas.yaw=-2.
        self.pixels()
        intact=next(path for path,object_id,face in self.canvas.hits if object_id=='p' and face=='side_x_min')
        probe=intact.boundingRect().center()
        self.assertTrue(intact.contains(probe))
        obj=self.device['shapes'][0]
        obj.update(shape='polygon',cx_um=0.,cy_um=0.,vertices=[[-1.2,-.2],[-.7,-.2],[-.7,.2],[-1.2,.2]])
        self.canvas.set_device(validate_device(self.device))
        self.pixels()
        self.assertTrue(any(object_id==obj['id'] for _,object_id,_ in self.canvas.hits))
        self.assertTrue(any(face=='side_x_min' for _,_,face in self.canvas.hits))
        cut=next(path for path,object_id,face in self.canvas.hits if object_id=='p' and face=='side_x_min')
        self.assertFalse(cut.contains(probe))

    def test_quality_and_wireframe_work_in_sidebar_and_linked_orthographic_views(self):
        self.canvas.compact_preview=True;self.canvas.resize(420,255)
        for quality in ('studio','flat'):
            self.canvas.set_render_quality(quality)
            for wireframe in (False,True):
                self.canvas.wireframe=wireframe
                self.pixels()
                self.assertTrue(self.canvas.hits)
        for mode in ('top','section'):
            linked=DeviceCanvas(mode);linked.resize(420,255);linked.set_device(self.device)
            linked.show();APP.processEvents()
            self.assertTrue(linked.hits)
            linked.close();linked.deleteLater()
        with self.assertRaises(ValueError):self.canvas.set_render_quality('unknown')


if __name__=='__main__':
    unittest.main()
