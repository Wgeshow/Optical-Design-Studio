# Optical Design Studio 1.4.0-alpha.4 — Meep progress and runtime estimates

Experimental Windows x64 usability update · 30 October 2026

The Meep Run stage now includes **Estimate runtime**, a live elapsed clock, and progress and estimated remaining time for the current Reference or Device phase. The pre-run button reads matching measured timing records in a background worker; it does not start a solver or hidden calibration run. With no matching record it explains that a run is needed to calibrate. The live estimate appears after enough time-stepping data is available, resets between phases, and becomes unavailable when updates go stale. Stop remains available during a run.

The progress percentage describes the current phase's configured simulation-time budget. It is not an overall completion percentage or a measure of convergence. Runtime estimates may change with machine load; decay may end a phase early. The original alpha.3 cavity-array pilot described below predates these timing controls.

Generated default objects now use neutral names such as **Optical device** and **Circle 1**. The stopping control is labeled **Monitor field decay target**, with wording that distinguishes the sampled squared field from integrated electromagnetic energy. The numerical stopping rule is unchanged.

## Download and validation

Download the Portable Windows x64 `.7z`, extract the complete archive using 7-Zip, and open `Optical Design Studio.exe`. Keep its backend executable and `_internal` directory together. The corresponding Source ZIP is for inspection and rebuilding. Bundled desktop/S4 support needs no separate Python; Meep uses its configured supported Linux/WSL runtime.

See the accompanying `VALIDATION.json` for the exact staged-source hash, source/package/frozen checks, native startup and manual Terra acceptance actually completed on this build. This candidate must pass those gates before publication. The broader full scientific/UI matrix remains incomplete. Stable 1.3.5 and its updater channel are preserved.

The following authored aggregate report distinguishes original simulation evidence from this usability update. No acceptance project, research data, private path, log or paper PDF is included in the public assets.

---

# Meep cavity-array pilot: aggregate progress report

**Date:** 30 October 2026  
**Tested packaged build:** Optical Design Studio 1.4.0-alpha.3  
**Tested source commit:** `57e20ecd313d5e0e55db2407ea0ca05744c935cd`

## Setup

The user selected the published ideal suspended coupled photonic-crystal resonator array (CPCRA) of Altug and Vučković. The manually entered design uses a square silicon slab with refractive index $n=3.5$, hole radius $r=0.4a$, slab thickness $d=0.55a$, and air holes and exterior media. At the analyst-selected scale $a=0.49\,\mu\mathrm m$, the cavity-array primitive period is $A=3a=1.47\,\mu\mathrm m$. A periodically repeated $6a\times6a$ supercell contains four cavity defects; it represents a repeated infinite array, not four isolated cavities.

The user approved removing the factory Device layer and starter circle and deleting the four designated holes. The resulting UI-authored geometry has one $0.2695\,\mu\mathrm m$ slab and 32 air holes of radius $0.196\,\mu\mathrm m$, leaving the four intended missing-hole defects. The visible UI geometry audit passed **16/16 geometry checks** and **14/14 saved-option checks**. An independent check of the actual Meep job snapshot passed **10/10 geometry, material, and option checks**. No structure, project, preset, material file, or curve was imported.

## Theory and derivation

For a linear, isotropic, nonmagnetic slab, the time-domain Maxwell equations are

$$
\frac{\partial\mathbf B}{\partial t}=-\nabla\times\mathbf E,\qquad
\mathbf B=\mu_0\mathbf H,
$$
$$
\frac{\partial\mathbf D}{\partial t}=\nabla\times\mathbf H-\mathbf J,\qquad
\mathbf D=\epsilon_0\epsilon_r(\mathbf r)\mathbf E.
$$

Here $\mathbf E$ is in V/m, $\mathbf H$ in A/m, $\mathbf J$ in A/m$^2$, and $\epsilon_r$ is dimensionless. For the ideal materials, $\epsilon_r=n^2=12.25$ in the slab and 1 in air. In a Yee FDTD discretization, the fields are spatially staggered and electric and magnetic updates are offset by half a time step. For example,

$$
H_x^{n+1/2}=H_x^{n-1/2}-\frac{\Delta t}{\mu_0}
\left[\frac{E_z|_{y+}-E_z|_{y-}}{\Delta y}-
\frac{E_y|_{z+}-E_y|_{z-}}{\Delta z}\right].
$$

The actual circular interfaces are represented on a finite mesh, so agreement of the entered dimensions does not establish resolution convergence.

For the repeated cavities, let $c_{mn}$ be one modal amplitude at lattice site $(m,n)$, with neighboring cavity period $A=3a$. A one-orbital nearest-neighbor illustration allows unequal coupling along the two axes:

$$
\dot c_{mn}=-(i\omega_0+\gamma)c_{mn}
-i\kappa_x(c_{m+1,n}+c_{m-1,n})
-i\kappa_y(c_{m,n+1}+c_{m,n-1})+s_{mn}(t).
$$

Substitute the Bloch form $c_{mn}=c_0e^{i(k_xmA+k_ynA)-i\omega t}$, set the drive $s_{mn}=0$, and combine opposite neighbors using $e^{iq}+e^{-iq}=2\cos q$. This gives

$$
\omega(k_x,k_y)=\omega_0+2\kappa_x\cos(k_xA)+2\kappa_y\cos(k_yA)-i\gamma,
$$
$$
\mathbf v_g=\nabla_{\mathbf k}\operatorname{Re}\omega
=-2A\left[\kappa_x\sin(k_xA)\hat{\mathbf x}
+\kappa_y\sin(k_yA)\hat{\mathbf y}\right].
$$

The rates $\omega_0,\kappa_x,\kappa_y,\gamma$ have units s$^{-1}$; $A\kappa_x$ and $A\kappa_y$ have units m/s. This is a teaching model, not a fit to the paper's multiple dipole, quadrupole, and monopole bands.

The $6a\times6a$ cell is a $2\times2$ repetition of the $3a\times3a$ primitive cavity-array cell. At supercell $\Gamma$, it folds exactly the primitive $\Gamma$, $X_x=(\pi/A,0)$, $X_y=(0,\pi/A)$, and $M=(\pi/A,\pi/A)$ points. A spatially uniform normal-incidence source preserves the primitive translations and probes the bright primitive-$\Gamma$ sector. This fixed in-plane wavevector does not map the full band diagram or group velocity.

## Numerical method

The completed pilot used a three-dimensional cell, periodic boundaries in $x,y$, PML along $z$, normal-incidence $p$-polarized / $E_x$ excitation, 40 cells/µm, Courant factor 0.5, 1 µm PML and air padding, and wavelengths from 1400 to 1800 nm with 401 uniform-frequency output samples. The options also specified a 200 µm/$c$ post-source time cap, a $10^{-7}$ monitored squared-field decay target, dispersion fitting off, and field-map output off. At 40 cells/µm, $\Delta x=25$ nm and the corresponding proposed time step is $\Delta t=0.5\Delta x/c\approx0.0417$ fs. For a three-dimensional isotropic grid with minimum refractive index 1, the usual Courant bound is $S\le1/\sqrt3\approx0.577$; this pilot's $S=0.5$ is below that bound.

The runner performs an empty-geometry reference run and then the device run, subtracting the reference Fourier fields from the device reflected monitor. The reference uses the incident material throughout; for this air/air case it represents both exterior media. Its suitability does not automatically extend to a device with a different exit medium. With signed monitor fluxes, the reported quantities are

$$
R=-\frac{P_{\mathrm{refl,signed}}}{P_{\mathrm{inc}}},\qquad
T=\frac{P_{\mathrm{trans,signed}}}{P_{\mathrm{inc}}},\qquad
A=1-R-T.
$$

Here $A$ is a residual power-balance quantity, not an independently computed absorption. In this lossless model, passive values are expected within [0,1] only when the flux calculation is sufficiently reliable.

The plotted normalized frequency is

$$
\nu=\frac{a}{\lambda}=\frac{0.49\,\mu\mathrm m}{\lambda\;(\mu\mathrm m)}.
$$

Thus the wavelength range maps to $\nu=0.272222$–0.35, and the 401 output points have spacing $\Delta\nu\approx0.000194444$. This is output sampling, not independent spectral resolution. The rough Fourier scale associated with a 200 µm/$c$ time cap is

$$
\Delta\nu_{\mathrm{time}}\sim\frac{a}{cT}=\frac{0.49}{200}\approx0.00245.
$$

It is only an order-of-magnitude estimate; the run stopped at its cap before the requested decay threshold, so this scale is not a claim of achieved resolution. The official [Meep Python API documentation](https://meep.readthedocs.io/en/stable/Python_User_Interface/) defines the Courant factor, field-decay stopping rule, and flux-data subtraction used by the runner.

## Results

The packaged UI run reached terminal status in **1021.1357 s** (about 17 min 1.14 s) and produced 401 finite spectrum rows. The saved summary reports Meep 1.30.0 and **Reference=false, Device=false** for the field-decay checks: both phases reached the post-source time cap without meeting the target. It also warns that the passive power range is exceeded by more than 3% and recommends refining resolution, PML, or runtime. Terminal completion means the job ended; it does not mean convergence.

Across the sampled spectrum:

- $R=0.00227185$ to $1.22603797$
- $T=0.00581409$ to $1.18131285$
- residual $A=-0.95978723$ to $0.51958065$
- 214 of 401 samples have at least one of $R,T,A$ outside [0,1]
- the maximum $|R+T-1|$ is 0.95978723

Although $R+T+A=1$ to about $1.11\times10^{-16}$, that is an algebraic identity because the runner defines $A=1-R-T$; it is not an independent energy-conservation check. The excursions above unity and negative residual values, together with both failed decay flags, make this pilot spectrum unsuitable for physical interpretation or quantitative fitting.

The native UI-exported CSV has the same seven columns in the same order and the same 401 rows as the saved run CSV. Of 2807 parsed numerical cells, 1894 compare exactly as floating-point values. The largest absolute differences are $2.27\times10^{-13}$ nm for wavelength, $2.22\times10^{-16}$ for $R$ and $T$, $9.96\times10^{-17}$ for $A$, and $3.55\times10^{-15}$ for incident flux; frequency and angle values compare exactly. These very small differences are consistent with text serialization and float representation, but that cause is an inference; the values are not described as exactly equal.

Campaign-wide status is **8/28 routes with UI-launched execution** and **5 scoped reference-agreement routes**. Those earlier agreement counts are unchanged. The cavity-array pilot adds an execution, but no new convergence or agreement result.

## Paper comparison

The selected primary reference is Altug and Vučković, “Two-dimensional coupled photonic crystal resonator arrays,” *Applied Physics Letters* 84, 161–163 (2004), [author-hosted paper](https://web.stanford.edu/group/nqp/jv_files/papers/hatice1.pdf). Their Figure 2 is a coupled eigenband plot, not a tabulated normal-incidence transmission curve. A coarse visual read of the primitive-$\Gamma$ $x/y$-dipole branches gives approximately $a/\lambda=0.310$, with analyst-assigned raster-reading uncertainty $\pm0.004$. At $a=490$ nm this is a central wavelength near 1581 nm and an outward-rounded interval about 1560–1602 nm. The paper separately reports a normalized-frequency calculation resolution of 0.0022. Raster-reading uncertainty, paper calculation resolution, CSV sampling interval, and the time-cap estimate are distinct quantities; none is an acceptance tolerance.

For reference only, the pilot has 41 samples in the coarse $\Gamma$-dipole interval $0.306\le\nu\le0.314$; sampled $T$ spans 0.0488–1.0763 and sampled $R$ spans 0.0307–0.9067. The lowest $T$ sample within that interval lies at its upper edge, near $\nu=0.313833$ (1561.34 nm), with $T=0.0488$. This is an interval statistic from an under-decayed, passive-range-violating run. It is not evidence that the sample is an eigenmode, a Fano minimum, or a paper resonance, and it is not an agreement claim. No exact $T$ target, fitted $Q$, or quantitative paper agreement is reported.

## Limits and next steps

One mesh and one capped-time spectrum cannot establish spatial, temporal, PML/padding, or sampling convergence. The next scientific work is to address the incomplete reference decay first, then perform controlled runtime, spatial-resolution, PML/padding, and output-sampling refinements and compare the matched spectra. A normal-incidence scattering run cannot reproduce the complete paper eigenband diagram or determine group velocity.

The scientific pilot described above used [alpha.3](https://github.com/Wgeshow/Optical-Design-Studio/releases/tag/v1.4.0-alpha.3). Alpha.4 adds the runtime controls described at the start of these notes; their separate software and packaged checks are recorded below and in VALIDATION.json. Passing those usability checks does not make the original spectrum converged or establish paper agreement.


## Alpha.4 build verification and timing method

The new candidate passed 42 targeted source tests and 34 packaging/privacy/license tests, with zero failures, errors or skips. Independently compiled code matches 201 staged modules in each executable, and the standalone Meep runner matches the staged bytes. The critical frozen profile passed 8 checks and real Windows startup passed 7 checks. The broader full installer/scientific matrix was not rerun. Fresh manual feature acceptance and final archive checks are recorded separately in VALIDATION.json.

Separate development-snapshot checks passed 48 tests, including six in-process electrical unit tests. These are separate from the 42 tests on the exact packaged candidate and are not substituted for its validation.

For timing, let $\tau$ denote simulated time in units of $\ell_0/c$ with $\ell_0=1\,\mu\mathrm m$, and $w$ wall-clock seconds. The actual source end time $\tau_s$ plus the configured post-source duration $\tau_a$ gives the phase budget $B=\tau_s+\tau_a$. Recent positive time advances give a measured rate

$$r=\frac{\tau_j-\tau_i}{w_j-w_i}.$$

Assuming that short-term rate continues, solve $\tau_j+rE=B$ for estimated remaining wall time:

$$E=\frac{\max(0,B-\tau_j)}{r},\qquad p=\min(1,\tau_j/B).$$

Here $E$ is in seconds and $p$ is the fraction of the current phase's configured time budget. The Reference rate is discarded when Device begins. Initialization and stale or invalid measurements have no ETA. Early field decay can finish a phase before its cap; load and memory pressure can change the measured rate. This is a performance estimate, not a convergence test or a guaranteed deadline.

For an exact matching saved configuration, the cached estimate sums each phase's $I+B/r$, where $I=\max(0,w_1-\tau_1/r)$ estimates initialization, plus observed overhead outside phase timers. Physical inputs, options, application/runtime/machine identity and thread settings must match. Saved timing reads and hashing occur in a background worker; a lightweight GUI timer updates elapsed time. Without a match, the button explains that measured calibration is missing. It never silently runs a solver.

Implementation: [timing calculations](https://github.com/Wgeshow/Optical-Design-Studio/blob/v1.4.0-alpha.4/src/fdtd_progress.py), [native controls and background worker](https://github.com/Wgeshow/Optical-Design-Studio/blob/v1.4.0-alpha.4/src/qt_fdtd.py), and [standalone solver telemetry](https://github.com/Wgeshow/Optical-Design-Studio/blob/v1.4.0-alpha.4/src/meep_runner.py). These additions preserve the configured decay and time-cap stopping rules.
