# Build Optical Design Studio 1.4.0 — build and verification

Build with Windows x64 CPython 3.12 and PyInstaller 6.16.0. The application version is 1.4.0, the build date is 2026-11-02, and Windows version metadata is 1.4.0.0 without the prerelease flag. Build and audit in a fresh directory; preserve existing releases.

## Native and optional dependency inputs

Install the Python dependencies from the source requirements into the build interpreter, including PyQt6, PyYAML, NumPy, SciPy, pandas, matplotlib, scikit-learn, pyqtgraph, Shapely, colorama, and DEVSIM. Optional isolated dependency directories may be provided without replacing the application's NumPy.

- `ODS_S4_RUNTIME`: complete reviewed `pcs_s4_runtime` directory. This release preserves the S4 native module shipped in alpha.1, SHA-256 `1387aa415cf73525420bcdfac5e86de3c0923b26565d62209b3ed1975df3333c`.
- `ODS_NATIVE_INPUTS`: native input directory containing `gpu/cublas64_11.dll`, `gpu/cublasLt64_11.dll`, and `gpu/cudart64_110.dll`.
- `ODS_OFFICIAL_RUNTIME`: compatible SQLite, FFI, MKL and Microsoft runtime DLL directory. If omitted, the recipe uses the build interpreter's `Library/bin` directory.
- `ODS_CAD_RUNTIME`: optional isolated CAD runtime containing `OCP` and `vtk.libs/vtk-runtime-directory.txt`. Defaults to `ODS_OFFICIAL_RUNTIME/cad_runtime` when the official runtime override is set.
- `ODS_RELEASE_DEPENDENCIES`: optional directory of `plot_dependencies`, `ml_dependencies`, and `geometry_dependencies`. Installed build-interpreter packages are otherwise used and checked.
- `ODS_DEVSIM_DEPENDENCIES`: optional isolated DEVSIM package and metadata directory.
- `ODS_EIGENFREE_GPU_PACKAGES` and `ODS_EIGENFREE_CUDA`: paired optional CuPy/CUDA package and toolkit trees; retain their on-disk layout.

Set `S4_DLL_DIRS` to the compatible native DLL directory and `DEVSIM_MATH_LIBS` to its `mkl_rt.2.dll` when verifying source. The public frozen app includes the native runtime; these build-machine settings are not shipped as user preferences. WSL, MPB, Meep, Legume, Sesame and Gmsh remain optional solver environments created or selected from the application.

## Stage, test and freeze

Run from `packaging` using the same build interpreter and explicit input environment:

```powershell
python .\stage_release.py --source ..\src --destination .\source
python -m unittest -v test_packaging test_release_package_gates test_native_setup_packaging test_thermal_packaging
python .\test_release_source.py
python .\build_release.py
python .\package_release.py --prepare-payload
python .\verify_release.py ".\dist\Optical Design Studio\Optical Design Studio.exe" --output .\verification
python .\audit_source_recipe.py
```

Staging refuses to overwrite an existing snapshot. It records exact hashes, sanitizes public tutorial metadata without changing scientific CSV values, validates benchmark resources, and creates an empty user-library seed. The compiler rejects changed staged files and an existing nonempty output directory. Both GUI and backend executables use the same staged code.

Source test reports must name the exact staged source hash and list the checks actually executed. A targeted test set does not imply that the full suite passed. The full frozen verifier includes real Windows startup and restore/maximize checks in addition to offscreen numerical and interface checks.

## Experimental shipment

`package_release.py` retains its complete-verification gate. The actual 1.4.0 release uses a separately identified critical profile and the supplied `package_final_release.py` helper. It records the narrower scope, requires the exact eight frozen critical checks, seven real Windows startup checks, fresh process-attributed manual acceptance, source/package/updater tests, compiled-source equality, dependency licenses and matching native source. The complete theme/field/installer matrix is not implied by this profile.

After payload preparation, run `verify_release.py` with `--critical`, finish fresh manual acceptance, and audit the source recipe. Preserve all receipts. The final helper requires the reviewed build receipts in the adjacent release-audit directory and refuses existing output assets:

```powershell
python .\package_final_release.py --allow-critical-profile --validation-scope "Targeted source and updater tests, critical frozen profile, real Windows startup and fresh manual checks; full packaged matrix not rerun."
```

It creates an LZMA-compressed ZIP compatible with the existing updater (manual extraction uses 7-Zip), a corresponding source ZIP, checksums and aggregate validation. Exact inventories, per-file SHA-256 comparisons and CRC checks precede publication. `packaged_self_tests_passed=false` truthfully records that the full profile was not run; the separately named critical/startup/manual gates record their actual results. The public payload excludes user runs, preferences, projects and solver-installation receipts. A rebuilder must supply fresh receipts for their own source and executable rather than reuse this release's hashes.
