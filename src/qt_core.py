"""Shared desktop project and supervised S4 work, independent of browser events."""
from bootstrap import initialize
initialize(1)

import copy
import json
import math
import os
from collections.abc import Mapping
from numbers import Real
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from types import SimpleNamespace

import pandas as pd
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from desktop_runtime import backend_command, initialize_desktop
if getattr(sys, 'frozen', False) and not os.environ.get('S4_LIBRARY_ROOT'):
    initialize_desktop()
import app as legacy
from data_library import DataLibrary, read_json, write_json
from model import MAT_COLS, LAYER_COLS, PAT_COLS, DEFAULT_PERFORMANCE, MODES, prepare, performance, integer
from structure_builder import validate_structure


def _mapping(value, label):
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f'{label} must be an object with named fields.')
    return copy.deepcopy(dict(value))


def _desktop_number(value, label, *, integral=False, minimum=None, maximum=1e12):
    """Normalize JSON/API numbers before passing them to native Qt setters."""
    if isinstance(value, bool) or not isinstance(value, (Real, str)):
        raise ValueError(f'{label} must be numeric.')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f'{label} must be numeric.') from None
    if not math.isfinite(result):
        raise ValueError(f'{label} must be finite.')
    if integral and not result.is_integer():
        raise ValueError(f'{label} must be a whole number.')
    if (minimum is not None and result < minimum) or (maximum is not None and result > maximum):
        raise ValueError(f'{label} must be between {minimum if minimum is not None else "−∞"} and {maximum}.')
    return int(result) if integral else result


def desktop_settings(values):
    """Validate individual controls, retaining incomplete cross-field drafts."""
    supplied = _mapping(values, 'Settings')
    result = dict(zip(legacy.SET_KEYS, legacy.SET_DEFAULTS))
    result.update({key: value for key, value in supplied.items() if key in result})
    if result['mode'] not in ('Wavelength sweep', 'Angle sweep'):
        raise ValueError('Invalid sweep mode. Choose Wavelength sweep or Angle sweep.')
    if result['polarization'] not in ('s', 'p', '45° s+p'):
        raise ValueError('Invalid polarization. Choose s, p, or 45° s+p.')
    for key in ('ax_um', 'ay_um', 'wl_start_nm', 'wl_stop_nm', 'wl_step_nm', 'fixed_wl_nm'):
        result[key] = _desktop_number(result[key], key, minimum=1e-6)
    result['NumG'] = _desktop_number(result['NumG'], 'Fourier basis count', integral=True, minimum=1, maximum=4096)
    for key in ('theta_deg', 'angle_start', 'angle_stop'):
        result[key] = _desktop_number(result[key], key, minimum=-89.999999, maximum=89.999999)
    result['phi_deg'] = _desktop_number(result['phi_deg'], 'Azimuth', minimum=-360, maximum=360)
    result['angle_step'] = _desktop_number(result['angle_step'], 'Angle step', minimum=1e-6, maximum=179.999999)
    return result


def desktop_performance(values):
    supplied = _mapping(values, 'Performance settings')
    result = dict(DEFAULT_PERFORMANCE)
    result.update({key: value for key, value in supplied.items() if key in result})
    if result['mode'] not in MODES:
        raise ValueError('Invalid CPU/GPU mode.')
    if not isinstance(result['require_gpu'], bool):
        raise ValueError('Require GPU work must be true or false.')
    for key, minimum, maximum in (('workers', 0, 2147483647), ('threads', 1, 2147483647),
            ('gpu_device', 0, 1024), ('gpu_min_n', 1, 2147483647), ('gpu_block', 64, 1024),
            ('chunk_size', 1, 10000), ('timeout_seconds', 1, 2147483647)):
        result[key] = _desktop_number(result[key], key, integral=True, minimum=minimum, maximum=maximum)
    if result['gpu_block'] not in (64, 128, 256, 512, 1024):
        raise ValueError('GPU tile size must be 64, 128, 256, 512 or 1024.')
    # Available CPUs and workers × threads are execution constraints, not a
    # reason to reject a saved setup from a different Windows/Linux computer.
    return result


def desktop_search(values):
    """Saved options remain drafts but must be safe to restore into Qt widgets."""
    result = _mapping(values, 'Desktop search')
    target_numbers = {'target_nm', 'tolerance_nm', 'min_q', 'half_window', 'step'}
    target_integers = {'grid_steps', 'trials', 'initial', 'finalists', 'history', 'field_grid', 'map_grid'}
    target_booleans = {'reuse', 'use_fields', 'track_resonance'}
    peak_integers = {'design_budget', 'refinement_rounds', 'point_budget', 'initial_designs', 'ml_trials',
                     'candidate_pool', 'random_seed', 'finalists', 'verification_step_divisor', 'patience'}
    peak_numbers = {'ratio_limit', 'min_bridge_um', 'absorption_target', 'tie_tolerance', 'prominence',
                    'verification_basis_factor', 'absorption_agreement', 'q_agreement'}
    for kind, value in list(result.items()):
        options = result[kind] = _mapping(value, f'Desktop search {kind}')
        controls = options
        if kind == 'peaks':
            controls = options['search_options'] = _mapping(options.get('search_options', {}), 'Peak search options')
            for key in peak_integers | peak_numbers:
                if key in controls:
                    controls[key] = _desktop_number(controls[key], f'Peak search {key}', integral=key in peak_integers,
                                                     maximum=2147483647 if key in peak_integers else 1e12)
            if 'search_mode' in controls and controls['search_mode'] not in ('Exhaustive grid', 'ML assisted', 'Hybrid verified'):
                raise ValueError('Invalid saved search mode.')
            if 'separate_circles' in controls and not isinstance(controls['separate_circles'], bool):
                raise ValueError('Separate circles must be true or false.')
        elif kind == 'target':
            for key in target_integers | target_numbers:
                if key in controls:
                    controls[key] = _desktop_number(controls[key], f'Target search {key}', integral=key in target_integers,
                                                     maximum=2147483647 if key in target_integers else 1e12)
            for key in target_booleans:
                if key in controls and not isinstance(controls[key], bool):
                    raise ValueError(f'{key} must be true or false.')
        elif kind == 'fields':
            if 'grid' in controls:
                controls['grid'] = _desktop_number(controls['grid'], 'Field grid', integral=True, minimum=3, maximum=80)
            if 'wavelength_nm' in controls:
                controls['wavelength_nm'] = _desktop_number(controls['wavelength_nm'], 'Field wavelength', minimum=1e-6)
            if 'layer' in controls and not isinstance(controls['layer'], str):
                raise ValueError('Field layer must be a layer name.')
    return result


def prepare_job(kind, project, options, library):
    """Use the same validated solver/search contracts as the existing application."""
    project=copy.deepcopy(project)
    options=copy.deepcopy(options)
    cfg=None
    if kind=='diagnostic':
        selected_perf=dict(project['performance'])
        project.update(materials=legacy.records(legacy.DEFAULT_MATERIALS,MAT_COLS),
                       layers=legacy.records(legacy.DEFAULT_LAYERS,LAYER_COLS),
                       patterns=legacy.records(legacy.DEFAULT_PATTERNS,PAT_COLS))
        project['settings']=dict(zip(legacy.SET_KEYS,legacy.SET_DEFAULTS))
        project['settings'].update(wl_start_nm=1550,wl_stop_nm=1550)
        project['performance'].update(workers=1,gpu_min_n=1,chunk_size=1,timeout_seconds=60,require_gpu=False)
    elif kind=='target':
        from target_ui import target_project
        project,bounds=target_project(project,options.get('holes',[]),options.get('bounds',[]),
            options.get('target_nm',1550),options.get('tolerance_nm',5),options.get('min_q',1000),
            options.get('half_window',20),options.get('step',.2),options.get('grid_steps',21))
    elif kind=='fields':
        wavelength=float(options.get('wavelength_nm',1550))
        project['settings'].update(mode='Wavelength sweep',wl_start_nm=wavelength,wl_stop_nm=wavelength)
    elif kind not in ('simulation','peaks'):
        raise ValueError('Unknown calculation: '+kind)
    model=prepare(project['materials'],project['layers'],project['patterns'],library.files_for(project),project['settings'])
    if kind=='peaks':
        from peak_optimizer import parse_search
        from ml_optimizer import validate_ml
        stop=float(project['settings']['wl_stop_nm'])
        if model['mode']=='Wavelength sweep' and model['points'][-1][1]<stop:
            model['points'].append([len(model['points']),stop,model['points'][0][2]])
        bounds=options.get('bounds',[])
        cfg=parse_search(model,bounds,options.get('search_options',{}))
        resume=options.get('resume_history_file')
        if cfg.get('search_mode','Exhaustive grid')!='Exhaustive grid':
            validate_ml(cfg,model)
            if resume:
                if Path(resume).stat().st_size>50*1024*1024:
                    raise ValueError('Resume JSON exceeds 50 MB.')
                cfg['resume_history']=read_json(resume)
        elif resume:
            raise ValueError('Resume history requires ML assisted or Hybrid verified search.')
        cfg.update(input_bounds=bounds,project=project)
    elif kind=='target':
        from peak_optimizer import parse_search
        from ml_optimizer import validate_ml
        target=float(options.get('target_nm',1550))
        tolerance=float(options.get('tolerance_nm',5))
        window=float(options.get('half_window',20))
        waves=sorted(set([p[1] for p in model['points']]+[target,target-tolerance,target+tolerance,target+window]))
        model['points']=[[i,w,model['points'][0][2]] for i,w in enumerate(waves)]
        trials=integer(options.get('trials',40),'New designs',2)
        cfg=parse_search(model,bounds,dict(search_mode='ML assisted',ml_trials=trials,
            initial_designs=options.get('initial',8),finalists=options.get('finalists',3),
            design_budget=trials,point_budget=200000,refinement_rounds=3))
        validate_ml(cfg,model)
        cfg.update(task='target',all_shape_bridges=True,target_nm=target,tolerance_nm=tolerance,
            minimum_q=float(options.get('min_q',1000)),history_limit=integer(options.get('history',300),'History limit',1),
            reuse_saved=bool(options.get('reuse',True)),use_fields=bool(options.get('use_fields',True)),
            track_resonance=bool(options.get('track_resonance',True)),
            field_grid=integer(options.get('field_grid',6),'Field grid',3),
            map_grid=integer(options.get('map_grid',25),'Map grid',3),project=project,input_bounds=bounds)
        if cfg['history_limit']>2000 or cfg['field_grid']>30 or cfg['map_grid']>80:
            raise ValueError('History limit must be ≤2000, training field grid ≤30, and final map grid ≤80.')
    elif kind=='fields':
        grid=integer(options.get('grid',25),'Map grid',3)
        if grid>80:
            raise ValueError('Map grid must be at most 80.')
        cfg=dict(task='fields',wavelength_nm=wavelength,layer=str(options.get('layer') or ''),grid=grid,maps=True,project=project)
    perf=performance(project['performance'],len(model['points']),os.cpu_count() or 1)
    result=dict(model=model,performance=perf,search=cfg)
    if kind=='diagnostic':
        result['diagnostic_selected_performance']=selected_perf
    return project,result


class BackendWorker(QThread):
    event = pyqtSignal(dict)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self,kind,project,options,library,parent=None):
        super().__init__(parent)
        self.kind,self.project,self.options,self.library=kind,project,options,library
        self.cancelled=threading.Event()
        self.directory=None
        self.process=None

    def cancel(self):
        self.cancelled.set()
        if self.directory is not None:
            try:
                (self.directory/'cancel.flag').touch()
            except OSError:
                # The supervisor also checks the in-memory cancellation event.
                pass

    def _stop_process(self):
        if self.process is None or self.process.poll() is not None:
            return
        if os.name=='nt':
            subprocess.run(['taskkill','/PID',str(self.process.pid),'/T','/F'],capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW,timeout=10)
        else:
            os.killpg(self.process.pid,signal.SIGKILL)
        self.process.wait(timeout=5)

    def run(self):
        terminal=None
        failure=None
        status='interrupted'
        try:
            self.event.emit(dict(kind='log',run_kind=self.kind,text='Validating the current project…'))
            project,spec=prepare_job(self.kind,self.project,self.options,self.library)
            if self.cancelled.is_set():
                raise RuntimeError('Calculation cancelled before launch.')
            directory=self.library.runs/uuid.uuid4().hex
            directory.mkdir(parents=True)
            self.directory=directory
            write_json(directory/'project.json',project)
            write_json(directory/'desktop_request.json',dict(kind=self.kind,options=self.options))
            write_json(directory/'job.json',spec)
            self.library.record(directory,kind='simulation' if self.kind in ('simulation','diagnostic') else 'optimization',
                title=dict(simulation='Spectrum',peaks='Peak search',target='Target design',fields='Electric fields',diagnostic='GPU / CPU diagnostic')[self.kind],
                status='running',materials=', '.join(r['Name'] for r in project['materials']))
            command=backend_command(directory/'job.json')
            options=dict(stdout=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',bufsize=1)
            options.update(creationflags=subprocess.CREATE_NO_WINDOW) if os.name=='nt' else options.update(start_new_session=True)
            messages=queue.Queue()
            with (directory/'backend_stderr.txt').open('w',encoding='utf-8') as log:
                self.process=subprocess.Popen(command,stderr=log,**options)
                def read_output():
                    try:
                        for line in self.process.stdout:
                            try:
                                messages.put(json.loads(line))
                            except json.JSONDecodeError:
                                messages.put(dict(kind='log',text=line.rstrip()))
                    finally:
                        messages.put(None)
                reader=threading.Thread(target=read_output,daemon=True)
                reader.start()
                started=time.monotonic()
                deadline=started+float(spec['performance']['timeout_seconds'])+15
                cancel_started=None
                while True:
                    if self.cancelled.is_set():
                        (directory/'cancel.flag').touch()
                        cancel_started=cancel_started or time.monotonic()
                    if time.monotonic()>deadline or cancel_started and time.monotonic()-cancel_started>10:
                        self._stop_process()
                        raise RuntimeError('Calculation cancelled.' if cancel_started else 'Calculation exceeded its time limit.')
                    try:
                        event=messages.get(timeout=.2)
                    except queue.Empty:
                        if self.process.poll() is not None and not reader.is_alive():
                            break
                        continue
                    if event is None:
                        break
                    event.update(directory=str(directory),run_kind=self.kind)
                    self.event.emit(event)
                    if event.get('kind') in ('complete','search_complete'):
                        terminal=event
                        status=event.get('summary',{}).get('status','complete')
                    elif event.get('kind') in ('error','cancelled'):
                        status=event['kind']
                        failure=event.get('error',status)
                self.process.wait(timeout=5)
                if failure:
                    raise RuntimeError(failure)
                if terminal is None:
                    log.flush()
                    detail=(directory/'backend_stderr.txt').read_text(encoding='utf-8')[-3000:]
                    raise RuntimeError(f'Backend exited without a result ({self.process.returncode}). {detail}')
            if self.kind=='diagnostic':
                from gpu_status import runtime_check_summary
                terminal['message']=runtime_check_summary(terminal.get('info',{}),spec['diagnostic_selected_performance'])
            self.library.record(directory,status=status,summary=terminal.get('summary',terminal.get('info',{})))
            self.completed.emit(terminal)
        except Exception as exc:
            failure=str(exc)
            status='cancelled' if self.cancelled.is_set() else 'error'
            self.failed.emit(failure)
        finally:
            try:
                self._stop_process()
            except Exception:
                pass
            if self.process is not None and self.process.stdout:
                self.process.stdout.close()
            if self.directory is not None:
                try:
                    self.library.record(self.directory,status=status)
                except Exception as exc:
                    # Never let a failing disk write escape QThread.run into Qt.
                    self.failed.emit('Could not save the final run status: '+str(exc))


class TaskWorker(QThread):
    completed=pyqtSignal(object)
    failed=pyqtSignal(str)
    def __init__(self,function,parent=None):
        super().__init__(parent)
        self.function=function
    def run(self):
        try:
            self.completed.emit(self.function())
        except Exception as exc:
            self.failed.emit(str(exc))


class ProjectStore(QObject):
    changed=pyqtSignal(str)
    library_changed=pyqtSignal()
    busy_changed=pyqtSignal(bool)
    progress=pyqtSignal(dict)
    run_finished=pyqtSignal(dict)
    run_failed=pyqtSignal(str)
    task_finished=pyqtSignal(str,object)
    task_failed=pyqtSignal(str,str)
    message=pyqtSignal(str)

    def __init__(self,library=None,restore=True,parent=None):
        super().__init__(parent)
        self.library=library or legacy.LIBRARY
        self.context=SimpleNamespace(PRESETS=legacy.PRESETS,LIBRARY=self.library,
            DEFAULT_MATERIALS=legacy.DEFAULT_MATERIALS,DEFAULT_LAYERS=legacy.DEFAULT_LAYERS,DEFAULT_PATTERNS=legacy.DEFAULT_PATTERNS)
        self.materials=legacy.DEFAULT_MATERIALS.copy()
        self.layers=legacy.DEFAULT_LAYERS.copy()
        self.patterns=legacy.DEFAULT_PATTERNS.copy()
        self.settings=dict(zip(legacy.SET_KEYS,legacy.SET_DEFAULTS))
        self.performance=dict(DEFAULT_PERFORMANCE)
        self.files=[]
        self.search_state={}
        self.imported_search={}
        self._undo=[]
        self._worker=None
        self.busy=False
        self.last_result=None
        self.session_path=self.library.data/'desktop_session.json'
        self.restore_error=''
        if restore and self.session_path.exists():
            try:
                self.load_project(read_json(self.session_path),autosave=False)
            except Exception as exc:
                self.restore_error='Could not restore the previous desktop session: '+str(exc)

    def project(self):
        return dict(format_version=3,materials=legacy.records(self.materials,MAT_COLS),
            layers=legacy.records(self.layers,LAYER_COLS),patterns=legacy.records(self.patterns,PAT_COLS),
            settings=copy.deepcopy(self.settings),performance=copy.deepcopy(self.performance),
            desktop_search=copy.deepcopy(self.search_state))

    def portable_project(self):
        return self.library.snapshot(self.project(),self.files)

    def _autosave(self):
        try:
            project=self.portable_project()
        except ValueError:
            project=self.project()
        write_json(self.session_path,project)

    def _capture(self):
        return (self.materials,self.layers,self.patterns,copy.deepcopy(self.settings),
                copy.deepcopy(self.performance),list(self.files),copy.deepcopy(self.search_state),
                copy.deepcopy(self.imported_search),list(self._undo))

    def _finish_change(self,previous,reason=None):
        try:
            self._autosave()
        except Exception:
            (self.materials,self.layers,self.patterns,self.settings,self.performance,self.files,
             self.search_state,self.imported_search,self._undo)=previous
            raise
        if reason:
            self.changed.emit(reason)

    def set_structure(self,materials,layers,patterns,reason='structure'):
        mats,lay,pat=validate_structure(materials,layers,patterns)
        previous=self._capture()
        self._undo.append((self.materials.copy(deep=True),self.layers.copy(deep=True),self.patterns.copy(deep=True)))
        self._undo=self._undo[-30:]
        self.materials=pd.DataFrame(mats,columns=MAT_COLS)
        self.layers=pd.DataFrame(lay,columns=LAYER_COLS)
        self.patterns=pd.DataFrame(pat,columns=PAT_COLS)
        self._finish_change(previous,reason)

    def undo(self):
        if not self._undo:
            raise ValueError('There is no earlier structure edit to restore.')
        previous=self._capture()
        self.materials,self.layers,self.patterns=self._undo.pop()
        self._finish_change(previous,'structure')

    def update_settings(self,values):
        values=desktop_settings(dict(self.settings,**_mapping(values,'Settings')))
        previous=self._capture()
        self.settings=values
        self._finish_change(previous,'settings')

    def update_performance(self,values):
        values=desktop_performance(dict(self.performance,**_mapping(values,'Performance settings')))
        previous=self._capture()
        self.performance=values
        self._finish_change(previous,'performance')

    def save_search(self,key,options):
        values=desktop_search(dict(self.search_state,**{key:options}))
        previous=self._capture()
        self.search_state=values
        self._finish_change(previous)

    def load_project(self,project,autosave=True):
        project=read_json(project) if isinstance(project,(str,Path)) else copy.deepcopy(project)
        project=_mapping(project,'Project')
        settings=desktop_settings(project.get('settings',{}))
        selected_performance=desktop_performance(project.get('performance',{}))
        search_state=desktop_search(project.get('desktop_search',{}))
        imported_search=_mapping(project.get('search',{}),'Search')
        project=self.library.materialize(project)
        m,l,p=validate_structure(project.get('materials',[]),project.get('layers',[]),project.get('patterns',[]))
        # Missing optical tables may belong to a draft. Keep their references,
        # but do not misidentify nonexistent paths as supplied upload files.
        files=[path for path in self.library.files_for(project) if Path(path).is_file()]
        previous=self._capture()
        self.materials=pd.DataFrame(m,columns=MAT_COLS)
        self.layers=pd.DataFrame(l,columns=LAYER_COLS)
        self.patterns=pd.DataFrame(p,columns=PAT_COLS)
        self.settings=settings
        self.performance=selected_performance
        self.files=files
        self.search_state=search_state
        self.imported_search=imported_search
        self._undo.clear()
        if autosave:
            self._finish_change(previous)
        self.changed.emit('project')
        self.notify_library()

    def save_project(self,path=None):
        project=self.portable_project()
        directory=self.library.runs/('project_'+uuid.uuid4().hex)
        directory.mkdir(parents=True)
        target=directory/'s4_project.json'
        write_json(target,project)
        if path:
            write_json(Path(path),project)
        self.library.record(directory,kind='project',status='complete',title='Desktop project')
        self.notify_library()
        return str(Path(path) if path else target)

    def notify_library(self):
        self.library_changed.emit()

    def _set_busy(self,value):
        self.busy=value
        self.busy_changed.emit(value)

    def start_run(self,kind,options=None):
        if self.busy:
            raise ValueError('A calculation or library operation is already running.')
        options=copy.deepcopy(options or {})
        project=self.portable_project()
        self.save_search(kind,options)
        project['desktop_search']=copy.deepcopy(self.search_state)
        worker=BackendWorker(kind,project,options,self.library,self)
        self._worker=worker
        worker.event.connect(self.progress)
        worker.completed.connect(self._completed)
        worker.failed.connect(self.run_failed)
        worker.finished.connect(self._finished)
        self._set_busy(True)
        worker.start()

    def _completed(self,event):
        self.last_result=event
        self.run_finished.emit(event)
        self.notify_library()

    def _finished(self):
        worker=self._worker
        self._worker=None
        self._set_busy(False)
        self.notify_library()
        if worker is not None:
            worker.deleteLater()

    def cancel(self):
        if isinstance(self._worker,BackendWorker):
            self._worker.cancel()
            self.message.emit('Cancellation requested; waiting for native workers to stop…')

    def run_task(self,name,function):
        if self.busy:
            raise ValueError('Wait for the active calculation or library operation to finish.')
        worker=TaskWorker(function,self)
        self._worker=worker
        worker.completed.connect(lambda result:self.task_finished.emit(name,result))
        worker.failed.connect(lambda error:self.task_failed.emit(name,error))
        worker.finished.connect(self._finished)
        self._set_busy(True)
        worker.start()

    def apply_design(self,directory,design_id=None,recommended=False):
        directory=Path(directory)
        if recommended:
            record=read_json(directory/'recommended_design.json')
            project=self.library.from_model(record['model'],read_json(directory/'project.json'))
        else:
            identifier=directory.name
            project,_=self.library.project_for(identifier,int(design_id or 0))
        self.load_project(project)
