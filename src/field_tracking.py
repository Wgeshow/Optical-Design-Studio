"""Portable field descriptors and phase-invariant comparison of steady-state designs.

Fractions refer to integrals of electric intensity, not stored optical energy.
Comparisons align layers in fractional cell coordinates and fractional layer depth.
"""
import csv
import math
from pathlib import Path
import json

import numpy as np

from data_library import write_json
from model import epsilon

SCHEMA_VERSION = 2
FIELD_DEFINITION = ('Sampled |E|^2 / incident |E|^2. Fractions are volume-weighted electric-intensity '
                    'fractions, not stored-energy fractions. Loss proxy = max(0,Im(epsilon))*|E|^2, '
                    'not absorptance or dispersive stored energy. Poynting convention: '
                    '0.5*Re(E cross conjugate(H)), in S4 normalized units.')


def _finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Field data contains a nonfinite value')
    return result


def _periodic_delta(a, b):
    return (a-b+.5) % 1. - .5


def _statistics(rows, weights, ax, ay, start, thickness):
    weights = np.asarray(weights, dtype=float)
    intensity = np.array([r['E2'] for r in rows])
    weighted = weights*intensity
    volume, total = float(weights.sum()), float(weighted.sum())
    loss = np.array([r['loss_proxy'] for r in rows])
    xyz = np.array([[r['x_um'], r['y_um'], r['z_um']] for r in rows])
    centroid, confidence, moments, spread = {}, {}, {}, {}
    for axis, period, col in [('x', ax, 0), ('y', ay, 1)]:
        fractions = xyz[:, col]/period
        moment = np.sum(weighted*np.exp(2j*np.pi*fractions))/total if total > 0 else 0j
        resultant = min(1., float(abs(moment)))
        position = float(np.angle(moment)/(2*np.pi)) if resultant > 1e-8 else None
        centroid[axis+'_fraction'] = position
        centroid[axis+'_um'] = None if position is None else position*period
        confidence[axis] = resultant
        moments[axis+'_cos'], moments[axis+'_sin'] = float(moment.real), float(moment.imag)
        spread[axis+'_fraction'] = (float(np.sqrt(np.sum(weighted*((fractions-position+.5)%1-.5)**2)/total))
                                   if position is not None else None)
    zfrac = (xyz[:, 2]-start)/thickness
    zmean = float(np.sum(weighted*zfrac)/total) if total > 0 else None
    centroid['z_layer_fraction'] = zmean
    centroid['z_um'] = None if zmean is None else start+thickness*zmean
    spread['z_layer_fraction'] = (float(np.sqrt(np.sum(weighted*(zfrac-zmean)**2)/total))
                                  if zmean is not None else None)
    maximum = float(intensity.max())
    ties = np.flatnonzero(np.isclose(intensity, maximum, rtol=1e-9, atol=1e-12))
    chosen = rows[int(ties[0])]
    uniform = len(ties) == len(rows)
    hotspot = dict(x_um=chosen['x_um'], y_um=chosen['y_um'], z_um=chosen['z_um'],
                   x_fraction=chosen['x_um']/ax, y_fraction=chosen['y_um']/ay,
                   z_layer_fraction=(chosen['z_um']-start)/thickness,
                   tied_samples=int(len(ties)), unique=len(ties) == 1)
    if uniform:
        for name in ('x_um','y_um','z_um','x_fraction','y_fraction','z_layer_fraction'):
            hotspot[name] = None
    components = {name: float(sum(w*abs(r['E'][i])**2 for w,r in zip(weights,rows))/total)
                  if total > 0 else 0. for i,name in enumerate(('Ex','Ey','Ez'))}
    output = dict(start_um=start, thickness_um=thickness, sample_count=len(rows),
                  mean_E2=total/volume, max_E2=maximum, integrated_E2_um3=total,
                  mean_loss_proxy=float(np.sum(weights*loss)/volume),
                  integrated_loss_proxy_um3=float(np.sum(weights*loss)),
                  centroid=centroid, centroid_confidence=confidence,
                  circular_moments=moments, spread=spread, hotspot=hotspot,
                  component_fractions=components)
    if all(r['H'] is not None for r in rows):
        output['mean_poynting'] = {name: float(sum(w*r['S'][i] for w,r in zip(weights,rows))/volume)
                                  for i,name in enumerate(('x','y','z'))}
    return output


def _signature(rows, grid, depth_fractions, depth_weights, ax, ay, start, thickness):
    """Mean complex E per bounded cell bin; no interpolation across interfaces."""
    count = min(grid, 6)
    bins = {}
    for row in rows:
        ix = min(grid-1, int((row['x_um']/ax+.5)*grid))
        iy = min(grid-1, int((row['y_um']/ay+.5)*grid))
        iz = min(range(len(depth_fractions)), key=lambda k: abs(depth_fractions[k]-(row['z_um']-start)/thickness))
        key = (iz, ix*count//grid, iy*count//grid)
        bins.setdefault(key, []).append(row['E'])
    values, weights = [], []
    for key in sorted(bins):
        samples = bins[key]
        vector = np.mean(np.array(samples), axis=0)
        values.append([float(c) for v in vector for c in (v.real,v.imag)])
        weights.append(float(depth_weights[key[0]]*len(samples)/(grid*grid)))
    return dict(bin_grid=count, values=values, weights=weights)


def enrich_fields(directory):
    """Recompute v2 descriptors from complete raw data; legacy E-only CSVs are valid.

    Original .25/.5/.75 samples use explicit nearest-depth-cell (Voronoi)
    quadrature weights .375/.25/.375. New midpoint samples have equal weights.
    These approximations are tagged and never silently compared to one another.
    """
    directory = Path(directory)
    saved = json.loads((directory/'field_model.json').read_text(encoding='utf-8'))
    model, cfg = saved['model'], saved.get('settings', {})
    wavelength = _finite(saved['wavelength_nm'])
    ax, ay = _finite(model['ax']), _finite(model['ay'])
    if min(ax,ay,wavelength) <= 0:
        raise ValueError('Field lattice and wavelength must be positive')
    materials = {m['name']: m for m in model['materials']}
    layer_list, start = [], 0.
    for layer in model['layers'][1:-1]:
        thickness = _finite(layer['thickness'])
        if thickness > 0:
            layer_list.append((layer['name'],start,thickness))
        start += thickness
    if not layer_list:
        raise ValueError('Field descriptors require finite-thickness layers')
    groups = {name: [] for name,_,_ in layer_list}
    with (directory/'electric_fields.csv').open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        has_h = all(name in reader.fieldnames for name in ('Hx_real','Hx_imag','Hy_real','Hy_imag','Hz_real','Hz_imag'))
        for row in reader:
            if row.get('plane') != 'volume_samples':
                continue
            name = row['layer']
            if name not in groups:
                raise ValueError('Field CSV contains an unexpected layer')
            item = {key: _finite(row[key]) for key in ('x_um','y_um','z_um')}
            item['E'] = [complex(_finite(row[k+'_real']), _finite(row[k+'_imag'])) for k in ('Ex','Ey','Ez')]
            item['H'] = ([complex(_finite(row[k+'_real']), _finite(row[k+'_imag'])) for k in ('Hx','Hy','Hz')]
                         if has_h else None)
            item['S'] = ((.5*np.real(np.cross(item['E'], np.conjugate(item['H'])))).tolist() if has_h else None)
            item['E2'] = float(sum(abs(v)**2 for v in item['E']))
            if not math.isfinite(item['E2']):
                raise ValueError('Nonfinite electric intensity')
            item['material'] = row['material']
            item['loss_proxy'] = max(0.,epsilon(materials[row['material']],wavelength).imag)*item['E2']
            groups[name].append(item)
    statistics, signatures, all_rows, all_weights = {}, {}, [], []
    material_integrals = {name:dict(volume_um3=0.,integrated_E2_um3=0.,integrated_loss_proxy_um3=0.) for name in materials}
    sampling = None
    for name, zstart, thickness in layer_list:
        rows = groups[name]
        if not rows:
            raise ValueError('Incomplete field data: missing volume samples for '+name)
        xs = sorted({round(r['x_um']/ax, 10) for r in rows})
        ys = sorted({round(r['y_um']/ay, 10) for r in rows})
        fractions = sorted({round((r['z_um']-zstart)/thickness, 9) for r in rows})
        grid = len(xs)
        expected_xy = [(i+.5)/grid-.5 for i in range(grid)]
        if len(ys) != grid or not np.allclose(xs,expected_xy,atol=1e-8,rtol=0) or not np.allclose(ys,expected_xy,atol=1e-8,rtol=0):
            raise ValueError('Unsupported field sampling: expected a full periodic midpoint XY grid')
        if len(fractions) != 3:
            raise ValueError('Incomplete field data: expected three depth slices')
        if np.allclose(fractions,[1/6,.5,5/6],atol=1e-8,rtol=0):
            method, depth_weights = 'midpoint_depth_v2', [1/3]*3
        elif np.allclose(fractions,[.25,.5,.75],atol=1e-8,rtol=0):
            method, depth_weights = 'legacy_depth_voronoi', [.375,.25,.375]
        else:
            raise ValueError('Unsupported field depth sampling')
        if sampling is not None and sampling != (grid, method):
            raise ValueError('Layer field sampling grids are inconsistent')
        sampling = (grid, method)
        positions = {(round(r['x_um']/ax,10),round(r['y_um']/ay,10),round((r['z_um']-zstart)/thickness,9)) for r in rows}
        if len(rows) != grid*grid*3 or len(positions) != len(rows):
            raise ValueError('Incomplete field data: missing or duplicate grid points')
        weights = [ax*ay*thickness*depth_weights[min(range(3),key=lambda k:abs(fractions[k]-(r['z_um']-zstart)/thickness))]/(grid*grid) for r in rows]
        statistics[name] = _statistics(rows,weights,ax,ay,zstart,thickness)
        pattern_materials = {p['material'] for p in model['patterns'] if p['layer'] == name}
        pattern_integral = sum(w*r['E2'] for r,w in zip(rows,weights) if r['material'] in pattern_materials)
        statistics[name]['pattern_material_E2_fraction'] = (pattern_integral/statistics[name]['integrated_E2_um3']
                                                           if statistics[name]['integrated_E2_um3'] > 0 else 0.)
        signatures[name] = _signature(rows,grid,fractions,depth_weights,ax,ay,zstart,thickness)
        all_rows.extend(rows)
        all_weights.extend(weights)
        for row, weight in zip(rows,weights):
            item = material_integrals.setdefault(row['material'], dict(volume_um3=0.,integrated_E2_um3=0.,integrated_loss_proxy_um3=0.))
            item['volume_um3'] += weight
            item['integrated_E2_um3'] += weight*row['E2']
            item['integrated_loss_proxy_um3'] += weight*row['loss_proxy']
    total = _statistics(all_rows,all_weights,ax,ay,0.,start)
    for item in list(statistics.values())+list(material_integrals.values()):
        item['E2_fraction'] = item['integrated_E2_um3']/total['integrated_E2_um3'] if total['integrated_E2_um3'] > 0 else 0.
        item['loss_fraction'] = item['integrated_loss_proxy_um3']/total['integrated_loss_proxy_um3'] if total['integrated_loss_proxy_um3'] > 0 else 0.
    pcs = {p['layer'] for p in model['patterns']}
    selected = [v for name,v in statistics.items() if name in pcs] or list(statistics.values())
    selected_thickness = sum(v['thickness_um'] for v in selected)
    descriptor = dict(schema_version=SCHEMA_VERSION,wavelength_nm=wavelength,grid=sampling[0],
                      sampling_method=sampling[1],sampling_mode=cfg.get('sampling_mode','manual'),
                      depth_fractions=fractions, depth_weights=depth_weights,
                      lattice_um=dict(x=ax,y=ay), layer_order=[name for name,_,_ in layer_list],
                      stack_order=[layer['name'] for layer in model['layers']],
                      illumination=dict(polarization=model['polarization'],theta_deg=float(model['points'][0][2]),phi_deg=float(model['phi'])),
                      magnetic_fields_available=has_h,layers=statistics,materials=material_integrals,
                      global_metrics=total, signature=signatures,
                      log_concentration=math.log1p(max(v['max_E2'] for v in selected)),
                      mean_pcs_E2=sum(v['mean_E2']*v['thickness_um'] for v in selected)/selected_thickness,
                      mean_loss_proxy=sum(v['mean_loss_proxy']*v['thickness_um'] for v in selected)/selected_thickness,
                      definition=FIELD_DEFINITION)
    write_json(directory/'field_features.json',descriptor)
    return descriptor


def feature_vector(descriptor):
    """Finite, dimensionless field-only targets; no wavelength, geometry or basis leakage."""
    if descriptor.get('schema_version') != SCHEMA_VERSION:
        return {}
    output = {}
    def add(prefix, item):
        for key in ('mean_E2','max_E2','mean_loss_proxy'):
            output[prefix+'log_'+key] = math.log1p(max(0.,item[key]))
        for key in ('E2_fraction','loss_fraction','pattern_material_E2_fraction'):
            if key in item:
                output[prefix+key] = item[key]
        for group in ('circular_moments','component_fractions'):
            for key, value in item[group].items():
                output[prefix+key] = value
        for group in ('centroid','spread'):
            for key,value in item[group].items():
                if key == 'z_layer_fraction' and value is not None:
                    output[prefix+group+'_z'] = value
        for axis in ('x','y'):
            value = item['spread'][axis+'_fraction']
            output[prefix+'spread_'+axis] = 0. if value is None else value
            output[prefix+'spread_'+axis+'_defined'] = float(value is not None)
        for axis,value in item.get('mean_poynting',{}).items():
            output[prefix+'flux_'+axis] = math.copysign(math.log1p(abs(value)),value)
    add('global.',descriptor['global_metrics'])
    for index,name in enumerate(descriptor['layer_order']):
        add('layer'+str(index)+'.',descriptor['layers'][name])
    for name,item in sorted(descriptor['materials'].items()):
        output['material.'+name+'.E2_fraction'] = item['E2_fraction']
        output['material.'+name+'.loss_fraction'] = item['loss_fraction']
    return {key: float(value) for key,value in output.items() if math.isfinite(value)}


def _overlap(a,b):
    av = np.asarray(a['values'],dtype=float)
    bv = np.asarray(b['values'],dtype=float)
    if av.shape != bv.shape or av.ndim != 2 or av.shape[1] != 6 or not np.allclose(a['weights'],b['weights']):
        raise ValueError('Field signature sampling does not match')
    av, bv = av[:,0::2]+1j*av[:,1::2], bv[:,0::2]+1j*bv[:,1::2]
    weights = np.asarray(a['weights'])[:,None]
    inner = np.sum(weights*np.conjugate(av)*bv)
    norm_a, norm_b = float(np.sum(weights*abs(av)**2)), float(np.sum(weights*abs(bv)**2))
    return inner,norm_a,norm_b


def compare_fields(current_descriptor, reference_descriptor):
    """Layer-relative field overlap; return explicit incompatibility instead of guessing.

    Intensity overlap is squared normalized complex inner product (0..1),
    invariant to one global phase and amplitude. Thickness changes are supported.
    """
    current, reference = current_descriptor, reference_descriptor
    for key in ('schema_version','layer_order','stack_order','illumination','grid','sampling_method','depth_fractions'):
        if current.get(key) != reference.get(key) or current.get(key) is None:
            return dict(compatible=False,reason='Incompatible '+key.replace('_',' '))
    if current['schema_version'] != SCHEMA_VERSION:
        return dict(compatible=False,reason='Upgrade saved raw fields to schema version 2 first')
    layers, inner, na, nb = {},0j,0.,0.
    for name in current['layer_order']:
        try:
            dot, norm_a, norm_b = _overlap(current['signature'][name],reference['signature'][name])
        except (KeyError,ValueError,TypeError):
            return dict(compatible=False,reason='Incompatible field signature sampling')
        inner += dot
        na += norm_a
        nb += norm_b
        a,b = current['layers'][name],reference['layers'][name]
        shifts,physical = {},{}
        for axis,key in [('x','x_fraction'),('y','y_fraction'),('z','z_layer_fraction')]:
            ac,bc = a['centroid'][key],b['centroid'][key]
            shifts[axis] = None if ac is None or bc is None else (_periodic_delta(ac,bc) if axis != 'z' else ac-bc)
            if axis == 'z':
                physical[axis] = None if shifts[axis] is None else a['centroid']['z_um']-b['centroid']['z_um']
            else:
                same_period = math.isclose(current['lattice_um'][axis],reference['lattice_um'][axis],rel_tol=1e-10)
                physical[axis] = shifts[axis]*current['lattice_um'][axis] if shifts[axis] is not None and same_period else None
        layers[name] = dict(field_overlap=min(1.,float(abs(dot)**2/(norm_a*norm_b))) if norm_a*norm_b > 0 else None,
                            centroid_shift_fraction=shifts,centroid_displacement_um=physical,
                            E2_fraction_change=a['E2_fraction']-b['E2_fraction'],
                            mean_E2_ratio=a['mean_E2']/b['mean_E2'] if b['mean_E2'] > 0 else None)
    return dict(compatible=True,field_overlap=min(1.,float(abs(inner)**2/(na*nb))) if na*nb > 0 else None,
                wavelength_shift_nm=current['wavelength_nm']-reference['wavelength_nm'],
                sampling_mode_changed=current.get('sampling_mode') != reference.get('sampling_mode'),
                layers=layers,definition='Squared normalized complex E overlap, phase invariant; equal layer weights on fractional cell/depth coordinates. No time evolution is implied.')
