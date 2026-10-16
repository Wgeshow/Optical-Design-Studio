"""RTA-only dispatch, exact field selection, and resize scene preservation."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication
from matplotlib.figure import Figure
from data_library import DataLibrary,read_json,write_json
from qt_core import ProjectStore,prepare_job
from qt_compute import SimulationPage
from qt_common import PlotWidget,ThemeManager
from scan_storage import SpectrumResults

APP=QApplication.instance() or QApplication([])


class SpectrumFieldMenuTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.library=DataLibrary(self.temp.name);self.store=ProjectStore(self.library,restore=False)
        self.store.settings.update(NumG=9,wl_start_nm=1049,wl_stop_nm=1051,wl_step_nm=1)
        self.store.performance.update(mode='CPU only',workers=1,threads=1,timeout_seconds=60,chunk_size=1)

    def page(self):
        page=SimulationPage(self.store);self.addCleanup(page.deleteLater);return page

    def saved(self,rows=None):
        project,job=prepare_job('simulation',self.store.portable_project(),{},self.library)
        root=self.library.runs/'menu-spectrum';root.mkdir()
        write_json(root/'project.json',project);write_json(root/'job.json',job)
        self.library.record(root,kind='simulation',title='Spectrum',status='complete')
        data=SpectrumResults(root/'spectrum.sqlite',create=True)
        data.add_batch(rows or [[0,1049,0,.1,.8,.1],[1,1050,0,.8,.1,.1],[2,1051,0,.2,.2,.6]])
        data.export_csv(root/'results.csv');data.close()
        return root

    def test_run_spectrum_never_requests_fields_even_with_legacy_settings(self):
        page=self.page()
        with patch.object(page,'_start') as start:page.run()
        self.assertEqual(start.call_args.args[0],'simulation')
        self.assertNotIn('electric_fields',start.call_args.args[1])
        _,job=prepare_job('simulation',self.store.portable_project(),dict(electric_fields={'grid':999999}),self.library)
        self.assertNotIn('simulation_fields',job)
        self.assertIsNone(job['search'])

    def test_samples_and_depth_caps_removed_in_both_menus_and_validation(self):
        from qt_compute import FieldsPage
        from field_solver import validate_field_settings
        from simulation_fields import validate_settings
        from qt_core import desktop_search
        page=self.page();page.field_controls['grid'].setValue(770);page.field_controls['depth_samples'].setValue(250)
        self.assertEqual(page.field_options()['grid'],770)
        self.assertEqual(page.field_options()['depth_samples'],250)
        fields=FieldsPage(self.store);self.addCleanup(fields.deleteLater)
        fields.grid.setValue(770);fields.depth.setValue(250)
        self.assertEqual(fields.options()['grid'],770)
        self.assertEqual(fields.options()['depth_samples'],250)
        cfg=dict(grid=770,depth_samples=250,wavelength_nm=1050)
        validate_field_settings(cfg)
        self.assertEqual(validate_settings(cfg)['grid'],770)
        self.assertEqual(desktop_search({'fields':cfg})['fields']['depth_samples'],250)
        _,job=prepare_job('fields',self.store.portable_project(),cfg,self.library)
        self.assertEqual(job['search']['grid'],770)
        self.assertEqual(job['search']['depth_samples'],250)

    def test_separate_manual_job_keeps_sweep_settings_and_full_sampling(self):
        project=self.store.portable_project();before=copy.deepcopy(project)
        _,job=prepare_job('simulation_fields',project,dict(wavelength_nm=1050,electric_fields=dict(grid=3,depth_samples=3)),self.library)
        self.assertEqual(project,before)
        self.assertEqual(job['search']['field_points'],[[0,1050,0]])
        self.assertEqual(job['search']['field_settings']['depth_samples'],3)
        self.assertIsNone(job.get('simulation_fields'))

    def test_all_six_extrema_use_exact_saved_samples(self):
        root=self.saved()
        expected={'maxR':1050,'minR':1049,'maxT':1049,'minT':1050,'maxA':1051,'minA':1049}
        page=self.page();page.directory=root;page.load_spectrum()
        for source,wave in expected.items():
            with self.subTest(source=source):
                page.field_source.setCurrentIndex(page.field_source.findData(source))
                self.assertTrue(page.field_run.isEnabled(),page.field_selection.text())
                self.assertEqual(page.field_wavelength.value(),wave)
                _,job=prepare_job('simulation_fields',self.store.portable_project(),dict(wavelength_source=source,spectrum_id=root.name),self.library)
                self.assertEqual(job['search']['field_points'][0][1],wave)
                self.assertEqual(list(job['model']['points']),job['search']['field_points'])

    def test_extrema_exclude_nonfinite_samples_and_keep_first_tie_for_old_indexes(self):
        rows=[[0,1049,0,float('inf'),0,0],[1,1050,0,.8,.1,.1],[2,1051,0,.8,.1,.1]]
        root=self.saved(rows)
        data=SpectrumResults(root/'spectrum.sqlite',create=False)
        self.assertEqual(data.extremum('R')[0],1)
        import sqlite3
        connection=sqlite3.connect(data.path)
        with connection:connection.execute("DELETE FROM metadata WHERE key IN ('peaks','minima')")
        connection.close()
        self.assertEqual(data.extremum('R',False)[0],1)
        data.close()

    def test_entire_spectrum_is_an_explicit_field_job_and_rejects_stale_geometry(self):
        root=self.saved();options=dict(single_wavelength=False,spectrum_id=root.name)
        _,job=prepare_job('simulation_fields',self.store.portable_project(),options,self.library)
        self.assertEqual(job['search']['selection']['samples'],3)
        self.assertNotIn('field_points',job['search'])
        project=self.store.portable_project();project['layers'][1]['Thickness_um']+=.1
        with self.assertRaisesRegex(ValueError,'setup has changed'):prepare_job('simulation_fields',project,options,self.library)

    def test_resize_updates_layout_without_rebuilding_scenes_or_stylesheet(self):
        manager=ThemeManager()
        with patch.object(manager,'apply') as apply:
            for width in range(800,1921,17):manager.set_window_width(width)
        apply.assert_not_called()
        page=self.page();figure=Figure();axis=figure.add_subplot(111);axis.plot(np.arange(30001),np.sin(np.arange(30001)))
        page.phase_plot.draw_figure(figure);canvas=page.phase_plot.canvas
        record=next(record for record in canvas.data_records if record['kind']=='line')
        item=record['native_item'];before=item.getData()[1].copy()
        canvas.show();APP.processEvents();canvas.hide();APP.processEvents()
        self.assertTrue(item.opts['autoDownsample'])
        self.assertTrue(item.opts['clipToView'])
        np.testing.assert_array_equal(item.getData()[1],before)


class NativeSeparateFieldWorkflowTests(unittest.TestCase):
    setUp=SpectrumFieldMenuTests.setUp
    def run_job(self,kind,options,folder):
        project,job=prepare_job(kind,self.store.portable_project(),options,self.library)
        root=self.library.runs/folder;root.mkdir()
        write_json(root/'project.json',project);write_json(root/'job.json',job)
        result=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'backend.py'),'--job',str(root/'job.json')],capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        event=[json.loads(line) for line in result.stdout.splitlines()][-1]
        self.library.record(root,kind='simulation' if kind=='simulation' else 'optimization',title=kind,status='complete')
        return root,event

    def test_real_spectrum_then_manual_extremum_and_all_fields(self):
        root,event=self.run_job('simulation',{},'native-spectrum')
        self.assertFalse((root/'fields').exists())
        self.assertNotIn('electric_fields',event['info'])
        reference_root=self.library.runs/'reference';reference_root.mkdir()
        spec=read_json(root/'job.json');spec['simulation_fields']=dict(grid=3,depth_samples=3,contour_step=.1)
        write_json(reference_root/'job.json',spec)
        result=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'backend.py'),'--job',str(reference_root/'job.json')],capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        spectrum=pd.read_csv(root/'results.csv');reference=pd.read_csv(reference_root/'results.csv')
        np.testing.assert_allclose(spectrum[['R','T','A']],reference[['R','T','A']],atol=1e-12,rtol=0)
        for name,options,count in [('manual',dict(wavelength_nm=1050),1),('extremum',dict(wavelength_source='maxA',spectrum_id=root.name),1),('all',dict(single_wavelength=False,spectrum_id=root.name),3)]:
            path,fields=self.run_job('simulation_fields',dict(options,electric_fields=dict(grid=3,depth_samples=3)),'native-fields-'+name)
            self.assertFalse((path/'results.csv').exists())
            self.assertEqual(fields['summary']['electric_fields']['samples'],count)
            manifest=read_json(path/'fields/samples.json')
            self.assertEqual(manifest['count'],count)
            with np.load(path/'fields/electric_fields.npz',allow_pickle=False) as data:
                self.assertIn('E',data.files);self.assertIn('H',data.files)
                self.assertTrue(np.isfinite(data['E']).all());self.assertTrue(np.isfinite(data['H']).all())
            if name=='all':
                for folder in ['', 'samples/000002','samples/000003']:
                    with np.load(path/'fields'/folder/'electric_fields.npz') as actual,np.load(reference_root/'fields'/folder/'electric_fields.npz') as expected:
                        for key in ('E','H'):np.testing.assert_allclose(actual[key],expected[key],atol=1e-10,rtol=1e-10)


if __name__=='__main__':unittest.main()
