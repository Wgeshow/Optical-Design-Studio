"""Native material and saved spectra preserve raw samples, units, and exports."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication, QWidget
from data_library import DataLibrary, write_json
from qt_core import ProjectStore
from qt_materials import MaterialsPage
from qt_library import LibraryPage

APP=QApplication.instance() or QApplication([])


class NativeMaterialSavedPlotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.store=ProjectStore(DataLibrary(self.root/'library'),restore=False)
        self.widgets=[]

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def page(self,kind):
        page=kind(self.store)
        self.widgets.append(page)
        page.resize(1460,950)
        page.show()
        for _ in range(5):APP.processEvents()
        return page

    def material_page(self):
        page=self.page(MaterialsPage)
        path=self.root/'measured_native.csv'
        path.write_text('wavelength,n,k\n1.0,2.1,0.001\n1.5,2.3,0.02\n2.0,2.2,0.005\n',encoding='utf-8')
        page.import_unit.setCurrentText('um')
        page.import_paths([str(path)])
        APP.processEvents()
        return page

    def record_for_line(self,canvas,line):
        records=[record for record in canvas.data_records if record.get('source_artist') is line]
        self.assertEqual(len(records),1)
        return records[0]

    def test_measured_material_dual_native_axes_keep_nm_and_raw_nk_through_export(self):
        page=self.material_page()
        canvas=page.plot.canvas
        self.assertIsInstance(canvas,QWidget)
        self.assertEqual(type(canvas).__name__,'NativeFigureCanvas')
        self.assertEqual(canvas.unsupported_artists,[])
        main,secondary=page.plot.figure.axes
        self.assertIsNot(canvas.axis_views[main],canvas.axis_views[secondary])
        expected_x=np.array([1000.,1500.,2000.])
        for axis,expected_y in ((main,[2.1,2.3,2.2]),(secondary,[.001,.02,.005])):
            line=axis.lines[0]
            record=self.record_for_line(canvas,line)
            np.testing.assert_array_equal(record['raw_x'],expected_x)
            np.testing.assert_array_equal(record['raw_y'],expected_y)
        self.assertEqual(secondary.get_yscale(),'log')
        self.assertEqual(canvas.plots[main].getAxis('bottom').labelText,'Wavelength (nm)')
        self.assertEqual(canvas.plots[main].getAxis('left').labelText,'Refractive index, n')
        self.assertEqual(canvas.plots[secondary].getAxis('right').labelText,'Extinction coefficient, k')
        before=copy.deepcopy(self.store.project())
        svg=self.root/'material-native.svg'
        page.plot.export_figure(svg)
        self.assertIn('<svg',svg.read_text(encoding='utf-8'))
        self.assertIn('Wavelength (nm)',svg.read_text(encoding='utf-8'))
        self.assertEqual(self.store.project(),before)
        exported=self.root/'constants.csv'
        with patch('qt_result_export.QFileDialog.getSaveFileName',return_value=(str(exported),'CSV')):
            page.export_constants()
        expected=pd.DataFrame({'wavelength_nm':expected_x,'n':[2.1,2.3,2.2],'k':[.001,.02,.005]})
        pd.testing.assert_frame_equal(pd.read_csv(exported),expected)
        for axis,expected_y in ((main,[2.1,2.3,2.2]),(secondary,[.001,.02,.005])):
            np.testing.assert_array_equal(axis.lines[0].get_ydata(),expected_y)

    def test_single_k_keeps_native_wavelength_axis_and_exact_values(self):
        page=self.material_page()
        page.plot_mode.setCurrentText('k only')
        APP.processEvents()
        main,secondary=page.plot.figure.axes
        self.assertTrue(main.get_visible())
        self.assertFalse(secondary.get_visible())
        self.assertEqual(main.get_xlabel(),'Wavelength (nm)')
        self.assertEqual(main.get_ylabel(),'Extinction coefficient, k')
        self.assertEqual(main.get_yscale(),'log')
        record=self.record_for_line(page.plot.canvas,main.lines[0])
        self.assertEqual(page.plot.canvas.unsupported_artists,[])
        np.testing.assert_array_equal(record['raw_y'],[.001,.02,.005])
        self.assertEqual(page.plot.canvas.plots[main].getAxis('bottom').labelText,'Wavelength (nm)')
        page.plot_mode.setCurrentText('n only')
        APP.processEvents()
        main=page.plot.figure.axes[0]
        self.assertEqual(main.get_yscale(),'linear')
        np.testing.assert_array_equal(self.record_for_line(page.plot.canvas,main.lines[0])['raw_y'],[2.1,2.3,2.2])

    def test_saved_angle_percent_ticks_keep_fraction_samples_and_complete_csv(self):
        directory=self.store.library.runs/'native-angle'
        directory.mkdir()
        write_json(directory/'project.json',self.store.portable_project())
        data=pd.DataFrame({'wavelength_nm':np.full(5002,1550.),'angle_deg':np.linspace(0,80,5002),
            'R':np.linspace(.1,.2,5002),'T':np.linspace(.8,.7,5002),'A':np.full(5002,.1)})
        data.loc[5001,['R','T','A']]=[.005,.005,.99]
        source=directory/'results.csv'
        data.to_csv(source,index=False)
        original=source.read_bytes()
        self.store.library.record(directory,kind='simulation',status='complete',title='Native angle samples')
        page=self.page(LibraryPage)
        canvas=page.plot.canvas
        self.assertEqual(type(canvas).__name__,'NativeFigureCanvas')
        self.assertEqual(canvas.unsupported_artists,[])
        axis=page.plot.figure.axes[0]
        self.assertEqual(axis.get_xlabel(),'Angle (degrees)')
        self.assertEqual(canvas.plots[axis].getAxis('bottom').labelText,'Angle (degrees)')
        self.assertEqual(page.table.rowCount(),5000)
        complete=pd.read_csv(source)
        for line,column in zip(axis.lines,('R','T','A')):
            record=self.record_for_line(canvas,line)
            self.assertEqual(len(record['raw_x']),5002)
            np.testing.assert_array_equal(record['raw_x'],complete.angle_deg)
            np.testing.assert_array_equal(record['raw_y'],complete[column])
            if column=='A':self.assertEqual(record['raw_y'][-1],.99)
        percent=canvas.plots[axis].getAxis('left').tickStrings([.2],1,.1)[0]
        self.assertIn('20',percent)
        self.assertIn('%',percent)
        self.assertEqual(source.read_bytes(),original)
        exported=self.root/'full-saved.csv'
        with patch('qt_library.QFileDialog.getSaveFileName',return_value=(str(exported),'CSV')):
            page.save_csv()
        self.assertEqual(exported.read_bytes(),original)
        self.assertEqual(len(pd.read_csv(exported)),5002)


if __name__=='__main__':unittest.main()
