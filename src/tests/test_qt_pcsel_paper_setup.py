"""Paper inputs remain editable, independent and incomplete when source is incomplete."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QCoreApplication,QEvent,Qt
from PyQt6.QtWidgets import QApplication,QLineEdit
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_pcsel_research_setup import PcselResearchWorkspace,pcsel_preview_device
from research_catalog import list_capabilities
from pcsel_paper_studies import king2024_example,triangle_vertices

class PaperSetupTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='paper-setup-ui-',dir=os.environ.get('ODS_TEST_TMPDIR'))
  self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
  self.store.study_navigation_enabled=True;self.pages=[]
 def tearDown(self):
  for p in self.pages:
   if hasattr(p,'_save_timer'):p._save_timer.stop()
   p.deleteLater()
  QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
  self.temp.cleanup()
 def page(self,model):
  target='pcsel.'+model;self.store.activate_study(target)
  cap=next(x for x in list_capabilities() if x['engine']=='pcsel')
  p=PcselResearchWorkspace(self.store,cap,document_id=target);p.bind_study_document(target);self.pages.append(p)
  return p
 def test_missing_published_thickness_is_blank_numeric_and_blocks_request(self):
  p=self.page('cwt')
  # First establish a valid geometry, then prove incomplete import cannot show it.
  p.load_settings(king2024_example('fig5',model='cwt'))
  self.assertIsNotNone(p.geometry_editor.preview.last_geometry)
  p.paper_setup.figure.setCurrentIndex(p.paper_setup.figure.findData('fig3'))
  device=copy.deepcopy(self.store.device)
  self.assertTrue(p.paper_setup.load_example())
  self.assertEqual(p.fields['model'].currentData(),'cwt');self.assertEqual(self.store.device,device)
  self.assertIsNone(p.geometry_editor.preview.last_geometry)
  self.assertIn('Missing published input',p.status.text())
  root=p.structured['layers'].tree.topLevelItem(0)
  found=None
  for i in range(root.childCount()):
   row=root.child(i)
   identity=next((row.child(j).text(1) for j in range(row.childCount()) if row.child(j).text(0)=='id'),'')
   if identity=='p-cladding':
    found=i
    item=next(row.child(j) for j in range(row.childCount()) if row.child(j).text(0)=='thickness_nm')
    self.assertEqual(item.data(0,Qt.ItemDataRole.UserRole),'number');self.assertEqual(item.text(1),'')
  self.assertIsNotNone(found)
  with self.assertRaises(ValueError):p.options()
  p.resize(1200,800);p.show();self.app.processEvents()
  self.assertTrue(p.open_diagnostic(dict(field=f'layers.{found}.thickness_nm')))
  control=p.geometry_editor.form.controls['thickness_nm']
  self.assertIsInstance(control,QLineEdit);self.assertEqual(control.text(),'')
  # Deliberately synthetic value only tests editing; it is not paper data.
  control.setText('1234.56789')
  self.assertEqual(p.options()['settings']['layers'][found]['thickness_nm'],1234.56789)
 def test_recipe_filter_and_loaded_finite_setup_preserve_document(self):
  p=self.page('finite');selection=p.paper_setup.figure
  self.assertEqual([selection.itemData(i) for i in range(selection.count())],['fig6','fig7','fig8','fig9'])
  selection.setCurrentIndex(selection.findData('fig8'))
  self.assertTrue(p.paper_setup.load_example())
  settings=p.options()['settings']
  self.assertEqual(settings['model'],'finite');self.assertEqual(self.store.active_study,'pcsel.finite')
  self.assertEqual(settings['aperture_um'],[2000.,2000.])
  self.assertEqual(settings['shapes'][0]['shape'],'triangle')
  self.assertEqual(settings['paper_study']['figure'],'fig8')
  self.assertTrue({'vertical_boundary','vertical_mode_selection','vertical_mode_candidates'}.issubset({r[0] for r in p.journey_review_fields()}))
 def test_triangle_preview_recomputes_vertices_from_parameters(self):
  cfg=king2024_example('fig5');shape=copy.deepcopy(cfg['shapes'][0]);shape['vertices']=[[999,999]]*3
  device,_=pcsel_preview_device(cfg['layers'],[shape],[320.,320.])
  self.assertEqual(device['shapes'][0]['shape'],'polygon')
  expected=[[x*.32,y*.32] for x,y in triangle_vertices(shape)]
  self.assertEqual(device['shapes'][0]['vertices'],expected)
  shape['base_angle_deg']=60
  changed,_=pcsel_preview_device(cfg['layers'],[shape],[320.,320.])
  self.assertNotEqual(changed['shapes'][0]['vertices'],device['shapes'][0]['vertices'])
 def test_sweep_has_triangle_square_targets_and_preserves_incomplete_budget(self):
  p=self.page('finite');p.load_settings(king2024_example('fig8',model='finite'))
  editor=p.structured['parameter_sweep'];editor.refresh_targets()
  targets=[editor.targets.itemData(i) for i in range(editor.targets.count())]
  self.assertIn(dict(path='aperture_um',field='side'),targets)
  self.assertIn(dict(path='shapes',object_id='triangle',field='base_angle_deg'),targets)
  value=dict(parameters=[dict(path='aperture_um',field='side',values=[1000.,2000.])])
  editor.set_value(value);self.assertEqual(editor.value(),value)
  editor.max_cases.setText('1e-');draft=editor.draft()
  with self.assertRaises(ValueError):editor.value()
  editor.set_value({});editor.restore_draft(draft)
  self.assertEqual(editor.max_cases.text(),'1e-')
  editor.max_cases.setText('256');editor.invalid_geometry.setCurrentIndex(editor.invalid_geometry.findData('mask'))
  self.assertEqual(editor.value()['invalid_geometry'],'mask');self.assertEqual(editor.value()['max_cases'],256)

 def test_reference_method_is_explicit_and_preserves_requested_period(self):
  p=self.page('cwt');selector=p.paper_setup.figure
  selector.setCurrentIndex(selector.findData('fig5'))
  self.assertEqual(p.paper_setup.formulation.currentData(),'fixed_period')
  self.assertTrue(p.paper_setup.load_example())
  self.assertEqual(p.options()['settings']['vertical_formulation'],'fixed_period')
  p.paper_setup.formulation.setCurrentIndex(p.paper_setup.formulation.findData('reference_wavelength'))
  self.assertTrue(p.paper_setup.load_example())
  settings=p.options()['settings']
  self.assertEqual(settings['vertical_formulation'],'reference_wavelength')
  self.assertEqual(settings['reference_wavelength_nm'],1070.)
  self.assertEqual(settings['lattice_nm'],320.)
  self.assertEqual(settings['vertical_mode_selection'],'core_overlap')
  self.assertEqual(p.fields['vertical_boundary'].currentText(),'Finite stack; zero field at boundaries')
  self.assertEqual(p.fields['radiation_boundary'].currentText(),'Supplied external interfaces')
  self.assertEqual(p.fields['green_model'].currentText(),'Layer-resolved radiation')
  self.assertEqual(settings['vertical_boundary'],'finite_stack_dirichlet')
  rows=p.journey_review_fields()
  self.assertEqual(next(row[1] for row in rows if row[0]=='lattice_nm'),'Requested lattice period (nm)')
  self.assertIn('Derived after',next(row[2] for row in rows if row[1]=='Calculated lattice period'))
 def test_hidden_method_drafts_remain_but_do_not_block_inactive_method(self):
  p=self.page('cwt');p.load_settings(king2024_example('fig5',model='cwt',formulation='reference_wavelength'))
  p.fields['reference_wavelength_nm'].setText('1e-')
  with self.assertRaises(ValueError):p.options()
  p.fields['vertical_formulation'].setCurrentIndex(p.fields['vertical_formulation'].findData('fixed_period'))
  self.assertEqual(p.options()['settings']['vertical_formulation'],'fixed_period')
  self.assertEqual(p.fields['reference_wavelength_nm'].text(),'1e-')
  p.fields['vertical_mode_selection'].setCurrentIndex(p.fields['vertical_mode_selection'].findData('mode_index'))
  p.fields['vertical_mode_index'].setText('2e')
  with self.assertRaises(ValueError):p.options()
  p.fields['vertical_mode_selection'].setCurrentIndex(p.fields['vertical_mode_selection'].findData('lowest_frequency'))
  self.assertEqual(p.options()['settings']['vertical_mode_selection'],'lowest_frequency')
  self.assertEqual(p.fields['vertical_mode_index'].text(),'2e')

if __name__=='__main__':unittest.main()
