# Layer-selective index sweeps and linked air holes

## Δn sweep

Open **Simulation → Δn sweep · S4**. Choose a material already in the Structure,
then check the layers where that material should change. Both the background and
patterned regions using that material in a checked layer receive the shift.
Occurrences in other layers and the material library remain unchanged.

Set the wavelength range and incident light on **S4 · RCWA**. Δn sweeps require
wavelength mode and at least three wavelength samples. Solver basis and CPU/GPU
settings are shared. Optical tables must cover the entire wavelength range.

- **Equal shift across selected layers**: each case applies the same Δn to every
  selected layer. Choose shared start, stop and sample count.
- **Unchecked**: edit each selected layer's start, stop and sample count in the
  table. Every combination is simulated. The count is shown before running.
- **One fixed offset**: use equal start/stop and one sample.

A zero-shift baseline is always included, at most once. Sweeps are limited to
200 requested combinations (plus baseline) and 200,000 wavelength samples.
The material is cloned privately for each shifted layer. For dispersive tables,
Δn is added to every tabulated n value while k stays fixed. Constant-permittivity
materials are converted to the principal complex refractive index before the
shift; this is a real-index perturbation, not an additive permittivity change.

Spectra retain R, T and A for every case in `index_shift_spectra.csv`. Select a
response, peak/dip, reference wavelength and search radius for the nearest sampled
local feature. The baseline feature is the tracking reference for later cases.
Features at spectrum endpoints are excluded; absent features remain blank.
`index_shift_features.csv` records wavelengths and shifts. Equal sweeps additionally
report the finite difference Δλ/Δn in nm/RIU. Independent sweeps do not claim a
single sensitivity for multiple independently changed layers.

### Fixed-wavelength power readout (default plot)

The Δn=0 peak/dip supplies a single locked wavelength λ₀. Every shifted case is
then measured at that same wavelength, even if its resonance moves elsewhere.
For example, a zero-shift peak at 1550 nm produces a plot of R(1550 nm, Δn),
T(1550 nm, Δn), or A(1550 nm, Δn), with Δn on the horizontal axis.

Use **Plot → Fixed-wavelength response** for the measured fraction, **Change from
baseline** for its signed difference from the Δn=0 value, or **Overlaid spectra**
for the full spectra with a vertical line at λ₀. The locked wavelength and
baseline value are shown above the plot. These are power fractions, not watts.

`index_shift_readout.csv` includes the fixed wavelength, selected response,
baseline value, difference, and all R/T/A values and differences for each case.
The data uses the exact baseline wavelength sample already simulated in every
case. An unresolved baseline peak/dip leaves the readout unavailable rather than
inventing a value. Older saved runs can also display this view from their spectra.

For independent multi-layer sweeps, choose the layer on the **Δn axis**. Each
curve holds the other selected layers' offsets fixed, as stated in the legend.

Tracking does not establish electromagnetic mode identity, convergence, or a
sub-sample peak location. Refine wavelength spacing and Fourier basis for final
sensor results. Curves that cross or split require inspection. The UI displays
at most 24 curves; every curve is available in CSV. Saved project files preserve
the controls, and **Load saved Δn result** restores plots and tables from a run.

## Equal air-hole radius through multiple layers

Open **Optimization → Explore designs** and enable **Link radii across layers**.
Check the circular air regions forming the hole. They must already exist in
Structure, and the air material must be constant n=1, k=0 (or ε=1).

Set the radius range in nm or µm. This creates one shared optimization dimension,
not one variable per layer: 0.1 nm means radius 0.0001 µm in every checked region.
Both exhaustive grid and ML/Hybrid candidates use this constraint. Shared controls
replace individual radius/radius-ratio/size-X bounds for the selected regions.
Other bounds still apply. Material changes on the selected air holes are rejected.

Centers stay as specified in Structure. For a straight etched hole through a
stack, align its center across those layers. The option equalizes radii; it does
not silently reposition holes or create missing regions. With multiple holes,
check only the ones that should share this radius. Disabled linking retains the
ordinary independent parameter bounds.
