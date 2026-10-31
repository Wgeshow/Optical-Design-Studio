# Optical Design Studio 1.4.0-alpha.4

Experimental portable application for Windows x64.

1. Download OpticalDesignStudio-Portable-1.4.0-alpha.4-Windows-x64.7z.
2. Use 7-Zip to extract the complete archive to a new writable folder.
3. Open the extracted Optical Design Studio folder and run Optical Design Studio.exe. Keep the backend executable and _internal folder together with it.
4. Choose a workspace and create your structure through its editor. Optional solver setup is available in the relevant study.

The bundled desktop and S4 runtime do not require a separate Python installation. MPB and Meep use their supported Linux/WSL environments; other optional solvers have separate setup requirements. This prerelease is downloaded manually and does not change the current stable update channel.

Preserve your current application folder and project/data library. To use an existing data location, select it in Settings → Data storage. Do not remove the only copy of an unfinished project or result.

Read RELEASE_NOTES.md for changes and known limitations, and VALIDATION.json for this build's actual checks. The 28-route UI-only scientific campaign remains incomplete; model availability is not a claim of physical validation.

The Source ZIP is for rebuilding and inspection. Normal use requires the Portable .7z archive. Corresponding readable source and third-party notices are included; see THIRD_PARTY_NOTICES.md and THIRD_PARTY_LICENSES.
