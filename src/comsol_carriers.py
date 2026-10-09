"""Import four COMSOL arc-length carrier exports without smoothing jumps."""
import bisect
import hashlib
import math
from pathlib import Path

def _read(path,tolerance):
    path=Path(path);raw=path.read_bytes()
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:text=raw.decode('cp1252')
    groups={};clipped=[];rows=0;previous=None
    for lineno,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line or line.startswith('%'):continue
        parts=line.split()
        if len(parts)!=2:raise ValueError(f'{path.name}:{lineno}: expected arc length and one carrier concentration.')
        try:z,value=map(float,parts)
        except ValueError:raise ValueError(f'{path.name}:{lineno}: nonnumeric profile row.') from None
        if not math.isfinite(z) or not math.isfinite(value) or z<0 or value>1e20:raise ValueError(f'{path.name}:{lineno}: invalid depth or concentration.')
        if value<0:
            if -value>tolerance:raise ValueError(f'{path.name}:{lineno}: negative concentration {value:g} cm^-3 exceeds the selected cleanup tolerance {tolerance:g}.')
            clipped.append(dict(line=lineno,z_um=z,raw_cm3=value));value=0.
        # COMSOL prints nominally identical mesh nodes with ~1e-17 µm noise.
        # Merge only to 12 decimal places (1e-6 nm), preserving duplicate order.
        z=round(z,12);groups.setdefault(z,[]).append(value);rows+=1
        if previous is not None and z<previous:raise ValueError(f'{path.name}:{lineno}: depths must follow one increasing directed cut line.')
        previous=z
        if len(groups[z])>2:raise ValueError(f'{path.name}: more than two values at one depth; export one directed cut line.')
    if len(groups)<2:raise ValueError(path.name+': at least two depths are needed.')
    depths=sorted(groups)
    return groups,dict(path=str(path.resolve()),sha256=hashlib.sha256(raw).hexdigest(),rows=rows,
                      depth_start_um=depths[0],depth_stop_um=depths[-1],clipped_count=len(clipped),clipped_samples=clipped)

def _at(groups,z,side):
    keys=sorted(groups);i=bisect.bisect_left(keys,z)
    if i<len(keys) and keys[i]==z:return groups[z][0 if side=='left' else -1]
    if i==0 or i==len(keys):raise ValueError('Carrier export does not cover the complete optical stack.')
    a,b=keys[i-1],keys[i];weight=(z-a)/(b-a)
    return groups[a][-1]+weight*(groups[b][0]-groups[a][-1])

def import_comsol_profiles(reference_electrons,reference_holes,biased_electrons,biased_holes,
                          top_layer,bottom_layer,negative_tolerance_cm3=0.,interfaces=(0.,.2,.22,.42)):
    """Map a directed GaAs / unchanged spacer / GaAs line to layer-local profiles.

    Units are explicitly supplied by this workflow: arc µm, concentration cm^-3.
    Duplicate rows are left/right limits in original line order. Interfaces use
    the appropriate one-sided value. No density averaging crosses a jump.
    """
    tolerance=float(negative_tolerance_cm3)
    if not math.isfinite(tolerance) or not 0<=tolerance<=1e4:raise ValueError('Negative-noise tolerance must be from 0 to 10,000 cm^-3.')
    if not top_layer or not bottom_layer or top_layer==bottom_layer:raise ValueError('Choose two distinct GaAs layer names.')
    bounds=list(map(float,interfaces))
    if len(bounds)!=4 or not all(math.isfinite(v) for v in bounds) or not all(a<b for a,b in zip(bounds,bounds[1:])):raise ValueError('Provide four increasing finite stack interfaces.')
    paths=[reference_electrons,reference_holes,biased_electrons,biased_holes]
    sources=[_read(p,tolerance) for p in paths];groups=[s[0] for s in sources]
    keys=('reference_electron_cm3','reference_hole_cm3','electron_cm3','hole_cm3')
    profiles=[]
    for layer,start,stop in [(top_layer,bounds[0],bounds[1]),(bottom_layer,bounds[2],bounds[3])]:
        nodes=sorted({round(start,12),round(stop,12)}|{z for g in groups for z in g if start<z<stop})
        for z in nodes:
            sides=['right'] if z==start else ['left'] if z==stop else ['left','right'] if any(len(g.get(z,[]))==2 for g in groups) else ['right']
            for side in sides:
                profiles.append(dict(layer=layer,z_um=round(z-start,12),side=side,**{key:_at(g,z,side) for key,g in zip(keys,groups)}))
    report=dict(format='COMSOL two-column arc-length exports',density_unit='cm^-3 (user-specified)',depth_unit='um',
                interfaces_um=bounds,unchanged_spacer_um=[bounds[1],bounds[2]],source_files=[s[1] for s in sources],
                negative_tolerance_cm3=tolerance,clipped_count=sum(s[1]['clipped_count'] for s in sources),
                duplicate_policy='Original first/last duplicate values are left/right limits; no interpolation across discontinuities.',
                depth_rounding_um=1e-12,profile_rows=len(profiles),profile_sampling='knots',
                layer_mapping=[dict(layer=top_layer,start_um=bounds[0],stop_um=bounds[1]),dict(layer=bottom_layer,start_um=bounds[2],stop_um=bounds[3])])
    return dict(profiles=profiles,report=report)
