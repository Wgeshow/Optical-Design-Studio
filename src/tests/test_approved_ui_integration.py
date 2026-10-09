"""Acceptance tests for the approved General Optical / Laser-PCSEL shell.

These deliberately exercise the assembled Qt window rather than implementation
helpers.  The reference UI has two top-level workspaces; the laser workspace
then owns its coupled-solver workflow and rendered results.
"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_bootstrap_library = tempfile.TemporaryDirectory(prefix="s4_approved_ui_import_")
os.environ.setdefault("S4_LIBRARY_ROOT", _bootstrap_library.name)

from PyQt6.QtCore import Qt, QCoreApplication, QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QTabWidget

from data_library import DataLibrary
from qt_app import OpticalStudio
from qt_core import ProjectStore


def _normal(text):
    """Normalize presentation punctuation without weakening wording checks."""
    return " ".join(str(text).replace("&&", "&").replace("&", "and").replace("/", " ").split()).casefold()


class ApprovedWorkspaceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="s4_approved_ui_")
        self.addCleanup(self.temp.cleanup)
        store = ProjectStore(DataLibrary(self.temp.name), restore=False)
        self.window = OpticalStudio(store)
        self.window.resize(1366, 768)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_workflow_labels_and_layer_form_fit_both_themes_and_sizes(self):
        from qt_common import theme_manager
        self.window.navigation.setCurrentRow(8)
        page = self.window.pages['PCSEL']
        for mode in ('light', 'dark'):
            theme_manager().apply(mode, persist=False)
            for width, height in ((1920, 1080), (1280, 800)):
                self.window.resize(width, height)
                self.app.processEvents()
                bar = page.tabs.tabBar()
                for index in range(bar.count()):
                    rect = bar.tabRect(index)
                    label = bar.tabText(index).replace('&&', '&')
                    self.assertGreaterEqual(rect.width(), bar.fontMetrics().horizontalAdvance(label) + 20)
                    self.assertGreaterEqual(rect.height(), bar.fontMetrics().height() + 12)
                    self.assertTrue(bar.rect().contains(rect))
                area = page.device_builder.tabs.widget(0)
                self.assertEqual(area.horizontalScrollBar().maximum(), 0)

    def _top_workspace_buttons(self):
        return [button for button in self.window.workspace_tabs.findChildren(QPushButton)
                if button.property("workspaceTab")]

    def _click_workspace(self, phrase):
        button = next(button for button in self._top_workspace_buttons()
                      if phrase in _normal(button.accessibleName() or button.text()))
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        return button

    def test_shell_exposes_exactly_two_primary_workspaces_and_routes_between_them(self):
        buttons = self._top_workspace_buttons()
        self.assertEqual(len(buttons), 2, [button.text() for button in buttons])
        self.assertEqual({_normal(button.accessibleName() or button.text()) for button in buttons}, {
            "general optical simulations", "laser pcsel simulations"})

        general = self._click_workspace("general optical simulations")
        self.assertNotEqual(self.window.stack.currentIndex(), 8)
        self.assertTrue(general.isChecked())

        laser = self._click_workspace("laser pcsel simulations")
        self.assertEqual(self.window.stack.currentIndex(), 8)
        self.assertIs(self.window.stack.currentWidget().findChild(
            type(self.window.pages["PCSEL"]), "laserWorkspace"),
            self.window.pages["PCSEL"])
        self.assertTrue(laser.isChecked())
        self.assertFalse(general.isChecked())

    def test_laser_workspace_contains_reference_regions_and_primary_run_action(self):
        self._click_workspace("laser pcsel simulations")
        page = self.window.pages["PCSEL"]
        visible_text = "\n".join(label.text() for label in page.findChildren(QLabel))
        normalized = _normal(visible_text)
        for required in ("device", "structure", "mode", "solver", "simulation results"):
            self.assertIn(required, normalized, f"missing laser layout region: {required}")

        run = page.findChild(QPushButton, "runLaserSimulationDashboard")
        self.assertIsNotNone(run)
        self.assertIn("run", _normal(run.text()))
        self.assertIn("simulation", _normal(run.text()))
        self.assertTrue(run.isEnabled())

    def test_laser_workflow_covers_device_through_comsol_and_report(self):
        page = self.window.pages["PCSEL"]
        tabs = page.findChild(QTabWidget, "laserWorkflowTabs")
        self.assertIsNotNone(tabs)
        names = [_normal(tabs.tabText(index)) for index in range(tabs.count())]
        for stage in ("device setup", "optical modes", "electrical and gain",
                      "results", "modulation", "thermal", "comsol", "report"):
            self.assertTrue(any(stage in name for name in names),
                            f"missing workflow stage {stage!r}: {names}")

    def test_window_retains_supported_minimum_and_laser_content_at_compact_size(self):
        self.assertGreaterEqual(self.window.minimumWidth(), 640)
        self.assertGreaterEqual(self.window.minimumHeight(), 480)
        self.window.resize(self.window.minimumSize())
        self.app.processEvents()
        self._click_workspace("laser pcsel simulations")
        page = self.window.pages["PCSEL"]
        self.assertTrue(page.isVisible())
        self.assertGreater(page.width(), 0)
        self.assertGreater(page.height(), 0)
        self.assertIsNotNone(page.findChild(QTabWidget, "laserWorkflowTabs"))
        self.assertIsNotNone(page.findChild(QPushButton, "runLaserSimulationDashboard"))

    def test_run_action_renders_solver_results_in_all_analysis_views(self):
        self.window.resize(1920, 1080)
        self._click_workspace("laser pcsel simulations")
        page = self.window.pages["PCSEL"]
        page.tabs.setCurrentIndex(page.results_index)
        self.app.processEvents()
        page.current_points.setValue(17)
        QTest.mouseClick(page.findChild(QPushButton, "runLaserSimulationDashboard"),
                         Qt.MouseButton.LeftButton)
        self.app.processEvents()

        result = page.last_result
        self.assertIsNotNone(result)
        self.assertEqual(len(result["currents_ma"]), 17)
        self.assertIn("solved", _normal(page.run_state.text()))
        self.assertIn("threshold", _normal(page.report.toPlainText()))
        self.assertGreater(len(page.laser_canvas.figure.axes[0].lines), 0)
        self.assertIn("independently", page.mode_canvas.figure.axes[0].texts[0].get_text())
        self.assertGreater(len(page.modulation_canvas.figure.axes[0].lines), 0)
        self.assertGreater(len(page.thermal_canvas.figure.axes[0].lines), 0)
        self.assertGreater(page.mode_table.rowCount(), 0)
        self.assertEqual(page.tabs.widget(page.results_index).verticalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
