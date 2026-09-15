Build on 64-bit Windows using Python 3.12 and the application's pinned dependencies. The native S4 extension requires the matching MKL 2023.1 DLLs in the build interpreter's `Library/bin` folder. PyInstaller 6.22.2 and Inno Setup 7.1.0 were used for this release.

For 1.0.4 portable delivery, use build_portable.py with --source, --bundle and
--public-source (a reviewed complete source tree), then package_portable.py.
The portable builder does not run Inno Setup. START_HERE.md describes extracting,
choosing a data directory, and upgrading without an installer. The ZIP contains
only inventoried public payload files, never data produced by verification.

1. Keep a verified source/runtime bundle if the complete native build and ML dependency source are not already available locally. A private library export can supply build dependencies; its research data is excluded by the public profile.
2. Keep the current complete application source alongside the export.
3. Install the Python requirements, including `requirements-desktop.txt`, `requirements-ml.txt`, and PyInstaller, into the build environment.
4. Install the official Inno Setup compiler, or pass its location to the command below.
5. Put these official NVIDIA Windows wheels in `tools` using `python -m pip download --no-deps --only-binary=:all: --dest tools nvidia-cublas-cu11==11.11.3.6 nvidia-cuda-runtime-cu11==11.8.89`.
6. Keep the supplied original icon files in `assets`.

For public delivery, prepare a separately reviewed readable-source tree rooted at the application files. Include the matching application source, native `S4-source` tree with licenses and build instructions, `third-party-licenses`, and reviewed `packaging` recipes. Leave research runs, presets, uploaded optical-constant tables, saved sessions, machine paths, duplicate runtime binaries, dependency wheels, archives, and private test reports out of this tree. Runtime dependencies are supplied separately by the frozen application's `_internal` directory.

Run from PowerShell:

```powershell
.\build_windows.ps1 -SourceRoot 'C:\path\to\application' -DataBundle 'C:\path\to\s4_bundle.zip' -Profile public -PublicSource 'C:\path\to\reviewed-source' -Python 'C:\path\to\python.exe' -InnoCompiler 'C:\path\to\ISCC.exe'
```

The output is `release/OpticalDesignStudio-Setup-1.0.3-Windows-x64.exe`. The public profile creates an empty valid seed archive, verifies that the readable source matches its reviewed inventory, compiles GUI and calculation executables sharing one bundled runtime, retains source and dependency notices, and runs the packaged CPU/ML/field/GUI checks before creating Setup. Version 1.0.3 checks and downloads from the public downloads repository without account credentials. It does not automatically apply an update.

The `private` profile remains available for explicitly approved private distribution of a saved library; it requires `-DataBundle` and retains that bundle's research seed. The data profile does not control updater authentication: payload metadata reads the staged `update_client.py` repository. Version 1.0.3's updater is anonymous with either data profile. Never publish a private-data-profile installer to the public downloads repository.

The build environment's paths are not needed on the destination computer. Setup installs files only in the chosen application directory and creates per-user shortcuts/uninstall registration. Fresh public installations start without saved research data. The empty tracked seed archive also replaces the older bundled seed on upgrade, while the separate user-data library remains intact. The installer does not install system Python, alter PATH, or install graphics drivers.

Source distribution and third-party dependency licensing information are in the installed `THIRD_PARTY_LICENSES` folder. Code signing requires a publisher certificate and is not part of this local build.

For a release with a different shared library, set the build verification's expected saved-entry count to that library's count. Keep the Inno `AppId` stable for upgrades. Set `APP_VERSION` and `BUILD_DATE` in the application's `app_version.py` before a release. `prepare_payload.py` reads those literal constants without importing the GUI and generates both `version_info.txt` and `version.iss`. The payload inventory, installer, executable versions, verification default, and release reports use that version. Do not change the Inno version override independently of the application.

For a complete release verification, run the packaged application check and an isolated upgrade from the previously published installer before finalizing deliverables:

```powershell
python verify_frozen.py 'dist/Optical Design Studio/Optical Design Studio.exe' 'v103_test' --gpu --expect-empty-library
python verify_local_installation.py 'release/OpticalDesignStudio-Setup-1.0.3-Windows-x64.exe' --previous-installer 'release/OpticalDesignStudio-Setup-1.0.2-Windows-x64.exe'
python finalize_release.py --fresh-runtime-report 'v103_test/report.json'
```

Use `--cpu-only` on the installer verification and omit `--gpu` on computers without NVIDIA hardware. Installer verification uses an owned temporary directory outside OneDrive, refuses to modify an existing registered installation, checks the install receipt, and verifies that upgrade and uninstall preserve the user library. Release finalization preserves each version's evidence and writes the installer checksum beside its EXE.

The download release contains the approved installer EXE and its `.sha256` checksum. Source-repository visibility and source-archive distribution are separate publishing decisions; this profile retains readable application and native source inside the installer, together with dependency notices. Do not describe the installer as hiding source code. Publish a stable release only after testing and reviewing its public contents. Use the separate `test` branch for experimental changes and mark any experimental release as a prerelease. The application ignores draft releases and prereleases. Do not include access tokens, credential-store contents, or signing keys in source or release assets.

The Windows installer requires Windows-native S4 and runtime binaries. Linux users run the cross-platform Python source with a native Linux S4 build and its dependencies; the Windows EXE and its bundled DLLs are not Linux binaries. See the application's source README and Linux launch/build scripts for that workflow. A Linux packaged update needs its own platform artifact and verification; this release distributes a Windows x64 installer.
