"""Editable PCSEL optical studies generalized from the recovered research.

Vertical TE, four-wave coupling, finite outgoing cavities and Fraunhofer beams
retain their distinct approximations. Geometry is in the saved input, never
read from an experiment directory. See arXiv:1107.1772 for the CWT formulation.
"""
from __future__ import annotations

import copy
import json
import math
import itertools
from pathlib import Path

import numpy as np
from scipy.linalg import eigh_tridiagonal, solve_banded
from scipy.special import j1

from input_diagnostics import InputValidationError, diagnostic

LIMITATIONS=[
    'Vertical and coupled-wave models use nondispersive positive real indices and a square periodic lattice.',
    'Four-basic-wave TE coupling uses a local longitudinal closure; it is not a full-vector Maxwell solver.',
    'Finite modes use a rectangular aperture with zero incoming basic waves. A single resolution does not establish convergence.',
    'Far fields use the paraxial Fraunhofer approximation with a unit-power basis. Absolute display power requires a supplied calibration; passive modes do not predict laser output.',
    'Reduced aperture electrothermal/rate calculations use explicit source-bound load anchors, not a new three-dimensional drift-diffusion solve.',
]
CAPABILITIES=dict(label='PCSEL optical and aperture studies',dimensions=[1,2],optional_runtime=False,
    models=['vertical','cwt','finite','beam','aperture','gme','rcwa_poles'],limitations=LIMITATIONS)
FIELD_SCHEMA=[
    dict(path='model',label='Physical model',type='choice',options=CAPABILITIES['models'],default='vertical',section='study'),
    dict(path='lattice_nm',label='Square lattice period',type='number',unit='nm',required=True,section='geometry'),
    dict(path='layers',label='Layers, top to bottom',type='array',required=True,section='geometry'),
    dict(path='shapes',label='Patterned inclusions',type='array',default=[],section='geometry'),
    dict(path='inclusion_index',label='Inclusion refractive index',type='number',default=1.,section='materials'),
    dict(path='top_index',label='Top half-space index',type='number',default=1.,section='materials'),
    dict(path='bottom_index',label='Bottom half-space index',type='number',required=True,section='materials'),
    dict(path='grid_nm',label='Vertical grid spacing',type='number',unit='nm',default=2.,section='accuracy'),
    dict(path='pad_nm',label='Vertical boundary padding',type='number',unit='nm',default=4000.,section='accuracy'),
    dict(path='vertical_formulation',label='Vertical reference convention',type='choice',options=['fixed_period','reference_wavelength'],default='fixed_period',section='accuracy'),
    dict(path='reference_wavelength_nm',label='Reference design wavelength',type='number',unit='nm',default=None,section='accuracy'),
    dict(path='vertical_boundary',label='Vertical profile boundary',type='choice',options=['padded_halfspaces','finite_stack_dirichlet'],default='padded_halfspaces',section='accuracy'),
    dict(path='vertical_mode_selection',label='Vertical mode selection',type='choice',options=['lowest_frequency','largest_qw_overlap','core_overlap','mode_index'],default='lowest_frequency',section='accuracy'),
    dict(path='vertical_mode_index',label='Explicit vertical mode index',type='integer',default=0,section='accuracy'),
    dict(path='vertical_mode_candidates',label='Vertical candidate modes',type='integer',default=8,section='accuracy'),
    dict(path='harmonics',label='Coupling harmonic order',type='integer',default=8,section='accuracy'),
    dict(path='radiation_boundary',label='External radiation interfaces',type='choice',options=['external_interfaces','matched_external'],default='external_interfaces',section='solver'),
    dict(path='paper_study',label='Paper source and reconstruction assumptions',type='object',default={},section='study'),
    dict(path='green_model',label='Radiation Green function',type='choice',options=['local','layer_resolved'],default='layer_resolved',section='solver'),
    dict(path='aperture_um',label='Aperture width and height',type='array',unit='um',default=[200.,200.],section='geometry'),
    dict(path='collocation_order',label='Finite-cavity collocation order',type='integer',default=12,section='accuracy'),
    dict(path='beam_grid',label='Near-field samples per axis',type='integer',default=128,section='accuracy'),
    dict(path='beam_padding',label='FFT zero-padding factor',type='integer',default=4,section='accuracy'),
    dict(path='beam_mode_count',label='Number of accepted beam modes',type='integer',default=1,section='outputs'),
    dict(path='beam_mode',label='Finite mode number (-1 selects lowest accepted loss)',type='integer',default=-1,section='outputs'),
    dict(path='beam_normalization',label='Beam normalization',type='choice',options=['unit_power','peak','calibrated_power'],default='unit_power',section='outputs'),
    dict(path='beam_power_W',label='Calibrated emitted power',type='number',unit='W',section='outputs'),
    dict(path='beam_power_source',label='Emitted-power calibration source',type='string',default='',section='outputs'),
    dict(path='beam_saved_run',label='Compatible saved finite-mode folder (optional)',type='string',default='',section='outputs'),
    dict(path='gmax',label='GME reciprocal cutoff',type='number',default=3.1,section='accuracy'),
    dict(path='guided_modes',label='GME guided mode indices',type='array',default=[0],section='solver'),
    dict(path='num_modes',label='Number of GME modes',type='integer',default=4,section='solver'),
    dict(path='kpoints',label='GME wavevectors in 2 pi / a',type='array',default=[[0.,0.]],section='solver'),
    dict(path='basis',label='RCWA Fourier basis',type='integer',default=49,section='accuracy'),
    dict(path='pole_seeds',label='Complex resonance seeds [real, imaginary]',type='array',default=[],section='solver'),
    dict(path='pole_bounds',label='Pole search bounds [[real min,max],[imaginary min,max]]',type='array',default=[[.001,2.],[-.5,-1e-12]],section='solver'),
    dict(path='pole_excitation',label='Incident s and p amplitudes [[real,imag],[real,imag]]',type='array',default=[[1.,0.],[0.,.37]],section='solver'),
    dict(path='probe',label='RCWA probe [x/a,y/a,z_nm]',type='array',default=[.113,.179,0.],section='outputs'),
    dict(path='pole_field_grid',label='Pole-residue field samples per cell axis',type='integer',default=24,section='outputs'),
    dict(path='pole_field_z_nm',label='Pole field depths (empty uses probe depth)',type='array',default=[],unit='nm',section='outputs'),
    dict(path='pole_detuning',label='Maximum imaginary residue detuning',type='number',default=1e-8,section='accuracy'),
    dict(path='aperture',label='Reduced electrical, carrier and thermal parameters',type='object',default={},section='physics'),
    dict(path='runtime',label='Optional GME Python runtime',type='object',default={},section='runtime'),
    dict(path='parameter_sweep',label='Geometry and accuracy sweep',type='object',section='sweep'),
]


def _model_provenance(model, cfg=None):
    """Fresh method metadata for this run, not the catalogue of all PCSEL models."""
    cwt = dict(title='Liang et al., coupled-wave model for square-lattice PC lasers (2011)',
        url='https://arxiv.org/abs/1107.1772', doi='10.1103/PhysRevB.84.195119')
    gme = dict(title='Minkov et al., guided-mode expansion and Legume (2020)',
        url='https://arxiv.org/abs/2003.00379', doi='10.1021/acsphotonics.0c00327')
    rcwa = dict(title='Liu and Fan, S4 electromagnetic solver (2012)',
        url='https://doi.org/10.1016/j.cpc.2012.04.026', doi='10.1016/j.cpc.2012.04.026')
    real_indices = 'The supplied optical indices are positive, real and nondispersive; the cell uses a square lattice.'
    cfg = cfg or {}
    reference_wavelength = cfg.get('vertical_formulation', 'fixed_period') == 'reference_wavelength'
    vertical = 'The scalar TE profile uses averaged patterned-layer permittivity. '
    vertical += ('At the supplied reference wavelength it solves for beta and derives a = 2 pi / beta. '
        if reference_wavelength else 'At the supplied period it fixes beta = 2 pi / a and solves for wavelength. ')
    selection = cfg.get('vertical_mode_selection', 'lowest_frequency')
    vertical += {
        'lowest_frequency': ('It selects the first candidate (largest propagation constant at the supplied wavelength). '
            if reference_wavelength else 'It selects the lowest-frequency candidate. '),
        'largest_qw_overlap': 'It selects the candidate with largest integrated QW overlap. ',
        'core_overlap': 'It selects the candidate with largest integrated overlap in the marked QW and photonic-crystal layers. ',
        'mode_index': 'It selects the explicitly requested candidate index. ',
    }.get(selection, 'Vertical candidate selection must be checked. ')
    vertical += ('The finite-stack Dirichlet profile requires vertical grid refinement and boundary sensitivity checks; it does not establish substrate-leakage confinement.'
        if cfg.get('vertical_boundary', 'padded_halfspaces') == 'finite_stack_dirichlet'
        else 'Vertical grid spacing and half-space boundary padding require refinement.')
    coupling = 'Four-basic-wave TE coupling uses a local longitudinal closure; it is not a full-vector Maxwell solver.'
    finite = 'Finite modes use a rectangular aperture with zero incoming basic waves. A single collocation resolution does not establish convergence.'
    beam = 'Far fields use the paraxial Fraunhofer approximation with a unit-power basis. Absolute display power requires a supplied calibration; passive modes do not predict laser output.'
    metadata = {
        'vertical': dict(method='Scalar TE vertical waveguide eigenproblem',
            references=[dict(cwt, scope='Equation 15 provides the averaged waveguide equation. This implementation uses finite differences, not the paper transfer-matrix discretization.')],
            limitations=[real_indices, vertical]),
        'cwt': dict(method='Four-basic-wave TE coupled-wave model',
            references=[dict(cwt, scope='Underlying infinite-periodic coupled-wave framework; the local longitudinal closure remains an implementation approximation.')],
            limitations=[real_indices, vertical, coupling]),
        'finite': dict(method='Finite rectangular coupled-wave cavity with outgoing boundaries',
            references=[dict(cwt, scope='Underlying infinite-periodic coupling framework only. The finite-aperture collocation extension is not a reproduced result from this paper.')],
            limitations=[real_indices, vertical, coupling, finite]),
        'beam': dict(method='Paraxial Fraunhofer transform of finite coupled-wave aperture fields',
            references=[dict(cwt, scope='Underlying coupling used to obtain source modes only; this citation does not validate the finite-aperture or Fraunhofer implementation.')],
            limitations=[real_indices, vertical, coupling, finite, beam]),
        'aperture': dict(method='Reduced calibrated sheet, local QW rate and substrate heat model',
            references=[], limitations=[
                'Reduced aperture electrothermal/rate calculations use explicit source-bound load anchors, not a new three-dimensional drift-diffusion solve.',
                'The current-voltage load is calibrated to the saved load source and geometry; its temperature extrapolation is not independently calibrated.',
                'Local carrier/gain rates and substrate sheet heat conduction are reduced models. Grid and coupled-iteration convergence do not establish agreement with a laser experiment.']),
        'gme': dict(method='Legume guided-mode expansion of a patterned slab',
            references=[dict(gme, scope='Guided-mode expansion method and software provenance, not a matched numerical dataset.')],
            limitations=[real_indices,
                'The guided-mode basis is incomplete; reciprocal cutoff and included guided modes must be refined together.',
                'Radiation loss is perturbative. Reliable Q requires abs(frequency_imag) / frequency much less than one and convergence in reciprocal cutoff and guided-mode basis.',
                'Legume frequency_imag is a radiation-loss magnitude; Q = frequency / (2 abs(frequency_imag)). It is not the signed negative-imaginary outgoing pole convention.',
                'Passive infinite-periodic slab modes do not predict finite-aperture losses, injection thresholds or emitted laser power.']),
        'rcwa_poles': dict(method='S4 periodic RCWA driven-response complex-pole search',
            references=[dict(rcwa, scope='RCWA/S-matrix backend provenance. The driven-response pole search is an application implementation, not a reproduced benchmark from this paper.')],
            limitations=[real_indices,
                'Driven pole search can miss modes orthogonal to the probe or excitation, and repeated seeds can identify the same mode.',
                'Negative-imaginary outgoing poles require independent Fourier-basis, seed and residue-detuning checks; acceptance of a numerical root does not establish convergence.',
                'Pole-residue field amplitude is arbitrary. Passive infinite-periodic resonances do not predict finite-aperture losses, injection thresholds or absolute laser power.']),
    }[model]
    references = metadata.pop('references')
    return dict(metadata, method_references=references,
        reference=references[0]['url'] if references else None,
        reference_scope='Method provenance only; no numerical paper agreement or experimental validation is implied.'
            if references else 'No matched method-paper citation is assigned to this reduced implementation. The saved load_source supplies calibration provenance.')


def _gme_radiation_diagnostics(modes):
    """Expose loss scale without inventing a quantitative validity cutoff."""
    records = []
    for row in modes:
        frequency, loss = row.get('frequency'), row.get('frequency_imag')
        ratio = None
        if isinstance(frequency, (int, float)) and isinstance(loss, (int, float)):
            if math.isfinite(frequency) and frequency > 0 and math.isfinite(loss):
                ratio = abs(loss) / frequency
        records.append(dict(k_index=row.get('k_index'), band=row.get('band'),
            abs_frequency_imag_over_frequency=ratio))
    ratios = [row['abs_frequency_imag_over_frequency'] for row in records
        if row['abs_frequency_imag_over_frequency'] is not None]
    maximum = max(ratios) if ratios else None
    observed = f'{maximum:.6g} ({maximum:.3%})' if maximum is not None else 'unavailable'
    return dict(method='Perturbative radiation correction',
        modes=records, maximum_abs_frequency_imag_over_frequency=maximum,
        invalid_ratio_count=len(records)-len(ratios), validity_established=False,
        acceptance_threshold=None,
        warning='Q is a perturbative estimate. Largest abs(frequency_imag) / frequency = '+observed+
            '. Reliable Q requires this ratio much less than one and convergence in reciprocal cutoff and guided-mode basis. No numerical validity threshold or convergence pass is assigned.',
        source='https://legume.readthedocs.io/en/v1.0.3/generated/legume.GuidedModeExp.compute_rad.html')


def active_input_paths(model):
    """Inputs consumed by this physical model; other drafts remain editable."""
    common = {'model', 'lattice_nm', 'layers', 'shapes', 'inclusion_index',
              'top_index', 'bottom_index', 'parameter_sweep', 'paper_study'}
    vertical = {'grid_nm', 'pad_nm', 'vertical_boundary', 'vertical_mode_selection', 'vertical_mode_candidates', 'vertical_mode_index', 'vertical_formulation', 'reference_wavelength_nm'}
    coupling = vertical | {'harmonics', 'green_model', 'radiation_boundary'}
    finite = coupling | {'aperture_um', 'collocation_order'}
    models = {
        'vertical': vertical, 'cwt': coupling, 'finite': finite,
        'beam': finite | {'beam_grid', 'beam_padding', 'beam_mode', 'beam_normalization',
                         'beam_power_W', 'beam_power_source', 'beam_saved_run', 'beam_mode_count'},
        'aperture': {'aperture_um', 'aperture'},
        'gme': {'gmax', 'guided_modes', 'num_modes', 'kpoints', 'runtime'},
        'rcwa_poles': {'basis', 'pole_seeds', 'pole_bounds', 'pole_excitation', 'probe',
                       'pole_field_grid', 'pole_field_z_nm', 'pole_detuning'},
    }
    return common | models.get(model, set())


def paper_example(kind='hole',shape='CC',fill=.16):
    """An explicit editable starting deck; no solver selects it implicitly."""
    if kind not in ('hole','pillar') or shape not in ('CC','RIT'):
        raise ValueError('Select hole/pillar and CC/RIT for this recovered example.')
    if kind=='hole':
        sequence=[('contact',100,3.524),('p-cladding',1500,3.307),('GaAs',20,3.524),
            ('PC',118,3.524),('GaAs',22,3.524),('cladding',40,3.279),('spacer',40,3.524)]
    else:sequence=[('PC1',100,3.524),('PC2',400,3.307),('spacer',40,3.524)]
    sequence += [('QW',8,3.6),('barrier',20,3.524),('QW',8,3.6),('barrier',20,3.524),
        ('QW',8,3.6),('spacer',30,3.524),('n-cladding',1500,3.307)]
    layers=[dict(id='layer-'+str(i),name=name,thickness_nm=d,index=n,qw=name=='QW',patterned=name.startswith('PC')) for i,(name,d,n) in enumerate(sequence)]
    if shape=='CC':
        shapes=[dict(id='circle-'+str(i),shape='circle',center=[center,center],radius=float(np.sqrt(part*fill/np.pi)))
            for i,(center,part) in enumerate([(-1/6,.75),(1/6,.25)])]
    else:
        b=np.sqrt(2*fill);shapes=[dict(id='triangle',shape='polygon',vertices=[[-b/3,-b/3],[2*b/3,-b/3],[-b/3,2*b/3]])]
    return dict(model='vertical',lattice_nm=295.,layers=layers,shapes=shapes,top_index=1.,bottom_index=3.307,
        inclusion_index=1.,grid_nm=1.,pad_nm=4000.,harmonics=8,green_model='layer_resolved',
        aperture_um=[200.,200.],collocation_order=12)


def _error(field,message,object_id=''):
    raise InputValidationError([diagnostic(message,workspace='research_studies',section='inputs',
        field=field,object_id=object_id,code='pcsel.input')])


def _number(value,field,minimum=None,integer=False,object_id=''):
    try:v=float(value)
    except (TypeError,ValueError,OverflowError):_error(field,'Enter a finite number.',object_id)
    if isinstance(value,bool) or not math.isfinite(v) or minimum is not None and v<minimum or integer and v!=int(v):
        _error(field,'Enter a finite '+('integer' if integer else 'number')+(f' of at least {minimum:g}.' if minimum is not None else '.'),object_id)
    return int(v) if integer else v


def _shape(shape,index):
    if not isinstance(shape,dict):_error('shapes','Each inclusion must be an object.')
    result=copy.deepcopy(shape);result.setdefault('id','shape-'+str(index))
    if not isinstance(result['id'],str) or not result['id']:_error('shapes','Every inclusion needs a nonempty stable ID.')
    kind=result.get('shape')
    if kind=='triangle':
        from pcsel_paper_studies import triangle_vertices, periodic_triangle_overlap
        try:result['vertices']=triangle_vertices(result)
        except (ValueError,TypeError,OverflowError) as exc:_error('shapes',str(exc),result['id'])
        if periodic_triangle_overlap(result['vertices']):
            _error('shapes','This triangle overlaps its periodically translated neighbours; reduce base length or angle.',result['id'])
    if kind=='circle':
        center=result.get('center',[0.,0.])
        if not isinstance(center,list) or len(center)!=2:_error('shapes','A circle center needs x and y.',result['id'])
        result['center']=[_number(v,'shapes.'+result['id']+'.center.'+str(i),object_id=result['id']) for i,v in enumerate(center)]
        result['radius']=_number(result.get('radius'),'shapes.'+result['id']+'.radius',1e-12,object_id=result['id'])
        c=np.array(result['center']);r=result['radius'];bounds=np.r_[c-r,c+r]
    elif kind in ('polygon','triangle'):
        try:points=np.asarray(result.get('vertices',[]),dtype=float)
        except (ValueError,TypeError):_error('shapes','Polygon vertices must be finite x/y pairs.',result['id'])
        if points.ndim!=2 or points.shape[1]!=2 or len(points)<3 or not np.isfinite(points).all():
            _error('shapes','A polygon needs at least three finite x/y vertices.',result['id'])
        edge=np.roll(points,-1,axis=0)-points
        turn=np.cross(edge,np.roll(edge,-1,axis=0))
        if not (np.all(turn>=-1e-12) or np.all(turn<=1e-12)):
            _error('shapes','This CWT adapter accepts convex, non-self-intersecting polygons.',result['id'])
        area=.5*np.sum(points[:,0]*np.roll(points[:,1],-1)-points[:,1]*np.roll(points[:,0],-1))
        if abs(area)<1e-12:_error('shapes','Polygon area must be positive.',result['id'])
        if area<0:points=points[::-1]
        # A star polygon can have equal-sign local turns while crossing itself.
        # Every vertex must lie in the interior half-plane of every edge.
        for a,b in zip(points,np.roll(points,-1,axis=0)):
            delta=b-a;offset=points-a
            if np.linalg.norm(delta)<1e-12 or np.any(delta[0]*offset[:,1]-delta[1]*offset[:,0]<-1e-12):
                _error('shapes','Use a convex polygon with distinct, non-crossing vertices.',result['id'])
        result['vertices']=points.tolist();bounds=np.r_[points.min(axis=0),points.max(axis=0)]
    else:_error('shapes','Choose circle, convex polygon, or parameterized triangle.',result['id'])
    if kind!='triangle' and (np.any(bounds[:2]<-.5-1e-12) or np.any(bounds[2:]>.5+1e-12)):
        _error('shapes','Inclusions must fit inside the editable cell [-0.5,0.5] in both directions.',result['id'])
    result['_bounds']=bounds.tolist()
    return result


def shape_fourier(shape,q):
    """Area-normalized analytic Fourier transform, exp(-2 pi i q.r)."""
    k=2*np.pi*np.asarray(q,dtype=float);norm=np.linalg.norm(k)
    if shape['shape']=='circle':
        r=shape['radius'];area=np.pi*r*r
        return area*(1. if norm==0 else 2*j1(norm*r)/(norm*r))*np.exp(-1j*k@shape['center'])
    points=np.asarray(shape['vertices']);edges=np.roll(points,-1,axis=0)-points
    if norm==0:return .5*np.sum(points[:,0]*np.roll(points[:,1],-1)-points[:,1]*np.roll(points[:,0],-1))
    middle=points+edges/2
    return np.sum(1j*(k[0]*edges[:,1]-k[1]*edges[:,0])/norm**2*
                  np.exp(-1j*(middle@k))*np.sinc((edges@k)/(2*np.pi)))


def prepare(project,settings):
    if not isinstance(settings,dict):_error('model','PCSEL settings must be an object.')
    allowed={row['path'] for row in FIELD_SCHEMA}
    if set(settings)-allowed:_error('model','Unsupported PCSEL settings: '+', '.join(sorted(set(settings)-allowed)))
    if 'parameter_sweep' in settings:
        return _prepare_sweep(project,settings)
    cfg={row['path']:copy.deepcopy(row['default']) for row in FIELD_SCHEMA if 'default' in row}
    cfg.update(copy.deepcopy(settings))
    if cfg['model'] not in CAPABILITIES['models']:_error('model','Select a supported PCSEL model.')
    active = active_input_paths(cfg['model'])
    vertical_grid = cfg['model'] in ('vertical', 'cwt', 'finite', 'beam')
    for field in ('lattice_nm','inclusion_index','top_index','bottom_index','grid_nm','pad_nm','gmax'):
        if field in active:cfg[field]=_number(cfg.get(field),field,1e-12)
    for field,minimum in [('harmonics',1),('collocation_order',4),('beam_grid',16),('beam_padding',1),('num_modes',1),('basis',3)]:
        if field in active:cfg[field]=_number(cfg[field],field,minimum,True)
    if 'collocation_order' in active and cfg['collocation_order']>60:
        _error('collocation_order','Use at most 60 until a memory budget is explicitly provided.')
    if cfg['model']=='beam':
        if cfg['beam_grid']*cfg['beam_padding']>4096:_error('beam_grid','The padded field may have at most 4096 samples per axis.')
        cfg['beam_mode']=_number(cfg['beam_mode'],'beam_mode',-1,True)
        if cfg['beam_normalization'] not in ('unit_power','peak','calibrated_power'):_error('beam_normalization','Select a beam normalization.')
        if cfg['beam_normalization']=='calibrated_power':
            cfg['beam_power_W']=_number(cfg.get('beam_power_W'),'beam_power_W',1e-30)
            if not isinstance(cfg['beam_power_source'],str) or not cfg['beam_power_source'].strip():_error('beam_power_source','Identify the emitted-power calibration; passive modes do not supply watts.')
        if not isinstance(cfg['beam_saved_run'],str):_error('beam_saved_run','Supply a saved run directory or leave it blank.')
    if 'harmonics' in active and cfg['harmonics']>30:_error('harmonics','Use a coupling harmonic order no larger than 30.')
    if 'green_model' in active and cfg['green_model'] not in ('local','layer_resolved'):_error('green_model','Select local or layer-resolved radiation.')
    if vertical_grid:
        if cfg['vertical_formulation'] not in ('fixed_period','reference_wavelength'):_error('vertical_formulation','Choose fixed period or a stated reference wavelength.')
        if cfg['vertical_formulation']=='reference_wavelength':cfg['reference_wavelength_nm']=_number(cfg['reference_wavelength_nm'],'reference_wavelength_nm',1e-12)
        if cfg['vertical_boundary'] not in ('padded_halfspaces','finite_stack_dirichlet'):_error('vertical_boundary','Choose a supported vertical boundary.')
        if cfg['vertical_mode_selection'] not in ('lowest_frequency','largest_qw_overlap','core_overlap','mode_index'):_error('vertical_mode_selection','Choose a supported vertical mode selection.')
        cfg['vertical_mode_candidates']=_number(cfg['vertical_mode_candidates'],'vertical_mode_candidates',1,True)
        cfg['vertical_mode_index']=_number(cfg['vertical_mode_index'],'vertical_mode_index',0,True)
        if cfg['vertical_mode_index']>=cfg['vertical_mode_candidates']:_error('vertical_mode_index','Explicit mode index must be smaller than the candidate count.')
        if cfg['vertical_mode_candidates']>32:_error('vertical_mode_candidates','Use at most 32 candidate modes.')
    if 'radiation_boundary' in active:
        if cfg['radiation_boundary'] not in ('external_interfaces','matched_external'):_error('radiation_boundary','Choose external interfaces or matched semiconductor ports.')
        if cfg['radiation_boundary']=='matched_external' and cfg['green_model']!='layer_resolved':_error('radiation_boundary','Matched external ports require the layer-resolved Green function.')
    if not isinstance(cfg['paper_study'],dict):_error('paper_study','Paper provenance must be an object.')
    if cfg['model']=='beam':
        cfg['beam_mode_count']=_number(cfg['beam_mode_count'],'beam_mode_count',1,True)
        if cfg['beam_mode_count']>8:_error('beam_mode_count','Select at most eight accepted modes per beam run.')
    layers=cfg.get('layers')
    if not isinstance(layers,list) or not layers:_error('layers','Add the editable layer stack, top to bottom.')
    ids=set()
    for i,row in enumerate(layers):
        if not isinstance(row,dict):_error('layers','Each layer must be an object.')
        if set(row)-{'id','name','thickness_nm','index','qw','patterned'}:_error('layers','Unsupported layer properties.')
        row.setdefault('id','layer-'+str(i));row.setdefault('name',row['id'])
        if not isinstance(row['id'],str) or not row['id']:_error('layers','Every layer needs a nonempty stable ID.')
        if row['id'] in ids:_error('layers','Layer IDs must be unique.',row['id'])
        ids.add(row['id'])
        for key in ('thickness_nm','index'):row[key]=_number(row.get(key),'layers.'+row['id']+'.'+key,1e-12,object_id=row['id'])
        for key in ('qw','patterned'):
            row.setdefault(key,False)
            if not isinstance(row[key],bool):_error('layers','QW and patterned flags must be true or false.',row['id'])
        if vertical_grid and row['thickness_nm']<cfg['grid_nm']:_error('grid_nm','Resolve every layer with at least one vertical cell; refine the spacing.')
    if vertical_grid and (sum(row['thickness_nm'] for row in layers)+2*cfg['pad_nm'])/cfg['grid_nm']>250000:
        _error('grid_nm','This vertical mesh exceeds 250,000 samples; adjust spacing or padding.')
    if not isinstance(cfg['shapes'],list):_error('shapes','Inclusions must be an array.')
    cfg['shapes']=[_shape(row,i) for i,row in enumerate(cfg['shapes'])]
    if len({r['id'] for r in cfg['shapes']})!=len(cfg['shapes']):
        _error('shapes','Inclusion IDs must be unique.')
    for i,a in enumerate(cfg['shapes']):
        for b in cfg['shapes'][i+1:]:
            if a['shape']==b['shape']=='circle':
                overlap=np.linalg.norm(np.array(a['center'])-b['center'])<a['radius']+b['radius']-1e-12
            else:
                aa,bb=np.array(a['_bounds']),np.array(b['_bounds'])
                overlap=np.all(np.minimum(aa[2:],bb[2:])-np.maximum(aa[:2],bb[:2])>1e-12)
            if overlap:_error('shapes','Inclusions must be disjoint. Polygon pairs also require disjoint bounding boxes.',a['id'])
    cfg['fill_fraction']=float(sum(shape_fourier(shape,[0,0]).real for shape in cfg['shapes']))
    if cfg['fill_fraction']>=1:_error('shapes','Inclusion area must be smaller than one unit cell.')
    if cfg['model'] in ('cwt','finite','beam','rcwa_poles','gme') and (not cfg['shapes'] or not any(r['patterned'] for r in layers)):
        _error('shapes','This model needs inclusions and at least one patterned layer.')
    if 'aperture_um' in active:
        if not isinstance(cfg['aperture_um'],list) or len(cfg['aperture_um'])!=2:_error('aperture_um','Enter aperture width and height.')
        cfg['aperture_um']=[_number(v,'aperture_um',1e-9) for v in cfg['aperture_um']]
    if cfg['model']=='aperture':
        from pcsel_aperture import prepare_parameters
        cfg['aperture']=prepare_parameters(cfg['aperture'],cfg['aperture_um'],cfg)
    if cfg['model']=='gme':
        from research_physics_runtime import validate_runtime
        cfg['runtime']=validate_runtime(cfg['runtime'])
        if not isinstance(cfg['guided_modes'],list) or not cfg['guided_modes']:_error('guided_modes','Select at least one guided-mode index.')
        cfg['guided_modes']=[_number(v,'guided_modes',0,True) for v in cfg['guided_modes']]
        if not isinstance(cfg['kpoints'],list) or not cfg['kpoints']:_error('kpoints','Supply at least one x/y wavevector.')
        for point in cfg['kpoints']:
            if not isinstance(point,list) or len(point)!=2:_error('kpoints','Each GME wavevector needs two components.')
            point[:]=[_number(v,'kpoints') for v in point]
    if cfg['model']=='rcwa_poles':
        if not isinstance(cfg['pole_seeds'],list) or not cfg['pole_seeds']:_error('pole_seeds','Enter initial complex resonance frequencies [real, negative imaginary].')
        seeds=[]
        for seed in cfg['pole_seeds']:
            if not isinstance(seed,list) or len(seed)!=2:
                _error('pole_seeds','Each pole seed needs [real, negative imaginary] frequencies.')
            pair=[_number(seed[0],'pole_seeds',1e-12),_number(seed[1],'pole_seeds')]
            if pair[1]>=0:_error('pole_seeds','Pole seeds require positive real and negative imaginary frequencies.')
            seeds.append(pair)
        cfg['pole_seeds']=seeds
        if not isinstance(cfg['probe'],list) or len(cfg['probe'])!=3:_error('probe','Enter x/a, y/a and physical z in nm.')
        cfg['probe']=[_number(v,'probe') for v in cfg['probe']]
        if not 0<=cfg['probe'][2]<=sum(row['thickness_nm'] for row in layers):_error('probe','Place the RCWA probe within the finite stack.')
        for key in ('pole_bounds','pole_excitation'):
            value=cfg[key]
            if not isinstance(value,list) or len(value)!=2 or any(not isinstance(v,list) or len(v)!=2 for v in value):
                _error(key,'Supply two pairs of finite numbers.')
            cfg[key]=[[_number(v,key) for v in pair] for pair in value]
        bounds=cfg['pole_bounds']
        if bounds[0][0]<=0 or bounds[1][1]>=0 or any(b<=a for a,b in bounds):
            _error('pole_bounds','Use increasing positive real bounds and increasing negative imaginary bounds.')
        if not any(v for pair in cfg['pole_excitation'] for v in pair):_error('pole_excitation','Supply at least one nonzero incident polarization amplitude.')
        if any(not all(bounds[j][0]<seed[j]<bounds[j][1] for j in (0,1)) for seed in cfg['pole_seeds']):
            _error('pole_seeds','Place every initial seed strictly inside the complex search bounds.')
        cfg['pole_field_grid']=_number(cfg['pole_field_grid'],'pole_field_grid',8,True)
        if cfg['pole_field_grid']>256:_error('pole_field_grid','Use at most 256 field samples per axis.')
        cfg['pole_detuning']=_number(cfg['pole_detuning'],'pole_detuning',1e-14)
        if not isinstance(cfg['pole_field_z_nm'],list) or len(cfg['pole_field_z_nm'])>128:_error('pole_field_z_nm','Supply up to 128 field depths.')
        cfg['pole_field_z_nm']=[_number(v,'pole_field_z_nm',0) for v in cfg['pole_field_z_nm']] or [cfg['probe'][2]]
        if max(cfg['pole_field_z_nm'])>sum(row['thickness_nm'] for row in layers):_error('pole_field_z_nm','Field depths must lie within the finite stack.')
    return cfg


def _prepare_sweep(project,settings):
    """Validate every editable case before launching the first calculation."""
    sweep=settings['parameter_sweep']
    if not isinstance(sweep,dict) or set(sweep)-{'parameters','invalid_geometry','max_cases','variants'}:
        _error('parameter_sweep','Supply an object containing a parameters array.')
    if 'variants' in sweep:
        return _prepare_comparison_sweep(project,settings)
    axes=sweep.get('parameters')
    if not isinstance(axes,list) or not axes:
        _error('parameter_sweep','Add at least one sweep parameter with explicit values.')
    policy=sweep.get('invalid_geometry','error')
    if policy not in ('error','mask'):_error('parameter_sweep','Invalid geometry policy must be error or mask.')
    budget=_number(sweep.get('max_cases',128),'parameter_sweep',1,True)
    if budget>4096:_error('parameter_sweep','At most 4096 sweep cases are supported; split larger studies.')
    base={k:copy.deepcopy(v) for k,v in settings.items() if k!='parameter_sweep'}
    baseline=prepare(project,base)
    scalar={'lattice_nm','inclusion_index','top_index','bottom_index','grid_nm','pad_nm','harmonics',
            'collocation_order','beam_grid','beam_padding','gmax','num_modes','basis','vertical_mode_candidates'}
    setters=[];labels=[];values=[]
    for axis in axes:
        if not isinstance(axis,dict) or set(axis)-{'path','object_id','field','values'}:
            _error('parameter_sweep','Each parameter needs path, values and, for an object, object_id and field.')
        path=axis.get('path');ident=axis.get('object_id');field=axis.get('field');numbers=axis.get('values')
        if not isinstance(numbers,list) or not numbers or len(numbers)>128:
            _error('parameter_sweep','Each parameter needs 1 to 128 explicit values.')
        numbers=[_number(v,'parameter_sweep') for v in numbers]
        active = active_input_paths(baseline['model'])
        if path=='lattice_nm' and baseline.get('vertical_formulation')=='reference_wavelength':_error('parameter_sweep','Reference-wavelength mode derives the period. Use fixed-period mode for a period sweep.')
        if path in scalar | {'aperture_um'} and path not in active:
            _error('parameter_sweep','This sweep target is not used by the '+baseline['model']+' model: '+path)
        if baseline['model']=='vertical' and (path=='center_scale' or path=='shapes' and field in ('center_x','center_y')):
            _error('parameter_sweep','The vertical effective-index model does not depend on inclusion positions.')
        if path in ('fill_fraction','center_scale') and not ident and not field:
            if not baseline['shapes']:_error('parameter_sweep','Pattern sweeps require at least one inclusion.')
            if path=='fill_fraction' and any(v<=0 or v>=1 for v in numbers):
                _error('parameter_sweep','Requested fill fractions must be strictly between zero and one.')
            setter=(path,None,None);label=path
        elif path in scalar and not ident and not field:
            setter=(path,None,None);label=path
        elif path=='aperture_um' and field in ('width','height','side') and not ident:
            setter=(path,None,'side' if field=='side' else 0 if field=='width' else 1);label=path+'.'+field
        elif path in ('layers','shapes') and isinstance(ident,str):
            found=[i for i,row in enumerate(base.get(path,[])) if row.get('id')==ident]
            if len(found)!=1:_error('parameter_sweep','Select one existing object by its stable ID.',ident)
            row=base[path][found[0]]
            permitted={'thickness_nm','index'} if path=='layers' else ({'radius','center_x','center_y'} if row.get('shape')=='circle' else {'base_length','base_angle_deg','rotation_deg','center_x','center_y'} if row.get('shape')=='triangle' else set())
            if field not in permitted:_error('parameter_sweep','This object supports '+', '.join(sorted(permitted))+' sweep fields.',ident)
            setter=(path,found[0],field);label=path+'.'+ident+'.'+field
        else:_error('parameter_sweep','Select a supported scalar input, aperture dimension, layer index/thickness, or circle radius.')
        if label in labels:_error('parameter_sweep','Each input can appear only once in a sweep.')
        setters.append(setter);labels.append(label);values.append(numbers)
    if 'fill_fraction' in labels and any(path=='shapes' and key in ('radius','base_length','base_angle_deg') for path,_,key in setters):
        _error('parameter_sweep','Choose total fill fraction or individual area-changing shape parameters in one sweep, so each requested value stays exact.')
    if 'center_scale' in labels and any(path=='shapes' and key in ('center_x','center_y') for path,_,key in setters):
        _error('parameter_sweep','Choose collective center scaling or individual center coordinates in one sweep.')
    if 'aperture_um.side' in labels and any(k in labels for k in ('aperture_um.width','aperture_um.height')):_error('parameter_sweep','Use square side or independent width/height targets, not both.')
    count=math.prod(map(len,values))
    if count>budget:_error('parameter_sweep',f'This sweep has {count} cases, above its explicit budget of {budget}; raise the budget up to 4096 or split it.')
    cases=[]
    for combination in itertools.product(*values):
        raw=copy.deepcopy(base)
        for (path,index,key),value in zip(setters,combination):
            if path in ('fill_fraction','center_scale'):
                factor=math.sqrt(value/baseline['fill_fraction']) if path=='fill_fraction' else value
                for shape in raw['shapes']:
                    if shape['shape']=='circle':
                        if path=='fill_fraction':shape['radius']*=factor
                        else:shape['center']=(np.array(shape.get('center',[0.,0.]))*factor).tolist()
                    elif shape['shape']=='triangle':
                        if path=='fill_fraction':shape['base_length']*=factor
                        else:shape['center']=(np.array(shape.get('center',[0.,0.]))*factor).tolist()
                    else:
                        vertices=np.asarray(shape['vertices']);following=np.roll(vertices,-1,axis=0)
                        cross=vertices[:,0]*following[:,1]-vertices[:,1]*following[:,0]
                        center=np.sum((vertices+following)*cross[:,None],axis=0)/(3*cross.sum())
                        shape['vertices']=(center+(vertices-center)*factor if path=='fill_fraction' else vertices+(factor-1)*center).tolist()
            elif index is not None:
                if key in ('center_x','center_y'):raw[path][index].setdefault('center',[0.,0.])[0 if key=='center_x' else 1]=value
                else:raw[path][index][key]=value
            elif key=='side':raw[path]=[value,value]
            elif key is not None:raw.setdefault(path,[200.,200.])[key]=value
            else:raw[path]=value
        try:case=prepare(project,raw)
        except ValueError as exc:
            geometry_error=isinstance(exc,InputValidationError) and any(d.get('field')=='shapes' or d.get('field','').startswith('shapes.') for d in exc.diagnostics)
            if policy=='mask' and geometry_error:
                cases.append(dict(parameters=dict(zip(labels,combination)),prepared=None,status='invalid_geometry',error=str(exc)))
                continue
            _error('parameter_sweep','A requested case is invalid ('+', '.join(f'{k}={v:g}' for k,v in zip(labels,combination))+'): '+str(exc))
        cases.append(dict(parameters=dict(zip(labels,combination)),prepared=case))
    cfg=prepare(project,base)
    cfg['parameter_sweep']=dict(parameters=copy.deepcopy(axes),cases=cases,invalid_geometry=policy,max_cases=budget)
    return cfg


def _prepare_comparison_sweep(project,settings):
    """Compare explicitly editable variants at the same requested sweep points.

    Each variant is a collection of fixed, numeric overrides. Reuse the regular
    sweep validator so unsupported inputs and overlapping targets cannot bypass
    normal geometry, model relevance, or case-budget checks.
    """
    sweep=settings['parameter_sweep'];variants=sweep['variants'];axes=sweep.get('parameters')
    if not isinstance(variants,list) or not variants or len(variants)>16:
        _error('parameter_sweep','Supply 1 to 16 named comparison variants, or remove variants for an ordinary sweep.')
    if not isinstance(axes,list) or not axes:
        _error('parameter_sweep','Add at least one sweep parameter with explicit values.')
    budget=_number(sweep.get('max_cases',128),'parameter_sweep',1,True)
    if budget>4096:_error('parameter_sweep','At most 4096 sweep cases are supported; split larger studies.')
    counts=[]
    for axis in axes:
        if not isinstance(axis,dict) or not isinstance(axis.get('values'),list) or not axis['values']:
            _error('parameter_sweep','Each sweep parameter needs explicit values.')
        counts.append(len(axis['values']))
    total=math.prod(counts)*len(variants)
    if total>budget:
        _error('parameter_sweep',f'This comparison has {total} cases including all variants, above its explicit budget of {budget}.')
    names=set();cases=[]
    for variant in variants:
        if not isinstance(variant,dict) or set(variant)-{'name','overrides'}:
            _error('parameter_sweep','Each comparison variant needs name and overrides.')
        name=variant.get('name')
        if not isinstance(name,str) or not name.strip() or name!=name.strip() or name in names:
            _error('parameter_sweep','Comparison variant names must be nonempty, unique and have no surrounding whitespace.')
        names.add(name);overrides=variant.get('overrides')
        if not isinstance(overrides,list):_error('parameter_sweep','Variant overrides must be an array of explicit inputs.')
        following=copy.deepcopy(settings)
        following['parameter_sweep']={k:copy.deepcopy(v) for k,v in sweep.items() if k!='variants'}
        override_labels=set()
        for override in overrides:
            if not isinstance(override,dict) or set(override)-{'path','object_id','field','value'} or 'value' not in override:
                _error('parameter_sweep','Each variant override needs path, value and, for an object, object_id and field.')
            target={k:copy.deepcopy(v) for k,v in override.items() if k!='value'}
            target['values']=[override['value']]
            following['parameter_sweep']['parameters'].append(target)
            override_labels.add('.'.join(str(override[k]) for k in ('path','object_id','field') if override.get(k) is not None))
        try:prepared=_prepare_sweep(project,following)
        except InputValidationError as exc:
            _error('parameter_sweep',f'Comparison variant {name}: {exc}')
        for case in prepared['parameter_sweep']['cases']:
            case['parameters']={k:v for k,v in case['parameters'].items() if k not in override_labels}
            case['variant']=name
            if case.get('prepared') and case['prepared'].get('paper_study'):
                provenance=case['prepared']['paper_study']
                provenance['base_structure']=provenance.get('structure')
                provenance['structure']=name
                provenance['comparison_variant']=name
            cases.append(case)
    base={k:copy.deepcopy(v) for k,v in settings.items() if k!='parameter_sweep'}
    cfg=prepare(project,base)
    cfg['parameter_sweep']=dict(parameters=copy.deepcopy(axes),variants=copy.deepcopy(variants),cases=cases,
        invalid_geometry=sweep.get('invalid_geometry','error'),max_cases=budget)
    return cfg


def vertical(cfg):
    h=cfg['grid_nm'];length=sum(r['thickness_nm'] for r in cfg['layers'])
    finite_boundary=cfg.get('vertical_boundary','padded_halfspaces')=='finite_stack_dirichlet'
    if finite_boundary:h=length/max(4,math.ceil(length/h))
    z=h*np.arange(1,round(length/h)) if finite_boundary else np.arange(-cfg['pad_nm']+h/2,length+cfg['pad_nm'],h)
    if len(z)<3:_error('grid_nm','The vertical domain requires at least three interior nodes.')
    n=np.where(z<length,cfg['top_index'],cfg['bottom_index']).astype(float)
    qw=np.zeros(len(z),bool);pc=qw.copy();contrast=np.zeros_like(z);edge=0.
    f=cfg['fill_fraction']
    for row in cfg['layers']:
        mask=(z>=edge)&(z<edge+row['thickness_nm']);edge+=row['thickness_nm']
        epsilon=row['index']**2
        n[mask]=np.sqrt((1-f)*epsilon+f*cfg['inclusion_index']**2) if row['patterned'] else row['index']
        if row['qw']:qw|=mask
        if row['patterned']:pc|=mask;contrast[mask]=cfg['inclusion_index']**2-epsilon
    selection=cfg.get('vertical_mode_selection','lowest_frequency')
    count=min(cfg.get('vertical_mode_candidates',8),len(z)) if finite_boundary or selection!='lowest_frequency' else 1
    if selection=='largest_qw_overlap' and not qw.any():_error('layers','QW-overlap selection requires an explicitly marked quantum-well layer.')
    if selection=='core_overlap' and not (qw|pc).any():_error('layers','Core-overlap selection requires marked quantum-well or photonic-crystal layers.')
    reference=cfg.get('vertical_formulation','fixed_period')=='reference_wavelength'
    if reference:
        k=2*np.pi/cfg['reference_wavelength_nm']
        # At the supplied wavelength solve -Theta''-k0^2 eps Theta=-beta^2 Theta.
        eig,vec=eigh_tridiagonal(2/h**2-k*k*n*n,np.full(len(n)-1,-1/h**2),select='i',select_range=(0,count-1))
        physical=eig<0
        if not physical.any():_error('reference_wavelength_nm','No real propagation-constant candidate exists at this reference wavelength.')
        eig=eig[physical];vec=vec[:,physical];count=len(eig)
        fields=vec;wave_numbers=np.full(count,k);propagation=np.sqrt(-eig)
    else:
        beta=2*np.pi/cfg['lattice_nm']
        diag=(2/h**2+beta**2)/n**2;off=-1/h**2/(n[:-1]*n[1:])
        eig,vec=eigh_tridiagonal(diag,off,select='i',select_range=(0,count-1))
        fields=vec/n[:,None];wave_numbers=np.sqrt(eig);propagation=np.full(count,beta)
    fields/=np.sqrt(np.sum(fields**2,axis=0)*h)
    qw_overlap=np.sum(fields[qw,:]**2,axis=0)*h
    pc_overlap=np.sum(fields[pc,:]**2,axis=0)*h
    core_overlap=np.sum(fields[qw|pc,:]**2,axis=0)*h
    selected=int(np.argmax(qw_overlap)) if selection=='largest_qw_overlap' else int(np.argmax(core_overlap)) if selection=='core_overlap' else cfg.get('vertical_mode_index',0) if selection=='mode_index' else 0
    if selected>=count:_error('vertical_mode_index','Requested mode exceeds the available vertical propagating candidates.')
    def node_count(values):
        significant=values[abs(values)>np.max(abs(values))*1e-6]
        return int(np.count_nonzero(significant[:-1]*significant[1:]<0))
    field=fields[:,selected];k=float(wave_numbers[selected]);beta=float(propagation[selected])
    actual_period=float(2*np.pi/beta);freq=actual_period*k/(2*np.pi);neff=beta/k
    ng=float(np.sum(n*n*field**2)*h/neff)
    candidates=[dict(index=i,wavelength_nm=float(2*np.pi/wave_numbers[i]),effective_index=float(propagation[i]/wave_numbers[i]),
        lattice_nm=float(2*np.pi/propagation[i]),Gamma_QW=float(qw_overlap[i]),Gamma_PC=float(pc_overlap[i]),Gamma_core=float(core_overlap[i]),node_count=node_count(fields[:,i])) for i in range(count)]
    row=dict(effective_group_index=ng,group_index_assumption='Nondispersive supplied permittivities: ng=integral(epsilon*|Theta|^2 dz)/neff, normalized Theta. Author material dispersion is unavailable.',actual_grid_nm=h,
        frequency=float(freq),wavelength_nm=float(2*np.pi/k),effective_index=float(neff),effective_lattice_nm=actual_period,
        requested_lattice_nm=cfg['lattice_nm'],vertical_formulation=cfg.get('vertical_formulation','fixed_period'),
        Gamma_QW=float(qw_overlap[selected]),Gamma_PC=float(pc_overlap[selected]),Gamma_core=float(core_overlap[selected]),
        guided=bool(finite_boundary or neff>max(cfg['top_index'],cfg['bottom_index'])),
        vertical_boundary=cfg.get('vertical_boundary','padded_halfspaces'),
        confinement_scope='Finite-domain Dirichlet profile approximation; not proof of confinement against substrate leakage.' if finite_boundary else 'Effective index compared with supplied halfspaces.',
        selected_mode_index=selected,selected_node_count=node_count(field),mode_candidates=candidates,
        boundary_intensity_fraction=float((field[0]**2+field[-1]**2)*h))
    return row,dict(z_nm=z,index=n,field=field,intensity_per_nm=field**2,patterned=pc,contrast=contrast,grid_nm=h,candidate_fields=fields.T)


def coupling(cfg,profile,row,cancelled=lambda:False):
    a=row.get('effective_lattice_nm',cfg['lattice_nm']);h=profile.get('grid_nm',cfg['grid_nm']);beta=2*np.pi/a;k=2*np.pi*row['frequency']/a
    n=profile['index'];theta=profile['field'];contrast=profile['contrast'];pc=profile['patterned']
    vectors=np.array([[1,0],[-1,0],[0,1],[0,-1]]);pol=np.array([[0,1],[0,1],[1,0],[1,0]])
    ft={}
    def coefficient(q):
        key=tuple(q)
        if key not in ft:ft[key]=sum(shape_fourier(shape,q) for shape in cfg['shapes'])
        return ft[key]
    I1=np.sum(contrast*theta**2)*h;Ip=np.sum(contrast**2*theta**2/n**2)*h
    cache={};flux={}
    def green(q2):
        if q2 in cache:return cache[q2]
        if cfg['green_model']=='layer_resolved':
            matched=cfg.get('radiation_boundary')=='matched_external'
            radiation_mask=(profile['z_nm']>=0)&(profile['z_nm']<sum(r['thickness_nm'] for r in cfg['layers'])) if matched else np.ones(len(n),bool)
            rn=n[radiation_mask]
            source=(contrast*theta)[radiation_mask]
            if cfg.get('vertical_boundary')=='finite_stack_dirichlet':
                rn=np.r_[rn[0],rn,rn[-1]];source=np.r_[0.,source,0.]
            v=q2*beta**2-k*k*rn*rn
            def outgoing(value):
                t=1+h*h*value/2
                if value<0:
                    if abs(t)>1:_error('grid_nm','Resolve propagating radiation on the vertical grid.')
                    return np.exp(-1j*np.arccos(t))
                return np.exp(-np.arccosh(t))
            left=outgoing(v[0] if matched else q2*beta**2-k*k*cfg['top_index']**2)
            right=outgoing(v[-1] if matched else q2*beta**2-k*k*cfg['bottom_index']**2)
            diagonal=(2/h**2+v).astype(complex);diagonal[0]-=left/h**2;diagonal[-1]-=right/h**2
            band=np.zeros((3,len(v)),complex);band[0,1:]=-1/h**2;band[2,:-1]=-1/h**2;band[1]=diagonal
            u=solve_banded((1,1),band,source);value=source@u*h
            if q2==0:
                up=-left.imag/h*abs(u[0])**2;down=-right.imag/h*abs(u[-1])**2
                flux.update(up_fraction=float(up/(up+down)) if up+down>0 else None,
                    green_flux_relative_error=float(abs(up+down+value.imag)/max(up+down,1e-30)))
        else:
            ns=n[pc];w=contrast[pc]*theta[pc]*h
            if len(w)>6000:_error('grid_nm','Local Green matrices exceed the supported memory budget; use layer-resolved Green.')
            if q2==0:
                optical=np.cumsum(ns)*h
                G=-1j*np.exp(-1j*k*abs(optical[:,None]-optical[None,:]))/(2*k*np.sqrt(ns[:,None]*ns[None,:]))
            else:
                argument=q2*beta**2-k*k*ns*ns
                if np.any(argument<=0):_error('green_model','The local high-order evanescent approximation is invalid; use layer-resolved Green.')
                kap=np.sqrt(argument);optical=np.cumsum(kap)*h
                G=np.exp(-abs(optical[:,None]-optical[None,:]))/(2*np.sqrt(kap[:,None]*kap[None,:]))
            value=w@G@w
        cache[q2]=value
        return value
    Ir=green(0);C=np.zeros((4,4),complex);direct=np.zeros_like(C);pref=-k*k/(2*beta)
    for i in range(4):
        for j in range(4):
            if i!=j:direct[i,j]=pref*coefficient(vectors[i]-vectors[j])*I1*np.dot(pol[i],pol[j]);C[i,j]+=direct[i,j]
            C[i,j]+=pref*k*k*coefficient(vectors[i])*coefficient(-vectors[j])*Ir*np.dot(pol[i],pol[j])
    for m in range(-cfg['harmonics'],cfg['harmonics']+1):
        if cancelled():raise InterruptedError('PCSEL calculation cancelled')
        for nn in range(-cfg['harmonics'],cfg['harmonics']+1):
            q2=m*m+nn*nn
            if q2<=1:continue
            q=np.array([m,nn]);long=np.outer(q,q)/q2;response=-Ip*long+k*k*green(q2)*(np.eye(2)-long)
            for i in range(4):
                for j in range(4):C[i,j]+=pref*coefficient(vectors[i]-q)*coefficient(q-vectors[j])*(pol[i]@response@pol[j])
    from pcsel_paper_studies import coupling_diagnostics
    flux['coupling_diagnostics']=coupling_diagnostics(C,direct)
    flux['radiation_boundary']=cfg.get('radiation_boundary','external_interfaces')
    return C,flux


def chebyshev(order):
    t=np.pi*np.arange(order+1)/order;x=np.cos(t);c=np.r_[2,np.ones(order-1),2]*(-1.)**np.arange(order+1)
    d=x[:,None]-x[None,:];D=(c[:,None]/c[None,:])/(d+np.eye(order+1));D-=np.diag(D.sum(axis=1));D=-2*D
    w=np.zeros(order+1);ii=np.arange(1,order);v=np.ones(order-1)
    if order%2==0:
        w[[0,-1]]=1/(order*order-1)
        for k in range(1,order//2):v-=2*np.cos(2*k*t[ii])/(4*k*k-1)
        v-=np.cos(order*t[ii])/(order*order-1)
    else:
        w[[0,-1]]=1/(order*order)
        for k in range(1,(order-1)//2+1):v-=2*np.cos(2*k*t[ii])/(4*k*k-1)
    w[ii]=2*v/order
    return (1-x)/2,D,w/2


def finite_modes(cfg,C,frequency,cancelled=lambda:False,group_index=None):
    from scipy.sparse import csr_matrix,kron,eye,block_diag
    from scipy.sparse.linalg import eigs
    period_nm=frequency*cfg['reference_wavelength_nm'] if cfg.get('vertical_formulation')=='reference_wavelength' else cfg['lattice_nm']
    Lx,Ly=np.array(cfg['aperture_um'])*1000;x,D,w=chebyshev(cfg['collocation_order']);P=len(x)
    I=eye(P,format='csr');Dx=kron(I,csr_matrix(D/Lx));Dy=kron(csr_matrix(D/Ly),I)
    op=block_diag([1j*Dx,-1j*Dx,1j*Dy,-1j*Dy],format='csr')+kron(csr_matrix(C),eye(P*P,format='csr'))
    ids=np.arange(P*P).reshape(P,P);mask=np.ones(4*P*P,bool)
    for i,edge in enumerate([ids[:,0],ids[:,-1],ids[0,:],ids[-1,:]]):mask[i*P*P+edge]=False
    op=op[mask,:][:,mask].tocsc();inf=np.linalg.eigvals(C);vals=[];vecs=[]
    for branch in range(4):
        if cancelled():raise InterruptedError('Finite mode calculation cancelled')
        va,ve=eigs(op,k=min(8,op.shape[0]-2),sigma=inf[branch]+.5j/max(Lx,Ly),tol=1e-9,maxiter=5000,ncv=min(64,op.shape[0]),v0=np.ones(op.shape[0],complex))
        for j,value in enumerate(va):
            if not any(abs(value-v)<1e-10 for v in vals):vals.append(value);vecs.append(ve[:,j])
    R=(C-C.conj().T)/(2j);weights=np.outer(w,w).ravel();rows=[];fields=[]
    for index in np.argsort(np.imag(vals)):
        value=vals[index];u=np.zeros(4*P*P,complex);u[mask]=vecs[index];u=u.reshape(4,P*P)
        norm=float(np.sum(abs(u)**2*weights));u/=np.sqrt(norm);v=u.reshape(4,P,P)
        rad=float(2*np.einsum('in,ij,jn,n->',u.conj(),R,u,weights).real)*1e7
        edge=float((np.sum(abs(v[0,:,-1])**2*w)+np.sum(abs(v[1,:,0])**2*w))/Lx+
                   (np.sum(abs(v[2,-1,:])**2*w)+np.sum(abs(v[3,0,:])**2*w))/Ly)*1e7
        total=float(2*value.imag*1e7);residual=np.linalg.norm(op@vecs[index]-value*vecs[index])/max(np.linalg.norm(op@vecs[index]),1e-30)
        ng=group_index if group_index is not None else 1/frequency
        freq=float(frequency*(1+value.real/(2*np.pi*frequency/period_nm*ng)))
        rows.append(dict(mode=len(rows),detuning_cm1=float(value.real*1e7),frequency=freq,wavelength_nm=period_nm/freq,
            total_loss_cm1=total,radiation_loss_cm1=rad,edge_loss_cm1=edge,
            balance_relative=abs(total-rad-edge)/max(abs(total),1e-30),eigen_residual=float(residual)))
        fields.append(v)
    return rows,dict(x=x,fields=np.asarray(fields),aperture_um=np.asarray(cfg['aperture_um']))


def _resolved_mode_radiation(mode):
    """Peak normalization requires radiative loss distinguishable from roundoff."""
    radiation=float(mode.get('radiation_loss_cm1',0.))
    total=float(mode.get('total_loss_cm1',0.))
    return math.isfinite(radiation) and radiation>1e-12*max(abs(total),1.)


def far_field(cfg,finite,mode):
    if cfg.get('radiation_boundary')=='matched_external' or not any(abs(cfg.get(key,1.)-1.)<1e-12 for key in ('top_index','bottom_index')):
        raise ValueError('This Fraunhofer angular view requires an explicit external air port. Matched semiconductor radiation or two non-air external ports need a medium-aware far-field model.')
    if not _resolved_mode_radiation(mode):
        raise ValueError('This mode has no resolved positive radiative flux. A normalized emitted beam is undefined for a dark mode.')
    from scipy.interpolate import BarycentricInterpolator
    grid=cfg['beam_grid'];padding=cfg['beam_padding'];Lx,Ly=cfg['aperture_um']
    t=(np.arange(grid)+.5)/grid;T=BarycentricInterpolator(finite['x'],np.eye(len(finite['x'])),axis=0)(t)
    wave=np.asarray([T@part@T.T for part in finite['fields'][mode['mode']]])
    vectors=np.array([[1,0],[-1,0],[0,1],[0,-1]])
    coeff=np.asarray([sum(shape_fourier(s,-q) for s in cfg['shapes']) for q in vectors])
    ex=coeff[2]*wave[2]+coeff[3]*wave[3];ey=coeff[0]*wave[0]+coeff[1]*wave[1]
    dx,dy=Lx/grid,Ly/grid;norm=float(np.sum(abs(ex)**2+abs(ey)**2)*dx*dy)
    if norm<=1e-30:raise ValueError('This mode has no resolved emitted aperture field.')
    ex/=np.sqrt(norm);ey/=np.sqrt(norm);size=grid*padding;lam=mode['wavelength_nm']/1000
    fx=np.fft.fftshift(np.fft.fft2(ex,s=(size,size)))*dx*dy
    fy=np.fft.fftshift(np.fft.fft2(ey,s=(size,size)))*dx*dy
    sx=np.fft.fftshift(np.fft.fftfreq(size,d=dx))*lam;sy=np.fft.fftshift(np.fft.fftfreq(size,d=dy))*lam
    far=(abs(fx)**2+abs(fy)**2)/lam**2
    return dict(x_um=(t-.5)*Lx,y_um=(t-.5)*Ly,near_per_um2=abs(ex)**2+abs(ey)**2,
        sin_theta_x=sx,sin_theta_y=sy,far_paraxial_per_sr=far,far_x_per_sr=abs(fx)**2/lam**2,far_y_per_sr=abs(fy)**2/lam**2,Ex=ex,Ey=ey,
        parseval_power=np.sum(far)*(sx[1]-sx[0])*(sy[1]-sy[0]))


def _saved_finite(cfg):
    """Reuse fields only when every physical and numerical finite-mode input matches."""
    import csv
    folder=Path(cfg['beam_saved_run']).expanduser().resolve()
    original=json.loads((folder/'pcsel_inputs.json').read_text(encoding='utf-8'))
    keys=('lattice_nm','layers','shapes','fill_fraction','inclusion_index','top_index','bottom_index',
          'grid_nm','pad_nm','harmonics','green_model','aperture_um','collocation_order','radiation_boundary','vertical_boundary','vertical_mode_selection','vertical_mode_candidates','vertical_mode_index','vertical_formulation','reference_wavelength_nm')
    defaults={r['path']:r['default'] for r in FIELD_SCHEMA if 'default' in r}
    def finite_input(source,key):
        value=source.get(key,defaults.get(key))
        if key in ('layers','shapes') and isinstance(value,list):
            # IDs/names address editable rows; they do not enter the finite
            # operator. Keep row order and every other (including unknown or
            # nested) field exact: independent UI authoring generates new IDs.
            return [{k:v for k,v in row.items() if k not in ('id','name')}
                    if isinstance(row,dict) else row for row in value]
        return value
    changed=[key for key in keys if finite_input(original,key)!=finite_input(cfg,key)]
    if changed:_error('beam_saved_run','Saved modes belong to different inputs: '+', '.join(changed)+'. Run the current finite cavity first.')
    with (folder/'finite_modes.csv').open(newline='',encoding='utf-8') as stream:
        def restored(key,value):
            if value=='':return None
            if key=='mode':return int(value)
            if key=='accepted':return value.lower()=='true'
            if key=='label':return value
            return float(value)
        modes=[{key:restored(key,value) for key,value in row.items()} for row in csv.DictReader(stream)]
    with np.load(folder/'finite_fields.npz',allow_pickle=False) as archive:
        fields={key:archive[key] for key in ('x','fields','aperture_um')}
    if not modes or fields['fields'].shape[:2]!=(len(modes),4) or not np.isfinite(fields['fields']).all():
        _error('beam_saved_run','Saved finite mode fields are incomplete or invalid.')
    return modes,fields


def _csv(path,rows):
    import csv
    if not rows:return
    with Path(path).open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def execute(prepared,directory,emit=lambda event:None,cancelled=lambda:False):
    cfg=copy.deepcopy(prepared);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if cancelled():raise InterruptedError('PCSEL calculation cancelled')
    (directory/'pcsel_inputs.json').write_text(json.dumps(cfg,indent=2,allow_nan=False),encoding='utf-8')
    if 'parameter_sweep' in cfg:
        return _execute_sweep(cfg,directory,emit,cancelled)
    model=cfg['model'];summary=dict(status='complete',engine='pcsel',model=model,
        convergence_established=False,artifacts=[],**_model_provenance(model, cfg))
    if model=='gme':
        from research_physics_runtime import run_worker
        result=run_worker(cfg,directory,emit,cancelled,worker_name='pcsel_physics_worker.py')
        summary.update(result)
        summary['radiation_diagnostics']=_gme_radiation_diagnostics(result.get('modes',[]))
        emit(dict(kind='log',message=summary['radiation_diagnostics']['warning']))
    elif model=='rcwa_poles':
        from pcsel_optional import rcwa_poles
        summary.update(rcwa_poles(cfg,directory,emit,cancelled))
    elif model=='aperture':
        from pcsel_aperture import execute_aperture
        summary.update(execute_aperture(cfg,directory,emit,cancelled))
    elif model=='beam' and cfg['beam_saved_run']:
        # _finite_outputs retains exact source-input and accepted-mode checks.
        # A saved finite field needs no new vertical/coupling/cavity solution.
        emit(dict(kind='log',message='Checking and reusing saved finite-mode fields for the beam.'))
        _finite_outputs(cfg,None,None,directory,summary,emit,cancelled)
        summary['source_reuse']='Compatible saved finite-mode fields; source solvers were not rerun.'
    else:
        row,profile=vertical(cfg);summary['vertical']=row
        if cfg.get('vertical_formulation')=='reference_wavelength':
            summary['derived_inputs']=dict(requested_lattice_nm=cfg['lattice_nm'],effective_lattice_nm=row['effective_lattice_nm'],reference_wavelength_nm=cfg['reference_wavelength_nm'],vertical_formulation='reference_wavelength',vertical_mode_selection=cfg['vertical_mode_selection'],selected_mode_index=row['selected_mode_index'],
                derivation='a=lambda0/neff from the calculated vertical eigenproblem; period is derived independently for this geometry, not fitted to published outputs.',method_reference='Radziunas et al. 2024, Optical Mode Calculation in Large-Area PCSELs, Eq.2 and Sec.4.2/4.4')
            cfg['lattice_nm']=row['effective_lattice_nm']
            (directory/'pcsel_derived_inputs.json').write_text(json.dumps(summary['derived_inputs'],indent=2,allow_nan=False),encoding='utf-8')
            summary['artifacts'].append('pcsel_derived_inputs.json')
        np.savetxt(directory/'vertical_profile.csv',np.column_stack([profile['z_nm'],profile['index'],profile['intensity_per_nm']]),delimiter=',',header='z_nm,index,intensity_per_nm',comments='')
        _csv(directory/'vertical_modes.csv',[row]);summary['artifacts']+=['vertical_profile.csv','vertical_modes.csv']
        if len(profile['candidate_fields'])>1:
            np.savez_compressed(directory/'vertical_candidates.npz',z_nm=profile['z_nm'],fields=profile['candidate_fields'],intensity_per_nm=profile['candidate_fields']**2,
                array_axes=json.dumps({key:dict(axes=[dict(name='Vertical mode index'),dict(name='Depth from p-side',coordinate='z_nm',unit='nm')],unit='nm^-1' if key=='intensity_per_nm' else 'nm^-1/2') for key in ('fields','intensity_per_nm')}))
            _csv(directory/'vertical_candidates.csv',row['mode_candidates'])
            summary['artifacts']+=['vertical_candidates.npz','vertical_candidates.csv']
        if not row['guided']:summary['status']='validity_limit'
        if model!='vertical':
            if not row['guided']:raise ValueError('The supplied stack has no confined fundamental mode at this propagation constant.')
            C,flux=coupling(cfg,profile,row,cancelled);summary.update(flux)
            eigen=np.linalg.eigvals(C);modes=[dict(mode=i,label='ABCD'[i],detuning_cm1=float(v.real*1e7),frequency=float(row['frequency']*(1+v.real/(2*np.pi*row['frequency']/cfg['lattice_nm']*row['effective_group_index']))),power_loss_cm1=float(2*v.imag*1e7)) for i,v in enumerate(sorted(eigen,key=lambda v:v.real))]
            _csv(directory/'coupled_modes.csv',modes);np.savez_compressed(directory/'coupling_matrix.npz',C=C,H=(C+C.conj().T)/2,R=(C-C.conj().T)/(2j))
            (directory/'coupling_diagnostics.json').write_text(json.dumps(flux['coupling_diagnostics'],indent=2,allow_nan=False),encoding='utf-8')
            summary['artifacts'].append('coupling_diagnostics.json')
            summary.update(coupled_modes=modes,green_model=cfg['green_model']);summary['artifacts']+=['coupled_modes.csv','coupling_matrix.npz']
            if model in ('finite','beam'):
                try:_finite_outputs(cfg,C,row['frequency'],directory,summary,emit,cancelled,group_index=row['effective_group_index'])
                except (ValueError,RuntimeError,OSError,KeyError) as exc:
                    summary.update(status='partial',optional_output_error=str(exc))
    if cancelled():raise InterruptedError('PCSEL calculation cancelled')
    from pcsel_paper_studies import design_metrics, figure_manifest
    summary['design_metrics']=design_metrics(summary)
    summary['paper_study']=copy.deepcopy(cfg.get('paper_study',{}))
    _csv(directory/'pcsel_design_metrics.csv',[summary['design_metrics']])
    summary['artifacts'].append('pcsel_design_metrics.csv')
    if cfg.get('paper_study'):
        (directory/'pcsel_paper_figures.json').write_text(json.dumps(figure_manifest(cfg,summary),indent=2,allow_nan=False),encoding='utf-8')
        summary['artifacts'].append('pcsel_paper_figures.json')
    (directory/'pcsel_summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    emit(dict(kind='log',message='PCSEL '+model+' completed with status '+summary['status']))
    return summary


def _finite_outputs(cfg,C,frequency,directory,summary,emit,cancelled,group_index=None):
    if cfg['model']=='beam' and cfg['beam_saved_run']:
        modes,fields=_saved_finite(cfg)
        folder=Path(cfg['beam_saved_run']).resolve()
        summary['finite_mode_source']=str(folder)
        source=json.loads((folder/'pcsel_summary.json').read_text(encoding='utf-8'))
        if 'up_fraction' in source:summary['up_fraction']=source['up_fraction']
        if 'derived_inputs' in source:summary['derived_inputs']=copy.deepcopy(source['derived_inputs'])
    else:modes,fields=finite_modes(cfg,C,frequency,cancelled,group_index=group_index)
    up=summary.get('up_fraction')
    def accepted(mode):
        return (mode['balance_relative']<=.02 and mode['eigen_residual']<=1e-6 and mode['total_loss_cm1']>0
            and mode['radiation_loss_cm1']>=-1e-10 and mode['edge_loss_cm1']>=0)
    for row in modes:
        row['accepted']=bool(accepted(row))
        row['eta_edge']=row['edge_loss_cm1']/row['total_loss_cm1'] if row['accepted'] else None
        row['eta_surface']=row['radiation_loss_cm1']/row['total_loss_cm1']*up if row['accepted'] and up is not None else None
        row['eta_substrate']=row['radiation_loss_cm1']/row['total_loss_cm1']*(1-up) if row['accepted'] and up is not None else None
    _csv(directory/'finite_modes.csv',modes)
    physical=dict(x_um=(fields['x']-.5)*cfg['aperture_um'][0],y_um=(fields['x']-.5)*cfg['aperture_um'][1])
    axes=dict(fields=dict(axes=[dict(name='Mode'),dict(name='Basic wave (+x, -x, +y, -y)'),
        dict(name='y',coordinate='y_um',unit='µm'),dict(name='x',coordinate='x_um',unit='µm')],unit='normalized amplitude'),
        mode_intensity=dict(axes=[dict(name='Mode'),dict(name='y',coordinate='y_um',unit='µm'),dict(name='x',coordinate='x_um',unit='µm')],unit='normalized sum of four basic-wave intensities'))
    # The coherent transverse aperture field differs from the intracavity sum
    # of basic-wave intensities. Preserve both quantities for paper insets.
    vectors=np.array([[1,0],[-1,0],[0,1],[0,-1]])
    coeff=np.asarray([sum(shape_fourier(s,-q) for s in cfg['shapes']) for q in vectors])
    waves=fields['fields']
    ex=coeff[2]*waves[:,2]+coeff[3]*waves[:,3]
    ey=coeff[0]*waves[:,0]+coeff[1]*waves[:,1]
    emitted=abs(ex)**2+abs(ey)**2
    peaks=emitted.max(axis=(1,2),keepdims=True)
    resolved=np.asarray([_resolved_mode_radiation(mode) for mode in modes])[:,None,None]
    emitted=np.divide(emitted,peaks,out=np.full_like(emitted,np.nan),where=(peaks>1e-30)&resolved)
    axes['emitted_near_intensity']=dict(axes=axes['mode_intensity']['axes'],unit='peak = 1')
    np.savez_compressed(directory/'finite_fields.npz',**fields,**physical,
        mode_intensity=np.sum(abs(waves)**2,axis=1),emitted_near_intensity=emitted,array_axes=json.dumps(axes))
    summary.update(emitted_near_field_available=True,
        emitted_near_field_modes=[dict(mode=mode['mode'],resolved_radiation=bool(ok),normalization='peak = 1' if ok else 'undefined: no resolved positive radiative flux') for mode,ok in zip(modes,resolved[:,0,0])],
        emitted_near_field_scope='Peak-normalized coherent transverse aperture intensity from the four basic waves and geometry-derived radiation coefficients, sampled on the native cavity grid. Radiative loss must exceed 1e-12 times max(abs(total loss), 1 cm^-1); dark/unresolved radiation has undefined peak normalization (NaN). No emitted watts or far-field propagation are inferred.')
    summary.update(finite_modes=modes,finite_mode_search_scope='Sparse shift-invert search near four infinite-cavity eigenvalues, up to eight roots per seed. Lowest accepted returned mode is not proof of the global fundamental; labels are loss-ranked and not branch-tracked.',
        efficiency_scope='Substrate is the bottom n-side port. Surface is the top p-side port. Fractions use actual modal radiation/edge integrals and Green-function port flux, with no internal absorption; only accepted residual/power-balance modes receive efficiencies.')
    summary['artifacts']+=['finite_modes.csv','finite_fields.npz']
    if any(not accepted(mode) for mode in modes):summary['status']='unconverged'
    if cfg['model']!='beam':return
    eligible=[mode for mode in modes if accepted(mode) and (cfg['beam_mode']==-1 or mode['mode']>=cfg['beam_mode'])]
    if cfg['beam_mode']!=-1 and not any(m['mode']==cfg['beam_mode'] for m in eligible):
        _error('beam_mode','The selected mode fails residual or power-balance checks; choose an accepted mode or refine the cavity solve.')
    if not eligible:_error('beam_mode','No selected positive-loss mode passes the finite-mode residual and power-balance checks. Refine the cavity solve.')
    eligible.sort(key=lambda mode:mode['total_loss_cm1'])
    chosen=eligible[:cfg.get('beam_mode_count',1)]
    summary['beam_outputs']=[]
    for number,selected in enumerate(chosen):
        if cancelled():raise InterruptedError('Beam calculation cancelled; completed numerical fields remain saved.')
        beam=far_field(cfg,fields,selected)
        near_axes=[dict(name='y',coordinate='y_um',unit='µm'),dict(name='x',coordinate='x_um',unit='µm')]
        far_axes=[dict(name='sin θy',coordinate='sin_theta_y',unit='dimensionless'),dict(name='sin θx',coordinate='sin_theta_x',unit='dimensionless')]
        axes={key:dict(axes=near_axes,unit=unit) for key,unit in [('Ex','µm^-1 (unit power)'),('Ey','µm^-1 (unit power)'),('near_per_um2','µm^-2')]}
        for key in ('far_paraxial_per_sr','far_x_per_sr','far_y_per_sr'):axes[key]=dict(axes=far_axes,unit='sr^-1 (paraxial)')
        normalization=cfg['beam_normalization'];power=cfg.get('beam_power_W',1.) if normalization=='calibrated_power' else 1.
        near_scale=1/beam['near_per_um2'].max() if normalization=='peak' else power
        far_scale=1/beam['far_paraxial_per_sr'].max() if normalization=='peak' else power
        beam['near_display']=beam['near_per_um2']*near_scale;beam['far_display']=beam['far_paraxial_per_sr']*far_scale
        axes['near_display']=dict(axes=near_axes,unit='peak = 1' if normalization=='peak' else 'W/µm²' if normalization=='calibrated_power' else 'µm^-2')
        axes['far_display']=dict(axes=far_axes,unit='peak = 1' if normalization=='peak' else 'W/sr (paraxial)' if normalization=='calibrated_power' else 'sr^-1 (paraxial)')
        suffix='' if number==0 else '_mode'+str(selected['mode']).zfill(4)
        npz='beam_fields'+suffix+'.npz';csv_name='beam_x'+suffix+'.csv'
        np.savez_compressed(directory/npz,**beam,array_axes=json.dumps(axes))
        center=len(beam['sin_theta_x'])//2;valid=abs(beam['sin_theta_x'])<1
        np.savetxt(directory/csv_name,np.column_stack([np.rad2deg(np.arcsin(beam['sin_theta_x'][valid])),beam['far_paraxial_per_sr'][center,valid],beam['far_display'][center,valid]]),
            delimiter=',',header='theta_x_deg,paraxial_intensity_per_sr,display_intensity',comments='')
        dx=cfg['aperture_um'][0]/cfg['beam_grid'];dy=cfg['aperture_um'][1]/cfg['beam_grid']
        output=dict(mode=selected['mode'],npz=npz,csv=csv_name,parseval_power=float(beam['parseval_power']))
        summary['beam_outputs'].append(output)
        if number==0:
            summary.update(beam_angular_scope='Free-space paraxial angular spectrum in an available external air port; no medium-angle or interface-extraction correction is applied.',beam_mode=selected['mode'],parseval_power=float(beam['parseval_power']),
                polarization_basis='Cartesian aperture x/y components',polarization_power_fraction_x=float(np.sum(abs(beam['Ex'])**2)*dx*dy),
                polarization_power_fraction_y=float(np.sum(abs(beam['Ey'])**2)*dx*dy),
                beam_normalization=dict(mode=normalization,power_W=power if normalization=='calibrated_power' else None,source=cfg['beam_power_source']))
        summary['artifacts'] += [npz,csv_name]
    summary['beam_modes_requested']=cfg.get('beam_mode_count',1)
    summary['beam_modes_completed']=len(chosen)
    if len(chosen)<cfg.get('beam_mode_count',1):summary['status']='partial'


def _execute_sweep(cfg,directory,emit,cancelled):
    from pcsel_paper_studies import METRIC_KEYS, figure_manifest
    cases=cfg['parameter_sweep']['cases'];rows=[];results=[];mode_rows=[]
    summary=dict(status='partial',engine='pcsel',model=cfg['model'],convergence_established=False,
        artifacts=['pcsel_sweep.csv','pcsel_sweep_modes.csv','pcsel_sweep.json'],cases=results,
        paper_study=copy.deepcopy(cfg.get('paper_study',{})),**_model_provenance(cfg['model'], cfg))
    summary['limitations'].append('Sweep completion is not convergence or paper agreement. Mode labels are independently frequency-ranked (A-D) or loss-ranked (finite), not tracked physical branches.')
    def save():
        _csv(directory/'pcsel_sweep.csv',rows);_csv(directory/'pcsel_sweep_modes.csv',mode_rows)
        if cfg.get('paper_study'):
            (directory/'pcsel_paper_figures.json').write_text(json.dumps(figure_manifest(cfg,summary),indent=2,allow_nan=False),encoding='utf-8')
            if 'pcsel_paper_figures.json' not in summary['artifacts']:summary['artifacts'].append('pcsel_paper_figures.json')
        for name in ('pcsel_sweep.json','pcsel_summary.json'):
            (directory/name).write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    for index,case in enumerate(cases):
        if cancelled():
            save();raise InterruptedError('PCSEL sweep cancelled; completed cases have been preserved.')
        name=f'case-{index+1:04d}'
        item=dict(case=index+1,directory=name,parameters=case['parameters'])
        variant={'variant':case['variant']} if 'variant' in case else {}
        item.update(variant)
        record=dict(case=index+1,**variant,**case['parameters'],status='',frequency=None,wavelength_nm=None,effective_lattice_nm=None,Gamma_QW=None,
            total_loss_cm1=None,radiation_loss_cm1=None,edge_loss_cm1=None,error='',**{key:None for key in METRIC_KEYS})
        if case.get('status')=='invalid_geometry':
            item.update(status='invalid_geometry',error=case['error']);record.update(status='invalid_geometry',error=case['error'])
        else:
            try:
                result=execute(case['prepared'],directory/name,emit,cancelled)
                item['summary']=result;record['status']=result['status']
                for key in ('frequency','wavelength_nm','effective_lattice_nm','Gamma_QW'):record[key]=result.get('vertical',{}).get(key)
                for key in METRIC_KEYS:record[key]=result.get('design_metrics',{}).get(key)
                modes=[r for r in result.get('finite_modes',[]) if r.get('accepted',False)]
                if modes:
                    selected=min(modes,key=lambda r:r['total_loss_cm1'])
                    for key in ('total_loss_cm1','radiation_loss_cm1','edge_loss_cm1'):record[key]=selected.get(key)
                for model,key in [('cwt','coupled_modes'),('finite','finite_modes')]:
                    for mode in result.get(key,[]):
                        mr=dict(case=index+1,**variant,**case['parameters'],model=model,label=mode.get('label','loss-rank-'+str(mode['mode'])),
                            mode=mode['mode'],status=result['status'])
                        for field in ('frequency','detuning_cm1','wavelength_nm','power_loss_cm1','total_loss_cm1','radiation_loss_cm1','edge_loss_cm1',
                            'accepted','balance_relative','eigen_residual','eta_substrate','eta_edge','eta_surface'):mr[field]=mode.get(field)
                        mode_rows.append(mr)
                summary['artifacts'].append(name+'/pcsel_summary.json')
            except InterruptedError:
                save();raise
            except Exception as exc:
                item.update(status='failed',error=str(exc));record.update(status='failed',error=str(exc))
        results.append(item);rows.append(record);save()
        emit(dict(kind='progress',done=index+1,total=len(cases),message=f'PCSEL sweep: {index+1}/{len(cases)} cases recorded.'))
    statuses={r['status'] for r in rows}
    summary['status']='partial' if 'failed' in statuses or 'partial' in statuses else 'validity_limit' if 'validity_limit' in statuses else 'unconverged' if 'unconverged' in statuses else 'complete'
    summary['completed_cases']=sum(r['status'] not in ('failed','invalid_geometry') for r in rows)
    summary['invalid_geometry_cases']=sum(r['status']=='invalid_geometry' for r in rows)
    summary['failed_cases']=sum(r['status']=='failed' for r in rows)
    if summary['completed_cases']==0:summary['status']='no_valid_cases'
    save()
    return summary
