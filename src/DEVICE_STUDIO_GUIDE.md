# Device Studio and Original Optical Studio

At startup choose **Device Studio** or **Original Optical Studio**. These are two interfaces in the same application, using the same current project, settings and saved library. They are workspace choices, not release versions or separate installations.

**Menu → Switch workspace…** changes the interface later. Switching does not discard the applied project/settings or rerun a calculation. Applying an edit, opening another project and restoring a saved setup are separate actions.

**Remember my choice** is unchecked by default. Check it to reopen that interface automatically on later starts; **Switch workspace…** can open the choice again. Source startup accepts `--workspace ask`, `--workspace device`, and `--workspace original`. Workspace selection keeps the same projects, presets and saved library.

| Workspace | Main controls and calculation scope |
| --- | --- |
| Device Studio | Editable finite device, electrical materials/doping/contacts, linked geometry, independent Optical/Electrical/Coupled setup and saved results. |
| Original Optical Studio | Original optical layer/region tables and lattice, S4 spectrum and wavelength/angle scans, optical Fields, saved work, target/explore searches and AI tools. |

Original S4 and manual Fields use only the applied **optical layer/region tables**. An active PC area uses one fundamental PC-pitch cell centered on an actual air hole in those tables; otherwise the original lattice dimensions remain authoritative. Canonical finite-device polygon shapes, optional electrical-contact optical pads and arbitrary Device Studio crop settings are not added automatically. Add explicit finite optical metal layers/regions in the original editor when that optical structure is intended. Switching retains the canonical device; use Device Studio for its supported geometry and electrical/coupled calculations.

## Build and inspect a finite device

In Device Studio → **Structure**, set device width/depth, then add enabled layers. Each layer has thickness, electrical material and donor/acceptor concentrations. Draw rectangles, circles, ellipses, polygons or square rings, choose a parent layer and **Material override** or **Void / subtract**, then **Apply selected object**. Later overlapping regions take precedence.

The finite inspector's **Full width / diameter** stores a circle's diameter. Original optical circle/ellipse tables store radii. The PC-area dialog separately asks for **hole radius**. Positions/lengths are labelled in µm, thickness may be displayed in nm, angles are degrees and dopants/carriers are cm⁻³. Follow each control's label.

Local doping regions change densities in their footprint. Contacts define exposed top/bottom/side boundary footprints, base voltage and an ohmic reservoir or fixed potential. Actual mesh coverage must resolve their faces. Optional exterior top/bottom optical material and thickness add S4 scattering pads; electrical contacts remain ideal boundaries. A name such as “Au” alone does not create a reflector. Buried/side optical pad geometry is not supported.

The **Top XY**, **Cross-section XZ** and **3D** views share object selection. **Section y** moves the XZ cut. Drag to orbit; use fit/zoom controls to inspect dimensions and hole walls. The 3D menu provides **Studio lighting**, **Soft shadows**, **Surface reflections**, and **Hole and edge shading**. These are preview effects, not solved optical/electrical fields.

**Fit thin-film display proportions** helps thin layers remain visible. **Use equal physical axis scales** provides physical proportions; read lengths from labels. Camera, colors, opacity, shading, shadows and reflections do not change solver inputs.

## PC area, optical cell and electrical domain

**Photonic-crystal area…** defines its own rectangle, center, cell spacing and hole radius. Automatic fill fits complete cells within that PC area and shows the count and unused margins before applying. The full generated hole set remains editable. Reapplying fill replaces that area's generated members. **Pattern array…** instead uses explicit row/column counts and pitch.

For a **150 µm** device and **100 µm** square PC area with **0.45 µm** pitch, 222 × 222 complete cells fit in the PC area: **49,284 holes**. The unused margins are centered. The remaining device area is not automatically perforated. Dense previews may sample drawing/labels for responsiveness; geometry and exports retain all objects.

The optical domain is a separate setting:

- **Selected periodic unit cell:** set width/depth and center. When an active PC area has no configured optical cell, Device Studio defaults to its pitch and centers the cell on one actual enabled air hole. **Use PC lattice size** copies this spacing and chooses an existing hole near the PC center, including even-sized arrays.
- **Full footprint — periodic supercell:** this remains available for custom periodic designs without an active PC area. A PC optical run uses one pitch cell with one air hole; an explicit disabled/oversized PC selection remains stored but must be corrected in **Domain & solver** before running.
- **Electrical:** always uses the full finite device and its contacts, regardless of the optical selection.

Both workspaces use one pitch cell with one air hole for the PC-area optical workflow. Original Optical Studio crops its table patterns to that PC cell without adding Device Studio contact pads or polygons. S4 always repeats the prepared periodic cell; its cell may contain other features in custom periodic designs, and it is not isolated finite-device diffraction. Outside patterns are excluded from the selected cell; crossing patterns are clipped and crossing curves use a recorded polygon approximation. Coupled selected-cell averages use actual solid electrical cells and fractional edge-cell overlap weights.

## Electrical and optical materials

**Materials → Electrical** includes editable GaAs, ITO, AlGaAs, Silicon and Air/void. Select a definition to inspect its saved/evaluated properties, source notes, assumptions and manual overrides. **Add custom**, **Duplicate**, **Import JSON** and **Export JSON** preserve stable material IDs.

Electrical properties include static εr, band gap, affinity, conduction/valence DOS, conductivity and DOS masses, mobilities, intrinsic/bulk populations and optional fixed conductivity. Units are explicit: eV, K, cm⁻³, cm²/(V·s), S/m and relative masses. An explicit conductivity of zero stays zero.

GaAs/AlGaAs reference laws use the Ioffe material archive. Silicon uses the Colorado parameter sheet and its recorded affinity/temperature sources. Reference gap/DOS/intrinsic values may vary with temperature/alloy fraction, while explicit edits remain overrides. Mobilities are editable bulk constants. ITO preset parameters and AlGaAs transport defaults are explicitly starting assumptions/estimates, not measurements of every film.

**Materials → Optical** remains the actual n/k dataset library. Electrical material names link to those optical entries; optional constant n/k is a stated approximation. Static electrical εr is never inferred to be optical ε or n. A missing optical assignment blocks Optical/Coupled; an electrical-only run can still use its electrical definition.

## All simulation setup sections

### Optical

| Section | Complete its settings |
| --- | --- |
| Overview | Study type, domain summary and requested outputs. |
| Domain & solver | S4 backend and selected periodic cell/full-footprint supercell; cell dimensions/center and clipping context. |
| Incident light | Polarization, θ and φ. s is perpendicular to the incidence plane; p lies in it. |
| Wavelength / angle sweep | Single wavelength, wavelength start/stop/positive step, or angle range/step with fixed wavelength; inspect actual sample count/last sample. |
| Materials & dispersion | Actual assignments, table coverage and interpolation. |
| Accuracy & execution | Fourier basis, CPU/GPU backend, workers/threads, chunks, timeout and supported diagnostics. |
| Outputs | Spectrum only, spectrum then fields, or optical fields only; phase request, saved/manual/extremum field selection, spatial/depth sampling. |

Optical-only does not solve electrical charge and does not require a valid finite electrical mesh. Spectrum stages save R/T/A power fractions; a fields-only job saves actual electromagnetic field samples without manufacturing a new spectrum. A failed field stage retains a completed preceding spectrum. New FDTD solver implementation is outside this update; existing optional FDTD controls and their prior restrictions remain.

### Electrical

| Section | Complete its settings |
| --- | --- |
| Overview | Editable finite device or explicitly fixed legacy study; scope and device summary. |
| Study & bias sweep | Study, swept terminal, range/manual offsets, zero-offset reference. |
| Contacts & boundaries | Enabled contact, base voltage, footprint/attachment and ohmic/fixed-potential boundary. |
| Materials & doping | Electrical assignment, donors/acceptors, local doping and evaluated parameters. |
| Temperature & charge | Temperature and semiconductor FD Poisson or charge-free dielectric/Laplace mode. |
| Finite device mesh | Nx/Ny, depth cells per enabled layer, total-cell budget and actual shape/contact coverage. |
| Outputs & measured data | I–V/C–V flags, initial saved-result display and optional measured CSV overlays. |

The swept terminal receives **base voltage + offset**; all other terminals keep their base voltages. Zero offset is always included; it is not necessarily zero applied voltage if a terminal has a nonzero base. The finite mesh spans all enabled layers; different layer thicknesses give nonuniform depth cells.

Semiconductor mode uses fully activated dopants, parabolic Fermi–Dirac charge, affinity-rule alignment and prescribed reservoirs. Equilibrium/reverse bias is supported; forward p/n or conflicting same-carrier reservoir voltages require continuity/transport and are rejected. Charge-free dielectric/Laplace ignores dopants/mobile carriers. Traps, recombination, tunnelling and transient transport are not added. Legacy study choices retain their fixed geometry/doping/temperature/runtime limits.

### Coupled

| Section | Complete its settings |
| --- | --- |
| Overview | Active shared Electrical/Optical summaries, references and state/sample counts. |
| Electrical setup | Complete shared Electrical editor; Run remains Coupled. |
| Optical setup | Complete shared Optical editor; Return to transfer returns to mapping. |
| Transfer & mapping | Zero-bias/undoped optical reference, stable layer mapping, selected-cell averaging and optical slices. |
| Response tracking | R/T/A, Peak/Dip, reference wavelength and tracking window. |
| Outputs & checks | Mandatory volumes/spectra/index/features, optional shared I–V/C–V and explicit unsupported-output policy. |

The order is finite Electrical → material/profile transfer → periodic S4 at the bias states → saved Results. Optical slicing does not refine electrical cells. Mappings require matching finite thickness, order and assigned optical data. Mixed solid materials in a layer need material-specific averages and are blocked for coupling; electrical-only remains usable.

Carrier Drude changes use editable conductivity masses/mobilities. Optional GaAs field/interband laws apply only to their stated supported conditions. Sampled peaks/dips may be absent; the program does not fabricate a resonance. Shared standalone phase/optical E/H requests are preserved but are unavailable in the coupled backend: choose supported coupled outputs explicitly, or require all requests and resolve the blocker. Use standalone Optical for phase/E/H.

## I–V, C–V and measured curves

- **I–V:** frozen zero-offset-carrier, low-field Ohmic conductivity estimate. σ=q(nμn+pμp), or an explicit fixed override including zero. Current-balance/power checks are saved. This is not diode injection, leakage or junction transport.
- **C–V:** signed electrostatic electrode displacement-charge derivative dQ/dV with other terminal voltages fixed. It requires at least three distinct bias states. Endpoint derivatives are one-sided; signed negative values are retained. Transported reservoir charge, AC frequency response and trap dynamics are absent.
- **Measured CSV:** `bias_V,current_A` or `bias_V,capacitance_F`, displayed separately as measured overlays. Import does not replace the physical calculation or automatically fit parameters.

Refine spatial mesh and voltage spacing to assess numerical convergence. The labels and model assumptions are saved with the curves.

## Results and complete exports

Loading a run inspects its immutable saved snapshot without replacing current geometry. Explicit restore/load setup changes the editor. Results categories are enabled according to actual files: **Overview**, **Potential & fields**, **Carriers & charge**, **Energy bands**, **Optical response**, **I–V / C–V**, **Mesh & convergence**, **Inputs & materials**, **Raw data & exports**, **Optical E/H**, and **Specular phase**.

Electrical XY/XZ/3D probes snap to stored coordinates and show the saved material/layer/contact identity and quantities. Missing quantities stay unavailable. Display point/row limits do not truncate complete data.

**Optical E/H** opens field-only jobs even without `results.csv`. Select a saved wavelength/angle sample, quantity and layer. Views are **XY / XZ maps**, **3D E/H playback**, and **Saved samples**. These are complex electromagnetic amplitudes with recorded S4 source normalization, not DC electrical V/m fields. Playback animates a harmonic phasor, not a travelling pulse.

**Specular phase** reads saved reflection/transmission amplitude phase. R/T/A power alone cannot reconstruct it; undefined or vanishing-signal phase stays unavailable. Spectrum/fields stages retain actual completion/error states and can be inspected separately.

Use **Export CSV / NPZ** for complete electrical-grid data, original electrical volume arrays, complete selected optical-field samples/arrays, full response/terminal curves or full phase CSV. **Export VTK** is for saved electrical volumes. Figure exports use the selected actual plot. Run folders/archives retain project/job snapshots, material provenance and solver checks.

## Presets, validation and menus

**Save setup** writes a named Optical, Electrical, Coupled or all-settings preset. **Load preset** previews changes and resolves contact/layer references before applying; it retains finite geometry. A portable project also contains geometry and materials.

Invalid input remains a visible draft rather than silently resetting. Mode switching preserves drafts. Standalone modes validate their relevant inputs; Coupled validates both shared setups. **Validate setup** routes each blocker to its edit section. **Run** snapshots applied inputs and starts without a second simulation confirmation. A busy application blocks another calculation; **Stop** requests cancellation and saved status distinguishes complete, failed and interrupted work.

The menu retains project actions, **Switch workspace…**, appearance/settings, saved work, refractive-index/carrier sweeps, field comparisons, target/explore searches and AI training/search. Opening a tool, selecting data or inspecting a material does not launch a solver. Existing optional GPU/CAD/FDTD runtime setup remains unchanged.

Input validation and a successful small test do not establish Fourier, mesh, voltage-step or wavelength convergence. Use actual comparison runs and sample-specific materials for quantitative device conclusions.
