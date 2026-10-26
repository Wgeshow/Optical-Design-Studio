"""Specular co-polarized tangential electric-field phase at stack boundaries."""
import cmath
import csv
import math
from pathlib import Path
from model import epsilon


def validate_phase_model(model):
    if len(model['layers']) < 3:
        raise ValueError('Phase measurement requires an internal layer; use a zero-thickness exit-material layer for a single interface.')
    boundaries = {model['layers'][0]['name'], model['layers'][-1]['name']}
    if any(p['layer'] in boundaries for p in model['patterns']):
        raise ValueError('Phase measurement requires uniform incident and exit half-spaces.')


def measure_phase(simulation, model, wavelength, theta):
    validate_phase_model(model)
    mats = {m['name']: m for m in model['materials']}
    eps_in = epsilon(mats[model['layers'][0]['material']], wavelength)
    eps_out = epsilon(mats[model['layers'][-1]['material']], wavelength)
    # Match S4's plane-wave source: its transverse wavevector uses the real
    # part of the incident index, including for absorbing incident media.
    # Complex n here would invent lateral attenuation and can reverse the
    # outgoing kz branch, changing the measured transmission phase by ~pi.
    n = cmath.sqrt(eps_in).real
    angle, phi = math.radians(theta), math.radians(model['phi'])
    kx, ky = n * math.sin(angle) * math.cos(phi), n * math.sin(angle) * math.sin(phi)

    def electric(amplitudes, eps, direction):
        kz = cmath.sqrt(eps-kx*kx-ky*ky)
        if kz.imag < 0 or (abs(kz.imag) < 1e-14 and kz.real < 0):
            kz = -kz
        kz *= direction
        if abs(kz) < 1e-14 or abs(eps) < 1e-14:
            return None
        hx, hy = amplitudes[0], amplitudes[len(amplitudes)//2]
        hz = -(kx*hx+ky*hy)/kz
        return ((hy*kz-hz*ky)/eps, (hz*kx-hx*kz)/eps)

    incident, reflected = simulation.GetAmplitudes(model['layers'][0]['name'], 0.)
    transmitted, _ = simulation.GetAmplitudes(model['layers'][-1]['name'], 0.)
    reference = electric(incident, eps_in, 1)
    if reference is None:
        return [None, None]
    norm = sum(abs(v)**2 for v in reference)
    if norm < 1e-24:
        return [None, None]
    phases = []
    for amps, eps, direction in [(reflected, eps_in, -1), (transmitted, eps_out, 1)]:
        field = electric(amps, eps, direction)
        coefficient = None if field is None else sum(v*r.conjugate() for v, r in zip(field, reference))/norm
        phases.append(math.degrees(cmath.phase(coefficient)) if coefficient is not None and abs(coefficient) > 1e-10 and math.isfinite(abs(coefficient)) else None)
    return phases


PHASE_MODES = [('0–2π', 'positive'), ('−π–π', 'signed'), ('Unwrapped', 'unwrapped')]
PHASE_UNITS = [('Radians', 'radians'), ('Phase / π', 'pi'), ('Degrees', 'degrees')]
PHASE_COLUMNS = ['wavelength_nm', 'angle_deg', 'reflection_phase_deg', 'transmission_phase_deg',
                 'reflection_change_deg', 'transmission_change_deg']


def _finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


class _PhaseAccumulator:
    """Unwrap in acquisition order, before any preview selection."""
    def __init__(self):
        self.variable = None
        self.coordinate = None
        self.direction = 0
        self.previous = [None, None]
        self.unwrapped = [None, None]
        self.offset = [0., 0.]
        self.reference = [None, None]
        self.segment = [0, 0]
        self.positive_segment = [0, 0]
        self.signed_segment = [0, 0]

    def reset(self):
        self.previous = [None, None]
        self.unwrapped = [None, None]
        self.offset = [0., 0.]
        self.reference = [None, None]
        self.direction = 0

    def process(self, row):
        row = dict(row)
        coordinates = (_finite(row.get('wavelength_nm')), _finite(row.get('angle_deg')))
        if None in coordinates:
            self.reset()
            self.coordinate = None
        elif self.coordinate is not None:
            wave, angle = coordinates
            old_wave, old_angle = self.coordinate
            if self.variable is None:
                if wave != old_wave:self.variable = 'wavelength_nm'
                elif angle != old_angle:self.variable = 'angle_deg'
            primary = 1 if self.variable == 'angle_deg' else 0
            delta = coordinates[primary]-self.coordinate[primary]
            direction = (delta > 0)-(delta < 0)
            # Independent angle/wavelength branches and reversed acquisition
            # sweeps have separate references. Never join them with a line.
            branch_changed = coordinates[1-primary] != self.coordinate[1-primary]
            if branch_changed or (direction and self.direction and direction != self.direction):
                self.reset()
            if direction and not branch_changed:self.direction = direction
        if None not in coordinates:self.coordinate = coordinates
        for index, response in enumerate(('reflection', 'transmission')):
            phase = _finite(row.get(f'{response}_effective_phase_deg',row.get(f'{response}_phase_deg')))
            row[f'{response}_effective_phase_deg'] = phase
            if phase is None or None in coordinates:
                self.previous[index] = self.unwrapped[index] = self.reference[index] = None
                self.offset[index] = 0.
                unwrapped = change = segment = None
            else:
                if self.previous[index] is None:
                    self.segment[index] += 1
                    self.positive_segment[index] += 1
                    self.signed_segment[index] += 1
                    self.offset[index] = 0.
                    self.unwrapped[index] = self.reference[index] = phase
                else:
                    # Retain actual wrap crossings in preview metadata, even
                    # when decimation omits the samples around that crossing.
                    previous = self.previous[index]
                    if abs(phase % 360-previous % 360) > 180:self.positive_segment[index] += 1
                    if abs((phase+180) % 360-(previous+180) % 360) > 180:self.signed_segment[index] += 1
                    delta = phase-previous
                    complement = (delta+180) % 360-180
                    # Match NumPy unwrap(period=360), including its positive
                    # half-period tie: +180 stays +180 rather than becoming
                    # -180. Below half a cycle there is no correction.
                    if complement == -180 and delta > 0:complement = 180
                    if abs(delta) >= 180:self.offset[index] += complement-delta
                    self.unwrapped[index] = phase+self.offset[index]
                self.previous[index] = phase
                unwrapped = self.unwrapped[index]
                change = unwrapped-self.reference[index]
                segment = self.segment[index]
            row[f'{response}_unwrapped_deg'] = unwrapped
            row[f'{response}_change_deg'] = change
            row[f'{response}_segment'] = segment
            row[f'{response}_positive_segment'] = self.positive_segment[index] if segment is not None else None
            row[f'{response}_signed_segment'] = self.signed_segment[index] if segment is not None else None
        return row


def write_phase_csv(path, rows):
    # Keep the established complete raw CSV schema and degree conventions.
    accumulator = _PhaseAccumulator()
    with open(path, 'w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=PHASE_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        for _, wave, theta, reflection, transmission in rows:
            writer.writerow(accumulator.process(dict(wavelength_nm=wave, angle_deg=theta,
                reflection_phase_deg=reflection, transmission_phase_deg=transmission)))


def _phase_rows(source,reference=None):
    """Stream exact matching grids; reference phase must also be defined."""
    from itertools import zip_longest
    with open(source,newline='',encoding='utf-8-sig') as stream:
        rows=csv.DictReader(stream)
        required={'wavelength_nm','angle_deg','reflection_phase_deg','transmission_phase_deg'}
        if not required.issubset(rows.fieldnames or []):raise ValueError('The sample CSV is missing saved phase / sweep columns.')
        if reference is None:
            yield from rows
            return
        with open(reference,newline='',encoding='utf-8-sig') as ref_stream:
            refs=csv.DictReader(ref_stream)
            if not required.issubset(refs.fieldnames or []):raise ValueError('The reference CSV must contain wavelength_nm, angle_deg and both saved phase columns.')
            missing=object()
            for index,(row,ref) in enumerate(zip_longest(rows,refs,fillvalue=missing)):
                if row is missing or ref is missing:raise ValueError('Reference grid mismatch: the complete sample and reference CSVs must have the same number of rows.')
                for coordinate in ('wavelength_nm','angle_deg'):
                    value,ref_value=_finite(row.get(coordinate)),_finite(ref.get(coordinate))
                    if value is None or ref_value is None or value!=ref_value:
                        raise ValueError(f'Reference grid mismatch at sample {index+1}: {coordinate} must match exactly in acquisition order. No interpolation is applied.')
                for response in ('reflection','transmission'):
                    phase,ref_phase=_finite(row.get(f'{response}_phase_deg')),_finite(ref.get(f'{response}_phase_deg'))
                    row[f'{response}_reference_phase_deg']=ref_phase
                    difference=phase-ref_phase if phase is not None and ref_phase is not None else None
                    wrapped=(difference+180)%360-180 if difference is not None else None
                    # Preserve the signed complex-ratio half-cycle tie; a
                    # +180 difference must not become a -180 step before the
                    # full-sampling NumPy-compatible accumulator sees it.
                    if wrapped == -180 and difference > 0:wrapped=180.
                    row[f'{response}_effective_phase_deg']=wrapped
                yield row


def _reference_metadata(reference):
    if reference is None:return dict(phase_reference_mode='stack_boundaries',phase_reference_csv='',
        phase_reference_convention='Co-polarized tangential E at the top and bottom stack boundary planes.')
    return dict(phase_reference_mode='reference_csv',phase_reference_csv=str(Path(reference).resolve()),
        phase_reference_convention='arg(response_sample / response_reference); assumes matching polarization and stack boundary reference planes; exact matching sweep coordinates, no interpolation or fitted offset.')


def read_phase_preview(path, count=None, limit=20000,reference_path=None):
    """Bounded rows with unwrapping derived from every authoritative CSV row."""
    import pandas as pd
    path = Path(path)
    if not path.is_file():return pd.DataFrame()
    if limit < 1:raise ValueError('Phase preview limit must be positive.')
    # The optional count is only a hint; independently count the actual phase
    # file, since failed optical samples can make spectrum counts different.
    with path.open(newline='', encoding='utf-8-sig') as stream:
        count = max(0, sum(1 for _ in stream)-1)
    stride = max(1, math.ceil(max(0, count-1)/max(1, limit-1)))
    accumulator = _PhaseAccumulator()
    selected = []
    for index,raw in enumerate(_phase_rows(path,reference_path)):
        row = accumulator.process(raw)
        if (index % stride == 0 or index == count-1) and len(selected) < limit:selected.append(row)
    frame = pd.DataFrame(selected).apply(pd.to_numeric, errors='coerce')
    frame.attrs.update(phase_prepared=True, phase_variable=accumulator.variable or 'wavelength_nm',
                       phase_sample_count=count,**_reference_metadata(reference_path))
    return frame


def prepare_phase_frame(frame):
    """Prepare complete input rows, or retain a prepared full-sample preview."""
    import pandas as pd
    if frame.empty or frame.attrs.get('phase_prepared'):return frame.copy()
    accumulator = _PhaseAccumulator()
    prepared = pd.DataFrame(accumulator.process(row) for row in frame.to_dict('records'))
    prepared.attrs.update(phase_prepared=True, phase_variable=accumulator.variable or 'wavelength_nm',
                          phase_sample_count=len(frame))
    return prepared


def phase_display_frame(frame, mode='positive', unit='radians'):
    """Convert display columns without modifying raw phase or the input frame."""
    import pandas as pd
    if mode not in dict((key, label) for label, key in PHASE_MODES):raise ValueError('Unknown phase display mode.')
    if unit not in dict((key, label) for label, key in PHASE_UNITS):raise ValueError('Unknown phase display unit.')
    frame = prepare_phase_frame(frame)
    scale = {'radians':math.pi/180, 'pi':1/180, 'degrees':1}[unit]
    for response in ('reflection', 'transmission'):
        if frame.empty:continue
        raw = pd.to_numeric(frame[f'{response}_effective_phase_deg'],errors='coerce')
        phase = frame[f'{response}_unwrapped_deg'] if mode == 'unwrapped' else raw % 360 if mode == 'positive' else (raw+180) % 360-180
        frame[f'{response}_display_{unit}'] = (phase*scale).where(frame[f'{response}_segment'].notna())
        frame[f'{response}_change_{unit}'] = frame[f'{response}_change_deg']*scale
    frame.attrs.update(phase_mode=mode, phase_unit=unit)
    return frame


def export_phase_display_csv(source, destination, mode='positive', unit='radians',reference_path=None):
    """Stream the entire selected-unit export, preserving original raw columns."""
    if Path(source).resolve() == Path(destination).resolve():raise ValueError('Choose a different file to preserve the complete raw phase CSV.')
    if reference_path and Path(reference_path).resolve()==Path(destination).resolve():raise ValueError('Choose a different file to preserve the physical reference CSV.')
    if mode not in {key for _, key in PHASE_MODES}:raise ValueError('Unknown phase display mode.')
    if unit not in {key for _, key in PHASE_UNITS}:raise ValueError('Unknown phase display unit.')
    scale = {'radians':math.pi/180, 'pi':1/180, 'degrees':1}[unit]
    accumulator = _PhaseAccumulator()
    metadata=_reference_metadata(reference_path)
    if reference_path:
        import hashlib
        with open(reference_path,'rb') as stream:metadata['phase_reference_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
    # Validate the entire reference grid before creating an export, so a late
    # mismatch cannot leave a seemingly complete comparison CSV on disk.
    if reference_path:
        for _ in _phase_rows(source,reference_path):pass
    with open(source, newline='', encoding='utf-8-sig') as incoming, open(destination, 'w', newline='', encoding='utf-8') as outgoing:
        reader = csv.DictReader(incoming)
        fields = list(reader.fieldnames or PHASE_COLUMNS)
        extras = ['phase_display_mode','phase_display_unit',*metadata]+[f'{response}_{suffix}_{unit}' for response in ('reflection', 'transmission') for suffix in ('display', 'change')]
        if reference_path:extras.extend(f'{response}_{suffix}_phase_deg' for response in ('reflection','transmission') for suffix in ('reference','effective'))
        writer = csv.DictWriter(outgoing, fieldnames=fields+[key for key in extras if key not in fields], extrasaction='ignore')
        writer.writeheader()
        for raw in _phase_rows(source,reference_path):
            prepared = accumulator.process(raw)
            converted = dict(phase_display_mode=mode,phase_display_unit=unit,**metadata)
            for response in ('reflection', 'transmission'):
                phase = _finite(prepared.get(f'{response}_unwrapped_deg' if mode == 'unwrapped' else f'{response}_effective_phase_deg'))
                if prepared[f'{response}_segment'] is None:phase = None
                if phase is not None:
                    if mode == 'positive':phase %= 360
                    elif mode == 'signed':phase = (phase+180) % 360-180
                change = prepared[f'{response}_change_deg']
                converted[f'{response}_display_{unit}'] = phase*scale if phase is not None else ''
                converted[f'{response}_change_{unit}'] = change*scale if change is not None else ''
                if reference_path:
                    for suffix in ('reference','effective'):
                        value=prepared[f'{response}_{suffix}_phase_deg']
                        converted[f'{response}_{suffix}_phase_deg']=value if value is not None else ''
            # Original degree strings and stored legacy change columns remain
            # byte-for-value intact; only additional display columns are new.
            writer.writerow(dict(raw, **converted))


def phase_figure(frame, mode='positive', unit='radians'):
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.ticker import MultipleLocator, FuncFormatter
    figure = Figure(figsize=(8, 6), layout='constrained')
    axes = figure.subplots(2, 1)
    if frame.empty:
        for axis in axes:axis.set_axis_off()
        axes[0].text(.5, .5, 'Enable phase measurement and run a simulation.\nOlder runs do not contain phase data.', ha='center', transform=axes[0].transAxes)
        return figure
    frame = phase_display_frame(frame, mode, unit)
    if frame.attrs.get('phase_reference_mode')=='reference_csv':
        name='/'.join(Path(frame.attrs['phase_reference_csv']).parts[-3:])
        figure.suptitle(f'Reference-relative phase · {name}\narg(response / reference); assumes matching polarization and boundary planes',fontsize=9)
    else:figure.suptitle('Boundary phase · co-polarized tangential E at top / bottom stack planes',fontsize=9)
    variable = frame.attrs['phase_variable']
    frame = frame.iloc[np.unique(np.linspace(0, len(frame)-1, min(len(frame), 20000), dtype=int))]
    ylabel = {'radians':'Phase (rad)', 'pi':'Phase / π', 'degrees':'Phase (°)'}[unit]
    cycle = {'radians':2*math.pi, 'pi':2., 'degrees':360.}[unit]
    titles = {'positive':'Wrapped phase · 0–2π', 'signed':'Wrapped phase · −π–π', 'unwrapped':'Unwrapped phase · continuous valid segments'}
    for axis, suffix, title in zip(axes, ['display', 'change'], [titles[mode], 'Unwrapped change · each 2π is one full cycle; resets after gaps / branches']):
        for response, color in (('reflection', '#36b9ff'), ('transmission', '#ed90bf')):
            segment_key = f'{response}_{mode}_segment' if suffix == 'display' and mode != 'unwrapped' else f'{response}_segment'
            segment_ids=frame[segment_key].to_numpy(dtype=float)
            x=frame[variable].to_numpy(dtype=float)
            y=frame[f'{response}_{suffix}_{unit}'].to_numpy(dtype=float)
            valid=np.isfinite(segment_ids)
            y=np.where(valid,y,np.nan)
            breaks=np.r_[False,segment_ids[1:]!=segment_ids[:-1]]
            positions=np.arange(len(frame))+np.cumsum(breaks)
            shown_x=np.full(len(frame)+int(breaks.sum()),np.nan)
            shown_y=np.full_like(shown_x,np.nan)
            shown_x[positions]=x;shown_y[positions]=y
            # One Line2D per response keeps long sweeps responsive. Inserted
            # NaNs preserve every gap/branch/wrap event without thousands of
            # individual Matplotlib artists.
            axis.plot(shown_x,shown_y,label=response.title(),color=color,marker='.',markersize=2)
        axis.set(ylabel=ylabel, title=title)
        axis.grid(alpha=.2)
        if axis.lines:axis.legend()
        if suffix == 'change' or mode == 'unwrapped':
            lower,upper=axis.get_ylim()
            cycle_stride=max(1,math.ceil((upper-lower)/(12*cycle)))
            axis.yaxis.set_major_locator(MultipleLocator(cycle*cycle_stride))
            if unit == 'radians':
                axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: '0' if abs(value)<1e-10 else f'{value/math.pi:g}π'))
    if mode != 'unwrapped':
        positions = np.linspace(0, cycle, 5) if mode == 'positive' else np.linspace(-cycle/2, cycle/2, 5)
        axes[0].set_ylim(positions[0], positions[-1]);axes[0].set_yticks(positions)
        # Native Qt tick text needs headroom at both fixed phase boundaries.
        # This affects its viewport only, not phase data or exported limits.
        axes[0]._ods_native_y_padding = .12
        if unit == 'radians':axes[0].set_yticklabels(['0','π/2','π','3π/2','2π'] if mode == 'positive' else ['−π','−π/2','0','π/2','π'])
    axes[-1].set_xlabel('Incidence angle (degrees)' if variable == 'angle_deg' else 'Wavelength (nm)')
    return figure
