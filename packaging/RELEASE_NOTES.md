# Optical Design Studio 1.3.1 — Windows x64

This update speeds up S4 spectra and electric-field scans and keeps detailed scans from accumulating their complete results in application memory. This is a local release candidate; it has not been published.

- Identical internal layers reuse their solved modes when their material identity and ordered geometry match exactly.
- Spectrum and electric-field calculations for each scan point share one S4 simulation and solution. Configured CPU workers process complete points in parallel.
- Electric-field maps evaluate the retained Fourier harmonics once per depth plane and reuse them across the requested coordinates. Electric and magnetic fields are checked against scalar S4 samples; an unsupported convention falls back to scalar sampling. Bloch phase and every retained harmonic are preserved.
- Compact wavelength ranges, SQLite spectrum checkpoints, and indexed field samples bound scan bookkeeping and previews. Complete CSV exports, exact selected samples, peaks, and zoomed data remain available. Stopping a scan retains completed results.
- Contour analysis reuses identical masks across adjacent thresholds while saving every requested threshold and its lineage.

## Maximized glass windows

Glass Light and Glass Dark switch to a fully painted opaque workspace while maximized or in fullscreen, then restore their glass policy when returned to a normal window. This avoids depending on the Windows Acrylic compositor during that transition. Acrylic is intentionally suspended while maximized.

The reported all-white compositor screen was not reproduced in the local checks. This change is a conservative mitigation for the maximize transition; the release checks verify opaque painting while maximized and the glass policy after restoration in both glass looks.

## Measured CPU performance

These are medians of two local runs using the same saved four-layer structure, native S4 runtime, requested Fourier basis, and output settings within each comparison. Each worker used one CPU thread. Field timings include the requested CSV output and descriptors.

| Calculation | Comparison settings | Before | After | Speedup |
| --- | --- | --- | --- | --- |
| Spectrum | Basis 225; 6 wavelengths; 1 worker | 11.0 s | 8.3 s | 1.3× |
| Dense electric-field maps | Basis 225; 50 × 50 grid; 3 depths; 1 wavelength; 1 worker | 48.1 s | 8.0 s | 6.0× |
| Spectrum and fields | Basis 121; 25 × 25 grid; 3 depths; 4 wavelengths; 2 workers | 26.8 s | 10.9 s | 2.5× |

The dense-field comparison preserved 42,500 output rows with a maximum numerical difference of approximately 1.2 × 10⁻¹⁴. These measurements describe those cases; speed varies with geometry, basis, sampling, hardware, and output size.

Additional wavelengths or angles still require independent solves. At fixed solver and output settings, scan bookkeeping avoids repeated rewrites of the entire growing dataset. Increasing both spatial grid dimensions doubles each dimension and produces four times as many points. Increasing the Fourier basis retains the RCWA solver's approximately cubic compute cost and quadratic memory cost.

## Install or update

After verification, the local build provides **OpticalDesignStudio-Portable-1.3.1-Windows-x64.zip** and **OpticalDesignStudio-Source-1.3.1.zip**, with SHA-256 checksums. Extract the complete portable folder and keep **OpticalDesignBackend.exe** and **_internal** beside **Optical Design Studio.exe**. No separate Python installation is required for the portable package.

Close the previous application before replacing files and preserve **User Data** and any configured data directory. See **START_HERE.md** for storage, upgrade, and source instructions. The package is unsigned and includes corresponding application/native source, dependency notices, and the public tutorial. Private user libraries and saved sessions are excluded.
