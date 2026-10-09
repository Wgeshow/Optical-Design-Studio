import os,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary,read_json
from qt_core import ProjectStore,prepare_job
from qt_ai_search import AISearchPage
from qt_app import OpticalStudio

class UI(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=ProjectStore(DataLibrary(self.tmp.name),restore=False);self.page=AISearchPage(self.store)
 def tearDown(self):self.page.deleteLater();self.app.processEvents();self.tmp.cleanup()
 def test_ranges_plan_and_persistence(self):
  self.page.default_ranges();self.assertTrue(self.page.bounds.records())
  self.page.preview();self.assertIn('Range grid:',self.page.plan_label.text())
  saved=self.store.project()['desktop_search']['ai_search'];self.assertEqual(saved['contour_step'],.1)
  self.store.load_project(self.store.project());self.assertEqual(self.page.bounds.records(),saved['bounds'])
 def test_app_has_independent_ai_tab_without_reassigning_old_routes(self):
  window=OpticalStudio(self.store)
  labels=[window.optical_workflow.tabText(i) for i in range(window.optical_workflow.count())]
  self.assertIn('AI Search',labels);window._navigate_route(8)
  self.assertIsInstance(window.pages['AI Search'],AISearchPage)
  self.assertEqual(window.pages['Settings'],window.pages[window.navigation.item(6).text()])
  window.close();window.deleteLater();self.app.processEvents()
 def test_full_scan_preview_rejects_over_budget(self):
  self.page.default_ranges();self.page.controls['mode'].setCurrentText('Full range scan');self.page.controls['new_budget'].setText('1');self.page.preview()
  self.assertIn('exceeding',self.page.plan_label.text())

 def test_counts_have_no_artificial_maximum(self):
  from ai_campaign import validate_options
  self.page.controls['initial'].setText('3000000000')
  self.page.controls['test_count'].setText('20000')
  self.page.controls['new_budget'].setText('0')
  cfg=validate_options(self.page.options())
  self.assertEqual(cfg['initial'],3000000000)
  self.assertEqual(cfg['test_count'],20000)
  self.page.default_ranges();self.page.preview()
  self.assertIn('No simulation limit',self.page.plan_label.text())
  self.page.save();self.page.restore('project')
  self.assertEqual(self.page.controls['new_budget'].text(),'0')

 def test_ai_and_simulation_settings_are_independent(self):
  from qt_compute import SimulationPage
  from copy import deepcopy
  simulation=SimulationPage(self.store)
  self.page.default_ranges()
  ai_before=deepcopy(self.page.options())
  self.store.update_settings(dict(polarization='s',theta_deg=35.,phi_deg=70.,NumG=91,wl_start_nm=1000.,wl_stop_nm=1200.))
  self.assertEqual(self.page.options(),ai_before)
  _,job=prepare_job('ai_search',self.store.portable_project(),self.page.options(),self.store.library)
  self.assertEqual(job['model']['polarization'],'p')
  self.assertEqual(job['model']['basis'],32)
  self.assertEqual(job['model']['points'][0][2],0.)
  settings=deepcopy(self.store.settings)
  simulation.controls['wl_start_nm'].setValue(1100.)
  self.page.controls['theta_deg'].setValue(12.)
  self.page.save()
  self.assertEqual(simulation.controls['wl_start_nm'].value(),1100.)
  self.assertEqual(self.store.settings,settings)
  simulation.deleteLater()

 def test_simulation_contains_fields_and_saved_data(self):
  window=OpticalStudio(self.store)
  top=[window.optical_workflow.tabText(i) for i in range(window.optical_workflow.count())]
  self.assertNotIn('Optical Fields',top);self.assertNotIn('Saved Results',top)
  tabs=[window.simulation_engines.tabText(i) for i in range(window.simulation_engines.count())]
  self.assertIn('Fields',tabs);self.assertIn('Saved results',tabs)
  for route,label in ((4,'Fields'),(5,'Saved results')):
   window._navigate_route(route)
   self.assertEqual(window.stack.currentIndex(),2)
   self.assertEqual(window.simulation_engines.tabText(window.simulation_engines.currentIndex()),label)
   self.assertEqual(window.optical_workflow.tabText(window.optical_workflow.currentIndex()),'Simulation')
  window._navigate_route(8)
  self.assertEqual(window.stack.currentIndex(),8)
  window.close();window.deleteLater();self.app.processEvents()

 def test_3d_view_follows_design_and_clears_missing_data(self):
  from test_field_tracking_ui import sample
  from unittest.mock import patch
  from matplotlib.figure import Figure
  first=self.store.library.runs/'campaign'/'designs'/'1'/'fields'
  second=self.store.library.runs/'campaign'/'designs'/'2'/'fields'
  model=sample(first,scale=1.)
  sample(second,scale=4.)
  constraints=dict(volume_rms_contrast=1.,xz_rms_contrast=1.,volume_coverage=.5,xz_coverage=.5)
  self.page.records=[dict(model=model,phase='train',field_directory=str(path),fields=dict(feasible=False,constraints=constraints)) for path in (first,second)]
  with patch('qt_ai_search.field_figure',return_value=Figure()),patch('qt_ai_search.line_figure',return_value=Figure()),patch('qt_ai_search.rta_figure',return_value=Figure()):
   self.page.refresh_designs()
   viewer=self.page.volume_view
   self.assertIsNone(viewer.data) # Load the volume only when requested.
   self.page.result_tabs.setCurrentWidget(viewer)
   self.assertIsNotNone(viewer.data,viewer.status.text())
   self.assertEqual(viewer.directory,second.resolve())
   peak=float(abs(viewer.data[3]['E']).max())
   viewer.mode.setCurrentText('Ex')
   viewer.show_arrows.setChecked(True)
   viewer.phase.setValue(90)
   self.assertIsNotNone(viewer.arrow)
   self.page.designs.setCurrentIndex(0)
   self.assertEqual(viewer.directory,first.resolve())
   self.assertAlmostEqual(float(abs(viewer.data[3]['E']).max())*2,peak)
   self.page.records[0]['field_directory']=str(first.parent/'missing')
   self.page.inspect()
   self.assertIsNone(viewer.data)
   self.assertFalse(viewer.play.isEnabled())
