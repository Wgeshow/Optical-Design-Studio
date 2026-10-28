import copy,csv,json,tempfile,unittest
from pathlib import Path
import numpy as np
import pcsel_research as pc
from pcsel_paper_studies import king2024_example


class ComparisonSweepTests(unittest.TestCase):
    def settings(self):
        cfg=king2024_example('fig9',model='finite',formulation='reference_wavelength')
        cfg.update(collocation_order=4,harmonics=1,grid_nm=2.5)
        cfg['parameter_sweep']=dict(parameters=[dict(path='aperture_um',field='side',values=[1000.,1500.])],
            variants=[dict(name=name,overrides=[dict(path='layers',object_id='photonic-crystal',field='thickness_nm',value=height),
                      dict(path='layers',object_id='qw-pc-spacer',field='thickness_nm',value=spacer)])
                      for name,height,spacer in [('Original',150.,50.),('Weakened',100.,300.)]],max_cases=4)
        return cfg

    def test_exact_variant_inputs_and_isolation(self):
        cfg=self.settings();before=copy.deepcopy(cfg);out=pc.prepare({},cfg);cases=out['parameter_sweep']['cases']
        self.assertEqual(cfg,before)
        self.assertEqual([r['variant'] for r in cases],['Original','Original','Weakened','Weakened'])
        for case,(height,spacer,side) in zip(cases,[(150,50,1000),(150,50,1500),(100,300,1000),(100,300,1500)]):
            deck=case['prepared'];layers={r['id']:r for r in deck['layers']}
            self.assertEqual(layers['photonic-crystal']['thickness_nm'],height)
            self.assertEqual(layers['qw-pc-spacer']['thickness_nm'],spacer)
            self.assertEqual(deck['aperture_um'],[side,side])
            self.assertEqual(case['parameters'],{'aperture_um.side':side})
            self.assertEqual(deck['paper_study']['comparison_variant'],case['variant'])
        cases[0]['prepared']['layers'][0]['index']=9
        self.assertNotEqual(cases[1]['prepared']['layers'][0]['index'],9)

    def test_aggregate_budget_and_duplicate_targets_are_rejected(self):
        cfg=self.settings();cfg['parameter_sweep']['max_cases']=3
        with self.assertRaisesRegex(ValueError,'4 cases'):pc.prepare({},cfg)
        cfg=self.settings();cfg['parameter_sweep']['variants'][0]['overrides'].append(dict(path='aperture_um',field='side',value=500.))
        with self.assertRaisesRegex(ValueError,'only once'):pc.prepare({},cfg)
        cfg=self.settings();cfg['parameter_sweep']['variants'][1]['name']='Original'
        with self.assertRaisesRegex(ValueError,'unique'):pc.prepare({},cfg)

    def test_actual_outputs_keep_variant_identity_and_coherent_near_field(self):
        cfg=self.settings()
        temporary=tempfile.TemporaryDirectory(prefix='test-variant-')
        with temporary as tmp:
            out=pc.execute(pc.prepare({},cfg),tmp)
            with (Path(tmp)/'pcsel_sweep.csv').open(encoding='utf-8') as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual([r['variant'] for r in rows],['Original','Original','Weakened','Weakened'])
            self.assertEqual(out['failed_cases'],0)
            for item in out['cases']:
                folder=Path(tmp)/item['directory']
                inputs=json.loads((folder/'pcsel_inputs.json').read_text(encoding='utf-8'))
                self.assertEqual(inputs['paper_study']['structure'],item['variant'])
                self.assertTrue(item['summary']['emitted_near_field_available'])
                with np.load(folder/'finite_fields.npz') as arrays:
                    waves=arrays['fields']
                    vectors=np.array([[1,0],[-1,0],[0,1],[0,-1]])
                    coeff=np.asarray([sum(pc.shape_fourier(s,-q) for s in inputs['shapes']) for q in vectors])
                    emitted=abs(coeff[2]*waves[:,2]+coeff[3]*waves[:,3])**2+abs(coeff[0]*waves[:,0]+coeff[1]*waves[:,1])**2
                    emitted/=emitted.max(axis=(1,2),keepdims=True)
                    np.testing.assert_allclose(arrays['emitted_near_intensity'],emitted,rtol=1e-13,atol=1e-13)
                    self.assertEqual(arrays['emitted_near_intensity'].shape,arrays['mode_intensity'].shape)
                    np.testing.assert_allclose(np.max(arrays['emitted_near_intensity'],axis=(1,2)),1.)


if __name__=='__main__':unittest.main(verbosity=2)
