"""Calculated laser results keep their inputs and never cross project boundaries."""
import copy
import os
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QCoreApplication,QEvent
from PyQt6.QtWidgets import QApplication
from comsol_results import ComsolPowerResults,ResultColumn
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel import PCSELPage,_PCSELPlot


class LaserResultSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='laser-result-snapshot-')
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.store.study_navigation_enabled=True
        self.store.activate_study('lumped_laser')
        self.stack=ExitStack()
        self.solve=self.stack.enter_context(patch('qt_pcsel.solve_laser',side_effect=AssertionError('No numerical solver permitted.')))
        self.page=PCSELPage(self.store)
        for name in ('plot_dashboard','plot_mode','plot_laser','plot_modulation','plot_thermal','plot_sensitivity','retheme'):
            self.stack.enter_context(patch.object(self.page,name))

    def tearDown(self):
        self.page.close();self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.stack.close();self.temp.cleanup()

    def calculate_fixture(self):
        # Marked controller data only; these numbers are not physical outputs.
        result=dict(currents_ma=[0.,150.],output_power_mw=[0.,1.],
            photon_lifetime_ps=777.,threshold_current_ma=1.,slope_efficiency_w_per_a=1.,
            **{'threshold_gain_cm-1':1.,'threshold_density_cm-3':1.})
        self.solve.side_effect=[result,{'modulation':{}}]
        self.page.run_simulation()
        self.assertEqual(self.solve.call_count,2)
        self.solve.side_effect=AssertionError('Import, navigation and restore must not run a solver.')
        return result

    def overlay(self):
        return ComsolPowerResults(Path('SYNTHETIC-NOT-SOLVER.json'),
            {'model_name':'Synthetic controller fixture','study':'No physical calculation'},
            (ResultColumn('i','current','A'),ResultColumn('p','optical_power','W')),
            ({'i':0.,'p':0.},{'i':.15,'p':.001}))

    def import_overlay(self):
        imported=self.overlay()
        with patch('qt_pcsel.load_comsol_power_results',return_value=imported):
            self.page.import_comsol('SYNTHETIC-NOT-SOLVER.json')
        return imported

    def test_overlay_report_uses_completed_snapshot_after_controls_change(self):
        result=self.calculate_fixture()
        original_geometry=result['report_context']['geometry']
        self.page.quality_factor.setValue(84000.)
        self.page.wavelength.setValue(1600.)
        self.page.confinement.setValue(.35)
        self.page.mode_volume.setValue(99.)
        self.page.pc_layer.clear()
        self.import_overlay()
        report=self.page.report.toPlainText()
        self.assertIn('Q: 42000\n',report)
        self.assertIn('Target wavelength: 1550 nm',report)
        self.assertIn('Confinement: 0.22\n',report)
        self.assertIn('Mode volume: 2.8 ',report)
        self.assertIn('Photon lifetime: 777 ps',report)
        self.assertIn(original_geometry,report)
        self.assertIn('INPUTS CHANGED',report)
        self.assertIn('COMSOL IMPORT',report)
        self.assertEqual(self.solve.call_count,2)

    def test_export_without_overlay_marks_previous_inputs_after_edit(self):
        self.calculate_fixture()
        self.page.quality_factor.setValue(84000.)
        target=Path(self.temp.name)/'report.txt'
        self.page.export_report(target)
        report=target.read_text(encoding='utf-8')
        self.assertIn('INPUTS CHANGED',report)
        self.assertIn('Q: 42000\n',report)
        self.assertNotIn('Q: 84000\n',report)

    def test_project_restore_clears_old_results_plots_and_overlay(self):
        self.calculate_fixture();self.import_overlay()
        draft=copy.deepcopy(self.page._default_draft)
        draft['controls']['quality_factor']=1000.
        self.store.search_state['research_workspaces']={'schema_version':1,'lumped_laser':draft}
        with patch.object(_PCSELPlot,'clear') as clear:
            self.page._project_draft_changed('project')
        self.assertIsNone(self.page.last_result)
        self.assertIsNone(self.page._comsol_imported)
        self.assertEqual(self.page.quality_factor.value(),1000.)
        self.assertEqual(clear.call_count,len(self.page.findChildren(_PCSELPlot)))
        self.assertNotIn('COMSOL IMPORT',self.page.report.toPlainText())
        self.assertNotIn('777',self.page.report.toPlainText())
        self.assertIn('No laser simulation',self.page.report.toPlainText())
        self.assertEqual(self.page.mode_table.rowCount(),0)
        self.assertEqual(self.solve.call_count,2)

    def test_normal_study_switch_retains_own_results_and_controls(self):
        self.page.quality_factor.setValue(50000.)
        self.calculate_fixture();imported=self.import_overlay()
        result=self.page.last_result
        self.page.flush_draft()
        self.store.activate_study('pcsel.vertical')
        self.assertEqual(self.page.quality_factor.value(),50000.)
        self.assertIs(self.page.last_result,result)
        self.store.activate_study('lumped_laser')
        self.assertEqual(self.page.quality_factor.value(),50000.)
        self.assertIs(self.page.last_result,result)
        self.assertIs(self.page._comsol_imported,imported)
        self.assertEqual(self.solve.call_count,2)

    def test_project_replacement_while_inactive_also_clears_cached_result(self):
        self.calculate_fixture();self.import_overlay()
        self.store.activate_study('pcsel.vertical')
        with patch.object(_PCSELPlot,'clear'):
            self.page._project_draft_changed('project')
        self.assertIsNone(self.page.last_result)
        self.assertIsNone(self.page._comsol_imported)
        self.assertFalse(self.page._results_stale)

    def test_manual_reopen_of_same_project_does_not_retain_stale_result(self):
        self.calculate_fixture();self.import_overlay()
        self.page.quality_factor.setValue(84000.)
        self.page.flush_draft()
        project=self.store.project()
        with patch.object(_PCSELPlot,'clear'):
            self.store.load_project(project,autosave=False)
        self.assertIsNone(self.page.last_result)
        self.assertIsNone(self.page._comsol_imported)
        self.assertFalse(self.page._results_stale)
        self.assertEqual(self.page.quality_factor.value(),84000.)
        self.assertNotIn('777',self.page.report.toPlainText())

    def test_explicit_rerun_replaces_snapshot_and_clears_stale_warning(self):
        self.calculate_fixture()
        self.page.quality_factor.setValue(84000.)
        self.solve.reset_mock()
        result=self.calculate_fixture()
        self.assertEqual(result['inputs']['quality_factor'],84000.)
        self.assertIn('Q: 84000\n',self.page.report.toPlainText())
        self.assertNotIn('INPUTS CHANGED',self.page.report.toPlainText())
        self.assertFalse(self.page._results_stale)


if __name__=='__main__':unittest.main()
