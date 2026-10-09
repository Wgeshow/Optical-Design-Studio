"""GPU diagnostics, field routing, and opt-in native CPU/GPU agreement."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gpu_status import acceleration_warnings, gpu_settings_note, runtime_check_summary
from model import DEFAULT_PERFORMANCE, MAT_COLS, LAYER_COLS, PAT_COLS, prepare


def field_model():
    return prepare([dict(zip(MAT_COLS, row)) for row in
                    [['Air','constant_nk',1.,0.,'','nm'], ['Film','constant_nk',3.4,.015,'','nm']]],
                   [dict(zip(LAYER_COLS,row)) for row in
                    [['Top',0.,'Air'],['Device',.25,'Film'],['Bottom',0.,'Air']]],
                   [dict(zip(PAT_COLS,['circle','Device','Air',0.,0.,.1,0.,0.]))], [],
                   dict(ax_um=.77,ay_um=.77,NumG=33,mode='Wavelength sweep',
                        wl_start_nm=1550.,wl_stop_nm=1550.,wl_step_nm=1.,fixed_wl_nm=1550.,
                        theta_deg=0.,phi_deg=0.,angle_start=0.,angle_stop=0.,angle_step=1.,polarization='p'))


class GPUDiagnosticsTests(unittest.TestCase):
    def test_connection_success_is_based_on_products_and_zero_failures(self):
        perf=dict(DEFAULT_PERFORMANCE,mode='CPU + GPU')
        for products,failures,expected in [(0,0,'GPU check failed'),(3,1,'GPU check failed'),(3,0,'GPU connection verified')]:
            text=runtime_check_summary(dict(gpu_gemm_calls=products,gpu_failures=failures),perf)
            self.assertIn(expected,text)
            self.assertIn('threshold remains 1024',text)
        self.assertIn('CPU runtime check completed',runtime_check_summary({},DEFAULT_PERFORMANCE))

    def test_threshold_and_missing_cuda_are_distinguished(self):
        perf=dict(DEFAULT_PERFORMANCE,mode='CPU + GPU')
        self.assertIn('1024',acceleration_warnings({},perf)[0])
        warning=acceleration_warnings(dict(statuses={'1':'CPU BLAS; this build has no CUDA support'}),perf)[0]
        self.assertIn('setup_linux.sh --cuda',warning)
        warning=acceleration_warnings(dict(gpu_failures=1,statuses={'1':'cuBLAS library unavailable; using CPU'}),perf)[0]
        self.assertIn('cuBLAS library unavailable',warning)
        self.assertEqual(acceleration_warnings({},DEFAULT_PERFORMANCE),[])
        self.assertIn('1024',gpu_settings_note('CPU + GPU',1024,32))
        self.assertIn('Enter',gpu_settings_note('CPU + GPU',None,32))

    def test_runtime_button_forces_probe_but_preserves_selected_threshold(self):
        import app
        captured=[]
        def run_backend(model,perf,key):
            captured.append(perf)
            yield dict(kind='complete',info=dict(gpu_gemm_calls=2,gpu_failures=0,cpu_gemm_calls=1,warnings=[]))
        perf=dict(DEFAULT_PERFORMANCE,mode='CPU + GPU',require_gpu=True)
        # The backend is mocked, so this callback does not create any saved runs.
        with patch.object(app,'run_backend',run_backend):
            result=list(app.test_backend(None,*[perf[key] for key in app.PERF_KEYS]))[-1]
        self.assertEqual(captured[0]['gpu_min_n'],1)
        self.assertEqual(captured[0]['effective_workers'],1)
        self.assertIn('GPU connection verified',result)
        self.assertIn('threshold remains 1024',result)
        self.assertEqual(perf['gpu_min_n'],1024)


class FieldRoutingTests(unittest.TestCase):
    def sample(self,perf,after):
        from field_solver import sample_fields
        class FakeSimulation:
            def SetFrequency(self,*args): pass
            def SetExcitationPlanewave(self,**kwargs): pass
            def GetFields(self,*args): return ((1.,0.,0.),(0.,1.,0.))
        class FakeModule:
            def __init__(self): self.calls=0
            def AccelerationInfo(self):
                self.calls+=1
                initial=dict(cpu_gemm_calls=10,gpu_gemm_calls=5,gpu_failures=0,status='ready')
                return initial if self.calls==1 else dict(initial,**after)
        with tempfile.TemporaryDirectory() as directory:
            with patch('backend.load_runtime',return_value=FakeModule()) as load, \
                 patch('backend.build_simulation',return_value=FakeSimulation()), \
                 patch('field_tracking.enrich_fields',return_value={'schema_version':2}):
                result=sample_fields(field_model(),perf,dict(wavelength_nm=1550.,grid=3,maps=False),directory)
            diagnostics=json.loads((Path(directory)/'field_diagnostics.json').read_text())
            self.assertEqual(result['acceleration'],diagnostics)
            return load.call_args.kwargs['gpu'],diagnostics

    def test_field_mode_is_honored_and_counts_are_per_run(self):
        for mode,enabled in [('CPU only',False),('CPU + GPU',True),('GPU-assisted (one worker)',True)]:
            with self.subTest(mode=mode):
                selected,info=self.sample(dict(DEFAULT_PERFORMANCE,mode=mode),dict(cpu_gemm_calls=13,gpu_gemm_calls=7))
                self.assertEqual(selected,enabled)
                self.assertEqual(info['gpu_gemm_calls'],2)
                self.assertEqual(info['cpu_gemm_calls'],3)

    def test_required_field_gpu_cannot_silently_fall_back(self):
        for after in [dict(gpu_gemm_calls=5),dict(gpu_gemm_calls=7,gpu_failures=1)]:
            with self.subTest(after=after),self.assertRaisesRegex(RuntimeError,'GPU work was required for fields'):
                self.sample(dict(DEFAULT_PERFORMANCE,mode='CPU + GPU',require_gpu=True),after)


class NativeGPUFieldsTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('S4_TEST_GPU')=='1','opt-in GPU test')
    def test_native_gpu_fields_agree_with_cpu(self):
        from field_solver import execute_fields
        from field_tracking import feature_vector
        model=field_model()
        cfg=dict(wavelength_nm=1550.,grid=3,maps=True)
        with tempfile.TemporaryDirectory() as directory:
            cpu=execute_fields(model,dict(DEFAULT_PERFORMANCE),cfg,Path(directory)/'cpu')
            gpu=execute_fields(model,dict(DEFAULT_PERFORMANCE,mode='GPU-assisted (one worker)',gpu_min_n=1,require_gpu=True),cfg,Path(directory)/'gpu')
            self.assertGreater(gpu['acceleration']['gpu_gemm_calls'],0)
            self.assertEqual(gpu['acceleration']['gpu_failures'],0)
            first,second=feature_vector(cpu),feature_vector(gpu)
            self.assertEqual(first.keys(),second.keys())
            for key in first:
                self.assertAlmostEqual(first[key],second[key],delta=1e-7,msg=key)
            def fields(name):
                with (Path(directory)/name/'electric_fields.csv').open(newline='') as stream:
                    return list(csv.DictReader(stream))
            for a,b in zip(fields('cpu'),fields('gpu')):
                for component in ('Ex','Ey','Ez','Hx','Hy','Hz'):
                    for part in ('real','imag'):
                        key=component+'_'+part
                        self.assertAlmostEqual(float(a[key]),float(b[key]),delta=1e-8,msg=key)
            print('GPU field verification:',gpu['acceleration'],flush=True)


class LinuxGPUSetupTests(unittest.TestCase):
    def test_cuda_flag_is_explicit_and_cpu_is_default(self):
        import importlib.machinery
        import platform_setup
        for argv,flag in [([],'-DS4_ENABLE_CUDA=OFF'),(['--cuda'],'-DS4_ENABLE_CUDA=ON')]:
            with self.subTest(argv=argv),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                build=root/'native_build'/'linux'
                build.mkdir(parents=True)
                (build/'S4.so').write_bytes(b'test')
                with patch.object(platform_setup,'__file__',str(root/'platform_setup.py')), \
                     patch.object(platform_setup.sys,'platform','linux'), \
                     patch.object(importlib.machinery,'EXTENSION_SUFFIXES',['.so']), \
                     patch.object(platform_setup.shutil,'which',return_value='tool'), \
                     patch.object(platform_setup.subprocess,'run') as run:
                    platform_setup.main(argv)
                self.assertIn(flag,run.call_args_list[0].args[0])


if __name__=='__main__':
    unittest.main()
