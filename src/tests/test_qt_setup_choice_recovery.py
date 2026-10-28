"""Rejected setup choices must not keep blocking a later valid selection.

This is a widget/state regression only; it does not run or validate a physical
simulation, and is separate from the manual UI-built paper comparisons.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6 import sip
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

from data_library import DataLibrary
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace


APP = QApplication.instance() or QApplication([])


class ChoiceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods_choice_recovery_',
            dir=Path(__file__).resolve().parents[3])
        self.store = ProjectStore(DataLibrary(self.temp.name), restore=False)
        self.page = SimulationSetupWorkspace(self.store)
        self.page.set_mode('electrical')
        self.page.select_section('electrical.study')
        self.row = next(row for row in self.page.fields
            if row.key == 'ui.electrical.study')

    def tearDown(self):
        sip.delete(self.page)
        APP.processEvents()
        self.temp.cleanup()

    def choose_study(self, value):
        index = self.row.editor.findData(value)
        self.assertGreaterEqual(index, 0)
        self.row.editor.setCurrentIndex(index)

    def test_rejected_iv_and_cv_recover_to_valid_dc_without_stale_run_blocker(self):
        for rejected in ('iv', 'cv'):
            with self.subTest(rejected=rejected):
                self.page.state.set('search.electrical.model', 'explicit_ito')
                # Exercise the real model guard. This control is hidden for the
                # legacy model, so this is not a claim of a native user journey.
                self.choose_study(rejected)
                self.assertIn('ui.electrical.study', self.page.draft_errors)
                self.assertIn('editable device', self.row.error.text())

                self.page.state.set('search.electrical.model', 'custom_device')
                self.choose_study(rejected)
                self.choose_study('bias')
                self.assertEqual(self.page.state.get('ui.electrical.study'), 'bias')
                self.assertNotIn('ui.electrical.study', self.page.draft_errors)
                self.assertTrue(self.row.error.isHidden())

                # Isolate the choice-recovery contract from physical geometry
                # validation; dispatch is observed and no backend is started.
                dispatched = QSignalSpy(self.page.runRequested)
                with patch.object(self.page.state, 'validate', return_value=[]):
                    self.page.run()
                self.assertEqual(list(dispatched), [['electrical']])


if __name__ == '__main__':
    unittest.main()
