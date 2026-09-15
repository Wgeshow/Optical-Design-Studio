"""Automatic CSV-to-material import and manual dispersive material entry."""
import html
from pathlib import Path
import gradio as gr
import pandas as pd

from model import MAT_COLS, number
from nk_import import parse_nk, csv_bytes


def store_table(library, name, rows, notes, original=None):
    asset = library.asset(csv_bytes(rows))
    row = dict(zip(MAT_COLS, [name.strip(), 'table_nk', None, None, asset.name, 'nm']))
    if original is not None:
        original_asset = library.asset(Path(original).read_bytes())
        notes += f'\nOriginal CSV: {Path(original).name}; preserved as {original_asset.name}'
    return store_row(library, row, notes)


def store_row(library, row, notes):
    if not row['Name']:
        raise ValueError('Enter a material name')
    # Upload events include earlier files in a multi-upload; identical data is reused.
    with library.lock:
        for key, record in library.presets().items():
            if record['project']['materials'][0] == row and record['notes'] == notes:
                return row, key
        key = library.save_preset(row, row['Name'], notes)
    return row, key


def merge_material(df, row):
    frame = pd.DataFrame(df, columns=MAT_COLS).astype(object)
    data = frame.where(pd.notna(frame), None).to_dict('records')
    found = False
    for index, previous in enumerate(data):
        if str(previous.get('Name')) == row['Name']:
            data[index] = dict(row)
            found = True
    if not found:
        data.append(dict(row))
    return pd.DataFrame(data, columns=MAT_COLS)


def import_csvs(library, df, files, unit, missing_k, source, name=''):
    if not files:
        raise ValueError('Upload at least one optical-constant CSV/TXT file')
    if name.strip() and len(files) != 1:
        raise ValueError('A custom name applies to one file. Clear it to import multiple files using their filenames.')
    parsed = []
    names = set()
    # Validate the entire selection before changing the material table or presets.
    for file in files:
        path = Path(file)
        material_name = name.strip() or path.stem.strip()
        if material_name in names:
            raise ValueError('Two files have the same material name; import them separately with different names')
        names.add(material_name)
        rows = parse_nk(path.read_text(encoding='utf-8-sig'), unit, 0. if missing_k else None)
        parsed.append((path, material_name, rows))
    result, reports, key = pd.DataFrame(df, columns=MAT_COLS).copy(), [], None
    for path, material_name, rows in parsed:
        notes = f'Source: {source.strip()}\nUploaded wavelengths: {unit}; wavelength-dependent n,k.'
        if missing_k:
            notes += '\nUser permits missing k = 0 (lossless assumption where k is absent).'
        row, key = store_table(library, material_name, rows, notes, original=path)
        result = merge_material(result, row)
        reports.append(f'{material_name}: {len(rows):,} samples, {rows[0][0]:g}–{rows[-1][0]:g} nm')
    return result, key, 'Added to the material table and saved presets. ' + '; '.join(reports)


def save_manual(library, df, name, mode, unit, table, n, k, source):
    name = (name or '').strip()
    if not name:
        raise ValueError('Enter a material name')
    notes = f'Source: {source.strip()}\nManually entered material data.'
    if mode == 'Wavelength-dependent n,k':
        frame = pd.DataFrame(table, columns=['Wavelength', 'n', 'k']).dropna(how='all')
        # Do not substitute example material values or fill missing data silently.
        text = 'wavelength,n,k\n' + '\n'.join(','.join(str(v) for v in row) for row in frame.itertuples(index=False, name=None))
        rows = parse_nk(text, unit)
        row, key = store_table(library, name, rows, notes + f'\nInput wavelength unit: {unit}')
        message = f'{name}: saved {len(rows):,} wavelength samples ({rows[0][0]:g}–{rows[-1][0]:g} nm).'
    elif mode == 'Constant n,k (explicit approximation)':
        row = dict(zip(MAT_COLS, [name, 'constant_nk', number(n, 'n'), number(k, 'k'), '', 'nm']))
        row, key = store_row(library, row, notes + '\nUser explicitly selected wavelength-independent n,k.')
        message = f'{name}: saved explicitly constant n,k.'
    else:
        raise ValueError('Choose wavelength-dependent data or an explicit constant approximation')
    return merge_material(df, row), key, message + ' Added to the material table and preset dropdown.'


def build_import_controls(library, materials, preset, uploads, builtins, unit, missing_k, source, name,include_upload=True,include_manual=True):
    def output(result):
        table, key, message = result
        return table, gr.update(choices=[*builtins, *library.presets()], value=key), html.escape(message)

    def upload(files, df, units, zero_k, reference, material_name):
        if not files:
            return gr.skip(), gr.skip(), 'Upload a CSV to add a wavelength-dependent material.'
        try:
            return output(import_csvs(library, df, files, units, zero_k, reference, material_name or ''))
        except Exception as exc:
            # Keep the existing table visible when a file needs corrected input.
            return gr.skip(), gr.skip(), '**Import needs attention:** ' + html.escape(str(exc))

    def manual(df, material_name, behavior, units, rows, n_value, k_value, reference):
        try:
            return output(save_manual(library, df, material_name, behavior, units, rows, n_value, k_value, reference))
        except Exception as exc:
            return gr.skip(), gr.skip(), '**Material needs attention:** ' + html.escape(str(exc))

    if include_upload:
        import_status = gr.Markdown('Accepts wavelength,n,k columns and refractiveindex.info n/k sections. Select the file units explicitly. Imported materials appear in the structure dropdowns automatically.')
        retry = gr.Button('Import selected files again')
        inputs = [uploads, materials, unit, missing_k, source, name]
        outputs = [materials, preset, import_status]
        uploads.upload(upload, inputs, outputs, api_name='auto_import_material_csv', concurrency_id='material-import')
        retry.click(upload, inputs, outputs, api_name='import_material_csv', concurrency_id='material-import')
    if not include_manual: return
    with gr.Column(elem_classes='studio-card'):
        gr.Markdown('### Add a material from values\nEnter at least two wavelengths with n and k, or explicitly choose a constant approximation. Every saved material is available in the layer and region dropdowns.')
        with gr.Row():
            manual_name = gr.Textbox(label='Material name')
            behavior = gr.Dropdown(['Wavelength-dependent n,k', 'Constant n,k (explicit approximation)'],
                                value='Wavelength-dependent n,k', label='Wavelength dependence')
            manual_unit = gr.Dropdown(['nm', 'um'], value='nm', label='Manual wavelength unit')
        values = gr.Dataframe(headers=['Wavelength', 'n', 'k'], datatype=['number']*3,
                              row_count=(3, 'dynamic'), column_count=(3, 'fixed'), interactive=True,
                              label='Measured / published values (at least two wavelengths)')
        with gr.Row(visible=False) as constants:
            n_value = gr.Number(value=None, label='Constant n (used only in constant mode)')
            k_value = gr.Number(value=None, label='Constant k (used only in constant mode)')
        reference = gr.Textbox(value='https://refractiveindex.info/', label='Dataset page / reference / conditions')
        save = gr.Button('Save material to project and library',variant='primary')
        manual_status = gr.Markdown()
        save.click(manual, [materials, manual_name, behavior, manual_unit, values, n_value, k_value, reference],
                   [materials, preset, manual_status], api_name='add_manual_material', concurrency_id='material-import')
        behavior.change(lambda mode:(gr.update(visible=mode=='Wavelength-dependent n,k'),
                                     gr.update(visible=mode=='Wavelength-dependent n,k'),
                                     gr.update(visible=mode!='Wavelength-dependent n,k')),
                        behavior,[values,manual_unit,constants],api_visibility='private')
