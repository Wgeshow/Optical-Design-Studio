import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from ai_campaign_storage import export_campaign_archive,load_campaign_checkpoint,resolve_campaign_paths
from field_storage import write_field_arrays,load_field_arrays


class CampaignStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.root=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def fixture(self,folder,fields=None):
        folder.mkdir(parents=True,exist_ok=True)
        fields=fields or folder/'designs/000001/fields';fields.mkdir(parents=True,exist_ok=True)
        array=np.array([[0.,0.,.1],[0.,0.,.2]])
        data=dict(xyz=array,E=np.array([[0,1+1j,0],[0,2-1j,0]]),H=np.array([[1.,0.,0.],[1.,0.,0.]]),
            plane=np.array([0,0]),layer=np.array([0,0]),material=np.array([0,0]),layer_names=np.array(['Slab']),material_names=np.array(['Si']))
        write_field_arrays(fields,data);(fields/'field_features.json').write_text('{"contour_features": {"shape": 0.1}}')
        saved=dict(settings={},base={},records=[dict(status='complete',phase='train',measurement_key='record-key',field_directory=str(fields.resolve()),values=[.1],rta=[dict(wavelength_nm=1550,R=.2,T=.8,A=0)])],summary=dict(completed=1))
        checkpoint=folder/'campaign.json';checkpoint.write_text(json.dumps(saved,indent=2));(folder/'project.json').write_text('{"evidence": "unchanged"}')
        return checkpoint,fields

    def test_legacy_relocation_prefers_extracted_fields_and_preserves_checkpoint(self):
        checkpoint,fields=self.fixture(self.root/'original');new=self.root/'extracted';shutil.copytree(checkpoint.parent,new)
        before=(new/'campaign.json').read_bytes();saved=load_campaign_checkpoint(new/'campaign.json')
        self.assertEqual(Path(saved['records'][0]['field_directory']),new/'designs/000001/fields')
        self.assertEqual(saved['records'][0]['source_field_directory'],str(fields))
        np.testing.assert_array_equal(load_field_arrays(saved['records'][0]['field_directory'])['E'],load_field_arrays(fields)['E'])
        self.assertEqual((new/'campaign.json').read_bytes(),before)

    def test_fit_archive_includes_external_fields_and_opens_without_original(self):
        checkpoint,fields=self.fixture(self.root/'fit',self.root/'old-collection/designs/000001/fields')
        checkpoint_bytes=checkpoint.read_bytes();project_bytes=(checkpoint.parent/'project.json').read_bytes();arrays=load_field_arrays(fields)
        archive=export_campaign_archive(checkpoint.parent,self.root/'portable.zip')
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.read('campaign.json'),checkpoint_bytes);self.assertEqual(z.read('project.json'),project_bytes)
            self.assertIsNone(z.testzip());z.extractall(self.root/'extracted')
        old=(self.root/'old-collection').resolve();unavailable=(self.root/'unavailable').resolve()
        self.assertTrue(old.is_relative_to(self.root.resolve()) and unavailable.is_relative_to(self.root.resolve()))
        old.rename(unavailable)
        loaded=load_campaign_checkpoint(self.root/'extracted/campaign.json');location=Path(loaded['records'][0]['field_directory'])
        self.assertTrue(location.is_relative_to(self.root/'extracted'));self.assertFalse(fields.exists())
        for key in ('xyz','E','H'):np.testing.assert_array_equal(load_field_arrays(location)[key],arrays[key])
        self.assertEqual(checkpoint.read_bytes(),checkpoint_bytes)

    def test_reference_fields_are_portable_without_rewriting_settings_file(self):
        checkpoint,fields=self.fixture(self.root/'campaign')
        _,reference=self.fixture(self.root/'reference')
        saved=json.loads(checkpoint.read_text());saved['settings']=dict(approach='reference',reference_directory=str(reference))
        checkpoint.write_text(json.dumps(saved));original=checkpoint.read_bytes()
        archive=export_campaign_archive(checkpoint.parent,self.root/'reference.zip')
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.read('campaign.json'),original);z.extractall(self.root/'extracted')
        loaded=load_campaign_checkpoint(self.root/'extracted/campaign.json')
        relocated=Path(loaded['settings']['reference_directory'])
        self.assertTrue(relocated.is_relative_to(self.root/'extracted'))
        self.assertEqual((relocated/'field_features.json').read_bytes(),(reference/'field_features.json').read_bytes())
        self.assertEqual(loaded['settings']['source_reference_directory'],str(reference))
        self.assertEqual(checkpoint.read_bytes(),original)

    def test_missing_fields_does_not_replace_existing_archive(self):
        checkpoint,fields=self.fixture(self.root/'source');(fields/'electric_fields.npz').unlink()
        destination=self.root/'keep.zip';destination.write_bytes(b'previous export')
        with self.assertRaisesRegex(ValueError,'field data is missing'):export_campaign_archive(checkpoint.parent,destination)
        self.assertEqual(destination.read_bytes(),b'previous export')

    def test_manifest_rejects_path_escape_and_record_mismatch(self):
        checkpoint,fields=self.fixture(self.root/'source');saved=json.loads(checkpoint.read_text())
        entry=dict(record_index=0,measurement_key='record-key',original_field_directory=str(fields.resolve()),relative_field_directory='../other')
        manifest=checkpoint.parent/'campaign_paths.json';manifest.write_text(json.dumps(dict(schema_version=1,records=[entry])))
        with self.assertRaisesRegex(ValueError,'inside'):load_campaign_checkpoint(checkpoint)
        entry.update(relative_field_directory='designs/000001/fields',measurement_key='other-record');manifest.write_text(json.dumps(dict(schema_version=1,records=[entry])))
        with self.assertRaisesRegex(ValueError,'does not match'):load_campaign_checkpoint(checkpoint)

    def test_backend_fit_reloads_relocated_legacy_records_without_solver_work(self):
        from test_ai_campaign import CampaignTests
        case=CampaignTests('test_fit_only_and_resume_do_not_simulate')
        temporary=tempfile.TemporaryDirectory
        with patch('test_ai_campaign.tempfile.TemporaryDirectory',side_effect=lambda:temporary(dir=self.root)):
            case.setUp()
        try:
            case.run_campaign('original');before=case.calls;relocated=case.root/'relocated';shutil.copytree(case.root/'original',relocated)
            source=(case.root/'original').resolve();target=(case.root/'unavailable').resolve()
            self.assertTrue(source.is_relative_to(case.root.resolve()) and target.is_relative_to(case.root.resolve()));source.rename(target)
            result=case.run_campaign('refit',resume_file=str(relocated/'campaign.json'),operation='fit')
            self.assertEqual(case.calls,before);self.assertEqual(result['summary']['new_simulations'],0);self.assertEqual(result['summary']['completed'],6)
            saved=json.loads((case.root/'refit/campaign.json').read_text())
            self.assertTrue(all(Path(record['field_directory']).is_relative_to(relocated) for record in saved['records']))
        finally:case.tearDown()


if __name__=='__main__':unittest.main()
