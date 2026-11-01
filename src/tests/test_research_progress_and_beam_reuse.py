"""Progress presentation and saved-mode dispatch; no numerical solver executes."""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QLabel, QProgressBar
import numpy as np
from qt_app import OpticalStudio
import pcsel_research as pc


class ResearchProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = SimpleNamespace(status=QLabel('Validating the current project…'),
                                     progress_bar=QProgressBar())
        self.owner.progress_bar.setRange(0, 0)

    def test_mpb_fraction_and_message_replace_validation_footer(self):
        OpticalStudio.show_progress(self.owner, dict(progress=63 / 78,
            message='Computed 63 of 78 band samples'))
        self.assertEqual(self.owner.status.text(), 'Computed 63 of 78 band samples')
        self.assertEqual(self.owner.progress_bar.value(), 80)
        self.assertEqual(self.owner.progress_bar.maximum(), 100)

    def test_count_progress_preserves_model_specific_message(self):
        OpticalStudio.show_progress(self.owner, dict(done=4, total=8,
            message='Completed 4 of 8 current biases'))
        self.assertEqual(self.owner.status.text(), 'Completed 4 of 8 current biases')
        self.assertEqual(self.owner.progress_bar.value(), 50)
        OpticalStudio.show_progress(self.owner, dict(done=1, total=8))
        self.assertEqual(self.owner.status.text(), '1 / 8 completed')

    def test_zero_and_text_only_events_are_retained(self):
        OpticalStudio.show_progress(self.owner, dict(progress=0, message='Starting bands'))
        self.assertEqual(self.owner.progress_bar.value(), 0)
        OpticalStudio.show_progress(self.owner, dict(text='Waiting for runtime'))
        self.assertEqual(self.owner.status.text(), 'Waiting for runtime')
        self.assertEqual(self.owner.progress_bar.value(), 0)

    def test_invalid_progress_does_not_hide_status_or_raise(self):
        for value in ('unfinished', None, float('nan'), float('inf')):
            with self.subTest(value=value):
                OpticalStudio.show_progress(self.owner, dict(progress=value, message='Solver running'))
                self.assertEqual(self.owner.status.text(), 'Solver running')


class SavedBeamDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pcsel-beam-dispatch-')
        self.root = Path(self.temp.name)
        settings = pc.paper_example()
        settings.update(model='beam', beam_saved_run=str(self.root / 'source'))
        self.cfg = pc.prepare({}, settings)
        self.guards = []
        for target in ('vertical', 'coupling', 'finite_modes', 'far_field'):
            guard = patch.object(pc, target, side_effect=AssertionError('Numerical execution forbidden'))
            self.guards.append(guard.start())
            self.addCleanup(guard.stop)
        self.addCleanup(self.temp.cleanup)

    def test_saved_beam_dispatch_skips_source_solvers(self):
        events = []
        with patch.object(pc, '_finite_outputs') as output:
            summary = pc.execute(self.cfg, self.root / 'output', events.append)
        output.assert_called_once()
        args = output.call_args.args
        self.assertIsNone(args[1])
        self.assertIsNone(args[2])
        self.assertEqual(args[0], self.cfg)
        self.assertIn('source solvers were not rerun', summary['source_reuse'])
        for guard in self.guards:
            guard.assert_not_called()

    def test_missing_saved_source_fails_without_running_new_source(self):
        with self.assertRaises(FileNotFoundError):
            pc.execute(self.cfg, self.root / 'output')
        self.assertFalse((self.root / 'output' / 'pcsel_summary.json').exists())
        for guard in self.guards:
            guard.assert_not_called()

    def test_changed_geometry_is_rejected_before_loading_fields(self):
        source = self.root / 'source'
        source.mkdir()
        original = copy.deepcopy(self.cfg)
        original['aperture_um'][0] += 1
        (source / 'pcsel_inputs.json').write_text(json.dumps(original), encoding='utf-8')
        with self.assertRaises(pc.InputValidationError) as caught:
            pc.execute(self.cfg, self.root / 'output')
        self.assertEqual(caught.exception.diagnostics[0]['field'], 'beam_saved_run')
        self.assertIn('aperture_um', str(caught.exception))
        for guard in self.guards:
            guard.assert_not_called()

    def test_unaccepted_saved_mode_does_not_produce_a_beam(self):
        source_mode = dict(mode=0, balance_relative=.03, eigen_residual=1e-9, total_loss_cm1=1.)
        fields = dict(x=np.array([0., 1.]), fields=np.zeros((1, 4, 2, 2)),
                      aperture_um=np.asarray(self.cfg['aperture_um']))
        source = Path(self.cfg['beam_saved_run'])
        source.mkdir()
        # The saved-mode contract reads its source summary before mode checks.
        # This synthetic source has a failed balance gate, hence unconverged.
        (source / 'pcsel_summary.json').write_text(json.dumps(dict(
            status='unconverged', engine='pcsel', model='finite',
            convergence_established=False)), encoding='utf-8')
        with patch.object(pc, '_saved_finite', return_value=([source_mode], fields)):
            with self.assertRaises(pc.InputValidationError) as caught:
                pc.execute(self.cfg, self.root / 'output')
        self.assertEqual(caught.exception.diagnostics[0]['field'], 'beam_mode')
        self.assertFalse((self.root / 'output' / 'beam_fields.npz').exists())
        for guard in self.guards:
            guard.assert_not_called()

    def test_fresh_beam_retains_source_solver_dispatch(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['beam_saved_run'] = ''
        with patch.object(pc, '_finite_outputs') as output:
            with self.assertRaisesRegex(AssertionError, 'Numerical execution forbidden'):
                pc.execute(cfg, self.root / 'output')
        self.guards[0].assert_called_once()
        output.assert_not_called()


if __name__ == '__main__':
    unittest.main()
