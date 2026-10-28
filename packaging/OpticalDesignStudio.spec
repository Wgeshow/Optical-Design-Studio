# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH)
inputs = Path(os.environ.get('ODS_NATIVE_INPUTS', root.parent/'local-windows-review-1.2.5-ui-review2'/'build_input'))
source = root/'source'
dependency_source = Path(os.environ.get('ODS_RELEASE_DEPENDENCIES', root.parent/'s4_ui_redesign'))
dependency_paths = [dependency_source/name for name in ('plot_dependencies', 'ml_dependencies', 'geometry_dependencies')]
for key in ('ODS_DEVSIM_DEPENDENCIES',):
    if os.environ.get(key):dependency_paths.insert(0,Path(os.environ[key]))
for path in reversed([source, *dependency_paths]):
    sys.path.insert(0, str(path))
env_bin = Path(os.environ.get('ODS_OFFICIAL_RUNTIME', Path(sys.prefix)/'Library'/'bin'))
cad_runtime = Path(os.environ.get('ODS_CAD_RUNTIME', env_bin/'cad_runtime' if os.environ.get('ODS_OFFICIAL_RUNTIME') else dependency_source/'cad_runtime'))
vtk_marker = cad_runtime/'vtk.libs'/'vtk-runtime-directory.txt'
if not vtk_marker.is_file():vtk_marker = inputs.parent/'assets'/'vtk-runtime-directory.txt'

data = [(str(root/'seed_library.zip'), '.'), (str(source/'S4_Studio.ico'), '.'),
        (str(source/'meep_runner.py'), '.'),
        (str(source/'research_physics_worker.py'), '.'),
        (str(source/'pcsel_physics_worker.py'), '.'),
        (str(source/'pcsel_transport_worker.py'), '.'),
        (str(source/'simulation_setup_plan.json'), '.'),
        (str(source/'pcs_s4_runtime'/'s4_runtime.py'), 'pcs_s4_runtime'),
        (str(source/'pcs_s4_runtime'/'s4_parallel.py'), 'pcs_s4_runtime'),
        (str(vtk_marker), 'cad_runtime/vtk.libs')]
# Qt Help resolves assets relative to its frozen module; retain the complete
# approved Silicon tutorial (41 saved wavelength field CSVs), not a seed library.
for path in (source/'help_assets').rglob('*'):
    if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
        data.append((str(path), str(Path('help_assets')/path.relative_to(source/'help_assets').parent)))
for path in source.iterdir():
    if path.is_file() and path.suffix.lower() in ('.md', '.html'):
        data.append((str(path), '.'))
for path in (source/'electrical_materials').glob('*.csv'):
    data.append((str(path),'electrical_materials'))
for path in (source/'benchmark_data').rglob('*'):
    if path.is_file():
        data.append((str(path), str(Path('benchmark_data')/path.relative_to(source/'benchmark_data').parent)))

# Preserve the existing isolated CAD runtime: its NumPy/SciPy must never replace
# the solver environment. IVtk loads vtk.libs dynamically, so retain its DLLs.
for path in cad_runtime.rglob('*'):
    if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
        continue
    relative = path.relative_to(cad_runtime)
    top = relative.parts[0].casefold()
    if top == 'vtkmodules' or top == 'vtk.py' or top.startswith('vtk-'):
        continue
    if top == 'ocp' and len(relative.parts) > 1 and relative.parts[1].casefold().startswith('ivtk'):
        continue
    data.append((str(path), str(Path('cad_runtime')/relative.parent)))
for package in ('scipy', 'sklearn', 'shapely', 'pyqtgraph'):
    data += collect_data_files(package, excludes=['**/tests/**', '**/test_*/**', '**/examples/**'])
for package in ('scikit-learn', 'scipy', 'joblib', 'threadpoolctl', 'shapely', 'pyqtgraph', 'colorama', 'devsim'):
    data += copy_metadata(package)

# Conda's _sqlite3 extension requires its Library/bin DLL even when the
# installed application has no developer or Conda directories on PATH.
assert (env_bin/'sqlite3.dll').is_file(), 'Missing SQLite runtime in the build environment'
# Keep pinned S4, CUDA and MKL runtime inputs unchanged from release 1.2.9.
names = ['sqlite3.dll', 'ffi.dll', 'libiomp5md.dll', 'mkl_rt.2.dll', 'mkl_core.2.dll',
         'mkl_intel_thread.2.dll', 'mkl_sequential.2.dll', 'mkl_def.2.dll',
         'mkl_mc.2.dll', 'mkl_mc3.2.dll', 'mkl_avx.2.dll', 'mkl_avx2.2.dll', 'mkl_avx512.2.dll']
names += [p.name for p in env_bin.glob('mkl_vml*.dll')]
names += [p.name for p in env_bin.glob('msvcp140*.dll')]
names += [p.name for p in env_bin.glob('vcruntime140*.dll')]
binaries = [(str(env_bin/name), '.') for name in sorted(set(names))]
binaries += [(str(inputs/'gpu'/name), '.') for name in ('cublas64_11.dll', 'cublasLt64_11.dll', 'cudart64_110.dll')]
binaries += [(str(source/'pcs_s4_runtime'/'S4.cp312-win_amd64.pyd'), 'pcs_s4_runtime')]
binaries += collect_dynamic_libs('devsim')
data += collect_data_files('devsim')

hidden = ['matplotlib.backends.backend_agg', 'PyQt6.sip', 'yaml',
          'qt_native_plot', 'qt_native_figure', 'qt_native_field_volume',
          'qt_field_volume', 'qt_structure_3d', 'qt_lattice_diagram', 'qt_windows_glass',
          'qt_pcsel', 'qt_multi_hole', 'qt_design_materials', 'circle_geometry', 'optical_objective',
          'pyqtgraph.exporters', 'colorama',
          'scan_storage', 'field_sampling', 'field_reconstruction', 'field_storage', 'direct_npz', 'simulation_fields', 'contour_sweep',
          'eigenfree_scan', 's4_eigenfree_gpu', 'gpu_solver_runtime', 'graphlib']
hidden += ['qt_electrical','electrical_solver','electrical_optics','electrical_preset']
hidden += ['electrical_sweep', 'electrical_thermal', 'electrical_transport', 'electrical_graph_transport',
           'electrical_fermi_transport', 'electrical_native_graph',
           'electrical_transport_adapter', 'qt_transport_setup']
hidden += ['research_simulation', 'photonic_bands', 'research_catalog', 'research_diagnostics',
           'thermal_study', 'benchmark_registry', 'research_physics_runtime', 'research_physics_worker','sesame_transport',
           'input_diagnostics','qt_input_diagnostics','qt_photonic_bands','qt_photonic_band_results','qt_photonic_crystal_3d','qt_photonic_runtime','qt_research_studies','qt_research_results','qt_thermal_setup',
           'qt_study_flow','qt_simulation_flow','qt_legacy_study_workbench','qt_study_fields','qt_study_library', 'qt_simulation_picker','qt_transport_research_setup','qt_high_field_results','qt_pcsel_research_setup','qt_research_runtime','solver_environment','desktop_environment_probe','qt_solver_environment','simulation_documents','qt_study_transfer']
hidden += ['qt_research_common','qt_sesame_setup','pcsel_research','pcsel_aperture','pcsel_optional','pcsel_physics_worker',
           'advanced_transport','advanced_transport_graph','electrical_temperature','nonlocal_tunnelling','high_field_optics','bandgap_narrowing',
           'pcsel_transport_study','pcsel_conformal_mesh','pcsel_conformal_solver','pcsel_transport_worker','pcsel_unitcell_transport']
hidden += ['qt_custom_device','device_model','device_project_bridge','custom_electrical_solver',
           'custom_device_optics','electrical_material_library','qt_electrical_materials',
           'electrical_terminal_studies','qt_electrical_results','contact_optics',
           'qt_reference_style','qt_results_workspace','optical_unit_cell','pc_array']
hidden += ['qt_simulation_setup','simulation_setup_state','qt_device_lighting',
           'qt_tool_workspace','qt_electrical_material_catalog','qt_optical_results','qt_workspace_start','fdtd_model',
           'meep_runtime','meep_managed','meep_bootstrap','structure_preview']
hidden += collect_submodules('devsim')
hidden += collect_submodules('electrical_physics')
# Optional CUDA solver packages retain their on-disk layout for JIT headers,
# dynamic libraries and CUDA path discovery. Keep the app's NumPy authoritative.
gpu_packages = os.environ.get('ODS_EIGENFREE_GPU_PACKAGES')
gpu_cuda = os.environ.get('ODS_EIGENFREE_CUDA')
if gpu_packages:
    package_root = Path(gpu_packages)
    for name in ('cupy', 'cupy_backends', 'cupyx', 'fastrlock', 'cuda', 'nvidia'):
        folder = package_root/name
        if not folder.is_dir():
            raise FileNotFoundError(folder)
        for path in folder.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                relative = path.relative_to(package_root)
                if relative.parts[:4] == ('nvidia','cu13','bin','x86_64'):
                    relative = Path('nvidia/cu13/bin')/path.name
                data.append((str(path), str(Path('gpu_solver_runtime')/relative.parent)))
    for folder in package_root.glob('*.dist-info'):
        if folder.name.startswith(('cupy_', 'fastrlock-', 'cuda_pathfinder-', 'nvidia_')):
            for path in folder.rglob('*'):
                if path.is_file():
                    data.append((str(path), str(Path('gpu_solver_runtime')/path.relative_to(package_root).parent)))
    if not gpu_cuda:
        raise ValueError('ODS_EIGENFREE_CUDA must accompany the GPU solver packages')
    cuda_root = Path(gpu_cuda)
    for path in cuda_root.rglob('*'):
        if path.is_file():
            relative = path.relative_to(cuda_root)
            if relative.parts[:2] == ('bin','x86_64'):
                relative = Path('bin')/path.name
            data.append((str(path), str(Path('gpu_solver_runtime/nvidia/cu13')/relative.parent)))
    # Retain the CUDA wheel metadata and licenses alongside its native payload.
    for folder in cuda_root.parent.parent.glob('nvidia_*.dist-info'):
        for path in folder.rglob('*'):
            if path.is_file():
                data.append((str(path),str(Path('gpu_solver_runtime')/path.relative_to(cuda_root.parent.parent).parent)))
for package in ('sklearn', 'scipy', 'shapely', 'pyqtgraph'):
    hidden += collect_submodules(package, filter=lambda name: not any(
        part in name.split('.') for part in ('tests', 'testing', 'examples', 'opengl', 'jupyter', 'MatplotlibWidget')))

hidden += ['ai_campaign_storage', 'optical_ui_scope', 'pcsel_paper_studies', 'qt_geometry_history', 'qt_journey', 'qt_optical_domain_canvas', 'qt_optical_journey', 'qt_pcsel_paper', 'qt_research_journey', 'qt_study_device_editor', 'qt_study_navigation']

a = Analysis([str(root/'desktop_entry.py'), str(root/'backend_entry.py')],
             pathex=[str(source), *map(str, dependency_paths)],
             binaries=binaries, datas=data, hiddenimports=hidden,
             hookspath=[], hooksconfig={'matplotlib': {'backends': ['Agg']}},
             runtime_hooks=[], excludes=['matplotlib.backends.backend_qtagg',
                'matplotlib.backends.backend_qt5agg', 'matplotlib.backends.backend_qt',
                'pyqtgraph.widgets.MatplotlibWidget',
                'PyQt5', 'PySide2', 'PySide6', 'tkinter', 'IPython', 'pytest',
                'gradio', 'gradio_client', 'plotly', 'safehttpx', 'groovy', 'vtk', 'vtkmodules',
                'cupy', 'cupy_backends', 'cupyx', 'fastrlock', 'cuda.pathfinder'],
             noarchive=False)
# CUDA discovery must resolve the toolkit in gpu_solver_runtime. PyInstaller's
# dependency scanner also adds root DLL copies, which make CuPy infer the
# executable directory as CUDA_PATH and lose its bin/include layout.
if gpu_packages:
    cuda_dll_names = {path.name.casefold() for folder in
        (Path(gpu_packages)/'nvidia',Path(gpu_cuda)) for path in folder.rglob('*.dll')}
    a.binaries = [entry for entry in a.binaries if not (
        len(Path(entry[0]).parts) == 1 and Path(entry[0]).name.casefold() in cuda_dll_names)]
pyz = PYZ(a.pure)
entries = {script[0]: script for script in a.scripts if script[0] in {'desktop_entry', 'backend_entry'}}
assert len(entries) == 2, entries
hooks = [script for script in a.scripts if script[0] not in entries]
common = dict(exclude_binaries=True, debug=False, strip=False, upx=False,
              icon=str(source/'S4_Studio.ico'), version=str(root/'version_info.txt'),
              uac_admin=False, contents_directory='_internal')
gui = EXE(pyz, hooks+[entries['desktop_entry']], [], name='Optical Design Studio', console=False, **common)
backend = EXE(pyz, hooks+[entries['backend_entry']], [], name='OpticalDesignBackend', console=True, **common)
coll = COLLECT(gui, backend, a.binaries, a.datas, strip=False, upx=False, name='Optical Design Studio')
