"""Different optical solvers retain separate native setup and execution paths."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QComboBox
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_app import OpticalStudio
from optical_ui_scope import require_s4_preset

APP=QApplication.instance() or QApplication([])


class OpticalEngineSeparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='ods-engine-separation-')
        cls.store=ProjectStore(DataLibrary(Path(cls.temp.name)/'library'),restore=False)
        cls.window=OpticalStudio(cls.store)
        cls.window.resize(1500,960);cls.window.show();APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window.hide();cls.window.deleteLater();APP.processEvents();cls.temp.cleanup()

    def test_s4_and_coupled_have_no_meep_controls_or_engine_toggle(self):
        for target in ('optical','coupled'):
            self.window._open_simulation_choice(target);APP.processEvents()
            page=self.window._active_setup_page()
            self.assertFalse(any(key.startswith('search.fdtd.') or 'meep' in key for key in page.widgets_by_key))
            self.assertIn('settings.NumG',page.widgets_by_key)
            self.assertTrue(all(not isinstance(widget,QComboBox) for widget in page.widgets_by_key['ui.optical.engine']))
            if target=='coupled':
                page.select_section('coupled.optical-setup');APP.processEvents()
                self.assertIn('optical',page.nested_sections)
                self.assertEqual(page.state.get('ui.optical.engine'),'s4')

    def test_switching_engines_preserves_each_setup_and_device(self):
        w=self.window;s=self.store
        w._open_simulation_choice('optical');APP.processEvents()
        w.setup_state.set('settings.NumG',37)
        s4device=copy.deepcopy(s.device)
        with patch.object(s,'start_run') as run:
            w._route_setup_action('engine.meep');APP.processEvents()
            self.assertEqual(s.active_study,'fdtd')
            page=w._active_setup_page()
            page.controls['resolution'].setValue(43)
            self.assertIn('pml_um',page.controls)
            self.assertIn('run_after_sources',page.controls)
            self.assertNotIn('num_basis',page.controls)
            meepdevice=copy.deepcopy(s.device)
            w._route_setup_action('engine.s4');APP.processEvents()
            self.assertEqual(s.active_study,'optical')
            self.assertEqual(w.setup_state.get('settings.NumG'),37)
            self.assertEqual(s.device,s4device)
            w._route_setup_action('engine.meep');APP.processEvents()
            self.assertEqual(page.controls['resolution'].value(),43)
            self.assertEqual(s.device,meepdevice)
            self.assertFalse(run.called)

    def test_legacy_mixed_engine_does_not_run_another_workspace(self):
        w=self.window
        w._open_simulation_choice('optical');APP.processEvents()
        w.setup_state.set('ui.optical.engine','meep')
        with patch.object(w,'show_error') as error,patch.object(w.fdtd_page,'run') as meep,patch.object(self.store,'start_run') as run:
            w._run_setup_mode('optical')
            self.assertTrue(error.called)
            self.assertFalse(meep.called or run.called)
        w.setup_state.set('ui.optical.engine','s4')

    def test_malformed_presets_are_validation_errors(self):
        for payload in ([], {'values':None}, {'values':[]}):
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                require_s4_preset(payload)

    def test_meep_import_keeps_device_and_s4_options_and_all_parameters_editable(self):
        from fdtd_model import DEFAULTS
        w=self.window;s=self.store
        w._open_simulation_choice('fdtd');APP.processEvents()
        page=w.fdtd_page
        self.assertEqual(set(page.controls),set(DEFAULTS))
        geometry=copy.deepcopy(s.device)
        settings=copy.deepcopy(s.settings)
        payload=dict(kind='ods_simulation_setup',schema_version=1,fdtd=dict(resolution=41,max_cells=2500000,fit_tolerance=.02),
                     settings={'NumG':999},values={'ui.optical.engine':'meep'})
        with patch.object(s,'start_run') as run:
            page.apply_setup_preset(payload)
            self.assertEqual(page.controls['resolution'].value(),41)
            self.assertEqual(page.controls['max_cells'].value(),2500000)
            self.assertEqual(page.controls['fit_tolerance'].value(),.02)
            self.assertEqual(s.device,geometry)
            self.assertEqual(s.settings,settings)
            self.assertFalse(run.called)
            before=copy.deepcopy(s.project())
            with self.assertRaises(ValueError):page.apply_setup_preset({'fdtd':{'dimensions':7}})
            self.assertEqual(s.project(),before)

    def test_legacy_coupled_identity_can_be_restored_without_losing_inputs(self):
        w=self.window;s=self.store
        w._open_simulation_choice('coupled');APP.processEvents()
        page=w.coupled_page
        w.setup_state.set('ui.optical.engine','meep');APP.processEvents()
        before=copy.deepcopy(s.project())
        self.assertTrue(page.engine_recovery.isVisible())
        page.engine_recovery.click();APP.processEvents()
        self.assertEqual(w.setup_state.get('ui.optical.engine'),'s4')
        self.assertEqual(s.device,before['device'])
        self.assertEqual(s.settings,before['settings'])
        self.assertEqual(s.search_state.get('fdtd'),before['desktop_search'].get('fdtd'))
        self.assertFalse(page.engine_recovery.isVisible())

    def test_meep_preset_rejected_before_mutation(self):
        before=copy.deepcopy(self.store.project())
        with self.assertRaisesRegex(ValueError,'separate Meep'):
            require_s4_preset({'values':{'ui.optical.engine':'meep'}})
        self.assertEqual(self.store.project(),before)


if __name__=='__main__':unittest.main()
