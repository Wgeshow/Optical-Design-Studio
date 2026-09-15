# S4 Optical Studio: quick guide

Start the updated source with `launch_peak_gui.cmd` on Windows, or `bash launch_peak_gui.sh` after Linux setup. Restart an open application after updating its source. Older packaged EXEs retain their previous interface.

| Tab | Use it to |
| --- | --- |
| **Structure** | Assemble layers and add holes or material regions |
| **Materials** | Choose presets, import optical constants, and inspect n/k graphs |
| **Simulate** | Measure reflection, transmission and absorption |
| **Optimize** | Search within your design and optical requirements |
| **Fields** | Calculate field maps and compare saved designs |
| **Saved work** | Reopen results, save projects, and share a library |
| **Settings** | Set accuracy, runtime limits and compute resources |

## Build a multilayer structure

The **Structure preview** shows a top view of the selected layer and a side view through the stack. Choose one, three, or five periodic cells, and set the side-view Y position to move the cut through the holes. Colors identify materials; hovering shows geometry details. Zoom into either plot to inspect small features. The incident medium and substrate are semi-infinite and shown with finite display padding. This is a geometry preview; field intensity is calculated separately in **Fields**.

In **Structure**, select **Layer to edit**, choose its material, enter a name and thickness, then click **Apply layer**. The stack summary shows the applied design. Apply edits before switching layers, running a calculation or saving a project.

The applied Structure is shared by every new simulation, optimization, field map, and project save. The shared summary above the tabs identifies that stack. Layer and pattern dropdowns follow added, renamed, and removed layers automatically; importing a project again is unnecessary. Saved results retain the design that produced them until you explicitly reopen or apply one.

- The first and last layers are the incident medium and substrate. They represent semi-infinite media with zero recorded thickness. Add finite layers between them.
- **Add above / Add below** inserts a layer using the form's material and thickness. **Duplicate layer** copies the selected layer and its regions. Move finite layers up or down to reorder the stack.
- **Repeat a layer block** copies an inclusive range of finite layers. Select its first and last layers and the number of **Additional copies**. Copies are inserted after the original block with unique names and their regions intact. For example, two additional copies of A–B produce A–B–A–B–A–B.
- **Undo last structure edit** restores the preceding layer/region edit. It is a single-step undo; newly added material presets remain available. Loading or editing the structure elsewhere can invalidate that undo.
- Deleting a layer also removes its regions. Advanced tables remain available for bulk copy/paste; their geometry columns use µm.

Use **Holes and material regions in the selected layer** to choose a shape and fill material. Select Air for an air hole. Click **Add region** for a new region or **Apply region** to commit edits to the selected one. After duplicating a region, change its position to avoid placing both copies at the same coordinates.

| Shape | Size inputs |
| --- | --- |
| Circle | Radius |
| Ellipse | X and Y radii |
| Rectangle | Full X and Y widths |

**Dimension unit** switches the layer/region form between nm and µm and converts the displayed values without changing their physical size: 100 nm = 0.1 µm. Position uses the same unit; rotation uses degrees. Lattice inputs and optimization geometry ranges are separately labelled in µm. Wavelength controls use nm.

## Choose and inspect materials

Structure material dropdowns include project materials and saved presets. Selecting a preset and applying a layer or region adds that material to the project as needed. In **Materials → Choose materials**, **Add to this project** also makes a preset available in the project's material records. Removing a project material keeps its saved preset; materials still used by the structure cannot be removed.

For CSV data, open **Materials → Import CSV**, set the file's wavelength unit **before uploading**, and enter source/measurement information. Uploading adds a wavelength-dependent material to the project and saves its preset. Supported layouts include `wavelength,n,k` and separate `wl,n` / `wl,k` sections. An n-only file requires explicitly selecting k = 0. Units are never guessed.

Use **Enter n/k values** for manual wavelength samples. A constant n/k pair requires choosing **Constant n,k (explicit approximation)**. Use **Inspect n and k** to graph project materials or saved presets. **Save a material for future projects** lets you save an edited material by name with source notes; previous saved versions remain intact.

## Simulate and optimize

In **Simulate**, choose a wavelength or angle sweep, enter its range and step, select polarization, and click **Run simulation**. Results are fractions: absorption 0.99 means 99%. Full results and applied design conditions are saved automatically.

For a specific resonance, use **Optimize → Target wavelength**. Enter the target, wavelength tolerance (default **±5 nm**) and minimum Q. A layer with one existing air hole appears automatically with its current size as both limits. Choose a **PCS layer**, shape and minimum/maximum size, then click **Add / update layer hole** to save wider search limits. Changes in Structure update automatic limits; manually saved limits and removed ranges are preserved. **Reset hole ranges to current structure sizes** starts over from the applied holes. Existing hole positions, rotations, and other material regions are retained. Use **Explore designs** for layers with multiple air holes, selecting the specific pattern from its dropdown.

Qualification requires absorption **strictly above 99%**, a resolved peak within the target tolerance, minimum Q, fabrication bounds and higher-resolution agreement. Circle r/a must be below 0.6, and periodic holes must leave a positive bridge. Peak-center tolerance does not guarantee 99% absorption at the exact target wavelength. The recommendation is the highest verified Q **found** within the search, without a guarantee of the continuous global maximum. Use **Use verified design in Structure** to load it.

**Optimize → Explore designs** provides exhaustive, ML-assisted and hybrid searches over the wavelength range in Simulate. Choose **What can change?**, **Where?**, and its range or allowed-material dropdown, then **Add / update range**. Saved compatible spectra and field measurements can support target learning. More trials or finer sampling may be needed for narrow peaks.

For layer thickness or material ranges, **Where?** lists the current Structure layers. To edit a saved range, select it in **Existing range**, then **Load range into editor**. Load and Remove are disabled until a valid range is selected. Updating another row preserves the selection; deleted selections leave your form values intact and show guidance.

Renaming or deleting a manually bounded layer invalidates its old target name. Reenter those limits for the new layer name; the program does not guess which layer should inherit a manual range.

## Fields, saved work and settings

In **Fields → Current structure**, choose wavelength, layer and map detail, then calculate XY/XZ field maps. In **Compare saved fields**, select a reference and comparison design, then a shared layer. The slider browses designs in numeric order. Physical coordinates retain distances; layer-relative coordinates help compare changed geometry. Maps share an intensity scale, and the per-layer table reports overlap, confinement changes and centroid displacement. These are steady-state comparisons, not time propagation. Save a comparison to retain its maps, measurements and original field samples.

In **Saved work → Results library**, refresh, filter and select a run. Choose **Original setup** or a named saved design, then **Reopen in editor**. Preview spectra or download complete CSVs and run ZIPs. To resume an existing ML search, reopen its original setup and retain compatible settings and bounds. **Project files** saves/opens portable JSON with embedded optical tables. **Back up, share or import a library** exports all results and presets, optionally including the application, or imports another library's data.

In **Settings**, adjust Fourier basis, time limit and compute mode. Spectra and field calculations honor the selected CPU/GPU mode; ML fitting uses the CPU. **Check selected runtime** verifies an actual GPU calculation when a GPU mode is selected and reports completed GPU products and failures. The default GPU matrix threshold of 1024 can keep small calculations entirely on the CPU. **Use GPU for small matrices** changes that threshold to 1 for subsequent runs; this can be slower on small problems. Field results save acceleration counts and fallback warnings. Check convergence as basis and spectral resolution increase. See [TARGET_DESIGN_GUIDE.md](TARGET_DESIGN_GUIDE.md) for scientific limits and platform setup, and [DATA_LIBRARY_GUIDE.md](DATA_LIBRARY_GUIDE.md) for storage details.
