"""
src/simulator/defects.py
────────────────────────
Rule-based defect diagnosis engine for injection molding.

Each rule evaluates a set of input conditions and returns:
  {
    "defect":       str,           # defect name
    "risk":         float,         # 0.0–1.0
    "severity":     str,           # "low" | "medium" | "high" | "critical"
    "root_causes":  list[str],
    "suggestions":  list[str],
  }

The engine also supports inverse diagnosis: given a reported defect,
it suggests parameter adjustments as a JSON diff (delta values).
"""

from dataclasses import dataclass, field
from typing import Optional
import math


# ─────────────────────────────────────────────────────────────────────────────
# Processing window
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProcessingWindow:
    """Recommended processing window from grade database."""
    melt_temp_min_C: float
    melt_temp_max_C: float
    mold_temp_min_C: float
    mold_temp_max_C: float
    injection_pressure_MPa_max: float = 140.0
    back_pressure_MPa: float = 5.0
    shrinkage_pct_min: float = 0.3
    shrinkage_pct_max: float = 1.5

    @classmethod
    def from_grade(cls, grade: dict) -> "ProcessingWindow":
        p = grade.get("processing", {})
        polymer = grade.get("polymer", "ABS")
        defaults = _window_defaults(polymer)

        def g(key, fallback):
            return p.get(key, defaults.get(key, fallback))

        return cls(
            melt_temp_min_C           = g("melt_temp_min_C", 200),
            melt_temp_max_C           = g("melt_temp_max_C", 280),
            mold_temp_min_C           = g("mold_temp_min_C",  40),
            mold_temp_max_C           = g("mold_temp_max_C",  80),
            injection_pressure_MPa_max= g("injection_pressure_MPa_max", 140),
            back_pressure_MPa         = g("back_pressure_MPa", 5),
            shrinkage_pct_min         = g("shrinkage_pct_min", 0.3),
            shrinkage_pct_max         = g("shrinkage_pct_max", 1.5),
        )


def _window_defaults(polymer: str) -> dict:
    table = {
        "ABS":  {"melt_temp_min_C": 210, "melt_temp_max_C": 260, "mold_temp_min_C": 40,  "mold_temp_max_C": 80,  "shrinkage_pct_min": 0.4, "shrinkage_pct_max": 0.9},
        "PC":   {"melt_temp_min_C": 270, "melt_temp_max_C": 320, "mold_temp_min_C": 70,  "mold_temp_max_C": 120, "shrinkage_pct_min": 0.5, "shrinkage_pct_max": 0.7},
        "PP":   {"melt_temp_min_C": 200, "melt_temp_max_C": 280, "mold_temp_min_C": 20,  "mold_temp_max_C": 60,  "shrinkage_pct_min": 1.0, "shrinkage_pct_max": 2.5},
        "PA6":  {"melt_temp_min_C": 230, "melt_temp_max_C": 270, "mold_temp_min_C": 40,  "mold_temp_max_C": 80,  "shrinkage_pct_min": 0.5, "shrinkage_pct_max": 2.0},
        "PA66": {"melt_temp_min_C": 265, "melt_temp_max_C": 310, "mold_temp_min_C": 40,  "mold_temp_max_C": 80,  "shrinkage_pct_min": 0.5, "shrinkage_pct_max": 2.0},
        "POM":  {"melt_temp_min_C": 180, "melt_temp_max_C": 220, "mold_temp_min_C": 50,  "mold_temp_max_C": 90,  "shrinkage_pct_min": 1.5, "shrinkage_pct_max": 3.5},
        "PBT":  {"melt_temp_min_C": 240, "melt_temp_max_C": 275, "mold_temp_min_C": 50,  "mold_temp_max_C": 80,  "shrinkage_pct_min": 0.8, "shrinkage_pct_max": 1.8},
        "PMMA": {"melt_temp_min_C": 200, "melt_temp_max_C": 250, "mold_temp_min_C": 40,  "mold_temp_max_C": 80,  "shrinkage_pct_min": 0.2, "shrinkage_pct_max": 0.8},
        "PS":   {"melt_temp_min_C": 180, "melt_temp_max_C": 280, "mold_temp_min_C": 20,  "mold_temp_max_C": 60,  "shrinkage_pct_min": 0.3, "shrinkage_pct_max": 0.8},
        "TPU":  {"melt_temp_min_C": 190, "melt_temp_max_C": 230, "mold_temp_min_C": 20,  "mold_temp_max_C": 50,  "shrinkage_pct_min": 0.5, "shrinkage_pct_max": 2.0},
        "PEEK": {"melt_temp_min_C": 360, "melt_temp_max_C": 400, "mold_temp_min_C": 160, "mold_temp_max_C": 200, "shrinkage_pct_min": 1.0, "shrinkage_pct_max": 1.5},
        "PPS":  {"melt_temp_min_C": 300, "melt_temp_max_C": 350, "mold_temp_min_C": 120, "mold_temp_max_C": 180, "shrinkage_pct_min": 0.5, "shrinkage_pct_max": 1.0},
    }
    return table.get(polymer, {"melt_temp_min_C": 200, "melt_temp_max_C": 280,
                                 "mold_temp_min_C": 40,  "mold_temp_max_C": 80,
                                 "shrinkage_pct_min": 0.5, "shrinkage_pct_max": 1.5})


# ─────────────────────────────────────────────────────────────────────────────
# Individual defect checkers
# ─────────────────────────────────────────────────────────────────────────────

def _risk(value: float) -> str:
    if value < 0.2:   return "low"
    if value < 0.5:   return "medium"
    if value < 0.75:  return "high"
    return "critical"


def check_flash(
    melt_temp_C: float,
    injection_pressure_MPa: float,
    actual_clamp_force_kN: Optional[float],
    required_clamp_kN: float,
    window: ProcessingWindow,
) -> dict:
    """Flash = material escaping at parting line."""
    causes = []
    score = 0.0

    # Over-temperature
    if melt_temp_C > window.melt_temp_max_C:
        excess = (melt_temp_C - window.melt_temp_max_C) / 20
        score += min(excess * 0.35, 0.35)
        causes.append(f"熔体温度 {melt_temp_C}°C 超出推荐上限 {window.melt_temp_max_C}°C，熔体粘度过低")

    # Over-pressure
    if injection_pressure_MPa > window.injection_pressure_MPa_max:
        excess = (injection_pressure_MPa - window.injection_pressure_MPa_max) / window.injection_pressure_MPa_max
        score += min(excess * 0.40, 0.40)
        causes.append(f"注射压力 {injection_pressure_MPa:.0f} MPa 超出建议最大值 {window.injection_pressure_MPa_max:.0f} MPa")

    # Insufficient clamp
    if actual_clamp_force_kN and actual_clamp_force_kN < required_clamp_kN:
        deficit = (required_clamp_kN - actual_clamp_force_kN) / required_clamp_kN
        score += min(deficit * 0.50, 0.50)
        causes.append(f"机器锁模力 {actual_clamp_force_kN:.0f} kN 不足，所需 {required_clamp_kN:.0f} kN")

    score = min(score, 1.0)
    suggestions = []
    if score > 0.1:
        if melt_temp_C > window.melt_temp_max_C:
            suggestions.append(f"将熔体温度降低至 {window.melt_temp_max_C - 10}–{window.melt_temp_max_C}°C")
        if injection_pressure_MPa > window.injection_pressure_MPa_max:
            suggestions.append("降低保压压力或注射压力 5–10%")
        if actual_clamp_force_kN and actual_clamp_force_kN < required_clamp_kN:
            suggestions.append(f"更换锁模力 ≥ {required_clamp_kN*1.1:.0f} kN 的注塑机，或减少模腔数量")

    return {"defect": "飞边 (Flash)", "risk": round(score, 2),
            "severity": _risk(score), "root_causes": causes, "suggestions": suggestions}


def check_short_shot(
    melt_temp_C: float,
    injection_pressure_MPa: float,
    required_pressure_MPa: float,
    window: ProcessingWindow,
    wall_thickness_mm: float = 2.0,
    flow_path_mm: float = 100.0,
) -> dict:
    causes = []
    score = 0.0

    # Under-temperature
    if melt_temp_C < window.melt_temp_min_C:
        deficit = (window.melt_temp_min_C - melt_temp_C) / 30
        score += min(deficit * 0.35, 0.35)
        causes.append(f"熔体温度 {melt_temp_C}°C 低于推荐下限 {window.melt_temp_min_C}°C，熔体流动性不足")

    # Insufficient pressure
    if injection_pressure_MPa < required_pressure_MPa:
        deficit = (required_pressure_MPa - injection_pressure_MPa) / required_pressure_MPa
        score += min(deficit * 0.45, 0.45)
        causes.append(f"注射压力 {injection_pressure_MPa:.0f} MPa 低于计算所需 {required_pressure_MPa:.0f} MPa")

    # Thin walls + long flow path → L/t ratio risk
    lt_ratio = flow_path_mm / wall_thickness_mm
    if lt_ratio > 200:
        score += min((lt_ratio - 200) / 200 * 0.25, 0.25)
        causes.append(f"流动比 L/t ≈ {lt_ratio:.0f} 过大，难以充填")

    score = min(score, 1.0)
    suggestions = []
    if score > 0.1:
        if melt_temp_C < window.melt_temp_min_C:
            suggestions.append(f"将熔体温度提高至 {window.melt_temp_min_C}–{window.melt_temp_min_C + 15}°C")
        if injection_pressure_MPa < required_pressure_MPa:
            suggestions.append(f"将注射压力提高至 {required_pressure_MPa * 1.1:.0f} MPa")
        if lt_ratio > 200:
            suggestions.append("增加壁厚，或在长流程末端增设溢料槽/排气口")

    return {"defect": "短射 (Short Shot)", "risk": round(score, 2),
            "severity": _risk(score), "root_causes": causes, "suggestions": suggestions}


def check_sink_marks(
    wall_thickness_mm: float,
    cooling_time_s: float,
    packing_pressure_MPa: float,
    mold_temp_C: float,
    window: ProcessingWindow,
) -> dict:
    causes = []
    score = 0.0

    # Thick walls need longer cooling; if CT is too short, sink marks appear
    # Rule of thumb: CT should be > 0.7 × s² [s, mm] (empirical)
    required_ct = 0.7 * wall_thickness_mm ** 2 / 10  # crude estimate [s]
    if cooling_time_s < required_ct * 0.8:
        score += 0.35
        causes.append(f"冷却时间 {cooling_time_s:.1f}s 可能不足（壁厚 {wall_thickness_mm}mm 建议 ≥ {required_ct:.1f}s）")

    # Low packing pressure → can't compensate shrinkage
    nominal_pack = 50.0
    if packing_pressure_MPa < nominal_pack * 0.6:
        score += 0.30
        causes.append(f"保压压力 {packing_pressure_MPa:.0f} MPa 过低，无法充分补缩")

    # Thick walls inherently prone
    if wall_thickness_mm > 4.0:
        score += 0.20
        causes.append(f"壁厚 {wall_thickness_mm}mm 较大，收缩差异明显")

    score = min(score, 1.0)
    suggestions = []
    if score > 0.1:
        if cooling_time_s < required_ct * 0.8:
            suggestions.append(f"延长冷却时间至 {required_ct:.1f}s 以上")
        if packing_pressure_MPa < nominal_pack * 0.6:
            suggestions.append("提高保压压力 10–15%，延长保压时间 2–3s")
        if wall_thickness_mm > 4.0:
            suggestions.append("优化制品设计，将厚壁改为中空肋板结构")

    return {"defect": "缩痕/缩孔 (Sink Marks)", "risk": round(score, 2),
            "severity": _risk(score), "root_causes": causes, "suggestions": suggestions}


def check_warpage(
    mold_temp_C: float,
    wall_thickness_mm: float,
    window: ProcessingWindow,
    polymer: str = "PP",
    cooling_time_s: float = 10.0,
) -> dict:
    causes = []
    score = 0.0

    # Semi-crystalline polymers (PP, PA, POM) are inherently warp-prone
    warp_prone = {"PP", "PA6", "PA66", "POM", "PBT", "PET", "PPS", "PEEK"}
    if polymer in warp_prone:
        score += 0.15
        causes.append(f"{polymer} 属于半结晶聚合物，各向异性收缩，天然具有翘曲倾向")

    # Mold temperature too low: steep thermal gradient → residual stress
    mold_mid = (window.mold_temp_min_C + window.mold_temp_max_C) / 2
    if mold_temp_C < mold_mid - 15:
        score += 0.25
        causes.append(f"模温 {mold_temp_C}°C 偏低，制品内外冷却速率差异大，易产生残余应力")

    # Thin walls → less bending stiffness to resist shrinkage force
    if wall_thickness_mm < 1.5:
        score += 0.20
        causes.append(f"壁厚 {wall_thickness_mm}mm 较薄，刚度低，易在收缩力作用下翘曲")

    score = min(score, 1.0)
    suggestions = []
    if score > 0.1:
        suggestions.append(f"将模温调整至推荐中间值 {mold_mid:.0f}°C，减少温度梯度")
        if polymer in warp_prone:
            suggestions.append("延长冷却时间并适当提高保压压力，降低残余应力")
            suggestions.append("确保浇口设计使流动方向对称，减少各向异性收缩差")

    return {"defect": "翘曲变形 (Warpage)", "risk": round(score, 2),
            "severity": _risk(score), "root_causes": causes, "suggestions": suggestions}


def check_burn_marks(
    injection_speed_mm_s: Optional[float],
    melt_temp_C: float,
    window: ProcessingWindow,
    cavity_shear_rate_s: float = 0.0,
) -> dict:
    causes = []
    score = 0.0

    # High shear rate → adiabatic shear heating → burn
    if cavity_shear_rate_s > 40000:
        score += min((cavity_shear_rate_s - 40000) / 40000 * 0.5, 0.5)
        causes.append(f"剪切速率 {cavity_shear_rate_s:.0f} s⁻¹ 过高，剪切热显著")

    # High melt temperature
    if melt_temp_C > window.melt_temp_max_C + 10:
        score += 0.35
        causes.append(f"熔体温度 {melt_temp_C}°C 超出推荐上限，材料已有降解风险")

    score = min(score, 1.0)
    suggestions = []
    if score > 0.1:
        suggestions.append("适当降低注射速度（降低剪切速率）")
        suggestions.append("在制品末端增加排气槽，避免绝热压缩烧焦")
        if melt_temp_C > window.melt_temp_max_C + 10:
            suggestions.append(f"将熔体温度降至 {window.melt_temp_max_C}°C 以内")

    return {"defect": "焦痕/烧焦 (Burn Marks)", "risk": round(score, 2),
            "severity": _risk(score), "root_causes": causes, "suggestions": suggestions}


def check_silver_streaks(
    drying_done: bool,
    drying_temp_C: Optional[float],
    drying_time_h: Optional[float],
    recommended_drying_temp_C: Optional[float],
    recommended_drying_time_h: Optional[float],
    melt_temp_C: float,
    window: ProcessingWindow,
) -> dict:
    causes = []
    score = 0.0

    if not drying_done:
        score += 0.60
        causes.append("未确认是否完成干燥处理，水分/挥发物是银纹的主要原因")
    elif (drying_temp_C and recommended_drying_temp_C and
          drying_temp_C < recommended_drying_temp_C - 5):
        score += 0.35
        causes.append(f"干燥温度 {drying_temp_C}°C 低于推荐 {recommended_drying_temp_C}°C")
    elif (drying_time_h and recommended_drying_time_h and
          drying_time_h < recommended_drying_time_h * 0.8):
        score += 0.30
        causes.append(f"干燥时间 {drying_time_h}h 可能不足（推荐 {recommended_drying_time_h}h）")

    if melt_temp_C > window.melt_temp_max_C:
        score += 0.25
        causes.append("熔体温度过高，材料热降解也可能产生银纹")

    score = min(score, 1.0)
    suggestions = []
    if score > 0.1:
        if recommended_drying_temp_C:
            suggestions.append(f"在 {recommended_drying_temp_C}°C 下干燥 {recommended_drying_time_h or 4}h，并确认料斗密封")
        suggestions.append("检查螺杆背压是否足够将气泡从熔体中排出")

    return {"defect": "银纹/料花 (Silver Streaks)", "risk": round(score, 2),
            "severity": _risk(score), "root_causes": causes, "suggestions": suggestions}


# ─────────────────────────────────────────────────────────────────────────────
# Inverse diagnosis: given reported defect → suggest parameter deltas
# ─────────────────────────────────────────────────────────────────────────────

DEFECT_ADJUSTMENTS: dict[str, dict] = {
    "飞边": {
        "melt_temp_delta_C":             -10,
        "injection_pressure_delta_MPa":  -5,
        "packing_pressure_delta_pct":    -10,
        "rationale": "飞边通常由熔体粘度过低或压力过大引起，应降温降压",
    },
    "短射": {
        "melt_temp_delta_C":             +15,
        "injection_pressure_delta_MPa":  +10,
        "injection_speed_delta_pct":     +20,
        "rationale": "短射由充填不完整引起，应升温升压或提高注射速度",
    },
    "缩痕": {
        "packing_pressure_delta_pct":    +15,
        "packing_time_delta_s":          +2,
        "mold_temp_delta_C":             -5,
        "rationale": "缩痕由补缩不足引起，增加保压压力和时间",
    },
    "翘曲": {
        "mold_temp_delta_C":             +10,
        "cooling_time_delta_s":          +5,
        "packing_pressure_delta_pct":    +10,
        "rationale": "翘曲由残余应力和各向异性收缩引起，提高模温并延长冷却",
    },
    "银纹": {
        "drying_action": "确保在推荐温度和时间下完成干燥",
        "melt_temp_delta_C":             -5,
        "back_pressure_delta_MPa":       +2,
        "rationale": "银纹多由水分或降解气体引起，首先检查干燥状态",
    },
    "焦痕": {
        "injection_speed_delta_pct":     -20,
        "melt_temp_delta_C":             -10,
        "vent_action": "检查排气槽是否堵塞",
        "rationale": "焦痕由剪切热或困气引起，降速降温并改善排气",
    },
    "熔接线": {
        "melt_temp_delta_C":             +10,
        "injection_speed_delta_pct":     +15,
        "mold_temp_delta_C":             +10,
        "rationale": "熔接线由两股料流汇合时温度过低引起，升温提速",
    },
}


def inverse_diagnose(reported_defect: str) -> dict:
    """
    Given a reported defect (Chinese keyword), return parameter adjustment recommendations.
    """
    for key, adj in DEFECT_ADJUSTMENTS.items():
        if key in reported_defect:
            return {"matched_defect": key, "adjustments": adj}
    return {
        "matched_defect": None,
        "adjustments": {},
        "note": "未识别到已知缺陷类型，请提供更多制品描述",
    }
