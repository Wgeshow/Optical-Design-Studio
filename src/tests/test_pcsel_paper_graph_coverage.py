"""Graph/parameter contracts; synthetic arrays below are UI tests, not paper data."""
import copy
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PyQt6.QtCore import QCoreApplication,QEvent
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel_research_setup import PcselResearchWorkspace
from qt_pcsel_paper import PcselPaperResults,saved_paper_figure
from research_catalog import list_capabilities
from pcsel_paper_studies import king2024_example,design_metrics,figure_manifest

APP=QApplication.instance() or QApplication([])
for font in ('segoeui.ttf','segoeuib.ttf','segoeuii.ttf'):
    path=Path('C:/Windows/Fonts')/font
    if path.is_file():QFontDatabase.addApplicationFont(str(path))

class GraphCoverageTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='paper-graphs-',dir=os.environ.get('ODS_TEST_TMPDIR'))
  self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
 def csv(self,name,headers,rows):
  with (self.root/name).open('w',newline='',encoding='utf-8') as f:
   w=csv.writer(f);w.writerow(headers);w.writerows(rows)
 def test_sorted_band_discrimination_is_not_clipped_A_gap(self):
  metrics=design_metrics({'coupled_modes':[dict(power_loss_cm1=g) for g in (10.,5.,20.,30.)]})
  self.assertEqual(metrics['delta_g_A_cm1'],0.)
  self.assertEqual(metrics['delta_g_band_cm1'],5.)
  self.assertEqual(metrics['lowest_band_loss_cm1'],5.)
  self.assertEqual(metrics['second_band_loss_cm1'],10.)
  spec=next(x for x in figure_manifest(king2024_example('fig5'),{})['plots'] if x['id']=='delta_g_band_cm1')
  self.assertIn('5(b)',spec['title']);self.assertEqual(spec['y'],'delta_g_band_cm1')
 def test_focused_scan_axes_and_missing_noDBR_input(self):
  cfg=king2024_example('fig4d');axes=cfg['parameter_sweep']['parameters']
  self.assertEqual((min(axes[0]['values']),max(axes[0]['values'])),(68.,75.))
  self.assertEqual((min(axes[1]['values']),max(axes[1]['values'])),(.65,.775))
  self.assertIsNone(next(row['thickness_nm'] for row in cfg['layers'] if row['id']=='p-cladding'))
  self.assertIn('inferred',' '.join(cfg['paper_study']['assumptions']))
  spec=figure_manifest(cfg,{})['plots'][0]
  self.assertEqual(spec['x'],'shapes.triangle.base_angle_deg')
  self.assertEqual(spec['y'],'shapes.triangle.base_length')
  self.assertEqual(spec['value'],'kappa_1d_direct_abs_cm1')
 def test_variant_domain_and_shared_geometry_are_explicit(self):
  cfg=king2024_example('fig9');sweep=cfg['parameter_sweep']
  self.assertEqual((min(sweep['parameters'][0]['values']),max(sweep['parameters'][0]['values'])),(100.,5000.))
  self.assertEqual([v['name'] for v in sweep['variants']],['Original structure','Weakened grating'])
  self.assertEqual([[r['value'] for r in v['overrides']] for v in sweep['variants']],[[150.,50.],[100.,300.]])
  plotted=next(s for s in figure_manifest(cfg,{})['plots'] if s['id']=='lowest_loss_cm1')
  self.assertEqual(plotted['series'],'variant')
  plots=figure_manifest(cfg,{})['plots']
  self.assertEqual([p['id'] for p in plots[:2]],['lowest_loss_cm1','delta_g_cm1'])
  self.assertNotIn('modes',[p['id'] for p in plots])
  cfg['parameter_sweep'].pop('variants')
  restored=figure_manifest(cfg,dict(cases=[dict(variant='Edited structure')]))['plots']
  self.assertEqual(restored[0]['series'],'variant')
  self.assertNotIn('modes',[p['id'] for p in restored])
 def test_combined_vertical_curve_transforms_units_not_values_to_paper(self):
  self.csv('vertical_profile.csv',['z_nm','index','intensity_per_nm'],[[0,3.,.002],[1000,3.5,.001]])
  cfg=king2024_example('fig2');spec=figure_manifest(cfg,dict(artifacts=['vertical_profile.csv']))['plots'][0]
  fig=saved_paper_figure(self.root,spec);self.assertEqual(len(fig.axes),2)
  height=sum(l['thickness_nm'] for l in cfg['layers'])/1000
  np.testing.assert_allclose(fig.axes[0].lines[0].get_xdata(),[height-1,height])
  np.testing.assert_array_equal(fig.axes[1].lines[0].get_ydata(),[1.,2.])
  self.assertIn('µm^-1',fig.axes[1].get_ylabel())
 def test_multiline_efficiencies_and_composite_variant_mode_groups(self):
  self.csv('values.csv',['L','substrate','edge','variant','label','status'],[[1,.6,.4,'A','A','complete'],[2,.8,.2,'A','A','complete'],[1,.4,.6,'B','A','complete'],[2,.7,.3,'B','A','failed']])
  spec=dict(kind='multi_line',curves=[dict(csv='values.csv',x='L',y=key,label=key,series='variant') for key in ('substrate','edge')])
  fig=saved_paper_figure(self.root,spec);self.assertEqual(len(fig.axes[0].lines),4)
  self.assertTrue(np.isnan(fig.axes[0].lines[1].get_ydata()[-1]))
  fig=saved_paper_figure(self.root,dict(kind='line',csv='values.csv',x='L',y='substrate',series=['variant','label']))
  self.assertEqual([l.get_label() for l in fig.axes[0].lines],['A · A','B · A'])
 def test_reference_overlay_is_opt_in_and_never_changes_saved_curve(self):
  self.csv('values.csv',['x','g'],[[1,3],[2,4]])
  spec=dict(kind='line',csv='values.csv',x='x',y='g',reference_lines=[dict(role='published_reference',value=8.7,label='Published no-DBR')])
  before=(self.root/'values.csv').read_bytes()
  computed=saved_paper_figure(self.root,spec);shown=saved_paper_figure(self.root,spec,show_references=True)
  self.assertEqual(len(computed.axes[0].lines),1);self.assertEqual(len(shown.axes[0].lines),2)
  np.testing.assert_array_equal(computed.axes[0].lines[0].get_ydata(),shown.axes[0].lines[0].get_ydata())
  self.assertIn('REFERENCE ONLY',shown.axes[0].lines[1].get_label())
  self.assertEqual(before,(self.root/'values.csv').read_bytes())
 def test_far_angles_are_degrees_without_intensity_resampling(self):
  x=np.array([-.01,0,.01]);y=np.array([-.02,0,.02]);values=np.arange(9.).reshape(3,3)
  np.savez(self.root/'field.npz',far_display=values,sin_theta_x=x,sin_theta_y=y)
  before=(self.root/'field.npz').read_bytes()
  spec=dict(kind='field_grid',npz='field.npz',array='far_display',x='sin_theta_x',y='sin_theta_y',x_transform='arcsin_degrees',y_transform='arcsin_degrees',x_label='θx (degrees)',y_label='θy (degrees)')
  fig=saved_paper_figure(self.root,spec);mesh=fig.axes[0].collections[0]
  np.testing.assert_array_equal(mesh.get_array(),values)
  coords=mesh.get_coordinates();self.assertAlmostEqual(coords[0,0,0],np.rad2deg(np.arcsin(-.01))*1.5)
  self.assertAlmostEqual(coords[0,0,1],np.rad2deg(np.arcsin(-.02))*1.5)
  self.assertEqual(before,(self.root/'field.npz').read_bytes())
 def test_case_insets_use_saved_accepted_mode_indices(self):
  modes=[dict(mode=0,total_loss_cm1=.1,accepted=False),dict(mode=1,total_loss_cm1=5.,accepted=True),dict(mode=2,total_loss_cm1=3.,accepted=True)]
  summary=dict(cases=[dict(directory='case-0002',variant='Original structure',parameters={'aperture_um.side':1500.},summary=dict(artifacts=['finite_fields.npz'],finite_modes=modes,emitted_near_field_available=True))])
  specs=[x for x in figure_manifest(king2024_example('fig6'),summary)['plots'] if x['kind']=='field_grid']
  self.assertEqual([x['mode_index'] for x in specs],[2,1]);self.assertTrue(all(x['npz']=='case-0002/finite_fields.npz' for x in specs))
  self.assertTrue(all(x['array']=='emitted_near_intensity' for x in specs))
 def test_saved_geometry_changes_with_input_without_field_simulation(self):
  cfg=king2024_example('fig2');(self.root/'pcsel_inputs.json').write_text(json.dumps(cfg))
  spec=dict(kind='device_schematic',json='pcsel_inputs.json',view='cell')
  first=saved_paper_figure(self.root,spec);old=first.axes[0].patches[5].get_xy().copy()
  cfg['shapes'][0]['base_angle_deg']=60;(self.root/'pcsel_inputs.json').write_text(json.dumps(cfg))
  changed=saved_paper_figure(self.root,spec)
  self.assertFalse(np.allclose(old,changed.axes[0].patches[5].get_xy()))
  self.assertTrue(changed.axes[0]._ods_input_schematic)
 def test_multi_source_export_is_exact_zip(self):
  self.csv('one.csv',['x','y'],[[1,2],[2,3]]);self.csv('two.csv',['x','y'],[[1,4],[2,5]])
  spec=dict(kind='multi_line',curves=[dict(csv=file,x='x',y='y') for file in ('one.csv','two.csv')])
  (self.root/'pcsel_paper_figures.json').write_text(json.dumps(dict(schema_version=1,plots=[spec])))
  panel=PcselPaperResults()
  try:
   self.assertTrue(panel.load_directory(self.root))
   with patch('qt_pcsel_paper.QFileDialog.getSaveFileName',return_value=(str(self.root/'export.zip'),'')):panel.export_source()
   with zipfile.ZipFile(self.root/'export.zip') as archive:
    for file in ('one.csv','two.csv'):self.assertEqual(archive.read(file),(self.root/file).read_bytes())
  finally:
   from PyQt6 import sip
   sip.delete(panel)
 def test_variant_editor_roundtrip_edit_draft_and_independent_device(self):
  store=ProjectStore(DataLibrary(self.root/'library'),restore=False);store.study_navigation_enabled=True;store.activate_study('pcsel.finite')
  cap=next(x for x in list_capabilities() if x['engine']=='pcsel')
  page=PcselResearchWorkspace(store,cap,document_id='pcsel.finite');page.bind_study_document('pcsel.finite')
  original=copy.deepcopy(store.device)
  try:
   page.load_settings(king2024_example('fig9',model='finite'));editor=page.structured['parameter_sweep']
   self.assertEqual(editor.variant_table.rowCount(),4)
   self.assertEqual([v['name'] for v in editor.value()['variants']],['Original structure','Weakened grating'])
   editor.variant_table.item(2,4).setText('110.5')
   self.assertEqual(editor.value()['variants'][1]['overrides'][0]['value'],110.5)
   editor.variant_table.item(2,4).setText('1e-');draft=editor.draft()
   with self.assertRaises(ValueError):editor.value()
   editor.set_value({});editor.restore_draft(draft)
   self.assertEqual(editor.variant_table.item(2,4).text(),'1e-');self.assertEqual(store.device,original)
  finally:
   if hasattr(page,'_save_timer'):page._save_timer.stop()
   page.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

if __name__=='__main__':unittest.main()
