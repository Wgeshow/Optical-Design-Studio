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


def build_simulation(module, model, wavelength):
    simulation = module.New(Lattice=((model["ax"], 0.0), (0.0, model["ay"])), NumBasis=model["basis"])
    for mat in model["materials"]:
        simulation.SetMaterial(Name=mat["name"], Epsilon=epsilon(mat, wavelength))
    for layer in model["layers"]:
        simulation.AddLayer(Name=layer["name"], Thickness=layer["thickness"], S4_Material=layer["material"])
    for region in model["patterns"]:
        common = dict(S4_Layer=region["layer"], S4_Material=region["material"], Center=(region["cx"], region["cy"]))
        if region["shape"] == "circle":
            simulation.SetRegionCircle(**common, Radius=region["sx"])
        else:
            halfwidths = (region["sx"], region["sy"])
            if region["shape"] == "rectangle":
                halfwidths = tuple(v / 2 for v in halfwidths)
            method = simulation.SetRegionEllipse if region["shape"] == "ellipse" else simulation.SetRegionRectangle
            method(**common, Angle=region["angle"], Halfwidths=halfwidths)
    return simulation


def worker(connection, model, p, gpu):
    """Only plain dictionaries cross process boundaries; S4 is worker-local."""
    try:
        module = load_runtime(p, gpu)
        simulation = None
        material_values = {}
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
            for index, wavelength, theta in batch:
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
                forward, backward = simulation.GetPowerFlux(model["layers"][0]["name"], 0.0)
                transmitted, _ = simulation.GetPowerFlux(model["layers"][-1]["name"], 0.0)
                # Match the original C++ runner: time-averaged REAL power flux.
                incident = abs(complex(forward).real)
                if not math.isfinite(incident) or incident < 1e-15:
                    raise ValueError(f"Zero/nonfinite incident power at {wavelength:g} nm, theta={theta:g}")
                reflection = abs(complex(backward).real) / incident
                transmission = abs(complex(transmitted).real) / incident
                absorption = 1 - reflection - transmission
                if not all(math.isfinite(v) for v in (reflection, transmission, absorption)):
                    raise ValueError(f"Nonfinite result at {wavelength:g} nm, theta={theta:g}. "
                                     "Check geometry, material data and basis convergence. Exact diffraction-order "
                                     "cutoffs can make S4 singular; no fabricated/interpolated result was substituted.")
                rows.append([index, wavelength, theta, reflection, transmission, absorption])
            info = module.AccelerationInfo()
            connection.send(dict(kind="result", rows=rows, status=info["status"],
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


def execute(model, p, emit=lambda event: None, cancelled=lambda: False, checkpoint=None):
    """Bounded, dynamically balanced point batches with exactly one GPU owner."""
    points = model["points"]
    p = performance(p, len(points), os.cpu_count() or 1)
    context = mp.get_context("spawn")
    workers, connections, busy, reserved = [], {}, set(), {}
    rows, statuses = [], {}
    counters = dict.fromkeys(COUNTERS, 0)
    info = dict(performance=p, workers=[], **counters)
    started, next_index, last_emit = time.monotonic(), 0, 0.0
    native_model = {key: value for key, value in model.items() if key != "points"}
    try:
        for index in range(p["effective_workers"]):
            parent, child = context.Pipe()
            process = context.Process(target=worker, args=(child, native_model, p, bool(p["gpu_workers"] and index == 0)), daemon=True)
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
            reserved[parent] = points[next_index:next_index + p["effective_chunk"]]
            next_index += len(reserved[parent])
        emit(dict(kind="started", total=len(points), performance=p))
        while len(rows) < len(points):
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
                    busy.discard(connection)
                    rows.extend(message["rows"])
                    if checkpoint is not None:
                        checkpoint(message["rows"])
                    statuses[str(connections[connection].pid)] = message["status"]
                    for key in COUNTERS:
                        counters[key] += message[key]
                if connection in reserved:
                    connection.send(reserved.pop(connection))
                    busy.add(connection)
                elif next_index < len(points):
                    batch = points[next_index:next_index + p["effective_chunk"]]
                    next_index += len(batch)
                    connection.send(batch)
                    busy.add(connection)
            for process in workers:
                if not process.is_alive():
                    raise RuntimeError(f"S4 worker {process.pid} exited (code {process.exitcode})")
            now = time.monotonic()
            if now - last_emit >= .25 or len(rows) == len(points):
                emit(dict(kind="progress", done=len(rows), total=len(points), elapsed=now-started,
                          statuses=statuses, **counters))
                last_emit = now
        if p["require_gpu"] and (counters["gpu_gemm_calls"] == 0 or counters["gpu_failures"]):
            raise RuntimeError("GPU work was required, but no GPU products completed or a GPU failure occurred. Check GPU device, threshold and runtime. " + repr(statuses))
        info.update(counters)
        info.update(statuses=statuses, elapsed_seconds=time.monotonic()-started, points=len(rows), warnings=list(model.get("warnings", [])))
        info["warnings"].extend(acceleration_warnings(info, p))
        rows.sort(key=lambda row: row[0])
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    directory = args.job.resolve().parent
    from evaluation_storage import EvaluationRecorder
    executor = EvaluationRecorder(directory, execute)
    def emit(event):
        print(json.dumps(event, allow_nan=False), flush=True)
    try:
        specification = json.loads(args.job.read_text(encoding="utf-8"))
        if specification.get("search") is not None:
            search = specification['search']
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
        rows, info = executor(specification["model"], specification["performance"], emit,
                             lambda: (directory / "cancel.flag").exists())
        output = directory / "results.csv"
        with output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["wavelength_nm", "angle_deg", "R", "T", "A", "R_plus_T_plus_A"])
            for _, wavelength, theta, reflection, transmission, absorption in rows:
                writer.writerow([wavelength, theta, reflection, transmission, absorption, reflection+transmission+absorption])
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
