"""Synthetic bridge/store regressions; no native app or scientific solver run."""
import copy,json,os,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary,read_json
from device_model import default_device,remove_object,validate_device
from device_project_bridge import optical_structure,sync_from_optical
from pc_array import apply_pc_array
from qt_core import ProjectStore

APP=QApplication.instance() or QApplication([])

def slab_device():
 d=default_device();d.update(name='Synthetic disabled-object regression',width_um=2.94,depth_um=2.94)
 d['layers']=[dict(id='slab',name='Synthetic slab',material_id='gaas',thickness_um=.2695,donor_cm3=0.,acceptor_cm3=0.,enabled=True)]
 d['shapes']=[];d['contacts']=[];d['doping_regions']=[];return d

def shape(identity,kind='circle',enabled=False,layer='slab',**changes):
 d=dict(id=identity,name='Editable '+identity,layer_id=layer,material_id='air',operation='void',shape=kind,cx_um=.1,cy_um=.2,size_x_um=.4,size_y_um=.3,angle_deg=12.,vertices=[],enabled=enabled)
 if kind=='square_ring':d.update(size_x_um=.8,size_y_um=.7,inner_size_x_um=.3,inner_size_y_um=.2)
 if kind=='polygon':d.update(vertices=[[-.1,-.1],[.1,-.1],[0,.1]])
 d.update(changes);return d

def array_device():
 d=apply_pc_array(slab_device(),dict(id='pc_synthetic',name='Synthetic six by six',layer_id='slab',cx_um=0.,cy_um=0.,width_um=2.94,depth_um=2.94,cell_width_um=.49,cell_depth_um=.49,radius_um=.196))
 for i in (14,15,20):d['shapes'][i]['enabled']=False
 return d

class DisabledShapeBridgeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('ODS_TEST_TMPDIR'));self.addCleanup(self.temp.cleanup)
  self.library=DataLibrary(Path(self.temp.name)/'library');self.store=ProjectStore(self.library,restore=False)
 def install_types(self):
  d=slab_device();d['shapes']=[shape('disabled_'+k,k) for k in ['circle','ellipse','rectangle','square_ring','polygon']]+[shape('active','circle',True,cx_um=-.5)]
  self.store.set_device(d);return copy.deepcopy(self.store.device)
 def material_edit(self):
  mats=self.store.materials.copy(deep=True)
  mats.loc[len(mats)]=dict(Name='Synthetic_n3p5',Model='constant_nk',A=3.5,B=0.,DataFile='',WavelengthUnit='nm')
  self.store.set_structure(mats,self.store.layers.copy(deep=True),self.store.patterns.copy(deep=True),'materials')
 def test_optical_material_table_edit_keeps_all_disabled_shape_types(self):
  before=self.install_types();self.material_edit()
  self.assertEqual({x['id'] for x in before['shapes']},{x['id'] for x in self.store.device['shapes']})
  self.assertEqual([x['id'] for x in before['shapes']],[x['id'] for x in self.store.device['shapes']])
  for x in before['shapes']:
   if not x['enabled']:self.assertEqual(x,next(y for y in self.store.device['shapes'] if y['id']==x['id']))
 def test_store_sequence_preserves_six_by_six_disabled_holes(self):
  self.store.activate_study('fdtd');self.store.set_device(array_device());before=copy.deepcopy(self.store.device)
  self.assertEqual(len(before['shapes']),36);self.material_edit()
  self.assertEqual(len(self.store.device['shapes']),36)
  changed=copy.deepcopy(self.store.device);changed['layers'][0]['optical_material_name']='Synthetic_n3p5';self.store.set_device(changed)
  self.assertEqual({x['id'] for x in before['shapes']},{x['id'] for x in self.store.device['shapes']})
  self.assertEqual(sum(not x['enabled'] for x in self.store.device['shapes']),3)
  self.assertEqual(len(self.store.project()['patterns']),33)
 def test_disabled_array_members_retain_metadata_and_cells(self):
  self.store.set_device(array_device());before=copy.deepcopy(self.store.device);self.material_edit()
  self.assertEqual(self.store.device['pc_arrays'],before['pc_arrays'])
  self.assertEqual({x['id']:x.get('pc_cell') for x in self.store.device['shapes']},{x['id']:x.get('pc_cell') for x in before['shapes']})
 def test_repeated_sync_is_lossless_without_disabled_duplicates(self):
  before=self.install_types();self.material_edit();self.material_edit_again()
  self.assertEqual(len(self.store.device['shapes']),len(before['shapes']))
  self.assertEqual(len({x['id'] for x in self.store.device['shapes']}),len(before['shapes']))
 def material_edit_again(self):
  self.store.set_structure(self.store.materials.copy(deep=True),self.store.layers.copy(deep=True),self.store.patterns.copy(deep=True),'materials')
 def test_coincident_active_objects_do_not_claim_disabled_identity(self):
  d=slab_device();d['shapes']=[shape('hidden'),shape('hidden_twin'),shape('one',enabled=True),shape('two',enabled=True)]
  self.store.set_device(d);self.material_edit()
  actual={x['id']:x for x in self.store.device['shapes']}
  self.assertEqual(set(actual),{'hidden','hidden_twin','one','two'});self.assertFalse(actual['hidden']['enabled'])
  self.assertEqual(sum(x['enabled'] for x in actual.values()),2)
 def test_explicit_canonical_deletion_stays_deleted(self):
  self.install_types();self.store.set_device(remove_object(self.store.device,'disabled_circle'));self.material_edit()
  self.assertNotIn('disabled_circle',{x['id'] for x in self.store.device['shapes']})
 def test_optical_pattern_deletion_does_not_restore_active_object(self):
  before=self.install_types();project=self.store.project();project['patterns']=[]
  fresh=sync_from_optical(project,self.store.electrical_materials,before)
  self.assertNotIn('active',{x['id'] for x in fresh['shapes']})
  self.assertEqual(len(fresh['shapes']),5)
 def test_changed_active_geometry_does_not_restore_prior_active_shape(self):
  before=self.install_types();project=self.store.project();project['patterns'][0]['CenterX_um']+=.1
  fresh=sync_from_optical(project,self.store.electrical_materials,before)
  self.assertNotIn('active',{x['id'] for x in fresh['shapes']});self.assertEqual(len(fresh['shapes']),6)
  self.assertAlmostEqual(next(x for x in fresh['shapes'] if x['enabled'])['cx_um'],-.4)
 def test_removed_parent_discards_its_disabled_shapes(self):
  d=slab_device();d['layers'].append(dict(d['layers'][0],id='other',name='Other slab'))
  d['shapes']=[shape('gone'),shape('kept',layer='other')];self.store.set_device(d);previous=copy.deepcopy(self.store.device);p=self.store.project()
  p['layers']=[x for x in p['layers'] if x['Name']!='Synthetic slab']
  fresh=sync_from_optical(p,self.store.electrical_materials,previous)
  self.assertEqual([x['id'] for x in fresh['shapes']],['kept'])
 def test_active_array_edit_drops_metadata_without_resurrecting_old_member(self):
  self.store.set_device(array_device());previous=copy.deepcopy(self.store.device);p=self.store.project()
  old=next(x for x in previous['shapes'] if x['enabled']);p['patterns'][0]['CenterX_um']+=.01
  fresh=sync_from_optical(p,self.store.electrical_materials,previous)
  self.assertNotIn(old['id'],{x['id'] for x in fresh['shapes']});self.assertEqual(fresh['pc_arrays'],[])
  self.assertEqual(sum(not x['enabled'] for x in fresh['shapes']),3)
 def test_material_undo_and_autosave_restore_keep_disabled_objects(self):
  before=self.install_types();self.material_edit();self.store.undo()
  self.assertEqual({x['id'] for x in self.store.device['shapes']},{x['id'] for x in before['shapes']})
  self.material_edit();saved=read_json(self.store.session_path)
  self.assertEqual(saved['device']['shapes'],self.store.device['shapes'])
  other=ProjectStore(self.library,restore=True);self.assertEqual(other.device['shapes'],self.store.device['shapes'])
 def test_disabled_retention_does_not_change_enabled_optical_projection(self):
  self.install_types();before=self.store.project();self.material_edit();after=self.store.project()
  self.assertEqual(before['layers'],after['layers']);self.assertEqual(before['patterns'],after['patterns'])
  snapshot=copy.deepcopy(self.store.device);snapshot['shapes']=[x for x in snapshot['shapes'] if x['enabled']]
  a=optical_structure(self.store.device,self.store.electrical_materials,after)
  b=optical_structure(snapshot,self.store.electrical_materials,after)
  self.assertEqual(a,b)
 def test_explicit_active_optical_reorder_remains_authoritative(self):
  d=slab_device();d['shapes']=[shape('first',enabled=True,cx_um=-.5),shape('hidden'),shape('last',enabled=True,cx_um=.5)]
  self.store.set_device(d);p=self.store.project();p['patterns'].reverse()
  fresh=sync_from_optical(p,self.store.electrical_materials,self.store.device)
  self.assertEqual([x['id'] for x in fresh['shapes'] if x['enabled']],['last','first'])
  self.assertEqual([x['id'] for x in fresh['shapes'] if not x['enabled']],['hidden'])
 def test_fully_disabled_array_keeps_metadata_without_optical_patterns(self):
  d=array_device();d['pc_arrays'][0]['enabled']=False
  for row in d['shapes']:row['enabled']=False
  self.store.set_device(d);before=copy.deepcopy(self.store.device);self.material_edit()
  self.assertEqual(self.store.device['shapes'],before['shapes']);self.assertEqual(self.store.device['pc_arrays'],before['pc_arrays'])
  self.assertEqual(self.store.project()['patterns'],[])
 def test_reenable_after_material_edit_retains_original_object_position(self):
  before=self.install_types();self.material_edit();d=copy.deepcopy(self.store.device)
  next(x for x in d['shapes'] if x['id']=='disabled_circle')['enabled']=True;self.store.set_device(d)
  self.assertEqual([x['id'] for x in self.store.device['shapes']],[x['id'] for x in before['shapes']])
  self.assertEqual(len(self.store.project()['patterns']),2)
if __name__=='__main__':unittest.main()
