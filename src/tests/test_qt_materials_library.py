"""Offscreen desktop regressions for durable materials and saved data workflows."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLBACKEND', 'Agg')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use('Agg')
import pandas as pd
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from data_library import DataLibrary, write_json
from model import prepare
from qt_core import ProjectStore
from qt_materials import MaterialsPage, show_frame
from qt_library import LibraryPage
from qt_field_compare import FieldComparisonWidget
from qt_common import theme_manager
from test_field_tracking_ui import sample


class NativeMaterialLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProjectStore(DataLibrary(self.root / 'library'), restore=False)
        self.widgets = []

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.store.busy and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def page(self, kind):
        page = kind(self.store)
        self.widgets.append(page)
        return page

    def wait_task(self):
        deadline = time.monotonic() + 15
        while self.store.busy and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertFalse(self.store.busy, 'Background operation did not finish')
        self.app.processEvents()

    def test_csv_import_updates_shared_materials_and_survives_portable_restore(self):
        page = self.page(MaterialsPage)
        changes = []
        self.store.changed.connect(changes.append)
        path = self.root / 'measured.csv'
        path.write_text('wavelength,n,k\n1.0,2.1,0.02\n1.5,2.3,0.03\n', encoding='utf-8')
        page.import_unit.setCurrentText('um')
        page.import_paths([str(path)])
        self.assertIn('materials', changes)
        row = self.store.materials.set_index('Name').loc['measured']
        self.assertEqual(row.Model, 'table_nk')
        self.assertEqual(page.selection.currentData(), 'project:measured')
        self.assertEqual(page.values.item(0, 0).text(), '1000')
        self.assertEqual(len(page.plot.figure.axes), 2)
        self.assertEqual(len(self.store.library.presets()), 1)
        path.unlink()
        portable = self.store.portable_project()
        restored = ProjectStore(DataLibrary(self.root / 'other'), restore=False)
        restored.load_project(portable)
        datafile = restored.library.assets / row.DataFile
        self.assertTrue(datafile.is_file())
        self.assertIn('1000.0,2.1,0.02', datafile.read_text())

    def test_bad_csv_does_not_modify_materials_and_in_use_material_cannot_be_removed(self):
        page = self.page(MaterialsPage)
        before = self.store.materials.copy(deep=True)
        path = self.root / 'missing_k.csv'
        path.write_text('wl,n\n1000,2.1\n1500,2.3\n', encoding='utf-8')
        page.import_paths([str(path)])
        pd.testing.assert_frame_equal(before, self.store.materials)
        self.assertIn('no k', page.status.text())
        page.selection.setCurrentIndex(page.selection.findData('project:GaAs'))
        self.assertFalse(page.remove.isEnabled())
        page.remove_material()
        pd.testing.assert_frame_equal(before, self.store.materials)
        self.assertEqual(len(self.store.library.presets()), 0)

    def test_manual_dispersion_and_explicit_constants_have_distinct_saved_behavior(self):
        page = self.page(MaterialsPage)
        page.manual_name.setText('Manual film')
        show_frame(page.manual_rows, pd.DataFrame([[1000, 2, .01], [2000, 3, .02]], columns=['Wavelength', 'n', 'k']))
        page.save_values()
        self.assertEqual(self.store.materials.set_index('Name').loc['Manual film', 'Model'], 'table_nk')
        page.manual_mode.setCurrentIndex(1)
        page.manual_name.setText('Constant film')
        page.n.setValue(1.8)
        page.k.setValue(.1)
        page.save_values()
        row = self.store.materials.set_index('Name').loc['Constant film']
        self.assertEqual((row.Model, row.A, row.B), ('constant_nk', 1.8, .1))
        page.selection.setCurrentIndex(page.selection.findData('project:Constant film'))
        self.assertIn('explicitly constant', page.description.text())
        self.assertEqual(len(self.store.library.presets()), 2)
        for mode in ('light', 'dark'):
            theme_manager().apply(mode, persist=False)
            page.plot.canvas.draw()
            self.assertEqual(len(page.plot.figure.axes), 2)

    def test_saved_design_selector_uses_actual_id_and_restores_shared_structure(self):
        project = self.store.portable_project()
        model = prepare(project['materials'], project['layers'], project['patterns'], [], project['settings'])
        model['layers'][1]['thickness'] = .333
        directory = self.store.library.runs / 'optimization_a'
        directory.mkdir()
        write_json(directory / 'project.json', project)
        (directory / 'design_models.jsonl').write_text(json.dumps(dict(design_id=7, model=model)) + '\n')
        (directory / 'results.csv').write_text('wavelength_nm,R,T,A\n1500,0.1,0.2,0.7\n1550,0,0.005,0.995\n')
        self.store.library.record(directory, kind='optimization', status='complete', title='A measured run')
        page = self.page(LibraryPage)
        self.assertEqual([page.design.itemData(i) for i in range(page.design.count())], [0, 7])
        self.assertEqual(page.table.rowCount(), 2)
        self.assertEqual(len(page.plot.figure.axes[0].lines), 3)
        page.design.setCurrentIndex(page.design.findData(7))
        page.restore_project()
        self.assertAlmostEqual(self.store.layers.iloc[1].Thickness_um, .333)
        page.query.setText('no matching run')
        self.assertIsNone(page.selection.currentData())
        self.assertFalse(page.restore.isEnabled())

    def test_native_library_export_and_import_preserves_projects_and_materials(self):
        project_path = self.store.save_project()
        layers = self.store.layers.copy(deep=True)
        layers.loc[1, 'Thickness_um'] = .432
        self.store.set_structure(self.store.materials, layers, self.store.patterns)
        page = self.page(LibraryPage)
        output = self.root / 'bundle.zip'
        page.include_source.setChecked(False)
        errors = []
        self.store.task_failed.connect(lambda name, error: errors.append(error))
        with patch('qt_library.QFileDialog.getSaveFileName', return_value=(str(output), 'ZIP')):
            page.export_bundle(False)
        self.wait_task()
        self.assertEqual(errors, [])
        self.assertTrue(output.is_file())
        other_store = ProjectStore(DataLibrary(self.root / 'receiver'), restore=False)
        other_page = LibraryPage(other_store)
        self.widgets.append(other_page)
        with patch('qt_library.QFileDialog.getOpenFileName', return_value=(str(output), 'ZIP')):
            other_page.import_bundle()
        deadline = time.monotonic() + 15
        while other_store.busy and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertFalse(other_store.busy)
        self.assertEqual(len(other_store.library.entries()), 2)
        restored = []
        for entry in other_store.library.entries():
            project, _ = other_store.library.project_for(entry['id'])
            restored.append(project['layers'][1]['Thickness_um'])
        self.assertIn(.432, restored, 'Whole-library export omitted the latest applied structure')
        identifier = next(entry['id'] for entry in other_store.library.entries() if other_store.library.project_for(entry['id'])[0]['layers'][1]['Thickness_um'] == .432)
        other_page.selection.setCurrentIndex(other_page.selection.findData(identifier))
        other_page.restore_project()
        pd.testing.assert_frame_equal(self.store.layers, other_store.layers)

    def test_field_comparison_preserves_common_scale_and_reports_thickness_change(self):
        run = self.store.library.runs / 'field_run'
        sample(run / 'design01' / 'fields', thickness=1, scale=1, maps=True)
        sample(run / 'design02' / 'fields', thickness=2, scale=4, maps=True)
        self.store.library.record(run, kind='optimization', status='complete', title='Field designs')
        page = self.page(FieldComparisonWidget)
        self.assertEqual(page.reference.count(), 2)
        self.assertEqual(page.layer.currentData(), 'PCS')
        errors = []
        self.store.task_failed.connect(lambda name, error: errors.append(error))
        page.compare_now()
        self.wait_task()
        self.assertEqual(errors, [])
        self.assertIsNotNone(page._payload)
        self.assertAlmostEqual(page._payload['comparison']['field_overlap'], 1)
        axes = page.plot.figure.axes[:4]
        self.assertTrue(all(axis.collections[0].norm is axes[0].collections[0].norm for axis in axes))
        condition = next(row for row in range(page.conditions.rowCount()) if page.conditions.item(row, 0).text() == 'layer/PCS/thickness_um')
        self.assertEqual(page.conditions.item(condition, 3).text(), 'True')


if __name__ == '__main__':
    unittest.main()
