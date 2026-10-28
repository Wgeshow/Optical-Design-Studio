"""Model-specific input binding, understandable transfers and device isolation."""
import copy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QLabel
from data_library import DataLibrary
from device_model import default_device
from qt_core import ProjectStore
from qt_custom_device import CustomDevicePage
from qt_pcsel_research_setup import PcselResearchWorkspace
from qt_study_transfer import StudyTransferDialog, transfer_preview_rows
from research_catalog import list_capabilities
import pcsel_research as pc


class ModelInputAndTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pcsel-model-bindings-')
        self.store = ProjectStore(DataLibrary(Path(self.temp.name) / 'library'), restore=False)
        self.store.study_navigation_enabled = True
        self.pages = []
        self.guards = []
        for target in ('pcsel_research.execute', 'pcsel_research.vertical', 'pcsel_research.coupling', 'pcsel_research.finite_modes', 'research_physics_runtime.run_worker'):
            guard = patch(target, side_effect=AssertionError('Numerical solver execution is forbidden in input-binding tests.'))
            guard.start(); self.guards.append(guard)

    def tearDown(self):
        for page in self.pages:
            if hasattr(page, '_save_timer'): page._save_timer.stop()
            page.close(); page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for guard in self.guards: guard.stop()
        self.temp.cleanup()

    def page(self, model):
        target = 'pcsel.' + model
        self.store.activate_study(target)
        capability = next(row for row in list_capabilities() if row['engine'] == 'pcsel')
        page = PcselResearchWorkspace(self.store, capability, document_id=target)
        page.bind_study_document(target)
        self.pages.append(page)
        return page

    def test_thin_gme_and_rcwa_layers_do_not_require_hidden_vertical_mesh(self):
        for model in ('gme', 'rcwa_poles'):
            with self.subTest(model=model):
                settings = pc.paper_example()
                settings.update(model=model, grid_nm=100, pole_seeds=[[.3, -1e-4]])
                settings['layers'][3]['thickness_nm'] = .5
                result = pc.prepare({}, settings)
                self.assertEqual(result['layers'][3]['thickness_nm'], .5)
                self.assertEqual(result['model'], model)
        settings['model'] = 'vertical'
        with self.assertRaises(pc.InputValidationError) as caught:
            pc.prepare({}, settings)
        self.assertEqual(caught.exception.diagnostics[0]['field'], 'grid_nm')

    def test_irrelevant_beam_inputs_do_not_block_vertical_but_active_checks_remain(self):
        settings = pc.paper_example()
        settings.update(beam_normalization='calibrated_power', beam_power_source='', beam_grid=9999,
                        collocation_order=99, gmax='unfinished')
        self.assertEqual(pc.prepare({}, settings)['model'], 'vertical')
        settings.update(model='beam', collocation_order=12)
        with self.assertRaises(pc.InputValidationError) as caught:
            pc.prepare({}, settings)
        self.assertEqual(caught.exception.diagnostics[0]['field'], 'beam_grid')

    def test_inactive_raw_text_is_preserved_but_not_parsed_into_another_model(self):
        page = self.page('rcwa_poles')
        page.load_pcsel_example()
        page.fields['grid_nm'].setText('1e-')
        page.fields['gmax'].setText('unfinished')
        page.structured['pole_seeds'].set_value([[.299, -1e-4]])
        page.fields['basis'].setText('81')
        page.fields['pole_field_grid'].setText('32')
        page.structured['pole_field_z_nm'].set_value([100., 200.])
        request = page.options()['settings']
        self.assertNotIn('grid_nm', request)
        self.assertNotIn('gmax', request)
        self.assertEqual(page.fields['grid_nm'].text(), '1e-')
        prepared = pc.prepare({}, request)
        self.assertEqual(prepared['basis'], 81)
        self.assertEqual(prepared['pole_field_grid'], 32)
        self.assertEqual(prepared['pole_field_z_nm'], [100., 200.])
        page.fields['basis'].setText('unfinished')
        with self.assertRaises(ValueError): page.options()

    def test_sweep_targets_follow_model_and_imported_noop_sweeps_are_rejected(self):
        expected = {'vertical': {'grid_nm', 'pad_nm'}, 'cwt': {'harmonics', 'grid_nm'},
                    'finite': {'collocation_order', 'aperture_um'}, 'beam': {'beam_grid', 'beam_padding'},
                    'gme': {'gmax', 'num_modes'}, 'rcwa_poles': {'basis'}}
        for model, required in expected.items():
            page = self.page(model)
            page.load_pcsel_example()
            targets = page.structured['parameter_sweep'].targets
            paths = {targets.itemData(i)['path'] for i in range(targets.count())}
            self.assertTrue(required <= paths, model)
            self.assertNotIn('gmax' if model != 'gme' else 'grid_nm', paths)
        settings = pc.paper_example()
        for parameter in (dict(path='gmax', values=[2.1, 3.1]), dict(path='center_scale', values=[.8, 1.])):
            settings['parameter_sweep'] = dict(parameters=[parameter])
            with self.assertRaises(pc.InputValidationError) as caught: pc.prepare({}, settings)
            self.assertEqual(caught.exception.diagnostics[0]['field'], 'parameter_sweep')
        settings['parameter_sweep'] = dict(parameters=[dict(path='grid_nm', values=[1., 2.])])
        self.assertEqual(len(pc.prepare({}, settings)['parameter_sweep']['cases']), 2)

    def test_crystal_transfer_preview_names_geometry_material_and_length_values(self):
        self.store.activate_study('photonic_bands.2d')
        crystal = dict(lattice=[['1', '0'], ['0', '1']], geometry=[['Rod', 'circle', '0,0', '.2']],
                       object_ids=['rod-id'], epsilons={'rod-id': '12'},
                       fields={'reference_length_um': '.4', 'background_epsilon': '1'})
        self.store.save_search('research_workspaces', dict(schema_version=1, bands=crystal))
        self.store.activate_study('photonic_bands.legume')
        before = copy.deepcopy(self.store.project())
        dialog = StudyTransferDialog(self.store); self.pages.append(dialog)
        dialog.source.setCurrentIndex(dialog.source.findData('photonic_bands.2d'))
        rows = [[dialog.preview.topLevelItem(i).text(j) for j in range(3)] for i in range(dialog.preview.topLevelItemCount())]
        text = str(rows)
        self.assertIn('Crystal lattice vectors', text)
        self.assertIn('Crystal objects', text)
        self.assertIn('Rod', text)
        self.assertIn('ε = 12', text)
        self.assertIn('Crystal length scale (µm)', text)
        self.assertNotIn('schema_version', text)
        self.assertNotIn('desktop search', text)
        self.assertEqual(self.store.project(), before)

    def test_pcsel_transfer_preview_decodes_raw_geometry_without_solver_parameters(self):
        source = self.page('vertical')
        source.load_pcsel_example()
        before = {'desktop_search': {'research_workspaces': {'model_pcsel_research': {}}}}
        after = {'desktop_search': {'research_workspaces': {'model_pcsel_research': source.draft()}}}
        rows = transfer_preview_rows(before, after, 'pcsel.finite')
        titles = [row[0] for row in rows]
        self.assertIn('Layer stack and refractive indices', titles)
        self.assertIn('Crystal inclusions', titles)
        self.assertIn('Square lattice pitch (nm)', titles)
        layers = next(row[2] for row in rows if row[0] == 'Layer stack and refractive indices')
        self.assertEqual(layers[0]['name'], 'contact')
        self.assertEqual(layers[0]['thickness_nm'], '100')
        self.assertNotIn('harmonics', str(titles))

    def test_thermal_shape_edit_is_isolated_and_notice_says_this_simulation(self):
        from qt_app import OpticalStudio
        self.store.set_device(default_device(self.store.electrical_materials))
        source = CustomDevicePage(self.store, include_advanced=False); self.pages.append(source)
        source.add_shape('circle')
        source_device = copy.deepcopy(self.store.device)
        self.store.activate_study('thermal')
        self.store.transfer_study_inputs('optical')
        editor = CustomDevicePage(self.store, include_advanced=False); self.pages.append(editor)
        identity = self.store.device['shapes'][-1]['id']
        editor.focus_object(identity)
        editor.enabled_edit.setChecked(False)
        self.assertTrue(editor.apply_inspector())
        self.assertFalse(self.store.device['shapes'][-1]['enabled'])
        self.assertEqual(self.store.study_project('optical')['device'], source_device)
        notice = Mock(title_label=QLabel(), summary=QLabel())
        owner = SimpleNamespace(store=self.store, _structure_snapshot=None,
                                structure_signature=lambda: 'changed', structure_notice=notice,
                                position_structure_notice=Mock())
        OpticalStudio.structure_changed(owner)
        self.assertIn('Applied to this simulation only.', notice.summary.text())
        self.assertNotIn('every workflow', notice.summary.text())


if __name__ == '__main__': unittest.main()
