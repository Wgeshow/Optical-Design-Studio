"""Descending absolute-amplitude superlevel sweep with connected-region lineage.

Input is |complex E|/|incident E|. Four-neighbor grid connectivity; no smoothing.
Physical area uses supplied pixel weights, including nonuniform depth spacing.
Raw amplitudes remain separate and unchanged; every threshold is retained.
"""
import math
import numpy as np

def _regions_reference(mask,periodic_x=False,periodic_y=False):
    ny,nx=mask.shape;labels=np.zeros(mask.shape,dtype=np.int32);count=0
    for j,i in zip(*np.where(mask)):
        if labels[j,i]:continue
        count+=1;labels[j,i]=count;queue=[(j,i)]
        for y,x in queue:
            for yy,xx in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
                if periodic_y:yy%=ny
                if periodic_x:xx%=nx
                if 0<=yy<ny and 0<=xx<nx and mask[yy,xx] and not labels[yy,xx]:
                    labels[yy,xx]=count;queue.append((yy,xx))
    return labels,count


def _regions_runs(mask,periodic_x=False,periodic_y=False):
    """Label horizontal runs rather than visiting each pixel's four neighbors."""
    mask=np.asarray(mask,dtype=bool);ny,nx=mask.shape
    labels=np.zeros(mask.shape,dtype=np.int32)
    changes=np.diff(np.pad(mask.astype(np.int8),((0,0),(1,1))),axis=1)
    rows,starts=np.where(changes==1);_,stops=np.where(changes==-1)
    count=len(starts)
    if not count:return labels,0
    offsets=np.r_[0,np.cumsum(np.bincount(rows,minlength=ny))]
    parents=list(range(count+1))
    def root(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    def merge(a,b):
        ra,rb=root(a),root(b)
        parents[max(ra,rb)]=min(ra,rb)
    def adjacent(a,b):
        i,end_i=int(offsets[a]),int(offsets[a+1]);j,end_j=int(offsets[b]),int(offsets[b+1])
        while i<end_i and j<end_j:
            if stops[i]<=starts[j]:i+=1
            elif stops[j]<=starts[i]:j+=1
            else:
                merge(i+1,j+1)
                if stops[i]<stops[j]:i+=1
                else:j+=1
    for y in range(ny):
        if y:adjacent(y-1,y)
        lo,hi=int(offsets[y]),int(offsets[y+1])
        if periodic_x and hi>lo and starts[lo]==0 and stops[hi-1]==nx:
            merge(lo+1,hi)
    if periodic_y:adjacent(0,ny-1)
    roots=np.array([root(i) for i in range(1,count+1)])
    unique=np.unique(roots);remap=np.zeros(count+1,dtype=np.int32)
    remap[unique]=np.arange(1,len(unique)+1)
    for y,start,stop,index in zip(rows,starts,stops,remap[roots]):
        labels[y,start:stop]=index
    return labels,len(unique)


def regions(mask,periodic_x=False,periodic_y=False):
    try:
        from scipy.ndimage import label
    except ImportError:
        return _regions_runs(mask,periodic_x,periodic_y)
    labels,count=label(mask)  # default is the same four-neighbor connectivity
    if not count or not (periodic_x or periodic_y):return labels,count
    parents=list(range(count+1))
    def root(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    pairs=[]
    if periodic_x:pairs.extend(zip(labels[:,0],labels[:,-1]))
    if periodic_y:pairs.extend(zip(labels[0,:],labels[-1,:]))
    for a,b in pairs:
        if a and b:
            ra,rb=root(int(a)),root(int(b))
            parents[max(ra,rb)]=min(ra,rb)
    roots=np.array([root(i) for i in range(count+1)])
    unique=np.unique(roots[1:]);remap=np.zeros(count+1,dtype=np.int32)
    remap[unique]=np.arange(1,len(unique)+1)
    # Retain row-major labels, including across a periodic seam, so lineage,
    # pixel runs and all saved contour identifiers match the reference sweep.
    return remap[roots[labels]],len(unique)

def sweep(amplitude,step=.1,pixel_area=None,x=None,y=None,periodic_x=False,periodic_y=False,noise_floor=1e-8):
    a=np.asarray(amplitude,dtype=float)
    if a.ndim!=2 or not np.isfinite(a).all() or np.any(a<0):raise ValueError('Expected a finite nonnegative 2D amplitude map')
    if not math.isfinite(step) or step<=0:raise ValueError('Step must be finite and positive')
    ny,nx=a.shape;area=np.ones_like(a) if pixel_area is None else np.broadcast_to(np.asarray(pixel_area,dtype=float),a.shape)
    if not np.isfinite(area).all() or np.any(area<=0):raise ValueError('Pixel areas must be positive and finite')
    total_area=float(area.sum())
    xs=np.arange(nx,dtype=float) if x is None else np.asarray(x,dtype=float);ys=np.arange(ny,dtype=float) if y is None else np.asarray(y,dtype=float)
    if len(xs)!=nx or len(ys)!=ny:raise ValueError('Coordinates must match the map')
    minimum=float(a.min());maximum=float(a.max());levels=np.round(np.arange(math.ceil(minimum/step),math.floor(maximum/step)+1)*step,12)
    # Exact observed endpoints, plus an incident-referenced grid shared by designs.
    levels=np.unique(np.r_[minimum,levels,maximum])[::-1]
    if len(levels)>20000:raise ValueError('More than 20000 levels; increase step')
    if maximum<noise_floor:
        return dict(schema_version=1,step=step,minimum=minimum,maximum=maximum,negligible=True,levels=[],tracks=[],summary=dict(level_count=0,births=0,merges=0,max_regions=0))
    prev=np.zeros_like(a,dtype=np.int32);next_id=0;tracks={};records=[];births=merges=0
    active_counts=a.size-np.searchsorted(np.sort(a,axis=None),levels,side='left')
    last_count=-1;stable_items=None
    for threshold,active_count in zip(levels,active_counts):
        if records and active_count==last_count:
            # Between two observed pixel amplitudes the entire mask is identical.
            # Retain every requested level, but reuse its shapes and statistics.
            previous=records[-1]
            if stable_items is None:
                stable_items=[dict(item,parents=[item['id']]) for item in previous['regions']]
            for item in stable_items:tracks[item['id']]['last_level']=float(threshold)
            records.append(dict(level=float(threshold),region_count=previous['region_count'],
                                area_fraction=previous['area_fraction'],regions=stable_items))
            continue
        last_count=active_count;stable_items=None
        labels,n=regions(a>=threshold,periodic_x,periodic_y);current=np.zeros_like(prev);items=[]
        for label in range(1,n+1):
            mask=labels==label;parents=sorted(int(k) for k in np.unique(prev[mask]) if k)
            if len(parents)==1:track_id=parents[0]
            else:
                next_id+=1;track_id=next_id
                event='birth' if not parents else 'merge'
                births+=int(not parents);merges+=int(bool(parents))
                tracks[track_id]=dict(id=track_id,event=event,parents=parents,birth_level=float(threshold),last_level=float(threshold))
                for p in parents:tracks[p]['merged_at']=float(threshold);tracks[p]['merged_into']=track_id
            current[mask]=track_id;tracks[track_id]['last_level']=float(threshold)
            jj,ii=np.where(mask);w=area[mask];physical=float(w.sum());
            # Pixel-center extents and centroid; seam-spanning periodic regions explicitly flagged.
            wrap_x=bool(periodic_x and np.any(mask[:,0]) and np.any(mask[:,-1]));wrap_y=bool(periodic_y and np.any(mask[0,:]) and np.any(mask[-1,:]))
            # Lossless row runs preserve each pixel-defined shape at every level.
            runs=[]
            row_mask=np.zeros(nx+2,dtype=np.int8)
            for row in np.unique(jj):
                row_mask[1:-1]=mask[row]
                change=np.diff(row_mask)
                for start,stop in zip(np.where(change==1)[0],np.where(change==-1)[0]):
                    runs.append([int(row),int(start),int(stop-start)])
            items.append(dict(id=track_id,parents=parents,area=physical,area_fraction=physical/total_area,
                centroid_x=float(np.average(xs[ii],weights=w)),centroid_y=float(np.average(ys[jj],weights=w)),
                xmin=float(xs[ii].min()),xmax=float(xs[ii].max()),ymin=float(ys[jj].min()),ymax=float(ys[jj].max()),
                pixel_runs=runs,peak=float(a[mask].max()),mean=float(np.average(a[mask],weights=w)),pixels=int(mask.sum()),wrap_x=wrap_x,wrap_y=wrap_y))
        records.append(dict(level=float(threshold),region_count=n,area_fraction=float(area[labels>0].sum()/total_area),regions=items))
        prev=current
    for t in tracks.values():t['persistence']=t['birth_level']-t.get('merged_at',minimum)
    return dict(schema_version=1,step=float(step),minimum=minimum,maximum=maximum,negligible=False,
                connectivity='four-neighbor',periodic_x=bool(periodic_x),periodic_y=bool(periodic_y),
                centroid_note='Arithmetic pixel-area centroid; seam-spanning regions flagged, not a periodic centroid.',
                levels=records,tracks=list(tracks.values()),
                summary=dict(level_count=len(records),births=births,merges=merges,max_regions=max(r['region_count'] for r in records),
                             mean_amplitude=float(np.average(a,weights=area)),max_amplitude=maximum,min_amplitude=minimum,
                             largest_persistences=sorted((t['persistence'] for t in tracks.values()),reverse=True)[:3]))

def feature_values(result,prefix='contour_v1.'):
    s=result['summary'];out={prefix+'negligible':float(result['negligible'])}
    for key in ('births','merges','max_regions','mean_amplitude','max_amplitude','min_amplitude'):
        out[prefix+key]=math.log1p(max(0.,s.get(key,0.)))
    lifetimes=s.get('largest_persistences',[])
    for k in range(3):out[prefix+'persistence_'+str(k)]=math.log1p(lifetimes[k] if k<len(lifetimes) else 0.)
    return out


def shape_features(result, amplitude, prefix):
    """Bounded spatial signatures preserve weak regions alongside absolute sweeps."""
    out=feature_values(result,prefix)
    a=np.asarray(amplitude,float);ny,nx=a.shape
    yy,xx=np.meshgrid((np.arange(ny)+.5)/ny,(np.arange(nx)+.5)/nx,indexing='ij')
    # Keep both level-set occupancy and periodic spatial moments. No maximum-only image.
    levels=np.r_[np.arange(17)*result['step'],np.linspace(0,result['maximum'],17)]
    moments={(axis,harmonic):np.exp(2j*np.pi*harmonic*coords)
             for axis,coords in [('x',xx),('y',yy)] for harmonic in (1,2)}
    for k,level in enumerate(levels):
        mask=a>=level;out[prefix+'shape.'+str(k)+'.area']=float(mask.mean())
        for axis,coords in [('x',xx),('y',yy)]:
            for harmonic in (1,2):
                z=np.mean(mask*moments[axis,harmonic])
                out[prefix+'shape.'+str(k)+'.'+axis+str(harmonic)+'.cos']=float(z.real)
                out[prefix+'shape.'+str(k)+'.'+axis+str(harmonic)+'.sin']=float(z.imag)
    return out


def describe_csv(directory, step=.1):
    """Track actual saved XY slices and XZ sections without interpolating depth."""
    import csv,json
    from pathlib import Path
    directory=Path(directory);groups={}
    with (directory/'electric_fields.csv').open(encoding='utf-8-sig',newline='') as stream:
        for r in csv.DictReader(stream):
            plane=r['plane']
            if plane not in ('volume_samples','xz'):continue
            key=(plane,r['layer'],float(r['z_um']) if plane=='volume_samples' else None)
            groups.setdefault(key,[]).append(r)
            if plane=='xz':groups.setdefault(('xz','__stack__',None),[]).append(r)
    saved=json.loads((directory/'field_model.json').read_text(encoding='utf-8'))
    model=saved['model'];grid=saved.get('settings',{}).get('grid',8)
    result={'schema_version':1,'step':step,'grid':grid,'views':{},'features':{}}
    layers=[l['name'] for l in model['layers'][1:-1] if l['thickness']>0]
    slices={}
    for (plane,layer,z),rows in sorted(groups.items()):
        xs=sorted({float(r['x_um']) for r in rows});ys=sorted({float(r['y_um'] if plane=='volume_samples' else r['z_um']) for r in rows})
        if len(rows)!=len(xs)*len(ys):raise ValueError('Incomplete contour map')
        e=np.zeros((len(ys),len(xs),3),complex);xi={v:i for i,v in enumerate(xs)};yi={v:i for i,v in enumerate(ys)}
        for r in rows:
            e[yi[float(r['y_um'] if plane=='volume_samples' else r['z_um'])],xi[float(r['x_um'])]]=[complex(float(r[c+'_real']),float(r[c+'_imag'])) for c in ('Ex','Ey','Ez')]
        index=slices.get(layer,0)
        if plane=='volume_samples':slices[layer]=index+1
        name='stack.xz' if layer=='__stack__' else 'layer'+str(layers.index(layer))+'.'+('xy'+str(index) if plane=='volume_samples' else 'xz')
        result['views'][name]={}
        dx=model['ax']/len(xs)
        if layer=='__stack__':
            thickness={l['name']:l['thickness'] for l in model['layers']}
            depth_count={n:len({float(r['z_um']) for r in rows if r['layer']==n}) for n in layers}
            row_layer={float(r['z_um']):r['layer'] for r in rows}
            dy=np.array([thickness[row_layer[z]]/depth_count[row_layer[z]] for z in ys])[:,None]
        else:
            dy=model['ay']/len(ys) if plane=='volume_samples' else next(l['thickness'] for l in model['layers'] if l['name']==layer)/len(ys)
        for i,c in enumerate(('Ex','Ey','Ez','total')):
            a=np.abs(e[:,:,i]) if i<3 else np.linalg.norm(e,axis=2)
            scan=sweep(a,step,dx*dy,xs,ys,True,plane=='volume_samples')
            result['views'][name][c]=scan
            prefix='contour_v1.step'+str(step)+'.grid'+str(grid)+'.'+name+'.'+c+'.'
            result['features'].update(shape_features(scan,a,prefix))
    (directory/'field_contours.json').write_text(json.dumps(result,separators=(',',':')),encoding='utf-8')
    return result
