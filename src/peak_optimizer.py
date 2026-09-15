"""Finite design-grid search, adaptive peak detection, and complete design reporting."""
import copy
import csv
import itertools
import json
import math
import time
import zipfile
from pathlib import Path
import numpy as np
from model import integer, number, sweep

BOUND_COLS = ['Parameter', 'Target', 'Min', 'Max', 'Step', 'Choices']
SEARCH_KEYS = ['ratio_limit', 'min_bridge_um', 'separate_circles', 'absorption_target',
               'tie_tolerance', 'prominence', 'refinement_rounds', 'design_budget', 'point_budget']
SEARCH_DEFAULTS = [.6, 0., True, .99, .0001, .00001, 3, 500, 200000]


def grid_values(lo, hi, step):
    lo, hi = number(lo, 'Minimum'), number(hi, 'Maximum')
    if hi < lo:
        raise ValueError('Maximum must be >= minimum')
    if lo == hi:
        return [lo]
    values = sweep(lo, hi, step, 'Design bound', limit=10000)
    if math.isclose(values[-1], hi, rel_tol=1e-12, abs_tol=1e-14):
        values[-1] = hi
    else:
        values.append(hi)
    return values


def parse_search(model, bounds, options):
    if model['mode'] != 'Wavelength sweep' or len(model['points']) < 3:
        raise ValueError('Choose Wavelength sweep with at least three spectral points')
    cfg = dict(zip(SEARCH_KEYS, SEARCH_DEFAULTS))
    cfg.update(options)
    for key in ('ratio_limit', 'min_bridge_um', 'absorption_target', 'tie_tolerance', 'prominence'):
        cfg[key] = number(cfg[key], key, minimum=0)
    if not 0 < cfg['ratio_limit'] <= .6:
        raise ValueError('r/a limit must be > 0 and <= 0.6; acceptance is strictly below the limit')
    if not .99 <= cfg['absorption_target'] < 1:
        raise ValueError('Absorption target must be >= 0.99 and < 1; acceptance is strictly above it')
    if cfg['tie_tolerance'] > 1 or cfg['prominence'] > 1:
        raise ValueError('Tie tolerance and prominence must be fractions between 0 and 1')
    if not isinstance(cfg['separate_circles'], bool):
        raise ValueError('Separate circles must be true or false')
    for key, low, high in (('refinement_rounds', 0, 6), ('design_budget', 1, 10000), ('point_budget', 3, 2000000)):
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
        if touched.intersection(keys):
            raise ValueError(f'Duplicate or conflicting bound: {p} {target}')
        touched.update(keys)
        if categorical:
            values = list(dict.fromkeys(v.strip() for v in str(row.get('Choices') or '').split(';') if v.strip()))
            if not values or any(v not in mats for v in values):
                raise ValueError('Material choices must be semicolon-separated material library names')
        else:
            values = grid_values(row.get('Min'), row.get('Max'), row.get('Step'))
            if p not in ('center_x', 'center_y', 'rotation', 'thickness') and min(values) <= 0:
                raise ValueError(f'{p} must be positive')
            if p == 'thickness' and min(values) < 0:
                raise ValueError('Thickness must be nonnegative')
        dims.append(dict(parameter=p, target=target, index=index, field=field, values=values))
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
        yield m


def geometry_error(m, cfg):
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
    from backend import Cancelled
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    total_points = completed = failed = skipped = errors_in_row = 0
    results, all_peaks, best_rows = [], [], []
    status, reason, best_absorption = 'complete', '', -1.
    (directory/'search_config.json').write_text(json.dumps(dict(options=cfg, base_model=base, performance=perf), indent=2, allow_nan=False), encoding='utf-8')
    try:
        with (directory/'design_models.jsonl').open('w', encoding='utf-8') as models:
            for design_id, model in enumerate(designs(base, cfg), 1):
                if cancelled():
                    raise Cancelled('Search cancelled by user')
                if time.monotonic()-started >= perf['timeout_seconds']:
                    raise TimeoutError('Whole-search timeout reached')
                record = dict(design_id=design_id, **conditions(model))
                models.write(json.dumps(dict(design_id=design_id, model=model), allow_nan=False)+'\n')
                models.flush()
                invalid = geometry_error(model, cfg)
                emit(dict(kind='search_progress', design=design_id, total=cfg['design_count'], points=total_points, text=invalid or 'Evaluating design'))
                if invalid:
                    results.append(dict(record, status='excluded', reason=invalid))
                    skipped += 1
                    continue
                rows_by_wavelength = {}
                try:
                    wavelengths = [p[1] for p in base['points']]
                    for round_id in range(cfg['refinement_rounds']+1):
                        if cancelled():
                            raise Cancelled('Search cancelled by user')
                        if not wavelengths:
                            break
                        if total_points+len(wavelengths) > cfg['point_budget']:
                            raise TimeoutError('Spectral point budget reached; increase it to finish the grid')
                        remaining = perf['timeout_seconds']-(time.monotonic()-started)
                        if remaining < 1:
                            raise TimeoutError('Whole-search timeout reached')
                        evaluation = dict(model, points=[[i, wl, base['points'][0][2]] for i, wl in enumerate(wavelengths)])
                        def progress(event):
                            if event['kind'] in ('started', 'progress'):
                                emit(dict(kind='search_progress', design=design_id, total=cfg['design_count'], points=total_points,
                                          text=f"Refinement {round_id}/{cfg['refinement_rounds']}; {event.get('done', 0)}/{len(wavelengths)} spectral points"))
                        rows, info = executor(evaluation, dict(perf, timeout_seconds=max(1, int(remaining))), progress, cancelled)
                        total_points += len(rows)
                        if any(not all(math.isfinite(float(v)) for v in row) or row[5] < -1e-8 or row[5] > 1 for row in rows):
                            raise ValueError('Nonphysical absorptance; check material loss and Fourier convergence. Values were not clipped.')
                        rows_by_wavelength.update({row[1]: row for row in rows})
                        (directory/f'design_{design_id}_round_{round_id}_diagnostics.json').write_text(json.dumps(info, indent=2, allow_nan=False), encoding='utf-8')
                        wavelengths = refinement_points(list(rows_by_wavelength.values()), cfg['prominence'])
                    rows = sorted(rows_by_wavelength.values(), key=lambda r: r[1])
                    peaks, _ = spectrum_peaks(rows, cfg['prominence'])
                    for p in peaks:
                        p.pop('index', None)
                        all_peaks.append(dict(record, **p))
                    top = peaks[0]
                    results.append(dict(record, status='evaluated', reason='', **top, spectral_points=len(rows)))
                    write_csv(directory/f'design_{design_id}_spectrum.csv', [dict(zip(['wavelength_nm', 'angle_deg', 'R', 'T', 'A'], r[1:])) for r in rows])
                    if top['absorption'] > best_absorption:
                        best_absorption, best_rows = top['absorption'], rows
                    completed += 1
                    errors_in_row = 0
                except (Cancelled, TimeoutError):
                    results.append(dict(record, status='incomplete', reason='Stopped before refinement finished'))
                    raise
                except Exception as exc:
                    failed += 1
                    errors_in_row += 1
                    results.append(dict(record, status='failed', reason=str(exc)))
                    if errors_in_row >= 3:
                        raise RuntimeError('Three consecutive design evaluations failed: '+str(exc)) from exc
    except Cancelled as exc:
        status, reason = 'cancelled', str(exc)
    except Exception as exc:
        status, reason = 'partial', str(exc)
    if failed and status == 'complete':
        status, reason = 'partial', 'One or more designs failed; grid coverage is incomplete'
    for row in results+all_peaks:
        a = row.get('absorption')
        row['above_target'] = a is not None and a > cfg['absorption_target']
        row['matches_best'] = a is not None and best_absorption-a <= cfg['tie_tolerance']+1e-15
    feasible = [p for p in all_peaks if p['above_target']]
    feasible.sort(key=lambda p: (p['Q_estimate'] is not None, p['Q_estimate'] or 0., p['absorption']), reverse=True)
    ties = [r for r in results if r['matches_best']]
    evaluated = sorted((r for r in results if r.get('status') == 'evaluated'), key=lambda r: -r['absorption'])
    results = evaluated+[r for r in results if r.get('status') != 'evaluated']
    summary = dict(status=status, reason=reason, grid_designs=cfg['design_count'], evaluated=completed, excluded=skipped, failed=failed,
                   spectral_points=total_points, elapsed_seconds=time.monotonic()-started,
                   best_absorption=best_absorption if completed else None, matching_designs=len(ties),
                   above_target_designs=len({p['design_id'] for p in feasible}),
                   highest_Q_estimate=next((p['Q_estimate'] for p in feasible if p['Q_estimate'] is not None), None),
                   scope='Best found on the finite design grid and sampled wavelength range; not a continuous global maximum. Q is a baseline-relative FWHM estimate, not a modal fit or convergence certification.')
    for name, data in (('design_results.csv', results), ('all_peaks.csv', all_peaks), ('matching_best.csv', ties), ('above_target_by_Q.csv', feasible)):
        write_csv(directory/name, data)
    write_csv(directory/'best_spectrum.csv', [dict(zip(['wavelength_nm', 'angle_deg', 'R', 'T', 'A'], r[1:])) for r in best_rows])
    (directory/'search_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    archive = directory/'peak_search_results.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(directory.iterdir()):
            if path.suffix in ('.csv', '.json', '.jsonl'):
                bundle.write(path, path.name)
    return dict(kind='search_complete', summary=summary, directory=str(directory), archive=str(archive))
