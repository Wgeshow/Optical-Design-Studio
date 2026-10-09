# Field-informed machine learning

## Native 3D field playback

In the desktop application, open **Fields → 3D field playback**, select a saved
snapshot, and choose **Load 3D fields**. Rotate the view with the mouse. Select
E, H, or time-averaged energy flow, optionally isolate a layer, and use Play or
the phase slider to inspect the saved solution. The plot toolbar saves images.
Older electric-only snapshots support E playback only.

The default **Continuous shape** encloses regions above the **Hide below**
threshold, expressed as a percentage of the complete snapshot's peak. Increasing
the threshold hides weak regions and leaves stronger lobes. The reference peak
does not change when selecting a layer. In E/H mode this filters squared field
magnitude; in Energy flow mode it filters time-averaged power-flow magnitude,
not watts. The status reports the cutoff in S4 units. Choose **Sample points**
to inspect the original samples, or enable **Field arrows** to view oscillation.
Continuous surfaces interpolate each layer separately, close at the sampled
boundaries, and do not add simulated resolution. Shape remains fixed over phase
because its intensity is time independent.

During rotation or arrow playback, the viewer uses a cached lighter surface
to keep interaction responsive. Full surface detail returns after releasing
the mouse or pausing playback. This changes display detail only; field samples,
thresholds and calculations stay unchanged. Arrow playback pauses while dragging
and resumes afterward. Playback is disabled when arrows are hidden, avoiding
redraws of an otherwise stationary intensity shape.

Colors show the phase-independent squared phasor magnitude (or energy-flow
magnitude); arrows show the real field at the selected optical phase. Arrow
scales stay fixed during a cycle. E and H use separate normalized scales.
Energy flow is time averaged and does not animate. All coordinates are in µm;
positive z points into the stack. Outlines show the saved periodic unit cell.

For finer depth sampling, set **Current Structure → 3D depths per layer**
(3–40) before calculating field maps. More depths add sampling cost. Playback
reuses saved complex fields without running S4. The display limits points and
arrows for responsiveness; continuous surfaces use a bounded interpolated grid.
Depth quadrature and compatibility tags distinguish denser samples from the
three-depth training data. This view shows steady-state oscillation; it does
not model pulse propagation or predict fields after changing the geometry.
Use the existing field-guided optimizer to propose candidate designs and
validate finalists with the solver.

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


AI Search includes a **3D electric field** result tab. Select a completed design
and open that tab to load its saved complex field volume. Choose E, Ex, Ey or Ez,
filter layers, rotate the surface, or show sample points. Enable Field arrows
and use Play or the phase slider to inspect the optical cycle. Changing designs
loads that design's measured snapshot and stops playback. Missing snapshots
clear the viewer instead of leaving a previous design visible.

This view uses the campaign's field grid and depths per layer. Surfaces are
interpolated from those samples; increase sampling and verify finalists to
resolve small features. AI Search currently measures fields at its configured
fixed wavelength; the RTA wavelength scan does not supply 3D field volumes at
other wavelengths.
