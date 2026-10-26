"""Cropped Original search designs reopen as complete finite PC documents."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from data_library import DataLibrary,write_json
from model import prepare
from optical_unit_cell import apply_original_pc_cell
from test_pc_optical_defaults import pc_project


class PcLibraryRoundtripTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ods_pc_library_',dir=Path(__file__).resolve().parents[3])
        self.addCleanup(self.temp.cleanup)
        self.library=DataLibrary(self.temp.name)
        self.project=pc_project()
        self.project['device']['contacts'][1].update(optical_material_name='Au',optical_thickness_um=.1)
        self.model=self.compile_original(self.project)
        self.assertEqual(len(self.model['patterns']),1)
        self.source=self.model['optical_unit_cell']['pattern_source_indices'][0]-1
        self.assertNotEqual(self.source,0)

    def compile_original(self,project):
        model=prepare(project['materials'],project['layers'],project['patterns'],
            self.library.files_for(project),project['settings'])
        apply_original_pc_cell(model,project)
        model['geometry_source']='original_tables'
        return model

    def test_radius_and_position_candidate_restore_the_source_row_and_recrop_identically(self):
        candidate=copy.deepcopy(self.model)
        candidate['patterns'][0].update(sx=.075,cx=.012,cy=-.009,angle=12.)
        before=copy.deepcopy(self.project)
        restored=self.library.from_model(candidate,self.project)
        self.assertEqual(self.project,before)
        self.assertEqual(restored['device'],before['device'])
        self.assertEqual(len(restored['patterns']),16)
        self.assertEqual((restored['settings']['ax_um'],restored['settings']['ay_um']),(2.,2.))
        for index,row in enumerate(restored['patterns']):
            if index!=self.source:self.assertEqual(row,before['patterns'][index])
        selected=restored['patterns'][self.source]
        offset=candidate['optical_unit_cell']['selection']
        self.assertAlmostEqual(selected['CenterX_um'],offset['cx_um']+.012)
        self.assertAlmostEqual(selected['CenterY_um'],offset['cy_um']-.009)
        self.assertEqual(selected['SizeX_um'],.075)
        reopened=self.compile_original(restored)
        self.assertEqual((reopened['ax'],reopened['ay']),(.3,.3))
        self.assertEqual(len(reopened['patterns']),1)
        row=reopened['patterns'][0]
        self.assertAlmostEqual(row['cx'],.012)
        self.assertAlmostEqual(row['cy'],-.009)
        self.assertEqual((row['sx'],row['angle']),(.075,12.))
        self.assertEqual(reopened['optical_unit_cell']['pattern_source_indices'],[self.source+1])

    def test_saved_design_restores_layer_thickness_and_material_without_shrinking_the_document(self):
        candidate=copy.deepcopy(self.model)
        candidate['layers'][1].update(thickness=.27,material='Au')
        directory=self.library.runs/'pc_search';directory.mkdir()
        write_json(directory/'project.json',self.project)
        search=dict(input_bounds=[dict(Parameter='radius',Target=str(self.source+1))])
        write_json(directory/'job.json',dict(model=self.model,search=search))
        (directory/'design_models.jsonl').write_text(json.dumps(dict(design_id=7,model=candidate))+'\n',encoding='utf-8')
        restored,returned_search=self.library.project_for('pc_search',7)
        self.assertEqual(returned_search,search)
        self.assertEqual(restored['device'],self.project['device'])
        self.assertEqual(len(restored['patterns']),16)
        self.assertEqual(restored['patterns'][self.source]['Material'],'Air')
        self.assertEqual((restored['layers'][1]['Thickness_um'],restored['layers'][1]['Material']),(.27,'Au'))
        reopened=self.compile_original(restored)
        self.assertEqual((reopened['layers'][1]['thickness'],reopened['layers'][1]['material']),(.27,'Au'))
        self.assertEqual(reopened['patterns'][0]['material'],'Air')
        self.assertFalse(any(row.get('contact_optical_surface') for row in reopened['layers']))

    def test_original_table_periods_can_differ_from_the_full_physical_footprint(self):
        self.project['settings'].update(ax_um=2.6,ay_um=2.8)
        candidate=self.compile_original(self.project)
        cell=candidate['optical_unit_cell']
        self.assertEqual((cell['source_width_um'],cell['source_depth_um']),(2.,2.))
        self.assertEqual((cell['source_model_ax_um'],cell['source_model_ay_um']),(2.6,2.8))
        candidate['patterns'][0].update(sx=.068,cx=.01)
        restored=self.library.from_model(candidate,self.project)
        self.assertEqual((restored['settings']['ax_um'],restored['settings']['ay_um']),(2.6,2.8))
        self.assertEqual(restored['device'],self.project['device'])
        self.assertEqual(len(restored['patterns']),16)
        reopened=self.compile_original(restored)
        self.assertEqual((reopened['ax'],reopened['ay']),(.3,.3))
        self.assertAlmostEqual(reopened['patterns'][0]['cx'],.01)
        self.assertEqual(reopened['patterns'][0]['sx'],.068)
        wrong_base=copy.deepcopy(self.project);wrong_base['settings']['ax_um']=2.7
        with self.assertRaisesRegex(ValueError,'full-table mapping'):
            self.library.from_model(candidate,wrong_base)
        # Old crops are accepted only when their recorded dimensions can be
        # matched to the complete source table periods without guessing.
        ambiguous=copy.deepcopy(candidate)
        ambiguous['optical_unit_cell'].pop('source_model_ax_um')
        ambiguous['optical_unit_cell'].pop('source_model_ay_um')
        with self.assertRaisesRegex(ValueError,'full-table mapping'):
            self.library.from_model(ambiguous,self.project)

    def test_legacy_source_period_metadata_is_accepted_when_it_matches_the_full_tables(self):
        model=copy.deepcopy(self.model)
        model['optical_unit_cell'].pop('source_model_ax_um',None)
        model['optical_unit_cell'].pop('source_model_ay_um',None)
        restored=self.library.from_model(model,self.project)
        self.assertEqual((restored['settings']['ax_um'],restored['settings']['ay_um']),(2.,2.))
        self.assertEqual(restored['device'],self.project['device'])
        self.assertEqual(len(restored['patterns']),16)

    def test_changed_pitch_is_preserved_in_saved_candidate_but_not_silently_applied(self):
        candidate=copy.deepcopy(self.model);candidate['ax']=.35
        before=copy.deepcopy(candidate)
        with self.assertRaisesRegex(ValueError,'regenerate the finite PC array'):
            self.library.from_model(candidate,self.project)
        self.assertEqual(candidate,before)
        self.assertEqual(candidate['ax'],.35)
        self.assertEqual(self.project['device']['width_um'],2.)
        self.assertEqual(len(self.project['patterns']),16)

    def test_missing_clipped_duplicate_and_wrong_base_mappings_are_rejected(self):
        missing=copy.deepcopy(self.model);missing['optical_unit_cell'].pop('pattern_source_indices')
        clipped=copy.deepcopy(self.model);clipped['optical_unit_cell']['clipped_patterns']=1
        duplicate=copy.deepcopy(self.model);duplicate['patterns']*=2
        duplicate['optical_unit_cell']['pattern_source_indices']*=2
        outside=copy.deepcopy(self.model);outside['optical_unit_cell']['pattern_source_indices']=[17]
        for model in (missing,clipped,duplicate,outside):
            with self.subTest(model=model),self.assertRaisesRegex(ValueError,'full-table mapping'):
                self.library.from_model(model,self.project)
        with self.assertRaisesRegex(ValueError,'full-table mapping'):
            self.library.from_model(self.model)
        wrong_base=copy.deepcopy(self.project);wrong_base['patterns']=wrong_base['patterns'][:1]
        with self.assertRaisesRegex(ValueError,'full-table mapping'):
            self.library.from_model(self.model,wrong_base)

    def test_legacy_and_device_projection_keep_the_existing_cropped_table_behavior(self):
        for source in (None,'device'):
            model=copy.deepcopy(self.model)
            if source is None:model.pop('geometry_source')
            else:model['geometry_source']=source
            model['optical_unit_cell'].pop('pattern_source_indices')
            restored=self.library.from_model(model,self.project)
            self.assertEqual(len(restored['patterns']),1)
            self.assertEqual((restored['settings']['ax_um'],restored['settings']['ay_um']),(.3,.3))
            self.assertEqual(restored['patterns'][0]['CenterX_um'],0.)


if __name__=='__main__':unittest.main()
