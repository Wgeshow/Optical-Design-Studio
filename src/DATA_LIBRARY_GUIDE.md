# Saved results and user material presets

Start this source version with **launch_peak_gui.cmd**. Previously built EXEs do not contain this update. Restart an already-running GUI after updating the code.

## Automatic CSV import and material plots

In **Materials → Import CSV**, select **Wavelength unit in the file** before uploading. Your
`AlGaAs50.csv` example uses the existing nm setting (800–2000 nm). Direct
refractiveindex.info exports commonly use micrometres: select **um** for those.
The unit is always an explicit input, never inferred from the numeric scale.

Uploading now automatically adds a wavelength-dependent material to the table
and saves/selects its preset. The filename becomes the material name, or you can
enter a name for a single upload. A matching name updates that row in the current
structure; previous saved versions and completed runs remain intact. Use
**Import selected files again** after correcting the unit, name or
missing-k option. Uploading identical data again reuses its saved preset.

Supported layouts are three columns `wavelength,n,k`, or the site's separate
`wl,n` and `wl,k` sections. Separate grids are linearly interpolated onto their
shared wavelength interval; the importer does not extrapolate one section beyond
the other. Files containing only n require supplied k data or an explicit
**Missing k = 0** choice. Zero extinction is a lossless assumption, not inferred
measurement data. The original CSV is preserved alongside the canonical table.

Under **Materials → Enter n/k values**, type or paste wavelength,
n and k samples and click **Save material to project and library**. At least two
distinct wavelengths are required. To use a single n/k pair, explicitly choose
**Constant n,k (explicit approximation)** and fill both values. New blank
material rows default to `table_nk`; built-in presets retain their explicitly
marked constant approximations. Dataset URLs, references and conditions are
entered manually and retained in preset notes.

Open **Materials → Inspect n and k** and select a material from
its dropdown. It can inspect current table rows or saved presets. Selecting the
main preset dropdown also selects that preset for plotting. n and k have
separate axes so small loss values remain visible. The plot uses every sample;
the numeric preview shows at most 5,000 rows. Constant approximations appear
as horizontal lines over the entered display range. Use **Refresh material
graph** after editing values or the display range. All plotted wavelengths are
shown in nm; imported um data is converted to nm for permanent storage.

Data source supplied by the user: [refractiveindex.info](https://refractiveindex.info/).
The code reads uploaded or manually entered datasets; it does not select a
publication, composition, temperature or crystallographic direction for you.

## Save a material

1. Open **Materials → Choose materials → Advanced material records** to edit a project material. CSV import and manual n/k entry also save presets automatically.
2. Choose its model:
   - `constant_nk`: **A** is refractive index n; **B** is extinction coefficient k.
   - `constant_eps`: **A** is real permittivity; **B** is imaginary permittivity.
   - `table_nk`: upload a CSV/TXT containing wavelength,n,k columns. Enter its filename in **DataFile** and explicitly choose `nm` or `um` in **WavelengthUnit**. At least two distinct wavelengths are required.
3. Open **Save a material for future projects**. Choose the material by name and enter an optional preset name and source/measurement notes.
4. Click **Save to material library**. It immediately appears in the preset dropdown. Use **Add to this project**, or select it directly in a Structure material dropdown and apply the edit. Use **Refresh saved presets** for changes made in another browser session.

Each save creates a separate dated version. Earlier values remain available, and completed runs retain their own material snapshots. Built-in approximate values remain distinguishable from user-saved values. Uploaded tables are copied to permanent storage with names based on their contents; two different files with the same original filename cannot silently replace one another. Keep source and measurement conditions in the preset notes; saving a preset does not establish its physical accuracy or validity outside the supplied wavelength range.

## Save and retrieve results

Every new simulation or optimization automatically saves its structure, material values, settings, results and diagnostics under **runs**. Optimization outputs include evaluated design conditions, peak tables, bounds, search settings and available ML history. The displayed final spectrum is also saved as a PNG. No entries are deleted automatically.

Every native evaluation additionally stores its normalized model, performance settings and **batch_results.csv** under `evaluations/<number>`. Each completed worker batch is flushed to disk. If stopped, timed out or failed, the finished batches remain available; points still inside an unfinished native batch cannot be recovered. A force-killed process or power loss may leave its last status as `running`; inspect the recorded batches and logs. ML continuation reuses completed design observations in its history, not unfinished spectral batches.

Open **Saved work → Results library**, click **Refresh library**, and select a saved run. Existing run folders from earlier versions are discovered automatically. Search by title, material names recorded in run metadata, notes, status or ID, and filter by work type or status. You can rename entries and add notes.

- Choose a **Result to view**; its preview loads automatically, or click **Load preview**. The preview shows at most 5,000 rows; **Download complete result CSV** retains every row. The collapsed diagnostics inventory lists additional models, figures and logs.
- Select **Original setup** in **Setup to reopen** and click **Reopen in editor** to restore Structure, Simulate, Settings and optimization controls. It does not start a calculation.
- Select a named saved design in the same dropdown to restore its saved material, geometry and Fourier basis. The dropdown uses the actual persisted design ID.
- Reopening an ML run's original setup loads its history automatically. Keep the structure, optical data, wavelength grid and bounds unchanged, increase budgets as needed, then start the search. Changing those conditions requires clearing the history to start a new search. Choosing an evaluated design clears the resume upload.
- **Download this saved run as ZIP** downloads the entry's complete run folder. Saved projects embed their required optical constants. Legacy optimization jobs also contain the numeric material tables for recovery.

**Saved work → Project files** saves portable version-3 JSON with embedded optical tables and checksums. Load it without re-uploading its original data files. Legacy JSON without embedded tables still loads; if its original files are unavailable, reopen its saved simulation job instead when one exists.

## Share the code with its data

In **Saved work → Results library → Back up, share or import a library**, leave **Include application source and bundled runtime** enabled and click **Create whole-library backup**. Wait for any simulation/search to stop so the exported run data is consistent.

The ZIP includes source code, environment specifications, bundled S4/ML runtime files, matching S4 source and licenses, every saved entry, and all saved material versions and optical tables. It excludes earlier export ZIPs, backup/build directories and Python caches. Extract it into a new folder: opening `launch_peak_gui.cmd` from that folder makes the included data and presets available immediately.

The source bundle requires the compatible Windows x64 / Python 3.12 environment described in README.md and environment.yml. It does not bundle Anaconda, external MKL/CUDA installations, or build a new standalone EXE. The launcher checks the configured S4 environment; a different computer may need to create that environment or use its own compatible Python to run `app.py`.

To merge into an existing updated program, select the ZIP and click **Import saved work and materials**. Import verifies the inventory, checksums and paths before merging data; it does not overwrite or execute uploaded source code. Existing run IDs are preserved by giving conflicting imported folders new IDs. Identical presets are reused; conflicting preset contents are kept separately. Re-importing the same run creates another copy. Export and import may take time for large libraries. The GUI accepts up to 2 GB compressed per upload and the importer allows up to 20 GB expanded / 100,000 files. For larger collections, copy the complete program folder directly while it is stopped.

## Storage and backup

By default these folders live beside the source program (beside the EXE in a rebuilt frozen application):

| Folder | Contents |
| --- | --- |
| `runs/` | Simulations, optimizations, model snapshots, projects, histories, partial batches and metadata |
| `data_library/presets/` | Separate JSON record for every saved material version |
| `data_library/optical_constants/` | Permanent copies of uploaded n,k files |
| `data_library/exports/` | Generated portable ZIP backups |

Copy **runs** and **data_library** together, or use the library export. Keep another backup outside the program folder. Data stays on the local filesystem; export/import does not synchronize separate computers. If you intentionally use a different storage location, set `S4_LIBRARY_ROOT` before launching. The GUI displays the active storage folder. Unsubmitted edits in the UI are saved only when you save a project/preset or start a valid run.

## Verification

Run `python -m unittest discover -s tests -v` in the compatible S4 environment. `python tests/check_library_gui_api.py` launches temporary GUI instances and checks saving a dispersive preset, portable project loading, native S4 results, CSV preview, setup restoration, server restart, data export/import, and ML-history continuation. Its temporary libraries do not modify user presets or runs.
