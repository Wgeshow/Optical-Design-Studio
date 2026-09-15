# Optical Design Studio

Version 1.1.3 improves automatic restart after an in-place update and reduces the Windows package by excluding unused legacy web and VTK visualization runtimes. It retains the COMSOL geometry fixes and Linux build helper from 1.1.2, COMSOL Java and STEP CAD export, repeated-cell export sizes,
explicit physical units, Windows native resizing/Snap, appearance controls,
collapsible icon navigation, and user-confirmed in-place updates. It retains a
portable Windows x64 ZIP, configurable saved-data location, and an explicit
user-initiated refractiveindex.info material finder.
Searching reads only the public catalog; a dataset is downloaded only after the
user selects it and confirms the import. Extract the ZIP and launch Optical
Design Studio.exe. Data defaults to User Data beside the program; choose another
folder in Settings and restart.
Development remains private; reviewed source is included with public packages.
See src/README.md and packaging/BUILDING.md for build and application details.
