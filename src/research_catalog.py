"""Discover only registered runnable adapters, without probing optional engines."""
from __future__ import annotations

import copy
import importlib

_BAND_FIELDS = [
    dict(path='solver', label='Band solver', type='choice', default='mpb', options=['mpb'], section='solver'),
    dict(path='dimension', label='Periodic dimensions', type='choice', default=2, options=[2, 3], section='geometry'),
    dict(path='lattice_vectors', label='Real-space lattice vectors', type='array', required=True, unit='a', section='geometry'),
    dict(path='background_epsilon', label='Background relative permittivity', type='number', default=1., section='materials'),
    dict(path='geometry', label='Editable primitives', type='array', default=[], section='geometry'),
    dict(path='k_vertices', label='Reciprocal path vertices', type='array', required=True, unit='reciprocal lattice', section='sampling'),
    dict(path='points_per_segment', label='Intervals per path segment', type='integer', default=10, section='sampling'),
    dict(path='polarizations', label='Field polarization', type='array', default=['te', 'tm'], section='solver'),
    dict(path='num_bands', label='Number of bands', type='integer', default=8, section='solver'),
    dict(path='resolution', label='Spatial resolution', type='integer', default=32, unit='pixels/a', section='convergence'),
    dict(path='tolerance', label='Eigensolver tolerance', type='number', default=1e-8, section='convergence'),
    dict(path='reference_length_um', label='Physical reference length', type='number', unit='um', section='geometry'),
    dict(path='runtime', label='Solver runtime', type='object', default={}, section='runtime'),
]


def _adapter(engine, study):
    from research_simulation import ADAPTERS
    key = (engine, study)
    if key not in ADAPTERS:
        raise ValueError('This research study is not registered as a runnable model.')
    return importlib.import_module(ADAPTERS[key])


def list_capabilities():
    from research_simulation import ADAPTERS
    rows = []
    for (engine, study), name in ADAPTERS.items():
        adapter = importlib.import_module(name)
        cap = copy.deepcopy(getattr(adapter, 'CAPABILITIES', {}))
        cap.update(engine=engine, study=study, implemented=True)
        cap.setdefault('label', 'Photonic bands' if engine == 'photonic_bands' else engine.replace('_', ' ').title())
        cap.setdefault('limitations', copy.deepcopy(getattr(adapter, 'LIMITATIONS', [])))
        cap.setdefault('dimensions', [2, 3] if engine == 'photonic_bands' else [])
        cap.setdefault('optional_runtime', engine == 'photonic_bands')
        cap['runtime_verified'] = False  # Listing an adapter is never a runtime probe.
        rows.append(cap)
    return rows


def field_schema(engine, study):
    adapter = _adapter(engine, study)
    fields = getattr(adapter, 'FIELD_SCHEMA', _BAND_FIELDS if engine == 'photonic_bands' else [])
    if isinstance(fields, dict):
        fields = fields.get(study, [])
    result = copy.deepcopy(fields)
    for field in result:
        field.setdefault('required', False)
        field.setdefault('unit', '')
        field.setdefault('section', 'inputs')
    return result


def validate_workspace_drafts(value):
    """Keep unfinished text verbatim; physical validation belongs to Run."""
    from research_simulation import _json_object
    result = _json_object(value, 'Research workspace drafts')
    if result.get('schema_version', 1) != 1:
        raise ValueError('Unsupported research workspace draft version.')
    result.setdefault('schema_version', 1)
    for key in ('bands', 'studies', 'thermal'):
        if key in result and not isinstance(result[key], dict):
            raise ValueError('Research workspace '+key+' draft must be an object.')
    return result
