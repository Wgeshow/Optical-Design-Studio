"""Offscreen UI contracts; no runtime probes, solver runs or visible windows."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from PyQt6.QtWidgets import QApplication,QWidget,QVBoxLayout,QPushButton,QLabel,QGroupBox
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_fdtd import FDTDPage
from qt_optical_journey import install_optical_journey
from qt_optical_domain_canvas import OpticalDomainCanvas

APP=QApplication.instance() or QApplication([])

class OpticalRuntimeLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='runtime-layout-',dir=Path.cwd())
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.window=QWidget();layout=QVBoxLayout(self.window)
        self.window._navigate_route=Mock()
        self.settings=Mock();self.window.pages={'Settings':self.settings}
        self.page=FDTDPage(self.store);layout.addWidget(self.page)
        self.host=install_optical_journey(self.page,self.store,'fdtd')
        self.window.resize(1300,850);self.window.show();APP.processEvents()

    def tearDown(self):
        self.window.close();self.window.deleteLater();APP.processEvents();self.temp.cleanup()

    def test_runtime_link_selects_runtime_and_meep_anchor_without_run(self):
        self.host.select_stage('checks')
        with patch.object(self.store,'start_run') as run:
            button=next(b for b in self.page.findChildren(QPushButton) if b.text()=='Open solver runtime settings')
            button.click();run.assert_not_called()
        self.window._navigate_route.assert_called_once_with(6)
        self.settings.select_section.assert_called_once_with('meep runtimes')

    def test_domain_note_does_not_absorb_preview_height(self):
        self.host.select_stage('structure');APP.processEvents()
        note=next(v for v in self.page.findChildren(QLabel) if v.text().startswith('This study'))
        canvas=self.page.findChild(OpticalDomainCanvas)
        self.assertTrue(note.isVisible());self.assertTrue(canvas.isVisible())
        self.assertLessEqual(note.height(),note.sizeHint().height()+4)
        self.assertGreater(canvas.height(),note.height()*3)

    def test_results_prioritize_plot_after_wide_compact_wide_resize(self):
        from PyQt6.QtCore import Qt
        self.host.select_stage('results');APP.processEvents()
        split=self.page.journey_results_layout
        for width in (1500,860,1500):
            self.window.resize(width,900);APP.processEvents();APP.processEvents()
            if width==1500:
                self.assertEqual(split.orientation(),Qt.Orientation.Horizontal)
                sizes=split.sizes()
                self.assertGreater(sizes[0]/sum(sizes),.65)
                self.assertGreater(sizes[1],200)
            else:
                self.assertEqual(split.orientation(),Qt.Orientation.Vertical)
                self.assertGreaterEqual(split.widget(0).height(),620)
                self.assertGreaterEqual(split.widget(1).height(),240)

    def test_fields_have_one_sidebar_and_full_width_map(self):
        from qt_compute import FieldsPage
        from PyQt6.QtCore import Qt
        page=FieldsPage(self.store);self.page.hide();self.window.layout().addWidget(page)
        host=install_optical_journey(page,self.store,'tools.fields');host.select_stage('results')
        self.window.resize(1500,900);APP.processEvents();APP.processEvents()
        split=page.journey_results_layout
        self.assertEqual(split.orientation(),Qt.Orientation.Horizontal)
        self.assertTrue(split.widget(0).isAncestorOf(page.plot))
        self.assertTrue(split.widget(1).isAncestorOf(page.arrows))
        self.assertTrue(split.widget(1).isAncestorOf(page.maximum))
        self.assertGreater(split.sizes()[0]/sum(split.sizes()),.65)
        self.assertGreater(page.plot.width(),800)
        self.assertTrue(page.arrows.isVisible())
        self.assertTrue(page.contour_enabled.isVisible())

    def test_run_page_has_no_empty_legacy_setup_groups(self):
        self.host.select_stage('run');APP.processEvents()
        current=self.host.stack.currentWidget()
        obsolete={'Domain & excitation','Spectrum','Boundaries & stopping','Simulation Setup'}
        self.assertFalse([g.title() for g in current.findChildren(QGroupBox) if g.title() in obsolete])
        self.assertTrue(any(b.text()=='Run FDTD simulation' for b in current.findChildren(QPushButton)))
        for key,stage in [('resolution','structure'),('wavelength_min_nm','parameters'),('run_after_sources','stopping')]:
            self.host.select_stage(stage);APP.processEvents()
            self.assertTrue(self.host.stack.currentWidget().isAncestorOf(self.page.controls[key]))
            self.assertTrue(self.page.controls[key].isVisible())

if __name__=='__main__':unittest.main()
