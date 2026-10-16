"""Conservative semiconductor transport on the editable device's full FV graph.

The native mesh contains the actual x/y/z cells and contact face ghost nodes.
Dielectric/void faces have exactly zero carrier flux. A dummy carrier variable
on passive cells is algebraically pinned and is never a physical population.
Full-vector field-dependent mobility and impact generation are iterated to
self-consistency outside the coupled native Poisson/continuity Newton solve.
"""
from __future__ import annotations

import contextlib
import io
import math
import uuid

import numpy as np
from scipy.constants import e, epsilon_0, k
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from electrical_transport import (ModelValidityError, REFERENCES, _NATIVE_LOCK,
    _number, _check_boltzmann_band_consistency, field_breakdown_screen, ionization_coefficient, neutral_carriers,
    validate_transport)


LIMITATIONS = [
    'Three-dimensional cell-centered conservative drift diffusion on the editable rasterized geometry; each physical face carries one equal and opposite current.',
    'Fully activated dopants and ideal ohmic carrier contacts. Conductor interiors, incomplete activation, band-gap narrowing and nonparabolic bands are omitted.',
    'Dielectric and void boundaries block carriers exactly. Surface recombination, surface leakage and dynamic interface traps are omitted.',
    'Optional SRH and local avalanche generation require explicit sourced parameters. Nonlocal carrier heating, dead space, radiative/Auger recombination and self-heating are omitted.',
    'Field threshold criteria and numerical nonconvergence do not predict destructive breakdown or post-damage current.',
]


def _vector_at_nodes(values, endpoints, direction, area, size, denominator_floor=None):
    """Cell-face vector reconstruction including zero-flux outside faces."""
    a,b=endpoints.T
    result=np.zeros((size,3)); denominator=np.zeros((size,3))
    for axis in range(3):
        weight=area*direction[:,axis]**2
        vector=area*values*direction[:,axis]
        result[:,axis]=np.bincount(a,weights=vector,minlength=size)+np.bincount(b,weights=vector,minlength=size)
        denominator[:,axis]=np.bincount(a,weights=weight,minlength=size)+np.bincount(b,weights=weight,minlength=size)
    if denominator_floor is not None:denominator=np.maximum(denominator,denominator_floor)
    return np.divide(result,denominator,out=np.zeros_like(result),where=denominator>0)


def _electric_field_at_nodes(edge_field,edge_epsilon,node_epsilon,endpoints,direction,area,denominator_floor):
    """Reconstruct local E from conservative D across permittivity steps.

    The center-to-center field is a series average. D is continuous across a
    charge-free dielectric interface; each cell's local field is D/epsilon_i.
    The common vacuum permittivity cancels in this relative-permittivity form.
    """
    displacement=_vector_at_nodes(np.asarray(edge_field)*edge_epsilon,endpoints,direction,
                                  area,len(node_epsilon),denominator_floor)
    return displacement/np.asarray(node_epsilon)[:,None]


def _validate_graph_materials(mesh,cfg):
    materials=mesh['materials']
    occupied=np.unique(mesh['material_index'])
    if any(materials[index]['kind'] not in ('semiconductor','dielectric') for index in occupied):
        raise ValueError('Conductor interiors (including ITO) need a separate transport/contact model; they cannot be silently treated as passive insulation')
    active_indices=np.unique(mesh['material_index'][mesh['mobile']])
    fd=cfg['statistics']=='fermi_dirac'
    if not len(active_indices) or any(materials[index]['kind']!='semiconductor' for index in active_indices):
        raise ValueError('Graph transport supports semiconductors and passive dielectrics/voids; conductor interiors require a separate contact/transport model')
    if len(active_indices)>1 and (not fd or cfg['heterojunction'] is None):
        raise ValueError('Multiple semiconductors require Fermi-Dirac statistics and an explicitly sourced ideal_quasi_fermi heterojunction model')
    props=materials[int(active_indices[0])]['properties']
    for index in active_indices:
        properties=materials[int(index)]['properties']
        for key in ('intrinsic_cm3','Nc_cm3','Nv_cm3','electron_mobility_cm2_Vs','hole_mobility_cm2_Vs','bandgap_eV'):
            _number(properties.get(key),key,positive=True)
        _number(properties.get('affinity_eV'),'affinity_eV')
    if any(contact['object']['boundary']!='ohmic' for contact in mesh['contacts']):
        raise ValueError('Graph drift diffusion requires ideal ohmic contacts on semiconductor cells')
    if any(not np.all(mesh['mobile'].ravel()[contact['ids']]) for contact in mesh['contacts']):
        raise ValueError('A carrier contact touches an insulator or conductor; define an explicit contact injection model')
    n0,p0=neutral_carriers(mesh['donor_cm3']-mesh['acceptor_cm3'],props['intrinsic_cm3'])
    if not fd and (np.any(n0[mesh['mobile']]>.1*props['Nc_cm3']) or np.any(p0[mesh['mobile']]>.1*props['Nv_cm3'])):
        raise ModelValidityError('Boltzmann graph transport requires n/Nc and p/Nv <= 0.1; degenerate regions need Fermi-Dirac transport')
    temperature=mesh['device']['temperature_K']
    if not fd:_check_boltzmann_band_consistency(props,temperature)
    if cfg['avalanche'] and not math.isclose(temperature,cfg['avalanche']['temperature_K'],rel_tol=1e-6):
        raise ModelValidityError('Avalanche coefficient temperature differs from the device temperature')
    if cfg['srh']:
        vt=k*temperature/e
        ei=props['bandgap_eV']/2+vt/2*math.log(props['Nv_cm3']/props['Nc_cm3'])
        if not 0<ei+cfg['srh']['trap_energy_eV']<props['bandgap_eV']:
            raise ModelValidityError('SRH trap lies outside the semiconductor band gap')
    return props


def iter_graph_states(options, transport_cfg=None, emit=lambda event:None,cancelled=lambda:False):
    """Yield flat cell arrays from the full geometry plus conserved edge currents.

    All physical lengths/fields returned are SI; n/p and R/G retain explicit
    cm-based units. ``mesh`` is the actual custom mesh for result reconstruction.
    ``graph`` and edge arrays provide face-resolved conservation evidence.
    """
    from custom_electrical_solver import build_mesh
    from electrical_material_library import builtin_materials
    from electrical_native_graph import build_native_graph, create_native_graph
    from electrical_solver import _load_core
    cfg=validate_transport(transport_cfg if transport_cfg is not None else options.get('transport'))
    fd=cfg['statistics']=='fermi_dirac'
    if cfg['mode']!='semiconductor_dd':
        raise ValueError('Graph transport requires semiconductor_dd mode')
    mesh=build_mesh(options['device'],options.get('material_library',builtin_materials()))
    props=_validate_graph_materials(mesh,cfg)
    graph=build_native_graph(mesh)
    biases=[_number(v,'bias_V') for v in options.get('biases_V',[0.])]
    if not biases:raise ValueError('Transport needs at least one requested voltage')
    swept=str(options.get('swept_contact_id') or mesh['contacts'][-1]['object']['id'])
    objects={contact['object']['id']:contact['object'] for contact in mesh['contacts']}
    if swept not in objects:raise ValueError('Swept contact does not exist on the native graph')
    if cancelled():raise InterruptedError('Graph transport cancelled')
    with _NATIVE_LOCK:
        ds=_load_core().ds; name='transport3d_'+uuid.uuid4().hex; region='body'
        precision={}
        for key in ('extended_model','extended_equation','extended_solver'):
            try:precision[key]=ds.get_parameter(name=key)
            except ds.error:precision[key]=False
        for key in precision:ds.set_parameter(name=key,value=True)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                native=create_native_graph(ds,name,graph)
            order=np.asarray(native['native_node_to_graph'],int)
            # Native endpoint order fixes current sign; all public cell arrays
            # are explicitly mapped back to graph order before yielding.
            edges=np.asarray(native['graph_node_to_native'],int)[np.asarray(native['native_edge_graph_endpoints'],int)]
            a,b=edges.T
            inverse=np.empty(len(order),int);inverse[order]=np.arange(len(order))
            graph_edges=np.asarray(graph['edges'],int)
            edge_order=np.asarray(native['native_edge_to_graph'],int)
            coords=np.asarray(graph['node_xyz_m'])[order]
            length=np.linalg.norm(coords[b]-coords[a],axis=1)
            direction=(coords[b]-coords[a])/length[:,None]
            area=np.asarray(graph['edge_area_m2'])[edge_order]
            volume=np.asarray(graph['node_volume_m3'])[order]
            material_index=np.asarray(graph['node_material_index'])[order]
            mobile=np.array([mesh['materials'][index]['kind']=='semiconductor' for index in material_index],bool)
            conducting=mobile[a]&mobile[b]
            donor=np.asarray(graph['donor_cm3'])[order];acceptor=np.asarray(graph['acceptor_cm3'])[order]
            donor=np.where(mobile,donor,0.);acceptor=np.where(mobile,acceptor,0.)
            net=donor-acceptor;ni=props['intrinsic_cm3'];vt=k*mesh['device']['temperature_K']/e
            def property_array(key,passive=1.):
                return np.array([mesh['materials'][index]['properties'].get(key,passive) if mobile[j] else passive
                                 for j,index in enumerate(material_index)],float)
            nc=property_array('Nc_cm3');nv=property_array('Nv_cm3')
            chi=property_array('affinity_eV',0.);gap=property_array('bandgap_eV',1.)
            base_mu_n=property_array('electron_mobility_cm2_Vs');base_mu_p=property_array('hole_mobility_cm2_Vs')
            n0,p0=neutral_carriers(net,ni)
            if fd:
                from electrical_fermi_transport import neutral_fermi_potential,install_fermi_density
                neutral=neutral_fermi_potential(net,nc,nv,chi,gap,vt)
            else:neutral=vt*np.log(n0/ni)
            # Each edge resistance includes its two actual half-cell lengths.
            # This matters at nonuniform layer meshes and abrupt band offsets.
            axes=np.asarray(graph['edge_axis'])[edge_order]
            half=np.zeros((len(order),3))
            real=np.flatnonzero(order<graph['cell_count'])
            indices=np.unravel_index(order[real],mesh['shape'])
            for axis in range(3):half[real,axis]=mesh['widths'][axis][indices[axis]]/2
            # Two full physical faces per cell axis, including insulating
            # outer boundaries absent from the edge graph. Those missing
            # faces have zero normal flux. Passive interior edges likewise
            # contribute their exact zero carrier current to reconstruction.
            face_weights=np.divide(volume[:,None],half,out=np.zeros_like(half),where=half>0)
            def vector(values):return _vector_at_nodes(values,edges,direction,area,len(order),face_weights)
            half_a=half[a,axes];half_b=half[b,axes]
            fraction_a=half_a/(half_a+half_b);fraction_b=1.-fraction_a
            def edge_harmonic(values):
                return conducting/(fraction_a/values[a]+fraction_b/values[b])
            contact_nodes={mid:inverse[np.asarray(indices,int)] for mid,indices in graph['contacts'].items()}
            adjacency=coo_matrix((np.ones(int(conducting.sum())*2),
                (np.r_[a[conducting],b[conducting]],np.r_[b[conducting],a[conducting]])),shape=(len(order),len(order))).tocsr()
            _,labels=connected_components(adjacency,directed=False)
            anchored=set(labels[np.concatenate(list(contact_nodes.values()))].tolist())
            if any(label not in anchored for label in np.unique(labels[mobile])):
                raise ValueError('A semiconductor component has no ohmic carrier contact; its carrier number needs a separate physical boundary condition')
            epsilon=np.asarray(graph['edge_epsilon_r'])[edge_order]
            node_epsilon=np.array([mesh['materials'][index]['properties']['epsilon_r'] for index in material_index])
            def local_field(values):return _electric_field_at_nodes(values,epsilon,node_epsilon,edges,direction,area,face_weights)
            # A common integration-area normalization leaves every equation,
            # potential and current density unchanged, while avoiding 1e-30
            # carrier Jacobian entries in micrometre-scale 3D devices. Native
            # integrated contact quantities are restored to physical units.
            reference_area_cm2=float(np.max(area))*1e4
            def ns(key,values):
                ds.node_solution(device=name,region=region,name=key)
                ds.set_node_values(device=name,region=region,name=key,values=np.asarray(values,float).tolist())
                ds.edge_from_node_model(device=name,region=region,node_model=key)
            edge_solutions=set()
            def es(key,values):
                if key not in edge_solutions:
                    ds.edge_solution(device=name,region=region,name=key)
                    edge_solutions.add(key)
                ds.set_edge_values(device=name,region=region,name=key,values=np.asarray(values,float).tolist())
            def nm(key,expression,variables=()):
                ds.node_model(device=name,region=region,name=key,equation=expression)
                for variable in variables:
                    ds.node_model(device=name,region=region,name=key+':'+variable,equation=f'simplify(diff({expression},{variable}))')
            def em(key,expression,variables=()):
                ds.edge_model(device=name,region=region,name=key,equation=expression)
                for variable in variables:
                    for node in ('n0','n1'):
                        ds.edge_model(device=name,region=region,name=f'{key}:{variable}@{node}',equation=f'simplify(diff({expression},{variable}@{node}))')
            with contextlib.redirect_stdout(io.StringIO()):
                physical_volume=volume*1e6/reference_area_cm2
                # DEVSIM multiplies Dirichlet node residuals by NodeVolume.
                # A zero ghost volume would erase the boundary row entirely.
                # Give only the algebraic boundary row a numerical weight;
                # PhysicalCell masks every volume charge/source on ghosts.
                algebraic_volume=np.where(volume>0,physical_volume,float(np.max(physical_volume)))
                ns('FVVolume',algebraic_volume);ns('PhysicalCell',(volume>0).astype(float))
                es('FVArea',area*1e4/reference_area_cm2)
                ds.set_parameter(device=name,name='node_volume_model',value='FVVolume')
                ds.set_parameter(device=name,name='edge_couple_model',value='FVArea')
                for key,value in dict(q=e,V_t=vt,n_i=ni).items():ds.set_parameter(device=name,region=region,name=key,value=value)
                ns('Mobile',mobile.astype(float));ns('Doping',net)
                ns('NeutralPotential',neutral);ns('ContactN',n0);ns('ContactP',p0)
                ns('Potential',np.where(mobile,neutral,0.))
                es('EdgeEpsilon',epsilon*epsilon_0/100.)
                es('ElectronMobility',edge_harmonic(base_mu_n))
                es('HoleMobility',edge_harmonic(base_mu_p))
                ns('ImpactGeneration',np.zeros(len(order)))
                if fd:
                    ns('Nc',nc);ns('Nv',nv);ns('Affinity',chi);ns('BandGap',gap)
                    install_fermi_density(ds,name,region,'EqN','Mobile*(Potential+Affinity)/V_t','Mobile*Nc',{'Potential':'Mobile/V_t'})
                    install_fermi_density(ds,name,region,'EqP','Mobile*(-Potential-Affinity-BandGap)/V_t','Mobile*Nv',{'Potential':'-Mobile/V_t'})
                else:
                    nm('EqN','Mobile*n_i*exp(Mobile*Potential/V_t)',('Potential',))
                    nm('EqP','Mobile*n_i*exp(-Mobile*Potential/V_t)',('Potential',))
                nm('EqCharge','-q*PhysicalCell*Mobile*kahan3(EqP,-EqN,Doping)',('Potential',))
                em('ElectricField','(Potential@n0-Potential@n1)*EdgeInverseLength',('Potential',))
                em('Displacement','EdgeEpsilon*ElectricField',('Potential',))
                ds.equation(device=name,region=region,name='Poisson',variable_name='Potential',node_model='EqCharge',edge_model='Displacement',variable_update='log_damp')
                for index,mid in enumerate(objects):
                    parameter=f'ContactBias{index}';bc=f'ContactPotential{index}'
                    ds.set_parameter(device=name,name=parameter,value=0.)
                    ds.contact_node_model(device=name,contact=mid,name=bc,equation=f'Potential-NeutralPotential-{parameter}')
                    ds.contact_node_model(device=name,contact=mid,name=bc+':Potential',equation='1')
                    ds.contact_equation(device=name,contact=mid,name='Poisson',node_model=bc,edge_charge_model='Displacement')
            solves=0
            def newton():
                nonlocal solves
                if cancelled():raise InterruptedError('Graph transport cancelled')
                log=io.StringIO()
                with contextlib.redirect_stdout(log):
                    try:ds.solve(type='dc',absolute_error=1e-9 if fd else 1e4,relative_error=1e-7,maximum_iterations=100)
                    except ds.error as exc:raise RuntimeError('Native graph transport did not converge: '+str(exc)+'\n'+log.getvalue()[-1000:]) from exc
                solves+=1
            newton()
            variables=('Potential','ElectronFermi','HoleFermi') if fd else ('Potential','Electrons','Holes')
            with contextlib.redirect_stdout(io.StringIO()):
                if fd:
                    ns('ElectronFermi',np.zeros(len(order)));ns('HoleFermi',np.zeros(len(order)))
                    install_fermi_density(ds,name,region,'Electrons','Mobile*(Potential+Affinity+ElectronFermi)/V_t','Mobile*Nc',
                        {'Potential':'Mobile/V_t','ElectronFermi':'Mobile/V_t','HoleFermi':'0'})
                    install_fermi_density(ds,name,region,'Holes','Mobile*(-Potential-Affinity-BandGap-HoleFermi)/V_t','Mobile*Nv',
                        {'Potential':'-Mobile/V_t','ElectronFermi':'0','HoleFermi':'-Mobile/V_t'})
                else:
                    ns('Electrons',np.where(mobile,np.asarray(ds.get_node_model_values(device=name,region=region,name='EqN')),1.))
                    ns('Holes',np.where(mobile,np.asarray(ds.get_node_model_values(device=name,region=region,name='EqP')),1.))
                nm('Charge','-q*PhysicalCell*Mobile*kahan3(Holes,-Electrons,Doping)',variables)
                ds.equation(device=name,region=region,name='Poisson',variable_name='Potential',node_model='Charge',edge_model='Displacement',variable_update='log_damp')
                if fd:
                    es('Conducting',conducting.astype(float))
                    for label,base in (('Electron',base_mu_n),('Hole',base_mu_p)):
                        es(label+'ResistanceA',fraction_a/base[a]);es(label+'ResistanceB',fraction_b/base[b])
                    # Ideal interface: integrate the two half-cell bulk
                    # resistances in series, with no additional interface
                    # resistance. One face current enforces continuity, while
                    # a constant physical quasi-Fermi energy gives exactly 0.
                    em('ElectronCurrent','q*Conducting*EdgeInverseLength*(ElectronFermi@n1-ElectronFermi@n0)/(ElectronResistanceA/Electrons@n0+ElectronResistanceB/Electrons@n1)',variables)
                    em('HoleCurrent','q*Conducting*EdgeInverseLength*(HoleFermi@n1-HoleFermi@n0)/(HoleResistanceA/Holes@n0+HoleResistanceB/Holes@n1)',variables)
                else:
                    em('vdiff','(Potential@n0-Potential@n1)/V_t',('Potential',))
                    em('Bern01','B(vdiff)',('Potential',))
                    em('ElectronCurrent','q*ElectronMobility*EdgeInverseLength*V_t*kahan3(Electrons@n1*Bern01,Electrons@n1*vdiff,-Electrons@n0*Bern01)',variables)
                    em('HoleCurrent','-q*HoleMobility*EdgeInverseLength*V_t*kahan3(Holes@n1*Bern01,-Holes@n0*Bern01,-Holes@n0*vdiff)',variables)
                if cfg['srh']:
                    srh=cfg['srh'];n1=ni*math.exp(srh['trap_energy_eV']/vt);p1=ni*math.exp(-srh['trap_energy_eV']/vt)
                    expression=f'PhysicalCell*Mobile*(Electrons*Holes-n_i^2)/(({srh["tau_p_s"]:.17e})*(Electrons+({n1:.17e}))+({srh["tau_n_s"]:.17e})*(Holes+({p1:.17e})))'
                else:expression='0'
                nm('SRH',expression,variables)
                # Passive node terms are algebraic proxy constraints. Their
                # derivative cannot create an edge current or physical charge.
                nm('ElectronSource','q*(-SRH+ImpactGeneration+(1-Mobile)*'+('ElectronFermi)' if fd else '(Electrons-1))'),variables)
                nm('HoleSource','q*(SRH-ImpactGeneration+(1-Mobile)*'+('HoleFermi)' if fd else '(Holes-1))'),variables)
                for eq,carrier,current,source,neutral in (('ElectronContinuity',variables[1],'ElectronCurrent','ElectronSource','ContactN'),
                        ('HoleContinuity',variables[2],'HoleCurrent','HoleSource','ContactP')):
                    ds.equation(device=name,region=region,name=eq,variable_name=carrier,node_model=source,edge_model=current,variable_update='log_damp' if fd else 'positive')
                    for index,mid in enumerate(objects):
                        bc=f'{carrier}Boundary{index}'
                        ds.contact_node_model(device=name,contact=mid,name=bc,equation=f'{carrier}+ContactBias{index}' if fd else f'{carrier}-{neutral}')
                        ds.contact_node_model(device=name,contact=mid,name=bc+':'+carrier,equation='1')
                        ds.contact_equation(device=name,contact=mid,name=eq,node_model=bc,edge_current_model=current)
            newton()
            def capture():
                nodes={key:np.asarray(ds.get_node_model_values(device=name,region=region,name=key),float)
                       for key in dict.fromkeys((*variables,'Electrons','Holes'))}
                edge={key:np.asarray(ds.get_edge_model_values(device=name,region=region,name=key),float) for key in ('ElectricField','ElectronCurrent','HoleCurrent')}
                return nodes,edge
            mu_n=base_mu_n.copy() if fd else edge_harmonic(base_mu_n)
            mu_p=base_mu_p.copy() if fd else edge_harmonic(base_mu_p)
            generation=np.zeros(len(order))
            def set_mobility():
                if fd:
                    for label,values in (('Electron',mu_n),('Hole',mu_p)):
                        es(label+'ResistanceA',fraction_a/values[a]);es(label+'ResistanceB',fraction_b/values[b])
                else:
                    es('ElectronMobility',mu_n);es('HoleMobility',mu_p)
            def converge_transport():
                nonlocal mu_n,mu_p,generation
                newton()
                if not cfg['high_field_mobility'] and not cfg['avalanche']:return 0
                for iteration in range(100):
                    nodes,edge=capture()
                    ef=local_field(edge['ElectricField']*100.)
                    target_mu=[]
                    for carrier,base in (('electron',base_mu_n),('hole',base_mu_p)):
                        if cfg['high_field_mobility']:
                            hp=cfg['high_field_mobility'];speed=hp[carrier+'_saturation_velocity_cm_s'];power=hp[carrier+'_exponent']
                            scalar=base/(1+(base*np.linalg.norm(ef,axis=1)/100./speed)**power)**(1/power)
                            mobility=scalar if fd else edge_harmonic(scalar)
                        else:mobility=base if fd else edge_harmonic(base)
                        target_mu.append(mobility)
                    target_generation=np.zeros(len(order))
                    if cfg['avalanche']:
                        av=cfg['avalanche']
                        for carrier,edge_name in (('electron','ElectronCurrent'),('hole','HoleCurrent')):
                            j=vector(edge[edge_name]*1e4)
                            magnitude=np.linalg.norm(j,axis=1)
                            driving=np.divide(np.abs(np.sum(ef*j,axis=1)),magnitude,out=np.zeros(len(order)),where=magnitude>0)
                            if 'maximum_field_V_cm' in av and np.max(driving[mobile])/100.>av['maximum_field_V_cm']:
                                raise ModelValidityError('Graph avalanche exceeds the supplied maximum_field_V_cm')
                            alpha=ionization_coefficient(driving,av[carrier+'_A_cm1'],av[carrier+'_B_V_cm'],av[carrier+'_exponent'])
                            target_generation+=mobile*(volume>0)*alpha*magnitude/e/1e6
                    errors=[float(np.max(np.abs(new-old)))/max(float(np.max(np.abs(new))),1e-100)
                            for new,old in zip([*target_mu,target_generation],[mu_n,mu_p,generation])]
                    if max(errors)<2e-6:return iteration+1
                    mu_n=.5*(mu_n+target_mu[0]);mu_p=.5*(mu_p+target_mu[1]);generation=.5*(generation+target_generation)
                    set_mobility()
                    ds.set_node_values(device=name,region=region,name='ImpactGeneration',values=generation.tolist())
                    newton()
                raise RuntimeError('Vector mobility/avalanche outer iteration did not converge; this is not a prediction of breakdown')
            current_voltage=np.zeros(len(objects));ids=list(objects)
            for bias_index,bias in enumerate(biases):
                target=np.array([objects[mid]['voltage_V']+(bias if mid==swept else 0.) for mid in ids])
                emit(dict(phase='transport',progress=bias_index/max(1,len(biases)),message=f'Solving 3D Poisson and continuity at {bias:g} V'))
                limit=cfg['max_bias_step_V'];outer=0
                while np.max(np.abs(target-current_voltage))>1e-13*max(1.,float(np.max(np.abs(target)))):
                    difference=target-current_voltage;fraction=min(1.,limit/float(np.max(np.abs(difference))))
                    following=current_voltage+fraction*difference
                    saved={key:list(ds.get_node_model_values(device=name,region=region,name=key)) for key in variables}
                    saved_mu_n,saved_mu_p,saved_g=mu_n.copy(),mu_p.copy(),generation.copy()
                    for index,value in enumerate(following):ds.set_parameter(device=name,name=f'ContactBias{index}',value=float(value))
                    try:outer=converge_transport()
                    except RuntimeError:
                        for key,values in saved.items():ds.set_node_values(device=name,region=region,name=key,values=values)
                        mu_n,mu_p,generation=saved_mu_n,saved_mu_p,saved_g
                        set_mobility()
                        ds.set_node_values(device=name,region=region,name='ImpactGeneration',values=generation.tolist())
                        for index,value in enumerate(current_voltage):ds.set_parameter(device=name,name=f'ContactBias{index}',value=float(value))
                        limit*=.5
                        if limit<1e-7:raise RuntimeError(f'3D continuity failed before {bias:g} V. No breakdown voltage is inferred from numerical failure.') from None
                        continue
                    current_voltage=following;limit=min(cfg['max_bias_step_V'],limit*1.5)
                # Also converge vector-dependent models at an unchanged target,
                # including the equilibrium sample.
                if cfg['high_field_mobility'] or cfg['avalanche']:outer=converge_transport()
                nodes,edge=capture()
                if not all(np.isfinite(v).all() for v in [*nodes.values(),*edge.values()]):raise RuntimeError('3D transport contains nonfinite values')
                if not fd and (np.any(nodes['Electrons'][mobile]>.1*nc[mobile]) or np.any(nodes['Holes'][mobile]>.1*nv[mobile])):
                    raise ModelValidityError('3D transport entered degenerate injection; Fermi-Dirac statistics are required')
                if fd:
                    eta_n=(nodes['Potential']+chi+nodes['ElectronFermi'])/vt
                    eta_p=(-nodes['Potential']-chi-gap-nodes['HoleFermi'])/vt
                    if min(float(np.min(eta_n[mobile])),float(np.min(eta_p[mobile]))) < -600 or max(float(np.max(eta_n[mobile])),float(np.max(eta_p[mobile])))>200:
                        raise ModelValidityError('Fermi-Dirac state is outside the validated numerical reduced-energy range -600 <= eta <= 200')
                n=nodes['Electrons']*mobile;p=nodes['Holes']*mobile
                rho=e*(p-n+net)*1e6
                ef=local_field(edge['ElectricField']*100.)
                jn=vector(edge['ElectronCurrent']*1e4)
                jp=vector(edge['HoleCurrent']*1e4)
                currents={mid:reference_area_cm2*sum(ds.get_contact_current(device=name,contact=mid,equation=eq) for eq in ('ElectronContinuity','HoleContinuity')) for mid in ids}
                charges={mid:reference_area_cm2*ds.get_contact_charge(device=name,contact=mid,equation='Poisson') for mid in ids}
                def divergence(flux):return np.bincount(a,weights=flux,minlength=len(order))-np.bincount(b,weights=flux,minlength=len(order))
                free=volume>0
                displacement=edge['ElectricField']*100.*epsilon*epsilon_0*area
                pres=divergence(displacement)-rho*volume
                pscale=max(float(np.max(np.abs(displacement))),float(np.max(np.abs(rho*volume))),
                           float(np.max(epsilon*epsilon_0*area/length))*vt)
                perror=float(np.max(np.abs(pres[free])))/pscale
                srh=np.asarray(ds.get_node_model_values(device=name,region=region,name='SRH'),float)
                recombination=e*(srh-generation)*volume*1e6
                rn=divergence(edge['ElectronCurrent']*area*1e4)-recombination
                rp=divergence(edge['HoleCurrent']*area*1e4)+recombination
                # Face-derived floating-point floor captures cancellation of
                # large drift and diffusion components in a depleted junction.
                rounding=128*np.finfo(float).eps*e*max(float(np.max(base_mu_n)),float(np.max(base_mu_p)))*vt*max(float(np.max(n)),float(np.max(p)))*float(np.max(area*1e4/(length*100.)))
                cscale=max(max(abs(v) for v in currents.values()),rounding)
                continuity=max(float(np.max(np.abs(rn[free]))),float(np.max(np.abs(rp[free]))))
                balance=abs(sum(currents.values()));gauss=abs(sum(charges.values())+float(np.sum(rho*volume)))
                qscale=max(sum(abs(v) for v in charges.values()),float(np.sum(np.abs(rho*volume))),
                           e*ni*float(np.sum(volume))*1e6)
                # Exporting quad-precision nearly neutral densities to doubles
                # loses their tiny residual charge. Bound that cancellation
                # from the actual populations, not an arbitrary charge floor.
                charge_rounding=128*np.finfo(float).eps*e*float(np.sum((n+p+np.abs(net))*volume))*1e6
                qscale=max(qscale,charge_rounding/1e-5)
                if perror>1e-6 or gauss>1e-5*qscale:
                    raise RuntimeError(f'Independent full-geometry Poisson/Gauss check failed: local={perror:.3g}, Gauss={gauss/qscale:.3g}')
                if continuity>max(1e-4*cscale,4*rounding) or balance>max(1e-4*cscale,4*rounding*math.sqrt(int(np.sum(free)))):
                    raise RuntimeError('Independent full-geometry current-continuity check failed')
                graph_order=inverse[:graph['cell_count']]
                material_fields={mat['id']:np.linalg.norm(ef[material_index==index],axis=1) for index,mat in enumerate(mesh['materials']) if np.any(material_index==index)}
                screen=field_breakdown_screen(material_fields,cfg['breakdown_fields'])
                checks=dict(terminal_current_A=currents,terminal_charge_C=charges,terminal_voltages_V=dict(zip(ids,target.tolist())),
                    current_balance_A=balance,relative_current_balance=balance/cscale,max_continuity_residual_A=continuity,
                    current_roundoff_floor_A=rounding,max_normalized_Poisson_residual=perror,
                    charge_roundoff_floor_C=charge_rounding,
                    integrated_Gauss_error_C=gauss,relative_gauss_balance=gauss/qscale,total_charge_C=float(np.sum(rho*volume)),
                    native_solve_count=solves,vector_model_iterations=outer,semiconductor_current_predicted=True,
                    peak_impact_generation_cm3_s=float(np.max(generation)),breakdown=screen)
                details={}
                limitations=list(LIMITATIONS)
                if fd:
                    details.update(electron_quasi_fermi_eV=nodes['ElectronFermi'][graph_order],
                                   hole_quasi_fermi_eV=nodes['HoleFermi'][graph_order])
                    limitations.extend([
                        'Experimental Fermi-Dirac bulk parabolic-band transport uses conservative quasi-Fermi energy gradients and half-cell conductivity resistances; mesh convergence is required in strongly depleted regions.',
                        'The selected ideal heterojunction law has continuous interface quasi-Fermi energies, zero extra interface resistance and no interface charge. It does not include thermionic emission barriers, tunneling or interface recombination.',
                        'The present Fermi-Dirac path omits SRH recombination because the Boltzmann np-ni^2 law is not valid at degenerate equilibrium.',
                    ])
                    checks.update(min_reduced_fermi_energy=float(min(np.min(eta_n[mobile]),np.min(eta_p[mobile]))),
                                  max_reduced_fermi_energy=float(max(np.max(eta_n[mobile]),np.max(eta_p[mobile]))))
                    bulk=conducting&(material_index[a]==material_index[b])
                    checks['max_bulk_reduced_energy_step']=float(max(np.max(np.abs(eta_n[a[bulk]]-eta_n[b[bulk]])),
                                                                  np.max(np.abs(eta_p[a[bulk]]-eta_p[b[bulk]]))))
                else:limitations.append('Boltzmann carrier statistics; n/Nc and p/Nv above 0.1 are rejected.')
                if cfg['high_field_mobility']:
                    limitations.append('The supplied saturation-velocity law is monotonic and applied to all semiconductor regions; GaAs intervalley-transfer negative differential mobility is not modeled.')
                for label,key in (('electron','ElectronCurrent'),('hole','HoleCurrent')):
                    face=np.empty(len(edge_order))
                    face[edge_order]=edge[key]*area*1e4*np.asarray(native['native_edge_direction_sign'])
                    details['edge_'+label+'_current_A']=face
                yield dict(bias_V=float(bias),mesh=mesh,graph=graph,
                    shape=mesh['shape'],potential_gauge='vacuum' if fd else 'intrinsic',
                    potential_V=nodes['Potential'][graph_order],electrons_cm3=n[graph_order],holes_cm3=p[graph_order],
                    field_V_m=ef[graph_order],charge_density_C_m3=rho[graph_order],
                    electron_current_density_A_m2=jn[graph_order],hole_current_density_A_m2=jp[graph_order],
                    donor_cm3=donor[graph_order],acceptor_cm3=acceptor[graph_order],
                    impact_generation_cm3_s=generation[graph_order],srh_recombination_cm3_s=srh[graph_order],
                    terminal_current_A=currents,terminal_charge_C=charges,terminal_voltages_V=checks['terminal_voltages_V'],
                    checks=checks,limitations=limitations,references=REFERENCES,
                    method='DEVSIM conservative 3D finite-volume Poisson and electron/hole continuity on the actual device graph'+(' with Fermi-Dirac quasi-Fermi transport and ideal interfaces' if fd else ''),**details)
        finally:
            if name in ds.get_device_list():ds.delete_device(device=name)
            if name in ds.get_mesh_list():ds.delete_mesh(mesh=name)
            for key,value in precision.items():ds.set_parameter(name=key,value=value)
