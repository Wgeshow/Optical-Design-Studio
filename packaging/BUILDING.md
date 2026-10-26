# Build the local 1.3.3 candidate

This directory contains release recipes copied from the verified 1.3.1 workflow, with fresh 1.3.3 version references and verification gates. The published 1.3.1 source, packages and tag remain unchanged. These commands create local artifacts; they do not upload, publish, sign, or install them.

Use a Windows x64 Python 3.12 environment with the compatible pinned S4, MKL, CUDA, SQLite, numerical, plotting, and CAD inputs. The default dependency source is the adjacent **s4_ui_redesign** directory. **ODS_NATIVE_INPUTS** and **ODS_RELEASE_DEPENDENCIES** can override the build input locations; see **SOURCE_README.md**.

For this UI patch, select the verified published 1.3.1 S4 runtime without replacing the production application's native file. Keep the override set for staging and recipe input tests; PyInstaller then bundles the selected runtime from the staged source:

```powershell
$env:ODS_S4_RUNTIME = (Resolve-Path .\..\release-1.3.1\source\pcs_s4_runtime).Path
```

**ODS_S4_RUNTIME** optionally selects the complete reviewed **pcs_s4_runtime** directory. With no override, staging uses the production source's **pcs_s4_runtime** directory as before. The selected native binary must still pass the unchanged published SHA-256 pin for this local patch. Staging records the chosen runtime's hashes, without adding machine-specific absolute paths to shipped manifests.

Run each command from this directory with the same build interpreter, and stop if a command fails:

```powershell
python .\stage_release.py --source ..\s4_ui_redesign --destination .\source
python -m unittest -v test_packaging test_release_package_gates
python .\test_release_source.py
python .\verify_release_source_smoke.py
python .\build_release.py
python .\package_release.py --prepare-payload
python .\verify_release.py ".\dist\Optical Design Studio\Optical Design Studio.exe" --output .\verification
python .\audit_source_recipe.py
python .\package_release.py
python .\audit_release_archives.py
```

Stage only after all intended application changes are complete. Staging verifies version **1.3.3**, records the exact source hashes, excludes working libraries, and creates an empty seed. Simulation modules and their callers must be present in the staged source, readable source, source archive, and both frozen executables.

Source verification includes the existing scientific rendering, desktop interface, release, and data checks, plus simulation performance, detailed scans, Windows glass, startup window-state restoration, and 0–100% glass opacity. The frozen application must independently exercise shared spectrum/field solutions, validated Fourier sampling, compact scan serialization, and exact SQLite spectrum storage with three completed field samples. Both glass looks must also paint an opaque maximized workspace and restore the glass policy after returning to a normal window.

**verify_release.py** additionally launches the compiled application's **--native-startup-test** path using the real Windows Qt platform and an isolated data directory. This temporarily opens a native window and exercises **qt_app.main** with saved maximized preferences. Five native checks are required: the initial maximized surface, restoration, another maximize, Windows system-command restoration, and Windows system-command maximization. Native visibility, surface painting and input checks must pass separately from the existing offscreen scientific/interface checks. The native report is required before packaging; an offscreen result alone cannot pass this gate.

The final commands verify the executable payload and archive integrity before writing **GitHub-Release-1.3.3** beside this directory. A passing recipe test or source check alone does not establish that the frozen package works. No build, test or validation reports from 1.3.1 are reused.
