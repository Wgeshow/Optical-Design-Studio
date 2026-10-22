"""Independent editable studies, explicit transfers, and real Qt input flows."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QCoreApplication,QEvent
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from simulation_documents import STUDY_IDS,transfer_sections

APP=QApplication.instance() or QApplication([])


class DocumentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.library=DataLibrary(Path(self.temp.name)/'library')
        self.store=ProjectStore(self.library,restore=False)

    def tearDown(self):self.temp.cleanup()

    def test_every_study_has_independent_geometry_and_parameters_and_portable_reload(self):
        for index,identifier in enumerate(STUDY_IDS):
            self.store.activate_study(identifier)
            self.store.update_settings(dict(ax_um=10.+index,wl_start_nm=1200.+index))
        project=self.store.portable_project()
        restored=ProjectStore(self.library,restore=False)
        restored.load_project(project,autosave=False)
        self.assertEqual(set(project['simulation_documents']['documents']),set(STUDY_IDS))
        for index,identifier in enumerate(STUDY_IDS):
            restored.activate_study(identifier)
            self.assertEqual(restored.device['width_um'],10.+index)
            self.assertEqual(restored.settings['wl_start_nm'],1200.+index)
        restored.device['width_um']=999
        self.assertNotEqual(restored.study_project('electrical')['device']['width_um'],999)

    def test_new_study_does_not_implicitly_copy_edited_structure(self):
        original=copy.deepcopy(self.store.device)
        self.store.update_settings(dict(ax_um=123))
        self.store.activate_study('thermal')
        self.assertEqual(self.store.device,original)
        self.store.activate_study('optical')
        self.assertEqual(self.store.device['width_um'],123)

    def test_explicit_geometry_transfer_preserves_destination_solver_settings(self):
        self.store.update_settings(dict(ax_um=12,wl_start_nm=1400))
        self.store.activate_study('electrical.iv')
        self.store.update_settings(dict(wl_start_nm=1660))
        self.store.transfer_study_inputs('optical')
        self.assertEqual(self.store.device['width_um'],12)
        self.assertEqual(self.store.settings['wl_start_nm'],1660)
        self.store.update_settings(dict(ax_um=22))
        self.assertEqual(self.store.study_project('optical')['device']['width_um'],12)
        self.assertEqual(transfer_sections('photonic_bands','thermal'),[])
        with self.assertRaises(ValueError):self.store.transfer_study_inputs('photonic_bands')

    def test_legacy_project_load_and_job_snapshot_remain_supported(self):
        legacy=self.store._project_payload()
        legacy['settings']['ax_um']=8
        legacy['device']['width_um']=8
        self.store.load_project(legacy)
        self.assertEqual(self.store.device['width_um'],8)
        self.store.activate_study('electrical')
        self.store.activate_study('optical')
        self.assertEqual(self.store.device['width_um'],8)

    def test_inactive_optical_table_assets_survive_new_library_reload(self):
        table=Path(self.temp.name)/'measured.csv'
        table.write_text('wavelength,n,k\n1.2,3.1,0.02\n1.7,3.7,0.03\n')
        self.store.materials.loc[1,'Model']='table_nk'
        self.store.materials.loc[1,'DataFile']=table.name
        self.store.materials.loc[1,'WavelengthUnit']='um'
        self.store.files=[str(table)]
        self.store.activate_study('electrical')
        portable=self.store.portable_project()
        restored=ProjectStore(DataLibrary(Path(self.temp.name)/'other-library'),restore=False)
        restored.load_project(portable,autosave=False)
        restored.activate_study('optical')
        self.assertTrue(restored.files)
        self.assertEqual(Path(restored.files[0]).read_text(),table.read_text())

    def test_apply_design_preserves_newer_inactive_studies(self):
        self.store.activate_study('tools.sweep')
        older=self.store.project()
        older['settings']['ax_um']=12;older['device']['width_um']=12
        self.store.activate_study('electrical')
        self.store.update_settings(dict(ax_um=99))
        self.store.activate_study('tools.sweep')
        with patch.object(self.library,'project_for',return_value=(older,{})):
            self.store.apply_design(Path(self.temp.name)/'old-sweep',design_id=1)
        self.assertEqual(self.store.active_study,'tools.sweep')
        self.assertEqual(self.store.device['width_um'],12)
        self.assertEqual(self.store.study_project('electrical')['device']['width_um'],99)


class DocumentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.environment=patch.dict(os.environ,S4_LIBRARY_ROOT=str(Path(cls.temp.name)/'preferences'))
        cls.environment.start()
        from qt_app import OpticalStudio
        cls.store=ProjectStore(DataLibrary(Path(cls.temp.name)/'library'),restore=False)
        cls.window=OpticalStudio(cls.store)
        cls.window.resize(1280,900)
        cls.window.show();APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window.hide();cls.window.deleteLater();APP.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        cls.environment.stop();cls.temp.cleanup()

    def open(self,target):
        self.window._open_simulation_choice(target);APP.processEvents()
        self.assertEqual(self.store.active_study,target)

    def test_chooser_all_types_restores_own_document(self):
        for index,target in enumerate(STUDY_IDS):
            self.open(target)
            self.store.update_settings(dict(ax_um=100+index))
        for index,target in enumerate(STUDY_IDS):
            self.open(target)
            self.assertEqual(self.store.device['width_um'],100+index,target)

    def test_fdtd_project_reload_and_unrun_inputs_persist(self):
        self.open('fdtd')
        page=self.window.fdtd_page
        page.controls['resolution'].setValue(47)
        self.open('optical');self.open('fdtd')
        self.assertEqual(page.options()['resolution'],47)
        project=self.store.project();project['desktop_search']['fdtd']['resolution']=52
        self.store.load_project(project)
        self.assertEqual(page.options()['resolution'],52)

    def test_pcsel_choices_have_separate_editors_and_independent_inputs(self):
        self.open('pcsel.vertical')
        vertical=self.window.research_studies_page._pages['pcsel']
        vertical.fields['lattice_nm'].setText('431')
        self.open('pcsel.cwt')
        page=self.window.research_studies_page._pages['pcsel']
        self.assertIsNot(page,vertical)
        self.assertEqual(self.store.active_study,'pcsel.cwt')
        self.assertNotEqual(page.fields['lattice_nm'].text(),'431')
        page.fields['lattice_nm'].setText('544')
        self.open('pcsel.vertical')
        self.assertEqual(vertical.fields['lattice_nm'].text(),'431')
        self.open('pcsel.cwt')
        self.assertEqual(page.fields['lattice_nm'].text(),'544')

    def test_incomplete_text_and_sampler_link_stay_with_own_document(self):
        self.open('electrical.iv')
        page=self.window.electrical_page
        page.drafts['ui.electrical.bias_list_text']='-1, unfinished'
        self.open('coupled');self.open('electrical.iv')
        self.assertEqual(page.drafts['ui.electrical.bias_list_text'],'-1, unfinished')
        self.open('tools.index_shift')
        self.window._route_setup_action('optical.sweep')
        self.assertEqual(self.store.active_study,'tools.index_shift')
        self.store.update_settings(dict(wl_start_nm=1391))
        self.open('optical')
        self.assertNotEqual(self.store.settings['wl_start_nm'],1391)

    def test_lumped_laser_parameters_and_device_round_trip_in_project(self):
        self.open('lumped_laser')
        page=self.window.research_studies_page._pages['lumped_laser']
        page.quality_factor.setValue(34567)
        page.device_store.update_settings(dict(ax_um=.555))
        self.window._flush_research_drafts()
        project=self.store.project()
        page.quality_factor.setValue(7000)
        self.store.load_project(project)
        self.assertEqual(page.quality_factor.value(),34567)
        self.assertEqual(page.device_store.settings['ax_um'],.555)

    def test_fresh_2d_bands_and_selector_keep_valid_independent_crystal(self):
        self.open('photonic_bands.2d')
        page=self.window.photonic_bands_page
        dimension,lattice,geometry=page._geometry_inputs()
        self.assertEqual(dimension,2)
        self.assertTrue(all(item['shape'] in ('circle','block') for item in geometry))
        page.background.setText('2.3')
        self.open('photonic_bands')
        self.assertEqual(self.store.active_study,'photonic_bands')
        self.assertNotEqual(self.window.photonic_bands_page.background.text(),'2.3')
        self.open('photonic_bands.2d')
        self.assertEqual(page.background.text(),'2.3')

    def test_explicit_pcsel_transfer_copies_geometry_not_solver_controls(self):
        self.open('pcsel.vertical')
        page=self.window.research_studies_page._pages['pcsel']
        page.fields['lattice_nm'].setText('499')
        self.open('pcsel.cwt')
        page=self.window.research_studies_page._pages['pcsel']
        page.fields['harmonics'].setText('8')
        self.window._flush_research_drafts()
        self.store.transfer_study_inputs('pcsel.vertical')
        self.assertEqual(page.fields['lattice_nm'].text(),'499')
        self.assertEqual(page.fields['model'].currentData(),'cwt')
        self.assertEqual(page.fields['harmonics'].text(),'8')

    def test_sweep_ai_documents_and_unknown_sections_are_safe(self):
        self.open('optical')
        self.store.update_settings(dict(ax_um=33))
        self.window._navigate_route(3)
        self.assertEqual(self.store.active_study,'tools.sweep')
        self.store.transfer_study_inputs('optical')
        self.store.update_settings(dict(ax_um=44))
        self.window._navigate_route(8)
        self.assertEqual(self.store.active_study,'tools.ai')
        self.store.update_settings(dict(ax_um=55))
        self.open('optical');self.assertEqual(self.store.device['width_um'],33)
        self.open('tools.sweep');self.assertEqual(self.store.device['width_um'],44)
        self.window._route_setup_action('coupled.electrical')
        self.assertEqual(self.store.active_study,'coupled')
        self.assertEqual(self.window.coupled_page.current_section,'coupled.overview')

    def test_ai_inputs_restore_and_empty_bounds_clear_old_ranges(self):
        self.open('tools.ai')
        page=self.window.pages['AI Search']
        page.controls['wavelength_nm'].setValue(1432)
        page.bounds.set_records([dict(Parameter='lattice_square',Target='',Min=.6,Max=.7,Step=.1,Choices='')])
        self.open('optical');self.open('tools.ai')
        self.assertEqual(page.controls['wavelength_nm'].value(),1432)
        self.assertTrue(page.bounds.records())
        project=self.store.project();project['desktop_search'].pop('ai_search',None)
        self.store.load_project(project)
        self.assertEqual(page.bounds.records(),[])

    def test_hidden_search_editors_do_not_save_when_another_structure_changes(self):
        self.open('tools.sweep')
        sweep=self.window.pages['Optimize']
        bounds=[dict(Parameter='lattice_square',Target='',Min=.6,Max=.7,Step=.1,Choices='')]
        sweep.bounds.set_records(bounds)
        sweep.target_controls['trials'].setValue(32)
        sweep.persist_setup('target')
        saved=copy.deepcopy(self.store.search_state)
        self.open('tools.ai')
        ai=self.window.pages['AI Search']
        ai.bounds.set_records(bounds)
        ai.controls['wavelength_nm'].setValue(1435)
        ai_saved=copy.deepcopy(self.store.search_state['ai_search'])
        self.open('electrical.cv')
        self.store.replace_active_study(self.store._study_seed)
        self.store.set_structure(self.store.materials,self.store.layers,self.store.patterns.iloc[0:0])
        for key in ('peaks','target','ai_search','index_shift'):
            self.assertNotIn(key,self.store.search_state,key)
        self.open('tools.sweep')
        self.assertEqual(sweep.bounds.records(),bounds)
        self.assertEqual(self.store.search_state['target'],saved['target'])
        self.open('tools.ai')
        self.assertEqual(ai.bounds.records(),bounds)
        self.assertEqual(self.store.search_state['ai_search'],ai_saved)

    def test_index_material_selection_is_saved_before_running(self):
        self.open('tools.index_shift')
        page=self.window.index_shift_page
        page.material.setCurrentIndex(1 if page.material.currentIndex()!=1 else 0)
        selected=page.material.currentData()
        self.open('thermal');self.open('tools.index_shift')
        self.assertEqual(page.material.currentData(),selected)


if __name__=='__main__':unittest.main()
