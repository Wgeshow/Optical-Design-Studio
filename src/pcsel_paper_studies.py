"""Editable King 2024 PCSEL recipes and diagnostics of actual solver outputs.

Reference values never enter a solver. Numerical sampling is an explicit application
choice; the author's underlying data and several termination details are unavailable.
"""
from __future__ import annotations
import copy
import math
import numpy as np

KING2024_SOURCE = dict(title="Design of very-large area photonic crystal surface emitting lasers with an all-semiconductor photonic crystal",
    authors="King et al.", doi="10.1364/OE.537452", year=2024)
KING2024_FIGURES = {
    'fig2': dict(title='Vertical structure and unit cell', model='vertical'),
    'fig3': dict(title='Triangle geometry: band-edge loss and discrimination', model='cwt'),
    'fig4': dict(title='Triangle geometry: in-plane coupling', model='cwt'),
    'fig4d': dict(title='Direct 1D coupling: focused triangle scan', model='cwt'),
    'fig5': dict(title='DBR interference: p-cladding thickness', model='cwt'),
    'fig6': dict(title='Finite cavity: loss and efficiencies versus size', model='finite'),
    'fig7': dict(title='Finite cavity: mode discrimination and switching', model='finite'),
    'fig8': dict(title='Two-millimetre cavity: three mode profiles', model='beam'),
    'fig9': dict(title='Weakened grating: cavity scaling and mode profiles', model='finite'),
    'fig9a': dict(title='Weakened grating: cavity scaling', model='finite'),
    'fig9b': dict(title='Weakened grating: five-millimetre mode profiles', model='beam'),
}

def triangle_vertices(shape):
    """Isosceles triangle; theta is BASE angle, coordinates in lattice periods.

The unrotated apex points along +y. Rotation -45 degrees gives y=x symmetry.
Center is the center of the axis-aligned bounding box, a documented phase gauge.
"""
    b=float(shape.get('base_length', .75)); angle=float(shape.get('base_angle_deg',70.))
    rotation=float(shape.get('rotation_deg',-45.)); center=np.asarray(shape.get('center',[0.,0.]),float)
    if not (math.isfinite(b) and b>0 and math.isfinite(angle) and 0<angle<90 and math.isfinite(rotation)):
        raise ValueError('Triangle base length must be positive and its base angle strictly between 0 and 90 degrees.')
    if center.shape!=(2,) or not np.isfinite(center).all():
        raise ValueError('Triangle center needs two finite coordinates in lattice periods.')
    h=.5*b*math.tan(math.radians(angle)); vertices=np.array([[-b/2,0.],[b/2,0.],[0.,h]])
    t=math.radians(rotation); R=np.array([[math.cos(t),-math.sin(t)],[math.sin(t),math.cos(t)]])
    vertices=vertices@R.T; vertices-=.5*(vertices.min(axis=0)+vertices.max(axis=0))
    return (vertices+center).tolist()

def periodic_triangle_overlap(vertices):
    """Interior overlap against translated copies; touching boundaries are allowed."""
    points=np.asarray(vertices,float)
    span=np.ceil(np.ptp(points,axis=0)).astype(int)+1
    # Very large features must not create an unbounded validation loop.
    if np.any(span>8):return True
    edges=np.roll(points,-1,axis=0)-points
    axes=np.column_stack([-edges[:,1],edges[:,0]])
    for ix in range(-span[0],span[0]+1):
        for iy in range(-span[1],span[1]+1):
            if ix==iy==0:continue
            other=points+[ix,iy]; separated=False
            for axis in axes:
                a=points@axis;b=other@axis
                if min(a.max(),b.max())-max(a.min(),b.min())<=1e-12*np.linalg.norm(axis):
                    separated=True;break
            if not separated:return True
    return False

def king2024_example(figure='fig3',model=None,formulation='fixed_period'):
    """An editable deck from Table 1. No fitted parameters or target injection."""
    if figure not in KING2024_FIGURES:raise ValueError('Choose a King 2024 figure from fig2 through fig9.')
    if formulation not in ('fixed_period','reference_wavelength'):raise ValueError('Select fixed_period or reference_wavelength.')
    no_dbr=figure in ('fig3','fig4','fig4d'); weak=figure in ('fig9','fig9a','fig9b')
    bottom_to_top=[('n-substrate',350.,12.1),('n-cladding-inner',100.,11.1),('n-cladding',1300.,10.2),
        ('lower-waveguide',100.,12.1),('quantum-well',5.,13.6),('qw-pc-spacer',300. if weak else 50.,12.1),
        ('photonic-crystal',100. if weak else 150.,12.1),('upper-waveguide',170.,12.1),
        ('p-cladding',None if no_dbr else 1565.,10.2)]
    if not no_dbr:
        for i in range(14):
            bottom_to_top.extend([(f'dbr-{i+1:02d}-low',90.,8.9),(f'dbr-{i+1:02d}-high',79.,11.6)])
    bottom_to_top.append(('p-cap',220.,12.1))
    layers=[dict(id=name,name=name,thickness_nm=d,index=math.sqrt(eps),qw=name=='quantum-well',patterned=name=='photonic-crystal')
        for name,d,eps in reversed(bottom_to_top)]
    chosen=model or KING2024_FIGURES[figure]['model']
    assumptions=[
        'The period is the approximately 320 nm value in the paper; it is not tuned to force 1070 nm.',
        'Table 1 dielectric constants and dimensions are used without material fitting; internal absorption is zero.',
        'DBR order follows the table bottom-to-top, 14 pairs of 90 nm epsilon 8.9 then 79 nm epsilon 11.6; the sequence is reversed for the top-to-bottom editor.',
        'Triangle theta is a base angle; h=b*tan(theta)/2. Rotation and bounding-box centering define a translation gauge.',
        'Vertical finite differences, harmonic cutoff, Chebyshev cavity discretization, and sweep samples are application numerical choices, not author data.',
        'The paper does not provide underlying numerical arrays or an author acceptance tolerance. No paper agreement is asserted.',
        'Vertical profile follows the finite-domain Dirichlet approximation of Wenzel et al. arXiv:2402.11246v5 Eq.23. The application selects the lowest-frequency, nodeless Dirichlet mode; the paper does not state a vertical-mode selector. All candidate overlaps/node counts are saved; this is not proof of substrate leakage confinement.',
        'Radiation Green functions separately use outgoing external air ports for the finite Table 1 stack, or matched semiconductor ports for no-DBR cases. The 350 nm finite substrate layer is the stated model, not an assumed physical wafer thickness.',
        'Local longitudinal CWT closure remains an implementation approximation; exact group velocity is not tabulated.',
    ]
    if no_dbr:assumptions.append('No-DBR reconstruction removes DBR pairs and uses matched outer semiconductor radiation ports. No-DBR p-cladding thickness is not specified and remains blank: Run is blocked until a documented value is supplied. Cap/cladding termination is also not completely specified; matching the paper requires that missing information.')
    cfg=dict(model=chosen,lattice_nm=320.,layers=layers,
        shapes=[dict(id='triangle',shape='triangle',base_length=.75,base_angle_deg=70.,rotation_deg=-45.,center=[0.,0.])],
        inclusion_index=math.sqrt(10.1),top_index=1.,bottom_index=1.,grid_nm=2.5,pad_nm=2000.,harmonics=8,
        green_model='layer_resolved',vertical_formulation=formulation,reference_wavelength_nm=1070.,vertical_boundary='finite_stack_dirichlet',vertical_mode_selection='lowest_frequency',vertical_mode_candidates=8,radiation_boundary='matched_external' if no_dbr else 'external_interfaces',
        aperture_um=[5000.,5000.] if figure=='fig9b' else [2000.,2000.],collocation_order=20,
        beam_grid=128,beam_padding=4,beam_mode=-1,beam_mode_count=3 if chosen=='beam' else 1,
        beam_normalization='peak',paper_study=dict(source=copy.deepcopy(KING2024_SOURCE),figure=figure,
            assumptions=assumptions,reference_only=True,validated=False,structure='weakened' if weak else 'original'))
    if formulation=='reference_wavelength':
        cfg['vertical_mode_selection']='core_overlap'
        cfg['paper_study']['assumptions'][0]='The paper states an approximately 320 nm period. This explicitly selected convention derives the actual period from the stated 1070 nm wavelength and calculated effective index; it does not fit radiation losses or efficiencies.'
        cfg['paper_study']['assumptions']=[v.replace('The application selects the lowest-frequency, nodeless Dirichlet mode; the paper does not state a vertical-mode selector.', 'The application selects largest combined QW and PC overlap according to cited Ref.21; King does not explicitly restate a vertical-mode selector.') for v in cfg['paper_study']['assumptions']]
        cfg['paper_study']['assumptions'].append('Explicit alternative follows cited Ref.21 Eq.2 and Sec.4.2/4.4: fix design wavelength 1070 nm, select largest combined QW+PC overlap among computed candidates, derive a=lambda0/neff for each geometry. This convention is not explicitly restated in King; exact-320-nm results are a separate scenario. No published loss or efficiency is used to choose inputs.')
    if figure in ('fig3','fig4'):
        cfg['parameter_sweep']=dict(parameters=[dict(path='shapes',object_id='triangle',field='base_angle_deg',values=[45.,50.,55.,60.,65.,70.,75.,80.]),
            dict(path='shapes',object_id='triangle',field='base_length',values=[.6,.7,.75,.8,.9,1.,1.1,1.2])],invalid_geometry='mask',max_cases=128)
    elif figure=='fig4d':
        cfg['parameter_sweep']=dict(parameters=[dict(path='shapes',object_id='triangle',field='base_angle_deg',values=[68.,69.,70.,71.,71.5,72.,73.,74.,75.]),
            dict(path='shapes',object_id='triangle',field='base_length',values=[.65,.675,.7,.725,.75,.775])],invalid_geometry='mask',max_cases=128)
        cfg['paper_study']['assumptions'].append('Figure 4(d) displayed scan bounds are theta 68 to 75 degrees and b/a 0.65 to approximately 0.775 (top frame inferred). Explicit sampling is an editable application choice; no grid is digitized from the published colors.')
    elif figure=='fig5':
        cfg['parameter_sweep']=dict(parameters=[dict(path='layers',object_id='p-cladding',field='thickness_nm',values=[1450.,1475.,1500.,1525.,1550.,1565.,1575.,1600.,1625.,1650.,1675.,1700.])])
    elif figure in ('fig6','fig7','fig9','fig9a'):
        cfg['parameter_sweep']=dict(parameters=[dict(path='aperture_um',field='side',values=[100.,500.,700.,1000.,1500.,2000.,2500.,3000.,4000.,5000.] if weak else [100.,300.,500.,700.,1000.,1500.,2000.,2500.,3000.])])
    if figure=='fig9':
        cfg['parameter_sweep']['variants']=[dict(name=name,overrides=[dict(path='layers',object_id='photonic-crystal',field='thickness_nm',value=pc),dict(path='layers',object_id='qw-pc-spacer',field='thickness_nm',value=spacer)]) for name,pc,spacer in [('Original structure',150.,50.),('Weakened grating',100.,300.)]]
        cfg['paper_study']['structure']='explicit original/weakened variants'
        cfg['paper_study']['assumptions'].append('The comparison evaluates both named structures at every explicit cavity-side sample. Only the listed layer overrides differ; all remaining editable inputs are shared. Variant names are labels, not evidence of exact paper agreement.')
    if 'parameter_sweep' in cfg:
        cfg['paper_study']['assumptions'].append('The default sparse samples span the displayed study domain to bound runtime; they are not the paper numerical grid. Edit Sweep values and numerical accuracy before a convergence study.')
    return cfg

def complex_pair(value):return [float(np.real(value)),float(np.imag(value))]

def coupling_diagnostics(C,direct):
    """Hermitian/radiative parts in (+x,-x,+y,-y) basis; inverse nm -> cm^-1."""
    H=(C+C.conj().T)/2; R=(C-C.conj().T)/(2j); scale=1e7
    k1=H[0,1]; kp=H[0,2]; km=H[0,3]
    expected=np.array([[H[0,0],k1,kp,km],[k1.conjugate(),H[0,0],km.conjugate(),kp],
        [kp,km,H[0,0],k1],[km.conjugate(),kp,k1.conjugate(),H[0,0]]])
    values=np.linalg.eigvalsh(R)
    return dict(convention='C and Omega are inverse nm; power loss g=2 Im(Omega)*1e7 cm^-1. Basis (+x,-x,+y,-y).',
        kappa_1d_cm1=complex_pair(k1*scale),kappa_2d_plus_cm1=complex_pair(kp*scale),kappa_2d_minus_cm1=complex_pair(km*scale),
        kappa_1d_abs_cm1=float(abs(k1)*scale),kappa_2d_plus_abs_cm1=float(abs(kp)*scale),
        kappa_2d_minus_abs_cm1=float(abs(km)*scale),kappa_1d_direct_abs_cm1=float(abs(direct[0,1])*scale),
        mu_cm1=float(np.mean(np.diag(R)).real*scale),theta_pc_rad=float(np.angle(R[0,1])),
        y_equals_x_symmetry_relative_residual=float(np.linalg.norm(H-expected)/max(np.linalg.norm(H),1e-30)),
        minimum_radiation_eigenvalue_cm1=float(values.min()*scale),
        decomposition='H=(C+C†)/2; R=(C-C†)/(2i); C=H+iR. Direct is the explicit first-order counter-propagating term.',
        interpretation='Named kappas use the paper symmetry positions; Fourier exp(-iG.r) is the conjugate sign convention of ref22, so phases require a basis/gauge comparison. Inspect the symmetry residual for arbitrary edited shapes; no symmetry is imposed.')

METRIC_KEYS=('g_A_cm1','delta_g_A_cm1','mode_A_is_lowest','lowest_band_loss_cm1','second_band_loss_cm1','delta_g_band_cm1','kappa_1d_abs_cm1','kappa_2d_plus_abs_cm1',
    'kappa_2d_minus_abs_cm1','kappa_1d_direct_abs_cm1','lowest_loss_cm1','second_loss_cm1','delta_g_cm1',
    'eta_substrate','eta_edge','eta_surface','accepted_finite_mode_count')

def design_metrics(summary):
    result={key:None for key in METRIC_KEYS}
    for key in METRIC_KEYS:
        if key in summary.get('coupling_diagnostics',{}):result[key]=summary['coupling_diagnostics'][key]
    modes=summary.get('coupled_modes',[])
    if modes:
        g=float(modes[0]['power_loss_cm1']); other=min(float(r['power_loss_cm1']) for r in modes[1:])
        result.update(g_A_cm1=g,mode_A_is_lowest=bool(g<=other),delta_g_A_cm1=max(0.,other-g))
        ordered=sorted(float(r['power_loss_cm1']) for r in modes)
        result.update(lowest_band_loss_cm1=ordered[0],second_band_loss_cm1=ordered[1],delta_g_band_cm1=ordered[1]-ordered[0])
    finite=[r for r in summary.get('finite_modes',[]) if r.get('accepted',False)]
    finite.sort(key=lambda r:r['total_loss_cm1'])
    if 'finite_modes' in summary:result['accepted_finite_mode_count']=len(finite)
    if finite:
        low=finite[0];result['lowest_loss_cm1']=low['total_loss_cm1']
        for key in ('eta_substrate','eta_edge','eta_surface'):result[key]=low.get(key)
        if len(finite)>1:result.update(second_loss_cm1=finite[1]['total_loss_cm1'],delta_g_cm1=finite[1]['total_loss_cm1']-low['total_loss_cm1'])
    return result

def figure_manifest(cfg,summary):
    """Panel specifications refer only to saved input/data; references are opt-in."""
    study=cfg.get('paper_study',{});target=study.get('figure','')
    axes=cfg.get('parameter_sweep',{}).get('parameters',[])
    labels=['.'.join([a['path']]+([a['object_id']] if a.get('object_id') else [])+([a['field']] if a.get('field') else [])) for a in axes]
    axis_labels={'shapes.triangle.base_angle_deg':'Base angle θ (degrees)','shapes.triangle.base_length':'Base length b/a',
        'aperture_um.side':'Cavity side L (µm)','aperture_um.width':'Cavity width (µm)','aperture_um.height':'Cavity height (µm)',
        'layers.p-cladding.thickness_nm':'p-cladding thickness (nm)'}
    metric_labels={'g_A_cm1':'Band A radiation loss (cm^-1)','delta_g_A_cm1':'Band A discrimination (cm^-1)',
        'delta_g_band_cm1':'Two lowest band-edge losses: difference (cm^-1)',
        'lowest_loss_cm1':'Lowest accepted returned loss (cm^-1)','delta_g_cm1':'Accepted returned mode discrimination (cm^-1)',
        'eta_substrate':'Substrate emission fraction','eta_edge':'Edge emission fraction','eta_surface':'p-side surface emission fraction'}
    axis_label=lambda key:axis_labels.get(key,key)
    plots=[]
    if len(labels)>=2:
        # Match the physical axes in the paper: theta horizontal, b/a vertical.
        x,y=labels[:2]
        if 'shapes.triangle.base_angle_deg' in labels and 'shapes.triangle.base_length' in labels:
            x,y='shapes.triangle.base_angle_deg','shapes.triangle.base_length'
        quantities=[('g_A_cm1','Figure 3(a) · Band A radiation loss'),('delta_g_A_cm1','Figure 3(b) · Band A discrimination'),
            ('kappa_2d_plus_abs_cm1','Figure 4(a) · Hermitian 2D+ coupling'),('kappa_2d_minus_abs_cm1','Figure 4(b) · Hermitian 2D− coupling'),
            ('kappa_1d_abs_cm1','Figure 4(c) · Hermitian 1D coupling'),('kappa_1d_direct_abs_cm1','Figure 4(d) · Direct 1D coupling')]
        if target=='fig4d':quantities=quantities[-1:]+quantities[:-1]
        for key,title in quantities:
            plots.append(dict(id=key,title=title,kind='heatmap',csv='pcsel_sweep.csv',x=x,y=y,value=key,
                x_label=axis_label(x),y_label=axis_label(y),value_label=title.split(' · ')[-1]+' (cm^-1)',invalid_statuses=['invalid_geometry','failed']))
    elif labels:
        x=labels[0]
        variant=bool(cfg.get('parameter_sweep',{}).get('variants')) or any(case.get('variant') for case in summary.get('sweep_cases',summary.get('cases',[])))
        # Loss ranks are not tracked branches. Cross-variant raw roots remain in
        # the modes CSV; the comparison opens the meaningful two-curve outputs.
        if not variant:
            plots.append(dict(id='modes',title='Computed modes (untracked branches)',kind='line',csv='pcsel_sweep_modes.csv',x=x,
                y='power_loss_cm1' if cfg['model']=='cwt' else 'total_loss_cm1',series='label',
                filter=dict(model='cwt') if cfg['model']=='cwt' else dict(model='finite',accepted=True),x_label=axis_label(x),y_label='Power loss (cm^-1)'))
        metrics=('g_A_cm1','delta_g_band_cm1','delta_g_A_cm1') if cfg['model']=='cwt' else ('lowest_loss_cm1','delta_g_cm1','eta_substrate','eta_edge','eta_surface')
        for key in metrics:
            spec=dict(id=key,title=metric_labels.get(key,key),kind='line',csv='pcsel_sweep.csv',x=x,y=key,x_label=axis_label(x),y_label=metric_labels.get(key,key),value_label='Calculated two-band loss difference' if key=='delta_g_band_cm1' else metric_labels.get(key,key))
            if variant:spec['series']='variant'
            if target=='fig5' and key=='delta_g_band_cm1':spec['title']='Figure 5(b) · Two lowest band-edge loss difference'
            if target in ('fig9','fig9a') and key in ('lowest_loss_cm1','delta_g_cm1'):
                spec['title']='Figure 9('+('a' if key=='lowest_loss_cm1' else 'b')+') · '+metric_labels[key]
            plots.append(spec)
        if cfg['model'] in ('finite','beam'):
            plots.append(dict(id='efficiencies',title='Figure 6(b) · Substrate and edge emission',kind='multi_line',
                curves=[dict(csv='pcsel_sweep.csv',x=x,y=key,label=title,series='variant' if variant else None) for key,title in [('eta_substrate','Substrate'),('eta_edge','Lateral edge')]],
                x_label=axis_label(x),y_label='Fraction of generated optical power'))
        if target=='fig5':
            # These are published comparison values, never saved solver samples.
            reference=dict(origin='King et al. 2024, p.44950 / Fig.5; DOI 10.1364/OE.537452',role='published_reference',scope='No-DBR comparison only; missing no-DBR thickness prevents an exact computed baseline.')
            band_plot=next((p for p in plots if p['id']=='modes'),next(p for p in plots if p['id']=='g_A_cm1'))
            if band_plot['id']=='modes':band_plot['title']='Figure 5(a) · Four calculated band-edge losses'
            band_plot['reference_lines']=[dict(reference,value=8.7,label='Published no-DBR mode A: 8.7 cm^-1')]
            next(p for p in plots if p['id']=='delta_g_band_cm1')['reference_lines']=[dict(reference,value=16.2,label='Published no-DBR discrimination: 16.2 cm^-1')]
    else:
        if 'vertical_profile.csv' in summary.get('artifacts',[]):
            height=sum(float(layer['thickness_nm']) for layer in cfg['layers'])/1000
            plots.append(dict(id='vertical-combined',title='Figure 2(a) · Index and calculated vertical intensity',kind='multi_line',
                curves=[dict(csv='vertical_profile.csv',x='z_nm',y='index',label='Refractive index',color='#50a8e8',markers=False,x_scale=-.001,x_offset=height),
                    dict(csv='vertical_profile.csv',x='z_nm',y='intensity_per_nm',label='Calculated intensity',color='#ed9366',markers=False,axis='right',x_scale=-.001,x_offset=height,y_scale=1000)],
                x_label='Height from n-side (µm)',y_label='Refractive index',right_y_label='Normalized intensity (µm^-1)',
                note='Saved depth from p-side is converted to height from n-side; intensity is unit-integral normalized, not scaled to the published curve.'))
            for key in ('index','intensity_per_nm'):
                plots.append(dict(id='vertical-'+key,title='Vertical '+key,kind='line',csv='vertical_profile.csv',x='z_nm',y=key,x_label='Depth from p-side (nm)',y_label=key))
        if 'finite_fields.npz' in summary.get('artifacts',[]):
            plots.append(dict(id='finite-spectrum',title='Figure 8(a) · Computed finite-cavity spectrum (unconnected modes)',kind='line',csv='finite_modes.csv',x='wavelength_nm',y='total_loss_cm1',connect=False,filter=dict(accepted=True),x_label='Approximate wavelength (nm)',y_label='Power loss (cm^-1)'))
            for m in sorted([r for r in summary.get('finite_modes',[]) if r.get('accepted',False)],key=lambda r:r['total_loss_cm1'])[:3]:
                plots.append(_finite_field_spec(m,'','Cavity intensity',emitted=False))
        plots.extend(_beam_specs(cfg,summary,''))
    # Saved case fields expose every sampled inset without rerunning or inferring band identity.
    for case in summary.get('sweep_cases',summary.get('cases',[])):
        result=case.get('summary',{});folder=case.get('directory','')
        if not folder or not result:continue
        label=', '.join(f'{axis_label(k)}={v:g}' for k,v in case.get('parameters',{}).items())
        if case.get('variant'):label=case['variant']+' · '+label
        modes=sorted([r for r in result.get('finite_modes',[]) if r.get('accepted',False)],key=lambda r:r['total_loss_cm1'])
        if 'finite_fields.npz' in result.get('artifacts',[]):
            for rank,mode in enumerate(modes[:2]):
                emitted=bool(result.get('emitted_near_field_available'))
                spec=_finite_field_spec(mode,folder,('Near-field inset' if emitted else 'Cavity envelope (older saved output)')+' · '+label+' · loss rank '+str(rank+1),emitted=emitted)
                plots.append(spec)
        plots.extend(_beam_specs(cfg,result,folder))
    # Geometry illustrations explicitly describe the saved input; not a solver result.
    plots.extend([dict(id='stack-schematic',title='Figure 1(a) · Saved vertical structure schematic',kind='device_schematic',json='pcsel_inputs.json',view='stack',note='Input schematic only, with actual layer thicknesses and saved indices; no computed field is implied.'),
        dict(id='cell-schematic',title='Figures 1(b), 2(b) · Saved unit-cell geometry',kind='device_schematic',json='pcsel_inputs.json',view='cell',note='Input schematic only. Coordinates are in lattice periods; triangle theta is the equal base angle.')])
    return dict(schema_version=1,source=study.get('source',{}),figure=target,status=summary.get('status'),
        scope='Actual solver outputs and separately labelled input schematics. Untracked mode ordering, sparse mode search, reconstruction assumptions and unconverged discretizations remain. Optional published reference lines are comparison-only; no fitted curves.',
        assumptions=study.get('assumptions',[]),plots=plots)

def _finite_field_spec(mode,folder,title,emitted=False):
    prefix=folder+'/' if folder else ''
    return dict(id=prefix+('emitted-' if emitted else 'cavity-')+str(mode['mode']),title=title+': returned mode '+str(mode['mode']),kind='field_grid',npz=prefix+'finite_fields.npz',
        array='emitted_near_intensity' if emitted else 'mode_intensity',x='x_um',y='y_um',mode_index=mode['mode'],x_label='x (µm)',y_label='y (µm)',
        value_label='Peak-normalized emitted near-field intensity' if emitted else 'Normalized sum of four basic-wave intensities',
        note='Accepted returned modes are loss-ranked; this does not establish band A/D identity or global mode-search completeness.')

def _beam_specs(cfg,summary,folder):
    prefix=folder+'/' if folder else '';plots=[]
    for item in summary.get('beam_outputs',[]):
        for key,x,y in [('near_display','x_um','y_um'),('far_display','sin_theta_x','sin_theta_y')]:
            far=key=='far_display';quantity='Peak-normalized intensity' if cfg.get('beam_normalization')=='peak' else ('W/sr (paraxial)' if far else 'W/µm²') if cfg.get('beam_normalization')=='calibrated_power' else ('sr^-1 (unit power, paraxial)' if far else 'µm^-2 (unit power)')
            spec=dict(id=prefix+key+'-'+str(item['mode']),title=('Far-field' if far else 'Near-field')+' intensity · mode '+str(item['mode'])+(' · '+folder if folder else ''),kind='field_grid',npz=prefix+item['npz'],array=key,x=x,y=y,x_label='θx (degrees)' if far else 'x (µm)',y_label='θy (degrees)' if far else 'y (µm)',value_label=quantity)
            if far:spec.update(x_transform='arcsin_degrees',y_transform='arcsin_degrees',note='Angular coordinate display is arcsin(saved sine angle), in degrees. Saved paraxial intensity values and their normalization are unchanged.')
            plots.append(spec)
    return plots
