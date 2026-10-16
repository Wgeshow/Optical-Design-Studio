"""Exact endpoint-inclusive bias schedules with explicit resource checks.

Editable devices have no arbitrary voltage/41-state restriction here. Physics
models validate their own domain; fixed legacy studies may pass bounds/caps.
Zero is an explicit reference solve, never a replacement for a requested point.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
import math
from collections.abc import Sequence

from electrical_mesh import available_memory_bytes


def _finite(value, name):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be a finite number')
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f'{name} must be a finite number') from None
    if not math.isfinite(number):
        raise ValueError(f'{name} must be a finite number')
    return number


def _allocation_check(states, max_states=None):
    if max_states is not None and states > max_states:
        raise ValueError(f'Limit the resolved voltage list, including zero, to {max_states} states.')
    available = available_memory_bytes()
    # Includes the Python sequence, duplicate set, UI metadata and transient
    # copies; mesh and per-bias saved volumes are estimated separately.
    budget = int(available * .6) if available is not None else 256 * 1024**2
    estimated = states * 256
    if estimated > budget:
        mode = '60% of currently available RAM' if available is not None else 'the 256 MiB scheduling guard (available RAM unknown)'
        raise ValueError(f'The requested {states:,}-state voltage schedule needs approximately '
                         f'{estimated / 1024**2:,.1f} MiB just for scheduling, exceeding {mode}. '
                         'No points were removed or coarsened.')


def resolve_biases(values, *, low=None, high=None, max_states=None):
    """Return finite distinct offsets in order, with the zero reference first."""
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
        raise ValueError('biases_V must contain at least one finite voltage')
    _allocation_check(len(values) + 1)
    output = [0.]
    seen = {0.}
    for value in values:
        number = _finite(value, 'Bias')
        if (low is not None and number < low) or (high is not None and number > high):
            raise ValueError(f'Bias must be between {low:g} and {high:g} V')
        if number not in seen:
            output.append(number)
            seen.add(number)
            if max_states is not None and len(output) > max_states:
                raise ValueError(f'Limit the resolved voltage list, including zero, to {max_states} states.')
    return output


def describe_sweep(start, stop, *, step=None, count=None, low=None, high=None, max_states=None):
    """Describe exact counts and endpoint spacing without building the list."""
    start, stop = _finite(start, 'Start voltage'), _finite(stop, 'Stop voltage')
    if (step is None) == (count is None):
        raise ValueError('Choose either a voltage step or a number of points')
    for value in (start, stop):
        if (low is not None and value < low) or (high is not None and value > high):
            raise ValueError(f'Bias must be between {low:g} and {high:g} V')
    beginning, end = Decimal(str(start)), Decimal(str(stop))
    direction = 1 if stop >= start else -1
    if count is not None:
        if isinstance(count, bool):
            raise ValueError('Number of points must be a positive integer')
        try:
            size = int(count)
        except (TypeError, ValueError, OverflowError):
            raise ValueError('Number of points must be a positive integer') from None
        if size != count or size < 1:
            raise ValueError('Number of points must be a positive integer')
        if (start == stop and size != 1) or (start != stop and size < 2):
            raise ValueError('Equal endpoints require one point; different endpoints require at least two.')
        increment = abs(end - beginning) / Decimal(size - 1) if size > 1 else Decimal(0)
        last_interval = increment
        sampling = 'count'
    else:
        magnitude = _finite(step, 'Voltage step')
        if magnitude <= 0:
            raise ValueError('Voltage step must be positive')
        increment = Decimal(str(magnitude))
        span = abs(end - beginning)
        full = int((span / increment).to_integral_value(rounding=ROUND_FLOOR))
        remainder = span - full * increment
        size = full + 1 + int(remainder != 0)
        last_interval = remainder if remainder else increment if size > 1 else Decimal(0)
        sampling = 'step'
    _allocation_check(size, max_states)
    # An interior zero is a requested point only if it lies on the exact grid.
    offset = -beginning / (direction * increment) if increment else Decimal(0)
    zero_present = start == 0 or stop == 0 or (increment and
        0 <= offset <= size - 1 and offset == offset.to_integral_value())
    resolved = size + int(not zero_present)
    _allocation_check(resolved, max_states)
    if size > 1:
        second = float(beginning + direction * increment) if size > 2 else stop
        penultimate = float(end - direction * last_interval)
        if second == start or penultimate == stop:
            raise ValueError('Requested voltage points cannot be distinguished as finite floating-point values; use wider spacing.')
    return dict(requested_count=size, resolved_count=resolved, spacing_V=float(increment),
                final_interval_V=float(last_interval), zero_reference_added=not bool(zero_present),
                sampling=sampling)


def generate_biases(start, stop, *, step=None, count=None, low=None, high=None, max_states=None):
    """Generate a step or point-count sweep, retaining both requested endpoints.

    A non-dividing step appends the exact stop with a shorter final interval.
    Descending sweeps are allowed. Distinct binary-float representability is
    checked rather than silently deleting indistinguishable requested points.
    """
    start = _finite(start, 'Start voltage')
    stop = _finite(stop, 'Stop voltage')
    describe_sweep(start, stop, step=step, count=count, low=low, high=high, max_states=max_states)
    if (step is None) == (count is None):
        raise ValueError('Choose either a voltage step or a number of points')
    for value in (start, stop):
        if (low is not None and value < low) or (high is not None and value > high):
            raise ValueError(f'Bias must be between {low:g} and {high:g} V')
    if count is not None:
        if isinstance(count, bool):
            raise ValueError('Number of points must be a positive integer')
        try:
            size = int(count)
        except (TypeError, ValueError, OverflowError):
            raise ValueError('Number of points must be a positive integer') from None
        if size != count or size < 1:
            raise ValueError('Number of points must be a positive integer')
        if start == stop:
            if size != 1:
                raise ValueError('Equal endpoints define exactly one distinct point')
            values = [start]
        else:
            if size < 2:
                raise ValueError('Different endpoints require at least two points')
            _allocation_check(size, max_states)
            _allocation_check(size + 1)
            # Decimal difference prevents finite endpoint subtraction overflow.
            beginning = Decimal(str(start))
            delta = (Decimal(str(stop)) - beginning) / Decimal(size - 1)
            values = [float(beginning + i * delta) for i in range(size)]
            values[0], values[-1] = start, stop
    else:
        step = _finite(step, 'Voltage step')
        if step <= 0:
            raise ValueError('Voltage step must be positive')
        beginning, end, increment = Decimal(str(start)), Decimal(str(stop)), Decimal(str(step))
        span = abs(end - beginning)
        full = int((span / increment).to_integral_value(rounding=ROUND_FLOOR))
        exact = full * increment == span
        size = full + 1 + (0 if exact else 1)
        _allocation_check(size, max_states)
        _allocation_check(size + 1)
        direction = 1 if stop >= start else -1
        values = [float(beginning + direction * i * increment) for i in range(full + 1)]
        if not exact:
            values.append(stop)
        values[0], values[-1] = start, stop
    if not all(math.isfinite(value) for value in values) or len(set(values)) != len(values):
        raise ValueError('Requested voltage points cannot be distinguished as finite floating-point values; use wider spacing.')
    return resolve_biases(values, low=low, high=high, max_states=max_states)
