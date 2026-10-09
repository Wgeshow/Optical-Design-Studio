# Optical Design Studio 1.3.1

## Start the Windows portable application

1. Download **OpticalDesignStudio-Portable-1.3.1-Windows-x64.zip** and **SHA256SUMS.txt** from the same release.
2. Verify the archive's SHA-256 checksum if you want to check download integrity:

   ```powershell
   Get-FileHash -Algorithm SHA256 -LiteralPath .\OpticalDesignStudio-Portable-1.3.1-Windows-x64.zip
   ```

   Compare the result with the entry in **SHA256SUMS.txt**.
3. Extract the entire ZIP to a folder where you can write files. Open the extracted **Optical Design Studio** folder and run **Optical Design Studio.exe**.

Keep **OpticalDesignBackend.exe**, **_internal**, and the supplied documents and notices together. Launch from the extracted folder, not the ZIP preview. The portable application contains its Python and calculation runtime; a separate Python installation or installer is not required.

This release is unsigned. Windows may display a publisher or reputation warning. The checksum verifies archive integrity, not publisher identity; follow your organization's software policy. Do not disable antivirus or Windows security to install it.

## Keep existing work

Save open projects, finish calculations, and close the old application before upgrading. Back up your saved project JSON files and the data directory shown in **Settings → Data storage**.

For a default portable installation, data lives in **User Data** beside the executables. When using a new application folder, preserve that folder. If you configured another data location, preserve it and the adjacent **portable_settings.json** setting; confirm the selected location after launch. Extraction does not move an existing library for you. **Help → Quick actions → Open library folder** opens the active library.

Supported installations can use **Help → Updates** after 1.3.1 is published. Read the offered release information before using its download and installation controls. **Help → About** shows the running version.

## First session

Open **Help** to load the bundled Silicon example or inspect its actual saved simulation results. The tutorial uses constant-index approximations for a 220 nm Silicon layer on SiO₂, 100 nm radius Air holes, and a 540 nm square period. The saved spectrum covers 1515–1555 nm; the illustrated fields are at 1550 nm. Loading the example restores inputs; changing the structure requires a new calculation for corresponding results.

In **Structure**, choose a layer by name using the **Layer** dropdown or the layer stack. Edit its material or thickness and use **Apply layer**. Use **Apply lattice** and **Apply pattern** for those edits. The applied structure supplies Materials, Simulation, sweeps, and AI Search.

In **Materials**, inspect the original n/k samples and source, or use **Import CSV**, **Find online**, or **Enter values**. Select the wavelength unit explicitly when importing. Interpolation is a physical calculation setting: **Linear (in log k)** requires every k sample to be positive. **Display color**, layer colors, and **Preview opacity** affect only geometry display. Source attribution and editable Notes are stored separately.

In **Settings → Appearance**, choose **B Light**, **B Dark**, **Glass Light**, or **Glass Dark**. Each look keeps its own colors. **Reset colors** restores that look's defaults, and the live preview displays your actual applied structure.

Glass Desktop Acrylic requires Windows 11 build 22621 or later. Windows may use a solid backdrop because of transparency, accessibility, power, or remote-session settings. A solid fallback is also used on unsupported desktops. Choose a B look whenever you prefer an opaque window.

## Plots and files

Hover over plot icons for **Fit**, **Pan**, **Zoom**, **Copy**, **Export**, and **Figure settings**. Live charts fill their panels; publication dimensions are set through the export controls. Plot percentages do not rewrite the saved numeric values. Table values are original samples and complete CSV exports retain the raw datasets, while interpolated curves are evaluated from the chosen material model.

Use **Ctrl+O** to open a project, **Ctrl+S** to save, **Ctrl+Shift+S** to save as, and **Ctrl+N** for a new project. Run and Stop remain in the bottom bar. Consult **Help → User guide** for units, convergence checks, MEEP setup, comparisons, and saved-field conventions.

## Source package

**OpticalDesignStudio-Source-1.3.1.zip** is the corresponding source package, not the ready-to-run Windows application. It requires Python 3.12, the listed dependencies, and an S4 native extension built for your platform. Read its **README.md** and **src/DESKTOP_GUIDE.md** before running or rebuilding. Optional MEEP, GPU, CAD, and machine-learning components have their own runtime requirements.

## Troubleshooting

If the application or backend is missing, extract the complete archive again and check whether your security software quarantined a file. If a calculation fails, retain the displayed error and the log information from **Help → Quick actions**. Loading inputs is not the same as calculating results; run the solver after applying changes. Older saved electric-only field snapshots remain supported.

All supplied third-party components retain their own licenses. See **THIRD_PARTY_NOTICES.md** and **THIRD_PARTY_LICENSES**.
