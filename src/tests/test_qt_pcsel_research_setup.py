"""Canonical PCSEL requests and drafts survive the friendly research editors."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLineEdit
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel_research_setup import PcselResearchWorkspace, pcsel_preview_device, _child
from research_catalog import list_capabilities

APP = QApplication.instance() or QApplication([])


class PcselSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pcsel-native-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page.close(); page.deleteLater()
        APP.processEvents()

    def page(self, engine='pcsel'):
        cap = next(row for row in list_capabilities() if row['engine'] == engine)
        page = PcselResearchWorkspace(self.store, cap)
        page.resize(1250, 850); page.show(); APP.processEvents()
        self.pages.append(page)
        return page

    def test_recovered_example_canonical_values_survive_and_geometry_is_independent(self):
        from pcsel_research import paper_example, prepare
        before = copy.deepcopy(self.store.device)
        page = self.page(); settings = paper_example('hole', 'CC', .16)
        page.load_settings(settings)
        actual = page.options()['settings']
        for key, value in settings.items(): self.assertEqual(actual[key], value)
        self.assertEqual(prepare(self.store.project(), actual)['layers'], prepare(self.store.project(), settings)['layers'])
        self.assertEqual(self.store.device, before)
        self.assertEqual(len(page.geometry_editor.preview.last_geometry[0]), len(settings['layers']))

    def test_invalid_inspector_text_roundtrips_and_exact_diagnostic_reveals_it(self):
        page = self.page(); page.load_pcsel_example()
        edit = page.geometry_editor.form.controls['thickness_nm']
        edit.setText('1e-')
        draft = copy.deepcopy(page.draft()); identity = page.geometry_editor.current_id
        with self.assertRaises(ValueError): page.options()
        page.study_flow.show_stage(2)
        self.assertTrue(page.open_diagnostic(dict(workspace='research_studies', field='layers.0.thickness_nm', object_id=identity)))
        APP.processEvents()
        self.assertEqual(page.geometry_editor.form.controls['thickness_nm'].text(), '1e-')
        self.assertTrue(page.geometry_editor.form.controls['thickness_nm'].isVisible())
        self.assertEqual(page.structured['layers'].tree.currentItem().text(0), 'thickness_nm')
        page.restore_draft(draft)
        self.assertEqual(page.geometry_editor.form.controls['thickness_nm'].text(), '1e-')

    def test_new_layer_is_explicitly_incomplete_and_reordering_retains_ids(self):
        page = self.page(); page.load_pcsel_example(); original = page.options()['settings']['layers']
        editor = page.geometry_editor
        editor.add_kind.setCurrentText('Layer'); editor.add_object()
        identity = editor.current_id
        self.assertEqual(editor.form.controls['thickness_nm'].text(), '')
        self.assertEqual(editor.form.controls['index'].text(), '')
        editor.form.controls['thickness_nm'].setText('27.5'); editor.form.controls['index'].setText('3.2')
        editor.move(-1)
        layers = page.options()['settings']['layers']
        self.assertEqual(layers[-2]['id'], identity)
        self.assertEqual([row['id'] for row in layers if row['id'] != identity], [row['id'] for row in original])
        editor.remove(); self.assertEqual(page.options()['settings']['layers'], original)

    def test_circle_editor_changes_same_stable_object_and_sweep_uses_it(self):
        page = self.page(); page.load_pcsel_example()
        old = page.options()['settings']['shapes']
        editor = page.geometry_editor
        self.assertTrue(editor.select_object('shapes', old[1]['id']))
        editor.form.controls['radius'].setText('.08')
        editor.form.controls['center'].components[0].setText('.1')
        result = page.options()['settings']['shapes']
        self.assertEqual(result[1]['id'], old[1]['id'])
        self.assertEqual(result[1]['radius'], .08)
        self.assertEqual(result[1]['center'][0], .1)
        self.assertEqual(result[0], old[0])

    def test_all_optical_models_preserve_nonvisible_values(self):
        page = self.page(); page.load_pcsel_example()
        page.fields['beam_power_source'].setText('Explicit calibration fixture')
        page.fields['gmax'].setText('4.3')
        for model in ('vertical', 'cwt', 'gme', 'rcwa_poles', 'finite', 'beam', 'aperture'):
            page.fields['model'].setCurrentIndex(page.fields['model'].findData(model))
            cfg = page.options()['settings']
            self.assertEqual(cfg['model'], model)
            self.assertEqual(cfg['gmax'], 4.3)
            self.assertEqual(cfg['beam_power_source'], 'Explicit calibration fixture')

    def test_conformal_material_form_edits_actual_material_and_preserves_extra_properties(self):
        from pcsel_transport_study import example_settings, prepare
        page = self.page('pcsel_transport'); settings = example_settings()
        settings['materials']['demo']['B_cm3_s'] = 1.2e-10
        page.load_settings(settings)
        self.assertEqual(page.material_picker.currentData(), 'demo')
        page.friendly_forms['materials'].controls['electron_mobility_cm2_Vs'].setText('140')
        actual = page.options()['settings']
        self.assertEqual(actual['materials']['demo']['electron_mobility_cm2_Vs'], 140)
        self.assertEqual(actual['materials']['demo']['B_cm3_s'], 1.2e-10)
        prepared = prepare(self.store.project(), actual)
        self.assertEqual(prepared['period_um'], settings['period_um'])
        self.assertEqual(actual['inclusions'], settings['inclusions'])

    def test_conformal_new_material_requires_explicit_values(self):
        page = self.page('pcsel_transport'); page._create_fields('materials')
        material = page.friendly_forms['materials']
        self.assertIsInstance(material.controls['bandgap_eV'], QLineEdit)
        self.assertEqual(material.controls['bandgap_eV'].text(), '')
        with self.assertRaises(ValueError): page.options()

    def test_runtime_setup_is_editable_without_requiring_physical_validation(self):
        page = self.page('pcsel_transport'); page._create_fields('runtime')
        form = page.friendly_forms['runtime']
        form.controls['executable'].setText('C:/explicit/python.exe')
        form.controls['timeout_s'].setText('120')
        request = page._runtime_request()
        self.assertEqual(request['settings']['runtime']['executable'], 'C:/explicit/python.exe')
        self.assertEqual(request['settings']['runtime']['timeout_s'], 120)
        self.assertFalse(page.runtime_check.ready)

    def test_aperture_template_never_invents_material_numbers_and_stays_reachable(self):
        page = self.page(); page.fields['model'].setCurrentIndex(page.fields['model'].findData('aperture'))
        page._create_fields('aperture')
        self.assertEqual(page.friendly_forms['aperture'].controls['sheet_ohm_square'].text(), '')
        self.assertTrue(page.open_diagnostic(dict(workspace='research_studies', field='aperture.sheet_ohm_square')))
        self.assertTrue(page.friendly_forms['aperture'].controls['sheet_ohm_square'].isVisible())

    def test_saved_advanced_property_is_preserved_by_friendly_layer_edit(self):
        page = self.page(); page.load_pcsel_example()
        # Existing typed drafts retain keys even when a model validator may later reject them.
        root = page.structured['layers'].tree.topLevelItem(0)
        page.structured['layers']._append(root.child(0), 'provenance_note', 'Keep this draft')
        page._refresh_friendly()
        page.geometry_editor.form.controls['thickness_nm'].setText('101')
        actual = page.options()['settings']['layers'][0]
        self.assertEqual(actual['provenance_note'], 'Keep this draft')
        self.assertEqual(actual['thickness_nm'], 101)

    def test_empty_cell_dimensions_require_both_explicit_values_and_compact_window_fits(self):
        page = self.page('pcsel_transport')
        components = page.period_form.controls['period_um'].components
        self.assertEqual([edit.text() for edit in components], ['', ''])
        components[0].setText('.3')
        with self.assertRaises(ValueError): page.structured['period_um'].value()
        components[1].setText('.4')
        self.assertEqual(page.structured['period_um'].value(), [.3, .4])
        page.resize(800, 760); APP.processEvents()
        self.assertEqual((page.width(), page.height()), (800, 760))
        self.assertTrue(all(edit.isVisible() for edit in components))

    def test_conformal_generic_import_opens_design_but_raw_geometry_restore_is_kept(self):
        from pcsel_transport_study import example_settings
        page = self.page('pcsel_transport'); settings = example_settings()
        page.load_settings(settings)
        self.assertEqual(page.tabs.currentIndex(), page.sections['design'])
        actual = page.options()['settings']
        for key, value in settings.items(): self.assertEqual(actual[key], value)
        self.assertEqual(self.store.search_state['research_workspaces'][page.state_key]['section'], page.sections['design'])
        page.select_section('Geometry')
        saved = copy.deepcopy(page.draft())
        page.select_section('design'); page.restore_draft(saved)
        self.assertEqual(page.tabs.currentIndex(), page.sections['Geometry'])
        self.assertEqual(page.options()['settings'], actual)

    def test_compact_structure_has_space_and_diagnostics_switch_to_cell_inputs(self):
        page = self.page(); page.load_pcsel_example(); page.select_model('finite')
        page.resize(800, 760); APP.processEvents()
        self.assertTrue(page.geometry_editor.isVisible())
        self.assertFalse(page.design_settings.isVisible())
        self.assertLess(page.geometry_editor.mapTo(page, page.geometry_editor.rect().topLeft()).y(), 290)
        self.assertTrue(page.open_diagnostic(dict(field='lattice_nm')))
        self.assertTrue(page.fields['lattice_nm'].isVisible())
        identity = page.options()['settings']['layers'][0]['id']
        self.assertTrue(page.open_diagnostic(dict(field='layers.0.thickness_nm', object_id=identity)))
        self.assertTrue(page.geometry_editor.form.controls['thickness_nm'].isVisible())

    def test_all_models_import_to_structure_and_more_never_opens_empty_legacy_pages(self):
        from pcsel_research import paper_example
        page = self.page()
        for model in ('vertical', 'cwt', 'finite', 'beam', 'aperture', 'gme', 'rcwa_poles'):
            settings = paper_example('hole', 'CC', .16); settings['model'] = model
            page.load_settings(settings)
            self.assertEqual(page.tabs.currentIndex(), page.sections['design'], model)
            self.assertEqual(page.options()['settings']['layers'], settings['layers'])
            for index in sorted(page.journey_allowed_sections()):
                if not page.tabs.isTabVisible(index):
                    continue
                action = next(action for action in page.study_flow.menu.actions()
                    if action.isCheckable() and action.text() == page.tabs.tabText(index))
                action.trigger()
                self.assertNotEqual(page.tabs.currentIndex(), page.sections['study'], (model, index))
                # Empty conditional sections must resolve to an actual setup;
                # useful legacy raw editors remain reachable at stable indices.
                shown = page.tabs.currentWidget()
                from PyQt6.QtWidgets import QAbstractButton, QAbstractItemView, QComboBox, QWidget
                kinds = (QAbstractButton, QAbstractItemView, QComboBox, QLineEdit)
                self.assertTrue(any(isinstance(control, kinds) and control.isVisibleTo(shown)
                                    for control in shown.findChildren(QWidget)), (model, index))
            page.select_section('materials')
            saved = copy.deepcopy(page.draft())
            page.select_section('design'); page.restore_draft(saved)
            self.assertEqual(page.tabs.currentIndex(), page.sections['materials'])
        page.select_model('finite')
        page.geometry_editor.form.controls['thickness_nm'].setText('1e-')
        saved = copy.deepcopy(page.draft()); saved['section'] = page.sections['study']
        page.restore_draft(saved)
        self.assertEqual(page.tabs.currentIndex(), page.sections['design'])
        self.assertEqual(page.geometry_editor.form.controls['thickness_nm'].text(), '1e-')
        page.select_section('advanced_aperture')
        page._save_timer.stop(); page.save_draft()
        restored = self.page()
        self.assertEqual(restored.tabs.currentIndex(), restored.sections['advanced_aperture'])
        self.assertEqual(restored.geometry_editor.form.controls['thickness_nm'].text(), '1e-')

    def test_all_pcsel_papers_keep_canonical_fingerprint_until_a_physical_edit(self):
        from benchmark_registry import list_benchmarks, load_benchmark, input_fingerprint
        page = self.page()
        count = 0
        for row in list_benchmarks():
            case = load_benchmark(row['id'])
            if case['options'].get('engine') != 'pcsel': continue
            count += 1
            page.load_settings(case['options']['settings'])
            expected = input_fingerprint(case['project'], case['kind'], case['options'])
            self.assertEqual(input_fingerprint(case['project'], case['kind'], page.options()), expected, row['id'])
            page.geometry_editor.form.controls['thickness_nm'].setText('101')
            self.assertNotEqual(input_fingerprint(case['project'], case['kind'], page.options()), expected, row['id'])
        self.assertEqual(count, 6)
        page.structured['guided_modes'].tree.topLevelItem(0).child(0).setText(1, '.5')
        self.assertEqual(page.options()['settings']['guided_modes'], [.5])

    def test_preview_converts_nm_and_normalized_geometry_exactly_without_mutation(self):
        from pcsel_research import paper_example
        cfg = paper_example('hole', 'CC', .16); before = copy.deepcopy(cfg)
        device, ids = pcsel_preview_device(cfg['layers'], cfg['shapes'], [cfg['lattice_nm']]*2, repeat=3)
        self.assertEqual(cfg, before)
        self.assertAlmostEqual(device['width_um'], .295*3)
        self.assertAlmostEqual(device['layers'][0]['thickness_um'], .1)
        self.assertEqual(len(device['shapes']), 18)
        center = next(row for row in device['shapes'] if row['id'].startswith('circle-0@') and row['id'].endswith(':0:0'))
        self.assertAlmostEqual(center['size_x_um'], cfg['shapes'][0]['radius']*.295*2)
        self.assertAlmostEqual(center['cx_um'], cfg['shapes'][0]['center'][0]*.295)
        self.assertEqual(ids[center['id']], ('shapes', 'circle-0'))
        self.assertEqual(device['contacts'], [])

    def test_preview_polygon_is_physical_and_selected_layer_keeps_real_thickness(self):
        from pcsel_research import paper_example
        cfg = paper_example('hole', 'RIT', .16)
        layer = next(row for row in cfg['layers'] if row['patterned'])
        device, _ = pcsel_preview_device(cfg['layers'], cfg['shapes'], [295., 295.], layer_id=layer['id'])
        self.assertEqual(len(device['layers']), 1)
        self.assertAlmostEqual(device['layers'][0]['thickness_um'], layer['thickness_nm']/1000)
        for expected, actual in zip(cfg['shapes'][0]['vertices'], device['shapes'][0]['vertices']):
            self.assertAlmostEqual(actual[0], expected[0]*.295)
            self.assertAlmostEqual(actual[1], expected[1]*.295)

    def test_three_preview_views_and_repeat_selection_preserve_solver_request(self):
        page = self.page(); page.load_pcsel_example()
        before = copy.deepcopy(page.options()); shared = copy.deepcopy(self.store.device)
        preview = page.geometry_editor.preview
        for mode in ('3d', 'top', 'section'):
            preview.view_choice.setCurrentIndex(preview.view_choice.findData(mode))
            preview.repeat_choice.setCurrentIndex(1)
            APP.processEvents()
            self.assertEqual(preview.canvas.mode, mode)
            self.assertFalse(preview.canvas.grab().isNull())
            self.assertTrue(preview.canvas.hits)
        display_id = next(key for key, source in preview._sources.items() if source == ('shapes', 'circle-1'))
        preview._picked(display_id)
        self.assertEqual(page.geometry_editor.current_id, 'circle-1')
        self.assertEqual(page.geometry_editor.current_group, 'shapes')
        self.assertEqual(page.options(), before)
        self.assertEqual(self.store.device, shared)
        preview.scope_choice.setCurrentIndex(1)
        self.assertEqual(len(preview.canvas.device['layers']), 1)

    def test_material_diagnostic_selects_canonical_item_and_visible_control(self):
        page = self.page('pcsel_transport'); page.load_conformal_example()
        self.assertTrue(page.open_diagnostic(dict(workspace='research_studies', object_id='demo',
            field='materials.demo.electron_mobility_cm2_Vs')))
        target = page.structured['materials'].tree.currentItem()
        self.assertIsNotNone(target)
        self.assertEqual(target.text(0), 'electron_mobility_cm2_Vs')
        target.setText(1, '125')
        self.assertEqual(page.options()['settings']['materials']['demo']['electron_mobility_cm2_Vs'], 125.)
        self.assertTrue(page.friendly_forms['materials'].controls['electron_mobility_cm2_Vs'].isVisible())

    def test_coordinate_and_aperture_diagnostics_focus_exact_native_component_without_editing(self):
        page = self.page(); page.load_pcsel_example(); page.select_model('finite')
        page.resize(800, 760); page.activateWindow(); APP.processEvents()
        identity = page.options()['settings']['shapes'][1]['id']
        page.geometry_editor.select_object('shapes', identity)
        page.geometry_editor.form.controls['center'].components[1].setText('1e-')
        page.friendly_forms['aperture_um'].controls['aperture_um'].components[1].setText('2e-')
        before = copy.deepcopy(page.draft()['structured'])
        shared = copy.deepcopy(self.store.device)
        for index in (0, 1):
            page.study_flow.show_stage(2)
            self.assertTrue(page.open_diagnostic(dict(workspace='research_studies',
                field=f'settings.shapes.0.center.{index}', object_id=identity)))
            APP.processEvents()
            control = page.geometry_editor.form.controls['center'].components[index]
            self.assertTrue(control.isVisible()); self.assertIs(APP.focusWidget(), control)
            self.assertEqual(page.geometry_editor.current_id, identity)
            self.assertEqual(page.design_view_choice.currentIndex(), 1)
            self.assertEqual(page.draft()['structured'], before)
        for index in (0, 1):
            page.study_flow.show_stage(2)
            self.assertTrue(page.open_diagnostic(dict(workspace='research_studies',
                field=f'aperture_um.{index}')))
            APP.processEvents()
            control = page.friendly_forms['aperture_um'].controls['aperture_um'].components[index]
            self.assertTrue(control.isVisible()); self.assertIs(APP.focusWidget(), control)
            self.assertEqual(page.design_view_choice.currentIndex(), 0)
            self.assertEqual(page.draft()['structured'], before)
        self.assertEqual(self.store.device, shared)

    def test_conformal_coordinate_and_cell_diagnostics_select_exact_component(self):
        page = self.page('pcsel_transport'); page.load_conformal_example()
        page.resize(800, 760); page.activateWindow(); APP.processEvents()
        identity = page.options()['settings']['inclusions'][0]['id']
        page.geometry_editor.select_object('inclusions', identity)
        page.geometry_editor.form.controls['center_um'].components[1].setText('unfinished')
        page.period_form.controls['period_um'].components[1].setText('4e-')
        before = copy.deepcopy(page.draft()['structured'])
        self.assertTrue(page.open_diagnostic(dict(workspace='research_studies',
            field='inclusions.0.center_um.1', object_id=identity)))
        APP.processEvents()
        self.assertIs(APP.focusWidget(), page.geometry_editor.form.controls['center_um'].components[1])
        self.assertEqual(page.geometry_editor.current_id, identity)
        self.assertTrue(page.open_diagnostic(dict(workspace='research_studies', field='period_um.1')))
        APP.processEvents()
        self.assertIs(APP.focusWidget(), page.period_form.controls['period_um'].components[1])
        self.assertEqual(page.draft()['structured'], before)


if __name__ == '__main__': unittest.main()
