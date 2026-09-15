# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH)
inputs = root/'build_input'
source = inputs/'source'
sys.path.insert(0, str(source/'ml_dependencies'))
sys.path.insert(0, str(source))
env_bin = Path(sys.prefix)/'Library'/'bin'

data = [(str(inputs/'seed_library.zip'), '.'), (str(inputs/'S4_Studio.ico'), '.'),
        (str(source/'pcs_s4_runtime'/'s4_runtime.py'), 'pcs_s4_runtime'),
        (str(source/'pcs_s4_runtime'/'s4_parallel.py'), 'pcs_s4_runtime')]
# Keep the CAD stack isolated: its own NumPy/SciPy must not override the solver.
# The exporter uses OpenCascade directly.  VTK is a CadQuery visualization
# dependency and is not used by either STEP or COMSOL export, so do not ship
# its 300+ MB runtime in the native desktop package.
cad_runtime = source/'cad_runtime'
for path in cad_runtime.rglob('*'):
    if not path.is_file():
        continue
    relative = path.relative_to(cad_runtime)
    top = relative.parts[0].casefold()
    if top in {'vtk.libs', 'vtkmodules'} or top == 'vtk.py' or top.startswith('vtk-'):
        continue
    if top == 'ocp' and len(relative.parts) > 1 and relative.parts[1].casefold().startswith('ivtk'):
        continue
    data.append((str(path), str(Path('cad_runtime')/relative.parent)))
for package in ('scipy', 'sklearn'):
    data += collect_data_files(package, excludes=['**/tests/**', '**/test_*/**'])
for package in ('scikit-learn', 'scipy', 'joblib', 'threadpoolctl'):
    data += copy_metadata(package)

# MKL chooses a dispatch library at runtime; include the supported CPU families.
names = ['ffi.dll', 'libiomp5md.dll', 'mkl_rt.2.dll', 'mkl_core.2.dll',
         'mkl_intel_thread.2.dll', 'mkl_sequential.2.dll',
         'mkl_def.2.dll', 'mkl_mc.2.dll', 'mkl_mc3.2.dll', 'mkl_avx.2.dll',
         'mkl_avx2.2.dll', 'mkl_avx512.2.dll']
names += [p.name for p in env_bin.glob('mkl_vml*.dll')]
names += [p.name for p in env_bin.glob('msvcp140*.dll')]
names += [p.name for p in env_bin.glob('vcruntime140*.dll')]
binaries = [(str(env_bin/n), '.') for n in sorted(set(names))]
binaries += [(str(inputs/'gpu'/name), '.') for name in ('cublas64_11.dll', 'cublasLt64_11.dll', 'cudart64_110.dll')]
binaries += [(str(source/'pcs_s4_runtime'/'S4.cp312-win_amd64.pyd'), 'pcs_s4_runtime')]

hidden = ['matplotlib.backends.backend_qtagg', 'PyQt6.sip', 'yaml']
for package in ('sklearn', 'scipy'):
    hidden += collect_submodules(package, filter=lambda name: '.tests' not in name and '.testing' not in name)

a = Analysis([str(root/'desktop_entry.py'), str(root/'backend_entry.py')],
             pathex=[str(source), str(source/'ml_dependencies')],
             binaries=binaries, datas=data, hiddenimports=hidden,
             hookspath=[], hooksconfig={'matplotlib': {'backends': ['Agg', 'QtAgg']}},
             runtime_hooks=[], excludes=['PyQt5', 'PySide2', 'PySide6', 'tkinter', 'IPython', 'pytest',
                                                'gradio', 'gradio_client', 'plotly', 'safehttpx', 'groovy', 'vtk', 'vtkmodules'],
             noarchive=False)
pyz = PYZ(a.pure)
entries = {script[0]: script for script in a.scripts if script[0] in {'desktop_entry', 'backend_entry'}}
assert len(entries) == 2, entries
hooks = [script for script in a.scripts if script[0] not in entries]
common = dict(exclude_binaries=True, debug=False, strip=False, upx=False,
              icon=str(inputs/'S4_Studio.ico'), version=str(root/'version_info.txt'),
              uac_admin=False, contents_directory='_internal')
gui = EXE(pyz, hooks+[entries['desktop_entry']], [], name='Optical Design Studio', console=False, **common)
backend = EXE(pyz, hooks+[entries['backend_entry']], [], name='OpticalDesignBackend', console=True, **common)
coll = COLLECT(gui, backend, a.binaries, a.datas, strip=False, upx=False, name='Optical Design Studio')
