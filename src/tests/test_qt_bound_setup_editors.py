"""Dedicated editors cannot expose or mutate another simulation's setup."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace
from qt_photonic_bands import PhotonicBandsWorkspace

APP=QApplication.instance() or QApplication([])


class BoundSetupEditorsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ods-bound-ui-',dir=Path(__file__).resolve().parents[3])
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        self.store.study_navigation_enabled=True
        self.pages=[]

    def tearDown(self):
        for page in self.pages:
            page.hide();page.deleteLater()
        APP.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def setup_page(self,identity):
        self.store.activate_study(identity)
        page=SimulationSetupWorkspace(self.store,mode='electrical',document_id=identity)
        self.pages.append(page)
        page.resize(1440,900);page.show();APP.processEvents()
        return page

    def test_electrical_context_hides_family_switching_and_preserves_section(self):
        page=self.setup_page('electrical.iv')
        page.select_section('electrical.study')
        page.state.set('ui.electrical.study','iv')
        self.assertTrue(page.mode_bar.isHidden())
        self.assertEqual(page.title.text(),'Current–voltage sweep')
        self.assertFalse(any(editor.isVisible() for editor in page.widgets_by_key['ui.electrical.study']))
        page.select_section('optical.overview')
        self.assertEqual(page.current_mode,'electrical')
        self.assertEqual(page.current_section,'electrical.study')
        self.assertTrue(page.widgets_by_key['device.mesh.nx'][0].isEnabled())

    def test_hidden_electrical_editor_cannot_commit_into_other_variant(self):
        iv=self.setup_page('electrical.iv')
        iv.state.set('device.mesh.nx',14)
        iv.flush_draft();iv.hide()
        cv=self.setup_page('electrical.cv')
        cv.state.set('device.mesh.nx',22)
        field=next(field for field in iv.fields if field.key=='device.mesh.nx')
        # Reproduce a late edit/focus callback from an editor that just closed.
        field.editor.setText('99')
        field.editor.editingFinished.emit()
        iv.flush_draft()
        self.assertEqual(self.store.device['mesh']['nx'],22)
        self.assertFalse(iv.validate_current())
        self.store.activate_study('electrical.iv')
        self.assertEqual(self.store.device['mesh']['nx'],14)
        self.assertEqual(field.editor.text(),'14')

    def test_hidden_table_callbacks_cannot_change_other_variant_device_or_selection(self):
        iv=self.setup_page('electrical.iv')
        table=iv.tables_by_key['device.layers'][0]
        table.item(0,4).setText('123')
        enabled=table.cellWidget(0,0)
        iv.flush_draft();iv.hide()
        cv=self.setup_page('electrical.cv')
        other_material=next(material['id'] for material in self.store.electrical_materials
            if material['id']!=table._rows[0]['material_id'])
        cv.state.set('ui.electrical.selected_material_id',other_material)
        device=copy.deepcopy(self.store.device)
        search=copy.deepcopy(self.store.search_state)
        drafts=copy.deepcopy(iv.table_drafts)
        # These signals may arrive after hiding the old cell editor during a switch.
        table.item(0,4).setText('456789')
        enabled.setChecked(False)
        table._select(0)
        self.assertEqual(self.store.device,device)
        self.assertEqual(self.store.search_state,search)
        self.assertEqual(iv.table_drafts,drafts)
        self.store.activate_study('electrical.iv')
        self.assertEqual(self.store.device['layers'][0]['donor_cm3'],123.)
        self.assertTrue(self.store.device['layers'][0]['enabled'])

    def test_coupled_nested_setup_stays_coupled_and_standalone_requests_host_route(self):
        self.store.activate_study('coupled')
        page=SimulationSetupWorkspace(self.store,mode='coupled',document_id='coupled')
        self.pages.append(page)
        routes=QSignalSpy(page.routeRequested)
        page.perform_action(dict(id='nested',target='coupled.optical-setup/optical.sweep'))
        self.assertEqual(page.current_mode,'coupled')
        self.assertEqual(page.current_section,'optical.sweep')
        self.assertEqual(len(routes),0)
        action=next(action for tab in page._modes['coupled']['tabs'] for card in tab.get('cards',[])
            for action in card.get('actions',[]) if action['id']=='coupled.output-standalone')
        before=copy.deepcopy(self.store.project())
        page.perform_action(action)
        self.assertEqual(list(routes),[['optical.outputs']])
        self.assertEqual(page.current_mode,'coupled')
        self.assertEqual(page.current_section,'optical.sweep')
        self.assertEqual(self.store.project(),before)
        self.assertEqual(action['label'],'Open standalone optical simulation')

    def test_band_variant_instances_keep_inputs_and_diagnostics_separate(self):
        self.store.activate_study('photonic_bands')
        first=PhotonicBandsWorkspace(self.store,document_id='photonic_bands')
        self.pages.append(first)
        first.background.setText('2.25');first.flush_draft()
        first.diagnostics.set_diagnostics([dict(code='private',message='Only 3D',severity='error')])
        self.store.activate_study('photonic_bands.2d')
        second=PhotonicBandsWorkspace(self.store,document_id='photonic_bands.2d')
        self.pages.append(second)
        second.initialize_2d_document();second.background.setText('1.44');second.flush_draft()
        self.assertTrue(first.dimension.isHidden())
        self.assertTrue(second.solver.isHidden())
        self.assertEqual(second.diagnostics.list.count(),0)
        first.background.setText('9');first.flush_draft()
        self.assertEqual(self.store.search_state['research_workspaces']['bands']['fields']['background_epsilon'],'1.44')
        self.store.activate_study('photonic_bands')
        self.assertEqual(first.background.text(),'2.25')
        self.assertEqual(first.dimension.currentData(),3)
        self.assertEqual(second.dimension.currentData(),2)

    def test_import_for_another_band_type_preserves_current_crystal(self):
        self.store.activate_study('photonic_bands')
        page=PhotonicBandsWorkspace(self.store,document_id='photonic_bands')
        self.pages.append(page)
        page.background.setText('2.25');page.flush_draft()
        before=page.draft()
        other=dict(dimension=2,solver='mpb',lattice_vectors=[[1,0],[0,1]],
            background_epsilon=1,geometry=[],polarizations=['te'],
            k_vertices=[[0,0],[0.5,0]],points_per_segment=4,
            runtime=dict(mode='wsl',distro='Ubuntu',executable='/usr/bin/mpb'))
        with self.assertRaisesRegex(ValueError,'different band simulation'):
            page.load_settings(other)
        self.assertEqual(page.draft(),before)
        self.assertEqual(self.store.search_state['research_workspaces']['bands'],before)


if __name__=='__main__':unittest.main()
