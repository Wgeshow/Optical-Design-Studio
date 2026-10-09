# Carrier-induced semiconductor index modulation

The carrier dialog accepts absolute electron and hole concentrations (cm^-3) for a reference state and one or more biased states. Choose the optical-data interpretation explicitly: **reference** means the selected library n/k already describe the reference carrier state; **undoped** means library n/k are carrier-free and absolute carrier corrections must be added for both reference and biased states. The readout always reports biased-minus-reference delta_n, including zero at the reference state. Only occurrences in selected layers are changed. Original library data remain unchanged.

Uniform-state CSV columns are `label,electron_cm3,hole_cm3,bias_v`; `label` and `bias_v` are optional. Voltage is metadata supplied by you, not a source from which this optical solver predicts concentrations. Uniform mode applies the same carrier state to selected material occurrences. Depth-profile mode automatically creates S4 slices from user-supplied carrier data as described below.

## Equations and provenance

Implemented: simple free-carrier (Drude) approximation in R. A. Soref and B. R. Bennett, *Electrooptical Effects in Silicon*, IEEE Journal of Quantum Electronics 23(1), 123–129 (1987), DOI [10.1109/JQE.1987.1073206](https://doi.org/10.1109/JQE.1987.1073206). Equations (4) and (5) on printed page 127 (PDF page 5) were inspected directly in the supplied paper. Extinction conversion k = alpha lambda/(4 pi) appears on printed page 123.

Using SI units internally:

```
delta_n = -e² lambda²/(8 pi² c² epsilon0 n_reference)
          * [delta_Ne/me + delta_Nh/mh]
delta_alpha = e³ lambda²/(4 pi² c³ epsilon0 n_reference)
              * [delta_Ne/(me² mu_e) + delta_Nh/(mh² mu_h)]
delta_k = delta_alpha lambda/(4 pi)
```

The silicon conductivity masses are me = 0.26 m0 and mh = 0.39 m0, as given on page 127. GaAs starting masses 0.067 m0 and 0.45 m0 come from the supplied slides, not a claim of identical Ioffe values. Both masses are editable. Custom materials, including AlGaAs, require explicit masses and mobilities; silicon values are not silently reused. Conductivity/optical masses must be used consistently; density-of-states or heavy-hole masses are not automatically interchangeable. Densities in cm^-3 become m^-3 by multiplying by 10^6; mobilities in cm²/(V s) become m²/(V s) by multiplying by 10^-4. Output delta_alpha is converted from m^-1 to cm^-1 by dividing by 100.

Editable mobility defaults 1350 and 480 cm²/(V s) are starting assumptions, not values claimed from this paper and not a doping-dependent mobility model. Enter suitable mobilities for your material and concentration regime. They are held fixed between reference and biased states for this approximation.

## Scientific scope

The supplied paper studies crystalline silicon near room temperature. The 1000–2000 nm software guard follows the spectral region studied in that paper; it does not assert accuracy throughout that range or validate GaAs/custom alloys. Those modes apply the same free-carrier equations using the user-selected material parameters, without adding band-edge, nonparabolicity or heterojunction corrections. Concentrations above 10^20 cm^-3 are rejected. Zero is allowed as an undoped reference; nonzero silicon concentrations below 10^17 cm^-3 carry an explicit extrapolation notice because the paper's carrier-refraction analysis covers 10^17–10^20 cm^-3 (page 128).

The paper's empirical Kramers–Kronig curves are **not** identical to its Drude equations. Page 127 reports theoretical absorption about one quarter of measured values for electrons and one half for holes. Page 128 discusses a nonlinear hole-index response that the simple Drude approximation does not reproduce. This tool labels the approximation and does not present it as an implementation of those empirical curves. No guessed curve digitization or unsupported empirical spectral interpolation is used.

Increased carriers lower n and increase loss in this model; depletion reverses those changes. Depletion cannot create negative k: if this occurs, check whether the chosen reference optical data include the reference free-carrier loss. The solver rejects such a state rather than clipping a physically inconsistent result.

The result is a **material index change**, not automatically a guided-mode effective-index change. It does not solve self-consistent electrostatics, charge transport, voltage-induced carrier accumulation, temperature changes, Kerr effects, or Franz–Keldysh effects. S4 solves the optical response of the supplied carrier-modified material distribution. Basis, depth slicing and wavelength convergence still need checking.

## Depth profiles

Each state's depth CSV requires `layer,z_um,reference_electron_cm3,reference_hole_cm3,electron_cm3,hole_cm3`. Depth is local to the named layer, measured from its top in micrometers; densities are cm^-3. Include both endpoints, z=0 and z=the layer thickness. Every selected layer must be covered exactly, with at least two distinct depth samples. Semi-infinite or zero-thickness layers cannot be profiled. All states must use the same depth grid and reference concentrations, so they share one well-defined baseline.

For each finite layer the program can create equally spaced slices (1–100 per layer, with added boundaries at jumps) or one slice between each pair of distinct profile knots. The default total cap is 1000 slices, explicitly adjustable up to 2000. Uniform sampling also retains the existing 500-slice base limit. Concentrations are interpolated inside each continuous interval and evaluated at slice midpoints. Duplicate depth nodes must be marked `side=left` followed by `side=right`; the two limits remain separate and interpolation never bridges the jump. Every original pattern is copied into each corresponding slice, preserving hole sidewalls, material assignments and total thickness. Only the chosen material changes; other materials in those slices retain their optical properties. The input project and library are not rewritten. Refine depth sampling to check convergence before using results quantitatively.

The plotting axis uses the thickness-weighted average of the slice delta_n values for the selected layer, including unequal knot spacings. This is **not** a field-weighted or modal effective index. The optical spectra use the full sliced structure, not the averaged index. In reference-data mode, library n/k already represent the reference optical material in each slice. In undoped-data mode, the reference carrier profile itself modifies each slice's n/k before the reference spectrum is calculated.

### Four-file COMSOL import

The four-file importer accepts reference electrons, reference holes, biased electrons and biased holes, each with arc length in micrometers and concentration in cm^-3. It maps the supplied stack onto two selected GaAs layers: 0–0.20 µm and 0.22–0.42 µm. The 0.20–0.22 µm spacer remains unchanged. Units are explicit workflow inputs; the concentration units are not inferred from a header that omits them.

Different sampling grids are combined into their union. First and second rows at a duplicate depth represent left and right limits in the directed cut line. The supplied files' jumps at 0.05 and 0.37 µm are preserved (the latter is local depth 0.15 µm in the lower GaAs layer). Coordinates are rounded only to 10^-12 µm to merge floating-point representations of the same mesh point.

Negative densities are rejected by default. The optional numerical-noise cleanup permits explicitly selected absolute tolerances no larger than 10,000 cm^-3; values in that small negative interval become zero, and larger negatives still fail. The import audit saves source paths, SHA-256 hashes, row counts, every clipped raw sample, the tolerance, and the layer mapping. The supplied four files contain 56 values cleaned under the explicit 10,000 cm^-3 tolerance. The imported result has 354 profile rows, including discontinuity limits.

## Abrupt-junction estimate

The calculator implements the slide equations:

```
Vbi = (kB T/q) ln(Na Nd/ni²)
W = sqrt[(2 epsilon_r epsilon0/q)(1/Na + 1/Nd)(Vbi + Vr)]
Wp = W Nd/(Na + Nd); Wn = W Na/(Na + Nd)
```

Dopant and intrinsic concentrations are entered in cm^-3 and converted to SI inside the width expression. Enter material-specific intrinsic concentration and static relative permittivity, plus temperature and nonnegative reverse bias. The assumptions are an abrupt homojunction, complete dopant ionization, depletion approximation and nondegenerate Boltzmann statistics. Densities must exceed intrinsic density; that check alone cannot establish nondegeneracy, so the user must verify it for their semiconductor. The calculation is not a heterojunction, forward-bias, breakdown or self-consistent transport model and does not automatically convert the estimated width into a carrier profile.

## Fixed-wavelength optical response

The carrier sweep runs the reference state first and locates its sampled peak/dip. Every carrier state is then read at that same reference wavelength. The final curve uses delta_n at this wavelength on its horizontal axis, and the selected reflection, transmission or absorption fraction on its vertical axis. Delta_k also varies with carriers, so this is a response along the supplied carrier path, not a pure fixed-loss index perturbation. The readout CSV includes densities, state labels, optional bias labels, delta_n, delta_k, and delta_alpha evaluated at the fixed wavelength. The full-spectrum CSV evaluates these quantities separately at each row's wavelength.

If the reference spectrum has no resolved internal local peak/dip inside the tracking window, the readout explicitly reports no resolved baseline feature; it does not silently choose a boundary or a different wavelength. Wavelength sampling determines the precision of the locked wavelength.

## Developer integration

`validate_configuration(config)` normalizes the carrier data. `evaluate_state(...)` gives delta_n, delta_k and delta_alpha_cm1. `carrier_shifted_model(model, material, layers, state, config)` creates a fresh model with an n/k table evaluated at each exact simulation wavelength; selected layers and patterns use a cloned material. Unselected layers keep their original material. `CarrierIndexDialog.configuration()` returns the serializable configuration (also exposed as `options()`).
