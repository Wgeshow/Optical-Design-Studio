"""Persistence, portability, recovery and native partial-result checks."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from backend import Cancelled, execute
from data_library import DataLibrary, read_json, write_json
from evaluation_storage import EvaluationRecorder
from model import MAT_COLS, DEFAULT_PERFORMANCE, epsilon, prepare
from test_backend import MATERIALS, LAYERS, PATTERNS, SETTINGS, sample


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = DataLibrary(self.root / 'one')
        self.project = dict(materials=copy.deepcopy(MATERIALS), layers=copy.deepcopy(LAYERS),
                            patterns=copy.deepcopy(PATTERNS), settings=dict(SETTINGS), performance=dict(DEFAULT_PERFORMANCE))

    def dispersive(self):
        path = self.root / 'measured.csv'
        path.write_text('wavelength,n,k\n1.2,3.1,0.02\n1.7,3.7,0.03\n')
        self.project['materials'][1].update(Model='table_nk', DataFile=path.name, WavelengthUnit='um')
        return path

    def test_preset_versions_survive_restart(self):
        first = self.library.save_preset(MATERIALS[1], 'Measured film', '300 K')
        changed = dict(MATERIALS[1], A=3.7)
        second = self.library.save_preset(changed, 'Measured film', '310 K')
        presets = DataLibrary(self.library.root).presets()
        self.assertEqual(len(presets), 2)
        self.assertEqual(presets[first]['project']['materials'][0]['A'], 3.4)
        self.assertEqual(presets[second]['project']['materials'][0]['A'], 3.7)
        self.assertEqual(presets[first]['notes'], '300 K')

    def test_table_project_portable_without_upload(self):
        path = self.dispersive()
        expected = prepare(self.project['materials'], LAYERS, PATTERNS, [path], SETTINGS)
        project = self.library.snapshot(self.project, [path])
        path.unlink()
        other = DataLibrary(self.root / 'two')
        restored = other.snapshot(json.loads(json.dumps(project)))
        actual = prepare(restored['materials'], LAYERS, PATTERNS, other.files_for(restored), SETTINGS)
        self.assertEqual(actual, expected)
        self.assertEqual(epsilon(actual['materials'][1], 1550), epsilon(expected['materials'][1], 1550))

    def test_same_filename_different_values_kept_separate(self):
        path = self.dispersive()
        first = self.library.snapshot(self.project, [path])
        path.write_text('wavelength,n,k\n1.2,1.1,0.02\n1.7,1.7,0.03\n')
        second = self.library.snapshot(self.project, [path])
        self.assertNotEqual(first['materials'][1]['DataFile'], second['materials'][1]['DataFile'])
        with self.assertRaisesRegex(ValueError, 'upload'):
            self.library.snapshot(self.project)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.library.snapshot(self.project, [path, path])

    def test_table_preset_reusable(self):
        path = self.dispersive()
        key = self.library.save_preset(self.project['materials'][1], 'Film', uploads=[path])
        path.unlink()
        saved = DataLibrary(self.library.root).presets()[key]['project']
        self.project['materials'][1] = saved['materials'][0]
        project = self.library.snapshot(self.project)
        self.assertTrue(self.library.files_for(project))
        prepare(project['materials'], LAYERS, PATTERNS, self.library.files_for(project), SETTINGS)

    def test_legacy_job_and_saved_design_recovery(self):
        path = self.dispersive()
        model = prepare(self.project['materials'], LAYERS, PATTERNS, [path], SETTINGS)
        run = self.library.runs / 'old_run'
        run.mkdir()
        write_json(run / 'job.json', dict(model=model, performance=DEFAULT_PERFORMANCE, search=dict(project=self.project)))
        altered = copy.deepcopy(model)
        altered['layers'][1]['thickness'] = .333
        (run / 'design_models.jsonl').write_text(json.dumps(dict(design_id=7, model=altered)) + '\n')
        path.unlink()
        project, _ = self.library.project_for('old_run')
        recovered = prepare(project['materials'], project['layers'], project['patterns'], self.library.files_for(project), project['settings'])
        self.assertEqual(recovered, model)
        project, _ = self.library.project_for('old_run', 7)
        self.assertEqual(project['layers'][1]['Thickness_um'], .333)
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.library.project_for('old_run', 8)

    def test_bundle_roundtrip_and_collision_preservation(self):
        path = self.dispersive()
        self.library.save_preset(self.project['materials'][1], 'Film', uploads=[path])
        project = self.library.snapshot(self.project, [path])
        run = self.library.runs / 'run_one'
        run.mkdir()
        write_json(run / 'project.json', project)
        (run / 'results.csv').write_text('wavelength_nm,R,T,A\n1550,0.01,0,0.99\n')
        self.library.record(run, title='My film', kind='simulation', status='complete')
        bundle = self.library.export()
        other = DataLibrary(self.root / 'two')
        result = other.import_bundle(bundle)
        self.assertEqual(result, dict(runs=1, presets=1, assets=1))
        self.assertEqual((other.runs / 'run_one' / 'results.csv').read_bytes(), (run / 'results.csv').read_bytes())
        self.assertEqual(other.project_for('run_one')[0], project)
        other.import_bundle(bundle)
        self.assertEqual(len(other.entries()), 2)
        self.assertEqual(len(other.presets()), 1)
        self.assertEqual(other.entries('My film')[0]['title'], 'My film')

    def test_unsafe_and_corrupt_bundles_rejected_before_merge(self):
        self.library.save_preset(MATERIALS[1], 'Film')
        bundle = self.library.export()
        other = DataLibrary(self.root / 'two')
        bad = self.root / 'bad.zip'
        with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(bad, 'w') as dest:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename.startswith('data_library/presets/'):
                    data += b' '
                dest.writestr(info.filename, data)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            other.import_bundle(bad)
        self.assertEqual(other.presets(), {})
        with zipfile.ZipFile(bad, 'w') as dest:
            dest.writestr('../outside.txt', 'no')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            other.import_bundle(bad)
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_embedded_table_corruption_rejected(self):
        path = self.dispersive()
        project = self.library.snapshot(self.project, [path])
        next(iter(project['optical_constants'].values()))['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'checksum'):
            DataLibrary(self.root / 'two').materialize(project)

    def test_source_bundle_does_not_overwrite_program_on_import(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'app.py').write_text('shared source')
        other = DataLibrary(self.root / 'two')
        (other.root / 'app.py').write_text('installed source')
        bundle = self.library.export(source_root=source)
        other.import_bundle(bundle)
        self.assertEqual((other.root / 'app.py').read_text(), 'installed source')
        with zipfile.ZipFile(bundle) as archive:
            self.assertEqual(archive.read('app.py'), b'shared source')

    def test_native_batches_saved_after_cancel(self):
        directory = self.library.runs / 'partial'
        directory.mkdir()
        stopped = False

        def tracked_executor(model, perf, emit, cancelled, checkpoint):
            def completed(rows):
                nonlocal stopped
                checkpoint(rows)
                stopped = True
            return execute(model, perf, emit, cancelled, checkpoint=completed)

        recorder = EvaluationRecorder(directory, tracked_executor)

        def progress(event):
            pass

        with self.assertRaises(Cancelled):
            recorder(sample(wl_start_nm=1500, wl_stop_nm=1600, wl_step_nm=1),
                     dict(DEFAULT_PERFORMANCE, workers=1, chunk_size=1), progress, lambda: stopped)
        evaluation = directory / 'evaluations' / '000001'
        status = read_json(evaluation / 'status.json')
        self.assertEqual(status['status'], 'interrupted')
        self.assertGreater(status['completed_points'], 0)
        self.assertLess(status['completed_points'], 101)
        self.assertEqual(len((evaluation / 'batch_results.csv').read_text().splitlines())-1, status['completed_points'])
        self.assertTrue((evaluation / 'model.json').exists())


if __name__ == '__main__':
    unittest.main()
