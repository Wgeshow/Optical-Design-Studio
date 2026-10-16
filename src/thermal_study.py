"""Standalone prescribed-heat jobs on the current editable project device."""
from __future__ import annotations

import copy
from pathlib import Path

CAPABILITIES = dict(engine='thermal', label='Steady heat flow', studies=[dict(id='steady_state', label='Prescribed heat')],
    dimensions=[3], geometry=['current_device'], outputs=['temperature', 'heat_density', 'energy_balance'],
    limitations=['Prescribed power with sourced constant isotropic conductivity; no current-derived heat or temperature feedback.'],
    optional_runtime=False)
FIELD_SCHEMA = [
    dict(path='power_by_layer_W', label='Heat supplied to each layer', type='object', required=True, unit='W', section='heat_sources'),
    dict(path='conductivity', label='Material conductivity and source', type='object', required=True, unit='W/(m K)', section='materials'),
    dict(path='boundaries', label='Fixed-temperature or convection faces', type='object', required=True, unit='', section='boundaries'),
    dict(path='ambient_temperature_K', label='Reference temperature', type='number', required=False, default=300., unit='K', section='boundaries'),
    dict(path='void_conductivity_W_mK', label='Void conductivity', type='number', required=False, unit='W/(m K)', section='materials'),
    dict(path='temperature_limit_K', label='Material validity limit', type='number', required=False, unit='K', section='validity'),
]


def prepare(project, settings):
    from electrical_thermal import validate_thermal
    from electrical_material_library import builtin_materials
    if not isinstance(project, dict) or not isinstance(project.get('device'), dict):
        raise ValueError('Create an editable device in Structure before calculating heat flow.')
    if not isinstance(settings, dict):
        raise ValueError('Thermal study inputs must be an object.')
    device = copy.deepcopy(project['device'])
    materials = copy.deepcopy(project.get('electrical_materials', builtin_materials()))
    config = validate_thermal(dict(settings, enabled=True), materials, device)
    return dict(schema_version=1, device=device, material_library=materials, thermal=config)


def execute(prepared, directory, emit=lambda event: None, cancelled=lambda: False):
    from electrical_thermal import execute_thermal
    directory = Path(directory).resolve()
    result = execute_thermal(dict(options=prepared), directory, prepared['thermal'], emit, cancelled)
    # Results stay portable when the library is exported to another computer.
    for key in ('volume_npz', 'summary_json'):
        if result.get(key):
            result[key] = str(Path(result[key]).relative_to(directory))
    return result
