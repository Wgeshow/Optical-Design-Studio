"""Targeted constrained search with compatible saved spectra and field-guided exploration."""
import copy
import csv
import json
import math
from pathlib import Path
import time
import numpy as np

from data_library import read_json, write_json
from ml_optimizer import model_for, value_key, pick_candidate, candidate_pool, encode, fit_predict
from peak_optimizer import spectrum_peaks, refinement_points, conditions, geometry_error, write_csv
from field_ml import field_augmented_candidate, _usable_descriptor
from field_tracking import compare_fields, enrich_fields, feature_vector


def target_metrics(rows, cfg):
    peaks,_ = spectrum_peaks(rows,cfg['prominence'])
    near = [p for p in peaks if abs(p['wavelength_nm']-cfg['target_nm']) <= cfg['tolerance_nm']+1e-10]
    resolved = [p for p in near if p['Q_estimate'] is not None]
    eligible = [p for p in resolved if p['absorption'] > cfg['absorption_target'] and p['Q_estimate'] >= cfg['minimum_q']]
    selected = max(eligible,key=lambda p:p['Q_estimate'],default=None)
    selected = selected or max(resolved,key=lambda p:p['absorption'],default=None)
    at = min(rows,key=lambda r:abs(r[1]-cfg['target_nm']))
    absorption = max((p['absorption'] for p in near),default=at[5])
    return dict(absorption=absorption, log_q=math.log(selected['Q_estimate']) if selected else None,
                q_absorption=selected['absorption'] if selected else None,
                q_wavelength=selected['wavelength_nm'] if selected else None,
                feasible_q=max((p['Q_estimate'] for p in eligible),default=None),
                absorption_at_target=at[5] if abs(at[1]-cfg['target_nm']) < 1e-8 else None,
                selected_peak=selected, all_peaks=peaks)


def family(model,cfg):
    model=copy.deepcopy(model)
    theta=model['points'][0][2]
    for key in ('points','warnings','basis'):
        model.pop(key,None)
    model['theta']=theta
    for d in cfg['dimensions']:
        p,i=d['parameter'],d['index']
        if p.startswith('lattice_'):
            for key in (('ax','ay') if p=='lattice_square' else ('ax',) if p=='lattice_x' else ('ay',)):
                model[key]=None
        elif p in ('thickness','layer_material'):
            model['layers'][i][d['field']]=None
        else:
            model['patterns'][i][d['field']]=None
    return model


def values_for(model,cfg):
    values=[]
    for d in cfg['dimensions']:
        p,i=d['parameter'],d['index']
        if p=='lattice_square' and model['ax'] != model['ay']:
            raise ValueError('Nonsquare saved lattice')
        if p.startswith('lattice_'):
            v=model['ay'] if p=='lattice_y' else model['ax']
        elif p in ('thickness','layer_material'):
            v=model['layers'][i][d['field']]
        else:
            v=model['patterns'][i][d['field']]
            if p=='r_over_a': v/=min(model['ax'],model['ay'])
        if p.endswith('_material'):
            if v not in d['values']: raise ValueError('Material outside current bounds')
        elif not d['values'][0] <= v <= d['values'][-1]:
            raise ValueError('Geometry outside current bounds')
        values.append(v)
    return values


def compatible_record(model,rows,base,cfg,source,fields=None,resonance_fields=None):
    if model['basis'] != base['basis'] or family(model,cfg) != family(base,cfg):
        return None
    values=values_for(model,cfg)
    if geometry_error(model,cfg): return None
    rows=sorted(rows,key=lambda r:r[1])
    low,high=base['points'][0][1],base['points'][-1][1]
    if not rows or rows[0][1]>low+1e-8 or rows[-1][1]<high-1e-8: return None
    rows=[r for r in rows if low<=r[1]<=high]
    if len(rows)<3 or len({r[1] for r in rows})!=len(rows): return None
    if any(len(r)!=6 or not all(math.isfinite(float(v)) for v in r) or not -1e-8<=r[5]<=1 or r[2]!=base['points'][0][2] for r in rows): return None
    def valid_field(descriptor,mode):
        try:
            return descriptor if _usable_descriptor(descriptor,cfg,mode) and feature_vector(descriptor) else None
        except (ValueError,KeyError,TypeError,OverflowError): return None
    fields=valid_field(fields,'fields')
    resonance_fields=valid_field(resonance_fields,'resonance_fields')
    targets=target_metrics(rows,cfg)
    if resonance_fields and (not targets['selected_peak'] or abs(resonance_fields['wavelength_nm']-targets['selected_peak']['wavelength_nm'])>1e-6):
        resonance_fields=None
    return dict(values=values,model=model,rows=rows,targets=targets,fields=fields,
                resonance_fields=resonance_fields,
                phase='exploration',status='evaluated',source=source,verification='saved training data; rerun before recommendation')


def load_training(runs,base,cfg):
    records,seen,skipped=[],set(),0
    if not cfg.get('reuse_saved',True): return records,skipped
    for directory in sorted(Path(runs).iterdir(),key=lambda p:p.stat().st_mtime,reverse=True):
        if not directory.is_dir(): continue
        if len(records)>=cfg['history_limit']: break
        candidates=[]
        try:
            if (directory/'target_history.json').exists():
                for o in read_json(directory/'target_history.json').get('observations',[]):
                    if o.get('status')=='evaluated' and o.get('source')=='new':
                        candidates.append((o['model'],o['rows'],o.get('fields'),o.get('resonance_fields'),o.get('id')))
            elif (directory/'optimization_history.json').exists():
                history=read_json(directory/'optimization_history.json')
                for o in history.get('observations',[]):
                    if o.get('status')=='evaluated':
                        m=model_for(history['base_model'],history['options'],o['values'])
                        m['basis']=o['basis']
                        candidates.append((m,o['rows'],None,None,o.get('id')))
            elif (directory/'job.json').exists() and (directory/'results.csv').exists():
                job=read_json(directory/'job.json')
                with (directory/'results.csv').open() as stream:
                    rows=[[i,*[float(r[k]) for k in ('wavelength_nm','angle_deg','R','T','A')]] for i,r in enumerate(csv.DictReader(stream))]
                candidates.append((job['model'],rows,None,None,None))
            elif (directory/'design_models.jsonl').exists():
                with (directory/'design_models.jsonl').open() as stream:
                    for line in stream:
                        o=json.loads(line)
                        path=directory/f'design_{o["design_id"]}_spectrum.csv'
                        if not path.exists(): continue
                        with path.open() as spectra:
                            rows=[[i,*[float(r[k]) for k in ('wavelength_nm','angle_deg','R','T','A')]] for i,r in enumerate(csv.DictReader(spectra))]
                        candidates.append((o['model'],rows,None,None,o.get('design_id')))
            for model,rows,fields,resonance_fields,source_id in candidates:
                try:
                    record=compatible_record(model,rows,base,cfg,str(directory.name),fields,resonance_fields)
                    if record and value_key(record['values']) not in seen:
                        record.update(id=len(records)+1,source_design_id=source_id)
                        seen.add(value_key(record['values']))
                        records.append(record)
                        if len(records)>=cfg['history_limit']: break
                    else: skipped+=1
                except (ValueError,KeyError,IndexError,TypeError): skipped+=1
        except (OSError,ValueError,KeyError,IndexError,TypeError): skipped+=1
    return records,skipped


def load_saved_fields(runs,base,cfg):
    records=[]
    seen=set()
    if not cfg.get('reuse_saved',True) or not cfg.get('use_fields'): return records
    for path in Path(runs).rglob('field_features.json'):
        if len(records)>=cfg['history_limit']: break
        try:
            descriptor=read_json(path)
            model=read_json(path.parent/'field_model.json')['model']
            if (descriptor.get('grid')!=cfg['field_grid']
                    or model['basis']!=base['basis'] or family(model,cfg)!=family(base,cfg)):
                continue
            if descriptor.get('schema_version')!=2 and (path.parent/'electric_fields.csv').exists():
                descriptor=enrich_fields(path.parent)
            mode='resonance_fields' if descriptor.get('sampling_mode')=='selected_resonance' else 'fields'
            if not _usable_descriptor(descriptor,cfg,mode): continue
            if mode=='resonance_fields':
                # Re-evaluate the selected peak for today's optical constraints.
                spectrum_path=path.parent.parent/'spectrum.csv'
                if not spectrum_path.exists(): continue
                with spectrum_path.open() as stream:
                    spectral_rows=[[i,*[float(r[k]) for k in ('wavelength_nm','angle_deg','R','T','A')]] for i,r in enumerate(csv.DictReader(stream))]
                selected=target_metrics(spectral_rows,cfg)['selected_peak']
                if not selected or abs(selected['wavelength_nm']-descriptor['wavelength_nm'])>1e-6: continue
            if not math.isfinite(float(descriptor['log_concentration'])): continue
            values=values_for(model,cfg)
            key=(mode,value_key(values))
            if key in seen or geometry_error(model,cfg): continue
            seen.add(key)
            records.append(dict(values=values,status='evaluated',phase='exploration',source=str(path.parent),**{mode:descriptor}))
        except (OSError,ValueError,KeyError,TypeError,IndexError): continue
    return records


def field_candidate(pool,observations,cfg):
    usable=[o for o in observations if o.get('fields') and o['status']=='evaluated'][-128:]
    if len(usable)<4: return None
    x=[encode(o['values'],cfg['dimensions']) for o in usable]
    c=[encode(v,cfg['dimensions']) for v in pool]
    mean,std,_=fit_predict(x,[o['fields']['log_concentration'] for o in usable],c,.05)
    index=int(np.argmax(mean+2*std))
    return pool[index],dict(selection_reason='field concentration / uncertainty exploration', predicted_log_field=float(mean[index]),field_std=float(std[index]))


def execute_target_search(base,perf,cfg,directory,executor,emit,cancelled,field_executor=None):
    from backend import Cancelled
    from field_solver import execute_fields
    field_executor=field_executor or execute_fields
    directory=Path(directory)
    observations,skipped=load_training(directory.parent,base,cfg)
    reused=len(observations)
    saved_fields=load_saved_fields(directory.parent,base,cfg)
    started=time.monotonic()
    spent=0
    errors=[]
    screened=set()
    status='complete'
    recommendation=None

    def checkpoint():
        write_json(directory/'target_history.json',dict(format='s4-target-history-v1',options=cfg,base_model=base,observations=observations))

    def guard():
        if cancelled(): raise Cancelled('Target search cancelled; completed spectra and fields retained')
        remaining=perf['timeout_seconds']-(time.monotonic()-started)
        if remaining<1: raise TimeoutError('Whole-search time budget reached')
        return remaining

    def track(record,folder):
        """Compare with a nearby measured design, preserving reference identity."""
        record['field_tracking']={}
        for mode in ('fields','resonance_fields'):
            descriptor=record.get(mode)
            if not descriptor or descriptor.get('schema_version')!=2: continue
            candidates=[o for o in observations if o.get(mode) and o['status']=='evaluated'
                        and o['model']['basis']==record['model']['basis']]
            position=np.asarray(encode(record['values'],cfg['dimensions']))
            candidates.sort(key=lambda o:float(np.sum((position-np.asarray(encode(o['values'],cfg['dimensions'])))**2)))
            for reference in candidates:
                comparison=compare_fields(descriptor,reference[mode])
                if not comparison.get('compatible'): continue
                comparison.update(reference_design_id=reference.get('id'),reference_source=reference.get('source'),
                                  reference_source_design_id=reference.get('source_design_id',reference.get('id')),
                                  reference_values=reference['values'],current_values=record['values'],
                                  comparison_rule='Nearest compatible evaluated geometry in normalized design coordinates',
                                  mode_note='Selected spectral peaks may belong to different resonance branches; overlap measures similarity, not certified mode identity.')
                record['field_tracking'][mode]=comparison
                break
        write_json(folder/'field_tracking.json',record['field_tracking'])

    def evaluate(values,verification=False):
        nonlocal spent
        guard()
        model=model_for(base,cfg,values)
        if verification: model['basis']=math.ceil(base['basis']*1.5)
        identifier=len(observations)+1
        folder=directory/f'target_design_{identifier}'
        folder.mkdir()
        model['points']=copy.deepcopy(base['points'])
        wavelengths=[p[1] for p in base['points']]
        if verification:
            wavelengths=sorted(set(wavelengths+[(a+b)/2 for a,b in zip(wavelengths,wavelengths[1:])]))
        combined={}
        emit(dict(kind='search_progress',design=identifier,total=cfg['ml_trials'],points=spent,text='Higher-resolution verification' if verification else 'Targeted S4 spectrum and field sampling'))
        record=dict(id=identifier,values=values,model=model,source='new',phase='verification' if verification else 'exploration',status='failed')
        try:
            for _ in range(cfg['refinement_rounds']+1):
                if not wavelengths: break
                if spent+len(wavelengths)>cfg['point_budget']: raise TimeoutError('Spectral-point budget reached')
                evaluation=dict(model,points=[[i,w,base['points'][0][2]] for i,w in enumerate(wavelengths)])
                rows,_=executor(evaluation,dict(perf,timeout_seconds=max(1,int(guard()))),lambda event:None,cancelled)
                spent+=len(rows)
                if any(not -1e-8<=r[5]<=1 or not all(math.isfinite(float(v)) for v in r) for r in rows):
                    raise ValueError('Nonphysical spectral observation')
                combined.update({r[1]:r for r in rows})
                write_json(folder/'partial_spectrum.json',list(combined.values()))
                wavelengths=refinement_points(list(combined.values()),cfg['prominence'])
            rows=sorted(combined.values(),key=lambda r:r[1])
            record.update(status='evaluated',rows=rows,targets=target_metrics(rows,cfg))
            write_csv(folder/'spectrum.csv',[dict(zip(['wavelength_nm','angle_deg','R','T','A'],r[1:])) for r in rows])
            if cfg['use_fields']:
                try:
                    record['fields']=field_executor(model,dict(perf,timeout_seconds=max(1,int(guard()))),
                        dict(wavelength_nm=cfg['target_nm'],grid=cfg['field_grid'],maps=False,sampling_mode='fixed_target'),folder/'fields',cancelled)
                    peak=record['targets']['selected_peak']
                    if cfg.get('track_resonance',True) and peak:
                        if abs(peak['wavelength_nm']-cfg['target_nm'])<1e-8:
                            # Same solve serves both views; retain explicit wavelength semantics.
                            record['resonance_fields']=dict(record['fields'],sampling_mode='selected_resonance')
                            if (folder/'fields/electric_fields.csv').exists():
                                alias=folder/'resonance_fields'
                                alias.mkdir()
                                (alias/'electric_fields.csv').write_bytes((folder/'fields/electric_fields.csv').read_bytes())
                                snapshot=read_json(folder/'fields/field_model.json')
                                snapshot['settings']=dict(snapshot['settings'],sampling_mode='selected_resonance',reused_fixed_target_solve=True)
                                write_json(alias/'field_model.json',snapshot)
                                write_json(alias/'field_features.json',record['resonance_fields'])
                        else:
                            record['resonance_fields']=field_executor(model,dict(perf,timeout_seconds=max(1,int(guard()))),
                                dict(wavelength_nm=peak['wavelength_nm'],grid=cfg['field_grid'],maps=False,
                                     sampling_mode='selected_resonance'),folder/'resonance_fields',cancelled)
                    track(record,folder)
                except (Cancelled,TimeoutError): raise
                except Exception as exc:
                    record['field_error']=str(exc)
            return record
        except (Cancelled,TimeoutError):
            record['reason']='Interrupted evaluation; use saved partial data'
            raise
        except Exception as exc:
            record['reason']=str(exc)
            return record
        finally:
            observations.append(record)
            checkpoint()

    try:
        checkpoint()
        for iteration in range(cfg['ml_trials']):
            guard()
            pool=candidate_pool(base,cfg,observations,screened)
            if not pool: break
            chosen=None
            field_warning=None
            if cfg['use_fields']:
                try:
                    chosen=field_augmented_candidate(pool,observations,saved_fields,cfg,explore=iteration%5==4)
                except Exception as exc:
                    field_warning=str(exc)
            values,prediction=chosen or pick_candidate(pool,observations,cfg)
            if field_warning: prediction['field_model_warning']='Used geometry-only acquisition: '+field_warning
            record=evaluate(values)
            record['prediction']=prediction
            checkpoint()
            if len(observations)>=3 and all(o['status']=='failed' for o in observations[-3:]):
                raise RuntimeError('Three consecutive S4 designs failed')
        successful=[o for o in observations if o['status']=='evaluated']
        # Verify the highest-Q feasible leaders, including leaders from older runs.
        leaders=sorted(successful,key=lambda o:(o['targets']['feasible_q'] or 0,o['targets']['absorption']),reverse=True)
        done=set()
        for old in leaders:
            if len(done)>=cfg['finalists']: break
            key=value_key(old['values'])
            if key in done: continue
            done.add(key)
            new=evaluate(old['values'],True)
            if new['status']!='evaluated': continue
            a,b=old['targets'],new['targets']
            q0,q1=a['feasible_q'],b['feasible_q']
            agree=bool(q0 and q1 and abs(q1-q0)/q0<=.05 and abs(a['q_absorption']-b['q_absorption'])<=.001
                       and abs(a['q_wavelength']-b['q_wavelength'])<=min(cfg['tolerance_nm'],max(1e-6,2*a['q_wavelength']/q0)))
            new['verification']='two-resolution agreement' if agree else 'needs further convergence review'
            if agree and (recommendation is None or q1>recommendation['targets']['feasible_q']): recommendation=new
            checkpoint()
        if recommendation and cfg['use_fields']:
            best=directory/'recommended_fields'
            field_executor(recommendation['model'],dict(perf,timeout_seconds=max(1,int(guard()))),
                dict(wavelength_nm=recommendation['targets']['q_wavelength'],grid=cfg['map_grid'],maps=True,
                     sampling_mode='selected_resonance'),best,cancelled)
    except (Cancelled,TimeoutError) as exc:
        status='partial'
        errors.append(str(exc))
    except Exception as exc:
        status='error'
        errors.append(str(exc))
    if any(o['status']=='failed' for o in observations) and status=='complete': status='partial'
    checkpoint()
    authoritative={}
    for o in observations:
        if o['status']=='evaluated': authoritative[value_key(o['values'])]=o
    table=[]
    with (directory/'design_models.jsonl').open('w',encoding='utf-8') as stream:
        for i,o in enumerate(observations,1):
            o.setdefault('id',i)
            stream.write(json.dumps(dict(design_id=o['id'],model=o['model']))+'\n')
        for o in authoritative.values():
            t=o['targets']
            table.append(dict(design_id=o['id'],source=o['source'],peak_nm=t['q_wavelength'],peak_absorption=t['q_absorption'],
                Q_estimate=math.exp(t['log_q']) if t['log_q'] is not None else None,eligible=bool(t['feasible_q']),
                absorption_at_target=t['absorption_at_target'],verification=o.get('verification','not verified'),
                field_log_concentration=(o.get('fields') or {}).get('log_concentration'),field_error=o.get('field_error',''),**conditions(o['model'])))
    table.sort(key=lambda r:(r['eligible'],r['Q_estimate'] or 0),reverse=True)
    write_csv(directory/'target_results.csv',table)
    field_table,comparisons=[],[]
    for o in observations:
        for mode in ('fields','resonance_fields'):
            descriptor=o.get(mode)
            if not descriptor or descriptor.get('schema_version')!=2: continue
            try:
                vector=feature_vector(descriptor)
            except (KeyError,ValueError,TypeError,OverflowError) as exc:
                errors.append('Skipped invalid field features for design '+str(o['id'])+': '+str(exc))
                continue
            field_table.append(dict(design_id=o['id'],source=o['source'],phase=o['phase'],mode=mode,
                wavelength_nm=descriptor['wavelength_nm'],grid=descriptor['grid'],
                **vector,**conditions(o['model'])))
            comparison=o.get('field_tracking',{}).get(mode)
            if comparison:
                comparisons.append(dict(design_id=o['id'],mode=mode,
                    reference_design_id=comparison['reference_design_id'],reference_source=comparison['reference_source'],
                    field_overlap=comparison.get('field_overlap'),details=json.dumps(comparison)))
    write_csv(directory/'field_training.csv',field_table)
    write_csv(directory/'field_comparisons.csv',comparisons)
    if recommendation:
        write_json(directory/'recommended_design.json',recommendation)
    summary=dict(status=status,reason='; '.join(errors),target_nm=cfg['target_nm'],tolerance_nm=cfg['tolerance_nm'],minimum_q=cfg['minimum_q'],
        reused_training_records=reused,reused_field_records=len(saved_fields),incompatible_or_duplicate_records=skipped,new_evaluations=len(observations)-reused,
        spectral_points=spent,recommended_design_id=recommendation['id'] if recommendation else None,
        field_feature_records=len(field_table),field_comparisons=len(comparisons),
        field_informed_proposals=sum(bool(o.get('prediction',{}).get('field_surrogates')) for o in observations),
        maximum_verified_Q=recommendation['targets']['feasible_q'] if recommendation else None,
        scope='Highest-Q design found that passes >99% peak absorption, wavelength tolerance, minimum Q and two-resolution agreement. Finite search; no continuous global-maximum guarantee. Q is a baseline-relative spectral estimate.')
    write_json(directory/'search_summary.json',summary)
    return dict(kind='search_complete',directory=str(directory),summary=summary)
