"""Build the matching native S4 extension for Linux in the active environment."""
import importlib.machinery
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cuda', action='store_true',
                        help='Build optional cuBLAS GPU support; requires a compatible CUDA toolkit (10/11/12).')
    args = parser.parse_args(argv)
    if not sys.platform.startswith('linux'):
        raise SystemExit('Run this setup on Linux. Windows uses the supplied Python 3.12 extension.')
    root = Path(__file__).resolve().parent
    for executable in ('cmake', 'c++', 'cc'):
        if not shutil.which(executable):
            raise SystemExit('Install build-essential, cmake, python3-dev and libopenblas-dev using your Linux package manager first.')
    build = root / 'native_build' / 'linux'
    subprocess.run(['cmake', '-S', str(root/'S4-source'), '-B', str(build),
                    '-DCMAKE_BUILD_TYPE=Release', '-DS4_NATIVE=OFF', '-DS4_ENABLE_CUDA='+('ON' if args.cuda else 'OFF'),
                    '-DBLA_VENDOR=OpenBLAS', '-DPython3_EXECUTABLE='+sys.executable], check=True)
    subprocess.run(['cmake', '--build', str(build), '--target', 'S4', '--parallel', str(min(4, os.cpu_count() or 1))], check=True)
    destination = root / 'pcs_s4_runtime' / sys.platform
    destination.mkdir(parents=True, exist_ok=True)
    binaries = [p for p in build.rglob('S4*.so') if any(p.name == 'S4'+s for s in importlib.machinery.EXTENSION_SUFFIXES)]
    if len(binaries) != 1:
        raise RuntimeError('Expected exactly one matching Python S4 extension after the build')
    shutil.copy2(binaries[0], destination / binaries[0].name)
    print('Built:', destination / binaries[0].name)
    print('Run: bash launch_peak_gui.sh')


if __name__ == '__main__':
    main()
