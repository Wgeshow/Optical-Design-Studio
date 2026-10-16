# Optimized simulation solvers

In **Settings → Performance**, select **S4 native (recommended)** for normal
CPU scans. **Use exact mirror symmetry** is enabled by default.
Eligible geometries are solved in smaller independent sectors; all Fourier
orders and complete 3D electric and magnetic fields are reconstructed. Other
geometries use the general S4 solver automatically.

Select **GPU scattering (eigenfree)** to solve wavelength batches
with the CUDA Maxwell scattering backend. The portable performance build
includes CuPy 14.2.0, NumPy 2.2.6 and its CUDA 13 runtime. A compatible NVIDIA
driver is required. The default spectrum batch is 32 wavelengths. Separate
field jobs process saved wavelengths in a persistent worker. **Check selected runtime** verifies a real
GPU solve. Solver selection, symmetry and batch size are saved with projects.

The GPU backend supports scalar materials with uniform, lossless exterior
layers, positive frequencies and one incident side. Use S4 native for phase
scans or unsupported port configurations. Failed or singular points produce
an explicit error; no wavelength interpolation is substituted. Exact
diffraction cutoffs can be singular in both backends.

**Run spectrum** calculates R/T/A without running an electric-field scan,
including when an older project contains saved field-sampling settings.
The Simulation tab's **Electric fields** section runs a separate job. Leave
**Single wavelength** on to enter a wavelength or select the exact maximum
or minimum of R, T or A from a matching completed spectrum. Ties use the first
finite saved sample. Changed structures/materials/basis/excitation require a
new spectrum or restoring its saved setup. Turning the toggle off explicitly
runs fields for all saved spectrum samples, including their saved angles.

Both the separate Simulation field job and standalone **Fields** jobs use the
selected CPU/GPU backend. All complex Ex/Ey/Ez/Hx/Hy/Hz values, coordinates,
contours and full 3D arrays are saved. **View saved electric fields** opens the
3D results view; XY/XZ maps remain in **Electric fields**. The former 80-sample
and 40-depth limits are removed from both menus and field validation; input
controls accept positive sample counts of at least three up to the Qt integer
representation limit. Field runs appear
in Recent runs and the saved library. Spectrum CSV export continues to use
the spectrum result after a separate field run.

Measure phase is saved as soon as it is toggled and retained when Run spectrum
refreshes the sweep settings. Both native CPU and eigenfree CUDA scans save
specular reflection/transmission phase in phase.csv and display it in the Phase
tab. The CUDA path uses cached physical exterior H amplitudes from the resident
batch; phase measurement does not request electric-field volumes.

Resizing changes layout density without reapplying the global stylesheet or
rebuilding hidden plots. Hidden curves retain clipping/downsampling, and
field maps are created only when their results tab is opened. Interface zoom
and theme controls still apply the chosen appearance explicitly.

Exact exterior diffraction thresholds use bounded Maxwell radiation columns:
with J the magnetic projector onto transverse k, H=(I-J)+(q/omega)J and
rotated E=(q/(epsilon*omega))(I-J)+J. The outgoing boundary conditions therefore
remain finite at q=0. The CPU path uses the same exported S4 Fourier operators
with the eigenfree NumPy solver only at a threshold; CUDA wavelength batches
use these regular ports directly. No wavelength offset, artificial absorption,
small replacement q, or interpolation is used. CPU cutoff results must pass
tangential interface residual checks. Full complex 3D fields and specular phase
are available at these wavelengths too. Nonzero material absorption is retained;
the lossless q-squared cancellation guard is bounded by floating-point roundoff.

Spectrum-only scans retain any still-unavailable exact S4 point as blank R/T/A in
results.csv and NULL in SQLite, with its reason in unavailable_points.csv.
The plot has a gap there; extrema ignore unavailable samples. Valid wavelengths
are never shifted or interpolated. The scan completes with a visible warning;
an entirely unavailable spectrum, a malformed geometry, or a runtime failure
still fails. Standalone fields and design-search calculations remain strict for
unresolved errors, and use the exact cutoff solve for eligible thresholds.
Explicit whole-spectrum field jobs use the finite saved wavelengths and report
how many unavailable spectrum points were excluded.

Windows maximize/restore commands and native caption clicks defer Qt state
changes until after the Win32 callback returns. Layout adaptation touches only
the visible page, and backdrop attributes are not rewritten on every resize.
Glass uses live Acrylic blur with a neutral tint and fine grain rather than
fully clear desktop pixels. Opaque controls stay crisp. Unavailable composition
uses an opaque fallback; no Windows transparency preference is changed.

In the validated 900–1200 nm / 0.01 nm basis-128 benchmark (121 retained orders),
the previous solver averaged 294.33 seconds, CPU symmetry 57.29 seconds and
GPU symmetry 107.77 seconds. These are spectrum-only times on the benchmark
workstation, averaged over two runs; GPU cache warmup differed between runs.
The exact 1155.00 nm cutoff was unavailable in the reference and excluded.
Maximum R/T/A difference was 2.60e-12. All 148,225,000 voxels in the separate
1050 nm / 1 nm field comparison passed; maximum complex E/H difference was
2.14e-11. Full volumes at every wavelength were not part of that timed scan.
