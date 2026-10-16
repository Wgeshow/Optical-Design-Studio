"""Portable input diagnostics with explicit navigation targets.

Field paths identify saved inputs; object IDs identify editable objects. Display
messages are never parsed to decide where a user should be sent.
"""
from __future__ import annotations

import hashlib
import json


def diagnostic(message, *, code='invalid_input', workspace='', section='',
               field='', object_id='', revision='', units='', severity='error',
               requirement='', **extra):
    if severity not in ('error', 'warning', 'information'):
        raise ValueError('Unknown diagnostic severity')
    text = lambda value: '' if value is None else str(value)
    result = dict(code=text(code), message=text(message), severity=severity,
                  workspace=text(workspace), section=text(section), field=text(field),
                  object_id=text(object_id), revision=text(revision), units=text(units),
                  requirement=text(requirement))
    result.update(extra)
    identity = [result[key] for key in ('code', 'workspace', 'section', 'field', 'object_id')]
    identity.extend(result.get(key,'') for key in ('column','model_id','study_id'))
    result['id'] = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:20]
    return result


def normalize_diagnostic(value, *, workspace='', revision=''):
    """Accept legacy key/tab records without guessing a target from prose."""
    if not isinstance(value, dict):
        return diagnostic(str(value), workspace=workspace, revision=revision)
    fields = dict(value)
    message = fields.pop('message', 'Check this input.')
    fields.pop('id', None)
    fields.setdefault('field', fields.get('key', ''))
    fields.setdefault('section', fields.get('tab', ''))
    if not fields.get('workspace'):fields['workspace']=workspace
    if not fields.get('revision'):fields['revision']=revision
    return diagnostic(message, **fields)


class InputValidationError(ValueError):
    """A validation failure whose exact input destinations survive dispatch."""
    def __init__(self, diagnostics):
        self.diagnostics = [normalize_diagnostic(row) for row in diagnostics]
        super().__init__('\n'.join(row['message'] for row in self.diagnostics))

