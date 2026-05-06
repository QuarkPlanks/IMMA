"""
src/knowledge/literature/searcher.py
──────────────────────────────────────
Search for polymer processing literature from free, legal sources:
  - Semantic Scholar API (comprehensive, free, no key required for basic use)
  - arXiv API (preprints in materials science, polymer physics)
  - CrossRef + Unpaywall (find legal open-access PDFs by DOI)

Rate limiting: both APIs enforce strict 429 limits. We use exponential
backoff + a local JSON cache so repeated runs skip already-known papers.
"""

import json
import re
import time
import logging
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "InjectionMoldingAI/1.0 (academic research; contact: user@example.com)"
}

# ── Local paper cache ─────────────────────────────────────────────────────────
# Stores titles of papers already indexed, so re-runs skip them instantly.
_ROOT = Path(__file__).parent.parent.parent.parent
_CACHE_FILE = _ROOT / "data" / "literature" / "indexed_papers.json"


def _load_cache() -> set[str]:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _CACHE_FILE.exists():
        try:
            return set(json.loads(_CACHE_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def _save_cache(seen: set[str]) -> None:
    _CACHE_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _title_key(title: str) -> str:
    return re.sub(r"\W+", "", title.lower())[:60]


# ── HTTP helper with retry / back-off ─────────────────────────────────────────

def _get_with_retry(url: str, params: dict, timeout: int = 15,
                    retries: int = 3, backoff: float = 5.0):
    """
    GET request with exponential back-off for 429 / timeout errors.
    Returns requests.Response or raises on final failure.
    """
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 429:
                wait = backoff * (2 ** attempt)
                log.warning("429 rate-limited by %s, waiting %.0fs …", url.split("/")[2], wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            wait = backoff * (2 ** attempt)
            log.warning("Timeout from %s, waiting %.0fs …", url.split("/")[2], wait)
            time.sleep(wait)
        except Exception as e:
            log.warning("HTTP error (%s): %s", url[:60], e)
            return None
    log.warning("Giving up on %s after %d attempts.", url[:60], retries)
    return None


# ─── Semantic Scholar ─────────────────────────────────────────────────────────

SS_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
SS_FIELDS = "title,authors,year,abstract,openAccessPdf,externalIds"

INJECTION_MOLDING_QUERIES = [
    "injection molding processing parameters polymer",
    "polymer melt rheology viscosity temperature",
    "cooling time injection molding heat transfer",
    "polymer crystallization injection molding",
    "polypropylene polyamide injection molding defects",
    "ABS PC polymer injection molding optimization",
    "polymer flow simulation filling pressure",
    "warpage sink marks injection molding defects",
    "polymer thermal properties processing window",
    "injection molding weld lines flow front",
]


def search_semantic_scholar(
    query: str,
    limit: int = 10,
    year_min: int = 2000,
) -> list[dict]:
    """
    Search Semantic Scholar and return paper metadata list.
    Each result: {title, abstract, year, doi, pdf_url, authors}
    """
    r = _get_with_retry(SS_SEARCH,
                        params={"query": query, "limit": limit, "fields": SS_FIELDS})
    if r is None:
        return []

    try:
        data = r.json()
    except Exception:
        log.warning("Semantic Scholar: invalid JSON response")
        return []

    results = []
    for p in data.get("data", []):
        year = p.get("year") or 0
        if year and year < year_min:
            continue
        pdf_url = None
        oa = p.get("openAccessPdf")
        if oa:
            pdf_url = oa.get("url")
        doi = (p.get("externalIds") or {}).get("DOI")
        results.append({
            "title":    p.get("title", ""),
            "abstract": p.get("abstract", ""),
            "year":     year,
            "doi":      doi,
            "pdf_url":  pdf_url,
            "authors":  [a.get("name", "") for a in (p.get("authors") or [])[:3]],
            "source_db": "semantic_scholar",
        })

    log.info("Semantic Scholar: %d results for '%s'", len(results), query[:50])
    return results


# ─── arXiv ───────────────────────────────────────────────────────────────────

def _elem_text(elem) -> str:
    """Safely extract .text from an XML element (returns '' if elem is None)."""
    if elem is None:
        return ""
    return (elem.text or "").strip()


def search_arxiv(query: str, max_results: int = 8) -> list[dict]:
    """
    Search arXiv for polymer/materials science preprints.
    Returns list of {title, abstract, year, pdf_url, authors}
    """
    # arXiv uses http (redirects to https on some endpoints)
    base = "https://export.arxiv.org/api/query"
    r = _get_with_retry(base,
                        params={
                            "search_query": f"all:{query}",
                            "max_results":  max_results,
                            "sortBy":       "relevance",
                        },
                        timeout=20)
    if r is None:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        log.warning("arXiv XML parse error: %s", e)
        return []

    results = []
    for entry in root.findall("atom:entry", ns):
        title     = _elem_text(entry.find("atom:title", ns)).replace("\n", " ")
        abstract  = _elem_text(entry.find("atom:summary", ns))[:500]
        published = _elem_text(entry.find("atom:published", ns))
        year      = int(published[:4]) if published and len(published) >= 4 else 0

        pdf_url = None
        for link in entry.findall("atom:link", ns):
            if link.get("title") == "pdf":
                pdf_url = link.get("href")
                break

        authors = [
            _elem_text(a.find("atom:name", ns))
            for a in entry.findall("atom:author", ns)[:3]
        ]

        if not title:
            continue  # skip malformed entries

        results.append({
            "title":    title,
            "abstract": abstract,
            "year":     year,
            "doi":      None,
            "pdf_url":  pdf_url,
            "authors":  authors,
            "source_db": "arxiv",
        })

    log.info("arXiv: %d results for '%s'", len(results), query[:50])
    return results


# ─── Unpaywall ───────────────────────────────────────────────────────────────

def find_open_access_pdf(doi: str, email: str = "user@example.com") -> Optional[str]:
    """
    Use Unpaywall to find a legal open-access PDF URL for a DOI.
    """
    if not doi:
        return None
    try:
        r = requests.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": email},
            headers=HEADERS,
            timeout=10,
        )
        if not r.ok:
            return None
        data = r.json()
        best = data.get("best_oa_location") or {}
        return best.get("url_for_pdf") or best.get("url")
    except Exception:
        return None


# ─── Main collector ───────────────────────────────────────────────────────────

def collect_papers(
    queries: list[str] | None = None,
    papers_per_query: int = 8,
) -> list[dict]:
    """
    Run all queries, collect unique papers with accessible PDFs.
    Skips papers whose title keys are already in the local cache
    (data/literature/indexed_papers.json) so re-runs don't waste time.

    Returns list of paper dicts that have a pdf_url.
    """
    queries = queries or INJECTION_MOLDING_QUERIES
    cached_keys = _load_cache()
    seen_titles: set[str] = set(cached_keys)
    new_cache_keys: set[str] = set()
    papers = []

    for i, q in enumerate(queries):
        log.info("[%d/%d] Searching: %s", i + 1, len(queries), q)

        results: list[dict] = []
        try:
            results += search_semantic_scholar(q, limit=papers_per_query)
        except Exception as e:
            log.warning("Semantic Scholar query failed: %s", e)

        time.sleep(1.0)  # polite gap between SS and arXiv

        try:
            results += search_arxiv(q, max_results=4)
        except Exception as e:
            log.warning("arXiv query failed: %s", e)

        for p in results:
            if not p.get("title"):
                continue
            key = _title_key(p["title"])
            if key in seen_titles:
                log.debug("  Already indexed, skipping: %s", p["title"][:60])
                continue
            seen_titles.add(key)

            # Try to find PDF if not already available
            if not p.get("pdf_url") and p.get("doi"):
                p["pdf_url"] = find_open_access_pdf(p["doi"])

            if p.get("pdf_url"):
                papers.append(p)
                new_cache_keys.add(key)

        # Polite gap between query rounds
        time.sleep(2.0)

    # Persist newly discovered papers to cache
    if new_cache_keys:
        _save_cache(cached_keys | new_cache_keys)
        log.info("Cache updated: %d new papers recorded.", len(new_cache_keys))

    log.info("Collected %d papers with accessible PDFs.", len(papers))
    return papers
