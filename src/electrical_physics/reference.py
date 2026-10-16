"""CPU-only 1D degenerate Poisson diagnostic for the solid semiconductor.

Equilibrium has one common Fermi level. Reverse bias uses prescribed flat
electron/hole quasi-Fermi reservoirs: this is not a leakage/continuity,
quantum-tunneling or finite-contact/etched-hole electrostatic simulation.
Band-gap narrowing and surface charges require separate calibrated models.
"""
import numpy as np
from scipy.constants import e,epsilon_0,k
from scipy.special import expit,roots_legendre
from scipy.interpolate import PchipInterpolator
from scipy.optimize import brentq
from scipy.linalg import solve_banded
from functools import lru_cache

TEMP=300.
KT=k*TEMP/e
THICKNESS_NM=420.
SOURCE='https://www.ioffe.ru/SVA/NSM/Semicond/AlGaAs/bandstr.html'
GAAS_SOURCE='https://www.ioffe.ru/SVA/NSM/Semicond/GaAs/bandstr.html'
EG_G=1.424
NC_G=4.7e17
NV_G=9e18
X=.5
VBO=.46*X
EG_X=1.9+.124*X+.144*X*X
NC_A=2.5e19*(.85-.14*X)**1.5
NV_A=2.5e19*(.51+.25*X)**1.5


@lru_cache(maxsize=1)
def fd_table():
    eta=np.arange(-80.,40.0001,.02)
    a,w=roots_legendre(384);t=(a+1)*5;weights=w*5
    values=np.empty(len(eta))
    for start in range(0,len(eta),256):
        values[start:start+256]=4/np.sqrt(np.pi)*np.sum(weights*t*t*expit(eta[start:start+256,None]-t*t),axis=1)
    return PchipInterpolator(eta,np.log(values))


def fermi_half(eta):
    eta=np.asarray(eta,float);bounded=np.clip(eta,-80,40)
    logf=fd_table()(bounded);f=np.exp(logf);df=f*fd_table().derivative()(bounded)
    low=eta<-80;f=np.where(low,np.exp(np.clip(eta,-745,-80)),f);df=np.where(low,f,df)
    # Sommerfeld tail is only used outside the tabulation; physical solutions
    # here stay inside. It also keeps damped Newton trial states well-defined.
    t=np.maximum(eta,40.)
    high=2/np.sqrt(np.pi)*(2/3*t**1.5+np.pi**2/12*t**-.5+7*np.pi**4/960*t**-2.5)
    dhigh=2/np.sqrt(np.pi)*(t**.5-np.pi**2/24*t**-1.5-35*np.pi**4/1920*t**-3.5)
    return np.where(eta>40,high,f),np.where(eta>40,dhigh,df)


def material_grid(spacing_nm):
    cells=round(THICKNESS_NM/spacing_nm);h=THICKNESS_NM*1e-9/cells
    z=(np.arange(cells)+.5)*h;nm=z*1e9
    al=(nm>=200)&(nm<220)
    doping=np.select([nm<50,nm<200,nm<220,nm<370],[-1e20,-3e19,0.,8e18],default=1e19)*1e6
    # Ev(Al) lies VBO below Ev(Ga). Use the X minimum for x=.5, rather
    # than the higher direct optical Gamma gap for electrical statistics.
    ev=np.where(al,-EG_G-VBO,-EG_G)
    ec=np.where(al,ev+EG_X,0.)
    return dict(z_m=z,spacing_m=h,net_doping_m3=doping,
                epsilon=np.where(al,12.9-2.84*X,12.9)*epsilon_0,
                Ec_flat_eV=ec,Ev_flat_eV=ev,Nc_m3=np.where(al,NC_A,NC_G)*1e6,
                Nv_m3=np.where(al,NV_A,NV_G)*1e6,AlGaAs=al)


def populations(phi,grid,bias):
    n,dn=fermi_half((bias-grid['Ec_flat_eV']+phi)/KT)
    p,dp=fermi_half((grid['Ev_flat_eV']-phi)/KT)
    n=n*grid['Nc_m3'];p=p*grid['Nv_m3']
    rho=e*(p-n+grid['net_doping_m3'])
    derivative=-e/KT*(dn*grid['Nc_m3']+dp*grid['Nv_m3'])
    return rho,derivative,n,p


def contacts(bias):
    # Contact charge neutrality with the same FD statistics as the interior.
    def neutral(phi,doping):
        n=NC_G*fermi_half((bias+phi)/KT)[0]
        p=NV_G*fermi_half((-EG_G-phi)/KT)[0]
        return p-n+doping
    return brentq(lambda phi:neutral(phi,-1e20),-6,6,xtol=1e-12),brentq(lambda phi:neutral(phi,1e19),-6,6,xtol=1e-12)


def solve(bias=0.,spacing_nm=.2,initial=None):
    if bias>0:raise ValueError('Only equilibrium and reverse-bias diagnostics are supported')
    grid=material_grid(spacing_nm);h=grid['spacing_m'];n=len(grid['z_m'])
    left,right=contacts(bias)
    eps=grid['epsilon'];eps_faces=np.r_[eps[0],2*eps[:-1]*eps[1:]/(eps[:-1]+eps[1:]),eps[-1]]
    distances=np.full(n+1,h);distances[[0,-1]]=h/2
    coeff=eps_faces/(distances*h)
    diagonal=coeff[:-1]+coeff[1:];off=-coeff[1:-1]
    boundary=np.zeros(n);boundary[0]=coeff[0]*left;boundary[-1]=coeff[-1]*right
    if initial is not None:
        phi=np.interp(grid['z_m'],initial['z_m'],initial['potential_V'])
    else:
        phi=np.interp(grid['z_m']*1e9,[0,50,180,240,370,420],[left,left+.1,left+.1,right-.04,right-.04,right])
    scale=e*1e26
    def residual(values):
        rho,derivative,nn,pp=populations(values,grid,bias)
        r=diagonal*values-boundary-rho
        r[:-1]+=off*values[1:];r[1:]+=off*values[:-1]
        return r,derivative,rho,nn,pp
    history=[]
    for iteration in range(160):
        r,derivative,rho,nn,pp=residual(phi);error=float(np.max(abs(r))/scale);history.append(error)
        if error<1e-10:break
        band=np.zeros((3,n));band[0,1:]=off;band[1]=diagonal-derivative;band[2,:-1]=off
        step=solve_banded((1,1),band,-r,check_finite=True)
        damping=min(1.,.2/max(float(np.max(abs(step))),1e-30))
        for trial in range(25):
            candidate=phi+damping*step
            if np.max(abs(residual(candidate)[0]))<np.max(abs(r)):break
            damping*=.5
        else:raise RuntimeError('Poisson Newton line search failed')
        phi=candidate
    else:raise RuntimeError('Poisson Newton did not converge')
    field=-np.diff(np.r_[left,phi,right])/distances
    displacement=eps_faces*field
    charge_error=float(abs(displacement[-1]-displacement[0]-np.sum(rho)*h))
    voltage_error=float(abs(-np.dot(field,distances)-(right-left)))
    assert charge_error<1e-9 and voltage_error<1e-10
    return dict(**grid,bias_V=float(bias),potential_V=phi,electron_density_cm3=nn*1e-6,
                hole_density_cm3=pp*1e-6,charge_density_C_m3=rho,
                Ec_eV=grid['Ec_flat_eV']-phi,Ev_eV=grid['Ev_flat_eV']-phi,
                z_face_m=np.linspace(0,THICKNESS_NM*1e-9,n+1),field_V_m=field,
                face_epsilon=eps_faces,left_contact_potential_V=float(left),right_contact_potential_V=float(right),
                electrostatic_contact_drop_V=float(right-left),integrated_Gauss_error_C_m2=charge_error,
                integrated_voltage_error_V=voltage_error,max_normalized_Poisson_residual=error,
                iterations=iteration,residual_history=history)
