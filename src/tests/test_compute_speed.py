"""Numerical parity for shared solves, layer modes and Fourier field sampling."""
import copy
import csv
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from backend import build_simulation, execute, load_runtime, Cancelled
from model import DEFAULT_PERFORMANCE, performance, epsilon
from field_sampling import FourierFieldSampler
from field_solver import sample_fields
from scan_storage import FieldSampleIndex, SpectrumResults
from simulation_fields import SimulationFieldRecorder
from contour_sweep import regions, _regions_reference, _regions_runs, sweep
from tests.test_backend import sample


class ComputeSpeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.perf=performance(dict(workers=1,threads=1),1,32)
        cls.module=load_runtime(cls.perf)

    def configure(self,model,wave=1500.,reuse=True):
        sim=build_simulation(self.module,model,wave,reuse_layers=reuse)
        sim.SetFrequency(1000/wave)
        pol=model['polarization']
        s,p=(1.,0.) if pol=='s' else (0.,-1.) if pol=='p' else (2**-.5,-2**-.5)
        sim.SetExcitationPlanewave(IncidenceAngles=(model['points'][0][2],model['phi']),sAmplitude=complex(s),pAmplitude=complex(p))
        return sim

    def test_fourier_planes_match_all_phasors_with_small_output_grid_and_oblique_dispersion(self):
        for angle,phi,pol,shape in ((0,0,'p','circle'),(23,37,'s','ellipse'),(43,81,'45° s+p','rectangle')):
            model=sample(NumG=49,theta_deg=angle,phi_deg=phi,polarization=pol,ay_um=.57)
            model['materials'][0].update(model='table_nk',table=[[1300,1.3,.01],[1600,1.5,.02]],grid=[1300,1600])
            model['patterns'][0].update(shape=shape,sx=.15,sy=.09,angle=27,cx=.035,cy=-.045)
            sim=self.configure(model)
            sampler=FourierFieldSampler(sim,model,1500.)
            for z in (.02,.12,.23):
                for count in (3,12,25):
                    xs=model['ax']*((np.arange(count)+.5)/count-.5)
                    ys=model['ay']*((np.arange(count)+.5)/count-.5)
                    e,h=sampler.grid(xs,ys,z)
                    for i,j in ((0,0),(count//2,count//2),(count-1,count-1)):
                        expected=sim.GetFields(float(xs[i]),float(ys[j]),z)
                        np.testing.assert_allclose([e[i,j],h[i,j]],expected,rtol=2e-10,atol=2e-12)
                xy=[(.113,-.037),(-.285,.12),(1.3,-.71)]
                e,h=sampler.GetFieldsMany(xy,z)
                for i,(x,y) in enumerate(xy):
                    np.testing.assert_allclose([e[i],h[i]],sim.GetFields(x,y,z),rtol=2e-10,atol=2e-12)
            self.assertIn(sampler.stats['method'],('validated_fourier_planes','validated_native_coefficients'))
            self.assertLessEqual(len(sampler.cache),8)
            self.assertEqual(sampler.stats['point_calls'],3)

    def test_mismatching_native_grid_uses_scalar_fallback(self):
        model=sample();sim=self.configure(model)
        class BadGrid:
            def GetBasisSet(self):return sim.GetBasisSet()
            def GetFields(self,*args):return sim.GetFields(*args)
            def GetFieldsOnGrid(self,z,shape,fmt):return np.zeros((2,*shape,3),complex)
        sampler=FourierFieldSampler(BadGrid(),model,1500.)
        xs=ys=[-.2,0.,.2]
        e,h=sampler.grid(xs,ys,.12)
        for i,x in enumerate(xs):
            for j,y in enumerate(ys):
                np.testing.assert_array_equal([e[i,j],h[i,j]],sim.GetFields(x,y,.12))
        self.assertFalse(sampler.enabled)
        self.assertIsNotNone(sampler.stats['fallback_reason'])

    def test_zero_hz_in_first_plane_does_not_guess_later_magnetic_sign(self):
        model=sample();ax=model['ax']
        for native_sign in (-1,1):
            class Grid:
                def GetBasisSet(self):return ((0,0),(1,0),(-1,0))
                def GetFields(self,x,y,z):return ((1.+0j,0j,0j),(0j,1.+0j,complex(np.sin(2*np.pi*x/ax) if z>.1 else 0.)))
                def GetFieldsOnGrid(self,z,shape,fmt):
                    fields=np.array([[self.GetFields(i*ax/shape[0],0,z) for j in range(shape[1])] for i in range(shape[0])])
                    fields[:,:,1,2]*=native_sign
                    return fields[:,:,0],fields[:,:,1]
            sim=Grid();sampler=FourierFieldSampler(sim,model,1500.)
            xs=ax*((np.arange(3)+.5)/3-.5)
            ys=model['ay']*((np.arange(3)+.5)/3-.5)
            sampler.grid(xs,ys,.05)
            e,h=sampler.grid(xs,ys,.15)
            for i,x in enumerate(xs):
                for j,y in enumerate(ys):
                    np.testing.assert_allclose([e[i,j],h[i,j]],sim.GetFields(x,y,.15),rtol=1e-12,atol=1e-12)
            self.assertTrue(sampler.sign_validated)

    def repeated(self):
        model=sample(NumG=49,theta_deg=23,phi_deg=31,polarization='45° s+p')
        film=model['layers'][1]
        model['layers']=[model['layers'][0],*[dict(film,name=f'Film{i}',thickness=.07+.01*i) for i in range(4)],model['layers'][-1]]
        model['patterns']=[dict(model['patterns'][0],layer=f'Film{i}') for i in range(4)]
        return model

    def test_copied_layer_modes_preserve_spectrum_and_fields_at_different_thicknesses(self):
        model=self.repeated()
        model['materials'][1].update(model='table_nk',table=[[1300,3.2,.01],[1600,3.6,.02]],grid=[1300,1600])
        original=self.configure(model,reuse=False);copied=self.configure(model)
        for name in ('Top','Bottom','Film0','Film3'):
            np.testing.assert_allclose(copied.GetPowerFlux(name,0.),original.GetPowerFlux(name,0.),rtol=2e-10,atol=2e-12)
        for z in (.025,.09,.17,.28):
            np.testing.assert_allclose(copied.GetFields(.07,-.03,z),original.GetFields(.07,-.03,z),rtol=2e-10,atol=2e-12)
        # Different solver geometry must receive its own layer modes.
        changed=copy.deepcopy(model);changed['patterns'][2]['sx']=.11
        sim=self.configure(changed);reference=self.configure(changed,reuse=False)
        np.testing.assert_allclose(sim.GetPowerFlux('Bottom',0.),reference.GetPowerFlux('Bottom',0.),rtol=2e-10,atol=2e-12)
        for wavelength in (1400.,1550.):
            for sim in (original,copied):
                material=model['materials'][1]
                sim.SetMaterial(Name=material['name'],Epsilon=epsilon(material,wavelength))
                sim.SetFrequency(1000/wavelength)
                sim.SetExcitationPlanewave(IncidenceAngles=(23.,31.),sAmplitude=complex(2**-.5),pAmplitude=complex(-2**-.5))
            np.testing.assert_allclose(copied.GetPowerFlux('Bottom',0.),original.GetPowerFlux('Bottom',0.),rtol=2e-10,atol=2e-12)
            np.testing.assert_allclose(copied.GetFields(.07,-.03,.17),original.GetFields(.07,-.03,.17),rtol=2e-10,atol=2e-12)

    def test_equal_epsilon_at_one_wavelength_does_not_merge_distinct_materials(self):
        model=self.repeated()
        material=dict(model['materials'][1],name='Other',model='table_nk',table=[[1300,3.4,.015],[1500,3.4,.015],[1600,4.1,.1]],grid=[1300,1500,1600])
        model['materials'].append(material)
        model['layers'][2]['material']='Other'
        original=self.configure(model,reuse=False);copied=self.configure(model)
        for sim in (original,copied):
            sim.GetPowerFlux('Bottom',0.)
            sim.SetMaterial(Name='Other',Epsilon=epsilon(material,1570.))
            sim.SetFrequency(1000/1570.)
            sim.SetExcitationPlanewave(IncidenceAngles=(23.,31.),sAmplitude=complex(2**-.5),pAmplitude=complex(-2**-.5))
        np.testing.assert_allclose(copied.GetPowerFlux('Bottom',0.),original.GetPowerFlux('Bottom',0.),rtol=2e-10,atol=2e-12)

    def test_parallel_combined_spectrum_fields_match_independent_solve_and_phase(self):
        model=sample(wl_start_nm=1490,wl_stop_nm=1510,wl_step_nm=10,theta_deg=23)
        model['measure_phase']=True
        perf=dict(DEFAULT_PERFORMANCE,workers=2,chunk_size=2,timeout_seconds=60)
        expected,expected_info=execute(model,perf)
        cfg=dict(grid=3,depth_samples=3,contour_step=.2)
        with tempfile.TemporaryDirectory() as d:
            rows,info=execute(model,perf,field_settings=cfg,field_directory=Path(d)/'combined')
            self.assertEqual(rows,expected)
            self.assertEqual(info['phase_rows'],expected_info['phase_rows'])
            self.assertEqual(info['electric_fields']['samples'],3)
            index=FieldSampleIndex(Path(d)/'combined/fields')
            for ordinal,row in enumerate(rows):
                saved=index.sample(ordinal)
                self.assertEqual(saved['point_index'],row[0])
                self.assertEqual(saved['wavelength_nm'],row[1])
                folder=Path(saved['directory'])
                diagnostics=json.loads((folder/'field_diagnostics.json').read_text())
                self.assertTrue(diagnostics['reused_spectrum_solution'])
                local=dict(model,points=[row[:3]])
                reference=Path(d)/f'reference{ordinal}'
                sample_fields(local,self.perf,dict(cfg,wavelength_nm=row[1],maps=True,track_contours=True,sampling_backend='point'),reference,module=self.module)
                from field_storage import load_field_frame
                for actual,original in zip(load_field_frame(folder).to_dict('records'),load_field_frame(reference).to_dict('records'),strict=True):
                    self.assertEqual(actual['plane'],original['plane'])
                    self.assertEqual(actual['material'],original['material'])
                    keys=[key for key in actual if key not in ('plane','material','layer')]
                    np.testing.assert_allclose([float(actual[k]) for k in keys],[float(original[k]) for k in keys],rtol=2e-10,atol=2e-12)
        self.assertEqual(mp.active_children(),[])

    def test_interrupted_parallel_fields_keep_all_completed_records_contiguous(self):
        with tempfile.TemporaryDirectory() as d:
            recorder=SimulationFieldRecorder({},d,6,lambda e:None)
            recorder.add(4,[4,1504.,20.]);recorder.add(1,[1,1501.,10.]);recorder.close()
            saved=FieldSampleIndex(Path(d)/'fields')
            self.assertEqual(len(saved),2)
            self.assertEqual([saved.sample(i)['point_index'] for i in range(2)],[1,4])
            self.assertEqual(json.loads((Path(d)/'fields/samples.json').read_text())['status'],'interrupted')

    def test_combined_cancel_preserves_spectrum_checkpoint_and_completed_fields(self):
        model=sample(wl_start_nm=1490,wl_stop_nm=1550,wl_step_nm=10)
        events=[]
        def emit(event):events.append(event)
        def cancelled():return any(e.get('kind')=='log' and '1/' in e.get('text','') for e in events)
        with tempfile.TemporaryDirectory() as d:
            store=SpectrumResults(Path(d)/'spectrum.sqlite',create=True)
            try:
                with self.assertRaises(Cancelled):
                    execute(model,dict(DEFAULT_PERFORMANCE,workers=1,chunk_size=3),emit,cancelled,result_store=store,field_settings=dict(grid=3),field_directory=d)
                self.assertGreaterEqual(len(store),1)
                index=FieldSampleIndex(Path(d)/'fields')
                self.assertGreaterEqual(len(index),1)
                self.assertEqual(json.loads((Path(d)/'fields/samples.json').read_text())['status'],'interrupted')
            finally:store.close()
        self.assertEqual(mp.active_children(),[])

    def test_fast_contour_labels_match_reference_including_periodic_seams(self):
        random=np.random.default_rng(4)
        for shape in ((1,1),(1,19),(21,1),(9,13),(50,60)):
            for periodic_x in (False,True):
                for periodic_y in (False,True):
                    for density in (0,.1,.5,.9,1):
                        mask=random.random(shape)<density
                        actual,n=regions(mask,periodic_x,periodic_y)
                        expected,m=_regions_reference(mask,periodic_x,periodic_y)
                        np.testing.assert_array_equal(actual,expected)
                        self.assertEqual(n,m)
                        labels,count=_regions_runs(mask,periodic_x,periodic_y)
                        np.testing.assert_array_equal(labels,expected)
                        self.assertEqual(count,m)

    def test_faster_contours_preserve_complete_lineage_and_pixel_shapes(self):
        random=np.random.default_rng(31)
        for periodic_x,periodic_y in ((False,False),(True,False),(True,True)):
            amplitude=np.round(random.random((13,19))*2,1)
            actual=sweep(amplitude,.2,periodic_x=periodic_x,periodic_y=periodic_y)
            with patch('contour_sweep.regions',_regions_reference):
                expected=sweep(amplitude,.2,periodic_x=periodic_x,periodic_y=periodic_y)
            self.assertEqual(actual,expected)

    def test_dense_threshold_sweep_retains_every_level_without_relabeling_identical_masks(self):
        amplitude=np.array([[1000.,0.,750.],[0.,500.,0.]])
        with patch('contour_sweep.regions',wraps=regions) as labeling:
            result=sweep(amplitude,.1,periodic_x=True)
        self.assertEqual(len(result['levels']),10001)
        self.assertEqual(labeling.call_count,4)
        for record in result['levels']:
            mask=np.zeros(amplitude.shape,dtype=bool)
            for region in record['regions']:
                for row,start,count in region['pixel_runs']:mask[row,start:start+count]=True
            np.testing.assert_array_equal(mask,amplitude>=record['level'])


if __name__=='__main__':
    mp.freeze_support();unittest.main()
