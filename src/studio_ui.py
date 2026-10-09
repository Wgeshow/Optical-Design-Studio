"""Guided desktop-scale interface, sharing the existing validated project model."""
import html
from gradio_compat import gr
import pandas as pd

from model import MAT_COLS, LAYER_COLS, PAT_COLS, MODES, prepare

CSS = """
.gradio-container {max-width:1600px!important; margin:auto!important; padding:24px 30px 50px!important; font-family:Inter,Segoe UI,Arial,sans-serif!important;}
body {background:#f3f6f8!important;}
.studio-header {display:flex; justify-content:space-between; align-items:center; gap:24px; padding:8px 2px 22px;}
.studio-brand {display:flex;align-items:center;gap:14px;}
.studio-mark {background:#0e655f;color:white;font-size:25px;font-weight:750;padding:12px 15px;border-radius:16px;}
.studio-header h1 {font-size:26px!important;line-height:1.25!important;letter-spacing:-.6px;margin:0!important;color:#172c36;}
.studio-header p {color:#5f717d;margin:5px 0 0!important;font-size:14px;}
.studio-local {font-size:12px;color:#17685e;background:#e2f2ec;border:1px solid #c1dfd4;padding:8px 12px;border-radius:20px;white-space:nowrap;}
#workflow-tabs > .tab-wrapper {margin-bottom:14px;}
#workflow-tabs > .tab-wrapper > .tab-container {background:#fff;border:1px solid #dce5e9;border-radius:12px;padding:6px;gap:4px;box-shadow:0 2px 7px #19374408;}
#workflow-tabs > .tab-wrapper > .tab-container button {border-radius:8px!important;font-weight:600!important;flex:1;min-height:42px;white-space:nowrap;}
#workflow-tabs > .tab-wrapper > .tab-container button.selected {background:#0e655f!important;color:#fff!important;border-color:transparent!important;}
.section-intro {padding:3px 0 14px;}
.section-intro h2 {margin:0 0 5px!important;font-size:21px!important;letter-spacing:-.3px;}
.section-intro p {color:#60727e;margin:0!important;max-width:920px;font-size:14px;}
.studio-card {border:1px solid #dbe5e9!important;border-radius:12px!important;background:white!important;padding:18px!important;}
.studio-hint {border-left:3px solid #279184;background:#eaf5f2;border-radius:5px;padding:11px 14px;font-size:13px;color:#245850;line-height:1.5;}
.studio-summary {display:flex;gap:10px;flex-wrap:wrap;margin:5px 0 10px;}
.studio-summary span {background:#edf2f5;border:1px solid #dbe4e8;border-radius:7px;padding:7px 12px;color:#425866;font-size:13px;}
button.primary {font-weight:650!important;box-shadow:0 2px 3px #13483c12;}
.gradio-container button:not(.label-wrap):not(.icon) {min-height:38px;}
.gradio-container .label-wrap {align-items:center;min-height:38px;}
.gradio-container .label-wrap > .icon {flex:0 0 auto;align-self:center;line-height:1;height:1em;}
.gradio-container label span {font-weight:550;}
.gradio-container .tabitem {padding-top:8px;}
.gradio-container table {font-size:13px!important;}
.gradio-container .prose h3 {font-size:17px;letter-spacing:-.2px;}
.gradio-container .prose p {line-height:1.55;}
.gradio-container input:focus,.gradio-container textarea:focus {outline-color:#248f80!important;}
@media(max-width:850px){.gradio-container{padding:12px!important}.studio-header{align-items:flex-start}.studio-local{display:none}#workflow-tabs>.tab-wrapper>.tab-container{overflow-x:auto;flex-wrap:nowrap}#workflow-tabs>.tab-wrapper>.tab-container button{flex:none;min-width:95px}.studio-header h1{font-size:22px!important}}
"""


def theme():
    return gr.themes.Soft(primary_hue='teal',secondary_hue='slate',neutral_hue='slate',
                          font=['Segoe UI','Arial','sans-serif'],font_mono=['Consolas','monospace']).set(
                              body_background_fill='#f3f6f8',block_background_fill='#ffffff',
                              button_primary_background_fill='#0e655f',button_primary_background_fill_hover='#0b524d',
                              block_label_background_fill='#ffffff',block_label_text_color='#475569')


def intro(title, description):
    gr.HTML('<div class="section-intro"><h2>'+html.escape(title)+'</h2><p>'+html.escape(description)+'</p></div>')


def material_catalog(app, materials):
    rows=[]
    for row in app.records(materials,MAT_COLS):
        kind=row.get('Model')
        rows.append({'Material':row.get('Name'),
                     'Optical model':{'table_nk':'Wavelength-dependent n/k','constant_nk':'Constant n/k approximation','constant_eps':'Constant permittivity approximation'}.get(kind,str(kind)),
                     'n (constant only)':row.get('A') if kind=='constant_nk' else '—',
                     'k (constant only)':row.get('B') if kind=='constant_nk' else '—'})
    return pd.DataFrame(rows,columns=['Material','Optical model','n (constant only)','k (constant only)'])


def remove_project_material(app, materials, layers, patterns, selected):
    rows=app.records(materials,MAT_COLS)
    if selected not in {r['Name'] for r in rows}: raise gr.Error('Choose a project material first.')
    used=[r['Name'] for r in app.records(layers,LAYER_COLS) if r['Material']==selected]
    used += [r['Layer']+' region' for r in app.records(patterns,PAT_COLS) if r['Material']==selected]
    if used: raise gr.Error('This material is used by '+', '.join(used)+'. Choose another material in those layers or regions first.')
    return pd.DataFrame([r for r in rows if r['Name']!=selected],columns=MAT_COLS), 'Removed from this project. Saved material presets remain available.'


def build_studio_ui(app):
    from structure_builder import build_structure_builder
    from material_import_ui import build_import_controls
    from material_viewer import build_material_viewer
    from library_ui import build_material_editor,build_library_ui
    from peak_search_ui import build_peak_search_ui
    from target_ui import build_target_ui
    from field_tracking_ui import build_field_tracking_ui
    with gr.Blocks(title='S4 Optical Studio') as demo:
        gr.HTML('<header class="studio-header"><div class="studio-brand"><div class="studio-mark">S⁴</div><div><h1>Optical Studio</h1><p>Build layered structures. Find resonances. Understand the fields.</p></div></div><span class="studio-local">Local workspace · data saved on this computer</span></header>')
        # Canonical data components retain project/API compatibility. Guided forms
        # edit these same tables, so every simulation receives the displayed model.
        materials=gr.Dataframe(app.DEFAULT_MATERIALS,headers=MAT_COLS,datatype=['str','str','number','number','str','str'],interactive=True,label='Material records',render=False)
        layers=gr.Dataframe(app.DEFAULT_LAYERS,headers=LAYER_COLS,interactive=True,label='Layer records — top to bottom',render=False)
        patterns=gr.Dataframe(app.DEFAULT_PATTERNS,headers=PAT_COLS,interactive=True,label='Region records',render=False)
        nkfiles=gr.File(label='Drop optical-constant CSV or TXT files here',file_count='multiple',type='filepath',file_types=['.csv','.txt'],render=False)
        def number(value,label,**kwargs): return gr.Number(value,label=label,render=False,**kwargs)
        ax=number(.77,'Lattice X (µm)',minimum=0)
        ay=number(.77,'Lattice Y (µm)',minimum=0)
        numg=number(32,'Fourier basis count',precision=0,minimum=1,maximum=4096,info='Increase and compare results when checking narrow resonances.')
        mode=gr.Radio(['Wavelength sweep','Angle sweep'],value='Wavelength sweep',label='What would you like to scan?',render=False)
        w0=number(1515,'Start wavelength (nm)'); w1=number(1555,'Stop wavelength (nm)'); ws=number(.1,'Wavelength step (nm)',minimum=0)
        fixed=number(1550,'Wavelength (nm)',minimum=0)
        theta=number(0,'Incidence angle θ (°)'); phi=number(0,'Azimuth φ (°)')
        pol=gr.Dropdown([('p polarized','p'),('s polarized','s'),('45° combination','45° s+p')],value='p',label='Polarization',render=False)
        a0=number(0,'Start angle (°)'); a1=number(60,'Stop angle (°)'); astep=number(2,'Angle step (°)',minimum=0)
        hardware=gr.Dropdown(list(MODES),value=MODES[0],label='Compute mode',render=False)
        workers=number(0,'Worker processes',precision=0,minimum=0,maximum=app.CPUS,info='0 selects automatically. Each worker handles different wavelengths.')
        threads=number(1,'Math threads per worker',precision=0,minimum=1,maximum=app.CPUS)
        chunk=number(8,'Wavelengths per batch',precision=0,minimum=1,maximum=10000)
        device=number(0,'CUDA device index',precision=0,minimum=0)
        threshold=number(1024,'Minimum GPU matrix size',precision=0,minimum=1,
                         info='All matrix dimensions must meet this threshold. 1 allows small products onto the GPU.')
        block=gr.Dropdown([64,128,256,512,1024],value=256,label='GPU tile size',render=False)
        timeout=number(3600,'Time limit per run (seconds)',precision=0,minimum=1)
        strict=gr.Checkbox(False,label='Require GPU work to succeed',render=False)
        settings=[ax,ay,numg,mode,w0,w1,ws,fixed,theta,phi,a0,a1,astep,pol]
        perf=[hardware,workers,threads,device,threshold,block,chunk,timeout,strict]
        from structure_sync import build_structure_summary
        build_structure_summary(materials,layers,patterns,ax,ay)
        with gr.Tabs(elem_id='workflow-tabs'):
            with gr.Tab('Structure',id='structure'):
                intro('Build your layer stack','Start with the incident medium, add your finite layers, and finish with the substrate. Choose a layer to edit its material, thickness, and patterned regions.')
                with gr.Accordion('Unit cell / lattice',open=False):
                    with gr.Row(): ax.render(); ay.render()
                    gr.Markdown('The lattice repeats in X and Y. Layer and hole dimensions have their own clearly labelled units below.')
                builder=build_structure_builder(app,materials,layers,patterns,ax,ay)
                with gr.Accordion('Bulk layer and region tables · advanced',open=False):
                    gr.Markdown('For copy/paste or existing projects. Layer names must be unique; region layer/material names must exist. The guided builder refreshes when these records change.')
                    layers.render(); patterns.render()
            with gr.Tab('Materials',id='materials'):
                intro('Your optical material library','Saved materials are available directly in the structure dropdowns. Import a dataset once, then reuse it across layers and projects.')
                with gr.Tabs():
                    with gr.Tab('Choose materials'):
                        with gr.Row():
                            preset=gr.Dropdown([*app.PRESETS,*app.LIBRARY.presets()],value='Air / Vacuum',label='Saved material or built-in approximation',scale=4)
                            addpreset=gr.Button('Add to this project',variant='primary',scale=1)
                        catalog=gr.Dataframe(material_catalog(app,app.DEFAULT_MATERIALS),interactive=False,label='Materials in this project',show_search='filter',wrap=True,max_height=300)
                        with gr.Row():
                            remove_choice=gr.Dropdown(app.DEFAULT_MATERIALS.Name.tolist(),value=None,label='Project material to remove',scale=4)
                            remove=gr.Button('Remove from project',scale=1)
                        material_status=gr.Markdown('Constant built-in values are approximations. Use wavelength-dependent datasets for a material-specific design.')
                        with gr.Accordion('Advanced material records',open=False):
                            gr.Markdown('Model names: table_nk uses a wavelength table; constant_nk uses A=n, B=k; constant_eps uses A=Re(ε), B=Im(ε).')
                            materials.render()
                        build_material_editor(app.LIBRARY,preset,materials,nkfiles,app.PRESETS,app.records)
                    with gr.Tab('Import CSV'):
                        gr.HTML('<div class="studio-hint">Set the wavelength unit before uploading. The material is added to your project and saved preset library automatically.</div>')
                        with gr.Row():
                            csv_unit=gr.Dropdown([('Nanometers (nm)','nm'),('Micrometers (µm)','um')],value='nm',label='Wavelength unit in the file')
                            csv_name=gr.Textbox(label='Material name (optional)',placeholder='Use the filename when left blank')
                        csv_zero=gr.Checkbox(False,label='This is an n-only dataset: explicitly use k = 0')
                        csv_source=gr.Textbox(value='https://refractiveindex.info/',label='Source page / measurement conditions')
                        nkfiles.render()
                        build_import_controls(app.LIBRARY,materials,preset,nkfiles,app.PRESETS,csv_unit,csv_zero,csv_source,csv_name,include_manual=False)
                    with gr.Tab('Enter n/k values'):
                        build_import_controls(app.LIBRARY,materials,preset,nkfiles,app.PRESETS,csv_unit,csv_zero,csv_source,csv_name,include_upload=False)
                    with gr.Tab('Inspect n and k'):
                        build_material_viewer(app.LIBRARY,materials,preset,nkfiles,app.PRESETS,app.records)
            with gr.Tab('Simulate',id='simulate'):
                intro('Measure the optical response','Scan wavelength or angle for the current structure. Reflection, transmission and absorption appear together, and the full results are saved automatically.')
                with gr.Row():
                    with gr.Column(scale=1,min_width=330,elem_classes='studio-card'):
                        mode.render()
                        with gr.Column() as wavelength_controls:
                            with gr.Row(): w0.render(); w1.render()
                            ws.render()
                            theta.render()
                        with gr.Column(visible=False) as angle_controls:
                            fixed.render()
                            with gr.Row(): a0.render(); a1.render()
                            astep.render()
                        pol.render()
                        with gr.Accordion('Illumination orientation',open=False): phi.render()
                        with gr.Row():
                            run=gr.Button('Run simulation',variant='primary')
                            cancel=gr.Button('Stop',variant='stop')
                        status=gr.Markdown('Ready. Apply any layer or region edits before running.')
                    with gr.Column(scale=2,min_width=460):
                        plot=gr.Plot(label='Reflection · transmission · absorption')
                        with gr.Row():
                            result_file=gr.File(label='Full spectrum CSV')
                            diagnostics=gr.File(label='Run diagnostics')
                        with gr.Accordion('Numerical results',open=False):
                            result_table=gr.Dataframe(label='Preview · first 5,000 rows',interactive=False,show_search='filter')
            with gr.Tab('Optimize',id='optimize'):
                intro('Find a better design','Set the allowed geometry and optical requirements. Use target design to maximize Q near one wavelength, or explore a broader design grid.')
                with gr.Tabs():
                    build_target_ui(app,materials,layers,patterns,nkfiles,settings,perf,include_fields=False,include_tracking=False)
                    search_controls=build_peak_search_ui(materials,layers,patterns,nkfiles,settings,perf,app.make_project,app.run_backend,app.cancel_run,app.records,app.RUNS,app.CPUS,MAT_COLS,LAYER_COLS,PAT_COLS,app.SET_KEYS,library=app.LIBRARY)
            with gr.Tab('Fields',id='fields'):
                intro('Inspect fields and compare designs','Calculate a field map for the current structure, or reopen saved designs to see how the field redistributes.')
                with gr.Tabs():
                    build_target_ui(app,materials,layers,patterns,nkfiles,settings,perf,include_design=False,include_tracking=False)
                    build_field_tracking_ui(app)
            with gr.Tab('Saved work',id='saved'):
                intro('Reopen, share, and continue','Your simulations, material presets and optimization history stay in the local library. Reopen a design or export the full workspace for another computer.')
                with gr.Tabs():
                    with gr.Tab('Results library'):
                        build_library_ui(app.LIBRARY,app.RESOURCE_ROOT,app._compute_lock,app.load_project,[materials,layers,patterns],nkfiles,settings,perf,search_controls,preset,app.PRESETS,wrap_tab=False)
                    with gr.Tab('Project files'):
                        with gr.Row():
                            with gr.Column(elem_classes='studio-card'):
                                gr.Markdown('### Save the current project\nIncludes the structure, run settings, and embedded optical-constant tables.')
                                save=gr.Button('Save project file',variant='primary')
                                project_out=gr.File(label='Portable project JSON')
                            with gr.Column(elem_classes='studio-card'):
                                gr.Markdown('### Open a project\nLoads its layers, materials, patterns and simulation settings into this workspace.')
                                project_in=gr.File(label='Choose a project JSON',type='filepath',file_types=['.json'])
                                load=gr.Button('Open project')
            with gr.Tab('Settings',id='settings'):
                intro('Accuracy and computation','These settings apply to subsequent runs. Start with CPU mode, then adjust resolution and hardware as needed.')
                with gr.Row():
                    with gr.Column(elem_classes='studio-card'):
                        gr.Markdown('### Accuracy & run limits')
                        numg.render(); timeout.render()
                        gr.Markdown('A larger Fourier basis costs more computation. Confirm that peak wavelength, absorption and Q converge as you increase resolution.')
                    with gr.Column(elem_classes='studio-card'):
                        gr.Markdown('### Compute resources')
                        hardware.render(); workers.render()
                        gr.Markdown(f'{app.CPUS} logical CPUs available. Spectra and field solves use the selected mode. ML model fitting uses the CPU.')
                with gr.Accordion('Advanced CPU scheduling',open=False):
                    with gr.Row(): threads.render(); chunk.render()
                    gr.Markdown('Workers × math threads must fit within the available CPU count.')
                with gr.Column(visible=False) as gpu_controls:
                    with gr.Accordion('GPU settings',open=True):
                        with gr.Row(): device.render(); threshold.render(); block.render()
                        strict.render()
                        gr.Markdown('GPU modes accelerate eligible matrix products. Other calculations still use the CPU; small problems may run faster on CPU alone.')
                        from gpu_status import gpu_settings_note
                        gpu_note=gr.Markdown(gpu_settings_note(MODES[0],1024,32))
                        small_gpu=gr.Button('Use GPU for small matrices')
                probe=gr.Button('Check selected runtime')
                probe_status=gr.Markdown('Checks the selected hardware with a small simulation. In GPU mode, the check forces an actual GPU attempt and reports completed GPU products.')
        def refresh_materials(df,selected):
            if isinstance(df,dict) and 'data' in df:
                df=pd.DataFrame(df['data'],columns=df.get('headers',MAT_COLS))
            names=[r['Name'] for r in app.records(df,MAT_COLS) if r.get('Name')]
            return material_catalog(app,df),gr.update(choices=names,value=selected if selected in names else None)
        materials.change(refresh_materials,[materials,remove_choice],[catalog,remove_choice],api_visibility='private',preprocess=False,show_progress='hidden')
        addpreset.click(app.add_preset,[materials,preset],materials,api_name='add_material_preset_to_project')
        remove.click(lambda mat,lay,pat,name:remove_project_material(app,mat,lay,pat,name),[materials,layers,patterns,remove_choice],[materials,material_status],api_name='remove_project_material')
        if 'refresh_materials' in builder:
            preset.change(builder['refresh_materials'],[materials,builder['layer_material'],builder['region_material']],[builder['layer_material'],builder['region_material']],api_visibility='private',**builder['sync_options'])
        mode.change(lambda selected:(gr.update(visible=selected=='Wavelength sweep'),gr.update(visible=selected=='Angle sweep')),mode,[wavelength_controls,angle_controls],api_visibility='private')
        hardware.change(lambda selected:gr.update(visible=selected!=MODES[0]),hardware,gpu_controls,api_visibility='private')
        gr.on([hardware.change,threshold.change,numg.change],gpu_settings_note,[hardware,threshold,numg],gpu_note,
              api_visibility='private',show_progress='hidden',trigger_mode='always_last')
        small_gpu.click(lambda:1,None,threshold,api_visibility='private')
        run.click(app.run_sim,[materials,layers,patterns,nkfiles,*settings,*perf],[plot,result_table,result_file,status,diagnostics],concurrency_id='s4-native',api_name='run_simulation')
        cancel.click(app.cancel_run,None,status,queue=False,api_name='cancel_simulation')
        probe.click(app.test_backend,perf,probe_status,concurrency_id='s4-native',api_name='test_backend')
        save.click(app.save_portable_project,[materials,layers,patterns,nkfiles,*settings,*perf],project_out,api_name='save_portable_project')
        load.click(app.load_project,project_in,[materials,layers,patterns,*settings,*perf],api_name='load_project')
        legacy_save=gr.Button(visible=False)
        legacy_save.click(app.save_project,[materials,layers,patterns,*settings,*perf],project_out,api_name='save_project')
    return demo
