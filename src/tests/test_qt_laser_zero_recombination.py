"""Offscreen control regression only; deliberately forbid simulation execution."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel import PCSELPage

APP = QApplication.instance() or QApplication([])


class LaserZeroRecombinationControlTests(unittest.TestCase):
    def test_zero_b_and_c_text_entry_survives_parameter_conversion_and_check(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            with patch.dict(os.environ, S4_LIBRARY_ROOT=directory), patch(
                    'qt_pcsel.solve_laser', side_effect=AssertionError('No simulation allowed.')) as solve:
                store = ProjectStore(DataLibrary(Path(directory) / 'library'), restore=False)
                store.study_navigation_enabled = True
                store.activate_study('lumped_laser')
                page = PCSELPage(store)
                try:
                    for field in (page.recombination_b, page.recombination_c):
                        self.assertEqual(field.minimum(), 0.0)
                        field.lineEdit().selectAll()
                        QTest.keyClicks(field.lineEdit(), '0')
                        field.interpretText()
                        self.assertEqual(field.value(), 0.0)
                    parameters = page.laser_parameters()
                    self.assertEqual(parameters.recombination_b_cm3_s, 0.0)
                    self.assertEqual(parameters.recombination_c_cm6_s, 0.0)
                    self.assertGreater(page.recombination_a.minimum(), 0.0)
                    self.assertGreater(parameters.recombination_a_s, 0.0)
                    self.assertIs(parameters.validate(), parameters)
                    self.assertTrue(page.validate_setup())
                    solve.assert_not_called()
                finally:
                    page.hide()
                    page.deleteLater()
                    APP.processEvents()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
