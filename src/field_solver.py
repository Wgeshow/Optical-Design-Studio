"""Supervised native electric-field sampling. Geometry in um, wavelength in nm."""
import csv
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import time
import traceback

from data_library import write_json
from gpu_status import gpu_requested, acceleration_warnings
from model import performance


def contains(region, x, y):
    angle = math.radians(region['angle'])
    dx, dy = x-region['cx'], y-region['cy']
    u, v = dx*math.cos(angle)+dy*math.sin(angle), -dx*math.sin(angle)+dy*math.cos(angle)
    if region['shape'] == 'circle':
        return u*u+v*v < region['sx']**2
    if region['shape'] == 'ellipse':
        return (u/region['sx'])**2+(v/region['sy'])**2 < 1
    return abs(u) < region['sx']/2 and abs(v) < region['sy']/2


def material_at(model, layer, x, y):
    material = layer['material']
    for region in model['patterns']:
        if region['layer'] == layer['name']:
            if any(contains(region, x+i*model['ax'], y+j*model['ay']) for i in (-1,0,1) for j in (-1,0,1)):
                material = region['material']
    return material


def sample_fields(model, perf, cfg, directory, module=None, simulation=None, solved=False):
    from backend import load_runtime, build_simulation
    from field_tracking import enrich_fields
    perf = performance(perf, 1, os.cpu_count() or 1)
    module = module or load_runtime(perf, gpu=gpu_requested(perf))
    before = module.AccelerationInfo()
    started = time.monotonic()
    wavelength = cfg['wavelength_nm']
    simulation = simulation or build_simulation(module, model, wavelength)
    if not solved:
        simulation.SetFrequency(1000/wavelength)
        s, p = ((1., 0.) if model['polarization'] == 's' else (0., -1.) if model['polarization'] == 'p' else (2**-.5, -2**-.5))
        simulation.SetExcitationPlanewave(IncidenceAngles=(model['points'][0][2], model['phi']), sAmplitude=complex(s), pAmplitude=complex(p), Order=0)
    from field_sampling import FourierFieldSampler
    sampler = FourierFieldSampler(simulation, model, wavelength, enabled=cfg.get('sampling_backend') != 'point')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory/'field_model.json', dict(model=model, wavelength_nm=wavelength, settings=cfg))
    headers = ['plane','layer','x_um','y_um','z_um','Ex_real','Ex_imag','Ey_real','Ey_imag','Ez_real','Ez_imag','E2','material',
               'Hx_real','Hx_imag','Hy_real','Hy_imag','Hz_real','Hz_imag','Sx','Sy','Sz']
    layers, z = [], 0.
    for layer in model['layers'][1:-1]:
        if layer['thickness'] > 0:
            layers.append((layer,z,z+layer['thickness']))
        z += layer['thickness']
    if not layers:
        raise ValueError('Field sampling requires a finite-thickness layer')
    chosen = cfg.get('layer') or next((p['layer'] for p in model['patterns']), layers[0][0]['name'])
    if chosen not in {l['name'] for l,_,_ in layers}:
        raise ValueError('Select a finite-thickness layer for the XY field map')
    count = cfg.get('grid', 8)
    xs = [model['ax']*((i+.5)/count-.5) for i in range(count)]
    ys = [model['ay']*((i+.5)/count-.5) for i in range(count)]
    material_cache = {}
    with (directory/'electric_fields.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)

        def point(plane, layer, x, y, z, fields):
            electric, magnetic = fields
            electric = [complex(v) for v in electric]
            magnetic = [complex(v) for v in magnetic]
            e2 = sum(abs(v)**2 for v in electric)  # incident electric amplitude squared is one
            if not math.isfinite(e2) or not all(math.isfinite(v.real) and math.isfinite(v.imag) for v in magnetic):
                raise ValueError('Nonfinite S4 electromagnetic field')
            # Time-averaged Poynting convention in S4 normalized units.
            flux = [.5*(electric[(i+1)%3]*magnetic[(i+2)%3].conjugate()
                         - electric[(i+2)%3]*magnetic[(i+1)%3].conjugate()).real for i in range(3)]
            key = (layer['name'], x, y)
            if key not in material_cache:
                material_cache[key] = material_at(model,layer,x,y)
            material = material_cache[key]
            writer.writerow([plane, layer['name'],x,y,z,*[v for e in electric for v in (e.real,e.imag)],e2,material,
                             *[v for h in magnetic for v in (h.real,h.imag)],*flux])

        for layer, start, stop in layers:
            depths = cfg.get('depth_samples', 3)
            for fraction in ((k+.5)/depths for k in range(depths)):
                z = start+(stop-start)*fraction
                electric, magnetic = sampler.grid(xs, ys, z)
                for i, x in enumerate(xs):
                    for j, y in enumerate(ys):
                        point('volume_samples',layer,x,y,z,(electric[i,j],magnetic[i,j]))
                stream.flush()
        if cfg.get('maps', False):
            layer,start,stop = next(t for t in layers if t[0]['name']==chosen)
            z = (start+stop)/2
            electric, magnetic = sampler.grid(xs, ys, z)
            for i, x in enumerate(xs):
                for j, y in enumerate(ys):
                    point('xy',layer,x,y,z,(electric[i,j],magnetic[i,j]))
                stream.flush()
        if cfg.get('track_contours', True):
            for layer,start,stop in layers:
                # Separate rows per layer preserve very thin films in the section.
                for j in range(count):
                    z = start+(stop-start)*(j+.5)/count
                    electric, magnetic = sampler.GetFieldsMany([(x, 0.) for x in xs], z)
                    for i, x in enumerate(xs):
                        point('xz',layer,x,0.,z,(electric[i],magnetic[i]))
                    stream.flush()
    # Geometry-following XZ/XY metrics and sidewall depth profiles enrich learning.
    from airhole_field_objective import aligned_hole, evaluate as evaluate_airhole, DEFAULTS as AIRHOLE_DEFAULTS
    try:
        aligned_hole(model, cfg.get('airhole_settings', AIRHOLE_DEFAULTS)['shell_um'])
    except ValueError:
        pass  # Other geometries retain the existing general field descriptor.
    else:
        write_json(directory/'airhole_field_metrics.json', evaluate_airhole(sampler, model, cfg.get('airhole_settings')))
    after = module.AccelerationInfo()
    diagnostics = dict(performance=perf, elapsed_seconds=time.monotonic()-started, sampling=sampler.stats,
                       reused_spectrum_solution=solved,
                       statuses={str(os.getpid()): after['status']},
                       **{key: int(after[key])-int(before[key])
                          for key in ('cpu_gemm_calls', 'gpu_gemm_calls', 'gpu_failures')})
    # A shared spectrum solve accounts for its GPU products upstream. Sampling
    # cached fields need not launch another GPU GEMM; still report any failure.
    diagnostics['warnings'] = ([] if solved and not diagnostics['gpu_failures']
                               else acceleration_warnings(diagnostics, perf))
    write_json(directory/'field_diagnostics.json', diagnostics)
    if perf['require_gpu'] and not solved and (not diagnostics['gpu_gemm_calls'] or diagnostics['gpu_failures']):
        raise RuntimeError('GPU work was required for fields, but it did not complete successfully. '+
                           ' '.join(diagnostics['warnings']))
    features = enrich_fields(directory)
    diagnostics['total_elapsed_seconds'] = time.monotonic()-started
    diagnostics['descriptor_seconds'] = diagnostics['total_elapsed_seconds']-diagnostics['elapsed_seconds']
    write_json(directory/'field_diagnostics.json', diagnostics)
    features['acceleration'] = diagnostics
    write_json(directory/'field_features.json', features)
    return features


def _worker(connection, model, perf, cfg, directory):
    try:
        connection.send(dict(result=sample_fields(model,perf,cfg,directory)))
    except BaseException:
        connection.send(dict(error=traceback.format_exc()))
    finally:
        connection.close()


def _session_worker(connection, geometry, perf):
    """Reuse the runtime and geometry for every field sample in a scan."""
    from backend import load_runtime, build_simulation
    from model import epsilon
    try:
        perf=performance(perf,1,os.cpu_count() or 1)
        module=load_runtime(perf,gpu=gpu_requested(perf))
        simulation=None
        materials={}
        while True:
            request=connection.recv()
            if request is None:break
            point,cfg,directory=request
            model=dict(geometry,points=[point])
            if simulation is None:
                simulation=build_simulation(module,model,cfg['wavelength_nm'])
                materials={m['name']:epsilon(m,cfg['wavelength_nm']) for m in model['materials']}
            for material in model['materials']:
                if material['model']=='table_nk':
                    value=epsilon(material,cfg['wavelength_nm'])
                    if materials[material['name']]!=value:
                        simulation.SetMaterial(Name=material['name'],Epsilon=value)
                        materials[material['name']]=value
            result=sample_fields(model,perf,cfg,directory,module,simulation)
            connection.send(dict(result=result))
    except (EOFError,BrokenPipeError):
        pass
    except BaseException:
        try:connection.send(dict(error=traceback.format_exc()))
        except (EOFError,BrokenPipeError):pass
    finally:connection.close()


class FieldSession:
    def __init__(self,geometry,perf):
        context=mp.get_context('spawn')
        self.parent,child=context.Pipe()
        self.process=context.Process(target=_session_worker,args=(child,geometry,perf))
        try:self.process.start()
        except BaseException:
            self.parent.close();child.close();raise
        child.close()

    def __call__(self,model,perf,cfg,directory,cancelled=lambda:False):
        from backend import Cancelled
        validate_field_settings(cfg)
        self.parent.send((model['points'][0],cfg,str(directory)))
        started=time.monotonic()
        while not self.parent.poll(.1):
            if cancelled():raise Cancelled('Field sampling cancelled; completed samples retained')
            if time.monotonic()-started>perf['timeout_seconds']:raise TimeoutError('Field sampling exceeded the run timeout')
            if not self.process.is_alive():raise RuntimeError('S4 field worker exited unexpectedly')
        message=self.parent.recv()
        if 'error' in message:raise RuntimeError(message['error'])
        return message['result']

    def close(self):
        try:
            if self.process.is_alive():self.parent.send(None)
        except (OSError,BrokenPipeError):pass
        self.parent.close()
        self.process.join(timeout=.5)
        if self.process.is_alive():
            self.process.terminate();self.process.join(timeout=3)
        if self.process.is_alive():
            self.process.kill();self.process.join()
        self.process.close()


def validate_field_settings(cfg):
    count = cfg.get('grid',8)
    depths = cfg.get('depth_samples',3)
    if not isinstance(depths,int) or isinstance(depths,bool) or not 3 <= depths <= 40:
        raise ValueError('3D depths per layer must be an integer between 3 and 40')
    if not isinstance(count,int) or not 3 <= count <= 80:
        raise ValueError('Field grid must be an integer between 3 and 80')
    if not math.isfinite(cfg['wavelength_nm']) or cfg['wavelength_nm'] <= 0:
        raise ValueError('Field wavelength must be positive')


def execute_fields(model, perf, cfg, directory, cancelled=lambda:False):
    from backend import Cancelled
    validate_field_settings(cfg)
    context = mp.get_context('spawn')
    parent,child = context.Pipe(duplex=False)
    process = context.Process(target=_worker,args=(child,model,perf,cfg,str(directory)))
    started = time.monotonic()
    try:
        process.start()
        child.close()
        while not parent.poll(.1):
            if cancelled():
                raise Cancelled('Field sampling cancelled; completed CSV rows retained')
            if time.monotonic()-started > perf['timeout_seconds']:
                raise TimeoutError('Field sampling exceeded the remaining run timeout')
            if not process.is_alive():
                raise RuntimeError('S4 field worker exited unexpectedly')
        message = parent.recv()
        if 'error' in message:
            raise RuntimeError(message['error'])
        return message['result']
    finally:
        parent.close()
        child.close()
        if process.pid is not None:
            process.join(timeout=.5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=3)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
