"""Standalone fixed worker copied into each optional-engine result directory."""
from pathlib import Path
import json
import os
import sys

os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['MPLBACKEND'] = 'Agg'


def event(progress, message):
    print('ODS_EVENT '+json.dumps(dict(phase='research_physics', progress=progress, message=message)), flush=True)


def legume_pwe(cfg, directory):
    import numpy as np
    import legume
    lattice_rows = np.asarray(cfg['lattice_vectors'])[:2, :2]
    lattice = legume.Lattice(lattice_rows[0], lattice_rows[1])
    layer = legume.ShapesLayer(lattice, eps_b=cfg['background_epsilon'])
    for obj in cfg['geometry']:
        center = np.asarray(obj['center'][:2])
        if obj['shape'] == 'circle':
            shape = legume.Circle(eps=obj['epsilon'], x_cent=center[0], y_cent=center[1], r=obj['radius'])
        elif obj['shape'] == 'block':
            axes = np.asarray(obj['axes'])[:2, :2]
            axes /= np.linalg.norm(axes, axis=1)[:, None]
            half = np.asarray(obj['size'][:2])/2
            vertices = np.array([[-1., -1.], [1., -1.], [1., 1.], [-1., 1.]])*half
            vertices = center+vertices@axes
            shape = legume.Poly(eps=obj['epsilon'], x_edges=vertices[:, 0], y_edges=vertices[:, 1])
        else:
            raise ValueError('Unsupported Legume PWE primitive')
        layer.add_shape(shape)
    points = np.asarray(cfg['k_points'])
    reciprocal = np.linalg.inv(lattice_rows).T
    kpoints = 2*np.pi*(points[:, :2]@reciprocal).T
    arrays = dict(k_fractional=points)
    pwe = legume.PlaneWaveExp(layer, gmax=cfg['gmax'])
    for index, pol in enumerate(cfg['polarizations']):
        event(index/len(cfg['polarizations']), 'Solving Legume '+pol.upper()+' bands')
        pwe.run(kpoints=kpoints, pol=pol, numeig=cfg['num_bands'])
        frequencies = np.asarray(pwe.freqs, float)
        if frequencies.shape != (len(points), cfg['num_bands']) or not np.isfinite(frequencies).all() or np.any(frequencies < -1e-10):
            raise RuntimeError('Legume returned incomplete or nonphysical band frequencies')
        arrays['frequencies_'+pol] = frequencies
    np.savez_compressed(directory/'engine_bands.npz', **arrays)
    return dict(status='complete', solver='legume', engine_version=str(getattr(legume, '__version__', 'unreported')),
                plane_waves=int(pwe.gvec.shape[1]), output_npz='engine_bands.npz')


def sampled_region_generation(region, x_um):
    """Prescribed exponential source at absolute device coordinates, in cm^-3 s^-1."""
    import numpy as np
    profile = region['generation_profile']
    x_um = np.asarray(x_um, dtype=float)
    # Validated origin <= region start: exponents cannot be positive. Large
    # attenuation may safely underflow to zero, including in a dark region.
    if region['generation_cm3_s'] == 0 or profile['absorption_cm1'] == 0:
        return np.full_like(x_um, region['generation_cm3_s'])
    with np.errstate(over='ignore', under='ignore'):
        attenuation = profile['absorption_cm1'] * ((x_um-profile['origin_um'])*1e-4)
        return region['generation_cm3_s'] * np.exp(-attenuation)


def sesame_transport(cfg, directory):
    import logging
    import numpy as np
    import sesame
    from sesame.solvers import Solver
    from sesame.observables import get_n, get_p, get_jn, get_jp, get_bulk_rr
    logging.getLogger().setLevel(logging.WARNING)
    x = np.asarray(cfg['x_nodes_um'])*1e-4
    y = np.asarray(cfg['y_nodes_um'])*1e-4 if cfg['dimension'] == 2 else np.array([0.])
    system = sesame.Builder(x, y, input_length='cm', T=cfg['temperature_K'], periodic=cfg['periodic_y'])
    xx, yy = np.meshgrid(x*1e4, y*1e4)
    labels = np.full(xx.shape, -1, dtype=int)
    # Use the original submitted node values to avoid unit roundoff at interfaces.
    xx, yy = np.meshgrid(cfg['x_nodes_um'], cfg['y_nodes_um'] or [0.])
    for index, region in enumerate(cfg['regions']):
        selected = (xx >= region['x_range_um'][0]) & (xx <= region['x_range_um'][1])
        if cfg['dimension'] == 2:
            selected &= (yy >= region['y_range_um'][0]) & (yy <= region['y_range_um'][1])
        labels[selected] = index
    labels = labels.ravel()
    for index, region in enumerate(cfg['regions']):
        selected = labels == index
        location = lambda position, selected=selected: selected
        system.add_material(cfg['materials'][region['material']], location)
        system.add_donor(region['donors_cm3'], location)
        system.add_acceptor(region['acceptors_cm3'], location)
        if 'generation_profile' in region:
            system.g[selected] = sampled_region_generation(region, xx.ravel()[selected])/system.scaling.generation
        else:
            system.g[selected] = region['generation_cm3_s']/system.scaling.generation
    left, right = cfg['contacts']['left'], cfg['contacts']['right']
    system.contact_type(left['kind'], right['kind'], left.get('work_function_eV'), right.get('work_function_eV'))
    system.contact_S(left['electron_velocity_cm_s'], left['hole_velocity_cm_s'], right['electron_velocity_cm_s'], right['hole_velocity_cm_s'])
    for defect in cfg['defects']:
        location = (np.asarray(defect['location_um'])*1e-4).tolist() if cfg['dimension'] == 2 else float(defect['location_um'])*1e-4
        system.add_defects(location, defect['density_cm2'], defect['sigma_e_cm2'], defect['sigma_h_cm2'],
                           E=defect['energy_eV'], transition=tuple(defect['transition']))
    solver = Solver()
    # Charge-neutral initial guess avoids the engine's log(0) for intrinsic contacts.
    rho, ni = system.rho, system.ni
    root = np.sqrt(rho*rho+4*ni*ni)
    electron = np.where(rho >= 0, (rho+root)/2, 2*ni*ni/np.maximum(root-rho, np.finfo(float).tiny))
    potential = np.log(electron/system.Nc)-system.bl
    if left['kind'] == 'Schottky':
        potential[np.arange(system.ny)*system.nx] = -left['work_function_eV']/system.scaling.energy
    if right['kind'] == 'Schottky':
        potential[system.nx-1+np.arange(system.ny)*system.nx] = -right['work_function_eV']/system.scaling.energy
    event(0., 'Solving semiconductor equilibrium')
    options = dict(tol=cfg['tolerance'], maxiter=cfg['max_iterations'], periodic_bcs=cfg['periodic_y'], verbose=False)
    state = solver.solve(system, compute='Poisson', guess={'v': potential}, **options)
    rows, state_files = [], []
    maximum_n_over_Nc, maximum_p_over_Nv = 0., 0.
    header = 'voltage_V,diode_current_A_cm2,Jx_mean_A_cm2,Jx_min_A_cm2,Jx_max_A_cm2,current_spread_A_cm2'
    np.savetxt(directory/'transport_iv.csv', np.empty((0, 6)), delimiter=',', header=header, comments='')
    if state is None:
        return dict(status='unconverged', reason='Equilibrium Poisson solve did not converge', completed_bias_points=0,
                    requested_bias_points=len(cfg['voltages_V']), state_files=[])
    boundary_sites = system.nx-1+np.arange(system.ny)*system.nx
    all_sites = np.arange(system.nx*system.ny)
    section_sites = (np.arange(system.nx-1)[None, :]+np.arange(system.ny)[:, None]*system.nx).ravel()
    edge_dx = np.tile(system.dx, system.ny)
    scales = system.scaling
    reason = None
    for index, voltage in enumerate(cfg['voltages_V']):
        event(index/len(cfg['voltages_V']), 'Solving right-contact bias '+str(voltage)+' V')
        state['v'][boundary_sites] = solver.equilibrium[boundary_sites]+voltage/scales.energy
        state = solver.solve(system, guess=state, **options)
        if state is None or any(not np.isfinite(state[key]).all() for key in ('v', 'efn', 'efp')):
            reason = 'Drift-diffusion did not converge at right-contact bias '+str(voltage)+' V'
            break
        n = get_n(system, state['efn'], state['v'], all_sites)
        p = get_p(system, state['efp'], state['v'], all_sites)
        jn = get_jn(system, state['efn'], state['v'], section_sites, section_sites+1, edge_dx).reshape(system.ny, system.nx-1)*scales.current
        jp = get_jp(system, state['efp'], state['v'], section_sites, section_sites+1, edge_dx).reshape(system.ny, system.nx-1)*scales.current
        if system.ny == 1:
            sections = (jn+jp)[0]
        elif cfg['periodic_y']:
            weights = (system.dy+np.roll(system.dy, 1))/2
            sections = np.sum((jn+jp)*weights[:, None], axis=0)/np.sum(weights)
        else:
            sections = np.trapz(jn+jp, y, axis=0)/(y[-1]-y[0])
        if not np.isfinite(sections).all() or not np.isfinite(n).all() or not np.isfinite(p).all():
            reason = 'Nonfinite carrier or current output at right-contact bias '+str(voltage)+' V'
            break
        maximum_n_over_Nc = max(maximum_n_over_Nc, float(np.max(n/system.Nc)))
        maximum_p_over_Nv = max(maximum_p_over_Nv, float(np.max(p/system.Nv)))
        rows.append([voltage, -float(np.mean(sections)), float(np.mean(sections)), float(np.min(sections)), float(np.max(sections)), float(np.ptp(sections))])
        filename = 'transport_state_'+str(index).zfill(4)+'.npz'
        np.savez_compressed(directory/filename, x_um=x*1e4, y_um=y*1e4, voltage_V=voltage,
            potential_V=state['v'].reshape(system.ny, system.nx)*scales.energy,
            electron_quasi_fermi_eV=state['efn'].reshape(system.ny, system.nx)*scales.energy,
            hole_quasi_fermi_eV=state['efp'].reshape(system.ny, system.nx)*scales.energy,
            conduction_band_eV=-(state['v']+system.bl).reshape(system.ny, system.nx)*scales.energy,
            valence_band_eV=-(state['v']+system.bl+system.Eg).reshape(system.ny, system.nx)*scales.energy,
            electrons_cm3=n.reshape(system.ny, system.nx)*scales.density,
            holes_cm3=p.reshape(system.ny, system.nx)*scales.density,
            bulk_recombination_cm3_s=get_bulk_rr(system, n, p).reshape(system.ny, system.nx)*scales.generation,
            generation_cm3_s=system.g.reshape(system.ny, system.nx)*scales.generation,
            region_index=labels.reshape(system.ny, system.nx),
            electron_Jx_A_cm2=jn, hole_Jx_A_cm2=jp, section_Jx_A_cm2=sections)
        state_files.append(filename)
        np.savetxt(directory/'transport_iv.csv', rows, delimiter=',', header=header, comments='')
    validity_limits = []
    if max(maximum_n_over_Nc, maximum_p_over_Nv) >= 1.:
        validity_limits.append('Carrier density reaches or exceeds its effective density of states; Boltzmann statistics are outside their nondegenerate regime.')
    return dict(status=('partial' if rows else 'unconverged') if reason else ('validity_limit' if validity_limits else 'complete'), reason=reason,
        solver='sesame', engine_version=str(getattr(sesame, '__version__', 'unreported')),
        dimension=cfg['dimension'], shape=[system.ny, system.nx], completed_bias_points=len(rows),
        requested_bias_points=len(cfg['voltages_V']), state_files=state_files,
        maximum_current_spread_A_cm2=max((row[-1] for row in rows), default=None),
        maximum_n_over_Nc=maximum_n_over_Nc, maximum_p_over_Nv=maximum_p_over_Nv, validity_limits=validity_limits,
        periodic_y=cfg['periodic_y'], y_period_um=float(sum(system.dy)*scales.length*1e4) if cfg['periodic_y'] else None,
        bias_convention='Positive voltage increases right-contact electrostatic potential; no doping-dependent sign flip.',
        convergence_test='Sesame Newton update tolerance; section-current spread reported independently')


def main():
    inputs = Path(sys.argv[1]).resolve()
    cfg = json.loads(inputs.read_text(encoding='utf-8'))
    sys.path[:0] = list(cfg['runtime'].get('module_paths', []))
    handlers = {'legume_pwe': legume_pwe, 'sesame_transport': sesame_transport}
    engine = cfg.get('worker_engine')
    if engine not in handlers:
        raise ValueError('Unsupported application physics worker')
    result = handlers[engine](cfg, inputs.parent)
    (inputs.parent/'engine_result.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    event(1., 'Optional physics engine completed')


if __name__ == '__main__':
    main()
