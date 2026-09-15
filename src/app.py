"""Local cross-platform optical design studio for the optimized S4 runtime."""
from bootstrap import initialize
initialize(1)  # GUI math is light; workers set their own limits before importing S4.

import argparse
import html
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid

import gradio as gr
import matplotlib.pyplot as plt
import pandas as pd

from model import MAT_COLS, LAYER_COLS, PAT_COLS, MODES, DEFAULT_PERFORMANCE, prepare, performance

FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
# Frozen resources are read-only/internal; user results belong beside the EXE.
ROOT = Path(sys.executable).resolve().parent if FROZEN else RESOURCE_ROOT
from data_library import DataLibrary, write_json
LIBRARY = DataLibrary(os.environ.get("S4_LIBRARY_ROOT", str(ROOT)))
RUNS = LIBRARY.runs
CPUS = os.cpu_count() or 1
SET_KEYS = ["ax_um", "ay_um", "NumG", "mode", "wl_start_nm", "wl_stop_nm", "wl_step_nm", "fixed_wl_nm",
            "theta_deg", "phi_deg", "angle_start", "angle_stop", "angle_step", "polarization"]
SET_DEFAULTS = [.77, .77, 32, "Wavelength sweep", 1515, 1555, .1, 1550, 0, 0, 0, 60, 2, "p"]
PERF_KEYS = list(DEFAULT_PERFORMANCE)
DEFAULT_MATERIALS = pd.DataFrame([
    ["Air", "constant_nk", 1., 0., "", "nm"],
    ["GaAs", "constant_nk", 3.4, 0., "", "nm"],
    ["SiO2", "constant_nk", 1.45, 0., "", "nm"],
], columns=MAT_COLS)
DEFAULT_LAYERS = pd.DataFrame([["AirAbove", 0, "Air"], ["Device", .25, "GaAs"], ["Substrate", 0, "SiO2"]], columns=LAYER_COLS)
DEFAULT_PATTERNS = pd.DataFrame([["circle", "Device", "Air", 0., 0., .1, 0., 0.]], columns=PAT_COLS)
PRESETS = {
    "Air / Vacuum": ["Air", "constant_nk", 1., 0., "", "nm"],
    "SiO2 (constant approximation)": ["SiO2", "constant_nk", 1.45, 0., "", "nm"],
    "GaAs (constant approximation near IR)": ["GaAs", "constant_nk", 3.4, 0., "", "nm"],
    "Si (constant approximation near IR)": ["Si", "constant_nk", 3.48, 0., "", "nm"],
    "PMMA (constant approximation)": ["PMMA", "constant_nk", 1.5, 0., "", "nm"],
    "Au (constant epsilon example at 1550 nm)": ["Au", "constant_eps", -115.13, 11.259, "", "nm"],
}
_jobs = {}
_jobs_lock = threading.Lock()
# Also protects direct Python/API invocation, not just Gradio's shared queue.
_compute_lock = threading.Lock()


def clean_df(df, columns):
    if df is None:
        return pd.DataFrame(columns=columns)
    result = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(df, columns=columns)
    for column in columns:
        if column not in result:
            result[column] = None
    return result[columns].dropna(how="all").reset_index(drop=True)


def records(df, columns):
    result = clean_df(df, columns).astype(object)
    return result.where(pd.notna(result), None).to_dict("records")


def add_material_row(df):
    result = clean_df(df, MAT_COLS)
    result.loc[len(result)] = [f"Material{len(result)+1}", "table_nk", None, None, "", "nm"]
    return result


def add_layer_row(df):
    result = clean_df(df, LAYER_COLS)
    result.loc[len(result)] = [f"Layer{len(result)+1}", .1, "Air"]
    return result


def add_pattern_row(df):
    result = clean_df(df, PAT_COLS)
    result.loc[len(result)] = ["circle", "Device", "Air", 0, 0, .1, 0, 0]
    return result


def add_preset(df, preset):
    result = clean_df(df, MAT_COLS)
    row = PRESETS[preset] if preset in PRESETS else [LIBRARY.presets()[preset]["project"]["materials"][0].get(k) for k in MAT_COLS]
    if row[0] in set(result.Name.astype(str)):
        result.loc[result.Name.astype(str) == row[0], :] = row
    else:
        result.loc[len(result)] = row
    return result


def make_project(materials, layers, patterns, values):
    count = len(SET_KEYS)
    return dict(format_version=2, materials=records(materials, MAT_COLS), layers=records(layers, LAYER_COLS),
                patterns=records(patterns, PAT_COLS), settings=dict(zip(SET_KEYS, values[:count])),
                performance=dict(zip(PERF_KEYS, values[count:])))


def session_key(request):
    return getattr(request, "session_hash", None) or "local"


def cancel_run(request: gr.Request):
    with _jobs_lock:
        record = _jobs.get(session_key(request))
        if record:
            record["cancel"].touch()
            return "Cancellation requested. Waiting for worker processes to stop…"
    return "No active simulation in this browser session."


def run_backend(model, perf, key, search=None, project=None):
    if not _compute_lock.acquire(blocking=False):
        raise RuntimeError("Another native run is active. Wait for it to finish or cancel it first.")
    process = None
    directory = None
    error_stream = None
    terminal_status = "interrupted"
    try:
        directory = RUNS / uuid.uuid4().hex
        directory.mkdir(parents=True)
        project = project or (search or {}).get('project') or LIBRARY.from_model(model, dict(performance=perf))
        write_json(directory / 'project.json', project)
        kind = 'optimization' if search is not None else 'simulation'
        material_names = ', '.join(m['name'] for m in model['materials'])
        LIBRARY.record(directory, kind=kind, status='running', title=kind.title() + ' — ' + material_names,
                       materials=material_names)
        job = directory / "job.json"
        job.write_text(json.dumps(dict(model=model, performance=perf, search=search), allow_nan=False), encoding="utf-8")
        error_stream = (directory / "backend_stderr.txt").open("w", encoding="utf-8")
        options = dict(stdout=subprocess.PIPE, stderr=error_stream, text=True, encoding="utf-8", errors="replace", bufsize=1)
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True
        if FROZEN:
            backend = ROOT / "S4_Backend" / "S4_Backend.exe"
            if not backend.is_file():
                raise RuntimeError("S4_Backend.exe is missing. Extract and keep the complete executable folder together.")
            command = [str(backend), "--job", str(job)]
        else:
            command = [sys.executable, "-u", str(RESOURCE_ROOT / "backend.py"), "--job", str(job)]
        process = subprocess.Popen(command, **options)
        with _jobs_lock:
            _jobs[key] = dict(cancel=directory / "cancel.flag", pid=process.pid)
        events = queue.Queue()
        def read_output():
            try:
                for line in process.stdout:
                    try:
                        events.put(json.loads(line))
                    except json.JSONDecodeError:
                        events.put(dict(kind="log", text=line.rstrip()))
            finally:
                events.put(None)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        ended = False
        while True:
            try:
                event = events.get(timeout=.3)
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if event is None:
                break
            if event.get("kind") in ("complete", "search_complete", "cancelled", "error"):
                ended = True
                terminal_status = event.get('summary', {}).get('status', event['kind'])
                LIBRARY.record(directory, status=terminal_status, summary=event.get('summary', event.get('info', {})))
            yield event
        process.wait(timeout=5)
        if not ended:
            error_stream.flush()
            detail = (directory / "backend_stderr.txt").read_text(encoding="utf-8")[-4000:]
            raise RuntimeError(f"Backend exited without a result (code {process.returncode}). {detail}")
    finally:
        try:
            if process is not None and process.poll() is None:
                # Generator cancellation/disconnect also requests worker cleanup.
                (directory / "cancel.flag").touch()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        finally:
            # Never leave the GUI permanently locked after a cleanup exception.
            if process is not None and process.stdout:
                process.stdout.close()
            if error_stream:
                error_stream.close()
            with _jobs_lock:
                _jobs.pop(key, None)
            _compute_lock.release()
            if directory is not None and directory.is_dir():
                LIBRARY.record(directory, status=terminal_status)


def progress_text(event):
    if event["kind"] == "started":
        p = event["performance"]
        return (f"Running {event['total']:,} points · {p['effective_workers']} workers × {p['threads']} math threads · "
                f"{p['gpu_workers']} GPU-designated worker · chunk {p['effective_chunk']}")
    done, total = event["done"], event["total"]
    return (f"**{done:,} / {total:,} points** ({100*done/total:.1f}%) · {event['elapsed']:.1f} s\n\n"
            f"CPU matrix products: {event['cpu_gemm_calls']:,} · GPU: {event['gpu_gemm_calls']:,} · GPU failures: {event['gpu_failures']:,}")


def run_sim(request: gr.Request, materials, layers, patterns, files, *values):
    yield None, pd.DataFrame(), None, "Validating inputs…", None
    iterator = None
    try:
        project = LIBRARY.snapshot(make_project(materials, layers, patterns, values), files)
        model = prepare(project["materials"], project["layers"], project["patterns"], LIBRARY.files_for(project), project["settings"])
        perf = performance(project["performance"], len(model["points"]), CPUS)
        iterator = run_backend(model, perf, session_key(request), project=project)
        for event in iterator:
            kind = event["kind"]
            if kind in ("started", "progress"):
                yield gr.skip(), gr.skip(), gr.skip(), progress_text(event), gr.skip()
            elif kind in ("error", "cancelled"):
                yield None, pd.DataFrame(), None, "**" + kind.title() + ":** " + html.escape(event["error"]), None
            elif kind == "complete":
                df = pd.read_csv(event["output"])
                x_name = "wavelength_nm" if model["mode"] == "Wavelength sweep" else "angle_deg"
                fig, axis = plt.subplots(figsize=(8, 5.5))
                for col in ("R", "T", "A"):
                    axis.plot(df[x_name], df[col], label=col, linewidth=2)
                axis.set_xlabel("Wavelength (nm)" if x_name == "wavelength_nm" else "Incidence angle (deg)")
                axis.set_ylabel("Fraction")
                axis.grid(True, alpha=.25)
                axis.legend()
                fig.tight_layout()
                fig.savefig(Path(event["output"]).parent / "spectrum.png", dpi=160)
                plt.close(fig)
                info = event["info"]
                text = (f"**Completed {len(df):,} points in {info['elapsed_seconds']:.2f} s.** "
                        f"CPU products: {info['cpu_gemm_calls']:,}; GPU products: {info['gpu_gemm_calls']:,}; GPU failures: {info['gpu_failures']:,}.")
                if len(df) > 5000:
                    text += " Table shows the first 5,000 points; the CSV and plot contain all points."
                for warning in info["warnings"]:
                    text += "\n\nWarning: " + html.escape(warning)
                yield fig, df.head(5000), event["output"], text, event["diagnostics"]
    except Exception as exc:
        yield None, pd.DataFrame(), None, "**Error:** " + html.escape(str(exc)), None
    finally:
        if iterator is not None:
            iterator.close()


def test_backend(request: gr.Request, *values):
    yield "Checking the selected backend with a tiny patterned simulation…"
    iterator = None
    try:
        from gpu_status import runtime_check_summary
        selected_perf = dict(DEFAULT_PERFORMANCE, **dict(zip(PERF_KEYS, values)))
        p = dict(selected_perf)
        # Force an actual GPU attempt, only for this diagnostic.
        p.update(workers=1, gpu_min_n=1, chunk_size=1, timeout_seconds=60, require_gpu=False)
        settings = dict(zip(SET_KEYS, SET_DEFAULTS))
        settings.update(wl_start_nm=1550, wl_stop_nm=1550)
        model = prepare(records(DEFAULT_MATERIALS, MAT_COLS), records(DEFAULT_LAYERS, LAYER_COLS), records(DEFAULT_PATTERNS, PAT_COLS), [], settings)
        p = performance(p, 1, CPUS)
        iterator = run_backend(model, p, session_key(request))
        for event in iterator:
            if event["kind"] == "complete":
                info = event["info"]
                yield (html.escape(runtime_check_summary(info, selected_perf))+
                       "\n\n```json\n" + json.dumps(info, indent=2) + "\n```")
            elif event["kind"] in ("error", "cancelled"):
                yield html.escape(event["error"])
    except Exception as exc:
        yield "Backend check failed: " + html.escape(str(exc))
    finally:
        if iterator is not None:
            iterator.close()


def save_project(materials, layers, patterns, *values):
    return save_portable_project(materials, layers, patterns, None, *values)


def save_portable_project(materials, layers, patterns, files, *values):
    project = LIBRARY.snapshot(make_project(materials, layers, patterns, values), files)
    directory = RUNS / ("project_" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    path = directory / "s4_project.json"
    write_json(path, project)
    LIBRARY.record(directory, kind="project", title="Saved project")
    return str(path)


def load_project(file):
    if not file:
        raise gr.Error("Choose a project JSON file")
    with open(file, encoding="utf-8-sig") as stream:
        project = LIBRARY.materialize(json.load(stream))
    settings = dict(zip(SET_KEYS, SET_DEFAULTS))
    settings.update({k: v for k, v in project.get("settings", {}).items() if k in SET_KEYS})
    perf = dict(DEFAULT_PERFORMANCE)
    perf.update({k: v for k, v in project.get("performance", {}).items() if k in PERF_KEYS})
    # Legacy projects remain supported; v3 embeds its optical-constant files.
    return (pd.DataFrame(project.get("materials", []), columns=MAT_COLS),
            pd.DataFrame(project.get("layers", []), columns=LAYER_COLS),
            pd.DataFrame(project.get("patterns", []), columns=PAT_COLS),
            *[settings[k] for k in SET_KEYS], *[perf[k] for k in PERF_KEYS])


def build_ui():
    from studio_ui import build_studio_ui
    return build_studio_ui(sys.modules[__name__])


if __name__ == "__main__":
    mp.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    RUNS.mkdir(exist_ok=True)
    build_ui().queue(max_size=8, default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=args.port, inbrowser=not args.no_browser,
        share=False, allowed_paths=[str(RUNS), str(LIBRARY.data)], max_file_size="2gb",
        theme=__import__("studio_ui").theme(), css=__import__("studio_ui").CSS, footer_links=[])
