"""S4 field training with optional simulation limits and constrained Bayesian search.

Checkpoints store observations and paths, never executable model objects.
Held-out designs are excluded from fitting, acquisition, and ranking.
"""
import copy
import hashlib
import itertools
import math
import time
from pathlib import Path
import numpy as np
from data_library import read_json, write_json
from field_storage import field_data_exists, copy_field_data
from ml_optimizer import model_for, encode, value_key, fit_predict, dependencies, expected_improvement
from peak_optimizer import parse_search, geometry_error, write_csv
from airhole_field_objective import aligned_hole, targets, choose_candidate,shape_covariates,feature_values

DEFAULTS=dict(basis=32,polarization='p',theta_deg=0.,phi_deg=0.,wavelength_nm=1550.,mode='Budgeted adaptive',initial=20,test_count=5,adaptive=15,
    new_budget=0,grid=9,depth_samples=3,contour_step=.1,contrast_target=3.,coverage_target=.8,
    shell_um=.02,finalists=2,verification_factor=1.5,verification_grid=17,agreement=.1,
    half_window=10.,rta_step=.5,reuse=True,seed=42,operation='collect',approach='discover',
    reference_directory='',reference_weight=1.,resume_file='',link_holes=True)


def validate_options(options):
    cfg=dict(DEFAULTS,**options)
    from decimal import Decimal, InvalidOperation
    for key,lo,hi in [('initial',1,None),('test_count',0,None),('adaptive',0,None),
                     ('new_budget',0,None),('grid',3,40),('depth_samples',3,40),
                     ('basis',1,4096),('finalists',0,None),('verification_grid',3,80),('seed',0,2147483647)]:
        v=cfg[key]
        try:
            n=Decimal(str(v).strip())
            valid=not isinstance(v,bool) and n.is_finite() and n==n.to_integral_value() and n>=lo and (hi is None or n<=hi)
        except InvalidOperation:valid=False
        if not valid:
            extent=f'from {lo} to {hi}' if hi is not None else f'at least {lo}'
            raise ValueError(f'{key} must be a whole number {extent}')
        cfg[key]=int(n)
    if cfg['polarization'] not in ('p','s','45° s+p'):raise ValueError('Unknown AI incident-light polarization')
    for key,limit in (('theta_deg',89.999999),('phi_deg',360.)):
        cfg[key]=float(cfg[key])
        if not math.isfinite(cfg[key]) or abs(cfg[key])>limit:raise ValueError(key+' is outside the supported angle range')
    for key in ('wavelength_nm','contour_step','contrast_target','shell_um','half_window','rta_step','verification_factor','agreement','reference_weight'):
        cfg[key]=float(cfg[key])
        if not math.isfinite(cfg[key]) or cfg[key]<=0:raise ValueError(key+' must be positive and finite')
    cfg['coverage_target']=float(cfg['coverage_target'])
    if not 0<=cfg['coverage_target']<=1:raise ValueError('Coverage must be between 0 and 1')
    if not 1<cfg['verification_factor']<=4:raise ValueError('Verification factor must be >1 and ≤4')
    if cfg['agreement']>1:raise ValueError('Agreement tolerance must be ≤1')
    if cfg['mode'] not in ('Budgeted adaptive','Full range scan'):raise ValueError('Unknown scan mode')
    if cfg['operation'] not in ('collect','fit','search','verify'):raise ValueError('Unknown campaign operation')
    if cfg['approach'] not in ('discover','reference'):raise ValueError('Unknown field target approach')
    if cfg['approach']=='reference' and not cfg['reference_directory']:raise ValueError('Choose a saved field directory for the shape reference')
    for key in ('reuse','link_holes'):
        if not isinstance(cfg[key],bool):raise ValueError(key+' must be true or false')
    if cfg['wavelength_nm']<=cfg['half_window']:raise ValueError('RTA window must remain above zero wavelength')
    if math.ceil(2*cfg['half_window']/cfg['rta_step'])>400:raise ValueError('RTA scan exceeds 401 points; increase its step')
    return cfg


def prepare_campaign(base,options,runs=None):
    cfg=validate_options(options);bounds=copy.deepcopy(options.get('bounds',[]))
    # Offer one hole-radius range linked through the perforated stack.
    if cfg['link_holes']:
        for row in bounds:
            if row['Parameter'] in ('radius','r_over_a','center_x','center_y'):
                index=int(row['Target'])-1;p=base['patterns'][index]
                row['linked_targets']=[i+1 for i,q in enumerate(base['patterns']) if i!=index and q['shape']==p['shape'] and all(q[k]==p[k] for k in ('cx','cy','sx'))]
    fake=copy.deepcopy(base);fake['mode']='Wavelength sweep';fake['points']=[[i,cfg['wavelength_nm']+(i-1)*.1,base['points'][0][2]] for i in range(3)]
    gridcfg=parse_search(fake,bounds,dict(search_mode='ML assisted',design_budget=10000,absorption_target=.99,ratio_limit=.49))
    cfg['input_bounds']=bounds
    cfg.update(dimensions=gridcfg['dimensions'],design_count=gridcfg['design_count'],ratio_limit=.49,min_bridge_um=0.,separate_circles=True)
    for dimension in cfg['dimensions']:
        if not dimension['parameter'].endswith('_material'):dimension['values']=[round(v,12) for v in dimension['values']]
    aligned_hole(base,cfg['shell_um'])
    if math.ceil(base['basis']*cfg['verification_factor'])>4096:raise ValueError('Verification basis exceeds 4096')
    if cfg['mode']=='Full range scan' and cfg['new_budget'] and cfg['design_count']>cfg['new_budget']:
        raise ValueError(f"Full scan has {cfg['design_count']:,} designs, exceeding the new-simulation budget. Remove or increase the optional limit, use adaptive sampling, or narrow ranges.")
    cfg['runs']=str(runs or '')
    return cfg


def measurement_key(model,cfg,verified=False):
    m=copy.deepcopy(model);theta=m['points'][0][2]
    for k in ('points','warnings','mode'):m.pop(k,None)
    spec=dict(model=m,theta=theta,wavelength=cfg['wavelength_nm'],grid=cfg['verification_grid'] if verified else cfg['grid'],
              depths=cfg['depth_samples'],contour_step=cfg['contour_step'],shell=cfg['shell_um'],contrast=cfg['contrast_target'],coverage=cfg['coverage_target'],
              half_window=cfg['half_window'],rta_step=cfg['rta_step'],schema=2)
    return hashlib.sha256(__import__('json').dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def campaign_key(base,cfg):
    return measurement_key(base,cfg)+hashlib.sha256(__import__('json').dumps(cfg['dimensions'],sort_keys=True).encode()).hexdigest()


def candidates(base,cfg,seen,count,seed):
    dims=cfg['dimensions'];rng=np.random.default_rng(seed)
    if count<=0:return []
    if cfg['mode']=='Full range scan' or count>=cfg['design_count']:
        choices=itertools.product(*(d['values'] for d in dims))
    elif cfg['design_count']<=10000:
        choices=list(itertools.product(*(d['values'] for d in dims)));rng.shuffle(choices)
    else:
        sampler=dependencies()[4].LatinHypercube(d=max(1,len(dims)),seed=seed)
        choices=[[d['values'][min(len(d['values'])-1,int(u*len(d['values'])))] for d,u in zip(dims,row)] for row in sampler.random(max(count*4,128))]
    result=[];used=set(seen)
    for values in choices:
        values=list(values);key=value_key(values)
        if key in used:continue
        used.add(key);m=model_for(base,cfg,values)
        if geometry_error(m,cfg):continue
        try:aligned_hole(m,cfg['shell_um'])
        except ValueError:continue
        result.append(values)
        if len(result)>=count:break
    return result


def field_features(record):
    p=Path(record['field_directory'])/'field_features.json'
    return read_json(p).get('contour_features',{}) if p.is_file() else {}


def training_observations(records,cfg):
    out=[]
    for r in records:
        if r['phase'] not in ('train','adaptive') or r.get('status')!='complete':continue
        f=copy.deepcopy(r['fields']);f['contour_features']=feature_values(f);f['contour_features'].update(field_features(r))
        if cfg.get('approach')=='reference' and r.get('reference_distance') is not None:
            f['objective']/=1+cfg['reference_weight']*r['reference_distance']
        out.append(dict(x=encode(r['values'],cfg['dimensions']),fields=f))
    return out


def validate_model(records,cfg):
    train=training_observations(records,cfg);test=[r for r in records if r['phase']=='test' and r.get('status')=='complete']
    report=dict(training_designs=len(train),test_designs=len(test),status='insufficient training data',measurements=[])
    if len(train)<2:return report
    x=[r['x'] for r in train];y=np.array([targets(r['fields']) for r in train]);query=[encode(r['values'],cfg['dimensions']) for r in test]
    report['status']='fitted; no independent test designs' if not test else 'validated on held-out designs'
    if not test:return report
    x,query,shape=shape_covariates(train,query,fit_predict);report['shape_model']=shape
    actual_fields=[]
    for r in test:
        f=copy.deepcopy(r['fields'])
        if cfg.get('approach')=='reference' and r.get('reference_distance') is not None:f['objective']/=1+cfg['reference_weight']*r['reference_distance']
        actual_fields.append(targets(f))
    actual=np.array(actual_fields);names=['log_exterior_objective','log_volume_contrast','log_xz_contrast','volume_coverage','xz_coverage']
    for j,name in enumerate(names):
        mu,sd,warnings=fit_predict(x,y[:,j],query,.015)
        report['measurements'].append(dict(name=name,mae=float(np.mean(abs(mu-actual[:,j]))),rmse=float(np.sqrt(np.mean((mu-actual[:,j])**2))),
            interval_95_coverage=float(np.mean(abs(mu-actual[:,j])<=1.96*sd)),predictions=mu.tolist(),std=sd.tolist(),measured=actual[:,j].tolist(),warnings=warnings))
    report['test_values']=[r['values'] for r in test]
    return report


def execute_campaign(base,perf,cfg,directory,executor,emit=lambda e:None,cancelled=lambda:False,field_executor=None):
    from backend import Cancelled
    from field_solver import execute_fields
    field_executor=field_executor or execute_fields;directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();records=[];new=0;reused=0;failures=[];plan=[];fit_report={};cache={};field_cache={};fields_reused=0;reference=[]
    if cfg['approach']=='reference':
        for reference_path in cfg['reference_directory'].split(';'):
            ref=read_json(Path(reference_path.strip())/'field_features.json')
            if abs(ref['wavelength_nm']-cfg['wavelength_nm'])>1e-8 or ref['grid']!=cfg['grid']:
                raise ValueError('Reference wavelength and field grid must match this campaign')
            features=ref.get('contour_features',{})
            if not features:raise ValueError('Reference needs contour features; analyze its saved fields first')
            reference.append(features)
    def reference_distance(feature):
        distances=[]
        for ref in reference:
            if set(ref)!=set(feature):raise ValueError('Reference contour sampling is incompatible')
            distances.append(float(np.mean([(feature[k]-ref[k])**2 for k in ref])))
        return min(distances)

    def checkpoint(status='running'):
        summary=dict(status=status,task='ai_search',new_simulations=new,reused=reused,completed=len([r for r in records if r.get('status')=='complete']),
                     training=len([r for r in records if r['phase'] in ('train','adaptive') and r.get('status')=='complete']),
                     tests=len([r for r in records if r['phase']=='test' and r.get('status')=='complete']),failures=len(failures),elapsed_seconds=time.monotonic()-started,
                     fields_reused=fields_reused,budget=cfg['new_budget'],plan_count=len(plan),validation=fit_report)
        write_json(directory/'campaign.json',dict(schema_version=1,fingerprint=campaign_key(base,cfg),base=base,settings=cfg,plan=plan,records=records,failures=failures,summary=summary))
        write_json(directory/'search_summary.json',summary)
        import json
        (directory/'design_models.jsonl').write_text(''.join(json.dumps(dict(design_id=i+1,model=r['model']),separators=(',',':'))+'\n' for i,r in enumerate(records)),encoding='utf-8')
        return summary
    if cfg.get('resume_file'):
        old=read_json(cfg['resume_file'])
        same_measurements=old.get('fingerprint')==campaign_key(base,cfg)
        old_settings=old.get('settings',{})
        same_plan=all(old_settings.get(k,DEFAULTS[k])==cfg[k] for k in ('mode','initial','test_count','seed'))
        if not same_measurements or not same_plan:
            if cfg['operation'] in ('fit','verify'):
                raise ValueError('Saved campaign settings differ. Restore its settings to fit or verify it, or use Collect and train / Run AI search to start a new campaign.')
            emit(dict(kind='log',text='Settings changed since the selected checkpoint. Starting a new campaign; the original saved results are preserved.'))
            cfg['resume_file']=''
        else:
            records=old['records'];plan=old.get('plan',[]);failures=old.get('failures',[])
            records=[r for r in records if r.get('status')=='complete' and (Path(r['field_directory'])/'field_features.json').is_file()]
    if reference:
        for record in records:
            if record['phase']!='verification':record['reference_distance']=reference_distance(field_features(record))
    # Campaign reuse requires an exact physical/numerical measurement key and complete fields/RTA.
    if cfg['reuse'] and cfg.get('runs'):
        for path in Path(cfg['runs']).glob('*/campaign.json'):
            if path.parent==directory:continue
            try:
                saved=read_json(path)
                for r in saved.get('records',[]):
                    if r.get('status')=='complete' and (Path(r['field_directory'])/'field_features.json').is_file() and r.get('rta'):
                        cache[r['measurement_key']]=r
            except (OSError,ValueError,KeyError):continue
    # Saved compatible raw fields can be re-analyzed without another field solve.
    if cfg['reuse'] and cfg.get('runs'):
        roots=Path(cfg['runs']);paths=[]
        for pattern in ('*/fields/field_model.json','*/recommended_fields/field_model.json','*/designs/*/fields/field_model.json','*/evaluations/*/fields/field_model.json'):
            paths.extend(roots.glob(pattern))
        for path in paths:
            try:
                snapshot=read_json(path);settings=snapshot.get('settings',{});folder=path.parent
                if settings.get('grid')!=cfg['grid'] or settings.get('depth_samples',3)!=cfg['depth_samples'] or settings.get('contour_step',.1)!=cfg['contour_step'] or abs(snapshot['wavelength_nm']-cfg['wavelength_nm'])>1e-8:continue
                metrics=read_json(folder/'airhole_field_metrics.json');msettings=metrics['settings']
                if any(msettings[k]!=cfg[k] for k in ('shell_um','contrast_target','coverage_target')):continue
                if not field_data_exists(folder):continue
                field_cache[measurement_key(snapshot['model'],cfg)]=folder
            except (OSError,ValueError,KeyError):continue

    if not plan:
        size=cfg['design_count'] if cfg['mode']=='Full range scan' else min(cfg['design_count'],cfg['initial']+cfg['test_count'])
        values=candidates(base,cfg,set(),size,cfg['seed'])
        if cfg['mode']!='Full range scan':
            from target_optimizer import values_for
            try:
                original=values_for(base,cfg)
                original=[round(v,12) if isinstance(v,(float,int)) else v for v in original]
                values=[original]+[v for v in values if value_key(v)!=value_key(original)]
                values=values[:size]
            except ValueError:pass
        tests=min(cfg['test_count'],max(0,len(values)-2));test_indices=set(np.random.default_rng(cfg['seed']+1).choice(np.arange(1,len(values)) if cfg['mode']!='Full range scan' else np.arange(len(values)),tests,replace=False).tolist()) if values else set()
        plan=[dict(values=v,phase='test' if i in test_indices else 'train') for i,v in enumerate(values)]
    checkpoint()
    def measure(values,phase,prediction=None):
        nonlocal new,reused,fields_reused
        if cancelled():raise Cancelled('Campaign paused; completed designs saved')
        model=model_for(base,cfg,values);verified=phase=='verification'
        if verified:model['basis']=min(4096,math.ceil(base['basis']*cfg['verification_factor']))
        key=measurement_key(model,cfg,verified)
        if key in cache:
            record=copy.deepcopy(cache[key]);record.update(values=values,phase=phase,reused=True,prediction=prediction);reused+=1
            if reference:
                if verified:
                    record['reference_distance']=next((r.get('reference_distance',0.) for r in records if r['phase'] in ('train','adaptive') and value_key(r['values'])==value_key(values)),0.)
                else:record['reference_distance']=reference_distance(field_features(record))
        else:
            if cfg['new_budget'] and new>=cfg['new_budget']:return None
            new+=1;folder=directory/'designs'/f'{len(records)+len(failures)+1:06d}';folder.mkdir(parents=True,exist_ok=True)
            write_json(folder/'model.json',model)
            emit(dict(kind='campaign_progress',completed=new-1,total=cfg['new_budget'] or (len(plan)+(cfg['adaptive'] if cfg['operation']=='search' and cfg['mode']!='Full range scan' else 0)+(cfg['finalists'] if cfg['operation'] in ('search','verify') else 0)),text=f'{phase}: S4 fields and visible RTA',phase=phase))
            fieldcfg=dict(wavelength_nm=cfg['wavelength_nm'],grid=cfg['verification_grid'] if verified else cfg['grid'],depth_samples=cfg['depth_samples'],maps=True,
                          track_contours=True,contour_step=cfg['contour_step'],sampling_mode='fixed_target',airhole_settings=dict(shell_um=cfg['shell_um'],contrast_target=cfg['contrast_target'],coverage_target=cfg['coverage_target']))
            try:
                if not verified and key in field_cache:
                    import shutil
                    source=field_cache[key];destination=folder/'fields';destination.mkdir(exist_ok=True)
                    copy_field_data(source,destination)
                    for filename in ('field_model.json','airhole_field_metrics.json'):
                        shutil.copy2(source/filename,destination/filename)
                    from field_tracking import enrich_fields
                    descriptor=enrich_fields(destination);fields_reused+=1
                    emit(dict(kind='log',text='Reused and analyzed compatible saved fields; only the RTA scan needs solver work.'))
                else:
                    descriptor=field_executor(model,perf,fieldcfg,folder/'fields',cancelled)
                if 'airhole_views' not in descriptor:raise ValueError('Airhole measurements unavailable for this geometry')
                spectrum=copy.deepcopy(model);waves=np.linspace(cfg['wavelength_nm']-cfg['half_window'],cfg['wavelength_nm']+cfg['half_window'],math.ceil(2*cfg['half_window']/cfg['rta_step'])+1)
                spectrum['points']=[[i,float(w),model['points'][0][2]] for i,w in enumerate(waves)]
                rows,_=executor(spectrum,perf,emit,cancelled);rta=[dict(wavelength_nm=r[1],R=r[3],T=r[4],A=r[5]) for r in rows]
                write_json(folder/'rta.json',rta)
                fields=copy.deepcopy(descriptor['airhole_views']);fields.pop('contour_features',None)
                record=dict(status='complete',values=values,phase=phase,model=model,measurement_key=key,field_directory=str((folder/'fields').resolve()),fields=fields,rta=rta,reused=False,prediction=prediction)
                if reference:
                    if verified:
                        record['reference_distance']=next((r.get('reference_distance',0.) for r in records if r['phase'] in ('train','adaptive') and value_key(r['values'])==value_key(values)),0.)
                        record['reference_distance_accuracy']='screening grid; verification confirms strength constraints'
                    else:record['reference_distance']=reference_distance(descriptor.get('contour_features',{}))
                write_json(folder/'observation.json',record)
            except Cancelled:raise
            except Exception as exc:
                failures.append(dict(values=values,phase=phase,error=str(exc)));checkpoint();emit(dict(kind='log',text='Design failed: '+str(exc)));return None
        records.append(record);checkpoint();emit(dict(kind='campaign_observation',record=record,completed=new,total=cfg['new_budget'] or (len(plan)+(cfg['adaptive'] if cfg['operation']=='search' and cfg['mode']!='Full range scan' else 0)+(cfg['finalists'] if cfg['operation'] in ('search','verify') else 0)),text=f"{phase} complete · {len(records)} saved observations"))
        return record
    try:
        if cfg['operation'] in ('collect','search'):
            for item in plan:
                if any(r['phase']==item['phase'] and value_key(r['values'])==value_key(item['values']) for r in records):continue
                if cfg['new_budget'] and new>=cfg['new_budget']:break
                measure(item['values'],item['phase'])
        if cfg['operation']=='search' and cfg['mode']!='Full range scan':
            existing=sum(r['phase']=='adaptive' for r in records)
            for iteration in range(existing,cfg['adaptive']):
                if cancelled():raise Cancelled('Campaign paused')
                if cfg['new_budget'] and new>=cfg['new_budget']-cfg['finalists']:break
                train=training_observations(records,cfg);seen={value_key(r['values']) for r in records}|{value_key(r['values']) for r in failures}
                pool=candidates(base,cfg,seen,256,cfg['seed']+len(records)+iteration)
                if not pool:break
                if len(train)>=4:
                    if iteration%5==4:
                        x=[r['x'] for r in train];y=[targets(r['fields'])[0] for r in train];_,sd,_=fit_predict(x,y,[encode(v,cfg['dimensions']) for v in pool],.015)
                        index=int(np.argmax(sd));prediction=dict(reason='uncertainty exploration')
                    else:index,prediction=choose_candidate(train,[encode(v,cfg['dimensions']) for v in pool],fit_predict,dependencies()[3],expected_improvement,dict(contrast_target=cfg['contrast_target'],coverage_target=cfg['coverage_target']))
                else:index=0;prediction=dict(reason='initial coverage; fewer than four training designs')
                measure(pool[index],'adaptive',prediction)
        fit_report=validate_model(records,cfg);write_json(directory/'model_validation.json',fit_report)
        eligible=[r for r in records if r.get('status')=='complete' and r['phase'] in ('train','adaptive')]
        def rank(r):
            f=r['fields'];score=f['objective']/(1+cfg['reference_weight']*r.get('reference_distance',0.))
            c=f['constraints'];shortfall=sum(max(0.,1-(c[k] or 0)/target) for k,target in [('volume_rms_contrast',cfg['contrast_target']),('xz_rms_contrast',cfg['contrast_target']),('volume_coverage',max(cfg['coverage_target'],1e-9)),('xz_coverage',max(cfg['coverage_target'],1e-9))])
            return (f['feasible'],-shortfall,score)
        eligible.sort(key=rank,reverse=True)
        if cfg['operation'] in ('search','verify'):
            for leader in eligible[:cfg['finalists']]:
                previous=next((r for r in records if r['phase']=='verification' and value_key(r['values'])==value_key(leader['values'])),None)
                check=previous or measure(leader['values'],'verification')
                if check:
                    relative=abs(check['fields']['objective']-leader['fields']['objective'])/max(leader['fields']['objective'],1e-12)
                    a=check['fields']['constraints'];b=leader['fields']['constraints']
                    differences={k:abs((a[k] or 0)-(b[k] or 0))/max(abs(b[k] or 0),1e-12) for k in ('volume_rms_contrast','xz_rms_contrast')}
                    differences.update({k:abs(a[k]-b[k]) for k in ('volume_coverage','xz_coverage')})
                    check['agreement_relative']=relative;check['constraint_agreement']=differences
                    check['verified']=relative<=cfg['agreement'] and all(v<=cfg['agreement'] for v in differences.values()) and check['fields']['feasible']
        verified=[r for r in records if r.get('verified')]
        if verified:
            best=max(verified,key=rank);write_json(directory/'recommended_design.json',dict(model=best['model'],record=best))
        # Candidates remain visibly separate from verified recommendations.
        rows=[]
        for i,r in enumerate(records):
            c=r['fields']['constraints'];rows.append(dict(design_id=i+1,phase=r['phase'],feasible=r['fields']['feasible'],verified=r.get('verified',False),volume_contrast=c['volume_rms_contrast'],xz_contrast=c['xz_rms_contrast'],coverage=c['volume_coverage'],xz_coverage=c['xz_coverage'],exterior_objective=r['fields']['objective'],reused=r.get('reused',False)))
        write_csv(directory/'design_results.csv',rows)
        summary=checkpoint('no successful designs' if not records else 'complete' if not cfg['new_budget'] or new<cfg['new_budget'] else 'budget reached');summary.update(verified_designs=len(verified),candidate_designs=len(eligible),best_candidate=rows[records.index(eligible[0])] if eligible else None)
        write_json(directory/'search_summary.json',summary)
        return dict(kind='search_complete',directory=str(directory),summary=summary)
    except Cancelled:
        return dict(kind='search_complete',directory=str(directory),summary=checkpoint('paused'))
