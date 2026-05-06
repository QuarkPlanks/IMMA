"""
src/simulator/rheology.py
─────────────────────────
Rheological (flow) analysis for injection molding:
  - Power-law viscosity model
  - Hele-Shaw thin-shell fill pressure for rectangular and disc cavities
  - Runner pressure drop
  - Injection speed / shear rate estimation
  - Clamp force from cavity pressure
"""

import math
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Material rheological defaults (Power-law n, consistency index K_Pa_s^n)
# ─────────────────────────────────────────────────────────────────────────────

RHEOLOGY_DEFAULTS: dict[str, dict] = {
    # polymer: {"n": power-law index, "K": consistency [Pa·sⁿ], "eta_ref_Pas": apparent viscosity at γ̇=100 s⁻¹}
    "ABS":  {"n": 0.26, "K": 28000, "eta_ref_Pas": 200},
    "PC":   {"n": 0.12, "K": 90000, "eta_ref_Pas": 500},
    "PP":   {"n": 0.35, "K": 8000,  "eta_ref_Pas": 80},
    "PA6":  {"n": 0.68, "K": 500,   "eta_ref_Pas": 50},
    "PA66": {"n": 0.66, "K": 600,   "eta_ref_Pas": 60},
    "POM":  {"n": 0.62, "K": 2000,  "eta_ref_Pas": 150},
    "PBT":  {"n": 0.58, "K": 2500,  "eta_ref_Pas": 120},
    "PET":  {"n": 0.63, "K": 800,   "eta_ref_Pas": 70},
    "PMMA": {"n": 0.25, "K": 55000, "eta_ref_Pas": 600},
    "PS":   {"n": 0.28, "K": 22000, "eta_ref_Pas": 300},
    "TPU":  {"n": 0.30, "K": 18000, "eta_ref_Pas": 250},
    "PEEK": {"n": 0.15, "K": 150000,"eta_ref_Pas": 1200},
    "PPS":  {"n": 0.22, "K": 60000, "eta_ref_Pas": 700},
}

# Temperature sensitivity factor β [1/°C] for WLF shift (simplified Arrhenius)
TEMP_SENSITIVITY: dict[str, float] = {
    "ABS": 0.040, "PC": 0.025, "PP": 0.045, "PA6": 0.065, "PA66": 0.065,
    "POM": 0.050, "PBT": 0.045, "PET": 0.050, "PMMA": 0.030, "PS": 0.035,
    "TPU": 0.040, "PEEK": 0.020, "PPS": 0.018,
}

# Reference temperatures for viscosity measurements [°C]
T_REF: dict[str, float] = {
    "ABS": 230, "PC": 300, "PP": 230, "PA6": 240, "PA66": 280,
    "POM": 200, "PBT": 250, "PET": 265, "PMMA": 240, "PS": 220,
    "TPU": 210, "PEEK": 380, "PPS": 320,
}


@dataclass
class RheologyProps:
    """Power-law viscosity model parameters."""
    n: float          # Power-law index (0–1); lower = more shear-thinning
    K: float          # Consistency index [Pa·sⁿ]
    beta: float       # Temperature sensitivity [1/°C]
    T_ref_C: float    # Reference temperature [°C]

    def eta(self, gamma_dot: float, T_C: float) -> float:
        """
        Apparent viscosity at shear rate gamma_dot [s⁻¹] and temperature T_C [°C].
        η(γ̇, T) = K · γ̇^(n-1) · exp(-β(T - T_ref))
        """
        if gamma_dot <= 0:
            gamma_dot = 1.0
        visc = self.K * (gamma_dot ** (self.n - 1)) * math.exp(-self.beta * (T_C - self.T_ref_C))
        return max(visc, 1.0)  # floor at 1 Pa·s

    @classmethod
    def from_polymer(cls, polymer: str) -> "RheologyProps":
        rh = RHEOLOGY_DEFAULTS.get(polymer, RHEOLOGY_DEFAULTS["ABS"])
        return cls(
            n=rh["n"],
            K=rh["K"],
            beta=TEMP_SENSITIVITY.get(polymer, 0.035),
            T_ref_C=T_REF.get(polymer, 230),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Geometry descriptors
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CavityGeometry:
    """Simplified mold cavity geometry."""
    type: str                  # "plate" | "disc" | "box" | "custom"
    length_mm: float           # longest flow path dimension
    width_mm: float            # width (or diameter for disc)
    wall_thickness_mm: float   # dominant wall thickness
    # Optional runner
    runner_length_mm: float  = 80.0
    runner_diameter_mm: float = 8.0
    n_cavities: int           = 1
    projected_area_cm2: Optional[float] = None  # if provided, used for clamp force

    @property
    def _proj_area_cm2(self) -> float:
        if self.projected_area_cm2:
            return self.projected_area_cm2
        if self.type == "disc":
            R = self.width_mm / 2 / 10  # → cm
            return math.pi * R ** 2
        return (self.length_mm / 10) * (self.width_mm / 10)  # → cm²

    @property
    def flow_path_mm(self) -> float:
        """Approximate flow path for a center-gated part."""
        if self.type == "disc":
            return self.width_mm / 2
        return self.length_mm


# ─────────────────────────────────────────────────────────────────────────────
# Pressure calculations
# ─────────────────────────────────────────────────────────────────────────────

def apparent_shear_rate(
    cavity: CavityGeometry,
    fill_time_s: float,
) -> float:
    """
    Estimate apparent wall shear rate in the cavity thin-walled channel.
    γ̇_app = 6Q / (w·h²)  for a rectangular channel
    where Q = V_cavity / t_fill
    """
    h_m = cavity.wall_thickness_mm / 1000          # thickness [m]
    w_m = cavity.width_mm / 1000                   # width [m]
    L_m = cavity.flow_path_mm / 1000               # flow length [m]
    V_m3 = L_m * w_m * h_m * cavity.n_cavities     # rough cavity volume
    Q_m3s = V_m3 / fill_time_s
    gamma_dot = 6 * Q_m3s / (w_m * h_m ** 2)
    return max(gamma_dot, 1.0)


def fill_pressure_rectangular(
    cavity: CavityGeometry,
    fill_time_s: float,
    melt_temp_C: float,
    rh: RheologyProps,
) -> dict:
    """
    Hele-Shaw pressure drop for a thin rectangular cavity.
    ΔP_cavity = 2 · L · η · (6Q / (wh²))^n  ·  (n+1)/n  / h
    (Power-law, Hele-Shaw approximation)

    Ref: Osswald & Hernandez-Ortiz, "Polymer Processing", Hanser 2006.
    """
    h_m = cavity.wall_thickness_mm / 1000
    w_m = cavity.width_mm / 1000
    L_m = cavity.flow_path_mm / 1000

    V_m3 = L_m * w_m * h_m
    Q_m3s = V_m3 / fill_time_s * cavity.n_cavities

    gamma_dot = 6 * Q_m3s / (w_m * h_m ** 2)
    gamma_dot_corrected = gamma_dot * (3 * rh.n + 1) / (4 * rh.n)  # Rabinowitsch

    eta = rh.eta(gamma_dot_corrected, melt_temp_C)

    # ΔP = 2L · η · γ̇_corrected / h  (simplified)
    dP_cavity_Pa = 2 * L_m * eta * gamma_dot_corrected / h_m
    dP_cavity_MPa = dP_cavity_Pa / 1e6

    return {
        "cavity_pressure_MPa": round(dP_cavity_MPa, 2),
        "apparent_shear_rate_s": round(gamma_dot, 1),
        "corrected_shear_rate_s": round(gamma_dot_corrected, 1),
        "melt_viscosity_Pas": round(eta, 1),
        "flow_path_mm": round(cavity.flow_path_mm, 1),
    }


def runner_pressure_drop(
    runner_length_mm: float,
    runner_diameter_mm: float,
    flow_rate_m3s: float,
    melt_temp_C: float,
    rh: RheologyProps,
) -> float:
    """
    Pressure drop in a circular runner using power-law Hagen-Poiseuille.
    ΔP = 2L · η · (4Q / (π·R³)) / R
    Returns [MPa].
    """
    R_m = runner_diameter_mm / 2 / 1000
    L_m = runner_length_mm / 1000
    gamma_runner = 4 * flow_rate_m3s / (math.pi * R_m ** 3)
    gamma_runner_corrected = gamma_runner * (3 * rh.n + 1) / (4 * rh.n)
    eta = rh.eta(gamma_runner_corrected, melt_temp_C)
    dP_Pa = 2 * L_m * eta * gamma_runner_corrected / R_m
    return round(dP_Pa / 1e6, 2)


def total_injection_pressure(
    cavity: CavityGeometry,
    fill_time_s: float,
    melt_temp_C: float,
    rh: RheologyProps,
    safety_factor: float = 1.3,
) -> dict:
    """
    Estimate total injection pressure = cavity fill ΔP + runner ΔP.
    Includes a safety factor (default 1.3 for typical gate/flow front losses).
    """
    fill = fill_pressure_rectangular(cavity, fill_time_s, melt_temp_C, rh)

    # Estimate runner flow rate
    h_m = cavity.wall_thickness_mm / 1000
    w_m = cavity.width_mm / 1000
    L_m = cavity.flow_path_mm / 1000
    V_m3 = L_m * w_m * h_m * cavity.n_cavities
    Q = V_m3 / fill_time_s

    runner_dP = runner_pressure_drop(
        cavity.runner_length_mm, cavity.runner_diameter_mm,
        Q, melt_temp_C, rh
    )

    total = (fill["cavity_pressure_MPa"] + runner_dP) * safety_factor

    return {
        **fill,
        "runner_pressure_MPa":  runner_dP,
        "total_injection_pressure_MPa": round(total, 2),
        "safety_factor": safety_factor,
        "recommended_machine_pressure_MPa": round(total * 1.15, 2),
    }


def clamp_force(
    cavity: CavityGeometry,
    cavity_pressure_MPa: float,
    safety_factor: float = 1.1,
) -> dict:
    """
    Minimum clamping force = cavity pressure × projected area × n_cavities × safety.
    Returns value in tonnes and kN.
    """
    A_cm2 = cavity._proj_area_cm2 * cavity.n_cavities
    A_m2  = A_cm2 / 1e4
    F_N   = cavity_pressure_MPa * 1e6 * A_m2 * safety_factor
    F_kN  = F_N / 1000
    F_ton = F_kN / 9.81

    return {
        "projected_area_cm2": round(A_cm2, 2),
        "clamp_force_kN":     round(F_kN, 1),
        "clamp_force_tonnes": round(F_ton, 1),
        "safety_factor":      safety_factor,
    }


def optimum_fill_time(
    cavity: CavityGeometry,
    melt_temp_C: float,
    rh: RheologyProps,
    target_shear_rate_s: float = 5000,
) -> float:
    """
    Back-calculate fill time that yields approximately the target shear rate.
    Useful for recommending injection speed to operators.
    """
    h_m = cavity.wall_thickness_mm / 1000
    w_m = cavity.width_mm / 1000
    L_m = cavity.flow_path_mm / 1000
    V_m3 = L_m * w_m * h_m * cavity.n_cavities

    # γ̇ = 6Q/(w·h²) and Q = V/t  →  t = 6V / (γ̇ · w · h²)
    t_opt = 6 * V_m3 / (target_shear_rate_s * w_m * h_m ** 2)
    return max(round(t_opt, 2), 0.3)
