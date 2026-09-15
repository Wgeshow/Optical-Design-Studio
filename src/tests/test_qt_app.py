"""Complete-window navigation, appearance, and real solver workflow regressions."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
_bootstrap_library=tempfile.TemporaryDirectory(prefix='s4_qt_app_import_')
os.environ.setdefault('S4_LIBRARY_ROOT',_bootstrap_library.name)

from PyQt6.QtCore import QSettings,Qt,QCoreApplication,QEvent
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QPushButton
from qt_app import OpticalStudio
from qt_core import ProjectStore
from qt_common import theme_manager,ThemeManager,COLORS,preferences
from data_library import DataLibrary,read_json


class DesktopApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='s4_qt_app_')
        self.addCleanup(self.temp.cleanup)
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.store.update_settings(dict(NumG=9,wl_start_nm=1549,wl_stop_nm=1551,wl_step_nm=1))
        self.store.update_performance(dict(workers=1,timeout_seconds=90))
        self.preferences=preferences()
        self.old_theme=self.preferences.value('theme')
        self.previous_mode=theme_manager().mode
        self.window=OpticalStudio(self.store)
        self.window.resize(1280,900)
        self.window.show()
        self.errors=[]
        self.store.run_failed.connect(self.errors.append)
        self.app.processEvents()

    def tearDown(self):
        if self.store.busy:
            self.store.cancel()
            self.wait_idle(20,check_errors=False)
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        if self.old_theme is None:
            self.preferences.remove('theme')
        else:
            self.preferences.setValue('theme',self.old_theme)
        theme_manager().apply(self.previous_mode,persist=False)

    def wait_idle(self,timeout=90,check_errors=True):
        deadline=time.monotonic()+timeout
        ticks=0
        while self.store.busy and time.monotonic()<deadline:
            QTest.qWait(20)
            ticks+=1
        self.assertFalse(self.store.busy,'Native calculation did not finish')
        if check_errors:
            self.assertEqual(self.errors,[])
        return ticks

    def test_themes_persist_and_all_pages_follow_one_structure(self):
        for mode in ('light','dark'):
            theme_manager().apply('dark' if mode=='light' else 'light',persist=False)
            self.window.theme_select.setCurrentIndex(self.window.theme_select.findData(mode))
            self.app.processEvents()
            self.assertEqual(ThemeManager().mode,mode)
            for index,page in enumerate(self.window.pages.values()):
                self.window.navigation.setCurrentRow(index)
                self.app.processEvents()
                self.assertEqual(self.window.stack.currentIndex(),index)
                self.assertIs(page.store,self.store)
                self.assertFalse(self.window.grab().isNull())
            from matplotlib.colors import to_hex
            self.assertEqual(to_hex(self.window.pages['Structure'].plot.figure.get_facecolor()),COLORS[mode]['panel'])
        structure=self.window.pages['Structure']
        structure.select_layer('Device')
        structure.layer_name.setText('PCS top')
        QTest.mouseClick(structure.findChild(QPushButton,'applyLayer'),Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.store.layers.iloc[1].Name,'PCS top')
        self.assertTrue(self.window.structure_notice.isVisible())
        self.assertIn('PCS top',self.window.structure_notice.toolTip())
        self.assertGreaterEqual(self.window.pages['Fields'].layer.findData('PCS top'),0)
        self.assertGreaterEqual(self.window.pages['Optimize'].holes.layer.findData('PCS top'),0)

    def test_close_save_failure_remains_reviewable_instead_of_raising_from_qt(self):
        event=QCloseEvent()
        with patch.object(self.store,'_autosave',side_effect=PermissionError('disk unavailable')):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertIn('disk unavailable',self.window.status.text())

    def test_real_spectrum_and_field_runs_render_and_remain_in_saved_work(self):
        simulation=self.window.pages['Simulate']
        simulation.run()
        self.assertGreater(self.wait_idle(),0)
        self.assertEqual(simulation.results.rowCount(),3)
        self.assertEqual(len(simulation.plot.figure.axes[0].lines),3)
        self.assertTrue((simulation.directory/'project.json').is_file())
        fields=self.window.pages['Fields']
        fields.grid.setValue(3)
        fields.run()
        self.wait_idle()
        self.assertTrue((fields.field_directory/'electric_fields.csv').is_file())
        self.assertGreaterEqual(len(fields.plot.figure.axes),4)
        self.assertGreaterEqual(self.window.pages['Saved work'].selection.count(),2)

    def test_real_small_field_assisted_target_search_saves_all_design_conditions(self):
        optimize=self.window.pages['Optimize']
        for key,value in dict(half_window=10,step=5,grid_steps=3,trials=3,initial=2,finalists=1,
                              min_q=1,field_grid=3,map_grid=3).items():
            optimize.target_controls[key].setValue(value)
        optimize.target_controls['reuse'].setChecked(False)
        optimize.holes.min_x.setValue(.08)
        optimize.holes.max_x.setValue(.12)
        self.assertTrue(optimize.holes.add_range())
        optimize.run_target()
        self.wait_idle()
        directory=optimize.result_directories['target']
        summary=read_json(directory/'search_summary.json')
        self.assertEqual(summary['status'],'complete',summary)
        self.assertGreaterEqual(summary['new_evaluations'],3,summary)
        self.assertGreaterEqual(summary['field_feature_records'],3,summary)
        self.assertGreaterEqual(optimize.target_results.rowCount(),3,summary)
        self.assertTrue((directory/'target_history.json').is_file())
        self.assertTrue((directory/'field_training.csv').is_file())
        self.assertEqual(summary['tolerance_nm'],5)
        # The lossless default cannot meet >99% absorption; do not enable a false recommendation.
        self.assertIsNone(summary['maximum_verified_Q'])
        self.assertFalse(optimize.apply_target.isEnabled())


if __name__=='__main__':
    unittest.main()
