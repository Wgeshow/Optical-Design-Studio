# Optical Design Studio 1.4.0-alpha.6 â€” corresponding source

This is a **Highly Experimental prerelease**. Model execution, physical convergence and paper agreement are distinct validation outcomes; inspect the saved status and model assumptions before using results.

For normal Windows use, download the separate **OpticalDesignStudio-Portable-1.4.0-alpha.6-Windows-x64.7z** and extract the complete folder. This source ZIP is for inspection, development, and rebuilding; it does not replace the portable runtime.

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

Set **ODS_OFFICIAL_RUNTIME** to a reviewed directory containing the build interpreter's compatible SQLite, MKL, OpenMP and other native runtime DLLs, plus the CAD runtime. The default is the build interpreter's **Library/bin**. The portable package bundles these DLLs and does not depend on a user's Conda installation. Consult **packaging/BUILDING.md** for the build-input layout and validation used for this release.

The build accepts these environment overrides so inputs can live outside the original development layout:

- **ODS_NATIVE_INPUTS**: the native input directory containing the compatible **gpu** DLL inputs. The VTK runtime marker is read from the isolated CAD runtime, with the legacy sibling **assets/vtk-runtime-directory.txt** location retained as a fallback.
- **ODS_RELEASE_DEPENDENCIES**: optional directory containing **plot_dependencies**, **ml_dependencies**, and **geometry_dependencies**. Installed build-interpreter packages are used and validated when those directories are absent. **ODS_CAD_RUNTIME** can separately select the isolated CAD runtime; otherwise it defaults to **ODS_OFFICIAL_RUNTIME/cad_runtime**.
- **ODS_OFFICIAL_RUNTIME**: the reviewed native runtime and CAD directory described above.
- **ODS_DEVSIM_DEPENDENCIES**, **ODS_EIGENFREE_GPU_PACKAGES**, and **ODS_EIGENFREE_CUDA**: optional external package/native input roots for the semiconductor and GPU dependencies. These build-time overrides do not select a user's simulation environment.
- **ODS_S4_RUNTIME**: optional complete **pcs_s4_runtime** directory to stage instead of the one inside the application source. This permits selecting a reviewed, compatible runtime without replacing an existing development binary. Omit it to use **src/pcs_s4_runtime**. The selected native runtime and its Python wrappers are copied into the staged source, and PyInstaller bundles that staged copy.

Set these variables to your prepared build inputs before staging/building. Keep the pinned requirement files and corresponding native source with your build record. Validate the resulting frozen desktop and backend together before distributing the portable folder. These are build-time input locations; users of the complete portable archive do not need to set them.

The archive contains the staging, compiler, source-test, frozen-verification and packaging helpers in **packaging**. It also contains the original source manifests and empty seed-library recipe as build records. After building the compatible S4 extension into **src/pcs_s4_runtime**, installing the pinned build dependencies (including PyInstaller), and configuring the required native input overrides above, run these commands from the archive root:

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

The final command creates locally verified portable and corresponding-source archives in **GitHub-Release-1.4.0-alpha.6** beside **packaging**. It does not upload, publish, sign, or install them. The helpers do not download native S4, MKL, CUDA, CAD or third-party build inputs automatically; prepare those compatible inputs and retain their applicable source and licenses first.

The standard full verification workflow includes detailed spectrum/field solves, Fourier sampling, SQLite results, scan serialization and broader UI/theme checks. Both compiled executables must contain the required simulation and environment modules. See **packaging/BUILDING.md** for the candidate verification sequence.

This highly experimental release uses the narrower **critical** profile: all 29 chooser destinations, 28 independent study/tool setups, unexpected-window detection, a small native S4 parameter sweep, saved-data analysis and environment resources. It also runs targeted source tests and packaging gates. The full theme/field/paper matrix is not claimed as completed for this package; consult **EXPERIMENTAL_VALIDATION.json** and the published **VALIDATION.json** for the actual outcomes and exact scope.

Native Windows startup verification is a separate **--native-startup-test** through **qt_app.main** with an isolated saved maximized state. It opens a native window and checks initial painting, restore/maximize and Windows system commands. Offscreen chooser checks are separate from that native-display test.

## Data and licenses

Live charts use native Qt rendering; Matplotlib remains available for publication exports. The material interpolation policy affects calculations. Geometry colors and preview opacity are display settings.

Do not replace or share your working data directory when updating source. The public archive contains the tutorial example and corresponding code; it excludes private user libraries, saved sessions and credentials. Native build manifests retain original toolchain paths as build provenance; these do not select runtime locations or include the contents of those directories.

Retain the complete **THIRD_PARTY_LICENSES** directory and **THIRD_PARTY_NOTICES.md** when redistributing included components. Those licenses apply to their respective components; the notices do not replace the corresponding native/application source supplied with this release.
