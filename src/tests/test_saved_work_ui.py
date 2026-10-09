"""Selection integrity for the named material, saved-work and field browsers."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_library import DataLibrary, write_json
from field_tracking_ui import common_layers, comparison_summary, dataset_selection, natural_key, saved_datasets
from library_ui import csv_choices, keep_choice, material_row_choices, saved_design_choices, saved_entry_choices
from model import MAT_COLS


def rows(df, columns):
    return pd.DataFrame(df, columns=columns).to_dict('records')


def snapshot(path, layer='PCS', material='Film'):
    path.mkdir(parents=True)
    model = dict(ax=1., ay=1., patterns=[], layers=[dict(name='Top', material='Air', thickness=0.),
        dict(name=layer, material=material, thickness=.3), dict(name='Bottom', material='Air', thickness=0.)])
    write_json(path / 'field_model.json', dict(model=model, wavelength_nm=1550, settings=dict(sampling_mode='fixed_target')))
    write_json(path / 'field_features.json', {})
    (path / 'electric_fields.csv').write_text('plane,layer,E2\nxy,PCS,1\n')
    return model


class SavedWorkUITests(unittest.TestCase):
    def test_selection_preserves_valid_values_and_clears_empty_lists(self):
        choices = [('First', 2), ('Second', 10)]
        self.assertEqual(keep_choice(choices, 10), 10)
        self.assertEqual(keep_choice(choices, 99), 2)
        self.assertIsNone(keep_choice([], 10))
        fields = [('Design 2', 'r/design2'), ('Design 10', 'r/design10')]
        self.assertEqual(dataset_selection(fields, 'r/design10', 'r/design2'), ('r/design10', 'r/design2', ['r/design2', 'r/design10'], 1))

    def test_named_materials_keep_real_row_ids(self):
        table = pd.DataFrame([['Air', 'constant_nk', 1, 0, '', 'nm'],
                              ['Film', 'table_nk', None, None, 'film.csv', 'um']], columns=MAT_COLS)
        choices = material_row_choices(table, rows)
        self.assertEqual([choice[1] for choice in choices], [1, 2])
        self.assertIn('Film', choices[1][0])
        self.assertIn('wavelength-dependent', choices[1][0])
        self.assertEqual(material_row_choices({'headers': MAT_COLS, 'data': table.values.tolist()}, rows), choices)

    def test_design_dropdown_uses_persisted_ids_in_numeric_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / 'project.json', {'materials': []})
            model = {'layers': [{'name': 'Top'}, {'name': 'Device', 'material': 'Film'}, {'name': 'Bottom'}]}
            with (root / 'design_models.jsonl').open('w') as stream:
                for design in (10, 2, 2, -1):
                    stream.write(json.dumps({'design_id': design, 'model': model}) + '\n')
                stream.write('{interrupted line\n')
            choices = saved_design_choices(root)
            self.assertEqual([value for _, value in choices], [0, 2, 10])
            self.assertIn('Film', choices[1][0])
            (root / 'project.json').unlink()
            self.assertEqual([value for _, value in saved_design_choices(root)], [2, 10])

    def test_result_labels_keep_original_paths_and_natural_design_order(self):
        choices = csv_choices(['design10/spectrum.csv', 'design2/spectrum.csv', 'target_results.csv'])
        self.assertEqual([value for _, value in choices][:2], ['design2/spectrum.csv', 'design10/spectrum.csv'])
        self.assertIn('ranked designs', choices[-1][0])
        self.assertEqual(sorted(['design10', 'design2', 'design1'], key=natural_key), ['design1', 'design2', 'design10'])

    def test_shared_layers_are_dropdown_choices_and_preserve_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            library = DataLibrary(Path(temp))
            a = library.runs / 'run' / 'design2' / 'fields'
            b = library.runs / 'run' / 'design10' / 'fields'
            snapshot(a)
            snapshot(b)
            write_json(library.runs / 'run' / 'library_record.json', {'title': 'Thickness scan', 'created': '2026-09-12T14:30:00+00:00'})
            choices = saved_datasets(library)
            self.assertEqual([value for _, value in choices], ['run/design2/fields', 'run/design10/fields'])
            self.assertIn('Thickness scan', choices[0][0])
            self.assertIn('Design 2', choices[0][0])
            self.assertIn('Film', choices[0][0])
            common, value = common_layers(library, choices[0][1], choices[1][1], 'PCS')
            self.assertEqual(value, 'PCS')
            self.assertEqual(common, [('PCS · Film', 'PCS')])
            path = b / 'field_model.json'
            saved = json.loads(path.read_text())
            saved['model']['layers'][1]['name'] = 'Other'
            write_json(path, saved)
            self.assertEqual(common_layers(library, choices[0][1], choices[1][1]), ([], None))
            self.assertEqual(common_layers(library, None, choices[1][1]), ([], None))

    def test_saved_run_label_does_not_require_reading_an_internal_id(self):
        choices = saved_entry_choices([dict(id='f12ac7', title='Silicon cavity scan', kind='optimization', created='2026-09-12T14:30:00+00:00', status='complete')])
        self.assertEqual(choices[0][1], 'f12ac7')
        self.assertIn('Silicon cavity scan', choices[0][0])
        self.assertNotIn('f12ac7', choices[0][0])

    def test_field_summary_keeps_units_and_undefined_positions(self):
        payload = {'comparison': {'layers': {'PCS': {'field_overlap': .9, 'E2_fraction_change': .125,
                    'centroid_displacement_um': {'x': None, 'y': .2, 'z': -.1}, 'mean_E2_ratio': 2.}}}}
        row = comparison_summary(payload).iloc[0]
        self.assertEqual(row['Confinement change (percentage points)'], 12.5)
        self.assertEqual(row['Centroid Δz (µm)'], -.1)
        self.assertTrue(pd.isna(row['Centroid Δx (µm)']))


if __name__ == '__main__':
    unittest.main()
