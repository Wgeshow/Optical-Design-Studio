# Optical Design Studio 1.3.4

Fixes two packaging errors in 1.3.3:
- Material search (including GaAs) failed with a missing-file error while creating an HTTPS context. The required Python certificate policy file is now included.
- PDF and SVG phase/figure exports failed because export backends and font dependencies were missing. These are now included.

The portable Windows ZIP supports the in-app software updater and includes a complete SHA-256 payload manifest. Existing 1.3.3 installations missing the certificate policy file need the small HTTPS repair before their update check can connect; the local installation used for verification has been repaired.

Preserves the 1.3.3 Absolute Phase Fix simulation code. This release changes packaging and release identity only; it does not add physics validation or resolve prior paper-comparison limitations.
