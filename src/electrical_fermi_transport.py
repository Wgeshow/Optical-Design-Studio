"""Fermi--Dirac populations and their consistent native Newton derivatives.

The normalized bulk parabolic-band F_1/2 integral follows Eq. (7) of
Kantner, arXiv:1911.00377. Log-polynomials are fitted to direct Gauss--Legendre
quadrature, not to a material fit. Low-density fugacity and high-density
Sommerfeld expansions keep Newton trial states finite. The public numerical
range is -600 <= eta <= 200 and is checked before a state is accepted.
"""
from functools import lru_cache

import numpy as np
from numpy.polynomial import Polynomial
from scipy.optimize import brentq
from scipy.special import expit, roots_legendre


@lru_cache(maxsize=1)
def _coefficients():
    # u=t^2 removes the square-root endpoint singularity in F_1/2.
    x,w=roots_legendre(1024)
    t=(x+1)*7.; weights=w*7.
    result=[]
    for lo in range(-16,64,4):
        eta=np.linspace(lo,lo+4,301);center=lo+2.
        values=4/np.sqrt(np.pi)*np.sum(weights*t*t*expit(eta[:,None]-t*t),axis=1)
        polynomial=Polynomial.fit((eta-center)/2.,np.log(values),14).convert()
        result.append((lo,center,polynomial.coef,polynomial.deriv().coef/2.))
    return tuple(result)


def fermi_half_transport(eta):
    """Return F_1/2 and its actual numerical derivative, both positive."""
    eta=np.asarray(eta,float)
    # Polynomial values are evaluated only on their own interval. No clipping
    # of an accepted population, density floor or substituted derivative.
    f=np.empty(eta.shape);df=np.empty(eta.shape)
    low=eta < -16.
    fugacity=np.exp(eta[low])
    f[low]=fugacity*(1-fugacity/2**1.5+fugacity**2/3**1.5-fugacity**3/4**1.5)
    df[low]=fugacity*(1-fugacity/2**.5+fugacity**2/3**.5-fugacity**3/4**.5)
    for lo,center,coef,dcoef in _coefficients():
        select=(eta>=lo)&(eta<lo+4)
        argument=(eta[select]-center)/2.
        f[select]=np.exp(np.polynomial.polynomial.polyval(argument,coef))
        df[select]=f[select]*np.polynomial.polynomial.polyval(argument,dcoef)
    high=eta>=64.
    z=eta[high]
    a=4/(3*np.sqrt(np.pi));b=np.pi**2/(6*np.sqrt(np.pi));c=7*np.pi**4/(480*np.sqrt(np.pi))
    f[high]=a*z**1.5+b*z**-.5+c*z**-2.5
    df[high]=1.5*a*z**.5-.5*b*z**-1.5-2.5*c*z**-3.5
    return f,df


def neutral_fermi_potential(net_doping, nc, nv, affinity, gap, thermal_voltage):
    """Neutral ideal-ohmic contact potential in the vacuum band-energy gauge."""
    arrays=np.broadcast_arrays(net_doping,nc,nv,affinity,gap)
    tuples=np.column_stack([value.ravel() for value in arrays])
    unique,inverse=np.unique(tuples,axis=0,return_inverse=True)
    result=[]
    for doping,c,v,chi,eg in unique:
        def charge(phi):
            n=c*fermi_half_transport((phi+chi)/thermal_voltage)[0]
            p=v*fermi_half_transport((-phi-chi-eg)/thermal_voltage)[0]
            return float(p-n+doping)
        result.append(brentq(charge,-chi-eg-200*thermal_voltage,
                            -chi+200*thermal_voltage,xtol=2e-14))
    return np.asarray(result)[inverse].reshape(arrays[0].shape)


def install_fermi_density(ds,device,region,name,eta,prefactor,partials):
    """Install a population and analytical derivatives used by native Newton.

    ``partials`` maps solution variables to d(eta)/d(variable) expressions.
    All material properties stay node-resolved; no band-edge smoothing occurs.
    The value and derivative use exactly the same polynomial coefficients.
    """
    def nm(key,expr):ds.node_model(device=device,region=region,name=key,equation=expr)
    variable=name+'Eta'
    nm(variable,eta)
    # Native ifelse evaluates inactive branches too. Bound each *inactive*
    # approximation to its own domain to avoid polynomial extrapolation
    # overflow; the selected physical population is never clipped.
    z=f'exp(min({variable},-16))'
    low=f'{z}*(1-{z}/({2**1.5:.17e})+{z}^2/({3**1.5:.17e})-{z}^3/8)'
    dlow=f'{z}*(1-{z}/({2**.5:.17e})+{z}^2/({3**.5:.17e})-{z}^3/2)'
    expression=low;derivative=dlow
    for lo,center,coef,dcoef in _coefficients():
        argument=f'((min(max({variable},{lo}),{lo+4})-({center:.17e}))/2)'
        def horner(values):
            value=f'({values[-1]:.17e})'
            for coefficient in values[-2::-1]:
                value=f'(({value})*{argument}+({coefficient:.17e}))'
            return value
        part=f'exp({horner(coef)})'
        expression=f'ifelse({variable}>={lo},{part},{expression})'
        derivative=f'ifelse({variable}>={lo},({part})*({horner(dcoef)}),{derivative})'
    a=4/(3*np.sqrt(np.pi));b=np.pi**2/(6*np.sqrt(np.pi));c=7*np.pi**4/(480*np.sqrt(np.pi))
    z=f'max({variable},64)'
    high=f'({a:.17e})*{z}^1.5+({b:.17e})*{z}^(-.5)+({c:.17e})*{z}^(-2.5)'
    dhigh=f'({1.5*a:.17e})*{z}^.5-({.5*b:.17e})*{z}^(-1.5)-({2.5*c:.17e})*{z}^(-3.5)'
    nm(name+'Integral',f'ifelse({variable}>=64,{high},{expression})')
    nm(name+'IntegralDerivative',f'ifelse({variable}>=64,{dhigh},{derivative})')
    nm(name,f'({prefactor})*{name}Integral+(1-Mobile)')
    ds.edge_from_node_model(device=device,region=region,node_model=name)
    for solution,slope in partials.items():
        key=name+':'+solution
        nm(key,f'({prefactor})*{name}IntegralDerivative*({slope})')
        ds.edge_from_node_model(device=device,region=region,node_model=key)
        for endpoint in ('n0','n1'):
            for other in ('n0','n1'):
                ds.edge_model(device=device,region=region,
                    name=f'{name}@{endpoint}:{solution}@{other}',
                    equation=f'{key}@{endpoint}' if endpoint==other else '0')
