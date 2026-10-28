"""Completion events carry a job summary; result panels need saved field summaries."""
import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from device_model import default_device
from qt_core import ProjectStore
from qt_simulation_setup import SimulationSetupWorkspace
APP=QApplication.instance() or QApplication([])


class ElectricalFlowCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='flow_result_')
        self.root=Path(self.temp.name)
        self.pages=[]
        self.store=ProjectStore(DataLibrary(self.root/'library'),restore=False)
        self.block=patch.object(self.store,'start_run',side_effect=AssertionError('No solver in presentation test'))
        self.block.start()

    def tearDown(self):
        self.block.stop()
        for page in self.pages:
            if hasattr(page, '_save_timer'):page._save_timer.stop()
            page.deleteLater()
        APP.processEvents();self.temp.cleanup()

    def page(self, identity):
        self.store.activate_study(identity)
        self.store.set_device(default_device(self.store.electrical_materials))
        page=SimulationSetupWorkspace(self.store, mode='coupled' if identity=='coupled' else 'electrical', document_id=identity)
        self.pages.append(page)
        return page

    def saved(self, name):
        directory=self.root/name;directory.mkdir()
        summary=dict(model='custom_device',results=[],terminal_studies=dict(studies={}))
        (directory/'electrical_summary.json').write_text(json.dumps(summary),encoding='utf-8')
        (directory/'electrical_iv.csv').write_text('bias_V,terminal_voltage_V,current_A\n0,0,0\n.01,.01,2e-6\n',encoding='utf-8')
        (directory/'electrical_cv.csv').write_text('bias_V,terminal_voltage_V,terminal_charge_C,capacitance_F\n-.01,-.01,-8e-17,8e-15\n0,0,0,8e-15\n.01,.01,8e-17,8e-15\n',encoding='utf-8')
        return dict(directory=str(directory),summary=dict(status='complete',task='electrical'))

    def test_wrapper_completion_loads_real_saved_summary_and_curves(self):
        for identity in ('electrical','electrical.iv','electrical.cv','coupled'):
            with self.subTest(identity=identity):
                p=self.page(identity);flow=p.setup_flow
                event=self.saved(identity)
                flow._owns_run=True;flow._finished(event)
                self.assertEqual(flow.result_dashboard.summary['model'],'custom_device')
                self.assertFalse(flow.result_dashboard.isHidden())
                self.assertEqual(flow.completed_event,event)
                self.assertEqual(flow.extra_stage,5)
                if identity in ('electrical.iv','electrical.cv'):
                    flow.show_stage(1)
                    axes=flow.curve_preview.figure.axes
                    self.assertEqual(len(axes),1 if identity.endswith('.iv') else 2)
                    self.assertTrue(all(len(ax.lines)==1 for ax in axes))
                    self.assertTrue(all(not ax.texts for ax in axes))
                    self.assertIn('Saved',axes[0].get_title())
                    expected=[0.,2e-6] if identity.endswith('.iv') else [-8e-17,0.,8e-17]
                    self.assertEqual(list(axes[0].lines[0].get_ydata()),expected)

    def test_missing_or_bad_new_summary_hides_previous_result_and_curve(self):
        p=self.page('electrical.cv');flow=p.setup_flow
        event=self.saved('good');flow._owns_run=True;flow._finished(event);flow.show_stage(1)
        self.assertTrue(flow.curve_preview.figure.axes[0].lines)
        for name,body in [('missing',None),('invalid','{}'),('malformed','{bad')]:
            directory=self.root/name;directory.mkdir()
            if body is not None:(directory/'electrical_summary.json').write_text(body,encoding='utf-8')
            flow._owns_run=True
            flow._finished(dict(directory=str(directory),summary=dict(status='partial')))
            self.assertTrue(flow.result_dashboard.isHidden())
            self.assertIn('could not be loaded',flow.result_note.text())
            flow.show_stage(1)
            self.assertFalse(flow.curve_preview.figure.axes[0].lines)
            self.assertTrue(flow.curve_preview.figure.axes[0].texts)

    def test_unowned_completion_cannot_replace_own_result(self):
        p=self.page('electrical.iv');flow=p.setup_flow
        own=self.saved('own');flow._owns_run=True;flow._finished(own)
        other=self.saved('other');flow._finished(other)
        self.assertEqual(flow.completed_event,own)
        self.assertEqual(flow.result_dashboard.directory,Path(own['directory']))


if __name__=='__main__':unittest.main()
