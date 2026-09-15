import json
import unittest

import gradio as gr
import pandas as pd

from bounds_editor import (BOUND_COLS, HOLE_COLS, build_bounds_editor, build_hole_editor,
                           finite_layers, prune_bounds, rows, target_choices, upsert_bound, upsert_hole)
from model import LAYER_COLS, MAT_COLS, PAT_COLS


MATERIALS = [['Air', 'constant_nk', 1, 0, '', 'nm'], ['Silicon', 'constant_nk', 3.4, 0, '', 'nm'],
             ['Glass', 'constant_nk', 1.45, 0, '', 'nm']]
LAYERS = [['Ambient', 0, 'Air'], ['PCS one', .2, 'Silicon'], ['Spacer', .5, 'Glass'],
          ['PCS two', .3, 'Silicon'], ['Substrate', 0, 'Glass']]
PATTERNS = [['circle', 'PCS one', 'Air', 0, 0, .1, 0, 0], ['ellipse', 'PCS two', 'Air', 0, 0, .15, .1, 0]]


def editor_callbacks():
    """Use the actual registered callbacks, including their declared outputs."""
    with gr.Blocks() as demo:
        materials = gr.Dataframe(MATERIALS, headers=MAT_COLS)
        layers = gr.Dataframe(LAYERS, headers=LAYER_COLS)
        patterns = gr.Dataframe(PATTERNS, headers=PAT_COLS)
        build_bounds_editor(materials, layers, patterns)
        build_hole_editor(layers, patterns)
    return demo, {fn.fn.__name__: fn for fn in demo.fns.values()}


def component_setting(update, name):
    """Handle both component replacements and Gradio update dictionaries."""
    return update.get(name) if isinstance(update, dict) else getattr(update, name)


class BoundsEditorTests(unittest.TestCase):
    def add(self, value, parameter, target='', low=.1, high=.2, step=.01, choices=None):
        return upsert_bound(value, parameter, target, low, high, step, MATERIALS, LAYERS, PATTERNS, choices)

    def test_finite_layers_and_meaningful_pattern_targets(self):
        self.assertEqual(finite_layers(LAYERS), ['PCS one', 'Spacer', 'PCS two'])
        self.assertEqual([value for _, value in target_choices('thickness', LAYERS, PATTERNS)], finite_layers(LAYERS))
        choices = target_choices('radius', LAYERS, PATTERNS)
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0][1], '1')
        self.assertIn('PCS one', choices[0][0])
        self.assertIn('circle', choices[0][0])

    def test_material_multiselect_preserves_canonical_backend_format(self):
        bounds = self.add([], 'layer_material', 'PCS one', choices=['Silicon', 'Glass', 'Silicon'])
        self.assertEqual(list(bounds.columns), BOUND_COLS)
        self.assertEqual(bounds.iloc[0]['Choices'], 'Silicon;Glass')
        self.assertIsNone(bounds.iloc[0]['Min'])
        with self.assertRaisesRegex(ValueError, 'library'):
            self.add([], 'layer_material', 'PCS one', choices=['Deleted material'])

    def test_reapplying_same_parameter_updates_one_range(self):
        bounds = self.add([], 'thickness', 'PCS one')
        bounds = self.add(bounds, 'thickness', 'PCS one', high=.4)
        self.assertEqual(len(bounds), 1)
        self.assertEqual(bounds.iloc[0]['Max'], .4)

    def test_conflicting_geometric_ranges_are_rejected_before_search(self):
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.add(self.add([], 'lattice_square'), 'lattice_x')
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.add(self.add([], 'radius', '1'), 'size_x', '1')
        with self.assertRaisesRegex(ValueError, 'current layer or pattern'):
            self.add([], 'radius', '2')
        with self.assertRaisesRegex(ValueError, 'current layer or pattern'):
            self.add([], 'thickness', 'Ambient')

    def test_numeric_validation_and_position_bounds(self):
        for low, high, step in [(float('nan'), .2, .01), (.2, .1, .01), (.1, .2, 0)]:
            with self.assertRaises(ValueError):
                self.add([], 'radius', '1', low=low, high=high, step=step)
        with self.assertRaisesRegex(ValueError, 'below 0.6'):
            self.add([], 'r_over_a', '1', high=.6)
        bounds = self.add([], 'center_x', '2', low=-.2, high=.2)
        self.assertEqual(bounds.iloc[0]['Min'], -.2)

    def test_changed_patterns_do_not_retarget_old_numeric_indices(self):
        bounds = self.add([], 'radius', '1')
        bounds = self.add(bounds, 'thickness', 'PCS one')
        cleaned, removed = prune_bounds(bounds, MATERIALS, LAYERS, list(reversed(PATTERNS)), patterns_changed=True)
        self.assertEqual(removed, 1)
        self.assertEqual(cleaned.iloc[0]['Parameter'], 'thickness')

    def test_removed_material_or_layer_invalidates_affected_range(self):
        bounds = self.add([], 'layer_material', 'PCS one', choices=['Silicon', 'Glass'])
        bounds = self.add(bounds, 'thickness', 'PCS two')
        remaining = [row for row in LAYERS if row[0] != 'PCS two']
        cleaned, removed = prune_bounds(bounds, MATERIALS[:2], remaining, PATTERNS)
        self.assertEqual(removed, 2)
        self.assertTrue(cleaned.empty)

    def test_hole_bounds_upsert_per_layer_and_handle_shape_dimensions(self):
        bounds = upsert_hole([], 'PCS one', 'circle', .1, .2, None, None, LAYERS)
        self.assertEqual(bounds.iloc[0]['MaxY_um'], 0)
        bounds = upsert_hole(bounds, 'PCS one', 'rectangle', .2, .4, .1, .3, LAYERS)
        bounds = upsert_hole(bounds, 'PCS two', 'ellipse', .1, .2, .1, .15, LAYERS)
        self.assertEqual(list(bounds.columns), HOLE_COLS)
        self.assertEqual(len(bounds), 2)
        self.assertEqual(bounds.iloc[0]['Shape'], 'rectangle')
        with self.assertRaises(ValueError):
            upsert_hole(bounds, 'Substrate', 'circle', .1, .2, None, None, LAYERS)
        with self.assertRaises(ValueError):
            upsert_hole(bounds, 'PCS two', 'ellipse', .1, .2, .3, .1, LAYERS)

    def test_gradio_component_values_and_editor_construction(self):
        with gr.Blocks() as demo:
            materials = gr.Dataframe(MATERIALS, headers=MAT_COLS)
            layers = gr.Dataframe(LAYERS, headers=LAYER_COLS)
            patterns = gr.Dataframe(PATTERNS, headers=PAT_COLS)
            self.assertEqual(rows(materials.value, MAT_COLS)[1]['Name'], 'Silicon')
            bounds = build_bounds_editor(materials, layers, patterns)
            holes = build_hole_editor(layers, patterns)
        self.assertFalse(bounds.interactive)
        self.assertFalse(holes.interactive)
        labels = [component.get('props', {}).get('label') for component in demo.config['components']]
        self.assertIn('Allowed materials', labels)
        self.assertIn('PCS layer', labels)
        # One serialized listener sees the whole structure; independent source
        # callbacks could otherwise prune bounds using inconsistent snapshots.
        refresh = [(identifier, fn) for identifier, fn in demo.fns.items()
                   if fn.fn.__name__ == 'refresh' and len(fn.inputs) == 8]
        self.assertEqual(len(refresh), 1)
        dependency = next(item for item in demo.config['dependencies'] if item['id'] == refresh[0][0])
        self.assertEqual(len(dependency['targets']), 3)
        self.assertTrue(dependency['queue'])
        self.assertEqual(dependency['trigger_mode'], 'always_last')
        self.assertEqual(dependency['api_visibility'], 'private')
        display_id = next(identifier for identifier, fn in demo.fns.items() if fn.fn.__name__ == 'display')
        display = next(item for item in demo.config['dependencies'] if item['id'] == display_id)
        self.assertEqual(display['targets'][0][1], 'input')


class RangeSelectionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo, cls.callbacks = editor_callbacks()

    def invoke(self, name, *arguments):
        callback = self.callbacks[name]
        result = callback.fn(*arguments)
        self.assertEqual(len(result), len(callback.outputs), name)
        return tuple(item for item, component in zip(result, callback.outputs) if not isinstance(component, gr.State))

    @staticmethod
    def range_key(parameter, target):
        return 'range:' + json.dumps([parameter, target], ensure_ascii=False, separators=(',', ':'))

    def range_table(self):
        first = upsert_bound([], 'thickness', 'PCS one', .1, .2, .01, MATERIALS, LAYERS, PATTERNS, [])
        return upsert_bound(first, 'thickness', 'PCS two', .3, .5, .02, MATERIALS, LAYERS, PATTERNS, [])

    def assert_preserved(self, result):
        self.assertTrue(all(item == gr.skip() for item in result[:-1]), result)
        self.assertIsInstance(result[-1], str)
        self.assertTrue(result[-1])

    def test_empty_range_load_preserves_form_and_returns_guidance(self):
        self.assert_preserved(self.invoke('load_range', [], None, LAYERS, PATTERNS, MATERIALS))

    def test_invalid_range_selections_preserve_form_and_table(self):
        bounds = self.range_table()
        invalid = [None, '', '-1', '0', 'not-a-range', self.range_key('thickness', 'Removed layer')]
        for selection in invalid:
            with self.subTest(selection=selection):
                self.assert_preserved(self.invoke('load_range', bounds, selection, LAYERS, PATTERNS, MATERIALS))
                self.assert_preserved(self.invoke('remove_range', bounds, selection))

    def test_selected_range_survives_refresh_and_previous_row_removal(self):
        bounds = self.range_table()
        selected = self.range_key('thickness', 'PCS two')
        refreshed = self.invoke('list_ranges', bounds, LAYERS, PATTERNS, selected)
        self.assertEqual(component_setting(refreshed[0], 'value'), selected)
        self.assertTrue(all(component_setting(item, 'interactive') for item in refreshed))
        removed = self.invoke('remove_range', bounds, self.range_key('thickness', 'PCS one'))[0]
        refreshed = self.invoke('list_ranges', removed, LAYERS, PATTERNS, selected)
        self.assertEqual(component_setting(refreshed[0], 'value'), selected)
        loaded = self.invoke('load_range', removed, selected, LAYERS, PATTERNS, MATERIALS)
        self.assertEqual(loaded[0], 'thickness')
        self.assertEqual(component_setting(loaded[1], 'value'), 'PCS two')
        self.assertEqual(component_setting(loaded[3], 'value'), .3)
        self.assertEqual(component_setting(loaded[4], 'value'), .5)

    def test_removed_selection_never_loads_new_row_at_old_index(self):
        bounds = self.range_table()
        removed_key = self.range_key('thickness', 'PCS one')
        remaining = self.invoke('remove_range', bounds, removed_key)[0]
        self.assert_preserved(self.invoke('load_range', remaining, removed_key, LAYERS, PATTERNS, MATERIALS))
        refreshed = self.invoke('list_ranges', remaining, LAYERS, PATTERNS, removed_key)
        self.assertIsNone(component_setting(refreshed[0], 'value'))
        self.assertTrue(component_setting(refreshed[0], 'interactive'))
        self.assertTrue(all(not component_setting(item, 'interactive') for item in refreshed[1:]))

    def test_range_with_removed_structure_reference_preserves_form(self):
        bounds = self.range_table()
        changed_layers = [row for row in LAYERS if row[0] != 'PCS one']
        self.assert_preserved(self.invoke('load_range', bounds, self.range_key('thickness', 'PCS one'),
                                          changed_layers, PATTERNS, MATERIALS))
        material_range = upsert_bound([], 'layer_material', 'PCS one', None, None, None,
                                      MATERIALS, LAYERS, PATTERNS, ['Silicon', 'Glass'])
        self.assert_preserved(self.invoke('load_range', material_range, self.range_key('layer_material', 'PCS one'),
                                          LAYERS, PATTERNS, MATERIALS[:2]))

    def test_empty_lists_and_missing_selections_disable_actions(self):
        refreshed = self.invoke('list_ranges', [], LAYERS, PATTERNS, None)
        self.assertIsNone(component_setting(refreshed[0], 'value'))
        self.assertTrue(all(not component_setting(item, 'interactive') for item in refreshed))
        bounds = self.range_table()
        for selection, enabled in [(None, False), ('0', False), (self.range_key('thickness', 'PCS one'), True)]:
            with self.subTest(selection=selection):
                buttons = self.invoke('range_actions', bounds, selection)
                self.assertEqual([component_setting(item, 'interactive') for item in buttons], [enabled, enabled])
        buttons = {'Load range into editor', 'Remove range', 'Load hole into editor', 'Remove hole range'}
        initial = [component['props'] for component in self.demo.config['components']
                   if component['type'] == 'button' and component['props'].get('value') in buttons]
        self.assertEqual(len(initial), len(buttons))
        self.assertTrue(all(not item['interactive'] for item in initial))

    def test_range_identifiers_are_unambiguous_for_unicode_layer_names(self):
        layers = [['Ambient', 0, 'Air'], ['PCS · α : 1', .2, 'Silicon'], ['Substrate', 0, 'Glass']]
        bounds = upsert_bound([], 'thickness', 'PCS · α : 1', .1, .2, .01, MATERIALS, layers, [], [])
        key = self.range_key('thickness', 'PCS · α : 1')
        refreshed = self.invoke('list_ranges', bounds, layers, [], key)
        self.assertEqual(component_setting(refreshed[0], 'choices')[0][1], key)
        loaded = self.invoke('load_range', bounds, key, layers, [], MATERIALS)
        self.assertEqual(component_setting(loaded[1], 'value'), 'PCS · α : 1')

    def test_empty_or_stale_hole_load_preserves_form(self):
        holes = upsert_hole([], 'PCS one', 'rectangle', .2, .4, .1, .3, LAYERS)
        for data, selected in [([], None), (holes, None), (holes, 'Removed layer')]:
            with self.subTest(selected=selected):
                self.assert_preserved(self.invoke('load_hole', data, selected))
                self.assert_preserved(self.invoke('remove_hole', data, selected))

    def test_hole_selection_survives_refresh_and_clears_only_if_removed(self):
        holes = upsert_hole([], 'PCS one', 'rectangle', .2, .4, .1, .3, LAYERS)
        holes = upsert_hole(holes, 'PCS two', 'ellipse', .1, .2, .1, .15, LAYERS)
        selected = self.invoke('selection_choices', holes, 'PCS two')
        self.assertEqual(component_setting(selected[0], 'value'), 'PCS two')
        self.assertTrue(all(component_setting(item, 'interactive') for item in selected))
        remaining = self.invoke('remove_hole', holes, 'PCS one')[0]
        selected = self.invoke('selection_choices', remaining, 'PCS two')
        self.assertEqual(component_setting(selected[0], 'value'), 'PCS two')
        missing = self.invoke('selection_choices', remaining, 'PCS one')
        self.assertIsNone(component_setting(missing[0], 'value'))
        self.assertTrue(all(not component_setting(item, 'interactive') for item in missing[1:]))
        empty = self.invoke('selection_choices', [], None)
        self.assertTrue(all(not component_setting(item, 'interactive') for item in empty))
        for selected, enabled in [(None, False), ('PCS one', False), ('PCS two', True)]:
            with self.subTest(selected=selected):
                buttons = self.invoke('hole_actions', remaining, selected)
                self.assertEqual([component_setting(item, 'interactive') for item in buttons], [enabled, enabled])


if __name__ == '__main__':
    unittest.main()
