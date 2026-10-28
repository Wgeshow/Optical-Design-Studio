"""Thermal input review regression with synthetic drafts; no numerical solve."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from device_model import default_device
from qt_core import ProjectStore
from qt_thermal_setup import ThermalSetupWorkspace

APP = QApplication.instance() or QApplication([])


class ThermalReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='thermal-review-', dir=Path.cwd())
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.store.activate_study('thermal')
        device = default_device(self.store.electrical_materials)
        device.update(width_um=3., depth_um=4., contacts=[], shapes=[], doping_regions=[])
        device['layers'] = device['layers'][:2]
        device['mesh'].update(nx=24, ny=32, nz_per_layer=6)
        self.store.set_device(device)
        self.page = ThermalSetupWorkspace(self.store, document_id='thermal')
        self.guard = patch.object(self.store, 'start_run', side_effect=AssertionError('No solver permitted'))
        self.guard.start()
        for row in range(self.page.powers.rowCount()):
            self.page.powers.item(row, 1).setText('0.0004')
        for row in range(self.page.conductivities.rowCount()):
            self.page.conductivities.item(row, 1).setText('1.25')
            self.page.conductivities.item(row, 2).setText('Authored test source <not an accepted paper>')
        self.page.boundaries.cellWidget(0, 1).setCurrentText('convection')
        self.page.boundaries.item(0, 2).setText('297')
        self.page.boundaries.item(0, 3).setText('1200')
        self.page.select_section('__journey_check')

    def tearDown(self):
        self.page._save_timer.stop()
        sip.delete(self.page)
        APP.processEvents()
        self.guard.stop()
        self.temp.cleanup()

    def rows(self):
        self.page.journey_execution.refresh()
        tree = self.page.journey_execution.inputs
        return {tree.topLevelItem(i).text(0): tree.topLevelItem(i) for i in range(tree.topLevelItemCount())}

    def test_review_contains_applied_geometry_mesh_and_all_thermal_assignments(self):
        rows = self.rows()
        values='\n'.join(item.text(0)+': '+item.text(1) for item in rows.values())
        for expected in ('Applied device geometry', '3.0 × 4.0', 'nx = 24', 'ny = 32',
                         'nz_per_layer = 6', '0.0004 W', '1.25 W/(m K)',
                         'Authored test source <not an accepted paper>', '297 K', '1200 W/(m² K)',
                         'Top · z_min', 'Bottom · z_max'):
            self.assertIn(expected, values)
        layer_value = rows['Applied layer · p+ GaAs'].text(1)
        self.assertIn('material GaAs', layer_value)
        self.assertNotIn(self.store.device['layers'][0]['id'], layer_value)

    def test_invalid_table_draft_is_visible_verbatim_and_marks_check_stale(self):
        panels = self.page.journey_execution
        panels.validation_status.setText('Inputs checked')
        self.page.powers.item(0, 1).setText('1e-')
        self.assertIn('Inputs changed', panels.validation_status.text())
        before = copy.deepcopy(self.page.draft())
        values='\n'.join(item.text(0)+': '+item.text(1) for item in self.rows().values())
        self.assertIn('1e- W', values)
        self.assertIn('Draft values', values)
        self.assertEqual(self.page.draft(), before)

    def test_rows_return_to_actual_geometry_power_material_and_cooling_sections(self):
        for label, section in [('Applied device geometry','device_editor'), ('Applied mesh','device_editor'),
                               ('Layer power · p+ GaAs','heat_sources'), ('Conductivity · GaAs','materials'),
                               ('Cooling · Left · x_min','boundaries')]:
            with self.subTest(label=label):
                self.page.select_section('__journey_check')
                self.page.journey_execution._open(self.rows()[label])
                self.assertEqual(self.page.tabs.currentIndex(), self.page.sections[section])

    def test_disabled_layer_power_is_not_shown_as_active_and_insulated_coefficients_are_omitted(self):
        device = copy.deepcopy(self.store.device)
        device['layers'][-1]['enabled'] = False
        self.store.set_device(device)
        self.page.boundaries.cellWidget(0, 1).setCurrentText('insulated')
        rows = self.rows()
        self.assertNotIn('Layer power · p GaAs', rows)
        self.assertIn('Insulated', rows['Cooling · Left · x_min'].text(1))
        self.assertNotIn('1200', rows['Cooling · Left · x_min'].text(1))


if __name__ == '__main__':
    unittest.main()
