"""Portable field descriptors and phase-invariant comparison of steady-state designs.

Fractions refer to integrals of electric intensity, not stored optical energy.
Comparisons align layers in fractional cell coordinates and fractional layer depth.
"""
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


def _statistics_arrays(xyz, electric, magnetic, intensity, loss, weights, ax, ay, start, thickness):
    weights = np.asarray(weights, dtype=float)
    weighted = weights*intensity
    volume, total = float(weights.sum()), float(weighted.sum())
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
    chosen = xyz[int(ties[0])]
    uniform = len(ties) == len(xyz)
    hotspot = dict(x_um=float(chosen[0]), y_um=float(chosen[1]), z_um=float(chosen[2]),
                   x_fraction=float(chosen[0]/ax), y_fraction=float(chosen[1]/ay),
                   z_layer_fraction=float((chosen[2]-start)/thickness),
                   tied_samples=int(len(ties)), unique=len(ties) == 1)
    if uniform:
        for name in ('x_um','y_um','z_um','x_fraction','y_fraction','z_layer_fraction'):
            hotspot[name] = None
    component_integrals = np.sum(weights[:, None]*np.abs(electric)**2, axis=0)
    components = {name: float(component_integrals[i]/total) if total > 0 else 0.
                  for i,name in enumerate(('Ex','Ey','Ez'))}
    output = dict(start_um=start, thickness_um=thickness, sample_count=len(xyz),
                  mean_E2=total/volume, max_E2=maximum, integrated_E2_um3=total,
                  mean_loss_proxy=float(np.sum(weights*loss)/volume),
                  integrated_loss_proxy_um3=float(np.sum(weights*loss)),
                  centroid=centroid, centroid_confidence=confidence,
                  circular_moments=moments, spread=spread, hotspot=hotspot,
                  component_fractions=components)
    if magnetic is not None:
        flux = np.sum(weights[:, None]*(.5*np.cross(electric, magnetic.conj()).real), axis=0)/volume
        output['mean_poynting'] = {name: float(flux[i]) for i,name in enumerate(('x','y','z'))}
    return output


def _signature_arrays(xyz, electric, grid, depth_indices, depth_weights, ax, ay):
    """Mean complex E per bounded cell bin; no interpolation across interfaces."""
    count = min(grid, 6)
    ix = np.minimum(grid-1, ((xyz[:, 0]/ax+.5)*grid).astype(np.intp))*count//grid
    iy = np.minimum(grid-1, ((xyz[:, 1]/ay+.5)*grid).astype(np.intp))*count//grid
    bins = (depth_indices*count+ix)*count+iy
    counts = np.bincount(bins, minlength=len(depth_weights)*count*count)
    present = np.flatnonzero(counts)
    values = np.empty((len(present), 6), dtype=float)
    for component in range(3):
        values[:, 2*component] = np.bincount(bins, weights=electric[:, component].real,
                                           minlength=len(counts))[present]/counts[present]
        values[:, 2*component+1] = np.bincount(bins, weights=electric[:, component].imag,
                                             minlength=len(counts))[present]/counts[present]
    weights = np.asarray(depth_weights)[present//(count*count)]*counts[present]/(grid*grid)
    return dict(bin_grid=count, values=values.tolist(), weights=weights.tolist())


def enrich_fields(directory, arrays=None, *, save=True):
    """Recompute v2 descriptors from complete raw data; legacy E-only CSVs are valid.

    Pass field_storage's flat array mapping to avoid any raw-data reread. With
    save=False the caller can attach run diagnostics before saving the result;
    the complete contour artifact is still written in either mode.

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
    if arrays is None:
        from field_storage import load_field_arrays
        arrays = load_field_arrays(directory)
    volume_indices = np.flatnonzero(np.asarray(arrays['plane']) == 0)
    xyz = np.asarray(arrays['xyz'], dtype=float)[volume_indices]
    electric = np.asarray(arrays['E'], dtype=complex)[volume_indices]
    has_h = arrays.get('H') is not None
    magnetic = np.asarray(arrays['H'], dtype=complex)[volume_indices] if has_h else None
    layer_ids = np.asarray(arrays['layer'], dtype=np.intp)[volume_indices]
    material_ids = np.asarray(arrays['material'], dtype=np.intp)[volume_indices]
    layer_names = list(map(str, arrays['layer_names']))
    material_names = list(map(str, arrays['material_names']))
    if xyz.shape != (len(volume_indices), 3) or electric.shape != xyz.shape or (has_h and magnetic.shape != xyz.shape):
        raise ValueError('Invalid field vector array dimensions')
    if not np.isfinite(xyz).all() or not np.isfinite(electric).all() or (has_h and not np.isfinite(magnetic).all()):
        raise ValueError('Field data contains a nonfinite value')
    if np.any(layer_ids < 0) or np.any(layer_ids >= len(layer_names)):
        raise ValueError('Field data contains an unexpected layer')
    if np.any(material_ids < 0) or np.any(material_ids >= len(material_names)):
        raise ValueError('Field data contains an unexpected material')
    known_layers = {name for name, _, _ in layer_list}
    if any(layer_names[i] not in known_layers for i in np.unique(layer_ids)):
        raise ValueError('Field data contains an unexpected layer')
    loss_factors = np.zeros(len(material_names))
    for i in np.unique(material_ids):
        if material_names[i] not in materials:
            raise ValueError('Field data contains an unexpected material')
        loss_factors[i] = max(0., epsilon(materials[material_names[i]], wavelength).imag)
    intensity = np.sum(np.abs(electric)**2, axis=1)
    if not np.isfinite(intensity).all():
        raise ValueError('Nonfinite electric intensity')
    loss = loss_factors[material_ids]*intensity
    statistics, signatures, all_indices, all_weights = {}, {}, [], []
    material_integrals = {name:dict(volume_um3=0.,integrated_E2_um3=0.,integrated_loss_proxy_um3=0.) for name in materials}
    sampling = None
    for name, zstart, thickness in layer_list:
        indices = np.flatnonzero(layer_ids == layer_names.index(name)) if name in layer_names else np.array([], dtype=np.intp)
        if not len(indices):
            raise ValueError('Incomplete field data: missing volume samples for '+name)
        points, fields = xyz[indices], electric[indices]
        xfrac, yfrac = np.round(points[:, 0]/ax, 10), np.round(points[:, 1]/ay, 10)
        zfrac = (points[:, 2]-zstart)/thickness
        xs, xi = np.unique(xfrac, return_inverse=True)
        ys, yi = np.unique(yfrac, return_inverse=True)
        fractions, zi = np.unique(np.round(zfrac, 9), return_inverse=True)
        fractions = fractions.tolist()
        grid = len(xs)
        expected_xy = [(i+.5)/grid-.5 for i in range(grid)]
        if len(ys) != grid or not np.allclose(xs,expected_xy,atol=1e-8,rtol=0) or not np.allclose(ys,expected_xy,atol=1e-8,rtol=0):
            raise ValueError('Unsupported field sampling: expected a full periodic midpoint XY grid')
        depths = cfg.get('depth_samples', 3)
        if len(fractions) != depths:
            raise ValueError('Incomplete field data: unexpected number of depth slices')
        if np.allclose(fractions,[(k+.5)/depths for k in range(depths)],atol=1e-8,rtol=0):
            method = 'midpoint_depth_v2' if depths == 3 else f'midpoint_depth_{depths}_v3'
            depth_weights = [1/depths]*depths
        elif depths == 3 and np.allclose(fractions,[.25,.5,.75],atol=1e-8,rtol=0):
            method, depth_weights = 'legacy_depth_voronoi', [.375,.25,.375]
        else:
            raise ValueError('Unsupported field depth sampling')
        if sampling is not None and sampling != (grid, method):
            raise ValueError('Layer field sampling grids are inconsistent')
        sampling = (grid, method)
        positions = (zi*grid+xi)*grid+yi
        if len(indices) != grid*grid*depths or len(np.unique(positions)) != len(indices):
            raise ValueError('Incomplete field data: missing or duplicate grid points')
        weights = ax*ay*thickness*np.asarray(depth_weights)[zi]/(grid*grid)
        statistics[name] = _statistics_arrays(points, fields, magnetic[indices] if has_h else None,
                                              intensity[indices], loss[indices], weights, ax, ay, zstart, thickness)
        pattern_materials = {p['material'] for p in model['patterns'] if p['layer'] == name}
        pattern_ids = [i for i,n in enumerate(material_names) if n in pattern_materials]
        pattern_integral = float(np.sum((weights*intensity[indices])[np.isin(material_ids[indices], pattern_ids)]))
        statistics[name]['pattern_material_E2_fraction'] = (pattern_integral/statistics[name]['integrated_E2_um3']
                                                           if statistics[name]['integrated_E2_um3'] > 0 else 0.)
        signatures[name] = _signature_arrays(points, fields, grid, zi, depth_weights, ax, ay)
        all_indices.append(indices)
        all_weights.append(weights)
    ordered = np.concatenate(all_indices)
    weights = np.concatenate(all_weights)
    total = _statistics_arrays(xyz[ordered], electric[ordered], magnetic[ordered] if has_h else None,
                              intensity[ordered], loss[ordered], weights, ax, ay, 0., start)
    for key, values in [('volume_um3', weights), ('integrated_E2_um3', weights*intensity[ordered]),
                        ('integrated_loss_proxy_um3', weights*loss[ordered])]:
        sums = np.bincount(material_ids[ordered], weights=values, minlength=len(material_names))
        for i in np.unique(material_ids):
            material_integrals[material_names[i]][key] = float(sums[i])
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
    from contour_sweep import describe_arrays
    contours=describe_arrays(directory, arrays, cfg.get('contour_step', .1))
    descriptor['contour_features']=contours['features']
    descriptor['contour_sampling']=dict(step=contours['step'],grid=contours['grid'])
    extra_path=directory/'airhole_field_metrics.json'
    if extra_path.exists():
        extra=json.loads(extra_path.read_text(encoding='utf-8'))
        if extra.get('schema_version') == 1:
            extra['contour_features']=contours['features']
            descriptor['airhole_views']=extra
    if save:
        write_json(directory/'field_features.json',descriptor,compact=True)
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
    if descriptor.get('airhole_views'):
        from airhole_field_objective import feature_values
        output.update(feature_values(descriptor['airhole_views']))
    output.update(descriptor.get('contour_features', {}))
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
