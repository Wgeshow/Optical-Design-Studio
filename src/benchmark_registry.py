"""Versioned immutable reference cases and numerical comparison of normal jobs.

Reference files are checked against bundled SHA-256 values. Editable copies run
through the same solver dispatch as ordinary user devices. Agreement with a
paper and numerical convergence are independent, explicitly reported claims.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent/'benchmark_data'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _path(root, name):
    root = Path(root).resolve()
    value = (root/name).resolve()
    if not value.is_relative_to(root):
        raise ValueError('Benchmark data path escapes its bundle.')
    return value


def _manifest():
    value = json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    if value.get('schema_version') != 1:
        raise ValueError('Unsupported benchmark manifest version.')
    return value


def list_benchmarks():
    """Metadata only; selecting or opening a reference does not run a solver."""
    return [copy.deepcopy({k: v for k, v in row.items() if k != 'files'}) for row in _manifest()['cases']]


def load_benchmark(identifier):
    rows = [row for row in _manifest()['cases'] if row['id'] == identifier]
    if len(rows) != 1:
        raise ValueError('Unknown or ambiguous benchmark case.')
    record = rows[0]
    for name, digest in record['files'].items():
        if hashlib.sha256(_path(ROOT, name).read_bytes()).hexdigest() != digest:
            raise ValueError('Bundled benchmark checksum mismatch: '+name)
    case = json.loads(_path(ROOT, record['case_file']).read_text(encoding='utf-8'))
    case.update(id=record['id'], version=record['version'], bundle_hash=_digest(record['files']))
    return case


def input_fingerprint(project, kind, options):
    project = copy.deepcopy(project)
    for key in ('benchmark_request', 'desktop_search', 'appearance', 'performance', 'literature_validation'):
        project.pop(key, None)
    options = copy.deepcopy(options)
    if kind == 'research_simulation':
        options.get('settings', {}).pop('runtime', None)
        if options.get('engine') in ('photonic_bands','pcsel','sesame_transport','pcsel_transport'):
            # These adapters take all physical inputs from their independent
            # settings. The unrelated finite-device project is provenance only.
            project = {}
            # Editors expose omitted solver defaults. Canonicalize through the
            # actual adapter so an unchanged draft does not become an edit only
            # because a default is now explicit. This preflight never runs an
            # engine, and the placeholder avoids the frozen-Python default.
            import importlib
            from research_simulation import ADAPTERS
            adapter=importlib.import_module(ADAPTERS[(options['engine'],options['study'])])
            settings=copy.deepcopy(options.get('settings',{}))
            settings['runtime']={'mode':'local','executable':'comparison-runtime'}
            if options['engine']=='photonic_bands' and settings.get('solver','mpb')=='mpb':
                settings['runtime']={'mode':'wsl','distro':'comparison-runtime','executable':'mpb'}
            settings=adapter.prepare({},settings)
            def physical(value):
                if isinstance(value,dict):
                    return {key:physical(child) for key,child in value.items() if key not in ('runtime','name','label')}
                if isinstance(value,list):return [physical(child) for child in value]
                return value
            settings=physical(settings)
            options['settings']=settings
    return _digest(dict(project=project, kind=kind, options=options))


def editable_copy(identifier):
    case = load_benchmark(identifier)
    project = copy.deepcopy(case['project'])
    options = copy.deepcopy(case['options'])
    project['benchmark_request'] = dict(id=case['id'], version=case['version'], bundle_hash=case['bundle_hash'],
        reference_input_hash=input_fingerprint(project, case['kind'], options))
    return dict(project=project, kind=case['kind'], options=options, label=case['label'],
                source=copy.deepcopy(case['source']), limitations=copy.deepcopy(case['limitations']))


def prepare_comparison_request(project, kind, options):
    request = copy.deepcopy(project.get('benchmark_request'))
    if request is None:
        return None
    case = load_benchmark(request.get('id'))
    if request.get('version') != case['version'] or request.get('bundle_hash') != case['bundle_hash']:
        raise ValueError('The saved benchmark reference version/checksum does not match the installed bundle.')
    expected = input_fingerprint(case['project'], case['kind'], case['options'])
    if request.get('reference_input_hash') != expected:
        raise ValueError('The benchmark reference input fingerprint does not match its immutable case.')
    request['input_edited'] = input_fingerprint(project, kind, options) != expected
    return request


def _table(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def _transform(values, kind, factor=1.):
    array = np.asarray(values, dtype=float)
    if kind == 'reciprocal':
        if np.any(array == 0):
            raise ValueError('Zero coordinate cannot be converted to reciprocal units.')
        return float(factor)/array
    if kind == 'db10':
        if np.any(array <= 0):
            raise ValueError('Nonpositive transmission cannot be compared on the published decibel scale.')
        return 10*np.log10(array)
    return array*float(factor)


def _metric(observed, reference, tolerance=None):
    observed, reference = np.asarray(observed, float), np.asarray(reference, float)
    if observed.shape != reference.shape or not observed.size or not np.isfinite(observed).all() or not np.isfinite(reference).all():
        raise ValueError('Comparison requires matching nonempty finite observations.')
    residual = observed-reference
    answer = dict(observations=int(observed.size), rmse=float(np.sqrt(np.mean(residual**2))),
        maximum_absolute_residual=float(np.abs(residual).max()), mean_residual=float(residual.mean()),
        residuals=residual.tolist(), observed=observed.tolist(), reference=reference.tolist())
    if tolerance is not None:
        bounds = np.broadcast_to(np.asarray(tolerance, float), residual.shape)
        if np.any(bounds < 0) or not np.isfinite(bounds).all():
            raise ValueError('Reference tolerances must be nonnegative finite values.')
        answer.update(tolerance=bounds.tolist(), fraction_within_tolerance=float(np.mean(np.abs(residual) <= bounds)),
                      tolerance_passed=bool(np.all(np.abs(residual) <= bounds)))
    return answer


def compare_run(identifier, directory, request=None):
    case = load_benchmark(identifier)
    directory = Path(directory).resolve()
    results = []
    for comparison in case['comparisons']:
        row = dict(id=comparison['id'], label=comparison['label'], units=comparison.get('units', ''),
                   tolerance_basis=comparison.get('tolerance_basis', 'No acceptance tolerance specified'))
        try:
            kind = comparison['type']
            actual_root = directory
            if comparison.get('last_accuracy_level') and (directory/'band_convergence.json').exists():
                levels = json.loads((directory/'band_convergence.json').read_text())['results']
                actual_root = _path(directory, levels[-1]['directory'])
            if kind in ('curve', 'npz_slice_curve'):
                reference = _table(_path(ROOT, comparison['reference_file']))
                reference = [r for r in reference if all(float(r.get(key, 0)) == 0 for key in comparison.get('exclude_flags', []))]
                if kind == 'npz_slice_curve':
                    with np.load(_path(actual_root, comparison['actual_file']), allow_pickle=False) as actual:
                        x = actual[comparison['actual_x']].copy()
                        axis = actual[comparison['slice_axis']]
                        index = int(np.argmin(np.abs(axis-comparison['slice_coordinate'])))
                        if abs(float(axis[index])-comparison['slice_coordinate']) > 1e-9:
                            raise ValueError('The requested reference slice is absent from the calculated mesh.')
                        y = actual[comparison['actual_y']][index].copy()
                else:
                    actual = _table(_path(actual_root, comparison['actual_file']))
                    x = [r[comparison['actual_x']] for r in actual]
                    y = [r[comparison['actual_y']] for r in actual]
                x = _transform(x, comparison.get('x_transform'), comparison.get('x_factor', 1))
                y = _transform(y, comparison.get('y_transform'), comparison.get('y_factor', 1))
                if len(x) < 2 or not np.isfinite(x).all() or not np.isfinite(y).all():
                    raise ValueError('A reference curve needs at least two finite calculated samples.')
                order = np.argsort(x); x, y = x[order], y[order]
                if np.any(np.diff(x) <= 0):
                    raise ValueError('Calculated coordinates repeat; select one polarization/condition before comparison.')
                xref = np.array([float(r[comparison.get('reference_x', 'x')]) for r in reference])
                keep = (xref >= x[0]) & (xref <= x[-1])
                yref = np.array([float(r[comparison.get('reference_y', 'y')]) for r in reference])[keep]
                tolerance = comparison.get('absolute_tolerance')
                if comparison.get('tolerance_column'):
                    tolerance = np.array([float(r[comparison['tolerance_column']]) for r in reference])[keep]
                row.update(_metric(np.interp(xref[keep], x, y), yref, tolerance), x=xref[keep].tolist(),
                    omitted_reference_samples=int((~keep).sum()), interpolation='Linear, within calculated domain only; no extrapolation')
            elif kind == 'scalar_csv':
                actual = _table(_path(actual_root, comparison['actual_file']))
                selected = [r for r in actual if all(abs(float(r[k])-float(v)) <= 1e-12 for k, v in comparison.get('where', {}).items())]
                if len(selected) != 1:
                    raise ValueError('Expected exactly one matching scalar result row.')
                value = float(selected[0][comparison['actual_column']])*comparison.get('factor', 1.)
                row.update(_metric([value], [comparison['reference_value']], comparison.get('absolute_tolerance')))
            elif kind == 'pcsel_slope':
                actual = _table(_path(actual_root, comparison['actual_file']))
                eligible = [r for r in actual if float(r['total_loss_cm1']) > 0
                            and float(r['radiation_loss_cm1']) >= 0
                            and float(r['eigen_residual']) <= 1e-6
                            and float(r['balance_relative']) <= .02]
                if not eligible:
                    raise ValueError('No passive returned mode meets the stated residual and power-balance bounds.')
                selected = min(eligible, key=lambda r: float(r['total_loss_cm1']))
                assumptions = comparison['assumptions']
                total = float(selected['total_loss_cm1'])+assumptions['internal_loss_cm1']
                wavelength = float(selected['wavelength_nm'])
                if total <= 0 or wavelength <= 0:
                    raise ValueError('Positive total loss and wavelength are required for the slope estimate.')
                value = (assumptions['hc_over_q_nm_V']/wavelength*assumptions['injection_efficiency']
                         *assumptions['upward_fraction']*float(selected['radiation_loss_cm1'])/total)
                row.update(_metric([value], [comparison['reference_value']], comparison.get('absolute_tolerance')),
                    selected_mode=int(selected['mode']), assumptions=copy.deepcopy(assumptions),
                    scope='Lowest-loss eligible returned mode; sparse modal search does not prove the global lowest-loss mode.')
            elif kind in ('band_edges', 'band_gap_percent'):
                actual = _table(_path(actual_root, comparison['actual_file']))
                band = comparison['after_band']
                lo = max(float(r[f'band_{band}_a_over_lambda']) for r in actual)
                hi = min(float(r[f'band_{band+1}_a_over_lambda']) for r in actual)
                if kind == 'band_gap_percent':
                    if hi+lo <= 0:
                        raise ValueError('Nonpositive midgap frequency.')
                    metric = _metric([200*(hi-lo)/(hi+lo)], [comparison['reference_value']], comparison.get('absolute_tolerance'))
                else:
                    metric = _metric([lo, hi], comparison['reference_edges'], comparison.get('absolute_tolerance'))
                row.update(metric, sampled_gap_exists=hi > lo, scope='Specified k samples only')
            else:
                raise ValueError('Unsupported benchmark comparison type.')
            row['status'] = 'compared'
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row.update(status='unavailable', message=str(exc))
        results.append(row)
    summary = dict(schema_version=1, id=case['id'], version=case['version'], bundle_hash=case['bundle_hash'],
        input_edited=bool((request or {}).get('input_edited')), results=results, source=case['source'],
        limitations=case['limitations'], status='compared' if all(r['status'] == 'compared' for r in results) else 'partial',
        convergence_status='not_established', reproduction_accepted=False)
    convergence = directory/'band_convergence.json'
    if convergence.exists():
        data = json.loads(convergence.read_text())
        summary['convergence_status'] = 'last_pair_tolerance_passed' if data.get('last_pair_tolerance_passed') else 'not_established'
        summary['convergence'] = {k: data.get(k) for k in ('comparisons', 'specified_frequency_tolerance', 'spatial_convergence_established')}
    from data_library import write_json
    write_json(directory/'benchmark_comparison.json', summary)
    return summary


def complete_event(event, specification, directory):
    request = specification.get('benchmark')
    if not request or event.get('kind') not in ('complete', 'search_complete'):
        return event
    event = copy.deepcopy(event)
    try:
        result = compare_run(request['id'], directory, request)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = dict(status='unavailable', message=str(exc), reproduction_accepted=False)
        from data_library import write_json
        write_json(Path(directory)/'benchmark_comparison.json', result)
    event['benchmark_comparison'] = result
    event.setdefault('summary', {})['benchmark_comparison'] = result
    from data_library import write_json, read_json
    for filename in ('search_summary.json', 'research_summary.json'):
        path = Path(directory)/filename
        if path.exists():
            value = read_json(path); value['benchmark_comparison'] = result; write_json(path, value)
    return event
