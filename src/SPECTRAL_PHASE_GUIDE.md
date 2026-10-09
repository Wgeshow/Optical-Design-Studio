# Phase and spectral search update

Launch `Try Phase and Expanded Sweeps.cmd` in the parent outputs directory to run the updated source application using the existing Python environment. Existing portable EXE packages have not been rebuilt.

- Simulation: enable **Measure specular reflection / transmission phase** before running. The new **Phase and phase change** tab shows wrapped phase and unwrapped change. Results are saved as `phase.csv` and `phase.png` beside the power spectrum.
- Phase is the specular tangential electric-field component projected onto the incident tangential polarization, normalized to the incident field. Reference planes are z=0 in the incident and exit half-spaces. It is not the phase of total diffracted power. Uniform boundary layers and at least one internal layer are required. Near-zero coefficients (magnitude <= 1e-10) are undefined. Change resets after an undefined gap. Use sufficiently fine sampling to keep true phase increments below 180 degrees.
- Wavelength sweeps and Explore Designs spectral evaluation budgets now accept up to **20,000,000** points. The default search budget remains 200,000. Available RAM, storage, and runtime still determine practical scan size; full result arrays remain in memory.
- Desktop tables show the first 10,000 samples and plots preview up to 20,000 samples. CSV exports retain all samples, and highest-sample calculations use the full power data.
- Explore Designs offers **Absorption**, **Reflection**, and **Transmission**, with a response threshold from 0 to below 1. Grid, ML-assisted, refinement, and hybrid verification use the selected response. Resume histories cannot mix different response objectives. Original R/T/A spectra remain unchanged.
- For compatibility, optimizer JSON/CSV numeric keys such as `absorption` and `best_absorption` remain legacy names for the selected response. Summary and table exports identify `response`; desktop tables label the value `response_value`.

Verification includes native uniform-layer propagation for s, p, and mixed polarization; native dielectric-interface phase; phase unwrapping and undefined gaps; a sweep exceeding two million samples; reflection grid search preserving raw power data; and ML reflection search/history identity.
