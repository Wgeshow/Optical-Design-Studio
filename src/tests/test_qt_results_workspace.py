"""Reference-layout workspace uses real saved fields, geometry and spectra."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pandas as pd
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication,QVBoxLayout,QWidget

from qt_results_workspace import ResultsWorkspace,results_preview_shapes

APP=QApplication.instance() or QApplication([])


def _device():
    return dict(schema_version=1,name='Saved silicon device',width_um=2.,depth_um=2.,temperature_K=300.,
        mesh=dict(nx=4,ny=4,nz_per_layer=2,max_nodes=10000),
        layers=[dict(id='p',name='p-Si',material_id='silicon',thickness_um=.2,donor_cm3=0.,acceptor_cm3=1e17,enabled=True),
                dict(id='n',name='n-Si',material_id='silicon',thickness_um=.2,donor_cm3=1e16,acceptor_cm3=0.,enabled=True)],
        shapes=[dict(id='hole',name='Hole',layer_id='p',material_id='air',operation='void',shape='circle',cx_um=0.,cy_um=0.,size_x_um=.5,size_y_um=.5,angle_deg=0.,vertices=[],enabled=True)],
        contacts=[dict(id='ring',name='P Au ring',layer_id='p',surface='top',shape='square_ring',cx_um=0.,cy_um=0.,size_x_um=1.8,size_y_um=1.8,
                       inner_size_x_um=1.2,inner_size_y_um=1.2,angle_deg=0.,vertices=[],optical_thickness_um=.03,enabled=True),
                  dict(id='reflector',name='N Au reflector',layer_id='n',surface='bottom',shape='rectangle',cx_um=0.,cy_um=0.,size_x_um=2.,size_y_um=2.,
                       angle_deg=0.,vertices=[],optical_thickness_um=.1,enabled=True)],doping_regions=[])


def _volume(bias):
    x=np.linspace(-.75,.75,4)*1e-6;y=x.copy();z=np.array([.05,.15,.25,.35])*1e-6
    xx,yy,zz=np.meshgrid(x,y,z,indexing='ij');potential=xx*1e6+zz*2e6+bias
    return dict(x=x,y=y,z=z,potential=potential,field_V_m=np.broadcast_to([1e6,2e6,2e6],potential.shape+(3,)).copy(),
                electrons_cm3=np.full(potential.shape,1e16)+zz*1e20,holes_cm3=np.full(potential.shape,1e17),charge_density_C_m3=potential*100,
                material_index=np.zeros(potential.shape,int),material_ids=np.array(['silicon']),layer_index=np.broadcast_to([0,0,1,1],potential.shape).copy(),
                layer_ids=np.array(['p','n']),solid=np.ones(potential.shape,bool),cell_volumes_m3=np.full(potential.shape,2.5e-20))


class ResultsWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='results_workspace_');self.directory=Path(self.temp.name);self.workspace=None;self.host=None
        self.summary=dict(model='custom_device',device=_device(),options=dict(device=_device()),mesh=dict(shape=[4,4,4],cells=64),elapsed_s=1.25,
            evaluated_materials=[dict(id='silicon',properties=dict(affinity_eV=4.05,bandgap_eV=1.124),sources=[dict(title='Actual saved source')])],
            limitations=['Prescribed-reservoir electrostatics'],results=[])
        for bias in (0.,-1.):
            path=self.directory/f'custom_{bias:g}V.npz';np.savez_compressed(path,**_volume(bias))
            self.summary['results'].append(dict(bias_V=bias,volume_npz=str(path),checks=dict(max_normalized_Poisson_residual=1e-11,relative_gauss_balance=1e-12)))
        (self.directory/'electrical_summary.json').write_text(json.dumps(self.summary),encoding='utf-8')
        (self.directory/'project.json').write_text(json.dumps(dict(device=_device())),encoding='utf-8')
        pd.DataFrame([dict(bias_V=bias,wavelength_nm=wave,R=.2,T=.3,A=.5) for bias in (0.,-1.) for wave in (1500.,1510.)]).to_csv(self.directory/'electrical_optical_spectra.csv',index=False)
        pd.DataFrame(dict(bias_V=[0.,-1.],shift_nm=[0.,-.5])).to_csv(self.directory/'electrical_features.csv',index=False)

    def tearDown(self):
        if self.workspace is not None:self.workspace.close();self.workspace.deleteLater()
        if self.host is not None:self.host.close();self.host.deleteLater()
        APP.processEvents();self.temp.cleanup()

    def show_workspace(self):
        self.workspace=ResultsWorkspace();self.workspace.load_run(self.directory);self.workspace.resize(1586,900);self.workspace.show();APP.processEvents();return self.workspace

    def test_reference_composition_and_actual_metric_values(self):
        workspace=self.show_workspace();workspace.set_bias(-1.);APP.processEvents()
        self.assertEqual(workspace.left_rail.width(),244);self.assertEqual(workspace.right_rail.width(),333)
        self.assertEqual(len(workspace.metric_values),5)
        self.assertEqual(workspace.metric_values['bias'].text(),'-1 V')
        self.assertEqual(workspace.metric_values['field'].text(),'3 MV/m')
        self.assertIn('cm⁻³',workspace.metric_values['electrons'].text())
        self.assertEqual(workspace.metric_values['shift'].text(),'-0.5 nm')
        self.assertGreater(workspace.field_scene.height(),workspace.top_card.height())
        self.assertGreater(workspace.field_scene.surface_sample_count,0)
        self.assertEqual(workspace.field_scene.device['contacts'][0]['optical_thickness_um'],.03)
        self.assertEqual(workspace.convergence_badge.text(),'✓  Converged')
        self.assertEqual(workspace.balance_badge.text(),'✓  Charge balanced')
        self.assertIn('Actual saved source',workspace.detail_expanders['sources'].toPlainText())

    def test_hero_tabs_and_navigation_show_actual_data_views(self):
        workspace=self.show_workspace()
        workspace.mode_buttons['Top view · XY'].click();self.assertEqual(workspace.hero_stack.currentIndex(),1)
        workspace.mode_buttons['Cross section · XZ'].click();self.assertEqual(workspace.hero_stack.currentIndex(),2)
        workspace.mode_buttons['Depth profiles'].click();self.assertEqual(workspace.hero_stack.currentIndex(),3)
        self.assertGreater(len(workspace.hero_depth.figure.axes[0].lines),0)
        workspace.mode_buttons['Optical spectra'].click();self.assertEqual(workspace.hero_stack.currentIndex(),4)
        self.assertEqual(len(workspace.hero_optical.figure.axes[0].lines),3)
        workspace.nav_buttons['Energy bands'].click();self.assertEqual(workspace.center_stack.currentIndex(),1)
        self.assertEqual(len(workspace.energy_plot.figure.axes[0].lines),2)
        workspace.nav_buttons['I–V / C–V'].click();self.assertEqual(workspace.center_stack.currentIndex(),3)
        self.assertEqual(len(workspace.iv_plot.figure.axes[0].lines),0)
        workspace.nav_buttons['Inputs & materials'].click();self.assertEqual(workspace.center_stack.currentIndex(),5)
        workspace.nav_buttons['Overview'].click();self.assertEqual(workspace.center_stack.currentIndex(),0)

    def test_probe_links_views_and_is_preserved_across_bias_states(self):
        workspace=self.show_workspace();workspace.set_probe(-.75e-6,.25e-6,.15e-6)
        before=workspace.probe['coordinates_m'];workspace.set_bias(-1.)
        np.testing.assert_allclose(workspace.probe['coordinates_m'],before)
        self.assertEqual(workspace.probe_values['potential'].text(),_format(workspace.probe['values']['potential']))
        self.assertEqual(workspace.top_view.crosshair,tuple(before[:2]))
        self.assertEqual(workspace.hero_top.crosshair,tuple(before[:2]))
        self.assertEqual(workspace.field_scene.cursor,tuple(before))
        rect=workspace.top_view._plot_bounds()
        self.assertAlmostEqual(rect.width()/rect.height(),1.)

    def test_initial_probe_uses_saved_solid_sample_and_manual_air_probe_stays_raw(self):
        volume=_volume(0.)
        volume['solid'][1:3,1:3,0]=False
        volume['electrons_cm3'][1:3,1:3,0]=0.
        volume['holes_cm3'][1:3,1:3,0]=0.
        volume['material_index'][1:3,1:3,0]=1
        volume['material_ids']=np.array(['silicon','air'])
        np.savez_compressed(self.summary['results'][0]['volume_npz'],**volume)
        workspace=self.show_workspace()
        self.assertTrue(workspace.probe['solid'])
        candidates=np.argwhere(volume['solid'][:,:,0])
        nearest_distance=np.min(volume['x'][candidates[:,0]]**2+volume['y'][candidates[:,1]]**2)
        x,y,z=workspace.probe['coordinates_m']
        self.assertAlmostEqual((x*x+y*y)/nearest_distance,1.)
        self.assertEqual(z,float(volume['z'][0]))
        workspace.set_probe(volume['x'][2],volume['y'][2],volume['z'][0])
        self.assertFalse(workspace.probe['solid'])
        self.assertEqual(workspace.probe['material_id'],'air')
        self.assertEqual(workspace.probe['values']['electrons_cm3'],0.)
        self.assertEqual(workspace.probe['values']['holes_cm3'],0.)

    def test_zero_bias_comparison_uses_saved_curve_samples(self):
        workspace=self.show_workspace();workspace.set_bias(-1.);workspace.compare_zero.setChecked(True)
        self.assertEqual(len(workspace.rta_plot.figure.axes[0].lines),6)
        self.assertEqual(len(workspace.depth_plot.figure.axes[0].lines),4)
        self.assertEqual(len(workspace.depth_plot.figure.axes[1].lines),2)
        self.assertEqual(len(workspace.depth_legend.lines),6)
        self.assertEqual(len(workspace.rta_legend.lines),6)
        for item in set(workspace.depth_plot.canvas.plots.values()):
            if item.legend is not None:self.assertFalse(item.legend.isVisible())
        lines=workspace.rta_plot.figure.axes[0].lines
        np.testing.assert_allclose(lines[0].get_ydata(),[.2,.2])
        np.testing.assert_allclose(lines[3].get_ydata(),[.2,.2])

    def test_optical_only_keeps_geometry_rta_and_clears_electrical_probe(self):
        workspace=self.show_workspace()
        optical=self.directory/'optical';optical.mkdir()
        (optical/'project.json').write_text(json.dumps(dict(device=_device())),encoding='utf-8')
        pd.DataFrame(dict(wavelength_nm=[1500,1510],R=[.1,.2],T=[.3,.2],A=[.6,.6])).to_csv(optical/'results.csv',index=False)
        workspace.load_run(optical);APP.processEvents()
        self.assertIsNone(workspace.volume);self.assertEqual(workspace.scene_stack.currentIndex(),1)
        self.assertEqual(workspace.geometry_scene.device['name'],'Saved silicon device')
        self.assertEqual(workspace.metric_values['field'].text(),'—')
        self.assertEqual(workspace.probe_values['potential'].text(),'—')
        self.assertFalse(workspace.quantity.isEnabled());self.assertFalse(workspace.cursor_controls['x'].isEnabled())
        self.assertEqual(len(workspace.rta_plot.figure.axes[0].lines),3)
        boundary=json.loads(workspace.detail_expanders['boundary'].toPlainText())
        self.assertEqual(boundary['contacts'],_device()['contacts'])
        self.assertIn('ideal electrical contacts',boundary['contact_scope'])
        self.assertEqual(json.loads(workspace.inputs.toPlainText())['device']['shape_count'],1)
        self.assertIn('#12283a',workspace.convergence_badge.styleSheet())

    def test_inherited_exports_and_saved_run_selection_are_usable(self):
        workspace=self.show_workspace();workspace.set_saved_runs([dict(directory=str(self.directory),title='Saved physical device',status='complete')])
        self.assertEqual(workspace.saved_run_list.count(),1)
        workspace.set_bias(-1.);workspace.export_file(self.directory/'exported.npz','npz')
        with np.load(self.directory/'exported.npz',allow_pickle=False) as loaded:np.testing.assert_array_equal(loaded['potential'],_volume(-1.)['potential'])
        workspace.export_file(self.directory/'exported.vtk','vtk')
        self.assertIn('RECTILINEAR_GRID',(self.directory/'exported.vtk').read_text())
        workspace.select_category('Optical response');workspace.export_file(self.directory/'optical.png','figure')
        self.assertGreater((self.directory/'optical.png').stat().st_size,1000)

    def test_root_can_reparent_footer_without_crushing_840_pixel_body(self):
        workspace=self.show_workspace()
        workspace.layout().removeWidget(workspace.footer_widget)
        self.host=QWidget();layout=QVBoxLayout(self.host);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        layout.addWidget(workspace,1);layout.addWidget(workspace.footer_widget)
        self.host.resize(1586,902);self.host.show();APP.processEvents()
        self.assertEqual(workspace.height(),840)
        self.assertEqual(workspace.footer_widget.height(),62)
        bottom=workspace.saved_run_list.mapTo(workspace,QPoint(0,workspace.saved_run_list.height())).y()
        top=workspace.result_bias.mapTo(workspace,QPoint(0,0)).y()
        self.assertGreater(top,bottom)
        self.assertGreater(workspace.depth_card.height(),150)
        self.assertGreater(workspace.top_card.height(),150)

    def test_smooth_display_shading_preserves_raw_probe_and_export_data(self):
        workspace=self.show_workspace();before={key:np.array(value,copy=True) for key,value in workspace.volume.items()}
        workspace.field_scene.yaw+=.2;workspace.field_scene.update();APP.processEvents()
        self.assertTrue(workspace.field_scene._texture_cache)
        self.assertLess(len(workspace.field_scene.hits),20)
        for key,value in before.items():np.testing.assert_array_equal(workspace.volume[key],value)
        workspace.set_probe(-.75e-6,.25e-6,.15e-6)
        self.assertAlmostEqual(workspace.probe['values']['potential'],before['potential'][0,2,1])
        workspace.export_file(self.directory/'smooth-display-raw.npz','npz')
        with np.load(self.directory/'smooth-display-raw.npz',allow_pickle=False) as loaded:
            np.testing.assert_array_equal(loaded['potential'],before['potential'])

    def test_large_field_preview_samples_real_shapes_without_rewriting_geometry(self):
        from pc_array import apply_pc_array
        device=_device();device.update(width_um=150.,depth_um=150.,shapes=[])
        device=apply_pc_array(device,dict(id='large_pc',name='100 µm PC',layer_id='p',width_um=100.,depth_um=100.,cx_um=0.,cy_um=0.,
            cell_width_um=.45,cell_depth_um=.45,radius_um=.09))
        self.assertEqual(len(device['shapes']),49284)
        selected,total=results_preview_shapes(device,'p')
        self.assertEqual(total,49284);self.assertLessEqual(len(selected),256)
        originals={obj['id']:obj for obj in device['shapes']}
        self.assertTrue(all(obj is originals[obj['id']] for obj in selected))
        self.assertEqual(device['pc_arrays'][0]['hole_count'],49284)
        workspace=self.show_workspace();workspace.summary['device']=device
        before=np.array(workspace.volume['potential'],copy=True)
        workspace.redraw();APP.processEvents()
        self.assertEqual(workspace.field_scene.total_shape_count,49284)
        self.assertLessEqual(workspace.field_scene.preview_shape_count,256)
        self.assertLessEqual(workspace.top_view.preview_shape_count,256)
        self.assertEqual(len(workspace.summary['device']['shapes']),49284)
        np.testing.assert_array_equal(workspace.volume['potential'],before)

    def test_large_optical_only_document_loads_and_renders_with_explicit_lod(self):
        from pc_array import apply_pc_array
        device=_device();device.update(width_um=150.,depth_um=150.,shapes=[])
        device=apply_pc_array(device,dict(id='large_pc',name='100 µm PC',layer_id='p',width_um=100.,depth_um=100.,cx_um=0.,cy_um=0.,
            cell_width_um=.45,cell_depth_um=.45,radius_um=.09))
        folder=self.directory/'large-optical';folder.mkdir()
        (folder/'project.json').write_text(json.dumps(dict(device=device,settings=dict(optical_unit_cell=dict(enabled=True,width_um=.45,depth_um=.45)))),encoding='utf-8')
        pd.DataFrame(dict(wavelength_nm=[1530.,1540.,1550.],R=[.9,.88,.85],T=[.0001,.00014,.00018],A=[.0999,.11986,.14982])).to_csv(folder/'results.csv',index=False)
        self.workspace=ResultsWorkspace();started=time.perf_counter();self.workspace.load_run(folder)
        self.workspace.resize(1586,900);self.workspace.show()
        self.workspace.select_category('Overview')
        APP.processEvents();self.workspace.grab()
        elapsed=time.perf_counter()-started
        self.assertLess(elapsed,6.,'Large optical-only preview should use bounded display geometry.')
        self.assertEqual(len(self.workspace.saved_project['device']['shapes']),49284)
        self.assertEqual(len(self.workspace.geometry_scene.device['shapes']),49284)
        self.assertLessEqual(len(self.workspace.geometry_scene._render_shapes),240)
        self.assertIn('49,284',self.workspace.geometry_scene.lod_note)
        self.assertIn('49,284',self.workspace.info_label.text())
        originals={obj['id'] for obj in device['shapes']}
        self.assertTrue(all(obj['id'] in originals for obj in self.workspace.geometry_scene._render_shapes))
        self.assertEqual(len(self.workspace.rta_legend.lines),3)
        self.assertIsNone(self.workspace.volume)
        inputs=json.loads(self.workspace.inputs.toPlainText())
        self.assertEqual(inputs['device']['shape_count'],49284)
        self.assertNotIn('shapes',inputs['device'])
        self.assertNotIn('shape_ids',inputs['device']['pc_arrays'][0])
        self.assertIn('project.json',inputs['complete_saved_project'])

    def test_studio_lighting_preserves_saved_colormap_textures_and_probe_values(self):
        workspace=self.show_workspace();scene=workspace.field_scene
        before={key:np.array(value,copy=True) for key,value in workspace.volume.items()}
        studio=scene.grab().toImage();studio_bytes=studio.constBits().asstring(studio.sizeInBytes())
        textures={key:image.constBits().asstring(image.sizeInBytes()) for key,image in scene._texture_cache.items()}
        limits=(scene.colors.low,scene.colors.high,scene.colors.logarithmic)
        scene.set_render_quality('flat',shadows=False,reflections=False,ambient_occlusion=False);APP.processEvents()
        flat=scene.grab().toImage()
        self.assertNotEqual(studio_bytes,flat.constBits().asstring(flat.sizeInBytes()))
        self.assertEqual(limits,(scene.colors.low,scene.colors.high,scene.colors.logarithmic))
        for key,image in scene._texture_cache.items():self.assertEqual(textures[key],image.constBits().asstring(image.sizeInBytes()))
        for key,value in before.items():np.testing.assert_array_equal(value,workspace.volume[key])
        workspace.set_probe(-.75e-6,.25e-6,.15e-6)
        self.assertAlmostEqual(workspace.probe['values']['potential'],before['potential'][0,2,1])


def _format(value):
    return f'{value:.5g}'


if __name__=='__main__':unittest.main()
