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
data += [(str(source/'cad_runtime'), 'cad_runtime')]
for package in ('gradio', 'gradio_client', 'safehttpx', 'groovy', 'plotly'):
    # Gradio's component metaclasses inspect Python source during import, even
    # though the desktop interface never starts a Gradio server.
    data += collect_data_files(package, include_py_files=package in {'gradio', 'gradio_client'})
for package in ('scipy', 'sklearn'):
    data += collect_data_files(package, excludes=['**/tests/**', '**/test_*/**'])
for package in ('gradio', 'gradio_client', 'scikit-learn', 'scipy', 'joblib', 'threadpoolctl'):
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
for package in ('sklearn', 'scipy', 'gradio', 'gradio_client'):
    hidden += collect_submodules(package, filter=lambda name: '.tests' not in name and '.testing' not in name)

a = Analysis([str(root/'desktop_entry.py'), str(root/'backend_entry.py')],
             pathex=[str(source), str(source/'ml_dependencies')],
             binaries=binaries, datas=data, hiddenimports=hidden,
             hookspath=[], hooksconfig={'matplotlib': {'backends': ['Agg', 'QtAgg']}},
             runtime_hooks=[], excludes=['PyQt5', 'PySide2', 'PySide6', 'tkinter', 'IPython', 'pytest'],
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
