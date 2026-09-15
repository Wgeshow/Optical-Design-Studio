import copy
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from field_tracking import enrich_fields,feature_vector,compare_fields


def field_fixture(directory, thicknesses=(1.,3.), grid=6, field=None, magnetic=True,
                  fractions=(1/6,.5,5/6), wavelength=1550., polarization='s'):
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    model = dict(ax=1.,ay=1.,polarization=polarization,phi=0.,points=[[0.,0.,0.]],
                 materials=[dict(name='Host',model='constant_nk',a=1.5,b=.1),
                            dict(name='Air',model='constant_nk',a=1.,b=0.),
                            dict(name='Unused',model='constant_nk',a=2.,b=0.)],
                 layers=[dict(name='Above',thickness=0.,material='Air')]+[
                     dict(name='Layer'+str(i),thickness=t,material='Host') for i,t in enumerate(thicknesses)
                 ]+[dict(name='Below',thickness=0.,material='Air')],
                 patterns=[dict(layer='Layer0',material='Air')])
    (directory/'field_model.json').write_text(json.dumps(dict(model=model,wavelength_nm=wavelength,
                  settings=dict(grid=grid,sampling_mode='fixed_target'))),encoding='utf-8')
    headers=['plane','layer','x_um','y_um','z_um']+[c+'_'+part for c in ('Ex','Ey','Ez') for part in ('real','imag')]+['E2','material']
    if magnetic:
        headers += [c+'_'+part for c in ('Hx','Hy','Hz') for part in ('real','imag')]+['Sx','Sy','Sz']
    with (directory/'electric_fields.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream)
        writer.writerow(headers)
        start=0.
        for layer,t in enumerate(thicknesses):
            for depth in fractions:
                for i in range(grid):
                    for j in range(grid):
                        x,y=(i+.5)/grid-.5,(j+.5)/grid-.5
                        e = field(x,y,depth,layer) if field else (1.+0j,0j,0j)
                        row=['volume_samples','Layer'+str(layer),x,y,start+t*depth]
                        row += [v for c in e for v in (complex(c).real,complex(c).imag)]
                        row += [sum(abs(c)**2 for c in e),'Air' if layer==0 and i<grid//2 else 'Host']
                        if magnetic:
                            row += [0.,0.,1.,0.,0.,0.,0.,0.,.5]
                        writer.writerow(row)
            start += t
    return enrich_fields(directory)


class FieldTrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make(self,name,**kwargs):
        return field_fixture(self.directory/name,**kwargs)

    def test_uniform_intensity_uses_volume_not_layer_count(self):
        result=self.make('uniform')
        self.assertAlmostEqual(result['layers']['Layer0']['E2_fraction'],.25)
        self.assertAlmostEqual(result['layers']['Layer1']['E2_fraction'],.75)
        self.assertAlmostEqual(result['global_metrics']['mean_E2'],1.)
        self.assertAlmostEqual(result['global_metrics']['integrated_E2_um3'],4.)
        self.assertAlmostEqual(result['materials']['Air']['E2_fraction'],.125)
        self.assertEqual(result['materials']['Unused']['E2_fraction'],0.)
        self.assertAlmostEqual(result['layers']['Layer0']['pattern_material_E2_fraction'],.5)
        self.assertIsNone(result['layers']['Layer0']['centroid']['x_um'])
        self.assertIsNone(result['layers']['Layer0']['hotspot']['x_um'])
        self.assertAlmostEqual(result['global_metrics']['centroid']['z_um'],2.)
        self.assertIn('not stored-energy',result['definition'])

    def test_poynting_and_loss_proxy_have_explicit_convention(self):
        result=self.make('flux')
        self.assertTrue(result['magnetic_fields_available'])
        self.assertAlmostEqual(result['layers']['Layer0']['mean_poynting']['z'],.5)
        self.assertAlmostEqual(result['layers']['Layer1']['mean_loss_proxy'],.3)
        self.assertAlmostEqual(result['global_metrics']['mean_loss_proxy'],.2625)
        self.assertAlmostEqual(feature_vector(result)['global.flux_z'],math.log1p(.5))

    def test_overlap_is_phase_and_amplitude_invariant(self):
        reference=self.make('reference')
        phase=self.make('phase',field=lambda *args:(2j,0j,0j))
        self.assertAlmostEqual(compare_fields(phase,reference)['field_overlap'],1.)
        orthogonal=self.make('orthogonal',field=lambda *args:(0j,1.+0j,0j))
        self.assertAlmostEqual(compare_fields(orthogonal,reference)['field_overlap'],0.)

    def test_periodic_centroid_tracks_across_cell_boundary(self):
        def localized(center):
            return lambda x,y,z,layer:(math.exp(-(((x-center+.5)%1-.5)/.08)**2),0.,0.)
        reference=self.make('left',grid=40,field=localized(.4))
        shifted=self.make('right',grid=40,field=localized(-.4))
        comparison=compare_fields(shifted,reference)
        self.assertTrue(comparison['compatible'])
        self.assertAlmostEqual(comparison['layers']['Layer0']['centroid_shift_fraction']['x'],.2,places=5)
        self.assertLess(comparison['field_overlap'],.1)
        self.assertLessEqual(len(reference['signature']['Layer0']['values']),6*6*3)

    def test_thickness_change_compares_in_layer_coordinates(self):
        reference=self.make('thin')
        thick=self.make('thick',thicknesses=(2.,4.),wavelength=1554.)
        comparison=compare_fields(thick,reference)
        self.assertTrue(comparison['compatible'])
        self.assertAlmostEqual(comparison['field_overlap'],1.)
        self.assertAlmostEqual(comparison['layers']['Layer1']['centroid_shift_fraction']['z'],0.)
        self.assertAlmostEqual(comparison['layers']['Layer1']['centroid_displacement_um']['z'],1.5)
        self.assertEqual(comparison['wavelength_shift_nm'],4.)

    def test_incompatible_layers_grid_and_illumination_are_rejected(self):
        reference=self.make('reference')
        for name,kwargs in [('layer',dict(thicknesses=(1.,))),('grid',dict(grid=4)),('polarization',dict(polarization='p'))]:
            with self.subTest(name=name):
                result=compare_fields(self.make(name,**kwargs),reference)
                self.assertFalse(result['compatible'])
                self.assertIn('Incompatible',result['reason'])

    def test_legacy_missing_magnetic_fields_and_quadrature_are_honest(self):
        legacy=self.make('legacy',magnetic=False,fractions=(.25,.5,.75),field=lambda x,y,z,layer:(z,0.,0.))
        self.assertFalse(legacy['magnetic_fields_available'])
        self.assertEqual(legacy['sampling_method'],'legacy_depth_voronoi')
        self.assertEqual(legacy['depth_weights'],[.375,.25,.375])
        self.assertAlmostEqual(legacy['global_metrics']['mean_E2'],.296875)
        self.assertNotIn('global.flux_z',feature_vector(legacy))
        self.assertFalse(compare_fields(legacy,self.make('new'))['compatible'])

    def test_vector_finite_and_schema_stable_for_uniform_and_localized_fields(self):
        uniform=feature_vector(self.make('uniform'))
        localized=feature_vector(self.make('localized',field=lambda x,y,z,l:(math.exp(-20*x*x),0.,0.)))
        self.assertEqual(set(uniform),set(localized))
        self.assertTrue(all(math.isfinite(v) for v in uniform.values()))
        self.assertEqual(uniform['layer0.spread_x_defined'],0.)
        self.assertEqual(localized['layer0.spread_x_defined'],1.)
        self.assertTrue(all('wavelength' not in key and 'basis' not in key for key in uniform))

    def test_incomplete_csv_is_not_silently_used_for_training(self):
        self.make('incomplete')
        path=self.directory/'incomplete'/'electric_fields.csv'
        lines=path.read_text().splitlines()
        path.write_text('\n'.join(lines[:-1])+'\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Incomplete field data'):
            enrich_fields(path.parent)


class NativeFieldDescriptorTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'pcs_s4_runtime').is_dir(),'Native S4 runtime is not present beside staged sources')
    def test_native_uniform_medium_has_forward_half_unit_flux(self):
        from field_solver import sample_fields
        from model import DEFAULT_PERFORMANCE
        from test_backend import sample
        model=sample(wl_start_nm=1550,wl_stop_nm=1550)
        for material in model['materials']:
            material.update(a=1.,b=0.)
        with tempfile.TemporaryDirectory() as directory:
            result=sample_fields(model,dict(DEFAULT_PERFORMANCE),dict(wavelength_nm=1550.,grid=3,maps=False),directory)
            self.assertAlmostEqual(result['global_metrics']['mean_E2'],1.,places=7)
            self.assertAlmostEqual(result['global_metrics']['mean_poynting']['z'],.5,places=7)
            self.assertAlmostEqual(result['global_metrics']['mean_poynting']['x'],0.,places=7)
            self.assertTrue(result['magnetic_fields_available'])
            with (Path(directory)/'electric_fields.csv').open(newline='') as stream:
                rows=list(csv.DictReader(stream))
            self.assertIn('Hy_imag',rows[0])
            self.assertAlmostEqual(float(rows[0]['Sz']),.5,places=7)


if __name__ == '__main__':
    unittest.main()
