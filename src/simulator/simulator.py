"""
src/simulator/simulator.py
──────────────────────────
Main simulation orchestrator.  Assembles thermal, rheological, and defect
modules into a single `run_simulation()` call that the LLM agent invokes.

Input  (SimulationInput dataclass or dict):
  - grade data (from knowledge base)
  - processing parameters (melt temp, mold temp, injection pressure, …)
  - mold/part geometry (dimensions, type)

Output (SimulationResult dataclass or dict):
  - cooling time, cycle time
  - fill pressure, clamp force
  - defect risk assessment for all defects
  - overall status: OK / WARNING / CRITICAL
  - human-readable summary in Chinese
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import json

from .thermal   import ThermalMaterialProps, cooling_time_plate, cooling_time_cylinder, estimate_cycle_time
from .rheology  import RheologyProps, CavityGeometry, total_injection_pressure, clamp_force, optimum_fill_time
from .defects   import ProcessingWindow, check_flash, check_short_shot, check_sink_marks, check_warpage, check_burn_marks, check_silver_streaks, inverse_diagnose


# ─────────────────────────────────────────────────────────────────────────────
# Input / Output data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SimulationInput:
    # Material
    grade_data: dict                          # full grade JSON from DB

    # Processing parameters (set by user / agent)
    melt_temp_C: float
    mold_temp_C: float
    injection_pressure_MPa: float            # target injection pressure
    packing_pressure_MPa: float              # = 50–80% of injection pressure
    fill_time_s: float = 1.5                 # injection fill time

    # Part / mold geometry
    part_geometry: str = "plate"             # "plate" | "disc" | "box"
    wall_thickness_mm: float = 2.5
    part_length_mm: float = 100.0
    part_width_mm: float = 60.0
    runner_length_mm: float = 80.0
    runner_diameter_mm: float = 8.0
    n_cavities: int = 1
    machine_clamp_kN: Optional[float] = None  # machine clamping force

    # Drying info
    drying_done: bool = True
    drying_temp_C: Optional[float] = None
    drying_time_h: Optional[float] = None

    @classmethod
    def from_dict(cls, d: dict) -> "SimulationInput":
        grade = d.get("grade_data", {})
        return cls(
            grade_data              = grade,
            melt_temp_C             = float(d.get("melt_temp_C", 230)),
            mold_temp_C             = float(d.get("mold_temp_C", 60)),
            injection_pressure_MPa  = float(d.get("injection_pressure_MPa", 100)),
            packing_pressure_MPa    = float(d.get("packing_pressure_MPa",
                                                   float(d.get("injection_pressure_MPa", 100)) * 0.6)),
            fill_time_s             = float(d.get("fill_time_s", 1.5)),
            part_geometry           = d.get("part_geometry", "plate"),
            wall_thickness_mm       = float(d.get("wall_thickness_mm", 2.5)),
            part_length_mm          = float(d.get("part_length_mm", 100)),
            part_width_mm           = float(d.get("part_width_mm", 60)),
            runner_length_mm        = float(d.get("runner_length_mm", 80)),
            runner_diameter_mm      = float(d.get("runner_diameter_mm", 8)),
            n_cavities              = int(d.get("n_cavities", 1)),
            machine_clamp_kN        = d.get("machine_clamp_kN"),
            drying_done             = bool(d.get("drying_done", True)),
            drying_temp_C           = d.get("drying_temp_C"),
            drying_time_h           = d.get("drying_time_h"),
        )


@dataclass
class SimulationResult:
    # Thermal
    cooling_time_s: float = 0.0
    cycle_time_s: float = 0.0
    throughput_per_hour: float = 0.0
    ejection_temp_C: float = 0.0

    # Rheology
    fill_pressure_MPa: float = 0.0
    total_pressure_MPa: float = 0.0
    optimal_fill_time_s: float = 0.0
    clamp_force_kN: float = 0.0
    clamp_force_tonnes: float = 0.0
    melt_viscosity_Pas: float = 0.0
    shear_rate_s: float = 0.0

    # Defects
    defects: list = field(default_factory=list)   # list of defect dicts

    # Overall
    status: str = "OK"        # "OK" | "WARNING" | "CRITICAL"
    warnings: list = field(default_factory=list)
    summary_zh: str = ""      # Chinese-language summary for display

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Main simulation function
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(inp: SimulationInput) -> SimulationResult:
    """
    Execute the full injection molding simulation.
    Returns a SimulationResult with thermal, rheological and defect data.
    """
    grade   = inp.grade_data
    polymer = grade.get("polymer", "ABS")

    # ── Build material models ─────────────────────────────────────────────────
    therm = ThermalMaterialProps.from_grade_data(grade)
    rh    = RheologyProps.from_polymer(polymer)
    win   = ProcessingWindow.from_grade(grade)

    # ── Build cavity geometry ─────────────────────────────────────────────────
    cavity = CavityGeometry(
        type              = inp.part_geometry,
        length_mm         = inp.part_length_mm,
        width_mm          = inp.part_width_mm,
        wall_thickness_mm = inp.wall_thickness_mm,
        runner_length_mm  = inp.runner_length_mm,
        runner_diameter_mm= inp.runner_diameter_mm,
        n_cavities        = inp.n_cavities,
    )

    # ── Thermal analysis ──────────────────────────────────────────────────────
    if inp.part_geometry == "disc":
        ct_result = cooling_time_cylinder(
            outer_diameter_mm = inp.part_width_mm,
            melt_temp_C       = inp.melt_temp_C,
            mold_temp_C       = inp.mold_temp_C,
            props             = therm,
        )
    else:
        ct_result = cooling_time_plate(
            wall_thickness_mm = inp.wall_thickness_mm,
            melt_temp_C       = inp.melt_temp_C,
            mold_temp_C       = inp.mold_temp_C,
            props             = therm,
        )
    ct = ct_result["cooling_time_s"]
    cycle = estimate_cycle_time(ct, inp.fill_time_s)

    # ── Rheological analysis ──────────────────────────────────────────────────
    opt_fill_t = optimum_fill_time(cavity, inp.melt_temp_C, rh)
    press = total_injection_pressure(cavity, inp.fill_time_s, inp.melt_temp_C, rh)
    cf    = clamp_force(cavity, press["cavity_pressure_MPa"])

    # ── Defect assessment ─────────────────────────────────────────────────────
    p_drying = grade.get("processing", {})
    defects = [
        check_flash(
            inp.melt_temp_C, inp.injection_pressure_MPa,
            inp.machine_clamp_kN, cf["clamp_force_kN"], win,
        ),
        check_short_shot(
            inp.melt_temp_C, inp.injection_pressure_MPa,
            press["total_injection_pressure_MPa"], win,
            inp.wall_thickness_mm, cavity.flow_path_mm,
        ),
        check_sink_marks(
            inp.wall_thickness_mm, ct, inp.packing_pressure_MPa, inp.mold_temp_C, win,
        ),
        check_warpage(
            inp.mold_temp_C, inp.wall_thickness_mm, win, polymer, ct,
        ),
        check_burn_marks(
            None, inp.melt_temp_C, win, press.get("corrected_shear_rate_s", 0),
        ),
        check_silver_streaks(
            inp.drying_done, inp.drying_temp_C, inp.drying_time_h,
            p_drying.get("drying_temp_C"), p_drying.get("drying_time_h"),
            inp.melt_temp_C, win,
        ),
    ]

    # Pass all defects so the UI radar chart can render properly (requires all variables)
    significant = defects

    # ── Overall status ────────────────────────────────────────────────────────
    max_risk = max((d["risk"] for d in defects), default=0)
    if   max_risk >= 0.75: status = "CRITICAL"
    elif max_risk >= 0.40: status = "WARNING"
    else:                  status = "OK"

    warnings = [f"[{d['severity'].upper()}] {d['defect']}: 风险 {d['risk']*100:.0f}%"
                for d in significant if d["risk"] > 0.15]

    # ── Assemble result ───────────────────────────────────────────────────────
    res = SimulationResult(
        cooling_time_s      = ct,
        cycle_time_s        = cycle["total_cycle_s"],
        throughput_per_hour = cycle["throughput_parts_per_hour"],
        ejection_temp_C     = ct_result["ejection_temp_C"],
        fill_pressure_MPa   = press["cavity_pressure_MPa"],
        total_pressure_MPa  = press["total_injection_pressure_MPa"],
        optimal_fill_time_s = opt_fill_t,
        clamp_force_kN      = cf["clamp_force_kN"],
        clamp_force_tonnes  = cf["clamp_force_tonnes"],
        melt_viscosity_Pas  = press.get("melt_viscosity_Pas", 0),
        shear_rate_s        = press.get("apparent_shear_rate_s", 0),
        defects             = significant,
        status              = status,
        warnings            = warnings,
        summary_zh          = _make_summary(inp, ct, cycle, press, cf, significant, status),
    )
    return res


def run_simulation_from_dict(d: dict) -> dict:
    """JSON-serializable wrapper for LLM tool calls."""
    inp = SimulationInput.from_dict(d)
    res = run_simulation(inp)
    return res.to_dict()


def inverse_diagnose_from_text(defect_description: str) -> dict:
    """Wrapper exposed to LLM agent for defect-based parameter adjustment."""
    return inverse_diagnose(defect_description)


# ─────────────────────────────────────────────────────────────────────────────
# Summary formatter
# ─────────────────────────────────────────────────────────────────────────────

def _make_summary(inp, ct, cycle, press, cf, defects, status) -> str:
    grade_name = inp.grade_data.get("grade_name", "未知牌号")
    lines = [
        f"## 注塑模拟报告 — {grade_name}",
        f"**工艺条件**: 熔体温度 {inp.melt_temp_C}°C | 模温 {inp.mold_temp_C}°C | 注射压力 {inp.injection_pressure_MPa} MPa",
        f"**制品几何**: {inp.part_geometry} | 壁厚 {inp.wall_thickness_mm}mm | {inp.part_length_mm}×{inp.part_width_mm}mm | {inp.n_cavities} 模腔",
        "",
        "### 热分析",
        f"- 冷却时间：**{ct}s**（顶出温度 {cycle.get('cooling_s', ct)}s）",
        f"- 成型周期：**{cycle['total_cycle_s']}s**（产能约 {cycle['throughput_parts_per_hour']} 件/小时）",
        "",
        "### 流动分析",
        f"- 型腔填充压力：{press['cavity_pressure_MPa']} MPa",
        f"- 总注射压力（含流道）：{press['total_injection_pressure_MPa']} MPa",
        f"- 推荐注射时间：{press.get('fill_s', inp.fill_time_s)} → 最优填充时间 ~{inp.fill_time_s}s",
        f"- 所需最小锁模力：**{cf['clamp_force_kN']} kN ({cf['clamp_force_tonnes']} 吨)**",
        "",
        "### 缺陷风险评估",
    ]
    if defects:
        for d in defects:
            emoji = "🔴" if d["severity"] == "critical" else "🟡" if d["severity"] == "high" else "🟢"
            lines.append(f"{emoji} **{d['defect']}**: 风险 {d['risk']*100:.0f}% ({d['severity']})")
            for c in d["root_causes"]:
                lines.append(f"  - 原因：{c}")
            for s in d["suggestions"][:2]:
                lines.append(f"  - 建议：{s}")
    else:
        lines.append("✅ 未检测到显著缺陷风险。")

    lines += ["", f"### 综合判断：**{status}**"]
    return "\n".join(lines)
