"""Numerical controls for editable PCSEL kernels and physical input changes."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

import pcsel_research as pc


class PCSELResearchTests(unittest.TestCase):
    def test_homogeneous_vertical_mode_matches_box_eigenvalue(self):
        settings=dict(model='vertical',lattice_nm=300.,layers=[dict(id='slab',thickness_nm=1000.,index=3.)],
            bottom_index=3.,top_index=3.,pad_nm=1000.,grid_nm=2.)
        cfg=pc.prepare({},settings);row,profile=pc.vertical(cfg)
        count=len(profile['z_nm']);beta=2*np.pi/300.;h=2.
        k=np.sqrt(beta**2+4/h**2*np.sin(np.pi/(2*(count+1)))**2)/3.
        self.assertAlmostEqual(row['frequency'],300*k/(2*np.pi),11)
        self.assertFalse(row['guided'])
        self.assertAlmostEqual(float(profile['intensity_per_nm'].sum()*h),1.,12)

    def test_polygon_fourier_matches_rectangle_analytic_and_translation(self):
        rectangle=dict(shape='polygon',vertices=[[-.2,-.1],[.2,-.1],[.2,.1],[-.2,.1]])
        for q in ([0,0],[1,0],[0,2],[2,3],[-2,-3]):
            expected=.08*np.sinc(q[0]*.4)*np.sinc(q[1]*.2)
            self.assertAlmostEqual(abs(pc.shape_fourier(rectangle,q)-expected),0.,13)
        translated=copy.deepcopy(rectangle);translated['vertices']=(np.array(rectangle['vertices'])+[.1,.2]).tolist()
        self.assertAlmostEqual(abs(pc.shape_fourier(translated,[1,2])-pc.shape_fourier(rectangle,[1,2])*np.exp(-2j*np.pi*.5)),0.,13)

    def test_chebyshev_derivative_and_integral(self):
        x,D,w=pc.chebyshev(12)
        np.testing.assert_allclose(D@(x*x),2*x,atol=2e-13)
        self.assertAlmostEqual(float(w@(x*x)),1/3,13)

    def test_triangle_fourier_matches_independent_area_quadrature(self):
        shape=pc.paper_example('hole','RIT')['shapes'][0]
        points=np.array(shape['vertices']);a,b,c=points
        nodes,weights=np.polynomial.legendre.leggauss(32)
        u=(nodes+1)/2;w=weights/2
        xx=a[None,None,:]+u[:,None,None]*(b-a)+(1-u[:,None,None])*u[None,:,None]*(c-a)
        area2=abs(np.linalg.det(np.stack([b-a,c-a])))
        for q in ([0,0],[1,0],[0,2],[2,3],[-2,-3]):
            integral=np.sum(np.exp(-2j*np.pi*(xx@q))*(1-u[:,None])*w[:,None]*w[None,:])*area2
            self.assertLess(abs(pc.shape_fourier(shape,q)-integral),1e-13)

    def test_changed_stack_and_pattern_reach_actual_solver(self):
        sample=pc.paper_example();sample.update(grid_nm=2.,harmonics=2,pad_nm=2000.)
        cfg=pc.prepare({},sample);row,profile=pc.vertical(cfg);C,flux=pc.coupling(cfg,profile,row)
        self.assertTrue(row['guided']);self.assertGreater(row['Gamma_QW'],0)
        self.assertLess(flux['green_flux_relative_error'],1e-7)
        changed=copy.deepcopy(sample);changed['shapes'][0]['radius']*=.8
        other=pc.prepare({},changed);row2,_=pc.vertical(other)
        self.assertGreater(abs(row2['frequency']-row['frequency']),1e-5)
        self.assertEqual(C.shape,(4,4));self.assertTrue(np.isfinite(C).all())

    def test_invalid_geometry_returns_exact_field_address(self):
        sample=pc.paper_example();sample['shapes'][0]['radius']=1.
        with self.assertRaises(pc.InputValidationError) as caught:pc.prepare({},sample)
        self.assertEqual(caught.exception.diagnostics[0]['field'],'shapes')
        self.assertEqual(caught.exception.diagnostics[0]['object_id'],'circle-0')

    def test_actual_vertical_outputs_contain_saved_quantities(self):
        sample=pc.paper_example('pillar');sample.update(grid_nm=2.,pad_nm=1500.)
        with tempfile.TemporaryDirectory(prefix='ods_pcsel_',dir=Path(__file__).resolve().parents[3]) as name:
            result=pc.execute(pc.prepare({},sample),name)
            profile=np.genfromtxt(Path(name)/'vertical_profile.csv',delimiter=',',names=True)
            self.assertTrue(np.all(profile['intensity_per_nm']>=0))
            self.assertEqual(result['model'],'vertical')
            self.assertFalse(result['convergence_established'])

    def test_actual_geometry_and_accuracy_sweep_changes_outputs(self):
        sample=pc.paper_example();sample.update(grid_nm=2.,pad_nm=1500.)
        radius=sample['shapes'][0]['radius']
        sample['parameter_sweep']=dict(parameters=[
            dict(path='shapes',object_id='circle-0',field='radius',values=[radius,radius*.8]),
            dict(path='grid_nm',values=[2.,1.])])
        prepared=pc.prepare({},sample)
        with tempfile.TemporaryDirectory(prefix='ods_pcsel_sweep_',dir=Path(__file__).resolve().parents[3]) as name:
            result=pc.execute(prepared,name)
            self.assertEqual(result['completed_cases'],4)
            self.assertEqual(result['status'],'complete')
            frequencies=[case['summary']['vertical']['frequency'] for case in result['cases']]
            self.assertGreater(abs(frequencies[0]-frequencies[2]),1e-5)
            self.assertLess(abs(frequencies[0]-frequencies[1]),abs(frequencies[0]-frequencies[2]))
            self.assertFalse(result['convergence_established'])
            self.assertTrue((Path(name)/'pcsel_sweep.csv').is_file())

    def test_sweep_preflights_all_cases_and_rejects_crossing_polygon(self):
        sample=pc.paper_example()
        sample['parameter_sweep']=dict(parameters=[dict(path='shapes',object_id='circle-0',field='radius',values=[.1,1.])])
        with self.assertRaises(pc.InputValidationError) as caught:pc.prepare({},sample)
        self.assertEqual(caught.exception.diagnostics[0]['field'],'parameter_sweep')
        sample.pop('parameter_sweep')
        theta=np.arange(5)*2*np.pi/5
        vertices=np.column_stack([np.cos(theta),np.sin(theta)])*.2
        sample['shapes']=[dict(id='star',shape='polygon',vertices=vertices[[0,2,4,1,3]].tolist())]
        with self.assertRaises(pc.InputValidationError):pc.prepare({},sample)

    def test_fill_and_offset_sweep_preserves_pattern_family(self):
        for shape in ('CC','RIT'):
            sample=pc.paper_example('hole',shape)
            sample['parameter_sweep']=dict(parameters=[dict(path='fill_fraction',values=[.08,.12]),dict(path='center_scale',values=[.8,1.])])
            cases=pc.prepare({},sample)['parameter_sweep']['cases']
            for case in cases:
                self.assertAlmostEqual(case['prepared']['fill_fraction'],case['parameters']['fill_fraction'],12)
                self.assertEqual(len(case['prepared']['shapes']),len(sample['shapes']))
        sample=pc.paper_example();sample['parameter_sweep']=dict(parameters=[dict(path='shapes',object_id='circle-0',field='center_x',values=[-.2,-.15])])
        cases=pc.prepare({},sample)['parameter_sweep']['cases']
        self.assertEqual([case['prepared']['shapes'][0]['center'][0] for case in cases],[-.2,-.15])

    def test_saved_mode_beam_tracks_power_and_rejects_changed_geometry(self):
        sample=pc.paper_example();sample.update(model='beam',grid_nm=2.,pad_nm=2000.,harmonics=2,
            collocation_order=8,beam_grid=32,beam_padding=2)
        with tempfile.TemporaryDirectory(prefix='ods_pcsel_saved_',dir=Path(__file__).resolve().parents[3]) as name:
            directory=Path(name);first=pc.execute(pc.prepare({},sample),directory/'first')
            self.assertIn('beam_mode',first)
            sample.update(beam_saved_run=str(directory/'first'),beam_mode=first['beam_mode'],
                beam_normalization='calibrated_power',beam_power_W=.2,beam_power_source='Explicit synthetic QA calibration')
            with patch.object(pc,'finite_modes',side_effect=AssertionError('Saved modes should be reused')):
                result=pc.execute(pc.prepare({},sample),directory/'second')
            self.assertEqual(result['beam_mode'],first['beam_mode'])
            self.assertAlmostEqual(result['polarization_power_fraction_x']+result['polarization_power_fraction_y'],1.,12)
            with np.load(directory/'second'/'beam_fields.npz',allow_pickle=False) as arrays:
                np.testing.assert_allclose(arrays['far_display'],arrays['far_paraxial_per_sr']*.2)
            sample['aperture_um']=[210.,200.]
            with self.assertRaises(pc.InputValidationError):pc._saved_finite(pc.prepare({},sample))

    def test_failed_optional_cavity_keeps_completed_vertical_and_coupling_outputs(self):
        sample=pc.paper_example();sample.update(model='beam',grid_nm=2.,pad_nm=2000.,harmonics=1)
        with tempfile.TemporaryDirectory(prefix='ods_pcsel_partial_',dir=Path(__file__).resolve().parents[3]) as name:
            with patch.object(pc,'finite_modes',side_effect=RuntimeError('Unconverged cavity')):
                result=pc.execute(pc.prepare({},sample),name)
            self.assertEqual(result['status'],'partial')
            self.assertTrue((Path(name)/'coupled_modes.csv').is_file())
            self.assertFalse((Path(name)/'beam_fields.npz').exists())
            self.assertIn('Unconverged cavity',result['optional_output_error'])

    def test_bad_layer_targets_exact_property_and_poles_respect_bounds(self):
        sample=pc.paper_example();sample['layers'][2]['thickness_nm']=-1
        with self.assertRaises(pc.InputValidationError) as caught:pc.prepare({},sample)
        self.assertEqual(caught.exception.diagnostics[0]['field'],'layers.layer-2.thickness_nm')
        self.assertEqual(caught.exception.diagnostics[0]['object_id'],'layer-2')
        sample=pc.paper_example();sample.update(model='rcwa_poles',pole_seeds=[[.29,-1e-4]],pole_bounds=[[.3,.4],[-.01,-1e-6]])
        with self.assertRaises(pc.InputValidationError) as caught:pc.prepare({},sample)
        self.assertEqual(caught.exception.diagnostics[0]['field'],'pole_seeds')


if __name__=='__main__':unittest.main()
