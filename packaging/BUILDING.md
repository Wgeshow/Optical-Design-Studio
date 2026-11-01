# Build Optical Design Studio 1.4.0-alpha.5 â€” Highly Experimental

Build with Windows x64 CPython 3.12 and PyInstaller 6.16.0. The application version is 1.4.0-alpha.5, the build date is 2026-11-01, and Windows version metadata is 1.4.0.5 with the prerelease flag. Build and audit in a fresh directory; preserve existing releases.

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

`package_release.py` retains the complete-verification gate. A Highly Experimental release may instead use `package_experimental_candidate.py` with fresh source/build reports, a passing critical frozen profile and real Windows startup, and explicit limits on the unrun full matrix. It must not describe unrun checks as passed. Create a portable `.7z`, a corresponding source `.zip`, SHA-256 checksums and an archive audit; verify exact inventories and integrity before publishing. The portable payload includes source and third-party licenses, but no user runs, preferences, projects or solver installation receipts.

For the bounded experimental profile, prepare the payload as above, run the verifier with `--critical`, finish the release notes, and audit the corresponding source recipe before creating archives:

```powershell
python .\verify_release.py ".\dist\Optical Design Studio\Optical Design Studio.exe" --critical --output .\verification
python .\audit_source_recipe.py
python .\package_experimental_candidate.py --seven-zip "C:\Program Files\7-Zip\7z.exe" --allow-partial --validation-scope "Targeted source checks, critical frozen profile, and real Windows startup; full theme and field matrix not rerun."
```

The critical profile checks all 29 chooser routes, independent setups and transfer, absence of stray panels, exact grid output, environment resources, bundled dependencies, and a native CPU spectrum. Real Windows startup and restore/maximize checks remain mandatory. It does not claim the full theme and scientific field matrix passed. The experimental helper verifies both executable module inventories and records the actual omitted checks, final archive integrity, and exact corresponding-source hashes.

These recipes build local artifacts only; they do not publish, sign or install the application.
