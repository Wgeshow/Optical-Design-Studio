"""Terminal charge C–V and frozen-conductivity I–V estimates.

The I–V calculation is explicitly a low-field Ohmic conductivity estimate using
the reference DC carrier population. It does not solve junction transport,
continuity, injection or leakage. No artificial conductivity is added to voids.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.constants import e
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from electrical_mesh import solve_linear_system

IV_MODEL = 'Ohmic conductivity estimate (not junction transport/leakage)'
CV_MODEL = 'Electrode displacement-charge derivative (electrostatic C–V)'


def validate_studies(cfg=None):
    """Validate optional persistable study settings without starting a solve."""
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise ValueError('Terminal study settings must be an object')
    result = dict(iv_enabled=False, cv_enabled=False, measured_iv_path='', measured_cv_path='')
    unknown = set(cfg)-set(result)
    if unknown:
        raise ValueError('Unsupported terminal study settings: '+', '.join(sorted(unknown)))
    result.update(cfg)
    for key in ('iv_enabled','cv_enabled'):
        if not isinstance(result[key],bool):
            raise ValueError(key+' must be true or false')
    for key in ('measured_iv_path','measured_cv_path'):
        if not isinstance(result[key],str):
            raise ValueError(key+' must be a file path string')
        result[key] = result[key].strip()
    return result


def read_measured_csv(path, kind='iv'):
    """Read a finite two-column measured curve without inferring a model."""
    if kind not in ('iv','cv'):
        raise ValueError('Measured curve kind must be iv or cv')
    column = 'current_A' if kind=='iv' else 'capacitance_F'
    path = Path(path)
    if path.stat().st_size > 10*1024*1024:
        raise ValueError('Measured curve CSV exceeds the 10 MiB limit')
    with path.open('r',newline='',encoding='utf-8-sig') as stream:
        reader=csv.DictReader(stream)
        if not reader.fieldnames or not {'bias_V',column} <= set(reader.fieldnames):
            raise ValueError('Measured '+kind.upper()+' CSV requires bias_V and '+column+' columns')
        rows=[]
        for index,row in enumerate(reader):
            if index>=100000:
                raise ValueError('Measured curve has more than 100000 samples')
            try:
                voltage=float(row['bias_V']); value=float(row[column])
            except (TypeError,ValueError):
                raise ValueError('Measured curve contains a nonnumeric sample') from None
            if not math.isfinite(voltage) or not math.isfinite(value):
                raise ValueError('Measured curve samples must be finite')
            rows.append(dict(bias_V=voltage,**{column:value}))
    if len(rows)<2:
        raise ValueError('Measured curve needs at least two samples')
    if len({row['bias_V'] for row in rows}) != len(rows):
        raise ValueError('Measured curve voltages must be unique')
    rows.sort(key=lambda row:row['bias_V'])
    return rows


def _write_rows(path, rows, columns):
    with Path(path).open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns)
        writer.writeheader(); writer.writerows(rows)


def terminal_cv(summary):
    """Return signed dQ/dV at the swept electrode using actual terminal voltages."""
    swept=summary.get('options',{}).get('swept_contact_id')
    if not swept:
        raise ValueError('C–V requires the custom solver swept contact identity')
    samples=[]
    fixed_voltages=None
    for row in summary.get('results',[]):
        checks=row.get('checks',{})
        try:
            voltage=float(checks['terminal_voltages_V'][swept])
            charge=float(checks['terminal_charge_C'][swept])
        except (KeyError,TypeError,ValueError):
            raise ValueError('C–V requires saved voltage and charge for the swept electrode') from None
        if not math.isfinite(voltage) or not math.isfinite(charge):
            raise ValueError('C–V terminal samples must be finite')
        others={key:float(value) for key,value in checks['terminal_voltages_V'].items() if key!=swept}
        if fixed_voltages is None:
            fixed_voltages=others
        elif set(others)!=set(fixed_voltages) or any(not math.isfinite(value) or abs(value-fixed_voltages[key])>1e-10 for key,value in others.items()):
            raise ValueError('C–V requires all other terminal voltages to remain fixed')
        samples.append((voltage,charge,float(row['bias_V'])))
    samples.sort()
    if len(samples)<3 or len({row[0] for row in samples}) != len(samples):
        raise ValueError('C–V requires at least three distinct swept terminal voltages. Add intermediate bias samples.')
    voltage=np.array([row[0] for row in samples]); charge=np.array([row[1] for row in samples])
    capacitance=np.gradient(charge,voltage,edge_order=2)
    if not np.isfinite(capacitance).all():
        raise ValueError('C–V derivative is not finite; separate the voltage samples')
    rows=[dict(bias_V=float(bias),terminal_voltage_V=float(v),terminal_charge_C=float(q),
               capacitance_F=float(c)) for (v,q,bias),c in zip(samples,capacitance)]
    spacings=np.diff(voltage)
    warnings=['C–V is a numerical terminal-charge derivative. Repeat with smaller voltage steps and a refined spatial mesh to establish convergence.',
              'Endpoint derivatives use a one-sided quadratic estimate and may be less reliable than interior samples.',
              'Quasi-static capacitance omits lifetime-dependent AC/transient response, AC frequency response, series resistance and dynamic interface traps.']
    if spacings.max()/spacings.min()>4:
        warnings.append('Voltage spacing varies by more than a factor of four; derivative accuracy may vary across the curve.')
    if np.any(capacitance<0):
        warnings.append('The signed electrode-charge derivative contains negative values. Inspect terminal polarity, mesh/bias convergence and the prescribed-reservoir model.')
    if np.ptp(charge) <= max(float(np.max(np.abs(charge)))*1e-12,1e-30):
        warnings.append('No electrode displacement-charge change was resolved. A zero derived value does not establish zero junction capacitance; prescribed carrier reservoirs omit transported reservoir charge.')
    if summary.get('options',{}).get('charge_model')=='semiconductor' and summary.get('options',{}).get('transport',{}).get('mode')!='semiconductor_dd':
        warnings.append('This curve differentiates electrode displacement charge. The prescribed-reservoir Poisson model does not include transported reservoir charge or predict a diode junction C–V response.')
    elif summary.get('options',{}).get('transport',{}).get('mode')=='semiconductor_dd':
        warnings.append('This is a quasi-static derivative of self-consistently solved DC electrode charge. It does not replace a frequency-resolved small-signal AC or transient capacitance calculation.')
    return rows,dict(model=CV_MODEL,swept_contact_id=swept,
                     sign_convention='C = dQ_swept_electrode / dV_swept_electrode, with all other applied terminal voltages fixed',
                     warnings=warnings)


def _conductivity(mesh, data):
    """Use an explicit fixed-conductivity override, otherwise carrier mobility."""
    n=np.asarray(data['electrons_cm3'],float); p=np.asarray(data['holes_cm3'],float)
    if n.shape!=mesh['shape'] or p.shape!=mesh['shape']:
        raise ValueError('Reference carrier volume does not match the editable device mesh')
    if not np.isfinite(n).all() or not np.isfinite(p).all() or np.any(n<0) or np.any(p<0):
        raise ValueError('Reference carrier populations must be finite and nonnegative')
    properties=[row['properties'] for row in mesh['materials']]
    indices=mesh['material_index']
    mun=np.take([row.get('electron_mobility_cm2_Vs',0.) for row in properties],indices)
    mup=np.take([row.get('hole_mobility_cm2_Vs',0.) for row in properties],indices)
    fixed=np.take([row.get('conductivity_S_m',0.) for row in properties],indices)
    overridden=np.take(['conductivity_S_m' in row for row in properties],indices)
    sigma=np.where(overridden,fixed,e*100.*(n*mun+p*mup))
    sigma=np.where(mesh['solid'],sigma,0.)
    if not np.isfinite(sigma).all() or np.any(sigma<0):
        raise ValueError('Material/carrier conductivity must be finite and nonnegative')
    return sigma


def _conductance_system(mesh, sigma):
    """Return finite-volume Ohmic graph, keeping zero-sigma cells disconnected."""
    index=mesh['index']; widths=mesh['widths']; values=sigma.ravel()
    removed={(min(int(a),int(b)),max(int(a),int(b))) for c in mesh['contacts']
             for a,b in zip(c['ids'],c['others']) if b>=0}
    aa=[];bb=[];gg=[]
    for axis in range(3):
        lo=[slice(None)]*3;hi=[slice(None)]*3
        lo[axis]=slice(0,-1);hi[axis]=slice(1,None);lo=tuple(lo);hi=tuple(hi)
        a=index[lo].ravel();b=index[hi].ravel()
        active=(values[a]>0)&(values[b]>0)
        if removed:
            active &= np.fromiter(((min(int(i),int(j)),max(int(i),int(j))) not in removed for i,j in zip(a,b)),bool,len(a))
        a,b=a[active],b[active]
        ca,cb=np.unravel_index(a,mesh['shape']),np.unravel_index(b,mesh['shape'])
        area=np.ones(len(a))
        for other in range(3):
            if other!=axis:area*=widths[other][ca[other]]
        g=area/(widths[axis][ca[axis]]/(2*values[a])+widths[axis][cb[axis]]/(2*values[b]))
        aa.append(a);bb.append(b);gg.append(g)
    a=np.concatenate(aa);b=np.concatenate(bb);g=np.concatenate(gg)
    size=index.size
    diagonal=np.bincount(np.r_[a,b],weights=np.r_[g,g],minlength=size).astype(float)
    contacts=[]
    for contact in mesh['contacts']:
        coefficient=values[contact['ids']]*contact['area']/contact['distance']
        diagonal[contact['ids']]+=coefficient
        other=contact['others']; valid=other>=0
        extra=np.zeros(len(other))
        if valid.any():
            coords=np.unravel_index(other[valid],mesh['shape'])
            distance=widths[contact['axis']][coords[contact['axis']]]/2
            extra[valid]=values[other[valid]]*contact['area'][valid]/distance
            diagonal[other[valid]]+=extra[valid]
        contacts.append(dict(object=contact['object'],ids=contact['ids'],others=other,
                             coefficient=coefficient,other_coefficient=extra))
    matrix=coo_matrix((np.r_[diagonal,-g,-g],
        (np.r_[np.arange(size),a,b],np.r_[np.arange(size),b,a])),shape=(size,size)).tocsr()
    adjacency=coo_matrix((np.ones(len(a)*2),(np.r_[a,b],np.r_[b,a])),shape=(size,size)).tocsr()
    _,labels=connected_components(adjacency,directed=False)
    anchored_labels=set()
    for contact in contacts:
        anchored_labels.update(labels[contact['ids'][contact['coefficient']>0]].tolist())
        valid=(contact['others']>=0)&(contact['other_coefficient']>0)
        anchored_labels.update(labels[contact['others'][valid]].tolist())
    active=(values>0)&np.isin(labels,list(anchored_labels))
    return matrix,contacts,active,labels,(a,b,g)


def _terminal_conductance(matrix,contacts,active,labels,edges,cancelled):
    """Dissipation quadratic forms avoid subtracting nearly equal potentials.

    Junction reference conductivity can span many decades. At a very conductive
    contact, direct sigma*(Vterminal-Vcell) loses the tiny resistor current to
    floating-point cancellation. The positive face-energy form computes the
    terminal conductance without that subtraction, with a local reference for
    every connected component. Kirchhoff symmetry and row sums are explicit.
    """
    names=[contact['object']['id'] for contact in contacts]
    conductance=np.zeros((len(names),len(names)))
    a,b,g=edges
    max_residual=0.;response_count=0;linear_checks=[]
    for label in np.unique(labels[active]):
        if cancelled():
            raise InterruptedError('Electrical terminal study cancelled')
        cells=np.flatnonzero(active&(labels==label));local=np.full(matrix.shape[0],-1,int)
        local[cells]=np.arange(len(cells))
        anchors=[];stencils={}
        for ci,contact in enumerate(contacts):
            ids=contact['ids'];coefficient=contact['coefficient']
            use=(coefficient>0)&(labels[ids]==label)
            boundary_ids=ids[use];boundary_coeff=coefficient[use]
            valid=(contact['others']>=0)&(contact['other_coefficient']>0)
            other=contact['others'][valid];extra=contact['other_coefficient'][valid]
            use_other=labels[other]==label
            boundary_ids=np.r_[boundary_ids,other[use_other]]
            boundary_coeff=np.r_[boundary_coeff,extra[use_other]]
            if len(boundary_ids):
                anchors.append(ci);stencils[ci]=(local[boundary_ids],boundary_coeff)
        if len(anchors)<2:
            continue
        reference=anchors[-1];variables=anchors[:-1]
        reduced=matrix[cells][:,cells]
        responses=[]
        for ci in variables:
            rhs=np.zeros(len(cells));ids,coef=stencils[ci]
            np.add.at(rhs,ids,coef)
            values,linear_check=solve_linear_system(reduced,rhs,cancelled=cancelled)
            linear_checks.append(linear_check)
            if not np.isfinite(values).all():
                raise RuntimeError('Ohmic unit-voltage solve produced a nonfinite connected potential')
            max_residual=max(max_residual,float(np.max(np.abs(reduced@values-rhs))))
            responses.append(values);response_count+=1
        values=np.asarray(responses)
        use=labels[a]==label
        differences=values[:,local[a[use]]]-values[:,local[b[use]]]
        block=(differences*g[use][None,:])@differences.T
        for ci in anchors:
            ids,coef=stencils[ci]
            differences=-values[:,ids]
            if ci in variables:
                differences[variables.index(ci)]+=1.
            block+=(differences*coef[None,:])@differences.T
        for ii,ci in enumerate(variables):
            for jj,cj in enumerate(variables):
                conductance[ci,cj]+=block[ii,jj]
            conductance[ci,reference]-=float(block[ii,:].sum())
            conductance[reference,ci]-=float(block[ii,:].sum())
        conductance[reference,reference]+=float(block.sum())
    return names,conductance,dict(unit_response_solves=response_count,max_unit_voltage_residual_A=max_residual,
        linear_solves=linear_checks,
        extraction='Positive conservative face-dissipation quadratic form, referenced independently within each connected conducting component')


def ohmic_iv(summary, cancelled=lambda:False, directory=None):
    """Solve conduction using frozen 0-bias carrier density and applied voltages."""
    from custom_electrical_solver import build_mesh
    cfg=summary.get('options',{})
    if cfg.get('model')!='custom_device' or 'device' not in cfg or 'material_library' not in cfg:
        raise ValueError('Ohmic I–V requires a saved custom-device electrostatic result')
    reference=next((row for row in summary.get('results',[]) if abs(float(row['bias_V']))<1e-12),None)
    if reference is None:
        raise ValueError('Ohmic I–V needs the saved zero sweep-bias carrier reference')
    mesh=build_mesh(cfg['device'],cfg['material_library'])
    reference_path=Path(reference['volume_npz'])
    if not reference_path.is_file() and directory is not None:
        reference_path=Path(directory)/reference_path.name
    with np.load(reference_path,allow_pickle=False) as data:
        sigma=_conductivity(mesh,data)
    matrix,contacts,active,labels,edges=_conductance_system(mesh,sigma)
    names,conductance,response_checks=_terminal_conductance(matrix,contacts,active,labels,edges,cancelled)
    swept=cfg['swept_contact_id'];rows=[];checks=[]
    for result in summary['results']:
        if cancelled():
            raise InterruptedError('Electrical terminal study cancelled')
        voltages=result['checks']['terminal_voltages_V']
        applied=np.array([float(voltages[name]) for name in names])
        if not np.isfinite(applied).all():
            raise ValueError('Saved terminal voltages must be finite')
        # Common-mode subtraction makes small voltage differences independent
        # of the arbitrary potential reference.
        current_values=conductance@(applied-applied[-1])
        currents={name:float(value) for name,value in zip(names,current_values)}
        balance=abs(sum(currents.values())); scale=max(sum(abs(v) for v in currents.values()),1e-30)
        if balance/scale>1e-6 and balance>1e-18:
            raise RuntimeError('Ohmic terminal-current conservation check failed')
        rows.append(dict(bias_V=float(result['bias_V']),terminal_voltage_V=float(voltages[swept]),
                         current_A=currents[swept],model=IV_MODEL))
        checks.append(dict(bias_V=float(result['bias_V']),terminal_currents_A=currents,
            current_balance_A=balance,relative_current_balance=balance/scale,
            power_W=float(sum((voltages[key]-applied[-1])*value for key,value in currents.items()))))
    rows.sort(key=lambda row:row['terminal_voltage_V'])
    return rows,dict(model=IV_MODEL,swept_contact_id=swept,
        sign_convention='Positive conventional current enters the device from the swept terminal',
        conductivity_model='sigma = explicit fixed conductivity override when supplied (including zero); otherwise q*(n_reference*mu_n + p_reference*mu_p), with reference carriers at zero sweep bias',
        reference_bias_V=0.,terminal_conductance_S=conductance.tolist(),terminal_order=names,
        response_checks=response_checks,connected_conducting_cells=int(active.sum()),
        zero_conductivity_cells=int(np.count_nonzero(sigma==0)),
        unanchored_conducting_cells=int(np.count_nonzero((sigma.ravel()>0)&~active)),checks=checks,
        warnings=['Ohmic conductivity estimate (not junction transport/leakage). The reference carrier distribution is frozen at zero sweep bias.',
                  'No carrier continuity, injection, recombination, tunnelling, diode transport or contact resistance is solved.',
                  'Bulk low-field mobility and material conductivity assumptions require calibration for this sample and operating field.',
                  'Exactly zero-conductivity regions are open circuits; isolated conductive regions have no defined potential and carry no terminal current.'])


def execute_studies(summary, cfg, directory, emit=lambda event:None, cancelled=lambda:False):
    """Save requested computed/measured curves and portable study provenance."""
    cfg=validate_studies(cfg)
    if cancelled():
        raise InterruptedError('Electrical terminal study cancelled')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    info=dict(schema_version=1,options=cfg,studies={},measured={})
    if cfg['cv_enabled']:
        emit(dict(phase='cv',progress=.9,message='Differentiating saved swept-electrode charge for C–V'))
        rows,metadata=terminal_cv(summary)
        path=directory/'electrical_cv.csv'
        _write_rows(path,rows,['bias_V','terminal_voltage_V','terminal_charge_C','capacitance_F'])
        info['cv_csv']=str(path);info['studies']['cv']=metadata
    if cfg['iv_enabled']:
        transport=summary.get('options',{}).get('transport',{})
        mode=transport.get('mode','disabled')
        emit(dict(phase='iv',progress=.94,message=IV_MODEL if mode=='disabled' else 'Saving physical transport currents'))
        if mode=='dielectric_leakage':
            cached=summary.get('dielectric_leakage')
            if cached:
                rows,metadata=cached['rows'],cached['metadata']
            else:
                from electrical_transport import dielectric_leakage_iv
                rows,metadata=dielectric_leakage_iv(summary,transport,cancelled)
        elif mode=='semiconductor_dd':
            rows=[]
            swept=summary['options']['swept_contact_id']
            for result in summary['results']:
                if cancelled():raise InterruptedError('Electrical terminal study cancelled')
                check=result['checks']
                rows.append(dict(bias_V=result['bias_V'],terminal_voltage_V=check['terminal_voltages_V'][swept],
                    current_A=check['terminal_current_A'][swept],model='Self-consistent Poisson and electron/hole current continuity'))
            metadata=dict(model='Self-consistent semiconductor drift diffusion',
                transport=transport,swept_contact_id=swept,
                sign_convention='Positive conventional current enters the device from the swept terminal',
                checks=[r['checks'] for r in summary['results']],
                warnings=summary.get('limitations',[]))
        else:
            rows,metadata=ohmic_iv(summary,cancelled=cancelled,directory=directory)
        path=directory/'electrical_iv.csv'
        columns=list(dict.fromkeys(key for row in rows for key in row))
        _write_rows(path,rows,columns)
        info['iv_csv']=str(path);info['studies']['iv']=metadata
    for kind in ('iv','cv'):
        if cancelled():
            raise InterruptedError('Electrical terminal study cancelled')
        path=cfg['measured_'+kind+'_path']
        if path:
            rows=read_measured_csv(path,kind)
            output=directory/('measured_'+kind+'.csv')
            column='current_A' if kind=='iv' else 'capacitance_F'
            _write_rows(output,rows,['bias_V',column])
            info['measured'][kind]=dict(csv=str(output),source_path=str(Path(path).resolve()),samples=len(rows),model='User supplied measured curve')
    path=directory/'electrical_study_summary.json'
    info['summary_json']=str(path)
    path.write_text(json.dumps(info,indent=2,allow_nan=False),encoding='utf-8')
    return info
