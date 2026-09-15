"""Constrained GP optimization over the manual S4 design grid.

Only actual S4 observations enter result rankings. JSON checkpoints contain
observations, not executable model objects. The surrogate is refit on resume.
"""
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
import time
import warnings
import zipfile

import numpy as np

from model import integer, number
from data_library import write_json
from peak_optimizer import designs, geometry_error, conditions, spectrum_peaks, refinement_points, write_csv

MODES = ['Exhaustive grid', 'ML assisted', 'Hybrid verified']
ML_KEYS = ['search_mode', 'initial_designs', 'ml_trials', 'candidate_pool', 'random_seed',
           'finalists', 'verification_basis_factor', 'verification_step_divisor',
           'absorption_agreement', 'q_agreement', 'patience']
ML_DEFAULTS = ['Hybrid verified', 24, 60, 1024, 42, 2, 1.5, 2, .001, .05, 0]


def dependencies():
    path = Path(__file__).resolve().parent / 'ml_dependencies'
    if sys.platform == 'win32' and path.is_dir() and str(path) not in sys.path:
        sys.path.insert(0, str(path))
    try:
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import ConstantKernel, Matern
        from scipy.special import ndtr
        from scipy.stats import qmc
        from threadpoolctl import threadpool_limits
        return GaussianProcessRegressor, ConstantKernel, Matern, ndtr, qmc, threadpool_limits
    except ImportError as exc:
        raise RuntimeError('ML dependencies are missing. On Windows run install_ml_dependencies.cmd; on Linux install requirements-linux.txt. Exhaustive grid needs no ML packages.') from exc


def validate_ml(cfg, base):
    for key, default in zip(ML_KEYS, ML_DEFAULTS):
        cfg.setdefault(key, default)
    if cfg['search_mode'] not in MODES:
        raise ValueError('Unknown search mode')
    for key, lo, hi in (('initial_designs', 2, 1000), ('ml_trials', 2, 10000),
                        ('candidate_pool', 32, 10000), ('random_seed', 0, 2147483647),
                        ('finalists', 1, 10), ('verification_step_divisor', 2, 10), ('patience', 0, 1000)):
        cfg[key] = integer(cfg[key], key, lo)
        if cfg[key] > hi:
            raise ValueError(f'{key} must be <= {hi}')
    cfg['verification_basis_factor'] = number(cfg['verification_basis_factor'], 'Verification basis factor')
    if not 1 < cfg['verification_basis_factor'] <= 4:
        raise ValueError('Verification basis factor must be > 1 and <= 4')
    if math.ceil(base['basis']*cfg['verification_basis_factor']) > 4096:
        raise ValueError('Verification Fourier basis would exceed 4096')
    for key in ('absorption_agreement', 'q_agreement'):
        cfg[key] = number(cfg[key], key, minimum=0)
        if cfg[key] > 1:
            raise ValueError(f'{key} must be <= 1')
    if cfg['initial_designs'] > cfg['ml_trials']:
        raise ValueError('Initial designs must not exceed the ML trial budget')
    if cfg['ml_trials'] > cfg['design_budget']:
        raise ValueError('ML trial budget must not exceed maximum design evaluations')
    return cfg


def model_for(base, cfg, values):
    dimensions = [dict(d, values=[v]) for d, v in zip(cfg['dimensions'], values)]
    return next(designs(base, dict(cfg, dimensions=dimensions)))


def value_key(values):
    return json.dumps(values, separators=(',', ':'), allow_nan=False)


def encode(values, dimensions):
    """One-hot categories have no artificial ordinal relationship."""
    out = []
    for value, d in zip(values, dimensions):
        choices = d['values']
        if len(choices) == 1:
            continue
        if d['parameter'].endswith('_material'):
            out.extend(float(value == item) for item in choices)
        else:
            out.append((value-choices[0])/(choices[-1]-choices[0]))
    return out or [0.]


def fingerprint(base, cfg):
    # Numerical/physical settings must match; budgets, mode and hardware may change.
    checked = dict(base=base, dimensions=cfg['dimensions'], **{k: cfg[k] for k in
        ('ratio_limit', 'min_bridge_um', 'separate_circles', 'absorption_target', 'prominence', 'refinement_rounds')})
    return hashlib.sha256(json.dumps(checked, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def peak_targets(peaks, target):
    resolved = [p for p in peaks if p.get('Q_estimate') is not None and p['Q_estimate'] > 0]
    feasible = [p for p in resolved if p['absorption'] > target]
    selected = max(feasible, key=lambda p: p['Q_estimate']) if feasible else max(resolved, key=lambda p: p['absorption'], default=None)
    return dict(absorption=max(p['absorption'] for p in peaks),
                log_q=math.log(selected['Q_estimate']) if selected else None,
                q_absorption=selected['absorption'] if selected else None,
                q_wavelength=selected['wavelength_nm'] if selected else None,
                feasible_q=max((p['Q_estimate'] for p in feasible), default=None))


def fit_predict(x, y, candidates, noise):
    GP, Constant, Matern, _, _, limits = dependencies()
    y = np.asarray(y, dtype=float)
    center, scale = float(y.mean()), max(float(y.std()), noise*10, 1e-6)
    kernel = Constant(1., (.01, 100.))*Matern(length_scale=.4, length_scale_bounds=(.03, 5.), nu=2.5)
    gp = GP(kernel=kernel, alpha=max((noise/scale)**2, 1e-8), normalize_y=False, n_restarts_optimizer=0)
    with limits(limits=1), warnings.catch_warnings(record=True) as caught:
        gp.fit(np.asarray(x), (y-center)/scale)
        mean, std = gp.predict(np.asarray(candidates), return_std=True)
    return mean*scale+center, np.maximum(std*scale, noise), [str(w.message) for w in caught]


def expected_improvement(mean, std, best):
    ndtr = dependencies()[3]
    z = (mean-best)/std
    return np.maximum((mean-best)*ndtr(z)+std*np.exp(-z*z/2)/math.sqrt(2*math.pi), 0.)


def acquisition(observations, candidates, cfg):
    """A separate absorption constraint stays paired with the Q-producing peak."""
    # Limit exact-GP cost; retain leaders and a deterministic spread of older data.
    iteration = cfg.get('_acquisition_iteration',len(observations))
    if len(observations) > 256:
        leaders = sorted(range(len(observations)), key=lambda i: observations[i]['targets']['absorption'], reverse=True)[:32]
        leaders += sorted(range(len(observations)), key=lambda i: observations[i]['targets']['feasible_q'] or 0, reverse=True)[:32]
        chosen = list(dict.fromkeys(leaders+np.linspace(0, len(observations)-1, 256, dtype=int).tolist()))[:256]
        observations = [observations[i] for i in chosen]
    x = [encode(o['values'], cfg['dimensions']) for o in observations]
    c = [encode(v, cfg['dimensions']) for v in candidates]
    ys = [o['targets']['absorption'] for o in observations]
    ma, sa, alerts = fit_predict(x, ys, c, 1e-4)
    probability = dependencies()[3]((ma-cfg['absorption_target'])/sa)
    score = expected_improvement(ma, sa, max(ys))
    phase = 'absorption improvement'
    mq = sq = paired_probability = None
    qobs = [o for o in observations if o['targets']['log_q'] is not None]
    incumbent = max((o['targets']['feasible_q'] or 0 for o in observations), default=0)
    if incumbent and len(qobs) >= 3 and iteration % 4 != 0:
        qx = [encode(o['values'], cfg['dimensions']) for o in qobs]
        mq, sq, w = fit_predict(qx, [o['targets']['log_q'] for o in qobs], c, .02)
        alerts += w
        qa, qsa, w = fit_predict(qx, [o['targets']['q_absorption'] for o in qobs], c, 1e-4)
        alerts += w
        paired_probability = dependencies()[3]((qa-cfg['absorption_target'])/qsa)
        score = expected_improvement(mq, sq, math.log(incumbent))*paired_probability
        phase = 'Q improvement subject to paired-peak absorption'
    if iteration % 7 == 0:
        score, phase = sa, 'uncertainty exploration'
    index = int(np.argmax(score))
    prediction = dict(selection_reason=phase, predicted_absorption=float(ma[index]), absorption_std=float(sa[index]),
                      probability_above_target=float(probability[index]),
                      predicted_log_Q=float(mq[index]) if mq is not None else None,
                      log_Q_std=float(sq[index]) if sq is not None else None,
                      paired_peak_probability=float(paired_probability[index]) if paired_probability is not None else None,
                      model_warnings='; '.join(dict.fromkeys(alerts)))
    return index, prediction


def candidate_pool(base, cfg, observed, screened):
    dimensions = cfg['dimensions']
    size = cfg['candidate_pool']
    seen = {value_key(o['values']) for o in observed if o['phase'] != 'verification'}
    if cfg['design_count'] <= size*4:
        raw = itertools.product(*(d['values'] for d in dimensions))
    else:
        sampler = dependencies()[4].LatinHypercube(d=max(len(dimensions), 1), seed=cfg['random_seed']+len(observed))
        raw = [[d['values'][min(int(v*len(d['values'])), len(d['values'])-1)] for d, v in zip(dimensions, row)] for row in sampler.random(size*2)]
    pool, used = [], set()
    for item in raw:
        values = list(item)
        key = value_key(values)
        if key in seen or key in used:
            continue
        used.add(key)
        if geometry_error(model_for(base, cfg, values), cfg):
            screened.add(key)
            continue
        pool.append(values)
    if len(pool) > size:
        rng = np.random.default_rng(cfg['random_seed']+len(observed))
        pool = [pool[int(i)] for i in rng.choice(len(pool), size, replace=False)]
    return pool


def pick_candidate(pool, observed, cfg):
    success = [o for o in observed if o['status'] == 'evaluated' and o['phase'] != 'verification']
    if len(success) < cfg['initial_designs']:
        if not success:
            index = int(np.random.default_rng(cfg['random_seed']).integers(len(pool)))
        else:
            x = np.asarray([encode(o['values'], cfg['dimensions']) for o in success])
            c = np.asarray([encode(v, cfg['dimensions']) for v in pool])
            distance = ((c[:, None, :]-x[None, :, :])**2).sum(axis=2).min(axis=1)
            index = int(np.argmax(distance))
        return pool[index], dict(selection_reason='space-filling initialization')
    index, prediction = acquisition(success, pool, cfg)
    return pool[index], prediction


def leaders(observations, count):
    by_value = {}
    for o in observations:
        if o['status'] == 'evaluated':
            by_value[value_key(o['values'])] = o
    items = list(by_value.values())
    by_a = sorted(items, key=lambda o: o['targets']['absorption'], reverse=True)
    by_q = sorted((o for o in items if o['targets']['feasible_q']), key=lambda o: o['targets']['feasible_q'], reverse=True)
    out, used = [], set()
    for q, a in itertools.zip_longest(by_q, by_a):
        for item in (q, a):
            if item is not None and value_key(item['values']) not in used:
                out.append(item)
                used.add(value_key(item['values']))
                if len(out) == count:
                    return out
    return out


def local_grid(seeds, cfg):
    """Full Cartesian half-step neighborhood, with seed materials held fixed."""
    sets, total = [], 0
    for seed in seeds:
        values = []
        for value, d in zip(seed['values'], cfg['dimensions']):
            domain = d['values']
            if len(domain) == 1 or d['parameter'].endswith('_material'):
                options = [value]
            else:
                step = float(np.median(np.diff(domain)))
                options = sorted(set(max(domain[0], min(domain[-1], value+s*step)) for s in (-.5, 0, .5)))
            values.append(options)
        total += math.prod(map(len, values))
        if total > 100000:
            raise ValueError('Local verification grid exceeds 100,000 combinations. Fix more parameters or reduce finalists.')
        sets.append(values)
    unique = {}
    for values in sets:
        for item in itertools.product(*values):
            unique[value_key(list(item))] = list(item)
    return list(unique.values())


def load_history(data, base, cfg):
    if not data:
        return []
    if data.get('format') != 's4-gp-history-v1' or data.get('fingerprint') != fingerprint(base, cfg):
        raise ValueError('Resume history does not match this structure, materials, bounds, wavelength grid, detection, or fabrication settings.')
    observations = data.get('observations')
    if not isinstance(observations, list) or len(observations) > 20000:
        raise ValueError('Invalid or oversized resume history')
    ids = set()
    for o in observations:
        if o.get('status') not in ('evaluated', 'failed') or o.get('phase') not in ('exploration', 'local grid', 'verification'):
            raise ValueError('Invalid history observation')
        if not isinstance(o.get('id'), int) or o['id'] < 1 or o['id'] in ids:
            raise ValueError('Duplicate or invalid history IDs')
        ids.add(o['id'])
        basis = o.get('basis')
        if not isinstance(basis, int) or not 1 <= basis <= 4096:
            raise ValueError('Invalid Fourier basis in resume history')
        if o['phase'] != 'verification' and basis != base['basis']:
            raise ValueError('Resume observation uses a different Fourier basis')
        if o['phase'] == 'verification':
            settings = o.get('verification_settings')
            if (not isinstance(settings, list) or len(settings) != 2
                    or not isinstance(settings[0], (int, float)) or not 1 < settings[0] <= 4
                    or not isinstance(settings[1], int) or not 2 <= settings[1] <= 10
                    or basis != math.ceil(base['basis']*settings[0])):
                raise ValueError('Invalid verification settings in resume history')


        values = o.get('values', [])
        if len(values) != len(cfg['dimensions']):
            raise ValueError('History parameter count mismatch')
        for value, d in zip(values, cfg['dimensions']):
            if d['parameter'].endswith('_material'):
                valid = value in d['values']
            else:
                valid = isinstance(value, (float, int)) and math.isfinite(value) and d['values'][0] <= value <= d['values'][-1]
            if not valid:
                raise ValueError('History contains an out-of-bounds parameter')
        model = model_for(base, cfg, values)
        if geometry_error(model, cfg):
            raise ValueError('History contains a fabrication-infeasible design')
        if o['status'] == 'evaluated':
            rows = o.get('rows')
            if not rows or len(rows) < 3 or len({r[1] for r in rows}) != len(rows) or any(len(r) != 6 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in r) or not -1e-8 <= r[5] <= 1 for r in rows):
                raise ValueError('History has missing or invalid spectral observations')
            lo, hi = base['points'][0][1], base['points'][-1][1]
            if any(not lo <= r[1] <= hi or r[2] != base['points'][0][2] for r in rows):
                raise ValueError('History wavelength or incidence angle mismatch')
            # Recompute objectives rather than trusting saved claimed metrics.
            peaks, _ = spectrum_peaks(rows, cfg['prominence'])
            o['peaks'], o['targets'] = peaks, peak_targets(peaks, cfg['absorption_target'])
    return copy.deepcopy(observations)


def execute_ml_search(base, perf, cfg, directory, executor, emit, cancelled):
    from backend import Cancelled
    validate_ml(cfg, base)
    dependencies()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    observations = load_history(cfg.get('resume_history'), base, cfg)
    resumed = len(observations)
    started, spent = time.monotonic(), 0
    screened, verification_plan, local_plan = set(), [], []
    previous_plan = (cfg.get('resume_history') or {}).get('local_plan', [])
    planned_after_exploration = (cfg.get('resume_history') or {}).get('planned_after_exploration', -1)
    status, reason = 'complete', ''
    local_complete, verification_complete = False, False
    warning_messages = []
    search_options = {k: v for k, v in cfg.items() if k != 'resume_history'}
    (directory/'search_config.json').write_text(json.dumps(dict(options=search_options, base_model=base, performance=perf), indent=2, allow_nan=False), encoding='utf-8')

    def checkpoint():
        data = dict(format='s4-gp-history-v1', fingerprint=fingerprint(base, cfg), observations=observations,
                    options=search_options, base_model=base, seed=cfg['random_seed'],
                    local_plan=local_plan, planned_after_exploration=planned_after_exploration)
        write_json(directory/'optimization_history.json',data)

    def guard():
        if cancelled():
            raise Cancelled('Search cancelled by user; completed observations saved')
        remaining = perf['timeout_seconds']-(time.monotonic()-started)
        if remaining < 1:
            raise TimeoutError('Whole-search timeout reached; resume from optimization_history.json')
        return remaining

    def notify(text):
        emit(dict(kind='search_progress', design=len(observations)+1, total=cfg['design_budget'], points=spent, text=text))

    def evaluate(values, phase, prediction=None, reference=None):
        nonlocal spent
        guard()
        model = model_for(base, cfg, values)
        if phase != 'verification' and sum(o['phase'] != 'verification' for o in observations) >= cfg['design_budget']:
            raise TimeoutError('Maximum cumulative design-evaluation budget reached; increase it to continue')
        if geometry_error(model, cfg):
            raise ValueError('Candidate violates fabrication bounds')

        if phase == 'verification':
            model['basis'] = math.ceil(base['basis']*cfg['verification_basis_factor'])
            initial = sorted(p[1] for p in base['points'])
            count = math.ceil((initial[-1]-initial[0])/(min(np.diff(initial))/cfg['verification_step_divisor']))+1
            if count > cfg['point_budget']-spent:
                raise TimeoutError('Insufficient spectral point budget for finalist verification')
            wavelengths = np.linspace(initial[0], initial[-1], count).tolist()
        else:
            wavelengths = [p[1] for p in base['points']]
        trial_id = max((o['id'] for o in observations), default=0)+1
        notify(f'{phase}: evaluating design {trial_id}; '+str((prediction or {}).get('selection_reason', 'S4 measurement')))
        combined = {}
        try:
            for round_id in range(cfg['refinement_rounds']+1):
                remaining = guard()
                if not wavelengths:
                    break
                if spent+len(wavelengths) > cfg['point_budget']:
                    raise TimeoutError('Spectral point budget reached; completed observations saved')
                evaluation = dict(model, points=[[i, wl, base['points'][0][2]] for i, wl in enumerate(wavelengths)])
                def progress(event):
                    if event['kind'] in ('started', 'progress'):
                        notify(f'{phase} design {trial_id}, refinement {round_id}/{cfg["refinement_rounds"]}: {event.get("done", 0)}/{len(wavelengths)} points')
                rows, info = executor(evaluation, dict(perf, timeout_seconds=max(1, int(remaining))), progress, cancelled)
                spent += len(rows)
                if any(not all(math.isfinite(float(v)) for v in r) or r[5] < -1e-8 or r[5] > 1 for r in rows):
                    raise ValueError('Nonphysical absorption; check material loss and Fourier convergence')
                combined.update({r[1]: r for r in rows})
                (directory/f'design_{trial_id}_round_{round_id}_diagnostics.json').write_text(json.dumps(info, indent=2, allow_nan=False), encoding='utf-8')
                wavelengths = refinement_points(list(combined.values()), cfg['prominence'])
            rows = sorted(combined.values(), key=lambda r: r[1])
            peaks, _ = spectrum_peaks(rows, cfg['prominence'])
            record = dict(id=trial_id, values=values, phase=phase, status='evaluated', basis=model['basis'], rows=rows,
                          peaks=peaks, targets=peak_targets(peaks, cfg['absorption_target']), prediction=prediction or {})
            if reference is not None:
                adiff = abs(record['targets']['absorption']-reference['targets']['absorption'])
                q0, q1 = reference['targets']['feasible_q'], record['targets']['feasible_q']
                qdiff = abs(q1-q0)/q0 if q0 and q1 else None
                wavelength_shift = abs(record['targets']['q_wavelength']-reference['targets']['q_wavelength']) if q0 and q1 else None
                linewidth = reference['targets']['q_wavelength']/q0 if q0 else 0
                agrees = adiff <= cfg['absorption_agreement'] and qdiff is not None and qdiff <= cfg['q_agreement'] and wavelength_shift <= max(2*linewidth, 1e-6)
                record['verification'] = dict(reference_design_id=reference['id'], absorption_difference=adiff,
                    relative_Q_difference=qdiff, q_peak_shift_nm=wavelength_shift,
                    status='two-resolution agreement' if agrees else 'needs further convergence review')
            observations.append(record)
        except (Cancelled, TimeoutError):
            raise
        except Exception as exc:
            observations.append(dict(id=trial_id, values=values, phase=phase, basis=model['basis'], status='failed',
                                     reason=str(exc), prediction=prediction or {}))
        if phase == 'verification':
            observations[-1]['verification_settings'] = [cfg['verification_basis_factor'], cfg['verification_step_divisor']]
        checkpoint()
        if len(observations) >= 3 and all(o['status'] == 'failed' for o in observations[-3:]):
            raise RuntimeError('Three consecutive S4 evaluations failed; review the exported reasons')

    try:
        checkpoint()
        stalled, previous = 0, (0., 0.)
        while sum(o['phase'] == 'exploration' for o in observations) < cfg['ml_trials']:
            guard()
            notify('Selecting the next bounded candidate from the learned model')
            pool = candidate_pool(base, cfg, observations, screened)
            if not pool:
                warning_messages.append('No unused feasible candidates in the candidate pool; this is not proof that a large design space is exhausted.')
                break
            values, prediction = pick_candidate(pool, observations, cfg)
            evaluate(values, 'exploration', prediction)
            successful = [o for o in observations if o['status'] == 'evaluated']
            best = (max((o['targets']['absorption'] for o in successful), default=0.), max((o['targets']['feasible_q'] or 0 for o in successful), default=0.))
            changed = best[0]-previous[0] > cfg['tie_tolerance'] or best[1] > previous[1]*1.001
            stalled = 0 if changed else stalled+1
            previous = best
            if cfg['patience'] and len(successful) >= cfg['initial_designs'] and stalled >= cfg['patience']:
                warning_messages.append('Stopped after the requested number of trials without a measured improvement; not a global-convergence certificate.')
                break
        if cfg['search_mode'] == 'Hybrid verified':
            guard()
            seeds = leaders([o for o in observations if o['phase'] != 'verification'], cfg['finalists'])
            exploration_count = sum(o['phase'] == 'exploration' for o in observations)
            if previous_plan and planned_after_exploration == exploration_count:
                # Finish exactly the saved local Cartesian grid after interruption.
                for values in previous_plan:
                    if len(values) != len(cfg['dimensions']):
                        raise ValueError('Invalid local grid in resume history')
                    for value, d in zip(values, cfg['dimensions']):
                        valid = value in d['values'] if d['parameter'].endswith('_material') else isinstance(value, (int, float)) and math.isfinite(value) and d['values'][0] <= value <= d['values'][-1]
                        if not valid:
                            raise ValueError('Out-of-bounds saved local grid')
                local_plan = previous_plan
            else:
                local_plan = local_grid(seeds, cfg)
            planned_after_exploration = exploration_count
            checkpoint()
            seen = {value_key(o['values']) for o in observations if o['phase'] != 'verification'}
            pending = []
            for values in local_plan:
                if geometry_error(model_for(base, cfg, values), cfg):
                    screened.add(value_key(values))
                elif value_key(values) not in seen:
                    pending.append(values)
            used = sum(o['phase'] != 'verification' for o in observations)
            if used+len(pending) > cfg['design_budget']:
                warning_messages.append(f'Local grid requires {len(pending)} new designs but only {cfg["design_budget"]-used} remain in the design budget. Local grid was not truncated. Increase budget and resume.')
                status = 'partial'
            else:
                for values in pending:
                    evaluate(values, 'local grid')
                completed_keys = {value_key(o['values']) for o in observations if o['status'] == 'evaluated'}
                local_complete = bool(local_plan) and all(value_key(v) in completed_keys or
                    bool(geometry_error(model_for(base, cfg, v), cfg)) for v in local_plan)
            verification_plan = leaders([o for o in observations if o['phase'] != 'verification'], cfg['finalists'])
            for seed in verification_plan:
                # A resumed run reuses a previous verification only at identical settings.
                same = [o for o in observations if o['phase'] == 'verification' and o['status'] == 'evaluated'
                        and value_key(o['values']) == value_key(seed['values']) and o.get('verification_settings') ==
                        [cfg['verification_basis_factor'], cfg['verification_step_divisor']]]
                if not same:
                    evaluate(seed['values'], 'verification', reference=seed)
                    observations[-1]['verification_settings'] = [cfg['verification_basis_factor'], cfg['verification_step_divisor']]
                    checkpoint()
            verification_complete = bool(verification_plan) and all(any(o['status'] == 'evaluated' and o['phase'] == 'verification'
                and o.get('verification_settings') == [cfg['verification_basis_factor'], cfg['verification_step_divisor']]
                and value_key(o['values']) == value_key(seed['values']) for o in observations) for seed in verification_plan)
    except Cancelled as exc:
        status, reason = 'cancelled', str(exc)
    except Exception as exc:
        status, reason = 'partial', str(exc)
    checkpoint()
    # Reassess agreement using the current tolerances, including reused checks.
    by_id = {o['id']: o for o in observations}
    for o in observations:
        verification = o.get('verification')
        if verification:
            reference = by_id.get(verification['reference_design_id'])
            q0 = reference['targets']['feasible_q'] if reference else None
            linewidth = reference['targets']['q_wavelength']/q0 if q0 else 0
            qdiff, shift = verification.get('relative_Q_difference'), verification.get('q_peak_shift_nm')
            agrees = verification['absorption_difference'] <= cfg['absorption_agreement'] and qdiff is not None and qdiff <= cfg['q_agreement'] and shift is not None and shift <= max(2*linewidth, 1e-6)
            verification['status'] = 'two-resolution agreement' if agrees else 'needs further convergence review'
    checkpoint()
    failed = sum(o['status'] == 'failed' for o in observations)
    if failed and status == 'complete':
        status = 'partial'
        warning_messages.append('Some simulations failed; inspect failure reasons in optimization history.')
    reason = '\n'.join([reason]+warning_messages).strip()
    # Successful higher-resolution observations replace coarse observations of
    # that geometry for final rankings, even if absorption or Q got worse.
    authoritative = {}
    for o in observations:
        if o['status'] == 'evaluated':
            key = value_key(o['values'])
            old = authoritative.get(key)
            if old is None or o['phase'] == 'verification' or old['phase'] != 'verification':
                authoritative[key] = o
    results, peaks_out, history_rows = [], [], []
    best = max((o['targets']['absorption'] for o in authoritative.values()), default=None)
    best_rows, best_id = [], None
    with (directory/'design_models.jsonl').open('w', encoding='utf-8') as models:
        for o in observations:
            model = model_for(base, cfg, o['values'])
            model['basis'] = o['basis']
            if o.get('rows'):
                model['points'] = [[i, r[1], r[2]] for i, r in enumerate(o['rows'])]
            models.write(json.dumps(dict(design_id=o['id'], model=model), allow_nan=False)+'\n')
            row = dict(design_id=o['id'], status=o['status'], phase=o['phase'], **conditions(model), **o.get('prediction', {}))
            row['verification_status'] = o.get('verification', {}).get('status', 'not checked at two resolutions')
            row.update(o.get('verification', {}))
            # Do not let verification.status overwrite the simulation status.
            row['status'] = o['status']
            if o['status'] == 'failed':
                row['reason'] = o.get('reason', '')
                history_rows.append(row)
                continue
            top = dict(o['peaks'][0]); top.pop('index', None)
            row.update(top)
            row['above_target'] = row['absorption'] > cfg['absorption_target']
            row['matches_best'] = best is not None and abs(best-row['absorption']) <= cfg['tie_tolerance']+1e-15
            current = authoritative.get(value_key(o['values'])) is o
            row['used_in_final_ranking'] = current
            history_rows.append(row)
            if current:
                results.append(row)
                for peak in o['peaks']:
                    p = dict(row, **peak); p.pop('index', None)
                    p['above_target'] = p['absorption'] > cfg['absorption_target']
                    p['matches_best'] = abs(best-p['absorption']) <= cfg['tie_tolerance']+1e-15
                    peaks_out.append(p)
                if row['absorption'] == best and best_id is None:
                    best_id, best_rows = o['id'], o['rows']
            write_csv(directory/f'design_{o["id"]}_spectrum.csv', [dict(zip(['wavelength_nm', 'angle_deg', 'R', 'T', 'A'], r[1:])) for r in o['rows']])
    results.sort(key=lambda r: -r['absorption'])
    feasible = sorted((p for p in peaks_out if p['above_target']), key=lambda p: (p['Q_estimate'] is not None, p['Q_estimate'] or 0., p['absorption']), reverse=True)
    matches = [r for r in results if r['matches_best']]
    failed_rows = [r for r in history_rows if r['status'] == 'failed']
    summary = dict(status=status, reason=reason, mode=cfg['search_mode'], grid_designs=cfg['design_count'], evaluated=len(results),
                   best_design_verified=bool(results and results[0]['phase'] == 'verification'),
                   best_Q_design_verified=bool(feasible and feasible[0]['phase'] == 'verification'),
                   verification_scope='Only the selected finalists are rerun at higher resolution. Other reported designs may remain unchecked; inspect verification_status.',

                   excluded=len(screened), failed=failed, spectral_points=spent, elapsed_seconds=time.monotonic()-started,
                   resumed_observations=resumed, total_observations=len(observations), best_absorption=best,
                   best_design_id=best_id, matching_designs=len(matches), above_target_designs=len({p['design_id'] for p in feasible}),
                   highest_Q_estimate=next((p['Q_estimate'] for p in feasible if p['Q_estimate'] is not None), None),
                   local_grid_complete=bool(local_complete), local_grid_points=len(local_plan),
                   finalist_checks_complete=verification_complete,
                   finalists_agree=sum(o.get('verification', {}).get('status') == 'two-resolution agreement' for o in authoritative.values()),
                   scope='ML proposes candidates; rankings contain S4 observations only. Only evaluated designs are reported. Hybrid local coverage and two-resolution checks are reported separately; neither certifies a continuous global maximum. Q remains a spectral estimate.')
    for name, records in (('design_results.csv', results+failed_rows), ('all_peaks.csv', peaks_out), ('matching_best.csv', matches),
                          ('above_target_by_Q.csv', feasible), ('optimization_history.csv', history_rows)):
        write_csv(directory/name, records)
    write_csv(directory/'best_spectrum.csv', [dict(zip(['wavelength_nm', 'angle_deg', 'R', 'T', 'A'], r[1:])) for r in best_rows])
    (directory/'search_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    archive = directory/'peak_search_results.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(directory.iterdir()):
            if path.suffix in ('.csv', '.json', '.jsonl'):
                bundle.write(path, path.name)
    return dict(kind='search_complete', summary=summary, directory=str(directory), archive=str(archive))
