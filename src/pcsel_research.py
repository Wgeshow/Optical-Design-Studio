"""Editable PCSEL optical studies generalized from the recovered research.

Vertical TE, four-wave coupling, finite outgoing cavities and Fraunhofer beams
retain their distinct approximations. Geometry is in the saved input, never
read from an experiment directory. See arXiv:1107.1772 for the CWT formulation.
"""
from __future__ import annotations

import copy
import json
import math
import itertools
from pathlib import Path

import numpy as np
from scipy.linalg import eigh_tridiagonal, solve_banded
from scipy.special import j1

from input_diagnostics import InputValidationError, diagnostic

LIMITATIONS=[
    'Vertical and coupled-wave models use nondispersive positive real indices and a square periodic lattice.',
    'Four-basic-wave TE coupling uses a local longitudinal closure; it is not a full-vector Maxwell solver.',
    'Finite modes use a rectangular aperture with zero incoming basic waves. A single resolution does not establish convergence.',
    'Far fields use the paraxial Fraunhofer approximation with a unit-power basis. Absolute display power requires a supplied calibration; passive modes do not predict laser output.',
    'Reduced aperture electrothermal/rate calculations use explicit source-bound load anchors, not a new three-dimensional drift-diffusion solve.',
]
CAPABILITIES=dict(label='PCSEL optical and aperture studies',dimensions=[1,2],optional_runtime=False,
    models=['vertical','cwt','finite','beam','aperture','gme','rcwa_poles'],limitations=LIMITATIONS)
FIELD_SCHEMA=[
    dict(path='model',label='Physical model',type='choice',options=CAPABILITIES['models'],default='vertical',section='study'),
    dict(path='lattice_nm',label='Square lattice period',type='number',unit='nm',required=True,section='geometry'),
    dict(path='layers',label='Layers, top to bottom',type='array',required=True,section='geometry'),
    dict(path='shapes',label='Patterned inclusions',type='array',default=[],section='geometry'),
    dict(path='inclusion_index',label='Inclusion refractive index',type='number',default=1.,section='materials'),
    dict(path='top_index',label='Top half-space index',type='number',default=1.,section='materials'),
    dict(path='bottom_index',label='Bottom half-space index',type='number',required=True,section='materials'),
    dict(path='grid_nm',label='Vertical grid spacing',type='number',unit='nm',default=2.,section='accuracy'),
    dict(path='pad_nm',label='Vertical boundary padding',type='number',unit='nm',default=4000.,section='accuracy'),
    dict(path='harmonics',label='Coupling harmonic order',type='integer',default=8,section='accuracy'),
    dict(path='green_model',label='Radiation Green function',type='choice',options=['local','layer_resolved'],default='layer_resolved',section='solver'),
    dict(path='aperture_um',label='Aperture width and height',type='array',unit='um',default=[200.,200.],section='geometry'),
    dict(path='collocation_order',label='Finite-cavity collocation order',type='integer',default=12,section='accuracy'),
    dict(path='beam_grid',label='Near-field samples per axis',type='integer',default=128,section='accuracy'),
    dict(path='beam_padding',label='FFT zero-padding factor',type='integer',default=4,section='accuracy'),
    dict(path='beam_mode',label='Finite mode number (-1 selects lowest accepted loss)',type='integer',default=-1,section='outputs'),
    dict(path='beam_normalization',label='Beam normalization',type='choice',options=['unit_power','peak','calibrated_power'],default='unit_power',section='outputs'),
    dict(path='beam_power_W',label='Calibrated emitted power',type='number',unit='W',section='outputs'),
    dict(path='beam_power_source',label='Emitted-power calibration source',type='string',default='',section='outputs'),
    dict(path='beam_saved_run',label='Compatible saved finite-mode folder (optional)',type='string',default='',section='outputs'),
    dict(path='gmax',label='GME reciprocal cutoff',type='number',default=3.1,section='accuracy'),
    dict(path='guided_modes',label='GME guided mode indices',type='array',default=[0],section='solver'),
    dict(path='num_modes',label='Number of GME modes',type='integer',default=4,section='solver'),
    dict(path='kpoints',label='GME wavevectors in 2 pi / a',type='array',default=[[0.,0.]],section='solver'),
    dict(path='basis',label='RCWA Fourier basis',type='integer',default=49,section='accuracy'),
    dict(path='pole_seeds',label='Complex resonance seeds [real, imaginary]',type='array',default=[],section='solver'),
    dict(path='pole_bounds',label='Pole search bounds [[real min,max],[imaginary min,max]]',type='array',default=[[.001,2.],[-.5,-1e-12]],section='solver'),
    dict(path='pole_excitation',label='Incident s and p amplitudes [[real,imag],[real,imag]]',type='array',default=[[1.,0.],[0.,.37]],section='solver'),
    dict(path='probe',label='RCWA probe [x/a,y/a,z_nm]',type='array',default=[.113,.179,0.],section='outputs'),
    dict(path='pole_field_grid',label='Pole-residue field samples per cell axis',type='integer',default=24,section='outputs'),
    dict(path='pole_field_z_nm',label='Pole field depths (empty uses probe depth)',type='array',default=[],unit='nm',section='outputs'),
    dict(path='pole_detuning',label='Maximum imaginary residue detuning',type='number',default=1e-8,section='accuracy'),
    dict(path='aperture',label='Reduced electrical, carrier and thermal parameters',type='object',default={},section='physics'),
    dict(path='runtime',label='Optional GME Python runtime',type='object',default={},section='runtime'),
    dict(path='parameter_sweep',label='Geometry and accuracy sweep',type='object',section='sweep'),
]


def paper_example(kind='hole',shape='CC',fill=.16):
    """An explicit editable starting deck; no solver selects it implicitly."""
    if kind not in ('hole','pillar') or shape not in ('CC','RIT'):
        raise ValueError('Select hole/pillar and CC/RIT for this recovered example.')
    if kind=='hole':
        sequence=[('contact',100,3.524),('p-cladding',1500,3.307),('GaAs',20,3.524),
            ('PC',118,3.524),('GaAs',22,3.524),('cladding',40,3.279),('spacer',40,3.524)]
    else:sequence=[('PC1',100,3.524),('PC2',400,3.307),('spacer',40,3.524)]
    sequence += [('QW',8,3.6),('barrier',20,3.524),('QW',8,3.6),('barrier',20,3.524),
        ('QW',8,3.6),('spacer',30,3.524),('n-cladding',1500,3.307)]
    layers=[dict(id='layer-'+str(i),name=name,thickness_nm=d,index=n,qw=name=='QW',patterned=name.startswith('PC')) for i,(name,d,n) in enumerate(sequence)]
    if shape=='CC':
        shapes=[dict(id='circle-'+str(i),shape='circle',center=[center,center],radius=float(np.sqrt(part*fill/np.pi)))
            for i,(center,part) in enumerate([(-1/6,.75),(1/6,.25)])]
    else:
        b=np.sqrt(2*fill);shapes=[dict(id='triangle',shape='polygon',vertices=[[-b/3,-b/3],[2*b/3,-b/3],[-b/3,2*b/3]])]
    return dict(model='vertical',lattice_nm=295.,layers=layers,shapes=shapes,top_index=1.,bottom_index=3.307,
        inclusion_index=1.,grid_nm=1.,pad_nm=4000.,harmonics=8,green_model='layer_resolved',
        aperture_um=[200.,200.],collocation_order=12)


def _error(field,message,object_id=''):
    raise InputValidationError([diagnostic(message,workspace='research_studies',section='inputs',
        field=field,object_id=object_id,code='pcsel.input')])


def _number(value,field,minimum=None,integer=False,object_id=''):
    try:v=float(value)
    except (TypeError,ValueError,OverflowError):_error(field,'Enter a finite number.',object_id)
    if isinstance(value,bool) or not math.isfinite(v) or minimum is not None and v<minimum or integer and v!=int(v):
        _error(field,'Enter a finite '+('integer' if integer else 'number')+(f' of at least {minimum:g}.' if minimum is not None else '.'),object_id)
    return int(v) if integer else v


def _shape(shape,index):
    if not isinstance(shape,dict):_error('shapes','Each inclusion must be an object.')
    result=copy.deepcopy(shape);result.setdefault('id','shape-'+str(index))
    if not isinstance(result['id'],str) or not result['id']:_error('shapes','Every inclusion needs a nonempty stable ID.')
    kind=result.get('shape')
    if kind=='circle':
        center=result.get('center',[0.,0.])
        if not isinstance(center,list) or len(center)!=2:_error('shapes','A circle center needs x and y.',result['id'])
        result['center']=[_number(v,'shapes.'+result['id']+'.center.'+str(i),object_id=result['id']) for i,v in enumerate(center)]
        result['radius']=_number(result.get('radius'),'shapes.'+result['id']+'.radius',1e-12,object_id=result['id'])
        c=np.array(result['center']);r=result['radius'];bounds=np.r_[c-r,c+r]
    elif kind=='polygon':
        try:points=np.asarray(result.get('vertices',[]),dtype=float)
        except (ValueError,TypeError):_error('shapes','Polygon vertices must be finite x/y pairs.',result['id'])
        if points.ndim!=2 or points.shape[1]!=2 or len(points)<3 or not np.isfinite(points).all():
            _error('shapes','A polygon needs at least three finite x/y vertices.',result['id'])
        edge=np.roll(points,-1,axis=0)-points
        turn=np.cross(edge,np.roll(edge,-1,axis=0))
        if not (np.all(turn>=-1e-12) or np.all(turn<=1e-12)):
            _error('shapes','This CWT adapter accepts convex, non-self-intersecting polygons.',result['id'])
        area=.5*np.sum(points[:,0]*np.roll(points[:,1],-1)-points[:,1]*np.roll(points[:,0],-1))
        if abs(area)<1e-12:_error('shapes','Polygon area must be positive.',result['id'])
        if area<0:points=points[::-1]
        # A star polygon can have equal-sign local turns while crossing itself.
        # Every vertex must lie in the interior half-plane of every edge.
        for a,b in zip(points,np.roll(points,-1,axis=0)):
            delta=b-a;offset=points-a
            if np.linalg.norm(delta)<1e-12 or np.any(delta[0]*offset[:,1]-delta[1]*offset[:,0]<-1e-12):
                _error('shapes','Use a convex polygon with distinct, non-crossing vertices.',result['id'])
        result['vertices']=points.tolist();bounds=np.r_[points.min(axis=0),points.max(axis=0)]
    else:_error('shapes','Choose circle or convex polygon.',result['id'])
    if np.any(bounds[:2]<-.5-1e-12) or np.any(bounds[2:]>.5+1e-12):
        _error('shapes','Inclusions must fit inside the editable cell [-0.5,0.5] in both directions.',result['id'])
    result['_bounds']=bounds.tolist()
    return result


def shape_fourier(shape,q):
    """Area-normalized analytic Fourier transform, exp(-2 pi i q.r)."""
    k=2*np.pi*np.asarray(q,dtype=float);norm=np.linalg.norm(k)
    if shape['shape']=='circle':
        r=shape['radius'];area=np.pi*r*r
        return area*(1. if norm==0 else 2*j1(norm*r)/(norm*r))*np.exp(-1j*k@shape['center'])
    points=np.asarray(shape['vertices']);edges=np.roll(points,-1,axis=0)-points
    if norm==0:return .5*np.sum(points[:,0]*np.roll(points[:,1],-1)-points[:,1]*np.roll(points[:,0],-1))
    middle=points+edges/2
    return np.sum(1j*(k[0]*edges[:,1]-k[1]*edges[:,0])/norm**2*
                  np.exp(-1j*(middle@k))*np.sinc((edges@k)/(2*np.pi)))


def prepare(project,settings):
    if not isinstance(settings,dict):_error('model','PCSEL settings must be an object.')
    allowed={row['path'] for row in FIELD_SCHEMA}
    if set(settings)-allowed:_error('model','Unsupported PCSEL settings: '+', '.join(sorted(set(settings)-allowed)))
    if 'parameter_sweep' in settings:
        return _prepare_sweep(project,settings)
    cfg={row['path']:copy.deepcopy(row['default']) for row in FIELD_SCHEMA if 'default' in row}
    cfg.update(copy.deepcopy(settings))
    if cfg['model'] not in CAPABILITIES['models']:_error('model','Select a supported PCSEL model.')
    for field in ('lattice_nm','inclusion_index','top_index','bottom_index','grid_nm','pad_nm','gmax'):
        cfg[field]=_number(cfg.get(field),field,1e-12)
    for field,minimum in [('harmonics',1),('collocation_order',4),('beam_grid',16),('beam_padding',1),('num_modes',1),('basis',3)]:
        cfg[field]=_number(cfg[field],field,minimum,True)
    if cfg['collocation_order']>60:_error('collocation_order','Use at most 60 until a memory budget is explicitly provided.')
    if cfg['beam_grid']*cfg['beam_padding']>4096:_error('beam_grid','The padded field may have at most 4096 samples per axis.')
    cfg['beam_mode']=_number(cfg['beam_mode'],'beam_mode',-1,True)
    if cfg['beam_normalization'] not in ('unit_power','peak','calibrated_power'):_error('beam_normalization','Select a beam normalization.')
    if cfg['beam_normalization']=='calibrated_power':
        cfg['beam_power_W']=_number(cfg.get('beam_power_W'),'beam_power_W',1e-30)
        if not isinstance(cfg['beam_power_source'],str) or not cfg['beam_power_source'].strip():_error('beam_power_source','Identify the emitted-power calibration; passive modes do not supply watts.')
    if not isinstance(cfg['beam_saved_run'],str):_error('beam_saved_run','Supply a saved run directory or leave it blank.')
    if cfg['harmonics']>30:_error('harmonics','Use a coupling harmonic order no larger than 30.')
    if cfg['green_model'] not in ('local','layer_resolved'):_error('green_model','Select local or layer-resolved radiation.')
    layers=cfg.get('layers')
    if not isinstance(layers,list) or not layers:_error('layers','Add the editable layer stack, top to bottom.')
    ids=set()
    for i,row in enumerate(layers):
        if not isinstance(row,dict):_error('layers','Each layer must be an object.')
        if set(row)-{'id','name','thickness_nm','index','qw','patterned'}:_error('layers','Unsupported layer properties.')
        row.setdefault('id','layer-'+str(i));row.setdefault('name',row['id'])
        if not isinstance(row['id'],str) or not row['id']:_error('layers','Every layer needs a nonempty stable ID.')
        if row['id'] in ids:_error('layers','Layer IDs must be unique.',row['id'])
        ids.add(row['id'])
        for key in ('thickness_nm','index'):row[key]=_number(row.get(key),'layers.'+row['id']+'.'+key,1e-12,object_id=row['id'])
        for key in ('qw','patterned'):
            row.setdefault(key,False)
            if not isinstance(row[key],bool):_error('layers','QW and patterned flags must be true or false.',row['id'])
        if row['thickness_nm']<cfg['grid_nm']:_error('grid_nm','Resolve every layer with at least one vertical cell; refine the spacing.')
    if (sum(row['thickness_nm'] for row in layers)+2*cfg['pad_nm'])/cfg['grid_nm']>250000:
        _error('grid_nm','This vertical mesh exceeds 250,000 samples; adjust spacing or padding.')
    if not isinstance(cfg['shapes'],list):_error('shapes','Inclusions must be an array.')
    cfg['shapes']=[_shape(row,i) for i,row in enumerate(cfg['shapes'])]
    if len({r['id'] for r in cfg['shapes']})!=len(cfg['shapes']):
        _error('shapes','Inclusion IDs must be unique.')
    for i,a in enumerate(cfg['shapes']):
        for b in cfg['shapes'][i+1:]:
            if a['shape']==b['shape']=='circle':
                overlap=np.linalg.norm(np.array(a['center'])-b['center'])<a['radius']+b['radius']-1e-12
            else:
                aa,bb=np.array(a['_bounds']),np.array(b['_bounds'])
                overlap=np.all(np.minimum(aa[2:],bb[2:])-np.maximum(aa[:2],bb[:2])>1e-12)
            if overlap:_error('shapes','Inclusions must be disjoint. Polygon pairs also require disjoint bounding boxes.',a['id'])
    cfg['fill_fraction']=float(sum(shape_fourier(shape,[0,0]).real for shape in cfg['shapes']))
    if cfg['fill_fraction']>=1:_error('shapes','Inclusion area must be smaller than one unit cell.')
    if cfg['model'] in ('cwt','finite','beam','rcwa_poles','gme') and (not cfg['shapes'] or not any(r['patterned'] for r in layers)):
        _error('shapes','This model needs inclusions and at least one patterned layer.')
    if not isinstance(cfg['aperture_um'],list) or len(cfg['aperture_um'])!=2:_error('aperture_um','Enter aperture width and height.')
    cfg['aperture_um']=[_number(v,'aperture_um',1e-9) for v in cfg['aperture_um']]
    if cfg['model']=='aperture':
        from pcsel_aperture import prepare_parameters
        cfg['aperture']=prepare_parameters(cfg['aperture'],cfg['aperture_um'],cfg)
    if cfg['model']=='gme':
        from research_physics_runtime import validate_runtime
        cfg['runtime']=validate_runtime(cfg['runtime'])
        if not isinstance(cfg['guided_modes'],list) or not cfg['guided_modes']:_error('guided_modes','Select at least one guided-mode index.')
        cfg['guided_modes']=[_number(v,'guided_modes',0,True) for v in cfg['guided_modes']]
        if not isinstance(cfg['kpoints'],list) or not cfg['kpoints']:_error('kpoints','Supply at least one x/y wavevector.')
        for point in cfg['kpoints']:
            if not isinstance(point,list) or len(point)!=2:_error('kpoints','Each GME wavevector needs two components.')
            point[:]=[_number(v,'kpoints') for v in point]
    if cfg['model']=='rcwa_poles':
        if not isinstance(cfg['pole_seeds'],list) or not cfg['pole_seeds']:_error('pole_seeds','Enter initial complex resonance frequencies [real, negative imaginary].')
        for seed in cfg['pole_seeds']:
            if len(seed)!=2 or _number(seed[0],'pole_seeds',1e-12)<=0 or _number(seed[1],'pole_seeds')>=0:_error('pole_seeds','Pole seeds require positive real and negative imaginary frequencies.')
        if not isinstance(cfg['probe'],list) or len(cfg['probe'])!=3:_error('probe','Enter x/a, y/a and physical z in nm.')
        cfg['probe']=[_number(v,'probe') for v in cfg['probe']]
        if not 0<=cfg['probe'][2]<=sum(row['thickness_nm'] for row in layers):_error('probe','Place the RCWA probe within the finite stack.')
        for key in ('pole_bounds','pole_excitation'):
            value=cfg[key]
            if not isinstance(value,list) or len(value)!=2 or any(not isinstance(v,list) or len(v)!=2 for v in value):
                _error(key,'Supply two pairs of finite numbers.')
            cfg[key]=[[_number(v,key) for v in pair] for pair in value]
        bounds=cfg['pole_bounds']
        if bounds[0][0]<=0 or bounds[1][1]>=0 or any(b<=a for a,b in bounds):
            _error('pole_bounds','Use increasing positive real bounds and increasing negative imaginary bounds.')
        if not any(v for pair in cfg['pole_excitation'] for v in pair):_error('pole_excitation','Supply at least one nonzero incident polarization amplitude.')
        if any(not all(bounds[j][0]<seed[j]<bounds[j][1] for j in (0,1)) for seed in cfg['pole_seeds']):
            _error('pole_seeds','Place every initial seed strictly inside the complex search bounds.')
        cfg['pole_field_grid']=_number(cfg['pole_field_grid'],'pole_field_grid',8,True)
        if cfg['pole_field_grid']>256:_error('pole_field_grid','Use at most 256 field samples per axis.')
        cfg['pole_detuning']=_number(cfg['pole_detuning'],'pole_detuning',1e-14)
        if not isinstance(cfg['pole_field_z_nm'],list) or len(cfg['pole_field_z_nm'])>128:_error('pole_field_z_nm','Supply up to 128 field depths.')
        cfg['pole_field_z_nm']=[_number(v,'pole_field_z_nm',0) for v in cfg['pole_field_z_nm']] or [cfg['probe'][2]]
        if max(cfg['pole_field_z_nm'])>sum(row['thickness_nm'] for row in layers):_error('pole_field_z_nm','Field depths must lie within the finite stack.')
    return cfg


def _prepare_sweep(project,settings):
    """Validate every editable case before launching the first calculation."""
    sweep=settings['parameter_sweep']
    if not isinstance(sweep,dict) or set(sweep)-{'parameters'}:
        _error('parameter_sweep','Supply an object containing a parameters array.')
    axes=sweep.get('parameters')
    if not isinstance(axes,list) or not axes:
        _error('parameter_sweep','Add at least one sweep parameter with explicit values.')
    base={k:copy.deepcopy(v) for k,v in settings.items() if k!='parameter_sweep'}
    baseline=prepare(project,base)
    scalar={'lattice_nm','inclusion_index','top_index','bottom_index','grid_nm','pad_nm','harmonics',
            'collocation_order','beam_grid','beam_padding','gmax','num_modes','basis'}
    setters=[];labels=[];values=[]
    for axis in axes:
        if not isinstance(axis,dict) or set(axis)-{'path','object_id','field','values'}:
            _error('parameter_sweep','Each parameter needs path, values and, for an object, object_id and field.')
        path=axis.get('path');ident=axis.get('object_id');field=axis.get('field');numbers=axis.get('values')
        if not isinstance(numbers,list) or not numbers or len(numbers)>128:
            _error('parameter_sweep','Each parameter needs 1 to 128 explicit values.')
        numbers=[_number(v,'parameter_sweep') for v in numbers]
        if path in ('fill_fraction','center_scale') and not ident and not field:
            if not baseline['shapes']:_error('parameter_sweep','Pattern sweeps require at least one inclusion.')
            if path=='fill_fraction' and any(v<=0 or v>=1 for v in numbers):
                _error('parameter_sweep','Requested fill fractions must be strictly between zero and one.')
            setter=(path,None,None);label=path
        elif path in scalar and not ident and not field:
            setter=(path,None,None);label=path
        elif path=='aperture_um' and field in ('width','height') and not ident:
            setter=(path,None,0 if field=='width' else 1);label=path+'.'+field
        elif path in ('layers','shapes') and isinstance(ident,str):
            found=[i for i,row in enumerate(base.get(path,[])) if row.get('id')==ident]
            if len(found)!=1:_error('parameter_sweep','Select one existing object by its stable ID.',ident)
            row=base[path][found[0]]
            permitted={'thickness_nm','index'} if path=='layers' else ({'radius','center_x','center_y'} if row.get('shape')=='circle' else set())
            if field not in permitted:_error('parameter_sweep','This object supports '+', '.join(sorted(permitted))+' sweep fields.',ident)
            setter=(path,found[0],field);label=path+'.'+ident+'.'+field
        else:_error('parameter_sweep','Select a supported scalar input, aperture dimension, layer index/thickness, or circle radius.')
        if label in labels:_error('parameter_sweep','Each input can appear only once in a sweep.')
        setters.append(setter);labels.append(label);values.append(numbers)
    if 'fill_fraction' in labels and any(path=='shapes' and key=='radius' for path,_,key in setters):
        _error('parameter_sweep','Choose total fill fraction or individual radii in one sweep, so each requested value stays exact.')
    if 'center_scale' in labels and any(path=='shapes' and key in ('center_x','center_y') for path,_,key in setters):
        _error('parameter_sweep','Choose collective center scaling or individual center coordinates in one sweep.')
    count=math.prod(map(len,values))
    if count>128:_error('parameter_sweep','The Cartesian product is limited to 128 cases; split this sweep.')
    cases=[]
    for combination in itertools.product(*values):
        raw=copy.deepcopy(base)
        for (path,index,key),value in zip(setters,combination):
            if path in ('fill_fraction','center_scale'):
                factor=math.sqrt(value/baseline['fill_fraction']) if path=='fill_fraction' else value
                for shape in raw['shapes']:
                    if shape['shape']=='circle':
                        if path=='fill_fraction':shape['radius']*=factor
                        else:shape['center']=(np.array(shape.get('center',[0.,0.]))*factor).tolist()
                    else:
                        vertices=np.asarray(shape['vertices']);following=np.roll(vertices,-1,axis=0)
                        cross=vertices[:,0]*following[:,1]-vertices[:,1]*following[:,0]
                        center=np.sum((vertices+following)*cross[:,None],axis=0)/(3*cross.sum())
                        shape['vertices']=(center+(vertices-center)*factor if path=='fill_fraction' else vertices+(factor-1)*center).tolist()
            elif index is not None:
                if key in ('center_x','center_y'):raw[path][index].setdefault('center',[0.,0.])[0 if key=='center_x' else 1]=value
                else:raw[path][index][key]=value
            elif key is not None:raw.setdefault(path,[200.,200.])[key]=value
            else:raw[path]=value
        try:case=prepare(project,raw)
        except ValueError as exc:
            _error('parameter_sweep','A requested case is invalid ('+', '.join(f'{k}={v:g}' for k,v in zip(labels,combination))+'): '+str(exc))
        cases.append(dict(parameters=dict(zip(labels,combination)),prepared=case))
    cfg=prepare(project,base)
    cfg['parameter_sweep']=dict(parameters=copy.deepcopy(axes),cases=cases)
    return cfg


def vertical(cfg):
    h=cfg['grid_nm'];length=sum(r['thickness_nm'] for r in cfg['layers'])
    z=np.arange(-cfg['pad_nm']+h/2,length+cfg['pad_nm'],h)
    n=np.where(z<length,cfg['top_index'],cfg['bottom_index']).astype(float)
    qw=np.zeros(len(z),bool);pc=qw.copy();contrast=np.zeros_like(z);edge=0.
    f=cfg['fill_fraction']
    for row in cfg['layers']:
        mask=(z>=edge)&(z<edge+row['thickness_nm']);edge+=row['thickness_nm']
        epsilon=row['index']**2
        n[mask]=np.sqrt((1-f)*epsilon+f*cfg['inclusion_index']**2) if row['patterned'] else row['index']
        if row['qw']:qw|=mask
        if row['patterned']:pc|=mask;contrast[mask]=cfg['inclusion_index']**2-epsilon
    beta=2*np.pi/cfg['lattice_nm']
    diag=(2/h**2+beta**2)/n**2;off=-1/h**2/(n[:-1]*n[1:])
    eig,vec=eigh_tridiagonal(diag,off,select='i',select_range=(0,0))
    field=vec[:,0]/n;field/=np.sqrt(np.sum(field**2)*h)
    k=float(np.sqrt(eig[0]));freq=cfg['lattice_nm']*k/(2*np.pi)
    neff=beta/k
    row=dict(frequency=freq,wavelength_nm=cfg['lattice_nm']/freq,effective_index=neff,
             Gamma_QW=float(np.sum(field[qw]**2)*h),Gamma_PC=float(np.sum(field[pc]**2)*h),
             guided=bool(neff>max(cfg['top_index'],cfg['bottom_index'])),
             boundary_intensity_fraction=float((field[0]**2+field[-1]**2)*h))
    return row,dict(z_nm=z,index=n,field=field,intensity_per_nm=field**2,patterned=pc,contrast=contrast)


def coupling(cfg,profile,row,cancelled=lambda:False):
    a=cfg['lattice_nm'];h=cfg['grid_nm'];beta=2*np.pi/a;k=2*np.pi*row['frequency']/a
    n=profile['index'];theta=profile['field'];contrast=profile['contrast'];pc=profile['patterned']
    vectors=np.array([[1,0],[-1,0],[0,1],[0,-1]]);pol=np.array([[0,1],[0,1],[1,0],[1,0]])
    ft={}
    def coefficient(q):
        key=tuple(q)
        if key not in ft:ft[key]=sum(shape_fourier(shape,q) for shape in cfg['shapes'])
        return ft[key]
    I1=np.sum(contrast*theta**2)*h;Ip=np.sum(contrast**2*theta**2/n**2)*h
    cache={};flux={}
    def green(q2):
        if q2 in cache:return cache[q2]
        if cfg['green_model']=='layer_resolved':
            v=q2*beta**2-k*k*n*n
            def outgoing(value):
                t=1+h*h*value/2
                if value<0:
                    if abs(t)>1:_error('grid_nm','Resolve propagating radiation on the vertical grid.')
                    return np.exp(-1j*np.arccos(t))
                return np.exp(-np.arccosh(t))
            left,right=outgoing(v[0]),outgoing(v[-1])
            diagonal=(2/h**2+v).astype(complex);diagonal[0]-=left/h**2;diagonal[-1]-=right/h**2
            band=np.zeros((3,len(v)),complex);band[0,1:]=-1/h**2;band[2,:-1]=-1/h**2;band[1]=diagonal
            source=contrast*theta;u=solve_banded((1,1),band,source);value=source@u*h
            if q2==0:
                up=-left.imag/h*abs(u[0])**2;down=-right.imag/h*abs(u[-1])**2
                flux.update(up_fraction=float(up/(up+down)) if up+down>0 else None,
                    green_flux_relative_error=float(abs(up+down+value.imag)/max(up+down,1e-30)))
        else:
            ns=n[pc];w=contrast[pc]*theta[pc]*h
            if len(w)>6000:_error('grid_nm','Local Green matrices exceed the supported memory budget; use layer-resolved Green.')
            if q2==0:
                optical=np.cumsum(ns)*h
                G=-1j*np.exp(-1j*k*abs(optical[:,None]-optical[None,:]))/(2*k*np.sqrt(ns[:,None]*ns[None,:]))
            else:
                argument=q2*beta**2-k*k*ns*ns
                if np.any(argument<=0):_error('green_model','The local high-order evanescent approximation is invalid; use layer-resolved Green.')
                kap=np.sqrt(argument);optical=np.cumsum(kap)*h
                G=np.exp(-abs(optical[:,None]-optical[None,:]))/(2*np.sqrt(kap[:,None]*kap[None,:]))
            value=w@G@w
        cache[q2]=value
        return value
    Ir=green(0);C=np.zeros((4,4),complex);pref=-k*k/(2*beta)
    for i in range(4):
        for j in range(4):
            if i!=j:C[i,j]+=pref*coefficient(vectors[i]-vectors[j])*I1*np.dot(pol[i],pol[j])
            C[i,j]+=pref*k*k*coefficient(vectors[i])*coefficient(-vectors[j])*Ir*np.dot(pol[i],pol[j])
    for m in range(-cfg['harmonics'],cfg['harmonics']+1):
        if cancelled():raise InterruptedError('PCSEL calculation cancelled')
        for nn in range(-cfg['harmonics'],cfg['harmonics']+1):
            q2=m*m+nn*nn
            if q2<=1:continue
            q=np.array([m,nn]);long=np.outer(q,q)/q2;response=-Ip*long+k*k*green(q2)*(np.eye(2)-long)
            for i in range(4):
                for j in range(4):C[i,j]+=pref*coefficient(vectors[i]-q)*coefficient(q-vectors[j])*(pol[i]@response@pol[j])
    return C,flux


def chebyshev(order):
    t=np.pi*np.arange(order+1)/order;x=np.cos(t);c=np.r_[2,np.ones(order-1),2]*(-1.)**np.arange(order+1)
    d=x[:,None]-x[None,:];D=(c[:,None]/c[None,:])/(d+np.eye(order+1));D-=np.diag(D.sum(axis=1));D=-2*D
    w=np.zeros(order+1);ii=np.arange(1,order);v=np.ones(order-1)
    if order%2==0:
        w[[0,-1]]=1/(order*order-1)
        for k in range(1,order//2):v-=2*np.cos(2*k*t[ii])/(4*k*k-1)
        v-=np.cos(order*t[ii])/(order*order-1)
    else:
        w[[0,-1]]=1/(order*order)
        for k in range(1,(order-1)//2+1):v-=2*np.cos(2*k*t[ii])/(4*k*k-1)
    w[ii]=2*v/order
    return (1-x)/2,D,w/2


def finite_modes(cfg,C,frequency,cancelled=lambda:False):
    from scipy.sparse import csr_matrix,kron,eye,block_diag
    from scipy.sparse.linalg import eigs
    Lx,Ly=np.array(cfg['aperture_um'])*1000;x,D,w=chebyshev(cfg['collocation_order']);P=len(x)
    I=eye(P,format='csr');Dx=kron(I,csr_matrix(D/Lx));Dy=kron(csr_matrix(D/Ly),I)
    op=block_diag([1j*Dx,-1j*Dx,1j*Dy,-1j*Dy],format='csr')+kron(csr_matrix(C),eye(P*P,format='csr'))
    ids=np.arange(P*P).reshape(P,P);mask=np.ones(4*P*P,bool)
    for i,edge in enumerate([ids[:,0],ids[:,-1],ids[0,:],ids[-1,:]]):mask[i*P*P+edge]=False
    op=op[mask,:][:,mask].tocsc();inf=np.linalg.eigvals(C);vals=[];vecs=[]
    for branch in range(4):
        if cancelled():raise InterruptedError('Finite mode calculation cancelled')
        va,ve=eigs(op,k=min(8,op.shape[0]-2),sigma=inf[branch]+.5j/max(Lx,Ly),tol=1e-9,maxiter=5000,ncv=min(64,op.shape[0]),v0=np.ones(op.shape[0],complex))
        for j,value in enumerate(va):
            if not any(abs(value-v)<1e-10 for v in vals):vals.append(value);vecs.append(ve[:,j])
    R=(C-C.conj().T)/(2j);weights=np.outer(w,w).ravel();rows=[];fields=[]
    for index in np.argsort(np.imag(vals)):
        value=vals[index];u=np.zeros(4*P*P,complex);u[mask]=vecs[index];u=u.reshape(4,P*P)
        norm=float(np.sum(abs(u)**2*weights));u/=np.sqrt(norm);v=u.reshape(4,P,P)
        rad=float(2*np.einsum('in,ij,jn,n->',u.conj(),R,u,weights).real)*1e7
        edge=float((np.sum(abs(v[0,:,-1])**2*w)+np.sum(abs(v[1,:,0])**2*w))/Lx+
                   (np.sum(abs(v[2,-1,:])**2*w)+np.sum(abs(v[3,0,:])**2*w))/Ly)*1e7
        total=float(2*value.imag*1e7);residual=np.linalg.norm(op@vecs[index]-value*vecs[index])/max(np.linalg.norm(op@vecs[index]),1e-30)
        freq=float(frequency*(1+value.real/(2*np.pi/cfg['lattice_nm'])))
        rows.append(dict(mode=len(rows),frequency=freq,wavelength_nm=cfg['lattice_nm']/freq,
            total_loss_cm1=total,radiation_loss_cm1=rad,edge_loss_cm1=edge,
            balance_relative=abs(total-rad-edge)/max(abs(total),1e-30),eigen_residual=float(residual)))
        fields.append(v)
    return rows,dict(x=x,fields=np.asarray(fields),aperture_um=np.asarray(cfg['aperture_um']))


def far_field(cfg,finite,mode):
    from scipy.interpolate import BarycentricInterpolator
    grid=cfg['beam_grid'];padding=cfg['beam_padding'];Lx,Ly=cfg['aperture_um']
    t=(np.arange(grid)+.5)/grid;T=BarycentricInterpolator(finite['x'],np.eye(len(finite['x'])),axis=0)(t)
    wave=np.asarray([T@part@T.T for part in finite['fields'][mode['mode']]])
    vectors=np.array([[1,0],[-1,0],[0,1],[0,-1]])
    coeff=np.asarray([sum(shape_fourier(s,-q) for s in cfg['shapes']) for q in vectors])
    ex=coeff[2]*wave[2]+coeff[3]*wave[3];ey=coeff[0]*wave[0]+coeff[1]*wave[1]
    dx,dy=Lx/grid,Ly/grid;norm=float(np.sum(abs(ex)**2+abs(ey)**2)*dx*dy)
    if norm<=1e-30:raise ValueError('This mode has no resolved emitted aperture field.')
    ex/=np.sqrt(norm);ey/=np.sqrt(norm);size=grid*padding;lam=mode['wavelength_nm']/1000
    fx=np.fft.fftshift(np.fft.fft2(ex,s=(size,size)))*dx*dy
    fy=np.fft.fftshift(np.fft.fft2(ey,s=(size,size)))*dx*dy
    sx=np.fft.fftshift(np.fft.fftfreq(size,d=dx))*lam;sy=np.fft.fftshift(np.fft.fftfreq(size,d=dy))*lam
    far=(abs(fx)**2+abs(fy)**2)/lam**2
    return dict(x_um=(t-.5)*Lx,y_um=(t-.5)*Ly,near_per_um2=abs(ex)**2+abs(ey)**2,
        sin_theta_x=sx,sin_theta_y=sy,far_paraxial_per_sr=far,far_x_per_sr=abs(fx)**2/lam**2,far_y_per_sr=abs(fy)**2/lam**2,Ex=ex,Ey=ey,
        parseval_power=np.sum(far)*(sx[1]-sx[0])*(sy[1]-sy[0]))


def _saved_finite(cfg):
    """Reuse fields only when every physical and numerical finite-mode input matches."""
    import csv
    folder=Path(cfg['beam_saved_run']).expanduser().resolve()
    original=json.loads((folder/'pcsel_inputs.json').read_text(encoding='utf-8'))
    keys=('lattice_nm','layers','shapes','fill_fraction','inclusion_index','top_index','bottom_index',
          'grid_nm','pad_nm','harmonics','green_model','aperture_um','collocation_order')
    changed=[key for key in keys if original.get(key)!=cfg.get(key)]
    if changed:_error('beam_saved_run','Saved modes belong to different inputs: '+', '.join(changed)+'. Run the current finite cavity first.')
    with (folder/'finite_modes.csv').open(newline='',encoding='utf-8') as stream:
        modes=[{key:int(value) if key=='mode' else float(value) for key,value in row.items()} for row in csv.DictReader(stream)]
    with np.load(folder/'finite_fields.npz',allow_pickle=False) as archive:
        fields={key:archive[key] for key in ('x','fields','aperture_um')}
    if not modes or fields['fields'].shape[:2]!=(len(modes),4) or not np.isfinite(fields['fields']).all():
        _error('beam_saved_run','Saved finite mode fields are incomplete or invalid.')
    return modes,fields


def _csv(path,rows):
    import csv
    if not rows:return
    with Path(path).open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def execute(prepared,directory,emit=lambda event:None,cancelled=lambda:False):
    cfg=copy.deepcopy(prepared);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if cancelled():raise InterruptedError('PCSEL calculation cancelled')
    (directory/'pcsel_inputs.json').write_text(json.dumps(cfg,indent=2,allow_nan=False),encoding='utf-8')
    if 'parameter_sweep' in cfg:
        return _execute_sweep(cfg,directory,emit,cancelled)
    model=cfg['model'];summary=dict(status='complete',engine='pcsel',model=model,limitations=LIMITATIONS,
        convergence_established=False,reference='https://arxiv.org/abs/1107.1772',artifacts=[])
    if model=='gme':
        from research_physics_runtime import run_worker
        result=run_worker(cfg,directory,emit,cancelled,worker_name='pcsel_physics_worker.py')
        summary.update(result)
    elif model=='rcwa_poles':
        from pcsel_optional import rcwa_poles
        summary.update(rcwa_poles(cfg,directory,emit,cancelled))
    elif model=='aperture':
        from pcsel_aperture import execute_aperture
        summary.update(execute_aperture(cfg,directory,emit,cancelled))
    else:
        row,profile=vertical(cfg);summary['vertical']=row
        np.savetxt(directory/'vertical_profile.csv',np.column_stack([profile['z_nm'],profile['index'],profile['intensity_per_nm']]),delimiter=',',header='z_nm,index,intensity_per_nm',comments='')
        _csv(directory/'vertical_modes.csv',[row]);summary['artifacts']+=['vertical_profile.csv','vertical_modes.csv']
        if not row['guided']:summary['status']='validity_limit'
        if model!='vertical':
            if not row['guided']:raise ValueError('The supplied stack has no confined fundamental mode at this propagation constant.')
            C,flux=coupling(cfg,profile,row,cancelled);summary.update(flux)
            eigen=np.linalg.eigvals(C);modes=[dict(mode=i,frequency=float(row['frequency']*(1+v.real/(2*np.pi/cfg['lattice_nm']))),power_loss_cm1=float(2*v.imag*1e7)) for i,v in enumerate(sorted(eigen,key=lambda v:v.real))]
            _csv(directory/'coupled_modes.csv',modes);np.savez_compressed(directory/'coupling_matrix.npz',C=C)
            summary.update(coupled_modes=modes,green_model=cfg['green_model']);summary['artifacts']+=['coupled_modes.csv','coupling_matrix.npz']
            if model in ('finite','beam'):
                try:_finite_outputs(cfg,C,row['frequency'],directory,summary,emit,cancelled)
                except (ValueError,RuntimeError,OSError,KeyError) as exc:
                    summary.update(status='partial',optional_output_error=str(exc))
    if cancelled():raise InterruptedError('PCSEL calculation cancelled')
    (directory/'pcsel_summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    emit(dict(kind='log',message='PCSEL '+model+' completed with status '+summary['status']))
    return summary


def _finite_outputs(cfg,C,frequency,directory,summary,emit,cancelled):
    if cfg['model']=='beam' and cfg['beam_saved_run']:
        modes,fields=_saved_finite(cfg)
        summary['finite_mode_source']=str(Path(cfg['beam_saved_run']).resolve())
    else:modes,fields=finite_modes(cfg,C,frequency,cancelled)
    _csv(directory/'finite_modes.csv',modes)
    physical=dict(x_um=(fields['x']-.5)*cfg['aperture_um'][0],y_um=(fields['x']-.5)*cfg['aperture_um'][1])
    axes=dict(fields=dict(axes=[dict(name='Mode'),dict(name='Basic wave (+x, -x, +y, -y)'),
        dict(name='y',coordinate='y_um',unit='µm'),dict(name='x',coordinate='x_um',unit='µm')],unit='normalized amplitude'))
    np.savez_compressed(directory/'finite_fields.npz',**fields,**physical,array_axes=json.dumps(axes))
    summary.update(finite_modes=modes);summary['artifacts']+=['finite_modes.csv','finite_fields.npz']
    def accepted(mode):return mode['balance_relative']<=.02 and mode['eigen_residual']<=1e-6 and mode['total_loss_cm1']>0
    if any(not accepted(mode) for mode in modes):summary['status']='unconverged'
    if cfg['model']!='beam':return
    eligible=[mode for mode in modes if accepted(mode) and (cfg['beam_mode']==-1 or mode['mode']==cfg['beam_mode'])]
    if not eligible:_error('beam_mode','No selected positive-loss mode passes the finite-mode residual and power-balance checks. Refine the cavity solve.')
    selected=min(eligible,key=lambda mode:mode['total_loss_cm1']);beam=far_field(cfg,fields,selected)
    near_axes=[dict(name='y',coordinate='y_um',unit='µm'),dict(name='x',coordinate='x_um',unit='µm')]
    far_axes=[dict(name='sin θy',coordinate='sin_theta_y',unit='dimensionless'),dict(name='sin θx',coordinate='sin_theta_x',unit='dimensionless')]
    axes={key:dict(axes=near_axes,unit=unit) for key,unit in [('Ex','µm^-1 (unit power)'),('Ey','µm^-1 (unit power)'),('near_per_um2','µm^-2')]}
    for key in ('far_paraxial_per_sr','far_x_per_sr','far_y_per_sr'):axes[key]=dict(axes=far_axes,unit='sr^-1 (paraxial)')
    normalization=cfg['beam_normalization'];power=cfg.get('beam_power_W',1.) if normalization=='calibrated_power' else 1.
    near_scale=1/beam['near_per_um2'].max() if normalization=='peak' else power
    far_scale=1/beam['far_paraxial_per_sr'].max() if normalization=='peak' else power
    beam['near_display']=beam['near_per_um2']*near_scale;beam['far_display']=beam['far_paraxial_per_sr']*far_scale
    axes['near_display']=dict(axes=near_axes,unit='peak = 1' if normalization=='peak' else 'W/µm²' if normalization=='calibrated_power' else 'µm^-2')
    axes['far_display']=dict(axes=far_axes,unit='peak = 1' if normalization=='peak' else 'W/sr (paraxial)' if normalization=='calibrated_power' else 'sr^-1 (paraxial)')
    np.savez_compressed(directory/'beam_fields.npz',**beam,array_axes=json.dumps(axes))
    center=len(beam['sin_theta_x'])//2;valid=abs(beam['sin_theta_x'])<1
    np.savetxt(directory/'beam_x.csv',np.column_stack([np.rad2deg(np.arcsin(beam['sin_theta_x'][valid])),beam['far_paraxial_per_sr'][center,valid],beam['far_display'][center,valid]]),
        delimiter=',',header='theta_x_deg,paraxial_intensity_per_sr,display_intensity',comments='')
    dx=cfg['aperture_um'][0]/cfg['beam_grid'];dy=cfg['aperture_um'][1]/cfg['beam_grid']
    summary.update(beam_mode=selected['mode'],parseval_power=float(beam['parseval_power']),
        polarization_basis='Cartesian aperture x/y components',polarization_power_fraction_x=float(np.sum(abs(beam['Ex'])**2)*dx*dy),
        polarization_power_fraction_y=float(np.sum(abs(beam['Ey'])**2)*dx*dy),
        beam_normalization=dict(mode=normalization,power_W=power if normalization=='calibrated_power' else None,source=cfg['beam_power_source']))
    summary['artifacts']+=['beam_fields.npz','beam_x.csv']


def _execute_sweep(cfg,directory,emit,cancelled):
    cases=cfg['parameter_sweep']['cases'];rows=[];results=[]
    summary=dict(status='partial',engine='pcsel',model=cfg['model'],convergence_established=False,
        limitations=LIMITATIONS+['Sweep completion is not a convergence or paper-agreement claim. Inspect each case and compare successive accuracy settings.'],
        artifacts=['pcsel_sweep.csv','pcsel_sweep.json'],cases=results)
    def save():
        _csv(directory/'pcsel_sweep.csv',rows)
        for name in ('pcsel_sweep.json','pcsel_summary.json'):
            (directory/name).write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    for index,case in enumerate(cases):
        if cancelled():
            save();raise InterruptedError('PCSEL sweep cancelled; completed cases have been preserved.')
        name=f'case-{index+1:04d}'
        item=dict(case=index+1,directory=name,parameters=case['parameters'])
        record=dict(case=index+1,**case['parameters'],status='',frequency=None,Gamma_QW=None,
            total_loss_cm1=None,radiation_loss_cm1=None,edge_loss_cm1=None,error='')
        try:
            result=execute(case['prepared'],directory/name,emit,cancelled)
            item['summary']=result;record['status']=result['status']
            for key in ('frequency','Gamma_QW'):record[key]=result.get('vertical',{}).get(key)
            modes=[r for r in result.get('finite_modes',[]) if r['total_loss_cm1']>0]
            if modes:
                selected=min(modes,key=lambda r:r['total_loss_cm1'])
                for key in ('total_loss_cm1','radiation_loss_cm1','edge_loss_cm1'):record[key]=selected.get(key)
            summary['artifacts'].append(name+'/pcsel_summary.json')
        except InterruptedError:
            save();raise
        except Exception as exc:
            item.update(status='failed',error=str(exc));record.update(status='failed',error=str(exc))
        results.append(item);rows.append(record);save()
        emit(dict(kind='progress',done=index+1,total=len(cases),message=f'PCSEL sweep: {index+1}/{len(cases)} cases saved.'))
    statuses={r['status'] for r in rows}
    summary['status']='partial' if 'failed' in statuses or 'partial' in statuses else 'validity_limit' if 'validity_limit' in statuses else 'unconverged' if 'unconverged' in statuses else 'complete'
    summary['completed_cases']=sum(r['status']!='failed' for r in rows)
    save()
    return summary
