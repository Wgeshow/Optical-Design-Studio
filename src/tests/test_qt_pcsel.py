import os
import csv
import unittest
import tempfile
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QFrame, QLabel
from PyQt6.QtCore import QCoreApplication, QEvent
from comsol_results import result_manifest, write_result_manifest
from qt_pcsel import PCSELPage


class PCSELPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = PCSELPage(None)
        self.page.run_simulation()

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_default_controls_run_laser_model(self):
        result = self.page.last_result
        self.assertIsNotNone(result)
        self.assertEqual(len(result['currents_ma']), self.page.current_points.value())
        self.assertIn('Threshold current', self.page.quick.text())
        self.assertIn('PCSEL LASER SIMULATION', self.page.report.toPlainText())

    def test_complete_laser_workflow_is_exposed(self):
        names=[self.page.tabs.tabText(i).replace('&&','&') for i in range(self.page.tabs.count())]
        self.assertEqual(names,['Device Setup','Optical Modes','Electrical & Gain','COMSOL',
                                'Thermal','Modulation · optional','Results','Report'])
        self.assertEqual(self.page.mode_table.rowCount(),1)
        self.assertIn('3 dB bandwidth',self.page.modulation_summary.text())
        self.assertIn('nm',self.page.thermal_summary.text())

    def test_dense_workspace_shell_and_live_overview_are_exposed(self):
        rail = self.page.findChild(QFrame, 'setupRail')
        self.assertIsNotNone(rail)
        self.assertEqual(rail.width(), 270)
        self.assertEqual(self.page.objectName(), 'laserWorkspace')
        self.assertEqual(self.page.run_state.text(), '●  SOLVED')
        self.assertIn('Ith', self.page.overview_status.text())
        self.assertIn('mA', self.page.overview_sweep.text())
        self.assertGreaterEqual(len(self.page.findChildren(QLabel, 'kpi')), 4)

    def test_approved_dashboard_panels_are_native_and_live(self):
        from qt_device_builder import GeometryViewport
        self.assertIsInstance(self.page.structure_canvas,GeometryViewport)
        self.assertEqual([layer['Name'] for layer in self.page.structure_canvas.layers],self.page.device_store.layers.Name.tolist())
        self.assertEqual(len(self.page.field_canvas.figure.axes), 1)  # field plus colorbar
        self.assertIn('S4 / Meep: not run', self.page.solver_status.text())
        self.assertEqual(len(self.page.dashboard_kpis), 8)
        self.assertIn('mA', self.page.dashboard_kpis[0].text())
        self.assertEqual(len(self.page.dashboard_li.figure.axes), 1)
        self.assertEqual(len(self.page.dashboard_mod.figure.axes), 1)
        self.assertEqual(len(self.page.dashboard_rolloff.figure.axes), 1)
        self.assertEqual(len(self.page.dashboard_shift.figure.axes), 1)

    def test_report_can_be_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'report.txt'
            returned=self.page.export_report(target)
            self.assertEqual(returned,target)
            self.assertIn('THRESHOLD AND OUTPUT',target.read_text(encoding='utf-8'))

    def test_control_changes_are_used_by_calculation(self):
        original = self.page.last_result['threshold_current_ma']
        self.page.active_volume.setValue(self.page.active_volume.value() * 2)
        updated = self.page.run_simulation()
        self.assertAlmostEqual(updated['threshold_current_ma'], original * 2, places=8)

    def test_ui_parameter_units_are_forwarded_to_backend(self):
        self.page.transparency_density.setValue(1.7)
        self.page.differential_gain.setValue(3.2)
        self.page.recombination_a.setValue(2.1)
        self.page.recombination_b.setValue(4.3)
        self.page.recombination_c.setValue(5.4)
        parameters = self.page.laser_parameters()

        self.assertEqual(parameters.transparency_density_cm3, 1.7e18)
        self.assertAlmostEqual(parameters.differential_gain_cm2, 3.2e-16)
        self.assertEqual(parameters.recombination_a_s, 2.1e8)
        self.assertAlmostEqual(parameters.recombination_b_cm3_s, 4.3e-10)
        self.assertAlmostEqual(parameters.recombination_c_cm6_s, 5.4e-29)

    def test_current_sweep_and_report_share_backend_result(self):
        self.page.current_max.setValue(80)
        self.page.current_points.setValue(9)
        result = self.page.run_simulation()

        self.assertEqual(result['currents_ma'][0], 0)
        self.assertEqual(result['currents_ma'][-1], 80)
        self.assertEqual(len(result['currents_ma']), 9)
        self.assertIn('Output at 80 mA', self.page.report.toPlainText())
        plotted = self.page.laser_canvas.figure.axes[0].lines[0]
        self.assertEqual(list(plotted.get_xdata()), result['currents_ma'])
        self.assertEqual(list(plotted.get_ydata()), result['output_power_mw'])

    def test_modulation_bias_control_is_independent_of_current_sweep(self):
        self.page.current_max.setValue(150)
        self.page.bias_current.setValue(65)
        result = self.page.run_simulation()

        self.assertEqual(result['currents_ma'][-1], 150)
        self.assertEqual(result['modulation']['bias_current_ma'], 65)

    def test_thermal_controls_are_forwarded_and_update_plot_summary(self):
        self.page.ambient_temperature.setValue(310)
        self.page.thermal_resistance.setValue(25)
        self.page.series_voltage.setValue(2.2)
        self.page.thermal_shift.setValue(.12)
        result = self.page.run_simulation()

        self.assertEqual(result['inputs']['ambient_temperature_k'], 310)
        self.assertEqual(result['inputs']['thermal_resistance_k_w'], 25)
        self.assertEqual(result['inputs']['drive_voltage_v'], 2.2)
        self.assertEqual(result['inputs']['wavelength_shift_nm_k'], .12)
        self.assertIn(f"{result['sweep'][-1]['temperature_k']:.1f} K",
                      self.page.thermal_summary.text())

    def test_comsol_import_adds_overlay_and_report_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (root / 'power.csv').open('w', encoding='utf-8', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(('current', 'power'))
                writer.writerows(((0, 0), (50, 8)))
            manifest = result_manifest(
                'power.csv',
                ({'name': 'current', 'quantity': 'current', 'unit': 'mA',
                  'expression': 'I0'},
                 {'name': 'power', 'quantity': 'optical_power', 'unit': 'mW',
                  'expression': 'ewfd.Poav'}),
                model_name='UI integration model', study='std1', dataset='dset1',
            )
            path = write_result_manifest(root / 'power.results.json', manifest)
            imported = self.page.import_comsol(path)

            self.assertIsNotNone(imported)
            self.assertEqual(self.page.last_result['comsol']['output_power_mw'], [0, 8])
            labels = [line.get_label()
                      for line in self.page.laser_canvas.figure.axes[0].lines]
            self.assertIn('COMSOL imported', labels)
            report = self.page.report.toPlainText()
            self.assertIn('COMSOL IMPORT', report)
            self.assertIn('Model: UI integration model', report)
            self.assertIn('Study: std1', report)

    def test_invalid_geometry_clears_results(self):
        self.page.period.setValue(.2)
        self.page.radius.setValue(.15)
        self.assertIsNone(self.page.run_simulation())
        self.assertIsNone(self.page.last_result)
        self.assertIn('smaller than half', self.page.status.text())


if __name__ == '__main__':
    unittest.main()
