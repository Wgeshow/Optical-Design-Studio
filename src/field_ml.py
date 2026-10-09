"""Geometry GPs enriched by predicted field redistribution, with spectral constraints.

Fields describe a learned geometry metric; the acceptance test remains measured
absorptance and resolved Q. The two wavelength modes are never pooled together.
No measured-only covariates are used at spectral training points: the same field
surrogates generate covariates for training points and untried geometries.
"""
import json
import math
import numpy as np

from field_tracking import feature_vector, compare_fields
from ml_optimizer import acquisition, encode, fit_predict, value_key


def _usable_descriptor(descriptor, cfg, mode):
    if not isinstance(descriptor, dict):
        return False
    schema=descriptor.get('schema_version', 0)
    if not isinstance(schema,(int,float)) or schema != 2:
        return False
    if descriptor.get('grid') != cfg['field_grid']:
        return False
    wavelength = descriptor.get('wavelength_nm')
    if not isinstance(wavelength, (int, float)) or not math.isfinite(wavelength):
        return False
    if mode == 'fields':
        return abs(wavelength-cfg['target_nm']) <= 1e-8 and descriptor.get('sampling_mode', 'fixed_target') != 'selected_resonance'
    return (descriptor.get('sampling_mode') == 'selected_resonance'
            and abs(wavelength-cfg['target_nm']) <= cfg['tolerance_nm']+1e-8)


def _field_rows(records, cfg, mode):
    groups = {}
    for record in records:
        if record.get('status') != 'evaluated' or record.get('phase') == 'verification':
            continue
        descriptor = record.get(mode)
        if not _usable_descriptor(descriptor, cfg, mode):
            continue
        try:
            vector = feature_vector(descriptor)
            if not vector or not all(math.isfinite(float(v)) for v in vector.values()):
                continue
            keys = tuple(sorted(vector))
            # Never mix different quadrature definitions or feature schemas.
            sampling = descriptor.get('sampling_method', descriptor.get('sampling', ''))
            group = (keys, json.dumps(sampling, sort_keys=True))
            groups.setdefault(group, {})[value_key(record['values'])] = (record['values'], [vector[k] for k in keys], descriptor)
        except (KeyError, TypeError, ValueError):
            continue
    if not groups:
        return [], []
    key, rows = max(groups.items(), key=lambda item: len(item[1]))
    rows=list(rows.values())[-128:]
    names=list(key[0])
    # A common reference makes overlap a reproducible covariate within each fit;
    # do not train on deltas against a different predecessor for every design.
    overlap_vectors=[]
    overlap_names=[]
    for _,_,descriptor in rows:
        try:
            comparison=compare_fields(descriptor,rows[0][2])
            if not comparison.get('compatible') or comparison.get('field_overlap') is None: break
            vector={'reference_overlap':comparison['field_overlap']}
            for name,item in comparison['layers'].items():
                if item['field_overlap'] is not None: vector['reference_overlap.'+name]=item['field_overlap']
            if overlap_names and sorted(vector)!=overlap_names: break
            overlap_names=sorted(vector)
            overlap_vectors.append([vector[k] for k in overlap_names])
        except (KeyError,ValueError,TypeError): break
    if len(overlap_vectors)==len(rows):
        names+=overlap_names
        return [(values,vector+overlap) for (values,vector,_),overlap in zip(rows,overlap_vectors)],names
    return [(values,vector) for values,vector,_ in rows],names


def field_augmented_candidate(pool, observations, field_records, cfg, explore=False):
    """Return a constrained spectral proposal, or None for geometry-only fallback."""
    successful = [o for o in observations if o.get('status') == 'evaluated' and o.get('phase') != 'verification']
    if not pool or len(successful) < max(3, cfg['initial_designs']):
        return None
    iteration=len(successful)
    # Use the same bounded observation policy as the base acquisition.
    if len(successful) > 256:
        leaders = sorted(range(len(successful)), key=lambda i: successful[i]['targets']['absorption'], reverse=True)[:32]
        leaders += sorted(range(len(successful)), key=lambda i: successful[i]['targets']['feasible_q'] or 0, reverse=True)[:32]
        keep = list(dict.fromkeys(leaders+np.linspace(0, len(successful)-1, 256, dtype=int).tolist()))[:256]
        successful = [successful[i] for i in keep]
    train = np.asarray([encode(o['values'], cfg['dimensions']) for o in successful], dtype=float)
    candidates = np.asarray([encode(v, cfg['dimensions']) for v in pool], dtype=float)
    query = np.concatenate([train, candidates])
    augmented, uncertainty, metadata, alerts = [query], [], [], []
    for mode in ('fields', 'resonance_fields'):
        if mode == 'resonance_fields' and not cfg.get('track_resonance', True):
            continue
        rows, names = _field_rows(field_records+observations, cfg, mode)
        if len(rows) < 4:
            continue
        x = [encode(row[0], cfg['dimensions']) for row in rows]
        values = np.asarray([row[1] for row in rows], dtype=float)
        center, scale = values.mean(axis=0), values.std(axis=0)
        varying = scale > 1e-8*np.maximum(1., np.abs(center))
        if not varying.any():
            continue
        normalized = np.clip((values[:, varying]-center[varying])/scale[varying], -5., 5.)
        _, singular, components = np.linalg.svd(normalized, full_matrices=False)
        count = min(3, len(rows)//4, int(np.sum(singular > 1e-8)))
        scores = normalized @ components[:count].T
        score_scales = np.maximum(scores.std(axis=0), 1e-8)
        predictions, errors = [], []
        for index in range(count):
            mean, std, warnings = fit_predict(x, scores[:, index]/score_scales[index], query, .05)
            if not np.isfinite(mean).all() or not np.isfinite(std).all():
                raise ValueError('Nonfinite field surrogate prediction')
            predictions.append(np.tanh(mean))
            errors.append(np.minimum(std[len(train):], 10.))
            alerts.extend(warnings)
        if not predictions:
            continue
        # Bounded metric contribution prevents a sparse field fit dominating geometry.
        augmented.append(.35/math.sqrt(count)*np.asarray(predictions).T)
        uncertainty.append(np.mean(errors, axis=0))
        metadata.append(dict(mode='fixed_target' if mode == 'fields' else 'selected_resonance',
                             observations=len(rows), components=count,
                             features=[name for name, use in zip(names, varying) if use],
                             variance_fraction=float(np.sum(singular[:count]**2)/np.sum(singular**2))))
    if len(augmented) == 1:
        return None
    features = np.concatenate(augmented, axis=1)
    local_cfg = dict(cfg, _acquisition_iteration=iteration,
                     dimensions=[dict(parameter='field_covariate', values=[0., 1.]) for _ in range(features.shape[1])])
    local_obs = [dict(o, values=list(row)) for o, row in zip(successful, features[:len(train)])]
    index, prediction = acquisition(local_obs, features[len(train):].tolist(), local_cfg)
    if explore:
        # Targeted exploration measures where redistribution predictions are uncertain.
        index = int(np.argmax(np.mean(uncertainty, axis=0)))
        # Spectral diagnostics must describe the chosen candidate, not the prior argmax.
        _, prediction = acquisition(local_obs, [features[len(train)+index].tolist()], local_cfg)
        prediction['selection_reason'] = 'field redistribution uncertainty exploration'
    else:
        prediction['selection_reason'] = 'field-informed '+prediction['selection_reason']
    prediction.update(field_surrogates=metadata,
                      field_uncertainty=float(np.mean(uncertainty, axis=0)[index]),
                      field_model_warnings='; '.join(dict.fromkeys(alerts)),
                      field_method='Predicted field PCA covariates at both training and candidate geometries; measured spectral constraints')
    return pool[index], prediction
