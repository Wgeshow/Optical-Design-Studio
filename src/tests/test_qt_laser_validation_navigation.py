"""Laser validation uses the actual footer and exact input widgets; no solver runs."""
import copy
import os
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QFrame
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel import PCSELPage

APP = QApplication.instance() or QApplication([])


class LaserValidationNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.env = patch.dict(os.environ, S4_LIBRARY_ROOT=self.temp.name)
        self.env.start()
        self.guard = patch('qt_pcsel.solve_laser', side_effect=AssertionError('No solver is allowed.'))
        self.solve = self.guard.start()
        self.store = ProjectStore(DataLibrary(Path(self.temp.name) / 'library'), restore=False)
        self.store.study_navigation_enabled = True
        self.store.activate_study('lumped_laser')
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            if hasattr(widget, '_save_timer'):
                widget._save_timer.stop()
            widget.hide()
            widget.deleteLater()
        APP.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.guard.stop()
        self.env.stop()
        self.temp.cleanup()

    def page(self):
        page = PCSELPage(self.store)
        self.widgets.append(page)
        page.resize(1200, 850)
        page.show()
        APP.processEvents()
        return page

    def test_current_range_go_button_reveals_unchanged_stopping_current(self):
        page = self.page()
        page.current_start.setValue(page.current_max.value())
        before = (page.current_start.value(), page.current_max.value(), page.quality_factor.value(), copy.deepcopy(self.store.device))
        page._show_laser_stage(4)
        self.assertFalse(page.validate_setup())
        self.assertEqual(page.laser_stage, 3)
        self.assertIn('Stopping current must exceed', page.laser_check_note.text())
        self.assertTrue(page.laser_issue_button.isVisible())
        page.laser_issue_button.click()
        APP.processEvents()
        self.assertEqual(page.laser_stage, 2)
        self.assertEqual(page.workbench.input_tabs.currentIndex(), page._laser_parameter_pages['Drive sweep'])
        self.assertTrue(page.current_max.isVisible())
        self.assertIsNotNone(page.current_max.findChild(QFrame, 'diagnosticFieldHighlight'))
        self.assertEqual((page.current_start.value(), page.current_max.value(), page.quality_factor.value(), self.store.device), before)
        page.current_start.setValue(0)
        self.assertTrue(page.validate_setup())
        self.assertIsNone(page._laser_diagnostic)
        self.assertFalse(page.laser_issue_button.isVisible())
        self.solve.assert_not_called()

    def test_backend_parameter_errors_find_their_actual_sections(self):
        page = self.page()
        for parameter, value, field, stage, section in (
            ('confinement', 0, 'confinement', 0, 'Mode inputs'),
            ('thermal_resistance_k_w', -1, 'thermal_resistance', 1, 'Lumped thermal inputs'),
        ):
            with self.subTest(parameter=parameter):
                invalid = replace(page.laser_parameters(), **{parameter: value})
                with patch.object(page, 'laser_parameters', return_value=invalid):
                    self.assertFalse(page.validate_setup())
                self.assertEqual(page._laser_diagnostic['field'], field)
                self.assertTrue(page.open_diagnostic())
                self.assertEqual(page.laser_stage, stage)
                self.assertEqual(page.workbench.input_tabs.currentIndex(), page._laser_parameter_pages[section])
                self.assertIsNotNone(getattr(page, field).findChild(QFrame, 'diagnosticFieldHighlight'))
        self.solve.assert_not_called()

    def test_optional_geometry_and_mode_volume_do_not_block_scalar_check(self):
        page = self.page()
        page.pc_layer.clear()
        page.mode_volume.lineEdit().setText('')
        self.assertFalse(page.mode_volume.hasAcceptableInput())
        self.assertTrue(page.validate_setup())
        self.solve.assert_not_called()

    def test_unfinished_required_numeric_input_is_preserved_and_linked(self):
        page = self.page()
        page.current_max.lineEdit().setText('')
        before = page.current_max.lineEdit().text()  # Qt retains the unit suffix.
        self.assertFalse(page.validate_setup())
        self.assertEqual(page._laser_diagnostic['field'], 'current_max')
        self.assertEqual(page.current_max.lineEdit().text(), before)
        self.assertIsNone(page.run_simulation())
        self.assertEqual(page.laser_stage, 3)
        self.assertEqual(page.current_max.lineEdit().text(), before)
        self.solve.assert_not_called()

    def test_actual_global_footer_check_and_run_dispatch(self):
        from qt_app import OpticalStudio
        self.store.activate_study('optical')
        window = OpticalStudio(self.store)
        self.widgets.append(window)
        window.resize(1440, 950)
        window.show()
        window._open_simulation_choice('lumped_laser')
        APP.processEvents()
        page = window.research_studies_page.stack.currentWidget()
        self.assertIsInstance(page, PCSELPage)
        page.current_start.setValue(page.current_max.value())
        page._show_laser_stage(4)
        window.footer_validate.click()
        APP.processEvents()
        self.assertEqual(page.laser_stage, 3)
        self.assertIn('Stopping current must exceed', page.laser_check_note.text())
        page.laser_issue_button.click()
        APP.processEvents()
        self.assertEqual(page.laser_stage, 2)
        self.assertIsNotNone(page.current_max.findChild(QFrame, 'diagnosticFieldHighlight'))
        page.current_start.setValue(0)
        window.footer_validate.click()
        self.assertIn('Analytical inputs are valid', page.laser_check_note.text())
        with patch.object(page, 'run_simulation') as run:
            window.run_button.click()
            run.assert_called_once_with()
        self.solve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
