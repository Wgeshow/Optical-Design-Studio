# Target-wavelength design and electric fields

Use the updated source GUI, not an older prebuilt EXE. Windows: run
`launch_peak_gui.cmd`. Linux: see the setup section below.

## Target workflow

1. Define the material stack in **Structure**. In **Materials**, upload wavelength-dependent n/k
   tables or explicitly choose constant approximations. This defines the number
   and order of layers and the material choices; wavelength alone cannot define
   an arbitrary stack.
2. Open **Optimize → Target wavelength**. Enter the target wavelength, its allowed
   peak-center error (default **±5 nm**) and minimum Q.
3. Existing single air holes appear automatically at their current sizes. Choose
   a **PCS layer**, shape and min/max sizes, then **Add / update layer hole** to
   save search limits. Automatic ranges follow applied Structure edits; saved
   manual limits and removed ranges are preserved. **Reset hole ranges to current
   structure sizes** discards those limits and starts from the applied geometry.
   Existing hole positions, rotations and other material regions are retained.
   A selected layer without an air hole receives a new centered hole. For multiple
   air holes in one layer, use **Explore designs** and select the specific pattern.
   Circles use radius in X; ellipses use X/Y radii; rectangles
   use full X/Y widths. Dimensions are in µm. Each named layer must already exist
   as a finite layer in the structure.
4. Open **Also vary lattice spacing, layer thickness, or layer materials**.
   Choose what can change and its layer/region from dropdowns, enter a range
   or select allowed materials, then click **Add / update range**. Parameters
   without ranges retain their Structure values. Advanced tables remain available
   for existing bounds and bulk input.
5. Set the run budget and sampling controls if needed, then start the search.
   It returns design conditions, target-specific peak/Q results, a complete data
   ZIP, and field maps when a verified recommendation exists. **Use verified
   design in Structure** loads the resulting geometry and basis.

Only peaks with absorption **strictly above 99%**, centers inside the wavelength
tolerance, and resolved spectral Q at least equal to the requested minimum can
qualify. Absorption at the exact target wavelength is reported separately;
allowing a ±5 nm peak-center tolerance does not mean a very narrow resonance has
99% absorption throughout that interval.

The highest-Q qualifying leaders are rerun using 1.5× the Fourier basis and half
the initial wavelength spacing, followed by adaptive sampling. A recommendation
requires agreement within 0.001 absolute peak absorption, 5% relative Q, and a
peak shift no larger than the smaller of the target tolerance and twice the
original linewidth. Higher-resolution measurements replace earlier measurements
in the final table. A design with unresolved or asymmetric/overlapping linewidth
cannot qualify for this spectral-Q estimate. If no design qualifies, the GUI says
so and preserves the evaluated data.

The method reports the **highest verified Q found**, not a proof of a continuous
global maximum. Hole sizes are sampled on a finite grid (default 21 values across
each min/max interval). The initial spectral step and window remain important:
adaptive sampling cannot guarantee discovery of a peak never seen by the initial
grid. Use a wider window if the linewidth lies outside it and a smaller initial
step for narrow peaks. The default new-point budget is 200,000; the Settings
timeout covers the entire run. Finalist reruns are additional to the ML trial
budget.

Circle r/a must remain strictly below 0.6. The existing circle-separation check
also applies. Target searches require every hole shape's bounding extent to
leave a positive bridge to its periodic copy. These implement the stated
geometric restrictions; process-specific minimum features can be represented by
tighter user bounds. Layers not listed in the hole table retain their patterns.

## How saved data and electric fields inform ML

The search scans the local `runs/` collection for saved target-search histories,
existing ML histories, ordinary spectra, and grid-search spectra. It accepts only
compatible material data, fixed geometry, illumination, Fourier basis, current
design bounds and sufficient wavelength coverage. Objectives are recalculated
from the saved spectra for the current target/tolerance/minimum Q. Thus saved
data can be useful for a new target when its recorded spectrum covers the new
window. Incompatible and duplicate entries are skipped and counted. Reused
spectra guide proposals; recommended designs still receive fresh verification.

Compatible field samples from searches and **Fields → Current structure** can also
be reused. New searches record three evenly spaced midpoint depth slices per
finite layer at the fixed target wavelength. **Compare fields at both the target
and the moving resonance**, under **Saved training data and field detail**,
also records fields at the resolved selected peak, when one
exists. If that peak is exactly the target, both snapshots reuse one native solve.
Fixed-target and selected-resonance observations train separate field models.

Field descriptors now include volume-weighted layer/material intensity fractions,
pattern-material confinement, mean and maximum intensity, periodic centroids,
spatial spread, electric-component fractions, loss distribution, and local
time-averaged energy flow. Complex field overlap against a common reference
adds pattern similarity to each compatible training group. These are sampled
approximations; three depth slices cannot resolve every fine spatial feature.

After at least four distinct compatible field observations, up to three principal
components per wavelength mode summarize the varying descriptors. Geometry-to-field
Gaussian processes predict those components for both spectral training designs and
untested candidates. The absorption/Q models use the predicted field features
alongside geometry. Their contribution is bounded so sparse field data does not
dominate the geometry. Every fifth trial instead explores uncertainty in field
redistribution. Insufficient, constant or incompatible field data uses the existing
geometry-only model. All accepted designs still require measured absorption/Q and
higher-resolution verification; a predicted field hotspot never qualifies a design.

Field reuse checks wavelength mode, wavelength/tolerance, spatial grid, quadrature,
feature schema and compatible physics. Older complete E-only CSVs can be upgraded
to descriptors without rerunning S4. They retain their older depth quadrature and
missing magnetic-field status and are kept separate from new sampling groups.
The JSON history stores descriptors and proposal diagnostics; portable models
are refitted from that data instead of depending on platform-specific pickles.

The selected amount of saved data is bounded (default 300 records). Exact GP
fits retain leaders and a spread of up to 256 spectral observations; the field
surrogate uses up to 128 field records. Stored data is not deleted by these fit
limits. More data or field guidance may help the search but is not a guarantee
of faster convergence; field sampling adds native computation.

New searches save `target_history.json`, per-design spectra, partial spectra,
complex fields, `target_results.csv`, `design_models.jsonl`, `field_training.csv`,
`field_comparisons.csv` and a summary. A
successful recommendation adds `recommended_design.json` and maps at its measured
peak wavelength. Saved work can reopen the original or a selected design's
structure. Start another target search with reuse enabled to learn from earlier
completed observations; target options are recorded in the history and summary.
Unfinished native batches are not treated as completed designs.

## Electric-field maps

**Fields → Current structure** computes the current structure at a manually entered
wavelength. Select the finite layer for the XY midplane map; the XZ section at
y=0 covers the finite layer stack. XY hole outlines and XZ layer boundaries
identify the structure. Colors show |E|² / incident |E|². Arrows show Re(E) at one
incident phase, not a time-averaged field direction. Fields and spectral sweeps
honor the compute mode selected in Settings. GPU modes offload eligible matrix
products; other solver work and ML fitting use the CPU. Field runs save per-run
CPU/GPU product counts and failures in `field_diagnostics.json`.

The CSV records coordinates, layer/material labels, real and imaginary Ex/Ey/Ez
and Hx/Hy/Hz, |E|², and Sx/Sy/Sz. Local Poynting components use
0.5 Re(E × H*) in S4 normalized units; the factor of one half is explicit and
these values are not directly equated to S4's differently normalized integrated
power-flux output. Layer features include sampled means/maxima and an Im(ε)|E|² loss proxy.
This proxy is not the measured absorptance, a full volume integral or the stored
energy of a dispersive medium. Spectral Q remains λpeak/FWHM, using the existing
baseline-relative linewidth estimator; it is not an eigenmode/pole Q.

Implementation references: S4's [GetFields and field API](https://web.stanford.edu/group/fan/S4/python_api.html#S4.Simulation.GetFields)
and [units and incident amplitudes](https://web.stanford.edu/group/fan/S4/units.html).
The code uses GetFields directly for both spatial sections and retains complex
components. The documented layer-volume integrals are not substituted for
dispersive energy or absorption.

## Tracking redistribution across designs

Open **Fields → Compare saved fields**, refresh the saved datasets, and select a reference and
comparison design. Choose an XY layer from the shared-layer dropdown.
Filter by run/design, wavelength or sampling mode to compare a
useful series. The slider browses saved datasets; it is not a time-propagation
animation or a claim that every parameter was swept in order. This viewer also
compares manually saved designs with changed index, thickness, hole size or shape.
The target optimizer continues to use the geometry/material bounds entered for
that search; shape comparisons between separate searches do not introduce a new
continuous shape parameter or silently enlarge the search domain.

The four XY/XZ panels share one intensity scale and incident normalization.
Physical coordinates preserve distances in µm; layer-relative coordinates align
x/ax, y/ay and fractional depth for changing lattice/thickness. Exact XY outlines
and sampled material boundaries identify the structure. Training snapshots use
the middle XY plane and the nearest sampled y plane for XZ, which is explicitly
labelled. Optional energy-flow arrows show direction, with equal arrow length.

Tables report all design conditions, n/k evaluated at each sample wavelength,
hotspots, centroids, spread, confinement fractions and complex-field overlap.
Periodic centroids can be undefined for uniform fields; hotspot ties are recorded.
Overlap is phase/amplitude invariant and uses equal layer weights in aligned
fractional coordinates, with signatures pooled to at most 6×6×3 bins per layer.
It measures spatial pattern similarity, not stored energy or a certified eigenmode
identity. A selected spectral peak can switch resonance branches. Fixed-target
comparisons include detuning; resonance comparisons remove that fixed-wavelength
effect but can still contain mode changes. Incompatible illumination/layer layout
or sampling disables overlap rather than fabricating a comparison.

Each newly evaluated design also saves its comparison with the nearest compatible
previously evaluated geometry, with reference design/source/parameter values.
**Save comparison & create download** retains the map, metrics, full models,
and raw fields for later review and portable export. This is a sequence of
steady-state designs, not a time-domain electromagnetic simulation.

## Linux installation

The included Windows `.pyd` and project-local Windows ML wheels cannot execute
on Linux. The same source GUI is now platform-aware and loads a native extension
from `pcs_s4_runtime/linux/` on Linux.

On a Debian/Ubuntu-style system, install **Python 3.12**, its development/venv
packages, a C/C++ compiler, **CMake**, and **LP64 OpenBLAS development libraries**.
For example, on a distribution providing Python 3.12 as python3, the packages are
`build-essential cmake python3-dev python3-venv libopenblas-dev`. Install these
with your package manager, then run from the extracted source folder:

```bash
bash setup_linux.sh
bash launch_peak_gui.sh
```

The setup script creates `.venv`, installs the pinned Linux Python requirements,
and builds the matching bundled S4 source with CMake/OpenBLAS. The portable build
uses no `-march=native` and enables CPU calculations by default. To enable optional
GPU support with a compatible CUDA toolkit installed, run `bash setup_linux.sh --cuda`.
On Linux, Windows `ml_dependencies/` is ignored; scikit-learn
and SciPy load from the Linux environment. To choose a Python executable, set
`S4_PYTHON` before setup/launch. Windows likewise honors `S4_PYTHON` and otherwise
uses its existing compatible Python 3.12/MKL environment.

Copy the whole source/data bundle or use **Saved work → Results library →
Back up, share or import a library → Create whole-library backup**.
The export now includes the Linux scripts and matching S4 sources. Saved JSON,
CSV, optical tables and presets are portable; native binaries and environments
must match their operating system. Larger spatial grids can be substantially
slower and require more storage.

Validation on the development host includes native Windows S4 field sampling,
known uniform-field intensity, target constraints, history compatibility,
field-guided candidate selection, and GUI integration. This Windows host has no
installed WSL distribution or active Docker Linux engine, so native Linux build
and execution have **not** been verified here. S4's [installation documentation](https://web.stanford.edu/group/fan/S4/install.html)
describes building native extensions and BLAS/LAPACK prerequisites.
