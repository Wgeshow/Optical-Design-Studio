"""Exact cutoff solutions, missing-value storage, and genuine solver failures."""
import csv
import math
import multiprocessing as mp
from pathlib import Path
import tempfile
import unittest
from backend import execute
from model import DEFAULT_PERFORMANCE
from scan_storage import SpectrumResults,ScanPoints
from spectrum_field_job import FiniteSpectrumPoints
from tests.test_backend import sample
from unittest.mock import patch


def cutoff_model(**extra):
    model=sample(NumG=32,wl_start_nm=1116.4,wl_stop_nm=1116.6,wl_step_nm=.1)
    model['materials'][1]['b']=0.
    model['materials'][2]['a']=1.45
    return dict(model,**extra)


class UnavailableSpectrumTests(unittest.TestCase):
    def test_real_cutoff_continues_in_same_batch_and_preserves_neighbors(self):
        perf=dict(DEFAULT_PERFORMANCE,workers=1,threads=1,chunk_size=8)
        model=cutoff_model(allow_unavailable_points=True,measure_phase=True)
        events=[]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=SpectrumResults(root/'spectrum.sqlite',create=True)
            try:
                saved,info=execute(model,perf,events.append,result_store=store)
                self.assertEqual(info['points'],3)
                self.assertEqual(info['valid_points'],3)
                self.assertEqual(info['unavailable_points'],0)
                self.assertEqual(info['exact_cutoff_points'],1)
                rows=list(saved)
                self.assertEqual(rows[1][:3],[1,1116.5,0.])
                self.assertTrue(all(math.isfinite(v) for v in rows[1][3:]))
                self.assertLess(abs(rows[1][5]),2e-10)
                self.assertLess(info['exact_cutoff_preview'][0]['interface_residual'],2e-10)
                for row in (rows[0],rows[2]):
                    fresh,_=execute(dict(model,points=[row[:3]],allow_unavailable_points=False),perf)
                    for actual,expected in zip(row[3:],fresh[0][3:]):self.assertAlmostEqual(actual,expected,delta=1e-12)
                self.assertTrue(all(math.isfinite(v) for v in list(store.phase_rows())[1][3:]))
                store.export_csv(root/'results.csv',bins=1)
                store.export_failures(root/'unavailable_points.csv')
                frame=store.frame(preview=True)
                self.assertEqual(frame.point_index.tolist(),[0,1,2])
                self.assertAlmostEqual(frame.iloc[1].R_plus_T_plus_A,1.)
                self.assertEqual(len(FiniteSpectrumPoints(store)),3)
                self.assertEqual([r[0] for r in FiniteSpectrumPoints(store)],[0,1,2])
                with (root/'results.csv').open(newline='') as stream:csv_rows=list(csv.DictReader(stream))
                self.assertTrue(all(csv_rows[1][key] for key in ('R','T','A','R_plus_T_plus_A')))
                self.assertFalse((root/'unavailable_points.csv').exists())
            finally:store.close()
        self.assertEqual(mp.active_children(),[])

    def test_strict_single_point_calculation_solves_exact_cutoff(self):
        model=cutoff_model(points=[[0,1116.5,0.]])
        rows,info=execute(model,dict(DEFAULT_PERFORMANCE,workers=1,threads=1))
        self.assertEqual(info['exact_cutoff_points'],1)
        self.assertTrue(all(math.isfinite(v) for v in rows[0]))

    def test_unrelated_nonfinite_native_result_is_not_replaced(self):
        from backend import worker
        class Simulation:
            def SetFrequency(self,*args):pass
            def SetExcitationPlanewave(self,**kwargs):pass
            def GetBasisSet(self):return [(0,0)]
            def GetPowerFlux(self,*args):return float('nan'),float('nan')
        class Module:
            __file__='test'
            def AccelerationInfo(self):return dict(status='test',cpu_gemm_calls=0,gpu_gemm_calls=0,gpu_failures=0)
        class Connection:
            def __init__(self):self.batches=iter([[[0,1050.,0.]],None]);self.sent=[]
            def recv(self):return next(self.batches)
            def send(self,message):self.sent.append(message)
            def close(self):pass
        for partial in (False,True):
            connection=Connection()
            with patch('backend.load_runtime',return_value=Module()),patch('backend.build_simulation',return_value=Simulation()),patch('cutoff_solver.solve_cutoff') as cutoff:
                worker(connection,cutoff_model(allow_unavailable_points=partial),dict(DEFAULT_PERFORMANCE),False)
            cutoff.assert_not_called()
            if partial:
                self.assertEqual(connection.sent[-1]['rows'][0][3:],[None]*3)
                self.assertEqual(len(connection.sent[-1]['failures']),1)
            else:self.assertEqual(connection.sent[-1]['kind'],'error')

    def test_geometry_errors_remain_fatal(self):
        model=cutoff_model(allow_unavailable_points=True)
        model['layers'][1]['material']='MissingMaterial'
        with self.assertRaises(RuntimeError):execute(model,dict(DEFAULT_PERFORMANCE,workers=1,threads=1))


if __name__=='__main__':unittest.main()
