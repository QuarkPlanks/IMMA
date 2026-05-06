"""
data_collector/scraper.py  (v2 — Playwright + Omnexus + regex parsing)

数据来源优先级:
  1. Playwright 驱动真实浏览器访问 MatWeb（绕过 Cloudflare 反爬）
  2. Omnexus 内部 REST API（无需登录，返回 JSON）
  3. DuckDuckGo 文本搜索 → 正则提取（不使用 LLM）
  4. 最后兜底：LLM 提取，并打上 data_source="llm_generated" 标记

重要：只有 data_source="llm_generated" 的记录才是 LLM 生成的参数，
      UI 中会显示醒目警告标识。其余来源均为网页实际数据。
"""

import sys, json, re, time, logging, argparse
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data" / "grades"
DATA_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _grade_id(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", name)[:80]

def _load_existing(grade_id: str) -> Optional[dict]:
    p = DATA_DIR / f"{grade_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def _save(data: dict) -> None:
    p = DATA_DIR / f"{data['grade_id']}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("  Saved → %s (source: %s)", p.name, data.get("data_source", "?"))

def _extract_num(text: str) -> Optional[float]:
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(text))
    return float(m.group().replace(",", ".")) if m else None

def _empty_grade(name: str, sources: list, source_tag: str) -> dict:
    return {
        "grade_id":   _grade_id(name),
        "grade_name": name,
        "polymer":    _infer_polymer(name),
        "supplier":   _infer_supplier(name),
        "sources":    sources,
        "data_source": source_tag,
        "processing": {},
        "mechanical": {},
        "thermal":    {},
        "rheology":   {},
        "raw_text":   "",
    }


# ─── Regex-based parameter extraction (NO LLM) ───────────────────────────────

# Patterns: (key, regex, section)
PARAM_PATTERNS = [
    # Melt temperature
    ("melt_temp_min_C", r"(?:melt|processing|barrel|cylinder|熔融|熔体|加工|料筒)\s*(?:temp|temperature|温度)[^0-9]*?(\d{2,3})\s*[-–to至~]+\s*(\d{2,3})", "processing"),
    # Mold temperature
    ("mold_temp_min_C", r"(?:mold|模具|模)\s*(?:temp|temperature|温度)[^0-9]*?(\d{2,3})\s*[-–to至~]+\s*(\d{2,3})", "processing"),
    # Single melt temp (relaxed to 2-3 digits since some polymers melt < 100C)
    ("melt_temp_ref_C", r"(?:melt|processing|熔融|熔体|加工|料筒)\s*(?:temp|temperature|温度)[^0-9]*?(\d{2,3})\s*°?C?", "processing"),
    # Drying temp
    ("drying_temp_C",  r"(?:dry|drying|干燥|烘干)\s*(?:temp|temperature|温度)[^0-9]*?(\d{2,3})\s*°?C?", "processing"),
    # Drying time
    ("drying_time_h",  r"(?:dry|drying|干燥|烘干)\s*(?:time|时间)[^0-9]*?(\d+(?:\.\d+)?)\s*[hH小]", "processing"),
    # Injection pressure
    ("injection_pressure_MPa_max", r"(?:inject|injection|注射|射出)\s*(?:pressure|压力)[^0-9]*?(\d{2,4})\s*(?:MPa|psi|bar|kg)", "processing"),
    # Shrinkage
    ("shrinkage_pct",  r"(?:shrinkage|收缩|成型收缩)[^0-9]*?(\d+(?:\.\d+)?)\s*%", "processing"),
    # Tg
    ("Tg_C",           r"(?:Tg|glass\s*transition|玻璃化|转化)[^0-9]*?(\d{2,3})\s*°?C?", "thermal"),
    # Tm
    ("Tm_C",           r"(?:Tm|melting\s*point|熔点)[^0-9]*?(\d{2,3})\s*°?C?", "thermal"),
    # Density
    ("density_g_cm3",  r"(?:density|密度|比重)[^0-9]*?(\d+\.\d+)", "mechanical"),
    # Thermal conductivity
    ("thermal_conductivity_W_mK", r"(?:thermal\s*conductivity|导热系数|热导率)[^0-9]*?(\d+\.\d+)", "thermal"),
]

RANGE_KEYS = {
    "melt_temp_min_C":  ("melt_temp_min_C",  "melt_temp_max_C"),
    "mold_temp_min_C":  ("mold_temp_min_C",  "mold_temp_max_C"),
}


def extract_params_regex(text: str) -> dict:
    """
    Extract processing parameters using regex only — no LLM.
    Returns dict of {section: {key: value}}.
    """
    text_l = text.lower()
    result: dict = {"processing": {}, "thermal": {}, "mechanical": {}}

    for key, pattern, section in PARAM_PATTERNS:
        m = re.search(pattern, text_l, re.IGNORECASE)
        if not m:
            continue
        groups = m.groups()
        if key in RANGE_KEYS and len(groups) >= 2:
            k_min, k_max = RANGE_KEYS[key]
            v1, v2 = _extract_num(groups[0]), _extract_num(groups[1])
            if v1 and v2:
                result[section][k_min] = min(v1, v2)
                result[section][k_max] = max(v1, v2)
        else:
            v = _extract_num(groups[0])
            if v is not None:
                result[section][key] = v

    return result


# ─── Source 1: Plasway (No Browser, fast API/Regex) ──────────────────────────

def _plasway(grade_name: str) -> Optional[dict]:
    """
    Search Plasway via DDG and extract properties using regex.
    No browser needed, purely automated.
    """
    log.info("  [Plasway] Searching: %s", grade_name)
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            query = f"site:plasway.com/datasheet {grade_name}"
            hits = list(ddgs.text(query, max_results=3))
    except Exception as e:
        log.warning("  [Plasway] Search failed: %s", e)
        return None

    if not hits:
        log.info("  [Plasway] No results found for '%s'", grade_name)
        return None

    target_url = hits[0].get("href", "")
    if not target_url or "plasway.com/datasheet" not in target_url:
        return None

    try:
        r = requests.get(target_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Plasway title usually in h1 or title
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else grade_name

        # Extract all text for regex
        page_text = soup.get_text(" ", strip=True)
        params = extract_params_regex(page_text)

        if not params["processing"]:
            log.info("  [Plasway] No structured data found on page")
            return None

        data = _empty_grade(grade_name, [target_url], "plasway")
        data["grade_name"] = title
        for sec in ("processing", "thermal", "mechanical"):
            data[sec].update(params.get(sec, {}))
        data["raw_text"] = page_text[:4000]

        log.info("  [Plasway] OK: %s", title)
        return data

    except Exception as e:
        log.warning("  [Plasway] Fetch failed: %s", e)
        return None



# ─── Source 2: Omnexus REST API ───────────────────────────────────────────────

OMNEXUS_SEARCH = "https://www.omnexus.com/nc/material-search/results"
OMNEXUS_DETAIL = "https://www.omnexus.com/nc/material-detail/properties"

def _omnexus(grade_name: str) -> Optional[dict]:
    """
    Query Omnexus (SpecialChem) material database via their internal JSON API.
    No login required for basic property data.
    """
    log.info("  [Omnexus] Searching: %s", grade_name)
    try:
        # Step 1: search
        r = requests.get(OMNEXUS_SEARCH, params={"q": grade_name, "lang": "en"},
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        items = r.json() if r.headers.get("Content-Type","").startswith("application") else []
        if isinstance(items, dict):
            items = items.get("results", items.get("materials", []))

        if not items:
            # Try HTML search page as fallback
            r2 = requests.get(
                "https://www.omnexus.com/tc/material-search",
                params={"search_query": grade_name},
                headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r2.text, "html.parser")
            # Grab first material link
            link = soup.select_one("a[href*='/tc/id-']")
            if not link:
                return None
            mat_url = "https://www.omnexus.com" + link["href"]
            r3 = requests.get(mat_url, headers=HEADERS, timeout=15)
            text = BeautifulSoup(r3.text, "html.parser").get_text(" ", strip=True)
            params = extract_params_regex(text)
            if not params["processing"]:
                return None
            data = _empty_grade(grade_name, [mat_url], "omnexus")
            for sec in ("processing", "thermal", "mechanical"):
                data[sec].update(params.get(sec, {}))
            data["raw_text"] = text[:4000]
            log.info("  [Omnexus HTML] Partial data extracted")
            return data

        # Step 2: fetch first result's properties
        mat = items[0]
        mat_id = mat.get("id") or mat.get("uid") or ""
        mat_url = f"https://www.omnexus.com/tc/id-{mat_id}" if mat_id else ""

        if mat_id:
            rp = requests.get(OMNEXUS_DETAIL,
                              params={"id": mat_id, "lang": "en"},
                              headers=HEADERS, timeout=15)
            prop_json = rp.json() if rp.ok else {}
        else:
            prop_json = {}

        data = _empty_grade(grade_name, [mat_url], "omnexus")
        data["grade_name"] = mat.get("name", grade_name)

        # Map Omnexus property names → our canonical keys
        OMNI_MAP = {
            "Melt Flow Index":          ("processing", "mfi_g10min"),
            "Processing Temperature":   ("processing", "melt_temp_ref_C"),
            "Mold Temperature":         ("processing", "mold_temp_ref_C"),
            "Drying Temperature":       ("processing", "drying_temp_C"),
            "Drying Time":              ("processing", "drying_time_h"),
            "Linear Mold Shrinkage":    ("processing", "shrinkage_pct"),
            "Glass Transition Temp":    ("thermal", "Tg_C"),
            "Melting Point":            ("thermal", "Tm_C"),
            "Density":                  ("mechanical", "density_g_cm3"),
            "Thermal Conductivity":     ("thermal", "thermal_conductivity_W_mK"),
            "Specific Heat Capacity":   ("thermal", "Cp_J_kgK"),
        }
        props = prop_json.get("properties", prop_json.get("data", []))
        for prop in props:
            pname = prop.get("name", "")
            for k, (sec, canon) in OMNI_MAP.items():
                if k.lower() in pname.lower():
                    v = _extract_num(prop.get("value", ""))
                    if v is not None:
                        data[sec][canon] = v

        if data["processing"]:
            log.info("  [Omnexus] OK for %s", data["grade_name"])
            return data
        return None

    except Exception as e:
        log.warning("  [Omnexus] Failed: %s", e)
        return None


# ─── Source 3: DuckDuckGo text search → regex (fixed package name) ───────────

def _ddg_regex(grade_name: str) -> Optional[dict]:
    """Search with ddgs and extract parameters via regex (no LLM)."""
    log.info("  [DDG+Regex] Searching: %s", grade_name)
    try:
        from ddgs import DDGS  # NEW package name
        with DDGS() as ddgs:
            hits = list(ddgs.text(
                f"{grade_name} injection molding processing temperature datasheet",
                max_results=8))
    except Exception as e:
        log.warning("  [DDG] Search failed: %s", e)
        return None

    combined = ""
    sources = []
    for h in hits[:4]:
        url = h.get("href", "")
        body = h.get("body", "")
        combined += f"\n{body}"
        # Try to scrape the actual page for more text
        if url:
            try:
                r = requests.get(url, headers=HEADERS, timeout=10)
                page_text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
                combined += "\n" + page_text[:3000]
                sources.append(url)
            except Exception:
                pass
        time.sleep(0.3)

    params = extract_params_regex(combined)
    if not params["processing"]:
        log.info("  [DDG+Regex] No structured data found for '%s'", grade_name)
        return None

    data = _empty_grade(grade_name, sources, "ddg_regex")
    for sec in ("processing", "thermal", "mechanical"):
        data[sec].update(params.get(sec, {}))
    data["raw_text"] = combined[:4000]
    log.info("  [DDG+Regex] Extracted params: %s", list(params["processing"].keys()))
    return data


# ─── Source 4: LLM fallback (marked as llm_generated) ────────────────────────

def _llm_fallback(grade_name: str) -> Optional[dict]:
    """
    Last resort: ask LLM to estimate parameters.
    ALWAYS marks data_source='llm_generated' so the UI can warn the user.
    """
    log.info("  [LLM-fallback] Estimating for: %s", grade_name)
    try:
        from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
        from openai import OpenAI
        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

        polymer = _infer_polymer(grade_name)
        prompt = (
            f"You are a polymer expert. Provide TYPICAL injection molding processing parameters "
            f"for a {polymer} grade similar to '{grade_name}'. "
            f"Base your answer ONLY on general {polymer} industry knowledge, NOT on this specific grade. "
            f"Return JSON only:\n"
            f'{{"melt_temp_min_C":n,"melt_temp_max_C":n,"mold_temp_min_C":n,"mold_temp_max_C":n,'
            f'"drying_temp_C":n,"drying_time_h":n,"injection_pressure_MPa_max":n,'
            f'"shrinkage_pct_min":n,"shrinkage_pct_max":n,"Tg_C":n,"density_g_cm3":n}}'
        )
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0, max_tokens=300,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        extracted = json.loads(raw)
    except Exception as e:
        log.warning("  [LLM-fallback] Failed: %s", e)
        return None

    thermal_keys = {"Tg_C"}
    mechanical_keys = {"density_g_cm3"}
    data = _empty_grade(grade_name, [], "llm_generated")
    data["warning"] = (
        f"⚠ 此牌号的参数由 AI 根据 {_infer_polymer(grade_name)} 行业通用值估算，"
        f"非该牌号实测数据，仅供参考！"
    )
    for k, v in extracted.items():
        if v is None:
            continue
        if k in thermal_keys:
            data["thermal"][k] = v
        elif k in mechanical_keys:
            data["mechanical"][k] = v
        else:
            data["processing"][k] = v

    log.info("  [LLM-fallback] Generated (ESTIMATED) data for '%s'", grade_name)
    return data


# ─── Main public API ──────────────────────────────────────────────────────────

def fetch_grade(grade_name: str, force: bool = False) -> Optional[dict]:
    """
    Fetch and save data for a single grade.
    Tries sources in order; marks data_source on each result.
    """
    gid = _grade_id(grade_name)
    if not force:
        cached = _load_existing(gid)
        if cached:
            log.info("Cache hit: '%s' (source: %s)", grade_name,
                     cached.get("data_source","?"))
            return cached

    data = (_plasway(grade_name)           or
            _omnexus(grade_name)           or
            _ddg_regex(grade_name)         or
            _llm_fallback(grade_name))

    if data:
        data["grade_id"] = gid  # ensure consistent id
        _save(data)
    else:
        log.error("All sources failed for '%s'", grade_name)
    return data


def fetch_batch(names: list, delay: float = 2.0, force: bool = False) -> dict:
    results = {}
    for name in names:
        results[name] = fetch_grade(name, force=force)
        time.sleep(delay)
    return results


# ─── Polymer / supplier inference ────────────────────────────────────────────

POLYMER_KW = {
    "ABS":["ABS","Acrylonitrile"],"PC":["PC","Polycarbonate","Lexan","Makrolon"],
    "PP":["PP","Polypropylene"],"PA6":["PA6","Nylon 6","Nylon6"],
    "PA66":["PA66","PA 66","Nylon 66","Zytel","Ultramid"],
    "POM":["POM","Acetal","Delrin","Hostaform"],"PBT":["PBT","Valox","Celanex"],
    "PET":["PET","Rynite"],"PMMA":["PMMA","Acrylic","Plexiglas"],
    "PS":["PS","Polystyrene","HIPS"],"TPU":["TPU","Elastollan"],
    "PEEK":["PEEK","Victrex"],"PPS":["PPS","Ryton"],
}
SUPPLIER_KW = {
    "SABIC":["Lexan","SABIC"],"Covestro":["Makrolon","Bayblend","Covestro","Bayer"],
    "BASF":["Ultramid","Ultradur","BASF","Ultraform"],
    "DuPont":["Zytel","Rynite","Delrin","DuPont"],"Celanese":["Celanex","Hostaform","Celanese"],
    "Toray":["Toray","Toyolac"],"Chimei":["Chimei","POLYLAC","PA-7"],
}

def _infer_polymer(name: str) -> str:
    for poly, kws in POLYMER_KW.items():
        if any(k.lower() in name.lower() for k in kws):
            return poly
    return "Unknown"

def _infer_supplier(name: str) -> str:
    for supplier, kws in SUPPLIER_KW.items():
        if any(k.lower() in name.lower() for k in kws):
            return supplier
    return "Unknown"


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch plastic grade data.")
    parser.add_argument("grades", nargs="*")
    parser.add_argument("--batch-file", "-f")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    names = list(args.grades)
    if args.batch_file:
        names += [l.strip() for l in open(args.batch_file) if l.strip()]
    if args.seed or not names:
        from seed_data import SEED_GRADES
        names += SEED_GRADES

    print(f"\n=== Fetching {len(names)} grade(s) ===\n")
    fetch_batch(names, force=args.force)
    print(f"\nDone. Files in: {DATA_DIR}")
