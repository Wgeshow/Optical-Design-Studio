"""Configure native thread counts and DLL directories BEFORE importing S4/NumPy."""
import os
from pathlib import Path
import sys

_dll_handles = []

def configure(threads=1, gpu=False, gpu_device=0, gpu_min_n=1024, dll_dirs=(), base_fallback=True):
    for name, value, minimum in [('threads', threads, 1), ('gpu_device', gpu_device, 0), ('gpu_min_n', gpu_min_n, 1)]:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f'{name} must be an integer >= {minimum}')
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'BLIS_NUM_THREADS'):
        os.environ[name] = str(threads)
    os.environ['MKL_DYNAMIC'] = 'FALSE'
    os.environ['OMP_DYNAMIC'] = 'FALSE'
    os.environ['MKL_INTERFACE_LAYER'] = 'LP64'
    os.environ['S4_GPU'] = '1' if gpu else '0'
    os.environ['S4_GPU_DEVICE'] = str(gpu_device)
    os.environ['S4_GPU_MIN_N'] = str(gpu_min_n)
    # CPython 3.8+ does not generally use PATH to find extension dependencies.
    if os.name == 'nt':
        candidates = [Path(sys.prefix) / 'Library/bin'] + [Path(p) for p in dll_dirs]
        candidates += [Path(p) for p in os.environ.get('S4_DLL_DIRS', '').split(os.pathsep) if p]
        # A named Conda environment may intentionally contain only Python,
        # while the compatible MKL runtime is installed in the Conda base
        # environment used to build this module. Make that DLL directory
        # available before importing S4, without permanently changing PATH.
        environment_root = Path(sys.prefix).resolve()
        if base_fallback and environment_root.parent.name.lower() == 'envs':
            candidates.append(environment_root.parent.parent / 'Library/bin')
        # With `conda create -n NAME`, Conda commonly stores the environment
        # in ~/.conda/envs while CONDA_EXE still points at its base install.
        # That is the authoritative base location in this situation.
        conda_executable = os.environ.get('CONDA_EXE')
        if base_fallback and conda_executable:
            candidates.append(Path(conda_executable).resolve().parent.parent / 'Library/bin')
        previous_prefix = os.environ.get('CONDA_PREFIX_1')
        if base_fallback and previous_prefix:
            candidates.append(Path(previous_prefix) / 'Library/bin')
        # MATLAB often ships a compatible CUDA 10/11/12 runtime. Locate it on
        # this machine without adding anything permanently to PATH.
        if gpu and 'S4_CUBLAS_LIBRARY' not in os.environ:
            program_files = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))
            for directory in sorted((program_files/'MATLAB').glob('R*/bin/win64'), reverse=True):
                found = next((directory/name for name in
                    ('cublas64_12.dll','cublas64_11.dll','cublas64_10.dll') if (directory/name).is_file()), None)
                if found:
                    os.environ['S4_CUBLAS_LIBRARY'] = str(found.resolve())
                    candidates.append(directory)
                    break
        for directory in candidates:
            if directory.is_dir():
                _dll_handles.append(os.add_dll_directory(str(directory.resolve())))
    return {'threads': threads, 'gpu': bool(gpu), 'gpu_device': gpu_device, 'gpu_min_n': gpu_min_n}
