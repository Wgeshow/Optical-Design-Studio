"""Lossless full-field arrays with legacy CSV import and explicit CSV export.

Every sample retains all three complex128 E and H components. Integer labels
refer to small name tables, so geometry strings are not repeated per voxel.
Uncompressed NPZ avoids a compression bottleneck and needs no optional runtime.
"""
from pathlib import Path

import numpy as np
from direct_npz import DirectNPZWriter

PLANE_NAMES = ('volume_samples', 'xy', 'xz')
ARRAY_FILENAME = 'electric_fields.npz'
CSV_FILENAME = 'electric_fields.csv'
SCHEMA_VERSION = 1
HEADERS = ['plane', 'layer', 'x_um', 'y_um', 'z_um',
           'Ex_real', 'Ex_imag', 'Ey_real', 'Ey_imag', 'Ez_real', 'Ez_imag', 'E2', 'material',
           'Hx_real', 'Hx_imag', 'Hy_real', 'Hy_imag', 'Hz_real', 'Hz_imag', 'Sx', 'Sy', 'Sz']


def field_data_path(directory):
    directory = Path(directory)
    binary = directory / ARRAY_FILENAME
    return binary if binary.is_file() else directory / CSV_FILENAME


def field_data_exists(directory):
    return field_data_path(directory).is_file()


def validate_field_arrays(arrays):
    """Validate untrusted persisted arrays before indexing or numerical use."""
    data = dict(arrays)
    for name in ('xyz', 'E'):
        value = np.asarray(data[name])
        kinds = 'f' if name == 'xyz' else 'fc'
        if value.ndim != 2 or value.shape[1] != 3 or value.dtype.kind not in kinds:
            raise ValueError(f'Invalid field {name} array')
        if not np.isfinite(value).all():
            raise ValueError('Field data contains a nonfinite value')
        data[name] = value.astype(np.float64 if name == 'xyz' else np.complex128, copy=False)
    count = len(data['xyz'])
    if count == 0 or len(data['E']) != count:
        raise ValueError('Incomplete field arrays')
    if data.get('H') is not None:
        h = np.asarray(data['H'])
        if h.shape != (count, 3) or h.dtype.kind not in 'fc' or not np.isfinite(h).all():
            raise ValueError('Invalid or nonfinite magnetic field array')
        data['H'] = h.astype(np.complex128, copy=False)
    else:
        data['H'] = None
    for names in ('layer_names', 'material_names'):
        values = np.asarray(data[names])
        if values.ndim != 1 or values.dtype.kind not in 'US' or not len(values):
            raise ValueError(f'Invalid field {names}')
        values = values.astype(str)
        if len(np.unique(values)) != len(values) or np.any(values == ''):
            raise ValueError(f'Invalid field {names}')
        data[names] = values
    for key, maximum in (('plane', len(PLANE_NAMES)), ('layer', len(data['layer_names'])),
                         ('material', len(data['material_names']))):
        value = np.asarray(data[key])
        if value.shape != (count,) or value.dtype.kind not in 'iu' or np.any(value >= maximum):
            raise ValueError(f'Invalid field {key} labels')
        if value.dtype.kind == 'i' and np.any(value < 0):
            raise ValueError(f'Invalid field {key} labels')
        data[key] = value.astype(np.int32, copy=False)
    return data


def write_field_arrays(directory, arrays):
    """Publish the field archive atomically; never expose a partial ZIP."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = validate_field_arrays(arrays)
    payload = {key: data[key] for key in ('xyz', 'E', 'plane', 'layer', 'material',
                                         'layer_names', 'material_names')}
    if data['H'] is not None:
        payload['H'] = data['H']
    payload['schema_version'] = np.asarray(SCHEMA_VERSION, dtype=np.int32)
    destination = directory / ARRAY_FILENAME
    specifications = {key: (value.shape, value.dtype) for key, value in payload.items()}
    with DirectNPZWriter(destination, specifications) as writer:
        for key, value in payload.items():
            if value.ndim == 0:
                writer.append(key, value)
            else:
                rows = max(1, (8 * 1024 * 1024) // max(1, value[0:1].nbytes))
                for first in range(0, len(value), rows):
                    writer.append(key, value[first:first + rows])
    # A caller explicitly recalculating this directory must not leave an old
    # alternate field representation that could be exported accidentally.
    (directory / CSV_FILENAME).unlink(missing_ok=True)
    return destination


def arrays_from_frame(frame):
    planes = frame['plane'].astype(str).to_numpy()
    if not np.isin(planes, PLANE_NAMES).all():
        raise ValueError('Unknown field plane')
    layers, layer = np.unique(np.asarray(frame['layer'], dtype=str), return_inverse=True)
    materials, material = np.unique(np.asarray(frame['material'], dtype=str), return_inverse=True)
    data = dict(xyz=frame[['x_um', 'y_um', 'z_um']].to_numpy(dtype=np.float64),
                plane=np.asarray([PLANE_NAMES.index(p) for p in planes], dtype=np.int32),
                layer=layer, material=material, layer_names=layers, material_names=materials)
    for prefix in ('E', 'H'):
        columns = [prefix + axis + '_' + part for axis in 'xyz' for part in ('real', 'imag')]
        if prefix == 'H' and not all(c in frame for c in columns):
            data[prefix] = None
        else:
            values = frame[columns].to_numpy(dtype=np.float64).reshape(-1, 3, 2)
            data[prefix] = values[..., 0] + 1j * values[..., 1]
    return validate_field_arrays(data)


def load_field_arrays(directory):
    path = field_data_path(directory)
    if path.suffix == '.csv':
        import pandas as pd
        return arrays_from_frame(pd.read_csv(path, float_precision='round_trip'))
    with np.load(path, allow_pickle=False) as archive:
        version = archive['schema_version']
        if version.shape != () or version.dtype.kind not in 'iu' or int(version) != SCHEMA_VERSION:
            raise ValueError('Unsupported field array schema')
        data = {key: archive[key] for key in ('xyz', 'E', 'plane', 'layer', 'material',
                                             'layer_names', 'material_names')}
        data['H'] = archive['H'] if 'H' in archive else None
    return validate_field_arrays(data)


def field_frame(arrays):
    import pandas as pd
    data = validate_field_arrays(arrays)
    e = data['E']
    columns = dict(plane=np.asarray(PLANE_NAMES)[data['plane']], layer=data['layer_names'][data['layer']],
                   x_um=data['xyz'][:, 0], y_um=data['xyz'][:, 1], z_um=data['xyz'][:, 2])
    for i, axis in enumerate('xyz'):
        columns['E' + axis + '_real'] = e[:, i].real
        columns['E' + axis + '_imag'] = e[:, i].imag
    columns['E2'] = np.sum(np.abs(e)**2, axis=1)
    columns['material'] = data['material_names'][data['material']]
    h = data['H']
    if h is not None:
        for i, axis in enumerate('xyz'):
            columns['H' + axis + '_real'] = h[:, i].real
            columns['H' + axis + '_imag'] = h[:, i].imag
        flux = .5 * np.cross(e, h.conj()).real
        for i, axis in enumerate('xyz'):
            columns['S' + axis] = flux[:, i]
    return pd.DataFrame(columns)


def load_field_frame(directory):
    path = field_data_path(directory)
    if path.suffix == '.csv':
        import pandas as pd
        return pd.read_csv(path, float_precision='round_trip')
    return field_frame(load_field_arrays(directory))


def export_field_csv(directory, destination):
    import shutil
    source = field_data_path(directory)
    destination = Path(destination)
    if source.suffix != '.csv' and source.resolve() == destination.resolve():
        raise ValueError('CSV export cannot overwrite its source field archive')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix == '.csv':
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
    else:
        load_field_frame(directory).to_csv(destination, index=False)
    return destination


def copy_field_data(source, destination):
    import shutil
    source = field_data_path(source)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / source.name
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
        alternate = CSV_FILENAME if source.name == ARRAY_FILENAME else ARRAY_FILENAME
        (destination / alternate).unlink(missing_ok=True)
    return target
