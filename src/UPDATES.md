# About and public updates

## Version 1.1.0 and later

The packaged Windows application offers **About → Download and install**.
Confirm the themed prompt, choose a download folder, and allow the verified
package to finish downloading. The application stages and checks the complete
package, saves the current project, closes, replaces its files in the same
folder, and restarts. Updates never begin without your confirmation.

The existing User Data, runs, data_library and portable_settings.json are
preserved. A backup of replaced application files remains in a sibling
`.optical-update-*` folder. Failed normal replacement operations attempt to
restore those files. Keep the application and staging folder on a writable
local drive; administrator-only folders are not supported by this updater.
Do not interrupt power during installation. Preparation checks free space;
the staged package, independent helper runtime and backup need extra disk space.

**One-time upgrade from 1.0.5 and earlier:** those versions cannot install a ZIP
in place. Download and extract 1.1.0 manually, preserve your existing data folder,
and select that folder in Settings → Data storage if using a new app folder.
Subsequent compatible releases can be installed by the 1.1.0 updater.
The public repository is renamed to `Wgeshow/Optical-Design-Studio` with this
release. Earlier applications reject the renamed repository identity, so use
the new release page for the one-time manual upgrade if their check fails.

## Historical update behavior

Version 1.0.4 prefers portable Windows ZIP assets. Extract the complete downloaded
ZIP and run Optical Design Studio.exe. Preserve User Data and portable_settings.json
when replacing the app, or point Settings → Data output folder to your existing
library after extracting into a new folder. The app does not extract or install
updates automatically. Versions through 1.0.3 need a one-time manual ZIP download
because their updater only recognizes Windows installer assets. The following
installer workflow describes the older releases; integrity checks still apply.

Version 1.0.3 checks and downloads releases without a GitHub account, access key,
token, or sign-in. Open **About → Check for updates**. About also shows the
installed version, recorded installation/update date, platform, and last check.

## Check and download

The public update endpoint is
[Wgeshow/optical-design-studio-downloads](https://github.com/Wgeshow/optical-design-studio-downloads).
Anyone can access its published installer assets. The desktop app sends no
authorization header, reads no saved GitHub credentials, and does not contact
the private development repository. Browser sign-in is not required.

Checks run only when requested. The client verifies the expected public
repository, ignores drafts and pre-releases, compares numeric versions, and
selects the matching platform package. Empty releases, incompatible packages,
offline connections, GitHub rate limits, and invalid metadata have separate
statuses; none is reported as up to date.

**Download update** appears beside Check when a newer compatible package is
available. Choose a destination folder, follow progress, or cancel. HTTPS,
GitHub's published SHA-256 asset digest, and the expected file size protect
download integrity. Existing files in the destination are preserved. The app
offers **Open download folder** after success; run the installer when ready.
This release does not install updates or restart the application automatically.

Simulation and optimization can continue during checks and downloads. Closing
the application cancels an active update request and waits for the worker to
finish before saving and closing. Existing project/material/results libraries
remain local and are not uploaded by the updater.

Versions 1.0.2 and earlier need an installer upgrade to receive this public,
key-free updater. This version does not use or delete credentials remembered by
an older version. Users can remove an old OpticalDesignStudio/GitHub entry from
Windows Credential Manager themselves if one was previously saved.

## Separate public downloads and private development

GitHub visibility applies to an entire repository. A branch cannot be public
inside a private repository. Therefore the two repositories have different roles:

- **Public downloads:** `Wgeshow/optical-design-studio-downloads` contains release
  instructions, installer assets, and checksums. Its Git history does not
  contain the application development tree.
- **Private development:** `Wgeshow/optical-design-studio-updates` contains the
  application source, tests, build recipes, and development history. Use `test`
  for experiments and pull requests into `main` for stable changes.

Keeping a GitHub repository private does not make files bundled inside a public
installer private. The current GPL PyQt6/S4 distribution includes corresponding
readable source and third-party notices. Public packaging excludes research
libraries, credentials, local session files, and machine-specific build reports.
Do not publish a package until its source/data contents have been reviewed for
the intended distribution. No organization is used for either repository.

## Publish a release

1. Develop on `test`, run relevant tests, then review and merge into private `main`.
2. Update `APP_VERSION` and `BUILD_DATE` in `app_version.py`. Build and verify a
   public-profile installer from that reviewed source. Preserve the Inno AppId
   so an upgrade retains the installation and user library.
3. Save the matching full source archive and development tag in the private
   repository. Do not upload the private source archive to the public repository.
4. Create a public draft with a numeric stable tag such as `v1.0.3`, attach the
   tested installer and its checksum, and publish after reviewing the assets.
   Experimental builds must be marked pre-release.

Windows x64 assets must use exactly
`OpticalDesignStudio-Setup-<version>-Windows-x64.exe`, with the same version in
the release tag and executable metadata. GitHub must provide a SHA-256 digest
for the asset before the application offers it. Checksums verify file integrity;
they are not independent publisher signatures.

The Windows installer is x64. Linux requires its own native build and tested
package; Windows binaries do not run natively on Linux. Updater tests on Linux
do not constitute verification of the native Linux optical solver or installer.
