"""Numerical laser exports retain full saved arrays and calculation provenance."""
import copy
import csv
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PyQt6.QtCore import QCoreApplication,QEvent
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel import PCSELPage


class LaserNumericalExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='laser-export-')
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.store.study_navigation_enabled=True;self.store.activate_study('lumped_laser')
        self.stack=ExitStack()
        self.solve=self.stack.enter_context(patch('qt_pcsel.solve_laser',side_effect=AssertionError('No numerical solver permitted.')))
        self.page=PCSELPage(self.store)
        for name in ('plot_dashboard','plot_mode','plot_laser','plot_modulation','plot_thermal','plot_sensitivity','retheme'):
            self.stack.enter_context(patch.object(self.page,name))

    def tearDown(self):
        self.page.close();self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.stack.close();self.temp.cleanup()

    def fixture(self):
        # Synthetic controller values, not numerical laser results.
        self.page.current_points.setValue(3)
        currents=[0.,75.,150.]
        points=[dict(current_ma=current,carrier_density_cm_3=1.0123456789012346e18+i,
            photon_density_cm_3=3.0123456789012345e13+i,output_power_mw=i*1.1234567890123457,
            temperature_k=300.0123456789012+i,wavelength_nm=1550.0123456789012+i,
            wall_plug_efficiency=.12345678901234567,relaxation_frequency_ghz=4.012345678901234+i)
            for i,current in enumerate(currents)]
        result=dict(schema='optical-design-studio/laser-performance/v1',currents_ma=currents,
            output_power_mw=[row['output_power_mw'] for row in points],sweep=points,
            photon_lifetime_ps=34.560531857283706,threshold_current_ma=5.776967701912766,
            slope_efficiency_w_per_a=.5599286380854206,optical={'fixture':'synthetic'},threshold={'fixture':'synthetic'},
            **{'threshold_gain_cm-1':123.12345678901235,'threshold_density_cm-3':1.0631740458199875e18})
        modulation=dict(bias_current_ma=80.,relaxation_frequency_ghz=5.123456789012345,
            damping_rate_ghz=3.123456789012345,frequencies_ghz=list(np.linspace(0,40,501)),
            magnitude_linear=[.9123456789012345]*501,magnitude_db=[-.8123456789012345]*501,bandwidth_3db_ghz=None)
        self.solve.side_effect=[result,{'modulation':modulation}]
        self.page.run_simulation()
        self.solve.side_effect=AssertionError('Export must not calculate or rerun.')
        self.assertEqual(self.solve.call_count,2)
        return self.page.last_result

    def target(self,name):return Path(self.temp.name)/name

    def test_json_keeps_exact_arrays_and_captured_inputs_after_live_edits(self):
        result=self.fixture();snapshot=copy.deepcopy(result)
        self.page.quality_factor.setValue(84000.);self.page.current_max.setValue(175.);self.page.bias_current.setValue(90.)
        target=self.target('result.json');self.assertEqual(self.page.export_result_json(target),target)
        saved=json.loads(target.read_text(encoding='utf-8'))
        for key,value in snapshot.items():self.assertEqual(saved[key],value)
        self.assertEqual(saved['inputs']['quality_factor'],42000.)
        self.assertEqual(saved['calculation_context']['current_sweep'],dict(start_mA=0.,stop_mA=150.,samples=3))
        self.assertEqual(saved['calculation_context']['modulation']['bias_current_mA'],80.)
        self.assertEqual(saved['modulation']['bias_current_ma'],80.)
        self.assertTrue(saved['export_metadata']['inputs_changed_since_calculation'])
        self.assertEqual(saved['export_metadata']['result_status'],'completed_for_previous_inputs')
        self.assertEqual(saved['threshold_current_ma'],5.776967701912766)
        self.assertEqual(self.page.last_result,snapshot)
        self.assertEqual(self.solve.call_count,2)

    def test_current_csv_has_units_exact_values_and_full_result_sidecar(self):
        result=self.fixture();self.page.quality_factor.setValue(84000.)
        target=self.target('current.csv');self.assertEqual(self.page.export_sweep_csv(target),target)
        with target.open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),3)
        self.assertEqual(float(rows[1]['output_power_mW']),result['sweep'][1]['output_power_mw'])
        self.assertEqual(float(rows[2]['carrier_density_cm^-3']),result['sweep'][2]['carrier_density_cm_3'])
        self.assertEqual(rows[0]['inputs_changed_since_calculation'],'true')
        self.assertEqual(rows[0]['result_id'],result['calculation_context']['result_id'])
        self.assertEqual(rows[0]['source_result_json'],'current.result.json')
        sidecar=json.loads(self.target('current.result.json').read_text(encoding='utf-8'))
        self.assertEqual(sidecar['sweep'],result['sweep']);self.assertEqual(sidecar['inputs']['quality_factor'],42000.)
        self.assertEqual(self.solve.call_count,2)

    def test_modulation_csv_uses_its_saved_bias_not_live_control_or_sweep_endpoint(self):
        result=self.fixture();self.page.bias_current.setValue(90.)
        target=self.target('modulation.csv');self.assertEqual(self.page.export_modulation_csv(target),target)
        with target.open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),501)
        self.assertEqual(float(rows[-1]['frequency_GHz']),40.)
        self.assertEqual(float(rows[-1]['bias_current_mA']),80.)
        self.assertEqual(float(rows[123]['magnitude_dB']),result['modulation']['magnitude_db'][123])
        self.assertTrue(self.target('modulation.result.json').is_file())
        self.assertEqual(self.solve.call_count,2)

    def test_export_menu_and_no_result_guard_do_not_start_a_calculation(self):
        button=self.page.result_export_button
        self.assertFalse(button.isEnabled())
        self.assertEqual(len(button.menu().actions()),3)
        self.assertIn('Raw numerical result JSON',button.menu().actions()[0].text())
        target=self.target('missing.json')
        with patch('qt_pcsel.QFileDialog.getSaveFileName',side_effect=AssertionError('No dialog without a result')):
            self.assertIsNone(self.page.export_result_json(target))
            self.assertIsNone(self.page.export_sweep_csv(target))
        self.assertFalse(target.exists());self.solve.assert_not_called()
        self.fixture();self.assertTrue(button.isEnabled())
        self.page._clear_results();self.assertFalse(button.isEnabled())
        self.assertIsNone(self.page.export_result_json(target));self.assertFalse(target.exists())

    def test_external_overlay_is_preserved_separately_and_nonfinite_export_is_rejected(self):
        result=self.fixture()
        overlay=dict(current_ma=[0.,150.],output_power_mw=[0.,9.],provenance={'model_name':'Synthetic external fixture'},manifest_path='synthetic.json')
        result['comsol']=copy.deepcopy(overlay)
        target=self.target('overlay.json');self.page.export_result_json(target)
        saved=json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(saved['comsol'],overlay);self.assertEqual(saved['sweep'],result['sweep'])
        self.assertFalse(saved['export_metadata']['inputs_changed_since_calculation'])
        target.write_text('preserve existing file',encoding='utf-8')
        result['bad_fixture_value']=float('nan')
        self.assertIsNone(self.page.export_result_json(target))
        self.assertEqual(target.read_text(encoding='utf-8'),'preserve existing file')
        self.assertIn('Numerical export failed',self.page.status.text())

    def test_compact_results_toolbar_exposes_the_raw_json_action(self):
        self.fixture()
        self.page.resize(860,720);self.page.show();self.page._show_laser_stage(5)
        self.app.processEvents()
        button=self.page.result_export_button
        self.assertTrue(button.isVisible())
        self.assertTrue(button.isEnabled())
        self.assertLessEqual(button.geometry().right(),button.parentWidget().width())
        target=self.target('from-menu.json')
        with patch('qt_pcsel.QFileDialog.getSaveFileName',return_value=(str(target),'')):
            button.menu().actions()[0].trigger()
        self.assertTrue(target.is_file())
        self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['inputs']['quality_factor'],42000.)
        self.assertEqual(self.solve.call_count,2)

    def test_cancelled_export_leaves_result_and_files_unchanged(self):
        result=copy.deepcopy(self.fixture())
        with patch('qt_pcsel.QFileDialog.getSaveFileName',return_value=('','')):
            self.assertIsNone(self.page.export_result_json())
        self.assertEqual(self.page.last_result,result)
        self.assertEqual(self.solve.call_count,2)


if __name__=='__main__':unittest.main()
