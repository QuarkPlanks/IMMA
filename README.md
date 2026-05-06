# 注塑成型 AI 助手 🌟

> **一个现代化、可扩展的注塑成型辅助系统**，集成了 **数据采集、物理模拟、缺陷诊断、RAG 知识库** 与 **大语言模型**，帮助工程师快速获取工艺参数、预判缺陷并提供可解释的调参建议。

---

## 目录

- [项目概览](#项目概览)
- [主要功能](#主要功能)
- [系统架构](#系统架构)
- [快速安装](#快速安装)
- [环境配置 (pip 指令)](#环境配置-pip-指令)
- [`.env` 配置说明](#env-配置说明)
- [数据采集 & 牌号数据库](#数据采集--牌号数据库)
- [构建本地知识库 (RAG)](#构建本地知识库-rag)
- [运行 Streamlit UI](#运行-streamlit-ui)
- [扩展与自定义](#扩展与自定义)
- [API Key 使用安全说明](#api-key-使用安全说明)
- [常见问题 FAQ](#常见问题-faq)
- [许可证](#许可证)

---

## 项目概览

本项目旨在帮助 **注塑成型工程师**：
1. **快速查询材料牌号**（通过网络爬取、Omnexus API、DDG 正则等多层次策略）。
2. **基于物理模型**（热、流变、冷却）进行注塑过程模拟，输出关键工艺指标。
3. **缺陷诊断**：使用经验规则与 AI 对话，给出缺陷原因及调参建议。
4. **增强答案可信度**：通过本地 RAG 知识库（论文、技术手册、TDS）检索专业文献，确保 AI 给出的答案可追溯、可验证。

---

## 主要功能

| 功能 | 说明 |
|------|------|
| **材料牌号查询** | ① MatWeb (Playwright) ② Omnexus API ③ DuckDuckGo + 正则 ④ LLM 估算（标记为 `llm_generated`） |
| **物理模拟** | 注塑热传导、流变、冷却时间、成型周期、锁模力、注射压力等六大关键指标（`src/simulator`） |
| **缺陷诊断** | 通过规则库 + AI 交互，返回缺陷风险雷达图、缺陷列表与调参建议 |
| **RAG 知识库** | 使用 **ChromaDB** 向量存储，Embedding 采用 **BAAI/bge-m3**（多语言），支持中文文献检索 |
| **AI 对话层** | 基于 OpenAI‑compatible 接口（DeepSeek / Qwen / Zhipu），能够在对话中自动调用工具（查询、模拟、RAG） |
| **可视化 UI** | Streamlit 三栏布局 + Plotly 动态图表，暗色渐变 UI，交互流畅 |

---

## 系统架构

```
+-----------------------------------------------------------+
|                       Streamlit 前端                     |
|   ├─ 牌号选择面板  ──► data_collector (爬虫)           |
|   ├─ 模具参数面板  ──► src/knowledge/database.py       |
|   ├─ 对话/目标面板 ──► InjectionMoldingAgent (src/agent) |
|   │            ├─ 调用 tools.search_knowledge_base      |
|   │            ├─ 调用 tools.recommend_initial_params   |
|   │            └─ 调用 tools.run_simulation            |
+-----------------------------------------------------------+
                │                     │
                ▼                     ▼
          src/knowledge               src/simulator
          ├─ rag (ChromaDB)          ├─ thermal.py
          │   ├─ embedder.py          │─ rheology.py
          │   └─ document_store.py    │─ cooling.py
          └─ literature (Semantic Scholar, arXiv, PDF)   
                │
                ▼
          本地向量库 (data/chroma_db) ←‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑‑⁞
```

* **数据流**：用户在 UI 选择材料 → 通过 `data_collector` 抓取并保存 JSON → `InjectionMoldingAgent` 加载并将材料属性、模具参数、目标约束传递给模拟器。*
* **RAG 调用**：当对话中出现需要文献支撑的请求（如公式来源、工艺原理）时，Agent 调用 `search_knowledge_base`，在向量库中检索最相关的片段并返回给 LLM，保证答案带有可靠来源标记。*

---

## 快速安装

> 本项目在 **Python 3.11** 环境下测试通过，推荐使用 `conda` 创建隔离环境。

```bash
# 1️⃣ 创建环境（可自行更改 env 名称）
conda create -n injection_ai python=3.11 -y
conda activate injection_ai

# 2️⃣ 安装系统依赖（Playwright 需要浏览器二进制）
pip install --upgrade pip
pip install streamlit==1.35.0 playwright==1.44.0 ddgs==9.0.0
pip install beautifulsoup4==4.12.0 python-dotenv==1.0.0 requests==2.31.0
pip install numpy==1.26.0 scipy==1.13.0 pandas==2.2.0
pip install plotly==5.22.0 matplotlib==3.9.0 pillow==10.3.0
pip install chromadb==0.5.0 sentence-transformers==3.0.0 pymupdf==1.24.0

# 3️⃣ 安装 Playwright 浏览器（仅一次）
playwright install chromium
```

> **Tip**：如网络受限，请提前配置国内的镜像源（`pip config set global.index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple`）。

---

## 环境配置 (pip 指令)

所有第三方库已经在上一步的 `pip install` 中列出。**不再使用 `requirements.txt`**，直接执行上述指令即可完成全部依赖安装。

---

## `.env` 配置说明

根目录下创建 `.env`（或直接修改 `config.py` 中的默认值）并填写以下字段：

```dotenv
# ---------- LLM（文本） ----------
LLM_API_KEY=your_llm_api_key            # DeepSeek / Qwen / Zhipu 任意兼容模型
LLM_BASE_URL=https://api.deepseek.com    # 根据实际提供商自行修改
LLM_MODEL=deepseek-chat                  # 模型名称（可换为 qwen-turbo、glm-4-flash 等）
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=2048

# ---------- Vision LLM ----------
VISION_API_KEY=${LLM_API_KEY}
VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VISION_MODEL=qwen-vl-max

# ---------- Optional SERPAPI ----------
SERPAPI_KEY=your_serpapi_key   # 如需更精准搜索，可填入

# ---------- RAG Embedding Model ----------
# 多语言模型（中文+英文均可）
EMBEDDING_MODEL=BAAI/bge-m3
```

**安全提示**：请勿把 `.env` 文件提交到公开仓库，可在 `.gitignore` 中添加 `*.env`。

---

## 数据采集 & 牌号数据库

1. **运行爬虫**：在项目根目录执行
   ```bash
   python data_collector/scraper.py --seed
   ```
   - 会使用 **Playwright** 自动登录 MatWeb，绕过 anti‑scraping；
   - 若 MatWeb 失效，将自动回退至 **Omnexus API** 或 **DuckDuckGo + 正则**;
   - 采集到的每个材料牌号保存在 `data/grades/*.json`，字段 `data_source` 标记来源（`matweb`, `omnexus`, `ddg_regex`, `llm_generated`）。

2. **手动补充**：可以直接编辑对应的 JSON，或使用 `search_and_fetch` UI 输入新牌号，系统会即时抓取并存入数据库。

---

## 构建本地知识库 (RAG)

### 一键脚本
```bash
python build_knowledge_base.py
```
脚本流程：
1. **索引 TDS 原始文本**（所有 `data/grades/*.json` 的 `raw_text`） → 作为 `tds` 文档。
2. **索引本地 PDF/MD**（`articles/` 目录下的论文、PolyNC 白皮书等）。
3. **在线检索**：调用 **Semantic Scholar** + **arXiv**，自动下载开放获取的 PDF，解析后分块、向量化并写入 ChromaDB。
4. **统计**：完成后输出总片段数、数据库路径。

### 常用参数
- `--skip-papers`   → 只索引本地 TDS 与 PDF，适用于离线环境。
- `--skip-tds`      → 仅抓取网络论文（如已存在完整 TDS 数据可跳过）。
- `--add-pdf path/to/file.pdf` → 手动添加单个 PDF。
- `--papers-per-query N` → 每个搜索词返回的论文数量（默认 8）。

> **注意**：向量库与模型维度耦合。切换 `EMBEDDING_MODEL` 时，系统会自动生成 **新 collection**（如 `polymer_knowledge_bge_m3`），旧 collection 完好，不会出现维度冲突。

---

## 运行 Streamlit UI
```bash
streamlit run app.py
```
打开浏览器后会看到三栏布局：
1. **牌号选择**（本地或在线搜索）
2. **模具/制品参数**（支持图片解析）
3. **目标与聊天**（可直接输入 "推荐参数"、"诊断缺陷" 或任意查询）

**重要 UI 交互**
- 当材料来源为 `llm_generated` 时，页面会弹出黄色警告，提醒用户该参数为 AI 估算，仅供参考。
- 使用 **RAG 检索**：在聊天框输入需要文献支撑的问句（如 "ABS 的熔体黏度公式依据是什么"），Agent 会自动调用 `search_knowledge_base`，返回最相关的文献片段并在回答中引用。

---

## 扩展与自定义

| 方向 | 操作指南 |
|------|----------|
| **新增仿真模型** | 在 `src/simulator` 目录添加新的热/流变/机械模块，遵循已有 `BaseModule` 接口，并在 `InjectionMoldingAgent` 中注册。 |
| **接入新材料数据库** | 在 `src/knowledge/database.py` 中实现 `search_and_fetch` 的新抓取逻辑（如使用国家标准平台），确保返回与现有 JSON 结构相同。 |
| **替换 Embedding** | 修改 `.env` 中 `EMBEDDING_MODEL`，重新运行 `build_knowledge_base.py`（会自动创建新 collection）。 |
| **自定义工具** | 在 `src/agent/tools.py` 中添加新的 function schema，随后在 `src/agent/agent.py` 的 `_dispatch_tool` 分支实现调用逻辑。 |

---

## API Key 使用安全说明

1. **统一管理**：所有 LLM、Vision、以及（可选）SerpAPI 的密钥统一放在 `.env` 文件中，程序通过 `python‑dotenv` 自动加载。
2. **防泄漏**：代码中不硬编码密钥，调用时使用 `os.getenv`，并在 `README` 中提醒用户 `.gitignore` 包含 `.env`。
3. **RAG 与 API Key**：检索本地向量库不需要网络请求；**仅**在以下情况下会触发外部 API：
   - 使用 LLM 进行对话/参数推荐。
   - 调用 Vision LLM 解析模具图纸。
   - 运行 `search_knowledge_base` 时 **不** 调用外部 API（完全本地），因此即使 API Key 被撤销，已有的知识库仍可离线使用。
4. **失效处理**：如果 LLM API 返回 401/403，系统会在 UI 中弹出错误提示并建议检查 `.env` 中的密钥。

---

## 常见问题 FAQ

- **Q: 为什么第一次运行会下载 570 MB 的模型？**
  - A: `BAAI/bge-m3` 是多语言大模型，提供最佳中文/英文检索效果。模型会在首次使用时自动下载并缓存到用户的 `~/.cache` 目录，后续启动无需再次下载。

- **Q: 知识库构建太慢怎么办？**
  - A: 可使用 `--skip-papers` 只索引本地文档；或调低 `papers_per_query` 参数。

- **Q: 如何在离线机器上使用？**
  - A: 只需要提前在联网机器上执行一次 `build_knowledge_base.py`，将 `data/chroma_db` 目录复制到离线机器即可（所有向量和文档均本地）。

- **Q: 如何更换为纯中文模型？**
  - A: 在 `.env` 中设定 `EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5`，重新跑一次 `build_knowledge_base.py`，系统会自动创建 `polymer_knowledge_bge_small_zh` collection。

---

## 许可证

本项目采用 **MIT License**，详见 `LICENSE` 文件。欢迎大家 Fork、Star、贡献 PR！
