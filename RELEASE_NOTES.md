# Optical Design Studio 1.3.3 — Absolute Phase Fix

This release promotes the selected **Optical Design Studio - Absolute Phase Fix** application to version **1.3.3**, rebuilt from its preserved October 13 source snapshot. The only application-source change from that snapshot is release identity and build date.

The phase extractor now uses the same transverse wavevector as the native S4 solver for absorbing media at oblique incidence. It retains the snapshot's phase display, unwrapping, reference controls, optical and device workspaces, and transport tools. Version 1.4 experimental workspace changes are not part of this release.

## Validation and scope

Validation results are recorded in **VALIDATION.json**, with hashes tying the checks to these executables and source. The release checks version metadata, phase extraction against independent Fresnel calculations, phase display/export behavior, the frozen application's self-test, and native startup in both workspaces.

This correction does not establish agreement with every published absolute-phase curve. The earlier paper absolute-phase mismatch remains unresolved. No phase offsets, sign changes, materials, or geometry were fitted to force agreement. GPU performance and a full literature/convergence sweep are not newly validated by this release.

## Install

Extract the complete Windows x64 portable archive and run **Optical Design Studio.exe**. Keep **OpticalDesignBackend.exe** and **_internal** beside it. The portable application includes its Python runtime and is unsigned. Preserve your existing User Data separately when updating; private libraries and saved sessions are not shipped.

The corresponding source archive, native source, third-party notices, and SHA-256 checksums accompany the portable build.
