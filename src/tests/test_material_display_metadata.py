"""Portable material display metadata stays separate from optical inputs."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary, read_json
from qt_core import ProjectStore

APP = QApplication.instance() or QApplication([])


class MaterialDisplayMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ProjectStore(DataLibrary(self.temp.name), restore=False)
        self.name = str(self.store.materials.iloc[0]['Name'])

    def tearDown(self):
        self.temp.cleanup()

    def optical_inputs(self):
        project = self.store.project()
        return {key: copy.deepcopy(project[key]) for key in
                ('materials', 'layers', 'patterns', 'settings', 'performance')}

    def test_colors_and_multiline_notes_roundtrip_and_survive_structure_undo(self):
        before = self.optical_inputs()
        note = 'Measured at room temperature.\nSource and sample conditions retained.'
        self.store.update_appearance({'material_colors': {self.name: '#Ab12CD'},
                                     'material_notes': {self.name: note}})
        self.assertEqual(self.store.appearance['material_colors'][self.name], '#ab12cd')
        self.assertEqual(self.optical_inputs(), before)
        path = Path(self.temp.name) / 'material-display.json'
        self.store.save_project(path)
        restored = ProjectStore(self.store.library, restore=False)
        restored.load_project(path)
        self.assertEqual(restored.appearance, self.store.appearance)
        self.assertEqual(restored.appearance['material_notes'][self.name], note)
        self.assertEqual(read_json(self.store.session_path)['appearance'], self.store.appearance)
        layers = self.store.layers.copy(deep=True)
        layers.loc[1, 'Thickness_um'] = .375
        self.store.set_structure(self.store.materials, layers, self.store.patterns)
        self.store.undo()
        self.assertEqual(self.optical_inputs(), before)
        self.assertEqual(self.store.appearance['material_notes'][self.name], note)

    def test_invalid_metadata_and_failed_save_leave_the_entire_project_intact(self):
        before = copy.deepcopy(self.store.project())
        for values in ({'material_colors': {self.name: 'red'}},
                       {'material_colors': {'': '#123456'}},
                       {'material_notes': {self.name: 42}},
                       {'material_notes': {'': 'text'}}):
            with self.assertRaises(ValueError):
                self.store.update_appearance(values)
            self.assertEqual(self.store.project(), before)
        with patch.object(self.store, '_autosave', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.update_appearance({'material_notes': {self.name: 'unsaved'}})
        self.assertEqual(self.store.project(), before)

    def test_old_projects_keep_default_display_metadata(self):
        project = self.store.portable_project()
        project.pop('appearance', None)
        path = Path(self.temp.name) / 'old-project.json'
        import json
        path.write_text(json.dumps(project), encoding='utf-8')
        self.store.update_appearance({'material_colors': {self.name: '#123456'}})
        self.store.load_project(path)
        self.assertEqual(self.store.appearance, {'layer_colors': {}, 'material_opacities': {}})


if __name__ == '__main__':
    unittest.main()
