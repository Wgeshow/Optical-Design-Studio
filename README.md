# Optical Design Studio

Application source code and public Windows releases for Optical Design Studio, maintained by Wgeshow.

## Download

[Download Optical Design Studio 1.1.0 for Windows x64](https://github.com/Wgeshow/Optical-Design-Studio/releases/tag/v1.1.0). Extract the complete portable ZIP and run **Optical Design Studio.exe**.

## Updating the application

Versions 1.0.5 and earlier require one manual upgrade to 1.1.0. Preserve **User Data** and **portable_settings.json**. If using a new application folder, select your existing data folder under **Settings → Data storage** and restart.

Version 1.1.0 supports user-confirmed download, checksum verification, in-place replacement and restart for subsequent compatible updates through **About → Download and install**. The application folder must be writable, with free space for staging and a backup. No GitHub account or token is required.

Packages appear under [Releases](https://github.com/Wgeshow/Optical-Design-Studio/releases). Windows package names follow `OpticalDesignStudio-Portable-VERSION-Windows-x64.zip`, with a matching `.sha256` file.

## Repository contents

This repository contains the reviewed source snapshot distributed with version 1.1.0:

- [src/](src/): application code, COMSOL/STEP exporters, launch scripts, requirements and documentation.
- [src/S4-source/](src/S4-source/): native S4 source and accompanying licenses/build instructions.
- [packaging/](packaging/): Windows packaging and verification scripts.
- [src/third-party-licenses/](src/third-party-licenses/): third-party notices.

Start with the [application README](src/README.md) and [build instructions](packaging/BUILDING.md). Older version-specific sections in those documents are historical. Running from source requires Python and the listed dependencies, including a compatible native S4 build. Prebuilt runtimes and dependency wheels are not tracked here; the Windows release bundles its required runtime.

Personal research data, material libraries, saved sessions, credentials and generated build output are intentionally excluded. Third-party code retains its accompanying license terms.

COMSOL export creates a Java model script, not an MPH file. Execution inside COMSOL has not been verified; simulation physics and optical tables require configuration and review. See the [export guide](src/CAD_COMSOL_EXPORT_GUIDE.md).
