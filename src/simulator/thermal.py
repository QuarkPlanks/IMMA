"""
src/simulator/thermal.py
────────────────────────
Thermal analysis for injection molding:
  - Cooling time (Janeschitz-Kriegl 1D model)
  - Mold temperature distribution (simplified)
  - Thermal diffusivity estimation from material properties
"""

import math
from dataclasses import dataclass
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ThermalMaterialProps:
    """Thermal properties needed for cooling calculations."""
    Cp_J_kgK: float          # Specific heat capacity [J/(kg·K)]
    density_kg_m3: float     # Density [kg/m³]
    k_W_mK: float            # Thermal conductivity of polymer [W/(m·K)]
    Tg_or_Tm_C: float        # Glass transition (amorphous) or melting (semi-cryst.) [°C]
    is_semicrystalline: bool = False

    @property
    def alpha(self) -> float:
        """Thermal diffusivity [m²/s]."""
        return self.k_W_mK / (self.density_kg_m3 * self.Cp_J_kgK)

    @classmethod
    def from_grade_data(cls, grade: dict) -> "ThermalMaterialProps":
        """Construct from a grade JSON dict, using defaults where missing."""
        thermal    = grade.get("thermal", {})
        mechanical = grade.get("mechanical", {})
        polymer    = grade.get("polymer", "ABS")

        defaults = _polymer_thermal_defaults(polymer)

        Cp      = thermal.get("Cp_J_kgK",                  defaults["Cp_J_kgK"])
        density = mechanical.get("density_g_cm3", defaults["density_g_cm3"]) * 1000  # → kg/m³
        k       = thermal.get("thermal_conductivity_W_mK", defaults["k_W_mK"])
        Tg      = thermal.get("Tg_C", thermal.get("HDT_C", defaults["Tg_C"]))
        Tm      = thermal.get("Tm_C", None)
        is_sc   = Tm is not None and Tm > Tg + 30

        return cls(
            Cp_J_kgK=Cp,
            density_kg_m3=density,
            k_W_mK=k,
            Tg_or_Tm_C=Tm if is_sc else Tg,
            is_semicrystalline=is_sc,
        )


def _polymer_thermal_defaults(polymer: str) -> dict:
    """Literature defaults for common polymers."""
    table = {
        "ABS":  {"Cp_J_kgK": 1400, "density_g_cm3": 1.05, "k_W_mK": 0.17, "Tg_C": 105},
        "PC":   {"Cp_J_kgK": 1200, "density_g_cm3": 1.20, "k_W_mK": 0.20, "Tg_C": 148},
        "PP":   {"Cp_J_kgK": 1950, "density_g_cm3": 0.91, "k_W_mK": 0.22, "Tg_C": 165},
        "PA6":  {"Cp_J_kgK": 1680, "density_g_cm3": 1.13, "k_W_mK": 0.25, "Tg_C": 220},
        "PA66": {"Cp_J_kgK": 1680, "density_g_cm3": 1.14, "k_W_mK": 0.26, "Tg_C": 260},
        "POM":  {"Cp_J_kgK": 1460, "density_g_cm3": 1.41, "k_W_mK": 0.31, "Tg_C": 175},
        "PBT":  {"Cp_J_kgK": 1250, "density_g_cm3": 1.31, "k_W_mK": 0.21, "Tg_C": 225},
        "PET":  {"Cp_J_kgK": 1250, "density_g_cm3": 1.37, "k_W_mK": 0.24, "Tg_C": 260},
        "PMMA": {"Cp_J_kgK": 1450, "density_g_cm3": 1.19, "k_W_mK": 0.19, "Tg_C": 105},
        "PS":   {"Cp_J_kgK": 1300, "density_g_cm3": 1.05, "k_W_mK": 0.17, "Tg_C":  95},
        "TPU":  {"Cp_J_kgK": 1750, "density_g_cm3": 1.20, "k_W_mK": 0.22, "Tg_C": 180},
        "PEEK": {"Cp_J_kgK": 1320, "density_g_cm3": 1.30, "k_W_mK": 0.25, "Tg_C": 340},
        "PPS":  {"Cp_J_kgK": 1090, "density_g_cm3": 1.36, "k_W_mK": 0.29, "Tg_C": 285},
    }
    return table.get(polymer, {"Cp_J_kgK": 1400, "density_g_cm3": 1.10, "k_W_mK": 0.20, "Tg_C": 120})


# ─────────────────────────────────────────────────────────────────────────────
# Cooling time — Janeschitz-Kriegl plate model (standard injection molding)
# ─────────────────────────────────────────────────────────────────────────────

def cooling_time_plate(
    wall_thickness_mm: float,
    melt_temp_C: float,
    mold_temp_C: float,
    props: ThermalMaterialProps,
    ejection_temp_C: Optional[float] = None,
) -> dict:
    """
    Compute cooling time for a flat-plate part using the 1D Fourier solution.

    Formula (Janeschitz-Kriegl):
        t_c = (s² / π²α) × ln(4/π × (T_m - T_w) / (T_e - T_w))

    where s = half wall thickness, α = thermal diffusivity,
    T_m = melt temp, T_w = mold temp, T_e = ejection temp.

    The ejection temp is taken as:
      - For amorphous polymers: T_g - 5°C (just below Tg)
      - For semi-crystalline:   T_m_crystal - 20°C

    Returns
    -------
    dict with keys:
        cooling_time_s, alpha_m2s, ejection_temp_C, half_thickness_mm,
        formula_description
    """
    s_m = (wall_thickness_mm / 2.0) / 1000.0  # half thickness [m]
    alpha = props.alpha                         # m²/s

    if ejection_temp_C is None:
        ejection_temp_C = props.Tg_or_Tm_C - (20 if props.is_semicrystalline else 5)

    # Validate temperature ordering: T_melt > T_eject > T_mold
    if melt_temp_C <= ejection_temp_C:
        melt_temp_C = ejection_temp_C + 50  # physical safety clamp
    if ejection_temp_C <= mold_temp_C:
        ejection_temp_C = mold_temp_C + 10

    ratio = (melt_temp_C - mold_temp_C) / (ejection_temp_C - mold_temp_C)
    if ratio <= 1:
        ratio = 1.001  # guard against log(≤0)

    t_c = (s_m ** 2 / (math.pi ** 2 * alpha)) * math.log((4.0 / math.pi) * ratio)

    return {
        "cooling_time_s":    round(t_c, 2),
        "alpha_m2s":         alpha,
        "ejection_temp_C":   round(ejection_temp_C, 1),
        "half_thickness_mm": wall_thickness_mm / 2.0,
        "formula":           "Janeschitz-Kriegl 1D plate model",
    }


def cooling_time_cylinder(
    outer_diameter_mm: float,
    melt_temp_C: float,
    mold_temp_C: float,
    props: ThermalMaterialProps,
    ejection_temp_C: Optional[float] = None,
) -> dict:
    """
    Cooling time for a solid cylindrical cross-section.
    Uses the first-term approximation of the Fourier series for a cylinder.

    Formula:  t_c = R² / (5.78 α) × ln(1.602 × (T_m - T_w) / (T_e - T_w))

    where R = radius of the cylinder.
    """
    R_m = (outer_diameter_mm / 2.0) / 1000.0
    alpha = props.alpha

    if ejection_temp_C is None:
        ejection_temp_C = props.Tg_or_Tm_C - (20 if props.is_semicrystalline else 5)

    if melt_temp_C <= ejection_temp_C:
        melt_temp_C = ejection_temp_C + 50
    if ejection_temp_C <= mold_temp_C:
        ejection_temp_C = mold_temp_C + 10

    ratio = (melt_temp_C - mold_temp_C) / (ejection_temp_C - mold_temp_C)
    if ratio <= 1:
        ratio = 1.001

    t_c = (R_m ** 2 / (5.78 * alpha)) * math.log(1.602 * ratio)

    return {
        "cooling_time_s":  round(t_c, 2),
        "alpha_m2s":       alpha,
        "ejection_temp_C": round(ejection_temp_C, 1),
        "radius_mm":       outer_diameter_mm / 2.0,
        "formula":         "Cylinder Fourier first-term approximation",
    }


def estimate_cycle_time(
    cooling_time_s: float,
    fill_time_s: float = 1.5,
    packing_time_s: float = 5.0,
    mold_open_close_s: float = 3.0,
) -> dict:
    """Estimate total injection molding cycle time."""
    total = cooling_time_s + fill_time_s + packing_time_s + mold_open_close_s
    return {
        "cooling_s":       round(cooling_time_s, 2),
        "fill_s":          fill_time_s,
        "packing_s":       packing_time_s,
        "mold_open_close_s": mold_open_close_s,
        "total_cycle_s":   round(total, 2),
        "throughput_parts_per_hour": round(3600 / total, 1),
    }
