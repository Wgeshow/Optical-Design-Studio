"""Portable electrical material definitions, reference models and SI conversion.

The library is deliberately independent of Qt, NumPy and the electrical solver.
All densities are cm^-3, mobilities cm^2/(V s), masses relative to m0, and
energies eV. ``epsilon_r`` is the static permittivity used by Poisson, not an
optical n/k model. Optical dispersion remains in the optical material library.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import uuid

SCHEMA_VERSION = 1
Q_C = 1.602176634e-19
KB_EV_K = 8.617333262145e-5

# Stable keys are shared by the device editor, portable projects and solver.
PROPERTY_FIELDS = (
    ('epsilon_r', 'Static relative permittivity', '1'),
    ('bandgap_eV', 'Band gap', 'eV'),
    ('affinity_eV', 'Electron affinity', 'eV'),
    ('Nc_cm3', 'Conduction density of states', 'cm⁻³'),
    ('Nv_cm3', 'Valence density of states', 'cm⁻³'),
    ('electron_mass_ratio', 'Electron conductivity mass / m₀', '1'),
    ('hole_mass_ratio', 'Hole conductivity mass / m₀', '1'),
    ('electron_dos_mass_ratio', 'Electron DOS mass / m₀', '1'),
    ('hole_dos_mass_ratio', 'Hole DOS mass / m₀', '1'),
    ('electron_mobility_cm2_Vs', 'Electron mobility', 'cm²/(V·s)'),
    ('hole_mobility_cm2_Vs', 'Hole mobility', 'cm²/(V·s)'),
    ('intrinsic_cm3', 'Intrinsic carrier concentration', 'cm⁻³'),
    ('bulk_electron_cm3', 'Equilibrium bulk electrons (optional)', 'cm⁻³'),
    ('bulk_hole_cm3', 'Equilibrium bulk holes (optional)', 'cm⁻³'),
    ('conductivity_S_m', 'Fixed conductivity (optional override)', 'S/m'),
    ('optical_n', 'Constant optical refractive index (optional)', '1'),
    ('optical_k', 'Constant optical extinction coefficient (optional)', '1'),
)
PROPERTY_UNITS = {key: units for key, _, units in PROPERTY_FIELDS}
_POSITIVE = {'epsilon_r', 'Nc_cm3', 'Nv_cm3', 'electron_mass_ratio',
             'hole_mass_ratio', 'electron_dos_mass_ratio', 'hole_dos_mass_ratio', 'optical_n'}
_NONNEGATIVE = set(PROPERTY_UNITS) - _POSITIVE - {'affinity_eV'}
_CARRIER_REQUIRED = {'bandgap_eV', 'affinity_eV', 'Nc_cm3', 'Nv_cm3',
                     'electron_mass_ratio', 'hole_mass_ratio',
                     'electron_mobility_cm2_Vs', 'hole_mobility_cm2_Vs', 'intrinsic_cm3'}
_AL_BASIC = 'https://www.ioffe.ru/SVA/NSM/Semicond/AlGaAs/basic.html'
_AL_BAND = 'https://www.ioffe.ru/SVA/NSM/Semicond/AlGaAs/bandstr.html'
_COLORADO = 'https://www.colorado.edu/ecee/sites/default/files/attached-files/sd_constants_sheet.pdf'


def _number(value, label, minimum=None, maximum=None, strictly_positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f'{label} must be a finite number.')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f'{label} must be a finite number.') from None
    if not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number.')
    if strictly_positive and value <= 0:
        raise ValueError(f'{label} must be greater than zero.')
    if minimum is not None and value < minimum:
        raise ValueError(f'{label} must be at least {minimum:g}.')
    if maximum is not None and value > maximum:
        raise ValueError(f'{label} must be at most {maximum:g}.')
    return value


def validate_materials(materials):
    """Validate and normalize a complete library, without mutating its input.

    Dielectrics require static permittivity only. Semiconductors and transparent
    conductors require the carrier model fields, so an incomplete custom record
    cannot silently fall back to GaAs parameters when running a simulation.
    """
    if not isinstance(materials, list) or len(materials) > 10000:
        raise ValueError('Electrical materials must be a list of at most 10000 definitions.')
    try:
        json.dumps(materials, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Electrical materials must contain finite, JSON-compatible values.') from None
    result = deepcopy(materials)
    ids = set()
    for index, material in enumerate(result):
        if not isinstance(material, dict):
            raise ValueError(f'Electrical material {index + 1} must be an object.')
        ident = material.get('id', '')
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', ident):
            raise ValueError('Material ID must contain 1–128 letters, digits, dots, underscores or hyphens.')
        if ident in ids:
            raise ValueError(f'Duplicate electrical material ID: {ident}.')
        ids.add(ident)
        name = material.get('name', '')
        if not isinstance(name, str) or not name.strip() or len(name) > 256:
            raise ValueError(f'Material {ident} needs a name of at most 256 characters.')
        material['name'] = name.strip()
        kind = material.get('kind', 'semiconductor')
        if kind not in ('semiconductor', 'conductor', 'dielectric'):
            raise ValueError(f'{name}: kind must be semiconductor, conductor or dielectric.')
        material['kind'] = kind
        material['temperature_K'] = _number(material.get('temperature_K', 300.), f'{name}: reference temperature', strictly_positive=True)
        props = material.get('properties')
        if not isinstance(props, dict) or 'epsilon_r' not in props:
            raise ValueError(f'{name}: properties must include epsilon_r.')
        required = _CARRIER_REQUIRED if kind != 'dielectric' else set()
        missing = required - props.keys()
        if missing:
            raise ValueError(f'{name}: missing electrical properties: {", ".join(sorted(missing))}.')
        for key, value in tuple(props.items()):
            if not isinstance(key, str):
                raise ValueError(f'{name}: property names must be strings.')
            props[key] = _number(value, f'{name}: {key}', minimum=0 if key in _NONNEGATIVE else None,
                                 strictly_positive=key in _POSITIVE)
        if 'al_fraction' in material:
            material['al_fraction'] = _number(material['al_fraction'], f'{name}: Al fraction', 0, 1)
        model = material.get('model', 'constant')
        if model not in ('constant', 'gaas_reference', 'silicon_reference', 'algaas_reference'):
            raise ValueError(f'{name}: unsupported reference model {model}.')
        if model == 'algaas_reference' and 'al_fraction' not in material:
            raise ValueError(f'{name}: AlGaAs reference model requires al_fraction.')
        material['model'] = model
        overrides = material.get('property_overrides', [])
        if not isinstance(overrides, list) or any(not isinstance(key, str) or key not in props for key in overrides):
            raise ValueError(f'{name}: property_overrides must name existing properties.')
        material['property_overrides'] = list(dict.fromkeys(overrides))
        sources = material.get('sources', [])
        if not isinstance(sources, list) or any(not isinstance(source, dict) for source in sources):
            raise ValueError(f'{name}: sources must be a list of source objects.')
        for source in sources:
            for key in ('title', 'url', 'note', 'kind'):
                if key in source and not isinstance(source[key], str):
                    raise ValueError(f'{name}: source {key} must be text.')
            url = source.get('url', '')
            if url and not re.match(r'^https?://[^\s]+$', url):
                raise ValueError(f'{name}: source URLs must begin with http:// or https://.')
        material['sources'] = sources
        for key in ('notes', 'optical_material_name', 'color'):
            if key in material and not isinstance(material[key], str):
                raise ValueError(f'{name}: {key} must be text.')
        if 'aliases' in material and (not isinstance(material['aliases'], list) or any(not isinstance(item, str) for item in material['aliases'])):
            raise ValueError(f'{name}: aliases must be a list of names.')
    return result


def _ni(props, temperature):
    return math.sqrt(props['Nc_cm3']) * math.sqrt(props['Nv_cm3']) * math.exp(-props['bandgap_eV'] / (2 * KB_EV_K * temperature))


def _model_properties(model, temperature, al_fraction=.5):
    scale = (temperature / 300.) ** 1.5
    if model == 'algaas_reference':
        x = al_fraction
        direct = x <= .45
        dos = .063 + .083*x if direct else .85 - .14*x
        hole = .51 + .25*x
        gap = 1.424 + 1.247*x if direct else 1.9 + .125*x + .143*x*x
        alpha = 5.41e-4 if direct else 4.6e-4
        gap -= alpha * (temperature**2/(temperature+204.) - 300.**2/504.)
        props = dict(epsilon_r=12.9-2.84*x, bandgap_eV=gap,
                     affinity_eV=4.07-1.1*x if direct else 3.64-.14*x,
                     electron_mass_ratio=dos if direct else .26, hole_mass_ratio=hole,
                     electron_dos_mass_ratio=dos, hole_dos_mass_ratio=hole,
                     Nc_cm3=2.5e19*dos**1.5*scale, Nv_cm3=2.5e19*hole**1.5*scale)
    elif model == 'gaas_reference':
        # The x=0 Ioffe alloy limit, plus a low-field bulk mobility reference.
        props = dict(epsilon_r=12.9, bandgap_eV=1.424-5.41e-4*(temperature**2/(temperature+204.)-300.**2/504.),
                     affinity_eV=4.07, electron_mass_ratio=.063, hole_mass_ratio=.51,
                     electron_dos_mass_ratio=.063, hole_dos_mass_ratio=.51,
                     Nc_cm3=2.5e19*.063**1.5*scale, Nv_cm3=2.5e19*.51**1.5*scale)
    elif model == 'silicon_reference':
        props = dict(epsilon_r=11.7, bandgap_eV=1.124-4.73e-4*(temperature**2/(temperature+636.)-300.**2/936.),
                     affinity_eV=4.05, electron_mass_ratio=.26, hole_mass_ratio=.39,
                     electron_dos_mass_ratio=1.08, hole_dos_mass_ratio=.81,
                     Nc_cm3=2.82e19*scale, Nv_cm3=1.83e19*scale)
    else:
        return {}
    props['intrinsic_cm3'] = _ni(props, temperature)
    return props


def reference_properties(model, temperature_K=300., al_fraction=.5):
    """Named analytic reference values for the editor's explicit reset action."""
    if model not in ('gaas_reference', 'silicon_reference', 'algaas_reference'):
        raise ValueError('Select a semiconductor reference model to recalculate values.')
    temperature = _number(temperature_K, 'Reference temperature', strictly_positive=True)
    fraction = _number(al_fraction, 'Al fraction', 0, 1)
    return _model_properties(model, temperature, fraction)


def evaluate_material(material, temperature_K=None, al_fraction=None):
    """Return an evaluated copy; explicit property edits override reference curves.

    Reference curves update band gap/DOS/intrinsic concentration at temperature,
    and AlGaAs composition. Mobility remains the editable reference value. Values
    changed directly in portable JSON are also detected as overrides, ensuring
    custom edits are never discarded merely because a preset has a model name.
    """
    result = validate_materials([material])[0]
    temperature = _number(result['temperature_K'] if temperature_K is None else temperature_K,
                          'Material temperature', strictly_positive=True)
    fraction = result.get('al_fraction', .5) if al_fraction is None else _number(al_fraction, 'Al fraction', 0, 1)
    if result['model'] != 'constant':
        original = _model_properties(result['model'], result['temperature_K'], result.get('al_fraction', .5))
        target = _model_properties(result['model'], temperature, fraction)
        overrides = set(result.get('property_overrides', []))
        for key, value in original.items():
            if key in result['properties'] and not math.isclose(result['properties'][key], value, rel_tol=1e-10, abs_tol=1e-20):
                if key == 'intrinsic_cm3' and math.isclose(result['properties'][key], _ni(result['properties'], result['temperature_K']), rel_tol=1e-10, abs_tol=1e-20):
                    continue  # Derived ni after a persisted manual Eg/DOS override.
                overrides.add(key)
        for key, value in target.items():
            if key not in overrides:
                result['properties'][key] = value
        # Recompute ni after an edited gap/DOS unless ni itself was overridden.
        if 'intrinsic_cm3' not in overrides:
            result['properties']['intrinsic_cm3'] = _ni(result['properties'], temperature)
        result['property_overrides'] = sorted(overrides)
    result['temperature_K'] = temperature
    if result['model'] == 'algaas_reference' or 'al_fraction' in result:
        result['al_fraction'] = fraction
        result['band_type'] = 'direct' if fraction <= .45 else 'indirect'
    return validate_materials([result])[0]


def conductivity_S_m(material, electrons_cm3=None, holes_cm3=None):
    """Return q(n μn + p μp) in S/m, or the user's fixed-conductivity override."""
    material = evaluate_material(material)
    props = material['properties']
    if electrons_cm3 is None and holes_cm3 is None and 'conductivity_S_m' in props:
        return props['conductivity_S_m']
    n = props.get('bulk_electron_cm3', props.get('intrinsic_cm3', 0.)) if electrons_cm3 is None else electrons_cm3
    p = props.get('bulk_hole_cm3', props.get('intrinsic_cm3', 0.)) if holes_cm3 is None else holes_cm3
    n = _number(n, 'Electron concentration', 0)
    p = _number(p, 'Hole concentration', 0)
    value = Q_C * 100. * (n*props.get('electron_mobility_cm2_Vs', 0.) + p*props.get('hole_mobility_cm2_Vs', 0.))
    if not math.isfinite(value):
        raise ValueError('Carrier conductivity exceeds finite numeric limits.')
    return value


def _source(title, url, properties, note='', kind='reference'):
    return dict(title=title, url=url, properties=list(properties), note=note,
                kind=kind, reference_temperature_K=300.)


def _builtins():
    gaas = dict(id='gaas', name='GaAs', kind='semiconductor', temperature_K=300.,
        model='gaas_reference', color='#ef7595', optical_material_name='GaAs', aliases=['Gallium arsenide'],
        properties={**_model_properties('gaas_reference', 300.), 'electron_mobility_cm2_Vs':8500., 'hole_mobility_cm2_Vs':400.},
        sources=[_source('Ioffe NSM: AlGaAs basic parameters (GaAs x=0 limit)', _AL_BASIC,
            ['epsilon_r', 'affinity_eV', 'electron_mass_ratio', 'hole_mass_ratio']),
            _source('Ioffe NSM: AlGaAs band structure (GaAs x=0 limit)', _AL_BAND,
            ['bandgap_eV', 'Nc_cm3', 'Nv_cm3', 'intrinsic_cm3'], 'DOS and ni are calculated from the reference model.'),
            _source('TYDEX: GaAs electronic properties', 'https://www.tydexoptics.com/materials1/for_transmission_optics/gaas/',
            ['electron_mobility_cm2_Vs', 'hole_mobility_cm2_Vs'], 'Low-field bulk reference; not a mobility fit for heavily doped material.')],
        notes='300 K bulk reference. Masses follow the Ioffe x=0 alloy limit. Mobility is constant unless edited. No recombination, high-field transport or impurity-scattering model is implied.')
    algaas = dict(id='algaas', name='AlGaAs', kind='semiconductor', temperature_K=300., al_fraction=.5,
        model='algaas_reference', color='#9c8cef', optical_material_name='AlGaAs', aliases=['Aluminium gallium arsenide'],
        properties={**_model_properties('algaas_reference', 300., .5), 'electron_mobility_cm2_Vs':1000., 'hole_mobility_cm2_Vs':100.},
        sources=[_source('Ioffe NSM: AlGaAs basic parameters', _AL_BASIC,
            ['epsilon_r','affinity_eV','electron_mass_ratio','hole_mass_ratio','electron_dos_mass_ratio']),
            _source('Ioffe NSM: AlGaAs band structure', _AL_BAND,
            ['bandgap_eV','Nc_cm3','Nv_cm3','intrinsic_cm3'], 'Piecewise 300 K fit. Indirect branch above x=0.45 uses DOS mass 0.85−0.14x and conductivity mass 0.26 m0.'),
            _source('Editable transport assumptions', '', ['electron_mobility_cm2_Vs','hole_mobility_cm2_Vs'],
                '1000 / 100 cm²/(V·s) are starting estimates, not measured mobility for a particular alloy or doping.', 'assumption')],
        notes='Editable alloy fraction x∈[0,1]. The approximate direct/indirect transition is represented at x=0.45; Ioffe also reports a 0.41–0.45 crossover region. Mobility values are explicit assumptions. Temperature gaps use Varshni corrections and DOS scales as T^1.5; validity outside the 300 K reference must be assessed for the device.')
    silicon = dict(id='silicon', name='Silicon', kind='semiconductor', temperature_K=300.,
        model='silicon_reference', color='#70cfa7', optical_material_name='Si', aliases=['Si','Crystalline silicon'],
        properties={**_model_properties('silicon_reference', 300.), 'electron_mobility_cm2_Vs':1400., 'hole_mobility_cm2_Vs':470.},
        sources=[_source('University of Colorado ECEE: silicon material parameters', _COLORADO,
            ['epsilon_r','bandgap_eV','Nc_cm3','Nv_cm3','electron_mass_ratio','hole_mass_ratio','electron_mobility_cm2_Vs','hole_mobility_cm2_Vs'],
            '300 K parameter sheet. ni is recalculated consistently from Eg/Nc/Nv rather than mixing independent rounded ni values.'),
            _source('Ioffe NSM: silicon reference', 'https://www.ioffe.ru/SVA/NSM/Semicond/Si/basic.html', ['affinity_eV'],
            'Conventional electron-affinity estimate 4.05 eV. Surface/interface processing can change the effective band alignment.'),
            _source('Silicon temperature model', 'https://www.ioffe.ru/SVA/NSM/Semicond/Si/bandstr.html', ['bandgap_eV','Nc_cm3','Nv_cm3'],
            'Varshni α=4.73e−4 eV/K, β=636 K; DOS T^1.5 scaling. Static permittivity and mobility are held constant.')],
        notes='Crystalline silicon, 300 K low-field reference. Electron/hole conductivity masses are distinct from DOS masses. Mobility is not a fit to high doping or field; edit to match your sample.')
    ito_props = dict(epsilon_r=9., bandgap_eV=3.5, affinity_eV=4.5, electron_mass_ratio=.35,
        hole_mass_ratio=1., electron_dos_mass_ratio=.35, hole_dos_mass_ratio=1.,
        Nc_cm3=2.5e19*.35**1.5, Nv_cm3=2.5e19, electron_mobility_cm2_Vs=30.,
        hole_mobility_cm2_Vs=0., bulk_electron_cm3=8e20, bulk_hole_cm3=0.)
    ito_props['intrinsic_cm3'] = _ni(ito_props, 300.)
    ito = dict(id='ito', name='ITO', kind='conductor', temperature_K=300., model='constant',
        color='#67c9e5', optical_material_name='ITO', aliases=['Indium tin oxide'], properties=ito_props,
        sources=[_source('Khusayfan & El-Nahass (2013): structure and electro-optical characteristics of ITO',
            'https://doi.org/10.1155/2013/408182', ['electron_mass_ratio'],
            'The paper uses assumed mass 0.35 m0 and reports process-dependent carrier density and mobility. Its measured optical band gap is not used as a universal electronic gap.'),
            _source('Editable ITO device-study assumptions', '', list(ito_props),
            'All preset values are model assumptions, not measurements of your film: n=8e20 cm−3, μn=30 cm²/(V·s), static εr=9, m*=0.35 m0, χ=4.5 eV, electronic gap=3.5 eV. Hole/DOS values are closure assumptions; degenerate ITO requires Fermi statistics.', 'assumption')],
        notes='Transparent conductor with degenerate electrons. Carrier density, mobility, static permittivity, mass and affinity depend on film growth; replace these assumptions with measured values. Static εr is not optical ε∞. The fixed mass approximation does not model nonparabolicity. Temperature is held constant in this preset.')
    air = dict(id='air', name='Air / void', kind='dielectric', temperature_K=300., model='constant',
        color='#cbd5df', optical_material_name='Air', aliases=['Air','Void'], properties={'epsilon_r':1., 'conductivity_S_m':0.},
        sources=[_source('Ideal void model', '', ['epsilon_r','conductivity_S_m'], 'Vacuum-permittivity, zero-conductivity approximation.', 'assumption')],
        notes='Ideal dielectric void. No mobile carriers or optical material data are inferred from this record.')
    return validate_materials([gaas, ito, algaas, silicon, air])


def builtin_materials():
    """Fresh independent definitions; caller edits can never change the defaults."""
    return _builtins()


def lookup_material(materials, material_id):
    """Resolve a stable ID (or legacy name/alias) and return a detached definition."""
    library = validate_materials(materials)
    for material in library:
        if material['id'] == material_id:
            return material
    query = str(material_id).casefold()
    for material in library:
        if query in [material['name'].casefold(), *[name.casefold() for name in material.get('aliases', [])]]:
            return material
    raise ValueError(f'Unknown electrical material: {material_id}.')


def new_material(name='Custom material', template=None):
    material = deepcopy(template) if template is not None else builtin_materials()[0]
    material.update(id='custom_'+uuid.uuid4().hex[:12], name=name, model='constant',
                    sources=[], notes='', property_overrides=[])
    material.pop('aliases', None)
    return validate_materials([material])[0]


def import_materials(path):
    """Read a JSON library or one material; perform validation before any mutation."""
    path = Path(path)
    if path.stat().st_size > 10*1024*1024:
        raise ValueError('Electrical material file exceeds 10 MiB.')
    try:
        payload = json.loads(path.read_text(encoding='utf-8-sig'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'Non-finite JSON value: {value}.')))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f'Invalid electrical material JSON: {exc}.') from exc
    if isinstance(payload, dict) and 'materials' in payload:
        if payload.get('schema_version', SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ValueError('Unsupported electrical material library schema version.')
        payload = payload['materials']
    elif isinstance(payload, dict):
        payload = [payload]
    return validate_materials(payload)


def export_materials(path, materials):
    payload = dict(format='ods_electrical_materials', schema_version=SCHEMA_VERSION,
                   materials=validate_materials(materials))
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')


def merge_materials(existing, incoming):
    """Import with stable IDs; an incoming definition replaces that ID atomically."""
    existing = validate_materials(existing)
    incoming = validate_materials(incoming)
    mapping = {material['id']: material for material in existing}
    mapping.update({material['id']: material for material in incoming})
    return validate_materials(list(mapping.values()))
