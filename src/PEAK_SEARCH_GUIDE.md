# Peak search and design optimization

**2026-09-09 update:** The GUI now defaults to Hybrid verified and also offers
ML assisted. See [ML_SEARCH_GUIDE.md](ML_SEARCH_GUIDE.md) for those modes and
resumable optimization. The finite-grid workflow below describes **Exhaustive
grid** mode; the peak-measurement and fabrication conventions still apply.

Open **Optimize → Explore designs** in the source GUI. Start the updated
source with `launch_peak_gui.cmd`. On this computer it selects the original
`%USERPROFILE%\anaconda3\envs\s4_updated` environment, which contains MKL 2023's
`mkl_rt.2.dll`. The separate ProgramData environment has MKL 2025's incompatible
`mkl_rt.3.dll`. The existing executable_build binaries have not been rebuilt;
launching those old executables will not show this source update.

## Workflow

1. Load or enter your layer stack and patterns in Structure and optical data in Materials.
   Include physical optical loss: a lossless model cannot produce a 99% absorber.
2. In Simulate choose Wavelength sweep and enter start, stop, and the initial
   wavelength step. The peak search explicitly includes the stop wavelength.
3. In **Optimize → Explore designs**, choose what can change and where using
   the dropdowns, enter Min/Max/Step and click **Add / update range**. Alternatively,
   click **Create ranges from the entire current structure** and edit those ranges.
   Equal Min/Max fixes a parameter. All
   bounds include both endpoints; the final interval may be shorter than Step.
   Leaving the bounds table empty analyzes the current structure only.
4. For material selection use **Allowed materials**. The advanced table also
   accepts library names separated by semicolons in Choices.
   Optical-constant tables continue to be evaluated at each wavelength by S4.
5. Set the detection prominence independently of the absorption target. Default
   prominence is 0.00001; acceptance is strictly greater than 0.99. Weak peaks
   remain candidates throughout the search. The highest sampled value is always
   reported, including a range-edge maximum or a flat spectrum with unresolved Q.
6. Choose **Exhaustive grid**, set design and spectral-point budgets and click **Start design search**.
   Every grid combination is considered. An oversized grid is rejected, never
   silently truncated. Performance timeout applies to the entire search.
7. Inspect all designs ranked by absorption, all designs matching the best within
   the tolerance, and every detected above-target peak ranked by estimated Q.
   Choose a design in **Design to use in Structure** and click **Use selected design**
   to load it into Structure and Simulate. Re-run leading designs with smaller wavelength steps and
   larger Fourier basis counts. The optical-constant uploads must remain present.
8. Save search boundaries separately from the existing project JSON. Download
   the ZIP for complete conditions, spectra, results, and runtime diagnostics.

## Manual-bound parameters

| Parameter | Target | Meaning |
| --- | --- | --- |
| lattice_square | blank | Set both lattice dimensions (um) |
| lattice_x / lattice_y | blank | Independent lattice dimensions (um) |
| thickness | Layer name | Internal layer thickness (um) |
| layer_material | Layer name | Semicolon-separated material library names |
| radius | 1-based pattern row | Circle radius (um) |
| r_over_a | 1-based pattern row | Circle radius divided by min(ax, ay) |
| size_x / size_y | 1-based pattern row | Existing S4 shape-size convention (um) |
| center_x / center_y | 1-based pattern row | Pattern center (um) |
| rotation | 1-based pattern row | Pattern rotation (degrees) |
| pattern_material | 1-based pattern row | Semicolon-separated material names |

A square-lattice bound cannot be combined with lattice_x/y bounds. Radius and
r_over_a cannot both control the same pattern. Ratio-derived radii are computed
AFTER setting the lattice, regardless of table row order. The lattice dimensions,
all layer thicknesses/materials, pattern geometry/materials, incidence angles,
polarization, and basis count appear in exported conditions. Complete normalized
models, including optical-constant tables, are in design_models.jsonl.

## Fabrication and acceptance

- Every circle must satisfy r/min(ax, ay) strictly below the selected limit,
  which may be tightened but cannot exceed the user's 0.6 requirement.
- By default circles must remain separate. Periodic self-neighbors and pairs in
  the same layer are checked, including the specified minimum bridge width.
  Disable this option only when merged circular regions are intentional.
- Bridge checks do not certify manufacturability for ellipses, rectangles, sidewall
  slopes, aspect ratios, roughness, or process variation. Enter suitable geometry
  bounds and verify these separately.
- Absorption is TOTAL stack absorptance from the existing backend (1 - R - T),
  not specifically graphene absorption. A design with parasitic material loss can
  therefore exceed the total absorption target. Layer-specific absorption is not
  calculated by this panel.
- The target comparison is strict: exactly 99% does not satisfy >99%.
- Matching tolerance is an ABSOLUTE fraction. 0.0001 means 0.01 percentage points.
  Best-match designs may be below the acceptance target; the above_target column
  distinguishes them. Use zero tolerance for numerically exact matches.

## Search and linewidth method

This is an exhaustive finite geometry grid with adaptive wavelength sampling,
not Bayesian optimization and not a proof of a global maximum over continuous
geometry/material space. Design steps define the geometry resolution. Lower
those steps around promising designs to refine the geometry search.

For every design the full initial wavelength grid is evaluated. All detected
local maxima above the prominence threshold, plus the absolute highest sampled
value, receive additional S4 samples near their centers and across their measured
linewidths. Peak selection is independent for each design; spectra may exchange
which resonance is tallest. This implementation does not assign persistent modal
IDs or use field-overlap tracking at mode crossings.

Q_estimate is wavelength divided by the interpolated baseline-relative FWHM,
appropriate as a spectral estimate for an isolated, approximately symmetric
resonance. The baseline is the higher of the adjacent valleys. Q is left blank
for flat, edge, undersampled, or strongly asymmetric peaks. Sampling gaps across
the width must be <= FWHM/8. This is NOT a Lorentzian/Fano pole fit, a separate
radiative Q, or proof of Fourier-basis convergence. Overlapping/Fano spectra need
modal fitting before treating the estimate as physical loaded Q.

Arbitrarily narrow peaks between initial samples can be missed. Repeat with a
finer initial wavelength grid and confirm absorption, peak location, and Q with
more Fourier harmonics. A tiny change in absorption near unity can be numerical;
use a match tolerance consistent with convergence evidence. Materials retain the
original backend's endpoint clamping outside uploaded table coverage; check
warnings in per-round diagnostics and provide data over the entire search range.

## Downloads and partial results

- design_results.csv: one highest-sampled-absorption result per completed design,
  plus excluded/failed/incomplete rows, sorted by absorption.
- matching_best.csv: all evaluated designs within tolerance of best absorption.
- above_target_by_Q.csv: ALL detected peaks strictly above target, descending Q;
  unresolved Q values are last. A design can occur more than once.
- all_peaks.csv: detected peaks for every completed design.
- design_models.jsonl: full normalized model for every attempted design.
- design_ID_spectrum.csv: complete combined coarse/refined spectrum per completed
  design; best_spectrum.csv is the best-absorption design's spectrum.
- search_config.json: manual bounds, original project, normalized base model,
  material tables, and search/performance settings.
- search_summary.json and per-round diagnostics: coverage, status, and runtime.

The UI previews at most 5,000 rows per table. Downloads are not truncated.
Cancellation, whole-search timeout, or spectral-budget exhaustion preserves
completed designs and labels the run cancelled/partial. An interrupted design
is marked incomplete and not ranked. Three consecutive simulation failures stop
the search with partial results. No result is called feasible when none exceeds
the requested absorption target.

## Validation (2026-09-08)

- 20 unittest cases: 19 passed; the opt-in GPU test was skipped.
- Includes existing native S4 Fresnel, serial/parallel, angle, dispersive-material,
  cancellation, timeout, and worker-cleanup regression tests.
- Seven new tests cover weak peaks, Lorentzian Q, multiple resonances, unresolved
  spectra, categorical materials, strict geometry bounds, finite-grid coverage,
  ties, export provenance, cancellation, budgets, and nonphysical results.
- Real S4 + Gradio API: two-design adaptive search, plot/table/download
  serialization, selected-design application, boundary save/load, original
  simulation callback, search cancellation, and subsequent native rerun passed.
- These validate the implementation; no fabrication-ready >99% physical design
  has been optimized or certified by these small test runs.

Run tests in the compatible S4 environment:

    python -m unittest discover -s tests -v
    python tests/check_peak_gui_api.py

Source backups are in backup_before_peak_search_TIMESTAMP inside this folder.
