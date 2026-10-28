"""Review-only widget regressions, separate from native scientific acceptance."""
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
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace

APP = QApplication.instance() or QApplication([])


class S4InputReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods_s4_review_', dir=Path(__file__).resolve().parents[3])
        self.store = ProjectStore(DataLibrary(self.temp.name), restore=False)
        self.page = SimulationSetupWorkspace(self.store)
        self.page.set_mode('optical')

    def tearDown(self):
        sip.delete(self.page)
        APP.processEvents()
        self.temp.cleanup()

    def test_applied_geometry_and_material_values_have_physical_units_and_no_ids(self):
        device = copy.deepcopy(self.store.device)
        layer = device['layers'][0]
        layer.update(name='Review slab', thickness_um=.5, optical_material_name='Air')
        device.update(width_um=1., depth_um=1.)
        device['shapes'] = [dict(id='private-region-identity', name='Review circle', layer_id=layer['id'],
            shape='circle', cx_um=.1, cy_um=-.1, size_x_um=.4, size_y_um=.4, angle_deg=0.,
            enabled=True, material_id=layer['material_id'], operation='material', optical_material_name='Air')]
        self.store.set_device(device)
        self.store.set_optical_exterior_material('exit', 'Air')
        rows = dict(self.page.setup_review_rows())
        self.assertIn('1 × 1 µm', rows['Applied finite footprint'])
        self.assertIn('0.5 µm', rows['Applied layer: Review slab'])
        self.assertIn('Air', rows['Applied layer: Review slab'])
        self.assertIn('diameter 0.4 µm', rows['Applied region: Review circle'])
        self.assertIn('center (0.1, -0.1) µm', rows['Applied region: Review circle'])
        self.assertEqual(rows['Applied incident medium'], 'Air')
        self.assertEqual(rows['Applied exit medium'], 'Air')
        self.assertIn('n = 1', rows['Applied material: Air'])
        self.assertIn('k = 0', rows['Applied material: Air'])
        self.assertNotIn('private-region-identity', str(rows))
        self.assertNotIn(layer['id'], str(rows))

    def test_invalid_numeric_draft_is_visible_beside_last_applied_value_without_commit(self):
        editor = self.page.widgets_by_key['settings.NumG'][0]
        editor.setText('121 unfinished')
        editor.editingFinished.emit()
        applied = self.page.state.get('settings.NumG')
        before = self.store.portable_project()
        drafts = copy.deepcopy(self.page.drafts)
        with patch.object(self.page, 'commit_drafts') as commit, patch.object(self.page.state, 'validate') as validate:
            rows = dict(self.page.setup_review_rows())
        value = rows['Fourier basis count']
        self.assertIn('121 unfinished', value)
        self.assertIn('not applied', value)
        self.assertIn('Applied: '+str(applied), value)
        self.assertIn('Invalid:', value)
        commit.assert_not_called(); validate.assert_not_called()
        self.assertEqual(before, self.store.portable_project())
        self.assertEqual(drafts, self.page.drafts)
        self.assertEqual(editor.text(), '121 unfinished')

    def test_review_includes_current_scan_incidence_and_basis_without_solver_or_mesh(self):
        self.page.state.set('settings.wl_start_nm', 1600.)
        self.page.state.set('settings.wl_stop_nm', 3000.)
        self.page.state.set('settings.wl_step_nm', 8.)
        self.page.state.set('settings.theta_deg', 0.)
        self.page.state.set('settings.phi_deg', 13.)
        self.page.state.set('settings.NumG', 121)
        before = self.store.portable_project()
        with patch('custom_electrical_solver.build_mesh') as mesh, patch('qt_core.prepare_job') as job:
            rows = dict(self.page.setup_review_rows())
        self.assertIn('1600', rows['Wavelength start'])
        self.assertIn('3000', rows['Wavelength stop'])
        self.assertIn('8', rows['Wavelength step'])
        self.assertIn('176', rows['Applied sample count'])
        self.assertIn('3000', rows['Applied last sample'])
        self.assertIn('13', rows['Azimuth φ'])
        self.assertEqual(rows['Fourier basis count'], '121')
        mesh.assert_not_called(); job.assert_not_called()
        self.assertEqual(before, self.store.portable_project())

    def test_check_stage_exposes_review_action_without_running_validation(self):
        flow = self.page.setup_flow
        flow.show_stage(3)
        self.assertEqual(flow.review_button.text(), 'Review current inputs')
        self.assertFalse(flow.review_button.isHidden())
        with patch.object(self.page, '_review_setup') as review, patch.object(self.page, 'validate_current') as validate:
            flow.review_button.click()
        review.assert_called_once_with()
        validate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
