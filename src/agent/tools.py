"""
src/agent/tools.py
──────────────────
Tool definitions for the LLM agent.
Each tool is exposed as an OpenAI-style function-calling schema.
"""

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_grade_database",
            "description": (
                "在本地数据库中搜索塑料牌号，返回匹配的牌号列表及基本信息。"
                "当用户提到一个塑料牌号或树脂类型时，首先调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如牌号名称、树脂类型或供应商名称",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_grade_details",
            "description": (
                "获取指定牌号的完整物性数据（包括加工窗口、热性能、力学性能等）。"
                "需要先通过 query_grade_database 获取 grade_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "grade_id": {
                        "type": "string",
                        "description": "牌号ID（由 query_grade_database 返回）",
                    }
                },
                "required": ["grade_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_grade_from_web",
            "description": (
                "当本地数据库中没有找到指定牌号时，从互联网搜索并获取该牌号的工艺参数。"
                "此工具较慢，仅在本地数据库查询失败时调用。"
                "【严禁调用】：如果全局上下文中已经存在【当前选定牌号】的信息，说明该牌号已经是本地数据库中的最新数据。"
                "此时即使部分加工参数显示为 '?'，也绝对不可再次调用此工具进行重复抓取，否则会破坏本地数据！直接基于你的高分子物理经验进行参数估算并直接进行后续模拟即可。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "grade_name": {
                        "type": "string",
                        "description": "完整的塑料牌号名称，如 'PC Covestro Makrolon 2205'",
                    }
                },
                "required": ["grade_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_injection_simulation",
            "description": (
                "运行注塑成型物理模拟，计算冷却时间、填充压力、锁模力，"
                "并对飞边、短射、缩痕、翘曲、焦痕等缺陷进行风险评估。"
                "调用前必须已知：grade_id（或grade_data）、熔体温度、模具温度、注射压力和制品几何参数。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "grade_id":              {"type": "string",  "description": "牌号ID"},
                    "melt_temp_C":           {"type": "number",  "description": "熔体温度 [°C]"},
                    "mold_temp_C":           {"type": "number",  "description": "模具温度 [°C]"},
                    "injection_pressure_MPa":{"type": "number",  "description": "注射压力 [MPa]"},
                    "packing_pressure_MPa":  {"type": "number",  "description": "保压压力 [MPa]，默认为注射压力的60%"},
                    "fill_time_s":           {"type": "number",  "description": "填充时间 [s]，默认1.5"},
                    "part_geometry":         {"type": "string",  "description": "'plate'|'disc'|'box'"},
                    "wall_thickness_mm":     {"type": "number",  "description": "壁厚 [mm]"},
                    "part_length_mm":        {"type": "number",  "description": "制品长度或流程长度 [mm]"},
                    "part_width_mm":         {"type": "number",  "description": "制品宽度或直径 [mm]"},
                    "runner_length_mm":      {"type": "number",  "description": "流道长度 [mm]，默认80"},
                    "runner_diameter_mm":    {"type": "number",  "description": "流道直径 [mm]，默认8"},
                    "n_cavities":            {"type": "integer", "description": "模腔数量，默认1"},
                    "machine_clamp_kN":      {"type": "number",  "description": "注塑机锁模力 [kN]，可选"},
                    "drying_done":           {"type": "boolean", "description": "是否已完成干燥"},
                    "drying_temp_C":         {"type": "number",  "description": "实际干燥温度 [°C]，可选"},
                    "drying_time_h":         {"type": "number",  "description": "实际干燥时间 [h]，可选"},
                },
                "required": ["grade_id", "melt_temp_C", "mold_temp_C", "injection_pressure_MPa",
                             "wall_thickness_mm", "part_length_mm", "part_width_mm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diagnose_defect",
            "description": (
                "根据用户描述的制品缺陷（如'飞边'、'短射'、'翘曲'等），"
                "给出参数调整建议。在用户反馈实际试模结果后调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "defect_description": {
                        "type": "string",
                        "description": "用户描述的缺陷，如'产品边缘有飞边，表面有银纹'",
                    }
                },
                "required": ["defect_description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_initial_params",
            "description": (
                "根据牌号数据直接推荐初始注塑工艺参数（熔体温度、模温、压力等），"
                "取推荐范围的中间值，并考虑制品壁厚进行适当调整。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "grade_id":          {"type": "string", "description": "牌号ID"},
                    "wall_thickness_mm": {"type": "number", "description": "制品壁厚 [mm]"},
                    "part_length_mm":    {"type": "number", "description": "制品长度 [mm]，影响保压设定"},
                },
                "required": ["grade_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "在本地专业文献知识库（注塑论文、技术手册、TDS）中进行语义搜索，"
                "返回与问题最相关的技术文献片段，增强回答的学术性和准确性。"
                "当需要解释物理现象、计算公式或工艺原理时优先调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索问题，英文效果更佳。例: 'cooling time formula wall thickness injection molding'",
                    },
                    "n_results": {
                        "type": "integer",
                        "description": "返回结果数量，默认3",
                    },
                },
                "required": ["query"],
            },
        },
    },
]
