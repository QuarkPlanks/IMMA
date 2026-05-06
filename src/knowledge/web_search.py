"""
src/knowledge/web_search.py
────────────────────────────
Online fallback: when a grade is not found in the local database,
search the web and extract parameters via the LLM.

Steps:
  1. DuckDuckGo search for grade TDS / datasheet
  2. Scrape top-3 URLs
  3. Send combined text to LLM for structured extraction
  4. Save result to local database
"""

import sys
import json
import time
import logging
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, MAX_SEARCH_RESULTS

log = logging.getLogger(__name__)


def search_and_fetch(grade_name: str, save: bool = True) -> Optional[dict]:
    """
    Search for grade data online, extract via LLM, optionally save.
    Returns grade dict or None.
    """
    # Delegate to the data_collector scraper which has the full pipeline
    try:
        import importlib.util, os
        scraper_path = ROOT_DIR / "data_collector" / "scraper.py"
        spec = importlib.util.spec_from_file_location("scraper", scraper_path)
        scraper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scraper)
        return scraper.fetch_grade(grade_name, force=False)
    except Exception as e:
        log.warning("web_search fallback failed: %s", e)
        return None


def enrich_grade_with_llm(grade_id: str, question: str) -> str:
    """
    Ask the LLM a domain-specific question about a grade and
    return a plain-text answer (not structured extraction).
    Useful for properties not in the database.
    """
    try:
        from openai import OpenAI
        from .database import get_grade
        grade = get_grade(grade_id) or {}
        grade_text = json.dumps(grade, ensure_ascii=False, indent=2)[:3000]

        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": (
                    "你是一位注塑成型专家。以下是某塑料牌号的已知数据（JSON），"
                    "请根据该数据和你的专业知识回答用户的问题。"
                    "如果数据中没有相关信息，请基于该聚合物类型的行业常识给出合理估计，"
                    "并注明这是估计值。"
                )},
                {"role": "user", "content": f"牌号数据:\n{grade_text}\n\n问题: {question}"},
            ],
            temperature=0.3,
            max_tokens=512,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"查询失败: {e}"
