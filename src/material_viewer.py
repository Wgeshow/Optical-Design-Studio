"""Inspect saved or current materials without running S4."""
import cmath
import html
from pathlib import Path
from gradio_compat import gr
import matplotlib.pyplot as plt
import pandas as pd
from model import MAT_COLS, numeric_rows, number


def material_data(library, selected, materials, files, low=800, high=2000):
    if not selected:
        raise ValueError('Select a material')
    row, notes = selected
    mode = str(row.get('Model', '')).strip()
    if mode == 'table_nk':
        project = library.snapshot(dict(materials=[row]), files)
        row = project['materials'][0]
        rows = numeric_rows(library.files_for(project)[0], row.get('WavelengthUnit') or 'nm')
        description = (f"{row['Name']}: wavelength-dependent n,k; {len(rows):,} samples, "
                       f'{rows[0][0]:g}–{rows[-1][0]:g} nm. S4 linearly interpolates n and k between samples. '
                       'Outside this range the existing solver clamps endpoint values and issues a warning.')
    elif mode in ('constant_nk', 'constant_eps'):
        low, high = number(low, 'Graph start wavelength'), number(high, 'Graph stop wavelength')
        if low <= 0 or high <= low:
            raise ValueError('Constant-material graph range must have 0 < start < stop')
        a, b = number(row.get('A'), 'A'), number(row.get('B'), 'B', default=0)
        if mode == 'constant_eps':
            nk = cmath.sqrt(complex(a, b))
            n, k = nk.real, nk.imag
        else:
            n, k = a, b
        rows = [[low, n, k], [high, n, k]]
        description = f"{row['Name']}: explicitly constant approximation, n={n:g}, k={k:g}. Horizontal lines are not measured dispersion."
    else:
        raise ValueError('Enter a valid material model before previewing')
    return pd.DataFrame(rows, columns=['wavelength_nm', 'n', 'k']), description, notes


def build_material_viewer(library, materials, preset, uploads, builtins, records):
    def frame(df):
        return pd.DataFrame(df['data'],columns=df.get('headers',MAT_COLS)) if isinstance(df,dict) and 'data' in df else df

    def choices(df):
        df=frame(df)
        current = [('Project · ' + str(row['Name']), 'table:' + str(row['Name']))
                   for row in records(df, MAT_COLS) if row.get('Name')]
        return current + [('Library · ' + key, 'preset:' + key) for key in [*builtins, *library.presets()]]

    def refresh(df, selected):
        items = choices(df)
        keys = [value for _, value in items]
        return gr.update(choices=items, value=selected if selected in keys else (keys[0] if keys else None))

    def follow_preset(key, df):
        items = choices(df)
        value = 'preset:' + key if key else None
        return gr.update(choices=items, value=value)

    def draw(key, df, files, low, high):
        df=frame(df)
        try:
            notes = ''
            if key and key.startswith('table:'):
                name = key[len('table:'):]
                row = next((r for r in records(df, MAT_COLS) if str(r.get('Name')) == name), None)
                if row is None:
                    raise ValueError('This material is no longer in the current table')
            elif key and key.startswith('preset:'):
                name = key[len('preset:'):]
                if name in builtins:
                    row = dict(zip(MAT_COLS, builtins[name]))
                    notes = 'Built-in constant approximation. No wavelength-resolved source table is attached.'
                else:
                    saved = library.presets()[name]
                    row = saved['project']['materials'][0]
                    notes = saved.get('notes', '')
            else:
                raise ValueError('Choose a material to plot')
            data, description, notes = material_data(library, (row, notes), df, files, low, high)
            fig, axes = plt.subplots(2, 1, sharex=True, figsize=(8, 6))
            for axis, column, color, label in zip(axes, ('n', 'k'), ('tab:blue', 'tab:orange'),
                                                 ('Refractive index n', 'Extinction coefficient k')):
                axis.plot(data.wavelength_nm, data[column], color=color, linewidth=1.8)
                axis.set_ylabel(label)
                axis.grid(alpha=.25)
                axis.ticklabel_format(axis='y', useOffset=False)
            axes[0].set_title(str(row['Name']) + (' — constant approximation' if row['Model'] != 'table_nk' else ' — wavelength-dependent'))
            axes[1].set_xlabel('Wavelength (nm)')
            fig.tight_layout()
            plt.close(fig)
            return fig, data.head(5000), html.escape(description) + '\n\n' + html.escape(notes)
        except Exception as exc:
            return None, pd.DataFrame(columns=['wavelength_nm', 'n', 'k']), '**Cannot plot material:** ' + html.escape(str(exc))

    with gr.Column(elem_classes='studio-card'):
        gr.Markdown('### Optical constants\nChoose a project material or library dataset to inspect n and k. Wavelength-dependent curves use their saved data; constant approximations use the display range.')
        initial = materials.value
        if isinstance(initial, dict) and 'data' in initial:
            initial = pd.DataFrame(initial['data'], columns=initial['headers'])
        initial_key = 'table:'+str(initial.iloc[0]['Name']) if len(initial) else None
        initial_graph, initial_values, initial_status = draw(initial_key,initial,[],800,2000)
        selection = gr.Dropdown(choices(initial), value=initial_key, label='Material to inspect')
        with gr.Row():
            with gr.Row() as constant_range:
                low = gr.Number(800, label='Constant-material graph start (nm)')
                high = gr.Number(2000, label='Constant-material graph stop (nm)')
            redraw = gr.Button('Refresh material graph')
        graph = gr.Plot(value=initial_graph,label='n(λ) and k(λ)')
        status = gr.Markdown(initial_status)
        with gr.Accordion('Optical constant values · first 5,000 samples',open=False):
            values = gr.Dataframe(value=initial_values,interactive=False, label='Wavelength (nm), n and k',show_search='filter')
        inputs = [selection, materials, uploads, low, high]
        outputs = [graph, values, status]
        selection.change(draw, inputs, outputs, api_name='plot_material_nk')
        redraw.click(draw, inputs, outputs, api_name='refresh_material_nk')
        materials.change(refresh, [materials, selection], selection, api_visibility='private',preprocess=False).then(draw,inputs,outputs,api_visibility='private',show_progress='hidden')
        preset.change(follow_preset, [preset, materials], selection, api_visibility='private',preprocess=False)
        def show_range(key,df):
            df=frame(df)
            if key and key.startswith('table:'):
                row=next((r for r in records(df,MAT_COLS) if str(r.get('Name'))==key[6:]),{})
            elif key and key.startswith('preset:'):
                name=key[7:]
                row=dict(zip(MAT_COLS,builtins[name])) if name in builtins else library.presets().get(name,{}).get('project',{}).get('materials',[{}])[0]
            else:
                row={}
            return gr.update(visible=row.get('Model')!='table_nk')
        selection.change(show_range,[selection,materials],constant_range,api_visibility='private',show_progress='hidden',preprocess=False)
