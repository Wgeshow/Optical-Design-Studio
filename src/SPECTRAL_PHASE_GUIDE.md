# Spectral phase

Enable **Measure specular reflection / transmission phase** before running an S4 spectrum. The complete measurements are saved as `phase.csv` beside the power spectrum. Power-only results cannot reconstruct phase. Inspect them in Original Optical Studio's **Phase** view or saved Results → **Specular phase**.

## Display and full cycles

Choose **0–2π**, **−π–π** or **Unwrapped**, then **Radians**, **Phase / π** or **Degrees**. One full cycle is 2π radians = 2 in Phase / π = 360°. The upper plot uses the selected wrapping; the lower plot shows unwrapped change relative to each valid segment's first sample.

Unwrapping uses every saved sample before selecting the bounded graph preview. Decimation does not discard cycle counts. Undefined signals and independent wavelength/angle branches split continuous segments and reset the change reference. Positive half-cycle ties follow NumPy's period-complement convention.

Use sufficiently fine sampling to keep true adjacent phase increments below π (180°). Unwrapping cannot determine how many cycles were missed when the physical phase changes more than π between saved samples. A smooth-looking preview does not establish adequate sampling.

## Measurement and physical reference

The measured quantity is the specular tangential electric field projected onto the incident tangential polarization and normalized to the incident field. It is distinct from total diffracted power. Uniform incident/exit half-spaces and at least one internal layer are required. Coefficient magnitude at or below 1e-10 has undefined phase and remains a gap.

The solver uses the `exp(-iωt)` phasor convention, with forward propagation `exp(+ikz z)` toward the next layer. Raw exterior mode amplitudes are magnetic-field amplitudes; phase measurement converts them to tangential electric fields before normalization. Transmission includes the total outgoing specular field, including the incident-background contribution. It is not the scattered-only coefficient `t - 1`, and its phase cannot be recovered from power transmittance.

For oblique incidence from an absorbing material, S4 defines the real transverse wavevector as `k_parallel = k0 Re(sqrt(ε_incident)) sin(θ)` in the selected azimuthal direction. Phase extraction uses that same wavevector and the outgoing longitudinal square-root branch. This specifies the actual S4 source; it does not assume a complex Snell angle or add lateral attenuation. A correction to this convention affects newly computed absorbing-incidence results; existing saved CSV files are unchanged. Lossless incident media, including the air-incident paper controls, retain the same calculation.

**Absolute · stack boundary planes** displays phase at offset 0 in the incident and exit half-spaces, including propagation through the finite stack between them.

**Relative · physical reference CSV** displays `arg(response_sample / response_reference)`. Select a complete phase CSV with the same wavelength and incidence-angle rows, exactly in acquisition order. Every row is checked before preview selection or converted export. There is no reference interpolation or fitted phase offset. If either signal is undefined, the relative phase is undefined and its continuous segment resets.

The sample and physical reference must share polarization and boundary planes. Retain the physical height of a removed patterned layer in the reference, using its chosen background material, when necessary to preserve those planes. Matching CSV coordinates cannot verify geometry or port definitions automatically. Check a research paper's phase reference, de-embedding and port conventions before interpreting an absolute comparison.

## Exports

**Export complete phase CSV** copies all saved samples in the established six-column degree schema: `wavelength_nm`, `angle_deg`, `reflection_phase_deg`, `transmission_phase_deg`, `reflection_change_deg`, `transmission_change_deg`.

**Export display CSV** retains those original columns and adds full selected-mode/unit columns. When using a physical reference, it also records its filename, SHA256, convention and effective/reference degree columns. Preview limits do not truncate this export, and neither raw input file is modified.

**Export phase figure** uses the current wrapping, units and reference selection. A figure is a selected display; the complete CSV is the authoritative sampling record.
