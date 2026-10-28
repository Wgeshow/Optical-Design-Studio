"""Journey controls reach real requests, exact inspectors and owned jobs."""
import copy
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from data_library import DataLibrary
from device_model import default_device
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace
from qt_sesame_setup import SesameSetupWorkspace
from qt_thermal_setup import ThermalSetupWorkspace

APP = QApplication.instance() or QApplication([])


class ElectricalJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='journey-bindings-', dir=Path.cwd())
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.pages = []

    def tearDown(self):
        for p in self.pages:
            if hasattr(p, '_save_timer'): p._save_timer.stop()
            p.close(); p.deleteLater()
        APP.processEvents(); self.temp.cleanup()

    def canonical(self, identity='electrical'):
        self.store.activate_study(identity)
        self.store.set_device(default_device(self.store.electrical_materials))
        p = SimulationSetupWorkspace(self.store, mode='coupled' if identity=='coupled' else 'electrical', document_id=identity)
        self.pages.append(p); p.resize(1350, 850); p.show(); APP.processEvents()
        return p

    def research(self, cls):
        p=cls(self.store); self.pages.append(p)
        p.resize(1050, 820); p.show(); QTest.qWait(140)
        return p

    def test_inline_layer_apply_changes_authoritative_request_and_preserves_other_study(self):
        p=self.canonical(); identity=self.store.device['layers'][0]['id']
        optical=copy.deepcopy(self.store.study_project('optical'))
        self.assertTrue(p.setup_flow.open_device_editor(identity))
        editor=p.setup_flow.device_editor.editor
        thickness=self.store.device['layers'][0]['thickness_um']*1.5
        editor.thickness_edit.setValue(thickness)
        self.assertTrue(editor.apply_inspector())
        self.assertAlmostEqual(p.options()['device']['layers'][0]['thickness_um'],thickness)
        self.assertEqual(self.store.study_project('optical'),optical)
        self.store.activate_study('electrical.cv'); APP.processEvents()
        self.assertFalse(p.setup_flow.device_editor.isEnabled())
        self.assertFalse(p.setup_flow.device_editor.open_editor(identity))

    def test_iv_cv_layouts_use_correct_axes_and_keep_native_fields(self):
        for identity,axes in [('electrical.iv',1),('electrical.cv',2)]:
            p=self.canonical(identity); controls={key:tuple(value) for key,value in p.widgets_by_key.items()}
            p.setup_flow.show_stage(1)
            self.assertEqual(len(p.setup_flow.curve_preview.figure.axes),axes)
            for i in (2,3,4,5,0):
                p.setup_flow.show_stage(i); APP.processEvents()
            self.assertEqual({key:tuple(value) for key,value in p.widgets_by_key.items()},controls)
            self.assertIsNone(p.setup_flow.result_dashboard)
            self.assertFalse(p.setup_flow.open_result_button.isEnabled())

    def test_inline_continue_preserves_unapplied_draft_and_forwards_validation_status(self):
        p=self.canonical(); identity=self.store.device['layers'][0]['id']
        p.setup_flow.open_device_editor(identity)
        host=p.setup_flow.device_editor; editor=host.editor
        before=copy.deepcopy(self.store.device)
        editor.donor_edit.setText('1e-')
        with patch.object(self.store,'start_run') as start:
            editor.continue_requested.emit(); APP.processEvents()
            self.assertEqual(p.setup_flow.journey_bar._current,1)
            self.assertEqual(self.store.device,before)
            start.assert_not_called()
        p.setup_flow.open_device_editor(identity)
        self.assertEqual(editor.donor_edit.text(),'1e-')
        self.assertFalse(editor.apply_inspector())
        self.assertIn('Could not apply',host.message.text())
        self.assertTrue(host.message.isVisible())

    def test_legacy_periodic_continue_reaches_optical_conditions_without_applying(self):
        p=SimulationSetupWorkspace(self.store,mode='optical')
        self.pages.append(p); p.resize(1350,850); p.show(); APP.processEvents()
        p.setup_flow.open_device_editor('device')
        editor=p.setup_flow.device_editor.editor
        self.assertIsNotNone(editor._legacy)
        before=copy.deepcopy(self.store.portable_project())
        with patch.object(self.store,'start_run') as start:
            editor._legacy.continue_requested.emit(); APP.processEvents()
            self.assertEqual(p.setup_flow.journey_bar._current,1)
            self.assertEqual(self.store.portable_project(),before)
            start.assert_not_called()

    def test_actual_progress_and_cancel_are_owned_by_initiating_workspace(self):
        p=self.canonical(); flow=p.setup_flow
        self.store._set_busy(True)
        with patch.object(self.store,'cancel') as cancel:
            flow._cancel(); cancel.assert_not_called()
        self.store._set_busy(False)
        flow._run_requested('electrical'); self.store._worker=SimpleNamespace(kind='electrical'); self.store._set_busy(True)
        self.store.progress.emit(dict(kind='log',text='Actual test worker event'))
        self.assertIn('Actual test worker event',flow.run_log.toPlainText())
        with patch.object(self.store,'cancel') as cancel:
            flow._cancel(); cancel.assert_called_once()
        self.store.run_finished.emit(dict(summary=dict(status='partial')))
        self.assertIn('partial',flow.run_state.text())
        self.assertEqual(flow.extra_stage,5)
        self.store._set_busy(False)

    def test_rejected_submission_cannot_claim_an_unrelated_job(self):
        p=self.canonical(); flow=p.setup_flow
        flow._run_requested('electrical')
        APP.processEvents()
        self.assertFalse(flow._pending_run)
        self.store._worker=SimpleNamespace(kind='research_simulation')
        self.store._set_busy(True)
        self.assertFalse(flow._owns_run)
        self.assertFalse(flow.stop_button.isEnabled())
        with patch.object(self.store,'cancel') as cancel:
            flow._cancel(); cancel.assert_not_called()
        self.store._set_busy(False)

    def test_destroyed_flow_disconnects_worker_signals_and_pending_submission(self):
        from PyQt6 import sip
        p=self.canonical(); p.setup_flow._run_requested('electrical')
        self.pages.remove(p)
        errors=[]
        with patch.object(sys,'excepthook',lambda kind,error,traceback: errors.append(str(error))):
            sip.delete(p)
            self.store.busy_changed.emit(False)
            self.store.progress.emit(dict(kind='log',text='Unrelated later job'))
            APP.processEvents()
        self.assertEqual(errors,[])

    def test_thermal_face_controls_and_layer_hit_reveal_exact_existing_inspector(self):
        p=self.research(ThermalSetupWorkspace)
        self.assertTrue(p.select_cooling_face('z_max'))
        self.assertEqual(p.boundaries.currentRow(),5)
        kind=p.boundary_inspector.editors['kind']
        kind.setCurrentIndex(kind.findData('convection'))
        p.boundary_inspector.editors['coefficient_W_m2K'].setText('1234')
        self.assertEqual(p.boundaries.item(5,3).text(),'1234')
        first=self.store.device['layers'][0]
        p._select_heated_layer(SimpleNamespace(ydata=first['thickness_um']/2))
        self.assertEqual(p.powers.currentRow(),0)
        self.assertIs(APP.focusWidget(),p.power_inspector.editors['power'])

    def test_sesame_geometry_hit_keeps_separate_rectilinear_domain(self):
        p=self.research(SesameSetupWorkspace)
        finite=copy.deepcopy(self.store.device)
        p._select_domain_geometry(SimpleNamespace(xdata=.5,ydata=.5))
        self.assertEqual(p.regions.currentRow(),0)
        self.assertIs(APP.focusWidget(),p.inspectors['regions'].editors['material'])
        p.inspectors['regions'].editors['donors_cm3'].setText('2.25e15')
        self.assertEqual(p.regions.item(0,4).text(),'2.25e15')
        p._select_domain_geometry(SimpleNamespace(xdata=1.,ydata=.5))
        self.assertEqual(p.contacts.currentRow(),1)
        self.assertEqual(self.store.device,finite)


if __name__ == '__main__': unittest.main()
