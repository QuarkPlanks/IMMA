"""
app.py — Streamlit 主应用
三栏左侧面板 + 右侧模拟结果展示
"""

import sys, json
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import time


ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from src.knowledge import list_grades, get_grade, search_grade, search_and_fetch
from src.agent     import InjectionMoldingAgent
from src.vision    import extract_mold_dimensions, merge_with_defaults, describe_mold_for_agent

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="注塑成型 AI 助手",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── CSS ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Dark gradient background */
.stApp { background: linear-gradient(135deg, #0f1117 0%, #1a1d2e 50%, #0f1117 100%); }

/* Panel cards */
.panel-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 14px;
    padding: 18px 20px 14px;
    margin-bottom: 14px;
    backdrop-filter: blur(10px);
}
.panel-title {
    font-size: 0.78rem; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: #7c83fd; margin-bottom: 10px;
}

/* Chat messages */
.msg-user {
    background: linear-gradient(135deg, #4f46e5, #7c3aed);
    color: white; border-radius: 16px 16px 4px 16px;
    padding: 10px 14px; margin: 6px 0 6px 40px;
    font-size: 0.92rem;
}
.msg-ai {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
    color: #e2e8f0; border-radius: 16px 16px 16px 4px;
    padding: 10px 14px; margin: 6px 40px 6px 0;
    font-size: 0.92rem;
}

/* Status badges */
.badge-ok       { background:#0d9488; color:white; padding:2px 10px; border-radius:99px; font-size:0.78rem; font-weight:600; }
.badge-warning  { background:#d97706; color:white; padding:2px 10px; border-radius:99px; font-size:0.78rem; font-weight:600; }
.badge-critical { background:#dc2626; color:white; padding:2px 10px; border-radius:99px; font-size:0.78rem; font-weight:600; }

/* Metric tiles */
.metric-row { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
.metric-tile {
    flex:1; min-width:100px;
    background:rgba(255,255,255,0.05);
    border:1px solid rgba(255,255,255,0.08);
    border-radius:10px; padding:10px 14px; text-align:center;
}
.metric-val { font-size:1.5rem; font-weight:700; color:#a5b4fc; }
.metric-lbl { font-size:0.72rem; color:#94a3b8; margin-top:2px; }

/* Streamlit overrides */
div[data-testid="stVerticalBlock"] > div:has(> div.panel-card) { gap: 0 !important; }
.stSelectbox label, .stSlider label, .stTextArea label, .stNumberInput label
    { color:#94a3b8 !important; font-size:0.82rem !important; }
.stButton>button {
    background: linear-gradient(135deg,#4f46e5,#7c3aed);
    color:white; border:none; border-radius:8px;
    font-weight:600; transition: opacity 0.2s;
}
.stButton>button:hover { opacity:0.85; }
</style>
""", unsafe_allow_html=True)

# ─── Session state ────────────────────────────────────────────────────────────
def _init():
    defaults = {
        "agent":        None,
        "chat_history": [],
        "grade_data":   {},
        "mold_params":  {"part_geometry": "plate", "wall_thickness_mm": 2.5,
                          "part_length_mm": 100.0, "part_width_mm": 60.0,
                          "runner_length_mm": 80.0, "runner_diameter_mm": 8.0,
                          "n_cavities": 1},
        "sim_result":   None,
        "extra_goals":  "",
        "mold_text":    "",
        "mold_image_description": "",   # Vision LLM description injected to agent
        "mold_image_bytes": None,       # stored bytes for re-use
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

def get_agent() -> InjectionMoldingAgent:
    if st.session_state.agent is None:
        st.session_state.agent = InjectionMoldingAgent()
    ag = st.session_state.agent
    if st.session_state.grade_data:
        ag.grade_data  = st.session_state.grade_data
    ag.mold_params = st.session_state.mold_params
    ag.extra_goals = st.session_state.extra_goals
    ag.mold_image_description = st.session_state.mold_image_description
    return ag


@st.dialog("📚 塑料牌号数据库", width="large")
def grade_selection_dialog():
    st.markdown("### 🌐 现场获取新牌号")
    st.info("💡 如果本地库中没有需要的牌号，请输入完整名称（如 'ABS PA-757'），系统将自动从 Plasway 或网络源抓取物性参数。")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        web_search = st.text_input("牌号名称", placeholder="输入后按 Enter 查询...", label_visibility="collapsed", key="dialog_web_search")
    with col2:
        if st.button("立即抓取", use_container_width=True, type="primary"):
            if web_search:
                with st.spinner(f"正在自动化抓取 {web_search} 的参数，请稍候…"):
                    g = search_and_fetch(web_search)
                if g:
                    st.session_state.grade_data = g
                    st.success(f"✅ 成功获取: {g.get('grade_name')}")
                    time.sleep(1.0)
                    st.rerun()
                else:
                    st.error("未能获取数据，请检查名称或尝试更通用的牌号。")

    st.markdown("---")
    st.markdown("### 📁 从本地库选择")
    all_grades = list_grades()
    if not all_grades:
        st.warning("本地数据库为空，请在上方抓取。")
        return

    df_data = []
    for g in all_grades:
        src = g.get("data_source", "unknown")
        src_label = {"plasway": "Plasway", "omnexus": "Omnexus", "ddg_regex": "网络搜索", "llm_generated": "AI估算"}.get(src, src)
        df_data.append({
            "牌号名称": g.get("grade_name", ""),
            "聚合物": g.get("polymer", ""),
            "供应商": g.get("supplier", ""),
            "数据来源": src_label,
            "_id": g.get("grade_id", "")
        })
    df = pd.DataFrame(df_data)

    search_term = st.text_input("🔍 搜索过滤 (牌号/供应商/聚合物)", "")
    if search_term:
        mask = df.apply(lambda row: row.astype(str).str.contains(search_term, case=False).any(), axis=1)
        df = df[mask]

    event = st.dataframe(
        df[["牌号名称", "聚合物", "供应商", "数据来源"]],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )

    if event.selection.rows:
        idx = event.selection.rows[0]
        selected_id = df.iloc[idx]["_id"]
        colA, colB = st.columns([1, 1])
        with colA:
            if st.button("✅ 确认选择", use_container_width=True, type="primary"):
                g = get_grade(selected_id)
                if g:
                    st.session_state.grade_data = g
                st.rerun()
        with colB:
            if st.button("重新抓取该牌号", use_container_width=True):
                with st.spinner("正在重新抓取…"):
                    g = search_and_fetch(df.iloc[idx]["牌号名称"], force=True)
                if g:
                    st.session_state.grade_data = g
                    st.success("已更新。")
                    time.sleep(1.0)
                    st.rerun()




# ─── Header ──────────────────────────────────────────────────────────────────
st.markdown("""
<div style='text-align:center; padding: 18px 0 10px'>
  <span style='font-size:2.2rem; font-weight:700;
    background:linear-gradient(135deg,#a5b4fc,#7c3aed);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent'>
    🏭 注塑成型 AI 助手
  </span>
  <p style='color:#64748b; font-size:0.88rem; margin-top:4px'>
    智能工艺参数推荐 · 物理仿真模拟 · 缺陷诊断调参
  </p>
</div>
""", unsafe_allow_html=True)

# ─── Layout: left (3 panels) | right (results) ───────────────────────────────
left, right = st.columns([5, 7], gap="large")

# ════════════════════════════════════════════════════════════════════════════
# LEFT COLUMN
# ════════════════════════════════════════════════════════════════════════════
with left:

    # ── Panel 1: 牌号选择 ─────────────────────────────────────────────────
    st.markdown('<div class="panel-card"><div class="panel-title">① 选择塑料牌号</div>', unsafe_allow_html=True)

    if st.button("🔍 浏览与搜索牌号库", use_container_width=True):
        grade_selection_dialog()

    # Show grade info + LLM warning
    gd = st.session_state.grade_data
    if gd:
        proc = gd.get("processing", {})
        is_llm = gd.get("data_source") == "llm_generated"
        src_tag = gd.get("data_source", "unknown")
        src_label = {
            "plasway": "📊 Plasway", "omnexus": "📊 Omnexus",
            "ddg_regex": "🔍 Web搜索", "llm_generated": "🤖 AI估算"
        }.get(src_tag, f"📁 {src_tag}")

        st.markdown(f"""
        <div style='background:rgba(99,102,241,0.08); border-radius:8px; padding:8px 12px;
                    font-size:0.82rem; color:#a5b4fc; margin-top:6px'>
        <b>{gd.get('grade_name','')}</b> &nbsp;|&nbsp; {gd.get('polymer','')} &nbsp;|&nbsp;
        {gd.get('supplier','')} &nbsp;<span style='color:#64748b;font-size:0.72rem'>{src_label}</span><br>
        熔体温度: {proc.get('melt_temp_min_C','?')}–{proc.get('melt_temp_max_C','?')} °C &nbsp;&nbsp;
        模温: {proc.get('mold_temp_min_C','?')}–{proc.get('mold_temp_max_C','?')} °C &nbsp;&nbsp;
        干燥: {proc.get('drying_temp_C','?')} °C × {proc.get('drying_time_h','?')} h
        </div>""", unsafe_allow_html=True)

        if is_llm:
            st.warning(
                f"⚠️ **参数由 AI 估算** — 未能从数据库或网络获取 '{gd.get('grade_name')}' 的实测数据，"
                f"当前参数为基于 {gd.get('polymer','该聚合物')} 行业通用值的 AI 估算，"
                f"**仅供参考，请在实际成型前向供应商索取原厂 TDS 确认。**"
            )
        if gd.get("warning"):
            st.caption(gd["warning"])

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Panel 2: 模具参数 ─────────────────────────────────────────────────
    st.markdown('<div class="panel-card"><div class="panel-title">② 模具 / 制品参数</div>', unsafe_allow_html=True)

    mp = st.session_state.mold_params

    # ── Geometry type selector (safe against unknown values) ──────────────
    GEOM_OPTIONS = ["plate", "disc", "box", "custom"]
    GEOM_LABELS  = {"plate": "平板 (plate)", "disc": "圆盘 (disc)",
                    "box": "盒体 (box)", "custom": "🖼 自定义 / 图片识别 (custom)"}
    current_geom = mp.get("part_geometry", "plate")
    if current_geom not in GEOM_OPTIONS:
        current_geom = "custom"   # <- 修复：Vision AI 返回 custom 时不崩溃
        mp["part_geometry"] = current_geom

    selected_geom = st.selectbox(
        "几何类型",
        options=GEOM_OPTIONS,
        index=GEOM_OPTIONS.index(current_geom),
        format_func=lambda x: GEOM_LABELS.get(x, x),
        key="geom_select",
    )
    mp["part_geometry"] = selected_geom

    if selected_geom == "custom":
        # ── Custom mode: hide numeric inputs, rely on text + image ────────
        st.info("📌 **自定义模式**：请上传模具图片和/或文字描述，AI 将自动生成模具特点描述并作为参数推荐的依据。")
    else:
        # ── Standard mode: numeric inputs ─────────────────────────────────
        geom_col, cav_col = st.columns(2)
        with cav_col:
            mp["n_cavities"] = st.number_input("模腔数", 1, 32, int(mp.get("n_cavities", 1)), step=1)

        c1, c2, c3 = st.columns(3)
        with c1:
            mp["wall_thickness_mm"] = st.number_input("壁厚 (mm)", 0.5, 20.0, float(mp.get("wall_thickness_mm", 2.5)), step=0.1)
        with c2:
            mp["part_length_mm"] = st.number_input("长度 (mm)", 10.0, 2000.0, float(mp.get("part_length_mm", 100.0)), step=5.0)
        with c3:
            mp["part_width_mm"] = st.number_input("宽度 (mm)", 10.0, 2000.0, float(mp.get("part_width_mm", 60.0)), step=5.0)

        r1, r2, r3 = st.columns(3)
        with r1:
            mp["runner_length_mm"] = st.number_input("流道长 (mm)", 10.0, 500.0, float(mp.get("runner_length_mm", 80.0)), step=5.0)
        with r2:
            mp["runner_diameter_mm"] = st.number_input("流道径 (mm)", 2.0, 20.0, float(mp.get("runner_diameter_mm", 8.0)), step=0.5)
        with r3:
            clamp_val = mp.get("machine_clamp_kN") or 0.0
            clamp_in = st.number_input("机台锁模力 (kN)", 0.0, 50000.0, float(clamp_val), step=100.0)
            mp["machine_clamp_kN"] = clamp_in if clamp_in > 0 else None

    # ── Image upload (always visible) ─────────────────────────────────────
    st.markdown("<div style='color:#64748b; font-size:0.78rem; margin:8px 0 4px'>上传模具图纸（可选，AI自动提取尺寸 + 生成特点描述）</div>",
                unsafe_allow_html=True)
    uploaded = st.file_uploader("", type=["png", "jpg", "jpeg", "webp"],
                                  label_visibility="collapsed", key="mold_image")
    mold_text = st.text_area("补充文字描述（尺寸、结构说明等）",
                               value=st.session_state.mold_text,
                               placeholder="例如：产品为外壳，有4个卡扣，最大流程180mm，主壁厚2mm",
                               height=70, key="mold_desc_input")
    st.session_state.mold_text = mold_text

    if uploaded is not None:
        img_bytes = uploaded.read()
        st.session_state.mold_image_bytes = img_bytes

        btn_label = "🔍 AI 解析图纸" if selected_geom != "custom" else "🔍 AI 分析模具特点"
        if st.button(btn_label, key="parse_img"):
            with st.spinner("正在分析图纸 …"):
                # Step 1: Generate detailed mold description for LLM context
                desc = describe_mold_for_agent(img_bytes, mold_text)
                if desc:
                    st.session_state.mold_image_description = desc

                # Step 2: Extract numeric dimensions (only meaningful in non-custom mode)
                if selected_geom != "custom":
                    extracted = extract_mold_dimensions(img_bytes, mold_text)
                    st.session_state.mold_params = merge_with_defaults(extracted, mp)
                    if extracted.get("notes"):
                        st.info(extracted["notes"])
                    # If Vision returned 'custom', keep it
                    if extracted.get("part_geometry") == "custom":
                        st.session_state.mold_params["part_geometry"] = "custom"
                else:
                    # custom mode: just store user text as vision_notes
                    mp["vision_notes"] = mold_text or "（见上传图片）"
                    st.session_state.mold_params = mp

            if st.session_state.mold_image_description:
                st.success("✅ 模具分析完成，AI 已生成模具特点描述，将在推荐参数时参考")
                with st.expander("📋 查看模具特点描述", expanded=False):
                    st.markdown(st.session_state.mold_image_description)
            else:
                st.warning("图片分析未能生成描述，请检查 Vision API 配置")
            st.rerun()
    elif st.session_state.mold_image_description:
        # Show previously generated description even without new upload
        with st.expander("📋 已有模具特点描述（点击查看）", expanded=False):
            st.markdown(st.session_state.mold_image_description)
        if st.button("🗑 清除模具描述", key="clear_desc_btn"):
            st.session_state.mold_image_description = ""
            st.rerun()

    st.session_state.mold_params = mp
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Panel 3: 补充目标 + 聊天框 ───────────────────────────────────────
    st.markdown('<div class="panel-card"><div class="panel-title">③ 设计目标 / 对话</div>', unsafe_allow_html=True)

    new_goals = st.text_area("设计目标与约束",
                               value=st.session_state.extra_goals,
                               placeholder="例如：制品要求表面光洁，不允许缩痕；生产节拍≤30s；机台锁模力800T",
                               height=65, key="goals_input")
    st.session_state.extra_goals = new_goals

    # Chat history display
    chat_container = st.container(height=320)
    with chat_container:
        for role, text in st.session_state.chat_history:
            css = "msg-user" if role == "user" else "msg-ai"
            icon = "👤" if role == "user" else "🤖"
            st.markdown(f'<div class="{css}">{icon} {text}</div>', unsafe_allow_html=True)

    # Input row
    ci1, ci2 = st.columns([5, 1])
    with ci1:
        user_input = st.text_input("对话输入", placeholder="输入问题或描述试模结果…",
                                    label_visibility="collapsed", key="chat_input")
    with ci2:
        send = st.button("发送 ▶", key="send_btn", use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔄 推荐初始参数", key="recommend_btn", use_container_width=True):
            if not st.session_state.grade_data:
                st.warning("请先选择塑料牌号")
            else:
                user_input = "请根据当前牌号和制品参数，推荐初始注塑工艺参数并进行模拟。"
                send = True
    with col_b:
        if st.button("🗑 清空对话", key="clear_btn", use_container_width=True):
            st.session_state.chat_history = []
            if st.session_state.agent:
                st.session_state.agent.reset_history()
            st.rerun()

    if send and user_input:
        if not st.session_state.grade_data:
            st.warning("请先在①面板中选择塑料牌号")
        else:
            st.session_state.chat_history.append(("user", user_input))
            agent = get_agent()
            with st.spinner("AI 正在分析…"):
                reply = agent.chat(user_input)
            st.session_state.chat_history.append(("ai", reply))
            if agent.last_sim_result:
                st.session_state.sim_result = agent.last_sim_result
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# RIGHT COLUMN — Simulation Results Dashboard
# ════════════════════════════════════════════════════════════════════════════
with right:
    sim = st.session_state.sim_result

    if sim is None:
        st.markdown("""
        <div style='display:flex; flex-direction:column; align-items:center;
                    justify-content:center; height:60vh; color:#334155; text-align:center'>
          <div style='font-size:4rem'>🏭</div>
          <div style='font-size:1.1rem; margin-top:12px; font-weight:600; color:#475569'>
            模拟结果将在此展示
          </div>
          <div style='font-size:0.88rem; margin-top:6px; color:#64748b'>
            在左侧选择牌号并发送消息以启动 AI 助手
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        status = sim.get("status", "OK")
        badge = f'<span class="badge-{status.lower()}">{status}</span>'

        gd_right = st.session_state.grade_data
        grade_name = gd_right.get("grade_name", "") or "模拟结果"
        is_llm_right = gd_right.get("data_source") == "llm_generated"
        llm_tag = ' &nbsp;<span style="background:#b45309;color:white;font-size:0.7rem;padding:1px 8px;border-radius:99px">⚠ AI估算参数</span>' if is_llm_right else ''
        st.markdown(f"### {grade_name} &nbsp; {badge}{llm_tag}", unsafe_allow_html=True)
        if is_llm_right:
            st.error("❗ 当前模拟使用的是 AI 估算工艺参数，非该牌号实测数据，模拟结果仅供参考！")

        # ── Key metrics ───────────────────────────────────────────────────
        st.markdown('<div class="metric-row">', unsafe_allow_html=True)
        metrics = [
            ("冷却时间", f"{sim.get('cooling_time_s', 0):.1f}s"),
            ("成型周期",  f"{sim.get('cycle_time_s', 0):.1f}s"),
            ("产能",      f"{sim.get('throughput_per_hour',0):.0f}/h"),
            ("锁模力",    f"{sim.get('clamp_force_tonnes',0):.0f} T"),
            ("注射压力",  f"{sim.get('total_pressure_MPa',0):.0f} MPa"),
            ("熔体粘度",  f"{sim.get('melt_viscosity_Pas',0):.0f} Pa·s"),
        ]
        cols = st.columns(len(metrics))
        for col, (lbl, val) in zip(cols, metrics):
            with col:
                st.markdown(f"""<div class="metric-tile">
                    <div class="metric-val">{val}</div>
                    <div class="metric-lbl">{lbl}</div></div>""",
                    unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # ── Defect radar chart ────────────────────────────────────────────
        defects = sim.get("defects", [])
        if defects:
            names  = [d["defect"].split("(")[0].strip() for d in defects]
            risks  = [round(d["risk"] * 100, 1) for d in defects]

            fig_radar = go.Figure(go.Scatterpolar(
                r=risks + [risks[0]],
                theta=names + [names[0]],
                fill='toself',
                fillcolor='rgba(124,58,237,0.25)',
                line=dict(color='#7c3aed', width=2),
                name="缺陷风险 %",
            ))
            fig_radar.update_layout(
                polar=dict(
                    bgcolor='rgba(0,0,0,0)',
                    radialaxis=dict(visible=True, range=[0, 100],
                                    gridcolor='rgba(255,255,255,0.1)',
                                    tickfont=dict(color='#94a3b8', size=10)),
                    angularaxis=dict(gridcolor='rgba(255,255,255,0.08)',
                                     tickfont=dict(color='#e2e8f0', size=11)),
                ),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(t=20, b=20, l=30, r=30),
                height=280,
                showlegend=False,
            )
            st.plotly_chart(fig_radar, use_container_width=True)

        # ── Defect detail table ───────────────────────────────────────────
        if defects:
            st.markdown("#### 缺陷风险明细")
            rows = []
            for d in defects:
                sev_emoji = {"low":"🟢","medium":"🟡","high":"🟠","critical":"🔴"}.get(d["severity"],"⚪")
                rows.append({
                    "缺陷类型":   d["defect"],
                    "风险":       f"{sev_emoji} {d['risk']*100:.0f}%",
                    "等级":       d["severity"],
                    "主要建议":   d["suggestions"][0] if d["suggestions"] else "—",
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True,
                         column_config={
                             "风险": st.column_config.TextColumn(width="small"),
                             "等级": st.column_config.TextColumn(width="small"),
                         })

        # ── Process parameters bar chart ──────────────────────────────────
        gd = st.session_state.grade_data
        proc = gd.get("processing", {})
        if proc.get("melt_temp_min_C"):
            st.markdown("#### 工艺参数范围校验")
            params_check = []
            agent_state = (st.session_state.agent.history or [{}])[-2] if st.session_state.agent else {}

            # Try to extract current params from last sim result
            melt_set  = sim.get("_melt_temp_C",  proc.get("melt_temp_min_C", 230))
            mold_set  = sim.get("_mold_temp_C",  proc.get("mold_temp_min_C",  60))

            bar_data = {
                "参数":  ["熔体温度", "模具温度"],
                "下限":  [proc.get("melt_temp_min_C", 200), proc.get("mold_temp_min_C", 40)],
                "推荐":  [
                    (proc.get("melt_temp_min_C",200)+proc.get("melt_temp_max_C",260))/2,
                    (proc.get("mold_temp_min_C",40)+proc.get("mold_temp_max_C",80))/2,
                ],
                "上限":  [proc.get("melt_temp_max_C", 260), proc.get("mold_temp_max_C", 80)],
            }
            df_bar = pd.DataFrame(bar_data)
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(name="下限", x=df_bar["参数"], y=df_bar["下限"],
                                      marker_color="#1e293b"))
            fig_bar.add_trace(go.Bar(name="推荐", x=df_bar["参数"], y=df_bar["推荐"],
                                      marker_color="#4f46e5"))
            fig_bar.add_trace(go.Bar(name="上限", x=df_bar["参数"], y=df_bar["上限"],
                                      marker_color="#7c3aed", opacity=0.5))
            fig_bar.update_layout(
                barmode='overlay',
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#94a3b8'), height=200,
                legend=dict(bgcolor='rgba(0,0,0,0)', font=dict(color='#94a3b8')),
                margin=dict(t=10, b=10, l=40, r=10),
                yaxis=dict(gridcolor='rgba(255,255,255,0.07)'),
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        # ── Warnings ──────────────────────────────────────────────────────
        warnings = sim.get("warnings", [])
        if warnings:
            st.markdown("#### ⚠️ 注意事项")
            for w in warnings:
                st.warning(w)

        # ── Summary text ──────────────────────────────────────────────────
        if sim.get("summary_zh"):
            with st.expander("📄 完整模拟报告", expanded=False):
                st.markdown(sim["summary_zh"])
