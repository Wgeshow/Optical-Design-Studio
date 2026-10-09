"""Read wavelength-dependent optical constants, including refractiveindex.info CSVs."""
import bisect
import math
import re

UNITS = {'nm': 1., 'um': 1000., 'µm': 1000., 'μm': 1000., 'micron': 1000., 'microns': 1000.}


def parse_nk(text, unit, missing_k=None):
    """Return wavelength/n/k rows in nm; never infer units or missing extinction."""
    if str(unit).strip().lower() not in UNITS:
        raise ValueError('WavelengthUnit must be nm or um; units are never guessed')
    scale = UNITS[str(unit).strip().lower()]
    if missing_k is not None and not math.isfinite(float(missing_k)):
        raise ValueError('The explicit missing-k value must be finite')
    triples, sections = [], {'n': [], 'k': []}
    layout = None
    for index, line in enumerate(text.lstrip('\ufeff').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        fields = [v.strip().strip('\"\'') for v in re.split(r'[,;\t ]+', line)]
        # Headers may use wl, wavelength, lambda or wavelength with a unit suffix.
        label = fields[0].lower()
        if label in ('wl', 'wavelength', 'lambda', 'λ') or label.startswith(('wavelength_', 'wl_')):
            names = [v.lower() for v in fields]
            if names[1:] == ['n', 'k']:
                layout = 'nk'
            elif names[1:] in (['n'], ['k']):
                layout = names[1]
            else:
                raise ValueError(f'Line {index}: expected wavelength,n,k, wl,n or wl,k header')
            continue
        try:
            wavelength = float(fields[0]) * scale
        except ValueError:
            if fields[0] and fields[0][0] in '+-.0123456789':
                raise ValueError(f'Line {index}: invalid numeric wavelength') from None
            continue  # References and human-readable header text are allowed.
        effective = layout or ('nk' if len(fields) >= 3 else 'n')
        expected = 3 if effective == 'nk' else 2
        if len(fields) != expected:
            raise ValueError(f'Line {index}: expected {expected} columns for {effective}; missing data is not inferred')
        try:
            values = [float(v) for v in fields[1:]]
        except ValueError:
            raise ValueError(f'Line {index}: n and k must be numeric') from None
        if wavelength <= 0 or not all(math.isfinite(v) for v in [wavelength, *values]):
            raise ValueError(f'Line {index}: wavelengths must be positive and all values finite')
        if effective == 'nk':
            triples.append([wavelength, *values])
        else:
            sections[effective].append([wavelength, values[0]])

    def checked(rows, label):
        rows.sort()
        if len(rows) < 2:
            raise ValueError(f'{label}: need at least two numeric wavelength samples')
        if any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
            raise ValueError(f'{label}: duplicate wavelengths are not supported')
        return rows

    if triples:
        if sections['n'] or sections['k']:
            raise ValueError('Mixed three-column data and separate n/k sections are ambiguous')
        return checked(triples, 'n,k table')
    n = checked(sections['n'], 'n table')
    if not sections['k']:
        if missing_k is None:
            raise ValueError('This file has n but no k. Supply k data or explicitly enable "Missing k = 0" for a lossless assumption.')
        return [[wl, value, float(missing_k)] for wl, value in n]
    k = checked(sections['k'], 'k table')
    low, high = max(n[0][0], k[0][0]), min(n[-1][0], k[-1][0])
    if high <= low:
        raise ValueError('Separate n and k tables need an overlapping wavelength interval')
    grid = sorted({wl for table in (n, k) for wl, _ in table if low <= wl <= high})
    ngrid, kgrid = [row[0] for row in n], [row[0] for row in k]

    def interpolate(table, wavelengths, wl):
        index = bisect.bisect_left(wavelengths, wl)
        if index < len(table) and table[index][0] == wl:
            return table[index][1]
        a, b = table[index-1], table[index]
        return a[1] + (b[1]-a[1]) * (wl-a[0]) / (b[0]-a[0])

    return [[wl, interpolate(n, ngrid, wl), interpolate(k, kgrid, wl)] for wl in grid]


def csv_bytes(rows):
    return ('wavelength,n,k\n' + '\n'.join(','.join(repr(float(v)) for v in row) for row in rows) + '\n').encode('utf-8')
