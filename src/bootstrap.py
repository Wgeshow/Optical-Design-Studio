"""Initialize DLL paths and math limits before importing numerical libraries."""
import os
import sys
from pathlib import Path

_handles = []


def initialize(threads=1):
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = str(threads)
    os.environ["MKL_DYNAMIC"] = "FALSE"
    os.environ["OMP_DYNAMIC"] = "FALSE"
    os.environ["MKL_INTERFACE_LAYER"] = "LP64"
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    os.environ.setdefault("MPLBACKEND", "Agg")
    if os.name == "nt":
        directories = [Path(sys.prefix) / "Library" / "bin"]
        if getattr(sys, 'frozen', False):
            bundled = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
            directories.insert(0, bundled)
            # Prefer the redistributable cuBLAS packaged with this application;
            # an explicit user override still wins. This is inherited by every
            # spawned solver process and avoids machine-specific MATLAB paths.
            for name in ('cublas64_12.dll', 'cublas64_11.dll', 'cublas64_10.dll'):
                candidate = bundled / name
                if candidate.is_file():
                    os.environ.setdefault('S4_CUBLAS_LIBRARY', str(candidate.resolve()))
                    break
            configured = [p for p in os.environ.get('S4_DLL_DIRS', '').split(os.pathsep) if p]
            if str(bundled) not in configured:
                os.environ['S4_DLL_DIRS'] = os.pathsep.join([str(bundled), *configured])
        for directory in directories:
            if directory.is_dir():
                _handles.append(os.add_dll_directory(str(directory)))
