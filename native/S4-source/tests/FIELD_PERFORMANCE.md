# Native field coefficients and dielectric caching

`simulation.GetFieldCoefficientsMany(z_values)` returns a `bytes` object of
native-endian complex128 values. Interpret it as `[nz, actual_basis_count, 6]`
in C order; components are `Ex, Ey, Ez, Hx, Hy, Hz`. Obtain actual basis order
from `GetBasisSet()`. The returned coefficients are at in-plane origin zero;
multiply by each order's `exp(i*(kx*x+ky*y))` to evaluate at a point. The Bloch
phase is not included. Depths may be unsorted or repeated and use the same
interface-side selection as `GetFields`. The magnetic z sign follows
`GetFields`; the old `GetFieldsOnGrid` has the opposite Hz sign.

The bulk call shares one amplitude/field workspace across planes, skips FFTs
and nested Python tuples, and preserves an existing spectrum/layer solution.
It retains the GIL because simulation mutation is not thread-safe. Parallel
wavelength workers remain separate processes. The caller should use bounded
depth batches to control its reconstruction-buffer memory.

Patterned-layer dielectric matrices (including inverse and Fourier
factorization) are frequency-independent for fixed material values. They are
cached up to 128 MiB per simulation, and cleared on changes to material,
geometry, lattice, basis or numerical options. Modes and scattering amplitudes
are recomputed for every changed frequency. `ConserveMemory=True` disables the
matrix cache. `S4_DISABLE_EPSILON_CACHE=1` disables it for controlled A/B
measurements. `GetEpsilonCacheStats()` reports lifetime hits/misses and current
bytes. Dispersive material updates invalidate the matrices.

## Windows portable build

The ordinary CMake build remains supported. The portable helper additionally
supports a workspace-local compiler without installing Visual Studio. It
requires CPython 3.12 development headers and `python312.lib`, `pefile`, and an
existing LP64 MKL runtime. Download dependencies to a chosen build directory:

```powershell
python -m pip install --target C:\build\toolchain ziglang==0.13.0
python -m pip install --target C:\build\cuda-headers nvidia-cublas-cu11==11.11.3.6 nvidia-cuda-runtime-cu11==11.8.89
python -m pip install --target C:\build\cuda-nvcc nvidia-cuda-nvcc-cu11==11.8.89
```

From the S4 source directory:

```powershell
python tests\build_windows_portable.py --zig C:\build\toolchain\ziglang\zig.exe --mkl-dll C:\runtime\mkl_rt.2.dll --cuda-headers C:\build\cuda-headers --cuda-nvcc-headers C:\build\cuda-nvcc --output C:\build\native-runtime --tests
```

Omit the CUDA options for a CPU-only build. This compiles the existing optional
dynamically loaded cuBLASXt backend when CUDA headers are supplied; it does not
change the solver's GPU thresholds. The helper writes the extension and
`pcs_s4_runtime` wrappers plus a source/compiler/binary manifest. C++ support is
statically linked; the extension requires the Python and MKL runtime DLLs plus
Windows system DLLs. GPU use additionally needs the existing cuBLAS DLLs.

## Verification and timing

Set `PYTHONPATH` to the built extension directory, `S4_TEST_DLL_DIR` to the MKL
DLL directory, and `MKL_NUM_THREADS=1`, `OMP_NUM_THREADS=1`. Run:

```powershell
python tests\test_field_coefficients.py -v
python tests\benchmark_field_coefficients.py snapshot C:\build\candidate.npz
python tests\benchmark_field_coefficients.py benchmark C:\build\native-timings.json
```

Repeat the snapshot with `PYTHONPATH` pointing at the original extension, then
compare the snapshots using `benchmark_field_coefficients.py compare old.npz
candidate.npz`. Snapshots include spectra and all complex field components at
900, 1050 and 1200 nm, for bases 32, 64 and 128, including oblique, lossy,
anisotropic, skew-lattice, uniform, and copied-layer cases. Microbenchmarks
measure solver caching and extraction only: dense-grid reconstruction and
storage must be included in application end-to-end measurements separately.

Do not run competing CPU benchmarks at the same time. Lua option invalidation
is maintained in source but requires the separate Lua build to exercise.
