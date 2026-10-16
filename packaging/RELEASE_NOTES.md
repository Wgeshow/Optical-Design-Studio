# Optical Design Studio 1.4.0-alpha.1 — Highly Experimental

**Shipment validation — deliberately partial:** 237 source tests, 20 packaging gates, all 27 compiled startup/model screens, 12 compiled model jobs, and 2 edited band-structure jobs passed. At the explicit request to package and ship, the remaining compiled self-tests and real Windows native startup suite were stopped before completion. This Highly Experimental release does not claim those unfinished checks passed. The finite PCSEL paper case executed but remains unconverged.

**Highly Experimental prerelease · Windows · October 15, 2026**

This release brings editable photonic-crystal, semiconductor, thermal and PCSEL studies into Optical Design Studio, alongside a substantial redesign of the existing simulation setup screens. It adds a searchable launcher with **27 destinations**, an integrated library of **24 reference cases**, and clearer routes from a missing input to the exact field that needs attention.

**These additions are experimental research tools.** Implemented controls, a completed calculation and agreement with a particular reference are separate claims. Model assumptions, numerical convergence and the suitability of material parameters still need to be assessed for each device. The 27 destinations include existing tools with redesigned workflows, related modes sharing a solver, and the paper library; they are not 27 new physics engines.

## All simulation destinations

| Family | Available destinations |
| --- | --- |
| Optical — 5 | **Optical spectrum** (S4); **Time-domain optics** (MEEP); **Refractive-index sweep**; **Optical fields & phase**; **High-field optical response** |
| Photonic crystals — 3 | **3D Photonic Bands** (MPB); **2D Photonic Bands** (MPB); **2D bands · Legume** |
| Electrical & heat — 8 | **Electrical device · DC**; **Current–voltage sweep**; **Capacitance–voltage sweep**; **Coupled electrical & optical**; **1D Semiconductor transport**; **2D Semiconductor transport**; **Temperature & heat flow**; **Finite-contact transport** |
| PCSEL and laser — 10 | **PCSEL vertical modes**; **PCSEL coupled-wave modes**; **PCSEL finite-area modes**; **PCSEL far-field beam**; **PCSEL aperture response**; **PCSEL guided-mode expansion**; **PCSEL RCWA resonances**; **PCSEL periodic transport**; **PCSEL representative cell**; **Laser rate equations** |
| Reference library — 1 | **Paper comparisons**, with 24 cases that can be run as references or opened as editable setups |

Selecting a destination opens its setup; it does not launch a calculation. Existing optical tools, workspace routes and saved-project workflows remain available.

## Editable setup and a cleaner interface

- A searchable, family-filtered launcher with native icons provides direct access to DC, IV, CV, 1D/2D transport and the individual optical/PCSEL models.
- Guided setup stages, structure previews and selected-object inspectors replace dense forms on the redesigned screens. Desktop layouts give the scene room; compact layouts stack or switch panels while retaining access to advanced settings.
- Geometry, materials and model parameters remain editable within each solver's supported domain. Independent periodic-crystal, Sesame and conformal PCSEL documents do not silently replace the shared finite device. Studies that use the shared device retain its material, contact and mesh assignments.
- Photonic Bands has a dedicated 3D unit-cell editor with orbit, pan, zoom, object picking, skew lattice cells and repeated neighbors. Existing 2D documents remain supported. PCSEL setups expose editable layer stacks and patterned objects, rather than fixed study presets.
- Clickable missing-input messages open the appropriate workspace, object and field, including individual coordinate components. The workflow supports returning to the issue list while preserving unfinished edits.
- Draft persistence retains stable object IDs, inactive settings and unfinished numeric text. Editing a reference uses the ordinary setup controls; reference provenance stays separate from the edited physical inputs.
- Results expose the saved artifacts appropriate to the model: spectra, band curves, current–voltage data, carrier and temperature fields, mode/beam maps, convergence records and reference comparisons. Array viewers support physical axes where supplied and retain explicit index-based access otherwise.
- Runtime configuration and explicit installation checks help identify missing external solvers. A successful installation check does not imply that a device calculation or its convergence has been verified.

## Newly integrated models and study controls

### Periodic photonic bands

MPB calculations support editable 2D and fully 3D periodic crystals; Legume supplies a separate 2D plane-wave route. Controls include real-space lattice vectors, supported geometric objects, dielectric constants, an optional physical reference scale, reciprocal-space paths, explicit points and reciprocal-cell grids. Resolution/basis convergence runs and linked geometry/material parameter sweeps use the same job and saved-result workflow.

The ordinary 2D MPB/Legume band models describe an infinite cross-section. Finite-thickness slab calculations are a separate PCSEL guided-mode-expansion route. Supported band materials use positive, real, nondispersive scalar permittivity. Sampled bands or a successful refinement run do not establish a complete Brillouin-zone gap or universal convergence. Legume rejects overlapping objects, including overlapping periodic images; MPB retains its own object-precedence behavior.

### Semiconductor transport and heat

Sesame provides independent editable 1D/2D drift-diffusion domains with mesh nodes, material regions, doping, generation, end contacts, voltage schedules and point/line defects. Saved outputs include current–voltage data, bands, potentials and carrier distributions. This route uses nondegenerate carriers, two contacts at the x ends and constant temperature; it is not a 3D or self-heating model.

Standalone heat flow uses the current finite device with explicit thermal conductivities, prescribed total power per layer and fixed-temperature, convection or insulated faces. It solves steady heat flow with constant isotropic properties. Current-derived heating and temperature feedback belong to the optional advanced-transport path, not this standalone prescribed-heat study. Reaching a temperature guard is not evidence of thermal runaway.

Finite-contact transport adds explicit contact/interface resistivities and optional recombination, electrochemical heating, temperature feedback, straight-column nonlocal tunnelling, bandgap-sensitivity and high-field optical calculations. These are experimental constitutive models requiring explicit parameters and source notes. They do not constitute a calibrated quantum, multiband, thermionic-barrier or carrier-energy solver. Optional mechanisms remain opt-in.

The standalone high-field optical route exposes a two-band Airy/Franz–Keldysh sensitivity calculation, including absorption and refractive-index changes. Its finite-energy Kramers–Kronig integration needs convergence checks; indirect transitions, excitons and calibrated many-body susceptibility are outside its scope.

### PCSEL and laser studies

Editable PCSEL studies now cover vertical waveguide modes, four-basic-wave coupled-wave calculations, rectangular finite-area modes, saved-mode beam calculations, a reduced aperture response, Legume slab GME and S4 RCWA resonance calculations. Model-specific controls include layer/shape geometry, numerical accuracy, mode selection, excitation and supported parameter sweeps. Existing lumped laser rate-equation tools are also reachable from the launcher.

These models have different meanings. Coupled-wave theory is an approximation, not a full-vector Maxwell solution. Finite-area modes require basis and spatial convergence. The beam model uses a paraxial Fraunhofer treatment; passive modes alone do not predict output watts, and absolute power requires explicit calibration. **PCSEL aperture response is a source-bound carrier, thermal and rate model**, not a new full-aperture 3D drift-diffusion solve.

Periodic PCSEL transport adds an independent editable conformal cell using Gmsh tetrahedral meshing and a finite-element transport worker. It assumes full-face ideal-ohmic end terminals and periodic lateral boundaries, and needs mesh/bias convergence. The separate representative-cell route uses the current rasterized finite device with insulating side faces; it must not be interpreted as periodic wraparound or a boundary-fitted mesh. Neither route automatically supplies calibrated gain or a full laser prediction.

## Paper comparisons that run inside the program

The library contains **24 reference cases, not 24 unique publications**: eight optical-spectrum cases, six dielectric-capacitance cases, two photonic-band cases, two Sesame transport cases and six PCSEL cases.

Each case retains its source and limitations. Users can run a reference through the program or duplicate it into an editable setup. Comparison artifacts retain observed/reference values, residuals and available error metrics, together with whether the physical input was edited. Provenance distinguishes author data, digitized figures and recovered study inputs. Inferred materials, contacts or other assumptions remain part of the case limitations.

The library's presence is not a claim that every case reproduces its publication. Partial results, validity limits, unmatched references and unconverged calculations must remain distinguishable from successful execution and accepted reproduction.

## Notable fixes

- Preserved unfinished edits during missing-input navigation, including shared-device object inspectors, without implicitly applying or discarding them.
- Flushed active editors before validation, saving and running; preserved inactive and invalid draft fields through model changes and project round trips.
- Corrected cross-workspace diagnostic routing and exact PCSEL coordinate/aperture-component focus, including stable-ID selection after objects are reordered.
- Added the normal project-replacement confirmation and active-job guard when restoring saved inputs through Results rerun/refine; reference-copy workflows also respect project replacement handling.
- Made generic PCSEL and conformal imports open the usable Build device editor, while preserving deliberately saved advanced-section selections. Removed routes to emptied legacy setup tabs.
- Corrected thermal-only validation so heat-flow models do not require electrical contacts.
- Corrected Photonic Bands template identity after importing, restoring or editing a crystal; retained physical-scale precision and clarified 2D polarization, reciprocal sampling and lattice-resolution labels.
- Kept geometry previews available while unrelated solver/runtime inputs are unfinished, with explicit last-valid-scene behavior during invalid geometry edits.
- Fixed compact-layout clipping, collapsed labels and overlapping 3D controls, and corrected theme callbacks that could reference deleted Qt widgets.
- Improved saved-array axis selection and unstructured-field handling; unevaluated high-field cells are masked rather than displayed as physical zeros.

## Additional changes since the stable 1.3.2 release

- Device Studio adds editable finite geometry, patterned areas and arrays, local doping, contact footprints, mesh controls, electrical materials with source notes, and linked optical/electrical setup. Original Optical Studio remains available. Finite electrical geometry and the periodic optical cell have explicit, different scopes.
- Optical execution supports native S4 structural/mirror-symmetry paths and an optional CUDA eigenfree scattering backend, with saved solver selection and runtime checks. Acceleration depends on geometry, sampling and hardware; this release does not promise a universal speedup. GPU operation requires a compatible NVIDIA driver.
- Spectrum-only and separately requested electric-field jobs are distinct. Saved-spectrum extrema can select an exact field wavelength; changed physical inputs invalidate that selection. Complex electric/magnetic arrays, saved 3D field views and CSV exports remain available.
- Field-array reconstruction and binary storage reduce repeated per-sample work. Exact-cutoff handling and explicit unavailable-point records avoid substituting shifted wavelengths or invented finite values. A spectrum with unavailable samples displays gaps and warnings; an entirely unavailable spectrum still fails.
- Phase output preserves the requested reference convention and reports unavailable values explicitly. Native window startup/maximize/restore, glass rendering and deferred layout/plot refresh fixes are retained in this build.

## Dependencies and practical limits

Solver availability depends on the selected route and the packaged/native checks listed below. MPB and MEEP require their supported external environments. Legume and Sesame need compatible Python environments and dependencies; conformal transport additionally needs Gmsh. Advanced semiconductor routes require their configured semiconductor runtime. S4-based spectrum and RCWA calculations use the application's S4 runtime.

Local/WSL executable selections and explicit package/library paths are saved where supported. Merely opening an editor does not install a solver. A configured runtime from one computer may need adjustment on another. No feature in this release implies GPU acceleration, a universally converged mesh, or validated material coefficients.

## Release evidence and downloads

The release packages include **BUILD_VERIFICATION.json**, a public payload manifest, corresponding application/native source and dependency licenses. The release assets **VALIDATION.json** and **SHA256SUMS.txt** record archive identities and integrity. Final release-page verification results refer to this version's exact compiled candidate; earlier local measurements are not substituted for its release checks.

The validation scope includes source regressions, packaging gates, compiled UI/model-route checks, real Windows startup checks and selected actual solver jobs. It does not establish convergence for every editable device or successful reproduction of all 24 reference cases. In particular, a finite-area PCSEL job may execute and still report **unconverged**. Treat that result as unconverged.

- **OpticalDesignStudio-Portable-1.4.0-alpha.1-Windows-x64.zip** — unsigned Windows application and bundled runtime.
- **OpticalDesignStudio-Source-1.4.0-alpha.1.zip** — matching readable application/native source, build recipe and licenses.
- **FEATURE-OVERVIEW.html** — a standalone offline overview with 60 actual source-application screenshots, 28 screens and all 27 selectable destinations. Screenshots show editors, not calculated simulation results. Fit-screen and actual-size controls prevent wide browsers from enlarging screenshots beyond their original pixels.
- **RELEASE_NOTES.md**, **VALIDATION.json** and **SHA256SUMS.txt** — feature/fix list and release evidence.

Extract the portable ZIP into a new writable folder and keep both executables and `_internal` together. Preserve existing projects and User Data. User libraries, sessions and machine-specific solver selections are not included in the public package; configure optional solvers on the destination machine. Read **START_HERE.md** for installation and **SOURCE_README.md** in the source package for rebuilding.

This is a **Highly Experimental prerelease**, not the stable update channel. Download it explicitly from the prerelease page; the stable release remains available. Use device-specific convergence checks before relying on numerical predictions.
