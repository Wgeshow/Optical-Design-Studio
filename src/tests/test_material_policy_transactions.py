"""Replacing an optical model cannot leave an invalid persisted policy."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from data_library import DataLibrary, read_json
from qt_core import ProjectStore, prepare_job


class MaterialPolicyTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = DataLibrary(Path(self.temp.name)/'library')
        self.path = Path(self.temp.name)/'measured.csv'
        self.path.write_text('wavelength,n,k\n1000,2,.01\n2000,4,1\n')
        self.store = ProjectStore(self.library, restore=False)
        materials = self.store.materials.copy(deep=True)
        self.name = materials.iloc[0]['Name']
        materials.loc[0, ['Model','DataFile','WavelengthUnit']] = ['table_nk', self.path.name, 'nm']
        self.store.files = [self.path]
        self.store.set_structure(materials, self.store.layers, self.store.patterns)
        self.store.update_settings({'material_interpolations': {self.name: 'log_k', 'Unused preset': 'log_k'}})
        self.before = copy.deepcopy(self.store.project())

    def tearDown(self):
        self.temp.cleanup()

    def replace_with_constant(self):
        materials = self.store.materials.copy(deep=True)
        materials.loc[0, ['Model','A','B','DataFile']] = ['constant_nk', 1.5, 0., '']
        self.store.set_structure(materials, self.store.layers, self.store.patterns)

    def test_constant_replacement_is_valid_in_session_job_and_undo(self):
        self.replace_with_constant()
        policies = { 'Unused preset': 'log_k' }
        self.assertEqual(self.store.settings['material_interpolations'], policies)
        self.assertEqual(read_json(self.store.session_path)['settings']['material_interpolations'], policies)
        _, job = prepare_job('simulation', self.store.portable_project(), {}, self.library)
        self.assertEqual(job['model']['materials'][0]['model'], 'constant_nk')
        self.assertNotIn('interpolation', job['model']['materials'][0])
        self.store.undo()
        self.assertEqual(self.store.project(), self.before)
        _, job = prepare_job('simulation', self.store.portable_project(), {}, self.library)
        self.assertEqual(job['model']['materials'][0]['interpolation'], 'log_k')

    def test_failed_replacement_and_failed_undo_restore_rows_and_policies(self):
        count = len(self.store._undo)
        with patch.object(self.store, '_autosave', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.replace_with_constant()
        self.assertEqual(self.store.project(), self.before)
        self.assertEqual(len(self.store._undo), count)
        self.replace_with_constant()
        constant = copy.deepcopy(self.store.project())
        with patch.object(self.store, '_autosave', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.store.undo()
        self.assertEqual(self.store.project(), constant)
        self.store.undo()
        self.assertEqual(self.store.project(), self.before)


if __name__ == '__main__': unittest.main()
