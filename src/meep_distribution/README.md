# Building the managed FDTD distribution

These maintainer tools build an optional Linux filesystem; they are not run by
the desktop app. Building requires Linux Docker with Linux amd64 support. They
do not enable Windows virtualization or alter WSL distributions.

## Locked inputs

Select and record an immutable reviewed `condaforge/miniforge3@sha256:<digest>`
Linux amd64 base image. In a Linux x64 conda-forge environment containing
`pymeep` and `numpy`, export a package lock with exact builds and checksums:

```sh
conda list --prefix /path/to/reviewed/meep-env --explicit --md5 > linux-64.explicit.txt
```

Review the lock. Only HTTPS conda-forge `linux-64` and `noarch` package URLs with
checksum fragments are accepted. Keep the lock under release source control.
The base image must have `/opt/conda/bin/conda`, `useradd`, `setsid`, `/bin/sh`,
and support for creating an unprivileged user with an available UID. The image build fails if these requirements
or any package/self-test are unsatisfied.

## Build and validate

```sh
python build_rootfs.py --base-image condaforge/miniforge3@sha256:<reviewed-digest> \
  --lock linux-64.explicit.txt --app-version 1.2.0 --output build-1.2.0
```

Use the actual application release version, not the example. The build creates
the unprivileged `ods` user, installs Meep at `/opt/ods-meep`, disables Windows
executable interop in this dedicated distro, and pins the `/mnt/` automount root.
It performs a minimal real Meep execution smoke test: one coarse 2D air cell,
one sampled frequency, and a short run checking finite positive transmitted flux.
This is an installation/execution check, not comprehensive physics validation.
It preserves dependency licenses, conda package metadata, the lock, image digest
and test results. It exports `rootfs.tar` and retains the uniquely named Docker
image; only its own temporary container is removed.

The inputs/dependency versions are locked for repeatable builds. Archive timestamps,
package-generated files and environment metadata can still vary between builds;
byte-for-byte reproducibility is not claimed.

## Package and publish

Review all included packages' licenses and supply required notices and
corresponding-source archives with the release. In particular, Meep is GPL;
binary redistribution needs the applicable license and source obligations met.
Do not treat a dependency list or a general upstream homepage as corresponding
source. Supply a reviewed `SOURCE-NOTICE.txt` identifying the actual matching
source artifacts being distributed. The packaging script requires this notice.

```sh
python package_rootfs.py build-1.2.0 --source-notice SOURCE-NOTICE.txt
```

Output: `OpticalDesignStudio-Addon-meep-1.2.0-WSL2-x64.zip` and its SHA256 sidecar.
The ZIP contains exactly `addon.json` and `rootfs.tar.gz`. The manifest records
application/platform identity, Meep version, rootfs hash/size, license list,
source notice, locked build provenance and real-solver test evidence.

Before publishing, import the built tar into a fresh Windows WSL2 test machine
using a separately designated test distro/location. Verify that the default user
is `ods`, Python is `/opt/ods-meep/bin/python`, the application can access a local
Windows library path, and a tiny UI-triggered single-frequency calculation and cancellation work.
This Windows integration check is not replaced by the Linux build tests.

Publish the pack and required source/license assets on the same official GitHub
release tag as the application, or its dedicated `addons-v<app-version>` release.
The desktop client requires the GitHub asset's
published `sha256:` digest, validates the ZIP and rootfs checksum, and only marks
the imported engine ready after probing the actual installed Meep version.

Until this build/import verification/publication has occurred, the UI reports
that no compatible managed pack has been published. It must not display an
installed or working engine based solely on the presence of this source code.
