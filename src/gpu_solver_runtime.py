"""Load the optional CUDA solver dependencies shipped with a portable build."""
import os
from pathlib import Path
import sys

_dll_handles = []
_configured = False


def load_cupy():
    global _configured
    if not _configured:
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'gpu_solver_runtime'
        if root.is_dir():
            sys.path.insert(0, str(root))
            cuda = root / 'nvidia' / 'cu13'
            if cuda.is_dir():
                os.environ['CUDA_PATH'] = str(cuda)
                if os.name == 'nt':
                    for folder in (cuda/'bin'/'x86_64', cuda/'bin', root/'fastrlock'):
                        if folder.is_dir():
                            _dll_handles.append(os.add_dll_directory(str(folder)))
        _configured = True
    try:
        import cupy
    except ImportError as exc:
        raise RuntimeError('The GPU scattering runtime is unavailable. Select S4 native in '
                           'Settings → Performance, or use the portable build with CUDA support. '
                           + str(exc)) from exc
    return cupy
