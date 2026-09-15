# Optical Design Studio 1.2.0

Optical Design Studio provides optical simulation, structure editing, material
management, optimization, and CAD/COMSOL export.

## Main features

| Area | What you can do |
| --- | --- |
| **Structure** | Build multilayer stacks and square/rectangular unit cells; edit patterned regions; use shared nm/µm units; inspect 2D and 3D previews. |
| **Materials** | Maintain reusable optical-material presets; enter n/k values; import CSV files; search and download selected datasets from refractiveindex.info with citations. |
| **Simulation** | Run S4/RCWA wavelength or angle sweeps; calculate reflection, transmission, and absorption; select the highest sampled result. |
| **FDTD** | Add Meep through a dedicated WSL2 environment with direct official Ubuntu/Miniforge downloads and pinned dependencies. |
| **Optimization** | Search target wavelengths, high-Q resonances, and absorption peaks with fabrication constraints and machine-learning assistance. |
| **Fields** | Generate electric-field maps, inspect components, compare saved designs, measure overlap/confinement, and export images/data. |
| **CAD/COMSOL** | Export STEP geometry and COMSOL Java models with configurable units and repeat counts. |
| **Projects** | Autosave work, reopen runs, back up/import libraries, export CSV results, and choose the data-storage location. |
| **Desktop UI** | Native resizing, maximize and Windows Snap; custom title bar; light/dark themes; adaptive scaling; collapsible icon sidebar; GPU diagnostics. |

> [!WARNING]
> Version 1.2.0 is experimental.

### (Optional add-ons V1.2.0 Only)

Install GPU acceleration, CAD/COMSOL, and Meep from **Settings → Add-ons**.
Add-ons download only after you click **Install**, verify their checksums, and
can be removed without changing your saved projects.

See src/README.md and packaging/BUILDING.md for application and build information.
Third-party components retain their individual licenses; see
src/third-party-licenses and src/S4-source/COPYING.

Simulation are done through the use of S4 (https://web.stanford.edu/group/fan/S4/index.html#) and Meep Library (https://meep.readthedocs.io/en/master/)
