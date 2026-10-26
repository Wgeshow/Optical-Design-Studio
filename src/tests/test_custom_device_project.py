"""Canonical finite-device integration through the real desktop project store."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
_imports=tempfile.TemporaryDirectory(prefix='ods_device_project_import_',dir=Path.cwd())
os.environ.setdefault('S4_LIBRARY_ROOT',_imports.name)

import numpy as np
from PyQt6.QtWidgets import QApplication

from data_library import DataLibrary, read_json
from device_model import default_device, geometry_vertices, shape_mask
from device_project_bridge import optical_structure, sync_from_optical
from electrical_material_library import builtin_materials
from model import MAT_COLS, PAT_COLS, prepare
from qt_core import ProjectStore, prepare_job
from structure_builder import validate_structure

APP=QApplication.instance() or QApplication([])


def user_device():
    device=default_device()
    device.update(name='Editable silicon photonic device',width_um=2.,depth_um=2.)
    device['layers']=[dict(id='p',name='User patterned P silicon',material_id='silicon',
        thickness_um=.24,donor_cm3=0.,acceptor_cm3=1e17,enabled=True),
        dict(id='n',name='User N silicon film',material_id='silicon',
             thickness_um=.32,donor_cm3=2e17,acceptor_cm3=0.,enabled=True)]
    device['mesh'].update(nx=8,ny=8,nz_per_layer=8)
    device['contacts'][0].update(layer_id='n',name='N connection to Au reflector',surface='bottom')
    device['contacts'][1].update(layer_id='p',name='Connected top P metal ring',surface='top',
        shape='square_ring',inner_size_x_um=1.2,inner_size_y_um=1.2)
    device['shapes']=[dict(id='void_polygon',name='Edited polygon aperture',layer_id='p',material_id='air',
        operation='void',shape='polygon',cx_um=.12,cy_um=-.07,angle_deg=25.,size_x_um=.35,size_y_um=.3,
        vertices=[[-.17,-.14],[.18,-.14],[.07,.16]],enabled=True)]
    device['doping_regions']=[dict(id='local_donor',name='N implant',layer_id='n',donor_cm3=3e18,acceptor_cm3=0.,
        shape='rectangle',cx_um=.3,cy_um=0.,size_x_um=.5,size_y_um=.6,angle_deg=10.,vertices=[],enabled=True)]
    return device


class CustomDeviceProjectTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.directory.cleanup)
        self.library=DataLibrary(Path(self.directory.name)/'library')
        self.store=ProjectStore(self.library,restore=False)
        # Keep optics independent of uploaded tables and use a bounded sweep.
        self.store.update_settings(dict(NumG=9,wl_start_nm=1500.,wl_stop_nm=1600.,wl_step_nm=50.))
        self.store.update_performance(dict(mode='CPU only',workers=1,threads=1,require_gpu=False))

    def install(self):
        self.store.set_device(user_device())
        return self.store.project()

    def test_save_load_preserves_canonical_geometry_doping_ring_and_material_edits(self):
        library=copy.deepcopy(self.store.electrical_materials)
        silicon=next(row for row in library if row['id']=='silicon')
        silicon['properties'].update(electron_mobility_cm2_Vs=820.,affinity_eV=4.12)
        self.store.set_electrical_materials(library)
        self.install()
        path=Path(self.directory.name)/'portable_device.json'
        self.store.save_project(path)
        saved=read_json(path)
        self.assertEqual(saved['device'],self.store.device)
        self.assertEqual(saved['electrical_materials'],self.store.electrical_materials)
        other=ProjectStore(DataLibrary(Path(self.directory.name)/'elsewhere'),restore=False)
        other.load_project(path)
        self.assertEqual(other.device,self.store.device)
        self.assertEqual(other.electrical_materials,self.store.electrical_materials)
        self.assertEqual(other.device['contacts'][1]['shape'],'square_ring')
        self.assertEqual(other.device['contacts'][0]['name'],'N connection to Au reflector')
        self.assertFalse(any('ROIC' in obj['name'] for obj in other.device['layers']))
        self.assertAlmostEqual(float(other.layers.iloc[1]['Thickness_um']),.24)

    def test_device_undo_restores_all_linked_optical_and_electrical_geometry(self):
        self.install()
        before=self.store.project()
        changed=copy.deepcopy(self.store.device)
        changed['layers'][0]['thickness_um']=.41
        changed['shapes'][0].update(cx_um=.31,angle_deg=60.)
        changed['contacts'][1]['inner_size_x_um']=1.5
        changed['doping_regions'][0]['donor_cm3']=8e18
        self.store.set_device(changed)
        self.assertEqual(float(self.store.layers.iloc[1]['Thickness_um']),.41)
        self.store.undo()
        after=self.store.project()
        for key in ('device','electrical_materials','materials','layers','patterns','settings'):
            self.assertEqual(after[key],before[key])

    def test_material_undo_restores_the_material_edit_without_reverting_device_geometry(self):
        self.install()
        before=self.store.project()
        library=copy.deepcopy(self.store.electrical_materials)
        next(row for row in library if row['id']=='silicon')['properties']['epsilon_r']=13.2
        self.store.set_electrical_materials(library)
        self.store.undo()
        self.assertEqual(self.store.electrical_materials,before['electrical_materials'])
        self.assertEqual(self.store.device,before['device'])
        self.assertEqual(self.store.project()['layers'],before['layers'])

    def test_electrical_only_uses_canonical_device_without_optical_assignments(self):
        library=copy.deepcopy(self.store.electrical_materials)
        custom=copy.deepcopy(next(row for row in library if row['id']=='silicon'))
        custom.update(id='custom_electrical',name='Unmapped electrical sample',model='constant')
        custom.pop('optical_material_name',None)
        custom['properties'].pop('optical_n',None);custom['properties'].pop('optical_k',None)
        library.append(custom);self.store.set_electrical_materials(library)
        device=user_device()
        for layer in device['layers']:layer['material_id']='custom_electrical'
        self.store.set_device(device)
        project=self.store.project()
        project['materials'][0].update(Model='table_nk',DataFile='missing_optical.csv')
        with patch('qt_core.prepare',side_effect=AssertionError('Optical preparation must not run')):
            _,job=prepare_job('electrical',project,dict(model='custom_device',optical_enabled=False,
                charge_model='dielectric',biases_V=[0.,-1.],device=default_device()),self.library)
        self.assertIsNone(job['model'])
        self.assertEqual(job['search']['device'],self.store.device)
        self.assertEqual(job['search']['material_library'],self.store.electrical_materials)

    def test_optical_and_coupled_reject_unassigned_optical_material(self):
        library=copy.deepcopy(self.store.electrical_materials)
        custom=copy.deepcopy(next(row for row in library if row['id']=='silicon'))
        custom.update(id='custom_electrical',name='Sample requiring measured n/k',model='constant')
        custom.pop('optical_material_name',None)
        custom['properties'].pop('optical_n',None);custom['properties'].pop('optical_k',None)
        library.append(custom);self.store.set_electrical_materials(library)
        device=user_device();device['layers'][0]['material_id']='custom_electrical'
        self.store.set_device(device)
        for kind,options in [('simulation',{}),('coupled',dict(model='custom_device',reference_nm=1550.,tracking_window_nm=50.,charge_model='dielectric'))]:
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'Assign optical n/k'):
                prepare_job(kind,self.store.project(),options,self.library)

    def test_coupled_job_consumes_edited_layers_and_transformed_polygon(self):
        library=copy.deepcopy(self.store.electrical_materials)
        next(row for row in library if row['id']=='silicon')['properties'].update(optical_n=3.48,optical_k=.01)
        self.store.set_electrical_materials(library)
        self.install()
        device=copy.deepcopy(self.store.device)
        device['layers'][0]['thickness_um']=.37
        device['shapes'][0].update(cx_um=.24,cy_um=.11,angle_deg=75.)
        self.store.set_device(device)
        _,job=prepare_job('coupled',self.store.project(),dict(model='custom_device',
            reference_nm=1550.,tracking_window_nm=50.,charge_model='dielectric',biases_V=[0.,-.2]),self.library)
        self.assertTrue(job['search']['optical_enabled'])
        self.assertEqual(job['search']['device'],self.store.device)
        self.assertAlmostEqual(job['model']['layers'][1]['thickness'],.37)
        pattern=next(row for row in job['model']['patterns'] if row['shape']=='polygon')
        np.testing.assert_allclose(pattern['vertices'],geometry_vertices(self.store.device['shapes'][0]),atol=1e-14)

    def test_rotated_ring_regions_bridge_to_exact_valid_optical_rectangles(self):
        device=user_device()
        ring=dict(device['shapes'][0],id='region_ring',name='Ring void',shape='square_ring',cx_um=.1,cy_um=-.1,
            angle_deg=31.,size_x_um=1.4,size_y_um=1.1,inner_size_x_um=.8,inner_size_y_um=.5,vertices=[])
        device['shapes']=[ring]
        self.store.set_device(device)
        project=self.store.project()
        self.assertEqual(len(project['patterns']),4)
        self.assertTrue(all(row['Shape']=='rectangle' for row in project['patterns']))
        validate_structure(project['materials'],project['layers'],project['patterns'])
        points=np.random.default_rng(17).uniform(-1.,1.,(500,2))
        decomposed=np.zeros(len(points),bool)
        for row in project['patterns']:
            bar=dict(shape='rectangle',cx_um=row['CenterX_um'],cy_um=row['CenterY_um'],
                size_x_um=row['SizeX_um'],size_y_um=row['SizeY_um'],angle_deg=row['Angle_deg'])
            decomposed |= shape_mask(bar,points[:,0],points[:,1])
        np.testing.assert_array_equal(decomposed,shape_mask(ring,points[:,0],points[:,1]))
        fresh=sync_from_optical(project,self.store.electrical_materials,self.store.device)
        self.assertEqual(fresh['shapes'],self.store.device['shapes'])
        # An explicit legacy edit to one bar becomes four physical rectangles.
        project['patterns'][0]['CenterX_um']+=.1
        fresh=sync_from_optical(project,self.store.electrical_materials,self.store.device)
        self.assertEqual(len(fresh['shapes']),4)
        self.assertTrue(all(row['shape']=='rectangle' for row in fresh['shapes']))

    def test_legacy_thickness_edit_preserves_unassigned_electrical_material_and_ring(self):
        device=user_device()
        ring=dict(device['shapes'][0],id='solid_ring',name='Silicon ring',shape='square_ring',material_id='silicon',operation='material',
            size_x_um=1.4,size_y_um=1.1,inner_size_x_um=.8,inner_size_y_um=.5,vertices=[])
        device['shapes']=[ring]
        self.store.set_device(device)
        project=self.store.project()
        self.assertTrue(project['layers'][1]['Material'].startswith('__optical_unassigned_'))
        project['layers'][1]['Thickness_um']=.4
        fresh=sync_from_optical(project,self.store.electrical_materials,self.store.device)
        self.assertEqual(fresh['layers'][0]['material_id'],'silicon')
        self.assertEqual(fresh['layers'][0]['thickness_um'],.4)
        self.assertEqual(fresh['shapes'],self.store.device['shapes'])

    def test_duplicate_editor_layer_names_couple_by_stable_identity(self):
        library=copy.deepcopy(self.store.electrical_materials)
        next(row for row in library if row['id']=='silicon')['properties'].update(optical_n=3.48,optical_k=.01)
        self.store.set_electrical_materials(library)
        device=user_device()
        for layer in device['layers']:layer['name']='Repeated silicon layer'
        self.store.set_device(device)
        _,job=prepare_job('coupled',self.store.project(),dict(model='custom_device',
            reference_nm=1550.,tracking_window_nm=50.,charge_model='dielectric'),self.library)
        self.assertEqual(job['search']['optical_mapping']['p']['layer'],'Repeated silicon layer')
        self.assertEqual(job['search']['optical_mapping']['n']['layer'],'Repeated silicon layer_2')
        self.assertEqual([row['device_layer_id'] for row in job['model']['layers'][1:-1]],['p','n'])

    def _install_named_hole_array(self):
        device=user_device()
        prototype=dict(device['shapes'][0],shape='circle',cx_um=0.,cy_um=0.,angle_deg=0.,
                       size_x_um=.18,size_y_um=.18,vertices=[])
        device['shapes']=[dict(prototype,id=f'hole_{i}_{j}',name=f'PCS hole [{i}, {j}]',
                              cx_um=(i-1)*.45,cy_um=(j-1)*.45)
                          for i in range(3) for j in range(3)]
        for index,shape in enumerate(('rectangle','ellipse')):
            device['shapes'].append(dict(prototype,id='named_'+shape,name='Custom '+shape,
                                        shape=shape,cx_um=.65,cy_um=.1*index,
                                        size_x_um=.2,size_y_um=.15,angle_deg=17.))
        self.store.set_device(device)
        return copy.deepcopy(self.store.device['shapes'])

    def test_material_addition_preserves_editor_shape_names_and_ids(self):
        before=self._install_named_hole_array()
        project=self.store.project()
        project['materials'].append(dict(Name='Au',Model='constant_nk',A=.3,B=7.,DataFile='',WavelengthUnit='nm'))
        # This is the same store mutation used by Materials' Add preset action.
        self.store.set_structure(project['materials'],project['layers'],project['patterns'],reason='materials')
        self.assertEqual([(row['id'],row['name']) for row in self.store.device['shapes']],
                         [(row['id'],row['name']) for row in before])
        for original,imported in zip(before,self.store.device['shapes']):
            for key in ('shape','layer_id','cx_um','cy_um','size_x_um','size_y_um','angle_deg'):
                self.assertEqual(imported[key],original[key])

    def test_optical_pattern_assignment_updates_material_without_resetting_identity(self):
        before=self._install_named_hole_array()
        project=self.store.project()
        if not any(row['Name']=='GaAs' for row in project['materials']):
            project['materials'].append(dict(Name='GaAs',Model='constant_nk',A=3.4,B=.01,DataFile='',WavelengthUnit='nm'))
        project['patterns'][0]['Material']='GaAs'
        self.store.set_structure(project['materials'],project['layers'],project['patterns'],reason='materials')
        changed=self.store.device['shapes'][0]
        self.assertEqual((changed['id'],changed['name']),(before[0]['id'],before[0]['name']))
        self.assertEqual(changed['material_id'],'gaas')
        self.assertEqual(changed['optical_material_name'],'GaAs')
        self.assertEqual(changed['operation'],'material')
        self.assertEqual([(row['id'],row['name']) for row in self.store.device['shapes'][1:]],
                         [(row['id'],row['name']) for row in before[1:]])

    def test_circle_identity_ignores_disabled_y_and_rotation_fields(self):
        self._install_named_hole_array()
        device=copy.deepcopy(self.store.device)
        for hole in device['shapes'][:9]:
            hole.update(size_x_um=.18,size_y_um=.174,angle_deg=37.)
        self.store.set_device(device)
        before=copy.deepcopy(self.store.device['shapes'])
        project=self.store.project()
        project['materials'].append(dict(Name='Au',Model='constant_nk',A=.3,B=7.,DataFile='',WavelengthUnit='nm'))
        # A circle has no physical rotation. An optical editor may normalize it.
        for row in project['patterns'][:9]:row['Angle_deg']=0.
        self.store.set_structure(project['materials'],project['layers'],project['patterns'],reason='materials')
        self.assertEqual([(row['id'],row['name']) for row in self.store.device['shapes']],
                         [(row['id'],row['name']) for row in before])
        for hole in self.store.device['shapes'][:9]:
            self.assertEqual(hole['size_x_um'],.18)
            self.assertEqual(hole['size_y_um'],.18)
            self.assertEqual(hole['angle_deg'],0.)

    def test_legacy_geometry_edits_and_deletions_do_not_restore_old_shapes(self):
        before=self._install_named_hole_array()
        project=self.store.project()
        project['patterns'][0]['SizeX_um']=.13
        del project['patterns'][1]
        self.store.set_structure(project['materials'],project['layers'],project['patterns'])
        shapes=self.store.device['shapes']
        self.assertEqual(len(shapes),len(before)-1)
        self.assertAlmostEqual(shapes[0]['size_x_um'],.26)
        self.assertAlmostEqual(shapes[0]['size_y_um'],.26)
        self.assertNotEqual(shapes[0]['id'],before[0]['id'])
        self.assertNotIn(before[1]['id'],{row['id'] for row in shapes})
        self.assertEqual([(row['id'],row['name']) for row in shapes[1:]],
                         [(row['id'],row['name']) for row in before[2:]])


if __name__=='__main__':unittest.main()
