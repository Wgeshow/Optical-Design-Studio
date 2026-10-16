"""Layer-local refractive-index sweeps; library materials are never mutated."""
import cmath
import copy
import csv
import itertools
import json
import math
from pathlib import Path

RESPONSES={'Reflection':3,'Transmission':4,'Absorption':5}

def sweep_values(start, stop, count):
    start,stop=float(start),float(stop)
    if not all(math.isfinite(v) for v in (start,stop)) or min(start,stop)<-10 or max(start,stop)>10:
        raise ValueError('Δn must be finite and between -10 and 10.')
    if isinstance(count,bool) or int(count)!=float(count) or not 1<=int(count)<=101:
        raise ValueError('Samples must be an integer from 1 to 101.')
    if stop<start or (int(count)==1 and start!=stop):
        raise ValueError('Use stop ≥ start; one sample requires equal endpoints.')
    return [start] if start==stop else [start+(stop-start)*i/(int(count)-1) for i in range(int(count))]

def validate_options(options):
    cfg=copy.deepcopy(options)
    if cfg.get('sweep_mode','manual') not in ('manual','carrier'):raise ValueError('Select manual or carrier index sweep.')
    if not isinstance(cfg.get('carrier',{}),dict):raise ValueError('Invalid carrier configuration.')
    if not isinstance(cfg.get('material',''),str): raise ValueError('Select a material.')
    if not isinstance(cfg.get('equal',True),bool): raise ValueError('Equal shift must be true or false.')
    rows=cfg.get('layers',[])
    if not isinstance(rows,list) or len(rows)>100: raise ValueError('Invalid selected layers.')
    names=[]
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('layer'),str): raise ValueError('Invalid layer selection.')
        names.append(row['layer'])
        sweep_values(row.get('start',0),row.get('stop',.02),row.get('samples',3))
    if len(set(names))!=len(names): raise ValueError('Each layer may be selected once.')
    sweep_values(cfg.get('start',0),cfg.get('stop',.02),cfg.get('samples',3))
    if cfg.get('response','Reflection') not in RESPONSES: raise ValueError('Select reflection, transmission or absorption.')
    if cfg.get('feature','Peak') not in ('Peak','Dip'): raise ValueError('Select Peak or Dip.')
    for key,default in [('reference_nm',1550),('tracking_window_nm',30)]:
        value=float(cfg.get(key,default))
        if not math.isfinite(value) or value<=0: raise ValueError(key+' must be positive and finite.')
        cfg[key]=value
    return cfg

def prepare_sweep(model,options):
    cfg=validate_options(options)
    name=cfg.get('material','')
    if not cfg.get('layers'): raise ValueError('Select at least one layer to shift.')
    if model['mode']!='Wavelength sweep': raise ValueError('Index shift requires a wavelength sweep.')
    if len(model['points'])<3: raise ValueError('Use at least three wavelength samples.')
    available={m['name']:m for m in model['materials']}
    if name not in available: raise ValueError('Select a material in the current Structure.')
    lo,hi=min(p[1] for p in model['points']),max(p[1] for p in model['points'])
    if not lo<=cfg['reference_nm']<=hi: raise ValueError('Reference wavelength must lie inside the simulation range.')
    used={l['material'] for l in model['layers']}|{r['material'] for r in model['patterns']}
    for mat in model['materials']:
        if mat['name'] in used and mat['model']=='table_nk' and (mat['grid'][0]>lo or mat['grid'][-1]<hi):
            raise ValueError(mat['name']+': optical table must cover the full wavelength range.')
    names=[r['layer'] for r in cfg['layers']]
    layers={l['name']:l for l in model['layers']}
    for name_layer in names:
        if name_layer not in layers or not (layers[name_layer]['material']==name or any(r['layer']==name_layer and r['material']==name for r in model['patterns'])):
            raise ValueError(name_layer+': selected material is not used in this layer.')
    if cfg.get('sweep_mode')=='carrier':
        from carrier_index import validate_configuration,carrier_shifted_model
        carrier=validate_configuration(cfg.get('carrier',{}))
        states=[dict(label='Reference',electron_cm3=carrier['reference_electron_cm3'],hole_cm3=carrier['reference_hole_cm3'],bias_v=None)]+carrier['states']
        if any(s.get('profiles') for s in carrier['states']):
            if not all(s.get('profiles') for s in carrier['states']):raise ValueError('Provide depth profiles for every carrier state, or use uniform concentrations for every state.')
            reference_profile=carrier['states'][0]['profiles']
            signature=lambda ps:[(r['layer'],r['z_um'],r['reference_electron_cm3'],r['reference_hole_cm3']) for r in ps]
            if any(signature(s['profiles'])!=signature(reference_profile) for s in carrier['states']):raise ValueError('All depth states must use the same depth grid and reference concentrations.')
            states[0]['profiles']=[dict(r,electron_cm3=r['reference_electron_cm3'],hole_cm3=r['reference_hole_cm3']) for r in reference_profile]
        if len(states)*len(model['points'])>200000:raise ValueError('Limit carrier sweeps to 200,000 total wavelength samples.')
        for state in states:carrier_shifted_model(model,cfg['material'],names,state,carrier)
        cfg.update(task='index_shift',carrier=carrier,carrier_states=states,equal=True,
                   assignments=[dict.fromkeys(names,0.) for _ in states])
        return cfg
    shared=sweep_values(cfg.get('start',0),cfg.get('stop',.02),cfg.get('samples',3))
    grids=[shared for _ in names] if cfg.get('equal',True) else [sweep_values(r.get('start',0),r.get('stop',.02),r.get('samples',3)) for r in cfg['layers']]
    count=len(shared) if cfg.get('equal',True) else math.prod(len(g) for g in grids)
    if count>200 or (count+1)*len(model['points'])>200000:
        raise ValueError('Limit the sweep to 200 combinations and 200,000 total wavelength samples.')
    values=[tuple(v for _ in names) for v in shared] if cfg.get('equal',True) else itertools.product(*grids)
    assignments=[dict.fromkeys(names,0.)]
    assignments += [dict(zip(names,v)) for v in values if any(abs(x)>1e-14 for x in v)]
    for assignment in assignments: shifted_model(model,cfg['material'],assignment)
    cfg.update(task='index_shift',assignments=assignments)
    return cfg

def shifted_material(material,delta):
    result=copy.deepcopy(material)
    if result['model']=='constant_eps':
        nk=cmath.sqrt(complex(result['a'],result['b']))
        result.update(model='constant_nk',a=nk.real,b=nk.imag)
    if result['model']=='table_nk':
        result['table']=[[w,n+delta,k] for w,n,k in result['table']]
        indexes=[row[1] for row in result['table']]
    else:
        result['a']+=delta
        indexes=[result['a']]
    if any(n<0 or not math.isfinite(n) for n in indexes):
        raise ValueError('Δn produces a negative or nonfinite real index for '+material['name'])
    return result

def shifted_model(model,material,assignment):
    result=copy.deepcopy(model)
    original=next(m for m in model['materials'] if m['name']==material)
    existing={m['name'] for m in result['materials']}
    for i,(layer,delta) in enumerate(assignment.items()):
        if not delta: continue
        clone=shifted_material(original,delta)
        name=f'__index_shift_{i}'
        while name in existing: name+='_' 
        existing.add(name)
        clone['name']=name
        result['materials'].append(clone)
        for row in result['layers']:
            if row['name']==layer and row['material']==material: row['material']=name
        for row in result['patterns']:
            if row['layer']==layer and row['material']==material: row['material']=name
    return result

def sampled_feature(rows,response,feature,center,window):
    col=RESPONSES[response]
    ordered=sorted(rows,key=lambda r:r[1])
    sign=1 if feature=='Peak' else -1
    candidates=[]
    for i in range(1,len(ordered)-1):
        a,b,c=ordered[i-1:i+2]
        if abs(b[1]-center)<=window and sign*b[col]>sign*a[col] and sign*b[col]>=sign*c[col]:
            candidates.append(b)
    return min(candidates,key=lambda r:abs(r[1]-center)) if candidates else None

def fixed_wavelength_readout(spectra,summary):
    """Sample every case at the SAME zero-shift feature wavelength, never its moved peak."""
    wavelength=summary.get('baseline_nm')
    column={'Reflection':'R','Transmission':'T','Absorption':'A'}[summary['response']]
    cases={}
    for row in spectra:cases.setdefault(row['case'],[]).append(row)
    selected={}
    if wavelength is not None and math.isfinite(float(wavelength)):
        for case,rows in cases.items():
            matches=[r for r in rows if math.isclose(float(r['wavelength_nm']),float(wavelength),rel_tol=0,abs_tol=1e-8)]
            if len(matches)!=1:raise ValueError('The fixed baseline wavelength must be sampled exactly once in every case.')
            selected[case]=matches[0]
    baseline=selected.get(0)
    records=[]
    for case,rows in sorted(cases.items()):
        row=selected.get(case)
        metadata=row if row is not None else rows[0]
        result=dict(case=case,baseline=case==0,**{k:v for k,v in metadata.items() if k.startswith(('dn:','dk:','dalpha:')) or k in ('state_label','electron_cm3','hole_cm3','bias_v','delta_alpha_cm1','index_evaluation_nm','index_average')},
                    wavelength_nm=wavelength,response=summary['response'],
                    value=row[column] if row else None,baseline_value=baseline[column] if baseline else None,
                    delta_value=row[column]-baseline[column] if row and baseline else None,
                    status='fixed baseline wavelength' if row and baseline else 'no resolved baseline feature')
        for key in ('R','T','A'):
            result[key]=row[key] if row else None
            result['delta_'+key]=row[key]-baseline[key] if row and baseline else None
        records.append(result)
    return records

def execute_sweep(model,performance,cfg,directory,executor,emit=lambda e:None,cancelled=lambda:False):
    from backend import Cancelled
    from optical_objective import valid_spectrum
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    names=[r['layer'] for r in cfg['layers']]
    spectra=[]; peaks=[]; baseline=None
    is_carrier=cfg.get('sweep_mode')=='carrier'
    total=len(cfg['assignments'])
    for index,assignment in enumerate(cfg['assignments']):
        if cancelled(): raise Cancelled('Index-shift sweep cancelled.')
        if is_carrier:
            from carrier_index import carrier_shifted_model,state_changes
            from model import epsilon
            state=cfg['carrier_states'][index];carrier=cfg['carrier']
            shifted=carrier_shifted_model(model,cfg['material'],names,state,carrier)
        else:shifted=shifted_model(model,cfg['material'],assignment)
        rows,info=executor(shifted,performance,lambda e:None,cancelled)
        if not valid_spectrum(rows) or len(rows)!=len(model['points']): raise ValueError('Invalid or incomplete index-shift spectrum.')
        center=cfg['reference_nm'] if baseline is None else baseline[1]
        found=sampled_feature(rows,cfg.get('response','Reflection'),cfg.get('feature','Peak'),center,cfg['tracking_window_nm'])
        if index==0: baseline=found
        if is_carrier:
            def carrier_change(w):
                return state_changes(model,cfg['material'],names,state,carrier,w)
            locked_nm=baseline[1] if baseline else cfg['reference_nm']
            change=carrier_change(locked_nm)
            assignment={n:change[n]['delta_n'] for n in names}
        common=dict(case=index,baseline=index==0,**{'dn:'+n:assignment[n] for n in names})
        if is_carrier:
            common.update(state_label=state['label'],electron_cm3=state['electron_cm3'] if not state.get('profiles') else None,hole_cm3=state['hole_cm3'] if not state.get('profiles') else None,bias_v=state.get('bias_v'),index_evaluation_nm=locked_nm,delta_alpha_cm1=change[names[0]]['delta_alpha_cm1'],index_average='thickness average; not mode effective index' if state.get('profiles') else 'uniform',**{'dk:'+n:change[n]['delta_k'] for n in names},**{'dalpha:'+n:change[n]['delta_alpha_cm1'] for n in names})
        for row in rows:
            record=dict(common,wavelength_nm=row[1],angle_deg=row[2],R=row[3],T=row[4],A=row[5])
            if is_carrier:
                spectral_change=carrier_change(row[1])
                record.update(index_evaluation_nm=row[1],delta_alpha_cm1=spectral_change[names[0]]['delta_alpha_cm1'],**{'dn:'+n:spectral_change[n]['delta_n'] for n in names},**{'dk:'+n:spectral_change[n]['delta_k'] for n in names},**{'dalpha:'+n:spectral_change[n]['delta_alpha_cm1'] for n in names})
            spectra.append(record)
        shift=found[1]-baseline[1] if found is not None and baseline is not None else None
        shared=next(iter(assignment.values()))
        sensitivity=shift/shared if shift is not None and cfg.get('equal',True) and abs(shared)>1e-14 and not (is_carrier and state.get('profiles')) else None
        peaks.append(dict(common,feature_nm=found[1] if found else None,shift_nm=shift,
            sensitivity_nm_per_RIU=sensitivity,status='sampled feature' if found and baseline else 'no resolved baseline/feature'))
        emit(dict(kind='progress',completed=index+1,total=total,text=f'Index shift: {index+1}/{total} spectra'))
    def save(name,records):
        with (directory/name).open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]))
            writer.writeheader();writer.writerows(records)
    save('index_shift_spectra.csv',spectra)
    save('index_shift_features.csv',peaks)
    save('results.csv',[{k:r[k] for k in ('wavelength_nm','angle_deg','R','T','A')} for r in spectra if r['case']==0])
    summary=dict(status='complete',task='index_shift',spectra=total,material=cfg['material'],equal=cfg.get('equal',True),layers=names,response=cfg.get('response','Reflection'),feature=cfg.get('feature','Peak'),baseline_nm=baseline[1] if baseline else None,
        note='Nearest sampled local feature relative to baseline; mode identity and basis convergence are not verified. Sensitivity is a finite difference, not a fitted derivative.')
    summary['sweep_mode']=cfg.get('sweep_mode','manual')
    if is_carrier:
        summary['depth_profiles']=any(s.get('profiles') for s in cfg['carrier_states'])
        summary['optical_reference']=cfg['carrier'].get('optical_reference','reference')
        summary['profile_sampling']=cfg['carrier'].get('profile_sampling','uniform')
        summary.update(carrier_model=cfg['carrier']['model'],carrier_source=cfg['carrier']['source'],carrier_limitations=cfg['carrier']['limitations'],carrier_warnings=cfg['carrier']['warnings'])
        summary['note']+=' Carrier Δn and Δk change together; response versus Δn is specific to this carrier path.'
    readout=fixed_wavelength_readout(spectra,summary)
    save('index_shift_readout.csv',readout)
    summary['baseline_response']=readout[0]['baseline_value']
    (directory/'index_shift_config.json').write_text(json.dumps(cfg,indent=2),encoding='utf-8')
    (directory/'search_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return dict(kind='search_complete',directory=str(directory),summary=summary)
