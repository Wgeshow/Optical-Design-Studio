"""Validated first-pass PCSEL design model."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class PCSELDesign:
    period_um: float = .8
    hole_radius_um: float = .22
    etch_depth_um: float = .18
    gain_thickness_um: float = .25
    wavelength_nm: float = 940.
    patterned_layer_thickness_um: float | None = None
    def validate(self):
        values=(self.period_um,self.hole_radius_um,self.etch_depth_um,self.gain_thickness_um,self.wavelength_nm)
        if not all(math.isfinite(v) and v>0 for v in values): raise ValueError('PCSEL values must be finite and positive.')
        if self.hole_radius_um >= self.period_um/2: raise ValueError('Hole radius must be smaller than half the lattice period.')
        thickness = self.gain_thickness_um if self.patterned_layer_thickness_um is None else self.patterned_layer_thickness_um
        if not math.isfinite(thickness) or thickness <= 0: raise ValueError('Patterned-layer thickness must be finite and positive.')
        if self.etch_depth_um > thickness: raise ValueError('Etch depth cannot exceed patterned-layer thickness.')
        return self
    @property
    def fill_factor(self): return math.pi*(self.hole_radius_um/self.period_um)**2
