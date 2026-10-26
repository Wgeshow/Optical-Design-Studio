"""Numerical and topology contracts for array-native field postprocessing."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from contour_sweep import describe_arrays, shape_features, sweep
from field_storage import load_field_arrays
from field_tracking import _signature_arrays, _statistics_arrays, enrich_fields
from test_field_tracking import field_fixture


class ArrayDescriptorTests(unittest.TestCase):
    def test_direct_arrays_need_no_raw_file_and_preserve_airhole_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            expected=field_fixture(directory,grid=4,field=lambda x,y,z,l:(1+x+1j*y,z,0.2j))
            arrays=load_field_arrays(directory)
            (directory/'electric_fields.csv').unlink()
            extra=dict(schema_version=1,objective=2.0,depth_profile=[dict(z_um=.25)])
            (directory/'airhole_field_metrics.json').write_text(json.dumps(extra))
            with patch('field_storage.load_field_arrays',side_effect=AssertionError('raw reread')):
                actual=enrich_fields(directory,arrays)
            self.assertEqual(actual['global_metrics'],expected['global_metrics'])
            self.assertEqual(actual['signature'],expected['signature'])
            self.assertEqual(actual['contour_features'],expected['contour_features'])
            self.assertEqual(actual['airhole_views']['depth_profile'],extra['depth_profile'])
            self.assertEqual(actual['airhole_views']['contour_features'],actual['contour_features'])

    def test_signature_reduction_preserves_bin_order_and_complex_means(self):
        rng=np.random.default_rng(10)
        grid,depths=9,4
        xy=(np.arange(grid)+.5)/grid-.5
        xyz=np.array([(x,y,(z+.5)/depths) for z in range(depths) for x in xy for y in xy])
        electric=rng.normal(size=xyz.shape)+1j*rng.normal(size=xyz.shape)
        zi=np.repeat(np.arange(depths),grid*grid)
        shuffle=rng.permutation(len(xyz));xyz,electric,zi=xyz[shuffle],electric[shuffle],zi[shuffle]
        weights=np.full(depths,1/depths)
        actual=_signature_arrays(xyz,electric,grid,zi,weights,1.,1.)
        bins={}
        for position,e,z in zip(xyz,electric,zi):
            ix=min(grid-1,int((position[0]+.5)*grid))
            iy=min(grid-1,int((position[1]+.5)*grid))
            bins.setdefault((z,ix*6//grid,iy*6//grid),[]).append(e)
        expected=[];expected_weights=[]
        for key,samples in sorted(bins.items()):
            mean=np.mean(samples,axis=0)
            expected.append([v for c in mean for v in (c.real,c.imag)])
            expected_weights.append(weights[key[0]]*len(samples)/(grid*grid))
        np.testing.assert_allclose(actual['values'],expected,rtol=1e-14,atol=1e-14)
        np.testing.assert_array_equal(actual['weights'],expected_weights)

    def test_statistics_match_scalar_weighted_components_flux_and_ties(self):
        xyz=np.array([[.1,.2,.1],[.2,.3,.4],[.3,.4,.8]])
        electric=np.array([[1+2j,2j,3.],[2-1j,2.,3j],[.1j,.2,.3]])
        magnetic=np.array([[1j,2.,3.],[3.,2j,1.],[.2,.4j,.6]])
        weights=np.array([.2,.3,.5]);intensity=np.sum(abs(electric)**2,axis=1)
        loss=.4*intensity
        actual=_statistics_arrays(xyz,electric,magnetic,intensity,loss,weights,1.,1.,0.,1.)
        total=sum(float(w)*sum(abs(complex(v))**2 for v in e) for w,e in zip(weights,electric))
        self.assertAlmostEqual(actual['integrated_E2_um3'],total)
        for i,c in enumerate(('Ex','Ey','Ez')):
            expected=sum(float(w)*abs(complex(e[i]))**2 for w,e in zip(weights,electric))/total
            self.assertAlmostEqual(actual['component_fractions'][c],expected)
        for i,axis in enumerate('xyz'):
            expected=sum(float(w)*.5*(e[(i+1)%3]*h[(i+2)%3].conjugate()-
                                     e[(i+2)%3]*h[(i+1)%3].conjugate()).real
                         for w,e,h in zip(weights,electric,magnetic))/sum(weights)
            self.assertAlmostEqual(actual['mean_poynting'][axis],expected)
        self.assertEqual(actual['hotspot']['tied_samples'],2)
        self.assertEqual(actual['hotspot']['x_um'],.1)

    def test_duplicate_coordinate_rejected_before_descriptor_or_contour(self):
        with tempfile.TemporaryDirectory() as tmp:
            field_fixture(tmp,grid=4)
            arrays=load_field_arrays(tmp)
            arrays['xyz'][1]=arrays['xyz'][0]
            with self.assertRaisesRegex(ValueError,'missing or duplicate'):
                enrich_fields(tmp,arrays)
            with self.assertRaisesRegex(ValueError,'Incomplete contour map'):
                describe_arrays(tmp,arrays)

    def test_array_legacy_e_only_retains_voronoi_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            field_fixture(tmp,grid=3,magnetic=False,fractions=(.25,.5,.75))
            arrays=load_field_arrays(tmp)
            (Path(tmp)/'electric_fields.csv').unlink()
            actual=enrich_fields(tmp,arrays)
            self.assertFalse(actual['magnetic_fields_available'])
            self.assertEqual(actual['depth_weights'],[.375,.25,.375])
            self.assertNotIn('mean_poynting',actual['global_metrics'])


class VectorizedContourTests(unittest.TestCase):
    def test_stack_contours_keep_nonuniform_depth_area_and_layer_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=dict(ax=1.,ay=2.,layers=[dict(name='Above',thickness=0.),
                       dict(name='B',thickness=1.),dict(name='A',thickness=3.),
                       dict(name='Below',thickness=0.)])
            (Path(tmp)/'field_model.json').write_text(json.dumps(dict(model=model,settings=dict(grid=3))))
            points=[];labels=[]
            for label,start,thickness,depths in [(0,0.,1.,2),(1,1.,3.,4)]:
                for z in start+thickness*(np.arange(depths)+.5)/depths:
                    for x in (-1/3,0.,1/3):points.append([x,0.,z]);labels.append(label)
            xyz=np.asarray(points);electric=np.zeros_like(xyz,dtype=complex);electric[:,0]=1.
            order=np.random.default_rng(1).permutation(len(xyz))
            arrays=dict(xyz=xyz[order],E=electric[order],plane=np.full(len(xyz),2),
                        layer=np.asarray(labels)[order],layer_names=np.asarray(['B','A']))
            actual=describe_arrays(tmp,arrays)
            self.assertEqual(set(actual['views']),{'layer0.xz','layer1.xz','stack.xz'})
            for name,area in [('layer0.xz',1.),('layer1.xz',3.),('stack.xz',4.)]:
                region=actual['views'][name]['Ex']['levels'][0]['regions'][0]
                self.assertAlmostEqual(region['area'],area)
                self.assertTrue(region['wrap_x'])
            stack=actual['views']['stack.xz']['Ex']['levels'][0]['regions'][0]
            self.assertAlmostEqual(stack['centroid_y'],2.)

    def test_random_regions_retain_pixels_lineage_and_weighted_statistics(self):
        rng=np.random.default_rng(9)
        a=np.round(rng.random((8,11))*2,2)
        area=rng.uniform(.1,2,size=a.shape)
        xs=np.linspace(-1,1,a.shape[1]);ys=np.linspace(0,4,a.shape[0])
        for periodic_x,periodic_y in [(False,False),(True,False),(True,True)]:
            result=sweep(a,.15,area,xs,ys,periodic_x,periodic_y)
            previous=np.zeros(a.shape,dtype=int)
            for level in result['levels']:
                current=np.zeros_like(previous)
                for region in level['regions']:
                    mask=np.zeros(a.shape,dtype=bool)
                    for row,start,count in region['pixel_runs']:mask[row,start:start+count]=True
                    jj,ii=np.where(mask);weights=area[mask]
                    self.assertEqual(region['parents'],sorted(int(v) for v in np.unique(previous[mask]) if v))
                    self.assertEqual(region['pixels'],int(mask.sum()))
                    self.assertAlmostEqual(region['area'],float(weights.sum()))
                    self.assertAlmostEqual(region['centroid_x'],float(np.average(xs[ii],weights=weights)))
                    self.assertAlmostEqual(region['centroid_y'],float(np.average(ys[jj],weights=weights)))
                    self.assertAlmostEqual(region['mean'],float(np.average(a[mask],weights=weights)))
                    self.assertEqual(region['peak'],float(a[mask].max()))
                    self.assertEqual(region['wrap_x'],bool(periodic_x and mask[:,0].any() and mask[:,-1].any()))
                    self.assertEqual(region['wrap_y'],bool(periodic_y and mask[0,:].any() and mask[-1,:].any()))
                    current[mask]=region['id']
                np.testing.assert_array_equal(current>0,a>=level['level'])
                previous=current

    def test_separable_shape_moments_match_full_image_formula(self):
        rng=np.random.default_rng(11)
        a=rng.random((7,9));result=sweep(a,.1)
        actual=shape_features(result,a,'test.')
        yy,xx=np.meshgrid((np.arange(7)+.5)/7,(np.arange(9)+.5)/9,indexing='ij')
        levels=np.r_[np.arange(17)*result['step'],np.linspace(0,result['maximum'],17)]
        for k,level in enumerate(levels):
            mask=a>=level
            self.assertEqual(actual[f'test.shape.{k}.area'],float(mask.mean()))
            for axis,coordinates in [('x',xx),('y',yy)]:
                for harmonic in (1,2):
                    expected=np.mean(mask*np.exp(2j*np.pi*harmonic*coordinates))
                    self.assertAlmostEqual(actual[f'test.shape.{k}.{axis}{harmonic}.cos'],float(expected.real),places=14)
                    self.assertAlmostEqual(actual[f'test.shape.{k}.{axis}{harmonic}.sin'],float(expected.imag),places=14)


if __name__=='__main__':
    unittest.main()
