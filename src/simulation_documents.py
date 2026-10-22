"""Independent simulation documents and explicit, conservative input transfer.

The active document keeps the existing project shape for older readers.  The
document bank holds other simulation types; no mutable object is shared.
"""
from copy import deepcopy

STUDY_IDS = ('optical', 'fdtd', 'tools.index_shift', 'tools.fields', 'tools.sweep', 'tools.ai',
    'photonic_bands', 'photonic_bands.2d', 'photonic_bands.legume',
    'electrical', 'electrical.iv', 'electrical.cv', 'coupled',
    'sesame_transport', 'sesame_transport.2d', 'thermal', 'advanced_transport',
    'high_field_optics', 'pcsel.vertical', 'pcsel.cwt', 'pcsel.finite',
    'pcsel.beam', 'pcsel.aperture', 'pcsel.gme', 'pcsel.rcwa_poles',
    'pcsel_transport', 'pcsel_unitcell_transport', 'lumped_laser')
FINITE = {'optical', 'fdtd', 'tools.index_shift', 'tools.fields', 'electrical',
    'electrical.iv', 'electrical.cv', 'coupled', 'thermal', 'advanced_transport',
    'pcsel_unitcell_transport'}
FINITE.update(('tools.sweep','tools.ai'))
OPTICAL = {'optical', 'fdtd', 'tools.index_shift', 'tools.fields','tools.sweep','tools.ai'}


def study_id(value):
    if value not in STUDY_IDS:
        raise ValueError('Unknown simulation document: '+str(value))
    return value


def payload(project):
    result = deepcopy(project)
    result.pop('simulation_documents', None)
    return result


def read_bank(project, default='optical'):
    bank = project.get('simulation_documents')
    if bank is None:
        return study_id(default), {}
    if not isinstance(bank, dict) or bank.get('schema_version') != 1:
        raise ValueError('Unsupported simulation document bank.')
    active = study_id(bank.get('active'))
    documents = bank.get('documents', {})
    if not isinstance(documents, dict):
        raise ValueError('Simulation documents must be a mapping.')
    clean = {}
    for key, value in documents.items():
        study_id(key)
        if not isinstance(value, dict) or 'simulation_documents' in value:
            raise ValueError('Each simulation document must be a nonnested project.')
        clean[key] = deepcopy(value)
    return active, clean


def transfer_sections(source, destination):
    """Human-readable contract. Unsupported conversions deliberately have none."""
    study_id(source); study_id(destination)
    if source == destination:
        return []
    if source in FINITE and destination in FINITE:
        result = ['Device geometry', 'Materials and optical tables', 'Physical dimensions']
        if destination not in OPTICAL and destination != 'thermal':
            result.append('Contacts and doping')
        return result
    if source.startswith('photonic_bands') and destination.startswith('photonic_bands'):
        if (source == 'photonic_bands') != (destination == 'photonic_bands'):
            return []
        return ['Crystal geometry and material permittivities', 'Lattice vectors and length scale']
    if source.startswith('pcsel.') and destination.startswith('pcsel.'):
        return ['Layer stack and refractive indices', 'Crystal inclusions and lattice pitch']
    return []


def transfer_inputs(source, destination, source_id, destination_id):
    sections = transfer_sections(source_id, destination_id)
    if not sections:
        raise ValueError('These simulation types do not have a compatible structure format. Build the destination structure in its editor.')
    result = payload(destination)
    if source_id in FINITE and destination_id in FINITE:
        for key in ('materials', 'layers', 'patterns', 'device', 'electrical_materials',
                    'optical_constants', 'material_provenance'):
            if key in source:
                result[key] = deepcopy(source[key])
            else:
                result.pop(key, None)
        if result.get('device') and destination_id in OPTICAL | {'thermal'}:
            # Optical contact coatings remain physical optical geometry. Strip
            # their electrical conditions, rather than silently losing layers.
            if destination_id == 'thermal':
                result['device']['contacts'] = []
            else:
                result['device']['contacts'] = [row for row in result['device'].get('contacts', [])
                    if row.get('optical_thickness_um', 0) > 0]
                for row in result['device']['contacts']:
                    row.pop('voltage_V', None)
                    row['bias_scale']=0.
            result['device']['doping_regions'] = []
            for layer in result['device'].get('layers',[]):
                layer['donor_cm3']=0.;layer['acceptor_cm3']=0.
        if result.get('device'):
            for key in ('mesh','temperature_K'):
                if key in (destination.get('device') or {}):
                    result['device'][key]=deepcopy(destination['device'][key])
            referenced={row.get('material_id') for group in ('layers','shapes') for row in result['device'].get(group,[])}
            # The finite editor requires complete material records for these
            # stable IDs, including optical n/k. Unused library entries stay out.
            result['electrical_materials']=[row for row in result.get('electrical_materials',[]) if row.get('id') in referenced]
        for key in ('ax_um', 'ay_um', 'a1', 'a2', 'lattice', 'material_interpolations', 'optical_unit_cell'):
            if key in source.get('settings', {}):
                result.setdefault('settings', {})[key] = deepcopy(source['settings'][key])
        if destination_id not in OPTICAL | {'coupled'}:
            result.setdefault('settings', {}).pop('optical_unit_cell', None)
    else:
        namespace = result.setdefault('desktop_search', {}).setdefault('research_workspaces', {'schema_version': 1})
        state_key = 'bands' if source_id.startswith('photonic_bands') else 'model_pcsel_research'
        incoming = source.get('desktop_search', {}).get('research_workspaces', {}).get(state_key, {})
        current = namespace.setdefault(state_key, {})
        keys = ('lattice', 'geometry', 'object_ids', 'epsilons') if state_key == 'bands' else ()
        for key in keys:
            if key in incoming: current[key] = deepcopy(incoming[key])
        field_keys = ('reference_length_um', 'background_epsilon') if state_key == 'bands' else (
            'lattice_nm', 'inclusion_index', 'top_index', 'bottom_index')
        for key in field_keys:
            if key in incoming.get('fields', {}):
                current.setdefault('fields', {})[key] = deepcopy(incoming['fields'][key])
        if state_key == 'model_pcsel_research':
            for key in ('layers', 'shapes'):
                if key in incoming.get('structured', {}):
                    current.setdefault('structured', {})[key] = deepcopy(incoming['structured'][key])
        # A changed geometry cannot continue claiming the old paper identity.
        current.pop('benchmark_request', None)
    result.pop('benchmark_request', None)
    # Saved geometry-bound execution options must be regenerated from the new
    # device at Run. They are historical outputs, not transferred inputs.
    for key in ('electrical','coupled'):
        options=result.get('desktop_search',{}).get(key)
        if isinstance(options,dict) and options.get('model')=='custom_device':
            options['device']=deepcopy(result.get('device'))
            options['material_library']=deepcopy(result.get('electrical_materials'))
    return result
