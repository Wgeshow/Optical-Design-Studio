"""Physical model drafts require explicit parameters and never overwrite on error."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from simulation_setup_state import SimulationSetupState
from qt_simulation_setup import SimulationSetupWorkspace
from qt_transport_setup import TransportSetupDialog

APP = QApplication.instance() or QApplication([])
QA_SOURCE = 'Explicit synthetic UI validation assumption, not a paper parameter or material default'


class TransportSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods_transport_ui_', dir=Path(__file__).resolve().parents[3])
        self.store = ProjectStore(DataLibrary(self.temp.name), restore=False)
        self.state = SimulationSetupState(self.store)
        self.page = SimulationSetupWorkspace(state=self.state)
        self.page.resize(1586, 940)
        self.page.show()
        self.dialog = TransportSetupDialog(self.page)
        self.dialog.show()
        APP.processEvents()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.page.close()
        self.page.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def mode(self, mode):
        self.dialog.mode.setCurrentIndex(self.dialog.mode.findData(mode))
        APP.processEvents()

    def material(self, mid):
        self.dialog.material.setCurrentIndex(self.dialog.material.findData(mid))
        APP.processEvents()

    def test_new_dialog_has_no_invented_physical_numbers(self):
        self.assertEqual(self.dialog.mode.currentData(), 'disabled')
        self.assertEqual(self.dialog.tabs.count(), 3)
        for group in self.dialog.groups.values():
            self.assertFalse(group.enabled.isChecked())
            self.assertTrue(all(not control.text() for control in group.controls.values()))
            self.assertFalse(group.source.toPlainText())
        self.assertFalse(self.dialog.leak_enabled.isChecked())
        self.assertFalse(self.dialog.threshold_enabled.isChecked())
        self.assertFalse(self.dialog.critical_field.text())

    def test_transport_configuration_is_before_material_table_with_action_at_top(self):
        self.page.set_mode('electrical')
        self.page.select_section('electrical.temperature')
        APP.processEvents()
        tab = self.page.section_meta['electrical.temperature']
        ids = [card['id'] for card in tab['cards']]
        self.assertEqual(ids.index('electrical.temperature.transport'), ids.index('electrical.temperature.charge') + 1)
        self.assertLess(ids.index('electrical.temperature.transport'), ids.index('electrical.temperature.table'))
        frame = next(frame for frame, card in self.page.cards if card['id'] == 'electrical.temperature.transport')
        self.assertEqual(frame.layout().itemAt(2).widget().text(), 'Configure physical models…')

    def test_all_electrical_tabs_describe_selected_physics_without_old_input_limits(self):
        self.page.set_mode('electrical')
        tabs = self.page.plan['modes']['electrical']['tabs'] if hasattr(self.page, 'plan') else [self.page.section_meta[key] for key in self.page.section_meta if key.startswith('electrical.')]
        self.assertEqual(len(tabs), 7)
        for tab in tabs:
            for card in tab['cards']:
                for field in card.get('fields', []):
                    if field.get('key') == 'search.electrical.terminal_studies.iv_enabled':
                        self.assertIn('selected current model', field['label'])
                    if field.get('key') == 'ui.electrical.study':
                        self.assertEqual(next(option['label'] for option in field['options'] if option['value'] == 'iv'), 'I–V · selected current model')
        bounds = self.state.get('ui.electrical.custom_bounds')
        self.assertIn('Finite voltage', bounds)
        self.assertNotIn('100', bounds)
        self.assertNotIn('41', bounds)
        self.assertIn('Static model', self.state.get('ui.electrical.semiconductor_gate'))
        self.state.apply_transport(dict(mode='semiconductor_dd'))
        for key in ('ui.electrical.semiconductor_gate', 'ui.electrical.iv_method', 'ui.electrical.iv_properties', 'ui.electrical.reservoirs', 'ui.electrical.saved_checks'):
            self.assertIn('continuity', self.state.get(key))
        self.state.apply_transport(dict(mode='dielectric_leakage', material_models={'air': {'mechanism': 'ohmic', 'parameters': {'conductivity_S_m': .004, 'parameter_source': QA_SOURCE}}}))
        self.assertIn('sourced material leakage', self.state.get('ui.electrical.dielectric_gate'))
        self.assertIn('leakage', self.state.get('ui.electrical.iv_properties'))

    def test_leakage_parameters_and_source_apply_atomically_and_share_with_coupled(self):
        self.mode('dielectric_leakage')
        self.material('air')
        self.dialog.leak_enabled.setChecked(True)
        self.dialog.material_controls['conductivity_S_m'].setText('0.004')
        self.dialog.material_source.setPlainText(QA_SOURCE)
        self.dialog.threshold_enabled.setChecked(True)
        self.dialog.critical_field.setText('1e8')
        self.dialog.threshold_source.setPlainText(QA_SOURCE)
        self.assertNotIn('transport', self.store.search_state.get('electrical', {}))
        self.dialog.apply()
        cfg = self.state.get('search.electrical.transport')
        self.assertEqual(cfg['mode'], 'dielectric_leakage')
        self.assertEqual(cfg['material_models']['air']['parameters']['conductivity_S_m'], .004)
        self.assertEqual(cfg['material_models']['air']['parameters']['parameter_source'], QA_SOURCE)
        self.assertEqual(cfg['breakdown_fields']['air']['critical_field_V_m'], 1e8)
        self.assertEqual(self.state.get('search.electrical.charge_model'), 'dielectric')
        self.assertEqual(self.state.job_options('electrical')['transport'], self.state.job_options('coupled')['transport'])
        self.assertIn('sourced leakage', self.state.get('ui.electrical.method'))

    def test_invalid_source_keeps_draft_and_applied_settings_then_valid_srh_persists(self):
        before = copy.deepcopy(self.store.project())
        self.mode('semiconductor_dd')
        group = self.dialog.groups['srh']
        group.enabled.setChecked(True)
        for key, value in [('tau_n_s', '1e-7'), ('tau_p_s', '2e-7'), ('trap_energy_eV', '0')]:
            group.controls[key].setText(value)
        self.dialog.apply()
        self.assertIn('parameter_source', self.dialog.status.text())
        self.assertEqual(self.store.project(), before)
        self.assertEqual(group.controls['tau_n_s'].text(), '1e-7')
        self.assertTrue(self.dialog.isVisible())
        group.source.setPlainText(QA_SOURCE)
        self.dialog.apply()
        cfg = self.state.get('search.electrical.transport')
        self.assertEqual(cfg['srh']['tau_p_s'], 2e-7)
        self.assertEqual(cfg['srh']['parameter_source'], QA_SOURCE)
        self.assertEqual(self.state.get('search.electrical.charge_model'), 'semiconductor')
        self.assertIn('continuity', self.state.get('ui.electrical.iv_method'))
        again = TransportSetupDialog(self.page)
        self.assertTrue(again.groups['srh'].enabled.isChecked())
        self.assertEqual(again.groups['srh'].source.toPlainText(), QA_SOURCE)
        again.close()

    def test_material_mechanism_navigation_retains_local_drafts_and_cancel_does_not_apply(self):
        before = copy.deepcopy(self.store.project())
        self.mode('dielectric_leakage')
        self.material('air')
        self.dialog.leak_enabled.setChecked(True)
        self.dialog.mechanism.setCurrentIndex(self.dialog.mechanism.findData('poole_frenkel'))
        self.dialog.material_controls['conductivity_prefactor_S_m'].setText('1e-9')
        self.dialog.material_controls['trap_depth_eV'].setText('.6')
        self.dialog.material_controls['optical_epsilon_r'].setText('3')
        self.dialog.material_source.setPlainText(QA_SOURCE)
        self.material('gaas')
        self.material('air')
        self.assertEqual(self.dialog.mechanism.currentData(), 'poole_frenkel')
        self.assertEqual(self.dialog.material_controls['trap_depth_eV'].text(), '.6')
        self.assertEqual(self.dialog.material_source.toPlainText(), QA_SOURCE)
        self.dialog.reject()
        self.assertEqual(self.store.project(), before)

    def test_transport_forward_preflight_validates_geometry_before_skipping_static_gate(self):
        from test_contact_optics import project
        from test_electrical_transport import planar_options
        options = planar_options(doping=1e15, biases=(0., .2))
        self.store.load_project(project(options['device']))
        self.state.set('search.electrical.swept_contact_id', options['swept_contact_id'])
        self.state.set('search.electrical.biases_V', options['biases_V'])
        self.state.apply_transport(dict(mode='semiconductor_dd'))
        with patch('custom_electrical_solver._reservoirs', side_effect=AssertionError('Static forward reservoir gate must not be used for validated continuity transport')):
            self.assertEqual(self.state.validate('electrical'), [])
        with patch('electrical_transport_adapter.validate_transport_device', side_effect=ValueError('Explicit geometry-validation QA rejection')):
            self.assertTrue(any('geometry-validation QA rejection' in issue['message'] for issue in self.state.validate('electrical')))

    def test_native_transport_runtime_check_does_not_report_only_scipy(self):
        self.state.apply_transport(dict(mode='semiconductor_dd'))
        with patch('electrical_solver._load_core', return_value=object()) as load:
            result = self.state.check_runtime('electrical')
        load.assert_called_once()
        self.assertTrue(result['available'])
        self.assertIn('DEVSIM', result['message'])

    def test_fermi_dirac_interface_source_and_3d_controls_are_explicit(self):
        self.mode('semiconductor_dd')
        self.dialog.statistics.setCurrentIndex(self.dialog.statistics.findData('fermi_dirac'))
        self.dialog.heterojunction.setChecked(True)
        before = copy.deepcopy(self.store.project())
        self.dialog.apply()
        self.assertIn('parameter_source', self.dialog.status.text())
        self.assertEqual(self.store.project(), before)
        self.assertFalse(self.dialog.custom_nodes.isEnabled())
        self.assertFalse(self.dialog.nodes.isEnabled())
        self.assertIn('actual Structure 3D mesh', self.dialog.path_readout.text())
        self.dialog.interface_source.setPlainText(QA_SOURCE)
        self.dialog.apply()
        cfg = self.state.get('search.electrical.transport')
        self.assertEqual(cfg['statistics'], 'fermi_dirac')
        self.assertEqual(cfg['heterojunction'], dict(model='ideal_quasi_fermi', parameter_source=QA_SOURCE))
        with patch('custom_electrical_solver.build_mesh', side_effect=AssertionError('Rendering settings must not allocate a transport mesh')):
            self.page.refresh()
            self.assertIn('Actual 3D Structure mesh', self.state.get('ui.electrical.transport_discretization'))
        self.assertIn('Fermi', self.state.get('ui.electrical.statistics'))


if __name__ == '__main__': unittest.main()
