"""Standalone Linux/WSL worker. Requires only Meep + NumPy and a JSON job.

Copied beside each job so the Windows Qt application never imports Meep.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import time


def event(kind, **values):
    print('ODS_MEEP ' + json.dumps(dict(kind=kind, **values), allow_nan=False), flush=True)


def run(job, directory, mp=None):
    if mp is None:
        import meep as mp
    import numpy as np
    directory = Path(directory)
    options = job['options']
    d2 = options['dimensions'] == 2
    direction = mp.Y if d2 else mp.Z
    component = (mp.Ez if d2 else mp.Ey) if options['polarization'] == 's' else mp.Ex
    def v(x=0., y=0., z=0.):
        return mp.Vector3(x, z, 0.) if d2 else mp.Vector3(x, y, z)
    def box_size(x, y, z):
        return mp.Vector3(x, z, mp.inf) if d2 else mp.Vector3(x, y, z)
    def material(record):
        poles = []
        for p in record.get('poles', []):
            if p['frequency'] == 0:
                poles.append(mp.DrudeSusceptibility(frequency=1., gamma=p['gamma'], sigma=p['strength']))
            else:
                poles.append(mp.LorentzianSusceptibility(frequency=p['frequency'], gamma=p['gamma'], sigma=p['strength']/p['frequency']**2))
        return mp.Medium(epsilon=record['epsilon'], E_susceptibilities=poles)
    media = {key: material(value) for key, value in job['materials'].items()}
    total, padding = job['total'], options['padding_um']
    geometry = [mp.Block(size=box_size(mp.inf, mp.inf, (job['size_z']-total)/2),
        center=v(z=(job['size_z']+total)/4), material=media[job['exit']])]
    for region in job['geometry']:
        medium = media[region['material']]
        center = v(region.get('x', 0), region.get('y', 0), region['z'])
        thick = region['thickness']
        shape = region['shape']
        if shape in ('layer', 'slice'):
            geometry.append(mp.Block(size=box_size(region.get('width', mp.inf), mp.inf, thick), center=center, material=medium))
        elif shape == 'circle':
            geometry.append(mp.Cylinder(radius=region['sx'], height=thick, center=center, material=medium))
        elif shape == 'rectangle':
            a = math.radians(region['angle'])
            geometry.append(mp.Block(size=v(region['sx'], region['sy'], thick), center=center, material=medium,
                e1=mp.Vector3(math.cos(a), math.sin(a)), e2=mp.Vector3(-math.sin(a), math.cos(a))))
        else:
            a = math.radians(region['angle'])
            vertices = []
            # Polygonal extrusion, with chord error kept below 0.05 grid cells.
            count = max(96, min(2048, math.ceil(math.pi*math.sqrt(max(region['sx'], region['sy'])*options['resolution']/.025))))
            for i in range(count):
                x, y = region['sx']*math.cos(i*2*math.pi/count), region['sy']*math.sin(i*2*math.pi/count)
                vertices.append(mp.Vector3(x*math.cos(a)-y*math.sin(a), x*math.sin(a)+y*math.cos(a)))
            geometry.append(mp.Prism(vertices, height=thick, center=center, material=medium))
    fcen, df = (job['fmin']+job['fmax'])/2, job['fmax']-job['fmin']
    src_z, refl_z, tran_z = -total/2-padding*.7, -total/2-padding*.35, total/2+padding*.35
    source = mp.Source(mp.GaussianSource(frequency=fcen, fwidth=df, cutoff=5),
        component=component, center=v(z=src_z), size=v(job['ax'], job['ay'], 0))
    common = dict(cell_size=v(job['ax'], job['ay'], job['size_z']), dimensions=options['dimensions'],
        resolution=options['resolution'], Courant=options['courant'],
        boundary_layers=[mp.PML(options['pml_um'], direction=direction)],
        k_point=mp.Vector3(), default_material=media[job['incident']], sources=[source])
    warnings = list(job.get('warnings', []))
    convergence = {}
    def cancelled():
        if (directory/'cancel.flag').exists():
            raise InterruptedError('FDTD calculation cancelled.')
    def execute(sim, phase):
        cancelled()
        event('progress', phase=phase, message=phase + ' run')
        last_event = [0.]
        decay = mp.stop_when_fields_decayed(20, component, v(z=tran_z), options['decay_by'])
        decay_reached = [False]
        def tick(sim):
            cancelled()
            now = time.monotonic()
            if now-last_event[0] > .5:
                last_event[0] = now
                event('progress', phase=phase, time=float(sim.meep_time()), message=f'{phase}: t = {sim.meep_time():.1f} µm/c')
        def stop(sim):
            # Meep calls this only after sources end. The source stop time is
            # provided by the native fields object, avoiding pulse estimates.
            reached = decay(sim)
            decay_reached[0] = bool(reached)
            return reached or sim.meep_time() >= sim.fields.last_source_time()+options['run_after_sources']
        sim.run(mp.at_every(1, tick), until_after_sources=stop)
        convergence[phase] = decay_reached[0]
        if not decay_reached[0]:
            warnings.append(phase + ': maximum post-source runtime reached before the field-decay target. Increase runtime and check convergence.')
    def monitors(sim):
        reflection = sim.add_flux(fcen, df, options['frequency_points'], mp.FluxRegion(center=v(z=refl_z), size=v(job['ax'], job['ay'], 0), direction=direction))
        transmission = sim.add_flux(fcen, df, options['frequency_points'], mp.FluxRegion(center=v(z=tran_z), size=v(job['ax'], job['ay'], 0), direction=direction))
        return reflection, transmission
    reference = mp.Simulation(geometry=[], **common)
    r0, t0 = monitors(reference)
    execute(reference, 'Reference')
    incident = np.asarray(mp.get_fluxes(t0), dtype=float)
    reflected_reference = reference.get_flux_data(r0)
    frequencies = np.asarray(mp.get_flux_freqs(t0), dtype=float)
    reference.reset_meep()
    sim = mp.Simulation(geometry=geometry, **common)
    reflection, transmission = monitors(sim)
    sim.load_minus_flux_data(reflection, reflected_reference)
    fields = None
    field_size = v(job['ax'], 0., total+padding)
    if options['save_fields']:
        fields = sim.add_dft_fields([component], fcen, 0, 1, center=v(), size=field_size)
    execute(sim, 'Device')
    valid = incident > max(float(np.max(abs(incident)))*1e-8, 1e-20)
    if not np.all(valid):
        raise RuntimeError('Reference power is too small at one or more frequencies. Narrow the wavelength band or increase runtime.')
    reflect = -np.asarray(mp.get_fluxes(reflection), dtype=float)/incident
    transmit = np.asarray(mp.get_fluxes(transmission), dtype=float)/incident
    absorb = 1-reflect-transmit
    if not np.all(np.isfinite(reflect+transmit+absorb)):
        raise RuntimeError('Meep produced nonfinite power values. Check grid/material stability.')
    if np.min(absorb) < -.03 or np.max(absorb) > 1.03:
        warnings.append('Power balance lies outside the passive range by more than 3%. Refine resolution/PML/runtime before interpreting this result.')
    with (directory/'results.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['wavelength_nm', 'angle_deg', 'R', 'T', 'A', 'frequency_per_um', 'incident_flux'])
        for i in np.argsort(1000/frequencies):
            writer.writerow([1000/frequencies[i], 0., reflect[i], transmit[i], absorb[i], frequencies[i], incident[i]])
    if fields is not None:
        field = sim.get_dft_array(fields, component, 0)
        x, y, z, _ = sim.get_array_metadata(center=v(), size=field_size)
        np.savez_compressed(directory/'fdtd_fields.npz', field=field, x_um=x,
            depth_um=y if d2 else z, wavelength_nm=1000/fcen,
            component='Ey' if options['polarization']=='s' else 'Ex',
            normalization='Raw Fourier amplitude; not normalized to incident electric field')
    info = dict(engine='Meep', version=str(mp.__version__), dimensions=options['dimensions'],
        grid_cells_estimated=job['estimated_cells'], warnings=warnings, convergence=convergence,
        samples=len(frequencies), status='complete')
    (directory/'fdtd_summary.json').write_text(json.dumps(info, indent=2, allow_nan=False), encoding='utf-8')
    sim.reset_meep()
    event('complete', info=info)
    return info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True)
    args = parser.parse_args()
    path = Path(args.job).resolve()
    try:
        run(json.loads(path.read_text(encoding='utf-8')), path.parent)
    except InterruptedError as exc:
        event('cancelled', message=str(exc))
        return 2
    except Exception as exc:
        import traceback
        (path.parent/'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        event('error', message=str(exc))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
