"""Finite-volume electrostatics for the editable finite device document.

The mesh resolves extruded material/void polygons, layer doping and local doping
overrides. Mobile charge uses parabolic-band Fermi-Dirac statistics and prescribed
reservoirs. This is an electrostatic model, not drift-diffusion/current simulation.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.constants import e, epsilon_0, k
from scipy.sparse import coo_matrix, diags

from device_model import layer_bounds, shape_mask, validate_device
from electrical_physics.reference import fermi_half
from electrical_mesh import check_mesh_resources, solve_linear_system
from electrical_sweep import resolve_biases

LIMITATIONS = [
    'Electrostatics with prescribed flat electron/hole quasi-Fermi reservoirs; carrier continuity and electrical current are not solved.',
    'Geometry is a finite rectangular device with material/void shapes and doping regions extruded through individual layers; no arbitrary STEP solids.',
    'Shapes and contact footprints are rasterized on a cell-centered conservative finite-volume mesh. Narrow features require mesh refinement.',
    'Fully activated dopants, parabolic-band Fermi-Dirac charge, and affinity-rule band alignment are assumed; traps, recombination, tunnelling and band-gap narrowing are omitted.',
    'Contacts must be on exposed selected-layer surfaces; buried contacts require an explicitly exposed opening or an external side surface.',
    'Material transport properties are retained in results but electrostatics does not consume mobility or conductivity to predict a current.',
]


def validate_options(options):
    from electrical_material_library import builtin_materials, validate_materials
    if not isinstance(options, dict):
        raise ValueError('Custom electrical options must be a dictionary')
    library = validate_materials(options.get('material_library', builtin_materials()))
    device = validate_device(options.get('device'), library, require_contacts=True)
    active = [row for row in device['contacts'] if row['enabled'] and row['layer_id'] in {layer['id'] for layer in layer_bounds(device)}]
    if not active:
        raise ValueError('Device needs an enabled contact on an enabled layer')
    swept = str(options.get('swept_contact_id') or active[-1]['id'])
    if swept not in {row['id'] for row in active}:
        raise ValueError('Swept contact must be an enabled contact on an enabled layer')
    biases = resolve_biases(options.get('biases_V', [0., -2.]))
    mode = str(options.get('charge_model', 'semiconductor'))
    if mode not in ('semiconductor', 'dielectric'):
        raise ValueError('charge_model must be semiconductor or dielectric')
    from electrical_transport import validate_transport
    transport=validate_transport(options.get('transport'))
    required={'semiconductor_dd':'semiconductor','dielectric_leakage':'dielectric'}.get(transport['mode'])
    if required and required!=mode:
        raise ValueError(f'{transport["mode"]} requires the {required} charge model')
    normalized=dict(model='custom_device', device=device, material_library=library,
                    biases_V=biases, charge_model=mode, swept_contact_id=swept,transport=transport)
    if transport['mode']!='disabled':
        from electrical_transport_adapter import validate_transport_device
        validate_transport_device(normalized,transport)
    return normalized


def build_mesh(device, material_library, *, require_contacts=True):
    """Resolve the actual document into a layer-aligned structured cell mesh."""
    from electrical_material_library import evaluate_material
    device = validate_device(device, material_library, require_contacts=require_contacts)
    resources = check_mesh_resources(device)
    bounds = layer_bounds(device)
    nx, ny, per = (device['mesh'][key] for key in ('nx', 'ny', 'nz_per_layer'))
    xf = np.linspace(-device['width_um']/2, device['width_um']/2, nx+1) * 1e-6
    yf = np.linspace(-device['depth_um']/2, device['depth_um']/2, ny+1) * 1e-6
    zf = np.r_[0., np.concatenate([np.linspace(row['z_min_um'], row['z_max_um'], per+1)[1:] for row in bounds])] * 1e-6
    axes = [(faces[:-1]+faces[1:])/2 for faces in (xf, yf, zf)]
    widths = [np.diff(faces) for faces in (xf, yf, zf)]
    shape = tuple(len(axis) for axis in axes)
    index = np.arange(np.prod(shape), dtype=int).reshape(shape)
    layer_index = np.broadcast_to(np.repeat(np.arange(len(bounds)), per)[None,None,:], shape).copy()
    materials = [evaluate_material(row, temperature_K=device['temperature_K']) for row in material_library]
    ids = {row['id']: i for i,row in enumerate(materials)}
    # Mesh air is independent of the user's material library and cannot acquire
    # accidental carriers through an edited Air entry.
    air_index = len(materials)
    materials.append(dict(id='__void__', name='Void / vacuum', kind='dielectric',
        properties=dict(epsilon_r=1., bandgap_eV=0., affinity_eV=0.,
                        Nc_cm3=0., Nv_cm3=0., bulk_electron_cm3=0., bulk_hole_cm3=0.)))
    material_index = np.empty(shape, int)
    donor = np.zeros(shape); acceptor = np.zeros(shape)
    for i, row in enumerate(bounds):
        slab = layer_index == i
        material_index[slab] = ids[row['material_id']]
        donor[slab] = row['donor_cm3']; acceptor[slab] = row['acceptor_cm3']
    xx, yy = np.meshgrid(axes[0]*1e6, axes[1]*1e6, indexing='ij')
    feature_cells = {}
    from pc_array import iter_shape_masks
    layer_ids={row['id']:i for i,row in enumerate(bounds)}
    for group in ('shapes', 'doping_regions'):
        entries=iter_shape_masks(device,xx,yy) if group=='shapes' else (
            (obj,shape_mask(obj,xx,yy),None) for obj in device[group] if obj['enabled'])
        for obj,footprint,group_counts in entries:
            if not obj['enabled']:
                continue
            layer = layer_ids.get(obj['layer_id'])
            if layer is None:
                continue
            mask = footprint[:,:,None] & (layer_index == layer)
            count = int(mask.sum())
            if group_counts is not None:
                unresolved=[object_id for object_id,hits in group_counts.items() if not hits]
                if unresolved:
                    raise ValueError(f'{obj["name"]}: {len(unresolved):,} of {len(group_counts):,} array/shape features do not intersect mesh cells. Refine the electrical XY mesh or reduce the electrical domain; the geometry has not been truncated.')
                feature_cells.update({object_id:hits*per for object_id,hits in group_counts.items()})
            else:feature_cells[obj['id']] = count
            if not count:
                raise ValueError(obj['name'] + ' does not intersect mesh cells. Move it inside the device or refine the mesh.')
            if group == 'shapes':
                if obj['operation'] == 'void':
                    material_index[mask] = air_index
                    donor[mask] = 0.; acceptor[mask] = 0.
                else:
                    material_index[mask] = ids[obj['material_id']]
            else:
                solid_mask = mask & (material_index != air_index)
                if not solid_mask.any():
                    raise ValueError(obj['name'] + ' intersects only void cells')
                donor[solid_mask] = obj['donor_cm3']; acceptor[solid_mask] = obj['acceptor_cm3']
    solid = material_index != air_index
    if not solid.any():
        raise ValueError('Device contains no solid mesh cells')
    fields = {}
    for key in ('epsilon_r', 'bandgap_eV', 'affinity_eV', 'Nc_cm3', 'Nv_cm3', 'bulk_electron_cm3', 'bulk_hole_cm3'):
        fields[key] = np.take([row['properties'].get(key, 0.) for row in materials], material_index)
    mobile = np.take([row['kind'] != 'dielectric' for row in materials], material_index)
    donor += fields['bulk_electron_cm3']; acceptor += fields['bulk_hole_cm3']
    volume = widths[0][:,None,None] * widths[1][None,:,None] * widths[2][None,None,:]
    mesh = dict(device=device, bounds=bounds, materials=materials, shape=shape,
                index=index, axes=axes, faces=[xf,yf,zf], widths=widths,
                layer_index=layer_index, material_index=material_index,
                donor_cm3=donor, acceptor_cm3=acceptor, solid=solid,
                mobile=mobile, volume=volume, feature_cells=feature_cells, resources=resources, **fields)
    mesh['contacts'] = _map_contacts(mesh) if require_contacts else []
    return mesh


def _map_contacts(mesh):
    shape, index = mesh['shape'], mesh['index']
    x, y, z = mesh['axes']; xf, yf, zf = mesh['faces']
    dx, dy, dz = mesh['widths']; solid = mesh['solid']
    contacts = []; occupied = set()
    for obj in mesh['device']['contacts']:
        if not obj['enabled']:
            continue
        layer = next((i for i,row in enumerate(mesh['bounds']) if row['id'] == obj['layer_id']), None)
        if layer is None:
            continue
        zindices = np.flatnonzero(mesh['layer_index'][0,0,:] == layer)
        surface = obj['surface']
        axis = 2 if surface in ('top','bottom') else 0 if surface.startswith('side_x') else 1
        sign = -1 if surface in ('top', 'side_x_min', 'side_y_min') else 1
        coord = int(zindices[0] if sign < 0 else zindices[-1]) if axis == 2 else (0 if sign < 0 else shape[axis]-1)
        selection = [slice(None)]*3; selection[axis] = coord
        selection = tuple(selection)
        ids = index[selection]
        ii,jj,kk = np.unravel_index(ids, shape)
        px = np.full(ids.shape, xf[0] if sign<0 else xf[-1])*1e6 if axis==0 else x[ii]*1e6
        py = np.full(ids.shape, yf[0] if sign<0 else yf[-1])*1e6 if axis==1 else y[jj]*1e6
        footprint = shape_mask(obj, px, py)
        if axis != 2:
            footprint &= (mesh['layer_index'][selection] == layer)
        footprint &= solid[selection]
        neighbor_coord = coord + sign
        buried = np.zeros(ids.shape, bool)
        other_ids = np.full(ids.shape, -1, int)
        if 0 <= neighbor_coord < shape[axis]:
            neighbor = list(selection); neighbor[axis] = neighbor_coord; neighbor = tuple(neighbor)
            buried = solid[neighbor]
            other_ids = index[neighbor]
        if np.any(footprint & buried):
            raise ValueError(obj['name'] + ' lies on a buried layer surface. Expose that surface with a void opening or select an external face.')
        hits = footprint & ~buried
        if not hits.any():
            raise ValueError(obj['name'] + ' does not intersect an exposed mesh face. Check its layer/surface/footprint or refine the mesh.')
        ids_hit = ids[hits].ravel()
        other_hit = other_ids[hits].ravel()
        ii,jj,kk = np.unravel_index(ids_hit, shape)
        area = dy[jj]*dz[kk] if axis==0 else dx[ii]*dz[kk] if axis==1 else dx[ii]*dy[jj]
        distance = (dx[ii] if axis==0 else dy[jj] if axis==1 else dz[kk])/2
        for cell in ids_hit:
            face = (int(cell), axis, sign)
            if face in occupied:
                raise ValueError('Electrical contact footprints overlap on the same surface: ' + obj['name'])
            occupied.add(face)
        contacts.append(dict(object=obj, ids=ids_hit, others=other_hit, area=area,
                             distance=distance, axis=axis, sign=sign,
                             area_m2=float(area.sum())))
    if not contacts:
        raise ValueError('Device has no resolved electrical contacts')
    return contacts


def _system(mesh):
    """Conservative harmonic-permittivity flux graph, including contact faces."""
    eps = mesh['epsilon_r']*epsilon_0
    index, widths = mesh['index'], mesh['widths']
    endpoints_a = []; endpoints_b = []; coefficients = []
    removed = {(min(int(a),int(b)), max(int(a),int(b))) for contact in mesh['contacts']
               for a,b in zip(contact['ids'], contact['others']) if b >= 0}
    for axis in range(3):
        lo=[slice(None)]*3; hi=[slice(None)]*3
        lo[axis]=slice(0,-1); hi[axis]=slice(1,None); lo=tuple(lo); hi=tuple(hi)
        left=index[lo].ravel(); right=index[hi].ravel()
        a,b=np.unravel_index(left,mesh['shape']),np.unravel_index(right,mesh['shape'])
        area=np.ones(len(left))
        for other in range(3):
            if other!=axis: area*=widths[other][a[other]]
        distance_left=widths[axis][a[axis]]/2; distance_right=widths[axis][b[axis]]/2
        coeff=area/(distance_left/eps[lo].ravel()+distance_right/eps[hi].ravel())
        if removed:
            keep=np.fromiter(((min(int(i),int(j)),max(int(i),int(j))) not in removed for i,j in zip(left,right)),bool,len(left))
            left,right,coeff=left[keep],right[keep],coeff[keep]
        endpoints_a.append(left); endpoints_b.append(right); coefficients.append(coeff)
    ia=np.concatenate(endpoints_a); ib=np.concatenate(endpoints_b); coeff=np.concatenate(coefficients)
    size=index.size
    diagonal=np.bincount(np.r_[ia,ib],weights=np.r_[coeff,coeff],minlength=size)
    for contact in mesh['contacts']:
        contact['coefficient']=eps.ravel()[contact['ids']]*contact['area']/contact['distance']
        diagonal[contact['ids']]+=contact['coefficient']
        other=contact['others']; valid=other>=0
        contact['other_coefficient']=np.zeros(len(other))
        if valid.any():
            coords=np.unravel_index(other[valid],mesh['shape'])
            dist=widths[contact['axis']][coords[contact['axis']]]/2
            contact['other_coefficient'][valid]=eps.ravel()[other[valid]]*contact['area'][valid]/dist
            diagonal[other[valid]]+=contact['other_coefficient'][valid]
    matrix=coo_matrix((np.r_[diagonal,-coeff,-coeff],
        (np.r_[np.arange(size),ia,ib],np.r_[np.arange(size),ib,ia])),shape=(size,size)).tocsr()
    return matrix


def _neutral_potential(mesh):
    """Local charge neutrality supplies a robust heterogeneous Newton seed."""
    kt=k*mesh['device']['temperature_K']/e
    ec=-mesh['affinity_eV'].ravel(); ev=ec-mesh['bandgap_eV'].ravel()
    nc=mesh['Nc_cm3'].ravel()*1e6; nv=mesh['Nv_cm3'].ravel()*1e6
    doping=(mesh['donor_cm3']-mesh['acceptor_cm3']).ravel()*1e6
    active=mesh['mobile'].ravel()
    low=ec-30.; high=ec+30.
    # Vectorized bisection avoids one scalar optimizer per mesh cell.
    for _ in range(75):
        phi=(low+high)/2
        charge=nv*fermi_half((ev-phi)/kt)[0]-nc*fermi_half((phi-ec)/kt)[0]+doping
        low=np.where(charge>0,phi,low); high=np.where(charge>0,high,phi)
    neutral=(low+high)/2
    return np.where(active,neutral,0.)


def _reservoirs(mesh, terminal_voltages, mode):
    """Use n/p contact voltages as the documented flat carrier reservoirs."""
    electrons=[]; holes=[]; intrinsic=[]
    net=(mesh['donor_cm3']-mesh['acceptor_cm3']).ravel()
    for contact in mesh['contacts']:
        if contact['object']['boundary'] != 'ohmic':
            continue
        voltage=terminal_voltages[contact['object']['id']]
        doping=float(np.mean(net[contact['ids']]))
        if doping > 1.:
            electrons.append(voltage)
        elif doping < -1.:
            holes.append(voltage)
        else:
            intrinsic.append(voltage)
    if mode=='dielectric':
        return 0.,0.
    for values,label in ((electrons,'electron'),(holes,'hole'),(intrinsic,'intrinsic')):
        if values and max(values)-min(values)>1e-9:
            raise ValueError(f'Different {label}-reservoir contact voltages require carrier continuity, which this electrostatic solver does not implement. Use potential electrodes with dielectric charge mode for field-only calculations.')
    if intrinsic and (electrons or holes) and any(abs(v-intrinsic[0])>1e-9 for v in electrons+holes):
        raise ValueError('Biased intrinsic ohmic contacts require carrier continuity; assign doped reservoirs or use dielectric charge mode.')
    vn=electrons[0] if electrons else intrinsic[0] if intrinsic else 0.
    vp=holes[0] if holes else intrinsic[0] if intrinsic else vn
    if holes and electrons and vp-vn>1e-9:
        raise ValueError('Forward-biased p/n reservoirs require carrier continuity. This electrostatic model supports equilibrium and reverse bias.')
    return float(vn),float(vp)


def _populations(phi, mesh, vn, vp, mode):
    if mode=='dielectric':
        zero=np.zeros_like(phi)
        return zero,zero,zero,zero
    kt=k*mesh['device']['temperature_K']/e
    ec=-mesh['affinity_eV'].ravel(); ev=ec-mesh['bandgap_eV'].ravel()
    active=mesh['mobile'].ravel()
    nc=mesh['Nc_cm3'].ravel()*1e6*active; nv=mesh['Nv_cm3'].ravel()*1e6*active
    n,dn=fermi_half((phi-ec-vn)/kt); p,dp=fermi_half((ev-phi+vp)/kt)
    electrons=n*nc; holes=p*nv
    fixed=(mesh['donor_cm3']-mesh['acceptor_cm3']).ravel()*1e6*active
    return e*(holes-electrons+fixed),-e/kt*(dn*nc+dp*nv),electrons,holes


def solve(options, directory, emit=lambda event:None, cancelled=lambda:False):
    """Write the same portable electrical result contract as the legacy solver."""
    cfg=validate_options(options)
    if cfg['transport']['mode']=='semiconductor_dd':
        from electrical_transport_adapter import solve_semiconductor_transport
        return solve_semiconductor_transport(cfg,directory,emit,cancelled)
    if cancelled():
        raise InterruptedError('Electrical simulation cancelled')
    started=time.monotonic()
    def progress(phase, amount, message):
        if cancelled():
            raise InterruptedError('Electrical simulation cancelled')
        emit(dict(phase=phase, progress=float(amount), message=message))
    progress('mesh',0.,'Resolving editable layers, shapes, doping and contacts')
    mesh=build_mesh(cfg['device'],cfg['material_library'])
    matrix=_system(mesh); volume=mesh['volume'].ravel()
    neutral=_neutral_potential(mesh) if cfg['charge_model']=='semiconductor' else np.zeros_like(volume)
    directory=Path(directory).resolve(); directory.mkdir(parents=True,exist_ok=True)
    summary=dict(schema_version=1,model='custom_device',experimental=True,options=cfg,
        device=cfg['device'], material_library=cfg['material_library'],
        evaluated_materials=[row for row in mesh['materials'] if row['id']!='__void__'],
        semiconductor_current_predicted=False,limitations=LIMITATIONS,
        geometry=dict(width_um=cfg['device']['width_um'],depth_um=cfg['device']['depth_um'],
                      thickness_um=sum(row['thickness_um'] for row in mesh['bounds']),
                      coordinates='x/y centered; z is depth from top, all stored volume axes in metres'),
        mesh=dict(shape=list(mesh['shape']),cells=int(volume.size),feature_cells=mesh['feature_cells'],
                  resources=mesh['resources'],
                  contact_faces={row['object']['id']:len(row['ids']) for row in mesh['contacts']}),
        provenance=dict(method='Conservative finite-volume Poisson with harmonic interface permittivity and Fermi-Dirac mobile charge',
                        band_alignment='Affinity rule from editable electrical material properties',
                        material_sources={row['id']:row.get('sources',[]) for row in mesh['materials'] if row['id']!='__void__'}),
        results=[])
    previous=None
    dielectric_base=None;dielectric_response=None;dielectric_linear_checks=[]
    if cfg['charge_model']=='dielectric':
        # The fixed-permittivity, charge-free Poisson system is exactly linear.
        # Retain every requested bias state while reusing its two independent
        # basis solutions, rather than refactorizing the same matrix per point.
        base_rhs=np.zeros_like(volume);unit_rhs=np.zeros_like(volume)
        for contact in mesh['contacts']:
            voltage=contact['object']['voltage_V']
            np.add.at(base_rhs,contact['ids'],contact['coefficient']*voltage)
            valid=contact['others']>=0
            np.add.at(base_rhs,contact['others'][valid],contact['other_coefficient'][valid]*voltage)
            if contact['object']['id']==cfg['swept_contact_id']:
                np.add.at(unit_rhs,contact['ids'],contact['coefficient'])
                np.add.at(unit_rhs,contact['others'][valid],contact['other_coefficient'][valid])
        dielectric_base,report=solve_linear_system(matrix,base_rhs,cancelled=cancelled)
        dielectric_linear_checks.append(report)
        dielectric_response,report=solve_linear_system(matrix,unit_rhs,cancelled=cancelled)
        dielectric_linear_checks.append(report)
        summary['provenance']['bias_sampling']='All requested states evaluated by exact linear dielectric superposition from the base-voltage and unit swept-offset Poisson solutions; per-state residual and Gauss checks remain independent.'
    for bias_index,bias in enumerate(cfg['biases_V']):
        progress('solve',.05+.85*bias_index/max(1,len(cfg['biases_V'])),f'Solving editable device at {bias:g} V')
        voltages={row['object']['id']:row['object']['voltage_V']+(bias if row['object']['id']==cfg['swept_contact_id'] else 0.) for row in mesh['contacts']}
        vn,vp=_reservoirs(mesh,voltages,cfg['charge_model'])
        rhs=np.zeros_like(volume)
        for contact in mesh['contacts']:
            voltage=voltages[contact['object']['id']]
            potential=(neutral[contact['ids']]+voltage if contact['object']['boundary']=='ohmic' and cfg['charge_model']=='semiconductor' else np.full(len(contact['ids']),voltage))
            contact['potential']=potential
            np.add.at(rhs,contact['ids'],contact['coefficient']*potential)
            valid=contact['others']>=0
            np.add.at(rhs,contact['others'][valid],contact['other_coefficient'][valid]*potential[valid])
        linear_checks=[]
        def linear_solve(system, values):
            answer, report=solve_linear_system(system, values, cancelled=cancelled,
                progress=lambda count: progress('solve',.05+.85*bias_index/max(1,len(cfg['biases_V'])),
                    f'Fine mesh at {bias:g} V: CG iteration {count:,}'))
            linear_checks.append(report)
            return answer
        if dielectric_base is not None:
            phi=dielectric_base+bias*dielectric_response
            linear_checks.extend(dielectric_linear_checks if bias_index==0 else
                [dict(method='Exact linear dielectric superposition',basis_solves=2)])
        else:
            phi=previous.copy() if previous is not None else linear_solve(matrix,rhs)
        # Equilibrium neutrality is often a much better semiconductor seed than
        # a Laplace interpolation across highly degenerate junctions.
        if previous is None and cfg['charge_model']=='semiconductor':
            phi=np.where(mesh['mobile'].ravel(),neutral+(vn+vp)/2,phi)
        scale=max(float(np.max(np.abs(matrix.diagonal())*.0259)),
                  float(np.max(e*(mesh['donor_cm3']+mesh['acceptor_cm3']).ravel()*1e6*volume)),1e-30)
        history=[]
        def residual(values):
            rho,derivative,n,p=_populations(values,mesh,vn,vp,cfg['charge_model'])
            return matrix@values-rhs-rho*volume,derivative,rho,n,p
        for iteration in range(160):
            if cancelled():
                raise InterruptedError('Electrical simulation cancelled')
            r,derivative,rho,n,p=residual(phi)
            error=float(np.max(np.abs(r))/scale); history.append(error)
            if error<1e-9:
                break
            jacobian=matrix-diags(derivative*volume)
            step=linear_solve(jacobian,-r)
            if not np.isfinite(step).all():
                raise RuntimeError('Electrical Newton update is not finite; check material parameters and contact connectivity')
            damping=min(1.,.25/max(float(np.max(np.abs(step))),1e-30))
            norm=float(np.max(np.abs(r)))
            for _ in range(28):
                candidate=phi+damping*step
                if float(np.max(np.abs(residual(candidate)[0])))<norm:
                    break
                damping*=.5
            else:
                raise RuntimeError('Editable-device Poisson line search failed; refine the mesh or reduce the bias step')
            phi=candidate
        else:
            raise RuntimeError('Editable-device Poisson solver did not converge; refine the mesh or reduce the bias step')
        previous=phi.copy()
        terminal_charge={}
        total_flux=0.
        for contact in mesh['contacts']:
            # Outward displacement flux equals epsilon*(phi_cell-phi_terminal)/d.
            flux=contact['coefficient']*(phi[contact['ids']]-contact['potential'])
            valid=contact['others']>=0
            if valid.any():
                flux[valid]+=contact['other_coefficient'][valid]*(phi[contact['others'][valid]]-contact['potential'][valid])
            charge=float(flux.sum()); terminal_charge[contact['object']['id']]=-charge; total_flux+=charge
        charge=float(np.dot(rho,volume)); gauss=abs(total_flux-charge)
        charge_scale=max(abs(total_flux),abs(charge),sum(abs(v) for v in terminal_charge.values()),scale,1e-30)
        checks=dict(max_normalized_Poisson_residual=error,iterations=iteration,
                    residual_history=history,integrated_Gauss_error_C=gauss,
                    relative_gauss_balance=gauss/charge_scale,total_charge_C=charge,
                    terminal_charge_C=terminal_charge,terminal_voltages_V=voltages,
                    reservoir_voltages_V=dict(electron=vn,hole=vp),
                    semiconductor_current_predicted=False,model_revision='custom_device',
                    linear_solves=linear_checks)
        if checks['relative_gauss_balance']>1e-6:
            raise RuntimeError('Independent custom-device Gauss balance check failed')
        grid_phi=phi.reshape(mesh['shape'])
        field=np.stack([-a for a in np.gradient(grid_phi,*mesh['axes'],edge_order=1)],axis=-1)
        if not np.isfinite(field).all():
            raise RuntimeError('Custom-device electric field contains nonfinite values')
        contact_index=np.full(mesh['shape'],-1,dtype=int)
        for ci,contact in enumerate(mesh['contacts']):
            contact_index.ravel()[contact['ids']]=ci
        data=dict(x=mesh['axes'][0],y=mesh['axes'][1],z=mesh['axes'][2],potential=grid_phi,
            field_V_m=field,electrons_cm3=n.reshape(mesh['shape'])*1e-6,
            holes_cm3=p.reshape(mesh['shape'])*1e-6,charge_density_C_m3=rho.reshape(mesh['shape']),
            donor_cm3=mesh['donor_cm3'],acceptor_cm3=mesh['acceptor_cm3'],
            epsilon_r=mesh['epsilon_r'],layer_index=mesh['layer_index'],
            material_index=mesh['material_index'],solid=mesh['solid'],
            material_ids=np.array([row['id'] for row in mesh['materials']]),
            contact_index=contact_index,
            contact_ids=np.array([row['object']['id'] for row in mesh['contacts']]),
            layer_ids=np.array([row['id'] for row in mesh['bounds']]),
            layer_names=np.array([row['name'] for row in mesh['bounds']]),
            bias_V=float(bias),cell_volumes_m3=mesh['volume'])
        profile,layers=_profile(mesh,data)
        # The shortest round-trip decimal preserves distinct dense voltages.
        # Default :g precision can overwrite distinct samples at high bias.
        token=str(int(bias)) if float(bias).is_integer() and abs(bias)<1e20 else repr(float(bias))
        stem=f'custom_{token}V'; volume_path=directory/(stem+'.npz')
        profile_path=directory/f'profile_{token}V.npz'; csv_path=directory/f'profile_{token}V.csv'
        layers_path=directory/f'layers_{token}V.json'
        np.savez_compressed(volume_path,**data)
        np.savez_compressed(profile_path,**profile,bias_V=float(bias))
        columns=('z_nm','electrons_cm3','holes_cm3','Ez_V_m','Ez_squared_V2_m2','ito_electrons_cm3')
        with csv_path.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream); writer.writerow([*columns,'layer_name','material'])
            for index in range(len(profile['z_nm'])):
                writer.writerow([float(profile[key][index]) for key in columns]+[str(profile['layer_name'][index]),str(profile['material'][index])])
        layers_path.write_text(json.dumps(layers,indent=2),encoding='utf-8')
        (directory/(stem+'.json')).write_text(json.dumps(checks,indent=2),encoding='utf-8')
        summary['results'].append(dict(bias_V=float(bias),volume_npz=str(volume_path),
            profile_npz=str(profile_path),profile_csv=str(csv_path),layers_json=str(layers_path),checks=checks))
    summary['elapsed_s']=time.monotonic()-started
    if cfg['transport']['mode']=='dielectric_leakage':
        from electrical_transport import dielectric_leakage_iv
        rows,metadata=dielectric_leakage_iv(summary,cfg['transport'],cancelled)
        summary['dielectric_leakage']=dict(rows=rows,metadata=metadata)
        for result,check in zip(summary['results'],metadata['checks']):
            result['checks']['dielectric_transport']=check
        summary['limitations']=[LIMITATIONS[1],LIMITATIONS[2],LIMITATIONS[4],
            'The saved 3D fields are charge-free electrostatic fields; dielectric leakage currents use a separate steady constitutive calculation. A multilayer steady-current partition can differ from the electrostatic capacitive partition.',
            *metadata['warnings']]
        summary['elapsed_s']=time.monotonic()-started
    summary_path=directory/'electrical_summary.json'; summary['summary_json']=str(summary_path)
    summary_path.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    progress('complete',1.,'Editable-device electrical profiles and 3D fields saved')
    return summary


def _profile(mesh, data):
    """Area averages retain actual user layer identity and separate ITO charge."""
    weights=mesh['widths'][0][:,None]*mesh['widths'][1][None,:]
    solid_weight=weights[:,:,None]*mesh['solid']
    denominator=solid_weight.sum(axis=(0,1))
    def average(values):
        return np.divide((solid_weight*values).sum(axis=(0,1)),denominator,
                         out=np.zeros_like(denominator),where=denominator>0)
    ito=np.take([row['id']=='ito' or str(row.get('name','')).casefold()=='ito' for row in mesh['materials']],mesh['material_index'])
    ito_e=average(data['electrons_cm3']*ito)
    electrons=average(data['electrons_cm3']*~ito)
    holes=average(data['holes_cm3']*~ito)
    ez=average(data['field_V_m'][...,2]); ez2=average(data['field_V_m'][...,2]**2)
    layer_index=mesh['layer_index'][0,0,:]
    names=np.take([row['name'] for row in mesh['bounds']],layer_index)
    ids=np.take([row['id'] for row in mesh['bounds']],layer_index)
    material=np.take([row['material_id'] for row in mesh['bounds']],layer_index)
    profile=dict(z_nm=mesh['axes'][2]*1e9,electrons_cm3=electrons,holes_cm3=holes,
                 Ez_V_m=ez,Ez_squared_V2_m2=ez2,ito_electrons_cm3=ito_e,
                 layer_name=names,layer_id=ids,material=material)
    records=[]
    for zi,(a,b) in enumerate(zip(mesh['faces'][2][:-1]*1e9,mesh['faces'][2][1:]*1e9)):
        layer=mesh['bounds'][layer_index[zi]]
        records.append(dict(name=layer['name'],layer_id=layer['id'],material=layer['material_id'],
            depth_start_nm=float(a),depth_end_nm=float(b),thickness_nm=float(b-a),
            electrons_cm3=float(electrons[zi]),holes_cm3=float(holes[zi]),
            field_V_m=float(ez[zi]),field_squared_V2_m2=float(ez2[zi]),
            ito_electrons_cm3=float(ito_e[zi]),solid_area_fraction=float(denominator[zi]/weights.sum())))
    return profile,records
