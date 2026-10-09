# S4 Optical Studio — native desktop guide

The PyQt6 application uses one shared structure, the existing S4 solver and machine-learning backends, and the established saved-data format. Native controls, material selectors, scientific plots, and file dialogs operate in the desktop window. The 1.3.1 Windows x64 portable release includes its runtime; extract the complete ZIP and run Optical Design Studio.exe. Source setup is described below.

## Start on Windows

Use the same 64-bit Python 3.12 environment that runs this S4 code set. On the original workstation, the launchers select `anaconda3\envs\s4_updated\python.exe` when it is available.

1. Run `install_desktop_dependencies.cmd` once to install the desktop interface dependencies into that environment.
2. Run `launch_qt_gui.cmd` to open the desktop application. `launch_peak_gui.cmd` also opens the native desktop interface.
3. Keep the application source and required scientific runtime together. qt_app.py is the desktop entry point; app.py supplies shared application/backend code.

If your Python environment is elsewhere, set `S4_PYTHON` to its `python.exe` before running either installer or launcher. The desktop dependency installer adds the Qt and plotting packages; it does not replace the existing S4, numerical, or machine-learning environment. Keep `pcs_s4_runtime`, `ml_dependencies`, and the application source together.

The desktop dependency set is pinned to:

```text
PyQt6==6.8.1
PyQt6-Qt6==6.8.2
PyQt6-sip==13.12.0
pyqtgraph==0.14.0
colorama==0.4.6
```

These versions were exercised in the workstation's Conda environment. The pins also avoid the Qt 6.11 loader incompatibility observed in that environment. If Qt cannot load, rerun the desktop installer using the same Python interpreter as the launcher.

## Start on Linux

Use Python 3.12 and a graphical Linux desktop. The native S4 extension must be built for Linux; the supplied Windows extension cannot run there.

Install the prerequisites described in the main README: a C/C++ compiler, CMake, Python development headers, and LP64 OpenBLAS development files. From the extracted application directory, run:

```bash
bash setup_linux.sh
.venv/bin/python -m pip install -r requirements-desktop.txt
bash launch_qt_gui.sh
```

`setup_linux.sh` creates `.venv`, installs the calculation dependencies, and builds S4. For an existing Linux S4 environment, install `requirements-desktop.txt` there and set `S4_PYTHON` to that environment's Python executable. `bash launch_peak_gui.sh` also opens the native desktop interface.

For a GPU-enabled Linux build, the existing `bash setup_linux.sh --cuda` workflow requires a supported CUDA toolkit and compatible NVIDIA driver. The interface uses the same GPU settings and native implementation as the browser application. Windows execution and offscreen rendering were tested on the supplied workstation; Linux build and launch scripts are provided, but a native Linux desktop was not available for execution testing in this conversion.

## Appearance and navigation

Select **B Light**, **B Dark**, **Glass Light** or **Glass Dark** using the four theme cards in **Settings → Appearance** or **Menu → Appearance**. Settings uses side navigation, a color editor with swatches and hex values, and a live preview of the shared Structure. Each appearance uses the same layout and keeps its own customizable colors. Preferences, window geometry and the last selected page are remembered locally in `data_library/desktop_preferences.ini`.

In Structure, **Layer color** applies to the selected layer. **Preview opacity** applies to its material in every layer using that material: 100% is opaque and 0% is invisible in the geometry preview. Reset removes that material's override. Colors and preview opacity are saved with the project; opacity does not change refractive index, extinction coefficient, absorption or any solver input. The lattice diagram uses the applied shape and dimensions; its two-period span is labelled 2a.

Successful saves, loads, assignments, copies and exports appear as four-second notifications. Problems, solver warnings and ongoing progress remain visible. The fixed bottom Run and Stop controls do not move when panels or notifications change.

The rounded outer boundary is the application window; the area outside it belongs to Windows. Glass modes use Windows Desktop Acrylic to blur the actual desktop and application windows behind the main window while labels, controls and data remain sharp. Glass surface opacity changes panel transparency and the background tint without lowering whole-window opacity. B modes are opaque. Desktop Acrylic requires Windows 11 build 22621 or later. Windows can substitute a solid material based on transparency, accessibility, power or remote-session settings. Unsupported desktops and offscreen screenshots use a solid fallback; the app never draws simulated wallpaper. Maximized and fullscreen windows use the same theme with an opaque background to keep painting stable; restoring the window enables Acrylic again.

The top navigation contains seven pages:

| Page | Use it for |
| --- | --- |
| Structure | Build the unit cell, layer stack, air holes, and other material regions. |
| Materials | Import optical constants, enter values, inspect n/k curves, and reuse saved presets. |
| Simulation | Run S4 RCWA, MEEP FDTD or Δn sweeps; inspect Fields and Saved results through the nested tabs. |
| Simulation Sweep | Define parameter bounds or a target wavelength and search for verified high-Q designs. |
| AI Search | Train models, search candidates and verify designs with the solver. |
| Settings | Set appearance and colors, computation resources, GPU diagnostics and add-ons. |
| Help | Read illustrated guides, load the silicon example and inspect actual simulation results. |

Run and Stop stay in fixed positions in the bottom application bar. Optical power graphs display 0–100%; saved solver values and CSV files retain fractions. Live 2D graphs use PyQtGraph inside PyQt6, including Materials, RCWA, phase, MEEP, Δn, field maps and comparisons, saved results, sweeps and AI Search. The 3D field viewer uses native Qt rendering of the saved samples, surface meshes and phase vectors. Graph controls use compact icons with tooltips. Clicking the RCWA spectrum selects the nearest actual sample and updates the readout. Live graphs fill their panels independently of publication paper dimensions; publication exports retain the physical-size Matplotlib export path. All source spectrum samples remain available, including narrow peaks in long datasets. Drag the Structure model to rotate, scroll to zoom and click a layer to select it. Air-hole apertures remain clear so lower layers can be seen while rotating.

## Detailed scans

RCWA scans generate wavelength batches on demand and save ordered results in `spectrum.sqlite`. The full `results.csv` and optional `phase.csv` retain every calculated sample. The live plot uses a bounded overview that preserves response extrema; zooming into a small interval loads its exact samples. Clicking the plot and entering a sample number inspect the original values. CSV export includes the complete scan. Large CSVs from older runs receive a reusable display index without changing their source data.

Electric fields are calculated for every requested wavelength and angle in the spectrum workers. Each worker reuses its solved spectrum for the fields at that point, avoiding a second layer-mode solve. The configured CPU workers process complete spectrum/field samples in parallel; GPU modes retain their existing single GPU owner. Standalone field scans also reuse their geometry across samples. `fields/samples.sqlite` indexes completed samples without rewriting a growing list. The field selector loads records on demand; its Sample control can open any sample. Small runs also retain the legacy inline `samples.json` list. Keep the complete run directory together when moving or exporting results.

Dense field maps extract all retained Fourier harmonics once per depth plane and evaluate them at the original requested coordinates. The sampler corrects the grid origin, oblique-incidence phase and native magnetic-field convention, checks E and H against scalar S4 samples, and falls back to scalar sampling if validation fails. No Fourier orders or field points are removed. `field_diagnostics.json` reports the sampler, validation error, native plane/point call counts, solution reuse and total descriptor time. Identical internal layers with the same material and solver geometry share their layer modes, even when their thicknesses differ. Contour tracking labels horizontal runs instead of visiting every pixel's neighbors; it uses compiled labeling when SciPy is installed. It reuses shapes between thresholds whose pixel masks are identical while retaining every threshold and its lineage. Both paths preserve the original connectivity, labels and pixel shapes.

Checkpoints use bounded batches and a one-second flush interval while work advances, with a final flush on completion or cancellation. An abrupt system failure can lose the current uncommitted batch. Peak solver memory still depends on the Fourier basis, layer count, and spatial field resolution; raw field and contour data grow with the requested sampling detail.

## Build once and use the structure everywhere

Set the lattice in **Structure** and click **Apply lattice**. Select a layer from the stack or the **Layer** dropdown, which lists layer names in stack order. The dropdown also follows selection in the 3D viewer and updates after renaming, adding, moving or deleting layers. Choose its material, edit its finite thickness, and click **Apply layer**. Use **Advanced editing… → Layer** to rename it and **Apply layer edits** to commit that change. The first and last layers are semi-infinite media, so their thickness remains zero.

Use the layer actions to add, duplicate, move, or remove finite layers. **Repeat block** copies a selected stack of layers and its regions. The structure preview shows the selected layer from above and a section through the full stack. Circle dimensions are radii, ellipse dimensions are X/Y radii, and rectangle dimensions are full widths.

The applied structure supplies all other pages immediately. Optimization and field layer selectors refer to the current layer names; no import step is needed after an edit. Changes typed into an editor become part of the shared design only after its Apply action. A calculation uses a snapshot of the applied structure at its start, so it remains reproducible.

A small **Shared Structure updated** notification appears after an applied structure, material, or lattice change. It disappears after four seconds, or you can dismiss it with **×**. It does not move the page or interrupt typing. Repeated unchanged Apply actions and unrelated calculation settings do not trigger it.

Layer rows show the name, material, and dimensions on separate lines. Long values have full-detail tooltips. Preview labels that cannot fit a thin layer are available by hovering over its geometry. At narrower window widths, computation controls stack above results; forms wrap and tables scroll instead of compressing their text.

**Undo structure edit** returns to an earlier applied structure. Unsaved text in an individual editing control is not a project revision.

## Add and inspect materials

In **Materials → Import CSV**, select the wavelength unit used by the file before choosing it. The importer accepts `wavelength,n,k` columns and separate n/k sections from refractiveindex.info. Enter the specific dataset page or other source information so it travels with the saved material. Units are explicit and are never inferred.

Each successfully imported material is immediately added to the project's material selectors and saved as a permanent library preset. Original uploaded data are retained. Files containing n without k require the explicit missing-k checkbox before a lossless assumption is used. Invalid input leaves the current project materials unchanged.

**Enter values** accepts at least two wavelength samples. Paste three tab- or comma-separated columns into the value table with the paste button, or type the values directly. Choose **Constant n,k (explicit approximation)** only for deliberately wavelength-independent values.

**Inspect** plots n and k from a project material, built-in approximation, or saved preset. Tabulated data use their saved wavelength range; constant approximations use the displayed start and stop wavelengths. Adding a preset with the same name as a different project material gives it a distinct name. A material used by any layer or region cannot be removed until those uses are changed.

The material library uses searchable cards and Project / Library / All scopes. Select **n & k**, **n only**, or **k only** above the plot. For a table, **Wavelength range** changes the graph's display limits; table values remain original samples and the complete CSV retains every measured sample. The curve between samples follows the selected interpolation. **Linear** interpolates n and k linearly. **Linear (in log k)** keeps n linear and interpolates log(k); every k sample must be strictly positive. This choice affects actual S4 optical constants and MEEP dispersion fitting and is saved with the project and material preset. Constants have no interpolation policy.

**Display color** changes the selected material's color in the library, Structure and Settings preview; a layer's explicit color takes priority. **Preview opacity** controls the material's visibility in the geometry preview. These two display controls do not alter optical data. **Notes** preserve your exact multiline text with the project and can be saved with a library preset. Source attribution remains separate. Changes autosave; a failed save keeps the note draft available for retry. Use **Apply material to layer** to assign the selected real material without changing layer dimensions.

## Optimize and track electric fields

Choose the parameter and the layer or region to vary, then save its allowed minimum, maximum, and sampling step. These bounds apply to the shared Structure. Target design search accepts the desired wavelength, its tolerance (default ±5 nm), the minimum Q factor, and the allowed hole shape and size for each PCS layer.

The target workflow retains the existing requirement for absorption above 99%, the requested wavelength/Q constraints, and fabrication checks including the strict circular-hole `r/a < 0.6` condition. The recommended result is the best verified eligible design found among the evaluated candidates. A finite machine-learning search does not certify a global maximum over all continuous designs. Review the saved spectra and verification results before treating a narrow peak as resolved.

Electric-field calculations use the same structure and computation settings. Compare two saved field snapshots in **Simulation → Fields** by selecting the reference, comparison, and a common XY layer. You can step between saved designs and switch between physical and layer-relative coordinates. All comparison panels share one intensity scale.

Map axes retain saved physical coordinates in µm. XY uses equal X/Y scale. The full-stack XZ pane can stretch vertically to fit a deep stack; read physical lengths from its ticks. The 3D field viewer preserves physical proportions.

The comparison reports field overlap, confinement changes, and centroid displacement. Optional arrows show local time-averaged energy-flow direction. Confinement here integrates `|E|²`; it is not a dispersive stored-energy calculation. Changing wavelength or switching resonance branches can also change the field pattern, so compare the displayed conditions alongside the maps.

The desktop interface does not make every computation GPU-only. The native solver accelerates eligible matrix products and field calculations, while some S4 work and machine-learning fitting remain on the CPU. Use the diagnostic controls to verify that the selected device is actually being used.

## Autosave, reopen, and share

Applied structures, material changes, calculation settings, and saved search options are autosaved to `data_library/desktop_session.json`. Opening the desktop app restores that session when it is readable. Material tables referenced by the session are retained in the library. Use **Save project** to create an explicit portable project version with its optical constants; this also creates a Saved results entry.

The native interface reads the existing saved-work format directly. Previously saved browser projects, optimization design IDs, CSV data, field snapshots, and material presets do not require migration. In **Simulation → Saved results**, choose a saved run and then its original setup or an actual saved design to reopen it in the shared Structure. CSV previews show up to 5,000 rows; **Save complete CSV as…** copies the full result.

**Export whole library…** automatically saves a portable snapshot of the current applied structure before creating the ZIP. The backup includes all saved runs, material presets, and optical-constant tables. With **Include application source and bundled runtime** selected, it also contains the code set, platform launchers, requirement files, and supplied runtime/source folders. Extract the bundle before launching it, then install or build the dependencies needed by the destination system.

**Export selected saved run…** packages that run's saved data. **Import a library ZIP…** verifies and merges saved data and presets, retaining existing work. Imported code is not installed or executed, and the current desktop session is not overwritten by importing a library. Choose a project from the imported Saved results list when you want to use it.

Library exports/imports and calculations run in the background. The interface blocks overlapping library operations and calculations within the desktop session. Keep backups outside the working library directory. The local library is not an automatic synchronization service between computers.

## Command-line options and dependency licensing

The desktop entry point also accepts:

```text
python qt_app.py --theme light
python qt_app.py --project path/to/s4_project.json
python qt_app.py --library path/to/library
python qt_app.py --no-restore
```

`--no-restore` starts with the default structure for that launch. Normal applied edits still autosave. Use `--library` for an independent working collection.

PyQt6 is distributed under GPL v3 and a commercial license; the PyPI installation provides the GPL version. Riverbank describes both options on the [official PyQt6 6.8.1 package page](https://pypi.org/project/PyQt6/6.8.1/). Existing S4 and other bundled dependency notices remain in the code set and the release THIRD_PARTY_LICENSES directory. PyQtGraph 0.14.0 uses the MIT license and Colorama 0.4.6 uses BSD 3-Clause; their full notices are included with the release.
