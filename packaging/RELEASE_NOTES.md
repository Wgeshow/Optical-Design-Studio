# Optical Design Studio 1.3.2 — Windows x64

This patch fixes invisible native startup with saved maximized geometry, repairs partially painted windows after Windows Restore/Maximize commands, and expands glass surface opacity to **0–100%**. The S4 solver and simulation improvements from 1.3.1 are retained.

## Native launch and saved window state

Windows investigation reproduced an invisible native surface when launching with saved maximized geometry and partially painted surfaces after Windows system-command restoration and maximization. Saved maximized or fullscreen state now takes effect after the first visible normal-window paint, allowing the native backing surface to initialize. Windows Restore/Maximize system commands now update the Qt window state along with the visible window. Restoring a minimized maximized window preserves its maximized state; normal snapped-window restoration continues through Windows.

Glass Light and Glass Dark keep the fully painted opaque workspace while maximized or in fullscreen and restore their glass policy when returned to a normal window. Controls retain their ordinary opacity.

A new compiled native-startup check exercises the real Windows Qt platform and **qt_app.main**, using isolated saved maximized preferences. It requires five checks: the initial maximized native surface, restoration, another maximize, Windows system-command restoration, and Windows system-command maximization. These check visible painting and input handling, and are required separately from the existing offscreen application/scientific checks. Passing offscreen rendering alone cannot establish that a visible native launch works.

The compiled Windows application passed all five native checks during patch validation. The exact earlier all-white compositor symptom was not independently reproduced; the opaque maximized/fullscreen fallback remains a conservative mitigation for that report.

## Glass opacity

The glass surface control now accepts and preserves the full **0–100%** range. Lower values reduce actual background and panel alpha, including a clear surface background at 0%. Input fields, buttons and text keep their opacity; the application does not fade its whole window. Calculated alpha is clamped to 0–255. Existing 65–95% appearance is preserved.

Unsupported desktops and maximized/fullscreen glass windows continue to use the opaque painting fallback. Windows still controls the Acrylic backdrop material where it is enabled.

## Inherited S4 performance and detailed-scan storage

The native S4 binary and simulation modules remain byte-identical to the verified 1.3.1 release. Its simulation improvements are retained:

- Identical internal layers reuse their solved modes when their material identity and ordered geometry match exactly.
- Spectrum and electric-field calculations for each scan point share one S4 simulation and solution. Configured CPU workers process complete points in parallel.
- Electric-field maps evaluate the retained Fourier harmonics once per depth plane and reuse them across the requested coordinates. Electric and magnetic fields are checked against scalar S4 samples; an unsupported convention falls back to scalar sampling. Bloch phase and every retained harmonic are preserved.
- Compact wavelength ranges, SQLite spectrum checkpoints, and indexed field samples bound scan bookkeeping and previews. Complete CSV exports, exact selected samples, peaks, and zoomed data remain available. Stopping a scan retains completed results.
- Contour analysis reuses identical masks across adjacent thresholds while saving every requested threshold and its lineage.

## CPU measurements from 1.3.1

These inherited 1.3.1 measurements are medians of two local runs using the same saved four-layer structure, native S4 runtime, requested Fourier basis, and output settings within each comparison. They are not new 1.3.2 benchmark results. Each worker used one CPU thread. Field timings include the requested CSV output and descriptors.

| Calculation | Comparison settings | Before | After | Speedup |
| --- | --- | --- | --- | --- |
| Spectrum | Basis 225; 6 wavelengths; 1 worker | 11.0 s | 8.3 s | 1.3× |
| Dense electric-field maps | Basis 225; 50 × 50 grid; 3 depths; 1 wavelength; 1 worker | 48.1 s | 8.0 s | 6.0× |
| Spectrum and fields | Basis 121; 25 × 25 grid; 3 depths; 4 wavelengths; 2 workers | 26.8 s | 10.9 s | 2.5× |

The dense-field comparison preserved 42,500 output rows with a maximum numerical difference of approximately 1.2 × 10⁻¹⁴. These measurements describe those cases; speed varies with geometry, basis, sampling, hardware, and output size.

Additional wavelengths or angles still require independent solves. At fixed solver and output settings, scan bookkeeping avoids repeated rewrites of the entire growing dataset. Doubling each spatial grid dimension produces four times as many points. Increasing the Fourier basis retains the RCWA solver's approximately cubic compute cost and quadratic memory cost.

## Release validation

The build syntax check compiled all 224 staged Python files. The full staged source suite ran **370 tests: 369 passed, one optional GPU test skipped, and no failures or errors**. Final packaging requires the successful staged source suite, all **11 application/scientific checks**, and all **five real Windows startup/window checks**, with results bound to the staged source hash and compiled executables. **BUILD_VERIFICATION.json** and **VALIDATION.json** record the actual final results and hashes. Native Windows validation exercises the normal application startup path in addition to the offscreen checks.

## Install or update

Release assets are **OpticalDesignStudio-Portable-1.3.2-Windows-x64.zip** and **OpticalDesignStudio-Source-1.3.2.zip**, with SHA-256 checksums. Extract the complete portable folder and keep **OpticalDesignBackend.exe** and **_internal** beside **Optical Design Studio.exe**. No separate Python installation is required for the portable package.

Close the previous application before replacing files and preserve **User Data** and any configured data directory. See **START_HERE.md** for storage, upgrade, and source instructions. The package is unsigned and includes corresponding application/native source, dependency notices, and the public tutorial. Private user libraries and saved sessions are excluded.
