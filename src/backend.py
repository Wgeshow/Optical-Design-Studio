"""Isolated coordinator and persistent S4 workers. No GUI/NumPy imports here."""
import argparse
import csv
import json
import math
import multiprocessing as mp
from multiprocessing.connection import wait
import os
from pathlib import Path
import sys
import time
import traceback

from bootstrap import initialize
from model import epsilon, performance
from gpu_status import acceleration_warnings

COUNTERS = ("cpu_gemm_calls", "gpu_gemm_calls", "gpu_failures")


def load_runtime(p, gpu=False):
    initialize(p["threads"])
    # The native guard proves geometry symmetry and otherwise uses the general
    # solver. An explicit zero remains available for reference comparisons.
    os.environ.setdefault('S4_MIRROR_SYMMETRY','1' if p.get('mirror_symmetry',True) else '0')
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    runtime = resource_root / "pcs_s4_runtime"
    if not runtime.is_dir():
        raise RuntimeError("Keep the supplied pcs_s4_runtime folder beside app.py and backend.py")
    native = runtime / sys.platform
    if not native.is_dir(): native = runtime
    sys.path.insert(0, str(runtime))
    if native != runtime: sys.path.insert(0, str(native))
    os.environ["S4_GPU_BLOCK"] = str(p["gpu_block"])
    from s4_runtime import configure
    configure(threads=p["threads"], gpu=gpu, gpu_device=p["gpu_device"],
              gpu_min_n=p["gpu_min_n"], base_fallback=False)
    try:
        import S4
    except ImportError as exc:
        raise RuntimeError(("Cannot import S4. On Linux run bash setup_linux.sh to build the matching extension. "
                            "On Windows use 64-bit Python 3.12 with MKL 2023.1. ") + str(exc)) from exc
    if not hasattr(S4, "AccelerationInfo") or Path(S4.__file__).resolve().parent != native.resolve():
        raise RuntimeError(f"Unexpected S4 module: {S4.__file__}")
    return S4


def build_simulation(module, model, wavelength, reuse_layers=True):
    simulation = module.New(Lattice=((model["ax"], 0.0), (0.0, model["ay"])), NumBasis=model["basis"])
    for mat in model["materials"]:
        simulation.SetMaterial(Name=mat["name"], Epsilon=epsilon(mat, wavelength))
    from circle_geometry import solver_regions
    regions = solver_regions(model)
    canonical, copied = {}, set()
    for index, layer in enumerate(model['layers']):
        # Thickness changes propagation, not a layer's eigenmodes. Copy only
        # exact material identities and ordered solver geometry; dispersive
        # materials with equal epsilon at one wavelength remain distinct.
        pattern = [{k:v for k,v in region.items() if k != 'layer'}
                   for region in regions if region['layer'] == layer['name']]
        key = (layer['material'], json.dumps(pattern, sort_keys=True))
        internal = 0 < index < len(model['layers'])-1
        if reuse_layers and internal and key in canonical and hasattr(simulation, 'AddLayerCopy'):
            simulation.AddLayerCopy(Name=layer['name'], Thickness=layer['thickness'], S4_Layer=canonical[key])
            copied.add(layer['name'])
        else:
            simulation.AddLayer(Name=layer['name'], Thickness=layer['thickness'], S4_Material=layer['material'])
            if internal:
                canonical.setdefault(key, layer['name'])
    for region in regions:
        if region['layer'] in copied:
            continue
        common = dict(S4_Layer=region["layer"], S4_Material=region["material"], Center=(region["cx"], region["cy"]))
        if region["shape"] == "polygon":
            simulation.SetRegionPolygon(region['layer'], region['material'], (0., 0.), 0., tuple(tuple(v) for v in region['vertices']))
        elif region["shape"] == "circle":
            simulation.SetRegionCircle(**common, Radius=region["sx"])
        else:
            halfwidths = (region["sx"], region["sy"])
            if region["shape"] == "rectangle":
                halfwidths = tuple(v / 2 for v in halfwidths)
            method = simulation.SetRegionEllipse if region["shape"] == "ellipse" else simulation.SetRegionRectangle
            method(**common, Angle=region["angle"], Halfwidths=halfwidths)
    return simulation


def worker(connection, model, p, gpu, field_job=None):
    """Only plain dictionaries cross process boundaries; S4 is worker-local."""
    try:
        module = load_runtime(p, gpu)
        simulation = None
        material_values = {}
        basis_orders = None
        from cutoff_solver import cutoff_candidate, solve_cutoff
        pol = model["polarization"]
        samp, pamp = ((1.0, 0.0) if pol == "s" else (0.0, 1.0) if pol == "p" else (2**-.5, 2**-.5))
        # Original C++ GUI: v = k cross s. Python's p basis has the opposite
        # sign. Pure-p powers are unchanged, but mixed s+p needs this phase.
        pamp = -pamp
        connection.send({"kind": "ready", "pid": os.getpid(), "gpu": gpu, "module": module.__file__})
        while True:
            batch = connection.recv()
            if batch is None:
                break
            before = module.AccelerationInfo()
            rows = []
            phase_rows = []
            failures = []
            cutoff_solutions = []
            for item in batch:
                if field_job is None:
                    index, wavelength, theta = item
                else:
                    ordinal, index, wavelength, theta = item
                if simulation is None:
                    simulation = build_simulation(module, model, wavelength)
                for mat in model["materials"]:
                    if mat["model"] == "table_nk":
                        value = epsilon(mat, wavelength)
                        if material_values.get(mat["name"]) != value:
                            simulation.SetMaterial(Name=mat["name"], Epsilon=value)
                            material_values[mat["name"]] = value
                simulation.SetFrequency(1000.0 / wavelength)
                # Refresh even at fixed theta: dispersive incident media change
                # the in-plane wavevector. This does not rebuild the geometry.
                simulation.SetExcitationPlanewave(IncidenceAngles=(theta, model["phi"]),
                    sAmplitude=complex(samp), pAmplitude=complex(pamp), Order=0)
                if basis_orders is None:
                    basis_orders = simulation.GetBasisSet()
                point_simulation = simulation
                exact_cutoff = cutoff_candidate(model, wavelength, theta, basis_orders)
                if exact_cutoff:
                    point_simulation, power, diagnostics = solve_cutoff(simulation, p)
                    cutoff_solutions.append(dict(point_index=index,wavelength_nm=wavelength,
                        angle_deg=theta,method='exact Maxwell radiation ports',**diagnostics))
                    forward, backward = 1., power[0]
                    transmitted = power[1]
                else:
                    forward, backward = simulation.GetPowerFlux(model["layers"][0]["name"], 0.0)
                    transmitted, _ = simulation.GetPowerFlux(model["layers"][-1]["name"], 0.0)
                # Match the original C++ runner: time-averaged REAL power flux.
                incident = abs(complex(forward).real)
                if not math.isfinite(incident) and model.get('allow_unavailable_points') and field_job is None:
                    failures.append(dict(point_index=index,wavelength_nm=wavelength,angle_deg=theta,
                        reason='Nonfinite incident power; the exact S4 point is unavailable.'))
                    rows.append([index,wavelength,theta,None,None,None])
                    simulation,material_values = None,{}
                    continue
                if not math.isfinite(incident) or incident < 1e-15:
                    raise ValueError(f"Zero/nonfinite incident power at {wavelength:g} nm, theta={theta:g}")
                reflection = abs(complex(backward).real) / incident
                transmission = abs(complex(transmitted).real) / incident
                absorption = 1 - reflection - transmission
                if not all(math.isfinite(v) for v in (reflection, transmission, absorption)):
                    if model.get('allow_unavailable_points') and field_job is None:
                        failures.append(dict(point_index=index,wavelength_nm=wavelength,angle_deg=theta,
                            reason='Nonfinite S4 R/T/A. Exact diffraction cutoffs can be singular; no interpolation was substituted.'))
                        rows.append([index,wavelength,theta,None,None,None])
                        # Retire the singular solution rather than carrying its
                        # native caches into the next exact wavelength.
                        simulation,material_values = None,{}
                        continue
                    raise ValueError(f"Nonfinite result at {wavelength:g} nm, theta={theta:g}. "
                                     "Check geometry, material data and basis convergence. Exact diffraction-order "
                                     "cutoffs can make S4 singular; no fabricated/interpolated result was substituted.")
                rows.append([index, wavelength, theta, reflection, transmission, absorption])
                if model.get('measure_phase'):
                    from spectral_phase import measure_phase
                    phase_rows.append([index, wavelength, theta, *measure_phase(point_simulation, model, wavelength, theta)])
                if field_job is not None:
                    # Save the spectrum before the longer field/contour stage.
                    info = module.AccelerationInfo()
                    connection.send(dict(kind='result', batch_done=False, rows=rows, phase_rows=phase_rows, status=info['status'],
                        cutoff_solutions=cutoff_solutions,**{key:int(info[key])-int(before[key]) for key in COUNTERS}))
                    before = info
                    rows, phase_rows = [], []
                    cutoff_solutions = []
                    from field_solver import sample_fields
                    root = Path(field_job['root'])
                    folder = root if ordinal == 0 else root/'samples'/f'{ordinal+1:06d}'
                    local = dict(model, points=[[index,wavelength,theta]])
                    settings = dict(field_job['settings'],wavelength_nm=wavelength,maps=True,track_contours=True)
                    field_features = sample_fields(local,p,settings,folder,module,point_simulation,solved=True,field_gpu=gpu)
                    info = module.AccelerationInfo()
                    counters = {key:int(info[key])-int(before[key]) for key in COUNTERS}
                    counters['gpu_gemm_calls'] += field_features['acceleration'].get('field_gpu_gemm_calls', 0)
                    counters['gpu_failures'] += field_features['acceleration']['sampling'].get('gpu_failures', 0)
                    connection.send(dict(kind='field_result', ordinal=ordinal, point=[index,wavelength,theta], status=info['status'],
                        **counters))
                    before = info
            info = module.AccelerationInfo()
            connection.send(dict(kind="result", rows=rows, phase_rows=phase_rows, failures=failures,
                                 cutoff_solutions=cutoff_solutions,status=info["status"],
                                 **{key: int(info[key]) - int(before[key]) for key in COUNTERS}))
    except (EOFError, BrokenPipeError):
        pass
    except BaseException:
        try:
            connection.send({"kind": "error", "error": traceback.format_exc()})
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        connection.close()


class Cancelled(RuntimeError):
    pass


def execute(model, p, emit=lambda event: None, cancelled=lambda: False, checkpoint=None, result_store=None,
            field_settings=None, field_directory=None):
    """Bounded, dynamically balanced point batches with exactly one GPU owner."""
    if p.get('solver_backend') == 'eigenfree-gpu':
        from eigenfree_scan import execute as execute_eigenfree
        return execute_eigenfree(model,p,emit,cancelled,checkpoint,result_store,field_settings,field_directory)
    points = model["points"]
    p = performance(p, len(points), os.cpu_count() or 1)
    context = mp.get_context("spawn")
    workers, connections, busy, reserved = [], {}, set(), {}
    rows, statuses = [], {}
    completed = 0
    unavailable, failure_preview = 0, []
    cutoff_count, cutoff_preview = 0, []
    phase_rows = []
    counters = dict.fromkeys(COUNTERS, 0)
    info = dict(performance=p, workers=[], **counters)
    started, next_index, last_emit = time.monotonic(), 0, 0.0
    native_model = {key: value for key, value in model.items() if key != "points"}
    field_recorder = None
    field_job = None
    if field_settings is not None:
        from simulation_fields import SimulationFieldRecorder
        if field_directory is None:
            raise ValueError('Combined field sampling requires an output directory')
        field_recorder = SimulationFieldRecorder(field_settings, field_directory, len(points), emit)
        field_job = dict(root=str(field_recorder.root), settings=field_recorder.cfg)
    def batch_at(start):
        batch = points[start:start + p['effective_chunk']]
        if field_job is not None:
            return [[start+j,*point] for j,point in enumerate(batch)]
        return batch
    try:
        for index in range(p["effective_workers"]):
            parent, child = context.Pipe()
            process = context.Process(target=worker, args=(child, native_model, p, bool(p["gpu_workers"] and index == 0), field_job), daemon=True)
            try:
                process.start()
            except BaseException:
                parent.close()
                child.close()
                raise
            child.close()
            workers.append(process)
            connections[parent] = process
            # Reserve initial work so a slower-starting GPU process is not starved.
            reserved[parent] = batch_at(next_index)
            next_index += len(reserved[parent])
        emit(dict(kind="started", total=len(points), performance=p))
        while completed < len(points) or busy:
            if cancelled():
                raise Cancelled("Cancelled by user; worker processes stopped")
            if time.monotonic() - started > p["timeout_seconds"]:
                raise TimeoutError(f"Run exceeded {p['timeout_seconds']} seconds; worker processes stopped")
            ready = wait(list(connections), timeout=0.15)
            for connection in ready:
                try:
                    message = connection.recv()
                except (EOFError, OSError) as exc:
                    raise RuntimeError(f"S4 worker {connections[connection].pid} exited unexpectedly") from exc
                if message["kind"] == "error":
                    raise RuntimeError(message["error"])
                if message["kind"] == "ready":
                    info["workers"].append({key: message[key] for key in ("pid", "gpu", "module")})
                elif message["kind"] == "result":
                    if message.get('batch_done', True):
                        busy.discard(connection)
                    if result_store is None:
                        rows.extend(message["rows"])
                        phase_rows.extend(message.get("phase_rows", []))
                    else:
                        result_store.add_batch(message["rows"], message.get("phase_rows", []))
                        result_store.add_failures(message.get('failures',[]))
                    failures=message.get('failures',[])
                    unavailable+=len(failures)
                    failure_preview.extend(failures[:max(0,8-len(failure_preview))])
                    cutoff_solutions=message.get('cutoff_solutions',[])
                    cutoff_count+=len(cutoff_solutions)
                    cutoff_preview.extend(cutoff_solutions[:max(0,8-len(cutoff_preview))])
                    completed += len(message['rows'])
                    if checkpoint is not None:
                        checkpoint(message["rows"])
                    statuses[str(connections[connection].pid)] = message["status"]
                    for key in COUNTERS:
                        counters[key] += message[key]
                elif message['kind'] == 'field_result':
                    field_recorder.add(message['ordinal'], message['point'])
                    statuses[str(connections[connection].pid)] = message['status']
                    for key in COUNTERS:
                        counters[key] += message[key]
                if message['kind'] not in ('ready','result') or not message.get('batch_done',True):
                    continue
                if connection in reserved:
                    connection.send(reserved.pop(connection))
                    busy.add(connection)
                elif next_index < len(points):
                    batch = batch_at(next_index)
                    next_index += len(batch)
                    connection.send(batch)
                    busy.add(connection)
            for process in workers:
                if not process.is_alive():
                    raise RuntimeError(f"S4 worker {process.pid} exited (code {process.exitcode})")
            now = time.monotonic()
            done = completed if field_recorder is None else len(field_recorder.index)
            if now - last_emit >= .25 or not busy and completed == len(points):
                emit(dict(kind="progress", done=done, spectrum_done=completed, total=len(points), elapsed=now-started,
                          statuses=statuses, unavailable_points=unavailable,**counters))
                last_emit = now
        if completed and unavailable == completed:
            raise RuntimeError('No finite spectrum samples were produced. Check the geometry, materials and excitation; all unavailable points were saved.')
        if p["require_gpu"] and (counters["gpu_gemm_calls"] == 0 or counters["gpu_failures"]):
            raise RuntimeError("GPU work was required, but no GPU products completed or a GPU failure occurred. Check GPU device, threshold and runtime. " + repr(statuses))
        info.update(counters)
        info.update(statuses=statuses, elapsed_seconds=time.monotonic()-started, points=completed, warnings=list(model.get("warnings", [])))
        info.update(valid_points=completed-unavailable,unavailable_points=unavailable,unavailable_preview=failure_preview)
        info.update(exact_cutoff_points=cutoff_count,exact_cutoff_preview=cutoff_preview)
        if unavailable:
            info['warnings'].append(f'{unavailable} exact spectrum point(s) are unavailable. R/T/A are blank there; see unavailable_points.csv. No interpolation was used.')
        info["warnings"].extend(acceleration_warnings(info, p))
        if field_recorder is not None:
            info['electric_fields'] = field_recorder.finish('complete')
        if result_store is not None:
            info['result_storage'] = str(result_store.path)
            return result_store, info
        rows.sort(key=lambda row: row[0])
        if model.get("measure_phase"):
            info["phase_rows"] = sorted(phase_rows, key=lambda row: row[0])
        return rows, info
    finally:
        # On success, clean shutdown; on cancellation/error, interrupt native work.
        for connection, process in connections.items():
            if process.is_alive() and connection not in busy:
                try:
                    connection.send(None)
                except (OSError, BrokenPipeError):
                    pass
        for process in workers:
            process.join(timeout=.25)
        for process in workers:
            if process.is_alive():
                process.terminate()
        for process in workers:
            process.join(timeout=3)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            process.close()
        for connection in connections:
            connection.close()
        if field_recorder is not None:
            field_recorder.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    directory = args.job.resolve().parent
    from evaluation_storage import EvaluationRecorder
    executor = EvaluationRecorder(directory, execute)
    def emit(event):
        if event.get('kind') in ('complete', 'search_complete') and specification.get('benchmark'):
            from benchmark_registry import complete_event
            event = complete_event(event, specification, directory)
        print(json.dumps(event, allow_nan=False), flush=True)
    try:
        from data_library import read_json
        specification = read_json(args.job)
        if specification.get("search") is not None:
            search = specification['search']
            if search.get('task') == 'research_simulation':
                from research_simulation import execute_research
                event=execute_research(search,directory,emit,lambda:(directory/'cancel.flag').exists())
                emit(event)
                return 0
            if search.get('task') == 'electrical':
                from electrical_optics import execute_electrical
                event=execute_electrical(specification.get('model'),specification['performance'],search,
                    directory,executor,emit,lambda:(directory/'cancel.flag').exists())
                emit(event)
                return 0
            if search.get('task') == 'simulation_fields':
                from spectrum_field_job import execute_field_job
                features=execute_field_job(specification['model'],specification['performance'],search,
                    directory,emit,lambda:(directory/'cancel.flag').exists())
                emit(dict(kind='search_complete',directory=str(directory),summary=dict(status='complete',task='simulation_fields',electric_fields=features)))
                return 0
            if search.get('task') == 'ai_search':
                from ai_campaign import execute_campaign
                event=execute_campaign(specification['model'],specification['performance'],search,directory,executor,emit,lambda:(directory/'cancel.flag').exists())
                emit(event)
                return 0
            if search.get('task') == 'index_shift':
                from index_shift import execute_sweep
                event=execute_sweep(specification['model'],specification['performance'],search,
                    directory,executor,emit,lambda:(directory/'cancel.flag').exists())
                emit(event)
                return 0
            if search.get('task') == 'fields':
                from field_solver import execute_fields
                from data_library import write_json
                features = execute_fields(specification['model'], specification['performance'], search,
                                          directory/'fields', lambda: (directory/'cancel.flag').exists())
                summary = dict(status='complete', task='fields', field_features=features)
                write_json(directory/'search_summary.json', summary)
                emit(dict(kind='search_complete', directory=str(directory), summary=summary))
                return 0
            if search.get('task') == 'target':
                from target_optimizer import execute_target_search
                event = execute_target_search(specification['model'], specification['performance'], search,
                                              directory, executor, emit, lambda: (directory/'cancel.flag').exists())
                emit(event)
                return 0 if event['summary']['status'] == 'complete' else 2
            if specification['search'].get('search_mode', 'Exhaustive grid') == 'Exhaustive grid':
                from peak_optimizer import execute_search
            else:
                from ml_optimizer import execute_ml_search as execute_search

            event = execute_search(specification["model"], specification["performance"],
                                   specification["search"], directory, executor, emit,
                                   lambda: (directory / "cancel.flag").exists())
            emit(event)
            return 0 if event["summary"]["status"] == "complete" else 2
        from scan_storage import SpectrumResults
        if specification.get('simulation_fields') is None:
            specification['model']['allow_unavailable_points']=True
        result_store = SpectrumResults(directory / 'spectrum.sqlite', create=True)
        try:
            rows, info = executor(specification["model"], specification["performance"], emit,
                                 lambda: (directory / "cancel.flag").exists(), result_store=result_store,
                                 field_settings=specification.get('simulation_fields'), field_directory=directory)
        finally:
            # Finalize every received spectrum row even if fields, cancellation
            # or a later worker fails. Parallel completion can leave scan-id gaps.
            try:
                emit(dict(kind='finalizing', points=len(result_store), text='Saving completed spectrum samples…'))
                if specification['model'].get('measure_phase'):
                    from spectral_phase import write_phase_csv
                    write_phase_csv(directory / 'phase.csv', result_store.phase_rows())
                result_store.export_csv(directory / 'results.csv')
                result_store.export_failures(directory / 'unavailable_points.csv')
            finally:
                result_store.close()
        output = directory / "results.csv"
        (directory / "diagnostics.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        emit(dict(kind="complete", output=str(output), diagnostics=str(directory / "diagnostics.json"), info=info))
        return 0
    except Cancelled as exc:
        emit(dict(kind="cancelled", error=str(exc)))
        return 2
    except BaseException:
        error = traceback.format_exc()
        (directory / "error.txt").write_text(error, encoding="utf-8")
        emit(dict(kind="error", error=error))
        return 1


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
