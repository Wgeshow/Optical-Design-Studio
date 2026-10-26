"""A complete finite PC array defaults to one actual pitch cell in S4."""
import copy
import math
import os
import tempfile
import unittest

from optical_unit_cell import pc_unit_cell,resolve_unit_cell,pc_unit_cell_issue
from pc_array import apply_pc_array
from test_contact_optics import device,project,prepared


def pc_project():
    physical=device();physical['mesh'].update(nx=32,ny=32)
    physical=apply_pc_array(physical,dict(id='pc',name='Custom finite PC',layer_id='p',
        width_um=1.2,depth_um=1.2,cell_width_um=.3,cell_depth_um=.3,radius_um=.05,
        cx_um=0.,cy_um=0.))
    return project(physical)


class PcOpticalDefaultTests(unittest.TestCase):
    def test_unconfigured_even_array_compiles_one_whole_hole_and_keeps_full_device(self):
        value=pc_project();original=copy.deepcopy(value)
        result=prepared(value)
        self.assertEqual(value,original)
        self.assertNotIn('optical_unit_cell',value['settings'])
        self.assertEqual(len(value['device']['shapes']),16)
        self.assertEqual(value['device']['width_um'],2.)
        self.assertEqual((result['ax'],result['ay']),(.3,.3))
        holes=[row for row in result['patterns'] if row['material']=='Air' and row['shape']=='circle']
        self.assertEqual(len(holes),1)
        self.assertAlmostEqual(holes[0]['cx'],0.)
        self.assertAlmostEqual(holes[0]['cy'],0.)
        self.assertEqual(holes[0]['sx'],.05)
        selection=result['optical_unit_cell']['selection']
        self.assertAlmostEqual(abs(selection['cx_um']),.15)
        self.assertAlmostEqual(abs(selection['cy_um']),.15)

    def test_default_uses_actual_enabled_member_and_preserves_its_edited_radius(self):
        value=pc_project();physical=value['device']
        selected=pc_unit_cell(physical)
        hole=next(row for row in physical['shapes'] if row['cx_um']==selected['cx_um'] and row['cy_um']==selected['cy_um'])
        hole['size_x_um']=hole['size_y_um']=.16
        result=prepared(project(physical))
        self.assertAlmostEqual(next(row['sx'] for row in result['patterns'] if row['shape']=='circle'),.08)
        hole['enabled']=False
        next_selection=pc_unit_cell(physical)
        self.assertNotEqual((next_selection['cx_um'],next_selection['cy_um']),(selected['cx_um'],selected['cy_um']))

    def test_explicit_cell_and_disabled_choice_are_never_replaced_by_defaults(self):
        physical=pc_project()['device']
        selection=dict(enabled=True,width_um=.2,depth_um=.25,cx_um=.1,cy_um=.1)
        self.assertEqual(resolve_unit_cell(selection,physical),selection)
        disabled=dict(selection,enabled=False)
        self.assertEqual(resolve_unit_cell(disabled,physical),disabled)
        self.assertIn('Use PC lattice size',pc_unit_cell_issue(disabled,physical))
        self.assertIn('one air hole',pc_unit_cell_issue(disabled,physical))

    def test_multi_cell_pc_selection_has_actionable_issue_and_single_pitch_is_valid(self):
        physical=pc_project()['device']
        single=resolve_unit_cell(None,physical)
        self.assertIsNone(pc_unit_cell_issue(single,physical))
        larger=dict(single,width_um=.6)
        self.assertIn('multiple PC cells',pc_unit_cell_issue(larger,physical))
        self.assertEqual(larger['width_um'],.6)

    def test_direct_backend_cannot_submit_explicit_full_or_multiple_pc_cells(self):
        for selection in (dict(enabled=False,width_um=2.,depth_um=2.,cx_um=0.,cy_um=0.),
                          dict(enabled=True,width_um=.6,depth_um=.3,cx_um=0.,cy_um=0.)):
            value=pc_project();value['settings']['optical_unit_cell']=selection
            original=copy.deepcopy(value)
            with self.assertRaisesRegex(ValueError,'one|multiple PC cells'):
                prepared(value)
            self.assertEqual(value,original)

    def test_non_pc_periodic_geometry_and_disabled_pc_keep_previous_domain_choices(self):
        physical=device()
        self.assertFalse(resolve_unit_cell(None,physical)['enabled'])
        self.assertIsNone(pc_unit_cell_issue(None,physical))
        physical=pc_project()['device'];physical['pc_arrays'][0]['enabled']=False
        self.assertFalse(resolve_unit_cell(None,physical)['enabled'])
        self.assertIsNone(pc_unit_cell_issue(None,physical))
        physical['pc_arrays'][0]['enabled']=True;physical['layers'][0]['enabled']=False
        self.assertFalse(resolve_unit_cell(None,physical)['enabled'])

    @unittest.skipUnless(os.environ.get('S4_TEST_CONTACT_OPTICS')=='1','Opt-in native S4 PC default test')
    def test_native_s4_receives_one_hole_without_a_saved_optical_crop(self):
        from backend import execute
        from model import DEFAULT_PERFORMANCE
        value=pc_project();model=prepared(value)
        self.assertNotIn('optical_unit_cell',value['settings'])
        self.assertEqual((model['ax'],model['ay']),(.3,.3))
        self.assertEqual(len([row for row in model['patterns'] if row['shape']=='circle']),1)
        rows,_=execute(model,dict(DEFAULT_PERFORMANCE,workers=1,threads=1,timeout_seconds=60))
        self.assertEqual(len(rows),1)
        self.assertTrue(all(math.isfinite(value) for value in rows[0]))
        self.assertAlmostEqual(sum(rows[0][3:]),1.,places=10)


class OriginalPcSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from qt_core import ProjectStore
        from data_library import DataLibrary
        from optical_unit_cell import pc_unit_cell
        self.directory=tempfile.TemporaryDirectory(prefix='ods_pc_search_')
        self.addCleanup(self.directory.cleanup)
        self.store=ProjectStore(DataLibrary(self.directory.name),restore=False)
        self.value=pc_project()
        self.value['settings'].update(wl_start_nm=1540.,wl_stop_nm=1560.,wl_step_nm=10.)
        self.store.load_project(self.value)
        self.value=self.store.project()
        self.cell=pc_unit_cell(self.value['device'])
        self.target=next(index for index,row in enumerate(self.value['patterns'],1)
            if row['CenterX_um']==self.cell['cx_um'] and row['CenterY_um']==self.cell['cy_um'])
        self.bounds=[dict(Parameter='radius',Target=str(self.target),Min=.04,Max=.05,Step=.01,Choices=''),
                     dict(Parameter='lattice_square',Target='',Min=.27,Max=.33,Step=.06,Choices='')]

    def prepare(self,kind,**changes):
        from qt_core import prepare_job
        options=dict(optical_geometry_source='original_tables',bounds=copy.deepcopy(self.bounds))
        options.update(changes)
        original=copy.deepcopy(options);project=copy.deepcopy(self.value)
        _,cfg=prepare_job(kind,self.value,options,self.store.library)
        self.assertEqual(options,original);self.assertEqual(self.value,project)
        self.assertEqual((cfg['model']['ax'],cfg['model']['ay']),(.3,.3))
        self.assertEqual(len(cfg['model']['patterns']),1)
        self.assertEqual(cfg['model']['optical_unit_cell']['pattern_source_indices'],[self.target])
        self.assertFalse(any(row.get('contact_optical_surface') for row in cfg['model']['layers']))
        self.assertEqual(len(cfg['search']['project']['device']['shapes']),16)
        return cfg

    def test_original_explore_remaps_retained_source_target_and_candidates_stay_one_hole(self):
        from peak_optimizer import designs
        cfg=self.prepare('peaks',search_options=dict(design_budget=8))
        self.assertEqual(cfg['search']['dimensions'][0]['index'],0)
        candidates=list(designs(cfg['model'],cfg['search']))
        self.assertEqual(len(candidates),4)
        self.assertEqual({model['ax'] for model in candidates},{.27,.33})
        self.assertEqual({model['patterns'][0]['sx'] for model in candidates},{.04,.05})
        self.assertTrue(all(len(model['patterns'])==1 for model in candidates))

    def test_original_target_structure_ranges_and_ai_search_use_one_pc_cell(self):
        from ml_optimizer import model_for
        target=self.prepare('target',use_structure_patterns=True,target_nm=1550.,tolerance_nm=1.,
            min_q=1000.,half_window=10.,step=10.,grid_steps=2,trials=2,initial=2,finalists=1)
        ai=self.prepare('ai_search',wavelength_nm=1550.,basis=9,shell_um=.02)
        for cfg in (target,ai):
            self.assertEqual(cfg['search']['dimensions'][0]['index'],0)
            values=[dimension['values'][0] for dimension in cfg['search']['dimensions']]
            candidate=model_for(cfg['model'],cfg['search'],values)
            self.assertEqual(len(candidate['patterns']),1)
            self.assertAlmostEqual(candidate['patterns'][0]['sx'],.04)

    def test_removed_pattern_targets_and_linked_selections_are_rejected_without_retargeting(self):
        from qt_core import prepare_job
        outside=next(index for index in range(1,17) if index!=self.target)
        for bounds,shared in (([dict(self.bounds[0],Target=str(outside))],None),
                              (self.bounds,dict(enabled=True,targets=[self.target,outside],min_um=.04,max_um=.05,step_um=.01))):
            with self.assertRaisesRegex(ValueError,'outside the optical PC cell'):
                prepare_job('peaks',self.value,dict(optical_geometry_source='original_tables',bounds=bounds,shared_hole=shared),self.store.library)

    def test_absolute_centers_and_whitespace_parameter_names_map_to_the_same_source_hole(self):
        bounds=[dict(self.bounds[0],Parameter=' radius '),
            dict(Parameter='center_x',Target=str(self.target),Min=self.cell['cx_um']-.01,
                 Max=self.cell['cx_um']+.01,Step=.02,Choices='')]
        cfg=self.prepare('peaks',bounds=bounds,search_options=dict(design_budget=8))
        self.assertEqual(cfg['search']['dimensions'][0]['index'],0)
        self.assertEqual(cfg['search']['dimensions'][0]['parameter'],'radius')
        self.assertAlmostEqual(cfg['search']['dimensions'][1]['values'][0],-.01)
        self.assertAlmostEqual(cfg['search']['dimensions'][1]['values'][-1],.01)

    def test_inconsistent_original_table_holes_are_rejected_without_changing_other_layers(self):
        from qt_core import prepare_job
        outside=next(index for index in range(16) if index!=self.target-1)
        for change in ('oversized','neighbor'):
            value=copy.deepcopy(self.value)
            if change=='oversized':value['patterns'][self.target-1]['SizeX_um']=.2
            else:value['patterns'][outside].update(CenterX_um=self.cell['cx_um']+.11,CenterY_um=self.cell['cy_um'],SizeX_um=.03)
            original=copy.deepcopy(value)
            with self.assertRaisesRegex(ValueError,'one whole circular Air hole'):
                prepare_job('simulation',value,dict(optical_geometry_source='original_tables'),self.store.library)
            self.assertEqual(value,original)
        value=copy.deepcopy(self.value)
        value['patterns'].append(dict(value['patterns'][self.target-1],Layer='n-Si film'))
        _,cfg=prepare_job('simulation',value,dict(optical_geometry_source='original_tables'),self.store.library)
        self.assertEqual(len(cfg['model']['patterns']),2)

    def test_raw_blank_table_rows_fail_before_search_index_mapping(self):
        from qt_core import prepare_job
        value=copy.deepcopy(self.value);value['patterns'].insert(0,dict(Shape='',Layer='',Material='',SizeX_um=0))
        with self.assertRaisesRegex(ValueError,'blank optical pattern rows'):
            prepare_job('peaks',value,dict(optical_geometry_source='original_tables',bounds=self.bounds),self.store.library)


if __name__=='__main__':unittest.main()
