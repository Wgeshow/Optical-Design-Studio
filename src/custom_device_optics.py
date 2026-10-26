"""Editable finite-device electrostatics coupled to a periodic optical cell.

Only material-specific, laterally averaged charge is applied to optics. Until
the solver exports separate averages for multiple solids, such layers are
explicitly rejected for coupling while remaining valid electrical devices.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np

from electrical_optics import E, EPS0, M0, C, _finite, _index, _save_csv, _tensor, interband_response
from electrical_sweep import resolve_biases

ELECTRICAL_KEYS = {'model', 'device', 'material_library', 'biases_V', 'charge_model', 'swept_contact_id', 'transport'}
OPTICAL_KEYS = {'optical_enabled', 'optical_reference', 'optical_mapping', 'optical_slices_per_layer',
                'electro_optic', 'interband', 'interband_extrapolation', 'r41_gaas_m_V',
                'response', 'feature', 'reference_nm', 'tracking_window_nm', 'requires_native', 'task',
                'terminal_studies', 'optical_unit_cell'}
LIMITATIONS = [
    'The finite electrical device is represented by a periodic optical cell. '
    'Exterior contact footprints with an assigned optical material and thickness '
    'become finite periodic scattering pads; electrical contacts remain ideal '
    'boundaries. Finite-device lateral diffraction is not computed.',
    'Depth-dependent carriers and vertical field moments are solid-area '
    'averages. Different-material solid overrides in one layer require '
    'material-specific electrical averages and are rejected for optical coupling.',
    'Drude optical damping uses the editable electrical conductivity masses '
    'and transport mobilities. Electrostatics does not predict junction '
    'transport or leakage; optional terminal I–V is a frozen-conductivity '
    'Ohmic estimate.',
    'Optional GaAs interband and electro-optic laws retain the prior study '
    'assumptions: 300 K parabolic interband bands below both edges; (001) GaAs '
    'with vertical-field electro-optic coefficients held constant near 1.15 µm. '
    'They are not applied to silicon, alloys or arbitrary custom materials.',
]


def validate_custom_options(options):
    """Normalize persistable drafts without requiring contacts or mappings."""
    from device_model import validate_device
    from electrical_material_library import builtin_materials, validate_materials
    from electrical_terminal_studies import validate_studies
    if not isinstance(options, dict):
        raise ValueError('Custom electrical settings must be an object.')
    unknown = set(options)-ELECTRICAL_KEYS-OPTICAL_KEYS
    if unknown:
        raise ValueError('Unsupported custom electrical settings: '+', '.join(sorted(unknown)))
    if options.get('model', 'custom_device') != 'custom_device':
        raise ValueError('Select the custom_device electrical model.')
    cfg = copy.deepcopy(options)
    cfg['model'] = 'custom_device'
    cfg['material_library'] = validate_materials(cfg.get('material_library', builtin_materials()))
    cfg['device'] = validate_device(cfg.get('device'), cfg['material_library'], require_contacts=False)
    cfg['biases_V'] = resolve_biases(cfg.get('biases_V', [0., -2.]))
    cfg['charge_model'] = cfg.get('charge_model', 'semiconductor')
    if cfg['charge_model'] not in ('semiconductor', 'dielectric'):
        raise ValueError('Charge model must be semiconductor or dielectric.')
    swept = cfg.get('swept_contact_id', '')
    if not isinstance(swept, str):
        raise ValueError('Swept contact ID must be text.')
    cfg['swept_contact_id'] = swept
    cfg['terminal_studies'] = validate_studies(cfg.get('terminal_studies'))
    from electrical_transport import validate_transport
    cfg['transport'] = validate_transport(cfg.get('transport'))
    for key in ('optical_enabled', 'electro_optic', 'interband', 'interband_extrapolation'):
        if not isinstance(cfg.get(key, False), bool):
            raise ValueError(key+' must be true or false.')
        cfg[key] = cfg.get(key, False)
    cfg['optical_reference'] = cfg.get('optical_reference', 'zero_bias')
    if cfg['optical_reference'] not in ('zero_bias', 'undoped'):
        raise ValueError('Optical reference must be zero_bias or undoped.')
    count = _finite(cfg.get('optical_slices_per_layer', 8), 'Optical slices per layer', minimum=1, maximum=100)
    if count != int(count):
        raise ValueError('Optical slices per layer must be an integer.')
    cfg['optical_slices_per_layer'] = int(count)
    mapping = cfg.get('optical_mapping', {})
    if not isinstance(mapping, dict):
        raise ValueError('Optical mapping must be keyed by electrical layer ID.')
    for source, row in mapping.items():
        if not isinstance(source, str):
            raise ValueError('Optical mapping layer IDs must be text.')
        if isinstance(row, str):
            row = {'layer': row}
        if not isinstance(row, dict) or set(row)-{'layer', 'material'} or any(not isinstance(v, str) for v in row.values()):
            raise ValueError('Every optical mapping needs a layer and optional material name.')
        mapping[source] = {key: value.strip() for key, value in row.items()}
    cfg['optical_mapping'] = mapping
    cfg['response'] = cfg.get('response', 'Absorption')
    cfg['feature'] = cfg.get('feature', 'Peak')
    if cfg['response'] not in ('Reflection', 'Transmission', 'Absorption') or cfg['feature'] not in ('Peak', 'Dip'):
        raise ValueError('Select a valid optical response and Peak or Dip.')
    for key, default in (('reference_nm', 1550.), ('tracking_window_nm', 30.)):
        cfg[key] = _finite(cfg.get(key, default), key, minimum=1e-6)
    cfg['r41_gaas_m_V'] = _finite(cfg.get('r41_gaas_m_V', 1.68e-12), 'GaAs r41', minimum=-1e-9, maximum=1e-9)
    from optical_unit_cell import validate_unit_cell
    cfg['optical_unit_cell'] = validate_unit_cell(cfg.get('optical_unit_cell'), cfg['device'])
    cfg['requires_native'] = bool(cfg['optical_enabled'] and cfg['electro_optic'])
    return cfg


def _is_gaas(material):
    return material.get('model') == 'gaas_reference' or material['id'] == 'gaas'


def prepare_custom_coupling(model, options):
    """Validate the actual device and physical optical mapping at Run."""
    from custom_electrical_solver import validate_options
    from device_model import layer_bounds
    cfg = validate_custom_options(options)
    cfg.update(validate_options({key: cfg[key] for key in ELECTRICAL_KEYS if key in cfg}))
    cfg['task'] = 'electrical'
    if cfg['terminal_studies']['cv_enabled']:
        if len(set(cfg['biases_V'])) < 3:
            raise ValueError('C–V requires at least three distinct bias voltages; add a third bias before running.')
        contact = next(row for row in cfg['device']['contacts'] if row['id'] == cfg['swept_contact_id'])
        if len({float(contact['voltage_V'])+bias for bias in cfg['biases_V']}) < 3:
            raise ValueError('C–V requires three distinct applied terminal voltages; increase the bias spacing.')
    if not cfg['optical_enabled']:
        return cfg
    if model is None or model.get('mode') != 'Wavelength sweep':
        raise ValueError('Custom electrical optical coupling requires a wavelength sweep.')
    from optical_unit_cell import validate_unit_cell
    # The prepared optical geometry is authoritative: its crop and the carrier
    # averages must use exactly the same selection, independent of UI drafts.
    selected = model.get('optical_unit_cell', {}).get('selection')
    if selected is not None:
        cfg['optical_unit_cell'] = validate_unit_cell(selected, cfg['device'])
    elif cfg['optical_unit_cell']['enabled']:
        raise ValueError('Prepare the selected optical unit-cell geometry before applying electrical coupling.')
    waves = sorted({float(row[1]) for row in model['points']})
    if not waves or not all(math.isfinite(w) and w > 0 for w in waves):
        raise ValueError('Optical wavelengths must be positive and finite.')
    if not waves[0] <= cfg['reference_nm'] <= waves[-1]:
        raise ValueError('Reference wavelength must lie inside the optical sweep.')
    device = cfg['device']
    library = {row['id']: row for row in cfg['material_library']}
    optical_layers = {row['name']: row for row in model['layers']}
    optical_materials = {row['name']: row for row in model['materials']}
    mapping, positions = {}, []
    for source in layer_bounds(device):
        electrical = library[source['material_id']]
        entry = cfg['optical_mapping'].get(source['id'], cfg['optical_mapping'].get(source['name'], {}))
        candidates = [row for row in model['layers'] if row.get('device_layer_id') == source['id']]
        name = entry.get('layer') or (candidates[0]['name'] if len(candidates) == 1 else source.get('optical_layer_name', source['name']))
        if name not in optical_layers:
            raise ValueError(source['name']+': map an optical layer representing this electrical layer.')
        layer = optical_layers[name]
        position = next(i for i, row in enumerate(model['layers']) if row['name'] == name)
        if position in (0, len(model['layers'])-1) or not math.isclose(float(layer['thickness']), source['thickness_um'], rel_tol=0, abs_tol=1e-8):
            raise ValueError(source['name']+': mapped optical layer must have the same finite thickness as the electrical layer.')
        material_name = entry.get('material') or layer['material']
        if material_name != layer['material'] or material_name not in optical_materials:
            raise ValueError(source['name']+': map the electrical material to its optical background material.')
        material = optical_materials[material_name]
        if material.get('epsilon_tensor') is not None:
            raise ValueError(source['name']+': choose a scalar optical reference before applying electrical corrections.')
        if material['model'] == 'table_nk' and (material['grid'][0] > waves[0] or material['grid'][-1] < waves[-1]):
            raise ValueError(material_name+': optical data must cover the complete wavelength sweep.')
        for shape in device['shapes']:
            if (shape['enabled'] and shape['layer_id'] == source['id'] and shape['operation'] != 'void'
                    and shape['material_id'] != source['material_id']):
                raise ValueError(source['name']+': optical coupling needs material-specific averages for mixed-material solid shapes. '
                                 'Run electrical-only simulation or use one solid material with voids in this layer.')
        mapping[source['id']] = dict(layer=name, material=material_name)
        positions.append(position)
        if cfg['interband'] and _is_gaas(electrical):
            if not math.isclose(device['temperature_K'], 300., abs_tol=1e-8):
                raise ValueError('The optional GaAs interband model requires 300 K.')
            dopings = [source['donor_cm3'], source['acceptor_cm3']]
            for region in device['doping_regions']:
                if region['enabled'] and region['layer_id'] == source['id']:
                    dopings.extend([region['donor_cm3'], region['acceptor_cm3']])
            if max(dopings) > 1e19 and not cfg['interband_extrapolation']:
                raise ValueError('GaAs interband doping above 1e19 cm^-3 requires explicit extrapolation.')
    if len(set(positions)) != len(positions) or positions != sorted(positions) or any(b != a+1 for a, b in zip(positions, positions[1:])):
        raise ValueError('Electrical layers must map to distinct consecutive optical layers in device order.')
    if (cfg['interband'] or cfg['electro_optic']) and not any(_is_gaas(library[row['material_id']]) for row in layer_bounds(device)):
        raise ValueError('GaAs optical corrections require a GaAs electrical material; other materials use their editable Drude parameters.')
    cfg['optical_mapping'] = mapping
    if len(waves)*len(mapping)*(device['mesh']['nz_per_layer']+cfg['optical_slices_per_layer'])*len(cfg['biases_V']) > 5_000_000:
        raise ValueError('Reduce optical samples or slices to stay below five million index records.')
    return cfg


def _read_profile(path):
    keys = ('z_nm', 'electrons_cm3', 'holes_cm3', 'Ez_V_m', 'Ez_squared_V2_m2', 'material')
    with np.load(path, allow_pickle=False) as loaded:
        if any(key not in loaded.files for key in keys):
            raise ValueError('Custom electrical profile is missing depth, material, carrier or field arrays.')
        values = {key: np.array(loaded[key], copy=True) for key in loaded.files}
    z = values['z_nm']
    if z.ndim != 1 or len(z) < 1 or not np.isfinite(z).all() or np.any(np.diff(z) <= 0):
        raise ValueError('Custom electrical profile depths must be finite and strictly ordered.')
    for key in keys[1:-1]:
        if values[key].shape != z.shape or not np.isfinite(values[key]).all() or (key != 'Ez_V_m' and np.any(values[key] < 0)):
            raise ValueError('Custom electrical profile '+key+' has invalid values.')
    if values['material'].shape != z.shape:
        raise ValueError('Custom electrical material identities have invalid dimensions.')
    if 'ito_electrons_cm3' in values:
        extra = values['ito_electrons_cm3']
        if extra.shape != z.shape or not np.isfinite(extra).all() or np.any(extra < 0):
            raise ValueError('Custom electrical conductor populations have invalid dimensions or values.')
        values['electrons_cm3'] = values['electrons_cm3']+extra
    return values


def _average(profile, layer, start, stop):
    z = profile['z_nm']
    mask = (z >= layer['z_min_um']*1000-1e-8) & (z <= layer['z_max_um']*1000+1e-8)
    if 'layer_id' in profile:
        mask &= profile['layer_id'] == layer['id']
    if not np.any(mask) or np.any(profile['material'][mask] != layer['material_id']):
        raise ValueError(layer['name']+': profile does not represent the mapped single solid material.')
    nodes = z[mask]
    points = np.unique(np.r_[start, nodes[(nodes > start) & (nodes < stop)], stop])
    answer = {}
    for key in ('electrons_cm3', 'holes_cm3', 'Ez_V_m', 'Ez_squared_V2_m2'):
        values = np.interp(points, nodes, profile[key][mask])
        answer[key] = float(np.sum((values[:-1]+values[1:])/2*np.diff(points))/(stop-start))
    return answer


def material_drude(waves, populations, material):
    """Use each material's editable masses/mobilities without semiconductor presets."""
    result = np.zeros(len(waves), complex)
    if material['kind'] == 'dielectric':
        return result
    omega = 2*np.pi*C/(np.asarray(waves)*1e-9)
    props = material['properties']
    for key, prefix in (('electrons_cm3', 'electron'), ('holes_cm3', 'hole')):
        density = _finite(populations[key], prefix+' concentration', minimum=0)
        mass = _finite(props[prefix+'_mass_ratio'], prefix+' conductivity mass', minimum=1e-12)*M0
        mobility = _finite(props[prefix+'_mobility_cm2_Vs'], prefix+' mobility', minimum=0)*1e-4
        if not density or not mobility:
            continue  # Zero mobility is the infinitely damped Drude limit.
        gamma = E/(mass*mobility)
        result -= density*1e6*E*E/(EPS0*mass)/(omega*omega+1j*gamma*omega)
    if not np.isfinite(result).all():
        raise ValueError('Material Drude response exceeds finite numerical limits.')
    return result


def build_custom_optical_model(model, cfg, profile, reference, *, layer_records=None, cancelled=lambda: False):
    from backend import Cancelled
    from device_model import layer_bounds
    from electrical_material_library import evaluate_material
    from model import epsilon
    output = copy.deepcopy(model)
    output.pop('measure_phase', None)
    waves = sorted({float(row[1]) for row in model['points']})
    materials = {row['name']: row for row in model['materials']}
    electrical = {row['id']: evaluate_material(row, temperature_K=cfg['device']['temperature_K']) for row in cfg['material_library']}
    bounds = layer_bounds(cfg['device'])
    mapped = {cfg['optical_mapping'][row['id']]['layer']: row for row in bounds}
    layers, patterns, audits = [], [], []
    used_layers = {row['name'] for row in model['layers']}
    used_materials = {row['name'] for row in model['materials']}
    for layer in model['layers']:
        old_patterns = [row for row in model['patterns'] if row['layer'] == layer['name']]
        if layer['name'] not in mapped:
            layers.append(copy.deepcopy(layer)); patterns.extend(copy.deepcopy(old_patterns)); continue
        source = mapped[layer['name']]
        material_name = cfg['optical_mapping'][source['id']]['material']
        mat = electrical[source['material_id']]
        base = np.array([complex(epsilon(materials[material_name], wave)) for wave in waves])
        start, stop = source['z_min_um']*1000, source['z_max_um']*1000
        fine = [edge for row in (layer_records or []) if row.get('layer_id') == source['id']
                for edge in (row['depth_start_nm'], row['depth_end_nm']) if start <= edge <= stop]
        boundaries = np.unique(np.r_[np.linspace(start, stop, cfg['optical_slices_per_layer']+1), fine])
        accumulated = 0.
        for position, (a, b) in enumerate(zip(boundaries[:-1], boundaries[1:])):
            if cancelled():
                raise Cancelled('Custom electrical optical coupling cancelled.')
            state, ref = _average(profile, source, a, b), _average(reference, source, a, b)
            correction = material_drude(waves, state, mat)
            if cfg['optical_reference'] == 'zero_bias':
                correction -= material_drude(waves, ref, mat)
            elif mat['kind'] == 'conductor':
                bulk = {'electrons_cm3': mat['properties'].get('bulk_electron_cm3', 0.),
                        'holes_cm3': mat['properties'].get('bulk_hole_cm3', 0.)}
                correction -= material_drude(waves, bulk, mat)
            index_change = np.zeros(len(waves), complex)
            if cfg['interband'] and _is_gaas(mat):
                key, kind = ('electrons_cm3', 'electrons') if ref['electrons_cm3'] >= ref['holes_cm3'] else ('holes_cm3', 'holes')
                index_change = interband_response(waves, state[key], kind, allow_extrapolation=cfg['interband_extrapolation'])
                if cfg['optical_reference'] == 'zero_bias':
                    index_change -= interband_response(waves, ref[key], kind, allow_extrapolation=cfg['interband_extrapolation'])
            eps = ((_index(base)+index_change)**2 if cfg['interband'] and _is_gaas(mat) else base)+correction
            tensor = cfg['electro_optic'] and _is_gaas(mat)
            xx, xy, zz = _tensor(eps, 'GaAs', state, ref, cfg) if tensor else (eps, np.zeros(len(waves), complex), eps)
            scalar, plus, minus, normal = map(_index, (xx, xx-xy, xx+xy, zz))
            suffix = f'__custom_dc_{position:03d}'
            new_layer = layer['name']+suffix
            while new_layer in used_layers: new_layer += '_'
            used_layers.add(new_layer)
            new_material = material_name+suffix+'_'+source['id']
            while new_material in used_materials: new_material += '_'
            used_materials.add(new_material)
            table = [[wave, float(value.real), float(value.imag)] for wave, value in zip(waves, scalar)]
            clone = dict(name=new_material, model='table_nk', a=table[0][1], b=table[0][2], table=table, grid=waves,
                         electrical_material_id=source['material_id'], electrical_layer_id=source['id'])
            if tensor:
                clone['epsilon_tensor'] = [
                    [[[float(x.real), float(x.imag)], [float(y.real), float(y.imag)], [0., 0.]],
                     [[float(y.real), float(y.imag)], [float(x.real), float(x.imag)], [0., 0.]],
                     [[0., 0.], [0., 0.], [float(z.real), float(z.imag)]]]
                    for x, y, z in zip(xx, xy, zz)]
            output['materials'].append(clone)
            thickness = float(layer['thickness'])-accumulated if position == len(boundaries)-2 else (b-a)/1000
            accumulated += thickness
            layers.append(dict(copy.deepcopy(layer), name=new_layer, material=new_material, thickness=thickness))
            for pattern in old_patterns:
                row = dict(copy.deepcopy(pattern), layer=new_layer)
                if row['material'] == material_name: row['material'] = new_material
                patterns.append(row)
            for i, wave in enumerate(waves):
                audits.append(dict(electrical_layer=source['name'], electrical_layer_id=source['id'],
                    electrical_material_id=source['material_id'], optical_layer=layer['name'], z_start_nm=float(a), z_end_nm=float(b),
                    wavelength_nm=wave, n=float(scalar[i].real), k=float(scalar[i].imag),
                    n_plus=float(plus[i].real), k_plus=float(plus[i].imag), n_minus=float(minus[i].real), k_minus=float(minus[i].imag),
                    n_z=float(normal[i].real), k_z=float(normal[i].imag), delta_n=0., delta_k=0.))
    output['layers'], output['patterns'] = layers, patterns
    output['electrical_coupling'] = dict(model='custom_device', optical_reference=cfg['optical_reference'],
                                        material_sources={row['id']: row.get('sources', []) for row in cfg['material_library']},
                                        optical_unit_cell=copy.deepcopy(cfg['optical_unit_cell']))
    return output, audits


def execute_custom_electrical(model, performance, cfg, directory, executor, emit=lambda event: None, cancelled=lambda: False):
    from backend import Cancelled
    from custom_electrical_solver import solve
    from index_shift import sampled_feature
    from optical_objective import valid_spectrum
    cfg = prepare_custom_coupling(model, cfg)
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    try:
        electrical = solve({key: cfg[key] for key in ELECTRICAL_KEYS if key in cfg}, directory/'electrical', emit, cancelled)
    except InterruptedError as exc:
        raise Cancelled(str(exc)) from exc
    if cancelled(): raise Cancelled('Custom electrical simulation cancelled.')
    study_options = cfg['terminal_studies']
    study_info = None
    if any(study_options[key] for key in ('iv_enabled', 'cv_enabled', 'measured_iv_path', 'measured_cv_path')):
        from electrical_terminal_studies import execute_studies
        try:
            study_info = execute_studies(electrical, study_options, directory, emit, cancelled)
        except InterruptedError as exc:
            raise Cancelled(str(exc)) from exc
        electrical['terminal_studies'] = study_info
        for key in ('iv_csv', 'cv_csv'):
            if key in study_info:
                electrical[key] = study_info[key]
        electrical['study_summary_json'] = study_info['summary_json']
    (directory/'electrical_summary.json').write_text(json.dumps(electrical, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    summary = dict(status='complete', task='electrical', model='custom_device', optical_enabled=cfg['optical_enabled'],
                   biases_V=[row['bias_V'] for row in electrical['results']], optical_reference=cfg['optical_reference'],
                   interband=cfg['interband'], electro_optic=cfg['electro_optic'],
                   transport=cfg['transport'],
                   limitations=list(electrical.get('limitations', []))+(
                       LIMITATIONS if cfg['transport']['mode']=='disabled' else [LIMITATIONS[0],LIMITATIONS[1],
                       'Drude optical damping uses editable conductivity masses and mobilities. The selected electrical transport model and its parameter validity are recorded independently; dielectric constitutive leakage does not create an unmodeled carrier population.',
                       LIMITATIONS[3]]))
    if study_info is not None:
        summary['terminal_studies'] = study_info
        summary['study_summary_json'] = study_info['summary_json']
        for study in study_info.get('studies', {}).values():
            summary['limitations'].extend(study.get('warnings', []))
        for key in ('iv_csv', 'cv_csv'):
            if key in study_info:
                summary[key] = study_info[key]
    if cfg['optical_enabled']:
        zero = next((row for row in electrical['results'] if float(row['bias_V']) == 0), None)
        if zero is None: raise ValueError('Custom optical coupling requires a solved 0 V reference.')
        cell_profiles = {}
        cell_audits = []
        if cfg['optical_unit_cell']['enabled']:
            from optical_unit_cell import selected_cell_profile
            profile_directory = directory/'optical_cell_profiles'
            profile_directory.mkdir(exist_ok=True)
            for state in electrical['results']:
                if cancelled(): raise Cancelled('Selected-cell profile averaging cancelled.')
                if not state.get('volume_npz'):
                    raise ValueError('Selected-cell coupling requires the actual finite-device electrical volume.')
                values, audit = selected_cell_profile(state['volume_npz'], cfg['device'], cfg['optical_unit_cell'], cfg['material_library'])
                filename = f"profile_{float(state['bias_V']):g}V.npz"
                path = profile_directory/filename
                np.savez_compressed(path, **values)
                cell_profiles[float(state['bias_V'])] = _read_profile(path)
                audit['profile_npz'] = str(path.relative_to(directory))
                cell_audits.append(audit)
            (profile_directory/'averaging.json').write_text(json.dumps(cell_audits, indent=2, allow_nan=False)+'\n', encoding='utf-8')
            summary['optical_cell_profiles'] = 'optical_cell_profiles/averaging.json'
        reference = cell_profiles.get(0.) if cell_profiles else _read_profile(zero['profile_npz'])
        summary['optical_unit_cell'] = copy.deepcopy(model.get('optical_unit_cell', {}))
        records = json.loads(Path(zero['layers_json']).read_text(encoding='utf-8')) if zero.get('layers_json') else []
        perf = copy.deepcopy(performance)
        if cfg['requires_native']: perf.update(solver_backend='native', mirror_symmetry=False)
        states = [zero]+[row for row in electrical['results'] if row is not zero]
        spectra, indices, features, baseline, baseline_indices, baseline_feature = [], [], [], None, None, None
        for case, state in enumerate(states):
            if cancelled(): raise Cancelled('Custom electrical optical coupling cancelled.')
            bias = float(state['bias_V'])
            profile = cell_profiles[bias] if cell_profiles else _read_profile(state['profile_npz'])
            shifted, index_rows = build_custom_optical_model(model, cfg, profile, reference,
                                                            layer_records=records, cancelled=cancelled)
            emit(dict(kind='log', text=f'Computing custom-device optics at {bias:g} V…'))
            rows, diagnostics = executor(shifted, perf, lambda event: emit(dict(event, bias_V=bias)), cancelled)
            if len(rows) != len(model['points']) or not valid_spectrum(rows):
                raise ValueError('Custom electrical optical calculation returned an invalid or incomplete spectrum.')
            if baseline is None:
                baseline, baseline_indices = rows, index_rows
                baseline_feature = sampled_feature(rows, cfg['response'], cfg['feature'], cfg['reference_nm'], cfg['tracking_window_nm'])
            if any(row[1:3] != base[1:3] for row, base in zip(rows, baseline)):
                raise ValueError('Custom optical spectra must share the solved 0 V grid.')
            for row, base in zip(rows, baseline):
                spectra.append(dict(bias_V=bias, wavelength_nm=row[1], angle_deg=row[2], R=row[3], T=row[4], A=row[5],
                                    dR=row[3]-base[3], dT=row[4]-base[4], dA=row[5]-base[5]))
            for row, base in zip(index_rows, baseline_indices):
                indices.append(dict(bias_V=bias, **dict(row, delta_n=row['n']-base['n'], delta_k=row['k']-base['k'])))
            found = sampled_feature(rows, cfg['response'], cfg['feature'], baseline_feature[1] if baseline_feature else cfg['reference_nm'], cfg['tracking_window_nm'])
            fixed = next((row for row in rows if baseline_feature and row[1:3] == baseline_feature[1:3]), None)
            features.append(dict(bias_V=bias, response=cfg['response'], feature=cfg['feature'], feature_nm=found[1] if found else None,
                shift_nm=found[1]-baseline_feature[1] if found and baseline_feature else None, baseline_nm=baseline_feature[1] if baseline_feature else None,
                fixed_R=fixed[3] if fixed else None, fixed_T=fixed[4] if fixed else None, fixed_A=fixed[5] if fixed else None,
                dR=fixed[3]-baseline_feature[3] if fixed else None, dT=fixed[4]-baseline_feature[4] if fixed else None,
                dA=fixed[5]-baseline_feature[5] if fixed else None, status='sampled feature' if found and baseline_feature else 'no resolved baseline/feature'))
            (directory/f'electrical_optical_model_{case:03d}.json').write_text(
                json.dumps(dict(bias_V=bias, model=shifted, diagnostics=diagnostics), indent=2, allow_nan=False)+'\n', encoding='utf-8')
            emit(dict(kind='progress', completed=case+1, total=len(states), text=f'Custom optical biases: {case+1}/{len(states)}'))
        _save_csv(directory/'electrical_optical_spectra.csv', spectra)
        _save_csv(directory/'electrical_index_changes.csv', indices)
        _save_csv(directory/'electrical_features.csv', features)
        _save_csv(directory/'results.csv', [dict(wavelength_nm=row[1], angle_deg=row[2], R=row[3], T=row[4], A=row[5]) for row in baseline])
        summary.update(spectra=len(states), optical_samples=len(spectra), spectra_csv='electrical_optical_spectra.csv',
                       index_profiles_csv='electrical_index_changes.csv', features_csv='electrical_features.csv',
                       optical_solver_backend=perf.get('solver_backend', 'native'), baseline_nm=baseline_feature[1] if baseline_feature else None,
                       max_abs_shift_nm=max((abs(row['shift_nm']) for row in features if row['shift_nm'] is not None), default=None),
                       tracking_note='Nearest sampled local feature; fixed R/T/A use the 0 V feature wavelength. Mode identity and basis convergence are not verified.')
    electrical['optical'], electrical['coupling_options'], electrical['limitations'] = summary, cfg, summary['limitations']
    (directory/'electrical_summary.json').write_text(json.dumps(electrical, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (directory/'search_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return dict(kind='search_complete', directory=str(directory), summary=summary)
