# Optical Design Studio 1.4.0 — cumulative release notes

## Downloads and report

- [Windows x64 portable program ZIP](https://github.com/Wgeshow/Optical-Design-Studio/releases/download/v1.4.0/OpticalDesignStudio-Portable-1.4.0-Windows-x64.zip): use the in-app updater, or extract the complete folder with 7-Zip and run Optical Design Studio.exe. The full runtime uses LZMA compression inside the ZIP to meet GitHub's asset-size limit; Windows Explorer extraction is not assumed.
- [Corresponding source ZIP](https://github.com/Wgeshow/Optical-Design-Studio/releases/download/v1.4.0/OpticalDesignStudio-Source-1.4.0.zip) and [version-tagged source](https://github.com/Wgeshow/Optical-Design-Studio/tree/v1.4.0).
- [Searchable HTML validation report](https://github.com/Wgeshow/Optical-Design-Studio/releases/download/v1.4.0/PUBLIC_ACCEPTANCE_REPORT.html): download and open in a browser. Includes all 28 tracked routes, equations, results and limitations.
- [Markdown report](https://github.com/Wgeshow/Optical-Design-Studio/releases/download/v1.4.0/VALIDATION.md), [build validation manifest](https://github.com/Wgeshow/Optical-Design-Studio/releases/download/v1.4.0/VALIDATION.json), and [SHA-256 checksums](https://github.com/Wgeshow/Optical-Design-Studio/releases/download/v1.4.0/SHA256SUMS.txt).

The Windows archive includes the desktop and native S4 runtime. Meep/MPB and other optional solvers retain their documented environment/setup requirements. A separate installer is not included.

**Scope:** cumulative 1.4 series relative to stable 1.3.5. Route families are application capabilities and are not all new in 1.4; the changes below are additions and repairs recorded across the alpha release history. Final downloadable archive identity and checksums belong to the release manifest.

## Additions and repairs in 1.4

- **Editable optical geometry:** disabled optical objects are retained when optical materials are edited. Object identities, coordinates, and array metadata persist; explicit enable/delete actions remain authoritative.
- **Beam-source reuse:** compatible saved finite modes may be reused when independently authored rows differ only in descriptive IDs or names. Physical/numerical fields, ordering, unknown/nested fields, and compatibility guards remain exact. A physical change is rejected before source copy or output. Beam guidance explains the existing transfer-from-results workflow.
- **Study input and range controls:** semantic material-assignment help explains layer/region optical overrides and electrical-material associations. Saved thickness/material ranges can be located, loaded, updated, or removed with selection-aware controls. Study preparation reports actual design/sample products and invalidates readiness after relevant edits.
- **Submitted option snapshots:** run options are recorded consistently in the project top-level state and active simulation-document copy while preserving geometry, inactive studies, and editor drafts.
- **Semiconductor generation and meshes:** optional exponential generation accepts an authored amplitude, nonnegative absorption, and global x origin. Uniform source settings retain their existing scalar path/schema. An explicit mesh builder previews bounds/counts and can include region/defect coordinates only on Apply.
- **Electrical materials and contacts:** help and authoring flows clarify contacts and distinguish static dielectric, frozen-conductivity, and semiconductor transport modes. These controls do not turn ideal boundaries into calibrated devices.
- **Thermal and editable-media workflows:** user-entered device/material inputs and thermal boundary setup support manually specified heat-conduction studies with review and result export.
- **High-field optics:** the native workflow accepts explicit material/state inputs and exposes energy-grid and Kramers–Kronig controls for the Franz–Keldysh model.
- **Meep study controls:** fractional spatial resolution expresses intended cells per lattice period; integrated-Gaussian source selection is opt-in and defaults off. These aid controlled studies but do not guarantee convergence.
- **Runtime and cancellation feedback:** runtime estimation, live phase progress, elapsed/remaining-time feedback where supported, and user-accessible Stop/cancellation help monitor long calculations. A configured budget or phase percentage is not a completion forecast.

The application carries studies for periodic optics, fields, sweeps, AI search, time-domain optics, 2D/3D photonic bands, electrical DC/I–V/C–V, coupled electrical/optical calculations, semiconductor transport, thermal conduction, high-field optics, PCSEL modes/transport/Beam/aperture, and lumped laser estimates. Many route families predate individual 1.4 repairs. Their acceptance evidence is summarized separately.

## Scientific snapshot

- 27 of 28 tracked routes have native UI execution; aperture response remains unexecuted.
- Five prior scoped reference agreements remain. The final Meep check adds zero.
- The stricter Meep decay check (1×10⁻⁸) completed in 8,712.703 s with 401 samples and both sampled decay flags passed.
- Same-grid maximum/RMS ΔT was 0.00585126791536 / 0.000968787349698: temporal stopping sensitivity, not convergence.
- Compared maximum balance residual changed 0.00727437037635→0.00241148249477. This derived residual is not independent absorption or proof of conservation.
- Spatial convergence and broad agreement with the cited cavity-array paper remain unresolved.

See the full public [1.4.0 release page](https://github.com/Wgeshow/Optical-Design-Studio/releases/tag/v1.4.0) for the route-by-route validation report, methods, equations, results, comparisons, and limits.

## Primary references

- Fan & Joannopoulos, “Analysis of guided resonances in photonic crystal slabs,” *Physical Review B* 65, 235112 (2002), [DOI 10.1103/PhysRevB.65.235112](https://doi.org/10.1103/PhysRevB.65.235112).
- Altug & Vučković, “Two-dimensional coupled photonic crystal resonator arrays,” *Applied Physics Letters* 84, 161 (2004), [DOI 10.1063/1.1639505](https://doi.org/10.1063/1.1639505).
- Johnson et al., “Guided modes in photonic crystal slabs,” *Physical Review B* 60, 5751 (1999), [DOI 10.1103/PhysRevB.60.5751](https://doi.org/10.1103/PhysRevB.60.5751).
- Cersonsky et al., “The diversity of three-dimensional photonic crystals,” *Nature Communications* 12, 2543 (2021), [DOI 10.1038/s41467-021-22809-6](https://doi.org/10.1038/s41467-021-22809-6).

This shareable aggregate omits local evidence, run identifiers, acceptance projects, personal libraries, logs, credentials, PDFs, and private repository details.

