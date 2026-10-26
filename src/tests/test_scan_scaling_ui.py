import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from data_library import DataLibrary,write_json
from scan_storage import SpectrumResults,FieldSampleIndex
from qt_core import ProjectStore
from qt_compute import SimulationPage,FieldSamplesModel

APP=QApplication.instance() or QApplication([])


class LargeScanUiTests(unittest.TestCase):
    def test_interrupted_sparse_spectrum_loads_peak_and_every_saved_sample(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);results=SpectrumResults(root/'spectrum.sqlite',create=True)
            rows=[[9,1509.,0.,.1,.2,.7],[31,1531.,0.,.01,.01,.98],[44,1544.,0.,.2,.3,.5]]
            results.add_batch(rows);results.export_csv(root/'results.csv');results.close()
            page=SimulationPage(ProjectStore(DataLibrary(root/'library'),restore=False));page.directory=root
            try:
                page.load_spectrum();page.update_peak()
                self.assertEqual(page.sample_position.maximum(),3)
                self.assertIn('1531',page.peak_summary.text())
                self.assertEqual(page.sample_position.value(),2)
                self.assertEqual(page.plot.nearest_sample(1544.),2)
                page.sample_position.setValue(3)
                self.assertIn('1544',page.sample_readout.text())
                self.assertEqual(page.plot._cursor_position,1544.)
                page.plot.plot.setXRange(1530.,1532.,padding=0);page.plot._load_visible_samples()
                self.assertIn(1,page.plot.raw.point_index.values)
                out=root/'export.csv';page.plot.export_raw_csv(out)
                self.assertEqual(out.read_bytes(),(root/'results.csv').read_bytes())
            finally:
                page.close();page.deleteLater();APP.processEvents()

    def test_exact_sample_peak_export_and_zoom_beyond_preview(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);results=SpectrumResults(root/'spectrum.sqlite',create=True)
            for offset in range(0,30001,1000):
                results.add_batch([[i,1500+i*.001,0.,.1,.2,.99 if i==29999 else .7] for i in range(offset,min(offset+1000,30001))])
            results.export_csv(root/'results.csv');results.close()
            page=SimulationPage(ProjectStore(DataLibrary(root/'library'),restore=False));page.directory=root
            try:
                with patch.object(page.plot,'export_figure'):page.show_result({})
                self.assertLessEqual(len(page.result_frame),16000)
                self.assertEqual(page.sample_position.maximum(),30001)
                self.assertIn('30000',page.peak_summary.text())
                page.sample_position.setValue(30001)
                self.assertIn('1530',page.sample_readout.text())
                self.assertEqual(page.plot._cursor_position,1530.)
                self.assertEqual(page.plot.nearest_sample(1529.9996),30000)
                page.plot.plot.setXRange(1529.99,1530.,padding=0)
                page.plot._load_visible_samples()
                self.assertLessEqual(len(page.plot.raw),12)
                self.assertIn(29999,page.plot.raw.point_index.values)
                page.plot.fit_data()
                self.assertLess(page.plot.plot.getViewBox().viewRange()[0][0],1500)
                out=root/'export.csv';page.plot.export_raw_csv(out)
                self.assertEqual(out.read_bytes(),(root/'results.csv').read_bytes())
            finally:
                page.close();page.deleteLater();APP.processEvents()

    def test_field_selector_is_virtual_and_all_samples_are_accessible(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fields=root/'fields';fields.mkdir()
            index=FieldSampleIndex(fields,create=True)
            index.connection.executemany('INSERT INTO samples VALUES (?,?,?,?,?)',
                ((i,i,1500+i*.001,0.,'.' if i==0 else f'samples/{i+1:06d}') for i in range(100001)))
            index.connection.commit();index.close()
            write_json(fields/'samples.json',dict(schema_version=2,status='complete',count=100001,index='samples.sqlite'))
            page=SimulationPage(ProjectStore(DataLibrary(root/'library'),restore=False));page.directory=root
            try:
                with patch('qt_compute.field_figure',side_effect=lambda *a,**kw:Figure()) as render:
                    page.load_generated_fields()
                    self.assertIsInstance(page.field_sample.model(),FieldSamplesModel)
                    self.assertLessEqual(page.field_sample.count(),200)
                    self.assertEqual(page.field_position.maximum(),100001)
                    self.assertLess(page.field_sample.model().sample.cache_info().currsize,100)
                    render.assert_not_called()
                    page.show();page.result_tabs.setCurrentWidget(page.generated_fields);APP.processEvents()
                    page.field_position.setValue(100001)
                    self.assertEqual(page.field_sample.model().offset+page.field_sample.currentIndex(),100000)
                    self.assertEqual(Path(render.call_args.args[0]),fields/'samples'/'100001')
            finally:
                page.close();page.deleteLater();APP.processEvents()


if __name__=='__main__':unittest.main()
