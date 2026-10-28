"""Imported optical assignments survive full finite-editor Apply operations."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QCoreApplication,QEvent
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from device_model import from_optical_project
from qt_core import ProjectStore
from qt_custom_device import CustomDevicePage


class OpticalAssignmentPreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='optical-assignment-')
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.guard=patch.object(self.store,'start_run',side_effect=AssertionError('No solver/job permitted'))
        self.guard.start()
        project=self.store.project()
        project['materials']=[dict(Name=name,Model='constant_nk',A=index,B=0.,DataFile='',WavelengthUnit='nm')
            for name,index in [('Air',1.),('Slab_n1p5',1.5),('Insert_n2',2.)]]
        project['layers']=[dict(Name=name,Thickness_um=thickness,Material=material)
            for name,thickness,material in [('Incident',0.,'Air'),('Slab',.5,'Slab_n1p5'),('Exit',0.,'Air')]]
        project['patterns']=[dict(Shape='circle',Layer='Slab',Material='Insert_n2',CenterX_um=0.,CenterY_um=0.,
            SizeX_um=.1,SizeY_um=0.,Angle_deg=0.)]
        project['settings'].update(ax_um=1.,ay_um=1.)
        project.pop('simulation_documents',None)
        project['device']=from_optical_project(project,self.store.electrical_materials)
        self.store.load_project(project,autosave=False)
        self.page=CustomDevicePage(self.store)
        self.layer=self.store.device['layers'][0]['id']
        self.shape=self.store.device['shapes'][0]['id']

    def tearDown(self):
        self.page.close();self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.guard.stop();self.temp.cleanup()

    def test_unchanged_apply_preserves_optical_only_layer_and_tables(self):
        self.page.select_object(self.layer)
        self.assertEqual(self.page.material_edit.currentData(),'')
        self.assertEqual(self.page.material_edit.currentText(),'No electrical material assigned')
        self.assertEqual(self.page.optical_assignment.currentData(),'Slab_n1p5')
        before=copy.deepcopy(self.store.device)
        materials=self.store.materials.copy(deep=True)
        layers=self.store.layers.copy(deep=True)
        self.assertTrue(self.page.apply_inspector())
        self.assertEqual(self.store.device,before)
        self.assertTrue(self.store.materials.equals(materials))
        self.assertTrue(self.store.layers.equals(layers))
        self.assertNotIn('__optical_unassigned_gaas',set(self.store.materials.Name))

    def test_thickness_edit_does_not_assign_electrical_material_or_replace_index(self):
        self.page.select_object(self.layer)
        self.page.thickness_edit.setValue(.6)
        self.assertTrue(self.page.apply_inspector())
        row=self.store.device['layers'][0]
        self.assertEqual(row['material_id'],'')
        self.assertEqual(row['optical_material_name'],'Slab_n1p5')
        self.assertEqual(row['thickness_um'],.6)
        slab=self.store.layers.loc[self.store.layers.Name=='Slab'].iloc[0]
        self.assertEqual(slab.Material,'Slab_n1p5')
        self.assertEqual(self.store.materials.loc[self.store.materials.Name=='Slab_n1p5','A'].iloc[0],1.5)

    def test_unchanged_shape_apply_preserves_its_optical_material(self):
        self.page.select_object(self.shape)
        self.assertEqual(self.page.material_edit.currentData(),'')
        self.assertEqual(self.page.optical_assignment.currentData(),'Insert_n2')
        before=copy.deepcopy(self.store.device['shapes'][0])
        patterns=self.store.patterns.copy(deep=True)
        self.assertTrue(self.page.apply_inspector())
        self.assertEqual(self.store.device['shapes'][0],before)
        self.assertTrue(self.store.patterns.equals(patterns))

    def test_explicit_optical_assignment_change_is_committed(self):
        self.page.select_object(self.layer)
        self.page.optical_assignment.setCurrentIndex(self.page.optical_assignment.findData('Insert_n2'))
        self.assertTrue(self.page.apply_inspector())
        self.assertEqual(self.store.device['layers'][0]['material_id'],'')
        self.assertEqual(self.store.device['layers'][0]['optical_material_name'],'Insert_n2')
        self.assertEqual(self.store.layers.loc[self.store.layers.Name=='Slab','Material'].iloc[0],'Insert_n2')

    def test_explicit_electrical_material_selection_still_changes_assignment(self):
        self.page.select_object(self.layer)
        self.page.material_edit.setCurrentIndex(self.page.material_edit.findData('silicon'))
        self.assertTrue(self.page.apply_inspector())
        self.assertEqual(self.store.device['layers'][0]['material_id'],'silicon')


if __name__=='__main__':unittest.main()
