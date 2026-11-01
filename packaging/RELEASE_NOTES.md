# Optical Design Studio 1.4.0-alpha.14 — Disabled object retention and saved Beam compatibility

Experimental Windows x64 usability update · 1 November 2026

Disabled editable optical objects survive optical material editing. Beam Source-mode guidance explains the existing Transfer inputs workflow. Compatible saved finite fields may be reused when independently authored rows differ only in descriptive IDs or names; physical, numerical, ordering and acceptance guards remain exact.

The candidate passed 247 distinct source checks, 34 package checks and exact comparison of 201 compiled modules per executable plus both standalone workers. Eight actual critical checks, seven Windows startup checks, seven disabled-object observations, readable Beam guidance, completed compatible Beam reuse and physical-change rejection are required. Every inspected process has its own observed normal exit. Actual Beam numerical execution is reported separately from source solver reuse and scientific convergence. Stable v1.3.5 remains unchanged.

The authored snapshot records 27/28 routes. Raw projects, libraries, logs, datasets and paper files are excluded.

---

# Optical Design Studio: 27-route campaign checkpoint

Scientific snapshot: 1 November 2026, 19:47 UTC. **27/28 routes have native UI execution evidence. Five earlier scoped reference agreements remain; zero new paper agreements are credited.** Completion, numerical convergence, model assumptions and paper agreement are separate judgments. All new structures and settings were authored through the visible application UI. The campaign's own automatic sessions were restored normally. No structures, projects, materials, presets or curves were imported.

This update adds actual RCWA pole and Beam execution beyond the [alpha.13 checkpoint](https://github.com/Wgeshow/Optical-Design-Studio/releases/tag/v1.4.0-alpha.13), which remains frozen at 25/28 routes. Earlier validation, equations, failed attempts and executable provenance remain in that release's authored report. Its corresponding source is `42980966b2905486d169e5b7a722b3584a839e49`. Stable v1.3.5 and its updater are unchanged.

## Software changes and validation boundary

Disabled optical objects are retained when the optical material editor synchronizes the active geometry. Their editable identities, coordinates and array metadata survive the round trip; active geometry changes and explicit deletions remain authoritative. The Beam panel now explains the role of a selected saved finite-mode result and the existing input-transfer workflow.

Saved finite-mode compatibility ignores only the top-level descriptive `id` and `name` of each layer or shape row. Row ordering, all physical and numerical fields, unknown fields, nested fields and all 20 compatibility guards remain exact. The actual independently authored Beam input had 77 descriptive-row differences from its compatible source. Its physical guards matched exactly. A valid p-cap thickness change from 220 to 221 nm was rejected for a saved-source layer mismatch; restoring 220 nm enabled the following runs. The prior false rejection remains recorded as failed evidence.

The reviewed candidate passed 247 distinct targeted source tests, 34 package checks, exact comparison of 201 compiled modules per executable and both standalone workers, eight actual frozen critical checks and seven Windows startup checks. These software tests are separate from campaign simulations. Fresh Terra observations cover seven disabled-object scopes and three Beam scopes. A visible 6×6 Pattern array produced 36 editable circles; three were disabled. After adding, assigning and editing a material, all 36 shape records and the 33 active optical patterns remained unchanged apart from the intended slab material assignment. Re-enabling one circle changed only its enabled flag and added one active optical pattern. A fresh process restored the saved session exactly, with 36 total and 34 active circles. The two feature processes and the separate Beam process each had their own observed normal exit code of zero. The full installer matrix and operational Stop behavior were not rerun for this candidate. The final release validation separately records exact archive, source and publication checks.

Independent review caught a release-helper error that confused the private update parent with the public corresponding-source parent. The candidate remained unpublished while the guard was repaired. Six added regression cases using distinct verified receipts exposed three baseline failures; the repaired combined suite passed all 37 helper tests. Complete parent validation now occurs before writing a binding. These are release-orchestration tests, separate from the 247 application source tests and scientific calculations.

Actual Beam calculations used alpha.14 r3: staged source SHA-256 `883ea917d5d34e360a96906b4c89cacc736d80c7356643fd3225e5912bcaaa13`, GUI SHA-256 `d36748a043c26dbf56b710de1ea6fc31f16e30abb02a13489e44a91ed6257859`. The later corresponding-source commit does not relabel earlier scientific runs. RCWA poles used the published alpha.13 source above; King-model vertical, coupled-wave and finite-mode refinements used alpha.8 source `ea6bb3dd0be90e1e9a1fac9f8f43df3a79dde4a5`. Meep controls continue on alpha.5, source `edd15d30e3170980d0cee9502d78141ac6cbd55e`.

## Coverage and outstanding work

| Group | Completed UI execution evidence | Remaining limit |
|---|---|---|
| Optical spectra, fields, index shift and radius sweep | Native construction, runs and selected exports; basis and sampling comparisons recorded | Field/basis resolution, resonance identification and model-specific paper comparisons remain limited |
| Meep cavity array | Completed temporal and 20/a versus 22/a runs; three new resolution/PML/padding controls are active | Earlier spectra are not converged; active runs supply no final spectrum at this snapshot |
| 2D/3D photonic bands, Legume and guided-mode expansion | Native band calculations, scoped prior comparisons and basis studies | Complete Brillouin-zone coverage and the GME mode identity/Q comparison remain unresolved |
| Electrical DC, C–V, I–V and thermal | Native construction and earlier scoped analytic benchmarks | Those diagnostic agreements do not validate every device/material model |
| Periodic, representative-cell and finite-contact transport; coupled optics | Native control cases and output audits | Homogeneous and dielectric null controls are not calibrated active-device validation |
| High-field optics, lumped laser and AI search | Actual native calculations and exports | Normalized optical shape only; no laser transient solve; AI search has zero verified feasible candidates |
| Sesame 1D and 2D | Native sweeps and external comparisons | Reference mismatches and mesh/model limits remain; the separate exponential 2D script adaptation is not yet run |
| PCSEL vertical, coupled-wave and finite cavity | Actual runs and bounded refinements | Source assumptions, mode identity, boundary conditions and complete mode coverage remain unresolved |
| RCWA poles | Four native runs, six accepted rows, four exact exports | Seeds repeat one candidate; no complete mode search or established Fourier convergence |
| Beam | Three native transforms, three exact exports, physical-change rejection | Angular tails, source model and paper-mode identity are unresolved |
| Aperture | Setup/validation inspected; no accepted execution | No matching, justified native electrical-calibration producer/source exists in this campaign |

Eight bounded refinements remain in the active queue at this scientific snapshot: optical spectrum basis 625; index-shift basis 441; driven fields basis 441; diamond path resolution 64; GME cutoff 6.1; index spectral step 0.5 nm if an interior feature is identifiable; diamond reciprocal-grid coverage 8³; and nested driven-field sampling 75×75 at 27 depths. Each changes one specified control from its recorded baseline. Failed or resource-limited attempts must remain failures; lower settings cannot silently substitute. The 2D exponential-generation author-script adaptation is a separate planned case. These queued items are not counted as completed tests here.

## RCWA poles: setup

The manually entered periodic slab has analyst period a=1 µm, thickness 0.5a, circular air holes of radius 0.2a and air above/below. The entered constant index is 3.464101615, giving permittivity 11.9999999990456 rather than exact 12. Normal incidence uses s=1 and p=0.37i. A single probe is at (0.113a,0.179a); an empty field-depth table invokes the documented middle-slab depth 250 nm. It was not an explicitly entered depth. Residue fields use a 16×16 sample plane and detuning δ=10⁻⁸ in normalized frequency.

The first three runs differ only in Fourier basis 49, 81 and 121, starting from u=0.38−0.001i. A fourth basis-121 run uses seeds 0.38−0.001i, 0.378−0.0008i and 0.382−0.0012i. Bounds are Re(u)∈[0.25,0.60] and Im(u)∈[−0.05,−10⁻⁷].

## RCWA poles: theory and numerical method

Let u=af/c=a/λ be dimensionless; a and λ are in metres, f in Hz, c in m/s and angular frequency ω=2πf in rad/s. Near an isolated simple resonance, a driven field channel has a Laurent expansion

`E(u) = r/(u−up) + B(u)`.

Multiplying by u−up shows `(u−up)E → r`; therefore a nonzero coupled channel has `1/E → 0` at up. The implementation chooses the larger-magnitude Ex or Ey channel at the real part of the seed, sets a fixed real scale S=|E| there, and minimizes the two-vector `[Re(S/E(u)), Im(S/E(u))]` by bounded least squares. This is a channel-specific inverse-field search, not a determinant-zero calculation or exhaustive eigenmode search. A dark or weakly coupled mode can be missed.

With time convention `exp(−iωt)`, amplitude magnitude varies as `exp(Im(ω)t)` and energy as `exp(2 Im(ω)t)`. For Im(ω)<0, identify `U=U0 exp(−t/τE)` to obtain `τE=−1/[2 Im(ω)]`. Since Q=Re(ω)τE,

`Q = Re(ω)/[−2 Im(ω)] = Re(u)/[−2 Im(u)]`.

The least-squares tolerances are 10⁻¹², maximum function evaluations 300, and x-scale `[1,max(|Im(useed)|,10⁻⁶)]`. An accepted row requires solver success, Re(u)>0, Im(u)<0 and inverse-field residual below 10⁻⁵. A reported `nfev=6` does not count every underlying optical solver evaluation. Residuals are crosschecked between saved records; the external audit does not independently rerun the root search.

At `up+iδ`, the implementation multiplies sampled fields by the real δ. Relative to the Laurent residue, that introduces a global phase convention. Stored residue amplitude and phase are arbitrary and do not define SI electric field strength, calibrated power or a mode normalization in joules. Flux partition checks use the signed outgoing reflection/transmission convention. A fraction pair that sums to one by construction is not an independent conservation test.

## RCWA poles: actual results and paper comparison

| Basis | Re(u) | Im(u) | Q | Saved inverse-field residual |
|---:|---:|---:|---:|---:|
| 49 | 0.380576688479 | −0.000903991346159 | 210.497971079 | 5.0287×10⁻¹³ |
| 81 | 0.380731564604 | −0.000902767510193 | 210.869110986 | 1.0847×10⁻¹² |
| 121 | 0.381090326076 | −0.000912670679094 | 208.777566107 | 2.4413×10⁻¹² |

All four selected CSV exports exactly match the saved results. The three-seed run repeats the same candidate within 1.89×10⁻¹⁵ in complex u; six accepted rows across four runs are not six distinct modes. Q changes by +0.371139907 then −2.091544880; the last relative change is −0.991869%. Phase-aligned residue E-field relative-L2 changes are about 4.49% and 8.59%. The growing second frequency/field step does not establish an asymptotic convergence sequence. A second detuning changes the up-port fraction by about 7.0–7.3×10⁻⁷, but raw flux and second-detuning fields were not saved for an independent flux reconstruction; this is not a full detuning convergence study.

[Fan and Joannopoulos, Physical Review B 65, 235112 (2002), page 7](https://web.stanford.edu/group/fan/publication/Fan_PRB_65_235112_2002.pdf) gives approximate Q≈213 at radius 0.2a. Taking 213 as the comparison denominator gives `(208.777566107−213)/213 = −1.98236%`. The paper value is approximate; branch identity, discretization error and reference uncertainty remain separate. Numerical proximity is not paper agreement. A real-axis Fano dip is not automatically the real part of a complex pole.

## Beam: setup and physics

The Beam study uses the independently UI-authored 38-layer, 6.376 µm King-model stack and one triangular inclusion, with period 320 nm, triangle base 0.75a, base angle 70° and rotation −45°. Its aperture is 2 mm×2 mm. The saved finite source uses collocation order 20, vertical step 2.5 nm and harmonic truncation 8. The selection −1 chooses the lowest total loss among accepted returned modes: returned mode 0, wavelength 1075.7119695098738 nm and total loss 34.05335137962673 cm⁻¹. This is not proof of a global fundamental or the paper's mode A.

The saved source contains four slowly varying basic-wave amplitudes on a Chebyshev grid. No vertical or cavity eigenproblem is rerun by Beam reuse. Source arrays are unchanged in each output. The three native transforms change only the aperture sampling 128→256 and then zero padding 4→8. All exports were made through the UI.

## Beam: derivation and implemented transform

1. For collocation samples ξj∈[0,1], evaluate the Lagrange interpolants at midpoint samples ti=(i+½)/n. With Tij=Lj(ti), each basic-wave envelope becomes `Wα = T Fα Tᵀ`. Physical coordinates are `xi=(ti−½)Lx`, `yi=(ti−½)Ly`. The source uses SciPy barycentric interpolation. Midpoint grids 128 and 256 are nonnested, so the audit does not subtract unlike near-field coordinates.
2. For the normalized inclusion indicator χ(ρ), evaluate its Fourier coefficients `cq=∫cell χ(ρ) exp(−i2πq·ρ)d²ρ`. The reduced radiating aperture fields are `ex=c(0,−1)W+y+c(0,+1)W−y` and `ey=c(−1,0)W+x+c(+1,0)W−x`. These are a coupled-wave aperture construction, not a full-vector Maxwell surface-integral near-to-far transform.
3. With dx=Lx/n and dy=Ly/n, form `P=Σ(|ex|²+|ey|²)dxdy` and `Ex=ex/√P`, `Ey=ey/√P`. Consequently `Σ(|Ex|²+|Ey|²)dxdy=1`. SI-normalized fields would have units m⁻¹ and intensity density m⁻². Stored coordinates use µm, so stored fields are µm⁻¹ and near intensity µm⁻². This is a unit-power basis, not an electric field in V/m or optical power in watts.
4. Approximate the aperture Fourier integral `F(fx,fy)=∫E(x,y) exp[−i2π(fx x+fy y)]dxdy` by `dx dy FFT(E)` on N=n×padding samples. Coordinates use cycles per unit length, not angular spatial frequency. Set `sx=λfx=sinθx` and `sy=λfy=sinθy`, with λ in the same length unit as dx,dy. Then store `I(sx,sy)=(|Fx|²+|Fy|²)/λ²`.
5. The change of variables gives `dsx dsy=λ² dfx dfy`. Applying discrete Parseval yields `ΣI Δsx Δsy=Σ(|Ex|²+|Ey|²)dxdy≈1`. In the paraxial limit dsx dsy≈dΩ; the stored intensity is labelled sr⁻¹ (paraxial). The implementation has no exact nonparaxial cosine Jacobian or interface extraction correction. Unit normalization and Parseval verify internal consistency, not independent physical conservation.
6. The UI CSV selects the θy=0 cut and reports `θx=(180/π)arcsin(sx)` in degrees. The full propagating domain is `sx²+sy²<1`; every saved sample is within it for these cases. Higher-angle tails outside the saved Nyquist window are untested.

## Beam: results and numerical comparison

| Aperture samples / padding | CSV rows | Parseval sum | Selected x-cut lobe width | Angular-radius RMS |
|---|---:|---:|---:|---:|
| 128 / 4 | 512 | 1.0000000000000413 | 0.03647218284° | 0.04264954088° |
| 256 / 4 | 1,024 | 1.0000000000001443 | 0.03647321384° | 0.05663724148° |
| 256 / 8 | 2,048 | 0.9999999999997311 | 0.03626871558° | 0.05663720760° |

All three exported CSVs are byte-identical to saved output. An independent FFT calculation from the saved complex Ex/Ey reproduces every saved far-field intensity sample exactly. Polarization fractions are approximately one half each. The half-height width is the connected lobe containing the global maximum on the selected cut; it is not a claimed global width for an arbitrary multiple-lobe beam.

For a common sampled domain, use `relative L2=√[Σ(I2−I1)²/ΣI1²]`, `RMS=√[Σ(I2−I1)²/N]`, and weighted absolute integral `Σ|I2−I1| ΔsxΔsy`. Exact angular-frequency bins were paired without intensity interpolation. The 128→256 comparison shares 512² bins and gives relative L2 **4.7659647×10⁻⁵**, maximum absolute change **147.4600 sr⁻¹**, RMS **0.757878 sr⁻¹**, and weighted absolute integral **0.000230775**. The peak itself is about 2.3025×10⁶ sr⁻¹.

Increasing the aperture sampling doubles Nyquist coverage while keeping the angular-bin step fixed. About 0.00020192 of the fine-grid power lies outside the old saved window, substantially affecting the second angular moment. Define `θr=arcsin√(sx²+sy²)` and `θRMS=√[ΣI θr² ΔsxΔsy / ΣI ΔsxΔsy]`. The increase from 0.04265° to 0.05664° therefore remains a tail-resolution warning despite central-intensity stability.

Padding 4→8 halves the angular step without refining the aperture field. Its 1024² common bins give relative L2 **9.4271×10⁻¹⁷** and maximum absolute difference **4.6566×10⁻¹⁰ sr⁻¹**. These are roundoff-scale differences at million-scale peaks, consistent with zero padding. The local half-height width still shifts about 0.56% because its linear interpolation uses denser angular samples. This is sampling sensitivity, not a newly solved electromagnetic field.

The source model is related to [Liang et al., Physical Review B 84, 195119](https://doi.org/10.1103/PhysRevB.84.195119) and the target stack is discussed by [King et al., Optics Express, DOI 10.1364/OE.537452](https://doi.org/10.1364/OE.537452). No branch-matched, independently digitized far-field target with established uncertainty is available for these Beam outputs. Source boundary conditions, nondispersive indices, sparse mode coverage, aperture reduction and paraxial assumptions remain unresolved; **no Beam paper agreement is claimed**.

## Further King-model refinements completed after the earlier snapshot

The vertical scalar TE equation is `−Θ″+β²Θ=k0²n²Θ`, with β=2π/a, k0=2π/λ and zero field at both ends of the finite stack. Replacing Θ″ by `(Θj+1−2Θj+Θj−1)/h²` and substituting uj=njΘj yields a symmetric discrete problem with diagonal `(2/h²+β²)/nj²` and neighboring entry `−1/(h² nj nj+1)`. Here β,k0 have SI units m⁻¹; stored calculations consistently use nm⁻¹. The two boundary conditions are finite Dirichlet conditions, not demonstrated radiative or substrate-confinement conditions.

Changing requested grid 2.5→1.25 nm, and no other input, gives actual fine step 1.2499509900 nm and wavelength **1076.2932485563 nm**, a change of **+0.00440205897 nm**. The fine discrete relative residual is **1.17061×10⁻¹²**. Piecewise-linear interpolation on the union of the two depth grids gives normalized field overlap **0.99999973155** and direct relative-L2 difference **0.0007327365**. This distinguishes interpolation effects, small algebraic residual and grid sensitivity; two grids do not establish continuum error or asymptotic order.

For coupled waves, `C=H+iR` and `C v=Ωv`. In the implemented spatial convention, detuning is Re(Ω) and power loss is `2 Im(Ω)`; multiplying nm⁻¹ values by 10⁷ gives cm⁻¹. Harmonic truncation 8→10→12 changes the four frequency-ranked losses by maximum/RMS **0.544650626/0.385126486 cm⁻¹** and then **0.353530090/0.250084665 cm⁻¹**. The final detuning maximum/RMS change is **1.236912820/0.985357324 cm⁻¹**. These are frequency-ranked differences. CWT eigenvectors were not saved, so branch tracking cannot be inferred from the labels or from unrelated vertical-mode vectors. No reconstruction solve was substituted.

For finite coupled waves the operator is `diag(iDx,−iDx,iDy,−iDy)+C⊗I`, with incoming-edge amplitudes removed and Chebyshev collocation coordinates `(1−cos(jπ/N))/2`. Fields are normalized with Clenshaw–Curtis quadrature. The implemented total loss is `2 Im(Ω)`, radiative loss is the normalized `2∫u†Ru`, and edge loss comes from the outgoing boundary flux divided by the appropriate aperture dimension. Units are converted consistently from nm⁻¹ to cm⁻¹. The dimensionless balance diagnostic is `|gtotal−grad−gedge|/max(|gtotal|, small floor)`; the eigen residual is `||Au−Ωu||/||Au||`. Neither residual bounds the unmodelled physics.

Order 20→24, with all other controls fixed, retains 32 accepted returned modes. The fine maximum balance residual is **2.85725×10⁻¹³** and maximum eigen residual **1.26102×10⁻¹⁴**. Field matching uses normalized overlaps `|∫u*·v|/(||u||||v||)` and direct phase-aligned `||u−exp(−i arg∫u*·v)v||/||u||` on common quadrature. The minimum overlap is **0.9999999999999996**, and maximum direct phase-aligned relative-L2 difference is **5.20955×10⁻¹⁰**. The maximum/RMS total-loss difference is **5.41434×10⁻¹¹/1.15104×10⁻¹¹ cm⁻¹**. A separate quadrature-order check changes overlaps by at most 3.55×10⁻¹⁵. These are stable results for the returned set, not proof of exhaustive spectrum coverage or paper-mode identity. The previously missing order-12 UI export was located and verified exactly; the earlier missing-file observation remains part of the dated history.

The earlier vertical raster values approximately 0.914 and 0.084 lacked reproducible provenance and are withdrawn from current numerical claims. The reproducible Figure 2(a) reanalysis gives intensity-distribution overlap **0.926405**, defined as the integral of the pointwise minimum of the two unit-integral intensity profiles. This differs from the complex-field inner-product overlap above. Profile RMSE is **0.073015 µm⁻¹**, with model/paper peak depths about **2.057526/2.079590 µm** and widths **0.442124/0.462970 µm**. Raster reading, axis calibration and curve extraction contribute reference uncertainty; model and boundary mismatch remain separate. This is not a successful fit or agreement claim.

## Meep and other unresolved comparisons

The cavity array follows the published design family in [Altug and Vučković, Applied Physics Letters (2004)](https://doi.org/10.1063/1.1639505): a periodic 6a×6a supercell with four omitted holes, n=3.5, r/a=0.4 and slab thickness 0.55a. The chosen a=0.49 µm is an analyst scaling. The completed 20/a and 22/a runs passed their monitored reference/device decay thresholds but differ strongly: maximum/RMS reflectance difference **0.9120444/0.07135195** and transmittance **0.9245956/0.0723253**. Absorptance, computed as `A=1−R−T`, has negative values in both cases; this identity is not an independent conservation check. Normalization quality, spatial dispersion, PML and monitor settling remain concerns.

The 24/a run, a separate PML-thickness control and a separate exterior-padding control are active at the snapshot. They have no terminal spectra to compare here. A driven reflectance/transmittance feature is not automatically the paper's Γ-point eigenband, and the analyst-read frequency interval 0.310±0.004 is not an author acceptance tolerance. Final exports and one-factor comparisons are required before any upgrade of status.

The remaining aperture route requires a physically compatible electrical J(V) source, accepted numerical checks, domain/material/contact/temperature provenance and at least two positive increasing anchors. The present native UI edits or imports such records but does not produce and link a justified source. A selected label, geometry hash or manually typed acceptance flag cannot establish calibration. Homogeneous transport controls from other studies cannot be relabelled as the patterned King-stack calibration. This is a real workflow/model dependency, not a passing test.

## Reporting integrity and next actions

A reporting script accidentally replaced the dated-history JSON envelope with one record. The last rendered report and all simulation evidence remained intact. All 24 previously displayed historical entries were recovered and verified by exact equality of their rendered article strings, including limitations, evidence labels and historical release links. Original JSON bytes and non-rendered metadata were not recovered; replacement recovery IDs are identified as such. The first inaccurate reconstruction was not used to regenerate the report.

An append-only history writer now checks the schema and expected preimage hash, prevents duplicate IDs and concurrent helper writes, saves exact preimage backups and replaces the file atomically. Ten synthetic integrity tests passed. The initial test attempt failed during setup/cleanup because the sandbox system temporary directory was unwritable; the corrected harness uses an explicit workspace test directory. No scientific result or public release asset was changed by the recovery.

Continue the bounded UI refinements, separate exponential 2D script case and three active Meep controls. Compare only compatible saved grids and models, retain failed gates and unresolved assumptions, and update the searchable report with equations, measured differences, references and remaining work. Roundoff-level identities, solver completion and small differences in selected outputs must not be relabelled as complete scientific validation.
