"""Silicon free-carrier Drude approximation, Soref & Bennett (1987), Eqs. 4–5.

All public densities are cm^-3, mobilities cm^2/(V s), wavelength nm.
The reference optical library must describe the reference carrier state.
"""
import copy
import csv
import math

SOURCE = 'Soref and Bennett, IEEE J. Quantum Electron. 23, 123–129 (1987), p.127 Eqs.(4),(5); doi:10.1109/JQE.1987.1073206'
MODEL = 'silicon_drude_1987'
PRESETS = {'Si':(.26,.39),'GaAs':(.067,.45)}
LIMITATION = ('Crystalline silicon, approximately 300 K; approximate Drude model over 1000–2000 nm. '
              'The paper reports that simple Drude theory underestimates measured carrier absorption '
              'and does not reproduce the empirical hole-index response. Uniform inputs or supplied layer-depth profiles; '
              'no self-consistent voltage-to-charge, spatial charge-transport, or guided-mode effective-index calculation.')

def _finite(value, label, minimum=0., maximum=None, positive=False):
    if isinstance(value,bool): raise ValueError(label+' must be a number.')
    try: value=float(value)
    except (ValueError,TypeError): raise ValueError(label+' must be a number.') from None
    if not math.isfinite(value) or value<minimum or (positive and value<=0) or (maximum is not None and value>maximum):
        raise ValueError(label+' is outside the supported finite range.')
    return value

def density(value,label='Carrier density (cm^-3)'):
    # The paper discusses 1e17–1e20 cm^-3. Zero supports the undoped reference;
    # lower densities are permitted, but explicitly flagged as extrapolations.
    return _finite(value,label,maximum=1e20)

def evaluate_state(wavelength_nm, reference_n, reference_electron_cm3, reference_hole_cm3,
                   electron_cm3, hole_cm3, mobility_e_cm2_Vs=1350., mobility_h_cm2_Vs=480.,
                   mass_e_m0=.26,mass_h_m0=.39,semiconductor='Si'):
    wavelength_nm=_finite(wavelength_nm,'Wavelength (nm)',1000.,2000.)
    reference_n=_finite(reference_n,'Reference real index',positive=True)
    n0,p0,n,p=[density(v) for v in (reference_electron_cm3,reference_hole_cm3,electron_cm3,hole_cm3)]
    mu_e=_finite(mobility_e_cm2_Vs,'Electron mobility',positive=True)*1e-4
    mu_h=_finite(mobility_h_cm2_Vs,'Hole mobility',positive=True)*1e-4
    e,c,eps0,m0=1.602176634e-19,299792458.,8.8541878128e-12,9.1093837139e-31
    me,mh=_finite(mass_e_m0,'Electron conductivity mass',positive=True)*m0,_finite(mass_h_m0,'Hole conductivity mass',positive=True)*m0
    wavelength=wavelength_nm*1e-9
    dne,dnh=(n-n0)*1e6,(p-p0)*1e6
    dn=-e*e*wavelength*wavelength/(8*math.pi**2*c*c*eps0*reference_n)*(dne/me+dnh/mh)
    alpha_m=e**3*wavelength*wavelength/(4*math.pi**2*c**3*eps0*reference_n)*(dne/(me*me*mu_e)+dnh/(mh*mh*mu_h))
    dk=alpha_m*wavelength/(4*math.pi)
    return dict(delta_n=dn,delta_k=dk,delta_alpha_cm1=alpha_m/100.,
                wavelength_nm=wavelength_nm,delta_electron_cm3=n-n0,delta_hole_cm3=p-p0)

def validate_configuration(configuration):
    cfg=copy.deepcopy(configuration)
    if cfg.get('model',MODEL) not in (MODEL,'semiconductor_drude'): raise ValueError('Unknown carrier model.')
    semi=cfg.get('semiconductor','Si')
    if semi not in ('Si','GaAs','Custom'):raise ValueError('Choose Si, GaAs or Custom semiconductor.')
    if not (cfg.get('material_confirmed') is True or (semi=='Si' and cfg.get('silicon_confirmed') is True)):
        raise ValueError('Confirm the semiconductor parameters and reference-state optical data.')
    cfg.update(model=MODEL if semi=='Si' else 'semiconductor_drude',semiconductor=semi)
    for key,idx in [('mass_e_m0',0),('mass_h_m0',1)]:
        default=PRESETS[semi][idx] if semi in PRESETS else None
        cfg[key]=_finite(cfg.get(key,default),key,positive=True)
    for key in ('reference_electron_cm3','reference_hole_cm3'):
        cfg[key]=density(cfg.get(key,0),key)
    for key,default in [('mobility_e_cm2_Vs',1350.),('mobility_h_cm2_Vs',480.)]:
        cfg[key]=_finite(cfg.get(key,default if semi=='Si' else None),key,positive=True)
    slices=cfg.get('profile_slices',20)
    if isinstance(slices,bool) or int(slices)!=float(slices) or not 1<=int(slices)<=100:raise ValueError('Profile slices must be an integer from 1 to 100 per layer.')
    cfg['profile_slices']=int(slices)
    if cfg.get('profile_sampling','uniform') not in ('uniform','knots'):raise ValueError('Profile sampling must be uniform or knots.')
    cfg['profile_sampling']=cfg.get('profile_sampling','uniform')
    maximum=cfg.get('profile_max_slices',1000)
    if isinstance(maximum,bool) or int(maximum)!=float(maximum) or not 1<=int(maximum)<=2000:raise ValueError('Maximum profile slices must be an integer from 1 to 2000.')
    cfg['profile_max_slices']=int(maximum)
    if cfg.get('optical_reference','reference') not in ('reference','undoped'):raise ValueError('Optical reference must be reference or undoped.')
    cfg['optical_reference']=cfg.get('optical_reference','reference')
    states=cfg.get('states',[])
    if not isinstance(states,list) or not 1<=len(states)<=200: raise ValueError('Provide 1–200 carrier states.')
    labels=set()
    for i,state in enumerate(states):
        if not isinstance(state,dict): raise ValueError('Invalid carrier state.')
        label=str(state.get('label',f'State {i+1}')).strip()
        if not label or label in labels: raise ValueError('State labels must be nonempty and unique.')
        labels.add(label);state['label']=label
        for key in ('electron_cm3','hole_cm3'):state[key]=density(state.get(key,0) if state.get('profiles') else state.get(key),key)
        if state.get('profiles'):
            state['profiles']=validate_profiles(state['profiles'])
        if state.get('bias_v') not in (None,''):
            state['bias_v']=_finite(state['bias_v'],'Bias label (V)',minimum=-1e9,maximum=1e9)
        else:state['bias_v']=None
    cfg['source']=SOURCE
    cfg['limitations']=LIMITATION
    if semi!='Si':
        cfg['source']='Generic Drude equations as in Soref & Bennett (1987) Eqs.4–5; GaAs conductivity mass starting values .067/.45 from user-supplied slides; custom parameters supplied by user.'
        cfg['limitations']='Approximate free-carrier Drude response using selected semiconductor parameters; the silicon empirical results do not validate GaAs or alloys. Wavelength guard 1000–2000 nm is a software scope, not a verified material range. Check band-edge, mobility, nonparabolicity and doping validity. No self-consistent charge transport or guided-mode effective index.'
    cfg['warnings']=[]
    densities=[cfg['reference_electron_cm3'],cfg['reference_hole_cm3']]+[s[k] for s in states for k in ('electron_cm3','hole_cm3')]
    if semi=='Si' and any(0<v<1e17 for v in densities):
        cfg['warnings'].append('Nonzero density below 1e17 cm^-3 extrapolates below the concentration range examined in the paper.')
    return cfg

PROFILE_KEYS=('reference_electron_cm3','reference_hole_cm3','electron_cm3','hole_cm3')

def validate_profiles(profiles):
    if not isinstance(profiles,list) or not 2<=len(profiles)<=20000:raise ValueError('Provide 2–20,000 depth profile samples.')
    result=[];seen={}
    for row in profiles:
        layer=str(row.get('layer','')).strip()
        if not layer:raise ValueError('Every profile sample needs a layer name.')
        z=_finite(row.get('z_um'),'Layer-local z (µm)')
        side=row.get('side','')
        if side not in ('','left','right'):raise ValueError('Profile side must be left or right.')
        prior=seen.setdefault((layer,z),[])
        if prior and not (prior==['left'] and side=='right'):raise ValueError('Duplicate profile depths require explicit left then right limits.')
        prior.append(side);result.append(dict(layer=layer,z_um=z,side=side,**{k:density(row.get(k),k) for k in PROFILE_KEYS}))
    return sorted(result,key=lambda r:(r['layer'],r['z_um']))

def read_profile_csv(path):
    """One state's depth profile: layer,z_um,reference_electron_cm3,reference_hole_cm3,electron_cm3,hole_cm3."""
    with open(path,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not {'layer','z_um',*PROFILE_KEYS}.issubset(reader.fieldnames or []):raise ValueError('Depth CSV needs layer,z_um and reference/biased electron_cm3 and hole_cm3 columns.')
        rows=[]
        for row in reader:
            if len(rows)>=20000:raise ValueError('Too many depth samples.')
            rows.append(row)
    return validate_profiles(rows)

def junction_depletion(acceptor_cm3,donor_cm3,intrinsic_cm3,epsilon_r,temperature_K=300.,reverse_bias_V=0.):
    """Abrupt homojunction, complete ionization, nondegenerate Boltzmann statistics.

    Returns total W and separate p/n-side widths, not a transport solution.
    Material-specific intrinsic density and static permittivity are mandatory.
    """
    na=_finite(acceptor_cm3,'Acceptor concentration',positive=True,maximum=1e20)
    nd=_finite(donor_cm3,'Donor concentration',positive=True,maximum=1e20)
    ni=_finite(intrinsic_cm3,'Intrinsic concentration',positive=True)
    er=_finite(epsilon_r,'Relative static permittivity',positive=True)
    temp=_finite(temperature_K,'Temperature',positive=True)
    vr=_finite(reverse_bias_V,'Reverse bias (V)')
    if min(na,nd)<=ni:raise ValueError('Both dopant densities must exceed intrinsic density for this extrinsic abrupt-junction approximation.')
    thermal=1.380649e-23*temp/1.602176634e-19
    built_in=thermal*(math.log(na/ni)+math.log(nd/ni))
    width=math.sqrt(2*er*8.8541878128e-12/1.602176634e-19*(1/(na*1e6)+1/(nd*1e6))*(built_in+vr))
    return dict(built_in_V=built_in,width_um=width*1e6,p_width_um=width*1e6*nd/(na+nd),n_width_um=width*1e6*na/(na+nd),
                assumptions='Abrupt homojunction, depletion approximation, complete ionization, nondegenerate Boltzmann statistics; user must verify doping is nondegenerate. No forward-bias, heterojunction, breakdown or transport model.')

def junction_estimate(acceptor_cm3,donor_cm3,intrinsic_cm3,relative_permittivity,temperature_k=300.,reverse_bias_v=0.):
    return junction_depletion(acceptor_cm3,donor_cm3,intrinsic_cm3,relative_permittivity,temperature_k,reverse_bias_v)

def _profile_segments(model,layers,state,cfg):
    """Midpoint samples for piecewise-constant S4 slices; depth from layer top."""
    profiles=state.get('profiles')
    if not profiles:return None
    grouped={}
    for row in profiles:grouped.setdefault(row['layer'],[]).append(row)
    if set(grouped)!=set(layers):raise ValueError('Depth profiles must cover exactly every selected layer.')
    known={r['name']:r for r in model['layers']};count=cfg['profile_slices']
    if cfg.get('profile_sampling','uniform')=='uniform' and len(layers)*count>500:raise ValueError('Limit uniform depth profiles to 500 total slices.')
    segments=[]
    for layer in layers:
        thickness=_finite(known[layer].get('thickness'),layer+' thickness',positive=True)
        rows=sorted(grouped[layer],key=lambda r:r['z_um'])
        if len(rows)<2 or abs(rows[0]['z_um'])>1e-12 or abs(rows[-1]['z_um']-thickness)>1e-10:
            raise ValueError(layer+': profile needs endpoints z=0 and z=layer thickness (µm).')
        if any(r['z_um']>thickness for r in rows):raise ValueError('Depth lies outside layer.')
        # Always retain discontinuities as boundaries, including in uniform mode.
        jumps={a['z_um'] for a,b in zip(rows,rows[1:]) if a['z_um']==b['z_um']}
        boundaries=sorted(set(r['z_um'] for r in rows)) if cfg.get('profile_sampling')=='knots' else sorted({thickness*i/count for i in range(count+1)}|jumps)
        for start,stop in zip(boundaries,boundaries[1:]):
            z=(start+stop)/2
            lo,hi=next((a,b) for a,b in zip(rows,rows[1:]) if a['z_um']<=z<=b['z_um'] and b['z_um']>a['z_um'])
            t=(z-lo['z_um'])/(hi['z_um']-lo['z_um'])
            segments.append(dict(layer=layer,z_um=z,thickness=stop-start,**{k:lo[k]+t*(hi[k]-lo[k]) for k in PROFILE_KEYS}))
    if len(segments)>cfg.get('profile_max_slices',1000):raise ValueError('Profile exceeds maximum total slices; increase the explicit cap (up to 2000) or simplify the input mesh without removing jumps.')
    return segments

def state_changes(model,material,layers,state,configuration,wavelength_nm):
    """Per-layer thickness-average Δn/Δk for plot labels, not mode-effective n."""
    import cmath
    from model import epsilon
    cfg=configuration
    original=next(m for m in model['materials'] if m['name']==material)
    n=cmath.sqrt(epsilon(original,wavelength_nm)).real
    segments=_profile_segments(model,layers,state,cfg)
    changes={}
    for layer in layers:
        samples=[s for s in segments if s['layer']==layer] if segments else [{**cfg,**state}]
        values=[evaluate_state(wavelength_nm,n,s['reference_electron_cm3'],s['reference_hole_cm3'],s['electron_cm3'],s['hole_cm3'],cfg['mobility_e_cm2_Vs'],cfg['mobility_h_cm2_Vs'],cfg['mass_e_m0'],cfg['mass_h_m0'],cfg['semiconductor']) for s in samples]
        weights=[s.get('thickness',1.) for s in samples];total=sum(weights)
        changes[layer]={key:sum(v[key]*weight for v,weight in zip(values,weights))/total for key in ('delta_n','delta_k','delta_alpha_cm1')}
    return changes

def read_states_csv(path):
    """CSV: label,electron_cm3,hole_cm3,bias_v (last column optional)."""
    with open(path,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not {'electron_cm3','hole_cm3'}.issubset(reader.fieldnames or []):
            raise ValueError('CSV needs electron_cm3 and hole_cm3 columns; optional label and bias_v.')
        states=[]
        for i,row in enumerate(reader):
            if i>=200:raise ValueError('CSV is limited to 200 carrier states.')
            states.append(dict(label=row.get('label') or f'State {i+1}',electron_cm3=row['electron_cm3'],hole_cm3=row['hole_cm3'],bias_v=row.get('bias_v')))
    return validate_configuration(dict(silicon_confirmed=True,states=states))['states']

def carrier_shifted_model(model, material, layers, state, configuration):
    """Clone selected material occurrences, tabulated at every simulated wavelength.

    ``layers`` is a list of layer names, and ``state`` uses electron_cm3/hole_cm3.
    The library data must already describe the reference densities. A depletion
    that would make k negative raises instead of silently clipping away loss.
    """
    import cmath
    from model import epsilon
    cfg=validate_configuration({**configuration,'states':[state]})
    state=cfg['states'][0]
    original=next((m for m in model['materials'] if m['name']==material),None)
    if original is None:raise ValueError('Select a material in the structure.')
    if not layers or len(set(layers))!=len(layers):raise ValueError('Select unique layers for the carrier change.')
    known={l['name']:l for l in model['layers']}
    for layer in layers:
        if layer not in known or not (known[layer]['material']==material or any(p['layer']==layer and p['material']==material for p in model['patterns'])):
            raise ValueError(str(layer)+': selected material is absent.')
    wavelengths=sorted(set(float(p[1]) for p in model['points']))
    if not wavelengths:raise ValueError('No simulation wavelengths.')
    if original['model']=='table_nk' and (wavelengths[0]<original['grid'][0] or wavelengths[-1]>original['grid'][-1]):
        raise ValueError('Reference optical data must cover the full wavelength range.')
    result=copy.deepcopy(model)
    names={m['name'] for m in result['materials']}
    def clone_for(sample):
        rows=[]
        for w in wavelengths:
            nk=cmath.sqrt(epsilon(original,w))
            zero=cfg.get('optical_reference')=='undoped'
            change=evaluate_state(w,nk.real,0 if zero else sample['reference_electron_cm3'],0 if zero else sample['reference_hole_cm3'],sample['electron_cm3'],sample['hole_cm3'],cfg['mobility_e_cm2_Vs'],cfg['mobility_h_cm2_Vs'],cfg['mass_e_m0'],cfg['mass_h_m0'],cfg['semiconductor'])
            n,k=nk.real+change['delta_n'],nk.imag+change['delta_k']
            if n<=0 or k < -1e-14 or not all(math.isfinite(x) for x in (n,k)):
                raise ValueError('Carrier state produces invalid n or negative k. Reference optical data must include the reference carrier loss for depletion.')
            rows.append([w,n,max(0.,k)])
        name='__carrier_shift'
        while name in names:name+='_' 
        names.add(name)
        clone=copy.deepcopy(original)
        clone.update(name=name,model='table_nk',a=rows[0][1],b=rows[0][2],table=rows,grid=wavelengths,carrier_source=cfg['source'],carrier_state=state['label'])
        result['materials'].append(clone)
        return name
    segments=_profile_segments(model,layers,state,cfg)
    if segments:
        new_layers=[];new_patterns=[];layer_names={l['name'] for l in model['layers']}
        for layer in model['layers']:
            old_patterns=[p for p in model['patterns'] if p['layer']==layer['name']]
            if layer['name'] not in layers:
                new_layers.append(copy.deepcopy(layer));new_patterns.extend(copy.deepcopy(old_patterns));continue
            for i,segment in enumerate(s for s in segments if s['layer']==layer['name']):
                layer_name=f"{layer['name']}__carrier_{i}"
                while layer_name in layer_names:layer_name+='_' 
                layer_names.add(layer_name);mat_name=clone_for(segment)
                new_layer=copy.deepcopy(layer);new_layer.update(name=layer_name,thickness=segment['thickness'])
                if new_layer['material']==material:new_layer['material']=mat_name
                new_layers.append(new_layer)
                for pattern in old_patterns:
                    new_pattern=copy.deepcopy(pattern);new_pattern['layer']=layer_name
                    if new_pattern['material']==material:new_pattern['material']=mat_name
                    new_patterns.append(new_pattern)
        result.update(layers=new_layers,patterns=new_patterns,carrier_profile_segments=segments)
        return result
    name=clone_for({**cfg,**state})
    for row in result['layers']+result['patterns']:
        layer=row.get('layer',row.get('name'))
        if layer in layers and row['material']==material:row['material']=name
    return result
