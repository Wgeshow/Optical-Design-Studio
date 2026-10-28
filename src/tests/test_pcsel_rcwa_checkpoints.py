"""Checkpoint failure/cancellation contracts with a fake S4 runtime and optimizer."""
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

import pcsel_optional


class FakeS4:
    def __init__(self, fail_second=False, fail_field=False):
        self.frequency=0j
        self.fail_second=fail_second
        self.fail_field=fail_field
        self.bottom_flux_calls=0

    def SetMaterial(self, **kwargs): pass
    def AddLayer(self, **kwargs): pass
    def SetExcitationPlanewave(self, **kwargs): pass
    def GetBasisSet(self): return [(0,0)]*9
    def SetFrequency(self, frequency): self.frequency=complex(frequency)

    def GetFields(self, x, y, z):
        if self.fail_second and self.frequency==complex(.3):
            raise ValueError('Second seed probe has no resolved field')
        if self.fail_field and 0<abs(self.frequency.imag+3e-5)<2e-8:
            raise RuntimeError('Residue field extraction failed')
        amplitude=1. if self.frequency.imag==0 else 1e16
        return np.array([amplitude,amplitude*.2,0j]),np.array([amplitude*.3,0j,amplitude*.1])

    def GetPowerFlux(self, port, offset):
        if port=='bottom':
            self.bottom_flux_calls+=1
            return .6+0j,0j
        return 0j,-.4+0j


class RCWACheckpointTests(unittest.TestCase):
    def config(self, seeds=None):
        return dict(lattice_nm=300.,top_index=1.,bottom_index=1.,inclusion_index=1.,
            layers=[],shapes=[],basis=9,pole_excitation=[[1.,0.],[0.,.37]],probe=[.1,.2,0.],
            pole_seeds=seeds or [[.29,-3e-5],[.3,-3e-5]],pole_bounds=[[.1,.5],[-.1,-1e-10]],
            pole_detuning=1e-8,pole_field_grid=2,pole_field_z_nm=[0.])

    def execute_fake(self, cfg, directory, solver=None, cancelled=lambda:False, optimizer_success=True):
        solver=solver or FakeS4()
        runtime=SimpleNamespace(New=lambda **kwargs:solver)
        with patch('backend.load_runtime',return_value=runtime),patch.object(pcsel_optional,'least_squares',
                side_effect=lambda fun,x0,**kwargs: SimpleNamespace(x=np.array(x0),success=optimizer_success,nfev=1)):
            return pcsel_optional.rcwa_poles(cfg,Path(directory),lambda event:None,cancelled)

    def progress(self, directory):
        return json.loads((Path(directory)/'rcwa_progress.json').read_text())

    def assert_manifest_exists(self, directory, result):
        for name in result['artifacts']:
            self.assertTrue((Path(directory)/name).is_file(),name)

    def test_later_probe_failure_preserves_accepted_first_seed_and_propagates(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'Second seed'):
                self.execute_fake(self.config(),directory,solver=FakeS4(fail_second=True))
            result=self.progress(directory)
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['processed_pole_seed_count'],1)
            self.assertEqual(result['active_seed_index'],1)
            self.assertEqual(len(result['poles']),1)
            self.assertEqual(result['poles'][0]['seed_real'],.29)
            self.assertEqual(result['pole_radiation'][0]['status'],'complete')
            with (Path(directory)/'rcwa_poles.csv').open(newline='') as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual(len(rows),1)
            self.assertEqual(float(rows[0]['Q']),result['poles'][0]['Q'])
            self.assert_manifest_exists(directory,result)

    def test_cancellation_between_seeds_preserves_first_and_remains_interrupted(self):
        solver=FakeS4()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(InterruptedError):
                self.execute_fake(self.config(),directory,solver=solver,
                    cancelled=lambda:solver.bottom_flux_calls>=2)
            result=self.progress(directory)
            self.assertEqual(result['status'],'cancelled')
            self.assertEqual(len(result['poles']),1)
            self.assertEqual(len(result['pole_radiation']),1)
            self.assertEqual(result['active_seed_index'],1)
            self.assert_manifest_exists(directory,result)

    def test_no_accepted_roots_has_partial_status_and_no_advertised_empty_radiation_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            result=self.execute_fake(self.config(),directory,optimizer_success=False)
            self.assertEqual(result['status'],'partial')
            self.assertEqual(result['poles'],[])
            self.assertEqual(len(result['failed_poles']),2)
            self.assertNotIn('rcwa_radiation.csv',result['artifacts'])
            self.assertFalse((Path(directory)/'rcwa_radiation.csv').exists())
            self.assertEqual(self.progress(directory)['status'],'partial')
            self.assert_manifest_exists(directory,result)

    def test_optional_field_failure_keeps_root_and_records_partial_once(self):
        with tempfile.TemporaryDirectory() as directory:
            result=self.execute_fake(self.config(seeds=[[.29,-3e-5]]),directory,solver=FakeS4(fail_field=True))
            self.assertEqual(result['status'],'partial')
            self.assertEqual(len(result['poles']),1)
            self.assertEqual(len(result['pole_radiation']),1)
            self.assertEqual(result['pole_radiation'][0]['status'],'failed')
            self.assertFalse(any(name.endswith('.npz') for name in result['artifacts']))
            self.assertEqual(self.progress(directory)['poles'],result['poles'])
            self.assert_manifest_exists(directory,result)

    def test_success_keeps_numeric_results_and_complete_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            result=self.execute_fake(self.config(),directory)
            self.assertEqual(result['status'],'complete')
            progress=self.progress(directory)
            self.assertEqual(progress['status'],'complete')
            self.assertEqual(progress['processed_pole_seed_count'],2)
            self.assertEqual(progress['poles'],result['poles'])
            self.assertEqual(progress['pole_radiation'],result['pole_radiation'])
            self.assertFalse(progress['convergence_established'])
            self.assertEqual(len(result['poles']),2)
            for row in result['poles']:
                self.assertEqual(row['Q'],row['frequency']/(-2*row['imaginary']))
            self.assert_manifest_exists(directory,result)


if __name__=='__main__':unittest.main()
