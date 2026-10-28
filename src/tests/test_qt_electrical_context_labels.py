"""Electrical setup labels and notices describe the active independent study."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import pandas as pd
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QLabel
from data_library import DataLibrary
from device_model import default_device
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace
from qt_app import OpticalStudio


class ElectricalContextLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def owner(self, device=None):
        store = SimpleNamespace(device=device, layers=pd.DataFrame({'Name':['Top','Legacy slab','Bottom']}), patterns=[], settings=dict(ax_um=.77, ay_um=.77))
        notice = Mock(title_label=QLabel('Simulation structure updated'), summary=QLabel())
        return SimpleNamespace(store=store, _structure_snapshot='before', structure_signature=lambda:'after', structure_notice=notice, position_structure_notice=Mock())

    def test_notice_summarizes_finite_device_instead_of_stale_optical_tables(self):
        device = dict(width_um=2., depth_um=3., layers=[dict(id='a',name='P layer',enabled=True),dict(id='b',name='N layer',enabled=True),dict(id='off',name='Disabled',enabled=False)], shapes=[dict(layer_id='a',enabled=True),dict(layer_id='b',enabled=False),dict(layer_id='off',enabled=True)])
        owner = self.owner(device)
        OpticalStudio.structure_changed(owner, 'device')
        self.assertIn('2 finite layers · 1 regions · 2 × 3 µm',owner.structure_notice.summary.text())
        self.assertNotIn('.77',owner.structure_notice.summary.text())
        owner.structure_notice.setToolTip.assert_called_once_with('P layer → N layer')
        self.assertEqual(owner.store.device,device)

    def test_legacy_optical_notice_still_summarizes_its_tables(self):
        owner = self.owner()
        OpticalStudio.structure_changed(owner, 'structure')
        self.assertIn('1 finite layers · 0 regions · 0.77 × 0.77 µm',owner.structure_notice.summary.text())

    def test_study_switch_updates_snapshot_without_claiming_an_edit(self):
        owner = self.owner()
        OpticalStudio.structure_changed(owner, 'study')
        self.assertEqual(owner._structure_snapshot,'after')
        owner.structure_notice.dismiss.assert_called_once()
        owner.structure_notice.show.assert_not_called()
        owner.structure_notice.timer.start.assert_not_called()
        owner.position_structure_notice.assert_not_called()

    def test_study_switch_does_not_dismiss_unrelated_completion_notice(self):
        owner = self.owner()
        owner.structure_notice.title_label.setText('Electrical simulation complete')
        OpticalStudio.structure_changed(owner, 'study')
        owner.structure_notice.dismiss.assert_not_called()
        owner.structure_notice.show.assert_not_called()

    def test_cached_iv_cv_plot_titles_are_restored_after_returning_from_device_editor(self):
        with tempfile.TemporaryDirectory(prefix='electrical-labels-') as folder:
            store = ProjectStore(DataLibrary(Path(folder)/'library'), restore=False)
            for identity,title in [('electrical.iv','Current–voltage experiment'),('electrical.cv','Electrode charge → electrostatic capacitance')]:
                with self.subTest(study=identity), patch.object(store,'start_run',side_effect=AssertionError('No solver/job permitted')):
                    store.activate_study(identity)
                    store.set_device(default_device(store.electrical_materials))
                    page = SimulationSetupWorkspace(store, mode='electrical', document_id=identity)
                    try:
                        flow=page.setup_flow
                        before=copy.deepcopy(store.device)
                        flow.show_stage(1)
                        self.assertEqual(flow.scene_caption.text(),title)
                        preview=flow.curve_preview
                        flow.show_stage(0)
                        self.assertIn('geometry',flow.scene_caption.text())
                        flow.show_stage(1)
                        self.assertIs(flow.curve_preview,preview)
                        self.assertEqual(flow.scene_caption.text(),title)
                        self.assertEqual(store.device,before)
                        note=flow.device_editor.editor.electrical_model_note.text()
                        self.assertIn('Bias & physics',note)
                        self.assertNotIn('Current transport is not solved',note)
                        self.assertNotIn('uses static',note)
                    finally:
                        page.close();page.deleteLater()
                        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
                        self.app.processEvents()


if __name__=='__main__':
    unittest.main()
