"""Save physically solved carrier transport in the existing linked result format."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import time

import numpy as np
from scipy.constants import e, k


def validate_transport_device(options, cfg=None):
    """Validate the selected law and return its actual dimensional scope.

    This is Run/preflight validation, not a lightweight paint-time readout: the
    full graph path resolves the actual mesh/contact coverage.
    """
    from electrical_transport import validate_transport, validate_planar_device
    cfg=validate_transport(cfg if cfg is not None else options.get('transport'))
    if cfg['mode']=='disabled':
        return dict(path='electrostatic',scope='Finite 3D electrostatics; optional frozen Ohmic current estimate')
    if cfg['mode']=='dielectric_leakage':
        validate_planar_device(options,cfg)
        return dict(path='dielectric_planar',scope='Planar steady dielectric leakage; separate pre-damage field criteria')
    if cfg.get('statistics','boltzmann')=='boltzmann':
        try:
            validate_planar_device(options,cfg)
            return dict(path='planar',scope='Uniform planar Poisson and electron/hole continuity; native depth grid with full-area extrusion')
        except ValueError:
            pass
    from custom_electrical_solver import build_mesh
    from electrical_graph_transport import _validate_graph_materials
    mesh=build_mesh(options['device'],options['material_library'])
    _validate_graph_materials(mesh,cfg)
    return dict(path='graph',scope='Conservative 3D carrier transport on the actual finite device mesh',
                mesh_shape=list(mesh['shape']),cells=int(np.prod(mesh['shape'])))


def _token(value):
    return str(int(value)) if float(value).is_integer() and abs(value)<1e20 else repr(float(value))


def solve_semiconductor_transport(options,directory,emit=lambda event:None,cancelled=lambda:False):
    from custom_electrical_solver import build_mesh, _profile
    from electrical_transport import iter_semiconductor_states
    from electrical_graph_transport import iter_graph_states
    cfg=options['transport']
    dispatch=validate_transport_device(options,cfg)
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    generator=(iter_graph_states if dispatch['path']=='graph' else iter_semiconductor_states)(options,cfg,emit,cancelled)
    mesh=None;summary=None
    for state in generator:
        if cancelled():raise InterruptedError('Semiconductor transport cancelled')
        if mesh is None:
            mesh=state.get('mesh') or build_mesh(options['device'],options['material_library'])
            summary=dict(schema_version=1,model='custom_device',experimental=True,options=options,
                device=options['device'],material_library=options['material_library'],
                evaluated_materials=[row for row in mesh['materials'] if row['id']!='__void__'],
                semiconductor_current_predicted=True,limitations=state['limitations'],
                transport_scope=dispatch,
                geometry=dict(width_um=options['device']['width_um'],depth_um=options['device']['depth_um'],
                    thickness_um=sum(row['thickness_um'] for row in mesh['bounds']),
                    coordinates='x/y centered; z depth from top; saved axes in metres'),
                mesh=dict(shape=list(mesh['shape']),cells=int(np.prod(mesh['shape'])),resources=mesh['resources'],
                    native_dimensionality=3 if dispatch['path']=='graph' else 1,
                    native_depth_points=len(state['z_m']) if dispatch['path']=='planar' else len(mesh['axes'][2]),
                    contact_faces={contact['object']['id']:len(contact['ids']) for contact in mesh['contacts']}),
                provenance=dict(method=state['method'],references=state['references'],
                    material_sources={row['id']:row.get('sources',[]) for row in mesh['materials'] if row['id']!='__void__'},
                    band_alignment='Vacuum affinity convention; the homogeneous intrinsic gauge is explicitly shifted by -chi + Vt ln(ni/Nc)',
                    output_sampling='Native full 3D cell samples' if dispatch['path']=='graph' else 'Native 1D node solution interpolated to saved finite depth cell centers and uniformly extruded only after exact full-area geometry validation'),
                results=[])
        shape=mesh['shape'];bias=float(state['bias_V']);token=_token(bias)
        def scalar(key):
            values=np.asarray(state[key],float)
            if dispatch['path']=='graph':return values.reshape(shape)
            centers=mesh['axes'][2]
            native_z=state['z_m']
            if len(values)==len(native_z)-1:native_z=(native_z[:-1]+native_z[1:])/2
            depth=np.interp(centers,native_z,values)
            return np.broadcast_to(depth[None,None,:],shape).copy()
        data={key:scalar(key) for key in ('electrons_cm3','holes_cm3','charge_density_C_m3','donor_cm3','acceptor_cm3',
                                         'impact_generation_cm3_s','srh_recombination_cm3_s')}
        for key in ('electron_quasi_fermi_eV','hole_quasi_fermi_eV'):
            if key in state:
                data[key]=scalar(key)
        potential=scalar('potential_V')
        if cfg.get('statistics','boltzmann')=='boltzmann':
            active_index=int(np.unique(mesh['material_index'][mesh['mobile']])[0])
            mobile_material=mesh['materials'][active_index]
            props=mobile_material['properties'];vt=k*options['device']['temperature_K']/e
            offset=-props['affinity_eV']+vt*np.log(props['intrinsic_cm3']/props['Nc_cm3'])
            potential+=offset
            summary['provenance']['potential_gauge_shift_V']=float(offset)
        if dispatch['path']=='graph':
            field=np.asarray(state['field_V_m'],float).reshape(shape+(3,))
            jn=np.asarray(state['electron_current_density_A_m2'],float).reshape(shape+(3,))
            jp=np.asarray(state['hole_current_density_A_m2'],float).reshape(shape+(3,))
        else:
            field=np.zeros(shape+(3,));field[...,2]=scalar('field_V_m')
            jn=np.zeros_like(field);jp=np.zeros_like(field)
            jn[...,2]=scalar('electron_current_density_A_m2');jp[...,2]=scalar('hole_current_density_A_m2')
        contact_index=np.full(shape,-1,int)
        for ci,contact in enumerate(mesh['contacts']):contact_index.ravel()[contact['ids']]=ci
        data.update(x=mesh['axes'][0],y=mesh['axes'][1],z=mesh['axes'][2],potential=potential,
            field_V_m=field,electron_current_density_A_m2=jn,hole_current_density_A_m2=jp,
            current_density_A_m2=jn+jp,current_density_magnitude_A_m2=np.linalg.norm(jn+jp,axis=-1),
            electron_current_density_magnitude_A_m2=np.linalg.norm(jn,axis=-1),
            hole_current_density_magnitude_A_m2=np.linalg.norm(jp,axis=-1),
            epsilon_r=mesh['epsilon_r'],layer_index=mesh['layer_index'],material_index=mesh['material_index'],
            solid=mesh['solid'],material_ids=np.array([row['id'] for row in mesh['materials']]),
            contact_index=contact_index,contact_ids=np.array([row['object']['id'] for row in mesh['contacts']]),
            layer_ids=np.array([row['id'] for row in mesh['bounds']]),layer_names=np.array([row['name'] for row in mesh['bounds']]),
            bias_V=bias,cell_volumes_m3=mesh['volume'],potential_reference='Vacuum affinity convention')
        if dispatch['path']=='graph':
            # Keep the conservative face samples alongside the visualized cell
            # vectors. Ghost nodes are ideal contact faces with zero physical
            # volume; edge orientation is graph node 0 to graph node 1.
            graph=state['graph']
            for key in ('edge_electron_current_A','edge_hole_current_A'):
                data[key]=np.asarray(state[key],float)
                if data[key].shape!=(len(graph['edges']),) or not np.isfinite(data[key]).all():
                    raise RuntimeError('Saved transport face currents do not match the actual graph')
            for key in ('edges','node_xyz_m','node_volume_m3','edge_area_m2','edge_length_m','edge_direction'):
                data['transport_graph_'+key]=np.asarray(graph[key])
            data['transport_graph_cell_count']=graph['cell_count']
            data['transport_graph_ghost_contact_index']=np.full(len(graph['node_xyz_m']),-1,int)
            for ci,contact in enumerate(mesh['contacts']):
                data['transport_graph_ghost_contact_index'][graph['contacts'][contact['object']['id']]]=ci
            summary['provenance']['saved_face_currents']='Signed conventional electron and hole currents in amperes, oriented from transport_graph_edges[:,0] to [:,1]; cell nodes precede zero-volume ideal contact-face ghosts.'
        if not all(np.isfinite(value).all() for value in (potential,field,jn,jp)):
            raise RuntimeError('Transport result reconstruction produced nonfinite values')
        if dispatch['path']=='graph' and np.any(~mesh['solid']):
            if np.any(data['electrons_cm3'][~mesh['solid']]) or np.any(data['holes_cm3'][~mesh['solid']]):
                raise RuntimeError('Passive voids acquired a physical carrier population')
        profile,layers=_profile(mesh,data)
        volume=directory/f'transport_{token}V.npz';profile_path=directory/f'profile_{token}V.npz'
        csv_path=directory/f'profile_{token}V.csv';layers_path=directory/f'layers_{token}V.json'
        np.savez_compressed(volume,**data);np.savez_compressed(profile_path,**profile,bias_V=bias)
        columns=('z_nm','electrons_cm3','holes_cm3','Ez_V_m','Ez_squared_V2_m2','ito_electrons_cm3')
        with csv_path.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream);writer.writerow([*columns,'layer_name','material'])
            for zi in range(len(profile['z_nm'])):
                writer.writerow([float(profile[key][zi]) for key in columns]+[str(profile['layer_name'][zi]),str(profile['material'][zi])])
        layers_path.write_text(json.dumps(layers,indent=2),encoding='utf-8')
        checks=dict(state['checks'])
        checks['terminal_charge_C']=state['terminal_charge_C'];checks['terminal_voltages_V']=state['terminal_voltages_V']
        checks['terminal_current_A']=state['terminal_current_A']
        (directory/f'transport_{token}V.json').write_text(json.dumps(checks,indent=2,allow_nan=False),encoding='utf-8')
        summary['results'].append(dict(bias_V=bias,volume_npz=str(volume),profile_npz=str(profile_path),
            profile_csv=str(csv_path),layers_json=str(layers_path),checks=checks))
    if summary is None:raise RuntimeError('Native transport returned no solved states')
    summary['elapsed_s']=time.monotonic()-started
    path=directory/'electrical_summary.json';summary['summary_json']=str(path)
    path.write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    emit(dict(phase='complete',progress=1.,message='Physical carrier transport currents and fields saved'))
    return summary
