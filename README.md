# Optical Design Studio 1.4.0-alpha.1 — corresponding source

This is a **Highly Experimental prerelease**. Model execution, physical convergence and paper agreement are distinct validation outcomes; inspect the saved status and model assumptions before using results.

For normal Windows use, download the separate **OpticalDesignStudio-Portable-1.4.0-alpha.1-Windows-x64.zip**. This source archive is for inspection, development, and rebuilding; it does not replace the complete portable runtime.

Application source and requirement files are in **src**. The corresponding S4 native source is in **native/S4-source**. Dependency notices accompany the archive. The public Silicon tutorial under **src/help_assets** contains genuine saved S4 results, explicit constant-index inputs, and file checksums; it is not a private user library.

## Run from source

Use a 64-bit Python 3.12 environment with the S4 native extension built for the same Python version and platform. Install the pinned requirements from **src/requirements.txt** in that environment; the desktop dependencies include PyQt6, PyQtGraph, and Colorama. Keep the **pcs_s4_runtime** package beside the application source and follow its native-runtime setup documentation.

From the source archive's root, launch with the interpreter from that environment:

```powershell
python .\src\qt_app.py
```

**src/launch_qt_gui.cmd** can also launch the application. Set **S4_PYTHON** to the intended Python interpreter when using a launcher. See **src/DESKTOP_GUIDE.md**, **src/README.md**, the requirements, and the native S4 source documentation for environment and build details. MEEP, GPU, CAD, and machine-learning features require their documented optional runtimes; installing the GUI dependencies alone does not provide those backends.

The prebuilt portable release targets Windows x64. Source scripts for other platforms require a native extension and dependencies built for that platform. Glass Desktop Acrylic requires Windows 11 build 22621 or later and can fall back to a solid appearance according to Windows settings.

## Rebuild the Windows portable package

Use a Windows x64 Python 3.12 build environment and the supplied staging/PyInstaller specification. Keep the S4 extension's Python ABI, native compiler/runtime, MKL libraries, and CUDA/cuBLAS inputs compatible with the extension you distribute. The reference S4 runtime uses MKL 2023.1 and its supported CUDA runtime; the native ABI and runtime versions must match.

This release's specification reads native DLLs from **ODS_OFFICIAL_RUNTIME**. Supply a reviewed runtime directory containing the matching SQLite runtime, MKL, OpenMP, FFI and Microsoft runtime DLLs, together with the isolated **cad_runtime** tree. The DLLs may originate in a compatible Conda environment's **Library/bin**, but this recipe does not read that directory automatically. The portable package bundles those DLLs and does not depend on a user's Conda installation.

The build accepts these environment overrides so inputs can live outside the original development layout:

- **ODS_OFFICIAL_RUNTIME** (required): the prepared native runtime described above. Its **cad_runtime/OCP** and **cad_runtime/vtk.libs/vtk-runtime-directory.txt** files must be present. This is a build input directory, not an installed application path required at runtime.
- **ODS_NATIVE_INPUTS**: the native input directory with **gpu/cublas64_11.dll**, **gpu/cublasLt64_11.dll** and **gpu/cudart64_110.dll**, compatible with the S4 extension.
- **ODS_RELEASE_DEPENDENCIES**: the directory containing the pinned **plot_dependencies**, **ml_dependencies** and **geometry_dependencies** trees. The isolated CAD runtime is read from **ODS_OFFICIAL_RUNTIME/cad_runtime**.
- **ODS_DEVSIM_DEPENDENCIES** (required): a directory containing **devsim** and its matching distribution metadata, including licenses. This release uses DEVSIM 2.11.0. Keep it isolated so it does not replace the application's numerical packages.
- **ODS_S4_RUNTIME**: optional complete **pcs_s4_runtime** directory to stage instead of the one inside the application source. This permits selecting a reviewed, compatible runtime without replacing an existing development binary. Omit it to use **src/pcs_s4_runtime**. The selected native runtime and its Python wrappers are copied into the staged source, and PyInstaller bundles that staged copy.
- **ODS_EIGENFREE_GPU_PACKAGES** and **ODS_EIGENFREE_CUDA**: provide both to reproduce the optional bundled GPU scattering runtime. The first contains CuPy, its support packages and complete distribution metadata; the second contains the compatible CUDA toolkit's **nvidia/cu13** tree. The public build uses CuPy 14.2.0 and CUDA 13 packages. Preserve their native layout, headers, libraries and licenses. A compatible NVIDIA driver is required when using this solver.

Set these variables to your prepared build inputs before staging/building. Keep the pinned requirement files and corresponding native source with your build record. Validate the resulting frozen desktop and backend together before distributing the portable folder. These are build-time input locations; users of the complete portable ZIP do not need to set them.

The archive contains the staging, compiler, source-test, frozen-verification and packaging helpers in **packaging**. It also contains the original source manifests and empty seed-library recipe as build records. The native S4 source has changed since 1.3.2; do not substitute an older binary to reproduce this release's numerical behavior. Match the native source and binary hashes recorded in **src/pcs_s4_runtime/build_manifest.json** and **packaging/stage-manifest.json**. Build-host paths inside the native manifest are historical provenance, not paths to create or commands to run; use your own prepared input locations through the variables above. After building the compatible S4 extension into **src/pcs_s4_runtime**, installing the pinned build dependencies (including PyInstaller), and setting the applicable input variables, run these commands from the archive root:

```powershell
Set-Location .\packaging
python .\stage_release.py --source ..\src --destination .\source
python -m unittest -v test_release_package_gates
python .\test_release_source.py
python .\verify_release_source_smoke.py
python .\build_release.py
python .\package_release.py --prepare-payload
python .\verify_release.py ".\dist\Optical Design Studio\Optical Design Studio.exe" --output .\verification
python .\audit_source_recipe.py
python .\package_release.py
python .\audit_release_archives.py
```

Stop if any command fails. Staging creates a fresh **packaging/source** snapshot and records its hashes; it refuses to overwrite an existing snapshot. The original shipped manifests are reference records, and staging replaces the manifest files with the hashes of your new snapshot. The compiler also refuses to overwrite an existing nonempty **packaging/dist**. The tests require the numerical, machine-learning and geometry dependencies from the pinned requirements in the build interpreter; the supplied dependency trees are additionally used by PyInstaller through **ODS_RELEASE_DEPENDENCIES**.

The packaging command creates locally verified portable and corresponding-source archives in **GitHub-Release-1.4.0-alpha.1** beside **packaging**; the final audit verifies their contents and checksums. The commands do not upload, publish, sign, or install them. The helpers do not download native S4, MKL, CUDA, CAD or third-party build inputs automatically; prepare those compatible inputs and retain their applicable source and licenses first. MPB, Legume, Sesame and Gmsh research workflows use separately configured runtimes; these archives do not install those external environments.

The staged source tests include the simulation speed and detailed-scan regressions. Both compiled executables must contain **scan_storage**, **field_sampling**, **simulation_fields**, and **contour_sweep**. Independent frozen checks exercise shared spectrum and field solves, validated Fourier sampling, exact SQLite spectrum results, and compact scan serialization before packaging. See **packaging/BUILDING.md** for the local candidate verification sequence.

Source checks cover editable simulation setups, preserved project drafts, saved startup window state and the full 0–100% glass opacity range. Frozen verification requires an additional **--native-startup-test** through **qt_app.main** and the real Windows Qt platform, with an isolated saved maximized state. It temporarily opens a native window and checks initial maximized painting, restore and maximize, and the Windows system restore/maximize commands. Existing offscreen checks, including all 27 simulation choices, remain required independently.

## Data and licenses

Live charts use native Qt rendering; Matplotlib remains available for publication exports. The material interpolation policy affects calculations. Geometry colors and preview opacity are display settings.

Do not replace or share your working data directory when updating source. The public archive contains the tutorial example and corresponding code; it excludes private user libraries, saved sessions and credentials. Original native build metadata retains historical build-host paths solely as provenance.

Retain the complete **THIRD_PARTY_LICENSES** directory and **THIRD_PARTY_NOTICES.md** when redistributing included components. Those licenses apply to their respective components; the notices do not replace the corresponding native/application source supplied with this release.
