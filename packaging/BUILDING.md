# Build the Highly Experimental 1.4.0-alpha.1 candidate

This directory contains the 1.4.0-alpha.1 prerelease recipes and verification gates. The existing stable releases remain unchanged. These commands create local artifacts; they do not upload, publish, sign, or install them. Windows version metadata uses numeric version 1.4.0.1 with the prerelease flag, while the application and release assets use 1.4.0-alpha.1.

Use a Windows x64 Python 3.12 environment with compatible S4, MKL, CUDA, SQLite, numerical, plotting, CAD and DEVSIM inputs. Install the build dependencies, including PyInstaller, and follow **SOURCE_README.md** for the required layouts. Source archives do not contain native binary build inputs or download them automatically.

Set these environment variables to your own prepared inputs before staging and keep the same values through the build:

- **ODS_OFFICIAL_RUNTIME**: matching native DLL directory, including **sqlite3.dll**, MKL/OpenMP/FFI DLLs and the isolated **cad_runtime** tree.
- **ODS_NATIVE_INPUTS**: directory containing the three compatible CUDA 11 runtime DLLs under **gpu**.
- **ODS_RELEASE_DEPENDENCIES**: parent of **plot_dependencies**, **ml_dependencies** and **geometry_dependencies**.
- **ODS_DEVSIM_DEPENDENCIES**: isolated DEVSIM 2.11.0 package and matching distribution metadata, including licenses.
- **ODS_S4_RUNTIME**: optional complete reviewed **pcs_s4_runtime** override. Omit to use **src/pcs_s4_runtime**. Source archives supply corresponding native source rather than the compiled extension.
- **ODS_EIGENFREE_GPU_PACKAGES** and **ODS_EIGENFREE_CUDA**: provide both to reproduce the optional CuPy 14.2.0 / CUDA 13 GPU scattering payload. See **SOURCE_README.md** for layouts.

This release includes native S4 changes since stable 1.3.2. Do not assume an older extension is interchangeable. The runtime build manifest records the native source hashes and extension hash; its original build-host paths are historical provenance, not runnable instructions. Native compiler, Python ABI and supporting DLL compatibility must be established when rebuilding.

Run each command from this directory with the same build interpreter, and stop if a command fails:

```powershell
python .\stage_release.py --source ..\src --destination .\source
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

Stage only after all intended application changes are complete. Staging verifies version **1.4.0-alpha.1**, records the exact source hashes, excludes working libraries, and creates an empty seed. Simulation modules and their callers must be present in the staged source, readable source, source archive, and both frozen executables.

Source verification includes the existing scientific rendering, desktop interface, release, and data checks, plus simulation performance, detailed scans, Windows glass, startup window-state restoration, and 0–100% glass opacity. The frozen application must independently exercise shared spectrum/field solutions, validated Fourier sampling, compact scan serialization, and exact SQLite spectrum storage with three completed field samples. Both glass looks must also paint an opaque maximized workspace and restore the glass policy after returning to a normal window.

**verify_release.py** additionally launches the compiled application's **--native-startup-test** path using the real Windows Qt platform and an isolated data directory. This temporarily opens a native window and exercises **qt_app.main** with saved maximized preferences. Native visibility, surface painting, input, restoration and maximization checks must pass separately from the offscreen scientific/interface checks. The native report is required before packaging; an offscreen result alone cannot pass this gate. Compiled verification also opens all 27 simulation choices and checks that selecting an editor does not launch a job or replace the shared device.

For research workflows, also run representative compiled-backend jobs using the intended MPB, Legume, Sesame and Gmsh runtime settings. Execution success, numerical convergence and agreement with a paper are separate outcomes. Review saved residuals and validity limits; an interface smoke test cannot establish physical accuracy for an arbitrary edited setup.

The final commands create portable and corresponding-source archives in **GitHub-Release-1.4.0-alpha.1** beside this directory, then audit their inventory, checksums, source correspondence and updater extraction contract. A passing recipe test or source check alone does not establish that the frozen package works. No earlier release's test report substitutes for verification of these executables. Preserve all third-party notices and corresponding native source when distributing the artifacts.
