"""Editable two-band Airy/KK high-field optical sensitivity.

Generalizes the recovered ring-device sensitivity calculation. This remains an
effective-mass, local-occupation approximation, not a multiband susceptibility.
"""
from __future__ import annotations
import json
import warnings
from pathlib import Path
import numpy as np
from scipy.constants import hbar, e, m_e, c, k
from scipy.special import airy, expit
from scipy.interpolate import PchipInterpolator
from scipy.integrate import quad,IntegrationWarning
from photonic_bands import _number, _integer

CAPABILITIES=dict(engine='high_field_optics',studies=[dict(id='franz_keldysh',label='High-field interband optical sensitivity')],
    dimensions=[0,3],geometry=['explicit material samples','optional advanced-transport cell maps'],
    outputs=['interband absorption','real-index change','imaginary-index change'],
    limitations=['Two-band Airy effective-mass approximation and local FD occupation proxy','Finite-energy Kramers-Kronig integral; convergence required'],optional_runtime=False)
FIELD_SCHEMA=[dict(path='wavelengths_nm',label='Wavelength samples',type='numbers',required=True,unit='nm',section='Spectrum'),
    dict(path='material',label='Effective masses, absorption prefactor and reference gap',type='object',required=True,section='Material'),
    dict(path='samples',label='Fields, temperature, gap and carrier occupations',type='objects',required=True,section='States'),
    dict(path='energy_order',label='Kramers-Kronig energy samples',type='integer',required=False,default=4096,section='Accuracy'),
    dict(path='energy_upper_eV',label='Kramers-Kronig upper energy',type='number',required=False,default=12.,unit='eV',section='Accuracy')]
LIMITATIONS=['Parabolic effective masses and a two-band Airy approximation; no indirect Gamma-X transitions, excitons or calibrated many-body susceptibility.',
    'Fields with magnitude below 1000 V/m use the zero-field asymptotic absorption expression.',
    'Carrier occupation blocking is a local band-edge proxy; finite-field transitions are nonlocal in momentum and need a multiband model for quantitative accuracy.',
    'Finite energy cutoff and grid must be converged independently. Results are sensitivities, not absolute material optical constants.',
    'Delta n and delta k use the supplied zero-field, unoccupied reference gap and the same absorption prefactor; quadratic electrorefraction is omitted to avoid counting the field effect twice.']


def validate_material(raw):
    keys={'electron_mass_ratio','hole_mass_ratios','absorption_prefactor_cm1_sqrt_eV','reference_gap_eV','source'}
    if not isinstance(raw,dict) or set(raw)!=keys:raise ValueError('High-field material needs '+', '.join(sorted(keys)))
    if not isinstance(raw['source'],str) or not raw['source'].strip():raise ValueError('High-field material needs an explicit parameter source')
    masses=raw['hole_mass_ratios']
    if not isinstance(masses,list) or not masses:raise ValueError('Supply at least one positive hole mass')
    return dict(electron_mass_ratio=_number(raw['electron_mass_ratio'],'electron_mass_ratio',positive=True),
        hole_mass_ratios=[_number(v,'hole_mass_ratios',positive=True) for v in masses],
        absorption_prefactor_cm1_sqrt_eV=_number(raw['absorption_prefactor_cm1_sqrt_eV'],'absorption prefactor',positive=True),
        reference_gap_eV=_number(raw['reference_gap_eV'],'reference_gap_eV',positive=True),source=raw['source'].strip())


def absorption_spectrum(energy_eV,gap_eV,field_V_m,eta_n,eta_p,temperature_K,material):
    energy=np.asarray(energy_eV,float)
    if np.any(energy<=0) or not np.isfinite(energy).all():raise ValueError('Photon energies must be positive and finite')
    thermal=k*temperature_K/e
    me=material['electron_mass_ratio'];mh=np.asarray(material['hole_mass_ratios']);mr=me*mh/(me+mh)
    coefficients=material['absorption_prefactor_cm1_sqrt_eV']*mr**1.5/np.sum(mr**1.5)
    result=np.zeros(energy.shape)
    for mass,reduced,coefficient in zip(mh,mr,coefficients):
        kinetic=np.maximum(energy-gap_eV,0.)
        occupation=expit(kinetic*me/(me+mass)/thermal-eta_p)-expit(eta_n-kinetic*mass/(me+mass)/thermal)
        if abs(field_V_m)<1e3:
            alpha=coefficient*np.sqrt(kinetic)/energy
        else:
            theta=(hbar*hbar*e*e*field_V_m*field_V_m/(2*reduced*m_e))**(1/3)/e
            def profile(u):
                ai,aip,_,_=airy(u)
                return aip*aip-u*ai*ai
            alpha=np.pi*coefficient*np.sqrt(theta)/energy*(profile((gap_eV-energy)/theta)-profile((gap_eV+energy)/theta))
        result+=alpha*occupation
    return result


def response(wavelengths_nm,gap_eV,field_V_m,eta_n,eta_p,temperature_K,material,*,energy_order=4096,energy_upper_eV=12.):
    wavelengths=np.asarray(wavelengths_nm,float);energies=1239.8419843320026/wavelengths
    if np.any(energies>=energy_upper_eV) or np.any(energies<=1e-5):raise ValueError('Requested photon energy must lie strictly inside the KK integration interval')
    grid=np.unique(np.r_[np.geomspace(1e-5,.5,256),np.linspace(.5,energy_upper_eV,energy_order),gap_eV,material['reference_gap_eV']])
    if grid[-1]>energy_upper_eV:raise ValueError('Band gaps must be below the KK upper energy')
    alpha=absorption_spectrum(grid,gap_eV,field_V_m,eta_n,eta_p,temperature_K,material)
    baseline=material['absorption_prefactor_cm1_sqrt_eV']*np.sqrt(np.maximum(grid-material['reference_gap_eV'],0.))/grid
    with warnings.catch_warnings(record=True) as interpolation_warnings:
        warnings.simplefilter('always',RuntimeWarning)
        fit=PchipInterpolator(grid,alpha-baseline)
    if not np.isfinite(fit.c).all():raise RuntimeError('KK interpolation produced nonfinite coefficients; refine or adjust the optical state')
    current=absorption_spectrum(energies,gap_eV,field_V_m,eta_n,eta_p,temperature_K,material)
    reference=material['absorption_prefactor_cm1_sqrt_eV']*np.sqrt(np.maximum(energies-material['reference_gap_eV'],0.))/energies
    real=[];errors=[];warning_counts=[]
    for energy in energies:
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter('always',IntegrationWarning)
            value,error=quad(lambda u:float(fit(u))/(u+energy),grid[0],energy_upper_eV,weight='cauchy',wvar=float(energy),epsabs=1e-4,epsrel=1e-7,limit=300)
        scale=c*hbar/e*100/np.pi
        real.append(scale*value);errors.append(scale*error);warning_counts.append(len(recorded)+len(interpolation_warnings))
    conversion=100*wavelengths*1e-9/(4*np.pi)
    return dict(delta_n=np.asarray(real),delta_k=(current-reference)*conversion,
        interband_k=current*conversion,absorption_cm1=current,reference_absorption_cm1=reference,
        kk_quadrature_error_estimate=np.asarray(errors),kk_quadrature_warning_count=np.asarray(warning_counts,int))


def prepare(project,settings):
    allowed={'wavelengths_nm','material','samples','energy_order','energy_upper_eV'}
    if not isinstance(settings,dict) or set(settings)-allowed:raise ValueError('Unsupported high-field optical settings')
    wavelengths=settings.get('wavelengths_nm')
    if not isinstance(wavelengths,list) or not wavelengths:raise ValueError('Supply wavelength samples in nm')
    result=dict(wavelengths_nm=[_number(v,'wavelengths_nm',positive=True) for v in wavelengths],
        material=validate_material(settings.get('material')),energy_order=_integer(settings.get('energy_order',4096),'energy_order',128),
        energy_upper_eV=_number(settings.get('energy_upper_eV',12.),'energy_upper_eV',positive=True),samples=[])
    samples=settings.get('samples')
    if not isinstance(samples,list) or not samples:raise ValueError('Supply explicit material state samples')
    ids=set()
    for raw in samples:
        fields={'id','bandgap_eV','field_V_m','temperature_K','electron_reduced_fermi','hole_reduced_fermi'}
        if not isinstance(raw,dict) or set(raw)!=fields or not isinstance(raw['id'],str) or not raw['id'] or raw['id'] in ids:raise ValueError('Each optical state needs unique id, gap, field, temperature and both reduced Fermi energies')
        ids.add(raw['id']);row=dict(id=raw['id'])
        for field in fields-{'id'}:row[field]=_number(raw[field],field,positive=field in ('bandgap_eV','temperature_K'))
        result['samples'].append(row)
    if max(1239.8419843320026/np.asarray(result['wavelengths_nm']))>=result['energy_upper_eV'] or max([result['material']['reference_gap_eV']]+[r['bandgap_eV'] for r in result['samples']])>=result['energy_upper_eV']:
        raise ValueError('KK upper energy must exceed every requested photon energy and band gap')
    return result


def execute(prepared,directory,emit=lambda event:None,cancelled=lambda:False):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    outputs=[]
    for index,sample in enumerate(prepared['samples']):
        if cancelled():raise InterruptedError('High-field optical sensitivity cancelled')
        outputs.append(response(prepared['wavelengths_nm'],sample['bandgap_eV'],sample['field_V_m'],sample['electron_reduced_fermi'],sample['hole_reduced_fermi'],sample['temperature_K'],prepared['material'],energy_order=prepared['energy_order'],energy_upper_eV=prepared['energy_upper_eV']))
        emit(dict(phase='high_field_optics',progress=(index+1)/len(prepared['samples']),message='Computed high-field optical state '+sample['id']))
    arrays={key:np.stack([row[key] for row in outputs]) for key in outputs[0]}
    np.savez_compressed(directory/'high_field_optics.npz',wavelengths_nm=prepared['wavelengths_nm'],sample_ids=np.array([r['id'] for r in prepared['samples']]),**arrays)
    result=dict(status='complete',engine='high_field_optics',model_scope='two_band_FK_local_occupation_sensitivity',options=prepared,
        samples=len(outputs),files=['high_field_optics.npz','high_field_optics_summary.json'],limitations=LIMITATIONS,spatial_or_spectral_convergence_established=False,
        kk_quadrature_warning_count=int(arrays['kk_quadrature_warning_count'].sum()))
    if result['kk_quadrature_warning_count']:
        result['numerical_warning']='Adaptive KK quadrature reported roundoff or tolerance warnings; inspect saved error estimates and refine the energy grid/cutoff before quantitative use.'
    (directory/'high_field_optics_summary.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    return result
