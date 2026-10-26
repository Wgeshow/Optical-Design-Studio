"""Explicit field jobs, selected from complete spectra or a manual wavelength."""
from pathlib import Path
import math

SOURCES = ('manual', 'maxR', 'minR', 'maxT', 'minT', 'maxA', 'minA')
MODEL_KEYS = ('materials', 'layers', 'patterns', 'ax', 'ay', 'basis', 'phi', 'polarization')


class FiniteSpectrumPoints:
    """Bounded view for explicit full-scan fields; singular points have no fields."""
    def __init__(self,results):
        self.results=results
        self.count=sum(1 for _ in self)
    def __len__(self):return self.count
    def __iter__(self):
        for row in self.results:
            if all(value is not None and math.isfinite(value) for value in row[1:]):yield row


def compatible_project(current, saved):
    """Cheap UI check; the worker also compares fully resolved solver inputs."""
    keys = ('ax_um', 'ay_um', 'NumG', 'mode', 'theta_deg', 'phi_deg', 'polarization', 'fixed_wl_nm')
    return (all(current.get(key) == saved.get(key) for key in ('materials', 'layers', 'patterns'))
            and all(current.get('settings', {}).get(key) == saved.get('settings', {}).get(key) for key in keys))


def prepare_field_job(model, options, library):
    from data_library import read_json
    from scan_storage import SpectrumResults, legacy_spectrum_index
    from simulation_fields import validate_settings
    single = options.get('single_wavelength', True)
    if not isinstance(single, bool):
        raise ValueError('Single wavelength must be true or false.')
    source = options.get('wavelength_source', 'manual')
    if source not in SOURCES:
        raise ValueError('Choose a manual wavelength or a spectrum maximum/minimum.')
    cfg = dict(task='simulation_fields', field_settings=validate_settings(options.get('electric_fields', {})))
    if single and source == 'manual':
        cfg['field_points'] = [model['points'][0]]
        cfg['selection'] = dict(source='manual', wavelength_nm=model['points'][0][1])
        return cfg
    identifier = options.get('spectrum_id')
    if not identifier:
        raise ValueError('Run or load a matching completed spectrum first.')
    directory = library.directory(identifier)
    record = read_json(directory/'library_record.json')
    if record.get('status') != 'complete':
        raise ValueError('Use a completed spectrum for field selection.')
    reference = read_json(directory/'job.json')['model']
    if any(model.get(key) != reference.get(key) for key in MODEL_KEYS) or model['mode'] != reference['mode']:
        raise ValueError('The spectrum setup has changed. Run a new spectrum or restore its setup first.')
    # Wavelength sweeps have a fixed incidence angle; angle sweeps select both
    # the saved wavelength and angle, never silently substituting an angle.
    if reference['mode'] == 'Wavelength sweep' and model['points'][0][2] != reference['points'][0][2]:
        raise ValueError('The incidence angle differs from the saved spectrum.')
    index = directory/'spectrum.sqlite'
    rows = SpectrumResults(index) if index.is_file() else legacy_spectrum_index(directory/'results.csv')
    if rows is None or not len(rows):
        raise ValueError('The completed spectrum has no saved samples.')
    try:
        cfg['spectrum_directory'] = str(directory)
        if single:
            row = rows.extremum(source[-1], maximum=source.startswith('max'))
            if row is None:
                raise ValueError('No finite samples are available for this spectrum extremum.')
            cfg['field_points'] = [row[:3]]
            cfg['selection'] = dict(source=source, wavelength_nm=row[1], angle_deg=row[2], value=row['RTA'.index(source[-1])+3])
        else:
            finite=FiniteSpectrumPoints(rows)
            if not len(finite):raise ValueError('The spectrum has no finite samples for electric fields.')
            cfg['selection'] = dict(source='all', samples=len(finite),unavailable_samples=len(rows)-len(finite))
    finally:
        rows.close()
    if 'field_points' in cfg:
        model['points']=cfg['field_points']
    return cfg


def execute_field_job(model, perf, cfg, directory, emit=lambda event: None, cancelled=lambda: False):
    from scan_storage import SpectrumResults, legacy_spectrum_index
    from simulation_fields import execute_simulation_fields
    rows = cfg.get('field_points')
    index = None
    if rows is None:
        root = Path(cfg['spectrum_directory'])
        index = SpectrumResults(root/'spectrum.sqlite') if (root/'spectrum.sqlite').is_file() else legacy_spectrum_index(root/'results.csv')
        rows = FiniteSpectrumPoints(index)
    try:
        result = execute_simulation_fields(model, perf, rows, cfg['field_settings'], directory, emit, cancelled)
        result['selection'] = cfg['selection']
        result['reused_spectrum_solution'] = False
        return result
    finally:
        if index is not None:
            index.close()
