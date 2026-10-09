"""Shared physical dimensions and array placement for CAD and COMSOL."""
from dataclasses import dataclass
import math
from structure_preview import normalize_region, periodic_centers

UNITS = {'nm': 1000., 'um': 1., 'mm': .001, 'm': .000001}


@dataclass(frozen=True)
class ExportOptions:
    cells_x: int = 1
    cells_y: int = 1
    unit: str = 'um'
    include_exterior: bool = True
    incident_um: float = 1.
    exit_um: float = 1.

    def validate(self):
        for value in (self.cells_x, self.cells_y):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000000:
                raise ValueError('Repeat counts must be whole numbers from 1 to 1,000,000.')
        if self.unit not in UNITS:
            raise ValueError('Export unit must be nm, um, mm, or m.')
        for value in (self.incident_um, self.exit_um):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Exterior thicknesses must be finite and positive.')
        return self


def dimensions(settings, options):
    options.validate()
    ax, ay = float(settings.get('ax_um', 0)), float(settings.get('ay_um', 0))
    if not all(math.isfinite(v) and v > 0 for v in (ax, ay)):
        raise ValueError('Lattice periods must be finite and greater than zero.')
    return ax, ay, ax * options.cells_x, ay * options.cells_y


def array_centers(raw, ax, ay, options):
    region = normalize_region(raw)
    # An even array contains whole cells, with centers at +/- half periods.
    region['cx'] += (1-options.cells_x)*ax/2
    region['cy'] += (1-options.cells_y)*ay/2
    width, depth = options.cells_x*ax, options.cells_y*ay
    return periodic_centers(region, ax, ay, (-width/2, width/2, -depth/2, depth/2), limit=100000)
