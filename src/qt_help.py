"""Searchable local guide for the controls in the B workspace."""
from pathlib import Path
import json
from html import escape
from PyQt6.QtCore import Qt,QUrl,QSize,QPointF,QRectF
from PyQt6.QtGui import QDesktopServices,QIcon,QPixmap,QImage,QPainter,QPen,QColor,QPainterPath,QTextCursor
from PyQt6.QtWidgets import (QWidget,QHBoxLayout,QVBoxLayout,QLineEdit,QListWidget,QListWidgetItem,
    QTextBrowser,QTabWidget,QLabel,QPushButton,QScrollArea,QFrame,QStackedWidget,QGridLayout,QSizePolicy,QBoxLayout)
from qt_surfaces import WorkspacePanel
from qt_common import COLORS,theme_manager
from qt_icons import navigation_icon

# Help is intentionally the home for explanatory prose removed from the workspaces.
# Screenshots show actual native controls, never generated scientific results.
ASSET_ROOT=Path(__file__).resolve().parent/'help_assets'
REAL_EXAMPLE_TOPIC='Silicon example: actual spectrum and fields'
REAL_EXAMPLE_ROOT=ASSET_ROOT/'silicon-reference-run'
GUIDES={
'Getting started': '''<ol><li>Create a project with Menu → New project, or open a portable project JSON. Save a copy before changing an existing device.</li><li>In Structure, set lattice dimensions, choose the dimension unit, add finite layers between the incident and exit media, and Apply layer. Add holes or filled regions and Apply region.</li><li>In Materials, inspect each optical dataset and confirm its wavelength coverage. Assign the intended material to every layer and region.</li><li>In Simulation → S4 · RCWA, choose wavelength or angle mode, range, step, polarization and angles. In Settings → Performance choose basis and computing resources. Start with a small calculation.</li><li>Run simulation; inspect R/T/A and the sample cursor. Export the complete CSV or reopen the saved run.</li><li>Refine basis, wavelength spacing and field sampling to check convergence before interpreting narrow peaks or accepting a search candidate.</li></ol><p>Structure is shared by new simulations and searches. Saved results retain the snapshot that produced them. Fields and Saved results are inside Simulation.</p>''',
'Structure and layers': '''<p>Select a stack layer or choose its name from the Layer dropdown. Edit name, material and finite thickness, then Apply layer before switching layers or running a calculation. Add above / below inserts using the current form; Duplicate copies regions; Move up / down changes finite-layer order; Delete removes its regions too.</p><p>The first and last layers are semi-infinite incident and exit media. Their stored thickness is zero; the preview displays only finite padding. Repeat a layer block copies the inclusive finite-layer range: two additional copies of A–B produce A–B–A–B–A–B. Undo restores earlier structure edits (up to 30 retained steps); loading another project clears that history and added material presets remain.</p><p>Applied geometry is checked during edits and calculation inputs are checked before a run; these checks do not establish optical convergence or material validity. Layer color and Reset color affect display only. Colors are stored in portable projects and follow renamed or duplicated layers. Eye / visibility controls, Show holes, Layer colors, Edges and Axes never remove physical geometry from the solver.</p>''',
'Shapes, lattice and units': '''<p>Add region creates a material inclusion; choose Air for an air hole. Apply region commits the selected region. Duplicate then move its center to avoid coincident copies. Circle sizes are radii; ellipse X/Y sizes are radii; rectangle X/Y sizes are full widths. Positions and sizes use the selected form unit; rotation uses degrees.</p><p>100 nm = 0.1 µm. Switching Dimension unit converts display values without changing size. Lattice and advanced table columns use their separately labeled µm units; wavelength is nm. Advanced editing exposes layer/region tables, positions and repetition. Apply table edits before calculation.</p><p>Geometry summary reports the applied finite-layer thickness/count, lattice, patterned-layer count and a single circular-hole radius when applicable. Multiple circles show Multiple; noncircular shapes have no circle radius.</p>''',
'Geometry views': '''<p>3D Stack shows layer ordering and periodic regions. Drag to rotate, scroll or use Zoom + / −, and Reset view to restore the camera. Cross-section is a cut through the stack; Unit cell shows plan geometry. Their view controls change only the preview.</p><p>The Structure preview can repeat one, three or five cells and change the side-view Y cut. Exterior padding is illustrative. A geometry view contains no computed field intensity. Applied changes are shared with new solver jobs; an uncommitted form is not the applied structure.</p>''',
'Common units': '''<table cellspacing="8"><tr><th>From</th><th>To</th><th>Multiply by</th></tr><tr><td>µm</td><td>nm</td><td>1,000</td></tr><tr><td>nm</td><td>µm</td><td>0.001</td></tr><tr><td>mm</td><td>µm</td><td>1,000</td></tr><tr><td>µm</td><td>mm</td><td>0.001</td></tr></table><p>Use the unit printed beside each control. Geometry form units can change; advanced geometry tables and search ranges use µm, wavelengths use nm, and rotation/incident angles use degrees. CSV wavelength units are selected explicitly, never inferred.</p><p>Raw R/T/A are dimensionless fractions; spectrum plots show 0–100% of incident power. Δn is in RIU and resonance sensitivity in nm/RIU. Carrier densities use cm⁻³, mobilities cm²/(V s), depth profiles µm and absorption coefficient cm⁻¹. FDTD frequency is inverse µm and time µm/c.</p>''',
'Geometry export': '''<p>Open the Structure geometry export controls to create supported STEP or COMSOL geometry. Choose cell repeats, file units and whether to include exterior media. Exterior padding gives semi-infinite media finite exported thickness; choose that thickness explicitly. Air/void inclusion depends on the selected export format.</p><p>Exporting geometry does not run a solver or establish convergence. CAD add-ons may need installation in Settings → Add-ons. COMSOL geometry and carrier workflows are documented in CAD_COMSOL_EXPORT_GUIDE.md and the carrier guide supplied with the program.</p>''',
'Materials': '''<p>Search project materials or saved presets. Inspect n / k, source and covered wavelengths. Apply material to layer assigns the selected entry; a preset is added to the project when needed. Removing a project material does not remove its saved preset, and a material used by geometry cannot be removed.</p><p>Constant n,k is an explicit approximation. A tabulated dataset has wavelength dependence; solver requests must stay inside its covered band. With the passive sign convention, k describes attenuation and ε=(n+ik)². Do not replace a dispersive dataset with a constant merely to bypass a coverage error.</p><p>Record the dataset page, publication, sample conditions and wavelength units. Save a named preset for future projects; prior saved versions are retained. Export optical constants CSV uses the selected real dataset.</p>''',
'Import CSV and manual materials': '''<p>In Import CSV, set wavelength unit before choosing files; units are never guessed. Supported layouts include wavelength,n,k and separate wl,n / wl,k sections. An n-only file requires explicitly choosing k = 0. Review name, source and coverage after import.</p><p>Enter values accepts manual wavelength samples. For a constant pair select Constant n,k (explicit approximation), enter n and k, then save. Import and manual entry create project datasets and reusable presets. Keep measured or published attribution separate from your approximation notes.</p><p>Find online retrieves external optical data. Review the selected dataset, reference, temperature/sample conditions and available band before importing; a material name alone does not identify a dataset. Network failure is not a valid zero-loss result.</p>''',
'Simulation and sample readout': '''<p>S4 · RCWA solves the applied periodic layered structure. Set wavelength or angle mode, start, stop, step, polarization, θ and φ with their labeled units. Wavelength mode scans λ; angle mode changes the selected incidence variable. Basis and CPU/GPU resources are shared through Settings.</p><p>R/T/A plots use percentages of incident power with 0–100% axes. Raw CSV values remain power fractions: 0.2 means 20%, not 0.2 watts. Inspect their sum and numerical stability. Click the spectrum or select a sample number to read the nearest calculated point; the cursor does not create a new solve or an interpolated resonance.</p><p>Spectrum, Samples, Phase and Electric fields are result views. The on-screen sample table can show only the first 10,000 rows; Export spectrum CSV retains all calculated samples. Recent runs load completed measurements; Load setup explicitly restores their design.</p>''',
'Spectral phase': '''<p>Enable Measure phase before an S4 run to save specular reflection/transmission phase. Power spectra alone cannot reconstruct phase. The Phase view displays saved complex-amplitude phase data; angle wrapping and phase-change behavior depend on that measurement.</p><p>Near vanishing reflected or transmitted amplitude, phase is poorly defined and needs careful interpretation. Use the recorded wavelengths and matched illumination when comparing phase. See SPECTRAL_PHASE_GUIDE.md for the supported phase conventions and saved columns.</p>''',
'MEEP FDTD': '''<p>On Windows, Meep uses a separate managed WSL2 runtime. Settings → Add-ons → Install FDTD engine checks for a matching published pack; opening Settings does not install anything. Set up Windows support can require an administrator prompt and restart. Expert setup validates an existing Linux interpreter.</p><p>2D solves an XZ cut extruded along Y: a hole array becomes a grating. Use 3D for the complete periodic unit cell. The supported source is a normal-incidence Gaussian broadband plane pulse with s (Ey) or p (Ex) polarization. X/Y are periodic; depth uses PML. Arbitrary sources, oblique incidence, GPU Meep and MPI are not exposed.</p><p>Length uses µm and time µm/c. Frequencies are evenly spaced in inverse µm, so wavelength samples are not uniform. A homogeneous reference simulation precedes the device; reflection subtracts incident Fourier fields and powers normalize to reference transmission.</p><p>Check resolution, PML, padding and maximum time. A maximum-time termination produces a convergence warning. Passive tabulated materials require validated dispersion fitting; complex constant index is rejected as a broadband model. Incident/exit media must be constant and lossless. Optional XZ DFT field amplitudes are raw, not incident-normalized. Saved job, fit, summary and worker logs are available with the run.</p>''',
'Δn sweep and carrier density': '''<p>Choose a project material and check layers to perturb; background and regions using that material in those layers change, while other occurrences and the library stay unchanged. Manual Δn adds a real refractive-index shift and keeps k fixed. Constant ε is first converted to its principal complex refractive index; Δn is not additive ε.</p><p>Equal shift uses one shared axis. Independent layer bounds enumerate combinations; equal start/stop with one sample gives a fixed offset. A zero-shift baseline is included at most once. The wavelength range and illumination come from S4 · RCWA; wavelength mode needs at least three samples. There is a limit of 200 requested combinations plus baseline and 200,000 wavelength samples.</p><p>Carrier density mode configures reference and biased electron/hole concentrations in cm⁻³ using the carrier dialog. Its material model can change both index and absorption; it is not equivalent to the manual real Δn approximation. Review material parameters and model applicability in the carrier guide.</p><p>Choose R/T/A, peak/dip, reference λ and search radius. Tracking locates a sampled local feature near the baseline; endpoints are excluded. Missing features remain blank. Shared sweeps report Δλ/Δn in nm/RIU; independent sweeps do not claim one multi-parameter sensitivity.</p>''',
'Fixed-wavelength Δn readout': '''<p>The baseline peak/dip selects one locked λ₀. Fixed-wavelength response measures every shifted spectrum at that same baseline sample, even when its resonance moves. Change from baseline is the signed difference; Overlaid spectra shows full curves and λ₀.</p><p>Underlying R/T/A are power fractions, not watts. Response plots show percent and baseline-change plots show signed percentage points; a 0.01 fraction change is 1 percentage point. An unresolved baseline feature leaves the readout unavailable. In independent sweeps, select a Δn axis; each curve holds other offsets fixed as recorded in its legend. The UI displays at most 24 curves, but CSV includes every case.</p><p>index_shift_spectra.csv retains R/T/A, index_shift_features.csv records sampled feature positions, and index_shift_readout.csv records λ₀, baseline and changes. Tracking does not establish mode identity or sub-sample peak location; inspect crossing/splitting curves and refine wavelength/basis.</p>''',
'Carrier models and depth profiles': '''<p>The carrier dialog uses absolute reference and biased electron/hole concentrations. Reference-data mode assumes library n/k already include the reference carrier state; Undoped mode adds absolute corrections for both states. Bias voltage is supplied metadata, not a prediction of carrier concentration.</p><p>The implemented free-carrier Drude approximation uses explicit conductivity masses and fixed mobilities. Increased carriers lower n and increase loss in this model; depletion reverses the change. Negative resulting k is rejected. GaAs/custom materials are not automatically validated by a silicon model; review source assumptions, editable masses/mobilities and the 1000–2000 nm guard. Concentrations above 10²⁰ cm⁻³ are rejected.</p><p>Depth CSV uses layer,z_um,reference_electron_cm3,reference_hole_cm3,electron_cm3,hole_cm3 and covers both endpoints of every selected finite layer. All states use the same depth/reference grid. Duplicate nodes marked side=left then side=right preserve discontinuities. Slice density is evaluated at midpoints; region geometry and total thickness are preserved. Refine slice sampling.</p><p>The reported depth-averaged Δn is thickness weighted, not field weighted or modal effective index; spectra use the full sliced model. COMSOL four-file import has explicit layer mapping, units and audited optional negative-noise cleanup. The abrupt-junction estimator assumes a homojunction/depletion model and does not solve transport or automatically generate a profile.</p>''',
'Electric fields': '''<p>Simulation → Fields → Current Structure calculates fields at the selected wavelength. Choose layer for the XY top view, grid samples per axis and depth samples per layer. XZ spans the stack. Inspect Ex/Ey/Ez, total field quantity, logarithmic display or arrows with the controls available in the view.</p><p>S4 electric-field amplitudes use the incident-amplitude convention; intensity is not automatically a power or energy density. MEEP optional field maps use raw DFT amplitudes and must not be treated as the same normalization. Finer grids/depths increase calculation time and storage; interpolation adds no solved detail.</p><p>Save image exports the current visualization. Export data retains complex field samples; Copy plot places the displayed image on the clipboard. Open saved files exposes the full result directory. Check the selected component and normalization before comparing brightness between runs.</p>''',
'Field comparison and 3D playback': '''<p>Compare saved designs selects reference, comparison and a common layer. Physical coordinates retain distances; layer-relative coordinates help compare changing geometries. Shared scales and overlap/confinement/centroid measures describe steady-state field differences, not time propagation.</p><p>3D field playback displays sampled volume points or interpolated surfaces with threshold, layer and component controls. Phase animates steady-state harmonic field arrows; it does not simulate pulse travel. Intensity surfaces are phase independent, and energy-flow displays are time averaged. Surface interpolation cannot add spatial resolution.</p><p>Export comparison keeps maps, measures and source fields. Use matched wavelength, illumination, normalization and sampling for interpretable comparisons.</p>''',
'Recent runs and saved results': '''<p>Load selected run inspects its stored measurements without replacing current geometry. Load setup / Reopen in editor restores the saved original setup or explicitly selected design. Review that choice before starting a new calculation.</p><p>Saved results filters by title, type and status. Refresh after jobs or imports, select a run, inspect results/notes, export CSV or a complete run ZIP. Portable project JSON embeds materials and applied geometry. A run archive also retains the calculation conditions and result files.</p><p>Back up / share exports the selected library, with optional application files; import merges supported library data. Keep a backup before transfer. Changing Data storage selects a library location rather than silently moving every old result. Never delete the only copy of a campaign checkpoint or measured field dataset.</p>''',
'Simulation Sweep': '''<p>Target wavelength searches within the target tolerance, minimum Q, hole bounds and other parameter ranges. Target qualification requires absorption strictly above 99%, a resolved peak within tolerance, fabrication bounds and higher-resolution agreement. Peak-center tolerance does not guarantee that absorption at the exact target is above 99%.</p><p>Circle r/a must be below 0.6 and periodic holes must leave a positive bridge. Linked radii create one common variable for checked existing circular air holes; their centers are not moved and missing holes are not created. Geometry ranges use labeled µm units; wavelength is nm.</p><p>Explore designs offers exhaustive, ML-assisted and hybrid search over parameter bounds. Set detection/sampling, trial budget, constraints and verification accuracy. Save/load preserves configuration; renaming a manually bounded layer requires reviewing its old target name.</p><p>Predicted or screening leaders remain candidates until higher-accuracy verification. Use selected design applies that geometry to Structure; inspect its verification status. Highest verified Q found does not establish a continuous global optimum.</p>''',
'AI Search': '''<p>Set up owns wavelength, polarization, angles, basis, field objective and parameter ranges. Structure geometry and Settings computing resources are shared, but Simulation edits do not change AI illumination. Copy ranges is an explicit copy.</p><p>The field-confinement objective supports an aligned circular air hole in each selected perforated layer above an unperforated substrate. Review strengths and coverage targets, XY/full-stack XZ fields, depth line, contours and RTA. Contour extraction is postprocessing, not a new optical simulation at each contour level.</p><p>Training uses adaptive sampling or a full range scan. Preview counts; optional NEW simulation limit 0 means no limit. Independent test designs are excluded from fitting and recommendations. Prediction vs S4 and Validation errors use those held-out results; prediction alone is not verification.</p><p>Search proposes untested designs, measures them, refits and verifies finalists at larger basis/grid. A recommended design is written only when the verified constraints and numerical agreement pass. Use selected design can still apply an explicitly chosen screening candidate with its status visible.</p>''',
'AI checkpoints and reference fields': '''<p>Stop requests cancellation. Completed observations are checkpointed in campaign.json during the run; inspect the saved status and last completed design before resuming. An interrupted native evaluation is not a completed observation. Resume validates geometry, wavelength, ranges, basis, sampling and collection plan. Changed settings start a new campaign rather than silently pooling incompatible observations. A resumed NEW simulation budget counts new evaluations only.</p><p>Fit / check saved data only performs no new S4 solves. Compatible campaigns and standalone field samples can be reused; missing RTA may still require native work. Screening and verification observations remain separate. Models are refit from recorded JSON observations rather than loaded executable model objects.</p><p>Match a saved field shape accepts one or more semicolon-separated field directories. Wavelength, grid, depth/contour sampling and features must be compatible. Reference similarity guides screening but does not override strength/coverage constraints; high-accuracy verification checks physical requirements.</p><p>Inspect campaign.json, model_validation.json, design_results.csv, design_models.jsonl and each design’s fields/rta records. Full contour masks can use substantial disk space. A fine contour increment does not improve spatial field resolution.</p>''',
'Appearance and colors': '''<p>B Light, B Dark, Glass Light and Glass Dark share layout and functions. Choose a theme card in Settings → Appearance, or use Menu → Appearance. Edit accent, background, panels, inputs, text, secondary text and borders with a color swatch or six-digit hex. Each look keeps its own local palette; Reset colors restores its defaults. The right-hand preview uses your actual applied structure.</p><p>The rounded outer boundary, including the title bar and Windows controls, is the application window. Glass looks use Windows Desktop Acrylic to frost the actual desktop and other application windows behind it, while text and controls remain sharp. Glass surface opacity adjusts panel transparency and the background tint. The application does not paint wallpaper outside its window or blur scientific data. Desktop Acrylic requires Windows 11 build 22621 or later; Windows transparency, accessibility, power and remote-session preferences can substitute a solid material. Unsupported platforms and offscreen previews use a solid fallback.</p><p>In Structure, select a layer and choose Layer color to customize that layer. Preview opacity controls the selected layer's material in every layer using it: 100% is opaque and 0% is invisible. Reset removes the material override. Layer colors and material preview opacity are saved in portable projects and do not change refractive index, extinction coefficient or any solver input.</p><p>UI scale adjusts display size; maximize the window or reduce scale when controls need more room. Interface preferences are local desktop settings. Choose sufficient text/background contrast after changing colors.</p>''',
'Performance and convergence': '''<p>Fourier basis controls RCWA accuracy and cost. Increase basis and refine wavelength/grid sampling until the quantity of interest stabilizes. A narrow high-Q feature needs sufficient spectral samples; a search result is not a convergence study.</p><p>Settings → Performance chooses CPU/GPU mode, time limit and offload threshold. Check selected runtime performs an actual GPU calculation when a GPU mode is selected. The default threshold 1024 can leave small calculations on CPU; Use GPU for small matrices sets threshold 1 and can be slower. ML fitting uses CPU. Review saved acceleration counts and fallback warnings.</p><p>For FDTD converge resolution, PML, padding and termination time separately; hitting maximum time requires review. For field maps refine Fourier basis as well as grid/depth sampling. Comparing different numerical settings is not a material effect.</p>''',
'Troubleshooting': '''<ul><li><b>Changes not reflected:</b> Apply layer/region edits, confirm the shared structure, and start a new run. Loading a saved result shows its historical snapshot.</li><li><b>Material coverage:</b> inspect n/k wavelengths, import unit and intended dataset. Restrict the request to covered data or obtain an appropriate dataset.</li><li><b>No phase/fields:</b> enable the relevant measurement before running; power CSV alone cannot reconstruct phase or complex fields.</li><li><b>No tracked peak:</b> inspect overlaid spectra, range and search radius. Endpoints and unresolved baseline features produce missing values.</li><li><b>GPU unavailable:</b> Check selected runtime, review dependency/device messages, then choose CPU to verify the model. GPU mode names do not prove offloading occurred.</li><li><b>Meep unavailable:</b> check Add-ons, published-pack availability, WSL2 and the selected Linux runtime. Source integration does not imply an installed engine.</li><li><b>Search cannot qualify:</b> inspect fabrication limits, sampled resolution, held-out errors and higher-accuracy verification. No passing design is a valid outcome.</li><li><b>Resume incompatible:</b> restore the campaign settings or start a new campaign. Do not merge mismatched materials/illumination/accuracy.</li><li><b>Slow or large results:</b> test a smaller design budget/grid, inspect basis and storage, then restore required accuracy for final work.</li><li><b>Old appearance:</b> restart the updated source launcher; an older packaged EXE keeps its own interface.</li></ul>''',
'Keyboard shortcuts': '''<table cellspacing="8"><tr><td>Ctrl+N</td><td>New project</td></tr><tr><td>Ctrl+O</td><td>Open project</td></tr><tr><td>Ctrl+S</td><td>Save project</td></tr><tr><td>Ctrl+Shift+S</td><td>Save as</td></tr><tr><td>Tab / Shift+Tab</td><td>Move between controls</td></tr><tr><td>Alt+F4</td><td>Close window</td></tr></table><p>Windows title controls minimize, maximize and close. Help search matches topic names and guide text; clear it to restore every topic. Quick actions open the bundled example, the active library/log folder and the real update controls.</p>''',
'About and updates': '''<p>Help → About displays the actual installation/version. Help → Updates displays update status, check time and the existing download/install controls. Check for updates queries the configured release source. Inspect the offered version and release notes; an available update is not automatically installed.</p><p>Download/stage and installation controls follow the application’s update lifecycle. Save work and finish active calculations before restarting into an update. Network or download failure leaves an error rather than a fabricated current-status date. Source and packaged installations can have different update capabilities.</p><p>Open library folder in Quick actions locates the active data library. For scientific conventions and extended examples, use the bundled documents linked below.</p>''',
}

GUIDES['Run, Stop and progress']='''<p>The fixed controls at the bottom of the application keep the same position while workspaces change. Run starts the active calculation: S4 · RCWA, MEEP · FDTD, Δn sweep or Fields in Simulation; the selected Target wavelength / Explore designs search in Simulation Sweep; or the search campaign in AI Search.</p><p>Choose the workspace and review its inputs before pressing Run. A running calculation disables another Run. Saved results, Structure, Materials, Settings and Help are inspection/editing workspaces; select a calculation workspace to enable Run.</p><p>Stop requests cancellation of the active cancellable calculation and waits for its native workers to stop. It is not an immediate process-exit promise or a completed result. Review saved run status and campaign checkpoints before resuming. AI training/fitting/verification retain their dedicated advanced controls. Software updates and add-on installation use the Cancel control inside their own panels.</p>'''
for _title in ('Simulation and sample readout','MEEP FDTD','Δn sweep and carrier density','Electric fields','Simulation Sweep','AI Search'):
    GUIDES[_title]+='<p>Use the fixed Run control at the bottom to start this active workspace. Stop requests cancellation and waits for workers to stop; monitor the progress/status area and inspect saved status before interpreting partial work.</p>'
GUIDES['Getting started']=GUIDES['Getting started'].replace('Run simulation; inspect','Use the fixed bottom Run control; inspect')
GUIDES['Electric fields']+='''<p>Map axes retain the saved physical coordinates in µm. XY uses equal X/Y scale. The full-stack XZ pane can stretch its vertical display to fit deep stacks; judge lengths from its coordinate ticks. The 3D field viewer preserves physical proportions.</p>'''

GUIDES['Materials']+='''<p>Project / Library / All scopes filter the searchable material cards. Choose n &amp; k, n only or k only above the graph. Dots show original table samples; the curve evaluates the selected interpolation between them. The data table and complete CSV retain original samples.</p><p>Linear interpolates n and k linearly. Linear (in log k) keeps n linear and interpolates log(k); every k sample must be strictly positive. This policy affects S4 optical constants and MEEP dispersion fitting and is saved with the project and library preset. Constant models have no wavelength interpolation.</p><p>Display color and Preview opacity affect the material's geometry preview only; explicit layer colors take priority. Notes preserve exact multiline project text and can be saved with a preset. Source attribution stays separate. Changes autosave; an unsuccessful save retains the notes draft for retry. Apply material to layer assigns real data without changing layer dimensions.</p>'''

TOPIC_IMAGES={
 'Getting started':('first-device.png','Native geometry preview: 220 nm Silicon on SiO₂ with 100 nm radius air holes.'),
 'Structure and layers':('structure.png','Layer stack, geometry views and selected-layer inspector.'),
 'Shapes, lattice and units':('structure-regions.png','Native region controls: sizes, center and rotation.'),
 'Geometry views':('structure-cross-section.png','Native cross-section preview; geometry only.'),
 'Materials':('materials.png','Material library, n/k inspection and assignment controls.'),
 'Import CSV and manual materials':('materials-import-csv.png','CSV import unit and dataset controls.'),
 'Simulation and sample readout':('simulation-rcwa.png','RCWA sweep controls and measured result views.'),
 'Spectral phase':('simulation-phase.png','Native phase view; data shown belongs to the captured example.'),
 'MEEP FDTD':('simulation-meep.png','FDTD settings and result views; source is normal incidence.'),
 'Δn sweep and carrier density':('simulation-index-shift.png','Layer selection and index-shift response views.'),
 'Fixed-wavelength Δn readout':('simulation-index-shift.png','Fixed-wavelength readout and overlaid-spectrum controls.'),
 'Electric fields':('simulation-fields.png','Field-map sampling, display and export controls.'),
 'Field comparison and 3D playback':('field-playback.png','Native steady-state field-volume playback controls.'),
 'Recent runs and saved results':('simulation-saved-results.png','Saved result selection, restore and archive controls.'),
 'Simulation Sweep':('simulation-sweep.png','Target/exploration controls and verification results.'),
 'AI Search':('ai-search.png','Campaign setup/training/search and measured field inspection.'),
 'AI checkpoints and reference fields':('ai-search-training.png','Native training and checkpoint controls.'),
 'Appearance and colors':('settings.png','Four appearances and per-look customization.'),
 'Performance and convergence':('settings-performance.png','Native compute resources and accuracy controls.'),
}

DOCUMENTS={
 'Geometry export':'CAD_COMSOL_EXPORT_GUIDE.md',
 'Spectral phase':'SPECTRAL_PHASE_GUIDE.md',
 'MEEP FDTD':'MEEP_FDTD.md',
 'Δn sweep and carrier density':'CARRIER_INDEX_GUIDE.md',
 'Carrier models and depth profiles':'CARRIER_INDEX_GUIDE.md',
 'Fixed-wavelength Δn readout':'INDEX_SHIFT_GUIDE.md',
 'Electric fields':'FIELD_TRACKING_GUIDE.md',
 'Recent runs and saved results':'DATA_LIBRARY_GUIDE.md',
 'Simulation Sweep':'TARGET_DESIGN_GUIDE.md',
 'AI Search':'AI_SEARCH_TRAINING_GUIDE.md',
 'AI checkpoints and reference fields':'AI_SEARCH_TRAINING_GUIDE.md',
 'About and updates':'UPDATES.md',
}
EXTRA_TOPIC_IMAGES={}
RESULT_LINKS={}
if (REAL_EXAMPLE_ROOT/'provenance.json').is_file():
    GUIDES[REAL_EXAMPLE_TOPIC]='''<p>These images come from a completed production S4 · RCWA calculation of the bundled example: a 220 nm Silicon layer on semi-infinite SiO₂, with centered circular Air holes of 100 nm radius and a 540 nm square lattice. Air is the incident medium.</p><p>The spectrum has 41 calculated samples from 1515 to 1555 nm at 1 nm spacing, p polarization and normal incidence. The recorded run requested Fourier basis 81 and used CPU calculation. Silicon n=3.48, SiO₂ n=1.45 and Air n=1; k=0 for all three. These constant indices are explicit demonstration approximations.</p><p>The field maps are calculated at 1550 nm with 25 samples per axis and 3 volume depths in the Silicon layer. Linear |E| is normalized to incident electric-field amplitude. XY is the mid-layer plane at z=0.11 µm; XZ is y=0 through the 0.22 µm film. Plot coordinates are µm; spectrum wavelength is nm. Spectrum graphs use 0–100% of incident power; raw CSV R/T/A remain power fractions.</p><p>The bundled validation records finite R/T/A and complex fields, lossless R+T balance, and requested basis 49/81/121 spectrum comparison. This smooth example spectrum does not establish a resonance. Spectral basis checks do not establish spatial field convergence or experimental material accuracy.</p><p><a href="guide:help_assets/silicon-reference-run/results.csv">Open actual spectrum CSV</a> · <a href="guide:help_assets/silicon-reference-run/electric_fields.csv">Open actual complex field CSV</a> · <a href="guide:help_assets/silicon-reference-run/project.json">Open calculation inputs</a> · <a href="guide:help_assets/silicon-reference-run/scientific-validation.json">Open scientific validation</a> · <a href="guide:help_assets/silicon-reference-run/bundle.json">Open portable provenance and file checksums</a></p><p><a href="guide:help_assets/silicon-reference-run/actual-spectrum-native.png">Open full native spectrum workspace</a> · <a href="guide:help_assets/silicon-reference-run/actual-fields-native.png">Open full native Fields workspace</a></p>'''
    GUIDES[REAL_EXAMPLE_TOPIC]+='''<p><a href="guide:help_assets/silicon-reference-run/field-samples.json">Open the portable index of all 41 wavelength field datasets</a> · <a href="guide:help_assets/silicon-reference-run/basis-49/results.csv">Open basis 49 comparison CSV</a> · <a href="guide:help_assets/silicon-reference-run/basis-121/results.csv">Open basis 121 comparison CSV</a></p><p><a href="guide:help_assets/silicon-reference-run/actual-spectrum-export.png">Open high-resolution spectrum export</a> · <a href="guide:help_assets/silicon-reference-run/actual-electric-field-maps.png">Open high-resolution field-map export</a></p>'''
    TOPIC_IMAGES[REAL_EXAMPLE_TOPIC]=('silicon-reference-run/actual-spectrum-plot.png','Actual production S4 spectrum for the Silicon example. Wavelength in nm; R/T/A plotted as percent of incident power, with raw CSV values retained as fractions.')
    EXTRA_TOPIC_IMAGES[REAL_EXAMPLE_TOPIC]=(('silicon-reference-run/actual-fields-plot.png','Actual S4 fields at 1550 nm: linear |E| / incident |E|. XY z=0.11 µm and XZ y=0; coordinates in µm.'),)
    TOPIC_IMAGES['Simulation and sample readout']=TOPIC_IMAGES[REAL_EXAMPLE_TOPIC]
    TOPIC_IMAGES['Electric fields']=EXTRA_TOPIC_IMAGES[REAL_EXAMPLE_TOPIC][0]
    TOPIC_IMAGES['Structure and layers']=('silicon-reference-run/actual-structure-native.png','Native applied Silicon example used for the actual spectrum and fields.')
    TOPIC_IMAGES['Geometry views']=TOPIC_IMAGES['Structure and layers']
    TOPIC_IMAGES['Shapes, lattice and units']=('silicon-reference-run/actual-unit-cell-native.png','Actual Silicon unit cell: centered 100 nm radius hole, 540 nm square period and applied geometry controls.')
    TOPIC_IMAGES['Field comparison and 3D playback']=('silicon-reference-run/actual-3d-fields-plot.png','Actual saved 1550 nm volume samples. Point colors are |E|²; arrows show real E at optical phase 45°. No pulse propagation or added spatial sampling.')
    TOPIC_IMAGES['Materials']=('silicon-reference-run/actual-materials-native.png','Actual example material inputs: constant Silicon n=3.48, SiO₂ n=1.45 and k=0. These are explicit approximations.')
    DOCUMENTS[REAL_EXAMPLE_TOPIC]='help_assets/silicon-reference-run/provenance.json'
    RESULT_LINKS={name:'help_assets/silicon-reference-run/'+name for name in ('results.csv','electric_fields.csv','project.json','scientific-validation.json','bundle.json','field-samples.json','basis-49/results.csv','basis-121/results.csv','actual-spectrum-native.png','actual-fields-native.png','actual-spectrum-export.png','actual-electric-field-maps.png')}

PRIMARY_TOPICS=('Getting started','Structure and layers','Materials','Simulation and sample readout','Electric fields','Recent runs and saved results','AI Search','Appearance and colors','Troubleshooting')
TOPIC_ORDER=PRIMARY_TOPICS+tuple(title for title in GUIDES if title not in PRIMARY_TOPICS)
EXAMPLE_PROJECT=ASSET_ROOT/'air-hole-example.json'
FIRST_STEPS=(
 ('Add layers','Create a 220 nm Silicon layer between Air and the semi-infinite SiO₂ substrate. Apply the material and thickness.'),
 ('Choose materials and thickness','Assign Silicon and SiO₂ in Materials. Inspect n/k and wavelength coverage; the example’s constant indices are approximations.'),
 ('Add air holes','Select the Silicon layer and choose Air as the fill. Use a 100 nm hole radius and 540 nm square period, then Apply pattern.'),
 ('Review structure','Inspect 3D Stack, Cross-section and Unit cell. Confirm applied layers, thicknesses and holes; resolve any input errors reported when you Run.'),
 ('Simulate','Choose S4 · RCWA in Simulation, set the sweep and illumination, then use the fixed bottom Run control. Refine basis and sampling to check convergence.'),
)


def help_icon(name,color):
    """Crisp vector icons without platform-dependent font glyphs."""
    if name not in ('book','folder','log','refresh','search','export','flask'):return navigation_icon(name,color)
    from PyQt6.QtGui import QPolygonF
    pixmap=QPixmap(72,72);pixmap.setDevicePixelRatio(3);pixmap.fill(Qt.GlobalColor.transparent)
    p=QPainter(pixmap);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(color),1.7,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    if name=='book':
        path=QPainterPath(QPointF(12,5));path.cubicTo(8,2,4,3,2,4);path.lineTo(2,20)
        path.cubicTo(5,18,9,19,12,21);path.cubicTo(15,19,19,18,22,20)
        path.lineTo(22,4);path.cubicTo(19,3,15,2,12,5);path.lineTo(12,21);p.drawPath(path)
    elif name=='folder':
        path=QPainterPath(QPointF(2,7));path.lineTo(2,20);path.lineTo(20,20);path.lineTo(23,10)
        path.lineTo(5,10);path.lineTo(2,20);p.drawPath(path)
        p.drawPolyline(QPolygonF([QPointF(2,7),QPointF(8,7),QPointF(10,9),QPointF(21,9)]))
    elif name=='log':
        path=QPainterPath(QPointF(5,2));path.lineTo(15,2);path.lineTo(20,7);path.lineTo(20,22);path.lineTo(5,22);path.closeSubpath();p.drawPath(path)
        p.drawPolyline(QPolygonF([QPointF(15,2),QPointF(15,7),QPointF(20,7)]))
        for y in (11,15,19):p.drawLine(QPointF(8,y),QPointF(16,y))
    elif name=='refresh':
        p.drawArc(QRectF(3,3,18,18),45*16,300*16);p.drawPolyline(QPolygonF([QPointF(21,3),QPointF(21,9),QPointF(15,9)]))
    elif name=='search':p.drawEllipse(QRectF(2,2,15,15));p.drawLine(QPointF(15,15),QPointF(22,22))
    elif name=='export':
        p.drawLine(QPointF(12,2),QPointF(12,16));p.drawPolyline(QPolygonF([QPointF(7,7),QPointF(12,2),QPointF(17,7)]))
        p.drawPolyline(QPolygonF([QPointF(3,13),QPointF(3,21),QPointF(21,21),QPointF(21,13)]))
    else:
        path=QPainterPath(QPointF(9,3));path.lineTo(9,10);path.lineTo(3,20);path.lineTo(21,20);path.lineTo(15,10);path.lineTo(15,3);p.drawPath(path)
        p.drawLine(QPointF(7,3),QPointF(17,3));p.drawLine(QPointF(7,15),QPointF(17,15))
    p.end();return QIcon(pixmap)


def topic_icon_name(title):
    if title=='Getting started':return 'book'
    if title in ('Troubleshooting','Geometry export'):return 'export'
    if 'material' in title.casefold():return 'flask'
    if title.startswith('AI'):return 'search'
    if 'field' in title.casefold():return 'Fields'
    if title=='Recent runs and saved results':return 'Optimize'
    if title=='Appearance and colors':return 'Settings'
    if title in ('Performance and convergence','About and updates'):return 'performance'
    if title in ('Keyboard shortcuts','Common units'):return 'log'
    if any(word in title for word in ('Simulation','MEEP','phase','Δn','Carrier')):return 'Simulate'
    return 'Structure'


def help_label(text,name='',wrap=False):
    widget=QLabel(text);widget.setWordWrap(wrap)
    if name:widget.setObjectName(name)
    return widget


class HelpIllustration(QWidget):
    """Fit a capture of the actual geometry renderer without stretching it."""
    def __init__(self,parent=None):
        super().__init__(parent);self.pixmap=QPixmap()
        self.setMinimumSize(190,240);self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.setAccessibleName('220 nm Silicon on semi-infinite SiO2, with 100 nm radius air holes and Air above. Exploded geometry, not to scale.')
        self.retheme()
    def retheme(self):
        filename='first-device-light.png' if theme_manager().mode=='light' else 'first-device.png'
        self.pixmap=QPixmap(str(ASSET_ROOT/filename));self.update()
    def paintEvent(self,event):
        if self.pixmap.isNull():return
        target=self.pixmap.size();target.scale(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap((self.width()-target.width())//2,(self.height()-target.height())//2,target.width(),target.height(),self.pixmap);p.end()


class HelpReader(QTextBrowser):
    """Keep native screenshot examples within the available reader width."""
    def resizeEvent(self,event):
        super().resizeEvent(event)
        width=max(100,min(640,self.viewport().width()-2*self.document().documentMargin()-10))
        block=self.document().begin()
        while block.isValid():
            iterator=block.begin()
            while not iterator.atEnd():
                fragment=iterator.fragment()
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    image_format=fragment.charFormat().toImageFormat()
                    if abs(image_format.width()-width)>1:
                        image_format.setWidth(width)
                        native=QImage(QUrl(image_format.name()).toLocalFile())
                        if not native.isNull():image_format.setHeight(width*native.height()/native.width())
                        cursor=QTextCursor(self.document());cursor.setPosition(fragment.position())
                        cursor.setPosition(fragment.position()+fragment.length(),QTextCursor.MoveMode.KeepAnchor)
                        cursor.mergeCharFormat(image_format)
                iterator+=1
            block=block.next()


class HelpGuide(QWidget):
    def __init__(self,parent=None,about_page=None):
        super().__init__(parent);self.setObjectName('helpGuide')
        self.about_page=about_page;self.store=getattr(about_page,'store',None)
        root=QHBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(10)
        self.left_panel=WorkspacePanel();layout=QVBoxLayout(self.left_panel);layout.setContentsMargins(12,14,12,12);layout.setSpacing(12)
        layout.addWidget(help_label('Help','helpRailTitle'))
        self.query=QLineEdit();self.query.setObjectName('helpSearch');self.query.setPlaceholderText('Search help topics…')
        self.query.setClearButtonEnabled(True);self.query.setMinimumHeight(36);self.query.setAccessibleName('Search help topics and guide text');layout.addWidget(self.query)
        self.topics=QListWidget();self.topics.setObjectName('helpTopicList');self.topics.setIconSize(QSize(25,25));self.topics.setSpacing(2)
        self.topics.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.topics.setAccessibleName('Help topics');layout.addWidget(self.topics,1);root.addWidget(self.left_panel,23)
        self.center_panel=WorkspacePanel();center=QVBoxLayout(self.center_panel);center.setContentsMargins(12,10,12,10);center.setSpacing(0)
        self.center_tabs=QTabWidget();self.center_tabs.setObjectName('helpCenterTabs');self.center_tabs.setDocumentMode(True);self.center_tabs.setUsesScrollButtons(True)
        self.center_tabs.tabBar().setDrawBase(False)
        self.reader=HelpReader();self.reader.setObjectName('helpReader');self.reader.setOpenExternalLinks(False)
        self.reader.setSearchPaths([str(ASSET_ROOT)]);self.reader.anchorClicked.connect(self.open_document);self.reader.document().setDocumentMargin(14)
        self.guide_stack=QStackedWidget();self.guide_stack.setObjectName('helpGuideStack');self.first_page=self._build_first_page()
        self.guide_stack.addWidget(self.first_page);self.guide_stack.addWidget(self.reader);self.center_tabs.addTab(self.guide_stack,'User guide')
        self.shortcuts_reader=QTextBrowser();self.shortcuts_reader.setObjectName('helpReader');self.shortcuts_reader.setHtml('<h2>Keyboard shortcuts</h2>'+GUIDES['Keyboard shortcuts'])
        self.shortcuts_reader.document().setDocumentMargin(18);self.center_tabs.addTab(self.shortcuts_reader,'Shortcuts');center.addWidget(self.center_tabs,1);root.addWidget(self.center_panel,50)
        self.quick_panel=QWidget();quick=QVBoxLayout(self.quick_panel);quick.setContentsMargins(0,0,0,0);quick.setSpacing(10)
        actions_panel=WorkspacePanel();actions=QVBoxLayout(actions_panel);actions.setContentsMargins(14,14,14,14);actions.setSpacing(9)
        actions.addWidget(help_label('Quick actions','helpPanelTitle'));self.action_buttons={}
        for key,title,detail,icon,callback in (
            ('example','Open example project','Load Silicon on SiO₂ with air holes','folder',self.open_example),
            ('library','Open library folder','Browse local projects and saved results','folder',self.open_library),
            ('logs','View logs','Open folder with desktop-crash.log','log',self.open_logs),
            ('updates','Check for updates','Manual check for compatible releases','refresh',self.check_updates)):
            action=QPushButton();action.setObjectName('helpQuickAction');action.setMinimumHeight(76);action.setAccessibleName(title);action.setToolTip(detail)
            contents=QHBoxLayout(action);contents.setContentsMargins(12,10,10,10);contents.setSpacing(12)
            icon_label=help_label('','helpActionIcon');icon_label.setFixedSize(28,28);icon_label.setProperty('helpIcon',icon)
            icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);contents.addWidget(icon_label)
            words=QVBoxLayout();words.setSpacing(4)
            for text,name in ((title,'helpActionTitle'),(detail,'helpSecondary')):
                label=help_label(text,name,True);label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);words.addWidget(label)
            contents.addLayout(words,1);action.clicked.connect(callback)
            action.setEnabled(about_page is not None if key=='updates' else self.store is not None);self.action_buttons[key]=action;actions.addWidget(action)
        self.example_button=self.action_buttons['example'];self.library_button=self.action_buttons['library'];self.logs_button=self.action_buttons['logs'];self.update_button=self.action_buttons['updates']
        self.action_status=help_label('','helpSecondary',True);self.action_status.hide();actions.addWidget(self.action_status);quick.addWidget(actions_panel)
        shortcut_panel=WorkspacePanel();shortcuts=QVBoxLayout(shortcut_panel);shortcuts.setContentsMargins(14,14,14,14);shortcuts.setSpacing(8)
        shortcuts.addWidget(help_label('Keyboard shortcuts','helpPanelTitle'))
        for title,keys in (('Open project',('Ctrl','O')),('Save project',('Ctrl','S')),('Save project as',('Ctrl','Shift','S'))):
            row=QFrame();row.setObjectName('helpShortcutRow');line=QHBoxLayout(row);line.setContentsMargins(9,8,9,8);line.setSpacing(5);line.addWidget(help_label(title,wrap=True),1)
            for index,key in enumerate(keys):
                if index:line.addWidget(QLabel('+'))
                cap=help_label(key,'helpKeyCap');cap.setAlignment(Qt.AlignmentFlag.AlignCenter);line.addWidget(cap)
            shortcuts.addWidget(row)
        quick.addWidget(shortcut_panel)
        more=WorkspacePanel();more_layout=QVBoxLayout(more);more_layout.setContentsMargins(14,14,14,14);more_layout.setSpacing(12)
        more_layout.addWidget(help_label('Need more help?','helpPanelTitle'));more_layout.addWidget(help_label('Browse the searchable guide, inspect native workspace examples, or review troubleshooting.',wrap=True))
        button=QPushButton('Export and troubleshooting');button.clicked.connect(lambda:self.open_topic('Troubleshooting'));more_layout.addWidget(button)
        quick.addWidget(more);quick.addStretch(1);root.addWidget(self.quick_panel,25)
        self.query.textChanged.connect(self.filter);self.topics.currentTextChanged.connect(self.display);theme_manager().changed.connect(self.retheme)
        self.filter('');self.retheme()

    def _build_first_page(self):
        scroll=QScrollArea();scroll.setObjectName('helpScroll');scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content=QWidget();content.setObjectName('helpTutorial');page=QVBoxLayout(content);page.setContentsMargins(8,18,8,10);page.setSpacing(14)
        page.addWidget(help_label('Build your first structure','helpTutorialTitle',True));page.addWidget(help_label('Build Silicon on SiO₂ with circular air holes of 100 nm radius, assign materials, and run a simulation. The example uses constant-index approximations.',wrap=True))
        self.tutorial_main=QWidget();body=QHBoxLayout(self.tutorial_main);body.setContentsMargins(0,0,0,0);body.setSpacing(14)
        steps=QWidget();step_layout=QVBoxLayout(steps);step_layout.setContentsMargins(0,0,0,0);step_layout.setSpacing(12);self.step_badges=[]
        for number,(title,description) in enumerate(FIRST_STEPS,1):
            row=QHBoxLayout();row.setSpacing(11);badge=help_label(str(number),'helpStepBadge');badge.setFixedSize(34,34);badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.step_badges.append(badge);row.addWidget(badge,0,Qt.AlignmentFlag.AlignTop)
            words=QVBoxLayout();words.setContentsMargins(0,2,0,0);words.setSpacing(5);words.addWidget(help_label(title,'helpStepTitle',True));words.addWidget(help_label(description,'helpStepDescription',True));row.addLayout(words,1);step_layout.addLayout(row)
        body.addWidget(steps,6)
        self.example_panel=WorkspacePanel();figure=QVBoxLayout(self.example_panel);figure.setContentsMargins(10,12,10,10);figure.setSpacing(6);figure.addWidget(help_label('Example structure','helpStepTitle'))
        self.example_illustration=HelpIllustration();figure.addWidget(self.example_illustration,1);figure.addWidget(help_label('Silicon on SiO₂ · exploded, not to scale\n220 nm Silicon · 100 nm hole radius\n540 nm square lattice period','helpSecondary',True))
        body.addWidget(self.example_panel,4);page.addWidget(self.tutorial_main)
        units=WorkspacePanel();unit_layout=QVBoxLayout(units);unit_layout.setContentsMargins(12,12,12,12);unit_layout.setSpacing(8)
        title_row=QHBoxLayout();title_row.addWidget(help_label('Common units','helpStepTitle'));title_row.addWidget(help_label('Length conversion factors','helpSecondary'),1);unit_layout.addLayout(title_row)
        lower=QHBoxLayout();self.units_lower=lower;lower.setSpacing(12);table=QFrame();table.setObjectName('helpUnitTable');grid=QGridLayout(table);grid.setContentsMargins(0,0,0,0);grid.setSpacing(0)
        for row,values in enumerate((('From','To','Multiply by'),('1 µm','nm','1,000'),('1 nm','µm','0.001'),('1 mm','µm','1,000'),('1 µm','mm','0.001'))):
            for col,value in enumerate(values):
                cell=help_label(value,'helpUnitHeader' if row==0 else 'helpUnitCell');cell.setAlignment(Qt.AlignmentFlag.AlignCenter);grid.addWidget(cell,row,col)
        lower.addWidget(table,6)
        note=QFrame();note.setObjectName('helpUnitsNote');words=QVBoxLayout(note);words.setContentsMargins(10,8,10,8);words.setSpacing(5);words.addWidget(help_label('Note','helpStepTitle'))
        words.addWidget(help_label('Use the unit shown beside each field. Form units may be nm, µm or mm; advanced tables use µm and wavelengths use nm.','helpSecondary',True));lower.addWidget(note,4);unit_layout.addLayout(lower);page.addWidget(units)
        self.actual_example_button=None
        if REAL_EXAMPLE_TOPIC in GUIDES:
            actual=WorkspacePanel();actual_layout=QHBoxLayout(actual);actual_layout.setContentsMargins(12,10,12,10);actual_layout.setSpacing(10)
            text=QVBoxLayout();text.setSpacing(4);text.addWidget(help_label('Actual S4 example','helpStepTitle'))
            text.addWidget(help_label('Calculated spectrum and fields · includes data and inputs','helpSecondary',True));actual_layout.addLayout(text,1)
            self.actual_example_button=QPushButton('View actual results');self.actual_example_button.clicked.connect(lambda:self.open_topic(REAL_EXAMPLE_TOPIC));actual_layout.addWidget(self.actual_example_button)
            page.addWidget(actual)
        page.addStretch(1);scroll.setWidget(content);return scroll

    def resizeEvent(self,event):
        super().resizeEvent(event)
        compact=self.width()<1250
        direction=QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
        self.tutorial_main.layout().setDirection(direction);self.units_lower.setDirection(direction)
        self.example_panel.setMaximumHeight(360 if compact else 16777215)

    def retheme(self,*args):
        manager=theme_manager();c=COLORS[manager.mode];fill=QColor(c['field']);alpha=65 if manager.style=='glass' else 255
        input_fill=f'rgba({fill.red()},{fill.green()},{fill.blue()},{alpha})'
        self.setStyleSheet(f'''
            QWidget#helpGuide, QWidget#helpTutorial, QWidget#helpGuideStack,
            QScrollArea#helpScroll, QScrollArea#helpScroll > QWidget > QWidget {{ background:transparent; }}
            QFrame#builderPanel {{ background:transparent; border:0; }}
            QListWidget#helpTopicList, QTextBrowser#helpReader {{ background:transparent; border:0; color:{c['text']}; }}
            QListWidget#helpTopicList::item {{ padding:9px 8px; border-bottom:1px solid {c['border']}; border-radius:0; }}
            QListWidget#helpTopicList::item:selected {{ background:{c['select']}; border:1px solid {c['accent']}; border-radius:7px; }}
            QLineEdit#helpSearch {{ background:{input_fill}; border:1px solid {c['border']}; border-radius:6px; padding:7px 10px; }}
            QTabWidget#helpCenterTabs::pane {{ background:transparent; border:0; }}
            QLabel#helpRailTitle, QLabel#helpPanelTitle {{ font-size:12pt; font-weight:600; }}
            QLabel#helpTutorialTitle {{ font-size:18pt; font-weight:650; }}
            QLabel#helpStepTitle, QLabel#helpActionTitle {{ font-weight:600; }}
            QLabel#helpSecondary {{ color:{c['muted']}; font-size:9pt; }}
            QLabel#helpStepDescription {{ color:{c['muted']}; }}
            QLabel#helpStepBadge {{ background:{c['select']}; border:1px solid {c['accent']}; border-radius:17px; color:{c['text']}; font-size:13pt; }}
            QPushButton#helpQuickAction {{ background:{input_fill}; border:1px solid {c['border']}; border-radius:8px; text-align:left; padding:0; min-height:74px; }}
            QPushButton#helpQuickAction:hover {{ background:{c['hover']}; border-color:{c['accent']}; }}
            QPushButton#helpQuickAction QLabel {{ background:transparent; border:0; }}
            QFrame#helpShortcutRow, QFrame#helpUnitsNote {{ background:{input_fill}; border:1px solid {c['border']}; border-radius:7px; }}
            QLabel#helpKeyCap {{ background:{input_fill}; border:1px solid {c['border']}; border-radius:5px; padding:4px 5px; font-size:9pt; }}
            QFrame#helpUnitTable {{ border:1px solid {c['border']}; border-radius:5px; }}
            QLabel#helpUnitHeader {{ background:{c['header']}; border:1px solid {c['border']}; padding:4px 6px; font-weight:600; }}
            QLabel#helpUnitCell {{ background:{input_fill}; border:1px solid {c['border']}; padding:3px 6px; }}
        ''')
        for reader in (self.reader,self.shortcuts_reader):reader.document().setDefaultStyleSheet('h2 {font-size:18pt; margin-top:4px; margin-bottom:14px;} p,li {line-height:135%;} p {margin-bottom:14px;} th {text-align:left;} a {color:'+c['accent']+';}')
        for row in range(self.topics.count()):
            item=self.topics.item(row);item.setIcon(help_icon(topic_icon_name(item.text()),c['text']))
        for icon_label in self.findChildren(QLabel,'helpActionIcon'):icon_label.setPixmap(help_icon(icon_label.property('helpIcon'),c['text']).pixmap(28,28))
        self.example_illustration.retheme()
        self.shortcuts_reader.setHtml('<h2>Keyboard shortcuts</h2>'+GUIDES['Keyboard shortcuts'])
        current=self.topics.currentItem()
        if current:
            position=self.reader.verticalScrollBar().value()
            self.display(current.text());self.reader.verticalScrollBar().setValue(position)

    def open_topic(self,title):
        self.center_tabs.setCurrentIndex(0);self.query.clear();matches=self.topics.findItems(title,Qt.MatchFlag.MatchExactly)
        if matches:self.topics.setCurrentItem(matches[0]);self.display(title)

    def filter(self,text):
        previous=self.topics.currentItem().text() if self.topics.currentItem() else '';self.topics.clear();c=COLORS[theme_manager().mode]
        for title in TOPIC_ORDER:
            if text.casefold() not in (title+' '+GUIDES[title]).casefold():continue
            item=QListWidgetItem(help_icon(topic_icon_name(title),c['text']),title);item.setToolTip(title);item.setSizeHint(QSize(0,50));self.topics.addItem(item)
        matches=self.topics.findItems(previous,Qt.MatchFlag.MatchExactly)
        if matches:self.topics.setCurrentItem(matches[0])
        elif self.topics.count():self.topics.setCurrentRow(0)
        else:self.guide_stack.setCurrentWidget(self.reader);self.reader.setPlainText('No matching guide. Try a control name such as layer, phase, export or color.')

    def display(self,title):
        if title not in GUIDES:return
        body='<h2>'+escape(title)+'</h2>'
        if title==REAL_EXAMPLE_TOPIC:
            body+='<p>Actual production S4 results for 220 nm Silicon on SiO₂ with 100 nm radius Air holes. Constant Silicon n=3.48, SiO₂ n=1.45 and k=0 are explicit approximations; illumination is normally incident p polarization.</p>'
        else:body+=GUIDES[title]
        images=([TOPIC_IMAGES[title]] if title in TOPIC_IMAGES else [])+list(EXTRA_TOPIC_IMAGES.get(title,()))
        for filename,caption in images:
            path=ASSET_ROOT/filename
            if path.is_file():
                width=max(100,min(640,self.reader.viewport().width()-38))
                native=QImage(str(path));height=round(width*native.height()/native.width())
                note=' Saved calculation or inputs shown; the current project may differ.' if filename.startswith('silicon-reference-run/') else ' Screenshot values are examples, not current project results.'
                body+='<p style="line-height:100%; margin-top:6px; margin-bottom:10px;"><img src="'+escape(QUrl.fromLocalFile(str(path)).toString(),quote=True)+'" width="'+str(int(width))+'" height="'+str(height)+'"></p><p><i>'+escape(caption)+note+'</i></p>'
                body+='<p><a href="help-image:'+escape(filename)+'">Open full-size native image</a></p>'
        if title==REAL_EXAMPLE_TOPIC:body+=GUIDES[title]
        if title in DOCUMENTS:
            filename=DOCUMENTS[title];body+='<p><a href="guide:'+escape(filename)+'">Open detailed documentation: '+escape(filename)+'</a></p>'
        self.reader.setHtml(body);self.guide_stack.setCurrentWidget(self.first_page if title=='Getting started' else self.reader)

    def open_document(self,url):
        # Guide/data/image links use explicit bundled whitelists. Reject
        # arbitrary file navigation and paths supplied by external content.
        filename=url.path()
        if url.scheme()=='guide':
            if filename not in tuple(DOCUMENTS.values())+tuple(RESULT_LINKS.values()):return
            path=Path(__file__).resolve().parent/filename
        elif url.scheme()=='help-image':
            allowed={item[0] for item in TOPIC_IMAGES.values()}
            allowed.update(item[0] for items in EXTRA_TOPIC_IMAGES.values() for item in items)
            if filename not in allowed:return
            path=ASSET_ROOT/filename
        else:return
        if path.is_file():QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _action_message(self,text):self.action_status.setText(text);self.action_status.show()

    def open_example(self):
        if self.store is None:return False
        window=self.window()
        if self.store.busy:self._action_message('Wait for the current calculation before opening the example.');return False
        # The main window's Save / Discard / Cancel guard protects the working session.
        if not hasattr(window,'_confirm_project_replace'):self._action_message('Open this example from the full application window.');return False
        if not window._confirm_project_replace():return False
        try:
            self.store.load_project(json.loads(EXAMPLE_PROJECT.read_text(encoding='utf-8')));window._navigate_route(0)
            window.status.setText('Opened Silicon on SiO₂ · 100 nm radius air holes · Constant n/k approximations; no computed results. Save as to keep a project copy.');self.action_status.hide();return True
        except (OSError,ValueError,TypeError,KeyError) as exc:self._action_message('Could not open the bundled example: '+str(exc));return False

    def open_library(self):
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.library.root))) if self.store is not None else False

    def open_logs(self):
        if self.store is None:return False
        # The crash reporter writes at the library root; solver logs belong to runs.
        self._action_message('Desktop diagnostics: desktop-crash.log. Solver logs are inside each saved run folder.')
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.library.root)))

    def check_updates(self):
        if self.about_page is None:return
        if hasattr(self,'updates_page'):self.center_tabs.setCurrentWidget(self.updates_page)
        self.about_page.check_for_updates()


def add_help_tabs(page):
    """Split existing identity/update widgets while retaining their lifecycle."""
    # The workspace composition hides prose called "muted" elsewhere. Help
    # owns explanation, including real update status/check timestamps.
    for explanation in page.findChildren(QLabel,'muted'):explanation.setObjectName('helpSecondary')
    original=page.layout();about=QWidget();about.setLayout(original);original.setContentsMargins(16,18,16,18)
    updates=QWidget();layout=QVBoxLayout(updates);layout.setContentsMargins(14,18,14,18);layout.setSpacing(12)
    if hasattr(page,'update_card'):original.removeWidget(page.update_card);layout.addWidget(page.update_card)
    else:layout.addWidget(QLabel('Updates use the configured release source.'))
    layout.addStretch(1);root=QVBoxLayout(page);root.setContentsMargins(0,0,0,0)
    guide=HelpGuide(about_page=page);guide.updates_page=updates;guide.center_tabs.addTab(about,'About');guide.center_tabs.addTab(updates,'Updates')
    root.addWidget(guide);page.help_guide=guide;page.help_tabs=guide.center_tabs
