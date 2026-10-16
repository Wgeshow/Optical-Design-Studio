# AI optical design in Optical Design Studio 1.2.7

## Start a design

1. Open **Structure** and define the incident medium, finite film layers, substrate, lattice periods, polarization, and incidence angle.
2. Open **Optimize → Target wavelength → Create multi-hole / double-lattice cell**. Pick the etched layer. Use **Double lattice** for two offset holes, or add/remove circle rows and edit each center and radius. The cell repeats periodically in X and Y. Applying replaces the air regions in that layer; other layers are retained.
3. For irregular openings, overlap circle primitives and enable circle unions. A connected cluster makes one opening; disconnected clusters make separate holes. All openings have straight vertical sidewalls through the selected layer. Model partial etches by retaining an unpatterned layer beneath the etched layer.
4. Apply the cell. **Use all Structure regions** is enabled and radius/position ranges appear under **Other parameters**. Edit those ranges to choose exactly what the AI may vary. Equal bounds fix a value. Unlisted parameters remain fixed. Add thickness or lattice ranges there if desired.
5. Use **Choose candidate materials from library** to select the film layer and allowed project, built-in, or saved materials. Repeat for additional layers. The search treats materials categorically, preserves their actual optical data, and checks that n/k tables cover the wavelength window. Add new datasets through the existing Materials page first.
6. Select **Absorption**, **Transmission**, or **Reflection**. Fractions are between zero and one. Enter the target wavelength and the minimum acceptable response.
7. Choose the objective:
   - **Response at target** maximizes the selected fraction at the exact target wavelength. This can optimize a broad response and does not claim to place a spectral peak.
   - **Maximum Q** searches for a resolved peak within the wavelength tolerance, above the response threshold and minimum Q, then ranks qualifying peaks by Q. Q is a baseline-relative spectral linewidth estimate, not an eigenmode lifetime calculation.
8. Keep **Use electric-field information during learning** enabled. Set a trial budget, initial sample count, and finalists. Run **AI design search**.
9. Review the verified result. **Use verified design in Structure** applies its complete geometry and materials. All spectra, intermediate designs, field maps, and model predictions are retained in the run files.

## What happens internally

The design is a list of editable circle primitives plus layer materials, thicknesses, and periodic-cell dimensions. The optimizer searches only the explicit ranges. Hole/primitive count is chosen in the editor for each run; it is not automatically added or removed by the optimizer. Connected-component count can change when circles merge or separate.

The first candidates cover the permitted parameter space. S4 supplies real spectra and complex electric-field samples. Gaussian-process models learn the selected optical response; additional field models predict compact field features at unevaluated candidate geometries. The field-informed acquisition chooses the next design while balancing expected improvement and uncertainty. No model-predicted score is accepted as a final optical result.

S4 uses the canonical circles directly when separate. Overlapping circles of one material are unioned before the solve and converted to polygon boundaries; they are never passed as invalid intersecting S4 regions. Circular arcs are approximated with 256 edges per full circle initially and 512 during merged-geometry verification. Nested material islands are preserved. Source projects retain the circles so they remain editable and can be regenerated at higher resolution.

The geometry screen checks spacing against periodic neighbors, minimum material bridges, and a minimum-neck check based on erosion of the merged opening. Point contacts and openings that span their own period are rejected. The neck check is a computational manufacturability screen, not a foundry certification; etch bias, roughness, and mechanical tolerances still need process-specific evaluation. Use circle-only patterned layers for merged-circle optimization.

Raw S4 rows always retain reflection, transmission, and absorption separately. The response selector controls peak detection, adaptive wavelength sampling, surrogate scoring, result ranking, and verification. Older acquisition/checkpoint fields named `absorption` are internal compatibility aliases for the explicitly recorded selected response; use `response`, `response_at_target`, and the raw R/T/A spectra when interpreting new results.

Each finalist is rerun with successively larger Fourier bases and finer wavelength sampling; merged contours are also refined. Two consecutive agreements across at least three requested basis settings are required, with at most four additional verification solves per finalist. A recommendation is produced only if the requested response/Q conditions and these checks pass. This is finite-search optimization, not a proof of a global optimum. Even successive agreement can miss slowly converging geometries, especially sharp features or high-contrast metals: increase the starting basis and repeat when needed. Failed convergence retains the results but does not produce an approved recommendation.

All pages now use the top tab row, including Settings and Help. The obsolete simulation-suite banner and visible navigation sidebar have been removed. The title bar still provides project, save, export, theme, and window controls.

## Practical limits

- An irregular unit cell still repeats. Two different lattice periods/rotations require a commensurate supercell, which you construct explicitly; the double-lattice preset uses a common period.
- A single run uses a fixed layer stack and circle count. Compare separate runs to explore different counts or stacks.
- Multiple material candidates can greatly increase the search space. Begin with a short allowed list and a few varying geometric parameters.
- Strong near fields alone do not guarantee the requested spectral behavior. The final criterion remains the selected S4 power response.
- The **Explore designs** tab retains the earlier absorption-peak workflow. The new three-response selector is in **Target wavelength**.
- Library constant-index presets are approximations. Measured wavelength-dependent data should be used for a fabrication decision.

## Source setup

The Windows portable build includes the native solver, ML dependencies, and Shapely. No separate Python installation is needed for that build.

For an existing source environment, install `requirements-geometry.txt` in addition to the existing desktop/ML dependencies. The source launcher also recognizes the local `geometry_dependencies` folder. Do not replace the solver's NumPy/MKL environment merely to add a geometry package.

## Verification artifacts

The delivery includes an AI test report and example recommended projects. Controlled tests give the AI a wavelength, response, and design ranges before any exhaustive reference calculation. Their example optical constants demonstrate the algorithm; they are not measured material recommendations.
