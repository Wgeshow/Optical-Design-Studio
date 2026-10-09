"""Verify scan storage bounds, exact result preservation, and field checkpoints."""
import copy
import csv
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from backend import execute, Cancelled, main
from data_library import write_json, read_json
from model import DEFAULT_PERFORMANCE, prepare
from scan_storage import ScanPoints, SpectrumResults, FieldSampleIndex, legacy_spectrum_index
from simulation_fields import execute_simulation_fields
from tests.test_backend import sample, MATERIALS, LAYERS, PATTERNS, SETTINGS


class StorageTests(unittest.TestCase):
    def test_sparse_interrupted_spectrum_preserves_ids_and_has_dense_view_positions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);store=SpectrumResults(root/'spectrum.sqlite',create=True)
            rows=[[2,1502.,0.,.1,.2,.7],[17,1517.,0.,.2,.3,.5],[41,1541.,0.,.01,.01,.98]]
            store.add_batch(rows[1:]);store.add_batch(rows[:1])
            store.export_csv(root/'results.csv');store.close()
            saved=SpectrumResults(root/'spectrum.sqlite')
            self.assertEqual(list(saved),rows)
            self.assertEqual(saved[0],rows[0]);self.assertEqual(saved[-1],rows[-1])
            self.assertEqual(saved.frame(preview=True).point_index.tolist(),[0,1,2])
            self.assertEqual(saved.peak('A'),rows[-1])
            self.assertEqual(saved.position_for_id(saved.peak('A')[0]),2)
            self.assertEqual(saved.nearest_index(1516.8),1)
            self.assertEqual(saved.view_frame(1516.,1518.).point_index.tolist(),[0,1,2])
            with (root/'results.csv').open(newline='') as stream:
                exported=list(csv.DictReader(stream))
            self.assertEqual([float(row['wavelength_nm']) for row in exported],[row[1] for row in rows])

    def test_backend_finalizes_received_spectrum_and_phase_after_cancel_or_error(self):
        for failure in (Cancelled('Requested cancellation'), RuntimeError('Intentional worker failure')):
            with self.subTest(failure=type(failure).__name__),tempfile.TemporaryDirectory() as d:
                root=Path(d);model=sample();model['measure_phase']=True
                write_json(root/'job.json',dict(model=model,performance=DEFAULT_PERFORMANCE))
                rows=[[4,1504.,0.,.1,.2,.7],[1,1501.,0.,.2,.3,.5]]
                def interrupted(model,perf,emit,cancelled,checkpoint=None,result_store=None,**options):
                    result_store.add_batch(rows,[[4,1504.,0.,.25,.5]])
                    checkpoint(rows)
                    raise failure
                with patch('backend.execute',interrupted),patch('sys.argv',['backend','--job',str(root/'job.json')]),patch('builtins.print') as output:
                    code=main()
                self.assertEqual(code,2 if isinstance(failure,Cancelled) else 1)
                events=[json.loads(call.args[0]) for call in output.call_args_list]
                self.assertEqual(events[-2]['kind'],'finalizing')
                self.assertEqual(events[-1]['kind'],'cancelled' if isinstance(failure,Cancelled) else 'error')
                saved=SpectrumResults(root/'spectrum.sqlite')
                self.assertEqual(list(saved),sorted(rows))
                self.assertEqual(saved.frame(preview=True).point_index.tolist(),[0,1])
                self.assertEqual(saved[1],rows[0])
                self.assertEqual(list(saved.phase_rows())[1][3:],(.25,.5))
                self.assertEqual(len((root/'results.csv').read_text().splitlines()),3)
                self.assertEqual(len((root/'phase.csv').read_text().splitlines()),3)

    def test_legacy_csv_index_preserves_source_and_refreshes_after_change(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'results.csv'
            source='wavelength_nm,angle_deg,R,T,A,R_plus_T_plus_A\n1500,0,.1,.2,.7,1\n1501,0,.2,.3,.5,1\n'
            path.write_text(source)
            store=legacy_spectrum_index(path,minimum_bytes=0)
            self.assertEqual(store[1],[1,1501.,0.,.2,.3,.5])
            self.assertEqual(path.read_text(),source)
            self.assertEqual(legacy_spectrum_index(path,minimum_bytes=0).peak('A')[0],0)
            path.write_text(source+'1502,0,.01,.01,.98,1\n')
            self.assertEqual(legacy_spectrum_index(path,minimum_bytes=0).peak('A')[0],2)

    def test_compact_scan_matches_existing_coordinates_and_roundtrips(self):
        for options in ({},dict(wl_step_nm=.1),dict(wl_start_nm=1550,wl_stop_nm=1550)):
            settings=dict(SETTINGS,**options)
            old=prepare(MATERIALS,LAYERS,PATTERNS,[],settings)
            new=prepare(MATERIALS,LAYERS,PATTERNS,[],settings,compact_points=True)
            self.assertEqual(list(new['points']),old['points'])
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'job.json';write_json(path,new)
                restored=read_json(path)
                self.assertIsInstance(restored['points'],ScanPoints)
                self.assertEqual(list(restored['points']),old['points'])
        points=ScanPoints(1300,.0001,10000000,0.)
        self.assertEqual(len(points[9999990:]),10)
        self.assertEqual(copy.deepcopy(points)[-1],points[-1])
        self.assertLess(len(json.dumps(points.as_json())),200)

    def test_out_of_order_batches_export_exact_rows_phase_and_peaks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);store=SpectrumResults(root/'spectrum.sqlite',create=True)
            rows=[[i,1500+i,0,.1,.2,.7] for i in range(12001)]
            rows[7777][5]=.95
            store.add_batch(rows[6000:],[[7777,9277,0,12.,None]])
            store.add_batch(rows[:6000])
            self.assertEqual(list(store),rows)
            store.export_csv(root/'results.csv',bins=20)
            self.assertLessEqual(len(store.frame(preview=True)),160)
            self.assertIn(7777,store.frame(preview=True).point_index.values)
            self.assertEqual(store.peak('A'),rows[7777])
            self.assertEqual(store.peak('R')[0],0)
            self.assertEqual(store[12000],rows[-1])
            self.assertEqual(list(store.phase_rows())[7777][3:],(12.,None))
            with (root/'results.csv').open(newline='') as stream:
                saved=list(csv.DictReader(stream))
            self.assertEqual(len(saved),len(rows))
            self.assertEqual(float(saved[7777]['A']),.95)
            store.close()

    def test_fields_do_not_copy_scan_and_large_manifest_stays_bounded(self):
        class NeverCopy(list):
            def __deepcopy__(self,memo):raise AssertionError('Copied the complete scan')
        model=dict(points=NeverCopy([[0,1550,0]]),polarization='p',materials=[])
        calls=[]
        def fields(local,perf,cfg,path,cancelled):
            calls.append(local['points'][0]);Path(path).mkdir(parents=True,exist_ok=True);return {}
        with tempfile.TemporaryDirectory() as d:
            rows=ScanPoints(1500,.01,1100,12.)
            info=execute_simulation_fields(model,{},rows,dict(grid=3),d,field_executor=fields)
            manifest=Path(info['manifest']);saved=read_json(manifest)
            self.assertEqual(saved['count'],1100)
            self.assertNotIn('samples',saved)
            self.assertLess(manifest.stat().st_size,1000)
            index=FieldSampleIndex(manifest.parent)
            self.assertEqual(len(index),1100)
            self.assertAlmostEqual(index.sample(1099)['wavelength_nm'],1510.99)
            index.close()
        self.assertEqual(len(calls),1100)
        self.assertEqual(model['points'],[[0,1550,0]])

    def test_interrupted_fields_keep_completed_index_and_status(self):
        calls=[]
        def fields(model,perf,cfg,path,cancelled):
            calls.append(1);Path(path).mkdir(parents=True,exist_ok=True);return {}
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Cancelled):
                execute_simulation_fields(dict(points=[]),{},ScanPoints(1500,1,20,0),{},d,
                    cancelled=lambda:len(calls)==3,field_executor=fields)
            saved=read_json(Path(d)/'fields/samples.json')
            self.assertEqual((saved['status'],saved['count']),('interrupted',3))


class NativeStorageTests(unittest.TestCase):
    def test_complete_backend_job_with_compact_scan_fields_and_phase(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            model=sample(wl_start_nm=1500,wl_stop_nm=1510,wl_step_nm=5)
            model['points']=ScanPoints(1500,5,3,17.);model['measure_phase']=True
            write_json(root/'job.json',dict(model=model,performance=dict(DEFAULT_PERFORMANCE,workers=1,timeout_seconds=60),
                simulation_fields=dict(grid=3,depth_samples=3,contour_step=.2)))
            process=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'backend.py'),'--job',str(root/'job.json')],
                capture_output=True,text=True,timeout=60)
            self.assertEqual(process.returncode,0,process.stdout+'\n'+process.stderr)
            events=[json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual(events[-1]['kind'],'complete')
            self.assertEqual(events[-1]['info']['points'],3)
            self.assertEqual(events[-1]['info']['electric_fields']['samples'],3)
            store=SpectrumResults(root/'spectrum.sqlite')
            self.assertEqual(len(store),3)
            self.assertEqual(store[-1][:3],[2,1510.,17.])
            self.assertEqual(len((root/'phase.csv').read_text().splitlines()),4)
            self.assertEqual(read_json(root/'fields/samples.json')['status'],'complete')

    def test_streamed_spectrum_matches_list_backend_and_phase(self):
        model=sample(wl_step_nm=100);model['measure_phase']=True
        perf=dict(DEFAULT_PERFORMANCE,workers=2,chunk_size=1)
        expected,info=execute(model,perf)
        with tempfile.TemporaryDirectory() as d:
            store=SpectrumResults(Path(d)/'spectrum.sqlite',create=True)
            try:
                actual,diagnostics=execute(model,perf,result_store=store)
                self.assertEqual(list(actual),expected)
                self.assertEqual([list(r) for r in store.phase_rows()],info['phase_rows'])
                self.assertNotIn('phase_rows',diagnostics)
            finally:store.close()
        self.assertEqual(mp.active_children(),[])

    def test_field_session_matches_fresh_for_dispersive_medium_and_angles(self):
        from field_solver import FieldSession,execute_fields
        model=sample()
        model['materials'][0].update(model='table_nk',table=[[1300,1,0],[1600,1.2,0]],grid=[1300,1600])
        perf=dict(DEFAULT_PERFORMANCE,workers=1,timeout_seconds=60)
        cfg=dict(grid=3,depth_samples=3,maps=True,track_contours=True)
        with tempfile.TemporaryDirectory() as d:
            session=FieldSession({k:v for k,v in model.items() if k!='points'},perf)
            try:
                for i,(wave,angle) in enumerate(((1400,0),(1550,23))):
                    local=dict(model,points=[[i,wave,angle]])
                    settings=dict(cfg,wavelength_nm=wave)
                    fresh=Path(d)/f'fresh{i}';reused=Path(d)/f'reused{i}'
                    execute_fields(local,perf,settings,fresh)
                    session(local,perf,settings,reused)
                    self.assertEqual((fresh/'electric_fields.csv').read_text(),(reused/'electric_fields.csv').read_text())
            finally:session.close()
        self.assertEqual(mp.active_children(),[])


if __name__=='__main__':
    mp.freeze_support();unittest.main()
