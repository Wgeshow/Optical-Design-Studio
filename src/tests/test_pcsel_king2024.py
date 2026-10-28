import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pcsel_research as pc
from pcsel_paper_studies import (king2024_example, triangle_vertices, periodic_triangle_overlap,
    coupling_diagnostics, design_metrics, figure_manifest)

class King2024Tests(unittest.TestCase):
    def test_table_and_weakened_structure_only_changes_reported_layers(self):
        original=king2024_example('fig5');weak=king2024_example('fig9')
        a={r['id']:r for r in original['layers']};b={r['id']:r for r in weak['layers']}
        self.assertEqual(len(a),38)
        changed={key for key in a if a[key]!=b[key]}
        self.assertEqual(changed,{'photonic-crystal','qw-pc-spacer'})
        self.assertEqual(a['photonic-crystal']['thickness_nm'],150.)
        self.assertEqual(b['photonic-crystal']['thickness_nm'],100.)
        self.assertEqual(original['lattice_nm'],320.)
        self.assertAlmostEqual(original['inclusion_index']**2,10.1)
        self.assertEqual(a['p-cladding']['thickness_nm'],1565.)
        self.assertNotIn('target',json.dumps(original).lower())

    def test_no_dbr_unknown_thickness_blocks_exact_field(self):
        cfg=king2024_example('fig3')
        with self.assertRaises(pc.InputValidationError) as caught:pc.prepare({},cfg)
        self.assertEqual(caught.exception.diagnostics[0]['field'],'layers.p-cladding.thickness_nm')
        self.assertIsNone(next(r for r in cfg['layers'] if r['id']=='p-cladding')['thickness_nm'])

    def test_triangle_area_symmetry_and_fourier_translation(self):
        shape=dict(id='t',shape='triangle',base_length=.75,base_angle_deg=70.,rotation_deg=-45.,center=[0.,0.])
        item=pc._shape(shape,0);v=np.asarray(item['vertices'])
        expected=.75**2*np.tan(np.deg2rad(70))/4
        self.assertAlmostEqual(pc.shape_fourier(item,[0,0]).real,expected,14)
        self.assertFalse(periodic_triangle_overlap(v))
        np.testing.assert_allclose(sorted(map(tuple,v)),sorted(map(tuple,v[:,::-1])),atol=1e-14)
        moved=copy.deepcopy(item);moved['vertices']=(v+[.1,.2]).tolist()
        for q in ([1,0],[2,-1]):
            self.assertAlmostEqual(abs(pc.shape_fourier(item,q).conjugate()-pc.shape_fourier(item,-np.array(q))),0.,14)
            self.assertAlmostEqual(abs(pc.shape_fourier(moved,q)-pc.shape_fourier(item,q)*np.exp(-2j*np.pi*np.dot(q,[.1,.2]))),0.,14)

    def test_periodic_overlap_distinguishes_crossing_from_self_overlap(self):
        good=triangle_vertices(dict(base_length=.75,base_angle_deg=70.,rotation_deg=-45.,center=[.2,.2]))
        self.assertGreater(np.max(good),.5)
        self.assertFalse(periodic_triangle_overlap(good))
        bad=triangle_vertices(dict(base_length=1.2,base_angle_deg=80.,rotation_deg=-45.))
        self.assertTrue(periodic_triangle_overlap(bad))

    def test_square_sweep_and_geometry_mask_preserve_explicit_values(self):
        cfg=king2024_example('fig6');cfg['parameter_sweep']={'parameters':[{'path':'aperture_um','field':'side','values':[1000.,2000.]}]}
        cases=pc.prepare({},cfg)['parameter_sweep']['cases']
        self.assertEqual([r['prepared']['aperture_um'] for r in cases],[[1000.,1000.],[2000.,2000.]])
        cfg=king2024_example('fig5');cfg['parameter_sweep']={'parameters':[{'path':'shapes','object_id':'triangle','field':'base_length','values':[.75,1.2]}], 'invalid_geometry':'mask'}
        cases=pc.prepare({},cfg)['parameter_sweep']['cases']
        self.assertIsNotNone(cases[0]['prepared']);self.assertEqual(cases[1]['status'],'invalid_geometry')
        cfg['parameter_sweep']['invalid_geometry']='error'
        with self.assertRaises(pc.InputValidationError):pc.prepare({},cfg)

    def test_finite_vertical_interval_and_group_index_identity(self):
        cfg=king2024_example('fig5');cfg.pop('parameter_sweep');cfg=pc.prepare({},cfg)
        row,profile=pc.vertical(cfg);h=profile['grid_nm'];length=sum(x['thickness_nm'] for x in cfg['layers'])
        self.assertAlmostEqual(profile['z_nm'][-1]+h,length,10)
        self.assertAlmostEqual(row['effective_group_index'],np.sum(profile['index']**2*profile['field']**2)*h/row['effective_index'],13)
        self.assertGreater(row['Gamma_QW'],0)
        self.assertIn('Dirichlet',row['confinement_scope'])

    def test_external_air_and_matched_semiconductor_radiation_differ(self):
        cfg=king2024_example('fig5');cfg.pop('parameter_sweep');cfg['harmonics']=1
        cfg=pc.prepare({},cfg);row,profile=pc.vertical(cfg)
        a,af=pc.coupling(cfg,profile,row)
        cfg['radiation_boundary']='matched_external'
        b,bf=pc.coupling(cfg,profile,row)
        self.assertGreater(np.linalg.norm(a-b),1e-9)
        for C,flux in [(a,af),(b,bf)]:
            H=(C+C.conj().T)/2;R=(C-C.conj().T)/(2j)
            np.testing.assert_allclose(H,H.conj().T,atol=1e-15)
            self.assertGreater(np.linalg.eigvalsh(R).min(),-1e-14)
            self.assertLess(flux['green_flux_relative_error'],1e-6)
            self.assertTrue(0<=flux['up_fraction']<=1)

    def test_diagnostics_do_not_fit_reference_values(self):
        H=np.diag([1.,2.,3.,4.]).astype(complex);H[0,1]=2+3j;H[1,0]=2-3j
        R=np.eye(4)*.5;C=(H+1j*R)*1e-7
        result=coupling_diagnostics(C,np.zeros((4,4),complex))
        self.assertAlmostEqual(result['kappa_1d_abs_cm1'],np.sqrt(13))
        self.assertEqual(result['kappa_1d_direct_abs_cm1'],0)
        self.assertAlmostEqual(result['mu_cm1'],.5)
        metrics=design_metrics({'coupled_modes':[{'power_loss_cm1':10.},{'power_loss_cm1':5.},{'power_loss_cm1':20.},{'power_loss_cm1':30.}]})
        self.assertEqual(metrics['delta_g_A_cm1'],0.);self.assertFalse(metrics['mode_A_is_lowest'])

    def test_finite_metrics_ignore_rejected_modes(self):
        rejected=dict(total_loss_cm1=.1,accepted=False)
        first=dict(total_loss_cm1=12.,accepted=True,eta_substrate=.7,eta_surface=.1,eta_edge=.2)
        second=dict(total_loss_cm1=15.,accepted=True)
        metrics=design_metrics({'finite_modes':[rejected,second,first]})
        self.assertEqual(metrics['lowest_loss_cm1'],12.);self.assertEqual(metrics['delta_g_cm1'],3.)
        self.assertEqual(metrics['eta_substrate'],.7)
        manifest=figure_manifest(king2024_example('fig8'),{'artifacts':['finite_fields.npz'],'finite_modes':[dict(rejected,mode=0),dict(first,mode=1),dict(second,mode=2)]})
        self.assertEqual([r['mode_index'] for r in manifest['plots'] if r['kind']=='field_grid'],[1,2])

    def test_nodeless_default_and_group_index_finite_difference(self):
        cfg=king2024_example('fig9');cfg.pop('parameter_sweep');cfg=pc.prepare({},cfg)
        row,profile=pc.vertical(cfg)
        self.assertEqual(row['selected_mode_index'],0)
        self.assertEqual(row['selected_node_count'],0)
        self.assertEqual(len(row['mode_candidates']),8)
        samples=[]
        for scale in (1-1e-5,1+1e-5):
            other=copy.deepcopy(cfg);other['lattice_nm']*=scale
            result,_=pc.vertical(other)
            samples.append((2*np.pi/other['lattice_nm'],2*np.pi/result['wavelength_nm']))
        derivative=(samples[1][1]-samples[0][1])/(samples[1][0]-samples[0][0])
        self.assertAlmostEqual(derivative,1/row['effective_group_index'],6)

    def test_actual_three_beams_and_accepted_efficiency_partition(self):
        cfg=pc.paper_example();cfg.update(model='beam',grid_nm=2.,pad_nm=2000.,harmonics=1,
            collocation_order=8,beam_grid=32,beam_padding=2,beam_mode_count=3)
        with tempfile.TemporaryDirectory() as tmp:
            result=pc.execute(pc.prepare({},cfg),tmp)
            self.assertEqual(result['beam_modes_completed'],3)
            self.assertEqual(len(result['beam_outputs']),3)
            self.assertEqual(len({x['npz'] for x in result['beam_outputs']}),3)
            accepted=[r for r in result['finite_modes'] if r['accepted']]
            self.assertEqual([x['mode'] for x in result['beam_outputs']],[r['mode'] for r in accepted[:3]])
            for mode in accepted:
                self.assertLess(abs(mode['eta_substrate']+mode['eta_surface']+mode['eta_edge']-1),.02)
            for item in result['beam_outputs']:
                self.assertAlmostEqual(item['parseval_power'],1.,12)
                with np.load(Path(tmp)/item['npz']) as arrays:
                    self.assertEqual(arrays['near_display'].shape,(32,32))
                    self.assertTrue(np.isfinite(arrays['far_display']).all())

    def test_reference_wavelength_derives_period_and_matches_inverse_eigenproblem(self):
        cfg=king2024_example('fig5',formulation='reference_wavelength');cfg.pop('parameter_sweep');cfg=pc.prepare({},cfg)
        row,profile=pc.vertical(cfg)
        self.assertAlmostEqual(row['wavelength_nm'],1070.,11)
        self.assertAlmostEqual(row['effective_lattice_nm'],1070/row['effective_index'],12)
        self.assertEqual(row['selected_mode_index'],int(np.argmax([m['Gamma_core'] for m in row['mode_candidates']])))
        fixed=copy.deepcopy(cfg);fixed.update(vertical_formulation='fixed_period',lattice_nm=row['effective_lattice_nm'])
        other,_=pc.vertical(fixed)
        self.assertAlmostEqual(other['wavelength_nm'],1070.,6)
        self.assertAlmostEqual(other['effective_index'],row['effective_index'],8)
        self.assertEqual(cfg['lattice_nm'],320.)

    def test_reference_run_preserves_requested_period_and_saves_actual_period(self):
        cfg=king2024_example('fig5',formulation='reference_wavelength');cfg.pop('parameter_sweep');cfg['harmonics']=1
        with tempfile.TemporaryDirectory() as tmp:
            result=pc.execute(pc.prepare({},cfg),tmp)
            original=json.loads((Path(tmp)/'pcsel_inputs.json').read_text())
            derived=json.loads((Path(tmp)/'pcsel_derived_inputs.json').read_text())
            self.assertEqual(original['lattice_nm'],320.)
            self.assertEqual(derived['requested_lattice_nm'],320.)
            self.assertNotEqual(derived['effective_lattice_nm'],320.)
            self.assertEqual(result['derived_inputs'],derived)
            persisted=json.loads((Path(tmp)/'pcsel_summary.json').read_text())
            limits=' '.join(persisted['limitations'])
            self.assertIn('supplied reference wavelength it solves for beta',limits)
            self.assertIn('largest integrated overlap in the marked QW and photonic-crystal layers',limits)
            self.assertIn('finite-stack Dirichlet',limits)
            self.assertNotIn('fundamental scalar',limits)
            self.assertNotIn('fixes beta = 2 pi / a',limits)
            self.assertNotIn('boundary padding',limits)
            row=result['vertical'];C=np.load(Path(tmp)/'coupling_matrix.npz')['C'];values=sorted(np.linalg.eigvals(C),key=lambda v:v.real)
            expected=[row['frequency']*(1+v.real/(2*np.pi/1070*row['effective_group_index'])) for v in values]
            np.testing.assert_allclose([r['frequency'] for r in result['coupled_modes']],expected)

    def test_reference_public_coupling_consumes_derived_period(self):
        cfg=king2024_example('fig5',formulation='reference_wavelength');cfg.pop('parameter_sweep');cfg['harmonics']=1;cfg=pc.prepare({},cfg)
        row,profile=pc.vertical(cfg)
        raw,_=pc.coupling(cfg,profile,row)
        derived=copy.deepcopy(cfg);derived['lattice_nm']=row['effective_lattice_nm']
        resolved,_=pc.coupling(derived,profile,row)
        np.testing.assert_array_equal(raw,resolved)
        self.assertEqual(cfg['lattice_nm'],320.)

    def test_reference_requires_wavelength_and_rejects_ignored_period_sweep(self):
        cfg=king2024_example('fig5',formulation='reference_wavelength');cfg.pop('parameter_sweep');cfg['reference_wavelength_nm']=None
        with self.assertRaises(pc.InputValidationError) as caught:pc.prepare({},cfg)
        self.assertEqual(caught.exception.diagnostics[0]['field'],'reference_wavelength_nm')
        cfg['reference_wavelength_nm']=1070.
        cfg['parameter_sweep']={'parameters':[{'path':'lattice_nm','values':[310.,320.]}]}
        with self.assertRaises(pc.InputValidationError):pc.prepare({},cfg)

    def test_nonair_beam_does_not_report_air_angles(self):
        for cfg in [dict(top_index=2.,bottom_index=3.),dict(top_index=1.,bottom_index=1.,radiation_boundary='matched_external')]:
            with self.assertRaisesRegex(ValueError,'external air port'):pc.far_field(cfg,{}, {})

    def test_actual_single_case_and_sweep_save_metric_and_raw_mode_data(self):
        cfg=king2024_example('fig5');cfg.pop('parameter_sweep');cfg.update(harmonics=1,model='cwt')
        with tempfile.TemporaryDirectory() as tmp:
            result=pc.execute(pc.prepare({},cfg),Path(tmp)/'single')
            self.assertEqual([r['label'] for r in result['coupled_modes']],list('ABCD'))
            C=np.load(Path(tmp)/'single'/'coupling_matrix.npz')['C']
            expected=sorted(np.linalg.eigvals(C),key=lambda v:v.real)
            np.testing.assert_allclose([r['power_loss_cm1'] for r in result['coupled_modes']],[2*v.imag*1e7 for v in expected])
            self.assertTrue((Path(tmp)/'single'/'pcsel_design_metrics.csv').exists())
            cfg['parameter_sweep']={'parameters':[{'path':'shapes','object_id':'triangle','field':'base_length','values':[.75,1.2]}], 'invalid_geometry':'mask'}
            sweep=pc.execute(pc.prepare({},cfg),Path(tmp)/'sweep')
            self.assertEqual(sweep['completed_cases'],1);self.assertEqual(sweep['invalid_geometry_cases'],1)
            data=np.genfromtxt(Path(tmp)/'sweep'/'pcsel_sweep.csv',delimiter=',',names=True,dtype=None,encoding='utf-8')
            self.assertEqual(data['status'][1],'invalid_geometry')
            self.assertTrue(np.isnan(data['g_A_cm1'][1]))
            self.assertTrue((Path(tmp)/'sweep'/'pcsel_sweep_modes.csv').exists())

if __name__=='__main__':unittest.main()
