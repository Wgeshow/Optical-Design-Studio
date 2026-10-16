"""Electric fields paired with every S4 spectrum sample."""
import copy
import time
from pathlib import Path
from data_library import write_json
from model import integer,number

DEFAULTS=dict(grid=25,depth_samples=3,contour_step=.1)

def validate_settings(options):
    cfg=dict(DEFAULTS,**options)
    for key in ('grid','depth_samples'):
        cfg[key]=integer(cfg[key],key,3)
    cfg['contour_step']=number(cfg['contour_step'],'Contour amplitude step')
    if cfg['contour_step']<=0:raise ValueError('Contour amplitude step must be positive')
    return {k:cfg[k] for k in DEFAULTS}


class SimulationFieldRecorder:
    """Index complete fields from spectrum workers, including out-of-order work."""
    def __init__(self, settings, directory, total, emit):
        from scan_storage import FieldSampleIndex
        self.cfg = validate_settings(settings)
        self.root = Path(directory)/'fields'
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = FieldSampleIndex(self.root, create=True)
        self.root = self.index.root
        self.total, self.emit = total, emit
        self.last_save = self.last_emit = 0.
        self.finished = False
        self.save('running')

    def save(self, status):
        self.index.flush()
        metadata = dict(schema_version=2,status=status,settings=self.cfg,count=len(self.index),index='samples.sqlite')
        if status == 'complete' and len(self.index) <= 1000:
            metadata['samples'] = [self.index.sample(i) for i in range(len(self.index))]
        write_json(self.root/'samples.json',metadata)

    def add(self, ordinal, point):
        index,wavelength,theta = point
        folder = self.root if ordinal == 0 else self.root/'samples'/f'{ordinal+1:06d}'
        self.index.add(ordinal,index,wavelength,theta,folder)
        now = time.monotonic()
        if now-self.last_emit >= .25 or len(self.index) == self.total:
            self.emit(dict(kind='log',text=f'Spectrum and electric fields {len(self.index)}/{self.total}: {wavelength:g} nm, angle {theta:g}°'))
            self.last_emit = now
        if now-self.last_save >= 1.:
            self.save('running');self.last_save = now

    def finish(self, status):
        self.index.compact()
        self.save(status)
        self.finished = True
        return dict(samples=len(self.index),manifest=str(self.root/'samples.json'),index=str(self.index.path),
                    reused_spectrum_solution=True)

    def close(self):
        try:
            if not self.finished:
                self.finish('interrupted')
        finally:
            self.index.close()

def execute_simulation_fields(model,perf,rows,settings,directory,emit=lambda e:None,cancelled=lambda:False,field_executor=None):
    from backend import Cancelled
    from field_solver import FieldSession
    from scan_storage import FieldSampleIndex
    cfg=validate_settings(settings);directory=Path(directory)
    root=directory/'fields';root.mkdir(parents=True,exist_ok=True)
    geometry={k:v for k,v in model.items() if k!='points'}
    session=None
    sample_index=FieldSampleIndex(root,create=True)
    root=sample_index.root
    last_emit=last_save=0.
    def save(status):
        sample_index.flush()
        metadata=dict(schema_version=2,status=status,settings=cfg,count=len(sample_index),index='samples.sqlite')
        # Small-run compatibility only; large scans never rebuild a growing list.
        if status=='complete' and len(sample_index)<=1000:
            metadata['samples']=[sample_index.sample(i) for i in range(len(sample_index))]
        write_json(root/'samples.json',metadata)
    try:
        if field_executor is None:
            session=FieldSession(geometry,perf);field_executor=session
        save('running')
        for i,row in enumerate(rows):
            if cancelled():raise Cancelled('Electric-field sampling cancelled; completed spectrum and fields are saved')
            index,wavelength,theta=row[:3]
            local=copy.deepcopy(geometry);local['points']=[[index,wavelength,theta]]
            folder=root if i==0 else root/'samples'/f'{i+1:06d}'
            now=time.monotonic()
            if now-last_emit>=.25 or i+1==len(rows):
                emit(dict(kind='log',text=f'Electric fields {i+1}/{len(rows)}: {wavelength:g} nm, angle {theta:g}°'))
                last_emit=now
            field_executor(local,perf,dict(cfg,wavelength_nm=wavelength,maps=True,track_contours=True),folder,cancelled)
            sample_index.add(i,index,wavelength,theta,folder)
            if time.monotonic()-last_save>=1.:
                save('running');last_save=time.monotonic()
        save('complete')
        return dict(samples=len(sample_index),manifest=str((root/'samples.json').resolve()),index=str(sample_index.path))
    except BaseException:
        save('interrupted')
        raise
    finally:
        sample_index.close()
        if session is not None:session.close()
