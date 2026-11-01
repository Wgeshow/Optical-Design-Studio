"""Independently verify the new frozen release without developer Python paths.

The Python process here only orchestrates executable launches and reads files.
All application and solver checks run inside the compiled release executables.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import uuid
import zipfile

ROOT=Path(__file__).resolve().parent
VERSION='1.4.0-alpha.8'
GUI_MODULES=('installer_smoke','qt_app','qt_device_builder','qt_lattice_diagram','qt_materials',
    'qt_help','qt_native_figure','qt_native_plot','qt_native_field_volume','qt_field_volume','qt_windows_glass',
    'scan_storage','field_sampling', 'field_reconstruction', 'field_storage', 'direct_npz','simulation_fields','contour_sweep',
    'eigenfree_scan','s4_eigenfree_gpu','gpu_solver_runtime')
BACKEND_MODULES=('backend','field_solver','model','field_volume',
    'scan_storage','field_sampling', 'field_reconstruction', 'field_storage', 'direct_npz','simulation_fields','contour_sweep',
    'eigenfree_scan','s4_eigenfree_gpu','gpu_solver_runtime')
NATIVE_SETUP_MODULES=('qt_simulation_setup','simulation_setup_state','qt_device_lighting',
    'qt_tool_workspace','qt_electrical_material_catalog','qt_results_workspace','qt_optical_results','qt_workspace_start',
    'qt_electrical','qt_electrical_materials','qt_electrical_results',
    'electrical_material_library','electrical_terminal_studies','electrical_thermal','research_simulation','photonic_bands','device_model',
    'research_catalog','research_diagnostics','thermal_study','benchmark_registry','research_physics_runtime','research_physics_worker',
    'sesame_transport','input_diagnostics','qt_input_diagnostics','qt_photonic_bands','qt_photonic_band_results','qt_photonic_crystal_3d','qt_photonic_runtime','qt_research_studies','qt_research_results','qt_thermal_setup',
    'qt_study_flow','qt_simulation_flow','qt_legacy_study_workbench','qt_study_fields','qt_study_library', 'qt_simulation_picker','qt_transport_research_setup','qt_high_field_results','qt_pcsel_research_setup','qt_research_runtime','solver_environment','desktop_environment_probe','qt_solver_environment','simulation_documents','qt_study_transfer',
    'qt_research_common','qt_sesame_setup','pcsel_research','pcsel_aperture','pcsel_optional','pcsel_physics_worker',
    'advanced_transport','advanced_transport_graph','electrical_temperature','nonlocal_tunnelling','high_field_optics','bandgap_narrowing',
    'pcsel_transport_study','pcsel_conformal_mesh','pcsel_conformal_solver','pcsel_transport_worker','pcsel_unitcell_transport',
    'device_project_bridge','custom_electrical_solver','custom_device_optics',
    'electrical_optics','electrical_solver','electrical_preset','contact_optics','optical_unit_cell','pc_array',
    'fdtd_model','meep_runtime','meep_managed','meep_bootstrap','structure_preview')
GUI_MODULES+=NATIVE_SETUP_MODULES
BACKEND_MODULES+=NATIVE_SETUP_MODULES
NATIVE_STARTUP_CHECKS=('initial_maximized_native_surface','restore_state','remaximize_native_surface',
    'system_restore_state','system_maximize_native_surface')

def sha256(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def pe_machine(path):
    with Path(path).open('rb') as stream:
        assert stream.read(2)==b'MZ',str(path)
        stream.seek(0x3c);offset=struct.unpack('<I',stream.read(4))[0]
        stream.seek(offset);assert stream.read(4)==b'PE\0\0',str(path)
        return struct.unpack('<H',stream.read(2))[0]

def validate_native_startup(report, application):
    """A real Windows main-loop launch is required in addition to offscreen checks."""
    assert (report.get('passed') is True and report.get('version')==VERSION
        and report.get('frozen') is True and report.get('platform')=='windows'),report
    assert Path(report.get('executable','')).resolve()==Path(application).resolve(),report
    for name in NATIVE_STARTUP_CHECKS:
        check=report.get('checks',{}).get(name,{})
        assert isinstance(check,dict) and check.get('passed') is True,(name,check)
        if name in ('initial_maximized_native_surface','remaximize_native_surface','system_maximize_native_surface'):
            detail=check.get('detail',{})
            assert isinstance(detail,dict),(name,detail)
            for field in ('qt_surface_alpha_preserved','transparent_background_verified','visible_controls_verified'):
                assert detail.get(field) is True,(name,field,detail)

def audit_payload(application,output):
    from PyInstaller.archive.readers import CArchiveReader
    from stage_release import inventory as source_inventory,tree_digest,REQUIRED_RESOURCES,validate_runtime_resources
    folder=application.parent
    manifest=json.loads((folder/'PAYLOAD-MANIFEST.json').read_text(encoding='utf-8'))
    assert str(manifest.get('version',manifest.get('app_version','')))==VERSION,manifest.keys()
    inventory=manifest['files']
    assert inventory,'Payload inventory is empty'
    for index,(relative,record) in enumerate(inventory.items(),1):
        path=(folder/relative).resolve()
        assert path.is_relative_to(folder),relative
        assert path.stat().st_size==record.get('size',record.get('bytes')),relative
        assert sha256(path)==record['sha256'],relative
        if index%1000==0:print(f'Payload checksums {index}/{len(inventory)}',flush=True)
    actual={path.relative_to(folder).as_posix() for path in folder.rglob('*')
        if path.is_file() and path.name!='PAYLOAD-MANIFEST.json'}
    assert actual==set(inventory),dict(extra=sorted(actual-set(inventory)),missing=sorted(set(inventory)-actual))
    architecture={}
    for relative in ('Optical Design Studio.exe','OpticalDesignBackend.exe','_internal/python312.dll',
            '_internal/_sqlite3.pyd','_internal/sqlite3.dll',
            '_internal/pcs_s4_runtime/S4.cp312-win_amd64.pyd','_internal/PyQt6/Qt6/bin/Qt6Core.dll'):
        machine=pe_machine(folder/relative);assert machine==0x8664,(relative,hex(machine))
        architecture[relative]=hex(machine)
    modules={}
    excluded_qt_modules={}
    for executable,required in (('Optical Design Studio.exe',GUI_MODULES),('OpticalDesignBackend.exe',BACKEND_MODULES)):
        archive=CArchiveReader(str(folder/executable))
        pyz=archive.open_embedded_archive(next(name for name in archive.toc if name.endswith('.pyz')))
        missing=set(required)-set(pyz.toc)
        assert not missing,(executable,missing)
        banned=sorted(name for name in pyz.toc if name.startswith((
            'matplotlib.backends.backend_qt','matplotlib.backends.qt_compat',
            'PyQt5','PySide2','PySide6')))
        assert not banned,(executable,'Unexpected Qt plotting backend or Qt binding',banned)
        modules[executable]=list(required)
        excluded_qt_modules[executable]=dict(matplotlib_qt_backends_absent=True,
            alternative_qt_bindings_absent=True)
    readable=folder/'_internal'/'source'
    staged=ROOT/'source'
    stage=json.loads((ROOT/'stage-manifest.json').read_text(encoding='utf-8'))
    staged_files=source_inventory(staged)
    assert staged_files==stage['files'],'The staged source changed before verification'
    source_tree_sha256=tree_digest(staged_files)
    assert source_tree_sha256==stage['source_tree_sha256']==manifest['source_tree_sha256']
    runtime_resources=validate_runtime_resources(folder/'_internal')
    for name in REQUIRED_RESOURCES:
        record=staged_files.get(name)
        assert record and runtime_resources[name]['sha256']==record['sha256'] and runtime_resources[name]['size']==record['size'],('Native setup runtime resource differs from staged source',name)
    readable_files={name:record for name,record in staged_files.items()
        if Path(name).suffix not in ('.pyd','.dll','.exe')}
    for relative,record in readable_files.items():
        path=readable/relative
        assert path.stat().st_size==record['size'] and sha256(path)==record['sha256'],relative
    frozen_help_files={relative:record for relative,record in staged_files.items()
        if relative.startswith('help_assets/') or relative=='USER_GUIDE.html'}
    for relative,record in frozen_help_files.items():
        path=folder/'_internal'/relative
        assert path.stat().st_size==record['size'] and sha256(path)==record['sha256'],(
            'Frozen Help resource differs from the final stage',relative)
    source_hashes={}
    for name in (*GUI_MODULES,'data_library','qt_core','field_solver','model','app_version'):
        relative=name+'.py'
        assert sha256(readable/relative)==sha256(staged/relative),relative
        source_hashes[relative]=sha256(readable/relative)
    if manifest.get('delivery_profile')=='public':
        with zipfile.ZipFile(folder/'_internal'/'seed_library.zip') as archive:
            assert archive.namelist()==['s4-library-manifest.json'],archive.namelist()
            assert json.loads(archive.read('s4-library-manifest.json'))==dict(format='s4-library',version=1,files={})
    report=dict(version=VERSION,payload_files_verified=len(inventory),architecture=architecture,
        compiled_modules=modules,excluded_qt_modules=excluded_qt_modules,
        source_sha256=source_hashes,delivery_profile=manifest.get('delivery_profile'),
        source_tree_sha256=source_tree_sha256,readable_source_files_verified=len(readable_files),
        frozen_help_files_verified=len(frozen_help_files),
        user_guide_sha256=sha256(readable/'USER_GUIDE.html'),
        executable_sha256=sha256(application),manifest_sha256=sha256(folder/'PAYLOAD-MANIFEST.json'))
    (output/'payload-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return manifest,report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('application',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'verification')
    parser.add_argument('--timeout',type=int,default=600)
    parser.add_argument('--critical',action='store_true',help='Bounded release checks; native Windows startup remains mandatory.')
    args=parser.parse_args()
    application=args.application.resolve(strict=True);output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    manifest,payload=audit_payload(application,output)
    # Keep the isolated test library short on Windows installations whose
    # long-path policy is disabled. Artifacts still go to the requested output.
    session=Path(tempfile.mkdtemp(prefix='ods-132-')).resolve()
    env={key:value for key,value in os.environ.items() if not key.upper().startswith(
        ('PYTHON','CONDA','S4_','QT_','MPL','MKL','OMP','OPENBLAS'))}
    windows=Path(os.environ.get('SystemRoot',r'C:\Windows'))
    env.update(PATH=os.pathsep.join(str(path) for path in (windows/'System32',windows,windows/'System32'/'Wbem')),
        PYTHONNOUSERSITE='1',PYINSTALLER_RESET_ENVIRONMENT='1',QT_QPA_PLATFORM='offscreen',
        S4_LIBRARY_ROOT=str(session/'User Data'),S4_SELF_TEST_GPU='0',
        S4_SELF_TEST_MIN_SAVED_ENTRIES=str(manifest.get('build_input',{}).get('seed_runs',0)),
        S4_SELF_TEST_EXPECT_EMPTY_LIBRARY='1' if manifest.get('delivery_profile')=='public' else '0')
    env['ODS_RELEASE_CRITICAL_SMOKE']='1' if args.critical else '0'
    report_path=output/'report.json'
    with (output/'stdout.log').open('w',encoding='utf-8') as stdout,(output/'stderr.log').open('w',encoding='utf-8') as stderr:
        process=subprocess.Popen([str(application),'--self-test',str(report_path)],cwd=session,env=env,
            stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:code=process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)
            process.wait(timeout=15)
            raise
    report=json.loads(report_path.read_text(encoding='utf-8'))
    assert code==0 and report['passed'],dict(exit_code=code,failed=[name for name,check in report['checks'].items() if not check['passed']])
    assert report['version']==VERSION and report['frozen']
    assert Path(report['executable']).resolve()==application
    assert Path(report['library_root']).resolve()==Path(env['S4_LIBRARY_ROOT'])
    assert report.get('validation_profile')==('critical_release' if args.critical else 'full_installer')
    assert report['checks']['desktop_pages_and_themes']['detail']['themes']==(['light'] if args.critical else ['dark','light','glass_dark','glass_light'])
    models=report['checks']['simulation_launcher_and_model_screens']['detail']
    assert models.get('choices_checked')==29 and len(models.get('choices',[]))==29,models
    assert all(row.get('passed') is True for row in models['choices']),models
    assert all(models.get(key) is True for key in ('editable_models_verified','correct_model_routes_verified',
        'independent_documents_verified','portable_drafts_verified','selective_transfer_verified','no_unintended_windows')),models
    assert models.get('unique_setup_pages')==28,models
    windows=report['checks']['no_transient_panel_windows']['detail']
    assert windows.get('unintended_count')==0 and windows.get('observed_before_main_construction') is True,windows
    assert models.get('automatic_jobs_started')==0,models
    grid=report['checks']['exact_parameter_grid']['detail']
    assert grid.get('designs')==4 and grid.get('spectral_rows')==24,grid
    assert all(grid.get(key) is True for key in ('unselected_inputs_unchanged','exact_requested_wavelengths',
        'archive_raw_bytes_verified','post_analysis_immutable')),grid
    environment=report['checks']['automatic_environment_resources']['detail']
    assert environment.get('setup_modules_imported') is True and environment.get('downloads_started') is False,environment
    assert environment.get('providers')==['gmsh','legume','meep','mpb','sesame'],environment
    assert len(report['checks']['native_cpu_spectrum']['detail']['rows'])==3
    if not args.critical:
        controls=report['checks']['native_reference_controls_and_graphs']['detail']
        assert controls['physical_model_unchanged'] and controls['shared_settings_preview']
        assert controls['native_2d_canvases'] and controls['native_3d_canvases'] and not controls['live_matplotlib_qt_widgets']
        fields=report['checks']['native_electric_field_maps_and_features']['detail']
        assert fields['selected_csv_verified']
        assert fields['selected_snapshot']==Path(fields['directory']).resolve().relative_to(
            (Path(env['S4_LIBRARY_ROOT'])/'runs').resolve()).as_posix()
        assert fields['live_renderer']=='NativeVolumeCanvas' and fields['native_2d_field_maps']
        assert fields['native_orbit_and_zoom'] and fields['actual_phase_vectors_verified']
        assert fields['saved_xyz_and_complex_fields_preserved'] and not fields['live_publication_artists_created']
        speed=report['checks']['simulation_speed_and_scan_storage']['detail']
        assert all(speed.get(name) is True for name in (
            'spectrum_rta_only','separate_field_job','validated_fourier_sampling',
            'exact_disk_backed_spectrum','compact_scan_roundtrip','contour_label_parity')),speed
        assert speed.get('field_sample_count')==3,speed
        maximize=report['checks']['maximize_restore_painting']['detail']
        assert maximize.get('maximized_transparency_policy_verified') is True,maximize
        assert maximize.get('restored_glass_policy') is True,maximize
        assert maximize.get('looks')==['glass_dark','glass_light'],maximize
    errors=(output/'stderr.log').read_text(encoding='utf-8',errors='replace')
    assert not any(marker in errors for marker in ('Traceback (most recent call last)','Exception ignored','ModuleNotFoundError:','ImportError:')),errors[-5000:]
    # The offscreen path does not call qt_app.main or restore native geometry.
    # Run the actual GUI entry through Windows QPA with its own preferences,
    # temporary files and data; do not inherit an offscreen platform override.
    native_session=output/'native-startup-session'
    native_session.mkdir(parents=True,exist_ok=True)
    native_env=dict(env)
    native_env.update(QT_QPA_PLATFORM='windows',TEMP=str(native_session),TMP=str(native_session),
        S4_LIBRARY_ROOT=str(native_session/'User Data'))
    native_report_path=output/'native-startup-report.json'
    with (output/'native-startup-stdout.log').open('w',encoding='utf-8') as stdout,(output/'native-startup-stderr.log').open('w',encoding='utf-8') as stderr:
        native_process=subprocess.Popen([str(application),'--native-startup-test',str(native_report_path)],
            cwd=native_session,env=native_env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:native_code=native_process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill','/PID',str(native_process.pid),'/T','/F'],stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)
            native_process.wait(timeout=15)
            raise
    native_report=json.loads(native_report_path.read_text(encoding='utf-8'))
    assert native_code==0,dict(exit_code=native_code,report=native_report)
    validate_native_startup(native_report,application)
    native_errors=(output/'native-startup-stderr.log').read_text(encoding='utf-8',errors='replace')
    assert not any(marker in native_errors for marker in ('Traceback (most recent call last)','Exception ignored','ModuleNotFoundError:','ImportError:')),native_errors[-5000:]
    result=dict(status='passed',version=VERSION,application=str(application),source_python_used_by_application=False,
        environment_path=env['PATH'],isolated_library=env['S4_LIBRARY_ROOT'],report=str(report_path),
        payload_audit=str(output/'payload-audit.json'),checks=list(report['checks']),
        source_tree_sha256=payload['source_tree_sha256'],
        readable_source_files_verified=payload['readable_source_files_verified'],
        payload_files_verified=payload['payload_files_verified'],native_fields_verified=not args.critical,
        validation_profile=report['validation_profile'],omitted_checks=report.get('omitted_checks',[]),
        native_startup_verified=True,native_startup_report=str(native_report_path),
        native_startup_report_sha256=sha256(native_report_path),
        native_startup_executable_sha256=sha256(application),
        native_startup_checks=list(NATIVE_STARTUP_CHECKS),
        visible_windows_opened=True,existing_installation_modified=False)
    (output/'independent-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
