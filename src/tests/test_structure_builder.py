import copy
import json
import shutil
import subprocess
from types import SimpleNamespace
import unittest

import gradio as gr
import pandas as pd

from model import MAT_COLS, LAYER_COLS, PAT_COLS
from structure_builder import (build_structure_builder, material_catalog, mutate_region,
                               mutate_structure, resolve_material, restore_structure, stack_view, validate_structure,
                               editor_revision_scripts)


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.m = pd.DataFrame([['Air','constant_nk',1.,0.,'','nm'],['Si','constant_nk',3.4,0.,'','nm']],columns=MAT_COLS)
        self.l = pd.DataFrame([['Top',0.,'Air'],['A',.2,'Si'],['B',.3,'Si'],['Bottom',0.,'Air']],columns=LAYER_COLS)
        self.p = pd.DataFrame([['circle','A','Air',.01,.02,.1,0.,0.],['rectangle','B','Air',0.,0.,.1,.2,30.]],columns=PAT_COLS)
        saved = dict(Name='AlGaAs',Model='table_nk',A=None,B=None,DataFile='nk_saved.csv',WavelengthUnit='nm')
        self.app = SimpleNamespace(PRESETS={'Si sample':['Si','constant_nk',3.6,0.,'','nm'], 'Air / Vacuum':['Air','constant_nk',1.,0.,'','nm']},
                                   LIBRARY=SimpleNamespace(presets=lambda: {'Alloy':dict(project=dict(materials=[saved]))}),
                                   DEFAULT_MATERIALS=self.m,DEFAULT_LAYERS=self.l,DEFAULT_PATTERNS=self.p)

    def edit(self,action,selected='A',**values):
        return mutate_structure(self.app,self.m,self.l,self.p,selected,action,**values)

    def test_apply_renames_only_selected_layer_and_its_regions(self):
        m,l,p,s,before=self.edit('apply',name='Cavity',material='current:Si',thickness=350,unit='nm')
        self.assertEqual(s,'Cavity')
        self.assertAlmostEqual(l.iloc[1].Thickness_um,.35)
        self.assertEqual(list(p.Layer),['Cavity','B'])
        self.assertEqual(list(self.l.Name),['Top','A','B','Bottom'])
        self.assertEqual(before['layers'][1]['Name'],'A')

    def test_duplicate_remaps_regions_preserves_geometry(self):
        _,l,p,s,_=self.edit('duplicate')
        self.assertEqual(list(l.Name),['Top','A','A_copy','B','Bottom'])
        self.assertEqual(s,'A_copy')
        original=p.iloc[0].to_dict(); duplicate=p.iloc[-1].to_dict()
        duplicate['Layer']='A'
        self.assertEqual(original,duplicate)

    def test_repeat_preserves_block_order_and_every_region(self):
        _,l,p,s,_=self.edit('repeat',start='A',end='B',count=3)
        self.assertEqual(len(l),10)
        self.assertEqual(len(p),8)
        self.assertEqual(list(l.Name)[1:-1],['A','B','A_copy','B_copy','A_copy_2','B_copy_2','A_copy_3','B_copy_3'])
        self.assertEqual(s,'A_copy')
        validate_structure(self.m,l,p)

    def test_large_stack_has_unique_layers_and_all_pattern_references(self):
        _,l,p,_,_=self.edit('repeat',start='A',end='B',count=49)
        self.assertEqual(len(l),102)
        self.assertEqual(len(p),100)
        self.assertEqual(l.iloc[0].Name,'Top')
        self.assertEqual(l.iloc[-1].Name,'Bottom')
        self.assertEqual(len(set(l.Name)),102)
        self.assertEqual(set(p.Layer),set(l.Name[1:-1]))
        self.assertAlmostEqual(l.Thickness_um.sum(),25.)
        validate_structure(self.m,l,p)

    def test_undo_retains_imported_materials_and_rejects_project_switch(self):
        m,l,p,_,snapshot=self.edit('duplicate')
        restored_l,restored_p=restore_structure(m,l,p,snapshot)
        pd.testing.assert_frame_equal(restored_l,self.l)
        pd.testing.assert_frame_equal(restored_p,self.p)
        edited=l.copy(); edited.loc[1,'Thickness_um']=.22
        with self.assertRaises(ValueError):
            restore_structure(m,edited,p,snapshot)

    def test_move_delete_and_outer_media(self):
        _,l,p,_,_=self.edit('down')
        self.assertEqual(list(l.Name),['Top','B','A','Bottom'])
        _,l,p,s,_=self.edit('delete')
        self.assertEqual(list(p.Layer),['B'])
        self.assertEqual(s,'B')
        for action in ('duplicate','delete','up','down'):
            with self.subTest(action=action),self.assertRaises(ValueError):
                self.edit(action,selected='Top')
        with self.assertRaises(ValueError):
            self.edit('up')

    def test_add_at_outer_media_and_rename_collision(self):
        _,l,_,s,_=self.edit('above',selected='Top',name='A',material='current:Air',thickness=0,unit='nm')
        self.assertEqual(s,'A_2')
        self.assertEqual(list(l.Name)[:2],['Top','A_2'])
        self.assertEqual(l.iloc[1].Thickness_um,.1)
        with self.assertRaises(ValueError):
            self.edit('apply',name='B',material='current:Si',thickness=200,unit='nm')

    def test_saved_preset_adds_wavelength_table_and_never_overwrites(self):
        catalog=material_catalog(self.app,self.m)
        self.assertIn('saved:Alloy',catalog)
        self.assertEqual(len(self.m),2)
        m,l,_,_,_=self.edit('apply',name='A',material='saved:Alloy',thickness=.2,unit='µm')
        self.assertEqual(l.iloc[1].Material,'AlGaAs')
        self.assertEqual(m.iloc[-1].DataFile,'nk_saved.csv')
        m,name=resolve_material(self.app,self.m,'builtin:Si sample')
        self.assertEqual(name,'Si_2')
        self.assertEqual(m[1]['A'],3.4)
        self.assertEqual(m[2]['A'],3.6)

    def test_invalid_mutations_are_atomic(self):
        original=self.l.copy(deep=True)
        for value in (float('nan'),float('inf'),-1,0):
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.edit('apply',name='A',material='builtin:Si sample',thickness=value,unit='nm')
        with self.assertRaises(ValueError):
            self.edit('apply',name='A',material='unknown',thickness=100,unit='nm')
        for name in ('', 'None', 'nan', 'invalid\nname'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                self.edit('apply',name=name,material='current:Si',thickness=100,unit='nm')
        pd.testing.assert_frame_equal(self.l,original)
        self.assertEqual(len(self.m),2)
        with self.assertRaises(ValueError):
            self.edit('repeat',start='B',end='A',count=2)
        with self.assertRaises(ValueError):
            self.edit('repeat',start='A',end='B',count=1.5)

    def test_region_dimensions_units_positions_and_rotation(self):
        m,l,p,r,b=mutate_region(self.app,self.m,self.l,self.p,'A','0','apply',shape='rectangle',material='current:Air',sx=250,sy=125,x=15,y=-20,angle=45,unit='nm')
        row=p.iloc[0]
        self.assertEqual(row.Shape,'rectangle')
        self.assertEqual(row.SizeX_um,.25)
        self.assertEqual(row.SizeY_um,.125)
        self.assertEqual(row.CenterY_um,-.02)
        self.assertEqual(row.Angle_deg,45)
        self.assertEqual(self.p.iloc[0].Shape,'circle')
        _,_,p,r,_=mutate_region(self.app,m,l,p,'A','0','copy')
        self.assertEqual(r,'2')
        self.assertEqual(len(p),3)
        _,_,p,r,_=mutate_region(self.app,m,l,p,'A','2','delete')
        self.assertEqual(len(p),2)

    def test_region_rejects_stale_selection_and_unknown_references(self):
        with self.assertRaises(ValueError):
            mutate_region(self.app,self.m,self.l,self.p,'B','0','delete')
        with self.assertRaises(ValueError):
            mutate_region(self.app,self.m,self.l,self.p,'Top','new','add')
        dangling=self.p.copy(); dangling.loc[0,'Layer']='Missing'
        with self.assertRaises(ValueError):
            validate_structure(self.m,self.l,dangling)

    def test_stack_escapes_names_and_reports_total(self):
        layers=self.l.copy(); layers.loc[1,'Name']='<script>bad</script>'
        rendered=stack_view(layers,self.p,'A',.77,.77)
        self.assertNotIn('<script>',rendered)
        self.assertIn('&lt;script&gt;',rendered)
        self.assertIn('500 nm total thickness',rendered)

    def test_build_and_refresh_callback(self):
        with gr.Blocks() as demo:
            m=gr.Dataframe(value=self.m); l=gr.Dataframe(value=self.l); p=gr.Dataframe(value=self.p)
            ax=gr.Number(.77); ay=gr.Number(.77)
            controls=build_structure_builder(self.app,m,l,p,ax,ay)
        refreshed=controls['refresh'](self.m,self.l,self.p,'B','0','nm','A','B',.77,.77)
        self.assertEqual(len(refreshed),len(controls['refresh_outputs']))
        self.assertEqual(refreshed[0]['value'],'B')
        self.assertEqual(refreshed[7]['value'],'1')
        self.assertEqual(refreshed[8],'rectangle')
        api_names={getattr(fn,'api_name',None) for fn in demo.fns.values()}
        self.assertIn('builder_layer_repeat',api_names)
        self.assertIn('builder_region_add',api_names)
        self.assertIn('builder_undo',api_names)
        repeat_callback=next(fn.fn for fn in demo.fns.values() if fn.api_name=='builder_layer_repeat')
        result=repeat_callback(self.m,self.l,self.p,'A','A','current:Si',200,'nm','A','B',49)
        self.assertEqual(len(result),7)
        self.assertEqual(len(result[1]),102)
        self.assertEqual(len(result[2]),100)
        self.assertIn('Applied repeat',result[-1])
        undo_callback=next(fn.fn for fn in demo.fns.values() if fn.api_name=='builder_undo')
        restored=undo_callback(result[0],result[1],result[2],result[4],result[3]['value'])
        self.assertEqual(len(restored[0]),4)
        failure=repeat_callback(self.m,self.l,self.p,'A','A','current:Si',200,'nm','B','A',49)
        self.assertIn('No changes applied',failure[-1])
        convert=next(fn.fn for fn in demo.fns.values() if fn.api_name=='builder_dimension_unit')
        converted=convert('nm','µm',375,100,90,5,-3,'ellipse')
        self.assertEqual(converted[1]['value'],.375)
        self.assertEqual(converted[2]['value'],.1)
        self.assertEqual(converted[5]['value'],-.003)
        self.assertIsNone(convert('nm','µm',None,100,90,5,-3,'ellipse')[1]['value'])
        # One combined listener coalesces multi-table updates. Every mutation has
        # a final refresh dependency, and every visible writer is serialized.
        config=demo.get_config_file()
        dependencies=config['dependencies']
        combined=[d for d in dependencies if len(d['targets'])==5]
        self.assertEqual(len(combined),1)
        self.assertEqual(combined[0]['trigger_mode'],'always_last')
        self.assertTrue(combined[0]['queue'])
        mutation_names={'builder_layer_'+a for a in ('apply','above','below','duplicate','up','down','delete','repeat')}
        mutation_names |= {'builder_region_'+a for a in ('apply','add','copy','delete')}
        mutation_names.add('builder_undo')
        for mutation in (d for d in dependencies if d['api_name'] in mutation_names):
            children=[d for d in dependencies if d['trigger_after']==mutation['id']]
            self.assertEqual(len(children),1,mutation['api_name'])
            self.assertTrue(children[0]['queue'])
            self.assertEqual(children[0]['show_progress'],'hidden')
        for fn in demo.fns.values():
            if fn.api_name == 'preview_structure':
                self.assertEqual(fn.concurrency_id,'structure_preview')
            elif fn.fn is not None:
                self.assertEqual(fn.concurrency_id,'structure_builder_editor')
                self.assertFalse(fn.preprocess)
        apply_callback=next(fn.fn for fn in demo.fns.values() if fn.api_name=='builder_layer_apply')
        committed=apply_callback(self.m,self.l,self.p,'A','A','saved:Alloy',200,'nm','A','B',1)
        rendered=controls['refresh'](committed[0],committed[1],committed[2],committed[3]['value'],'0','nm','A','B',.77,.77)
        self.assertEqual(rendered[2]['value'],'current:AlGaAs')
        self.assertIn('AlGaAs',rendered[4])
        self.assertIn('AlGaAs',rendered[0]['choices'][1][0])
        raw=lambda value: dict(headers=list(value.columns),data=value.astype(object).where(value.notna(),None).values.tolist(),metadata=None)
        stale=controls['refresh'](raw(self.m),raw(self.l),raw(self.p),'Deleted','999','nm','Deleted','Deleted',.77,.77)
        self.assertEqual(stale[0]['value'],'A')
        self.assertEqual(stale[5]['value'],'A')
        self.assertEqual(stale[6]['value'],'B')
        self.assertEqual(stale[7]['value'],'0')
        selected_new=controls['refresh'](self.m,self.l,self.p,'A','new','nm','A','B',.77,.77)
        self.assertEqual(selected_new[7]['value'],'new')
        guarded=next(fn.fn for fn in demo.fns.values() if fn.fn and fn.fn.__name__=='guarded_refresh')
        patch=guarded(self.m,self.l,self.p,'B','1','nm','A','B',.77,.77,12)
        json.dumps(patch) # hidden JSON must contain plain update dictionaries
        self.assertEqual(patch['revision'],12)
        self.assertEqual(patch['updates'][18:20],['B','1'])
        self.assertTrue(patch['updates'][1]['interactive'])
        choose_layer=next(fn.fn for fn in demo.fns.values() if fn.fn and fn.fn.__name__=='guarded_layer_selection')
        patterned=self.p.copy()
        patterned.loc[1,['Shape','SizeX_um','SizeY_um']]=['circle',.05,0.]
        switched=choose_layer(self.m,self.l,patterned,'B','new','nm','A','B',.77,.77,'Bottom',13)
        self.assertEqual(switched['updates'][7]['value'],'1')
        self.assertEqual(switched['updates'][10]['value'],50)
        same_layer=choose_layer(self.m,self.l,patterned,'B','new','nm','A','B',.77,.77,'B',14)
        self.assertEqual(same_layer['updates'][7]['value'],'new')
        self.assertEqual(same_layer['updates'][10]['value'],100)
        loaded=next(fn.fn for fn in demo.fns.values() if fn.fn and fn.fn.__name__=='invoke_loaded')
        pending=loaded(self.m,self.l,self.p,'B','A','current:Si',200,'nm','A','B',1,'A')
        self.assertIn('Layer is still loading',pending[-1])
        self.assertTrue(all(result==gr.skip() for result in pending[:-1]))
        applied=loaded(self.m,self.l,self.p,'B','B','current:Si',450,'nm','A','B',1,'B')
        self.assertAlmostEqual(applied[1].iloc[2].Thickness_um,.45)
        loaded_region=next(fn.fn for fn in demo.fns.values() if fn.fn and fn.fn.__name__=='invoke_loaded_region')
        pending_region=loaded_region(self.m,self.l,self.p,'B','1','rectangle','current:Air',150,80,0,0,0,'nm','A','0')
        self.assertIn('Region is still loading',pending_region[-1])
        self.assertTrue(all(result==gr.skip() for result in pending_region[:-1]))

    def test_background_refresh_cannot_restore_old_layer_or_material_choice(self):
        with gr.Blocks() as demo:
            controls=build_structure_builder(self.app,gr.Dataframe(self.m),gr.Dataframe(self.l),
                gr.Dataframe(self.p),gr.Number(.77),gr.Number(.77))
        # A previously submitted A refresh can finish after the user picked B.
        # It may refresh choices, but must not command the dropdown back to A.
        older=controls['refresh_editor'](self.m,self.l,self.p,'A','0','nm','A','B',.77,.77)
        newer=controls['refresh_editor'](self.m,self.l,self.p,'B','1','nm','A','B',.77,.77)
        self.assertNotIn('value',older[0])
        self.assertNotIn('value',newer[0])
        self.assertEqual(older[1],'A')
        self.assertEqual(newer[1],'B')
        removed=controls['refresh_editor'](self.m,self.l,self.p,'Deleted','0','nm','A','B',.77,.77)
        self.assertEqual(removed[0]['value'],'A')
        updates=controls['refresh_materials'](self.m,'current:Air','current:Si')
        self.assertTrue(all('value' not in update for update in updates))
        dependencies=demo.get_config_file()['dependencies']
        guarded=[d for d in dependencies if d.get('js') and 'args.slice(0, -1)' in d['js']]
        self.assertGreaterEqual(len(guarded),16)
        self.assertTrue(all(len(d['outputs'])==1 for d in guarded))

    @unittest.skipUnless(shutil.which('node'),'Node is needed to execute the browser revision guard')
    def test_browser_ignores_reversed_responses_and_preserves_unsaved_edits(self):
        issue,apply,invalidate=editor_revision_scripts('test',18)
        script=r'''
            const fs=require('fs'), vm=require('vm'), assert=require('assert/strict');
            const scripts=JSON.parse(fs.readFileSync(0,'utf8'));
            const context=vm.createContext({window:{}});
            const issue=vm.runInContext('('+scripts[0]+')',context);
            const apply=vm.runInContext('('+scripts[1]+')',context);
            const invalidate=vm.runInContext('('+scripts[2]+')',context);
            const first=issue('PCS1',0).at(-1);
            const second=issue('PCS2',0).at(-1);
            const gold=issue('Gold',0).at(-1);
            const expectIgnored=(updates)=>{
                assert.equal(updates.length,18);
                assert.ok(updates.every(update=>update.__type__==='update' && !('value' in update)));
            };
            assert.equal(apply({revision:gold,updates:['Gold',100]})[0],'Gold');
            expectIgnored(apply({revision:second,updates:['PCS2',250]}));
            expectIgnored(apply({revision:first,updates:['PCS1',250]}));
            const pending=issue('Gold',0).at(-1);
            invalidate(); // user types a new thickness before the response arrives
            expectIgnored(apply({revision:pending,updates:['Gold',100]}));
            const fresh=issue('PCS1',0).at(-1);
            assert.equal(apply({revision:fresh,updates:['PCS1',350]})[1],350);
        '''
        subprocess.run([shutil.which('node'),'-e',script],input=json.dumps([issue,apply,invalidate]),
                       text=True,check=True,capture_output=True)


if __name__=='__main__':
    unittest.main()
