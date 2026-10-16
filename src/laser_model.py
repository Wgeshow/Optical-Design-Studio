"""Traceable lumped semiconductor-laser/PCSEL performance calculations.

SI units are used internally; serialized field suffixes state display units.
The model couples optical-mode inputs to threshold, carrier/photon, thermal and
small-signal estimates. It complements rather than replaces FDTD/drift diffusion.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import math
from typing import Iterable

Q_E = 1.602176634e-19
H = 6.62607015e-34
C0 = 299792458.0


@dataclass(frozen=True)
class LaserParameters:
    wavelength_nm: float = 940.0
    group_index: float = 3.6
    confinement: float = 0.22
    quality_factor: float = 4.2e4
    transparency_density_cm3: float = 1.0e18
    differential_gain_cm2: float = 2.5e-16
    active_volume_um3: float = 120.0
    recombination_a_s: float = 1.0e8
    recombination_b_cm3_s: float = 1.0e-10
    recombination_c_cm6_s: float = 3.0e-29
    injection_efficiency: float = 0.85
    differential_efficiency: float = 0.70
    internal_loss_cm: float = 0.0
    spontaneous_emission_factor: float = 1.0e-4
    gain_compression_cm3: float = 0.0
    ambient_temperature_k: float = 300.0
    thermal_resistance_k_w: float = 0.0
    drive_voltage_v: float = 1.5
    wavelength_shift_nm_k: float = 0.07
    transparency_temperature_coefficient_k: float = 0.002
    differential_gain_temperature_coefficient_k: float = 0.0015

    def validate(self):
        positive = ("wavelength_nm", "group_index", "confinement", "quality_factor",
                    "transparency_density_cm3", "differential_gain_cm2", "active_volume_um3",
                    "recombination_a_s", "recombination_b_cm3_s", "recombination_c_cm6_s",
                    "injection_efficiency", "differential_efficiency",
                    "ambient_temperature_k", "drive_voltage_v")
        nonnegative = ("internal_loss_cm", "spontaneous_emission_factor",
                       "gain_compression_cm3", "thermal_resistance_k_w",
                       "wavelength_shift_nm_k", "transparency_temperature_coefficient_k",
                       "differential_gain_temperature_coefficient_k")
        if any(not math.isfinite(float(getattr(self, n))) or getattr(self, n) <= 0 for n in positive):
            raise ValueError("Positive laser parameters must be finite and greater than zero.")
        if any(not math.isfinite(float(getattr(self, n))) or getattr(self, n) < 0 for n in nonnegative):
            raise ValueError("Loss, thermal, and correction parameters must be finite and non-negative.")
        for name in ("confinement", "injection_efficiency", "differential_efficiency"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name.replace('_', ' ').title()} must be between zero and one.")
        if not 0 <= self.spontaneous_emission_factor <= 1:
            raise ValueError("Spontaneous-emission factor must be between zero and one.")
        return self


@dataclass(frozen=True)
class OpticalResult:
    wavelength_nm: float
    angular_frequency_rad_s: float
    group_velocity_m_s: float
    quality_factor: float
    linewidth_nm: float
    photon_lifetime_ps: float
    q_loss_cm_1: float
    internal_loss_cm_1: float
    total_loss_cm_1: float
    confinement_factor: float


@dataclass(frozen=True)
class ThresholdResult:
    material_gain_cm_1: float
    carrier_density_cm_3: float
    current_ma: float


@dataclass(frozen=True)
class SweepPoint:
    current_ma: float
    carrier_density_cm_3: float
    photon_density_cm_3: float
    output_power_mw: float
    temperature_k: float
    wavelength_nm: float
    wall_plug_efficiency: float
    relaxation_frequency_ghz: float


def _threshold(p, loss_cm, temperature):
    dt = temperature - p.ambient_temperature_k
    ntr = p.transparency_density_cm3 * math.exp(p.transparency_temperature_coefficient_k * dt)
    gain0 = p.differential_gain_cm2 * math.exp(-p.differential_gain_temperature_coefficient_k * dt)
    density = ntr + loss_cm / (p.confinement * gain0)
    rate = (p.recombination_a_s*density + p.recombination_b_cm3_s*density**2
            + p.recombination_c_cm6_s*density**3)
    current = Q_E * p.active_volume_um3 * 1e-12 * rate / p.injection_efficiency
    return density, current


def _subthreshold_density(p, current_a):
    target = p.injection_efficiency*current_a/(Q_E*p.active_volume_um3*1e-12)
    if target <= 0:
        return 0.0
    def rate(n):
        return p.recombination_a_s*n+p.recombination_b_cm3_s*n*n+p.recombination_c_cm6_s*n**3
    lo, hi = 0.0, p.transparency_density_cm3
    while rate(hi) < target:
        hi *= 2
    for _ in range(80):
        mid = (lo+hi)/2
        if rate(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo+hi)/2


def solve_laser(parameters: LaserParameters, currents_ma: Iterable[float],
                modulation_frequencies_ghz: Iterable[float] | None = None):
    """Return legacy flat values plus structured optical/threshold/sweep results."""
    p = parameters.validate()
    currents = [float(i) for i in currents_ma]
    if not currents or not all(math.isfinite(i) and i >= 0 for i in currents):
        raise ValueError("Drive currents must be a non-empty finite, non-negative sequence.")
    frequencies = [] if modulation_frequencies_ghz is None else [float(f) for f in modulation_frequencies_ghz]
    if not all(math.isfinite(f) and f >= 0 for f in frequencies):
        raise ValueError("Modulation frequencies must be finite and non-negative.")
    wavelength_m = p.wavelength_nm*1e-9
    omega = 2*math.pi*C0/wavelength_m
    vg = C0/p.group_index
    tau_p = p.quality_factor/omega
    q_loss = 1/(vg*tau_p)/100
    total_loss = q_loss+p.internal_loss_cm
    optical = OpticalResult(p.wavelength_nm, omega, vg, p.quality_factor,
                            p.wavelength_nm/p.quality_factor, tau_p*1e12,
                            q_loss, p.internal_loss_cm, total_loss, p.confinement)
    nth0, ith0 = _threshold(p, total_loss, p.ambient_temperature_k)
    slope = p.differential_efficiency*(H*C0/wavelength_m)/Q_E
    points = []
    for current_ma in currents:
        current = current_ma*1e-3
        temperature, power = p.ambient_temperature_k, 0.0
        for _ in range(50):
            nth, ith = _threshold(p, total_loss, temperature)
            power = slope*max(0, current-ith)/(1+p.gain_compression_cm3*nth)
            updated = p.ambient_temperature_k+p.thermal_resistance_k_w*max(0, p.drive_voltage_v*current-power)
            if abs(updated-temperature) < 1e-8:
                temperature = updated
                break
            temperature = (temperature+updated)/2
        nth, ith = _threshold(p, total_loss, temperature)
        if current < ith:
            density = _subthreshold_density(p, current)
            photons = p.spontaneous_emission_factor*p.recombination_b_cm3_s*density**2*tau_p
        else:
            density = nth
            stimulated = p.injection_efficiency*(current-ith)/(Q_E*p.active_volume_um3*1e-12)
            photons = max(0, stimulated*tau_p)
        excess = max(0, current/ith-1) if ith else 0
        carrier_lifetime = 1/max(p.recombination_a_s, 1)
        fr = math.sqrt(excess)/(2*math.pi*math.sqrt(max(tau_p*carrier_lifetime, 1e-30)))
        wpe = power/(p.drive_voltage_v*current) if current else 0
        points.append(SweepPoint(current_ma, density, photons, power*1e3, temperature,
                                 p.wavelength_nm+p.wavelength_shift_nm_k*(temperature-p.ambient_temperature_k),
                                 wpe, fr/1e9))
    threshold = ThresholdResult(total_loss/p.confinement, nth0, ith0*1e3)
    result = {
        "threshold_gain_cm-1": threshold.material_gain_cm_1,
        "threshold_density_cm-3": threshold.carrier_density_cm_3,
        "threshold_current_ma": threshold.current_ma,
        "photon_lifetime_ps": optical.photon_lifetime_ps,
        "slope_efficiency_w_per_a": slope,
        "currents_ma": currents,
        "output_power_mw": [x.output_power_mw for x in points],
        "schema": "optical-design-studio/laser-performance/v1",
        "inputs": asdict(p), "optical": asdict(optical), "threshold": asdict(threshold),
        "sweep": [asdict(x) for x in points],
        "thermal": {"enabled": p.thermal_resistance_k_w > 0,
                    "ambient_temperature_k": p.ambient_temperature_k,
                    "thermal_resistance_k_w": p.thermal_resistance_k_w,
                    "maximum_temperature_k": max(x.temperature_k for x in points),
                    "maximum_wavelength_nm": max(x.wavelength_nm for x in points)},
    }
    if frequencies:
        result["modulation"] = _modulation(frequencies, points[-1])
    return result


def _modulation(frequencies, point):
    fr = point.relaxation_frequency_ghz
    damping = max(.1, .7*fr)
    magnitudes = []
    for f in frequencies:
        if fr <= 0:
            magnitude = 1.0 if f == 0 else 0.0
        else:
            magnitude = fr*fr/max(math.sqrt((fr*fr-f*f)**2+(f*damping)**2), 1e-30)
        magnitudes.append(magnitude)
    target, bandwidth = 1/math.sqrt(2), None
    for left, right, ml, mr in zip(frequencies, frequencies[1:], magnitudes, magnitudes[1:]):
        if (ml-target)*(mr-target) <= 0 and mr != ml:
            bandwidth = left+(target-ml)*(right-left)/(mr-ml)
            break
    return {"bias_current_ma": point.current_ma, "relaxation_frequency_ghz": fr,
            "damping_rate_ghz": damping, "frequencies_ghz": frequencies,
            "magnitude_linear": magnitudes,
            "magnitude_db": [20*math.log10(max(x, 1e-30)) for x in magnitudes],
            "bandwidth_3db_ghz": bandwidth}
