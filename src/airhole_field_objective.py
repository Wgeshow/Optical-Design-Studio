"""Geometry-following volume, XY and XZ scores for aligned circular airholes.

All values use complex phasor magnitude, not abs(real(E)). Geometry is um.
XZ is through the hole center, rather than a fixed global plane for moved holes.
The objective requires BOTH volume and XZ confinement; no symmetry-zero
component ratio can create spurious feasibility.
"""
import math
import numpy as np

DEFAULTS=dict(shell_um=.020,contrast_target=3.,coverage_target=.8,
              radial_samples=3,angle_samples=24,depth_samples=3,
              component='total',schema_version=1)

def statistics(outside,inside,weights):
    o=np.asarray(outside,dtype=complex);i=np.asarray(inside,dtype=complex)
    w=np.asarray(weights,dtype=float)
    if o.shape!=i.shape or o.ndim!=3 or o.shape[2]!=3 or w.shape!=(o.shape[0],):
        raise ValueError('Expected matched depth x lateral x component fields and depth weights')
    if not np.isfinite(o).all() or not np.isfinite(i).all() or not np.isfinite(w).all() or np.any(w<=0):
        raise ValueError('Fields and positive depth weights must be finite')
    values={}
    for name,index in [('total',None),('Ex',0),('Ey',1),('Ez',2)]:
        ao=np.sqrt(np.sum(np.abs(o)**2,axis=2)) if index is None else np.abs(o[:,:,index])
        ai=np.sqrt(np.sum(np.abs(i)**2,axis=2)) if index is None else np.abs(i[:,:,index])
        om=float(np.average(ao.mean(axis=1),weights=w));im=float(np.average(ai.mean(axis=1),weights=w))
        oq=float(np.average((ao**2).mean(axis=1),weights=w));iq=float(np.average((ai**2).mean(axis=1),weights=w))
        negligible=max(oq,iq)<1e-16
        values[name]=dict(outside_mean_abs=om,inside_mean_abs=im,outside_E2=oq,inside_E2=iq,
                          rms_contrast=None if negligible or iq<=1e-24 else math.sqrt(oq/iq),
                          mean_abs_contrast=None if negligible or im<=1e-12 else om/im,
                          negligible=negligible)
    return values

def aligned_hole(model,shell):
    patterns=model['patterns']
    if not patterns or any(p['shape']!='circle' for p in patterns):
        raise ValueError('This objective requires one aligned circular airhole per perforated layer')
    names=[p['layer'] for p in patterns]
    if len(set(names))!=len(names):raise ValueError('Only one hole per perforated layer is supported')
    first=patterns[0]
    if any(any(abs(p[k]-first[k])>1e-12 for k in ('cx','cy','sx')) or p['material']!=first['material'] for p in patterns):
        raise ValueError('Hole centers, radii and fill materials must match across layers')
    r=first['sx']
    if r<=0 or shell<=0 or abs(first['cx'])+r+shell>=model['ax']/2 or abs(first['cy'])+r+shell>=model['ay']/2:
        raise ValueError('Hole and exterior shell must fit inside the unit cell')
    layers=[];z=0.
    for layer in model['layers'][1:-1]:
        if layer['name'] in names:
            if layer['thickness']<=0:raise ValueError('Perforated layers need positive thickness')
            layers.append((layer,z))
        z+=layer['thickness']
    if len(layers)!=len(names):raise ValueError('All patterned layers must be finite internal layers')
    return first,layers

def evaluate(simulation,model,settings=None):
    cfg=dict(DEFAULTS,**(settings or {}))
    if cfg['component'] not in ('total','Ex','Ey','Ez'):raise ValueError('Unknown component')
    if cfg['contrast_target']<=0 or not 0<=cfg['coverage_target']<=1:raise ValueError('Invalid target')
    nr,nt,nz=[cfg[k] for k in ('radial_samples','angle_samples','depth_samples')]
    if any(not isinstance(n,int) or n<2 for n in (nr,nt,nz)):raise ValueError('Sample counts must be integers >=2')
    p,layers=aligned_hole(model,cfg['shell_um']);r=p['sx'];h=cfg['shell_um'];cx=p['cx'];cy=p['cy']
    fraction=(np.arange(nr)+.5)/nr;angles=2*np.pi*(np.arange(nt)+.5)/nt
    def field(x,y,z):return simulation.GetFields(float(cx+x),float(cy+y),float(z))[0]
    def fields(xy,z):
        if hasattr(simulation,'GetFieldsMany'):
            return np.asarray(simulation.GetFieldsMany([(float(cx+x),float(cy+y)) for x,y in xy],float(z))[0])
        return np.array([field(x,y,z) for x,y in xy])
    def ring(lo,hi,z):
        radii=np.sqrt(lo**2+(hi**2-lo**2)*fraction)
        return fields([(rad*np.cos(a),rad*np.sin(a)) for rad in radii for a in angles],z)
    def xz(z):
        # Each side has equal-width exterior samples; interior covers the full diameter.
        outside=fields([(sign*(r+h*f),0) for sign in (-1,1) for f in fraction],z)
        inside=fields([(-r+2*r*(j+.5)/(2*nr),0) for j in range(2*nr)],z)
        return outside,inside
    vo=[];vi=[];xo=[];xi=[];weights=[];xy=[]
    for layer,z0 in layers:
        mid=z0+layer['thickness']/2
        mo,mi=ring(r,r+h,mid),ring(0,r,mid)
        xy.append(dict(layer=layer['name'],z_um=mid,components=statistics(mo[None],mi[None],[1.])))
        for f in (np.arange(nz)+.5)/nz:
            z=z0+f*layer['thickness'];vo.append(ring(r,r+h,z));vi.append(ring(0,r,z));a,b=xz(z);xo.append(a);xi.append(b);weights.append(layer['thickness']/nz)
    vo,vi,xo,xi=map(np.array,(vo,vi,xo,xi));w=np.array(weights)
    volume=statistics(vo,vi,w);side=statistics(xo,xi,w)
    def e2(a):return (np.abs(a)**2).sum(axis=-1) if cfg['component']=='total' else np.abs(a[:,:,'xyz'.index(cfg['component'][-1])])**2
    vstat=volume[cfg['component']];xstat=side[cfg['component']]
    angular=np.average(e2(vo).reshape(-1,nr,nt).mean(axis=1),axis=0,weights=w)
    vol_coverage=float(np.mean(angular>=cfg['contrast_target']**2*vstat['inside_E2'])) if not vstat['negligible'] else 0.
    # Require coverage on BOTH sidewalls, across depth; an isolated corner cannot pass.
    walls=e2(xo).reshape(-1,2,nr).mean(axis=2)
    wall_coverage=np.average(walls>=cfg['contrast_target']**2*xstat['inside_E2'],axis=0,weights=w) if not xstat['negligible'] else np.zeros(2)
    xz_coverage=float(min(wall_coverage))
    contrasts=[vstat['rms_contrast'],xstat['rms_contrast']]
    feasible=all(c is not None and c>=cfg['contrast_target'] for c in contrasts) and min(vol_coverage,xz_coverage)>=cfg['coverage_target']
    objective=math.sqrt(vstat['outside_E2']*xstat['outside_E2'])
    # A sidewall-adjacent depth trace through EVERY finite material layer.
    # Fractional per-layer sampling preserves thin films and comparable geometry changes.
    profile=[];z0=0.
    for layer in model['layers'][1:-1]:
        if layer['thickness']>0:
            for fraction in (np.arange(17)+.5)/17:
                z=z0+layer['thickness']*fraction
                values=np.abs(field(r+h/2,0,z))
                profile.append(dict(layer=layer['name'],z_um=float(z),layer_fraction=float(fraction),
                                    abs_E=list(map(float,values)),total_abs=float(np.linalg.norm(values))))
        z0+=layer['thickness']
    return dict(schema_version=1,settings=cfg,volume=volume,xy_midplanes=xy,xz=side,
                volume_angular_coverage=vol_coverage,xz_sidewall_coverage=xz_coverage,
                xz_each_side_coverage=list(map(float,wall_coverage)),
                depth_profile=profile,objective=objective,feasible=bool(feasible),
                constraints=dict(volume_rms_contrast=contrasts[0],xz_rms_contrast=contrasts[1],
                                 volume_coverage=vol_coverage,xz_coverage=xz_coverage))

def targets(result):
    c=result['constraints']
    return [math.log(max(result['objective'],1e-24)),
            math.log(max(c['volume_rms_contrast'] or 0.,1e-12)),
            math.log(max(c['xz_rms_contrast'] or 0.,1e-12)),c['volume_coverage'],c['xz_coverage']]

def shape_covariates(observations,pool,fit_predict):
    x=np.array([o['x'] for o in observations]);pool=np.asarray(pool)
    # Predict shape covariates for both measured and untried geometries.
    # Never use measured-only field features as candidate inputs.
    contour_keys=sorted(set.intersection(*(set(o['fields'].get('contour_features',{})) for o in observations))) if observations else []
    contour_components=0
    if len(observations)>=4 and contour_keys:
        values=np.array([[o['fields']['contour_features'][k] for k in contour_keys] for o in observations])
        scale=values.std(axis=0);varying=scale>1e-8
        if varying.any():
            normalized=(values[:,varying]-values[:,varying].mean(axis=0))/scale[varying]
            _,singular,components=np.linalg.svd(normalized,full_matrices=False)
            contour_components=min(3,len(observations)//4,int(np.sum(singular>1e-8)))
            query=np.concatenate([x,pool]);predictions=[]
            for score in (normalized@components[:contour_components].T).T:
                mu,_,_=fit_predict(x,score/max(score.std(),1e-8),query,.05)
                predictions.append(np.tanh(mu))
            if predictions:
                covariates=.35/np.sqrt(contour_components)*np.asarray(predictions).T
                x=np.concatenate([x,covariates[:len(x)]],axis=1)
                pool=np.concatenate([pool,covariates[len(x):]],axis=1)
    return x,pool,dict(contour_features=len(contour_keys),contour_components=contour_components)


def choose_candidate(observations,pool,fit_predict,ndtr,expected_improvement,settings=None):
    """Normalized geometry in observations['x']; measurements never predicted as facts."""
    cfg=dict(DEFAULTS,**(settings or {}));x=np.array([o['x'] for o in observations]);y=np.array([targets(o['fields']) for o in observations]);pool=np.asarray(pool)
    x,pool,shape=shape_covariates(observations,pool,fit_predict)
    mus=[];stds=[]
    for col in range(5):
        mu,sd,_=fit_predict(x,y[:,col],pool,.015);mus.append(mu);stds.append(sd)
    thresholds=[math.log(cfg['contrast_target'])]*2+[cfg['coverage_target']]*2
    probabilities=[ndtr((mus[j+1]-thresholds[j])/stds[j+1]) for j in range(4)]
    probability=np.prod(probabilities,axis=0)
    feasible=[o['fields']['objective'] for o in observations if o['fields']['feasible']]
    acquisition=probability if not feasible else probability*expected_improvement(mus[0],stds[0],math.log(max(feasible)))
    reason='joint volume and XZ feasibility' if not feasible else 'joint constrained expected improvement'
    if float(np.max(acquisition))<1e-12:
        # Minimax standardized shortfall: XZ affects proposals even before any feasible sample.
        acquisition=-sum(np.maximum(0.,(t-mu)/sd)**2 for t,mu,sd in zip(thresholds,mus[1:],stds[1:]))
        reason='joint constraint shortfall exploration'
    index=int(np.argmax(acquisition))
    return index,dict(reason=reason,**shape,predicted_joint_feasibility=float(probability[index]),
                      predicted_xz_rms_contrast=float(np.exp(mus[2][index])))


def feature_values(result):
    """Stable finite learning features; undefined contrast has an explicit mask."""
    cfg=result['settings']
    prefix='airhole_v1.'+str(cfg['shell_um'])+'.'+str(cfg['radial_samples'])+'_'+str(cfg['angle_samples'])+'_'+str(cfg['depth_samples'])+'.'
    values={}
    views=[('volume',result['volume']),('xz',result['xz'])]
    views += [('xy_'+str(i),v['components']) for i,v in enumerate(result['xy_midplanes'])]
    for view,components in views:
        for name,stats in components.items():
            for key in ('outside_mean_abs','inside_mean_abs','outside_E2','inside_E2','rms_contrast'):
                value=stats[key];p=prefix+view+'.'+name+'.'+key
                values[p]=math.log1p(max(0.,value)) if value is not None else 0.
                if key=='rms_contrast':values[p+'.defined']=float(value is not None)
    for j,point in enumerate(result['depth_profile']):
        for axis,value in zip('xyz',point['abs_E']):values[prefix+'zline17.'+str(j)+'.E'+axis]=math.log1p(value)
    return values
