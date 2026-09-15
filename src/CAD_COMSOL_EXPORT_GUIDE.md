# Structure export

On the Structure page, apply your edits, then choose **Export COMSOL…** or **Export CAD…**.

- Enter independent X and Y cell counts (1 × 1, 2 × 5, etc.). Even counts contain whole cells centered about the origin. Features crossing the outer boundary are clipped; periodic copies preserve the pattern.
- Select nm, µm, mm, or m. This changes the declared file unit, never the physical size. For example, a 0.77 µm period exported as 2 × 5 has a footprint of 1.54 × 3.85 µm, or 0.00154 × 0.00385 mm.
- Exterior media are optional finite replacements for the incident and exit half-spaces. Their thickness controls are always in µm, regardless of file units.
- CAD defaults to finite device layers without air/vacuum solids so holes are visible. Enable air/vacuum solids to include those named material domains. STEP preserves named bodies, colors and units, and can be opened in STEP-compatible CAD viewers.
- Exports run in the background from a snapshot of the applied structure. Repeat controls accept up to 1,000,000 per axis, with a practical limit of 100,000 patterned copies; there is no preview-cell restriction.

## COMSOL

Export creates Java source plus matching `.README.txt` instructions and a Windows `.build.ps1` helper. **Do not open the `.java` as an MPH model or import it through Geometry.** First run COMSOL's `comsolcompile.exe` (Windows) or `comsol compile` (Linux/macOS). Then use **File → Open → Compiled Model File for Java (*.class)** and select the compiled file. Once the model builds, save it as `.mph`. The helper accepts `-ComsolBin` for your version's `Multiphysics/bin/win64` directory and optional `-BuildMph` for batch generation. It saves each build and its logs in a new subfolder. There is no automatic fixed-name MPH overwrite when opening the class. Geometry lengths carry explicit units. The geometry consists of blocks, work planes, extrusions and Boolean operations; material domains use cumulative selections. The exported numeric region locations are a snapshot: re-export after changing periods or repeat counts.

The exporter converts the S4 loss convention to COMSOL's negative-imaginary complex permittivity convention. Tabulated n/k materials still require manual interpolation setup; their generated placeholder is not a simulation-ready material. Ports, Floquet conditions, PML domains, meshes and studies require setup in COMSOL. `pml_thickness` is only a suggested parameter. COMSOL execution has not been verified on this machine.

## Dependencies and packaging

COMSOL text export needs no COMSOL installation. STEP export uses OpenCascade directly (`requirements-cad.txt`). Runtime packages are in `cad_runtime` beside the source and are loaded lazily. The existing Python environment was not modified. CadQuery's Python wrapper is deliberately not imported because its assembly imports reproduced a native Windows shutdown failure.

For a frozen build, include `comsol_export.py`, `export_geometry.py`, `cad_export.py`, and `qt_export.py` through their imports in `qt_structure.py`. Bundle the entire `cad_runtime` directory beside these modules, preserving its native DLL directories, metadata and licenses. Alternatively install the CAD requirements in the build environment and collect OCP/VTK with freezer hooks. Do not bundle the trial folders `cad_dependencies`, `cad_stable_dependencies`, or `cad_solver_dependencies`. Test STEP export in the frozen executable before publishing. For cross-platform source distributions, ship the requirements file, not Windows binary packages.

`cad_export.read_step_metrics(path)` reopens a STEP file and returns `x_um`, `y_um`, `z_um`, and `volume_um3`, independently of its declared file units, for packaged-application smoke tests.

Validation includes a STEP export/import round trip in all four units, physical bounding-box and volume comparisons, array placement checks, and Qt dialog/export regressions.
