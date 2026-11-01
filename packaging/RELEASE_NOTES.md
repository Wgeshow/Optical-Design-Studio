# Optical Design Studio 1.4.0-alpha.6 — Meep grid alignment warnings

Experimental Windows x64 usability update · 1 November 2026

**Check inputs now shows the requested Meep pixel counts and approximate rounded cell dimensions.** The display updates when you edit resolution, cell dimensions, slab thickness, padding or PML. It warns when rounding changes a lateral periodic dimension and states that alignment does not establish convergence. The calculation reads the current UI tables and does not start a solver or fit material data. It does not silently change geometry or resolution.

Fractional resolution, the opt-in integrated Gaussian source, Estimate runtime and live phase timing from earlier experimental versions remain available. The new grid display is an estimate; the actual solver log is the authority for the represented cell. Runtime estimates remain dependent on measured history, stepping data and machine load.

## Grid calculation and derivation

Let L be a requested positive cell length in µm and ρ the resolution in cells/µm. In SI units L_SI=10⁻⁶L m and ρ_SI=10⁶ρ m⁻¹; the grid spacing is Δ=1/ρ_SI m. The desired number of cells is N*=L_SI/Δ=Lρ. Meep's positive-length nearest-pixel rule gives N=floor(N*+1/2), so the represented length is L_eff=N/ρ µm and the relative domain shift is (L_eff−L)/L. This is a representation calculation, not a bound on electromagnetic error.

For L=2.94 µm and ρ=40 cells/µm: N*=117.6, N=118 and L_eff=2.95 µm, a +0.3401% shift. Choosing ρ=20/0.49≈40.81632653 cells/µm makes the lateral count approximately 120 and L_eff≈2.94 µm. The propagation length is calculated separately: for d=0.2695 µm slab thickness and p=h=1 µm padding/PML, L_z=d+2(p+h)=4.2695 µm; at this fractional resolution N_z≈174.2653 rounds to 174 and L_z,eff≈4.263 µm. Thus lateral alignment does not imply all dimensions align.

The UI's near-integer display tolerance accommodates eight-decimal resolution entry; it is not the solver stopping tolerance. The implementation is in `src/fdtd_model.py:grid_alignment`, `src/qt_fdtd.py:FDTDPage.grid_alignment` and `src/qt_optical_journey.py:_checks`. The rounding rule follows [Meep 1.30.0 grid construction](https://github.com/NanoComp/meep/blob/v1.30.0/src/vec.cpp#L857-L873). Material refractive indices do not enter this grid estimate. Spatial, temporal and PML convergence still require separate calculations and appropriate reference comparisons.

## Download and tested scope

Extract the entire Portable Windows x64 `.7z` archive with 7-Zip, then open `Optical Design Studio.exe`; keep the backend and `_internal` folder together. The matching Source ZIP, checksums and `VALIDATION.json` accompany this experimental release. Bundled desktop/S4 support needs no separate Python; Meep uses its configured supported Linux/WSL runtime. Stable 1.3.5 and its updater remain unchanged.

This build passed 75 targeted staged-source tests, 34 packaging/privacy/license checks, exact comparison of 201 compiled modules in each executable plus the standalone Meep runner, eight frozen critical checks and seven actual Windows startup checks. Fresh GPT-6.1 Terra manual checks confirmed the 40→40.81632653 display change, 2D/3D axes, immediate Estimate response and a separately captured normal-close exit code 0. The smoke manually authored cell/slab dimensions but retained default optical materials; it ran no scientific simulation. Operational Stop was not rerun on alpha.6. The full installer/scientific matrix and native field-map checks were not rerun; omitted checks remain explicit.

The dated aggregate below reports 13 of 28 routes with native execution and five earlier scoped reference agreements. Meep's aligned-grid cap-400 run still fails Device decay and passive-power checks; cap 800 is in progress at this checkpoint. GME cutoff/basis sensitivity remains unresolved. The homogeneous periodic-transport mesh pair agrees at roundoff scale without establishing general device accuracy. These application/release checks do not establish physical validation. Public assets exclude raw acceptance projects, research data, logs, private paths and paper PDFs.

---

# 1 November 2026 — current 13-route UI campaign progress

This current local aggregate supersedes the earlier alpha.5 progress snapshot for campaign totals, while leaving dated publication notes immutable. It summarizes manually entered native UI calculations and independently checked aggregate results; it contains no private machine paths, raw arrays, per-run identifiers, or imported geometry. Historical scientific calculations retain their actual tested application versions. Alpha.5 is now a published experimental prerelease with seven public assets verified. Its public notes preserve the dated 12/28-route, five-agreement checkpoint; this live aggregate includes subsequent verified results at 13/28 with the same five agreements. Detailed local evidence is retained separately; this authored aggregate records the tested scope and results.

## Campaign status

- **13 of 28** routes have a completed native UI calculation or simulation workflow.
- **15** routes remain unexecuted.
- **13** executed routes still have unresolved convergence or comparison questions.
- **5** pre-existing scoped reference agreements remain; Nov. 1 high-field, laser, electrical.iv, GME and periodic transport work adds no new paper-agreement count.

These counts separate UI construction/execution, numerical convergence, and external reference agreement. A calculation completing in the UI is not by itself convergence or physical validation.

## Alpha.5 publication and validation scope

Optical Design Studio **1.4.0-alpha.5** is published as an experimental prerelease: [release and downloads](https://github.com/Wgeshow/Optical-Design-Studio/releases/tag/v1.4.0-alpha.5). Seven public assets and their digests were verified. The corresponding source commit is `edd15d30e3170980d0cee9502d78141ac6cbd55e`. Release checks recorded 72 selected source checks, 34 packaging/privacy/license checks, exact compiled matches for 201 modules per executable, 8 critical packaged checks, 7 Windows startup checks, and the documented fresh packaged UI scope. The full installer matrix was not rerun. These build and UI checks are separate from scientific convergence and paper agreement.

Alpha.5 added an integrated-Gaussian source option that defaults off and a fractional spatial-resolution input. The fractional value `40.81632653 cells/µm` represents 20 cells per `0.49 µm` lattice period. In the aligned-grid/integrated-source Meep run, Reference decay passed but Device decay failed at the cap, and passive-range violations remained. Its comparison with the earlier standard-source spectrum changes both source waveform and grid/domain representation, so neither effect is isolated and no spectral correction is established.
## High-field optical response

### Setup

Five calculations were manually entered through the high-field UI: one 41-sample spectrum and four 81-sample refinements. The model used individual electron and hole masses of `0.1106 m₀`, band gap `1.519 eV`, temperature `300 K`, reduced Fermi levels `−50`, fields `0` and `6.6 MV/m`, and absorption prefactor `1 cm⁻¹√eV`. The Kramers–Kronig (KK) cases used energy-grid/cutoff pairs `4096/12 eV`, `4096/12 eV` on the 81-point spectrum, `8192/12 eV`, `8192/24 eV`, and `16384/24 eV`.

### Theory and scope

For each heavy-hole branch, the effective reduced mass is `μ_j=m₀ m_e,r m_h,j,r/(m_e,r+m_h,j,r)`, where the supplied masses are ratios to the free-electron mass `m₀`. For the equal UI masses this gives `μ=0.0553m₀`. Photon energy is converted from wavelength by `E(eV)=1239.8419843320026/λ(nm)`. With kinetic energy `K=max(E−E_g,0)` and thermal energy `E_T=k_B T/e` in eV, the local occupation proxy is

\[
f_j(K)=\mathrm{expit}\!\left(\frac{K m_{e,r}}{m_{e,r}+m_{h,j,r}}\frac{1}{E_T}-\eta_p\right)-\mathrm{expit}\!\left(\eta_n-\frac{K m_{h,j,r}}{m_{e,r}+m_{h,j,r}}\frac{1}{E_T}\right).
\]

Let `r_j=m_e,r m_h,j,r/(m_e,r+m_h,j,r)=μ_j/m₀`. The weighted coefficient is `C_j=P r_j^(3/2)/Σ_i r_i^(3/2)`, where the supplied prefactor `P` has units `cm⁻¹√eV`. At zero field, the branch absorption is `α_j=C_j√K/E f_j(K)`; the implementation uses this zero-field expression whenever `|F|<1000 V/m`. At nonzero field, the Airy energy and profile are

\[
\theta_j=\frac{1}{e}\left(\frac{\hbar^2 e^2 F^2}{2\mu_j}\right)^{1/3},\quad
g(x)=\mathrm{Ai}'(x)^2-x\mathrm{Ai}(x)^2,
\]
\[
\alpha_j=\frac{\pi C_j\sqrt{\theta_j}}{E}
\left[g\!\left(\frac{E_g-E}{\theta_j}\right)-g\!\left(\frac{E_g+E}{\theta_j}\right)\right]f_j(K).
\]

The `E_g+E` term is the implemented counter-rotating subtraction. The occupation factor is a local band-edge proxy; finite-field transitions are nonlocal in momentum and this is not a multiband susceptibility. The state absorption sums the branches. The reference is the unoccupied zero-field edge `α_ref=P√max(E−E_g,ref,0)/E`. Thus `Δα=α_F−α_ref` and `Δk=Δα λ/(4π)` after converting wavelength to metres and absorption to m⁻¹.

For the KK transform, begin with `n(ω)−1=(2/π)PV∫₀∞ Ωκ(Ω)/(Ω²−ω²)dΩ` and `α(Ω)=2Ωκ(Ω)/c`, where `Ω` is angular frequency in rad/s, `κ` is dimensionless, and SI absorption is in m⁻¹. Substitution gives `(c/π)PV∫α(Ω)/(Ω²−ω²)dΩ`. Represent photon energy numerically in eV as `E_eV=ℏω/e`, so `ω=eE_eV/ℏ`. Then `dΩ=(e/ℏ)dE′` and `Ω²−ω²=(e/ℏ)²(E′²−E²)`, which yields

\[
\Delta n(E)=\frac{c\hbar}{\pi e}\,\mathrm{PV}\int\frac{\Delta\alpha_{SI}(E')}{E'^2-E^2}\,dE'
=\frac{100c\hbar}{\pi e}\,\mathrm{PV}\int\frac{\Delta\alpha_{cm^{-1}}(E')}{E'^2-E^2}\,dE'.
\]

For the Airy energy, `F` is V/m, `μ_j` is kg, `e` is C, and `ℏ` is J·s; `θ` is reported in eV after division by `e`. In the occupation factor, `k_B` is J/K, `T` is K, and `m_e,r,m_h,r` are dimensionless. For the KK expression, `E′` and `E` are numerical energies in eV, `c` is m/s, `ℏ` is J·s, `e` is C, and `100` converts stored cm⁻¹ to m⁻¹. The implementation integrates over `[10⁻⁵ eV,E_cut]`, where `E_cut` is 12 or 24 eV. It interpolates `Δα` and evaluates the principal value as `Δα(E′)/(E′−E)` times `1/(E′+E)`, exactly the squared-energy denominator above. Grid order and upper cutoff require separate convergence checks.

### Numerics and results

All five native calculations completed with zero reported KK quadrature warnings. The selected UI CSV exports exactly match all seven audited numeric arrays in the saved numerical data. The 41- and 81-sample absorption spectra agree exactly at the 41 shared energy nodes. This confirms consistent evaluation at those nodes; it does not prove that the energy spacing resolves every feature.

For sampled `Δn` curves `n_left(E_i)` and `n_right(E_i)`, error is measured as `max_i|n_right(E_i)−n_left(E_i)|` and `RMSE=√[(1/N)Σ_i(n_right−n_left)²]`; the percentage divides that pointwise maximum by `max_i|n_left(E_i)|`. At 8192 points, expanding the upper cutoff from 12 to 24 eV gives pointwise maximum difference `2.6340×10⁻⁷` (`101.7%` of the left curve peak). The peak magnitudes themselves differ by `7.8827×10⁻⁸`. This holds point count fixed but also coarsens linear-grid spacing from `(12−0.5)/8191=0.00140398 eV` to `(24−0.5)/8191=0.00286900 eV`; it is not an isolated tail/cutoff test. Increasing point count at fixed 12 eV gives pointwise maximum difference `2.6910×10⁻⁸` (`10.2%` of the left curve peak); increasing point count at fixed 24 eV gives `1.7659×10⁻⁸` (`9.8%`). These fixed-cutoff comparisons refine grid spacing. Zero quadrature warnings do not establish KK cutoff/grid convergence.

A future UI-entered spacing-matched cutoff comparison is `8192 points / 12 eV` versus `16383 points / 23.5 eV`: each linear segment from 0.5 eV has spacing `(12−0.5)/8191=(23.5−0.5)/16382=0.00140398 eV`. It is planned only, not run, and would compare the added high-energy tail at approximately fixed spacing; it would not prove a global KK error bound.

### Primary-paper comparison

The primary reference is Duque-Gomez and Sipe, [“The Franz–Keldysh effect revisited” (2014)](https://arxiv.org/abs/1403.1619), Figures 4(a,b), dashed independent-particle two-band curves. Each simulated curve and the manually digitized paper curve were divided by their own 1.90 eV Figure 4(a) endpoint. No horizontal shift, amplitude fit, or parameter fit was applied.

On the 81-sample normalized curves and digitized raster values `y_app,i` and `y_fig,i`, metrics are `MAE=(1/N)Σ_i|y_app,i−y_fig,i|` and `RMSE=√[(1/N)Σ_i(y_app,i−y_fig,i)²]`. Figure 4(a) shape differences are MAE `0.004956` and RMSE `0.006197`. Figure 4(b)'s normalized differential-absorption shape differences are MAE `0.009762` and RMSE `0.016765`; oscillatory features are less reliable against the raster. Estimated raster-reading uncertainty is `±0.01 eV` horizontally and `±0.03×10⁴ cm⁻¹` vertically. These are analyst digitization uncertainties, not tolerances supplied by the authors.

### Limits

The selected prefactor is arbitrary, and the UI lacks the paper's refractive-index and velocity-matrix-element inputs. Equal individual UI masses are not the paper's material parameterization. Endpoint-normalized shape similarity therefore does not validate absolute absorption, `Δk`, `Δn`, or all assumptions in the paper calculation. This remains a preliminary figure comparison, not an added scoped agreement.

**Evidence filenames:** `HIGH_FIELD_MANUAL_UI_RECIPE.md`, `high_field_optics.py`, `analyze_nov1_high_field.py`, `nov1-high-field-analysis.json`.

## Lumped-laser steady-state A-only calculation

### Setup

A fresh native UI calculation used the narrow, ideal A-only steady-state case: wavelength `1550 nm`, group index `3.6`, `Q=1215`, confinement `Γ=0.44`, transparency density `1.2×10¹⁸ cm⁻³`, differential gain `3.6025×10⁻¹⁶ cm²`, active volume `90 µm³`, `A=333,330,000 s⁻¹`, `B=C=0`, injection efficiency `1`, differential efficiency `0.5`, internal loss `0`, spontaneous factor `β=0`, gain compression `0`, temperature `300 K`, and thermal resistance `0`. The UI exported a completed 41-point sweep from 0 to 20 mA in 0.5 mA steps; the raw result records unchanged inputs. The selected CSV exactly matches all eight numeric sweep columns in the raw result.

### Theory and analytical checks

For actual captured UI inputs, the independent scalar calculation uses

\[
\omega=\frac{2\pi c}{\lambda},\quad \tau_p=\frac{Q}{\omega},\quad
\alpha_Q=\frac{1}{(c/n_g)\tau_p\,100},
\]

where `α_Q` is in `cm⁻¹`; `(c/n_g)τ_p` is a length in metres and its inverse is divided by 100 to convert `m⁻¹` to `cm⁻¹`. The threshold carrier density and current are

\[
N_{th}=N_{tr}+\frac{\alpha_Q+\alpha_i}{\Gamma g'},\qquad
I_{th,A}=\frac{q V_{cm^3} A_{SRH} N_{th}}{\eta_{inj}}.
\]

With `B=C=0`, below threshold the carrier balance is

\[
N(I)=\frac{\eta_{inj} I_A}{qV_{cm^3}A_{SRH}}.
\]

Here `A_SRH` denotes the SRH recombination coefficient `333,330,000 s⁻¹`, while subscripts `_A` on current denote amperes. With `q` in coulombs, `N` in cm⁻³ and `V_cm3=90 µm³=9×10⁻¹¹ cm³`, the product `q V_cm3 A_SRH N` has units of amperes. Equivalently, use `V_m3=9×10⁻¹⁷ m³` with `N_m3=10⁶ N_cm3`. Below threshold, `I_A` is current in amperes; sweep values in mA are multiplied by `10⁻³`. Above threshold, the application clamps carriers at `N_th` and computes the above-threshold photon-density term `S_app=η_inj(I_A−I_th,A)τ_p/(qV_cm3)`. Its output law is `P_W=[η_d hc/(qλ)] max(I_A−I_th,A,0)/(1+εN_th)`; for this case `ε=0`, so output is linear in excess current. The independently evaluated equations reproduce the saved model result, not an experimental measurement.

### Numerics and results

The saved threshold is material gain `272.97427206167424 cm⁻¹`, carrier density `1.9577356615174858×10¹⁸ cm⁻³`, and current `9.409820898145572 mA`. Independent calculations using the actual exported inputs reproduce all three threshold values with zero residual at stored precision. All 41 applicable checks pass: below threshold, carrier balance and zero output; above threshold, carrier clamping and linear output; at threshold, zero output. Across the sweep, the largest carrier-density residual is `768 cm⁻³` (maximum relative residual `4.10×10⁻¹⁶`); remaining nonzero residuals are floating-point roundoff. The actual representation uses analyst choices `λ=1550 nm` and `n_g=3.6`, yielding `Q=1215.25907568` before UI rounding to 1215. For comparison, the paper parameter conversion `g' = 10⁴ g₀/v_g` with `g₀=3×10⁻¹² m³/s` gives `3.60249222814×10⁻¹⁶ cm²`, rounded in the UI to `3.6025×10⁻¹⁶ cm²`. These are representation choices, not paper-reported λ or group-index parameters. The UI's in-process calculation completed; this route has no backend solver job because it is a lumped scalar model.

### Paper comparison

Li et al., [“Step-Pulse Modulation of Gain-Switched Semiconductor Pulsed Laser,” Eqs. 1–3 (2019)](https://doi.org/10.3390/app9030602), supplies a model and parameters but no numerical steady threshold or steady L–I dataset. Its ideal `β=0`, A-only onset limit is derived from

\[
\Gamma g_0(N_{th}-N_t)=1/\tau_p,\qquad I_{th}=qVN_{th}/\tau_N.
\]

Using the paper's published parameters and the modern charge constant gives the derived limit `N_th=1.9575757575757578×10¹⁸ cm⁻³` and `I_th=9.409146414218183 mA`; using the paper's rounded charge constant gives `9.396363636363636 mA`. The actual UI-rounded calculation is higher than the modern-constant ideal by `0.008168%` in density and `0.007168%` in current. The modern-versus-paper charge convention alone changes current by about `0.1360%`. These differences describe rounded model inputs and constants, not experimental error bars. Because the paper has no corresponding numerical steady-state data, this is not paper agreement.

### Limits

The comparison is restricted to the `β=0`, `B=C=0`, zero-compression, ideal steady-state threshold limit. The application does not solve coupled time-dependent carrier/photon rate equations. Its heuristic modulation output is excluded from the paper comparison. Finite-β behavior, pulse timing and waveforms, absolute optical power, raw photon-density normalization, and a spatial device or optical-mode result are not validated.

**Evidence filenames:** `LASER_MANUAL_UI_RECIPE.md`, `laser_model.py`, `laser2019-steady-threshold-reference.json`, `analyze_nov1_laser_aonly.py`, `nov1-laser-a-only-analysis.json`.

## Electrical I–V: homogeneous Ohmic equation diagnostic

### Setup

A manually authored native UI study used one constant-conductivity conductor, `σ=1 S/m`, with analyst-selected relative permittivity `5`, zero doping, a `10 × 10 × 1 µm` bar, and full-face top and bottom potential contacts. The top terminal was swept at `−1, −0.5, 0, 0.5, 1 V`; the bottom was held at zero. Two runs used `8³` and `16³` spatial meshes. Static dielectric charge mode was selected; carrier transport and thermal solving were disabled.

### Theory

For a uniform rectangular bar, `G=σA/L` and `I_top=G(V_top−V_bottom)`. Here `A=(10 µm)(10 µm)=1×10⁻¹⁰ m²`, `L=1 µm=1×10⁻⁶ m`, so `G=1×10⁻⁴ S` and the signed top current is `I_top=1×10⁻⁴ V_top A`. The application convention is positive conventional current entering the device from its swept top terminal; the bottom terminal current is equal and opposite.

### Numerics and results

All five requested biases completed at both meshes. The selected native UI CSV exports match their saved five-row outputs row-by-row within `1×10⁻¹²` absolute tolerance across all four fields. Both saved studies report zero terminal-current balance at every bias. The largest current deviation from the exact decimal Ohmic values is `2.71×10⁻²⁰ A` (`2.71×10⁻¹⁶` relative at `|V|=1 V`); the maximum `8³` to `16³` current change is the same roundoff scale. This shows mesh stability for the uniform full-face slab, not a general refinement order or accuracy claim for nonuniform geometries.

### Paper comparison

Noor et al. describes PN semiconductor drift-diffusion diode `J–V`. This native route used a fixed-conductivity conductor with transport disabled, so the paper is not a quantitative target and receives no agreement credit.

### Limits

This is a scoped equation diagnostic for the manually selected homogeneous bar. It does not model carrier continuity, injection, recombination, depletion, contact resistance, nonlinear transport, or a semiconductor diode. That checkpoint raised campaign execution to 11/28; scoped paper/reference agreements remained five.

**Evidence filenames:** `ELECTRICAL_MANUAL_UI_RECIPES.md`, `analyze_nov1_ohmic_iv.py`, `nov1-ohmic-iv-mesh-comparison.json`, `nov1-ohmic-8-analysis.json`, `nov1-ohmic-16-analysis.json`, `nov1-ohmic-8-ui-export.csv`, `nov1-ohmic-16-ui-export.csv`.

## PCSEL periodic transport: homogeneous analyst diagnostic

### Setup

A fresh native UI study used a manually authored, unpatterned semiconductor slab in a periodic cell of `0.3 × 0.4 µm`, with `1 µm` thickness, donors `1×10¹⁶ cm⁻³`, zero acceptors, and full-face ideal ohmic top/bottom contacts. The analyst-selected material used `εr=12.9`, `Nc=1×10¹⁸ cm⁻³`, `Nv=1×10¹⁹ cm⁻³`, band gap `1.4 eV`, affinity `4 eV`, electron/hole mobilities `100/20 cm²/(V·s)`, and `300 K`; recombination coefficients/lifetime were zero. Biases were `0` and `0.01 V`, swept at the top terminal. The `0.3×0.4 µm` period area is `0.12 µm²`; no pattern or inclusion was present. These are analyst inputs, not measured material data or values taken from a paper.

### Theory and units

For a uniform low-field n-type slab, the drift estimate is `J≈q μ_n n E`, with `E=ΔV/L`. Integrating over the period cross-section `A` gives `I≈q μ_n n(A/L)ΔV`. Using `q=1.602176634×10⁻¹⁹ C`, assumed `n≈N_D=1×10¹⁶ cm⁻³`, `μ_n=100 cm²/(V·s)`, `A=(0.3×10⁻⁴ cm)(0.4×10⁻⁴ cm)=1.2×10⁻⁹ cm²`, `L=1×10⁻⁴ cm`, and `ΔV=0.01 V`, the field is `100 V/cm` and conductivity is `σ=q μ_n n=0.1602176634 S/cm`. Thus `J≈σE=16.02176634 A/cm²` and `I≈JA=1.9226119608×10⁻⁸ A`. This is a deliberately simple low-field equation check, not an independent carrier-density measurement.

### Numerical method and results

The native conformal solver used a P1 tetrahedral finite-element weak form, Fermi–Dirac carrier statistics, lumped charge/recombination, element-average conductivity and an exact residual Jacobian. Two meshes were compared while every non-mesh engine input, including both biases, remained identical. The coarse mesh used edge segments 3, xy size `0.08 µm`, z maximum step `0.25 µm`, 100 nodes and 312 tetrahedra; the refined mesh used edge segments 6, xy size `0.04 µm`, z maximum step `0.125 µm`, 522 nodes and 2160 tetrahedra. Cell volume was `0.12 µm³` at both. Periodic matching-face triangle counts were 24 per axis and 96 per axis, respectively.

Both selected native UI exports have two rows and seven numeric columns and exactly match their saved native CSV fields; the refined export and saved CSV share SHA-256 `856d07410cc9888916d491e7d6637b39779db398ab4b9d411129e2bf0610d07a`. At `0.01 V`, coarse top/bottom currents are `+1.9226119607999046×10⁻⁸ A` and `−1.9226119608000012×10⁻⁸ A`; refined values are `+1.922611960799936×10⁻⁸ A` and `−1.9226119608000118×10⁻⁸ A`. The expected current is `1.9226119608000002×10⁻⁸ A`. Absolute top-current equation residuals are `9.5622×10⁻²² A` (relative `4.9736×10⁻¹⁴`) coarse and `6.4189×10⁻²² A` (relative `3.3386×10⁻¹⁴`) refined. The coarse/refined top-current difference is `3.1433×10⁻²² A`, or `1.6349×10⁻¹⁴` relative to the coarse current. Relative terminal imbalance is `5.0252×10⁻¹⁴` coarse and `3.9410×10⁻¹⁴` refined; scaled residuals are `9.8571×10⁻¹⁷ V` and `2.8717×10⁻¹⁶ V`; contact-range overshoot is zero at saved precision. The two meshes show only roundoff-scale sensitivity for this ideal uniform slab. Two meshes do not establish a refinement order, discretization-error estimate, or general accuracy.

### Paper comparison and limits

No matched primary-paper case is claimed for this analyst-authored homogeneous cell. The drift-law comparison is equation consistency for analyst-selected coefficients, not an additional scoped paper agreement. The ideal periodic cell and full-face contacts do not represent a finite aperture, patterned PCSEL, diode, or laser; no experimental material accuracy is claimed. The mesh pair is a limited sensitivity check only; convergence order and paper comparison remain unresolved.
## Guided-mode expansion: Fan 2002 slab modes

### Setup

Three reciprocal-cutoff native UI GME runs, plus one guided-index expansion, used a square lattice with period `a=1000 nm`, a `500 nm` patterned dielectric slab (`n=√12`), one centered air hole of radius `r/a=0.20`, and air half-spaces. The calculation used normal incidence at the Γ point, guided-mode indices `[0,1]`, and 12 requested modes. Reciprocal cutoff `gmax=3.1, 4.1, 5.1` was varied while the other saved inputs were held fixed. These cutoff choices are numerical trials, not settings reported by Fan and Joannopoulos.

### Theory and comparison scope

The UI reports dimensionless frequency `a/λ` and perturbative radiation-loss magnitude `|Im(f)|`; its quality estimate is `Q=f/[2|Im(f)|]`. At Γ the paper states that doubly degenerate modes can couple to normal-incidence waves, whereas singly degenerate states are uncoupled by symmetry. This makes a degenerate finite-loss pair a plausible candidate class, but branch identity requires field symmetry or polarization-overlap evidence. Figure 12(d) is a driven transmission spectrum with Fano line shapes; a plotted transmission minimum need not coincide with an eigenfrequency. The article's text gives approximately `Q=213` for the lowest-order resonance at `r/a=0.20` ([Fan and Joannopoulos, PRB 65, 235112](https://doi.org/10.1103/PhysRevB.65.235112); paper DOI).

### Numerics and results

The near-degenerate pair tracked provisionally as sorted bands 4 and 5 has mean frequency `0.38136973`, `0.38205016`, and `0.38248123 a/λ` and mean perturbative `Q=253.49`, `267.36`, and `277.80` at `gmax=3.1`, `4.1`, and `5.1`. Frequency shifts by `0.1784%` then `0.1128%`; Q shifts by `5.47%` then `3.90%`. All saved summaries leave convergence unestablished. All four selected UI exports exactly match their saved native mode tables. At fixed `gmax=5.1`, expanding guided indices from `[0,1]` to `[0,1,2,3]` changes the provisional band-4/5 pair frequency by `−0.0035%` and perturbative Q by `−1.83%`; other sorted band labels reorder, so band-index tracking is not branch proof.

### Primary-paper comparison

The paper's first narrow Figure 12(d) transmission feature is raster-estimated near `0.377–0.382 a/λ` with approximate reading uncertainty `±0.002`; the gmax-5.1 candidate eigenfrequency is `0.000481 a/λ` above the nominal interval, within that raster uncertainty. Its perturbative `Q=277.80` is `30.4%` above the article's approximate `213`. This is only a plausible frequency-region and mode-class comparison. No eigenfield symmetry/polarization overlap identifies the branch, and the observables differ; no quantitative paper agreement is claimed.

### Limits

Only reciprocal cutoff was varied: guided-mode indices `[0,1]` and requested mode count 12 stayed fixed. Mode tracking by sorted band index is provisional without eigenvector overlap data, and radiative Q is perturbative. These calculations do not reproduce the paper's driven transmission spectrum. The route is native-executed with partial reciprocal-cutoff and guided-index sensitivity evidence; basis convergence and paper comparison remain unresolved.

**Evidence filenames:** `PCSEL_FAN2002_MANUAL_UI_RECIPES.md`, `analyze_nov1_gme.py`, `nov1-gme-external-analysis.json`, `analyze_nov1_gme_guided_basis.py`, `nov1-gme-guided-basis-analysis.json`, `nov1-gme-5p1-guided0123-ui-export.csv`, `nov1-gme-3p1-ui-export.csv`, `nov1-gme-4p1-ui-export.csv`, `nov1-gme-5p1-ui-export.csv`, `fan2002-figure12d-reference.json`.

## Photonic-crystal cavity array: cap-400 Meep diagnostic

### Setup

The 1.4.0-alpha.4 native Meep run used the manually authored 3D cavity-array cell, 40 pixels/µm, 401 spectral samples over 1400–1800 nm, p polarization, 1 µm PML and padding, Courant factor 0.5, and decay target `10⁻⁷`. Its only saved job-setting difference from the prior cap-200 run is post-source runtime cap `400 µm/c` vs `200 µm/c`; all other job JSON fields match exactly.

### Theory and numerical interpretation

The runner first computes an empty-cell Reference phase and then a Device phase, subtracting reference flux to obtain reflectance/transmittance. At normal incidence in an air/air configuration, the lossless passive expectation is `0≤R,T≤1`; residual `A=1−R−T` is derived from those values, so `R+T+A=1` is an algebraic identity rather than an independent conservation check. A rough finite-window spectral scale is `Δ(a/λ)≈a/(cT)`: approximately `0.00245` for the 200 µm/c cap and `0.001225` for 400 µm/c. This is an order-of-magnitude time-window estimate, not a measured resolution or acceptance tolerance.

### Current results

The cap-400 run completed in `1721.4694 s` runner time; Reference took `780.3362 s` and Device `869.3645 s`. Both phases reached the cap with decay flags false. The summary records 401 samples and warns power balance is outside the passive range by more than 3%. The cap-200 baseline also has both decay flags false and the same warning. The selected native UI CSV export has 401 rows and matches the saved CSV row-by-row within `1×10⁻¹²` absolute tolerance across all seven numeric columns; per-column maximum absolute differences are `2.27×10⁻¹³ nm` for wavelength, `2.22×10⁻¹⁶` for each of R and T, `9.80×10⁻¹⁷` for A, and `3.55×10⁻¹⁵` for incident flux; angle and frequency are exact. These quantities have different units, so no cross-column maximum is reported. This establishes export integrity only.

The two saved 401-point spectra share an exact frequency grid; comparison uses rowwise pairs with no interpolation. Define `δy_i=y_400,i−y_200,i`, `max_abs=max_i|δy_i|`, and `RMS=√[(1/401)Σ_iδy_i²]`. Over the full window, `R` has max/RMS difference `1.04065/0.122765`, `T` `0.997682/0.133840`, and residual `A` `1.33771/0.165772`. Maxima occur near normalized frequency `a/λ≈0.273`, near the low-frequency end. In coarse `Γ`-eigenband context `0.306≤a/λ≤0.314` (41 samples), `max|δT|=0.323363` and RMS `0.128460`.

Passivity counts are still bad. Cap-200 has `R>1` at 3 samples, `T>1` at 20, and residual `A<0` at 214. Cap-400 has `R>1` at 4, `T>1` at 16, and `A<0` at 205. The count reduction is not convergence. For cap-400, ranges are `R=0.008525…1.170518`, `T=0.002063…1.173590`, and `A=−0.623163…0.458071`. Since `A=1−R−T`, `R+T+A=1` is an identity, not an independent energy-conservation test.

Sampled transmission minima are retained as unfitted grid points in `nov1-meep-cap400-comparison.json`; they are not paired as resonances or used to infer `Q`.

The alpha.5 integrated-source `40 cells/µm` run was stopped through the native UI during Reference at displayed `t=269 µm/c`; the log ends at `t=276 µm/c` during cancellation. The Reference decay ratio stayed near `2.129×10⁻⁵` across `t=120–260 µm/c`, above the `10⁻⁷` target. It produced no Device phase or spectrum. A separate integrated-source run at `40.81632653 cells/µm` completed with Reference decay pass at `t=80.017 µm/c`, ratio `5.4877×10⁻⁹`, and phase time `154.07 s`; Device decay failed at the cap with final ratio `4.8616×10⁻⁴` against target `10⁻⁷` after `979.92 s`. It retains a passive-range warning: `R>1` at 1/401 points, `T>1` at 21/401, and `A<0` at 205/401. Against the alpha.4 standard-source cap-400 spectrum on the identical frequency grid, max/RMS pointwise differences are `R=0.99488/0.12707`, `T=0.67581/0.12011`, `A=0.77434/0.12162`. This comparison is confounded by both integrated-source setting and grid resolution: the computational cell changes from `2.95 × 2.95 × 4.275 µm` at 40 cells/µm to `2.94 × 2.94 × 4.263 µm` at 40.81632653 cells/µm. The integrated source represents a free polarization that vanishes after the pulse, following the [Meep source-current definition](https://meep.readthedocs.io/en/latest/FAQ/#how-is-the-source-current-defined). Meep’s [FAQ on static fields and DFT](https://meep.readthedocs.io/en/latest/FAQ/#how-do-i-include-static-fields-in-a-frequency-domain-calculation) states residual electrostatic fields do not affect nonzero-frequency DFT quantities. No DC-field explanation or spectral correction is established, and no eigenmode/Fano/Q claim is made.

### Primary-paper comparison

Altug and Vuckovic, [“Two-dimensional coupled photonic crystal resonator arrays,” Fig. 2 (2004), DOI 10.1063/1.1639505](https://doi.org/10.1063/1.1639505), supplies approximate `Γ`-point eigenband context. A driven R/T spectrum is a different observable; proximity of a transmission feature to an eigenband coordinate does not identify a mode, prescribe a Fano minimum, or validate `Q`.

### Limits

Both cap-400 phase decay tests failed, and passive-range violations persist. The large differences establish sensitivity to post-source cap but not convergence, mode identity, Fano agreement, or physical correction. The primary Altug–Vuckovic `Γ`-point eigenband is coordinate context, not a driven transmission target. The native UI export audit passes at the stated roundoff tolerance; it does not change scientific status. The alpha.5 aligned-grid saved-output comparison is in `nov1-meep-aligned-comparison.json` with a single-run audit in `nov1-meep-aligned-run-analysis.json`; the read-only comparison utility is `compare_nov1_meep_aligned.py`. Its selected native UI export has 401 rows and matches the saved seven-column result at serialization roundoff: maxima are 2.27×10⁻¹³ nm for wavelength, 2.22×10⁻¹⁶ for R/T, 9.89×10⁻¹⁷ for A, and 3.55×10⁻¹⁵ for incident flux; angle and frequency are exact. This confirms export integrity only.

## Alpha.5 source controls and scientific limits

### Setup and theory

A separate source candidate adds an opt-in integrated-Gaussian source setting and a fractional spatial-resolution field. The fractional control can express 20 grid cells per `0.49 µm` period as `20/0.49 = 40.81632653 cells/µm`; the earlier integer-only value 40 represented a `2.95 µm` cell for a requested `2.94 µm` period. Moving to an aligned `2.94 µm` cell changes both grid and domain representation, so that future comparison is not a pure discretization refinement. The integrated-source setting is opt-in and defaults off; static-field FAQ reasoning motivates a controlled test but does not show that nonzero-frequency spectra are fixed.

### Verification and limits

The cumulative v2 source suite passed 66 tests; the clean staged candidate passed 72 source checks and 34 packaging checks. Build completed in `142.437 s`. All 201 compiled modules match within each executable; the standalone runner matches exactly. Eight frozen critical checks and actual Windows startup passed. Fresh packaged-UI checks confirmed integrated-source default-off/checked behavior, fractional-resolution `40.81632653` persistence through navigation, input preparation, and the immediate Estimate no-data message. A native Stop request cancelled the integrated-source resolution-40 Reference-only run; a separate fresh no-solve candidate chooser closed normally with process exit 0. The alpha.5 source is published at the corresponding commit and seven public assets were verified. These UI/source checks remain separate from scientific results.

**Evidence filenames:** `nov1-ui-change-checkpoint.md`, `nov1-fractional-resolution-v2-implementation.json`, `nov1-source-cumulative-v2-hashes.json`, `nov1-source-v2-final-tests.log`, `nov1-private-publication.json`, `manual-packaged-ui.json`.

## Alpha.6 grid-alignment build and native UI control check

### Build and frozen verification

The separate alpha.6 candidate passed 75 selected source checks, 34 packaging/privacy/license checks, and exact compiled-module matching for 201 modules per executable. Its bounded critical frozen profile passed 8/8 checks, and actual Windows startup passed 7/7 checks. These results do not constitute scientific validation or publication. The manual Meep grid-warning check described next is UI-control evidence only.

### Meep grid rounding and observed controls

For requested positive cell length `L` and resolution `ρ` in pixels per micrometre, the Meep 1.30 implementation forms an integer grid count `N=floor(Lρ+0.5)` (C++ positive-value conversion after adding 0.5) and uses grid spacing `1/ρ`; therefore the represented size is `L_eff=N/ρ`. The implementation also emits a warning when the requested size is not an integer number of pixels ([Meep v1.30.0 `grid_volume` spacing, `vec.cpp` lines 283–289](https://github.com/NanoComp/meep/blob/v1.30.0/src/vec.cpp#L283-L289); [`vol3d` rounding, lines 857–873](https://github.com/NanoComp/meep/blob/v1.30.0/src/vec.cpp#L857-L873)). The source uses strict integer rounding and warns when a requested dimension is not an integer number of pixels; the manual UI observation below records the UI’s displayed near-integer alignment state separately. This rounding rule predicts the previously observed alpha.5 geometry:

- At `ρ=40 cells/µm`, requested `2.94 × 2.94 × 4.2695 µm` yields `N=118 × 118 × 171` and `L_eff=2.95 × 2.95 × 4.275 µm`.
- At `ρ=40.81632653 cells/µm`, the same request yields `N=120 × 120 × 174` and `L_eff≈2.94000000004 × 2.94000000004 × 4.26300000006 µm`, displayed as `2.94 × 2.94 × 4.263 µm` at reported precision. The slab thickness was `0.2695 µm`; the requested cell Z extent is `4.2695 µm` (slab plus surrounding padding), distinct from the rounded `4.263 µm` represented at fractional resolution.

Terra's alpha.6 native UI control check manually authored a `2.94 µm` cell and `0.2695 µm` slab; default GaAs/SiO2 materials remained selected and do not change the grid-rounding calculation. At resolution `40`, the 2D UI showed a lateral warning (X 117.6→118; Z 170.78→171). At `40.81632653`, it showed lateral alignment (X 120→120; Z 174.2653061→174). The 3D control added Y 120→120 at the aligned resolution. This is the UI’s near-integer status display, not a change to Meep’s source rounding rule. Estimate returned responsively. No solver was launched, so this verifies the UI warning/alignment display and input interaction, not that geometry was automatically corrected, nor any spectral change or convergence. Operational Stop was not rerun. One close attempt has no captured exit; a separate owned-window close exited normally with code 0.

### Limits

The source formula explains grid rounding; the native UI check establishes the displayed warning/alignment state for these tested inputs. Neither establishes a solution to the passive-power violations, validates a nonzero-frequency spectrum, or makes the alpha.5 integrated-source/aligned-grid comparison unconfounded. The alpha.6 candidate is not published, and no scientific validation is claimed.
## Next actions

1. Continue the 15 remaining user-authorized routes in queue order, preserving native entry, execution, convergence and reference scopes. The periodic transport route now has a two-mesh sensitivity pair; do not infer general convergence from it.
2. Alpha.6 grid-alignment candidate build checks passed: 75 source checks, 34 packaging checks and 201 compiled modules per executable. Its critical frozen profile (8 checks) and Windows startup (7 checks) have now passed; Terra passed the native grid-warning UI control check without a solver run; warning visibility does not imply corrected geometry. Do not treat this as a release or a scientific result. Maintain the five scoped reference agreements unless later evidence independently supports a scoped quantitative comparison.

**Aggregate evidence filenames:** `nov1-session-report.json`, `nov1-route-queue.json`, `nov1-pcsel-transport-analysis.json`, `nov1-pcsel-periodic-export-audit.json`, `nov1-pcsel-periodic-refinement-analysis.json`, `nov1-pcsel-periodic-refinement-export-audit.json`, `nov1-pcsel-periodic-refined-ui-export.csv`, `NOV1_ALPHA6_NATIVE_GATE_HANDOFF.md`, `nov1-grid-alignment-alpha6-build-handoff.json`, `nov1-electrical-iv-native-acceptance-updates.json`, `nov1-meep-native-acceptance-updates.json`, `nov1-private-publication.json`, `nov1-ui-change-checkpoint.md`, `nov1-fractional-resolution-v2-implementation.json`, `nov1-source-cumulative-v2-hashes.json`, `nov1-source-v2-final-tests.log`, `build_qa_report.py`. This aggregate reflects the live 13-route state after verified alpha.5 publication. The public alpha.5 notes remain a dated 12-route snapshot; see the separate live-report addendum. Alpha.6 passed the stated build/critical/startup gates and manual grid-warning control check; it is not published.


