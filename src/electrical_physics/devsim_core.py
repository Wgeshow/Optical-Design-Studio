"""DEVSIM 3D finite-volume electrostatic pilot. SI internally, mesh in metres.

Shared solver infrastructure. Use run_device.py for the current geometry;
it overrides mesh_axes, contact_masks and materials with the half-domain model.
Legacy standalone geometry functions below are not the current device layout.
Fermi-Dirac charge; prescribed flat quasi-Fermi reservoirs under reverse bias.
This is NOT a continuity/current, tunnelling, or calibrated surface-state model.
The structured control-volume couplings replace tetrahedral dual volumes so
the thin layers do not inherit badly conditioned tetrahedral circumcentres.
"""
import json
import numpy as np
import devsim as ds
from scipy.constants import elementary_charge as Q, epsilon_0 as EP0, Boltzmann
from scipy.optimize import brentq
from . import reference as ref

KT = Boltzmann * 300 / Q
FHOLE = np.pi * 46**2 / 444**2
D = 'device'; R = 'body'

def nodeset(name, values):
    ds.node_solution(device=D, region=R, name=name)
    ds.set_node_values(device=D, region=R, name=name, values=np.asarray(values).ravel().tolist())

def edgeset(name, values):
    ds.edge_solution(device=D, region=R, name=name)
    ds.set_edge_values(device=D, region=R, name=name, values=np.asarray(values).ravel().tolist())

def nm(name, expr):
    ds.node_model(device=D, region=R, name=name, equation=expr)

def em(name, expr):
    ds.edge_model(device=D, region=R, name=name, equation=expr)

def fd_models(name,eta):
    """Piecewise polynomial log F_1/2 fitted to the quadrature reference.

    Avoid native Fermi in this Windows binary: its numerical derivative failed
    at eta~9. Every segment and analytic derivative is independently checked.
    """
    from numpy.polynomial import Polynomial
    nm(name+'Eta',eta)
    nm(name+'T',name+'Eta')
    variable=name+'Eta'
    log_expr=variable
    d_expr='1'
    for a in range(-12,40,4):
        b=a+4;center=(a+b)/2
        xx=np.linspace(a,b,301)
        yy,dy=ref.fermi_half(xx)
        pol=Polynomial.fit((xx-center)/2,np.log(yy),12).convert()
        def horner(coeff):
            expr=f'({coeff[-1]:.17g})'
            for c in coeff[-2::-1]:expr=f'(({expr})*(({variable}-({center}))/2)+({c:.17g}))'
            return expr
        part=horner(pol.coef); deriv=horner(pol.deriv().coef)+'/2'
        log_expr=f'ifelse({variable}>={a}, {part}, {log_expr})'
        d_expr=f'ifelse({variable}>={a}, {deriv}, {d_expr})'
    # Physical operating range stays below 40; stable high-eta continuation.
    # Use the same three-term Sommerfeld continuation as the independent
    # quadrature reference, including the high-density ITO sensitivity range.
    a = 4 / (3 * np.sqrt(np.pi))
    b = np.pi**2 / (6 * np.sqrt(np.pi))
    c = 7 * np.pi**4 / (480 * np.sqrt(np.pi))
    high=f'({a:.17g}*max({variable},40)^1.5+{b:.17g}*max({variable},40)^(-0.5)+{c:.17g}*max({variable},40)^(-2.5))'
    dhigh=f'({1.5*a:.17g}*max({variable},40)^0.5-{.5*b:.17g}*max({variable},40)^(-1.5)-{2.5*c:.17g}*max({variable},40)^(-3.5))'
    nm(name,f'ifelse({variable}>40,{high},exp({log_expr}))')
    nm(name+'D',f'ifelse({variable}>40,{dhigh},{name}*({d_expr}))')

def axis_width(a):
    faces = np.r_[a[0], (a[:-1]+a[1:])/2, a[-1]]
    return faces, np.diff(faces)

def zaxis(level, cap=True):
    h = 1.0 if level == 0 else .5
    pieces = [np.arange(0, 45, 5), np.arange(45, 56, 1), np.arange(60, 180, 10),
              np.arange(180, 240+h/2, h), np.arange(250, 365, 10),
              np.arange(365, 376, 1), np.arange(380, 421, 5),np.array([430,450])]
    if cap: pieces.append(np.array([-280,-200,-120,-60,-30,-10,-3,-1,0]))
    return np.unique(np.concatenate(pieces)) * 1e-9

def mesh_axes(kind, level):
    z = zaxis(level, cap=kind=='full')
    if kind == 'full':
        # All dimensions are provisional image estimates, in micrometres.
        x = np.unique(np.r_[np.arange(0,29, 6 if level==0 else 3),
            29,29.8,29.95,29.99,30,30.005,30.01,30.02,30.05,30.2,31,
            34,37,38.01,39,41,41.9,42,42.1,43,44,45,48,52,56,58,59,60]) * 1e-6
        y = np.unique(np.r_[np.arange(0,41, 10 if level==0 else 5),
            41,41.9,42,42.1,43,46,49,50,51,55,60]) * 1e-6
    elif kind == 'cell':
        # Quarter of a 444 nm periodic cell; hole centre is on symmetry axes.
        step = 8 if level==0 else 4
        x = np.unique(np.r_[np.arange(0,81,step),100,125,155,185,222]) * 1e-9
        y = x.copy()
    else:
        x = y = np.array([0.,50e-9,100e-9])
    return x,y,z

def contact_masks(kind, x,y,z):
    if kind=='full':
        p = (x>=30.01e-6-1e-14)&(x<=38.01e-6+1e-14)&(y<=42e-6+1e-14)&(z<=1e-14)
        metal_pad = (x>=44e-6-1e-14)&(x<=58e-6+1e-14)&(y<=50e-6+1e-14)&(z<=420e-9+1e-14)
        n = metal_pad | (z>=420e-9-1e-14)
    else:
        # Imposed top/bottom reservoir potentials, only on semiconductor.
        solid = x*x+y*y >= (46e-9)**2 if kind=='cell' else np.ones_like(x,dtype=bool)
        p = np.isclose(z,0,atol=1e-16,rtol=0)&solid
        n = z>=420e-9-1e-14
    return p,n

def build_mesh(kind, level):
    axes = mesh_axes(kind,level)
    grid = np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1)
    pts = grid.reshape(-1,3)
    shape = grid.shape[:3]
    ids = np.arange(len(pts)).reshape(shape)
    # Six conforming tetrahedra per rectangular brick.
    a=ids[:-1,:-1,:-1].ravel(); b=ids[1:,:-1,:-1].ravel()
    c=ids[:-1,1:,:-1].ravel(); d=ids[1:,1:,:-1].ravel()
    e=ids[:-1,:-1,1:].ravel(); f=ids[1:,:-1,1:].ravel()
    g=ids[:-1,1:,1:].ravel(); h=ids[1:,1:,1:].ravel()
    tet=np.concatenate([np.stack(t,axis=1) for t in [(a,b,d,h),(a,d,c,h),(a,c,g,h),(a,g,e,h),(a,e,f,h),(a,f,b,h)]])
    p,n=contact_masks(kind,*pts.T)
    elems=np.column_stack([np.full(len(tet),3),np.zeros(len(tet),int),tet]).ravel().tolist()
    for tag,mask in [(1,p),(2,n)]:
        ix=np.flatnonzero(mask)
        elems.extend(np.column_stack([np.zeros(len(ix),int),np.full(len(ix),tag),ix]).ravel().tolist())
    ds.create_gmsh_mesh(mesh='grid',coordinates=pts.ravel().tolist(),elements=elems,physical_names=['body','p_contact','n_contact'])
    ds.add_gmsh_region(mesh='grid',gmsh_name='body',region=R,material='GaAs_AlGaAs_dielectric')
    for name in ['p_contact','n_contact']:
        ds.add_gmsh_contact(mesh='grid',gmsh_name=name,region=R,name=name,material='ideal_metal')
    ds.finalize_mesh(mesh='grid'); ds.create_device(mesh='grid',device=D)
    coords=np.array([ds.get_node_model_values(device=D,region=R,name=k) for k in ('x','y','z')]).T
    idx=np.stack([np.searchsorted(ax, coords[:,j]) for j,ax in enumerate(axes)],axis=1)
    widths=[axis_width(ax)[1] for ax in axes]
    vol=np.prod(np.stack([w[idx[:,j]] for j,w in enumerate(widths)]),axis=0)
    nodeset('FVVolume',vol)
    for j in range(3): nodeset(f'I{j}',idx[:,j])
    nodeset('NodeID',np.arange(len(coords)))
    ds.edge_from_node_model(device=D,region=R,node_model='NodeID')
    i0=np.array(ds.get_edge_model_values(device=D,region=R,name='NodeID@n0'),int)
    i1=np.array(ds.get_edge_model_values(device=D,region=R,name='NodeID@n1'),int)
    delta=abs(idx[i0]-idx[i1]); axis_edges=delta.sum(axis=1)==1
    direction=delta.argmax(axis=1)
    length=np.linalg.norm(coords[i0]-coords[i1],axis=1)
    area=np.zeros(len(i0))
    for j in range(3):
        mask=axis_edges&(direction==j)
        others=[k for k in range(3) if k!=j]
        area[mask]=widths[others[0]][idx[i0[mask],others[0]]]*widths[others[1]][idx[i0[mask],others[1]]]
    edgeset('FVArea',area)
    ds.set_parameter(device=D,name='node_volume_model',value='FVVolume')
    ds.set_parameter(device=D,name='edge_couple_model',value='FVArea')
    return dict(axes=axes,coords=coords,idx=idx,volume=vol,i0=i0,i1=i1,area=area,length=length,direction=direction,shape=shape,tetrahedra=len(tet))

def overlap(lo,hi,a,b): return np.maximum(0,np.minimum(hi,b)-np.maximum(lo,a))/(hi-lo)

def materials(kind,m):
    axes=m['axes']; idx=m['idx']; x,y,z=m['coords'].T
    faces=[axis_width(a)[0] for a in axes]
    lo=np.array([faces[j][idx[:,j]] for j in range(3)])
    hi=np.array([faces[j][idx[:,j]+1] for j in range(3)])
    zlo,zhi=lo[2],hi[2]
    # Volume fractions give charge integration across each abrupt layer.
    frac=np.array([overlap(zlo,zhi,a*1e-9,b*1e-9) for a,b in [(0,50),(50,200),(200,220),(220,370),(370,420)]])
    if kind=='full':
        patterned=overlap(lo[0],hi[0],0,30e-6)*overlap(lo[1],hi[1],0,42e-6)
        solid_xy=1-FHOLE*patterned
        # Exposed ITO terrace: entire semiconductor mesa ends at x=42 um.
        mesa=overlap(lo[0],hi[0],0,42e-6)
        frac*=mesa
        frac*=solid_xy
        dielectric=np.where((x<30e-6)&(y<42e-6)&(z<0),1.,3.9)
    elif kind=='cell':
        # Integrate circular hole area with deterministic subcell quadrature.
        solid_xy=np.zeros(len(x))
        for u in (np.arange(20)+.5)/20:
            for v in (np.arange(20)+.5)/20:
                solid_xy+=((lo[0]+u*(hi[0]-lo[0]))**2+(lo[1]+v*(hi[1]-lo[1]))**2 >= (46e-9)**2)
        solid_xy/=400
        frac*=solid_xy
        dielectric=np.ones(len(x))
    else:
        solid_xy=np.ones(len(x));dielectric=np.ones(len(x))
    ga=frac[[0,1,3,4]].sum(axis=0); al=frac[2]
    eps=EP0*(12.9*ga+(12.9-2.84*.5)*al+dielectric*(1-ga-al))
    doping=np.array([-1e26,-3e25,0,8e24,1e25])@frac
    for name,val in [('GaFraction',ga),('AlFraction',al),('NetDoping',doping),('Epsilon',eps)]: nodeset(name,val)
    i0,i1=m['i0'],m['i1']
    # Harmonic face coefficient is conservative and positive.
    epse=2*eps[i0]*eps[i1]/(eps[i0]+eps[i1])
    edgeset('EdgeEpsilon',epse)
    m.update(ga=ga,al=al,eps=eps,epse=epse,doping=doping)

def setup(kind,m):
    for k,v in {'q':Q,'KT':KT,'Vp':0.,'Vn':0.,'NcG':ref.NC_G*1e6,'NvG':ref.NV_G*1e6,
                'NcA':ref.NC_A*1e6,'NvA':ref.NV_A*1e6,'EcA':.344,'EvA':-1.654}.items():
        ds.set_parameter(device=D,region=R,name=k,value=v)
    nodeset('Potential',np.zeros(len(m['coords'])))
    ds.edge_from_node_model(device=D,region=R,node_model='Potential')
    fd_models('NG','(Potential-Vn)/KT');fd_models('NA','(Potential-Vn-EcA)/KT')
    fd_models('PG','(-1.424-Potential+Vp)/KT');fd_models('PA','(EvA-Potential+Vp)/KT')
    nm('Electrons','GaFraction*NcG*NG+AlFraction*NcA*NA')
    nm('Holes','GaFraction*NvG*PG+AlFraction*NvA*PA')
    nm('Charge','-q*(Holes-Electrons+NetDoping)')
    nm('Charge:Potential','q/KT*(GaFraction*(NvG*PGD+NcG*NGD)+AlFraction*(NvA*PAD+NcA*NAD))')
    em('Displacement','EdgeEpsilon*(Potential@n0-Potential@n1)*EdgeInverseLength')
    em('Displacement:Potential@n0','EdgeEpsilon*EdgeInverseLength')
    em('Displacement:Potential@n1','-EdgeEpsilon*EdgeInverseLength')
    ds.equation(device=D,region=R,name='Poisson',variable_name='Potential',node_model='Charge',edge_model='Displacement',variable_update='log_damp')
    p0,n0=ref.contacts(0)
    for contact,base,param in [('p_contact',p0,'Vp'),('n_contact',n0,'Vn')]:
        ds.contact_node_model(device=D,contact=contact,name=contact+'_bc',equation=f'Potential-({base:.17g}+{param})')
        ds.contact_node_model(device=D,contact=contact,name=contact+'_bc:Potential',equation='1')
        ds.contact_equation(device=D,contact=contact,name='Poisson',node_model=contact+'_bc',edge_charge_model='Displacement')
    p,n=contact_masks(kind,*m['coords'].T); m.update(p=p,n=n)
    r=ref.solve(0,.2)
    initial=np.interp(m['coords'][:,2],r['z_m'],r['potential_V'])
    if kind=='full':initial[(m['coords'][:,0]>=42e-6)&(m['coords'][:,2]<420e-9)]=n0
    initial[p]=p0;initial[n]=n0
    ds.set_node_values(device=D,region=R,name='Potential',values=initial.tolist())

def capture(kind,level,bias,m,out):
    vals={k:np.array(ds.get_node_model_values(device=D,region=R,name=k)) for k in ['Potential','Electrons','Holes','Charge']}
    phi=vals['Potential'];i0,i1=m['i0'],m['i1']
    flux=m['area']*m['epse']*(phi[i0]-phi[i1])/m['length']
    balance=np.bincount(i0,weights=flux,minlength=len(phi))-np.bincount(i1,weights=flux,minlength=len(phi))+vals['Charge']*m['volume']
    free=~(m['p']|m['n'])
    norm=np.max(abs(balance[free])/(Q*1e26*m['volume'][free]))
    contact_charge={k:float(balance[m[mask]].sum()) for k,mask in [('p_C_half','p'),('n_C_half','n')]}
    total_rho=-float(np.dot(vals['Charge'],m['volume']))
    gauss=abs(sum(contact_charge.values())+total_rho)
    shape=m['shape']; order=np.ravel_multi_index(m['idx'].T,shape)
    def grid(a):
        b=np.empty(len(a));b[order]=a;return b.reshape(shape)
    phig=grid(phi)
    field=np.stack([-a for a in np.gradient(phig,*m['axes'],edge_order=2)],axis=-1)
    # Conductor interior E=0; the derivative straddling its surface belongs to
    # the dielectric/semiconductor side, not to the metal/ITO volume.
    conductor=grid((m['p']|m['n']).astype(float)).astype(bool)
    field[conductor]=0.
    zs=m['axes'][2];bar=(zs>=202e-9)&(zs<=218e-9)
    # Central solid column: full device origin; local cell far from hole.
    ix,iy=(0,int(np.argmin(abs(m['axes'][1])))) if kind!='cell' else (-1,-1)
    center=float(np.max(abs(field[ix,iy,bar,2]))/1e8)
    name=f'{kind}_L{level}_{bias:g}V'
    np.savez_compressed(out/(name+'.npz'),x=m['axes'][0],y=m['axes'][1],z=zs,potential=phig,
        electrons_cm3=grid(vals['Electrons'])*1e-6,holes_cm3=grid(vals['Holes'])*1e-6,
        ga_fraction=grid(m['ga']),al_fraction=grid(m['al']),field_V_m=field,
        net_doping_cm3=grid(m['doping'])*1e-6,charge_C_m3=grid(-vals['Charge']),
        p_contact=grid(m['p'].astype(float)),n_contact=grid(m['n'].astype(float)),
        ito=(np.broadcast_to(zs[None,None,:],shape)>=420e-9-1e-14))
    result=dict(kind=kind,level=level,bias_V=bias,nodes=len(phi),tetrahedra=m['tetrahedra'],shape=shape,
        central_barrier_field_MV_cm=center,normalized_free_node_residual=float(norm),
        total_charge_C_half=total_rho,gauss_balance_error_C_half=gauss,**contact_charge,
        contact_difference_V=float(phi[m['n']].mean()-phi[m['p']].mean()),
        ito_potential_range_V=float(np.ptp(phi[m['coords'][:,2]>=420e-9-1e-14])),
        model_revision='n-contact-on-ITO, ideal ohmic equipotential',
        finite=bool(all(np.isfinite(v).all() for v in vals.values())))
    if not result['finite'] or norm>1e-5:raise RuntimeError(f'Independent residual check failed: {result}')
    (out/(name+'.json')).write_text(json.dumps(result,indent=2))
    print('RESULT '+json.dumps(result),flush=True)
    return result

