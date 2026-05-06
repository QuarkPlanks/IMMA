"""
src/agent/agent.py
──────────────────
LLM Agent main loop.

Architecture:
  - Uses OpenAI-compatible API with function calling (tool use).
  - Maintains conversation history across turns.
  - Dispatches tool calls to local Python functions.
  - Global context (grade selection + mold params) is injected as system prompt prefix.
"""

import json
import logging
from typing import Optional, Generator

from openai import OpenAI

import sys
from pathlib import Path
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS
from .tools import TOOLS
from src.knowledge import search_grade, get_grade, get_processing_params, search_and_fetch
from src.simulator  import run_simulation_from_dict, inverse_diagnose_from_text

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """你是一位专业的注塑成型工艺工程师AI助手。你的职责是：
1. 根据用户选择的塑料牌号，查询其工艺参数数据
2. 推荐合适的初始注塑工艺参数（熔体温度、模温、注射压力、保压压力等）
3. 调用注塑模拟工具，对成型过程进行物理仿真，输出冷却时间、所需锁模力、缺陷风险等
4. 根据用户反馈的实际试模缺陷（飞边、短射、翘曲等），分析原因并调整工艺参数

工作原则：
- 总是优先查询本地数据库，查不到时再联网搜索
- 推荐参数时要给出具体数值，不要给模糊范围
- 调用模拟工具后，以结构化方式展示结果并解读
- 用中文回答，术语使用规范中文（可附英文缩写）
- 每次参数调整要给出明确的物理原因

{global_context}"""


def build_system_prompt(grade_data: Optional[dict], mold_params: Optional[dict],
                         extra_goals: str = "",
                         mold_image_description: str = "") -> str:
    """Build the full system prompt injecting global context."""
    ctx_parts = []

    if grade_data:
        name = grade_data.get("grade_name", "未知")
        poly = grade_data.get("polymer", "")
        supl = grade_data.get("supplier", "")
        proc = grade_data.get("processing", {})
        ctx_parts.append(
            f"【当前选定牌号】{name}（{poly}，{supl}）\n"
            f"  加工窗口: 熔体温度 {proc.get('melt_temp_min_C','?')}–{proc.get('melt_temp_max_C','?')}°C | "
            f"模温 {proc.get('mold_temp_min_C','?')}–{proc.get('mold_temp_max_C','?')}°C | "
            f"干燥 {proc.get('drying_temp_C','?')}°C × {proc.get('drying_time_h','?')}h"
        )

    if mold_params:
        mp = mold_params
        geom = mp.get('part_geometry', '未设定')
        if geom == "custom":
            geom_str = "自定义（见下方图片描述）"
        else:
            geom_str = (
                f"{geom} | 壁厚: {mp.get('wall_thickness_mm','未设定')} mm | "
                f"尺寸: {mp.get('part_length_mm','?')} × {mp.get('part_width_mm','?')} mm | "
                f"模腔数: {mp.get('n_cavities', 1)} | "
                f"机台锁模力: {mp.get('machine_clamp_kN','未设定')} kN"
            )
        ctx_parts.append(f"【当前模具/制品参数】\n  几何类型: {geom_str}")
        if mp.get("vision_notes"):
            ctx_parts.append(f"  图纸解析备注: {mp['vision_notes']}")

    # ── Mold image description (from Vision LLM) ──────────────────────────────
    if mold_image_description.strip():
        ctx_parts.append(
            f"【模具图片分析（由视觉AI生成，请重点参考）】\n{mold_image_description}"
        )

    if extra_goals.strip():
        ctx_parts.append(f"【用户设计目标与约束】\n{extra_goals}")

    global_ctx = "\n\n".join(ctx_parts) if ctx_parts else "（尚未选择牌号或设定模具参数）"
    return BASE_SYSTEM_PROMPT.format(global_context=f"--- 全局上下文 ---\n{global_ctx}\n---")


# ─────────────────────────────────────────────────────────────────────────────
# Tool dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def _dispatch_tool(name: str, args: dict, grade_data_ref: dict) -> str:
    """Execute a tool call and return the result as a JSON string."""
    try:
        if name == "query_grade_database":
            results = search_grade(args["query"])
            return json.dumps(results, ensure_ascii=False, indent=2)

        elif name == "get_grade_details":
            g = get_grade(args["grade_id"])
            if g:
                grade_data_ref.update(g)   # update shared reference
                return json.dumps(g, ensure_ascii=False, indent=2)
            return json.dumps({"error": f"Grade '{args['grade_id']}' not found"})

        elif name == "fetch_grade_from_web":
            g = search_and_fetch(args["grade_name"])
            if g:
                grade_data_ref.update(g)
                return json.dumps(g, ensure_ascii=False, indent=2)
            return json.dumps({"error": "Web fetch failed"})

        elif name == "run_injection_simulation":
            # Resolve grade_data
            gid = args.get("grade_id", "")
            if gid and not grade_data_ref:
                g = get_grade(gid)
                if g:
                    grade_data_ref.update(g)

            sim_input = dict(args)
            sim_input["grade_data"] = dict(grade_data_ref)
            result = run_simulation_from_dict(sim_input)
            return json.dumps(result, ensure_ascii=False, indent=2)

        elif name == "diagnose_defect":
            result = inverse_diagnose_from_text(args["defect_description"])
            return json.dumps(result, ensure_ascii=False, indent=2)

        elif name == "search_knowledge_base":
            try:
                from src.knowledge.rag.document_store import query as rag_query
                n = args.get("n_results", 3)
                hits = rag_query(args["query"], n_results=n)
                if not hits:
                    return json.dumps({
                        "note": "知识库为空或未找到相关内容。请先运行 build_knowledge_base.py 构建知识库。",
                        "results": []
                    }, ensure_ascii=False)
                return json.dumps({"results": hits}, ensure_ascii=False, indent=2)
            except Exception as e:
                return json.dumps({"error": str(e), "results": []})

        elif name == "recommend_initial_params":
            gid = args.get("grade_id", "")
            g = grade_data_ref if grade_data_ref else get_grade(gid)
            if not g:
                return json.dumps({"error": f"Grade '{gid}' not found"})
            return json.dumps(_recommend_params(g, args), ensure_ascii=False, indent=2)

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as e:
        log.exception("Tool '%s' raised: %s", name, e)
        return json.dumps({"error": str(e)})


def _recommend_params(grade: dict, args: dict) -> dict:
    """Generate initial parameter recommendations from grade data."""
    p = grade.get("processing", {})
    wall = args.get("wall_thickness_mm", 2.5)
    length = args.get("part_length_mm", 100)

    def mid(lo, hi, default_lo=200, default_hi=260):
        a = p.get(lo, default_lo)
        b = p.get(hi, default_hi)
        return round((a + b) / 2, 0)

    melt   = mid("melt_temp_min_C", "melt_temp_max_C")
    mold   = mid("mold_temp_min_C",  "mold_temp_max_C", 40, 80)
    inj_p  = p.get("injection_pressure_MPa_max", 130) * 0.75
    pack_p = inj_p * 0.60
    bp     = p.get("back_pressure_MPa", 5)

    # Thin walls → higher temp; long flow path → higher pressure
    if wall < 1.5:
        melt = min(melt + 10, p.get("melt_temp_max_C", 300))
        inj_p *= 1.10
    if length > 150:
        inj_p *= 1.10

    return {
        "grade_id":               grade.get("grade_id"),
        "grade_name":             grade.get("grade_name"),
        "recommended": {
            "melt_temp_C":             round(melt, 0),
            "mold_temp_C":             round(mold, 0),
            "injection_pressure_MPa":  round(inj_p, 1),
            "packing_pressure_MPa":    round(pack_p, 1),
            "back_pressure_MPa":       bp,
            "drying_temp_C":           p.get("drying_temp_C"),
            "drying_time_h":           p.get("drying_time_h"),
        },
        "note": "以上参数为推荐初始值（加工窗口中间值），请在实际成型中根据制品情况调整。",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Agent class
# ─────────────────────────────────────────────────────────────────────────────

class InjectionMoldingAgent:
    """
    Stateful injection molding AI agent.
    Maintains conversation history and current global context.
    """

    def __init__(self):
        self.client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        self.history: list[dict] = []
        self.grade_data: dict = {}        # shared grade state
        self.mold_params: dict = {}       # shared mold geometry state
        self.extra_goals: str = ""
        self.mold_image_description: str = ""   # Vision LLM-generated mold description
        self.last_sim_result: dict = {}

    def set_grade(self, grade_id: str):
        g = get_grade(grade_id)
        if g:
            self.grade_data = g

    def set_mold_params(self, params: dict):
        self.mold_params.update(params)

    def set_extra_goals(self, text: str):
        self.extra_goals = text

    def reset_history(self):
        self.history = []

    def _system_msg(self) -> dict:
        return {
            "role": "system",
            "content": build_system_prompt(
                self.grade_data or None,
                self.mold_params or None,
                self.extra_goals,
                self.mold_image_description,
            ),
        }

    def chat(self, user_message: str, max_tool_rounds: int = 5) -> str:
        """
        Send a user message and return the agent's final response.
        Handles multi-step tool call loops internally.
        """
        self.history.append({"role": "user", "content": user_message})
        messages = [self._system_msg()] + self.history

        for _ in range(max_tool_rounds):
            response = self.client.chat.completions.create(
                model       = LLM_MODEL,
                messages    = messages,
                tools       = TOOLS,
                tool_choice = "auto",
                temperature = LLM_TEMPERATURE,
                max_tokens  = LLM_MAX_TOKENS,
            )

            msg = response.choices[0].message
            finish = response.choices[0].finish_reason

            # No more tool calls → done
            if finish == "stop" or not msg.tool_calls:
                text = msg.content or ""
                self.history.append({"role": "assistant", "content": text})
                return text

            # Append assistant's tool-call message
            messages.append(msg)

            # Execute each tool call
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result_str = _dispatch_tool(tc.function.name, args, self.grade_data)

                # Cache simulation result for the UI
                if tc.function.name == "run_injection_simulation":
                    try:
                        self.last_sim_result = json.loads(result_str)
                    except Exception:
                        pass

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # Fallback: ask model to summarise
        response = self.client.chat.completions.create(
            model=LLM_MODEL, messages=messages,
            temperature=LLM_TEMPERATURE, max_tokens=LLM_MAX_TOKENS,
        )
        text = response.choices[0].message.content or ""
        self.history.append({"role": "assistant", "content": text})
        return text
