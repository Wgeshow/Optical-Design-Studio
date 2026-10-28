"""Check/edit/import safety only; numerical execution is forbidden."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel_research_setup import PcselResearchWorkspace
from research_catalog import list_capabilities
import pcsel_research as pc


class RcwaSeedValidationTests(unittest.TestCase):
    def settings(self, seeds):
        result = pc.paper_example()
        result.update(model='rcwa_poles', pole_seeds=seeds)
        return result

    def test_numeric_seed_strings_become_solver_numbers(self):
        cfg = pc.prepare({}, self.settings([['.299', '-.0001']]))
        self.assertEqual(cfg['pole_seeds'], [[.299, -.0001]])
        self.assertTrue(all(isinstance(v, float) for v in cfg['pole_seeds'][0]))

    def test_malformed_seed_rows_have_a_field_diagnostic(self):
        for row in (None, .299, '0.299', {}, [], [.299], [.299, -.001, 1]):
            with self.subTest(row=row):
                with self.assertRaises(pc.InputValidationError) as caught:
                    pc.prepare({}, self.settings([row]))
                self.assertEqual(caught.exception.diagnostics[0]['field'], 'pole_seeds')

    def test_sign_bounds_and_finite_checks_remain(self):
        for row in ([-.1, -.001], [.299, 0], [.299, .001], [float('nan'), -.001], [.299, float('inf')], [999, -.001]):
            with self.subTest(row=row):
                with self.assertRaises(pc.InputValidationError) as caught:
                    pc.prepare({}, self.settings([row]))
                self.assertEqual(caught.exception.diagnostics[0]['field'], 'pole_seeds')


class ResearchSetupImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pcsel-import-safety-')
        self.root = Path(self.temp.name)
        self.store = ProjectStore(DataLibrary(self.root / 'library'), restore=False)
        self.store.study_navigation_enabled = True
        self.store.activate_study('pcsel.cwt')
        cap = next(row for row in list_capabilities() if row['engine'] == 'pcsel')
        self.page = PcselResearchWorkspace(self.store, cap, document_id='pcsel.cwt')
        self.page.bind_study_document('pcsel.cwt')
        self.page.load_pcsel_example()
        self.page.fields['harmonics'].setText('17')
        self.page.fields['gmax'].setText('1e-')
        self.before = copy.deepcopy(self.page.draft())
        self.guards = []
        for target in ('pcsel_research.execute', 'pcsel_research.vertical', 'pcsel_research.coupling', 'pcsel_research.finite_modes'):
            guard = patch(target, side_effect=AssertionError('Numerical execution forbidden'))
            self.guards.append(guard.start())
            self.addCleanup(guard.stop)

    def tearDown(self):
        for guard in self.guards:
            guard.assert_not_called()
        self.page._save_timer.stop()
        self.page.close(); self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def import_document(self, document):
        path = self.root / 'import.json'
        path.write_text(json.dumps(document), encoding='utf-8')
        with patch('qt_research_studies.QFileDialog.getOpenFileName', return_value=(str(path), 'JSON')):
            self.page.import_settings()

    def test_wrong_engine_or_study_leaves_current_raw_draft_untouched(self):
        for document in (
            dict(engine='thermal', study=self.page.study, settings={}),
            dict(engine='pcsel', study='unrelated', settings={})):
            with self.subTest(document=document):
                self.import_document(document)
                self.assertIn('different simulation type', self.page.status.text())
                self.assertEqual(self.page.draft(), self.before)

    def test_nonobject_setup_leaves_current_raw_draft_untouched(self):
        for document in ([], None, 'not an object', dict(settings=[]), dict(settings=None)):
            with self.subTest(document=document):
                self.import_document(document)
                self.assertIn('JSON object', self.page.status.text())
                self.assertEqual(self.page.draft(), self.before)

    def test_matching_wrapper_and_raw_settings_preserve_bound_model(self):
        settings = pc.paper_example()
        settings.update(model='cwt', harmonics=11)
        for document in (settings, dict(engine='pcsel', study=self.page.study, settings=settings)):
            with self.subTest(wrapper='settings' in document):
                self.import_document(document)
                self.assertEqual(self.store.active_study, 'pcsel.cwt')
                self.assertEqual(self.page.fields['model'].currentData(), 'cwt')
                self.assertEqual(self.page.options()['settings']['harmonics'], 11)
                self.assertEqual(self.page.structured['layers'].value(), settings['layers'])


if __name__ == '__main__':
    unittest.main()
