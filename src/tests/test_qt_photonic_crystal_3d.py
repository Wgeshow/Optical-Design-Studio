"""Actual geometry and native interaction checks for the independent 3D crystal."""
import copy
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from qt_photonic_crystal_3d import PhotonicCrystal3D, crystal_scene, primitive_mesh

APP = QApplication.instance() or QApplication([])


def crystal():
    return dict(dimension=3,lattice_vectors=[[1.,.2,.1],[.1,1.2,.3],[.2,.1,1.1]],
        background_epsilon=1.,geometry=[dict(id='sphere-one',name='Sphere',shape='sphere',center=[0.,0.,0.],radius=.2,epsilon=8.)])


class CrystalGeometryTests(unittest.TestCase):
    def test_sphere_surface_has_physical_radius_and_outward_normals(self):
        item=dict(shape='sphere',center=[.3,-.1,.2],radius=.4)
        original=copy.deepcopy(item); faces,wires=primitive_mesh(item)
        np.testing.assert_allclose(np.linalg.norm(faces-np.asarray(item['center']),axis=2),.4,atol=1e-14)
        normals=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
        self.assertTrue(np.all(np.sum(normals*(faces.mean(axis=1)-item['center']),axis=1)>0))
        self.assertFalse(faces.flags.writeable); self.assertEqual(item,original)
        self.assertEqual(len(wires),3)

    def test_tilted_cylinder_retains_radius_height_center_and_axis(self):
        axis=np.asarray([1.,2.,3.]); axis/=np.linalg.norm(axis)
        center=np.asarray([.1,.2,-.3])
        faces,wires=primitive_mesh(dict(shape='cylinder',center=center,axis=axis,radius=.17,height=.9))
        points=np.concatenate(wires[:2])-center
        along=points@axis
        np.testing.assert_allclose(abs(along),.45,atol=1e-14)
        np.testing.assert_allclose(np.linalg.norm(points-along[:,None]*axis,axis=1),.17,atol=1e-14)
        self.assertEqual(len(faces),96)

    def test_skew_block_uses_unit_directions_and_exact_3d_edge_sizes(self):
        axes=np.asarray([[1.,0.,1.],[0.,2.,2.],[3.,3.,0.]])
        faces,wires=primitive_mesh(dict(shape='block',center=[.1,.2,.3],axes=axes,size=[.2,.4,.6]))
        self.assertEqual(faces.shape,(12,3,3)); self.assertEqual(len(wires),12)
        lengths=sorted(round(float(np.linalg.norm(edge[1]-edge[0])),12) for edge in wires)
        self.assertEqual(lengths,[.2]*4+[.4]*4+[.6]*4)
        self.assertEqual(len(np.unique(faces.reshape(-1,3),axis=0)),8)
        np.testing.assert_allclose(np.unique(faces.reshape(-1,3),axis=0).mean(axis=0),[.1,.2,.3])

    def test_skew_cell_and_periodic_copies_use_real_lattice_translation(self):
        cfg=crystal(); original=copy.deepcopy(cfg)
        one=crystal_scene(cfg); repeated=crystal_scene(cfg,3)
        self.assertEqual(len(one['cell_edges']),12); self.assertEqual(len(repeated['cells']),27)
        base=next(row for row in repeated['meshes'] if row['image']==(0,0,0))
        adjacent=next(row for row in repeated['meshes'] if row['image']==(1,-1,1))
        translation=np.asarray([1,-1,1])@np.asarray(cfg['lattice_vectors'])
        np.testing.assert_allclose(adjacent['faces']-base['faces'],np.broadcast_to(translation,base['faces'].shape),atol=1e-14)
        self.assertEqual(adjacent['id'],base['id']); self.assertEqual(cfg,original)
        self.assertEqual(len(crystal_scene(cfg,2)['cells']),8)

    def test_preview_preflight_rejects_degenerate_geometry_without_runtime_requirement(self):
        cfg=crystal(); cfg.update(runtime={'executable':''},num_bands='unfinished')
        self.assertEqual(crystal_scene(cfg)['primitive_count'],1)
        for update in [dict(lattice_vectors=[[1,0,0],[0,1,0],[0,0,0]]),dict(dimension=2),
                       dict(geometry=[dict(shape='cylinder',axis=[0,0,0],height=1,radius=.2,epsilon=2)])]:
            with self.subTest(update=update),self.assertRaises(ValueError):
                crystal_scene(dict(cfg,**update))


class CrystalInteractionTests(unittest.TestCase):
    def setUp(self):
        self.widget=PhotonicCrystal3D(); self.widget.resize(640,500); self.widget.show()
        self.widget.set_crystal(crystal()); APP.processEvents()

    def tearDown(self):
        self.widget.close(); self.widget.deleteLater(); APP.processEvents()

    def test_upward_z_presets_and_equal_physical_axis_scale(self):
        w=self.widget; w.set_standard_view('front')
        xy,_=w.project(np.asarray([[0,0,0],[0,0,.1],[.1,0,0]]))
        self.assertLess(xy[1,1],xy[0,1])
        self.assertAlmostEqual(np.linalg.norm(xy[1]-xy[0]),np.linalg.norm(xy[2]-xy[0]))
        w.set_standard_view('top'); xy,_=w.project(np.asarray([[0,0,0],[.1,0,0],[0,.1,0]]))
        self.assertGreater(xy[1,0],xy[0,0]); self.assertLess(xy[2,1],xy[0,1])

    def test_click_selects_authoritative_id_orbit_pan_zoom_do_not_edit_geometry(self):
        w=self.widget; original=copy.deepcopy(w._cfg); selected=[]; w.objectSelected.connect(selected.append)
        center,_=w.project(np.asarray([0.,0.,0.])); point=QPoint(round(center[0]),round(center[1]))
        self.assertEqual(w.pick_object(point),'sphere-one')
        QTest.mouseClick(w,Qt.MouseButton.LeftButton,pos=point)
        self.assertEqual(selected,['sphere-one'])
        azimuth=w.azimuth
        QTest.mousePress(w,Qt.MouseButton.LeftButton,pos=point)
        self.assertTrue(w.fast)
        QTest.mouseMove(w,point+QPoint(40,10)); QTest.mouseRelease(w,Qt.MouseButton.LeftButton,pos=point+QPoint(40,10))
        self.assertFalse(w.fast)
        self.assertNotEqual(w.azimuth,azimuth); self.assertEqual(selected,['sphere-one'])
        QTest.mousePress(w,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,pos=point)
        QTest.mouseMove(w,point+QPoint(12,8)); QTest.mouseRelease(w,Qt.MouseButton.LeftButton,pos=point+QPoint(12,8))
        self.assertNotEqual(w.pan,QPointF())
        event=QWheelEvent(QPointF(point),QPointF(w.mapToGlobal(point)),QPoint(),QPoint(0,120),
            Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        QApplication.sendEvent(w,event); self.assertGreater(w.zoom,1.)
        self.assertEqual(w._cfg,original)
        w.reset_camera(); self.assertEqual(w.zoom,1.); self.assertEqual(w.pan,QPointF())

    def test_invalid_draft_keeps_last_valid_scene_and_repeat_is_display_only(self):
        w=self.widget; before=w.scene; original=copy.deepcopy(w._cfg)
        invalid=crystal(); invalid['geometry'][0]['radius']='unfinished'
        with self.assertRaises(ValueError):w.set_crystal(invalid)
        self.assertIs(w.scene,before); self.assertEqual(w._cfg,original)
        w.set_repeat(3); self.assertEqual(len(w.scene['meshes']),27); self.assertEqual(w._cfg,original)
        w.set_selected('sphere-one'); self.assertEqual(w.selected_id,'sphere-one')
        w.clear(); self.assertIsNone(w.scene); self.assertIsNone(w.model)


if __name__=='__main__':unittest.main()
