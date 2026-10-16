"""Supervised native electric-field sampling. Geometry in um, wavelength in nm."""
import csv
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import time
import traceback
from functools import lru_cache

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


@lru_cache(maxsize=2)
def _sampling_layout(signature):
    """Reuse coordinates and material labels across wavelengths, never fields."""
    import numpy as np
    from field_storage import PLANE_NAMES
    model, cfg = json.loads(signature)
    count, depths = cfg.get('grid', 8), cfg.get('depth_samples', 3)
    xs = np.asarray([model['ax']*((i+.5)/count-.5) for i in range(count)])
    ys = np.asarray([model['ay']*((i+.5)/count-.5) for i in range(count)])
    layers, start = [], 0.
    for layer in model['layers'][1:-1]:
        if layer['thickness'] > 0:
            layers.append((layer, start, start+layer['thickness']))
        start += layer['thickness']
    if not layers:
        raise ValueError('Field sampling requires a finite-thickness layer')
    chosen = cfg.get('layer') or next((p['layer'] for p in model['patterns']), layers[0][0]['name'])
    if chosen not in {l['name'] for l, _, _ in layers}:
        raise ValueError('Select a finite-thickness layer for the XY field map')
    layer_names = [l['name'] for l, _, _ in layers]
    material_names = model['materials']
    material_ids = {name: i for i, name in enumerate(material_names)}
    instructions, coords, planes, labels, materials = [], [], [], [], []
    masks, offset = {}, 0

    def append(plane, layer, z, output_ys):
        nonlocal offset
        x, y = np.meshgrid(xs, output_ys, indexing='ij')
        x, y = x.ravel(), y.ravel()
        key = (layer['name'], plane == 'xz')
        if key not in masks:
            ids = np.full(len(x), material_ids[layer['material']], dtype=np.int32)
            for region in model['patterns']:
                if region['layer'] != layer['name']:
                    continue
                angle = math.radians(region['angle'])
                mask = np.zeros(len(x), dtype=bool)
                for ix in (-1, 0, 1):
                    for iy in (-1, 0, 1):
                        dx, dy = x+ix*model['ax']-region['cx'], y+iy*model['ay']-region['cy']
                        u, v = dx*math.cos(angle)+dy*math.sin(angle), -dx*math.sin(angle)+dy*math.cos(angle)
                        if region['shape'] == 'circle':
                            mask |= u*u+v*v < region['sx']**2
                        elif region['shape'] == 'ellipse':
                            mask |= (u/region['sx'])**2+(v/region['sy'])**2 < 1
                        else:
                            mask |= (np.abs(u) < region['sx']/2) & (np.abs(v) < region['sy']/2)
                ids[mask] = material_ids[region['material']]
            masks[key] = ids
        coords.append(np.column_stack((x, y, np.full(len(x), z))))
        planes.append(np.full(len(x), PLANE_NAMES.index(plane), dtype=np.int32))
        labels.append(np.full(len(x), layer_names.index(layer['name']), dtype=np.int32))
        materials.append(masks[key])
        instructions.append((offset, offset+len(x), plane, float(z)))
        offset += len(x)

    for layer, start, stop in layers:
        for fraction in ((k+.5)/depths for k in range(depths)):
            append('volume_samples', layer, start+(stop-start)*fraction, ys)
    if cfg.get('maps', False):
        layer, start, stop = next(t for t in layers if t[0]['name'] == chosen)
        append('xy', layer, (start+stop)/2, ys)
    if cfg.get('track_contours', True):
        for layer, start, stop in layers:
            for j in range(count):
                append('xz', layer, start+(stop-start)*(j+.5)/count, np.asarray([0.]))
    arrays = dict(xyz=np.concatenate(coords), plane=np.concatenate(planes),
                  layer=np.concatenate(labels), material=np.concatenate(materials),
                  layer_names=np.asarray(layer_names), material_names=np.asarray(material_names))
    for value in arrays.values():
        value.flags.writeable = False
    return arrays, instructions, xs, ys


def _sample_field_arrays(sampler, model, cfg):
    import numpy as np
    geometry = {key: model[key] for key in ('ax', 'ay', 'layers', 'patterns')}
    geometry['materials'] = [m['name'] for m in model['materials']]
    settings = {key: cfg[key] for key in ('grid', 'depth_samples', 'layer', 'maps', 'track_contours') if key in cfg}
    layout, instructions, xs, ys = _sampling_layout(json.dumps((geometry, settings), sort_keys=True))
    arrays = dict(layout)
    arrays['E'] = np.empty((len(layout['xyz']), 3), dtype=np.complex128)
    arrays['H'] = np.empty_like(arrays['E'])
    for offset in range(0, len(instructions), 8):
        batch = instructions[offset:offset+8]
        if hasattr(sampler, 'prepare_planes'):
            sampler.prepare_planes([item[3] for item in batch])
        if hasattr(sampler, 'prepare_grid'):
            sampler.prepare_grid(xs, ys, [item[3] for item in batch if item[2] != 'xz'])
        for first, last, plane, z in batch:
            if plane == 'xz':
                e, h = sampler.GetFieldsMany(np.column_stack((xs, np.zeros(len(xs)))), z)
            else:
                e, h = sampler.grid(xs, ys, z)
            arrays['E'][first:last] = np.asarray(e).reshape(-1, 3)
            arrays['H'][first:last] = np.asarray(h).reshape(-1, 3)
    if not np.isfinite(arrays['E']).all() or not np.isfinite(arrays['H']).all():
        raise ValueError('Nonfinite S4 electromagnetic field')
    return arrays


def sample_fields(model, perf, cfg, directory, module=None, simulation=None, solved=False, field_gpu=None):
    from backend import load_runtime, build_simulation
    from field_tracking import enrich_fields
    perf = performance(perf, 1, os.cpu_count() or 1)
    module = module or load_runtime(perf, gpu=gpu_requested(perf))
    before = module.AccelerationInfo()
    started = time.monotonic()
    wavelength = cfg['wavelength_nm']
    reused_spectrum_solution = solved
    simulation = simulation or build_simulation(module, model, wavelength)
    if not solved:
        simulation.SetFrequency(1000/wavelength)
        s, p = ((1., 0.) if model['polarization'] == 's' else (0., -1.) if model['polarization'] == 'p' else (2**-.5, -2**-.5))
        simulation.SetExcitationPlanewave(IncidenceAngles=(model['points'][0][2], model['phi']), sAmplitude=complex(s), pAmplitude=complex(p), Order=0)
        if perf.get('solver_backend') == 'eigenfree-gpu':
            from gpu_solver_runtime import load_cupy
            from eigenfree_scan import FieldView
            from s4_eigenfree_gpu import solve_batch
            cp = load_cupy()
            payload = simulation.GetEigenfreeOperators()
            with cp.cuda.Device(perf['gpu_device']):
                solution = solve_batch([payload], backend='cupy', symmetry=perf['eigenfree_symmetry'])
            simulation = FieldView(solution, 0, payload)
            solved = True
            field_gpu = False
        else:
            from cutoff_solver import cutoff_candidate, solve_cutoff
            if cutoff_candidate(model, wavelength, model['points'][0][2], simulation.GetBasisSet()):
                simulation, _, cutoff_diagnostics = solve_cutoff(simulation, perf)
                solved = True
    from field_sampling import FourierFieldSampler
    sampler = FourierFieldSampler(simulation, model, wavelength, enabled=cfg.get('sampling_backend') != 'point',
                                  threads=perf['threads'], gpu=gpu_requested(perf) if field_gpu is None else field_gpu,
                                  gpu_device=perf['gpu_device'])
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory/'field_model.json', dict(model=model, wavelength_nm=wavelength, settings=cfg))
    from field_storage import write_field_arrays, field_frame
    arrays = _sample_field_arrays(sampler, model, cfg)
    storage_format = cfg.get("storage_format", "array")
    if storage_format == "array":
        write_field_arrays(directory, arrays)
    elif storage_format == "csv":
        field_frame(arrays).to_csv(directory/"electric_fields.csv", index=False)
        (directory/"electric_fields.npz").unlink(missing_ok=True)
    else:
        raise ValueError("Field storage format must be array or csv")
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
                       reused_spectrum_solution=reused_spectrum_solution,
                       statuses={str(os.getpid()): after['status']},
                       **{key: int(after[key])-int(before[key])
                          for key in ('cpu_gemm_calls', 'gpu_gemm_calls', 'gpu_failures')})
    diagnostics['native_gpu_gemm_calls'] = diagnostics['gpu_gemm_calls']
    if perf.get('solver_backend') == 'eigenfree-gpu':
        diagnostics.update(solver_backend='eigenfree-gpu',gpu_solved_points=1,eigendecompositions=0)
    if getattr(getattr(simulation, 'solution', None), 'regular_ports', False):
        diagnostics['exact_cutoff_solution'] = dict(simulation.solution.diagnostics)
    diagnostics['field_gpu_gemm_calls'] = sampler.stats['gpu_grid_batches']
    diagnostics['gpu_gemm_calls'] += diagnostics['field_gpu_gemm_calls']
    diagnostics['gpu_failures'] += sampler.stats['gpu_failures']
    # A shared spectrum solve accounts for its GPU products upstream. Sampling
    # cached fields need not launch another GPU GEMM; still report any failure.
    diagnostics['warnings'] = ([] if (solved or diagnostics['field_gpu_gemm_calls']) and not diagnostics['gpu_failures']
                               else acceleration_warnings(diagnostics, perf))
    write_json(directory/'field_diagnostics.json', diagnostics)
    if perf['require_gpu'] and not solved and (not diagnostics['gpu_gemm_calls'] or diagnostics['gpu_failures']):
        raise RuntimeError('GPU work was required for fields, but it did not complete successfully. '+
                           ' '.join(diagnostics['warnings']))
    features = enrich_fields(directory, arrays=arrays, save=False)
    diagnostics['total_elapsed_seconds'] = time.monotonic()-started
    diagnostics['descriptor_seconds'] = diagnostics['total_elapsed_seconds']-diagnostics['elapsed_seconds']
    write_json(directory/'field_diagnostics.json', diagnostics)
    features['acceleration'] = diagnostics
    write_json(directory/'field_features.json', features, compact=True)
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
    if not isinstance(depths,int) or isinstance(depths,bool) or depths < 3:
        raise ValueError('3D depths per layer must be an integer of at least 3')
    if not isinstance(count,int) or isinstance(count,bool) or count < 3:
        raise ValueError('Field grid must be an integer of at least 3')
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
