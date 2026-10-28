"""Shared sweep drafts restore all parameters without leaking prior projects."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import pandas as pd
from PyQt6.QtCore import QObject,pyqtSignal
from PyQt6.QtWidgets import QApplication
from linked_hole_sweep import make_widget
APP=QApplication.instance() or QApplication([])
class Store(QObject):
    changed=pyqtSignal(str)
    def __init__(self):
        super().__init__()
        self.materials=pd.DataFrame([dict(Name='Air',Model='constant_nk',A=1,B=0)])
        self.patterns=pd.DataFrame([dict(Shape='circle',Material='Air',Layer='Layer',CenterX_um=x,CenterY_um=0) for x in [0,1]])
class SharedHoleRestoreTests(unittest.TestCase):
    def setUp(self):self.store=Store();self.widget=make_widget(self.store)
    def tearDown(self):self.widget.close();self.widget.deleteLater();APP.processEvents()
    def test_new_draft_resets_limits_and_selection_in_current_units(self):
        self.widget.restore(dict(enabled=True,min_um=.123,max_um=.321,step_um=.004,targets=[2]))
        self.widget.unit.setCurrentIndex(1)
        self.widget.restore({})
        self.assertEqual(self.widget.options(),dict(enabled=False,min_um=.05,max_um=.15,step_um=.025,targets=[1,2]))
        self.assertEqual(self.widget.unit.currentIndex(),1)
    def test_explicit_empty_selection_and_saved_bounds_roundtrip(self):
        saved=dict(enabled=True,min_um=.123,max_um=.321,step_um=.004,targets=[])
        self.widget.restore(saved);self.assertEqual(self.widget.options(),saved)
        self.widget.restore({});self.widget.restore(saved)
        self.assertEqual(self.widget.options(),saved)
if __name__=='__main__':unittest.main()
