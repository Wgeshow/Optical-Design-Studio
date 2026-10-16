"""Field-addressed input issues shared by research editors and Run preflight."""
from __future__ import annotations

import copy
import math


def _get(value, path):
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def validate_request(project, options):
    from research_catalog import field_schema
    from research_simulation import prepare_research_job, validate_research_options
    engine = options.get('engine') if isinstance(options, dict) else None
    workspace = {'photonic_bands': 'photonic_bands', 'thermal': 'thermal'}.get(engine, 'research_studies')
    issues = []

    def typed(rows):
        from input_diagnostics import normalize_diagnostic
        result = [normalize_diagnostic(row, workspace=workspace) for row in rows]
        for row in result:
            row.setdefault('model_id', engine)
        return result

    def issue(code, message, field='', section='inputs', units='', object_id=None):
        from input_diagnostics import diagnostic
        issues.append(diagnostic(message, code=code, severity='error', workspace=workspace,
            section=section, object_id=object_id or '', field=field, units=units, model_id=engine))

    try:
        cfg = validate_research_options(options)
    except ValueError as exc:
        if getattr(exc, 'diagnostics', None):
            return typed(exc.diagnostics)
        issue('research.selection', str(exc), 'engine', 'study')
        return issues
    for spec in field_schema(cfg['engine'], cfg['study']):
        path = spec['path']
        value = _get(cfg['settings'], path)
        missing = value is None or value == ''
        if missing and spec.get('required') and 'default' not in spec:
            issue('research.required', 'Enter '+spec['label']+'.', path, spec['section'], spec['unit'])
            continue
        if missing:
            continue
        kind = spec.get('type')
        valid = True
        if kind in ('number', 'integer'):
            try:
                number = float(value)
                valid = not isinstance(value, bool) and math.isfinite(number) and (kind != 'integer' or number == int(number))
            except (TypeError, ValueError, OverflowError):
                valid = False
        elif kind in ('array', 'matrix', 'objects', 'numbers'):
            valid = isinstance(value, list)
        elif kind == 'object':
            valid = isinstance(value, dict)
        elif kind == 'choice' and spec.get('options'):
            valid = value in spec['options']
        if not valid:
            issue('research.field_type', 'Enter a valid '+spec['label']+'.', path, spec['section'], spec['unit'])
    if issues:
        return issues
    try:
        prepare_research_job(copy.deepcopy(project), cfg)
    except ValueError as exc:
        if getattr(exc, 'diagnostics', None):
            return typed(exc.diagnostics)
        # A solver can report an exact address. Untyped legacy errors target the
        # owning input editor, never guess a field from words in its message.
        field = getattr(exc, 'field', getattr(exc, 'field_path', ''))
        issue(getattr(exc, 'code', 'research.physical_inputs'), str(exc), field,
              getattr(exc, 'section', 'inputs'), getattr(exc, 'units', ''), getattr(exc, 'object_id', None))
    return issues
