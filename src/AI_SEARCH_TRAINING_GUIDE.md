# AI Search and Training

Open `launch_ai_search_test.cmd` for the updated source application with the small completed test campaign preloaded in its own library. Open `launch_ai_search.cmd` to use your normal source-project library. The installed EXE is unchanged.

## Supported device

The field confinement objective currently supports one aligned circular air hole per perforated layer. The hole may pass through several finite PCS layers above an unperforated substrate. Geometry comes from the shared Structure; wavelength and illumination remain fixed during field sampling. Layer material choices use the materials already in the project, including their n/k tables.

## First test

1. Apply your GaAs / Al98Ga0.02As / GaAs / SiC device in Structure.
2. Open AI Search → Set up. Create ranges around the current design or copy ranges from Optimize. Review all values; range units are micrometers. Linking keeps the hole aligned across PCS layers.
3. Open Training. Choose Adaptive range sampling, set training/test counts, field sampling and an optional NEW S4 design limit (0 means no limit). Preview the count first.
4. Use Collect and train. Each design runs fields at the fixed wavelength plus a visible RTA sweep; contour extraction is postprocessing, not a separate optical simulation per level.
5. Inspect XY, full-stack XZ, each absolute field component, the sidewall depth trace, and RTA. Prediction vs S4 uses independent test designs; its errors are in log contrast or coverage units as labeled.
6. Open Search and run AI search. It selects promising and uncertain untested designs, refits from saved observations, and verifies the requested finalists. Verification requires agreement in field objective and confinement constraints at a larger basis/grid.

Training counts have no application maximum. All saved compatible training designs are used for fitting. Full range scans enumerate every combination, including grids above 10,000 designs. A full range scan refuses grids larger than an explicitly chosen nonzero limit. The default is 0, meaning no simulation limit. Adaptive range sampling samples the same ranges without enumerating every combination. The starting design is included when it lies within the bounds. Test designs are excluded from training, candidate proposals, and recommendation rankings.

## Save, pause, and reuse

Pause and save interrupts the current worker; completed designs remain in `campaign.json`. Open that checkpoint to resume. If native work must be forcibly stopped, open the last checkpoint manually. Resuming checks geometry, wavelength, ranges, basis, sampling, and collection-plan compatibility. Collect and train / Run AI search automatically start a new campaign when settings change, preserving the old checkpoint. Fit-only and verification require compatible saved settings. Each resumed run has its own optional NEW-simulation limit; completed observations do not consume it again.

Compatible completed campaigns are reused automatically from the selected project library. Compatible standalone saved field CSVs can also be analyzed without another field solve; if RTA is missing, only RTA needs additional native work. Different accuracy, illumination, materials or confinement settings are not silently pooled. Screening and verification samples are kept separate.

Fit / check saved data only launches no S4 work. Models are refit from JSON observations; no unsafe serialized executable model is loaded. Change the number of initial/adaptive designs to extend a campaign, then resume.

## Shape references

Select Match a saved field shape and choose one or more saved field directories (semicolon separated). Each must have compatible wavelength, field grid, depth/contour sampling and contour features. Multiple examples guide the search toward the nearest reference shape. References do not override the strength and coverage requirements. Higher-accuracy verification confirms physical constraints; reference similarity remains measured at the screening grid.

## Resource and accuracy limits

The optional limit counts design evaluations, each including its field sample and RTA sweep. Fourier basis and field sampling strongly affect time. The estimate uses observed average campaign time, not a guarantee. Saved contour masks can require substantial disk space. Reduce NEW designs or field grid to test the workflow, then establish numerical convergence before trusting an optimum. A 0.1 contour step improves amplitude detail, not spatial resolution.

The bundled eight-design native smoke test used deliberately low basis (17; verification 26) and coarse grids (3; verification 5). It checks the application pipeline, not an optimal or converged physical design. No tested design met the 3× target.

## Saved files

- `campaign.json`: plan, measurements, failures, settings, resumable checkpoint.
- `model_validation.json`: independent test predictions, uncertainty and errors.
- `design_results.csv` and `design_models.jsonl`: measured design review / Saved work integration.
- `designs/*/fields/`: raw complex fields, contour masks and learning features.
- `designs/*/rta.json`: visible spectral scan.
- `recommended_design.json`: written only when a higher-accuracy design meets constraints and numerical agreement.

The Use selected design action can also apply an explicitly selected screening candidate; its verification status remains visible.

AI Search owns its wavelength, polarization, incident angles, Fourier basis, scan ranges, and training settings. Simulation edits do not change these controls. Structure geometry and computing resources in Settings remain shared. Copy ranges from Optimize is an explicit copy, not a live link.
