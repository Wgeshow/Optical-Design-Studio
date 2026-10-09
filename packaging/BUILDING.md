# Build the local 1.3.1 candidate

This directory contains release recipes copied from the verified 1.3.0 workflow. Previous release snapshots and deliverables remain in their original directories. These commands create local artifacts; they do not upload, publish, sign, or install them.

Use a Windows x64 Python 3.12 environment with the compatible pinned S4, MKL, CUDA, SQLite, numerical, plotting, and CAD inputs. The default dependency source is the adjacent **s4_ui_redesign** directory. **ODS_NATIVE_INPUTS** and **ODS_RELEASE_DEPENDENCIES** can override the build input locations; see **SOURCE_README.md**.

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
```

Stage only after all intended application changes are complete. Staging verifies version **1.3.1**, records the exact source hashes, excludes working libraries, and creates an empty seed. Both new simulation modules and their callers must be present in the staged source, readable source, source archive, and both frozen executables.

Source verification includes the existing scientific rendering, desktop interface, release, and data checks, plus the simulation performance, detailed-scan, Windows glass, and window chrome tests. The frozen application must independently exercise shared spectrum/field solutions, validated Fourier sampling, compact scan serialization, and exact SQLite spectrum storage with three completed field samples. Both glass looks must also paint an opaque maximized workspace and restore the glass policy after returning to a normal window.

The final commands verify the executable payload and archive integrity before writing **GitHub-Release-1.3.1** beside this directory. A passing recipe test or source check alone does not establish that the frozen package works. No build reports or validation claims from 1.3.0 are reused.
