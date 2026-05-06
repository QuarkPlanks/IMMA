"""
config.py — Central configuration for the Injection Molding AI system.
All API keys and model choices are loaded from a .env file or environment variables.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data" / "grades"       # JSON grade files
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ─── LLM (Text) ─────────────────────────────────────────────────────────────
# Recommended free options:
#   DeepSeek: https://platform.deepseek.com  (model: deepseek-chat)
#   Qwen:     https://dashscope.aliyuncs.com (model: qwen-turbo)
#   Zhipu:    https://open.bigmodel.cn       (model: glm-4-flash)
LLM_API_KEY    = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL   = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL      = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = 0.3
LLM_MAX_TOKENS  = 2048

# ─── Vision LLM (for mold drawing analysis) ─────────────────────────────────
# Recommended: Qwen-VL or any vision-capable model via OpenAI-compat API
VISION_API_KEY   = os.getenv("VISION_API_KEY", LLM_API_KEY)
VISION_BASE_URL  = os.getenv("VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
VISION_MODEL     = os.getenv("VISION_MODEL", "qwen-vl-max")

# ─── Web Search ─────────────────────────────────────────────────────────────
# Uses DuckDuckGo (no API key required) as primary; SerpAPI as optional upgrade
SERPAPI_KEY      = os.getenv("SERPAPI_KEY", "")   # optional
MAX_SEARCH_RESULTS = 5

# ─── Application ─────────────────────────────────────────────────────────────
APP_TITLE   = "注塑成型 AI 助手"
APP_VERSION = "1.0.0"
DEBUG       = os.getenv("DEBUG", "false").lower() == "true"

# ─── RAG Embedding Model ─────────────────────────────────────────────────────
# BAAI/bge-m3: 多语言（中英文混合），~570MB，维度1024，推荐
# BAAI/bge-small-zh-v1.5: 纯中文，~95MB，维度512（仅中文文献时选此）
# paraphrase-multilingual-MiniLM-L12-v2: 轻量多语言，~118MB，维度384
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
