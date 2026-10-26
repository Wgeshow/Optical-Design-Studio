"""Portable 3D semiconductor electrostatics for Optical Design Studio.

DEVSIM is optional and imported only when solving. The completed contacts-only
template is retained; explicit 40 nm ITO is an experimental material branch.
This computes electrostatic carrier reservoirs, not semiconductor current.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

DEFAULT_OPTIONS = dict(model='explicit_ito',biases_V=[0.,-2.],mesh_level=0,
    ito_thickness_nm=40.,ito_density_cm3=8e20,sheet_resistance_ohm_square=45.,
    geometry='contacts_only_100um',current_offset='subtract_zero',temperature_K=300.)
LAYERS = [('p+ GaAs','GaAs',0.,50.),('p GaAs','GaAs',50.,200.),
          ('Al0.5Ga0.5As','AlGaAs',200.,220.),('n GaAs','GaAs',220.,370.),
          ('n+ GaAs','GaAs',370.,420.),('ITO','ITO',420.,460.)]
GEOMETRY = dict(center_square_um=[100,100],p_ring_inner_um=[100.01,100.01],
    p_ring_outer_um=[120,120],external_gap_nm=5,n_pad_outer_um=[780,770],
    n_pad_opening_width_um=156,n_pad_opening_top_y_um=-75,ITO_domain_um=[820,820],
    hole_radius_nm=46,hole_period_nm=444,net_doping_cm3=[-1e20,-3e19,0,8e18,1e19])
LIMITATIONS = [
    'Prescribed electron/hole quasi-Fermi reservoirs; carrier continuity, leakage, tunnelling and recombination are not solved.',
    'The exact contacts-only preset uses an ideal p reservoir connection; no SiO2 or interconnect resistance.',
    'Holes in the electrical mesh are homogenized; local hole-edge and sharp metal-corner field peaks are not validated.',
    'No calibrated interface traps, contact barriers, surface charge or electrical band-gap narrowing.',
    '300 K, fully activated nominal dopants and parabolic-band Fermi-Dirac populations are assumed.',
    'Explicit ITO uses assumed affinity-rule alignment, electron density, effective mass and DC optical damping; it is experimental.',
    'ITO sheet current is a prescribed load; zero current is imposed unless measurements are supplied. Offset subtraction is a sensitivity assumption.',
]
PROVENANCE = dict(source_study='Semiconductor electrical study, 2026-10-12',
    geometry_revision='contacts_only_revision',explicit_ito_revision='ito40_explicit',
    prior_contacts_only_validation=dict(biases_V=[0,-2],mesh_levels=[0,1],
        center_field_mesh_change_percent={'0':.203649046,'-2':.061481975}),
    explicit_ito_validation=dict(prior_completed_mesh_levels=[0],mesh_convergence_established=False),
    electrical_material_sources=['https://www.ioffe.ru/SVA/NSM/Semicond/GaAs/bandstr.html',
        'https://www.ioffe.ru/SVA/NSM/Semicond/AlGaAs/bandstr.html'],
    ito_parameter_source='https://photonics.oregonstate.edu/sites/photonics.oregonstate.edu/files/ome-8-9-2850.pdf',
    method='Structured conservative finite-volume nonlinear Poisson with Fermi-Dirac charge',
    units='SI mesh and fields; optical profiles use nm, cm^-3 and V/m',
    domain_symmetry='Half device x>=0, mirror scalar/Ey/Ez evenly and Ex oddly')
_LOCK = threading.Lock()
_DLL_HANDLES = []


def _number(value, name, low, high):
    if isinstance(value,bool):raise ValueError(f'{name} must be a finite number')
    try:value=float(value)
    except (TypeError,ValueError):raise ValueError(f'{name} must be a finite number') from None
    if not math.isfinite(value) or not low<=value<=high:
        raise ValueError(f'{name} must be between {low:g} and {high:g}')
    return value


def validate_options(options=None):
    """Return JSON-safe canonical configuration and reject unmodelled inputs."""
    if options is None:options={}
    if not isinstance(options,dict):raise ValueError('Electrical options must be a dictionary')
    supported=set(DEFAULT_OPTIONS)|{'measured_current','geometry_parameters','net_doping_cm3'}
    unknown=set(options)-supported
    if unknown:raise ValueError('Unsupported electrical options: '+', '.join(sorted(unknown)))
    cfg=dict(DEFAULT_OPTIONS);cfg['biases_V']=list(DEFAULT_OPTIONS['biases_V']);cfg.update(options)
    if cfg['model'] not in ('contacts_only_sheet','explicit_ito'):
        raise ValueError('model must be contacts_only_sheet or explicit_ito')
    if cfg['geometry']!='contacts_only_100um':
        raise ValueError('Only the contacts_only_100um geometry template is implemented')
    if 'geometry_parameters' in cfg:
        parameters=cfg.pop('geometry_parameters')
        if not isinstance(parameters,dict) or any(k not in GEOMETRY or v!=GEOMETRY[k] for k,v in parameters.items()):
            raise ValueError('Custom geometry is not implemented; retain the validated contacts-only preset')
    if 'net_doping_cm3' in cfg:
        if cfg.pop('net_doping_cm3')!=GEOMETRY['net_doping_cm3']:
            raise ValueError('Custom doping is not implemented; retain the validated five-layer stack')
    if isinstance(cfg['mesh_level'],bool) or cfg['mesh_level'] not in (0,1):
        raise ValueError('mesh_level must be 0 (standard) or 1 (refined)')
    cfg['mesh_level']=int(cfg['mesh_level'])
    if not isinstance(cfg['biases_V'],(list,tuple)) or not 1<=len(cfg['biases_V'])<=21:
        raise ValueError('biases_V must contain 1 to 21 equilibrium/reverse biases')
    cfg['biases_V']=sorted(set([0.]+[_number(v,'bias',-4,0) for v in cfg['biases_V']]),reverse=True)
    cfg['ito_thickness_nm']=_number(cfg['ito_thickness_nm'],'ITO thickness',40,40)
    cfg['temperature_K']=_number(cfg['temperature_K'],'temperature',300,300)
    cfg['ito_density_cm3']=_number(cfg['ito_density_cm3'],'ITO density',1e20,1e21)
    cfg['sheet_resistance_ohm_square']=_number(cfg['sheet_resistance_ohm_square'],'sheet resistance',30,60)
    if cfg['current_offset'] not in ('subtract_zero','as_plotted'):
        raise ValueError('current_offset must be subtract_zero or as_plotted')
    if 'measured_current' in cfg:
        data=cfg['measured_current']
        if not isinstance(data,(list,tuple)) or len(data)<2:
            raise ValueError('measured_current needs at least two {bias_V,current_A} samples')
        rows=[]
        for row in data:
            if not isinstance(row,dict) or set(row)!={'bias_V','current_A'}:
                raise ValueError('Each measured-current sample needs bias_V and current_A')
            rows.append(dict(bias_V=_number(row['bias_V'],'measured bias',-100,100),
                current_A=_number(row['current_A'],'measured current',-1,1)))
        rows.sort(key=lambda r:r['bias_V'])
        if len({r['bias_V'] for r in rows})!=len(rows):raise ValueError('Measured biases must be unique')
        if rows[0]['bias_V']>min(cfg['biases_V']) or rows[-1]['bias_V']<0:
            raise ValueError('Measured-current samples must cover every requested bias and 0 V')
        cfg['measured_current']=rows
    return cfg


def _load_core():
    """Discover native math libraries without workstation paths or PATH edits."""
    if importlib.util.find_spec('devsim') is None:
        raise RuntimeError('Electrical 3D simulation requires the optional DEVSIM package. Install devsim in this application Python environment, then restart Optical Design Studio.')
    if os.name=='nt':
        directories=[]
        if getattr(sys,'_MEIPASS',None):directories.append(Path(sys._MEIPASS))
        directories += [Path(sys.executable).parent,Path(sys.executable).parent/'_internal',
                        Path(sys.prefix)/'Library'/'bin',Path(sys.base_prefix)/'Library'/'bin']
        directories += [Path(p) for p in os.environ.get('PATH','').split(os.pathsep) if p]
        configured=os.environ.get('DEVSIM_MATH_LIBS')
        if configured:directories.insert(0,Path(configured).parent)
        seen=set()
        for directory in directories:
            if directory in seen:continue
            try:
                if not directory.is_dir():continue
            except OSError:
                continue
            seen.add(directory)
            if not configured:
                for name in ('mkl_rt.2.dll','mkl_rt.dll'):
                    native=directory/name
                    if native.is_file():
                        os.environ['DEVSIM_MATH_LIBS']=str(native);configured=str(native);break
            if any((directory/name).is_file() for name in ('mkl_rt.2.dll','mkl_rt.dll')) and hasattr(os,'add_dll_directory'):
                _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
    try:return importlib.import_module('electrical_physics.devsim_core')
    except (ImportError,OSError,RuntimeError) as exc:
        raise RuntimeError('DEVSIM could not load its native solver/math libraries. Install a compatible DEVSIM runtime or set DEVSIM_MATH_LIBS to your math library. '+str(exc)) from exc


def _profile(data,par,explicit):
    import numpy as np
    from scipy.integrate import trapezoid
    def widths(axis,lo,hi):
        faces=np.r_[axis[0],(axis[:-1]+axis[1:])/2,axis[-1]]
        return np.maximum(0,np.minimum(faces[1:],hi)-np.maximum(faces[:-1],lo))
    w=widths(data['x'],0,50e-6)[:,None]*widths(data['y'],-50e-6,50e-6)[None,:]
    w/=w.sum()
    fraction=data['ga_fraction']+data['al_fraction']
    ne=data['electrons_cm3']
    if explicit:ne=ne-data['ito_fraction']*data['ito_electrons_cm3']
    carriers=[np.divide(a,fraction,out=np.zeros_like(a),where=fraction>0)
              for a in (ne,data['holes_cm3'])]
    ez=data['field_V_m'][:,:,:,2]
    values=[np.sum(w[:,:,None]*a,axis=(0,1)) for a in carriers+[ez,ez**2]]
    z=data['z']*1e9
    sem=(z>=0)&(z<420)
    zs=np.r_[z[sem],420.]
    semiconductor=[np.r_[a[sem],a[sem][-1]] for a in values]
    mask=(z>420)&(z<=460+1e-7)
    zi=z[mask]
    ito=(np.sum(w[:,:,None]*data['ito_electrons_cm3'],axis=(0,1))[mask]
         if explicit else np.full(len(zi),par['density_cm3']))
    zout=np.r_[zs,zi]
    arrays=[np.r_[a,np.zeros(len(zi))] for a in semiconductor[:2]]
    arrays += [np.r_[semiconductor[index],values[index][mask]] for index in (2,3)]
    ito_out=np.r_[np.zeros(len(zs)),ito]
    material=np.where(zout<=420,np.where((zout>=200)&(zout<220),'AlGaAs','GaAs'),'ITO')
    names=np.select([zout<50,zout<200,zout<220,zout<370,zout<=420],
        ['p+ GaAs','p GaAs','Al0.5Ga0.5As','n GaAs','n+ GaAs'],default='ITO')
    profile=dict(z_nm=zout,electrons_cm3=arrays[0],holes_cm3=arrays[1],
        Ez_V_m=arrays[2],Ez_squared_V2_m2=arrays[3],ito_electrons_cm3=ito_out,
        material=material,layer_name=names)
    # Retain the same fine electrical/optical boundaries as the source study.
    edges=np.array([0,46,48,49,50,51,52,54,58,180,190,194,196,197,198,199,
        200,220,221,222,224,226,228,230,233,237,244,260,350,360,366,370,
        374,380,390,420,421,422,424,428,435,445,455,460],float)
    records=[]
    for a,c in zip(edges[:-1],edges[1:]):
        name,mat,_,_=next(layer for layer in LAYERS if layer[2]<=a<layer[3])
        query=np.linspace(a,c,max(3,int(math.ceil((c-a)/.1))+1))
        if mat=='ITO':
            densities=[0.,0.]+[float(trapezoid(np.interp(query,zi,values[index][mask]),query)/(c-a))
                                 for index in (2,3)]
            concentration=float(trapezoid(np.interp(query,zi,ito),query)/(c-a))
        else:
            densities=[float(trapezoid(np.interp(query,zs,arr),query)/(c-a)) for arr in semiconductor]
            concentration=0.
        records.append(dict(name=name,material=mat,depth_start_nm=float(a),depth_end_nm=float(c),
            thickness_nm=float(c-a),electrons_cm3=densities[0],holes_cm3=densities[1],
            field_V_m=densities[2],field_squared_V2_m2=densities[3],ito_electrons_cm3=concentration))
    return profile,records


def solve(options,directory,emit=lambda event:None,cancelled=lambda:False):
    """Solve the saved template, write portable NPZ/CSV/JSON results, return summary."""
    cfg=validate_options(options)
    if cancelled():raise InterruptedError('Electrical simulation cancelled')
    with _LOCK:
        return _solve(cfg,Path(directory).resolve(),emit,cancelled)


def _solve(cfg,directory,emit,cancelled):
    import numpy as np
    from scipy.interpolate import PchipInterpolator,RegularGridInterpolator
    from electrical_physics import device
    explicit=cfg['model']=='explicit_ito'
    def progress(phase,amount,message):
        if cancelled():raise InterruptedError('Electrical simulation cancelled')
        emit(dict(phase=phase,progress=float(amount),message=message))
    progress('initializing',0.,'Loading the optional semiconductor solver')
    core=_load_core();ds=core.ds
    # DEVSIM maintains process-global mesh names. Each worker serializes solves
    # and removes its temporary device in the finally block.
    directory.mkdir(parents=True,exist_ok=True)
    par=device.ito_parameters(cfg['ito_density_cm3'],cfg['sheet_resistance_ohm_square'],cfg['ito_thickness_nm'])
    summary=dict(schema_version=1,options=cfg,model=cfg['model'],experimental=explicit,
        geometry=GEOMETRY,ito_parameters=par,limitations=LIMITATIONS,provenance=PROVENANCE,
        results=[],devsim_version=getattr(ds,'__version__','unknown'))
    started=time.monotonic()
    try:
        core.mesh_axes=lambda kind,level:device.axes(core,level,explicit)
        core.contact_masks=lambda kind,x,y,z:device.masks(x,y,z,explicit)
        core.materials=lambda kind,m:device.materials(core,m,explicit,par)
        progress('mesh',.05,'Building the half-device mesh and terminal contacts')
        m=core.build_mesh('full',cfg['mesh_level'])
        core.materials('full',m);core.setup('full',m)
        x,y,z=m['coords'].T
        if explicit:
            for key,val in [('NcITO',par['Nc_m3']),('EcITO',par['Ec_flat_eV'])]:
                ds.set_parameter(device=core.D,region=core.R,name=key,value=val)
            core.fd_models('NI','(Potential-Vn-EcITO)/KT')
            core.nm('ITOE','NcITO*NI')
            core.nm('Electrons','GaFraction*NcG*NG+AlFraction*NcA*NA+ITOFraction*NcITO*NI')
            core.nm('Charge','-q*(Holes-Electrons+NetDoping)')
            core.nm('Charge:Potential','q/KT*(GaFraction*(NvG*PGD+NcG*NGD)+AlFraction*(NvA*PAD+NcA*NAD)+ITOFraction*NcITO*NID)')
            ds.contact_node_model(device=core.D,contact='n_contact',name='n_contact_bc',
                equation=f"Potential-({par['neutral_potential_V']:.17g}+Vn)")
            seed=device.planar_ito(par,cancelled=cancelled)
            initial=np.interp(z,seed['z_m'],seed['potential_V'])
            initial[(x>50e-6)|(abs(y)>50e-6)]=par['neutral_potential_V']
            initial[m['p']]=core.ref.contacts(0)[0];initial[m['n']]=par['neutral_potential_V']
            summary['planar_seed_checks']=dict(residual=seed['residual'],gauss_C_m2=seed['gauss_C_m2'])
            summary['current_load_used']=False
        else:
            progress('sheet',.1,'Solving the prescribed-current ITO sheet')
            sh,checks=device.sheet(1. if cfg['mesh_level'] else 2.)
            np.savez_compressed(directory/'ito_sheet.npz',**sh)
            summary['sheet_checks']=checks
            transfer=RegularGridInterpolator((sh['x'],sh['y']),sh['transfer'])(m['coords'][:,:2])
            core.nodeset('VnLocal',np.zeros(len(x)))
            core.nm('NGEta','(Potential-VnLocal)/KT');core.nm('NAEta','(Potential-VnLocal-EcA)/KT')
            n0=core.ref.contacts(0)[1]
            ds.contact_node_model(device=core.D,contact='n_contact',name='n_contact_bc',equation=f'Potential-({n0:.17g}+VnLocal)')
            if cfg.get('measured_current'):
                iv=np.array([[r['bias_V'],r['current_A']] for r in cfg['measured_current']])
                summary['current_load_source']='User supplied measured_current samples'
            else:
                iv=np.array([[-4.,0.],[0.,0.]])
                summary['current_load_source']='Zero imposed current; no measured-current samples supplied'
            ifun=PchipInterpolator(iv[:,0],iv[:,1],extrapolate=False)
            offset=float(ifun(0)) if cfg['current_offset']=='subtract_zero' else 0.
            seed=core.ref.solve(0,.2);initial=np.interp(z,seed['z_m'],seed['potential_V'])
            initial[(x>50e-6)|(abs(y)>50e-6)]=n0
            initial[m['p']]=core.ref.contacts(0)[0];initial[m['n']]=n0
            summary['current_load_used']=True
        ds.set_node_values(device=core.D,region=core.R,name='Potential',values=initial.tolist())
        # Continuation prevents large requested reverse steps from breaking Newton.
        requested=cfg['biases_V'];lowest=min(requested)
        biases=sorted(set(requested+[float(v) for v in np.arange(0,lowest-.001,-.25)]),reverse=True)
        for index,bias in enumerate(biases):
            progress('solve',.15+.75*index/max(1,len(biases)),f'Solving {bias:g} V')
            ds.set_parameter(device=core.D,region=core.R,name='Vp',value=bias)
            current=0.
            if not explicit:
                current=float(ifun(bias))-offset
                ds.set_node_values(device=core.D,region=core.R,name='VnLocal',
                    values=(transfer*cfg['sheet_resistance_ohm_square']*current).tolist())
            ds.solve(type='dc',solver_type='direct',absolute_error=1e-10,relative_error=1e-10,maximum_iterations=140)
            if cancelled():raise InterruptedError('Electrical simulation cancelled')
            if bias not in requested:continue
            checks=core.capture('full',cfg['mesh_level'],bias,m,directory)
            stem=f'full_L{cfg["mesh_level"]}_{bias:g}V'
            volume=directory/(stem+'.npz')
            with np.load(volume,allow_pickle=False) as loaded:data={key:loaded[key] for key in loaded.files}
            if explicit:
                order=np.ravel_multi_index(m['idx'].T,m['shape'])
                def grid(a):
                    vals=np.empty(len(a));vals[order]=a;return vals.reshape(m['shape'])
                data['ito_fraction']=grid(m['ito'])
                data['ito_electrons_cm3']=grid(np.asarray(ds.get_node_model_values(device=core.D,region=core.R,name='ITOE')))*1e-6
            else:
                sheet_grid=RegularGridInterpolator((sh['x'],sh['y']),sh['transfer'])(
                    np.stack(np.meshgrid(data['x'],data['y'],indexing='ij'),axis=-1))
                sheet_grid*=cfg['sheet_resistance_ohm_square']*current
                data['ITO_sheet_voltage_V']=sheet_grid
                field=np.stack([-a for a in np.gradient(data['potential'],data['x'],data['y'],data['z'],edge_order=2)],axis=-1)
                ex,ey=[-a for a in np.gradient(sheet_grid,data['x'],data['y'],edge_order=2)]
                ito=data['ito']
                field[ito,0]=np.broadcast_to(ex[:,:,None],ito.shape)[ito]
                field[ito,1]=np.broadcast_to(ey[:,:,None],ito.shape)[ito];field[ito,2]=0
                field[(data['p_contact']>0)|((data['n_contact']>0)&~ito)]=0
                data['field_V_m']=field
                checks['imposed_total_current_A']=current
            np.savez_compressed(volume,**data)
            scale=sum(abs(checks[k]) for k in ('p_C_half','n_C_half','total_charge_C_half'))
            checks['relative_gauss_balance']=checks['gauss_balance_error_C_half']/max(scale,1e-30)
            if checks['relative_gauss_balance']>1e-7 or not np.isfinite(data['field_V_m']).all():
                raise RuntimeError('Independent electrical Gauss/finite-field check failed')
            checks['semiconductor_current_predicted']=False
            checks['model_revision']=cfg['model']
            (directory/(stem+'.json')).write_text(json.dumps(checks,indent=2),encoding='utf-8')
            profile,layers=_profile(data,par,explicit)
            profile_path=directory/f'profile_{bias:g}V.npz'
            csv_path=directory/f'profile_{bias:g}V.csv'
            layers_path=directory/f'layers_{bias:g}V.json'
            np.savez_compressed(profile_path,**profile,bias_V=bias)
            columns=('z_nm','electrons_cm3','holes_cm3','Ez_V_m','Ez_squared_V2_m2','ito_electrons_cm3')
            np.savetxt(csv_path,np.column_stack([profile[k] for k in columns]),delimiter=',',header=','.join(columns),comments='')
            layers_path.write_text(json.dumps(layers,indent=2),encoding='utf-8')
            summary['results'].append(dict(bias_V=float(bias),volume_npz=str(volume),profile_npz=str(profile_path),
                profile_csv=str(csv_path),layers_json=str(layers_path),checks=checks))
        summary['elapsed_s']=time.monotonic()-started
        summary_path=directory/'electrical_summary.json'
        summary['summary_json']=str(summary_path)
        summary_path.write_text(json.dumps(summary,indent=2),encoding='utf-8')
        progress('complete',1.,'Electrical profiles and volume fields saved')
        return summary
    finally:
        try:ds.delete_device(device=core.D)
        except Exception:pass
        try:ds.delete_mesh(mesh='grid')
        except Exception:pass
