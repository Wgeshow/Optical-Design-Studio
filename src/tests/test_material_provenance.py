"""Standalone projects carry dataset citation separately from editable notes."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_materials import MaterialsPage

APP = QApplication.instance() or QApplication([])


class MaterialProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = DataLibrary(self.root/'source-library')
        self.store = ProjectStore(self.library, restore=False)
        self.page = MaterialsPage(self.store)
        self.widgets = [self.page]
        self.measured = self.root/'Measured.csv'
        self.measured.write_text('wavelength,n,k\n1000,2,.01\n2000,4,1\n')
        self.page.import_paths([str(self.measured)])
        self.page.selection.setCurrentIndex(self.page.selection.findData('project:Measured'))

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def test_clean_library_standalone_project_keeps_source_notes_policy_and_raw_bytes(self):
        source = self.page.material_source.text()
        self.assertIn('Measured', source)
        self.assertNotIn('not recorded', source.lower())
        self.page.material_notes.setPlainText('My independent project note')
        self.assertTrue(self.page.save_material_notes())
        self.page.interpolation.setCurrentIndex(self.page.interpolation.findData('log_k'))
        original_inputs = copy.deepcopy(self.store.project())
        portable = self.store.portable_project()
        upload_bytes = self.measured.read_bytes()
        row = next(row for row in portable['materials'] if row['Name'] == 'Measured')
        original_bytes = (self.library.assets/row['DataFile']).read_bytes()
        target_library = DataLibrary(self.root/'empty-library')
        self.assertEqual(target_library.presets(), {})
        target = ProjectStore(target_library, restore=False)
        target.load_project(portable)
        reopened = MaterialsPage(target)
        self.widgets.append(reopened)
        reopened.selection.setCurrentIndex(reopened.selection.findData('project:Measured'))
        self.assertEqual(reopened.material_source.text(), source)
        self.assertEqual(reopened.material_notes.toPlainText(), 'My independent project note')
        self.assertEqual(reopened.interpolation.currentData(), 'log_k')
        self.assertEqual(reopened.values.rowCount(), 2)
        self.assertEqual(Path(target.files[0]).read_bytes(), original_bytes)
        self.assertEqual(self.measured.read_bytes(), upload_bytes)
        self.assertEqual(target.project(), original_inputs)
        records = len(target_library.presets())
        for _ in range(3):
            target.load_project(portable)
            target.portable_project()
        self.assertEqual(len(target_library.presets()), records)
        self.assertEqual(target.portable_project()['material_provenance'], portable['material_provenance'])

    def test_legacy_snapshot_without_source_has_no_new_metadata(self):
        clean = DataLibrary(self.root/'clean-library')
        legacy = ProjectStore(clean, restore=False).portable_project()
        self.assertNotIn('material_provenance', legacy)
        clean.materialize(legacy)
        self.assertEqual(clean.presets(), {})

    def test_provenance_is_bound_to_exact_material_and_validated_before_restore(self):
        portable = self.store.portable_project()
        self.assertTrue(portable['material_provenance'])
        for change in ('wrong_material', 'non_text', 'duplicate'):
            bad = copy.deepcopy(portable)
            if change == 'wrong_material':
                bad['material_provenance'][0]['material']['Name'] = 'Other dataset'
            elif change == 'non_text':
                bad['material_provenance'][0]['source_notes'] = []
            else:
                bad['material_provenance'].append(copy.deepcopy(bad['material_provenance'][0]))
            library = DataLibrary(self.root/change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'provenance'):
                library.materialize(bad)
            self.assertEqual(library.presets(), {})

    def test_replacing_same_named_material_cannot_inherit_dataset_citation(self):
        original = self.store.project()
        before = self.library.snapshot(original, self.store.files)
        row = next(row for row in original['materials'] if row['Name'] == 'Measured')
        self.assertTrue(self.library.material_metadata(row))
        replaced = copy.deepcopy(original)
        changed = next(row for row in replaced['materials'] if row['Name'] == 'Measured')
        changed.update(Model='constant_nk', A=2., B=0., DataFile='')
        self.assertEqual(self.library.material_metadata(changed), {})
        constant = self.library.snapshot(replaced)
        self.assertFalse(any(entry['material']['Name'] == 'Measured'
                             for entry in constant.get('material_provenance', [])))
        restored = self.library.snapshot(original, self.store.files)
        self.assertEqual(restored['material_provenance'], before['material_provenance'])

    def test_incoming_project_source_wins_existing_metadata_without_repeated_duplicates(self):
        original = self.store.portable_project()
        row = next(row for row in original['materials'] if row['Name'] == 'Measured')
        library = DataLibrary(self.root/'existing-library')
        library.materialize(original)
        alternate = copy.deepcopy(original)
        alternate['material_provenance'][0].update(source_notes='An alternate dataset provenance statement',
                                                  notes='Alternate default note', label='Alternate record')
        library.materialize(alternate)
        self.assertEqual(library.material_metadata(row)['source_notes'], 'An alternate dataset provenance statement')
        library.materialize(original)
        self.assertEqual(library.material_metadata(row)['source_notes'], original['material_provenance'][0]['source_notes'])
        count = len(library.presets())
        for _ in range(3):
            library.materialize(original)
        self.assertEqual(len(library.presets()), count)


if __name__ == '__main__':
    unittest.main()
