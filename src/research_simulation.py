"""Typed dispatch for optional research solvers using editable, saved inputs.

Adapters are explicit application code, never import names supplied by a job.
The shared project is preserved as provenance; each adapter validates its own
physical geometry and reports its dimensional and numerical limitations.
"""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path


ADAPTERS = {('photonic_bands', 'band_structure'): 'photonic_bands',
            ('thermal', 'steady_state'): 'thermal_study',
            ('sesame_transport', 'drift_diffusion'): 'sesame_transport',
            ('pcsel', 'research'): 'pcsel_research',
            ('advanced_transport', 'finite_contact'): 'advanced_transport',
            ('pcsel_transport', 'conformal'): 'pcsel_transport_study',
            ('pcsel_unitcell_transport', 'representative_cell'): 'pcsel_unitcell_transport',
            ('high_field_optics', 'franz_keldysh'): 'high_field_optics'}


def _json_object(value, label):
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(label + ' must be an object with named fields.')
    try:
        encoded = json.dumps(value, allow_nan=False)
        if len(encoded) > 16 * 1024**2:
            raise ValueError(label + ' exceeds the 16 MiB input limit.')
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + ' must contain portable finite JSON values: ' + str(exc)) from exc


def validate_research_options(options):
    """Validate persistable options without starting an optional runtime."""
    cfg = _json_object(options, 'Research simulation settings')
    if set(cfg) - {'engine', 'study', 'settings'}:
        raise ValueError('Unsupported research simulation fields: ' + ', '.join(sorted(set(cfg)-{'engine', 'study', 'settings'})))
    engine, study = cfg.get('engine'), cfg.get('study')
    if not isinstance(engine, str) or not isinstance(study, str) or (engine, study) not in ADAPTERS:
        raise ValueError('Select a supported research engine and study.')
    cfg['settings'] = _json_object(cfg.get('settings', {}), 'Research study inputs')
    return cfg


def prepare_research_job(project, options):
    """Validate physical inputs through the chosen adapter before launch."""
    cfg = validate_research_options(options)
    adapter = importlib.import_module(ADAPTERS[(cfg['engine'], cfg['study'])])
    prepared = adapter.prepare(copy.deepcopy(project), copy.deepcopy(cfg['settings']))
    return dict(task='research_simulation', **cfg, project=copy.deepcopy(project),
                prepared=_json_object(prepared, 'Prepared research simulation'))


def execute_research(specification, directory, emit=lambda event: None, cancelled=lambda: False):
    """Run a registered adapter and preserve its actual completion status."""
    from backend import Cancelled
    cfg = validate_research_options({key: specification[key] for key in ('engine', 'study', 'settings') if key in specification})
    if cancelled():
        raise Cancelled('Research simulation cancelled before launch.')
    # Revalidate portable inputs at the process boundary. Never trust a saved
    # prepared payload to bypass the adapter's geometry/runtime constraints.
    job = prepare_research_job(specification.get('project', {}), cfg)
    adapter = importlib.import_module(ADAPTERS[(cfg['engine'], cfg['study'])])
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'research_inputs.json').write_text(json.dumps(job, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    try:
        result = adapter.execute(job['prepared'], directory, emit, cancelled)
    except InterruptedError as exc:
        raise Cancelled(str(exc)) from exc
    if cancelled():
        raise Cancelled('Research simulation cancelled.')
    summary = _json_object(result, 'Research simulation result')
    if summary.get('status') not in ('complete', 'partial', 'validity_limit', 'unconverged'):
        raise RuntimeError('Research adapter did not report a recognized result status.')
    if summary.get('engine') and summary['engine'] != cfg['engine']:
        summary['solver_engine'] = summary['engine']
    summary.update(task='research_simulation', engine=cfg['engine'], study=cfg['study'])
    for name in ('research_summary.json', 'search_summary.json'):
        (directory/name).write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return dict(kind='search_complete', directory=str(directory), summary=summary)
