"""Contacts-only device template and explicitly assumed ITO material model.

Geometry and finite-volume weights follow the completed 2026-10-12 study.
All distances are metres internally; the stored half device has x >= 0.
"""
import numpy as np
from scipy.constants import e, epsilon_0, k, h, m_e
from scipy.optimize import brentq
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve
from . import reference as ref


def ito_parameters(density_cm3=5e20, rs=45., thickness_nm=40.):
    temperature = 300.
    mass = .35
    density = density_cm3 * 1e6
    mobility = 1 / (e * density * rs * thickness_nm * 1e-9)
    nc = 2 * (2 * np.pi * mass * m_e * k * temperature / h**2)**1.5
    eta = brentq(lambda a: nc * ref.fermi_half(a)[0] - density, -20, 300)
    ec = 4.07 - 5.
    return dict(thickness_nm=thickness_nm, density_cm3=density_cm3,
                donors_m3=density, rs_ohm=rs, mobility_cm2_Vs=mobility * 1e4,
                mass_ratio=mass, static_eps=9., eps_infinity=3.9,
                affinity_eV=5., bandgap_eV=3.8, Nc_m3=nc,
                eta_bulk=float(eta), Ec_flat_eV=ec,
                neutral_potential_V=float(ec + eta * k * temperature / e),
                gamma_rad_s=e / (mass * m_e * mobility), temperature_K=temperature)


def axes(core, level, explicit=False):
    xs = [0,15,30,45,49,49.9,49.99,50,50.0025,50.005,50.01,50.1,
          51,55,59,60,61,70,75,78,80,120,200,300,380,385,390,400,410]
    x = np.asarray(xs) * 1e-6
    if level:
        x = np.unique(np.r_[x, np.array([7.5,22.5,37.5,49.95,50.00125,
                                         50.00375,50.0075]) * 1e-6])
    y = np.unique(np.r_[-x[:0:-1], x])
    z = core.zaxis(level, False)
    z = np.unique(np.r_[z[z <= 420e-9 + 1e-16],
                         np.array([-200,-100,-50,-10,-1,320,445,470]) * 1e-9])
    if explicit:
        step = .5 if level == 0 else .25
        z = np.unique(np.r_[z[z < 400e-9],np.arange(400,414,1)*1e-9,
            np.arange(414,427+step/2,step)*1e-9,np.arange(428,441,1)*1e-9,
            np.array([442,445,450,455,459,460])*1e-9])
    return x,y,z


def masks(x,y,z, explicit=False):
    p = ((x <= 60e-6+1e-14) & (abs(y) <= 60e-6+1e-14)
         & ((x >= 50.005e-6-1e-14) | (abs(y) >= 50.005e-6-1e-14))
         & (z >= -100e-9-1e-14) & (z <= 1e-14))
    metal = ((x <= 390e-6+1e-14) & (abs(y) <= 385e-6+1e-14)
             & ((x >= 78e-6-1e-14) | (y <= -75e-6+1e-14))
             & (z >= 320e-9-1e-14) & (z <= 420e-9+1e-14))
    return p, metal if explicit else metal | (z >= 420e-9-1e-14)


def materials(core, mesh, explicit=False, par=None):
    faces = [core.axis_width(a)[0] for a in mesh['axes']]
    idx = mesh['idx']
    lo = np.array([faces[j][idx[:,j]] for j in range(3)])
    hi = np.array([faces[j][idx[:,j]+1] for j in range(3)])
    frac = np.array([core.overlap(lo[2],hi[2],a*1e-9,c*1e-9)
                     for a,c in [(0,50),(50,200),(200,220),(220,370),(370,420)]])
    mesa = core.overlap(lo[0],hi[0],0,50e-6) * core.overlap(lo[1],hi[1],-50e-6,50e-6)
    frac *= mesa * (1-core.FHOLE)
    ga = frac[[0,1,3,4]].sum(axis=0)
    al = frac[2]
    ito = core.overlap(lo[2],hi[2],420e-9,460e-9) if explicit else np.zeros(len(ga))
    eps = epsilon_0 * (12.9*ga + 11.48*al + 9*ito + (1-ga-al-ito))
    doping = np.array([-1e26,-3e25,0,8e24,1e25]) @ frac
    if explicit:
        doping += par['donors_m3'] * ito
    for name,a in [('GaFraction',ga),('AlFraction',al),('ITOFraction',ito),
                   ('NetDoping',doping),('Epsilon',eps)]:
        core.nodeset(name,a)
    epse = 2*eps[mesh['i0']]*eps[mesh['i1']]/(eps[mesh['i0']]+eps[mesh['i1']])
    core.edgeset('EdgeEpsilon',epse)
    mesh.update(ga=ga,al=al,ito=ito,eps=eps,epse=epse,doping=doping)


def sheet(step_um=2.):
    """Unit sheet resistance, unit full-device load; conservative half device."""
    x = np.arange(0,410+step_um/2,step_um)*1e-6
    y = np.arange(-410,410+step_um/2,step_um)*1e-6
    fx = np.r_[x[0],(x[:-1]+x[1:])/2,x[-1]]
    fy = np.r_[y[0],(y[:-1]+y[1:])/2,y[-1]]
    wx,wy = np.diff(fx),np.diff(fy)
    xx,yy = np.meshgrid(x,y,indexing='ij')
    ids = np.arange(xx.size).reshape(xx.shape)
    a = np.r_[ids[:-1,:].ravel(),ids[:,:-1].ravel()]
    c = np.r_[ids[1:,:].ravel(),ids[:,1:].ravel()]
    g = np.r_[np.broadcast_to(wy[None,:]/np.diff(x)[:,None],ids[:-1,:].shape).ravel(),
              np.broadcast_to(wx[:,None]/np.diff(y)[None,:],ids[:,:-1].shape).ravel()]
    matrix = coo_matrix((np.r_[g,g,-g,-g],(np.r_[a,c,a,c],np.r_[a,c,c,a])),
                        shape=(xx.size,xx.size)).tocsr()
    contact = ((xx<=390e-6+1e-14)&(abs(yy)<=385e-6+1e-14)
               &((xx>=78e-6-1e-14)|(yy<=-75e-6+1e-14))).ravel()
    injection = np.outer(np.maximum(0,np.minimum(fx[1:],50e-6)-fx[:-1]),
        np.maximum(0,np.minimum(fy[1:],50e-6)-np.maximum(fy[:-1],-50e-6))).ravel()
    injection *= .5/injection.sum()
    free = ~contact
    potential = np.zeros(xx.size)
    potential[free] = spsolve(matrix[free][:,free],injection[free])
    balance = abs(-(matrix@potential)[contact].sum()-.5)/.5
    energy = abs(np.dot(injection,potential)-np.sum(g*(potential[a]-potential[c])**2))/np.dot(injection,potential)
    if balance > 1e-8 or energy > 1e-8:
        raise RuntimeError('ITO sheet current/power balance failed')
    return dict(x=x,y=y,transfer=potential.reshape(xx.shape),contact=contact.reshape(xx.shape)),dict(
        step_um=step_um,nodes=xx.size,current_balance_relative=float(balance),
        power_balance_relative=float(energy),peak_transfer=float(potential.max()))


def planar_ito(par, bias=0., spacing_nm=.2, initial=None, cancelled=lambda:False):
    """Independent finite-volume planar reference used only as a Newton seed."""
    from scipy.linalg import solve_banded
    kt = k*300/e
    cells = round(460/spacing_nm)
    dz = 460e-9/cells
    z = (np.arange(cells)+.5)*dz
    nm = z*1e9
    ito,al = nm>=420,(nm>=200)&(nm<220)
    nc = np.where(ito,par['Nc_m3'],np.where(al,ref.NC_A,ref.NC_G)*1e6)
    nv = np.where(ito,0,np.where(al,ref.NV_A,ref.NV_G)*1e6)
    ec = np.where(ito,par['Ec_flat_eV'],np.where(al,.344,0.))
    ev = np.where(al,-1.654,-1.424)
    doping = np.select([nm<50,nm<200,nm<220,nm<370,nm<420],
                       [-1e26,-3e25,0,8e24,1e25],default=par['donors_m3'])
    eps = epsilon_0*np.where(ito,par['static_eps'],np.where(al,11.48,12.9))
    ef = np.r_[eps[0],2*eps[:-1]*eps[1:]/(eps[:-1]+eps[1:]),eps[-1]]
    dist = np.full(cells+1,dz);dist[[0,-1]]=dz/2
    coeff = ef/(dist*dz);diag=coeff[:-1]+coeff[1:];off=-coeff[1:-1]
    left,right = ref.contacts(0)[0]+bias,par['neutral_potential_V']
    boundary=np.zeros(cells);boundary[0]=coeff[0]*left;boundary[-1]=coeff[-1]*right
    phi = (np.interp(z,initial['z_m'],initial['potential_V']) if initial is not None
           else np.interp(nm,[0,50,180,240,370,415,425,460],
                           [left,left+.1,left+.1,.2,.23,.2,right,right]))
    def residual(values):
        fn,dn=ref.fermi_half((values-ec)/kt);fp,dp=ref.fermi_half((ev-values+bias)/kt)
        nn=nc*fn;pp=nv*fp;rho=e*(pp-nn+doping);der=-e/kt*(nc*dn+nv*dp)
        rr=diag*values-boundary-rho;rr[:-1]+=off*values[1:];rr[1:]+=off*values[:-1]
        return rr,der,nn,pp,rho
    for iteration in range(180):
        if cancelled():raise InterruptedError('Electrical simulation cancelled')
        rr,der,nn,pp,rho=residual(phi);error=float(np.max(abs(rr))/(e*1e26))
        if error<3e-9:break
        band=np.zeros((3,cells));band[0,1:]=off;band[1]=diag-der;band[2,:-1]=off
        update=solve_banded((1,1),band,-rr);damping=min(1,.2/max(float(np.max(abs(update))),1e-30))
        for trial in range(30):
            candidate=phi+damping*update
            if np.max(abs(residual(candidate)[0]))<np.max(abs(rr)):break
            damping*=.5
        else:raise RuntimeError('ITO planar seed line search failed')
        phi=candidate
    else:raise RuntimeError('ITO planar seed failed to converge')
    field=-np.diff(np.r_[left,phi,right])/dist
    gauss=float(abs(ef[-1]*field[-1]-ef[0]*field[0]-rho.sum()*dz))
    if gauss>1e-7:raise RuntimeError('ITO planar seed Gauss balance failed')
    return dict(z_m=z,potential_V=phi,electrons_cm3=nn*1e-6,holes_cm3=pp*1e-6,
                field_faces_V_m=field,residual=error,gauss_C_m2=gauss)
