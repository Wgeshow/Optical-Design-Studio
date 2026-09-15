# MEEP FDTD add-on

The native desktop application uses a separate Linux/macOS Python Meep runtime.
On Windows the normal installation uses a dedicated, versioned WSL2 distribution
with Meep already installed. Expert setup can use an existing Linux runtime.
Opening the application or Settings never installs or downloads anything.

## Setup

1. Open Settings → Add-ons and click **Install FDTD engine**. The application
   checks Windows support and the official GitHub release for a package matching
   this application version and WSL2 x64 platform. If no pack is published, it
   reports that fact without downloading or installing anything.
2. If Windows support is missing, click **Set up Windows support**. Read the
   explanation and approve Windows' administrator prompt. This starts Microsoft's
   WSL installation without a Linux distribution. Hardware virtualization must be
   enabled; Windows may require a restart. The app never restarts Windows itself.
3. Click **Install FDTD engine** again after prerequisites are ready. The pack is
   downloaded, verified against its GitHub SHA256 digest and manifest, and imported
   using `wsl --import ... --version 2`. There is no location selector: it uses
   `%LOCALAPPDATA%/OpticalDesignStudio/FDTD/<app-version>/distro`.
4. The application checks that the registered distribution points to its owned
   directory and successfully imports the expected Meep version before enabling
   it. Existing Linux distributions and the user's default distribution are not
   modified. No unregister commands are used.

The **Expert setup** section is collapsed by default. It accepts Linux paths to
an existing interpreter and Conda installation. For example:
`/opt/miniforge3/bin/conda` and
`/opt/miniforge3/envs/ods-meep/bin/python`. **Check & save runtime** validates
an existing installation; **Install into existing Conda** creates the isolated
`ods-meep` environment with conda-forge packages.

Installation is user-initiated and uses Meep's supported Conda distribution.
It is a preconfigured Linux filesystem, not a native Windows DLL pack. See the
[official installation guide](https://meep.readthedocs.io/en/latest/Installation/).
Microsoft documents [custom-distro imports](https://learn.microsoft.com/en-us/windows/wsl/use-custom-distro)
and the [WSL setup commands](https://learn.microsoft.com/en-us/windows/wsl/basic-commands).

## Simulating a structure

The FDTD panel takes a snapshot of the same materials, finite layers, periodic
circles, ellipses and rotated rectangles used by the Structure page. Circles
become finite cylinders; ellipses use finely tessellated prism extrusions.
Periodic boundary-crossing regions are copied so wrapped geometry is preserved.

- **2D** solves the selected XZ cross section extruded along Y. This changes the
  physical geometry of a hole array into a grating; use 3D for the actual array.
- **3D** solves the complete periodic unit cell.
- Excitation is a Gaussian broadband plane pulse at normal incidence, using s
  (Ey) or p (Ex) polarization. X/Y boundaries are periodic and depth boundaries
  use PML. Oblique incidence, finite nonperiodic devices, arbitrary sources,
  MPI and GPU Meep are not exposed in this first integration.
- Length is in micrometres; time is in µm/c. Frequency samples are evenly spaced
  in inverse micrometres, so their wavelengths are not evenly spaced.
- One homogeneous incident-medium reference simulation precedes the device
  simulation. Reflection subtracts the incident Fourier fields; reflected and
  transmitted powers are normalized by reference transmission.
- Each run stops when the field-energy decay condition is met, or at the chosen
  maximum time after the source stops. Hitting the maximum produces a visible
  convergence warning. Always check convergence versus resolution, PML, padding
  and runtime before interpreting numerical results.

## Materials and results

Positive lossless constant permittivity/index translates exactly. A complex
constant is not a causal broadband material and is rejected with instructions
to supply n,k data. With dispersion fitting enabled, tabulated passive n,k is
fitted to nonnegative Lorentz/Drude poles. The entire requested band must be
covered, and an independent dense validation grid must stay within 5% relative
permittivity error (scaled by max(|epsilon|,1)); a failed fit stops the job.
This fit tolerance is not a guarantee of spectral accuracy, particularly for
high-Q resonances. The fitted model and its error are saved for review.
Incident and exit media must be constant and lossless for the monitor/PML setup.

Each calculation is recorded in the existing library with `project.json`,
`fdtd_job.json`, `results.csv`, `fdtd_summary.json`, the standalone worker source,
and its log. Optional centre-frequency XZ DFT field maps are saved in NPZ format.
These field amplitudes are explicitly labelled **raw, not incident-normalized**.
No R/T/A values are clipped to hide power-balance or convergence errors.

Solver/expert-setup cancellation signals only the process group launched for
that operation, with a forced stop fallback. Download cancellation stops before
importing. Once a Windows WSL import has begun, cancellation waits for that
bounded import operation to finish safely and preserves its receipt/VHD; it
does not activate the runtime. **Check availability** can verify it later.
Setup shutdown waits for its QThread to finish before the application closes.
An unsuccessful import directory is preserved for inspection, never deleted.

## Verification

`python -m unittest tests.test_meep_managed tests.test_fdtd tests.test_qt_fdtd` checks exact slab and
periodic geometry, passive dispersion fitting on independent synthetic data,
invalid material/band/grid rejection, runtime command boundaries, version/digest
validation, exact distro ownership, no-overwrite handling, and Qt controls.
The real-Meep air-cell conservation test runs only where `import meep` succeeds;
it is explicitly skipped on the Windows host if no Linux/WSL Meep runtime exists.
For a configured WSL runtime, copy a saved job folder and launch its worker with
the configured interpreter, or start the same calculation from the FDTD page.

The Meep calls follow the [Python API](https://meep.readthedocs.io/en/latest/Python_User_Interface/)
and [reference-flux subtraction tutorial](https://meep.readthedocs.io/en/latest/Python_Tutorials/Basics/).

## Release-maintainer build

See `meep_distribution/README.md`. A source-only integration does not imply the
managed pack is available. The rootfs must be built on a Linux Docker host,
pass actual Meep air-cell/Fresnel checks and a Windows WSL2 import test, then be
published as the named release asset with license/corresponding-source artifacts.
