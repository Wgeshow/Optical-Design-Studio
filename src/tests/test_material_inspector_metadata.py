"""Actual material inspector metadata and validated interpolation persistence."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from model import sample_nk
from qt_core import ProjectStore
from qt_materials import MaterialsPage, material_display_color

APP=QApplication.instance() or QApplication([])


class MaterialInspectorMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.store=ProjectStore(DataLibrary(self.root/'library'),restore=False)
        self.page=MaterialsPage(self.store)
        self.measured=self.root/'Measured.csv'
        self.measured.write_text('wavelength,n,k\n1000,2,.01\n2000,4,1\n',encoding='utf-8')
        self.page.import_paths([str(self.measured)])
        self.page.selection.setCurrentIndex(self.page.selection.findData('project:Measured'))

    def tearDown(self):
        self.page.close();self.page.deleteLater();APP.processEvents()
        self.temp.cleanup()

    def optical_inputs(self):
        project=self.store.project()
        return {key:copy.deepcopy(project[key]) for key in ('materials','layers','patterns','settings','performance')}

    def test_preview_color_and_notes_roundtrip_without_changing_optical_inputs_or_undo(self):
        before=self.optical_inputs();undo_count=len(self.store._undo)
        source_before=self.page.material_source.text()
        original=self.measured.read_bytes()
        self.page.set_material_color('#ABCDEF')
        self.assertEqual(self.page.material_color.text(),'#abcdef')
        self.assertEqual(self.store.appearance['material_colors'],{'Measured':'#abcdef'})
        note='Measured at 295 K\nExact user note: μm and trailing space '
        self.page.material_notes.setPlainText(note)
        self.assertTrue(self.page.save_material_notes())
        self.assertEqual(self.store.appearance['material_notes'],{'Measured':note})
        self.assertEqual(self.page.preset_notes.text(),note)
        self.assertEqual(self.optical_inputs(),before)
        self.assertEqual(len(self.store._undo),undo_count)
        self.assertEqual(self.measured.read_bytes(),original)
        path=self.root/'metadata.json';self.store.save_project(path)
        restored=ProjectStore(self.store.library,restore=False);restored.load_project(path)
        self.assertEqual(restored.appearance,self.store.appearance)
        self.assertEqual(ProjectStore(self.store.library,restore=True).appearance,self.store.appearance)
        self.page.preset_name.setText('Measured notes');self.page.save_selected()
        entry=next(entry for entry in self.store.library.presets().values() if entry['label']=='Measured notes')
        self.assertEqual(entry['notes'],note)
        self.assertEqual(entry['source_notes'],source_before)
        self.assertEqual(self.page.material_source.text(),source_before)
        reopened=MaterialsPage(restored)
        reopened.selection.setCurrentIndex(reopened.selection.findData('project:Measured'))
        self.assertEqual(reopened.material_source.text(),source_before)
        self.assertEqual(reopened.material_notes.toPlainText(),note)
        reopened.close();reopened.deleteLater();APP.processEvents()
        clean=ProjectStore(DataLibrary(self.root/'clean-library'),restore=False)
        clean.load_project(self.store.portable_project())
        standalone=MaterialsPage(clean)
        standalone.selection.setCurrentIndex(standalone.selection.findData('project:Measured'))
        self.assertEqual(standalone.material_source.text(),source_before)
        self.assertEqual(standalone.material_notes.toPlainText(),note)
        self.assertIn('material_provenance',clean.portable_project())
        standalone.close();standalone.deleteLater();APP.processEvents()
        self.page.reset_material_color()
        self.assertEqual(self.store.appearance['material_colors'],{})
        self.assertEqual(self.store.appearance['material_notes'],{'Measured':note})
        for name,color in [('GaAs','#ff6884'),('AlGaAs','#8b80ff'),('SiC','#50d689'),('Air','#dce6ed'),('SiO2','#ffda55')]:
            self.assertEqual(material_display_color(name,{}),color)

    def test_note_switch_flushes_previous_material_and_failed_save_keeps_draft(self):
        self.page.material_notes.setPlainText('Measured pending note')
        air=self.page.selection.findData('project:Air')
        self.assertGreaterEqual(air,0)
        self.page.selection.setCurrentIndex(air)
        self.assertEqual(self.store.appearance['material_notes'],{'Measured':'Measured pending note'})
        self.assertNotEqual(self.page.material_notes.toPlainText(),'Measured pending note')
        self.page.material_notes.setPlainText('Air pending note')
        before=copy.deepcopy(self.store.appearance)
        with patch.object(self.store,'_autosave',side_effect=OSError('disk full')):
            self.assertFalse(self.page.save_material_notes())
            self.page.selection.setCurrentIndex(self.page.selection.findData('project:Measured'))
            self.assertEqual(self.page.selection.currentData(),'project:Air')
            self.assertEqual(self.page.material_name.text(),'Air')
            self.assertEqual(self.page._notes_material,'Air')
            self.page.material_notes.setPlainText('Air draft edited after failed switch')
        self.assertEqual(self.store.appearance,before)
        self.assertEqual(self.page.material_notes.toPlainText(),'Air draft edited after failed switch')
        self.assertEqual(self.page._notes_pending,('Air','Air draft edited after failed switch'))
        self.assertIn('disk full',self.page.status.text())
        self.assertTrue(self.page.save_material_notes())
        self.assertEqual(self.store.appearance['material_notes']['Air'],'Air draft edited after failed switch')
        self.assertEqual(self.store.appearance['material_notes']['Measured'],'Measured pending note')
        self.page.selection.setCurrentIndex(self.page.selection.findData('project:Measured'))
        self.assertEqual(self.page.material_notes.toPlainText(),'Measured pending note')

    def test_both_interpolated_curves_use_canonical_evaluator_and_keep_exact_raw_samples(self):
        raw_before=self.measured.read_bytes();geometry=copy.deepcopy(self.store.project()['materials'])
        for mode,midpoint in [('linear',.505),('log_k',.1),('linear',.505)]:
            self.page.interpolation.setCurrentIndex(self.page.interpolation.findData(mode))
            main,twin=self.page.plot.figure.axes
            measured=np.array([[1000.,2.,.01],[2000.,4.,1.]])
            for axis,column in ((main,1),(twin,2)):
                np.testing.assert_array_equal(axis.lines[0].get_xdata(),measured[:,0])
                np.testing.assert_array_equal(axis.lines[0].get_ydata(),measured[:,column])
                curve=axis.lines[1]
                x=curve.get_xdata();y=curve.get_ydata()
                expected=sample_nk(dict(model='table_nk',table=measured.tolist(),interpolation=mode),x)[column-1]
                np.testing.assert_array_equal(y,expected)
                for original in measured[:,0]:self.assertIn(original,x)
                self.assertAlmostEqual(y[np.flatnonzero(x==1500)[0]],3. if column==1 else midpoint,places=14)
                record=next(r for r in self.page.plot.canvas.data_records if r.get('source_artist') is curve)
                np.testing.assert_array_equal(record['raw_x'],x);np.testing.assert_array_equal(record['raw_y'],y)
            self.assertEqual(self.page.plot.canvas.unsupported_artists,[])
            self.assertEqual(self.page.values.rowCount(),2)
            self.assertEqual(self.page.values.horizontalHeaderItem(0).text(),'Wavelength (nm)')
        self.assertEqual(self.measured.read_bytes(),raw_before)
        self.assertEqual(self.store.project()['materials'],geometry)
        exported=self.root/'raw.csv'
        with patch('qt_result_export.QFileDialog.getSaveFileName',return_value=(str(exported),'CSV')):self.page.export_constants()
        pd.testing.assert_frame_equal(pd.read_csv(exported),pd.DataFrame({'wavelength_nm':[1000.,2000.],'n':[2.,4.],'k':[.01,1.]}))

    def test_measured_display_range_keeps_full_samples_export_and_restores_on_dataset_switch(self):
        self.assertEqual((self.page.low.value(),self.page.high.value()),(1000.,2000.))
        before=self.optical_inputs();source=self.measured.read_bytes()
        self.page.low.setValue(1200.);self.page.high.setValue(1800.)
        main,twin=self.page.plot.figure.axes
        self.assertEqual(main.get_xlim(),(1200.,1800.))
        self.assertEqual(twin.get_xlim(),(1200.,1800.))
        for axis,expected in ((main,[2.,4.]),(twin,[.01,1.])):
            np.testing.assert_array_equal(axis.lines[0].get_xdata(),[1000.,2000.])
            np.testing.assert_array_equal(axis.lines[0].get_ydata(),expected)
        self.assertEqual(self.page.values.rowCount(),2)
        self.page.selection.setCurrentIndex(self.page.selection.findData('project:Air'))
        self.page.selection.setCurrentIndex(self.page.selection.findData('project:Measured'))
        self.assertEqual((self.page.low.value(),self.page.high.value()),(1200.,1800.))
        self.assertEqual(self.optical_inputs(),before)
        self.assertEqual(self.measured.read_bytes(),source)
        exported=self.root/'range-originals.csv'
        with patch('qt_result_export.QFileDialog.getSaveFileName',return_value=(str(exported),'CSV')):self.page.export_constants()
        self.assertEqual(len(pd.read_csv(exported)),2)
        np.testing.assert_array_equal(pd.read_csv(exported).wavelength_nm,[1000.,2000.])

    def test_saved_log_policy_is_real_on_assignment_and_linear_can_override_saved_default(self):
        self.page.interpolation.setCurrentIndex(self.page.interpolation.findData('log_k'))
        self.page.preset_name.setText('Logarithmic version');self.page.save_selected()
        key,entry=next((key,entry) for key,entry in self.store.library.presets().items() if entry['label']=='Logarithmic version')
        self.assertEqual(entry['project']['settings']['material_interpolations'],{'Measured':'log_k'})
        self.store.update_settings({'material_interpolations':{}})
        self.page.remove_material()
        self.page.selection.setCurrentIndex(self.page.selection.findData('saved:'+key))
        self.assertEqual(self.page.interpolation.currentData(),'log_k')
        before=copy.deepcopy(self.store.project()['materials'])
        self.page.set_material_color('#2468ab')
        self.page.material_notes.setPlainText('Library inspection note');self.page.save_material_notes()
        self.assertEqual(self.store.project()['materials'],before)
        self.page.apply_to_layer()
        self.assertEqual(self.store.settings['material_interpolations']['Measured'],'log_k')
        self.assertIn('Measured',self.store.layers.Material.to_list())
        self.assertEqual(self.store.appearance['material_colors']['Measured'],'#2468ab')
        self.page.selection.setCurrentIndex(self.page.selection.findData('saved:'+key))
        self.page.interpolation.setCurrentIndex(self.page.interpolation.findData('linear'))
        self.assertEqual(self.store.settings['material_interpolations']['Measured'],'linear')
        self.assertEqual(self.page.interpolation.currentData(),'linear')

    def test_zero_k_and_constant_models_cannot_apply_logarithmic_interpolation(self):
        path=self.root/'Zero.csv';path.write_text('wavelength,n,k\n1000,2,0\n2000,4,.01\n')
        self.page.import_paths([str(path)])
        self.assertFalse(self.page.interpolation.model().item(1).isEnabled())
        before=copy.deepcopy(self.store.settings)
        self.page.interpolation.setCurrentIndex(1)
        self.assertEqual(self.store.settings,before)
        self.assertEqual(self.page.interpolation.currentData(),'linear')
        self.assertIn('requires every saved k sample',self.page.status.text())
        self.page.selection.setCurrentIndex(self.page.selection.findData('project:Air'))
        self.assertFalse(self.page.interpolation.isEnabled())
        self.page.interpolation.setCurrentIndex(1)
        self.assertEqual(self.store.settings,before)

    def test_colliding_saved_material_keeps_exact_source_on_add_assignment_and_portable_reopen(self):
        source='Source: Authentic measured collision dataset\nDataset: Original two-sample table'
        selected,_=self.page.selected_row()
        original=copy.deepcopy(next(row for row in self.store.project()['materials'] if row['Name']=='GaAs'))
        row=dict(selected,Name='GaAs')
        key=self.store.library.save_preset(row,'Measured GaAs',notes='Original user note',
            interpolation='log_k',source_notes=source)
        self.store.notify_library()
        self.page.selection.setCurrentIndex(self.page.selection.findData('saved:'+key))
        self.page.set_material_color('#2468ab')
        self.page.material_notes.setPlainText('Edited collision note')
        raw=self.measured.read_bytes()
        self.page.use_preset()
        self.assertEqual(self.page.selection.currentData(),'project:GaAs 2')
        added,_=self.page.selected_row()
        self.assertEqual(added,dict(row,Name='GaAs 2'))
        self.assertEqual(self.page.material_source.text(),source)
        self.assertEqual(self.page.material_notes.toPlainText(),'Edited collision note')
        self.assertEqual(self.store.settings['material_interpolations']['GaAs 2'],'log_k')
        self.assertEqual(self.store.appearance['material_colors']['GaAs 2'],'#2468ab')
        self.assertEqual(next(r for r in self.store.project()['materials'] if r['Name']=='GaAs'),original)
        self.page.selection.setCurrentIndex(self.page.selection.findData('saved:'+key))
        layer=self.page.assignment_layer.currentData()
        self.page.apply_to_layer()
        assigned=self.store.layers.loc[self.store.layers.Name==layer,'Material'].iloc[0]
        self.assertNotEqual(assigned,'GaAs')
        assigned_row=next(r for r in self.page.project_material_rows() if r['Name']==assigned)
        self.assertEqual(assigned_row,dict(row,Name=assigned))
        self.assertEqual(self.store.library.material_metadata(assigned_row)['source_notes'],source)
        self.assertEqual(self.store.settings['material_interpolations'][assigned],'log_k')
        clean=ProjectStore(DataLibrary(self.root/'collision-clean'),restore=False)
        clean.load_project(self.store.portable_project())
        reopened=MaterialsPage(clean)
        for name in ('GaAs 2',assigned):
            reopened.selection.setCurrentIndex(reopened.selection.findData('project:'+name))
            self.assertEqual(reopened.material_source.text(),source)
            self.assertEqual(reopened.material_notes.toPlainText(),'Edited collision note')
            self.assertEqual(reopened.interpolation.currentData(),'log_k')
            self.assertEqual(reopened.material_color.text(),'#2468ab')
        self.assertEqual(next(r for r in clean.project()['materials'] if r['Name']=='GaAs'),original)
        self.assertEqual(self.measured.read_bytes(),raw)
        reopened.close();reopened.deleteLater();APP.processEvents()


if __name__=='__main__':unittest.main()
