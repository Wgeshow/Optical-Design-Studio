"""Portable device preset from the electrical study, with undoped optical data."""
import base64
import hashlib
from pathlib import Path


LAYERS=(('p+ GaAs','GaAs_p_plus','GaAs',50.),
        ('p GaAs','GaAs_p','GaAs',150.),
        ('Al0.5Ga0.5As','AlGaAs_50','AlGaAs',20.),
        ('n GaAs','GaAs_n','GaAs',150.),
        ('n+ GaAs','GaAs_n_plus','GaAs',50.))


def device_project(model='explicit_ito',ito_thickness_nm=40.,ito_density_cm3=8e20):
    from electrical_solver import validate_options
    options=validate_options(dict(model=model,ito_thickness_nm=ito_thickness_nm,
                                  ito_density_cm3=ito_density_cm3))
    materials=[dict(Name='Air',Model='constant_nk',A=1.,B=0.,DataFile='',WavelengthUnit='nm')]
    embedded={};provenance=[]
    datasets={'GaAs':'Skauli', 'AlGaAs':'Adachi alloy dispersion, x=0.5',
              'ITO':'Minenkov glass sample', 'Glass':'Rubin clear soda-lime',
              'Ti':'Rakic Lorentz-Drude', 'Au':'Johnson'}
    for name in datasets:
        payload=(Path(__file__).resolve().parent/'electrical_materials'/(name+'.csv')).read_bytes()
        digest=hashlib.sha256(payload).hexdigest();asset='nk_'+digest[:24]+'.csv'
        row=dict(Name=name,Model='table_nk',A=0.,B=0.,DataFile=asset,WavelengthUnit='nm')
        materials.append(row)
        embedded[asset]=dict(sha256=digest,base64=base64.b64encode(payload).decode('ascii'),original_name=name+'.csv')
        note=('Electrical study reference: '+datasets[name]+'. Sampled 1100–1200 nm; '
              'baseline optical constants, not measured values for this device. '
              'GaAs baseline is undoped; ITO baseline already includes its sample carrier response. '
              'Database snapshot c5c2f188e848453def5970e347399d653df2ffc2.')
        provenance.append(dict(material=row.copy(),label=name+' electrical study reference',notes=note,source_notes=note))
    layers=[dict(Name='Incident_air',Thickness_um=0.,Material='Air')]
    mapping={};patterns=[]
    for source,name,material,thickness in LAYERS:
        layers.append(dict(Name=name,Thickness_um=thickness/1000,Material=material))
        mapping[source]=dict(layer=name,material=material)
        patterns.append(dict(Shape='circle',Layer=name,Material='Air',CenterX_um=0.,CenterY_um=0.,SizeX_um=.046,SizeY_um=0.,Angle_deg=0.))
    for name,thickness in (('ITO',options['ito_thickness_nm']/1000),('Glass',550.),('Ti',.003),('Au',.2)):
        layers.append(dict(Name=name,Thickness_um=thickness,Material=name))
    mapping['ITO']=dict(layer='ITO',material='ITO')
    layers.append(dict(Name='Exit_air',Thickness_um=0.,Material='Air'))
    options.update(optical_enabled=False,optical_mapping=mapping,optical_reference='undoped',
                   interband=True,interband_extrapolation=True,electro_optic=True,
                   reference_nm=1157.,tracking_window_nm=1.,optical_slices_per_layer=8)
    return dict(format_version=3,materials=materials,layers=layers,patterns=patterns,
        settings=dict(ax_um=.444,ay_um=.444,NumG=128,mode='Wavelength sweep',
            wl_start_nm=1100.,wl_stop_nm=1200.,wl_step_nm=.1,fixed_wl_nm=1150.,
            theta_deg=0.,phi_deg=0.,angle_start=0.,angle_stop=60.,angle_step=2.,polarization='45° s+p'),
        optical_constants=embedded,material_provenance=provenance,
        desktop_search={'electrical':options},
        device_metadata=dict(model_scope='Fixed contacts-only 100 µm square electrical preset. '
            '40 nm ITO is explicit by default; interface and ITO parameters remain assumptions. '
            'Optics uses an active-area electrical average in a periodic 444 nm cell.',
            baseline='Undoped GaAs tables; ITO carrier correction relative to its nominal bulk state.'))
