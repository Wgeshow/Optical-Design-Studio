"""Field-addressed geometry validation; no solver or runtime process is run."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_sesame_setup import SesameSetupWorkspace
from research_diagnostics import validate_request

APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


class SesameRegionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sesame-diagnostic-', dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'), restore=False)
        self.store.activate_study('sesame_transport')
        self.page = None

    def tearDown(self):
        if self.page is not None:
            from PyQt6 import sip
            self.page._save_timer.stop()
            sip.delete(self.page)
        APP.processEvents()

    def case(self, dimension=1):
        name = 'sesame_1d_heterojunction' if dimension == 1 else 'sesame_2d_grain_boundary'
        return json.loads((ROOT/'benchmark_data'/name/'case.json').read_text(encoding='utf-8'))

    def test_backend_bounds_failures_keep_region_axis_and_units(self):
        for dimension, axis, bounds in [(1, 'x', [.025, 4.03]), (1, 'x', [.025, .025]),
                (1, 'x', [.025]), (1, 'x', ['bad', 4.025]), (2, 'y', [0, 3.01])]:
            with self.subTest(dimension=dimension, axis=axis, bounds=bounds):
                options = copy.deepcopy(self.case(dimension)['options'])
                region = options['settings']['regions'][1]
                region[axis+'_range_um'] = bounds
                rows = validate_request(self.store.project(), options)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['object_id'], region['id'])
                self.assertEqual(rows[0]['field'], 'regions.'+region['id']+'.'+axis+'_range_um')
                self.assertEqual(rows[0]['units'], 'um')
                self.assertEqual(rows[0]['section'], 'Device')

    def test_native_inspector_diagnostic_returns_to_unchanged_absorber_bounds(self):
        self.page = SesameSetupWorkspace(self.store, document_id='sesame_transport')
        self.page.load_settings(copy.deepcopy(self.case()['options']['settings']))
        self.page.resize(1100, 820)
        self.page.show()
        self.page.open_diagnostic(dict(field='regions.x_range_um', object_id='absorber'))
        edit = self.page.inspectors['regions'].editors['x_range_um']
        edit.setText('0.025, 4.03')
        self.page.tabs.setCurrentIndex(4)
        self.assertFalse(self.page.validate_inputs())
        row = self.page.diagnostics.list.item(0).data(Qt.ItemDataRole.UserRole)
        self.assertEqual(row['field'], 'regions.absorber.x_range_um')
        self.assertEqual(row['object_id'], 'absorber')
        self.page.diagnostics.go_to_first()
        APP.processEvents()
        self.assertIs(APP.focusWidget(), edit)
        self.assertEqual(edit.text(), '0.025, 4.03')
        self.assertEqual(self.page.regions.item(self.page.regions.currentRow(), 0).text(), 'absorber')
        self.assertEqual(self.page.tabs.currentIndex(), 0)

    def test_diagnostic_uses_stable_id_after_row_reordering(self):
        self.page = SesameSetupWorkspace(self.store, document_id='sesame_transport')
        cfg = copy.deepcopy(self.case()['options']['settings'])
        self.page.load_settings(cfg)
        self.page.resize(1100, 820)
        self.page.show()
        options = self.page.options()
        next(row for row in options['settings']['regions'] if row['id'] == 'absorber')['x_range_um'] = [.025, 4.03]
        target = validate_request(self.store.project(), options)[0]
        from qt_photonic_bands import _fill, _rows
        _fill(self.page.regions, list(reversed(_rows(self.page.regions))))
        self.page.inspectors['regions'].refresh()
        self.page._edited()
        self.page.save_draft()
        self.assertTrue(self.page.open_diagnostic(target))
        APP.processEvents()
        self.assertEqual(self.page.regions.currentRow(), 1)
        self.assertEqual(self.page.regions.item(1, 0).text(), 'absorber')
        self.assertIs(APP.focusWidget(), self.page.inspectors['regions'].editors['x_range_um'])


if __name__ == '__main__':
    unittest.main()
