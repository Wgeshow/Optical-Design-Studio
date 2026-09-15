import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from model import LAYER_COLS, MAT_COLS, PAT_COLS, prepare
from structure_sync import (HOLE_COLS, initial_hole_sync, records, structure_hole_ranges,
                            structure_summary, sync_hole_ranges)
from target_ui import target_project


MATERIALS = [['Air', 'constant_nk', 1, 0, '', 'nm'], ['Silicon', 'constant_nk', 3.4, .01, '', 'nm'],
             ['Glass', 'constant_nk', 1.45, 0, '', 'nm']]
LAYERS = [['Top', 0, 'Air'], ['PCS one', .2, 'Silicon'], ['PCS two', .3, 'Silicon'], ['Bottom', 0, 'Glass']]
PATTERNS = [['ellipse', 'PCS one', 'Air', .02, -.03, .1, .08, 25],
            ['circle', 'PCS two', 'Air', -.02, .01, .12, 0, 0]]


class StructureSyncTests(unittest.TestCase):
    def test_source_sizes_follow_changes_without_reimport(self):
        holes, state = initial_hole_sync(MATERIALS, LAYERS, PATTERNS)
        changed = copy.deepcopy(PATTERNS)
        changed[0][5:7] = [.16, .09]
        result, _ = sync_hole_ranges(holes, state, MATERIALS, LAYERS, changed)
        self.assertEqual(result.iloc[0].tolist(), ['PCS one', 'ellipse', .16, .16, .09, .09])

    def test_manual_limits_and_explicit_removals_survive_geometry_changes(self):
        holes, state = initial_hole_sync(MATERIALS, LAYERS, PATTERNS)
        holes.loc[0, ['MinX_um', 'MaxX_um']] = [.07, .2]
        holes = holes.iloc[:1]
        changed = copy.deepcopy(PATTERNS)
        changed[0][5] = .15
        updated, state = sync_hole_ranges(holes, state, MATERIALS, LAYERS, changed)
        self.assertEqual(updated.iloc[0]['MinX_um'], .07)
        self.assertEqual(updated.iloc[0]['MaxX_um'], .2)
        self.assertEqual(updated.Layer.tolist(), ['PCS one'])
        again, _ = sync_hole_ranges(updated, state, MATERIALS, LAYERS, PATTERNS)
        self.assertEqual(again.Layer.tolist(), ['PCS one'])

    def test_explicit_fixed_manual_range_is_not_overwritten(self):
        holes, state = initial_hole_sync(MATERIALS, LAYERS, PATTERNS)
        state['manual'] = ['PCS one']
        changed = copy.deepcopy(PATTERNS)
        changed[0][5] = .18
        result, _ = sync_hole_ranges(holes, state, MATERIALS, LAYERS, changed)
        self.assertEqual(result.iloc[0]['MinX_um'], .1)
        self.assertEqual(result.iloc[0]['MaxX_um'], .1)

    def test_added_renamed_and_deleted_layers_update_automatic_rows(self):
        holes, state = initial_hole_sync(MATERIALS, LAYERS, PATTERNS)
        layers = [LAYERS[0], ['Renamed PCS', .25, 'Silicon'], ['New PCS', .15, 'Silicon'], LAYERS[-1]]
        patterns = [PATTERNS[0].copy(), ['circle', 'New PCS', 'Air', 0, 0, .06, 0, 0]]
        patterns[0][1] = 'Renamed PCS'
        updated, _ = sync_hole_ranges(holes, state, MATERIALS, layers, patterns)
        self.assertEqual(updated.Layer.tolist(), ['Renamed PCS', 'New PCS'])

    def test_nonair_and_ambiguous_multiple_air_regions_are_not_auto_selected(self):
        patterns = copy.deepcopy(PATTERNS)
        patterns[0][2] = 'Glass'
        patterns.append(['rectangle', 'PCS two', 'Air', .2, .2, .05, .05, 0])
        self.assertEqual(structure_hole_ranges(MATERIALS, LAYERS, patterns), [])

    def test_target_preserves_offset_rotation_and_other_regions_in_same_layer(self):
        project = dict(materials=records(MATERIALS, MAT_COLS), layers=records(LAYERS, LAYER_COLS),
                       patterns=records(PATTERNS, PAT_COLS), settings={})
        inclusion = dict(zip(PAT_COLS, ['rectangle', 'PCS one', 'Glass', -.2, .2, .03, .04, 5]))
        project['patterns'].append(inclusion)
        original = copy.deepcopy(project)
        holes = structure_hole_ranges(MATERIALS, LAYERS, PATTERNS)
        holes[0]['MinX_um'], holes[0]['MaxX_um'] = .08, .18
        updated, bounds = target_project(project, holes, [], 1550, 5, 1000, 20, .1, 3)
        self.assertEqual(project, original)
        self.assertEqual(updated['patterns'][-1], inclusion)
        self.assertEqual(len(updated['patterns']), len(original['patterns']))
        for before, after in zip(original['patterns'], updated['patterns']):
            for key in ('Layer', 'Material', 'CenterX_um', 'CenterY_um', 'Angle_deg'):
                self.assertEqual(before[key], after[key])
        self.assertAlmostEqual(updated['patterns'][0]['SizeX_um'], .13)
        self.assertEqual(bounds[0]['Target'], '1')

    def test_target_rejects_ambiguous_hole_instead_of_replacing_patterns(self):
        project = dict(materials=records(MATERIALS, MAT_COLS), layers=records(LAYERS, LAYER_COLS),
                       patterns=records(PATTERNS, PAT_COLS), settings={})
        project['patterns'].append(dict(zip(PAT_COLS, ['circle', 'PCS one', 'Air', .2, .2, .03, 0, 0])))
        original = copy.deepcopy(project)
        holes = structure_hole_ranges(MATERIALS, LAYERS, PATTERNS)
        with self.assertRaisesRegex(ValueError, 'Explore designs'):
            target_project(project, holes, [], 1550, 5, 1000, 20, .1, 3)
        self.assertEqual(project, original)

    def test_shared_summary_identifies_current_stack_and_saved_snapshot_semantics(self):
        summary = structure_summary(MATERIALS, LAYERS, PATTERNS, .7, .8)
        self.assertIn('2 finite layers', summary)
        self.assertIn('PCS one → PCS two', summary)
        self.assertIn('Saved results keep the design', summary)


class SharedWorkflowTests(unittest.TestCase):
    def test_applied_six_finite_layer_stack_is_consumed_by_every_workflow(self):
        import app
        from data_library import DataLibrary
        from structure_builder import mutate_structure

        captured = []

        def capture_backend(model, performance, session, **kwargs):
            captured.append(copy.deepcopy((model, kwargs)))
            yield from ()

        with tempfile.TemporaryDirectory(prefix='s4_shared_structure_') as temp:
            library = DataLibrary(temp)
            with patch.object(app, 'LIBRARY', library), patch.object(app, 'RUNS', library.runs), \
                    patch.object(app, 'run_backend', capture_backend):
                demo = app.build_ui()
                endpoints = {fn.api_name: fn for fn in demo.fns.values() if fn.fn is not None}
                m, l, p, _, _ = mutate_structure(app, app.DEFAULT_MATERIALS, app.DEFAULT_LAYERS,
                    app.DEFAULT_PATTERNS, 'Device', 'repeat', start='Device', end='Device', count=5)
                m, l, p, _, _ = mutate_structure(app, m, l, p, 'Device_copy_3', 'apply',
                    name='Tunable cavity', material='current:GaAs', thickness=347, unit='nm')
                self.assertEqual(len(l) - 2, 6)
                shared = endpoints['run_simulation'].inputs[:3]
                for name in ('search_peaks', 'search_target_wavelength', 'calculate_electric_fields',
                             'save_portable_project', 'save_project'):
                    self.assertEqual(endpoints[name].inputs[:3], shared, name)
                settings = list(app.SET_DEFAULTS)
                values = settings + list(app.DEFAULT_PERFORMANCE.values())
                expected = prepare(app.records(m, MAT_COLS), app.records(l, LAYER_COLS), app.records(p, PAT_COLS),
                                   {}, dict(zip(app.SET_KEYS, settings)))
                for name in ('run_simulation', 'search_peaks', 'search_target_wavelength', 'calculate_electric_fields'):
                    endpoint = endpoints[name]
                    inputs = [component.value for component in endpoint.inputs]
                    inputs[:4] = [m, l, p, None]
                    if name == 'search_target_wavelength':
                        inputs[4] = pd.DataFrame(structure_hole_ranges(m, l, p), columns=HOLE_COLS)
                    output = list(endpoint.fn(None, *inputs))
                    self.assertEqual(len(captured), ('run_simulation', 'search_peaks',
                        'search_target_wavelength', 'calculate_electric_fields').index(name) + 1, (name, output))
                    for key in ('layers', 'patterns', 'materials'):
                        self.assertEqual(captured[-1][0][key], expected[key], (name, key))
                saved = endpoints['save_portable_project'].fn(m, l, p, None, *values)
                project = json.loads(Path(saved).read_text())
                self.assertEqual(project['layers'], app.records(l, LAYER_COLS))
                self.assertEqual(project['patterns'], app.records(p, PAT_COLS))
                displays = [fn for fn in demo.fns.values() if fn.fn is not None and fn.fn.__name__ == 'display']
                for display in displays:
                    dropdown = display.fn('thickness', l, p, 'Device_copy_3', [], m)[0]
                    self.assertEqual([value for _, value in dropdown.choices], l.Name.tolist()[1:-1])
                field_refresh = next(fn for fn in demo.fns.values()
                                     if fn.fn is not None and fn.fn.__name__ == 'refresh_field_layers')
                dropdown = field_refresh.fn(l, 'Device_copy_3')
                self.assertEqual([value for _, value in dropdown.choices][1:], l.Name.tolist()[1:-1])
                self.assertEqual(dropdown.value, '')


if __name__ == '__main__':
    unittest.main()
