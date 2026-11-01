# Optical Design Studio 1.4.0-alpha.5 — Meep grid and pulse controls

Experimental Windows x64 usability update · 1 November 2026

Meep spatial resolution now accepts fractional values. For a 0.49 µm lattice period, enter 40.81632653 cells/µm to represent 20 cells per lattice period. The source panel also exposes an opt-in **Integrated Gaussian source** setting, default off, with a summary in Check inputs. Both Reference and Device use the selected source setting. These controls make the convergence study possible through the native UI; they do not establish convergence by themselves.

The earlier **Estimate runtime** button, live phase progress, elapsed time and estimated remaining time remain available. Estimates use matching measured history or live stepping data and do not launch a hidden solver. With no matching history the UI says so promptly. Stop remains available. A phase percentage describes its configured simulation-time budget, not overall completion or convergence.

## Download and validation

Download the Portable Windows x64 `.7z`, extract the complete archive using 7-Zip, and open `Optical Design Studio.exe`. Keep the backend executable and `_internal` directory together. The corresponding Source ZIP supports inspection and rebuilding. Bundled desktop/S4 support needs no separate Python; Meep uses its configured supported Linux/WSL runtime.

This build passed 72 targeted staged-source tests, 34 packaging/privacy/license checks, exact compiled-code comparison for 201 modules in each executable plus the standalone Meep runner, eight frozen critical checks, and seven actual Windows startup checks. A fresh GPT-6.1 Terra manual check verified fractional entry persistence, integrated-source controls, input preparation, responsive Estimate behavior, native Stop/cancellation and normal close. The full installer and scientific matrix was not rerun. Exact hashes and gate scope are recorded in `VALIDATION.json`.

Stable version 1.3.5 and its updater are preserved. The authored aggregate below is a dated scientific checkpoint, separate from release acceptance. It includes numerical results, assumptions, equations, comparison limits and outstanding work. No raw acceptance projects, research runs, private paths, logs or paper PDFs are included in public assets.

---

# 1 November 2026 — aggregate UI campaign progress

This evidence note summarizes only manually entered native UI calculations and independently checked aggregate results. It contains no private machine paths, PDFs, raw arrays, per-run identifiers, or imported geometry. The tested native application was **Optical Design Studio 1.4.0-alpha.4**, corresponding to public source commit `37a8dea74b9a897ee011d98ff7d03f301304bb23`. The alpha.5 r2 source candidate is separate from the alpha.4 optical/laser runs. Its integrated-source 40-resolution run was cancelled during Reference; the separate 40.81632653-resolution run passed Reference decay and remains active in Device with no full spectrum. The alpha.5 source checkpoint has been merged and hash-audited; no downloadable alpha.5 package or public release is claimed.

## Campaign status

- **11 of 28** routes have a completed native UI calculation or simulation workflow.
- **17** routes remain unexecuted.
- **11** executed routes still have unresolved convergence or comparison questions.
- **5** pre-existing scoped reference agreements remain; Nov. 1 high-field, laser and electrical.iv work adds no new paper-agreement count.

These counts separate UI construction/execution, numerical convergence, and external reference agreement. A calculation completing in the UI is not by itself convergence or physical validation.

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

This is a scoped equation diagnostic for the manually selected homogeneous bar. It does not model carrier continuity, injection, recombination, depletion, contact resistance, nonlinear transport, or a semiconductor diode. The 10/28 route count increases to 11/28, but scoped paper/reference agreements remain five.

**Evidence filenames:** `ELECTRICAL_MANUAL_UI_RECIPES.md`, `analyze_nov1_ohmic_iv.py`, `nov1-ohmic-iv-mesh-comparison.json`, `nov1-ohmic-8-analysis.json`, `nov1-ohmic-16-analysis.json`, `nov1-ohmic-8-ui-export.csv`, `nov1-ohmic-16-ui-export.csv`.

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

The alpha.5 integrated-source `40 cells/µm` run was stopped through the native UI during Reference at displayed `t=269 µm/c`; the log ends at `t=276 µm/c` during cancellation. The Reference decay ratio stayed near `2.129×10⁻⁵` across `t=120–260 µm/c`, above the `10⁻⁷` target. It produced no Device phase or spectrum. A separate integrated-source run at `40.81632653 cells/µm` passed Reference decay at `t=80.017 µm/c` with ratio `5.4877×10⁻⁹` and elapsed phase time `154.07 s`. Its Device phase is still running; no full spectrum or overall convergence result is available. The captured job audit shows this second run differs from the preceding resolution-40 job only in resolution; cell/memory counts are derived values. Its actual represented cell is `2.94 × 2.94 × 4.263 µm`.

### Primary-paper comparison

Altug and Vuckovic, [“Two-dimensional coupled photonic crystal resonator arrays,” Fig. 2 (2004), DOI 10.1063/1.1639505](https://web.stanford.edu/group/nqp/jv_files/papers/hatice1.pdf), supplies approximate `Γ`-point eigenband context. A driven R/T spectrum is a different observable; proximity of a transmission feature to an eigenband coordinate does not identify a mode, prescribe a Fano minimum, or validate `Q`.

### Limits

Both cap-400 phase decay tests failed, and passive-range violations persist. The large differences establish sensitivity to post-source cap but not convergence, mode identity, Fano agreement, or physical correction. The primary Altug–Vuckovic `Γ`-point eigenband is coordinate context, not a driven transmission target. The native UI export audit passes at the stated roundoff tolerance; it does not change scientific status. The read-only analysis utility is `analyze_nov1_meep_cap400.py`.

## Alpha.5 r2 source candidate checkpoint

### Setup and theory

A separate source candidate adds an opt-in integrated-Gaussian source setting and a fractional spatial-resolution field. The fractional control can express 20 grid cells per `0.49 µm` period as `20/0.49 = 40.81632653 cells/µm`; the earlier integer-only value 40 represented a `2.95 µm` cell for a requested `2.94 µm` period. Moving to an aligned `2.94 µm` cell changes both grid and domain representation, so that future comparison is not a pure discretization refinement. The integrated-source setting is opt-in and defaults off; static-field FAQ reasoning motivates a controlled test but does not show that nonzero-frequency spectra are fixed.

### Verification and limits

The cumulative v2 source suite passed 66 tests; the clean staged candidate passed 72 source checks and 34 packaging checks. Build completed in `142.437 s`. All 201 compiled modules match within each executable; the standalone runner matches exactly. Eight frozen critical checks and actual Windows startup passed. Fresh packaged-UI checks confirmed integrated-source default-off/checked behavior, fractional-resolution `40.81632653` persistence through navigation, input preparation, and the immediate Estimate no-data message. A native Stop request cancelled the integrated-source resolution-40 Reference-only run; a separate fresh no-solve candidate chooser closed normally with process exit 0. The source checkpoint is merged and its 10-file payload hashes are verified; no downloadable alpha.5 package or public release is claimed. These UI/source checks remain separate from scientific results.

**Evidence filenames:** `nov1-ui-change-checkpoint.md`, `nov1-fractional-resolution-v2-implementation.json`, `nov1-source-cumulative-v2-hashes.json`, `nov1-source-v2-final-tests.log`, `nov1-private-publication.json`, `manual-packaged-ui.json`.

## Next actions

1. Allow the current alpha.5-r2 integrated-source `40.81632653 cells/µm` Device phase to complete; the Reference passed its decay target, but no Device spectrum is available yet. Keep the cancelled resolution-40 trial separate.
2. Continue the 17 remaining user-authorized routes in queue order, preserving each native entry, execution, convergence and reference scope.
3. Maintain the five scoped reference agreements unless a later route adds independently supported quantitative evidence. Do not convert a completed run, static arithmetic check, or source test into broader physical validation.

**Aggregate evidence filenames:** `nov1-session-report.json`, `nov1-route-queue.json`, `nov1-electrical-iv-native-acceptance-updates.json`, `nov1-meep-native-acceptance-updates.json`, `nov1-private-publication.json`, `nov1-ui-change-checkpoint.md`, `nov1-fractional-resolution-v2-implementation.json`, `nov1-source-cumulative-v2-hashes.json`, `nov1-source-v2-final-tests.log`, `build_qa_report.py`. This aggregate is dated; update it after the active Device phase or another route produces verified evidence.
