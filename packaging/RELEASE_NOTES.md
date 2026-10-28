# Optical Design Studio 1.4.0-alpha.3 — UI Usability Update

Experimental Windows x64 release · 28 October 2026

This downloadable build includes the usability changes developed while constructing simulation structures through the native interface. It follows 1.4.0-alpha.2. Download the Windows x64 Portable .7z archive, extract the complete archive with 7-Zip, and run Optical Design Studio.exe from the extracted folder. No separate Python installation is needed for the bundled desktop and S4 runtime. The corresponding Source ZIP is a separate download for inspection and rebuilding.

## Changes
- Start an empty photonic crystal, edit the full-precision geometry, select TE/TM, review submitted inputs and read saved bands on their actual symmetry path.
- Edit incident and exit media for S4 and Meep; see finite-device context and optical-only result controls.
- Create electrical materials with blank properties, retain explicit edits, and author constant-conductivity materials without irrelevant carrier placeholders.
- Apply and check voltage schedules beside the editable values. Export dialogs identify the selected saved bias and run.
- Display nearly constant fields without magnifying roundoff into a misleading full-range color map; an explicit control can reveal the tiny range.
- Clear stale thermal and Meep results after invalid loads and show fuller input reviews.
- Repeat manually authored PCSEL layer blocks with fresh identities and one undo operation.
- Improve solver discovery, editable-choice recovery and steady-state laser model labels.

## Validation scope
Seven of the 28 simulation/tool routes have been constructed and executed through the UI during this campaign. Five have scoped agreement with an independent paper equation or reference: MPB 2D, Legume 2D, thermal, electrical DC and electrical C–V. This is not full validation of every model or arbitrary edited device.

C–V was independently authored through the UI, with 8³, 16³ and 32³ meshes and a final five-point voltage sweep. Its signed electrode derivative agrees with Liu et al. (2023), Eq. 4 for the analyst-selected homogeneous capacitor (4.4270939094 fF). The maximum final relative difference is 3.742e-14. This checks static ideal capacitance, without fringing, semiconductor transport or AC-frequency response. Roundoff agreement does not establish a convergence order.

See VALIDATION.json for the checks actually run on this exact packaged build. Source/offscreen checks, automated frozen startup and manual packaged-app navigation are recorded separately. Built-in application catalogs are distributed for normal operation; the campaign acceptance structures were not imported from them.

## Known limits
S4 line-shape agreement and tight 3D diamond convergence remain unresolved. Several recent controls still need route-specific native acceptance. A repeated access violation on closing the development application remains under investigation; any packaged close result is reported separately and does not establish a general fix. Optional MPB/Meep, Legume, Sesame and other solvers retain their runtime requirements and may require their setup workflow.

This prerelease does not replace stable 1.3.5 in the stable updater. Preserve your existing projects and data, and extract the new package to a separate folder. The package excludes personal run libraries, session files, credentials and private paper PDFs. Matching source, third-party notices and checksums are supplied.
