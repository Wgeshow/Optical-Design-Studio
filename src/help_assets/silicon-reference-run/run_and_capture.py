"""Reproducible production S4 run and native Qt captures for the Help example.

All calculation and preference writes stay under this helper's folder.
No synthetic spectra, fabricated fields, or image-generation tools are used.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = next((candidate for parent in (ROOT, *ROOT.parents)
               for candidate in (parent, parent / 's4_ui_redesign')
               if (candidate / 'qt_app.py').is_file()), None)
if SOURCE is None:
    raise RuntimeError('Place this helper inside or alongside the s4_ui_redesign application source.')
os.environ['S4_LIBRARY_ROOT'] = str(ROOT / 'isolated_library')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(SOURCE))

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import copy, hashlib, json, subprocess, time
    import numpy as np
    import pandas as pd
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication
    from data_library import DataLibrary, write_json
    from qt_core import ProjectStore, prepare_job
    from qt_common import theme_manager
    from qt_app import OpticalStudio

    capture_only = '--capture-only' in sys.argv
    reuse_saved = capture_only or '--reuse' in sys.argv

    ROOT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setFont(QFont('Segoe UI', 10))
    theme_manager().apply_look('glass_dark', persist=False)
    library = DataLibrary(ROOT / 'isolated_library')
    store = ProjectStore(library, restore=False)
    example = SOURCE / 'help_assets' / 'air-hole-example.json'
    store.load_project(example)
    # Keep the bundled geometry and explicit constant-index approximation.
    # This tutorial run uses 1 nm sampling and 81 requested Fourier terms.
    store.update_settings(dict(NumG=81, wl_start_nm=1515, wl_stop_nm=1555, wl_step_nm=1))
    store.update_performance(dict(mode='CPU only', workers=1, threads=1, chunk_size=8, timeout_seconds=3600))
    store.save_search('simulation', dict(measure_phase=False, electric_fields=dict(grid=25, depth_samples=3, contour_step=.1)))
    store.save_search('fields', dict(wavelength_nm=1550, layer='Silicon', grid=25, depth_samples=3))
    project = store.portable_project()
    project['example_notes'] = 'Actual production S4 RCWA tutorial calculation; 100 nm radius air hole in 220 nm Silicon on SiO2. Constant n=3.48 and n=1.45, k=0 are illustrative approximations near 1550 nm.'
    if not capture_only:
        write_json(ROOT / 'actual-silicon-project.json', project)
        write_json(ROOT / 'Si-SiO2-r100nm.json', project)
    print(('Refreshing captures from completed saved S4 results; no solver calculation.' if reuse_saved else 'Running production S4 spectrum and per-sample fields (41 wavelengths, requested NumG=81, 25x25 grid).'), flush=True)
    window = OpticalStudio(store)
    window.project_path = ROOT / 'Si-SiO2-r100nm.json'
    window.project_button.setText('Silicon / SiO2 · r 100 nm  ⌄')
    window.project_select.setText('Silicon / SiO2 · r 100 nm')
    window.resize(1536, 1024)
    window.show()
    events, errors = [], []
    store.progress.connect(lambda e: events.append(copy.deepcopy(e)))
    store.run_failed.connect(errors.append)
    sim = window.pages['Simulate']
    window._navigate_route(2, 0)
    if reuse_saved:
        saved_run = next(p.parent for p in library.runs.glob('*/diagnostics.json') if (p.parent/'fields'/'samples.json').is_file())
        store.last_result = dict(kind='complete',run_kind='simulation',directory=str(saved_run),output=str(saved_run/'results.csv'),info=json.loads((saved_run/'diagnostics.json').read_text()))
        sim._finished(store.last_result)
        events.append(copy.deepcopy(store.last_result))
    else:
        sim.run()
    started = time.monotonic()
    last_report = 0
    while store.busy:
        app.processEvents()
        time.sleep(.02)
        elapsed = time.monotonic() - started
        if elapsed - last_report >= 15:
            last_report = elapsed
            print(f'Actual run {elapsed:.0f}s: ' + str(events[-1].get('text', events[-1].get('kind', 'running')) if events else 'running'), flush=True)
        if elapsed > 3590:
            store.cancel()
    for _ in range(20): app.processEvents()
    if errors: raise RuntimeError('\n'.join(errors))
    actual_event = copy.deepcopy(store.last_result)
    actual_directory = Path(actual_event['directory'])
    raw_data_paths = [p for p in actual_directory.rglob('*') if p.is_file() and p.suffix in ('.csv','.json')]
    raw_data_paths += [p for basis in (49,121) for p in (ROOT/('convergence-basis-'+str(basis)+'-verified')).rglob('*') if p.is_file() and p.suffix in ('.csv','.json')]
    raw_data_paths += [ROOT/name for name in ('actual-silicon-project.json','Si-SiO2-r100nm.json','scientific-validation.json','backend-events.json') if (ROOT/name).is_file()]
    raw_data_hashes = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in raw_data_paths}
    frame = pd.read_csv(actual_directory / 'results.csv')
    assert len(frame) == 41
    assert np.isfinite(frame[['R','T','A']].to_numpy()).all()
    energy_error = float(np.abs(frame['R'] + frame['T'] - 1).max())
    assert energy_error < 1e-7, energy_error
    assert frame['R'].min() >= -1e-9 and frame['T'].min() >= -1e-9
    assert frame['R'].max() <= 1 + 1e-7 and frame['T'].max() <= 1 + 1e-7
    manifest = json.loads((actual_directory/'fields'/'samples.json').read_text())
    assert manifest['status'] == 'complete' and len(manifest['samples']) == len(frame)
    field_samples = []
    for saved in manifest['samples']:
        data = pd.read_csv(Path(saved['directory'])/'electric_fields.csv')
        numeric = data.select_dtypes(include='number')
        assert np.isfinite(numeric.to_numpy()).all()
        assert (data.E2 >= 0).all()
        reconstructed_E2 = sum(data[component+'_real']**2 + data[component+'_imag']**2 for component in ('Ex','Ey','Ez'))
        assert np.allclose(data.E2, reconstructed_E2, atol=1e-12, rtol=1e-10)
        assert set(data.plane) == {'volume_samples', 'xy', 'xz'}
        field_samples.append(dict(wavelength_nm=saved['wavelength_nm'], points=len(data), max_E_amplitude=float(np.sqrt(data.E2.max()))))
    field_sample = next(s for s in manifest['samples'] if s['wavelength_nm'] == 1550)
    field_directory = Path(field_sample['directory'])

    def capture(name, widget=None):
        for _ in range(30): app.processEvents()
        target = widget or window
        path = ROOT / (name + '.png')
        assert target.grab().save(str(path)), path
        print('Captured ' + path.name, flush=True)
        return path.name

    images = []
    sim.result_tabs.setCurrentIndex(0)
    sim.inspect_sample(int(frame.index[frame.wavelength_nm == 1550][0]))
    images.append(capture('actual-spectrum-native'))
    images.append(capture('actual-spectrum-plot', sim.plot))
    sim.plot.export_figure(ROOT/'actual-spectrum-export.png')
    # Load the genuine field sample through the production Fields renderer.
    fields = window.pages['Fields']
    fields.directory = actual_directory
    fields.field_directory = field_directory
    fields.wavelength.setValue(1550)
    fields.grid.setValue(25)
    fields.depth.setValue(3)
    fields.layer.setCurrentIndex(fields.layer.findData('Silicon'))
    fields.arrows.setChecked(False)
    fields.logarithmic.setChecked(False)
    fields.render_fields()
    window._navigate_route(2, 3)
    images.append(capture('actual-fields-native'))
    images.append(capture('actual-fields-plot', fields.plot))
    fields.plot.export_figure(ROOT/'actual-electric-field-maps.png')
    # The production replay viewer reads the saved complex volume samples.
    # Sample points preserve the original grid without added interpolation.
    snapshot_id = field_directory.relative_to(library.runs).as_posix()
    fields.volume.snapshot.setCurrentIndex(fields.volume.snapshot.findData(snapshot_id))
    fields.volume.load()
    assert fields.volume.data is not None, fields.volume.status.text()
    fields.volume.style.setCurrentText('Sample points')
    fields.volume.threshold.setValue(0)
    fields.volume.show_arrows.setChecked(True)
    fields.volume.phase.setValue(45)
    fields.tabs.setCurrentIndex(2)
    images.append(capture('actual-3d-fields-native'))
    images.append(capture('actual-3d-fields-plot', fields.volume.plot))
    fields.tabs.setCurrentIndex(0)
    window._navigate_route(0)
    structure = window.pages['Structure']
    structure.set_geometry_view('Cross-section')
    images.append(capture('actual-structure-native'))
    structure.set_geometry_view('Unit cell')
    images.append(capture('actual-unit-cell-native'))
    window._navigate_route(1)
    materials = window.pages['Materials']
    materials.selection.setCurrentIndex(materials.selection.findData('project:Silicon'))
    materials.filter_materials()
    images.append(capture('actual-materials-native'))
    # Exit without a save prompt: no workspace or normal preferences changed.
    window._saved_project = copy.deepcopy(store.project())

    convergence = []
    # Repeat only spectra at neighboring requested basis counts. Per-sample
    # fields are already complete above; convergence jobs deliberately omit
    # them because energy and R/T convergence need only power fluxes.
    for basis in (49, 121):
        run = ROOT / ('convergence-basis-' + str(basis) + '-verified')
        if capture_only:
            assert (run/'diagnostics.json').is_file() and (run/'results.csv').is_file(), 'Capture-only requires completed saved convergence data.'
        else:
            run.mkdir(exist_ok=True)
            trial = copy.deepcopy(project)
            trial['settings']['NumG'] = basis
            trial, spec = prepare_job('simulation', trial, {}, library)
            spec.pop('simulation_fields')
            write_json(run/'project.json', trial)
            write_json(run/'job.json', spec)
            if not ((run/'diagnostics.json').is_file() and (run/'results.csv').is_file()):
                with (run/'backend_stdout.jsonl').open('w', encoding='utf-8') as out, (run/'backend_stderr.txt').open('w', encoding='utf-8') as err:
                    done = subprocess.run([sys.executable, str(SOURCE/'backend.py'), '--job', str(run/'job.json')], stdout=out, stderr=err, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0), timeout=3600)
                assert done.returncode == 0, (run/'backend_stderr.txt').read_text()
        other = pd.read_csv(run/'results.csv')
        assert np.isfinite(other[['R','T','A']].to_numpy()).all()
        delta = float(np.abs(frame[['R','T']].to_numpy()-other[['R','T']].to_numpy()).max())
        convergence.append(dict(requested_NumG=basis, max_absolute_R_T_difference_from_81=delta, max_abs_R_plus_T_minus_1=float(np.abs(other['R']+other['T']-1).max()), points=len(other), directory=str(run)))
        print('Convergence basis ' + str(basis) + ': max absolute R/T change=' + str(delta), flush=True)
    assert convergence[-1]['max_absolute_R_T_difference_from_81'] < .002, convergence
    validation = dict(status='passed', samples=41, finite_RTA=True, all_field_samples_finite=True, E2_matches_saved_complex_field_components=True, physical_power_bounds=True, max_abs_R_plus_T_minus_1=energy_error, fields_per_wavelength=field_samples, basis_comparisons=convergence, spectrum_81_vs_121_tolerance=.002, notes=['R+T is the non-tautological energy check for this lossless model; A is calculated as 1-R-T.', 'Requested S4 basis truncations are solver basis settings; square lattice truncation can retain fewer terms.', 'This sampled, absolute R/T comparison does not establish a general convergence guarantee or measured-material prediction.'])
    if capture_only:
        assert json.loads((ROOT/'scientific-validation.json').read_text(encoding='utf-8')) == validation, 'Saved scientific validation no longer matches its raw data.'
    else:
        write_json(ROOT/'scientific-validation.json', validation)
        write_json(ROOT/'backend-events.json', events)
    provenance = dict(status='complete', source_project=str(example), source_project_sha256=hashlib.sha256(example.read_bytes()).hexdigest(), geometry=dict(incident='Air semi-infinite', slab_material='Silicon', slab_thickness_nm=220, substrate='SiO2 semi-infinite', hole_material='Air', hole_radius_nm=100, period_x_nm=540, period_y_nm=540), optical_model=dict(Air_n=1, Silicon_n=3.48, SiO2_n=1.45, k=0, approximation='Explicit constant, real indices for an illustrative tutorial near 1550 nm.'), solver='Bundled production S4 RCWA via ProjectStore -> BackendWorker -> backend.main', calculation=dict(wavelength_start_nm=1515,wavelength_stop_nm=1555,wavelength_step_nm=1,requested_NumG=81,polarization='p',theta_deg=0,phi_deg=0,performance=project['performance']), fields=dict(displayed_wavelength_nm=1550,layer='Silicon',grid_per_axis=25,depth_samples_per_finite_layer=3,plane_XY='Silicon midplane z=0.11 um',plane_XZ='y=0, finite Silicon thickness 0..0.22 um',amplitude_normalization='|E| / incident |E|',displayed_directory=str(field_directory),all_wavelengths_saved=True), actual_run_directory=str(actual_directory), native_UI=dict(width=1536,height=1024,look='glass_dark',platform=app.platformName(),method='Production Qt widgets rendered with QWidget.grab after actual calculation and result loading.'), images=images, scientific_validation=str(ROOT/'scientific-validation.json'), helper=str(Path(__file__).resolve()), helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    provenance['fields']['display_scale'] = 'linear normalized amplitude'
    provenance['fields']['volume_playback'] = dict(wavelength_nm=1550, saved_volume_samples=1875, visualization='Original sample points',colors='|E| squared (S4 units)',arrows='Real electric field at optical phase 45 degrees',phase_animation_running=False,added_interpolation=False)
    provenance['source_code_sha256'] = {name:hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in ('backend.py','field_solver.py','model.py','data_library.py','qt_core.py','qt_common.py','qt_materials.py','qt_compute.py','qt_field_volume.py','qt_native_field_volume.py','qt_native_plot.py','qt_native_figure.py','qt_device_builder.py','qt_help.py')}
    native_module = Path(actual_event['info']['workers'][0]['module'])
    provenance['native_S4_module'] = str(native_module)
    provenance['native_S4_module_sha256'] = hashlib.sha256(native_module.read_bytes()).hexdigest()
    provenance['python_executable'] = sys.executable
    provenance['native_UI'].update(outer_margin_px=8,footer_height_px=56,spectrum_display='0 to 100 percent; saved R/T/A remain fractions')
    provenance['native_UI']['live_plot_renderer'] = 'Native Qt 2D plot widgets and typed QPainter 3D saved-field replay; Matplotlib remains an offline publication export path.'
    if capture_only:
        assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in raw_data_hashes.items()), 'Raw scientific files changed during capture-only refresh.'
        provenance['capture_refresh'] = dict(mode='capture-only',solver_rerun=False,raw_data_unchanged=True,raw_data_file_count=len(raw_data_hashes),raw_data_sha256=raw_data_hashes)
    write_json(ROOT/'provenance.json', provenance)
    print(json.dumps(dict(status='complete', actual_run=str(actual_directory), field_directory=str(field_directory), energy_error=energy_error, basis_comparisons=convergence, images=images)), flush=True)
    window.close()
    app.processEvents()

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
