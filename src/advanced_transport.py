"""Explicit optional FD transport with conductor and finite-resistance interfaces."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import numpy as np

from input_diagnostics import diagnostic, InputValidationError
from photonic_bands import _number

CAPABILITIES = dict(engine='advanced_transport', studies=[dict(id='finite_contact', label='Finite contacts and conductor transport')],
    dimensions=[3], geometry=['current editable device and contacts'],
    outputs=['potential and carrier maps', 'conserved face currents', 'terminal current and charge', 'electrochemical heat and temperature feedback',
             'nonlocal Gamma pair sources and transfer currents', 'dopant-screening gap shift', 'high-field optical sensitivity maps'],
    optional_mechanisms=['recombination','thermal','temperature_feedback','nonlocal_tunnelling','bandgap_narrowing','high_field_optics'],
    limitations=['Experimental parabolic-band FD transport', 'Local resistivity interfaces; no thermionic barrier law',
                 'All added laws require explicit parameters; no full carrier-energy or calibrated quantum/multiband model'], optional_runtime='DEVSIM')
FIELD_SCHEMA = [
    dict(path='biases_V', label='Bias sequence', type='numbers', required=True, unit='V', section='Bias'),
    dict(path='swept_contact_id', label='Swept device contact', type='string', required=True, section='Bias'),
    dict(path='unipolar_conductors', label='Explicit electron-only conductors and source notes', type='object', required=False, default={}, section='Materials'),
    dict(path='contacts', label='Contact carrier resistivities', type='object', required=False, default={}, unit='ohm cm²', section='Contacts'),
    dict(path='interfaces', label='Material-interface carrier resistivities', type='objects', required=False, default=[], unit='ohm cm²', section='Interfaces'),
    dict(path='recombination', label='Material recombination and surface coefficients', type='object', required=False, default={}, section='Recombination'),
    dict(path='thermal', label='Heat from electrochemical dissipation', type='object', required=False, section='Heat'),
    dict(path='temperature_feedback', label='Material-temperature feedback laws and convergence', type='object', required=False, section='Heat'),
    dict(path='nonlocal_tunnelling', label='Straight-column Gamma tunnelling paths', type='object', required=False, section='Tunnelling'),
    dict(path='high_field_optics', label='Cell-resolved high-field optical sensitivity', type='object', required=False, section='Optical response'),
    dict(path='bandgap_narrowing', label='Dopant-screening band-gap sensitivity', type='object', required=False, section='Materials'),
    dict(path='parameter_source', label='Model assumption or parameter source', type='string', required=True, section='Model'),
    dict(path='max_bias_step_V', label='Maximum continuation step', type='number', required=False, default=.05, unit='V', section='Solver'),
]


def input_template(field, project):
    """Create explicit empty controls; never turn a missing coefficient into a fit."""
    from electrical_material_library import builtin_materials
    library={row['id']:row for row in project.get('electrical_materials',builtin_materials())}
    device=project.get('device',{})
    ids={row.get('material_id') for row in device.get('layers',[]) if row.get('enabled',True)}
    ids|={row.get('material_id') for row in device.get('shapes',[]) if row.get('enabled',True) and row.get('operation')!='void'}
    ids={key for key in ids if key in library}
    sem=sorted(key for key in ids if library[key]['kind']=='semiconductor')
    mobile=sorted(key for key in ids if library[key]['kind']!='dielectric')
    if field=='nonlocal_tunnelling':
        return dict(axis='z',path_min_um=None,path_max_um=None,hole_reservoir_um=None,electron_reservoir_um=None,
            transverse_mass_ratio=None,energy_order=16,transverse_order=8,scale=1.,source='',
            materials={key:dict(electron_gamma_mass_ratio=None,hole_mass_ratio=None) for key in sem})
    if field=='high_field_optics':
        return dict(wavelengths_nm=[],energy_order=4096,energy_upper_eV=12.,
            materials={key:dict(electron_mass_ratio=None,hole_mass_ratios=[],absorption_prefactor_cm1_sqrt_eV=None,reference_gap_eV=None,source='') for key in sem})
    if field=='temperature_feedback':
        return dict(maximum_iterations=40,temperature_tolerance_K=.01,relaxation=.5,
            temperature_models={key:dict(Nc_exponent=None,Nv_exponent=None,electron_mobility_exponent=None,hole_mobility_exponent=None,
                minimum_temperature_K=None,maximum_temperature_K=None,source='') for key in mobile},conductivity_exponents={})
    if field=='recombination':
        return {key:dict(model='fd_detailed_balance_proxy',tau_n_s=None,tau_p_s=None,trap_energy_eV=None,B_cm3_s=0.,Cn_cm6_s=0.,Cp_cm6_s=0.,surface_velocity_cm_s=0.,source='') for key in sem}
    if field=='bandgap_narrowing':
        return {key:dict(model='thomas_fermi_dopant_screening',scale=None,conduction_partition=None,source='') for key in sem}
    if field=='thermal':
        return dict(source='electrochemical_dissipation',conductivity={key:dict(value_W_mK=None,source='') for key in sorted(ids)},
            power_by_layer_W={},void_conductivity_W_mK=None,ambient_temperature_K=device.get('temperature_K',300.),boundaries={},temperature_limit_K=None)
    if field=='contacts':
        return {row['id']:dict(electron_resistivity_ohm_cm2=None,hole_resistivity_ohm_cm2=None,source='') for row in device.get('contacts',[]) if row.get('enabled',True)}
    if field=='unipolar_conductors':
        return {key:'' for key in mobile if library[key]['kind']=='conductor'}
    if field=='interfaces':return [dict(materials=[],electron_resistivity_ohm_cm2=None,hole_resistivity_ohm_cm2=None,source='')]
    raise ValueError('No input template for '+str(field))


def _invalid(message, field, section, object_id=''):
    return InputValidationError([diagnostic(message, workspace='advanced_transport', field=field, section=section, object_id=object_id)])


def _source(value, field):
    if not isinstance(value, str) or not value.strip():
        raise _invalid('Provide a source or explicit assumption for '+field, field, 'Model')
    return value.strip()


def prepare(project, settings):
    from electrical_material_library import builtin_materials
    from custom_electrical_solver import build_mesh
    from electrical_transport import validate_transport
    if not isinstance(project, dict) or not isinstance(project.get('device'), dict):
        raise _invalid('Create an editable device first', 'device', 'Structure')
    if not isinstance(settings, dict) or set(settings)-{'biases_V', 'swept_contact_id', 'unipolar_conductors', 'contacts', 'interfaces', 'recombination', 'thermal', 'temperature_feedback', 'nonlocal_tunnelling', 'high_field_optics', 'bandgap_narrowing', 'parameter_source', 'max_bias_step_V'}:
        raise _invalid('Unsupported advanced transport settings', '', 'Model')
    device = copy.deepcopy(project['device'])
    library = copy.deepcopy(project.get('electrical_materials', builtin_materials()))
    mesh = build_mesh(device, library)
    available_contacts = {row['object']['id'] for row in mesh['contacts']}
    materials = {mesh['materials'][index]['id']: mesh['materials'][index] for index in np.unique(mesh['material_index'])}
    source = _source(settings.get('parameter_source'), 'parameter_source')
    swept = settings.get('swept_contact_id')
    if swept not in available_contacts:
        raise _invalid('Select an existing enabled device contact to sweep', 'swept_contact_id', 'Bias')
    biases = settings.get('biases_V')
    if not isinstance(biases, list) or not biases:
        raise _invalid('Provide an explicit bias sequence', 'biases_V', 'Bias')
    biases = [_number(v, 'biases_V') for v in biases]
    conductors = settings.get('unipolar_conductors', {})
    if not isinstance(conductors, dict):
        raise _invalid('Conductor selections must map material IDs to source notes', 'unipolar_conductors', 'Materials')
    conductors = {key: _source(value, 'unipolar_conductors.'+key) for key, value in conductors.items()}
    for key in conductors:
        if key not in materials or materials[key]['kind'] != 'conductor':
            raise _invalid('Selected electron-only material is not a conductor in this mesh', 'unipolar_conductors.'+key, 'Materials', key)
        selected = mesh['material_index'] == next(i for i, row in enumerate(mesh['materials']) if row['id'] == key)
        if np.any(mesh['donor_cm3'][selected] <= mesh['acceptor_cm3'][selected]):
            raise _invalid('Electron-only conductors require positive net donor density in every occupied cell', 'unipolar_conductors.'+key, 'Materials', key)
    def resistance(raw, field):
        if not isinstance(raw, dict) or set(raw) != {'electron_resistivity_ohm_cm2', 'hole_resistivity_ohm_cm2', 'source'}:
            raise _invalid('Supply electron and hole resistivity plus a source note', field, 'Contacts')
        row = {'source': _source(raw['source'], field+'.source')}
        for key in ('electron_resistivity_ohm_cm2', 'hole_resistivity_ohm_cm2'):
            value = _number(raw[key], key)
            if value < 0:
                raise _invalid('Resistivity must be nonnegative; zero selects an ideal interface', field+'.'+key, 'Contacts')
            row[key] = value
        return row
    contacts = settings.get('contacts', {})
    if not isinstance(contacts, dict) or set(contacts)-available_contacts:
        raise _invalid('Contact resistivity references an absent or disabled device contact', 'contacts', 'Contacts')
    contacts = {key: resistance(value, 'contacts.'+key) for key, value in contacts.items()}
    for contact in mesh['contacts']:
        key = contact['object']['id']
        if key in contacts and contacts[key]['hole_resistivity_ohm_cm2'] > 0:
            kinds = [mesh['materials'][index]['kind'] for index in mesh['material_index'].ravel()[contact['ids']]]
            if 'semiconductor' not in kinds:
                raise _invalid('An electron-only conductor contact has no hole channel; set hole resistivity to zero', 'contacts.'+key+'.hole_resistivity_ohm_cm2', 'Contacts', key)
    interfaces = settings.get('interfaces', [])
    if not isinstance(interfaces, list):
        raise _invalid('Interfaces must be a list of material-pair resistivities', 'interfaces', 'Interfaces')
    rows, pairs = [], set()
    for index, raw in enumerate(interfaces):
        field = 'interfaces.'+str(index)
        if not isinstance(raw, dict):
            raise _invalid('Interface needs material pair and resistivity fields', field, 'Interfaces')
        pair = raw.get('materials')
        if not isinstance(pair, list) or len(pair) != 2 or pair[0] == pair[1] or any(key not in materials for key in pair):
            raise _invalid('Select two different occupied materials for the interface', field+'.materials', 'Interfaces')
        if any(materials[key]['kind'] == 'dielectric' for key in pair):
            raise _invalid('Carrier interface resistance requires two mobile materials; dielectric faces block carrier transport', field+'.materials', 'Interfaces')
        first, second = [next(i for i, material in enumerate(mesh['materials']) if material['id'] == key) for key in pair]
        adjacent = False
        for axis in range(3):
            left, right = [slice(None)]*3, [slice(None)]*3
            left[axis], right[axis] = slice(None, -1), slice(1, None)
            a, b = mesh['material_index'][tuple(left)], mesh['material_index'][tuple(right)]
            adjacent |= bool(np.any(((a == first)&(b == second))|((a == second)&(b == first))))
        if not adjacent:
            raise _invalid('The selected materials share no resolved mesh face; refine the geometry or remove this interface', field+'.materials', 'Interfaces')
        identity = tuple(sorted(pair))
        if identity in pairs:
            raise _invalid('Material-interface pairs must not repeat', field+'.materials', 'Interfaces')
        pairs.add(identity)
        row = dict(resistance({k:v for k,v in raw.items() if k != 'materials'}, field), materials=pair)
        if row['hole_resistivity_ohm_cm2'] > 0 and any(materials[key]['kind'] != 'semiconductor' for key in pair):
            raise _invalid('An interface touching an electron-only conductor has no hole channel; set hole resistivity to zero', field+'.hole_resistivity_ohm_cm2', 'Interfaces')
        rows.append(row)
    recombination = settings.get('recombination', {})
    if not isinstance(recombination, dict):
        raise _invalid('Recombination must map semiconductor material IDs to explicit coefficients', 'recombination', 'Recombination')
    recomb = {}
    fields = {'model', 'tau_n_s', 'tau_p_s', 'trap_energy_eV', 'B_cm3_s', 'Cn_cm6_s', 'Cp_cm6_s', 'surface_velocity_cm_s', 'source'}
    for key, raw in recombination.items():
        if key not in materials or materials[key]['kind'] != 'semiconductor' or not isinstance(raw, dict) or set(raw)-fields:
            raise _invalid('Recombination requires an occupied semiconductor and supported coefficient fields', 'recombination.'+key, 'Recombination', key)
        if raw.get('model') != 'fd_detailed_balance_proxy':
            raise _invalid('Select the explicit fd_detailed_balance_proxy approximation; this is not a calibrated degenerate trap law', 'recombination.'+key+'.model', 'Recombination', key)
        row = dict(model=raw['model'], source=_source(raw.get('source'), 'recombination.'+key+'.source'))
        has_tau = 'tau_n_s' in raw or 'tau_p_s' in raw
        if has_tau:
            for field in ('tau_n_s', 'tau_p_s'):
                row[field] = _number(raw.get(field), field, positive=True)
            row['trap_energy_eV'] = _number(raw.get('trap_energy_eV', 0.), 'trap_energy_eV')
            from scipy.constants import k, e
            props = materials[key]['properties']
            intrinsic_above_valence = props['bandgap_eV']/2 + k*mesh['device']['temperature_K']/(2*e)*np.log(props['Nv_cm3']/props['Nc_cm3'])
            if not 0 < intrinsic_above_valence + row['trap_energy_eV'] < props['bandgap_eV']:
                raise _invalid('The trap energy relative to the intrinsic level lies outside this material band gap', 'recombination.'+key+'.trap_energy_eV', 'Recombination', key)
        elif 'trap_energy_eV' in raw:
            raise _invalid('A trap energy needs both carrier lifetimes', 'recombination.'+key+'.trap_energy_eV', 'Recombination', key)
        for field in ('B_cm3_s', 'Cn_cm6_s', 'Cp_cm6_s', 'surface_velocity_cm_s'):
            row[field] = _number(raw.get(field, 0.), field)
            if row[field] < 0:
                raise _invalid('Recombination coefficients must be nonnegative', 'recombination.'+key+'.'+field, 'Recombination', key)
        recomb[key] = row
    # An isolated hole component needs either an ohmic reservoir or an explicit
    # net-pair law tying its quasi-Fermi energy to the electron population.
    from scipy.ndimage import label
    hole_mask = np.take([row['kind'] == 'semiconductor' for row in mesh['materials']], mesh['material_index'])
    mobile_mask = np.take([row['kind'] != 'dielectric' for row in mesh['materials']], mesh['material_index'])
    exposed = np.zeros(mesh['shape'], bool)
    for axis in range(3):
        for sign in (-1, 1):
            neighbor = np.roll(mobile_mask, sign, axis=axis)
            outer = [slice(None)]*3
            outer[axis] = 0 if sign == 1 else -1
            neighbor[tuple(outer)] = False
            exposed |= ~neighbor
    components, count = label(hole_mask)
    contacted = set(components.ravel()[np.concatenate([row['ids'] for row in mesh['contacts']])].tolist())
    for component in range(1, count+1):
        if component in contacted:
            continue
        keys = {mesh['materials'][index]['id'] for index in np.unique(mesh['material_index'][components == component])}
        pair_anchored = False
        for key in keys & set(recomb):
            row = recomb[key]
            material_index = next(i for i, material in enumerate(mesh['materials']) if material['id'] == key)
            has_surface = np.any(exposed & (components == component) & (mesh['material_index'] == material_index))
            pair_anchored |= 'tau_n_s' in row or any(row[field] > 0 for field in ('B_cm3_s','Cn_cm6_s','Cp_cm6_s')) or (has_surface and row['surface_velocity_cm_s'] > 0)
        if not pair_anchored:
            raise _invalid('A semiconductor hole component has no ohmic contact or explicit pair-recombination law; its carrier population is not defined', 'recombination', 'Recombination', sorted(keys)[0])
    advanced = dict(unipolar_conductors=conductors, contacts=contacts, interfaces=rows, recombination=recomb, parameter_source=source)
    if settings.get('nonlocal_tunnelling') is not None:
        from nonlocal_tunnelling import validate_tunnelling
        advanced['nonlocal_tunnelling'] = validate_tunnelling(settings['nonlocal_tunnelling'], mesh)
    if settings.get('bandgap_narrowing') is not None:
        from bandgap_narrowing import validate_narrowing
        advanced['bandgap_narrowing'] = validate_narrowing(settings['bandgap_narrowing'], {key for key,row in materials.items() if row['kind']=='semiconductor'})
    transport = validate_transport(dict(mode='semiconductor_dd', statistics='fermi_dirac',
        heterojunction=dict(model='ideal_quasi_fermi', parameter_source=source),
        max_bias_step_V=_number(settings.get('max_bias_step_V', .05), 'max_bias_step_V', positive=True)))
    from advanced_transport_graph import _validate_graph_materials
    _validate_graph_materials(mesh, transport, advanced)
    result = dict(schema_version=1, device=device, material_library=library, biases_V=biases,
                  swept_contact_id=swept, transport=transport, advanced=advanced)
    if settings.get('thermal') is not None:
        from electrical_thermal import validate_thermal
        raw = settings['thermal']
        if not isinstance(raw, dict) or raw.get('source') != 'electrochemical_dissipation':
            raise _invalid('Explicitly select source=electrochemical_dissipation for this approximate thermal coupling', 'thermal.source', 'Heat')
        result['thermal'] = validate_thermal(dict({k:v for k,v in raw.items() if k != 'source'}, enabled=True), library, device)
    if settings.get('temperature_feedback') is not None:
        from electrical_temperature import validate_feedback
        if 'thermal' not in result:
            raise _invalid('Temperature feedback needs explicit thermal source, conductivity and boundary inputs', 'thermal', 'Heat')
        active = {mesh['materials'][index]['id'] for index in np.unique(mesh['material_index']) if mesh['materials'][index]['kind'] != 'dielectric'}
        result['temperature_feedback'] = validate_feedback(settings['temperature_feedback'], active, mesh['device']['temperature_K'])
        occupied = {mesh['materials'][index]['id'] for index in np.unique(mesh['material_index'])}
        if set(result['temperature_feedback']['conductivity_exponents'])-occupied:
            raise _invalid('Thermal conductivity exponent references an absent material', 'temperature_feedback.conductivity_exponents', 'Heat')
    if settings.get('high_field_optics') is not None:
        from high_field_optics import validate_material
        raw = settings['high_field_optics']
        if not isinstance(raw, dict) or set(raw)-{'materials', 'wavelengths_nm', 'energy_order', 'energy_upper_eV'}:
            raise _invalid('High-field optical maps need materials,wavelengths_nm,energy_order,energy_upper_eV', 'high_field_optics', 'Optical response')
        if not isinstance(raw.get('materials'), dict) or not raw['materials'] or any(key not in materials or materials[key]['kind']!='semiconductor' for key in raw['materials']):
            raise _invalid('Select occupied semiconductor optical materials', 'high_field_optics.materials', 'Optical response')
        if not isinstance(raw.get('wavelengths_nm'), list) or not raw['wavelengths_nm']:
            raise _invalid('Supply optical map wavelengths', 'high_field_optics.wavelengths_nm', 'Optical response')
        from photonic_bands import _integer
        optical = dict(materials={key:validate_material(value) for key,value in raw['materials'].items()},
            wavelengths_nm=[_number(v,'wavelengths_nm',positive=True) for v in raw['wavelengths_nm']],
            energy_order=_integer(raw.get('energy_order',4096),'energy_order',128),energy_upper_eV=_number(raw.get('energy_upper_eV',12.),'energy_upper_eV',positive=True))
        if max(1239.8419843320026/np.asarray(optical['wavelengths_nm'])) >= optical['energy_upper_eV']:
            raise _invalid('Optical KK upper energy must exceed all photon energies', 'high_field_optics.energy_upper_eV', 'Optical response')
        result['high_field_optics'] = optical
    return result


def _heat_state(prepared, state, cancelled):
    if prepared.get('thermal') is None:
        return None
    from electrical_thermal import _mesh_inputs, solve_steady_heat
    mesh = state['mesh']; config = prepared['thermal']
    conductivity, prescribed_heat = _mesh_inputs(mesh, config)
    temperature = np.asarray(state['temperature_K']).reshape(mesh['shape'])
    for material, exponent in prepared.get('temperature_feedback', {}).get('conductivity_exponents', {}).items():
        index = next(i for i, row in enumerate(mesh['materials']) if row['id'] == material)
        selected = mesh['material_index'] == index
        conductivity[selected] *= (temperature[selected]/mesh['device']['temperature_K'])**exponent
    heat = np.asarray(state['electrochemical_heat_density_W_m3']).reshape(mesh['shape'])
    return solve_steady_heat(mesh['faces'], conductivity, prescribed_heat+heat, config['boundaries'],
        reference_temperature_K=config['ambient_temperature_K'], cancelled=cancelled)


def _iter_coupled_states(prepared, emit, cancelled):
    from advanced_transport_graph import iter_advanced_states
    feedback = prepared.get('temperature_feedback')
    if feedback is None:
        for state in iter_advanced_states(prepared, prepared['transport'], emit, cancelled):
            state['thermal_result'] = _heat_state(prepared, state, cancelled)
            yield state
        return
    from custom_electrical_solver import build_mesh
    mesh = build_mesh(prepared['device'], prepared['material_library'])
    temperature = np.full(mesh['shape'], mesh['device']['temperature_K'])
    for bias in prepared['biases_V']:
        converged = False; validity_reason = None
        for iteration in range(feedback['maximum_iterations']):
            if cancelled():
                raise InterruptedError('Electrothermal feedback cancelled')
            options = dict(prepared, biases_V=[bias], temperature_field_K=temperature.tolist())
            iterator = iter_advanced_states(options, prepared['transport'], emit, cancelled)
            try:
                state = next(iterator)
            finally:
                iterator.close()
            thermal = _heat_state(prepared, state, cancelled)
            target = thermal['temperature_K']
            difference = float(np.max(np.abs(target-temperature)))
            emit(dict(phase='electrothermal', progress=(iteration+1)/feedback['maximum_iterations'],
                message=f'Temperature feedback {iteration+1}: change {difference:.5g} K'))
            for material, model in feedback['temperature_models'].items():
                selected = mesh['material_index'] == next(i for i,row in enumerate(mesh['materials']) if row['id']==material)
                if np.any(target[selected] < model['minimum_temperature_K']) or np.any(target[selected] > model['maximum_temperature_K']):
                    validity_reason = 'Heat solution is outside the supplied temperature-law validity range for '+material
                    break
            if validity_reason or difference <= feedback['temperature_tolerance_K']:
                converged = not validity_reason
                break
            temperature = (1-feedback['relaxation'])*temperature+feedback['relaxation']*target
        state['thermal_result'] = thermal
        state['temperature_feedback'] = dict(status='validity_limit' if validity_reason else ('complete' if converged else 'unconverged'),
            iterations=iteration+1, max_temperature_fixed_point_error_K=difference,
            tolerance_K=feedback['temperature_tolerance_K'], reason=validity_reason,
            limitation='Local DOS/mobility/Varshni and Fourier conduction feedback only; no Seebeck, Peltier, carrier-energy or emitted-photon balance.')
        yield state
        if not converged:
            return
        temperature = target


def _array_axis_metadata(arrays, shape):
    axes = [dict(name=axis, coordinate=axis+'_um', unit='µm') for axis in ('x','y','z')]
    units = {'potential_V':'V','electrons_cm3':'cm^-3','holes_cm3':'cm^-3','donor_cm3':'cm^-3','acceptor_cm3':'cm^-3',
        'electron_quasi_fermi_eV':'eV','hole_quasi_fermi_eV':'eV','charge_density_C_m3':'C/m³','field_V_m':'V/m',
        'electron_current_density_A_m2':'A/m²','hole_current_density_A_m2':'A/m²',
        'electrochemical_heat_density_W_m3':'W/m³','thermal_heat_density_W_m3':'W/m³','thermal_conductivity_W_mK':'W/(m K)',
        'transport_temperature_K':'K','temperature_K':'K','effective_bandgap_eV':'eV','bandgap_narrowing_eV':'eV',
        'srh_recombination_cm3_s':'cm^-3/s','impact_generation_cm3_s':'cm^-3/s',
        'nonlocal_electron_generation_cm3_s':'cm^-3/s','nonlocal_hole_generation_cm3_s':'cm^-3/s',
        'high_field_absorption_cm1':'cm^-1','high_field_reference_absorption_cm1':'cm^-1','cell_volumes_m3':'m³'}
    metadata = {}
    for key, value in arrays.items():
        value = np.asarray(value)
        if value.shape[:3] != tuple(shape):
            continue
        record = dict(axes=list(axes), unit=units.get(key,'1'))
        if value.ndim == 4:
            if key.startswith('high_field_'):
                record['axes'].append(dict(name='Wavelength',coordinate='high_field_wavelengths_nm',unit='nm'))
            else:
                record['axes'].append(dict(name='Cartesian component (x=0, y=1, z=2)',coordinate='cartesian_component',unit='index'))
        metadata[key] = record
    return np.array(json.dumps(metadata,ensure_ascii=False))


def execute(prepared, directory, emit=lambda event: None, cancelled=lambda: False):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    summary = dict(status='partial', engine='advanced_transport', model_scope='finite_contact_fermi_transport', options=prepared, results=[], files=['advanced_transport_summary.json'])
    for index, state in enumerate(_iter_coupled_states(prepared, emit, cancelled)):
        mesh, graph = state['mesh'], state['graph']
        arrays = dict(x=mesh['axes'][0], y=mesh['axes'][1], z=mesh['axes'][2],
            x_um=mesh['axes'][0]*1e6,y_um=mesh['axes'][1]*1e6,z_um=mesh['axes'][2]*1e6,cartesian_component=np.arange(3),
            cell_volumes_m3=mesh['volume'], material_index=mesh['material_index'], layer_index=mesh['layer_index'],
            material_ids=np.array([row['id'] for row in mesh['materials']]), layer_ids=np.array([row['id'] for row in mesh['bounds']]),
            bias_V=state['bias_V'], transport_graph_edges=graph['edges'], transport_graph_node_xyz_m=graph['node_xyz_m'],
            transport_graph_node_volume_m3=graph['node_volume_m3'])
        for key in ('potential_V', 'electrons_cm3', 'holes_cm3', 'electron_quasi_fermi_eV', 'hole_quasi_fermi_eV', 'charge_density_C_m3',
                    'donor_cm3', 'acceptor_cm3', 'impact_generation_cm3_s', 'srh_recombination_cm3_s'):
            arrays[key] = np.asarray(state[key]).reshape(mesh['shape'])
        arrays['electrochemical_heat_density_W_m3'] = np.asarray(state['electrochemical_heat_density_W_m3']).reshape(mesh['shape'])
        arrays['transport_temperature_K'] = np.asarray(state['temperature_K']).reshape(mesh['shape'])
        for key in ('effective_bandgap_eV','bandgap_narrowing_eV','electron_reduced_fermi','hole_reduced_fermi','nonlocal_electron_generation_cm3_s','nonlocal_hole_generation_cm3_s'):
            arrays[key] = np.asarray(state[key]).reshape(mesh['shape'])
        if 'nonlocal_tunnelling' in state:
            tunnel = state['nonlocal_tunnelling']
            arrays['tunnelling_column_current_A_m2'] = tunnel['column_current_A_m2']
            transfer_file = 'tunnelling_transfers_'+str(index).zfill(4)+'.json'
            (directory/transfer_file).write_text(json.dumps(tunnel['transfers'], indent=2, allow_nan=False), encoding='utf-8')
            summary['files'].append(transfer_file)
        for key in ('field_V_m', 'electron_current_density_A_m2', 'hole_current_density_A_m2'):
            arrays[key] = np.asarray(state[key]).reshape(mesh['shape']+(3,))
        for key in ('edge_electron_current_A', 'edge_hole_current_A', 'edge_dissipation_W'):
            arrays[key] = np.asarray(state[key])
        thermal = state.get('thermal_result')
        if thermal is not None:
            arrays['temperature_K'] = thermal['temperature_K']
            arrays['thermal_heat_density_W_m3'] = thermal['heat_density_W_m3']
            arrays['thermal_conductivity_W_mK'] = thermal['conductivity_W_mK']
        filename = 'advanced_state_'+str(index).zfill(4)+'.npz'
        record = dict(bias_V=state['bias_V'], volume_npz=filename, checks=state['checks'])
        if 'temperature_feedback' in state:
            record['temperature_feedback'] = state['temperature_feedback']
        if thermal is not None:
            record['thermal_checks'] = thermal['checks']
            prefix = 'Iterated local material-temperature feedback with ' if prepared.get('temperature_feedback') else 'Frozen electrical state with '
            record['thermal_source_scope'] = prefix+'electrochemical dissipation of the solved face-resistance law; internal face watts split equally, contact watts deposited in adjacent device cells. No carrier-energy, Peltier/Seebeck or emitted-photon energy model.'
        # Save the solved electrical/thermal state before optional optical work.
        # A failed or cancelled optical stage must not discard the completed bias.
        if prepared.get('high_field_optics'):
            record['high_field_optics_status'] = 'pending'
        arrays['array_axes'] = _array_axis_metadata(arrays,mesh['shape'])
        np.savez_compressed(directory/filename, **arrays)
        summary['results'].append(record)
        summary['files'].append(filename)
        summary['limitations'] = state['limitations']
        (directory/'advanced_transport_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
        if prepared.get('high_field_optics'):
            from high_field_optics import response, LIMITATIONS as OPTICAL_LIMITATIONS
            optical = prepared['high_field_optics']; count=len(optical['wavelengths_nm'])
            outputs={key:np.zeros((int(np.prod(mesh['shape'])),count)) for key in ('delta_n','delta_k','interband_k','absorption_cm1','reference_absorption_cm1','kk_quadrature_error_estimate','kk_quadrature_warning_count')}
            selected_cells=np.zeros(int(np.prod(mesh['shape'])),bool)
            ids=mesh['material_index'].ravel()
            fields=np.linalg.norm(np.asarray(state['field_V_m']),axis=1)
            for material,params in optical['materials'].items():
                material_index=next(i for i,row in enumerate(mesh['materials']) if row['id']==material)
                cells=np.flatnonzero(ids==material_index);selected_cells[cells]=True
                for position,cell in enumerate(cells):
                    if cancelled():raise InterruptedError('High-field optical map cancelled')
                    try:
                        values=response(optical['wavelengths_nm'],state['effective_bandgap_eV'][cell],fields[cell],
                            state['electron_reduced_fermi'][cell],state['hole_reduced_fermi'][cell],state['temperature_K'][cell],params,
                            energy_order=optical['energy_order'],energy_upper_eV=optical['energy_upper_eV'])
                    except Exception as exc:
                        record.update(high_field_optics_status='failed', high_field_optics_error=str(exc))
                        (directory/'advanced_transport_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
                        raise
                    for key,value in values.items():outputs[key][cell]=value
                    emit(dict(phase='high_field_optics',progress=(position+1)/len(cells),message='Computing optical sensitivity for '+material))
            for key,values in outputs.items():arrays['high_field_'+key]=values.reshape(mesh['shape']+(count,))
            arrays['high_field_evaluated_mask']=selected_cells.reshape(mesh['shape'])
            arrays['high_field_wavelengths_nm']=optical['wavelengths_nm']
            summary['high_field_optical_limitations']=OPTICAL_LIMITATIONS
            record['high_field_optics_status']='complete'
            record['high_field_kk_quadrature_warning_count']=int(outputs['kk_quadrature_warning_count'].sum())
            summary['high_field_kk_quadrature_warning_count']=summary.get('high_field_kk_quadrature_warning_count',0)+record['high_field_kk_quadrature_warning_count']
            summary['high_field_optical_mask_semantics']='Only cells marked high_field_evaluated_mask have computed optical values; zeros outside the mask are storage placeholders.'
        arrays['array_axes'] = _array_axis_metadata(arrays,mesh['shape'])
        np.savez_compressed(directory/filename, **arrays)
        (directory/'advanced_transport_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    summary['status'] = 'complete'
    if any(row.get('temperature_feedback', {}).get('status') == 'unconverged' for row in summary['results']):
        summary['status'] = 'unconverged'
    elif any(row.get('temperature_feedback', {}).get('status') == 'validity_limit' for row in summary['results']):
        summary['status'] = 'validity_limit'
    if prepared.get('thermal') and prepared['thermal']['temperature_limit_K'] is not None:
        if any(row.get('thermal_checks', {}).get('maximum_temperature_K', 0.) > prepared['thermal']['temperature_limit_K'] for row in summary['results']):
            summary['status'] = 'validity_limit'
            summary['status_reason'] = 'A supplied temperature limit was exceeded; this is not a thermal-runaway or damage prediction.'
    (directory/'advanced_transport_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    return summary
