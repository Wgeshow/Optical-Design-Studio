"""Peak-search tab for the existing Gradio application."""
import html
import json
from pathlib import Path
import uuid
from gradio_compat import gr
import pandas as pd
import matplotlib.pyplot as plt
from model import prepare, performance
from bounds_editor import build_bounds_editor
from peak_optimizer import BOUND_COLS, SEARCH_KEYS, SEARCH_DEFAULTS, parse_search
from ml_optimizer import MODES, ML_KEYS, ML_DEFAULTS, validate_ml
ALL_KEYS = SEARCH_KEYS + ML_KEYS
ALL_DEFAULTS = SEARCH_DEFAULTS + ML_DEFAULTS


def build_peak_search_ui(materials, layers, patterns, files, settings, perf_inputs,
                         make_project, run_backend, cancel_run, records, runs, cpus,
                         mat_cols, layer_cols, pat_cols, set_keys, library=None):
    def current_bounds(layer_df, pattern_df, ax, ay):
        rows = []
        if ax == ay:
            rows.append(['lattice_square', '', ax, ax, .01, ''])
        else:
            rows.extend([['lattice_x', '', ax, ax, .01, ''], ['lattice_y', '', ay, ay, .01, '']])
        for row in records(layer_df, layer_cols)[1:-1]:
            rows.append(['thickness', row['Name'], row['Thickness_um'], row['Thickness_um'], .01, ''])
            rows.append(['layer_material', row['Name'], None, None, None, row['Material']])
        for i, row in enumerate(records(pattern_df, pat_cols), 1):
            if str(row.get('Shape', '')).lower() == 'circle':
                rows.append(['radius', str(i), row['SizeX_um'], row['SizeX_um'], .005, ''])
            else:
                rows.extend([[p, str(i), row[k], row[k], .005, ''] for p, k in [('size_x', 'SizeX_um'), ('size_y', 'SizeY_um')]])
            rows.append(['pattern_material', str(i), None, None, None, row['Material']])
        return pd.DataFrame(rows, columns=BOUND_COLS)

    def run_search(request: gr.Request, mat, lay, pat, uploads, bounds_df, resume_file, *values):
        yield None, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None, 'Validating search...', None
        iterator = None
        try:
            count = len(settings)+len(perf_inputs)
            project = make_project(mat, lay, pat, values[:count])
            if library is not None:
                project = library.snapshot(project, uploads)
                uploads = library.files_for(project)
            model = prepare(project['materials'], project['layers'], project['patterns'], uploads, project['settings'])
            stop = float(project['settings']['wl_stop_nm'])
            if model['mode'] == 'Wavelength sweep' and model['points'][-1][1] < stop:
                model['points'].append([len(model['points']), stop, model['points'][0][2]])
            bounds_records = records(bounds_df, BOUND_COLS)
            cfg = parse_search(model, bounds_records, dict(zip(ALL_KEYS, values[count:])))
            if cfg.get('search_mode', 'Exhaustive grid') != 'Exhaustive grid':
                validate_ml(cfg, model)
                if resume_file:
                    if Path(resume_file).stat().st_size > 50 * 1024 * 1024:
                        raise ValueError('Resume JSON exceeds the 50 MB upload limit')
                    cfg['resume_history'] = json.loads(Path(resume_file).read_text(encoding='utf-8-sig'))
            elif resume_file:
                raise ValueError('Resume history is supported in ML assisted / Hybrid verified modes')
            cfg['input_bounds'] = bounds_records
            cfg['project'] = project
            p = performance(project['performance'], len(model['points']), cpus)
            iterator = run_backend(model, p, getattr(request, 'session_hash', None) or 'local', search=cfg)
            for event in iterator:
                if event['kind'] == 'search_progress':
                    text = f"**Design / observation {event['design']:,}** | budget {event['total']:,} | {event['points']:,} spectral points completed. {html.escape(event['text'])}"
                    yield gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip(), text, gr.skip()
                elif event['kind'] in ('error', 'cancelled'):
                    yield None, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None, '**Search failed:** '+html.escape(event['error']), None
                elif event['kind'] == 'search_complete':
                    directory = Path(event['directory'])
                    summary = event['summary']
                    df = pd.read_csv(directory/'design_results.csv')
                    ties = pd.read_csv(directory/'matching_best.csv')
                    feasible = pd.read_csv(directory/'above_target_by_Q.csv')
                    spectrum = pd.read_csv(directory/'best_spectrum.csv')
                    fig = None
                    if not spectrum.empty:
                        fig, axis = plt.subplots(figsize=(8, 5))
                        axis.plot(spectrum.wavelength_nm, spectrum.A, label='Absorption')
                        index = spectrum.A.idxmax()
                        axis.scatter([spectrum.loc[index, 'wavelength_nm']], [spectrum.loc[index, 'A']], color='red', label='Highest sampled peak')
                        axis.axhline(cfg['absorption_target'], color='gray', linestyle='--', label='Acceptance threshold')
                        axis.set(xlabel='Wavelength (nm)', ylabel='Absorptance (fraction)', title='Best absorption design found')
                        axis.grid(alpha=.25)
                        axis.legend()
                        fig.tight_layout()
                        fig.savefig(directory / 'best_spectrum.png', dpi=160)
                        plt.close(fig)
                    best = 'none' if summary['best_absorption'] is None else f"{100*summary['best_absorption']:.8f}%"
                    text = (f"**{summary['status'].title()}. Best absorption found: {best}.** "
                            f"{summary['evaluated']} designs evaluated; {summary['excluded']} excluded; {summary['failed']} failed. "
                            f"{summary['above_target_designs']} designs strictly above {100*cfg['absorption_target']:g}%. "
                            f"{summary['matching_designs']} designs match the best within the entered tolerance. "
                            f"{summary['spectral_points']:,} spectral points in {summary['elapsed_seconds']:.1f} s.")
                    if not summary['above_target_designs']:
                        text += '\n\n**No evaluated design meets the absorption target.**'
                    if 'local_grid_complete' in summary:
                        text += f"\n\nLocal grid complete: {summary['local_grid_complete']}. Finalist checks complete: {summary['finalist_checks_complete']}. Finalists with two-resolution agreement: {summary['finalists_agree']}. Resumed observations: {summary['resumed_observations']}."
                        text += '\n\nPredicted absorption/std and paired-peak feasibility in the tables describe surrogate uncertainty; they are not measured absorption or fabrication yield.'
                        text += f"\n\nCurrent best absorption design checked at higher resolution: {summary['best_design_verified']}; current best-Q design checked: {summary['best_Q_design_verified']}."
                    if summary['reason']:
                        text += '\n\n'+html.escape(summary['reason'])
                    text += '\n\n'+summary['scope']+' Tables show at most 5,000 rows each; downloads contain every result and full model/material settings.'
                    downloads = [event['archive']]+[str(directory/name) for name in ('design_results.csv', 'matching_best.csv', 'above_target_by_Q.csv', 'all_peaks.csv')]
                    if (directory/'optimization_history.json').is_file():
                        downloads.extend(str(directory/name) for name in ('optimization_history.json', 'optimization_history.csv'))
                    yield fig, df.head(5000), ties.head(5000), feasible.head(5000), downloads, text, dict(directory=str(directory), project=project)
        except Exception as exc:
            yield None, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None, '**Error:** '+html.escape(str(exc)), None
        finally:
            if iterator is not None:
                iterator.close()

    def save_bounds(bounds_df, *options):
        directory = runs/('search_settings_'+uuid.uuid4().hex)
        directory.mkdir(parents=True)
        path = directory/'search_bounds.json'
        path.write_text(json.dumps(dict(bounds=records(bounds_df, BOUND_COLS), options=dict(zip(ALL_KEYS, options))), indent=2, allow_nan=False), encoding='utf-8')
        return str(path)

    def load_bounds(path):
        if not path:
            raise gr.Error('Choose a search-bounds JSON file')
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        defaults = dict(zip(ALL_KEYS, ALL_DEFAULTS))
        if 'search_mode' not in data.get('options', {}):
            defaults['search_mode'] = 'Exhaustive grid'
        defaults.update(data.get('options', {}))
        return pd.DataFrame(data['bounds'], columns=BOUND_COLS), *[defaults[k] for k in ALL_KEYS]

    def apply_design(state, design_id):
        if not state:
            raise gr.Error('Run a search first')
        if design_id is None or float(design_id) < 1 or not float(design_id).is_integer():
            raise gr.Error('Enter a positive integer design ID from the results')
        model = None
        with (Path(state['directory'])/'design_models.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                data = json.loads(line)
                if data['design_id'] == int(design_id):
                    model = data['model']
                    break
        if model is None:
            raise gr.Error('Design ID not found in this search')
        project = state['project']
        lay = [[l['name'], l['thickness'], l['material']] for l in model['layers']]
        pat = [[p['shape'], p['layer'], p['material'], p['cx'], p['cy'], p['sx'], p['sy'], p['angle']] for p in model['patterns']]
        updated = dict(project['settings'], ax_um=model['ax'], ay_um=model['ay'], NumG=model['basis'])
        return (pd.DataFrame(project['materials'], columns=mat_cols), pd.DataFrame(lay, columns=layer_cols),
                pd.DataFrame(pat, columns=pat_cols), *[updated[k] for k in set_keys])

    with gr.Tab('Explore designs'):
        gr.Markdown('### Compare designs across your wavelength range\nFind absorption peaks, compare all matching designs, and rank qualifying peaks by Q. This search uses the wavelength range and solver settings chosen in **Simulation**.')
        with gr.Row():
            search_mode = gr.Dropdown(MODES, value='Hybrid verified', label='Search method', allow_custom_value=False,
                                     info='ML learns where to search. Hybrid adds local exploration and verification. Grid evaluates every combination.')
            budget = gr.Number(500, precision=0, minimum=1, maximum=10000, label='Maximum designs to evaluate',info='Includes learning and local exploration; final verification adds reruns.')
        gr.Markdown('#### 1. Choose what the optimizer can change')
        bounds = build_bounds_editor(materials, layers, patterns, label='Saved design ranges')
        populate = gr.Button('Create ranges from the entire current structure')
        gr.Markdown('Creating ranges from the structure fixes each value initially. Load a range into the editor to choose wider limits. An empty range list analyzes the current design only.')
        with gr.Accordion('Absorption target and fabrication limits', open=False):
            with gr.Row():
                target = gr.Number(.99, minimum=.99, maximum=.999999999, label='Required absorption (fraction)',info='0.99 = 99%. Accepted peaks must be strictly above this value.')
                ratio = gr.Number(.6, minimum=.000001, maximum=.6, label='Maximum circle radius / lattice spacing',info='The ratio must be strictly below this limit; spacing is the smaller X/Y value.')
            with gr.Row():
                bridge = gr.Number(0, minimum=0, label='Minimum gap between circular regions (µm)')
                separate = gr.Checkbox(True, label='Keep circular holes and pillars separate')
            gr.Markdown('Circle separation includes periodic neighbors and other circles in the same layer. Set suitable size and position ranges for other shapes.')
        with gr.Accordion('Peak detection and wavelength sampling', open=False):
            with gr.Row():
                tie = gr.Number(.0001, minimum=0, maximum=1, label='Tolerance for matching the best absorption (fraction)',info='0.0001 = 0.01 percentage points.')
                prominence = gr.Number(.00001, minimum=0, maximum=1, label='Minimum peak prominence (fraction)',info='Lower values allow weaker peaks to be found before optimization.')
            with gr.Row():
                rounds = gr.Number(3, precision=0, minimum=0, maximum=6, label='Rounds of finer sampling around peaks')
                points = gr.Number(200000, precision=0, minimum=3, maximum=2000000, label='Maximum wavelength evaluations for the whole run')
            gr.Markdown('Q is estimated from the resolved spectral linewidth relative to the local baseline. Narrow peaks may need a smaller initial wavelength step in Simulation.')
        with gr.Accordion('Learning and verification settings', open=False) as ml_section:
            with gr.Row():
                initial = gr.Number(24, precision=0, minimum=2, label='Initial designs before guided learning')
                trials = gr.Number(60, precision=0, minimum=2, label='Total learning trials',info='Includes the initial designs and any resumed trials.')
                finalists = gr.Number(2, precision=0, minimum=1, maximum=10, label='Best designs to explore locally and verify')
            resume = gr.File(label='Continue from a saved optimization history (optional JSON)', type='filepath', file_types=['.json'])
            gr.Markdown('The saved history must match the structure, materials, wavelength range, and search ranges. Increase the trial and design budgets to continue a previous search.')
            with gr.Accordion('Detailed learning and convergence controls', open=False):
                with gr.Row():
                    pool = gr.Number(1024, precision=0, minimum=32, maximum=10000, label='Candidate designs considered per proposal')
                    seed = gr.Number(42, precision=0, minimum=0, label='Random seed')
                    patience = gr.Number(0, precision=0, minimum=0, label='Stop after trials without improvement',info='0 disables early stopping.')
                with gr.Row():
                    basis_factor = gr.Number(1.5, minimum=1.01, maximum=4, label='Verification: Fourier-basis multiplier')
                    step_divisor = gr.Number(2, precision=0, minimum=2, maximum=10, label='Verification: wavelength-step divisor')
                with gr.Row():
                    a_agreement = gr.Number(.001, minimum=0, maximum=1, label='Allowed absorption change between resolutions (fraction)')
                    q_agreement = gr.Number(.05, minimum=0, maximum=1, label='Allowed relative Q change between resolutions',info='0.05 = 5%.')
        search_mode.change(lambda mode: gr.Accordion(visible=mode != 'Exhaustive grid'), search_mode, ml_section, queue=False, api_visibility='private')
        gr.Markdown('#### 2. Run the search')
        with gr.Row():
            start = gr.Button('Start design search', variant='primary')
            stop = gr.Button('Stop search', variant='stop')
        status = gr.Markdown('Ready. Add design ranges, or run with an empty list to analyze the current structure.')
        plot = gr.Plot(label='Best absorption spectrum found')
        gr.Markdown('#### 3. Compare and use a design')
        state = gr.State(None)
        with gr.Row():
            selected_design = gr.Dropdown([], value=None, label='Design to use in Structure',allow_custom_value=False,scale=3)
            apply = gr.Button('Use selected design',variant='primary',scale=1)
        with gr.Tabs():
            with gr.Tab('Highest Q above target'):
                feasible = gr.Dataframe(label='Qualifying peaks ranked by Q', interactive=False)
            with gr.Tab('Best absorption matches'):
                matches = gr.Dataframe(label='Designs matching the highest absorption within your tolerance', interactive=False)
            with gr.Tab('All designs'):
                results = gr.Dataframe(label='Evaluated designs ranked by absorption', interactive=False)
        downloads = gr.File(file_count='multiple', label='Download all results, spectra, and design conditions')
        with gr.Accordion('Use a design by its numeric ID', open=False):
            selected_id = gr.Number(1, precision=0, minimum=1, label='Design ID',info='Also allows loading designs beyond the first 5,000 shown in the tables.')
        with gr.Accordion('Save or load search setup', open=False):
            with gr.Row():
                save = gr.Button('Save search setup')
                saved = gr.File(label='Download search setup JSON')
            with gr.Row():
                uploaded = gr.File(label='Saved search setup JSON', type='filepath',file_types=['.json'])
                load = gr.Button('Load search setup')
        gr.Markdown('Results report the best designs found in the evaluated search. A finite search cannot guarantee a continuous global maximum. Complete downloads include results beyond the table display limit.')

        def design_choices(value):
            frame = value if isinstance(value,pd.DataFrame) else pd.DataFrame(value)
            choices=[]
            if 'design_id' in frame:
                for row in frame.to_dict('records'):
                    if row.get('status') != 'evaluated':
                        continue
                    identifier=str(int(row['design_id']))
                    absorption=row.get('absorption')
                    text=f'Design {identifier}'
                    if pd.notna(absorption):
                        text+=f" · absorption {100*float(absorption):.5g}%"
                    wavelength=row.get('wavelength_nm')
                    if pd.notna(wavelength):
                        text+=f" · {float(wavelength):.6g} nm"
                    choices.append((text,identifier))
            return gr.Dropdown(choices=choices,value=choices[0][1] if choices else None)

        results.change(design_choices,results,selected_design,queue=False,api_visibility='private')
        selected_design.change(lambda value: int(value) if value else gr.skip(),selected_design,selected_id,queue=False,api_visibility='private')
        options = [ratio, bridge, separate, target, tie, prominence, rounds, budget, points,
                   search_mode, initial, trials, pool, seed, finalists, basis_factor, step_divisor, a_agreement, q_agreement, patience]
        populate.click(current_bounds, [layers, patterns, settings[0], settings[1]], bounds,api_visibility='private')
        start.click(run_search, [materials, layers, patterns, files, bounds, resume, *settings, *perf_inputs, *options],
                    [plot, results, matches, feasible, downloads, status, state], concurrency_limit=1, concurrency_id='s4-native', api_name='search_peaks')
        stop.click(cancel_run, None, status, queue=False, api_name='cancel_peak_search')
        save.click(save_bounds, [bounds, *options], saved, api_name='save_search_bounds')
        load.click(load_bounds, uploaded, [bounds, *options], api_name='load_search_bounds')
        apply.click(apply_design, [state, selected_id], [materials, layers, patterns, *settings], api_name='apply_search_design')
    return dict(bounds=bounds, options=options, resume=resume, state=state)
