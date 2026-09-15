"""Build a local 64-bit Python extension with a portable LLVM-MinGW toolchain.

No pip install, administrator rights, or global environment changes required.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    'S4/S4.cpp', 'S4/rcwa.cpp', 'S4/fmm/fmm_common.cpp',
    'S4/fmm/fmm_FFT.cpp', 'S4/fmm/fmm_kottke.cpp', 'S4/fmm/fmm_closed.cpp',
    'S4/fmm/fmm_PolBasisNV.cpp', 'S4/fmm/fmm_PolBasisVL.cpp',
    'S4/fmm/fmm_PolBasisJones.cpp', 'S4/fmm/fmm_experimental.cpp',
    'S4/fmm/fft_iface.cpp', 'S4/pattern/pattern.c',
    'S4/pattern/intersection.c', 'S4/pattern/predicates.c', 'S4/numalloc.c',
    'S4/gsel.c', 'S4/sort.c', 'S4/kiss_fft/kiss_fft.c',
    'S4/kiss_fft/tools/kiss_fftnd.c', 'S4/SpectrumSampler.c',
    'S4/cubature.c', 'S4/Interpolator.c', 'S4/convert.c', 'S4/main_python.c',
]

def run(command):
    subprocess.run([str(x) for x in command], check=True, cwd=ROOT)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compiler', default=shutil.which('clang'), help='LLVM-MinGW bin/clang.exe')
    p.add_argument('--blas', help='LP64 MKL/OpenBLAS DLL or MinGW import library')
    p.add_argument('--cuda-include', type=Path, help='CUDA <=12.x include directory (optional)')
    p.add_argument('--reference', action='store_true', help='Build original internal math for comparison')
    p.add_argument('--output', type=Path, default=ROOT / 'build' / 'python')
    p.add_argument('--jobs', type=int, default=min(4, os.cpu_count() or 1))
    p.add_argument('--native', action='store_true', help='Optimize for this CPU; binary is less portable')
    args = p.parse_args()
    if sys.platform != 'win32' or sys.maxsize < 2**32:
        p.error('This helper requires 64-bit Windows Python. Use CMake on Linux.')
    if not args.compiler or not Path(args.compiler).is_file():
        p.error('Supply --compiler pointing to LLVM-MinGW clang.exe')
    if args.jobs < 1:
        p.error('--jobs must be positive')
    compiler = Path(args.compiler).resolve()
    bindir = compiler.parent
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    objects = output / 'obj'
    objects.mkdir(exist_ok=True)
    flags = ['-O3', '-DNDEBUG', '-D_USE_MATH_DEFINES', '-Dstrcasecmp=_stricmp',
             '-Wno-deprecated-declarations', '-Wno-implicit-const-int-float-conversion',
             '-Wno-macro-redefined', '-Wno-deprecated-non-prototype']
    for include in ['S4', 'S4/kiss_fft']:
        flags += ['-I', ROOT / include]
    flags += ['-I', sysconfig.get_path('include')]
    if args.native:
        flags += ['-march=native']
    sources = list(SOURCES)
    libraries = [Path(sys.base_prefix) / 'libs' / f'python{sys.version_info.major}{sys.version_info.minor}.lib']
    if args.reference:
        sources += ['S4/RNP/Eigensystems.cpp']
    else:
        flags += ['-DHAVE_BLAS', '-DHAVE_LAPACK', '-DHAVE_S4_ACCEL']
        sources += ['S4/accelerator.cpp']
        if args.cuda_include:
            if not (args.cuda_include / 'cublasXt.h').is_file():
                p.error('--cuda-include must contain cublasXt.h')
            flags += ['-DS4_USE_CUDA', '-I', args.cuda_include]
    # A few legacy routines call BLAS directly even in reference mode.
    blas = Path(args.blas) if args.blas else Path(sys.prefix) / 'Library/bin/mkl_rt.2.dll'
    if not blas.is_file():
        p.error('Supply --blas with an LP64 MKL/OpenBLAS DLL or import library')
    if blas.suffix.lower() == '.dll':
        exports = subprocess.check_output([str(bindir / 'llvm-readobj.exe'), '--coff-exports', str(blas)], text=True)
        names = re.findall(r'^\s+Name: (\S+)', exports, re.MULTILINE)
        if 'zgemm_' not in names or 'zgeev_' not in names:
            p.error('BLAS DLL must expose the LP64 Fortran zgemm_ and zgeev_ interfaces')
        definition = objects / 'blas.def'
        definition.write_text('LIBRARY "' + blas.name + '"\nEXPORTS\n' + '\n'.join(names) + '\n')
        implib = objects / 'blas.dll.a'
        run([bindir / 'llvm-dlltool.exe', '-m', 'i386:x86-64', '-d', definition, '-l', implib])
        libraries.append(implib)
    else:
        libraries.append(blas)
    def compile_one(source):
        obj = objects / (source.replace('/', '_') + '.o')
        cxx = source.endswith('.cpp')
        command = [bindir / ('clang++.exe' if cxx else 'clang.exe')]
        command += ['-std=c++11' if cxx else '-std=gnu99'] + flags
        if cxx:
            command += ['-I', ROOT / 'S4/RNP']
        command += ['-c', ROOT / source, '-o', obj]
        run(command)
        return obj
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        compiled = list(pool.map(compile_one, sources))
    target = output / ('S4' + sysconfig.get_config_var('EXT_SUFFIX'))
    run([bindir / 'clang++.exe', '-shared', '-static-libstdc++', '-static-libgcc',
         '-o', target, *compiled, *libraries])
    # LLVM-MinGW may require libc++/unwind even with static options: supply any
    # actual DLL dependencies beside the module, including their toolchain licenses.
    imports = subprocess.check_output([str(bindir / 'llvm-readobj.exe'), '--coff-imports', str(target)], text=True)
    for name in re.findall(r'^\s+Name: (\S+\.dll)', imports, re.MULTILINE | re.IGNORECASE):
        dep = bindir / name
        if dep.is_file():
            shutil.copy2(dep, output / name)
    shutil.copy2(ROOT / 'python/s4_parallel.py', output / 's4_parallel.py')
    shutil.copy2(ROOT / 'python/s4_runtime.py', output / 's4_runtime.py')
    print(f'Built {target}', flush=True)

if __name__ == '__main__':
    main()
