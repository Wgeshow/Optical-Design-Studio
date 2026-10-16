"""Explicit temperature laws for the optional advanced transport model."""
import math
import numpy as np
from photonic_bands import _number, _integer


def validate_feedback(raw, material_ids, reference_temperature):
    fields={'temperature_models','conductivity_exponents','maximum_iterations','temperature_tolerance_K','relaxation'}
    if not isinstance(raw,dict) or set(raw)-fields:
        raise ValueError('Temperature feedback supports temperature_models, conductivity_exponents, maximum_iterations, temperature_tolerance_K and relaxation')
    models=raw.get('temperature_models')
    if not isinstance(models,dict) or set(models)!=set(material_ids):
        raise ValueError('Supply a temperature model for every occupied mobile material, and no absent materials')
    result=dict(temperature_models={},conductivity_exponents={},maximum_iterations=_integer(raw.get('maximum_iterations',40),'maximum_iterations'),
        temperature_tolerance_K=_number(raw.get('temperature_tolerance_K',.01),'temperature_tolerance_K',positive=True),
        relaxation=_number(raw.get('relaxation',.5),'relaxation',positive=True))
    if result['relaxation']>1:raise ValueError('Temperature relaxation must be at most 1')
    required={'Nc_exponent','Nv_exponent','electron_mobility_exponent','hole_mobility_exponent','minimum_temperature_K','maximum_temperature_K','source'}
    for key,raw_model in models.items():
        if not isinstance(raw_model,dict) or required-set(raw_model) or set(raw_model)-required-{'varshni'}:
            raise ValueError('Temperature material '+key+' requires explicit DOS and mobility exponents, validity temperature range, source and optional varshni')
        model={field:_number(raw_model[field],key+'.'+field) for field in required-{'source'}}
        if not 0<model['minimum_temperature_K']<=reference_temperature<=model['maximum_temperature_K']:
            raise ValueError('Temperature validity range must include the device reference temperature')
        if not isinstance(raw_model['source'],str) or not raw_model['source'].strip():raise ValueError('Temperature material needs source/assumption note')
        model['source']=raw_model['source'].strip()
        if 'varshni' in raw_model:
            value=raw_model['varshni']
            if not isinstance(value,dict) or set(value)!={'alpha_eV_K','beta_K','conduction_partition'}:
                raise ValueError('Varshni needs alpha_eV_K,beta_K,conduction_partition')
            law={field:_number(value[field],'varshni.'+field) for field in value}
            if law['alpha_eV_K']<0 or law['beta_K']<0 or not 0<=law['conduction_partition']<=1:
                raise ValueError('Invalid Varshni coefficient or band-edge partition')
            model['varshni']=law
        result['temperature_models'][key]=model
    exponents=raw.get('conductivity_exponents',{})
    if not isinstance(exponents,dict):raise ValueError('Thermal conductivity exponents must map material IDs to numbers')
    result['conductivity_exponents']={key:_number(value,'thermal conductivity exponent') for key,value in exponents.items()}
    return result


def apply_material_temperature(properties,temperature,reference,model):
    """Return coefficients at T, preserving the supplied reference exactly."""
    temperature=np.asarray(temperature,float)
    if not np.isfinite(temperature).all() or np.any(temperature<model['minimum_temperature_K']) or np.any(temperature>model['maximum_temperature_K']):
        raise ValueError('Temperature is outside the explicitly supplied material-law validity range')
    ratio=temperature/reference
    values={key:np.broadcast_to(float(value),temperature.shape).copy() for key,value in properties.items()}
    for key,exponent in [('Nc_cm3','Nc_exponent'),('Nv_cm3','Nv_exponent'),('electron_mobility_cm2_Vs','electron_mobility_exponent'),('hole_mobility_cm2_Vs','hole_mobility_exponent')]:
        values[key]*=ratio**model[exponent]
    if 'varshni' in model:
        law=model['varshni'];alpha,beta=law['alpha_eV_K'],law['beta_K']
        shift=-alpha*(temperature**2/(temperature+beta)-reference**2/(reference+beta))
        values['bandgap_eV']+=shift
        values['affinity_eV']-=law['conduction_partition']*shift
    if np.any(values['bandgap_eV']<=0):raise ValueError('Temperature law produced a nonpositive band gap')
    return values
