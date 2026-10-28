"""Project the historical mixed setup catalog into the real S4 workspace.

Meep owns FDTDPage and its independent document. Keeping this projection separate
from the saved schema preserves older projects without exposing a false engine
toggle or applying a Meep draft to an RCWA calculation.
"""
from copy import deepcopy


def _condition(value):
    if not isinstance(value, dict):
        return value
    if value.get('key') == 'ui.optical.engine':
        if 'equals' in value:
            return value['equals'] == 's4'
        if 'not_equals' in value:
            return value['not_equals'] != 's4'
    for operator in ('all', 'any'):
        if operator in value:
            children = [_condition(item) for item in value[operator]]
            decisive = False if operator == 'all' else True
            if any(item is decisive for item in children):
                return decisive
            children = [item for item in children if item is not (not decisive)]
            return {operator: children} if children else not decisive
    return deepcopy(value)


def s4_setup_plan(plan):
    """Keep every supported S4 input; remove Meep-only cards/rows/actions."""
    def project(node):
        if isinstance(node, list):
            return [result for child in node if (result := project(child)) is not None]
        if not isinstance(node, dict):
            return node
        key = str(node.get('key', ''))
        target = str(node.get('target', ''))
        if key.startswith('search.fdtd.') or 'meep' in key or 'meep' in target:
            return None
        result = {}
        for name, value in node.items():
            if name in ('visible_when', 'enabled_when'):
                condition = _condition(value)
                if name == 'visible_when' and condition is False:
                    return None
                if condition is not True:
                    result[name] = condition
            else:
                result[name] = project(value)
        if key == 'ui.optical.engine':
            result.update(widget='readonly', label='Optical solver', default='s4')
        return result

    result = project(deepcopy(plan))
    for mode in result['modes'].values():
        for tab in mode['tabs']:
            tab['cards'] = [card for card in tab.get('cards', [])
                            if card.get('fields') or card.get('actions') or card.get('embedded_editor')]
            if tab['id'] == 'optical.overview':
                tab['purpose'] = 'S4 periodic RCWA: build the cell, set illumination and wavelength or angle samples, then choose Fourier accuracy and outputs.'
                card = next(card for card in tab['cards'] if card['id'] == 'optical.overview.study')
                card['title'] = 'S4 optical study'
                card.setdefault('actions', []).append(dict(id='optical.open-meep',
                    label='Open separate Meep / FDTD study', type='route', target='engine.meep'))
            elif tab['id'] == 'coupled.optical-setup':
                tab['title'] = 'S4 optical setup'
                tab['purpose'] = 'Configure the S4 response used for each electrical bias. Meep has a separate time-domain workspace; electrical-to-Meep coupling is not implemented.'
    return result


def require_s4_preset(payload):
    """Reject an engine-changing preset before any active draft is replaced."""
    if not isinstance(payload, dict) or not isinstance(payload.get('values', {}), dict):
        raise ValueError('Choose a simulation setup preset with an object of UI values.')
    if payload.get('values', {}).get('ui.optical.engine', 's4') != 's4':
        raise ValueError('This preset belongs to Meep. Open the separate Meep / FDTD study; S4 inputs and this device have been retained.')


def meep_preset_options(payload):
    """Read only the Meep settings from a current or legacy setup preset."""
    if (not isinstance(payload, dict) or payload.get('kind') != 'ods_simulation_setup'
            or payload.get('schema_version') != 1 or not isinstance(payload.get('fdtd'), dict)):
        raise ValueError('Choose a simulation setup preset containing Meep / FDTD settings.')
    from fdtd_model import validate_options
    return validate_options(payload['fdtd'])
