# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH)
inputs = Path(os.environ.get('ODS_NATIVE_INPUTS', root.parent/'local-windows-review-1.2.5-ui-review2'/'build_input'))
source = root/'source'
dependency_source = Path(os.environ.get('ODS_RELEASE_DEPENDENCIES', root.parent/'s4_ui_redesign'))
dependency_paths = [dependency_source/name for name in ('plot_dependencies', 'ml_dependencies', 'geometry_dependencies')]
for path in reversed([source, *dependency_paths]):
    sys.path.insert(0, str(path))
env_bin = Path(sys.prefix)/'Library'/'bin'

data = [(str(root/'seed_library.zip'), '.'), (str(source/'S4_Studio.ico'), '.'),
        (str(source/'meep_runner.py'), '.'),
        (str(source/'pcs_s4_runtime'/'s4_runtime.py'), 'pcs_s4_runtime'),
        (str(source/'pcs_s4_runtime'/'s4_parallel.py'), 'pcs_s4_runtime'),
        (str(inputs.parent/'assets'/'vtk-runtime-directory.txt'), 'cad_runtime/vtk.libs')]
# Qt Help resolves assets relative to its frozen module; retain the complete
# approved Silicon tutorial (41 saved wavelength field CSVs), not a seed library.
for path in (source/'help_assets').rglob('*'):
    if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
        data.append((str(path), str(Path('help_assets')/path.relative_to(source/'help_assets').parent)))
for path in source.iterdir():
    if path.is_file() and path.suffix.lower() in ('.md', '.html'):
        data.append((str(path), '.'))

# Preserve the existing isolated CAD runtime: its NumPy/SciPy must never replace
# the solver environment. IVtk loads vtk.libs dynamically, so retain its DLLs.
cad_runtime = dependency_source/'cad_runtime'
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
for package in ('scikit-learn', 'scipy', 'joblib', 'threadpoolctl', 'shapely', 'pyqtgraph', 'colorama'):
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

hidden = ['matplotlib.backends.backend_agg', 'PyQt6.sip', 'yaml',
          'qt_native_plot', 'qt_native_figure', 'qt_native_field_volume',
          'qt_field_volume', 'qt_structure_3d', 'qt_lattice_diagram', 'qt_windows_glass',
          'qt_pcsel', 'qt_multi_hole', 'qt_design_materials', 'circle_geometry', 'optical_objective',
          'pyqtgraph.exporters', 'colorama',
          'scan_storage', 'field_sampling', 'simulation_fields', 'contour_sweep']
for package in ('sklearn', 'scipy', 'shapely', 'pyqtgraph'):
    hidden += collect_submodules(package, filter=lambda name: not any(
        part in name.split('.') for part in ('tests', 'testing', 'examples', 'opengl', 'jupyter', 'MatplotlibWidget')))

a = Analysis([str(root/'desktop_entry.py'), str(root/'backend_entry.py')],
             pathex=[str(source), *map(str, dependency_paths)],
             binaries=binaries, datas=data, hiddenimports=hidden,
             hookspath=[], hooksconfig={'matplotlib': {'backends': ['Agg']}},
             runtime_hooks=[], excludes=['matplotlib.backends.backend_qtagg',
                'matplotlib.backends.backend_qt5agg', 'matplotlib.backends.backend_qt',
                'pyqtgraph.widgets.MatplotlibWidget',
                'PyQt5', 'PySide2', 'PySide6', 'tkinter', 'IPython', 'pytest',
                'gradio', 'gradio_client', 'plotly', 'safehttpx', 'groovy', 'vtk', 'vtkmodules'],
             noarchive=False)
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
