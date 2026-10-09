# Optimized S4 for Python

This is a separate, optimized copy of S4 1.1.1. It does not modify the source
ZIP. It targets independent parameter sweeps and dense complex linear algebra.

## What changed

- All double-complex matrix products now use LP64 BLAS. Eigenproblems and
  linear solves use LAPACK. On this PC the supplied build uses multithreaded MKL.
- An optional cuBLASXt backend offloads sufficiently large matrix products to
  one CUDA GPU. If loading or a calculation fails, it falls back to CPU BLAS.
- `s4_parallel.parallel_map` runs independent simulations in spawn-safe worker
  processes with explicit CPU and GPU resource limits.
- The obsolete Python `SolveInParallel` no longer silently does nothing; it
  points callers to `parallel_map`.
- Repaired the stale Python/core material and layer API, Python 3 string access,
  frequency and material cache invalidation, and unsafe shallow cloning.
- Added numerical and process tests plus a repeatable benchmark.

## Ready-to-use build on this PC

The ready build is in `build/python` for the installed Anaconda Python 3.12.
Configure native libraries before importing S4:

```python
from s4_runtime import configure
configure(threads=1)  # for process sweeps
import S4
print(S4.AccelerationInfo())
```

Run the multiprocessing example from PowerShell:

```powershell
$s4 = 'C:\path\to\S4-source'
$env:PYTHONPATH = "$s4\build\python"
& 'C:\path\to\python.exe' "$s4\examples\parallel_sweep.py" --workers 4
```

For your 4-core Xeon, begin with `workers=4, threads_per_worker=1`. For one very
large simulation instead, try `workers=1, threads_per_worker=4`. Never set both
to four; oversubscribing 16 BLAS threads onto four cores is usually slower.

Define worker functions at the top level, import S4 inside them, pass plain
parameters (not S4 objects), and call `parallel_map` under the main guard:

```python
from s4_parallel import parallel_map

def simulate(parameter):
    import S4
    # Construct and solve a fresh S4 simulation here.
    return parameter

if __name__ == '__main__':
    results = parallel_map(simulate, parameters, workers=4,
                           threads_per_worker=1)
```

## GPU and hybrid mode

The Quadro P400 is Pascal compute capability 6.1 and has only 2 GB dedicated
memory. This build dynamically loads MATLAB R2020b's CUDA 10 cuBLAS on this PC.
It does not depend on MATLAB APIs. `s4_runtime.configure` finds that DLL without
permanently changing PATH.

```python
results = parallel_map(simulate, parameters, workers=4,
                       threads_per_worker=1, gpu=True,
                       gpu_device=0, gpu_min_n=1024)
```

Although Windows Task Manager calls the card "GPU 1", it is CUDA device `0`
because it is the only CUDA device reported by `nvidia-smi`.

`gpu=True` makes one GPU-designated process and three CPU-only processes. Only
large ZGEMM operations go to the GPU; eigenproblems remain on the CPU. Matrices
are kept in host memory and cuBLASXt tiles transfers, which avoids assuming that
Windows' shared-GPU figure is fast CUDA memory. The default `gpu_min_n=1024`
avoids costly transfers for small matrices. For diagnostic testing only, lower
it and inspect `S4.AccelerationInfo()` in each worker result.

## Measured results

Xeon E-2224G (4 cores), Quadro P400, 12 independent patterned simulations,
requested 101 basis terms, median of two end-to-end runs including pool startup:

| Mode | Seconds | Relative to reference |
|---|---:|---:|
| Repaired reference/internal math | 3.438 | 1.00x |
| Optimized CPU, 1 process x 1 thread | 1.328 | 2.59x |
| Optimized CPU, 1 process x 4 threads | 1.989 | 1.73x |
| Optimized CPU, 4 processes x 1 thread | **0.809** | **4.25x** |
| Forced GPU, 1 process (`gpu_min_n=1`) | 1.799 | 1.91x |
| Forced hybrid, 1 GPU + 3 CPU processes | 1.133 | 3.03x |

Maximum R/T disagreement was below `8e-14`. The forced-GPU result confirms that
the backend works, but not that it is beneficial: the P400's double-precision
rate and PCIe transfers lose on this workload. Keep the default threshold and
benchmark a representative large job before enabling GPU in production. Raw
reports are `../../benchmark-reference-101.json` and `../../benchmark-101.json`.

## Rebuild

The tested helper uses portable LLVM-MinGW and compiles source files on four
cores. It expects an LP64 BLAS/LAPACK DLL with Fortran symbols (the installed
Anaconda MKL meets that requirement). CUDA is optional and must be version 12.x
or older for Pascal:

```powershell
python tools/build_windows.py --compiler C:\path\to\llvm-mingw\bin\clang.exe --native
python tools/build_windows.py --compiler C:\path\to\llvm-mingw\bin\clang.exe `
  --cuda-include 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\include' --native
```

Linux/macOS builds can use CMake with `S4_REFERENCE`, `S4_NATIVE`, and
`S4_ENABLE_CUDA` options. Use an LP64 BLAS; S4's integer ABI is not ILP64.

## Verification

```powershell
$env:PYTHONPATH = "$s4\build\python"
python tests/test_parallel.py
python tests/test_physics.py
python tools/benchmark.py --basis 101 --points 12 --repeat 2
```

Tests cover process ordering/limits/error propagation, GPU/CPU worker lanes,
energy conservation, analytic Fresnel reflection, repeated-frequency cache
correctness, material invalidation, clone ownership, and the legacy no-op.
