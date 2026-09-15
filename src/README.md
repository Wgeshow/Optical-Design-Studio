# Optical Design Studio

## Portable ZIP (1.0.4)

Download OpticalDesignStudio-Portable-1.0.4-Windows-x64.zip, extract the entire
folder and run Optical Design Studio.exe. No installer is needed. Data defaults
to User Data beside the application. Settings → Data output folder lets you
browse for another location, save the selection, and restart to use it. Existing
data is retained in its previous folder; select it to reopen your saved work.
Keep User Data and portable_settings.json when upgrading to a newer ZIP.

About supports verified public ZIP downloads without a key. Earlier versions
need this ZIP downloaded once manually because they only recognize installers.
The older installer instructions below apply to releases through 1.0.3.

## Windows installer

Run **OpticalDesignStudio-Setup-1.0.3-Windows-x64.exe**, choose an installation
folder, and complete the setup wizard. The installer and application are native
64-bit. Python, PyQt6, S4, machine-learning dependencies, and GPU runtime libraries
are included for offline installation. Public packages start with an empty
saved-work library and do not include the development machine's research data.
No separate Python, Conda, or CUDA Toolkit installation is needed. GPU use
requires compatible NVIDIA hardware and its driver.

The installed **Optical Design Studio.exe** uses the supplied optical-layer icon.
Saved data lives in `%LOCALAPPDATA%/Optical Design Studio/User Data` and survives
updates and uninstalling. The program's installation folder can be selected
independently. See the installed **INSTALLATION.md** for instructions, and
**_internal/source/packaging/BUILDING.md** for rebuilding the installer.

Version 1.0.3 makes **About → Check for updates** work without a GitHub account,
access key, or sign-in. It reads the public installer repository and verifies
update downloads. Open and Save are in the **File**
menu, with **Ctrl+O / Ctrl+S**; duplicate title-bar buttons were removed. View
provides appearance choices. You choose when to run the downloaded installer.
The development repository remains private. See [UPDATES.md](UPDATES.md).

## Native PyQt6 desktop

**launch_peak_gui.cmd** and **launch_qt_gui.cmd** now open the native desktop.
Choose **Dark mode** or **Light mode** at the bottom of the navigation sidebar;
the choice is remembered and applies to plots, tables, and editors.

The desktop includes eight workspaces: Structure, Materials, Simulate,
Optimize, Fields, Saved work, Settings, and About. Every calculation uses the same
applied Structure. Background calculations support progress and cancellation,
and the existing library retains projects, optical constants, spectra, search
history, and electric-field maps. The structure and material editors have
native interactive plots, named selections, and reversible structure edits.

Run **install_desktop_dependencies.cmd** once for an existing Windows source
installation. On Linux, install `requirements-linux.txt` and run
`bash launch_qt_gui.sh`. See [DESKTOP_GUIDE.md](DESKTOP_GUIDE.md) for setup and
the complete workflow, and [DESKTOP_TEST_REPORT.md](DESKTOP_TEST_REPORT.md) for
validation. Native Linux execution has not been tested on this Windows host.

The previous browser interface is available explicitly through
**launch_web_gui.cmd** or **bash launch_web_gui.sh**. The legacy browser EXE
described below predates the native desktop; use the current installer or source launcher.

## Guided interface

The source GUI is organized into **Structure, Materials, Simulate, Optimize,
Fields, Saved work, and Settings**. Build multilayer stacks with named material
dropdowns, duplicate layers or repeat whole blocks, and edit holes with
shape-specific dimensions. See [UI_GUIDE.md](UI_GUIDE.md) for the complete quick
start, including Apply controls, units, material imports and saved results.

The Structure tab includes an interactive geometry preview of the layer stack
and patterned unit cells. It updates after applied edits and project loads.
Existing source installations should run the requirements installation command
below once to add Plotly, which provides zoom and hover in this preview.

## Machine-learning search update (2026-09-09)

Start the current source with **launch_qt_gui.cmd** and select **Optimize →
Explore designs**. It offers Exhaustive grid, ML assisted and Hybrid verified
(default), with resumable JSON histories and higher-resolution S4 checks.
See [ML_SEARCH_GUIDE.md](ML_SEARCH_GUIDE.md) for controls, installed optional
dependencies, budgets, result interpretation and validation. The current desktop
installer includes these tools; legacy browser executables predate this update.

This is the v1.1 GUI ported from its Linux-only runner to the updated Python S4
module. Existing project JSONs and the optical model are preserved. New project
files also save performance settings.

## Legacy browser executable

Download and extract the complete S4_Optical_GUI_Executable ZIP, then
double-click S4_Optical_GUI.exe. Keep its console window open while using the
browser; closing that console stops the local application. Do not move the EXE out of its folder:
the _internal and S4_Backend folders are required. No Anaconda activation or
Python installation is needed. The first launch can take longer while Windows
scans the bundled scientific libraries. The browser opens at
http://127.0.0.1:7860 and the service is bound to this computer only.

## Start in Anaconda

Use 64-bit Python 3.12 and MKL 2023.1. Keep pcs_s4_runtime beside app.py.

    conda activate s4_updated
    cd C:\path\to\S4_Optical_GUI_Accelerated
    python -m pip install --constraint constraints.txt -r requirements.txt
    python qt_app.py

For a new installation:

    conda env create -f environment.yml
    conda activate s4_updated
    python qt_app.py

The native desktop opens its own window. To use the older browser interface,
run `python app.py` or `launch_web_gui.cmd`; it serves http://127.0.0.1:7860.
Its `--port` and `--no-browser` options apply only to the browser launcher.

The server is local-only; public sharing and Gradio analytics are disabled.
Do not pip install a different S4: the GUI loads the supplied corrected module.

## Performance settings

| Setting | Meaning |
| --- | --- |
| CPU only | All-core CPU execution; recommended on this machine |
| CPU + GPU | One GPU-designated worker, remaining workers on CPU |
| GPU-assisted (one worker) | One process using GPU products and CPU eigensolvers |
| Worker processes | 0 = all logical CPUs divided by math threads per worker |
| Math threads per worker | MKL/OpenMP/BLAS thread limit; default 1 |
| Points per batch | Scheduling overhead versus load balancing |
| CUDA device index | P400 = 0 on this PC, despite Windows calling it GPU 1 |
| Minimum GPU matrix dimension | All three GEMM dimensions must meet this threshold |
| GPU tile size | cuBLASXt tile size, not a hard VRAM limit |
| Require successful GPU work | Fail if no GPU products finish or GPU failures occur |
| Timeout | Maximum native-job duration, followed by worker cleanup |

Workers x threads must not exceed the CPU count. Each process owns its own S4
structure; memory use grows with basis size, layer count, and worker count.
Reduce workers for large models or to keep the desktop responsive.

Only matrix multiplication is GPU-accelerated. Eigensolvers and other S4
operations still use the CPU, including in GPU-assisted mode. A busy GPU is not
necessarily faster. The P400 has 2 GB dedicated memory; Windows shared GPU
memory is not an equivalent pool of device memory.

The default GPU threshold is 1024, leaving small products on the CPU.
To prove offload, use **Settings → Check selected runtime**, which temporarily sets the
threshold to 1 for its tiny test without changing the saved controls. For a
normal simulation you can set threshold 1 yourself and compare timings.
Progress and downloadable diagnostics include actual CPU/GPU call counters,
GPU failures, effective worker/thread counts, and runtime status.

## Measured on your computer

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
Optical tables require explicit nm or um units. They are linearly interpolated
with endpoint clamping outside the provided range, matching v1.1; clamping now
produces a warning. New project JSONs embed their optical tables; legacy projects
may still need the original upload unless restored from a saved simulation job.

Each worker reuses its geometry but updates frequency, excitation, and dispersive
materials at every point. Results are sorted back into sweep order. Python's
mixed-polarization convention is mapped to match the original C++ GUI's s+p
basis. Dispersion in the incident medium also refreshes the excitation.

R/T/A use real time-averaged power flux and are plotted as fractions, not percent.
The code does not manufacture peaks or smooth failed points. Resonances depend
on geometry, material data, basis convergence, and sampling resolution.
At exact diffraction-order cutoffs S4 may become singular; nonfinite results
are reported as errors instead of substituted or silently plotted.

## Tests and outputs

    set S4_TEST_GPU=1
    python -m unittest discover -s tests -v

With a local GUI running on port 7861:

    python tests\check_gui_api.py

Or pass its URL as an argument. The independent C++ adapter comparison covers
all three shapes, s/p/mixed polarization, and dispersive material updates.
See TEST_REPORT.md and benchmark_results.json for verification details.

Stop simulation / test cancels the active job in that browser session.
Timeouts and errors clean up workers. Only one native job runs at a time.
Every run/project export gets its own folder under runs, so CSV and JSON
downloads do not overwrite other sessions. This folder retains simulation
inputs, optical-table snapshots, outputs and error logs locally.

## GPU libraries

On this PC, the helper discovers compatible cuBLAS installed with MATLAB R2020b.
The package does not redistribute NVIDIA libraries. On another computer a
compatible cuBLAS runtime must be present; a display driver alone is not enough.
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

app.py is the GUI; backend.py manages workers; model.py validates inputs;
bootstrap.py sets per-process thread limits and DLL paths. pcs_s4_runtime
contains the tested module and helper files. S4-source contains the matching
modified source, build instructions, and GPL license. third-party-licenses
contains compiler-runtime notices. Existing user files are not overwritten.

The supplied binary targets this Windows x64/Python 3.12 machine. Rebuild from
source for a different OS, Python ABI, or unsupported CPU.

S4 binary SHA-256:
FEEBCCA5078672A6382BF0BD5C94F0014635F9C2C88E6427DE77F599D37FFEA1

## Peak-search update (2026-09-08)

The source GUI includes **Optimize → Explore designs** for manual design
bounds, weak-peak detection, adaptive wavelength refinement, >99% absorption
filtering, best-match design reports, and Q-estimate ranking. Start the updated
source using `launch_peak_gui.cmd`; existing packaged executables are unchanged.
See [PEAK_SEARCH_GUIDE.md](PEAK_SEARCH_GUIDE.md) for controls, result files,
validation, and the finite-grid / spectral-Q limitations.

## Persistent data and custom materials

The updated source GUI includes **Saved work → Results library** for browsing existing and new runs,
viewing saved spectra, restoring original or optimized designs, and continuing
saved ML histories. New runs save completed worker batches as well as final
results. The **Materials** tab can save user-entered n/k, permittivity or uploaded
wavelength-dependent tables as reusable, dated material presets.

Use **Saved work → Results library → Back up, share or import a library →
Create whole-library backup** with application source included to share
the code, results, material library and optical tables together. Importing into
another updated installation merges data without overwriting its program.
See [DATA_LIBRARY_GUIDE.md](DATA_LIBRARY_GUIDE.md) for the complete workflow,
storage folders, limits and setup requirements. Restart using
`launch_peak_gui.cmd`; old prebuilt executables are unchanged.

## Target-wavelength search, electric fields and Linux

**Optimize → Target wavelength** searches for >99% absorption and the highest
verified spectral Q found inside the user target tolerance (default ±5 nm).
Enter one air-hole shape and min/max size per PCS layer, a minimum Q, and optional
lattice/thickness bounds. Compatible saved spectra and sampled electric-field
data inform ML proposals. **Fields → Current structure** displays and saves XY/XZ maps,
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
for later reuse. **Fields → Compare saved fields** compares saved designs on a shared color scale,
shows complete conditions and field metrics, and exports comparisons to Saved work.
See [FIELD_TRACKING_GUIDE.md](FIELD_TRACKING_GUIDE.md) for the workflow.
