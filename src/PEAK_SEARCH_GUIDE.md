# Parameter grid sweep and saved-data analysis

Choose **Simulation parameter sweep** from **Choose simulation**. This dedicated workspace evaluates the selected parameter grid and retains all data. Its setup contains parameter ranges and sweep budgets; Q-factor and high/low reflection, transmission or absorption are analysis of the saved data after running. AI search has its own separate workspace.

## Run an exact sweep

1. Edit the active study structure and materials. Set the wavelength or incidence-angle samples under optical sampling.
2. Add each parameter range using Parameter, Target, Minimum, Maximum and Step, then **Save range**. Parameters not listed stay fixed. Material choices are explicit library names. Empty bounds run the current structure once.
3. Set the design and total sample budgets and click **Run simulation** in the bottom bar. Numeric design bounds include both endpoints; a final interval can be shorter than Step. Optical wavelength/angle samples follow the input scan exactly, with no appended endpoint or peak refinement.
4. Inspect **All designs**. Every requested combination has an ID and status, including failed, invalid, incomplete or not-run designs. Select a design to plot its stored R/T/A spectrum. A numerical failure does not silently exclude that design or stop later combinations.
5. Use **Analyze saved sweep** to find high or low Reflection, Transmission or Absorption, optionally applying a threshold from 0 to 1. Each match identifies the actual sampled wavelength and angle. Select **Q factor** to find resolved peaks and dips of the chosen response. Analysis never invokes the solver.
6. Export the filtered table or open complete sweep files. **Use design in Structure** explicitly applies the selected design to the active study.

Grid runs do not apply response targets, fabrication constraints, learning, verification reruns or adaptive wavelength refinement. These optimizer-only settings are hidden in grid mode, including when loading an old setup. Oversized design grids are rejected before execution; sample/time budgets and cancellation produce an explicitly partial dataset.

## Saved data

- `design_results.csv`: every design in grid order, status, reason, parameter values and sampled R/T/A extrema.
- `all_spectra.csv`: all returned samples with design ID, point index, wavelength, angle, R, T and A.
- `design_<id>_spectrum.csv`: raw data for one design, even if incomplete or nonphysical.
- `design_models.jsonl`: complete model for every requested combination, including not-run combinations.
- `design_<id>_diagnostics.json`, `search_config.json`, `search_summary.json`: settings, provenance, failures and coverage.
- `evaluations/`: native worker checkpoints, including samples received before cancellation or an error.
- `grid_sweep_results.zip`: complete nested data and diagnostics. Filtering does not overwrite this archive or the raw tables.

Invalid/nonfinite or incomplete spectra remain visible in raw exports but do not qualify for response/Q filtering. No R/T/A value is clipped. A is total stack absorptance, not layer-specific absorption.

## Q interpretation

Q is wavelength divided by interpolated baseline-relative FWHM. Both peaks and dips of R, T or A can be inspected. A linewidth needs sampling gaps no larger than FWHM/8 and an approximately symmetric isolated feature. Flat spectra, scan edges, unresolved features and strongly asymmetric/overlapping features do not receive a Q value. Angle sweeps alone cannot produce a wavelength Q.

This estimate is not a pole fit, a radiative Q or convergence certification. A narrower resonance between samples can be missed: explicitly rerun with finer wavelength sampling and more Fourier harmonics to check convergence. No refinement happens automatically.

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
