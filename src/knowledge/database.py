"""
src/knowledge/database.py
─────────────────────────
Interface to the local grade JSON database in data/grades/*.json.

Public API:
  - list_grades()                   → list of grade dicts (id + name + polymer)
  - get_grade(grade_id)             → full grade dict or None
  - search_grade(query)             → fuzzy search, returns list of candidates
  - get_processing_window(grade_id) → ProcessingWindow
"""

import json
import re
from pathlib import Path
from typing import Optional

import sys
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config import DATA_DIR


# ─────────────────────────────────────────────────────────────────────────────
# Core database functions
# ─────────────────────────────────────────────────────────────────────────────

def list_grades(polymer_filter: Optional[str] = None) -> list[dict]:
    """
    Return summary records for all grades in the database.
    Each record: {grade_id, grade_name, polymer, supplier}
    """
    results = []
    for p in sorted(DATA_DIR.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if polymer_filter and d.get("polymer", "").upper() != polymer_filter.upper():
                continue
            results.append({
                "grade_id":   d.get("grade_id", p.stem),
                "grade_name": d.get("grade_name", p.stem),
                "polymer":    d.get("polymer", "Unknown"),
                "supplier":   d.get("supplier", "Unknown"),
            })
        except Exception:
            pass
    return results


def get_grade(grade_id: str) -> Optional[dict]:
    """Load a full grade dict by grade_id."""
    p = DATA_DIR / f"{grade_id}.json"
    if not p.exists():
        # Try case-insensitive search
        for candidate in DATA_DIR.glob("*.json"):
            if candidate.stem.lower() == grade_id.lower():
                p = candidate
                break
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def search_grade(query: str, top_k: int = 5) -> list[dict]:
    """
    Fuzzy search for grades by name, polymer, or supplier.
    Returns a list of summary records ranked by relevance score.
    """
    query_tokens = set(re.split(r"[\s/\-_]+", query.lower()))
    scored = []

    for p in DATA_DIR.glob("*.json"):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue

        name     = d.get("grade_name", "").lower()
        polymer  = d.get("polymer", "").lower()
        supplier = d.get("supplier", "").lower()
        text     = f"{name} {polymer} {supplier}"

        # Score: count query token hits
        score = sum(1 for t in query_tokens if t and t in text)

        # Boost if exact substring match
        if query.lower() in text:
            score += 3

        if score > 0:
            scored.append((score, {
                "grade_id":   d.get("grade_id", p.stem),
                "grade_name": d.get("grade_name", p.stem),
                "polymer":    d.get("polymer", "Unknown"),
                "supplier":   d.get("supplier", "Unknown"),
                "score":      score,
            }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]


def get_processing_params(grade_id: str) -> Optional[dict]:
    """Return the processing sub-dict for a grade, or None if not found."""
    grade = get_grade(grade_id)
    if grade is None:
        return None
    return grade.get("processing", {})


def get_all_grade_names() -> list[str]:
    """Return all grade_name strings in the database (for UI dropdown)."""
    return [g["grade_name"] for g in list_grades()]


def upsert_grade(data: dict) -> Path:
    """
    Save or overwrite a grade record.
    Used by the scraper and the web-search fallback.
    """
    gid = data.get("grade_id")
    if not gid:
        raise ValueError("grade_id is required")
    p = DATA_DIR / f"{gid}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return p
