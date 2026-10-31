"""Independent geometry and finite-volume checks for editable electrical devices."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from custom_electrical_solver import build_mesh, solve
from device_model import (default_device, find_object, from_optical_project,
                          geometry_inner_vertices,geometry_vertices, layer_bounds, remove_object,
                          shape_mask, validate_device)
from electrical_material_library import builtin_materials


def footprint(ident, layer, **extra):
    result = dict(id=ident,name=ident,layer_id=layer,shape='rectangle',
                  cx_um=0.,cy_um=0.,size_x_um=2.,size_y_um=2.,angle_deg=0.,vertices=[],enabled=True)
    result.update(extra)
    return result


def planar_device(material='air'):
    d=default_device(); d['layers']=[dict(id='film',name='User film',material_id=material,
        thickness_um=.3,donor_cm3=0.,acceptor_cm3=0.,enabled=True)]
    d['contacts']=[footprint('top','film',surface='top',boundary='potential',voltage_V=-1.,bias_scale=0.),
                   footprint('bottom','film',surface='bottom',boundary='potential',voltage_V=0.,bias_scale=0.)]
    d['mesh'].update(nx=4,ny=4,nz_per_layer=12)
    return d


class DeviceDocumentTests(unittest.TestCase):
    def test_default_is_independent_editable_json_and_depth_order(self):
        d=default_device(); d['layers'][0]['thickness_um']=.08
        d['layers'][0]['name']='User top'
        result=validate_device(json.loads(json.dumps(d)),builtin_materials())
        bounds=layer_bounds(result)
        self.assertEqual(bounds[0]['name'],'User top')
        self.assertEqual(bounds[0]['z_min_um'],0.)
        self.assertAlmostEqual(bounds[0]['z_max_um'],.08)
        self.assertEqual(default_device()['layers'][0]['thickness_um'],.05)
        self.assertEqual(find_object(result,'layer_1')['name'],'User top')

    def test_optical_import_preserves_top_order_radii_and_missing_assignment(self):
        project=dict(settings=dict(ax_um=.8,ay_um=.9),layers=[
            dict(Name='Incident',Material='Air',Thickness_um=0.),
            dict(Name='Top',Material='GaAs',Thickness_um=.05),
            dict(Name='Bottom',Material='Unknown user sample',Thickness_um=.1),
            dict(Name='Exit',Material='Air',Thickness_um=0.)],patterns=[
            dict(Layer='Top',Material='Air',Shape='circle',SizeX_um=.046,SizeY_um=0.,CenterX_um=.1,CenterY_um=0.,Angle_deg=0.)])
        d=from_optical_project(project)
        self.assertEqual(d['name'],'Optical device')
        self.assertEqual(d['shapes'][0]['name'],'Circle 1')
        self.assertEqual([r['name'] for r in d['layers']],['Top','Bottom'])
        self.assertEqual(d['layers'][1]['material_id'],'')
        self.assertEqual(d['layers'][1]['optical_material_name'],'Unknown user sample')
        self.assertAlmostEqual(d['shapes'][0]['size_x_um'],.092)
        self.assertEqual(d['shapes'][0]['operation'],'void')
        with self.assertRaisesRegex(ValueError,'missing material'):
            validate_device(d,builtin_materials(),require_contacts=True)

    def test_optical_conversion_uses_plain_shape_names_without_mutating_source(self):
        project=dict(layers=[dict(Name='Authored slab',Material='GaAs',Thickness_um=.25)],
            patterns=[dict(Layer='Authored slab',Material='Air',Shape=shape,
                SizeX_um=.1,SizeY_um=.2) for shape in ('circle','ellipse','rectangle')])
        before=copy.deepcopy(project)
        device=from_optical_project(project)
        self.assertEqual([row['name'] for row in device['shapes']],['Circle 1','Ellipse 2','Rectangle 3'])
        self.assertEqual(device['layers'][0]['name'],'Authored slab')
        self.assertEqual(project,before)

    def test_disabled_layers_keep_children_and_remove_cascades(self):
        d=default_device(); d['layers'][0]['enabled']=False
        self.assertEqual(len(validate_device(d)['contacts']),2)
        self.assertEqual(len(layer_bounds(d)),5)
        deleted=remove_object(d,'layer_1')
        self.assertEqual(len(deleted['contacts']),1)
        self.assertEqual(len(d['contacts']),2)

    def test_geometry_rotation_polygon_and_circle_diameter(self):
        obj=footprint('circle','film',shape='circle',size_x_um=1.,size_y_um=.1)
        self.assertEqual(shape_mask(obj,[.49,.51,0.],[0.,0.,.49]).tolist(),[True,False,True])
        obj=footprint('ellipse','film',shape='ellipse',size_x_um=2.,size_y_um=.5,angle_deg=90.)
        self.assertEqual(shape_mask(obj,[0.,.3],[.9,0.]).tolist(),[True,False])
        obj=footprint('polygon','film',shape='polygon',vertices=[[-1.,-1.],[1.,-1.],[0.,1.]])
        self.assertEqual(shape_mask(obj,[0.,.9],[0.,.9]).tolist(),[True,False])
        self.assertEqual(geometry_vertices(obj),obj['vertices'])
        obj.update(cx_um=3.,cy_um=1.,angle_deg=90.)
        moved=geometry_vertices(obj)
        self.assertAlmostEqual(sum(p[0] for p in moved)/3,3.)
        self.assertAlmostEqual(sum(p[1] for p in moved)/3,2/3)
        self.assertTrue(shape_mask(obj,3.,1.))
        self.assertFalse(shape_mask(obj,0.,0.))

    def test_invalid_reference_mesh_and_nonfinite_are_rejected(self):
        for mutate in (lambda d:d['layers'][0].update(thickness_um=-.1),
                       lambda d:d['layers'][0].update(donor_cm3=float('nan')),
                       lambda d:d['mesh'].update(nx=256,ny=256,nz_per_layer=256,max_nodes=120000),
                       lambda d:d['contacts'][0].update(layer_id='missing')):
            d=default_device(); mutate(d)
            with self.assertRaises(ValueError):validate_device(d,builtin_materials())

    def test_square_ring_has_editable_hole_and_one_electrode_identity(self):
        d=planar_device('silicon')
        contact=d['contacts'][0]
        contact.update(shape='square_ring',inner_size_x_um=1.,inner_size_y_um=1.)
        d=validate_device(d,builtin_materials())
        mesh=build_mesh(d,builtin_materials())
        self.assertEqual(len(mesh['contacts'][0]['ids']),12)
        self.assertEqual(shape_mask(contact,[0.,.8],[0.,0.]).tolist(),[False,True])
        self.assertEqual(len(geometry_inner_vertices(contact)),4)
        invalid=copy.deepcopy(d); invalid['contacts'][0]['inner_size_x_um']=2.
        with self.assertRaisesRegex(ValueError,'smaller'):validate_device(invalid)


class EditableSolverTests(unittest.TestCase):
    def run_solve(self, d, **options):
        directory=tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        return solve(dict(device=d,material_library=builtin_materials(),biases_V=[0.],**options),directory.name)

    def test_dielectric_parallel_plate_matches_analytic_solution_and_base_voltage(self):
        d=planar_device()
        s=self.run_solve(d,charge_model='dielectric')
        row=s['results'][0]
        with np.load(row['volume_npz'],allow_pickle=False) as data:
            target=-1.+data['z']/(.3e-6)
            np.testing.assert_allclose(data['potential'],np.broadcast_to(target,data['potential'].shape),atol=2e-12)
            np.testing.assert_allclose(data['field_V_m'][...,2],-1./(.3e-6),rtol=1e-11)
            self.assertTrue(np.all(data['electrons_cm3']==0))
        self.assertLess(row['checks']['relative_gauss_balance'],1e-10)
        self.assertEqual(row['checks']['terminal_voltages_V'],{'top':-1.,'bottom':0.})
        self.assertFalse(row['checks']['semiconductor_current_predicted'])

    def test_layered_dielectric_has_continuous_displacement(self):
        d=planar_device()
        d['layers']=[dict(id='film',name='Vacuum',material_id='air',thickness_um=.1,
            donor_cm3=0.,acceptor_cm3=0.,enabled=True),
            dict(id='second',name='Second',material_id='silicon',thickness_um=.2,
                 donor_cm3=0.,acceptor_cm3=0.,enabled=True)]
        d['contacts'][1]['layer_id']='second'
        s=self.run_solve(d,charge_model='dielectric')
        with np.load(s['results'][0]['volume_npz'],allow_pickle=False) as data:
            dz=np.diff(data['z']); dphi=np.diff(data['potential'][1,1,:])
            eps=data['epsilon_r'][1,1,:]
            resist=dz/(2*eps[:-1]*eps[1:]/(eps[:-1]+eps[1:]))
            displacement=dphi/resist
            # Nonuniform cells at a layer interface use width-weighted harmonic
            # permittivity; compare the independently reconstructed true flux.
            dz_cell=np.repeat([.1e-6/12,.2e-6/12],12)
            resistance=dz_cell[:-1]/(2*eps[:-1])+dz_cell[1:]/(2*eps[1:])
            np.testing.assert_allclose(dphi/resistance,np.full(len(dphi),1./(.1e-6+.2e-6/11.7)),rtol=1e-10)

    def test_edited_gaas_and_silicon_junctions_converge_and_write_identity(self):
        for material in ('gaas','silicon'):
            d=default_device(); d['mesh'].update(nx=4,ny=4,nz_per_layer=6)
            if material=='silicon':
                d['layers']=[dict(id='p',name='User P silicon',material_id='silicon',thickness_um=.1,donor_cm3=0.,acceptor_cm3=1e17,enabled=True),
                             dict(id='n',name='User N silicon',material_id='silicon',thickness_um=.1,donor_cm3=1e17,acceptor_cm3=0.,enabled=True)]
                d['contacts'][0]['layer_id']='n'; d['contacts'][1]['layer_id']='p'
            with self.subTest(material=material):
                s=self.run_solve(d)
                self.assertLess(s['results'][0]['checks']['max_normalized_Poisson_residual'],1e-9)
                self.assertLess(s['results'][0]['checks']['relative_gauss_balance'],1e-6)
                layers=json.loads(Path(s['results'][0]['layers_json']).read_text())
                self.assertEqual(layers[0]['name'],d['layers'][0]['name'])
                self.assertEqual(layers[0]['depth_start_nm'],0.)
                with np.load(s['results'][0]['profile_npz'],allow_pickle=False) as data:
                    self.assertEqual(data['layer_name'][0],d['layers'][0]['name'])
                    self.assertTrue(np.isfinite(data['electrons_cm3']).all())

    def test_pattern_and_doping_overrides_are_resolved_not_decorative(self):
        d=planar_device('gaas'); d['contacts'][0]['size_x_um']=.5
        d['contacts'][0]['size_y_um']=.5; d['contacts'][0]['cx_um']=.25; d['contacts'][0]['cy_um']=.25
        d['shapes']=[footprint('replacement','film',material_id='silicon',operation='material',size_x_um=1.,size_y_um=1.)]
        d['doping_regions']=[footprint('donors','film',donor_cm3=2e17,acceptor_cm3=0.,size_x_um=1.,size_y_um=1.)]
        mesh=build_mesh(d,builtin_materials())
        material_id=mesh['materials'][mesh['material_index'][1,1,0]]['id']
        self.assertEqual(material_id,'silicon')
        self.assertEqual(mesh['donor_cm3'][1,1,0],2e17)
        self.assertEqual(mesh['donor_cm3'][0,0,0],0.)
        self.assertEqual(mesh['feature_cells']['replacement'],48)

    def test_buried_overlapping_and_unresolved_contacts_fail_precisely(self):
        d=default_device(); d['mesh'].update(nx=4,ny=4,nz_per_layer=4)
        d['contacts'][1]['layer_id']='layer_2'
        with self.assertRaisesRegex(ValueError,'buried'):build_mesh(d,builtin_materials())
        d=planar_device(); d['contacts'].append(dict(d['contacts'][0],id='copy',name='copy'))
        with self.assertRaisesRegex(ValueError,'overlap'):build_mesh(d,builtin_materials())
        d=planar_device(); d['contacts'][0]['size_x_um']=.001; d['contacts'][0]['size_y_um']=.001
        with self.assertRaisesRegex(ValueError,'does not intersect'):build_mesh(d,builtin_materials())

    def test_cancellation_does_not_create_results(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            with self.assertRaises(InterruptedError):
                solve(dict(device=planar_device(),charge_model='dielectric'),directory,cancelled=lambda:True)
            self.assertEqual(list(Path(directory).iterdir()),[])


if __name__=='__main__':unittest.main()
