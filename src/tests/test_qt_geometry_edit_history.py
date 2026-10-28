"""Geometry convenience actions preserve typed solver models and raw drafts."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_photonic_bands import PhotonicBandsWorkspace
from qt_pcsel_research_setup import PcselResearchWorkspace, _child, _text
from research_catalog import list_capabilities

APP = QApplication.instance() or QApplication([])


class GeometryEditHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='geometry-history-')
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page._save_timer.stop()
            page.close(); page.deleteLater()
        APP.processEvents(); self.temp.cleanup()

    def bands(self):
        page = PhotonicBandsWorkspace(self.store)
        self.pages.append(page)
        return page

    def pcsel(self, engine='pcsel'):
        cap = next(row for row in list_capabilities() if row['engine'] == engine)
        page = PcselResearchWorkspace(self.store, cap)
        self.pages.append(page)
        if engine == 'pcsel': page.load_pcsel_example()
        else: page.load_conformal_example()
        return page

    def test_band_duplicate_keeps_invalid_geometry_and_material_drafts_with_unique_ids(self):
        page = self.bands()
        page.geometry.setCurrentCell(0, 0)
        page.primitive_fields['radius'].setText('1e-')
        page.primitive_fields['epsilon'].setText('12e-')
        before = copy.deepcopy(page._object_draft())
        self.assertTrue(page.duplicate_primitive())
        after = copy.deepcopy(page._object_draft())
        self.assertEqual(after['geometry'][1][3], '1e-')
        self.assertEqual(len(set(after['object_ids'])), len(after['object_ids']))
        new_id = after['object_ids'][1]
        self.assertEqual(after['epsilons'][new_id], '12e-')
        self.assertTrue(page.geometry_history.undo())
        self.assertEqual(page._object_draft(), before)
        self.assertTrue(page.geometry_history.redo())
        self.assertEqual(page._object_draft(), after)
        self.assertIn(new_id, page._object_ids)
        self.assertFalse(page.geometry_history.can_redo)

    def test_band_remove_undo_preserves_sweep_reference_and_import_resets_history(self):
        page = self.bands()
        original = page._object_ids[0]
        page.sweep_target.setCurrentIndex(page.sweep_target.findData(original))
        page.add_sweep()
        page.geometry.setCurrentCell(0, 0)
        page.remove_primitive()
        self.assertTrue(page.geometry_history.can_undo)
        page.geometry_history.undo()
        self.assertEqual(page._object_ids[0], original)
        self.assertEqual(page._sweep_targets, [original])
        state = copy.deepcopy(page.draft())
        page.primitive_fields['radius'].setText('.33')
        page.restore_draft(state)
        self.assertFalse(page.geometry_history.can_undo)
        self.assertFalse(page.geometry_history.can_redo)

    def test_band_new_template_starts_object_history_from_its_own_geometry(self):
        page = self.bands()
        page.duplicate_primitive()
        page.crystal_template.setCurrentIndex(page.crystal_template.findData('diamond'))
        page.apply_crystal_template()
        self.assertFalse(page.geometry_history.can_undo)
        baseline = copy.deepcopy(page._object_draft())
        page.duplicate_primitive()
        page.geometry_history.undo()
        self.assertEqual(page._object_draft(), baseline)

    def test_pcsel_duplicate_and_history_preserve_raw_layer_and_polygon_values(self):
        for engine in ('pcsel', 'pcsel_transport'):
            page = self.pcsel(engine)
            editor = page.geometry_editor
            editor.group.setCurrentIndex(0)
            node = editor.root().child(0)
            key = 'thickness_nm' if engine == 'pcsel' else 'thickness_um'
            _child(node, key).setText(1, '1e-')
            before = copy.deepcopy(editor._geometry_draft())
            self.assertTrue(editor.duplicate())
            after = copy.deepcopy(editor._geometry_draft())
            ids = [_text(editor.root().child(i), 'id') for i in range(editor.root().childCount())]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(_text(editor.root().child(1), key), '1e-')
            self.assertTrue(editor.history.undo())
            self.assertEqual(editor._geometry_draft(), before)
            self.assertTrue(editor.history.redo())
            self.assertEqual(editor._geometry_draft(), after)
            editor.add_kind.setCurrentText('Polygon')
            editor.add_object()
            raw = copy.deepcopy(editor._geometry_draft())
            count = editor.root().childCount()
            editor.history.undo()
            self.assertEqual(editor.root().childCount(), count-1)
            editor.history.redo()
            self.assertEqual(editor._geometry_draft(), raw)
            self.assertTrue(editor.duplicate())
            self.assertEqual(editor.root().childCount(), count+1)

    def test_pcsel_move_remove_and_new_edit_clear_redo_without_touching_parameters(self):
        page = self.pcsel()
        editor = page.geometry_editor
        grid = page.fields['grid_nm']; grid.setText('3.75')
        original = copy.deepcopy(editor._geometry_draft())
        editor.objects.setCurrentRow(0)
        editor.move(1)
        moved = copy.deepcopy(editor._geometry_draft())
        self.assertNotEqual(moved, original)
        editor.history.undo()
        self.assertEqual(editor._geometry_draft(), original)
        editor.history.redo()
        self.assertEqual(editor._geometry_draft(), moved)
        editor.remove()
        editor.history.undo()
        self.assertEqual(editor._geometry_draft(), moved)
        _child(editor.root().child(0), 'name').setText(1, 'New edit')
        self.assertFalse(editor.history.can_redo)
        self.assertIs(page.fields['grid_nm'], grid)
        self.assertEqual(grid.text(), '3.75')
        state = copy.deepcopy(page.draft())
        page.restore_draft(state)
        self.assertFalse(editor.history.can_undo)
        self.assertFalse(editor.history.can_redo)


if __name__ == '__main__':
    unittest.main()
