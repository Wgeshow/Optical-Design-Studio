# ML-assisted S4 design optimization

Start the updated source with **launch_peak_gui.cmd**, then open **Optimize →
Explore designs**. The default search method is **Hybrid verified**. The older
packaged EXEs have not been rebuilt and do not contain these changes.

## Choose a search mode

| Mode | What gets simulated |
| --- | --- |
| Exhaustive grid | Every combination of your manual Min/Max/Step settings |
| ML assisted | A space-filling initial sample, then designs selected by learned absorption and Q models |
| Hybrid verified | ML search, a complete local half-step geometry grid around leading designs, then higher-resolution S4 runs of selected finalists |

Use the **Simulate** tab to enter wavelength start, stop, initial step,
incidence and polarization. Material libraries, layer definitions and pattern
conventions are unchanged. Your manual Step still defines the global candidate
grid; hybrid mode also tests geometry between those grid points near leaders.

An ML or hybrid search reports the best **evaluated** candidates. It cannot report
every design in an unsimulated region or certify a global maximum. Exhaustive
mode remains available when complete coverage of a manageable grid is required.

## Suggested first run

1. Enter/load the physical structure and optical constants, including loss.
2. Enter the wavelength range and initial spectral step in Simulate.
3. Use the guided range editor or **Create ranges from the entire current structure**.
   Set Min/Max/Step for lattice,
   radius or r/a, layer thicknesses, and any other desired parameters. Equal
   Min/Max fixes a parameter. Select material alternatives in **Allowed materials**;
   the advanced table also accepts semicolon-separated material names.
4. Choose Hybrid verified. Start with the default 24 initial designs, 60 ML
   trials, and a maximum of 500 geometry evaluations. These are starting budgets,
   not guarantees of convergence. Small grids may contain fewer candidates.
5. Keep the strict absorption target at 0.99 or higher and the strict r/a limit
   at 0.6 or lower. Set circle separation and minimum bridge requirements.
6. Run. Read the absorption ranking, matched-best table, and above-target Q
   ranking together with each row's phase and verification_status.
7. Download the ZIP and optimization_history.json. If more search is needed,
   upload that history, retain matching physical/detection settings and bounds,
   and increase budgets. ML assisted history can be continued in Hybrid verified.

Use at least two finalists to cover both the highest-Q feasible candidate and
the highest-absorption candidate when they differ. With one finalist the Q leader
has priority once a resolved above-target Q exists.

## What the model learns

The model is a CPU Gaussian process using a Matérn covariance function. Numeric
design variables are scaled to their entered ranges. Material choices use
one-hot categorical encoding, so a material's position in the list does not imply
an optical similarity or numerical ordering.

Initial designs are chosen to cover the allowed space. Later proposals use
expected improvement and posterior uncertainty. Before a feasible Q has been
observed, the search emphasizes peak absorption. After feasibility is found,
most proposals pursue higher log(Q), weighted by the predicted probability that
the **same resonance** has absorption above the target. Separate models track
maximum absorption and the absorption paired with the Q-producing peak. Periodic
absorption and uncertainty proposals retain exploration outside the current Q
leader's region. Unresolved Q values are omitted from Q-model training.

The candidate pool is refreshed deterministically from the random seed and the
completed history. Small grids are enumerated for candidate selection; large
grids use Latin-hypercube candidates. Geometrically invalid proposals are
screened before S4. Absorption and Q models are refit from observations; fitting
uses at most 256 records, retaining leaders and a spread of earlier observations
to control cost. Complete observations remain in the saved history and reports.

The absorption surrogate uses a small noise floor (0.0001 fraction), and the
log-Q model uses 0.02. These are numerical modeling assumptions, not a measured
fabrication-error distribution. Posterior standard deviations are not proof of
physical accuracy, feasibility, or manufacturing yield.

## Peak measurement and constraints

Every selected geometry goes through actual S4 wavelength simulations and the
existing adaptive peak refinement. Weak peaks remain eligible for detection
before the >99% requirement is met. Initial sampling can still miss extremely
narrow resonances; a surrogate cannot recover a peak that the spectral evaluator
never detected. Use a suitable initial step and compare refined spectra.

The optimizer retains:

- Strict A_peak > 0.99 (or the higher user target).
- Strict r/min(ax, ay) < 0.6 (or the lower user limit).
- Manual geometry/material bounds and optional circular-region bridge checks.
- A manually entered wavelength window.

Absorption is total stack absorptance, 1 - R - T. It is not layer-specific
graphene absorption. Q is still a baseline-relative spectral FWHM estimate;
unresolved or strongly asymmetric peaks do not supply Q training data. This
update does not add a Fano pole fit or field-overlap mode tracking. All final
rankings contain S4 observations, never unevaluated surrogate predictions.

## Hybrid verification

The local stage builds the full Cartesian neighborhood of each selected leader.
Each varied numerical coordinate is evaluated at the leader value and ±half of
the median original grid spacing, clipped to the manual bounds. Fixed variables
and the leader's material choices are retained. Overlapping neighborhoods are
deduplicated. Geometry exclusions remain active.

The grid can grow as 3^d for d varied numerical parameters. If the remaining
design budget cannot cover it, the grid is not silently shortened: the run is
marked partial and the required budget is reported. The selected finalists can
still receive their resolution checks. Resume with a larger budget to finish
the saved local grid. A saved partial grid remains fixed unless additional ML
exploration changes the stage that produced it.

Finalist checks increase the Fourier basis by the chosen multiplier (default
1.5, rounded up) and reduce the initial wavelength step by the divisor (default
2), followed by the same adaptive spectral refinement. The export records the
reference design, absorption change, relative Q change and Q-peak wavelength
shift. By default, two-resolution agreement requires absorption changes <=0.001,
relative Q changes <=5%, and a consistent Q-peak location. The higher-resolution
Q must still satisfy the strict absorption constraint.

Successful higher-resolution observations replace the earlier result for that
geometry in all final rankings, even when absorption or Q decreases. All earlier
observations remain in the history. A completed verification run does not mean
the two resolutions agreed. Check **verification_status**, **finalists_agree**,
and the summary flags for whether the current absorption/Q leaders were checked.
When a finalist degrades, a different, unchecked candidate can become the leader;
the GUI reports that explicitly. Only selected finalists are rerun.

Two-resolution agreement is a numerical check, not fabrication certification or
a proof that a continuous global optimum has been found. Geometry and material
uncertainties must still be assessed for the selected physical design.

## Budgets, stopping and resume

- ML trials include the initial designs and previously saved exploration trials.
- Maximum designs counts all exploration/local-grid evaluations, including prior
  attempts on resume. Finalist resolution reruns are additional.
- Spectral-point budget and the Performance timeout apply to the entire new run,
  including verification. Previously completed observations are not charged to
  the new spectral budget. An interrupted in-progress spectrum is rerun on resume.
- Optional patience stops after the entered number of trials without a measured
  improvement. Zero disables it. This is a stopping rule, not a convergence proof.
- The saved history must match the structure, materials/tables, basis, wavelength
  grid, design dimensions, absorption target and fabrication/detection settings.
  Changes to budgets, hardware settings or search mode do not invalidate it.
- Histories are JSON, not pickled models or executable objects. Metrics are
  recomputed from stored spectra on load. The GUI's upload limit is 50 MB.
- Stop preserves completed observations. Native S4 errors are reported, and three
  consecutive evaluation failures stop the run. A failed or cancelled run never
  becomes an undocumented successful full search.

## Result files

Existing CSVs, full spectra, diagnostics and normalized design-model JSONL remain
available. The ZIP also contains:

- **optimization_history.json**: resumable observations, spectra, search settings,
  physical-model fingerprint and local verification plan. Written after each
  completed/failed trial using atomic file replacement.
- **optimization_history.csv**: every observation, phase, prediction at selection
  time, measured peak, Q estimate and verification result. Earlier coarse results
  are retained with used_in_final_ranking=false after successful verification.
- **search_summary.json**: ML/grid coverage, resumed counts, local-grid status,
  verification completion and agreement, plus whether the current leaders were
  checked at higher resolution.

Tables include predicted_absorption, absorption_std, probability_above_target,
predicted_log_Q, log_Q_std and paired_peak_probability when a model was available
at candidate selection time. Initialization/local-grid/verification rows may have
blank prediction fields. Predicted absorption can extend outside [0,1] because
the Gaussian surrogate is unconstrained; predictions never replace S4 values.

Applying a selected design now also loads its Fourier basis count. The Simulation
tab's wavelength step remains your original input; the exact irregular sampled
spectrum is available in the exported CSV.

## Dependencies and installation

Optional packages are installed in **ml_dependencies** within the project:
scikit-learn 1.7.2, SciPy 1.16.3, joblib 1.5.3 and threadpoolctl 3.6.0. NumPy and
MKL in the existing S4 environment have not been replaced. The GP fit uses one
math thread; S4 still uses the selected Performance settings.

For another compatible Windows/Python 3.12 installation, run
**install_ml_dependencies.cmd**, then **launch_peak_gui.cmd**. Optional versions
are recorded in requirements-ml.txt. Exhaustive mode does not require the ML
packages. Existing packaged executable builds have not been updated.

## Validation

The regression suite covers constrained acquisition with paired absorption/Q,
categorical encoding, weak peaks, strict bounds, finite candidate budgets, GP
uncertainty, large histories, cancellation/resume, saved local grids, and
replacement of coarse results after higher-resolution degradation.

Real S4/Gradio integration checks exercise all three modes, new predictions,
resuming four completed trials with only one new trial, hybrid geometry and
resolution checks, loading a verified design's basis, history mismatch rejection,
the original simulation API, and cancellation/worker cleanup. These small tests
validate the software; they do not establish a physical >99% optimized design or
a guaranteed speedup on a particular user's design space.

Run in the compatible S4 environment:

    python -m unittest discover -s tests -v
    python tests/check_peak_gui_api.py

Source backups are in backup_before_ml_search_TIMESTAMP.
