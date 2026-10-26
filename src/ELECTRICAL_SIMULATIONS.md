# Electrical simulations

Choose **Device Studio** at startup for the shared finite-device **Structure** canvas and **Simulation → Optical / Electrical / Coupled** mode bar. Each mode has complete setup sections; [DEVICE_STUDIO_GUIDE.md](DEVICE_STUDIO_GUIDE.md) documents all 20 sections. **Menu → Switch workspace…** changes to **Original Optical Studio** without discarding the applied project/settings or rerunning jobs. Original optical controls compile their layer/region tables, using one fundamental PC-pitch cell with one air hole when a PC array is active and the original lattice otherwise. They do not implicitly add canonical polygons, contact pads or arbitrary Device Studio crop settings. Both interfaces use the same project/library.

The shared builder's **Run simulation** applies the current inspector edits and opens the selected simulation workflow. Choose a mode card to change that workflow. An optical unit-cell run does not require a resolved full-device electrical mesh; electrical and coupled jobs validate their actual finite mesh when preparing the solve.

The editable-device Poisson solver uses NumPy and SciPy. The older fixed study models additionally require DEVSIM. Install the electrical requirements in the same Python 3.12 environment that launches the app:

```powershell
python -m pip install -r requirements-electrical.txt
python qt_app.py
```

DEVSIM needs a compatible native direct solver. Windows packaged builds reuse the supplied MKL runtime. A source installation can discover MKL beside Python, in its `Library/bin`, beside the executable, or on `PATH`; `DEVSIM_MATH_LIBS` can specify the runtime library explicitly. A missing runtime produces a saved job error. The optical workspace can still open without DEVSIM.

## Build an editable device

The combined workspace has a device tree on the left, linked top, cross-section and orbitable 3D geometry previews in the center, selected-object properties on the right, and electrical material shortcuts below the views. The default opaque dark palette uses the approved blue-toned mockup; light and Glass looks remain available in **Settings → Appearance**. Preview color and transparency affect display only.

1. Select the device outline to set its finite x/y dimensions and temperature. Add, rename, reorder, duplicate, enable/disable or delete layers in the tree. Each enabled layer has a physical thickness, electrical material and donor/acceptor densities.
2. Draw rectangles, circles, ellipses, polygons or square rings in the top view. Polygon vertices can also be entered as `[[x,y], ...]` in µm; finish a drawn polygon with Enter or a double-click. Coordinates, rotation, layer assignment, and a ring's inner and outer dimensions remain editable in the inspector. Choose **Material override** or **Void / subtract**, then **Apply selected object** to commit inspector changes. Later regions override earlier regions where they overlap.
3. Use **Photonic-crystal area…** to specify the patterned region's width, depth, center, unit-cell spacing and hole radius. Automatic fill fits complete cells inside this region, independently of the full device dimensions, and previews the actual hole count and unused edge margins. The generated holes remain editable. **Pattern array…** additionally supports manual x/y counts and pitches. **Extrude to layers…** copies a selected material or void footprint through the chosen layers. These are physical extruded regions; the editor does not import arbitrary STEP solids. **Import geometry…** reads a canonical device JSON or shape records, and **Export device…** saves the editable geometry document.
4. Add local doping regions and contacts. Each contact has a footprint, base voltage, selected layer/surface and either an ohmic reservoir or fixed-potential boundary. **Pick contact surface** links a preview selection to that assignment. Contacts must resolve exposed faces; use an actual void opening for access to a lower layer, or select an external side/bottom face. Contact footprints define electrical boundary conditions. **Optical contact metal** optionally assigns an optical material and thickness to an exterior top/bottom contact; its same footprint becomes an actual periodic scattering pad in Optical/Coupled runs. A square ring retains its open center. Contacts on a plane require matching optical thicknesses; buried/side optical pads are rejected. Electrical contacts remain ideal boundaries without a metal transport volume. An opaque backing reflector can use an assigned optical exit medium.
5. Use the shared selection to inspect all three geometry views before solving; **Section y** moves the XZ cut, and **Fit views** resets preview zoom. Enable **Show mesh preview**, select Mesh in the tree, set x/y cell counts and depth cells per layer, then **Validate device**. The validator checks the actual material/void masks, doping regions and contact-face intersections, including features that the selected mesh does not resolve.

The shared device and optical layer/shape tables update together. **Advanced periodic optical editor** retains the existing layer, lattice and repeat-table tools. Under **Simulation → Optical** or **Coupled**, enable **Use selected optical cell** and set its width/depth; Advanced controls its center. This selection does not resize the finite electrical device. The PC-area optical workflow uses one pitch cell with one air hole in both workspaces. Device Studio derives it automatically when no cell is configured; explicit disabled/oversized PC settings remain editable but must be corrected before running. Designs without PC metadata retain the full-footprint periodic-supercell choice. S4 repeats the prepared periodic cell rather than providing isolated finite-device optics. Outside patterns are excluded from a selected cell, and crossing patterns are clipped; crossing curves use a documented polygon approximation. Coupling uses conservative, solid-only averages of actual electrical mesh cells overlapping the optical selection, with fractional edge-cell weights. The electrical fields and terminal I–V/C–V retain the full device footprint. Device lengths are µm, z increases downward from the first enabled layer, carrier and doping densities are cm⁻³, and saved electrical volume coordinates are metres.

For example, a patterned p-Silicon layer above an n-Silicon film uses the Silicon electrical preset in both layers with separately edited acceptor/donor densities. A **Square ring** contact can define an exposed p terminal, with an n boundary on the film's exposed bottom surface. An Au reflector requires Au optical data and a corresponding optical region/layer; naming an electrical contact Au does not create an optical mirror or introduce a calibrated metal/semiconductor interface model.

## Electrical material library

GaAs, ITO, AlGaAs, Silicon and Air/void are preloaded as independent editable definitions. **Edit electrical material…** or **Manage / import…** exposes static permittivity, band gap, electron affinity, conduction/valence density of states, conductivity and DOS effective masses, electron/hole mobilities, intrinsic concentration, optional bulk carrier populations, and an optional fixed conductivity. Scientific notation is accepted. **Add custom**, **Duplicate**, **Import JSON** and **Export JSON** support user materials; library values, stable IDs, source records and notes are saved with the project.

Reference data include the [Ioffe AlGaAs parameter archive](https://www.ioffe.ru/SVA/NSM/Semicond/AlGaAs/basic.html), its [band structure models](https://www.ioffe.ru/SVA/NSM/Semicond/AlGaAs/bandstr.html), the [University of Colorado silicon parameter sheet](https://www.colorado.edu/ecee/sites/default/files/attached-files/sd_constants_sheet.pdf), and the original [ITO study used for the assumed effective mass](https://doi.org/10.1155/2013/408182). Each preset contains its property-specific sources and model limits. AlGaAs has an editable Al fraction; the approximate indirect branch above x=0.45 uses a separate DOS mass and conductivity mass. Reference models can update gap/DOS/intrinsic concentration with temperature or alloy fraction, while manual property overrides are retained. Mobilities remain editable constants.

The ITO density, mobility, static permittivity, mass, affinity and gap are explicitly labeled model assumptions for a starting film, not measured universal ITO properties. AlGaAs transport defaults are also estimates. Replace them with sample-specific data when quantitative transport or Drude changes matter. **Update values from reference model** explicitly restores the reference fields after manual edits.

Electrical materials link by name to actual optical materials in **Materials**. Custom nondispersive materials can instead specify optional constant optical n/k. Static electrical permittivity is never converted into an assumed optical refractive index. If a new electrical material has no optical assignment, optical/coupled runs request real n/k data before computing. The electrical-only model can still use its electrical properties.

## Choose the simulation workflow

| Workspace | Uses and saved outputs |
| --- | --- |
| **Simulation → Electrical** | Select **Editable device from Structure**, choose semiconductor carrier charge or charge-free dielectric/Laplace mode, the swept terminal and bias offsets, then run the finite-device electrical model. Optical work is disabled in this workflow. |
| **Simulation → Optical · S4 / Optical · FDTD** | Run the shared applied optical layers and patterns using their optical materials, lattice, wavelength, angle and polarization settings. No electrical carrier correction is applied. |
| **Simulation → Coupled** | Solve the editable electrical device and run voltage-dependent periodic S4 optics from its saved depth profiles. Set the material-reference convention, optical slicing and sampled peak/dip tracking window. |

The custom electrical solve includes a zero-offset reference and applies each requested offset to the selected terminal's base voltage. The Structure Run action applies current inspector edits and follows the selected simulation workflow; use the Electrical setup to configure a bias sweep and terminal studies. Selecting a page or material preset does not run a simulation.

The actual custom mesh is cell-centered, conservative finite volume: x/y faces span the finite footprint and z faces align with every enabled layer boundary. Material/void footprints, rings, polygons, doping masks and exposed contact faces are rasterized on this mesh, with harmonic interface permittivity in the Poisson fluxes. Narrow holes, ring bars and contacts require sufficient x/y resolution. Depth cells are assigned per layer, so different thicknesses produce nonuniform z spacing and control-volume sizes. The saved cell-volume array and mesh/feature/contact counts describe the computed mesh; a geometry preview alone does not establish mesh convergence.

Semiconductor mode uses parabolic-band Fermi–Dirac charge, fully activated dopants, affinity-rule band alignment and prescribed electron/hole reservoirs. Charge-free dielectric/Laplace mode ignores dopants and mobile carriers and solves the applied boundary voltages. The model omits carrier continuity, recombination, tunnelling, transient dynamics and calibrated traps. Conflicting voltages on distinct reservoirs of the same carrier type require a transport solver and are rejected instead of silently approximated.

## Optional terminal studies

The editable device supports **Calculate I–V · Ohmic conductivity estimate** and **Calculate C–V · electrode charge derivative**. These labels describe the implemented models:

- **I–V:** a low-field conductivity solve using the frozen zero-offset carrier populations and edited mobilities. It uses `σ = q(nμn + pμp)` unless the material supplies an explicit fixed-conductivity override, including zero. Zero-conductivity regions are open circuits; terminal currents and current-balance checks are saved. This estimate does not predict diode injection, junction transport or leakage.
- **C–V:** signed `dQelectrode / dVterminal` from actual saved electrode displacement charge, with the other applied terminal voltages fixed. Request at least three distinct bias states; endpoints use one-sided numerical derivatives. This electrostatic derivative omits transported reservoir charge, frequency response, carrier lifetime, series resistance and trap dynamics, so it is not a calibrated diode junction capacitance.
- **Measured curves:** optional measured I–V/C–V CSVs require `bias_V,current_A` or `bias_V,capacitance_F`. They are saved and displayed as separately labeled measured curves. They do not replace the physical model or establish its calibration automatically.

Refine the voltage spacing and spatial mesh before interpreting either derivative/current estimate quantitatively. Model names, assumptions and numerical warnings travel with the saved curve metadata.

## Inspect and export saved results

**Device results → Linked fields** reads the saved NPZ volume for the selected bias. Choose potential, |E|, Ex/Ey/Ez, electrons, holes, charge density, static permittivity or saved doping fields. XY and XZ views share a color range and nearest-grid probe with the orbitable 3D view. A click in either slice or a sampled 3D point updates the linked position; x/y/z controls choose the nearest stored sample. The readout reports that sample's actual coordinates, material/layer/contact identity when saved, and physical values. Missing quantities in older saved runs remain **Unavailable**.

The 3D view renders up to 10,000 actual saved grid samples and outlines the linked slice planes. It scales the axes independently for visibility and displays the sample count; this display sampling does not change solver data or exports. Drag to orbit and use the wheel to zoom. Positive quantities support logarithmic colors, with nonpositive values marked separately.

The dashboard also shows actual computed/measured I–V and C–V curves, mesh/check records, material sources, saved inputs and run summary. The surrounding Electrical/Coupled result tabs retain solid-area depth profiles, optical n/k, R/T/A, CSV data and sampled resonance shifts.

| Output | Contents |
| --- | --- |
| `electrical_summary.json` | Device, electrical library/evaluated properties, geometry, mesh identity, per-bias file paths, checks, assumptions and optional coupling/study metadata. |
| `custom_<bias>V.npz` | Actual x/y/z axes, potential, vector DC field, n/p, charge, permittivity, doping, identity masks and nonuniform control-volume measures. |
| `profile_<bias>V.npz` / `.csv`, `layers_<bias>V.json` | Solid-area depth averages and layer/material identity used by the results and optical coupling. |
| `electrical_iv.csv`, `electrical_cv.csv`, `electrical_study_summary.json` | Optional computed terminal curves, their model scope and checks; optional `measured_iv.csv` / `measured_cv.csv` preserve imported measured samples. |
| `electrical_index_changes.csv`, `electrical_optical_spectra.csv`, `electrical_features.csv` | Coupled n/k corrections, R/T/A and changes from the solved zero-offset reference, plus sampled peak/dip shifts when resolved. |

**Export volume NPZ** copies the selected saved dataset, **Export grid CSV** writes all actual grid samples with explicit SI coordinates and field units, and **Export VTK** writes a rectilinear grid using the true nonuniform coordinate axes, scalar/vector values and saved control-volume metadata. VTK values are point data at the stored cell-center samples; export does not invent a uniform mesh or interpolated cell values. **Export figure** saves the selected field slices or I–V/C–V plot. Source data, display sampling and numerical model scope remain distinct.

## Run the legacy study device

1. Open **Simulation → Electrical** and choose **Load device preset**. This replaces the applied structure, material tables, and wavelength settings with the study device. Save your current project first if you want to retain it.
2. Choose bias voltages, mesh level, and ITO settings. The preset uses **40 nm** ITO and a nominal **8 × 10²⁰ cm⁻³** electron concentration within the user's stated range. Density, sheet resistance, affinity, mass, and interface assumptions remain conditional inputs.
3. Run electrical profiles first, or enable the optical comparison. Optical coupling uses the current S4 wavelength, angle, polarization, and basis settings. Check the six layer mappings before running.
4. Inspect carrier, DC field, n/k, and R/T/A plots. Load a saved run folder to reopen its data, or open/export its CSV files.

The legacy electrical template is the contacts-only device from the study: a 100 × 100 µm semiconductor mesa, five layers of 50/150/20/150/50 nm, a 120 µm outer p ring with a 5 nm external clearance, and a U-shaped n contact on ITO. The periodic holes are homogenized for electrical charge and represented explicitly in the optical cell (444 nm pitch, 46 nm radius). SiO₂ and interconnect geometry are excluded. These fixed study models retain their geometry restrictions and reject mismatched optical layers. Choose **Editable device from Structure** to run custom layers, shapes, contacts and electrical materials instead.

## Models and optical conventions

**Contacts only / ITO sheet** retains the completed ideal-contact model. Its optional resistive sheet calculation uses a supplied measured current; it does not predict semiconductor current. **Explicit ITO** resolves its degenerate electron population in the 3D Poisson domain and the n pad contact. It remains an experimental model pending mesh convergence and interface calibration.

The two legacy modes use Fermi–Dirac statistics and prescribed flat quasi-Fermi reservoirs under reverse bias. They calculate electrostatic potential and carrier populations. They do not solve carrier continuity, leakage, quantum tunneling, heating, or calibrated interface traps. Their Poisson residual, Gauss balance, and mesh identity are saved with each state.

Legacy optical coupling averages the electrical solution across the active square, recovers solid semiconductor carrier densities from the homogenized volume fractions, and splits only mapped optical layers. Thickness and patterned regions are preserved. It applies complex free-carrier Drude changes, optional GaAs band filling/band-gap narrowing, and optional linear/quadratic electro-optic tensors. ITO corrections are relative to its nominal bulk population, since its reference optical table already includes carriers.

Editable-device coupling instead uses the actual solid-area averages at each saved depth and editable material masses/mobilities for the Drude correction. Its optical mapping requires matching finite thicknesses, distinct consecutive layers in the same order, and scalar optical reference data covering the full wavelength scan. Void patterns are preserved across the optical slices. Mixed solid materials in one electrical layer currently require material-specific optical averages and are rejected for coupled runs; their electrical-only calculation remains supported. Optional GaAs interband and electro-optic corrections retain the stated experimental conditions. Geometry that the selected optical backend cannot represent is rejected before a run.

Choose **0 V optical reference** if the selected optical tables describe the zero-bias carrier state; the correction subtracts the calculated zero-bias material response. Choose **undoped reference** for intrinsic GaAs data, as supplied by the preset. High-density interband extrapolation and the illustrative AlGaAs electro-optic coefficient are recorded explicitly. Sample n/k tables in the preset span 1100–1200 nm and identify their original datasets; they are not measured optical constants for the user's film.

The S4 comparison is a periodic optical solve driven by averaged 3D electrical profiles. Assigned exterior top/bottom optical contact pads scatter within that periodic cell; isolated finite-device/contact diffraction and lateral electrical variations are not resolved optically. Tensor jobs use native S4 because the eigenfree GPU solver accepts scalar permittivity. This choice is recorded for the job and leaves the saved global performance settings intact.

Optical slice count, electrical mesh, Fourier basis, and wavelength spacing require convergence checks for a quantitative resonance shift. The feature table tracks sampled peaks/dips within the chosen wavelength window; a coarse scan cannot establish a shift smaller than its spacing.

## Saved results and provenance

Each run saves the project and job inputs, electrical volumes/profiles, model parameters and assumptions, solver checks, and optical CSVs when enabled. Electrical settings and mappings travel with project JSON; material tables are embedded in portable projects. Result folders can be relocated and reopened. Packaging stages the private electrical solver package and material tables and collects DEVSIM plus its distribution metadata/licenses.

The legacy implementation snapshots the local electrical study's reference Fermi quadrature, finite-volume DEVSIM infrastructure, contacts geometry, and semiconductor optical laws. The editable-device implementation shares the reference Fermi quadrature and optical correction conventions while resolving the user's finite geometry through its own NumPy/SciPy finite-volume mesh. No experiment folder or fixed workstation path is needed at runtime. Dependencies include NumPy/SciPy and optional DEVSIM 2.11.0 (Apache 2.0) for the legacy models; the existing S4 runtime performs coupled optical solves. The legacy optical datasets are the study's sampled reference tables from the pinned refractiveindex.info database and Adachi's x=0.5 alloy dispersion.

## Verification status

Automated tests cover electrical material validation and overrides, device/optical synchronization, custom geometry and mesh masks, Poisson/charge checks, terminal-study scope, saved-result linking/probing, and exports. A Windows Qt usability run also exercised the actual desktop with mouse/keyboard events: two doped silicon layers, a drawn and arrayed nine-hole pattern, a p-side square ring, the n-side gold reflector, custom material creation/assignment/undo, Optical/Electrical/Coupled backend runs, linked probes, VTK export, and portable project save/reopen. The UI was rendered offscreen with Qt; these checks establish control behavior and saved geometry, not scientific mesh convergence or device calibration.
