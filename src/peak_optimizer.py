"""Exact parameter sweeps, saved-result analysis, and optimizer helpers."""
import copy
import csv
import itertools
import json
import math
import time
import zipfile
from pathlib import Path
import numpy as np
from model import integer, number, sweep_range, MAX_SWEEP_POINTS
from optical_objective import response_name, response_rows

BOUND_COLS = ['Parameter', 'Target', 'Min', 'Max', 'Step', 'Choices']
SEARCH_KEYS = ['ratio_limit', 'min_bridge_um', 'separate_circles', 'absorption_target',
               'tie_tolerance', 'prominence', 'refinement_rounds', 'design_budget', 'point_budget']
SEARCH_DEFAULTS = [.6, 0., True, .99, .0001, .00001, 3, 500, 200000]
MAX_DESIGN_BOUND_VALUES = 10_000


def grid_values(lo, hi, step, max_values=MAX_DESIGN_BOUND_VALUES):
    lo, hi = number(lo, 'Minimum'), number(hi, 'Maximum')
    if hi < lo:
        raise ValueError('Maximum must be >= minimum')
    if lo == hi:
        return [lo]
    start, spacing, count = sweep_range(lo, hi, step, 'Design bound', limit=math.inf)
    last = start + (count-1)*spacing
    includes_endpoint = math.isclose(last, hi, rel_tol=1e-12, abs_tol=1e-14)
    size = count + (not includes_endpoint)
    if size > max_values:
        raise ValueError(f'Design bound has {size:,} values, exceeding the budget or safety limit of {max_values:,}; narrow bounds or increase the step.')
    values = [start + i*spacing for i in range(count)]
    if includes_endpoint:
        values[-1] = hi
    else:
        values.append(hi)
    return values


def parse_search(model, bounds, options):
    exhaustive = options.get('search_mode', 'Exhaustive grid') == 'Exhaustive grid'
    if not exhaustive and (model['mode'] != 'Wavelength sweep' or len(model['points']) < 3):
        raise ValueError('Choose Wavelength sweep with at least three spectral points')
    cfg = dict(zip(SEARCH_KEYS, SEARCH_DEFAULTS))
    cfg.update(options)
    # Old saved grid setups contain optimizer controls. They must never change
    # the requested sampling, reject geometry, or qualify the recorded data.
    if exhaustive:
        cfg.update(ratio_limit=.6, min_bridge_um=0., separate_circles=False,
                   absorption_target=.99, tie_tolerance=.0001, prominence=.00001,
                   refinement_rounds=0)
    response_name(cfg)
    for key in ('ratio_limit', 'min_bridge_um', 'absorption_target', 'tie_tolerance', 'prominence'):
        cfg[key] = number(cfg[key], key, minimum=0)
    if not 0 < cfg['ratio_limit'] <= .6:
        raise ValueError('r/a limit must be > 0 and <= 0.6; acceptance is strictly below the limit')
    if not (0 if 'response' in cfg else .99) <= cfg['absorption_target'] < 1:
        raise ValueError('Response threshold must be >= 0 and < 1; acceptance is strictly above it' if 'response' in cfg else
                         'Absorption target must be >= 0.99 and < 1; acceptance is strictly above it')
    if cfg['tie_tolerance'] > 1 or cfg['prominence'] > 1:
        raise ValueError('Tie tolerance and prominence must be fractions between 0 and 1')
    if not isinstance(cfg['separate_circles'], bool):
        raise ValueError('Separate circles must be true or false')
    for key, low, high in (('refinement_rounds', 0, 6), ('design_budget', 1, 10000), ('point_budget', 1 if exhaustive else 3, MAX_SWEEP_POINTS)):
        cfg[key] = integer(cfg[key], key, low)
        if cfg[key] > high:
            raise ValueError(f'{key} must be <= {high}')
    dims, touched = [], set()
    mats = {m['name'] for m in model['materials']}
    layers = {v['name']: i for i, v in enumerate(model['layers'])}
    fields = dict(radius='sx', r_over_a='sx', size_x='sx', size_y='sy', center_x='cx', center_y='cy', rotation='angle', pattern_material='material')
    for row in bounds:
        p = str(row.get('Parameter') or '').strip()
        if not p or p.lower() == 'nan':
            continue
        target = str(row.get('Target') or '').strip()
        categorical = p in ('layer_material', 'pattern_material')
        index, field = None, None
        if p in ('lattice_square', 'lattice_x', 'lattice_y'):
            keys = ['ax', 'ay'] if p == 'lattice_square' else ['ax' if p == 'lattice_x' else 'ay']
        elif p in ('thickness', 'layer_material'):
            if target not in layers:
                raise ValueError(f'Unknown layer: {target}')
            index = layers[target]
            if p == 'thickness' and index in (0, len(layers)-1):
                raise ValueError('Cannot vary half-space thickness')
            field = 'material' if categorical else 'thickness'
            keys = [f'layer.{index}.{field}']
        elif p in fields:
            index = integer(target, 'Pattern target (1-based)', 1)-1
            if index >= len(model['patterns']):
                raise ValueError('Pattern target exceeds the number of patterns')
            if p in ('radius', 'r_over_a') and model['patterns'][index]['shape'] != 'circle':
                raise ValueError('Radius and r_over_a require a circle')
            field = fields[p]
            keys = [f'pattern.{index}.{field}']
        else:
            raise ValueError(f'Unknown parameter: {p}')
        linked = []
        if row.get('linked_targets'):
            if p not in fields:
                raise ValueError('Linked targets require a pattern parameter')
            linked = [integer(v, 'Linked pattern target', 1)-1 for v in row['linked_targets']]
            if len(set([index] + linked)) != len(linked)+1:
                raise ValueError('Linked pattern targets must be distinct')
            for other in linked:
                if other >= len(model['patterns']) or model['patterns'][other]['shape'] != model['patterns'][index]['shape']:
                    raise ValueError('Linked holes must exist and have the same shape')
                keys.append(f'pattern.{other}.{field}')
        if touched.intersection(keys):
            raise ValueError(f'Duplicate or conflicting bound: {p} {target}')
        touched.update(keys)
        if categorical:
            values = list(dict.fromkeys(v.strip() for v in str(row.get('Choices') or '').split(';') if v.strip()))
            if not values or any(v not in mats for v in values):
                raise ValueError('Material choices must be semicolon-separated material library names')
        else:
            # Exhaustive searches must reject over-budget dimensions before
            # allocating them. ML may search a much larger Cartesian product,
            # while each materialized domain retains the design-bound cap.
            maximum = MAX_DESIGN_BOUND_VALUES
            if cfg.get('search_mode', 'Exhaustive grid') == 'Exhaustive grid':
                maximum = min(maximum, cfg['design_budget']//math.prod(len(d['values']) for d in dims))
            values = grid_values(row.get('Min'), row.get('Max'), row.get('Step'), maximum)
            if p not in ('center_x', 'center_y', 'rotation', 'thickness') and min(values) <= 0:
                raise ValueError(f'{p} must be positive')
            if p == 'thickness' and min(values) < 0:
                raise ValueError('Thickness must be nonnegative')
        dimension = dict(parameter=p, target=target, index=index, field=field, values=values)
        if linked:
            dimension['linked_indices'] = linked
        dims.append(dimension)
    cfg['dimensions'] = dims
    cfg['design_count'] = math.prod(len(d['values']) for d in dims)
    if cfg.get('search_mode', 'Exhaustive grid') == 'Exhaustive grid' and cfg['design_count'] > cfg['design_budget']:
        raise ValueError(f"Grid has {cfg['design_count']:,} designs. Increase the design budget or narrow bounds. No truncation is performed.")
    return cfg


def designs(base, cfg):
    for values in itertools.product(*(d['values'] for d in cfg['dimensions'])):
        m, ratios = copy.deepcopy(base), []
        for d, value in zip(cfg['dimensions'], values):
            p, i = d['parameter'], d['index']
            if p.startswith('lattice_'):
                if p in ('lattice_square', 'lattice_x'):
                    m['ax'] = value
                if p in ('lattice_square', 'lattice_y'):
                    m['ay'] = value
            elif p in ('thickness', 'layer_material'):
                m['layers'][i][d['field']] = value
            elif p == 'r_over_a':
                ratios.append((i, value))
            else:
                m['patterns'][i][d['field']] = value
        for i, ratio in ratios:
            m['patterns'][i]['sx'] = ratio*min(m['ax'], m['ay'])
        for d in cfg['dimensions']:
            for other in d.get('linked_indices', []):
                m['patterns'][other][d['field']] = m['patterns'][d['index']][d['field']]
        yield m


def geometry_error(m, cfg):
    if cfg.get('merge_circles'):
        from circle_geometry import merged_geometry_error
        error = merged_geometry_error(m, cfg['min_bridge_um'], cfg.get('min_neck_um', 0.))
        if error:
            return error
        cfg = dict(cfg, separate_circles=False)
    a = min(m['ax'], m['ay'])
    if cfg.get('all_shape_bridges'):
        for p in m['patterns']:
            angle = math.radians(p['angle'])
            c, s = abs(math.cos(angle)), abs(math.sin(angle))
            if p['shape'] == 'circle': ex = ey = p['sx']
            elif p['shape'] == 'ellipse':
                ex = math.hypot(p['sx']*c, p['sy']*s)
                ey = math.hypot(p['sx']*s, p['sy']*c)
            else:
                ex = (p['sx']*c+p['sy']*s)/2
                ey = (p['sx']*s+p['sy']*c)/2
            if min(m['ax']-2*ex,m['ay']-2*ey) <= max(0.,cfg['min_bridge_um']):
                return 'Hole shape does not leave a positive periodic bridge'
    circles = [p for p in m['patterns'] if p['shape'] == 'circle']
    for p in circles:
        if p['sx']/a >= cfg['ratio_limit']:
            return 'r/a is not strictly below the limit'
        if cfg['separate_circles'] and (2*p['sx'] >= a or a-2*p['sx'] < cfg['min_bridge_um']-1e-12):
            return 'Periodic circle separation / minimum bridge failed'
    if cfg['separate_circles']:
        for p, q in itertools.combinations(circles, 2):
            if p['layer'] != q['layer']:
                continue
            dx = abs((p['cx']-q['cx']+m['ax']/2) % m['ax']-m['ax']/2)
            dy = abs((p['cy']-q['cy']+m['ay']/2) % m['ay']-m['ay']/2)
            gap = math.hypot(dx, dy)-p['sx']-q['sx']
            if gap <= 0 or gap < cfg['min_bridge_um']-1e-12:
                return 'Circles in the same layer overlap or violate minimum bridge'
    return ''


def local_maxima(y):
    result, i = [], 1
    while i < len(y)-1:
        if y[i] > y[i-1]:
            j = i
            while j+1 < len(y) and y[j+1] == y[i]:
                j += 1
            if j+1 < len(y) and y[j] > y[j+1]:
                result.append((i+j)//2)
            i = j+1
        else:
            i += 1
    return result


def peak_info(x, y, i, minima):
    left = max((k for k in minima if k < i), default=0)
    right = min((k for k in minima if k > i), default=len(y)-1)
    baseline = max(y[left], y[right])
    prominence = max(0., float(y[i]-baseline))
    out = dict(wavelength_nm=float(x[i]), absorption=float(y[i]), prominence=prominence,
               fwhm_nm=None, Q_estimate=None, linewidth_status='unresolved', index=int(i))
    if i in (0, len(y)-1):
        out['linewidth_status'] = 'range edge; peak may lie outside range'
        return out
    if prominence <= 0:
        out['linewidth_status'] = 'flat / no resolved local peak'
        return out
    level, l, r = baseline+prominence/2, i, i
    while l > left and y[l] > level:
        l -= 1
    while r < right and y[r] > level:
        r += 1
    if l == i or r == i or y[l] > level or y[r] > level:
        return out
    xl = x[l]+(level-y[l])/(y[l+1]-y[l])*(x[l+1]-x[l])
    xr = x[r-1]+(level-y[r-1])/(y[r]-y[r-1])*(x[r]-x[r-1])
    width = float(xr-xl)
    out['fwhm_nm'] = width
    asymmetry = max(x[i]-xl, xr-x[i])/max(min(x[i]-xl, xr-x[i]), 1e-30)
    if width <= 0 or max(np.diff(x[l:r+1])) > width/8:
        out['linewidth_status'] = 'needs finer wavelength sampling'
    elif asymmetry > 2:
        out['linewidth_status'] = 'asymmetric / overlapping; modal fit needed'
    else:
        out['Q_estimate'] = float(x[i]/width)
        out['linewidth_status'] = 'baseline-relative FWHM estimate; verify convergence'
    return out


def spectrum_peaks(rows, prominence):
    array = np.asarray(sorted(rows, key=lambda r: r[1]), dtype=float)
    x, y = array[:, 1], array[:, 5]
    minima = local_maxima(-y)
    peaks = [peak_info(x, y, i, minima) for i in local_maxima(y)]
    peaks = [p for p in peaks if p['prominence'] >= prominence]
    top = int(np.argmax(y))
    if all(p['index'] != top for p in peaks):
        peaks.append(peak_info(x, y, top, minima))
    return sorted(peaks, key=lambda p: (-p['absorption'], p['wavelength_nm'])), array


def refinement_points(rows, prominence):
    peaks, array = spectrum_peaks(rows, prominence)
    x, points = array[:, 1], set()
    existing = set(x)
    for p in peaks:
        i = p['index']
        half = max(x[min(i+1, len(x)-1)]-x[i], x[i]-x[max(0, i-1)])
        # Refine the peak center independently so the height keeps converging.
        points.update(float(v) for v in np.linspace(max(x[0], x[i]-half), min(x[-1], x[i]+half), 17) if v not in existing)
        if p['fwhm_nm']:
            half = max(half, p['fwhm_nm']*1.5)
        points.update(float(v) for v in np.linspace(max(x[0], x[i]-half), min(x[-1], x[i]+half), 49) if v not in existing)
    return sorted(points)


def conditions(m):
    out = dict(lattice_x_um=m['ax'], lattice_y_um=m['ay'], basis=m['basis'], theta_deg=m['points'][0][2], phi_deg=m['phi'], polarization=m['polarization'])
    for layer in m['layers']:
        out[f"layer:{layer['name']}:thickness_um"] = layer['thickness']
        out[f"layer:{layer['name']}:material"] = layer['material']
    for i, p in enumerate(m['patterns'], 1):
        out.update({f'pattern:{i}:{k}': v for k, v in p.items()})
        if p['shape'] == 'circle':
            out[f'pattern:{i}:r_over_a'] = p['sx']/min(m['ax'], m['ay'])
    return out


def write_csv(path, records):
    fields = list(dict.fromkeys(k for row in records for k in row)) or ['design_id', 'status']
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def execute_search(base, perf, cfg, directory, executor, emit, cancelled):
    """Evaluate the exact requested Cartesian grid, without optimization.

    No geometry acceptance limits, response targets, early winner selection or
    adaptive sampling are applied. Invalid solver results remain in the raw
    files and are explicitly flagged. Every requested design gets a status.
    """
    from backend import Cancelled
    from scan_storage import json_default
    from optical_objective import valid_spectrum
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    records, total_points, attempted = [], 0, 0
    status, reason = 'complete', ''
    stopped = False
    finalizing = False
    def begin_finalizing():
        nonlocal finalizing
        if not finalizing:
            finalizing = True
            emit(dict(kind='finalizing', points=total_points,
                      text='Saving all sweep samples, design statuses and archive…'))
    def finite_row(row):
        try:
            return len(row) == 6 and all(math.isfinite(float(v)) for v in row)
        except (TypeError, ValueError, OverflowError):
            return False
    def checkpoint_value(value):
        if value is None or value == '':
            return None
        try:
            return float(value)
        except (ValueError, OverflowError):
            return value
    def save_json(path, data):
        path.write_text(json.dumps(data, indent=2, allow_nan=False, default=json_default), encoding='utf-8')
    save_json(directory/'search_config.json', dict(options=cfg, base_model=base, performance=perf,
              semantics='Exact grid and input samples; analysis never changes sampling.'))
    columns = ['point_index', 'wavelength_nm', 'angle_deg', 'R', 'T', 'A']
    with (directory/'design_models.jsonl').open('w', encoding='utf-8') as models, \
            (directory/'all_spectra.csv').open('w', newline='', encoding='utf-8') as spectra:
        writer = csv.writer(spectra)
        writer.writerow(['design_id']+columns)
        for design_id, model in enumerate(designs(base, cfg), 1):
            record = dict(design_id=design_id, **conditions(model))
            models.write(json.dumps(dict(design_id=design_id, model=model), allow_nan=False, default=json_default)+'\n')
            models.flush()
            if not stopped:
                if cancelled():
                    status, reason, stopped = 'cancelled', 'Sweep cancelled by user', True
                elif total_points+len(model['points']) > cfg['point_budget']:
                    status, reason, stopped = 'partial', 'Sample budget reached; remaining designs were not run', True
            if stopped:
                begin_finalizing()
                records.append(dict(record, status='not_run', reason=reason, spectral_points=0))
                continue
            attempted += 1
            emit(dict(kind='search_progress', design=design_id, total=cfg['design_count'],
                      points=total_points, text='Sweeping requested samples'))
            rows, info = [], {}
            evaluation_status, evaluation_reason = 'evaluated', ''
            try:
                remaining = 0  # No elapsed-time limit.
                def progress(event):
                    if event.get('kind') in ('started', 'progress'):
                        emit(dict(kind='search_progress', design=design_id, total=cfg['design_count'],
                                  points=total_points+event.get('done', 0), text='Sweeping requested samples'))
                rows, info = executor(model, dict(perf, timeout_seconds=remaining), progress, cancelled)
                rows = list(rows)
                if len(rows) != len(model['points']):
                    evaluation_status, evaluation_reason = 'incomplete', 'Solver did not return every requested sample'
                elif not all(finite_row(row) for row in rows) or not valid_spectrum(rows):
                    evaluation_status, evaluation_reason = 'invalid', 'Nonphysical or nonfinite R/T/A; raw values retained without clipping'
            except Exception as exc:
                evaluation_status, evaluation_reason = 'failed', str(exc)
                # backend.py also runs as __main__; its Cancelled class then
                # has a different module identity from imported backend.Cancelled.
                was_cancelled = cancelled() or isinstance(exc, Cancelled)
                if was_cancelled or isinstance(exc, TimeoutError):
                    status = 'cancelled' if was_cancelled else 'partial'
                    reason, stopped, evaluation_status = str(exc), True, 'incomplete'
                    begin_finalizing()
                # The real backend checkpoints each worker batch. Recover it
                # when an evaluation stops so even its partial spectrum is visible.
                if hasattr(executor, 'directory') and hasattr(executor, 'index'):
                    checkpoint = Path(executor.directory)/'evaluations'/f'{executor.index:06d}'/'batch_results.csv'
                    if checkpoint.is_file():
                        with checkpoint.open(encoding='utf-8') as stream:
                            rows = [[checkpoint_value(row.get(k)) for k in columns] for row in csv.DictReader(stream)]
                info = dict(error=str(exc))
            if design_id == cfg['design_count']:
                begin_finalizing()
            total_points += len(rows)
            # Persist before deriving summaries: failed/invalid data is evidence.
            with (directory/f'design_{design_id}_spectrum.csv').open('w', newline='', encoding='utf-8') as stream:
                per_design = csv.writer(stream)
                per_design.writerow(columns)
                per_design.writerows(rows)
            writer.writerows([design_id]+list(row) for row in rows)
            spectra.flush()
            save_json(directory/f'design_{design_id}_diagnostics.json', info)
            record.update(status=evaluation_status, reason=evaluation_reason, spectral_points=len(rows))
            finite = [r for r in rows if finite_row(r)]
            for index, key in ((3, 'R'), (4, 'T'), (5, 'A')):
                for direction, selector in (('min', min), ('max', max)):
                    if finite:
                        row = selector(finite, key=lambda r: r[index])
                        record.update({f'{key}_{direction}': row[index], f'{key}_{direction}_wavelength_nm': row[1],
                                       f'{key}_{direction}_angle_deg': row[2]})
            records.append(record)
            write_csv(directory/'design_results.csv', records)
    begin_finalizing()
    evaluated = sum(r['status'] == 'evaluated' for r in records)
    if status == 'complete' and evaluated != cfg['design_count']:
        status, reason = 'partial', 'Some designs failed or returned incomplete/invalid data; see each design status'
    summary = dict(search_mode='Exhaustive grid', status=status, reason=reason, grid_designs=cfg['design_count'],
                   evaluated=evaluated, attempted=attempted, failed=sum(r['status'] == 'failed' for r in records),
                   invalid=sum(r['status'] == 'invalid' for r in records),
                   incomplete=sum(r['status'] == 'incomplete' for r in records),
                   not_run=sum(r['status'] == 'not_run' for r in records), excluded=0,
                   spectral_points=total_points, elapsed_seconds=time.monotonic()-started,
                   scope='Exact requested parameter grid and samples. All data retained. Q is a sampled, baseline-relative linewidth estimate, not a modal fit or convergence certification.')
    write_csv(directory/'design_results.csv', records)
    save_json(directory/'search_summary.json', summary)
    archive = directory/'grid_sweep_results.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(directory.rglob('*')):
            if path.is_file() and path.suffix in ('.csv', '.json', '.jsonl', '.sqlite', '.npz'):
                bundle.write(path, str(path.relative_to(directory)))
    return dict(kind='search_complete', summary=summary, directory=str(directory), archive=str(archive))


def analyze_grid_results(directory, response='Reflection', direction='High', threshold=None, metric='Response'):
    """Query saved data only; never run/refine the solver or discard source data."""
    from optical_objective import RESPONSES
    response_name(dict(response=response))
    if direction not in ('High', 'Low') or metric not in ('Response', 'Q factor'):
        raise ValueError('Choose high/low response or Q factor')
    if threshold is not None:
        threshold = number(threshold, 'Threshold', minimum=0)
        if metric == 'Response' and threshold > 1:
            raise ValueError('Response threshold must be between 0 and 1')
    directory = Path(directory)
    with (directory/'design_results.csv').open(encoding='utf-8') as stream:
        designs_data = list(csv.DictReader(stream))
    matches = []
    column = RESPONSES[response]
    for design in designs_data:
        # Invalid/incomplete results remain available under All designs/raw data,
        # but cannot silently qualify as physical candidates.
        if design['status'] != 'evaluated':
            continue
        with (directory/f"design_{design['design_id']}_spectrum.csv").open(encoding='utf-8') as stream:
            data = list(csv.DictReader(stream))
        rows = [[i, float(r['wavelength_nm']), float(r['angle_deg']), float(r['R']), float(r['T']), float(r['A'])]
                for i, r in enumerate(data)]
        if metric == 'Response':
            selected = (max if direction == 'High' else min)(rows, key=lambda r: r[column])
            value = selected[column]
            if threshold is None or (value >= threshold if direction == 'High' else value <= threshold):
                matches.append(dict(design, response=response, response_value=value,
                                    wavelength_nm=selected[1], angle_deg=selected[2]))
        else:
            for theta in sorted({r[2] for r in rows}):
                spectrum = sorted((r for r in rows if r[2] == theta), key=lambda r: r[1])
                if len(spectrum) < 3 or len({r[1] for r in spectrum}) != len(spectrum):
                    continue
                x = np.array([r[1] for r in spectrum])
                for feature, sign in (('peak', 1), ('dip', -1)):
                    y = sign*np.array([r[column] for r in spectrum])
                    minima = local_maxima(-y)
                    for i in local_maxima(y):
                        peak = peak_info(x, y, i, minima)
                        q = peak['Q_estimate']
                        if q is not None and (threshold is None or (q >= threshold if direction == 'High' else q <= threshold)):
                            peak.pop('index'); peak.pop('absorption')
                            matches.append(dict(design, response=response, feature=feature,
                                                response_value=spectrum[i][column], angle_deg=theta, **peak))
    key = 'Q_estimate' if metric == 'Q factor' else 'response_value'
    return sorted(matches, key=lambda r: float(r[key]), reverse=direction == 'High')
