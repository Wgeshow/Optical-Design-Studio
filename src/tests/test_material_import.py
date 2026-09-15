import copy
import tempfile
import unittest
from pathlib import Path
import pandas as pd

from data_library import DataLibrary
from material_import_ui import import_csvs, save_manual
from material_viewer import material_data
from model import MAT_COLS, numeric_rows, prepare, epsilon
from nk_import import parse_nk
from test_backend import MATERIALS, LAYERS, PATTERNS, SETTINGS


class MaterialImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = DataLibrary(self.root / 'library')
        self.frame = pd.DataFrame(copy.deepcopy(MATERIALS), columns=MAT_COLS)

    def test_separate_sections_and_common_range(self):
        text = 'wl,n\n1,2\n2,4\n3,6\n\nwl,k\n1.5,0.1\n2.5,0.3\n'
        rows = parse_nk(text, 'um')
        self.assertEqual([r[0] for r in rows], [1500, 2000, 2500])
        self.assertEqual([r[1] for r in rows], [3, 4, 5])
        self.assertAlmostEqual(rows[1][2], .2)

    def test_units_and_missing_k_are_explicit(self):
        text = 'wl,n\n1,2\n2,3\n'
        with self.assertRaisesRegex(ValueError, 'no k'):
            parse_nk(text, 'um')
        self.assertEqual(parse_nk(text, 'um', missing_k=0), [[1000, 2, 0], [2000, 3, 0]])
        with self.assertRaisesRegex(ValueError, 'WavelengthUnit'):
            parse_nk(text, 'auto', missing_k=0)
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            parse_nk('wl,n\n1,2\n2,3\nwl,k\n3,0\n4,0\n', 'um')

    def test_bad_tables_do_not_silently_fill_values(self):
        for text in ('wavelength,n,k\n1,2,0\n2,3\n', 'wl,n\n1,2\n1,3\n',
                     'wavelength,n,k\n1,2,0\n2,nan,0\n', 'wl,n,k\n1,2,0\n2,3,0\nwl,k\n1,0\n2,0'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_nk(text, 'um')

    def test_auto_import_names_persists_and_reuses(self):
        file = self.root / 'AlGaAs50.csv'
        file.write_text('wavelength,n,k\n800,3.33,0\n2000,3.16,0\n')
        frame, key, report = import_csvs(self.library, self.frame, [file], 'nm', False, 'https://refractiveindex.info/')
        row = frame.iloc[-1].to_dict()
        self.assertEqual(row['Name'], 'AlGaAs50')
        self.assertEqual(row['Model'], 'table_nk')
        self.assertIn('800–2000 nm', report)
        second, key2, _ = import_csvs(self.library, frame, [file], 'nm', False, 'https://refractiveindex.info/')
        self.assertEqual(len(second), len(frame))
        self.assertEqual(key, key2)
        self.assertEqual(len(self.library.presets()), 1)
        file.unlink()
        restarted = DataLibrary(self.library.root)
        project = restarted.snapshot(dict(materials=frame.to_dict('records')))
        self.assertTrue(restarted.files_for(project))

    def test_automatic_material_replaces_same_name_and_preserves_old_version(self):
        file = self.root / 'Film.csv'
        file.write_text('wl,n,k\n1200,3.2,0.01\n1700,3.6,0.02\n')
        frame, first, _ = import_csvs(self.library, self.frame, [file], 'nm', False, 'reference')
        self.assertEqual(len(frame), len(self.frame))
        file.write_text('wl,n,k\n1200,2.2,0.01\n1700,2.6,0.02\n')
        frame2, second, _ = import_csvs(self.library, frame, [file], 'nm', False, 'reference')
        self.assertNotEqual(first, second)
        self.assertNotEqual(frame.iloc[1].DataFile, frame2.iloc[1].DataFile)

    def test_manual_dispersion_reaches_solver_and_plot(self):
        frame, key, _ = save_manual(self.library, self.frame, 'Film', 'Wavelength-dependent n,k', 'um',
                                   [[1.2, 2, .1], [1.7, 4, .2]], None, None, 'dataset URL')
        project = self.library.snapshot(dict(materials=frame.to_dict('records')))
        model = prepare(project['materials'], LAYERS, PATTERNS, self.library.files_for(project), SETTINGS)
        self.assertAlmostEqual(epsilon(model['materials'][1], 1450), complex(3, .15)**2)
        data, description, notes = material_data(self.library, (project['materials'][1], 'source'), frame, None)
        self.assertEqual(data.wavelength_nm.tolist(), [1200, 1700])
        self.assertEqual(data.n.tolist(), [2, 4])
        self.assertIn('wavelength-dependent', description)

    def test_constant_requires_explicit_mode_and_values(self):
        with self.assertRaises(ValueError):
            save_manual(self.library, self.frame, 'Film', 'Wavelength-dependent n,k', 'nm', [], 2, 0, '')
        with self.assertRaises(ValueError):
            save_manual(self.library, self.frame, 'Film', 'Constant n,k (explicit approximation)', 'nm', [], None, None, '')
        frame, _, _ = save_manual(self.library, self.frame, 'Film', 'Constant n,k (explicit approximation)', 'nm', [], 2, .1, '')
        data, description, _ = material_data(self.library, (frame.iloc[1].to_dict(), ''), frame, None, 1000, 2000)
        self.assertEqual(data.n.tolist(), [2, 2])
        self.assertIn('constant approximation', description)

    def test_invalid_second_upload_does_not_save_first(self):
        valid, invalid = self.root / 'first.csv', self.root / 'second.csv'
        valid.write_text('wl,n,k\n1,2,0\n2,3,0\n')
        invalid.write_text('wl,n\n1,2\n2,3\n')
        with self.assertRaises(ValueError):
            import_csvs(self.library, self.frame, [valid, invalid], 'um', False, 'source')
        self.assertFalse(self.library.presets())


if __name__ == '__main__':
    unittest.main()
