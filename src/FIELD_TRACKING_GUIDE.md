# Field-informed machine learning

Run `launch_peak_gui.cmd` on Windows, or `bash launch_peak_gui.sh` after Linux
setup. Restart the source GUI after installing this update.

1. Build the stack in Structure and add wavelength-dependent optical constants in Materials.
2. In **Optimize → Target wavelength**, enter the target (default tolerance ±5 nm),
   minimum Q, hole-size bounds and any lattice/thickness/material-choice bounds.
3. Leave field-guided learning enabled. Optionally sample the selected resonance
   as well as the fixed target; this can add one field solve per evaluated design.
4. Run the search. The ML models learn from confinement, hotspot concentration,
   periodic centroids/spread, field-component fractions, loss distribution,
   energy flow and field-pattern similarity. Saved compatible data is reused.
5. Open **Fields → Compare saved fields** to compare saved designs, browse them with the slider,
   inspect maps/conditions/metrics, and save a comparison to the shared library.

Select a reference and comparison design by their saved run/design labels, then
choose a common finite layer from the dropdown. The slider orders design numbers
numerically. The main table summarizes each layer's overlap, confinement change
and centroid displacement; full descriptors and conditions are in the collapsed
details section. Save/download controls also retain the comparison in
**Saved work → Results library**. See [UI_GUIDE.md](UI_GUIDE.md) for the full interface.

Fixed-target fields and selected-resonance fields have separate learned models.
Field predictions guide which S4 simulation to run next. A recommendation still
requires absorption strictly above 99%, a resolved peak within the wavelength
tolerance, minimum Q, fabrication bounds, and agreement at higher resolution.
The result is the highest verified Q found in the bounded search; field learning
does not establish a continuous global maximum or guarantee faster convergence.

The new CSVs store complex electric and magnetic fields and energy-flow vectors.
`field_features.json` stores portable descriptors, and `target_history.json`
stores observations and the feature-model diagnostics used for each proposal.
`field_training.csv` lists descriptors with design conditions, while
`field_comparisons.csv` records reference-design comparisons. Export the whole
library to share code, optical materials, raw simulations and training history.

Map fractions are sampled integrals of |E|², not dispersive stored energy.
Coarse training grids can miss narrow hotspots; increase field resolution and
inspect finalist maps. Overlap is measured on aligned layer-relative coordinates
and is phase invariant. Selected peaks can change branches; overlap measures
similarity and does not prove they are the same eigenmode. A parameter series
compares steady-state designs rather than showing time propagation.

See [TARGET_DESIGN_GUIDE.md](TARGET_DESIGN_GUIDE.md) for the full sampling,
normalization, compatibility, convergence and Windows/Linux setup details.
