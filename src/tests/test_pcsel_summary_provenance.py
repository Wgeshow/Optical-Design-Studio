"""Exercise persisted summary routing with every numerical engine replaced by a stub."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import pcsel_research as pc


class PCSELSummaryProvenanceTests(unittest.TestCase):
    def execute_stubbed(self, cfg, directory, events=None):
        worker_result = dict(status='complete', engine='pcsel', model='gme',
            engine_version='test-version', approximation='Worker perturbative approximation',
            convergence_established=False, artifacts=['gme_modes.csv'], modes=[
                dict(k_index=0, band=0, frequency=.4, frequency_imag=.1, Q=2.),
                dict(k_index=0, band=1, frequency=.5, frequency_imag=.0001, Q=2500.)])
        with ExitStack() as stack:
            stack.enter_context(patch('research_physics_runtime.run_worker',
                side_effect=lambda *args, **kwargs: copy.deepcopy(worker_result)))
            stack.enter_context(patch('pcsel_optional.rcwa_poles', return_value=dict(
                status='partial', artifacts=['rcwa_poles.csv'], approximation='RCWA stub',
                search_limitations='Probe can miss a dark mode.', basis_actual=13)))
            stack.enter_context(patch('pcsel_aperture.execute_aperture', return_value=dict(
                status='unconverged', artifacts=['aperture_sweep.csv'],
                approximation='Reduced calibrated model', load_source='Supplied source anchor',
                temperature_load_law_calibrated=False)))
            stack.enter_context(patch.object(pc, 'vertical', return_value=(
                dict(guided=True, frequency=.25, Gamma_QW=.1, effective_group_index=4.),
                dict(z_nm=np.array([0., 1.]), index=np.array([2., 2.]),
                     intensity_per_nm=np.array([.5, .5]),candidate_fields=np.array([[.5,.5]])))))
            stack.enter_context(patch.object(pc, 'coupling', return_value=(np.zeros((4,4)), {'coupling_diagnostics': {}})))
            stack.enter_context(patch.object(pc.np.linalg, 'eigvals', return_value=np.arange(4)*.001j))
            stack.enter_context(patch.object(pc, '_finite_outputs',
                side_effect=lambda cfg,C,freq,d,summary,*rest,**kwargs: summary.update(finite_stub=True)))
            return pc.execute(cfg, directory, emit=(events.append if events is not None else lambda e: None))

    def test_every_engine_persists_its_own_citation_and_limits(self):
        expected = dict(vertical='1107.1772', cwt='1107.1772', finite='1107.1772',
            beam='1107.1772', aperture=None, gme='2003.00379', rcwa_poles='10.1016/j.cpc.2012.04.026')
        with tempfile.TemporaryDirectory() as name:
            for model, reference in expected.items():
                with self.subTest(model=model):
                    cfg=dict(model=model,lattice_nm=300.,green_model='local',beam_saved_run='')
                    result=self.execute_stubbed(cfg,Path(name)/model)
                    persisted=json.loads((Path(name)/model/'pcsel_summary.json').read_text())
                    self.assertEqual(result,persisted)
                    self.assertFalse(result['convergence_established'])
                    if reference is None:
                        self.assertIsNone(result['reference'])
                        self.assertEqual(result['method_references'],[])
                        self.assertEqual(result['load_source'],'Supplied source anchor')
                        self.assertFalse(result['temperature_load_law_calibrated'])
                    else:
                        self.assertIn(reference,result['reference'])
                        self.assertEqual(result['method_references'][0]['url'],result['reference'])
                        self.assertTrue(result['method_references'][0]['scope'])
                    limits=' '.join(result['limitations'])
                    self.assertEqual('local longitudinal closure' in limits,model in ('cwt','finite','beam'))
                    self.assertEqual('Finite modes use a rectangular aperture' in limits,model in ('finite','beam'))
                    self.assertEqual('Far fields use the paraxial Fraunhofer' in limits,model=='beam')
                    self.assertEqual('explicit source-bound load anchors' in limits,model=='aperture')
                    if model=='rcwa_poles':
                        self.assertEqual(result['search_limitations'],'Probe can miss a dark mode.')
                        self.assertEqual(result['status'],'partial')
                    if model=='gme':
                        self.assertEqual(result['engine_version'],'test-version')
                        self.assertEqual(result['approximation'],'Worker perturbative approximation')
                        self.assertIn('much less than one',limits)

    def test_gme_ratio_and_warning_are_saved_without_a_new_acceptance_gate(self):
        events=[]
        with tempfile.TemporaryDirectory() as name:
            result=self.execute_stubbed(dict(model='gme'),name,events)
        diagnostics=result['radiation_diagnostics']
        self.assertEqual(diagnostics['modes'][0]['abs_frequency_imag_over_frequency'],.25)
        self.assertEqual(diagnostics['modes'][1]['abs_frequency_imag_over_frequency'],.0002)
        self.assertEqual(diagnostics['maximum_abs_frequency_imag_over_frequency'],.25)
        self.assertFalse(diagnostics['validity_established'])
        self.assertIsNone(diagnostics['acceptance_threshold'])
        self.assertIn('25.000%',diagnostics['warning'])
        self.assertTrue(any(event.get('message')==diagnostics['warning'] for event in events))
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['modes'][0]['Q'],2.)

    def test_gme_ratios_do_not_invent_zero_for_missing_or_invalid_frequencies(self):
        rows=[dict(frequency=1.,frequency_imag=-.2),dict(frequency=0.,frequency_imag=.1),
            dict(frequency=1.),dict(frequency=float('nan'),frequency_imag=.1)]
        result=pc._gme_radiation_diagnostics(rows)
        self.assertEqual(result['modes'][0]['abs_frequency_imag_over_frequency'],.2)
        self.assertEqual(result['invalid_ratio_count'],3)
        self.assertTrue(all(row['abs_frequency_imag_over_frequency'] is None for row in result['modes'][1:]))
        json.dumps(result,allow_nan=False)
        empty=pc._gme_radiation_diagnostics([])
        self.assertIsNone(empty['maximum_abs_frequency_imag_over_frequency'])
        self.assertIn('unavailable',empty['warning'])

    def test_sweep_parent_and_case_metadata_use_selected_engine(self):
        cfg=dict(model='gme',parameter_sweep=dict(cases=[
            dict(parameters={'gmax':2.1},prepared=dict(model='gme',gmax=2.1)),
            dict(parameters={'gmax':3.1},prepared=dict(model='gme',gmax=3.1))]))
        before=copy.deepcopy(cfg)
        with tempfile.TemporaryDirectory() as name:
            result=self.execute_stubbed(cfg,name)
            persisted=json.loads((Path(name)/'pcsel_summary.json').read_text())
            self.assertEqual(result,persisted)
        self.assertEqual(cfg,before)
        self.assertIn('2003.00379',result['reference'])
        self.assertEqual(result['completed_cases'],2)
        self.assertFalse(result['convergence_established'])
        self.assertNotIn('rectangular aperture',' '.join(result['limitations']))
        self.assertTrue(any('Sweep completion' in item for item in result['limitations']))
        for case in result['cases']:
            self.assertIn('2003.00379',case['summary']['reference'])
            self.assertIn('radiation_diagnostics',case['summary'])
            self.assertFalse(any('Sweep completion' in item for item in case['summary']['limitations']))

    def test_metadata_has_no_cross_run_mutable_state(self):
        first=pc._model_provenance('finite')
        first['limitations'].append('test mutation')
        first['method_references'][0]['scope']='test mutation'
        other=pc._model_provenance('finite')
        self.assertNotIn('test mutation',other['limitations'])
        self.assertNotEqual(other['method_references'][0]['scope'],'test mutation')
        self.assertIn('infinite-periodic',other['method_references'][0]['scope'])


if __name__=='__main__':
    unittest.main()
