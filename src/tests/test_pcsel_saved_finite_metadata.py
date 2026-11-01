"""Saved-field compatibility fixtures only; no scientific solver is executed."""
import copy
import csv
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pcsel_research as pc


class SavedFiniteMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='saved-finite-fixture-',
            dir=Path(os.environ.get('ODS_TEST_TMPDIR', Path(__file__).resolve().parents[3])))
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        settings = dict(model='beam', beam_saved_run=str(self.folder), lattice_nm=320.,
            inclusion_index=1., bottom_index=3.1, reference_wavelength_nm=1075., layers=[
            dict(id='source-top', name='Top', thickness_nm=100., index=3., qw=False, patterned=False),
            dict(id='source-core', name='Core', thickness_nm=200., index=3.4, qw=True, patterned=True),
            dict(id='source-bottom', name='Bottom', thickness_nm=300., index=3.1, qw=False, patterned=False)],
            shapes=[dict(id='hole-left', name='Left', shape='circle', center=[-.2, 0.], radius=.05),
                    dict(id='hole-right', name='Right', shape='circle', center=[.2, 0.], radius=.06)])
        self.cfg = pc.prepare({}, settings)
        self.original = copy.deepcopy(self.cfg)
        self.original['model'] = 'finite'
        self.write_inputs()
        self.mode = dict(mode=0, label='Synthetic', accepted=True, balance_relative=0.,
            eigen_residual=0., total_loss_cm1=2., radiation_loss_cm1=1., edge_loss_cm1=1.)
        with (self.folder/'finite_modes.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.mode))
            writer.writeheader(); writer.writerow(self.mode)
        self.fields = np.ones((1, 4, 2, 2), dtype=complex)
        np.savez(self.folder/'finite_fields.npz', x=np.array([0., 1.]),
            fields=self.fields, aperture_um=np.asarray(self.cfg['aperture_um']))
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.vertical_operator = pc.vertical
        self.guards = [self.stack.enter_context(patch.object(pc, name,
            side_effect=AssertionError('Scientific solver execution forbidden')))
            for name in ('vertical', 'coupling', 'finite_modes', 'far_field')]

    def write_inputs(self):
        (self.folder/'pcsel_inputs.json').write_text(json.dumps(self.original), encoding='utf-8')

    def renamed(self):
        cfg = copy.deepcopy(self.cfg)
        for group in ('layers', 'shapes'):
            for index, row in enumerate(cfg[group]):
                row['id'] = 'independent-'+group+'-'+str(index)
                row['name'] = 'Independently authored '+str(index)
        return cfg

    def assert_rejected(self, cfg, key):
        with patch.object(pc.np, 'load', side_effect=AssertionError('Do not load incompatible fields')) as load:
            with self.assertRaises(pc.InputValidationError) as caught:
                pc._saved_finite(cfg)
        self.assertIn(key, str(caught.exception)); load.assert_not_called()

    def test_independently_named_rows_reuse_exact_saved_fields(self):
        before = copy.deepcopy(self.original)
        modes, fields = pc._saved_finite(self.renamed())
        self.assertEqual(modes, [self.mode])
        np.testing.assert_array_equal(fields['fields'], self.fields)
        self.assertEqual(json.loads((self.folder/'pcsel_inputs.json').read_text()), before)
        for guard in self.guards: guard.assert_not_called()

    def test_matching_metadata_still_loads_saved_fields(self):
        modes, fields = pc._saved_finite(self.cfg)
        self.assertEqual(modes, [self.mode])
        np.testing.assert_array_equal(fields['fields'], self.fields)

    def test_metadata_does_not_enter_vertical_operator_or_shape_coefficients(self):
        operators = []
        def stub_eigen(diagonal, off_diagonal, **options):
            operators.append((diagonal.copy(), off_diagonal.copy(), options))
            return np.array([1e-4]), np.ones((len(diagonal), 1))
        with patch.object(pc, 'eigh_tridiagonal', side_effect=stub_eigen):
            row, profile = self.vertical_operator(self.cfg)
            renamed_row, renamed_profile = self.vertical_operator(self.renamed())
        self.assertEqual(len(operators), 2)
        for left, right in zip(operators[0][:2], operators[1][:2]):
            np.testing.assert_array_equal(left, right)
        self.assertEqual(operators[0][2], operators[1][2])
        self.assertEqual(row, renamed_row)
        for key in profile: np.testing.assert_array_equal(profile[key], renamed_profile[key])
        for source, renamed in zip(self.cfg['shapes'], self.renamed()['shapes']):
            for q in ([0, 0], [1, 0], [0, -1], [2, 3]):
                self.assertEqual(pc.shape_fourier(source, q), pc.shape_fourier(renamed, q))

    def test_absent_descriptive_metadata_is_nonphysical(self):
        for group in ('layers', 'shapes'):
            for row in self.original[group]:
                row.pop('id'); row.pop('name', None)
        self.write_inputs()
        self.assertEqual(pc._saved_finite(self.cfg)[0], [self.mode])

    def test_layer_geometry_index_and_roles_remain_exact(self):
        for key, value in [('thickness_nm', 200.00000000000003), ('index', 3.4000000000000004),
                           ('qw', False), ('patterned', False)]:
            cfg = self.renamed(); cfg['layers'][1][key] = value
            with self.subTest(key=key): self.assert_rejected(cfg, 'layers')

    def test_shape_geometry_kind_and_unknown_material_index_remain_exact(self):
        for key, value in [('radius', .05000000000000001), ('center', [-.20000000000000004, 0.]),
                           ('shape', 'polygon'), ('index', 1.2), ('material_index', 2.)]:
            cfg = self.renamed(); cfg['shapes'][0][key] = value
            with self.subTest(key=key): self.assert_rejected(cfg, 'shapes')

    def test_layer_and_shape_order_and_row_count_remain_exact(self):
        for group in ('layers', 'shapes'):
            for change in ('reverse', 'remove', 'duplicate'):
                cfg = self.renamed()
                if change == 'reverse': cfg[group].reverse()
                elif change == 'remove': cfg[group].pop()
                else: cfg[group].append(copy.deepcopy(cfg[group][-1]))
                with self.subTest(group=group, change=change): self.assert_rejected(cfg, group)

    def test_unknown_fields_and_nested_id_name_are_not_stripped(self):
        for group in ('layers', 'shapes'):
            for value in (7., {'id': 'physical-reference', 'name': 'physical-choice'}):
                cfg = self.renamed(); cfg[group][0]['future_property'] = value
                with self.subTest(group=group, value=value): self.assert_rejected(cfg, group)
            self.original[group][0]['future_property'] = {'id': 'source-reference', 'name': 'source-choice'}
            self.write_inputs()
            cfg = copy.deepcopy(self.cfg); cfg[group][0]['future_property'] = {'id': 'other-reference', 'name': 'source-choice'}
            self.assert_rejected(cfg, group)
            self.original[group][0].pop('future_property'); self.write_inputs()

    def test_unknown_matching_row_fields_are_retained_compatibly(self):
        cfg = self.renamed()
        for group in ('layers', 'shapes'):
            value = {'id': 'same-reference', 'name': 'same-choice', 'value': 4.}
            self.original[group][0]['future_property'] = copy.deepcopy(value)
            cfg[group][0]['future_property'] = copy.deepcopy(value)
        self.write_inputs()
        self.assertEqual(pc._saved_finite(cfg)[0], [self.mode])

    def test_all_existing_scalar_and_numerical_guards_remain_exact(self):
        changes = dict(lattice_nm=301., fill_fraction=self.cfg['fill_fraction']+1e-16,
            inclusion_index=1.1, top_index=1.1, bottom_index=1.1, grid_nm=self.cfg['grid_nm']+1e-12,
            pad_nm=self.cfg['pad_nm']+1e-12, harmonics=self.cfg['harmonics']+1,
            green_model='different', aperture_um=[201., 200.],
            collocation_order=self.cfg['collocation_order']+1, radiation_boundary='different',
            vertical_boundary='different', vertical_mode_selection='different',
            vertical_mode_candidates=self.cfg['vertical_mode_candidates']+1,
            vertical_mode_index=self.cfg['vertical_mode_index']+1,
            vertical_formulation='different', reference_wavelength_nm=self.cfg['reference_wavelength_nm']+1.)
        for key, value in changes.items():
            cfg = self.renamed(); cfg[key] = value
            with self.subTest(key=key): self.assert_rejected(cfg, key)

    def test_invalid_saved_field_shape_and_nonfinite_values_still_rejected(self):
        for fields in (np.ones((1, 3, 2, 2)), np.full((1, 4, 2, 2), np.nan)):
            np.savez(self.folder/'finite_fields.npz', x=np.array([0., 1.]), fields=fields,
                aperture_um=np.asarray(self.cfg['aperture_um']))
            with self.assertRaisesRegex(pc.InputValidationError, 'incomplete or invalid'):
                pc._saved_finite(self.renamed())

    def test_unaccepted_saved_mode_still_rejected_after_metadata_match(self):
        invalid = dict(self.mode, balance_relative=.03)
        with (self.folder/'finite_modes.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(invalid))
            writer.writeheader(); writer.writerow(invalid)
        (self.folder/'pcsel_summary.json').write_text('{}', encoding='utf-8')
        output = self.folder/'beam-output'; output.mkdir()
        with self.assertRaises(pc.InputValidationError) as caught:
            pc._finite_outputs(self.renamed(), None, None, output,
                dict(artifacts=[]), lambda event: None, lambda: False)
        self.assertEqual(caught.exception.diagnostics[0]['field'], 'beam_mode')
        self.assertFalse((output/'beam_fields.npz').exists())
        for guard in self.guards: guard.assert_not_called()


if __name__ == '__main__': unittest.main()
