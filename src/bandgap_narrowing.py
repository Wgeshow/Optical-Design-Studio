"""Explicit dopant-screening band-gap sensitivity, not a calibrated material fit."""
import numpy as np
from scipy.constants import e,epsilon_0,k
from electrical_fermi_transport import neutral_fermi_potential,fermi_half_transport
from photonic_bands import _number


def validate_narrowing(raw,semiconductor_ids):
    if not isinstance(raw,dict) or set(raw)-set(semiconductor_ids):raise ValueError('Band-gap narrowing must map occupied semiconductor material IDs to explicit laws')
    result={}
    for key,row in raw.items():
        if not isinstance(row,dict) or set(row)!={'model','scale','conduction_partition','source'} or row['model']!='thomas_fermi_dopant_screening':raise ValueError('Narrowing requires model=thomas_fermi_dopant_screening, scale, conduction_partition and source')
        scale=_number(row['scale'],'band-gap narrowing scale');partition=_number(row['conduction_partition'],'conduction_partition')
        if scale<0 or not 0<=partition<=1:raise ValueError('Narrowing scale must be nonnegative and conduction partition between0and1')
        if not isinstance(row['source'],str) or not row['source'].strip():raise ValueError('Band-gap narrowing needs an explicit parameter source/assumption')
        result[key]=dict(model=row['model'],scale=scale,conduction_partition=partition,source=row['source'].strip())
    return result


def screening_shift_eV(net_doping_cm3,nc_cm3,nv_cm3,affinity_eV,gap_eV,epsilon_r,temperature_K,scale=1.):
    arrays=np.broadcast_arrays(net_doping_cm3,nc_cm3,nv_cm3,affinity_eV,gap_eV,epsilon_r,temperature_K)
    rows=np.column_stack([value.ravel() for value in arrays]);unique,inverse=np.unique(rows,axis=0,return_inverse=True)
    shifts=[]
    for doping,nc,nv,chi,gap,eps,temp in unique:
        if min(nc,nv,gap,eps,temp)<=0:raise ValueError('Screening model needs positive material properties and temperature')
        thermal=k*temp/e;neutral=float(neutral_fermi_potential(doping,nc,nv,chi,gap,thermal))
        derivative=(nc*fermi_half_transport((neutral+chi)/thermal)[1]+nv*fermi_half_transport((-neutral-chi-gap)/thermal)[1])/thermal*1e6
        beta=np.sqrt(e*derivative/(eps*epsilon_0))
        shifts.append(float(scale*e*beta/(4*np.pi*eps*epsilon_0)))
    return np.asarray(shifts)[inverse].reshape(arrays[0].shape)
