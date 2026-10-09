# Optical Design Studio 1.3.2

## Windows x64 portable release

Download **OpticalDesignStudio-Portable-1.3.2-Windows-x64.zip**, extract the complete folder, and run **Optical Design Studio.exe**. Keep **OpticalDesignBackend.exe**, **_internal**, and the supplied documents together. The portable application includes its runtime; no separate Python installation or installer is required.

Data defaults to **User Data** beside the application. **Settings → Data storage** lets you select a different data location for the next launch; it does not move existing data. Close the application before upgrading and preserve **User Data**, any custom data directory, and **portable_settings.json**. See the release's **START_HERE.md** for startup and upgrade instructions.

The portable package is unsigned. Verify the archive against **SHA256SUMS.txt** and follow your organization's software policy. After publication, supported installations can check the configured public release channel through **Help → Updates**. **Help → About** shows the running version. This release supplies portable and corresponding source archives, with dependency notices and the public Silicon tutorial; private user libraries and credentials are excluded.

Detailed S4 scans stream exact results to indexed storage and keep plotting and sample selection bounded. Spectrum and electric fields share each wavelength solve; repeated layers reuse identical modes, and field planes use a validated Fourier sampler with a scalar fallback. These changes preserve the selected Fourier basis and sample coordinates. See **DESKTOP_GUIDE.md → Detailed scans** for performance and convergence guidance.

## Native Qt desktop

The application has seven top-level pages:

| Page | Use it for |
| --- | --- |
| Structure | Build the applied layer stack, lattice, holes, and material regions. |
| Materials | Inspect, import, assign, and save optical materials. |
| Simulation | Run S4 RCWA, MEEP FDTD, or Δn sweeps; open Fields and Saved results in its nested tabs. |
| Simulation Sweep | Explore bounded designs or search a target wavelength. |
| AI Search | Train models, propose candidates, and verify them with the solver. |
| Settings | Set appearance, data storage, performance, and add-ons. |
| Help | Read illustrated guides, load the Silicon example, and inspect actual saved results. |

Every calculation uses the same applied Structure. In Structure, choose a layer by name in the **Layer** dropdown or the stack. Use **Apply layer**, **Apply lattice**, and **Apply pattern** to commit edits; **Advanced editing…** provides layer renaming and the complete region/repeat tools. Run and Stop remain in the bottom bar. Background calculations report progress and support cancellation.

Choose **B Light**, **B Dark**, **Glass Light**, or **Glass Dark** through **Settings → Appearance** or **Menu → Appearance**. Each look has customizable colors and a real preview of the applied structure. Layer colors and material preview opacity are saved with projects and do not change optical constants or solver inputs.

Glass looks use Windows Desktop Acrylic to blur the actual desktop behind the window while controls and scientific data remain sharp. It requires Windows 11 build 22621 or later. Windows transparency, accessibility, power, or remote-session settings can substitute a solid backdrop; unsupported desktops and offscreen captures use a solid fallback. B looks are opaque. Maximized and fullscreen windows use the same theme with an opaque background to keep painting stable; restoring the window enables Acrylic again.

Live 2D scientific plots use native Qt/PyQtGraph items. Geometry and saved 3D fields use native Qt rendering. Fit, pan, zoom, copy, sample readout, and publication exports are available; Matplotlib remains the offline publication-export path. Graphs keep complete saved samples, and power percentages are display formatting while raw R/T/A values remain fractions.

**Materials** has searchable Project / Library / All cards, authentic source metadata, original sample tables, evaluated n/k curves, display colors, and editable Notes. Linear interpolation is the default. **Linear (in log k)** requires strictly positive k samples and is used by the actual S4 and MEEP material evaluation; n remains linear. Source attribution stays separate from Notes in saved presets and portable projects.

**Help** includes the real saved Silicon/SiO₂ air-hole calculation, raw spectrum and field CSVs, calculation inputs, and provenance. The tutorial's constant refractive indices are explicit approximations. See [UI_GUIDE.md](UI_GUIDE.md) for the quick workflow and [DESKTOP_GUIDE.md](DESKTOP_GUIDE.md) for setup, plots, saved results, and scientific conventions.

**Simulation Sweep → Explore designs** offers Exhaustive grid, ML assisted, and Hybrid verified searches, with resumable JSON histories and higher-resolution S4 checks. See [ML_SEARCH_GUIDE.md](ML_SEARCH_GUIDE.md) for optional dependencies, budgets, result interpretation, and validation.

## Run from source

Use a 64-bit Python 3.12 environment with an S4 native extension built for the same platform and Python version. Keep **pcs_s4_runtime** beside the application source. The corresponding native source is supplied with the source release. Do not substitute an unrelated S4 package.

For an existing compatible environment:

```powershell
python -m pip install --constraint constraints.txt -r requirements.txt
python qt_app.py
```

For the supplied Conda environment specification:

```powershell
conda env create -f environment.yml
conda activate s4_updated
python qt_app.py
```

**launch_qt_gui.cmd** and **launch_peak_gui.cmd** launch the native desktop on Windows. Set **S4_PYTHON** to the intended interpreter when using a launcher. **install_desktop_dependencies.cmd** installs the pinned GUI dependencies into an existing scientific environment; optional calculation runtimes have their own setup requirements.

On Linux, follow `bash setup_linux.sh` to build the native S4 extension and install the documented dependencies, then use `bash launch_qt_gui.sh`. A Windows native extension cannot run on Linux. Native Linux desktop execution has not been tested on the development Windows host. See [DESKTOP_GUIDE.md](DESKTOP_GUIDE.md) for details.

Legacy saved project, material, spectrum, and field formats remain readable in the native desktop. `app.py` supplies shared application/backend code; `qt_app.py` is the desktop entry point.

## Performance settings

| Setting | Meaning |
| --- | --- |
| CPU only | Native CPU execution; default compute mode |
| CPU + GPU | One GPU-designated worker, remaining workers on CPU |
| GPU-assisted (one worker) | One process using GPU products and CPU eigensolvers |
| Worker processes | 0 = all logical CPUs divided by math threads per worker |
| Math threads per worker | MKL/OpenMP/BLAS thread limit; default 1 |
| Points per batch | Scheduling overhead versus load balancing |
| CUDA device index | Native CUDA device index; verify with the runtime diagnostic |
| Minimum GPU matrix dimension | All three GEMM dimensions must meet this threshold |
| GPU tile size | cuBLASXt tile size, not a hard VRAM limit |
| Require successful GPU work | Fail if no GPU products finish or GPU failures occur |
| Timeout | Maximum native-job duration, followed by worker cleanup |

Workers x threads must not exceed the CPU count. Each process owns its own S4
structure; memory use grows with basis size, layer count, and worker count.
Reduce workers for large models or to keep the desktop responsive.

Only matrix multiplication is GPU-accelerated. Eigensolvers and other S4
operations still use the CPU, including in GPU-assisted mode. A busy GPU is not
necessarily faster. Windows shared GPU memory is not an equivalent pool of dedicated device memory.

The default GPU threshold is 1024, leaving small products on the CPU.
To prove offload, use **Settings → Check selected runtime**, which temporarily sets the
threshold to 1 for its tiny test without changing the saved controls. For a
normal simulation you can set threshold 1 yourself and compare timings.
Progress and downloadable diagnostics include actual CPU/GPU call counters,
GPU failures, effective worker/thread counts, and runtime status.

## Recorded solver reference benchmark

301 wavelengths (1300-1600 nm), requested basis 101, patterned absorptive film;
Xeon E-2224G, four cores, Quadro P400. Timings include worker startup and native
computation but exclude GUI plotting.

| Mode | Time | Maximum absolute difference vs serial |
| --- | ---: | ---: |
| CPU serial | 18.406 s | 0 |
| CPU all four cores | 5.828 s | 0 |
| One worker, four MKL threads | 13.079 s | 2.13e-13 |
| Four workers, CPU + P400, threshold 1 | 7.453 s | 1.85e-13 |

All-core multiprocessing was 3.16x faster than serial. Forced P400 offload
completed 200 GPU products with zero failures but was slower than CPU-only
for this workload. CPU-only is therefore the default. These are not guaranteed
speedups for other geometries/basis sizes.

    python tests\benchmark.py --gpu --output benchmark_results.json

## Numerical compatibility

Stored geometry is in micrometers; the guided Structure form converts between
nm and µm. Wavelengths are in nanometers. Rectangle sizes are
full width/height; circle/ellipse sizes are radii. Pattern angles are degrees.
Optical tables require explicit nm or um units. Linear interpolation is the default; the optional Linear (in log k) policy requires strictly positive k values and keeps n linear. Both policies clamp outside the supplied range, with a warning. New project JSONs embed their optical tables; legacy projects
may still need the original upload unless restored from a saved simulation job.

Each worker reuses its geometry but updates frequency, excitation, and dispersive
materials at every point. Results are sorted back into sweep order. Python's
mixed-polarization convention is mapped to match the original C++ GUI's s+p
basis. Dispersion in the incident medium also refreshes the excitation.

R/T/A use real time-averaged power flux. Raw results and CSVs retain fractions; desktop power graphs display percentages.
The code does not manufacture peaks or smooth failed points. Resonances depend
on geometry, material data, basis convergence, and sampling resolution.
At exact diffraction-order cutoffs S4 may become singular; nonfinite results
are reported as errors instead of substituted or silently plotted.

## Tests and outputs

    set S4_TEST_GPU=1
    python -m unittest discover -s tests -v

The independent C++ adapter comparison covers
all three shapes, s/p/mixed polarization, and dispersive material updates.
See TEST_REPORT.md and benchmark_results.json for verification details.

Stop requests cancellation of the active calculation in the desktop session.
Timeouts and errors clean up workers. Only one native job runs at a time.
Every run/project export gets its own folder under runs, so CSV and JSON
downloads do not overwrite other sessions. This folder retains simulation
inputs, optical-table snapshots, outputs and error logs locally.

## GPU libraries

GPU execution needs compatible NVIDIA hardware, its driver, and a compatible cuBLAS runtime. The Windows portable payload includes its selected runtime files and their NVIDIA notices; source installations must provide the required runtime. A display driver alone does not supply cuBLAS.
Advanced users can set S4_CUBLAS_LIBRARY to the full cublas64_*.dll path and
S4_DLL_DIRS to its dependency directories. Test the backend before a long run.

In **Settings**, select **CPU + GPU** or **GPU-assisted (one worker)** and click
**Check selected runtime**. The check runs a patterned S4 calculation with a
matrix threshold of 1 and reports actual completed GPU products; detecting a
display adapter alone is not counted as a successful test. Your normal run
threshold remains unchanged. The default threshold of 1024 leaves many small
Fourier-basis calculations entirely on CPU. **Use GPU for small matrices** sets
it to 1 for subsequent spectra and field solves; compare timings because small
products can be faster on CPU. **Require GPU work to succeed** rejects a run
whose GPU work failed or whose threshold prevented any GPU products.

Electric-field calculations now honor the same compute mode and save native
CPU/GPU counters in `field_diagnostics.json` alongside the raw field samples.
Field-map completion also displays these counters. Only eligible S4 matrix
products use cuBLAS; eigensolvers, field processing, and the scikit-learn ML
surrogate remain on CPU. Brief GPU products may not appear in a sampled GPU
utilization graph, so use the native product counters as the execution record.

Linux setup builds CPU support by default. To enable GPU matrix products, install
a compatible CUDA toolkit and run `bash setup_linux.sh --cuda` (or rebuild an
existing environment with `.venv/bin/python platform_setup.py --cuda`). The
bundled native source supports CUDA 10/11/12; use a toolkit compatible with your
GPU and driver. GPU-enabled Linux builds still need cuBLAS available at runtime,
optionally through `S4_CUBLAS_LIBRARY=/full/path/to/libcublas.so.12`.

## Package contents and licensing

qt_app.py is the native desktop entry point; app.py supplies shared application code; backend.py manages workers; model.py validates inputs. bootstrap.py sets per-process thread limits and DLL paths. pcs_s4_runtime contains the native wrapper/runtime. The release source archive includes matching native S4 source, build instructions, and its GPL license. THIRD_PARTY_LICENSES retains dependency notices, including PyQtGraph and Colorama. Existing user files are separate from application payloads.

The supplied binary targets this Windows x64/Python 3.12 machine. Rebuild from
source for a different OS, Python ABI, or unsupported CPU.

Use the release SHA256SUMS.txt and payload manifest for the exact distributed-file checksums.

## Peak-search update (2026-09-08)

The source GUI includes **Simulation Sweep → Explore designs** for manual design
bounds, weak-peak detection, adaptive wavelength refinement, >99% absorption
filtering, best-match design reports, and Q-estimate ranking. Start the updated
source using `launch_peak_gui.cmd`; use the 1.3.2 portable package for the current interface.
See [PEAK_SEARCH_GUIDE.md](PEAK_SEARCH_GUIDE.md) for controls, result files,
validation, and the finite-grid / spectral-Q limitations.

## Persistent data and custom materials

The updated source GUI includes **Simulation → Saved results** for browsing existing and new runs,
viewing saved spectra, restoring original or optimized designs, and continuing
saved ML histories. New runs save completed worker batches as well as final
results. The **Materials** tab can save user-entered n/k, permittivity or uploaded
wavelength-dependent tables as reusable, dated material presets.

Use **Simulation → Saved results → Back up, share or import a library →
Create whole-library backup** with application source included to share
the code, results, material library and optical tables together. Importing into
another updated installation merges data without overwriting its program.
See [DATA_LIBRARY_GUIDE.md](DATA_LIBRARY_GUIDE.md) for the complete workflow,
storage folders, limits and setup requirements. Restart using
`launch_peak_gui.cmd`; older prebuilt executables retain their own interface.

## Target-wavelength search, electric fields and Linux

**Simulation Sweep → Target wavelength** searches for >99% absorption and the highest
verified spectral Q found inside the user target tolerance (default ±5 nm).
Enter one air-hole shape and min/max size per PCS layer, a minimum Q, and optional
lattice/thickness bounds. Compatible saved spectra and sampled electric-field
data inform ML proposals. **Simulation → Fields → Current structure** displays and saves XY/XZ maps,
complex field components and concentration features from native S4.

Windows continues to use `launch_peak_gui.cmd`. Linux uses `bash setup_linux.sh`
then `bash launch_peak_gui.sh`, with Python 3.12, a compiler, CMake and LP64
OpenBLAS development packages. Linux builds the bundled S4 source for its own
platform; it cannot use the Windows binary or Windows ML wheels. Native Linux
execution has not been tested on the development Windows machine.
See [TARGET_DESIGN_GUIDE.md](TARGET_DESIGN_GUIDE.md) for setup, search constraints,
training-data compatibility, field interpretation and validation limits.

## Field redistribution in the target ML model

Target searches now learn from field confinement, periodic centroids/spread,
component fractions, loss distribution, energy flow and complex-field overlap.
Fixed-target and selected-resonance measurements train separate auxiliary models;
measured absorption, Q and convergence checks still determine recommendations.
Raw complex E/H samples, portable descriptors and proposal diagnostics are saved
for later reuse. **Simulation → Fields → Compare saved fields** compares saved designs on a shared color scale,
shows complete conditions and field metrics, and exports comparisons to Saved results.
See [FIELD_TRACKING_GUIDE.md](FIELD_TRACKING_GUIDE.md) for the workflow.

Glass opacity accepts the full 0–100% range. Lower values clear the workspace and panel tint while labels and input controls remain readable. Saved maximized or fullscreen windows establish a normal native paint before restoring their saved state, preserving visible startup content.
