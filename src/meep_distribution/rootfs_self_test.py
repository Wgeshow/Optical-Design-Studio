"""Required real-solver image build gate: air and Fresnel-interface R/T."""
import json
import pathlib
import meep as mp
import numpy as np


def simulate(substrate_index):
    common = dict(cell_size=mp.Vector3(1, 8), resolution=30,
        boundary_layers=[mp.PML(1, direction=mp.Y)], k_point=mp.Vector3(),
        sources=[mp.Source(mp.GaussianSource(.7, fwidth=.25), component=mp.Ez,
            center=mp.Vector3(0, -2), size=mp.Vector3(1, 0))])
    def monitor(sim, y):
        return sim.add_flux(.7, .2, 11, mp.FluxRegion(center=mp.Vector3(0, y), size=mp.Vector3(1, 0), direction=mp.Y))
    reference = mp.Simulation(**common)
    r0, t0 = monitor(reference, -1), monitor(reference, 2)
    reference.run(until_after_sources=100)
    incident, data = np.array(mp.get_fluxes(t0)), reference.get_flux_data(r0)
    reference.reset_meep()
    sim = mp.Simulation(geometry=[mp.Block(size=mp.Vector3(mp.inf, 4, mp.inf),
        center=mp.Vector3(0, 2), material=mp.Medium(index=substrate_index))], **common)
    reflection, transmission = monitor(sim, -1), monitor(sim, 2)
    sim.load_minus_flux_data(reflection, data)
    sim.run(until_after_sources=100)
    r, t = -np.array(mp.get_fluxes(reflection))/incident, np.array(mp.get_fluxes(transmission))/incident
    expected_r = ((1-substrate_index)/(1+substrate_index))**2
    assert np.max(abs(r-expected_r)) < .03, (r, expected_r)
    assert np.max(abs(t-(1-expected_r))) < .03, (t, expected_r)
    assert np.max(abs(1-r-t)) < .03, (r, t)
    sim.reset_meep()
    return dict(index=substrate_index, expected_r=expected_r,
        max_reflection_error=float(np.max(abs(r-expected_r))), max_power_error=float(np.max(abs(1-r-t))))


report = dict(meep_version=mp.__version__, passed=True, checks=[simulate(1.), simulate(1.5)])
pathlib.Path('/opt/ods-build/self-test.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
