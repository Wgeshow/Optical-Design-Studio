"""Reference layout preserves model selection and independent layer controls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_index_shift import IndexShiftPage
from test_backend import MATERIALS,LAYERS,PATTERNS,SETTINGS
from model import DEFAULT_PERFORMANCE

class ReferenceIndexShiftTests(unittest.TestCase):
    def test_three_columns_and_toolbar_remain_hidden(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(DataLibrary(directory),restore=False)
            store.load_project(dict(materials=MATERIALS,layers=LAYERS,patterns=PATTERNS,settings=SETTINGS,performance=DEFAULT_PERFORMANCE))
            page=IndexShiftPage(store);page.resize(1460,850);page.show();app.processEvents()
            self.assertEqual(page.workbench.splitter.count(),3)
            self.assertEqual(page.setup_layout.itemAt(0).widget().text(),'Simulation Setup')
            self.assertTrue(page.workbench.preview.isVisible())
            page.workbench.show_results();page.workbench.input_tabs.setCurrentIndex(1);app.processEvents()
            self.assertTrue(page.plot.isVisible());self.assertTrue(page.layers.isVisible())
            self.assertTrue(page.plot.toolbar.isHidden())
            page.plot.retheme();self.assertTrue(page.plot.toolbar.isHidden())
            self.assertLess(page.plot.mapTo(page,page.plot.rect().topLeft()).x(),page.layers.mapTo(page,page.layers.rect().topLeft()).x())
            page.material.setCurrentIndex(page.material.findData('Film'))
            page.equal.setChecked(False)
            self.assertFalse(page.layers.isColumnHidden(2))
            page.sweep_mode.setCurrentIndex(1)
            page.workbench.input_tabs.setCurrentIndex(0);app.processEvents()
            self.assertTrue(page.carrier_button.isVisible())
            self.assertTrue(page.layers.isColumnHidden(2))
            page.close();page.deleteLater();app.processEvents()

    def test_percent_power_axes_preserve_fraction_data_and_signed_changes(self):
        from test_fixed_readout import FixedReadoutTests
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'run';FixedReadoutTests().simulate(run)
            page=IndexShiftPage(ProjectStore(DataLibrary(Path(directory)/'library'),restore=False))
            page.directory=run;page.show_result({})
            for view in ['Fixed-wavelength response','Overlaid spectra']:
                page.readout_view.setCurrentText(view)
                axis=page.plot.figure.axes[0]
                self.assertEqual(axis.get_ylim(),(0,1))
                self.assertEqual(axis.yaxis.get_major_formatter()(1),'100%')
                self.assertIn('(%)',axis.get_ylabel())
            page.readout_view.setCurrentText('Fixed-wavelength response')
            self.assertEqual(list(page.plot.figure.axes[0].lines[0].get_ydata()),[.9,.25])
            page.readout_view.setCurrentText('Change from baseline')
            axis=page.plot.figure.axes[0]
            self.assertAlmostEqual(axis.lines[0].get_ydata()[1],-.65)
            self.assertLess(axis.get_ylim()[0],-.65)
            self.assertIn('percentage points',axis.get_ylabel())
            self.assertEqual(axis.yaxis.get_major_formatter()(-.65),'−65%')
            page.close();page.deleteLater();app.processEvents()

if __name__=='__main__':unittest.main()
