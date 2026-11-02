# Optical Design Studio 1.4.0

Portable application for Windows x64.

1. Download **OpticalDesignStudio-Portable-1.4.0-Windows-x64.zip** from the public release page.
2. Use **7-Zip** to extract the complete archive into a new writable folder. The ZIP uses LZMA compression; Windows Explorer extraction is not assumed. The existing in-app updater also supports this format.
3. Open the extracted **Optical Design Studio** folder and run **Optical Design Studio.exe**. Keep the backend executable and **_internal** folder together with it.
4. Choose a workspace and create a structure in its editor. Optional solver setup is available in the relevant study.

The bundled desktop and S4 runtime do not require a separate Python installation. MPB and Meep use their supported Linux/WSL environments; other optional solvers have separate setup requirements. The standard Windows ZIP is compatible with the application's existing update workflow. This release is version 1.4.0; earlier 1.4 alpha releases remain available as historical prereleases.

Preserve your current application folder and project/data library. To use an existing data location, select it in Settings → Data storage. Avoid deleting the only copy of an unfinished project or result.

Read **RELEASE_NOTES.md** for additions and known limitations, and the release's **VALIDATION.json** for exact build checks. The public **PUBLIC_ACCEPTANCE_REPORT.html** and **VALIDATION.md** release attachments explain route coverage, equations and scientific limitations. Open the downloaded HTML report in a browser; it is self-contained.

The campaign has 27 of 28 routes executed through the UI, with five earlier scoped reference agreements and zero new agreements from the latest Meep temporal refinement. Program availability is not a claim that every numerical model is converged or physically validated.

The Source ZIP is for rebuilding and inspection. Normal Windows use requires the Portable ZIP. Corresponding readable source and dependency notices are included; see **THIRD_PARTY_NOTICES.md** and **THIRD_PARTY_LICENSES**.

Public release: https://github.com/Wgeshow/Optical-Design-Studio/releases/tag/v1.4.0
