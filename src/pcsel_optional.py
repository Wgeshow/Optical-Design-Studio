"""Independent outgoing RCWA resonance poles on the editable PCSEL stack."""
import numpy as np
import json
from scipy.optimize import least_squares


def rcwa_poles(cfg,directory,emit,cancelled):
    from backend import load_runtime
    from model import DEFAULT_PERFORMANCE
    from pcsel_research import _csv
    runtime=load_runtime(dict(DEFAULT_PERFORMANCE,threads=1,mode='CPU only'))
    a=cfg['lattice_nm'];solver=runtime.New(Lattice=((1.,0.),(0.,1.)),NumBasis=cfg['basis'])
    for name,index in [('top',cfg['top_index']),('bottom',cfg['bottom_index']),('inclusion',cfg['inclusion_index'])]:
        solver.SetMaterial(Name=name,Epsilon=index*index)
    solver.AddLayer(Name='top',Thickness=0.,S4_Material='top')
    for i,layer in enumerate(cfg['layers']):
        name='L'+str(i);material='M'+str(i);solver.SetMaterial(Name=material,Epsilon=layer['index']**2)
        solver.AddLayer(Name=name,Thickness=layer['thickness_nm']/a,S4_Material=material)
        if layer['patterned']:
            for shape in cfg['shapes']:
                if shape['shape']=='circle':
                    solver.SetRegionCircle(S4_Layer=name,S4_Material='inclusion',Center=tuple(shape['center']),Radius=shape['radius'])
                else:
                    solver.SetRegionPolygon(S4_Layer=name,S4_Material='inclusion',Center=(0.,0.),Angle=0.,Vertices=tuple(map(tuple,shape['vertices'])))
    solver.AddLayer(Name='bottom',Thickness=0.,S4_Material='bottom')
    excitation=cfg['pole_excitation']
    solver.SetExcitationPlanewave(IncidenceAngles=(0.,0.),sAmplitude=complex(*excitation[0]),pAmplitude=complex(*excitation[1]),Order=0)
    probe=cfg['probe'];rows=[];failures=[];field_records=[]
    artifacts=['rcwa_field_provenance.json','rcwa_progress.json']
    basis_actual=len(solver.GetBasisSet());active_seed=None
    def checkpoint(status,error=None):
        # Commit each root before its optional fields and before the next seed.
        # Failed/cancelled jobs retain evidence without becoming completed jobs.
        if rows or failures:
            _csv(directory/'rcwa_poles.csv',rows+failures)
            if 'rcwa_poles.csv' not in artifacts:artifacts.append('rcwa_poles.csv')
        (directory/'rcwa_field_provenance.json').write_text(json.dumps(field_records,indent=2,allow_nan=False),encoding='utf-8')
        if field_records:
            radiation=[{key:row.get(key) for key in ('seed','frequency','imaginary','up_fraction','down_fraction','fraction_detuning_change','residue_detuning','status','error')} for row in field_records]
            _csv(directory/'rcwa_radiation.csv',radiation)
            if 'rcwa_radiation.csv' not in artifacts:artifacts.append('rcwa_radiation.csv')
        progress=dict(status=status,engine='pcsel',model='rcwa_poles',
            seed_count=len(cfg['pole_seeds']),processed_pole_seed_count=len(rows)+len(failures),
            active_seed_index=active_seed,poles=rows,failed_poles=failures,pole_radiation=field_records,
            basis_requested=cfg['basis'],basis_actual=basis_actual,
            convergence_established=False,artifacts=artifacts)
        if error is not None:progress['error']=error
        (directory/'rcwa_progress.json').write_text(json.dumps(progress,indent=2,allow_nan=False),encoding='utf-8')
    checkpoint('running')
    def response(frequency):
        if cancelled():raise InterruptedError('RCWA pole calculation cancelled')
        solver.SetFrequency(complex(frequency))
        field,_=solver.GetFields(probe[0],probe[1],probe[2]/a)
        return np.asarray(field)
    try:
        for index,seed in enumerate(cfg['pole_seeds']):
            active_seed=index
            real,imag=seed;field=response(real);channel=int(np.argmax(abs(field[:2])));scale=abs(field[channel])
            if not np.isfinite(scale) or scale<1e-20:raise ValueError('The selected probe has no resolvable driven field; move the probe.')
            def residual(value):
                field=response(complex(*value))[channel]
                if not np.isfinite(field) or abs(field)<1e-300:return [1e100,1e100]
                value=scale/field
                return [float(value.real),float(value.imag)]
            bounds=cfg['pole_bounds']
            result=least_squares(residual,[real,imag],bounds=([bounds[0][0],bounds[1][0]],[bounds[0][1],bounds[1][1]]),
                x_scale=[1.,max(abs(imag),1e-6)],ftol=1e-12,xtol=1e-12,gtol=1e-12,max_nfev=300)
            pole=complex(*result.x);error=float(np.linalg.norm(residual(result.x)))
            accepted=bool(result.success and pole.real>0 and pole.imag<0 and error<1e-5)
            record=dict(seed_real=real,seed_imag=imag,frequency=float(pole.real),imaginary=float(pole.imag),
                Q=float(pole.real/(-2*pole.imag)) if pole.imag<0 else None,residual=error,accepted=accepted,calls=int(result.nfev))
            (rows if accepted else failures).append(record)
            checkpoint('running')
            emit(dict(kind='log',message=f'RCWA resonance seed {index+1}/{len(cfg["pole_seeds"])}: '+('accepted' if accepted else 'unresolved')))
            if accepted:
                try:
                    detuning=min(cfg['pole_detuning'],abs(pole.imag)*.001)
                    solver.SetFrequency(pole+1j*detuning)
                    count=cfg['pole_field_grid'];electric=[];magnetic=[]
                    coordinates=np.arange(count)/count-.5
                    for depth in cfg['pole_field_z_nm']:
                        if cancelled():raise InterruptedError('RCWA field extraction cancelled')
                        # Scalar coordinates preserve the canonical S4 E/H convention;
                        # some native grid builds differ in origin and the Hz sign.
                        E=np.empty((count,count,3),complex);H=np.empty_like(E)
                        for xi,x in enumerate(coordinates):
                            if cancelled():raise InterruptedError('RCWA field extraction cancelled')
                            for yi,y in enumerate(coordinates):
                                E[xi,yi],H[xi,yi]=solver.GetFields(float(x),float(y),depth/a)
                        electric.append(E*detuning);magnetic.append(H*detuning)
                    # Residue scaling is arbitrary. Port fractions use outgoing flux,
                    # with a second detuning checking contamination from the drive.
                    _,reflected=solver.GetPowerFlux('top',0);transmitted,_=solver.GetPowerFlux('bottom',0)
                    up,down=-reflected.real,transmitted.real
                    fraction=float(up/(up+down)) if up>=0 and down>=0 and up+down>0 else None
                    solver.SetFrequency(pole+2j*detuning)
                    _,reflected2=solver.GetPowerFlux('top',0);transmitted2,_=solver.GetPowerFlux('bottom',0)
                    up2,down2=-reflected2.real,transmitted2.real
                    second=float(up2/(up2+down2)) if up2>=0 and down2>=0 and up2+down2>0 else None
                    E=np.asarray(electric);H=np.asarray(magnetic)
                    meta=dict(seed=index,frequency=record['frequency'],imaginary=record['imaginary'],
                        up_fraction=fraction,down_fraction=None if fraction is None else 1-fraction,
                        fraction_detuning_change=None if fraction is None or second is None else abs(fraction-second),
                        residue_detuning=detuning,field_normalization='Driven fields multiplied by detuning; arbitrary pole-residue amplitude',
                        status='complete' if fraction is not None and second is not None else 'unresolved_flux')
                    axes=[dict(name='z',coordinate='z_nm',unit='nm'),dict(name='x',coordinate='x_over_a',unit='a'),
                        dict(name='y',coordinate='y_over_a',unit='a'),dict(name='Cartesian component (x,y,z)')]
                    name=f'rcwa_fields_{index:04d}.npz'
                    np.savez_compressed(directory/name,E_residue=E,H_residue=H,z_nm=np.asarray(cfg['pole_field_z_nm']),
                        x_over_a=coordinates,y_over_a=coordinates,
                        array_axes=json.dumps({key:dict(axes=axes,unit='arbitrary residue amplitude') for key in ('E_residue','H_residue')}))
                    artifacts.append(name)
                    field_records.append(meta)
                except (ValueError,RuntimeError) as exc:
                    field_records.append(dict(seed=index,status='failed',error=str(exc)))
            checkpoint('running')
    except Exception as exc:
        try:
            checkpoint('cancelled' if isinstance(exc,InterruptedError) else 'failed',str(exc))
        except (OSError,ValueError):
            # Preserve the original runtime/cancellation error if saving fails.
            pass
        raise
    status='partial' if failures or any(row['status']!='complete' for row in field_records) else 'complete'
    checkpoint(status)
    return dict(status=status,poles=rows,failed_poles=failures,
        basis_requested=cfg['basis'],basis_actual=basis_actual,
        approximation='Full-vector passive periodic RCWA pole search; prescribed real nondispersive indices.',
        pole_radiation=field_records,convergence_established=False,artifacts=artifacts,
        search_limitations='Driven pole search can miss modes orthogonal to the chosen probe/excitation. Repeated seeds may identify the same mode; inspect branches and refine basis/detuning independently.')
