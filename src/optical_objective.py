"""Explicit optical response selection; raw S4 rows always remain [i, wl, theta, R, T, A]."""
import math

RESPONSES = {'Absorption': 5, 'Transmission': 4, 'Reflection': 3}


def response_name(cfg):
    name = cfg.get('response', 'Absorption')
    if name not in RESPONSES:
        raise ValueError('Response must be Absorption, Transmission, or Reflection')
    return name


def response_rows(rows, cfg):
    """Adapt the legacy peak detector without changing stored physical spectra."""
    column = RESPONSES[response_name(cfg)]
    return [list(row[:5]) + [row[column]] for row in rows]


def valid_spectrum(rows):
    return bool(rows) and all(len(r) == 6 and all(math.isfinite(float(v)) for v in r)
        and all(-1e-8 <= float(v) <= 1 + 1e-8 for v in r[3:6])
        and abs(sum(r[3:6]) - 1) <= 1e-5 for r in rows)
