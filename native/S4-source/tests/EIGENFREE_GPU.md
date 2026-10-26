# Optional eigenfree GPU spectrum and field solver

`src/s4_eigenfree_gpu.py` implements a direct complex128 Fourier Maxwell solver
using the exact constitutive operators exported by `S4.GetEigenfreeOperators()`.
Every requested wavelength is solved independently. It uses neither wavelength
interpolation nor a patterned-layer eigendecomposition.

## Numerical method and fields

For `h=(Hx,Hy)` and `e=(-Ey,Ex)`, the first-order equations are
`h'=i Q e`, `e'=i P h`, where `P=kp/omega` and
`Q=omega*epsilon2-kk/omega`. A patterned homogeneous layer is divided until its
generator norm is at most0.5; degree8 Taylor polynomials in the squared operator
form the small transfer matrix. This is immediately converted to scattering,
then doubled using Redheffer composition. Thick growing transfer matrices are
never formed. Uniform scalar layers use analytic independent2x2 Fourier blocks.

The off-diagonal Maxwell generator has exact z-reversal symmetry, so homogeneous
slab doubling computes only its equal left/right R and T blocks. This does not
assume Hermitian matrices, reciprocity, or commuting P/Q. General interfaces and
heterogeneous stacks still use the full scattering composition.

The complete six-component E/H Fourier coefficients remain available at every
depth. Interior recovery joins the scattering networks on both sides of that
depth; longitudinal components use the full native inverse-permittivity operator.
Reverse cascades are generated lazily, and eight coefficient planes are cached.
The existing field pipeline can reconstruct any3D sampling grid from these
coefficients, with every original retained Fourier order included.

## Exact symmetry option

Symmetry reduction requires `mirror_eligible` from the native exact geometry
guard. The solver also checks Fourier mirror closure and numerical invariance
of every P/Q operator, both exterior admittances, and the incident excitation.
It retains every sector with a nonzero projected source, including arbitrarily
weak polarization. Failed guards keep the full matrix. Reduced solutions are
lifted back to the original physical Fourier basis for all field outputs.

For the centered benchmark at normal p incidence, the internal matrix reduces
from242 to61 while output still contains all121 retained orders. This is a
symmetry decomposition, not harmonic truncation.

## Application integration

The existing `backend.execute` routes to `src/eigenfree_scan.py` when performance
configuration contains:

```python
{
    'solver_backend': 'eigenfree-gpu',
    'eigenfree_symmetry': True,
    'eigenfree_batch_size': 32,
}
```

The ordinary CPU backend remains the default. The GPU coordinator uses bounded
wavelength batches and its `FieldView` exposes native-compatible coefficient and
point-field methods to the existing field sampler. Constant-material, exact
normal-incidence scans reuse constitutive operators while updating omega at
every requested wavelength. Dispersive/oblique scans request fresh operators.
CuPy and a compatible CUDA runtime are optional dependencies; ordinary CPU use
does not need them.

Direct API:

```python
from s4_eigenfree_gpu import solve_batch
solution = solve_batch([simulation.GetEigenfreeOperators()],
                       backend='cupy', symmetry=True)
rta = solution.rta()                            # [batch,3]
coeff = solution.coefficients(layer_index, z)   # [batch,nG,6]
fields = solution.fields(layer_index, z, xy)    # [batch,nPoints,6]
```

Coefficient order is Ex,Ey,Ez,Hx,Hy,Hz, matching native `GetFields` convention.
`port_amplitudes()` returns physical H amplitudes in columns incoming-top,
outgoing-top, outgoing-bottom, incoming-bottom. These are not interior modal
amplitudes. `diagnostics` reports actual solver dimension, retained order count,
symmetry guard outcome, invariance residual and doubling counts.

## Current restrictions

- Positive real frequency; uniform scalar exterior media.
- Both exterior reference-layer thicknesses must be exactly zero.
- R/T normalization requires lossless exteriors and one incident side.
- Exterior diffraction thresholds request native handling by raising an error.
  The generic coordinator currently reports this error; it does **not** silently
  fall back or interpolate. The900–1200nm benchmark preserves the known1155nm
  point as explicitly unavailable, consistent with the native baseline.
- Phase-measurement scans currently use the native backend.
- A failed symmetry proof falls back to the full eigenfree matrix. This differs
  from switching to the native eigensolver.

## Verified calibration

RTX4070TiSUPER; exact native121-order1050nm operators; complex128; two warm trials:

| Path | Batch | Solver dimension | ms/wavelength | max absolute R/T/A difference |
|---|---:|---:|---:|---:|
| Full eigenfree GPU |16|242|28.991|6.87e-13|
| Symmetry + eigenfree GPU |1|61|21.793|9.65e-14|
| Symmetry + eigenfree GPU |8|61|5.466|9.65e-14|
| Symmetry + eigenfree GPU |16|61|3.789|9.65e-14|
| Symmetry + eigenfree GPU |32|61|3.214|9.65e-14|
| Symmetry + eigenfree GPU |64|61|3.185|9.65e-14|

Batch32 is recommended: batch64 improved less than1% while cumulative allocator
pool reservations grew from809MB to1.71GB. These figures include prior batch-size
calibrations, not independent minimum-memory measurements. Invariance residual
was3.25e-16. Calibration repeats one wavelength; full-scan reports provide the
end-to-end performance comparison.

The focused tests in `src/tests/test_s4_eigenfree_gpu.py` check an independent
dense matrix-exponential/boundary solution for noncommuting complex operators,
all six coefficients, analytic quarter-wave reflection, thick-absorber PIM,
specialized/general doubling equivalence, exact weak-source preservation,
symmetry guards and cutoff detection. Independent native comparisons cover
oblique, tensor, absorbing, copied-layer and alternate-FMM cases.

Both full-matrix and symmetry-reduced GPU variants passed the independent
23-case suite (the known exact cutoff remains explicitly unavailable). Maximum
R/T/A absolute differences were3.85e-12 and4.75e-13, respectively; maximum
point-field absolute differences were5.00e-11 and1.57e-11.

The combined backend also passed a complete1050nm field-volume comparison:
250 depths x770 x770 cell-centered1nm samples,148,225,000 voxels and all
889,350,000 complex six-component values. Every value was finite and passed the
comparison. Maximum absolute difference was2.14e-11 (Hy), and the largest
component-relative L2 difference was4.65e-12 (Ez). All121 Fourier orders were
retained. This validates one full spatial volume, not dense volumes at every
wavelength. Evidence is in `symmetry-eigenfree-work/validation/`:
`physical_accuracy_summary.json`, `volume_gpu_symmetry_compare.json`, and the
small complete Fourier coefficient snapshots used for streamed reconstruction.

## Isolated Windows validation environment

The development environment is outside the production runtime:
`C:/codes/s4-performance-implementation/eigenfree-gpu-deps` contains CuPy14.2,
NumPy2.2.6, cuda-pathfinder1.8.3 and CUDA support packages. CuPy14 requires NumPy2;
add this directory before any NumPy import. CUDA13 libraries are under
`C:/codes/s4-performance-implementation/cuda-eigen-work/deps/nvidia/cu13`.

Set CUDA_PATH and DLL PATH in the launching shell **before** Python starts;
updating only `os.environ` after startup did not reliably update CUDA pathfinder's
CRT environment. Add both CUDA DLL directories via `os.add_dll_directory` too.

```powershell
$env:PYTHONPATH='C:/codes/s4-performance-implementation/eigenfree-gpu-deps;C:/codes/Optical-Design-Studio/src'
$env:CUDA_PATH='C:/codes/s4-performance-implementation/cuda-eigen-work/deps/nvidia/cu13'
$env:PATH='C:/codes/s4-performance-implementation/cuda-eigen-work/deps/nvidia/cu13/bin/x86_64;C:/codes/s4-performance-implementation/eigenfree-gpu-deps/nvidia/cu13/bin/x86_64;'+$env:PATH
$env:CUPY_CACHE_DIR='C:/codes/s4-performance-implementation/cuda-eigen-work/cupy-cache'
& C:/codes/ods-review-env/Scripts/python.exe C:/codes/s4-performance-implementation/cuda-eigen-work/benchmark_eigenfree.py --runtime C:/codes/s4-performance-implementation/symmetry-eigenfree-work/candidate-runtime-v3 --symmetry --batches 1,8,16,32,64 --trials 2
```

Use an existing writable TEMP/TMP directory if sandbox restrictions block the
default temporary directory. Calibration evidence is stored in
`cuda-eigen-work/eigenfree-symmetry-calibration.json` and
`cuda-eigen-work/eigenfree-final-full-calibration.json` under the artifact root.
