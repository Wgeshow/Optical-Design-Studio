"""Editable periodic conformal semiconductor transport through a fixed worker."""
import copy
import math
from pathlib import Path

from input_diagnostics import diagnostic, InputValidationError

LIMITATIONS = [
    'Full three-dimensional periodic unit cell with full-face ideal-ohmic top and bottom terminals; not a finite laser aperture.',
    'P1 tetrahedral weak form with lumped charge/recombination and element-average conductivity; it is not an exponentially fitted or monotone discretization.',
    'Parabolic-band Fermi-Dirac densities, fully activated dopants and ideal continuous quasi-Fermi interfaces. No contact barriers, quantum confinement or optical gain.',
    'Optional B/C/lifetime recombination uses an explicitly approximate detailed-balance factor; not a calibrated degenerate trap law.',
    'No self-heating, avalanche, nonlocal tunnelling or surface recombination in this conformal model.',
    'Circular boundaries are represented by first-order facets. Mesh and bias convergence remain required.',
]
CAPABILITIES = dict(label='Periodic conformal semiconductor transport', dimensions=[3],
    optional_runtime='Python with NumPy, SciPy and Gmsh', limitations=LIMITATIONS)
FIELD_SCHEMA = [
    dict(path='period_um', label='Cell width and depth', type='array', required=True, unit='um', section='Geometry'),
    dict(path='layers', label='Editable layers, top to bottom', type='objects', required=True, section='Geometry'),
    dict(path='inclusions', label='Air inclusions in patterned layers', type='objects', default=[], section='Geometry'),
    dict(path='materials', label='Explicit semiconductor material properties', type='object', required=True, section='Materials'),
    dict(path='temperature_K', label='Uniform material temperature', type='number', default=300., unit='K', section='Materials'),
    dict(path='void_epsilon_r', label='Void relative permittivity', type='number', default=1., section='Materials'),
    dict(path='biases_V', label='Bias sequence', type='numbers', required=True, unit='V', section='Bias'),
    dict(path='swept_contact', label='Swept full-face terminal', type='choice', options=['top','bottom'], default='top', section='Bias'),
    dict(path='mesh', label='Mesh accuracy and size budget', type='object', required=True, section='Accuracy'),
    dict(path='maximum_iterations', label='Newton iteration limit', type='integer', default=80, section='Accuracy'),
    dict(path='tolerance_V', label='Scaled equation residual tolerance', type='number', default=2e-9, unit='V', section='Accuracy'),
    dict(path='max_bias_step_V', label='Bias continuation step', type='number', default=.05, unit='V', section='Accuracy'),
    dict(path='parameter_source', label='Material and interface assumption source', type='string', required=True, section='Model'),
    dict(path='runtime', label='Gmsh Python runtime', type='object', default={}, section='Runtime'),
]


def _bad(field, message, object_id=''):
    raise InputValidationError([diagnostic(message, workspace='research_studies', model_id='pcsel_transport',
        section='inputs', field=field, object_id=object_id, code='pcsel_transport.input')])


def _number(value, field, positive=False, nonnegative=False, integer=False):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        _bad(field, 'Enter a finite number.')
    if isinstance(value,bool) or not math.isfinite(number) or positive and number<=0 or nonnegative and number<0 or integer and number!=int(number):
        _bad(field, 'Enter a finite '+('positive ' if positive else 'nonnegative ' if nonnegative else '')+('integer.' if integer else 'number.'))
    return int(number) if integer else number


def prepare(project, settings):
    from research_physics_runtime import validate_runtime
    from shapely.geometry import Polygon, Point, box
    if not isinstance(settings,dict) or set(settings)-{row['path'] for row in FIELD_SCHEMA}:
        _bad('', 'Unsupported conformal transport input fields.')
    cfg = copy.deepcopy(settings)
    period = cfg.get('period_um')
    if not isinstance(period,list) or len(period)!=2:
        _bad('period_um', 'Enter the cell width and depth.')
    cfg['period_um'] = [_number(value,'period_um',positive=True) for value in period]
    if not isinstance(cfg.get('parameter_source'),str) or not cfg['parameter_source'].strip():
        _bad('parameter_source', 'Document the material data and ideal interface assumptions.')
    materials = cfg.get('materials')
    required = ('epsilon_r','Nc_cm3','Nv_cm3','bandgap_eV','affinity_eV','electron_mobility_cm2_Vs','hole_mobility_cm2_Vs')
    optional = ('B_cm3_s','C_cm6_s','tau_s')
    if not isinstance(materials,dict) or not materials:
        _bad('materials', 'Supply at least one explicit semiconductor material.')
    for identity, material in materials.items():
        field = 'materials.'+identity
        if not isinstance(material,dict) or set(material)-set(required+optional+('kind','source')):
            _bad(field,'Unsupported material property fields.',identity)
        material.setdefault('kind','semiconductor')
        if material['kind'] != 'semiconductor':
            _bad(field+'.kind','This conformal model currently supports semiconductor layers and air inclusions.',identity)
        for key in required:
            material[key] = _number(material.get(key),field+'.'+key,positive=key!='affinity_eV')
        for key in optional:
            material[key] = _number(material.get(key,0.),field+'.'+key,nonnegative=True)
    layers = cfg.get('layers')
    if not isinstance(layers,list) or not layers:
        _bad('layers','Supply an editable layered stack.')
    identities = set()
    for index,layer in enumerate(layers):
        field = 'layers.'+str(index)
        if not isinstance(layer,dict) or set(layer)-{'id','name','thickness_um','material','donors_cm3','acceptors_cm3','patterned'}:
            _bad(field,'Unsupported layer fields.')
        identity = layer.get('id')
        if not isinstance(identity,str) or not identity or identity in identities:
            _bad(field+'.id','Every layer needs a unique stable ID.')
        identities.add(identity)
        if layer.get('material') not in materials:
            _bad(field+'.material','Select a supplied semiconductor material.',identity)
        layer['thickness_um'] = _number(layer.get('thickness_um'),field+'.thickness_um',positive=True)
        for key in ('donors_cm3','acceptors_cm3'):
            layer[key] = _number(layer.get(key,0.),field+'.'+key,nonnegative=True)
        layer.setdefault('patterned',False)
        if not isinstance(layer['patterned'],bool):
            _bad(field+'.patterned','Patterned must be true or false.',identity)
    shapes = cfg.setdefault('inclusions',[])
    if not isinstance(shapes,list):
        _bad('inclusions','Inclusions must be an editable list.')
    width,depth = cfg['period_um']; domain = box(-width/2,-depth/2,width/2,depth/2)
    polygons = []; identities = set()
    for index,shape in enumerate(shapes):
        field = 'inclusions.'+str(index)
        if not isinstance(shape,dict):_bad(field,'An inclusion must be an object.')
        identity = shape.get('id')
        if not isinstance(identity,str) or not identity or identity in identities:
            _bad(field+'.id','Every inclusion needs a unique stable ID.')
        identities.add(identity)
        if shape.get('shape')=='circle':
            if set(shape)-{'id','shape','center_um','radius_um'}:_bad(field,'Unsupported circle fields.',identity)
            center=shape.get('center_um')
            if not isinstance(center,list) or len(center)!=2:_bad(field+'.center_um','Enter two center coordinates.',identity)
            shape['center_um']=[_number(v,field+'.center_um') for v in center]
            shape['radius_um']=_number(shape.get('radius_um'),field+'.radius_um',positive=True)
            polygon=Point(*shape['center_um']).buffer(shape['radius_um'],quad_segs=128)
        elif shape.get('shape')=='polygon':
            if set(shape)-{'id','shape','vertices_um'}:_bad(field,'Unsupported polygon fields.',identity)
            vertices=shape.get('vertices_um')
            if not isinstance(vertices,list) or len(vertices)<3 or any(not isinstance(v,list) or len(v)!=2 for v in vertices):
                _bad(field+'.vertices_um','Enter at least three x,y vertices.',identity)
            shape['vertices_um']=[[_number(v,field+'.vertices_um') for v in point] for point in vertices]
            polygon=Polygon(shape['vertices_um'])
        else:_bad(field+'.shape','Select circle or polygon.',identity)
        if not polygon.is_valid or polygon.area<=0 or not domain.contains(polygon) or polygon.distance(domain.boundary)<=min(width,depth)*1e-7:
            _bad(field,'An inclusion must be valid and strictly inside the periodic cell.',identity)
        if any(polygon.intersects(other) for other in polygons):_bad(field,'Inclusions may not touch or overlap.',identity)
        polygons.append(polygon)
    cfg['temperature_K']=_number(cfg.get('temperature_K',300.),'temperature_K',positive=True)
    cfg['void_epsilon_r']=_number(cfg.get('void_epsilon_r',1.),'void_epsilon_r',positive=True)
    cfg.setdefault('swept_contact','top')
    if cfg['swept_contact'] not in ('top','bottom'):_bad('swept_contact','Select top or bottom.')
    if not isinstance(cfg.get('biases_V'),list) or not cfg['biases_V']:_bad('biases_V','Supply an explicit bias sequence.')
    cfg['biases_V']=[_number(v,'biases_V') for v in cfg['biases_V']]
    for key,default in [('tolerance_V',2e-9),('max_bias_step_V',.05)]:
        cfg[key]=_number(cfg.get(key,default),key,positive=True)
    cfg['maximum_iterations']=_number(cfg.get('maximum_iterations',80),'maximum_iterations',positive=True,integer=True)
    mesh=cfg.get('mesh')
    defaults=dict(edge_segments=4,circle_segments=16,xy_size_um=min(width,depth)/4,z_max_step_um=min(row['thickness_um'] for row in layers)/2,maximum_tetrahedra=200000)
    if not isinstance(mesh,dict) or set(mesh)-set(defaults):_bad('mesh','Unsupported mesh fields.')
    cfg['mesh']=dict(defaults,**mesh)
    for key,value in cfg['mesh'].items():
        cfg['mesh'][key]=_number(value,'mesh.'+key,positive=True,integer=key in ('edge_segments','circle_segments','maximum_tetrahedra'))
    if cfg['mesh']['edge_segments']<2:_bad('mesh.edge_segments','Use at least two segments per cell edge.')
    if cfg['mesh']['circle_segments']<8 or cfg['mesh']['circle_segments']%4:_bad('mesh.circle_segments','Circle segments must be a multiple of four, at least eight.')
    cfg['runtime']=validate_runtime(cfg.get('runtime'))
    return cfg


def execute(prepared,directory,emit=lambda event:None,cancelled=lambda:False):
    from research_physics_runtime import run_worker
    return run_worker(prepared,Path(directory),emit,cancelled,worker_name='pcsel_transport_worker.py')


def example_settings():
    """Explicit analytic demo, never selected automatically by the solver."""
    return dict(period_um=[.3,.4],layers=[dict(id='bulk',thickness_um=1.,material='demo',donors_cm3=1e16,patterned=True)],
        materials=dict(demo=dict(epsilon_r=12.9,Nc_cm3=1e18,Nv_cm3=1e19,bandgap_eV=1.4,affinity_eV=4.,
            electron_mobility_cm2_Vs=100.,hole_mobility_cm2_Vs=20.)),
        inclusions=[dict(id='hole',shape='circle',center_um=[0.,0.],radius_um=.04)],
        biases_V=[0.,.01],temperature_K=300.,swept_contact='top',
        mesh=dict(edge_segments=3,circle_segments=16,xy_size_um=.08,z_max_step_um=.25),
        parameter_source='Illustrative homogeneous parabolic-band conductor for analytic q mu n A/L verification; not measured PCSEL parameters.')
