"""The shell can mirror real journeys without losing advanced destinations."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication, QWidget
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_journey import JourneyBar, StageHost
from qt_photonic_bands import PhotonicBandsWorkspace
from qt_pcsel_research_setup import PcselResearchWorkspace
from research_catalog import list_capabilities

APP = QApplication.instance() or QApplication([])


class JourneyNavigationContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='journey-navigation-')
        self.store = ProjectStore(DataLibrary(Path(self.temporary.name)/'library'), restore=False)
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page.close()
            page.deleteLater()
        APP.processEvents()
        self.temporary.cleanup()

    def own(self, page):
        self.pages.append(page)
        return page

    def test_bar_changes_publish_one_complete_state_without_navigation_requests(self):
        bar = self.own(JourneyBar(['Device', 'Run', 'Results']))
        changed, requested = QSignalSpy(bar.navigationChanged), QSignalSpy(bar.stageRequested)
        snapshots = []
        bar.navigationChanged.connect(lambda: snapshots.append((len(bar.stages), bar._current)))
        bar.set_current(2)
        bar.set_current(2)
        self.assertEqual(len(changed), 1)
        bar.set_stages(['Device', 'Run'])
        self.assertEqual(snapshots, [(3, 2), (2, 1)])
        bar.set_stages(['Device', 'Run'])
        self.assertEqual(len(changed), 2)
        bar.set_stages([dict(title='Device', description='New description'), dict(title='Run')])
        self.assertEqual(len(changed), 3)
        bar.set_stages([])
        self.assertEqual(snapshots[-1], (0, -1))
        self.assertEqual(len(changed), 4)
        self.assertEqual(len(requested), 0)

    def test_promoted_bar_stays_hidden_during_resize_and_state_updates(self):
        bar = self.own(JourneyBar([dict(title='Device', description='Edit geometry'), 'Run']))
        bar.resize(1200, 150)
        bar.show()
        APP.processEvents()
        self.assertFalse(bar.strip.isHidden())
        bar.set_external_navigation(True)
        for width in (700, 1300):
            bar.resize(width, 150)
            bar.resizeEvent(QResizeEvent(QSize(width, 150), QSize(1000, 150)))
            bar.set_current(1)
            bar.set_stages([dict(title='Device', description='Edit geometry'), 'Run'])
            bar.apply_theme()
            APP.processEvents()
            self.assertTrue(bar.isHidden())
            for control in (bar.strip, bar.selector, bar.position, bar.back_button, bar.next_button, bar.description):
                self.assertTrue(control.isHidden())
        bar.set_external_navigation(False)
        APP.processEvents()
        self.assertFalse(bar.isHidden())
        self.assertFalse(bar.strip.isHidden())
        self.assertFalse(bar.back_button.isHidden())
        bar.resize(700, 150)
        APP.processEvents()
        self.assertTrue(bar.strip.isHidden())
        self.assertFalse(bar.selector.isHidden())

    def test_shell_request_selects_existing_stage_without_signal_loop(self):
        host = self.own(StageHost())
        first, second = QWidget(), QWidget()
        host.add_stage('Device', first)
        host.add_stage('Run', second)
        bar = host.bar
        bar.set_external_navigation(True)
        changed = QSignalSpy(bar.navigationChanged)
        bar.navigationChanged.connect(lambda: bar.set_current(host.stack.currentIndex()))
        bar.stageRequested.emit(1)
        self.assertIs(host.stack.currentWidget(), second)
        self.assertEqual(bar._current, 1)
        self.assertEqual(len(changed), 1)
        self.assertTrue(bar.isHidden())

    def test_coupled_physics_subsections_do_not_jump_back_to_device(self):
        from qt_simulation_setup import SimulationSetupWorkspace
        self.store.activate_study('coupled')
        page = self.own(SimulationSetupWorkspace(self.store, mode='coupled', document_id='coupled'))
        flow = page.setup_flow
        flow.show_stage(1)
        self.assertEqual(flow.journey_bar._current, 1)
        for target in ('electrical.overview', 'optical.overview'):
            page.select_section(target)
            self.assertEqual(flow.journey_bar._current, 1, target)
        flow.show_stage(0)
        self.assertEqual(flow.journey_bar._current, 0)

    def test_every_band_section_has_a_stage_and_same_tab_builder_switch_notifies(self):
        page = self.own(PhotonicBandsWorkspace(self.store))
        expected = {'Overview': 0, 'Materials': 1, 'k-space path': 2,
            'Solver & accuracy': 3, 'Outputs': 3, 'Parameter sweep': 3,
            'Convergence': 3, 'Review & Run': 4, 'Paper benchmarks': 4,
            'Check inputs': 4, 'Run & progress': 5, 'Results': 6}
        with patch.object(self.store, 'start_run') as start:
            for index in range(page.tabs.count()):
                if not page.tabs.isTabVisible(index):
                    continue
                page.tabs.setCurrentIndex(index)
                name = page.tabs.tabText(index)
                self.assertGreaterEqual(page.journey_bar._current, 0, name)
                if name in expected:
                    self.assertEqual(page.journey_bar._current, expected[name], name)
            page.show_stage('unit')
            changed = QSignalSpy(page.journey_bar.navigationChanged)
            page.show_stage('build')
            self.assertEqual(page.journey_bar._current, 1)
            self.assertEqual(len(changed), 1)
            page.show_stage('unit')
            self.assertEqual(page.journey_bar._current, 0)
            self.assertEqual(len(changed), 2)
            start.assert_not_called()

    def test_every_allowed_pcsel_section_retains_unique_stage_and_bound_editors(self):
        for engine in ('pcsel', 'pcsel_transport'):
            capability = next(row for row in list_capabilities() if row['engine'] == engine)
            page = self.own(PcselResearchWorkspace(self.store, capability))
            models = ('vertical', 'cwt', 'finite', 'beam', 'aperture', 'gme', 'rcwa_poles') if engine == 'pcsel' else (None,)
            fields = dict(page.fields)
            with patch.object(self.store, 'start_run') as start:
                for model in models:
                    if model is not None:
                        page.select_model(model)
                    flow = page.study_flow
                    indices = [section for _, sections in flow.stages for section in sections]
                    self.assertEqual(len(indices), len(set(indices)), model)
                    for index in page.journey_allowed_sections():
                        if not page.tabs.isTabVisible(index):
                            continue
                        self.assertIn(index, indices, (model, page.tabs.tabText(index)))
                        page.tabs.setCurrentIndex(index)
                        self.assertGreaterEqual(flow.bar._current, 0, (model, page.tabs.tabText(index)))
                        self.assertIn(index, flow.stages[flow.bar._current][1])
                    self.assertEqual([title for title, _ in flow.stages[-3:]],
                                     ['Check inputs', 'Run & progress', 'Results'])
                    for key, widget in fields.items():
                        self.assertIs(page.fields[key], widget)
                start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
