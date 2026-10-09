# Optical Design Studio 1.3.1 — corresponding source

For normal Windows use, download the separate **OpticalDesignStudio-Portable-1.3.1-Windows-x64.zip**. This source archive is for inspection, development, and rebuilding; it does not replace the complete portable runtime.

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

The specification expects the build interpreter's native DLLs in **Library/bin**, as provided by the Conda environment in **src/environment.yml**. This includes that interpreter's matching SQLite runtime as well as MKL and OpenMP; the resulting portable package bundles those DLLs and does not depend on a user's Conda installation.

The build accepts these environment overrides so inputs can live outside the original development layout:

- **ODS_NATIVE_INPUTS**: the native input directory, including its **gpu** directory and the expected sibling **assets/vtk-runtime-directory.txt** marker. Supply the compatible native GPU/runtime inputs required by the specification.
- **ODS_RELEASE_DEPENDENCIES**: the directory containing the pinned **plot_dependencies**, **ml_dependencies**, **geometry_dependencies**, and **cad_runtime** trees.

Set these variables to your prepared build inputs before staging/building. Keep the pinned requirement files and corresponding native source with your build record. Validate the resulting frozen desktop and backend together before distributing the portable folder. These are build-time input locations; users of the complete portable ZIP do not need to set them.

The archive contains the staging, compiler, source-test, frozen-verification and packaging helpers in **packaging**. It also contains the original source manifests and empty seed-library recipe as build records. After building the compatible S4 extension into **src/pcs_s4_runtime**, installing the pinned build dependencies (including PyInstaller), and setting the two input variables above, run these commands from the archive root:

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
```

Stop if any command fails. Staging creates a fresh **packaging/source** snapshot and records its hashes; it refuses to overwrite an existing snapshot. The original shipped manifests are reference records, and staging replaces the manifest files with the hashes of your new snapshot. The compiler also refuses to overwrite an existing nonempty **packaging/dist**. The tests require the numerical, machine-learning and geometry dependencies from the pinned requirements in the build interpreter; the supplied dependency trees are additionally used by PyInstaller through **ODS_RELEASE_DEPENDENCIES**.

The final command creates locally verified portable and corresponding-source archives in **GitHub-Release-1.3.1** beside **packaging**. It does not upload, publish, sign, or install them. The helpers do not download native S4, MKL, CUDA, CAD or third-party build inputs automatically; prepare those compatible inputs and retain their applicable source and licenses first.

The staged source tests include the simulation speed and detailed-scan regressions. Both compiled executables must contain **scan_storage**, **field_sampling**, **simulation_fields**, and **contour_sweep**. Independent frozen checks exercise shared spectrum and field solves, validated Fourier sampling, exact SQLite spectrum results, and compact scan serialization before packaging. See **packaging/BUILDING.md** for the local candidate verification sequence.

## Data and licenses

Live charts use native Qt rendering; Matplotlib remains available for publication exports. The material interpolation policy affects calculations. Geometry colors and preview opacity are display settings.

Do not replace or share your working data directory when updating source. The public archive contains the tutorial example and corresponding code; it excludes private user libraries, saved sessions, credentials, and developer-specific paths.

Retain the complete **THIRD_PARTY_LICENSES** directory and **THIRD_PARTY_NOTICES.md** when redistributing included components. Those licenses apply to their respective components; the notices do not replace the corresponding native/application source supplied with this release.
