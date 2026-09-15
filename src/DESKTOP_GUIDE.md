# S4 Optical Studio — native desktop guide

The PyQt6 application uses one shared structure, the existing S4 solver and machine-learning backends, and the same saved-data library as the browser interface. Its native controls, material selectors, plots, and file dialogs work without opening a browser.

## Start on Windows

Use the same 64-bit Python 3.12 environment that runs this S4 code set. On the original workstation, the launchers select `anaconda3\envs\s4_updated\python.exe` when it is available.

1. Run `install_desktop_dependencies.cmd` once to install the desktop interface dependencies into that environment.
2. Run `launch_qt_gui.cmd` to open the desktop application. `launch_peak_gui.cmd` also opens the native desktop interface.
3. Use `launch_web_gui.cmd` when you want the previous browser interface.

If your Python environment is elsewhere, set `S4_PYTHON` to its `python.exe` before running either installer or launcher. The desktop dependency installer adds the Qt packages; it does not replace the existing S4, numerical, or machine-learning environment. Keep `pcs_s4_runtime`, `ml_dependencies`, and the application source together.

The desktop dependency set is pinned to:

```text
PyQt6==6.8.1
PyQt6-Qt6==6.8.2
PyQt6-sip==13.12.0
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

`setup_linux.sh` creates `.venv`, installs the calculation dependencies, and builds S4. For an existing Linux S4 environment, install `requirements-desktop.txt` there and set `S4_PYTHON` to that environment's Python executable. `bash launch_peak_gui.sh` opens the desktop interface; `bash launch_web_gui.sh` opens the browser interface.

For a GPU-enabled Linux build, the existing `bash setup_linux.sh --cuda` workflow requires a supported CUDA toolkit and compatible NVIDIA driver. The interface uses the same GPU settings and native implementation as the browser application. Windows execution and offscreen rendering were tested on the supplied workstation; Linux build and launch scripts are provided, but a native Linux desktop was not available for execution testing in this conversion.

## Appearance and navigation

Select **Dark mode** or **Light mode** in the sidebar. The selection is remembered after closing the application, and the native charts change with it. Window geometry and the last selected page are also remembered locally in `data_library/desktop_preferences.ini`.

The sidebar contains seven pages:

| Page | Use it for |
| --- | --- |
| Structure | Build the unit cell, layer stack, air holes, and other material regions. |
| Materials | Import optical constants, enter values, inspect n/k curves, and reuse saved presets. |
| Simulate | Calculate spectra for the currently applied structure. |
| Optimize | Define parameter bounds or a target wavelength and search for verified high-Q designs. |
| Fields | Generate and compare electric-field maps for saved designs. |
| Saved work | Reopen projects and designs, inspect result tables, and share the library. |
| Settings | Select computation resources and inspect GPU diagnostics. |

## Build once and use the structure everywhere

Set the lattice in **Structure** and click **Apply lattice**. Select a layer from the stack, choose its material, edit its name or thickness, and click **Apply layer**. The first and last layers are semi-infinite media, so their thickness remains zero.

Use the layer actions to add, duplicate, move, or remove finite layers. **Repeat block** copies a selected stack of layers and its regions. The structure preview shows the selected layer from above and a section through the full stack. Circle dimensions are radii, ellipse dimensions are X/Y radii, and rectangle dimensions are full widths.

The applied structure supplies all other pages immediately. Optimization and field layer selectors refer to the current layer names; no import step is needed after an edit. Changes typed into an editor become part of the shared design only after its Apply action. A calculation uses a snapshot of the applied structure at its start, so it remains reproducible.

A small **Shared Structure updated** notification appears after an applied structure, material, or lattice change. It disappears after four seconds, or you can dismiss it with **×**. It does not move the page or interrupt typing. Repeated unchanged Apply actions and unrelated calculation settings do not trigger it.

Layer rows show the name, material, and dimensions on separate lines. Long values have full-detail tooltips. Preview labels that cannot fit a thin layer are available by hovering over its geometry. At narrower window widths, computation controls stack above results; forms wrap and tables scroll instead of compressing their text.

**Undo structure edit** returns to an earlier applied structure. Unsaved text in an individual editing control is not a project revision.

## Add and inspect materials

In **Materials → Import CSV**, select the wavelength unit used by the file before choosing it. The importer accepts `wavelength,n,k` columns and separate n/k sections from refractiveindex.info. Enter the specific dataset page or other source information so it travels with the saved material. Units are explicit and are never inferred.

Each successfully imported material is immediately added to the project's material selectors and saved as a permanent library preset. Original uploaded data are retained. Files containing n without k require the explicit missing-k checkbox before a lossless assumption is used. Invalid input leaves the current project materials unchanged.

**Enter values** accepts at least two wavelength samples. Paste three tab- or comma-separated columns into the value table with the paste button, or type the values directly. Choose **Constant n,k (explicit approximation)** only for deliberately wavelength-independent values.

**Inspect & manage** plots n and k from a project material, built-in approximation, or saved preset. Tabulated data use their saved wavelength range; constant approximations use the displayed start and stop wavelengths. Adding a preset with the same name as a different project material gives it a distinct name. A material used by any layer or region cannot be removed until those uses are changed.

## Optimize and track electric fields

Choose the parameter and the layer or region to vary, then save its allowed minimum, maximum, and sampling step. These bounds apply to the shared Structure. Target design search accepts the desired wavelength, its tolerance (default ±5 nm), the minimum Q factor, and the allowed hole shape and size for each PCS layer.

The target workflow retains the existing requirement for absorption above 99%, the requested wavelength/Q constraints, and fabrication checks including the strict circular-hole `r/a < 0.6` condition. The recommended result is the best verified eligible design found among the evaluated candidates. A finite machine-learning search does not certify a global maximum over all continuous designs. Review the saved spectra and verification results before treating a narrow peak as resolved.

Electric-field calculations use the same structure and computation settings. Compare two saved field snapshots in **Fields** by selecting the reference, comparison, and a common XY layer. You can step between saved designs and switch between physical and layer-relative coordinates. All comparison panels share one intensity scale.

The comparison reports field overlap, confinement changes, and centroid displacement. Optional arrows show local time-averaged energy-flow direction. Confinement here integrates `|E|²`; it is not a dispersive stored-energy calculation. Changing wavelength or switching resonance branches can also change the field pattern, so compare the displayed conditions alongside the maps.

The desktop interface does not make every computation GPU-only. The native solver accelerates eligible matrix products and field calculations, while some S4 work and machine-learning fitting remain on the CPU. Use the diagnostic controls to verify that the selected device is actually being used.

## Autosave, reopen, and share

Applied structures, material changes, calculation settings, and saved search options are autosaved to `data_library/desktop_session.json`. Opening the desktop app restores that session when it is readable. Material tables referenced by the session are retained in the library. Use **Save project** to create an explicit portable project version with its optical constants; this also creates a Saved work entry.

The native interface reads the existing saved-work format directly. Previously saved browser projects, optimization design IDs, CSV data, field snapshots, and material presets do not require migration. In **Saved work**, choose a saved run and then its original setup or an actual saved design to reopen it in the shared Structure. CSV previews show up to 5,000 rows; **Save complete CSV as…** copies the full result.

**Export whole library…** automatically saves a portable snapshot of the current applied structure before creating the ZIP. The backup includes all saved runs, material presets, and optical-constant tables. With **Include application source and bundled runtime** selected, it also contains the code set, platform launchers, requirement files, and supplied runtime/source folders. Extract the bundle before launching it, then install or build the dependencies needed by the destination system.

**Export selected saved run…** packages that run's saved data. **Import a library ZIP…** verifies and merges saved data and presets, retaining existing work. Imported code is not installed or executed, and the current desktop session is not overwritten by importing a library. Choose a project from the imported Saved work list when you want to use it.

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

PyQt6 is distributed under GPL v3 and a commercial license; the PyPI installation provides the GPL version. Riverbank describes both options on the [official PyQt6 6.8.1 package page](https://pypi.org/project/PyQt6/6.8.1/). Existing S4 and other bundled dependency notices remain in the code set and `third-party-licenses` directory.
