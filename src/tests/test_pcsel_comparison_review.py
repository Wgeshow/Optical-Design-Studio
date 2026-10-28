"""Independent edge-case regressions for comparison inputs and emitted-field output.

Output edge cases stub the cavity solver to isolate the saved-array contract;
they do not claim physical cavity solutions or paper agreement.
"""
from pathlib import Path
import copy,csv,json,tempfile,unittest
from unittest.mock import patch
import numpy as np
import pcsel_research as pc
from pcsel_paper_studies import king2024_example


def settings():
    cfg=king2024_example('fig5',model='finite',formulation='reference_wavelength')
    cfg.pop('parameter_sweep');cfg.update(collocation_order=4,harmonics=1,grid_nm=2.5)
    return cfg

def fake_fields(cfg,zero_coherent=False):
    x,_,_=pc.chebyshev(4);X,Y=np.meshgrid(x,x);waves=np.zeros((1,4,5,5),complex)
    coeff=np.array([sum(pc.shape_fourier(s,-np.asarray(q)) for s in cfg['shapes']) for q in ([1,0],[-1,0],[0,1],[0,-1])])
    if zero_coherent:
        waves[0,0]=coeff[1]*(1+X+2j*Y);waves[0,1]=-coeff[0]*(1+X+2j*Y)
    else:
        waves[0,0]=1+X+2j*Y;waves[0,1]=.3*(1+X);waves[0,2]=.2j*(1+Y)
    return dict(x=x,fields=waves,aperture_um=np.array(cfg['aperture_um']))

def row(radiation=1.):
    return dict(mode=0,total_loss_cm1=1.+radiation,radiation_loss_cm1=radiation,edge_loss_cm1=1.,
        balance_relative=0.,eigen_residual=0.,wavelength_nm=1070.)

class IndependentComparisonReviewTests(unittest.TestCase):
    def test_total_fill_and_triangle_area_override_conflict(self):
        for field,value in [('base_length',.5),('base_angle_deg',60.)]:
            cfg=settings();cfg['parameter_sweep']=dict(parameters=[dict(path='fill_fraction',values=[.2,.3])],
                variants=[dict(name='fixed area field',overrides=[dict(path='shapes',object_id='triangle',field=field,value=value)])])
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'fill fraction'):
                pc.prepare({},cfg)

    def test_square_side_and_width_override_conflict(self):
        cfg=settings();cfg['parameter_sweep']=dict(parameters=[dict(path='aperture_um',field='side',values=[1000.,1500.])],
            variants=[dict(name='width',overrides=[dict(path='aperture_um',field='width',value=500.)])])
        with self.assertRaisesRegex(ValueError,'square side'):pc.prepare({},cfg)

    def test_comparison_masks_preserve_names_and_do_not_modify_source(self):
        cfg=settings();cfg['parameter_sweep']=dict(parameters=[dict(path='shapes',object_id='triangle',field='base_length',values=[.75,1.2])],
            variants=[dict(name='stretched',overrides=[]),dict(name='right angle',overrides=[dict(path='shapes',object_id='triangle',field='base_angle_deg',value=45.)])],
            invalid_geometry='mask',max_cases=4)
        before=copy.deepcopy(cfg);out=pc.prepare({},cfg);self.assertEqual(cfg,before)
        cases=out['parameter_sweep']['cases'];self.assertEqual(len(cases),4)
        self.assertEqual([r['variant'] for r in cases],['stretched','stretched','right angle','right angle'])
        self.assertEqual(cases[1]['status'],'invalid_geometry');self.assertIsNone(cases[1]['prepared'])
        self.assertEqual(cases[1]['parameters'],{'shapes.triangle.base_length':1.2})
        self.assertTrue(all(r.get('prepared') for r in (cases[0],cases[2],cases[3])))
        self.assertEqual(cases[3]['prepared']['shapes'][0]['base_angle_deg'],45.)

    def test_existing_partial_paper_metadata_survives_comparison(self):
        cfg=settings();cfg['paper_study']['custom_note']='retained source annotation'
        cfg['parameter_sweep']=dict(parameters=[dict(path='aperture_um',field='side',values=[1000.])],
            variants=[dict(name='unchanged',overrides=[])])
        case=pc.prepare({},cfg)['parameter_sweep']['cases'][0]
        provenance=case['prepared']['paper_study']
        self.assertEqual(provenance['custom_note'],'retained source annotation')
        self.assertEqual(provenance['source'],cfg['paper_study']['source'])
        self.assertEqual(provenance['base_structure'],cfg['paper_study']['structure'])

    def save_fields(self,cfg,fields,mode):
        tmp=tempfile.TemporaryDirectory(prefix='emitted-review-');self.addCleanup(tmp.cleanup)
        summary=dict(status='complete',artifacts=[],up_fraction=.2)
        with patch.object(pc,'finite_modes',return_value=([mode],fields)):
            pc._finite_outputs(cfg,np.zeros((4,4),complex),.3,Path(tmp.name),summary,lambda e:None,lambda:False)
        with np.load(Path(tmp.name)/'finite_fields.npz') as a:
            return {k:a[k] for k in a.files},summary

    def test_exact_coherent_dark_mode_is_nan_and_intracavity_retained(self):
        cfg=pc.prepare({},settings());fields=fake_fields(cfg,zero_coherent=True)
        arrays,_=self.save_fields(cfg,fields,row(radiation=0.))
        self.assertTrue(np.isnan(arrays['emitted_near_intensity']).all())
        self.assertGreater(arrays['mode_intensity'].max(),0.)

    def test_zero_actual_radiation_cannot_become_peak_one_emission(self):
        cfg=pc.prepare({},settings());fields=fake_fields(cfg)
        for radiation in (0.,1e-14):
            with self.subTest(radiation=radiation):
                arrays,summary=self.save_fields(cfg,fields,row(radiation=radiation))
                self.assertTrue(np.isnan(arrays['emitted_near_intensity']).all())
                self.assertFalse(summary['emitted_near_field_modes'][0]['resolved_radiation'])

    def test_dark_mode_has_no_normalized_far_field(self):
        cfg=pc.prepare({},settings());cfg.update(beam_grid=16,beam_padding=1)
        for radiation in (0.,1e-14,-1e-14):
            with self.subTest(radiation=radiation),self.assertRaisesRegex(ValueError,'dark mode'):
                pc.far_field(cfg,fake_fields(cfg),row(radiation=radiation))

    def test_bright_field_agrees_with_beam_coherent_definition(self):
        cfg=pc.prepare({},settings());cfg.update(beam_grid=16,beam_padding=1)
        fields=fake_fields(cfg);arrays,_=self.save_fields(cfg,fields,row())
        coefficients=np.array([sum(pc.shape_fourier(s,-np.asarray(q)) for s in cfg['shapes']) for q in ([1,0],[-1,0],[0,1],[0,-1])])
        t=(np.arange(16)+.5)/16;X,Y=np.meshgrid(t,t)
        expected=abs(coefficients[2]*.2j*(1+Y))**2+abs(coefficients[0]*(1+X+2j*Y)+coefficients[1]*.3*(1+X))**2
        expected/=expected.max()
        beam=pc.far_field(cfg,fields,row());observed=beam['near_per_um2']/beam['near_per_um2'].max()
        np.testing.assert_allclose(observed,expected,rtol=1e-12,atol=1e-12)
        self.assertAlmostEqual(float(np.nanmax(arrays['emitted_near_intensity'])),1.)
        self.assertAlmostEqual(float(beam['parseval_power']),1.,12)

if __name__=='__main__':unittest.main(verbosity=2)
