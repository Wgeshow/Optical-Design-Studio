"""Target-wavelength inverse design and native field-map controls."""
import copy
import html
import json
import math
from pathlib import Path
from gradio_compat import gr
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from data_library import read_json,write_json
from model import MAT_COLS,LAYER_COLS,PAT_COLS,prepare,performance,number,integer
from ml_optimizer import validate_ml
from peak_optimizer import BOUND_COLS,parse_search
from bounds_editor import build_bounds_editor, build_hole_editor, finite_layers
from structure_sync import air_materials

HOLE_COLS=['Layer','Shape','MinX_um','MaxX_um','MinY_um','MaxY_um']


def target_project(project,holes,extra,target,tolerance,min_q,half_window,step,grid_steps):
    project=copy.deepcopy(project)
    target=number(target,'Target wavelength',minimum=0)
    tolerance=number(tolerance,'Wavelength tolerance',minimum=0)
    min_q=number(min_q,'Minimum Q',minimum=1)
    half_window=number(half_window,'Search half-window',minimum=0)
    step=number(step,'Wavelength step',minimum=0)
    grid_steps=integer(grid_steps,'Geometry grid points',2)
    if grid_steps>101 or target<=half_window or half_window<=tolerance or tolerance<=0 or step<=0:
        raise ValueError('Use positive wavelengths/step, 0 < tolerance < half-window < target, and 2–101 geometry points')
    if len(holes)<1: raise ValueError('Add at least one PCS layer with hole bounds')
    finite={r['Name'] for r in project['layers'][1:-1]}
    names=[str(r['Layer']) for r in holes]
    if len(set(names))!=len(names) or any(n not in finite for n in names):
        raise ValueError('List each finite PCS layer once; names must match Structure')
    air=next((r['Name'] for r in project['materials'] if r['Model']=='constant_nk' and r.get('A')==1 and r.get('B')==0),None)
    if air is None: raise ValueError('Add an explicit air material with constant n=1, k=0')
    air_names=air_materials(project['materials'])
    bounds=list(extra)
    for row in holes:
        shape=str(row['Shape']).strip().lower()
        if shape not in ('circle','ellipse','rectangle'): raise ValueError('Hole shape must be circle, ellipse or rectangle')
        low,high=number(row['MinX_um'],'Min X'),number(row['MaxX_um'],'Max X')
        ly,hy=(0.,0.) if shape=='circle' else (number(row['MinY_um'],'Min Y'),number(row['MaxY_um'],'Max Y'))
        if low<=0 or high<low or shape!='circle' and (ly<=0 or hy<ly): raise ValueError('Hole sizes must be positive with max >= min')
        candidates=[i for i,p in enumerate(project['patterns']) if p['Layer']==row['Layer'] and p['Material'] in air_names]
        if len(candidates)>1:
            raise ValueError(f"Layer {row['Layer']} has multiple air regions. Use Explore designs and its pattern dropdown to vary a specific hole; the Structure regions were kept.")
        if candidates:
            position=candidates[0]
            project['patterns'][position].update(Shape=shape,SizeX_um=(low+high)/2,SizeY_um=(ly+hy)/2)
        else:
            project['patterns'].append(dict(zip(PAT_COLS,[shape,row['Layer'],air,0.,0.,(low+high)/2,(ly+hy)/2,0.])))
            position=len(project['patterns'])-1
        index=str(position+1)
        bounds.append(dict(zip(BOUND_COLS,['radius' if shape=='circle' else 'size_x',index,low,high,(high-low)/(grid_steps-1) or .001,''])))
        if shape!='circle': bounds.append(dict(zip(BOUND_COLS,['size_y',index,ly,hy,(hy-ly)/(grid_steps-1) or .001,''])))
    project['settings'].update(mode='Wavelength sweep',wl_start_nm=target-half_window,wl_stop_nm=target+half_window,wl_step_nm=step)
    return project,bounds


def plot_fields(directory):
    path=Path(directory)/'electric_fields.csv'
    data=pd.read_csv(path)
    model=read_json(Path(directory)/'field_model.json')['model']
    fig,axes=plt.subplots(1,2,figsize=(12,5))
    for axis,plane,vertical,components in ((axes[0],'xy','y_um',('Ex_real','Ey_real')),(axes[1],'xz','z_um',('Ex_real','Ez_real'))):
        frame=data[data.plane==plane]
        if frame.empty:
            axis.text(.5,.5,'No map sampled',ha='center')
            continue
        table=frame.pivot(index=vertical,columns='x_um',values='E2').sort_index()
        artist=axis.pcolormesh(table.columns,table.index,table.values,shading='nearest',cmap='turbo')
        fig.colorbar(artist,ax=axis,label='|E|² / incident |E|²')
        subset=frame.iloc[::max(1,len(frame)//160)]
        axis.quiver(subset.x_um,subset[vertical],subset[components[0]],subset[components[1]],color='black',alpha=.65)
        axis.set(xlabel='x (µm)',ylabel=vertical.replace('_um',' (µm)'),title='XY layer midplane' if plane=='xy' else 'XZ cross-section (y=0)')
        if plane=='xy':
            from matplotlib.patches import Circle, Ellipse, Rectangle
            for region in model['patterns']:
                if region['layer'] not in set(frame.layer): continue
                common=dict(fill=False,edgecolor='white',linewidth=1.3)
                center=(region['cx'],region['cy'])
                if region['shape']=='circle': outline=Circle(center,region['sx'],**common)
                elif region['shape']=='ellipse': outline=Ellipse(center,2*region['sx'],2*region['sy'],angle=region['angle'],**common)
                else: outline=Rectangle((center[0]-region['sx']/2,center[1]-region['sy']/2),region['sx'],region['sy'],angle=region['angle'],rotation_point='center',**common)
                axis.add_patch(outline)
        if plane=='xz':
            depth=0.
            for structure_layer in model['layers'][1:-1]:
                axis.axhline(depth,color='white',alpha=.6,lw=.7)
                depth+=structure_layer['thickness']
            axis.axhline(depth,color='white',alpha=.6,lw=.7)
            for layer,group in frame.groupby('layer',sort=False):
                axis.text(frame.x_um.max(),group[vertical].mean(),str(layer),ha='right',fontsize=8,color='white')
    fig.suptitle('Electric-field intensity; arrows show Re(E) at the chosen incident phase')
    fig.tight_layout()
    fig.savefig(Path(directory)/'electric_field_maps.png',dpi=160)
    plt.close(fig)
    return fig


def build_target_ui(app,materials,layers,patterns,uploads,settings,perf_inputs, *, include_design=True, include_fields=True, include_tracking=True):
    def populate(layer_df,pattern_df):
        rows=[]
        used=set()
        for p in app.records(pattern_df,PAT_COLS):
            if p['Layer'] in used: continue
            used.add(p['Layer'])
            rows.append([p['Layer'],p['Shape'],p['SizeX_um'],p['SizeX_um'],p['SizeY_um'],p['SizeY_um']])
        return pd.DataFrame(rows,columns=HOLE_COLS)

    def search(request:gr.Request,mat,lay,pat,files,hole_rows,extras,target,tol,qmin,window,step,geo_points,trials,initial,finalists,reuse,history,fields,field_grid,map_grid,*values):
        yield None,pd.DataFrame(),None,'Validating target search…',None
        iterator=None
        try:
            setting_count=len(settings)+len(perf_inputs)
            track_resonance=bool(values[setting_count]) if len(values)>setting_count else True
            values=values[:setting_count]
            project=app.make_project(mat,lay,pat,values)
            project,bounds=target_project(project,app.records(hole_rows,HOLE_COLS),app.records(extras,BOUND_COLS),target,tol,qmin,window,step,geo_points)
            project=app.LIBRARY.snapshot(project,files)
            model=prepare(project['materials'],project['layers'],project['patterns'],app.LIBRARY.files_for(project),project['settings'])
            # Explicitly sample the target and both tolerance boundaries.
            wavelengths=sorted(set([p[1] for p in model['points']]+[float(target),float(target-tol),float(target+tol),float(target+window)]))
            model['points']=[[i,w,model['points'][0][2]] for i,w in enumerate(wavelengths)]
            cfg=parse_search(model,bounds,dict(search_mode='ML assisted',ml_trials=trials,initial_designs=initial,
                finalists=finalists,design_budget=trials,point_budget=200000,refinement_rounds=3))
            validate_ml(cfg,model)
            cfg.update(task='target',all_shape_bridges=True,target_nm=float(target),tolerance_nm=float(tol),minimum_q=float(qmin),
                history_limit=integer(history,'History record limit',1),reuse_saved=bool(reuse),use_fields=bool(fields),
                track_resonance=track_resonance,
                field_grid=integer(field_grid,'Field sample grid',3),map_grid=integer(map_grid,'Map grid',3),project=project,input_bounds=bounds)
            if cfg['history_limit']>2000 or cfg['field_grid']>30 or cfg['map_grid']>80: raise ValueError('History <= 2000; training field grid <= 30; map grid <= 80')
            p=performance(project['performance'],len(model['points']),app.CPUS)
            iterator=app.run_backend(model,p,app.session_key(request),search=cfg)
            for event in iterator:
                if event['kind']=='search_progress':
                    yield gr.skip(),gr.skip(),gr.skip(),html.escape(event['text'])+f" · {event['points']:,} spectral points",gr.skip()
                elif event['kind']=='search_complete':
                    directory=Path(event['directory'])
                    summary=event['summary']
                    fig=plot_fields(directory/'recommended_fields') if (directory/'recommended_fields/electric_fields.csv').exists() else None
                    table=pd.read_csv(directory/'target_results.csv')
                    result_path=directory/'recommended_design.json'
                    text=f"**{summary['status'].title()}.** Reused {summary['reused_training_records']} compatible saved spectra and {summary['reused_field_records']} field datasets; {summary['new_evaluations']} new evaluations. "
                    text+=f"Recommended verified Q: {summary['maximum_verified_Q']:.6g}." if summary['maximum_verified_Q'] else '**No verified design meets all requested constraints yet.**'
                    text+='\n\n'+summary['scope']+'\n\n'+summary['reason']
                    yield fig,table,app.LIBRARY.export(directory.name),text,str(result_path) if result_path.exists() else None
                elif event['kind'] in ('error','cancelled'):
                    yield None,pd.DataFrame(),None,html.escape(event['error']),None
        except Exception as exc:
            yield None,pd.DataFrame(),None,'**Error:** '+html.escape(str(exc)),None
        finally:
            if iterator is not None: iterator.close()

    def apply(path):
        if not path: raise gr.Error('No verified recommendation is available')
        record=read_json(path)
        folder=Path(path).parent
        project=app.LIBRARY.from_model(record['model'],read_json(folder/'project.json'))
        save=folder/'recommended_project.json'
        write_json(save,project)
        return (*app.load_project(str(save)),app.LIBRARY.files_for(project) or None)

    def field_run(request:gr.Request,mat,lay,pat,files,wavelength,layer,resolution,*values):
        yield None,None,'Preparing native field map…'
        iterator=None
        try:
            project=app.LIBRARY.snapshot(app.make_project(mat,lay,pat,values),files)
            project['settings'].update(mode='Wavelength sweep',wl_start_nm=wavelength,wl_stop_nm=wavelength)
            model=prepare(project['materials'],project['layers'],project['patterns'],app.LIBRARY.files_for(project),project['settings'])
            p=performance(project['performance'],1,app.CPUS)
            cfg=dict(task='fields',wavelength_nm=float(wavelength),layer=layer.strip(),grid=integer(resolution,'Map grid',3),maps=True,project=project)
            iterator=app.run_backend(model,p,app.session_key(request),search=cfg)
            for event in iterator:
                if event['kind']=='search_complete':
                    directory=Path(event['directory'])
                    from gpu_status import acceleration_summary
                    diagnostics=event.get('summary',{}).get('field_features',{}).get('acceleration',{})
                    status='Saved XY and XZ fields, complex E components and layer concentration features. Arrows show Re(E); colors show |E|².'
                    if diagnostics:
                        status+='\n\n'+acceleration_summary(diagnostics)
                        status+=''.join('\n\n'+html.escape(warning) for warning in diagnostics.get('warnings',[]))
                    yield plot_fields(directory/'fields'),app.LIBRARY.export(directory.name),status
                elif event['kind'] in ('error','cancelled'):
                    yield None,None,html.escape(event['error'])
        except Exception as exc:
            yield None,None,'**Error:** '+html.escape(str(exc))
        finally:
            if iterator is not None: iterator.close()

    if include_design:
        with gr.Tab('Target wavelength'):
            gr.Markdown('### Find a high-Q design at your wavelength\nChoose a target, set the allowed hole sizes, and search. Eligible designs must have **absorption above 99%**, satisfy your wavelength and Q limits, and pass the fabrication checks.')
            with gr.Row():
                target=gr.Number(1550,minimum=0,label='Target wavelength (nm)')
                tolerance=gr.Number(5,minimum=0,label='Wavelength tolerance ± (nm)',info='A peak may lie this far above or below the target.')
                qmin=gr.Number(1000,minimum=1,label='Minimum Q factor')
            gr.Markdown('#### 1. Set hole ranges for your PCS layers')
            gr.Markdown('The applied Structure is shared with this search. Choose its layers below; single air holes appear automatically. Only parameters with saved ranges are varied.')
            holes=build_hole_editor(layers,patterns,materials)
            with gr.Accordion('Also vary lattice spacing, layer thickness, or layer materials',open=False):
                extras=build_bounds_editor(materials,layers,patterns,label='Additional design ranges',
                    allowed={'lattice_square','lattice_x','lattice_y','thickness','layer_material'})
            gr.Markdown('Circle radius / lattice spacing must stay below **0.6**. Every hole shape must leave a positive bridge to its periodic neighbors.')
            gr.Markdown('#### 2. Choose how much to explore')
            with gr.Row():
                trials=gr.Number(40,precision=0,minimum=2,label='New designs to evaluate',info='Larger searches take longer and explore more possibilities.')
                reuse=gr.Checkbox(True,label='Learn from compatible saved results')
                fields=gr.Checkbox(True,label='Use electric-field information during learning')
            with gr.Accordion('Wavelength sampling and verification',open=False):
                with gr.Row():
                    window=gr.Number(20,minimum=0,label='Search range: target ± (nm)',info='Must be wider than the wavelength tolerance.')
                    step=gr.Number(.2,minimum=0,label='Initial wavelength step (nm)',info='Use a smaller step to detect narrower peaks.')
                    grid_points=gr.Number(21,precision=0,minimum=2,maximum=101,label='Size values between each hole minimum and maximum')
                with gr.Row():
                    initial=gr.Number(8,precision=0,minimum=2,label='Initial designs before guided learning')
                    finalists=gr.Number(3,precision=0,minimum=1,label='Best designs to verify at higher resolution')
                gr.Markdown('Verification uses a larger Fourier basis and finer wavelength sampling. A design qualifies only when absorption, wavelength, and Q agree across resolutions. Unresolved narrow peaks cannot qualify.')
            with gr.Accordion('Saved training data and field detail',open=False):
                history=gr.Number(300,precision=0,minimum=1,maximum=2000,label='Maximum saved observations to reuse')
                track_resonance=gr.Checkbox(True,label='Compare fields at both the target and the moving resonance',info='Adds field calculations to distinguish peak shifts from changes in the field pattern.')
                with gr.Row():
                    field_grid=gr.Number(6,precision=0,minimum=3,maximum=30,label='Training field samples along X and Y')
                    map_grid=gr.Number(25,precision=0,minimum=3,maximum=80,label='Final field-map samples along each axis')
                gr.Markdown('Field measurements help choose designs to evaluate. Final acceptance uses simulated absorption and Q. All compatible saved data remain available for later searches.')
            fields.change(lambda enabled: [gr.Checkbox(interactive=enabled),gr.Number(interactive=enabled),gr.Number(interactive=enabled)],fields,[track_resonance,field_grid,map_grid],queue=False,api_visibility='private')
            reuse.change(lambda enabled: gr.Number(interactive=enabled),reuse,history,queue=False,api_visibility='private')
            with gr.Row():
                start=gr.Button('Find a design',variant='primary')
                stop=gr.Button('Stop search',variant='stop')
            status=gr.Markdown('Ready. Add at least one hole range to begin.')
            recommendation=gr.State(None)
            gr.Markdown('#### 3. Review and use the result')
            apply_button=gr.Button('Use verified design in Structure',variant='primary')
            plot=gr.Plot(label='Recommended design: electric-field maps')
            with gr.Accordion('All evaluated designs and design conditions',open=False):
                table=gr.Dataframe(interactive=False,label='Eligible designs ranked by Q')
            bundle=gr.File(label='Download complete search, designs, spectra, and fields')
            gr.Markdown('The result is the highest verified Q found within this search. A finite search cannot guarantee the continuous global maximum. The run timeout and spectral budget also cover final verification.')
            start.click(search,[materials,layers,patterns,uploads,holes,extras,target,tolerance,qmin,window,step,grid_points,trials,initial,finalists,reuse,history,fields,field_grid,map_grid,*settings,*perf_inputs,track_resonance],
                        [plot,table,bundle,status,recommendation],concurrency_id='s4-native',api_name='search_target_wavelength')
            stop.click(app.cancel_run,None,status,queue=False,api_name='cancel_target_search')
            apply_button.click(apply,recommendation,[materials,layers,patterns,*settings,*perf_inputs,uploads],api_name='apply_target_design')
    if include_fields:
        with gr.Tab('Current structure'):
            gr.Markdown('### See where the field concentrates\nCalculate a top view within a layer and a side view through the current stack. Colors show field intensity relative to the incident field; arrows show the real electric field at one phase.')
            with gr.Row():
                wavelength=gr.Number(1550,minimum=0,label='Wavelength (nm)')
                layer=gr.Dropdown([('Automatic: first patterned layer','')]+[(name,name) for name in finite_layers(layers.value)],value='',label='Layer for the top view',allow_custom_value=False)
            with gr.Accordion('Map detail',open=False):
                resolution=gr.Slider(3,80,value=25,step=1,label='Samples along each map axis',info='Higher values show more spatial detail and take longer.')
                gr.Markdown('The XY view is at the middle of the selected layer. The XZ view crosses the stack at y = 0. These are steady-state fields at the chosen wavelength.')
            with gr.Row():
                start_fields=gr.Button('Calculate field maps',variant='primary')
                cancel_fields=gr.Button('Stop calculation',variant='stop')
            field_status=gr.Markdown('Ready. Select a wavelength and a layer.')
            field_plot=gr.Plot(label='Top and side views of the electric field')
            field_bundle=gr.File(label='Download field maps, samples, and structure')
            def refresh_field_layers(value,current):
                options=finite_layers(value)
                return gr.Dropdown(choices=[('Automatic: first patterned layer','')]+[(name,name) for name in options],value=current if current in options else '')
            layers.change(refresh_field_layers,[layers,layer],layer,trigger_mode='always_last',concurrency_limit=1,preprocess=False,api_visibility='private')
            start_fields.click(field_run,[materials,layers,patterns,uploads,wavelength,layer,resolution,*settings,*perf_inputs],
                               [field_plot,field_bundle,field_status],concurrency_id='s4-native',api_name='calculate_electric_fields')
            cancel_fields.click(app.cancel_run,None,field_status,queue=False,api_name='cancel_electric_fields')
    if include_tracking:
        from field_tracking_ui import build_field_tracking_ui
        build_field_tracking_ui(app)
