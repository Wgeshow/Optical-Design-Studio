"""The reference-styled diagram keeps real dimensions and applied geometry."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import unittest
from types import SimpleNamespace
import pandas as pd
from PyQt6.QtWidgets import QApplication
from qt_lattice_diagram import LatticeDiagram,region_path
from model import PAT_COLS


class LatticeDiagramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.store=SimpleNamespace(settings={'ax_um':.54,'ay_um':.54},patterns=pd.DataFrame([
            ['circle','Silicon','Air',0.,0.,.1,0.,0.],
            ['ellipse','Other','Air',0.,0.,.08,.04,30.]],columns=PAT_COLS))
        self.diagram=LatticeDiagram()

    def tearDown(self):self.diagram.deleteLater();self.app.processEvents()

    def test_applied_layer_replicas_and_dimensions_never_change_model(self):
        original=self.store.patterns.copy(deep=True);settings=copy.deepcopy(self.store.settings)
        self.diagram.set_model(self.store,'Silicon')
        self.assertEqual(len(self.diagram.copies),9)
        self.assertAlmostEqual(self.diagram.dimensions[0]['value_um'],.2)
        self.assertAlmostEqual(self.diagram.dimensions[1]['value_um'],1.08)
        self.assertEqual(self.diagram.dimensions[1]['label'],'2a')
        for width in (180,244,380):
            self.diagram.resize(width,178)
            transform,scale=self.diagram._mapping()
            self.assertAlmostEqual(transform.m11(),-transform.m22())
            self.assertGreater(scale,0)
            self.assertFalse(self.diagram.grab().isNull())
        self.assertTrue(self.store.patterns.equals(original));self.assertEqual(self.store.settings,settings)

    def test_rectangular_periods_and_full_width_convention(self):
        self.store.settings['ay_um']=.8
        self.store.patterns.iloc[0]=['rectangle','Silicon','Air',0.,0.,.16,.06,0.]
        self.diagram.set_model(self.store,'Silicon')
        self.assertEqual([d['label'] for d in self.diagram.dimensions],['wₓ','2aₓ','aᵧ'])
        self.assertAlmostEqual(self.diagram.dimensions[0]['value_um'],.16)
        self.assertAlmostEqual(self.diagram.dimensions[2]['value_um'],.8)
        bounds=region_path(self.diagram.patterns[0],(0.,0.)).boundingRect()
        self.assertAlmostEqual(bounds.width(),.16);self.assertAlmostEqual(bounds.height(),.06)

    def test_unpatterned_or_invalid_layer_never_shows_false_dimensions(self):
        self.diagram.set_model(self.store,'Substrate')
        self.assertEqual(self.diagram.copies,[]);self.assertEqual(self.diagram.dimensions,[])
        self.store.settings['ax_um']=0
        self.diagram.set_model(self.store,'Silicon')
        self.assertTrue(self.diagram.error);self.assertEqual(self.diagram.copies,[])


if __name__=='__main__':unittest.main()
