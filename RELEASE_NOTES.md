# Optical Design Studio 1.4.0-alpha.13 — Semiconductor generation and mesh controls

Experimental Windows x64 usability update · 1 November 2026

Semiconductor transport regions now expose optional prescribed exponential generation and explicit mesh construction. Generation uses an authored amplitude, nonnegative absorption and global x origin; Uniform retains its omitted optional schema and scalar source path. The mesh builder previews authored bounds/counts and optionally includes region/defect coordinates only on explicit Apply. Inserting coordinates changes the base uniform discretization. Backend alignment validation and solver equations are unchanged; neither feature is a fit or a claim to resolve a paper discrepancy.

The candidate passed 202 distinct source checks and 34 package/privacy/license checks. Both executables match 201 compiled application modules; the standalone Meep and research workers match staged source. Eight actual critical checks, seven Windows startup checks and all seven generation-profile and all seven mesh-builder observations, including the same inspected feature-process exit0, are required. A separately recorded actually UI-launched Uniform diagnostic is permitted for normalized-input omission evidence; its actual scope/status is retained. No completion, convergence, operational Stop or paper agreement is inferred from UI acceptance.

Extract the complete portable `.7z`, retaining the backend and `_internal` directory. Stable v1.3.5 remains the stable channel. The authored aggregate below records 25/28 routes and five earlier scoped agreements at their actual application versions. Raw projects, user libraries, logs and paper files are excluded.

---

# Optical Design Studio — dated 25-route scientific aggregate

**Snapshot: 2026-11-01T16:41:15.864985+00:00.** The campaign has native execution evidence for 25/28 routes; beam, aperture and RCWA poles remain without completed execution at this checkpoint. Five earlier scoped reference agreements are retained, and no new agreement is credited. Execution, convergence, assumptions and external agreement are separate judgments. Structures and settings were authored in the native UI without importing structures, projects, presets, materials or curves.

The latest verified download at this snapshot is [alpha.11](https://github.com/Wgeshow/Optical-Design-Studio/releases/tag/v1.4.0-alpha.11), corresponding source `130793e2b7a8e0b42424a485c3c01f8c7c568b83`. Its public notes remain frozen at 21/28. Seven uploaded SHA-256 digests/sizes and seven anonymous download HEAD responses were verified; full anonymous redownload hashes were not checked. Its private four-file source/report update was merged and all remote bytes were verified. Stable v1.3.5 and public main remain unchanged.

Subsequent software acceptance, 1 November: the combined alpha.13 candidate adds prescribed exponential generation and explicit mesh authoring in the semiconductor inspector. Uniform source inputs retain their prior normalized schema and numerical path; the mesh builder applies only explicitly requested coordinates. The candidate passed 202 distinct source tests, 34 package checks, exact comparison of 201 compiled modules per executable and both standalone workers, eight actual frozen critical checks and seven Windows startup checks. Fresh Terra testing passed all seven generation-profile and all seven mesh-builder observation scopes, with normal exit code 0 from the same inspected feature process. The original visible settings export retained both authored Uniform regions and their scalar amplitudes while omitting the optional generation_profile object. Actual navigation restored the separately authored 2D study; read-only saved-state comparison verified its 102 by 101 nodes, regions and defect were unchanged. In the 1D generator the y option was listed, but selecting it kept x; it was functionally unavailable and was not visibly greyed. No scientific solve or operational Stop test was performed in these feature checks. Alpha.12 remains an unpublished partial checkpoint; none of its observations substituted for fresh alpha.13 acceptance.

## Earlier route evidence, with original executable provenance

The following retained observations describe the completed first 21 routes at their actual executable versions. Their original failures and numerical limitations remain valid; later Meep and PCSEL refinements follow in separate sections. Release packaging tests do not relabel earlier scientific runs.



### Run provenance for the curated route records

The results above preserve the application version and source that actually launched each run. The curated records use these exact identities:

| Result record | Application version | Source commit |
|---|---|---|
| Driven fields basis and sampling runs | 1.4.0-alpha.4 | `37a8dea74b9a897ee011d98ff7d03f301304bb23` |
| Corrected index-shift run and three-radius sweep | 1.4.0-alpha.6 | `ed55aa115aec192bb939a0491400d8c09253e364` |
| Meep cap800, completed 20/a cap4000, completed 22/a, and dated 24/a active snapshot | 1.4.0-alpha.5 (session revision `alpha5-r2`) | `edd15d30e3170980d0cee9502d78141ac6cbd55e` |
| AI search, representative-cell transport, finite-contact transport, and coupled dielectric control | 1.4.0-alpha.8 | `ea6bb3dd0be90e1e9a1fac9f8f43df3a79dde4a5` |

These are run provenance labels; a later release does not retroactively alter the source used for a prior native run. This aggregate retains those identities and the earlier immutable release checkpoints.

## Route coverage

The original eight executed routes remain the dated baseline: S4 optical spectra, Meep cavity-array optics, 3D and 2D photonic bands, Legume bands, electrical DC, electrical C–V, and thermal conduction. Their previous scoped comparisons remain intact; their results are not recounted as new November 1 validation. Twelve later route executions are summarized below. Their run-specific application provenance is retained separately; later source releases do not retroactively change those runs.



| Live route | Evidence and scope | Remaining scientific limit |
|---|---|---|
| High-field optical response | Five alpha.4 native spectra at 41/81 wavelengths, 300 K, gap 1.519 eV, mass ratios 0.1106/0.1106, and zero/6.6 MV/m; selected exports audited against saved arrays. | Primary Figure 4(a,b) shape comparison is normalized and preliminary; no horizontal or parameter fit. Energy-grid/cutoff sensitivity and absolute prefactor remain unresolved. |
| Lumped laser | One alpha.4 in-process 41-point A-only steady-state sweep; independently checked scalar threshold relations and exported values. | The source model has no coupled transient integration. The paper’s transient/modulation dataset is not a comparable steady-state target. No transient, experimental, or paper-curve agreement. |
| Electrical I–V | Homogeneous fixed-conductivity bar at 8³ and 16³ meshes with five biases; signed current and terminal balance agree with the Ohmic equation. | This is a static conductor diagnostic, not a semiconductor diode or Noor et al. drift-diffusion validation. |
| Guided-mode expansion | Three reciprocal cutoffs and one guided-basis expansion; a plausible near-degenerate pair changes with cutoff/basis. At gmax 5.1, candidate mean Q is 277.8 versus the paper’s approximate 213, a +30.4% relative discrepancy using 213 as denominator. | Near-degeneracy prevents proof of mode identity; cutoff dependence remains. This is not a paper agreement. |
| Periodic transport | Two meshes on an analyst-selected uniform slab; expected low-field current is `q μₙ n A ΔV/L = 1.9226119608×10⁻⁸ A` at 10 mV. Mesh-pair differences are near roundoff. | Two meshes do not establish an error order; the analytic diagnostic is not a matched paper comparison. |
| Driven optical fields | Three alpha.4 runs at basis 121/225 on grid/depth 25/9 and basis 225 on 49/17; native exports match saved field arrays. At identical coordinates, relative-L2 basis changes are 4.8239% for E and 0.8134% for H. | The 25/9 and 49/17 midpoint samples are nonnested; no field convergence order. Fan Figure 5 is a dark eigenmode, unlike this off-resonant driven field. |
| Index-shift spectrum | Corrected alpha.6 air/air case: basis 225, 41 wavelengths from 2596–2636 nm; a +0.01 slab-index step moves the sampled minimum 7 nm, or 700 nm/RIU as a one-step finite difference. | One-nanometre sampling and basis sensitivity remain. This is not a measured derivative, resonance-pole identity, or changed-index paper target. |
| Radius sweep | Three alpha.6 designs at radii 0.19/0.20/0.21 µm, each with 41 saved spectra. The filtered UI export contains three summary rows, not 123 spectral rows. The middle-radius spectrum matches the index-shift baseline at all 41 samples. | Endpoint extrema for 0.19 and 0.21 µm are not resolved resonance centers or measured shifts. One basis and one spectral step; no convergence or paper credit. |
| AI optical search | Alpha.8 native collection produced two training designs and one held-out design at basis 49; a resumed campaign added two basis-74 verification calculations. | All five campaign records are infeasible/unverified with zero field coverage; two training points and one held-out point do not establish GP calibration or generalization. No paper agreement. |
| Representative-cell transport | Alpha.8 native two-bias run on one 4×4×8 finite homogeneous analyst-defined material slab; exact export and low-field Ohmic equation check. | One mesh, not calibrated GaAs, not a periodic cell, and not a paper reproduction. |
| Finite-contact transport | Alpha.8 homogeneous analyst-defined semiconductor, 4×4×8/16/32 meshes at ρc=10⁻⁵ Ω·cm² plus same-mesh zero-ρ control; all four two-row exports match saved outputs. | At 10 mV, current changes only slightly with axial depth mesh; contact and solved-state resistance checks are diagnostics, not independent physical validation. No calibrated contacts or paper agreement. |
| Coupled dielectric null case | Alpha.8 native 0/1 V electrostatic solve plus five-point normal-incidence air/slab/air spectra; external capacitor and Airy equations checked and 10-row export audited. | Analyst-defined εr=5 dielectric, no EO/interband physics, one 4×4×8 mesh and basis 9. This is a bias-invariance null check, not active electrical-optical coupling, convergence, or paper agreement. |

### High-field response: normalized shape and Kramers–Kronig scope

The native high-field model was the two-band Franz–Keldysh limit with analyst-entered electron and hole masses `m_e=m_h=0.1106m₀`, hence reduced mass `mᵣ=m_em_h/(m_e+m_h)=0.0553m₀`, `E_g=1.519 eV`, `T=300 K`, quasi-Fermi parameters `η_e=η_h=−50`, and fields 0 or 6.6 MV/m. The primary [Duque-Gómez and Sipe paper](https://arxiv.org/abs/1403.1619) reports effects beyond this no-Coulomb two-band limit; the comparison uses only its dashed Figure 4(a,b) curves. The 41- and 81-point datasets span `E=1.50…1.90 eV` with spacings 0.01 and 0.005 eV. Their common nodes agree exactly for computed absorption, confirming repeated evaluation at shared energies, not feature resolution. Native exports matched saved absorption, refractive-index change, extinction change and quadrature diagnostics.

The calculated absorption includes the local transition-availability factor `1−f_e−f_h`; the saved reference absorption used for `Δα`, `Δn` and `Δκ` is explicitly zero-field and unoccupied. At `η_e=η_h=−50`, both carrier occupations are effectively zero and transition availability is effectively unity in the selected range. The endpoint normalization divides model absorption by `α(1.90 eV)=0.323395871 cm⁻¹` and the paper’s dashed curve by its raster-read ordinate `1.189635703×10⁴ cm⁻¹` at the same energy. Both normalized endpoints are one. No horizontal or multi-parameter fit is applied. This is a normalized shape check using coarse raster digitization, not absolute absorption agreement; the figure-reading uncertainty is analyst-assigned, not an author tolerance.

For the KK index change, begin with the nonmagnetic dispersion relation

`n(ω)−1=(2/π) P∫₀∞ Ω κ(Ω)/(Ω²−ω²) dΩ`, with `α=2Ωκ/c`.

Let photon energy in electron-volts be `E=ħω/e` and `E′=ħΩ/e` (joules divided by joules per eV), so `dΩ=(e/ħ)dE′`. Then

`Δn(E)=(100 c ħ/(π e)) P∫₀∞ Δα(E′)/(E′²−E²) dE′`,

when `Δα` is entered in cm⁻¹ and the energy variables in eV; the factor 100 converts inverse centimetres to inverse metres. The principal-value singularity is handled numerically. The 81-point KK refinements vary energy-grid order/cutoff; increasing 8192 points from 12 to 24 eV also doubles the interval and coarsens the linear spacing, so that pair does not isolate the omitted tail. Fixed-cutoff refinements are separate. All sampled KK warning counts were zero, but warning-free quadrature is not convergence. The pilot prefactor is analyst-selected, so no absolute `Δn` scale or physical material validation is inferred.

### Lumped laser: exact scope of the steady A-only algebra

The 41-point alpha.4 native calculation is an in-process scalar estimate with A-only recombination, `B=C=β=0`, injection efficiency 1, differential efficiency 0.5, confinement `Γ=0.44`, active volume 90 µm³, transparency density `N_tr=1.2×10¹⁸ cm⁻³`, and A coefficient `A=3.3333×10⁸ s⁻¹`. The representation `λ=1550 nm`, `n_g=3.6` gives `v_g=c/n_g=8.32756828×10⁷ m/s`, `ω=2πc/λ=1.21525907568×10¹⁵ rad/s`; with `Q=1215`, `τ_p=Q/ω≈0.99979 ps`. Using the unrounded `Q=ωτ_p` relation gives 1215.25907568 before the UI’s rounded display.

The source differential-gain coefficient `g₀=3×10⁻¹² m³/s` is converted by `g′=10⁴ g₀/v_g=3.60249222814×10⁻¹⁶ cm²`; UI representation rounds this to `3.6025×10⁻¹⁶ cm²`. The Q-derived total photon loss is `α_Q=ω/(Qv_g)=120.108679707 cm⁻¹`, after conversion from m⁻¹; the separately entered internal loss is zero. Using the saved rounded `g′=3.6025×10⁻¹⁶ cm²`, threshold gain balance is `Γ g′(N_th−N_tr)=α_Q`, so `N_th=N_tr+α_Q/(Γg′)=1.9577356615×10¹⁸ cm⁻³`. Under A-only recombination, the threshold current is `I_th=q V N_th A/η_i=9.409820898 mA`, with `V=90 µm³=9×10⁻¹¹ cm³`. Above threshold, this scalar estimate uses linear differential-efficiency power and clamps carrier density; the 41 exported rows exactly match the saved JSON values apart from floating-point roundoff (the maximum carrier discrepancy is 768 cm⁻³ at ~10¹⁸ cm⁻³, about 4.1×10⁻¹⁶ relative).

The cited [2019 laser article](https://www.mdpi.com/2076-3417/9/3/602) concerns time-dependent gain switching. This scalar implementation does not integrate coupled carrier/photon rate equations, so no transient waveform, modulation response, or paper steady-data agreement is claimed. The paper supplies no matching numerical steady threshold/L–I dataset; the threshold equation is a derived ideal limit, not a paper measurement.
### AI search: numerical definitions and interpretation

The manually authored periodic cell used a 1×1 µm square, 0.5 µm slab with index 3.464102, a centered circular air inclusion, air/air exteriors, normal s polarization, and a 41-point spectrum from 2992 to 3012 nm at 0.5 nm spacing. The three basis-49 radii were 0.20 and 0.19 µm for training and 0.21 µm for the held-out design. The resumed basis-74 calculations checked radii 0.20 and 0.19 µm. The campaign’s five total records include the original three checkpoint designs; only two basis-74 spectra were new in the resumed run. A preceding one-design attempt is preserved as partial. A structure edit cleared the saved range while an earlier preview remained visible; the corrected range was saved and inspected before rerun. That observation did not prove a Save-persistence defect.

At 3002 nm, the basis-49 R/T values were 0.1281418343/0.8718581657 at radius 0.20 µm, 0.1461045505/0.8538954495 at 0.19 µm, and 0.1100214050/0.8899785950 for held-out radius 0.21 µm. For each design, max `|R+T−1|` was between `3.77×10⁻¹⁵` and `4.66×10⁻¹⁵`; absorptance was within approximately `±5×10⁻¹⁵`. This is floating-point consistency, not convergence. The training-radius 0.20 µm basis-49 vs basis-74 maximum absolute R/T changes were `9.684×10⁻⁶`; at 0.19 µm they were `1.723×10⁻⁴`. These two geometries are a basis-sensitivity check only.

The three positive score targets use transforms `y₀=ln(max(objective,10⁻²⁴))`, `y₁=ln(max(volume contrast,10⁻¹²))`, and `y₂=ln(max(XZ contrast,10⁻¹²))`; coverage targets remain untransformed. In target space, `MAE=mean(|ŷ−y|)` and `RMSE=sqrt(mean((ŷ−y)²))`. With one held-out case, these are identical for each target. The absolute natural-log errors were 0.0307333 for the exterior objective, 0.0166319 for volume contrast, and 0.0136670 for XZ contrast. The corresponding relative errors after exponentiation are `exp(ŷ−y)−1`, or −3.0266%, −1.6494%, and −1.3574%. The 95% interval check is `|ŷ−y|≤1.96σ`; with one held-out point, coverage is only 0 or 1. Coverage was 0/1 for the exterior objective and 1/1 for the two contrast metrics. Both measured field-coverage metrics were zero. GP hyperparameter warnings reached configured bounds. One holdout cannot establish calibration or generalization.

The approximately 10⁻¹⁵ “field sampling relative error” is the maximum coefficient-reconstruction versus direct-field absolute difference at three fixed in-cell probes, divided by the maximum absolute direct field. It checks representation/sign consistency for those probes, not spatial sampling, Fourier convergence, or physical accuracy. Energy balance near machine precision is also a numerical identity check, not candidate acceptance. All five campaign rows remain `feasible=false` and `verified=false`.

### Representative-cell transport: SI equation check

The finite alpha.8 cell was 0.3×0.4×1.0 µm with 4×4×8 cells, full-face Ohmic contacts, top at +0.01 V, bottom at 0 V, and insulating lateral faces. Its single homogeneous material used analyst-selected coefficients; the “GaAs” electrical label did not make these calibrated GaAs parameters. Electron mobility was 100 cm²/(V·s) = 0.01 m²/(V·s), and donor density was 10¹⁶ cm⁻³ = 10²² m⁻³.

For uniform low-field electron drift, `σₙ=q μₙ n`. Using `q=1.602176634×10⁻¹⁹ C` gives `σₙ=16.02176634 S/m`. The applied field is `E=ΔV/L=0.01 V/(10⁻⁶ m)=10⁴ V/m`; thus `Jₙ=σₙE=1.602176634×10⁵ A/m²`. The cross section is `A=(0.3×10⁻⁶)(0.4×10⁻⁶)=1.2×10⁻¹³ m²`, so

`I=JₙA=q μₙ n A ΔV/L=1.9226119608×10⁻⁸ A`.

The saved top current was `1.9226119608000012×10⁻⁸ A`, relative difference `6.88×10⁻¹⁶`; bottom current was equal and opposite. Current balance was zero. The maximum continuity residual `4.88×10⁻²⁸ A` was below the estimated `1.96×10⁻²¹ A` current roundoff floor. The selected UI export had two bias rows and 28 columns and matched all 56 numeric summary values exactly. This checks a uniform equation in one toy model, not a mesh-converged semiconductor calculation.

## Optical-field method, normalization, and uncertainty

The three alpha.4 native fields runs used a manually authored 1×1 µm periodic cell, 0.5 µm slab (`n=3.464102`, `k=0`), centered air circle (`r=0.2 µm`), and air half-spaces at 3001.666667 nm. Illumination was normal-incidence s polarization, φ=0, with normalized incident amplitude. Their execution source provenance is alpha.4 commit `37a8dea74b9a897ee011d98ff7d03f301304bb23`; the native phasor archives do not embed the application version. Outputs are normalized complex phasors, not calibrated V/m or W/m².

For nonmagnetic media with the `e^(−iωt)` convention, Maxwell’s equations are `∇×E=iωμ₀H` and `∇×H=−iωεE`. With impedance-scaled magnetic field H_norm=Z0 H_SI and consistent length units, these are expressed as `∇×E=i k₀H` and `∇×H=−i k₀εE`, `k₀=2π/λ`. The derived intensity-like quantity is `E²=Σ_j|E_j|²`, and peak-amplitude time-averaged flux is `S=(1/2)Re(E×H*)`. Incident E points along +y and H along −x. Because amplitudes are normalized, no absolute field or power scale is claimed. The primary [S4 planewave-excitation API](https://web.stanford.edu/group/fan/S4/python_api.html#S4.Simulation.SetExcitationPlanewave), [field API](https://web.stanford.edu/group/fan/S4/python_api.html#S4.Simulation.GetFields), and [units guide](https://web.stanford.edu/group/fan/S4/units.html) document the underlying solver quantities.

For lateral sample count `N` and volume depth count `D`, cell-midpoint coordinates are `x_i,y_i=((i+1/2)/N−1/2) µm`, and `z_k=0.5(k+1/2)/D µm`. XY is at z=0.25 µm; XZ lies at y=0 and uses N for its z count. The 25/9 and 49/17 samples are nonnested: there is only one exact common midpoint per volume/plane group. Basis 121→225 relative-L2 changes at common 25/9 points were 4.8239% in E and 0.8134% in H; E² relative-L2 change was 7.9411%. The exact same-grid basis225 XY mean `S_z=0.437226704769279` implies `T=2<S_z>=0.874453409538558` because unit-normalized air incidence has `S_inc=0.5`; an independent native S4 basis225 spectrum gave `T=0.874453409538692`. This checks normalization/flux consistency at the matching wavelength and cell, not field convergence or an absolute SI calibration. Figure 5 of Fan and Joannopoulos is a dark eigenmode, not this driven field; no field-shape or mode agreement is claimed.

### Route 19 — finite-contact transport: analyst-selected resistance diagnostic

The alpha.8 native case used a 0.3×0.4×1.0 µm homogeneous analyst-defined n-type slab, 4×4×8 base mesh, 10¹⁶ cm⁻³ donors, electron mobility 100 cm²/(V·s), insulating lateral faces, full-face contacts, 0/10 mV biases, and equal electron/hole contact resistivities ρc=10⁻⁵ Ω·cm². A separate same-study control changed only structured contact resistivities to zero; the retained freeform note still says 10⁻⁵ and is stale for that control. The 16/32 depth refinements restored ρc=10⁻⁵ and changed only nz from 8 to 16/32. All four native selected exports match their saved summaries exactly (56 numeric cells each).

For a nominal uniform-density limiting estimate, with `n=10²² m⁻³`, `μ=0.01 m²/(V·s)`, `q=1.602176634×10⁻¹⁹ C`, `A=1.2×10⁻¹³ m²`, `L=10⁻⁶ m`, and `V=0.01 V`, bulk resistance is `Rbulk=L/(qμnA)=520.125756205 kΩ` (520.1258 kΩ rounded). Convert contact resistivity by `10⁻⁵ Ω·cm²=10⁻⁹ Ω·m²`, giving `Rcontact,total=2ρc/A=16.666666667 kΩ`; hence nominal `I=V/(Rbulk+Rcontact,total)=1.8629175029151926×10⁻⁸ A`. The observed nz=8 current differs by `1.5351127296637598×10⁻⁶` using the denominator `I_nominal` in `|I_observed−I_nominal|/I_nominal`; this is not a roundoff-sized discrepancy. The native nz=8,16,32 currents are `1.8629146431`, `1.8629114351`, and `1.8629092555 ×10⁻⁸ A`; this is small but nonzero depth sensitivity, not an error-order or convergence proof. The same-mesh zero-contact control is `1.9226119608×10⁻⁸ A`.

The bulk density is not exactly uniform at nonzero bias: the nz=8 solved n range is `9.9894369×10¹⁵` to `1.0010523×10¹⁶ cm⁻³`, with maximum relative deviation from nominal ND `1.0563×10⁻³`. Therefore the nominal-ND series formula is an independent limiting estimate, not an exact benchmark. The profile-derived resistance uses the solved quasi-Fermi edge conductance and reproduces the saved current by construction; it is not independent evidence. Physical electrostatic field, drift and diffusion, and quasi-Fermi voltage drops all contribute; do not describe the nonuniform profile as drift-only. The current balance and tiny continuity/Poisson residuals establish numerical conservation/linear-solve consistency for these runs, not accuracy against a calibrated device.

### Route 20 — coupled dielectric: capacitor and Airy null checks

The alpha.8 native UI-authored case used a 10×10×1 µm analyst-defined dielectric slab, a 4×4×8 electrical mesh, εr,static=5, σ=0, zero donor/acceptor density, full-face potential contacts, top 0 V and bottom +1 V. The resulting potential increases with z, so `E_z=−∂φ/∂z≈−1.000000×10⁶ V/m`; the bottom terminal carries positive charge and the top negative charge. The saved mapped optical material was a rounded n=2.236068, k=0 layer in air on both sides, normal s polarization, φ=0, 10×10 µm periodic supercell, basis 9, and five wavelengths (1400,1450,1500,1550,1600 nm), evaluated at both 0 and 1 V. Electro-optic and interband switches were off. The job requested two uniform slices/layer; the generated optical geometry has eight 0.125 µm intervals because `custom_device_optics` takes the union of requested uniform-slice boundaries and the boundaries of eight electrical z cells (nine boundary points). It is not an eight-slice setting entered by the user.

The capacitor derivation is `A=(10 µm)²=1×10⁻¹⁰ m²`, `d=1 µm=10⁻⁶ m`, and `C=ε₀εrA/d`. Using the solver's SciPy `epsilon_0` value (CODATA 2022, `ε₀=8.8541878188×10⁻¹² F/m`) gives `C=4.4270939094×10⁻¹⁵ F=4.4270939094 fF`. Then `Q=CΔV=4.4270939094 fC` at 1 V, `|E|=ΔV/d=10⁶ V/m`, and `U=½CV²=2.2135469547×10⁻¹⁵ J`. Saved terminal charges are `Qtop=−4.427093909400004×10⁻¹⁵ C` and `Qbottom=+4.427093909399985×10⁻¹⁵ C`; terminal sum is `−1.8933×10⁻²⁹ C`, normalized Poisson residual `1.83×10⁻¹⁴`, and relative Gauss balance `2.14×10⁻¹⁵`. Charge differs from the 2022-constant equation by `1.50×10⁻²⁹ C`. An earlier analysis used the 2018 `ε₀=8.8541878128×10⁻¹² F/m`, whose constant alone shifts predicted Q by `3.00×10⁻²⁴ C`; that difference is a constants-version mismatch, not solver roundoff.

For the lossless symmetric air/n/air layer, `F=(n²−1)²/(4n²)`, `δ=2πnd/λ`, `T=1/[1+F sin²δ]`, and `R=1−T`. With the actual rounded optical `n`, the five native spectra agree with Airy values to maximum absolute errors `1.06×10⁻¹⁵` in R and `8.89×10⁻¹⁶` in T. R/T are identical between the two biases; 90 selected-export numeric cells match saved values within `1×10⁻¹²` absolute tolerance. The exact Airy reflection minimum near `λ=2nd/3=1490.712 nm` lies between the 1450 and 1500 nm samples; the nearest sample is 9.288 nm away, so the sampled nonzero R does not indicate a shifted resonance. The UI indicates mesh refinement was not verified: only the single 4×4×8 electrical mesh and one basis-9/five-point optical setup were run. Static εr and optical n² differ by `1.00624×10⁻⁷` because n was rounded. During authoring, a source audit found that changing the electrical material identity clears its optical override; retaining the same identity and override is supported. The completed job had a valid linked optical material, and a native first-step loss was not reproduced. This is an observed workflow clarification, not a confirmed data-loss defect or repair. This analyst-defined case has no active EO/interband response, no coupled-device benchmark, and no paper-agreement or convergence credit.

## Route 21 — Sesame1D illuminated short-circuit and bias sweep

### Setup and assumptions

This native UI route ran in Optical Design Studio 1.4.0-alpha.8, source commit `ea6bb3dd0be90e1e9a1fac9f8f43df3a79dde4a5`. The manually authored 1D CdS/CdTe domain spans 0 to 4.025 µm, with a 0.025 µm interface. The first region uses CdS, donor density 1×10¹⁷ cm⁻³; the second uses CdTe, acceptor density 1×10¹⁵ cm⁻³. Uniform generation is 3.3×10²⁰ cm⁻³s⁻¹, temperature 300 K, and the defect list is empty.

The entered material values were CdS: affinity 4.0 eV, gap 2.4 eV, relative permittivity 10, `Nc=2.2×10¹⁸ cm⁻³`, `Nv=1.8×10¹⁹ cm⁻³`, mobilities 100/25 cm²V⁻¹s⁻¹ and electron/hole lifetimes 10⁻⁸/10⁻¹³ s; CdTe: affinity 3.9 eV, gap 1.5 eV, relative permittivity 9.4, `Nc=8×10¹⁷ cm⁻³`, `Nv=1.8×10¹⁹ cm⁻³`, mobilities 320/40 cm²V⁻¹s⁻¹ and lifetimes 5×10⁻⁹/5×10⁻⁹ s. `Et=0`, radiative `B=0`, Auger `Cn=Cp=0`; these are explicit analyst assumptions, not fully specified Fig. 2 inputs.

Both ends are Ohmic. Selective surface velocities are left electron/hole `1×10⁷/0 cm s⁻¹`, right `0/1×10⁷ cm s⁻¹`. The paper does not fully specify these contacts; the values follow the manual recipe/tutorial interpretation, not an established exact reconstruction of the paper’s contacts. The corrected short-circuit baseline uses 51 nodes, includes the interface exactly, and requests 0 V. The first attempt with right hole velocity zero is retained as an incomplete 0/1 run and excluded from the corrected result.

### Governing equations and units

The steady 1D model solves electron and hole continuity with conventional current densities `Jn,Jp` in A cm⁻²:

```text
dJn/dx = q(R − G)
dJp/dx = q(G − R)
Jn = −q μn n dφ/dx + q Dn dn/dx
Jp = −q μp p dφ/dx − q Dp dp/dx
D(n,p) = μ(n,p) kBT/q
−d/dx(ε0 εr dφ/dx) = ρ,    ρ = q(p − n + ND − NA)
```

Here `x` is in cm for the transport unit system, `q=1.602176634×10⁻¹⁹ C`, number densities are cm⁻³, `μ` is cm²V⁻¹s⁻¹, `D` is cm²s⁻¹, `φ` is volts, and `G,R` are cm⁻³s⁻¹. For this form, use `ε0=8.8541878×10⁻¹⁴ F/cm`, the SI vacuum permittivity converted by dividing by 100; `εr` is dimensionless, making the Poisson equation dimensionally consistent with `ρ` in C/cm³. `ND` and `NA` are the entered donor and acceptor densities. Einstein’s relation uses the fixed 300 K temperature. The app’s plotted convention is `diode_current = −mean(Jx)`; the underlying `Jx` is conventional current along +x.

At the two Ohmic endpoints the selected contact model sets the applied contact potentials and uses the entered electron/hole surface velocities to define carrier exchange. The signed bias convention increases the right-contact electrostatic potential for positive voltage; no doping-dependent sign flip is applied. This contact closure is part of the analyst-selected boundary model and is not claimed to reproduce an unspecified paper boundary exactly.

### Implementation-tied derivation

This supplement explains the existing steady, nondegenerate, fixed-temperature model and numerical checks. It adds no simulation, fitted parameter, convergence result or paper-agreement credit. Energies below are in joules unless explicitly marked eV; q is positive elementary charge, θ=kBT and VT=θ/q.

#### 1. Physical equations and unit conversion

For this case without explicit charged defects, let φ be electrostatic potential, E=−dφ/dx, and ρ=q(p−n+ND−NA), with fully ionized entered dopants. In a homogeneous material, conventional charge currents and steady balances are

    Jn = −q μn n φ′ + q Dn n′,       Jp = −q μp p φ′ − q Dp p′,
    Dn,p = μn,p VT,
    Jn′ = q(R−G),                   Jp′ = q(G−R),
    −(ε0 εr φ′)′ = ρ.

Thus total current obeys (Jn+Jp)′=0 even when electron/hole currents vary through generation and recombination. SI units are x in m, densities in m⁻³, J in A/m², G,R in m⁻³s⁻¹ and ε0 in F/m. Spatial changes of affinity, gap and density of states require the generalized formulation in section 4; the homogeneous drift/diffusion expressions alone omit those material-gradient terms.

The wrapper chooses the backend's cm convention. Convert consistently:

| Quantity | SI value → numerical backend value |
|---|---|
| x; surface velocity S | m ×100 → cm; m/s ×100 → cm/s |
| n,p,ND,NA,Nc,Nv; G,R | m⁻³ ÷10⁶ → cm⁻³; m⁻³s⁻¹ ÷10⁶ → cm⁻³s⁻¹ |
| μ; D | m²/(V·s) ×10⁴ → cm²/(V·s); m²/s ×10⁴ → cm²/s |
| ε0; J | F/m ÷100 → F/cm; A/m² ÷10⁴ → A/cm² |
| Energy; B; Cn,p | J ÷q → eV numerically; m³/s ×10⁶ → cm³/s; m⁶/s ×10¹² → cm⁶/s |

In particular, ε0≈8.8541878×10⁻¹⁴ F/cm in the cm-based Poisson equation, and 1 A/m²=0.1 mA/cm². The wrapper converts its entered micrometre nodes to cm by ×10⁻⁴ before constructing Sesame. [Application wrapper, function sesame_transport, lines 54–79](https://github.com/Wgeshow/Optical-Design-Studio/blob/ea6bb3dd0be90e1e9a1fac9f8f43df3a79dde4a5/src/research_physics_worker.py#L54-L79).

Sesame then nondimensionalizes: N0=10¹⁹ cm⁻³, μ0=1 cm²/(V·s), L0²=ε0VT/(qN0), t0=L0²/(μ0VT), J0=qμ0N0VT/L0 and G0=N0/t0. Here ε0 must use F/cm when N0 uses cm⁻³. The unknowns are v=φ/VT and ηn,p=EFn,p/θ. The code's thermal energy in eV has the same numerical value as VT in volts. Saved densities, potentials and currents are multiplied by their scales again. [Scaling.__init__, lines 57–85](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/builder.py#L57-L85), [wrapper output conversion, lines 118–148](https://github.com/Wgeshow/Optical-Design-Studio/blob/ea6bb3dd0be90e1e9a1fac9f8f43df3a79dde4a5/src/research_physics_worker.py#L118-L148).

#### 2. Poisson and continuity on a control volume

For consecutive nodes define h−=xi−xi−1, h+=xi+1−xi and ℓi=(h−+h+)/2. Integrating a derivative across the node-centred control volume gives the right-face flux minus the left-face flux. With displacement flux Di+1/2=−εi+1/2(φi+1−φi)/h+, the interior equations are

    (Di+1/2 − Di−1/2)/ℓi − ρi = 0,
    (Jn,i+1/2 − Jn,i−1/2)/ℓi + q(Gi−Ri) = 0,
    (Jp,i+1/2 − Jp,i−1/2)/ℓi + q(Ri−Gi) = 0.

A shared face current enters its two neighbouring volumes with opposite signs. Adding the two continuity equations cancels G−R. The installed implementation uses the arithmetic face average εi+1/2=ε0(εr,i+εr,i+1)/2, not a separately assumed harmonic average. Its dimensionless residuals absorb q and the unit scales. Contact rows replace the interior balances: potential is held at the chosen endpoint value, while entered surface velocities set carrier exchange relative to equilibrium densities. [getF, densities and interior residuals, lines 35–114](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/getF.py#L35-L114); [contact residuals, lines 121–155](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/getF.py#L121-L155).

#### 3. SRH recombination from steady trap occupancy

For a single effective trap population NT, let f be its electron occupancy, cn,cp the capture coefficients and en,ep the emission rates. Capturing an electron or emitting a hole fills the trap; electron emission or hole capture empties it:

    df/dt = (cn n + ep)(1−f) − (en + cp p)f.

Setting this to zero and using detailed balance en=cn n1 and ep=cp p1 gives

    f = (cn n + cp p1)/[cn(n+n1)+cp(p+p1)].

The net electron removal rate equals the steady net hole removal rate:

    RSRH = NT[cn n(1−f) − en f]
         = NT cn cp (np−n1p1)/[cn(n+n1)+cp(p+p1)]
         = (np−ni²)/[τp(n+n1)+τn(p+p1)],
    τn=1/(NT cn),     τp=1/(NT cp).

For the effective Boltzmann trap convention used here, ni²=NcNv exp(−Eg/θ), n1=ni exp(Et/θ), p1=ni exp(−Et/θ), so n1p1=ni²; Et is relative to intrinsic energy. At np=ni² the net rate is zero, while np<ni² gives net thermal generation. The implemented bulk rate also permits B(np−ni²)+(Cn n+Cp p)(np−ni²); the authored case sets these added coefficients to zero. Empty explicit-defect lists do not remove bulk SRH lifetimes. NT here explains the entered lifetimes; it is not an additional charge density inserted into this model, nor an inferred measured trap density or capture cross section. [Builder.add_material, lines 249–266](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/builder.py#L249-L266); [get_bulk_rr, lines 60–68](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/observables.py#L60-L68).

#### 4. Generalized Scharfetter–Gummel link flux

Use the energy reference Ec=−qφ−χ and Ev=Ec−Eg. Boltzmann statistics imply

    wn = qφ/θ + χ/θ + ln(Nc/N0),
    wp = qφ/θ + χ/θ + Eg/θ − ln(Nv/N0),
    n = N0 exp(wn+ηn),        p = N0 exp(−wp−ηp).

Nc/N0 and Nv/N0 are dimensionless logarithm arguments. Affinity, gap and density-of-states variations therefore enter wn,wp explicitly. Differentiating these relations in the quasi-Fermi current laws yields

    Jn = qDn n ηn′ = qDn(n′−n wn′),
    Jp = qDp p ηp′ = −qDp(p′+p wp′).

On a link i→j of length h, freeze D and approximate w linearly; the link-fit approximation treats its current as constant. Multiplication by integrating factors gives

    (n exp(−wn))′ = [Jn/(qDn)] exp(−wn),
    (p exp(+wp))′ = −[Jp/(qDp)] exp(+wp).

For Δw=wj−wi, the required integrals are

    ∫i→j exp(−w) dx = h exp(−wi)(1−exp(−Δw))/Δw,
    ∫i→j exp(+w) dx = h exp(+wi)(exp(Δw)−1)/Δw.

Insert the endpoint densities and solve for current. With B(z)=z/[exp(z)−1] and B(0)=1,

    Jn,i→j = (qDn/h)[B(Δwn) nj − B(−Δwn) ni],
    Jp,i→j = (qDp/h)[B(Δwp) pi − B(−Δwp) pj].

Three analytic sign checks follow directly:

1. B(−z)=exp(z)B(z). Constant ηn,ηp gives nj=ni exp(Δwn), pj=pi exp(−Δwp), making both currents exactly zero in the algebra.
2. For Δw→0, B→1: Jn=qDn(nj−ni)/h and Jp=−qDp(pj−pi)/h, the correct diffusion signs.
3. In a homogeneous material with constant density and small potential step, B(z)=1−z/2+O(z²) gives Jn≈−qμn n Δφ/h and Jp≈−qμp p Δφ/h, both conventional drift currents along E=−Δφ/h.

Crucially, installed get_jn/get_jp use the mobility at the left site i: Dn,p=μn,p,i VT. They do not use the two-site mean suggested by the online derivation. Regular code branches are algebraically equivalent to the fluxes above; small-difference branches use Taylor expansions to reduce cancellation, rather than evaluating the displayed quotient literally at zero. This is an implementation observation, not an explanation assigned to the paper discrepancy. [get_n/get_p, lines 10–57](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/observables.py#L10-L57); [get_jn, lines 118–143](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/observables.py#L118-L143); [get_jp, lines 171–192](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/observables.py#L171-L192).

#### 5. Initialization and the Newton stopping rule

The wrapper seeds local neutrality and mass action: n0−p0=C, n0p0=ni², where C=ND−NA. Solving the quadratic gives n0=(C+√(C²+4ni²))/2 for C≥0. For C<0 it uses the equivalent, cancellation-resistant n0=2ni²/[√(C²+4ni²)−C]. The potential seed is v0=ln(n0/Nc)−χ/θ, with zero initial quasi-Fermi energies. This seed is not the final junction solution.

An equilibrium Poisson solve comes first. For each illuminated bias, the wrapper raises the right boundary by Vapp/VT relative to equilibrium, then starts the coupled solve from the preceding state. Thus illuminated 0 V is short circuit, not dark equilibrium. [Wrapper initialization and bias continuation, lines 86–118](https://github.com/Wgeshow/Optical-Design-Studio/blob/ea6bb3dd0be90e1e9a1fac9f8f43df3a79dde4a5/src/research_physics_worker.py#L86-L118).

For dimensionless u=(ηn,ηp,v), linearization F(u+δu)≈F(u)+Aδu gives Aδu=−F(u), A=∂F/∂u. The sparse linear solve supplies δu. Components exceeding magnitude one are damped to sign(δu)ln[1+1.72|δu|], then added to u. The installed solver stops when the maximum absolute undamped update is below tolerance, before applying that final small update. The entered tolerance 10⁻⁹ and maximum 300 iterations are numerical choices, not a physical-error tolerance or a proof of a small normalized residual. Failure stops the bias loop: earlier completed states are retained, and the failed bias is not counted as complete. [Solver.solve, lines 149–193](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/solvers.py#L149-L193); [damping, lines 198–203](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/solvers.py#L198-L203); [_get_system/_newton, lines 216–298](https://github.com/usnistgov/sesame/blob/e2769a9d15c64415a87a5cfb566cbf2f3dac309f/sesame/solvers.py#L216-L298).

#### 6. What the reported errors measure

The wrapper exports Jdiode=−mean(Jx) and section spread=max(Jx)−min(Jx). Their ratio spread/|mean(Jx)| measures within-state current consistency. The separate mesh sensitivity is |J101−J51|/|J51|. Neither is a bound on physical or spatial error. [Wrapper section reduction and export, lines 119–148](https://github.com/Wgeshow/Optical-Design-Studio/blob/ea6bb3dd0be90e1e9a1fac9f8f43df3a79dde4a5/src/research_physics_worker.py#L119-L148).

For paired author/native current-density samples in the same units, ΔJi=JUI,i−Jauthor,i, MAE=mean(|ΔJ|), RMSE=√mean(ΔJ²), and pointwise symmetric relative difference=2|ΔJ|/(|JUI|+|Jauthor|), when that denominator is nonzero. These are descriptive discrepancies, not acceptance tolerances. Exact export reproduction tests serialization; qGL is only an input-generation scale. No trap derivation, link equilibrium identity, Newton termination, small current spread, or two-grid comparison supplies missing paper inputs, validates interface physics or establishes paper agreement.

The [official numerical-method documentation](https://sesame.readthedocs.io/en/latest/physics/discretization.html) provides context. The equations here were derived independently using the executed source, rather than transcribing its displayed formulas. Installed Sesame2.0 source was traced to immutable revision e2769a9d15c64415a87a5cfb566cbf2f3dac309f; the cited source files were byte-verified against that revision. In particular, observables.py SHA-256 is 7a5cf4ade2790f61ad729ee006ebc05f9a4c16ac863f668f68cf72b69ae379ea. Application citations are pinned to the actual alpha.8 corresponding-source commit. No solver or substitute calculation was executed to create this supplement.

### Numerical method and checks

The baseline used Newton update tolerance 10⁻⁹ and maximum 300 iterations. It completed one state. The 19-point sweep then used the same 51-node mesh and all identical non-voltage inputs, varying only bias from 0 to 0.9 V in 0.05 V steps. The UI-exported 19-row, six-column CSV is byte-identical to the saved transport table (SHA256 `3422AB724023E79B97F8A30F3FBDCE7DB615EB9675906E4B166077641C348018`). The sampled diode current rises monotonically in the entered voltage order and changes sign between the last negative and positive samples; no fitted Voc is asserted. Largest within-state section spread divided by `|mean Jx|` is 7.27×10⁻⁷ at 0.05 V.

A separate 101-node 0 V run subdivides each of the 50 baseline intervals once. Audit of saved engine inputs shows the same non-mesh inputs; all 51 original nodes and x=0.025 µm are retained. The one-row selected UI export matches saved CSV byte-for-byte (SHA256 `ED925C50CF262D738D3CA8458EE96A903D178DD62F768DE638D692E585D15FD6`). Current is −15.0997109162 mA cm⁻² at 51 nodes and −15.0027154197 mA cm⁻² at 101 nodes, a 0.64237% two-grid sensitivity. Section-current spread/mean ratios are 2.72×10⁻⁹ and 8.84×10⁻⁹. These are within-state conservation checks, not estimates of spatial error. A two-grid pair does not establish asymptotic order or convergence.

An input-scale check gives `GL = (3.3×10²⁰ cm⁻³s⁻¹)(4.025×10⁻⁴ cm) = 1.32825×10¹⁷ cm⁻²s⁻¹`, so `qGL=21.2809 mA cm⁻²`. This is the charge-flux scale of uniform generation, not a predicted or validated collection efficiency. The observed current-to-`qGL` ratio is descriptive only. At the heterointerface, sampled band offsets after subtracting the local 1 nm electrostatic potential drop are +0.100 eV for the conduction edge and +1.000 eV for the valence edge, consistent with the entered affinities and band gaps. This checks the model against its own inputs, not independent physics.

### Primary-reference comparison and limits

The primary [Gaury et al. (2018) Sesame paper](https://arxiv.org/abs/1806.06919) Fig. 2(a) shows the illuminated 1D CdS/CdTe J–V curve; the authored case takes its Table I material values and uniform generation. A historical raster-only estimate from the cited 1160×1500 PNG (embedded resolution metadata 136.3472 dpi; no separate 400 dpi raster retained) put the Sesame 0 V current near −12.1±0.4 mA cm⁻². That earlier estimate is retained as historical, not used for the new numeric metrics.

A public author numeric vector is now available in Paul Haney’s CC0 Mendeley dataset ([DOI 10.17632/34gb6xjt4g.1](https://data.mendeley.com/datasets/34gb6xjt4g/1), published 28 April 2019). Its `jsesame` array in A/m² was parsed as literal data without executing the MATLAB file; the first 19 of 21 values exactly share the native 0–0.9 V bias samples. Conversion is `J_author(mA cm⁻²)=A m⁻²/10`; UI `diode_current_A_cm2` is multiplied by 1000. Both original current signs are retained. Across 19 paired points, MAE is 2.774021 mA cm⁻², RMSE 2.779462 mA cm⁻², maximum absolute difference 3.243478 mA cm⁻² at 0.90 V, and mean pointwise symmetric relative difference 24.32%, using `100|J_UI−J_author|/[(|J_UI|+|J_author|)/2]`. At 0 V, author −12.178013807 versus native −15.099710916 mA cm⁻² (difference −2.921697109 mA cm⁻²; 23.99% relative to author magnitude). No fit, interpolation or acceptance tolerance is applied. These are descriptive sampled-curve discrepancies, not an acceptance score.

Exact paper contact conditions, temperature, trap level, recombination coefficients, mesh, bias sampling and solver tolerances are not all specified. The recipe’s selective contact velocities, 300 K, `Et=0`, and zero `B/Cn/Cp` remain assumptions. Thus precise author data improves reference precision but does not establish exact reproduction or add agreement credit. Fig. 2(b) band profile was compared qualitatively only; no pixel residual was calculated. The small within-state current spread and 51→101 two-grid change do not establish convergence; a third grid and finer voltage spacing would be separate numerical checks.

The 2019 author 2D data file is identified as `heteroJunctionWithGB`, while the planned 2018 Fig. 3 route is a homojunction with a grain boundary. The 2019 full article describes a CdS/CdTe heterojunction with a grain boundary. That 2D curve is therefore not used as a numeric target for the planned 2018 case until setup/version and observable are matched.

The initial wrong-contact zero-row attempt, corrected baseline, full sweep and mesh comparison remain preserved as separate dated evidence. This route was first added in the dated alpha.11 scientific checkpoint at 21/28. The earlier alpha.10 aggregate remains frozen at 20 routes; later results below do not change those historical snapshots.

## Later route and Meep observations at this checkpoint

### Sesame 2D: nine completed bias points, paper mismatch retained

Alpha.8, source `ea6bb3dd0be90e1e9a1fac9f8f43df3a79dde4a5`, ran the manually authored 3 by 3 micrometre CdTe grain-boundary case on a 41 by 31 mesh. All nine biases from 0 to 0.8 V completed. The sampled diode current density increased from -94.3022 to -32.3213 mA/cm² without crossing zero; the full curve remains in the local evidence report. Both the initial short-circuit and nine-bias native exports matched saved tables. The short-circuit relative current spread was about 3.60e-11. This does not establish mesh or bias-step convergence.

The model couples Poisson's equation, -div(epsilon*grad(phi))=rho, with electron and hole drift-diffusion currents and steady carrier balance. In SI, Jn=q*mu_n*n*E+q*Dn*grad(n), Jp=q*mu_p*p*E-q*Dp*grad(p), E=-grad(phi), div(Jn)=q*(R-G) and div(Jp)=q*(G-R). Here phi is in volts, E in V/m, n and p in m^-3, mobility in m²/(V*s), D in m²/s, G and R in m^-3/s, and current density in A/m². The Einstein relation D=mu*kB*T/q supplies diffusion. The implementation converts the entered semiconductor cm-based quantities consistently, uses Scharfetter–Gummel edge currents and Newton iteration, and reports the diode convention as minus the mean longitudinal current. The detailed authored derivation in the release notes explains the edge integrating factor, trap occupancy and residual definitions.

The uniform prescribed G=3.3e21 cm^-3/s and thickness L=3e-4 cm give q*G*L=0.158615486766 A/cm² as the full-collection generation scale, not the predicted collected current. At 300 K, the intrinsic-to-midgap offset is (kB*T/(2*q))*ln(Nv/Nc)=0.0402452985544 eV for the entered densities of states. Thus the prose benchmark's trap 0.4 eV above midgap was entered as 0.3597547014456 eV relative to intrinsic energy. Contact velocities, mesh and the interpretation of the density for two transition populations remain explicit assumptions.

The [2018 primary paper](https://arxiv.org/abs/1806.06919) Fig. 3(a) raster reads are approximately -12.2 +/- 1.0 mA/cm² at 0 V and +17 +/- 2 mA/cm² at 0.8 V. The uncertainty bands are analyst visual-reading ranges. The application's -94.3022 and -32.3213 values do not agree. The same preprint's scripting example differs from its prose benchmark in generation profile, affinity, capture cross section and defect convention; its exponential generation cannot be represented by the old uniform-only UI. These differences prevent attributing the mismatch to a solver bug or claiming that the new profile control will resolve it. The later author's 2019 heterojunction data are a different case and were not substituted for this target.

### Meep cavity array: decay passed, spatial convergence unresolved

These runs used alpha.5, source `edd15d30e3170980d0cee9502d78141ac6cbd55e`. Increasing only resolution from 20 to 22 cells per lattice pitch retained the manually authored periodic cavity array, source, physical dimensions, 401 frequency samples, PML, padding and decay settings. Both reference and device met the field-decay target of 1e-7. The 22-cell device ended at a measured decay ratio of 9.85560e-8; its saved total runtime was 9525.39 seconds, versus 7172.515 seconds at 20 cells.

On the common 401-point grid, the maximum absolute changes in reflectance and transmittance were 0.912044 and 0.924596; RMS changes were 0.0713519 and 0.0723253. The 22-cell residual A ranged from -0.00861688 to 0.0143272. In the approximate paper Gamma-frequency window a/lambda=0.306–0.314, 41 samples gave RMS changes 0.219674 in R and 0.222672 in T. These are substantial spatial sensitivities despite the successful decay checks.

For a passive, nondispersive dielectric, the time-domain calculation advances Maxwell's curl equations, epsilon*dE/dt=curl(H)-J and mu*dH/dt=-curl(E), from initially zero fields with the prescribed pulse. E is in V/m, H in A/m, J in A/m², epsilon in F/m and mu in H/m; epsilon=epsilon0*n² for the stated dielectric model. Meep discretizes these coupled equations on a staggered Yee grid and advances E and H in alternating half-time steps. Lateral boundaries are periodic and the propagation direction has absorbing PML layers. Integrating the time-averaged Poynting flux gives incident, reflected and transmitted powers; R=P_ref/P_inc and T=P_trans/P_inc with the implemented outward-flux sign convention. A is calculated as 1-R-T, so R+T+A=1 is an identity, not an independent conservation test. For paired results X, max error=max|X_22-X_20| and RMS=sqrt(mean((X_22-X_20)^2)). These differences combine spatial discretization sensitivity with remaining temporal/boundary sensitivity; they are not roundoff estimates or certified error bounds.

The [Altug–Vuckovic paper](https://doi.org/10.1063/1.1639505) describes cavity-array bands. The approximate Gamma reading 0.310 +/- 0.004 is analyst raster uncertainty, not a tolerance or an exact driven-transmission feature. The current normal-incidence driven spectrum does not establish dark-mode, Q, group-velocity or full-band agreement. A separate 24-cell UI run is active; boundary refinement remains pending.

### PCSEL vertical mode: output consistency passed

The vertical and coupled-wave cases used alpha.8, source `ea6bb3dd0be90e1e9a1fac9f8f43df3a79dde4a5`. The manually authored King-inspired stack has 38 layers totaling 6376 nm, one patterned layer and one quantum-well layer. The period is 320 nm, with the documented triangular inclusion and finite-stack Dirichlet boundary assumptions.

The first vertical run returned lambda=1076.2888465 nm, effective index=3.3634026453, quantum-well overlap=0.0095368797 and patterned-layer overlap=0.3172895661. The actual spacing was 2.4994119953 nm across 2550 interior nodes. Its intensity sum, sum(I_i*h), was 0.9999999999999984. All three exported columns matched saved values. Reconstructing the saved discrete eigenproblem gave a relative L2 residual of approximately 1.83e-13; this is a self-consistency check, not a second solve or a mesh-convergence result.

The scalar TE equation is -Theta''+beta^2*Theta=k0^2*n(z)^2*Theta, with beta=2*pi/a and k0=2*pi/lambda. Central differences and u_i=n_i*Theta_i give diagonal (2/h^2+beta^2)/n_i^2 and adjacent off-diagonal -1/(h^2*n_i*n_(i+1)). Normalize sum(|Theta_i|^2*h)=1; then a layer overlap is the same sum restricted to that layer. With h and wavelength in nm, matrix entries have units nm^-2; the same equations hold in SI metres with consistent conversion. The residual reported above is ||D*u-k0^2*u||_2/(k0^2*||u||_2). The exact algebraic identities a/lambda=0.2973179561 and n_eff=lambda/a are checked independently of the eigenvalue residual.

This scalar finite-difference model and its finite boundary need separate grid and boundary refinements. The `guided` classification does not prove confinement against substrate leakage. The [King paper](https://doi.org/10.1364/OE.537452) profile and approximate wavelength cannot establish agreement without reconciling mode selection, material and boundary assumptions.

### PCSEL coupled waves: four modes, branch matching unresolved

At harmonic order 8, the same authored stack produced four frequency-ordered program labels A/B/C/D with power losses 41.2787723, 212.9268451, 203.6389621 and 31.9908893 cm^-1. The four-row native export matched saved values and labels exactly. Independently checking the saved 4x4 coupling matrix gave eigenvector residuals of order 1e-16.

The implemented four-basic-wave model solves C*b=Omega*b in the (+x,-x,+y,-y) basis. C and Omega are expressed in nm^-1; detuning is Re(Omega)*1e7 cm^-1 and power loss is 2*Im(Omega)*1e7 cm^-1. With the stated propagation convention exp(i*Omega*s), the amplitude contains exp(-Im(Omega)*s), so its squared magnitude decays twice as fast. This gives the factor two; 1 nm^-1=1e7 cm^-1. The matrix decomposition C=H+iR uses H=(C+C†)/2 and R=(C-C†)/(2i), where † is the conjugate transpose. Coefficient-vector normalization is not an absolute physical field normalization. The method follows the [Liang coupled-wave framework](https://doi.org/10.1103/PhysRevB.84.195119) with the application's explicitly limited local longitudinal closure.

Program label A is not established as King mode A. The paper's 17.0 cm^-1 loss and 21.9 cm^-1 discrimination are therefore retained as unmatched targets. Harmonic refinements, vertical sensitivity and paper branch identification remain pending. The later finite-device calculations are reported below. No fitting or relabeling was used to manufacture agreement.

## Route 25 — finite PCSEL modes and the meaning of the refinement

Three native alpha.8 calculations, source `ea6bb3dd0be90e1e9a1fac9f8f43df3a79dde4a5`, used the same manually authored 38-layer King-inspired stack, 320 nm period, triangular inclusion, scalar vertical profile, harmonic order 8 and 2000 by 2000 micrometre aperture. Only the finite-cavity collocation order changed, 8 to 12 to 20. The initial order-20 text entry briefly read 2; Check inputs caught it, and it was corrected before execution. No order-2 result exists. The paper's 20 by 20 discretization is not automatically the same as this Chebyshev order.

Order 8 returned 32 modes, of which 31 passed the application's validity checks. The rejected mode had a relative power-balance residual of 0.0786607 despite a small eigenvalue residual. Orders 12 and 20 returned 32 accepted modes each. Their largest relative power-balance residuals were 1.42387e-5 and 2.24252e-10. All summaries still explicitly state that convergence is not established. Native exports for orders 8 and 20 matched their saved 32-row, 13-column tables exactly. The order-12 selected UI export was missing at this checkpoint; its saved solver outputs are available and retained. Solver elapsed durations were not recorded in these artifacts, and file timestamps were not substituted for measured runtimes.

### Finite operator, boundary conditions and discretization

The four slowly varying basic-wave amplitudes form u=(u_+x,u_-x,u_+y,u_-y). At fixed underlying coupling matrix C, the envelope eigenproblem is A*u=Omega*u, with

`A = diag(i*Dx, -i*Dx, i*Dy, -i*Dy) + C tensor I`.

This is the implemented four-wave approximation, not a full-vector Maxwell calculation. Its outgoing boundary condition sets the incoming component to zero: u_+x at x=0, u_-x at x=Lx, u_+y at y=0 and u_-y at y=Ly. The corresponding unknowns are removed from the matrix. The finite-stack vertical Dirichlet boundary is an additional, separate modeling assumption.

For collocation order N, the dimensionless nodes are xi_j=(1-cos(j*pi/N))/2, j=0,...,N. Interpolating each component by its degree-N Lagrange polynomial gives a differentiation matrix; scaling it by 1/Lx or 1/Ly converts the derivatives to inverse length. Tensor products form the two-dimensional derivative operators. The implementation uses nm internally, so C, A and Omega have units nm^-1. The saved four-component fields are normalized using product Clenshaw–Curtis weights w_i*w_j so that sum(|u|²*w_i*w_j)=1 on the unit square. This normalization is not an emitted optical power in watts.

Sparse shift-invert iteration searches near the four infinite-cavity eigenvalues, asking for up to eight roots per seed and removing duplicates. Its returned set is not an exhaustive spectrum or proof of the global lowest-loss mode. The reference formulation and local longitudinal closure follow the [Liang coupled-wave framework](https://doi.org/10.1103/PhysRevB.84.195119); the implementation is in `src/pcsel_research.py`, functions `chebyshev`, `finite_modes` and `_finite_outputs`, in the stated corresponding source.

### Derivation of modal loss and numerical checks

Split C=H+iR, where H=(C+C†)/2 and R=(C-C†)/(2i). Multiply the finite eigenproblem by u† and integrate with the stated normalization. Taking the imaginary part removes the Hermitian bulk contribution. Integration by parts converts the derivative terms to boundary flux; zero incoming amplitudes leave outgoing flux only. Thus the continuous four-wave identity is

`2*Im(Omega) = 2*integral(u†*R*u) + outgoing-edge contribution`.

In the discrete calculation, g_rad=2*Re(sum(u†*R*u*w_i*w_j))*1e7 cm^-1. The edge term integrates the squared outgoing components on each edge, divided by the corresponding aperture length in nm, then multiplies by 1e7. Independently, g_total=2*Im(Omega)*1e7 cm^-1. The factor 1e7 converts inverse nm to inverse cm; the factor two arises because power is the squared magnitude of amplitude. Comparing the eigenvalue loss to the separately integrated radiation and edge losses supplies a numerical power-balance check.

The recorded balance residual is |g_total-g_rad-g_edge|/max(|g_total|,1e-30). The eigen residual is ||A*u-Omega*u||₂/max(||A*u||₂,1e-30). The implementation accepts a mode when the balance is at most 0.02, the eigen residual at most 1e-6, g_total>0, g_rad>=-1e-10 cm^-1 and g_edge>=0. These are application validity gates, not paper-specified agreement tolerances or convergence certificates.

The normalized-frequency correction uses f=f0*[1+Re(Omega)/(k0*ng)], with k0=2*pi*f0/a and a in nm, followed by lambda=a/f. The group index ng comes from the nondispersive vertical-profile model; it does not supply missing material dispersion. Conditional port fractions use eta_edge=g_edge/g_total, eta_surface=(g_rad/g_total)*up_fraction and eta_substrate=(g_rad/g_total)*(1-up_fraction). Their derived sum is not a second independent power-conservation test.

### Saved-field matching and remaining uncertainty

Between orders 12 and 20, the maximum wavelength change was 1.81551e-6 nm and maximum total-loss change was 3.25747e-4 cm^-1. To check that sorted rows represented the same returned numerical modes, an external read-only analysis compared all four complex field components. It evaluated their tensor polynomial interpolants on a common product Gauss–Legendre grid, normalized each to unit L2 norm and computed

`overlap(u,v) = |integral(u†*v)| / (||u||₂*||v||₂)`.

One-to-one assignment maximized the sum of squared overlaps. Removing the arbitrary global phase gives the normalized field distance sqrt(2-2*overlap). Products of degree-at-most-20 interpolants have degree at most 40 per axis; 24-point Gauss quadrature is exact through degree 47 in exact arithmetic. Repeating with 32 points checks numerical integration roundoff, not physical resolution.

All 32 order-12 to order-20 assignments preserved row identity, with minimum overlap 0.9999999972828619 and largest phase-aligned L2 distance approximately 7.37e-5. An independent interpolation and assignment implementation corroborated this result; integration differences were of order 1e-15. By contrast, order 8 to 12 did not preserve row identity throughout and had a minimum assigned overlap of only 0.231539. The low-order discrepancies must not be described as changes of already identified physical branches.

These checks support close agreement between two returned, discretized mode sets at the fixed underlying model. They do not establish continuum error bounds, complete spectral coverage, vertical/boundary convergence, physical material accuracy or paper mode identity. The [King study](https://doi.org/10.1364/OE.537452) supplies target discrimination 2.6 cm^-1 and substrate fraction 0.94 at a 2 mm aperture, but matching those targets requires compatible branches and port/model definitions. No fit or mode relabeling was used. Paper agreement remains unresolved.


## Remaining work and runtime interpretation

The 24-cell Meep run was still active at its recorded telemetry snapshot 2026-11-01T16:31:51.730503+00:00: phase Device, simulated time 263.11 of 4063 micrometres/c, after 1085.83 wall seconds in that phase. A linear time-allowance estimate is (allowance-current_time)*elapsed/current_time. It can overestimate a run that stops early on decay and excludes startup, finalization, later refinements and scientific acceptance. A current phase fraction is not a fraction of the entire campaign.

Remaining planned controls include the 24-cell result audit, separate PML and padding sensitivity, vertical-grid refinement, coupled-wave harmonic refinement, finite order 24, direct-chain far-field sampling/padding controls, RCWA poles and the bounded optical/band/field follow-up queue. Aperture retains a genuine missing compatible accepted native calibration prerequisite; no imported or fabricated acceptance record is substituted. No full scientific completion date is inferred from solver progress.

The published Sesame script's 100-by-100 uniform mesh misses required region/defect coordinates in the application's aligned-node model. The separately documented adaptation adds the junction and defect coordinates to yield 102-by-101 nodes. This changes the numerical mesh and is not an exact script reproduction. It remains an unrun plan at this snapshot. The 2018 preprint and 2019 article distinguish benchmark and script cases differently; their exact versions are kept separate.

The local report has searchable, sortable route sections in the order setup, theory and derivation, numerical method, results, primary comparison, limitations and next actions. Static link checks passed, while private-browser visual QA remains incomplete. An activation failure during the later manual UI workflow was recovered through fresh documented window selection; it is not evidence of a program calculation defect.

Raw projects, per-run libraries, reference datasets, paper PDFs, local logs and credentials are excluded from publication. These authored notes and aggregate metrics retain quantitative failures and uncertainty without exposing those materials.


## Prescribed exponential generation: theory and implementation

The new region control specifies a carrier-generation source for the semiconductor continuity equations. It is uniform across y and attenuates along the global +x direction. It does not solve optical reflection, interference, photon transport or wavelength-dependent absorption. The [Gaury et al. primary script](https://pmc.ncbi.nlm.nih.gov/articles/PMC7047709/) supplies the volumetric function directly; an incident photon flux is not specified in that script. The earlier [2018 preprint](https://arxiv.org/abs/1806.06919) contains a separate uniform-illumination benchmark description, so the script and that description remain distinct comparison cases.

For constant attenuation coefficient alpha and a prescribed source amplitude G0 at x0, the spatial initial-value law is dG/dx = -alpha*G, G(x0)=G0. Separating variables gives dG/G=-alpha*dx. Integrating from x0 to x yields ln[G(x)/G0]=-alpha*(x-x0), hence G(x)=G0*exp[-alpha*(x-x0)]. This is a spatial source profile, not a time-dependent carrier initial condition. In SI, x and x0 are in m, alpha is in m^-1, and G is in m^-3 s^-1. The UI uses x in micrometres, alpha in cm^-1 and G in cm^-3 s^-1; 1 micrometre=1e-4 cm, so its exponent is -alpha_cm^-1*(x_um-x0_um)*1e-4. Equivalently alpha_SI=100*alpha_cm^-1 and G_SI=1e6*G_cm^-3_s^-1.

For the script values G0=2.3e21 cm^-3 s^-1, alpha=23000 cm^-1 and x0=0, the 1/e attenuation length is 1/alpha=0.4347826 micrometres. At x=3 micrometres the attenuation factor is exp(-6.9)=0.00100778543, giving G=2.31790649e18 cm^-3 s^-1. These are analytic input checks, not outputs from a new transport run.

Integrating over a slab from x0 to x0+L gives the generated pair flux per area: integral(G dx)=(G0/alpha)*[1-exp(-alpha*L)]. Multiplying by the positive elementary charge q=1.602176634e-19 C gives a full-collection charge-flux scale Jgen. For L=3e-4 cm, integral(G dx)=9.98992215e16 cm^-2 s^-1 and Jgen=16.00561984 mA/cm^2, or 160.0561984 A/m^2. The alpha->0 limit follows from 1-exp(-alpha*L)=alpha*L+O((alpha*L)^2), yielding q*G0*L. This scale assumes one collected charge per generated pair and excludes recombination, injection and gain; it is not the predicted terminal current. The diode plotting convention is Jdiode=-mean(Jx), so an ideal generation-only contribution would have the opposite sign. For a region starting at a different global x, integrate its actual endpoints; do not restart the exponential at each material interface.

In this alpha.13 corresponding source, `src/qt_sesame_setup.py` converts explicit region controls to optional normalized profile settings; Uniform omits the optional object. `src/sesame_transport.py` validates finite inputs, alpha>=0 and x0 at or left of the region start. `src/research_physics_worker.py`, `sampled_region_generation` and `sesame_transport`, evaluates the exponential at the actual supplied global x nodes, broadcasts it across y, selects each node's authored region and divides by Sesame's generation scale before assigning the dimensionless source. Shared boundary nodes follow the existing ordered region assignment. Uniform retains the prior scalar branch. Zero amplitude or zero attenuation uses an exact constant-array branch; large nonnegative attenuation may underflow to zero without exponential growth.

Sampling this analytic source does not establish accuracy of the resulting transport solution. A transport test must separately check mesh/bias sensitivity, nonlinear residuals, current consistency, boundary conditions and matching paper assumptions. Floating-point exponential roundoff, spatial discretization error and reference uncertainty are different effects. No new transport execution, numerical convergence or paper agreement is claimed by this derivation.

## Explicit mesh authoring and the effect on discretization

The mesh builder creates an explicit coordinate list from the user's interval and count. It does not run a transport solver or choose a scientifically adequate resolution. For endpoints a<b in micrometres and N>=3 requested nodes, the uniform construction is x_i=a+i*(b-a)/(N-1), i=0,...,N-1. There are N-1 intervals, so the spacing is h=(b-a)/(N-1), and the endpoints are included. SI coordinates are x_m=1e-6*x_um. The y-axis follows the same construction in 2D; it is unavailable in 1D.

With the optional inclusion control selected, let B be the set of currently authored region-boundary and defect-endpoint coordinates on the selected axis. The intended node list is sort(unique({x_i} union B)). All required coordinates must lie within the explicit interval. Required coordinates take precedence over nearby uniform samples, and the final list is rechecked against the backend's alignment convention: zero relative tolerance with absolute tolerance max(1,abs(coordinate_um))*1e-12 in the numerical micrometre coordinate. That tolerance resolves numerical representation; it is not an allowed physical geometry error or a convergence criterion. Invalid, ambiguous, unrepresentable or out-of-range requests leave the prior axes unchanged.

For the primary Sesame script's interval 0 to 3 micrometres with N=100, h=3/99 micrometres. The desired positions 0.1, 2.9 and 1.5 micrometres correspond to uniform-grid indices 3.3, 95.7 and 49.5, respectively, so none is a node. Adding x=0.1 and 2.9 gives 102 x nodes; adding y=1.5 gives 101 y nodes. The result has 10302 node sites rather than 10000, and its spacings are nonuniform. This makes the explicitly authored junction and defect endpoints representable under the application's existing alignment requirement. It is an adaptation of the printed 100x100 script grid, not its exact reproduction. The [2018 preprint](https://arxiv.org/abs/1806.06919) also states that its illustrated benchmark used a nonuniform mesh; the actual benchmark coordinates are not supplied by that statement.

The implementation in `src/qt_sesame_setup.py` constructs a bounded one-dimensional proposal, validates current geometry and selected-axis capacity, previews its count, and writes the complete list only after an explicit Apply. The original coordinate editors remain available; transient builder controls are not serialized as physical settings. Optional geometry inclusion starts unchecked. No region, defect, material, bias, source profile or solver equation is changed by this action. Existing backend alignment validation in `src/sesame_transport.py` remains in force.

The helper rejects more than 10000 processed or output axis entries, a proposed 2D product above 1000000 nodes, and formatted text longer than the actual editor capacity. These are visible UI resource guards, not validated solver memory or runtime estimates. Preview drawing is capped at 201 mesh lines per axis with a visible explanation; all authored nodes remain in the calculation. A passing preview or input check does not establish convergence or guarantee that a large solve will fit available resources.

Changing this node list changes the discretization used by the existing Scharfetter-Gummel transport calculation. The source and continuity equations are unchanged. Subsequent analysis must compare actual mesh-refined native results and residuals, preserving contact, material, generation, bias and boundary assumptions. Agreement of saved input serialization or a successful Apply is not an estimate of spatial error, and floating-point duplicate tolerance is separate from both discretization error and uncertain paper inputs.


## Separate remaining editor limitation

A native optical-material editing sequence dropped three previously disabled circles from the editable object list. The precise individual UI transition was not isolated, while a targeted material-commit reproduction confirmed the loss in the synchronization code. The running control's geometry was corrected through visible UI edits and audited before attribution. A separate fix has passed source review and targeted tests but is not included in alpha.13; its packaged native acceptance remains pending. Material assignment before disabling objects avoids the observed sequence during the current tests, but this is a workflow workaround, not a repair claim. The initial wrong cavity-site draft and a short canceled run with two differing defaults remain excluded from scientific comparisons.


## Later evidence recovery and release-checker qualification

After the dated scientific snapshot above, the missing order-12 finite-area Results export was recovered through the native UI. All 416 cells in its 32-row, 13-column table exactly matched the existing saved order-12 output. This closes the earlier export-evidence gap without creating a new simulation, changing its numerical results or adding scientific-agreement credit. The curated metrics retain the explicitly dated earlier snapshot; this later qualification supersedes only its missing-export status.

The first release-checker pass rejected the correctly saved settings export because it expected internal worker metadata. The checker was corrected to recognize the actual engine/study/settings export envelope, with explicit format identification, unchanged original-byte hashes and the same visible-authoring, region-identity, scalar-amplitude and process-exit requirements. Fifteen synthetic public-helper tests and seven private-helper tests passed, and independent review confirmed the actual export. No worker fields were invented and no application or solver behavior changed for this correction.

Scientific results in this aggregate retain their actual tested versions and snapshot dates. Later active Meep boundary controls and ongoing route refinements are not included as completed or converged results in this fixed release snapshot.
