"""Build the CPython S4 extension without a system compiler installation.

Requires the portable ziglang 0.13 package, CPython development headers/libs,
and an existing LP64 MKL runtime DLL. Everything generated stays in --output.
Pass --cuda-headers with the root of installed nvidia-cublas-cu11 and
nvidia-cuda-runtime-cu11 wheels to retain the optional dynamic cuBLASXt backend.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pefile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zig", type=Path, required=True)
    parser.add_argument("--mkl-dll", type=Path, required=True)
    parser.add_argument("--python-home", type=Path, default=Path(sys.base_prefix))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cuda-headers", type=Path)
    parser.add_argument("--cuda-nvcc-headers", type=Path)
    parser.add_argument("--cuda-eigen-headers", type=Path, action="append", default=[],
                        help="CUDA headers exposing cuSOLVER Xgeev; repeat for CRT/CCCL include roots")
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(args.output / "zig-cache"),
               ZIG_LOCAL_CACHE_DIR=str(args.output / "zig-local-cache"))

    def run(cmd):
        completed = subprocess.run([str(x) for x in cmd], env=env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if completed.returncode:
            raise RuntimeError(" ".join(map(str, cmd)) + "\n" + completed.stdout)
        return completed.stdout

    exports = pefile.PE(str(args.mkl_dll), max_symbol_exports=1000000).DIRECTORY_ENTRY_EXPORT.symbols
    definition = args.output / "mkl_runtime.def"
    definition.write_text('LIBRARY "' + args.mkl_dll.name + '"\nEXPORTS\n' +
                          "\n".join(x.name.decode() for x in exports if x.name) + "\n")
    mkl_lib = args.output / "mkl_runtime.lib"
    run([args.zig, "dlltool", "-m", "i386:x86-64", "-d", definition, "-l", mkl_lib])
    sources = """S4/S4.cpp S4/rcwa.cpp S4/accelerator.cpp S4/cuda_eigensolver.cpp
        S4/fmm/fmm_common.cpp S4/fmm/fmm_FFT.cpp S4/fmm/fmm_kottke.cpp
        S4/fmm/fmm_closed.cpp S4/fmm/fmm_PolBasisNV.cpp S4/fmm/fmm_PolBasisVL.cpp
        S4/fmm/fmm_PolBasisJones.cpp S4/fmm/fmm_experimental.cpp S4/fmm/fft_iface.cpp
        S4/pattern/pattern.c S4/pattern/intersection.c S4/pattern/predicates.c
        S4/numalloc.c S4/gsel.c S4/sort.c S4/kiss_fft/kiss_fft.c
        S4/kiss_fft/tools/kiss_fftnd.c S4/SpectrumSampler.c S4/cubature.c
        S4/Interpolator.c S4/convert.c S4/main_python.c""".split()
    common = ["-target", "x86_64-windows-gnu", "-O3", "-DNDEBUG",
              "-DHAVE_BLAS", "-DHAVE_LAPACK", "-DHAVE_S4_ACCEL",
              "-D_USE_MATH_DEFINES", "-Dstrcasecmp=_stricmp",
              "-I" + str(args.source / "S4"), "-I" + str(args.source / "S4/kiss_fft"),
              "-I" + str(args.python_home / "include")]
    if args.cuda_headers:
        common += ["-DS4_USE_CUDA", "-I" + str(args.cuda_headers / "nvidia/cublas/include"),
                   "-I" + str(args.cuda_headers / "nvidia/cuda_runtime/include")]
    if args.cuda_nvcc_headers:
        common += ["-I" + str(args.cuda_nvcc_headers / "nvidia/cuda_nvcc/include")]
    if args.cuda_eigen_headers:
        common += ["-DHAVE_S4_CUDA_EIGEN"]

    def compile_one(source):
        cpp = source.endswith(".cpp")
        obj = args.output / (source.replace("/", "_") + ".obj")
        command = [args.zig, "c++" if cpp else "cc", *common]
        if source == "S4/cuda_eigensolver.cpp" and args.cuda_eigen_headers:
            # New cuSOLVER headers must precede the optional older cuBLASXt
            # headers. Only this translation unit needs the newer CUDA ABI.
            command = [args.zig, "c++", "-DS4_USE_CUDA_EIGEN",
                       *["-I" + str(root) for root in args.cuda_eigen_headers], *common]
        if cpp:
            command += ["-std=c++11", "-I" + str(args.source / "S4/RNP")]
        else:
            command += ["-std=c99"]
        command += ["-c", args.source / source, "-o", obj]
        run(command)
        print("Compiled", source, flush=True)
        return obj

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        objects = list(pool.map(compile_one, sources))
    extension = args.output / "S4.cp312-win_amd64.pyd"
    run([args.zig, "c++", "-target", "x86_64-windows-gnu", "-shared", "-O3",
         *objects, mkl_lib, args.python_home / "libs/python312.lib", "-o", extension])
    package = args.output / "pcs_s4_runtime"
    package.mkdir(exist_ok=True)
    shutil.copy2(extension, package / extension.name)
    for name in ("s4_runtime.py", "s4_parallel.py"):
        shutil.copy2(args.source / "python" / name, package / name)
    manifest = {
        "compiler": run([args.zig, "version"]).strip(), "flags": common,
        "python_home": str(args.python_home), "mkl_dll": str(args.mkl_dll),
        "cuda": bool(args.cuda_headers),
        "cuda_eigen_headers": [str(root) for root in args.cuda_eigen_headers],
        "binary_sha256": hashlib.sha256(extension.read_bytes()).hexdigest(),
        "sources": {str(path.relative_to(args.source)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (args.source / "S4").rglob("*")
                    if path.is_file() and path.suffix in {".c", ".cpp", ".h"}},
    }
    (args.output / "build_manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Built", extension)
    if args.tests:
        test_object = compile_one("tests/test_field_cache.cpp")
        test_program = args.output / "test_field_cache.exe"
        run([args.zig, "c++", "-target", "x86_64-windows-gnu", "-O3",
             *[obj for obj in objects if obj.name != "S4_main_python.c.obj"],
             test_object, mkl_lib, "-o", test_program])
        env["PATH"] = str(args.mkl_dll.parent) + os.pathsep + env.get("PATH", "")
        env["MKL_NUM_THREADS"] = "1"
        print(run([test_program]))


if __name__ == "__main__":
    main()
