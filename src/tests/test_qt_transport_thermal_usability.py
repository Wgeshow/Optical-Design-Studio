"""Native scientific editors retain authored values and reveal precise inputs."""
import copy
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QScrollArea
from benchmark_registry import list_benchmarks, load_benchmark
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_sesame_setup import SesameSetupWorkspace
from qt_thermal_setup import ThermalSetupWorkspace

APP=QApplication.instance() or QApplication([])


class TransportThermalUsabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='transport-thermal-ui-',dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.pages=[]

    def tearDown(self):
        for page in self.pages:
            page._save_timer.stop(); page.close(); page.deleteLater()
        APP.processEvents()

    def page(self,cls):
        page=cls(self.store); page.resize(1000,760); page.show(); page.adapt_layout()
        self.pages.append(page); QTest.qWait(160)
        return page

    def test_deleted_pages_disconnect_from_global_theme_signal(self):
        from PyQt6 import sip
        from qt_common import theme_manager
        errors=[]
        with patch.object(sys,'excepthook',lambda kind,error,traceback:errors.append(str(error))):
            for cls in (SesameSetupWorkspace,ThermalSetupWorkspace):
                page=self.page(cls)
                self.pages.remove(page)
                sip.delete(page)
            theme_manager().changed.emit(theme_manager().mode)
            APP.processEvents()
        self.assertEqual(errors,[])

    def transport(self,dimension=1):
        item=next(item for item in list_benchmarks() if item.get('engine')=='sesame_transport'
            and load_benchmark(item['id'])['options']['settings']['dimension']==dimension)
        case=load_benchmark(item['id']); page=self.page(SesameSetupWorkspace)
        page.load_settings(copy.deepcopy(case['options']['settings']))
        return page,case

    def test_paper_domain_editor_preserves_options_and_shared_device(self):
        before=copy.deepcopy(self.store.device)
        page,case=self.transport(2)
        actual=page.options()['settings']; expected=case['options']['settings']
        for key in ('materials','contacts','x_nodes_um','y_nodes_um','defects'):
            self.assertEqual(actual[key],expected[key])
        identity=actual['regions'][0]['id']
        editor=page.inspectors['regions']
        page.open_diagnostic(dict(field='regions.donors_cm3',object_id=identity))
        editor.editors['donors_cm3'].setText('3.25e15')
        self.assertEqual(page.options()['settings']['regions'][0]['donors_cm3'],3.25e15)
        material=editor.editors['material']
        material.setCurrentIndex(1)
        self.assertEqual(page.regions.item(0,1).text(),material.currentData())
        self.assertEqual(self.store.device,before)

    def test_material_diagnostic_reveals_exact_advanced_input_and_preserves_invalid_draft(self):
        page,_=self.transport()
        identity=page.materials.item(0,0).text()
        editor=page.inspectors['materials']
        page.materials.item(0,page.material_keys.index('B')).setText('1e-')
        page.tabs.setCurrentIndex(4)
        self.assertTrue(page.open_diagnostic(dict(field='materials.B',object_id=identity)))
        APP.processEvents()
        self.assertTrue(editor.advanced_toggle.isChecked())
        self.assertIs(APP.focusWidget(),editor.editors['B'])
        self.assertTrue(editor.editors['B'].isVisible())
        page.flush_draft(); state=copy.deepcopy(page.draft())
        page.restore_draft(state)
        self.assertEqual(editor.editors['B'].text(),'1e-')
        self.assertEqual(page.materials.item(0,page.material_keys.index('B')).text(),'1e-')

    def test_inactive_contact_value_survives_native_kind_switch(self):
        page,_=self.transport()
        page.contacts.setCurrentCell(1,0)
        editor=page.inspectors['contacts']
        editor.editors['kind'].setCurrentIndex(editor.editors['kind'].findData('Schottky'))
        editor.editors['work_function_eV'].setText('4.7e-')
        editor.editors['kind'].setCurrentIndex(editor.editors['kind'].findData('Ohmic'))
        self.assertFalse(editor.editors['work_function_eV'].isVisible())
        self.assertEqual(page.contacts.item(1,4).text(),'4.7e-')
        editor.editors['kind'].setCurrentIndex(editor.editors['kind'].findData('Schottky'))
        self.assertEqual(editor.editors['work_function_eV'].text(),'4.7e-')

    def test_preview_uses_domain_not_runtime_and_retains_last_valid_geometry(self):
        page,_=self.transport(2)
        page.executable.setText('unfinished runtime')
        page.preview_domain(); figure=page.domain_preview.figure
        self.assertGreater(len(figure.axes[0].patches),0)
        page.regions.item(0,2).setText('0, 1e-')
        page.preview_domain()
        self.assertIs(page.domain_preview.figure,figure)
        self.assertIn('last valid',page.preview_note.text())

    def test_focused_region_edit_is_in_normal_job_request(self):
        page,_=self.transport()
        identity=page.regions.item(0,0).text()
        page.open_diagnostic(dict(field='regions.generation_cm3_s',object_id=identity))
        edit=page.inspectors['regions'].editors['generation_cm3_s']
        edit.setFocus(); edit.setText('2.5e19')
        with patch.object(self.store,'start_run') as run:
            page.run()
        self.assertEqual(run.call_args.args[0],'research_simulation')
        self.assertEqual(run.call_args.args[1]['settings']['regions'][0]['generation_cm3_s'],2.5e19)

    def thermal(self):
        page=self.page(ThermalSetupWorkspace)
        for i in range(page.conductivities.rowCount()):
            page.conductivities.item(i,1).setText('45')
            page.conductivities.item(i,2).setText('Explicit test source')
        page.void_k.setText('.025')
        return page

    def test_thermal_native_power_source_and_face_edit_roundtrip(self):
        page=self.thermal(); before=copy.deepcopy(self.store.device)
        layer=page._layer_ids[0]; material=page._material_ids[0]
        self.assertTrue(page.open_diagnostic(dict(field='power_by_layer_W',object_id=layer)))
        page.power_inspector.editors['power'].setText('.125')
        self.assertTrue(page.open_diagnostic(dict(field='conductivity.source',object_id=material)))
        self.assertIs(APP.focusWidget(),page.material_inspector.editors['source'])
        self.assertTrue(page.open_diagnostic(dict(field='boundaries.z_max.kind')))
        edit=page.boundary_inspector.editors['kind']; edit.setCurrentIndex(edit.findData('convection'))
        page.boundary_inspector.editors['temperature_K'].setText('295')
        page.boundary_inspector.editors['coefficient_W_m2K'].setText('1200')
        settings=page.options()['settings']; state=copy.deepcopy(page.draft())
        page.restore_draft(state)
        self.assertEqual(page.options()['settings'],settings)
        self.assertEqual(settings['power_by_layer_W'][layer],.125)
        self.assertEqual(settings['boundaries']['z_max'],dict(kind='convection',temperature_K=295,coefficient_W_m2K=1200))
        self.assertEqual(self.store.device,before)
        self.assertIn('Bottom',page.boundary_inspector.selector.currentText())

    def test_thermal_hidden_boundary_and_source_drafts_are_lossless(self):
        page=self.thermal(); page.open_diagnostic(dict(field='boundaries.z_max.coefficient_W_m2K'))
        page.boundary_inspector.editors['coefficient_W_m2K'].setText('1e-')
        combo=page.boundary_inspector.editors['kind']; combo.setCurrentIndex(combo.findData('insulated'))
        state=copy.deepcopy(page.draft()); page.restore_draft(state)
        self.assertEqual(page.boundaries.item(5,3).text(),'1e-')
        self.assertFalse(page.boundary_inspector.editors['coefficient_W_m2K'].isVisible())
        page.open_diagnostic(dict(field='boundaries.z_max.coefficient_W_m2K'))
        self.assertTrue(page.boundary_inspector.editors['coefficient_W_m2K'].isVisible())
        self.assertIs(APP.focusWidget(),page.boundary_inspector.editors['coefficient_W_m2K'])

    def test_thermal_top_to_bottom_context_and_stable_removed_id(self):
        page=self.thermal(); page.preview_device()
        self.assertGreater(page.layer_preview.figure.axes[0].get_ylim()[0],page.layer_preview.figure.axes[0].get_ylim()[1])
        self.assertFalse(page.open_diagnostic(dict(field='conductivity',object_id='removed-material')))
        self.assertIn('no longer',page.status.text())
        requests=[]; page.diagnosticRequested.connect(requests.append)
        page.edit_device()
        self.assertEqual(requests,[])
        self.assertEqual(page.tabs.currentIndex(),page.sections['device_editor'])
        self.assertIsNotNone(page.device_editor.editor)

    def test_return_from_structure_refreshes_device_and_keeps_layer_draft(self):
        page=self.thermal(); identity=page._layer_ids[0]
        page.powers.item(0,1).setText('1e-')
        device=copy.deepcopy(self.store.device)
        device['layers'][0]['thickness_um']*=2
        self.store.set_device(device)
        page.preview_device()
        self.assertEqual(page.powers.item(page._layer_ids.index(identity),1).text(),'1e-')
        expected=sum(row['thickness_um'] for row in device['layers'] if row.get('enabled',True))
        self.assertEqual(page.layer_preview.figure.axes[0].get_ylim()[0],expected)

    def test_compact_form_captions_and_inputs_remain_reachable(self):
        for cls in (SesameSetupWorkspace,ThermalSetupWorkspace):
            page=self.page(cls); page.resize(760,700); page.adapt_layout(); APP.processEvents()
            if cls is SesameSetupWorkspace:
                targets=[(0,page.inspectors['regions'],'donors_cm3'),(1,page.inspectors['materials'],'Eg'),(2,page.inspectors['contacts'],'kind')]
            else:
                targets=[(0,page.power_inspector,'power'),(1,page.material_inspector,'source'),(2,page.boundary_inspector,'kind')]
            for index,inspector,key in targets:
                page.tabs.setCurrentIndex(index); APP.processEvents()
                widget=inspector.editors[key]; caption=inspector.forms[key].labelForField(widget)
                self.assertGreaterEqual(caption.width(),80)
                self.assertGreaterEqual(caption.height(),caption.fontMetrics().height())
                ancestor=widget.parentWidget()
                while ancestor and ancestor is not page:
                    if isinstance(ancestor,QScrollArea):
                        ancestor.ensureWidgetVisible(widget)
                        APP.processEvents()
                        self.assertEqual(ancestor.horizontalScrollBar().maximum(),0)
                        left=widget.mapTo(ancestor.viewport(),QPoint(0,0)).x()
                        self.assertGreaterEqual(left,0)
                        self.assertLessEqual(left+widget.width(),ancestor.viewport().width()+1)
                    ancestor=ancestor.parentWidget()


if __name__=='__main__': unittest.main()
