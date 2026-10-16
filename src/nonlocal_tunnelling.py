"""Editable straight-column Gamma two-band WKB/Landauer pair source.

Recovered model generalization: explicit path axis, span, reservoir positions,
transverse mass and local band/mass arrays replace all study dimensions.
"""
from __future__ import annotations
import numpy as np
from scipy.constants import e,hbar,m_e,k
from scipy.special import expit
from scipy.integrate import trapezoid
from numpy.polynomial.legendre import leggauss
from photonic_bands import _number,_integer

LIMITATIONS=['Straight axis-aligned Gamma-channel two-band WKB/Landauer approximation; no Gamma-X, trap-assisted, lateral curved paths or calibrated tunnel interface transmission.',
    'Reservoir coordinates resolve to nearest cell centers within the explicit path span; resolved positions are reported. Mesh and energy/transverse quadrature convergence are required.',
    'Reverse interband pair generation only. Positive occupation difference is retained; forward tunnelling/recombination is outside this source law.',
    'A path-average reservoir temperature is used for occupancy; no thermoelectric tunnelling or carrier-energy distribution is solved.']


def validate_tunnelling(raw,mesh=None):
    fields={'axis','path_min_um','path_max_um','hole_reservoir_um','electron_reservoir_um','transverse_mass_ratio','energy_order','transverse_order','scale','materials','source'}
    if not isinstance(raw,dict) or set(raw)-fields:raise ValueError('Unsupported nonlocal tunnelling settings')
    if raw.get('axis') not in ('x','y','z'):raise ValueError('Tunnelling path axis must be x, y or z')
    if not isinstance(raw.get('source'),str) or not raw['source'].strip():raise ValueError('Tunnelling requires a source/assumption note')
    result=dict(axis=raw['axis'],source=raw['source'].strip(),energy_order=_integer(raw.get('energy_order',16),'energy_order',2),transverse_order=_integer(raw.get('transverse_order',8),'transverse_order',2))
    for field in ('path_min_um','path_max_um','hole_reservoir_um','electron_reservoir_um','transverse_mass_ratio','scale'):
        result[field]=_number(raw.get(field,1. if field=='scale' else None),field,positive=field=='transverse_mass_ratio')
    lo,hi=result['path_min_um'],result['path_max_um']
    if not lo<hi or not lo<=result['hole_reservoir_um']<=hi or not lo<=result['electron_reservoir_um']<=hi or result['hole_reservoir_um']==result['electron_reservoir_um'] or result['scale']<0:
        raise ValueError('Tunnelling path needs increasing bounds, distinct reservoirs inside the span, and nonnegative scale')
    materials=raw.get('materials')
    if not isinstance(materials,dict) or not materials:raise ValueError('Tunnelling needs explicit Gamma electron and hole masses for path materials')
    result['materials']={}
    for key,row in materials.items():
        if not isinstance(row,dict) or set(row)-{'electron_gamma_mass_ratio','hole_mass_ratio','gamma_gap_eV'} or not {'electron_gamma_mass_ratio','hole_mass_ratio'}<=set(row):raise ValueError('Tunnelling material needs electron_gamma_mass_ratio,hole_mass_ratio and optional gamma_gap_eV')
        result['materials'][key]={field:_number(value,key+'.'+field,positive=True) for field,value in row.items()}
    if mesh is not None:
        axis='xyz'.index(result['axis']);nodes=np.asarray(mesh['axes'][axis])*1e6
        selected=np.flatnonzero((nodes>=lo)&(nodes<=hi))
        if len(selected)<2:raise ValueError('Tunnelling span must contain at least two transport cell centers')
        resolved=[int(selected[np.argmin(abs(nodes[selected]-result[field]))]) for field in ('hole_reservoir_um','electron_reservoir_um')]
        if resolved[0]==resolved[1]:raise ValueError('Both tunnelling reservoirs resolve to the same cell; refine or edit the path')
        available={row['id']:row for row in mesh['materials']}
        if any(key not in available or available[key]['kind']!='semiconductor' for key in result['materials']):raise ValueError('Tunnelling path materials must be occupied semiconductors')
        result['resolved_hole_reservoir_um']=float(nodes[resolved[0]])
        result['resolved_electron_reservoir_um']=float(nodes[resolved[1]])
    return result


def source(axes_m,faces_m,volume_m3,semiconductor,conduction_eV,valence_eV,electron_mass_ratio,hole_mass_ratio,
           electron_fermi_eV,hole_fermi_eV,temperature_K,config,cancelled=lambda:False):
    shape=np.shape(volume_m3);axis='xyz'.index(config['axis']);others=[a for a in range(3) if a!=axis]
    order=others+[axis]
    def columns(value):return np.transpose(np.broadcast_to(np.asarray(value),shape),order).reshape(-1,shape[axis])
    volume=columns(volume_m3);sem=columns(semiconductor)
    ce,ve,me,mh,fn,fp,temp=[columns(value) for value in (conduction_eV,valence_eV,electron_mass_ratio,hole_mass_ratio,electron_fermi_eV,hole_fermi_eV,temperature_K)]
    if any(not np.isfinite(v).all() for v in (ce,ve,me,mh,fn,fp,temp)) or np.any(me<=0) or np.any(mh<=0) or np.any(temp<=0):raise ValueError('Tunnelling state arrays must be finite with positive masses and temperature')
    positions=np.asarray(axes_m[axis]);selected=np.flatnonzero((positions*1e6>=config['path_min_um'])&(positions*1e6<=config['path_max_um']))
    if len(selected)<2:raise ValueError('Tunnelling path is unresolved')
    if config['hole_reservoir_um']>config['electron_reservoir_um']:selected=selected[::-1]
    z=positions[selected];distance=np.r_[0.,np.cumsum(abs(np.diff(z)))]
    ih=int(np.argmin(abs(z*1e6-config['hole_reservoir_um'])));ie=int(np.argmin(abs(z*1e6-config['electron_reservoir_um'])))
    if ih>=ie:raise ValueError('Resolved hole reservoir must precede the electron reservoir along the tunnelling path')
    ge=np.zeros_like(volume);gp=np.zeros_like(volume);heat=np.zeros_like(volume)
    currents=np.zeros(len(volume));eligible=0;transfers={}
    a,we=leggauss(config['energy_order']);t,wt=leggauss(config['transverse_order']);mt=config['transverse_mass_ratio']*m_e
    area=np.multiply.outer(np.diff(faces_m[others[0]]),np.diff(faces_m[others[1]])).ravel()
    for column in range(len(volume)):
        if cancelled():raise InterruptedError('Nonlocal tunnelling cancelled')
        if not sem[column,selected].all():continue
        eligible+=1
        ec,ev=ce[column,selected],ve[column,selected];emn,emh=me[column,selected],mh[column,selected]
        if np.any(ec<=ev):raise ValueError('Two-band tunnelling requires positive local direct gaps')
        overlap=ev[ih]-ec[ie]
        if overlap<=0:continue
        max_transverse=overlap/(mt/(emn[ie]*m_e)+mt/(emh[ih]*m_e))
        perps=(t+1)*max_transverse/2;wp=wt*max_transverse/2
        for perpendicular,weight_p in zip(perps,wp):
            conduction=ec+perpendicular*mt/(emn*m_e);valence=ev-perpendicular*mt/(emh*m_e)
            low,high=conduction[ie],valence[ih]
            if high<=low:continue
            for energy,weight_e in zip((a+1)*(high-low)/2+low,we*(high-low)/2):
                origins=np.flatnonzero((valence>=energy)&(np.arange(len(z))<=ie))
                if not len(origins):continue
                start=origins[-1];destinations=np.flatnonzero((conduction<=energy)&(np.arange(len(z))>start))
                if not len(destinations):continue
                stop=destinations[0];path=np.arange(start,stop+1)
                gap=conduction[path]-valence[path];mr=emn[path]*emh[path]/(emn[path]+emh[path])*m_e
                barrier=np.maximum((conduction[path]-energy)*(energy-valence[path])/gap,0)*e
                kappa=np.sqrt(2*mr*barrier)/hbar
                action=2*trapezoid(kappa,distance[path]);transmission=np.exp(-action)
                nsite,psite=selected[stop],selected[start]
                thermal=k*(temp[column,nsite]+temp[column,psite])/2/e
                occupied=expit((fp[column,psite]-energy)/thermal)-expit((fn[column,nsite]-energy)/thermal)
                density=e*mt/(2*np.pi**2*hbar**3)*e**2*weight_e*weight_p*transmission*max(occupied,0)*config['scale']
                pairs=density*area[column]/e
                if not pairs:continue
                gp[column,psite]+=pairs/volume[column,psite];ge[column,nsite]+=pairs/volume[column,nsite]
                dissipation=e*pairs*(fp[column,psite]-fn[column,nsite])
                heat[column,psite]+=dissipation/2;heat[column,nsite]+=dissipation/2
                currents[column]+=density
                key=(column,int(psite),int(nsite));transfers[key]=transfers.get(key,0.)+e*pairs
    def grid(value):return np.transpose(value.reshape(tuple(shape[a] for a in order)),np.argsort(order))
    integrated=float(np.sum(ge*volume));imbalance=float(np.sum((ge-gp)*volume))
    if abs(imbalance)>max(1e-12*integrated,1e-20):raise RuntimeError('Nonlocal electron/hole pair deposition is not conservative')
    return dict(electron_generation_m3_s=grid(ge),hole_generation_m3_s=grid(gp),reservoir_dissipation_W=grid(heat),
        column_current_A_m2=currents.reshape(tuple(shape[a] for a in others)),
        transfers=[dict(column=int(a),hole_axis_index=int(b),electron_axis_index=int(c),current_A=float(value)) for (a,b,c),value in transfers.items()],
        checks=dict(eligible_columns=eligible,total_columns=len(volume),integrated_pairs_s=integrated,pair_balance_error_s=imbalance,
                    resolved_hole_reservoir_um=float(z[ih]*1e6),resolved_electron_reservoir_um=float(z[ie]*1e6)))
