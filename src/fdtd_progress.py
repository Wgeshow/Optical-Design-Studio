"""Measured Meep timing estimates; no solver imports or numerical preflight."""
import hashlib
import json
import math
import os
import platform
from collections import deque
from pathlib import Path

SCHEMA = 1


def finite(value):
    try:
        return float(value) if math.isfinite(float(value)) else None
    except (TypeError, ValueError, OverflowError):
        return None


def duration(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f'{seconds}s'
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02}m' if hours else f'{minutes}m {seconds:02}s'


def timing_key(project, options, runtime):
    # Exact conservative match; do not extrapolate between different devices.
    payload = {key: project.get(key) for key in ('materials', 'layers', 'patterns', 'settings')}
    from app_version import APP_VERSION
    payload.update(options=options, runtime=runtime, schema=SCHEMA,
                   application_version=APP_VERSION, machine=platform.node(),
                   threads={key: os.environ.get(key) for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


class PhaseEstimate:
    def __init__(self):
        self.phase = None
        self.samples = deque(maxlen=12)
        self.last_received = None
        self.rate = None
        self.remaining = None
        self.fraction = None
        self.budget = None
        self.phase_elapsed = 0.
        self.first_elapsed = 0.
        self.first_time = 0.

    def update(self, event, now):
        phase = event.get('phase')
        if phase != self.phase:
            self.__init__()
            self.phase = phase
        t, budget, wall = (finite(event.get(key)) for key in
                           ('time', 'phase_budget_time', 'phase_elapsed_seconds'))
        if t is None or budget is None or wall is None or budget <= 0 or t < 0 or wall < 0:
            self.rate = self.remaining = self.fraction = None
            return
        if self.samples and (wall <= self.samples[-1][0] or t <= self.samples[-1][1]):
            self.samples.clear()
            self.rate = self.remaining = None
        if not self.samples:
            self.first_elapsed, self.first_time = wall, t
        self.samples.append((wall, t))
        self.last_received, self.budget, self.phase_elapsed = now, budget, wall
        self.fraction = min(1., t/budget)
        if len(self.samples) >= 3:
            dw, dt = wall-self.samples[0][0], t-self.samples[0][1]
            if dw >= 2 and dt > 0:
                self.rate = dt/dw
                self.remaining = max(0., budget-t)/self.rate

    def text(self, now):
        if self.last_received is not None and now-self.last_received > 10:
            return 'Waiting for solver update; estimate unavailable.'
        if self.remaining is None:
            return 'Estimating after time stepping begins…'
        return f'Estimated time to phase limit ~{duration(self.remaining)}; decay may finish sooner.'

    def budget_seconds(self):
        if self.rate is None or self.budget is None:
            return None
        initialization = max(0., self.first_elapsed-self.first_time/self.rate)
        return initialization+self.budget/self.rate


def cached_estimate(runs, key, limit=100, cancelled=lambda: False):
    """Read bounded recent timing receipts; call only on a background thread."""
    runs = Path(runs)
    if not runs.is_dir():
        return None
    candidates = []
    for directory in runs.iterdir():
        if cancelled():
            return None
        if directory.name.startswith('fdtd_') and directory.is_dir() and not directory.is_symlink():
            try:
                candidates.append((directory.stat().st_mtime, directory))
            except OSError:
                continue
    for _, directory in sorted(candidates, reverse=True)[:limit]:
        if cancelled():
            return None
        try:
            receipt = json.loads((directory/'runtime_timing.json').read_text(encoding='utf-8'))
            seconds = finite(receipt.get('estimated_budget_seconds'))
            if receipt.get('schema') == SCHEMA and receipt.get('input_key') == key and seconds is not None and seconds > 0:
                return dict(seconds=seconds, run=directory.name)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return None
