# Optical Design Studio 1.4.0-alpha.2 — Highly Experimental

**Highly Experimental prerelease · Windows x64 · October 2026**

This update fixes exhaustive parameter sweeps, separates every simulation into its own editable workspace, and adds automatic solver-environment setup. It follows **1.4.0-alpha.1** and retains its optical, electrical, photonic-crystal, thermal and PCSEL capabilities.

## Changes since alpha.1

### Exact parameter sweeps and saved-data analysis

- **Simulation Sweep** now runs the Cartesian product of the parameter values you select, using exactly the requested optical samples. It does not add hidden wavelength samples, refine the grid, optimize toward a target, or discard designs because they have weak peaks.
- Every selected combination receives a recorded outcome. Completed spectra, parameters and saved artifacts remain available; stopping a run preserves available partial samples and identifies unfinished or unstarted designs. Unavailable values remain explicit blanks instead of invented zeros. Failed or incomplete designs are excluded from applicable analysis without deleting their raw data.
- After running, search the saved data for **Q-factor estimates** or designs with **high/low reflection, transmission or absorption**. Changing these filters does not rerun the solver or rewrite the recorded spectra. Q is a sampled, baseline-relative linewidth estimate, not a fitted eigenmode Q or proof of convergence.
- The sweep has its own setup and saved results. **AI Search** remains a separate selectable tool. Applying a saved design updates the active simulation without restoring an older copy of other simulations.

### Independent simulation workspaces

- The chooser now contains **29 destinations: 28 simulation/tool workspaces and Paper comparisons**. Simulation Sweep and AI Search are directly selectable alongside the existing study types. These are destinations, not 28 separate physics engines.
- Each type retains its own structure, materials, parameters and unfinished inputs. DC, I–V and C–V, all three band variants, the two Sesame dimensions, and the individual PCSEL models have separate editors. Their diagnostics and results no longer appear as another study's state.
- Dedicated pages show the selected simulation's controls and identity. Unrelated family/model switches are removed from those pages; **Choose simulation** opens another workspace. The coupled workspace still exposes its own optical and electrical setup sections.
- **Transfer inputs** explicitly copies compatible structure/material inputs into the destination. It retains destination solver, sampling and operating settings and leaves the source independent. Unsupported crystal/finite-device conversions are not guessed.
- Saving and reopening retains the document collection, including inactive material-table assets. Existing single-study projects remain readable. Loading a recent setup, an electrical preset or an applied search design no longer overwrites newer edits in unrelated studies.

### Automatic environment setup

- Optional-solver panels provide **Find installed solver**, **Set up automatically**, progress/error logs and cancellation. Supported paths cover Legume, Sesame, Gmsh and the MPB/Meep Linux or WSL runtimes.
- Setup uses separate managed environments, checks the required solver API and selects a verified runtime for the study. Solver-specific runtime choices are remembered independently. Opening an editor does not download dependencies.
- Windows source launch/install scripts can prepare a compatible Python desktop environment and check full application construction, native S4 and semiconductor dependencies. Missing PyYAML and native-library discovery issues found during fresh setup were corrected.
- Windows support still requires a functioning WSL installation for MPB/Meep; enabling Windows components can require administrator permission and a restart. Download access is needed for automatic installation.

## Fixed bugs

- Late edits and selection callbacks from hidden electrical tables could change the active study's doping, enabled objects or selection. Hidden editor/save callbacks are now checked against their owning document.
- FDTD project restoration could leave the displayed resolution and submitted job stale. Unrun controls now restore with the correct study; AI/index/sweep settings and empty bounds also restore independently.
- Partial research drafts could retain values from the previously displayed setup. Missing fields now restore defaults; incompatible model/dimension imports cannot change a dedicated workspace's type.
- Worker progress signals conflicted with a Qt event handler, producing “signal is not callable” errors during cleanup. The signals are now separate from Qt's event method.
- Grid cancellation could be reported as failure or lose final artifacts while saving. Cancellation now retains partial data, and finalization protects checkpoint/archive saving. Unavailable spectrum cells no longer crash analysis or checkpoint recovery.
- Opening the simulation chooser briefly created many extra top-level windows. Cards and the empty-search label now have parents before becoming visible. The targeted audit changed from **174 unexpected window-show events to zero** across six chooser constructions.
- Cached electrical results could appear under another study; Results-to-Simulation navigation could lose the local setup view. Dedicated result ownership and return navigation now preserve the correct context.
- PCSEL revisits could reset the local section while the header still indicated Results. First-visit titles, paper-library context and setup/result navigation now stay synchronized.
- Choose simulation and Transfer inputs were hidden in some wide layouts; compact grid controls overlapped. Both actions remain accessible, and the compact sweep form scrolls without the observed overlaps.
- Coupled's standalone-optical action could remain in Coupled mode. **Open standalone optical simulation** now opens the independent optical workspace; copying inputs remains an explicit transfer.
- Study-bank metadata could falsely mark an unchanged paper reference as edited. Physical-input comparison excludes this persistence metadata.

- The portable build keeps the reviewed NumPy runtime ahead of optional GPU vendor packages, avoiding an unintended core-library version override.

## Available features

| Family | Selectable studies and tools |
| --- | --- |
| Optical and search — 7 | S4 optical spectrum; Meep time-domain optics; refractive-index sweep; optical fields and phase; high-field optical response; Simulation Sweep; AI Search |
| Photonic crystals — 3 | 3D MPB bands; 2D MPB bands; 2D Legume bands |
| Electrical and heat — 8 | DC device; I–V; C–V; coupled electrical/optical; 1D and 2D Sesame transport; prescribed temperature/heat flow; finite-contact transport |
| PCSEL and laser — 10 | Vertical modes; coupled-wave modes; finite-area modes; far-field beam; aperture response; guided-mode expansion; RCWA resonances; periodic transport; representative-cell transport; laser rate equations |
| Paper library — 1 | 24 versioned reference cases with source/provenance, editable copies and comparison artifacts |

Editable geometry/material controls, supported structure previews, the 3D crystal editor, clickable missing-input navigation, saved spectra/fields/modes and model-specific result exports remain available. Each solver retains its documented geometry, boundary-condition and physical-model limits.

## Verification and unresolved scientific limits

The source audit exercised **all 29 chooser destinations**, recorded actual numerical execution for **28 study/tool scenarios**, and ran **all 24 bundled paper cases**. The native S4 sweep check retained all four requested designs and 2,804 samples, exercised saved-data filters, and separately verified cancellation with partial data. A focused grid suite passed **58 tests**. Separate UI acceptance observed 28 distinct setup widgets, checked desktop/compact layouts, explicit transfers and results return paths, and found no remaining issues within that scope.

These are scoped execution/UI checks, not proof that every editable device is correct. The UI checks used real Qt widgets and mouse events with offscreen rendering; they do not substitute for native displayed-Windows testing or checks on the final packaged build. Fresh desktop, Legume, Sesame, Gmsh and Meep environments were exercised. MPB was discovered and verified, but a fresh standalone MPB installation was not exercised. This machine required local Python/WSL executable recovery during validation; that recovery is not a general Windows repair feature.

**No bundled paper case is marked as an accepted, converged reproduction by this audit.** All 24 produced comparison artifacts; four finite-PCSEL cases explicitly remain **unconverged**. Several other studies have no directly matched experimental reference, and passing a worker or a UI test does not establish scientific agreement.

- Fan's small-hole/narrow-resonance spectrum discrepancies remain unresolved. For the r/a = 0.20 S4 case, transmission RMSE was approximately **0.0702**, with maximum residual **0.6166**. Limited higher-basis probes did not remove the largest discrepancy; neither convergence nor a digitization-only explanation has been established.
- The Winn spectrum RMSE was approximately **0.227 dB**, not a power-fraction error. Other optical cases also failed their recorded tolerance checks; some scalar/transport cases have no established acceptance tolerance.
- An additional full-3D Meep/Fan comparison executed and saved 351 samples, but did not meet its device field-decay target and failed the passive-power range check. It is an unconverged result, not an accepted reproduction.
- Passive PCSEL modes, periodic-cell transport and averaged electrical-to-optical coupling do not establish full finite-device active-laser thresholds, output power or ring-contact behavior. Prescribed heating is not a validated coupled steady-state electrothermal solution.

Use the release's final build-validation record and checksums for the packaged application's verification scope. Source audit results must not be substituted for unperformed package checks. This release remains **Highly Experimental** and separate from the stable update channel.

## Verification of this packaged alpha.2 build

Fresh checks against the final release snapshot passed:

- **35 targeted source tests** and **34 packaging gate tests**, with no failures or skips.
- **8 focused checks in the compiled application**, including all **29 chooser destinations**, **28 distinct setup pages**, independent draft roundtrips and project reloads, explicit compatible transfers, and no unexpected panel windows during the observed chooser flows.
- A native S4 sweep retained exactly **4 requested designs and 24 spectrum rows**; saved-data analysis left the raw archive unchanged. A separate three-sample native CPU spectrum also passed.
- **7 real Windows startup/display checks**, covering initial maximized painting, restore/maximize, system commands and caption actions. These are separate from the offscreen UI checks.
- Both executables contain **106 required modules** and the reviewed **NumPy 1.26.4**. The native binary and all **73 corresponding S4 source hashes** match their manifest.

This is the **critical release** verification profile, not the complete installer/scientific acceptance matrix. The extended theme/field/phase, CAD/COMSOL export, machine-learning, AI-search and performance checks were not all repeated in this package. The full paper-physics suite and fresh optional-solver downloads were not repeated in the compiled application. See **VALIDATION.json** for the exact scope, source fingerprint and artifact hashes. The scientific limitations above still apply.
