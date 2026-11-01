"""Opt-in, bounded CUDA wavelength batches using S4's exact Fourier operators.

Select with performance.solver_backend='eigenfree-gpu'. CuPy with a compatible
CUDA runtime is an optional dependency; the normal CPU installation needs none.
"""
import math
import time


class FieldView:
    """Read-only complete-field view of one wavelength in a resident batch."""
    def __init__(self, solution, index, payload):
        self.solution, self.index, self.payload = solution, index, payload

    def GetBasisSet(self):
        return self.payload['G']

    def GetReciprocalLattice(self):
        return self.payload['reciprocal']

    def GetAmplitudes(self, layer, depth=0.):
        """Native H-amplitude convention for exterior specular phase queries."""
        import numpy as np
        layers = self.payload['layers']
        if layer == layers[0]['name']:
            first, q = 0, self.solution.qleft
        elif layer == layers[-1]['name']:
            first, q = 2, self.solution.qright
        else:
            raise NotImplementedError('FieldView amplitudes are available at exterior ports')
        cache = getattr(self.solution, '_phase_port_cache', None)
        if cache is None:
            cache = self.solution._phase_port_cache = (self.solution.port_amplitudes(),
                self.solution._host(self.solution.qleft), self.solution._host(self.solution.qright))
        values = cache[0][self.index]
        phase = np.exp(1j*cache[1 if first == 0 else 2][self.index]*depth)
        return tuple(values[:, first]*phase), tuple(values[:, first+1]/phase)

    def _layer(self, z):
        index, origin = 0, 0.
        layers = self.payload['layers']
        while index+1 < len(layers) and z > origin+layers[index]['thickness']:
            origin += layers[index]['thickness']
            index += 1
        return index, z-origin

    def _coefficients(self, z):
        from collections import OrderedDict
        key = self._layer(float(z))
        cache = getattr(self.solution,'_field_view_cache',None)
        if cache is None:
            cache = self.solution._field_view_cache = OrderedDict()
        if key not in cache:
            value = self.solution.coefficients(*key)
            value.flags.writeable = False
            while cache and sum(v.nbytes for v in cache.values())+value.nbytes > 128*1024**2:
                cache.popitem(last=False)
            cache[key] = value
        cache.move_to_end(key)
        return cache[key][self.index]

    def GetFieldCoefficientsMany(self, depths):
        import numpy as np
        values = [self._coefficients(z) for z in depths]
        return np.asarray(values,dtype=np.complex128).tobytes()

    def GetFields(self, x, y, z):
        import numpy as np
        phase = np.exp(1j*(np.asarray(self.payload['kx'])*x+np.asarray(self.payload['ky'])*y))
        value = phase@self._coefficients(z)
        return tuple(value[:3]), tuple(value[3:])

    def GetFieldsOnGrid(self, z, shape, format='Array'):
        import numpy as np
        nx,ny = shape
        a,b = np.asarray(self.payload['lattice'])
        # S4's Fourier grid starts at the lattice origin.
        xy = (np.arange(nx)[:,None,None]/nx*a+np.arange(ny)[None,:,None]/ny*b).reshape(-1,2)
        phase = np.exp(1j*(xy[:,0,None]*np.asarray(self.payload['kx'])+xy[:,1,None]*np.asarray(self.payload['ky'])))
        value = (phase@self._coefficients(z)).reshape(nx,ny,6)
        if format != 'Array':
            raise ValueError('FieldView supports Array grid output')
        return value[...,:3], value[...,3:]


def execute(model, p, emit, cancelled, checkpoint=None, result_store=None,
            field_settings=None, field_directory=None):
    from backend import Cancelled, build_simulation, load_runtime
    from model import epsilon, performance
    from s4_eigenfree_gpu import solve_batch
    import os
    import numpy as np
    from gpu_solver_runtime import load_cupy
    cp = load_cupy()
    points = model['points']
    p = performance(dict(p,mode='GPU-assisted (one worker)',workers=1),len(points),os.cpu_count() or 1)
    batch_size = int(p.get('eigenfree_batch_size',p['chunk_size']))
    if not 1 <= batch_size <= 256:
        raise ValueError('Eigenfree batch size must be between 1 and 256')
    if field_settings is not None:
        batch_size = min(batch_size,8)
    module = load_runtime(p,False)
    if not hasattr(module.New(Lattice=((1.,0.),(0.,1.)),NumBasis=1),'GetEigenfreeOperators'):
        raise RuntimeError('The eigenfree backend needs the updated S4 native runtime')
    pol = model['polarization']
    samp,pamp = (1.,0.) if pol=='s' else (0.,-1.) if pol=='p' else (2**-.5,-2**-.5)
    simulation = build_simulation(module,model,points[0][1])
    materials = {m['name']:epsilon(m,points[0][1]) for m in model['materials']}
    # For fixed scalar constitutives at exact normal incidence, all spatial
    # Fourier operators, source H and transverse k are wavelength independent.
    # Dispersive or oblique jobs always ask S4 for fresh exact operators.
    constant = all(m['model'] in ('constant_nk','constant_eps') for m in model['materials'])
    template = None
    rows, completed, fallback_points = [],0,0
    phase_rows, cutoff_count = [],0
    unavailable,failure_preview=0,[]
    allow_unavailable=bool(model.get('allow_unavailable_points')) and field_settings is None
    diagnostics = []
    started = time.monotonic()
    recorder = None
    if field_settings is not None:
        from simulation_fields import SimulationFieldRecorder
        if field_directory is None:
            raise ValueError('Combined field sampling requires an output directory')
        recorder = SimulationFieldRecorder(field_settings,field_directory,len(points),emit)
    def payload_at(wavelength,theta):
        nonlocal template
        if constant and theta==0. and template is not None:
            return dict(template,omega=2*math.pi*1000./wavelength)
        for material in model['materials']:
            value = epsilon(material,wavelength)
            if materials[material['name']] != value:
                simulation.SetMaterial(Name=material['name'],Epsilon=value)
                materials[material['name']] = value
        simulation.SetFrequency(1000./wavelength)
        simulation.SetExcitationPlanewave(IncidenceAngles=(theta,model['phi']),
            sAmplitude=complex(samp),pAmplitude=complex(pamp),Order=0)
        payload = simulation.GetEigenfreeOperators()
        if constant and theta==0.:
            template = payload
        return payload
    emit(dict(kind='started',total=len(points),performance=p))
    def solve_segments(payloads,batch):
        """Isolate singular points without changing successful batch values."""
        if cancelled():raise Cancelled('Cancelled while isolating an unavailable GPU point')
        try:
            solution=solve_batch(payloads,backend='cupy',symmetry=bool(p.get('eigenfree_symmetry',False)))
            rta=solution.rta()
            if not np.all(np.isfinite(rta)):
                raise FloatingPointError('Nonfinite eigenfree R/T/A')
        except (FloatingPointError,np.linalg.LinAlgError,ValueError) as exc:
            known_threshold=isinstance(exc,ValueError) and str(exc)=='Exterior diffraction threshold needs native fallback'
            if not allow_unavailable or (isinstance(exc,ValueError) and not known_threshold):raise
            if len(batch)>1:
                middle=len(batch)//2
                yield from solve_segments(payloads[:middle],batch[:middle])
                yield from solve_segments(payloads[middle:],batch[middle:])
            else:
                yield None,batch,payloads,str(exc)
        else:
            yield solution,batch,payloads,rta
    try:
        with cp.cuda.Device(p['gpu_device']):
            for offset in range(0,len(points),batch_size):
                if cancelled():
                    raise Cancelled('Cancelled between bounded GPU batches')
                batch = points[offset:offset+batch_size]
                payloads = [payload_at(wave,theta) for _,wave,theta in batch]
                for solution,segment,segment_payloads,value in solve_segments(payloads,batch):
                    received_phase = []
                    if solution is None:
                        index,wave,theta=segment[0]
                        failure=dict(point_index=index,wavelength_nm=wave,angle_deg=theta,
                            reason=value+'; exact point unavailable, no interpolation was substituted.')
                        unavailable+=1
                        if len(failure_preview)<8:failure_preview.append(failure)
                        received=[[index,wave,theta,None,None,None]]
                        if result_store is not None:result_store.add_failures([failure])
                    else:
                        received=[[index,wave,theta,*map(float,rta)] for (index,wave,theta),rta in zip(segment,value)]
                        cutoff_count += sum(bool(left or right) for left,right in zip(*solution.diagnostics.get('cutoff_orders',[[],[]])))
                        if not diagnostics or solution.diagnostics != diagnostics[-1]:diagnostics.append(dict(solution.diagnostics))
                    if model.get('measure_phase'):
                        from spectral_phase import measure_phase
                        for bi,(index,wave,theta) in enumerate(segment):
                            phase = [None,None] if solution is None else measure_phase(
                                FieldView(solution,bi,segment_payloads[bi]),model,wave,theta)
                            received_phase.append([index,wave,theta,*phase])
                    if result_store is None:
                        rows.extend(received)
                        phase_rows.extend(received_phase)
                    else:result_store.add_batch(received,received_phase)
                    if checkpoint is not None:checkpoint(received)
                    if recorder is not None:
                        from pathlib import Path
                        from field_solver import sample_fields
                        for bi,point in enumerate(segment):
                            ordinal=offset+bi
                            folder=Path(recorder.root) if ordinal==0 else Path(recorder.root)/'samples'/f'{ordinal+1:06d}'
                            settings=dict(recorder.cfg,wavelength_nm=point[1],maps=True,track_contours=True)
                            sample_fields(dict(model,points=[point]),p,settings,folder,module,
                                FieldView(solution,bi,segment_payloads[bi]),solved=True,field_gpu=False)
                            recorder.add(ordinal,point)
                completed += len(batch)
                emit(dict(kind='progress',done=completed,spectrum_done=completed,total=len(points),
                          elapsed=time.monotonic()-started,statuses={'gpu':'Eigenfree complex128 scattering'},
                          gpu_solved_points=completed-unavailable,unavailable_points=unavailable))
            cp.cuda.get_current_stream().synchronize()
        if unavailable==completed:
            raise RuntimeError('No finite spectrum samples were produced; all unavailable points were saved.')
        info = dict(performance=p,points=completed,elapsed_seconds=time.monotonic()-started,
                    solver_backend='eigenfree-gpu',eigendecompositions=0,fallback_points=fallback_points,
                    gpu_solved_points=completed-unavailable,valid_points=completed-unavailable,
                    unavailable_points=unavailable,unavailable_preview=failure_preview,
                    exact_cutoff_points=cutoff_count,
                    constitutive_cache=constant,diagnostics=diagnostics,warnings=list(model.get('warnings',[])))
        info.update(cupy_version=cp.__version__,numpy_version=np.__version__)
        if unavailable:info['warnings'].append(f'{unavailable} exact spectrum point(s) are unavailable. R/T/A are blank there; see unavailable_points.csv. No interpolation was used.')
        if recorder is not None:
            info['electric_fields'] = recorder.finish('complete')
        if result_store is not None:
            info['result_storage'] = str(result_store.path)
            return result_store,info
        if model.get('measure_phase'):info['phase_rows']=phase_rows
        return rows,info
    finally:
        if recorder is not None:
            recorder.close()
