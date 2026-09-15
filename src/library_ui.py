"""Gradio controls for permanent material presets and portable saved results."""
from contextlib import nullcontext
from datetime import datetime
import html
import json
from pathlib import Path
from gradio_compat import gr
import matplotlib.pyplot as plt
import pandas as pd

from data_library import read_json, write_json
from model import MAT_COLS
from peak_optimizer import BOUND_COLS
from peak_search_ui import ALL_KEYS, ALL_DEFAULTS
from field_tracking_ui import natural_key


def keep_choice(choices, selected=None):
    values = [choice[1] if isinstance(choice, (tuple, list)) else choice for choice in choices]
    return selected if selected in values else (values[0] if values else None)


def material_row_choices(df, records):
    if isinstance(df, dict) and 'data' in df:
        df = pd.DataFrame(df['data'], columns=df.get('headers', MAT_COLS))
    rows = records(df, MAT_COLS)
    labels = {'constant_nk': 'constant n, k', 'constant_eps': 'constant permittivity', 'table_nk': 'wavelength-dependent n, k'}
    return [(f"{row.get('Name') or 'Unnamed material'} · {labels.get(row.get('Model'), row.get('Model', ''))}", index)
            for index, row in enumerate(rows, 1) if row.get('Name')]


def saved_entry_choices(entries):
    choices = []
    for row in entries:
        created = row.get('created', '')
        try:
            created = datetime.fromisoformat(created.replace('Z', '+00:00')).astimezone().strftime('%b %d, %Y · %H:%M')
        except (TypeError, ValueError):
            pass
        choices.append((' · '.join(str(part) for part in (row.get('title', row['id']), row.get('kind'), created, row.get('status')) if part), row['id']))
    return choices


def csv_choices(filenames):
    purposes = {'results.csv': 'Spectrum · reflection, transmission & absorption',
                'best_spectrum.csv': 'Best design spectrum', 'spectrum.csv': 'Design spectrum',
                'partial_spectrum.csv': 'Partially completed spectrum',
                'design_results.csv': 'Optimization results · all designs',
                'target_results.csv': 'Target search · ranked designs',
                'electric_fields.csv': 'Electric & magnetic field samples',
                'field_training.csv': 'Field measurements used by machine learning',
                'field_comparison_metrics.csv': 'Field comparison measurements',
                'design_conditions.csv': 'Complete design conditions'}
    return [(purposes.get(Path(name).name, Path(name).stem.replace('_', ' ').capitalize())
             + (' · ' + str(Path(name).parent).replace('\\', '/') if Path(name).parent != Path('.') else ''), name)
            for name in sorted(filenames, key=natural_key)]


def saved_design_choices(directory):
    """Offer only actual saved model IDs; never infer IDs from table row numbers."""
    directory = Path(directory)
    result = []
    project = any((directory / name).exists() for name in ('project.json', 's4_project.json'))
    if (directory / 'job.json').exists():
        try:
            job = read_json(directory / 'job.json')
            project = project or 'model' in job or bool((job.get('search') or {}).get('project'))
        except (OSError, ValueError, TypeError):
            pass
    if project:
        result.append(('Original setup · resume from saved settings', 0))
    models = directory / 'design_models.jsonl'
    if not models.exists():
        return result
    indexed = {}
    with models.open(encoding='utf-8') as stream:
        for line in stream:
            try:
                item = json.loads(line)
                identifier = item['design_id']
                if isinstance(identifier, bool) or not isinstance(identifier, (int, float)) or int(identifier) != identifier or identifier <= 0:
                    continue
                model = item['model']
                layers = model['layers'][1:-1]
                materials = ' → '.join(str(layer['material']) for layer in layers[:4])
                if len(layers) > 4:
                    materials += ' …'
                label = f'Design {int(identifier)} · {len(layers)} finite layers'
                if materials:
                    label += ' · ' + materials
                indexed[int(identifier)] = label
            except (ValueError, KeyError, TypeError):
                continue
    return result + [(indexed[key], key) for key in sorted(indexed)]


def preset_choices(library, builtins):
    return [*builtins, *library.presets()]


def build_material_editor(library, preset, materials, uploads, builtins, records):
    def refresh():
        return gr.update(choices=preset_choices(library, builtins))

    def save(df, row_number, label, notes, files):
        rows = records(df, MAT_COLS)
        if row_number is None or not float(row_number).is_integer() or not 1 <= row_number <= len(rows):
            raise gr.Error('Enter a valid material row number (first row = 1)')
        try:
            key = library.save_preset(rows[int(row_number)-1], label, notes, files)
            return gr.update(choices=preset_choices(library, builtins), value=key), 'Saved permanently. The material is now available in the preset dropdown for future projects. Earlier saved versions remain available.'
        except Exception as exc:
            raise gr.Error(str(exc)) from exc

    def update_materials(df, selected):
        choices = material_row_choices(df, records)
        return gr.update(choices=choices, value=keep_choice(choices, selected))

    initial = material_row_choices(materials.value, records)
    with gr.Accordion('Save a material for future projects', open=False):
        gr.Markdown('Choose a material from this project and save it as a reusable preset. Wavelength-dependent tables are copied into permanent storage. Each save keeps a separate version.')
        with gr.Row():
            material = gr.Dropdown(initial, value=keep_choice(initial), label='Material to save', filterable=True)
            label = gr.Textbox(label='Preset name', placeholder='Leave empty to use the material name')
        notes = gr.Textbox(label='Source and measurement conditions', placeholder='Source URL, temperature, composition, preparation method…', lines=2)
        with gr.Row():
            save_button = gr.Button('Save to material library', variant='primary')
            refresh_button = gr.Button('Refresh saved presets')
        status = gr.Markdown()
        materials.change(update_materials, [materials, material], material, api_visibility='private')
        save_button.click(save, [materials, material, label, notes, uploads], [preset, status], api_visibility='private')
        refresh_button.click(refresh, None, preset, api_name='refresh_material_presets')
        row_number = gr.Number(1, precision=0, visible=False)
        legacy_save = gr.Button(visible=False)
        legacy_save.click(save, [materials, row_number, label, notes, uploads], [preset, status], api_name='save_material_preset')


def build_library_ui(library, source_root, compute_lock, load_project, structure_outputs,
                     nkfiles, settings_outputs, perf_outputs, search, preset, builtins, wrap_tab=True):

    def refresh(query, kind='All types', status_filter='All statuses', selected=None):
        entries = library.entries(query or '')
        if kind != 'All types':
            entries = [entry for entry in entries if entry.get('kind') == kind]
        if status_filter != 'All statuses':
            entries = [entry for entry in entries if entry.get('status') == status_filter]
        choices = saved_entry_choices(entries)
        return (gr.update(choices=choices, value=keep_choice(choices, selected)),
                pd.DataFrame(entries, columns=['id', 'title', 'kind', 'status', 'created', 'notes']))

    def refresh_ui(query, kind, status_filter, selected):
        entries = library.entries()
        kinds = ['All types', *sorted({row.get('kind', '') for row in entries if row.get('kind')})]
        statuses = ['All statuses', *sorted({row.get('status', '') for row in entries if row.get('status')})]
        kind = keep_choice(kinds, kind)
        status_filter = keep_choice(statuses, status_filter)
        return (*refresh(query, kind, status_filter, selected), gr.update(choices=kinds, value=kind),
                gr.update(choices=statuses, value=status_filter))

    def inspect(identifier):
        if not identifier:
            return {}, gr.update(choices=[], value=None), '', ''
        directory = library.directory(identifier)
        record = read_json(directory / 'library_record.json')
        files = [p.relative_to(directory).as_posix() for p in sorted(directory.rglob('*'), key=natural_key) if p.is_file() and not p.is_symlink()]
        csvs = [name for name in files if name.endswith('.csv')]
        preferred = next((name for name in ('target_results.csv', 'design_results.csv', 'results.csv', 'best_spectrum.csv') if name in csvs), csvs[0] if csvs else None)
        details = dict(record=record, files=files)
        for name in ('search_summary.json', 'diagnostics.json'):
            if (directory / name).exists():
                details[name] = read_json(directory / name)
        return details, gr.update(choices=csv_choices(csvs), value=preferred), record['title'], record.get('notes', '')

    def inspect_ui(identifier):
        try:
            values = inspect(identifier)
            choices = saved_design_choices(library.directory(identifier)) if identifier else []
            message = ('Choose a saved setup below to reopen it in the editor. Reopening does not start a simulation.'
                       if choices else 'This entry contains results without a restorable structure. Preview or download its files below.')
            return (*values, gr.update(choices=choices, value=keep_choice(choices), interactive=bool(choices)),
                    gr.update(interactive=bool(choices)), message)
        except Exception as exc:
            return ({}, gr.update(choices=[], value=None), '', '', gr.update(choices=[], value=None, interactive=False),
                    gr.update(interactive=False), '**Unable to open entry:** ' + html.escape(str(exc)))

    def preview(identifier, filename):
        if not filename:
            return pd.DataFrame(), None, None
        directory = library.directory(identifier)
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory) or path.suffix != '.csv' or not path.is_file():
            raise gr.Error('Choose a CSV from this saved entry')
        df = pd.read_csv(path, nrows=5000)
        fig = None
        x = 'wavelength_nm' if 'wavelength_nm' in df else None
        if 'angle_deg' in df and df.angle_deg.nunique() > 1 and (not x or df[x].nunique() <= 1):
            x = 'angle_deg'
        ys = [col for col in ('R', 'T', 'A') if col in df]
        if x and ys and not df.empty:
            fig, axis = plt.subplots(figsize=(8, 5))
            for name in ys:
                data = df[[x, name]].sort_values(x)
                axis.plot(data[x], data[name], label=name)
            axis.set(xlabel='Wavelength (nm)' if x == 'wavelength_nm' else 'Angle (deg)', ylabel='Fraction', title='Saved data preview (up to 5,000 rows)')
            axis.legend()
            axis.grid(alpha=.25)
            fig.tight_layout()
            plt.close(fig)
        return df, fig, str(path)

    def restore(identifier, design_id):
        if design_id is None or not float(design_id).is_integer() or design_id < 0:
            raise gr.Error('Design ID must be an integer; 0 restores the original setup')
        try:
            project, cfg = library.project_for(identifier, int(design_id))
            directory = library.directory(identifier)
            restored = directory / 'restored_project.json'
            write_json(restored, project)
            values = load_project(str(restored))
            option_values = dict(zip(ALL_KEYS, ALL_DEFAULTS))
            if cfg:
                option_values['search_mode'] = 'Exhaustive grid'
                option_values.update({k: v for k, v in cfg.items() if k in ALL_KEYS})
            history = directory / 'optimization_history.json'
            if history.exists() and not design_id:
                history_value = str(history)
            else:
                history_value = None
            message = 'Restored structure, materials, simulation and performance settings.'
            if cfg:
                message += ' Search bounds and options restored. Saved search designs can now be applied in Peak Optimization.'
            if history_value:
                message += ' ML history loaded; clear it for a new search or after changing the setup.'
            return (*values, library.files_for(project) or None,
                    pd.DataFrame(cfg.get('input_bounds', []), columns=BOUND_COLS),
                    *[option_values[k] for k in ALL_KEYS], history_value,
                    dict(directory=str(directory), project=project) if cfg else None, message)
        except Exception as exc:
            raise gr.Error(str(exc)) from exc

    def rename(identifier, title, notes):
        library.record(library.directory(identifier), title=title.strip() or identifier, notes=notes or '')
        return 'Title and notes saved. Refresh the list to update its labels.'

    def export(identifier, include_source):
        if not compute_lock.acquire(blocking=False):
            raise gr.Error('Wait for the current simulation/search to stop before exporting a consistent snapshot.')
        try:
            return library.export(identifier or None, source_root if include_source else None)
        finally:
            compute_lock.release()

    def import_data(filename):
        if not filename:
            raise gr.Error('Choose an exported S4 library ZIP')
        if not compute_lock.acquire(blocking=False):
            raise gr.Error('Wait for the current simulation/search to stop before importing.')
        try:
            result = library.import_bundle(filename)
            return (f"Imported {result['runs']} saved entries, {result['presets']} presets and {result['assets']} material tables. Existing entries were kept.",
                    gr.update(choices=preset_choices(library, builtins)), *refresh(''))
        except Exception as exc:
            raise gr.Error(str(exc)) from exc
        finally:
            compute_lock.release()

    def export_selected(identifier):
        if not identifier:
            raise gr.Error('Choose a saved run to download')
        return export(identifier, False)

    entries = library.entries()
    with gr.Tab('Saved work') if wrap_tab else nullcontext():
        gr.Markdown('### Reopen, compare and share your work\nSimulations, optimization trials, field maps and material tables stay available after you close the app. Refresh the list after new calculations finish.')
        with gr.Group(elem_classes=['card']):
            with gr.Row():
                query = gr.Textbox(label='Find saved work', placeholder='Search run titles, notes, status or IDs…', scale=3)
                refresh_button = gr.Button('Refresh library', scale=1)
            with gr.Row():
                kind = gr.Dropdown(['All types', *sorted({row.get('kind', '') for row in entries if row.get('kind')})], value='All types', label='Work type')
                status_filter = gr.Dropdown(['All statuses', *sorted({row.get('status', '') for row in entries if row.get('status')})], value='All statuses', label='Run status')
            selection = gr.Dropdown(saved_entry_choices(entries), label='Saved run or project', value=None, filterable=True,
                                    info='Select a run to see its setup, results and download options.')
        status = gr.Markdown('Choose a saved run above to get started.' if entries else 'No saved work yet. Your first simulation, optimization or field calculation will appear here.')
        with gr.Row():
            design = gr.Dropdown([], value=None, interactive=False, label='Setup to reopen', scale=3,
                                 info='Choose the original setup or a saved design by name.')
            restore_button = gr.Button('Reopen in editor', variant='primary', interactive=False, scale=1)
        with gr.Accordion('Rename this run or add notes', open=False):
            title = gr.Textbox(label='Run title', placeholder='Give this run a recognizable name')
            notes = gr.Textbox(label='Notes', placeholder='What changed, material sources, observations…', lines=3)
            save_notes = gr.Button('Save title and notes')
        gr.Markdown('#### Explore results')
        with gr.Row():
            csv = gr.Dropdown([], label='Result to view', scale=3)
            view = gr.Button('Load preview', scale=1)
        plot = gr.Plot(label='Saved spectrum')
        with gr.Accordion('View numeric results', open=False):
            table = gr.Dataframe(interactive=False, label='Result preview · first 5,000 rows', max_height=420)
        with gr.Row():
            download = gr.File(label='Download complete result CSV', interactive=False)
            export_one = gr.Button('Download this saved run as ZIP')
        one_bundle = gr.File(label='Saved run ZIP · includes its data and materials', interactive=False)
        with gr.Accordion('Back up, share or import a library', open=False):
            gr.Markdown('A whole-library ZIP includes every saved run, material preset and optical-constant table. Include the application to share an editable code set with its data. Import merges data and presets while keeping existing entries.')
            include_source = gr.Checkbox(True, label='Include application source and bundled runtime')
            export_all = gr.Button('Create whole-library backup')
            bundle = gr.File(label='Download library ZIP', interactive=False)
            gr.Markdown('Keep a backup outside this storage folder. To run a shared copy, extract the ZIP and use the Windows or Linux launcher for that system.')
            uploaded = gr.File(type='filepath', file_types=['.zip'], label='Choose a library ZIP to import')
            import_button = gr.Button('Import saved work and materials')
        with gr.Accordion('Library details and diagnostics', open=False):
            gr.Markdown('Storage folder: `' + str(library.root) + '`\n\nCompleted worker batches are retained after a stopped run. Unfinished batches cannot be recovered. Libraries are local and are not automatically synchronized between computers.')
            catalog = gr.Dataframe(pd.DataFrame(entries, columns=['id', 'title', 'kind', 'status', 'created', 'notes']), interactive=False, label='Complete saved-work catalog', max_height=320)
            details = gr.JSON(label='Run metadata, diagnostics and file inventory', open=False)
        restore_outputs = [*structure_outputs, *settings_outputs, *perf_outputs, nkfiles, search['bounds'], *search['options'], search['resume'], search['state'], status]
        inspect_outputs = [details, csv, title, notes, design, restore_button, status]
        for event in (refresh_button.click, query.submit, kind.input, status_filter.input):
            event(refresh_ui, [query, kind, status_filter, selection], [selection, catalog, kind, status_filter], api_visibility='private').then(
                inspect_ui, selection, inspect_outputs, api_visibility='private').then(
                preview, [selection, csv], [table, plot, download], api_visibility='private')
        selection.input(inspect_ui, selection, inspect_outputs, api_visibility='private').then(
            preview, [selection, csv], [table, plot, download], api_visibility='private')
        csv.input(preview, [selection, csv], [table, plot, download], api_visibility='private')
        view.click(preview, [selection, csv], [table, plot, download], api_name='preview_saved_csv')
        restore_button.click(restore, [selection, design], restore_outputs, api_visibility='private')
        save_notes.click(rename, [selection, title, notes], status, api_name='name_saved_data')
        export_all.click(lambda code: export(None, code), include_source, bundle, api_name='export_data_library')
        export_one.click(export_selected, selection, one_bundle, api_name='export_saved_entry')
        import_button.click(import_data, uploaded, [status, preset, selection, catalog], api_name='import_data_library').then(
            inspect_ui, selection, inspect_outputs, api_visibility='private').then(
            preview, [selection, csv], [table, plot, download], api_visibility='private')
        # Retain numeric IDs and original response shapes for existing automation clients.
        legacy_design = gr.Number(0, precision=0, visible=False)
        legacy_restore = gr.Button(visible=False)
        legacy_list = gr.Button(visible=False)
        legacy_inspect = gr.Button(visible=False)
        legacy_restore.click(restore, [selection, legacy_design], restore_outputs, api_name='restore_saved_setup')
        legacy_list.click(lambda text: refresh(text), query, [selection, catalog], api_name='list_saved_data')
        legacy_inspect.click(inspect, selection, [details, csv, title, notes], api_name='inspect_saved_data')
