# Optical Design Studio 1.3.2: quick guide

For the Windows portable release, extract the complete ZIP and run **Optical Design Studio.exe**. For source, use `launch_qt_gui.cmd` on Windows or `bash launch_qt_gui.sh` after Linux setup. The ready-to-run portable release targets Windows x64; source runs need their documented native runtime and dependencies.

At startup, **Choose a simulation** opens the setup you select. Search by name or filter by family: Optical, Photonic crystals, Electrical & heat, PCSEL, or Paper library. Selecting a simulation opens its editor; it does not start a calculation. The persistent **Choose simulation** button reopens the chooser. **Remember my choice** can reopen the selected simulation on the next normal launch.

The chooser has 28 simulation/tool entries and a Paper comparisons library, including separate DC, I–V, C–V, 1D/2D semiconductor, 3D/2D MPB and 2D Legume setups and each PCSEL model. Icons identify the model families. Each selected type has its own device and parameters. Its name remains visible above the editor, and **Simulation**, **Results**, **Check inputs** and **Run** follow that selection. Returning from Settings restores the selected simulation. To reuse a structure, choose **Transfer inputs**, select a source, and review the compatible inputs before copying them into the active simulation. Switching types alone does not copy inputs. A legacy electrical model must be changed explicitly before an editable-device I–V or C–V run.

Simulation setup uses a structure/object list, a large native preview and an editable parameter inspector. The step buttons group the work; section selectors and **More** retain access to every original and advanced control. On a compact window, the **Settings**, **Device/Structure**, and **Objects** views give each area usable space. Optical table tools open the original optical structure editor; finite-device tools open the shared device editor. Geometry and material editing remain separate from preview display settings.

PCSEL previews offer **3D**, **Top**, and **Cross-section**, selected-layer isolation and neighboring cell copies. Picking a displayed object selects its editable source. The preview's nanometre-to-micrometre conversion and repeated cells are display-only; they do not rewrite the solver geometry. High-field and lumped-rate diagrams are explicitly illustrative model diagrams rather than computed fields.

The chooser's **Workspaces** tab still offers **Device Studio** for editable finite-device geometry, Optical/Electrical/Coupled setup, electrical materials and linked saved results, and **Original Optical Studio** for the original optical layer/region tables, S4 scans, Fields, saved work and searches. Switching workspaces keeps the applied project and settings. Both workspaces belong to the same application/library.

See [DEVICE_STUDIO_GUIDE.md](DEVICE_STUDIO_GUIDE.md) for the new 20-section setup, PC-area/cell distinction, contacts/doping, shaded previews, I–V/C–V model scope, presets and complete exports. Original S4/manual Fields compile the optical layer/region tables. An active PC area uses one PC-pitch cell with one air hole; other designs keep the original lattice. Canonical polygons/contact pads and arbitrary Device Studio crop settings are not added automatically. The original optical controls remain documented below.

| Tab | Use it to |
| --- | --- |
| **Structure** | Assemble the shared layer stack, lattice, holes, and material regions |
| **Materials** | Import, inspect, assign, and save optical materials |
| **Simulation** | Run S4 RCWA, MEEP FDTD, and Δn sweeps; open nested Fields and Saved results |
| **Simulation Sweep** | Explore bounded designs and target wavelengths |
| **AI Search** | Train models, propose designs, and verify them with the solver |
| **Settings** | Set appearance, storage, compute resources, and add-ons |
| **Help** | Read illustrated guidance and inspect the actual Silicon tutorial results |

## Photonic Bands: build a fully 3D periodic crystal

**Photonic Bands** is a separate workspace with its own periodic unit cell and crystal objects. It does not replace the layer stack or finite electrical device. New band workspaces start in 3D; opening an existing 2D or custom project preserves its saved model.

1. **Unit cell.** Choose the crystal model and, optionally, enter **Reference scale a (nm)**. Use **Apply starting crystal** to load an editable example, or **Custom lattice vectors** for your own cell. The simple cubic example has one sphere of radius 0.25a and relative permittivity 12 in air; it is illustrative and does not promise a band gap. The diamond example uses an FCC primitive cell and two overlapping spheres of radius approximately 0.233345a and relative permittivity 16. For this example, a is the conventional cubic edge and each primitive lattice vector has length a/√2. Applying a starting crystal replaces the crystal objects, lattice and suggested wavevector path; it is an explicit action.
2. **Build crystal.** Add a sphere, block or finite cylinder, select it in the list or scene, and edit its position, size and material. Positions and dimensions are **Cartesian multiples of a**, not fractions along the lattice vectors. Block sizes are full edge lengths; cylinder height is the full length along its axis. For example, with a = 500 nm, a radius of 0.25a means 125 nm. Materials use real, positive, constant relative permittivity εr; for a nonmagnetic, lossless material, εr = n². The illustrative dielectric values are not wavelength-dependent material calibrations.
3. **Calculate.** A fully 3D crystal uses **MPB full-vector modes**; TE/TM separation applies only to the supported 2D models. Review the suggested wavevector sampling, number of bands and grid accuracy. Set up the solver installation and select **Check solver**, then use **Calculate bands** in the bottom bar. Solver setup can be remembered on this computer. Missing-input messages take you to the relevant control. Use **More → Customize wavevector sampling** for a different path, explicit points or a reciprocal-cell grid. Wavevector coordinates are fractional coordinates in the reciprocal basis, distinct from the Cartesian object coordinates.

The physical scale is optional: leave it blank to work entirely in normalized units. Entering a scale converts nanometres to the saved micrometre reference value; it does not rescale the authored coordinates or lattice vectors. Old projects retain their original definition of a, including paper comparisons that use a primitive-vector length rather than the conventional cubic edge. Normalized frequency is a/λ; a physical scale permits conversion to wavelength.

In the 3D scene, drag to orbit, scroll to zoom, Shift-drag to pan, or choose a standard view. **3 × 3 × 3 cells** shows neighboring copies and makes diamond connectivity easier to inspect. Repetition and camera settings affect only the preview. The scene shows editable primitive surfaces and cell edges, not a calculated field or a Boolean-resolved material volume; overlapping objects and embedded air regions can obscure interior boundaries. One-cell view shows the authored objects, so neighboring copies may be needed to inspect a boundary crossing.

Open **Results** for bands and sampled gaps. A gap on a finite path does not establish a complete three-dimensional band gap. Check both solver accuracy through **More → Convergence** and wavevector coverage, including interior reciprocal-cell samples where needed. The diamond starting crystal and paper benchmark remain editable, with their different normalization conventions stated separately.

## Choose a research simulation or paper setup

Use **Choose simulation** to change simulation types. Each research setup keeps its own editor, diagnostics and results, including separate PCSEL models and 1D/2D semiconductor transport. The original optical spectrum, time-domain optics, refractive-index sweep, fields/phase, electrical and coupled-device workflows remain available alongside Photonic Bands and the research models.

| Setup | How to use it |
| --- | --- |
| **Semiconductor transport** | Follow **Domain → Materials & contacts → Calculate**. Edit the 1D/2D nodes and regions, assign explicit material properties, contacts, generation and grain-boundary defects, then enter the bias sequence. The preview shows the authored geometry even before all material inputs are complete. |
| **Temperature & heat flow** | Follow **Device & power → Materials & cooling → Calculate**. Use the shared device, assign prescribed power, thermal conductivity and cooling boundaries. This is steady heat conduction; electrical heating and temperature feedback are separate transport options. |
| **Finite-contact transport** | Follow **Device → Physics → Calculate**. Open the shared geometry and material editors from the device step, choose the swept contact, and supply the bias sequence. Optional contact/interface resistance, recombination, heating, temperature feedback, tunnelling and high-field response require explicit coefficients and sources. |
| **High-field optical response** | Follow **Material → States → Calculate**. Enter material parameters, add electric-field/carrier states and choose wavelengths and integration accuracy. These are material-response samples; selecting this model does not imply a finite-device solution. |
| **PCSEL periodic transport** | Follow **Structure → Physics → Calculate**. Enter cell width/depth in µm, edit layers and inclusions, assign semiconductor materials, then configure bias, mesh and the Gmsh Python installation. Its top/bottom terminals cover full faces and lateral transport is periodic. |
| **PCSEL representative cell** | Use the shared editable device, contacts and transport physics. Its side faces are insulating; it is a different boundary model from periodic conformal transport. |
| **Laser rate equations** | Edit the existing lumped gain, recombination, optical-mode and thermal parameters for threshold, light–current and modulation calculations. This reduced model does not construct a spatial PCSEL crystal. |

The three step buttons choose a stage. The **Section** selector chooses a page within that stage. **More** retains advanced properties, exact settings and supporting pages; **Results** opens saved outputs. **Check inputs** lists missing or invalid values. Select an issue, or **Go to first missing input**, to reveal its owning control; **Back to issues** returns to the list. An issue for a removed object requires a new input check rather than selecting a different object.

### PCSEL optical and aperture setup

Each PCSEL optical model can be selected directly at startup or through **Choose simulation**. Its editor contains only that model's workflow. Switching to another PCSEL model preserves the current draft; **Transfer inputs** explicitly copies compatible structure inputs when needed:

| Model | Inputs and interpretation |
| --- | --- |
| **Vertical confinement** | Layer thicknesses and real refractive indices; calculates the vertical TE mode and confinement. |
| **Unit-cell coupling · CWT** | Patterned layers, circle/convex-polygon inclusions and coupling accuracy; uses a four-wave TE approximation. |
| **Slab modes · GME** | Editable wavevectors, guided-mode indices, reciprocal cutoff and mode count; uses a configured Legume installation. |
| **Resonance poles · RCWA** | Explicit complex-frequency seeds, search bounds, Fourier basis and field probes; searches resonances with S4. |
| **Finite-aperture modes** | Rectangular aperture width/height and collocation accuracy; imposes zero incoming basic waves. |
| **Far-field beam** | A calculated or compatible saved finite mode, angular sampling and normalization. Absolute emitted power requires an explicit calibration and source. |
| **Aperture carriers & heating** | Source-bound load calibration, contacts, carrier/rate, optical and thermal inputs. This reduced aperture model is not a new 3D drift-diffusion calculation. |

In **Structure**, select **Layer stack** or **Cell pattern**. **Add object** creates an editable layer, circle or polygon; select an object to edit its properties, move it or remove it. Optical layer thickness and lattice period use nm; inclusion positions, radii and vertices use multiples of the lattice period a. Finite aperture dimensions use µm. Conformal-transport geometry uses µm. **Apply cell pattern** selects which layers contain the inclusions. Use **3D**, **Top** and **Section** to inspect the authored geometry, isolate a selected layer or display repeated cells. These views show setup geometry; calculated fields and solver meshes are separate outputs.

**Editable starting structures** provides explicitly chosen recovered PCSEL decks or the illustrative homogeneous transport example. Loading one replaces that study's draft. Their availability does not establish agreement with a paper. New physical inputs remain blank until supplied; **All object properties** and the advanced pages retain additional saved properties.

### Paper comparisons, solver installations and saved drafts

**Paper comparisons** opens the searchable library of **24 paper setups**. Read the selected case's source, figure and limitations. **Open editable setup** copies it into the relevant editor, where geometry, material values and model settings can be changed. The original reference remains available. Device-based cases may use the project's replacement flow; follow its save prompt before replacing the active device. **Run original reference** executes the original case through the application's job system. Opening a case alone does not validate or run it.

For optional Python engines, enter the installation in **Solver setup** or **Runtime** and use **Check solver**. WSL needs an explicit absolute Linux Python path and distribution; local execution needs the appropriate Python environment. GME uses Legume, conformal transport uses Gmsh, and the semiconductor junction workflow uses Sesame. **Remember this installation** saves installation inputs on this computer; **Use saved installation** loads them into the study. A saved path is not a successful check, and a successful installation check is not numerical convergence. MPB installation remains in the separate Photonic Bands workspace.

Portable projects retain each study's editable draft, including incomplete number text, and its attached paper-reference identity. Changing visible sections or optical model choices does not discard hidden values. Fix incomplete inputs before running. Advanced property editors expose the same draft rather than a second copy of the device.

Use **Results** and its **Result view** selector for the available plots, tables, maps, comparison data and exact artifacts. Preserve the recorded completion, convergence, validity and comparison status when interpreting an output. Successful execution does not establish a complete band gap, calibrated laser power or paper agreement; missing quantities remain unavailable. Refine the appropriate spatial, spectral, wavevector, mesh or bias resolution for the selected model.

## Build a multilayer structure

Choose **B Dark**, **B Light**, **Glass Dark**, or **Glass Light** through **Menu → Appearance** or **Settings → Appearance**. The seven pages share the same layout and controls in each look. Glass uses Windows Desktop Acrylic to blur the actual desktop behind the window while controls and scientific data remain sharp. It requires Windows 11 build 22621 or later; Windows transparency, accessibility, power, and remote-session settings can substitute a solid material. Unsupported desktops and offscreen captures use a solid fallback. Windows title controls stay at the top right. Maximized and fullscreen windows use the same theme with an opaque background to keep painting stable; restoring the window enables Acrylic again.

In **Settings → Appearance → Interface colors**, choose colors or enter six-digit hex values for accent, background, panels, input fields, text, secondary text, and borders. Each look saves its own palette on this computer. **Reset colors** restores its defaults. **Glass surface opacity** adjusts the two glass looks. These UI preferences are separate from portable project data.

Select a layer from the stack or the named **Layer** dropdown. The dropdown follows geometry selection and the current stack order after renaming, adding, moving, or deleting layers. **Layer color…** chooses a display color and **Reset** removes its override. Layer colors are saved with portable projects and follow renamed or duplicated layers. **Preview opacity** controls the selected layer's material in every preview layer using it, from 100% opaque to 0% invisible; Reset removes the material override. These controls do not alter optical constants or solver inputs. The inspector includes applied lattice/pattern controls; **Advanced editing…** provides layer renaming and complete region/repeat tools.

Layer-list checkboxes control preview visibility. **Show holes**, **Layer colors**, **Edges**, and **Axes** control the geometry display; **Zoom − / Zoom +**, dragging, scrolling, and **Reset view** adjust the view. The **Geometry summary** shows applied lattice dimensions, the selected layer's single circular air-hole radius when applicable, finite-layer thickness/count, and patterned-layer count. Multiple circular holes show “Multiple”; other shapes show no radius. The Structure panels stack vertically in smaller windows.

Run and Stop remain fixed in the bottom bar. Brief notifications confirm successful actions; errors, warnings, and calculation progress stay visible. Electric fields and saved results are nested inside **Simulation**.

The **Geometry Viewer** offers **3D Stack**, **Cross-section**, and **Unit cell** views of the applied design. Choose one, three, or five periodic cells. Rotate the 3D view by dragging, scroll to zoom, or use the zoom and Reset view controls. Colors identify materials; hovering exposes geometry details. The incident medium and substrate are semi-infinite and shown with finite display padding. Geometry visibility does not remove physical solver geometry; field intensity is calculated separately in **Simulation → Fields**.

In **Structure**, choose a layer from the **Layer** dropdown, select its material, and edit its finite thickness before clicking **Apply layer**. Use **Advanced editing… → Layer** for a name change and **Apply layer edits** to commit it. The stack and Geometry summary show the applied design. Apply edits before switching layers, running a calculation, or saving a project.

The applied Structure is shared by every new simulation, optimization, field map, and project save. A brief Shared Structure updated notification confirms applied changes. Layer and pattern dropdowns follow added, renamed, and removed layers automatically; importing a project again is unnecessary. Saved results retain the design that produced them until you explicitly reopen or apply one.

- The first and last layers are the incident medium and substrate. They represent semi-infinite media with zero recorded thickness. Add finite layers between them.
- **Add above / Add below** inserts a layer using the form's material and thickness. **Duplicate layer** copies the selected layer and its regions. Move finite layers up or down to reorder the stack.
- **Repeat a layer block** copies an inclusive range of finite layers. Select its first and last layers and the number of **Additional copies**. Copies are inserted after the original block with unique names and their regions intact. For example, two additional copies of A–B produce A–B–A–B–A–B.
- **Undo** restores earlier applied structure edits, with up to 30 retained steps. Loading another project clears this history; newly added library material presets remain available.
- Deleting a layer also removes its regions. Advanced tables remain available for bulk copy/paste; their geometry columns use µm.

Open **Advanced editing… → Regions** to choose a shape and fill material. Select Air for an air hole. Click **Add region** for a new region or **Apply region** to commit edits to the selected one. After duplicating a region, change its position to avoid placing both copies at the same coordinates.

| Shape | Size inputs |
| --- | --- |
| Circle | Radius |
| Ellipse | X and Y radii |
| Rectangle | Full X and Y widths |

**Dimension unit** switches the layer/region form between nm and µm and converts the displayed values without changing their physical size: 100 nm = 0.1 µm. Position uses the same unit; rotation uses degrees. Lattice inputs and optimization geometry ranges are separately labelled in µm. Wavelength controls use nm.

## Choose and inspect materials

Structure material dropdowns include project materials and saved presets. Selecting a preset and applying a layer or region adds that material to the project as needed. In **Materials**, **Add to project** also makes a preset available in the project's material records. Removing a project material keeps its saved preset; materials still used by the structure cannot be removed.

For CSV data, open **Materials → Import CSV**, set the file's wavelength unit **before uploading**, and enter source/measurement information. Uploading adds a wavelength-dependent material to the project and saves its preset. Supported layouts include `wavelength,n,k` and separate `wl,n` / `wl,k` sections. An n-only file requires explicitly selecting k = 0. Units are never guessed.

Use the inspector's **Enter values** tab for manual wavelength samples. A constant n/k pair requires choosing **Constant n,k (explicit approximation)**. **Inspect** graphs project materials or saved presets, with **n & k**, **n only**, and **k only** modes. The Project / Library / All scopes filter searchable material cards. **Save to library** stores a reusable preset; source attribution stays separate from editable Notes, and previous saved versions remain intact. Linear interpolation is the default. **Linear (in log k)** requires strictly positive k samples and affects S4/MEEP material evaluation, while n stays linear. Display color and preview opacity affect geometry display only.

## Simulation and Simulation Sweep

In **Simulation → S4 · RCWA**, choose a wavelength or angle sweep, enter its range and step, select polarization, and use **Run** in the bottom bar. Raw results are fractions: absorption 0.99 means 99%; optical power graphs display percentages. Full results and applied design conditions are saved automatically. Live scientific plots use native Qt rendering with Fit, Pan, Zoom, Copy, Export, and Figure settings controls; publication exports retain physical-size settings.

For a specific resonance, use **Simulation Sweep → Target wavelength**. Enter the target, wavelength tolerance (default **±5 nm**) and minimum Q. A layer with one existing air hole appears automatically with its current size as both limits. Choose a **PCS layer**, shape and minimum/maximum size, then click **Add / update layer hole** to save wider search limits. Changes in Structure update automatic limits; manually saved limits and removed ranges are preserved. **Reset hole ranges to current structure sizes** starts over from the applied holes. Existing hole positions, rotations, and other material regions are retained. Use **Explore designs** for layers with multiple air holes, selecting the specific pattern from its dropdown.

Qualification requires absorption **strictly above 99%**, a resolved peak within the target tolerance, minimum Q, fabrication bounds and higher-resolution agreement. Circle r/a must be below 0.6, and periodic holes must leave a positive bridge. Peak-center tolerance does not guarantee 99% absorption at the exact target wavelength. The recommendation is the highest verified Q **found** within the search, without a guarantee of the continuous global maximum. Use **Use verified design in Structure** to load it.

**Simulation Sweep → Explore designs** provides exhaustive, ML-assisted and hybrid searches over the wavelength range configured in Simulation. Choose **What can change?**, **Where?**, and its range or allowed-material dropdown, then **Add / update range**. Saved compatible spectra and field measurements can support target learning. More trials or finer sampling may be needed for narrow peaks.

For layer thickness or material ranges, **Where?** lists the current Structure layers. To edit a saved range, select it in **Existing range**, then **Load range into editor**. Load and Remove are disabled until a valid range is selected. Updating another row preserves the selection; deleted selections leave your form values intact and show guidance.

Renaming or deleting a manually bounded layer invalidates its old target name. Reenter those limits for the new layer name; the program does not guess which layer should inherit a manual range.

## Fields, saved results, and Settings

In **Simulation → Fields → Current structure**, choose wavelength, layer and map detail, then calculate XY/XZ field maps. In **Compare saved fields**, select a reference and comparison design, then a shared layer. The slider browses designs in numeric order. Physical coordinates retain distances; layer-relative coordinates help compare changed geometry. Maps share an intensity scale, and the per-layer table reports overlap, confinement changes and centroid displacement. These are steady-state comparisons, not time propagation. Save a comparison to retain its maps, measurements and original field samples.

In **Simulation → Saved results**, refresh, filter and select a run. Choose **Original setup** or a named saved design, then **Reopen in editor**. Preview spectra or download complete CSVs and run ZIPs. To resume an existing ML search, reopen its original setup and retain compatible settings and bounds. **Project files** saves/opens portable JSON with embedded optical tables. **Back up, share or import a library** exports all results and presets, optionally including the application, or imports another library's data.

Set Fourier basis in **Simulation → S4 · RCWA**. In **Settings → Performance**, adjust the time limit and compute mode. Spectra and field calculations honor the selected CPU/GPU mode; ML fitting uses the CPU. **Check selected runtime** verifies an actual GPU calculation when a GPU mode is selected and reports completed GPU products and failures. The default GPU matrix threshold of 1024 can keep small calculations entirely on the CPU. **Use GPU for small matrices** changes that threshold to 1 for subsequent runs; this can be slower on small problems. Field results save acceleration counts and fallback warnings. Check convergence as basis and spectral resolution increase. See [TARGET_DESIGN_GUIDE.md](TARGET_DESIGN_GUIDE.md) for scientific limits and platform setup, and [DATA_LIBRARY_GUIDE.md](DATA_LIBRARY_GUIDE.md) for storage details.

Glass opacity accepts the full 0–100% range. Lower values clear the workspace and panel tint while labels and input controls remain readable. Saved maximized or fullscreen windows establish a normal native paint before restoring their saved state, preserving visible startup content.
