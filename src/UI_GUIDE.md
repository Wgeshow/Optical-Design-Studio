# Optical Design Studio 1.3.1: quick guide

For the Windows portable release, extract the complete ZIP and run **Optical Design Studio.exe**. For source, use `launch_qt_gui.cmd` on Windows or `bash launch_qt_gui.sh` after Linux setup. The ready-to-run portable release targets Windows x64; source runs need their documented native runtime and dependencies.

| Tab | Use it to |
| --- | --- |
| **Structure** | Assemble the shared layer stack, lattice, holes, and material regions |
| **Materials** | Import, inspect, assign, and save optical materials |
| **Simulation** | Run S4 RCWA, MEEP FDTD, and Δn sweeps; open nested Fields and Saved results |
| **Simulation Sweep** | Explore bounded designs and target wavelengths |
| **AI Search** | Train models, propose designs, and verify them with the solver |
| **Settings** | Set appearance, storage, compute resources, and add-ons |
| **Help** | Read illustrated guidance and inspect the actual Silicon tutorial results |

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
