"""Actual volume/probe linking, portable paths, terminal curves and exports."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication

from qt_electrical_results import (
    ElectricalResultsPanel, export_rectilinear_vtk, load_electrical_volume,
    nearest_grid_probe, terminal_curve_figure,
)

APP = QApplication.instance() or QApplication([])


def _volume(bias=0.):
    x = np.array([-2.,-.5,1.])*1e-6
    y = np.array([-1.,.2,1.5])*1e-6
    z = np.array([.02,.09,.21,.42])*1e-6
    xx,yy,zz = np.meshgrid(x,y,z,indexing='ij')
    potential = (xx*2+yy*3+zz*4)*1e6+bias
    field = np.broadcast_to(np.array([-2e6,-3e6,-4e6]),potential.shape+(3,)).copy()
    return dict(x=x,y=y,z=z,potential=potential,field_V_m=field,
        electrons_cm3=np.full(potential.shape,1e18)+potential*1e12,
        holes_cm3=np.full(potential.shape,1e10),charge_density_C_m3=potential*100,
        epsilon_r=np.full(potential.shape,11.7),
        layer_index=np.zeros(potential.shape,int),material_index=np.zeros(potential.shape,int),
        contact_index=np.full(potential.shape,-1,int),solid=np.ones(potential.shape,bool),
        material_ids=np.array(['silicon']),layer_ids=np.array(['silayer']),layer_names=np.array(['Silicon active layer']),contact_ids=np.array(['ring']),
        cell_volumes_m3=np.arange(potential.size,dtype=float).reshape(potential.shape)*1e-24+1e-24)


class ElectricalResultsTests(unittest.TestCase):
    def test_physical_model_invalid_samples_remain_curve_gaps(self):
        frame=pd.DataFrame(dict(bias_V=[0.,.1,.2,.3],current_A=[0.,float('nan'),1e-9,2e-9]))
        figure=terminal_curve_figure(frame,None,'iv',dict(model='Sourced leakage model'))
        values=np.asarray(figure.axes[0].lines[0].get_ydata(),float)
        self.assertEqual(len(values),4)
        self.assertTrue(np.isnan(values[1]))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='electrical_results_')
        self.directory = Path(self.temp.name)
        self.panel = None
        self.summary = dict(model='custom_device',options=dict(swept_contact_id='ring',charge_model='semiconductor'),
            mesh=dict(shape=[3,3,4],cells=36,feature_cells={'ring':8}),
            evaluated_materials=[dict(id='silicon',sources=[dict(title='Sample source',url='https://example.org/silicon')])],
            limitations=['Electrostatic reservoir model'],results=[],elapsed_s=.1)
        for bias in (0.,-1.):
            path = self.directory/f'custom_{bias:g}V.npz'
            np.savez_compressed(path,**_volume(bias))
            self.summary['results'].append(dict(bias_V=bias,volume_npz=str(Path('C:/old/moved')/path.name),
                checks=dict(max_normalized_Poisson_residual=1e-11,relative_gauss_balance=1e-12,iterations=5)))

    def tearDown(self):
        if self.panel is not None:
            self.panel.close(); self.panel.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def show_panel(self):
        self.panel = ElectricalResultsPanel()
        self.panel.resize(1160,800)
        self.panel.set_result(self.directory,self.summary)
        self.panel.show(); APP.processEvents()
        return self.panel

    def test_linked_views_probe_the_actual_nonuniform_grid(self):
        panel = self.show_panel()
        panel.set_probe(-.6e-6,.25e-6,.19e-6)
        self.assertEqual(panel.cursor_indices,(1,1,2))
        expected = _volume()['potential'][1,1,2]
        self.assertAlmostEqual(panel.probe['values']['potential'],expected)
        self.assertEqual(panel.probe['material_id'],'silicon')
        self.assertEqual(panel.probe['layer_id'],'silayer')
        self.assertEqual(panel.probe['layer_name'],'Silicon active layer')
        self.assertIn('Silicon active layer',panel.probe_label.text())
        self.assertAlmostEqual(panel.probe['coordinates_m'][2],.21e-6)
        self.assertAlmostEqual(panel.top_view.values[1,1],expected)
        self.assertAlmostEqual(panel.cross_view.values[1,2],expected)
        self.assertEqual(len(panel.volume_view.points),36)
        self.assertIn('Nearest stored grid sample',panel.probe_label.text())
        panel._pick_xy(1e-6,-1e-6)
        self.assertEqual(panel.cursor_indices,(2,0,2))
        panel._pick_xz(-2e-6,.42e-6)
        self.assertEqual(panel.cursor_indices,(0,0,3))
        panel.quantity.setCurrentIndex(panel.quantity.findData('field_magnitude_V_m'))
        self.assertAlmostEqual(panel.probe['values']['field_magnitude_V_m'],np.sqrt(29)*1e6)
        self.assertIn('Electric field |E|',panel.probe_label.text())
        self.assertTrue(panel.export_npz_button.isEnabled())

    def test_bias_selection_reloads_saved_data_and_exposes_sources_checks_inputs(self):
        panel = self.show_panel()
        panel.set_probe(-.5e-6,.2e-6,.21e-6)
        value = panel.probe['values']['potential']
        panel.result_bias.setCurrentIndex(1)
        panel.set_probe(-.5e-6,.2e-6,.21e-6)
        self.assertAlmostEqual(panel.probe['values']['potential'],value-1)
        self.assertEqual(panel.volume_path.name,'custom_-1V.npz')
        self.assertIn('Sample source',panel.sources.toPlainText())
        self.assertIn('swept_contact_id',panel.inputs.toPlainText())
        self.assertIn('feature_cells',panel.run_details.toPlainText())
        self.assertEqual(panel.checks_table.rowCount(),2)

    def test_parent_bias_selector_can_synchronize_using_saved_voltage(self):
        panel = self.show_panel()
        changed = []
        panel.biasChanged.connect(changed.append)
        self.assertTrue(panel.set_bias(-1.))
        self.assertEqual(panel.selected_bias(),-1.)
        self.assertEqual(changed,[-1.])
        self.assertEqual(panel.volume_path.name,'custom_-1V.npz')
        self.assertFalse(panel.set_bias(None))
        self.assertFalse(panel.set_bias(-3.))
        self.assertEqual(panel.selected_bias(),-1.)
        with self.assertRaisesRegex(ValueError,'finite voltage'):
            panel.set_bias(float('nan'))

    def test_missing_legacy_quantities_are_unavailable_and_no_fake_curves(self):
        minimal = _volume()
        for key in ('field_V_m','electrons_cm3','holes_cm3','charge_density_C_m3'):
            del minimal[key]
        np.savez_compressed(self.directory/'custom_0V.npz',**minimal)
        panel = self.show_panel()
        index = panel.quantity.findData('electrons_cm3')
        self.assertIn('Unavailable',panel.quantity.itemText(index))
        self.assertFalse(panel.quantity.model().item(index).isEnabled())
        self.assertNotIn('electrons_cm3',panel.probe['values'])
        self.assertEqual(len(panel.iv_plot.figure.axes[0].lines),0)
        self.assertEqual(len(panel.cv_plot.figure.axes[0].lines),0)
        missing = dict(self.summary,results=[dict(bias_V=0.)])
        panel.set_result(self.directory,missing)
        self.assertFalse(panel.export_npz_button.isEnabled())
        self.assertIsNone(panel.top_view.values)
        self.assertIn('no available volume',panel.status.text())

    def test_iv_cv_and_measured_curves_use_saved_actual_terminal_values(self):
        pd.DataFrame(dict(bias_V=[0,-1,-2],terminal_voltage_V=[.1,-.9,-1.9],current_A=[0,-2e-6,-4e-6],
                          model=['Frozen conductivity']*3)).to_csv(self.directory/'electrical_iv.csv',index=False)
        pd.DataFrame(dict(bias_V=[0,-1,-2],terminal_voltage_V=[.1,-.9,-1.9],terminal_charge_C=[0,-3e-15,-6e-15],
                          capacitance_F=[3e-15]*3)).to_csv(self.directory/'electrical_cv.csv',index=False)
        pd.DataFrame(dict(bias_V=[0,-1],current_A=[0,-1e-6])).to_csv(self.directory/'measured_iv.csv',index=False)
        info = dict(studies=dict(iv=dict(model='Frozen conductivity model'),cv=dict(model='Saved electrode derivative',warnings=['No transported reservoir charge'])))
        (self.directory/'electrical_study_summary.json').write_text(json.dumps(info),encoding='utf-8')
        panel = self.show_panel()
        iv_lines = panel.iv_plot.figure.axes[0].lines
        self.assertEqual(len(iv_lines),2)
        np.testing.assert_allclose(iv_lines[0].get_xdata(),[-1.9,-.9,.1])
        np.testing.assert_allclose(iv_lines[0].get_ydata(),[-4e-6,-2e-6,0])
        self.assertEqual(iv_lines[0].get_label(),'Frozen conductivity model')
        self.assertEqual(iv_lines[1].get_label(),'User supplied measured curve')
        self.assertIn('2 user supplied measured samples',panel.iv_scope.text())
        self.assertIn('No transported reservoir charge',panel.cv_scope.text())
        self.assertEqual(len(panel.cv_plot.figure.axes[0].lines),1)

    def test_real_exports_preserve_arrays_coordinates_and_nonuniform_volumes(self):
        panel = self.show_panel()
        npz = panel.export_file(self.directory/'exported.npz','npz')
        with np.load(npz,allow_pickle=False) as saved:
            np.testing.assert_array_equal(saved['potential'],_volume()['potential'])
            np.testing.assert_array_equal(saved['cell_volumes_m3'],_volume()['cell_volumes_m3'])
        path = panel.export_file(self.directory/'grid.csv','csv')
        with path.open(newline='',encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows),36)
        self.assertEqual(float(rows[0]['x_m']),-2e-6)
        self.assertAlmostEqual(float(rows[0]['potential']),_volume()['potential'][0,0,0])
        vtk = panel.export_file(self.directory/'grid.vtk','vtk').read_text(encoding='utf-8')
        self.assertIn('DATASET RECTILINEAR_GRID',vtk)
        self.assertIn('DIMENSIONS 3 3 4',vtk)
        self.assertIn('POINT_DATA 36',vtk)
        self.assertIn('SCALARS cell_volumes_m3 double 1',vtk)
        self.assertIn('VECTORS electric_field_V_m double',vtk)
        lines = vtk.splitlines()
        offset = lines.index('X_COORDINATES 3 double')
        np.testing.assert_allclose(np.fromstring(lines[offset+1],sep=' '),_volume()['x'])
        offset = lines.index('SCALARS potential double 1')+2
        scalars = []
        while lines[offset] and not lines[offset].startswith('SCALARS'):
            scalars.extend(float(value) for value in lines[offset].split()); offset += 1
        np.testing.assert_allclose(scalars,_volume()['potential'].ravel(order='F'))
        figure = panel.export_file(self.directory/'fields.png','figure')
        self.assertGreater(figure.stat().st_size,1000)

    def test_invalid_axes_are_rejected_before_display(self):
        bad = _volume(); bad['x'] = np.array([1.,0.,2.])
        path = self.directory/'invalid.npz'; np.savez_compressed(path,**bad)
        with self.assertRaisesRegex(ValueError,'increasing'):
            load_electrical_volume(path)
        with self.assertRaisesRegex(ValueError,'three finite'):
            nearest_grid_probe(_volume(),[float('nan'),0,0])

    def test_preview_point_count_is_bounded_for_large_actual_volume(self):
        panel = self.show_panel()
        x=np.linspace(-1,1,25)*1e-6; y=x.copy(); z=np.linspace(0,1,30)*1e-6
        values=np.arange(25*25*30,dtype=float).reshape(25,25,30)
        from qt_electrical_results import _FieldColors
        panel.volume_view.set_field(dict(x=x,y=y,z=z),values,_FieldColors(values),(0,0,0),'Large actual volume')
        self.assertEqual(len(panel.volume_view.points),10000)
        self.assertEqual(panel.volume_view.total_samples,18750)
        self.assertEqual(panel.volume_view.values[0],0)
        self.assertEqual(panel.volume_view.values[-1],18749)


if __name__ == '__main__':
    unittest.main()
